"""Per-event parity coverage table, derived from evidence/parityscan.json.

Read-only reporter: prints declared/hashed/unhashed field counts per event class
so the Phase 0 write-up cites measured numbers rather than hand counts.
"""

from __future__ import annotations

import json
import pathlib

EVIDENCE = pathlib.Path(__file__).resolve().parent / "evidence"


def main() -> None:
    data = json.loads((EVIDENCE / "parityscan.json").read_text(encoding="utf-8"))
    declared = data["declared_fields_by_event"]
    missing = data["fields_in_no_parity_hash"]

    rows = []
    for event in sorted(declared):
        if event == "Event":
            continue
        total = len(declared[event])
        unhashed = len(missing.get(event, []))
        rows.append((event, total, total - unhashed, unhashed))

    print("event                        declared  hashed  unhashed")
    for event, total, hashed, unhashed in rows:
        print(f"{event:28}{total:>9}{hashed:>8}{unhashed:>10}")

    full = [r[0] for r in rows if r[3] == 0]
    none = [r[0] for r in rows if r[2] == 0]
    print()
    print(f"event types scanned: {len(rows)}")
    print(f"fully covered ({len(full)}): {full}")
    print(f"zero coverage ({len(none)}): {none}")
    print(f"float precision histogram: {data['float_precision_histogram']}")
    print(f"hash helpers: {data['n_hash_helpers']}")
    print(f"distinct hashed field names: {len(data['all_hashed_field_names'])}")


if __name__ == "__main__":
    main()
