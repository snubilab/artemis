"""The numbers in a criterion are parsed, not inferred, before the LLM sees it.

Agent 1 was asked to do two jobs at once: classify a criterion (domain, logic,
window) and extract its numeric constraint. It is good at the first and unreliable
at the second, and the failure is silent -- the rule keeps its label and loses its
value.

Measured 2026-07-31 on ARISTOTLE. The protocol's exclusion 20) reached the LLM
intact and came back as::

    {"description": "Liver Enzyme Elevation", "valueConstraint": null}

while the same run extracted LVEF <= 40, Hb < 9, platelets <= 100000 and
creatinine > 2.5 correctly. What separated the failure from the successes was not
difficulty but shape: three analytes and two thresholds in one sentence.

`parse_value_constraints` -- deterministic, no model -- reads that same sentence as
two constraints, 2.0 gt uln and 1.5 gte uln, which is exactly what the gold Circe
carries. So the parser is authoritative for numbers and the annotation is what
carries its answer into the prompt.
"""
from __future__ import annotations

import json

import pytest

from src.services.value_constraint import annotate_value_constraints

ARISTOTLE = (
    "ALT or AST > 2X ULN or a Total Bilirubin ≥ 1.5X ULN "
    "(unless an alternative causative factor [e.g., Gilbert’s syndrome] is identified)"
)
PLATO = "Troponin I or T or CK-MB greater than the upper limit of normal"


def _constraints(annotation: str) -> list[dict]:
    return [
        json.loads(line.split("[value_constraint]", 1)[1].strip())
        for line in annotation.splitlines()
        if "[value_constraint]" in line
    ]


def test_compound_sentence_yields_both_thresholds() -> None:
    """The exact sentence Agent 1 dropped."""
    parsed = _constraints(annotate_value_constraints(ARISTOTLE))

    assert parsed == [
        {"op": "gt", "value": 2.0, "referenceBound": "uln"},
        {"op": "gte", "value": 1.5, "referenceBound": "uln"},
    ]


def test_spelled_out_bound_is_recognised() -> None:
    """PLATO writes it out instead of abbreviating; both must reach "uln"."""
    parsed = _constraints(annotate_value_constraints(PLATO))

    assert parsed == [{"op": "gt", "value": 1.0, "referenceBound": "uln"}]


def test_absolute_constraints_keep_their_unit() -> None:
    """Not everything is a ratio -- the unit has to survive for ValueAsNumber."""
    parsed = _constraints(annotate_value_constraints("Serum creatinine > 2.5 mg/dL"))

    assert parsed[0]["op"] == "gt"
    assert parsed[0]["value"] == 2.5
    assert parsed[0]["referenceBound"] == "absolute"
    assert parsed[0]["unitText"] == "mg/dL"


@pytest.mark.parametrize(
    "text",
    [
        "History of atrial fibrillation",
        "Unable to provide informed consent",
        "",
    ],
)
def test_criteria_without_numbers_annotate_to_nothing(text: str) -> None:
    """An annotation on every line would train the model to invent one."""
    assert annotate_value_constraints(text) == ""


def test_prompt_templates_still_format() -> None:
    """A stray unescaped brace in a prompt breaks every parse, not one criterion.

    Documenting the annotation with a literal ``{value_constraint}`` example made
    ``str.format`` read it as a replacement field: `IndexError: Replacement index 0
    out of range`, raised on the first line of every LogicDecomposer.parse call.
    Nine tests went red at once and none of them named the prompt.

    Scoped to the two templates parser.py actually formats. The system prompts go to
    SystemMessage verbatim and are deliberately excluded -- NCT_SYSTEM_PROMPT carries
    an unescaped ``{start: -90, end: 0}`` that is harmless only because nothing
    formats it, and asserting on it here would fail for a defect that does not exist.
    """
    import string

    from src.agents.agent1.prompts import DECOMPOSITION_PROMPT, NCT_DECOMPOSITION_PROMPT

    for template in (DECOMPOSITION_PROMPT, NCT_DECOMPOSITION_PROMPT):
        fields = {name for _, name, _, _ in string.Formatter().parse(template) if name}
        template.format(**{name: "x" for name in fields})


def test_statistical_language_is_not_a_reference_bound() -> None:
    """"upper boundary of the two-sided 95% CI" is one word from "upper limit of normal"."""
    text = "the upper boundary of the two-sided 95% confidence interval was less than 1.3"

    assert "uln" not in annotate_value_constraints(text)
