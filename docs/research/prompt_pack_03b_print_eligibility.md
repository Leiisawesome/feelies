<!--
  File:   docs/research/prompt_pack_03b_print_eligibility.md
  Status: NORMATIVE-WITH-OPEN-ROWS — condition-code semantics and the
          PRINT-ELIGIBILITY CONVENTION for the NEW candidate's sensors
          (Task FQ-5A, 2026-07-09). OQ-2 CLOSED, OQ-4 CLOSED (verdict
          DOUBLE-COUNT RISK YES, netting rule §4.4), OQ-6 CLOSED for all
          interpreted ids. Open rows (§7.3, vendor question text
          attached): quote condition id 34; live-WS cancel/correction
          dissemination (parity input to Task 12); the 2026-06-29 quote
          vocabulary shift (feeds OQ-3). Platform-wide DI-09 behavior is
          UNCHANGED by this doc.
  Owner:  data-engineering (semantics) / feature-engine (sensor
          eligibility); prompt-pack Task FQ-5A, Phase A.

  Provenance (FQ-3 template, Amendment B):
    git_sha: "23813ed5de1e7cbef27b32b0e5e6f65f4ece3c2f"
    worktree_clean: "no — pre-existing untracked research docs only
      (plans, rules, prompt_pack_03, prior conditions dump); no tracked
      file modified before this task"
    pythonhashseed: "0 (all scripted scans and the fetch)"
    env_check: "MASSIVE_API_KEY set (shell + `uv run python` os.environ
      both report set; key never echoed)"
    normative_inputs: prompt_pack_03_data_contract.md (§1 schemas, §2.1
      DI-09 ingest-everything, §2.4 cache inventory + first condition
      scan, §2.5 first conditions dump, §8 OQ-2/OQ-4/OQ-6),
      prompt_pack_00c_eval_canon.md (latency pins), platform-invariants
      (Inv-6 causality, Inv-11 fail-safe).
    artifact: docs/research/artifacts/massive_conditions_2026-07-09.json
-->

# Prompt-pack Task FQ-5A — Condition-code semantics and print eligibility

Scope guard, stated first: **everything below is a convention for the NEW
candidate's sensors only.** Platform-wide ingest behavior (DI-09: every
parseable print and quote becomes an event and feeds every existing sensor,
`prompt_pack_03_data_contract.md` §2.1) is unchanged — changing it would
touch locked parity baselines and every shipped alpha. Any NEW sensor
implements its own condition filter as an **explicit constructor/yaml
parameter** (default = the Class table of §3.3), so the filter is versioned
sensor state, not ingestion behavior. No forward-return computation was
performed in this task.

---

## 1. Reference-table artifact (step 1)

Fetched 2026-07-09 with the repository's own client construction —
`massive.RESTClient(api_key=...)` exactly as `ingestion/massive_ingestor.py:202`
builds it; base URL `https://api.massive.com` and Bearer-header auth come
from the SDK, nothing hardcoded. `GET /v3/reference/conditions?asset_class=
stocks&limit=1000`, paginated to completion via `next_url` (1 page, 94
rows). Raw vendor JSON preserved verbatim, sorted `(type, id)`:

**`docs/research/artifacts/massive_conditions_2026-07-09.json`** — the
`_provenance` block records endpoint, base URL, fetch date, git SHA, page
and row counts (never the key).

Vocabulary: 40 `sale_condition`, 33 `quote_condition`,
10 `financial_status_indicator`, 4 `short_sale_restriction_indicator`,
2 `market_condition`, 2 `settlement_condition`, 2 `sip_generated_flag`,
1 `trade_thru_exempt`.

**Supersedes the §2.5 dump.** Canonical diff against
`docs/research/massive_conditions_dump_2026-07-09.json` (same day, earlier
session): 9 sale-condition rows (ids 2, 7, 12, 13, 20, 22, 29, 32, 37)
carry a `FINRA_TDDS` key in `sip_mapping` in the raw fetch that the earlier
dump lacks. Cause: the earlier dump was round-tripped through the SDK's
typed `Condition` model, whose `sip_mapping` knows only CTA/UTP/OPRA —
typed-model lossiness, not vendor drift. All ids, names, types, and
`update_rules` are identical; every §2.5 conclusion survives. This task's
raw-JSON artifact is the authoritative copy for the unknown-id guard (§6).

