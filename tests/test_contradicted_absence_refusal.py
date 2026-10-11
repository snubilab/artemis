"""An absence that forbids a concept a mandatory presence names is refused, not emitted.

The measured case, 2026-10-11 LEADER/PLATO/ARISTOTLE rebuild, ARISTOTLE treatment and
comparator (``output/site_gap/2026-10-11_alltrials/DELIVERY``)::

    #3 'AF/Flutter documentation'          >=1 ConditionOccurrence cs3  [-365, 0]
        {313217 AF, 314665 flutter, 4064452 ECG: AF, 4111700 VF and flutter}
    #4 'AF/Flutter documentation details'  >=1 ConditionOccurrence cs4  [-9999, 0]
        {314665 flutter, 4065288 EKG: flutter}
    #7 'Reversible cause AF/Flutter'       ==0 ConditionOccurrence cs14 [-9999, 0]
        {313217 AF, 314665 flutter, 4065288 EKG: flutter}

The protocol line of #7 is "Atrial fibrillation or flutter due to reversible causes"; the
mapper was handed the criterion's name and returned the head condition. A trial that
requires AF/flutter then forbids every AF/flutter record: check (y) fails on #7 vs #3 and
check (t) on #7 vs #4. The absence is the half that cannot be what the protocol meant --
a concept the presence lists as qualifying cannot also be one the protocol excludes -- so
it is refused at build time and recorded as criterion loss, rather than shipped.

DB-free: ``PrefetchedVocabulary`` over the measured relations (synthea23m: none of the five
ids is an ancestor of another).
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from src.services.conceptset_closure import PrefetchedVocabulary

AF, FLUTTER, ECG_AF, VF_FLUTTER, EKG_FLUTTER = 313217, 314665, 4064452, 4111700, 4065288
APIXABAN = 43013024

_IDS = (AF, FLUTTER, ECG_AF, VF_FLUTTER, EKG_FLUTTER, APIXABAN)
VOCAB = PrefetchedVocabulary(
    concept_invalid_reason={c: None for c in _IDS},
    ancestor_edges={c: {c} for c in _IDS},
)


def _item(cid: int) -> dict[str, Any]:
    return {"concept": {"CONCEPT_ID": cid, "CONCEPT_NAME": f"c{cid}"},
            "isExcluded": False, "includeDescendants": True, "includeMapped": False}


def _set(set_id: int, name: str, *ids: int) -> dict[str, Any]:
    return {"id": set_id, "name": name, "expression": {"items": [_item(i) for i in ids]}}


def _entry(codeset: int, occurrence: tuple[int, int], start: int) -> dict[str, Any]:
    return {
        "Criteria": {"ConditionOccurrence": {"CodesetId": codeset}},
        "StartWindow": {"Start": {"Days": start, "Coeff": -1}, "End": {"Days": 0, "Coeff": 1}},
        "RestrictVisit": False,
        "IgnoreObservationPeriod": False,
        "Occurrence": {"Type": occurrence[0], "Count": occurrence[1]},
    }


def _rule(name: str, *entries: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "expression": {"Type": "ALL", "CriteriaList": list(entries),
                                         "DemographicCriteriaList": [], "Groups": []}}


PRESENT, ABSENT = (2, 1), (0, 0)


def _aristotle(absence_ids=(AF, FLUTTER, EKG_FLUTTER)) -> dict[str, Any]:
    return {
        "ConceptSets": [
            _set(0, "apixaban", APIXABAN),
            _set(3, "AF/Flutter documentation", AF, FLUTTER, ECG_AF, VF_FLUTTER),
            _set(4, "AF/Flutter documentation details", FLUTTER, EKG_FLUTTER),
            _set(14, "Reversible cause AF/Flutter", *absence_ids),
        ],
        "PrimaryCriteria": {"CriteriaList": [{"DrugExposure": {"CodesetId": 0}}]},
        "InclusionRules": [
            _rule("AF/Flutter documentation", _entry(3, PRESENT, 365)),
            _rule("AF/Flutter documentation details", _entry(4, PRESENT, 9999)),
            _rule("Reversible cause AF/Flutter", _entry(14, ABSENT, 9999)),
        ],
        "_criterionConceptSetRefs": {"inclusion:4": 3, "inclusion:5": 4, "exclusion:7": 14},
    }


def _refuse(cohort: dict[str, Any]) -> list[dict[str, Any]]:
    from src.services.contradicted_absence_refusal import refuse_contradicted_absences

    return refuse_contradicted_absences(cohort, VOCAB)


def test_should_remove_the_absence_when_it_forbids_concepts_a_mandatory_presence_names():
    cohort = _aristotle()
    records = _refuse(cohort)

    assert [r["name"] for r in cohort["InclusionRules"]] == [
        "AF/Flutter documentation", "AF/Flutter documentation details",
    ]
    assert len(records) == 1
    record = records[0]
    assert record["rule"] == "Reversible cause AF/Flutter"
    assert record["ruleIndex"] == 2
    assert record["ruleAfter"] is None
    assert record["outcome"] == "rule-removed"
    assert record["codesetId"] == 14
    assert record["criterionKeys"] == ["exclusion:7"]
    assert record["presenceRule"] == "AF/Flutter documentation"
    assert sorted(record["namedConceptIds"]) == [AF, FLUTTER]


def test_should_leave_the_cohort_alone_when_the_absence_forbids_nothing_the_presence_names():
    cohort = _aristotle(absence_ids=(VF_FLUTTER,))
    # VF_FLUTTER is a named member of #3, so take it out of the presence for this case.
    cohort["ConceptSets"][1] = _set(3, "AF/Flutter documentation", AF, FLUTTER, ECG_AF)
    before = deepcopy(cohort)

    assert _refuse(cohort) == []
    assert cohort == before


def test_should_decline_when_the_absence_shares_its_rule_with_other_criteria():
    """Removing a multi-criterion rule would take criteria with it that nothing refuted."""
    cohort = _aristotle()
    cohort["ConceptSets"].append(_set(20, "Other exclusion", APIXABAN))
    cohort["InclusionRules"][2]["expression"]["CriteriaList"].append(_entry(20, ABSENT, 9999))
    before = deepcopy(cohort)

    assert _refuse(cohort) == []
    assert cohort == before


def test_should_clear_both_lint_findings_once_the_absence_is_refused():
    from src.utils.circe_lint import (
        closure_subsumed_presence_criteria,
        forbidden_explicit_presence_criteria,
    )

    cohort = _aristotle()
    assert forbidden_explicit_presence_criteria(cohort, VOCAB)
    assert closure_subsumed_presence_criteria(cohort, VOCAB)

    _refuse(cohort)

    assert forbidden_explicit_presence_criteria(cohort, VOCAB) == []
    assert closure_subsumed_presence_criteria(cohort, VOCAB) == []


# --------------------------------------------------------------------------
# The gate and the export read the record: reconciled for check (b), booked as loss
# --------------------------------------------------------------------------

def _refused_file() -> dict[str, Any]:
    cohort = _aristotle()
    from src.utils.circe_lint import CONTRADICTED_ABSENCE_REFUSALS_KEY

    cohort[CONTRADICTED_ABSENCE_REFUSALS_KEY] = _refuse(cohort)
    return cohort


def test_should_move_the_store_rule_set_forward_when_a_refusal_is_recorded():
    from scripts.verify_circe_delivery import reconcile_dropped_rules

    store = ["AF/Flutter documentation", "AF/Flutter documentation details",
             "Reversible cause AF/Flutter"]
    expected, violations = reconcile_dropped_rules(_refused_file(), store)

    assert violations == []
    assert sorted(expected) == sorted(store[:2])


def test_should_book_every_refusal_as_criterion_loss_in_the_accounting():
    from scripts.verify_circe_delivery import criterion_accounting

    violations, summary = criterion_accounting(_refused_file(), {})

    loss = [v for v in violations if "Reversible cause AF/Flutter" in v]
    assert len(loss) == 1
    assert "lost" in loss[0]
    assert "1 refused as contradicting a mandatory presence" in summary


def test_should_fail_a_refusal_record_whose_rule_is_still_in_the_file():
    from scripts.verify_circe_delivery import contradicted_absence_refusal_violations
    from src.utils.circe_lint import CONTRADICTED_ABSENCE_REFUSALS_KEY

    cohort = _refused_file()
    assert contradicted_absence_refusal_violations(cohort) == []

    cohort["InclusionRules"].append(_rule("Reversible cause AF/Flutter", _entry(14, ABSENT, 9999)))
    assert any("still carries it" in v for v in contradicted_absence_refusal_violations(cohort))

    cohort = _refused_file()
    cohort[CONTRADICTED_ABSENCE_REFUSALS_KEY][0]["presenceRule"] = "No such rule"
    assert any("does not carry" in v for v in contradicted_absence_refusal_violations(cohort))


def test_should_record_the_key_present_and_empty_when_no_absence_meets_a_presence():
    """The export wiring: an arm with nothing to refuse still carries the key, DB-free."""
    from src.services.tte_service import TTEService
    from src.utils.circe_lint import CONTRADICTED_ABSENCE_REFUSALS_KEY

    cohort = _aristotle()
    cohort["InclusionRules"] = cohort["InclusionRules"][:2]
    TTEService._refuse_contradicted_absences(TTEService.__new__(TTEService), cohort)

    assert cohort[CONTRADICTED_ABSENCE_REFUSALS_KEY] == []
