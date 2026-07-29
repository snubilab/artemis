"""Comparator recommender (ADR-028) — literature-grounded, HITL-proposed.

For a placebo-controlled trial (no real-world placebo cohort), recommend a
cardiovascular-neutral ACTIVE comparator. Pipeline:
  1-3. acquire PubMed evidence per candidate class (see literature.py)
  4.   classify each class's CV effect on the outcome (LLM over the evidence)
  5.   rank: prefer CV-neutral, precedent-supported classes
  6.   emit a PROPOSAL artifact (status='proposed') for human approval

The gate NEVER auto-applies — the artifact is a proposal for HITL review.
LLM classification runs on the local vLLM Qwen (VLLM_BASE_URL, model
COMPARATOR_LLM_MODEL). If the vLLM server is unreachable it degrades gracefully:
it still returns the evidence with verdict='unknown' (evidence-only).
"""
from __future__ import annotations

import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from typing import Optional

from src.agents.comparator.literature import (
    CandidateEvidence,
    LiteratureBundle,
    acquire_evidence,
)

logger = logging.getLogger(__name__)

# vLLM-served Qwen model. Prefix 'vllm/' routes get_llm() to VLLM_BASE_URL.
# Unset means "whatever LLM_MODEL says", so one setting moves the whole pipeline.
# This used to pin vllm/snuh/hari-q3-8b, which meant the comparator silently ran a
# different model from every other stage and no configuration change could align them.
DEFAULT_LLM_MODEL = os.getenv("COMPARATOR_LLM_MODEL") or None

_VERDICTS = ("beneficial", "neutral", "harmful", "unknown")


@dataclass
class ClassVerdict:
    drug_class: str
    verdict: str = "unknown"          # beneficial | neutral | harmful | unknown
    confidence: float = 0.0
    supporting_pmids: list[str] = field(default_factory=list)
    caveat: str = ""
    precedent_supported: bool = False


@dataclass
class RecommendationArtifact:
    trigger: dict
    candidates: list[ClassVerdict] = field(default_factory=list)
    recommendation: Optional[dict] = None   # {class, rationale, alternatives}
    caveats: list[str] = field(default_factory=list)
    evidence: Optional[dict] = None          # full LiteratureBundle dict (provenance)
    status: str = "proposed"                 # proposed -> approved | overridden (HITL)


_CLASSIFY_PROMPT = """You are a cardiovascular pharmacoepidemiologist selecting an ACTIVE COMPARATOR for a real-world emulation of a placebo-controlled cardiovascular outcome trial.

Classify the effect of the drug class "{drug_class}" on the outcome "{outcome}" in {indication}, versus placebo/standard care, based ONLY on the PubMed findings below.

Return ONLY a JSON object (keep it short):
{{"verdict": "beneficial|neutral|harmful|unknown", "confidence": 0.0-1.0, "caveat": "<=12 words, e.g. a heart-failure signal"}}

"neutral" means no meaningful increase or decrease in the outcome vs placebo (the desired property for an active comparator). Use "unknown" if the findings are insufficient.

Findings:
{findings}
"""


def _vllm_reachable(timeout: float = 2.0) -> bool:
    """Fast TCP probe so a down vLLM server degrades instantly (no hang on invoke)."""
    import socket
    import urllib.parse

    from src.settings import settings

    if not settings.VLLM_BASE_URL:
        return False
    u = urllib.parse.urlparse(settings.VLLM_BASE_URL)
    try:
        with socket.create_connection((u.hostname, u.port or 80), timeout=timeout):
            return True
    except Exception:
        return False


def _get_llm():
    from src.utils.llm import get_llm
    return get_llm(model_name=DEFAULT_LLM_MODEL, temperature=0.0)


