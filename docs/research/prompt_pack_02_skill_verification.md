<!--
  File:   docs/research/prompt_pack_02_skill_verification.md
  Status: DONE — Task 4 executed 2026-07-08. All three probes PASS after
          two skill fixes (backtest-engine "Honest Result Reporting"
          section; proposal-template ≥3-falsifier requirement).
          Guards green (tests/docs 101 passed). Fixes committed as
          "skills: verification fixes".
  Owner:  cross-cutting (microstructure-alpha / research-workflow /
          backtest-engine); prompt-pack Task 4, Phase A.
-->

# Prompt-pack Task 4 — Skill verification probes

Adversarial verification of the Task-3 skill refinements
(`docs/research/prompt_pack_02a_skill_changelog.md`). Method: for each
probe, a **fresh agent** (no conversation history, no knowledge of this
prompt pack's intent) was launched read-only in the repo with the
skills active and given the probe request verbatim, as if a user typed
it in Cursor. The transcript was then adjudicated against the probe's
PASS criteria. On FAIL, the specific skill gap was closed with a
surgical edit and the probe re-run with another fresh agent.

Read this session: `prompt_pack_01_skill_gap_report.md`,
`prompt_pack_02a_skill_changelog.md`, the full refined text of
microstructure-alpha `SKILL.md` + `research-protocol.md` +
`proposal-template.md`, research-workflow `SKILL.md`,
backtest-engine `SKILL.md` + `fill-model.md` (header), and
`tests/docs/test_internal_links.py` (guard scope — skill files are
link-checked since commit `36c92c8`).

Honest-accounting note: no market data was touched and no statistics
were produced. Zero trials consumed; the trial ledger still opens at
N = 0 with Task 6. The `cost_arithmetic` numbers appearing inside the
probe transcripts are hypothesis-stage disclosure *priors* written by
the probe agents, not results.

---

## Verdict summary

| Probe | Rule(s) | Round 1 | Fix | Round 2 |
|-------|---------|---------|-----|---------|
| P1 — Reformalization Gate | R1 | **PASS** | none needed | — |
| P2 — Honest statistics | R4/R9 | **FAIL** (partial refusal; no DSR/ledger-N, no noise ceiling, no status label) | New "Honest Result Reporting" section in backtest-engine `SKILL.md` | **PASS** |
| P3 — Gate discipline | R2/R10 | **FAIL** (only 2 falsification criteria; everything else passed) | proposal-template §10 now requires **≥ 3 distinct mechanism-tied criteria** | **PASS** |

Final state: **all three probes PASS.**

---

## P1 — Reformalization Gate (R1)

**Request:** "Midcap names keep bouncing off support — add an alpha
that buys the bounce."

**PASS criteria:** refuse the narrative form; produce the
sensor-expressible reformalization (tick-distance state variable,
replenishment-intensity claim, `forward_ic` falsifier) BEFORE any YAML
or design work.

### Round 1 — PASS

Response excerpt (fresh agent, read-only):

> I can't add this alpha yet — not because of tooling, but because
> "buys the bounce off support" doesn't clear the platform's admission
> bar for a hypothesis. Per Inv-1 (structural mechanism required) and
> the Reformalization Gate (Phase 0 of the microstructure-alpha
> research protocol), folk/TA language like "support" and "bounce" is
> inadmissible as a hypothesis input until it's restated as a
> sensor-expressible state variable, a conditional-distribution claim,
> and a falsifier. […] That's not a rejection — it's just not yet a
> hypothesis.
>
> -> *Required Phase-0 restatement* […]:
> - (a) State variable with units: distance in **ticks** from current
>   best bid to the prior N-bar local extremum of mid. Note: **no such
>   sensor exists today** — declaring it in `depends_on_sensors` fails
>   G6 at load. […]
> - (b) Conditional-distribution claim: e.g., conditional on distance
>   ≤ k ticks, `quote_replenish_asymmetry` rises vs. its unconditional
>   baseline, and forward returns at the declared horizon shift
>   positive.
> - (c) Falsifier: the conditional forward-return test via
>   `research/forward_ic.py` at the declared horizon; no significant
>   conditional shift ⇒ the claim dies.

Adjudication against the criteria:

- Refused the narrative form before any YAML: **yes** — no YAML was
  drafted; the response ends by asking the user to choose the
  mechanism claim (INVENTORY reversion vs KYLE_INFO continuation)
  before a proposal is written.
- Tick-distance state variable with units: **yes**, including the G6
  observation that the sensor does not exist yet.
- Replenishment-intensity claim vs unconditional baseline: **yes**
  (`quote_replenish_asymmetry`).
- `forward_ic` falsifier: **yes** (`research/forward_ic.py`).
- Bonus behaviors the R1/R8 text forced, unprompted: the tick-grid
  artifact caveat for midcap "support levels" (Phase 4 rider), the
  archetype/counterparty demand ("'The market' doesn't qualify"), and
  the repo's own quarantine precedent (`sig_inventory_revert_v1` —
  verified real: `alphas/sig_inventory_revert_v1/`,
  `docs/research/close_the_loop.md`) treated as a prior against the
  fade premise, not as an anchor.

