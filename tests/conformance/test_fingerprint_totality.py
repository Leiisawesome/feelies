"""R4 — the run fingerprint covers everything that can change output.

G06: alpha manifest content moves no checksum. G30: engine 12's forensic
outputs carry no fingerprint.

Scope is the resolved registry (the ``alpha_specs`` the run will load),
never the promotion ledger. The ledger is a wall-clock-stamped append-only
record of decisions, never read on the tick path; demanding its
reproducibility is unachievable. R4 states that exclusion rather than
discovering it.
"""

from __future__ import annotations

from pathlib import Path

from feelies.core.platform_config import PlatformConfig


def test_r4_fingerprint_covers_resolved_registry_not_promotion_ledger(
    tmp_path: Path,
) -> None:
    spec_one = tmp_path / "alpha_one.alpha.yaml"
    spec_two = tmp_path / "alpha_two.alpha.yaml"
    spec_one.write_text("threshold: 1.0\n", encoding="utf-8")
    spec_two.write_text("threshold: 2.0\n", encoding="utf-8")
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text("decision-a\n", encoding="utf-8")

    cfg = PlatformConfig(
        symbols=frozenset({"AAPL"}),
        alpha_specs=[spec_one, spec_two],
        promotion_ledger_path=ledger,
    )

    uncovered: list[str] = []
    for spec in (spec_one, spec_two):
        original = spec.read_text(encoding="utf-8")
        before = cfg.snapshot().checksum
        spec.write_text(original.replace("threshold: ", "threshold: 9"), encoding="utf-8")
        after = cfg.snapshot().checksum
        spec.write_text(original, encoding="utf-8")
        if after == before:
            uncovered.append(spec.name)
    assert not uncovered, f"manifest content moves no checksum: {uncovered[0]}"

    # Promotion ledger content is excluded: the ledger is never read on the
    # tick path, and a wall-clock-stamped append-only log cannot reproduce.
    restored = cfg.snapshot().checksum
    ledger.write_text("decision-b\n", encoding="utf-8")
    assert cfg.snapshot().checksum == restored, (
        "promotion ledger content must not enter the run fingerprint"
    )
