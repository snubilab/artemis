"""
Agent 1 - PubMed Fetcher.
Fetches abstracts from PubMed and extracts eligibility criteria sections.

Uses PubMed E-utilities efetch for XML abstract retrieval and
hybrid regex + LLM parsing for eligibility section extraction.
"""
import logging
import re
import requests
from collections import Counter
from difflib import SequenceMatcher
from typing import Dict, List, Optional
from dataclasses import dataclass

from src.agents.agent1.criteria_dedup import (
    DROP,
    KEEP,
    OR_GROUP_JOIN,
    OR_GROUP_PREFIX,
    OR_GROUP_SEP,
    structural_verdict,
)

logger = logging.getLogger(__name__)

# Lazy-cached LLM instance for criteria parsing validation
_criteria_llm = None


PUBMED_EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


@dataclass
class PubMedPaper:
    """Fetched PubMed paper data."""
    pmid: str
    title: str = ""
    abstract: str = ""


def fetch_pubmed_abstract(pmid: str, timeout: int = 10) -> Optional[PubMedPaper]:
    """
    Fetch title and abstract from PubMed via E-utilities efetch.
    
    Args:
        pmid: PubMed ID
        timeout: Request timeout in seconds
        
    Returns:
        PubMedPaper with title and abstract, or None if not found
    """
    try:
        params = {
            "db": "pubmed",
            "id": pmid,
            "retmode": "xml",
            "rettype": "abstract",
        }
        
        response = requests.get(PUBMED_EFETCH, params=params, timeout=timeout)
        response.raise_for_status()
        
        xml_text = response.text
        
        # Parse title
        title_match = re.search(
            r"<ArticleTitle>(.*?)</ArticleTitle>", xml_text, re.DOTALL
        )
        title = title_match.group(1).strip() if title_match else ""
        
        # Parse abstract
        abstract_match = re.search(
            r"<AbstractText[^>]*>(.*?)</AbstractText>", xml_text, re.DOTALL
        )
        if not abstract_match:
            # Try multi-section abstract
            abstracts = re.findall(
                r"<AbstractText[^>]*>(.*?)</AbstractText>", xml_text, re.DOTALL
            )
            abstract = "\n\n".join(a.strip() for a in abstracts) if abstracts else ""
        else:
            abstract = abstract_match.group(1).strip()
        
        if not title and not abstract:
            return None
        
        return PubMedPaper(pmid=pmid, title=title, abstract=abstract)
        
    except Exception as e:
        print(f"[PubMed Fetcher] Failed to fetch PMID {pmid}: {e}")
        return None


def fetch_pubmed_abstracts(pmids: List[str], timeout: int = 20) -> Dict[str, PubMedPaper]:
    """Batch efetch: fetch many PMIDs in ONE request. Returns {pmid: PubMedPaper}.

    Far cheaper than per-PMID fetches (one round-trip + one courtesy delay for N papers).
    """
    ids = [str(p) for p in pmids if p]
    if not ids:
        return {}
    try:
        response = requests.get(
            PUBMED_EFETCH,
            params={"db": "pubmed", "id": ",".join(ids), "retmode": "xml", "rettype": "abstract"},
            timeout=timeout,
        )
        response.raise_for_status()
        xml_text = response.text
    except Exception as e:
        print(f"[PubMed Fetcher] Batch fetch failed ({len(ids)} ids): {e}")
        return {}

    out: Dict[str, PubMedPaper] = {}
    # Split the article set into individual articles and parse each one.
    for chunk in re.split(r"(?=<PubmedArticle>)", xml_text):
        if "<PubmedArticle>" not in chunk:
            continue
        pm = re.search(r"<PMID[^>]*>(\d+)</PMID>", chunk)
        if not pm:
            continue
        pmid = pm.group(1)
        tm = re.search(r"<ArticleTitle>(.*?)</ArticleTitle>", chunk, re.DOTALL)
        title = tm.group(1).strip() if tm else ""
        abstracts = re.findall(r"<AbstractText[^>]*>(.*?)</AbstractText>", chunk, re.DOTALL)
        abstract = "\n\n".join(a.strip() for a in abstracts) if abstracts else ""
        if title or abstract:
            out[pmid] = PubMedPaper(pmid=pmid, title=title, abstract=abstract)
    return out


