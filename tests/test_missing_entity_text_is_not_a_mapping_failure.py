"""A criterion whose mandatory ``entity_text`` is empty says so, in the artifact.

``8bbd50d`` made ``entity_text`` MANDATORY on any criterion with no ``sub_criteria``,
because it is the ONLY text the concept mapper is ever given. The model complies per
row and unreliably. What happens when it does not comply is what this file pins.

Nothing enforced the mandate and nothing recorded a breach, because
:func:`~src.utils.criterion_seed.criterion_mapper_seed` falls back from ``sourceText``
(which carries the IR's ``entity_text`` -- see ``_criterion_dict_from_ir_item``, where
``source_text = entity_text``) to ``description``, and that fallback is invisible. So a
mapper refused on a substituted seed was recorded as ``no-concept-mapping``: a verdict
about the VOCABULARY, on a seed the protocol never named.

Measured over ``output/site_gap/2026-09-10/store_grounded/studies.json`` and
``tmp/tte_cold6_20260908/studies.json``, counting only the criteria that REACH the
mapper across the six delivered trials, the substitution is neither rare nor fatal --
which is why the remedy is a record and a re-coding, not a refusal:

    store                reach   entity present      entity EMPTY
    store_grounded        293    4/223 = 0.018      8/70 = 0.114
    tte_cold6_20260908    274    1/184 = 0.005     10/90 = 0.111

The two runs agree on the EMPTY column to within 0.003 -- and ~89% of the substituted
seeds still map. A guard that refused every empty ``entity_text`` would destroy 62
working criteria in the grounded store alone to recover 8.

Two rules follow, and both are pinned below:

* the loss is re-coded to ``REFUSAL_MISSING_ENTITY_TEXT``, so an extraction defect
  stops being booked as a mapping defect -- but ONLY for the codes the seed actually
  causes, and NEVER over ``unmappable-placeholder``, which is the one code the delivery
  gate permits and which those rows earn on the seed's own words whichever field
  carried them. Re-coding it would flip ARISTOTLE from PASS to FAIL for a row nothing
  is wrong with;
* every criterion that reached the mapper on a substituted seed is recorded under
  ``MISSING_ENTITY_CRITERIA_KEY``, whether it survived or not -- same
  present-and-empty contract as ``_defaultedWindowCriteria``. The 62 survivors are the
  reason: they are mapped on a human-facing label ("CV risk factor A", "Positive
  biomarker", "Drug Naïve or Pre-treated") and nothing anywhere said so.

Every criterion dict below is transcribed verbatim from
``output/site_gap/2026-09-10/store_grounded/studies.json`` rather than invented, per
``docs/mistakes.md``.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

# The two NEW names -- `REFUSAL_MISSING_ENTITY_TEXT` and everything under
# `criterion_seed` this file needs -- are reached THROUGH their modules rather than
# imported by name, so this file still COLLECTS against a tree without them: on
# `36973f2` the rows below fail on `AttributeError: REFUSAL_MISSING_ENTITY_TEXT` and
# `no-concept-mapping != missing-entity-text`, which is the evidence that the producer
# half is missing, instead of the whole module erroring at import and reporting nothing
# about the behaviour. Same convention as
# `tests/test_placeholder_seed_refuses_as_irreducible.py`.
from src.services.tte_service import TTEService
from src.utils import criterion_refusal, criterion_seed
from src.utils.criterion_refusal import (
    REFUSAL_DOMAIN_CONTRADICTION,
    REFUSAL_NO_CONCEPT_MAPPING,
    REFUSAL_UNMAPPABLE_PLACEHOLDER,
    CriterionRefused,
)

# The delivery-gate fixture and its ARISTOTLE store study, shared with the sibling gate
# tests rather than re-declared, so a change to the store shape cannot leave this file
# testing a study the others no longer use.
from tests.test_delivery_gate_reads_drop_records import (
    ARISTOTLE_RECORDS,
    CLEAN_RECORDS,
    _study,
)


def _missing(criterion) -> bool:
    return criterion_seed.criterion_entity_text_missing(criterion)


def _expected_code() -> str:
    return criterion_refusal.REFUSAL_MISSING_ENTITY_TEXT

# ---------------------------------------------------------------------------
# The rows. Study indices are the store's own 0-based positions; the reporting
# convention that produced the observation this file answers is 1-based, so
# store index 7 is EMPA-REG "[8]" and store index 8 is CARMELINA "[9]".
# ---------------------------------------------------------------------------

#: EMPA-REG (store index 7) inclusion 15 and 16. Both leaves, both reached the mapper,
#: both refused `no-concept-mapping` in the 2026-09-10 grounded delivery. These are the
#: two rows in the observation that are genuine mandate breaches.
EMPA_REG_INCL_15 = {
    "id": 15,
    "description": "Drug naive",
    "domain": "Drug",
    "sourceText": "",
    "protocolLine": (
        "Glycosylated haemoglobin (HbA1c) of >= 7.0% and <=10% for patients on "
        "background therapy or HbA1c >= 7.0% and <= 9.0% for drug naive patients"
    ),
    "window": {"start": -365, "end": 0},
    "logicType": "ABSENCE",
    "groupId": "37b44bb4-d2c6-4973-8816-e9a87249d2ea",
    "groupType": "ANY",
    "isGroupLabel": False,
}
EMPA_REG_INCL_16 = {
    "id": 16,
    "description": "Pre treated with any background therapy",
    "domain": "Drug",
    "sourceText": "",
    "protocolLine": (
        "Male or female patients on diet and exercise regimen who are drug naive or "
        "pre treated with any background therapy. Antidiabetic therapy has to be "
        "unchanged for 12 weeks prior to randomization."
    ),
    "window": {"start": -365, "end": 0},
    "logicType": "PRESENCE",
    "groupId": "37b44bb4-d2c6-4973-8816-e9a87249d2ea",
    "groupType": "ANY",
    "isGroupLabel": False,
}

#: The other three rows of the same observation. Every one is a GROUP LABEL -- a parent
#: with `sub_criteria` -- where `8bbd50d` states `entity_text` is null "ONLY on a parent
#: row that has them". They are mandate-COMPLIANT, they never reach the mapper
#: (`EligibilityCriterion.mappable` is False for a group label), and a guard that fired
#: on them would be flagging correct extraction. Two of the three cost nothing at all:
#: CARMELINA 10 and 13 each label a group whose members both mapped (concept sets 7/8
#: and 9/10).
EMPA_REG_INCL_14_GROUP_LABEL = {
    "id": 14,
    "description": "Drug naive or pre treated with any background therapy",
    "domain": "Drug",
    "sourceText": "",
    "window": None,
    "logicType": "PRESENCE",
    "groupId": "37b44bb4-d2c6-4973-8816-e9a87249d2ea",
    "groupType": "ANY",
    "isGroupLabel": True,
}
CARMELINA_INCL_10_GROUP_LABEL = {
    "id": 10,
    "description": "Antidiabetic Naïve or Pre-treated (Excluding GLP-1/DPP-4/SGLT-2)",
    "domain": "Drug",
    "sourceText": "",
    "window": None,
    "logicType": "PRESENCE",
    "groupId": "bbd9cf25-edc0-44f3-aa6b-32e6a4e3d7d5",
    "groupType": "ANY",
    "isGroupLabel": True,
}
CARMELINA_INCL_13_GROUP_LABEL = {
    "id": 13,
    "description": "Antidiabetic Naïve or Pre-treated (General)",
    "domain": "Drug",
    "sourceText": "",
    "window": None,
    "logicType": "PRESENCE",
    "groupId": "9e1407f0-8282-433b-81ac-be87215753f8",
    "groupType": "ANY",
    "isGroupLabel": True,
}

#: The two rows of the observation where the model DID comply, on the same rule and the
#: same run. Both carry an entity and both mapped (concept sets 5 and 7). The guard must
#: stay silent on them, or it is measuring nothing.
LEADER_INCL_9_COMPLIANT = {
    "id": 9,
    "description": "Anti-diabetic drug naive",
    "domain": "Drug",
    "sourceText": "oral anti-diabetic drug",
    "window": {"start": -365, "end": 0},
    "logicType": "ABSENCE",
    "groupId": "5b5b0274-2f71-441e-9e95-9abe04064610",
    "groupType": "ANY",
    "isGroupLabel": False,
}
CARMELINA_INCL_11_COMPLIANT = {
    "id": 11,
    "description": "Drug Naïve or Pre-treated",
    "domain": "Drug",
    "sourceText": "antidiabetic background medication",
    "window": None,
    "logicType": "PRESENCE",
    "groupId": "bbd9cf25-edc0-44f3-aa6b-32e6a4e3d7d5",
    "groupType": "ANY",
    "isGroupLabel": False,
}

#: ARISTOTLE (store index 2) exclusion 26, verbatim. Empty `sourceText` AND the one
#: permitted refusal code in the whole 2026-09-10 batch. It is the reason the re-coding
#: carries an exemption rather than firing on every empty entity: ARISTOTLE's two arms
#: PASS the delivery gate on this row's permit, and a re-code would take that away for
#: a row whose loss is genuinely irreducible -- "investigational drug" names a role in
#: the study, not a substance, so no `entity_text` would have helped.
ARISTOTLE_EXCL_26_PLACEHOLDER = {
    "id": 26,
    "description": "Investigational drug use",
    "domain": "Drug",
    "sourceText": "",
    "window": {"start": -30, "end": 0},
    "logicType": "ABSENCE",
    "isGroupLabel": False,
}

#: PLATO (store index 1) exclusion 32, verbatim. A `domain-contradiction` on a criterion
#: whose entity IS present -- the control that keeps the re-coding honest. `criterion_
#: refusal.py` already records the verdict: "Contraindication to clopidogrel ...
#: REDUCIBLE -- names a real substance, and a better mapper finds it". The defect is on
#: the mapper side and the code must keep saying so.
PLATO_EXCL_32_COMPLIANT = {
    "id": 32,
    "description": "Clopidogrel contraindication",
    "domain": "Condition",
    "sourceText": "Clopidogrel contraindication",
    "window": {"start": -9999, "end": 0},
    "logicType": "ABSENCE",
    "isGroupLabel": False,
}


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


def _service(monkeypatch, mapping_or_raiser) -> TTEService:
    svc = TTEService.__new__(TTEService)

    def _recommend(seed, **kwargs):
        if isinstance(mapping_or_raiser, BaseException):
            raise mapping_or_raiser
        return mapping_or_raiser

    monkeypatch.setattr(svc, "_recommend_seeded_concept_set", _recommend)
    return svc


def _mapping(domains: list[str], name: str) -> dict[str, Any]:
    """A seeded-concept-set answer, one concept per domain."""
    return {
        "name": name,
        "domain": domains[0],
        "expression": {
            "items": [
                {
                    "concept": {
                        "CONCEPT_ID": 9_000_000 + index,
                        "CONCEPT_NAME": f"{name} ({domain})",
                        "CONCEPT_CODE": str(9_000_000 + index),
                        "DOMAIN_ID": domain,
                        "VOCABULARY_ID": "SNOMED",
                        "CONCEPT_CLASS_ID": "Clinical Finding",
                    },
                    "includeDescendants": True,
                    "isExcluded": False,
                }
                for index, domain in enumerate(domains)
            ]
        },
        "mapping_metadata": None,
    }


# ---------------------------------------------------------------------------
# 1. The predicate, on the rows of the observation itself
# ---------------------------------------------------------------------------


class TestThePredicateSeparatesTheObservationsRows:
    """The observation listed five rows as "empty anyway". Two are breaches; three are
    group labels the mandate exempts. The predicate has to say which is which, and stay
    silent on the two rows where the model complied."""

    @pytest.mark.parametrize(
        "criterion",
        [EMPA_REG_INCL_15, EMPA_REG_INCL_16],
        ids=["empa-reg-incl-15", "empa-reg-incl-16"],
    )
    def test_should_report_missing_when_a_leaf_carries_no_entity_text(self, criterion):
        assert _missing(criterion) is True

    @pytest.mark.parametrize(
        "criterion",
        [LEADER_INCL_9_COMPLIANT, CARMELINA_INCL_11_COMPLIANT, PLATO_EXCL_32_COMPLIANT],
        ids=["leader-incl-9", "carmelina-incl-11", "plato-excl-32"],
    )
    def test_should_stay_silent_when_the_criterion_carries_its_entity(self, criterion):
        assert _missing(criterion) is False

    @pytest.mark.parametrize(
        "criterion",
        [
            EMPA_REG_INCL_14_GROUP_LABEL,
            CARMELINA_INCL_10_GROUP_LABEL,
            CARMELINA_INCL_13_GROUP_LABEL,
        ],
        ids=["empa-reg-incl-14", "carmelina-incl-10", "carmelina-incl-13"],
    )
    def test_should_stay_silent_on_a_group_label_that_the_mandate_exempts(self, criterion):
        """`8bbd50d`: null "ONLY on a parent row that has [sub_criteria]". A group label
        is that row, it never reaches the mapper, and firing here would flag compliant
        extraction as a defect."""
        assert _missing(criterion) is False

    def test_should_treat_a_whitespace_only_entity_as_missing(self):
        """`criterion_mapper_seed` strips before choosing, so "   " is not an entity
        there either -- the two must agree or the record contradicts the seed."""
        assert _missing({**EMPA_REG_INCL_15, "sourceText": "   "}) is True


# ---------------------------------------------------------------------------
# 2. The re-coding, at the raise site
# ---------------------------------------------------------------------------


class TestASubstitutedSeedIsNotABookedMappingFailure:
    @pytest.mark.parametrize(
        "criterion",
        [EMPA_REG_INCL_15, EMPA_REG_INCL_16],
        ids=["empa-reg-incl-15", "empa-reg-incl-16"],
    )
    def test_should_recode_no_concept_mapping_when_the_seed_was_substituted(
        self, monkeypatch, criterion
    ):
        """The two rows of the 2026-09-10 EMPA-REG failure, at the raise site.

        The gate said "No concept mapping found for 'Drug naive'", which sends a reader
        to the vocabulary. 'Drug naive' is the criterion's human-facing name; the mapper
        was never given an entity at all."""
        refusal = CriterionRefused(
            f"No concept mapping found for '{criterion['description']}'",
            code=REFUSAL_NO_CONCEPT_MAPPING,
        )
        service = _service(monkeypatch, refusal)

        with pytest.raises(CriterionRefused) as caught:
            service._build_seeded_eligibility_rule(
                criterion=criterion, codeset_id=7, exclusion=False
            )

        assert caught.value.code == _expected_code()
        # The mapper's own verdict is not thrown away -- it is chained, so
        # `describe_mapping_failure` folds both into one reason.
        assert caught.value.__cause__ is refusal
        # ...and the code it carried is recoverable without parsing prose.
        assert REFUSAL_NO_CONCEPT_MAPPING in (caught.value.detail or "")

    def test_should_recode_a_domain_contradiction_earned_on_a_substituted_seed(
        self, monkeypatch
    ):
        """CARMELINA inclusion 16/17 ('Stable Background Medication ...') are Drug
        criteria whose concept set came back Condition/Observation/Procedure. The seed
        was the label, not a drug; the row one line above it in the same store
        (inclusion 11, `sourceText='antidiabetic background medication'`) mapped to a
        Drug set. The wrong-domain answer is downstream of the substitution."""
        criterion = {
            "id": 16,
            "description": "Stable Background Medication (8 weeks prior to screening)",
            "domain": "Drug",
            "sourceText": "",
            "window": {"start": -56, "end": 0},
            "logicType": "PRESENCE",
            "isGroupLabel": False,
        }
        service = _service(
            monkeypatch,
            _mapping(
                ["Condition", "Observation", "Procedure"],
                "Stable Background Medication (8 weeks prior to screening)",
            ),
        )

        with pytest.raises(CriterionRefused) as caught:
            service._build_seeded_eligibility_rule(
                criterion=criterion, codeset_id=7, exclusion=False
            )

        assert caught.value.code == _expected_code()
        assert REFUSAL_DOMAIN_CONTRADICTION in (caught.value.detail or "")
        # The mechanism stays legible in the delivered record.
        assert "DrugExposure reads Drug" in str(caught.value.__cause__)

    def test_should_keep_the_contradiction_code_when_the_entity_is_present(
        self, monkeypatch
    ):
        """PLATO exclusion 32, the control. A real substance answered from the wrong
        domain is a mapper defect, and re-coding it would send a reader to extraction
        for a row whose extraction was correct."""
        service = _service(
            monkeypatch, _mapping(["Drug"], "Clopidogrel contraindication")
        )

        with pytest.raises(CriterionRefused) as caught:
            service._build_seeded_eligibility_rule(
                criterion=PLATO_EXCL_32_COMPLIANT, codeset_id=41, exclusion=True
            )

        assert caught.value.code == REFUSAL_DOMAIN_CONTRADICTION

    def test_should_never_recode_over_the_one_permitted_code(self, monkeypatch):
        """ARISTOTLE exclusion 26. `unmappable-placeholder` is the ONLY code
        `PERMITTED_REFUSAL_CODES` permits, and the row earns it on the seed's own words:
        "Investigational drug use" names no substance whichever field carried it. Both
        ARISTOTLE arms PASS on this permit; re-coding it costs two PASSes for a loss
        that is irreducible either way."""
        refusal = CriterionRefused(
            "No concept mapping found for 'Investigational drug use'",
            code=REFUSAL_UNMAPPABLE_PLACEHOLDER,
        )
        service = _service(monkeypatch, refusal)

        with pytest.raises(CriterionRefused) as caught:
            service._build_seeded_eligibility_rule(
                criterion=ARISTOTLE_EXCL_26_PLACEHOLDER, codeset_id=41, exclusion=True
            )

        assert caught.value.code == REFUSAL_UNMAPPABLE_PLACEHOLDER
        assert caught.value is refusal

    def test_should_not_touch_a_refusal_the_seed_did_not_cause(self, monkeypatch):
        """A value filter the CDM table cannot read is refused AFTER the mapper answered
        and has nothing to do with which text seeded it. Re-coding it would attribute a
        Circe-side defect to extraction. CAROLINA inclusion 37 is the measured row and
        it carries its entity; this is the same shape with the entity removed, so the
        exemption is tested where it could actually fire."""
        criterion = {
            "id": 37,
            "description": "Significant vessel stenosis",
            "domain": "Condition",
            "sourceText": "",
            "valueConstraint": {
                "op": "gte",
                "value": 50.0,
                "unitText": "%",
                "referenceBound": "absolute",
                "unitConceptId": 8554,
            },
            "window": {"start": -9999, "end": 0},
            "logicType": "PRESENCE",
            "isGroupLabel": False,
        }
        service = _service(monkeypatch, _mapping(["Condition"], "Significant vessel stenosis"))

        with pytest.raises(CriterionRefused) as caught:
            service._build_seeded_eligibility_rule(
                criterion=criterion, codeset_id=7, exclusion=False
            )

        assert caught.value.code != _expected_code()

    def test_should_build_the_rule_unchanged_when_a_substituted_seed_maps(
        self, monkeypatch
    ):
        """The 62 survivors. A substituted seed that maps is NOT refused -- refusing it
        would trade 8 recovered losses for 62 new ones."""
        service = _service(monkeypatch, _mapping(["Drug"], "Antidiabetic agent"))

        rule = service._build_seeded_eligibility_rule(
            criterion=EMPA_REG_INCL_16, codeset_id=7, exclusion=False
        )

        assert rule["rule"]["expression"]["CriteriaList"][0]["Criteria"]["DrugExposure"][
            "CodesetId"
        ] == 7


# ---------------------------------------------------------------------------
# 3. The record, so a survivor is visible too
# ---------------------------------------------------------------------------


class TestTheBreachIsRecordedWhetherOrNotItCost:
    def test_should_carry_the_key_when_no_seed_was_substituted(self):
        """Present-and-empty, the same contract `_defaultedWindowCriteria` keeps: "0
        substituted" is a claim an absent key cannot make."""
        assert criterion_seed.MISSING_ENTITY_CRITERIA_KEY == "_missingEntityCriteria"

    def test_should_record_a_survivor_and_name_its_substituted_seed(self, monkeypatch):
        """CARMELINA inclusion 12 mapped on `description` because `sourceText` was empty.
        It shipped with a concept set and nothing anywhere said the mapper had been asked
        about the criterion's name."""
        criterion = {
            "id": 12,
            "description": "Exclusion of GLP-1/DPP-4/SGLT-2",
            "domain": "Drug",
            "sourceText": "",
            "window": None,
            "logicType": "ABSENCE",
            "isGroupLabel": False,
        }
        record = criterion_seed.missing_entity_record(criterion, role="inclusion", mapped=True)

        assert record["criterionId"] == "12"
        assert record["role"] == "inclusion"
        assert record["seed"] == "Exclusion of GLP-1/DPP-4/SGLT-2"
        assert record["outcome"] == "mapped"

    def test_should_record_a_loss_under_a_distinct_outcome(self):
        record = criterion_seed.missing_entity_record(
            EMPA_REG_INCL_15, role="inclusion", mapped=False
        )
        assert record["outcome"] == "unmapped"
        assert record["seed"] == "Drug naive"


