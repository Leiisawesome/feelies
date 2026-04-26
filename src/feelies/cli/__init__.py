"""Operator command-line surface for the feelies platform.

This package hosts the ``feelies`` console script (registered via
``[project.scripts]`` in ``pyproject.toml``) and any subcommand
modules that operate over the platform's durable artefacts — most
notably the append-only :mod:`feelies.alpha.promotion_ledger` written
during alpha-lifecycle transitions.

Workstream F-3 introduced this package with the ``feelies promote``
subcommand tree:

- :command:`feelies promote inspect <alpha_id>` — render every
  ledger entry for one alpha as a chronological timeline.
- :command:`feelies promote list` — summarise every alpha that
  appears in the ledger (current state + transition count).
- :command:`feelies promote replay-evidence <alpha_id>` — re-run the
  F-2 :func:`feelies.alpha.promotion_evidence.validate_gate`
  dispatcher against every promotion-style entry recorded for the
  alpha and report any evidence that no longer satisfies the
  current :class:`feelies.alpha.promotion_evidence.GateThresholds`.
- :command:`feelies promote validate` — preflight the ledger file:
  parse every line, surface malformed entries, confirm
  :data:`feelies.alpha.promotion_ledger.LEDGER_SCHEMA_VERSION`
  compatibility.
- :command:`feelies promote gate-matrix` — print the F-2 declarative
  gate matrix in human-readable or JSON form.

Determinism contract — the CLI is **read-only and forensic-only**.
It never writes to the ledger and never imports orchestrator /
risk-engine production code.  Operator invocation cannot perturb
replay (audit A-DET-02) because nothing the CLI does is reachable
from the per-tick hot path.
"""

from feelies.cli.main import main

__all__ = ["main"]