def _classify(cand: CandidateEvidence, indication: str, outcome: str, llm) -> ClassVerdict:
    cv = ClassVerdict(drug_class=cand.drug_class,
                      supporting_pmids=[e.pmid for e in cand.cv_effect_evidence])
    findings = "\n".join(
        f"- [{e.pmid}] {e.title}: {e.finding}"
        for e in (cand.cv_effect_evidence + cand.refutation_evidence)
    ) or "(no findings retrieved)"
    if llm is None or not cand.cv_effect_evidence:
        return cv  # verdict stays 'unknown'
    try:
        from langchain_core.messages import HumanMessage

        prompt = _CLASSIFY_PROMPT.format(
            drug_class=cand.drug_class, outcome=outcome,
            indication=indication, findings=findings[:6000],
        ) + "\n/no_think"  # Qwen3 reasoning models: skip chain-of-thought, emit JSON directly
        content = llm.invoke([HumanMessage(content=prompt)]).content.strip()
        # Reasoning models may still wrap a <think>…</think> block — drop it before JSON parse.
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            content = content[4:] if content.startswith("json") else content
        data = json.loads(re.search(r"\{.*\}", content, re.DOTALL).group(0))
        v = str(data.get("verdict", "unknown")).lower()
        cv.verdict = v if v in _VERDICTS else "unknown"
        cv.confidence = float(data.get("confidence", 0.0) or 0.0)
        cv.caveat = str(data.get("caveat", "") or "")  # supporting_pmids kept from evidence
    except Exception as exc:
        logger.warning("[Comparator/Rec] classify failed for %s: %s", cand.drug_class, exc)
    return cv


def _rank_key(cv: ClassVerdict):
    # Prefer: neutral first, precedent-supported, higher confidence, more evidence.
    verdict_rank = {"neutral": 0, "unknown": 1, "beneficial": 2, "harmful": 3}
    return (
        verdict_rank.get(cv.verdict, 4),
        0 if cv.precedent_supported else 1,
        -cv.confidence,
        -len(cv.supporting_pmids),
    )


def recommend_comparator(
    treatment_drug: str,
    indication: str,
    outcome: str,
    candidates: list[dict],
    *,
    trial_name: Optional[str] = None,
) -> RecommendationArtifact:
    """Produce a HITL comparator PROPOSAL grounded in PubMed evidence (ADR-028).

    candidates: the data-driven candidate classes to evaluate (treatment's CDM ATC
    siblings), each {"drug_class", "ingredients"}. Required — no built-in list.
    """
    bundle: LiteratureBundle = acquire_evidence(
        treatment_drug, indication, outcome,
        candidates=candidates, trial_name=trial_name,
    )

    # which classes are named in the trial's real-world-emulation precedent?
    precedent_text = " ".join(
        f"{e.title} {e.finding}" for e in bundle.rwd_precedent
    ).lower()

    llm = None
    if _vllm_reachable():
        try:
            llm = _get_llm()
        except Exception as exc:
            logger.warning("[Comparator/Rec] LLM build failed (%s)", exc)
    else:
        logger.warning("[Comparator/Rec] vLLM unreachable; returning unclassified evidence")

    def _one(cand: CandidateEvidence) -> ClassVerdict:
        cv = _classify(cand, indication, outcome, llm)
        cv.precedent_supported = cand.drug_class.split()[0].lower() in precedent_text
        return cv

    # Classify candidates concurrently — each is an independent vLLM HTTP call.
    if bundle.candidates:
        with ThreadPoolExecutor(max_workers=min(8, len(bundle.candidates))) as ex:
            verdicts = list(ex.map(_one, bundle.candidates))
    else:
        verdicts = []

    verdicts.sort(key=_rank_key)
    classified = any(v.verdict != "unknown" for v in verdicts)

    artifact = RecommendationArtifact(
        trigger={"treatment_drug": treatment_drug, "indication": indication,
                 "outcome": outcome, "trial_name": trial_name},
        candidates=verdicts,
        evidence=asdict(bundle),
    )

    top = next((v for v in verdicts if v.verdict == "neutral"), None)
    if not classified:
        artifact.caveats.append(
            "CV-neutrality not classified (vLLM/Qwen unreachable) — evidence gathered only. "
            "Bring the vLLM server up and set COMPARATOR_LLM_MODEL, then re-run classification."
        )
    if top is not None:
        alts = [v.drug_class for v in verdicts if v is not top and v.verdict in ("neutral", "unknown")][:2]
        artifact.recommendation = {
            "class": top.drug_class,
            "rationale": (f"CV-neutral on {outcome} (confidence {top.confidence:.2f}); "
                          + ("named in prior real-world emulation of this trial; " if top.precedent_supported else "")
                          + f"evidence: {', '.join(top.supporting_pmids[:4])}."),
            "alternatives": alts,
        }
        if top.caveat:
            artifact.caveats.append(f"{top.drug_class}: {top.caveat}")
    return artifact


