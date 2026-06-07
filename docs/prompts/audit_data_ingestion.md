# Data ingestion & replay model audit (Claude Code)

Use this prompt in a **Claude Code** session with full repo access. Scope: feelies
market data ingestion, normalization, storage, and replay — from Massive REST/WS
through `EventLog` to `ReplayFeed` and the orchestrator market-event path.

---

## Mission

You are a senior quantitative systems engineer and data-pipeline auditor. Perform a
**read-only, evidence-based audit** of the feelies data ingestion / replay model
end-to-end — from raw vendor messages → `MassiveNormalizer` → `EventLog` →
`ReplayFeed` → orchestrator `_process_tick` / `_process_trade`.

**Primary focus:** This layer is the system's first contact with the external world.
Every downstream sensor, signal, fill model, and parity hash depends on the fidelity,
ordering, and causality of the events it produces. A silent ordering bug, lookahead
via clock semantics, or corrupt-cache acceptance invalidates all research and live
PnL attribution.

**Goal:** Identify where ingestion is rigorous vs. fragile, where replay ordering and
latency modeling are correct vs. leaky, where backtest/live parity holds vs. drifts,
and what changes would yield **deterministic, causally sound, fail-safe** market data
— without breaking platform invariants.

**Do not implement fixes in this pass.** Deliver a structured audit report with
file/line citations, severity, and prioritized recommendations.

---

## Platform context (read first)

1. Read `.cursor/skills/data-engineering/SKILL.md` end-to-end.
2. Read `.cursor/skills/backtest-engine/SKILL.md` § on event replay, ordering, clock
   & latency injection.
3. Read `.cursor/rules/platform-invariants.mdc` — especially Inv-5 (deterministic
   replay), Inv-6 (causality), Inv-9 (backtest/live parity), Inv-10 (clock
   abstraction), Inv-11 (fail-safe), Inv-13 (provenance).

### Repository facts

- **Language / tooling:** Python 3.12+, `uv run` for all commands, strict mypy on
  `src/feelies/`
- **Data vendor:** Massive (formerly Polygon.io) — REST backfill + WebSocket live
- **Canonical events:** `NBBOQuote`, `Trade` (`src/feelies/core/events.py`)
- **Three ingestion paths** (must converge on identical downstream types):
  1. **Historical backfill:** `MassiveHistoricalIngestor` → `MassiveNormalizer` →
     `EventLog`
  2. **Live stream:** `MassiveLiveFeed` → `MassiveNormalizer` → orchestrator pipeline
  3. **Replay:** `EventLog.replay()` → `ReplayFeed` → orchestrator pipeline
- **Backtest entry:** `Orchestrator.run_backtest()` via
  `ExecutionBackend.market_data.events()`
- **Cache layer:** `DiskEventCache` (per-symbol/day JSONL.gz + manifest)

---

## Scope — files to trace end-to-end

### Ingestion boundary

- `src/feelies/ingestion/normalizer.py` — `MarketDataNormalizer` protocol
- `src/feelies/ingestion/massive_normalizer.py` — WS + REST parsing, dedup, gap
  detection, fingerprints
- `src/feelies/ingestion/data_integrity.py` — `DataHealth` state machine
- `src/feelies/ingestion/ingest_health.py` — health aggregation
- `src/feelies/ingestion/massive_ingestor.py` — REST backfill, parallel ingest,
  checkpointing, multi-symbol resequence
- `src/feelies/ingestion/massive_ws.py` — live WebSocket feed, reconnect, queue
  overflow
- `src/feelies/ingestion/replay_feed.py` — `ReplayFeed`, BT-17 visibility time,
  causality guard
- `src/feelies/ingestion/idle_tick.py` — idle tick semantics (if wired)

### Storage & ordering

- `src/feelies/storage/event_log.py` — `EventLog` protocol
- `src/feelies/storage/memory_event_log.py` — in-memory impl + append_batch causality
- `src/feelies/storage/event_resequence.py` — `event_merge_sort_key`,
  `resequence_event_list`
- `src/feelies/storage/disk_event_cache.py` — cache format, schema hash, manifest,
  checksums
- `src/feelies/storage/cache_replay.py` — cache → replay path

### Integration / wiring

- `src/feelies/bootstrap.py` — how ingestion/replay backends are constructed per mode
- `src/feelies/execution/backend.py`, `paper_backend.py` — `MarketDataSource` contract
- `src/feelies/harness/backtest_runner.py`, `backtest_prep.py` — ingest → resequence
  → run
