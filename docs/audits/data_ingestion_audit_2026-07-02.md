# Data Ingestion / Replay / Storage Audit — 2026-07-02

**Scope:** raw Massive REST/WS messages → `MassiveNormalizer` → `EventLog` /
`DiskEventCache` → `ReplayFeed` → orchestrator `_process_tick` /
`_process_trade`. Storage (`EventLog`, `DiskEventCache`, `cache_replay`,
resequencing) and live feed (`MassiveLiveFeed`).

**Mode:** read-only, evidence-based audit. No production code, configs,
baselines, or ledgers were modified. No fixes were implemented.

**Lineage:** third installment of this audit. `docs/audits/data_ingestion_audit_2026-06-11.md`
found ING-01…ING-10 (all fixed same-day). `docs/audits/data_ingestion_audit_2026-06-19.md`
found DI-01…DI-09 (all still open at that time; no P0). Between 06-19 and
today, `git log` shows **no commits touched the core ingestion/replay
contract files** (`massive_normalizer.py`, `replay_feed.py`,
`event_resequence.py`, `memory_event_log.py`, `massive_ws.py`,
`data_integrity.py`, `cache_replay.py`) — the only touches were a
repo-wide `ruff format` pass (whitespace-only, verified via `git show
3b528df -- src/feelies/ingestion/massive_ingestor.py
src/feelies/storage/disk_event_cache.py`) and an unrelated harness/CLI
audit remediation (`c0315ab`) that touched `backtest_runner.py` /
`platform_config.py` for a different reason (`--strict-config` YAML-key
validation). This pass therefore re-verifies every 06-19 finding against
current line numbers and code paths rather than assuming staleness, and
found one finding materially **improved** (DI-01, see below) beyond what
re-verification alone would show — the shipped reference configs already
close the gap the code-level default leaves open.

**Verdict: No P0 found.** Ingestion remains rigorous where it was
rigorous six weeks ago: the normalizer is the single typed boundary,
resequencing is centralized and defended at both write and replay time,
BT-17 latency is wired from config, and the targeted
ingestion/storage/causality/determinism suites are fully green. The
sharpest finding in this pass is a **root-cause refinement of the live
partial-subscription gap (DI-02)**: the coverage safeguards that look
like they should catch it (`strict_normalizer_symbol_coverage`,
`Orchestrator._verify_data_integrity`) structurally cannot, because
`MassiveNormalizer.register_symbols()` marks every configured symbol
"tracked" at bootstrap, before the WebSocket ever confirms a channel
subscription.

---

## 0. Remediation Status

Sections 1–9 below preserve the original read-only pass as written. A
follow-up remediation pass (same day) implemented the P1/P2 backlog from
§9; current status:

