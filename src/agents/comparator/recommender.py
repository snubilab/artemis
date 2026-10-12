"""Comparator recommender (ADR-028) — literature-first, HITL-proposed.

For a placebo-controlled trial (no real-world placebo cohort), propose a
cardiovascular-neutral ACTIVE comparator: PubMed records found by
:func:`_comparator_queries` are handed to the LLM, which names the candidate classes
(:func:`recommend_from_literature`). The proposal is NEVER auto-applied — the caller
logs it for HITL review. LLM calls go to the configured model (COMPARATOR_LLM_MODEL,
else LLM_MODEL); if the vLLM server is unreachable it returns the literature only.
"""
from __future__ import annotations

import json
import logging
import os
import re

logger = logging.getLogger(__name__)

# vLLM-served Qwen model. Prefix 'vllm/' routes get_llm() to VLLM_BASE_URL.
# Unset means "whatever LLM_MODEL says", so one setting moves the whole pipeline.
# This used to pin vllm/snuh/hari-q3-8b, which meant the comparator silently ran a
# different model from every other stage and no configuration change could align them.
DEFAULT_LLM_MODEL = os.getenv("COMPARATOR_LLM_MODEL") or None

_VERDICTS = ("beneficial", "neutral", "harmful", "unknown")


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
    return get_llm(model_name=DEFAULT_LLM_MODEL, temperature=0.0, json_mode=True)


_LIT_EXTRACT_PROMPT = """You are a cardiovascular pharmacoepidemiologist designing an ACTIVE-COMPARATOR NEW-USER study to emulate a PLACEBO-controlled trial of {treatment} ({treatment_class}) for {indication}, primary outcome {outcome}.

There is no real-world placebo cohort, so choose a CV-NEUTRAL ACTIVE COMPARATOR: a drug used at the SAME treatment line, route, and setting as the treatment that has NO meaningful effect on {outcome} (behaves like placebo). REJECT drugs that reduce or increase {outcome}; REJECT wrong-modality drugs, whose route or duration of use differs from the treatment's; REJECT the treatment's own class and background standard-of-care that both arms already take.

Using ONLY the literature below (prior emulations, comparative-effectiveness studies, methods papers), list the recommended active-comparator DRUG CLASSES, BEST FIRST. Prefer classes that prior real-world emulations of this drug/class actually used. Give member ingredient drugs so each can be found in a database.

Return ONLY JSON:
{{"candidates":[{{"drug_class":"<drug class name>","ingredients":["<ingredient name>", ...],"verdict":"<neutral|beneficial|harmful>","same_setting":<true|false>,"rationale":"<one line citing the supporting PMIDs>"}}]}}

Literature:
{lit}
/no_think"""


def _comparator_queries(treatment, treatment_class, indication, outcome, trial):
    return [
        f'("{trial}"[Title/Abstract]) AND (emulation OR observational OR "comparative effectiveness") AND (comparator OR "active comparator")',
        f'("{treatment}" OR "{treatment_class}") AND ("active comparator" OR emulation OR "new-user" OR "comparative effectiveness") AND ({outcome} OR cardiovascular) AND ({indication})',
        f'("{treatment_class}") AND "active comparator" AND ({indication})',
    ]


def _fetch_comparator_docs(queries):
    from src.agents.comparator.literature import _esearch, _evidence_from_pmids
    seen, docs = set(), []
    for t in queries:
        for e in _evidence_from_pmids(_esearch(t, 8)):
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
        docs, source = _fetch_comparator_docs(queries), "pubmed"

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