---

## 2. Empirical prevalence — all seven usable cached sessions (PYTHONHASHSEED=0)

Direct JSONL read of every `~/.feelies/cache/APP/*.jsonl.gz` (the §2.4
inventory; 2026-03-21 is empty/weekend). Aggregate: **818,166 prints,
35,011,640 shares; 147,074 prints (17.98%) / 16,314,242 shares (46.60%)
carry no condition code at all** (plain regular-way trades).

Per-id aggregate (consolidated `update_rules` from the artifact: updates
volume / high-low / open-close). A print may carry several ids — id 41 is
`type: trade_thru_exempt`, an overlay flag that co-occurs with sale
conditions (e.g. `[14, 41]`, `[53, 41]`):

| id | name | vol/hl/oc | prints | % prints | shares | % vol |
|---|---|---|---|---|---|---|
| 37 | Odd Lot Trade | y/n/n | 604,131 | 73.84% | 4,926,665 | 14.07% |
| 41 | Trade Thru Exempt (overlay) | y/y/y | 258,164 | 31.55% | 10,960,979 | 31.31% |
| 14 | Intermarket Sweep | y/y/y | 233,220 | 28.51% | 6,150,396 | 17.57% |
| 12 | Form T / Extended Hours | y/n/n | 40,807 | 4.99% | 2,053,532 | 5.87% |
| 10 | Derivatively Priced | y/y/n | 23,575 | 2.88% | 445,148 | 1.27% |
| 2 | Average Price Trade | y/n/n | 5,086 | 0.62% | 458,105 | 1.31% |
| 22 | Prior Reference Price | y/y/n | 278 | 0.034% | 964,424 | 2.76% |
| 53 | Qualified Contingent Trade | y/n/n | 230 | 0.028% | 576,343 | 1.65% |
| 35 | Stock Option | y/y/y | 191 | 0.023% | 198,166 | 0.57% |
| 7 | Cash Sale | y/n/n | 26 | 0.003% | 30 | ~0% |
| 13 | Ext. Hours (Sold Out of Seq.) | y/n/n | 26 | 0.003% | 3,018 | 0.009% |
| 52 | Contingent Trade | y/n/n | 18 | 0.002% | 17,735 | 0.051% |
| 32 | Sold (Out of Sequence) | y/y/n | 16 | 0.002% | 142 | ~0% |
| 16 | Market Center Official Open | n/n/n | 14 | 0.002% | 420,011 | 1.20% |
| 9 | Cross Trade | y/y/y | 14 | 0.002% | 3,239,415 | 9.25% |
| 15 | Market Center Official Close | n/n/n | 14 | 0.002% | 3,167,302 | 9.05% |
| 17 | Market Center Opening Trade | y/y/y | 7 | 0.001% | 419,881 | 1.20% |
| 8 | Closing Prints | y/y/y | 7 | 0.001% | 2,819,534 | 8.05% |
| 29 | Seller | y/n/n | 5 | 0.001% | 3,333 | 0.010% |

Shape is stable across all seven sessions (37 is 70–74% of prints in each;
the §2.4 two-session scan generalizes). The striking count-vs-volume skew:
the auction/summary family {8, 9, 15, 16, 17} is 56 prints total but ~29%
of tape volume — a handful of enormous open/close crosses and their
official summary re-prints. Any volume-normalized sensor that ingests them
absorbs a session-scale volume shock from 5–10 events.

**Duplicate-print check (feeds OQ-4):** raw `trade_id` collisions are large
(e.g. 111,199 extra rows on 2026-03-26) but almost entirely cross-venue id
reuse; keyed `(trade_id, exchange)` they collapse to ~2.4k groups/session,
>99% on exchange 4 (FINRA TRF) where three TRF partitions (`trf_id`
201/202/203) run separate `trade_id` namespaces. Across all sessions the
full fingerprint `(sequence_number, trf_id, exchange_timestamp_ns)` never
repeats — **zero true duplicate prints outside the correction channel of
§4**.

---

