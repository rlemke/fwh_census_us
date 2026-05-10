#!/usr/bin/env bash
# Shell wrapper for tiger_extract.py — see python file for argparse help.
exec python3 "$(dirname "$0")/tiger_extract.py" "$@"
