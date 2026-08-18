#!/usr/bin/env python3
"""
Declared-vs-actual verification for a migration step.

Parses docs/architecture/target/out/phase7_migration.md, extracts the step's
declared FILES / PARITY IMPACT / DELETES / NET DELTA / BLAST RADIUS, and checks
reality against them. A step that did something it did not declare fails here.

Usage:
    uv run python tools/exec/verify_step.py --list
    uv run python tools/exec/verify_step.py S-07 --base <sha>
    uv run python tools/exec/verify_step.py --reconcile

Exit codes: 0 clean, 1 mismatch, 2 usage/parse error.

This tool NEVER modifies anything.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / "docs" / "architecture" / "target" / "out" / "phase7_migration.md"
LEDGER = ROOT / "docs" / "architecture" / "target" / "out" / "exec" / "LEDGER.md"
EXEC_OUT = ROOT / "docs" / "architecture" / "target" / "out" / "exec"
MANIFEST = ROOT / "tests" / "determinism" / "parity_manifest.py"

STEP_ID = re.compile(r"^\s*STEP:\s*(S-\d+[a-z]?(?:\.\d+)?)", re.M)
FIELD = re.compile(r"^\s*([A-Z][A-Z /]*[A-Z]):\s*(.*)$")
FENCE = re.compile(r"^\s*(?:```|~~~)")
HEADING = re.compile(r"^#{1,6}\s")
KNOWN = {"STEP", "CLOSES", "PROBLEM", "FILES", "WHY THIS OWNER", "REFACTOR PATH",
         "BLAST RADIUS", "VALIDATED BY", "PARITY IMPACT", "DELETES", "NET DELTA",
         "ROLLBACK"}

# Path-like tokens only. Prose inside a FILES field must not become a fake entry.
DIRPATH = re.compile(r"(?:[\w.\-]+[/\\])+(?=[\s,;)\]]|$)")
PATHY = re.compile(
    r"(?:[\w.\-]+[/\\])+[\w.\-]+\.\w+"
    r"|(?<![\w./\\])[\w.\-]+\.(?:py|md|yaml|yml|toml|json|mdc|cfg|ini|txt|sh|ps1)\b"
)

# Parity constants may be named as EXPECTED_* / _BASELINE_* -- the full set
# baseline.py captures (EXPECTED_* under tests/determinism/ plus the APP
# acceptance oracle's _BASELINE_* constants) -- or by the owning test module.
# Manifest short-keys (e.g. level4_hazard_exit_order) are resolved against the
# moved constants at the step gate (cmd_step). Show the raw text either way.
HASHNAME = re.compile(
    r"(?<![A-Za-z0-9_])(?:EXPECTED_[A-Z0-9_]+|_BASELINE_[A-Z0-9_]+)")
TESTMOD = re.compile(r"tests[/\\]determinism[/\\][\w.\-]+\.py")

BLAST_ORDER = {"local": 1, "boundary": 2, "platform-wide": 3}

# Paths written by the execution process itself. They appear in every diff and
# are not source changes, so they are excluded from the declared-files check.
# Everything else -- including all of src/ and tests/ -- must be declared.
PROCESS_ARTIFACTS = (
    "docs/architecture/target/out/",
    "tools/exec/",
    "tools/arch/evidence/",
)


def is_artifact(path: str) -> bool:
    p = path.replace("\\", "/")
    return any(p.startswith(prefix) for prefix in PROCESS_ARTIFACTS)


def run(cmd: list[str]) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, errors="replace")
    return p.returncode, (p.stdout or "").strip()


def _blocks(text: str) -> list[list[str]]:
    """Step blocks, bounded so a block can never run into surrounding prose.

    Preferred: fenced code blocks containing a STEP: line (the P7 template).
    Fallback: from STEP: to the next STEP:, markdown heading, or fence.
    """
    lines = text.splitlines()
    fenced, buf, inside = [], [], False
    for line in lines:
        if FENCE.match(line):
            if inside:
                if any(STEP_ID.match(l) for l in buf):
                    fenced.append(buf)
                buf, inside = [], False
            else:
                buf, inside = [], True
            continue
        if inside:
            buf.append(line)
    if fenced:
        return fenced

    out, cur = [], None
    for line in lines:
        if STEP_ID.match(line):
            if cur:
                out.append(cur)
            cur = [line]
            continue
        if cur is None:
            continue
        if HEADING.match(line) or FENCE.match(line):
            out.append(cur)
            cur = None
            continue
        cur.append(line)
    if cur:
        out.append(cur)
    return out


def parse_plan() -> dict[str, dict[str, str]]:
    if not PLAN.exists():
        print(f"plan not found: {PLAN.relative_to(ROOT)}")
        sys.exit(2)
    text = PLAN.read_text(encoding="utf-8", errors="replace")
    steps: dict[str, dict[str, str]] = {}
    for block in _blocks(text):
        fields, current = {}, None
        for line in block:
            m = FIELD.match(line)
            if m and m.group(1) in KNOWN:
                current = m.group(1)
                fields[current] = m.group(2).strip()
            elif current and line.strip():
                # continuation stays inside the block, which is already bounded
                fields[current] += " " + line.strip()
        sid = fields.get("STEP", "").split()[0] if fields.get("STEP") else None
        if sid:
            steps[sid] = fields
    if not steps:
        print("no parseable 'STEP: S-nn' blocks found. The plan must use the P7 "
              "template field labels verbatim.")
        sys.exit(2)
    return steps


def sort_key(sid: str):
    m = re.match(r"S-(\d+)([a-z]?)", sid)
    return (int(m.group(1)), m.group(2)) if m else (999, sid)


def file_list(v: str) -> list[str]:
    """Path-like tokens only; prose in a FILES field is ignored."""
    return sorted({x.replace("\\", "/") for x in PATHY.findall(v or "")})


def dir_list(v: str) -> list[str]:
    """Directory scopes, e.g. 'src/feelies/alpha/'.

    A legitimate declaration for a step touching hundreds of sites, but a far
    weaker guardrail than an enumerated file list: it permits any change
    anywhere beneath the prefix. cmd_list reports the permitted surface so the
    weakening is visible rather than silent.
    """
    return sorted({x.replace("\\", "/") for x in DIRPATH.findall(v or "")})


def permitted_surface(dirs: list[str]) -> int:
    """How many .py files the declared directory scopes actually permit."""
    n = 0
    for d in dirs:
        base = ROOT / d
        if base.is_dir():
            n += sum(1 for _ in base.rglob("*.py"))
    return n


def blast_class(v: str) -> tuple[str, bool]:
    """-> (most severe class named, whether more than one was named)"""
    low = (v or "").lower()
    found = [c for c in BLAST_ORDER if re.search(rf"\b{re.escape(c)}\b", low)]
    if not found:
        return "unknown", False
    return max(found, key=lambda c: BLAST_ORDER[c]), len(found) > 1


def declared_parity(v: str) -> tuple[str, list[str]]:
    """-> ('hold'|'break'|'unknown', [named constants or test modules])

    The LEADING token decides. Checking for the substring "break" anywhere
    misreads 'hold -- additive, does not break any hashed stream', and naming a
    constant is not itself a declaration of breakage: 'hold -- EXPECTED_X_HASH
    is unaffected' names one precisely because it does not move.
    """
    raw = (v or "").strip()
    names = sorted(set(HASHNAME.findall(raw))
                   | {m.replace("\\", "/") for m in TESTMOD.findall(raw)})

    m = re.match(r"[^\w]*(\w+)", raw)
    head = m.group(1).lower() if m else ""
    if head in {"hold", "holds", "held", "unchanged", "none", "stable", "no"}:
        return "hold", names
    if head in {"break", "breaks", "broken", "rebaseline", "rebaselined"}:
        return "break", names

    low = raw.lower()
    # A declaration naming constants is ACTIONABLE, whatever else it says.
    # "break -- EXPECTED_X moves; all other baselines hold" is the best possible
    # form: specific about what moves and what does not. Flagging it as mixed
    # punishes precision.
    if names:
        return "break", names

    says_hold = any(w in low for w in ("hold", "unchanged", "no change"))
    says_move = any(w in low for w in ("break", "rebaselin", "re-baselin",
                                       "baseline to move", "will move",
                                       "baseline to change"))
    if says_hold and says_move:
        # Both asserted, no constant named. A stop-the-line gate cannot act on
        # this -- it needs one declaration, or named constants, per step.
        return "mixed", names
    if says_move:
        return "break", []
    if says_hold:
        return "hold", []
    return "unknown", []


def manifest_key_map() -> dict[str, str]:
    """Map each manifest HASH constant to its short key, read from the manifest
    source so a step may name either the constant or the key.

    The key<->constant mapping is arbitrary (``level1_sensor_reading`` pins
    ``EXPECTED_LEVEL4_READING_HASH``), so it is read, not derived. COUNT
    constants are deliberately excluded: an event-count move is noteworthy on
    its own and must be declared by name, not covered by naming its key.
    """
    out: dict[str, str] = {}
    if not MANIFEST.exists():
        return out
    text = MANIFEST.read_text(encoding="utf-8", errors="replace")
    for key, body in re.findall(r'"([a-z][a-z0-9_]+)"\s*:\s*\(([^)]*)\)', text):
        for const in re.findall(r"EXPECTED_[A-Z0-9_]+", body):
            if const.endswith("_HASH"):
                out[const] = key
    return out


def cmd_list(args):
    steps = parse_plan()
    order = sorted(steps, key=sort_key)
    print(f"{len(steps)} steps parsed from {PLAN.relative_to(ROOT)}\n")

    defects, warnings = 0, 0
    dist = {"local": 0, "boundary": 0, "platform-wide": 0, "unknown": 0}
    breaks = []

    for sid in order:
        f = steps[sid]
        missing = sorted(KNOWN - set(f) - {"STEP"})
        cls, mixed = blast_class(f.get("BLAST RADIUS", ""))
        mode, names = declared_parity(f.get("PARITY IMPACT", ""))
        files = file_list(f.get("FILES", ""))
        dirs = dir_list(f.get("FILES", ""))
        dist[cls] = dist.get(cls, 0) + 1

        notes = []
        if missing:
            notes.append("MISSING: " + ", ".join(missing))
            defects += 1
        if cls == "unknown":
            notes.append("blast radius unclassifiable")
            defects += 1
        if mixed:
            notes.append(f"multiple classes named, escalated to {cls}")
            warnings += 1
        if mode == "unknown":
            notes.append("PARITY IMPACT unparseable")
            defects += 1
        if mode == "break" and not names:
            notes.append("breaks parity, names no constant")
            breaks.append(sid)
            defects += 1
        elif mode == "break":
            breaks.append(sid)
        elif mode == "hold" and names:
            notes.append(f"declares hold but mentions {len(names)} constant(s) -- check wording")
            warnings += 1
        joined = " ".join(f.get(k, "") for k in
                          ("REFACTOR PATH", "ROLLBACK", "BLAST RADIUS")).lower()
        if any(w in joined for w in ("independent commits", "per §f item", "per section f",
                                     "each commit", "step 1", "step 2", "one per")):
            notes.append("step describes multiple sub-changes -- one gate for N changes; "
                         "consider splitting")
            warnings += 1

        if mode == "mixed":
            notes.append("PARITY IMPACT asserts both hold and movement -- "
                         "split the step or state one impact")
            defects += 1
            breaks.append(sid)
        if dirs:
            surface = permitted_surface(dirs)
            if surface == 0:
                pass  # directory does not exist yet -- the step creates it
            elif surface >= 10 and surface > 5 * max(len(files), 1):
                notes.append(f"scope permits ~{surface} files against {len(files)} named "
                             f"-- enumerate or accept the weaker guard")
                warnings += 1
        if not files and not dirs:
            notes.append("no path-like tokens in FILES")
            defects += 1
        elif len(files) > 25:
            notes.append(f"{len(files)} files -- review independent revertibility")
            warnings += 1

        scope = f"{len(files)}" + (f"+{len(dirs)}d" if dirs else "")
        tag = "  " + " | ".join(notes) if notes else ""
        print(f"  {sid:<7} [{cls:<13}] parity={mode:<7} files={scope:<6}{tag}")

    print(f"\nblast radius: local {dist['local']}, boundary {dist['boundary']}, "
          f"platform-wide {dist['platform-wide']}"
          + (f", unknown {dist['unknown']}" if dist["unknown"] else ""))
    print(f"parity-breaking steps: {len(breaks)}"
          + (f" -- {', '.join(breaks)}" if breaks else ""))
    print(f"\n{len(steps) - defects} of {len(steps)} steps fully specified"
          + (f"  ({warnings} warning(s))" if warnings else ""))

    if defects:
        print("\nA defect means the plan cannot be mechanically verified. Fix the "
              "plan and re-lock; do not work around it in execution.")
    sys.exit(1 if defects else 0)


def cmd_show(args):
    """Dump one step's parsed fields, to check the parser read it correctly."""
    steps = parse_plan()
    sid = args.show.upper()
    if sid not in steps:
        print(f"{sid} not in plan. Known: {', '.join(sorted(steps, key=sort_key))}")
        sys.exit(2)
    f = steps[sid]
    cls, mixed = blast_class(f.get("BLAST RADIUS", ""))
    mode, names = declared_parity(f.get("PARITY IMPACT", ""))
    files = file_list(f.get("FILES", ""))

    print(f"=== {sid} : parsed fields ===\n")
    for k in ("STEP", "CLOSES", "PROBLEM", "WHY THIS OWNER", "REFACTOR PATH",
              "VALIDATED BY", "DELETES", "NET DELTA", "ROLLBACK"):
        v = f.get(k)
        if v is not None:
            print(f"{k}:\n    {v[:400]}{'...' if len(v) > 400 else ''}\n")

    print(f"BLAST RADIUS (raw):\n    {f.get('BLAST RADIUS','(absent)')[:400]}")
    print(f"  -> class: {cls}" + ("  [multiple named, escalated]" if mixed else "") + "\n")

    print(f"PARITY IMPACT (raw):\n    {f.get('PARITY IMPACT','(absent)')[:400]}")
    print(f"  -> mode: {mode}, constants named: {names or '(none)'}\n")

    print(f"FILES ({len(files)} path-like tokens extracted):")
    for x in files:
        print(f"    {x}")
    print(f"\nFILES (raw):\n    {f.get('FILES','(absent)')[:600]}")