## 3. OQ-2 — THE PRINT-ELIGIBILITY CONVENTION (trade-fed sensors of the NEW candidate)

### 3.1 What each sensor's mechanism actually needs

- **`hawkes_intensity`** proxies self-excitation of *aggressive order
  arrivals*: it needs prints whose SIP timestamp is causally close to a
  demand-arrival event. Late reports, averaged fills, and negotiated/
  derived executions carry reporting times, not arrival times.
- **`inventory_pressure`** proxies market-maker inventory via inferred
  aggressor side: it needs prints executed *against the displayed NBBO* so
  quote/tick-rule signing is meaningful.
- **OFI/Kyle trade legs** (`kyle_lambda_60s` signed flow; any new
  signed-flow leg): same signing requirement plus a contemporaneous
  price-impact relation — the print's price must be formed at the current
  market.
- **`vpin_50bucket`** orders volume into sequential toxicity buckets: late
  or out-of-sequence prints corrupt bucket *ordering*; auction/cross lumps
  flush multiple buckets with volume that is uninformed by construction.
- **`trade_through_rate`** compares print prices to the prevailing NBBO: it
  needs prices formed at the current market, but odd lots qualify — an
  odd-lot execution at/inside/through the NBBO is a real execution against
  the book even though the SIP excludes it from high/low summaries.

### 3.2 Verdict matrix — (id × sensor)

INC = include, EXC = exclude, DW = down-weight (include with reduced or
separately-binned weight; the concrete weight is a Task-7 spec decision and
one trial in the N-ledger if varied). "no-cond" = prints with an empty
`conditions` tuple.

| id | hawkes_intensity | inventory_pressure | OFI/Kyle legs | vpin_50bucket | trade_through_rate | rationale (mechanism-tied) |
|---|---|---|---|---|---|---|
| no-cond | INC | INC | INC | INC | INC | Regular-way, in-sequence, at-market. |
| 37 Odd Lot | INC | INC | INC | INC | INC | Real arrivals against the book (73.8% of prints — excluding them starves every window); SIP h/l-ineligibility concerns summary stats, not execution reality. |
| 14 ISO | INC | INC | INC | INC | INC | Sweep = maximal aggression; exactly the signal these sensors proxy. |
| 41 TTE (overlay) | INC | INC | INC | INC | INC | Exemption flag, not an execution type; eligibility is decided by the co-occurring sale condition. |
| 12 Form T | INC* | DW | DW | DW | DW | In-sequence real executions, but outside RTH: thin one-sided books make signing and NBBO comparison unreliable, and VPIN toxicity semantics are an RTH concept. *Arrival times are genuine, so intensity keeps them; entries are RTH-gated downstream anyway. |
| 10 Derivatively Priced | EXC | EXC | EXC | EXC | EXC | Price derived from another market/reference, typically negotiated; report time ≠ demand arrival, price not formed at current NBBO. |
| 2 Average Price | EXC | EXC | EXC | EXC | EXC | Administrative benchmark fill of an earlier parent; carries no arrival-time or price-formation information. |
| 22 Prior Reference Price | EXC | EXC | EXC | EXC | EXC | Priced off an earlier reference — late by definition (0.03% of prints yet 2.8% of volume: single large blocks; a lethal outlier for volume-normalized state). |
| 32 / 13 Sold Out of Seq. | EXC | EXC | EXC | EXC | EXC | Explicitly out-of-sequence: timestamp is reporting time; distorts VPIN bucket ordering and Hawkes inter-arrival times. |
| 29 Seller / 7 Cash Sale | EXC | EXC | EXC | EXC | EXC | Non-regular-way settlement; negotiated, no aggressor semantics. |
| 53 QCT / 52 Contingent | EXC | EXC | EXC | EXC | EXC | Legs of multi-instrument packages; execution is contingent on the other leg, not on equity-book demand. |
| 35 Stock Option | EXC | EXC | EXC | EXC | EXC | Legacy option-related print; same contingency argument. |
| 9 Cross / 8 Closing / 17 Opening | EXC | EXC | EXC | EXC | EXC | Auction/negotiated crosses: scheduled or matched liquidity, no aggressor, no arrival clustering; 9.3%/8.1%/1.2% of volume in ≤14 prints each would flush VPIN buckets spuriously. |
| 15 / 16 MC Official Close/Open | EXC | EXC | EXC | EXC | EXC | Summary re-prints — do not even update consolidated volume (n/n/n); pure double-count if ingested. |

