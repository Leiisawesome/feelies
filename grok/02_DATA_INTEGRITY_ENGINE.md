# PROMPT 2 — DATA INTEGRITY ENGINE: CHRONOLOGICAL PROTOCOL

## ACTIVATION DIRECTIVE

The Data Integrity Engine is now active. This module enforces strict chronological data integrity to prevent look-ahead bias and ensure reproducible research.

Without this module, every subsequent result is potentially invalid.

---

## 1. DATA PARTITIONING

Every experiment uses three strictly separated time partitions, defined BEFORE any data is examined.

```
┌─────────────────┬──────────────────┬──────────────────┐
│   TRAIN WINDOW  │ VALIDATION WINDOW│   OOS WINDOW     │
│ Signal discovery│ Parameter tuning │ Final evaluation  │
│ Feature search  │ Threshold select │ No re-optimization│
└─────────────────┴──────────────────┴──────────────────┘
```

### Default Configuration

```python
PARTITION_CONFIG = {
    "train_days": 20,         # ~4 trading weeks
    "validation_days": 5,     # ~1 trading week
    "oos_days": 5,            # ~1 trading week
    "gap_days": 1,            # Embargo at boundaries
    "embargo_seconds": 300,   # 5-minute buffer within partitions
}
```

### Rules — Non-Negotiable
1. Signal discovery occurs ONLY within the train window.
2. Validation tunes parameters but does NOT discover new features.
3. OOS evaluates final performance. No re-optimization. Sealed.
4. Embargo gaps prevent leakage across boundaries.

---

## 2. DATA FETCH ENGINE

### Polygon.io REST API — Field Mapping

The Polygon REST API returns fields that must be mapped to the platform's canonical `NBBOQuote` format:

```
Polygon REST field     →  Platform field        →  Type
─────────────────────────────────────────────────────────
ticker                 →  symbol                →  str
sip_timestamp          →  timestamp_ns          →  int (nanoseconds)
sip_timestamp          →  exchange_timestamp_ns  →  int (same value as timestamp_ns)
bid_price              →  bid                   →  Decimal
ask_price              →  ask                   →  Decimal
bid_size               →  bid_size              →  int
ask_size               →  ask_size              →  int
sequence_number        →  sequence_number       →  int
conditions             →  conditions            →  tuple[int]
indicators             →  indicators            →  tuple[int]
tape                   →  tape                  →  int
participant_timestamp  →  participant_timestamp_ns → int | None
```

Note: `exchange_timestamp_ns` is set to the same value as `timestamp_ns`
(both from `sip_timestamp`). The parity harness uses `exchange_timestamp_ns`
for clock advancement.

For trades:
```
Polygon REST field     →  Platform field        →  Type
─────────────────────────────────────────────────────────
ticker                 →  symbol                →  str
sip_timestamp          →  timestamp_ns          →  int (nanoseconds)
price                  →  price                 →  Decimal
size                   →  size                  →  int
exchange               →  exchange              →  int
conditions             →  conditions            →  tuple[int]
```

### Fetch Implementation

```python
import requests, time, os
import pandas as pd

class PolygonDataEngine:
    BASE_URL = "https://api.polygon.io"

    def __init__(self, api_key):
        self.api_key = api_key
        self.cache_dir = "/home/user/data_cache"
        self.rate_limit_delay = 0.15
        os.makedirs(self.cache_dir, exist_ok=True)

    def fetch_quotes(self, ticker, date):
        cache_key = f"quotes_{ticker}_{date}"
        cached = self._load_cache(cache_key)
        if cached is not None:
            return cached

        url = f"{self.BASE_URL}/v3/quotes/{ticker}"
        params = {
            "timestamp.gte": f"{date}T09:30:00Z",
            "timestamp.lt": f"{date}T16:00:00Z",
            "limit": 50000, "sort": "timestamp",
            "order": "asc", "apiKey": self.api_key,
        }
        all_results = []
        while True:
            resp = requests.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            all_results.extend(data.get("results", []))
            next_url = data.get("next_url")
            if not next_url:
                break
            url = next_url
            params = {"apiKey": self.api_key}
            time.sleep(self.rate_limit_delay)

        df = pd.DataFrame(all_results)
        self._save_cache(cache_key, df)
        return df

    def fetch_trades(self, ticker, date):
        cache_key = f"trades_{ticker}_{date}"
        cached = self._load_cache(cache_key)
        if cached is not None:
            return cached

        url = f"{self.BASE_URL}/v3/trades/{ticker}"
        params = {
            "timestamp.gte": f"{date}T09:30:00Z",
            "timestamp.lt": f"{date}T16:00:00Z",
            "limit": 50000, "sort": "timestamp",
            "order": "asc", "apiKey": self.api_key,
        }
        all_results = []
        while True:
            resp = requests.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            all_results.extend(data.get("results", []))
            next_url = data.get("next_url")
            if not next_url:
                break
            url = next_url
            params = {"apiKey": self.api_key}
            time.sleep(self.rate_limit_delay)

        df = pd.DataFrame(all_results)
        self._save_cache(cache_key, df)
        return df

    def _cache_path(self, key):
        return os.path.join(self.cache_dir, f"{key}.parquet")

    def _load_cache(self, key):
        path = self._cache_path(key)
        if os.path.exists(path):
            return pd.read_parquet(path)
        return None

    def _save_cache(self, key, df):
        if not df.empty:
            df.to_parquet(self._cache_path(key), index=False)
```

---

## 3. EVENT ORDER GUARANTEE

Feature computation must only use information available at timestamp t.

```python
# CORRECT: rolling computation anchored at current time
df['vol_20'] = df['returns'].rolling(20).std()

# FORBIDDEN: using future data
df['future_vol'] = df['returns'].rolling(20).std().shift(-10)

# FORBIDDEN: using OOS statistics in feature construction
oos_mean = df_oos['spread'].mean()
df_train['norm_spread'] = df_train['spread'] / oos_mean
```

---

## 4. ROLLING WINDOW ADVANCEMENT

Autonomous experiments advance windows chronologically:

```
Window 1:  [====TRAIN====][=VAL=][=OOS=]
Window 2:       [====TRAIN====][=VAL=][=OOS=]
Window 3:            [====TRAIN====][=VAL=][=OOS=]

Report: distribution of OOS metrics across windows, not single point.
```

---

## 5. DATA QUALITY VALIDATION

Every fetched dataset must pass:
- Timestamps ordered monotonically
- No nulls in bid_price, ask_price, bid_size, ask_size
- No crossed quotes (bid ≤ ask)
- Positive sizes
- Reasonable spread (< 5% of midprice for 99% of ticks)
- Minimum data density (> 0.1 quotes/second)

---

## 6. CACHE MANAGEMENT

```
/home/user/data_cache/
├── quotes_AAPL_2026-01-02.parquet
├── trades_AAPL_2026-01-02.parquet
└── cache_manifest.json
```

Cache rules:
- Reuse cached data whenever available (reproducibility)
- Append-only within session (never overwrite)
- Data quality checks on every fetch

---

## DATA ENGINE STATUS

```
Data Integrity Engine: ACTIVE
Chronological protocol: ENFORCED
Cache directory: /home/user/data_cache/
Event order guarantee: ENFORCED
Polygon field mapping: ALIGNED with platform MassiveNormalizer
```

Awaiting Market State Engine activation (Prompt 3).
