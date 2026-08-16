# INSTALL — Windows / PowerShell

Step One of `RUNBOOK.md`, written out exactly for Windows. Seven blocks. Run them in order, each from **PowerShell**, and check the stated result before moving to the next.

Three Windows-specific things this handles, which the generic instructions do not:

- The `.sh` scripts will not run without Git Bash — PowerShell `.ps1` equivalents are included.
- Files extracted from a downloaded `.zip` carry the Mark of the Web, which **blocks `.ps1` execution** until unblocked.
- `python3` usually does not exist on Windows; the command is `python` or `py`.

---

## 0. Preflight — confirm your tools

```powershell
git --version
python --version
```

Expected: git 2.x, Python 3.x.

If `python --version` opens the Microsoft Store or prints nothing, try `py --version` instead and use `py` everywhere below. If neither works, install Python 3 and tick **"Add python.exe to PATH"** during install.

---

## 1. Go to the repository root

```powershell
cd C:\path\to\feelies
Test-Path src\feelies
```

Replace the path with your clone. Expected: `True`.

If it prints `False` you are in the wrong directory — everything below assumes the repo root, the folder containing `src\`, `alphas\`, and `pyproject.toml`.

---

## 2. Extract the pack

Assuming the download landed in `Downloads`:

```powershell
$Zip  = "$HOME\Downloads\feelies-arch-pack.zip"
$Dest = "$HOME\Downloads\feelies-arch-pack"

Expand-Archive -Path $Zip -DestinationPath $Dest -Force
$Pack = Join-Path $Dest 'feelies-arch'
Get-ChildItem $Pack -Recurse -File | Select-Object -ExpandProperty FullName
```

Expected: 20 files listed — `RUNBOOK.md`, `INSTALL-WINDOWS.md`, `arch-guardrail.mdc`, nine files under `prompts\`, and five under `tools\arch\`.

If the listing shows a nested `feelies-arch\feelies-arch`, set `$Pack` to the inner one.

---

## 3. Unblock the downloaded files

**Do not skip this.** Without it, PowerShell refuses to run `setup.ps1` with a security error.

```powershell
Get-ChildItem $Pack -Recurse -File | Unblock-File
```

Expected: no output. Silence means success.

---

## 4. Create the destination folders

```powershell
'docs\architecture\target\prompts',
'docs\architecture\target\out',
'tools\arch\evidence',
'.cursor\rules' | ForEach-Object { New-Item -ItemType Directory -Force -Path $_ | Out-Null }

Test-Path '.cursor\rules'
```

Expected: `True`.

---

## 5. Copy the pack into the repo

```powershell
Copy-Item "$Pack\prompts\*.md"          'docs\architecture\target\prompts\' -Force
Copy-Item "$Pack\RUNBOOK.md"            'docs\architecture\target\'         -Force
Copy-Item "$Pack\INSTALL-WINDOWS.md"    'docs\architecture\target\'         -Force
Copy-Item "$Pack\tools\arch\*"          'tools\arch\'                       -Force
Copy-Item "$Pack\arch-guardrail.mdc"    '.cursor\rules\'                    -Force

Get-ChildItem 'docs\architecture\target\prompts' -Name
Get-ChildItem 'tools\arch' -File -Name
```

Expected from the first listing — nine files:

```
00_CORE.md
P0_comprehension.md
P1_plumbing.md
P2_contracts.md
P3_flow_gating.md
P4_performance.md
P5_gap_table.md
P6_conformance.md
P7_migration.md
```

Expected from the second — five files: `check_scope.ps1`, `check_scope.sh`, `measure.py`, `setup.ps1`, `setup.sh`.

---

## 6. Verify the pre-derived CONFIG still matches your repo

The CONFIG block in `measure.py` is already filled in from `Leiisawesome/feelies @ main` as of 2026-08-14. This checks whether main has moved since.

```powershell
python tools\arch\measure.py discover
```

Expected, roughly:

```
# bus public API (src/feelies/bus/event_bus.py), with call-site counts:
#   publish          48
#   subscribe        32
#   subscribe_all    0   <-- DEAD API

