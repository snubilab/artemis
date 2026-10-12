"""Gate check (z): an absence that forbids the values its sibling presence requires.

CARMELINA states one line, "HbA1c of ≥ 6.5% and ≤ 10.0% at Visit 1 (screening)". Agent 1
wrote it (shared IR cache, ``target/inclusion_rules[4:6]``, SHA-256 in the fixture) as
``PRESENCE gte 6.5`` + ``ABSENCE lte 10.0`` -- "no HbA1c <= 10", the inverse of the upper
half. The repair that read ``≤`` out of the line (A1) is deleted, so the pair now reaches
the delivery as two rules, and the cohort keeps only patients whose HbA1c is ABOVE 10.

No existing check sees it. (n) skips a bounded absence; the containment check (the absence
forbidding EVERY value the presence admits) is silent because ``lte 10`` does not cover
``gte 6.5``; and the literal overlap reading -- "the required set intersects the forbidden
set" -- also fires on the correct split ``gte 6.5`` + ``ABSENCE gt 10``, whose sets
intersect on ``(10, inf)``. So the check reads the presence's own BOUND: it fails when, after
the absence's forbidden values are removed, the presence no longer reaches the bound its
protocol line states. Numbers and operators only, for criteria from one ``protocolLine`` over
the same (or a member-identical) concept set in overlapping windows.

Producer to gate: the IR rows go through ``_criteria_from_ir`` and ``_build_seeded_target_circe``
with the mapper stubbed (both halves map to the same concepts, as they do live).
"""

from __future__ import annotations

import json
import zlib
from copy import deepcopy
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from scripts.verify_circe_delivery import absence_forbids_required_values_findings
from src.services.tte_service import TTEService
from src.utils.circe_lint import CRITERION_CONCEPT_SET_REFS_KEY

FIXTURE = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "rfc016_quantity_rows.json").read_text()
)
BAND = FIXTURE["carmelina_ir_hba1c_band"]["inclusion_rules_4_5"]


class _Agent2IsStubbed:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise RuntimeError("Agent 2 is stubbed out in this test")


@pytest.fixture
def service(monkeypatch) -> TTEService:
    monkeypatch.setattr("src.agents.agent2.workflow.Agent2Workflow", _Agent2IsStubbed)
    monkeypatch.setattr("src.agents.agent2.query_expander.QueryExpander", _Agent2IsStubbed)
    monkeypatch.setattr("src.agents.agent2.retriever.ConceptRetriever", _Agent2IsStubbed)
    svc = TTEService.__new__(TTEService)

    def fake_recommend(seed_text: str, **kwargs: Any) -> dict[str, Any]:
        seed = seed_text.strip()
        concept_id = zlib.crc32(seed.encode()) % 10**8
        domain = kwargs.get("expected_domain") or "Measurement"
        return {
            "name": seed,
            "domain": domain,
            "expression": {"items": [{
                "concept": {"CONCEPT_ID": concept_id, "CONCEPT_NAME": seed,
                            "CONCEPT_CODE": str(concept_id), "DOMAIN_ID": domain,
                            "VOCABULARY_ID": "SNOMED", "CONCEPT_CLASS_ID": "Clinical Finding"},
                "includeDescendants": True, "isExcluded": False,
            }]},
            "mapping_metadata": None,
        }

    monkeypatch.setattr(svc, "_recommend_seeded_concept_set", fake_recommend)
    monkeypatch.setattr(svc, "_concept_set_lab_properties", lambda expression: {})
    return svc


def _delivered(service: TTEService, upper_op: str) -> tuple[dict, dict]:
    from src.agents.agent1.parser import LogicDecomposer

    raw = deepcopy(BAND)
    raw[1]["value_constraint"]["op"] = upper_op
    with patch("src.agents.agent1.parser.get_llm", return_value=MagicMock()):
        agent1 = LogicDecomposer(model_name="vllm/google/gemma-4-E4B-it")
    rows = service._criteria_from_ir([agent1._build_criteria(item) for item in raw])
    eligibility = {"targetCohortName": "linagliptin", "inclusionCriteria": rows,
                   "exclusionCriteria": []}
    expression = service._build_seeded_target_circe(deepcopy(eligibility))
    return expression, {"id": 9, "eligibility": eligibility}


def test_should_have_the_reversed_upper_half_in_the_ir_row():
    assert [(r["logic_type"], r["value_constraint"]["op"]) for r in BAND] == [
        ("PRESENCE", "gte"), ("ABSENCE", "lte"),
    ]
    assert BAND[0]["source_text"] == BAND[1]["source_text"]


def test_should_fail_the_reversed_range_from_the_real_ir_row(service):
    expression, study = _delivered(service, "lte")
    assert len(expression["InclusionRules"]) == 2
    [finding] = absence_forbids_required_values_findings(expression, study)
    assert "absence forbids the values the presence requires" in finding
    assert "gte 6.5" in finding and "lte 10.0" in finding


def test_should_pass_a_correct_split(service):
    """PRESENCE gte 6.5 + ABSENCE gt 10.0 is "6.5 <= HbA1c <= 10" written as two rules."""
    expression, study = _delivered(service, "gt")
    assert len(expression["InclusionRules"]) == 2
    assert absence_forbids_required_values_findings(expression, study) == []


def test_should_not_judge_halves_from_different_protocol_lines(service):
    expression, study = _delivered(service, "lte")
    study["eligibility"]["inclusionCriteria"][1]["protocolLine"] = "another line"
    assert absence_forbids_required_values_findings(expression, study) == []


def test_should_fail_closed_when_the_file_cannot_say_which_line_a_rule_came_from(service):
    expression, study = _delivered(service, "lte")
    expression.pop(CRITERION_CONCEPT_SET_REFS_KEY)
    [finding] = absence_forbids_required_values_findings(expression, study)
    assert CRITERION_CONCEPT_SET_REFS_KEY in finding


def test_should_be_a_shape_no_other_structural_check_reports(service):
    from src.utils.circe_lint import (
        bound_contradicted_presence_criteria,
        contradictory_presence_absence_criteria,
        unsatisfiable_presence_rules,
    )

    expression, _study = _delivered(service, "lte")
    assert contradictory_presence_absence_criteria(expression) == []
    assert bound_contradicted_presence_criteria(expression) == []
    assert unsatisfiable_presence_rules(expression) == []
