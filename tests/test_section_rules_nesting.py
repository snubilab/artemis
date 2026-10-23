"""A listed member sits under the item it is listed under, read from the list's FORMAT only.

The fixtures are the production rendering (plain ``pdftotext``, no ``-layout``) of each study's list
capture, exactly as ``extract_eligibility_from_text`` hands it to ``_regex_parse_criteria`` at e5f423a.
``flat_e5f423a.json`` is what e5f423a returned for them: every line a separate top-level item.

Nesting is carried by the marker scheme ("1)" items then "a)" items, "" bullets then "o" bullets), by
a bare letter that continues the "a, b, c" sequence, and by the colon that ends the line a list hangs
from. Never by the words of a line: the OR / AND / "at least two" reading stays with Agent 1, which reads
the header line itself.
"""
import json
from pathlib import Path

import pytest

from src.agents.agent1.parser import LogicDecomposer
from src.agents.agent1.section_rules import _regex_parse_criteria

FIXTURES = Path(__file__).parent / "fixtures" / "section_nesting"
FLAT = json.loads((FIXTURES / "flat_e5f423a.json").read_text())


def _parse(name: str) -> list[str]:
    return _regex_parse_criteria((FIXTURES / f"{name}.txt").read_text())


def _rendered(criteria: list[str]) -> list[str]:
    """The numbered lines Agent 1 reads, without the two-space indent."""
    return [line.strip() for line in LogicDecomposer._format_criteria(criteria).split("\n")]


def _criterion(criteria: list[str], header_start: str) -> str:
    hits = [c for c in criteria if c.startswith(header_start)]
    assert len(hits) == 1, (header_start, [c[:60] for c in criteria])
    return hits[0]


def _members(criterion: str, depth: int = 1) -> list[str]:
    """Lines of a criterion at exactly ``depth`` (1 = listed directly under its header)."""
    out = []
    for line in criterion.split("\n")[1:]:
        if len(line) - len(line.lstrip("\t")) == depth:
            out.append(line.lstrip("\t"))
    return out


def _flat(criteria: list[str]) -> list[str]:
    return [line.lstrip("\t") for c in criteria for line in c.split("\n")]


def test_should_nest_carolina_a_to_d_and_their_bullets_when_the_marker_scheme_changes():
    got = _parse("CAROLINA_02")
    head = _criterion(got, "High risk of CV events defined as any one (or more) of A), B), C) or D):")
    assert [m[:30] for m in _members(head)] == [
        "Previous Vascular Disease:",
        "Evidence of vascular related e",
        "Age ≥ 70 years (at Visit 1a)",
        "At least two of the following ",
    ]
    # A) has 6 bullets plus "arm blood pressure ratio < 0.90)", a wrap cut at "ankle:" (as at e5f423a) that stays
    # under A) rather than ending the list
    assert len(_members(head, depth=2)) == 7 + 3 + 4
    lines = _rendered(got)
    assert "1.1.1 Myocardial infarction (> 6 weeks prior to informed consent)" in lines
    assert any(line.startswith("1.4.4 Current* LDL cholesterol") for line in lines)


def test_should_nest_aristotle_stroke_risk_factors_under_item_3_and_not_under_the_preamble():
    got = _parse("ARISTOTLE_01")
    head = _criterion(got, "One or more of the following risk factor(s) for stroke:")
    assert [m[:20] for m in _members(head)] == [
        "Age 75 years or olde", "Prior stroke, TIA or", "Either symptomatic c",
        "Diabetes mellitus", "Hypertension requiri",
    ]
    # "For entry into the study, the following criteria MUST be met." ends in a full stop, not a colon:
    # the numbered items after it are its siblings, not its members.
    assert "Age ≥ 18 years" in got
    assert any(c.startswith("Women of childbearing potential") for c in got)


def test_should_nest_leader_cohort_members_and_the_renal_sub_bullets():
    got = _parse("LEADER_01")
    prior = _criterion(got, "Prior cardiovascular disease cohort:")
    no_prior = _criterion(got, "No Prior cardiovascular disease group:")
    # ">50% stenosis ..." rides in the line before it, as at e5f423a (a symbol-led line after no stop is a wrap)
    assert len(_members(prior)) == 7 and _members(prior)[-1] == "Chronic renal failure:"
    assert [m[:10] for m in _members(prior, depth=2)] == ["eGFR <60 m", "eGFR <60 m"]
    assert [m[:20] for m in _members(no_prior)] == [
        "Microalbuminuria or ", "Hypertension and lef", "Left ventricular sys", "Ankle-brachial index",
    ]


def test_should_keep_every_carmelina_high_risk_member_inside_criterion_8():
    got = _parse("CARMELINA_01")
    head = _criterion(got, "High risk of CV events (I and/or II):")
    assert _members(head)[0].startswith("Albuminuria (UACR ≥ 30 mg/g creatinine")
    assert _members(head, depth=2)[:2] == [
        "Confirmed history of MI (> 2 months prior to Visit 1)",
        "Advanced coronary artery disease, defined by any one of the following:",
    ]
    for fragment in ("Left main stem coronary artery", "High-risk single-vessel coronary artery disease",
                     "a positive stress echocardiogram", "Patient discharged from hospital",
                     "History of ischemic or haemorrhagic stroke", "Presence of carotid artery disease",
                     "Presence of peripheral artery disease", "Evidence of impaired renal function",
                     "with an eGFR:15- <45", "with an eGFR ≥ 45-75"):
        assert fragment in head, fragment


