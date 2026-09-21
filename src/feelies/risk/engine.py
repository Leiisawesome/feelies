"""Risk engine protocol — the sole gatekeeper between signal and execution.

The risk engine is independent and dominant.  It can veto any order
and trigger risk lockdown.  No strategy layer can bypass it (invariant 11).

Every order intent transits the risk engine; no direct
signal-to-execution path exists.
"""

from __future__ import annotations

from feelies.core.risk_protocol import RiskEngine as RiskEngine
