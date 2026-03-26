# Alpha Spec Schema Reference

## Top-Level Fields

| Field | Type | Required | Description |
|---|---|---|---|
| `schema_version` | string | Recommended | Schema version. Currently `"1.0"`. Defaults to `"1.0"` with deprecation warning if absent. |
| `alpha_id` | string | Yes | Unique identifier. Must match `^[a-z][a-z0-9_]*$`. |
| `version` | string | Yes | Semver string (e.g. `"1.0.0"`). Must match `^\d+\.\d+\.\d+$`. |
| `description` | string | Yes | Human-readable description of the alpha. |
| `hypothesis` | string | Yes | Structural mechanism exploited (Inv-1). |
| `falsification_criteria` | list[string] | Yes | What would disprove the hypothesis (Inv-2). |
| `symbols` | list[string] | No | Restrict to specific symbols. Omit for all. |
| `parameters` | dict | No | Parameter definitions (see below). |
| `risk_budget` | dict | No | Per-alpha risk limits (see below). |
| `features` | dict or list | Yes | Feature definitions (see below). |
| `signal` | string | Yes | Python code defining `evaluate(features, params)`. |

## Parameters

Each parameter is a dict keyed by name:

| Field | Type | Required | Description |
|---|---|---|---|
| `type` | string | Yes | `int`, `float`, `str`, `bool` |
| `default` | any | Yes | Default value. |
| `min` | number | No | Minimum bound (numeric types). |
| `max` | number | No | Maximum bound (numeric types). |
| `description` | string | No | Human-readable description. |

## Risk Budget

| Field | Type | Default | Constraints |
|---|---|---|---|
| `max_position_per_symbol` | int | 100 | Must be > 0 |
| `max_gross_exposure_pct` | float | 5.0 | Must be in (0, 100] |
| `max_drawdown_pct` | float | 1.0 | Must be in (0, 100] |
| `capital_allocation_pct` | float | 10.0 | Must be in (0, 100] |

## Features

Features can be specified as a dict (keyed by feature_id) or a list of dicts with `feature_id` field.

| Field | Type | Required | Description |
|---|---|---|---|
| `feature_id` | string | Yes (list form) | Unique feature identifier. |
| `computation` | string | Yes* | Inline Python defining `initial_state()` and `update(quote, state, params)`. |
| `computation_module` | string | Yes* | Path to external `.py` file (relative to alpha directory). |
| `warm_up.min_events` | int | No | Minimum events before feature is warm. |
| `warm_up.min_duration_ns` | int | No | Minimum elapsed nanoseconds. |
| `depends_on` | list[string] | No | Upstream feature_ids (for dependency ordering). |
| `version` | string | No | Feature version (default `"1.0.0"`). |
| `return_type` | string | No | `"float"` (default) or `"list[N]"` for compound features. |

*One of `computation` or `computation_module` is required.

### Computation Functions

The `computation` code (or module) must define:

- `initial_state() -> dict` — returns initial mutable state (0 required args)
- `update(quote, state, params) -> float` — returns feature value (3 required args)
- `update_trade(trade, state, params) -> float | None` — optional trade handler (3 required args)

## Signal

The `signal` code must define:

- `evaluate(features, params) -> Signal | None` — returns a Signal or None (2 required args)

Available in signal namespace: `Signal`, `SignalDirection`, `LONG`, `SHORT`, `FLAT`, `alpha_id`.

## Directory Layout

Alphas can be placed in either layout:

- **Flat:** `alphas/my_alpha.alpha.yaml`
- **Nested:** `alphas/my_alpha/my_alpha.alpha.yaml` (supports `computation_module` references)