# ---------------------------------------------------------------------------
# 4. End to end, through the generator that writes the artifact
# ---------------------------------------------------------------------------


UNMAPPABLE = "qqzzxx nonexistent clinical term"


def _stub_concept_set(name: str, domain: str = "Drug") -> dict[str, Any]:
    return {
        "name": name,
        "domain": domain,
        "expression": {
            "items": [
                {
                    "concept": {
                        "CONCEPT_ID": 1594973,
                        "CONCEPT_NAME": name,
                        "CONCEPT_CODE": "1594973",
                        "DOMAIN_ID": domain,
                        "VOCABULARY_ID": "RxNorm",
                        "CONCEPT_CLASS_ID": "Ingredient",
                    },
                    "includeDescendants": True,
                    "isExcluded": False,
                }
            ]
        },
        "mapping_metadata": None,
    }


@pytest.fixture
def generator(monkeypatch) -> TTEService:
    """A service whose mapper resolves everything except :data:`UNMAPPABLE`."""
    svc = TTEService.__new__(TTEService)

    def fake_recommend(seed_text: str, **kwargs: Any) -> dict[str, Any]:
        if seed_text.strip() == UNMAPPABLE:
            raise CriterionRefused(
                f"No concept mapping found for '{seed_text}'",
                code=REFUSAL_NO_CONCEPT_MAPPING,
            )
        return _stub_concept_set(seed_text.strip())

    monkeypatch.setattr(svc, "_recommend_seeded_concept_set", fake_recommend)
    return svc


