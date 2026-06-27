# Harness / CLI / Scripts Reproducibility & Fidelity Audit — 2026-06-27

**Scope:** `src/feelies/harness/` (runner, report, jsonl, cli glue, prep touchpoint),
`src/feelies/cli/` (backtest path), `scripts/` (operator + baseline-mutating), and the
matching test surface. Read-only pass — no production code, baseline, or parity hash was
modified.

**Method:** read the four context docs (`backtest-engine` / `research-workflow` SKILLs,
`AGENTS.md`, `platform-invariants.mdc` Inv-5/Inv-13); traced the run-artifact path;
recomputed the report PnL formula against the position/journal model by hand; diffed the
emitter format against the splitter parser; checked exit-code and config-key contracts;
audited the baseline-mutating scripts for guardrails. Ran (read-only):
`pytest tests/harness/ tests/cli/test_backtest_cli.py tests/scripts/` → **51 passed**;
`pytest tests/acceptance/test_backtest_app_baseline.py test_backtest_app_config_keys.py`
→ **13 passed, 1 skipped** (cache miss); `python scripts/smoke_pipeline.py` → **failed**
(see E-4); `uv sync --all-extras` was required to import `bootstrap` at all (see E-5).

Severity legend matches the task brief: **P0** report doesn't reconcile / run not
reproducible / CLI exits 0 on error / baseline-mutating script ungated / lossy JSONL;
**P1** config keys silently ignored / fee-population drift / paper-compare broken; **P2**
ergonomics, richer provenance, hardening. Each finding tags **[bug] / [limitation] /
[design]**.

---

## 0. Resolution (follow-up commit)

The P1/P2 backlog below was addressed in a follow-up. Status per item:

| Item | Status | Change |
|---|---|---|
| P1-1 split emit | **Fixed** | `split_backtest_emit.py:_parse_line` now splits on the first space (tolerates legacy colon); test feeds real emitter output + a round-trip test |
| P1-2 paper-compare | **Fixed** | `compare_paper_backtest.py` no longer fabricates a 1.0 fill-rate or hardcoded metrics; reports real paper rates + counts, marks divergence metrics `unavailable`, flags `promotion_grade: false` |
| P1-3 report fees | **Fixed** | Baseline test reconciles to `sum(ack.fees)` and asserts `== Σ cumulative_fees` |
| P1-4 config strictness | **Fixed (opt-in)** | `from_yaml(..., strict=True)` raises on unknown keys; `--strict-config` flag wired; default warn-behaviour preserved (the deliberate, separately-tested forward-compat path) |
| P1-5 PYTHONHASHSEED | **Fixed** | Runner warns when unpinned; report Parity block echoes `hash_seed` |
| P1-6 data provenance | **Fixed** | `cache_data_version()` binds `data_version` to per-day event counts + health; used when day-sources present |
| P1-7 code provenance | **Fixed** | `code_version()` folds the HEAD git SHA into `artifact_id` and the report |
| P1-8 smoke | **Fixed** | Removed dead `hysteresis` margins and bumped the stale `kyle_lambda_60s` version; `smoke_pipeline.py` runs green |
| P2-9 scripts import | **Fixed** | `bootstrap` lazy-imports the paper backend; backtest scripts import without the `ib` extra |
| P2-10 fixtures guard | **Fixed** | `generate_bt12_fixtures.py` gains `--force` / `--dry-run`; refuses to clobber without them |
| P2-11/12 report docs | **Fixed** | Latency-block non-determinism documented; scratch trades counted explicitly; `pnl_per_share` denominator documented |
| P2-13 macro gate | **Fixed** | Explicit `macro == READY` gate after the pipeline (exit 1 otherwise) |
| P2-14 CI parity | **Fixed** | New `tests/harness/test_backtest_parity_no_cache.py` pins trade-path bit-identity without the disk cache |
| P2-15 jsonl precision | **Documented** | Float coercion flagged lossy in the emitter docstring (format is test-pinned, so not changed) |

