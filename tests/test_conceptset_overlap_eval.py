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
    MACRO_RESOLUTION_FLOOR,
    ResolvedSet,
    build_report,
    delta_verdict,
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


def test_should_fold_punctuation_between_a_letter_and_a_digit_when_normalising():
    """'DPP-4' and 'DPP4' are the same class and must yield the same token.

    Splitting on every non-alphanumeric gave {dpp, 4} against {dpp4}, which
    share nothing at all -- see the CARMELINA mispairing below.
    """
    assert normalize_set_name("DPP-4 inhibitor") == normalize_set_name("DPP4 inhibitor")
    assert normalize_set_name("SGLT-2 inhibitors") == normalize_set_name("SGLT2 inhibitors")
    # a hyphen that does not sit between a letter and a digit is untouched
    assert normalize_set_name("CKD 4-ESRD") == frozenset({"ckd", "4", "esrd"})


def test_should_fold_a_trailing_plural_when_normalising():
    assert normalize_set_name("Sulfonylureas") == normalize_set_name("Sulfonylurea")
    assert normalize_set_name("inhibitors") == normalize_set_name("inhibitor")
    # 'ss' / 'us' / 'is' endings are not plurals and must survive intact
    assert normalize_set_name("weight loss") == frozenset({"weight", "loss"})
    assert normalize_set_name("diabetes mellitus") == frozenset({"diabete", "mellitus"})


def test_should_score_the_observed_dpp4_gold_higher_against_gliptins_than_against_sglt2():
    """The exact three names from scoped_atc_fix.json, CARMELINA.

    Under the plain split these scored 0.000 and 0.250 respectively, so the
    scorer handed gold DPP4 to the SGLT-2 set and read recall 0.07.
    """
    gold = "[TROY intervention] DPP4 inhibitors"
    assert name_similarity(gold, "DPP-4 inhibitor") == 1.0
    assert name_similarity(gold, "DPP-4 inhibitor") > name_similarity(gold, "SGLT-2 inhibitors")


def test_should_pair_the_observed_dpp4_gold_with_the_gliptin_set_not_the_sglt2_set():
    """Reproduces the mispairing mechanism, not just the similarity number.

    SGLT-2 needs only a single shared concept to turn its 0.25 name score into
    name evidence, which outranks the gliptin set's overlap-only match.
    """
    gold = [rs("g1", "[TROY intervention] DPP4 inhibitors", range(0, 10))]
    generated = [
        rs("a1", "SGLT-2 inhibitors", {9, 80, 81}),  # one shared concept
        rs("a2", "DPP-4 inhibitor", range(0, 7)),  # the real counterpart
    ]
    pairing = pair_concept_sets(gold, generated, DEFAULT_THRESHOLDS)
    assert partners(pairing)["[TROY intervention] DPP4 inhibitors"] == "DPP-4 inhibitor"
    assert outcomes(pairing)["[TROY intervention] DPP4 inhibitors"] == "matched_by_name"


def test_should_match_the_observed_sulfonylurea_gold_that_was_left_without_a_counterpart():
    """CARMELINA gold sat in unmatched_gold while 'Sulfonylurea' sat in unmatched_generated."""
    assert name_similarity("[TROY intervention] Sulfonylureas", "Sulfonylurea") == 1.0


def test_should_not_let_the_generic_word_disease_carry_a_name_match():
    """Observed in EMPA-REG once 'diseases' folded to 'disease'.

    Gold 'diseases of the blood' then scored 0.333 against generated 'Chronic
    disease' -- beating its real counterpart 'Unspecified blood dyscrasia' at
    0.250 -- and the pair's recall fell from 0.066 to 0.005. 'disease' names a
    category, not a concept, exactly like the 'atc' vocabulary label.
    """
    gold = "[TROY condition] diseases of the blood"
    assert name_similarity(gold, "Chronic disease") == 0.0
    assert name_similarity(gold, "Unspecified blood dyscrasia") > name_similarity(gold, "Chronic disease")


def test_should_still_count_a_category_noun_that_is_not_the_only_shared_token():
    """The narrow rule must not cost the pairs that legitimately share 'disease'.

    Dropping 'disease' from the token set entirely broke EMPA-REG gold
    'coronary atherosis and other chronic ischemic heart disease' away from
    'Coronary Artery Disease', a real pair at recall 1.00.
    """
    gold = "[TROY condition] coronary atherosis and other chronic ischemic heart disease"
    assert name_similarity(gold, "Coronary Artery Disease") >= DEFAULT_THRESHOLDS.name_weak


def test_should_refuse_a_generic_only_name_match_for_the_observed_chronic_disease_set():
    """'Chronic disease' is large enough to overlap anything, so weak name
    evidence plus non-zero jaccard let it claim unrelated golds."""
    gold = [rs("g1", "[TROY condition] peripheral arterial disease", range(0, 300))]
    generated = [rs("a1", "Chronic disease", range(200, 1400))]
    pairing = pair_concept_sets(gold, generated, DEFAULT_THRESHOLDS)
    assert outcomes(pairing)["[TROY condition] peripheral arterial disease"] != "matched_by_name"


