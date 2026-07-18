<!--
  File:   docs/research/prompt_pack_13_tranche2_characterization.md
  Status: DECIDED (2026-07-18, Lei) — NO-GO DISPOSITION ratified.
          Measured map stands (§§1–7 unedited). Tranche-2 thesis
          CLOSED by measurement. Standing state PAUSE-AND-HARVEST.
          AXTI is a single-name characterization fact, not a seed.
  Owner:  research-workflow (tranche-2 go/no-go) / data-engineering
          (Massive census-legal samples); prompt-pack Task T2-C.

  Provenance (FQ-3 template): see §7.
-->

# Task T2-C — Tranche-2 frontier characterization (go/no-go)

**What this is.** Bounded, census-legal characterization of a higher-σ
US midcap candidate set: daily-bar screen → small RTH quote samples on
2–3 admissible-span sessions → floor / κ_req arithmetic at
H ∈ {30, 120, 300}. **No grids drawn. No full-day intraday ingestion
beyond the capped samples. No forward returns, IC, or signal
evaluation.** Standing capital state remains **PAUSE-AND-HARVEST**
(pack-12 DISPOSITION 1) until Lei reads the measured map. Full
tranche-2 program authorization is **not** granted by this file.

**Trial ledger: N = 12, untouched** — characterization only; no
hypothesis evaluated.

**Verdict (measured): NO-GO** — 1 name clears §1.6 (need ≥ 5). Detail §5.

---

## 1. FROZEN SCREEN CRITERIA (written before any candidate result)

Frozen at task start, before any ticker ranking or quote sample was
examined. Mechanical; no discretion mid-flight. *(This section was
committed to the working tree before the network pull examined
rankings or κ numbers.)*

### 1.1 Universe filters (all must hold)

| # | predicate | freeze |
|---|---|---|
| U1 | Instrument | Massive `type=CS`, `market=stocks`, `locale=us`, `active=true` |
| U2 | Primary listing | `primary_exchange ∈ {XNYS, XNAS}` |
| U3 | Market-cap band | **$2B ≤ M ≤ $12B**, with `M = shares × close_asof` where `shares = weighted_shares_outstanding` if present else `share_class_shares_outstanding` (ticker details), `close_asof` = adjusted daily close on **as-of date** |
| U4 | Price | `close_asof > $10` |
| U5 | As-of date | **2026-04-24** (last full session inside the admissible span; pack-12 Q2 / 03c §1(a) — post-2026-04-27 banned) |
| U6 | Closed-grid exclusion | Drop `{APP, RMBS, OLN, ENSG, DIOD, PCTY, MLI, CROX}` — diversification tranche; never pooled with the frozen grid (backlog 11; pack-12 §5.1) |
| U7 | ADV adequacy | Trailing-20-session **median** daily dollar volume (`close × volume`, adjusted daily aggs ending as-of) **≥ $15,000,000**. Floor matches the thinnest admitted frozen-grid name's order of magnitude (03c DIOD grid-session median eligible ~$16.3M) — platform-scale liquidity, not a research taste cut. |
| U8 | Ranking key | Trailing **rv20** on adjusted daily log-closes ending as-of: `rv20 = √252 × s_{n−1}(r) × 100` (percent), sample stdev over the trailing 20 close-to-close log returns (same convention as `universe_draw_evidence_2026-07-10.md` Step 1). Require ≥ 21 daily bars with last bar = as-of. |
| U9 | Candidate set size | Top **15** by rv20 among names passing U1–U8. Ties broken by ticker ascending (deterministic). If fewer than 15 pass, take all passers and record underfill. |

**Disclosed non-binding prefilter (API cost only):** as-of single-day
dollar volume ≥ $8M before `get_ticker_details` / trailing-bar pulls.
Binding ADV gate remains U7. Recorded in the artifact
`screen_summary.asof_dv_prefilter_usd`.

**Shares-outstanding caveat (recorded):** Massive ticker-details shares
are the vendor's current outstanding figure at pull time, multiplied by
the as-of close — not a point-in-time April-2026 diluted share count.
Cap-band membership is therefore a **proxy screen**, disclosed as such.

### 1.2 Sample sessions (admissible span only)

