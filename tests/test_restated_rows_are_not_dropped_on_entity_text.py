"""A criterion is no longer dropped because another row of its role carries the same entity text.

`restated_distinctness.analyze_restated_groups` grouped a role's rows on
``(domain, sourceText, window, valueConstraint, logicType)`` before mapping and dropped every
row of a class but the first. ``sourceText`` is entity text, so two rows were declared one fact
because their words were equal. Measured on the 2026-10-12 P3 dry arms it dropped rows that state
a different fact -- LEADER inclusion #40 ("age min. 60 years") under #34 ("age min. 50 years") --
and rows the mapper is asked something different for: CARMELINA's second "Hypersensitivity" row
carries a stated exception its survivor does not, and the second "PCI" row a different base span.

What stands in its place is structural and runs after mapping: a rule that selects exactly what
another rule selects is collapsed by :mod:`src.services.restated_rules` on concept-set content,
never on names. A row whose own fields make it a skip is skipped under its own reason.

Rows: ``tests/fixtures/restated_text_key_rows.json``, verbatim, with each source's SHA-256.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from src.services.restated_distinctness import COLLAPSE_REASON
from src.services.restated_rules import IDENTICAL_REASON
from src.services.tte_service import TTEService
from src.utils.circe_lint import CRITERION_CONCEPT_SET_REFS_KEY

ROWS = json.loads(
    (Path(__file__).parent / "fixtures" / "restated_text_key_rows.json").read_text()
)


def _rows(section: str) -> list[dict[str, Any]]:
    return copy.deepcopy(ROWS[section]["rows"])


class _Mapper:
    """A mapper that answers each distinct request with its own concept, and only that one.

    The request is what `_recommend_seeded_concept_set` is asked: the seed, the domain and the
    stated exception. Equal requests get the same set -- what the criterion cache gives -- so
    two rows select the same thing exactly when the build asked the same thing for both.
    """

    def __init__(self) -> None:
        self.requests: list[tuple[Any, ...]] = []
        self._concepts: dict[tuple[Any, ...], int] = {}

    def __call__(
        self,
        seed_text: str,
        *,
        expected_domain: str | None = None,
        entity_exception: Any = None,
        **_: Any,
    ) -> dict[str, Any]:
        exception = (
            None
            if entity_exception is None
            else (entity_exception.base, tuple(entity_exception.excepted))
        )
        request = (seed_text, expected_domain, exception)
        self.requests.append(request)
        concept_id = self._concepts.setdefault(request, 9_000_000 + len(self._concepts))
        domain = expected_domain or "Condition"
        return {
            "name": f"set {concept_id}",
            "domain": domain,
            "expression": {
                "items": [
                    {
                        "concept": {
                            "CONCEPT_ID": concept_id,
                            "CONCEPT_NAME": f"concept {concept_id}",
                            "CONCEPT_CODE": str(concept_id),
                            "DOMAIN_ID": domain,
                            "VOCABULARY_ID": "SNOMED",
                            "CONCEPT_CLASS_ID": "Clinical Finding",
                            "STANDARD_CONCEPT": "S",
                        },
                        "includeDescendants": True,
                        "isExcluded": False,
                    }
                ]
            },
            "mapping_metadata": None,
        }


@pytest.fixture
def mapper() -> _Mapper:
    return _Mapper()


@pytest.fixture
def build(monkeypatch, mapper):
    svc = TTEService.__new__(TTEService)
    monkeypatch.setattr(svc, "_recommend_seeded_concept_set", mapper)

    def _build(*, inclusion=(), exclusion=()) -> dict[str, Any]:
        return svc._build_seeded_target_circe(
            {
                "targetCohortName": "empagliflozin",
                "inclusionCriteria": list(inclusion),
                "exclusionCriteria": list(exclusion),
            }
        )

    return _build


def _skip_reasons(circe: dict[str, Any]) -> dict[str, str]:
    return {f"{r['role']}:{r['criterionId']}": r["reason"] for r in circe["_skippedCriteria"]}


def _balances(census: dict[str, Any]) -> bool:
    return census["total"] == (
        census["mapped"] + census["unmapped"] + census["demographicRules"] + census["skipped"]
    )


class TestARowSharingEntityTextIsDecidedOnItsOwnFields:
    def test_should_not_skip_the_age_60_row_as_restated_when_it_shares_entity_text_with_age_50(
        self, build
    ):
        """LEADER #34 and #40 both carry ``sourceText`` "age" and no value constraint in one
        ANY group, and quote "age min. 50" and "age min. 60" from one line. They are not one
        fact; #40 is accounted for under whatever its own fields decide."""
        rows = _rows("leader_age_group")
        assert {r["id"]: r["protocolSpan"] for r in rows if r["id"] in (34, 40)} == {
            34: "age min. 50 years at screening",
            40: "age min. 60 years at screening",
        }
        circe = build(inclusion=rows)
        reasons = _skip_reasons(circe)
        assert reasons.get("inclusion:40") != COLLAPSE_REASON
        assert COLLAPSE_REASON not in reasons.values()
        assert _balances(circe["_generationCensus"])

    @pytest.mark.parametrize(
        "section,member",
        [
            # Same entity text as #29; this row's annotation states an exception #29's does not.
            ("carmelina_hypersensitivity_group", "exclusion:31"),
            ("carmelina_hypersensitivity_group", "exclusion:32"),
            # Same entity text "PCI" as #29; quotes "any previous PCI" under a different base span.
            ("carmelina_revascularisation_group", "exclusion:31"),
        ],
    )
    def test_should_map_a_member_when_another_member_shares_its_entity_text(
        self, build, section, member
    ):
        circe = build(exclusion=_rows(section))
        assert member in circe[CRITERION_CONCEPT_SET_REFS_KEY]
        assert COLLAPSE_REASON not in _skip_reasons(circe).values()
        assert _balances(circe["_generationCensus"])

    def test_should_ask_the_mapper_for_each_rows_own_exception_when_entity_text_is_equal(
        self, build, mapper
    ):
        build(exclusion=_rows("carmelina_hypersensitivity_group"))
        hypersensitivity = {r for r in mapper.requests if r[0] == "Hypersensitivity"}
        assert len(hypersensitivity) == 2, hypersensitivity
        assert {r[2] is None for r in hypersensitivity} == {True, False}


class TestARestatedGroupIsCollapsedOnWhatItSelects:
    def test_should_collapse_the_restated_blood_pressure_group_when_its_rule_selects_the_same(
        self, build
    ):
        """ARISTOTLE exclusion group #18 restates group #15 member for member (systolic > 180,
        diastolic > 100 mm Hg). Both groups map; the second rule selects exactly what the first
        does, and the rule-level collapse removes it and names both of its criteria."""
        circe = build(exclusion=_rows("aristotle_restated_blood_pressure_groups"))
        (record,) = circe["_restatedRuleCollapse"]
        assert record["reason"] == IDENTICAL_REASON
        assert record["criterionKeys"] == ["exclusion:19", "exclusion:20"]
        assert record["survivorCriterionKeys"] == ["exclusion:16", "exclusion:17"]
        assert len(circe["InclusionRules"]) == 1
        assert _balances(circe["_generationCensus"])
