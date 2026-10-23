"""A list header nested over its members is the group, not a condition on records.

Measured on P11 MAIN (sec-nest 3a253a4, ``output/site_gap/2026-10-22_p11_secnest/arm_main``):
format-based nesting (S10) put LEADER's and CARMELINA's list members under their header, the
annotation read the header's own wording as ``conditional`` ("age ≥50 and ≥1 of the following
criteria:", "High risk of CV events (I and/or II):"), and ``conditional_skips`` took every
member with it -- LEADER inclusion 9-22 and CARMELINA inclusion 12-38 left the files, and the
delivery gate passed because the reason is allowlisted.

The structural property that separates them from a real conditional group: the header's span
lies in the header's own line and in none of its members' lines (each member is a line of its
own, listed under it). PLATO's WOCBP label ("Females of child-bearing potential must ...") and
CARMELINA's pre-menopausal exclusion are splits of ONE line: every member carries that line,
so the span is in the members' lines too, and their skip stands.

Every row here is verbatim from the P11 MAIN store and delivered treatment files
(``tests/fixtures/p11_nested_header_rows.json``, with the store's SHA-256).
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from src.services.criterion_annotation import (
    CONDITIONAL_REASON,
    GROUP_RELATION_UNRESOLVED_REASON,
    conditional_skips,
    unresolved_group_relations,
)

_FX = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "p11_nested_header_rows.json").read_text()
)


def _rows(case: str) -> list[dict[str, Any]]:
    return deepcopy(_FX[case]["rows"])


def _index(case: str, role: str) -> dict[tuple[str, str], dict[str, Any]]:
    return {(role, str(r["id"])): r for r in _rows(case)}


class TestTheBuildDoesNotSkipAListHeaderAsConditional:
    def test_should_skip_nothing_when_leader_headers_quote_only_their_own_lines(self):
        """LEADER 9 and 18: each span ("age ≥50 and ≥1 of the following criteria:") is in
        the header's line only; their members are 4.1 ... 5.4, lines of their own."""
        assert conditional_skips(_rows("leader_inclusion_9_22")) == {}

    def test_should_keep_only_a_members_own_conditional_under_carmelinas_nested_header(self):
        """CARMELINA 12 nests five subgroups. Its header span is reverted; member 20 ("in
        patients not revascularized", on its own line) keeps its own decision."""
        skips = conditional_skips(_rows("carmelina_inclusion_12_38"))
        assert set(skips) == {"20"}
        assert skips["20"].decided_by == "20"

    @pytest.mark.parametrize(
        "case", ["plato_inclusion_7_10", "plato_inclusion_49_54", "carmelina_exclusion_30_36"]
    )
    def test_should_keep_every_skip_when_the_members_share_the_headers_line(self, case):
        """WOCBP / pre-menopausal: one line split into a label and requirements on the
        patients the span names. Unchanged: every row of the group is skipped."""
        rows = _rows(case)
        assert set(conditional_skips(rows)) == {str(r["id"]) for r in rows}


class TestTheGateFailsAHeaderSkippedWithAllItsMembers:
    """Check (i) gains a line: a group header whose span lies in no member's line, skipped
    as conditional together with every member, is a list lost under a permit."""

    @pytest.fixture()
    def violations(self):
        from scripts.verify_circe_delivery import conditional_header_violations

        return conditional_header_violations

    @pytest.mark.parametrize(
        "case, headers",
        [("leader_inclusion_9_22", {"9", "18"}), ("carmelina_inclusion_12_38", {"12"})],
    )
    def test_should_fail_on_p11_mains_delivered_skip_records(self, violations, case, headers):
        out = violations(_FX[case]["skipped"], _index(case, "inclusion"))
        assert len(out) == len(headers), out
        for header in headers:
            assert any(f"#{header} " in line for line in out), out

    @pytest.mark.parametrize(
        "case, role",
        [
            ("plato_inclusion_7_10", "inclusion"),
            ("plato_inclusion_49_54", "inclusion"),
            ("carmelina_exclusion_30_36", "exclusion"),
        ],
    )
    def test_should_pass_a_real_conditional_group(self, violations, case, role):
        assert violations(_FX[case]["skipped"], _index(case, role)) == []

    def test_should_pass_when_a_member_was_built(self, violations):
        """One member emitted: the header did not take the whole list with it."""
        skipped = [r for r in _FX["leader_inclusion_9_22"]["skipped"] if r["criterionId"] != "10"]
        out = violations(skipped, _index("leader_inclusion_9_22", "inclusion"))
        assert all("#9 " not in line for line in out), out