Exactly three sessions, regime-balanced from the frozen 03c calendar
(no new date draw):

| role | date |
|---|---|
| elevated_A | 2025-11-25 |
| calm | 2026-01-15 |
| elevated_B | 2026-04-10 |

### 1.3 Quote-sample protocol (small; /v2 last-NBBO banned)

- Endpoint: Massive REST **`/v3/quotes/{ticker}`** via repo client
  (`massive.RESTClient.list_quotes`) — same construction as
  `ingestion/massive_ingestor.py`. **`/v2` last-NBBO is banned** (task
  constraint; never called).
- Per (symbol, session): **time-stratified RTH sample** — RTH =
  09:30 ≤ t < 16:00 America/New_York on `sip_timestamp`; partition into
  contiguous **5-minute** buckets; keep the first **≤ 40** positive
  two-sided quotes (`bid > 0`, `ask > 0`, `ask ≥ bid`) per bucket;
  hard cap **3,120** quotes/session (= 78 × 40). Timestamp-ascending
  within bucket. This is the entire intraday touch — no
  `DiskEventCache` write, no full tape ingest.
- Half-spread (bps): per session, median `(ask−bid)/(2·mid) × 1e4` over
  the sampled two-sided quotes; then **median-of-per-session-medians**
  across the three sessions (03c §7 / pack-05 pooling convention).
- Price for fee-in-bps: median bid, same pooling.
- σ_H (H ∈ {30, 120, 300}): Bessel-corrected sample std of
  non-overlapping H-second mid log returns on the 09:30-ET-anchored
  grid (`rth_open_ns`), last-mid-at-or-before sampling from the
  **sample** mid series only, in bps — identical estimator geometry to
  `scripts/research/horizon_feasibility_map.py`, applied to the capped
  sample (not a full-cache cell). Per-session σ_H → median across the
  three sessions.

### 1.4 Floor / κ arithmetic (unchanged from pack-05 / pack-08)

Reference fill **80 shares**; `$0.35` min-commission
(`max(0.0035 × 80, 0.35)`); taker exchange `$0.003/sh`.

- Passive: `C_ow = 2.0 + fee_passive_bps`; `floor = 2.25 × C_ow`
- Taker: `C_ow = half_spread_bps + impact + fee_taker_bps` with
  impact = 1.0 if half-spread < 8 bps else 2.0; `floor = 2.25 × C_ow`
- `κ_req = floor / σ_H` (median session σ)
- **Min-commission trap flag:** `fee_passive_bps > 2.0` (fee exceeds the
  pinned passive adverse-selection pin) — reported, not a screen kill.

### 1.5 Comparison bands (display; not outcome bars)

| band | value | role |
|---|---|---|
| Honest-κ ceiling | **0.30** | pack-05 FEASIBLE flag / H2 derivation ceiling |
| Realized central κ range | **0.146–0.190** | program freezes (H12 0.146 … H13 0.172 class) |
| Honest central screen | **0.16** | pack-08 shrinkage lens |

### 1.6 GO / NO-GO bar (frozen now)

**GO** iff at least **5** names in the candidate set satisfy:

> exists H ∈ {30, 120} such that κ_req_passive(median σ_H) ≤ **0.12**

where **0.12 = 0.16 × (1 − 0.25)** — honest central screen with
**≥ 25% margin** on the sampled medians (room for the documented
prior-miss factor on non-percentile design occupancy,
pack-12 §2 ≈ 0.46×–0.69×; this margin is the κ-side headroom freeze,
not an occupancy measurement).

**Anything less = NO-GO.** On NO-GO the standing state remains
**PAUSE-AND-HARVEST**; no slate, no cache build, no N increment.

---

## 2. CANDIDATE SET (mechanical; post-freeze)

Screen funnel (artifact `screen_summary`):

| stage | n |
|---|---|
| CS primary XNYS/XNAS, excl. closed grid | 5,063 |
| price > $10 ∧ as-of DV ≥ $8M (prefilter) | 2,105 |
| details called | 2,105 |
| cap-band fail | 1,097 |
| ADV fail (U7) | 65 |
| rv20 fail | 1 |
| bars/as-of fail | 0 |
| **survivors** | **941** |
| **top-15 candidates** | **15** (no underfill) |

