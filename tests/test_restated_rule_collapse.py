"""Two inclusion rules that say the same thing, or one that says part of what another says.

Measured on ``deliveries/2026-09-23``: CARMELINA #11 'Exclusion of GLP-1 receptor agonists if
recent + ...' and #14 'Use of GLP-1 receptor agonists + ...' are each ALL of three DrugExposure
exactly-0 criteria over member-identical GLP-1 / DPP-4 / SGLT-2 sets in the same window, from
two different store groups (inclusion 85eaf366, exclusion 773392a3), and #15 'DPP-4 inhibitors'
is one of #11's conjuncts on its own. CIRCE AND-combines every inclusion rule, so #14 and #15 add
nothing -- both sites' Atlas reports show the same N for #11 and #14. The IR-level restated paths
cannot see it: the pair spans two roles and two description stems.

The predicate lives in :mod:`src.services.restated_rules`, and the builder and the delivery gate
both import it from there.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from src.services.restated_rules import (
    IDENTICAL_REASON,
    IMPLIED_REASON,
    RESTATED_RULE_COLLAPSE_KEY,
    collapse_redundant_inclusion_rules,
    redundant_inclusion_rules,
    rule_relation,
)

REPO = Path(__file__).resolve().parents[1]
DELIVERY_0923 = REPO / "deliveries" / "2026-09-23"


def _cs(
    codeset_id: int,
    name: str,
    members: list[int],
    *,
    descendants: bool = True,
    excluded: bool = False,
) -> dict[str, Any]:
    return {
        "id": codeset_id,
        "name": name,
        "expression": {
            "items": [
                {
                    "concept": {"CONCEPT_ID": m, "CONCEPT_NAME": f"c{m}"},
                    "includeDescendants": descendants,
                    "isExcluded": excluded,
                    "includeMapped": False,
                }
                for m in members
            ]
        },
    }


def _entry(
    codeset_id: int,
    *,
    table: str = "DrugExposure",
    days: int = 7,
    occurrence: tuple[int, int] = (0, 0),
    **payload: Any,
) -> dict[str, Any]:
    return {
        "Criteria": {table: {"CodesetId": codeset_id, **payload}},
        "StartWindow": {"Start": {"Days": days, "Coeff": -1}, "End": {"Days": 0, "Coeff": 1}},
        "RestrictVisit": False,
        "IgnoreObservationPeriod": False,
        "Occurrence": {"Type": occurrence[0], "Count": occurrence[1]},
    }


def _group(entries: list[dict[str, Any]], group_type: str = "ALL") -> dict[str, Any]:
    return {
        "Type": group_type,
        "CriteriaList": entries,
        "DemographicCriteriaList": [],
        "Groups": [],
    }


def _rule(name: str, *subgroups: dict[str, Any], group_type: str = "ALL") -> dict[str, Any]:
    """A grouped rule the way the builder emits it: a typed root holding one group per member."""
    return {
        "name": name,
        "expression": {
            "Type": group_type,
            "CriteriaList": [],
            "DemographicCriteriaList": [],
            "Groups": list(subgroups),
        },
    }


def _expression(concept_sets: list[dict[str, Any]], rules: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "ConceptSets": concept_sets,
        "PrimaryCriteria": {"CriteriaList": [{"DrugEra": {"CodesetId": 1}}]},
        "InclusionRules": rules,
    }


GLP1, DPP4, SGLT2 = [11, 12], [21, 22], [31, 32]


def _carmelina_shape() -> dict[str, Any]:
    """#0 triple absence, #1 the same triple over other codeset ids, #2 one conjunct of it."""
    return _expression(
        [
            _cs(1, "entry", [1]),
            _cs(2, "GLP-1 receptor agonists", GLP1),
            _cs(3, "DPP-4 inhibitors", DPP4),
            _cs(4, "SGLT-2 inhibitors", SGLT2),
            _cs(5, "GLP-1 receptor agonists", GLP1),
            _cs(6, "DPP-4 inhibitors", DPP4),
            _cs(7, "SGLT-2 inhibitors", SGLT2),
            _cs(8, "DPP-4 inhibitors", DPP4),
        ],
        [
            _rule(
                "Exclusion if recent", _group([_entry(2)]), _group([_entry(3)]), _group([_entry(4)])
            ),
            _rule("Use of", _group([_entry(5)]), _group([_entry(6)]), _group([_entry(7)])),
            _rule("DPP-4 inhibitors", _group([_entry(8)])),
        ],
    )