Pre-existing, out-of-scope failures on this branch (unrelated to these changes; verified failing with the changes reverted): 5 `tests/kernel/test_orchestrator.py` `STOP_EXIT`-reason tests and the `platform_config.py` stale wall-clock-allowlist entry.

---

## 1. Executive summary

1. **[P1, bug] `scripts/split_backtest_emit.py` silently drops every real emitter line.**
   The emitters write `PREFIX {json}` (single space — `backtest_jsonl.py:97`); the splitter
   parses on `": "` and requires `prefix.endswith("_JSONL")` (`split_backtest_emit.py:27-29`).
   Real output partitions at the first `": "` *inside* the JSON, so the prefix check fails
   and the line is skipped. The unit test feeds the wrong `PREFIX: {json}` colon format
   (`test_split_backtest_emit.py:26-27`) and passes — false confidence. `main()` returns 0
   on an empty run-dir.
2. **[P1, bug] `scripts/compare_paper_backtest.py` is a near-stub that feeds promotion.**
   `backtest_fill_rate = len(fills)/max(len(fills),1)` is identically `1.0`
   (`compare_paper_backtest.py:58`), and `fills.jsonl` is FILLED-only while paper uses
   all `order_acks` — not apples-to-apples. `slippage_residual_bps`, `latency_ks_p`,
   `pnl_compression_ratio`, `anomalous_event_count` are hardcoded constants (lines 72-76).
3. **[P1, limitation] Report Net P&L and the journal-based reconciliation use different fee
   populations.** The report sums `OrderAck.fees` over **all** acks (`backtest_report.py:191`),
   which includes CANCELLED/EXPIRED cancel fees debited at `orchestrator.py:5530-5540`. The
   trade journal has no record for those non-fill acks, so the baseline test's "mirror"
   (`test_backtest_app_baseline.py:127-137`, journal fees only) diverges from the printed
   number by exactly the cancel fees. Report reconciles with fills **only when no non-fill
   ack carries a fee**.
4. **[P1, limitation] The operator backtest CLI never pins or echoes `PYTHONHASHSEED`.**
   Determinism is contractually pinned at `PYTHONHASHSEED=0` (`conftest.py:36-39`,
   `docs/three_layer_architecture.md:1475`), but that guard is test-only; `run_backtest_api`
   / `main` (`backtest_runner.py:921-924`, `815-918`) set nothing. Cross-machine
   reproducibility of any frozenset-ordered path is unenforced at the harness boundary
   (cross-ref kernel-P1, determinism-P1).
5. **[P1, limitation] `data_version` does not bind to the actual input bytes.** Both API and
   cache-replay paths pass `live_data_version(symbols, date_range)` (`backtest_runner.py:773`,
   `backtest_report.py:603-614`) = SHA of `(symbols, date_range)` only. Two different tapes
   for the same symbol+date collide → identical `artifact_id`. Inv-13 provenance gap.
6. **[P1, limitation] `ENGINE_VERSION` is a hand-bumped string, not the code SHA.**
   `ENGINE_VERSION = "0.1.0"` (`backtest_report.py:664`) feeds `artifact_id`. A fill-semantics
   change that forgets to bump it yields an identical `artifact_id` for different code.
7. **[P1, bug/limitation] Misspelled config keys are warned, not rejected.**
   `_check_yaml_keys_and_types` logs a WARNING and proceeds — the docstring literally says
   "a misspelled key silently keeps the default" (`platform_config.py:1697-1704`). Loose
   *scalar types* DO raise (1711-1729), but unknown keys silently no-op; the run still
   exits 0. `test_backtest_app_config_keys.py` does not cover unknown-key rejection.
8. **[P1, bug] `scripts/smoke_pipeline.py` is broken on `main`.** Its embedded smoke alpha
   YAML declares a `regime_gate.hysteresis` block whose margins are unreferenced; the loader
   now rejects this as dead config (`AlphaLoadError`) before any stage runs. AGENTS.md
   advertises it as the no-API-key smoke.
