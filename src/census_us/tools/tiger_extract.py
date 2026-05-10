#!/usr/bin/env python3
"""tiger-extract — parse a TIGER/Line shapefile ZIP into GeoJSON features.

The ZIP is what ``download.sh --kind tiger`` writes (or what the
``census.Operations.DownloadTIGER`` handler caches). This CLI unpacks
the shapefile and emits county / tract / block-group geometry as
GeoJSON-ready dicts.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys

from census_us.tools._lib.tiger_extractor import extract_tiger


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument("--zip", required=True, dest="zip_path", help="Path to a TIGER/Line .zip (from download.sh --kind tiger)")
    p.add_argument("--state-fips", required=True, help="State FIPS code (e.g. 06 for California)")
    p.add_argument("--geo-level", default="COUNTY", help="COUNTY / TRACT / BG (default: COUNTY)")
    p.add_argument("--year", default="2024", help="Vintage year (default: 2024)")
    args = p.parse_args()

    print(
        f"TIGERExtract: state={args.state_fips} geo={args.geo_level} year={args.year}",
        file=sys.stderr,
    )
    result = extract_tiger(
        zip_path=args.zip_path,
        geo_level=args.geo_level,
        state_fips=args.state_fips,
        year=args.year,
    )
    out = dataclasses.asdict(result) if dataclasses.is_dataclass(result) else result
    json.dump(out, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
