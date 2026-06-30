# Determinism & parity harness audit (Claude Code)

Use this prompt in a **Claude Code** session with full repo access. Scope: feelies
correctness immune system — the parity-hash baselines, the `parity_manifest`, the
determinism test suite, and the strict-mypy / DTZ scope locks that together enforce
Inv-5 (deterministic replay) across the platform.

---

## Mission

You are a senior test-infrastructure and reproducibility auditor. Perform a **read-only,
evidence-based audit** of the feelies determinism guarantees and the harness that pins
them.

**Primary focus:** The parity hashes are the platform's claim that "same log + params →
bit-identical outputs." Their value is exactly as strong as their **coverage and
pinning**. A hash that locks too little, a baseline that drifted, or a determinism test
that passes for the wrong reason gives false safety to every layer above.

**Goal:** Identify what the parity hashes actually pin vs. what they claim, which event
types / state transitions have **no** determinism coverage, where the scope locks
(mypy-strict, DTZ) could be silently weakened, and what minimal additions would close the
gaps — without changing production behavior.

**Do not implement fixes in this pass.** Deliver a structured audit report with
file/line citations, severity, and prioritized recommendations.

---

## Agent context (mandatory)

| Step | Resource |
|------|----------|
| 1 | `.cursor/rules/platform-invariants.mdc` — **Inv-5**; glossary: replay, strict typing |
| 2 | `.cursor/rules/karpathy-guidelines.mdc` |
| 3 | `.cursor/skills/README.md` — parity hash table canonical → this skill |
| 4 | `.cursor/skills/testing-validation/SKILL.md` (**owner**) — L1–L6 baselines, scope locks |
| 5 | `.cursor/skills/system-architect/SKILL.md` — ordering assumptions under test |

Never re-pin baselines during the audit pass.


**Shipped vs Not shipped:** Treat skill sections marked **Not shipped** as design
targets — P0 only if code/tests claim they are live.

**Finding bar:** P0/P1 items must cite `Inv-N` + `path:line`. Read-only pass per
`.cursor/rules/karpathy-guidelines.mdc`.

---

## Platform context (read first)

**Docs and config** (after Agent context):

1. Read `docs/three_layer_architecture.md` §12 (determinism & parity requirements),
   §13 (testing strategy).
   entry.


**Architecture (contractual):**

```
Eleven locked parity hashes (parity_manifest.py LOCKED_PARITY_BASELINES), six levels:
  L1: sensor_reading, v03_sensor_reading
  L2: horizon_tick, signal
  L3: horizon_feature_snapshot, sized_intent_decay_off, sized_intent_decay_on
  L4: portfolio_order, hazard_exit_order
  L5: regime_hazard_spike
  L6: regime_state
parity_manifest.py = registry of baselines + the canonical hash computation
determinism tests replay a fixed event log and assert the hash matches the pinned baseline
scope locks: mypy strict on all of src/feelies (no ignore_errors overrides); DTZ datetime ban
```

**Hard invariants (non-negotiable):**

- Inv-5: same event log + params → bit-identical signals, orders, PnL.
- A parity hash must lock **scope, ordering, and sequence allocation**, not just values.
- Scope locks are themselves locked by acceptance tests (no silent weakening).

---

## Scope — files to audit

### Parity harness

- `tests/determinism/parity_manifest.py` — baseline registry + hash computation
- `tests/determinism/test_parity_manifest.py` — manifest self-test

### The eleven baselines + supporting replays

- `tests/determinism/test_sensor_reading_replay.py`, `test_v03_sensor_replay.py`
- `tests/determinism/test_signal_replay.py`, `test_emit_signals_jsonl.py`
- `tests/determinism/test_sized_intent_replay.py`, `test_sized_intent_with_decay_replay.py`
- `tests/determinism/test_portfolio_order_replay.py`
- `tests/determinism/test_hazard_exit_replay.py`, `test_regime_hazard_replay.py`,
  `test_emit_hazard_spikes_jsonl.py`
- `tests/determinism/test_regime_state_replay.py`,
  `test_horizon_tick_replay.py`, `test_horizon_feature_snapshot_replay.py`
- `tests/determinism/test_legacy_sequence_isolation.py`
- Observational emit streams (not pinned hashes — assess whether they should be):
### Scope locks

- `tests/acceptance/test_mypy_strict_scope.py` — strict mypy + no-override assertion
- `pyproject.toml` — `[tool.mypy]`, ruff DTZ rule config

### Tests (cross-ref)

- `tests/causality/test_anti_lookahead.py`

**Out of scope:** the *correctness* of the math inside each layer (audited per layer);
here the question is **"is determinism truly pinned and broadly covered?"**

---

## Audit dimensions (answer each with evidence)

### A. What do the hashes actually pin? — highest priority

