"""A seed that names no clinical entity refuses under a code the gate may permit.

`PERMITTED_REFUSAL_CODES` in `scripts/verify_circe_delivery.py` permits exactly one
code, `unmappable-placeholder`, and the axis it permits on is not "was the refusal
deliberate" -- every code is deliberate -- it is "is this loss IRREDUCIBLE given a
correct pipeline". `no-concept-mapping` straddles that line, and the gate cannot split
it: all it sees is the seed's English, and two seeds sharing a lexical stem can sit on
opposite sides of the line:

    Contraindication                    irreducible -- names no substance
    Contraindication to clopidogrel     REDUCIBLE   -- names a real one, and a better
                                                       mapper finds it

So the split is made at the raise site, which is what this file pins. The six rows of
`REAL_SEEDS` below are transcribed from the delivered 2026-09-08 batch
(`tmp/tte_cold6_20260908/studies.json`, criterion `sourceText` values) rather than
invented, per `docs/mistakes.md`: a classifier that has only ever met synthetic strings
has not been tested.

The guard list is the half that matters. A false `unmappable-placeholder` walks a real
loss through the delivery gate; a false `no-concept-mapping` merely fails a delivery a
human then reads. Every entry in `REDUCIBLE_SEEDS_FROM_THE_BATCH` is a real seed from
that same batch whose shape is close enough to a placeholder to be mistaken for one --
`Platelet count` is the batch's only "... Count", `Multiple endocrine neoplasia type 2`
and `MELD score >= 30` both end in a bare digit, and four of the five `Contraindication`
seeds carry a substance.

The classifier is reached through the module rather than imported by name so that this
file still COLLECTS against a tree without it: at `0e410be` the raise-site rows below
fail with `no-concept-mapping != unmappable-placeholder`, which is the evidence that the
producer half was missing, instead of the whole module erroring on an import.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import src.services.tte_service as tte_service
from src.services.tte_service import TTEService
from src.utils.criterion_refusal import (
    REFUSAL_NO_CONCEPT_MAPPING,
    REFUSAL_UNMAPPABLE_PLACEHOLDER,
    CriterionRefused,
)

#: The table the split was specified against: seed -> the code its refusal must carry.
#: Rows 4 and 5 are the same lexical stem with opposite verdicts.
REAL_SEEDS = [
    ("Risk factor 1", REFUSAL_UNMAPPABLE_PLACEHOLDER),
    ("Table II criteria", REFUSAL_UNMAPPABLE_PLACEHOLDER),
    ("Preexisting Conditions Count", REFUSAL_UNMAPPABLE_PLACEHOLDER),
    ("Contraindication", REFUSAL_UNMAPPABLE_PLACEHOLDER),
    ("Contraindication to clopidogrel", REFUSAL_NO_CONCEPT_MAPPING),
    ("Aspirin and thienopyridine combination", REFUSAL_NO_CONCEPT_MAPPING),
]

#: Real seeds from the same batch, each shaped like a placeholder and each naming
#: something a vocabulary holds. None of these may be permitted.
REDUCIBLE_SEEDS_FROM_THE_BATCH = [
    "Platelet count",
    "Contraindication against clopidogrel use",
    "Contraindication to clopidogrel or other reason",
    "Contraindications to background therapy",
    "Cardiovascular Risk Factors",
    "Specified cardiovascular risk factor",
    "Age ≥50",
    "MELD score >= 30",
    "Multiple endocrine neoplasia type 2",
    "Chronic Kidney Disease Stage 4 or 5",
    "Chronic heart failure NYHA class IV",
    "DPP-IV inhibitors",
    "Troponin I",
    "Investigational drug use",
]

#: Entities outside this batch that the rules must not swallow. Each names the rule it
#: would trip if that rule were written one step wider: a roman numeral read as an
#: ordinal ("Factor V Leiden"), a cell count read as a tally ("Absolute neutrophil
#: count"), a pointer word used anatomically ("Cesarean section", "Appendix").
REDUCIBLE_SEEDS_OUTSIDE_THE_BATCH = [
    "Factor V Leiden",
    "Factor VIII deficiency",
    "Absolute neutrophil count",
    "White blood cell count",
    "CD4 count",
    "Cesarean section",
    "Appendix",
    "Vitamin supplement",
]

#: Placeholder shapes beyond the four in `REAL_SEEDS`, one per rule.
PLACEHOLDER_SHAPES = [
    "Risk factor 2",
    "Exclusion criterion 3",
    "Table 3",
    "Appendix B criteria",
    "Supplementary Table 1",
    "Comorbidity count",
    "Contraindications",
    "  contraindication.  ",
]


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> TTEService:
    monkeypatch.setenv("CRITERION_CACHE_ENABLED", "false")
    return TTEService(store=MagicMock())


def _recommender_finding_nothing(service: TTEService, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every tier ran and matched nothing, and the intent router had no complaint.

    `fallback_reason=None` is what selects the branch under test: a reason present means
    the router refused to parse the seed at all, which is `intent-unparsed` and is a
    different verdict on a different axis.
    """
    recommender = MagicMock()
    recommender.recommend.return_value = SimpleNamespace(
        include_recommendations=[], fallback_reason=None
    )
    monkeypatch.setattr(service, "_get_seeded_concept_set_recommender", lambda: recommender)


