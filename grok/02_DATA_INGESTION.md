# MODULE 2 — DATA INGESTION: POLYGON RTH FETCHER

## ACTIVATION DIRECTIVE

The Data Ingestion module activates with this block. This is the **single
allowed substitution** from the repo pipeline. It replaces
`MassiveHistoricalIngestor` with a Grok-native Polygon REST fetcher that
emits **identical** `NBBOQuote` / `Trade` dataclasses.

Everything downstream (sensor registry, horizon aggregation, signal engine,
composition, execution, risk, and orchestrator) sees the same canonical
events it would see from the repo's ingestor.

---

## CELL 1 — PolygonFetcher: canonical L1 NBBO ingestion for Grok

```python
import requests, time, os, json, datetime, zoneinfo, concurrent.futures
from decimal import Decimal
from dataclasses import replace

# pyarrow/parquet used for the disk cache. Fall back to JSON if not available.
try:
    import pyarrow as pa, pyarrow.parquet as pq
    _PARQUET_AVAILABLE = True
except ImportError:
    _PARQUET_AVAILABLE = False
    print("NOTE: pyarrow not found — cache will use JSON instead of Parquet (slower but functional)")

# Re-import from repo source to make sure we use the real dataclasses
from feelies.core.events import NBBOQuote, Trade
from feelies.core.identifiers import SequenceGenerator, make_correlation_id
from feelies.storage.memory_event_log import InMemoryEventLog

# -------------------------------------------------------------------
# RTH window in Eastern time
# -------------------------------------------------------------------
_ET = zoneinfo.ZoneInfo("America/New_York")
_RTH_OPEN  = datetime.time(9, 30, 0)
_RTH_CLOSE = datetime.time(16, 0, 0)

def _rth_ns(date_str: str) -> tuple[int, int]:
    """Return (open_ns, close_ns) in UTC nanoseconds for 09:30–16:00 ET on date_str."""
    d = datetime.date.fromisoformat(date_str)
    open_dt  = datetime.datetime(d.year, d.month, d.day, 9, 30, 0, tzinfo=_ET)
    close_dt = datetime.datetime(d.year, d.month, d.day, 16, 0, 0, tzinfo=_ET)
    open_ns  = int(open_dt.timestamp() * 1_000_000_000)
    close_ns = int(close_dt.timestamp() * 1_000_000_000)
    return open_ns, close_ns


def _day_bounds_ns(date_str: str) -> tuple[int, int]:
    """Return (start_ns, end_ns) for the full calendar day in UTC nanoseconds.

    Matches MassiveHistoricalIngestor: timestamp_gte="{date}T00:00:00Z",
    timestamp_lte="{date}T23:59:59Z".
    """
    d = datetime.date.fromisoformat(date_str)
    utc = datetime.timezone.utc
    start_ns = int(datetime.datetime(d.year, d.month, d.day, 0,  0,  0,  tzinfo=utc).timestamp() * 1_000_000_000)
    end_ns   = int(datetime.datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=utc).timestamp() * 1_000_000_000)
    return start_ns, end_ns


# -------------------------------------------------------------------
# Polygon REST pagination helper
# -------------------------------------------------------------------
_BASE = "https://api.polygon.io"

def _paginate(url: str, params: dict, api_key: str) -> list[dict]:
    """Fetch all pages from a Polygon v3 endpoint. Returns merged results list."""
    params = dict(params)
    params["apiKey"] = api_key
    all_results = []
    while True:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        all_results.extend(data.get("results", []))
        next_url = data.get("next_url")
        if not next_url:
            break
        # next_url already includes query params; only inject apiKey
        url = next_url
        params = {"apiKey": api_key}
        time.sleep(0.12)   # ~8 req/s — respect rate limit
    return all_results


# -------------------------------------------------------------------
# Per-day, per-symbol fetch (raw Polygon dicts, not yet dataclasses)
#
# PARITY NOTE: MassiveHistoricalIngestor fetches the full calendar day
# (00:00:00Z–23:59:59Z).  We do the same here so that the event log
# composition (including pre-market / after-hours for regime warm-up)
# is identical to what scripts/run_backtest.py produces.
# The orchestrator suppresses signals outside RTH internally; pre/post
# market events still flow through the feature and regime engines for
# warm-up, matching repo behavior exactly.
# -------------------------------------------------------------------
def _fetch_day_raw(symbol: str, date_str: str, api_key: str) -> tuple[list, list]:
    """Fetch raw quotes and trades for the full calendar day. Returns (quotes, trades)."""
    ts_gte, ts_lte = _day_bounds_ns(date_str)

    # Polygon v3 timestamps as nanosecond integers
    q_params = {
        "timestamp.gte": ts_gte,
        "timestamp.lte": ts_lte,
        "limit": 50000,
        "sort": "timestamp",
        "order": "asc",
    }
    t_params = dict(q_params)

    quotes = _paginate(f"{_BASE}/v3/quotes/{symbol}", q_params, api_key)
    trades = _paginate(f"{_BASE}/v3/trades/{symbol}", t_params, api_key)

    # Inject ticker field (Polygon v3 does not always include it in each record)
    for r in quotes: r.setdefault("ticker", symbol)
    for r in trades: r.setdefault("ticker", symbol)

    return quotes, trades


# -------------------------------------------------------------------
# Parquet cache — stores raw Polygon dicts, not dataclasses
# (sequences are reassigned at load time; caching sequences would break
#  multi-symbol resequencing)
# -------------------------------------------------------------------
_CACHE_DIR = "/home/user/data_cache"
os.makedirs(_CACHE_DIR, exist_ok=True)

def _cache_path(symbol: str, date_str: str, kind: str) -> str:
    return os.path.join(_CACHE_DIR, f"{symbol}_{date_str}_{kind}.parquet")

def _save_raw(records: list[dict], symbol: str, date_str: str, kind: str) -> None:
    if not records:
        return
    path = _cache_path(symbol, date_str, kind)
    if _PARQUET_AVAILABLE:
        pq.write_table(pa.Table.from_pylist(records), path)
    else:
        with open(path.replace(".parquet", ".json"), "w") as f:
            json.dump(records, f)

def _load_raw(symbol: str, date_str: str, kind: str) -> list[dict] | None:
    parquet_path = _cache_path(symbol, date_str, kind)
    json_path    = parquet_path.replace(".parquet", ".json")
    if _PARQUET_AVAILABLE and os.path.exists(parquet_path):
        return pq.read_table(parquet_path).to_pylist()
    if os.path.exists(json_path):
        with open(json_path) as f:
            return json.load(f)
    return None


# -------------------------------------------------------------------
# Data quality validation
# -------------------------------------------------------------------
def _validate_quotes(quotes: list[dict], symbol: str, date_str: str) -> None:
    if not quotes:
        print(f"  WARNING: {symbol}/{date_str} — 0 quotes fetched (non-trading day?)")
        return
    nulls = sum(1 for q in quotes if q.get("bid_price") is None or q.get("ask_price") is None
                or q.get("bid_size") is None or q.get("ask_size") is None)
    crossed = sum(1 for q in quotes
                  if q.get("bid_price") is not None and q.get("ask_price") is not None
                  and float(q["bid_price"]) > float(q["ask_price"]))
    zero_sz = sum(1 for q in quotes
                  if (q.get("bid_size") or 0) <= 0 or (q.get("ask_size") or 0) <= 0)
    total = len(quotes)
    print(f"  Quotes {symbol}/{date_str}: {total} | nulls={nulls} | crossed={crossed} | zero_size={zero_sz}")
    if nulls / max(total, 1) > 0.01:
        print(f"  WARNING: >1% null quotes for {symbol}/{date_str}")


# -------------------------------------------------------------------
# Convert raw Polygon dicts → canonical repo dataclasses
# Field mapping matches MassiveNormalizer._rest_quote / _rest_trade exactly.
# -------------------------------------------------------------------
def _to_nbbo(rec: dict, seq: int) -> NBBOQuote | None:
    """Convert one Polygon quote record to NBBOQuote. Returns None on bad data."""
    try:
        symbol   = rec["ticker"]
        sip_ts   = int(rec["sip_timestamp"])
        seq_num  = int(rec.get("sequence_number", 0))
        cid      = make_correlation_id(symbol, sip_ts, seq)

        raw_cond = rec.get("conditions")
        conditions = tuple(int(x) for x in raw_cond) if isinstance(raw_cond, list) else ()

        raw_ind = rec.get("indicators")
        indicators = tuple(int(x) for x in raw_ind) if isinstance(raw_ind, list) else ()

        raw_part = rec.get("participant_timestamp")
        part_ts  = int(raw_part) if raw_part is not None else None

        raw_trf = rec.get("trf_timestamp")
        trf_ts  = int(raw_trf) if raw_trf is not None else None

        return NBBOQuote(
            timestamp_ns           = sip_ts,
            correlation_id         = cid,
            sequence               = seq,
            symbol                 = symbol,
            bid                    = Decimal(str(rec["bid_price"])),
            ask                    = Decimal(str(rec["ask_price"])),
            bid_size               = int(rec["bid_size"]),
            ask_size               = int(rec["ask_size"]),
            bid_exchange           = int(rec.get("bid_exchange", 0)),
            ask_exchange           = int(rec.get("ask_exchange", 0)),
            exchange_timestamp_ns  = sip_ts,      # matches MassiveNormalizer
            conditions             = conditions,
            indicators             = indicators,
            sequence_number        = seq_num,
            tape                   = int(rec.get("tape", 0)),
            participant_timestamp_ns = part_ts,
            trf_timestamp_ns       = trf_ts,
        )
    except (KeyError, ValueError, TypeError) as exc:
        print(f"  WARN: bad quote record ({exc}): {list(rec.keys())}")
        return None

def _to_trade(rec: dict, seq: int) -> Trade | None:
    """Convert one Polygon trade record to Trade. Returns None on bad data."""
    try:
        symbol   = rec["ticker"]
        sip_ts   = int(rec["sip_timestamp"])
        seq_num  = int(rec.get("sequence_number", 0))
        cid      = make_correlation_id(symbol, sip_ts, seq)

        raw_cond = rec.get("conditions")
        conditions = tuple(int(x) for x in raw_cond) if isinstance(raw_cond, list) else ()

        raw_part = rec.get("participant_timestamp")
        part_ts  = int(raw_part) if raw_part is not None else None

        return Trade(
            timestamp_ns           = sip_ts,
            correlation_id         = cid,
            sequence               = seq,
            symbol                 = symbol,
            price                  = Decimal(str(rec["price"])),
            size                   = int(rec["size"]),
            exchange               = int(rec.get("exchange", 0)),
            trade_id               = str(rec.get("id", "")),
            exchange_timestamp_ns  = sip_ts,      # matches MassiveNormalizer
            conditions             = conditions,
            decimal_size           = rec.get("decimal_size"),
            sequence_number        = seq_num,
            tape                   = int(rec.get("tape", 0)),
            trf_id                 = int(rec["trf_id"]) if "trf_id" in rec else None,
            trf_timestamp_ns       = None,
            participant_timestamp_ns = part_ts,
            correction             = int(rec["correction"]) if "correction" in rec else None,
        )
    except (KeyError, ValueError, TypeError) as exc:
        print(f"  WARN: bad trade record ({exc}): {list(rec.keys())}")
        return None


# -------------------------------------------------------------------
# Resequence: matches _resequence() in scripts/run_backtest.py lines 196-214
# Sort by exchange_timestamp_ns; assign monotonic sequences from a fresh
# SequenceGenerator; regenerate correlation_ids.
# -------------------------------------------------------------------
def _resequence(events: list) -> list:
    """Sort all events by exchange_timestamp_ns and assign globally monotonic sequences."""
    events.sort(key=lambda e: e.exchange_timestamp_ns)
    gen = SequenceGenerator(start=0)
    result = []
    for event in events:
        new_seq = gen.next()
        new_cid = make_correlation_id(event.symbol, event.exchange_timestamp_ns, new_seq)
        result.append(replace(event, sequence=new_seq, correlation_id=new_cid))
    return result


# -------------------------------------------------------------------
# Main fetcher: builds InMemoryEventLog ready for build_platform()
# -------------------------------------------------------------------
class PolygonFetcher:
    """
    Replaces MassiveHistoricalIngestor for Grok REPL.

    Fetches RTH L1 NBBO data from Polygon REST API and populates an
    InMemoryEventLog with canonical NBBOQuote / Trade dataclasses,
    field-for-field identical to what MassiveNormalizer produces.

    Usage:
        fetcher = PolygonFetcher(api_key=SESSION["api_key"])
        event_log = fetcher.load("AAPL", "2026-01-15")
        event_log = fetcher.load(["AAPL","MSFT"], "2026-01-13", "2026-01-17")
    """

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def load(
        self,
        symbols: str | list[str],
        start: str,
        end: str | None = None,
    ) -> InMemoryEventLog:
        """
        Fetch data and return a populated InMemoryEventLog.

        Args:
            symbols: ticker or list of tickers
            start:   YYYY-MM-DD (start date, inclusive)
            end:     YYYY-MM-DD (end date, inclusive; defaults to start for single day)

        Returns:
            InMemoryEventLog sorted by exchange_timestamp_ns, ready for build_platform().
        """
        if isinstance(symbols, str):
            symbols = [symbols]
        end = end or start

        # Enumerate trading days in [start, end] (skip weekends)
        dates = _trading_days(start, end)
        print(f"Loading {symbols} for {dates} (RTH only)...")

        # Collect raw dicts in parallel: one thread per (symbol, date)
        raw_pairs: list[tuple[list, list]] = []
        tasks = [(sym, d) for sym in symbols for d in dates]

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futures = {
                pool.submit(self._fetch_with_cache, sym, date): (sym, date)
                for sym, date in tasks
            }
            for fut in concurrent.futures.as_completed(futures):
                sym, date = futures[fut]
                quotes_raw, trades_raw = fut.result()
                _validate_quotes(quotes_raw, sym, date)
                raw_pairs.append((quotes_raw, trades_raw))

        # Convert all raw records to canonical dataclasses using a temporary
        # SequenceGenerator (will be replaced by _resequence below)
        tmp_seq = SequenceGenerator(start=0)
        all_events: list[NBBOQuote | Trade] = []
        for quotes_raw, trades_raw in raw_pairs:
            for rec in quotes_raw:
                evt = _to_nbbo(rec, tmp_seq.next())
                if evt is not None:
                    all_events.append(evt)
            for rec in trades_raw:
                evt = _to_trade(rec, tmp_seq.next())
                if evt is not None:
                    all_events.append(evt)

        # Resequence: sort by exchange_timestamp_ns, assign final monotonic sequences
        all_events = _resequence(all_events)

        # Load into InMemoryEventLog
        event_log = InMemoryEventLog()
        event_log.append_batch(all_events)

        print(f"  Loaded {len(all_events)} events "
              f"({sum(isinstance(e, NBBOQuote) for e in all_events)} quotes, "
              f"{sum(isinstance(e, Trade) for e in all_events)} trades)")

        # Update session state
        SESSION["event_log"]      = event_log
        SESSION["loaded_symbols"] = symbols
        SESSION["loaded_dates"]   = dates

        return event_log

    def _fetch_with_cache(self, symbol: str, date_str: str) -> tuple[list, list]:
        """Cache-first fetch: raw Polygon dicts only (sequences reassigned at load time)."""
        quotes = _load_raw(symbol, date_str, "quotes")
        trades = _load_raw(symbol, date_str, "trades")
        if quotes is not None and trades is not None:
            print(f"  Cache hit: {symbol}/{date_str} "
                  f"({len(quotes)} quotes, {len(trades)} trades)")
            return quotes, trades

        print(f"  Fetching {symbol}/{date_str} from Polygon...")
        quotes, trades = _fetch_day_raw(symbol, date_str, self.api_key)
        _save_raw(quotes, symbol, date_str, "quotes")
        _save_raw(trades, symbol, date_str, "trades")
        print(f"  Fetched and cached: {symbol}/{date_str} "
              f"({len(quotes)} quotes, {len(trades)} trades)")
        return quotes, trades


# US equity market holidays (NYSE/NASDAQ official calendar).
# Covers 2024-2028. Extend by appending ISO dates for later years.
# Observed dates already applied: e.g. Jul 3 2026 (Jul 4 falls on Saturday),
# Jul 5 2027 (Jul 4 on Sunday), Dec 31 2027 (observed New Year's Day 2028).
_US_MARKET_HOLIDAYS: frozenset[str] = frozenset([
    # 2024
    "2024-01-01", "2024-01-15", "2024-02-19", "2024-03-29",
    "2024-05-27", "2024-06-19", "2024-07-04", "2024-09-02",
    "2024-11-28", "2024-12-25",
    # 2025 (Jan 9: National Day of Mourning for Jimmy Carter)
    "2025-01-01", "2025-01-09", "2025-01-20", "2025-02-17",
    "2025-04-18", "2025-05-26", "2025-06-19", "2025-07-04",
    "2025-09-01", "2025-11-27", "2025-12-25",
    # 2026 (Jul 3: Independence Day observed; Jul 4 is Saturday)
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03",
    "2026-05-25", "2026-06-19", "2026-07-03", "2026-09-07",
    "2026-11-26", "2026-12-25",
    # 2027 (Jun 18: Juneteenth observed; Jul 5: Independence Day observed;
    #        Dec 24: Christmas observed; Dec 31: New Year's Day 2028 observed)
    "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26",
    "2027-05-31", "2027-06-18", "2027-07-05", "2027-09-06",
    "2027-11-25", "2027-12-24", "2027-12-31",
    # 2028 (New Year's Day observed 2027-12-31 above)
    "2028-01-17", "2028-02-21", "2028-04-14",
    "2028-05-29", "2028-06-19", "2028-07-04", "2028-09-04",
    "2028-11-23", "2028-12-25",
])


def _trading_days(start: str, end: str) -> list[str]:
    """Return US equity market trading days in [start, end] as YYYY-MM-DD strings.

    Excludes weekends and US exchange holidays (NYSE/NASDAQ calendar).
    Holiday table covers 2024-2028; append to _US_MARKET_HOLIDAYS for later years.
    """
    s = datetime.date.fromisoformat(start)
    e = datetime.date.fromisoformat(end)
    days = []
    cur = s
    while cur <= e:
        iso = cur.isoformat()
        if cur.weekday() < 5 and iso not in _US_MARKET_HOLIDAYS:
            days.append(iso)
        cur += datetime.timedelta(days=1)
    return days


# Convenience LOAD command
def LOAD(symbols, start: str, end: str | None = None) -> InMemoryEventLog:
    """Fetch RTH L1 NBBO data and populate the session event log.

    Usage:
        LOAD("AAPL", "2026-01-15")
        LOAD(["AAPL", "MSFT"], "2026-01-13", "2026-01-17")
    """
    assert SESSION["api_key"], "Run INITIALIZE(api_key) first."
    fetcher = PolygonFetcher(api_key=SESSION["api_key"])
    return fetcher.load(symbols, start, end)

print("Data Ingestion module: ACTIVE")
print("Usage: LOAD('AAPL', '2026-01-15')  or  LOAD(['AAPL','MSFT'], '2026-01-13', '2026-01-17')")
```

