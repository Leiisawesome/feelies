"""Closes G-D — §20.12.2 #3 G16 rule completeness.

§20.12.2 #3 of ``design_docs/three_layer_architecture.md`` requires
that "G16 unit tests cover all 9 binding rules with pass + fail
cases".  The unit tests themselves live in
``tests/alpha/test_gate_g16.py`` and are organised as one
``TestRuleN…`` class per binding rule (Rule 1 through Rule 9).

This acceptance test introspects that module and asserts that every
rule class has at least one test method whose name signals a *pass*
case (``…accepted``, ``…passes``, ``…unaffected``, ``…abstains``,
``…skipped``, ``…can_be_constructed``) and at least one method
whose name signals a *fail* case (``…rejected``, ``…refused``).

Why introspection rather than a static checklist?

* The G16 test suite is the canonical artefact, not this file.  As
  rule-N tests evolve (more parametrizations, additional edge
  cases) the introspection automatically tracks the truth.
* A static list would silently rot if a rule's test class were
  deleted or renamed without anyone updating the matrix.
  Introspection promotes that drift to a loud failure.
* Adding a 10th binding rule is a design-doc change that should
  *also* require updating this test (extending ``_EXPECTED_RULES``)
  — the failure mode at that point is "you added rule 10 but
  haven't told the matrix yet", which is exactly the discipline the
  Acceptance Sweep is meant to enforce.
"""

from __future__ import annotations

import inspect
import re

import tests.alpha.test_gate_g16 as g16_tests


# Binding rules enumerated in §20.6.1.  Each entry is the rule class
# name in tests/alpha/test_gate_g16.py.  Adding a 10th rule?  Update
# this tuple AND docs/acceptance/v02_v03_matrix.md row §20.12.2 #3 in
# the same PR.
_EXPECTED_RULES: tuple[str, ...] = (
    "TestRule1Family",
    "TestRule2HalfLifeRange",
    "TestRule3HorizonRatio",
    "TestRule4SensorRegistration",
    "TestRule5FingerprintSensor",
    "TestRule6FailureSignature",
    "TestRule7StressEntryProhibited",
    "TestRule8ShareReachable",
    "TestRule9DependencyAuthorised",
)


# Substrings (case-insensitive) that mark a method as an
# acceptance/pass-case test.  ``can_be_constructed`` is included
# because Rule 1's parametrized "each family can be constructed"
# tests are the canonical positive cases for that rule.
_PASS_TOKENS: tuple[str, ...] = (
    "accepted",
    "passes",
    "unaffected",
    "abstains",
    "skipped",
    "can_be_constructed",
)


# Substrings (case-insensitive) that mark a method as a rejection /
# fail-case test.
_FAIL_TOKENS: tuple[str, ...] = (
    "rejected",
    "refused",
)


_TEST_METHOD_RE = re.compile(r"^test_")


def _classify(method_name: str) -> str:
    """Return ``'pass'`` / ``'fail'`` / ``'unknown'`` for a test method."""
    name_lower = method_name.lower()
    is_pass = any(token in name_lower for token in _PASS_TOKENS)
    is_fail = any(token in name_lower for token in _FAIL_TOKENS)
    if is_pass and is_fail:
        # Conservatively treat ambiguous names as 'unknown' so they
        # are reported by the unknown-name check below; ambiguity
        # silently double-counting would mask real coverage gaps.
        return "unknown"
    if is_pass:
        return "pass"
    if is_fail:
        return "fail"
    return "unknown"


def _rule_classes() -> dict[str, type]:
    found: dict[str, type] = {}
    for name, obj in inspect.getmembers(g16_tests, inspect.isclass):
        if name.startswith("TestRule"):
            found[name] = obj
    return found


def test_all_nine_g16_rules_have_test_classes() -> None:
    classes = _rule_classes()
    missing = [name for name in _EXPECTED_RULES if name not in classes]
    extra = [
        name for name in classes
        if name not in _EXPECTED_RULES
    ]
    assert not missing, (
        f"§20.12.2 #3: G16 rule test classes missing: {missing}.  "
        "Either restore the class in tests/alpha/test_gate_g16.py "
        "or, if the rule was retired by a design-doc change, also "
        "remove it from _EXPECTED_RULES and update "
        "docs/acceptance/v02_v03_matrix.md row §20.12.2 #3."
    )
    assert not extra, (
        f"§20.12.2 #3: unexpected G16 rule test classes found: "
        f"{extra}.  Add them to _EXPECTED_RULES (and the matrix) or "
        "rename them so they no longer match the TestRule* prefix."
    )


def test_every_g16_rule_has_pass_and_fail_cases() -> None:
    classes = _rule_classes()
    failures: list[str] = []

    for rule_name in _EXPECTED_RULES:
        cls = classes.get(rule_name)
        if cls is None:
            # Already reported by the previous test; skip here so we
            # do not double-fail on the same defect.
            continue

        method_names = [
            name for name, _ in inspect.getmembers(
                cls, predicate=inspect.isfunction,
            )
            if _TEST_METHOD_RE.match(name)
        ]

        pass_methods = [
            n for n in method_names if _classify(n) == "pass"
        ]
        fail_methods = [
            n for n in method_names if _classify(n) == "fail"
        ]
        unknown_methods = [
            n for n in method_names if _classify(n) == "unknown"
        ]

        if not pass_methods:
            failures.append(
                f"{rule_name}: no pass-case test method "
                f"(expected one of *_accepted / *_passes / *_abstains "
                f"/ *_unaffected / *_skipped / *_can_be_constructed). "
                f"Method names found: {method_names}"
            )
        if not fail_methods:
            failures.append(
                f"{rule_name}: no fail-case test method "
                f"(expected one of *_rejected / *_refused). "
                f"Method names found: {method_names}"
            )
        if unknown_methods:
            failures.append(
                f"{rule_name}: methods with ambiguous pass/fail "
                f"naming -- rename or extend _PASS_TOKENS / "
                f"_FAIL_TOKENS so the matrix can audit the case "
                f"split.  Offenders: {unknown_methods}"
            )

    assert not failures, (
        "§20.12.2 #3 G16 rule completeness gaps:\n  - "
        + "\n  - ".join(failures)
    )


def test_g16_property_test_module_exists() -> None:
    """§20.12.2 #3 also requires "property-based tests for random
    valid/invalid combinations".  Verify the property-test module is
    present (its content is exercised by the regular pytest run).
    """
    import importlib

    try:
        module = importlib.import_module("tests.alpha.test_gate_g16_props")
    except ModuleNotFoundError as exc:
        raise AssertionError(
            "§20.12.2 #3 requires property-based G16 tests at "
            "tests/alpha/test_gate_g16_props.py — the file is missing. "
            "Restore it or update the matrix to reflect the change."
        ) from exc

    has_test = any(
        name.startswith("test_")
        for name in dir(module)
    )
    assert has_test, (
        "tests/alpha/test_gate_g16_props.py contains no `test_*` "
        "callables — §20.12.2 #3 expects at least one property-based "
        "G16 test."
    )