- `scripts/run_backtest.py`, `scripts/smoke_pipeline.py` — CLI ingest/replay paths
- `src/feelies/kernel/orchestrator.py` — M1 `EventLog.append`, `_process_tick` /
  `_process_trade` (read-only; focus on market-event path only)

### Tests (map coverage gaps)

- `tests/ingestion/**`
- `tests/storage/test_memory_event_log.py`, `test_disk_event_cache.py`,
  `test_cache_replay.py`
- `tests/causality/test_anti_lookahead.py`
- `tests/determinism/` — parity hashes that depend on event ordering
- `tests/ingestion/test_massive_functional.py` — network-backed; note but don't
  require API key

**Out of scope:** alpha logic, sensors, fills, promotion gates, regime detection.

---

## Audit questions (answer each with file:line evidence)

### A. Ingestion boundary integrity

1. Is **every** market data path (REST, WS, cache load) forced through
   `MassiveNormalizer` (or equivalent typed boundary)? Any bypass?
2. Are `correlation_id` and `sequence` assigned consistently at the boundary
   (`make_correlation_id`)? Do live vs replay vs resequenced backfill produce
   **intentionally different** IDs — and is that documented/consumed correctly
   downstream?
3. REST vs WS: is gap detection correctly **disabled for REST** (thinned SIP rows)
   and **enabled for WS**? What happens with `enable_rest_sequence_gap_detection`?
4. Dedup semantics: exact duplicate vs sequence reuse with conflicting payload →
   `CORRUPTED`. Are fingerprints complete for all wire fields that matter?
5. Timestamp normalization: ms vs ns coercion, exchange vs receipt time
   (`timestamp_ns` from injectable clock). Any path using raw `datetime.now()` in
   core logic (Inv-10 violation)?
6. Trade conditions / irregular prints: are condition codes parsed and filtered
   consistently across REST and WS?
7. `DataHealth` transitions: can `GAP_DETECTED` recover to `HEALTHY`? Is `CORRUPTED`
   truly terminal? How does orchestrator/bootstrap degrade on gap vs corrupt?

### B. Deterministic ordering & resequencing (Inv-5 / Inv-6)

1. Canonical sort key:
   `(exchange_timestamp_ns, symbol, type_rank[quote<trade], prior_sequence)`. Is it
   applied **everywhere** multi-symbol/multi-day streams merge?
2. Known risk from skills: `scripts/run_backtest.py` may concatenate without global
   timestamp sort for multi-symbol. Verify current code — is this still true?
3. `MassiveHistoricalIngestor` multi-symbol path calls `replace_events` after
   resequence — is single-symbol ingest order preserved? Parallel per-symbol ingest +
   merge: race or ordering bugs?
4. `ReplayFeed` raises `CausalityViolation` on out-of-order keys — who is
   responsible for pre-sorting? Are there call sites that skip resequence?
5. Micro-batch semantics at equal `exchange_timestamp_ns`: quotes before trades,
   symbol tie-break. Is intra-batch order stable and documented?
6. Does `InMemoryEventLog.append_batch` enforce the same ordering invariant as
   `ReplayFeed`?

### C. Replay model & causality (BT-17)

1. `ReplayFeed` sets `SimulatedClock` to
   `exchange_timestamp_ns + market_data_latency_ns`. Is this wired from
   bootstrap/config? Default 0 — is that safe for production backtests?
2. Separation of **market data latency** vs **fill/submit latency** — any leakage or
   double-counting?
3. `ReplayFeed` only advances clock forward (monotonic). What happens with equal
   visibility times across events?
4. Anti-lookahead: trace one `NBBOQuote` from `ReplayFeed.events()` through
   orchestrator M1→M2→SENSOR_UPDATE. Can any sensor/feature/signal read exchange time
   before visibility time?
5. Compare live `MassiveLiveFeed` clock behavior vs `ReplayFeed` — parity gaps
   (Inv-9)?

### D. Storage, cache, provenance (Inv-11, Inv-13)

1. `EventLog` contract: `append` vs `append_batch` vs `replace_events` — atomicity,
   failure modes, replay determinism
2. `DiskEventCache`: schema hash, semantic version bump, manifest checksums,
   `require_healthy_disk_cache_manifests` — fail-safe on corrupt cache?
3. Round-trip: event → JSONL.gz → load → replay. Any field loss (Decimal, tuple
   conditions)? Bit-identical after reload?
4. Is there an immutable **raw** vendor log, or only normalized events? Skill says
   "immutable raw log" — gap between design doc and implementation?
