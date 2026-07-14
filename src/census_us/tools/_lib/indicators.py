"""External county-indicator sources: County Health Rankings + HUD PIT.

These fill national county metrics no ACS table carries:

- **Homicides** (``chr_homicide``) — CHR 2025 measure v015: CDC NVSS death
  records, deaths per 100,000, pooled over multiple years to reduce
  small-county suppression (still ~1/3 of counties suppressed → None).
- **Violent crime** (``chr_violent_crime``) — CHR 2022 measure v043: FBI UCR
  offenses per 100,000, 2014/2016 data — the LAST comparable national county
  series (agency reporting broke in the UCR→NIBRS transition).
- **Jobless time series** — CHR trends "Unemployment rate": BLS-derived annual
  county unemployment 2002-2022 (fraction → percent).
- **Homeless time series** — HUD Point-in-Time "Overall Homeless" by
  Continuum of Care (one sheet per year, 2007+), apportioned to counties by
  each county's population share of its CoC (Byrne HUD-CoC crosswalk), as a
  rate per 10,000 residents. An explicit APPROXIMATION: CoCs are not county
  aggregates, the crosswalk is 2017-vintage, and the population denominator
  is current-ACS. Labeled as such on the map.

Every fetch caches the raw file under cache/indicators/ (cstore-backed) and
each normalizer writes a CSV shaped like the ACS downloader's output
(GEOID "0500000US<fips>", NAME, value columns) so the map builders can merge
them exactly like ACS files. Parsers are separated from fetchers so tests run
offline on synthetic files.
"""

from __future__ import annotations

import csv
import logging
import re
from datetime import UTC, datetime
from typing import Any

try:
    import requests

    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

from census_us.tools._lib import storage as cstore

logger = logging.getLogger(__name__)

CHR_BASE = "https://www.countyhealthrankings.org/sites/default/files/media/document"
CHR_HOMICIDE_URL = f"{CHR_BASE}/analytic_data2025_v2.csv"  # v015
CHR_CRIME_URL = f"{CHR_BASE}/analytic_data2022.csv"  # v043 (last release with it)
CHR_TRENDS_URL = f"{CHR_BASE}/chr_trends_csv_2024.csv"  # Unemployment rate 2002-2022
PIT_URL = "https://www.huduser.gov/portal/sites/default/files/xls/2007-2024-PIT-Counts-by-CoC.xlsb"
COC_XWALK_URL = (
    "https://raw.githubusercontent.com/tomhbyrne/HUD-CoC-Geography-Crosswalk/"
    "master/output/county_coc_match.csv"
)