Top 15 by trailing rv20 (as-of 2026-04-24):

| rank | ticker | rv20 (%) | M ($B) | ADV20 med ($M) | close_asof |
|---|---|---|---|---|---|
| 1 | CAR | 352.61 | 7.21 | 1,642.6 | 204.00 |
| 2 | MXL | 204.29 | 5.40 | 24.8 | 60.32 |
| 3 | AXTI | 202.03 | 4.98 | 908.1 | 76.16 |
| 4 | POET | 164.60 | 2.61 | 75.5 | 15.10 |
| 5 | DOO | 164.26 | 4.16 | 25.9 | 56.78 |
| 6 | YSS | 162.37 | 4.08 | 102.4 | 31.06 |
| 7 | NN | 150.54 | 2.42 | 32.0 | 17.71 |
| 8 | OGN | 149.24 | 2.96 | 54.9 | 11.26 |
| 9 | FSLY | 146.19 | 3.72 | 337.0 | 23.76 |
| 10 | AEHR | 130.15 | 3.12 | 272.0 | 95.91 |
| 11 | TVTX | 127.00 | 3.77 | 72.9 | 40.50 |
| 12 | NVTS | 126.55 | 4.21 | 199.1 | 17.28 |
| 13 | AGX | 122.84 | 9.15 | 177.7 | 652.99 |
| 14 | FLY | 122.51 | 5.77 | 262.7 | 35.13 |
| 15 | LUNR | 121.91 | 4.10 | 384.9 | 25.53 |

---

## 3. PER-NAME FLOORS (sampled medians)

Fee / half-spread / floors from the three-session quote samples.
`trap` = min-commission trap (§1.4).

| ticker | med bid≈ | half-spread (bps) | fee_P (bps) | floor P | floor T | trap |
|---|---|---|---|---|---|---|
| CAR | (via costs) | 26.14 | 0.33 | **5.24** | 64.56 | — |
| MXL | | 7.86 | 2.29 | **9.66** | 28.64 | **Y** |
| AXTI | | 9.75 | 1.71 | **8.34** | 32.91 | — |
| POET | | 7.37 | 6.45 | **19.01** | 43.29 | **Y** |
| DOO | | 9.37 | 0.57 | **5.77** | 27.73 | — |
| YSS | | 9.15 | 1.33 | **7.50** | 30.14 | — |
| NN | | 13.62 | 2.98 | **11.21** | 46.46 | **Y** |
| OGN | | 5.84 | 5.11 | **16.00** | 34.78 | **Y** |
| FSLY | | 4.09 | 3.58 | **12.56** | 25.04 | **Y** |
| AEHR | | 18.66 | 1.63 | **8.17** | 52.69 | — |
| TVTX | | 10.11 | 1.47 | **7.82** | 32.84 | — |
| NVTS | | 5.25 | 4.59 | **14.83** | 31.47 | **Y** |
| AGX | | 43.48 | 0.12 | **4.77** | 102.77 | — |
| FLY | | 10.06 | 1.47 | **7.80** | 32.69 | — |
| LUNR | | 2.50 | 2.19 | **9.43** | 16.19 | **Y** |

Seven of fifteen names trip the min-commission trap at the 80-share
reference fill (low price → fee dominates the passive pin). Exact bids
in the artifact `per_name.*.costs.median_bid`.

---

## 4. THE MAP — κ_req (name × H × variant)

σ = median across the three sampled sessions (bps). κ_req = floor / σ.
Full precision in the artifact.

