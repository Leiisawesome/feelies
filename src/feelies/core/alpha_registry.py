"""AlphaRegistry — registered-alpha lookup protocol.

The Protocol lives in core so kernel can name it without importing the
alpha package.
"""

from __future__ import annotations

from typing import Protocol


class _AlphaManifest(Protocol):
    version: str


class _RegisteredAlpha(Protocol):
    manifest: _AlphaManifest


class AlphaRegistry(Protocol):
    """Lookup of loaded alphas; kernel and report consumers share this surface."""

    def has_portfolio_alphas(self) -> bool:
        """True iff at least one ``layer: PORTFOLIO`` alpha is registered."""
        ...

    def alpha_ids(self) -> frozenset[str]:
        """Set of all registered alpha IDs."""
        ...

    def get(self, alpha_id: str) -> _RegisteredAlpha:
        """Retrieve a registered alpha by ID."""
        ...

    def get_lifecycle(self, alpha_id: str) -> object | None:
        """Lifecycle record for *alpha_id*, or ``None`` if untracked."""
        ...
