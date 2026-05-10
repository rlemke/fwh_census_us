#!/usr/bin/env bash
# Shell wrapper for download.py — see python file for argparse help.
exec python3 "$(dirname "$0")/download.py" "$@"
