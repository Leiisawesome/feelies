# Core Primitives Audit — Clock / Config / Events / Serialization / StateMachine

- **Date:** 2026-06-25
- **Scope:** `src/feelies/core/` (clock, session_clock, config, config_yaml,
  platform_config, events, identifiers, errors, serialization, inv12_stress,
  state_machine) + `tests/core/`
- **Mode:** Read-only, evidence-based. No production code modified.
- **Test baseline:** `uv run pytest tests/core/ -q` → **208 passed in 0.64s**
  (clean; the three known main-branch acceptance failures live under
  `tests/acceptance/`, out of scope here).
- **Invariants in focus:** Inv-5 (bit-identical replay), Inv-7 (typed events),
  Inv-10 (clock abstraction), deterministic/non-mutating config merge.

Each finding is tagged **[bug]** (implementation defect), **[limitation]**
(documented/known gap), or **[design]** (intentional, flagged for awareness).

---

## 1. Executive summary

Top foundational risks first.

1. **Core is in good shape.** The two highest-stakes paths — the
   NBBOQuote/Trade serialization round-trip (Inv-5) and the generic
   `StateMachine` atomicity contract (promotion-ledger reliance) — are both
   **correct and verified empirically**. No P0 was found.
2. **[P1, bug] Lone wall-clock read in core:** `PlatformConfig.snapshot()`
   calls `time.time_ns()` directly (`platform_config.py:979`) instead of
   routing through an injected `Clock`. It is the only raw wall-clock read in
   `core/` outside the `WallClock` primitive itself. It does **not** break
   Inv-5 (the field is excluded from the checksum — verified), so it is P1, not
   P0, but it violates the Inv-10 discipline ("no raw wall-clock in core").
3. **[P1, bug] Serialization has no schema/version tag** and mishandles
   forward-schema data. An event dict carrying an unknown future field raises an
   **uncaught `TypeError`** from `cls(**work)` (`serialization.py:112`),
   contradicting both the class docstring ("Schema evolution handled
   explicitly") and the documented `deserialize` contract ("Raises
   `ValueError`"). Verified empirically.
4. **[P1, bug] Weak YAML type coercion in `PlatformConfig.from_yaml`.**
   `bool(...)`, `int(...)`, `float(...)` wrappers accept anything truthy:
   `bool("false") → True`, `int(5.7) → 5` (silent truncation), `int("5")`
   string→number auto-parse. This is exactly the strictness the audit asks
   about (bool-not-int, no string→number). Verified empirically.
5. **[P1, bug] Unknown YAML keys are silently ignored.** `from_yaml` reads only
   known keys via `data.get(...)`; a typo'd override key (e.g.
   `cost_stress_multipler`) is dropped with no error or warning → the operator's
   intended override silently no-ops. Fail-**open** direction (config drift).
6. **[design/verified] Config merge is correct.** `deep_merge_mapping`
   (`config_yaml.py:16`) is non-mutating (copies via `dict(base)`, returns fresh
   nested dicts), deterministic, and `extends:` inheritance guards both cycles
   and depth.
7. **[verified] StateMachine atomicity holds for the single-callback case** —
   callbacks fire pre-commit; a raising callback leaves state and history
   untouched (`state_machine.py:148-166`; test
   `test_callback_raises_prevents_transition`).
8. **[P2, limitation] StateMachine multi-callback partial execution.** If a
   later callback raises, an earlier callback's *external* side effects (e.g. a
   ledger file already appended) are not rolled back — the SM rolls back only
   its own state. Docstring slightly overpromises ("no side effects remain").
   Untested.
9. **[verified] All seven `StateMachine` consumers use the generic primitive
   consistently** — macro, micro, order, risk-escalation, alpha-lifecycle (the
   five named SMs) plus normalizer/data-integrity health machines.
10. **[verified] Serialization round-trip is type-faithful** for the two
    supported events: `Decimal` keeps precision and trailing zeros, `tuple`
    fields restore as tuples (not lists), `None` preserved, and re-serialization
    is byte-identical.
