"""Handler-side compatibility shim for the census-us pipeline.

The real implementation lives in ``census_us.tools._lib``. It is shared
verbatim by:

- the ``download`` / ``acs-extract`` / ``tiger-extract`` /
  ``ingest-to-db`` / ``summarize-state`` / ``join-geo`` CLI tools
  (``src/census_us/tools/``), and
- the FFL downloads / acs / tiger / ingestion / summary handlers (this
  package's siblings).

Both entry points read and write the same on-disk cache
(``$FW_DATA_ROOT/cache/census-us/...``) — the tool and the FFL are
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
    publish,
    summary_builder,
    svi,
    tiger_extractor,
)
from census_us.tools._lib.indicators import (  # noqa: F401
    build_chr_indicators_csv,
    build_chr_jobless_ts_csv,
    build_chr_measure_series_csv,
    build_election_ts_csv,
    build_cancer_mortality_csv,
    build_drug_overdose_ts_csv,
    build_suicide_ts_csv,
    build_home_value_ts_csv,
    build_unauthorized_ts_csv,
    build_heart_disease_ts_csv,
    build_homeless_ts_csv,
)
from census_us.tools._lib.maps import (  # noqa: F401
    acs_timeseries_values,
    build_metrics_index,
    build_metrics_map,
    build_national_county_map,
    build_national_county_time_map,
    build_national_rankings,
    build_state_metrics,
    wide_csv_values,
)
from census_us.tools._lib.publish import (  # noqa: F401
    publish_bundles,
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
    "publish",
    "summary_builder",
    "svi",
    "tiger_extractor",
    "build_metrics_index",
    "build_metrics_map",
    "acs_timeseries_values",
    "build_chr_indicators_csv",
    "build_chr_jobless_ts_csv",
    "build_chr_measure_series_csv",
    "build_election_ts_csv",
    "build_cancer_mortality_csv",
    "build_drug_overdose_ts_csv",
    "build_suicide_ts_csv",
    "build_home_value_ts_csv",
    "build_unauthorized_ts_csv",
    "build_heart_disease_ts_csv",
    "build_homeless_ts_csv",
    "build_national_county_map",
    "build_national_county_time_map",
    "wide_csv_values",
    "build_national_rankings",
    "build_state_metrics",
    "publish_bundles",
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
