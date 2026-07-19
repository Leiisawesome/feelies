<!--
  File:   docs/research/prompt_pack_03_data_contract.md
  Status: VERIFIED — data contract + sensor vocabulary audited against source
          2026-07-08 (Task 5). Read-only audit; no code changed. The
          L2-INFORMATION-LOSS BASELINE LEDGER (§7) is MANDATORY INPUT to
          every Task-6 hypothesis. Massive dissemination-spec items that
          could not be verified from this environment are OPEN QUESTIONS
          (§8), per Amendment C — nothing is marked verified from memory.
          Addendum 2026-07-09: authenticated /v3/reference/conditions dump
          executed (§2.5) — OQ-2 and OQ-6 resolved, OQ-3/OQ-4 narrowed.
          Task FQ-5A (same day, prompt_pack_03b_print_eligibility.md):
          OQ-4 CLOSED (double-count risk YES, netting rule), OQ-6 CLOSED
          for interpreted ids (new open id: quote condition 34), OQ-2
          convention issued for the new candidate's sensors.
          Task FQ-5B (2026-07-10, prompt_pack_03c_universe_and_cache.md):
          OQ-1 RESOLVED (live WS sizes = SHARES), OQ-3 upgraded to
          CHANGED-CONFIRMED/UNKNOWN CAUSE with the post-2026-04-27
          inadmissibility rule, OQ-5 RESOLVED (80-cell evidence grid
          cached); §8 ids are task-prefixed T5-OQ-n from now on.
  Owner:  data-engineering (contract) / feature-engine (sensor vocabulary);
          prompt-pack Task 5, Phase A.

  Provenance (FQ-3 template, Amendment B):
    git_sha: "23813ed5de1e7cbef27b32b0e5e6f65f4ece3c2f"
    worktree_clean: "yes (git status --porcelain empty at start of task)"
    pythonhashseed: "0 (set for the cache condition-code scan in §2.4)"
    normative_inputs: prompt_pack_00b_edge_units_convention.md (edge units),
      prompt_pack_00c_eval_canon.md (realism knobs + latency pins),
      prompt_pack_00_architecture_verification.md (tick path, router
      latency gating, guard inventory).
-->

# Prompt-pack Task 5 — Data contract and sensor vocabulary audit

What a hypothesis may assume, verified from code (not docs). Line numbers are
1-based against the SHA above; treat cited symbols as primary. Where
`prompt_pack_00c_eval_canon.md` (hereafter **00c**) already pinned a value,
this doc cites it instead of restating; likewise `prompt_pack_00b_…` (**00b**)
for edge units and `prompt_pack_00_…` (**00**) for tick-path wiring.

---

## 1. Event fields and the timestamp story

### 1.1 Schemas

`NBBOQuote` (`core/events.py:60-90`): `bid`/`ask: Decimal`,
`bid_size`/`ask_size: int`, `bid_exchange`/`ask_exchange: int` (quote-setting
venue ids only — not depth), `exchange_timestamp_ns: int` (required),
`conditions: tuple[int, ...] = ()`, `indicators: tuple[int, ...] = ()`,
`sequence_number` (vendor, per-symbol, resets daily), `tape`,
`participant_timestamp_ns / trf_timestamp_ns: int | None`,
`received_ns: int | None`.

`Trade` (`core/events.py:93-116`): `price: Decimal`, `size: int`, `exchange:
int`, `trade_id`, `exchange_timestamp_ns` (required), `conditions`,
`decimal_size`, `sequence_number`, `tape`, `trf_id`, `trf_timestamp_ns`,
`participant_timestamp_ns`, `correction: int | None`, `received_ns`.

**No aggressor-side flag exists on `Trade`** — L1 SIP data does not
disseminate it; any signed-flow quantity is inferred downstream (see §7 row
L6). There is no depth beyond the single BBO level on `NBBOQuote` (§7 row L1).

### 1.2 Which timestamp is which

| Field | Source | Consumed by |
|---|---|---|
| `timestamp_ns` | Set **equal to** `exchange_timestamp_ns` by the normalizer on every market event (WS: `massive_normalizer.py:414, 467` quotes / `:496, 534` trades; REST: `:604, 649` / `:678, 713`) | Everything on the tick path: sensors, scheduler, features, signals |
| `exchange_timestamp_ns` | Massive's **SIP receipt timestamp** — WS field `t` (Unix **ms**, ×1e6 at `massive_normalizer.py:414, 496`); REST field `sip_timestamp` (Unix **ns**, verbatim at `:604, 678`). Vendor doc: "timestamp of when the SIP received this quote from the exchange" (massive.com REST /v3/quotes field table, checked 2026-07-08) | EventLog ordering, horizon boundaries, RTH/MOC gates, router fill eligibility |
| `participant_timestamp_ns` | Exchange-generation time (WS keys `participant_timestamp`/`ft`, `:434-438`; REST `:626-627`) | **Nobody** — provenance + dedup fingerprint only (repo grep: no consumer outside the normalizer/serializer) |
| `trf_timestamp_ns` | TRF receipt time (`:439-443, 507-508, 629-630`) | Nobody (same) |
| `received_ns` | Normalizer's injected `Clock` at frame receipt: per-frame wall time live (`massive_ws.py:393-396`); **static per batch** on REST ingest (`massive_ingestor.py:431`, `SimulatedClock` does not advance — `core/events.py:68-74`) | Nobody on the tick path; backtests **cannot** derive ingest latency from it |
| `Trade.correction` | REST/WS `correction` field (`:515-516, 701`) | **Nobody** — corrected/cancelled prints are ingested like any other print (see OQ-4) |

**Contract: the entire pipeline keys on SIP exchange time.** Specifically:

1. **EventLog order** — canonical merge key `(exchange_timestamp_ns, symbol,
   type_rank[quote=0 < trade=1], sequence)` (`storage/event_resequence.py:33-43`);
   `ReplayFeed` raises `CausalityViolation` on regression
   (`ingestion/replay_feed.py:84-99`).
2. **Decision-clock visibility** — `ReplayFeed` advances the `SimulatedClock`
   to `exchange_timestamp_ns + market_data_latency_ns` **before** yielding
   (`replay_feed.py:29-34, 100-107`); this is the only place
   `market_data_latency_ns` enters (00 §(a) execution table, fill-latency
   row). Pinned at 20 ms — cite 00c §1, do not restate.
