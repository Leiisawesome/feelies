# Phase 14E: calibration and evaluation (gate for campaign 15)

Status: setup (stage 1). Bar: docs/architecture/target/position_engine/evaluation.md
section 4 (lines 145-173 at d26fd6ea), registered before any engine-on result. On
failure campaign 15 does not start: fix the engine or the calibration, never the bar.

## State (D-260)

- Integration branch: arch/exec. Protected: main.
- Plan: this file. Ledger: docs/architecture/target/out/exec/LEDGER_14E.md from
  T-18; T-16 and T-17 are recorded in LEDGER.md under contract version 8.
- Decisions: docs/architecture/target/position_engine/decisions.md (one D-id space).
- Findings: a generated 14E register (T-18).
- Contract: .cursor/rules/exec-guardrail.mdc, version 9 from T-17.

## Data (D-259)

- Universe: APP, CROX, DIOD, ENSG, MLI, OLN, PCTY, RMBS.
- In-sample, calibration only: every cached day whose manifest has
  ingestion_health HEALTHY and event_count > 0; the list is generated, never
  hand-picked.
- Embargo: 2026-07-23 to 2026-07-31, never used.
- Out-of-sample, evaluation only: every regular session from 2026-08-03 to
  2026-10-30 on the exchange calendar; half days kept and tagged.
- Read barrier: no out-of-sample day is fetched or read until this plan fixes
  delta, the alpha and configuration set, and the configuration counter N. The
  fetch is its own per-run operator authorisation; a fetched day that is not
  HEALTHY with event_count > 0 is a STOP.

## Ladder

| Rung | Stage | Lands | Gate | Parity |
|---|---|---|---|---|
| T-16 | setup | open. 14E state files (this plan, LEDGER_14E.md); D-258 to D-262: main event cache, data split, state, cleanup, setup decisions. Docs only. | operator | hold |
| T-17 | setup | open. Contract version 9 (D-260): 14E paths, fetch-authorisation rule, configuration counter N, main event-cache rule (D-258), repository-location decision (F-C16-6). | operator | hold |
| T-18 | setup | open. Generated 14E findings register, seeded from the CARRIED-14E items, F-C16-1, F-C16-6 and F-C16-7. | operator | hold |

Rows after T-18 are added by plan amendment once stage-1 design fixes them.

## Open (operator decisions)

- delta, the alpha and configuration set under evaluation, and the counter N
  (before any out-of-sample read).
- Out-of-sample fetch authorisation (D-259).
- Repository location outside OneDrive (F-C16-6).
- Nightly dispatch that runs reference battery (real) (F-C16-7).
- Local PYTHONHASHSEED; exposure-cap policy including in-flight orders (F-P23g-9,
  F-P23g-13, F-P23b2-18); default fill-report latency; maker adverse-selection
  calibration; feelies-probes disk use.
- F-P23b-c (HIGH): check whether D-191 closed it.

## Carried into 14E

F-P13, F-P23c-f, F-P23c-g, F-P23c-l, F-P23c-m, F-P23e-8, F-P23e-9, F-P23f-9,
F-P99a-1, F-P99b-2 (P-99c register, D-255); F-C16-1 (D-257).
