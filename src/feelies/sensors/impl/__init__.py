"""Concrete Layer-1 sensor implementations.

Sensors here are loaded by ``PlatformConfig._parse_sensor_spec``,
which enforces a ``feelies.sensors.impl.`` import prefix.  All
sensors satisfy :class:`feelies.sensors.protocol.Sensor` and remain
stateless on the instance — per-symbol state lives in the dict
returned by ``initial_state()``.

P2-β simple-sensor catalog (4 sensors):

- :mod:`feelies.sensors.impl.ofi_ewma` — Order-Flow Imbalance (EWMA).
- :mod:`feelies.sensors.impl.micro_price` — Bid/ask micro-price.
- :mod:`feelies.sensors.impl.spread_z_30d` — Spread z-score over 30
  days of history (30-second bucketed).
- :mod:`feelies.sensors.impl.realized_vol_30s` — 30-second realized
  volatility from mid-price returns.

P2-γ complex-sensor catalog (5 sensors):

- :mod:`feelies.sensors.impl.vpin_50bucket` — Volume-Synchronized
  Probability of Informed Trading.
- :mod:`feelies.sensors.impl.kyle_lambda_60s` — Kyle's lambda price-
  impact regression over a 60-second rolling window.
- :mod:`feelies.sensors.impl.quote_hazard_rate` — quote-arrival hazard
  rate.
- :mod:`feelies.sensors.impl.quote_replenish_asymmetry` — bid-vs-ask
  depth-replenishment asymmetry.
- :mod:`feelies.sensors.impl.trade_through_rate` — fraction of trades
  printing at or beyond the prevailing NBBO.

P2.1 v0.3 mechanism-fingerprint catalog (4 sensors):

- :mod:`feelies.sensors.impl.hawkes_intensity` — Hawkes self-exciting
  trade-arrival intensity (HAWKES_SELF_EXCITE family).
- :mod:`feelies.sensors.impl.scheduled_flow_window` — calendar-driven
  scheduled-flow window membership (SCHEDULED_FLOW family).
- :mod:`feelies.sensors.impl.snr_drift_diffusion` — per-horizon SNR
  exploitability gate (cross-cutting; consumed by alpha regime DSL).
- :mod:`feelies.sensors.impl.structural_break_score` — page-Hinkley
  structural-break diagnostic (cross-cutting; consumed by forensics).

P2-3 missing-fingerprint catalog (3 sensors; close the INVENTORY /
LIQUIDITY_STRESS coverage gap):

- :mod:`feelies.sensors.impl.inventory_pressure` — trade-side MM-inventory
  proxy (INVENTORY family).
- :mod:`feelies.sensors.impl.liquidity_stress_score` — composite
  spread-widening + depth-thinning stress alarm (LIQUIDITY_STRESS family).
- :mod:`feelies.sensors.impl.quote_flicker_rate` — best-price reversal
  fraction (LIQUIDITY_STRESS family).

P1-B/P1-C / 2P-2 KYLE_INFO catalog (2 sensors; this pair was previously
missing from this module docstring — see sensor_audit_2026-07-02):

- :mod:`feelies.sensors.impl.book_imbalance` — signed top-of-book size
  imbalance (KYLE_INFO family); the level-invariant transform of the
  Stoikov micro-price deviation from mid. A recognised
  ``_FAMILY_FINGERPRINT_SENSORS["KYLE_INFO"]`` member (G16 rule 5).
- :mod:`feelies.sensors.impl.ofi_raw` — per-event, unsmoothed Order-Flow
  Imbalance (KYLE_INFO family); the windowed-sum input for the
  ``ofi_integrated`` feature (no shipped alpha depends on it yet).
"""
