"""Event facet handlers for TIGER/Line shapefile extraction.

Handles ExtractCounties, ExtractTracts, ExtractBlockGroups, and
ExtractPlaces event facets.
"""

import os
from typing import Any

from ..shared.census_utils import extract_tiger

NAMESPACE = "census.TIGER"

# Facet name → TIGER geo_level
_FACET_GEO_MAP = {
    "ExtractCounties": "COUNTY",
    "ExtractTracts": "TRACT",
    "ExtractBlockGroups": "BG",
    "ExtractPlaces": "PLACE",
}


def _make_tiger_handler(facet_name: str, geo_level: str):
    """Create a handler for a TIGER extraction event facet."""

    def handler(params: dict[str, Any]) -> dict[str, Any]:
        file_info = params.get("file", {})
        zip_path = file_info.get("path", "")
        state_fips = params.get("state_fips", "")
        step_log = params.get("_step_log")

        try:
            result = extract_tiger(
                zip_path=zip_path,
                geo_level=geo_level,
                state_fips=state_fips,
            )

            if step_log:
                step_log(
                    f"{facet_name}: {result.feature_count} features "
                    f"(state={state_fips}, level={geo_level})",
                    level="success",
                )

            return {
                "result": {
                    "output_path": result.output_path,
                    "feature_count": result.feature_count,
                    "geography_level": result.geography_level,
                    "year": result.year,
                    "format": result.format,
                    "extraction_date": result.extraction_date,
                }
            }
        except Exception as exc:
            if step_log:
                step_log(f"{facet_name}: {exc}", level="error")
            raise

    return handler


# Build handlers for each facet
_HANDLERS = {
    facet: _make_tiger_handler(facet, geo_level) for facet, geo_level in _FACET_GEO_MAP.items()
}

# RegistryRunner dispatch adapter
_DISPATCH: dict[str, Any] = {
    f"{NAMESPACE}.{facet}": handler for facet, handler in _HANDLERS.items()
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


def register_tiger_handlers(poller) -> None:
    """Register all TIGER extraction handlers with the poller."""
    for facet_name, handler in _DISPATCH.items():
        poller.register(facet_name, handler)