def cmd_attach(args):
    """Emit the exact Cursor attach set and GO line for one step."""
    steps = parse_plan()
    sid = args.attach.upper()
    if sid not in steps:
        print(f"{sid} not in plan. Known: {', '.join(sorted(steps, key=sort_key))}")
        sys.exit(2)
    f = steps[sid]

    files = file_list(f.get("FILES", ""))
    dirs = dir_list(f.get("FILES", ""))
    tests = file_list(f.get("VALIDATED BY", ""))
    mode, names = declared_parity(f.get("PARITY IMPACT", ""))
    cls, _ = blast_class(f.get("BLAST RADIUS", ""))

    fixed = [
        "docs/architecture/target/prompts/exec/X0_CORE_EXEC.md",
        "docs/architecture/target/prompts/exec/X2_step.md",
        "docs/architecture/target/out/phase7_migration.md",
        "docs/architecture/target/out/exec/LEDGER.md",
    ]

    existing, new_files = [], []
    for x in files + tests:
        (existing if (ROOT / x).exists() else new_files).append(x)

    # Parent packages: the engine boundary the step works inside. A file cannot
    # be changed correctly without its siblings and its package __init__.
    parents = sorted({str(Path(x).parent).replace("\\", "/")
                      for x in existing
                      if str(Path(x).parent) not in (".", "")})
    # Drop parents already covered by an explicit directory scope.
    parents = [d for d in parents if not any(d.startswith(s.rstrip("/")) for s in dirs)]
    # New files cannot be attached; attach where they will land.
    for x in new_files:
        d = str(Path(x).parent).replace("\\", "/")
        if d and d not in parents and (ROOT / d).exists():
            parents.append(d)
    parents = sorted(set(parents))

    extra, why = [], []
    if mode == "break" or cls == "platform-wide":
        extra.append("tests/determinism")
        why.append("tests/determinism -- parity is declared to move, or the step is "
                   "platform-wide; the replay corpus is the oracle")
    contract_words = ("event", "contract", "envelope", "payload", "field on")
    text = " ".join(f.get(k, "") for k in ("PROBLEM", "REFACTOR PATH")).lower()
    if any(x.startswith(("src/feelies/core", "src/feelies/bus")) for x in files) \
            or any(w in text for w in contract_words):
        for d in ("src/feelies/core", "src/feelies/bus"):
            if (ROOT / d).exists():
                extra.append(d)
        why.append("src/feelies/core + bus -- the step changes a contract or event type")

    attach = fixed + sorted(set(existing)) + parents + [d.rstrip("/") for d in dirs] + extra
    seen, ordered = set(), []
    for a in attach:
        if a not in seen:
            seen.add(a)
            ordered.append(a)

    print(f"=== {sid} attach set ===")
    print(f"blast radius {cls} | parity {mode}"
          + (f" ({', '.join(names)})" if names else "") + "\n")

    print("Paste into Cursor:\n")
    print(" ".join(f"@{a}" for a in ordered))

    print("\nThen the GO line:\n")
    print("This is Windows/PowerShell -- `python` not `python3`, `uv run` unchanged.")
    print(f"Execute step {sid} only, per the attached X0 and X2 files. "
          f"Stop at the hard stop.")

    if new_files:
        print("\nDeclared but not yet on disk (the step creates these):")
        for x in new_files:
            print(f"  {x}")
    if why:
        print("\nWhy the extras:")
        for w in why:
            print(f"  {w}")

    print("\nDeliberately NOT attached:")
    print("  phase0-phase6 outputs -- design rationale; in execution they invite")
    print("    re-litigating decisions the plan already settled")
    print("  @Codebase / semantic search -- returns plausible partial context,")
    print("    which defeats the scope discipline this step depends on")


