"""RFC-016 step 2: three text rules removed, each pinned on the real input it used to act on.

* **A2** -- Agent 1's post-parse "Pattern E" repair merged flat inclusion rules whose
  entity text hit one of four keyword clusters into an ANY group. Removed: grouping is
  Agent 1's own (``sub_criteria`` / ``group_type``) and the relation the line states.
  Input: LEADER's Agent 1 IR, target arm (``tests/fixtures/rfc016_leader_ir_target.json``).
* **A10** -- ``criterion_seed`` cut temporal phrases out of a mapper seed with a regex
  table. Removed: the seed is the criterion's own ``entity_text`` (or the annotation's
  verified ``base_span``); a criterion whose ``entity_text`` is empty is refused as
  ``missing-entity-text`` and recorded in ``_missingEntityCriteria`` instead of being
  seeded on its (stripped) description.
* **A14** -- Agent 2 split a Drug query on " or " and expanded each part via ATC. Removed:
  the query is expanded whole; alternatives are split upstream by Agent 1 / the planner.

Rows from ``tests/fixtures/rfc016_relation_timing_rows.json`` (2026-10-12 prompt_f2
candidate store). No LLM, no database: Agent 1's LLM handle, the mapper, the DB pool and
the ATC expander are stubs.
"""

from __future__ import annotations

import json
import zlib
from copy import deepcopy
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.services.tte_service import TTEService
from src.utils.criterion_seed import MISSING_ENTITY_CRITERIA_KEY, criterion_mapper_seed

FIXTURES = Path(__file__).resolve().parent / "fixtures"
ROWS = json.loads((FIXTURES / "rfc016_relation_timing_rows.json").read_text())
LEADER_IR = json.loads((FIXTURES / "rfc016_leader_ir_target.json").read_text())["target"]

PLATO_ACS = ROWS["plato_inclusion_12"][0]
CARMELINA_CABG = ROWS["carmelina_exclusion_27"][0]
CAROLINA_CANCER = ROWS["carolina_exclusion_68"][0]
CARMELINA_BACKGROUND = ROWS["carmelina_inclusion_3"][0]


# --------------------------------------------------------------------------- #
# A2
# --------------------------------------------------------------------------- #


class TestPatternEIsGone:
    @staticmethod
    def _cohort():
        from src.agents.agent1.parser import LogicDecomposer

        with patch("src.agents.agent1.parser.get_llm", return_value=MagicMock()):
            agent1 = LogicDecomposer(model_name="vllm/google/gemma-4-E4B-it")
        return agent1._build_cohort_definition(deepcopy(LEADER_IR))

    def test_should_not_merge_flat_rules_into_a_keyword_cluster_group(self):
        names = [rule.name for rule in self._cohort().inclusion_rules]
        assert "Cv Prior (OR group)" not in names
        assert "Cv Risk (OR group)" not in names

    def test_should_keep_every_flat_rule_the_model_emitted_at_the_top_level(self):
        flat = [r["name"] for r in LEADER_IR["inclusion_rules"] if not r.get("sub_criteria")]
        top = [rule.name for rule in self._cohort().inclusion_rules]
        for name in ("Chronic renal failure", "Prior stroke or TIA", "Ankle-brachial index < 0.9"):
            assert name in flat
            assert name in top


# --------------------------------------------------------------------------- #
# A10
# --------------------------------------------------------------------------- #


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
def service(monkeypatch):
    monkeypatch.setattr("src.agents.agent2.workflow.Agent2Workflow", _Agent2IsStubbed)
    monkeypatch.setattr("src.agents.agent2.retriever.ConceptRetriever", _Agent2IsStubbed)
    svc = TTEService.__new__(TTEService)
    asked: list[str] = []

    def fake_recommend(seed_text: str, **kwargs: Any) -> dict[str, Any]:
        asked.append(seed_text)
        return _stub_concept_set(seed_text.strip(), kwargs.get("expected_domain") or "Condition")

    monkeypatch.setattr(svc, "_recommend_seeded_concept_set", fake_recommend)
    svc.asked = asked
    return svc


