"""Per-day disk cache for normalized market events.

Stores JSONL.gz files with companion manifests per (symbol, date) pair.
Enables repeat backtests to skip the Massive API entirely.  Corrupt or
stale caches fall through to API download (invariant 11 — fail-safe).

Cache layout::

    {cache_dir}/{SYMBOL}/{YYYY-MM-DD}.jsonl.gz
    {cache_dir}/{SYMBOL}/{YYYY-MM-DD}.manifest.json
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import time
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path

from feelies.core.events import NBBOQuote, Trade

logger = logging.getLogger(__name__)

_TYPE_QUOTE = "NBBOQuote"
_TYPE_TRADE = "Trade"

# Bump when the semantic meaning of existing fields changes without
# altering the dataclass schema.  Forces re-ingestion from the API.
_CACHE_SEMANTIC_VERSION = "2"


def _compute_schema_hash() -> str:
    """SHA-256 of sorted field names + types from NBBOQuote and Trade.

    Changes when the dataclass schema evolves or when the semantic
    version is bumped, auto-invalidating stale caches.
    """
    parts: list[str] = [f"__semantic_version__:{_CACHE_SEMANTIC_VERSION}"]
    for cls in (NBBOQuote, Trade):
        for name, f in sorted(cls.__dataclass_fields__.items()):
            parts.append(f"{cls.__name__}.{name}:{f.type}")
    raw = "\n".join(parts)
    return f"sha256:{hashlib.sha256(raw.encode()).hexdigest()}"


def _event_to_dict(event: NBBOQuote | Trade) -> dict:
    """Serialize a frozen event to a JSON-safe dict.

    Decimal fields are converted to strings to preserve precision (Inv-5).
    Tuple fields are converted to lists for JSON compatibility.
    """
    d: dict = {"__type__": _TYPE_QUOTE if isinstance(event, NBBOQuote) else _TYPE_TRADE}

    for name in event.__dataclass_fields__:
        val = getattr(event, name)
        if isinstance(val, Decimal):
            d[name] = str(val)
        elif isinstance(val, tuple):
            d[name] = list(val)
        else:
            d[name] = val

    return d


def _dict_to_event(d: dict) -> NBBOQuote | Trade:
    """Deserialize a dict back into a frozen NBBOQuote or Trade."""
    type_tag = d.pop("__type__")
    cls = NBBOQuote if type_tag == _TYPE_QUOTE else Trade

    for name, field_obj in cls.__dataclass_fields__.items():
        if name not in d:
            continue
        val = d[name]
        ft = field_obj.type

        if ft == "Decimal" or (isinstance(ft, str) and "Decimal" in ft):
            if val is not None:
                d[name] = Decimal(str(val))
        elif ft == "tuple[int, ...]":
            if isinstance(val, list):
                d[name] = tuple(val)

    return cls(**d)


class DiskEventCache:
    """Per-day, per-symbol disk cache for normalized market events."""

    __slots__ = ("_cache_dir", "_schema_hash")

    def __init__(self, cache_dir: Path) -> None:
        self._cache_dir = Path(cache_dir)
        self._schema_hash = _compute_schema_hash()

    def _symbol_dir(self, symbol: str) -> Path:
        return self._cache_dir / symbol

    def _data_path(self, symbol: str, date: str) -> Path:
        return self._symbol_dir(symbol) / f"{date}.jsonl.gz"

    def _manifest_path(self, symbol: str, date: str) -> Path:
        return self._symbol_dir(symbol) / f"{date}.manifest.json"

    def exists(self, symbol: str, date: str) -> bool:
        """Check if a valid cache entry exists for this (symbol, date).

        Returns False if data file or manifest is missing, or if the
        schema hash doesn't match current event definitions.
        """
        data_path = self._data_path(symbol, date)
        manifest_path = self._manifest_path(symbol, date)

        if not data_path.exists() or not manifest_path.exists():
            return False

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return False

        return manifest.get("event_schema_hash") == self._schema_hash

    def load(self, symbol: str, date: str) -> list[NBBOQuote | Trade] | None:
        """Load cached events for a (symbol, date) pair.

        Returns None on any failure (checksum mismatch, corrupt data,
        schema mismatch) — caller falls through to API (Inv-11).
        """
        data_path = self._data_path(symbol, date)
        manifest_path = self._manifest_path(symbol, date)

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("disk_cache: unreadable manifest for %s/%s", symbol, date)
            return None

        if manifest.get("event_schema_hash") != self._schema_hash:
            logger.warning("disk_cache: schema mismatch for %s/%s, invalidating", symbol, date)
            return None

        expected_checksum = manifest.get("checksum", "")

        try:
            raw_bytes = data_path.read_bytes()
        except Exception:
            logger.warning("disk_cache: unreadable data file for %s/%s", symbol, date)
            return None

        actual_checksum = f"sha256:{hashlib.sha256(raw_bytes).hexdigest()}"
        if actual_checksum != expected_checksum:
            logger.warning(
                "disk_cache: checksum mismatch for %s/%s (expected %s, got %s)",
                symbol, date, expected_checksum, actual_checksum,
            )
            return None

        try:
            decompressed = gzip.decompress(raw_bytes)
            lines = decompressed.decode("utf-8").splitlines()
            events: list[NBBOQuote | Trade] = []
            for line in lines:
                if not line.strip():
                    continue
                d = json.loads(line)
                events.append(_dict_to_event(d))
        except Exception:
            logger.warning("disk_cache: deserialization failed for %s/%s", symbol, date, exc_info=True)
            return None

        expected_count = manifest.get("event_count", -1)
        if expected_count >= 0 and len(events) != expected_count:
            logger.warning(
                "disk_cache: event count mismatch for %s/%s (expected %d, got %d)",
                symbol, date, expected_count, len(events),
            )
            return None

        logger.info(
            "disk_cache: loaded %d events for %s/%s from cache",
            len(events), symbol, date,
        )
        return events

    def save(self, symbol: str, date: str, events: Sequence[NBBOQuote | Trade]) -> None:
        """Persist events to gzipped JSONL with an atomic manifest write."""
        sym_dir = self._symbol_dir(symbol)
        sym_dir.mkdir(parents=True, exist_ok=True)

        data_path = self._data_path(symbol, date)
        manifest_path = self._manifest_path(symbol, date)

        lines: list[str] = []
        quotes_count = 0
        trades_count = 0
        for event in events:
            lines.append(json.dumps(_event_to_dict(event), default=str))
            if isinstance(event, NBBOQuote):
                quotes_count += 1
            else:
                trades_count += 1

        raw_jsonl = "\n".join(lines).encode("utf-8")
        compressed = gzip.compress(raw_jsonl)

        data_path.write_bytes(compressed)

        checksum = f"sha256:{hashlib.sha256(compressed).hexdigest()}"

        manifest = {
            "symbol": symbol,
            "date": date,
            "event_count": len(events),
            "quotes_count": quotes_count,
            "trades_count": trades_count,
            "checksum": checksum,
            "event_schema_hash": self._schema_hash,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

        tmp_path = manifest_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        os.replace(str(tmp_path), str(manifest_path))

        logger.info(
            "disk_cache: saved %d events (%d quotes, %d trades) for %s/%s (%.1f MB)",
            len(events), quotes_count, trades_count, symbol, date,
            len(compressed) / 1_048_576,
        )
