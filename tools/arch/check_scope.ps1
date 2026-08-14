<#
  Protocol guard. Run at EVERY hard stop, before accepting a phase output.
  CORE section H permits writes only under docs/architecture/target/out/
  and tools/arch/.

      powershell -ExecutionPolicy Bypass -File tools\arch\check_scope.ps1
#>

$protected = @('src', 'tests', 'alphas', 'configs', 'pyproject.toml', 'platform.yaml')

$dirty = git status --porcelain -- $protected

if ($dirty) {
    Write-Host "PROTOCOL VIOLATION -- protected paths modified:" -ForegroundColor Red
    $dirty | ForEach-Object { Write-Host "  $_" }
    Write-Host ""
    Write-Host "Revert before accepting this phase output:"
    Write-Host "  git checkout -- $($protected -join ' ')"
    exit 1
}

Write-Host "scope: OK -- no protected-path changes" -ForegroundColor Green
exit 0