9. **[P2, design] `bootstrap` eagerly imports the IB stack.** `bootstrap.py:119` →
   `paper_backend` → `broker.ib` → `ibapi`, unconditionally, so *every* script entry point
   (`run_backtest.py`, `smoke_pipeline.py`) needs the optional `ib` extra even for a pure
   backtest. `cli/main.py` deliberately lazy-imports `backtest` to avoid exactly this for
   `feelies promote`; the scripts get no such treatment.
10. **[limitation] The full report text is NOT bit-identical across runs/machines** — only
    the parity-hash block is. The Latency section prints wall-clock `avg/p95/p99/max
    tick-to-decision` and a spike-origin line (`backtest_report.py:486-518`). Inv-5's
    "identical report" holds for `pnl_hash/config_hash/parity_hash/artifact_id`, not the
    rendered string. GC is disabled and (on Windows) process priority elevated during replay
    (`backtest_runner.py:724-758`) — these touch only the latency numbers.
11. **[limitation] Trade-path reproducibility is unverified in clean CI.** The APP baseline
    test is `@pytest.mark.functional` and **skips on cache miss** (`test_backtest_app_baseline.py:172-179`;
    observed "1 skipped"); the in-process determinism check calls `compute_parity_hash`
    twice on the *same* orchestrator (line 231-232), which is trivially equal. Only the
    data-free `config_contract_hash` is locked without the disk cache.
12. **[good] Core PnL accounting is correct.** `realized_pnl` is gross of fees by design
    (`position_store.py:35-45`); the half-spread lives in the fill price; `net_pnl =
    gross_pnl - fees` (`backtest_report.py:189-192`) is the right formula and does not
    double-count.
13. **[good] Baseline-mutating `rebaseline_parity_hashes.py` is safe** — it only prints
    candidate constants to stdout and writes nothing (`scripts/rebaseline_parity_hashes.py:86-92`);
    `record_perf_baseline.py` refuses to record from a failing perf run (`:92-97`).
14. **[good] Exit-code spine is sound** for the failures it models: bad/missing config → 1,
    boot/ingest failure → 1, verification failure → 2, pipeline integrity exception → re-raised
    nonzero. The gap is that an integrity failure surfaces as an uncaught traceback, and a
    DEGRADED post-run is caught only indirectly by verification check #6.
15. **[P2, bug] `generate_bt12_fixtures.py` overwrites committed fixtures with no guard** —
    no `--force`/confirmation/dry-run (`scripts/generate_bt12_fixtures.py:65-69`); mitigated
    only by deterministic seeds + validation gates (idempotent unless params/code change).

---

## 2. Run-artifact inventory

What a backtest run (`run_backtest_api` → `_run_backtest_phases_2_7`) produces, and what
carries provenance.

| Artifact | Where | Provenance captured? | Notes |
|---|---|---|---|
| Operator text report (stdout) | `generate_report` `backtest_report.py:131-597` | Partial | Parity block reproducible; Latency block wall-clock (not reproducible) |
| `pnl_hash` (trade sequence) | `compute_parity_hash` `:617-640` | Yes | SHA-256 over ordered `TradeRecord` canonical JSON |
| `config_hash` | `compute_config_hash` `:643-649` = `config.snapshot().checksum` | Yes | Captures resolved PlatformConfig + ingest-health rows |
| `parity_hash` (combined) | `:652-658` | Yes | `SHA(pnl_hash:config_hash)` |
| `artifact_id` | `compute_artifact_id` `:667-706` | Partial | strategy=`alpha@manifest.version`, config.version, data_version, ENGINE_VERSION |
| `engine_version` | `ENGINE_VERSION="0.1.0"` `:664` | Weak | Hand-bumped string, **not** git SHA |
| `data_version` | `live_data_version` `:603-614` | Weak | `(symbols,date_range)` hash, **not** bytes |
| FILL_JSONL etc. (stdout) | `backtest_jsonl.py` (opt-in flags) | Field-level | `fill_price` as `str(Decimal)`; Signal/Intent streams float-coerce Decimals |
| Verification table | `run_verification` `:709-763` + `print_verification` runner `:491-508` | n/a | 7 checks → exit 2 on any FAIL |
| Disk cache (JSONL.gz) | `DiskEventCache` (ingest path, owned elsewhere) | Yes | per-day manifest incl. `ingestion_health` |
| Code/git SHA | — | **No** | Not recorded anywhere in the run output |
| Host / env (`PYTHONHASHSEED`, locale, thread count) | — | **No** | Not echoed into the report |

