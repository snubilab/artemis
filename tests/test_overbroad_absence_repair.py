"""The export-time narrowing of an over-broad absence concept set.

Every id here is a real one from the live vocabulary, measured on 2026-09-18 against
``synthea23m.concept`` / ``concept_ancestor``:

    4130526  'Disorder of glucose metabolism'  Condition SNOMED  standard, valid
             180 valid descendants, which INCLUDE 201826
    201254   'Type 1 diabetes mellitus'        Condition SNOMED  standard, valid
             25 valid descendants, which do NOT include 201826
    201826   'Type 2 diabetes mellitus'        Condition SNOMED  standard, valid
    4170226  'Disorder of lipoprotein AND/OR lipid metabolism'  Condition, 280 desc.
    4159131  'Dyslipidemia'                    Condition SNOMED, 6 desc., child of 4170226
    381316   'Cerebrovascular accident'        Condition SNOMED
    36210384 'Stroke'                          Meas Value LOINC  -- the domain trap

No database: the closure resolver runs against
:class:`~src.services.conceptset_closure.PrefetchedVocabulary` and the name/domain
lookup against :class:`~src.services.overbroad_absence_repair.PrefetchedConcepts`.
"""
from __future__ import annotations

import copy

import pytest

from src.services.conceptset_closure import PrefetchedVocabulary
from src.services.overbroad_absence_repair import (
    ConceptRecord,
    PrefetchedConcepts,
    iter_overbroad_candidates,
    repair_overbroad_absence_sets,
)

# --------------------------------------------------------------------------
# vocabulary fixtures
# --------------------------------------------------------------------------

RECORDS = {
    4130526: ConceptRecord(4130526, "Disorder of glucose metabolism", "Condition",
                           "SNOMED", "Disorder", "S", "126859007", None),
    201254: ConceptRecord(201254, "Type 1 diabetes mellitus", "Condition",
                          "SNOMED", "Disorder", "S", "46635009", None),
    201826: ConceptRecord(201826, "Type 2 diabetes mellitus", "Condition",
                          "SNOMED", "Disorder", "S", "44054006", None),
    4170226: ConceptRecord(4170226, "Disorder of lipoprotein AND/OR lipid metabolism",
                           "Condition", "SNOMED", "Disorder", "S", "30924005", None),
    4159131: ConceptRecord(4159131, "Dyslipidemia", "Condition",
                           "SNOMED", "Disorder", "S", "370992007", None),
    381316: ConceptRecord(381316, "Cerebrovascular accident", "Condition",
                          "SNOMED", "Disorder", "S", "230690007", None),
    36210384: ConceptRecord(36210384, "Stroke", "Meas Value",
                            "LOINC", "Answer", "S", "LA14283-8", None),
    4112752: ConceptRecord(4112752, "Basal cell carcinoma of skin", "Condition",
                           "SNOMED", "Disorder", "S", "254701007", None),
    4028320: ConceptRecord(4028320, "Basal cell carcinoma", "Observation",
                           "SNOMED", "Morph Abnormality", "S", "11897000", None),
}

#: ancestor -> descendants, as ``concept_ancestor`` holds them (self rows omitted:
#: the resolver adds the ancestor itself through the direct branch).
ANCESTOR_EDGES = {
    4130526: {201254, 201826},
    4170226: {4159131},
}


def vocabulary() -> PrefetchedVocabulary:
    return PrefetchedVocabulary(
        concept_invalid_reason={cid: rec.invalid_reason for cid, rec in RECORDS.items()},
        ancestor_edges={a: set(d) for a, d in ANCESTOR_EDGES.items()},
    )


def catalog(*, extra: list[ConceptRecord] = ()) -> PrefetchedConcepts:
    records = dict(RECORDS)
    for rec in extra:
        records[rec.concept_id] = rec
    return PrefetchedConcepts(records=records)


# --------------------------------------------------------------------------
# cohort fixtures
# --------------------------------------------------------------------------

