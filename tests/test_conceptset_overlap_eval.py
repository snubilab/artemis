"""Unit tests for gold-vs-generated concept-set overlap evaluation.

DB-free: every test builds ``ResolvedSet`` fixtures directly, so the pairing
rule and the reporting shape are exercised without a vocabulary.

The fixture names are the real ones from the ARISTOTLE run that motivated the
rule -- a naive best-Jaccard pairing declared gold "CKD 4-ESRD" a match for
generated "Hypertension" at recall 0.14, which is the regression these tests
exist to prevent.
"""
from __future__ import annotations

import pytest

from scripts.conceptset_overlap_eval import (
    DEFAULT_THRESHOLDS,
    ResolvedSet,
    build_report,
    micro_totals,
    name_similarity,
    normalize_set_name,
    over_expansion_rows,
    pair_concept_sets,
    resolve_cohort_sets,
)


def rs(key, name, ids):
    return ResolvedSet(key=str(key), name=name, concept_ids=set(ids))


def outcomes(pairing):
    return {p.gold_name: p.outcome for p in pairing.pairs}


def partners(pairing):
    return {p.gold_name: p.gen_name for p in pairing.pairs}


# --------------------------------------------------------------------------
# pairing rule
# --------------------------------------------------------------------------

def test_should_report_no_counterpart_when_names_and_concepts_both_disagree():
    gold = [rs("g1", "[TROY condition] CKD 4-ESRD", range(0, 51))]
    generated = [rs("a8", "Hypertension", range(45, 187))]  # jaccard 0.04, name 0.00
    pairing = pair_concept_sets(gold, generated, DEFAULT_THRESHOLDS)
    assert outcomes(pairing) == {"[TROY condition] CKD 4-ESRD": "no_counterpart"}
    assert partners(pairing)["[TROY condition] CKD 4-ESRD"] is None


def test_should_match_by_name_when_concept_overlap_is_zero():
    """A real counterpart with recall 0 is a recall failure, not an absent set."""
    gold = [rs("g1", "[TROY] substance abuse", {1, 2, 3})]
    generated = [rs("a12", "Active substance abuse", {90, 91})]
    pairing = pair_concept_sets(gold, generated, DEFAULT_THRESHOLDS)
    assert outcomes(pairing) == {"[TROY] substance abuse": "matched_by_name"}
    assert pairing.pairs[0].recall == 0.0


def test_should_match_by_overlap_when_names_disagree_but_overlap_is_high():
    gold = [rs("g1", "Renal impairment", {1, 2, 3, 4})]
    generated = [rs("a1", "eGFR below threshold", {1, 2, 3, 9})]
    pairing = pair_concept_sets(gold, generated, DEFAULT_THRESHOLDS)
    assert outcomes(pairing) == {"Renal impairment": "matched_by_overlap"}


def test_should_prefer_name_evidence_over_higher_jaccard_partner():
    """AST must pair with AST even though ALT shares more concepts."""
    gold = [rs("g1", "Aspartate aminotransferase (AST)", {1, 2})]
    generated = [
        rs("a1", "Alanine aminotransferase", {1, 2, 3}),  # jaccard 0.67
        rs("a2", "Aspartate aminotransferase", {1, 50, 51}),  # jaccard 0.25, name 0.67
    ]
    pairing = pair_concept_sets(gold, generated, DEFAULT_THRESHOLDS)
    assert partners(pairing)["Aspartate aminotransferase (AST)"] == "Aspartate aminotransferase"
    assert outcomes(pairing)["Aspartate aminotransferase (AST)"] == "matched_by_name"


def test_should_allow_two_gold_sets_to_share_one_generated_counterpart():
    """Gold splits Apixaban into RxNorm and ATC sets; generated has one."""
    gold = [rs("g1", "Apixaban", {1, 2}), rs("g2", "Apixaban (ATC)", {1, 2, 3})]
    generated = [rs("a1", "apixaban", {1, 2, 3})]
    pairing = pair_concept_sets(gold, generated, DEFAULT_THRESHOLDS)
    assert partners(pairing) == {"Apixaban": "apixaban", "Apixaban (ATC)": "apixaban"}


def test_should_report_generated_set_as_unmatched_when_no_gold_claims_it():
    gold = [rs("g1", "Apixaban", {1, 2})]
    generated = [rs("a1", "apixaban", {1, 2}), rs("a2", "Serum ferritin", {700, 701})]
    pairing = pair_concept_sets(gold, generated, DEFAULT_THRESHOLDS)
    assert [u["name"] for u in pairing.unmatched_generated] == ["Serum ferritin"]


