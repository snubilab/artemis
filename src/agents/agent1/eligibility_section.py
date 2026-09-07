"""Pull the eligibility section out of a protocol PDF's plain text.

The extractor exists to keep tables, figures and author lists out of the
criteria. When it finds nothing the caller still parses the whole paper —
that is the failure mode this module was written to prevent, and on the
2026-09-07 six-study cold run it happened for 6 of 9 PDFs, over as much as
153431 chars.

Reading those nine PDFs' pdftotext output showed the extractor was not
failing on hard documents. It was failing on heading vocabulary it had
never been shown, so the patterns below are the ones those documents
actually use, not a guessed lexicon.

This module only classifies text. It does not print: a ``Truncated`` or
``Missing`` result is the announcement, and the caller decides what to say.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


# How the nine study PDFs number their own divisions: "Section D.",
# "eAppendix 3.", "Table I.", "Annex 2.", or a bare "3.2". Optional, because
# ARISTOTLE's protocol and CAROLINA's supplement head the section with a bare
# "Inclusion criteria".
_HEADING_PREFIX = (
    r'(?:(?:e?appendix|section|table|part|annex)\s+[\w\.]{1,6}[\.\)\s\-]+\s*'
    r'|\d{1,2}(?:\.\d{1,2})*[\.\)]\s+)?'
)

# A heading owns its line. Allows a trailing ":" (CAROLINA writes "Inclusion
# criteria:") or "." (LEADER writes "Inclusion and exclusion criteria."), then
# nothing but the line ending. This is what separates a heading from a sentence
# that merely mentions the criteria.
_HEADING_TAIL = r'[:.\)]?[ \t]*(?:\r?\n|$)'

# A numbered container heading — "eAppendix 4. Exclusion Criteria",
# "Section E. Definitions of major clinical outcomes". Used only to recognise a
# table of contents, where such headings appear on consecutive lines.
#
# It deliberately does NOT match a bare numbered line. A real inclusion section
# is followed by "1) Documented diagnosis of type 2 diabetes...", and treating
# that as a heading rejected CARMELINA's genuine section along with its
# contents entry.
_CONTAINER_HEADING = re.compile(
    r'^[ \t]*(?:e?appendix|section|table|part|annex)\s+[\w\.]{1,6}[\.\)\s\-]+\S.{0,90}$',
    re.IGNORECASE,
)

# Ceiling on the returned section, to keep the downstream LLM prompt bounded.
# ARISTOTLE's protocol hits it exactly, which is why the truncation is
# announced: "20000 chars" printed on its own is indistinguishable from a
# section that happens to be that long.
SECTION_CHAR_CAP = 20000


@dataclass(frozen=True)
class Found:
    """A heading was found and the section fits under the cap."""

    text: str


@dataclass(frozen=True)
class Missing:
    """No eligibility heading, or the matched span was too short to be one."""


@dataclass(frozen=True)
class Truncated:
    """A heading was found; the tail past :data:`SECTION_CHAR_CAP` was dropped."""

    text: str
    dropped: int
    cap: int = SECTION_CHAR_CAP


SectionResult = Found | Missing | Truncated


def _is_contents_entry(full_text: str, heading_end: int) -> bool:
    """Whether a matched heading is a table-of-contents line rather than the
    section itself.

    The dotted-leader test alone is not enough. CARMELINA's supplement lists
    its appendices with no leaders at all::

        eAppendix 3. Inclusion Criteria
        eAppendix 4. Exclusion Criteria
        eAppendix 5. Definitions of Major Clinical Outcomes

    so the contents entry passed straight through and anchored the section on
    the front matter — 20000 chars of it, with 92893 more dropped by the cap
    and not one criterion extracted. What distinguishes it is that the next
    line is another container heading; the real section is followed by a
    criterion.

    :param full_text: The whole document.
    :param heading_end: Offset just past the matched heading.
    :returns: True when the following non-blank line is a container heading.
    """
    for line in full_text[heading_end:heading_end + 400].split("\n"):
        if not line.strip():
            continue
        return bool(_CONTAINER_HEADING.match(line))
    return False


def extract_eligibility_section(full_text: str) -> SectionResult:
    """Classify the eligibility span of one PDF's plain text.

    Looks for section headings like:
    - "Inclusion and exclusion criteria"
    - "Inclusion criteria"
    - "Study Eligibility Criteria"
    - "Section C - STUDY ELIGIBILITY CRITERIA"

    Terminates at the next section heading (e.g., "Figure", "Table",
    "Section D", "Clinical event definitions", "References").

    :param full_text: The whole pdftotext output for one PDF.
    :returns: :class:`Found` when a section fits under the cap,
        :class:`Truncated` when a real section was cut at the cap,
        :class:`Missing` when no heading was found or the span is too short.
    """
    if not full_text:
        return Missing()

    # Two things widened these beyond the original three, both read off the
    # nine study PDFs rather than guessed:
    #
    # - the heading is routinely numbered by its container, and the container
    #   is not always the word "Section": CARMELINA's supplement writes
    #   "eAppendix 3. Inclusion Criteria" and PLATO's design paper writes
    #   "Table I. Inclusion criteria". _HEADING_PREFIX covers those.
    # - a document may document exclusions only. EMPA-REG's appendix has
    #   "Section D. Exclusion criteria" and no inclusion section anywhere,
    #   and "exclusion criteria" was not in the alternation at all. It is
    #   tried LAST, so a document carrying both still anchors on inclusion.
    #
    # _HEADING_TAIL is the guard that keeps this from matching prose. A
    # heading occupies its line; "Eligibility criteria for this study have
    # been carefully considered to..." (ARISTOTLE's protocol, char 88826)
    # and "...eligibility criteria they could be re-screened whenever..."
    # (CAROLINA's supplement, char 90164) are sentences, and the extractor
    # takes the FIRST non-contents match, so without this it anchors on
    # whichever comes first in the file.
    start_patterns = [
        r'(?:^|\n)[ \t]*' + _HEADING_PREFIX + r'(?:key\s+|main\s+|major\s+|study\s+)?'
        r'(?:inclusion\s+and\s+exclusion\s+criteria|eligibility\s+criteria|'
        r'criteria\s+for\s+inclusion|inclusion\s+criteria)' + _HEADING_TAIL,
        r'(?:^|\n)[ \t]*' + _HEADING_PREFIX + r'STUDY\s+ELIGIBILITY\s+CRITERIA' + _HEADING_TAIL,
        r'(?:^|\n)[ \t]*' + _HEADING_PREFIX + r'(?:key\s+|main\s+|major\s+)?'
        r'(?:exclusion\s+criteria|criteria\s+for\s+exclusion)' + _HEADING_TAIL,
    ]

    start_pos = None
    for pattern in start_patterns:
        # Use finditer to skip TOC entries (have dotted leaders like "... 39")
        for match in re.finditer(pattern, full_text, re.IGNORECASE | re.MULTILINE):
            context = full_text[match.start():match.start() + 300]
            is_toc = bool(re.search(r'\.{3,}', context))
            if is_toc or _is_contents_entry(full_text, match.end()):
                continue
            start_pos = match.start()
            break
        if start_pos is not None:
            break

    if start_pos is None:
        return Missing()

    # Patterns to find the END (next section heading)
    end_patterns = [
        # "Section D.", "eAppendix 5.", "Annex 2." — but NOT a container
        # whose own title is an eligibility heading: CARMELINA splits
        # inclusion into eAppendix 3 and exclusion into eAppendix 4, and
        # ending at eAppendix 4 drops all 16 exclusion criteria.
        #
        # "Table" is deliberately absent here. PLATO's design paper puts
        # inclusion in "Table I" and exclusion in "Table II", so a Table
        # terminator would cut the exclusion criteria off the same way.
        r'\n\s*(?:e?Appendix|Section|Annex|Part)\s+[\w\.]{1,6}[\.\)\s\-]+'
        r'(?![^\n]{0,30}(?:inclusion|exclusion|eligibility)\s+criteria)',
        r'\n\s*(?:Figure\s+S?\d|Table\s+S?\d)',  # "Figure S1", "Table S1"
        r'\n\s*Clinical\s+event\s+definitions?',
        r'\n\s*Definitions?\s+of\s+(?:major\s+)?clinical',
        r'\n\s*(?:Statistical\s+)?(?:Analysis|Methods|Results|References|Discussion|Sensitivity)',
        r'\n\s*Supplementary\s+(?:Table|Figure|Methods)',
    ]

    # Search for end after start_pos + 200 (skip the start heading itself)
    search_start = start_pos + 200
    end_pos = len(full_text)

    for pattern in end_patterns:
        match = re.search(pattern, full_text[search_start:], re.IGNORECASE)
        if match:
            candidate = search_start + match.start()
            if candidate < end_pos:
                end_pos = candidate

    section = full_text[start_pos:end_pos].strip()

    if len(section) < 50:
        return Missing()
    cap = SECTION_CHAR_CAP
    if len(section) > cap:
        # Cap to avoid LLM token explosion. The caller's "N chars" line cannot
        # distinguish a capped section from one that is naturally that long,
        # which is why this is a distinct result rather than a silent trim.
        # Back up to the last line break so the tail is not a half
        # criterion that reads like a whole one. Guarded by cap // 2 so a
        # section with no line breaks at all still yields something.
        truncated = section[:cap]
        last_break = truncated.rfind("\n")
        if last_break > cap // 2:
            truncated = truncated[:last_break]
        dropped = len(section) - len(truncated)
        return Truncated(text=truncated.rstrip(), dropped=dropped, cap=cap)

    return Found(text=section)