11. **[design] Only `NBBOQuote`/`Trade` are serializable;** all other event
    types raise `ValueError` on `serialize`. Intentional (market-data
    persistence only) but means the serializer is not a general event-log codec.
12. **[P2, bug-latent] Tuple round-trip is type-narrow.** Restoration keys on
    the substring `"tuple[int"` (`serialization.py:108`); a future
    `tuple[str, ...]` field on a market event would silently round-trip as a
    `list`, an Inv-5 hash drift. No such field exists today (latent).
13. **[P2, bug] Events are not deeply immutable.** Frozen dataclasses with
    mutable `dict` fields (`Signal.metadata`, `RiskVerdict.constraints`,
    `MetricEvent.tags`, `HorizonFeatureSnapshot.values/warm/stale`, …) can be
    mutated in place, violating "immutable after creation, safe to share without
    copying" (`events.py:33-43`) and making those events unhashable.
14. **[P2, design] `SequenceGenerator` is thread-safe but not order-
    deterministic across threads** (`identifiers.py:28-41`). Uniqueness holds;
    assignment *order* under concurrency does not. Only matters in live/paper
    (multi-threaded); replay/backtest is single-threaded so Inv-5 is safe.
15. **[note] `validate()` is not auto-invoked by `from_yaml`** — the caller
    (bootstrap) must call it. Comprehensive range checks exist, but a config
    constructed and used without `validate()` skips them.

---

## 2. Primitive inventory

| Primitive | File | Surface | Notes |
|-----------|------|---------|-------|
| `Clock` (Protocol) | `clock.py:13` | `now_ns() -> int` | Injection contract |
| `WallClock` | `clock.py:21` | `now_ns` = `time.time_ns()` | Production clock (intentional wall read) |
| `SimulatedClock` | `clock.py:30` | `now_ns`, `set_time` (rejects backward) | Deterministic; Inv-5 anchor |
| `rth_open_ns` | `session_clock.py:25` | pure `(ts_ns)->int` | DST-correct via `zoneinfo`, integer-exact |
| `ConfigSnapshot` | `config.py:19` | frozen dc (version, ts_ns, author, data, checksum) | Provenance record |
| `Configuration` (Protocol) | `config.py:34` | version/symbols/snapshot/validate | Typed config contract |
| `deep_merge_mapping` | `config_yaml.py:16` | non-mutating recursive merge | Scalars/seqs replace |
| `load_yaml_mapping` | `config_yaml.py:34` | `extends:` inheritance | Cycle + depth(16) guards |
| `PlatformConfig` | `platform_config.py:59` | ~190 fields, `from_yaml`/`validate`/`snapshot` | Concrete config |
| `Event` + 25 subclasses | `events.py:30+` | frozen, kw_only dataclasses | Inv-7 typed catalog |
| `make_correlation_id` | `identifiers.py:9` | `{sym}:{ts}:{seq}` | Deterministic |
| `derive_order_id` | `identifiers.py:18` | sha256[:16] of seed | 64-bit truncation |
| `SequenceGenerator` | `identifiers.py:28` | locked counter | Thread-safe uniqueness |
| Error taxonomy | `errors.py:10-53` | `FeeliesError` + 11 subclasses | Crash/degrade/retry mapping |
| `event_to_dict`/`dict_to_event` | `serialization.py:55,77` | NBBOQuote/Trade ↔ dict | Decimal→str, tuple→list |
| `JsonLineEventSerializer` | `serialization.py:115` | `serialize`/`deserialize` bytes | JSONL, bit-deterministic |
| Inv-12 stress | `inv12_stress.py:29-55` | 1.5× cost / 2× latency, pure `replace` | Inv-5-safe |
| `StateMachine[S]` | `state_machine.py:52` | `transition`/`reset`/`on_transition` | Generic, frozen table |
| `TransitionRecord` | `state_machine.py:25` | frozen audit record | Inv-13 |

