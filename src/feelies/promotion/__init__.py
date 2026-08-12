"""Alpha lifecycle, promotion gates, and the append-only promotion ledger.

Split out of ``feelies.alpha`` on 2026-08-12. That package conflated three
concerns under one name: turning alpha YAML into a loaded module (loader,
layer_validator, discovery, *_layer_module), running one at a time (registry,
risk_wrapper, arbitration, fill_attribution), and deciding whether an alpha may
hold capital — which is this package.

Nothing here runs on the tick path. The ledger is append-only and forensic
(``platform-invariants.mdc``: "Never read on the tick path"); evidence schemas
and gate validation are consulted at promotion time by ``feelies promote``.
``AlphaRegistry`` holds a ledger reference and drives lifecycle transitions, so
``feelies.alpha`` depends on this package — never the reverse.

No re-exports: import from the defining module. The old ``feelies.alpha``
package ``__init__`` re-exported this surface and had no consumer anywhere in
``src/``, ``tests/`` or ``scripts/``, which is how 111 lines of export list
drifted unnoticed.
"""
