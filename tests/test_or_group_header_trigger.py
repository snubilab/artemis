"""Which lines open an OR group, and which only look like they do.

`_collapse_hierarchical_groups` folds a parent header plus its children into one
`[OR-GROUP]` string so that Circe emits an ANY node instead of AND-ing the
alternatives. The trigger used to fire on a bare quantifier phrase anywhere in a
line, which cannot tell "any of the following:" from "any of the components".
CAROLINA's exclusion criterion 10, "known hypersensitivity to any of the
components", therefore swallowed criteria 11-20 as ten fabricated alternatives
and turned ten independent exclusions into one.

These call `_collapse_hierarchical_groups` directly. `_parse_criteria_items`
invokes a real LLM for input over 200 characters, so it must not be used here.
"""
import pytest

from src.agents.agent1.pubmed_fetcher import _collapse_hierarchical_groups


MUST_FIRE = [
    "One or more of the following risk factor(s) for stroke:",
    "at least 1 of the following:",
    "at least one of the following:",
    "≥1 of the following:",
    ">=1 of the following:",
    "Patients must have any of the following:",
    "Documented history of any of the below",
    "Meets at least one of these criteria:",
    "age >=50 and >=1 of:",
    "defined by any of the following:",
    "either of the following:",
    "any one of the following:",
    "Clinical manifestations of heart failure including at least one of",
    "meets any of these criteria:",
    # The cardinality is not always one, and the numeral is not always adjacent
    # to "of". Both are CAROLINA's, verbatim from the protocol supplement.
    "D) At least two of the following CV risk factors:",
    "At least three of the following:",
    "High risk of CV events defined as any one (or more) of A), B), C) or D):",
]

MUST_NOT_FIRE = [
    "10. known hypersensitivity to any of the components",
    "known hypersensitivity to any of the excipients",
    "Use of any of the prohibited medications listed in Appendix 2",
    "time to first occurrence of any of the adjudicated components of the primary",
    "Subjects, Investigators, members of any of the administrative and adjudicating",
    "Each subject who meets the inclusion criteria and does not meet any of the exclusion",
    "measurements, at least one of which should be performed after an overnight fast at the",
    "Boehringer Ingelheim International GmbH or one or more of its affiliated companies.",
    "Many of the subjects randomized to the study",
    "any of these products are part of your normal diet.",
    "criteria of acute MI (NSTEMI or STEMI). If neither of these",
    "randomization to first occurrence of any of the components of each secondary efficacy",
    # Widening the numeral must not turn every counted noun into a list header.
    # "of" still has to follow the numeral, and this line is CAROLINA's too --
    # it sits inside inclusion criterion A) as ordinary prose.
    "Documented coronary artery disease (>=50% in at least two major coronary",
    "in two of three unrelated specimens in previous 12 months prior Visit 1a",
]


def _collapses(header: str) -> bool:
    """Whether ``header`` followed by two children produces an OR group.

    :param header: the candidate parent line.
    :returns: True when the collapse fired.
    """
    text = f"{header}\na) first child criterion\nb) second child criterion"
    return _collapse_hierarchical_groups(text).splitlines()[0].startswith("[OR-GROUP]")


@pytest.mark.parametrize("header", MUST_FIRE)
def test_should_open_or_group_when_header_announces_a_list(header):
    assert _collapses(header)


@pytest.mark.parametrize("line", MUST_NOT_FIRE)
def test_should_not_open_or_group_when_quantifier_binds_a_noun(line):
    assert not _collapses(line)


def test_should_not_swallow_independent_exclusions_after_hypersensitivity_line():
    """CAROLINA's real shape: three unrelated exclusions, none an alternative."""
    text = ("10. known hypersensitivity to any of the components\n"
            "11. Inappropriateness of glimepiride treatment\n"
            "12. CHF NYHA class III or IV\n")

    out = _collapse_hierarchical_groups(text)

    assert "[OR-GROUP]" not in out
    assert len(out.splitlines()) == 3


