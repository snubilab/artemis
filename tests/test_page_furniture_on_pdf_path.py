"""Page furniture never reaches a criterion on the production PDF path (`_enrich_from_pdf`).

Measured in the sec-rules render (output/site_gap/2026-10-22_sec_rules/new_B.json, 67ba93d):
CAROLINA's supplement footer "! 2016 Boehringer Ingelheim International GmbH ... All rights
reserved" was glued to three criteria and stood alone as one inclusion criterion, and the
page numbers 37, 38, 39 of ARISTOTLE's protocol and 39 of LEADER's appendix were glued to the
criterion that crossed the page. The literals below are the measured event, read only by the
test; the removal itself (page_layout.without_page_furniture) reads position and repetition.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.agents.agent1.nct_fetcher import TrialData
from src.agents.agent1.parser import LogicDecomposer

PAPERS = Path(__file__).resolve().parents[1] / "data" / "papers"
CAROLINA = PAPERS / "NCT01243424" / "jama_2019_carolina_supplement.pdf"
ARISTOTLE = PAPERS / "NCT00412984" / "nejmoa1107039_protocol.pdf"
LEADER = PAPERS / "NCT01179048" / "nejmoa1603827_appendix.pdf"


def _criteria(pdf: Path, nct: str, role: str) -> list[str]:
    if not pdf.exists():
        pytest.skip(f"corpus PDF absent: {pdf}")
    enriched = LogicDecomposer.__new__(LogicDecomposer)._enrich_from_pdf(
        TrialData(nct_id=nct), str(pdf), role=role
    )
    return list(enriched.inclusion_criteria) + list(enriched.exclusion_criteria)


def test_should_keep_carolinas_copyright_footer_out_of_every_criterion():
    criteria = _criteria(CAROLINA, "NCT01243424", "supplement")
    assert criteria, "CAROLINA's supplement yielded no criteria"
    leaked = [c for c in criteria if "Boehringer Ingelheim International GmbH" in c
              or "may not - in full or in part - be passed on" in c]
    assert not leaked, leaked


@pytest.mark.parametrize(
    ("pdf", "nct", "role", "start"),
    [
        (ARISTOTLE, "NCT00412984", "protocol", "Either symptomatic congestive heart failure"),
        (ARISTOTLE, "NCT00412984", "protocol", "Active infective endocarditis"),
        (LEADER, "NCT01179048", "supplement", "Personal history of non-familial medullary thyroid carcinoma"),
    ],
)
def test_should_not_glue_a_page_number_onto_a_criterion_that_crosses_a_page(pdf, nct, role, start):
    hits = [c for c in _criteria(pdf, nct, role) if c.startswith(start)]
    assert hits, f"criterion starting {start!r} vanished"
    assert not hits[0].rstrip().split(" ")[-1].isdigit(), hits[0][-80:]
