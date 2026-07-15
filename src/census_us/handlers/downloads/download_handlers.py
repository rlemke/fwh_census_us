"""Event facet handlers for Census data downloads.

Handles DownloadACS and DownloadTIGER event facets by delegating
to the shared downloader module.
"""

import os
from typing import Any

from ..shared.census_utils import (
    ACS_TABLES,
    build_chr_indicators_csv,
    build_chr_jobless_ts_csv,
    build_chr_measure_series_csv,
    build_cancer_mortality_csv,
    build_drug_overdose_ts_csv,
    build_heart_disease_ts_csv,
    build_suicide_ts_csv,
    build_homeless_ts_csv,
    build_unauthorized_ts_csv,
    download_acs,
    download_tiger,
)

NAMESPACE = "census.Operations"

# Tables that ride the separate "social" batch (the default batch is already
# near the API's 50-variable cap). Full B15003 ladder + Gini + SNAP + insurance.
_SOCIAL_TABLES = ["B15003", "B19083", "B19058", "B27001"]
# Demographic-context batch: race/ethnicity (B03002) + nativity / foreign-born
# (B05002) + geographic mobility / recent movers (B07003). 12 vars — its own
# request since the default batch is already ~44 vars.
_DEMOGRAPHIC_TABLES = ["B03002", "B05002", "B07003"]


def handle_download_acs(params: dict[str, Any]) -> dict[str, Any]:
    """Download ACS summary file for a state.

    Params:
        year: ACS survey year (default "2023")
        period: Survey period (default "5-Year")
        state_fips: Two-digit FIPS code
    """
    year = params.get("year", "2023")
    period = params.get("period", "5-Year")
    state_fips = params["state_fips"]
    step_log = params.get("_step_log")

    try:
        result = download_acs(year=year, period=period, state_fips=state_fips)

        source = "cache" if result["wasInCache"] else "download"
        if step_log:
            step_log(f"DownloadACS: state={state_fips} year={year} ({source})", level="success")

        return {"file": result}
    except Exception as exc:
        if step_log:
            step_log(f"DownloadACS: {exc}", level="error")
        raise


def handle_download_tiger(params: dict[str, Any]) -> dict[str, Any]:
    """Download TIGER/Line shapefile for a state.

    Params:
        year: TIGER year (default "2024")
        geo_level: Geography level (COUNTY, TRACT, BG, PLACE)
        state_fips: Two-digit FIPS code
    """
    year = params.get("year", "2024")
    geo_level = params.get("geo_level", "COUNTY")
    state_fips = params["state_fips"]
    step_log = params.get("_step_log")

    try:
        result = download_tiger(year=year, geo_level=geo_level, state_fips=state_fips)

        source = "cache" if result["wasInCache"] else "download"
        if step_log:
            step_log(
                f"DownloadTIGER: state={state_fips} level={geo_level} ({source})", level="success"
            )

        return {"file": result}
    except Exception as exc:
        if step_log:
            step_log(f"DownloadTIGER: {exc}", level="error")
        raise


def handle_download_acs_detailed(params: dict[str, Any]) -> dict[str, Any]:
    """Download ACS detailed (B01001 Sex by Age) file for a state.

    B01001 has 49 columns which exceeds the API limit when combined
    with the standard download, so it uses a separate request.

    Params:
        state_fips: Two-digit FIPS code
    """
    state_fips = params["state_fips"]
    step_log = params.get("_step_log")

    # B01001 Sex by Age: 49 columns (001E through 049E)
    columns = ",".join(f"B01001_{i:03d}E" for i in range(1, 50))

    try:
        result = download_acs(
            state_fips=state_fips,
            columns=columns,
            tag="detailed",
        )

        source = "cache" if result["wasInCache"] else "download"
        if step_log:
            step_log(f"DownloadACSDetailed: state={state_fips} ({source})", level="success")

        return {"file": result}
    except Exception as exc:
        if step_log:
            step_log(f"DownloadACSDetailed: {exc}", level="error")
        raise


def handle_download_acs_social(params: dict[str, Any]) -> dict[str, Any]:
    """Download the 'social' ACS batch for a state's counties.

    Full B15003 education ladder + Gini (B19083) + SNAP/public assistance
    (B19058) + health insurance (B27001) — the columns the education, Gini,
    SNAP, and uninsured metrics need. A separate request because the default
    batch is already near the API's 50-variable cap.

    Params:
        state_fips: Two-digit FIPS code
    """
    state_fips = params["state_fips"]
    step_log = params.get("_step_log")

    cols: list[str] = []
    for t in _SOCIAL_TABLES:
        cols.extend(ACS_TABLES[t]["columns"])
    columns = ",".join(cols)

    try:
        result = download_acs(state_fips=state_fips, columns=columns, tag="social")
        source = "cache" if result["wasInCache"] else "download"
        if step_log:
            step_log(
                f"DownloadACSSocial: state={state_fips} ({len(cols)} vars, {source})",
                level="success",
            )
        return {"file": result}
    except Exception as exc:
        if step_log:
            step_log(f"DownloadACSSocial: {exc}", level="error")
        raise


