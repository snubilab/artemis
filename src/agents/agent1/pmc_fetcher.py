"""
Agent 1 - PMC Full-Text Fetcher.
Converts PMIDs to PMCIDs and fetches full-text XML from PubMed Central Open Access.

The article body is handed to the eligibility segmentation step (RFC-016 §5), which
finds the inclusion and exclusion criteria in it; nothing here reads the text for
section headings.
"""
import re
import requests
from typing import Dict, List, Optional

from src.agents.agent1.segmentation import segment_eligibility


PMC_IDCONV_URL = "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"
PMC_EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


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


def get_pmc_eligibility(pmid: str, timeout: int = 30) -> Optional[Dict[str, List[str]]]:
    """
    High-level function: fetch PMC full-text and extract eligibility criteria.

    Combines pmid_to_pmcid, fetch_pmc_fulltext and the eligibility segmentation step
    into a single call.

    Args:
        pmid: PubMed ID string
        timeout: Request timeout in seconds for full-text fetch

    Returns:
        Dict with "inclusion" and "exclusion" lists, or None if:
        - No PMC version exists for the PMID
        - Full-text is unavailable
        - The segmentation step found no criteria in it
    """
    # Step 1: Convert PMID -> PMCID
    pmcid = pmid_to_pmcid(pmid, timeout=10)
    if not pmcid:
        return None

    # Step 2: Fetch full-text body
    fulltext = fetch_pmc_fulltext(pmcid, timeout=timeout)
    if not fulltext:
        return None

    # Step 3: The segmentation step finds and slices the criteria
    segmented = segment_eligibility(fulltext)
    if segmented.failures:
        print(f"[PMC Fetcher] ⚠ {pmcid} eligibility segmentation: "
              f"{segmented.describe_rejections(segmented.failures)}")
    criteria = segmented.criteria()
    if not any(criteria.values()):
        print(f"[PMC Fetcher] No eligibility criteria found for {pmcid} (PMID {pmid})")
        return None
    return criteria