@pytest.mark.parametrize(("seed", "expected_code"), REAL_SEEDS)
def test_should_carry_the_irreducible_code_when_the_seed_names_no_entity(
    service, monkeypatch, seed, expected_code
):
    """The six real seeds the split was specified against, at the raise site itself."""
    _recommender_finding_nothing(service, monkeypatch)

    with pytest.raises(CriterionRefused) as caught:
        service._recommend_seeded_concept_set_rag_fallback(seed, expected_domain="Condition")
    assert caught.value.code == expected_code


def test_should_propagate_the_new_code_through_the_agent2_wrapper(service, monkeypatch):
    """`_recommend_seeded_concept_set` re-wraps the fallback refusal by `.code`.

    The wrapper builds a fresh `CriterionRefused` to name the Agent 2 stage, so a code
    it failed to copy would be lost between the raise site and the artifact.
    """
    from src.agents.agent2 import workflow as agent2_workflow

    monkeypatch.setattr(
        agent2_workflow.Agent2Workflow,
        "process_with_details",
        lambda self, *a, **k: SimpleNamespace(
            concept_ids=[], overbroad_concept_ids=[], route_path="rag_only"
        ),
    )
    _recommender_finding_nothing(service, monkeypatch)

    with pytest.raises(CriterionRefused) as caught:
        service._recommend_seeded_concept_set("Risk factor 1", expected_domain="Condition")
    assert caught.value.code == REFUSAL_UNMAPPABLE_PLACEHOLDER
    assert "Agent 2 returned no concepts" in str(caught.value)


@pytest.mark.parametrize("seed", PLACEHOLDER_SHAPES)
def test_should_classify_placeholder_shapes_as_naming_no_entity(seed):
    assert tte_service._seed_is_unmappable_placeholder(seed) is True


@pytest.mark.parametrize(
    "seed", REDUCIBLE_SEEDS_FROM_THE_BATCH + REDUCIBLE_SEEDS_OUTSIDE_THE_BATCH
)
def test_should_refuse_to_permit_a_seed_that_names_something(seed):
    """The bias is one-directional: when uncertain, do not permit."""
    assert tte_service._seed_is_unmappable_placeholder(seed) is False


def test_should_not_permit_an_empty_seed():
    """An empty seed is `empty-seed` upstream; here it must not read as a placeholder."""
    assert tte_service._seed_is_unmappable_placeholder("") is False
    assert tte_service._seed_is_unmappable_placeholder("   ") is False
