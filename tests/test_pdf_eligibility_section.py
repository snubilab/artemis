"""Which headings `_extract_eligibility_section` must recognise, and where it stops.

The extractor exists to keep tables, figures and author lists out of the
criteria. When it finds nothing the caller parses the whole paper instead, which
is the failure mode it was written to prevent — on the 2026-09-07 six-study cold
run that happened for 6 of 9 PDFs, over as much as 153431 chars.

Reading those nine PDFs' pdftotext output showed the extractor was not failing on
hard documents; it was failing on heading vocabulary it had never been shown:

| PDF                     | heading actually used            | matched? |
| ARISTOTLE protocol      | `Inclusion criteria`             | yes      |
| CAROLINA supplement     | `Inclusion criteria:`            | yes      |
| LEADER appendix         | `Inclusion and exclusion criteria.` | yes    |
| CARMELINA supplement    | `eAppendix 3. Inclusion Criteria` | no       |
| PLATO design paper      | `Table I. Inclusion criteria`     | no       |
| EMPA-REG appendix       | `Section D. Exclusion criteria`    | no       |
| ARISTOTLE appendix      | none — no eligibility text at all  | n/a      |
| PLATO supplement sa1    | none — no eligibility text at all  | n/a      |
| PLATO main paper        | prose only, mid-line              | n/a      |

Only the first three were in the pattern set. The last three genuinely have no
eligibility heading — `rg -i 'inclusion|exclusion|eligib'` returns nothing at all
for the two appendices — so nothing is expected to change for them.

Every fixture below is the shape of one of those real headings. The two guards
that keep this from becoming "find a bigger section": a heading must sit on its
own line (a prose mention is not a section), and the exclusion block must survive
whatever ends the section.
"""
import pytest

from src.agents.agent1.parser import LogicDecomposer

extract = LogicDecomposer._extract_eligibility_section

# The end-of-section search deliberately starts 200 chars past the heading, so a
# fixture needs a real body before its terminator can be exercised.
INCLUSION_BODY = "\n".join(
    f"{n}) Documented diagnosis of type 2 diabetes before visit {n}, with a stable "
    f"antidiabetic background medication for at least eight weeks."
    for n in range(1, 6)
)
EXCLUSION_BODY = "\n".join(
    f"{n}) Uncontrolled hyperglycemia with glucose above 240 mg/dL after an "
    f"overnight fast, confirmed by a second measurement on another day."
    for n in range(1, 6)
)


class TestHeadingsThatRealDocumentsUse:

    def test_should_find_the_section_when_the_heading_carries_a_journal_appendix_label(self):
        """CARMELINA's supplement: `eAppendix 3. Inclusion Criteria`."""
        text = (
            "Supplementary Online Content\n\n"
            "eAppendix 3. Inclusion Criteria\n" + INCLUSION_BODY + "\n\n"
            "eAppendix 5. Definitions of Major Clinical Outcomes\n"
            "Acute coronary syndrome was adjudicated centrally.\n"
        )
        section = extract(text)
        assert section is not None, "the eAppendix heading was not recognised"
        assert "Documented diagnosis of type 2 diabetes" in section
        assert "adjudicated centrally" not in section

    def test_should_find_the_section_when_the_heading_is_a_table_caption(self):
        """PLATO's design paper puts the criteria in `Table I. Inclusion criteria`."""
        text = (
            "Study design and rationale\n\n"
            "Table I. Inclusion criteria\n" + INCLUSION_BODY + "\n\n"
            "References\n1. Wallentin L, et al.\n"
        )
        section = extract(text)
        assert section is not None, "the table-caption heading was not recognised"
        assert "Documented diagnosis of type 2 diabetes" in section

    def test_should_find_the_section_when_only_exclusion_criteria_are_documented(self):
        """EMPA-REG's appendix documents `Section D. Exclusion criteria` and no
        inclusion section at all."""
        text = (
            "Section C. Definition of high risk of cardiovascular events\n"
            "Ankle brachial index below 0.9 in at least one ankle.\n\n"
            "Section D. Exclusion criteria\n" + EXCLUSION_BODY + "\n\n"
            "Section E. Definitions of major clinical outcomes\n"
            "Acute coronary syndrome was adjudicated centrally.\n"
        )
        section = extract(text)
        assert section is not None, "an exclusion-only document yielded no section"
        assert "Uncontrolled hyperglycemia" in section
        assert "adjudicated centrally" not in section

    def test_should_prefer_the_inclusion_heading_when_the_document_has_both(self):
        """The exclusion-only heading is a last resort, not a competing anchor."""
        text = (
            "Eligibility\n\n"
            "Inclusion criteria\n" + INCLUSION_BODY + "\n\n"
            "Exclusion criteria\n" + EXCLUSION_BODY + "\n\n"
            "References\n"
        )
        section = extract(text)
        assert section.lower().startswith("inclusion criteria")


