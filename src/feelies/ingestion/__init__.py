"""Market data ingestion layer — normalize Polygon L1 NBBO into canonical events."""

from feelies.ingestion.data_integrity import DataHealth, create_data_integrity_machine

__all__ = ["DataHealth", "create_data_integrity_machine"]
