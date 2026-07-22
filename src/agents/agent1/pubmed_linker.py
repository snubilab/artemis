"""
Agent 1 - PubMed Linker.
Links NCT trials to PubMed publications for enriching eligibility criteria.

Provides two strategies:
1. Direct extraction from NCT referencesModule (fast, preferred)
2. PubMed E-utilities esearch fallback (when references absent)
"""
import re
import requests
from typing import List, Optional


# PubMed E-utilities endpoints
PUBMED_ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


def extract_pmids_from_nct(nct_data: dict) -> List[str]:
    """
    Extract PMIDs directly from NCT referencesModule.
    
    Path: protocolSection.referencesModule.references[].pmid
    
    Args:
        nct_data: Raw JSON from ClinicalTrials.gov API v2
        
    Returns:
        List of PMID strings (may be empty)
    """
    try:
        refs = (nct_data
                .get("protocolSection", {})
                .get("referencesModule", {})
                .get("references", []))
    except (AttributeError, TypeError):
        return []
    
    pmids = []
    for ref in refs:
        pmid = ref.get("pmid")
        if pmid:
            pmids.append(str(pmid))
    
    return pmids


def search_pubmed_for_nct(nct_id: str, timeout: int = 10) -> List[str]:
    """
    Search PubMed for publications linked to an NCT ID.
    
    Uses E-utilities esearch with the NCT ID as query term.
    
    Args:
        nct_id: ClinicalTrials.gov identifier (e.g., "NCT01179048")
        timeout: Request timeout in seconds
        
    Returns:
        List of PMID strings (may be empty)
    """
    try:
        params = {
            "db": "pubmed",
            "term": f"{nct_id}[Secondary Source ID]",
            "retmode": "xml",
            "retmax": 20,
        }
        
        response = requests.get(PUBMED_ESEARCH, params=params, timeout=timeout)
        response.raise_for_status()
        
        # Parse XML response for <Id> elements
        pmids = re.findall(r"<Id>(\d+)</Id>", response.text)
        return pmids
        
    except Exception as e:
        print(f"[PubMed Linker] esearch failed: {e}")
        return []


def get_design_paper_pmids(nct_data: dict) -> List[str]:
    """
    Get PMIDs prioritized by paper type.
    
    Design/protocol papers (BACKGROUND type) are prioritized over
    results papers, as they contain the full eligibility criteria.
    
    Args:
        nct_data: Raw JSON from ClinicalTrials.gov API v2
        
    Returns:
        List of PMIDs sorted: BACKGROUND first, then RESULT
    """
    try:
        refs = (nct_data
                .get("protocolSection", {})
                .get("referencesModule", {})
                .get("references", []))
    except (AttributeError, TypeError):
        return []
    
    background_pmids = []
    result_pmids = []
    
    for ref in refs:
        pmid = ref.get("pmid")
        if not pmid:
            continue
            
        ref_type = ref.get("type", "").upper()
        if ref_type == "BACKGROUND":
            background_pmids.append(str(pmid))
        else:
            result_pmids.append(str(pmid))
    
    # Design papers first
    return background_pmids + result_pmids