| ticker | σ₃₀ | σ₁₂₀ | σ₃₀₀ | κP₃₀ | κP₁₂₀ | κP₃₀₀ | κT₃₀ | κT₁₂₀ | κT₃₀₀ | GO-bar (H≤120 P≤0.12) |
|---|---|---|---|---|---|---|---|---|---|---|
| CAR | 8.10 | 15.21 | 23.44 | 0.646 | 0.344 | 0.223 | 7.970 | 4.246 | 2.755 | — |
| MXL | 11.72 | 22.42 | 36.10 | 0.824 | 0.431 | 0.268 | 2.444 | 1.277 | 0.793 | — |
| **AXTI** | 35.02 | 70.28 | 111.35 | 0.238 | **0.119** | 0.075 | 0.940 | 0.468 | 0.296 | **YES** |
| POET | 19.73 | 39.61 | 63.17 | 0.964 | 0.480 | 0.301 | 2.194 | 1.093 | 0.685 | — |
| DOO | 5.98 | 11.97 | 18.39 | 0.965 | 0.482 | 0.314 | 4.637 | 2.316 | 1.508 | — |
| YSS | 29.58 | 60.51 | 97.35 | 0.254 | **0.124** | 0.077 | 1.019 | 0.498 | 0.310 | — (misses 0.12) |
| NN | 12.45 | 24.86 | 35.29 | 0.900 | 0.451 | 0.318 | 3.733 | 1.869 | 1.317 | — |
| OGN | 16.09 | 32.12 | 51.17 | 0.994 | 0.498 | 0.313 | 2.161 | 1.083 | 0.680 | — |
| FSLY | 10.04 | 20.11 | 31.23 | 1.250 | 0.625 | 0.402 | 2.493 | 1.245 | 0.802 | — |
| AEHR | 14.45 | 30.56 | 47.58 | 0.566 | 0.268 | 0.172 | 3.646 | 1.724 | 1.107 | — |
| TVTX | 13.34 | 26.16 | 40.95 | 0.586 | 0.299 | 0.191 | 2.463 | 1.256 | 0.802 | — |
| NVTS | 21.97 | 44.12 | 70.29 | 0.675 | 0.336 | 0.211 | 1.432 | 0.713 | 0.448 | — |
| AGX | 10.34 | 23.24 | 35.29 | 0.461 | 0.205 | 0.135 | 9.938 | 4.422 | 2.912 | — |
| FLY | 20.58 | 41.69 | 66.49 | 0.379 | 0.187 | 0.117 | 1.588 | 0.784 | 0.492 | — |
| LUNR | 18.15 | 36.31 | 57.47 | 0.519 | 0.260 | 0.164 | 0.892 | 0.446 | 0.282 | — |

### 4.1 Lens vs comparison bands (passive median)

| lens | names open at H≤120 | names |
|---|---|---|
| GO-bar κP ≤ **0.12** | **1** | AXTI |
| Honest central κP ≤ **0.16** | **2** | AXTI, YSS (YSS κP₁₂₀ = 0.124) |
| Ceiling κP ≤ **0.30** | **6** | AXTI, YSS, AEHR, AGX, FLY, TVTX (+ LUNR at H=120) |
| Realized-central band 0.146–0.190 (display) | several H=300 cells sit inside/near; **not** a GO input | — |

**H=30:** no name opens at the GO bar or at central 0.16 (best AXTI
κP₃₀ = 0.238). Short-horizon families stay closed on this candidate set
under honest κ with margin.

**Taker:** closed at GO-bar / central 0.16 for every (name, H≤120) cell;
minimum κT₁₂₀ among GO-relevant cells is AXTI 0.468.

**Structural note (not a rescue):** CAR ranks #1 on daily rv20 (352%)
but is **closed** at H=120 passive (κP 0.344) — overnight-gap daily vol
does not imply usable intraday σ_H on the sample. High daily-σ ranking
alone is not a short-horizon reopen.

---

## 5. GO / NO-GO VERDICT

| quantity | value |
|---|---|
| Names clearing §1.6 (H≤120 passive κ_req ≤ 0.12) | **1** (AXTI) |
| Required | ≥ **5** |
| **Verdict** | **NO-GO** |

Per the freeze: standing state remains **PAUSE-AND-HARVEST**. No tranche-2
slate, no cache build, no protocol freeze, **N = 12 unchanged**.

Lei decides whether any follow-on expenditure is warranted; this task
does not authorize one.

---

## 6. Legality / non-claims

- Census-legal: daily bars + capped quote samples + floor/κ arithmetic
  only.
- Not a result in the Rule-5 sense: no edge, no IC, no fill realism,
  no Tier-1 PnL.
- Does not amend pack-05 / pack-08 maps; does not touch the closed
  03c grid; does not authorize tranche-2 cards.
