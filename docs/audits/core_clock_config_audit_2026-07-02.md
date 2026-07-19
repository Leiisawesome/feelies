# Core: Clock, Config, Serialization & State-Machine Audit — 2026-07-02

- **Scope:** `src/feelies/core/` (`clock.py`, `session_clock.py`, `config.py`,
  `config_yaml.py`, `platform_config.py`, `events.py`, `identifiers.py`,
  `errors.py`, `serialization.py`, `inv12_stress.py`, `state_machine.py`) +
  `tests/core/`. Cross-checked against `src/feelies/` broadly for wall-clock
  discipline (Inv-10) per the audit brief.
- **Mode:** Read-only, evidence-based. No production code, tests, configs, or
  ledgers modified.
- **Test baseline:** `uv sync --all-extras` (clean install) then
  `uv run pytest tests/core/ -q` → **229 passed**, 1 warning (pinned
  `PYTHONHASHSEED` reminder, pre-existing, see §3).
- **Invariants in focus:** Inv-5 (bit-identical replay), Inv-7 (typed events),
  Inv-10 (clock abstraction), Inv-13 (provenance), deterministic/non-mutating
  config merge.

Each finding is tagged **[bug]** (implementation defect), **[limitation]**
(documented/known gap, accepted), or **[design]** (intentional). Findings are
additionally tagged **[NEW]** (first raised in this pass) or **[RECONFIRMED]**
(carried over from the prior audit below, still in the same state).

## 0. Relationship to the prior audit (2026-06-25)

`docs/audits/core_clock_config_audit_2026-06-25.md` covers the identical file
scope and recorded a remediation pass (its §0) that fixed all six P1s/P2s it
found in the same branch: the `snapshot()` wall-clock read, the missing
serialization schema tag / `TypeError`-vs-`ValueError` contract break, weak
YAML scalar coercion, silently-dropped unknown YAML keys, the narrow
`tuple[int`-only restoration match, and the undocumented SM/event/identifier
limitations (multi-callback rollback boundary, shallow event immutability,
`SequenceGenerator` cross-thread ordering, `FailureMode` taxonomy).

This pass **independently re-verified every one of those six fixes by reading
the current code** (not by trusting the prior report) and confirms **all six
are still in place and correct**:

| Prior finding | Current evidence it's fixed |
|---|---|
| P1-1 wall clock in `snapshot()` | `platform_config.py:973-994` — `snapshot(*, ts_ns: int \| None = None)`; bootstrap always passes `ts_ns=clock.now_ns()` (`bootstrap.py:741`); the `WallClock()` fallback (`:990`) is excluded from `_to_dict()`/checksum — verified empirically, §5.6 below |
| P1-2 no schema tag / `TypeError` escape | `serialization.py:36` `_SCHEMA_VERSION`, `:110-114` version check, `:143-148` `TypeError`→`ValueError`; `tests/core/test_serialization.py:137-167` cover all four cases |
| P1-3 weak YAML coercion | `platform_config.py:1678-1744` `_check_yaml_keys_and_types` rejects non-bool bools, float/str for `int`-typed fields |
| P1-4 unknown keys silently dropped | `platform_config.py:1705-1718` — WARN by default, `strict=True` opt-in raise |
| P2-1 tuple restore narrow (`"tuple[int"`) | `serialization.py:131` now matches bare `"tuple"`, generalized to any element type |
| P2-2..P2-6 (documentation fixes) | `state_machine.py:149-157` (rollback boundary) + `test_multi_callback_rollback_boundary`; `events.py:39-49` (shallow immutability); `identifiers.py:31-38` (cross-thread ordering); `errors.py` `FailureMode` enum — all present |

No regression was found in any of the six. This pass therefore focuses on
**what has changed or was missed since 2026-06-25** — new fields added to
`PlatformConfig`, and primitive-level angles the prior pass did not examine
(alias-fallback YAML parsing, snapshot defensive-copy consistency, SM thread
safety, identifier test coverage, DTZ lint-exemption scope vs. documentation).
Findings below are tagged **[NEW]** where they were not raised on 2026-06-25.

---

## 1. Executive summary

1. **No P0 found, again.** Consistent with 2026-06-25: no raw wall-clock read
   sits on the deterministic tick/replay path, no lossy round-trip exists for
   any type `serialization.py` claims to support, the YAML→`PlatformConfig`
   merge is deterministic (same input → same output, every time), and
   `StateMachine.transition()` never commits state/history when a callback
   raises. See §3–§6 for the evidence per dimension.
2. **[NEW, P1, bug] Falsy-zero YAML aliasing silently discards explicit
   operator overrides.** Four cost-bps fields in
   `PlatformConfig.from_yaml` resolve legacy/current aliases with Python `or`
   chains (`platform_config.py:1506-1525`): `data.get("cost_passive_adverse_selection_bps")
   or data.get("cost_adverse_selection_drain_bps") or 2.0`. Because `0.0` is
   falsy, an operator who explicitly sets
   `cost_passive_adverse_selection_bps: 0.0` gets **`2.0`** instead — silently.
   Reproduced empirically (§5.4). Zero test coverage anywhere in the repo.
   Contrast with the *correct* `is not None` pattern used one screen earlier
   in the same method for the `cost_taker/maker_exchange_per_share` legacy
   alias (`:1341-1347`) — one code path in the same function does this right,
   the other doesn't.
3. **[NEW, P1, bug] `PlatformConfig.snapshot()`'s "immutable" provenance
   record aliases live, mutable config state.** `_to_dict()` returns
   `"parameter_overrides": self.parameter_overrides` **without a defensive
   copy** (`platform_config.py:1011`), unlike the very next field,
   `regime_engine_options`, which *is* copied (`:1013`). Mutating
   `snapshot().data["parameter_overrides"]` mutates the live `PlatformConfig`
   instance — reproduced empirically (§5.6). This breaks the documented
   contract of `ConfigSnapshot` ("**Immutable**, serializable snapshot... for
   provenance", `config.py:21`), which is exactly the Inv-13 guarantee this
   audit is checking.
4. **[NEW, P1, test gap] `derive_order_id` — a determinism-critical primitive
   consumed at 6+ call sites across `risk/` and `kernel/orchestrator.py` for
   every order ID emitted by the platform — has zero direct unit tests.**
   `tests/core/test_identifiers.py` covers `make_correlation_id` and
   `SequenceGenerator` only. The prior audit's test-gap matrix labeled
   "Identifiers determinism" as "✅ covered" at the file level; that label
   does not hold at the function level.
5. **[NEW, P1, bug/gap] `StateMachine` has no thread-safety, unlike its
   sibling primitive `SequenceGenerator`.** `identifiers.py`'s
   `SequenceGenerator` has an explicit `threading.Lock` and a documented
   concurrency contract (`:31-38`). `state_machine.py`'s `StateMachine` has
   neither — `transition()`'s check-then-act sequence
   (`can_transition` → build record → run callbacks → append history → set
   state, `:159-177`) is unguarded. `OrderState` (one of the five named
   platform SMs, `execution/order_state.py:89`) is exercised in PAPER/LIVE
   mode where `broker/ib/connection.py` runs dedicated `_msg_thread` /
   `_writer_thread` reader threads (`:107-160`). **Not confirmed:** whether
   any call path actually invokes `.transition()` on the same SM instance
   from two threads concurrently — that requires tracing the live-execution
   call graph, out of this audit's file scope. Flagged as a real gap in the
   primitive's contract regardless of current exploitability.
6. **[NEW, P2, doc/CI hygiene] CLAUDE.md's DTZ-exemption claim is stale.**
   CLAUDE.md states *"Only `src/feelies/core/clock.py` is exempted (enforced
   by ruff CI)"*. `pyproject.toml:117-131` actually exempts **four** files:
   `clock.py`, two functional-test files (legitimately, network-timed tests),
   and `src/feelies/monitoring/structured_logging.py`. The last exemption's
   stated justification — "module-level helpers retain a wall-clock fallback
   for bootstrap-time error messages" — describes code that does not exist:
   the file is 59 lines, a `Protocol` + an `Enum`, with **zero** `datetime`/
   `time` references and no concrete implementation anywhere in the repo
   (verified by grep). The exemption is currently harmless (nothing in the
   file could trip DTZ) but pre-authorizes a future wall-clock read in that
   module without review.
