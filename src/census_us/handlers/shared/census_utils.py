"""Handler-side compatibility shim for the census-us pipeline.

The real implementation lives in ``census_us.tools._lib``. It is shared
verbatim by:

- the ``download`` / ``acs-extract`` / ``tiger-extract`` /
  ``ingest-to-db`` / ``summarize-state`` / ``join-geo`` CLI tools
  (``src/census_us/tools/``), and
- the FFL downloads / acs / tiger / ingestion / summary handlers (this
  package's siblings).

Both entry points read and write the same on-disk cache
(``$AFL_DATA_ROOT/cache/census-us/...``) — the tool and the FFL are
two surfaces onto one extraction.

Imports use the fully-qualified ``census_us.tools._lib.<name>`` path so
this package coexists cleanly with sibling Facetwork example packages
(osm-geocoder, noaa-weather, jenkins, osm-lz) that also ship their own
``tools/_lib/`` directory — there is no fight for the bare ``_lib``
name on ``sys.modules``.
"""

from __future__ import annotations

# Module-level re-exports for handlers that need the full module surface.
from census_us.tools._lib import (  # noqa: F401
    acs_extractor,
    db_ingest,
    downloader,
    maps,
    metrics,
    summary_builder,
    svi,
    tiger_extractor,
)
from census_us.tools._lib.maps import (  # noqa: F401
    build_metrics_map,
    build_national_rankings,
)

# Symbol-level re-exports — preserve the names handlers import today.
from census_us.tools._lib.acs_extractor import (  # noqa: F401
    ACS_TABLES,
    extract_acs_table,
)
from census_us.tools._lib.db_ingest import (  # noqa: F401
    OutputStore,
    get_mongo_db,
)
from census_us.tools._lib.downloader import (  # noqa: F401
    download_acs,
    download_tiger,
)
from census_us.tools._lib.summary_builder import (  # noqa: F401
    join_geo,
    summarize_state,
)
from census_us.tools._lib.svi import (  # noqa: F401
    build_national_index,
    build_svi_map,
)
from census_us.tools._lib.tiger_extractor import (  # noqa: F401
    extract_tiger,
)

__all__ = [
    # Modules
    "acs_extractor",
    "db_ingest",
    "downloader",
    "maps",
    "metrics",
    "summary_builder",
    "svi",
    "tiger_extractor",
    "build_metrics_map",
    "build_national_rankings",
    # Symbols
    "ACS_TABLES",
    "OutputStore",
    "build_national_index",
    "build_svi_map",
    "download_acs",
    "download_tiger",
    "extract_acs_table",
    "extract_tiger",
    "get_mongo_db",
    "join_geo",
    "summarize_state",
]