Gaps vs Inv-13: the run captures config + alpha-manifest versions, but **not** the code SHA,
the actual data bytes, or the host environment that governs determinism.

---

## 3. Reproducibility audit (Inv-5)

**Reproducible by construction:** order IDs are SHA-derived (`identifiers.derive_order_id`),
the clock is `SimulatedClock`, the bus is synchronous, and `resequence_event_list` imposes a
total order. The four provenance hashes are pure functions of trades + config and were
observed stable across the in-process double-call in the baseline test.

**Environment dependence found:**

- **`PYTHONHASHSEED` unpinned at the CLI boundary (P1).** The only guard is `conftest.py`,
  which runs for pytest, not for `python scripts/run_backtest.py` or `feelies backtest`. The
  runner's entrypoints (`backtest_runner.py:921-924`, `815`) do not set, re-exec with, or
  even print the seed. Any frozenset/`set`-ordered code in the tick path is therefore
  unprotected for operator runs. The kernel audit (kernel-P1) reports the tick-path
  set-order dependency was removed, making this defence-in-depth rather than a live
  miscompute — but the harness still ships zero backstop and no provenance echo. **Minimal
  fix:** assert/echo `os.environ.get("PYTHONHASHSEED")` in `run_backtest_api` and stamp it
  into the report header.
- **Full report text is not bit-identical (limitation/design).** `backtest_report.py:486-518`
  renders wall-clock latency percentiles and the spike-origin timestamp; two runs of the
  same config+cache differ in those lines. This is observability, not a run-output defect —
  but it means "identical report" (Inv-5 literal) is only true of the parity block. **Fix:**
  document the boundary, or split a deterministic "artifact report" from the timing view.
- **GC/priority side effects (limitation).** `backtest_runner.py:724-758` calls
  `gc.disable()/freeze()` and elevates Windows priority (`:738-746`). These are global
  process mutations affecting only latency numbers; they don't change PnL/hashes, but they
  are an undeclared environmental side effect of "just running a backtest."

**Provenance reconstructability (A2/A3):** config is fully captured (`config_hash`), and
alpha code is pinned at `alpha@manifest.version` in `artifact_id`. **Not** captured: the
engine git SHA (only the hand-bumped `ENGINE_VERSION`) and the actual input bytes
(`data_version` is a `(symbols,date_range)` label). A run is reconstructable from config +
cache *if* the cache for that symbol/date is unchanged, but nothing in the artifact detects
that the cache bytes changed underneath the same label.

---

## 4. Report-fidelity audit (the core question)

### 4.1 PnL formula — correct

```
realized + unrealized  = gross_pnl            backtest_report.py:181-189
gross_pnl - sum(ack.fees) = net_pnl           backtest_report.py:190-192
start_equity + net_pnl  = final_equity        :193
```

`Position.realized_pnl` is **gross** of fees and embeds the half-spread in the executed
price (`position_store.py:32-58`). So subtracting fees once is correct and there is **no
double-count** — this is the central good-news result.

### 4.2 Fee-population divergence (P1, worked example)

The report sums fees over **all** acks (`backtest_report.py:191`):
`fees = sum(a.fees for a in acks)`. But `orchestrator.py:5530-5540` debits cancel/expiry
fees from positions for **non-fill** acks (CANCELLED/EXPIRED) that produce **no
`TradeRecord`**. The journal therefore omits those fees.

Worked case — 1 entry fill, 1 exit fill ($0.01 fee each), 1 EXPIRED passive order charged a
$0.01 cancel fee; gross realized = $5.00:

| Path | gross | fees | net |
|---|---|---|---|
| Report (`sum(ack.fees)`, all 3 acks) | 5.00 | 0.03 | **4.97** |
| Baseline test `_net_pnl_from_orchestrator` (journal fees, 2 records) | 5.00 | 0.02 | **4.98** |