def test_should_report_gold_set_in_unmatched_gold_when_it_has_no_counterpart():
    gold = [rs("g1", "[TROY condition] CKD 4-ESRD", {1, 2})]
    generated = [rs("a8", "Hypertension", {300, 301})]
    pairing = pair_concept_sets(gold, generated, DEFAULT_THRESHOLDS)
    assert [u["name"] for u in pairing.unmatched_gold] == ["[TROY condition] CKD 4-ESRD"]


# --------------------------------------------------------------------------
# name normalisation
# --------------------------------------------------------------------------

def test_should_keep_parenthetical_tokens_when_comparing_names():
    assert normalize_set_name("Stroke (hemorrhagic)") == frozenset({"stroke", "hemorrhagic"})
    # dropping the parenthetical would collapse this to a perfect match
    assert name_similarity("Stroke (hemorrhagic)", "Stroke") < 1.0
    # an abbreviation restated in parentheses still scores strongly
    assert name_similarity("Systolic blood pressure (SBP)", "Systolic blood pressure") >= 0.5


def test_should_strip_leading_bracket_prefix_when_normalising_a_name():
    assert normalize_set_name("[TROY condition] hypertension") == frozenset({"hypertension"})


# --------------------------------------------------------------------------
# over-expansion
# --------------------------------------------------------------------------

def test_should_flag_pair_as_over_expanded_when_generated_is_at_least_three_times_gold():
    gold = [
        rs("g1", "Systolic blood pressure", {1}),
        rs("g2", "Hypertension", set(range(100, 142))),
    ]
    generated = [
        rs("a1", "Systolic blood pressure", set(range(1, 35))),
        rs("a2", "Hypertension", set(range(100, 142))),
    ]
    pairing = pair_concept_sets(gold, generated, DEFAULT_THRESHOLDS)
    rows = over_expansion_rows(pairing.pairs, DEFAULT_THRESHOLDS.over_expansion_ratio)
    assert [r["gold_name"] for r in rows] == ["Systolic blood pressure"]
    assert rows[0]["expansion_ratio"] == 34.0


# --------------------------------------------------------------------------
# micro totals
# --------------------------------------------------------------------------

def test_should_compute_micro_totals_over_unions_independently_of_pairing():
    """Concepts shared across differently-named sets still count in the micro total."""
    gold = [rs("g1", "Alpha", {1, 2}), rs("g2", "Beta", {3, 4})]
    generated = [rs("a1", "Zeta", {2, 3, 9})]
    pairing = pair_concept_sets(gold, generated, DEFAULT_THRESHOLDS)
    assert set(outcomes(pairing).values()) == {"no_counterpart"}

    micro = micro_totals(gold, generated)
    assert micro["gold_union"] == 4
    assert micro["generated_union"] == 3
    assert micro["intersection"] == 2
    assert micro["recall"] == 0.5
    assert round(micro["precision"], 4) == round(2 / 3, 4)
    assert micro["jaccard"] == 0.4


# --------------------------------------------------------------------------
# mode discipline
# --------------------------------------------------------------------------

def _cohort():
    return {
        "ConceptSets": [
            {
                "id": 0,
                "name": "Apixaban",
                "expression": {
                    "items": [
                        {"concept": {"CONCEPT_ID": 1}, "includeDescendants": True},
                        {"concept": {"CONCEPT_ID": 2}, "isExcluded": True},
                    ]
                },
            }
        ]
    }


def test_should_refuse_closure_mode_when_no_lookup_is_supplied():
    with pytest.raises(ValueError, match="closure"):
        resolve_cohort_sets(_cohort(), mode="closure", lookup=None)


def test_should_use_raw_item_ids_when_mode_is_raw():
    sets = resolve_cohort_sets(_cohort(), mode="raw", lookup=None)
    assert [s.concept_ids for s in sets] == [{1}]


def test_should_record_mode_in_report_output():
    gold = [rs("g1", "Apixaban", {1, 2})]
    generated = [rs("a1", "apixaban", {1, 2})]
    report = build_report("ARISTOTLE", "raw", gold, generated, DEFAULT_THRESHOLDS)
    assert report["mode"] == "raw"
    assert report["thresholds"]["name_strong"] == DEFAULT_THRESHOLDS.name_strong
    assert report["micro"]["jaccard"] == 1.0


def test_should_reject_unknown_mode_when_resolving_a_cohort():
    with pytest.raises(ValueError):
        resolve_cohort_sets(_cohort(), mode="approximate", lookup=None)
