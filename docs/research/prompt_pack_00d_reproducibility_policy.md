<!--
  File:   docs/research/prompt_pack_00d_reproducibility_policy.md
  Status: NORMATIVE — reproducibility policy under cross-host libm
          variation (Task FQ-3, 2026-07-07). Resolves OQ-5 of
          docs/research/prompt_pack_00_architecture_verification.md.
          Binding on Task 10's determinism proof and Task 13's closure.
  Owner:  testing-validation (parity manifest) / cross-cutting
          (evidence provenance); prompt-pack Task FQ-3, Phase A.
-->

# Prompt-pack Task FQ-3 — Reproducibility policy under cross-host libm variation

Context: locked parity hashes guarantee bit-identical replay on a fixed
(platform, libm) pair only. Sensors calling `math.exp` / `math.log`
depend on the C math library's rounding, which is not guaranteed
correctly-rounded across libm versions; the manifest's own FOLLOW-UP
(per-baseline host/libm fingerprint) is unimplemented
(`tests/determinism/parity_manifest.py:13-27`). IEEE-754 **does** fix
`+`, `−`, `×`, `/`, and `sqrt` to correct rounding, so those paths are
cross-host stable (also stated in
`tests/determinism/test_transcendental_determinism.py:3-6`).

## Policy (codified)

**(A) Same-host self-parity is the pack's acceptance criterion.**
Task 10's determinism proof and Task 13's reproducibility closure
require two runs on the SAME host, same `PYTHONHASHSEED=0`, producing
identical parity hashes and identical evidence values. Cross-host
equality with the pinned baselines is NOT an acceptance criterion of
this pack.

**(B) A locked-baseline failure on the analysis host is diagnosed,
never rebaselined.** Procedure: value-diff the failing stream against a
same-host rerun and against the pinned expectation. If (and only if)
the divergence is confined to last-bit differences in
transcendental-sensor outputs (exp/log paths — see the classification
table for exactly which streams qualify), classify it
**ENVIRONMENT-LIBM** and report it as a finding. Anything else —
count drift, non-last-bit value drift, drift in a stream classified
SAFE below, or drift on a same-host rerun — is treated as a potential
defect and **stops the pack**. An unclassified failure blocks all
evidence-producing tasks. Locked baselines are immutable without
architectural review, regardless of classification (session constraint;
`parity_manifest.py:1-11`, fingerprint guard
`test_parity_manifest.py`).

**(C) Every evidence run's provenance block gains a host fingerprint**
(template below): OS + version, CPU arch, Python build string,
libc/libm identification, git SHA, config checksum, `PYTHONHASHSEED`.

## 1. Empirical result on this host (2026-07-07)

`PYTHONHASHSEED=0 uv run pytest tests/determinism/ -q` →
**126 passed, 4 skipped, 0 failed** (7.7 s). The 4 skips are
`test_sized_intent_solver_replay.py` cvxpy/ECOS solver-path tests gated
on the uninstalled `[portfolio]` extra — unrelated to libm. **The
cross-host concern is currently theoretical on this host**: the pinned
baselines reproduce bit-identically here, so this host can serve as the
same-host reference for Tasks 10–13 without any ENVIRONMENT-LIBM
classification being invoked. The policy is codified anyway because the
analysis host for later runs is not guaranteed to be this one.

Host fingerprint of this run (also the reference instance of the
template in §3):

```yaml
host_fingerprint:
  os: "Windows-11-10.0.26200-SP0"
  cpu_arch: "AMD64"
  python_build: "3.14.2 (tags/v3.14.2:df79316, Dec 5 2025, 17:18:21) [MSC v.1944 64 bit (AMD64)]"
  libm: "Microsoft UCRT (linked by MSC v.1944; platform.libc_ver() = ('', '') on Windows)"
  git_sha: "825a7bc3bda48d3a819fed0a498dbf9d65e711c4"
  config_checksum: "n/a — no PlatformConfig loaded by tests/determinism (fixtures are self-contained)"
  pythonhashseed: "0"
```

## 2. Classification table — where last-bit libm drift is plausible vs impossible

