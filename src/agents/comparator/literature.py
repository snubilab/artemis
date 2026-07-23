"""Comparator recommender — literature acquisition (ADR-028 stages 1-3).

For a placebo-controlled trial there is no real-world placebo cohort, so a
cardiovascular-neutral ACTIVE comparator must be substituted. This module
gathers the PubMed evidence needed to later recommend one: for the treatment
drug + indication + primary outcome it retrieves, per candidate active-comparator
drug class, (a) the trial's prior real-world-emulation precedent, (b) that
class's cardiovascular effect on the outcome, and (c) refuting evidence.

Scope: ACQUISITION ONLY. Ranking, neutrality classification, HITL, and cohort
building are later stages (see ADR-028). Reuses agent1's PubMed efetch client.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Optional

import requests

from src.agents.agent1.pubmed_fetcher import fetch_pubmed_abstracts

logger = logging.getLogger(__name__)

PUBMED_ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
_NCBI_COURTESY_DELAY = 0.34  # ~3 req/s without an API key

# Cardiovascular-outcome terms; an on-topic CV paper mentions at least one.
_CV_TERMS = ["cardiovascular", "mace", "myocardial", "stroke", "cardiovascular death",
             "heart failure", "hazard ratio", "atherosclerotic"]


def _text_has_any(text: str, terms: list[str]) -> bool:
    low = text.lower()
    return any(t.lower() in low for t in terms)


@dataclass
class Evidence:
    pmid: str
    title: str
    finding: str  # snippet around the effect keyword
    year: str = ""


@dataclass
class CandidateEvidence:
    drug_class: str
    cv_effect_evidence: list[Evidence] = field(default_factory=list)
    refutation_evidence: list[Evidence] = field(default_factory=list)


@dataclass
class LiteratureBundle:
    treatment_drug: str
    indication: str
    outcome: str
    rwd_precedent: list[Evidence] = field(default_factory=list)
    candidates: list[CandidateEvidence] = field(default_factory=list)


def _norm(s: Optional[str]) -> str:
    return " ".join((s or "").split()).strip()


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


def _snippet(text: str, keywords: list[str], width: int = 260) -> str:
    """A short snippet around the first keyword hit — the human-readable finding."""
    low = text.lower()
    for kw in keywords:
        idx = low.find(kw.lower())
        if idx >= 0:
            start = max(0, idx - width // 3)
            return re.sub(r"\s+", " ", text[start:start + width]).strip()
    return re.sub(r"\s+", " ", text[:width]).strip()


def _evidence_from_pmids(
    pmids: list[str],
    keywords: list[str],
    require_all: list[list[str]] | None = None,
) -> list[Evidence]:
    """Batch-fetch abstracts and keep only relevant ones.

    require_all: list of term-groups; a paper is kept only if its title+abstract
    matches at least one term in EVERY group (e.g. [class_terms, cv_terms]).
    """
    papers = fetch_pubmed_abstracts(pmids)  # one efetch request for all PMIDs
    if pmids:
        time.sleep(_NCBI_COURTESY_DELAY)  # one courtesy delay per batch, not per paper
    out: list[Evidence] = []
    for pmid in pmids:  # preserve PubMed relevance order
        paper = papers.get(str(pmid))
        if not paper:
            continue
        text = f"{paper.title} {paper.abstract}"
        if require_all and not all(_text_has_any(text, grp) for grp in require_all):
            continue  # wrong-class or off-topic — drop the citation
        out.append(Evidence(pmid=pmid, title=paper.title,
                             finding=_snippet(text, keywords)))
    return out


def acquire_evidence(
    treatment_drug: str,
    indication: str,
    outcome: str,
    *,
    candidates: list[dict],
    trial_name: Optional[str] = None,
    per_query: int = 4,
    candidate_limit: int = 10,
) -> LiteratureBundle:
    """Gather PubMed evidence for later comparator recommendation (ADR-028 1-3).

    candidates: the data-driven candidate classes to evaluate, each
    {"drug_class": str, "ingredients": [str, ...]} — e.g. the treatment drug's ATC
    siblings discovered from the CDM vocabulary. Required; there is no built-in list.
    """
    treatment_drug = _norm(treatment_drug)
    indication = _norm(indication)
    outcome = _norm(outcome)
    bundle = LiteratureBundle(treatment_drug=treatment_drug,
                              indication=indication, outcome=outcome)

    # (1) Precedent: prior real-world emulation of THIS trial and its comparator.
    trial = _norm(trial_name) or treatment_drug
    precedent_term = (
        f'("{trial}"[Title/Abstract]) '
        f'AND (emulation OR "real-world" OR observational OR "comparative effectiveness") '
        f'AND (comparator OR "active comparator")'
    )
    bundle.rwd_precedent = _evidence_from_pmids(
        _esearch(precedent_term, per_query),
        ["comparator", "emulat", "real-world", "active comparator"],
    )

    # (2)+(3) Per candidate class: CV-effect evidence + refuting evidence.
    # Every kept citation must mention the class (or a member ingredient) AND a
    # cardiovascular term — the relevance gate that stops wrong-class/off-topic PMIDs.
    cand_specs = [(c["drug_class"], list(c.get("ingredients") or []))
                  for c in (candidates or [])][:candidate_limit]

    for cls, ingredients in cand_specs:
        cand = CandidateEvidence(drug_class=cls)
        # Drug clause = class name OR member ingredients — maximises PubMed recall for
        # verbose ATC class names (e.g. "Dipeptidyl peptidase 4 (DPP-4) inhibitors").
        drug_clause = " OR ".join(f'"{t}"' for t in ([cls] + ingredients[:8]))
        class_terms = ingredients + [cls]
        cv_gate = [class_terms, _CV_TERMS + [outcome]]
        cv_term = (
            f'({drug_clause}) '
            f'AND ("{outcome}" OR "cardiovascular outcomes" OR MACE OR "cardiovascular safety") '
            f'AND ({indication}) AND (trial OR "meta-analysis" OR placebo)'
        )
        cand.cv_effect_evidence = _evidence_from_pmids(
            _esearch(cv_term, per_query * 2),  # fetch more; the relevance gate drops some
            [cls, "cardiovascular", "hazard", "MACE", outcome, "neutral"],
            require_all=cv_gate,
        )
        refute_term = (
            f'({drug_clause}) '
            f'AND (cardiovascular OR "heart failure") AND (increase OR risk OR harm OR adverse)'
        )
        cand.refutation_evidence = _evidence_from_pmids(
            _esearch(refute_term, max(3, per_query)),
            ["risk", "increase", "heart failure", "harm"],
            require_all=cv_gate,
        )
        bundle.candidates.append(cand)

    return bundle


def to_dict(bundle: LiteratureBundle) -> dict:
    return asdict(bundle)


if __name__ == "__main__":  # live self-check (needs network)
    # relevance gate (offline, deterministic): wrong-class paper must be rejected.
    assert not _text_has_any("oral semaglutide cardiovascular outcomes SOUL trial",
                             ["metformin", "biguanide"]), "gate lets wrong-class through"
    assert _text_has_any("sitagliptin cardiovascular safety TECOS",
                         ["sitagliptin", "dpp-4"]), "gate rejects correct class"

    # candidates are injected (normally CDM-discovered); a minimal explicit set here.
    cands = [
        {"drug_class": "DPP-4 inhibitors",
         "ingredients": ["sitagliptin", "saxagliptin", "linagliptin", "alogliptin"]},
        {"drug_class": "Sulfonylureas", "ingredients": ["glimepiride", "glipizide", "gliclazide"]},
    ]
    b = acquire_evidence("empagliflozin", "Type 2 Diabetes", "MACE",
                         candidates=cands, trial_name="EMPA-REG OUTCOME")
    classes = [c.drug_class for c in b.candidates]
    print("candidates:", classes)
    print("precedent PMIDs:", [e.pmid for e in b.rwd_precedent])
    for c in b.candidates:
        print(f"  {c.drug_class}: cv={[e.pmid for e in c.cv_effect_evidence]} "
              f"refute={[e.pmid for e in c.refutation_evidence]}")
    assert classes == ["DPP-4 inhibitors", "Sulfonylureas"], f"unexpected: {classes}"
    got = sum(len(c.cv_effect_evidence) for c in b.candidates)
    assert got > 0, "no CV evidence retrieved (network/PubMed issue?)"
    print(f"self-check OK: {len(classes)} candidates, {got} CV-evidence papers")