def test_should_give_no_name_evidence_when_only_a_drug_class_noun_is_shared():
    """Folding the plural makes generic drug-class names collide on one token.

    Observed in CAROLINA: gold 'alpha-glucosidase inhibitor' and generated
    'SGLT2 inhibitors' share only the class noun once 'inhibitors' is folded.
    Two different drug classes are not the same set, so this is not evidence at
    all -- the class noun still counts once a real token matches too.
    """
    assert name_similarity("[TROY drug] alpha-glucosidase inhibitor", "SGLT2 inhibitors") == 0.0
    assert name_similarity("[TROY drug] anti-obesity drugs", "investigational drug") == 0.0
    # the same noun still contributes when a discriminating token matches as well
    assert name_similarity("[TROY intervention] DPP4 inhibitors", "DPP-4 inhibitor") == 1.0


def test_should_refuse_a_shared_class_noun_pair_when_the_concepts_do_not_overlap():
    gold = [rs("g1", "[TROY drug] alpha-glucosidase inhibitor", {1, 2, 3})]
    generated = [rs("a1", "SGLT2 inhibitors", {80, 81})]
    pairing = pair_concept_sets(gold, generated, DEFAULT_THRESHOLDS)
    assert outcomes(pairing)["[TROY drug] alpha-glucosidase inhibitor"] == "no_counterpart"


def test_should_leave_a_numeric_threshold_qualifier_unmatched():
    """Documents a case this normalisation deliberately does NOT fix.

    LEADER gold 'Ankle brachial index less than 0.9' scores 0.43 against
    generated 'Ankle-brachial index' -- below name_strong -- because the
    threshold words stay in the union. An earlier draft folded '0' onto 'than'
    and pushed this over 0.50, which is the right pair for the wrong reason.
    Stripping numeric qualifiers is a separate change with its own evidence.
    """
    similarity = name_similarity(
        "[TROY condition] Ankle brachial index less than 0.9", "Ankle-brachial index"
    )
    assert similarity < DEFAULT_THRESHOLDS.name_strong


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


# --------------------------------------------------------------------------
# plan-045: delta resolution floor
# --------------------------------------------------------------------------

def test_single_draw_delta_below_floor_is_unresolved():
    """A single-draw |Δmacro| < 0.02 must not be printed as a quality claim.

    Motivation (plan-045): the reranker picked SNOMED-finding 4/5 vs LOINC 1/5
    at temperature 0 on the same candidate pool.  Control and baseline then agreed
    ±0.001 — not stability, the same face of the coin.  The two wrong attributions
    that followed came from reading this as a settled result.
    """
    assert delta_verdict(0.019, n_draws=1) == "unresolved"
    assert delta_verdict(-0.019, n_draws=1) == "unresolved"
    assert delta_verdict(0.0, n_draws=1) == "unresolved"
    # exact floor value — at the boundary counts as a claim
    assert delta_verdict(MACRO_RESOLUTION_FLOOR, n_draws=1) != "unresolved"
    assert delta_verdict(-MACRO_RESOLUTION_FLOOR, n_draws=1) != "unresolved"


def test_single_draw_delta_at_or_above_floor_is_a_directional_claim():
    assert delta_verdict(0.02, n_draws=1) == "improved"
    assert delta_verdict(-0.02, n_draws=1) == "regressed"
    assert delta_verdict(0.5, n_draws=1) == "improved"
    assert delta_verdict(-0.5, n_draws=1) == "regressed"


def test_six_draws_below_floor_is_labeled_below_floor_not_unresolved():
    """Six draws may still report the number, but the floor label must accompany it."""
    verdict = delta_verdict(0.008, n_draws=6)
    assert verdict == "below floor"
    assert verdict != "unresolved"
    assert verdict != "improved"


def test_six_draws_at_or_above_floor_is_still_a_directional_claim():
    assert delta_verdict(0.03, n_draws=6) == "improved"
    assert delta_verdict(-0.03, n_draws=6) == "regressed"


def test_the_coin_flip_case_that_caused_two_wrong_attributions():
    """The +0.008 six-trial recall result from retrieval-preference-scale.md.

    That delta sat under the ±0.02 floor, so recall did not move.  The harness
    must refuse to label it 'improved', whether from a single draw or six draws.
    """
    assert delta_verdict(0.008, n_draws=1) == "unresolved"
    assert delta_verdict(0.008, n_draws=6) == "below floor"
    # Neither outcome is 'improved' — the delta is not a quality claim
    assert delta_verdict(0.008, n_draws=1) not in ("improved", "regressed")
    assert delta_verdict(0.008, n_draws=6) not in ("improved", "regressed")


def test_delta_verdict_floor_constant_matches_documented_value():
    """The floor is pinned at 0.02 and must not drift silently."""
    assert MACRO_RESOLUTION_FLOOR == 0.02