| ID | Status | Notes |
|----|--------|-------|
| DI-01 (WS queue overflow → DataHealth) | **Fixed** | `MassiveLiveFeed._consume()` now calls `normalizer.notify_feed_interrupted((event.symbol,))` on every `queue.Full` drop (`ingestion/massive_ws.py`). Test: `tests/ingestion/test_massive_normalizer.py::TestMassiveLiveFeedBackpressure::test_consume_drop_marks_symbol_gap_detected`. |
| DI-02 (partial WS subscription → DataHealth) | **Fixed** | `_subscribe()` calls `normalizer.notify_feed_interrupted(self._symbols)` when `successes < n_expected` (symbol-granularity, not per-channel — channel identity isn't reliably attributable from Massive's response frames). Tests: `TestMassiveLiveFeedSubscriptionHealth` in the same file. |
| DI-03 (rejected-event provenance) | **Fixed** | New `Orchestrator._publish_rejected_event_alert()` publishes a typed `Alert` (reusing the existing bus/Inv-7 provenance path rather than a bespoke sink) whenever a quote/trade is blocked by the data-health gate; HALTED trades are unaffected (already logged via the existing carve-out). Tests: `TestRejectedEventAlert` in `tests/kernel/test_data_integrity_runtime.py`. |
| DI-04 (ingest-health defaults fail-open) | **Revised, not flipped** | Flipping the `PlatformConfig` dataclass defaults would break every PAPER config (`configs/paper_run.yaml`/`paper_smoke_rth.yaml`, standalone, no `extends:`) and ~95 direct `PlatformConfig(...)` test constructions — `backtest_enforce_ingest_terminal_health=True` raises outside BACKTEST mode; `require_healthy_disk_cache_manifests=True` raises whenever `disk_cache_ingestion_health_rows` is empty. Instead pinned the already-safe shipped-config state with a test (`test_backtest_configs_are_fail_closed_on_ingest_health` in `tests/acceptance/test_backtest_app_config_keys.py`) and locked the intentional dataclass defaults (`test_ingest_health_gates_default_fail_open_by_design` in `tests/core/test_platform_config.py`). |
| DI-05 (anonymous malformed-frame counter) | **Fixed** | New `MassiveNormalizer.anonymous_malformed_frames` counter, incremented on JSON-decode failure and on `_mark_corrupted`'s empty/UNKNOWN-symbol early return. Threshold/escalation policy deliberately left to the monitoring layer (not invented here). Tests in `TestMassiveNormalizerDefensiveHardening`. |
| DI-06 (normalizer_version cache enforcement) | **Fixed** | `DiskEventCache.load()` now compares manifest `normalizer_version` and logs a WARNING on mismatch; does not invalidate the cache (that stays `event_schema_hash`'s job — a version bump doesn't always mean cached values are wrong). Tests in `TestDiskEventCacheManifest`. |
| DI-07 (wall-clock cache provenance) | **Partially fixed** | `harness/backtest_runner.py`'s `ingest_data()` — the only call site that actually calls `DiskEventCache.save()` — now injects `WallClock()`. The other 3 cited call sites (`cache_replay.py`, 2 scripts) only call `load()`/`exists()`, never `save()`, so `created_at` is never written there — threading a clock through them would have been a no-op; skipped. The factor-loadings-freshness half of this finding was already fixed by an unrelated, concurrently-landed kernel-audit remediation (commit `12ffafa`) before this pass started. |
| DI-08 (factor/sector loader ownership) | **Deferred** | Composition-layer territory with its own active audit series (`composition_audit_2026-07-02.md`) already covering this exact code in more depth; both loaders are no-ops in the shipped `platform.yaml`. Refactoring across the ingestion/composition boundary here risked duplicating or conflicting with that audit's remediation. |
| DI-09 (trade-condition eligibility policy) | **Fixed (documented)** | Documented as intentional design in the data-engineering skill rather than inventing a cross-layer eligibility classifier that would belong to the sensor layer's own audit territory. |
| DI-10 (SKILL.md doc drift) | **Fixed** | Corrected the `EventSerializer` section of `.cursor/skills/data-engineering/SKILL.md`. |
| *(collateral)* | **Fixed** | `tests/acceptance/test_no_walltime_outside_clock.py` had a pre-existing failure on `main` (unrelated kernel-audit remediation removed `bootstrap.py`'s wall-clock fallback but left it on the allowlist) — dropped the stale entry so the full suite is green. |

Verification: `ruff check` clean, `ruff format --check` clean on all touched
files (2 pre-existing-unformatted files touched had no new violations in the
changed lines), `mypy --strict src/feelies` clean (192 files), full fast
suite (`pytest -m "not functional and not slow"`) **3870 passed, 5 skipped**.

---

## 1. Executive Summary

1. **[P1] Live WS queue overflow drops normalized market events without
   touching `DataHealth` or macro state.** `MassiveLiveFeed._consume()`
   drops on `queue.Full` with only a counter and a log line
   (`src/feelies/ingestion/massive_ws.py:388-396`). Carried from 06-19
   DI-02, unchanged.
2. **[P1] Partial WS subscription confirmation runs in degraded coverage
   with only a WARNING — and the two coverage safeguards that look like
   they should catch this cannot, by construction.** `_subscribe()`
   raises only when **zero** channels confirm; a missing `Q.<sym>` or
   `T.<sym>` channel among many just logs a WARNING
   (`src/feelies/ingestion/massive_ws.py:332-341`). `register_symbols()`
   is called at bootstrap (`src/feelies/bootstrap.py:475`), **before**
   `live_feed.start()` (`scripts/run_paper.py:212` vs. `:245`), so every
   configured symbol is marked HEALTHY-by-presence in `all_health()`
   before a single WS frame arrives. Both
   `Orchestrator._verify_data_integrity()`
   (`src/feelies/kernel/orchestrator.py:6753-6758`) and the
   `strict_normalizer_symbol_coverage` runtime gate
   (`src/feelies/kernel/orchestrator.py:6607-6617`) check membership in
   `all_health()`, which pre-registration already guarantees — neither
   can observe "channel never confirmed." This sharpens 06-19 DI-03 with
   the specific mechanism, confirmed against `tests/kernel/test_data_integrity_runtime.py:178-193`,
   whose `TestStrictNormalizerSymbolCoverage` test only swaps the
   normalizer instance wholesale, not a realistic partial-subscription.
3. **[P1] Live/paper forensic logs omit the bad/gappy market event that
   triggers `DataHealth` blocking.** Fail-safe for trading (the tick is
   dropped before it can produce a signal or order), but the rejected
   event never reaches `EventLog.append`, so post-incident replay cannot
   reconstruct exactly what the normalizer saw. Trade path:
   `src/feelies/kernel/orchestrator.py:1856-1874`. Quote path: health
   gate at `:2314` runs before `EventLog.append` at `:2333`. Carried from
   06-19 DI-04, unchanged.
4. **[P2, revised down from 06-19's P1] Offline backtest ingestion-health
   defaults are fail-open at the `PlatformConfig` dataclass level, but
   every shipped entry point is fail-closed in practice.**
   `require_healthy_disk_cache_manifests` and
   `backtest_enforce_ingest_terminal_health` both default to `False`
   (`src/feelies/core/platform_config.py:99,114`) — confirming 06-19's
   DI-01 at the code level. **New this pass:** `platform.yaml` (the
   repo's reference config and the CLI's own `--config` default,
   `src/feelies/harness/backtest_cli.py:134`) sets
   `backtest_enforce_ingest_terminal_health: true` and
   `backtest_reject_zero_ingest_events: true`
   (`platform.yaml:33-34`), and every `configs/bt_*.yaml` alpha config
   inherits both via `extends: ../platform.yaml`
   (verified for all 6 `bt_*.yaml` files plus the `bt_app.yaml` →
   `bt_sig_benign_midcap.yaml` → `platform.yaml` chain, and confirmed
   `deep_merge_mapping` in `src/feelies/core/config_yaml.py:16-31`
   preserves unset base keys). The residual gap is narrower than 06-19
   implied: `require_healthy_disk_cache_manifests` is not set in any
   shipped config, but `backtest_enforce_ingest_terminal_health`'s
   worst-case-per-symbol-across-all-days check
   (`src/feelies/ingestion/ingest_health.py:27-31`) substantively covers
   the same failure mode. Only a hand-authored config that skips
   `extends:`, or direct `PlatformConfig()` construction outside
   `from_yaml`, hits the unsafe default.
5. **[P2] Malformed frames with no usable symbol cannot mark any stream
   `CORRUPTED`.** `_mark_corrupted()` early-returns when the symbol is
   empty or `"UNKNOWN"` (`src/feelies/ingestion/massive_normalizer.py:945-951`).
   Carried from 06-19 DI-05, unchanged.
6. **[P2] Cache `normalizer_version` is provenance-only — not part of
   load acceptance.** `exists()` and `load()` check only
   `event_schema_hash` (`src/feelies/storage/disk_event_cache.py:117,134`);
   `normalizer_version` is written (`:246`) but never compared. Carried
   from 06-19 DI-06, unchanged.
7. **[P2] Residual wall-clock provenance fallbacks, confirmed exercised
   in every real call path.** `DiskEventCache._created_at_utc()` falls
   back to `time.gmtime()` when no `Clock` is injected
   (`src/feelies/storage/disk_event_cache.py:82-87`); **every** production
   construction site — `cache_replay.py:79`, `backtest_runner.py:326`,
   plus `scripts/sensor_feature_ic.py:698` and
   `scripts/calibrate_hawkes.py:260` — omits `clock=`, so the fallback
   fires on every real cache write, not just in theory. Separately,
   factor-loadings freshness (`src/feelies/bootstrap.py:2295-2304`) has
   **improved** since 06-19 (unrelated composition-layer commit
   `452f13a`): it now prefers a deterministic embedded `_meta.as_of_ns`
   anchor over raw file mtime, falling to `time.time()` only as a last
   resort with an explicit warning when `session_open_ns` is also unset.
   Both remain provenance-only, not replay-hot-path (Inv-5 unaffected).
   Carried from 06-19 DI-07.
8. **[P2] Reference-data validation ownership is still split.**
   `event_calendar` / `corporate_actions` validate schema and dates
   inside `storage/reference`; `factor_loadings/__init__.py` and
   `sector_map/__init__.py` remain 1-line docstring-only marker modules,
   with actual JSON validation living in
   `composition/factor_neutralizer.py:195` and
   `composition/sector_matcher.py:119`. Carried from 06-19 DI-08,
   unchanged.
9. **[P2] No shared trade-condition eligibility policy at the ingestion
   boundary.** Conditions are parsed and preserved consistently on both
   REST and WS, but nothing decides which prints are "regular sale"
   eligible for sensors/queue-volume models beyond the halt/SSR side
   effects. `grep` for irregular/regular-sale/eligibility patterns
   across `src/feelies/` returns no matches. Carried from 06-19 DI-09,
   unchanged.
10. **[P2, NEW] Skill doc drift has now persisted across three audit
    cycles.** `.cursor/skills/data-engineering/SKILL.md`'s "EventSerializer"
    section states a concrete bit-deterministic serializer is "still
    TODO." It is not: `JsonLineEventSerializer`
    (`src/feelies/core/serialization.py:151-176`) is a complete,
    round-trip-tested implementation wired into `DiskEventCache`
    (`src/feelies/storage/disk_event_cache.py:45,167,223`), and both the
    06-11 audit (ING-05, "Fixed") and 06-19 audit ("Verified strengths")
    already confirmed this. The skill file every future Claude Code
    audit session is instructed to read *first*
    (`docs/prompts/audit_data_ingestion.md` "Agent context (mandatory)")
    has not been corrected despite two prior audits flagging the code as
    fixed — this actively risks mis-directing the next audit pass.
    **Verified strengths (unchanged from 06-19):** global multi-symbol
    ordering is fixed and tested; `ReplayFeed` enforces causality; BT-17
    latency is wired from `PlatformConfig` with non-zero defaults (20ms
    market data / 50ms fill); the targeted ingestion/storage/causality
    suite is **196 passed, 19 skipped** (all skips legitimate — API-key-
    or RTH-window-gated); `tests/determinism/` is **108 passed, 0
    failed**.

---

## 2. Architecture Trace

```text
            ┌─────────────────────── EXTERNAL (untyped) ───────────────────────┐
            │                                                                   │
  REST /v3/quotes,/v3/trades                         WS Q.* / T.* frames
            │                                                                   │
            ▼                                                                   ▼
  MassiveHistoricalIngestor                          MassiveLiveFeed (bg thread, asyncio,
  (_download_raw parallel q/t,                        bounded queue 100k, reconnect backoff
   per-thread REST clients,                            1s→60s, overflow → drop + counter,
   sort by (sip_ts, type_rank, seq))                   partial-subscribe → WARN + continue)
            │ raw dict → json.dumps                              │ raw bytes
            ▼                                                    ▼
        ┌──────────────────────  MassiveNormalizer.on_message  ───────────────────┐
        │  source="massive_rest"            │            source="massive_ws"       │
        │  parse → validate price/size      │  ms→ns coerce, ts-range guard,       │
        │  (NaN/Inf/neg reject)             │  dedup by (sym,feed,seq,fingerprint),│
        │  fingerprint dedup / seq-reuse→CORRUPTED, gap (WS on; REST opt-in),      │
        │  halt on/off (BT-5), correlation_id @ boundary, internal sequence        │
        └──────────────────────────────┬──────────────────────────────────────────┘
                                        │ typed NBBOQuote | Trade
                 ┌──────────────────────┴───────────────────────┐
                 ▼ (backfill)                                    ▼ (live)
        EventLog.append_batch ──► [multi-symbol scratch-log      queue.Queue ─► events()
                 │               + resequence_event_list          │  (+ IdleTick on
                 │               + replace_events]                 │   1s timeout,
                 ▼                                                  │   async-fill-drain only)
        DiskEventCache.save (per sym/day JSONL.gz + manifest:      │
          checksum, event_schema_hash, normalizer_version,         │
          counts, ingestion_health, created_at)                    │
                 │ load: checksum+schema+count verify, else None→API│
                 ▼ (cache_replay: merge all days+syms → resequence) │
        InMemoryEventLog (append/append_batch/replace_events        │
          all run _stabilize_market_slice + _enforce_market_order,  │
          relaxed for live/paper via enforce_market_order=False)    │
                 │                                                   │
                 ▼ ReplayFeed.events()                               │
        - filters NBBOQuote|Trade                                    │
        - re-checks event_merge_sort_key monotonic → CausalityViolation
        - SimulatedClock.set_time(exchange_ts + market_data_latency_ns)
          (BT-17 visibility time, monotonic-only)                    │
                 │                                                   │
                 └───────────────► ExecutionBackend.market_data ◄────┘
                                          │ events()
                                          ▼
                            Orchestrator._run_pipeline
                   NBBOQuote → _process_tick → data-health gate → M1 append(quote)*
                              → M2 … SENSOR_UPDATE … signal/risk/order path
                   Trade     → _process_trade → halt/SSR update → data-health gate
                              → M1 append(trade)* (HALTED: append+publish, no router)
                   IdleTick  → _drain_async_fills only (never logged, never on bus)
                   (* append skipped in backtest/replay: _events_prelogged=True)
```

---

## 3. Invariant Compliance Matrix

| Invariant | Verdict | Evidence |
|-----------|---------|----------|
| **Inv-5 — Deterministic replay** | **PASS** | Canonical key `(exchange_timestamp_ns, symbol, type_rank, sequence)` (`src/feelies/storage/event_resequence.py:33-43`); `resequence_event_list` assigns contiguous sequence + deterministic `correlation_id` (`:46-68`); disk cache round-trips Decimal→str / tuple→list losslessly through `JsonLineEventSerializer` (`src/feelies/core/serialization.py:62-148`); `tests/determinism/` — **108 passed, 0 failed** (this pass, `PYTHONHASHSEED=0`). |
| **Inv-6 — Causality** | **PASS** | `ReplayFeed.events()` raises `CausalityViolation` on backward merge-key (`src/feelies/ingestion/replay_feed.py:90-98`); `InMemoryEventLog._enforce_market_order` defends at insert for ingest/replay logs (`src/feelies/storage/memory_event_log.py:110-125`); BT-17 visibility-time gating advances the clock only forward (`replay_feed.py:100-107`, `if visible_ns > self._clock.now_ns()`); `tests/causality/test_anti_lookahead.py` passes. Live/paper logs are intentionally relaxed (`enforce_market_order=False`) for arrival-ordered append and re-imposed to canonical order at forensic-replay time — documented at `memory_event_log.py:42-57` and unchanged since the 06-11 ING-01 fix. |
| **Inv-9 — Backtest/live parity** | **PARTIAL** | Same `_process_tick`/`_process_trade`/`ExecutionBackend.market_data.events()` for all modes (`src/feelies/execution/backend.py:34-99`); PAPER shares one `MassiveNormalizer` instance across `MassiveLiveFeed` and the orchestrator's `DataHealth` gate (`src/feelies/execution/paper_backend.py:43-46`, docstring at `:9-12`). Gaps: live queue-overflow and partial-subscription do not escalate `DataHealth` (DI-01/DI-02 below); backtest runs with `normalizer=None` so the runtime health gate is structurally inert there (`orchestrator.py:6601-6602`) — this asymmetry is *intentional and documented* (data-engineering SKILL.md "Backtest vs live health-gate parity"), not re-flagged as a defect. |
| **Inv-10 — Clock abstraction** | **PARTIAL** | Normalizer `received_ns` and the ts-range guard use the injected `Clock` (`massive_normalizer.py:740-769`); `ReplayFeed`/routers use `SimulatedClock`; **no raw `datetime.now()` / `datetime.utcnow()` / `time.time()` anywhere in `src/feelies/ingestion/` or `src/feelies/storage/`** (verified by direct grep, zero matches). Carve-outs, both provenance-only: `DiskEventCache._created_at_utc()` → `time.gmtime()` when no clock injected, and exercised at every real call site (`disk_event_cache.py:82-87`; DI-07); factor-loadings freshness → `time.time()` last resort (`bootstrap.py:2295-2304`; DI-07, improved since 06-19). |
| **Inv-11 — Fail-safe default** | **PARTIAL** | Cache `load()` fails closed to `None` on unreadable manifest, schema mismatch, checksum mismatch, deserialize error, or count mismatch (`disk_event_cache.py:128-184`); `CORRUPTED` is terminal and force-flattens + degrades macro (`orchestrator.py:6618-6633`); REST partial pagination refuses checkpoint and refuses to normalize (`massive_ingestor.py:378-389`); oversized/malformed frames dropped pre-`json.loads` (`massive_normalizer.py:313-326`); shipped configs fail closed on non-HEALTHY ingest/zero-event backtests (DI-04, revised). Not fail-safe: live queue overflow and partial WS subscription are warn-and-continue with no exposure reduction (DI-01/DI-02); anonymous malformed frames cannot trip `CORRUPTED` (DI-05). |
| **Inv-13 — Provenance** | **PARTIAL** | `correlation_id` + internal `sequence` assigned at the boundary via `make_correlation_id` on every parse path (`massive_normalizer.py:461,529,643,707`); cache manifest persists checksum/schema_hash/counts/normalizer_version/created_at/ingestion_health (`disk_event_cache.py:238-250`). Gaps: rejected live events never reach `EventLog` (DI-03); `normalizer_version` is written but not enforced on load (DI-06). No raw-vendor log exists, but this matches the data-engineering skill's Inv-1 (post-normalization storage only) — not re-flagged as a defect (06-11 ING-06 already reconciled the doc/code mismatch on this point). |

---

## 4. Findings Table

| ID | Severity | Effort | Component | Finding | Evidence | Recommendation | Test gap? |
|----|----------|--------|-----------|---------|----------|-----------------|-----------|
| DI-01 | **P1** | S | `MassiveLiveFeed` | Queue overflow drops normalized events without setting `DataHealth.GAP_DETECTED` or degrading macro state. | `_consume()` drop-on-`queue.Full` (`src/feelies/ingestion/massive_ws.py:388-396`); counter exposed (`:129-138`) but not consumed by any health path. | On sustained overflow (e.g. N drops in a rolling window), call `normalizer.notify_feed_interrupted(self._symbols)` (already exists, used today only on reconnect at `massive_ws.py:256`) or publish a critical alert the orchestrator treats as a data gap. | Yes — `tests/ingestion/test_massive_normalizer.py:762-789` covers non-blocking drop/log only, no health assertion. |
| DI-02 | **P1** | M | `MassiveLiveFeed` / `MassiveNormalizer` / orchestrator | Partial WS subscription confirmation is WARN-only; the two coverage safeguards that appear to guard this (`strict_normalizer_symbol_coverage`, boot-time `_verify_data_integrity`) cannot detect it because `register_symbols()` pre-marks every configured symbol HEALTHY-by-presence before the WS ever confirms a channel. | `_subscribe()` only raises at zero confirmations (`massive_ws.py:332-341`); `register_symbols(config.symbols)` at bootstrap (`bootstrap.py:475`) precedes `live_feed.start()` (`scripts/run_paper.py:212` vs `:245`); `all_health()` includes registered-but-unseen symbols as HEALTHY (`massive_normalizer.py:367-370`); both gates key off `all_health()` membership (`orchestrator.py:6607-6617`, `:6753-6758`). | Track expected `(symbol, channel)` pairs distinctly from "registered"; only mark a channel HEALTHY after its first confirmed subscribe response, and treat "never confirmed" as `GAP_DETECTED` (or fail connection) rather than defaulting to HEALTHY. | Yes — `tests/kernel/test_data_integrity_runtime.py:178-193` (`TestStrictNormalizerSymbolCoverage`) swaps the whole normalizer object post-boot rather than modeling a channel that never confirmed; no test constructs a real `MassiveNormalizer` + `register_symbols` + partial-`_subscribe` scenario end-to-end. |
| DI-03 | **P1** | M | orchestrator / provenance | Bad/gappy live events are dropped before `EventLog.append`, so the forensic replay log lacks the exact event that triggered a `DataHealth` block. | Quote path: health gate at `orchestrator.py:2314` precedes `self._event_log.append(quote)` at `:2333`. Trade path: CORRUPTED/GAP-blocked trades return before append at `:1856-1871`; HALTED trades are the one exception, still appended+published (`:1864-1870`) for forensic continuity. | Persist a bounded quarantine/audit sink for rejected normalized events (or raw frames) independent of `EventLog`, so trading stays fail-safe while the triggering event remains reconstructable. | Yes — no test asserts provenance for a rejected event. |
| DI-04 | P2 | S | `PlatformConfig` / shipped configs | Dataclass-level defaults for `require_healthy_disk_cache_manifests` / `backtest_enforce_ingest_terminal_health` are `False` (fail-open), but `platform.yaml` (the CLI's own default config) and every `configs/bt_*.yaml` inherit `backtest_enforce_ingest_terminal_health: true` + `backtest_reject_zero_ingest_events: true` via `extends:`. `require_healthy_disk_cache_manifests` is unset everywhere. | Defaults: `platform_config.py:99,114`. `platform.yaml:33-34`. Inheritance verified via `grep -n extends configs/bt_*.yaml` (all 6 point to `../platform.yaml`, directly or via `bt_sig_benign_midcap.yaml`) and `deep_merge_mapping` (`core/config_yaml.py:16-31`) preserving unset base keys. `backtest_enforce_ingest_terminal_health`'s worst-case-per-symbol check: `ingestion/ingest_health.py:27-31`. | Flip the `PlatformConfig` dataclass defaults to match the shipped `platform.yaml` values so a bespoke config or direct `PlatformConfig()` construction is fail-closed by default too; optionally set `require_healthy_disk_cache_manifests: true` in `platform.yaml` for defense-in-depth even though `backtest_enforce_ingest_terminal_health` covers the same ground today. | Partial — strict-gate unit tests exist; no test pins that `platform.yaml`'s effective (post-`extends`) config is fail-closed. |
| DI-05 | P2 | S | `MassiveNormalizer` | Malformed frames with no usable symbol cannot mark any stream `CORRUPTED`; only symbol-known bad prices trip health. | `_mark_corrupted()` early-returns and only logs when `symbol` is falsy or `"UNKNOWN"` (`massive_normalizer.py:945-951`). JSON decode failures return `[]` before any symbol is known (`:322-326`). | Add a global (non-per-symbol) malformed-frame counter and degrade when anonymous parse failures exceed a small threshold within a window. | Partial — symbol-known bad-price tests exist; anonymous-frame health impact is untested. |
| DI-06 | P2 | S | `DiskEventCache` | `normalizer_version` is persisted but not part of load acceptance; only `event_schema_hash` invalidates a cache. | `exists()` checks only `event_schema_hash` (`disk_event_cache.py:117`); `load()` same (`:134-136`); `save()` writes `normalizer_version` (`:246`) that is never read back for validation. | Either fold `_NORMALIZER_VERSION` into `_compute_schema_hash()`, or compare manifest `normalizer_version` on load and warn/reject on mismatch. | Yes — no normalizer-version-mismatch test found in `tests/storage/test_disk_event_cache.py`. |
| DI-07 | P2 | S | `DiskEventCache` / bootstrap | Wall-clock fallback for cache `created_at` is exercised in every real call path (no call site injects `clock=`); factor-loadings freshness has a documented, improved but still-present wall-clock last resort. | `_created_at_utc()` fallback: `disk_event_cache.py:82-87`. Call sites all omitting `clock=`: `storage/cache_replay.py:79`, `harness/backtest_runner.py:326`, `scripts/sensor_feature_ic.py:698`, `scripts/calibrate_hawkes.py:260`. Factor-loadings: `bootstrap.py:2295-2304` (embedded `_meta.as_of_ns` preferred; `time.time()` last resort with WARNING). | Thread the run's `Clock` into `DiskEventCache(..., clock=clock)` at each harness/script construction site. | Partial — no test asserts `created_at` provenance derives from an injected clock in the harness path. |
| DI-08 | P2 | M | `storage/reference` | Reference-data validation ownership is split: `event_calendar` / `corporate_actions` validate in `storage/reference`; `factor_loadings` / `sector_map` remain marker-only packages, with real validation in `composition/` consumers. | `storage/reference/factor_loadings/__init__.py` and `.../sector_map/__init__.py` are single-line docstrings. Validation lives in `composition/factor_neutralizer.py:195` and `composition/sector_matcher.py:119`. | Centralize factor/sector loaders under `storage/reference` so schema, freshness, and provenance share one contract with the already-centralized calendar/ex-date loaders. | Yes. |
| DI-09 | P2 | M | `MassiveNormalizer` / consumers | No shared trade-condition eligibility (regular-sale / irregular-print) policy at the ingestion boundary beyond halt/SSR side effects. | Conditions parsed and preserved symmetrically on REST/WS (`massive_normalizer.py:501-502,531,684-685,709,719`). No eligibility/irregular-print filter found anywhere in `src/feelies/` (`grep -rln "irregular\|regular_sale\|eligib"` → no matches). | Decide and document: either "all prints pass through, eligibility is a downstream concern" as intentional design, or add a shared eligibility classifier used consistently by sensors and queue-volume models. | Yes — REST/WS parity tests cover field preservation, not eligibility semantics. |
| DI-10 | P2 | S | `.cursor/skills/data-engineering/SKILL.md` | Skill doc claims `EventSerializer` is unimplemented ("still TODO"); the code has had a complete, tested implementation since before the 06-11 audit, and two prior audits already recorded it fixed. Doc has not been corrected across 3 audit cycles. | `JsonLineEventSerializer` (`core/serialization.py:151-176`); wired into `DiskEventCache` (`disk_event_cache.py:45,167,223`); round-trip + bit-equality tests in `tests/core/test_serialization.py`; prior confirmations: `docs/audits/data_ingestion_audit_2026-06-11.md` §1 ING-05 "Fixed", `docs/audits/data_ingestion_audit_2026-06-19.md` §1 executive-summary item 10. | Update the skill's "EventSerializer" paragraph and the "Design Decisions" table to state the serializer is implemented and cite the module, so the mandatory pre-audit skill read (`docs/prompts/audit_data_ingestion.md` step 4) stops propagating a false premise. | n/a (doc). |

---

## 5. Live vs Replay vs Backfill Parity

| Dimension | Backfill (REST → EventLog) | Replay (EventLog → ReplayFeed) | Live (WS → orchestrator) | Assessment |
|-----------|----------------------------|----------------------------------|----------------------------|------------|
| Typed boundary | `MassiveHistoricalIngestor` → `MassiveNormalizer.on_message(..., "massive_rest")` (`massive_ingestor.py:432`) | reads already-normalized events | `MassiveLiveFeed` → `MassiveNormalizer.on_message(..., "massive_ws")` (`massive_ws.py:383-387`) | Pass — no bypass found. |
| `correlation_id` / `sequence` | reassigned by `resequence_event_list` (multi-symbol/global paths) | as persisted post-resequence | assigned per-frame in arrival order | Intentionally divergent, documented at `event_resequence.py:15-18`. |
| Gap detection | off by default (thinned SIP), opt-in via `enable_rest_sequence_gap_detection` (`platform_config.py:123`, `massive_normalizer.py:640,703`) | n/a (reads normalized stream) | on (`_check_gap`, `massive_normalizer.py:867-902`) | Correct, intentional asymmetry (06-11 ING-08 acknowledged, unchanged). |
| Ordering | single-symbol sorts `(sip_ts, type_rank, seq)` matching canonical key (`massive_ingestor.py:407-423`); multi-symbol scratch-log + `resequence_event_list` + `replace_events` (`massive_ingestor.py:216-221,272-296`) | `ReplayFeed` re-checks `event_merge_sort_key` monotonic, raises `CausalityViolation` (`replay_feed.py:90-98`) | arrival order accepted (`enforce_market_order=False` for live/paper logs, `memory_event_log.py:42-57`) | Pass; forensic replay of a live log must resequence before reuse — no production path replays a live log directly (unchanged from 06-11 §11.2 verification). |
| Clock / latency | `SimulatedClock` does not advance during ingest; `received_ns` constant per REST batch | `SimulatedClock.set_time(exchange_ts + market_data_latency_ns)`, monotonic-only (`replay_feed.py:100-107`) | `WallClock` per-frame `received_ns` (`massive_ws.py:382`) | Pass, documented semantics difference (data-engineering skill "received_ns semantics"). |
| DataHealth gate | drives manifest `ingestion_health`, folded into `ingest_terminal_symbol_health` for optional strict backtest gating | inert — backtest runs with `normalizer=None` (`orchestrator.py:6601-6602`) | active — `_data_health_blocks_trading` gates every tick/trade (`orchestrator.py:6587-6641`) | Intentional asymmetry (documented); residual practical risk narrowed by DI-04's `extends:` chain finding. |
| Queue-overflow / partial-subscription health impact | n/a | n/a | **not wired to `DataHealth`** (DI-01, DI-02) | Gap — live-only, no replay/backfill equivalent failure mode exists to compare against. |
| `_events_prelogged` | n/a | `True` — no re-append on replay | `False` — every quote/trade appended at M1/`_process_trade` | Correct: replay must not double-log; live must log (unchanged). |

---

## 6. Ordering & Causality Deep-Dive

**Canonical sort key** (`event_resequence.py:33-43`):
`(exchange_timestamp_ns, symbol, type_rank, sequence)`, `NBBOQuote=0 < Trade=1`.
Quotes precede trades at equal exchange time; symbol is the secondary
tie-break; the fourth field is the *pre-reassignment* sequence, preserving
intra-batch order. This key is applied uniformly at every merge point
found in the codebase:

| Merge point | Behavior |
|-------------|----------|
| `MassiveHistoricalIngestor.ingest_symbol_parallel` | Downloads quotes/trades in parallel per symbol, sorts by `(sip_timestamp, type_rank, sequence_number)` — aligned to the canonical key (`massive_ingestor.py:407-423`, comment explicitly documents the 06-11 ING-02 fix). |
| `MassiveHistoricalIngestor.ingest` (multi-symbol) | Accumulates each symbol's full-session batch into an order-tolerant scratch `InMemoryEventLog(enforce_market_order=False)` (`:216-221`), then `_finalize_multi_symbol_merge` reads **both** the destination and scratch logs, `resequence_event_list`s the union, and `replace_events` once (`:272-296`) — this also re-includes any pre-existing destination content and avoids `replace_events([])` wiping a checkpoint-skipped run (the 06-11 ING-10 follow-up fix, still intact). |
| `backtest_runner.ingest_data` (API path) | Global `resequence_event_list` across all cache-hit + API-miss days/symbols before building the replay log (`harness/backtest_runner.py:432`). |
| `cache_replay.load_event_log_from_disk_cache` | Global resequence across all requested symbol/day cache files (`storage/cache_replay.py:125`). |
| `backtest_prep.prepare_backtest_event_log` (RTH filter) | Single pass over already-ordered `event_log.replay()`; filtered rows are appended to a fresh `InMemoryEventLog` in the same relative order — no re-sort needed since the stabilization in `append_batch` is a no-op on already-canonical input (`harness/backtest_prep.py:153-176`). |
| `InMemoryEventLog.append` / `append_batch` / `replace_events` | `append_batch`/`replace_events` run `_stabilize_market_slice` (canonical in-place re-sort of the `NBBOQuote`/`Trade` rows in the batch) before the monotonicity guard; single `append` has no stabilization — correct for pre-sorted replay, intentionally relaxed for live (`memory_event_log.py:67-125`). |
| `ReplayFeed.events()` | Defends, does not impose: raises `CausalityViolation` if the upstream `EventLog` was not merge-sorted (`replay_feed.py:84-98`). |

**Equal-timestamp semantics:** deterministic, not micro-batched (matches
the backtest-engine skill's documented "micro-batching is a design
target, not implemented" status) — at equal `exchange_timestamp_ns`,
order is quote → trade, then symbol, then pre-reassignment sequence.
`sorted()` is stable, so this is total within any merged batch.

**BT-17 visibility / anti-lookahead trace:**
1. `ReplayFeed.events()` computes `visible_ns = exchange_timestamp_ns + market_data_latency_ns` and calls `SimulatedClock.set_time(visible_ns)` **only if** `visible_ns > now` (`replay_feed.py:100-107`) — never moves time backward, so ties or out-of-order visibility times cannot regress the clock.
2. The event is yielded only after the clock has advanced.
3. Orchestrator `_process_tick_inner` runs the data-health gate, then the M0→M1 transition and `EventLog.append`, then the sensor/signal/risk/order pipeline — all against the now-current (post-visibility) `SimulatedClock` (`orchestrator.py:2314-2333` onward).
4. `market_data_latency_ns` (feed visibility) and `backtest_fill_latency_ns` (fill deferral inside the routers) are independent legs — no double-counting was found; the routers defer fill eligibility separately from when the clock advances for feature computation.

No lookahead path was found: every quote a sensor observes has already
had its visibility time applied to the clock before the sensor layer
runs.

---

## 7. Storage & Cache Integrity

`DiskEventCache` stores *normalized* events (JSONL.gz + manifest), not
raw vendor frames — this matches the data-engineering skill's Inv-1 as
currently written (06-11 ING-06 already reconciled a prior doc/code
mismatch on this point; not re-flagged).

**Strengths (re-verified this pass):**

| Area | Evidence |
|------|----------|
| Schema invalidation | `_compute_schema_hash()` hashes sorted dataclass field names/types plus `_CACHE_SEMANTIC_VERSION` (`disk_event_cache.py:53-64`). |
| Corrupt-cache rejection | `load()` returns `None` (→ API fallback, Inv-11) on unreadable manifest, schema mismatch, checksum mismatch, deserialize failure, or event-count mismatch (`:128-184`). |
| Atomic writes | Data written before manifest, both via `.tmp` + `os.replace()`, so a crash between the two leaves `exists() == False` (`:232-254`). |
| Round-trip fidelity | `JsonLineEventSerializer` preserves Decimal-as-string and tuple-as-list, with substring type matching robust to `from __future__ import annotations` stringized types (`core/serialization.py:62-148`); bit-equality tested in `tests/core/test_serialization.py`. |
| Manifest provenance | symbol/date/counts/checksum/schema_hash/normalizer_version/created_at/ingestion_health, all written per save (`disk_event_cache.py:238-250`). |

**Fragile areas (re-verified, see Findings Table for detail):**

| Area | Assessment |
|------|------------|
| `normalizer_version` | Persisted, never enforced on load (DI-06). |
| `created_at` provenance | Wall-clock fallback exercised at every real call site — no harness or script injects a clock (DI-07). |
| Feature snapshots | `InMemoryFeatureSnapshotStore` (explicitly non-durable, dev/test-only per its own docstring) accepts stored checksums as short as 8 hex chars via prefix match (`storage/memory_feature_snapshot.py:13,46-58`) — acceptable for a volatile store, not a durable provenance standard; unchanged from 06-19, not re-numbered as it carries no new evidence. |
| Raw auditability | No immutable raw-vendor archive; re-normalization under a future normalizer revision requires re-hitting the REST API (design target per skill, not a bug). |

---

## 8. Test Coverage Map

Environment note: this pass required `uv sync --all-extras` before any
test could import `feelies` (the sandbox starts with no venv populated;
`AGENTS.md`/`CLAUDE.md` document this as the standard setup step). After
sync, targeted commands:

```bash
PYTHONHASHSEED=0 uv run pytest tests/ingestion/ tests/storage/ \
  tests/causality/test_anti_lookahead.py -q
→ 196 passed, 19 skipped in 5.54s

PYTHONHASHSEED=0 uv run pytest tests/determinism/ -q
→ 108 passed in 16.47s
```

All 19 skips are legitimate and expected: 16 require `MASSIVE_API_KEY`
(`test_massive_functional.py` ×2, `test_parallel_ingest_integration.py`
×14), 2 require the US RTH window (`tests/paper/conftest.py`), and 1
(`test_massive_ingestor.py:170`) only applies when the `massive` SDK is
absent — it correctly self-skips now that `uv sync --all-extras`
installed it. No unexpected failures; no regressions since 06-19's 178
passed / 4 skipped baseline (that run predated `uv sync --all-extras` in
its environment and used a narrower file selection).

| Behavior | Coverage |
|----------|----------|
| REST/WS normalizer parsing, dedup, gap, halt, timestamp, condition parity | `tests/ingestion/test_massive_normalizer.py`, `tests/ingestion/test_rest_ws_parity.py` |
| Multi-symbol/multi-day resequence and correlation-id rebuild | `tests/ingestion/test_resequence_fidelity.py`, `tests/storage/test_event_resequence.py` |
| `ReplayFeed` causality and BT-17 visibility-time clock behavior | `tests/ingestion/test_replay_feed.py`, `tests/causality/test_anti_lookahead.py` |
| `InMemoryEventLog` append/append_batch/replace ordering + relaxed live mode | `tests/storage/test_memory_event_log.py` |
| Disk cache checksum/schema/count/round-trip | `tests/storage/test_disk_event_cache.py` |
| Cache-only replay health gate | `tests/storage/test_cache_replay.py` |
| `EventSerializer` round-trip + bit-equality | `tests/core/test_serialization.py` |
| Live WS queue overflow (drop/log mechanics) | `tests/ingestion/test_massive_normalizer.py:762-789` (`TestMassiveLiveFeedBackpressure`) — mechanics only |
| Live WS queue overflow → `DataHealth`/macro impact | **Missing** (DI-01) |
| Partial WS subscription confirmation mechanics | `tests/ingestion/test_massive_normalizer.py:676-707` (`TestMassiveLiveFeedValidation`) — auth/full-success/full-failure only, no partial-success case |
| Partial WS subscription → `strict_normalizer_symbol_coverage` interaction | **Missing** (DI-02) — nearest test (`tests/kernel/test_data_integrity_runtime.py:178-193`) swaps the whole normalizer, doesn't model channel-level partial confirmation |
| Rejected bad/gappy event forensic provenance | **Missing** (DI-03) |
| Normalizer-version cache invalidation | **Missing** (DI-06) |
| Cache `created_at` derives from injected clock in real harness paths | **Missing** (DI-07) — unit-level clock injection is tested; no harness-level assertion |
| Trade-condition eligibility / irregular-print filtering | **Missing** (DI-09) — parity tests cover field preservation only |
| Massive functional network behavior | Present, appropriately skipped without `MASSIVE_API_KEY` |

**Determinism sensitivity:** `tests/determinism/` locks sequence
allocation and emission order end-to-end (108 tests, all passing this
pass). Any change to `event_merge_sort_key`, the resequence tie-break, or
the quote-before-trade rule would require deliberately re-baselining
every one of these parity hashes — they are the regression tripwire for
§6 changes.

---

## 9. Prioritized Remediation Roadmap

**P1 — do first**

1. **DI-01 / DI-02 (live health-coverage blind spots).** These share a
   root cause: nothing ties actual WS data flow (or its absence) to
   `DataHealth` at channel granularity. Track `(symbol, channel)`
   confirmation explicitly in `MassiveLiveFeed`/`MassiveNormalizer`;
   only mark a channel HEALTHY after its first confirmed subscribe
   response or first message; route sustained queue-overflow into the
   same `notify_feed_interrupted` path already used for reconnect.
   *Tests:* a real `MassiveNormalizer` + `register_symbols` +
   `_subscribe` scenario where one of two channels never confirms,
   asserting the symbol is *not* silently HEALTHY; a queue-overflow
   scenario asserting `DataHealth` escalates after N drops.
2. **DI-03 (rejected-event provenance).** Add a bounded quarantine sink
   (in-memory ring buffer or dedicated log) for events the health gate
   rejects, independent of the fail-safe trading block. *Tests:* assert
   a CORRUPTED/GAP-blocked event is recoverable from the sink even
   though it never reached `EventLog`.

**P2 — parity, provenance, and doc hardening**

3. **DI-04**: align `PlatformConfig` dataclass defaults with the
   `platform.yaml` values already shipped, so a bespoke or
   programmatically-constructed config is fail-closed without relying on
   `extends:`. Add a test pinning that the post-`extends` effective
   config for every `configs/bt_*.yaml` is fail-closed.
4. **DI-05**: add a global anonymous-malformed-frame counter and a
   threshold-based degrade path independent of per-symbol tracking.
5. **DI-06**: fold `_NORMALIZER_VERSION` into `_compute_schema_hash()`,
   or compare it explicitly on load.
6. **DI-07**: thread the run's `Clock` into every `DiskEventCache(...)`
   construction site (`cache_replay.py`, `backtest_runner.py`, the two
   scripts) so `created_at` stops depending on wall time.
7. **DI-08**: move factor/sector loader validation into
   `storage/reference`, matching the calendar/ex-date pattern.
8. **DI-09**: decide and document trade-condition eligibility — either
   confirm "all prints pass through by design" or add a shared
   classifier with REST/WS parity tests.
9. **DI-10**: correct `.cursor/skills/data-engineering/SKILL.md`'s
   `EventSerializer` section (and any other stale "TODO" language it
   still carries) so the mandatory pre-audit skill read stops asserting
   a false premise for the next audit pass.
