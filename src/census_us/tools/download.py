#!/usr/bin/env python3
"""download — download ACS demographics or a TIGER/Line shapefile.

Both kinds write into the same on-disk cache the FFL handlers use
(`$FW_DATA_ROOT/cache/census-us/...`), so subsequent extracts reuse
what this CLI fetched.
"""

from __future__ import annotations

import argparse
import json
import sys

from census_us.tools._lib.downloader import download_acs, download_tiger


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument("--kind", required=True, choices=["acs", "tiger"], help="Which dataset to download")
    p.add_argument("--year", default=None, help="Vintage year (default: 2023 for ACS, 2024 for TIGER)")
    p.add_argument("--state-fips", default="01", help="State FIPS code (default: 01 / Alabama)")
    p.add_argument("--period", default="5-Year", help="ACS period: 5-Year or 1-Year (acs only)")
    p.add_argument(
        "--columns",
        default=None,
        help="Comma-separated ACS variable IDs (acs only; default: a 12-table starter pack)",
    )
    p.add_argument("--geo-level", default="COUNTY", help="TIGER geography level (tiger only; default: COUNTY)")
    args = p.parse_args()

    if args.kind == "acs":
        kwargs = {"state_fips": args.state_fips, "period": args.period}
        if args.year:
            kwargs["year"] = args.year
        if args.columns:
            kwargs["columns"] = args.columns
        print(f"DownloadACS: state={args.state_fips} period={args.period}", file=sys.stderr)
        result = download_acs(**kwargs)
    else:
        kwargs = {"state_fips": args.state_fips, "geo_level": args.geo_level}
        if args.year:
            kwargs["year"] = args.year
        print(f"DownloadTIGER: state={args.state_fips} layer={args.geo_level}", file=sys.stderr)
        result = download_tiger(**kwargs)

    json.dump(result, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