def _build(service, *, inclusion=(), exclusion=()) -> dict[str, Any]:
    return service._build_seeded_target_circe(
        {
            "targetCohortName": "ticagrelor",
            "inclusionCriteria": deepcopy(list(inclusion)),
            "exclusionCriteria": deepcopy(list(exclusion)),
        }
    )


class TestAnEmptyEntityIsSeededOnTheDescriptionAsWritten:
    """A10 removed the stripping; the description stays the seed, exactly as written, and
    the row says so (``seededOnDescription`` / ``mapperSeed``). CARMELINA is in the default
    delivery; PLATO's line is the one the stripper cut into "with onset , ischemic ..."."""

    @pytest.mark.parametrize(
        "row,role", [(PLATO_ACS, "inclusion"), (CARMELINA_CABG, "exclusion")], ids=["plato", "carmelina"]
    )
    def test_should_map_on_the_description_as_written_and_mark_the_row(self, service, row, role):
        assert row["sourceText"] == "" and row["window"]
        eligibility = {
            "targetCohortName": "ticagrelor",
            "inclusionCriteria": [deepcopy(row)] if role == "inclusion" else [],
            "exclusionCriteria": [deepcopy(row)] if role == "exclusion" else [],
        }
        circe = service._build_seeded_target_circe(eligibility)
        written = " ".join(row["description"].split())

        assert len(circe["InclusionRules"]) == 1
        assert circe["_unmappedCriteria"] == []
        assert written in service.asked
        [record] = circe[MISSING_ENTITY_CRITERIA_KEY]
        assert (record["criterionId"], record["outcome"], record["seed"]) == (
            str(row["id"]), "mapped", written
        )
        [stored] = eligibility[f"{role}Criteria"]
        assert stored["seededOnDescription"] is True
        assert stored["mapperSeed"] == written

    def test_should_not_mark_a_row_that_carries_its_entity(self, service):
        eligibility = {
            "targetCohortName": "linagliptin",
            "inclusionCriteria": [],
            "exclusionCriteria": [deepcopy(CAROLINA_CANCER)],
        }
        service._build_seeded_target_circe(eligibility)
        assert "seededOnDescription" not in eligibility["exclusionCriteria"][0]

    def test_should_seed_on_the_entity_text_as_extracted_when_it_carries_a_time_phrase(self):
        """The seed is no longer cut: CAROLINA exclusion 68's entity text is the seed."""
        assert criterion_mapper_seed(CAROLINA_CANCER) == (
            "cancer other than non-melanoma skin cancer within last 3 years"
        )

    def test_should_seed_on_the_description_as_written_when_entity_text_is_empty(self):
        assert criterion_mapper_seed(PLATO_ACS) == " ".join(PLATO_ACS["description"].split())


# --------------------------------------------------------------------------- #
# A14
# --------------------------------------------------------------------------- #


class TestADrugQueryIsExpandedWhole:
    def test_should_ask_the_atc_expander_once_with_the_whole_query(self, monkeypatch):
        from src.agents.agent2 import workflow as workflow_mod

        query = CARMELINA_BACKGROUND["description"]
        assert " or " in query
        asked: list[str] = []

        def fake_expand(text: str, conn: Any, schema: str) -> tuple[str, list[int]]:
            asked.append(text)
            return "antidiabetic", [1, 2]

        pool = MagicMock()
        pool.getconn.return_value = MagicMock()
        monkeypatch.setattr(workflow_mod, "_get_db_pool", lambda: pool)
        monkeypatch.setattr(workflow_mod, "expand_drug_class_via_vocab", fake_expand)
        monkeypatch.setattr(
            workflow_mod.logician, "roll_up_to_rxnorm_ingredients", lambda ids: list(ids)
        )
        flow = workflow_mod.Agent2Workflow.__new__(workflow_mod.Agent2Workflow)

        result = flow.process_with_details(query, domain_hint="Drug")

        assert len(asked) == 1, asked
        assert result.route_path == "atc"