class TestAGroupWithNoRelationIsUnresolved:
    """The IR declares no group_type for LEADER's and CARMELINA's nested groups. When neither
    the planner nor the annotation states a verified relation there is nothing to build the
    group from, and ALL is not a reading -- the rows are recorded unresolved."""

    @staticmethod
    def _undeclared(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for row in rows:
            row["groupType"] = None
        return rows

    def test_should_resolve_from_the_annotations_verified_relation(self):
        """LEADER 9 states at_least 1 on "≥1 of the following criteria:", in its line."""
        assert unresolved_group_relations(self._undeclared(_rows("leader_inclusion_9_22"))) == {}

    def test_should_mark_the_whole_group_when_no_relation_verifies(self):
        rows = self._undeclared(_rows("leader_inclusion_9_22"))
        for row in rows:
            if row["id"] in (9, 18):
                row["annotation"]["relation"] = None
        unresolved = unresolved_group_relations(rows)
        assert set(unresolved) == {str(r["id"]) for r in rows}
        assert unresolved["10"] == rows[0]["groupId"]

    def test_should_leave_a_declared_group_type_alone(self):
        """A store written before the IR's group_type was kept carries ALL/ANY: declared."""
        rows = _rows("leader_inclusion_9_22")
        for row in rows:
            if row["id"] in (9, 18):
                row["annotation"]["relation"] = None
        assert unresolved_group_relations(rows) == {}

    def test_should_not_be_an_allowed_skip_reason(self):
        from scripts.verify_circe_delivery import ALLOWED_SKIP_REASONS

        assert GROUP_RELATION_UNRESOLVED_REASON not in ALLOWED_SKIP_REASONS
        assert CONDITIONAL_REASON in ALLOWED_SKIP_REASONS


class TestTheIrGroupTypeIsKeptWhenAbsent:
    def test_should_keep_none_when_the_model_declared_no_group_type(self):
        from src.agents.agent1.parser import LogicDecomposer

        parser = LogicDecomposer.__new__(LogicDecomposer)
        rule = parser._build_criteria(
            {
                "name": "Prior cardiovascular disease cohort criteria",
                "domain": "Condition",
                "source_text": "4. Prior cardiovascular disease cohort: age ≥50 and ≥1 of the "
                "following criteria",
                "group_type": None,
                "sub_criteria": [
                    {"name": "Prior MI", "domain": "Condition", "source_text": "4.1 Prior MI"},
                    {"name": "Prior stroke or TIA", "domain": "Condition",
                     "source_text": "4.2 Prior stroke or TIA"},
                ],
            }
        )
        assert rule.group_type is None
        assert rule.sub_criteria[0].group_type == "ALL"

    def test_should_keep_a_declared_group_type(self):
        from src.agents.agent1.parser import LogicDecomposer

        parser = LogicDecomposer.__new__(LogicDecomposer)
        rule = parser._build_criteria(
            {"name": "x", "domain": "Condition", "group_type": "any",
             "sub_criteria": [{"name": "a", "domain": "Condition"},
                              {"name": "b", "domain": "Condition"}]}
        )
        assert rule.group_type == "ANY"

    def test_should_write_none_to_the_store_row(self):
        from src.models.ir import Criteria
        from src.services.tte_service import TTEService

        group = Criteria(
            name="Prior cardiovascular disease cohort criteria", domain="Condition",
            source_text="4. Prior cardiovascular disease cohort: age ≥50 and ≥1 of the following",
            sub_criteria=[
                Criteria(name="Prior MI", domain="Condition", source_text="4.1 Prior MI")
            ],
            group_type=None,
        )
        rows = TTEService.__new__(TTEService)._criteria_from_ir([group])
        assert [r["groupType"] for r in rows] == [None, None]
