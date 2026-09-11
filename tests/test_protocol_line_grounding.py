"""A criterion can claim more than the protocol line it was extracted from says.

`tests/test_criterion_protocol_line_provenance.py` put `protocolLine` on every stored
criterion so that "the line can be read next to what was claimed from it", and ends by
saying it is provenance only -- nothing reads it. This module is the reader.

The case that forced it is ARISTOTLE. `output/site_gap/2026-09-14/DELIVERY/
aristotle_treatment.circe.json` carries TWO ischemic-stroke exclusions:

    InclusionRules[14]  ConceptSet 26, window -7..0    <- protocol exclusion 18,
                                                         "Recent ischemic stroke
                                                         (within 7 days)"
    InclusionRules[13]  ConceptSet 25, window -9999..0 <- no protocol line at all

Rule 13's store criterion (exclusion id 24, "Prior ischemic stroke") carries the
`protocolLine` **"Prior"** -- one word, the left half of a split the extractor made
across `Recent ischemic stroke (within 7 days)`. Section 4.2.2 of
`data/papers/NCT00412984/nejmoa1107039_protocol.pdf` lists item 18 as the only stroke
exclusion; "Prior stroke, TIA or systemic embolus" is inclusion criterion 3(b), and the
delivered file emits it as InclusionRules[19] group G0. So rule 13 removes, for all time,
the patients rule 19 exists to admit.

What separates rule 13 from a correct criterion is NOT how short its line is. Measured
over the 251 emitted criteria of the six delivered trials, `protocolLine` naming-word
counts run 1 to 145 and the six known fabrications sit at 1, 3, 3, 3, 8 and 23 -- while a
cut at 3 words sweeps 35 criteria of which 31 are terse and correct (`Type 1 diabetes`,
`Diabetes mellitus`, `PCI planned`, `Planned major surgery`, `Calcitonin >=50 ng/L`).
Length is not the signal and this module does not use it.

What the check reads instead is whether the line names what the criterion claims, in the
two shapes the corpus actually shows:

  * `line-names-nothing-it-claims` -- no naming word of the criterion (its `sourceText`,
    `description` or `conceptSetName`) appears in its own `protocolLine`. CARMELINA
    exclusion 5 is the clearest: a `Total Bilirubin >= 1.5x ULN` leaf hung off a line
    that names ALT, AST and alkaline phosphatase and never says bilirubin.
  * `line-inside-the-name` -- the line's naming words are a strict subset of the
    criterion's own description, so the line contributes nothing the name did not
    already have. `"Prior"` inside `"Prior ischemic stroke"` is the only instance in the
    corpus, and it is rule 13.

This is a REPORT, not a refusal, and the false-positive population is why. The check
fires 21 times on the six delivered trials; nine carry a defect finding in
`output/site_gap/2026-09-14/conversion_audit.json` (ARISTOTLE exclusion 24,
CARMELINA exclusion 5, EMPA-REG inclusions 8-12, PLATO inclusion 8, LEADER
exclusion 5) and the other twelve are legitimate elaborations of an umbrella the
line does name -- `Acute coronary syndrome` decomposed
into STEMI / NSTEMI / unstable angina, `End-stage liver disease` into cirrhosis -- plus
one line truncated by `pdftotext` (EMPA-REG exclusion 8's eGFR) and one lay paraphrase
(PLATO exclusion 24, `blood clotting agents`). Refusing those would delete correct
criteria, which is the failure `_grounded_span` in `src/agents/planner/decomposer.py`
already refuses to commit for the same reason.

Known and stated miss: PLATO inclusion 4, `Coronary artery disease with LBBB`, was built
from a table's abbreviation legend (`CAD, Coronary artery disease; LBBB, left
bundle-branch block`). The legend repeats the entity's own words, so grounding cannot see
it. Five of the six known fabrications are named here; that one is not.
"""

from __future__ import annotations

import copy
import json
import pathlib

