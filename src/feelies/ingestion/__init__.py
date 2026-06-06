"""Market data ingestion layer — normalize Massive L1 NBBO into canonical events."""

from feelies.ingestion.data_integrity import DataHealth, create_data_integrity_machine
from feelies.ingestion.ingest_health import (
    merge_worst_health,
    parse_ingestion_health_label,
    terminal_symbol_health_rows,
)
from feelies.ingestion.massive_ingestor import (
    BackfillCheckpoint,
    IngestResult,
    InMemoryCheckpoint,
    MassiveHistoricalIngestor,
)
from feelies.ingestion.massive_normalizer import MassiveNormalizer
from feelies.ingestion.massive_ws import MassiveLiveFeed
from feelies.ingestion.normalizer import MarketDataNormalizer
from feelies.ingestion.replay_feed import ReplayFeed

__all__ = [
    "BackfillCheckpoint",
    "DataHealth",
    "IngestResult",
    "InMemoryCheckpoint",
    "MarketDataNormalizer",
    "MassiveHistoricalIngestor",
    "MassiveLiveFeed",
    "MassiveNormalizer",
    "ReplayFeed",
    "create_data_integrity_machine",
    "merge_worst_health",
    "parse_ingestion_health_label",
    "terminal_symbol_health_rows",
]