Transcendental call sites feeding hashed streams, verified in source:
`hawkes_intensity.py:152` (exp), `liquidity_stress_score.py:82,202`
(sqrt+exp), `ofi_ewma.py:238` (exp — time-decay alpha),
`snr_drift_diffusion.py:172,210-211` (log+sqrt),
`realized_vol_30s.py:109,137` (log+sqrt),
`structural_break_score.py:182` (log), `spread_z_30d.py:166` (**sqrt
only — safe**), HMM regime engine `services/regime_engine.py:52,336,
844,1027-1155` (log+exp Gaussian emissions/entropy), decay weighting
`composition/cross_sectional.py:299,444,519` (exp),
`features/library.py:185` (sqrt only — safe), permanent impact
`execution/market_fill.py:159-171` (**`Decimal.sqrt` deliberately —
correctly-rounded, platform-independent**).

| Locked baseline | Transcendental exposure | Class | Why |
|---|---|---|---|
| `level1_sensor_reading` | `ofi_ewma` (exp), `realized_vol_30s` (log) | **LIBM-PLAUSIBLE** | fixture runs those sensors (`test_sensor_reading_replay.py:8-11, 35-66`) |
| `level1_v03_sensor_reading` | `hawkes_intensity` (exp), `snr_drift_diffusion` (log), `structural_break_score` (log) | **LIBM-PLAUSIBLE** | `test_v03_sensor_replay.py:8-11, 81-111` |
| `multi_symbol_sensor_reading` | `ofi_ewma` (exp) | **LIBM-PLAUSIBLE** | `test_multi_symbol_sensor_replay.py:24-45` |
| `level3_horizon_feature_snapshot` | `ofi_ewma` (exp) upstream; zscore reducer itself is sqrt-only | **LIBM-PLAUSIBLE** (via sensor values) | `test_horizon_feature_snapshot_replay.py:12-19, 31-68` |
| `level2_signal` | runs `ofi_ewma` upstream but pins the **empty** Signal stream | **INDIRECT-THRESHOLD** (hash of empty stream is libm-immune; a last-bit flip could only matter by flipping a gate comparison, changing the count — which is then NOT last-bit-confined and stops the pack per (B)) | `test_signal_replay.py:54-104` |
| `level6_regime_state` | HMM posteriors (exp/log Gaussian likelihoods) | **LIBM-PLAUSIBLE** | real `engine.posterior(quote)` (`test_regime_state_replay.py:19, 60`) |
| `level3_sized_intent_decay_on` | ranker decay weighting `exp(-age/hl)` | **LIBM-PLAUSIBLE** | `test_sized_intent_with_decay_replay.py:1-9`; `cross_sectional.py:299` |
| `level5_regime_hazard_spike` | none — detector fed hand-built posteriors; hazard score is ratio/clip arithmetic | SAFE | `test_regime_hazard_replay.py:31, 70-143` |
| `level2_horizon_tick` | none — integer boundary math | SAFE | ENG-1 integer boundaries |
| `level3_sized_intent_decay_off` | none on the hashed path (cross-sectional std is sqrt — correctly rounded) | SAFE | `cross_sectional.py:603` |
| `level4_portfolio_order`, `level4_hazard_exit_order` | none — synthetic spikes / intent-to-order arithmetic | SAFE | `test_hazard_exit_replay.py:5, 61-71` |
| `market_fill_acks` | none — Decimal arithmetic; `Decimal.sqrt` for permanent impact | SAFE (by design) | `market_fill.py:159-171` |
| `position_pnl`, `state_transition`, `cross_sectional_context`, `risk_verdict` | none — Decimal/FIFO/SM/ratio arithmetic | SAFE | fixture inspection |
| `signal_fires`, `reference_alpha_signal_fires` | none — snapshots built from literal feature values, no sensor pipeline | SAFE | `test_signal_fires_replay.py:43-127`; `test_reference_alpha_signal_fires_replay.py:26-82` |
| `symbol_halted`, `halt_order`, `halt_ack`, `halt_position_update` | none — condition-code driven halt walk | SAFE | fixture inspection |

