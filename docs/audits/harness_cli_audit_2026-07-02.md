# Harness / CLI / Scripts Reproducibility & Fidelity Audit — 2026-07-02

**Scope:** `src/feelies/harness/` (runner, report, jsonl, cli glue, prep touchpoint),
`src/feelies/cli/` (backtest path), `scripts/` (operator + baseline-mutating), and the
matching test surface. Read-only pass — no production code, baseline, config, or ledger
was modified.

**Relationship to the prior audit:** `docs/audits/harness_cli_audit_2026-06-27.md` filed
15 findings (P0: none; P1: 8; P2: 7). Commit `c0315ab` ("Fix P1/P2 harness/CLI/scripts
audit backlog", 2026-06-27) and a follow-up `7188758` (SCALE_UP entry-classification fix)
addressed all 15. This is an independent, fresh pass over the current tree — every claim
below was re-verified against today's code, not copied from the prior report. Two commits
landed in scope since then with no dedicated harness audit: `ef6557e` (close-the-loop
two-pass `--edge-calibration` wiring) and `08c3da6` (L1→L2 boundary-time fix, which
re-baked the APP/2026-03-26 baseline to fill-count 21 / net P&L $430.85). The
`--edge-calibration` feature is the source of this audit's main new finding (R-1).

**Method:** read every in-scope file plus `AGENTS.md`, `docs/paper_rth_test_runbook.md`,
`.cursor/rules/platform-invariants.mdc`, `.cursor/skills/{backtest-engine,alpha-lifecycle,
research-workflow}/SKILL.md`. Ran the prescribed read-only commands:
`pytest tests/harness/ tests/cli/test_backtest_cli.py tests/scripts/ -q` → **58 passed**;
`pytest tests/acceptance/test_backtest_app_baseline.py test_backtest_app_config_keys.py -q`
→ **13 passed, 1 skipped** (cache miss — no disk cache for `APP/2026-03-26` in this
environment); `pytest tests/acceptance/test_bt12_reference_alpha_validation.py
test_bt13_portfolio_research_only.py -q` → **31 passed**; `python scripts/smoke_pipeline.py`
→ **exit 0, ALL STAGES PASS**. Additionally, since the disk cache needed for the APP
baseline's own reconciliation assertions is unavailable here, I built a small **live,
non-cached backtest** through the same `bootstrap.build_platform` → `orchestrator.
run_backtest()` path (via `scripts/smoke_pipeline.py`'s `_build()` harness) and
independently recomputed gross/fee/net P&L from `position_store` + `OrderAck` + the trade
journal by hand, in a script that never calls any `backtest_report` helper — see §4. I
also directly exercised the CLI (missing config, missing API key, `--strict-config`
rejection, ingestion failure) rather than relying only on reading tests.

Severity legend matches the task brief: **P0** report doesn't reconcile / run not
reproducible / CLI exits 0 on error / baseline-mutating script ungated / lossy JSONL;
**P1** config keys silently ignored / fee-population drift / paper-compare broken /
provenance identifier can collide across different effective inputs; **P2** ergonomics,
richer provenance, hardening. Each item tags **[bug] / [limitation] / [design]**.
Per the audit brief, skill sections marked **Not shipped** (daily-PnL bucketing, the
structured JSON report envelope, stochastic latency profiles) are treated as design
targets, not bugs — confirmed absent from the code, not filed as P0.

---

## 1. Executive summary

1. **[P1, bug, NEW] `--edge-calibration` is a trade-path-altering input with zero
   provenance trace.** `orchestrator.py:3178` multiplies the disclosed edge by a
   calibration factor loaded from an external JSON file (`backtest_runner.py:673-693`),
   which can change which signals clear the B4 cost gate and thus the fills/PnL — yet
   `compute_artifact_id`'s documented "five orthogonal axes"
   (`backtest_report.py:767-780`) omit it entirely, and `generate_report` never receives
   or prints it. Two runs with identical config+cache+`--edge-calibration` **path** string
   but a regenerated calibration file (or one run with the flag, one without) can produce
   different `pnl_hash`/fills with an **identical `artifact_id`**, and the printed report
   gives no way to tell after the fact whether a haircut was applied. Only a console
   `print()` (not the report) notes it. See §3, §4.6.
2. **[P1, bug, NEW] `scripts/run_paper.py` has no `--strict-config` / strict YAML-key
   rejection at all.** The prior audit's fix wired `--strict-config` into the *backtest*
   CLI only (`backtest_cli.py:163-170`); `run_paper.py`'s own arg parser
   (`run_paper.py:71-119`) and its `load_platform_config(args.config)` call
   (`run_paper.py:192`) never gained the flag, so a misspelled key in a PAPER-mode config
   — the mode that submits real orders to a live IB Gateway — can only ever warn, never
   fail closed. See §6.2.
3. **[good] Report P&L reconciles with the underlying fills.** Verified two ways: (a) the
   existing `test_app_20260326_backtest_baseline_from_disk_cache` assertion
   `sum(ack.fees) == Σ position.cumulative_fees` (skipped here, no cache — see #6 below),
   and (b) a fresh, self-built non-cached run I hand-verified myself end-to-end (§4) —
   `Net P&L = Gross P&L − Σ(ack.fees)` reconciled to the cent, and `Σ(ack.fees) ==
   Σ(position.cumulative_fees) == Σ(TradeRecord.fees)` held in this run too.
4. **[good] The prior audit's P1/P2 backlog (`c0315ab`, `7188758`) is fully and correctly
   landed** — `split_backtest_emit.py` round-trips real emitter output, `--strict-config`
   exists and is tested (`test_platform_config.py:250-257`), `PYTHONHASHSEED` is warned
   and echoed into the report (confirmed live: `hash_seed 0` in my test run), `code_version`
   folds the HEAD git SHA (confirmed live: `0.1.0+929e9fb67f1d`), `cache_data_version`
   binds to per-day event counts/health, `smoke_pipeline.py` runs green (verified: exit 0),
   `generate_bt12_fixtures.py` refuses to clobber without `--force`/`--dry-run`, and the
   explicit post-pipeline `macro == READY` gate is in place. Re-verified line-by-line, not
   assumed. See §3–§7.
5. **[P2, bug, confirmed still present] JSONL prefix-map drift, now with different
   members.** `split_backtest_emit.py:11-22`'s `_PREFIX_MAP` still carries `ORDER_ACK_JSONL`
   / `TIMING_JSONL` (confirmed: these prefixes are **never** emitted anywhere via
   `_emit_jsonl_line` — `run_paper.py`'s `PaperSessionRecorder` writes `order_acks.jsonl`
   / `timing.jsonl` directly to disk, bypassing this splitter entirely), and is still
   missing the newer `SIZEDIV_JSONL` / `NETDIV_JSONL` / `HAZARD_EXIT_JSONL` prefixes that
   the backtest genuinely emits (`backtest_jsonl.py:61,90,271`). Not data loss — the
   unmapped prefixes fall through to `f"{prefix.lower()}.jsonl"` (e.g.
   `sizediv_jsonl.jsonl`), just an inconsistent, unreviewed filename. See §5.
6. **[limitation, carried forward, partially mitigated] Real-dataset trade-path
   reproducibility is still unverified in a clean CI checkout.** The APP baseline
   functional test skips on cache miss (`test_backtest_app_baseline.py:166-185` —
   reproduced live in this audit: "1 skipped"). Mitigated since the prior audit by
   `tests/harness/test_backtest_parity_no_cache.py`, which locks Inv-5 bit-identity on a
   *synthetic* dataset without the disk cache (re-ran: **passed**) — but the actual
   reference dataset's trade path is still only locked by whatever machine last had the
   cache populated.
7. **[good] CLI exit-code contract verified empirically, not just read.** I ran the actual
   binaries: missing config file → exit 1 (`ERROR: Config file not found`); missing
   `MASSIVE_API_KEY` → exit 1; misspelled config key with `--strict-config` → exit 1
   (`ERROR: Invalid config: ... unrecognized config key(s)`); ingestion failure (sandboxed
   network) → exit 1 (`ERROR: Ingestion failed: ...`). No path returned 0 on any injected
   failure. See §6.1.
8. **[P2, bug, confirmed still present] `scripts/record_paper_perf_baseline.py` merges
   into the shared perf-baseline JSON with no pass/fail or run-quality gate.** Unlike its
   sibling `record_perf_baseline.py:92-97` (refuses `SystemExit` on a failing perf run),
   `record_paper_perf_baseline.py:50-74` only checks that `timing.jsonl` parses — any
   run-dir with *some* timing rows (aborted, degraded, non-representative) silently
   overwrites `hosts[host_label]["paper_rth"]` in `tests/perf/baselines/v02_baseline.json`.
9. **[P2, minor, confirmed still present] `run_paper.py` writes `session_start_ns` /
   `session_end_ns` as Python `float`, not `int`** (`run_paper.py:140,173`). At current
   epoch magnitudes (~1.8×10¹⁸ ns) float64 only carries ~512 ns of precision — immaterial
   for session metadata, but inconsistent with the platform's `int`-ns convention
   everywhere else and worth a one-line fix (`int(...)`).
10. **[P2, minor, NEW] `code_version()` does not flag a dirty working tree**
    (`backtest_report.py:696-706`) — it stamps the last-*committed* HEAD SHA, so a locally
    modified engine (uncommitted change to, say, `cost_model.py`) still reports the
    previous commit's `code_version`, silently.
11. **[P2, limitation, confirmed still present] Uncaught traceback (not a clean
    message+code) on a pipeline integrity exception.** `_run_backtest_phases_2_7`
    (`backtest_runner.py:776-786`) has a `try/finally` around `orchestrator.run_backtest()`
    with no `except` — an integrity failure propagates as a raw Python traceback. Exit
    code is still correctly nonzero (Python default 1); this is a UX rough edge, not a
    contract violation.
12. **[design, NEW observation] No report/diagnostics are printed when a run ends
    DEGRADED.** The explicit post-pipeline `macro == READY` gate
    (`backtest_runner.py:793-801`) returns *before* Phase 6 (`generate_report`), so an
    operator debugging a real integrity failure gets a one-line stderr message and nothing
    else — by design (a DEGRADED run's numbers can't be trusted), but worth knowing when
    triaging.
13. **[good] Baseline-mutating scripts remain safely gated.**
    `rebaseline_parity_hashes.py` writes nothing (prints only); `record_perf_baseline.py`
    refuses to record from a failing perf run; `generate_bt12_fixtures.py` refuses to
    overwrite existing fixtures without `--force`/`--dry-run` (verified by reading the
    guard clause — not re-run, since re-running would touch committed fixtures). No P0
    "ungated baseline-mutating script" found.
14. **[limitation, confirmed] Full report text is not bit-identical across runs/hosts —
    only the Parity block is**, and this is now explicitly documented in-code
    (`backtest_report.py:329-334`). Confirmed the Latency section prints wall-clock
    percentiles and a spike-origin timestamp that will differ run to run.

---

## 2. Run-artifact inventory

What a backtest run (`run_backtest_api` → `_run_backtest_phases_2_7`) produces, and
whether it carries provenance.

| Artifact | Where | Provenance captured? | Notes |
|---|---|---|---|
| Operator text report (stdout) | `generate_report` `backtest_report.py:139-625` | Partial | Parity block deterministic; Latency block wall-clock, documented non-deterministic (`:329-334`) |
| `pnl_hash` (trade sequence) | `compute_parity_hash` `:709-732` | Yes | SHA-256 over ordered `TradeRecord` canonical JSON |
| `config_hash` | `compute_config_hash` `:735-741` = `config.snapshot().checksum` | Yes | Resolved `PlatformConfig` + per-run ingest-health rows |
| `parity_hash` (combined) | `compute_combined_parity_hash` `:744-750` | Yes | `SHA(pnl_hash:config_hash)` |
| `artifact_id` | `compute_artifact_id` `:759-802` | **Partial — incomplete** | Five documented axes (strategy/config/data/engine/code version); a sixth live input, edge-calibration factors, is unlisted (R-1) |
| `engine_version` | `ENGINE_VERSION = "0.1.0"` `:756` | Weak alone | Paired with `code_version()` for a real anchor |
| `code_version` | `code_version()` `:696-706` | Yes, HEAD-only | Folds git HEAD SHA (confirmed live: `0.1.0+929e9fb67f1d`); does not flag a dirty tree (P2-4) |
| `data_version` | `cache_data_version()` preferred, `live_data_version()` fallback `runner.py:814-821` | Yes (cache path); Weak (fallback) | Per-day event counts + ingestion health, not a full byte-hash (documented tradeoff, `backtest_report.py:655-658`) |
| **Edge-calibration factors** | `EdgeCalibrationStore` via `--edge-calibration` `runner.py:673-693`, applied `orchestrator.py:3175-3192` | **No** | Alters the trade path (B4 gate); absent from `artifact_id`, the report, and `config_hash` entirely — only a console `print()` (R-1) |
| `FILL_JSONL` / `SIGNAL_JSONL` / etc. (stdout, opt-in) | `backtest_jsonl.py` | Field-level | `fill_price` exact (`str(Decimal)`); SIGNAL/INTENT/SIZEDIV/NETDIV float-coerce Decimals (documented lossy, `backtest_jsonl.py:1-9`) |
| Verification table | `run_verification` `backtest_report.py:805-859` + `print_verification` `runner.py:499-516` | n/a | 7 checks → exit 2 on any FAIL |
| Disk cache (JSONL.gz) | `DiskEventCache` (ingest path, owned elsewhere) | Yes | Per-day manifest incl. `ingestion_health` |
| `hash_seed` | `os.environ["PYTHONHASHSEED"]` echoed `:619` | Yes (echoed, not enforced) | Warned pre-run if `!= "0"` (`runner.py:522-539`); not pinned or re-exec'd |
| Host / env (locale, thread count, OS) | — | No | Not echoed anywhere |

Gap vs Inv-13: the run now captures config, alpha-manifest, code SHA, and content-bound
data version — a real improvement since the prior audit — but the new close-the-loop
edge-calibration input (R-1) and the host environment remain uncaptured.

---

## 3. Reproducibility audit (Inv-5)

**Reproducible by construction, confirmed:** order IDs are SHA-derived
(`identifiers.derive_order_id`), the clock is `SimulatedClock`, the bus is synchronous,
`resequence_event_list` imposes a total order, and `ReplayFeed` defends the ordering
invariant at consumption time. `tests/harness/test_backtest_parity_no_cache.py` builds the
real bootstrap → `run_backtest()` path twice over an identical synthetic tape and asserts
`compute_parity_hash(orch1) == compute_parity_hash(orch2)` — **re-ran it: passed.**

**Environment dependence — resolved since the prior audit:**

- `PYTHONHASHSEED` is now warned pre-run (`_warn_if_unpinned_hash_seed`,
  `backtest_runner.py:522-539`, called from both `run_backtest_api:865` and
  `main_cache_replay:980`) and echoed into the report's Parity block
  (`backtest_report.py:619`). Confirmed live in my hand-verification run: `hash_seed  0`
  when invoked with `PYTHONHASHSEED=0`. This is a backstop/observability fix, not
  enforcement — the harness does not itself set or re-exec with the pinned value, so an
  operator who ignores the warning still gets an unpinned run, but it is no longer silent.
- `data_version` is now content-bound via `cache_data_version()` (per-day event counts +
  ingestion health, `backtest_report.py:645-665`), preferred over the label-only
  `live_data_version()` fallback whenever `day_sources` is non-empty
  (`backtest_runner.py:814-821`). This closes the previously-reported collision where two
  different tapes for the same symbol/date produced the same `artifact_id`. It is still
  not a full byte-hash of the cache (explicitly documented as such, `:655-658`) — a
  re-ingested tape with identical event counts and `HEALTHY` status for every day would
  still collide. Accepted, documented tradeoff — not re-filed as a fresh finding.
- `code_version()` (`:696-706`) folds the HEAD git SHA into `artifact_id` and the printed
  report. Confirmed live: `code_version   0.1.0+929e9fb67f1d`, matching this checkout's
  actual `git rev-parse HEAD` short form. **New gap (P2):** it reads only `.git/HEAD` (via
  a committed-ref walk, no subprocess) and has no dirty-tree check — a locally modified
  engine still reports the last-committed SHA. Low urgency (operator backtests are
  normally run from a clean checkout) but cheap to close (`git diff --quiet` / mtime
  check, append `+dirty`).

**New environment-dependence finding (R-1, detailed in §4.6):** the `--edge-calibration
PATH` CLI flag (`backtest_runner.py:674-683`, `harness/backtest_cli.py:187-197`) is an
external, mutable file that changes the trade path
(`orchestrator.py:3175-3192`) but is invisible to every provenance hash. A run *with* the
flag and a run *without* it, given the same config + cache, are **not** guaranteed to be
reproducible from the artifact_id/report alone — you cannot tell after the fact which one
you're looking at. Within a single invocation, replay is still bit-identical (the module's
own docstring — `edge_calibration.py:24-27` — correctly states factors are fixed for the
duration of one replay); the gap is specifically in **provenance**, not in-run determinism.

**Unchanged limitations (documented, not re-filed):**

- Full report text is not bit-identical across runs/machines — only the Parity block is.
  The Latency section (`backtest_report.py:509-542`) prints wall-clock percentiles and a
  spike-origin timestamp; this is now explicitly called out in a code comment
  (`:329-334`), closing the prior audit's "document this" recommendation.
- `gc.disable()`/`gc.freeze()` and Windows `HIGH_PRIORITY_CLASS` elevation
  (`backtest_runner.py:747-775`) remain global process-level side effects during replay —
  they affect only latency numbers, not PnL/hashes, and are already scoped by a
  `try/finally`.
- Multi-day ranges skip the per-day RTH/session rebinding that single-day runs get
  (`backtest_cli.py:57-64`, explicitly documented as "not implemented yet" in the
  docstring) — a **Not shipped** design gap, not a bug; not filed as a fresh finding per
  the audit brief.

---

## 4. Report-fidelity audit (the core question)

### 4.1 Formula — confirmed correct, live

```
realized_pnl + unrealized_pnl        = gross_pnl      backtest_report.py:189-197
gross_pnl − Σ(ack.fees for ALL acks) = net_pnl         :198-199
starting_equity + net_pnl            = final_equity    :200
```

`Position.realized_pnl` is gross of fees by design and the half-spread is embedded in the
executed fill price, so subtracting fees once is correct — no double-count. This matches
the prior audit's conclusion; I re-derived it independently rather than trusting the prior
write-up.

### 4.2 Worked example — a real, self-built, non-cached run

The disk cache required for `test_app_20260326_backtest_baseline_from_disk_cache`'s own
built-in reconciliation assertions is not populated in this environment (confirmed: the
test skips — see §6, §8). Rather than stop at "the code looks right," I built a small
**real** backtest through the production path (`bootstrap.build_platform` →
`orchestrator.boot()` → `orchestrator.run_backtest()`, via `scripts/smoke_pipeline.py`'s
`_build()` harness, seed 42, no disk cache, no API key) and wrote a standalone script that
independently recomputes every reported P&L number **without calling any
`backtest_report` helper**, then diffs against the printed report text.

Printed report (`generate_report` output):

```
[P&L]
    Starting equity         $100,000.00
    Gross P&L               $7.55
      Realized              $0.00
      Unrealized            $7.55
    Fees                    $2.58
    Net P&L                 $4.97
    Final equity            $100,004.97
[TRADE ANALYSIS]
    Total fills             3
      Entry fills           3
      Closing fills         0
[PARITY]
    pnl_hash    (trades)    e7093be9949151d33a236b2b3e4c1d98ed01d300ff1a49066a78cd9e83e9c9fd
    code_version            0.1.0+929e9fb67f1d
    hash_seed               0
```

Independent hand recomputation (separate code, reading only `position_store`, the raw
`OrderAck` list, and `trade_journal`):

| Quantity | Hand-computed (full Decimal precision) | Printed (2dp display) | Match? |
|---|---|---|---|
| `realized_pnl` total | `0` | `$0.00` | ✓ |
| `unrealized_pnl` total | `7.5499999999999999999999989` | `$7.55` | ✓ (correctly rounds) |
| `gross_pnl` | `7.5499999999999999999999989` | `$7.55` | ✓ |
| `Σ(ack.fees)`, all 6 `OrderAck`s (3 FILLED, 3 non-FILLED) | `2.58` | `$2.58` | ✓ |
| `Σ(position.cumulative_fees)` | `2.58` | — | **== Σ(ack.fees)** ✓ |
| `Σ(TradeRecord.fees)` (3 journal records) | `2.58` | — | **== Σ(ack.fees)** ✓ |
| non-FILLED acks carrying a nonzero fee | `0` of 3 | — | (see caveat below) |
| `net_pnl = gross − fees` | `7.5499999999999999999999989 − 2.58 = 4.9699999999999999999999989` | `$4.97` | ✓ |
| `final_equity = 100000 + net_pnl` | `100004.9699999999999999999999989` | `$100,004.97` | ✓ |

Every printed number reconciles to the cent with an independently-recomputed value. The
`Σ(ack.fees) == Σ(position.cumulative_fees)` invariant — the exact assertion the prior
audit's fix added to the APP baseline test
(`test_backtest_app_baseline.py:240-252`) to close the cancel-fee/journal-fee divergence —
held in this freshly-generated run too.

**Caveat, stated plainly:** in this particular run, all 3 non-FILLED acks carry a **zero**
fee, so it does not independently stress-test the specific scenario the prior audit's fix
targeted (a CANCELLED/EXPIRED ack that *does* carry a nonzero fee, which the trade journal
has no record for). That scenario is covered by the APP baseline test's own assertion,
which I could not execute here (cache miss). I built and ran the strongest verification
available without the reference dataset; closing the residual gap requires either the
disk cache or a small committed fixture that deliberately includes a fee-bearing
cancel/expiry (see §8 recommendation).

### 4.3 Aggregation / bucketing — unchanged from prior audit, re-verified

- **Scratch vs. entry classification is now correct for `SCALE_UP`.** The prior audit's
  follow-up commit (`7188758`) added `SCALE_UP` to `_ENTRY_INTENTS`
  (`backtest_report.py:43`), fixing a real misclassification (a zero-PnL additive-entry
  fill was previously counted as a "scratch" break-even close). Confirmed present in the
  current tree.
- **`pnl_per_share` denominator remains documented, not changed** (`:236-238` code
  comment) — divides realized PnL by entry+exit share count (≈2× net position), a coarse
  metric, not a per-unit edge. Unchanged design tradeoff.
- **Multi-symbol running-NAV bias remains documented, not changed** (`:272-322`,
  incremental per-symbol dict rebuild) — immaterial for the single-symbol shipped
  baseline.
- **No daily-PnL bucket exists** (**Not shipped** — confirmed absent from `generate_report`
  by reading the full function body). The brief's session-edge / receipt-vs-session
  bucketing risk does not apply because the feature does not exist; not filed as a
  finding.
- **Rounding is display-only.** `_money()` formats at `:,.2f` for print; the arithmetic
  above shows the underlying Decimal carries ~25 digits of accumulated arithmetic noise
  from upstream mark-price/avg-price division (outside this audit's scope — owned by
  execution/position layers) that rounds cleanly at 2dp. No misleading-display issue.

### 4.4 TCA and Per-Alpha Cost Survival — new sections since last audit, same data source

`generate_report` gained a "Per-Alpha Cost Survival" section
(`backtest_report.py:581-595`, feature `af43d51`) since the prior harness audit. It is
sourced from the same `records` (`TradeRecord` list from the trade journal) used
throughout the rest of the report — no separate/divergent data path. In the hand-verified
run above, its `FLEET` row printed `net -2.58 (gross +0.00, fees 2.58)`, matching the
hand-computed `Σ(TradeRecord.fees) = 2.58` and `Σ(TradeRecord.realized_pnl) = 0` exactly.
Internal math of the TCA/cost-survival calculations themselves is out of scope (owned by
`audit_execution_fills.md` / forensics).

### 4.5 What "reconciliation" does *not* yet cover

The reconciliation contract is: report ⟷ `OrderAck`/`TradeRecord`/`Position` state within
**one** run. §4.6 (R-1) is a different, adjacent gap: the report can reconcile perfectly
with its own run's fills and still not tell you, after the fact, whether an external input
(edge-calibration factors) shaped which fills occurred at all.

### 4.6 R-1 — edge-calibration close-the-loop input has no provenance trace (P1)

New since the prior harness audit (`ef6557e`, predates but was not covered by the
06-27 report). Mechanism:

1. `--emit-edge-calibration PATH` (pass 1) writes per-alpha realized-vs-disclosed edge
   factors to a durable JSON (`EdgeCalibrationStore.save`, `edge_calibration.py:141-157`).
2. `--edge-calibration PATH` (pass 2, a later run) loads those factors
   (`backtest_runner.py:674-683`) and passes them into `build_platform(...,
   edge_calibration_factors=_edge_factors)` (`:692`).
3. `Orchestrator._edge_calibration_factors` (`orchestrator.py:741-742`) is read at the B4
   cost gate: `factor = self._edge_calibration_factors.get(signal.strategy_id, 1.0)`
   then `effective_edge_bps = signal.edge_estimate_bps * factor`
   (`orchestrator.py:3178-3179`) — this can flip a signal from "clears cost" to
   "suppressed," directly changing which orders are submitted and therefore the trade
   path, `pnl_hash`, and the printed P&L.
4. `compute_artifact_id`'s docstring (`backtest_report.py:767-780`) enumerates exactly
   five axes it hashes: `strategy_version`, `config_version`, `data_version`,
   `engine_version`, `code_version`. Calibration factors are not one of them, and are
   never passed into `generate_report` (signature: `backtest_report.py:139-152`) or
   printed in the Parity block (`:607-619`).
5. The *only* trace of calibration having been applied is a `print()` to the console
   (`backtest_runner.py:678-682`) — not part of the returned report string, so a caller
   who captures `generate_report`'s output alone (or greps the "BACKTEST REPORT" block out
   of a saved log) sees no indication it happened.

**Why this matters, concretely:** two runs with byte-identical config, cache, and CLI
invocation *except* a regenerated `--edge-calibration` file (e.g., re-run weeks later
after another session-reconcile job overwrote the calibration JSON) can produce a
different `pnl_hash` and different fills — while `artifact_id` stays identical, because
none of its five inputs changed. This is the same class of defect the prior audit's fix
closed for `data_version` (label-only vs content-bound), now reopened one layer up. It is
P1, not P0, because within any single run the factors are a fixed, deterministic input
(the module's own docstring is correct about that) — the gap is provenance/traceability
(Inv-13), not in-run determinism (Inv-5).

**Minimal fix (effort S):** hash the resolved, sorted `factors()` mapping (or reuse
`EdgeCalibrationStore`'s own `version` field plus a content hash) and fold it into
`compute_artifact_id` as a sixth axis; add an `edge_calibration_path` / `edge_calibration_hash`
line to the report's Parity block, defaulting to `"none"` when the flag is unused.

---

## 5. JSONL emit audit (Inv-13)

- **`FILL_JSONL` is lossless for its fields.** `fill_price` serialized as `str(Decimal)`
  with a `None`-guard (`backtest_jsonl.py:118-125`); `_emit_jsonl_line` uses
  `sort_keys=True` for stable ordering (`:106`). Confirmed by direct round-trip in
  `test_split_backtest_emit.py:47-61` (re-ran: passed) — a real `_emit_jsonl_line` call is
  captured via `redirect_stdout`, split, and the row compared field-for-field.
- **Float coercion in SIGNAL/INTENT/SIZEDIV/NETDIV streams remains a documented,
  intentional lossy path** (module docstring, `backtest_jsonl.py:1-9`) — unchanged since
  the prior audit's fix (which added the documentation, not a format change). Not a
  regression; explicitly not a source of truth for replay parity (the determinism suite
  hashes typed events, not these emits).
- **`split_backtest_emit.py` now correctly parses real emitter output (fixed).** Splits on
  the first single space, tolerates the legacy `PREFIX: {json}` colon form
  (`split_backtest_emit.py:25-47`), and warns (not silently exits 0) when zero rows parse
  (`:116-121`). `test_split_emit_matches_real_emitter_output` feeds an actual
  `_emit_jsonl_line`-produced line and round-trips it (re-ran: passed).
- **Prefix-map drift persists, with different members than before (P2, bug).**
  `_PREFIX_MAP` (`split_backtest_emit.py:11-22`):

  | Prefix in map | Actually emitted anywhere? |
  |---|---|
  | `SIGNAL_JSONL`, `FILL_JSONL`, `SNAP_JSONL`, `SENSOR_JSONL`, `HTICK_JSONL`, `HAZARD_JSONL`, `XSECT_JSONL`, `INTENT_JSONL` | Yes — via `backtest_jsonl.py` emitters |
  | `ORDER_ACK_JSONL`, `TIMING_JSONL` | **No** — confirmed by repo-wide grep: these two strings appear only as `_PREFIX_MAP` keys. `run_paper.py`'s `PaperSessionRecorder` writes `order_acks.jsonl` / `timing.jsonl` **directly to disk** (`paper_session_recorder.py:127-139`), never through `_emit_jsonl_line`/stdout, so this splitter can never receive them from any real code path today. |
  | `SIZEDIV_JSONL`, `NETDIV_JSONL`, `HAZARD_EXIT_JSONL` | **Emitted, but missing from the map** — confirmed at `backtest_jsonl.py:61` (`SIZEDIV_JSONL`), `:90` (`NETDIV_JSONL`), `:271` (`HAZARD_EXIT_JSONL`). Falls through to `f"{prefix.lower()}.jsonl"` (`split_backtest_emit.py:70`) → files named e.g. `sizediv_jsonl.jsonl` (redundant double "jsonl") instead of a curated name like `size_divergence.jsonl`. |

  **Impact:** no data loss (the fallback naming still writes every row), but the map is
  demonstrably stale against the current emitter set, and any future consumer that reads
  by the curated filename (as `compare_paper_backtest.py` does for `fills.jsonl` /
  `order_acks.jsonl`) would silently miss the divergence-stream files under their odd
  names. Not covered by any test — `test_split_backtest_emit.py` only exercises
  `SIGNAL_JSONL` and `FILL_JSONL`.

---

## 6. CLI contract audit

### 6.1 Exit codes — verified empirically, not just by reading code

I ran the actual entry points (not just tests) with `PYTHONHASHSEED=0`:

| Scenario | Command | Observed exit | Message |
|---|---|---|---|
| Missing config file | `run_backtest.py --config /tmp/does_not_exist.yaml --date 2026-01-01 --symbol AAPL` (with a fake API key set) | **1** | `ERROR: Config file not found: /tmp/does_not_exist.yaml` |
| Missing `MASSIVE_API_KEY` | `feelies backtest --config platform.yaml --date 2026-01-01 --symbol AAPL` (key unset) | **1** | `ERROR: MASSIVE_API_KEY not set...` |
| Misspelled config key, `--strict-config` | `feelies backtest --config <bad.yaml> ... --strict-config` | **1** | `ERROR: Invalid config: ...: unrecognized config key(s) ['cost_stress_multipler'] — check for typos. (strict config loading is enabled...)` |
| Misspelled config key, no `--strict-config`, real ingestion attempted | same, flag omitted | **1** | Config loads with a warning (not shown to exit code), run proceeds and fails later at network/ingestion (sandboxed here) → `ERROR: Ingestion failed: DataIntegrityError(...)` |

No path returned 0 on an injected failure. This corroborates and extends the prior audit's
(code-reading-only) table with live evidence. Cross-referenced against the source:

| Failure | Code | Citation |
|---|---|---|
| Config file missing | 1 | `backtest_runner.py:269-271` (`ConfigNotFoundError` → `None` → `:883-884`) |
| Invalid/misspelled config (`--strict-config`) | 1 | `backtest_cli.py:22-31` (`ConfigurationError`) → `backtest_runner.py:272-274` |
| No symbols resolved | 1 | `:887-891` |
| `MASSIVE_API_KEY` unset | 1 | `:878-880` |
| Ingestion raises | 1 | `:919-927` |
| Zero-event mix rejected | 1 | `_enforce_ingest_event_mix`, `:154-192` |
| Boot not READY | 1 | `:734-739` |
| Post-pipeline macro not READY | 1 | `:793-801` (new since prior audit) |
| Verification FAIL | 2 | `:855-860` (`0 if all_passed else 2`) |
| Pipeline integrity exception | re-raised → nonzero (uncaught traceback) | `:776-786` (no `except`) — P2 rough edge, not a contract violation |
| Bad subcommand / no handler | 1 | `cli/main.py:104-107` |

Two rough edges remain, both P2 (UX, not correctness):

- **Integrity failure surfaces as a raw traceback**, not a clean message+code. Exit code
  is still correctly nonzero (Python default `1`).
- **No report is printed for a DEGRADED-ending run** — the explicit gate at `:793-801`
  returns before Phase 6 (report generation). Intentional (a DEGRADED run's numbers
  shouldn't be trusted) but leaves an operator with only the one stderr line to triage.

### 6.2 Config-key strictness — fixed for backtest, gap reopened for paper (P1)

`_check_yaml_keys_and_types` (`platform_config.py:1679-1744`) is unchanged in mechanism
from the prior audit's fix: unknown keys **warn** by default
(`:1713-1718`) and **raise** `ConfigurationError` when `strict=True`
(`:1707-1712`). `PlatformConfig.from_yaml(..., strict=True)` is wired to
`--strict-config` on the **backtest** CLI (`backtest_cli.py:163-170`,
`backtest_runner.py:266-268`) and is directly tested
(`test_platform_config.py:242-257`, both the warn-and-keep-default and the
raise-under-strict paths — re-ran: both passed) and empirically confirmed live in §6.1.

**Gap: `scripts/run_paper.py` never received this treatment.** Its argument parser
(`run_paper.py:71-119`) has no `--strict-config` flag, and its
`load_platform_config(args.config)` call (`:192`) passes no `strict=` argument (default
`False`, unconditionally). A misspelled risk/sizing key in a PAPER-mode config — the mode
that connects to a real IB Gateway and submits orders — can only ever log a WARNING; there
is no way to make it fail closed, unlike the backtest path. This is the same defect class
the prior audit rated P1 for backtest, now present, unaddressed, on the higher-stakes
entry point. **Fix (effort S):** add `add_common_backtest_arguments`'s `--strict-config`
flag (or a standalone equivalent) to `run_paper.py`'s parser and thread
`strict=args.strict_config` into its `load_platform_config` call.

### 6.3 Arg parsing / `--json` stability

`cli/main.py:80` still selects the `backtest` subtree via `argv[0] == "backtest"` — lazy
registration to keep `feelies promote` free of the `ib`-extra-requiring harness import
(verified live: `tests/cli/test_cli_import_isolation.py`, 3/3 passed, confirms `feelies
promote` never imports `feelies.cli.backtest` / `feelies.bootstrap` / `feelies.harness.*`).
No global flags exist on the top-level parser today, so the "a global flag before the
subcommand would route to the placeholder" risk noted previously remains latent/inapplicable
(P2, unchanged). `--json` output is stable where present
(`compare_paper_backtest.py:115-116`, `sort_keys=True`).

---

## 7. Operator-scripts safety audit

| Script | Mutating? | Guarded? | Finding |
|---|---|---|---|
| `rebaseline_parity_hashes.py` | No (prints only) | n/a | **Safe**, unchanged. Writes nothing (`:86-96`); `os.chdir` side effect on import (`:24`), minor. |
| `record_perf_baseline.py` | Yes (host blob) | **Yes** | Refuses to record from a failing perf run (`:92-97`, raises `SystemExit`); requires `CI_BENCHMARK=1`. No confirm prompt but well-gated, unchanged. |
| `record_paper_perf_baseline.py` | Yes (host blob, `paper_rth` key) | **Weak (P2, unchanged from "partial")** | Only checks `timing.jsonl` exists and parses (`:27-47`); no check that the run *passed* or was representative, unlike its sibling. Merges unconditionally into the shared `v02_baseline.json` (`:66-72`). |
| `generate_bt12_fixtures.py` | Yes (committed fixtures) | **Yes (fixed)** | `--force` / `--dry-run` guard (`:38-63`) refuses to clobber existing fixtures without explicit intent — confirmed present and matches the prior audit's fix description. |
| `run_paper.py` | Side-effecting (real orders via IB paper account) | **Yes, mostly** | `--max-runtime-s` → `threading.Timer` halt (`:246-264`); SIGINT handler (`:223-234`, only on main thread); `finally` teardown in a fixed order — `shutdown()` → `live_feed.stop()` → `ib_connection.disconnect_and_stop()` → recorder flush (`:270-288`), each independently try/excepted so one failure doesn't skip the rest; mode-guarded to `PAPER` (`:196-201`). Verified live by `tests/scripts/test_run_paper.py::TestRunPaperTeardownOrder` (re-ran: passed, asserts `shutdown` index < `feed.stop`/`ib.disconnect` index). **Gaps:** no `--strict-config` (§6.2, P1); `session_start_ns`/`session_end_ns` as `float` not `int` (`:140,173`, P2). |
| `run_paper_soak.py` | Spawns `run_paper.py` | **Yes** | Passes `--max-runtime-s=duration`; `finally` terminates + waits on the child (`:56-59`, `timeout=60`). Unchanged, sound. |
| `compare_paper_backtest.py` | No (read-only report) | n/a | **Fixed.** No longer fabricates a 1.0 backtest fill-rate; explicitly lists unavailable metrics (`:70-76`) instead of hardcoding placeholder constants; `promotion_grade` is hardcoded `False` (`:86`) — a deliberate, permanent "not ready for promotion decisions" flag given the documented incompleteness (honesty note, `:41-49`), not a bug. `comparison_confidence` is capped at `"LOW"`/`"INSUFFICIENT"` (`:82`), never higher — consistent with the same honesty stance. |
| `smoke_pipeline.py` | No | n/a | **Fixed and re-verified.** Ran it: exit 0, `RESULT: ALL STAGES PASS`, determinism check passed (two in-process replays hash-identical). The `regime_gate.hysteresis` dead-margin block is gone; `kyle_lambda_60s` is version `2.0.0` — confirmed by direct grep, matching the prior audit's fix description. |

No P0 "ungated baseline-mutating script" found — every script that mutates committed or
shared state either writes nothing, refuses on failure, or requires an explicit
`--force`/`--dry-run`. `record_paper_perf_baseline.py`'s weaker guard is real but does not
rise to "ungated" (it still requires deliberate invocation with specific `--run-dir`/
`--host-label` arguments), so it stays P2.

---

## 8. Test gap matrix

| Invariant / property | Covered | Partial | Missing | Evidence |
|---|---|---|---|---|
| PnL formula gross−fees correct | ✓ | | | Hand-verified live in this audit (§4.2) + `test_backtest_app_baseline.py` (cache-gated) |
| `Σ(ack.fees) == Σ(cumulative_fees)` | ✓ | | | `test_backtest_app_baseline.py:246-252` (cache-gated, not run here) **and** independently reproduced in a fresh non-cached run in this audit |
| Trade-path bit-identity, synthetic dataset, no cache | ✓ | | | `test_backtest_parity_no_cache.py` — re-ran: passed |
| Trade-path bit-identity, real APP/2026-03-26 dataset | | ✓ | | Functional test **skips** on cache miss (reproduced live: "1 skipped") — mitigated but not closed by the synthetic-dataset test above |
| Config snapshot / contract hash | ✓ | | | `test_app_baseline_config_contract_hash` (data-free, re-ran: passed) |
| Unknown config key rejected (backtest, `--strict-config`) | ✓ | | | `test_platform_config.py:250-257` — re-ran: passed; also verified live via CLI (§6.1) |
| Unknown config key rejected (**paper**) | | | ✗ | No `--strict-config` exists on `run_paper.py` at all (R-2, §6.2) |
| Loose scalar type rejected | ✓ | | | `_check_yaml_keys_and_types` (`:1725-1743`) |
| Exit code nonzero on bad config / boot / ingest | ✓ | | | `tests/harness`, `tests/cli/test_backtest_cli.py` (58 passed) + live CLI runs (§6.1) |
| Exit 2 on verification fail | ✓ | | | `backtest_runner.py:855-860` |
| Exit nonzero on integrity exception, with a clean message | | ✓ | | Nonzero confirmed; message is an uncaught traceback, not tested for cleanliness |
| JSONL fill round-trip (`FILL_JSONL`) | ✓ | | | `test_split_emit_matches_real_emitter_output` — re-ran: passed |
| JSONL prefix-map completeness (`SIZEDIV`/`NETDIV`/`HAZARD_EXIT`) | | | ✗ | Not covered by any test; confirmed missing by direct code inspection (§5) |
| `edge_calibration` reflected in `artifact_id`/report | | | ✗ | No test asserts `artifact_id` changes (or is documented not to) when `--edge-calibration` is applied (R-1, §4.6) |
| `compare_paper_backtest` correctness | | ✓ | | Honest-metrics behavior is now what the code does; no dedicated unit test of `compare_runs()` found under `tests/scripts/` |
| `PYTHONHASHSEED` enforced/echoed | ✓ (echoed) | | | Warned + echoed (`:522-539`, `:619`); confirmed live (`hash_seed  0`); not *enforced* (accepted, documented backstop-only design) |
| `smoke_pipeline.py` runs green | ✓ | | | Re-ran: exit 0, all stages pass |
| `record_paper_perf_baseline.py` refuses a bad run | | | ✗ | No pass/fail gate exists to test (§7) |
| `code_version()` dirty-tree detection | | | ✗ | Feature doesn't exist (§3) |

**Minimal new tests (specs only):**

1. `test_artifact_id_changes_with_edge_calibration` — build two otherwise-identical runs,
   one with `--edge-calibration` pointed at a factors file with a non-1.0 factor, one
   without; assert either (a) `artifact_id` differs, or (b) if left unchanged by design,
   assert the report prints an explicit calibration marker. Closes R-1 (§4.6).
2. `test_run_paper_rejects_unknown_config_key_when_strict` — mirror
   `test_unknown_key_strict_raises` through `run_paper.py`'s own arg parser once
   `--strict-config` is added. Closes R-2 (§6.2).
3. `test_split_emit_prefix_map_covers_all_backtest_jsonl_prefixes` — introspect
   `backtest_jsonl.__all__`'s emitter prefixes (or a small hardcoded list) and assert every
   one has a `_PREFIX_MAP` entry; assert every `_PREFIX_MAP` entry is actually emitted
   somewhere. Closes the drift in §5.
4. `test_record_paper_perf_baseline_refuses_incomplete_run` — feed a `run-dir` with a
   truncated/degraded `timing.jsonl` (e.g., zero `tick_process` rows past warm-up, or a
   sentinel "run did not complete" marker) and assert the script refuses to merge, mirroring
   `record_perf_baseline.py`'s pattern.
5. `test_app_baseline_from_committed_fixture` (carried over from the prior audit,
   still open) — a tiny committed-fixture deterministic backtest that pins `pnl_hash`
   without the disk cache, so the real reference dataset's trade path is locked in clean
   CI too.

---

## 9. Prioritized backlog

**P0** — none. No report failed to reconcile with its fills (§4 — verified live, not just
read), no run was shown non-reproducible for identical inputs (§3), no CLI path returned 0
on an injected failure (§6.1 — verified live), no baseline-mutating script is ungated
(§7), and `FILL_JSONL` (the only stream anything currently depends on for fidelity) is
lossless.

**P1**

| # | Component | `file:line` | One-line fix | Impact | Effort |
|---|---|---|---|---|---|
| R-1 | edge-calibration provenance | `backtest_runner.py:673-693`, `orchestrator.py:3175-3192`, `backtest_report.py:759-802,139-152,601-619` | Hash `EdgeCalibrationStore(path).factors()` into `compute_artifact_id` as a sixth axis; print it in the Parity block | Closes an `artifact_id` collision vector for a live trade-path input (Inv-13) | S |
| R-2 | `run_paper.py` config strictness | `scripts/run_paper.py:71-119,192` | Add `--strict-config` (mirror `backtest_cli.py:163-170`) and thread `strict=` into `load_platform_config` | Gives PAPER-mode (live-adjacent orders) the same fail-closed protection backtest already has | S |

**P2**

| # | Component | `file:line` | Fix | Effort |
|---|---|---|---|---|
| 3 | JSONL prefix-map drift | `scripts/split_backtest_emit.py:11-22` vs `backtest_jsonl.py:61,90,271` | Add `SIZEDIV_JSONL`/`NETDIV_JSONL`/`HAZARD_EXIT_JSONL`; drop or annotate the never-emitted `ORDER_ACK_JSONL`/`TIMING_JSONL` | S |
| 4 | paper perf baseline guard | `scripts/record_paper_perf_baseline.py:50-74` vs `record_perf_baseline.py:92-97` | Add a pass/fail or minimum-sample-size gate before merging into the shared baseline | S |
| 5 | session timestamp precision | `scripts/run_paper.py:140,173` | `int(datetime.now(UTC).timestamp() * 1_000_000_000)` | S |
| 6 | code provenance dirty-tree | `backtest_report.py:696-706` | Append `+dirty` when `git diff --quiet` (or mtime-based check) fails | S |
| 7 | integrity-failure UX | `backtest_runner.py:776-786` | Wrap `orchestrator.run_backtest()` in a narrow `except Exception` that prints a one-line summary before re-raising (or exiting with the same nonzero code) | S |
| 8 | DEGRADED-run diagnostics | `backtest_runner.py:793-801` | Consider printing a minimal (non-Parity, clearly-labeled "PARTIAL/UNTRUSTED") diagnostic before returning, to aid triage | S/M |
| 9 | real-dataset CI parity | `tests/acceptance/test_backtest_app_baseline.py:166-185` | Small committed-fixture backtest pinning `pnl_hash` without the disk cache (carried over, still open) | M |
| 10 | `--strict-config` default | `backtest_cli.py:163-170` | Consider flipping the default to strict in a coordinated release, now that the escape hatch is proven | S (policy decision, not code) |

---

*Read-only audit. No production code, baseline, config, or ledger was modified. All test
commands and CLI invocations in §Method/§6.1 were run for evidence only; the one temp
config file and temp output files created for CLI exit-code verification were deleted
after use. The hand-verification script for §4.2 lives at
`/tmp/claude-0/.../scratchpad/hand_verify_report.py` (session-scoped scratch directory,
not part of the repository).*
