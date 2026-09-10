"""The six protocol PDFs are the contract for the eligibility extractor.

Every change to the parse chain gets checked against these numbers before it is
believed. They are not aspirational -- they are what the extractor produced on
2026-08-06, frozen so that a change which improves one study and quietly wrecks
another cannot pass. The ULN count is included because the six deliverable
Circe definitions depend on liver-enzyme value constraints surviving the parse.

Requires `pdftotext` (poppler-utils) and the PDFs under data/papers/. Both are
present on the host; nothing here needs the container.
"""
import re
import shutil
import subprocess

import pytest

from src.agents.agent1.parser import LogicDecomposer
from src.agents.agent1.pubmed_fetcher import extract_eligibility_from_text


# study -> (NCT id, protocol PDF filename under data/papers/<NCT>/)
DOCUMENTS = {
    "CAROLINA": ("NCT01243424", "jama_2019_carolina_supplement.pdf"),
    "ARISTOTLE": ("NCT00412984", "nejmoa1107039_protocol.pdf"),
    "CARMELINA": ("NCT01897532", "jama_2019_carmelina_supplement.pdf"),
    "EMPA-REG": ("NCT01131676", "nejmoa1504720_appendix.pdf"),
    "PLATO": ("NCT00391872", "plato_design_ahj2009.pdf"),
    "LEADER": ("NCT01179048", "nejmoa1603827_appendix.pdf"),
}

# study -> (inclusion count, exclusion count, ULN-bearing item count)
# CAROLINA's exclusion count moved 24 -> 29 on 2026-08-19: the bare "follow-up"
# section-boundary terminator matched mid-sentence ("...requirements for
# follow-up during the study...") and truncated the criteria list at that
# point, dropping 5 real exclusion criteria written after it. Fixed by scoping
# the terminator to an actual heading phrase (follow-up period/schedule/visit/
# procedures/assessment) -- see src/agents/agent1/pubmed_fetcher.py.
#
# CAROLINA's inclusion count moved 20 -> 16 on 2026-09-10, and the four items
# are accounted for exactly: "D) At least two of the following CV risk factors:"
# now opens an OR group, so that header plus its four bullets (type 2 diabetes
# duration, systolic blood pressure, cigarette smoking, LDL cholesterol) became
# one [OR-GROUP] item instead of five. Before the fix the header matched no
# arm of the trigger -- the numeral was "two", not "one" -- and survived as a
# colon-terminated criterion promising items it did not contain, which
# extraction answered with invented "CV risk factor 1/2" placeholders. Every
# other inclusion item is still present and in the same order, the exclusion
# count is untouched, and the other five studies did not move.
#
# CAROLINA's inclusion count moved 16 -> 3 on 2026-09-11, and every item that
# left the list is accounted for below. The umbrella "High risk of CV events
# defined as any one (or more) of A), B), C) or D):" opens a two-level tree that
# mixes enumeration styles flush left: A) and B) are colon-announced sublists of
# "-" bullets, C) is a leaf, D) carries an "at least two of" quantifier this
# codebase already widens to ANY. The child loop enforced ONE style per group,
# so the first bullet under A) ended the group at a single child -- below the
# two-child floor -- and no group was emitted at all; the header survived as a
# colon-terminated criterion that extraction answered with invented "CV risk
# factor A/B/C/D" placeholders, which map to nothing and are refused. A bullet
# following an enumerator child is now that child's sub-item, and the tree
# flattens to one ANY node of 14 alternatives: 6 from A), 3 from B), C) itself,
# 4 from D). The 15 items that left, one by one:
#   - the umbrella header became the group's header text, trailing colon stripped;
#   - "Previous Vascular Disease:" and "Evidence of vascular related end-organ
#     damage:" are dropped -- they announce their bullets, they are not criteria;
#   - their 6 and 3 bullets became alternatives 1-6 and 7-9;
#   - "Peripheral occlusive arterial disease (...bilateral ankle:" and its
#     orphaned tail "arm blood pressure ratio < 0.90)" are one alternative
#     again (6): the group now absorbs the wrap before _parse_criteria_items
#     can split it at the line break;
#   - "Age >= 70 years (at Visit 1a) ! 2016 Boehringer Ingelheim ..." split in
#     two, the criterion becoming alternative 10 and the page footer standing
#     alone as its own (still noise) item;
#   - the separate "[OR-GROUP] D) At least two of the following CV risk factors"
#     is absorbed into the outer group, its four bullets becoming alternatives
#     11-14. Its header TEXT is the one thing this change loses: a nested
#     announcer is dropped like any other, so "at least two" is no longer
#     carried in a string. The widening is unchanged -- that group was already
#     emitted as an ANY node.
# TROY's gold standard answers this same line with 13 factors. 14 is
# corroboration, not a target. The exclusion count is untouched and the other
# five studies did not move.
#
# One consequence these numbers do not show: a 3-item inclusion list crosses the
# `len(regex_items) < 5` gate in _parse_criteria_items, so CAROLINA's inclusion
# span now invokes the LLM validation pass. The stub above keeps that
# deterministic here; in production it is a real call.
#
# CAROLINA's inclusion count moved 3 -> 17 on 2026-09-11, and all 14 items are
# accounted for below. _best_section_match kept the single heaviest regex match
# and discarded the rest. CAROLINA's supplement repeats "Inclusion criteria:" as
# a running page header, so ONE criteria list arrives as three page-sized
# captures -- protocol pages 5, 6 and 7, weights 964 / 1818 / 1244. Only page 6
# (the CV-risk OR-GROUP) survived. They are NOT three renderings of one list at
# different detail levels: measured on the production rendering, the only
# cross-block item pairs scoring >= 0.7 are the page-footer boilerplate, and real
# criteria overlap zero. The union is now taken at the ITEM level, heaviest block
# seeding the result and the rest folding in document order through
# _merge_parsed_items. Recovered from page 5 (6 items) and page 7 (12 items):
#   - "Documented diagnosis of T2DM and concurrently insufficient glycaemic
#     control and a high risk of CV events prior to informed consent:";
#   - its announcer "∀ Insufficient glycaemic control (at Visit 1a) defined as:";
#   - BOTH HbA1c tiers, separately: a) 6.5-8.5% while treatment naive, and
#     b) 6.5-7.5% while on SU/glinide. These are different criteria -- different
#     bands tied to different background therapy -- and they read almost alike,
#     so criteria_dedup.numerically_distinct now vetoes any merge whose two sides
#     state different numeric literals. tests/test_section_block_union.py pins
#     both halves: that the tiers score 0.857 whole-string (over the 0.7
#     duplicate threshold, i.e. the veto is proven to fire) and that they survive
#     as two items;
#   - tier a)'s therapy list "metformin monotherapy, or alpha-glucosidase ...";
#   - BMI <= 45 kg/m2, age 40-85, the informed-consent criterion, stable
#     anti-diabetic background medication, and the 80-120% run-in compliance rule;
#   - four non-criteria that page 7 carries and no existing filter removes: the
#     "Note: To ensure appropriate representation ..." recruitment note and its
#     two continuation lines, and the fragment "Criteria for" left by the
#     exclusion terminator. They are noise, not criteria, and they are counted
#     here rather than silently trimmed.
# Four of the 21 raw block items collapsed, each one named: page 5's and page 7's
# copies of "This document may not ..." and page 7's "! 2016 Boehringer ..."
# are exact duplicates (ratio 1.000) of page 6's; and page 7's asterisk footnote
# "Current = Blood pressure or LDL cholesterol measurement < 6 months prior V1a"
# is dropped by structural_verdict, which already reads it as restating the
# OR-GROUP alternatives "Current* systolic blood pressure" and "Current* LDL
# cholesterol". Nothing that was in the list before this change left it: the
# corpus-wide item-level diff is +14 / -0, and the other five studies plus every
# exclusion list are byte-identical.
#
# The LLM gate does NOT stop firing at 17 items. It is evaluated per block inside
# _parse_criteria_items, not on the unioned list, so CAROLINA's 2236-char page-6
# span still yields 3 items and still opens it -- one opening before, one after.
BASELINE = {
    "CAROLINA": (17, 29, 1),
    "ARISTOTLE": (8, 21, 1),
    "CARMELINA": (3, 16, 1),
    "EMPA-REG": (0, 15, 1),
    "PLATO": (24, 12, 1),
    "LEADER": (17, 14, 0),
}