**State-machine consumers (all use the generic primitive):**
macro (`kernel/macro.py:120`), micro (`kernel/micro.py:220`), order
(`execution/order_state.py:87`), risk-escalation (`risk/escalation.py:62`),
alpha-lifecycle (`alpha/lifecycle.py:271`), plus normalizer health
(`ingestion/massive_normalizer.py:777`) and data-integrity
(`ingestion/data_integrity.py:97`).

---

## 3. Clock-abstraction audit (Inv-10) — deep dive

A repo-wide grep for `datetime.now|datetime.utcnow|time.time|time.perf_counter|
time.monotonic|date.today` across `src/feelies/` yields the following. Each is
classified core vs. non-core.

| Site | Call | In `core/`? | Verdict |
|------|------|-------------|---------|
| `clock.py:27` | `time.time_ns()` | yes | **OK** — this *is* `WallClock`, the production clock primitive (DTZ-exempt by design). |
| `platform_config.py:979` | `time.time_ns()` | **yes** | **[P1, bug]** Raw wall-clock in core logic — see below. |
| `ingestion/massive_ingestor.py:326-336` | `time.monotonic()` | no | Progress-callback wall timing (off the deterministic path). |
| `kernel/orchestrator.py` (×6) | `time.perf_counter_ns()` | no | Tick-latency *telemetry* only; not fed into outputs. |
| `harness/backtest_*.py` (many) | `time.monotonic()` | no | Operator progress meters. |
| `broker/ib/connection.py:166` | `time.monotonic()` | no | Live socket readiness deadline. |
| `bootstrap.py:2251` | `time.time()` | no | Explicitly guarded last-resort with a warning that it breaks Inv-5. |
| `sensors/registry.py`, `monitoring/structured_logging.py` | — | n/a | Comments *prohibiting* wall-clock; no live calls. |

### A.1 — `PlatformConfig.snapshot()` reads wall clock — **[P1, bug]**

```python
# platform_config.py:973-983
def snapshot(self) -> ConfigSnapshot:
    data = self._to_dict()
    raw = json.dumps(data, sort_keys=True, default=str)
    checksum = hashlib.sha256(raw.encode()).hexdigest()
    return ConfigSnapshot(
        version=self.version,
        timestamp_ns=time.time_ns(),   # ← raw wall clock in core
        ...
    )
```

- **Falsifiable claim:** two `snapshot()` calls on the same config produce
  **different** `timestamp_ns` but the **same** `checksum`. Verified:
  `checksum deterministic: True`, `timestamp_ns differs: True`.
- **Why it is P1, not P0:** `timestamp_ns` is *not* part of `_to_dict()`, so it
  never enters the SHA-256 checksum that gates replay reproducibility (audit
  A-DET-02 path). Inv-5 is intact.