def _eligibility(inclusion: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "targetCohortName": "empagliflozin",
        "inclusionCriteria": inclusion,
        "exclusionCriteria": [],
    }


class TestTheArtifactCarriesTheRecord:
    def test_should_carry_the_key_present_and_empty_when_every_entity_was_extracted(
        self, generator
    ):
        """"0 substituted" is a claim; an absent key cannot make it. Same contract as
        `_defaultedWindowCriteria`, and the reason is the same: a check whose only output
        is silence cannot be told from a check that never ran."""
        circe = generator._build_seeded_target_circe(
            _eligibility([{**LEADER_INCL_9_COMPLIANT, "id": "inc-1"}])
        )
        assert circe[criterion_seed.MISSING_ENTITY_CRITERIA_KEY] == []

    def test_should_record_a_substituted_seed_that_mapped(self, generator):
        """The half `_unmappedCriteria` structurally cannot hold. 62 of the grounded
        store's 70 substituted seeds are this row: a concept set minted from a
        human-facing label, shipped, and recorded nowhere."""
        circe = generator._build_seeded_target_circe(
            _eligibility([{**EMPA_REG_INCL_16, "id": "inc-1"}])
        )
        records = circe[criterion_seed.MISSING_ENTITY_CRITERIA_KEY]
        assert len(records) == 1
        assert records[0]["outcome"] == "mapped"
        assert records[0]["seed"] == "Pre treated with any background therapy"
        # ...and it is NOT a loss: the rule shipped.
        assert circe["_unmappedCriteria"] == []
        assert circe["_generationCensus"]["mapped"] == 1

    def test_should_record_a_substituted_seed_that_was_lost_and_recode_its_refusal(
        self, generator
    ):
        """Both halves on one criterion: the record says the mandate was breached, and
        `_unmappedCriteria` stops blaming the vocabulary for it."""
        circe = generator._build_seeded_target_circe(
            _eligibility(
                [{**EMPA_REG_INCL_15, "id": "inc-1", "description": UNMAPPABLE}]
            )
        )
        records = circe[criterion_seed.MISSING_ENTITY_CRITERIA_KEY]
        assert [r["outcome"] for r in records] == ["unmapped"]

        unmapped = circe["_unmappedCriteria"]
        assert len(unmapped) == 1
        assert unmapped[0]["refusalCode"] == _expected_code()
        # The mapper's verdict is chained, not discarded, so the delivered reason names
        # both stages -- `describe_mapping_failure` reads `__cause__` one level deep.
        assert "No concept mapping found" in unmapped[0]["reason"]
        assert REFUSAL_NO_CONCEPT_MAPPING in unmapped[0]["refusalDetail"]

    def test_should_not_record_rows_that_never_reach_the_mapper(self, generator):
        """A group label and a demographic have no seed to substitute. Recording them
        would report the mandate's own exemption as a breach and bury the rows that
        matter under rows that do not."""
        circe = generator._build_seeded_target_circe(
            _eligibility(
                [
                    {**EMPA_REG_INCL_14_GROUP_LABEL, "id": "inc-hdr"},
                    {"id": "inc-age", "domain": "Demographics", "description": "Age >= 50"},
                ]
            )
        )
        assert circe[criterion_seed.MISSING_ENTITY_CRITERIA_KEY] == []
        assert len(circe["_skippedCriteria"]) == 2