_LIT_EXTRACT_PROMPT = """You are a cardiovascular pharmacoepidemiologist designing an ACTIVE-COMPARATOR NEW-USER study to emulate a PLACEBO-controlled trial of {treatment} ({treatment_class}) for {indication}, primary outcome {outcome}.

There is no real-world placebo cohort, so choose a CV-NEUTRAL ACTIVE COMPARATOR: a drug used at the SAME treatment line, route, and setting as the treatment that has NO meaningful effect on {outcome} (behaves like placebo). REJECT drugs that reduce or increase {outcome}; REJECT wrong-modality drugs (e.g. an acute parenteral drug standing in for a chronic oral one); REJECT the treatment's own class and background standard-of-care that both arms already take.

Using ONLY the literature below (prior emulations, comparative-effectiveness studies, methods papers), list the recommended active-comparator DRUG CLASSES, BEST FIRST. Prefer classes that prior real-world emulations of this drug/class actually used. Give member ingredient drugs so each can be found in a database.

Return ONLY JSON:
{{"candidates":[{{"drug_class":"...","ingredients":["ingredient1","ingredient2"],"verdict":"neutral|beneficial|harmful","same_setting":true,"rationale":"one line with PMIDs"}}]}}

Literature:
{lit}
/no_think"""


def _comparator_queries(treatment, treatment_class, indication, outcome, trial):
    return [
        f'("{trial}"[Title/Abstract]) AND (emulation OR observational OR "comparative effectiveness") AND (comparator OR "active comparator")',
        f'("{treatment}" OR "{treatment_class}") AND ("active comparator" OR emulation OR "new-user" OR "comparative effectiveness") AND ({outcome} OR cardiovascular) AND ({indication})',
        f'("{treatment_class}") AND "active comparator" AND ({indication})',
    ]


def _fetch_comparator_docs(queries, outcome):
    from src.agents.comparator.literature import _esearch, _evidence_from_pmids
    seen, docs = set(), []
    for t in queries:
        for e in _evidence_from_pmids(_esearch(t, 8), ["comparator", "active comparator", "emulat", "neutral", outcome]):
            if e.pmid not in seen:
                seen.add(e.pmid)
                docs.append({"pmid": e.pmid, "title": e.title, "finding": e.finding})
    return docs


def _evidence_dir():
    from pathlib import Path
    d = os.getenv("COMPARATOR_EVIDENCE_DIR")
    return Path(d) if d else Path(__file__).resolve().parents[3] / "data" / "comparator_literature"


def _evidence_slug(key):
    return re.sub(r"[^a-z0-9]+", "_", (key or "comparator").lower()).strip("_") or "comparator"


def _load_evidence_snapshot(key):
    p = _evidence_dir() / f"{_evidence_slug(key)}.json"
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            return None
    return None


