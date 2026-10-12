"""Comparator recommender — PubMed acquisition for the literature-first path (ADR-028).

For a placebo-controlled trial there is no real-world placebo cohort, so an active
comparator has to be proposed. This module fetches PubMed records for the queries
:func:`src.agents.comparator.recommender.recommend_from_literature` builds; the LLM
reads them there. Reuses agent1's PubMed efetch client.

No word list decides which abstract is relevant or which part of it is shown: every
record a query returns is kept, in PubMed relevance order, and its finding is the
head of its title and abstract.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass

import requests

from src.agents.agent1.pubmed_fetcher import fetch_pubmed_abstracts

logger = logging.getLogger(__name__)

PUBMED_ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
_NCBI_COURTESY_DELAY = 0.34  # ~3 req/s without an API key


@dataclass
class Evidence:
    pmid: str
    title: str
    finding: str  # head of the title + abstract, whitespace-folded
    year: str = ""


def _esearch(term: str, retmax: int = 5, timeout: int = 10) -> list[str]:
    """Return PubMed IDs for a query term (relevance-sorted)."""
    try:
        resp = requests.get(
            PUBMED_ESEARCH,
            params={"db": "pubmed", "term": term, "retmax": retmax,
                    "retmode": "json", "sort": "relevance"},
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json().get("esearchresult", {}).get("idlist", [])
    except Exception as exc:
        logger.warning("[Comparator/Lit] esearch failed for %r: %s", term, exc)
        return []


def _snippet(text: str, width: int = 260) -> str:
    """The first ``width`` characters of ``text``, whitespace-folded."""
    return re.sub(r"\s+", " ", text[:width]).strip()


def _evidence_from_pmids(pmids: list[str]) -> list[Evidence]:
    """Batch-fetch abstracts and return one Evidence per PMID that resolved."""
    papers = fetch_pubmed_abstracts(pmids)  # one efetch request for all PMIDs
    if pmids:
        time.sleep(_NCBI_COURTESY_DELAY)  # one courtesy delay per batch, not per paper
    out: list[Evidence] = []
    for pmid in pmids:  # preserve PubMed relevance order
        paper = papers.get(str(pmid))
        if not paper:
            continue
        text = f"{paper.title} {paper.abstract}"
        out.append(Evidence(pmid=pmid, title=paper.title, finding=_snippet(text)))
    return out