def cmd_reconcile(_args):
    if not LEDGER.exists():
        print(f"ledger not found: {LEDGER.relative_to(ROOT)}")
        sys.exit(2)
    ledger = LEDGER.read_text(encoding="utf-8", errors="replace")
    entries = {m.group(1) for m in re.finditer(r"^##\s+(S-\d+)", ledger, re.M)}
    # Each entry runs from its header to the next header (or EOF); a step is
    # 'passed' only if its OWN block records that verdict. Without the bound a
    # blocked/reverted entry absorbs a later step's 'passed'.
    passed = {
        m.group(1)
        for m in re.finditer(
            r"^##\s+(S-\d+)((?:(?!^##\s+S-\d+)[\s\S])*)", ledger, re.M)
        if re.search(r"VERDICT:\s*passed", m.group(2))
    }
    _, log = run(["git", "log", "--oneline", "--no-merges"])
    committed = {m.group(1) for m in re.finditer(r"\b(S-\d+):", log)}

    print(f"ledger entries : {len(entries)}")
    print(f"ledger passed  : {len(passed)}")
    print(f"git commits    : {len(committed)}\n")

    orphan_commits = sorted(committed - entries)
    orphan_ledger = sorted(passed - committed)
    for s in orphan_commits:
        print(f"  UNREVIEWED  {s} committed with no ledger entry")
    for s in orphan_ledger:
        print(f"  MISSING     {s} marked passed but no commit found")
    if not orphan_commits and not orphan_ledger:
        print("  clean -- ledger and git agree")
    sys.exit(1 if orphan_commits or orphan_ledger else 0)


