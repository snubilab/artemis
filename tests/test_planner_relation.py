"""RFC-016 step 2 (RFC-014 §2-1) in the planner: ``relation`` decides the split's group type.

The planner states, definitions only, how the protocol line combines the sub-terms it names
(``relation`` / ``relation_span`` / ``cardinality``). ``decomposer.py`` then derives the
group type from the logic and that relation, and declines a split whose line names two or
more members without a verified relation -- the same outcome ``_torn_range_declined`` gives.
A split whose members the line does not name (an elaboration of an umbrella term) is read
as ``any``. Gate 2 of ``_grounded_span`` (shared naming words, inventory A9) is removed;
gate 1, the substring check, stays.

Every criterion and member here is a real store row (2026-10-12 prompt_f2 candidate,
``tests/fixtures/rfc016_relation_timing_rows.json``); the planner's single LLM call is
mocked with the split those rows record, spans copied from their own lines.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from src.agents.planner.decomposer import CriteriaPlanner, _grounded_span
from src.models.ir import Criteria, TemporalWindow
from src.services.criterion_annotation import PLANNER_RELATION_KEY, stated_relation
from src.services.tte_service import TTEService

FIXTURE = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "rfc016_relation_timing_rows.json").read_text()
)
CAROLINA_HEAD = FIXTURE["carolina_inclusion_1"]
LEADER_CHF = FIXTURE["leader_exclusion_10"]
LEADER_DECOMPENSATION = FIXTURE["leader_exclusion_4"]
CAROLINA_LIVER = FIXTURE["carolina_exclusion_21"]

HEAD_SPAN = "T2DM and concurrently insufficient glycaemic control and a high risk of CV events"
CHF_SPAN = "Chronic heart failure (NYHA class IV)"


def _criterion(label: dict[str, Any]) -> Criteria:
    """The planner's input, rebuilt from the label row the planner's output became."""
    window = label.get("window")
    return Criteria(
        name=label["description"],
        domain=label["domain"],
        entity_text=label["sourceText"],
        source_text=label["protocolLine"],
        logic_type=label["logicType"],
        window=TemporalWindow(**window) if window else None,
    )


def _member(row: dict[str, Any], span: str | None) -> dict[str, Any]:
    return {
        "name": row["description"],
        "entity_text": row["sourceText"],
        "domain": row["domain"],
        "source_span": span,
        "value_constraint_text": None,
    }


def _plan(criterion: Criteria, members: list[dict[str, Any]], **relation: Any) -> Criteria:
    answer = {
        "decompose": True,
        "reasoning": "stub",
        "excepted_entities": [],
        "relation": None,
        "relation_span": None,
        "cardinality": None,
        "sub_criteria": members,
    }
    answer.update(relation)
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(content=json.dumps(answer))
    with patch("src.agents.planner.decomposer.get_llm", return_value=llm):
        planner = CriteriaPlanner()
    return planner._decompose_criterion(criterion)


def _head_members() -> list[dict[str, Any]]:
    t2dm, glycaemic, cv_risk = CAROLINA_HEAD[1:]
    return [
        _member(t2dm, "T2DM"),
        _member(glycaemic, glycaemic["protocolSpan"]),
        _member(cv_risk, cv_risk["protocolSpan"]),
    ]


def _chf_members() -> list[dict[str, Any]]:
    chf, nyha = LEADER_CHF[1:]
    return [_member(chf, chf["protocolSpan"]), _member(nyha, nyha["protocolSpan"])]


class TestTheSplitNeedsAStatedRelation:
    def test_should_decline_the_split_when_the_line_names_its_members_and_states_no_relation(
        self,
    ):
        """CAROLINA's T2DM head rule stays the one criterion "Type 2 Diabetes Mellitus"."""
        result = _plan(_criterion(CAROLINA_HEAD[0]), _head_members())
        assert result.sub_criteria == []
        assert result.entity_text == "Type 2 Diabetes Mellitus"

    def test_should_decline_the_split_when_the_relation_span_is_not_in_the_line(self):
        result = _plan(
            _criterion(CAROLINA_HEAD[0]),
            _head_members(),
            relation="all",
            relation_span="T2DM and insufficient glycaemic control",
        )
        assert result.sub_criteria == []

    def test_should_split_as_all_when_the_line_states_all(self):
        result = _plan(
            _criterion(CAROLINA_HEAD[0]), _head_members(), relation="all", relation_span=HEAD_SPAN
        )
        assert len(result.sub_criteria) == 3
        assert result.group_type == "ALL"
        assert (result.relation, result.relation_span, result.cardinality) == (
            "all",
            HEAD_SPAN,
            None,
        )

    def test_should_split_an_absence_that_states_all_as_any(self):
        """LEADER "Chronic heart failure (NYHA class IV)": exclude only the patient with
        both, so the absence group is ANY (RFC-014 §2-1 table)."""
        result = _plan(
            _criterion(LEADER_CHF[0]), _chf_members(), relation="all", relation_span=CHF_SPAN
        )
        assert len(result.sub_criteria) == 2
        assert result.group_type == "ANY"

    def test_should_read_an_elaboration_as_any(self):
        """LEADER "Acute decompensation of glycemic control": the line names none of the four
        members, so there is no relation to state and the umbrella reading applies."""
        members = [_member(row, None) for row in LEADER_DECOMPENSATION[1:]]
        result = _plan(_criterion(LEADER_DECOMPENSATION[0]), members)
        assert len(result.sub_criteria) == 4
        assert result.group_type == "ALL"
        assert result.relation is None


class TestTheRelationReachesTheStore:
    def test_should_write_the_planner_relation_on_the_group_label_row(self):
        planned = _plan(
            _criterion(CAROLINA_HEAD[0]), _head_members(), relation="all", relation_span=HEAD_SPAN
        )
        rows = TTEService.__new__(TTEService)._criteria_from_ir([planned])
        label = rows[0]
        assert label["isGroupLabel"] is True
        assert label[PLANNER_RELATION_KEY] == {
            "relation": "all",
            "relation_span": HEAD_SPAN,
            "cardinality": None,
        }
        assert all(PLANNER_RELATION_KEY not in row for row in rows[1:])
        stated = stated_relation(label)
        assert (stated.relation, stated.source) == ("all", "planner")


class TestOnlyTheSubstringGateRemains:
    def test_should_keep_a_span_that_is_in_the_line_but_names_the_umbrella(self):
        """A9 gate 2 removed: the substring check is the only test (RFC-016 §5)."""
        line = CAROLINA_LIVER[0]["protocolLine"]
        alt = CAROLINA_LIVER[1]
        sub_term = f"{alt['sourceText']} {alt['description']}"
        assert _grounded_span("impaired hepatic function", line, sub_term) == (
            "impaired hepatic function"
        )

    def test_should_refuse_a_span_that_is_not_in_the_line(self):
        line = CAROLINA_LIVER[0]["protocolLine"]
        assert _grounded_span("ALT > 3x ULN", line, "ALT elevation") is None