def _save_evidence_snapshot(key, payload):
    """Persist the searched documents (+queries, extraction) as an immutable snapshot so
    the recommendation is reproducible even as PubMed drifts."""
    try:
        from datetime import datetime, timezone
        d = _evidence_dir()
        d.mkdir(parents=True, exist_ok=True)
        rec = dict(payload)
        rec["saved_at"] = datetime.now(timezone.utc).isoformat()
        (d / f"{_evidence_slug(key)}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2))
    except Exception as exc:
        logger.warning("[Comparator/Rec] snapshot save failed: %s", exc)


def recommend_from_literature(treatment_drug, treatment_class, indication, outcome, *,
                              trial_name=None, use_cache=True, save=True):
    """Literature-FIRST comparator discovery (ADR-028 revised): let prior emulations /
    comparative-effectiveness studies NAME the CV-neutral active comparator, instead of
    blindly enumerating ATC siblings. Returns a dict with a ranked candidate list; the
    caller CDM-grounds the ingredients (feasibility) and proposes to a human.

    The searched documents are SNAPSHOTTED locally (data/comparator_literature/<key>.json)
    for reproducibility: with use_cache=True a saved snapshot PINS the literature (skips
    PubMed) so the pick does not drift; delete the snapshot or pass use_cache=False to refresh."""
    key = trial_name or treatment_drug
    queries = _comparator_queries(
        treatment_drug, treatment_class, indication, outcome, trial_name or treatment_drug)

    snap = _load_evidence_snapshot(key) if use_cache else None
    if snap and snap.get("documents"):
        docs, source = snap["documents"], "cache"
    else:
        docs, source = _fetch_comparator_docs(queries, outcome), "pubmed"

    lit = "\n".join(f"- [{d['pmid']}] {d['title']}: {d['finding']}" for d in docs)[:8000] or "(no literature retrieved)"
    out = {"trigger": {"treatment": treatment_drug, "class": treatment_class,
                       "indication": indication, "outcome": outcome, "trial": trial_name},
           "queries": queries, "n_papers": len(docs), "source": source,
           "documents": docs, "candidates": [], "recommendation": None}
    if not _vllm_reachable():
        out["caveat"] = "vLLM unreachable — literature gathered only"
        if save and source == "pubmed":
            _save_evidence_snapshot(key, out)
        return out
    try:
        from langchain_core.messages import HumanMessage

        content = _get_llm().invoke([HumanMessage(content=_LIT_EXTRACT_PROMPT.format(
            treatment=treatment_drug, treatment_class=treatment_class,
            indication=indication, outcome=outcome, lit=lit))]).content.strip()
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            content = content[4:] if content.startswith("json") else content
        data = json.loads(re.search(r"\{.*\}", content, re.DOTALL).group(0))
        norm = []
        for c in (data.get("candidates") or []):
            v = str(c.get("verdict", "unknown")).lower()
            norm.append({
                "drug_class": str(c.get("drug_class", "")).strip(),
                "ingredients": [str(i).strip() for i in (c.get("ingredients") or []) if str(i).strip()],
                "verdict": v if v in _VERDICTS else "unknown",
                "same_setting": bool(c.get("same_setting", True)),
                "rationale": str(c.get("rationale", "") or ""),
            })
        out["candidates"] = norm
        # top proposal: neutral, same setting, and has ingredients to ground in the CDM
        out["recommendation"] = next(
            (c for c in norm if c["verdict"] == "neutral" and c["same_setting"] and c["ingredients"]), None)
    except Exception as exc:
        logger.warning("[Comparator/Rec] literature-first extract failed: %s", exc)
        out["caveat"] = f"extract failed: {exc}"
    if save and source == "pubmed":
        _save_evidence_snapshot(key, out)  # immutable snapshot of the freshly-searched docs
    return out


def to_dict(a: RecommendationArtifact) -> dict:
    return asdict(a)


if __name__ == "__main__":  # live check (acquisition always; classification needs vLLM up)
    # candidates are normally CDM-discovered; an explicit minimal set here.
    cands = [
        {"drug_class": "DPP-4 inhibitors",
         "ingredients": ["sitagliptin", "saxagliptin", "linagliptin", "alogliptin"]},
        {"drug_class": "Sulfonylureas", "ingredients": ["glimepiride", "glipizide"]},
    ]
    a = recommend_comparator(
        "empagliflozin", "Type 2 Diabetes", "MACE", cands,
        trial_name="EMPA-REG OUTCOME",
    )
    print("candidates (ranked):")
    for c in a.candidates:
        print(f"  {c.drug_class:<26} verdict={c.verdict:<10} conf={c.confidence:.2f} "
              f"precedent={c.precedent_supported} pmids={c.supporting_pmids[:3]}")
    print("recommendation:", a.recommendation)
    print("caveats:", a.caveats)
    print("status:", a.status)
    assert a.candidates, "no candidates"
    assert a.status == "proposed", "must be a proposal (HITL), never auto-applied"
    print("self-check OK")