def cmd_step(args):
    steps = parse_plan()
    sid = args.step.upper()
    if sid not in steps:
        print(f"{sid} not in plan. Known: {', '.join(sorted(steps))}")
        sys.exit(2)
    f = steps[sid]

    declared_files = file_list(f.get("FILES", ""))
    declared_dirs = dir_list(f.get("FILES", ""))
    mode, declared_hashes = declared_parity(f.get("PARITY IMPACT", ""))
    br, mixed = blast_class(f.get("BLAST RADIUS", ""))

    print(f"=== {sid} ===")
    print(f"blast radius : {br}" + ("  [multiple named, escalated]" if mixed else ""))
    print(f"parity       : declared {mode}"
          + (f" ({', '.join(declared_hashes)})" if declared_hashes else ""))
    print()

    fail = 0

    # --- files -------------------------------------------------------------
    code, out = run(["git", "diff", "--name-only", f"{args.base}..HEAD"])
    all_touched = sorted(x for x in out.splitlines() if x.strip())
    artifacts = [x for x in all_touched if is_artifact(x)]
    touched = [x for x in all_touched if not is_artifact(x)]
    norm = {x.replace("\\", "/") for x in touched}
    decl = {x.replace("\\", "/") for x in declared_files}
    under_dir = {x for x in norm if any(x.startswith(d) for d in declared_dirs)}
    extra = sorted(norm - decl - under_dir)
    unused = sorted(decl - norm)

    print("FILES")
    if declared_dirs:
        print(f"  directory scopes: {', '.join(declared_dirs)} "
              f"(~{permitted_surface(declared_dirs)} files permitted -- weak guard)")
        print(f"  matched under scope: {len(under_dir)}")
    print(f"  declared {len(decl)}, touched {len(norm)}"
          + (f", process artifacts {len(artifacts)} (ignored)" if artifacts else ""))
    for x in extra:
        print(f"    UNDECLARED  {x}")
    for x in unused:
        print(f"    not touched {x}")
    if extra:
        print("  VERDICT: FAIL -- files outside the declared list were modified")
        fail = 1
    else:
        print("  VERDICT: clean")

    # --- parity ------------------------------------------------------------
    pre = EXEC_OUT / f"baseline_pre-{sid}.json"
    post = EXEC_OUT / f"baseline_post-{sid}.json"
    parity_raw = f.get("PARITY IMPACT", "")
    key_map = manifest_key_map()
    print("\nPARITY")
    if pre.exists() and post.exists():
        a = json.loads(pre.read_text(encoding="utf-8")).get("parity", {})
        b = json.loads(post.read_text(encoding="utf-8")).get("parity", {})
        moved = sorted(k for k in set(a) & set(b) if a[k] != b[k])
        added = sorted(set(b) - set(a))
        removed = sorted(set(a) - set(b))
        changed = bool(moved or added or removed)

        # Moves and removals change or drop a pinned stream and must be
        # declared; additions are new coverage -- reported, but not a stop on
        # their own. A constant is declared by its own name, its owning module,
        # or the manifest key it belongs to (named in PARITY IMPACT).
        must = moved + removed
        must_names = sorted({k.split("::")[1] for k in must})
        must_mods = {k.split("::")[0] for k in must}
        mod_declared = any(m in declared_hashes for m in must_mods)

        def _declared(name: str) -> bool:
            if name in declared_hashes or mod_declared:
                return True
            key = key_map.get(name)
            return bool(key) and re.search(
                rf"\b{re.escape(key)}\b", parity_raw) is not None

        undeclared = [n for n in must_names if not _declared(n)]

        moved_names = sorted({k.split("::")[1] for k in moved})
        print(f"  moved {len(moved)}: {', '.join(moved_names) if moved_names else '(none)'}")
        for k in added:
            print(f"    ADDED       {k.split('::')[1]}")
        for k in removed:
            print(f"    REMOVED     {k.split('::')[1]}")
        if mode == "hold" and changed:
            print("  VERDICT: FAIL -- declared hold, but the constant set changed. "
                  "STOP THE LINE.")
            fail = 1
        elif undeclared:
            for n in undeclared:
                print(f"    UNDECLARED  {n}")
            print("  VERDICT: FAIL -- undeclared parity movement. STOP THE LINE.")
            fail = 1
        elif changed:
            print("  VERDICT: declared break, matches. HUMAN RE-BASELINE REQUIRED.")
            print("           Do not run scripts/rebaseline_parity_hashes.py yourself.")
        else:
            print("  VERDICT: parity holds, as declared")
    else:
        print(f"  cannot check -- need {pre.name} and {post.name}")
        print("  run: baseline.py capture --label pre-<step> / post-<step>")
        fail = 1

    # --- net delta ---------------------------------------------------------
    print("\nNET DELTA")
    if pre.exists() and post.exists():
        ea = json.loads(pre.read_text(encoding="utf-8")).get("evidence", {})
        eb = json.loads(post.read_text(encoding="utf-8")).get("evidence", {})
        for grp, keys in (("modules", ("total_files", "public_symbols", "total_sloc")),
                          ("imports", ("n_cycles",)),
                          ("alphaleak", ("n",))):
            for k in keys:
                va, vb = ea.get(grp, {}).get(k), eb.get(grp, {}).get(k)
                if isinstance(va, int) and isinstance(vb, int):
                    print(f"  {grp}.{k:<16} {va} -> {vb} ({vb - va:+d})")
        print(f"  declared: {f.get('NET DELTA', '(not declared)')}")
        print(f"  deletes : {f.get('DELETES', '(not declared)')}")
        print("  VERDICT: compare by eye -- a step claiming deletions with no "
              "negative delta did not do what it said")
    else:
        print("  cannot check -- captures missing")

    print(f"\n=== {sid}: {'FAIL' if fail else 'CLEAN'} ===")
    if br in ("boundary", "platform-wide"):
        print(f"    blast radius '{br}' -- human gate required before commit")
    sys.exit(fail)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", nargs="?", help="step ID, e.g. S-07")
    ap.add_argument("--base", help="SHA before the step")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--reconcile", action="store_true")
    ap.add_argument("--show", metavar="S-nn", help="dump one step's parsed fields")
    ap.add_argument("--attach", metavar="S-nn", help="emit the Cursor attach set and GO line")
    args = ap.parse_args()
    if args.list:
        cmd_list(args)
    elif args.show:
        cmd_show(args)
    elif args.attach:
        cmd_attach(args)
    elif args.reconcile:
        cmd_reconcile(args)
    elif args.step and args.base:
        cmd_step(args)
    else:
        ap.print_help()
        sys.exit(2)


if __name__ == "__main__":
    main()
