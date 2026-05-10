#!/usr/bin/env bash
# Shell wrapper for acs_extract.py — see python file for argparse help.
exec python3 "$(dirname "$0")/acs_extract.py" "$@"