---

## CELL 2 — Data Partitioning Helpers

```python
def partition_dates(
    all_dates: list[str],
    train_days: int = 20,
    val_days: int   = 5,
    oos_days: int   = 5,
    gap_days: int   = 1,
) -> dict[str, list[str]]:
    """
    Split a sorted list of trading dates into train/validation/OOS windows.

    Rules (non-negotiable):
    - Signal discovery occurs ONLY within train window.
    - Validation tunes parameters but does NOT discover new features.
    - OOS evaluates final performance — no re-optimization after peeking.
    - Gap days are excluded at partition boundaries to prevent leakage.
    """
    needed = train_days + gap_days + val_days + gap_days + oos_days
    assert len(all_dates) >= needed, (
        f"Need at least {needed} trading days, got {len(all_dates)}"
    )
    train = all_dates[:train_days]
    val   = all_dates[train_days + gap_days : train_days + gap_days + val_days]
    oos   = all_dates[train_days + gap_days + val_days + gap_days :
                      train_days + gap_days + val_days + gap_days + oos_days]
    print(f"Partitions: TRAIN={train[0]}…{train[-1]} | "
          f"VAL={val[0]}…{val[-1]} | OOS={oos[0]}…{oos[-1]}")
    return {"train": train, "validation": val, "oos": oos}

print("partition_dates() available.")
```

