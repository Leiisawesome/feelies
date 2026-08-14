<#
  One-time setup. Run from the repository ROOT.

      powershell -ExecutionPolicy Bypass -File tools\arch\setup.ps1

  Idempotent -- safe to re-run after a partial failure.

  NOTE ON ERROR HANDLING (this script previously had a bug here):
  PowerShell 5.1 converts native-command stderr into ErrorRecords when the
  stream is redirected. With $ErrorActionPreference = 'Stop' that makes benign
  git messages -- "Switched to branch", "a branch already exists" -- into
  terminating errors. So this script sets 'Continue' and checks $LASTEXITCODE
  explicitly after every native call. Do not set 'Stop' here.
#>

$ErrorActionPreference = 'Continue'
$Branch = 'arch/target-design'

function Die([string]$msg) {
    Write-Host ""
    Write-Host "FAILED: $msg" -ForegroundColor Red
    exit 1
}

function Get-Python {
    foreach ($c in @('python', 'py', 'python3')) {
        if (Get-Command $c -ErrorAction SilentlyContinue) {
            $v = (& $c --version 2>&1 | Out-String).Trim()
            if ($v -match 'Python 3') { return @{ Cmd = $c; Version = $v } }
        }
    }
    Die "No Python 3 interpreter on PATH. Install Python 3 and tick 'Add python.exe to PATH'."
}

# --- preflight -------------------------------------------------------------

& git rev-parse --is-inside-work-tree 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { Die "Not inside a git repository. cd to the feelies repo root." }

if (-not (Test-Path 'src\feelies')) {
    Die "src\feelies not found. Run from the repository ROOT, not from tools\arch."
}
if (-not (Test-Path 'tools\arch\measure.py')) {
    Die "tools\arch\measure.py not found. Complete install step 5 first."
}

$py = Get-Python
Write-Host "==> python: $($py.Cmd) ($($py.Version))"

# --- branch (idempotent) ---------------------------------------------------

Write-Host "==> branch"

# show-ref --verify --quiet is silent on both paths: exit 0 exists, 1 does not.
& git show-ref --verify --quiet "refs/heads/$Branch"
$exists = ($LASTEXITCODE -eq 0)

if ($exists) {
    Write-Host "    '$Branch' already exists -- switching to it"
    & git checkout $Branch 2>&1 | ForEach-Object { Write-Host "    $_" }
} else {
    Write-Host "    creating '$Branch'"
    & git checkout -b $Branch 2>&1 | ForEach-Object { Write-Host "    $_" }
}
if ($LASTEXITCODE -ne 0) {
    Die "Could not switch to $Branch. Commit or stash your working-tree changes first."
}

$current = (& git rev-parse --abbrev-ref HEAD | Out-String).Trim()
if ($current -ne $Branch) { Die "Expected HEAD on $Branch, found $current." }
Write-Host "    on $current"

# --- directories -----------------------------------------------------------

Write-Host "==> directories"
foreach ($d in @('docs\architecture\target\prompts',
                 'docs\architecture\target\out',
                 'tools\arch\evidence')) {
    New-Item -ItemType Directory -Force -Path $d -ErrorAction Stop | Out-Null
    Write-Host "    $d"
}
if (-not (Test-Path 'tools\arch\evidence\.gitkeep')) {
    New-Item -ItemType File -Force -Path 'tools\arch\evidence\.gitkeep' | Out-Null
}

# --- measurement -----------------------------------------------------------

Write-Host "==> generating evidence (Phase 0 input)"
& $py.Cmd tools\arch\measure.py all
if ($LASTEXITCODE -ne 0) { Die "measure.py failed. Fix before continuing -- bad evidence is worse than none." }

# --- commit ----------------------------------------------------------------

Write-Host ""
Write-Host "==> commit the baseline"
& git add docs/architecture/target tools/arch
if ($LASTEXITCODE -ne 0) { Die "git add failed." }

# diff --cached --quiet: exit 0 means nothing staged, 1 means changes staged.
& git diff --cached --quiet
if ($LASTEXITCODE -eq 0) {
    Write-Host "    nothing new to commit"
} else {
    & git commit -m "arch: scaffold target-design review, baseline evidence" 2>&1 |
        ForEach-Object { Write-Host "    $_" }
    if ($LASTEXITCODE -ne 0) { Die "git commit failed." }
}

# --- report ----------------------------------------------------------------

$jsonCount = (Get-ChildItem 'tools\arch\evidence' -Filter *.json -ErrorAction SilentlyContinue).Count

Write-Host ""
Write-Host "done. Next: run Phase 0 (see RUNBOOK.md)." -ForegroundColor Green
Write-Host "  branch:   $((& git rev-parse --abbrev-ref HEAD | Out-String).Trim())"
Write-Host "  evidence: $jsonCount json files in tools\arch\evidence"
if ($jsonCount -lt 8) {
    Write-Host "  WARNING: expected 8 evidence files. Re-run: $($py.Cmd) tools\arch\measure.py all" -ForegroundColor Yellow
}
