"""Build deterministic reference factor loadings and sector mappings.

The idempotent outputs are JSON, a flat sector map, and optional Parquet.
Symbol-seeded values, six-decimal rounding, and sorted compact JSON keep bytes
stable across runs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import struct
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_SCRIPT_PATH = Path(__file__).resolve()
_DEFAULT_REFERENCE_ROOT = _SCRIPT_PATH.parent.parent / "src" / "feelies" / "storage" / "reference"


REFERENCE_UNIVERSE: tuple[str, ...] = (
    "AAPL",
    "MSFT",
    "GOOG",
    "AMZN",
    "META",
    "NVDA",
    "JPM",
    "BAC",
    "XOM",
    "CVX",
)

REFERENCE_SECTORS: dict[str, str] = {
    "AAPL": "TECH",
    "MSFT": "TECH",
    "GOOG": "TECH",
    "AMZN": "CONS_DISC",
    "META": "TECH",
    "NVDA": "TECH",
    "JPM": "FIN",
    "BAC": "FIN",
    "XOM": "ENERGY",
    "CVX": "ENERGY",
}

FACTORS_FF5_MOMENTUM_STR: tuple[str, ...] = (
    "MKT",
    "SMB",
    "HML",
    "RMW",
    "CMA",
    "MOM",
    "STR",
)

# Prior trading day for the reference session, embedded for deterministic freshness checks.
REFERENCE_AS_OF_NS: int = 1_768_446_000_000_000_000


def _deterministic_loading(symbol: str, factor: str) -> float:
    """Map ``(symbol, factor)`` to a stable pseudo-random loading.

    Uses SHA-256 of the canonical key as the entropy source; takes
    the first 8 bytes as a uint64, converts to a [-1, 1] float, then
    scales to a plausible factor-loading magnitude.  Bit-identical
    across runs and platforms.
    """
    key = f"{symbol}:{factor}".encode("utf-8")
    digest = hashlib.sha256(key).digest()
    (raw,) = struct.unpack(">Q", digest[:8])
    unit = (raw / (2**64 - 1)) * 2.0 - 1.0
    if factor == "MKT":
        return round(0.6 + unit * 0.4, 6)
    if factor in ("SMB", "HML"):
        return round(unit * 0.5, 6)
    return round(unit * 0.3, 6)


def build_loadings() -> dict[str, dict[str, float]]:
    return {
        sym: {f: _deterministic_loading(sym, f) for f in FACTORS_FF5_MOMENTUM_STR}
        for sym in REFERENCE_UNIVERSE
    }


def build_sector_map() -> dict[str, str]:
    return dict(REFERENCE_SECTORS)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    logger.info("wrote %s (%d bytes)", path, path.stat().st_size)


def write_parquet_if_available(
    path: Path,
    loadings: dict[str, dict[str, float]],
) -> bool:
    try:
        import pyarrow as pa  # noqa: F401
        import pyarrow.parquet as pq
    except ImportError:
        logger.info(
            "pyarrow not installed — skipping parquet emission "
            "(install via `pip install feelies[portfolio]`)"
        )
        return False

    import pyarrow as pa
    import pyarrow.parquet as pq

    rows = []
    for sym in sorted(loadings):
        row = {"symbol": sym}
        for f in FACTORS_FF5_MOMENTUM_STR:
            row[f] = float(loadings[sym].get(f, 0.0))
        rows.append(row)
    table = pa.Table.from_pylist(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path)
    logger.info("wrote %s (%d bytes)", path, path.stat().st_size)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build the reference factor-loadings + sector-map fixtures for Phase 4-finalize."
        )
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=_DEFAULT_REFERENCE_ROOT,
        help="Root directory for the emitted reference fixtures.",
    )
    parser.add_argument(
        "--no-parquet",
        action="store_true",
        help="Skip parquet emission even when pyarrow is installed.",
    )
    parser.add_argument(
        "--as-of-ns",
        type=int,
        default=REFERENCE_AS_OF_NS,
        help=(
            "Content-embedded freshness anchor (ns since epoch) emitted as a "
            "`_meta.as_of_ns` block so the bootstrap freshness check uses a "
            "reproducible timestamp instead of the file mtime (audit P1-3). "
            f"Defaults to REFERENCE_AS_OF_NS ({REFERENCE_AS_OF_NS}); pass 0 to omit."
        ),
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    loadings = build_loadings()
    sector_map = build_sector_map()

    loadings_payload: dict[str, object] = dict(loadings)
    sector_map_payload: dict[str, object] = dict(sector_map)
    if args.as_of_ns:  # 0 (or None) omits the block
        loadings_payload["_meta"] = {"as_of_ns": int(args.as_of_ns)}
        # Give both fixtures the same reproducible freshness anchor.
        sector_map_payload["_meta"] = {"as_of_ns": int(args.as_of_ns)}

    write_json(
        args.output_root / "factor_loadings" / "loadings.json",
        loadings_payload,
    )
    write_json(
        args.output_root / "sector_map" / "sector_map.json",
        sector_map_payload,
    )
    if not args.no_parquet:
        write_parquet_if_available(
            args.output_root / "factor_loadings" / "loadings.parquet",
            loadings,
        )

    logger.info(
        "Reference fixtures built: %d symbols × %d factors, %d sector(s)",
        len(loadings),
        len(FACTORS_FF5_MOMENTUM_STR),
        len(set(sector_map.values())),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