from src.utils.circe_lint import ungrounded_criteria

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "protocol_line_grounding_corpus.json"


def _corpus() -> dict:
    with FIXTURE.open(encoding="utf-8") as fh:
        return json.load(fh)


def _study(trial: str) -> dict:
    for study in _corpus()["studies"]:
        if study["trial"] == trial:
            return study
    raise KeyError(f"no study named {trial!r} in {FIXTURE}")


def _criteria(study: dict, role: str) -> list[dict]:
    """Rows live under `eligibility`, as they do in the store this was cut from.

    The fixture keeps that nesting on purpose. A first version of it flattened the two
    lists onto the study, every assertion below passed, and the gate pointed at the real
    delivery reported `0 of 0 emitted criteria` on all twelve files -- the check read
    nothing and said so in a sentence that reads like a clean result.
    """
    return study["eligibility"][f"{role}Criteria"]


def _expression(study: dict) -> dict:
    """The only part of a delivered file this check reads: the emission link.

    Restricting to emitted criteria is load-bearing, not tidiness. Over the same six
    trials eight NON-emitted criteria fire -- group labels whose `protocolLine` is empty,
    and `PLATO inclusion 32` whose line is the list header `>=2 of the following:` --
    and none of them reached a rule, so reporting them would bury the ones that did.
    """
    return {"_criterionConceptSetRefs": {key: 1 for key in study["emittedKeys"]}}


def _reported(trial: str) -> tuple[list[dict], str]:
    study = _study(trial)
    return ungrounded_criteria(_expression(study), study)


def _keys(records) -> set[tuple[str, int]]:
    return {(r["role"], r["id"]) for r in records}


def test_should_name_the_aristotle_all_time_stroke_exclusion_when_its_line_is_one_word():
    records, _ = _reported("ARISTOTLE")
    hit = [r for r in records if (r["role"], r["id"]) == ("exclusion", 24)]
    assert hit, (
        "the criterion behind InclusionRules[13] was not reported; its protocolLine is "
        f"one word and its name claims a whole clinical entity. reported: {_keys(records)}"
    )
    assert hit[0]["shape"] == "line-inside-the-name"
    assert hit[0]["protocolLine"] == "Prior"
    assert hit[0]["description"] == "Prior ischemic stroke"


def test_should_stay_silent_on_terse_but_correct_criteria():
    """Real corpus rows, each 2-3 naming words, each an exact reading of its line.

    These are the population a length threshold would wrongly catch: at <=3 naming words
    a cut takes 35 of the 251 emitted criteria and only 4 of them are fabrications.
    """
    terse = {
        "LEADER": [("exclusion", 31), ("inclusion", 42), ("inclusion", 6), ("exclusion", 9)],
        "PLATO": [("inclusion", 9), ("inclusion", 16), ("inclusion", 18)],
        "ARISTOTLE": [("exclusion", 22)],
    }
    for trial, expected_silent in terse.items():
        records, _ = _reported(trial)
        named = _keys(records)
        for key in expected_silent:
            assert key not in named, f"{trial} {key} is terse and correct but was reported"


def test_should_name_the_empa_reg_members_built_from_a_group_header():
    """Five members whose only line is the header `High cardiovascular risk`.

    Three of them -- hypertension, diabetes mellitus, hyperlipidemia -- appear nowhere in
    the protocol's definition of high cardiovascular risk; the other two coincide with
    protocol members but were not read from any line either.
    """
    records, _ = _reported("EMPA-REG")
    named = _keys(records)
    for cid in (8, 9, 10, 11, 12):
        assert ("inclusion", cid) in named, f"EMPA-REG inclusion {cid} was not reported"
    for record in records:
        if record["role"] == "inclusion" and record["id"] in (8, 9, 10, 11, 12):
            assert record["protocolLine"] == "High cardiovascular risk"
            assert record["shape"] == "line-names-nothing-it-claims"


