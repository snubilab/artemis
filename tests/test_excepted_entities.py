"""RFC-016 step 1: ``excepted_entities`` and ``base_span`` replace the exception regex.

Every criterion is a real row of the 2026-10-12 prompt_f2 candidate store (copied into
``tests/fixtures/rfc016_store_rows.json``). The annotation is stubbed by writing what the
step would store for a given model answer; the mapper is a stub table: a phrase asked in
the exception branch (``resolving_entity_exception``) is looked up, and a phrase asked whole
is mapped as the table says, which is how a tail-dominated seed is simulated. Agent 2's
workflow, query expander and retriever raise on construction; nothing reaches an LLM,
ChromaDB, Postgres or Neo4j.

What is pinned:

* each accepted excepted entity is mapped by the same mapper and subtracted as
  ``isExcluded`` (EMPA-REG exclusion 30: T2DM out of "endocrine disorder");
* nothing is subtracted on the strength of the description or the seed text any more --
  only an annotation span that is a substring of ``protocolLine`` does it;
* an accepted ``base_span`` replaces the mapper seed, so a seed that carries the whole
  clause (CAROLINA exclusion 68, LEADER exclusions 39-41) maps its base, not its tail;
* the export-time entry-exclusion repair is triggered by the stated exceptions of the
  criterion behind a concept set, not by a rule name.
"""

from __future__ import annotations

import json
import zlib
from copy import deepcopy
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.services.criterion_annotation import (
    ANNOTATION_KEY,
    ANNOTATION_REJECTED_KEY,
    PLANNER_EXCEPTED_KEY,
    stated_exceptions,
    stated_exceptions_by_codeset,
    validate_annotation,
)
from src.services.entry_exclusion_repair import iter_repair_candidates
from src.services.tte_service import TTEService
from src.utils.circe_lint import CRITERION_CONCEPT_SET_REFS_KEY

FIXTURE = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "rfc016_store_rows.json").read_text()
)
EMPA_REG_30 = FIXTURE["empareg_exclusion_30"]
CAROLINA_68 = FIXTURE["carolina_exclusion_68"]
LEADER = {cid: FIXTURE[f"leader_exclusion_{cid}"] for cid in (38, 39, 40, 41)}

#: What the candidate file's EMPA-REG concept set 29 excludes for T2DM.
T2DM = [201826, 44793113]
#: Four of the candidate's own included members of that set.
ENDOCRINE = [23986, 192963, 201820, 4028942]
#: Stub concept ids for the cancer and insulin sets.
CANCER = [443392, 4280904]
NMSC = [4111017, 4112752]
NPH, LONG_ACTING, PREMIXED, OTHER_INSULIN = [1001], [1002], [1003], [1004, 1005]