3. **Horizon boundaries** — `HorizonScheduler` computes
   `boundary_index = (event.timestamp_ns − session_open_ns) // (h·1e9)`
   (`sensors/horizon_scheduler.py:201-212`), i.e. boundaries are anchored on
   **exchange time**, not visibility time; `boundary_ts_ns` is the exact
   nominal grid anchor (`:304, 313-327`; `core/events.py:606-615`).
4. **Fill eligibility** — routers key on the quote's exchange timestamp:
   deferral deadline `max(clock.now_ns() [= visibility time],
   quote.exchange_timestamp_ns) + backtest_fill_latency_ns`, fill against the
   first quote with `exchange_timestamp_ns ≥ deadline`
   (`execution/backtest_router.py:273, 301-309, 325, 359-360`; passive
   equivalents cited in 00 §(a)). RTH and MOC gates likewise test
   `quote.exchange_timestamp_ns` (`backtest_router.py:259-270`). Latency pins
   and the zero-latency prohibition: 00c decisions (A)/§1.
5. **Cost/edge units** at the fill boundary follow the **one-way (per-fill)
   convention** of 00b — this doc adds nothing to that derivation and any
   cost figure quoted downstream of this contract is one-way unless
   explicitly derived round-trip (00b, THE CONVENTION).

**Replay-vs-live timestamp asymmetry (flag for Task 12):** WS timestamps are
ms-resolution (×1e6 → ns grid of 10⁶), REST/cached timestamps are true ns.
Live data therefore has far more exact-timestamp ties (broken by the merge
key above), and live `sequence`/`correlation_id` values are **not** expected
to match a replay of the same session unless live applies the identical
resequence policy (`event_resequence.py:15-18`). `IdleTick` exists only on
live feeds and never reaches bus/log (`ingestion/idle_tick.py:10-18`).

---

## 2. Normalizer behavior, data-integrity SM, cache provenance

### 2.1 What is included / excluded (`ingestion/massive_normalizer.py`)

**Included: everything parseable.** There is **no condition-code, indicator,
odd-lot, venue, or session filtering at the ingestion boundary** — every
quote update and every trade print that parses becomes an event, with
`conditions`/`indicators` preserved verbatim (by design, audit DI-09; 00 §(a)
event-contract table, `Trade` row). The only runtime consumers of condition
codes are the halt classifier (BT-5: trade-tape codes,
`massive_normalizer.py:530, 933-961`; `ingestion/data_integrity.py:69-88`)
and the SSR trigger (BT-6: `kernel/orchestrator.py:6494`) — both **inert on
the reference config** (empty code lists, 00c §1 regulatory table).
Consequence: **trade-fed sensors consume irregular prints** (odd lots,
late/out-of-sequence reports, average-price prints, whatever the tape
carries) — quantified empirically in §2.4, decoded against the vendor
condition vocabulary in §2.5 (residual correction-row question: OQ-4).

**Excluded / dropped (each with anchor):**

| Drop | Anchor |
|---|---|
| Frames > 16 MB (pre-parse cap) | `massive_normalizer.py:250-254, 315-323` |
| Unparseable JSON / RecursionError | `:324-329` |
| Non-dict WS array elements; WS events other than `ev∈{Q,T}` (status frames silently ignored) | `:385-402` |
| NaN/Inf/negative prices; zero **trade** price (`allow_zero=False`); zero bid/ask allowed (auction/indicator quotes carry `bid=0`/`ask=0` legitimately) | `:43-77, 449-450, 518, 632-633, 696` |
| Negative sizes (zero size allowed) | `:80-92` |
| WS exchange timestamps outside [now−30 d, now+1 h] (ms-vs-ns wire-bug guard; wall-clock-like clocks only; **REST paths exempt** — historical backfill) | `:256-261, 743-772, 415, 497, 605-613` |
| Exact duplicates: same vendor `sequence_number` + same content fingerprint | `:850-875` |
| Sequence reuse with **different** payload → drop + `CORRUPTED` | `:876-883` |
| Field-level parse failure → drop + `CORRUPTED` for that symbol | `:486-489, 554-557, 668-671, 732-735` |
| REST record whose returned `ticker` ≠ requested symbol (ingestor defense) | `ingestion/massive_ingestor.py:554-564` |
| Ambiguous REST record with both quote and trade keys → classified as quote, trade side dropped (WARN once) | `:574-597` |

**Gap detection:** per `(symbol, feed-channel)` on vendor sequence numbers —
`seq > prev+1` → `GAP_DETECTED`, contiguous next → back to `HEALTHY`
(`:885-920`); WS feed disconnect → `GAP_DETECTED` for all symbols
(`:992-1006`). REST gap detection is **off by default** (historical rows are
thinned; `enable_rest_sequence_gap_detection: false`, `platform.yaml:38-39`,
`massive_normalizer.py:292-295`).

**Ingest window:** the REST backfill requests `T00:00:00Z–T23:59:59Z`
(`massive_ingestor.py:471-478`) — cached sessions therefore contain
**pre-market and after-hours** quotes/prints. Nothing in ingestion trims to
RTH; RTH discipline is enforced at the entry-fill layer only (§3), and
sensors run on the full tape.

### 2.2 Massive dissemination-spec check (Amendment C)

Checked against Massive's **public** documentation on 2026-07-08 (REST
`/v3/quotes` + `/v3/trades` field tables, WS `stocks/Q` field table,
flat-files quotes page, `/v3/reference/conditions` endpoint description).
Findings:

1. **Quote sizes — shares vs round lots (DATA-INTEGRITY FINDING, OQ-1).**
   Massive's flat-file/REST docs state sizes are **round lots before
   2025-11-03 and direct shares on/after** (SEC MDI rule; UTP vendor alert
   2025-10). All cached sessions are 2026 → REST-ingested sizes are
   **shares**. Empirical confirmation: cached APP quote `bid_size`
   percentiles p10/p50/p90 = 40/80/160–200 — multiples of 40, consistent with
   MDI share units rounded to APP's assigned 40-share round lot
   ($250.01–$1,000 price tier), and impossible under lots-of-100 semantics.
   **However Massive's current WS doc still describes `bs`/`as` as "number of
   round lot orders."** The normalizer applies **no unit conversion on either
   path** (`massive_normalizer.py:451-452, 634-635`). If the WS doc reflects
   live dissemination (rather than being stale), live sizes would be lots
   while backtest sizes are shares — a ×round-lot backtest/live divergence in
   every depth-consuming path (through-fill size cap, walk-the-book impact,
   `book_imbalance`, `ofi_ewma` depth normalization). Unresolvable from this
   environment → **OQ-1**.
