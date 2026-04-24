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
"""