def concept_item(concept_id: int, *, excluded: bool = False) -> dict:
    rec = RECORDS[concept_id]
    return {
        "concept": {
            "CONCEPT_ID": rec.concept_id,
            "CONCEPT_NAME": rec.concept_name,
            "DOMAIN_ID": rec.domain_id,
            "VOCABULARY_ID": rec.vocabulary_id,
            "CONCEPT_CLASS_ID": rec.concept_class_id,
            "STANDARD_CONCEPT": rec.standard_concept,
            "STANDARD_CONCEPT_CAPTION": "Standard",
            "CONCEPT_CODE": "",
            "INVALID_REASON": None,
            "INVALID_REASON_CAPTION": None,
        },
        "includeDescendants": True,
        "includeMapped": False,
        "isExcluded": excluded,
    }


def cohort(
    *,
    set_name: str,
    members: list[dict],
    criteria_type: str = "ConditionOccurrence",
    occurrence: dict | None = None,
) -> dict:
    """CARMELINA's shape: a T2DM entry event and one single-criterion inclusion rule."""
    return {
        "ConceptSets": [
            {"id": 2, "name": "Type 2 Diabetes Mellitus",
             "expression": {"items": [concept_item(201826)]}},
            {"id": 14, "name": set_name, "expression": {"items": members}},
        ],
        "PrimaryCriteria": {
            "CriteriaList": [{"ConditionOccurrence": {"CodesetId": 2}}],
            "ObservationWindow": {"PriorDays": 0, "PostDays": 0},
            "PrimaryCriteriaLimit": {"Type": "First"},
        },
        "InclusionRules": [
            {
                "name": set_name,
                "expression": {
                    "Type": "ALL",
                    "CriteriaList": [
                        {
                            "Criteria": {criteria_type: {"CodesetId": 14}},
                            "StartWindow": {"Start": {"Days": 9999, "Coeff": -1},
                                            "End": {"Days": 0, "Coeff": 1}},
                            "RestrictVisit": False,
                            "IgnoreObservationPeriod": False,
                            "Occurrence": occurrence or {"Type": 0, "Count": 0},
                        }
                    ],
                    "DemographicCriteriaList": [],
                    "Groups": [],
                },
            }
        ],
    }


def real_shape() -> dict:
    """The measured defect: codeset 14 'Type 1 diabetes mellitus' = [4130526]."""
    return cohort(set_name="Type 1 diabetes mellitus", members=[concept_item(4130526)])


def apply(base: dict, *, cat: PrefetchedConcepts | None = None):
    return repair_overbroad_absence_sets(base, vocabulary(), cat or catalog())


def member_ids(base: dict, codeset_id: int = 14) -> list[int]:
    cs = next(c for c in base["ConceptSets"] if c["id"] == codeset_id)
    return [i["concept"]["CONCEPT_ID"] for i in cs["expression"]["items"]]


# --------------------------------------------------------------------------
# it fires on the real shape
# --------------------------------------------------------------------------

def test_should_narrow_to_the_named_concept_when_the_set_holds_a_proper_ancestor():
    base = real_shape()
    applied = apply(base)

    assert [(r.codeset_id, r.previous_concept_id, r.concept_id) for r in applied] == [
        (14, 4130526, 201254)
    ]
    assert member_ids(base) == [201254]


def test_should_rewrite_the_whole_concept_record_when_it_narrows():
    base = real_shape()
    apply(base)

    item = next(c for c in base["ConceptSets"] if c["id"] == 14)["expression"]["items"][0]
    assert item["concept"] == {
        "CONCEPT_ID": 201254,
        "CONCEPT_NAME": "Type 1 diabetes mellitus",
        "DOMAIN_ID": "Condition",
        "VOCABULARY_ID": "SNOMED",
        "CONCEPT_CLASS_ID": "Disorder",
        "STANDARD_CONCEPT": "S",
        "STANDARD_CONCEPT_CAPTION": "Standard",
        "CONCEPT_CODE": "46635009",
        "INVALID_REASON": None,
        "INVALID_REASON_CAPTION": None,
    }
    # The flags say how the set is read, not which concept it holds; they survive.
    assert item["includeDescendants"] is True
    assert item["includeMapped"] is False
    assert item["isExcluded"] is False