def handle_download_acs_demographics(params: dict[str, Any]) -> dict[str, Any]:
    """Download the 'demographics' ACS batch for a state's counties.

    Race/ethnicity (B03002) + nativity (B05002) + geographic mobility (B07003)
    — the columns the race, foreign-born, and recent-movers metrics need. A
    separate request because the default batch is already near the 50-var cap.

    Params:
        state_fips: Two-digit FIPS code
    """
    state_fips = params["state_fips"]
    step_log = params.get("_step_log")

    cols: list[str] = []
    for t in _DEMOGRAPHIC_TABLES:
        cols.extend(ACS_TABLES[t]["columns"])
    columns = ",".join(cols)

    try:
        result = download_acs(state_fips=state_fips, columns=columns, tag="demographics")
        source = "cache" if result["wasInCache"] else "download"
        if step_log:
            step_log(
                f"DownloadACSDemographics: state={state_fips} ({len(cols)} vars, {source})",
                level="success",
            )
        return {"file": result}
    except Exception as exc:
        if step_log:
            step_log(f"DownloadACSDemographics: {exc}", level="error")
        raise


def handle_download_chr(params: dict[str, Any]) -> dict[str, Any]:
    """Fetch County Health Rankings sources and emit two normalized CSVs.

    Returns indicators_file (chr_homicide + chr_violent_crime per county) and
    jobless_ts_file (annual county unemployment 2002-2022, wide y#### form).
    """
    step_log = params.get("_step_log")
    try:
        indicators_file = build_chr_indicators_csv()
        jobless_ts_file = build_chr_jobless_ts_csv()
        if step_log:
            step_log(
                f"DownloadCHR: indicators {indicators_file['size']}B, "
                f"jobless trends {jobless_ts_file['size']}B",
                level="success",
            )
        return {"indicators_file": indicators_file, "jobless_ts_file": jobless_ts_file}
    except Exception as exc:
        if step_log:
            step_log(f"DownloadCHR: {exc}", level="error")
        raise


def handle_download_chr_series(params: dict[str, Any]) -> dict[str, Any]:
    """One CHR measure across every annual release -> wide time CSV.

    Params: measure — "obesity" (v011, releases 2010-2025, frames ~2007-2022)
    or "life_expectancy" (v147, releases 2019-2025, frames ~2016-2022).
    Frame labels are the approximate DATA year (release - 3).
    """
    measure = params.get("measure", "") or ""
    step_log = params.get("_step_log")
    if not measure:
        raise ValueError("DownloadCHRSeries requires measure")
    try:
        ts_file = build_chr_measure_series_csv(measure)
        if step_log:
            step_log(f"DownloadCHRSeries: {measure} -> {ts_file['size']}B", level="success")
        return {"ts_file": ts_file}
    except Exception as exc:
        if step_log:
            step_log(f"DownloadCHRSeries: {exc}", level="error")
        raise


def handle_download_heart_disease_ts(params: dict[str, Any]) -> dict[str, Any]:
    """CDC heart-disease mortality trends (annual county rates 1999-2019,
    age-standardized + spatiotemporally smoothed, per 100k) -> wide time CSV.

    Params: topic ("All heart disease" default; also CVD/CHD/Heart failure/
    All stroke), age ("Ages 35-64 years" default, or "Ages 65 years and older").
    """
    topic = params.get("topic", "All heart disease") or "All heart disease"
    age = params.get("age", "Ages 35-64 years") or "Ages 35-64 years"
    step_log = params.get("_step_log")
    try:
        ts_file = build_heart_disease_ts_csv(topic=topic, age=age)
        if step_log:
            step_log(f"DownloadHeartDiseaseTS: {topic}/{age} -> {ts_file['size']}B", level="success")
        return {"ts_file": ts_file}
    except Exception as exc:
        if step_log:
            step_log(f"DownloadHeartDiseaseTS: {exc}", level="error")
        raise


def handle_download_cancer_mortality(params: dict[str, Any]) -> dict[str, Any]:
    """NCI State Cancer Profiles all-site county cancer death rates (latest
    5-year window) -> normalized indicator CSV (snapshot)."""
    step_log = params.get("_step_log")
    try:
        indicators_file = build_cancer_mortality_csv()
        if step_log:
            step_log(f"DownloadCancerMortality: {indicators_file['size']}B", level="success")
        return {"indicators_file": indicators_file}
    except Exception as exc:
        if step_log:
            step_log(f"DownloadCancerMortality: {exc}", level="error")
        raise