def test_should_nest_plato_lettered_risk_factors_under_one_of_the_following():
    got = _parse("PLATO_01")
    head = _criterion(got, "One of the following:")
    assert [m[:15] for m in _members(head)][:4] == [
        "≥60 y of age", "Previous MI or ", "CAD with ≥50% s", "Previous ischem",
    ]


@pytest.mark.parametrize("name", sorted(FLAT))
def test_should_lose_no_line_of_text_when_lines_are_nested(name):
    """Every word e5f423a passed on is still there, in order; only list markers leave (CARMELINA's bare "a"/"b",
    LEADER's private-use square bullet), because they are read as markers now."""
    old, new = " ".join(FLAT[name]).split(), " ".join(_flat(_parse(name))).split()
    removed, at = [], 0
    for word in old:
        if at < len(new) and new[at] == word:
            at += 1
        else:
            removed.append(word)
    assert at == len(new), "a word appeared that e5f423a did not pass on"
    assert all(len(word) == 1 for word in removed), removed


@pytest.mark.parametrize("name", ["CAROLINA_04", "LEADER_02", "PLATO_02"])
def test_should_leave_a_list_with_one_level_exactly_as_before(name):
    assert _parse(name) == FLAT[name]


def test_should_number_members_k_j_and_their_members_k_j_m():
    criteria = ["Age ≥ 18", "Header:\n\tA\n\t\tA1\n\t\tA2\n\tB", "Last"]
    assert _rendered(criteria) == [
        "1. Age ≥ 18", "2. Header:", "2.1 A", "2.1.1 A1", "2.1.2 A2", "2.2 B", "3. Last",
    ]


def test_should_render_a_criterion_with_no_members_byte_for_byte_as_before():
    criteria = ["Age ≥ 18 years", "HbA1c ≥ 7.0%"]
    assert LogicDecomposer._format_criteria(criteria) == "  1. Age ≥ 18 years\n  2. HbA1c ≥ 7.0%"


# A wrapped line is read as a wrap by the punctuation the line before it was cut at, never by its words. Two cuts
# reopened a wrapped line as a new item at 3a253a4 whatever its first letter: a line ending in a comma (the item has
# not ended) and a line that opened a bracket it did not close (the item cannot end inside the bracket).


def test_should_keep_plato_tia_line_inside_item_d_when_the_line_before_ends_in_a_comma():
    got = _parse("PLATO_01")
    head = _criterion(got, "One of the following:")
    assert _members(head) == [
        "≥60 y of age",
        "Previous MI or CABG",
        "CAD with ≥50% stenosis in ≥2 vessels",
        "Previous ischemic stroke, TIA (hospital-based diagnosis), carotid stenosis (≥50%), or cerebral "
        "revascularization",
        "Diabetes mellitus",
        "Peripheral artery disease",
        "Chronic renal dysfunction",
    ]
    # the unmarked footnote after (g) opens with a capital after a full stop: it is not a member
    assert any(c.startswith("Urinary and/or blood pregnancy tests") for c in got)


def test_should_keep_carolina_exclusions_whole_when_a_line_is_cut_inside_a_bracket():
    got = _parse("CAROLINA_04")
    assert any(c.startswith("Any history and/or current treatment with other antidiabetic drugs (e.g. rosiglitazone, "
                            "pioglitazone, GLP-1 analogue/agonists, DPP-IV inhibitors or any insulin) prior") for c in got)
    assert any(c.startswith("Uncontrolled hyperglycaemia with a glucose level >240 mg/dl (>13.3 mmol/L) after an "
                            "overnight fast") for c in got)
    assert any(c.startswith("Current treatment with systemic corticosteroids") and "steroids (e.g. for asthma/COPD) is "
               "no exclusion criterion" in c for c in got)
    assert not [c for c in got if c.startswith(("rosiglitazone", "mmol/L)", "for asthma"))]


def test_should_keep_empa_reg_egfr_whole_when_the_wrap_inside_its_bracket_opens_with_a_capital():
    got = _parse("EMPA-REG_01")
    assert any("(according to the Modification of Diet in Renal Disease equation) at screening" in c for c in got)
    assert not [c for c in got if c.startswith("Diet in Renal Disease")]


def test_should_keep_aristotle_and_carmelina_wraps_after_a_comma_or_inside_a_bracket():
    assert any("(e.g. prosthetic mechanical heart valve)" in c for c in _parse("ARISTOTLE_02"))
    assert any("on a rhythm strip, Holter recording, or intracardiac electrogram" in c for c in _parse("ARISTOTLE_01"))
    assert any("by coronary angiography, MRI angiography or CT angiography" in c for c in _parse("CARMELINA_01"))


def test_should_still_open_an_item_at_a_capital_after_a_full_stop_or_a_marker():
    got = _regex_parse_criteria("Age ≥ 18 years (at screening).\nBody mass index ≤ 45\n- Wrapped list item (one,\n"
                                "- Next item, opens at its marker")
    assert got == ["Age ≥ 18 years (at screening)", "Body mass index ≤ 45", "Wrapped list item (one,",
                   "Next item, opens at its marker"]
