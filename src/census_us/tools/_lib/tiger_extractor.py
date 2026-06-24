"""TIGER/Line shapefile extraction.

Reads shapefiles from downloaded TIGER ZIP archives and writes
GeoJSON output filtered by state FIPS code.
"""

import json
import logging
import os
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from census_us.tools._lib import storage as cstore

logger = logging.getLogger(__name__)

try:
    import fiona

    HAS_FIONA = True
except ImportError:
    HAS_FIONA = False

try:
    import shapefile  # pyshp

    HAS_PYSHP = True
except ImportError:
    HAS_PYSHP = False

# Geography level → TIGER file component and FIPS field name
_GEO_CONFIG: dict[str, dict[str, str | None]] = {
    "COUNTY": {"suffix": "county", "fips_field": "STATEFP"},
    # STATE: national file, no per-state filter (keep all 50 states + DC).
    "STATE": {"suffix": "state", "fips_field": None},
    "TRACT": {"suffix": "tract", "fips_field": "STATEFP"},
    "BG": {"suffix": "bg", "fips_field": "STATEFP"},
    "PLACE": {"suffix": "place", "fips_field": "STATEFP"},
}


def _match(props: dict, fips_field: str | None, state_fips: str) -> bool:
    """Keep a feature: no filter when fips_field is None (e.g. STATE), else the
    feature's state FIPS must equal state_fips."""
    return fips_field is None or props.get(fips_field) == state_fips



@dataclass
class TIGERExtractionResult:
    """Result of a TIGER shapefile extraction."""

    output_path: str
    feature_count: int
    geography_level: str
    year: str
    format: str = "GeoJSON"
    extraction_date: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


def extract_tiger(
    zip_path: str, geo_level: str, state_fips: str, year: str = "2024"
) -> TIGERExtractionResult:
    """Extract features from a TIGER/Line shapefile ZIP.

    Args:
        zip_path: Path to downloaded TIGER ZIP file.
        geo_level: Geography level (COUNTY, TRACT, BG, PLACE).
        state_fips: Two-digit state FIPS code.
        year: TIGER year.

    Returns:
        TIGERExtractionResult with output path and feature count.
    """
    geo_upper = geo_level.upper()
    config = _GEO_CONFIG.get(geo_upper)
    if config is None:
        raise ValueError(
            f"Unsupported geo_level: {geo_level}. Supported: {list(_GEO_CONFIG.keys())}"
        )

    output_path = cstore.join(
        cstore.output_root(), "tiger", geo_upper.lower(), f"{state_fips}_{geo_upper.lower()}.geojson"
    )

    features: list[dict[str, Any]] = []

    # The shapefile readers (fiona/pyshp/zipfile) need a real local file, so pull
    # the cached ZIP down from the backend (no-op when it's already local).
    zip_exists = cstore.exists(zip_path)
    local_zip = cstore.localize(zip_path) if zip_exists else zip_path

    if HAS_FIONA and zip_exists:
        try:
            with fiona.open(f"zip://{local_zip}") as src:
                for feature in src:
                    props = feature.get("properties", {})
                    if _match(props, config["fips_field"], state_fips):
                        features.append(
                            {
                                "type": "Feature",
                                "properties": dict(props),
                                "geometry": dict(feature["geometry"]),
                            }
                        )
        except Exception as exc:
            logger.warning("Failed to read TIGER ZIP %s: %s", zip_path, exc)
    elif HAS_PYSHP and zip_exists:
        try:
            reader = shapefile.Reader(local_zip)
            for sr in reader.shapeRecords():
                props = sr.record.as_dict()
                if _match(props, config["fips_field"], state_fips):
                    geo = sr.shape.__geo_interface__
                    if geo.get("type") != "Null":
                        features.append(
                            {
                                "type": "Feature",
                                "properties": props,
                                "geometry": geo,
                            }
                        )
        except Exception as exc:
            logger.warning("Failed to read TIGER ZIP %s with pyshp: %s", zip_path, exc)
    elif zip_exists:
        # Fallback: try to find .geojson inside ZIP
        try:
            with zipfile.ZipFile(local_zip, "r") as zf:
                geojson_names = [n for n in zf.namelist() if n.endswith(".geojson")]
                for name in geojson_names:
                    with zf.open(name) as f:
                        data = json.load(f)
                        for feat in data.get("features", []):
                            props = feat.get("properties", {})
                            if _match(props, config["fips_field"], state_fips):
                                features.append(feat)
        except (zipfile.BadZipFile, json.JSONDecodeError) as exc:
            logger.warning("Failed to read TIGER ZIP %s: %s", zip_path, exc)

    # Write GeoJSON output
    geojson = {
        "type": "FeatureCollection",
        "features": features,
    }
    with cstore.open_write(output_path, "w") as f:
        json.dump(geojson, f)

    logger.info(
        "Extracted %d features for %s (state=%s, level=%s)",
        len(features),
        geo_upper,
        state_fips,
        geo_level,
    )

    return TIGERExtractionResult(
        output_path=output_path,
        feature_count=len(features),
        geography_level=geo_level,
        year=year,
    )
