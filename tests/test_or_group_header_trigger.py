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
