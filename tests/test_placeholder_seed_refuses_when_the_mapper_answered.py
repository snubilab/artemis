"""A seed that names no entity is refused even when the mapper answered it.

`_seed_is_unmappable_placeholder` decides whether a seed names a clinical entity at
all, and until now it was consulted at two sites only -- the RAG fallback that found
NOTHING, and `_refuse_domain_contradiction_for_seed`, where the answer's domain betrayed
that there was nothing to find. Both are refusal paths. A placeholder seed whose mapper
answered plausibly, in the criterion's own domain, took neither and was emitted.

Measured on `output/site_gap/2026-09-10/store_grounded/studies.json` and its delivery
`output/site_gap/2026-09-10/deliver_grounded`: nine criteria across six trials carry a
seed the classifier calls a placeholder. ONE (ARISTOTLE exclusion 26) already refuses,
through the domain-contradiction path. The other EIGHT emitted rules that filter
patients:

    CAROLINA incl 6/7    "CV risk factor 1" / "... 2"      -> InclusionRule "CV risk
                         factor 1 + CV risk factor 2", ANY over two Observation codesets
                         at >= 1 occurrence. The concepts are risk-ASSESSMENT flags
                         ("At increased risk of thrombophlebitis", "Cardiovascular
                         disease 10Y risk"), not the smoking/hypertension/dyslipidemia
                         the protocol line enumerates. A required inclusion rule over
                         codes almost no CDM records is a cohort that matches nobody.
    CAROLINA incl 25-28  "CV risk factor A".."D"            -> the same shape a second
                         time, and the same two 8-concept sets: A repeats 6's set, B/C/D
                         repeat 7's. Four protocol branches, two answers.
    CAROLINA excl 39     "Investigational drug"             -> ABSENCE over 25 Procedure
                         concepts including "Drug therapy", "Routine administration of
                         medication" and "Administration of sulfonylurea" -- in a trial
                         whose active comparator IS a sulfonylurea. The exclusion removes
                         the patients the protocol enrols.
    CAROLINA excl 71     "Investigational Medicinal Product" -> ABSENCE over 4 Procedure
                         concepts. Three name clinical-trial assessment and are arguably
                         near the protocol's intent; the fourth is "Dispensing of
                         pharmaceutical/biologic product" WITH DESCENDANTS, which in an
                         absence rule excludes anyone who was ever dispensed a medicine.

So the third consult site is added where the criterion and the mapper's verdict are both
in hand, and it is placed AFTER `_refuse_domain_contradiction_for_seed` on purpose: a
placeholder whose answer also contradicts the domain must keep the richer message, which
is what ARISTOTLE exclusion 26 relies on and what `test_should_keep_the_contradiction_
message_when_the_answer_also_contradicts_the_domain` pins.

The rows below carry the real store fields (`sourceText` empty where extraction left it
empty, the declared domain, the real window) and the real concept ids the delivered
artifact holds, per `docs/mistakes.md`: a guard that has only met synthetic strings has
not been tested against the case that motivated it.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.services.tte_service import TTEService
from src.utils.criterion_refusal import (
    REFUSAL_MISSING_ENTITY_TEXT,
    REFUSAL_UNMAPPABLE_PLACEHOLDER,
    CriterionRefused,
)

#: `carolina_treatment.circe.json` codeset 4, verbatim. The answer "CV risk factor 1"
#: actually received: eight Observation risk-assessment flags, every one with
#: `includeDescendants`.
CV_RISK_FACTOR_1_ANSWER = [
    (601865, "High risk of cardiovascular disease"),
    (602868, "At increased risk of embolism"),
    (1077359, "At increased risk of thrombophlebitis"),
    (1989206, "Cardiovascular disease 10Y risk"),
    (3050686, "Risk factors"),
    (3663227, "At increased risk of stroke"),
    (4024219, "At increased risk of deep vein thrombosis"),
    (4059347, "At increased risk of heart disease"),
]

#: `carolina_treatment.circe.json` codeset 93, verbatim. The one of the eight whose
#: answer comes closest to the protocol's intent -- three of its four concepts name
#: clinical-trial assessment -- and which is refused anyway, because the fourth is
#: "Dispensing of pharmaceutical/biologic product" with descendants inside an ABSENCE
#: rule. A partly-plausible set is still a set the protocol never asked for.
INVESTIGATIONAL_MEDICINAL_PRODUCT_ANSWER = [
    (4206702, "Dispensing of pharmaceutical/biologic product"),
    (40484635, "Initial assessment for clinical trial"),
    (42873080, "Assessment of eligibility for clinical trial"),
    (44782116, "ADM EXP DRUGS,CLINICAL TRIAL (Deprecated)"),
]

#: The eight rows that emit today, transcribed from
#: `output/site_gap/2026-09-10/store_grounded/studies.json`. `sourceText` is the store
#: column carrying the IR's `entity_text`; the six CAROLINA inclusion rows have it empty,
#: which is why the `missing-entity-text` interaction below is load-bearing rather than
#: hypothetical.
EMITTING_PLACEHOLDER_CRITERIA: list[tuple[dict[str, Any], str, str]] = [
    (
        {
            "id": 6,
            "description": "CV risk factor 1",
            "sourceText": "",
            "domain": "Observation",
            "window": {"start": -9999, "end": 0},
        },
        "CV risk factor 1",
        "Observation",
    ),
    (
        {
            "id": 7,
            "description": "CV risk factor 2",
            "sourceText": "",
            "domain": "Observation",
            "window": {"start": -9999, "end": 0},
        },
        "CV risk factor 2",
        "Observation",
    ),
    (
        {
            "id": 25,
            "description": "CV risk factor A",
            "sourceText": "",
            "domain": "Observation",
            "window": {"start": -9999, "end": 0},
        },
        "CV risk factor A",
        "Observation",
    ),
    (
        {
            "id": 26,
            "description": "CV risk factor B",
            "sourceText": "",
            "domain": "Observation",
            "window": {"start": -9999, "end": 0},
        },
        "CV risk factor B",
        "Observation",
    ),
    (
        {
            "id": 27,
            "description": "CV risk factor C",
            "sourceText": "",
            "domain": "Observation",
            "window": {"start": -9999, "end": 0},
        },
        "CV risk factor C",
        "Observation",
    ),
    (
        {
            "id": 28,
            "description": "CV risk factor D",
            "sourceText": "",
            "domain": "Observation",
            "window": {"start": -9999, "end": 0},
        },
        "CV risk factor D",
        "Observation",
    ),
    (
        {
            "id": 39,
            "description": "Participation in another trial",
            "sourceText": "Investigational drug",
            "domain": "Procedure",
            "window": {"start": -60, "end": 0},
        },
        "Investigational drug",
        "Procedure",
    ),
    (
        {
            "id": 71,
            "description": "Participation in another trial with IMP",
            "sourceText": "Investigational Medicinal Product",
            "domain": "Procedure",
            "window": {"start": -60, "end": 0},
        },
        "Investigational Medicinal Product",
        "Procedure",
    ),
]


def _mapping(concepts: list[tuple[int, str]], domain: str, name: str) -> dict[str, Any]:
    """A mapper answer in the criterion's OWN domain, so nothing contradicts."""
    return {
        "name": name,
        "domain": domain,
        "expression": {
            "items": [
                {
                    "concept": {
                        "CONCEPT_ID": cid,
                        "CONCEPT_NAME": cname,
                        "CONCEPT_CODE": str(cid),
                        "DOMAIN_ID": domain,
                        "VOCABULARY_ID": "SNOMED",
                        "CONCEPT_CLASS_ID": "Context-dependent",
                    },
                    "includeDescendants": True,
                    "isExcluded": False,
                }
                for cid, cname in concepts
            ]
        },
        "mapping_metadata": None,
    }


