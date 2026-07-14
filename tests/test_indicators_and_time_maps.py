"""Offline tests for the external county indicators (CHR/HUD parsers) and the
national county time map builder. Fetchers are not exercised — parsers take
local synthetic files."""

from __future__ import annotations

import csv
import json
import re
import zipfile

import pytest
import shapefile

from census_us.tools._lib import indicators
from census_us.tools._lib.maps import (
    build_national_county_time_map,
    wide_csv_values,
)


@pytest.fixture
def out_env(tmp_path, monkeypatch):
    monkeypatch.setenv("FW_CENSUS_OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setenv("FW_CENSUS_CACHE_DIR", str(tmp_path / "cache"))
    return tmp_path


def _county_zip(path, counties):
    base = path.with_suffix("")
    w = shapefile.Writer(str(base))
    w.field("STATEFP", "C", size=2)
    w.field("COUNTYFP", "C", size=3)
    w.field("GEOID", "C", size=5)
    w.field("NAME", "C", size=100)
    w.field("NAMELSAD", "C", size=100)
    for st, cty, name, lon, lat in counties:
        w.record(st, cty, f"{st}{cty}", name, f"{name} County")
        w.poly([[(lon, lat), (lon + 1, lat), (lon + 1, lat + 1), (lon, lat + 1), (lon, lat)]])
    w.close()
    with zipfile.ZipFile(path, "w") as zf:
        for ext in ("shp", "shx", "dbf"):
            zf.write(f"{base}.{ext}", f"{base.name}.{ext}")
    return str(path)


class TestCHRParsers:
    def test_parse_chr_measure(self, tmp_path):
        p = tmp_path / "chr.csv"
        with open(p, "w", newline="") as f:
            wr = csv.writer(f)
            wr.writerow(["State FIPS", "County FIPS", "FIPS", "State", "County", "V15"])
            wr.writerow(["statecode", "countycode", "fipscode", "state", "county", "v015_rawvalue"])
            wr.writerow(["00", "000", "00000", "US", "United States", "6.0"])  # national row
            wr.writerow(["01", "000", "01000", "AL", "Alabama", "12.0"])  # state row
            wr.writerow(["01", "001", "01001", "AL", "Autauga County", "8.13"])
            wr.writerow(["01", "003", "01003", "AL", "Baldwin County", ""])  # suppressed
        out = indicators.parse_chr_measure(str(p), "v015_rawvalue")
        assert out == {"01001": (8.1, "Autauga County, AL")}

    def test_parse_chr_jobless_trends(self, tmp_path):
        p = tmp_path / "trends.csv"
        with open(p, "w", newline="") as f:
            wr = csv.writer(f)
            wr.writerow(["yearspan", "measurename", "statecode", "countycode",
                         "county", "state", "numerator", "denominator", "rawvalue"])
            wr.writerow(["2002", "Unemployment rate", "06", "001", "Alameda County", "CA", "", "", "0.07"])
            wr.writerow(["2003", "Unemployment rate", "06", "001", "Alameda County", "CA", "", "", "0.065"])
            wr.writerow(["2002", "Unemployment rate", "00", "000", "United States", "US", "", "", "0.06"])
            wr.writerow(["2002", "Premature death", "06", "001", "Alameda County", "CA", "", "", "5000"])
        out = indicators.parse_chr_jobless_trends(str(p))
        assert out == {"06001": {2002: 7.0, 2003: 6.5}}


class TestHomelessApportionment:
    def test_apportion_split_coc(self):
        # One CoC covering two counties 100%, one county split 50/50 with another CoC.
        pit = {2024: {"XX-500": 1000.0, "XX-501": 300.0}}
        xwalk = {
            "01001": [("XX-500", 1.0)],
            "01003": [("XX-500", 0.5), ("XX-501", 0.5)],
            "01005": [("XX-501", 1.0)],
        }
        pop = {"01001": 10000.0, "01003": 20000.0, "01005": 5000.0}
        out = indicators.apportion_homeless(pit, xwalk, pop)
        # XX-500 pop = 10000 + 10000 = 20000; XX-501 pop = 10000 + 5000 = 15000
        assert out["01001"][2024] == pytest.approx(1000 * (10000 / 20000) / 10000 * 10000)
        expected_01003 = 1000 * (10000 / 20000) + 300 * (10000 / 15000)
        assert out["01003"][2024] == pytest.approx(round(expected_01003 / 20000 * 10000, 2))
        assert out["01005"][2024] == pytest.approx(round(300 * (5000 / 15000) / 5000 * 10000, 2))

    def test_crosswalk_parser_cp1252(self, tmp_path):
        p = tmp_path / "xw.csv"
        raw = (
            b'county_fips,coc_number,coc_name,pct_cnty_pop_coc\n'
            b'"01001","AL-504","Prince George\x92s CoC","100"\n'
            b'"01003","AL-504","x","0"\n'
        )
        p.write_bytes(raw)
        out = indicators.parse_coc_crosswalk(str(p))
        assert out == {"01001": [("AL-504", 1.0)]}


class TestTimeMap:
    def test_build_time_map(self, out_env, tmp_path):
        tiger = _county_zip(
            tmp_path / "tc.zip",
            [("01", "001", "Autauga", -86.6, 32.5), ("06", "001", "Alameda", -122.3, 37.7)],
        )
        values = {
            2010: {"01001": 40000.0, "06001": 70000.0},
            2023: {"01001": 58000.0, "06001": 112000.0},
        }
        res = build_national_county_time_map(
            tiger, "median_income", values, title="Income over time", region="t-income"
        )
        assert res.valued_count == 2
        with open(res.html_path) as f:
            html = f.read()
        assert "yslider" in html and 'id="play"' in html
        years = json.loads(re.search(r"YEARS=(\[[^\]]*\])", html).group(1))
        assert years == [2010, 2023]
        with open(res.output_path) as f:
            fc = json.load(f)
        props = {ft["properties"]["GEOID"]: ft["properties"] for ft in fc["features"]}
        assert props["01001"]["y2010"] == 40000.0
        assert props["01001"]["y2023"] == 58000.0
        assert "cx" in props["01001"] and "cy" in props["01001"]
        # TIGER-derived display name carries the state
        assert props["06001"]["NAME"] == "Alameda County, California"

    def test_wide_csv_roundtrip(self, tmp_path):
        p = tmp_path / "wide.csv"
        with open(p, "w", newline="") as f:
            wr = csv.writer(f)
            wr.writerow(["GEOID", "NAME", "y2007", "y2024"])
            wr.writerow(["0500000US06075", "", "68.19", "99.52"])
            wr.writerow(["0500000US06001", "", "", "57.21"])
        vals = wide_csv_values(str(p))
        assert vals[2007]["06075"] == 68.19
        assert vals[2007]["06001"] is None
        assert vals[2024]["06001"] == 57.21

    def test_empty_years_raises(self, out_env, tmp_path):
        tiger = _county_zip(tmp_path / "t2.zip", [("01", "001", "A", -86.6, 32.5)])
        with pytest.raises(ValueError, match="No yearly values"):
            build_national_county_time_map(tiger, "median_income", {}, title="x", region="r")
