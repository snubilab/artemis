"""
Journal-specific paper URL mapper and auto-downloader.

Maps DOI prefixes to journal supplement URL patterns and attempts
direct download. Falls back to DOI resolver URL + hints on failure.
"""
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

# DOI prefix -> journal config
_JOURNAL_MAP = {
    "10.1056": {
        "name": "NEJM",
        "main_url": "https://www.nejm.org/doi/pdf/{doi}",
        "supp_url": "https://www.nejm.org/doi/suppl/{doi}/suppl_file/{stem}_appendix.pdf",
        "hint": "Supplementary Appendix section",
    },
    "10.1016": {
        "name": "Lancet/Elsevier",
        "main_url": None,  # Complex URL, use DOI resolver
        "supp_url": None,
        "hint": "Supplementary appendix link on article page",
    },
    "10.1001": {
        "name": "JAMA",
        "main_url": None,
        "supp_url": None,
        "hint": "Supplement tab on article page",
    },
    "10.1136": {
        "name": "BMJ",
        "main_url": None,
        "supp_url": None,
        "hint": "Supplementary materials section",
    },
    "10.7326": {
        "name": "Annals of Internal Medicine",
        "main_url": None,
        "supp_url": None,
        "hint": "Supplements section on article page",
    },
}


@dataclass
class DownloadAttempt:
    url: str
    role: str  # "main" | "supplement"
    status: str  # "downloaded" | "paywalled" | "unavailable" | "error"
    saved_path: Optional[str] = None


def extract_doi_from_pubmed_xml(xml_text: str) -> Optional[str]:
    """Extract DOI from PubMed efetch XML response."""
    # Pattern: <ArticleId IdType="doi">10.xxxx/xxx</ArticleId>
    match = re.search(r'<ArticleId\s+IdType="doi">([^<]+)</ArticleId>', xml_text)
    if match:
        return match.group(1).strip()
    # Also try ELocationID
    match = re.search(r'<ELocationID\s+EIdType="doi"[^>]*>([^<]+)</ELocationID>', xml_text)
    if match:
        return match.group(1).strip()
    return None


def extract_doi_from_pubmed(pmid: str, timeout: int = 10) -> Optional[str]:
    """Fetch PubMed XML for a PMID and extract the DOI."""
    try:
        resp = requests.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            params={"db": "pubmed", "id": pmid, "retmode": "xml"},
            timeout=timeout,
        )
        resp.raise_for_status()
        return extract_doi_from_pubmed_xml(resp.text)
    except Exception as exc:
        logger.warning("[PaperURLMapper] Failed to fetch DOI for PMID %s: %s", pmid, exc)
        return None


def _get_journal_info(doi: str) -> dict:
    """Look up journal info from DOI prefix."""
    prefix = doi.split("/")[0] if "/" in doi else doi
    return _JOURNAL_MAP.get(prefix, {
        "name": None,
        "main_url": None,
        "supp_url": None,
        "hint": "Search article page for supplementary materials",
    })


def _extract_doi_stem(doi: str) -> str:
    """Extract the article identifier stem from a DOI for URL construction.

    e.g., '10.1056/NEJMoa1603827' -> 'nejmoa1603827'
    """
    parts = doi.split("/")
    if len(parts) >= 2:
        return parts[-1].lower()
    return doi.lower()


def build_paper_urls(doi: str) -> list[dict]:
    """Build download URLs for main paper + supplement from DOI.

    Returns list of dicts with: journal, doi, url, role, hint
    """
    info = _get_journal_info(doi)
    stem = _extract_doi_stem(doi)
    doi_url = f"https://doi.org/{doi}"

    urls = []

    # Main paper URL
    main_url = info.get("main_url")
    if main_url:
        urls.append({
            "journal": info["name"],
            "doi": doi,
            "url": main_url.format(doi=doi, stem=stem),
            "role": "main",
            "hint": None,
        })
    else:
        urls.append({
            "journal": info["name"],
            "doi": doi,
            "url": doi_url,
            "role": "main",
            "hint": "Download PDF from article page",
        })

    # Supplement URL — only add when journal has a specific supplement URL pattern.
    # When supp_url is None, showing the same doi_url as main is misleading.
    supp_url = info.get("supp_url")
    if supp_url:
        urls.append({
            "journal": info["name"],
            "doi": doi,
            "url": supp_url.format(doi=doi, stem=stem),
            "role": "supplement",
            "hint": info.get("hint"),
        })

    return urls