- **Why it is still a finding:** by the literal Inv-10 rule ("all timestamps via
  injectable clock; no raw wall-clock in core") this is a violation — `snapshot()`
  accepts no `clock` or `ts_ns` argument and has no way to be made deterministic
  by a caller. Two snapshots of an identical config are not bit-identical
  records.
- **Distinction:** implementation bug (the method *could* accept `ts_ns`), with
  a mitigating design (checksum exclusion) that keeps the platform invariant
  that actually matters (Inv-5) safe.

### A.2 — Injectability is otherwise airtight

- `StateMachine.__init__` **requires** `clock: Clock` with no default
  (`state_machine.py:75-81`); there is no silent fallback to `WallClock`.
- `SimulatedClock.set_time` rejects backward movement (`clock.py:46-47`),
  enforcing monotonicity for replay.
- The `Clock` Protocol is a pure `now_ns() -> int`; no hidden state.

### A.3 — `session_clock.rth_open_ns` — **[OK]**

- Pure function of `ts_ns`; **no** wall-clock read (`session_clock.py:25-36`).
- DST handled correctly: the ET offset is resolved per-date via `zoneinfo`
  (`astimezone(_TZ_ET)` then `datetime.combine(..., tzinfo=_TZ_ET)`), so 09:30
  ET maps to the right UTC instant on both EST and EDT dates.
- Integer-exact: input split into whole seconds + remainder before the tz math,
  so no float touches the nanosecond field. The returned value is always a whole
  second × 1e9 (09:30:00 has no sub-second part) — correct and deterministic.
- **Limitation (by design):** hardcoded to US-equities 09:30 RTH open
  (`session_clock.py:21-22`). Early-close (half) days do **not** move the *open*,
  only the close, so anchoring is unaffected — no bug. A non-US session_kind
  would need a different anchor; out of current scope.

---

## 4. Serialization round-trip audit (Inv-5)

`event_to_dict` (`serialization.py:55`) / `dict_to_event` (`serialization.py:77`)
support **only** `NBBOQuote` and `Trade`. Round-trip verified empirically
(serialize → deserialize → `==`, then re-serialize for byte-identity).

### Per-type / per-field fidelity

| Type | Field kind | Encoded as | Restored as | Fidelity |
|------|-----------|-----------|-------------|----------|
| `NBBOQuote` | `bid`/`ask` `Decimal` | `str` | `Decimal(str(v))` | ✅ precision + trailing zeros (`"150.1200"` ↔ `Decimal("150.1200")`) |
| `NBBOQuote` | `conditions`/`indicators` `tuple[int,...]` | `list` | `tuple` | ✅ tuple restored |
| `NBBOQuote` | `participant_/trf_/received_ns` `int\|None` | `null` | `None` | ✅ |
| `NBBOQuote` | `bid_size`/`exchange`/`tape` `int` | `int` | `int` | ✅ |
| `Trade` | `price` `Decimal` | `str` | `Decimal` | ✅ |
| `Trade` | `conditions` `tuple[int,...]` | `list` | `tuple` | ✅ |
| `Trade` | `decimal_size` `str\|None` | `str`/`null` | `str`/`None` | ✅ (type string lacks `"Decimal"`, correctly *not* coerced) |
| `Trade` | `trf_id`/`correction` `int\|None` | `null` | `None` | ✅ |
| base `Event` | `source_layer` `str` (default) | `str` | `str` | ✅ |
| **all other events** (`Signal`, `OrderAck`, …) | — | — | — | ❌ `serialize` raises `ValueError` (design) |

Empirical results: `QUOTE round-trip eq: True`, `conditions type after rt:
tuple`, `bid preserves trailing zeros: 150.1200`, `bit-identical re-serialize:
True`, `TRADE round-trip eq: True`.

### B.1 — Determinism mechanism — **[OK, but implicit]**

- Key order = `__type__` first, then `__dataclass_fields__` iteration (base
  fields before subclass fields), and `json.dumps` preserves insertion order
  (no `sort_keys` needed). Stable across processes.
- **Fragility note:** determinism is *implicit* in dataclass field order + dict
  insertion order rather than enforced by `sort_keys`. Reordering field
  definitions would silently change the on-disk bytes (and any external hash of
  them). Not a bug today; a documented sensitivity.

### B.2 — No schema/version tag; forward-schema crashes — **[P1, bug]**

- The only discriminator is `__type__`; there is **no** version field. The
  module docstring claims "Schema evolution handled explicitly (not silently
  dropped)" (`serialization.py:8-9`) — this is not implemented.
- **Falsifiable:** deserializing a dict with an extra future field raises
  `TypeError: NBBOQuote.__init__() got an unexpected keyword argument
  'future_field'` from `cls(**work)` (`serialization.py:112`). The
  `deserialize` docstring promises `ValueError` on bad data
  (`serialization.py:48-51`); the `TypeError` escapes unconverted. Verified.
- *Missing* new fields are tolerated (defaults fill in) — additive evolution
  works one-way only.

### B.3 — Tuple restoration is type-narrow — **[P2, latent bug]**

- `dict_to_event` restores tuples only when the field-type string contains
  `"tuple[int"` (`serialization.py:108`). A hypothetical `tuple[str, ...]` or
  `tuple[float, ...]` field on a market event would deserialize as a **list**,
  so `deserialize(serialize(e)) != e` and the re-serialized bytes would differ →
  Inv-5 break. No such field exists on `NBBOQuote`/`Trade` today, so this is
  latent, not live.

---

## 5. Config-layering audit

