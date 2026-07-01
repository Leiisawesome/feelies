# Core: clock, config, serialization & state-machine audit (Claude Code)

Use this prompt in a **Claude Code** session with full repo access. Scope: feelies
foundational core — the injectable clock (Inv-10), the layered config, event
serialization round-trip fidelity, identifiers, and the generic `StateMachine` primitive
shared by the platform's five SMs.

---

## Mission

You are a senior systems-correctness auditor. Perform a **read-only, evidence-based audit**
of the feelies `core/` package — the primitives every other layer depends on.

**Primary focus:** Core is small but load-bearing. Inv-10 (clock abstraction) and Inv-7
(typed events) originate here, and serialization fidelity underwrites Inv-5 (a backtest
that round-trips through disk must be bit-identical). A wall-clock leak, a lossy
serializer (Decimal/tuple), or a non-deterministic config merge poisons everything above.

**Goal:** Identify where the clock abstraction is airtight vs. leaky, where serialization
preserves vs. drops type information, where config precedence is deterministic and
documented, and where the shared `StateMachine` enforces its contract — without changing
behavior.

**Do not implement fixes in this pass.** Deliver a structured audit report with
file/line citations, severity, and prioritized recommendations.

---

## Agent context (mandatory)

| Step | Resource |
|------|----------|
| 1 | `.cursor/rules/platform-invariants.mdc` — **Inv-5, 7, 10**; glossary: replay, strict typing |
| 2 | `.cursor/rules/karpathy-guidelines.mdc` |
| 3 | `.cursor/skills/README.md` |
| 4 | `.cursor/skills/system-architect/SKILL.md` (**owner**) — clock, events, SM primitive |
| 5 | `src/feelies/core/inv12_stress.py` — Inv-12 stress helper (touchpoint for execution_fills) |

This audit **owns** `core/state_machine.py`; kernel/alpha_lifecycle are touchpoints.


Before running commands, follow `AGENTS.md` for environment/test guidance. If Claude Code
also loads `CLAUDE.md`, `AGENTS.md`, this prompt, and `.cursor/rules/` /
`.cursor/skills/` context take precedence for audit execution.

**Shipped vs Not shipped:** Treat skill sections marked **Not shipped** as design
targets — P0 only if code/tests claim they are live.

**Finding bar:** P0/P1 items must cite `Inv-N` + `path:line`. Read-only pass per
`.cursor/rules/karpathy-guidelines.mdc`.

---

## Platform context (read first)

**Docs and config** (after Agent context):

1. Read `docs/three_layer_architecture.md` §5 (event contracts), §9 (platform config).
   glossary entry.


**Architecture (contractual):**

```
clock.py / session_clock.py  → injectable clock (SimulatedClock vs wall clock)
config.py / config_yaml.py / platform_config.py → layered PlatformConfig (YAML → typed)
events.py / identifiers.py   → typed events, correlation IDs, sequence
serialization.py             → event ↔ JSON(L) round-trip
state_machine.py             → generic SM + on_transition (used by 5 platform SMs)
inv12_stress.py              → cost/latency stress multipliers
```

**Hard invariants (non-negotiable):**

- Inv-10: all timestamps via injectable clock; no raw `datetime.now()` in core logic.
- Inv-7: typed events; serialization preserves declared types.
- Inv-5: round-trip (serialize → load → replay) is bit-identical.
- Config merge is deterministic, non-mutating, and resolved once.

---

## Scope — files to audit

### Clock & time

- `src/feelies/core/clock.py`, `session_clock.py`

### Config

- `src/feelies/core/config.py`, `config_yaml.py`, `platform_config.py`

### Events & identifiers

- `src/feelies/core/events.py` — all typed event dataclasses
- `src/feelies/core/identifiers.py` — `make_correlation_id`, sequence
- `src/feelies/core/errors.py` — error taxonomy

### Serialization & stress

- `src/feelies/core/serialization.py` — round-trip
- `src/feelies/core/inv12_stress.py` — stress multipliers

### State machine

- `src/feelies/core/state_machine.py` — generic SM primitive

### Tests (spec + gap analysis)

- `tests/core/test_clock.py`, `test_session_clock.py`
- `tests/core/test_config.py`, `test_config_yaml.py`, `test_platform_config.py`,
  `test_platform_config_gate_thresholds.py`, `test_platform_config_phase2.py`,
  `test_platform_config_v03_strict.py`
- `tests/core/test_events.py`, `test_new_events.py`, `test_trend_mechanism_events.py`,
  `test_identifiers.py`, `test_errors.py`
- `tests/core/test_serialization.py`, `test_inv12_stress.py`, `test_state_machine.py`