The report's $4.97 matches `Position.cumulative_fees` and the risk engine's NAV
(`_compute_current_equity`), so the **report is the truer NAV**; the baseline test
*understates* cost by the cancel fee while claiming to "Mirror `generate_report` net PnL"
(`test_backtest_app_baseline.py:128`). For APP/2026-03-26 the two coincide (no cancel fees),
which is why the locked $19.64 passes — but the contract "report reconciles with the fills
it summarizes" holds only when no non-fill ack carries a fee. **Fix:** reconcile the test to
`sum(ack.fees)` (or have the report sum fill+debited fees explicitly) and add an assertion
that `sum(ack.fees) == Σ position.cumulative_fees`.

### 4.3 Aggregation / bucketing observations

- **Scratch trades misclassified (P2).** `realized_pnl == 0` records are neither win nor loss
  (`backtest_report.py:204-214`) and fall into `entry_fills = total_fills - resolved_count`.
  A break-even *exit* is counted as an entry fill and excluded from `win_rate`.
- **`pnl_per_share` denominator (P2).** `realized_pnl / total_shares` where `total_shares`
  counts entry **and** exit fills (`:171`, `:220`) — divides realized PnL by ≈2× the traded
  position; a rough metric, not a per-unit edge.
- **Multi-symbol running NAV (P2).** The exposure and drawdown loops rebuild `current_equity`
  from per-symbol dicts populated incrementally in `pos_updates` order
  (`:263-305`); early iterations reflect a partial portfolio, so `max_exposure_pct` /
  `max_drawdown` can be biased on multi-symbol runs. Single-symbol (the shipped baseline)
  is unaffected.
- **Daily-PnL bucketing:** there is **no** per-session-date PnL bucket in `generate_report`
  — PnL is whole-run aggregate from the position store. The session-edge / receipt-vs-session
  bucketing risk called out in the brief does not apply because the feature is absent. If a
  daily-PnL table is added later, bucket by session date, not fill receipt time.
- **Rounding:** `_money` formats Decimals at `:,.2f` for **display only**
  (`:114-117`); stored values stay Decimal. No misleading-display issue.

---

## 5. JSONL emit audit (Inv-13)

- **Fills are lossless** for their fields: `fill_price` serialized as `str(Decimal(...))`
  with a None-guard (`backtest_jsonl.py:110-117`); `_emit_jsonl_line` uses `sort_keys=True`
  for stable ordering (`:97`).
- **Float coercion in non-fill streams (P2, limitation).** SIGNAL/INTENT/SIZEDIV/NETDIV
  emitters coerce Decimals to `float` (`:177-182`, `:237-241`, `:60-66`). Round-trip through
  these streams loses Decimal precision on `strength`, `edge_estimate_bps`, exposures,
  target USD. Acceptable for diagnostic streams, but they are **not** exact round-trips —
  do not treat them as a source of truth for replay parity (the determinism JSONL tests use
  the typed events, not these emits).
- **`split_backtest_emit.py` is incompatible with the emitter (P1, bug).** Detail in §1.1.
  The emitter writes `PREFIX {json}` (space, `:97`); the splitter parses `": "`
  (`split_backtest_emit.py:27-29`). Every real line is dropped; ordering/completeness are
  moot because nothing is written. The test encodes the wrong format
  (`test_split_backtest_emit.py:26`), so coverage is illusory. **Fix:** parse on the first
  single space and validate `prefix.endswith("_JSONL")`; update the test to feed real
  emitter output (`mod._emit_jsonl_line`-shaped lines).
- **Prefix map drift (P2).** `_PREFIX_MAP` lists `ORDER_ACK_JSONL` / `TIMING_JSONL` that the
  backtest never emits and omits `SIZEDIV_JSONL` / `NETDIV_JSONL` / `HAZARD_EXIT_JSONL` that
  it does — those fall to the `{prefix.lower()}.jsonl` default and won't match what
  `compare_paper_backtest.py` reads.