# ---------------------------------------------------------------------------
# 5. The delivery gate
# ---------------------------------------------------------------------------



def _substituted(criterion_id: str, label: str, *, outcome: str, role: str = "inclusion"):
    """One :data:`MISSING_ENTITY_CRITERIA_KEY` row, in the producer's shape."""
    return {
        "criterionId": criterion_id,
        "role": role,
        "label": label,
        "domain": "Drug",
        "seed": label,
        "outcome": outcome,
    }


@pytest.fixture
def gate(monkeypatch, tmp_path, capsys):
    """Run the delivery gate over both ARISTOTLE arms carrying `records`."""

    def _run(records: dict[str, Any] | None) -> tuple[int, str]:
        monkeypatch.delenv("TTE_STORE_PATH", raising=False)
        study = _study()
        core = study["eligibility"]["structuredExpression"]
        for role in ("treatment", "comparator"):
            payload = json.loads(json.dumps(core))
            if records is not None:
                payload.update(json.loads(json.dumps(records)))
            (tmp_path / f"aristotle_{role}.circe.json").write_text(json.dumps(payload))
        store = tmp_path / "studies.json"
        store.write_text(json.dumps([study]))

        from scripts.verify_circe_delivery import main

        rc = main(["--dir", str(tmp_path), "--store", str(store), "--map", "aristotle=3"])
        return rc, capsys.readouterr().out

    return _run


