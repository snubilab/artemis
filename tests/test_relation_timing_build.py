"""RFC-016 step 2 (RFC-014) in the build: group Type from the stated relation, and the
prospective skip with the lint that FAILs a prospective criterion emitted anyway.

Every row is real, copied verbatim into ``tests/fixtures/rfc016_relation_timing_rows.json``
(the 2026-10-12 prompt_f2 candidate store, and InclusionRules[14] of its delivered
``carolina_treatment.circe.json``; paths and SHA-256 inside). Annotations are stubbed with
fragments of each row's own line. The mapper is a stub; Agent 2 raises on construction.

What is pinned:

* a group's CIRCE ``Type`` comes from the relation its label states (planner first, then
  annotation), by the RFC-014 §2-1 table -- an ABSENCE group negates it;
* without a verified relation the declared type stands, except the structural De Morgan
  rewrite of an all-ABSENCE ``ANY`` group (SPEC-INFRA-003 REQ-004), which never touches a
  verified relation; the connective words in the line decide nothing any more (A18 gone);
* a criterion annotated ``prospective`` (span in its line) is not emitted and is recorded
  under ``prospective-not-observable-at-index``; a prospective label takes its members;
* ``circe_lint.prospective_occurrence_criteria`` FAILs the real delivered rule 14 once its
  store label carries that annotation, and is silent without it.
"""

from __future__ import annotations

import json
import zlib
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from src.services import criterion_annotation as annotation_mod
from src.services.tte_service import TTEService

FIXTURE = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "rfc016_relation_timing_rows.json").read_text()
)
CAROLINA_HEAD = FIXTURE["carolina_inclusion_1"]
CAROLINA_REVASC = FIXTURE["carolina_exclusion_25"]
LEADER_OADS = FIXTURE["leader_inclusion_12"]
LEADER_CHF = FIXTURE["leader_exclusion_10"]
PLATO_TWO_OF = FIXTURE["plato_inclusion_32"]
ARISTOTLE_LIVER = FIXTURE["aristotle_exclusion_1"]
ARISTOTLE_ABLATION = FIXTURE["aristotle_exclusion_21"][0]
CAROLINA_RULE_14 = FIXTURE["carolina_treatment_inclusion_rule_14"]

HEAD_SPAN = "T2DM and concurrently insufficient glycaemic control and a high risk of CV events"
OADS_SPAN = (
    "Anti-diabetic drug naive or treated with one or more oral anti-diabetic drugs (OADs) or "
    "treated with human NPH insulin"
)
LIVER_SPAN = "ALT or AST > 2X ULN or a Total Bilirubin"
REVASC_PLANNED_SPAN = (
    "Pre-planned coronary artery re-vascularisation (PCI, CABG) within next 6 months after V1a"
)


def _payload(**fields: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"record_requirement": "required", "excepted_entities": []}
    base.update(fields)
    return base


