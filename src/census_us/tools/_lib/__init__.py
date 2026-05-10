"""Real implementation for the census-us pipeline.

Each module here is a pure-function library that the CLIs in
``src/census_us/tools/*.py`` and the FFL handlers in
``src/census_us/handlers/`` both call into via the
``handlers/shared/census_utils.py`` shim.

Modules:

- ``downloader``     — Census ACS REST + TIGER/Line shapefile HTTP downloads with on-disk caching
- ``acs_extractor``  — parse ACS API responses into per-state per-variable rows
- ``tiger_extractor``— parse TIGER shapefiles into county GeoJSON features
- ``db_ingest``      — MongoDB upsert helpers for `census_acs_*`, `census_tiger_*` (lazy-imports ``pymongo``)
- ``summary_builder``— per-state rollups + join census variables to TIGER county geometry
"""