def _service(monkeypatch, mapping: dict[str, Any]) -> TTEService:
    svc = TTEService.__new__(TTEService)
    monkeypatch.setattr(svc, "_recommend_seeded_concept_set", lambda seed, **kwargs: mapping)
    return svc


class TestAPlaceholderSeedIsRefusedThoughTheMapperAnswered:
    @pytest.mark.parametrize(
        ("criterion", "seed", "domain"),
        EMITTING_PLACEHOLDER_CRITERIA,
        ids=[c["description"] for c, _, _ in EMITTING_PLACEHOLDER_CRITERIA],
    )
    def test_should_refuse_as_irreducible_when_the_seed_names_no_entity(
        self, monkeypatch, criterion, seed, domain
    ):
        """The eight rows that emitted on 2026-09-10, at the site that emitted them."""
        answer = (
            INVESTIGATIONAL_MEDICINAL_PRODUCT_ANSWER
            if seed == "Investigational Medicinal Product"
            else CV_RISK_FACTOR_1_ANSWER
        )
        service = _service(monkeypatch, _mapping(answer, domain, seed))

        with pytest.raises(CriterionRefused) as excinfo:
            service._build_seeded_eligibility_rule(
                criterion=criterion, codeset_id=4, exclusion=criterion["id"] in (39, 71)
            )

        refused = excinfo.value
        assert refused.code == REFUSAL_UNMAPPABLE_PLACEHOLDER
        # The record must say the mapper ANSWERED, or a reader cannot tell this row from
        # the RAG-fallback refusal that shares its code and found nothing at all.
        assert seed in str(refused)
        assert str(len(answer)) in str(refused)

    def test_should_not_let_the_missing_entity_recode_steal_the_permit(self, monkeypatch):
        """`sourceText` is empty on all six CAROLINA rows, and the permit must survive it.

        `_recode_refusal_for_missing_entity` re-codes a seed-caused refusal to
        `missing-entity-text`, which the delivery gate does NOT permit. It re-codes only
        `SEED_CAUSED_REFUSAL_CODES`, an allow-list that deliberately excludes
        `unmappable-placeholder` -- the same exemption ARISTOTLE exclusion 26 already
        depends on. Pinned here because these rows are the first to reach it from the
        new site.
        """
        criterion, seed, domain = EMITTING_PLACEHOLDER_CRITERIA[0]
        service = _service(monkeypatch, _mapping(CV_RISK_FACTOR_1_ANSWER, domain, seed))

        with pytest.raises(CriterionRefused) as excinfo:
            service._build_seeded_eligibility_rule(
                criterion=criterion, codeset_id=4, exclusion=False
            )

        assert excinfo.value.code != REFUSAL_MISSING_ENTITY_TEXT
        assert excinfo.value.code == REFUSAL_UNMAPPABLE_PLACEHOLDER

    def test_should_keep_the_contradiction_message_when_the_answer_also_contradicts(
        self, monkeypatch
    ):
        """ARISTOTLE exclusion 26's record must not lose its mechanism to the new site.

        It already refuses with `unmappable-placeholder`, through
        `_refuse_domain_contradiction_for_seed`, and that path carries the message and
        `detail` verbatim so a reader still sees WHICH domains came back. Refusing
        before the domain check would have replaced that with a generic sentence.
        """
        criterion = {
            "id": 26,
            "description": "Investigational drug use",
            "sourceText": "",
            "domain": "Drug",
            "window": {"start": -30, "end": 0},
        }
        service = _service(
            monkeypatch,
            _mapping([(4216752, "Drug therapy")], "Procedure", "Investigational drug use"),
        )

        with pytest.raises(CriterionRefused) as excinfo:
            service._build_seeded_eligibility_rule(
                criterion=criterion, codeset_id=41, exclusion=True
            )

        refused = excinfo.value
        assert refused.code == REFUSAL_UNMAPPABLE_PLACEHOLDER
        assert "criterion domain contradiction: DrugExposure reads Drug" in str(refused)
        assert refused.detail == "DrugExposure vs Procedure"