### Precedence (lowest → highest)

For platform YAML:
1. `PlatformConfig` field defaults (`platform_config.py:67+`).
2. `extends:` base file(s), deep-merged (`config_yaml.py:77-79`).
3. The leaf YAML file's own keys (override the base).

For gate thresholds, an additional documented chain
(`platform_config.py:654-664`): `GateThresholds()` defaults →
`platform.yaml: gate_thresholds` → per-alpha `promotion.gate_thresholds`.

### C.1 — Merge is non-mutating & deterministic — **[OK, verified]**

```python
# config_yaml.py:16-31
def deep_merge_mapping(base, override):
    merged = dict(base)                 # copy — base never mutated
    for key, override_val in override.items():
        ...
        merged[key] = deep_merge_mapping(base_val, override_val)  # fresh dicts
```

- Non-mutating (top-level copy + recursion returns new dicts), deterministic
  (pure function of inputs, dict-order preserving), and `extends:` resolution
  guards cycles (`config_yaml.py:45-47`) and depth ≤ 16
  (`config_yaml.py:48-51`).
- Sequences and scalars in the override **replace** the base value wholesale —
  documented (`config_yaml.py:20-21`). Reasonable; flagged only so operators
  know lists don't merge.

### C.2 — Type coercion is weak — **[P1, bug]**

`from_yaml` coerces every scalar through `bool(...)`, `int(...)`, `float(...)`:

- `bool(data.get("flag", False))`: a *quoted* YAML string `"false"` →
  `bool("false") == True`. (Unquoted `false` is fine because `yaml.safe_load`
  pre-parses it to Python `False`.) No "must be a real bool" check.
- `int(...)`: `int(5.7) → 5` — a float in YAML where an int is expected is
  **silently truncated**, not rejected.
- `int("5")` / `float("5")`: string→number **auto-parse** is accepted, contrary
  to the strict-typing posture the audit asks about.

Verified: `bool('false') = True`, `int(5.7) = 5`, `int('5') = 5`.

### C.3 — Unknown keys silently ignored — **[P1, bug]**

- `from_yaml` reads only known keys via `data.get(name, default)`; there is no
  pass that rejects or warns on keys it didn't consume. A typo (e.g.
  `cost_stress_multipler:`) is silently dropped and the field keeps its default.
- Direction is **fail-open** (silent config drift): the operator believes an
  override is in effect when it is not. Note: two *deprecated* keys
  (`cost_exchange_per_share`, `passive_rebate_per_share`) *do* get warnings
  (`platform_config.py:1238-1246`), so the warning machinery exists — it just
  isn't applied to unknown keys generally.

### C.4 — `validate()` not auto-called — **[note/limitation]**

- `from_yaml` returns `cls(...)` without calling `validate()`
  (`platform_config.py:1371-1645`). The (thorough) range checks in
  `validate()` (`platform_config.py:673-971`) only run if the caller invokes
  them. Bootstrap does; ad-hoc construction paths may not.

### C.5 — Snapshot determinism hygiene — **[OK]**

- `_to_dict` normalizes all `Path` fields to `.name` (basename)
  (`platform_config.py:985-992`) so absolute filesystem paths don't leak into
  the checksum — correct for cross-machine reproducibility. Non-default-only
  serialization of `composition_signal_max_age_seconds` /
  `composition_optimizer_mode` (`platform_config.py:1187-1196`) keeps legacy
  checksums bit-stable.

---

## 6. StateMachine primitive audit

### D.1 — Transition atomicity — **[OK, verified]**

```python
# state_machine.py:148-166
if not self.can_transition(target):
    raise IllegalTransition(...)
record = TransitionRecord(...)            # build (immutable)
for callback in self._on_transition_callbacks:
    callback(record)                      # notify — may raise/veto
self._history.append(record)              # commit
self._state = target                      # commit
```

- Validate → build → notify → commit ordering is correct: state and history are
  written **only after** all callbacks succeed. A raising callback leaves the SM
  unchanged. Verified by `test_callback_raises_prevents_transition`
  (`tests/core/test_state_machine.py:96-106`): asserts `state == A` and
  `history == 0` after a vetoing callback.