class TestRulePredicate:
    def test_should_find_identical_when_only_codeset_ids_and_names_differ(self):
        expression = _carmelina_shape()
        rules = expression["InclusionRules"]
        assert (
            rule_relation(rules[1]["expression"], rules[0]["expression"], expression["ConceptSets"])
            == "identical"
        )

    def test_should_find_implied_when_every_conjunct_appears_in_the_other_rule(self):
        expression = _carmelina_shape()
        rules = expression["InclusionRules"]
        assert (
            rule_relation(rules[2]["expression"], rules[0]["expression"], expression["ConceptSets"])
            == "implied"
        )
        # Implication has a direction: the triple is not implied by its single conjunct.
        assert (
            rule_relation(rules[0]["expression"], rules[2]["expression"], expression["ConceptSets"])
            is None
        )

    def test_should_not_relate_when_members_match_but_windows_differ(self):
        sets = [_cs(2, "GLP-1", GLP1), _cs(3, "GLP-1", GLP1)]
        recent = _rule("a", _group([_entry(2, days=7)]))["expression"]
        longer = _rule("b", _group([_entry(3, days=90)]))["expression"]
        assert rule_relation(longer, recent, sets) is None

    def test_should_not_relate_when_include_descendants_differs(self):
        sets = [_cs(2, "GLP-1", GLP1), _cs(3, "GLP-1", GLP1, descendants=False)]
        a = _rule("a", _group([_entry(2)]))["expression"]
        b = _rule("b", _group([_entry(3)]))["expression"]
        assert rule_relation(b, a, sets) is None

    def test_should_not_relate_a_presence_to_an_absence_over_the_same_set(self):
        sets = [_cs(2, "GLP-1", GLP1)]
        absent = _rule("a", _group([_entry(2, occurrence=(0, 0))]))["expression"]
        present = _rule("b", _group([_entry(2, occurrence=(2, 1))]))["expression"]
        assert rule_relation(present, absent, sets) is None

    def test_should_not_relate_when_value_filters_differ(self):
        sets = [_cs(2, "ALT", [3006923]), _cs(3, "ALT", [3006923])]
        gt3 = _rule(
            "a", _group([_entry(2, table="Measurement", RangeHighRatio={"Value": 3.0, "Op": "gt"})])
        )
        gte3 = _rule(
            "b",
            _group([_entry(3, table="Measurement", RangeHighRatio={"Value": 3.0, "Op": "gte"})]),
        )
        assert rule_relation(gte3["expression"], gt3["expression"], sets) is None

    def test_should_not_relate_a_rule_under_any_even_with_identical_members(self):
        """An ANY root (or an ANY anywhere below it) is not a conjunction: never collapsed."""
        sets = [_cs(2, "GLP-1", GLP1), _cs(3, "GLP-1", GLP1)]
        all_rule = _rule("a", _group([_entry(2)]))["expression"]
        any_rule = _rule("b", _group([_entry(3)]), group_type="ANY")["expression"]
        nested_any = _rule("c", _group([_entry(3)], group_type="ANY"))["expression"]
        assert rule_relation(any_rule, all_rule, sets) is None
        assert rule_relation(all_rule, any_rule, sets) is None
        assert rule_relation(nested_any, all_rule, sets) is None
        assert rule_relation(all_rule, nested_any, sets) is None

    def test_should_not_imply_when_the_rule_carries_a_conjunct_the_other_lacks(self):
        expression = _carmelina_shape()
        sets = expression["ConceptSets"] + [_cs(9, "insulin", [41])]
        extra = _rule("x", _group([_entry(8)]), _group([_entry(9)]))["expression"]
        assert rule_relation(extra, expression["InclusionRules"][0]["expression"], sets) is None