7. **[RECONFIRMED, verified] Clock injectability is otherwise airtight.**
   `WallClock` is instantiated in exactly two places in all of `src/feelies/`:
   the primitive itself (`clock.py:27`) and the bootstrap composition root for
   PAPER/LIVE mode (`bootstrap.py:790`) — both are the intended composition
   boundary, not core decision logic.
8. **[RECONFIRMED, verified] `rth_open_ns` remains correct** — pure function
   of `ts_ns`, DST-safe via `zoneinfo`, integer-exact (seconds-then-multiply,
   never a float touches the ns field). §3.3.
9. **[NEW, informational] A second, independent ET-anchor implementation
   exists outside `core/`:** `execution/moc_session.py::et_clock_to_ns`
   computes the same "ET wall-clock time on a date → epoch ns" operation as
   `core/session_clock.py::rth_open_ns`, but with float-multiply-then-`int()`
   instead of `int()`-then-multiply. Empirically the two agree exactly across
   a 16-year, both-DST-sides sample (§3.4) — **no bug demonstrated** — but only
   the `core/` version is exact by construction; the other relies on float64
   headroom that narrows over calendar time. Low-priority hygiene item, not a
   `core/` defect.
10. **[RECONFIRMED, verified] Serialization remains scoped, by design, to
    `NBBOQuote`/`Trade` only** — the `EventSerializer` module docstring's
    "every event" framing is broader than its sole implementation
    (`JsonLineEventSerializer`); this is deliberate (disk-cache codec for the
    *input* market-data tape, not a general event-log codec) and is directly
    tested (`test_serialize_rejects_non_market_event`). §4.
11. **[RECONFIRMED, verified] `StateMachine` atomicity holds** for both the
    single-callback case and the documented multi-callback rollback boundary
    (rolls back its own state; does not/cannot undo an earlier callback's
    external side effects) — this is exactly the contract the promotion
    ledger depends on, and it is directly tested. §6.
12. **[RECONFIRMED, verified] All six `StateMachine` consumers** (macro,
    micro, order, risk-escalation, data-integrity, alpha-lifecycle) construct
    through the one generic primitive — no bespoke reimplementation found.
    §6.5.
13. **[NEW, P2, design] `PlatformConfig` is a mutable dataclass** (`@dataclass
    (kw_only=True)`, not `frozen=True`), unlike `ConfigSnapshot` and every
    `Event` subclass. No in-place mutation of a `PlatformConfig` instance was
    found anywhere in `src/feelies/` (all "modification" goes through
    `dataclasses.replace`, e.g. `inv12_stress.py:44`) — the immutability holds
    today by convention only, not by the type system.
14. **[NEW, P2, hygiene] Several small test-completeness gaps**, none
    invariant-threatening: `test_apply_inv12_stress_joint` doesn't assert
    `market_data_latency_ns` is doubled even though the code doubles it;
    `test_errors.py`'s parametrized suite omits 2 of 9 `FeeliesError`
    subclasses; `test_config_yaml.py` (3 tests) doesn't cover the
    `extends:` depth limit, a missing `extends` target, a non-mapping root, or
    a non-mutation regression guard for `deep_merge_mapping`. §7.
