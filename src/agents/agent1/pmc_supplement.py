"""
Agent 1 - PMC Supplementary Materials Downloader.

Downloads supplement PDFs from PMC Open Access service for a given PMCID.
Supplement PDFs often contain detailed eligibility criteria tables not
present in the main article text.
"""
import io
import re
import tarfile
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

import requests


# PMC Open Access utilities endpoint
PMC_OA_URL = "https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi"

# Default output base directory (mirrors parser.py auto-discovery path)
DEFAULT_PAPERS_DIR = Path(__file__).resolve().parents[4] / "data" / "papers"

# Supplement indicator keywords (lowercase)
_SUPPLEMENT_KEYWORDS = ("suppl", "supplement", "supplementary", "supp", "table_s", "figure_s")
_APPENDIX_KEYWORDS = ("appendix",)
_MAIN_KEYWORDS = ("main", "nejm", "jama", "lancet", "bmj", "annals")


def fetch_pmc_file_list(pmcid: str, timeout: int = 10) -> List[Dict[str, str]]:
    """
    Query PMC OA service for available files for the given PMCID.

    API: https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi?id={pmcid}

    Args:
        pmcid:   PMC identifier, e.g. "PMC1234567"
        timeout: Request timeout in seconds

    Returns:
        List of dicts: [{"url": "...", "format": "pdf|tgz|..."}]
        Empty list on any error or if the article is not in the OA corpus.
    """
    try:
        response = requests.get(PMC_OA_URL, params={"id": pmcid}, timeout=timeout)
        response.raise_for_status()

        # Parse <link format="..." href="..."/> elements from the XML response
        links = re.findall(
            r'<link\s+format="([^"]+)"\s+href="([^"]+)"',
            response.text,
        )
        return [{"url": url, "format": fmt} for fmt, url in links]

    except Exception as exc:
        print(f"[PMC Supplement] fetch_pmc_file_list failed for {pmcid}: {exc}")
        return []


def classify_supplement(filename: str) -> str:
    """
    Classify a filename as 'supplement', 'appendix', 'main', or 'other'.

    Args:
        filename: Basename of the file (case-insensitive matching)

    Returns:
        One of: 'supplement', 'appendix', 'main', 'other'
    """
    if not filename:
        return "other"

    name_lower = filename.lower()

    for kw in _APPENDIX_KEYWORDS:
        if kw in name_lower:
            return "appendix"

    for kw in _SUPPLEMENT_KEYWORDS:
        if kw in name_lower:
            return "supplement"

    for kw in _MAIN_KEYWORDS:
        if kw in name_lower:
            return "main"

    # Files named PMC{digits}.pdf (no extra suffix) are the primary article
    stem = Path(filename).stem.lower()
    if re.fullmatch(r"pmc\d+", stem):
        return "main"

    # No keyword match — default to main paper (not supplement)
    return "main"


def download_pmc_supplements(
    pmcid: str,
    nct_id: str,
    output_dir: Optional[str] = None,
    timeout: int = 30,
) -> List[Dict[str, str]]:
    """
    Download PDFs (especially supplements) from PMC for the given PMCID.

    Strategy:
    1. Query PMC OA API for file listings.
    2. If a .tar.gz package is available, download and extract all PDFs from it,
       classifying each by filename.
    3. If no .tar.gz is present, fall back to the direct PDF link (role='main').
    4. Save all PDFs to output_dir / nct_id (or DEFAULT_PAPERS_DIR / nct_id).

    Args:
        pmcid:      PMC identifier, e.g. "PMC1234567"
        nct_id:     ClinicalTrials.gov identifier, e.g. "NCT01234567"
        output_dir: Base directory to save PDFs.  If None, uses DEFAULT_PAPERS_DIR.
        timeout:    Request timeout in seconds

    Returns:
        List of dicts: [{"path": "/abs/path/to/file.pdf", "role": "supplement", "name": "file.pdf"}]
        This matches the format used by parser.py's _discover_pdfs().
        Returns empty list on errors or when article is not in OA.
    """
    base_dir = Path(output_dir) if output_dir is not None else DEFAULT_PAPERS_DIR
    save_dir = base_dir / nct_id.upper()
    save_dir.mkdir(parents=True, exist_ok=True)

    file_list = fetch_pmc_file_list(pmcid, timeout=timeout)
    if not file_list:
        print(f"[PMC Supplement] No OA files found for {pmcid} — article may not be in OA corpus.")
        return []

    # Prefer tgz (full package) over direct PDF
    tgz_entries = [f for f in file_list if f["format"] == "tgz"]
    pdf_entries = [f for f in file_list if f["format"] == "pdf"]

    if tgz_entries:
        return _download_from_tgz(tgz_entries[0]["url"], save_dir, pmcid, timeout)

    if pdf_entries:
        return _download_direct_pdf(pdf_entries[0]["url"], save_dir, pmcid, timeout)

    print(f"[PMC Supplement] No tgz or pdf links found for {pmcid}.")
    return []


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _download_from_tgz(
    tgz_url: str,
    save_dir: Path,
    pmcid: str,
    timeout: int,
) -> List[Dict[str, str]]:
    """Download a PMC tgz package, extract PDFs, and save them to save_dir."""
    try:
        print(f"[PMC Supplement] Downloading tgz for {pmcid}: {tgz_url}")
        resp = requests.get(tgz_url, timeout=timeout)
        resp.raise_for_status()
    except Exception as exc:
        print(f"[PMC Supplement] tgz download failed for {pmcid}: {exc}")
        return []

    results: List[Dict[str, str]] = []

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tgz_buf = io.BytesIO(resp.content)
            with tarfile.open(fileobj=tgz_buf, mode="r:gz") as tar:
                for member in tar.getmembers():
                    if not member.name.lower().endswith(".pdf"):
                        continue

                    basename = Path(member.name).name
                    role = classify_supplement(basename)

                    dest = save_dir / basename
                    fileobj = tar.extractfile(member)
                    if fileobj is None:
                        continue

                    dest.write_bytes(fileobj.read())
                    results.append({
                        "path": str(dest.resolve()),
                        "role": role,
                        "name": basename,
                    })
                    print(f"[PMC Supplement] Saved [{role}] {basename}")

    except Exception as exc:
        print(f"[PMC Supplement] tgz extraction failed for {pmcid}: {exc}")
        return []

    if not results:
        print(f"[PMC Supplement] tgz contained no PDF files for {pmcid}.")

    return results


def _download_direct_pdf(
    pdf_url: str,
    save_dir: Path,
    pmcid: str,
    timeout: int,
) -> List[Dict[str, str]]:
    """Download a single PDF directly and save to save_dir."""
    try:
        print(f"[PMC Supplement] Downloading direct PDF for {pmcid}: {pdf_url}")
        resp = requests.get(pdf_url, timeout=timeout)
        resp.raise_for_status()
    except Exception as exc:
        print(f"[PMC Supplement] Direct PDF download failed for {pmcid}: {exc}")
        return []

    basename = Path(pdf_url).name or f"{pmcid}.pdf"
    role = classify_supplement(basename)
    # A direct single PDF from the OA endpoint is typically the main article
    if role == "other":
        role = "main"

    dest = save_dir / basename
    dest.write_bytes(resp.content)
    print(f"[PMC Supplement] Saved [{role}] {basename}")

    return [{"path": str(dest.resolve()), "role": role, "name": basename}]
