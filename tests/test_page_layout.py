"""Page furniture is removed before segmentation, by position and repetition only.

Measured live (2026-10-21 seg_probe, rfc016-s5-v4): every segmentation part that failed
was a whitespace runaway in `interruptions`, the field where the model copies running
headers, footers and page numbers; and CAROLINA's synopsis exclusion list was quoted to
end at the last line before a page footer. Lines that recur in a page's top or bottom
zone on most pages are layout, whatever they say, and are removed from the text the
segmentation step reads.
"""

from __future__ import annotations

import subprocess

from src.agents.agent1.page_layout import page_furniture, without_page_furniture
from src.utils.span_match import fold
from tests.test_eligibility_segmentation import ROOT, SOURCES, locate, text_of


def _raw(source_id: str) -> str:
    path = ROOT / SOURCES[source_id]["path"]
    command = ["pdftotext", str(path), "-"]
    rendered = subprocess.run(command, capture_output=True, text=True, check=True)
    return rendered.stdout


PDFS = sorted(s for s, v in SOURCES.items() if v["kind"] == "pdf")


def test_should_remove_the_running_header_and_footer_between_carolinas_exclusions_16_and_17():
    """The real event: between 'Participation in another trial ... 2 months prior to informed
    consent' (exclusion 16) and 'Pre-menopausal women' (exclusion 17) pdftotext puts the page 7
    footer and the page 8 header; the part quoted the section's end at exclusion 16."""
    text = without_page_furniture(_raw("CAROLINA.supplement"))
    sixteenth = text.index("Participation in another trial")
    lo = text.index("months prior to informed consent\n", sixteenth)
    gap = text[lo : text.index("Pre-menopausal women (last menstruation", lo)]
    for line in ("Proprietary confidential information.", "BI Trial No.: 1218.74", "Page 8 of 172"):
        assert line not in gap


def test_should_remove_no_line_of_any_criterion_in_the_corpus():
    """No removed line lies inside a criterion of the hand-made truth, unless the truth itself
    lists it as an interruption."""
    for source_id in PDFS:
        raw = _raw(source_id)
        sections = [s for placed in locate(source_id).values() for s in placed]
        for lo, hi in page_furniture(raw):
            for section in sections:
                for head, tail in section.items:
                    inside = head[0] <= lo < tail[1]
                    assert not inside or fold(raw[lo:hi])[0] in section.interruption_lines, (
                        source_id,
                        raw[lo:hi],
                    )


def test_should_keep_offsets_of_the_text_production_reads_when_nothing_is_furniture():
    """A text with no page breaks (a registry record, an abstract) is returned unchanged, and
    a PDF's text loses only whole lines: every kept line is a line of the original, in order."""
    nct = text_of("LEADER.nct")
    assert without_page_furniture(nct) == nct
    raw = _raw("LEADER.appendix")
    kept = without_page_furniture(raw).split("\n")
    original = raw.replace("\f", "\n").split("\n")
    position = 0
    for line in kept:
        position = original.index(line, position) + 1
