#!/usr/bin/env bash
# Shell wrapper for join_geo.py — see python file for argparse help.
exec python3 "$(dirname "$0")/join_geo.py" "$@"
