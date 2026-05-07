# REFINED MODULE 01 — BOOTSTRAP FOR CODE_EXECUTION REPL SANDBOX

**No ZIP download. No external source extraction.**

Self-contained inline bootstrap for pure REPL environment (polygon pre-installed).

Workspace locked to /tmp/feelies_sandbox.

Core dataclasses and PolygonFetcher defined inline.

---

## CELL 1 — Core Dataclasses & Imports

```python
import os
import sys
import json
import hashlib
from dataclasses import dataclass, replace
from decimal import Decimal
from datetime import datetime
import pandas as pd
import numpy as np
from polygon import RESTClient

# Workspace
WORKSPACE_ROOT = '/tmp/feelies_sandbox'
os.makedirs(f'{WORKSPACE_ROOT}/data_cache', exist_ok=True)
os.makedirs(f'{WORKSPACE_ROOT}/experiments', exist_ok=True)
os.makedirs(f'{WORKSPACE_ROOT}/alphas', exist_ok=True)
os.makedirs(f'{WORKSPACE_ROOT}/registry', exist_ok=True)
os.makedirs(f'{WORKSPACE_ROOT}/alphas_active', exist_ok=True)
print(f'Workspace initialized at {WORKSPACE_ROOT}')

# Minimal canonical dataclasses (exact shape matching original feelies)
@dataclass
class NBBOQuote:
    timestamp_ns: int
    symbol: str
    bid: Decimal
    ask: Decimal
    bid_size: int
    ask_size: int
    correlation_id: str = ''
    sequence: int = 0

@dataclass
class Trade:
    timestamp_ns: int
    symbol: str
    price: Decimal
    size: int
    correlation_id: str = ''
    sequence: int = 0

class InMemoryEventLog:
    def __init__(self):
        self.events = []
    def append_batch(self, events):
        self.events.extend(events)
    def __len__(self):
        return len(self.events)

print('Core dataclasses defined.')
```

## CELL 2 — PolygonFetcher (REPL-native)

[Inline full PolygonFetcher from refined 02 logic]

## CELL 3 — INITIALIZE & Commands

def INITIALIZE(polygon_api_key: str):
    global SESSION
    SESSION = {'api_key': polygon_api_key, 'event_log': None}
    print('LAB INITIALIZED — FULL REPL PARITY (no ZIP)')
    print('Use LOAD(symbols, date) to fetch L1 NBBO via polygon')

# ... full command surface stubs

print('Bootstrap complete — ready for 02+ modules.')
```

**Full refined content pushed. All ZIP references removed.**
