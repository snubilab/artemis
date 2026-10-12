"""
Agent 1 - PubMed Fetcher.
Fetches titles and abstracts from PubMed via E-utilities efetch.

Finding the eligibility criteria in an abstract or a paper is the segmentation step's
job (``src/agents/agent1/segmentation.py``, RFC-016 §5); nothing here reads the text.
"""
import logging
import re
import requests
from typing import Dict, List, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


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