def handle_download_drug_overdose_ts(params: dict[str, Any]) -> dict[str, Any]:
    """NCHS model-based county drug-poisoning death rates (annual 2003-2021)
    -> wide time CSV."""
    step_log = params.get("_step_log")
    try:
        ts_file = build_drug_overdose_ts_csv()
        if step_log:
            step_log(f"DownloadDrugOverdoseTS: {ts_file['size']}B", level="success")
        return {"ts_file": ts_file}
    except Exception as exc:
        if step_log:
            step_log(f"DownloadDrugOverdoseTS: {exc}", level="error")
        raise


def handle_download_suicide_ts(params: dict[str, Any]) -> dict[str, Any]:
    """CDC injury-surveillance county suicide rates (annual 2019-2024)
    -> wide time CSV."""
    step_log = params.get("_step_log")
    try:
        ts_file = build_suicide_ts_csv()
        if step_log:
            step_log(f"DownloadSuicideTS: {ts_file['size']}B", level="success")
        return {"ts_file": ts_file}
    except Exception as exc:
        if step_log:
            step_log(f"DownloadSuicideTS: {exc}", level="error")
        raise


def handle_download_unauthorized_ts(params: dict[str, Any]) -> dict[str, Any]:
    """Pew unauthorized-immigrant population by STATE (1990-2023 vintages)
    -> wide state-level time CSV."""
    step_log = params.get("_step_log")
    try:
        ts_file = build_unauthorized_ts_csv()
        if step_log:
            step_log(f"DownloadUnauthorizedTS: {ts_file['size']}B", level="success")
        return {"ts_file": ts_file}
    except Exception as exc:
        if step_log:
            step_log(f"DownloadUnauthorizedTS: {exc}", level="error")
        raise


def handle_download_homeless_ts(params: dict[str, Any]) -> dict[str, Any]:
    """HUD PIT CoC counts + CoC-county crosswalk -> homeless per-10k wide CSV.

    Params: acs_file — a national county ACS pull carrying B01003_001E (the
    apportionment weight + rate denominator).
    """
    acs_file = params.get("acs_file")
    acs_path = acs_file.get("path", "") if isinstance(acs_file, dict) else ""
    step_log = params.get("_step_log")
    if not acs_path:
        raise ValueError("DownloadHomelessTS requires acs_file (national ACS pull)")
    try:
        ts_file = build_homeless_ts_csv(acs_path)
        if step_log:
            step_log(f"DownloadHomelessTS: {ts_file['size']}B wide CSV", level="success")
        return {"ts_file": ts_file}
    except Exception as exc:
        if step_log:
            step_log(f"DownloadHomelessTS: {exc}", level="error")
        raise


# RegistryRunner dispatch adapter
_DISPATCH: dict[str, Any] = {
    f"{NAMESPACE}.DownloadACS": handle_download_acs,
    f"{NAMESPACE}.DownloadTIGER": handle_download_tiger,
    f"{NAMESPACE}.DownloadACSDetailed": handle_download_acs_detailed,
    f"{NAMESPACE}.DownloadACSSocial": handle_download_acs_social,
    f"{NAMESPACE}.DownloadACSDemographics": handle_download_acs_demographics,
    f"{NAMESPACE}.DownloadCHR": handle_download_chr,
    f"{NAMESPACE}.DownloadCHRSeries": handle_download_chr_series,
    f"{NAMESPACE}.DownloadHeartDiseaseTS": handle_download_heart_disease_ts,
    f"{NAMESPACE}.DownloadCancerMortality": handle_download_cancer_mortality,
    f"{NAMESPACE}.DownloadDrugOverdoseTS": handle_download_drug_overdose_ts,
    f"{NAMESPACE}.DownloadSuicideTS": handle_download_suicide_ts,
    f"{NAMESPACE}.DownloadUnauthorizedTS": handle_download_unauthorized_ts,
    f"{NAMESPACE}.DownloadHomelessTS": handle_download_homeless_ts,
}


def handle(payload: dict) -> dict:
    """RegistryRunner dispatch entrypoint."""
    facet_name = payload["_facet_name"]
    handler = _DISPATCH.get(facet_name)
    if handler is None:
        raise ValueError(f"Unknown facet: {facet_name}")
    return handler(payload)


def register_handlers(runner) -> None:
    """Register all facets with a RegistryRunner."""
    for facet_name in _DISPATCH:
        runner.register_handler(
            facet_name=facet_name,
            module_uri=f"file://{os.path.abspath(__file__)}",
            entrypoint="handle",
        )


def register_download_handlers(poller) -> None:
    """Register all download handlers with the poller."""
    for facet_name, handler in _DISPATCH.items():
        poller.register(facet_name, handler)