def test_should_keep_a_wrapped_bullet_whole_when_pdftotext_drops_the_indent():
    """CAROLINA's four CV risk factors, verbatim, with the real line breaks.

    pdftotext flattens the hanging indent, so the remainder of a wrapped bullet
    starts flush left and looks like the end of the list. The group used to stop
    at the second child, emitting "...(or on at least" as a truncated
    alternative and leaving cigarette smoking and LDL cholesterol behind as
    separate criteria.
    """
    text = (
        "D) At least two of the following CV risk factors:\n"
        "- Type 2 diabetes mellitus duration > 10 years at Visit 1a.\n"
        "- Current* systolic blood pressure (SBP) > 140 mmHg (or on at least\n"
        "one blood pressure lowering treatment at Visit 1a)\n"
        "- Current daily cigarette smoking\n"
        "- Current* LDL cholesterol ≥ 135 mg/dL (3.5 mmol/l) (or specific current\n"
        "treatment for this lipid abnormality at Visit 1a)\n"
    )

    group = _collapse_hierarchical_groups(text).splitlines()[0]

    assert group.startswith("[OR-GROUP]")
    alternatives = group.partition(" with any of: ")[2].split(" | ")
    assert len(alternatives) == 4
    assert alternatives[1].endswith("treatment at Visit 1a)")
    assert alternatives[2] == "Current daily cigarette smoking"
    assert alternatives[3].endswith("lipid abnormality at Visit 1a)")


def test_should_not_absorb_the_next_criterion_when_the_bullet_is_complete():
    """Absorption is bounded by the parenthesis, not by appetite.

    A balanced child ends where it ends; the line after it is a criterion in its
    own right, not a continuation.
    """
    text = (
        "At least two of the following:\n"
        "- Current daily cigarette smoking\n"
        "- Body mass index above 30 kg/m2\n"
        "Patients must give written informed consent before any trial procedure.\n"
    )

    lines = _collapse_hierarchical_groups(text).splitlines()

    assert lines[0].startswith("[OR-GROUP]")
    assert lines[0].count(" | ") == 1
    assert "informed consent" not in lines[0]
    assert lines[1] == "Patients must give written informed consent before any trial procedure."


def test_should_nest_bullets_under_an_enumerator_child_rather_than_end_the_group():
    """CAROLINA's inclusion tree is two levels deep and mixes styles flush left.

    The child loop enforced one enumeration per group, so the first "-" bullet
    under "A)" ended the group at a single child -- below the two-child floor --
    and no group was emitted at all. The header then survived as a
    colon-terminated criterion, which extraction answered with invented "CV risk
    factor A/B/C/D" placeholders that map to nothing and are refused, taking the
    whole criterion out of the cohort.

    "A)" only announces its bullets, so it is not an alternative in its own
    right; "C)" is a leaf and is.
    """
    text = (
        "High risk of CV events defined as any one (or more) of A), B), C) or D):\n"
        "A) Previous Vascular Disease:\n"
        "- Myocardial infarction (> 6 weeks prior to informed consent)\n"
        "- Ischemic or hemorrhagic stroke (> 3 months prior to informed consent)\n"
        "C) Age ≥ 70 years (at Visit 1a)\n"
    )

    lines = _collapse_hierarchical_groups(text).splitlines()

    assert len(lines) == 1
    assert lines[0].startswith("[OR-GROUP]")
    assert lines[0].partition(" with any of: ")[2].split(" | ") == [
        "Myocardial infarction (> 6 weeks prior to informed consent)",
        "Ischemic or hemorrhagic stroke (> 3 months prior to informed consent)",
        "Age ≥ 70 years (at Visit 1a)",
    ]


def test_should_not_flatten_a_sublist_announced_with_an_all_quantifier():
    """Promoting a conjunction's bullets would silently widen an AND into an OR.

    The sublist stays one alternative carrying its own items. "at least two of"
    is deliberately not treated as an all-quantifier: such a group is already
    emitted as an ANY node, so flattening it widens nothing that was not
    already widened.
    """
    text = (
        "Eligible if any one of A) or B):\n"
        "A) All of the following liver findings:\n"
        "- ALT above 3 x ULN\n"
        "- AST above 3 x ULN\n"
        "B) Age ≥ 70 years\n"
    )

    group = _collapse_hierarchical_groups(text).splitlines()[0]

    assert group.partition(" with any of: ")[2].split(" | ") == [
        "All of the following liver findings: ALT above 3 x ULN; AST above 3 x ULN",
        "Age ≥ 70 years",
    ]