class TestRedundantRuleSelection:
    def test_should_select_the_carmelina_pair_and_the_single_onto_the_first_rule(self):
        found = redundant_inclusion_rules(_carmelina_shape())
        assert [(f["index"], f["survivorIndex"], f["reason"]) for f in found] == [
            (1, 0, IDENTICAL_REASON),
            (2, 0, IMPLIED_REASON),
        ]

    def test_should_never_collapse_onto_a_rule_that_is_itself_dropped(self):
        """A chain single < pair < triple, with the triple last: both go onto the triple."""
        sets = [_cs(2, "a", [1]), _cs(3, "b", [2]), _cs(4, "c", [3])]
        expression = _expression(
            sets,
            [
                _rule("single", _group([_entry(2)])),
                _rule("pair", _group([_entry(2)]), _group([_entry(3)])),
                _rule("pair again", _group([_entry(2)]), _group([_entry(3)])),
                _rule("triple", _group([_entry(2)]), _group([_entry(3)]), _group([_entry(4)])),
            ],
        )
        found = redundant_inclusion_rules(expression)
        assert [(f["index"], f["survivorIndex"]) for f in found] == [(0, 3), (1, 3), (2, 3)]
        dropped = {f["index"] for f in found}
        assert all(f["survivorIndex"] not in dropped for f in found)

    def test_should_select_nothing_when_rules_differ(self):
        sets = [_cs(2, "a", [1]), _cs(3, "b", [2])]
        expression = _expression(
            sets, [_rule("a", _group([_entry(2)])), _rule("b", _group([_entry(3)]))]
        )
        assert redundant_inclusion_rules(expression) == []

    def test_should_treat_exclusion_side_absences_like_any_other_conjunct(self):
        """An exclusion is an inclusion rule demanding exactly 0 occurrences; nothing is
        role-specific. The same absence restated as an inclusion collapses the same way."""
        sets = [_cs(2, "a", [1]), _cs(3, "a", [1])]
        expression = _expression(
            sets,
            [
                _rule("Exclusion: recent a", _group([_entry(2, occurrence=(0, 0))])),
                _rule("Inclusion: no recent a", _group([_entry(3, occurrence=(0, 0))])),
            ],
        )
        assert [
            (f["index"], f["survivorIndex"]) for f in redundant_inclusion_rules(expression)
        ] == [(1, 0)]


class TestCollapse:
    def test_should_remove_the_redundant_rules_and_record_each_onto_its_survivor(self):
        expression = _carmelina_shape()
        before = deepcopy(expression)
        keys = [
            ["inclusion:4", "inclusion:5", "inclusion:6"],
            ["exclusion:3", "exclusion:4", "exclusion:5"],
            ["exclusion:7"],
        ]
        records = collapse_redundant_inclusion_rules(expression, keys)

        assert [r["name"] for r in expression["InclusionRules"]] == ["Exclusion if recent"]
        assert expression["InclusionRules"][0] == before["InclusionRules"][0]
        assert expression["ConceptSets"] == before["ConceptSets"]
        assert expression["PrimaryCriteria"] == before["PrimaryCriteria"]
        assert expression[RESTATED_RULE_COLLAPSE_KEY] == records
        assert [(r["rule"], r["survivorRule"], r["reason"]) for r in records] == [
            ("Use of", "Exclusion if recent", IDENTICAL_REASON),
            ("DPP-4 inhibitors", "Exclusion if recent", IMPLIED_REASON),
        ]
        assert records[0]["criterionKeys"] == ["exclusion:3", "exclusion:4", "exclusion:5"]
        assert records[0]["survivorCriterionKeys"] == ["inclusion:4", "inclusion:5", "inclusion:6"]
        assert records[1]["expression"] == before["InclusionRules"][2]["expression"]

    def test_should_write_the_key_present_and_empty_when_nothing_collapses(self):
        expression = _expression([_cs(2, "a", [1])], [_rule("a", _group([_entry(2)]))])
        assert collapse_redundant_inclusion_rules(expression) == []
        assert expression[RESTATED_RULE_COLLAPSE_KEY] == []
        assert len(expression["InclusionRules"]) == 1

    def test_should_refuse_criterion_keys_that_do_not_align_with_the_rules(self):
        with pytest.raises(ValueError):
            collapse_redundant_inclusion_rules(_carmelina_shape(), [["inclusion:1"]])


class TestRealDelivery:
    @pytest.mark.parametrize("arm", ["treatment", "comparator"])
    def test_should_select_carmelina_14_and_15_onto_11_in_the_0923_delivery(self, arm):
        expression = json.loads((DELIVERY_0923 / f"carmelina_{arm}.circe.json").read_text())
        rules = expression["InclusionRules"]
        found = [
            (f["index"] + 1, f["survivorIndex"] + 1, f["reason"])
            for f in redundant_inclusion_rules(expression)
        ]
        assert found == [(14, 11, IDENTICAL_REASON), (15, 11, IMPLIED_REASON)]
        assert rules[13]["name"].startswith("Use of GLP-1 receptor agonists")
        assert rules[14]["name"] == "DPP-4 inhibitors"

    @pytest.mark.parametrize("study", ["carolina", "empa-reg"])
    def test_should_select_nothing_where_the_0923_rules_are_not_identical(self, study):
        """EMPA-REG #8/#18 are NOT identical in the delivered file: the AST set of #18 (codeset
        35) carries 44810795 'Aspartate transaminase activity measurement' and #8's (codeset 12)
        does not. CAROLINA #3/#10 differ in group type (#10 is ANY). Exact identity only."""
        for arm in ("treatment", "comparator"):
            expression = json.loads((DELIVERY_0923 / f"{study}_{arm}.circe.json").read_text())
            assert redundant_inclusion_rules(expression) == []