- This is precisely the contract the promotion ledger relies on (skill glossary:
  "a ledger-write failure rolls the SM back atomically"). The
  `AlphaLifecycle` wiring registers `_record_to_ledger` via `on_transition`
  (`alpha/lifecycle.py:283`), so a failed ledger append vetoes the lifecycle
  transition. ✅

### D.2 — Multi-callback partial execution — **[P2, bug/limitation]**

- The SM rolls back **only its own** state. If two callbacks are registered and
  the second raises, the first's *external* side effects (a file already
  written, a list already appended) persist. The docstring "If a callback
  raises, no side effects remain" (`state_machine.py:145-146`) is true of the
  SM's own state but overstated for callback side effects.
- No test exercises the 2+ callback failure ordering. Low live impact today
  (lifecycle registers a single ledger callback; orchestrator registers a single
  `_emit_state_transition`), but the contract gap is real.

### D.3 — Illegal transitions & completeness — **[OK]**

- Illegal transitions raise `IllegalTransition` (`state_machine.py:148-149`;
  test `test_illegal_transition_raises`).
- `__init__` rejects an incomplete transition table — every enum member must
  appear as a key, so no state silently becomes terminal
  (`state_machine.py:91-101`; test `test_incomplete_transition_table_raises`).
- `reset()` intentionally bypasses table validation (documented unconditional
  reinit, `state_machine.py:168-198`) but preserves the same callback-pre-commit
  semantics and logs `metadata={"type": "reset"}`.

### D.4 — No replay-breaking hidden state — **[OK]**

- All non-determinism enters via the injected `clock`; `history` is per-instance
  and the `history` property returns a shallow copy (`state_machine.py:113`).
  Given a `SimulatedClock`, transitions are reproducible.
- Minor: `TransitionRecord.metadata` is a shared mutable dict (caller-owned);
  the record itself is `frozen=True` but its dict is mutable in place.

### D.5 — Consistent usage — **[OK, verified]**

All five named platform SMs plus the two ingestion health machines construct
`StateMachine[S]` with an injected clock (grep in §2). No bespoke
state-machine reimplementations were found.

---

## 7. Identifiers & events audit

### E.1 — Identifiers — **[OK / P2]**

- `make_correlation_id` (`identifiers.py:9-15`): `"{symbol}:{exch_ts}:{seq}"` —
  deterministic; collision-free as long as `(symbol, exchange_timestamp_ns,
  sequence)` is unique per emission (the `SequenceGenerator` guarantees per-run
  uniqueness).
- `derive_order_id` (`identifiers.py:18-25`): `sha256(seed)[:16]` — deterministic
  for replay; 64-bit truncation gives birthday-collision risk at ~2³² orders
  (irrelevant at intraday scale). **[OK]**
- `SequenceGenerator` (`identifiers.py:28-41`): lock guarantees *uniqueness* but
  not deterministic *assignment order* across concurrent callers. **[P2,
  design]** — only matters live/paper (multi-threaded); backtest replay is
  single-threaded so Inv-5 is unaffected.

### E.2 — Event immutability & v0.2-compatible defaults — **[OK / P2]**

- Every event is `@dataclass(frozen=True, kw_only=True)` (`events.py` passim) —
  no rebinding of fields. ✅
- v0.2/v0.3-compatible defaults are present and correct:
  `Signal.trend_mechanism=None`, `Signal.expected_half_life_seconds=0`
  (`events.py:250-251`), `RegimeState.calibrated=True`,
  `discriminability=+inf` (`events.py:189-190`), `source_layer="UNKNOWN"`
  (`events.py:43`) — additive, parity-preserving.
- **[P2, bug] Shallow immutability:** frozen events with mutable `dict`/nested
  fields (`Signal.metadata` `events.py:245`, `RiskVerdict.constraints` `:272`,
  `MetricEvent.tags` `:414`, `Alert.context` `:447`,
  `HorizonFeatureSnapshot.values/warm/stale` `:653-655`,
  `SizedPositionIntent.target_positions/mechanism_breakdown` `:704-708`) can be
  mutated in place. This contradicts "immutable after creation, safe to share
  without copying" (`events.py:33-43`) and makes those events unhashable (the
  generated `__hash__` raises on the dict field).

