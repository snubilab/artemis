"""Where a document's eligibility section is, and where each listed item starts and ends -- by its format.

Re-admitted by the user on 2026-10-22: rules that only LOCATE and SPLIT the eligibility section by
document format -- section headings ("Inclusion/Exclusion criteria" style headers), list numbering and
bullets, page furniture -- are allowed again. They are the rules the delivery candidate
(output/site_gap/2026-10-12_prompt_f2, code d7dc2bb) built Agent 1's input with, restored from 2498fcb
(the parent of fe7839e, which had replaced them with an LLM segmentation step that loses lines and list
members on the production path).

Every regex and word list in this module is ledgered in ``tests/fixtures/text_rule_ledger.json`` as kind
``section_locating``, which the guard admits in this module only. Rules that decide what a criterion
MEANS stay forbidden here as everywhere, so these were NOT restored:

- A6 ``_collapse_hierarchical_groups``: it fired on quantifier phrases ("one or more of", "at least two
  of", "any of the following") and joined the list after them into one ``[OR-GROUP]`` alternative --
  a decision about OR-grouping, not about format. Without it the header and its members stay separate
  items in document order, which is where Agent 1 reads the grouping from.
- the LLM split pass (``_llm_parse_criteria``) and the flow-table refusal that gated it: a model call,
  not a format rule; on the six evaluated trials it opened twice and added nothing to the candidate.
- the similarity merge (``_merge_parsed_items``: SequenceMatcher >= 0.7 with a numeric veto) that
  unioned repeated section captures: a duplicate decision by wording. Captures are unioned dropping only
  an item that repeats one already held character for character.
- the plain-text split at commas, semicolons and ", and"/", or", and the strip of a leading "and"/"or"
  from an item: both decide what a conjunction means. Neither changes an item on the six trials.
- the registry split's removal of sub-bullet text ("keep only main item"): it deletes list members and
  is unreachable after the split it follows (that split already breaks at every "\n *").

Sections S1-S9 below follow the 2026-10-12 inventory (docs/inventory/2026-10-12_text_rules.md).
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------------------------------------------
# S1 -- the eligibility section of a protocol PDF's plain text (was eligibility_section.py)
# ---------------------------------------------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------------------------------------------
# S9 -- page furniture a PDF prints on every page, and S6 -- superscripts pdftotext hoists onto their own line
# ---------------------------------------------------------------------------------------------------------------


def strip_pdf_furniture(full_text: str) -> str:
    """Remove the download and copyright lines a journal stamps on every page, and page breaks.

    :param full_text: the ``pdftotext`` output of one PDF.
    :returns: the same text without those lines; form feeds become line breaks.
    """
    full_text = re.sub(r'Downloaded from .*?\n', '', full_text)
    full_text = re.sub(r'Copyright © .*?\n', '', full_text)
    return re.sub(r'\f', '\n', full_text)


# ---------------------------------------------------------------------------------------------------------------
# S2-S5 -- the inclusion and exclusion lists inside a section, item by item (was pubmed_fetcher.py)
# ---------------------------------------------------------------------------------------------------------------

# A section heading occupies its own line, give or take a caption label: the
# corpus writes "eAppendix 3. Inclusion Criteria", "Section D. Exclusion ..."
# and "Table I. Inclusion ...", so a bare start-of-line test would reject three
# studies outright. A mention inside a sentence never has this shape. Measured
# separation across the six protocol PDFs: all 12 real headings carry a prefix
# of 0 or 2 tokens, the one false heading ("Each subject who meets the
# inclusion/exclusion criteria will be randomly assigned ...") carries 6.
_HEADING_LINE_PREFIX = re.compile(r"^\s*(?:\S+\s+)?\S*[.:)]\s*$")


def _opens_a_line(text: str, start: int) -> bool:
    """Whether the heading matched at ``start`` opens its line, or only a sentence.

    :param text: the text finditer scanned.
    :param start: offset of the heading match.
    :returns: True when the heading is preceded on its line by nothing or by a
        caption label.
    """
    prefix = text[text.rfind("\n", 0, start) + 1:start]
    return not prefix.strip() or bool(_HEADING_LINE_PREFIX.match(prefix))


def _best_section_match(text: str, patterns: list[str]) -> list[str]:
    """Union the criteria of every substantive section match, item by item.

    Two kinds of false heading have to be dropped before anything is unioned,
    and they need different tests. A Table of Contents entry matches the header
    but captures only dot-fill and page numbers, so it is caught by weight. A
    heading MENTIONED inside a sentence captures real prose and weighs enough to
    pass, so it is caught by position (:func:`_opens_a_line`) -- ARISTOTLE's
    protocol contributes exactly one, and it parses into two plausible-looking
    criteria about randomisation that no weight test can distinguish.

    What survives is unioned rather than reduced to the single heaviest match,
    which is what this function used to return. CAROLINA's supplement repeats
    "Inclusion criteria:" as a running page header, so ONE criteria list arrives
    as three page-sized captures; keeping only the heaviest dropped the T2DM
    diagnosis, both HbA1c tiers, BMI, age and the consent criterion. The three
    captures are consecutive pages, not three renderings of one list at
    different detail levels: measured on the production rendering, the only
    cross-block pairs scoring >= 0.7 are the page-footer boilerplate, and real
    criteria overlap zero.

    Blocks fold in document order, EARLIEST first. The seed used to be the
    HEAVIEST block, which is a different thing: since the union
    appends what it does not already hold onto the end, seeding with a block from the
    middle of the document put every earlier block's unique items AFTER it.
    Measured on the production rendering, that is 3 of CAROLINA's 46 items, 6 of
    DECLARE's appendix exclusion list and 7 of its main paper's inclusion list
    sitting before items that precede them in the document -- and since a2fb858
    stopped alphabetising the list before the model reads it, position is the
    only thing still carrying "this header owns the items that follow it".

    Blocks are unioned dropping only an item that repeats one already held
    character for character -- the overlapping captures of two heading patterns,
    or a page repeated. Until fe7839e the union went through ``_merge_parsed_items``
    (SequenceMatcher >= 0.7 with a numeric veto), which decides by wording that two
    items state one fact; that is not restored (see the module docstring).

    :param text: the text to search, already stripped of running headers.
    :param patterns: heading regexes, each capturing its section body in group 1.
    :returns: the unioned criteria items.
    """
    blocks = []  # (weight, start, items)

    for pattern in patterns:
        for m in re.finditer(pattern, text, re.IGNORECASE | re.DOTALL):
            captured = m.group(1).strip()
            # Skip TOC-like captures: mostly dots, page numbers, whitespace
            weight = len(re.sub(r"[.\s\d]", "", captured))
            if not weight or not _opens_a_line(text, m.start()):
                continue
            blocks.append((weight, m.start(), _regex_parse_criteria(captured)))

    if not blocks:
        return []

    heaviest = max(blocks, key=lambda b: (b[0], -b[1]))
    ordered = sorted(blocks, key=lambda b: b[1])
    merged: list[str] = []
    for block in ordered:
        merged.extend(item for item in block[2] if item not in merged)

    if len(blocks) > 1:
        logger.info(
            "[Section rules] Unioned %d substantive section blocks into %d items "
            "(heaviest block contributed %d)",
            len(blocks), len(merged), len(heaviest[2]),
        )
    return merged


# A page header repeats once per page; a criterion is written once. Measured over
# the six protocol PDFs: running headers occur 5 to 10 times inside the extracted
# section, real criteria 0 or 1. Three sits in the gap.
_RUNNING_HEADER_MIN_REPEATS = 3
# The longest running header measured was 26 characters ("Name of active
# ingredient:"). Real criteria are sentences, so the length guard means a genuine
# criterion cannot be dropped merely for repeating.
_RUNNING_HEADER_MAX_CHARS = 60

# Lines that open a criteria section, in either noun order. Protected from the
# header strip because they repeat as often as a page header does.
_SECTION_HEADER_RE = re.compile(
    r"(?:key\s+)?(?:in|ex)clusion\s+criteria|criteria\s+for\s+(?:in|ex)clusion|"
    r"eligible\s+(?:patients?|subjects?|if)|(?:in|ex)clusion\s*:",
    re.IGNORECASE,
)


# A superscript digit sits ABOVE its baseline text, and `pdftotext` (which
# production runs without `-layout`) sorts by vertical position -- so the digit is
# emitted as its own line BEFORE the line it belongs to. Measured on the
# production rendering: ARISTOTLE's protocol strands the `3` of `mm3` two lines
# above `21) Platelet count <= 100,000/ mm`, CARMELINA's supplement strands the
# `2` of `m2` directly above `4) eGFR <15 ml/min/1.73 m (...)`, and EMPA-REG's
# appendix strands `2` (carrying its footnote daggers) above
# `Estimated glomerular filtration rate - mL/min/1.73m`.
#
# The cost is a refused criterion, not a cosmetic one: `_resolve_unit` returns
# None for the truncated spellings `/ mm` and `ml/min/1.73 m` and resolves the
# repaired `/ mm3` -> 8785 and `mL/min/1.73 m2` -> 720870.
#
# A wrong re-attachment corrupts the criterion text itself, so the digit is only
# moved on POSITIVE evidence that it is an exponent, never on the absence of a
# reason not to. Three conditions must all hold, and any one failing declines:
#
#   1. The stray line is a bare `2` or `3` (optionally trailed by footnote
#      markers). These are the only exponents clinical units carry -- area and
#      volume. A page number that is not 2 or 3 is out on this test alone.
#   2. The line it would join contains EXACTLY ONE length-unit token
#      (`m` / `mm` / `cm`) standing on its own. Zero sites means there is nothing
#      an exponent could belong to -- the ordinary case for a page number or a
#      stranded list index. More than one site means the position is ambiguous,
#      and guessing is precisely the corruption this guard exists to prevent.
#   3. At most one blank line separates them. A digit further away than that is
#      more likely a page artefact than a hoisted superscript.
#
# Idempotence falls out of condition 2's right-hand guard: a token already
# carrying its exponent (`m2`, `mm3`) is not a bare unit token, so it offers zero
# sites and the line is left alone. That is load-bearing rather than incidental
# -- CARMELINA's supplement writes `mL/min/1.73 m2` inline at lines 998 and 1000
# and the stranded form at 1016, so the same document is repaired and untouched
# in two places.
#
# Group 1 is the exponent; group 2 is any footnote markers riding with it. They
# are separated because only the first belongs to the unit: gluing `2\u2021\u2021` onto
# `mL/min/1.73m` re-blocks the very resolution this repair exists to restore
# (measured: `_resolve_unit("mL/min/1.73m2\u2021\u2021")` -> None, against 720870 for the
# clean spelling). The markers stay on their own line rather than being deleted.
_STRANDED_SUPERSCRIPT_RE = re.compile(
    "^[ \t]*([23])([\u2020\u2021*\u00a7\u00b6]{0,4})[ \t]*$"
)

# A length unit standing alone. The left guard forbids a preceding LETTER but
# allows a preceding DIGIT, because EMPA-REG writes `1.73m` with no space. The
# right guard forbids a following letter or DIGIT: the digit half is what makes
# the repair idempotent on `m2`, and the letter half is what stops `m` matching
# inside `ml`, `min` or `mg`. Longest alternative first so `mm` is not consumed
# as `m` plus a stray `m`.
_BARE_LENGTH_UNIT_RE = re.compile(r"(?<![A-Za-z])(mm|cm|m)(?![A-Za-z0-9])")

#: How many blank lines may sit between a stranded superscript and its text.
_STRANDED_SUPERSCRIPT_MAX_BLANKS = 1


def rejoin_stranded_superscripts(text: str) -> str:
    """Re-attach superscript digits `pdftotext` hoisted onto their own line.

    See the comment block above for the rule and for why it is stated as three
    positive conditions rather than as a heuristic: the digit is inserted INTO a
    criterion's text, so a wrong join does not degrade the criterion, it
    rewrites it.

    :param text: the `pdftotext` output, or any span of it.
    :returns: the same text with each confidently-identified stranded
        superscript moved to the single unit token it belongs to, and every
        other bare digit line left exactly where it was.
    """
    lines = text.split("\n")
    consumed = set()
    out_lines = list(lines)

    for i, line in enumerate(lines):
        m = _STRANDED_SUPERSCRIPT_RE.match(line)
        if not m:
            continue
        # The first non-blank line below, within the blank-line budget.
        j = i + 1
        blanks = 0
        while j < len(lines) and not lines[j].strip():
            blanks += 1
            j += 1
        if blanks > _STRANDED_SUPERSCRIPT_MAX_BLANKS or j >= len(lines):
            continue
        target = out_lines[j]
        sites = list(_BARE_LENGTH_UNIT_RE.finditer(target))
        if len(sites) != 1:
            continue
        end = sites[0].end()
        out_lines[j] = target[:end] + m.group(1) + target[end:]
        if m.group(2):
            out_lines[i] = m.group(2)
        else:
            consumed.add(i)

    return "\n".join(
        line for k, line in enumerate(out_lines) if k not in consumed
    )


def _strip_running_header_lines(text: str) -> str:
    """Remove page headers and footers before the text is split into criteria.

    Order matters. The item-level filter below compares a whole criterion
    against the line frequencies, so it only catches a header that survived as
    its own item. Once line-wrap rejoining glues `Approved v 8.0` to the `37`
    and `930018272 6.0` beneath it, the result is unique and slips through —
    which is what happened when rejoining was extended to continuations
    starting with a symbol. Stripping first means there is nothing to glue.

    :param text: the eligibility section, or the whole document on fallback.
    :returns: the same text with repeated short lines removed.
    """
    lines = text.split("\n")
    counts = Counter(line.strip() for line in lines if line.strip())
    kept = []
    for line in lines:
        stripped = line.strip()
        # A section header repeats as often as a page header -- CAROLINA's
        # supplement writes "Inclusion criteria:" three times. Removing those
        # leaves the header patterns nothing to match and the study ingests zero
        # inclusion criteria, so they are protected explicitly.
        if _SECTION_HEADER_RE.search(stripped):
            kept.append(line)
            continue
        if (len(stripped) <= _RUNNING_HEADER_MAX_CHARS
                and counts.get(stripped, 0) >= _RUNNING_HEADER_MIN_REPEATS):
            continue
        kept.append(line)
    return "\n".join(kept)


def _drop_running_headers(items: list[str], source_text: str) -> list[str]:
    """Remove criteria that are really page headers or footers.

    pdftotext interleaves a PDF's running header into the body, so a protocol
    stamped "CV185030 / BMS-562247 / Approved v 8.0" on every page yields one
    criterion per line per page. ARISTOTLE contributed 12 such items of 48 and
    CAROLINA 32 of 80. Each was mapped to the Procedure domain, matched zero
    people, and Circe ANDs inclusion rules -- so one of them empties the cohort.
    Cohort 3395 returned 0 patients against 1113 for gold on the same source.

    :param items: candidate criteria strings.
    :param source_text: the text they were parsed from, for line frequency.
    :returns: items with repeated short lines removed, original order preserved.
    """
    line_counts = Counter(line.strip() for line in source_text.split("\n") if line.strip())
    kept = []
    for item in items:
        stripped = item.strip()
        if (len(stripped) <= _RUNNING_HEADER_MAX_CHARS
                and line_counts.get(stripped, 0) >= _RUNNING_HEADER_MIN_REPEATS):
            logger.debug("dropping running header %r (%d occurrences)", stripped,
                         line_counts[stripped])
            continue
        kept.append(item)
    return kept


# Where one list's capture ends: the other list's heading (or its own repeated), or the name of a section that is
# not eligibility at all.
_OTHER_LIST = {
    # a running header repeats "Inclusion criteria:" inside the inclusion list (CAROLINA), so it ends that
    # capture too; the union in _best_section_match joins the captures again
    "inclusion": r"(?:key\s+)?exclusion|inclusion\s+criteria|criteria\s+for\s+inclusion",
    "exclusion": r"inclusion\s+criteria|criteria\s+for\s+inclusion",
}
_OTHER_SECTION = (
    r"conclusion|result|discussion|statistical|"
    r"definition|clinical\s+event|endpoint|study\s+procedure|study\s+design|"
    r"section\s+[A-Z]|appendix|reference|bibliography|"
    r"supplement|figure|table\s+\d|acknowledgement|"
    r"randomization|treatment\s+period|"
    r"follow-up\s+(?:period|schedule|visit|procedures?|assessment)|visit\s+schedule"
)
def _section_end(kind: str) -> str:
    """The lookahead that ends one list's capture: a section name anywhere, as in 2498fcb.

    :param kind: the list being captured, "inclusion" or "exclusion".
    :returns: a regex lookahead.
    """
    return r"(?=" + _OTHER_LIST[kind] + r"|" + _OTHER_SECTION + r"|$)"


def extract_eligibility_from_text(text: str) -> dict[str, list[str]]:
    """The inclusion and exclusion lists in a text, item by item.

    :param text: a PDF's eligibility section, or free text that may hold one (an abstract, a PMC body).
    :returns: ``{"inclusion": [...], "exclusion": [...]}`` in document order.
    """
    result = {"inclusion": [], "exclusion": []}

    if not text:
        return result

    text_lower = text.lower()

    # Check if text contains any criteria-related keywords
    criteria_keywords = [
        "inclusion criteria", "exclusion criteria",
        "criteria for inclusion", "criteria for exclusion",
        "key inclusion", "key exclusion",
        "eligible if", "excluded if",
        "inclusion:", "exclusion:",
    ]
    has_criteria = any(kw in text_lower for kw in criteria_keywords)

    if not has_criteria:
        return result

    # Before anything is split or rejoined, so a header cannot be glued to a
    # criterion and thereby escape the frequency check.
    text = _strip_running_header_lines(text)

    # Protocol synopses (e.g. the Boehringer Ingelheim form used by the
    # CAROLINA supplement) reverse the noun phrase: "Criteria for inclusion:".
    inc_end = _section_end("inclusion")
    inc_patterns = [
        r"(?:key\s+)?inclusion\s+criteria\s*(?:include)?[:\s]*(.*?)" + inc_end,
        r"criteria\s+for\s+inclusion\s*[:\s]*(.*?)" + inc_end,
        r"eligible\s+(?:patients?|subjects?|if)[:\s]*(.*?)" + inc_end,
    ]
    result["inclusion"] = _drop_running_headers(_best_section_match(text, inc_patterns), text)

    exc_end = _section_end("exclusion")
    exc_patterns = [
        r"(?:key\s+)?exclusion\s+criteria\s*(?:include)?[:\s]*(.*?)" + exc_end,
        r"criteria\s+for\s+exclusion\s*[:\s]*(.*?)" + exc_end,
        r"(?:ineligible|excluded)\s+(?:patients?|subjects?|if)[:\s]*(.*?)" + exc_end,
    ]
    result["exclusion"] = _drop_running_headers(_best_section_match(text, exc_patterns), text)

    return result


def _regex_parse_criteria(text: str) -> list[str]:
    """
    Split a list's text into items on bullets, list numbering and line structure.

    Each item keeps its own line. The plain-text mode of 2498fcb, which split a line without list
    structure at commas, semicolons and ", and"/", or" into separate criteria, is not restored: it
    decides that a conjunction separates criteria, which is grouping meaning. On the six evaluated
    trials it never fired (every captured span has list structure), so the candidate's input is
    unchanged by its removal.
    """
    # Bullet characters (Unicode + ASCII)
    bullet_chars = r"[\u25cb\u2022\u2023\u2043\u25e6\uf0b7\u00b7\u2219•○]"

    # Step 1: Normalize bullet/numbered list items into newline-delimited items
    normalized = text

    # Replace bullet characters with newline delimiter
    normalized = re.sub(
        rf"\s*{bullet_chars}\s*", "\n", normalized
    )
    # Replace ASCII bullet-like markers at line start: -, *
    normalized = re.sub(r"(?m)^\s*[-*]\s+", "\n", normalized)
    # Replace pdftotext hollow-circle bullet artifact: 'o ' at line start
    normalized = re.sub(r"(?m)^\s*o\s+(?=\S)", "\n", normalized)
    # Replace numbered lists: 1., 2., 1), 2), a., b., a), b), i., ii., iii.
    normalized = re.sub(
        r"(?m)^\s*\(?(?:\d{1,2}[.)]|[a-z][.)]|(?:i{1,3}|iv|vi{0,3})[.)])\s+",
        "\n",
        normalized,
        flags=re.IGNORECASE,
    )
    # Split on newlines that start a new item (newline followed by capital letter)
    normalized = re.sub(r"\n\s*(?=[A-Z])", "\n", normalized)

    # Step 2: Rejoin line-wrapped continuations. A criterion that wraps resumes
    # either with a lowercase word or with a symbol; only a capital letter
    # reliably opens a new one.
    rejoined_lines: list[str] = []
    for line in normalized.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue

        first_char = stripped[0]
        # A wrap can land anywhere, including before a bracket, an operator or a
        # number: CARMELINA's supplement breaks straight after "ALT" so the next
        # line opens "(SGPT), AST (SGOT), ...". Testing only for a lowercase
        # letter made that fragment its own criterion, and a fragment with no
        # ALT in it yielded one generic "Liver enzyme elevation" where gold has
        # three analytes.
        resumes_with_symbol = not first_char.isalpha()
        # A lowercase start is a continuation unless the first word is an
        # abbreviation that opens a criterion of its own — eGFR, mL, mmHg.
        first_word = stripped.split()[0]
        resumes_lowercase = first_char.islower() and not any(c.isupper() for c in first_word[1:])
        previous_ended = bool(rejoined_lines) and rejoined_lines[-1].rstrip()[-1:] in ".;:"

        if rejoined_lines and not previous_ended and (resumes_with_symbol or resumes_lowercase):
            rejoined_lines[-1] = rejoined_lines[-1].rstrip() + " " + stripped
        else:
            rejoined_lines.append(stripped)

    raw_items = [line.strip() for line in rejoined_lines if line.strip()]

    # Step 4: Clean up
    # PDF header artifact patterns to filter out
    _header_patterns = [
        r"^(?:revised\s+)?protocol\s+(?:no|number|version)",
        r"^date\s*:\s*\d",
        r"^(?:page|confidential|proprietary|draft)",
        r"^(?:bristol|astra|pfizer|novo|merck|sanofi|bayer|lilly|boehringer)",
        r"^\d+\s*$",
        r"^(?:version|amendment|supplement)\s*(?:no|number)?\s*[:\d]",
    ]
    _header_re = re.compile("|".join(_header_patterns), re.IGNORECASE)

    seen: set = set()
    cleaned: list[str] = []
    for item in raw_items:
        item = item.strip().rstrip(".")
        # Strip pdftotext 'o ' bullet artifacts
        item = re.sub(r"^o\s+", "", item)
        item = item.strip()
        if len(item) < 5:
            continue
        # Skip PDF header artifacts
        if _header_re.search(item):
            continue
        key = item.lower()
        if key not in seen:
            seen.add(key)
            cleaned.append(item)

    return cleaned


# ---------------------------------------------------------------------------------------------------------------
# S7 -- the registry's eligibility field: "Inclusion Criteria:" / "Exclusion Criteria:" and its bullets
# (was nct_fetcher.py)
# ---------------------------------------------------------------------------------------------------------------

def parse_registry_criteria(text: str) -> tuple[list[str], list[str]]:
    """
    Parse raw eligibility criteria text into inclusion/exclusion lists.

    Handles common ClinicalTrials.gov formatting:
    - "Inclusion Criteria:" / "Exclusion Criteria:" headers
    - Numbered items (1., 2., ...) or bullet points (-, *, •)
    """
    if not text:
        return [], []

    # Split by exclusion/non-inclusion header
    parts = re.split(
        r'(?:exclusion|non-inclusion)\s*criteria\s*:?',
        text,
        flags=re.IGNORECASE
    )

    inc_text = parts[0]
    exc_text = parts[1] if len(parts) > 1 else ""

    # Remove "Inclusion Criteria:" header
    inc_text = re.sub(r'^inclusion\s*criteria\s*:?\s*', '', inc_text, flags=re.IGNORECASE)

    inclusion = _parse_items(inc_text)
    exclusion = _parse_items(exc_text)

    return inclusion, exclusion


def _parse_items(text: str) -> list[str]:
    """Parse numbered/bulleted items from criteria text.

    Handles both:
    - Newline-separated items (standard format)
    - Inline dash-separated items: "- item1 - item2 - item3" (common in API v2)

    Codex-reviewed: regex uses negative lookaround for digits to avoid
    splitting numeric ranges like "18 - 60 years".
    """
    items = []

    # Check if text has newlines with bullets/numbers
    has_newline_items = bool(re.search(r'\n\s*[\d•\-\*]', text))

    if has_newline_items:
        # Standard: split by newline + number/bullet
        lines = re.split(r'\n\s*\d+\.?\s*|\n\s*[•\-\*]\s*', text)
    else:
        # Inline: split on spaced dashes that are list markers, not numeric ranges.
        # (?<!\d) = not preceded by digit, (?!\d) = not followed by digit
        # This correctly splits "Type 2 diabetes - Age min. 50 years"
        # but preserves "18 - 60 years" and "long-acting" (no spaces around hyphen).
        lines = re.split(r'(?<!\d)\s+-\s+(?!\d)', text)

    for line in lines:
        line = line.strip()
        # Clean up escaped characters
        line = line.replace('\\>', '>').replace('\\<', '<')
        # Keep items with meaningful content (lowered from 10 to avoid dropping
        # short but valid criteria like "Male only" or "Age 18+")
        if line and len(line) > 5:
            items.append(line)

    return items


# ---------------------------------------------------------------------------------------------------------------
# S8 -- the eligibility or methods section of a PMC article body (was pmc_fetcher.py)
# ---------------------------------------------------------------------------------------------------------------

ELIGIBILITY_KEYWORDS = [
    "eligibility",
    "inclusion",
    "exclusion",
    "study population",
    "patient selection",
    "participants",
    "subject selection",
]

METHODS_KEYWORDS = [
    "methods",
    "study design",
    "materials and methods",
]

def extract_pmc_eligibility_section(fulltext: str) -> str:
    """
    Extract eligibility/methods section from PMC full-text.

    Search strategy (in order of priority):
    1. Locate a heading that contains an eligibility keyword and return all
       text from just after that heading up to the next heading or end of text.
    2. Fall back to the methods section if it contains any eligibility keywords.
    3. Return empty string if nothing relevant is found.

    The input is expected to be plain text (XML tags already stripped).
    Section headings are short title-case phrases (under 60 chars) that appear
    at word boundaries in the text.

    Args:
        fulltext: Plain text extracted from PMC article body

    Returns:
        Relevant section text, or empty string if not found
    """
    if not fulltext:
        return ""

    text_lower = fulltext.lower()

    # Strategy 1: Find a heading containing an eligibility keyword.
    # A heading is a short phrase that immediately precedes the section body.
    # We look for: <heading> <body up to next heading or end>
    # where <heading> is up to 60 non-sentence-ending chars containing a keyword.
    eligibility_pattern = "|".join(re.escape(kw) for kw in ELIGIBILITY_KEYWORDS)

    # Match a short heading that contains an eligibility keyword, followed by body text.
    # The heading is captured in group 1; the body (section content) in group 2.
    heading_body_re = re.compile(
        rf"(?:(?:^|\s)([A-Za-z][^.!?]{{0,58}})?\b(?:{eligibility_pattern})\b[^.!?]{{0,58}})\s+((?:.|\n)+?)(?=(?:\s[A-Z][a-z]+(?:\s+[A-Z][a-z]+){{0,3}}\s)|\Z)",
        re.IGNORECASE,
    )
    for m in heading_body_re.finditer(fulltext):
        body = m.group(2).strip() if m.group(2) else ""
        if len(body) > 20:
            return body

    # Strategy 2: Keyword present anywhere — return context window around first hit
    for kw in ELIGIBILITY_KEYWORDS:
        idx = text_lower.find(kw)
        if idx >= 0:
            # Find the sentence/phrase start: scan back to nearest period or start
            start = max(0, text_lower.rfind(".", 0, idx) + 1)
            end = min(len(fulltext), idx + 1500)
            snippet = fulltext[start:end].strip()
            if len(snippet) > 20:
                return snippet

    # Strategy 3: Fall back to methods section, but only if it contains
    # eligibility-related content (inclusion/exclusion/eligible/excluded keywords)
    methods_pattern = "|".join(re.escape(kw) for kw in METHODS_KEYWORDS)
    methods_eligibility_keywords = ["inclusion", "exclusion", "eligible", "excluded", "criteria", "enroll"]

    methods_match = re.search(
        rf"(?:^|\s)(?:{methods_pattern})\b[^.!?]{{0,30}}\s+((?:.|\n)+?)(?=\Z)",
        fulltext,
        re.IGNORECASE,
    )
    if methods_match:
        methods_text = methods_match.group(1).strip()
        methods_lower = methods_text.lower()
        has_eligibility = any(kw in methods_lower for kw in methods_eligibility_keywords)
        if has_eligibility and len(methods_text) > 20:
            return methods_text

    return ""