15. **Bottom line:** core primitives are in good shape and the 2026-06-25
    remediation held completely. The new findings are concentrated in one
    method (`PlatformConfig.from_yaml`'s alias resolution) and one
    cross-primitive asymmetry (`StateMachine` vs. `SequenceGenerator`
    thread-safety) rather than being spread evenly across the package.

---

## 2. Primitive inventory

| Primitive | File | Surface | Notes |
|-----------|------|---------|-------|
| `Clock` (Protocol) | `clock.py:13-18` | `now_ns() -> int` | Injection contract |
| `WallClock` | `clock.py:21-27` | `now_ns` = `time.time_ns()` | Production clock; only 2 call sites repo-wide |
| `SimulatedClock` | `clock.py:30-49` | `now_ns`, `set_time` (rejects backward) | Deterministic; Inv-5 anchor |
| `rth_open_ns` | `session_clock.py:25-36` | pure `(ts_ns) -> int` | DST-correct via `zoneinfo`, integer-exact; wired into `bootstrap.py:1658` |
| `ConfigSnapshot` | `config.py:19-31` | frozen dc (version, ts_ns, author, data, checksum) | Provenance record; `data` dict itself not deep-frozen |
| `Configuration` (Protocol) | `config.py:34-67` | version / symbols / snapshot / validate | `PlatformConfig` is the sole implementer |
| `deep_merge_mapping` | `config_yaml.py:16-31` | non-mutating recursive merge | Scalars/sequences replace wholesale |
| `load_yaml_mapping` | `config_yaml.py:34-79` | `extends:` inheritance | Cycle guard + depth cap 16 |
| `PlatformConfig` | `platform_config.py:59-1892` | ~215 fields, `from_yaml` / `validate` / `snapshot` / `_to_dict` | Concrete `Configuration`; mutable dataclass (§5.7) |
| `Event` + 21 subclasses | `events.py:30-775` | frozen, `kw_only` dataclasses | Inv-7 typed catalog; shallow immutability documented |
| `make_correlation_id` | `identifiers.py:9-15` | `"{symbol}:{exch_ts}:{seq}"` | Deterministic string format |
| `derive_order_id` | `identifiers.py:18-25` | `sha256(seed)[:16]` | Deterministic; **no direct test** (§7.1) |
| `SequenceGenerator` | `identifiers.py:28-51` | locked counter | Thread-safe uniqueness; documented cross-thread ordering caveat |
| Error taxonomy | `errors.py:9-91` | `FailureMode` enum + `FeeliesError` + 9 subclasses | Crash/degrade/retry/lockdown mapping |
| `event_to_dict` / `dict_to_event` | `serialization.py:62-148` | `NBBOQuote`/`Trade` ↔ dict | Decimal→str, tuple→list, schema-versioned |
| `JsonLineEventSerializer` | `serialization.py:151-176` | `serialize`/`deserialize` bytes | JSONL, bit-deterministic, scoped by design |
| Inv-12 stress harness | `inv12_stress.py:29-71` | 1.5× cost / 2× latency, pure `dataclasses.replace` | Inv-5-safe |
| `StateMachine[S]` | `state_machine.py:52-217` | `transition` / `reset` / `on_transition` / `can_transition` | Generic, frozen transition table, **no lock** |
| `TransitionRecord` | `state_machine.py:25-35` | frozen audit record | Inv-13; `metadata` dict is caller-owned/mutable |

**`StateMachine` consumers** (all via the generic primitive, confirmed by
grep for `StateMachine(`): macro (`kernel/macro.py:122`), micro
(`kernel/micro.py:222`), order (`execution/order_state.py:89`),
risk-escalation (`risk/escalation.py:64`), data-integrity
(`ingestion/data_integrity.py:104`), alpha-lifecycle
(`alpha/lifecycle.py:271`). No bespoke state-machine reimplementation exists
anywhere in `src/feelies/`.

---

## 3. Clock-abstraction audit (Inv-10) — deep dive

Repo-wide grep for `datetime\.now|time\.time\(\)|time\.perf_counter|date\.today|utcnow`
across `src/feelies/`, classified core vs. non-core:

| Site | Call | In `core/`? | Verdict |
|------|------|-------------|---------|
| `clock.py:27` | `time.time_ns()` | yes | **OK** — this *is* `WallClock`, the canonical, DTZ-exempted production clock. |
| `platform_config.py:990` | `WallClock().now_ns()` | yes | **[RECONFIRMED OK]** Fallback only when caller omits `ts_ns`; excluded from checksum; production call site (`bootstrap.py:741`) always passes `ts_ns=clock.now_ns()`. §3.2. |
| `kernel/orchestrator.py` (×8: `:2241,2455,2457,2606,2608,3072,5205,5219`) | `time.perf_counter_ns()` | no | Tick-latency **telemetry** (`_tick_timings`), not event timestamps or decisions. Out of `core/` scope (kernel audit territory); see §3.5 for a cross-reference note. |
| `bootstrap.py:2298` | `time.time()` | no | Bootstrap-time-only fallback in `_enforce_factor_loadings_freshness`, explicitly logged as breaking Inv-5; unaddressed by either audit's backlog. §3.6. |
| `bootstrap.py:790` | `return WallClock()` | no | Composition root for PAPER/LIVE mode — the intended, single place `WallClock` is selected. |
| `sensors/registry.py:152-155` | (comment only) | no | Documents a **prior, already-fixed** violation: "A-CLOCK-01: latency timing via `time.perf_counter_ns()` is prohibited in the deterministic dispatch path... removed accordingly." Institutional memory, not a live issue. |
| `monitoring/structured_logging.py` | (comment only, DTZ-exempted) | no | Zero actual `datetime`/`time` calls exist in the file. §3.7. |

### 3.1 — `SimulatedClock` / `WallClock` — **[OK]**

`clock.py` is 49 lines: a `Clock` Protocol (`now_ns() -> int`), `WallClock`
(`time.time_ns()`, `__slots__ = ()`), and `SimulatedClock` (`now_ns` returns a
stored int; `set_time` raises `ValueError` on any backward move,
`:46-47`). Minimal and exactly matches its documented contract — no hidden
defaulting, no partial state. `StateMachine.__init__` requires a `clock: Clock`
argument with no default (`state_machine.py:80`), so nothing in `core/` can
silently fall back to wall time.

### 3.2 — `PlatformConfig.snapshot()`'s `WallClock` fallback — **[RECONFIRMED intentional design, verified safe]**

```python
# platform_config.py:973-994
def snapshot(self, *, ts_ns: int | None = None) -> ConfigSnapshot:
    data = self._to_dict()
    raw = json.dumps(data, sort_keys=True, default=str)
    checksum = hashlib.sha256(raw.encode()).hexdigest()
    return ConfigSnapshot(
        version=self.version,
        timestamp_ns=ts_ns if ts_ns is not None else WallClock().now_ns(),
        ...
    )
```

This was the prior audit's P1-1 finding; it is now fixed and additionally
verified here: `_to_dict()` (`:996-1225`) never includes a `timestamp_ns` key,
so the checksum — the only field of `ConfigSnapshot` that gates replay
reproducibility — is provably independent of which branch fires. The sole
production call site, `bootstrap.py:741`
(`config.snapshot(ts_ns=clock.now_ns())`), always supplies the injected clock,
so the `WallClock()` branch is dead code on every real run today; it only
fires for ad hoc/test construction that omits `ts_ns`. No action needed.

### 3.3 — `session_clock.rth_open_ns` — **[RECONFIRMED OK]**

```python
# session_clock.py:25-36
def rth_open_ns(ts_ns: int) -> int:
    secs, _rem_ns = divmod(ts_ns, _NS_PER_SECOND)
    dt_et = datetime.fromtimestamp(secs, tz=timezone.utc).astimezone(_TZ_ET)
    open_et = datetime.combine(dt_et.date(), time(9, 30), tzinfo=_TZ_ET)
    return int(open_et.timestamp()) * _NS_PER_SECOND
```

Pure function of `ts_ns`, no wall-clock read. DST is resolved per-calendar-date
via `zoneinfo` (not a fixed UTC offset), and the arithmetic takes `int()` of
the **seconds** value first, then multiplies by `1_000_000_000` in pure
integer arithmetic — sidestepping any float-precision risk at nanosecond
magnitude. Live and tested: wired into `bootstrap.py:1658` for
`session_open_ns` derivation, and covered by 4 targeted tests
(`test_session_clock.py`) spanning same-day anchoring, integer-exactness,
both sides of the 2026 spring-forward transition (EST *and* EDT), and a
pre-open event anchoring forward to the same day's open. Hardcoded to the
09:30 ET US-equities open (`_RTH_OPEN_HOUR/_MINUTE`, `:21-22`) — documented
scope, not a bug; a non-US `market_id` would need a different anchor function,
out of current scope (`market_id`/`session_kind` fields exist on
`PlatformConfig` as forward hooks but only one anchor implementation exists).

### 3.4 — [NEW] A second ET-anchor implementation exists outside `core/` — **[informational, no bug demonstrated]**

`execution/moc_session.py:60-64` independently implements the same
"ET clock-time on a date → epoch ns" operation, consumed by
`execution/trading_session.py`'s RTH entry-gating (a *different* consumer than
`bootstrap.py`'s `session_open_ns`, which uses `core/session_clock.py`):

```python
# execution/moc_session.py:60-64
def et_clock_to_ns(session_date: date, clock_str: str) -> int:
    t = _parse_clock_time(clock_str)
    local = datetime.combine(session_date, t, tzinfo=_NY_TZ)
    return int(local.timestamp() * _NS_PER_SECOND)   # multiply-then-int
```

This computes the product in the opposite order from `rth_open_ns`
(float-seconds × 1e9, then truncate) rather than integer-seconds × 1e9. In
principle, float64's 53-bit mantissa can lose precision multiplying an
epoch-seconds value (~2^31 today) by 1e9 (~2^30) — the exact product needs
~61 bits. **This was checked empirically, not just asserted:** a script
comparing both functions across 16 years × 3 sample months × both DST sides
found **zero divergence** — every case landed on an exact multiple of 60
seconds (whole-minute clock strings only, via `_parse_clock_time`), which
supplies enough factors of 2 to keep the product inside the 53-bit-exact
range for the foreseeable calendar future. **Conclusion: not a live bug.**
Flagged only as a latent-fragility / consistency-hygiene note: `core/session_clock.py`'s
pattern is exact *by construction* (no float ever touches the nanosecond
field); `moc_session.py`'s is exact *empirically, for the inputs it happens to
receive today*. Recommend aligning `et_clock_to_ns` to the integer-safe
pattern for defense-in-depth — low priority, outside `core/`'s file scope, not
added to the `core/` backlog in §9.

### 3.5 — [cross-reference] Orchestrator's `time.perf_counter_ns()` telemetry — not a `core/` finding

`kernel/orchestrator.py` calls `time.perf_counter_ns()` at 8 sites to populate
`_tick_timings` (e.g. `signal_evaluate_ns`, `risk_check_ns`) for latency
`MetricEvent`s. This is monotonic-but-arbitrary-origin wall time, not epoch
time, and does not feed any trading decision or event-content hash — it is
telemetry. Noted for completeness because dimension A of the audit brief asks
for a repo-wide grep, and because it stands in mild tension with
`sensors/registry.py`'s explicit comment that this exact pattern
("A-CLOCK-01... prohibited in the deterministic dispatch path") was removed
from the sensor layer. The distinction holds today only because no locked
parity hash currently exercises `Orchestrator` itself (a gap independently
flagged by `docs/audits/kernel_audit_2026-06-24.md`); if that gap is ever
closed by hashing the full orchestrator-level bus stream, these
non-reproducible latency values would immediately break the new hash. Owned by
the kernel audit, not actioned here.

### 3.6 — [RECONFIRMED, still open] `bootstrap.py` factor-loadings freshness wall-clock fallback

`_enforce_factor_loadings_freshness` (`bootstrap.py:2298-2301`) falls back to
`time.time()` when `config.session_open_ns` is unset and the loadings file
carries no embedded `_meta.as_of_ns`, logging a warning that this "breaks
bit-identical replay." The 2026-06-25 audit's clock table already listed this
site ("Explicitly guarded last-resort with a warning") but did not assign it a
severity or backlog entry. Re-confirmed present and unchanged. It is
bootstrap-time-only (gates whether a run *starts*, not per-tick decision
logic) so it does not corrupt an in-progress replay, but it does mean the
same historical config + universe can pass bootstrap on one day and fail it
(`StaleFactorLoadingsError`) on another purely because of wall-clock drift —
a narrow reproducibility gap for the bootstrap *outcome* itself. Outside
`core/`'s file scope; carried forward here as still-open since neither audit
has tracked it to resolution.

### 3.7 — [NEW] DTZ lint-exemption scope vs. documentation — see §9 P2 item

Covered in full in the executive summary (item 6) and the backlog (§9); not
repeated here.

---

## 4. Serialization round-trip audit (Inv-5)

`event_to_dict` / `dict_to_event` (`serialization.py:62-148`) and the concrete
`JsonLineEventSerializer` (`:151-176`) support **only** `NBBOQuote` and
`Trade` — `serialize()` raises `ValueError` for anything else
(`:162-165`), which is directly asserted by
`test_serialize_rejects_non_market_event`. This is the durable codec for
`DiskEventCache` (`storage/disk_event_cache.py`) — the **input** market-data
tape that must replay bit-identically (Inv-5). It is not a general event-log
codec, and the module/Protocol docstrings ("Every event must be
serializable...", `:1-17`) read more broadly than the implementation — a
documentation-precision nit (§9 P2), not a functional gap: nothing else in the
codebase attempts to round-trip `Signal`/`OrderRequest`/etc. through this
module. Downstream forensic records (e.g. the promotion ledger,
`alpha/promotion_ledger.py:104`) use their own independent
`json.dumps(..., sort_keys=True, default=_json_default)` path, appropriately
out of scope for a bit-identical-replay contract since those records are
forensic-only and never fed back into decisions.

### Per-event-type fidelity

| Event type | Byte round-trip via `core/serialization.py`? | Frozen? | Notes |
|---|---|---|---|
| `NBBOQuote` | ✅ full (`Decimal`↔str, `tuple`↔list, `None`, all 17 fields) | ✅ | `test_serialization.py:84,101,109` |
| `Trade` | ✅ full | ✅ | `test_serialization.py:89` |
| `SymbolHalted` | ❌ not supported (by design) | ✅ | Forensic marker only |
| `RegimeState` | ❌ not supported | ✅ | `dataclasses.replace`-based equality tests only (`test_new_events.py`) |
| `Signal` | ❌ not supported | ✅ | `replace`-round-trip stand-in: `test_signal_replace_round_trip`, `test_signal_v03_round_trip` |
| `RiskVerdict` | ❌ not supported | ✅ | Construction test only |
| `OrderRequest` | ❌ not supported | ✅ | Construction test only |
| `OrderAck` | ❌ not supported | ✅ | Construction test only |
| `PositionUpdate` | ❌ not supported | ✅ | Construction test only |
| `StateTransition` | ❌ not supported | ✅ | Construction test only |
| `MetricEvent` | ❌ explicitly rejected | ✅ | `test_serialize_rejects_non_market_event` asserts the rejection |
| `Alert` | ❌ not supported | ✅ | Construction test only |
| `KillSwitchActivation` | ❌ not supported | ✅ | Construction test only |
| `RegimeHazardSpike` | ❌ not supported | ✅ | `replace`-based; `test_regime_hazard_spike_is_frozen` |
| `HorizonTick` | ❌ not supported | ✅ | `test_horizon_tick_replace_with_field_change` |
| `SensorReading` | ❌ not supported | ✅ | Construction test only |
| `HorizonFeatureSnapshot` | ❌ not supported | ✅ | Construction test only |
| `CrossSectionalContext` | ❌ not supported | ✅ | Construction test only |
| `SizedPositionIntent` | ❌ not supported | ✅ | `test_sized_position_intent_round_trip_with_mechanism_breakdown` (replace-based) |
| `SensorProvenance` / `TargetPosition` (support types) | ❌ not supported | ✅ | Frozenness parametrized in `test_frozenness` |

**Reading the table:** the ❌ column is a scope statement, not a defect
report — every non-market event's actual replay-durability requirement is
"recomputed deterministically from the input tape on every run," not
"persisted and reloaded," so no round-trip contract is needed for Inv-5 to
hold for them. The frozen-dataclass "round trip" tests (`dataclasses.replace`)
that exist for these types are explicitly documented as a **stand-in**
(`test_new_events.py:449-455`: *"Stand-in for bus serialization until
`core/serialization.py` is implemented... without relying on JSON or pickle
round-trips that the platform's serialization layer will eventually
formalize"*) — i.e. the test suite itself flags that this is a substitute, not
equivalent coverage, consistent with the scope table above.

### 4.1 — Decimal / tuple / enum / None fidelity for the supported types — **[RECONFIRMED OK]**

`event_to_dict` (`:62-82`) stringifies every `Decimal` field and lists every
`tuple` field; `dict_to_event` (`:85-148`) reverses both by **substring
match** on the (stringified, `from __future__ import annotations`-erased)
field-type annotation — `"Decimal" in ft_str` and `"tuple" in ft_str`
(`:128,131`, generalized from the pre-2026-06-25 `"tuple[int"`-only match).
Unknown fields from a newer schema are dropped, not raised on
(`:139-142`); a missing required field surfaces as `ValueError`, not a raw
`TypeError` (`:143-148`). All of this is directly exercised by
`test_serialization.py`'s 14 tests, including explicit trailing-zero Decimal
preservation, tuple-not-list restoration, schema-version enforcement, and the
legacy (no-tag ⇒ v1) load path.

### 4.2 — Determinism mechanism — **[OK, same implicit-ordering note as 2026-06-25]**

Key order is `__type__`/`__schema_version__` first, then
`__dataclass_fields__` iteration (base fields before subclass fields), and
`json.dumps` preserves insertion order without needing `sort_keys`.
Bit-determinism is implicit in dataclass field-definition order rather than
enforced by explicit sorting — reordering a dataclass's field declarations
would silently change the on-disk byte layout. Not a bug (field order is
itself stable across processes and is never reordered casually), but a
sensitivity worth knowing before refactoring `NBBOQuote`/`Trade`.

---

## 5. Config-layering audit

### Precedence (lowest → highest)

For platform YAML: (1) `PlatformConfig` field defaults
(`platform_config.py:67+`) → (2) `extends:` base file(s), deep-merged
(`config_yaml.py:77-79`) → (3) the leaf file's own keys. For gate thresholds,
a documented three-layer chain (`platform_config.py:644-664`):
`GateThresholds()` skill-pinned defaults → `platform.yaml: gate_thresholds` →
per-alpha `promotion.gate_thresholds` (the per-alpha layer is resolved in
`alpha/registry.py`, out of `core/` scope).

### 5.1 — `deep_merge_mapping` — **[RECONFIRMED OK, non-mutating & deterministic]**

```python
# config_yaml.py:16-31
def deep_merge_mapping(base, override):
    merged = dict(base)                                        # top-level copy
    for key, override_val in override.items():
        if key == _EXTENDS_KEY: continue
        base_val = merged.get(key)
        if isinstance(base_val, dict) and isinstance(override_val, dict):
            merged[key] = deep_merge_mapping(base_val, override_val)  # fresh nested dict
        else:
            merged[key] = override_val
    return merged
```

Verified by code inspection: every branch either copies (`dict(base)`) or
recurses into a fresh dict; neither `base` nor `override` is ever mutated.
`extends:` resolution guards both cycles (`config_yaml.py:45-47`,
`ConfigurationError` on repeat) and depth (`:48-51`, capped at 16). Sequences
and scalars in the override replace the base value wholesale (documented,
`:20-21`) — reasonable, flagged only so operators know lists don't merge
element-wise.

### 5.2 — `PlatformConfig.validate()` — **[RECONFIRMED OK, thorough]**

~40 discrete range/consistency checks (`:673-971`), every one raising
`ConfigurationError` (never a silent default) — position limits, account
type/PDT floor, halt condition-code disjointness, borrow-tier enum
membership, cost-model non-negativity, sizer floor≤cap invariants, Phase-2
sensor-DAG topological order (`:895-923`, rejects both unknown upstream IDs
and out-of-order producers), Phase-4 composition thresholds. Consistently
fail-loud, matching Inv-11's fail-safe-toward-CRASH direction for invalid
config. **Caveat (unchanged from 2026-06-25, now explicitly documented):**
`from_yaml`'s own docstring states validation is deliberately **not**
auto-invoked — *"Construction is kept separate from validation so
partially-specified configs can be assembled in tests"*
(`platform_config.py:1241-1245`) — callers (bootstrap) must call `validate()`
themselves. This is now an intentional, documented design choice rather than
an unaddressed gap.

### 5.3 — `_check_yaml_keys_and_types` — **[RECONFIRMED OK]**

Rejects non-`bool` values for `bool`-typed fields (checking `bool` before
`int`, since `bool` is an `int` subclass — `:1725-1732`), rejects
non-`int`/float-with-fraction values for `int`-typed fields
(`:1733-1738`), and warns (or raises, with `strict=True`) on unrecognized
top-level keys (`:1705-1718`). This directly matches dimension C.2/C.3 of the
audit brief and is the fix verified in §0.

### 5.4 — [NEW, P1, bug] Falsy-zero `or`-chain aliasing discards explicit overrides

Four adjacent fields in `from_yaml` resolve alias pairs with `or`:

```python
# platform_config.py:1506-1525
cost_passive_adverse_selection_bps=float(
    data.get("cost_passive_adverse_selection_bps")
    or data.get("cost_adverse_selection_drain_bps")
    or 2.0
),
cost_through_fill_adverse_selection_bps=float(
    data.get("cost_through_fill_adverse_selection_bps")
    or data.get("cost_adverse_selection_through_bps")
    or 5.0
),
cost_adverse_selection_through_bps=float(
    data.get("cost_adverse_selection_through_bps")
    or data.get("cost_through_fill_adverse_selection_bps")
    or 5.0
),
cost_adverse_selection_drain_bps=float(
    data.get("cost_adverse_selection_drain_bps")
    or data.get("cost_passive_adverse_selection_bps")
    or 2.0
),
```

`0.0 or X` evaluates to `X` in Python — an explicit, validly-typed
`cost_passive_adverse_selection_bps: 0.0` in YAML is silently replaced by
whichever alias or hardcoded default comes next in the chain. **Reproduced
empirically:**

```
$ echo 'symbols: [AAPL]\nalpha_specs: [x.yaml]\ncost_passive_adverse_selection_bps: 0.0' | PlatformConfig.from_yaml(...)
cost_passive_adverse_selection_bps = 2.0   # expected 0.0
```

Contrast with the **correct** pattern 165 lines earlier in the same method,
for a structurally identical legacy-alias problem:

```python
# platform_config.py:1341-1347 — correct: explicit is-None checks
taker_exch_raw = data.get("cost_taker_exchange_per_share")
legacy_exch = data.get("cost_exchange_per_share")
if taker_exch_raw is None and legacy_exch is not None:
    taker_exch_raw = legacy_exch
```

This second pattern correctly preserves an explicit `0.0`. The bug is
therefore a **local inconsistency**, not a systemic misunderstanding — the
fix is mechanical (swap `or` for the `is not None` chain already used as a
precedent in the same file). No test anywhere in the repository exercises a
zero value for any of the four fields (`grep` across `tests/` returned zero
hits); `PlatformConfig.validate()` cannot catch this either, since by the time
`validate()` runs the silent substitution has already happened and the
resulting `2.0`/`5.0` is a valid, in-range value.

### 5.5 — `PlatformConfig._to_dict()` / snapshot canonicalization — **[RECONFIRMED OK, one exception — see 5.6]**

Deliberate, broad use of `sorted(...)` for every set/frozenset-valued field
before it enters the checksum (`symbols`, `alpha_specs`, `horizons_seconds`,
`gate_thresholds_overrides.items()`, `sensor_specs[*].subscribes_to`, etc.) —
this is exactly the hygiene that keeps the checksum independent of
Python's (unpinned, per the `PYTHONHASHSEED` pytest warning) hash-seed-
dependent set-iteration order. `Path`-typed fields are normalized to their
basename (`:996-1004`) so absolute filesystem paths — which differ by
machine/checkout — don't leak into the checksum, citing two prior audits by
name (`audit A-DET-02`, `audit B-PROMO-04`) that found and fixed this exact
class of bug for a *different* set of fields previously — good evidence of
institutional learning being applied prospectively. One latent, low-severity
edge case: `alpha_specs` is checksummed by `sorted(p.name for p in
self.alpha_specs)` (basename only, `:1010`) — two distinct `alpha_specs`
entries in different directories sharing a basename would be indistinguishable
in the checksum. Documented tradeoff, not flagged as an actionable finding.

### 5.6 — [NEW, P1, bug] `_to_dict()` aliases a live mutable field into the "immutable" snapshot

```python
# platform_config.py:1011-1013
"parameter_overrides": self.parameter_overrides,             # NOT copied
"regime_engine_options": dict(self.regime_engine_options),   # copied
```

The two adjacent `dict[str, ...]`-typed fields are handled inconsistently.
**Reproduced empirically:**

```python
cfg = PlatformConfig(symbols=frozenset({"AAPL"}), parameter_overrides={"sig_x": {"k": 1}})
snap = cfg.snapshot(ts_ns=0)
snap.data["parameter_overrides"]["sig_x"]["k"] = 999
cfg.parameter_overrides  # => {'sig_x': {'k': 999}}  — mutated!
snap.data["parameter_overrides"] is cfg.parameter_overrides  # => True
```

`ConfigSnapshot`'s own docstring promises: *"Immutable, serializable snapshot
of configuration for provenance"* (`config.py:20-25`). A consumer that reads a
`ConfigSnapshot` for forensic/audit purposes and (reasonably, given the
"immutable" label) mutates a working copy of `.data` for further processing
would silently corrupt the live `PlatformConfig` it was snapshotted from. No
current caller was found doing this, so it has not manifested as a live
defect, but the contract violation is concrete and mechanically trivial to
fix (wrap in `dict(...)`, mirroring the sibling field one line below it).

### 5.7 — [NEW, P2, design] `PlatformConfig` itself is not frozen

`platform_config.py:59`: `@dataclass(kw_only=True)` — no `frozen=True`, unlike
`ConfigSnapshot` (`config.py:19`) and every `Event` subclass
(`events.py`). A grep for in-place field assignment
(`config\.\w+ = `/`cfg\.\w+ = `/`platform_config\.\w+ = `) across
`src/feelies/` found **zero** occurrences; every place that "changes" a
`PlatformConfig` goes through `dataclasses.replace(...)`
(`inv12_stress.py:44`, `harness/backtest_runner.py`, `harness/backtest_cli.py`,
`bootstrap.py`), which returns a fresh instance. The "resolved once,
non-mutating" contract this audit is checking for therefore holds **by
convention**, not by construction — nothing in the type system would catch a
future contributor adding `config.some_field = x` for a quick fix. Given the
~215-field size and central role of this dataclass, freezing it outright is a
larger, riskier change to fully verify than the size of the actual gap
warrants (§9 rates it effort M, not S) — recommended as hardening, not urgent.

---

## 6. StateMachine primitive audit

### 6.1 — Transition atomicity — **[RECONFIRMED OK, verified]**

```python
# state_machine.py:159-177
if not self.can_transition(target):
    raise IllegalTransition(...)                    # 1. validate
record = TransitionRecord(...)                        # 2. build (immutable)
for callback in self._on_transition_callbacks:
    callback(record)                                   # 3. notify — may veto by raising
self._history.append(record)                          # 4. commit
self._state = target                                   # 4. commit
```

State and history are written **only after every callback succeeds** — a
raising callback leaves both untouched. Directly tested:
`test_callback_raises_prevents_transition` asserts `state == A` and
`history == 0` post-veto. This is the exact contract the promotion ledger
relies on: `AlphaLifecycle` registers its ledger-append callback via
`on_transition`, so a failed ledger write vetoes the lifecycle transition
atomically.

### 6.2 — Multi-callback rollback boundary — **[RECONFIRMED, documented + tested]**

The docstring (`:149-157`) and `test_multi_callback_rollback_boundary`
(`test_state_machine.py:108-130`) both now explicitly scope the guarantee:
the SM rolls back only **its own** state; if a second callback raises, an
earlier callback's *external* side effect (e.g. a file already written) is
**not** undone — "the SM cannot reverse effects it does not own." This closes
the 2026-06-25 P2-2 finding (the docstring previously read as overpromising).
Verified current and accurate.

### 6.3 — Illegal transitions & table completeness — **[RECONFIRMED OK]**

Illegal transitions raise `IllegalTransition` without mutating state
(`test_illegal_transition_raises`). Construction rejects an incomplete
transition table — every enum member must have an explicit entry, even if its
targets are an empty `frozenset` (terminal) — so a contributor adding a new
state without wiring it gets a hard `ValueError` at `__init__`, not silent
terminal behavior (`:90-101`, `test_incomplete_transition_table_raises`).
`reset()` intentionally bypasses the transition table (unconditional
reinit) but preserves identical pre-commit callback semantics and tags
`metadata={"type": "reset"}` for audit-trail disambiguation (`:179-209`).

### 6.4 — [NEW, P1, bug/gap] No thread-safety, asymmetric with `SequenceGenerator`

`state_machine.py`'s `__slots__` (`:65-73`) list no lock, and `transition()`'s
four-step sequence (§6.1) has no synchronization: two threads racing on the
same `StateMachine` instance could both pass `can_transition()` against the
same pre-transition state, both build a record, both run callbacks, and then
whichever thread's `self._history.append` / `self._state = target` executes
second silently wins — the first thread's transition is **lost**, not
detected, not erred on. Contrast with the sibling primitive one file over:

```python
# identifiers.py:40-51 — SequenceGenerator: explicit lock + documented contract
class SequenceGenerator:
    __slots__ = ("_counter", "_lock")
    def __init__(self, start: int = 0) -> None:
        self._counter = start
        self._lock = threading.Lock()
    def next(self) -> int:
        with self._lock:
            ...
```

`SequenceGenerator`'s docstring (`:31-38`) explicitly reasons about
concurrent callers and states the exact guarantee (uniqueness yes,
cross-thread ordering no). `StateMachine` offers neither the lock nor the
documentation. This asymmetry is itself evidence the gap was not a deliberate
choice for `StateMachine` specifically. Live exposure: `OrderState`
(`execution/order_state.py:89`, one of the five named platform SMs) drives
order lifecycle in PAPER/LIVE mode; `broker/ib/connection.py` runs dedicated
`_msg_thread` and `_writer_thread` background threads (`:107-160`) that
receive broker callbacks. **This audit did not trace** whether any live-mode
code path actually calls `.transition()` on a shared `OrderState` SM instance
from more than one of those threads concurrently (that requires following
`execution/live_router.py`'s dispatch, which is live-execution-skill
territory) — flagging the primitive-level gap and recommending that trace as
a fast, high-value follow-up rather than asserting a confirmed live race.

### 6.5 — Consistent usage — **[RECONFIRMED OK]**

All six real consumers (macro, micro, order, risk-escalation, data-integrity,
alpha-lifecycle — see §2) construct `StateMachine[S]` with an injected
`Clock`. No parallel/bespoke state-machine implementation was found anywhere
in `src/feelies/`.

---

## 7. Identifiers & events audit

### 7.1 — [NEW, P1, test gap] `derive_order_id` is production-critical and untested

```python
# identifiers.py:18-25
def derive_order_id(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()[:16]
```

Deterministic by construction (SHA-256 truncated to 16 hex chars) — the
implementation itself is simple enough that a defect is unlikely — but it is
the **sole mechanism by which every order ID in the platform is generated**,
confirmed by 6 call sites in `risk/sized_intent_orders.py:129`,
`risk/hazard_exit.py:292`, and `kernel/orchestrator.py` (5 sites:
`:3703,4314,4479,4696,5272,6683`), each building a seed from
`(correlation_id, sequence, symbol, reason)`-style provenance tuples per
`identifiers.py:19-24`'s own docstring contract. `uuid4` is confirmed absent
from the entire codebase (`grep -rn "uuid4"` → zero imports, two comments
*forbidding* it), so this function is the entire Inv-5 order-ID-determinism
surface. `tests/core/test_identifiers.py` has 6 tests, all for
`make_correlation_id` (2) and `SequenceGenerator` (4) — **zero** for
`derive_order_id**. A silent regression here (e.g. an accidental switch to a
non-deterministic seed component) would be invisible until a replay-parity
hash broke somewhere downstream, rather than being caught at the primitive
level.

### 7.2 — `make_correlation_id` — **[RECONFIRMED OK]**

`f"{symbol}:{exchange_timestamp_ns}:{sequence}"` (`:9-15`) — deterministic
given its inputs; covered by 2 tests confirming format and field-linking.
Collision-freedom is a caller-discipline property (the function performs no
uniqueness check itself), which is a reasonable, intentional simplicity
tradeoff for a pure string formatter — not a finding.

### 7.3 — `SequenceGenerator` — **[RECONFIRMED OK, documented]**

Thread-safe uniqueness via `threading.Lock` (`:44-50`); cross-thread
*assignment order* is explicitly documented as non-deterministic
(`:31-38`) — acceptable because deterministic replay is single-threaded by
construction (backtest/replay path), and live/paper is not
parity-hashed. `test_thread_safe` (`test_identifiers.py:45-59`) exercises 100
concurrent submissions via `ThreadPoolExecutor`, asserting uniqueness and full
range coverage.

### 7.4 — Event immutability & v0.2/v0.3-compatible defaults — **[RECONFIRMED OK / documented limitation]**

Every event is `@dataclass(frozen=True, kw_only=True)`. The base `Event`
docstring (`events.py:39-49`) explicitly documents shallow immutability —
`frozen=True` blocks field rebinding, but mutable containers reached through a
field (`Signal.metadata`, `RiskVerdict.constraints`, `MetricEvent.tags`,
`HorizonFeatureSnapshot.values/warm/stale`, `SizedPositionIntent.target_positions`)
can still be mutated in place, and those events are consequently unhashable —
with an explicit usage contract: *"Treat every event as read-only once
published... build a fresh event instead."* This is the 2026-06-25 P2-3 fix,
reconfirmed present. Backward-compatible defaults are correct and verified:
`Signal.trend_mechanism: TrendMechanism | None = None`,
`Signal.expected_half_life_seconds: int = 0`, `RegimeState.calibrated: bool =
True`, `RegimeState.discriminability: float = float("inf")`,
`source_layer: str = "UNKNOWN"` — all additive, all parity-preserving for
legacy producers, matching the `three_layer_architecture.md` §5 contract.
`test_frozenness` in `test_new_events.py` parametrizes the immutability check
across 10+ distinct event/support-type + field combinations.

### 7.5 — Error taxonomy — **[RECONFIRMED OK]**

`FailureMode` enum (`CRASH`/`DEGRADE`/`RETRY`/`LOCKDOWN`) plus a
`ClassVar[FailureMode]` on `FeeliesError` and each of its 9 concrete
subclasses (`errors.py:9-91`) — this is the 2026-06-25 P2-6 fix, reconfirmed
present and machine-readable (not just prose). Minor, new observation:
`test_errors.py`'s parametrized inheritance/failure-mode tests cover 7 of the
9 concrete subclasses — `OrchestratorPipelineAbortError` (`:76-84`) and
`SessionEntryBlockedError` (`:87-91`) are defined but absent from both
parametrize lists (§9 P2 item).

---

## 8. Test gap matrix

| Invariant / behavior | Test(s) | Status |
|---|---|---|
| `SimulatedClock` rejects backward time | `test_clock.py` | ✅ covered |
| Clock injectable / `StateMachine` requires it, no default | `test_clock.py`, `state_machine.py:75-81` (by construction) | ✅ covered |
| `rth_open_ns` DST correctness (both sides) + integer-exactness | `test_session_clock.py` (4 tests) | ✅ covered |
| NBBOQuote/Trade round-trip, Decimal/tuple fidelity, schema version, corrupt/unknown handling | `test_serialization.py` (14 tests) | ✅ covered |
| Round-trip property over all 20 event types | — | ❌ missing (by design — see §4; `dataclasses.replace` stand-ins exist for several) |
| `deep_merge_mapping` nested merge + `extends` chain + cycle | `test_config_yaml.py` (3 tests) | ◐ partial |
| `deep_merge_mapping` non-mutation of inputs (regression guard) | — | ❌ missing (verified correct by inspection, §5.1; no test pins it) |
| `extends:` depth-limit (16) exceeded | — | ❌ missing |
| `extends:` missing target file / non-string / non-mapping root | — | ❌ missing |
| `PlatformConfig.validate()` range checks | `test_platform_config*.py` (108 tests across 4 files) | ✅ broad |
| YAML strict scalar coercion (bool/int/float) | `test_platform_config_gate_thresholds.py` + inline `from_yaml` tests | ✅ covered |
| Unknown top-level YAML key → warn/raise | (inferred from `_check_yaml_keys_and_types` design; not independently grepped in this pass) | ◐ likely covered, not re-verified line-by-line |
| Alias fallback preserves explicit `0.0` (cost-bps fields) | — | ❌ missing — **and the code is wrong**, §5.4 |
| `snapshot().data` defensive-copy consistency across fields | — | ❌ missing — **and one field is wrong**, §5.6 |
| SM illegal transition / incomplete table / single-callback rollback | `test_state_machine.py` | ✅ covered |
| SM multi-callback rollback boundary | `test_state_machine.py:108-130` | ✅ covered |
| SM thread-safety under concurrent `.transition()` | — | ❌ missing (and no lock exists to test) |
| `make_correlation_id` determinism | `test_identifiers.py` (2 tests) | ✅ covered |
| `derive_order_id` determinism / format / distinctness | — | ❌ **missing entirely** |
| `SequenceGenerator` thread-safety | `test_identifiers.py:45-59` | ✅ covered |
| Event frozen / v0.2-v0.3-compatible defaults | `test_events.py`, `test_new_events.py`, `test_trend_mechanism_events.py` (46 tests) | ✅ covered |
| Event deep-immutability (dict-field mutation) | — | ❌ missing (behavior is mutable; documented, not tested) |
| Error taxonomy inheritance + `failure_mode` | `test_errors.py` (3 parametrized tests, 7/9 classes) | ◐ partial — 2 classes untested |
| Inv-12 stress: cost multiplier, fill-latency doubling | `test_inv12_stress.py` (8 tests) | ✅ covered |
| Inv-12 stress: `market_data_latency_ns` doubling in the joint-stress test | `test_inv12_stress.py:31-39` | ◐ code does it; test doesn't assert it |

### Proposed minimal new tests (specs only, per the audit brief — no code)

1. **Alias-fallback zero-preservation:** for each of the 4 cost-bps alias
   pairs, load a YAML fragment setting the primary key to `0.0` with no alias
   present, and assert the loaded field is `0.0`, not the alias's default.
   Pins §5.4; would fail today.
2. **Snapshot defensive-copy:** construct a `PlatformConfig` with a non-empty
   `parameter_overrides`, take a snapshot, mutate a nested value in
   `snapshot().data["parameter_overrides"]`, and assert the source config's
   `parameter_overrides` is unchanged. Pins §5.6; would fail today.
3. **`derive_order_id` unit tests:** same seed → same id (determinism);
   different seeds → different ids (basic collision sanity); output is
   exactly 16 lowercase hex characters; output matches
   `hashlib.sha256(seed.encode()).hexdigest()[:16]` directly (pins the exact
   contract, not just "looks random").
4. **SM concurrent-transition race (documents the gap even if not fixed):** two
   threads racing `.transition()` from the same source state on a
   `StateMachine` backed by a real `threading.Barrier` to force the
   interleaving; assert either a well-defined outcome (e.g. one wins, one
   raises) or explicitly document/`xfail` the lost-update behavior so a future
   fix has a red test to turn green.
5. **`deep_merge_mapping` non-mutation + `extends` edge cases:** assert `base`
   and `override` are unchanged after the call; assert `ConfigurationError`
   for `extends:` depth 17, a missing target file, and a non-mapping root.
6. **`test_apply_inv12_stress_joint`:** add the missing
   `assert stressed.market_data_latency_ns == 40_000_000`-style assertion
   alongside the existing `backtest_fill_latency_ns` check.
7. **`test_errors.py`:** add `OrchestratorPipelineAbortError` and
   `SessionEntryBlockedError` to both parametrize lists.

---

## 9. Prioritized backlog

Effort: **S** ≤ ½ day, **M** ≈ 1–2 days, **L** > 2 days. No fixes applied in
this pass (read-only per the audit contract).

### P0 — none found

Same conclusion as 2026-06-25, independently re-derived: no wall-clock read on
the deterministic tick/replay path, no lossy round-trip for any type
`serialization.py` claims to support, no non-deterministic config merge (the
new §5.4 finding is a *deterministic-but-wrong* merge, which the audit brief's
own rubric places at P1, not P0), and `StateMachine` never commits
state/history on callback failure.

### P1

| # | Component | `file:line` | One-sentence fix | Impact | Effort |
|---|-----------|-------------|-------------------|--------|--------|
| N1 | Alias `or`-chain drops explicit `0.0` | `platform_config.py:1506-1525` | Replace the four `or`-chains with the `is not None` pattern already used correctly at `:1341-1347` in the same method. | Stops silent, deterministic corruption of an explicit operator cost-model override. | S |
| N2 | `_to_dict()` doesn't copy `parameter_overrides` | `platform_config.py:1011` | Wrap in `dict(self.parameter_overrides)`, mirroring `regime_engine_options` one line below. | Restores the "immutable snapshot" contract (Inv-13) `ConfigSnapshot.data` promises. | S |
| N3 | `derive_order_id` has zero direct tests | `identifiers.py:18-25` / `tests/core/test_identifiers.py` | Add ~4 tests per §8 item 3. | Closes the coverage gap on the platform's sole order-ID-determinism primitive. | S |
| N4 | `StateMachine` has no thread-safety or documented concurrency contract | `state_machine.py:52-217` | Either add a `threading.Lock` around `transition()`/`reset()` (mirroring `SequenceGenerator`), or explicitly document a single-thread-only contract — but first trace whether `OrderState` is ever driven from >1 thread in PAPER/LIVE (live-execution skill territory). | Closes an asymmetric gap vs. `SequenceGenerator`; prevents a silent lost-transition race if/when the live call graph does cross threads. | M (needs the cross-layer trace before deciding lock vs. document) |
| N5 | CLAUDE.md DTZ-exemption claim is inaccurate; one exemption is unjustified by current code | `CLAUDE.md` ("Only `clock.py` is exempted"); `pyproject.toml:128-131`; `monitoring/structured_logging.py` | Update CLAUDE.md to state the actual exemption set (4 files); remove or re-scope the `structured_logging.py` ignore since no code in that file needs it today. | Keeps the Inv-10 CI gate's documented surface honest; removes a pre-authorized-but-unused hole. | S |

### P2

| # | Component | `file:line` | One-sentence fix | Impact | Effort |
|---|-----------|-------------|-------------------|--------|--------|
| N6 | `PlatformConfig` is mutable (not `frozen=True`) | `platform_config.py:59` | Add `frozen=True`; audit already found zero in-place mutation sites, so this should be low-risk, but verify against the full `~215`-field surface and `dataclasses.replace` call sites before flipping. | Enforces the "resolved once" contract at the type level instead of by convention. | M |
| N7 | `EventSerializer` docstrings overstate scope | `serialization.py:1-17,39-47` | Reword to state explicitly "market-data (`NBBOQuote`/`Trade`) disk-cache codec," not "every event." | Prevents a future contributor from assuming `Signal`/`OrderRequest`/etc. round-trip through this module. | S |
| N8 | `alpha_specs` checksum collapses on basename collision across directories | `platform_config.py:1010` | Document the tradeoff explicitly (already partially documented at `:996-1004` for the general Path-basename policy) or key on the relative path from a common root instead. | Closes a narrow, low-likelihood checksum-collision edge case. | S |
| N9 | `execution/moc_session.py::et_clock_to_ns` uses a float-multiply-then-`int()` pattern instead of `core/session_clock.py`'s integer-safe order | `execution/moc_session.py:60-64` | Mirror `rth_open_ns`'s `int(seconds) * NS_PER_SECOND` pattern. | Defense-in-depth; no live divergence found empirically (§3.4), but removes reliance on float64 headroom that narrows over calendar time. | S |
| N10 | `test_errors.py` omits 2 of 9 `FeeliesError` subclasses | `tests/core/test_errors.py` | Add `OrchestratorPipelineAbortError` / `SessionEntryBlockedError` to both parametrize lists. | Closes a small, mechanical coverage gap. | S |
| N11 | `test_apply_inv12_stress_joint` doesn't assert `market_data_latency_ns` doubling | `tests/core/test_inv12_stress.py:31-39` | Add the missing assertion. | Closes a small coverage gap on a 3-field function currently checked on 2 fields. | S |
| N12 | `test_config_yaml.py` (3 tests) has no coverage for depth-limit, missing-target, non-mapping-root, or a non-mutation regression guard | `tests/core/test_config_yaml.py` | Add ~4 tests per §8 item 5. | Turns code-inspection-verified correctness (§5.1) into a regression-guarded property. | S |
| N13 | `bootstrap.py` factor-loadings freshness `time.time()` fallback (reconfirmed from 2026-06-25, still untracked) | `bootstrap.py:2298-2301` | Either require `session_open_ns` whenever `factor_loadings_dir` is set, or fail closed instead of falling back to wall time. | Closes a narrow bootstrap-outcome reproducibility gap (Inv-5-adjacent). Outside `core/`'s file scope — recommend routing to the backtest-engine/live-execution audit owners. | M |

---

## Appendix — verification commands run (read-only)

- `uv sync --all-extras` — clean dependency install (38 packages).
- `uv run pytest tests/core/ -q` → **229 passed**, 1 warning
  (`PYTHONHASHSEED=None` reminder from `conftest.py:34`, pre-existing and
  unrelated to any finding above — noted in §1 item 1 for completeness since
  it's directly about determinism hygiene for `frozenset`-valued config
  fields, all of which were independently confirmed to be `sorted()`-guarded
  before hashing, §5.5).
- Repo-wide grep for `datetime\.now|time\.time\(\)|time\.perf_counter|date\.today|utcnow`
  across `src/feelies/` (table in §3).
- Grep for `\.snapshot\(`, `WallClock\(`, `\.failure_mode`, `StateMachine\(`,
  `derive_order_id`, `rth_open_ns`, `uuid4` across `src/feelies/` and
  `tests/` to trace call sites and confirm/refute test coverage claims.
- Two standalone reproduction scripts (run via `uv run python`, not committed):
  one loading a `PlatformConfig` from a temp YAML file to confirm the §5.4
  alias-fallback bug end-to-end; one constructing a `PlatformConfig`,
  snapshotting it, and mutating `snapshot().data["parameter_overrides"]` to
  confirm the §5.6 live-aliasing bug end-to-end. Both outputs are quoted
  verbatim in §5.4/§5.6.
- Numerical sweep (16 years × 3 months × both DST sides) comparing
  `core/session_clock.py`'s and `execution/moc_session.py`'s independent
  ET-anchor arithmetic — zero divergence found (§3.4).
- Read `docs/three_layer_architecture.md` §5 (event contracts) and §9
  (platform configuration changes) as required platform context; read
  `docs/audits/core_clock_config_audit_2026-06-25.md` in full and
  cross-verified all six of its P1/P2 remediations against current code
  (§0).
