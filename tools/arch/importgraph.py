#!/usr/bin/env python3
"""
Grimp-backed import graph for the five-tier / twelve-engine contracts.

Phase 3 named grimp as the evidence producer for the static graph that
import-linter reasons over.  This script is that producer: it builds the
installed ``feelies`` graph, records edges, Tarjan SCCs of size > 1, and the
G16 chain ``core.inv12_stress -> core.platform_config -> promotion.evidence``.

Writes evidence/importgraph.json.

Usage:
    python tools/arch/importgraph.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import grimp

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "tools" / "arch" / "evidence"

G16_CHAIN = (
    "feelies.core.inv12_stress",
    "feelies.core.platform_config",
    "feelies.promotion.evidence",
)


def rel(p: Path) -> str:
    return str(p.relative_to(ROOT)).replace("\\", "/")


def tarjan_sccs(graph: dict[str, list[str]]) -> list[list[str]]:
    index, low, on, stack, out, counter = {}, {}, set(), [], [], [0]
    sys.setrecursionlimit(10000)

    def strong(v: str) -> None:
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on.add(v)
        for w in graph.get(v, []):
            if w not in index:
                strong(w)
                low[v] = min(low[v], low[w])
            elif w in on:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp = []
            while True:
                w = stack.pop()
                on.discard(w)
                comp.append(w)
                if w == v:
                    break
            if len(comp) > 1:
                out.append(sorted(comp))

    for v in list(graph):
        if v not in index:
            strong(v)
    return out


def build() -> dict[str, object]:
    g = grimp.build_graph("feelies")
    modules = sorted(g.modules)
    edges: dict[str, list[str]] = {}
    for m in modules:
        imported = sorted(t for t in g.find_modules_directly_imported_by(m) if t in g.modules)
        if imported:
            edges[m] = imported

    cycles = tarjan_sccs(edges)
    chain_hops = []
    present = True
    for a, b in zip(G16_CHAIN, G16_CHAIN[1:]):
        hop = g.find_shortest_chain(a, b)
        chain_hops.append({"from": a, "to": b, "chain": list(hop) if hop else None})
        if hop is None:
            present = False

    return {
        "n_modules": len(modules),
        "n_edges": sum(len(v) for v in edges.values()),
        "n_cycles": len(cycles),
        "cycles": cycles,
        "g16_chain": list(G16_CHAIN),
        "g16_chain_present": present,
        "g16_chain_hops": chain_hops,
        "edges": edges,
    }


def main() -> None:
    payload = build()
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    out = EVIDENCE / "importgraph.json"
    out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"importgraph -> {rel(out)}")
    print(
        f"  modules: {payload['n_modules']}, edges: {payload['n_edges']}, "
        f"cycles: {payload['n_cycles']}"
    )
    for cyc in payload["cycles"]:
        print(f"      {' -> '.join(cyc)}")
    present = "PRESENT" if payload["g16_chain_present"] else "absent"
    print(f"  G16 chain ({present}): {' -> '.join(G16_CHAIN)}")


if __name__ == "__main__":
    main()