class TestASeedThatNamesSomethingStillBuilds:
    """The control that makes the refusal mean something.

    The bias is one-directional: a false permit walks a real mapping loss through the
    delivery gate, so a seed the classifier does not claim must build exactly as before
    even when its shape is close to a placeholder's.
    """

    @pytest.mark.parametrize(
        "seed",
        [
            "Type 2 diabetes mellitus",
            # The group label the six CAROLINA rows hang under. Every component is a
            # placeholder and the classifier still declines the join -- pinned because
            # the new site would refuse a whole group's label if it did not.
            "CV risk factor A + CV risk factor B + CV risk factor C + CV risk factor D",
            # Counts an unnamed set rather than indexing into one.
            "Two or more specified CV risk factors",
        ],
    )
    def test_should_build_the_rule_when_the_seed_names_an_entity(self, monkeypatch, seed):
        criterion = {
            "id": 2,
            "description": seed,
            "sourceText": seed,
            "domain": "Observation",
            "window": {"start": -9999, "end": 0},
        }
        service = _service(
            monkeypatch, _mapping(CV_RISK_FACTOR_1_ANSWER, "Observation", seed)
        )

        rule = service._build_seeded_eligibility_rule(
            criterion=criterion, codeset_id=4, exclusion=False
        )

        criteria = rule["rule"]["expression"]["CriteriaList"][0]["Criteria"]
        assert list(criteria) == ["Observation"]
        assert criteria["Observation"]["CodesetId"] == 4
