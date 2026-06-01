"""Broker adapters — concrete implementations of the OrderRouter protocol.

Sub-packages adapt a specific broker API (IB Gateway, etc.) to the
:class:`feelies.execution.backend.OrderRouter` protocol.  All broker-
specific imports MUST live inside these sub-packages — the
``feelies.execution`` layer continues to import only the protocols.
"""
