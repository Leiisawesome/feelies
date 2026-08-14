#!/usr/bin/env bash
# Protocol guard. Run at every hard stop, before accepting a phase output.
# CORE §H permits writes only under docs/architecture/target/out/ and tools/arch/.
set -uo pipefail

PROTECTED=(src tests alphas configs pyproject.toml platform.yaml)

DIRTY=$(git status --porcelain -- "${PROTECTED[@]}" 2>/dev/null)

if [ -n "$DIRTY" ]; then
  echo "PROTOCOL VIOLATION -- protected paths modified:"
  echo "$DIRTY"
  echo
  echo "Revert before accepting this phase output:"
  echo "  git checkout -- ${PROTECTED[*]}"
  exit 1
fi

echo "scope: OK -- no protected-path changes"
