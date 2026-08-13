"""A criterion that fails to map must leave a trace in the artifact.

`_build_seeded_target_circe` maps criteria in a thread pool and swallows any failure:

    except Exception as e:
        logging.warning("Failed to process criterion %s: %s", index, e)
        result = (index, None)

and every consumer below then skips on `if result is not None`. So the criterion is
gone from the cohort and the only record is a log line that nobody reads next week.
That is worse than an empty concept set, because an empty set at least occupies a
slot: a dropped exclusion silently widens the cohort past the protocol, and the stored
study looks complete.

The mapper itself already fails loudly (`_recommend_seeded_concept_set_rag_fallback`
raises "No concept mapping found for ..."), so what is missing is not detection — it
is that the detection never reaches the artifact.
"""
from __future__ import annotations

from typing import Any

import pytest

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


UNMAPPABLE = "qqzzxx nonexistent clinical term"


@pytest.fixture
def service_with_one_unmappable_criterion(monkeypatch):
    """A service whose mapper resolves everything except one criterion."""
    svc = TTEService.__new__(TTEService)

    def fake_recommend(seed_text: str, **kwargs: Any) -> dict[str, Any]:
        if seed_text.strip() == UNMAPPABLE:
            raise ValueError(f"No concept mapping found for '{seed_text}'")
        if seed_text.strip() == "empagliflozin":
            return _stub_concept_set("empagliflozin", 1594973, "Drug")
        return _stub_concept_set(seed_text.strip(), 201826)

    monkeypatch.setattr(svc, "_recommend_seeded_concept_set", fake_recommend)
    return svc


@pytest.fixture
def eligibility() -> dict[str, Any]:
    return {
        "targetCohortName": "empagliflozin",
        "inclusionCriteria": [
            {"id": "inc-1", "domain": "Condition", "sourceText": "Type 2 diabetes mellitus"},
        ],
        "exclusionCriteria": [
            {"id": "exc-1", "domain": "Condition", "sourceText": UNMAPPABLE},
        ],
    }


class TestUnmappedCriteriaAreRecorded:
    def test_should_record_the_criterion_when_mapping_raises(
        self, service_with_one_unmappable_criterion, eligibility
    ):
        circe = service_with_one_unmappable_criterion._build_seeded_target_circe(eligibility)
        unmapped = circe.get("_unmappedCriteria")
        assert unmapped, "a criterion was dropped and the artifact says nothing about it"
        assert len(unmapped) == 1
        assert unmapped[0]["criterionId"] == "exc-1"
        assert unmapped[0]["role"] == "exclusion"
        assert UNMAPPABLE in unmapped[0]["label"]
        assert "No concept mapping found" in unmapped[0]["reason"]

    def test_should_still_emit_the_criteria_that_did_map(
        self, service_with_one_unmappable_criterion, eligibility
    ):
        """One unmappable criterion must not cost the rest of the study."""
        circe = service_with_one_unmappable_criterion._build_seeded_target_circe(eligibility)
        names = [cs["name"] for cs in circe["ConceptSets"]]
        assert "empagliflozin" in names
        assert "Type 2 diabetes mellitus" in names

    def test_should_not_emit_a_concept_set_for_the_dropped_criterion(
        self, service_with_one_unmappable_criterion, eligibility
    ):
        """Recording the drop is the fix; inventing a placeholder set would not be."""
        circe = service_with_one_unmappable_criterion._build_seeded_target_circe(eligibility)
        assert all(UNMAPPABLE not in cs["name"] for cs in circe["ConceptSets"])
        assert all(
            (cs.get("expression") or {}).get("items") for cs in circe["ConceptSets"]
        ), "no concept set may ship with zero items"

    def test_should_report_an_empty_list_when_every_criterion_maps(self, monkeypatch, eligibility):
        """The key is always present, so its absence cannot be read as 'nothing failed'."""
        svc = TTEService.__new__(TTEService)
        monkeypatch.setattr(
            svc,
            "_recommend_seeded_concept_set",
            lambda seed_text, **kw: _stub_concept_set(seed_text.strip(), 201826),
        )
        eligibility["exclusionCriteria"][0]["sourceText"] = "Chronic heart failure"
        circe = svc._build_seeded_target_circe(eligibility)
        assert circe.get("_unmappedCriteria") == []