2. **Condition-code semantics.** The unified condition-id table lives behind
   `GET /v3/reference/conditions` (auth required) and includes per-SIP
   mappings and update-rule flags ("how conditions affect high/low/volume").
   The platform ingests all prints regardless (§2.1). *Resolved 2026-07-09:*
   the authenticated dump was executed and decoded against the §2.4
   empirical distribution — see §2.5 (OQ-2 closed, OQ-6 closed except the
   quote-`indicators` id-1 residual).
3. **Odd-lot quote dissemination (effective 2026-04-27).** The SIPs now
   disseminate odd-lot quotes / BOLO (SEC MDI; UTP alert 2025-18; dxFeed
   notice). Odd-lot quotes do **not** affect the NBBO. The platform assumes
   every `NBBOQuote` is the NBBO. Whether Massive's `Q` WS channel and
   `/v3/quotes` remain NBBO-only after 2026-04-27 needs vendor confirmation.
   Weak in-repo evidence of no contamination: the June-2026 cached sessions
   show the **same** quote condition/indicator distribution as March-2026
   (condition 1 + indicator 1 dominant, identical tail codes 2/19/82 — §2.4)
   → **OQ-3**.
4. **Timestamps** — WS `t` = SIP ms, REST `sip_timestamp` = SIP ns: matches
   the normalizer exactly (§1.2). No drift.

### 2.3 Data-integrity SM, degrade behavior, replay vs live

States: `HEALTHY ↔ {GAP_DETECTED, HALTED}`; `CORRUPTED` terminal (manual
restart only); halt-on wins over halt-off on contradictory tape
(`ingestion/data_integrity.py:17-58, 69-88`). Orchestrator gating
(`kernel/orchestrator.py:6655-6735`):

- `CORRUPTED` → force-flatten symbol + macro `DEGRADED` (`:6694-6709`).
- `GAP_DETECTED` → same **iff** `degrade_on_data_gap` (`:6718-6735`); the
  reference config sets it `true` (`platform.yaml:29`), macro `DEGRADED` is
  sticky (operator command to clear).
- `HALTED` → fills blocked, no macro escalation (`:6710-6717`); in-halt
  prints are still logged/published for forensics but not routed
  (`:1859-1876`).
- Caveat (stated in the config itself, `platform.yaml:25-28`): **standard
  backtest replay wires no normalizer**, so this SM path is live/paper-only;
  offline strictness comes from `backtest_enforce_ingest_terminal_health` +
  `backtest_reject_zero_ingest_events` (`platform.yaml:33-34`) which refuse
  boot unless every symbol's ingest ended HEALTHY.

Replay-vs-live differences (beyond §1.2): live = WS → normalizer → bounded
queue (drops counted) with real network latency; replay = REST → normalizer →
EventLog → global resequence (`massive_ingestor.py:405-423, 272-296`) →
`ReplayFeed` with modeled 20 ms visibility latency. `received_ns` semantics
differ per §1.2; REST sequence-gap detection off vs WS on.

### 2.4 DiskEventCache provenance + inventory (Amendment D)

Mechanics (`storage/disk_event_cache.py`): layout
`{cache_dir}/{SYMBOL}/{YYYY-MM-DD}.jsonl.gz` + `.manifest.json` (`:7-11`);
default dir `~/.feelies/cache` (`harness/backtest_runner.py:326`). Manifest
records `event_count`, `quotes_count`, `trades_count`, SHA-256 `checksum`,
`event_schema_hash` (dataclass fields + semantic version `2`),
`normalizer_version` (`1`), `created_at`, optional `ingestion_health`
(`:37-45, 258-270`). Load fails safe to API re-ingest on schema-hash,
checksum, or count mismatch (`:119-212`, Inv-11); `normalizer_version`
mismatch only warns (`:138-156`). Writes are atomic (data before manifest,
`:222-254`).

**Inventory on this host (2026-07-08), from manifests — Task 8 pre-registers
its IC sessions from this list:**

| symbol | date | events | quotes | trades | ingestion_health | usable |
|---|---|---|---|---|---|---|
| APP | 2026-03-20 | 142,283 | 52,489 | 89,794 | HEALTHY | yes |
| APP | 2026-03-21 | 0 | 0 | 0 | UNKNOWN | **no (empty — weekend date)** |
| APP | 2026-03-23 | 196,357 | 80,476 | 115,881 | HEALTHY | yes |
| APP | 2026-03-26 | 266,754 | 87,899 | 178,855 | HEALTHY | yes (APP acceptance-baseline day) |
| APP | 2026-06-01 | 181,732 | 52,398 | 129,334 | HEALTHY | yes |
| APP | 2026-06-02 | 141,829 | 50,292 | 91,537 | HEALTHY | yes |
| APP | 2026-06-03 | 143,448 | 43,644 | 99,804 | HEALTHY | yes |
| APP | 2026-06-29 | 167,709 | 54,748 | 112,961 | HEALTHY | yes |

**Seven usable (symbol, date) sessions, all APP.** No other symbol is cached
— in particular no AAPL despite `platform.yaml:9-10` defaulting to AAPL
(→ OQ-5). All `bt_*` configs point at APP (§6).

*Superseded for evidence purposes (2026-07-10):* Task FQ-5B ingested the
frozen 8-symbol × 10-session evaluation grid; the CLOSED inventory that
Task 8 pre-registers from is `prompt_pack_03c_universe_and_cache.md` §5.
The table above remains the historical record of this host's pre-FQ-5B
cache; the four post-2026-04-27 APP sessions in it are QUARANTINED for
evidence (T5-OQ-3, FQ-5B amendment A).

**Empirical condition-code scan** (PYTHONHASHSEED=0; direct manifest/JSONL
read, two sessions):

- 2026-03-26 — trade conditions: `{37: 129906, 41: 66494, 14: 61459,
  12: 12033, 10: 4635, 2: 847, 53: 68, 35: 62, …}` of 178,855 prints; quote
  conditions `{1: 87801, 2: 62, 19: 36, 82: 2}`; quote indicators
  `{1: 82585}`.
