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
from dataclasses import asdict, dataclass, field
from typing import Optional

from src.agents.comparator.literature import (
    CandidateEvidence,
    LiteratureBundle,
    acquire_evidence,
)

logger = logging.getLogger(__name__)

# vLLM-served Qwen model. Prefix 'vllm/' routes get_llm() to VLLM_BASE_URL.
# Default matches the Qwen3-8B this host's vLLM serves on :8000; override with
# COMPARATOR_LLM_MODEL to point at whatever model the target vLLM actually serves.
DEFAULT_LLM_MODEL = os.getenv("COMPARATOR_LLM_MODEL", "vllm/snuh/hari-q3-8b")

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

Return ONLY a JSON object:
{{"verdict": "beneficial|neutral|harmful|unknown", "confidence": 0.0-1.0, "supporting_pmids": ["..."], "caveat": "short note, e.g. an outcome-specific signal like heart failure"}}

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
        if data.get("supporting_pmids"):
            cv.supporting_pmids = [str(p) for p in data["supporting_pmids"]]
        cv.caveat = str(data.get("caveat", "") or "")
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
    *,
    trial_name: Optional[str] = None,
    treatment_class: Optional[str] = None,
) -> RecommendationArtifact:
    """Produce a HITL comparator PROPOSAL grounded in PubMed evidence (ADR-028)."""
    bundle: LiteratureBundle = acquire_evidence(
        treatment_drug, indication, outcome,
        trial_name=trial_name, treatment_class=treatment_class,
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

    verdicts: list[ClassVerdict] = []
    for cand in bundle.candidates:
        cv = _classify(cand, indication, outcome, llm)
        cv.precedent_supported = cand.drug_class.split()[0].lower() in precedent_text
        verdicts.append(cv)

    verdicts.sort(key=_rank_key)
    classified = any(v.verdict != "unknown" for v in verdicts)

    artifact = RecommendationArtifact(
        trigger={"treatment_drug": treatment_drug, "indication": indication,
                 "outcome": outcome, "trial_name": trial_name,
                 "treatment_class": treatment_class},
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


def to_dict(a: RecommendationArtifact) -> dict:
    return asdict(a)


if __name__ == "__main__":  # live check (acquisition always; classification needs vLLM up)
    a = recommend_comparator(
        "empagliflozin", "Type 2 Diabetes", "MACE",
        trial_name="EMPA-REG OUTCOME", treatment_class="SGLT2 inhibitors",
    )
    print("candidates (ranked):")
    for c in a.candidates:
        print(f"  {c.drug_class:<26} verdict={c.verdict:<10} conf={c.confidence:.2f} "
              f"precedent={c.precedent_supported} pmids={c.supporting_pmids[:3]}")
    print("recommendation:", a.recommendation)
    print("caveats:", a.caveats)
    print("status:", a.status)
    assert a.candidates, "no candidates"
    assert "SGLT2 inhibitors" not in [c.drug_class for c in a.candidates], "treatment class not excluded"
    assert a.status == "proposed", "must be a proposal (HITL), never auto-applied"
    print("self-check OK")
