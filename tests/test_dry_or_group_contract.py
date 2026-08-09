"""The OR-GROUP wire format and the duplicate decision each have one home.

The bug this guards against already happened once. The same "is this criterion
already represented?" decision was written four times -- in _merge_parsed_items,
_merge_criteria, _supplement_priority_merge and _pick_richer -- each as a
whole-string difflib ratio with its own threshold, and none of them could see a
containment relation. Fixing one left the other three, so the ARISTOTLE cohort
stayed empty through two attempts.

A comment asking the next person not to re-type the literal would not have
stopped it. These tests fail loudly instead.
"""
import ast
import pathlib
import re

import pytest

from src.agents.agent1 import criteria_dedup


SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
OWNER = "criteria_dedup.py"
_DOCSTRING_OWNERS = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


def _sources():
    """Every Python file under src/ except the module that owns the contract."""
    return [p for p in SRC.rglob("*.py") if p.name != OWNER]


# OR_GROUP_SEP is deliberately absent: it is " | ", which appears as a genuine
# separator in 40 unrelated files under src/ (log lines, prompt fields). No
# substring gate can own a string that generic, so the separator is pinned by
# test_the_wire_format_constants_are_what_the_parser_emits instead.
_GATED_MARKERS = ("[OR-GROUP]", " with any of: ")


def _marker_literals(source):
    """Executable string literals containing a gated OR-GROUP marker fragment.

    Comments never reach the AST, and docstrings are excluded explicitly, so
    what survives is a literal the interpreter actually uses -- the only kind
    that can drift out of step with the parser. f-string fragments are caught
    because their constant parts are ordinary Constant nodes.

    :param source: Python source text.
    :returns: the offending literal values.
    """
    tree = ast.parse(source)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, _DOCSTRING_OWNERS) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                    and isinstance(first.value.value, str):
                docstrings.add(id(first.value))
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and any(m in n.value for m in _GATED_MARKERS) and id(n) not in docstrings]


def test_or_group_wire_format_has_one_home():
    """No module may re-type the [OR-GROUP] marker in code.

    _collapse_hierarchical_groups builds the string, _parse_criteria_items
    splits it out and criteria_dedup reads it back. Three literals in three
    files drift apart the moment one of them changes. Prose is exempt --
    forbidding the marker in comments would only make the code harder to read.
    """
    offenders = {p.relative_to(SRC).as_posix(): found
                 for p in _sources() if (found := _marker_literals(p.read_text()))}

    assert not offenders, (
        f"OR-GROUP wire format re-typed in {offenders}; import OR_GROUP_PREFIX / "
        f"OR_GROUP_JOIN from agents.agent1.{OWNER[:-3]} instead"
    )


def test_the_gate_would_catch_a_re_typed_literal():
    """A guard on the guard: prove the detector fires on the shape it forbids."""
    assert _marker_literals('x = "[OR-GROUP] " + h\n') == ["[OR-GROUP] "]
    assert _marker_literals('x = f"[OR-GROUP] {h} with any of: {c}"\n')
    # The join marker on its own, without the prefix, was previously invisible.
    assert _marker_literals('head, _, tail = s.partition(" with any of: ")\n')
    assert _marker_literals('"""Module doc mentioning [OR-GROUP]."""\nx = 1\n') == []
    assert _marker_literals('# a comment about [OR-GROUP]\nx = 1\n') == []


# structural_verdict and prune_superseded are the DROP/KEEP/UNDECIDED form of the
# same decision, and a merge site that routes through them names neither of the
# two older predicates. Adding them keeps this gate meaningful only for as long
# as both genuinely live in criteria_dedup.py -- if a later change inlines either
# into a merge site, the gate goes quiet. That is what
# test_the_shared_names_are_actually_owned_by_the_module below pins.
PREDICATE_NAMES = frozenset({
    "restates_or_group_alternative",
    "is_or_group",
    "or_group_subsumed_by",
    "structural_verdict",
    "prune_superseded",
})


def test_the_shared_names_are_actually_owned_by_the_module():
    """Every name this gate accepts must be defined in criteria_dedup.py.

    The gate asserts a merge site CALLS a shared name. Nothing in that check
    stops someone defining a same-named local helper inside enricher.py and
    satisfying it while re-growing the logic, so ownership is asserted here.
    """
    owner = ast.parse((SRC / "agents/agent1" / OWNER).read_text())
    defined = {node.name for node in owner.body
               if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}

    assert PREDICATE_NAMES <= defined, PREDICATE_NAMES - defined

    for relative in MERGE_SITES:
        module = ast.parse((SRC / relative).read_text())
        local = {node.name for node in ast.walk(module)
                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        assert not (PREDICATE_NAMES & local), f"{relative} re-defines {PREDICATE_NAMES & local}"

MERGE_SITES = {
    "agents/agent1/enricher.py": ["_merge_criteria", "_supplement_priority_merge",
                                  "_pick_richer"],
    "agents/agent1/pubmed_fetcher.py": ["_merge_parsed_items"],
}


def _predicate_calls(source, name):
    """Names of shared-predicate functions actually CALLED inside one function.

    Deliberately AST-based rather than a substring search over the function's
    text. An earlier version of this gate matched raw source, so the comment
    already sitting in _merge_criteria -- which mentions is_or_group in prose --
    was enough to keep it green with both real predicate calls deleted. A gate
    a comment can satisfy is the thing this file exists to argue against.

    :param source: whole module source.
    :param name: top-level function to inspect.
    :returns: the predicate names invoked, or None when the function is absent.
    """
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return {call.func.id for call in ast.walk(node)
                    if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                    and call.func.id in PREDICATE_NAMES}
    return None


def test_the_duplicate_decision_is_not_re_grown_in_the_merge_sites():
    """The four historical copies must route through the shared predicate.

    SequenceMatcher is still legitimately used for the pre-existing similarity
    thresholds, so this asserts the predicate is reached rather than that
    difflib is absent.
    """
    missing = []
    for relative, functions in MERGE_SITES.items():
        source = (SRC / relative).read_text()
        if "from src.agents.agent1.criteria_dedup import" not in source:
            missing.append(f"{relative}: does not import the shared predicate")
        for function in functions:
            called = _predicate_calls(source, function)
            if called is None:
                missing.append(f"{relative}::{function}: function not found")
            elif not called:
                missing.append(f"{relative}::{function}: decides duplication on its own")

    assert not missing, missing


def test_the_merge_site_gate_is_not_satisfied_by_prose():
    """A guard on the guard: a mention in a comment or docstring must not count."""
    prose_only = (
        "def _merge_criteria(a, b):\n"
        '    """Mentions restates_or_group_alternative in the docstring."""\n'
        "    # and is_or_group in a comment\n"
        "    return a + b\n"
    )
    real_call = (
        "def _merge_criteria(a, b):\n"
        "    return [x for x in b if not restates_or_group_alternative(x, a)]\n"
    )

    assert _predicate_calls(prose_only, "_merge_criteria") == set()
    assert _predicate_calls(real_call, "_merge_criteria") == {"restates_or_group_alternative"}
    assert _predicate_calls(real_call, "_absent") is None


@pytest.mark.parametrize("constant, expected", [
    ("OR_GROUP_PREFIX", "[OR-GROUP] "),
    ("OR_GROUP_JOIN", " with any of: "),
    ("OR_GROUP_SEP", " | "),
])
def test_the_wire_format_constants_are_what_the_parser_emits(constant, expected):
    """Pins the format itself, so a change to it is a deliberate act."""
    assert getattr(criteria_dedup, constant) == expected