_ULN = re.compile(r"ULN|upper limit of normal", re.IGNORECASE)

pytestmark = pytest.mark.skipif(
    shutil.which("pdftotext") is None, reason="pdftotext (poppler-utils) not installed"
)


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    """CARMELINA's PDF inclusion section opens the LLM fallback gate.

    Left unstubbed this file bills a paid call per run and its counts become
    nondeterministic, which is the opposite of a regression contract.
    """
    monkeypatch.setattr(
        "src.agents.agent1.pubmed_fetcher._llm_parse_criteria",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        "src.agents.agent1.pubmed_fetcher._get_criteria_llm",
        lambda *args, **kwargs: pytest.fail("the LLM was reached despite the stub"),
    )


def _extract(study):
    """Run the production parse chain over one study's protocol PDF.

    :param study: key into DOCUMENTS.
    :returns: the {"inclusion", "exclusion"} dict the extractor produced.
    """
    nct, pdf = DOCUMENTS[study]
    text = subprocess.run(
        ["pdftotext", f"data/papers/{nct}/{pdf}", "-"],
        capture_output=True, text=True, check=True,
    ).stdout
    section = LogicDecomposer._extract_eligibility_section(text)
    return extract_eligibility_from_text(section or text)


@pytest.mark.parametrize("study", sorted(DOCUMENTS))
def test_should_reproduce_frozen_counts_when_parsing_the_protocol_pdf(study):
    criteria = _extract(study)
    items = (criteria["inclusion"] or []) + (criteria["exclusion"] or [])
    uln = sum(1 for item in items if _ULN.search(item))

    assert (len(criteria["inclusion"]), len(criteria["exclusion"]), uln) == BASELINE[study]


def test_should_collapse_the_aristotle_stroke_risk_factors_into_one_group():
    """The five stroke risk factors are alternatives, not five requirements.

    Splitting them into five AND-ed rules is what emptied the ARISTOTLE cohort
    against a gold standard of 1,113 patients.
    """
    from src.agents.agent1.criteria_dedup import or_group_alternatives

    inclusion = _extract("ARISTOTLE")["inclusion"]
    groups = [item for item in inclusion if or_group_alternatives(item)]

    assert len(groups) == 1
    assert len(or_group_alternatives(groups[0])) == 5
