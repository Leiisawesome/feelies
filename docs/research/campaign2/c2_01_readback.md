# C2-01 — GPT-Sol onboarding read-back

## Operating contract

1. I use the repository's `uv` environment exclusively. Every scripted analysis runs with `PYTHONHASHSEED=0`, and hashes of text artifacts use LF-normalized bytes. (`docs/research/prompt_pack_16_campaign2_charter.md` §3, “Environment pinning”; `docs/research/sig_hour_checkpoint_drift_h1800_v1_validation_protocol.md` §0 P0-4 and provenance block.)
2. The repository is the handoff medium: inputs arrive as paths, outputs go only to the card's named paths, and the docs guards must pass before I commit. (`docs/research/prompt_pack_16_campaign2_charter.md` §3, “Environment pinning” and “Relay rules”.)
3. An evidence-class run begins from a clean worktree, records FQ-3 provenance—git SHA, LF-canonical artifact SHA-256, host fingerprint, and cleanliness—and is repeated bit-for-bit. (`docs/research/prompt_pack_16_campaign2_charter.md` §3, “Grading rule”; `docs/research/sig_hour_checkpoint_drift_h1800_v1_validation_protocol.md` §0 P0-4.)
4. Locked parity values are read-only. Code work must preserve the determinism suite's untouched-baselines check; a parity move is never an implementation convenience. (`docs/research/prompt_pack_16_campaign2_charter.md` §3, “Environment pinning”; `.cursor/rules/platform-invariants.mdc` “Architectural”, invariant 5.)
5. Edge and cost disclosures are one-way, per-fill bps. The single stressed passive anchor is `2.25 × (2.0 + fee_bps)`, applied once; I will not stack it with another stressed adverse-selection setting. (`docs/research/prompt_pack_00b_edge_units_convention.md` “THE CONVENTION” and “Hop 3 detail”; `docs/research/sig_hour_checkpoint_drift_h1800_v1_validation_protocol.md` preamble “Units” and §1.2.)
6. Return-free census facts—counts, volatility, occupancy, and warm coverage—are legal characterization. Forward returns, IC, PnL, or signal scoring are outcome contact and require explicit card authority; each authorized contact consumes the campaign budget and updates N. (`docs/research/prompt_pack_16_campaign2_charter.md` §§2–3; `docs/research/sig_hour_checkpoint_drift_h1800_v1_validation_protocol.md` §1 and §10.)
7. Frozen text governs. If frozen sources conflict or a card leaves a judgment unresolved, I stop and report the ambiguity rather than selecting an interpretation. (`docs/research/prompt_pack_16_campaign2_charter.md` §3, roles and interface contract.)
8. Machine changes are additive unless a separately gated approval says otherwise. I do not alter thresholds, frozen protocols, or pre-registered bars without a Lei-signed amendment card. (`docs/research/prompt_pack_15_grammar_machine_universe_doctrine.md` §8; `docs/research/prompt_pack_16_campaign2_charter.md` §§2–3.)
9. Campaign 2 uses Ordering B: build and verify instruments before evidence, and do not begin Phase B implementation until Lei has adjudicated a step-2 PASS. (`docs/research/prompt_pack_16_campaign2_charter.md` §4, Phases 1 and 3; `docs/research/prompt_pack_14_success_matrix.md` §4 item 2.)
10. Drafting variants is N-neutral. The first evaluation of any variant against outcomes is a pre-authorized `+1 N`, recorded before proceeding. (`docs/research/prompt_pack_16_campaign2_charter.md` §2, “Alpha vertex”; `docs/research/prompt_pack_12_final_retrospective.md` §6.3.)

## E ∧ P ∧ M