### E.3 — Error taxonomy — **[OK]**

- `FeeliesError` base + 11 typed subclasses mapping to failure modes
  (`errors.py:10-53`). Docstrings encode crash/degrade/retry intent. Clean and
  layer-agnostic. Minor hygiene only: severity/mode is encoded in prose
  docstrings, not a structured attribute (P2 nicety, not a defect).

---

## 8. Test gap matrix

| Invariant / behavior | Test(s) | Status |
|----------------------|---------|--------|
| `SimulatedClock` rejects backward time | `test_clock.py` | ✅ covered |
| Clock injectable / no wall fallback | `test_clock.py` | ✅ covered |
| `snapshot()` wall-clock isolation from checksum | — | ❌ missing |
| `rth_open_ns` DST correctness | `test_session_clock.py` | ◐ partial (add explicit EST↔EDT cases) |
| NBBOQuote/Trade round-trip | `test_serialization.py:84,89` | ✅ covered |
| Bit-determinism of serialize | `test_serialization.py:94` | ✅ covered |
| Decimal fidelity | `test_serialization.py:101` | ✅ covered |
| Tuple restored as tuple | `test_serialization.py:109` | ✅ covered |
| Reject non-market / corrupt / unknown type | `test_serialization.py:114,128,133` | ✅ covered |
| Round-trip **property** over all fields/random values | — | ❌ missing |
| Forward-schema (extra field) handling | — | ❌ missing (and currently a `TypeError`) |
| `deep_merge` nested + `extends` | `test_config_yaml.py:16,31` | ✅ covered |
| Merge **non-mutating** (base unchanged) | — | ❌ missing |
| Merge determinism property | — | ❌ missing |
| Weak coercion (`bool("false")`, `int(5.7)`) | — | ❌ missing |
| Unknown-key rejection/warning | — | ❌ missing (behavior absent) |
| `PlatformConfig.validate()` range checks | `test_platform_config*.py` | ✅ broad |
| SM illegal transition raises | `test_state_machine.py:66` | ✅ covered |
| SM incomplete table rejected | `test_state_machine.py:126` | ✅ covered |
| SM single-callback rollback | `test_state_machine.py:96` | ✅ covered |
| SM **multi-callback** partial-execution rollback | — | ❌ missing |
| Identifiers determinism | `test_identifiers.py` | ✅ covered |
| Event frozen / defaults | `test_events.py`, `test_new_events.py` | ✅ covered |
| Event deep-immutability (dict mutation) | — | ❌ missing (behavior is mutable) |

### Proposed minimal new tests (specs only)

1. **Round-trip property (serialization):** generate randomized
   `NBBOQuote`/`Trade` (random Decimals incl. trailing zeros, random `int`
   tuples, `None`/value optionals) and assert
   `deserialize(serialize(e)) == e` **and**
   `serialize(deserialize(serialize(e))) == serialize(e)` for N≥500 cases.
2. **Forward-schema contract:** assert that a dict with an unknown extra field
   raises **`ValueError`** (not `TypeError`) — pins the documented contract and
   would fail today, flagging B.2.
3. **Merge determinism + non-mutation:** assert `deep_merge_mapping(b, o)` (a)
   leaves `b` and `o` unchanged (deep-equal to pre-call copies) and (b) is
   order-independent for disjoint keys / idempotent for repeated application.
4. **SM rollback-on-callback-failure (multi-callback):** register two
   callbacks where the *second* raises; assert state/history unchanged **and**
   document/assert what happens to the first callback's effect (pins D.2).
5. **Snapshot determinism:** assert two `snapshot()` calls share a `checksum`
   (already true) and add a regression that the checksum is independent of
   `timestamp_ns` (guards A.1 against future leakage into `_to_dict`).