def _with_substitutions(records: dict[str, Any], rows: list[dict[str, Any]] | None):
    payload = json.loads(json.dumps(records))
    if rows is not None:
        payload[criterion_seed.MISSING_ENTITY_CRITERIA_KEY] = json.loads(json.dumps(rows))
    return payload


class TestTheGateNamesTheSubstitutedSeeds:
    def test_should_report_the_split_between_lost_and_mapped(self, gate):
        """The mapped count is the reason the clause exists. A file can PASS while
        carrying concept sets minted from a human-facing label, and the report used to
        say nothing about that in either direction."""
        rc, out = gate(
            _with_substitutions(
                CLEAN_RECORDS,
                [
                    _substituted("15", "Drug naive", outcome="unmapped"),
                    _substituted("16", "Pre treated with any background therapy", outcome="mapped"),
                    _substituted("12", "Exclusion of GLP-1/DPP-4/SGLT-2", outcome="mapped"),
                ],
            )
        )
        assert rc == 0, out
        assert "3 seeds substituted for a missing entity_text (1 lost, 2 mapped" in out

    def test_should_say_zero_when_every_criterion_carried_its_entity(self, gate):
        rc, out = gate(_with_substitutions(CLEAN_RECORDS, []))
        assert rc == 0, out
        assert "0 seeds substituted" in out

    def test_should_omit_the_clause_when_the_artifact_predates_the_record(self, gate):
        """All 12 files of the 2026-09-10 delivery are one of these. Printing "0" would
        claim every entity was extracted, which is known to be false -- 70 of the 293
        criteria reaching the mapper in the store behind them were seeded on a
        description."""
        rc, out = gate(CLEAN_RECORDS)
        assert rc == 0, out
        assert "seeds substituted" not in out

    def test_should_change_no_verdict(self, gate):
        """A substituted seed that MAPPED is not criterion loss. The clause reports; it
        must never be what blocks a delivery, or 62 working criteria in the grounded
        store would block 12 files on their own."""
        clean_rc, _ = gate(CLEAN_RECORDS)
        rc, _out = gate(
            _with_substitutions(
                CLEAN_RECORDS, [_substituted("16", "Pre treated", outcome="mapped")] * 3
            )
        )
        assert clean_rc == 0
        assert rc == 0


class TestTheGateNeverPermitsTheNewCode:
    def test_should_block_a_delivery_carrying_a_missing_entity_refusal(self, gate):
        """The re-coding changes WHICH defect a reader is sent to look at, not whether
        the loss ships. `PERMITTED_REFUSAL_CODES` permits `unmappable-placeholder` and
        nothing else; a criterion lost because extraction dropped its entity is a loss a
        correct pipeline would not incur."""
        records = json.loads(json.dumps(ARISTOTLE_RECORDS))
        for row in records["_unmappedCriteria"]:
            row["refusalCode"] = _expected_code()
            row["refusalDetail"] = f"{REFUSAL_NO_CONCEPT_MAPPING}: nothing found"
        rc, out = gate(records)
        assert rc == 1, out
        assert _expected_code() in out
        assert "criterion loss a correct pipeline would not incur" in out