1. For each of the eleven baselines, state precisely what the hash covers: which fields,
   ordering, sequence numbers, correlation IDs. Does it lock *ordering and sequence
   allocation* or only output values?
2. Could a real determinism bug (reordered emission, reused sequence) pass the hash
   because the hash canonicalizes/sorts before hashing? Find any such laundering.
3. Are baselines pinned to a committed constant, or recomputed at test time (which would
   make the test tautological)?

### B. Coverage gaps

1. Enumerate every event type on the bus (`core/events.py`) and every state-machine
   transition. Which have a determinism/parity test and which **do not**?
2. Are decay-ON and decay-OFF both pinned (sized-intent)? Regime + hazard both pinned?
3. Is multi-symbol / multi-day ordering covered, or only single-symbol single-day?

### C. Baseline integrity

1. Has any baseline drifted from its documented value (git history of the pinned hashes)?
2. Is there a documented, gated procedure to update a baseline (with justification), or
   can it be silently re-pinned?
3. `parity_manifest` self-test: does it detect a missing/extra baseline?

### D. Scope locks

1. `test_mypy_strict_scope.py`: confirm it runs `mypy --no-incremental src/feelies` and
   asserts zero exit, **and** parses `pyproject.toml` to reject any
   `[[tool.mypy.overrides]]` with `ignore_errors = true` on `feelies.*`.
2. DTZ (datetime ban): is the ruff rule active across `src/feelies/`, and does any
   `# noqa`/per-file ignore re-open the `datetime.now()` door (Inv-10)?
3. Are third-party untyped imports handled at the call site (`# type: ignore[import-...]`)
   rather than via project-level overrides?

### E. Determinism test honesty

1. Do determinism tests assert *bit-identical* across two independent runs, or just that a
   single run matches a stored value (weaker)?
2. Any reliance on dict/set ordering, wall-clock, or environment that could make a test
   pass non-deterministically?

### F. Test & validation gaps + prioritized recommendations

1. Produce a **coverage matrix**: event type / SM transition × {pinned hash? two-run
   identity? cross-platform?}.
2. Propose **minimal** new baselines for uncovered event types — specs only, including the
   fixed event log they should replay.
3. Tiers:
   - **P0:** a hash that launders a real ordering/sequence bug, an uncovered
     capital-affecting event type, a silently re-pinnable baseline, a weakened scope lock.
   - **P1:** single-run-only assertions, missing multi-symbol coverage, decay/regime gaps.
   - **P2:** cross-platform determinism harness, baseline-update tooling.

Each item: component, `file:line`, one-sentence fix, expected impact on Inv-5 confidence.

---

## Working method

1. Read `parity_manifest.py` and list the registered baselines + the canonical hash fn.
2. For each baseline, open its replay test and record exactly what it hashes.
3. Diff the set of bus event types against the set of pinned hashes → coverage gaps.
4. Audit the scope-lock acceptance tests.
5. Cross-check findings against the owning skill's **Not shipped** sections before filing P0 on absent features.
6. Run **read-only** checks only:
   - `uv run pytest tests/determinism/ -q`
   - `uv run pytest tests/acceptance/test_mypy_strict_scope.py -q`
   - `uv run pytest tests/causality/test_anti_lookahead.py -q`
   Do not modify production code or re-pin any baseline.

---

## Output format (strict)

Write the audit report to `docs/audits/determinism_audit_YYYY-MM-DD.md` with these sections:

1. **Executive summary** (≤15 bullets): top false-safety risks first.
2. **Parity-hash scope table** (baseline → exactly what it pins).
3. **Coverage matrix** (event type / SM transition × coverage kind — deep dive).
4. **Baseline integrity audit** (drift, re-pin procedure).
5. **Scope-lock audit** (mypy strict, DTZ, no-override).
6. **Determinism-test honesty audit** (two-run vs stored-value).
7. **Test gap matrix** + proposed new baselines.
8. **Prioritized backlog** (P0/P1/P2, effort S/M/L).
9. **Appendix:** uncovered event types with proposed fixed logs.

Use code citations as `path:line` for every non-trivial claim.
Distinguish **harness weakness** vs **genuine coverage gap** vs **intentional scope**.

---

## Quality bar

- Prefer **falsifiable** statements ("the signal hash sorts emissions by symbol before
  hashing, so a real cross-symbol emission-order bug would not be caught") over adjectives.
- A hash that *launders* a determinism bug is worse than no hash — flag it P0.
- Treat any silently weakenable scope lock as a P0.
- Stay read-only: never re-pin a baseline to make a test pass.

---

## Optional follow-ups (paste after the audit)

- *"After the report, draft P0 fixes only for any hash that canonicalizes away ordering and
  any uncovered capital-affecting event type as a follow-up PR plan."*
- *"Produce the full event-type × parity-coverage matrix as a standalone table — audit
  commentary only."*
- *"Propose a two-run bit-identity wrapper for the determinism suite — spec only, no code."*