def _best_section_match(text: str, patterns: List[str]) -> List[str]:
    """Find the best (longest substantive) section match across all regex matches.

    Supplement PDFs often have a Table of Contents that also matches
    "inclusion/exclusion criteria" headers. The TOC match captures only
    dot-fill lines or whitespace. We iterate *all* matches from finditer
    and pick the one whose captured group has the most non-whitespace
    content, skipping TOC-like entries (mostly dots, digits, whitespace).
    """
    best_text = ""
    best_weight = 0

    for pattern in patterns:
        for m in re.finditer(pattern, text, re.IGNORECASE | re.DOTALL):
            captured = m.group(1).strip()
            # Skip TOC-like captures: mostly dots, page numbers, whitespace
            stripped = re.sub(r"[.\s\d]", "", captured)
            weight = len(stripped)
            if weight > best_weight:
                best_weight = weight
                best_text = captured

    if best_text:
        return _parse_criteria_items(best_text)
    return []


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


def _drop_running_headers(items: List[str], source_text: str) -> List[str]:
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


def extract_eligibility_from_text(text: str) -> Dict[str, List[str]]:
    """
    Extract inclusion/exclusion criteria from free text.
    
    Uses heuristic pattern matching to find criteria sections.
    Works on abstracts, methods sections, or any text containing
    eligibility criteria.
    
    Args:
        text: Text potentially containing eligibility criteria
        
    Returns:
        Dict with "inclusion" and "exclusion" lists of criteria strings
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

    # Section boundary terminators for clinical trial supplements
    _section_end = (
        r"(?="
        r"(?:key\s+)?exclusion|conclusion|result|discussion|statistical|"
        r"definition|clinical\s+event|endpoint|study\s+procedure|study\s+design|"
        r"section\s+[A-Z]|appendix|reference|bibliography|"
        r"supplement|figure|table\s+\d|acknowledgement|"
        r"randomization|treatment\s+period|follow-up|visit\s+schedule|"
        r"inclusion\s+criteria|criteria\s+for\s+inclusion"
        r"|$)"
    )

    # Strategy 1: Split by inclusion/exclusion headers
    # Find inclusion section — pick the longest substantive match.
    # Protocol synopses (e.g. the Boehringer Ingelheim form used by the
    # CAROLINA supplement) reverse the noun phrase: "Criteria for inclusion:".
    inc_patterns = [
        r"(?:key\s+)?inclusion\s+criteria\s*(?:include)?[:\s]*(.*?)" + _section_end,
        r"criteria\s+for\s+inclusion\s*[:\s]*(.*?)" + _section_end,
        r"eligible\s+(?:patients?|subjects?|if)[:\s]*(.*?)" + _section_end,
    ]

    result["inclusion"] = _drop_running_headers(_best_section_match(text, inc_patterns), text)

    # Find exclusion section (same terminators, minus 'exclusion' itself)
    _exc_section_end = (
        r"(?="
        r"conclusion|result|discussion|statistical|"
        r"definition|clinical\s+event|endpoint|study\s+procedure|study\s+design|"
        r"section\s+[A-Z]|appendix|reference|bibliography|"
        r"supplement|figure|table\s+\d|acknowledgement|"
        r"randomization|treatment\s+period|follow-up|visit\s+schedule|"
        r"inclusion\s+criteria|criteria\s+for\s+inclusion"
        r"|$)"
    )
    exc_patterns = [
        r"(?:key\s+)?exclusion\s+criteria\s*(?:include)?[:\s]*(.*?)" + _exc_section_end,
        r"criteria\s+for\s+exclusion\s*[:\s]*(.*?)" + _exc_section_end,
        r"(?:ineligible|excluded)\s+(?:patients?|subjects?|if)[:\s]*(.*?)" + _exc_section_end,
    ]

    result["exclusion"] = _drop_running_headers(_best_section_match(text, exc_patterns), text)

    return result


def _collapse_hierarchical_groups(text: str) -> str:
    """
    Pre-process text to collapse "parent header + indented bullets" into
    a single [OR-GROUP] criterion string.

    Detection rule:
    - A line carrying an OR-quantifier phrase is treated as a parent header.
      `any of` additionally requires a list announcer -- 'the/these/those
      following|below|listed', or a line-terminal colon within 40 characters --
      because `any of` also quantifies nouns ("any of the components").
    - Followed by 2+ lines that start with whitespace (spaces/tabs) or a
      bullet character (•, -, *, o followed by space).
    - Those child lines are joined with ' | ' and the whole group becomes:
      "[OR-GROUP] <header stripped colon> with any of: <children>"

    Lines NOT matching this pattern are left intact.

    Args:
        text: Raw criteria section text (indentation preserved).

    Returns:
        Text with hierarchical groups collapsed; flat lines unchanged.
    """
    # Bullet prefix pattern at line start (optional indentation)
    _bullet_start = re.compile(r"^[\s]*[•\-\*\u25cb\u2022\u2023\u2043\u25e6\uf0b7\u00b7\u2219○]?\s+", re.UNICODE)
    # Indented line: starts with whitespace or a bullet
    _indented = re.compile(r"^(?:[\t ]+|\s*[•\-\*\u25cb\u2022\u2023\u2043\u25e6\uf0b7\u00b7\u2219○]\s+)", re.UNICODE)
    # Header trigger: ONLY explicit OR-quantifier phrases trigger OR-group collapse.
    # Plain "Criteria:" headers must NOT trigger — their children are AND criteria.
    #
    # A quantifier phrase alone is not a list header: CAROLINA's "known
    # hypersensitivity to any of the components" quantifies a noun, and matching
    # it swallowed exclusion criteria 11-20 as ten fabricated alternatives. Only
    # the ambiguous `any of` arm is constrained -- it must be followed by a
    # forward reference (the/these/those following|below|listed) or terminate the
    # line, optionally after a short noun phrase and a colon. The unambiguous
    # arms keep firing anywhere so that wrapped headers ("...including at least
    # one of") still collapse; they only refuse relative pronouns and
    # possessives, which is what "at least one of which should be performed" and
    # "one or more of its affiliated companies" are.
    _header_trigger = re.compile(
        r"(?:[≥>]=?\s*1|\bat\s+least\s+(?:one|1)|\bone\s+or\s+more|\beither)"
        r"\s+of\b(?!\s+(?:which|whom|its|their|his|her)\b)"
        r"|\bany\s+(?:one\s+)?of"
        r"(?:\s+(?:the\s+|these\s+|those\s+)?(?:following|below|listed)\b"
        r"|[^:\n]{0,40}:\s*$)",
        re.IGNORECASE,
    )
    # Protocols enumerate rather than indent. ARISTOTLE lists its five stroke risk
    # factors as a) to e), flush left, under "One or more of the following:".
    _enum_marker = re.compile(
        r"^\s*\(?(?:(?P<roman>i{2,3}|iv|vi{1,3}|ix|xi{0,3})|(?P<alpha>[a-z])|(?P<digit>\d{1,2}))[.)]\s+",
        re.IGNORECASE,
    )
    # A page number stranded between children by pdftotext.
    _noise_line = re.compile(r"^\s*\d{1,4}\s*$")

    def _child_style(candidate: str) -> Optional[str]:
        """Which enumeration a line uses, or None if it is not a list item."""
        if _indented.match(candidate):
            return "bullet"
        marker = _enum_marker.match(candidate)
        if not marker:
            return None
        if marker.group("roman"):
            return "roman"
        return "alpha" if marker.group("alpha") else "digit"

    lines = text.split("\n")
    result_lines: List[str] = []
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Check if this line is a potential parent header
        if stripped and _header_trigger.search(stripped):
            children: List[str] = []
            # The children share one enumeration; a different one ends the group.
            # That is what separates ARISTOTLE's a)-e) from the 4) after them.
            style: Optional[str] = None
            j = i + 1
            while j < len(lines):
                child = lines[j]
                child_stripped = child.strip()

                if not child_stripped or _noise_line.match(child):
                    # Step over blank lines and page numbers only when a child of
                    # the same enumeration resumes after them; otherwise the group
                    # has really ended. ARISTOTLE's list is broken between c) and
                    # d) by a stray "37".
                    k = j + 1
                    while k < len(lines) and (not lines[k].strip() or _noise_line.match(lines[k])):
                        k += 1
                    if k < len(lines) and style is not None and _child_style(lines[k]) == style:
                        j = k
                        continue
                    break

                this_style = _child_style(child)
                if this_style is None:
                    # A wrapped child, e.g. c) running onto a second line. Only
                    # enumerated lists wrap this way; for indented bullets the
                    # indentation is the signal and its absence ends the group.
                    if children and style in ("alpha", "roman", "digit"):
                        children[-1] = children[-1] + " " + child_stripped
                        j += 1
                        continue
                    break

                if style is None:
                    style = this_style
                elif this_style != style:
                    break

                child_text = (_bullet_start.sub("", child) if style == "bullet"
                              else _enum_marker.sub("", child)).strip()
                if child_text:
                    children.append(child_text)
                j += 1

            if len(children) >= 2:
                # Build [OR-GROUP] string from header + children
                # Strip trailing colon/whitespace from header
                header_text = re.sub(r"[\s:]+$", "", stripped)
                or_group = (f"{OR_GROUP_PREFIX}{header_text}"
                            f"{OR_GROUP_JOIN}{OR_GROUP_SEP.join(children)}")
                result_lines.append(or_group)
                i = j  # skip consumed child lines
                continue

        result_lines.append(line)
        i += 1

    return "\n".join(result_lines)


def _parse_criteria_items(text: str) -> List[str]:
    """
    Parse individual criteria items from a criteria section text.

    Hybrid approach:
    1. Hierarchical pre-processing: collapse "parent + indented bullets"
       into single [OR-GROUP] criterion strings (preserves OR logic).
    2. Enhanced regex pass handles bullets, numbered lists, newlines,
       comma/semicolon separators.
    3. LLM validation pass fires only when regex produces suspiciously
       few items from long text (< 5 items from > 200 chars).
    """
    if not text.strip():
        return []

    # Pre-process: collapse hierarchical parent+children groups
    preprocessed = _collapse_hierarchical_groups(text)

    # Separate [OR-GROUP] lines — they must NOT be further split by the regex pass
    or_group_items: List[str] = []
    remaining_lines: List[str] = []
    for line in preprocessed.splitlines():
        if line.strip().startswith(OR_GROUP_PREFIX.strip()):
            or_group_items.append(line.strip())
        else:
            remaining_lines.append(line)
    remaining_text = "\n".join(remaining_lines)

    regex_items = _regex_parse_criteria(remaining_text) if remaining_text.strip() else []
    # Merge preserving document order: OR-GROUP items were already interspersed
    # with flat lines before separation; insert them back at the front since
    # they typically appear at section start (age-stratified parent headers).
    # For now a simple prepend is sufficient — document order within OR-groups
    # is preserved by the children join order.
    regex_items = or_group_items + regex_items

    # Gate: only invoke LLM when regex likely missed structure
    if len(regex_items) < 5 and len(text) > 200:
        logger.info(
            "[PubMed Fetcher] Regex produced %d items from %d chars — "
            "invoking LLM validation pass",
            len(regex_items), len(text),
        )
        try:
            llm_items = _llm_parse_criteria(text)
        except Exception as exc:
            logger.warning(
                "[PubMed Fetcher] LLM fallback failed, using regex-only result: %s",
                exc,
            )
            llm_items = []
        if llm_items:
            regex_items = _merge_parsed_items(regex_items, llm_items)

    return regex_items


def _regex_parse_criteria(text: str) -> List[str]:
    """
    Enhanced regex pass: split criteria text on bullets, numbered lists,
    newlines, commas, and semicolons.

    Detects whether the text has bullet/numbered/newline structure.
    - Bullet mode: split on structural markers only (no comma sub-split).
    - Plain mode: split on commas and semicolons.
    """
    # Bullet characters (Unicode + ASCII)
    bullet_chars = r"[\u25cb\u2022\u2023\u2043\u25e6\uf0b7\u00b7\u2219•○]"

    # Detect whether the text has bullet / numbered-list / multi-newline structure
    has_bullets = bool(re.search(bullet_chars, text))
    has_dash_bullets = bool(re.search(r"(?m)^\s*[-*]\s+", text))
    has_o_bullets = bool(re.search(r"(?m)^\s*o\s+\S", text))
    has_numbered = bool(re.search(
        r"(?m)^\s*(?:\d+[.)]\s+|[a-z][.)]\s+|(?:i{1,3}|iv|vi{0,3})[.)]\s+)",
        text, re.IGNORECASE,
    ))
    has_multi_newlines = text.strip().count("\n") >= 2

    is_bullet_mode = has_bullets or has_dash_bullets or has_o_bullets or has_numbered or has_multi_newlines

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
        r"(?m)^\s*(?:\d+[.)]\s+|[a-z][.)]\s+|(?:i{1,3}|iv|vi{0,3})[.)]\s+)",
        "\n",
        normalized,
        flags=re.IGNORECASE,
    )
    # Split on newlines that start a new item (newline followed by capital letter)
    normalized = re.sub(r"\n\s*(?=[A-Z])", "\n", normalized)

    # Step 2: Rejoin line-wrapped continuations. A criterion that wraps resumes
    # either with a lowercase word or with a symbol; only a capital letter
    # reliably opens a new one.
    rejoined_lines: List[str] = []
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

    # Step 3: Split on structure; sub-split only in plain (non-bullet) mode
    raw_items: List[str] = []
    for line in rejoined_lines:
        line = line.strip()
        if not line:
            continue
        if is_bullet_mode:
            # Bullet mode: keep each line intact (no comma/conjunction sub-split)
            raw_items.append(line)
        else:
            # Plain mode: sub-split by semicolons, commas with conjunction,
            # or plain commas
            sub_items = re.split(
                r"[;]\s+(?:and\s+)?|,\s+(?:and|or)\s+|,\s+", line
            )
            raw_items.extend(sub_items)

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
    cleaned: List[str] = []
    for item in raw_items:
        item = item.strip().rstrip(".")
        # Strip pdftotext 'o ' bullet artifacts
        item = re.sub(r"^o\s+", "", item)
        # Remove leading conjunctions
        item = re.sub(r"^(?:and|or)\s+", "", item, flags=re.IGNORECASE)
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


def _get_criteria_llm():
    """Return a cached LLM instance for criteria parsing (temperature=0)."""
    global _criteria_llm
    if _criteria_llm is None:
        from src.utils.llm import get_llm
        _criteria_llm = get_llm(temperature=0.0, json_mode=True)
        logger.info("[PubMed Fetcher] Initialized LLM for criteria parsing validation")
    return _criteria_llm


_LLM_CRITERIA_PROMPT = """\
Extract individual eligibility criteria items from the following clinical trial text.
Return ONLY a JSON array of strings, one string per criterion.
Do not number them. Do not add explanations.