Triage rule from the table: an ENVIRONMENT-LIBM classification is only
admissible for the six baselines marked LIBM-PLAUSIBLE. Last-bit
drift in any SAFE baseline is a defect, full stop. The classification
table above is authoritative over any prose count; in particular,
`level2_signal` is INDIRECT-THRESHOLD — drift there stops the pack and
is never admissible as ENVIRONMENT-LIBM.

Two manifest-caveat corrections surfaced by this enumeration (fold into
the separate thread of §4; they change documentation, not baselines):

1. `ofi_ewma` calls `math.exp` (`ofi_ewma.py:238`) but is **missing**
   from the manifest's cross-libm caveat list
   (`parity_manifest.py:16-18`), despite being the most widely
   exercised sensor in the locked fixtures.
2. `liquidity_stress_score` is **in** the caveat list but exercised by
   **no** locked baseline (no determinism fixture instantiates it) —
   the caveat is currently aspirational for that sensor.

## 3. Provenance-block template (Tasks 10–13 copy verbatim)

Every evidence run (backtest report, CPCV/DSR evidence, determinism
proof, closure artifact) embeds:

```yaml
host_fingerprint:
  os: "<platform.platform()>"
  cpu_arch: "<platform.machine()>"
  python_build: "<sys.version, one line>"
  libm: "<libc/libm id: platform.libc_ver() on POSIX; 'Microsoft UCRT (MSC vNNNN)' on Windows from the sys.version compiler tag>"
  git_sha: "<git rev-parse HEAD; append '-dirty' if the working tree differs>"
  config_checksum: "<PlatformConfig.snapshot().checksum of the run's config>"
  pythonhashseed: "<os.environ['PYTHONHASHSEED']; must be '0' for evidence runs>"
  worktree_clean: "yes/no (git status --porcelain empty)"
```

Rule: evidence-producing runs require `worktree_clean: yes`. (Approved
Task 3a step 4, 2026-07-08.)

Generation snippet (uses only stdlib + the loaded config; no wall-clock
dependency — the block is provenance, not a timestamp):

```python
import os, sys, platform

def host_fingerprint(config, git_sha: str) -> dict[str, str]:
    libc = platform.libc_ver()
    libm = (
        f"{libc[0]} {libc[1]}".strip()
        or f"Microsoft UCRT ({sys.version.split('[')[1].rstrip(']')})"
    )
    return {
        "os": platform.platform(),
        "cpu_arch": platform.machine(),
        "python_build": " ".join(sys.version.split()),
        "libm": libm,
        "git_sha": git_sha,
        "config_checksum": config.snapshot().checksum,
        "pythonhashseed": os.environ.get("PYTHONHASHSEED", "<unset>"),
    }
```

Acceptance hook: Task 10's determinism proof asserts the two same-host
runs carry **identical** `host_fingerprint` blocks (all fields) before
comparing hashes; Task 13's closure quotes the block alongside the
evidence values.

## 4. Separate scoped-thread proposal (NOT this pack)

**Thread: implement the parity-manifest FOLLOW-UP — per-baseline
host/libm fingerprint provenance.** Scope: extend
`tests/determinism/parity_manifest.py` (or a sidecar
`parity_manifest_provenance.py`) to record, per locked baseline, the
host fingerprint (fields of §3) of the host that pinned it; add tests
that (a) the provenance record exists for every manifest entry, (b) the
recorded fingerprint schema is stable, and (c) a cross-host mismatch
report can name the (pinned-host, current-host) libm pair. Constraints:
**must not alter any baseline hash or count** (the manifest fingerprint
`EXPECTED_MANIFEST_FINGERPRINT` must be byte-identical before/after);
provenance is a new sidecar, not a manifest-value change. Also fold in
the two caveat-list corrections from §2 (add `ofi_ewma`; annotate
`liquidity_stress_score` as not currently exercised by any locked
baseline). Owner per the manifest's own note: data-ingestion /
determinism harness (`parity_manifest.py:23-27`).

**OQ-5 is RESOLVED for this pack by policy (A)/(B)/(C); the cross-host
fingerprint gap is delegated to the thread above.**