def _generate_filename(url: str, role: str) -> str:
    """Generate a reasonable filename from URL and role."""
    parsed = urlparse(url)
    path_parts = parsed.path.rstrip("/").split("/")

    # Try to use the last path component if it looks like a filename
    if path_parts and path_parts[-1].endswith(".pdf"):
        return path_parts[-1]

    # Fallback: role-based naming
    if path_parts and len(path_parts[-1]) > 3:
        stem = path_parts[-1].replace(".", "_")
        return f"{stem}_{role}.pdf"

    return f"paper_{role}.pdf"


def try_download_paper(
    url: str,
    save_dir: Path,
    role: str,
    timeout: int = 30,
) -> DownloadAttempt:
    """Attempt to download a paper PDF from a URL.

    Returns DownloadAttempt with status:
    - "downloaded": Success, file saved
    - "paywalled": 401/403 response (paywall)
    - "unavailable": 404 or other HTTP error
    - "error": Network/other exception
    """
    try:
        # Use headers that mimic a browser to avoid simple bot blocks
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; ArtemisAgent/1.0; clinical-trial-research)",
            "Accept": "application/pdf,*/*",
        }
        resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)

        if resp.status_code in (401, 403):
            logger.info("[PaperURLMapper] Paywalled: %s (%d)", url, resp.status_code)
            return DownloadAttempt(url=url, role=role, status="paywalled")

        if resp.status_code == 404:
            logger.info("[PaperURLMapper] Not found: %s", url)
            return DownloadAttempt(url=url, role=role, status="unavailable")

        resp.raise_for_status()

        # Check content type — must be PDF
        content_type = resp.headers.get("Content-Type", "")
        if "pdf" not in content_type.lower() and not resp.content[:5] == b"%PDF-":
            logger.info("[PaperURLMapper] Not a PDF: %s (content-type: %s)", url, content_type)
            return DownloadAttempt(url=url, role=role, status="unavailable")

        # Save the file
        save_dir.mkdir(parents=True, exist_ok=True)
        # Generate filename from URL or role
        filename = _generate_filename(url, role)
        save_path = save_dir / filename
        save_path.write_bytes(resp.content)

        logger.info("[PaperURLMapper] Downloaded [%s] %s -> %s", role, url, save_path)
        return DownloadAttempt(
            url=url, role=role, status="downloaded", saved_path=str(save_path)
        )

    except requests.RequestException as exc:
        logger.warning("[PaperURLMapper] Download error for %s: %s", url, exc)
        return DownloadAttempt(url=url, role=role, status="error")


def download_papers_for_doi(
    doi: str,
    nct_id: str,
    papers_dir: Optional[Path] = None,
) -> list[DownloadAttempt]:
    """Build URLs and attempt to download main + supplement for a DOI.

    Args:
        doi: Article DOI
        nct_id: NCT ID (for save directory)
        papers_dir: Base directory for papers. Defaults to artemis/data/papers/

    Returns:
        List of DownloadAttempt results
    """
    if papers_dir is None:
        papers_dir = Path(__file__).resolve().parents[3] / "data" / "papers"

    save_dir = papers_dir / nct_id.upper()
    urls = build_paper_urls(doi)

    results = []
    for url_info in urls:
        attempt = try_download_paper(
            url=url_info["url"],
            save_dir=save_dir,
            role=url_info["role"],
        )
        results.append(attempt)

    return results
