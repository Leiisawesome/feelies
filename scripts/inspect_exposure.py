"""Diagnostic: dump fills and peak position to understand max exposure."""
from __future__ import annotations
import sys
from pathlib import Path
from collections import defaultdict
from decimal import Decimal

# ── bootstrap ────────────────────────────────────────────────────────
from dataclasses import replace

from feelies.core.platform_config import PlatformConfig
from feelies.bootstrap import build_platform
from feelies.storage.disk_event_cache import DiskEventCache
from feelies.storage.memory_event_log import InMemoryEventLog
from feelies.core.events import PositionUpdate, OrderAck, OrderRequest, NBBOQuote

config = PlatformConfig.from_yaml("platform.yaml")
config = replace(
    config,
    symbols=frozenset({"AAPL"}),
    ingest_terminal_symbol_health=(("AAPL", "HEALTHY"),),
)

cache = DiskEventCache(Path.home() / ".feelies" / "cache")
events = cache.load("AAPL", "2026-04-08")
if not events:
    print("ERROR: no cache for AAPL 2026-04-08")
    sys.exit(1)

el = InMemoryEventLog()
el.append_batch(events)

orc, cfg_out = build_platform(config, event_log=el)

by_type: dict[str, list] = defaultdict(list)

def rec(e: object) -> None:
    by_type[type(e).__name__].append(e)

orc._bus.subscribe_all(rec)  # type: ignore[attr-defined]
orc.boot(cfg_out)
orc.run_backtest()  # type: ignore[attr-defined]

# ── analyse ──────────────────────────────────────────────────────────
fills = [a for a in by_type.get("OrderAck", []) if a.status.name == "FILLED"]
pos_upds: list[PositionUpdate] = by_type.get("PositionUpdate", [])  # type: ignore[assignment]
orders: list[OrderRequest] = by_type.get("OrderRequest", [])  # type: ignore[assignment]

print("=== ORDERS ===")
for o in orders:
    print(f"  {o.side.name:4s}  qty={o.quantity:5d}  {o.symbol}  strat={o.strategy_id}")

print()
print("=== FILLS ===")
for a in fills:
    print(f"  qty={a.filled_quantity:+5d}  price={a.fill_price:>8.2f}  order_id={a.order_id[:12]}")

print()
print("=== POSITION UPDATES (qty != 0) ===")
max_exp = Decimal("0")
max_pu: PositionUpdate | None = None
for pu in pos_upds:
    exp = abs(pu.quantity) * pu.avg_price
    if exp > max_exp:
        max_exp = exp
        max_pu = pu
    if abs(pu.quantity) > 5:
        print(
            f"  {pu.symbol}  qty={pu.quantity:6d}  avg={float(pu.avg_price):8.2f}"
            f"  exp={float(exp):>12,.0f}"
        )

if max_pu:
    print()
    print(
        f"Peak: qty={max_pu.quantity}  avg={float(max_pu.avg_price):.4f}"
        f"  exposure=${float(max_exp):,.2f}"
    )
else:
    print("No significant positions found.")
