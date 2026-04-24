"""Level-3 baseline — ``SizedPositionIntent`` replay parity (decay ON).

Counterpart to :mod:`tests.determinism.test_sized_intent_replay` with
``CrossSectionalRanker(decay_weighting_enabled=True)``.  The decay
weighting introduces the ``exp(-Δt / hl)`` factor on raw scores; the
two replays must still produce a bit-identical
:class:`SizedPositionIntent` stream because every input timestamp is
a deterministic constant of the test fixture (Inv-5).
"""

from __future__ import annotations

# Reuse the helpers from the decay-OFF Level-3 fixture so the two
# baselines stay tightly coupled.  Any change to the underlying
# universe / signal book lights up both tests in the same commit.
from tests.determinism.test_sized_intent_replay import (  # noqa: E501
    _NUM_BOUNDARIES,
    _replay,
)


def test_two_replays_produce_identical_intent_hash_with_decay() -> None:
    hash_a, count_a = _replay(decay=True)
    hash_b, count_b = _replay(decay=True)
    assert count_a == count_b, (
        f"intent count drift across replays (decay ON): "
        f"{count_a} vs {count_b}"
    )
    assert hash_a == hash_b, (
        "Level-3 SizedPositionIntent (decay ON) hash drift across "
        f"identical replays!\n  a: {hash_a}\n  b: {hash_b}"
    )


def test_decay_changes_hash_vs_baseline() -> None:
    """Cross-check: decay-ON and decay-OFF must NOT collide.

    Guards against a regression where the decay branch is silently a
    no-op (e.g. multiplying by 1.0 because half-life is misread as 0).
    """
    decay_on_hash, _ = _replay(decay=True)
    decay_off_hash, _ = _replay(decay=False)
    assert decay_on_hash != decay_off_hash, (
        "decay-ON and decay-OFF replays produced identical hashes — "
        "decay weighting may be silently disabled"
    )


def test_intent_count_matches_boundary_count_with_decay() -> None:
    _hash, count = _replay(decay=True)
    assert count == _NUM_BOUNDARIES, (
        f"expected exactly {_NUM_BOUNDARIES} intents with decay ON, "
        f"got {count}"
    )
