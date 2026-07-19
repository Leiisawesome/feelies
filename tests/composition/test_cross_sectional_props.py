"""Hypothesis property tests for mechanism-cap enforcement.

Composition audit 2026-07-02, finding P0-1: ``cap_family_vectors`` /
``CrossSectionalRanker._apply_mechanism_cap`` rescale one over-cap family at
a time, holding the others fixed -- exactly correct in one pass only when at
most one family is ever over cap simultaneously. With 2+ families
simultaneously over cap, a fixed iteration budget can leave a family's
realised share above its declared cap; the previous budget of 5 left a
confirmed ~9% relative overshoot for hand-picked 4-family cases even under
``trend_mechanism.consumes`` caps that legitimately pass G16 rule 8
(``sum(caps) >= 1.0``) at load time.

``test_cross_sectional.py`` locks that one hand-picked counter-example as a
regression test. This module instead generates a wide range of 3-5-family,
G16-valid cap configurations and raw gross distributions, asserting the
invariant the fix promises -- every family's realised share stays within its
declared cap -- holds broadly, not just for the one example we happened to
construct by hand.
"""

from __future__ import annotations

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from feelies.composition.cross_sectional import CrossSectionalRanker, cap_family_vectors
from feelies.core.events import TrendMechanism

_ALL_FAMILIES = tuple(TrendMechanism)
# Production warns when share exceeds cap by >1e-9 after the iteration budget,
# but simultaneous multi-family pressure can still leave a tiny float residue.
# Bound residual loosely enough for that noise while still catching the
# multi-percent overshoots this module was written to prevent.
_CAP_TOLERANCE = 1e-4


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