### 3.3 The convention, operationally

For any NEW trade-fed sensor of the candidate:

1. **Class A (include):** empty-`conditions` prints and ids {37, 14},
   with 41 as a pass-through overlay. Id 12 per the DW column (sensor
   parameter decides include/down-weight; the choice is pre-registered in
   Task 7 and counted in N if varied).
2. **Class B (exclude):** ids {2, 7, 8, 9, 10, 13, 15, 16, 17, 22, 29,
   32, 35, 52, 53}.
3. **Correction netting (from §4):** drop rows with
   `correction ∈ {10, 11, 12}` before anything else.
4. Filter = explicit sensor parameter (`eligible_conditions` /
   `excluded_conditions` + `drop_correction_records`), recorded in the
   sensor's version metadata. Unknown ids at runtime → the §6 guard, not a
   silent include.

**Measured pass-through** of Class A (with 12 included, before DW):
**96.96% of prints, 74.32% of volume** — the convention discards almost no
arrival information while removing the auction/late/derived volume lumps
that are 25% of shares in <0.1% of prints.

Consistency note: this does **not** contradict §2.5's "ingest-everything is
correct for flow sensors" — that finding concerned SIP consolidated-volume
semantics and the *existing* sensors, which keep DI-09 behavior untouched.
This convention is the hypothesis-level filter decision §2.5 explicitly
deferred to the candidate.

---

## 4. OQ-4 — Cancel/correction semantics. VERDICT: DOUBLE-COUNT RISK **YES** (bounded, netting rule below)

### 4.1 Vendor semantics

The conditions vocabulary contains **no cancel/bust/error sale condition**
(§2.5, re-confirmed on the fresh artifact) — the only channel is
`Trade.correction`. Vendor/NYSE modifier semantics (Massive
conditions-indicators glossary, checked 2026-07-09): `0/None` regular;
`1` original later corrected; `7` original later marked erroneous;
`8` original later cancelled; `10` cancel record (follows 8); `11` error
record (follows 7); `12` correction record (follows 1).

### 4.2 Empirical corroboration (all sessions)

Historical REST **delivers both the original and the follow-on row** — it
does not net out:

- Every session except 2026-06-29 contains matched pairs sharing
  `(trade_id, exchange, sequence_number)`: an original stamped
  `correction=8` and a cancel record stamped `correction=10` arriving 6–33
  minutes later at its own `exchange_timestamp_ns` (e.g. APP 2026-03-26
  `trade_id=62506`: 8-row at 14:22:21 ET, 10-row at 14:55:06 ET, same
  price/size). 2026-03-26 additionally has one corrected pair
  (`correction=1` then `correction=12`, `trade_id=56`, prices 395.885 →
  395.855, 5,000 shares).
- Prevalence: 15 follow-on rows ({10, 12}) and 15 flagged originals
  ({1, 8}) in 818,166 prints (~0.004%); most cancelled originals are
  odd-lot size-0 prints. No `7/11` observed.
- No other duplicate-print signature exists (§2 fingerprint check), so the
  correction channel is the *only* double-count path.

### 4.3 Causality trap (Inv-6), stated explicitly

The `correction=1/7/8` flag on the original row is **retroactive** — the
vendor edits the historical row after the fact. At the original print's
timestamp that flag is future information. A causal sensor must NOT
condition on `correction ∈ {1, 7, 8}` at arrival time (that would be
lookahead a live feed cannot reproduce); those rows are ingested as normal
prints, exactly as they printed in real time.

### 4.4 The netting rule (joins the §3.3 convention, rule 3)

Drop rows with `correction ∈ {10, 11, 12}` — the follow-on bookkeeping
records, which arrive at their own later timestamps and are causally
droppable. Accept that cancelled originals remain in sensor state (they
were real information at print time; ~0.002% of prints). Economically
negligible on this cache, structurally sound, and live-reproducible **iff**
the WS feed disseminates equivalent records — which is the surviving
vendor question (§7.3 row 2, a Task-12 parity input).