- Shelf firewall (pack-12 DISPOSITION 3) binds: nothing here promotes
  contaminated-shelf numbers.
- Sample σ_H is **not** a full-tape pack-05 cell — coverage is the
  stratified cap; figures are characterization-grade for the go/no-go
  bar, not promotion evidence.

---

## 7. Determinism and provenance (FQ-3)

```yaml
os: "Windows-11-10.0.26200-SP0"
cpu_arch: "AMD64"
python_build: "3.14.2 (tags/v3.14.2:df79316, Dec 5 2025, 17:18:21) [MSC v.1944 64 bit (AMD64)]"
libm: "Microsoft UCRT (platform.libc_ver() empty on Windows)"
git_sha: "d8a06d8b28845337c1fd25189da79572b5fa4de2"  # HEAD at task start
config_checksum: "n/a — no PlatformConfig; REST samples + pure arithmetic"
pythonhashseed: "0 (set in session for every scripted run)"
worktree_clean: "yes at task start (git status --porcelain empty);
  research outputs of this task are the only dirty paths at close"
env_check: "MASSIVE_API_KEY loaded from repo-root .env into the task
  session (same pattern as 03c); key never echoed"
command_network: "PYTHONHASHSEED=0 uv run python
  scripts/research/tranche2_frontier_characterization.py
  --json docs/research/artifacts/tranche2_frontier_characterization_2026-07-18.json"
command_replay: "PYTHONHASHSEED=0 uv run python
  scripts/research/tranche2_frontier_characterization.py
  --replay-artifact docs/research/artifacts/tranche2_frontier_characterization_2026-07-18.json
  --json <out.json>"
artifact: "docs/research/artifacts/tranche2_frontier_characterization_2026-07-18.json
  sha256=572602b675806dec0703a0cf7e0b8cba3bec94e49423a2e41c8510a110124bc0"
determinism: "rematerialize from embedded raw samples bit-identical
  (SHA-256 equal on two replay writes)"
script: "scripts/research/tranche2_frontier_characterization.py"
tests: "tests/scripts/test_tranche2_frontier_characterization.py (7 passed)"
normative_inputs: "prompt_pack_12_final_retrospective.md DISPOSITION 1
  (bounded T2 characterization authorized; PAUSE-AND-HARVEST standing),
  prompt_pack_05_horizon_feasibility_map.md / prompt_pack_08_frontier_refresh.md
  (floor/κ arithmetic), prompt_pack_03c_universe_and_cache.md §1(a)
  (admissible span), prompt_pack_00d_reproducibility_policy.md (FQ-3),
  universe_draw_evidence_2026-07-10.md (rv20 convention), backlog 11"
multiple_testing_ledger: "N = 12, unchanged — characterization; no hypothesis"
verdict: "NO-GO"
```

*Task T2-C body (§§1–7) measured and committed. Disposition appended
below (Lei, 2026-07-18).*

---

## DISPOSITION (NO-GO ratification — Lei, 2026-07-18; append-only; §§1–7 unedited)

1. **NO-GO RATIFIED** under the §1.6 bar frozen before measurement:
   **1 / 5** names clear (need ≥ 5). Sole clear: **AXTI** κP₁₂₀ =
   **0.119**. **YSS** κP₁₂₀ = **0.124** fails the 0.12 margin.
   **H = 30** closed for all 15 candidates (best AXTI κP₃₀ = 0.238).
   Standing capital state: **PAUSE-AND-HARVEST**. No tranche-2 slate,
   cache build, protocol freeze, card, or N increment.

2. **Mechanism finding (map's permanent contribution).** Daily **rv20
   does not transfer** to usable intraday **σ_H**: overnight-gap
   variance is excluded from horizon returns while spreads price the
   same risk into **C_ow** (CAR #1 on rv20 closed at κP₁₂₀ = 0.344 —
   §4.1). The higher-σ tranche-2 thesis is **closed by measurement**,
   not deferred.

3. **AXTI is not a program seed.** Logged solely as a single-name
   characterization fact on the sampled map. One name cannot carry a
   universe program: **no card, no grid, no authorization** attaches
   to AXTI.

4. **N = 12 confirmed.** Characterization only — living ledger
   unchanged.
