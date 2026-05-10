#!/usr/bin/env python3
"""acs-extract — extract a specific ACS table from a downloaded CSV.

The CSV is the file produced by ``download.sh --kind acs`` (or by the
FFL ``census.Operations.DownloadACS`` handler — they share a cache).
This CLI parses that CSV and pulls out the rows for the named ACS
table (e.g. ``B01003`` for total population, ``B19013`` for median
household income).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys

from census_us.tools._lib.acs_extractor import ACS_TABLES, extract_acs_table


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument("--csv", required=True, help="Path to the downloaded ACS CSV (from download.sh --kind acs)")
    p.add_argument(
        "--table",
        required=True,
        help=f"ACS table ID. Known tables: {', '.join(sorted(ACS_TABLES.keys()))}",
    )
    p.add_argument("--state-fips", required=True, help="State FIPS code (e.g. 06 for California)")
    p.add_argument("--geo-level", default="county", help="county / tract / block_group (default: county)")
    p.add_argument("--year", default="2023", help="Vintage year (default: 2023)")
    args = p.parse_args()

    if args.table not in ACS_TABLES:
        print(
            f"acs-extract: warning — table '{args.table}' not in the known ACS_TABLES catalog; proceeding anyway",
            file=sys.stderr,
        )

    print(
        f"ACSExtract: table={args.table} state={args.state_fips} geo={args.geo_level} year={args.year}",
        file=sys.stderr,
    )
    result = extract_acs_table(
        csv_path=args.csv,
        table_id=args.table,
        state_fips=args.state_fips,
        geo_level=args.geo_level,
        year=args.year,
    )
    out = dataclasses.asdict(result) if dataclasses.is_dataclass(result) else result
    json.dump(out, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