---

## 5. OQ-6 — Quote condition/indicator semantics

### 5.1 New empirical fact: the 2026-06-29 vocabulary shift

Six of seven sessions (2026-03-20 → 2026-06-03) show quote conditions
`{1 dominant; 2, 19, 82 tail}` and indicator `{1}` on ~94–96% of quotes.
**2026-06-29 is different**: conditions almost always empty (only
`{15: 2, 34: 2, 82: 2}` on 54,748 quotes) and indicators from a new set
`{604: 43,376; 602: 11,369; 502: 553; 501: 292; 503: 88; 603: 2}`. The
vendor changed which condition/indicator fields it populates somewhere
between the 2026-06-03 and 2026-06-29 sessions. This is direct evidence
that id vocabularies are **not stable across sessions** — the §6 guard is
mandatory, and it feeds OQ-3 (dissemination changes post-2026-04-27).

### 5.2 Interpretation per observed id

Quote **conditions** (artifact rows unless noted):

| id | vendor definition (quoted) | non-firm / indicative / non-tradeable? | prevalence |
|---|---|---|---|
| 1 | "Regular Two-Sided Open" (UTP R / CTA R) | No — the normal firm state | ~99.97% of quotes, pre-06-29 sessions |
| 2 | "Regular One-Sided Open" (UTP Y, nbbo) | No — firm but one side of the NBBO may be absent (2 of 104 observed rows have a zero side) | ≤0.03%/session |
| 19 | "Market Maker Quotes Closed" (CTA L, bbo) | Not non-firm; a closed-MM state — 14 of 52 observed rows are one-sided; effectively out-of-session records | ≤0.04%/session |
| 15 | "Closed" (UTP L) | Session-closed placeholder: `bid=ask=0`, sizes 0 | 2 rows, 06-29 only |
| 82 | "SIP Generated" (`sip_generated_flag`, UTP E) | No — SIP-originated record, prices firm | 2 rows/session |
| 34 | **NOT IN VOCABULARY** — observed on 2 one-sided 04:00:00 ET session-opening rows on 06-29 (`bid=0`, ask firm, indicator 604) | **UNKNOWN** | 2 rows |

Quote **indicators** — none of the observed ids {1, 501, 502, 503, 602,
603, 604} appear in the `/v3/reference/conditions` vocabulary (it carries
only SSR 57–60 and financial-status 62–71 for the indicator families).
Interpretation from the vendor's Conditions & Indicators glossary (checked
2026-07-09): `601 NBBO_NO_CHANGE`, `602 NBBO_QUOTE_IS_NBBO`,
`603 NBBO_NO_BB_NO_BO`, `604/605 NBBO short/long appendage`,
`501/502/503 retail interest on bid/ask/both (NYSE RPI)`. These are NBBO
bookkeeping and retail-interest annotations — none marks a non-firm or
indicative quote. The long-standing **indicator id 1** (§2.5 residual) is
now interpreted with medium confidence: it matches the CTA *legacy numeric*
National BBO Indicator `'1'` = "quote contains Best Bid and Best Offer —
the quote is itself the NBBO" (NYSE Daily TAQ spec, Appendix G: modern `G`
"formerly '1'"), which is exactly the semantics of `602
NBBO_QUOTE_IS_NBBO` that replaces it wholesale in the 06-29 session at the
same ~80–95% prevalence. Uniform, non-discriminating, benign either way.

`20 Non-Firm` exists in the vocabulary (CTA N / UTP N) and was **never
observed** in any cached session.

### 5.3 Consequences

**(a) Spread/micro-price/imbalance sensors:** every *interpreted* observed
id is benign — no indicative or non-firm quotes reach sensor state. The
real hazards are (i) zero-sided/closed records (36 quotes across the whole
cache; `micro_price`/`book_imbalance` already go cold on zero depth, §5.1
of the data contract) and (ii) the vocabulary instability of §5.1 —
condition-based quote filtering in any NEW sensor must be
presence-tolerant (empty `conditions` is the normal case on 06-29-style
sessions) and backed by the §6 guard.