---

## 6. CLI contract audit

### 6.1 Exit codes — mostly sound

| Failure | Code | Citation |
|---|---|---|
| Config file missing | 1 | `backtest_runner.py:265` (`_load_backtest_config` → None → `:834`) |
| No symbols resolved | 1 | `:838-842` |
| `MASSIVE_API_KEY` unset | 1 | `:829-831` |
| Ingestion raises | 1 | `:876-878` |
| Zero-event mix rejected | 1 | `_enforce_ingest_event_mix` `:155-189` |
| Boot not READY | 1 | `:706-711` |
| Verification FAIL | 2 | `:807-808` (`0 if all_passed else 2`) |
| Pipeline integrity exception | re-raised → nonzero | `orchestrator.py:1509-1515` |
| Bad subcommand / no handler | 1 | `cli/main.py:104-107` |

No path was found that swallows an error and returns 0. Two rough edges:
- **Integrity failure surfaces as an uncaught traceback**, not a clean message+code —
  `run_backtest_api` has no try/except around `_run_backtest_phases_2_7`. Exit is nonzero
  (Python default 1) but operator-hostile.
- **No explicit post-run macro-state check.** After `run_backtest()` returns, a DEGRADED
  orchestrator is caught only because verification check #6 ("Macro state == READY",
  `backtest_report.py:749-751`) fails → exit 2. If verification were ever relaxed, a
  DEGRADED run could slip to exit 0. Add an explicit `assert macro == READY` gate.

### 6.2 Config-key strictness — silent no-op (P1)

`_check_yaml_keys_and_types` **warns** on unknown keys and continues
(`platform_config.py:1697-1704`); the docstring concedes "a misspelled key silently keeps
the default." A typo'd `signal_min_edge_cost_ratoi: 2.0` produces a buried WARNING and a run
that exits 0 with the default value. Scalar **type** mismatches do raise (`:1711-1729`), so
the half of the footgun that's covered is covered — but the typo half is not.
`test_backtest_app_config_keys.py` asserts only that *allowed* deltas load; it never asserts
that an *unknown* key is rejected. **Fix:** promote unknown-key handling to `ConfigurationError`
(or a `--strict-config` default), and add a `pytest.raises` test.

### 6.3 Arg parsing

`cli/main.py:80` selects the backtest subtree via `argv[0] == "backtest"`. Any global flag
before the subcommand would route to the no-handler placeholder (`:86-89`) → help + exit 1.
No global flags exist today, so this is latent (P2). `--json` is stable where present
(`compare_paper_backtest.py:98-99`, sorted keys).

---

## 7. Operator-scripts safety audit

| Script | Mutating? | Guarded? | Finding |
|---|---|---|---|
| `rebaseline_parity_hashes.py` | No (prints only) | n/a | **Safe.** Writes nothing; manual copy step (`:86-92`). Minor: `os.chdir` side effect (`:24`). |
| `record_perf_baseline.py` | Yes (host blob) | **Yes** | Refuses to record from a failing perf run (`:92-97`); needs `CI_BENCHMARK=1`. No confirm prompt but well-gated. |
| `record_paper_perf_baseline.py` | Yes | partial | Same shape as perf baseline (RTH-gated); low blast radius. |
| `generate_bt12_fixtures.py` | **Yes (committed fixtures)** | **Weak (P2)** | `write_text` with no `--force`/dry-run (`:65-69`). Deterministic seed + cpcv/dsr validation gates (`:51-64`) make it idempotent, but an accidental run silently regenerates acceptance fixtures. Add a confirmation/`--force`. |
| `run_paper.py` | Side-effecting (orders) | **Yes** | `--max-runtime-s` Timer→halt (`:246-264`), SIGINT handler (`:223-234`), teardown `finally` (`:270-288`). Mode-guarded to PAPER (`:196-201`). Minor: `session_start_ns` written as a **float** not int-ns (`:140`). |
| `run_paper_soak.py` | Spawns paper | **Yes** | Passes `--max-runtime-s=duration` and terminates the child on exit (`:60-64`). OK. |
| `compare_paper_backtest.py` | No | n/a | **Broken comparator (P1)** — see below; feeds promotion. |
| `smoke_pipeline.py` | No | n/a | **Broken on main (P1)** — see E-4. |