def _annotated(row: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    row = deepcopy(row)
    fields, rejected = annotation_mod.validate_annotation(payload, row["protocolLine"])
    row[annotation_mod.ANNOTATION_KEY] = {"promptVersion": "test", "model": "stub", **fields}
    if rejected:
        row[annotation_mod.ANNOTATION_REJECTED_KEY] = rejected
    return row


def _liver_rows_with_thresholds() -> list[dict[str, Any]]:
    """ARISTOTLE's liver group with each member's threshold annotated.

    The members store "x ULN" in ``unitText`` under ``referenceBound: absolute``. Since the
    ratio is read only from the annotation's ``reference_bound`` (RFC-016 step 3, A21
    deleted), an unannotated member is an absolute bound in an unresolvable unit and is
    refused, which would leave no rule whose group type these tests could read.
    """
    spans = {2: "> 2X ULN", 3: "> 2X ULN", 4: "≥ 1.5X ULN"}
    rows = deepcopy(ARISTOTLE_LIVER)
    return [rows[0]] + [
        _annotated(
            row,
            _payload(
                threshold_span=spans[row["id"]], quantity_kind="lab_value", reference_bound="uln"
            ),
        )
        for row in rows[1:]
    ]


def _with_label(rows: list[dict[str, Any]], payload: dict[str, Any]) -> list[dict[str, Any]]:
    """The group's rows, its label (the first row) carrying ``payload``'s annotation."""
    return [_annotated(rows[0], payload), *deepcopy(rows[1:])]


def _stub_concept_set(seed: str, domain: str) -> dict[str, Any]:
    concept_id = zlib.crc32(seed.encode()) % 10**8
    return {
        "name": seed,
        "domain": domain,
        "expression": {
            "items": [
                {
                    "concept": {
                        "CONCEPT_ID": concept_id,
                        "CONCEPT_NAME": seed,
                        "CONCEPT_CODE": str(concept_id),
                        "DOMAIN_ID": domain,
                        "VOCABULARY_ID": "SNOMED",
                        "CONCEPT_CLASS_ID": "Clinical Finding",
                    },
                    "includeDescendants": True,
                    "isExcluded": False,
                }
            ]
        },
        "mapping_metadata": None,
    }


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
        return _stub_concept_set(seed_text.strip(), kwargs.get("expected_domain") or "Condition")

    monkeypatch.setattr(svc, "_recommend_seeded_concept_set", fake_recommend)
    return svc


def _build(service: TTEService, *, inclusion=(), exclusion=()) -> dict[str, Any]:
    return service._build_seeded_target_circe(
        {
            "targetCohortName": "linagliptin",
            "inclusionCriteria": deepcopy(list(inclusion)),
            "exclusionCriteria": deepcopy(list(exclusion)),
        }
    )


def _only_rule(circe: dict[str, Any]) -> dict[str, Any]:
    assert len(circe["InclusionRules"]) == 1, [r["name"] for r in circe["InclusionRules"]]
    return circe["InclusionRules"][0]["expression"]


class TestTheGroupTypeComesFromTheStatedRelation:
    def test_should_emit_any_when_an_absence_group_states_all(self, service):
        """LEADER "Chronic heart failure (NYHA class IV)": exclude only a patient with both.
        Declared ALL today, which excludes every heart-failure patient."""
        rows = _with_label(
            LEADER_CHF,
            _payload(relation="all", relation_span="Chronic heart failure (NYHA class IV)"),
        )
        assert _only_rule(_build(service, exclusion=rows))["Type"] == "ANY"

    def test_should_emit_all_when_a_presence_group_states_all(self, service):
        """CAROLINA's T2DM head rule, declared ANY, states "and concurrently ... and"."""
        rows = _with_label(CAROLINA_HEAD, _payload(relation="all", relation_span=HEAD_SPAN))
        assert _only_rule(_build(service, inclusion=rows))["Type"] == "ALL"

    def test_should_emit_any_when_a_presence_group_states_any(self, service):
        rows = _with_label(LEADER_OADS, _payload(relation="any", relation_span=OADS_SPAN))
        assert _only_rule(_build(service, inclusion=rows))["Type"] == "ANY"

    def test_should_keep_the_declared_all_when_no_relation_is_stated(self, service):
        """The line's "or" is no longer read by the builder (A18 removed)."""
        assert _only_rule(_build(service, inclusion=LEADER_OADS))["Type"] == "ALL"

    def test_should_keep_the_declared_all_when_the_relation_span_is_not_in_the_line(
        self, service
    ):
        rows = _with_label(
            LEADER_OADS, _payload(relation="any", relation_span="drug naive or treated with OADs")
        )
        assert rows[0][annotation_mod.ANNOTATION_REJECTED_KEY][0]["field"] == "relation"
        assert _only_rule(_build(service, inclusion=rows))["Type"] == "ALL"

    def test_should_read_the_planner_relation_before_the_annotation(self, service):
        rows = _with_label(CAROLINA_HEAD, _payload(relation="any", relation_span="T2DM and"))
        rows[0][annotation_mod.PLANNER_RELATION_KEY] = {
            "relation": "all",
            "relation_span": HEAD_SPAN,
            "cardinality": None,
        }
        assert _only_rule(_build(service, inclusion=rows))["Type"] == "ALL"

    def test_should_keep_the_declared_type_when_at_least_asks_for_more_members_than_emit(
        self, service
    ):
        """PLATO "≥2 of the following:" reached the store with one member."""
        rows = _with_label(
            PLATO_TWO_OF,
            _payload(relation="at_least", relation_span="≥2 of the following", cardinality=2),
        )
        rule = _only_rule(_build(service, inclusion=rows))
        assert rule["Type"] == "ANY"
        assert "Count" not in rule

    def test_should_still_rewrite_an_all_absence_any_group_when_no_relation_is_stated(
        self, service
    ):
        """SPEC-INFRA-003 REQ-004: structural, reads no text."""
        assert ARISTOTLE_LIVER[0]["groupType"] == "ANY"
        assert _only_rule(_build(service, exclusion=_liver_rows_with_thresholds()))["Type"] == "ALL"

    def test_should_emit_all_when_an_absence_group_states_any(self, service):
        rows = _with_label(
            _liver_rows_with_thresholds(), _payload(relation="any", relation_span=LIVER_SPAN)
        )
        assert _only_rule(_build(service, exclusion=rows))["Type"] == "ALL"


class TestTheRelationTable:
    """RFC-014 §2-1, plus AT_LEAST: numbers in, CIRCE type out; no text anywhere."""

    @pytest.mark.parametrize(
        "logic,relation,cardinality,members,expected",
        [
            ("PRESENCE", "all", None, 3, ("ALL", None)),
            ("PRESENCE", "any", None, 3, ("ANY", None)),
            ("ABSENCE", "any", None, 3, ("ALL", None)),
            ("ABSENCE", "all", None, 3, ("ANY", None)),
            ("PRESENCE", "at_least", 2, 5, ("AT_LEAST", 2)),
            ("PRESENCE", "at_least", 1, 5, ("ANY", None)),
            ("PRESENCE", "at_least", 5, 5, ("ALL", None)),
            ("ABSENCE", "at_least", 2, 5, ("AT_LEAST", 4)),
            ("ABSENCE", "at_least", 1, 5, ("ALL", None)),
            ("ABSENCE", "at_least", 5, 5, ("ANY", None)),
            ("PRESENCE", "at_least", 2, 1, None),
            ("PRESENCE", "all", None, 0, None),
        ],
    )
    def test_should_map_relation_and_logic_to_a_circe_type(
        self, logic, relation, cardinality, members, expected
    ):
        assert annotation_mod.relation_group_type(logic, relation, cardinality, members) == (
            expected
        )


class TestAProspectiveCriterionIsNotEmitted:
    def test_should_record_the_label_and_its_members_as_prospective_skips(self, service):
        rows = _with_label(
            CAROLINA_REVASC, _payload(timing="prospective", window_span=REVASC_PLANNED_SPAN)
        )
        circe = _build(service, exclusion=rows)
        assert circe["InclusionRules"] == []
        skips = {r["criterionId"]: r for r in circe["_skippedCriteria"]}
        assert set(skips) == {"25", "26", "27"}
        for record in skips.values():
            assert record["reason"] == annotation_mod.PROSPECTIVE_REASON
            assert record["windowSpan"] == REVASC_PLANNED_SPAN
            assert record["timingDecidedBy"] == "25"
        assert circe["_generationCensus"]["skippedByReason"] == {
            annotation_mod.PROSPECTIVE_REASON: 3
        }

    def test_should_emit_as_before_when_the_window_span_is_not_in_the_line(self, service):
        rows = _with_label(
            CAROLINA_REVASC, _payload(timing="prospective", window_span="planned in 6 months")
        )
        circe = _build(service, exclusion=rows)
        assert len(circe["InclusionRules"]) == 1
        assert [r["reason"] for r in circe["_skippedCriteria"]] == ["group-label"]

    def test_should_skip_a_flat_prospective_exclusion(self, service):
        row = _annotated(ARISTOTLE_ABLATION, _payload(timing="prospective", window_span="Planned"))
        circe = _build(service, exclusion=[row])
        assert circe["InclusionRules"] == []
        assert circe["_skippedCriteria"][0]["reason"] == annotation_mod.PROSPECTIVE_REASON

    def test_should_emit_a_prior_criterion_as_before(self, service):
        row = _annotated(ARISTOTLE_ABLATION, _payload(timing="prior", window_span=None))
        assert len(_build(service, exclusion=[row])["InclusionRules"]) == 1


class TestTheLintFailsAProspectiveOccurrence:
    """The negative case is the real delivered rule: CAROLINA treatment InclusionRules[14]
    'Pre-planned PCI + Pre-planned CABG' over codesets 48 and 49, which the store rows 26
    and 27 carry as their conceptSetId."""

    @staticmethod
    def _study(rows: list[dict[str, Any]]) -> dict[str, Any]:
        return {"eligibility": {"inclusionCriteria": [], "exclusionCriteria": rows}}

    @staticmethod
    def _expression() -> dict[str, Any]:
        return {"InclusionRules": [deepcopy(CAROLINA_RULE_14)]}

    def test_should_fail_when_a_prospective_criterion_reached_the_file_as_an_occurrence(self):
        from src.utils.circe_lint import prospective_occurrence_criteria

        rows = _with_label(
            CAROLINA_REVASC, _payload(timing="prospective", window_span=REVASC_PLANNED_SPAN)
        )
        assert [r.get("conceptSetId") for r in rows] == [None, 48, 49]
        findings = prospective_occurrence_criteria(self._expression(), self._study(rows))
        assert len(findings) == 2, findings
        assert all("prospective" in f for f in findings)
        assert any("exclusion #26" in f for f in findings)
        assert any("exclusion #27" in f for f in findings)

    def test_should_stay_silent_when_no_criterion_is_annotated_prospective(self):
        from src.utils.circe_lint import prospective_occurrence_criteria

        study = self._study(deepcopy(CAROLINA_REVASC))
        assert prospective_occurrence_criteria(self._expression(), study) == []

    def test_should_stay_silent_when_the_prospective_rows_did_not_emit(self, service):
        from src.utils.circe_lint import prospective_occurrence_criteria

        rows = _with_label(
            CAROLINA_REVASC, _payload(timing="prospective", window_span=REVASC_PLANNED_SPAN)
        )
        built = _build(service, exclusion=rows)
        assert prospective_occurrence_criteria(built, self._study(rows)) == []

    def test_should_read_the_refs_map_when_the_file_carries_one(self):
        from src.utils.circe_lint import prospective_occurrence_criteria

        rows = _with_label(
            CAROLINA_REVASC, _payload(timing="prospective", window_span=REVASC_PLANNED_SPAN)
        )
        expression = {**self._expression(), "_criterionConceptSetRefs": {"exclusion:27": 49}}
        findings = prospective_occurrence_criteria(expression, self._study(rows))
        assert len(findings) == 1 and "exclusion #27" in findings[0], findings
