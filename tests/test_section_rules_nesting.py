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
    assert len(_members(head, depth=2)) == 6 + 3 + 4
    lines = _rendered(got)
    assert "1.1.1 Myocardial infarction (> 6 weeks prior to informed consent)" in lines
    assert any(line.startswith("1.4.4 Current* LDL cholesterol") for line in lines)


def test_should_nest_aristotle_stroke_risk_factors_under_item_3_and_not_under_the_preamble():
    got = _parse("ARISTOTLE_01")
    head = _criterion(got, "One or more of the following risk factor(s) for stroke:")
    assert [m[:25] for m in _members(head)] == [
        "Age 75 years or older", "Prior stroke, TIA or syste", "Either symptomatic conges",
        "Diabetes mellitus", "Hypertension requiring ph",
    ]
    # "For entry into the study, the following criteria MUST be met." ends in a full stop, not a colon:
    # the numbered items after it are its siblings, not its members.
    assert "Age ≥ 18 years" in got
    assert any(c.startswith("Women of childbearing potential") for c in got)


def test_should_nest_leader_cohort_members_and_the_renal_sub_bullets():
    got = _parse("LEADER_01")
    prior = _criterion(got, "Prior cardiovascular disease cohort:")
    no_prior = _criterion(got, "No Prior cardiovascular disease group:")
    assert len(_members(prior)) == 8 and _members(prior)[-1] == "Chronic renal failure:"
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
    flat = FLAT[name]
    # the square bullet LEADER sets its third level with is a marker now, so it leaves the text
    expected = [line.removeprefix(" ") for line in flat]
    assert _flat(_parse(name)) == expected


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
