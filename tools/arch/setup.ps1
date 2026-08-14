<#
  One-time setup. Run ONCE from the repository root.

      powershell -ExecutionPolicy Bypass -File tools\arch\setup.ps1

  Creates the review branch, the directory tree, runs the full measurement
  pass, and commits the baseline evidence.
#>

$ErrorActionPreference = 'Stop'

function Get-Python {
    foreach ($c in @('python', 'py', 'python3')) {
        $exe = Get-Command $c -ErrorAction SilentlyContinue
        if ($exe) {
            $v = & $c --version 2>&1
            if ($v -match 'Python 3') { return $c }
        }
    }
    throw "No Python 3 interpreter found on PATH. Install Python 3 or add it to PATH."
}

# --- preflight -------------------------------------------------------------

git rev-parse --is-inside-work-tree *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Not inside a git repository. cd to the feelies repo root first."
}

if (-not (Test-Path 'src\feelies')) {
    throw "src\feelies not found. Run this from the repository ROOT, not from tools\arch."
}

$py = Get-Python
Write-Host "==> python: $py ($(& $py --version 2>&1))"

# --- branch ----------------------------------------------------------------

Write-Host "==> branch"
git checkout -b arch/target-design *> $null
if ($LASTEXITCODE -ne 0) {
    git checkout arch/target-design
    if ($LASTEXITCODE -ne 0) { throw "Could not create or switch to arch/target-design." }
}
Write-Host "    on $(git rev-parse --abbrev-ref HEAD)"

# --- directories -----------------------------------------------------------

Write-Host "==> directories"
foreach ($d in @('docs\architecture\target\prompts',
                 'docs\architecture\target\out',
                 'tools\arch\evidence')) {
    New-Item -ItemType Directory -Force -Path $d | Out-Null
}
New-Item -ItemType File -Force -Path 'tools\arch\evidence\.gitkeep' | Out-Null

# --- measurement -----------------------------------------------------------

Write-Host "==> generating evidence (Phase 0 input)"
& $py tools\arch\measure.py all
if ($LASTEXITCODE -ne 0) { throw "measure.py failed. Fix before continuing." }

# --- commit ----------------------------------------------------------------

Write-Host ""
Write-Host "==> commit the baseline"
git add docs/architecture/target tools/arch
git commit -m "arch: scaffold target-design review, baseline evidence" -q
if ($LASTEXITCODE -ne 0) { Write-Host "    (nothing to commit)" }

Write-Host ""
Write-Host "done. Next: run Phase 0 (see RUNBOOK.md)." -ForegroundColor Green