**(b) Fill simulation (Task 12 precondition):** on the six pre-06-29
sessions, all quotes fillable under RTH gating carry firm two-sided
condition 1 — fill simulation is **not** trading against known-indicative
quotes; explicitly: vendor definitions quoted in §5.2 for each id, none
marks non-firmness. On 2026-06-29 the same holds for every interpreted id,
**but the session carries uninterpreted quote condition 34** → under the §6
guard, 2026-06-29 is flagged UNKNOWN-ID and is inadmissible for evidence
(including fill-sim-dependent evidence) until id 34 is interpreted (vendor
question, §7.3 row 1). Both id-34 rows sit at 04:00 ET with a zero bid, so
the practical fill-sim exposure inside RTH is nil — but admissibility is a
rule, not a judgment call.

---

## 6. UNKNOWN-ID GUARD + UNITS-SANITY SPEC (Task-9 test-plan amendment; no implementation now)

Defends OQ-3 and any future data source/path. Both checks are per-session,
deterministic, offline (direct cache read, PYTHONHASHSEED=0), run at
session pre-registration and re-run before evidence aggregation. Failure →
session flagged, **inadmissible for evidence** until dispositioned; never a
runtime/tick-path change (Inv-11: unknown states reduce what we trust, not
what we trade).

**(a) Unknown-id validation.** For each cached (symbol, date): collect the
session's observed id sets — trade `conditions`, quote `conditions`, quote
`indicators`, plus distinct `Trade.correction` values. Assert each is a
subset of the INTERPRETED TABLE = (ids in
`artifacts/massive_conditions_2026-07-09.json`) ∪ (glossary indicator ids
{1, 501–509, 601–605, 901–908} as interpreted in §5.2; **id 2 added by
FQ-5B**, `prompt_pack_03c_universe_and_cache.md` §6.2 — legacy UTP
numeric NBBO-appendage indicator, medium confidence, vendor question
§7.3 row 4) ∪ (correction
values {None, 0, 1, 7, 8, 10, 11, 12}). Any excess id → flag
`UNKNOWN-ID(<field>, <id>)`. Acceptance: the seven §2.4 sessions produce
exactly one flag — quote condition 34 on APP/2026-06-29 (the guard's
known-answer test). A newly interpreted id enters the table only by
updating this doc (or its successor) with a vendor definition, never by
whitelisting in test code.

**(b) Units-sanity check (the OQ-1 failure signature, defensively).** For
each session and side: let `S` = nonzero displayed quote sizes, `L` = the
symbol's MDI round lot (APP: 40). Flag `UNITS-SUSPECT` if
`median(S) < L` (share-denominated NBBO sizes cannot have a sub-lot
median; a lots-denominated feed would have median ≈ 1–2), or if the
share-unit divisibility baseline breaks: cached baseline is
`100% of S divisible by L` with `median(S) = 2L` (80 shares) and
`p10 = L` — a session whose `S` is dominated by small integers indivisible
by `L` matches lots units or a unit regression. Both thresholds cite the
measured baseline (§2 scan: `frac_mod40 = 1.0`, `frac_lt40 = 0.0`,
p10/p50/p90 = 40/80/160–200 on every session). Round-lot reassignments are
semiannual scheduled boundaries (data contract §4 note) — `L` is a lookup
per (symbol, effective date), not a constant.

---

## 7. CLOSE-OUT

### 7.1 Disposition updates

The OQ-2/OQ-4/OQ-6 rows in **`prompt_pack_03_data_contract.md` §8** are
updated this task (OQ-2 → convention here; OQ-4 → CLOSED, verdict YES +
netting rule; OQ-6 → CLOSED for interpreted ids, id-34 open row). Note:
`prompt_pack_00_architecture_verification.md` §(e) also has rows labelled
OQ-2/OQ-4/OQ-6, but those are the *Task-1* questions (edge-units
convention, fill latency, realism profile) — unrelated namespace,
deliberately untouched.

### 7.2 AMENDMENTS for downstream tasks

- **Task 6 (hypothesis cards):** any trade-fed candidate cites this doc's
  §3.3 convention as a data requirement — status **met** (verdict matrix
  §3.2, netting rule §4.4). Cards inheriting volume-normalized state must
  note the §2 count-vs-volume skew (29% of volume in 56 auction/summary
  prints) as the concrete hazard the convention removes.