ALPHA_IDS = [
    "my_portfolio_alpha",
    "my_signal_alpha",
    "paper_smoke_v1",
    "pro_burst_revert_v1",
    "pro_kyle_benign_v1",
    "sig_benign_midcap_v1",
    "sig_contra_fixture_v1",
    "sig_hawkes_burst_v1",
    "sig_inventory_revert_v1",
    "sig_kyle_drift_v1",
    "sig_moc_imbalance_v1",
]
```

**If the alpha list or the bus method names differ**, open `tools\arch\measure.py`, paste the new `ALPHA_IDS` over the old one, and adjust `BUS_PUBLISH` / `BUS_SUBSCRIBE` to match. Ignore the `SYMBOL_LITERALS` suggestions — that heuristic is noisy and the hand-picked list in CONFIG is better.

**Do not edit CONFIG again after this point.** Changing the measurement mid-review invalidates the evidence.

---

## 7. Run setup

```powershell
powershell -ExecutionPolicy Bypass -File tools\arch\setup.ps1
```

This creates the branch `arch/target-design`, makes the directories, runs the full measurement pass, and commits the baseline.

Expected tail, as of 2026-08-14:

```
modules: 196 files, 43197 sloc
  largest:
      4778  src/feelies/kernel/orchestrator.py
imports: 159 modules, 609 internal edges, 2 cycle(s)
clock: 22 wall-clock call sites
nondet: 34 candidate sites
bus: 48 publish, 32 subscribe call sites
handlers: 16 non-bus dispatch call sites
gates: 153 guard-like functions, 1 silent except blocks
alphaleak: 2 LEAK(S)
    [alpha_id] src/feelies/core/platform_config.py:108  ...
    [alpha_id] src/feelies/core/platform_config.py:910  ...
```

**If your numbers differ materially, main has moved.** That is worth knowing before Phase 0 — the RUNBOOK baseline and this evidence should agree.

Install is complete. Confirm:

```powershell
git rev-parse --abbrev-ref HEAD
git log --oneline -1
Get-ChildItem tools\arch\evidence -Name
```

Expected: branch `arch/target-design`, one commit `arch: scaffold target-design review, baseline evidence`, and eight `.json` evidence files plus `.gitkeep`.

---

## Windows command translations for the RUNBOOK

The RUNBOOK's acceptance commands are written for bash. Use these instead:

| RUNBOOK says | On PowerShell run |
|---|---|
| `bash tools/arch/check_scope.sh` | `powershell -ExecutionPolicy Bypass -File tools\arch\check_scope.ps1` |
| `bash tools/arch/setup.sh` | `powershell -ExecutionPolicy Bypass -File tools\arch\setup.ps1` |
| `python3 tools/arch/measure.py ...` | `python tools\arch\measure.py ...` |

Cursor's integrated terminal on Windows defaults to PowerShell, so the agent will hit the same translation. Add this line to the top of each phase's GO prompt:

```
This is Windows/PowerShell. Use `python` not `python3`, and run the scope
guard as `powershell -ExecutionPolicy Bypass -File tools\arch\check_scope.ps1`.
```

---

## If something goes wrong

| Symptom | Cause | Fix |
|---|---|---|
| `...ps1 cannot be loaded because running scripts is disabled` | Execution policy | Use the `-ExecutionPolicy Bypass` form shown above |
| `...ps1 is not digitally signed` | Mark of the Web | Re-run step 3, `Unblock-File` |
| `python` opens Microsoft Store | Python not installed, PATH alias only | Install Python 3 with "Add to PATH", or use `py` |
| `Not inside a git repository` | Wrong directory | `cd` to the repo root, the folder with `src\` in it |
| `src\feelies not found` | Ran from `tools\arch` | `cd` back to the repo root |
| `measure.py bus` reports 0 publish sites | CONFIG mismatch | Re-run step 6 and paste the discovered values |
| `fatal: a branch named 'arch/target-design' already exists` **and the script stops** | You have an old `setup.ps1`. PowerShell 5.1 turns redirected native stderr into a terminating error. | Replace `tools\arch\setup.ps1` with the current version and re-run. It is idempotent. |
| Evidence JSON has Windows line endings in git diff | `core.autocrlf` | Harmless — evidence is read by the agent, not diffed |