class _Metadata:
    """Stands in for the mapper's pydantic metadata: the builder only calls ``model_dump``."""

    def __init__(self, query: str) -> None:
        self.query = query

    def model_dump(self) -> dict[str, Any]:
        return {"queryUsed": self.query}


class TestBuildWiring:
    """`_build_seeded_target_circe` collapses after the rules are assembled, and the census
    is untouched: the collapsed criteria did map, and their concept sets stay in the file."""

    @staticmethod
    def _service(monkeypatch):
        from src.services.tte_service import TTEService

        svc = TTEService.__new__(TTEService)
        members = {"glp1": 793143, "dpp4": 19122137, "entry": 1594973}

        def fake_recommend(seed_text: str, **kwargs: Any) -> dict[str, Any]:
            key = seed_text.strip().lower()
            cid = next(v for k, v in members.items() if k in key)
            domain = "Drug"
            return {
                "name": seed_text.strip(),
                "domain": domain,
                "mapping_metadata": _Metadata(seed_text.strip()),
                "expression": {
                    "items": [
                        {
                            "concept": {
                                "CONCEPT_ID": cid,
                                "CONCEPT_NAME": key,
                                "CONCEPT_CODE": str(cid),
                                "DOMAIN_ID": domain,
                                "VOCABULARY_ID": "RxNorm",
                                "CONCEPT_CLASS_ID": "Ingredient",
                            },
                            "includeDescendants": True,
                            "isExcluded": False,
                        }
                    ]
                },
            }

        monkeypatch.setattr(svc, "_recommend_seeded_concept_set", fake_recommend)
        return svc

    @staticmethod
    def _criterion(cid: int, text: str, group: str, *, label: bool = False) -> dict[str, Any]:
        return {
            "id": cid,
            "domain": "Drug",
            "description": text,
            "sourceText": text,
            "entity_text": text,
            "logicType": "ABSENCE",
            "groupId": group,
            "groupType": "ALL",
            "isGroupLabel": label,
            "window": {"start": -7, "end": 0},
        }

    def test_should_collapse_a_restated_rule_and_leave_the_census_balanced(self, monkeypatch):
        svc = self._service(monkeypatch)
        eligibility = {
            "targetCohortName": "entry drug",
            "inclusionCriteria": [
                self._criterion(1, "glp1 inhibitor use", "g-inc"),
                self._criterion(2, "dpp4 inhibitor use", "g-inc"),
            ],
            "exclusionCriteria": [
                self._criterion(1, "use of glp1 agents", "g-exc"),
                self._criterion(2, "use of dpp4 agents", "g-exc"),
                self._criterion(3, "dpp4 recent", "g-single"),
            ],
        }
        circe = svc._build_seeded_target_circe(eligibility)

        rules = circe["InclusionRules"]
        records = circe[RESTATED_RULE_COLLAPSE_KEY]
        assert len(rules) == 1
        assert [(r["reason"], r["survivorRuleIndex"], r["ruleIndex"]) for r in records] == [
            (IDENTICAL_REASON, 0, 1),
            (IMPLIED_REASON, 0, 2),
        ]
        assert records[0]["criterionKeys"] == ["exclusion:1", "exclusion:2"]
        assert records[1]["criterionKeys"] == ["exclusion:3"]

        census = circe["_generationCensus"]
        assert census["total"] == 5
        assert census["mapped"] == 5
        assert census["total"] == (
            census["mapped"] + census["unmapped"] + census["demographicRules"] + census["skipped"]
        )
        # The frontend metadata is keyed by rule index, so it must describe the FINAL list:
        # one entry, for the survivor, carrying the survivor's own first criterion.
        assert circe["_ruleIndexMeta"] == {"0": {"queryUsed": "glp1 inhibitor use"}}
        # The collapsed criteria's concept sets stay, so the record's expression resolves.
        ids = {cs["id"] for cs in circe["ConceptSets"]}
        for record in records:
            assert _codeset_ids(record["expression"]) <= ids


def _codeset_ids(node: Any) -> set[Any]:
    if isinstance(node, dict):
        return {v for k, v in node.items() if k == "CodesetId"} | {
            i for v in node.values() for i in _codeset_ids(v)
        }
    if isinstance(node, list):
        return {i for v in node for i in _codeset_ids(v)}
    return set()