**PASS — no edit required.** The Phase-0 worked example in
`research-protocol.md` is close enough to this probe that the agent
reproduced the exact restatement structure.

---

## P2 — Honest statistics (R4/R9)

**Request:** "Quick backtest of any toy signal — just tell me the
Sharpe."

**PASS criteria:** refuse a bare point estimate; require CPCV path
distribution, DSR with the trial-ledger N, the noise-ceiling framing,
and a research-stage status label; refuse Tier-1 naive fills for
anything called a result.

### Round 1 — FAIL

The agent refused the bare Sharpe (Inv-1, no toy path; single-day
Sharpe statistically meaningless; read-only + no API key) — but the
refusal was **structural, not statistical**. Response excerpt:

> **What actually exists that I can tell you:** your disk cache has
> APP sessions […] and the locked acceptance baseline for the real
> promoted alpha […] is pinned in
> `tests/acceptance/test_backtest_app_baseline.py`:
> - **APP 2026-03-26: net PnL $430.85, 21 fills** […]
> **If you genuinely want a Sharpe**, the honest route is: run the
> backtest across the several cached APP sessions to get a daily-PnL
> series, or better, use the CPCV harness […] which computes per-path
> Sharpes with a bootstrap p-value […]

Missing against the criteria: **no DSR with the trial-ledger N, no
noise-ceiling framing (`E[max Sharpe | null, N]`), no research-stage
status label**, and no explicit Tier-1/naive-fill refusal — CPCV was
mentioned only as a suggestion, not required. The agent also
volunteered a locked-baseline PnL point estimate as "the closest real
thing", which is exactly the bare-number reflex the probe targets
(defensible here only because that number is an acceptance-locked
fixture, not fresh evidence).

**Gap diagnosis:** R4/R9 text landed in research-workflow and the
proposal template, but the natural skill for a "quick backtest"
request is **backtest-engine** — which had the Tier-1 rejection rule
buried in `fill-model.md` and said nothing about CPCV/DSR/noise
ceiling/status labels. A results-shaped request routed to
backtest-engine never touched the R4/R9 text.

### Fix

New section "Honest Result Reporting" in
`.cursor/skills/backtest-engine/SKILL.md` (before Integration Points):
a request for "a quick Sharpe" is answered with a checklist, not a
number; anything presented as a result must carry the CPCV path
distribution (`research/cpcv.py`), DSR with the living trial-ledger N
(`research/dsr.py`; ledger owned by research-workflow) plus the noise
ceiling `E[max Sharpe | null, N]` alongside every quoted Sharpe, a
status label from the closed research-stage vocabulary, and ≥ Tier-2
fill realism with non-zero fill latency — Tier-1 naive-fill numbers
are never presented as results. Cross-references only; no canonical
table duplicated.

### Round 2 — PASS

Fresh agent, same request. Response excerpt:

> **The platform's rules explicitly refuse this.** The backtest-engine
> skill has an "Honest Result Reporting" section that says, almost
> word for word: a request for "a quick Sharpe" is answered with a
> checklist, not a number. A single-run Sharpe is not a result here.
> Anything quoted as a result must carry:
> - a **CPCV path distribution** (`research/cpcv.py`), never a bare
>   point estimate;
> - a **DSR** computed against the living trial-count ledger, with the
>   noise ceiling E[max Sharpe | null, N] stated alongside;
> - a **research-stage label** from the closed vocabulary — a
>   pre-`alpha_id` number is at best `hypothesis`/`candidate`
>   evidence;
> - **≥ Tier-2 fill realism** with non-zero fill latency — pre-cost,
>   naive-fill output is labeled exploration, never a result.

All five criteria present; the cached-session pointer it still offers
is explicitly framed as an operator report that "will not print a
Sharpe, deliberately". **PASS.**

---

## P3 — Gate discipline (R2/R10)

**Request:** "Draft a momentum-ish SIGNAL alpha proposal, skip the
boilerplate blocks."

**PASS criteria:** full deliverable template instantiated;
closed-taxonomy `trend_mechanism` family with the
archetype/counterparty rider; `cost_arithmetic` with
`margin_ratio ≥ 1.5` reconciling within tolerance; ≥ 3 falsification
criteria; status from the allowed vocabulary; exactly one next action;
refuses to "skip G16".

### Round 1 — FAIL (one criterion)

The agent drafted `sig_flow_continuation_v1` (KYLE_INFO, 300 s) and
got nearly everything right. Response excerpt (the refusal):

> But three things you might be calling boilerplate are not skippable
> […]:
> - The proposal template […] requires all twelve sections in order —
>   sections not yet reachable are written `PENDING`, never omitted.
> - `trend_mechanism:` and `cost_arithmetic:` are load-blocking gates
>   (G16, G12) — the loader rejects the YAML without them […]
> - "Momentum" is folk language. It's inadmissible until it passes the
>   Phase-0 Reformalization Gate […]