# huduser.gov sits behind a bot filter that serves an HTML challenge to
# default client UAs; a browser UA gets the real file.
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept": "*/*",
}

_COC_RE = re.compile(r"^[A-Z]{2}-\d{3}$")


def _fetch(url: str, dest: str, *, browser: bool = False, min_bytes: int = 10000) -> str:
    """Download url → cstore dest (cache-first). Returns the dest path."""
    if cstore.exists(dest) and cstore.size(dest) >= min_bytes:
        logger.info("indicator cache hit: %s", dest)
        return dest
    if not HAS_REQUESTS:
        raise RuntimeError("requests library required for downloads")
    logger.info("Fetching %s -> %s", url, dest)
    resp = requests.get(
        url, timeout=300, stream=True, headers=_BROWSER_HEADERS if browser else None
    )
    resp.raise_for_status()
    size = 0
    with cstore.open_write(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=65536):
            f.write(chunk)
            size += len(chunk)
    if size < min_bytes:
        raise RuntimeError(
            f"Suspiciously small download ({size}B) from {url} — likely a bot-challenge page"
        )
    return dest


def _file_info(path: str, url: str, was_cached: bool) -> dict[str, Any]:
    return {
        "url": url,
        "path": path,
        "date": datetime.now(UTC).isoformat(),
        "size": cstore.size(path),
        "wasInCache": was_cached,
    }


# ---------------------------------------------------------------------------
# County Health Rankings — homicide + violent crime snapshot indicators.
# ---------------------------------------------------------------------------


def parse_chr_measure(path: str, measure_col: str) -> dict[str, tuple[float, str]]:
    """{5-digit fips: (rawvalue, "County, ST")} from a CHR analytic CSV.

    Row 1 is human-readable headers, row 2 machine names — DictReader keys on
    row 1's cells only if we skip it, so read via the machine-name row.
    """
    out: dict[str, tuple[float, str]] = {}
    with cstore.open_read(path, newline="") as f:
        reader = csv.reader(f)
        next(reader)  # human header
        machine = next(reader)
        idx = {c: i for i, c in enumerate(machine)}
        for col in ("fipscode", "county", "state", "countycode"):
            if col not in idx:
                raise ValueError(f"CHR file missing column {col}")
        if measure_col not in idx:
            raise ValueError(f"CHR file missing measure column {measure_col}")
        for row in reader:
            if len(row) <= idx[measure_col]:
                continue
            if (row[idx["countycode"]] or "000") == "000":
                continue  # US + state rows
            fips = (row[idx["fipscode"]] or "").zfill(5)
            try:
                val = float(row[idx[measure_col]])
            except (TypeError, ValueError):
                continue
            name = f"{row[idx['county']]}, {row[idx['state']]}"
            out[fips] = (round(val, 1), name)
    return out


def build_chr_indicators_csv() -> dict[str, Any]:
    """Fetch CHR releases and write the normalized homicide+crime CSV."""
    cache = cstore.join(cstore.cache_root(), "indicators")
    homicide_raw = _fetch(CHR_HOMICIDE_URL, cstore.join(cache, "chr_analytic_2025.csv"))
    crime_raw = _fetch(CHR_CRIME_URL, cstore.join(cache, "chr_analytic_2022.csv"))
    homicide = parse_chr_measure(homicide_raw, "v015_rawvalue")
    crime = parse_chr_measure(crime_raw, "v043_rawvalue")

    dest = cstore.join(cache, "chr_indicators.csv")
    all_fips = sorted(set(homicide) | set(crime))
    with cstore.open_write(dest, "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["GEOID", "NAME", "chr_homicide", "chr_violent_crime"])
        for fips in all_fips:
            name = (homicide.get(fips) or crime.get(fips))[1]
            wr.writerow([
                f"0500000US{fips}", name,
                homicide[fips][0] if fips in homicide else "",
                crime[fips][0] if fips in crime else "",
            ])
    logger.info(
        "CHR indicators: %d counties (homicide %d, crime %d) -> %s",
        len(all_fips), len(homicide), len(crime), dest,
    )
    return _file_info(dest, CHR_HOMICIDE_URL, False)


# ---------------------------------------------------------------------------
# County Health Rankings trends — annual county unemployment 2002-2022.
# ---------------------------------------------------------------------------


def parse_chr_jobless_trends(path: str) -> dict[str, dict[int, float]]:
    """{fips: {year: pct}} from the CHR trends CSV ("Unemployment rate")."""
    out: dict[str, dict[int, float]] = {}
    with cstore.open_read(path, newline="") as f:
        for row in csv.DictReader(f):
            if row.get("measurename") != "Unemployment rate":
                continue
            county = (row.get("countycode") or "000").strip()
            state = (row.get("statecode") or "00").strip()
            if county == "000" or state == "00":
                continue
            try:
                year = int((row.get("yearspan") or "").strip())
                val = float(row.get("rawvalue", "").replace(",", "").strip('"'))
            except (TypeError, ValueError):
                continue
            out.setdefault(state.zfill(2) + county.zfill(3), {})[year] = round(val * 100, 2)
    return out


def build_chr_jobless_ts_csv() -> dict[str, Any]:
    """Fetch the CHR trends CSV and write the wide jobless time-series CSV."""
    cache = cstore.join(cstore.cache_root(), "indicators")
    raw = _fetch(CHR_TRENDS_URL, cstore.join(cache, "chr_trends_2024.csv"), min_bytes=1000000)
    series = parse_chr_jobless_trends(raw)
    years = sorted({y for by_year in series.values() for y in by_year})
    dest = cstore.join(cache, "chr_jobless_ts.csv")
    with cstore.open_write(dest, "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["GEOID", "NAME"] + [f"y{y}" for y in years])
        for fips in sorted(series):
            wr.writerow(
                [f"0500000US{fips}", ""]
                + [series[fips].get(y, "") for y in years]
            )
    logger.info("CHR jobless trends: %d counties x %d years -> %s", len(series), len(years), dest)
    return _file_info(dest, CHR_TRENDS_URL, False)


# ---------------------------------------------------------------------------
# HUD PIT — homeless per 10k residents, apportioned CoC → county.
# ---------------------------------------------------------------------------


def parse_coc_crosswalk(path: str) -> dict[str, list[tuple[str, float]]]:
    """{fips: [(coc_number, pct_of_county_pop_in_coc 0..1), …]}."""
    out: dict[str, list[tuple[str, float]]] = {}
    # cp1252 bytes in CoC names ("Prince George's") — decode accordingly.
    local = cstore.localize(path)
    with open(local, newline="", encoding="cp1252") as f:
        for row in csv.DictReader(f):
            fips = (row.get("county_fips") or "").zfill(5)
            coc = (row.get("coc_number") or "").strip()
            if len(fips) != 5 or not _COC_RE.match(coc):
                continue
            try:
                pct = float(row.get("pct_cnty_pop_coc") or 0) / 100.0
            except (TypeError, ValueError):
                continue
            if pct > 0:
                out.setdefault(fips, []).append((coc, pct))
    return out


def parse_pit_workbook(path: str) -> dict[int, dict[str, float]]:
    """{year: {coc_number: overall homeless}} from the PIT xlsb workbook."""
    from pyxlsb import open_workbook

    local = cstore.localize(path)
    out: dict[int, dict[str, float]] = {}
    with open_workbook(local) as wb:
        for sheet in wb.sheets:
            if not (sheet.isdigit() and 2007 <= int(sheet) <= 2100):
                continue
            year = int(sheet)
            with wb.get_sheet(sheet) as ws:
                coc_i = overall_i = None
                header_tries = 0
                for row in ws.rows():
                    vals = [c.v for c in row]
                    if coc_i is None or overall_i is None:
                        # scan the first rows for the header (usually row 1)
                        header_tries += 1
                        if header_tries > 5:
                            break
                        header = [str(v or "").strip() for v in vals]
                        for i, h in enumerate(header):
                            if h == "CoC Number":
                                coc_i = i
                            # "Overall Homeless" or "Overall Homeless, <year>"
                            if h in ("Overall Homeless", f"Overall Homeless, {year}"):
                                overall_i = i
                        continue
                    coc = str(vals[coc_i] or "").strip() if len(vals) > coc_i else ""
                    if not _COC_RE.match(coc):
                        continue
                    try:
                        out.setdefault(year, {})[coc] = float(vals[overall_i])
                    except (TypeError, ValueError, IndexError):
                        continue
    return out


def apportion_homeless(
    pit: dict[int, dict[str, float]],
    xwalk: dict[str, list[tuple[str, float]]],
    county_pop: dict[str, float],
) -> dict[str, dict[int, float]]:
    """{fips: {year: rate per 10k}} — CoC totals split by county pop share."""
    # county share of each CoC's population
    coc_pop: dict[str, float] = {}
    for fips, links in xwalk.items():
        pop = county_pop.get(fips)
        if not pop:
            continue
        for coc, pct in links:
            coc_pop[coc] = coc_pop.get(coc, 0.0) + pop * pct
    out: dict[str, dict[int, float]] = {}
    for fips, links in xwalk.items():
        pop = county_pop.get(fips)
        if not pop:
            continue
        for year, totals in pit.items():
            homeless = 0.0
            seen = False
            for coc, pct in links:
                total = totals.get(coc)
                if total is None or not coc_pop.get(coc):
                    continue
                homeless += total * (pop * pct) / coc_pop[coc]
                seen = True
            if seen:
                out.setdefault(fips, {})[year] = round(homeless / pop * 10000, 2)
    return out


def build_homeless_ts_csv(acs_path: str) -> dict[str, Any]:
    """Fetch PIT + crosswalk, apportion, and write the wide homeless CSV.

    ``acs_path`` is a national county ACS pull carrying B01003_001E (total
    population) — the apportionment weight and the rate denominator.
    """
    cache = cstore.join(cstore.cache_root(), "indicators")
    pit_raw = _fetch(
        PIT_URL, cstore.join(cache, "pit_counts_by_coc.xlsb"),
        browser=True, min_bytes=1000000,
    )
    xwalk_raw = _fetch(COC_XWALK_URL, cstore.join(cache, "county_coc_match.csv"))

    county_pop: dict[str, float] = {}
    with cstore.open_read(acs_path, newline="") as f:
        for row in csv.DictReader(f):
            fips = (row.get("GEOID", "") or "").rsplit("US", 1)[-1]
            try:
                pop = float(row.get("B01003_001E", ""))
            except (TypeError, ValueError):
                continue
            if len(fips) == 5 and pop > 0:
                county_pop[fips] = pop

    pit = parse_pit_workbook(pit_raw)
    xwalk = parse_coc_crosswalk(xwalk_raw)
    rates = apportion_homeless(pit, xwalk, county_pop)
    years = sorted({y for by_year in rates.values() for y in by_year})

    dest = cstore.join(cache, "hud_homeless_ts.csv")
    with cstore.open_write(dest, "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["GEOID", "NAME"] + [f"y{y}" for y in years])
        for fips in sorted(rates):
            wr.writerow(
                [f"0500000US{fips}", ""]
                + [rates[fips].get(y, "") for y in years]
            )
    logger.info(
        "HUD homeless: %d CoC-years, %d counties x %d years -> %s",
        sum(len(v) for v in pit.values()), len(rates), len(years), dest,
    )
    return _file_info(dest, PIT_URL, False)