def _annotated(row: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """``row`` carrying the annotation the step stores for ``payload``."""
    row = deepcopy(row)
    fields, rejected = validate_annotation(payload, row["protocolLine"])
    row[ANNOTATION_KEY] = {"promptVersion": "test", "model": "stub", **fields}
    if rejected:
        row[ANNOTATION_REJECTED_KEY] = rejected
    return row


def _exception(entities: list[tuple[str, str]], base: str | None) -> dict[str, Any]:
    return {
        "record_requirement": "forbidden",
        "conditional_span": None,
        "excepted_entities": [{"text": text, "span": span} for text, span in entities],
        "base_span": base,
    }


def _mapping(seed: str, ids: list[int], domain: str = "Condition") -> dict[str, Any]:
    return {
        "name": seed,
        "domain": domain,
        "expression": {
            "items": [
                {
                    "concept": {
                        "CONCEPT_ID": cid,
                        "CONCEPT_NAME": f"c{cid}",
                        "DOMAIN_ID": domain,
                        "VOCABULARY_ID": "SNOMED",
                        "CONCEPT_CLASS_ID": "Clinical Finding",
                        "CONCEPT_CODE": str(cid),
                    },
                    "isExcluded": False,
                    "includeDescendants": True,
                    "includeMapped": False,
                }
                for cid in ids
            ]
        },
        "mapping_metadata": None,
    }


class _Agent2IsStubbed:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise RuntimeError("Agent 2 is stubbed out in this test")


class _TableMapper(TTEService):
    """The real exception branch, over a stub table of phrase -> concept ids."""

    table: dict[str, list[int]] = {}
    asked: list[str] = []

    def _recommend_seeded_concept_set(self, seed_text, **kwargs):
        phrase = " ".join(seed_text.split())
        if kwargs.get("resolving_entity_exception"):
            self.asked.append(phrase)
            if phrase not in self.table:
                raise LookupError(f"no mapping for {phrase!r}")
            return _mapping(
                phrase, self.table[phrase], kwargs.get("expected_domain") or "Condition"
            )
        if kwargs.get("entity_exception") is not None:
            return super()._recommend_seeded_concept_set(seed_text, **kwargs)
        ids = self.table.get(phrase) or [zlib.crc32(phrase.encode()) % 10**8]
        return _mapping(phrase, ids, kwargs.get("expected_domain") or "Condition")

    def _recommend_seeded_concept_set_rag_fallback(self, seed_text, **kwargs):
        phrase = " ".join(seed_text.split())
        return _mapping(
            phrase, self.table.get(phrase) or [9], kwargs.get("expected_domain") or "Condition"
        )

    def _exact_ingredient_match_enabled(self) -> bool:
        return False


@pytest.fixture
def mapper(monkeypatch):
    monkeypatch.setattr("src.agents.agent2.workflow.Agent2Workflow", _Agent2IsStubbed)
    monkeypatch.setattr("src.agents.agent2.query_expander.QueryExpander", _Agent2IsStubbed)
    monkeypatch.setattr("src.agents.agent2.retriever.ConceptRetriever", _Agent2IsStubbed)
    monkeypatch.setenv("CRITERION_CACHE_ENABLED", "false")

    def build(table: dict[str, list[int]]) -> _TableMapper:
        svc = _TableMapper(store=MagicMock())
        svc.table = dict(table)
        svc.asked = []
        return svc

    return build


def _concept_set_of(circe: dict[str, Any], role: str, criterion_id: int) -> dict[str, Any]:
    codeset = circe[CRITERION_CONCEPT_SET_REFS_KEY][f"{role}:{criterion_id}"]
    return next(cs for cs in circe["ConceptSets"] if cs["id"] == codeset)


def _ids(concept_set: dict[str, Any], *, excluded: bool) -> list[int]:
    return sorted(
        i["concept"]["CONCEPT_ID"]
        for i in concept_set["expression"]["items"]
        if bool(i.get("isExcluded")) is excluded
    )


def _build(svc: TTEService, *, exclusion: list[dict[str, Any]]) -> dict[str, Any]:
    return svc._build_seeded_target_circe(
        {
            "targetCohortName": "Type 2 diabetes",
            "inclusionCriteria": [],
            "exclusionCriteria": deepcopy(exclusion),
        }
    )


class TestEmpaRegExclusion30:
    TABLE = {
        "endocrine disorder": ENDOCRINE,
        "Endocrine disorder": ENDOCRINE,
        "type 2 diabetes": T2DM,
    }

    def test_should_exclude_what_the_mapper_returns_for_the_excepted_entity(self, mapper):
        svc = mapper(self.TABLE)
        row = _annotated(
            EMPA_REG_30, _exception([("type 2 diabetes", "type 2 diabetes")], "endocrine disorder")
        )
        concept_set = _concept_set_of(_build(svc, exclusion=[row]), "exclusion", 30)
        assert _ids(concept_set, excluded=True) == sorted(T2DM)
        assert _ids(concept_set, excluded=False) == sorted(ENDOCRINE)
        assert svc.asked == ["endocrine disorder", "type 2 diabetes"]

    def test_should_keep_the_seed_and_record_why_when_no_base_span_is_given(self, mapper):
        svc = mapper(self.TABLE)
        row = _annotated(EMPA_REG_30, _exception([("type 2 diabetes", "type 2 diabetes")], None))
        assert [r["field"] for r in row[ANNOTATION_REJECTED_KEY]] == ["base_span"]
        concept_set = _concept_set_of(_build(svc, exclusion=[row]), "exclusion", 30)
        assert svc.asked == ["Endocrine disorder", "type 2 diabetes"]
        assert _ids(concept_set, excluded=True) == sorted(T2DM)

    def test_should_subtract_nothing_when_the_row_carries_no_annotation(self, mapper):
        """Its description says "(excluding T2DM)"; that text decides nothing any more."""
        svc = mapper(self.TABLE)
        concept_set = _concept_set_of(_build(svc, exclusion=[EMPA_REG_30]), "exclusion", 30)
        assert svc.asked == []
        assert _ids(concept_set, excluded=True) == []

    def test_should_subtract_nothing_when_the_excepted_span_is_not_in_the_line(self, mapper):
        svc = mapper(self.TABLE)
        row = _annotated(EMPA_REG_30, _exception([("T2DM", "T2DM")], "endocrine disorder"))
        assert {r["field"] for r in row[ANNOTATION_REJECTED_KEY]} == {
            "excepted_entities",
            "base_span",
        }
        concept_set = _concept_set_of(_build(svc, exclusion=[row]), "exclusion", 30)
        assert svc.asked == []
        assert _ids(concept_set, excluded=True) == []


class TestASeedThatCarriesTheWholeClause:
    """The old regex split these seeds into base and exception; ``base_span`` does it now."""

    CAROLINA_TABLE = {
        "cancer": CANCER,
        "non-melanoma skin cancer": NMSC,
        # Mapped whole, the clause is dominated by its tail (AGENTS.md, CAROLINA codeset 45).
        "cancer other than non-melanoma skin cancer within last 3 years": NMSC,
    }
    LEADER_TABLE = {
        "insulin": NPH + LONG_ACTING + PREMIXED + OTHER_INSULIN,
        "human NPH insulin": NPH,
        "long-acting insulin analogue": LONG_ACTING,
        "premixed insulin": PREMIXED,
        "insulin other than human NPH insulin": NPH,
        "insulin other than long-acting insulin analogue": LONG_ACTING,
        "insulin other than premixed insulin": PREMIXED,
    }

    def test_should_map_the_base_span_and_subtract_the_exception_for_carolina_68(self, mapper):
        svc = mapper(self.CAROLINA_TABLE)
        row = _annotated(
            CAROLINA_68,
            _exception([("non-melanoma skin cancer", "non-melanoma skin cancer")], "cancer"),
        )
        assert ANNOTATION_REJECTED_KEY not in row
        concept_set = _concept_set_of(_build(svc, exclusion=[row]), "exclusion", 68)
        assert svc.asked == ["cancer", "non-melanoma skin cancer"]
        assert _ids(concept_set, excluded=False) == sorted(CANCER)
        assert _ids(concept_set, excluded=True) == sorted(NMSC)

    def test_should_map_carolina_68_whole_when_it_carries_no_annotation(self, mapper):
        svc = mapper(self.CAROLINA_TABLE)
        concept_set = _concept_set_of(_build(svc, exclusion=[CAROLINA_68]), "exclusion", 68)
        assert svc.asked == []
        assert _ids(concept_set, excluded=True) == []

    @pytest.mark.parametrize("criterion_id", [39, 40, 41])
    def test_should_subtract_every_insulin_the_leader_line_excepts(self, mapper, criterion_id):
        """The line excepts three insulins from one set. Read off the seed, each member
        excepted only its own one, and the three absences together forbade all insulin."""
        svc = mapper(self.LEADER_TABLE)
        row = _annotated(
            LEADER[criterion_id],
            _exception(
                [
                    ("human NPH insulin", "human NPH insulin"),
                    ("long-acting insulin analogue", "long-acting insulin analogue"),
                    ("premixed insulin", "premixed insulin"),
                ],
                "insulin",
            ),
        )
        assert ANNOTATION_REJECTED_KEY not in row
        concept_set = _concept_set_of(_build(svc, exclusion=[row]), "exclusion", criterion_id)
        assert svc.asked == [
            "insulin",
            "human NPH insulin",
            "long-acting insulin analogue",
            "premixed insulin",
        ]
        assert _ids(concept_set, excluded=True) == sorted(NPH + LONG_ACTING + PREMIXED)
        assert _ids(concept_set, excluded=False) == sorted(OTHER_INSULIN)


class TestWhoseExceptionsCount:
    def test_should_prefer_the_planners_exceptions_when_both_are_present(self):
        row = _annotated(EMPA_REG_30, _exception([("diabetes", "diabetes")], "endocrine disorder"))
        row[PLANNER_EXCEPTED_KEY] = [{"text": "type 2 diabetes", "span": "type 2 diabetes"}]
        assert [e["text"] for e in stated_exceptions(row)] == ["type 2 diabetes"]

    def test_should_fall_back_to_the_annotation_when_the_planner_left_none(self):
        row = _annotated(
            EMPA_REG_30, _exception([("type 2 diabetes", "type 2 diabetes")], "endocrine disorder")
        )
        row[PLANNER_EXCEPTED_KEY] = []
        assert [e["text"] for e in stated_exceptions(row)] == ["type 2 diabetes"]

    def test_should_drop_a_stored_exception_whose_span_is_not_in_the_line(self):
        row = dict(deepcopy(EMPA_REG_30), **{PLANNER_EXCEPTED_KEY: [{"text": "x", "span": "T2DM"}]})
        assert stated_exceptions(row) == []


class TestTheExportRepairReadsTheField:
    """`entry_exclusion_repair` used to find its exception in the rule's NAME."""

    @staticmethod
    def _base(rule_name: str) -> dict[str, Any]:
        return {
            "ConceptSets": [
                {"id": 2, "name": "Type 2 Diabetes Mellitus", "expression": {"items": []}},
                {"id": 29, "name": rule_name, "expression": {"items": []}},
            ],
            "PrimaryCriteria": {"CriteriaList": [{"ConditionOccurrence": {"CodesetId": 2}}]},
            "InclusionRules": [
                {
                    "name": rule_name,
                    "expression": {
                        "Type": "ALL",
                        "CriteriaList": [],
                        "Groups": [
                            {
                                "Type": "ALL",
                                "Groups": [],
                                "CriteriaList": [
                                    {
                                        "Criteria": {"ConditionOccurrence": {"CodesetId": 29}},
                                        "StartWindow": {
                                            "Start": {"Days": 9999, "Coeff": -1},
                                            "End": {"Days": 0, "Coeff": 1},
                                        },
                                        "Occurrence": {"Type": 0, "Count": 0},
                                    }
                                ],
                            }
                        ],
                    },
                }
            ],
        }

    def test_should_offer_no_candidate_when_only_the_rule_name_states_an_exception(self):
        base = self._base("Endocrine disorder (excluding T2DM)")
        assert list(iter_repair_candidates(base, {})) == []

    def test_should_offer_the_candidate_when_its_criterion_stated_the_exception(self):
        base = self._base("Endocrine disorder")
        [candidate] = iter_repair_candidates(base, {29: ["type 2 diabetes"]})
        assert (candidate.codeset_id, list(candidate.excepted)) == (29, ["type 2 diabetes"])

    def test_should_key_the_stated_exceptions_by_the_rows_concept_set(self):
        row = _annotated(
            EMPA_REG_30, _exception([("type 2 diabetes", "type 2 diabetes")], "endocrine disorder")
        )
        eligibility = {"inclusionCriteria": [], "exclusionCriteria": [row, EMPA_REG_30]}
        assert stated_exceptions_by_codeset(eligibility) == {29: ["type 2 diabetes"]}

    def test_should_hand_the_map_to_the_entry_repair_through_the_export_chain(self, monkeypatch):
        svc = TTEService.__new__(TTEService)
        seen: list[Any] = []
        monkeypatch.setattr(
            svc, "_repair_entry_excluded_by_own_rule", lambda built, stated: seen.append(stated)
        )
        try:
            svc._apply_export_repairs({"InclusionRules": []}, stated_exceptions={29: ["t2dm"]})
        except Exception:
            pass  # later repairs in the chain are not this test's concern
        assert seen and seen[0] == {29: ["t2dm"]}