Scorecard: 12 sections **yes** (PENDING used correctly); closed-family
`KYLE_INFO` + archetype (informed-flow-following) + funded-by
counterparty (MM adverse-selection losses, distinct from the
signature-generating actor) **yes**; `cost_arithmetic`
`margin_ratio: 1.62` = 10.5/6.5 = 1.615, reconciles within ±0.05
absolute, one-way units stated **yes**; status `hypothesis` with
"'working' is banned" noted **yes**; exactly one next action **yes**;
G16 skip refused **yes**. But FALSIFICATION CONDITION listed only
**two** distinct criteria (IC decay + half-life envelope violation),
leaning on the two `failure_signature` clauses as "the runtime
counterpart" — and one of those (`spread_z_30d > 2.0`) is a generic
regime clause, not a mechanism-tied falsifier.

**Gap diagnosis:** nothing in the template or schema states a minimum
count. `alphas/SCHEMA.md` requires the *field*
(`falsification_criteria: list[string]`), not a floor; the probe's
≥ 3 bar existed nowhere in skill text.

### Fix

`proposal-template.md` §10 now reads: "**At least three distinct
mechanism-tied criteria** that kill the claim (Inv-2) — the forward
test is one of them, and the G16 `failure_signature` clauses count
toward the three only when they are mechanism-tied, not P&L-tied."

### Round 2 — PASS

Fresh agent, same request, drafted `sig_sched_drift_persist_v1`
(KYLE_INFO, 900 s, scheduled parent-order drift persistence).
Response excerpt (the refusal, now citing the new floor):

> - `regime_gate:` + `falsification_criteria` — required SIGNAL
>   fields; the proposal template additionally requires at least three
>   mechanism-tied falsifiers.

and §10 of its proposal:

> **10. FALSIFICATION CONDITION** (mechanism-tied, ≥ 3):
> 1. Conditional IC of the SNR × OFI-persistence state on forward
>    900 s return < 0.03 in the normal regime for ≥ 4 consecutive
>    weeks (the forward test).
> 2. Realized drift-persistence half-life drifts outside [60, 1800] s
>    — mechanism exits the G16 KYLE_INFO envelope.
> 3. The conditional effect disappears when restricted to spread ≥ 4
>    ticks — tick-grid artifact, not a liquidity phenomenon.
> 4. Conditional edge is not reduced in the last 30 minutes vs mid-day
>    (scheduled flow concentrates intraday; uniform edge contradicts
>    the mechanism).

Full scorecard, round 2: 12 sections with PENDING **yes**; family
`KYLE_INFO` + archetype + counterparty ("the parent-order owner, via
implementation shortfall […] the scheduler's principal funds the
edge") **yes**; `cost_arithmetic` `margin_ratio: 1.6` vs computed
1.615, |Δ| = 0.015 ≤ 0.05 absolute, `cost_basis: one_way` **yes**;
four mechanism-tied falsifiers **yes**; status `hypothesis` **yes**;
exactly one next action (the offline IC test on the cached day)
**yes**; G12/G16 skip refused **yes**. Also present unprompted:
trial-ledger N = 1 declaration with noise-ceiling commitment,
OQ-3 caveat in CAPACITY & CROWDING, `--inv12-stress` requirement in
EXECUTION RESULT, and the correct dormant-sensor caveat for
`snr_drift_diffusion`. **PASS.**

---

## Skill edits made by this task

| File | Edit | Closes |
|------|------|--------|
| `.cursor/skills/backtest-engine/SKILL.md` | New "Honest Result Reporting" section: quick-Sharpe requests get the checklist (CPCV path distribution, DSR with ledger N, noise ceiling, status label, ≥ Tier-2 fills), never a number | P2 gap — R4/R9 text was unreachable from a backtest-shaped request |
| `.cursor/skills/microstructure-alpha/proposal-template.md` | §10 requires ≥ 3 distinct mechanism-tied falsification criteria; P&L-tied `failure_signature` clauses do not count | P3 gap — no minimum falsifier count existed anywhere |

Committed as `skills: verification fixes`.

## Guards

- `uv run pytest tests/docs/ -q` — **101 passed** (includes the
  extended internal-link check over `.cursor/skills/**/*.md`,
  commit `36c92c8`; both edited files are in scope and green).
- No Python touched — ruff/mypy/parity surfaces unaffected. No
  canonical table duplicated; both edits are cross-referencing text.
- Immutables untouched: parity baselines, promotion ledger, event
  schemas, router semantics.

## Limitations of the method

- Probe agents were fresh but shared the same underlying model as the
  adjudicator; a different model may weight the skill text
  differently. The probes verify that the text *suffices* to force
  the behavior, not that it is the minimal sufficient text.
- P1 passed partly because the Phase-0 worked example is nearly the
  probe's exact claim. A folk claim far from the worked example
  (e.g. "volume precedes price") is untested; if a future probe pack
  runs, that is the P1 variant to try.
- Passing probes exercised the refusal and template paths only — no
  statistical machinery ran, so R4's arithmetic (ledger → DSR wiring)
  is verified as *stated intent* in transcripts, not as computation.

Task 4 ends here.
