"""Concrete Layer-1 sensor implementations.

``PlatformConfig`` only imports sensor classes from this package. Instances
remain stateless; each symbol's mutable state comes from ``initial_state()``.
The package includes price, flow, liquidity, volatility, mechanism-fingerprint,
scheduled-flow, and structural-break sensors.
"""