- 2026-06-01 — same shape: `{37: 96505, 41: 39467, 14: 33793, 12: 5870,
  10: 5522, 2: 1557, 53: 42, 35: 39, 22: 26, …}`; quotes `{1: 52389, 2: 6,
  19: 3, 82: 2}`; indicators `{1: 50490}`.

The majority of prints carry non-trivial condition codes and **all of them
feed the trade sensors** (§2.1). Interpretation of ids 37/41/14/12/10
against the unified conditions table: §2.5 (addendum, resolves OQ-2/OQ-6).

### 2.5 Conditions-endpoint dump — addendum 2026-07-09 (resolves OQ-2, OQ-6)

Authenticated `GET /v3/reference/conditions?asset_class=stocks` executed
2026-07-09 with `MASSIVE_API_KEY` (94 rows). Raw artifact committed alongside
this doc: `docs/research/massive_conditions_dump_2026-07-09.json` (sorted by
`(type, id)`, deterministic). Vocabulary: 40 `sale_condition`,
33 `quote_condition`, 10 `financial_status_indicator`,
4 `short_sale_restriction_indicator`, 2 `market_condition`,
2 `settlement_condition`, 2 `sip_generated_flag`, 1 `trade_thru_exempt`.

**Observed trade-condition ids decoded** (name | consolidated update rules
vol / high-low / open-close from the endpoint's `update_rules`):

| id | name | vol | h/l | o/c |
|---|---|---|---|---|
| 37 | Odd Lot Trade | yes | no | no |
| 41 | Trade Thru Exempt | yes | yes | yes |
| 14 | Intermarket Sweep | yes | yes | yes |
| 12 | Form T / Extended Hours | yes | no | no |
| 10 | Derivatively Priced | yes | yes | no |
| 2 | Average Price Trade | yes | no | no |
| 53 | Qualified Contingent Trade | yes | no | no |
| 35 | Stock Option (legacy) | yes | yes | yes |
| 22 | Prior Reference Price | yes | yes | no |

**Reading for sensor eligibility (the OQ-2 checklist, answered):**

- **No cancel/bust/error condition exists in the vocabulary at all** — the
  endpoint's only correction-adjacent entries are sale condition 38
  ("Corrected Consolidated Close", listing-market summary print) and quote
  condition 81 ("Corrected Price Indication"). Cancelled/corrected prints
  are therefore *not* signalled via `conditions`; they can only arrive via
  the separate `Trade.correction` field (OQ-4, narrowed below).
- **Every observed dominant id updates consolidated volume** (only 15/16,
  Market Center Official Open/Close, do not — and those are not in the
  observed dominant set). So volume-/flow-style sensors (`hawkes_intensity`,
  `inventory_pressure`, `kyle_lambda_60s`, VPIN buckets) consuming all
  prints is **consistent with SIP consolidated-volume semantics** — the
  ingest-everything design (DI-09) stands for flow sensors.
- **Price-inference caveat, hypothesis-level not normalizer-level:** ids
  {37, 12, 2, 53, 7, 13, 29, 52} are high/low-ineligible and {10, 22, 32}
  additionally open/close-ineligible — the SIPs deem their *prices*
  non-representative of the current market. Odd lots (37) alone are ~70% of
  cached APP prints (§2.4). Any Task-6 hypothesis that infers "current
  price" or trade-through from raw prints must state whether it filters on
  these ids; the platform gives it the verbatim `conditions` tuple to do so.
- **Quote conditions decoded (OQ-6):** 1 = Regular Two-Sided Open (normal),
  2 = Regular One-Sided Open (one side of the NBBO absent), 19 = Market
  Maker Quotes Closed, 82 = SIP Generated. None marks a non-firm/indicative
  quote (20 "Non-Firm" exists in the vocabulary but was never observed in
  cache), so fill simulation against cached ticks is not trading against
  known-indicative quotes. Tail ids 2/19/82 are ≤0.1% of quotes (§2.4).
- **Quote `indicators` id 1 is NOT in this vocabulary** — the endpoint
  carries SSR indicators (57–60) and financial-status indicators (62–71)
  but no id-1 "indicator" row; the quote-`indicators` field's id 1 remains
  formally uninterpreted (residual of OQ-6, low stakes: it is present on
  ~94% of quotes uniformly, so it cannot be a discriminating flag).
- **Odd-lot/BOLO quote conditions do not exist in the current vocabulary**
  (no quote_condition names an odd-lot/BOLO record type) — strengthens the
  OQ-3 negative evidence: even post-2026-04-27 the vendor's condition
  vocabulary offers no way to mark an odd-lot quote, consistent with the
  `Q`/NBBO channels remaining round-lot-NBBO-only.

---

## 3. Session mechanics — enforcement anchor × reference-config activation

Knob values are pinned in 00c §1 (regulatory/session table) — not restated.
Enforcement anchors verified this task:

| Mechanic | Enforcement anchor(s) | Active in reference `platform.yaml`? |
|---|---|---|
| **Halt (BT-5)** | In-halt suppression: quote early-return `kernel/orchestrator.py:2339-2346`; halt-on edge + resting-cancel `:6411-6441, 5052-5075`; post-resume entry blackout (`halt_resolution_blackout_seconds`) `:2703-2726, 6442-6458`; normalizer-side defense `:6710-6717`. Router files contain no halt logic — all orchestrator-side. | **No** — `halt_on/off_condition_codes: []` (`platform.yaml:73-74`); blackout timer set but unreachable |
| **SSR (BT-6)** | Intent-time (pre-`OrderRequest`), not fill-time: `_ssr_blocks_intent` → `NO_ORDER`, trace `"ssr_suppressed"` `:2750-2769, 6582-6586`; short-intent set `execution/regulatory/borrow_availability.py:56-71`; daily seed `:1249-1251`; sticky intraday trigger `:6486-6499`. Runtime token is lowercase `ssr_suppressed`, not the doc token `SSR_SUPPRESSED`. | **No** — empty lists (`platform.yaml:83-84`); `ssr_mode: refuse_short` is the only implemented mode (`platform_config.py:718-722`) |
| **PDT / account (BT-4)** | Non-`margin_25k` refused at bootstrap (`bootstrap.py:398-403`); `PDTConstraint.should_suppress_entry` = flagged (≥4 round trips) **and** equity < floor (`execution/regulatory/pdt_constraint.py:162-179`); order-level `REJECT` reason `PDT_MIN_EQUITY` in `risk/basic_risk.py:265-272, 486-520` (entry-only) | **Yes** (armed, conditional) — `margin_25k`, floor $25k (`platform.yaml:101, 105`) |
| **Borrow (BT-7)** | `unavailable` → `NO_ORDER`, trace `locate_unavailable` (`orchestrator.py:2771-2785, 6515-6523`); `hard` → `OrderRequest.is_short=True` (`:4732-4737, 4818`; `borrow_availability.py:74-76`) → HTB fee at fill `execution/cost_model.py:377-393` | **No** — table `{}` → all `available`; HTB bps 0.0 (`platform.yaml:91, 177`) |
| **Ex-date guard (BT-18)** | Bootstrap **hard refusal** (`ConfigurationError`), not warning: `bootstrap.py:295-299, 2211-2240`; span-vs-ex-date check `storage/reference/corporate_actions/__init__.py:196-238`. Policy: **raw unadjusted L1 within-session**; replays must not span an ex-date (`docs/data_adjustment_policy.md`; `RAW_UNADJUSTED_L1_POLICY`, `corporate_actions/__init__.py:34-37`) | **Yes** — calendar path set (`platform.yaml:249`), guard default `True` (`platform_config.py:502`) |
| **RTH (BT-16)** | Predicate `should_suppress_entry` (09:30–16:00 ET; 13:00 early close; holiday; `no_entry_first_seconds`) `execution/trading_session.py:114-135`; enforced twice — risk engine `basic_risk.py:284-290, 522-548` **and** router fill-time on every path incl. resting through/drain fills (`backtest_router.py:259-263, 354-358`; `passive_limit_router.py:340-344, 480-501, 597-612`). Entries only; exits always permitted (Inv-11) | **Yes** — `rth_session_gating_enabled` default `True` (`platform_config.py:165`); session date from `event_calendar_path` (`platform.yaml:246`) |
| **MOC (BT-8)** | Orders flagged `is_moc` only for strategies in `moc_strategy_ids` (`orchestrator.py:4760-4764`); queue until first quote with `exchange_timestamp_ns ≥ official_close_ns`, fill at close **mid** (`execution/moc_fill.py:60-147, 199-206`); cutoff 15:50/12:50 ET (`execution/moc_session.py:72-95`); `cost_moc_penalty_bps: 3.0` inert for non-MOC alphas (00c §1) | **Configured, not exercised** by `sig_benign_midcap_v1` |

Hypothesis-relevant summary: on the reference profile, **halts, SSR, and
borrow constraints are not priced or simulated** (00c already flags this for
SHORT/halt-prone candidates); RTH entry gating, PDT floor, MOC machinery, and
the ex-date bootstrap guard are live.

---

## 4. Tick handling (`execution/tick_size.py`) — R8 anchor

The entire tick model is one 59-line module: prices ≥ $1.00 → $0.01 tick,
< $1.00 → $0.0001 (`tick_size.py:22-31`). Fill prices snap **against** the
taker (BUY ceil / SELL floor, `:34-38`); resting limits snap to the valid
passive-side tick (BUY floor / SELL ceil, `:41-45`); `is_on_tick_grid`
(`:48-51`). Consumers: taker fill snapping and the passive maker-grid snap
(00c §2 through-fill trigger note).

**Hardcoded assumptions:** the grid is a pure function of price — no
per-symbol table, no config knob, no calendar. A tick-regime change
propagates only by editing this module, which would shift fill/limit prices
everywhere and therefore the locked parity baselines (`market_fill_acks` et
al., 00 §(d)) — i.e. it is a **pre-registered structural sample boundary**,
not a tunable.

**Current regulatory status (verified 2026-07-08):** the SEC's Rule 612
amendment ($0.005 tick for tick-constrained NMS stocks, adopted 2024-09-18,
release 34-101070) is **not in force** — compliance deferred by exemptive
order to the first business day of **November 2027** (release 34-105656;
prior extension to Nov 2026 dated 2025-10-31). The two-tier hardcode is
therefore correct for all cached sessions and for this pack's horizon.
**R8 anchor:** the tick-grid artifact test (spread-in-ticks distribution;
re-derivation of single-grid-value "states"; scheduled tick-regime changes as
structural boundaries) hangs off this module per the Task-3 skill edit
(`prompt_pack_02a_skill_changelog.md`, R8 row). Note the interaction with
§2.2: APP's MDI **round lot** is 40 shares (quote-size units), a separate
regime from the **tick** grid — both are scheduled semiannual reassignments
and both are pre-registered boundaries for sample construction.

---

## 5. Sensor catalog and reducer vocabulary

Full source-verified detail (params, warm rules, libm exposure, per-file line
cites) was audited this task; the operative summary follows. Registry
mechanics: `SensorRegistry` instantiates from `sensor_specs`, fans out only
declared event types (`sensors/registry.py:217-221, 273-275`), suppresses
non-finite values (`:317-329`), and stamps sequence/correlation/provenance
(`:350-399`); the **sensor** decides `warm`, downstream enforces it —
`HorizonAggregator` ignores cold readings
(`features/impl/horizon_windowed.py:263-264`), `HorizonSignalEngine` drops
cold readings from its gate cache (`signals/horizon_engine.py:333-335`).

### 5.1 Implemented sensors (18 under `sensors/impl/`)

| sensor_id | version (class / yaml) | Subscribes | Warm rule (un-warm?) | Output | libm |
|---|---|---|---|---|---|
| `ofi_ewma` | 1.1.0 | NBBOQuote | ≥50 quotes in 300 s sliding window; **state reset after >300 s gap** (yaml) | EWMA-smoothed L1 OFI, depth-normalized (yaml: `decay_tau_seconds=10`) | exp (`ofi_ewma.py:238`) |
| `ofi_raw` | 1.0.0 | NBBOQuote | ≥50 in 300 s | Per-event raw OFI (shares); `sum` reducer → `ofi_integrated` | no |
| `micro_price` | 1.1.0 | NBBOQuote | ≥1 in 60 s; zero depth → cold | Stoikov micro-price ($) | no |
| `book_imbalance` | 1.0.0 | NBBOQuote | ≥1 in 60 s; zero depth → cold | Top-of-book size imbalance ∈ [−1,1], winsorized ±0.95 (yaml) | no |
| `spread_z_30d` | 1.1.0 | NBBOQuote | 6000-quote count window; **flush after >300 s gap** (yaml) | Spread z-score vs rolling Welford baseline | sqrt |
| `realized_vol_30s` | 1.3.0 | NBBOQuote | ≥16 mid-returns in 30 s event-time window (can un-warm) | Sample σ of mid log-returns, unannualized | log, sqrt |
| `quote_replenish_asymmetry` | 1.1.0 | NBBOQuote | ≥20 obs in 5 s + both sides seen | Bid-vs-ask replenishment asymmetry ∈ [−1,1] | no |
| `quote_hazard_rate` | 1.0.0 | NBBOQuote | ≥20 in 5 s | Quote arrival rate (1/s) | no |
| `quote_flicker_rate` | 1.0.0 | NBBOQuote | ≥20 in 5 s | Fraction of direction-reversing quotes ∈ [0,1] | no |
| `kyle_lambda_60s` | 1.2.0 / **2.0.0 (causal lag-one)** | NBBOQuote+Trade | ≥30 OLS samples in 60 s | Kyle λ ($/share per signed flow) | no |
| `trade_through_rate` | 1.1.0 | NBBOQuote+Trade | ≥5 trades (yaml) in 30 s | Fraction of prints at/through NBBO ∈ [0,1] | no |
| `hawkes_intensity` | 1.2.0 | Trade | ≥10/side (yaml) in 60 s | (λ_buy, λ_sell, ratio, α/β) tuple | exp |
| `inventory_pressure` | 1.0.0 | Trade | ≥20 trades in 60 s (can un-warm) | Σ(−aggressor·size)/Σsize ∈ [−1,1] (aggressor **inferred** — §7 L6) | no |
| `liquidity_stress_score` | 1.0.0 | NBBOQuote | 6000-quote window; **gap flush** (yaml) | Spread-widen + depth-thin composite ∈ [0,1] | sqrt, exp |
| `scheduled_flow_window` | 1.2.0 | NBBOQuote (yaml spec; class accepts any event) | Calendar-dependent | (active, s-to-close, window-id, direction-prior) tuple | no |
| `snr_drift_diffusion` | 1.3.0 | NBBOQuote | ≥4 samples per horizon (30/120 s) | Per-horizon SNR \|μ\|/(σ/√h) tuple | log, sqrt |
| `structural_break_score` | 1.2.0 | NBBOQuote | ≥100 samples spanning ≥3600 s | Page–Hinkley break score ∈ [0,1] | log |
| `vpin_50bucket` | 1.1.0 | Trade | ≥10 of 50 volume buckets (5000 sh) | Mean bucket flow imbalance ∈ [0,1] | no |

### 5.2 Registered vs dormant (verified against configs)

- **Reference `platform.yaml` registers 15** (`platform.yaml:252-466`):
  all of the above except the last three.
- **Dormant (implemented, registered in no production config —
  `configs/*.yaml` grep clean): `vpin_50bucket`, `snr_drift_diffusion`,
  `structural_break_score`.** This confirms the skill's coverage note and
  adds `structural_break_score` to it. Dormant sensors also have **no**
  `_HORIZON_FEATURE_FACTORIES` entry (`bootstrap.py:1134-1354`), so even if
  registered they would produce no Layer-2 features without new wiring.
- Other configs are subsets: `paper_smoke_rth.yaml` registers 2;
  `paper_run.yaml` registers 11.

### 5.3 Horizon-windowed reducers and derived names

Exact reducer set (`features/impl/horizon_windowed.py:61`):
`{last, mean, sum, rms, zscore, percentile, delta}` — semantics: `last` =
newest in-window value; `mean` = Welford window mean; `sum` = `mean·n`
(integrated flow — the `ofi_integrated` construction); `rms` =
√(mean²+var); `zscore` = (latest − window mean)/window std, clamped ±10;
`percentile` = Hazen rank (rank−0.5)/n of latest; `delta` = latest − oldest
(`:322-354`). Derived feature ids default to `{sensor_id}{suffix}` with
suffixes `"" / _hmean / _hsum / _hrms / _zscore / _percentile / _delta`
(`:93-101, 135-136`); explicit overrides exist (e.g. `ofi_integrated` =
`ofi_raw`+`sum`, `bootstrap.py:1168-1174`). Companion features:
`RollingZscoreFeature` → `{sensor_id}_zscore` (v1.1.0),
`RollingPercentileFeature` → `{sensor_id}_percentile` (v1.1.0),
`SensorPassthroughFeature` → `{sensor_id}` (v1.0.0)
(`features/impl/rolling_stats.py:87, 245`; `sensor_passthrough.py:50-59`).

**Feature-level warm/stale:** feature `finalize()` returns
`(value, warm, stale)`; the aggregator demotes non-finite values to cold,
omits cold values from `snapshot.values` (presence-keyed, S2), and
**overrides stale=True when no warm reading from any input sensor arrived
within `horizon_seconds` before the boundary**
(`features/aggregator.py:489-548`). Downstream, `not warm or stale` blocks
**entries only**; exits and gate-close still run
(`signals/horizon_engine.py:372-395`) — matching the glossary warm/stale
contract. `feature_version` is a class attribute recorded per-key in
`HorizonFeatureSnapshot.feature_versions`; conflicting versions for one
`(feature_id, horizon)` are rejected at registration
(`aggregator.py:175-190, 550-553`).

---

## 6. Universe

- **Run universe = `PlatformConfig.symbols`, period.** Fan-out at bootstrap:
  sensor registry (`bootstrap.py:1587`), horizon aggregator (`:1670, 1692`),
  live normalizer registration (`:475`), hazard fallback (`:640`), ex-date
  guard (`:2232`), SIGNAL-alpha composition fallback universe
  (`:2127-2152`).
- **PORTFOLIO alphas:** YAML `universe` is a required non-empty list (G10,
  `alpha/layer_validator.py:471-486`; parse `alpha/loader.py:633-648`); the
  union of all loaded PORTFOLIO universes is hard-capped at
  `composition_max_universe_size = 50` → `UniverseScaleError` at bootstrap
  (`bootstrap.py:1972-1978`; `platform_config.py:567-570, 584`). Barrier
  completeness threshold 0.80 (`platform_config.py:576`).
- **"Midcap" is config convention, confirmed:** zero `market_cap` matches
  under `src/`; `midcap` appears only in alpha/config **names**. There is no
  membership, ADV, or cap-tier logic anywhere in the platform — a
  hypothesis may not assume any universe-selection machinery beyond the
  operator's symbol list.
- Reference `platform.yaml` symbols: `[AAPL]` (`platform.yaml:9-10`); every
  `configs/bt_*.yaml` declares `APP` (directly or via `extends`). Only APP
  is cached on this host (§2.4) → OQ-5.

---

## 7. L2-INFORMATION-LOSS BASELINE LEDGER

**Mandatory input to every Task-6 hypothesis.** Consolidated L1 NBBO
(quotes + prints, ~10–50 ms WS latency) structurally cannot show the
following. Every hypothesis card must state which of these rows its mechanism
touches and inherit the corresponding modeling consequence; no candidate may
implicitly assume observability of any row.

| # | Structurally unobservable | Modeling consequence | Existing platform treatment (probabilistic or bounding) |
|---|---|---|---|
| L1 | **Depth beyond the BBO** (no L2/L3 book) | Cost of any size beyond displayed top-of-book is a model, not an observation; stop/forced exits into thin books are systematically mispriced if taken at face value | Walk-the-book impact on excess over L1 depth, capped at `cost_max_impact_half_spreads = 4.0` half-spreads; within-L1 participation impact 0.3; forced-exit depth depletion 2.0 (00c §1 impact table; `execution/market_fill.py:259-328`). Geometric next-level model is a **Not-shipped** Tier-2/3 target (`.cursor/skills/backtest-engine/fill-model.md:205-210`) |
| L2 | **Queue composition and own queue position** at a price level | Passive fill timing/probability is unknowable; deterministic fill-after-N-ticks rules would be fiction; maker fills are conditionally adverse | Seeded-Bernoulli per-tick fill hazard (SHA-256 uniform over replay-stable keys — no RNG): queue-depth regime via `passive_queue_position_shares = 200` trade-drain proxy, quote-imbalance regime `h = (1/fill_delay_ticks)·2·imbalance`, capped `passive_fill_hazard_max = 0.5` (`execution/passive_limit_router.py:734-791, 793-814`; knobs 00c §1). Uniform-queue + `queue_depth_multiplier` 1.5–3× model is **Not-shipped** (`fill-model.md:107-121`) |
| L3 | **Venue fragmentation behind the NBBO** (only the quote-setting exchange id is visible; no per-venue book, no routing table) | Displayed NBBO size ≠ accessible liquidity at one venue; fee/rebate economics of actual routing are approximations; "the NBBO ticked" conflates 16+ venues' behavior | Flat per-share taker/maker exchange fees (taker 0.003, maker 0.0 = SmartRouter blend; 00c §1 cost table); no per-venue modeling anywhere. `bid_exchange`/`ask_exchange` carried but unconsumed on the tick path |
| L4 | **Hidden / reserve / midpoint liquidity** | Prints can occur inside the spread (hidden midpoint) or exceed displayed size (icebergs); displayed-size caps on fills are conservative, hidden-liquidity fills optimistic — direction differs per path | Through-fill capped at **displayed** crossing size (`through_fill_size_cap_enabled: true`, degenerate zero-size → full remainder; 00c §2); `trade_through_rate` sensor measures inside/through prints statistically; iceberg prevalence is an open **assumptions-register** row (`fill-model.md:234-239`), not a model |
| L5 | **Cancel attribution / order-level flow** (book deltas conflate cancels, replenishment, and trades; no order ids) | L1 OFI is the Cont–Kukanov–Stoikov *best-level* form, not true order flow; cancellation-driven "pressure" and trade-driven pressure are indistinguishable per event | `ofi_ewma`/`ofi_raw` implement exactly the L1 form (documented in the sensors); `quote_replenish_asymmetry` / `quote_flicker_rate` infer replenishment/cancel behavior distributionally; nothing claims order-level attribution |
| L6 | **Trade aggressor side / informedness** (SIP prints carry no aggressor flag; no trader identity) | Any signed-flow sensor rests on quote-rule/tick-rule inference — misclassification concentrates exactly where signals fire (fast markets, locked/crossed moments, midpoint prints); "informed flow" is a proxy, never a label | Aggressor inference inside trade sensors (`inventory_pressure`, `hawkes_intensity` side split, `kyle_lambda_60s` signed flow); adverse selection charged as **flat bps by fill type** (LEVEL 2.0 / THROUGH 5.0, 00c §1) rather than flow-conditional; VPIN toxicity proxy ships but is **dormant** (§5.2). Flow-conditional adverse selection is a Not-shipped design target (`fill-model.md:166-186`) |
| L7 | **Latency microstructure below the feed floor** (queue races, ISO sweeps, sub-ms sequencing; WS delivery ~10–50 ms, ms-resolution timestamps live) | No hypothesis may claim an edge that requires reacting faster than visibility latency + fill latency; same-tick fills are forbidden in evidence runs | 20 ms visibility + 50 ms fill legs, doubled under stress — pinned in 00c (decision A: zero-latency runs invalid for evidence); router eligibility semantics in §1.2 item 4 |

Cross-cutting consequence, stated once: **every quantity above that the
platform models rather than observes is already priced conservatively into
the cost/fill stack that 00b's floor arithmetic runs on.** A Task-6
hypothesis whose mechanism *is* one of these unobservables (e.g. "queue
position improves") is claiming to predict something the platform explicitly
models as noise — such a hypothesis must name the observable L1 footprint it
actually trades on, or it fails Inv-1 at the card stage.

---

## 8. OPEN QUESTIONS

Namespace (FQ-5B amendment D, 2026-07-10): the OQ ids in this section are
the **Task-5** questions — task-prefixed **T5-OQ-1 … T5-OQ-6** from now on
(no retroactive renumbering of existing text). The unrelated Task-1
questions labelled OQ-1…OQ-6 live in
`prompt_pack_00_architecture_verification.md` §(e) (**T1-OQ-n**).

- **OQ-1 (data integrity — quote size units, live WS) — RESOLVED
  2026-07-10 (Task FQ-5B): live WS sizes are SHARES.** Original question:
  Massive's WS doc describes `bs`/`as` as **round lots**, while REST/
  flat-file docs and the cached 2026 data are **shares** (post-MDI
  2025-11-03); the normalizer applies no conversion on either path
  (`massive_normalizer.py:451-452, 634-635`). FQ-5B captured 100 raw
  `Q.APP` events live during RTH (2026-07-10 ~09:31 ET): sizes min 40,
  100% divisible by APP's 40-share round lot, medians 80/40 — impossible
  under lots semantics — and a near-simultaneous REST window match was
  size-identical on 80/98 matched events (rest off by exactly one lot on
  ms-timestamp ties). Full evidence + raw-frame artifact:
  `prompt_pack_03c_universe_and_cache.md` §8;
  `artifacts/oq1_ws_quote_frames_APP_2026-07-10.jsonl`. The WS doc's
  "round lot orders" wording is stale — worth a vendor doc-bug note, not
  a parity blocker. Residual live-WS parity questions (cancel/correction
  dissemination, June-2026 population change) remain open under
  **AXIS-2** of the parity-gap register
  (`prompt_pack_00_architecture_verification.md` §(e)).
- **OQ-2 (condition-code eligibility for sensors) — RESOLVED 2026-07-09;
  convention issued by Task FQ-5A.** Authenticated conditions dump executed
  and decoded in §2.5 (artifact: `massive_conditions_dump_2026-07-09.json`;
  superseded by the raw-fetch artifact
  `artifacts/massive_conditions_2026-07-09.json` — identical semantics, the
  older dump lost `FINRA_TDDS` sip-mapping keys to the SDK's typed model).
  Verdict: every dominant observed id updates consolidated volume, so
  ingest-everything is correct for flow sensors; ids {37, 12, 2, 53} et al.
  are high/low-ineligible (odd lots ≈70% of prints), which is a
  **hypothesis-level filter decision** for price-inference uses, not a
  normalizer defect. No cancel/bust condition exists in the vocabulary.
  The hypothesis-level decision is now normative: the (id × sensor)
  PRINT-ELIGIBILITY CONVENTION for the new candidate's sensors is
  `prompt_pack_03b_print_eligibility.md` §3 (DI-09 platform behavior
  unchanged).
- **OQ-3 (odd-lot/BOLO dissemination since 2026-04-27) —
  CHANGED-CONFIRMED, UNKNOWN CAUSE (FQ-5B amendment C, 2026-07-10;
  supersedes the earlier weak-negative reading).** Task FQ-5A found the
  quote condition/indicator population **switched** between the
  2026-06-03 and 2026-06-29 cached sessions (03b §5.1: conditions mostly
  empty, new indicator set 501–604, uninterpreted quote condition 34) —
  something in dissemination or vendor population semantics **did**
  change after 2026-04-27; whether it is BOLO-related is unknown. Vendor
  question outstanding (03b §7.3 rows 1/3). Admissibility rule (FQ-5B
  amendment A): post-2026-04-27 sessions are **INADMISSIBLE for the
  evidence grid** until the vendor answers — they may be ingested but are
  flagged QUARANTINED in the `prompt_pack_03c_universe_and_cache.md` §5
  inventory and do not count toward per-symbol targets. This supersedes
  the FQ-5B step-1(a) unknown-id-guard proviso.
- **OQ-4 (corrected/cancelled prints) — CLOSED 2026-07-09 (Task FQ-5A).
  Verdict: DOUBLE-COUNT RISK YES, bounded.** `Trade.correction` is carried
  but consumed by nothing (§1.2); cancels/busts are **not** signalled via
  condition codes (§2.5). Historical REST delivers **both** the original
  (retroactively stamped `correction` 1/7/8) and the follow-on
  cancel/error/correction record (10/11/12) at its own later timestamp —
  proven empirically from cache (matched `(trade_id, exchange,
  sequence_number)` pairs in six of seven sessions; ~0.004% of prints).
  Netting rule for the new candidate's sensors (drop
  `correction ∈ {10,11,12}`; never condition on the retroactive 1/7/8
  flags — lookahead): `prompt_pack_03b_print_eligibility.md` §4. Residual
  open row (live-WS dissemination parity, Task-12 input): 03b §7.3.
- **OQ-5 (universe/data gap for Task 8) — RESOLVED 2026-07-10 (Task
  FQ-5B).** The frozen 8-symbol × 10-session evidence grid (Lei's
  UNIVERSE_DECISION, 2026-07-10) was ingested through the platform path
  into the disk cache; Task 8 pre-registers its IC sessions and CPCV data
  from the CLOSED inventory in `prompt_pack_03c_universe_and_cache.md`
  §5, **not** from the §2.4 APP-only list (which remains the historical
  record; June-2026 APP sessions are QUARANTINED per T5-OQ-3).
  Cross-symbol claims are now possible within the grid's pre-registered
  limitations L1–L4.
- **OQ-6 (quote condition/indicator semantics) — CLOSED 2026-07-09 for all
  interpreted ids (Task FQ-5A); one new open id.** Quote conditions decoded
  in §2.5: 2 = Regular One-Sided Open, 19 = Market Maker Quotes Closed,
  82 = SIP Generated; none marks a non-firm/indicative quote, so fill
  simulation against cached ticks is safe on this axis. The indicator-id-1
  residual is now interpreted (medium confidence) as the legacy CTA numeric
  National BBO Indicator '1' = "quote is itself the NBBO" (modern G/602) —
  03b §5.2. New findings from the full-cache scan (03b §5): the
  2026-06-29 session switches to glossary indicators {602, 604, 501–503}
  (all benign NBBO/retail-interest bookkeeping) and carries quote
  condition **34, absent from the reference vocabulary** → that session is
  UNKNOWN-ID-flagged and inadmissible for evidence until interpreted
  (vendor question: 03b §7.3). Full verdicts and fill-sim consequences:
  `prompt_pack_03b_print_eligibility.md` §5.

**Task 5 complete. The §7 ledger and §8 OQ-1 are binding inputs to Task 6
(OQ-2/OQ-6 resolved 2026-07-09 via §2.5; the §2.5 price-inference caveat is
the surviving Task-6 obligation); §2.4's session list is the binding input
to Task 8 pre-registration.**