**E-1 (P1): `compare_paper_backtest.py` divergence math is wrong / placeholder.**
`backtest_fill_rate = len(backtest_fills)/max(len(backtest_fills),1)` ≡ 1.0
(`:58`) because `fills.jsonl` is FILLED-only; the paper side uses all `order_acks`
(`:53-57`, with a dead inner `else`). So `fill_rate_drift_pct` is structurally biased and
`comparison_confidence` caps at MEDIUM (`:63-65`). `slippage_residual_bps=0.0`,
`latency_ks_p=1.0`, `pnl_compression_ratio=1.0`, `anomalous_event_count=0` are hardcoded
(`:72-76`), so the only live signals are fill-rate-drift (broken) and rejection-rate. It
exits 3 on blocking alerts (`:108`) — capable of both false blocks and false all-clears.
Since the brief flags this as feeding promotion, treat it as P1 and gate any promotion use
behind a real implementation.

**E-4 (P1): `smoke_pipeline.py` fails before exercising the pipeline.** Observed:
`AlphaLoadError: ... regime_gate.hysteresis declares ['percentile_margin','posterior_margin']
but neither on_condition nor off_condition references any of them`. The embedded smoke YAML
(`scripts/smoke_pipeline.py:191-198`, `250-256`) predates the loader's dead-margin check.
The documented no-API-key smoke (AGENTS.md §Running services) is therefore non-functional.
**Fix:** reference the margins (e.g. `P(normal) > 0.5 + posterior_margin`) or drop the
`hysteresis` block.

**E-5 (P2): scripts can't import without the `ib` extra.** `bootstrap.py:119` eagerly imports
`paper_backend` → `broker.ib` → `ibapi`, so `smoke_pipeline.py` / `run_backtest.py` raise
`ModuleNotFoundError: ibapi` on a default `uv sync`. `cli/main.py` avoids this for `promote`
via lazy import; the scripts should either lazy-import the paper backend in `bootstrap` or
the docs should require `--all-extras`.

---

## 8. Test gap matrix

| Invariant / property | Covered | Partial | Missing | Evidence |
|---|---|---|---|---|
| PnL formula gross−fees correct | ✓ | | | `test_backtest_app_baseline.py` (when cache present) |
| Report Net P&L == report-printed formula | | ✓ | | Baseline mirrors *journal* fees, not `sum(ack.fees)` (§4.2) |
| `sum(ack.fees) == Σ cumulative_fees` | | | ✗ | No assertion anywhere |
| Trade-path bit-identity in CI | | ✓ | | Functional test **skips** on cache miss; in-proc double-call only |
| Config snapshot contract | ✓ | | | `test_app_baseline_config_contract_hash` (data-free) |
| Unknown config key rejected | | | ✗ | `test_backtest_app_config_keys.py` covers allowed deltas only |
| Loose scalar type rejected | ✓ | | | `_check_yaml_keys_and_types` raises (`:1711-1729`) |
| Exit code nonzero on bad config / boot / ingest | ✓ | | | `tests/harness`, `tests/cli/test_backtest_cli.py` (51 passed) |
| Exit 2 on verification fail | ✓ | | | runner `:807-808` |
| Exit nonzero on integrity exception | | ✓ | | Re-raise path untested for clean message |
| JSONL fill round-trip | | ✓ | | Fields covered; float-coercion streams not asserted lossless |
| `split_backtest_emit` round-trips real output | | | ✗ | Test uses wrong format (§5) |
| `compare_paper_backtest` correctness | | | ✗ | No test of the divergence math |
| `PYTHONHASHSEED` enforced for operator runs | | | ✗ | conftest-only |
| `smoke_pipeline.py` runs green | | | ✗ | Broken on main (E-4) |