---

## 1. SUBSTITUTION CONTRACT

The Polygon REST fetcher is the **only** code in this system that deviates from the
repo. The contract it must satisfy:

| Property | Requirement |
|---|---|
| Output type | `InMemoryEventLog` (from repo `feelies.storage.memory_event_log`) |
| Event types | `NBBOQuote` and `Trade` (from repo `feelies.core.events`) |
| Prices | `Decimal` (exact string conversion from Polygon float) |
| Sizes | `int` |
| Timestamps | `int` nanoseconds from `sip_timestamp` field |
| `exchange_timestamp_ns` | Equal to `timestamp_ns` (same `sip_timestamp` source) |
| **Fetch window** | **Full calendar day (00:00:00Z – 23:59:59Z) — matches `MassiveHistoricalIngestor`** |
| Sorting | Events sorted by `exchange_timestamp_ns` before `append_batch` |
| Sequences | Monotonically increasing from 0, via `SequenceGenerator` |
| Correlation IDs | `{symbol}:{exchange_timestamp_ns}:{sequence}` format |
| Field mapping | Field-for-field identical to `MassiveNormalizer._rest_quote/trade` |

Any deviation from this contract is a defect. If parity fails, check here first.

---

## 2. RTH STANDARD

All **signal evaluation** uses Regular Trading Hours only:

```
09:30:00 America/New_York  →  16:00:00 America/New_York
```

The event log contains full-day data (matching the repo). The orchestrator internally
suppresses entry signals outside RTH via the session guard in `Orchestrator`.
Pre- and post-market ticks still flow through the sensor, horizon, and regime
path when the loaded alpha requires them, providing warm-up identical to the
repo's `scripts/run_backtest.py`.

---

## DATA INGESTION STATUS

```
Data Ingestion Module: ACTIVE
Substitution:         MassiveHistoricalIngestor → PolygonFetcher
Field mapping:        Matches MassiveNormalizer._rest_quote/_rest_trade exactly
Fetch window:         Full calendar day (00:00:00Z–23:59:59Z) — matches repo
RTH filtering:        Handled by orchestrator internally (not at ingest layer)
Downstream path:      sensor -> horizon -> signal -> composition when required by alpha
Cache:                /home/user/data_cache/{symbol}_{date}_{quotes|trades}.parquet
Resequencing:         Matches scripts/run_backtest.py _resequence() logic
Output:               InMemoryEventLog (from repo source)
```
