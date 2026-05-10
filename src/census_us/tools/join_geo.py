#!/usr/bin/env python3
"""join-geo — join an ACS extraction to TIGER county geometry.

Produces a single GeoJSON-style FeatureCollection where each county
polygon carries the ACS variable values as properties. This is the
input to a choropleth map (the dashboard renders these directly).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys

from census_us.tools._lib.summary_builder import join_geo


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument("--acs-path", required=True, help="Path to a JSON ACS extraction (from acs-extract.sh)")
    p.add_argument("--tiger-path", required=True, help="Path to a JSON TIGER extraction (from tiger-extract.sh)")
    p.add_argument(
        "--join-field",
        default="GEOID",
        help="Field used to align ACS rows to TIGER features (default: GEOID)",
    )
    p.add_argument(
        "--extra-acs",
        default=None,
        help="Comma-separated paths to additional ACS extractions to merge in (e.g. income + education + housing)",
    )
    args = p.parse_args()

    extras = [s.strip() for s in args.extra_acs.split(",")] if args.extra_acs else None
    print(
        f"JoinGeo: acs={args.acs_path} tiger={args.tiger_path} join={args.join_field}"
        + (f" extras={len(extras)}" if extras else ""),
        file=sys.stderr,
    )
    result = join_geo(
        acs_path=args.acs_path,
        tiger_path=args.tiger_path,
        join_field=args.join_field,
        extra_acs_paths=extras,
    )
    out = dataclasses.asdict(result) if dataclasses.is_dataclass(result) else result
    json.dump(out, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
