"""Which merge strategy a PDF's role selects.

A protocol PDF is the trial's own text. ClinicalTrials.gov holds a summary of
the same trial. Merging the two as equals duplicates every criterion they share,
and Circe ANDs InclusionRules, so a duplicate is not redundant — it is an extra
mandatory rule.

Measured on ARISTOTLE: the protocol's "one or more of the following risk
factor(s)" collapsed correctly into one ANY rule over five factors, and then
`merge` added the CT.gov summary's versions of the same criteria as three more
standalone rules — diabetes-or-hypertension, TIA-or-embolism, LVEF <= 40%.
A patient satisfying the five-way OR by age alone still had to satisfy those
independently. `Age >= 18 years` appeared twice for the same reason.

See omx_wiki/route-of-administration-overreach.md for the sibling case where a
duplicate rule mattered, and docs/handoff/2026-08-03.
"""
import pytest

from src.agents.agent1.parser import LogicDecomposer


class TestStrategyForRole:

    @pytest.mark.parametrize("role", ["protocol", "supplement"])
    def test_the_trials_own_document_is_authoritative(self, role):
        """Both are the trial's own text, so both take the PDF as the base and
        add only CT.gov items that are genuinely missing."""
        assert LogicDecomposer._strategy_for_role(role) == "supplement_priority"

    def test_an_unclassified_pdf_still_merges(self):
        """"main" is whatever the classifier could not place — a results paper,
        a design paper. It is not the protocol, so it does not get to override
        the registry."""
        assert LogicDecomposer._strategy_for_role("main") == "merge"
