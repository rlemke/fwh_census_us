"""ACS data extraction from Census Bureau API downloads.

Reads CSV data produced by the Census API downloader and extracts columns
for specific tables (e.g. B01003 for population, B19013 for income).
"""

import csv
import logging
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from census_us.tools._lib import storage as cstore

logger = logging.getLogger(__name__)

# ACS table ID -> human-readable label and estimate columns
ACS_TABLES: dict[str, dict] = {
    "B01003": {"label": "Total Population", "columns": ["B01003_001E"]},
    "B19013": {"label": "Median Household Income", "columns": ["B19013_001E"]},
    "B25001": {"label": "Housing Units", "columns": ["B25001_001E"]},
    "B15003": {
        "label": "Educational Attainment",
        # Full attainment ladder: _001 total, _002-016 < high school, _017-018
        # HS diploma/GED, _019-021 some college/associate, _022 bachelor's,
        # _023-025 master's/professional/doctorate. Needed for less-than-HS,
        # HS-only, no-bachelor's, and graduate-degree metrics.
        "columns": [f"B15003_{i:03d}E" for i in range(1, 26)],
    },
    "B08301": {
        "label": "Means of Transportation",
        "columns": ["B08301_001E", "B08301_003E", "B08301_010E", "B08301_019E", "B08301_021E"],
    },
    "B25003": {
        "label": "Housing Tenure",
        "columns": ["B25003_001E", "B25003_002E", "B25003_003E"],
    },
    "B11001": {
        "label": "Household Type",
        "columns": [
            "B11001_001E",
            "B11001_002E",
            "B11001_003E",
            "B11001_004E",
            "B11001_005E",
            "B11001_006E",
            "B11001_007E",
            "B11001_008E",
            "B11001_009E",
        ],
    },
    "B01001": {
        "label": "Sex by Age",
        "columns": [f"B01001_{i:03d}E" for i in range(1, 50)],
    },
    "B25044": {
        "label": "Vehicles Available",
        "columns": [
            "B25044_001E",
            "B25044_002E",
            "B25044_003E",
            "B25044_004E",
            "B25044_005E",
            "B25044_006E",
            "B25044_007E",
            "B25044_008E",
            "B25044_009E",
            "B25044_010E",
            "B25044_011E",
            "B25044_012E",
            "B25044_013E",
            "B25044_014E",
            "B25044_015E",
        ],
    },
    "B02001": {
        "label": "Race",
        "columns": [
            "B02001_001E",
            "B02001_002E",
            "B02001_003E",
            "B02001_004E",
            "B02001_005E",
            "B02001_006E",
            "B02001_007E",
            "B02001_008E",
        ],
    },
    "B17001": {
        "label": "Poverty Status",
        "columns": ["B17001_001E", "B17001_002E"],
    },
    "B23025": {
        "label": "Employment Status",
        "columns": [
            "B23025_001E",
            "B23025_002E",
            "B23025_003E",
            "B23025_004E",
            "B23025_005E",
            "B23025_006E",
            "B23025_007E",
        ],
    },
    "B19083": {
        "label": "Gini Index of Income Inequality",
        "columns": ["B19083_001E"],
    },
    "B19058": {
        "label": "Public Assistance / SNAP",
        "columns": ["B19058_001E", "B19058_002E", "B19058_003E"],
    },
    "B27001": {
        "label": "Health Insurance Coverage",
        # _001 total + the 18 "No health insurance coverage" cells (male+female,
        # all age bands) → uninsured rate. The full table is 57 cols; we keep
        # only the total + the no-coverage cells the uninsured metric needs.
        "columns": ["B27001_001E"]
        + [
            "B27001_005E", "B27001_008E", "B27001_011E", "B27001_014E",
            "B27001_017E", "B27001_020E", "B27001_023E", "B27001_026E",
            "B27001_029E", "B27001_033E", "B27001_036E", "B27001_039E",
            "B27001_042E", "B27001_045E", "B27001_048E", "B27001_051E",
            "B27001_054E", "B27001_057E",
        ],
    },
}

@dataclass
class ACSExtractionResult:
    """Result of an ACS table extraction."""

    table_id: str
    output_path: str
    record_count: int
    geography_level: str
    year: str
    extraction_date: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


def extract_acs_table(
    csv_path: str, table_id: str, state_fips: str, geo_level: str = "county", year: str = "2023"
) -> ACSExtractionResult:
    """Extract a specific ACS table from a downloaded CSV file.

    The CSV is produced by the Census API downloader with columns:
    GEOID, NAME, B01003_001E, B19013_001E, etc.

    Args:
        csv_path: Path to downloaded ACS CSV file.
        table_id: ACS table ID (e.g. "B01003").
        state_fips: Two-digit state FIPS code.
        geo_level: Geography level (county, tract, etc.).
        year: Survey year.

    Returns:
        ACSExtractionResult with output path and record count.
    """
    table_info = ACS_TABLES.get(table_id)
    if table_info is None:
        raise ValueError(f"Unknown ACS table: {table_id}. Supported: {list(ACS_TABLES.keys())}")

    target_cols = table_info["columns"]
    output_path = cstore.join(
        cstore.output_root(), "acs", table_id.lower(), f"{state_fips}_{geo_level}_{table_id}.csv"
    )

    records: list[dict[str, Any]] = []

    if cstore.exists(csv_path):
        try:
            with cstore.open_read(csv_path, newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    geoid = row.get("GEOID", "")
                    if not geoid.startswith(f"0500000US{state_fips}"):
                        continue
                    # Check that at least one target column has a value
                    values = {c: row.get(c, "") for c in target_cols}
                    if any(values.values()):
                        record: dict[str, Any] = {"GEOID": geoid, "NAME": row.get("NAME", "")}
                        record.update(values)
                        records.append(record)
        except (OSError, csv.Error) as exc:
            logger.warning("Failed to read ACS CSV %s: %s", csv_path, exc)

    # Write output CSV
    with cstore.open_write(output_path, "w", newline="") as f:
        fieldnames = ["GEOID", "NAME"] + target_cols
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)

    logger.info(
        "Extracted %d records for %s (state=%s, level=%s)",
        len(records),
        table_id,
        state_fips,
        geo_level,
    )

    return ACSExtractionResult(
        table_id=table_id,
        output_path=output_path,
        record_count=len(records),
        geography_level=geo_level,
        year=year,
    )