def test_should_drop_the_entry_concept_from_the_closure_when_it_narrows():
    """The point of the repair: the absence set stops covering the entry event."""
    from src.services.conceptset_closure import resolve_concept_set

    base = real_shape()
    absence = next(c for c in base["ConceptSets"] if c["id"] == 14)
    assert 201826 in resolve_concept_set(absence, vocabulary()).concept_ids

    apply(base)
    assert 201826 not in resolve_concept_set(absence, vocabulary()).concept_ids


def test_should_leave_everything_else_untouched_when_it_narrows():
    base = real_shape()
    before = copy.deepcopy(base)
    apply(base)

    before["ConceptSets"][1]["expression"]["items"] = base["ConceptSets"][1]["expression"]["items"]
    assert base == before


def test_should_be_a_no_op_when_the_set_already_holds_the_named_concept():
    base = cohort(set_name="Type 1 diabetes mellitus", members=[concept_item(201254)])
    before = copy.deepcopy(base)

    assert apply(base) == []
    assert base == before


# --------------------------------------------------------------------------
# the five declines
# --------------------------------------------------------------------------

def test_should_decline_when_the_set_holds_more_than_one_member():
    base = cohort(
        set_name="Type 1 diabetes mellitus",
        members=[concept_item(4130526), concept_item(4170226)],
    )
    before = copy.deepcopy(base)

    assert apply(base) == []
    assert base == before


def test_should_decline_when_the_set_carries_an_excluded_member():
    base = cohort(
        set_name="Type 1 diabetes mellitus",
        members=[concept_item(4130526), concept_item(201826, excluded=True)],
    )
    assert apply(base) == []


def test_should_decline_when_the_sets_only_member_is_excluded():
    """The case the member count does NOT catch: one item, and it is the exclusion."""
    base = cohort(
        set_name="Type 1 diabetes mellitus",
        members=[concept_item(4130526, excluded=True)],
    )
    before = copy.deepcopy(base)

    assert apply(base) == []
    assert base == before


def test_should_decline_when_the_existing_member_is_a_descendant_rather_than_an_ancestor():
    """The direction is what makes this a narrowing. Reversed, it is a widening."""
    base = cohort(set_name="Disorder of glucose metabolism", members=[concept_item(201254)])
    before = copy.deepcopy(base)

    assert apply(base) == []
    assert base == before


def test_should_decline_when_the_existing_member_is_unrelated_to_the_named_concept():
    base = cohort(set_name="Type 1 diabetes mellitus", members=[concept_item(4170226)])
    assert apply(base) == []


def test_should_decline_when_the_name_matches_no_standard_concept():
    base = cohort(set_name="Thrombocytopenia", members=[concept_item(4130526)])
    before = copy.deepcopy(base)

    assert apply(base) == []
    assert base == before


def test_should_decline_when_the_name_matches_more_than_one_standard_concept():
    """Two standard concepts share the name, so the name does not resolve."""
    twin = ConceptRecord(9_000_001, "Type 1 diabetes mellitus", "Condition",
                         "SNOMED", "Disorder", "S", "X", None)
    base = real_shape()
    before = copy.deepcopy(base)

    assert apply(base, cat=catalog(extra=[twin])) == []
    assert base == before


def test_should_decline_when_the_only_name_match_is_not_standard():
    non_standard = ConceptRecord(9_000_002, "Hyperglycemia", "Condition",
                                 "SNOMED", "Disorder", None, "X", None)
    base = cohort(set_name="Hyperglycemia", members=[concept_item(4130526)])
    assert apply(base, cat=catalog(extra=[non_standard])) == []


def test_should_decline_when_the_only_name_match_is_invalid():
    retired = ConceptRecord(9_000_003, "Hyperglycemia", "Condition",
                            "SNOMED", "Disorder", "S", "X", "D")
    base = cohort(set_name="Hyperglycemia", members=[concept_item(4130526)])
    assert apply(base, cat=catalog(extra=[retired])) == []


# --------------------------------------------------------------------------
# the domain gate, and the presence gate
# --------------------------------------------------------------------------