**Out of scope:** layer-specific consumers of these primitives (audited separately);
here the focus is the **primitives themselves**.

---

## Audit dimensions (answer each with evidence)

### A. Clock abstraction (Inv-10) — highest priority

1. Grep `core/` (and ideally all of `src/feelies/`) for `datetime.now`, `time.time`,
   `time.perf_counter`, `date.today`. Any in core logic (vs DTZ-exempt rendering)?
2. Is the clock genuinely injectable everywhere a timestamp is needed? Any default that
   falls back to wall clock?
3. `session_clock`: session-open anchoring correct across timezones / DST / RTH?

### B. Serialization round-trip (Inv-5)

1. For each event type, round-trip serialize → deserialize. Are `Decimal`, `tuple`
   (e.g. trade conditions), enums, and `None` preserved exactly (no float coercion, no
   list-vs-tuple drift)?
2. Is field order / JSON key order deterministic?
3. Any schema/version tag, and is it validated on load?

### C. Config layering

1. Trace the merge precedence (skill defaults → `platform.yaml` → per-alpha where
   applicable). Non-mutating? Resolved once? Deterministic?
2. Type coercion: bool-not-int strictness, no string→number auto-parse — consistent?
3. Unknown/missing keys: fail loudly or silently defaulted? Fail-safe direction.

### D. Generic StateMachine primitive

1. Does `state_machine.py` reject illegal transitions and invoke `on_transition`
   atomically (rollback on callback failure — the contract the promotion ledger relies on)?
2. Is it free of hidden state that would break replay across instances?
3. Confirm the five platform SMs (macro, micro, order, risk-escalation, alpha-lifecycle)
   all use this primitive consistently.

### E. Identifiers & events

1. `make_correlation_id` / sequence: deterministic and collision-free given the event log?
2. Event dataclasses: immutable (frozen)? Typed fields with sane defaults that are
   v0.2-compatible (e.g. `trend_mechanism=None`, `expected_half_life_seconds=0`)?

### F. Test & validation gaps + prioritized recommendations

1. Map invariants (clock discipline, round-trip fidelity, deterministic merge, SM
   atomicity) to tests — **covered / partial / missing**.
2. Propose **minimal** new tests (round-trip property over all event types, merge-
   determinism property, SM rollback-on-callback-failure) — specs only.
3. Tiers:
   - **P0:** wall-clock in core, lossy serialization, non-deterministic merge, SM that
     commits on callback failure.
   - **P1:** weak type coercion, timezone/DST edge cases, missing schema tag.
   - **P2:** richer config validation, error-taxonomy hygiene.

Each item: component, `file:line`, one-sentence fix, expected impact.

---

## Working method

1. Build a **primitive inventory** (clock APIs, config layers, event types, SM users).
2. Grep for wall-clock usage across `src/feelies/` first.
3. Round-trip every event type through `serialization.py` and diff.
4. Audit the config merge and the generic SM atomicity.
5. Cross-check findings against the owning skill's **Not shipped** sections before filing P0 on absent features.
6. Run **read-only** checks only:
   - `uv run pytest tests/core/ -q`
   Do not modify production code.

---

## Output format (strict)

Write the audit report to `docs/audits/core_clock_config_audit_YYYY-MM-DD.md` with these sections:

1. **Executive summary** (≤15 bullets): top foundational risks first.
2. **Primitive inventory** (markdown table).
3. **Clock-abstraction audit** (every wall-clock candidate — deep dive).
4. **Serialization round-trip audit** (per-event-type fidelity table).
5. **Config-layering audit** (precedence, coercion, fail-safe).
6. **StateMachine primitive audit** (atomicity, illegal transitions).
7. **Identifiers & events audit**.
8. **Test gap matrix**.
9. **Prioritized backlog** (P0/P1/P2, effort S/M/L).

Use code citations as `path:line` for every non-trivial claim.
Distinguish **implementation bug** vs **documented limitation** vs **intentional design**.

---

## Quality bar

- Prefer **falsifiable** statements ("`serialization.py` decodes trade conditions to a
  list, not a tuple, so a reloaded event hashes differently → Inv-5 break") over
  adjectives.
- Any `datetime.now()` in core logic is a P0 (Inv-10).
- Any lossy round-trip is a P0 (Inv-5).
- Stay read-only; harden primitives without changing observable behavior.

---

## Optional follow-ups (paste after the audit)

- *"After the report, draft P0 fixes only for any wall-clock leak and any lossy event
  round-trip as a follow-up PR plan."*
- *"Write a round-trip property-test spec covering every event type in `events.py` —
  spec only, no code."*