- **E—economics:** for every deployable symbol, `κ_frozen × σ_H,measured ≥ 1.5 × C_ow,stressed`; fee at clip scale is about `43.75 / price` bps, stressed passive floors are about 4.7–6.2 bps, honest κ realized at 0.146–0.190, and κ may not exceed 0.30. In round 1, E killed short horizons because volatility-scaled honest edge could not cover the cost floor. (`docs/research/prompt_pack_14_success_matrix.md` §§1.3 and 2.)
- **P—power:** a measured conditioning arm needs at least 100 episodes, with at least 130 at design; approximate boundaries/session are 78, 25, and 12 at H=300/900/1800. Unmeasured non-percentile arms realized only 0.46–0.69× their projections, so they are budgeted at no more than 0.5×. In round 1, P killed long horizons because sparse boundaries and conditioning attrition left too few episodes. (Same source, §§1.2–1.3 and 2.)
- **M—magnitude:** at `n ≥ 100`, the proof bar is conjunctive: `|RankIC| ≥ 0.03` and the p-bar implies roughly `2.576 / √(n−3)`. Ambient round-1 IC was only 0.019–0.089. M killed the middle horizons because observed effects were below the magnitude/significance jointly required at achievable n. (Same source, §§1.3 and 2.)

## Prohibitions and relay formats

I never (1) make unauthorized outcome contact, (2) edit a threshold, frozen document, or pre-registered bar, (3) touch paths outside the card, (4) decide an ambiguity or judgment call myself, or (5) rebaseline locked parity values. (`docs/research/gpt_sol_onboarding_index.md` “The five things you never do”; `docs/research/prompt_pack_16_campaign2_charter.md` §3.)

I accept cards only in the pack-16 envelope: `CARD id/from/to/date; OBJECTIVE; INPUTS (repo paths); FROZEN CONSTRAINTS; DELIVERABLES; GATES; STOP-AND-ASK IF; FORBIDDEN; N-LEDGER`. I return: `CARD id · VERDICT; ARTIFACTS (paths + SHA-256); COMMITS; GATES (counts); DEVIATIONS/JUDGMENT CALLS; QUESTIONS; N`. Lei relays both directions verbatim, with no unresolved placeholder, and Fable grades the report before another card issues. (`docs/research/prompt_pack_16_campaign2_charter.md` §3.)

## Three questions for the corpus owner

1. What exact command set does “the full gate battery” mean for future cards: the repository-local fast tests + determinism + lint/format + strict mypy, literal `uv run pytest`, or also prerequisite-gated functional, paper-RTH, and per-host performance tests? `AGENTS.md` “Common commands” separates these classes, while C2-01 does not enumerate the phrase.
2. What renderer, page size, font, and margins govern a “≤2 pages” limit on a Markdown artifact? The corpus gives no pagination convention; a word/line ceiling would be deterministic.
3. What is the authoritative test for classifying a run as “evidence-class” (and therefore requiring a fresh session, start-clean worktree, FQ-3, and bit-identical rerun), versus a census-legal or ordinary engineering run? Pack-16 §3 names the obligations but not a classification rule.

## Environment attestation — 2026-07-20 Asia/Shanghai

- Start state: branch `main`, HEAD `da772056d759b6229eb5d100f20943e95ce6acd6`; `git status --short` was empty before this deliverable was created.
- Toolchain: `uv 0.11.19 (7b2cff1c3 2026-06-03 x86_64-pc-windows-msvc)`; `Python 3.14.2`; `pytest 9.0.2`; `mypy 1.20.2 (compiled: yes)`; `ruff 0.15.4`.
- Hash behavior: ambient `PYTHONHASHSEED` was unset. With it explicitly set to `0`, two separate `uv run python` processes both produced `hash('feelies-c2-01') == -6913599679011449701`; the child processes also reported `PYTHONHASHSEED=0`.
- Docs guard: PowerShell-equivalent of `PYTHONHASHSEED=0 uv run pytest tests/docs/ -q` passed: **101 passed, 0 failed, 0 skipped in 0.37 s**.
- Full-battery readiness: the current `uv` environment resolves Python, pytest, strict mypy, and Ruff, so I can execute the repository-local test, determinism, lint/format, and typing commands in `AGENTS.md`. C2-01 authorized only the docs guard, so no green result is claimed for the unrun full battery; network/paper/per-host gates retain their stated external prerequisites.
- No outcome contact occurred. This card is N-neutral: **N remains 12**.
