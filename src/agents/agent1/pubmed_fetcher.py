"""
Agent 1 - PubMed Fetcher.
Fetches abstracts from PubMed and extracts eligibility criteria sections.

Uses PubMed E-utilities efetch for XML abstract retrieval and
hybrid regex + LLM parsing for eligibility section extraction.
"""
import logging
import re
import requests
from difflib import SequenceMatcher
from typing import Dict, List, Optional
from dataclasses import dataclass

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
        "key inclusion", "key exclusion",
        "eligible if", "excluded if",
        "inclusion:", "exclusion:",
    ]
    has_criteria = any(kw in text_lower for kw in criteria_keywords)
    
    if not has_criteria:
        return result
    
    # Section boundary terminators for clinical trial supplements
    _section_end = (
        r"(?="
        r"(?:key\s+)?exclusion|conclusion|result|discussion|statistical|"
        r"definition|clinical\s+event|endpoint|study\s+procedure|study\s+design|"
        r"section\s+[A-Z]|appendix|reference|bibliography|"
        r"supplement|figure|table\s+\d|acknowledgement|"
        r"randomization|treatment\s+period|follow-up|visit\s+schedule|"
        r"inclusion\s+criteria"
        r"|$)"
    )

    # Strategy 1: Split by inclusion/exclusion headers
    # Find inclusion section — pick the longest substantive match
    inc_patterns = [
        r"(?:key\s+)?inclusion\s+criteria\s*(?:include)?[:\s]*(.*?)" + _section_end,
        r"eligible\s+(?:patients?|subjects?|if)[:\s]*(.*?)" + _section_end,
    ]

    result["inclusion"] = _best_section_match(text, inc_patterns)

    # Find exclusion section (same terminators, minus 'exclusion' itself)
    _exc_section_end = (
        r"(?="
        r"conclusion|result|discussion|statistical|"
        r"definition|clinical\s+event|endpoint|study\s+procedure|study\s+design|"
        r"section\s+[A-Z]|appendix|reference|bibliography|"
        r"supplement|figure|table\s+\d|acknowledgement|"
        r"randomization|treatment\s+period|follow-up|visit\s+schedule|"
        r"inclusion\s+criteria"
        r"|$)"
    )
    exc_patterns = [
        r"(?:key\s+)?exclusion\s+criteria\s*(?:include)?[:\s]*(.*?)" + _exc_section_end,
        r"(?:ineligible|excluded)\s+(?:patients?|subjects?|if)[:\s]*(.*?)" + _exc_section_end,
    ]

    result["exclusion"] = _best_section_match(text, exc_patterns)
    
    return result


def _collapse_hierarchical_groups(text: str) -> str:
    """
    Pre-process text to collapse "parent header + indented bullets" into
    a single [OR-GROUP] criterion string.

    Detection rule:
    - A line ending with ':' (or containing "≥1 of", "at least one of",
      "one or more of", "any of") is treated as a parent header.
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
    _header_trigger = re.compile(
        r"(?:≥\s*1\s+of|at\s+least\s+one\s+of|one\s+or\s+more\s+of|any\s+(?:one\s+)?of\s*:?)",
        re.IGNORECASE,
    )

    lines = text.split("\n")
    result_lines: List[str] = []
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Check if this line is a potential parent header
        if stripped and _header_trigger.search(stripped):
            # Collect contiguous indented/bullet children
            children: List[str] = []
            j = i + 1
            while j < len(lines):
                child = lines[j]
                child_stripped = child.strip()
                if not child_stripped:
                    # Blank line — stop collecting
                    break
                if _indented.match(child):
                    child_text = _bullet_start.sub("", child).strip()
                    if child_text:
                        children.append(child_text)
                    j += 1
                else:
                    break

            if len(children) >= 2:
                # Build [OR-GROUP] string from header + children
                # Strip trailing colon/whitespace from header
                header_text = re.sub(r"[\s:]+$", "", stripped)
                or_group = f"[OR-GROUP] {header_text} with any of: {' | '.join(children)}"
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
        if line.strip().startswith("[OR-GROUP]"):
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

    # Step 2: Rejoin line-wrapped continuations: lines starting with lowercase
    # are likely sentence continuations (not new criteria items)
    rejoined_lines: List[str] = []
    for line in normalized.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        # Continuation: starts with lowercase AND prev line doesn't end sentence.
        # Exclude medical abbreviations like eGFR, mL — first word has uppercase
        # after initial lowercase.
        first_word = stripped.split()[0] if stripped else ""
        is_abbrev = any(c.isupper() for c in first_word[1:])
        if (rejoined_lines
                and stripped[0].islower()
                and not is_abbrev
                and not rejoined_lines[-1].rstrip()[-1:] in ".;:"):
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
        _criteria_llm = get_llm(temperature=0.0)
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

    LLM items not similar to any regex item are appended.
    """
    merged = list(regex_items)

    for llm_item in llm_items:
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
