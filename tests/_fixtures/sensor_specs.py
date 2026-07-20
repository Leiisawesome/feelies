"""Shared :class:`SensorSpec` catalogs for cross-cutting test setup.

Bootstrap and integration tests that exercise
SIGNAL-layer alphas with declared ``trend_mechanism:`` blocks need
catalogs that include the family fingerprint sensors enumerated in
:data:`feelies.alpha.layer_validator._FAMILY_FINGERPRINT_SENSORS`,
otherwise G16 (``MissingFingerprintSensorError``) blocks the alpha
at load.  Each integration test used to inline its own catalog; this
module collects the canonical mappings in one place so a hazard-
wiring or wiring-coverage test can import the union directly.

Per-family fingerprint sensors (per ``_FAMILY_FINGERPRINT_SENSORS``):

* ``KYLE_INFO``         — ``kyle_lambda_60s``, ``micro_price``
* ``INVENTORY``         — ``quote_replenish_asymmetry``
* ``HAWKES_SELF_EXCITE``— ``hawkes_intensity``
* ``LIQUIDITY_STRESS``  — ``vpin_50bucket``, ``realized_vol_30s``
* ``SCHEDULED_FLOW``    — ``scheduled_flow_window``

:data:`ALL_FINGERPRINT_SENSOR_SPECS` is the union; tests that only
need a subset can either import the per-family tuple or filter by
``sensor_id``.
"""

from __future__ import annotations

from feelies.core.events import NBBOQuote, Trade
from feelies.sensors.impl.hawkes_intensity import HawkesIntensitySensor
from feelies.sensors.impl.kyle_lambda_60s import KyleLambda60sSensor
from feelies.sensors.impl.micro_price import MicroPriceSensor
from feelies.sensors.impl.ofi_ewma import OFIEwmaSensor
from feelies.sensors.impl.quote_replenish_asymmetry import (
    QuoteReplenishAsymmetrySensor,
)
from feelies.sensors.impl.realized_vol_30s import RealizedVol30sSensor
from feelies.sensors.impl.scheduled_flow_window import ScheduledFlowWindowSensor
from feelies.sensors.impl.spread_z_30d import SpreadZScoreSensor
from feelies.sensors.impl.vpin_50bucket import VPIN50BucketSensor
from feelies.sensors.spec import SensorSpec


# ── Family-by-family fingerprint catalogs ──────────────────────────


KYLE_INFO_SENSOR_SPECS: tuple[SensorSpec, ...] = (
    SensorSpec(
        # Pin the causal, correct-sign alignment.
        sensor_id="kyle_lambda_60s",
        sensor_version="2.0.0",
        cls=KyleLambda60sSensor,
        params={"min_samples": 5},
        subscribes_to=(NBBOQuote, Trade),
    ),
    SensorSpec(
        sensor_id="micro_price",
        sensor_version="1.1.0",
        cls=MicroPriceSensor,
        params={},
        subscribes_to=(NBBOQuote,),
    ),
)

INVENTORY_SENSOR_SPECS: tuple[SensorSpec, ...] = (
    SensorSpec(
        sensor_id="quote_replenish_asymmetry",
        sensor_version="1.1.0",
        cls=QuoteReplenishAsymmetrySensor,
        params={"min_observations": 5},
        subscribes_to=(NBBOQuote,),
    ),
)

HAWKES_SELF_EXCITE_SENSOR_SPECS: tuple[SensorSpec, ...] = (
    SensorSpec(
        sensor_id="hawkes_intensity",
        sensor_version="1.2.0",
        cls=HawkesIntensitySensor,
        params={"warm_trades_per_side": 3},
        subscribes_to=(Trade,),
    ),
)

LIQUIDITY_STRESS_SENSOR_SPECS: tuple[SensorSpec, ...] = (
    SensorSpec(
        sensor_id="vpin_50bucket",
        sensor_version="1.1.0",
        cls=VPIN50BucketSensor,
        params={},
        subscribes_to=(Trade,),
    ),
    SensorSpec(
        sensor_id="realized_vol_30s",
        sensor_version="1.3.0",
        cls=RealizedVol30sSensor,
        params={"window_seconds": 30, "warm_after": 8},
        subscribes_to=(NBBOQuote,),
    ),
)

SCHEDULED_FLOW_SENSOR_SPECS: tuple[SensorSpec, ...] = (
    SensorSpec(
        sensor_id="scheduled_flow_window",
        sensor_version="1.2.0",
        cls=ScheduledFlowWindowSensor,
        params={},
        subscribes_to=(NBBOQuote,),
    ),
)

# Sensors not strictly required by G16 fingerprints but referenced
# by every shared SIGNAL fixture (cost / gate expressions).  Keeping
# them here avoids each consumer redeclaring the same two specs.
BASELINE_SUPPORT_SENSOR_SPECS: tuple[SensorSpec, ...] = (
    SensorSpec(
        sensor_id="ofi_ewma",
        sensor_version="1.1.0",
        cls=OFIEwmaSensor,
        params={"alpha": 0.1, "warm_after": 5},
        subscribes_to=(NBBOQuote,),
    ),
    SensorSpec(
        sensor_id="spread_z_30d",
        sensor_version="1.1.0",
        cls=SpreadZScoreSensor,
        params={},
        subscribes_to=(NBBOQuote,),
    ),
)


# ── Union catalogs ─────────────────────────────────────────────────


# Default catalog — includes every fingerprint sensor that loads from
# config defaults alone.  ``scheduled_flow_window`` is excluded here
# because it requires :attr:`PlatformConfig.event_calendar_path` to be
# set; tests that need :data:`SCHEDULED_FLOW_SENSOR_SPECS` must
# compose them in explicitly and provide an event calendar.
ALL_FINGERPRINT_SENSOR_SPECS: tuple[SensorSpec, ...] = (
    BASELINE_SUPPORT_SENSOR_SPECS
    + KYLE_INFO_SENSOR_SPECS
    + INVENTORY_SENSOR_SPECS
    + HAWKES_SELF_EXCITE_SENSOR_SPECS
    + LIQUIDITY_STRESS_SENSOR_SPECS
)


__all__ = [
    "ALL_FINGERPRINT_SENSOR_SPECS",
    "BASELINE_SUPPORT_SENSOR_SPECS",
    "HAWKES_SELF_EXCITE_SENSOR_SPECS",
    "INVENTORY_SENSOR_SPECS",
    "KYLE_INFO_SENSOR_SPECS",
    "LIQUIDITY_STRESS_SENSOR_SPECS",
    "SCHEDULED_FLOW_SENSOR_SPECS",
]
