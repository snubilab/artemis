"""A group nested inside a group reaches CIRCE, and a stated cardinality with it.

Two halves of one defect, both measured on the cached IR before anything was changed.

**The grandchild is dropped.** ``TTEService._criteria_from_ir`` flattened the IR one
level deep: a criterion with ``sub_criteria`` became a group-label row plus flat member
rows, and the member loop never looked at ``sub.sub_criteria``. Across the six evaluated
trials' 79 cached IR files, 25 nodes at depth >= 2 carry children and **58 nodes below
them were never visited** -- 54 at depth 3 and 4 at depth 4. PLATO's
``One of the following ACS/CAD features`` (ANY, 9 members) holds
``TIA, carotid stenosis (>=50%), or cerebral revascularization`` (ANY, 3 members) as its
ninth member, and those three reached no store row, no concept set and no CIRCE rule.

**The cardinality has nowhere to live.** ``AT_LEAST`` was emitted zero times by anything
under ``src/`` (``rg -c AT_LEAST src/`` exits 1). CIRCE's group expression carries
``Type: "AT_LEAST"`` with a ``Count``, and Atlas's own ``CriteriaGroup`` reads both, so
the target shape was always available; nothing built it.

The count comes from the relation the group's label states (RFC-016 step 2): the
annotation's ``relation: at_least`` with its ``cardinality``, kept only when its
``relation_span`` is a substring of the label's line. It is never defaulted and never read
off the line's words any more (the former ``circe_lint.list_cardinality``, inventory A18,
is removed). A label that states no relation leaves the group exactly as it was, which is
what ``TestCardinalityComesFromTheStatedRelation`` asserts in both directions.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# IR-side fixtures (builder A: `_criteria_from_ir`)
# ---------------------------------------------------------------------------

def _ir(name: str, **kw: Any) -> SimpleNamespace:
    """One IR criterion node, with every attribute `_criteria_from_ir` reads."""
    node = {
        "name": name,
        "domain": "Condition",
        "entity_text": name,
        "source_text": "",
        "source_span": "",
        "value_constraint": None,
        "window": None,
        "logic_type": "PRESENCE",
        "sub_criteria": [],
        "group_type": "ALL",
        "conditional": False,
    }
    node.update(kw)
    return SimpleNamespace(**node)


def _plato_acs_group() -> SimpleNamespace:
    """PLATO/NCT00391872's real shape, from
    ``data/cache/agent1_ir/NCT00391872_vllm_google_gemma-4-E4B-it_0947526e2840809c.json``
    -- trimmed to three flat members plus the nested one, which is the part that moved.
    """
    return _ir(
        "One of the following ACS/CAD features",
        source_text="One of the following:",
        group_type="ANY",
        sub_criteria=[
            _ir("Persistent ST-segment"),
            _ir("PCI planned"),
            _ir("Previous MI or CABG"),
            _ir(
                "TIA, carotid stenosis (>=50%), or cerebral revascularization",
                group_type="ANY",
                sub_criteria=[
                    _ir("TIA"),
                    _ir("Carotid stenosis (>=50%)"),
                    _ir("Cerebral revascularization"),
                ],
            ),
        ],
    )


@pytest.fixture
def service():
    """A bare TTEService; `_criteria_from_ir` touches no I/O and no agent."""
    from src.services.tte_service import TTEService

    return TTEService.__new__(TTEService)


def _by_description(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {row["description"]: row for row in rows}


# ---------------------------------------------------------------------------
# Emitter-side fixtures (builder B: `_build_seeded_target_circe`)
#
# Same stub shape as tests/test_infra_003_absence_group_semantics.py -- the mapper and
# the vector search are the only expensive parts and neither decides group geometry.
# ---------------------------------------------------------------------------

def _stub_recommend(name: str, expected_domain: str | None = None, workflow=None, **kwargs):
    return {
        "name": name,
        "domain": "Condition",
        "expression": {"items": [{"concept": {"CONCEPT_ID": 99999}}]},
    }


def _stub_eligibility_rule(criterion, *, codeset_id, exclusion):
    label = criterion.get("description", "rule")
    absent = exclusion or criterion.get("logicType") == "ABSENCE"
    return {
        "conceptSet": {"id": codeset_id, "name": label, "expression": {"items": []}},
        "rule": {
            "name": label,
            "expression": {
                "Type": "ALL",
                "CriteriaList": [{
                    "Criteria": {"ConditionOccurrence": {"CodesetId": codeset_id}},
                    "Occurrence": {"Type": 0, "Count": 0} if absent else {"Type": 2, "Count": 1},
                }],
                "DemographicCriteriaList": [],
                "Groups": [],
            },
        },
    }


@pytest.fixture
def emitter():
    """A TTEService with only the mapping calls stubbed; group geometry is real."""
    from src.services.tte_service import TTEService

    svc = TTEService.__new__(TTEService)
    svc._recommend_seeded_concept_set = MagicMock(side_effect=_stub_recommend)
    svc._build_seeded_eligibility_rule = MagicMock(side_effect=lambda **kw: _stub_eligibility_rule(
        kw["criterion"], codeset_id=kw["codeset_id"], exclusion=kw["exclusion"],
    ))
    svc._seeded_primary_criteria_key = MagicMock(return_value="ConditionOccurrence")
    svc._patch_codeset_id_in_rule = MagicMock()
    return svc


def _shell(inclusion: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "targetCohortName": "ACS cohort",
        "inclusionCriteria": inclusion,
        "exclusionCriteria": [],
    }


def _codeset_names(expression: dict[str, Any]) -> dict[int, str]:
    return {cs["id"]: cs["name"] for cs in expression["ConceptSets"]}


def _leaf_entry_count(group: dict[str, Any]) -> int:
    """How many criteria entries a group holds, at any depth beneath it.

    `_build_grouped_inclusion_rule` wraps each member in a one-entry `Groups[]` child,
    so a group's own `CriteriaList` is empty and the members live one level down.
    """
    total = len(group.get("CriteriaList") or [])
    for child in group.get("Groups") or []:
        total += _leaf_entry_count(child)
    return total


# ---------------------------------------------------------------------------
# Half 1 -- the grandchild
# ---------------------------------------------------------------------------

class TestGrandchildrenBecomeRows:
    def test_should_emit_the_grandchildren_when_a_group_member_carries_sub_criteria(
        self, service
    ):
        rows = service._criteria_from_ir([_plato_acs_group()])

        assert "TIA" in _by_description(rows)
        assert "Carotid stenosis (>=50%)" in _by_description(rows)
        assert "Cerebral revascularization" in _by_description(rows)

    def test_should_make_the_nested_member_a_group_label_rather_than_a_leaf(self, service):
        rows = _by_description(service._criteria_from_ir([_plato_acs_group()]))
        nested = rows["TIA, carotid stenosis (>=50%), or cerebral revascularization"]

        # It names three conditions, not one queryable entity: mapping it as a leaf
        # sends that whole string to the concept mapper.
        assert nested["isGroupLabel"] is True

    def test_should_put_the_grandchildren_in_their_own_group_under_the_outer_one(
        self, service
    ):
        rows = _by_description(service._criteria_from_ir([_plato_acs_group()]))
        outer = rows["One of the following ACS/CAD features"]
        nested = rows["TIA, carotid stenosis (>=50%), or cerebral revascularization"]

        assert nested["groupId"] != outer["groupId"]
        assert nested["parentGroupId"] == outer["groupId"]
        for child in ("TIA", "Carotid stenosis (>=50%)", "Cerebral revascularization"):
            assert rows[child]["groupId"] == nested["groupId"]
            assert rows[child]["parentGroupId"] == outer["groupId"]

    def test_should_carry_the_nested_groups_own_type_to_its_members(self, service):
        rows = _by_description(service._criteria_from_ir([_plato_acs_group()]))

        assert rows["TIA"]["groupType"] == "ANY"

    def test_should_leave_a_flat_group_untouched(self, service):
        """A one-level group is the overwhelming majority of the corpus and must not
        gain a field value, an id, or a row."""
        flat = _ir(
            "CV history",
            group_type="ANY",
            sub_criteria=[_ir("MI"), _ir("Stroke")],
        )

        rows = service._criteria_from_ir([flat])

        assert [r["description"] for r in rows] == ["CV history", "MI", "Stroke"]
        assert {r["parentGroupId"] for r in rows} == {None}
        assert len({r["groupId"] for r in rows}) == 1


class TestGrandchildrenReachTheCirce:
    def test_should_give_each_grandchild_its_own_concept_set(self, service, emitter):
        rows = service._criteria_from_ir([_plato_acs_group()])

        names = set(_codeset_names(emitter._build_seeded_target_circe(_shell(rows))).values())

        assert {"TIA", "Carotid stenosis (>=50%)", "Cerebral revascularization"} <= names

    def test_should_not_map_the_nested_group_label_as_a_concept(self, service, emitter):
        """"TIA, carotid stenosis (>=50%), or cerebral revascularization" names three
        conditions; handing that string to the mapper as one entity is how a group
        became a single wrong concept set."""
        rows = service._criteria_from_ir([_plato_acs_group()])

        names = set(_codeset_names(emitter._build_seeded_target_circe(_shell(rows))).values())

        assert "TIA, carotid stenosis (>=50%), or cerebral revascularization" not in names

    def test_should_nest_the_child_group_inside_its_parents_rule(self, service, emitter):
        rows = service._criteria_from_ir([_plato_acs_group()])

        expression = emitter._build_seeded_target_circe(_shell(rows))

        assert len(expression["InclusionRules"]) == 1, (
            "the nested group must ride inside its parent, not alongside it -- CIRCE "
            "AND-combines top-level InclusionRules"
        )
        outer = expression["InclusionRules"][0]["expression"]
        nested = [g for g in outer["Groups"] if g.get("Groups")]
        assert len(nested) == 1, f"expected one nested group among {outer['Groups']}"
        assert nested[0]["Type"] == "ANY"
        assert _leaf_entry_count(nested[0]) == 3
        # Three flat members, each in its own one-entry child, plus the nested group.
        assert len(outer["Groups"]) == 4
        assert _leaf_entry_count(outer) == 6


# ---------------------------------------------------------------------------
# Half 2 -- the cardinality
# ---------------------------------------------------------------------------

def _cardinality_group(
    line: str,
    *,
    members: int = 3,
    group_type: str = "ALL",
    relation: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """A label plus ``members`` rows; the label carries ``relation`` as its annotation."""
    from src.services.criterion_annotation import ANNOTATION_KEY, check_relation

    gid = str(uuid.uuid4())
    rows = [{
        "id": 0,
        "description": "risk factor list",
        "domain": "Condition",
        "protocolLine": line,
        "logicType": "PRESENCE",
        "groupId": gid,
        "groupType": group_type,
        "isGroupLabel": True,
    }]
    rows += [{
        "id": i + 1,
        "description": f"risk factor {i + 1}",
        "domain": "Condition",
        "protocolLine": line,
        "logicType": "PRESENCE",
        "groupId": gid,
        "groupType": group_type,
    } for i in range(members)]
    if relation is not None:
        fields, rejected = check_relation(relation, line)
        assert rejected is None, rejected
        rows[0][ANNOTATION_KEY] = fields
    return rows


def _at_least(span: str, count: int) -> dict[str, Any]:
    return {"relation": "at_least", "relation_span": span, "cardinality": count}


class TestCardinalityComesFromTheStatedRelation:
    TWO_OF = (
        "Two or more of the following risk factors: age >= 60 years, documented "
        "hypercholesterolemia, documented diabetes mellitus"
    )
    NO_NUMBER = "Documented hypertension or documented diabetes mellitus"

    def test_should_emit_at_least_with_the_count_the_label_states(self, emitter):
        rows = _cardinality_group(self.TWO_OF, relation=_at_least("Two or more of the following", 2))
        expression = emitter._build_seeded_target_circe(_shell(rows))

        rule = expression["InclusionRules"][0]["expression"]
        assert rule["Type"] == "AT_LEAST"
        assert rule["Count"] == 2

    def test_should_not_read_a_count_off_the_line_when_no_relation_is_stated(self, emitter):
        """The line states "Two or more"; without a stated relation nothing reads it."""
        expression = emitter._build_seeded_target_circe(_shell(_cardinality_group(self.TWO_OF)))

        rule = expression["InclusionRules"][0]["expression"]
        assert not rule["Type"].startswith("AT_")
        assert "Count" not in rule

    def test_should_not_invent_a_count_for_a_line_that_states_no_number(self, emitter):
        expression = emitter._build_seeded_target_circe(
            _shell(_cardinality_group(self.NO_NUMBER))
        )

        rule = expression["InclusionRules"][0]["expression"]
        assert not rule["Type"].startswith("AT_")
        assert "Count" not in rule

    def test_should_decline_when_the_label_asks_for_more_members_than_survived(self, emitter):
        """Members are lost to mapping failures. `AT_LEAST 3` over two surviving
        members is unsatisfiable, and an unsatisfiable rule empties the cohort as
        quietly as a dropped criterion does."""
        line = "At least three of the following: A, B, C, D"
        rows = _cardinality_group(
            line, members=2, relation=_at_least("At least three of the following", 3)
        )

        expression = emitter._build_seeded_target_circe(_shell(rows))

        rule = expression["InclusionRules"][0]["expression"]
        assert not rule["Type"].startswith("AT_")

    def test_should_tighten_a_declared_any_group_that_states_two_of(self, emitter):
        rows = _cardinality_group(
            self.TWO_OF, group_type="ANY", relation=_at_least("Two or more of the following", 2)
        )
        expression = emitter._build_seeded_target_circe(_shell(rows))

        rule = expression["InclusionRules"][0]["expression"]
        assert rule["Type"] == "AT_LEAST"
        assert rule["Count"] == 2

    def test_should_keep_an_all_absence_group_as_all_when_no_relation_is_stated(self, emitter):
        """SPEC-INFRA-003 REQ-004 still owns an all-ABSENCE group that states nothing:
        N separate exclusions mean absence from the UNION."""
        rows = _cardinality_group(self.TWO_OF, group_type="ANY")
        for row in rows:
            row["logicType"] = "ABSENCE"

        expression = emitter._build_seeded_target_circe(
            {"targetCohortName": "T", "inclusionCriteria": [], "exclusionCriteria": rows}
        )

        assert expression["InclusionRules"][0]["expression"]["Type"] == "ALL"

    def test_should_negate_a_stated_at_least_over_an_exclusion_group(self, emitter):
        """Exclude when two or more of three are present = keep when at least two of the
        three are absent: AT_LEAST k - N + 1 over the absence members."""
        rows = _cardinality_group(
            self.TWO_OF, group_type="ANY", relation=_at_least("Two or more of the following", 2)
        )
        for row in rows:
            row["logicType"] = "ABSENCE"

        expression = emitter._build_seeded_target_circe(
            {"targetCohortName": "T", "inclusionCriteria": [], "exclusionCriteria": rows}
        )

        rule = expression["InclusionRules"][0]["expression"]
        assert (rule["Type"], rule["Count"]) == ("AT_LEAST", 2)

    def test_should_emit_any_for_a_stated_at_least_one(self, emitter):
        """`AT_LEAST 1` and `ANY` are the same rule."""
        line = "One of the following: A, B, C"
        rows = _cardinality_group(line, relation=_at_least("One of the following", 1))
        expression = emitter._build_seeded_target_circe(_shell(rows))

        rule = expression["InclusionRules"][0]["expression"]
        assert rule["Type"] == "ANY"
        assert "Count" not in rule