5. `EventSerializer` noted as NOT YET IMPLEMENTED in skill — assess impact on
   persistence guarantees
6. Provenance metadata on backfills: source tag, ingest timestamp, version — what is
   actually persisted?

### E. Live feed robustness

1. WS reconnect backoff, auth failure handling, subscription validation
2. Bounded queue (100k) overflow — events dropped with warning. Downstream impact?
   Detectable?
3. Thread/async model — any GIL or blocking risk on hot path?
4. Idle tick injection — purpose and parity with replay (sessions with sparse quotes)

### F. Backtest/live parity & operator paths

1. Trace `feelies backtest` CLI and `backtest_runner.ingest_data()` — cache hit vs
   API miss vs multi-day merge
2. Does paper trading use the same normalizer + event types as backtest replay?
3. Orchestrator appends every inbound quote/trade to `EventLog` at M1 — does live
   session log match what replay would consume?

### G. Test & determinism coverage gaps

1. What behaviors have **no** test? Prioritize: multi-symbol global ordering, cache
   corruption fallback, WS queue overflow, REST/WS field parity, clock latency wiring,
   `replace_events` edge cases
2. Run targeted tests and record pass/fail:

   ```bash
   uv run pytest tests/ingestion/ tests/storage/test_memory_event_log.py \
     tests/storage/test_disk_event_cache.py tests/storage/test_cache_replay.py \
     tests/causality/test_anti_lookahead.py -q
   ```

3. Note any determinism tests that would break if ordering semantics change

---

## Deliverable

Write the audit report to **`docs/audits/data_ingestion_audit_YYYY-MM-DD.md`** using
the section structure below.

### Required sections

0. **Remediation status** — empty table (read-only audit); note if any trivial doc
   fixes made
1. **Executive summary** — 5–10 numbered findings, most severe first
2. **Architecture trace** — ASCII or mermaid diagram: REST/WS/Cache → Normalizer →
   EventLog → ReplayFeed → Orchestrator
3. **Invariant compliance matrix** — Inv-5, 6, 9, 10, 11, 13 × Pass / Fail / Partial
   with evidence
4. **Findings table** — columns: ID, Severity (P0/P1/P2), Effort (S/M/L), Component,
   Finding, Evidence (`file:line`), Recommendation, Test gap?
5. **Live vs replay vs backfill parity** — explicit diff table
6. **Ordering & causality deep-dive** — sort key, resequence call graph, all merge
   points
7. **Storage & cache integrity** — serialization, checksums, recovery protocol
   assessment
8. **Test coverage map** — covered / partial / missing behaviors
9. **Prioritized remediation roadmap** — P0 first, with suggested test additions per
   fix

### Severity definitions

- **P0:** Silent wrong data, lookahead, non-deterministic replay, corrupt cache
  accepted, safety degradation not triggered
- **P1:** Contract drift, incomplete normalization, parity gap backtest↔live, missing
  provenance, latent multi-symbol ordering bug
- **P2:** Performance, docs, research hygiene, nice-to-have hardening

### Rules

- Every finding must cite **file:line** or test name — no speculation without code
  search
- Distinguish **bug** vs **documented limitation** vs **intentional design**
- Flag skill/doc drift where `.cursor/skills/data-engineering/SKILL.md` or
  `backtest-engine/SKILL.md` disagrees with code
- Do not audit alpha logic, sensors, fills, or promotion gates — stay inside
  ingestion/replay/storage
- If you find a P0, stop and surface it in the executive summary before finishing
  the full doc

---

## Suggested investigation order

1. Read skills + invariants (above)
2. Read `event_resequence.py` + `replay_feed.py` + `massive_normalizer.py` (core
   contracts)
3. Trace bootstrap wiring for BACKTEST vs PAPER vs LIVE
4. Trace `backtest_runner.ingest_data()` and `run_backtest.py` merge paths
5. Grep for `resequence_event_list`, `replace_events`, `CausalityViolation`,
   `market_data_latency`
6. Run ingestion/storage/causality tests
7. Write the audit doc

---

## Optional scope modifiers

Prepend one of these to narrow or deepen the pass:

- **Narrow:** "Single-symbol APP/2026-03-26 backtest path only; skip WS live feed."
- **Deep:** "Also run `uv run pytest tests/determinism/ -q` and note any
  ingestion-order sensitivity in parity hashes."
- **Functional:** "If `MASSIVE_API_KEY` is set, run
  `tests/ingestion/test_massive_functional.py -m functional` and compare
  REST-normalized events to cached `DiskEventCache` round-trip."

Begin.
