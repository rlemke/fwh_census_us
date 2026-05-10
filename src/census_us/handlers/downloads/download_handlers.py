"""Event facet handlers for Census data downloads.

Handles DownloadACS and DownloadTIGER event facets by delegating
to the shared downloader module.
"""

import os
from typing import Any

from ..shared.census_utils import download_acs, download_tiger

NAMESPACE = "census.Operations"


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


# RegistryRunner dispatch adapter
_DISPATCH: dict[str, Any] = {
    f"{NAMESPACE}.DownloadACS": handle_download_acs,
    f"{NAMESPACE}.DownloadTIGER": handle_download_tiger,
    f"{NAMESPACE}.DownloadACSDetailed": handle_download_acs_detailed,
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
