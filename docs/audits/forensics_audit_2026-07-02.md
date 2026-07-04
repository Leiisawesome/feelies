# Post-Trade Forensics & Edge-Decay Audit — 2026-07-02

**Scope:** the forensics feedback loop — multi-horizon attribution, decay/TCA detection, the
realized-vs-disclosed close-the-loop modules, and the quarantine auto-trigger surface. This is
the layer that decides whether a live edge is still real (Inv-4) and demotes it fail-safe
(Inv-11). Read-only, evidence-based. **No production code, ledger, baseline, or config was
modified.**

**Method:** this is a *re-audit*. The prior pass (`docs/audits/forensics_audit_2026-06-23.md`,
branch `claude/charming-keller-xttb6e`) filed 5 P0s and 9 P1s. A remediation commit
(`9949dab`, 2026-06-25) plus a follow-on CLI fix (`7125ebe`, 2026-06-26) claim to close most of
them. Rather than re-deriving findings from scratch, this audit **independently verifies each
claimed fix against the current working tree** (branch `claude/determined-euler-33zqmv`, which
is current with `main`) by tracing the actual production call sites — not just reading module
docstrings — and only then looks for defects the remediation introduced or missed. All
`path:line` citations are against the current working tree.

**Read-only checks executed**

| Check | Result |
|-------|--------|
| `uv sync --all-extras` (environment bootstrap; venv was not pre-built) | OK |
| `pytest tests/forensics/test_tca.py tests/acceptance/test_decay_divergence.py -q` | **16 passed** |
| `pytest tests/alpha/test_promotion_evidence.py -q -k quarantine` | **11 passed**, 124 deselected |
| `pytest tests/forensics/ -q` (full directory, not mission-mandated but directly informs §8) | **49 passed** |
| `grep` for callers of `MultiHorizonAttributor.attribute` outside its own module/test | **none** |
| `grep` for `Alert(` / `bus.publish` / `EventBus` inside `src/feelies/forensics/` | **none** |
| `grep` for `expected_half_life_seconds` inside `src/feelies/forensics/` | **none** |
| Traced `OrderIntent.strategy_id` / `SizedPositionIntent.strategy_id` to confirm the per-trade mechanism side-table actually activates in production (not just in unit tests) | confirmed — see §3.2 |
| Traced `TradeRecord.cost_bps` / `.fees` back through `CostBreakdown` to confirm/refute the "two distinct cost views" claim in `cost_survival.py` | confirmed same underlying quantity — see §4.3 |

Classification legend: **[BUG]** implementation defect · **[MODELING]** modeling choice that
may be wrong but is a judgement call · **[DESIGN]** intentional design (flagged where it
carries decision-corruption risk) · **[DOC]** documentation drift · **[FIXED]** a prior
finding independently reverified as resolved.

---

## 1. Executive summary