- **Task 7 (formal spec):** the observable-state section applies the
  filters explicitly: eligible-condition classes, the id-12 DW decision
  (pre-registered; a varied weight is one N-ledger trial), and
  `drop_correction_records={10,11,12}` — all as named sensor parameters
  with the §4.3 causality note (no conditioning on retroactive
  `correction ∈ {1,7,8}`).
- **Task 9 (test plan):** §6(a) unknown-id guard and §6(b) units-sanity
  check join the plan verbatim, with the known-answer expectations stated
  there (exactly one UNKNOWN-ID flag on the current cache: quote condition
  34 @ APP/2026-06-29; zero UNITS-SUSPECT flags).
- **Task 12 (fill-sim trust):** the OQ-6 verdict (§5.3(b)) is a
  precondition input: fill simulation against the six pre-06-29 sessions
  is clean on the firmness axis; APP/2026-06-29 is inadmissible until id
  34 is interpreted; the live-WS cancel-dissemination question (§7.3 row
  2) must be answered before the §4.4 netting rule is claimed
  backtest/live-parity-safe.

### 7.3 OPEN ROWS — vendor-support question text (for Lei)

1. **Quote condition id 34 (blocks APP/2026-06-29 admissibility).**
   > "On 2026-06-29, `/v3/quotes` for APP returned two records at
   > 04:00:00 ET with `conditions: [34]` (one-sided: bid 0, firm ask,
   > indicator 604). `/v3/reference/conditions?asset_class=stocks` contains
   > no id 34 for quote data types. What does quote condition 34 denote,
   > and why is it absent from the reference endpoint?"
2. **Live-WS cancel/correction dissemination (Task-12 parity input).**
   > "Historical `/v3/trades` delivers cancelled/corrected trades as two
   > rows: the original retroactively stamped `correction` 1/7/8 and a
   > follow-on record stamped 10/11/12 at the later report time. On the
   > real-time stocks `T` WebSocket channel, are cancel/error/correction
   > records disseminated at all, and if so with which `correction`
   > values? We need to know whether a `correction ∈ {10,11,12}` drop rule
   > behaves identically on WS and REST."
3. **Quote condition/indicator population change ~late June 2026 (joins
   the standing OQ-3 question).**
   > "Sessions up to 2026-06-03 return quote `conditions: [1]` and
   > `indicators: [1]` on ~94% of NBBO records; the 2026-06-29 session
   > returns mostly empty `conditions` with `indicators` from the
   > 501–604 glossary set (602/604 dominant). Did the dissemination or
   > population semantics of these fields change in June 2026, and is the
   > change documented anywhere? Is `indicators: [1]` on older sessions
   > the legacy CTA numeric National BBO Indicator ('1' = quote is itself
   > the NBBO, modern 'G'/602)?"
4. **Quote indicator id 2 (added by Task FQ-5B, 2026-07-10 — interpreted
   with medium confidence and admitted to the interpreted table in
   `prompt_pack_03c_universe_and_cache.md` §6.2; confirmation wanted).**
   > "On 2026-01-27 and 2026-04-22, `/v3/quotes` for PCTY returned three
   > 09:30:00 ET records with `indicators: [2]` (wide, 300×300, two
   > flagged SIP-generated). Is quote indicator 2 the legacy UTP numeric
   > National BBO Indicator ('2' = short-form NBBO appendage), as
   > indicator 1 is the legacy CTA numeric? Which glossary id replaces
   > it going forward?"

A platform-wide session-admissibility guard (extending §6 beyond the new
candidate's evidence pipeline to all ingest) is argued for by the §5.1
vocabulary shift but touches data-integrity behavior shared by every
shipped alpha — logged as a backlog entry in `prompt_pack_backlog.md`
(entry 5), not acted on here.

**Task FQ-5A complete. §3.3 + §4.4 are the PRINT-ELIGIBILITY CONVENTION
(normative for the new candidate's sensors); §6 is the Task-9 amendment;
§7.3 rows are the open vendor questions.**
