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
from typing import Any, cast

from feelies.core.events import NBBOQuote, Trade

logger = logging.getLogger(__name__)

_TYPE_QUOTE = "NBBOQuote"
_TYPE_TRADE = "Trade"

# Bump when the semantic meaning of existing fields changes without
# altering the dataclass schema.  Forces re-ingestion from the API.
_CACHE_SEMANTIC_VERSION = "2"


def _sha256_prefixed(data: bytes) -> str:
    """Return the ``sha256:<hex>`` checksum string used across the cache."""
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


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
    return _sha256_prefixed(raw.encode())


def _event_to_dict(event: NBBOQuote | Trade) -> dict[str, Any]:
    """Serialize a frozen event to a JSON-safe dict.

    Decimal fields are converted to strings to preserve precision (Inv-5).
    Tuple fields are converted to lists for JSON compatibility.
    """
    d: dict[str, Any] = {
        "__type__": _TYPE_QUOTE if isinstance(event, NBBOQuote) else _TYPE_TRADE,
    }

    for name in event.__dataclass_fields__:
        val = getattr(event, name)
        if isinstance(val, Decimal):
            d[name] = str(val)
        elif isinstance(val, tuple):
            d[name] = list(val)
        else:
            d[name] = val

    return d


def _dict_to_event(d: dict[str, Any]) -> NBBOQuote | Trade:
    """Deserialize a dict back into a frozen NBBOQuote or Trade.

    Type-string matching is intentionally **substring-based** so
    annotations such as ``"Decimal"``, ``"Decimal | None"``,
    ``"tuple[int, ...]"``, and any future ``"tuple[int, ...] | None"``
    are all reverse-mapped correctly without depending on the exact
    spelling (audit D3-MINOR).  ``from __future__ import annotations``
    makes every dataclass field type a string at this layer, so we
    cannot rely on runtime ``isinstance`` of the declared type.
    """
    type_tag = d.pop("__type__")
    cls = NBBOQuote if type_tag == _TYPE_QUOTE else Trade

    for name, field_obj in cls.__dataclass_fields__.items():
        if name not in d:
            continue
        val = d[name]
        ft = field_obj.type
        ft_str = ft if isinstance(ft, str) else getattr(ft, "__name__", str(ft))

        if "Decimal" in ft_str:
            if val is not None:
                d[name] = Decimal(str(val))
        elif "tuple[int" in ft_str:
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

    def read_manifest(self, symbol: str, date: str) -> dict[str, Any] | None:
        """Return parsed manifest JSON for a cache day, or None if unreadable."""
        manifest_path = self._manifest_path(symbol, date)
        if not manifest_path.exists():
            return None
        try:
            return cast(dict[str, Any], json.loads(manifest_path.read_text(encoding="utf-8")))
        except Exception:
            return None

    def exists(self, symbol: str, date: str) -> bool:
        """Check if a valid cache entry exists for this (symbol, date).

        Returns False if data file or manifest is missing, or if the
        schema hash doesn't match current event definitions.
        """
        if not self._data_path(symbol, date).exists():
            return False
        manifest = self.read_manifest(symbol, date)
        return manifest is not None and manifest.get("event_schema_hash") == self._schema_hash

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

        actual_checksum = _sha256_prefixed(raw_bytes)
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

    def save(
        self,
        symbol: str,
        date: str,
        events: Sequence[NBBOQuote | Trade],
        *,
        ingestion_health: str | None = None,
    ) -> None:
        """Persist events to gzipped JSONL with atomic writes.

        Both the data file and manifest are written to temporary files
        first, then atomically renamed.  Data is written before the
        manifest so that a crash between the two leaves exists()
        returning False (no manifest) and the stale .tmp is
        overwritten on the next successful save.
        """
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

        data_tmp = data_path.with_suffix(".tmp")
        data_tmp.write_bytes(compressed)
        os.replace(str(data_tmp), str(data_path))

        checksum = _sha256_prefixed(compressed)

        manifest: dict[str, Any] = {
            "symbol": symbol,
            "date": date,
            "event_count": len(events),
            "quotes_count": quotes_count,
            "trades_count": trades_count,
            "checksum": checksum,
            "event_schema_hash": self._schema_hash,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        if ingestion_health is not None:
            manifest["ingestion_health"] = ingestion_health

        manifest_tmp = manifest_path.with_suffix(".tmp")
        manifest_tmp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        os.replace(str(manifest_tmp), str(manifest_path))

        logger.info(
            "disk_cache: saved %d events (%d quotes, %d trades) for %s/%s (%.1f MB)",
            len(events), quotes_count, trades_count, symbol, date,
            len(compressed) / 1_048_576,
        )