**Headline: the 2026-06-23 P0s are genuinely fixed, not just marked fixed.** All five prior
P0s were independently re-derived from the production call path (not merely re-read from the
remediation's own docstrings) and hold up. No new P0 surfaced. The residual findings are P1
documentation/semantic-precision and wiring gaps — real, but none corrupt a live decision.

1. **[FIXED] Regime bucketing is now causal and deterministic.** `TradeRecord.regime_state` is
   captured once, synchronously, at fill time via `_regime_label_for` (`orchestrator.py:5859-5878`,
   called from the fill-journal site at `orchestrator.py:5843`) — not re-derived from a live
   `RegimeEngine` handle at audit time. The attributor buckets on this recorded field only
   (`multi_horizon_attribution.py:186-191`), with no engine lookup. Verified against a new,
   passing test that asserts two `attribute()` calls over the same journal agree bit-for-bit
   (`tests/forensics/test_multi_horizon_attribution.py:156-173`). Closes old P0-1/P0's
   determinism corollary.

2. **[FIXED, for the case it targets] Mechanism attribution now reads per-trade
   `Signal.trend_mechanism` provenance instead of re-inferring from a stale gross-exposure
   snapshot.** I traced this end-to-end rather than trusting the docstring: a Signal's
   `trend_mechanism` is cached in `_last_signal_mechanism[(strategy_id, symbol)]`
   (`orchestrator.py:6087-6091`) and stamped onto the `TradeRecord` at fill time
   (`orchestrator.py:5817-5843`). Crucially, `OrderIntent.strategy_id = signal.strategy_id`
   (`execution/intent.py:45,115,126,134...`), so for a SIGNAL-alpha trading directly, the fill's
   `order.strategy_id` **does** match the side-table key — the per-trade path genuinely fires in
   production, not only in unit tests. For PORTFOLIO alphas, `order.strategy_id` is the
   portfolio's own id (from `SizedPositionIntent.strategy_id`, `orchestrator.py:6222-6238`), so
   the lookup correctly misses and falls back to the (now explicit, now-conserving) gross-share
   snapshot split — a legitimate approximation for fills that genuinely commingle mechanisms.
   Eight new unit tests pin conservation, provenance-over-snapshot precedence, and the
   `unattributed` residual (`tests/forensics/test_multi_horizon_attribution.py`). Closes old
   P0-1/P0-4/P0-5's attribution-correctness claims.

3. **[FIXED] The decay z-test is no longer ~7× under-powered.** `detect_edge_decay` now divides
   the historical-vs-recent mean shift by the standard error of the recent-window mean
   (`hist_stdev / sqrt(len(recent))`, `decay_detector.py:178-179`) instead of the raw per-trade
   stdev. This is the statistically correct denominator for "is the recent-50 mean below
   history" and closes old P0-2. Minor new residual: when historical stdev is exactly 0, the
   epsilon-only denominator makes the test *hypersensitive* (any nonzero recent deviation → huge
   z) — a false-*positive* risk, which is the less costly error under Inv-4 (§5.1).

4. **[FIXED] Decay detection is no longer blind to cost-driven/crowding decay.**
   `detect_edge_decay`'s internal edge series is now net of fees
   (`net = realized_pnl - fees`, `decay_detector.py:155`), so a strategy whose gross edge holds
   flat while costs rise is now visible to the z-test itself, not only to the circuit breaker's
   separate `net ≤ 0` rule. Closes old P0-3.

5. **[P1, refines old P0-5] The attributor now has real unit-test coverage but is still**
   **completely unwired in production.** `grep` for `MultiHorizonAttributor` / `.attribute(`
   outside its own module and test file returns nothing — no CLI command, script, or
   `session_reconcile` call site ever constructs or invokes it. The "untested" half of old P0-5
   is closed; the "unwired" half is unchanged. Downgraded from P0 to P1 because the risk is now
   "the tool sits idle," not "the tool is silently wrong" (Inv-4).

6. **[P1/MODELING, new] `cost_survival.py`'s "two distinct cost views" claim is not accurate —**
   **`cost_bps` and `fees` are the same underlying dollar figure in different units.** I traced
   `TradeRecord.cost_bps` back through `CostBreakdown`: `cost_bps = total_fees / notional × 1e4`
   is computed from the *same* `total_fees` that becomes `TradeRecord.fees`
   (`execution/cost_model.py:395-396`; both set from one `CostBreakdown` at
   `market_fill.py:281-282,324-325,350-351`). The P1-9 remediation's own docstring
   (`cost_survival.py:54-59`) asserts they are "a different quantity" — they are not; the real
   (undocumented) source of "net-positive yet thin-gross-margin" divergence is a
   notional-weighted-sum vs. unweighted-mean-of-ratios aggregation effect, not two independent
   cost measurements. Does not corrupt the BLEED/MARGINAL/SURVIVES verdict (which uses
   well-defined inputs correctly); does mean there is still no comparison against the alpha's
   *disclosed* `cost_arithmetic` anywhere in this layer (Inv-12) — confirming P1-7/P1-8 remain
   the real expected-vs-realized gap.

7. **[P1, new] The circuit breaker's new structured evidence will flag most of its own real**
   **triggers as "spurious."** `_decision_to_quarantine_evidence` (`cost_circuit_breaker.py:206-240`)
   only ever populates `crowding_symptoms` (≤ 3 cost/decay tags, not real crowding symptoms) and
   `pnl_compression_ratio_5d` (repurposed as a margin ratio). Working the three real trigger
   branches against the five documented thresholds (`promotion_evidence.py:754-796`): only the
   `net ≤ 0` "bleed" branch reliably crosses a threshold (the one scenario the new test covers,
   `tests/forensics/test_cost_circuit_breaker.py:218-248`); the "does not cover cost" and
   "decay-z" branches will typically cross **none** of the five fields and get logged as
   spurious. Inv-11 still holds (the demotion always commits), but a consistency check that
   cries wolf on legitimate triggers trains operators to ignore it — undermining the one thing
   it exists to do.

8. **[FIXED] The Inv-11 fail-safe-with-evidence gap is now tested.** Old P1-13 ("no test proves
   a spurious `QuarantineTriggerEvidence` still commits + warns") is closed:
   `test_spurious_trigger_still_commits_and_warns` (`tests/forensics/test_cost_circuit_breaker.py:251-262`)
   asserts exactly this.

9. **[FIXED, cross-cutting] The CLI can now round-trip a quarantine-with-evidence ledger entry.**
   Commit `7125ebe` added `RESERVED_METADATA_KEYS = {"schema_version", "reason"}`
   (`promotion_evidence.py`) so `metadata_to_evidence` no longer raises on the `reason` co-key
   `AlphaLifecycle.quarantine` always writes. Without this, `feelies promote replay-evidence`
   would have false-FAILed (exit 3) on every auto-quarantine the new P1-6 evidence path
   produces — this fix is load-bearing for item 2/6 above to be useful in practice, not just a
   separate alpha-lifecycle-audit item.

10. **[P2/DOC, new] Three documents now disagree about whether `realized_pnl` is "mid-to-mid."**
    `trade_journal.py`'s `net_pnl` docstring was corrected (commit `0a3fa3e`) to state
    `realized_pnl` already includes the crossed half-spread and `fees` carries no separate
    spread cost. `cost_survival.py:51,65` (written before that correction, never updated after)
    still calls it "mid-to-mid ``realized_pnl`` (gross of fees)" — the exact stale convention the
    correction rejected — and the post-trade-forensics SKILL.md (canonical audit context) carries
    the identical stale claim. I traced the actual cost model and confirmed no double-counting
    occurs in the common path (`fee_half_spread = 0` for ordinary taker fills,
    `market_fill.py:228-230`; authoritative convention at `portfolio/position_store.py:22-63`) —
    this is a real documentation-drift risk, not a live computational bug.

11. **[P1/DOC, new] The SKILL's "Event Interface" section describes a mechanism that does not**
    **exist for any shipped module.** The skill states forensic findings "are delivered via
    `Alert` events... `AlertManager` routes by severity," softened only by a "Not shipped" note
    that dedicated event types aren't built (implying generic `Alert` is used instead). `grep`
    across all of `src/feelies/forensics/` for `Alert(`, `bus.publish`, `EventBus` returns
    **zero** matches — no forensics module publishes any event, generic or dedicated.

12. **[P1/MODELING, carries forward] Holding-period vs. `expected_half_life_seconds` still has**
    **no comparison logic**, though the blocking data gap is now closed. `TradeRecord` now
    carries `expected_half_life_seconds` (populated causally, `orchestrator.py:5842`), but `grep`
    confirms zero references to this field anywhere in `src/feelies/forensics/` — nothing
    consumes it yet.

13. **[P2/DOC, reverified unchanged] The architecture doc still overstates the attributor.**
    `docs/three_layer_architecture.md:824-838,1591-1602,1907` (re-read at current HEAD, byte-for-byte
    unchanged since 2026-06-23) still claims gross alpha / TC drag / factor bleed / timing
    slippage / realized-vs-expected IC / rolling-30d realized IC with numeric CRITICAL/WARNING
    thresholds. None of this exists in the shipped `multi_horizon_attribution.py`.

14. **[Scoping note]** `tests/acceptance/test_decay_divergence.py` — named in this mission's own
    file list and read-only-check command, and run by both this audit and the prior one — tests
    the **composition-layer's** `CrossSectionalRanker.decay_weighting_enabled` (temporal
    signal-staleness re-weighting), not forensics edge-decay detection. It is a naming
    collision with **zero** bearing on Inv-4 decay-detection coverage. Flagged so its "16 passed"
    (really: 4 composition tests + 12 unrelated `test_tca.py` tests) is not miscounted as
    forensics decay-detector coverage in a future re-audit.

15. **[GREEN, reverified] Everything the 2026-06-23 audit marked GREEN still holds.**
    `validate_quarantine_trigger` only ever returns warnings (`promotion_evidence.py:754-796`);
    `AlphaLifecycle.quarantine` always commits the transition regardless
    (`lifecycle.py:416-437`); `fill_attribution.py`'s largest-remainder allocation remains
    conservation-correct and deterministic; no forensics module reads the promotion ledger or
    takes a wall-clock reading.

---

## 2. Forensic-metric inventory

| Metric | Formula (as coded) | Threshold / trigger | Source |
|--------|--------------------|---------------------|--------|
| Horizon PnL bucket | `Σ realized_pnl` per `(strategy_id, horizon)`; horizon from a static map | — (reporting) | `multi_horizon_attribution.py:173-182,211-222` |
| Mechanism PnL (provenance path) | `Σ realized_pnl` per `(strategy_id, trade.trend_mechanism)` — per-trade, causal | — (reporting) | `:193-198,262-285` |
| Mechanism PnL (fallback path) | `total_strategy_pnl × (gross_share_m / Σ gross_share)` from latest snapshot, only when no trade in the strategy carries provenance | — (reporting) | `:287-309` |
| `unattributed[sid]` residual | strategy PnL from mechanism-less trades when the strategy has *some* provenance, or all PnL when it has none/no snapshot | — (conservation) | `:169,282-284,293-300` |
| Regime PnL bucket | `Σ realized_pnl` per `(strategy_id, trade.regime_state)` — recorded at fill time | — (reporting) | `:186-191,224-233` |
| `regime_state` capture | argmax of `RegimeEngine`'s already-computed posterior, read synchronously at fill-ack time | — (provenance) | `orchestrator.py:5843,5859-5878` |
| `trend_mechanism` / `expected_half_life_seconds` capture | last SIGNAL event's fields for `(strategy_id, symbol)`, stamped at fill | — (provenance) | `orchestrator.py:773-780,5817-5843,6087-6091` |
| `mean_edge_bps` (TCA) | `mean(realized_pnl / notional × 1e4)` — **gross** of fees | — | `decay_detector.py:66-74,81` |
| `mean_cost_bps` | `mean(cost_bps)`, where `cost_bps ≡ fees / notional × 1e4` by construction (§4.3) | — | `decay_detector.py:67,77`; `cost_model.py:395-396` |
| `pct_edge_covers_cost` | `%` trades with `edge_bps > 2 × cost_bps` | fixed **2×** (not the alpha's disclosed 1.5× `margin_ratio`) | `decay_detector.py:87-89` |
| `rolling_50 / 200_mean_edge` | mean of last 50 / 200 gross edges | — | `decay_detector.py:110-113` |
| Edge-decay Z | `(hist_mean − recent_mean) / (hist_stdev/√n_recent + 1e-9)`, **net of fees** | `z > 2.0`, n ≥ 100, recent = 50 | `decay_detector.py:146-182` |
| Realized margin (survival) | `mean_edge_bps / mean_cost_bps` (both gross-of-fees / fee-derived) | `< cover` (1.0) → trip; `< survival` (1.5) → WATCH | `cost_survival.py:105-109`, `cost_circuit_breaker.py:143-149` |
| Net (survival) | `Σ realized_pnl − Σ fees` | `net ≤ 0` over ≥ `min_fills`(30) → QUARANTINE | `cost_survival.py:104`, `cost_circuit_breaker.py:133-137` |
| Edge haircut factor | `clamp(realized_mean / disclosed, 0, 1)` | applies only when `n ≥ 30` and `disclosed > 0` | `edge_calibration.py:107,111` |
| Edge LCB factor | `clamp((mean − z·std/√n) / disclosed, 0, 1)` | `z = 1.0` (default), `min_fills = 30` | `edge_calibration.py:100,104,112` |
| Quarantine trigger (schema) | per-field comparisons; OR of 5 conditions | 10 neg-α days / ≤ −15pp hit / ≤ 0.3 PnL-compress / ≥ 2 micro / ≥ 3 crowding | `promotion_evidence.py:322-336,754-796` |
| Circuit-breaker → evidence mapping | `crowding_symptoms` ← ≤ 3 cost/decay tags; `pnl_compression_ratio_5d` ← `max(0, margin)` | only 2 of 5 schema fields ever populated (§6.2) | `cost_circuit_breaker.py:206-240` |

**Read this table as the gap map (unchanged conclusion from 2026-06-23):** every "expected"
column the skill specifies (expected slippage, expected hit rate, backtest IC) is still absent;
every threshold that exists is either a self-referential drift bar or a hardcoded constant. The
remediation fixed *how the realized side is computed* (causality, statistical power, fee
netting); it did not add an expected/disclosed side to compare against (P1-7/P1-8, still
explicitly deferred — confirmed by `grep`, no new module implements this).

---

## 3. Attribution audit

### 3.1 Conservation (Σ buckets [+ unattributed] = total) — now holds, verified by property tests

- **Horizon axis.** Unchanged design: `Σ_h HorizonBucket.realized_pnl = Σ_trades realized_pnl`.
  **Conserved**, `multi_horizon_attribution.py:173-182,211-222`; pinned by
  `test_horizon_axis_conserves` (`tests/forensics/test_multi_horizon_attribution.py:82-91`).
- **Mechanism axis.** Now conserves **including across strategies**. Per strategy: if any trade
  carries `trend_mechanism`, every mechanism-bearing trade's PnL is bucketed exactly
  (`:262-285`), and any residual from mechanism-less trades in that same strategy goes to
  `unattributed[sid]` (`:282-284`). If no trade in the strategy carries provenance, the gross-share
  snapshot fallback runs (`:287-309`), and a strategy with neither provenance nor a snapshot (or
  an empty one) reports its whole PnL in `unattributed` instead of vanishing (`:293-300`). Pinned
  by four tests (`tests/forensics/test_multi_horizon_attribution.py:94-153`), including the exact
  scenario the prior audit's P1-8 finding described (a strategy with no snapshot silently
  dropping PnL — now `test_no_provenance_no_snapshot_is_unattributed_not_dropped`, `:133-138`).
  **This closes old P1-8.**
- **Regime axis.** `Σ_r RegimeBucket.realized_pnl = Σ_trades realized_pnl` for trades with a
  non-empty `regime_state`; trades with `regime_state == ""` (cold start, no engine) are excluded
  from the regime axis only, by design (`:187-188`, tested
  `test_empty_regime_label_is_skipped`). This is a legitimate exclusion (there is no regime to
  attribute to), not a leak — the horizon and mechanism axes still capture that PnL.
- **Cross-axis.** As before, the three axes remain independent partitions of the same `total`;
  no joint (mechanism × regime × horizon) decomposition exists, matching the architecture doc's
  unfulfilled promise (§13 below). No double-count risk since there is no joint structure to
  double-count.

### 3.2 Mechanism bucketing — provenance vs re-inference (the mission's central falsifiable test)

The mission's test: *"attribution buckets by mechanism re-inferred from features, so a
KYLE_INFO alpha's PnL can land in the INVENTORY bucket."* **No longer true for SIGNAL-alpha
trades; still an accepted approximation for PORTFOLIO-alpha trades.**

I did not stop at reading the attributor's docstring — I traced the actual production wiring
that makes per-trade provenance possible:

1. When a SIGNAL-layer alpha's `Signal` arrives, the orchestrator caches
   `(trend_mechanism, expected_half_life_seconds)` keyed by `(event.strategy_id, event.symbol)`
   (`orchestrator.py:6083-6091`) — a pure side table, never read on the decision path.
2. `SignalPositionTranslator.translate` builds an `OrderIntent` with
   `strategy_id=signal.strategy_id` (`execution/intent.py:112-119,121-135` and every other
   branch of the translation matrix) — i.e., for a SIGNAL alpha trading directly, the eventual
   `OrderRequest.strategy_id` (`orchestrator.py:4509-4519`, `strategy_id=intent.strategy_id`) is
   the **same** id the Signal handler used as the side-table key.
3. At fill time, the lookup `_last_signal_mechanism.get((order.strategy_id, ack.symbol))`
   (`orchestrator.py:5817-5820`) therefore **hits** for SIGNAL-alpha fills, and the mechanism/
   half-life are stamped onto the `TradeRecord` (`:5841-5842`).
4. For a PORTFOLIO alpha, per-leg orders are submitted from `SizedPositionIntent` fan-out
   (`_on_bus_sized_intent` → `_submit_portfolio_leg_without_micro_walk`,
   `orchestrator.py:6222-6238`), where `strategy_id` is the **portfolio's own** id — never a key
   in `_last_signal_mechanism` (which is only ever written from SIGNAL events). The lookup
   correctly misses, `trend_mechanism=None` is stamped, and the attributor falls back to the
   gross-share snapshot split.

This is a coherent, deliberate design, not an accident: a single cross-sectional PORTFOLIO fill
genuinely can commingle several signal families, so there is no single "true" per-trade
mechanism to stamp — the gross-share approximation is the right tool for that specific case, and
it is now explicit and conserving (§3.1) rather than silently smearing history through a stale
point-in-time snapshot (the old P0-4 finding). **Verdict: the KYLE→INVENTORY mis-bucketing the
2026-06-23 audit demonstrated is fixed for the SIGNAL-only path; the PORTFOLIO path uses the
same coarser (but now honestly-labeled) method as before.**

### 3.3 Regime bucketing — causality and determinism

`_regime_label_for(symbol)` (`orchestrator.py:5859-5878`) reads
`self._regime_engine.current_state(symbol)` — the **same underlying API** the old, buggy code
called. The fix is *when* it is called: synchronously, once, during fill-ack processing
(`orchestrator.py:5843`, inside the same handler that constructs the `TradeRecord`), with the
result immediately frozen onto the record. The forensic layer never touches the live engine —
it reads `trade.regime_state` (`multi_horizon_attribution.py:187`), a value fixed at write time.
Two audits over the same journal necessarily agree because there is no live state left to
diverge on. This is exactly the right shape of fix (move the causality-sensitive read from
audit-time to write-time, don't try to make an audit-time read "more causal"), and it is
directly tested (`test_regime_bucketing_is_causal_and_deterministic`,
`tests/forensics/test_multi_horizon_attribution.py:156-173`, asserting two `attribute()` calls
over the same trades produce identical regime buckets). **This closes old P0-1's causality and
determinism findings together** (they were one root cause, and one fix addressed both).

One scope caveat, not a defect: I did not independently re-verify the exact micro-state
ordering guarantee that the regime engine's posterior for a symbol is never updated *after* a
same-tick fill using information that arrived later in that same tick (i.e., that "fill time"
and "regime-computation time" are correctly ordered inside the synchronous cascade). The new
unit tests exercise the attributor against fixed `TradeRecord` fixtures, which validates the
*consumption* side but not this specific *production* ordering claim. Given the single-threaded,
deterministic bus architecture (Inv-6/Inv-7) this is very likely correct, but it rests on
`orchestrator.py`'s micro-state sequencing rather than on a forensics-layer test, so I flag it
as an open item rather than a fully closed loop (§10, appendix).

### 3.4 Holding-period bucketing vs. `expected_half_life_seconds`

Unchanged in substance from 2026-06-23, but the blocking data gap is now closed:
`TradeRecord.expected_half_life_seconds` exists and is populated causally
(`orchestrator.py:5842`, sourced from the same `_last_signal_mechanism` side table as
`trend_mechanism`). However, `grep` for `expected_half_life_seconds` inside
`src/feelies/forensics/` returns **zero matches** — no module reads it. The horizon axis remains
a static, configured `strategy_id → horizon_seconds` label (`multi_horizon_attribution.py:173`),
not a measured holding period compared against the alpha's own half-life. **[P1/MODELING]**
(Inv-1/Inv-4): the prerequisite is now in place; the comparison itself is still unbuilt. Given
the data now exists for SIGNAL-alpha trades specifically (§3.2), this is a smaller lift than it
was in the prior audit — worth noting in the backlog as now more tractable, not as newly urgent.

---

## 4. Expected-vs-realized (TCA) audit

### 4.1 Expected side — still absent (confirmed unchanged)

No metric anywhere in this layer is sourced from an alpha's disclosed `cost_arithmetic`
(`expected_edge_bps`, `half_spread_bps`, `expected_impact_bps`, `margin_ratio`) or a backtest
baseline, except `edge_calibration.py`, which remains the one place a disclosed value enters
(`haircut/lcb = realized / disclosed`, `:107-108,111-112`) — and that is realized-vs-disclosed
*shrinkage for the next run's gate*, not a forensic residual or significance test, exactly as
found in 2026-06-23. `pct_edge_covers_cost` still hardcodes a literal `2×`
(`decay_detector.py:88`) rather than reading the alpha's own `margin_ratio` (Inv-12's bar is
1.5×). **Unchanged; P1-7/P1-8 remain the real gap, confirmed still deferred.**

### 4.2 Statistical meaningfulness

The decay z-test (§5) is now the one place in the TCA stack with a defensible statistical
construction (§5.1). Everything else — `mean_edge_bps`, `p95_edge_bps`, `pct_positive_edge`,
`pct_edge_covers_cost`, `realized_margin_ratio` — remains point estimates with no variance,
confidence interval, or sample-size gate on the headline figures
(`decay_detector.py:41-127`, `cost_survival.py:103-146`). `edge_calibration`'s LCB
(`mean − z·std/√n`, `edge_calibration.py:100,104`) remains the only other statistically
grounded construct in the layer. **Unchanged from 2026-06-23.**

### 4.3 Sign / units consistency — re-derived from first principles, and the P1-9 "clarity" fix is itself imprecise

This is the deepest new finding in this audit. I traced `TradeRecord.cost_bps` and
`TradeRecord.fees` back to their common source rather than accepting either module's
description of them:

- `CostBreakdown.total_fees = spread_cost + commission + adverse_cost + regulatory_cost + htb_cost`
  and `cost_bps = total_fees / notional × 1e4` (`execution/cost_model.py:395-396`) — **one**
  computation produces both.
- Every fill-ack construction site sets `fees=costs.total_fees` and `cost_bps=costs.cost_bps`
  from the **same** `CostBreakdown` instance in the same call
  (`market_fill.py:281-282,324-325,350-351`; `moc_fill.py:216,223,235`).
- Therefore `TradeRecord.cost_bps ≡ TradeRecord.fees / notional × 1e4` (up to the 2-decimal
  quantization on `cost_bps`) **by construction**, not by coincidence.

`cost_survival.py:49-59`'s docstring, added by the P1-9 "clarity" remediation, states:

> `realized_margin_ratio = mean_edge_bps / mean_cost_bps` is a **gross** edge-vs-modeled-cost
> ratio... `mean_cost_bps` is the modeled per-trade cost... — a **different quantity from
> `fees`**. An alpha can be net-positive yet have a thin gross margin (MARGINAL). The two views
> are not interchangeable.

This is not accurate: `mean_cost_bps` is not an independent "modeled" cost estimate distinct
from what was actually charged — it *is* the realized fees, expressed as a per-trade bps rate
instead of a dollar sum. The genuine (but undocumented) reason `net` (a notional-weighted dollar
sum: `Σrealized_pnl − Σfees`) and `mean_edge_bps / mean_cost_bps` (an unweighted mean-of-ratios
across trades) can diverge is an **aggregation-weighting** effect — a few large-notional trades
can dominate the dollar sum while contributing proportionally to the bps average like every
other trade — not two economically distinct cost concepts. `test_profitable_but_fragile_is_watch`
(`tests/forensics/test_cost_circuit_breaker.py:97-100`) exercises exactly this divergence but
via uniform per-trade fixtures, so it does not distinguish "different cost concept" from
"different aggregation," leaving the docstring's causal claim unverified by its own test suite.

**Consequences, calibrated honestly:**
- The `_verdict()` / `evaluate_cost_circuit_breaker()` logic is unaffected — it consumes
  well-defined, correctly-computed `net` and `margin` values regardless of how the docstring
  describes them. **No decision is corrupted.**
- What *is* affected: an operator reading `cost_survival.py`'s docstring would believe
  `realized_margin_ratio` is cross-checking realized edge against an independently *modeled*
  transaction-cost estimate (the kind of check dimension B of this audit is looking for). It
  is not — it is realized edge against realized fees, restated. The layer still has no
  comparison against a genuinely independent expected-cost source (the alpha's disclosed
  `cost_arithmetic`), reinforcing §4.1.
- I confirmed this is not a live double-counting bug: for ordinary taker fills,
  `fee_half_spread = 0` is passed into `cost_model.compute` (`market_fill.py:228-230`), so
  `spread_cost` inside `total_fees` is zero and the crossed-price spread lives only in
  `realized_pnl`, per the authoritative convention at `portfolio/position_store.py:22-63`. Only
  for a stop/forced-exit fill does `fee_half_spread` become the *additional* slippage beyond one
  half-spread (`market_fill.py:227-228`) — correctly kept out of `realized_pnl` and booked as a
  fee, matching `trade_journal.py:71` ("any forced-exit panic slippage").

**[P1/MODELING]** (Inv-12, Inv-13): re-label `cost_survival.py:54-59` to describe the
aggregation-weighting effect accurately, or (better) stop citing `cost_bps` as if it were an
independent modeled-cost benchmark and instead wire in the alpha's disclosed
`cost_arithmetic.round_trip_cost_bps` as the actual second, independent view the docstring
believes already exists.

---

## 5. Decay detection audit (Inv-4)

### 5.1 Calibration — now statistically sound, with one new corner case

`detect_edge_decay` (`decay_detector.py:129-197`): unchanged gate structure (≥ 100 trades, last
50 "recent," z > 2.0), but the denominator is now `recent_se = hist_stdev / sqrt(len(recent))`
(`:178-179`) instead of raw `hist_stdev`. This is the correct standard error for testing whether
a 50-trade sample mean has dropped significantly below a historical mean, assuming the
historical stdev approximates the population sigma (reasonable when historical ≥ 50 trades,
which the ≥100-total/50-recent gate guarantees). Worked re-check of the prior audit's own
example: edge halving from 5→2.5 bps with per-trade σ=20 bps now gives
`z = 2.5 / (20/√50) ≈ 0.88` — still below the 2.0 gate at this specific magnitude, but no longer
off by the old ~7× factor; a larger (still realistic) shift or a lower per-trade σ now crosses
threshold where it categorically could not before. **Closes old P0-2.**

New corner case introduced by the fix: when `hist_stdev == 0` (a constant historical edge),
`recent_se = 0`, so `z = (hist_mean − recent_mean) / 1e-9` — any nonzero deviation in the recent
window, however small, produces an enormous z-score. This trades the old *false-negative* bias
(the costly error under Inv-4) for a narrow *false-positive* risk in a degenerate,
low-realistic-probability input (real trade PnL is essentially never exactly constant across 50+
fills). **[P2/MODELING]**: low severity, opposite-direction risk, no test currently exercises
this zero-variance corner case (§8).

The `z > 2.0` threshold itself remains a fixed, undocumented-derivation constant with no stated
p-value or false-discovery control, and the test is still strategy-wide on **gross** edge for
the reporting path (`analyze_fills`) even though the *decision* path (`detect_edge_decay`) is
now net — this split is intentional (§1 item 4) but worth keeping in mind when the two are
compared side by side in a report. **[P1/MODELING], unchanged from 2026-06-23.**

### 5.2 False-negative bias — the P0s are closed; residual bias is now the ordinary kind

The two mechanisms that let a genuinely dead edge stay invisible before are both fixed:
cost/crowding blindness (§1 item 4, now net-of-fees) and statistical under-power (§5.1, now
correctly scaled). What remains is the *ordinary* residual false-negative risk any fixed
threshold carries (a decay smaller than what n=50/z=2.0 can resolve slips through) — a
reasonable, disclosed limitation rather than a structural blind spot. **No P0 remains here.**

### 5.3 Crowding / latency / microstructure signals — still entirely absent (confirmed unchanged)

None of the skill's §3 structural-change detectors exist: no spread-regime shift, no
quote-frequency KS test, no venue-Herfindahl, no latency-stratified PnL, no adverse-selection or
quote-anticipation scorecard. `QuarantineTriggerEvidence.microstructure_metrics_breached` and
`.crowding_symptoms` still have no computing module behind them in the sense the skill
describes — the only thing that *does* populate `crowding_symptoms` today is the circuit
breaker's re-purposed cost/decay tags (§6.2), which are not crowding symptoms in the skill's
sense (adverse selection, quote anticipation, factor correlation, etc.). **[P1/LIM], unchanged.**

---

## 6. Quarantine trigger audit (fail-safe + wiring)

### 6.1 Schema vs. skill thresholds — aligned, unchanged

`QuarantineTriggerEvidence` (`promotion_evidence.py:313-336`) and the quarantine `GateThresholds`
block (`:437-448`: 10 net-α-negative days, hit-rate ≤ −15pp, PnL compression ≤ 0.3 over 5d, ≥ 2
microstructure breaches, ≥ 3 crowding symptoms) still match the skill's "Strategy Quarantine"
table one-for-one, reverified against current code and
`tests/alpha/test_promotion_evidence.py:952-956`. **[GREEN].**

### 6.2 The validator never blocks, but the new evidence path will make it cry wolf

`validate_quarantine_trigger` (`promotion_evidence.py:754-796`) is unchanged: it returns errors
**only** when *none* of the five documented thresholds is crossed, and never raises. Confirmed
`AlphaLifecycle.quarantine` (`lifecycle.py:395-437`) always calls `self._sm.transition(...)`
after only logging any validator warnings. **Inv-11 holds in code — unconditionally.** This is
the important, unconditional part of the finding, and it remains true.

What's new is the *quality* of the evidence the one production auto-trigger now supplies.
`_decision_to_quarantine_evidence` (`cost_circuit_breaker.py:206-240`) builds a
`QuarantineTriggerEvidence` with only two of five fields ever set:

```
crowding_symptoms=(subset of {"net_negative_over_window",
                              "realized_edge_below_cost",
                              "edge_decay_zscore"})   # at most 3 tags
pnl_compression_ratio_5d=max(0.0, decision.realized_margin_ratio)  # or 1.0 if non-finite
```

`net_alpha_negative_days`, `hit_rate_residual_pp`, and `microstructure_metrics_breached` are
**never** set by this path (always their zero/empty defaults). Walking the three real
`evaluate_cost_circuit_breaker` trigger branches (`cost_circuit_breaker.py:128-158`) against the
five thresholds:

| Circuit-breaker trigger | Typical `compression` value | Crosses 0.3 threshold? | Typical `crowding_symptoms` count | Crosses 3-symptom threshold? | `validate_quarantine_trigger` verdict |
|---|---|---|---|---|---|
| `net ≤ 0` ("bleed") | often ≈ 0 (edge itself is usually weak/negative here) | usually yes | 1 (`net_negative_over_window`) | no | **usually NOT spurious** |
| margin < 1.0, net > 0 ("undercover") | 0.3–1.0 (by definition of this branch) | **often no** | 1 (`realized_edge_below_cost`) | no | **likely flagged spurious** |
| `decay_z > 2.0` | unconstrained by this branch | depends | 1 (`edge_decay_zscore`) | no | **likely flagged spurious** |

Only the first branch is covered by a test asserting the *non-spurious* outcome
(`test_apply_records_structured_quarantine_evidence`,
`tests/forensics/test_cost_circuit_breaker.py:218-248`, whose own comment acknowledges "a
genuine cost bleed maps to compression 0.0 ... so it is NOT mislabelled spurious" — correctly
scoped to that one branch only). The other two branches' interaction with
`validate_quarantine_trigger` is untested (§8).

**Why this matters despite Inv-11 holding:** the validator's purpose (per its own docstring,
`promotion_evidence.py:758-768`) is to flag *spurious-looking* triggers so operators investigate
false positives. If two of the three real trigger reasons routinely produce that flag, the
signal-to-noise of the flag collapses for the only automated trigger path that exists — a
"suspicious" WARNING that fires on most real quarantines teaches operators to ignore it,
which is the opposite of fail-safe in spirit even though the demotion mechanics remain fail-safe
in fact. **[P1/DESIGN]** (Inv-13: the evidence recorded should let an operator distinguish real
from spurious triggers; today it frequently can't for two of three real reasons).

### 6.3 Does forensics actually call `quarantine`? — yes, with real evidence now, still not from a live job

End-to-end trace, reverified at current HEAD:

```
session_reconcile.reconcile_session          (session_reconcile.py:55)   ← still NO production caller
  └ evaluate_cost_circuit_breaker(records)    (cost_circuit_breaker.py:95)
       ├ per_alpha_cost_survival(...)         (cost_survival.py:103)  → DecayDetector.analyze_fills
       └ DecayDetector.detect_edge_decay(...) (cost_circuit_breaker.py:124)
  └ apply_cost_circuit_breaker(decisions, lifecycles)  (:176)
       └ lifecycle.quarantine(reason, structured_evidence=[...])  (:197-201)
            ← NOW carries a QuarantineTriggerEvidence (was reason-only before 9949dab)
```

- **Old P1-6 (evidence never populated) is closed**: the auto-trigger now records structured
  evidence, and (per §6.2) it is imperfect but genuinely present and round-trips through the CLI
  (§1 item 9). **[FIXED, with the §6.2 caveat].**
- **Old P1-7 (nothing invokes the loop in production) is unchanged.** `grep` for
  `reconcile_session` outside its own module and tests still returns nothing. **[P1/LIM],
  confirmed still open** — this was explicitly deferred by the remediation commit's own message,
  and that is accurate.

---

## 7. Determinism & provenance audit

- **Horizon, mechanism, and regime axes are now all deterministic** given fixed inputs: no clock
  reads, no live-engine lookups, output keys sorted for stable iteration
  (`multi_horizon_attribution.py:211-212,224-225`; module docstring `:26-30`). This is a genuine
  upgrade from 2026-06-23, where the regime axis specifically was not (§3.3). **[GREEN, upgraded
  from prior finding].**
- **No ledger reads, no per-tick perturbation**, unchanged: the attributor, `decay_detector`, and
  the close-the-loop modules take no bus subscriptions and read no promotion ledger;
  `cost_circuit_breaker.apply` and `edge_calibration`'s store are documented and structured as
  session/epoch-boundary actions (`cost_circuit_breaker.py:19-22`, `edge_calibration.py:22-25`,
  `session_reconcile.py:12-14`). Inv-5 on the per-tick path is respected. **[GREEN].**
- **Provenance capture is a pure side effect of the fill path**, not a new decision input: the
  `_last_signal_mechanism` side table and `_regime_label_for` are read-only w.r.t. the trading
  decision itself (they run *after* the fill is already determined, purely to annotate the
  journal) — confirmed by reading the surrounding orchestrator code; neither is consulted by any
  signal-evaluation or risk-check logic. **[GREEN]**, and this is the correct shape for adding
  forensic provenance without creating a new Inv-8 layering edge or an Inv-5 replay-sensitivity
  path.
- **Open item (not a defect, a verification gap):** the exact micro-state ordering guarantee
  that regime-engine state used at `_regime_label_for` time cannot reflect information from
  *after* the fill within the same synchronous tick was not independently re-derived from the
  kernel's micro-state machine in this pass — it is asserted by the provenance-capture docstring
  and is consistent with the platform's single-threaded synchronous-bus design, but no
  forensics-layer test exercises the ordering directly (§10).

---

## 8. Test gap matrix

`tests/forensics/` now holds **six** files (was five): `test_tca.py`, `test_cost_survival.py`,
`test_edge_calibration.py`, `test_session_reconcile.py`, `test_cost_circuit_breaker.py`, and the
new `test_multi_horizon_attribution.py`. Full directory: **49 passed** (this audit's run).

| Invariant / behaviour | Status (2026-06-23) | Status (2026-07-02) | Evidence |
|-----------------------|---------------------|----------------------|----------|
| Attribution conservation (Σ buckets + unattributed = total) | MISSING | **COVERED** | `test_multi_horizon_attribution.py:82-153` |
| Causal regime bucketing (regime at entry, not audit-time) | MISSING | **COVERED** | `test_multi_horizon_attribution.py:156-173` |
| Mechanism bucketing prefers per-trade provenance over snapshot | MISSING | **COVERED** | `test_multi_horizon_attribution.py:108-116` |
| Mechanism-axis leak (no-snapshot strategy silently dropped) | MISSING (bug live) | **COVERED** (bug fixed + regression-guarded) | `test_multi_horizon_attribution.py:133-138` |
| Decay sensitivity to *realistic* (partial, non-catastrophic) decay | PARTIAL | **still PARTIAL** | only the catastrophic 5→0 bps case is asserted (`test_tca.py:168-195`); no test exercises the new `stdev/√n` statistic at a moderate (e.g. 25–50%) decay magnitude to demonstrate the P0-2 fix's actual sensitivity gain |
| Decay net-of-fees / cost-driven-decay detectability | MISSING | **still MISSING as a dedicated test** | the fix is real (§5, code-verified) but no test constructs "flat gross edge, rising fees" fills and asserts the detector now fires where it previously wouldn't — a regression here (e.g. someone reverting `net` back to gross in `detect_edge_decay`) would not be caught |
| Zero-historical-variance corner case (§5.1) | N/A (bug not yet introduced) | **MISSING** | no test with constant historical edge + any recent deviation |
| Expected-vs-realized residuals | MISSING | **still MISSING** | feature absent, confirmed by grep |
| Quarantine trigger thresholds (each field) | COVERED | **COVERED** | `test_promotion_evidence.py:615-646` |
| Quarantine validator never blocks (pure) | COVERED | **COVERED** | `test_promotion_evidence.py:642-646` |
| Inv-11 fail-safe *with spurious structured evidence* commits + WARNING | MISSING | **COVERED** | `test_cost_circuit_breaker.py:251-262` |
| Auto-trigger applies & writes ledger | COVERED | **COVERED** | `test_cost_circuit_breaker.py:151-173` |
| Auto-trigger records `QuarantineTriggerEvidence` (bleed branch) | N/A (not implemented) | **COVERED** | `test_cost_circuit_breaker.py:218-248` |
| Auto-trigger evidence vs. `validate_quarantine_trigger` for "undercover" / "decay" branches | N/A | **MISSING** | no test asserts spurious-or-not for these two branches (§6.2) |
| CLI round-trip of quarantine-with-evidence (`reason` co-key) | N/A (bug live, different audit) | **COVERED** | commit `7125ebe`'s tests (alpha-lifecycle scope, cross-referenced here as load-bearing) |
| Cost-survival verdicts on cached APP/2026-03-26 fills | COVERED | **COVERED** | `test_cost_survival.py:66-125` |
| Edge calibration LCB / parity-preserving haircut | COVERED | **COVERED** | `test_edge_calibration.py` (all 8 tests) |
| Forensic determinism (two audits agree) | MISSING (regime axis non-deterministic) | **COVERED** | `test_multi_horizon_attribution.py:164-173` |
| `cost_bps ≈ fees/notional×1e4` identity (§4.3) | N/A (not yet asked) | **MISSING** | no test encodes this invariant; a future change to `fee_half_spread` defaults could silently break the (currently-true) equivalence without any test noticing |
| `MultiHorizonAttributor` production wiring | MISSING (no callers) | **still MISSING** | grep, confirmed |
| `reconcile_session` production wiring | MISSING (no callers) | **still MISSING** | grep, confirmed (explicitly deferred, P1-7) |

---

## 9. Prioritized backlog

Effort: **S** ≤ ½ day · **M** ~1–2 days · **L** > 2 days. All prior P0s are closed; nothing below
is P0.

### P1

1. **Reconcile the `cost_bps`/`fees` documentation.** `cost_survival.py:49-59` · **S** ·
   either relabel the claim to describe the notional-weighted-sum-vs-unweighted-mean-of-ratios
   effect accurately, or better, wire `mean_cost_bps` to actually compare against the alpha's
   disclosed `cost_arithmetic.round_trip_cost_bps` (a genuinely independent second view). *Impact:*
   removes a misleading "independent cross-check" impression and is a concrete, small step toward
   closing the still-open P1-7/P1-8 expected-vs-realized gap (§4.1, §4.3).
2. **Align the circuit breaker's evidence mapping with what actually crosses documented**
   **thresholds.** `cost_circuit_breaker.py:206-240` · **M** · either populate
   `net_alpha_negative_days` / `hit_rate_residual_pp` from the same window the breaker already
   has (it knows `n_fills` and could track a negative-day streak), or accept that this trigger
   model is legitimately different from the skill's five fields and stop routing it through
   `QuarantineTriggerEvidence`'s "consistency" check at all (e.g. a distinct, honestly-named
   evidence variant). *Impact:* stops training operators to ignore a "spurious" WARNING that
   fires on most real triggers (§6.2).
3. **Test the two untested circuit-breaker → evidence branches.**
   `tests/forensics/test_cost_circuit_breaker.py` · **S** · add cases for the "undercover" and
   "decay-z" QUARANTINE branches asserting (and documenting, whichever way it falls) their
   `validate_quarantine_trigger` outcome, mirroring the existing bleed-branch test. *Impact:*
   makes the §6.2 finding regression-visible instead of implicit.
4. **Dedicated net-of-fees decay-detection regression test.** `tests/forensics/test_tca.py` ·
   **S** · construct fills with stable gross edge and rising fees and assert
   `detect_edge_decay` now fires (it wouldn't have, pre-9949dab). *Impact:* guards the P0-3 fix
   against silent reversion.
5. **Moderate-decay sensitivity test for the new statistic.** `tests/forensics/test_tca.py` ·
   **S** · a 25–50% edge decay (not the existing catastrophic 5→0 case) with realistic per-trade
   variance, asserting the new `stdev/√n` statistic detects it where the old raw-stdev version
   provably would not (worked example in §5.1). *Impact:* empirically demonstrates the P0-2 fix's
   actual sensitivity gain, not just its formula correctness.
6. **`cost_bps ≈ fees/notional` identity guard.** new test in `tests/forensics/` or
   `tests/execution/` · **S** · assert the invariant this audit derived in §4.3 directly against
   `CostBreakdown`/`TradeRecord` construction, so a future change to `fee_half_spread` handling
   can't silently reintroduce spread double-counting or break the (currently load-bearing but
   untested) equivalence. *Impact:* converts a manually-traced fact into a regression guard.
7. **Wire `MultiHorizonAttributor` and `reconcile_session` into a real boundary job.**
   `session_reconcile.py:55` + a paper/live session-end entry point · **M** (this is the
   remediation's own deferred P1-7, reconfirmed still open) · *Impact:* the fully-tested,
   fully-correct attribution and cost-survival logic actually runs against live data instead of
   sitting idle behind unit tests.
8. **Expected-vs-realized residuals.** New module, sourcing `cost_arithmetic` + a backtest
   baseline · **L** (the remediation's own deferred P1-8, reconfirmed still open) · *Impact:*
   implements the skill's stated primary decay signal (§1, "Compare: Expected vs Realized"),
   still entirely absent.
9. **Holding-period vs. `expected_half_life_seconds` axis.** `multi_horizon_attribution.py` ·
   **M**, downgraded from the prior audit's **L** now that per-trade `expected_half_life_seconds`
   provenance exists for SIGNAL-alpha trades (§3.4) · *Impact:* surfaces G16 half-life drift,
   at least for the SIGNAL-alpha population where the data now supports it.
10. **Fix the SKILL's Event Interface section.** `.cursor/skills/post-trade-forensics/SKILL.md`
    ("Event Interface") · **S** · state plainly that no forensics module publishes any event
    today (not even generic `Alert`), rather than implying `Alert` is the current fallback.
    *Impact:* removes a documentation claim that is fully aspirational, not partially-shipped.

### P2

11. **Reconcile the "mid-to-mid" documentation drift.** `cost_survival.py:51,65` +
    `.cursor/skills/post-trade-forensics/SKILL.md` (Data Sources section) · **S** · update both
    to match the corrected `trade_journal.py:60-74` BT-3 convention. *Impact:* removes a
    three-way documentation disagreement about the same field (§1 item 10, §4.3).
12. **Doc reconciliation for the architecture doc.**
    `docs/three_layer_architecture.md:824-838,1591-1602,1907` · **S** (unchanged from prior
    audit, still open) · downgrade IC / TC-drag / factor-bleed / rolling-30d-realized-IC claims to
    "design target" to match SKILL.md and the shipped code.
13. **Zero-historical-variance decay-detector corner case.** `decay_detector.py:178-179` · **S** ·
    either add a floor to `recent_se` (e.g. treat `hist_stdev == 0` as "insufficient variance to
    test" and skip) or accept the current epsilon-driven hypersensitivity with a documented
    rationale and a test. *Impact:* closes a narrow, low-probability false-positive path
    introduced by the P0-2 fix (§5.1).
14. **Crowding / microstructure detectors.** New module · **L** (unchanged from prior audit,
    still open) · implement the skill's §3 scorecard so `microstructure_metrics_breached` and
    genuine `crowding_symptoms` (not cost/decay tags) stop being fields nothing computes.
15. **Note the `test_decay_divergence.py` naming collision** in this mission's own prompt/context
    bundle (`docs/prompts/audit_forensics.md`) so a future re-audit doesn't read its "16 passed"
    as forensics decay-detector coverage (§1 item 14). *Impact:* process hygiene for the audit
    pipeline itself, not a code change.

---

## 10. Appendix — open questions needing data runs (or kernel-level verification)

1. **Empirical detector power, now that the statistic is fixed.** On cached APP/2026-03-26 fills
   (fixture at `test_cost_survival.py:_app_2026_03_26_fills`), inject synthetic decays of
   −25%/−50%/−75% into the recent-50 window and measure detection rate under the new
   `stdev/√n` denominator. This is the empirical counterpart to backlog item 5 and would give a
   concrete sensitivity curve instead of the single worked example in §5.1.
2. **Circuit-breaker spurious-flag rate in practice.** Run `evaluate_cost_circuit_breaker` +
   `validate_quarantine_trigger` together over a realistic multi-alpha fill window (or a
   generated distribution of "undercover"/"decay" scenarios) and measure what fraction of real
   QUARANTINE decisions get the "spurious-looking" WARNING. This would convert §6.2's branch-by-
   branch reasoning into a measured rate.
3. **Kernel micro-state ordering proof for `_regime_label_for`.** Trace (or add a targeted
   kernel/orchestrator test for) the exact guarantee that the regime engine's posterior read at
   fill-ack time cannot reflect information from later in the same synchronous tick than the
   fill itself — currently asserted by comment/design, not demonstrated by a test that would
   catch a future reordering regression (§3.3, §7).
4. **Per-mechanism realized-vs-disclosed on cached fills (methodology only, no code change).**
   Group APP/2026-03-26 fills by `TradeRecord.trend_mechanism` (now real provenance for
   SIGNAL-alpha trades) rather than the old intent-snapshot approximation, compute realized edge
   per mechanism with an LCB (`edge_calibration`-style), and compare to each alpha's disclosed
   `edge_estimate_bps`. This is the same proposal as the 2026-06-23 audit's appendix item 4, now
   more feasible because per-trade mechanism provenance genuinely exists rather than needing to
   be approximated.
5. **Aggregation-weighting sensitivity for `cost_survival`'s two "views."** On the same cached
   fills, compute both `net` (notional-weighted) and `mean_edge_bps/mean_cost_bps`
   (unweighted-mean) across a fleet with heterogeneous trade sizes, to quantify how much of their
   historical divergence (the "net-positive yet MARGINAL" cases in the existing test suite) is
   explained by size-weighting alone versus any residual effect — this would either fully confirm
   or partially refute §4.3's aggregation-effect explanation.