def test_should_name_the_carmelina_bilirubin_leaf_whose_line_names_three_other_analytes():
    records, _ = _reported("CARMELINA")
    hit = [r for r in records if (r["role"], r["id"]) == ("exclusion", 5)]
    assert hit, "CARMELINA exclusion 5 (Elevated Total Bilirubin) was not reported"
    assert hit[0]["shape"] == "line-names-nothing-it-claims"
    assert "bilirubin" not in hit[0]["protocolLine"].lower()


def test_should_split_two_members_of_one_line_by_whether_the_line_names_them():
    """The control pair: PLATO inclusions 7 and 8 share the line `Chronic renal dysfunction`.

    Inclusion 7 is `Chronic Kidney Disease (CKD)` -- a reading of that line, and it
    shares the word `chronic` with it. Inclusion 8 is `Acute Kidney Injury (AKI)`, which
    the delivery audit calls the clinical opposite of the line and not in the criterion
    at all. One `protocolLine`, one emitted rule (InclusionRules[1], Type ANY over both),
    and the only thing separating the two members is whether the line names them -- so a
    check that fired on both, or on neither, would be indistinguishable from one reading
    the rule rather than the line.
    """
    records, _ = _reported("PLATO")
    named = _keys(records)
    assert ("inclusion", 8) in named, "Acute Kidney Injury is not named by its own line"
    assert ("inclusion", 7) not in named, "Chronic Kidney Disease IS named by its own line"


def test_should_not_report_a_criterion_the_delivered_file_never_emitted():
    study = _study("PLATO")
    empty = ungrounded_criteria({"_criterionConceptSetRefs": {}}, study)[0]
    assert empty == [], f"nothing was emitted, so nothing can be reported: {empty}"


def test_should_say_in_the_summary_when_the_file_carries_no_emission_link():
    """A check whose only output is silence cannot be told from one that never ran."""
    study = _study("PLATO")
    records, summary = ungrounded_criteria({}, study)
    assert records == []
    assert "_criterionConceptSetRefs" in summary


def test_should_report_a_criterion_carrying_no_protocol_line_as_a_gap_not_a_claim():
    """An absent line is a provenance gap; the check cannot judge what it cannot read."""
    study = copy.deepcopy(_study("ARISTOTLE"))
    for criterion in _criteria(study, "exclusion"):
        if criterion["id"] == 24:
            criterion["protocolLine"] = ""
    records, summary = ungrounded_criteria(_expression(study), study)
    assert ("exclusion", 24) not in _keys(records)
    assert "1 emitted criterion carries no protocolLine" in summary


def test_should_read_criteria_from_the_eligibility_block_the_store_nests_them_in():
    """The shape guard. A study whose rows sit anywhere else must report nothing.

    Flattening the two criteria lists onto the study is the exact mistake that made an
    earlier version of this module green while the gate read `0 of 0` on all twelve
    delivered files.
    """
    study = _study("ARISTOTLE")
    flattened = {
        "emittedKeys": study["emittedKeys"],
        "inclusionCriteria": _criteria(study, "inclusion"),
        "exclusionCriteria": _criteria(study, "exclusion"),
    }
    records, summary = ungrounded_criteria(_expression(flattened), flattened)
    assert records == []
    assert "eligibility" in summary

    nested, _ = _reported("ARISTOTLE")
    assert nested, "the same rows under `eligibility` must be read"


def test_should_hold_the_corpus_wide_count_so_the_check_cannot_widen_unnoticed():
    """21 records over the six delivered trials, at the counts measured per trial.

    A bound, not a target. The check is report-only precisely because these 21 are not
    21 defects; freezing the number is what makes a later widening visible instead of
    arriving as extra noise in a delivery report.
    """
    expected = {
        "LEADER": 5,
        "PLATO": 2,
        "ARISTOTLE": 1,
        "EMPA-REG": 6,
        "CARMELINA": 4,
        "CAROLINA": 3,
    }
    observed = {trial: len(_reported(trial)[0]) for trial in expected}
    assert observed == expected
    assert sum(observed.values()) == 21