def test_should_decline_when_the_named_concept_sits_in_another_domain():
    """'Stroke' as a name resolves to a LOINC Meas Value, not to the Condition."""
    base = cohort(set_name="Stroke", members=[concept_item(381316)])
    before = copy.deepcopy(base)

    assert apply(base) == []
    assert base == before


def test_should_decline_when_the_domains_differ_but_the_criterion_admits_both():
    """The case the criterion-domain gate does NOT catch, so condition 5 has to.

    ``Death`` reads Condition OR Observation, so an Observation replacement passes
    condition 4 -- but the set holds ``4112752 'Basal cell carcinoma of skin'``
    (Condition) while the name resolves to ``4028320 'Basal cell carcinoma'``
    (Observation, a morphologic abnormality). Different kinds of thing, same criterion.
    """
    vocab = PrefetchedVocabulary(
        concept_invalid_reason={cid: rec.invalid_reason for cid, rec in RECORDS.items()},
        ancestor_edges={4112752: {4028320}},
    )
    base = cohort(
        set_name="Basal cell carcinoma",
        members=[concept_item(4112752)],
        criteria_type="Death",
    )
    before = copy.deepcopy(base)

    assert repair_overbroad_absence_sets(base, vocab, catalog()) == []
    assert base == before


def test_should_decline_when_the_criterion_table_cannot_hold_the_replacement():
    """A Measurement criterion over a Condition replacement is the shape the
    delivery gate refuses, so the generator must not emit it."""
    base = cohort(
        set_name="Type 1 diabetes mellitus",
        members=[concept_item(4130526)],
        criteria_type="Measurement",
    )
    assert apply(base) == []


def test_should_decline_when_the_criterion_is_a_presence_criterion():
    """EMPA-REG codeset 9 'Dyslipidemia' = [4170226], read at ``at least 1``.

    Narrowing there is a population change (280 concepts -> 6), not the repair of
    a rule that can never be satisfied, and which reading the protocol intended is
    not decidable from the file.
    """
    base = cohort(
        set_name="Dyslipidemia",
        members=[concept_item(4170226)],
        occurrence={"Type": 2, "Count": 1},
    )
    before = copy.deepcopy(base)

    assert apply(base) == []
    assert base == before


def test_should_decline_when_the_set_is_also_the_entry_event():
    """A PrimaryCriteria reference carries no Occurrence, so it is never an absence."""
    base = real_shape()
    base["PrimaryCriteria"]["CriteriaList"].append({"ConditionOccurrence": {"CodesetId": 14}})
    assert apply(base) == []


def test_should_decline_when_nothing_references_the_set():
    base = real_shape()
    base["InclusionRules"] = []
    assert apply(base) == []


# --------------------------------------------------------------------------
# the DB-free pre-gate
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "base,expected",
    [
        (real_shape(), 1),
        # A presence-read set IS a candidate, so its decline can name the concept it
        # would have been narrowed to; the absence test is applied after the vocabulary.
        (cohort(set_name="Dyslipidemia", members=[concept_item(4170226)],
                occurrence={"Type": 2, "Count": 1}), 1),
        (cohort(set_name="Type 1 diabetes mellitus",
                members=[concept_item(4130526), concept_item(4170226)]), 0),
        (cohort(set_name="Type 1 diabetes mellitus", members=[concept_item(4130526)],
                criteria_type="NotAModelledCriteriaType"), 0),
    ],
)
def test_should_report_candidates_without_a_vocabulary_when_asked(base, expected):
    assert len(list(iter_overbroad_candidates(base))) == expected


def test_should_name_what_it_would_have_narrowed_when_it_declines_a_presence_set(caplog):
    """The presence decline is the one a reader must be able to act on."""
    base = cohort(
        set_name="Dyslipidemia",
        members=[concept_item(4170226)],
        occurrence={"Type": 2, "Count": 1},
    )
    with caplog.at_level("WARNING"):
        assert apply(base) == []

    assert any(
        "4159131" in r.getMessage() and "not an absence" in r.getMessage()
        for r in caplog.records
    ), caplog.text
