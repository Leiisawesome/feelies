"""Parsed ``exit_policy`` block (P-15). Load-time only; the engine is a stub."""

from __future__ import annotations

from dataclasses import dataclass

_NS_PER_SECOND = 1_000_000_000


@dataclass(frozen=True, slots=True)
class HorizonPolicy:
    T_ns: int
    cutoff_before_close_ns: int


@dataclass(frozen=True, slots=True)
class AdversePolicy:
    centre_ticks: int
    band_ticks: int
    lo_ticks: int
    hi_ticks: int
    blind_limit_ns: int
    crossing_ticks: int | None = None
    premium_bps: float | None = None


@dataclass(frozen=True, slots=True)
class FavorablePolicy:
    form: str
    quiet_limit_ns: int
    target_ticks: int | None = None
    giveback_spread_multiple: float | None = None
    ceiling_ticks: int | None = None


@dataclass(frozen=True, slots=True)
class ExitPolicy:
    archetype: str
    declared_shape: str | None
    curve_ref: str
    fee_round_trip_ticks: int
    horizon: HorizonPolicy
    adverse: AdversePolicy
    favorable: FavorablePolicy


def seconds_to_ns(seconds: int) -> int:
    return seconds * _NS_PER_SECOND
