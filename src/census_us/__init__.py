"""US Census example package — Facetwork workflows + handlers for
American Community Survey (ACS) demographics, TIGER/Line county
shapefiles, MongoDB ingestion, and per-state summary generation.

Discovered by the Facetwork runner via the ``facetwork.examples`` entry
point declared in ``pyproject.toml``::

    [project.entry-points."facetwork.examples"]
    census-us = "census_us:example"

Once ``pip install -e .`` has been run from this repository, Facetwork's
``scripts/start-runner --example census-us`` and
``scripts/seed-examples`` will pick this package up automatically — no
edits to the Facetwork repository required.
"""

from __future__ import annotations

from pathlib import Path

from facetwork.examples import ExamplePackage

from .handlers import register_all_registry_handlers

example = ExamplePackage(
    name="census-us",
    ffl_dir=Path(__file__).parent / "ffl",
    register_handlers=register_all_registry_handlers,
)
