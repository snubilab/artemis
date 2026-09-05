"""The concept set a criterion is wired to must be the one it was mapped from.

`_build_seeded_target_circe` walks the criteria twice. The first walk decides which
criteria reach the mapper, and the concept sets are appended in that order, so concept
set `k` is the set mapped from the `k`-th selected criterion. A second walk then
re-derives the same selection to pair each mapped result back with a criterion, and
pairs them by position. The two walks are separate code, so a filter added to one and
not the other silently re-pairs every criterion after the first divergence with a
neighbour's concept set.

That is not hypothetical. The restated-collapse drops (SPEC-INFRA-003 / SPEC-INFRA-004)
were added to the first walk only. In the 2026-08-27 six-trial store this left EMPA-REG
with 6 of 9 grouped rules and CAROLINA with 14 of 18 referencing concept sets belonging
to unrelated rules -- liver-enzyme sets under a malignancy rule, an eGFR set under a
stroke rule. The concept sets themselves were correct and every count still balanced,
which is why nothing downstream failed loudly and the defect reached a hospital.

These tests pin the pairing rather than either walk, so a filter added to one walk and
not the other is caught here instead of in a delivered CIRCE file.
"""
from __future__ import annotations

from typing import Any

import pytest

from src.services.restated_distinctness import COLLAPSE_REASON as DISTINCTNESS_REASON
from src.services.tte_service import TTEService


def _stub_concept_set(name: str, concept_id: int, domain: str = "Condition") -> dict[str, Any]:
    return {
        "name": name,
        "domain": domain,
        "expression": {
            "items": [
                {
                    "concept": {
                        "CONCEPT_ID": concept_id,
                        "CONCEPT_NAME": name,
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


@pytest.fixture
def service(monkeypatch) -> TTEService:
    """Every seed maps to its own concept set, named after the seed.

    Distinct names are the whole point: a mis-pairing is only visible when the set a
    rule references can be told apart from the set it should have referenced.
    """
    svc = TTEService.__new__(TTEService)
    concept_ids = {"empagliflozin": 1594973}

    def fake_recommend(seed_text: str, **kwargs: Any) -> dict[str, Any]:
        seed = seed_text.strip()
        domain = "Drug" if seed == "empagliflozin" else "Condition"
        concept_id = concept_ids.get(seed, abs(hash(seed)) % 900000 + 1000)
        return _stub_concept_set(seed, concept_id, domain)

    monkeypatch.setattr(svc, "_recommend_seeded_concept_set", fake_recommend)
    return svc


def _criterion(
    id: str,
    description: str,
    source_text: str,
    *,
    domain: str = "Condition",
    group_id: str | None = None,
) -> dict[str, Any]:
    return {
        "id": id,
        "domain": domain,
        "description": description,
        "sourceText": source_text,
        "valueConstraint": None,
        "groupId": group_id,
        "isGroupLabel": False,
        "logicType": "ABSENCE",
    }


def _eligibility(exclusion: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "targetCohortName": "empagliflozin",
        "inclusionCriteria": [],
        "exclusionCriteria": exclusion,
    }


# Two byte-identical restatements in different groups: SPEC-INFRA-004 collapses the
# second one, and that drop is what desynchronises the two walks.
ALCOHOL_RESTATEMENT = [
    _criterion("5", "Alcohol Use Disorder", "Alcohol Use Disorder", group_id="c8c4cfc2"),
    _criterion("49", "Alcohol Use Disorder", "Alcohol Use Disorder", group_id="ade8ea06"),
]

# A grouped pair sitting after the drop -- the population that gets re-paired.
CARDIOVASCULAR_GROUP = [
    _criterion("60", "Stroke", "Stroke", group_id="cv"),
    _criterion("61", "Myocardial Infarction", "Myocardial Infarction", group_id="cv"),
]


def _sets_by_id(circe: dict[str, Any]) -> dict[int, str]:
    return {cs["id"]: cs["name"] for cs in circe.get("ConceptSets") or []}


def _leaves(expression: dict[str, Any]) -> list[dict[str, Any]]:
    out = list(expression.get("CriteriaList") or [])
    for group in expression.get("Groups") or []:
        out.extend(_leaves(group))
    return out


def _referenced_set_names(circe: dict[str, Any], rule_name: str) -> list[str]:
    """The concept set names a named rule actually points at, in leaf order."""
    names = _sets_by_id(circe)
    matches = [r for r in circe.get("InclusionRules") or [] if r.get("name") == rule_name]
    assert matches, (
        "no rule named " + repr(rule_name) + "; emitted rules were "
        + repr([r.get("name") for r in circe.get("InclusionRules") or []])
    )
    assert len(matches) == 1, "expected exactly one rule named " + repr(rule_name)
    out = []
    for leaf in _leaves(matches[0].get("expression") or {}):
        body = leaf.get("Criteria", leaf)
        domain = next((k for k in body if isinstance(body[k], dict)), None)
        if domain is not None:
            out.append(names.get(body[domain].get("CodesetId")))
    return out


class TestTheTwoWalksStayInStep:
    def test_should_wire_a_group_to_its_own_concept_sets_when_an_earlier_criterion_was_collapsed(
        self, service
    ):
        """The regression itself. With the walks out of step the group is labelled
        'Stroke' alone and carries the myocardial-infarction set."""
        circe = service._build_seeded_target_circe(
            _eligibility(ALCOHOL_RESTATEMENT + CARDIOVASCULAR_GROUP)
        )
        assert _referenced_set_names(circe, "Stroke + Myocardial Infarction") == [
            "Stroke",
            "Myocardial Infarction",
        ]

    def test_should_wire_a_group_to_its_own_concept_sets_when_nothing_was_collapsed(self, service):
        """The control. Same group, no drop ahead of it -- this passes either way, and
        its job is to show the criterion above fails for the drop and not for the group."""
        circe = service._build_seeded_target_circe(_eligibility(CARDIOVASCULAR_GROUP))
        assert _referenced_set_names(circe, "Stroke + Myocardial Infarction") == [
            "Stroke",
            "Myocardial Infarction",
        ]

    def test_should_not_emit_a_rule_for_a_criterion_the_collapse_dropped(self, service):
        """The dropped criterion is recorded as skipped, so a rule bearing another
        criterion's concept set must not be emitted in its place."""
        circe = service._build_seeded_target_circe(
            _eligibility(ALCOHOL_RESTATEMENT + CARDIOVASCULAR_GROUP)
        )
        dropped = [
            r for r in circe["_skippedCriteria"] if r["reason"] == DISTINCTNESS_REASON
        ]
        assert [r["criterionId"] for r in dropped] == ["49"]
        assert len(circe["InclusionRules"]) == 2

    def test_should_reference_every_mapped_concept_set_exactly_once_when_a_criterion_was_collapsed(
        self, service
    ):
        """No concept set left orphaned and none used twice. The entry set (id 1) is
        excluded -- it is referenced from PrimaryCriteria, not from an inclusion rule."""
        circe = service._build_seeded_target_circe(
            _eligibility(ALCOHOL_RESTATEMENT + CARDIOVASCULAR_GROUP)
        )
        referenced = []
        for rule in circe["InclusionRules"]:
            for leaf in _leaves(rule.get("expression") or {}):
                body = leaf.get("Criteria", leaf)
                domain = next((k for k in body if isinstance(body[k], dict)), None)
                if domain is not None:
                    referenced.append(body[domain]["CodesetId"])
        mapped_ids = sorted(i for i in _sets_by_id(circe) if i != 1)
        assert sorted(referenced) == mapped_ids
        assert circe["_generationCensus"]["mapped"] == len(mapped_ids)
