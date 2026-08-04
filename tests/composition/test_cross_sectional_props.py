"""Property tests for convergent mechanism-cap enforcement."""

from __future__ import annotations

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from feelies.composition.cross_sectional import CrossSectionalRanker, cap_family_vectors
from feelies.core.events import TrendMechanism

_ALL_FAMILIES = tuple(TrendMechanism)
# The capped allocation is now solved directly rather than iterated to
# convergence, so a feasible configuration lands *on* its cap to float
# precision.  This tolerance was 1e-4 to absorb the old sweep's residual, which
# is exactly what let a real overshoot hide: a four-family case sat 1.0e-4 above
# cap, right at the bound.  Tightened to match the production backstop so the
# property can actually fail if the solve regresses.
_CAP_TOLERANCE = 1e-9


@st.composite
def _families_caps_and_gross(
    draw: st.DrawFn,
) -> tuple[tuple[TrendMechanism, ...], dict[TrendMechanism, float], dict[TrendMechanism, float]]:
    """Draw (families, per-family caps, per-family raw gross).

    ``n`` in [3, 5] targets the regime this finding is about (2-family
    configurations are arithmetically immune whenever both caps exceed 0.5,
    and are already covered by hand-picked unit tests). Caps are drawn from
    [0.1, 1.0] and filtered to sum to at least 1.0 (G16 rule 8's own load-time
    floor) so every generated configuration is one the platform would
    actually accept from an alpha author.
    """
    n = draw(st.integers(min_value=3, max_value=5))
    families = draw(st.permutations(list(_ALL_FAMILIES)).map(lambda perm: tuple(perm[:n])))
    caps_list = draw(
        st.lists(
            st.floats(min_value=0.1, max_value=1.0, allow_nan=False),
            min_size=n,
            max_size=n,
        )
    )
    assume(sum(caps_list) >= 1.0)
    gross_list = draw(
        st.lists(
            st.floats(min_value=0.01, max_value=10.0, allow_nan=False),
            min_size=n,
            max_size=n,
        )
    )
    caps = dict(zip(families, caps_list))
    gross = dict(zip(families, gross_list))
    return families, caps, gross


@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
@given(drawn=_families_caps_and_gross())
def test_cap_family_vectors_never_exceeds_declared_cap(
    drawn: tuple[
        tuple[TrendMechanism, ...], dict[TrendMechanism, float], dict[TrendMechanism, float]
    ],
) -> None:
    families, caps, gross = drawn
    vectors = {mech: {f"SYM_{mech.name}": gross[mech]} for mech in families}

    _scaled, breakdown = cap_family_vectors(vectors, (caps, 1.0))

    for mech, share in breakdown.items():
        assert share <= caps[mech] + _CAP_TOLERANCE, (
            f"{mech.name} share {share} exceeds cap {caps[mech]} "
            f"(families={[f.name for f in families]}, caps={ {k.name: v for k, v in caps.items()} }, "
            f"gross={ {k.name: v for k, v in gross.items()} })"
        )


@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
@given(drawn=_families_caps_and_gross())
def test_apply_mechanism_cap_never_exceeds_declared_cap(
    drawn: tuple[
        tuple[TrendMechanism, ...], dict[TrendMechanism, float], dict[TrendMechanism, float]
    ],
) -> None:
    families, caps, gross = drawn
    ranker = CrossSectionalRanker()
    weights = {f"SYM_{mech.name}": gross[mech] for mech in families}
    mechanism_by_symbol = {f"SYM_{mech.name}": mech for mech in families}

    _scaled, breakdown = ranker._apply_mechanism_cap(  # noqa: SLF001 -- exercising the fix directly
        weights, mechanism_by_symbol, (caps, 1.0)
    )

    for mech, share in breakdown.items():
        assert share <= caps[mech] + _CAP_TOLERANCE, (
            f"{mech.name} share {share} exceeds cap {caps[mech]} "
            f"(families={[f.name for f in families]}, caps={ {k.name: v for k, v in caps.items()} }, "
            f"gross={ {k.name: v for k, v in gross.items()} })"
        )


@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(drawn=_families_caps_and_gross())
def test_cap_family_vectors_breakdown_sums_to_one(
    drawn: tuple[
        tuple[TrendMechanism, ...], dict[TrendMechanism, float], dict[TrendMechanism, float]
    ],
) -> None:
    """The realised breakdown is a share partition -- it must sum to 1.0
    (modulo float tolerance) regardless of how the caps redistributed gross."""
    families, caps, gross = drawn
    vectors = {mech: {f"SYM_{mech.name}": gross[mech]} for mech in families}

    _scaled, breakdown = cap_family_vectors(vectors, (caps, 1.0))

    assert abs(sum(breakdown.values()) - 1.0) < 1e-6


def test_multi_family_cap_pressure_lands_exactly_on_cap() -> None:
    """Regression: the Gauss-Seidel sweep could not converge here.

    Hypothesis found this configuration. Three caps bind simultaneously and sum
    to 0.984375, so the old iterate-to-convergence sweep contracted by only
    ~0.984 per pass: after its 200-pass budget KYLE_INFO still sat 1.0e-4 above
    cap, and reaching the 1e-9 production tolerance would have taken ~1300
    passes. The required budget scales with the caps, so no fixed limit is
    correct — G16 rule 8's own floor (caps sum >= 1.0) is what pushes the
    contraction factor toward 1.

    A feasible allocation exists and is closed-form: with INVENTORY uncapped at
    gross 0.01 and the other three at their caps, total gross settles at
    0.01 / (1 - 0.984375) = 0.64. Pinned explicitly because the property test
    above only samples randomly and will not rediscover this reliably.
    """
    caps = {
        TrendMechanism.KYLE_INFO: 0.46875,
        TrendMechanism.INVENTORY: 1.0,
        TrendMechanism.HAWKES_SELF_EXCITE: 0.40625,
        TrendMechanism.LIQUIDITY_STRESS: 0.109375,
    }
    gross = {
        TrendMechanism.KYLE_INFO: 2.0,
        TrendMechanism.INVENTORY: 0.010000000000000002,
        TrendMechanism.HAWKES_SELF_EXCITE: 1.0,
        TrendMechanism.LIQUIDITY_STRESS: 2.0,
    }
    vectors = {mech: {f"SYM_{mech.name}": gross[mech]} for mech in caps}

    scaled, breakdown = cap_family_vectors(vectors, (caps, 1.0))

    for mech, cap in caps.items():
        assert breakdown[mech] <= cap + 1e-12, (
            f"{mech.name} share {breakdown[mech]} exceeds cap {cap}"
        )
    # The three binding families sit exactly on their caps, not merely under.
    for mech in (
        TrendMechanism.KYLE_INFO,
        TrendMechanism.HAWKES_SELF_EXCITE,
        TrendMechanism.LIQUIDITY_STRESS,
    ):
        assert abs(breakdown[mech] - caps[mech]) < 1e-12

    # Uncapped INVENTORY keeps its gross and absorbs the remaining share.
    total = sum(abs(v) for vec in scaled.values() for v in vec.values())
    assert abs(total - 0.64) < 1e-12
    assert abs(scaled[TrendMechanism.INVENTORY]["SYM_INVENTORY"] - 0.01) < 1e-15
