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
BASELINE = {
    "CAROLINA": (20, 29, 1),
    "ARISTOTLE": (8, 21, 1),
    "CARMELINA": (3, 16, 1),
    "EMPA-REG": (0, 15, 1),
    "PLATO": (18, 12, 1),
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
