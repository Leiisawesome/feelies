#!/usr/bin/env bash
# One-time setup. Run once from the repo root, before Phase 0.
set -euo pipefail

git rev-parse --is-inside-work-tree >/dev/null

echo "==> branch"
git checkout -b arch/target-design 2>/dev/null || git checkout arch/target-design

echo "==> directories"
mkdir -p docs/architecture/target/prompts
mkdir -p docs/architecture/target/out
mkdir -p tools/arch/evidence

echo "==> ignore evidence churn in normal diffs, keep it committed on this branch"
touch tools/arch/evidence/.gitkeep

echo "==> permissions"
chmod +x tools/arch/*.sh 2>/dev/null || true

echo "==> generating evidence (Phase 0 input)"
python3 tools/arch/measure.py all

echo
echo "==> commit the baseline"
git add docs/architecture/target tools/arch .cursor/rules/arch-guardrail.mdc
if git diff --cached --quiet; then
    echo "nothing new to commit"
else
    git commit -m "arch: scaffold target-design review, baseline evidence" -q
fi
echo "done. Next: run Phase 0 (see RUNBOOK.md)."
