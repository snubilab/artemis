"""
Agent 1 - PMC Full-Text Fetcher.
Converts PMIDs to PMCIDs and fetches full-text XML from PubMed Central Open Access.

Extracts eligibility/methods sections from article body text to enrich
eligibility criteria beyond what is available in PubMed abstracts.
"""
import re
import requests
from typing import Dict, List, Optional


PMC_IDCONV_URL = "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"
PMC_EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

# Section title keywords that indicate eligibility content
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


def pmid_to_pmcid(pmid: str, timeout: int = 10) -> Optional[str]:
    """
    Convert PMID to PMCID via NCBI ID Converter API.

    Args:
        pmid: PubMed ID string
        timeout: Request timeout in seconds

    Returns:
        PMCID string (e.g. "PMC3901982"), or None if no PMC version exists
    """
    try:
        params = {"ids": pmid, "format": "json"}
        response = requests.get(PMC_IDCONV_URL, params=params, timeout=timeout)
        response.raise_for_status()

        data = response.json()
        records = data.get("records", [])

        if not records:
            print(f"[PMC Fetcher] No ID converter records for PMID {pmid}")
            return None

        record = records[0]
        pmcid = record.get("pmcid")
        if not pmcid:
            print(f"[PMC Fetcher] No PMCID found for PMID {pmid} (not open-access?)")
            return None

        return pmcid

    except Exception as e:
        print(f"[PMC Fetcher] Failed to convert PMID {pmid} to PMCID: {e}")
        return None


def fetch_pmc_fulltext(pmcid: str, timeout: int = 30) -> Optional[str]:
    """
    Fetch full-text XML from PMC Open Access and extract body text.

    Uses regex-based extraction to strip XML tags and return plain text
    from the article body. Returns None if the article is not available
    or has no body element.

    Args:
        pmcid: PubMed Central ID string (e.g. "PMC3901982")
        timeout: Request timeout in seconds

    Returns:
        Plain text extracted from article body, or None if not available
    """
    try:
        params = {"db": "pmc", "id": pmcid, "rettype": "xml"}
        response = requests.get(PMC_EFETCH_URL, params=params, timeout=timeout)
        response.raise_for_status()

        xml_text = response.text

        # Extract content within <body>...</body>
        body_match = re.search(r"<body\b[^>]*>(.*?)</body>", xml_text, re.DOTALL | re.IGNORECASE)
        if not body_match:
            print(f"[PMC Fetcher] No <body> element found for {pmcid}")
            return None

        body_xml = body_match.group(1)

        # Strip all XML/HTML tags to get plain text
        plain_text = re.sub(r"<[^>]+>", " ", body_xml)
        # Collapse whitespace
        plain_text = re.sub(r"\s+", " ", plain_text).strip()

        if not plain_text:
            print(f"[PMC Fetcher] Empty body text for {pmcid}")
            return None

        return plain_text

    except Exception as e:
        print(f"[PMC Fetcher] Failed to fetch full-text for {pmcid}: {e}")
        return None


def extract_eligibility_section(fulltext: str) -> str:
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


def get_pmc_eligibility(pmid: str, timeout: int = 30) -> Optional[Dict[str, List[str]]]:
    """
    High-level function: fetch PMC full-text and extract eligibility criteria.

    Combines pmid_to_pmcid, fetch_pmc_fulltext, extract_eligibility_section, and
    the standard extract_eligibility_from_text parser into a single call.

    Args:
        pmid: PubMed ID string
        timeout: Request timeout in seconds for full-text fetch

    Returns:
        Dict with "inclusion" and "exclusion" lists, or None if:
        - No PMC version exists for the PMID
        - Full-text is unavailable
        - No eligibility section could be found
    """
    # Step 1: Convert PMID -> PMCID
    pmcid = pmid_to_pmcid(pmid, timeout=10)
    if not pmcid:
        return None

    # Step 2: Fetch full-text body
    fulltext = fetch_pmc_fulltext(pmcid, timeout=timeout)
    if not fulltext:
        return None

    # Step 3: Extract eligibility section
    section = extract_eligibility_section(fulltext)
    if not section:
        print(f"[PMC Fetcher] No eligibility section found for {pmcid} (PMID {pmid})")
        return None

    # Step 4: Parse criteria using the shared eligibility extractor
    from src.agents.agent1.pubmed_fetcher import extract_eligibility_from_text

    criteria = extract_eligibility_from_text(section)
    return criteria