class TestTheSectionKeepsItsExclusionBlock:
    """A bigger section is not automatically better, but losing the exclusions
    is unambiguously worse — the first attempt at the eAppendix heading ended
    CARMELINA's section at `eAppendix 4` and dropped all 16 exclusion criteria."""

    def test_should_keep_the_exclusion_block_when_it_is_a_separate_appendix(self):
        text = (
            "eAppendix 3. Inclusion Criteria\n" + INCLUSION_BODY + "\n\n"
            "eAppendix 4. Exclusion Criteria\n" + EXCLUSION_BODY + "\n\n"
            "eAppendix 5. Definitions of Major Clinical Outcomes\n"
            "Acute coronary syndrome was adjudicated centrally.\n"
        )
        section = extract(text)
        assert "Uncontrolled hyperglycemia" in section, (
            "the section ended at the exclusion heading, losing every exclusion criterion"
        )
        assert "adjudicated centrally" not in section

    def test_should_keep_the_exclusion_table_when_the_criteria_live_in_two_tables(self):
        """PLATO's design paper: `Table I. Inclusion criteria`, then
        `Table II. Exclusion criteria`. A Table terminator would cut the second."""
        text = (
            "Table I. Inclusion criteria\n" + INCLUSION_BODY + "\n\n"
            "Table II. Exclusion criteria\n" + EXCLUSION_BODY + "\n\n"
            "References\n1. Wallentin L, et al.\n"
        )
        section = extract(text)
        assert "Uncontrolled hyperglycemia" in section


class TestAHeadingIsNotAMention:
    """The extractor takes the first non-contents match, so a prose mention
    earlier in the paper can anchor the section in the wrong place. Both real
    documents that could have been anchored this way — ARISTOTLE's protocol
    ('Eligibility criteria for this study have been carefully considered to...')
    and CAROLINA's supplement ('...eligibility criteria they could be
    re-screened whenever...') — escaped only by ordering luck."""

    @pytest.mark.parametrize("prose", [
        "Inclusion criteria were assessed by the site investigator at visit 1.",
        "Eligibility criteria for this study have been carefully considered to "
        "balance risk against benefit.",
    ])
    def test_should_not_anchor_on_a_prose_mention_of_the_criteria(self, prose):
        text = (
            "Background\n" + prose + "\n"
            "The trial enrolled 6979 patients across 39 countries and was stopped "
            "early for benefit at the second interim analysis.\n"
        )
        assert extract(text) is None


class TestTableOfContentsEntriesAreSkipped:

    def test_should_skip_a_contents_entry_that_has_dotted_leaders(self):
        text = (
            "Table of Contents\n"
            "Inclusion criteria ............................................ 17\n"
            "Trial committees .............................................. 21\n\n"
            "Inclusion criteria\n" + INCLUSION_BODY + "\n\nReferences\n"
        )
        section = extract(text)
        assert "...." not in section

    def test_should_skip_a_contents_entry_that_has_no_dotted_leaders(self):
        """CARMELINA's supplement lists its appendices with no leaders at all, so
        the dotted-leader test passes them straight through. What gives them away
        is that the next line is another appendix heading rather than a criterion."""
        text = (
            "Supplementary Online Content\n"
            "eAppendix 1. List of Investigators\n"
            "eAppendix 3. Inclusion Criteria\n"
            "eAppendix 4. Exclusion Criteria\n"
            "eAppendix 5. Definitions of Major Clinical Outcomes\n\n"
            "eAppendix 3. Inclusion Criteria\n" + INCLUSION_BODY + "\n\n"
            "eAppendix 5. Definitions of Major Clinical Outcomes\n"
            "Acute coronary syndrome was adjudicated centrally.\n"
        )
        section = extract(text)
        assert section is not None
        assert "List of Investigators" not in section, (
            "the section was anchored on the table of contents"
        )
        assert "Documented diagnosis of type 2 diabetes" in section


class TestTruncationCutsAtALineBoundary:

    def test_should_cut_at_a_line_boundary_when_the_cap_fires(self):
        """ARISTOTLE's protocol overruns the cap by thousands of chars. Cutting
        mid-line leaves a half-criterion that reads as a whole one."""
        body = "\n".join(
            f"{n}) A criterion long enough that the cap lands somewhere inside "
            f"this list rather than neatly at its end." for n in range(1, 400)
        )
        section = extract("Inclusion criteria\n" + body)
        assert len(section) <= LogicDecomposer._SECTION_CHAR_CAP
        assert not section.endswith(" "), "cut inside trailing whitespace"
        assert section.splitlines()[-1].endswith("."), (
            f"the cap cut a criterion in half: {section.splitlines()[-1]!r}"
        )