Text:
{text}
"""


def _llm_parse_criteria(text: str) -> List[str]:
    """
    LLM validation pass: ask an LLM to extract criteria items from text.

    Returns a list of criteria strings, or an empty list on failure.
    """
    import json
    from langchain_core.messages import HumanMessage

    try:
        llm = _get_criteria_llm()
        prompt = _LLM_CRITERIA_PROMPT.format(text=text[:4000])
        response = llm.invoke([HumanMessage(content=prompt)])
        content = response.content.strip()

        # Strip markdown code fences if present
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
            content = content.strip()

        items = json.loads(content)
        if not isinstance(items, list):
            logger.warning("[PubMed Fetcher] LLM returned non-list: %s", type(items))
            return []

        cleaned = [str(i).strip().rstrip(".") for i in items if isinstance(i, str) and len(str(i).strip()) >= 5]
        logger.info("[PubMed Fetcher] LLM extracted %d criteria items", len(cleaned))
        return cleaned

    except Exception as exc:
        logger.warning("[PubMed Fetcher] LLM criteria parsing failed: %s", exc)
        return []


def _merge_parsed_items(
    regex_items: List[str],
    llm_items: List[str],
    similarity_threshold: float = 0.7,
) -> List[str]:
    """
    Merge regex and LLM parsed items, deduplicating by string similarity.

    LLM items not similar to any regex item are appended, unless they merely
    restate an alternative already inside an [OR-GROUP] -- the LLM is handed the
    raw, uncollapsed text, so it re-flattens any hierarchy the collapse just
    built. Whole-string similarity cannot catch that: an alternative is far
    shorter than the group line that contains it.

    Routed through structural_verdict for the single-home rule rather than for a
    behaviour change: the LLM is handed raw text and never emits the OR-GROUP
    wire format, so the KEEP branch is unreachable from here in production.
    """
    merged = list(regex_items)

    for llm_item in llm_items:
        verdict = structural_verdict(llm_item, merged)
        if verdict == DROP:
            continue
        if verdict == KEEP:
            merged.append(llm_item)
            continue
        is_duplicate = False
        for existing in merged:
            similarity = SequenceMatcher(
                None, llm_item.lower(), existing.lower()
            ).ratio()
            if similarity >= similarity_threshold:
                is_duplicate = True
                break
        if not is_duplicate:
            merged.append(llm_item)

    if len(merged) > len(regex_items):
        logger.info(
            "[PubMed Fetcher] Merged: %d regex + %d LLM unique = %d total",
            len(regex_items), len(merged) - len(regex_items), len(merged),
        )

    return merged
