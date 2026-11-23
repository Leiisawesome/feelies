"""Real-day P-95 attribution report (D-253). Stub until the runner lands."""

from __future__ import annotations

from collections.abc import Sequence

from feelies.core.events import Alert, GateDecision, PositionClosed


def exit_mix(closed: Sequence[PositionClosed]) -> dict[str, int]:
    raise NotImplementedError("P-99a stub")


def refusal_counts(alerts: Sequence[Alert]) -> dict[str, int]:
    raise NotImplementedError("P-99a stub")


def suppression_counts(
    decisions: Sequence[GateDecision],
) -> tuple[int, dict[str, int]]:
    raise NotImplementedError("P-99a stub")


def main(argv: list[str] | None = None) -> int:
    raise NotImplementedError("P-99a stub")
