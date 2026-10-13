"""The text-rule guard must catch every shape a natural-language rule takes, and only those.

``tests/test_no_text_rules.py`` reads green over any rule its collector cannot see, and a
guard that misses a class of rule is worse than none because it reads green. These tests
hold its detectors to three fixtures, all parsed with ``ast`` and never imported:

- ``fixtures/text_rule_probe_shapes.py`` -- 53 syntactic shapes from the 2026-10-13
  blind-spot audit and 5 added on 2026-10-14 (text as the key of a dict that is not a
  literal). Every shape is a violation (the parameter ``text`` stands for protocol /
  criterion / entity text), so every shape must be flagged.
- ``fixtures/text_rule_real_cases.py`` -- verbatim excerpts of the rules the guard missed in
  ``src/`` at 79b9a3f (and, for r09, at 3c6fd4f), one per detector, so each detector keeps its
  real case after the ``src/`` copy is removed.
- ``fixtures/text_rule_machine_formats.py`` and ``fixtures/text_rule_data/id_keyed.json`` --
  ids, enum values, OMOP field names and structured vocabulary attributes (rule 4). A
  detector that fires on them is making an unobserved defect claim.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests import test_no_text_rules as guard

FIXTURES = guard.ROOT / "tests" / "fixtures"
PROBE = FIXTURES / "text_rule_probe_shapes.py"
REAL_CASES = FIXTURES / "text_rule_real_cases.py"
MACHINE_FORMATS = FIXTURES / "text_rule_machine_formats.py"
DATA = FIXTURES / "text_rule_data"

# Shapes judged not to be a violation, with the reason. Empty: every probe shape tests
# natural-language text for a word, a length, a character class or a similarity.
NOT_VIOLATIONS: dict[str, str] = {}

# Sinks added on 2026-10-13; the machine-format fixture must produce none of them.
NEW_SINKS = frozenset(
    {
        "sql",
        "wordlist",
        "datafile",
        "fuzzy",
        "length",
        "charclass",
        "literal",
        "lookup",
        "textmatch",
    }
)


def _sink(site: guard.Site) -> str:
    return site.fingerprint.split(":", 1)[0]


def _symbol(site: guard.Site) -> str:
    return getattr(site, "symbol", site.scope)


def _shape_spans(path: Path) -> list[tuple[int, int, str]]:
    """``(first, last, shape)`` per probe function; module lines before a function are its own."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    functions = sorted(
        (node.lineno, node.end_lineno or node.lineno, node.name)
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name[:1] == "s"
        and node.name[1:3].isdigit()
    )
    spans, previous_end = [], 0
    for first, last, name in functions:
        spans.append((previous_end + 1, last, name))
        previous_end = last
    return spans


def _shape(name: str) -> str:
    """``s37b_len_helper`` is the helper half of shape ``s37``."""
    return name[:3]


def test_should_flag_every_violation_shape_when_the_probe_is_scanned():
    spans = _shape_spans(PROBE)
    shapes = sorted({_shape(name) for _, _, name in spans})
    assert len(shapes) == 58, shapes
    flagged: dict[str, list[str]] = {}
    for site in guard.collect_sites([PROBE]):
        owner = next((name for first, last, name in spans if first <= site.line <= last), None)
        if owner is not None:
            flagged.setdefault(_shape(owner), []).append(site.fingerprint)
    missed = [shape for shape in shapes if shape not in flagged and shape not in NOT_VIOLATIONS]
    print(f"probe coverage: {len(shapes) - len(missed)}/{len(shapes)} shapes flagged")
    assert not missed, f"{len(missed)}/{len(shapes)} probe shapes read green: {missed}"


@pytest.mark.parametrize(
    ("symbol", "sink"),
    [
        ("r01_sql_exact_concept_name", "sql"),
        ("r02_sql_like_fstring", "sql"),
        ("r03_sql_lower_any", "sql"),
        ("r04_sql_umls_str", "sql"),
        ("_STOPWORDS", "wordlist"),
        ("_NEGATORS", "wordlist"),
        ("r05_fuzzy_sequence_matcher", "fuzzy"),
        ("r06_content_tokens", "length"),
        ("r06_content_tokens", "literal"),
        ("r07_initialism_run", "length"),
        ("r07_initialism_run", "charclass"),
        ("QueryExpander.expand", "length"),
        ("r08_umls_short_query", "length"),
        ("r09_entity_lookup_by_lowered_text", "lookup"),
    ],
)
def test_should_flag_the_real_rule_when_its_src_excerpt_is_scanned(symbol, sink):
    found = {(_symbol(site), _sink(site)) for site in guard.collect_sites([REAL_CASES])}
    assert (symbol, sink) in found, f"no {sink} site in {symbol}; found {sorted(found)}"


def test_should_flag_nothing_new_when_only_machine_formats_are_scanned():
    fired = [
        f"{site.line} {site.fingerprint}"
        for site in guard.collect_sites([MACHINE_FORMATS])
        if _sink(site) in NEW_SINKS
    ]
    assert not fired, "a text-rule detector fired on ids / enums / field names:\n" + "\n".join(
        fired
    )


def test_should_flag_a_word_keyed_data_file_and_not_an_id_keyed_one():
    data_file_sites = getattr(guard, "data_file_sites", None)
    assert data_file_sites is not None, "the guard has no data-file detector"
    flagged = {Path(site.file).name for site in data_file_sites(sorted(DATA.iterdir()))}
    assert flagged == {"word_list.json", "word_array.json"}, flagged


def test_should_scan_every_delivery_path_script():
    scanned = {path.relative_to(guard.ROOT).as_posix() for path in guard.scanned_files()}
    for script in (
        "scripts/export_seeded_cohorts.py",
        "scripts/export_circe_from_store.py",
        "scripts/verify_circe_delivery.py",
        "scripts/reingest_protocol_pdfs.py",
    ):
        assert script in scanned, script