**Minimal new tests (specs only):**
1. `test_report_net_pnl_matches_ack_fee_population` — build a run with one CANCELLED ack
   carrying a fee; assert the report's Net P&L equals `gross − sum(ack.fees)` and equals
   `start + Σ position.cumulative_fees` to the cent. Locks §4.2.
2. `test_unknown_config_key_rejected` — `pytest.raises(ConfigurationError)` on a YAML with a
   misspelled field (or assert a strict-mode flag). Closes §6.2.
3. `test_split_emit_parses_real_emitter_output` — feed `mod._emit_jsonl_line`-shaped lines
   (`PREFIX {json}`) and assert non-empty per-stream files + preserved order. Closes §5.
4. `test_backtest_exits_nonzero_on_integrity_failure` — inject a pipeline exception; assert
   `run_backtest_api` returns/raises nonzero with a message (not a bare traceback).
5. `test_smoke_pipeline_runs` (CI, no API key) — guards E-4 from regressing again.

---

## 9. Prioritized backlog

**P0** — none. (No silent exit-0-on-error, no double-count, no ungated *destructive* baseline
overwrite. The fidelity issues below are real but conditional/diagnostic, hence P1.)

**P1**

| # | Component | `file:line` | One-line fix | Impact | Effort |
|---|---|---|---|---|---|
| 1 | split emit | `scripts/split_backtest_emit.py:27-29` vs `backtest_jsonl.py:97` | Parse on first single space; fix the test format | Splitter actually works; `compare_paper_backtest` gets real data | S |
| 2 | paper-compare | `scripts/compare_paper_backtest.py:53-76` | Compute backtest fill-rate from acks (or remove the constant), implement or remove the hardcoded metrics; gate promotion use | Stops a broken comparator feeding promotion | M |
| 3 | report fees | `backtest_report.py:191` / `test_backtest_app_baseline.py:127-137` | Reconcile test to `sum(ack.fees)` + assert `==Σ cumulative_fees` | Locks report↔fills reconciliation incl. cancel fees | S |
| 4 | config strictness | `platform_config.py:1697-1704` | Raise `ConfigurationError` on unknown keys (or `--strict-config`) + test | Kills silent-misconfiguration footgun | S |
| 5 | reproducibility | `backtest_runner.py:815-924` | Assert/echo `PYTHONHASHSEED` into report header | Harness-level determinism backstop + provenance | S |
| 6 | provenance: data | `backtest_report.py:603-614`, runner `:773` | Derive `data_version` from cache content hash, not `(symbols,date_range)` | Detects changed tape under same label (Inv-13) | M |
| 7 | provenance: code | `backtest_report.py:664` | Fold git SHA into `ENGINE_VERSION`/`artifact_id` | Code change can't masquerade as same artifact | S |
| 8 | smoke | `scripts/smoke_pipeline.py:191-198,250-256` | Reference/remove `hysteresis` margins | Restores the documented no-API-key smoke | S |

**P2**

| # | Component | `file:line` | Fix | Effort |
|---|---|---|---|---|
| 9 | scripts import | `bootstrap.py:119` | Lazy-import paper backend so backtest scripts don't need `ib` | M |
| 10 | fixtures | `scripts/generate_bt12_fixtures.py:65-69` | Add `--force`/confirmation/dry-run guard | S |
| 11 | report text | `backtest_report.py:486-518` | Document non-determinism of Latency block / split a deterministic artifact view | S |
| 12 | report metrics | `backtest_report.py:204-214,220` | Treat scratch trades explicitly; document `pnl_per_share` denominator | S |
| 13 | macro check | `backtest_runner.py` after `:759` | Explicit `assert macro==READY` gate (don't rely on verification #6) | S |
| 14 | CI baseline | `test_backtest_app_baseline.py` | Add a tiny committed-fixture deterministic backtest that pins `pnl_hash` without the disk cache | M |
| 15 | jsonl precision | `backtest_jsonl.py:177-182,237-241` | Emit Decimals as strings in SIGNAL/INTENT streams (or document lossy) | S |

---

*Read-only audit. No production code, baseline, or parity hash was modified. Test commands
in §Method were run for evidence only.*
