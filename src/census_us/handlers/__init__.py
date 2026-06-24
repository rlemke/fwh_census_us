"""Census-US handlers package.

Provides registration functions for all census event facet handlers,
supporting both AgentPoller and RegistryRunner execution models.
"""

from .acs.acs_handlers import register_acs_handlers
from .downloads.download_handlers import register_download_handlers
from .ingestion.ingestion_handlers import register_ingestion_handlers
from .publish.publish_handlers import register_publish_handlers
from .summary.summary_handlers import register_summary_handlers
from .tiger.tiger_handlers import register_tiger_handlers
from .vocab.vocab_handlers import register_vocab_handlers
from .vulnerability.svi_handlers import register_vulnerability_handlers

__all__ = [
    "register_all_handlers",
    "register_all_registry_handlers",
    "register_download_handlers",
    "register_acs_handlers",
    "register_tiger_handlers",
    "register_summary_handlers",
    "register_ingestion_handlers",
    "register_vocab_handlers",
    "register_vulnerability_handlers",
    "register_publish_handlers",
]


def register_all_handlers(poller) -> None:
    """Register all event facet handlers with the given poller."""
    register_download_handlers(poller)
    register_acs_handlers(poller)
    register_tiger_handlers(poller)
    register_summary_handlers(poller)
    register_ingestion_handlers(poller)
    register_vocab_handlers(poller)
    register_vulnerability_handlers(poller)
    register_publish_handlers(poller)


def register_all_registry_handlers(runner) -> None:
    """Register all facet handlers with a RegistryRunner."""
    from .acs.acs_handlers import register_handlers as reg_acs
    from .downloads.download_handlers import register_handlers as reg_downloads
    from .ingestion.ingestion_handlers import register_handlers as reg_ingestion
    from .summary.summary_handlers import register_handlers as reg_summary
    from .tiger.tiger_handlers import register_handlers as reg_tiger
    from .publish.publish_handlers import register_handlers as reg_publish
    from .vocab.vocab_handlers import register_handlers as reg_vocab
    from .vulnerability.svi_handlers import register_handlers as reg_vuln

    reg_downloads(runner)
    reg_acs(runner)
    reg_tiger(runner)
    reg_summary(runner)
    reg_ingestion(runner)
    reg_vocab(runner)
    reg_vuln(runner)
    reg_publish(runner)