6. **Coercion strictness (if tightened):** assert quoted `"false"` and a float
   for an int field are rejected — would fail today, scoping C.2.

---

## 9. Prioritized backlog

Effort: **S** ≤ ½ day, **M** ≈ 1–2 days, **L** > 2 days. No fixes applied (this
pass is read-only).

### P0 — none found
The two invariant-critical paths (serialization round-trip Inv-5, SM atomicity)
are correct. No wall-clock in the deterministic tick/replay path, no lossy
round-trip on supported types, no non-deterministic merge.

### P1

| # | Component | `file:line` | One-sentence fix | Impact | Effort |
|---|-----------|-------------|------------------|--------|--------|
| P1-1 | `PlatformConfig.snapshot` wall clock | `platform_config.py:979` | Accept `ts_ns: int` (or a `Clock`) and pass it in; default to `WallClock` only at the bootstrap edge. | Restores Inv-10 discipline; makes snapshot records reproducible. | S |
| P1-2 | Serializer forward-schema / contract | `serialization.py:99-112` | Drop unknown keys (or wrap in `try/except TypeError → ValueError`) and add an explicit `__schema_version__` tag validated on load. | Honors `deserialize` contract; enables additive schema evolution without crashes. | M |
| P1-3 | Weak YAML coercion | `platform_config.py:1371-1645` | Add strict scalar coercers (reject non-bool for bools, reject float/str-with-fraction for ints) used uniformly in `from_yaml`. | Stops silent truncation / quoted-string truthiness config bugs. | M |
| P1-4 | Unknown YAML keys silently ignored | `platform_config.py:1216-1247` | After parsing, diff `data.keys()` against known fields (+ `extends`/`paper`/`gate_thresholds`/deprecated) and warn or raise on the remainder. | Eliminates silent override drift (fail-open → fail-loud). | S |

### P2

| # | Component | `file:line` | One-sentence fix | Impact | Effort |
|---|-----------|-------------|------------------|--------|--------|
| P2-1 | Tuple restoration too narrow | `serialization.py:108` | Match `"tuple"` (any element type) and restore element types by annotation, not just `tuple[int`. | Prevents latent list/tuple Inv-5 drift if a `tuple[str/float]` market field is ever added. | S |
| P2-2 | SM multi-callback partial execution | `state_machine.py:161-166` | Document the "earlier-callback side effects are not rolled back" caveat and/or run callbacks in a two-phase (validate-then-commit) protocol. | Clarifies/strengthens the promotion-ledger atomicity contract for >1 callback. | M |
| P2-3 | Events not deeply immutable | `events.py:245,272,414,447,653-708` | Use `MappingProxyType`/`frozendict` (or tuple-of-pairs) for dict fields, or document the shallow-immutability caveat. | Upholds "safe to share without copying"; restores hashability. | M |
| P2-4 | `SequenceGenerator` cross-thread order | `identifiers.py:28-41` | Document that deterministic ordering requires single-threaded use (replay); no change needed for backtest. | Prevents future live-path Inv-5 surprises. | S |
| P2-5 | `validate()` not auto-called | `platform_config.py:1371` | Optionally call `validate()` at the end of `from_yaml` (or document that bootstrap must). | Closes the "constructed-but-unvalidated config" gap. | S |
| P2-6 | Error taxonomy is prose-only | `errors.py:10-53` | Add a structured `failure_mode` attribute (crash/degrade/retry) per class. | Lets handlers branch on mode without parsing docstrings. | S |

---

### Appendix — verification commands run (read-only)

- `uv run pytest tests/core/ -q` → 208 passed.
- Serialization round-trip / forward-schema probe (NBBOQuote, Trade, Signal):
  confirmed Decimal+tuple+None fidelity, byte-identical re-serialize, `TypeError`
  on extra field, `ValueError` on missing `__type__` and on non-market event.
- Snapshot probe: confirmed `checksum` stable across calls while `timestamp_ns`
  varies; confirmed `bool("false")==True`, `int(5.7)==5`, `int("5")==5`.
- Repo-wide grep for wall-clock APIs across `src/feelies/` (table in §3).
