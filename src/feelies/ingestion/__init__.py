"""Market data ingestion layer — normalize Polygon L1 NBBO into canonical events."""

from feelies.ingestion.data_integrity import DataHealth, create_data_integrity_machine
from feelies.ingestion.normalizer import MarketDataNormalizer
from feelies.ingestion.polygon_ingestor import IngestResult, PolygonHistoricalIngestor
from feelies.ingestion.polygon_normalizer import PolygonNormalizer
from feelies.ingestion.polygon_ws import PolygonLiveFeed
from feelies.ingestion.replay_feed import ReplayFeed

__all__ = [
    "DataHealth",
    "IngestResult",
    "MarketDataNormalizer",
    "PolygonHistoricalIngestor",
    "PolygonLiveFeed",
    "PolygonNormalizer",
    "ReplayFeed",
    "create_data_integrity_machine",
]
