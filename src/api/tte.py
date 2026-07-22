"""FastAPI router for the TTE integration MVP."""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pydantic import BaseModel

from src.api.models.tte import (
    ArtifactApplyRequest,
    ArtifactApplyResponse,
    CapabilityRunResponse,
    CircePreviewResponse,
    CriterionMappingMetadata,
    DataSourceOption,
    EvaluateAnalysisStrategyRequest,
    ExecuteRequest,
    ExecuteResponse,
    FullPipelineResponse,
    GenerateRequest,
    GenerateResponse,
    NCTGenerateRequest,
    ReRecommendRequest,
    ReportHtmlExportResponse,
    ReportPdfExportResponse,
    TTEArtifact,
    TTEJob,
    TTEStudy,
)
from src.pipeline.webapi_client import WebAPIError
from src.services.tte_service import TTEService
from src.services.tte_store import TTEStore
from src.settings import settings
from src.utils.llm import list_available_models

router = APIRouter(prefix="/tte", tags=["TTE"])

PAPERS_DIR = Path(__file__).resolve().parents[2] / "data" / "papers"


@lru_cache(maxsize=1)
def get_tte_service() -> TTEService:
    store_path = os.getenv("TTE_STORE_PATH", "/app/tmp/tte/studies.json")
    return TTEService(TTEStore(store_path))


@router.get("/models")
async def get_available_models() -> dict:
    """Return list of available LLM models for the UI selector."""
    models = await list_available_models()
    return {"models": models, "defaultModel": settings.LLM_MODEL}


@router.post("/generate", response_model=GenerateResponse)
async def generate_protocol(request: GenerateRequest) -> GenerateResponse:
    return get_tte_service().generate_draft(request.naturalLanguageDescription, model_name=request.model)


@router.post("/studies/{study_id}/generate-draft", response_model=CapabilityRunResponse)
async def generate_draft_for_study(study_id: int, request: GenerateRequest) -> CapabilityRunResponse:
    try:
        return get_tte_service().run_generate_draft(
            study_id, request.naturalLanguageDescription, model_name=request.model
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/studies/{study_id}/generate-from-nct", response_model=CapabilityRunResponse)
async def generate_from_nct_for_study(
    study_id: int, request: NCTGenerateRequest
) -> CapabilityRunResponse:
    try:
        return get_tte_service().run_generate_from_nct(
            study_id, request.nctId,
            force_refresh=request.forceRefresh,
            model_name=request.model,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/studies/{study_id}/validate", response_model=CapabilityRunResponse)
async def validate_design(study_id: int) -> CapabilityRunResponse:
    try:
        return get_tte_service().validate_design(study_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/studies/{study_id}/suggest-eligibility", response_model=CapabilityRunResponse)
async def suggest_eligibility(study_id: int) -> CapabilityRunResponse:
    try:
        return get_tte_service().suggest_eligibility(study_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@router.post("/studies/{study_id}/process-eligibility", response_model=CapabilityRunResponse)
async def process_eligibility(study_id: int) -> CapabilityRunResponse:
    import asyncio

    def run_sync():
        return get_tte_service().process_eligibility(study_id)

    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, run_sync)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/studies/{study_id}/process-eligibility-progress")
async def process_eligibility_progress(study_id: int):
    """Poll mapping progress during process-eligibility."""
    latest_job = get_tte_service().get_latest_job_for_study(
        study_id=study_id,
        capability="process_eligibility",
    )
    if latest_job is None:
        return {"phase": "idle"}

    meta = latest_job.meta or {}
    progress = dict(meta.get("progress") or {})
    if not progress:
        progress = {"phase": "starting" if latest_job.status == "running" else latest_job.status}

    progress["jobId"] = latest_job.id
    progress["jobStatus"] = latest_job.status
    if latest_job.artifactId:
        progress["artifactId"] = latest_job.artifactId
    if meta.get("summary"):
        progress["summary"] = meta["summary"]
    if latest_job.error:
        progress["error"] = latest_job.error
    return progress


@router.get(
    "/studies/{study_id}/criteria/{criterion_id}/mapping-candidates",
    response_model=CriterionMappingMetadata,
    summary="Get AI mapping candidates for a specific criterion",
)
async def get_mapping_candidates(study_id: int, criterion_id: int) -> CriterionMappingMetadata:
    """Return AI mapping candidates generated during process-eligibility.

    Returns 404 if no mapping metadata is found for this criterion.
    """
    try:
        artifacts = get_tte_service().list_artifacts(study_id)
        eligibility_artifacts = [
            a for a in artifacts
            if (a.get("kind") if isinstance(a, dict) else a.kind) == "eligibility_processing"
        ]
        if not eligibility_artifacts:
            raise HTTPException(status_code=404, detail="No eligibility processing artifact found")

        latest = eligibility_artifacts[-1]
        artifact_id = latest.get("id") if isinstance(latest, dict) else latest.id
        artifact = get_tte_service().get_artifact(artifact_id)

        payload = artifact.get("payload") if isinstance(artifact, dict) else artifact.payload
        criterion_meta_map = (payload or {}).get("criterionMappingMetadata") or {}
        meta = criterion_meta_map.get(str(criterion_id))
        if not meta:
            # Fallback 1: stored rule-index-keyed metadata (new artifacts)
            rule_index_meta = (payload or {}).get("ruleIndexMeta") or {}
            meta = rule_index_meta.get(str(criterion_id))
        if not meta and criterion_meta_map:
            # Fallback 2: treat criterion_id as rule index (0-based) for legacy
            # artifacts that lack ruleIndexMeta. Build mapping on-the-fly from
            # the study's eligibility criteria.
            from src.api.models.tte import DEMOGRAPHIC_DOMAINS
            study = get_tte_service().get_study(study_id)
            eligibility = (study.get("eligibility") if isinstance(study, dict) else study.eligibility) or {}
            mappable_ids: list[str] = []
            for crit in (eligibility.get("inclusionCriteria") or []) + (eligibility.get("exclusionCriteria") or []):
                domain = (crit.get("domain") or "").strip()
                if domain in DEMOGRAPHIC_DOMAINS or crit.get("isGroupLabel"):
                    continue
                cid = crit.get("id")
                if cid is not None:
                    mappable_ids.append(str(cid))
            if 0 <= criterion_id < len(mappable_ids):
                meta = criterion_meta_map.get(mappable_ids[criterion_id])
        if not meta:
            raise HTTPException(
                status_code=404,
                detail=f"No mapping metadata found for criterion {criterion_id}",
            )

        return CriterionMappingMetadata.model_validate(meta)
    except HTTPException:
        raise
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/studies/{study_id}/criteria/{criterion_id}/re-recommend",
    response_model=CriterionMappingMetadata,
    summary="Re-run AI mapping for a specific criterion with optional hint",
)
async def re_recommend_criterion(
    study_id: int,
    criterion_id: int,
    request: ReRecommendRequest,
    group: str = "any",
) -> CriterionMappingMetadata:
    """Re-run the mapping pipeline for a criterion with an optional refinement hint.

    Returns fresh candidates WITHOUT modifying the existing concept set expression.

    Args:
        group: Which criteria group to search. One of "inclusion", "exclusion", or "any".
               Use "inclusion" or "exclusion" when inclusion and exclusion criteria share
               the same ID to avoid ambiguity. Defaults to "any" (inclusion searched first).
    """
    from src.api.models.tte import DEMOGRAPHIC_DOMAINS

    try:
        study = get_tte_service().get_study(study_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    eligibility = study.get("eligibility") or {} if isinstance(study, dict) else (study.eligibility or {})
    inc = (eligibility.get("inclusionCriteria") or []) if isinstance(eligibility, dict) else (eligibility.inclusionCriteria or [])
    exc_list = (eligibility.get("exclusionCriteria") or []) if isinstance(eligibility, dict) else (eligibility.exclusionCriteria or [])

    if group == "inclusion":
        search_pool = list(inc)
    elif group == "exclusion":
        search_pool = list(exc_list)
    else:
        search_pool = list(inc) + list(exc_list)

    all_criteria = search_pool

    criterion = next(
        (c for c in all_criteria if (c.get("id") if isinstance(c, dict) else c.id) == criterion_id),
        None,
    )
    if criterion is None:
        raise HTTPException(status_code=404, detail=f"Criterion {criterion_id} not found")

    domain = (criterion.get("domain") or "") if isinstance(criterion, dict) else (criterion.domain or "")
    description = (criterion.get("description") or "") if isinstance(criterion, dict) else (criterion.description or "")
    source_text = (criterion.get("sourceText") or "") if isinstance(criterion, dict) else (criterion.sourceText or "")

    if domain.strip() in DEMOGRAPHIC_DOMAINS or not description.strip():
        raise HTTPException(status_code=400, detail="Cannot re-recommend for demographic criterion")

    query = f"{source_text or description} {request.hint}".strip()

    try:
        return get_tte_service().run_mapping_pipeline_for_query(
            query, domain=domain.strip() or None, top_k=request.topK
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/studies/{study_id}/suggest-treatment", response_model=CapabilityRunResponse)
async def suggest_treatment(study_id: int) -> CapabilityRunResponse:
    try:
        return get_tte_service().suggest_treatment(study_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/studies/{study_id}/suggest-outcomes", response_model=CapabilityRunResponse)
async def suggest_outcomes(study_id: int) -> CapabilityRunResponse:
    try:
        return get_tte_service().suggest_outcomes(study_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/studies/{study_id}/generate-seeded-cohorts", response_model=CapabilityRunResponse)
async def generate_seeded_cohorts(study_id: int) -> CapabilityRunResponse:
    try:
        return get_tte_service().generate_seeded_cohorts(study_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WebAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/studies/{study_id}/preview-seeded-cohorts", response_model=CircePreviewResponse)
async def preview_seeded_cohorts(study_id: int) -> CircePreviewResponse:
    try:
        return get_tte_service().preview_seeded_cohorts(study_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


class RegisterRequest(BaseModel):
    previewHash: str


@router.post("/studies/{study_id}/register-seeded-cohorts", response_model=CapabilityRunResponse)
async def register_seeded_cohorts(study_id: int, body: RegisterRequest) -> CapabilityRunResponse:
    try:
        return get_tte_service().register_seeded_cohorts(study_id, body.previewHash)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except WebAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/studies/{study_id}/run-analysis", response_model=CapabilityRunResponse)
async def run_analysis(study_id: int) -> CapabilityRunResponse:
    try:
        return get_tte_service().run_analysis(study_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/studies/{study_id}/evaluate-analysis-strategy", response_model=CapabilityRunResponse)
async def evaluate_analysis_strategy(
    study_id: int, body: EvaluateAnalysisStrategyRequest | None = None
) -> CapabilityRunResponse:
    try:
        request = body or EvaluateAnalysisStrategyRequest()
        return get_tte_service().evaluate_analysis_strategy(
            study_id,
            requested_ps_method=request.requestedPsMethod,
            recommendation_stage=request.stage,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/studies/{study_id}/generate-report-summary", response_model=CapabilityRunResponse)
async def generate_report_summary(study_id: int) -> CapabilityRunResponse:
    try:
        return get_tte_service().generate_report_summary(study_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/studies/{study_id}/export-report-html", response_model=ReportHtmlExportResponse)
async def export_report_html(study_id: int) -> ReportHtmlExportResponse:
    try:
        return get_tte_service().export_report_html(study_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/studies/{study_id}/export-report-pdf", response_model=ReportPdfExportResponse)
async def export_report_pdf(study_id: int) -> ReportPdfExportResponse:
    try:
        return get_tte_service().export_report_pdf(study_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/sources", response_model=list[DataSourceOption])
async def list_sources() -> list[DataSourceOption]:
    try:
        return get_tte_service().list_sources()
    except WebAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/studies", response_model=list[TTEStudy])
async def list_studies() -> list[TTEStudy]:
    studies = get_tte_service().list_studies()
    return [TTEStudy.model_validate(study) for study in studies]


@router.post("/studies", response_model=TTEStudy)
async def create_study(study: TTEStudy) -> TTEStudy:
    created = get_tte_service().create_study(study.model_dump())
    return TTEStudy.model_validate(created)


@router.get("/studies/{study_id}", response_model=TTEStudy)
async def get_study(study_id: int) -> TTEStudy:
    try:
        study = get_tte_service().get_study(study_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return TTEStudy.model_validate(study)


@router.put("/studies/{study_id}", response_model=TTEStudy)
async def update_study(study_id: int, study: TTEStudy) -> TTEStudy:
    try:
        updated = get_tte_service().update_study(study_id, study.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return TTEStudy.model_validate(updated)


@router.delete("/studies/{study_id}")
async def delete_study(study_id: int) -> dict[str, bool]:
    try:
        get_tte_service().delete_study(study_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True}


@router.delete("/studies")
async def clear_studies() -> dict[str, int | bool]:
    deleted_count = get_tte_service().clear_studies()
    return {"ok": True, "deletedCount": deleted_count}


@router.delete("/purge")
async def purge_all_data() -> dict[str, Any]:
    counts = get_tte_service().purge_all_data()
    return {"ok": True, **counts}


@router.post("/studies/{study_id}/copy", response_model=TTEStudy)
async def copy_study(study_id: int) -> TTEStudy:
    try:
        copied = get_tte_service().copy_study(study_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return TTEStudy.model_validate(copied)


@router.post("/studies/{study_id}/execute", response_model=ExecuteResponse)
async def execute_study(study_id: int, request: ExecuteRequest) -> ExecuteResponse:
    try:
        return get_tte_service().execute_study(study_id, request.sourceKey)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except WebAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/studies/{study_id}/run-full-pipeline", response_model=FullPipelineResponse)
async def run_full_pipeline(study_id: int, request: ExecuteRequest) -> FullPipelineResponse:
    try:
        return get_tte_service().run_full_pipeline(study_id, request.sourceKey)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except WebAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/studies/{study_id}/artifacts", response_model=list[TTEArtifact])
async def list_artifacts(study_id: int) -> list[TTEArtifact]:
    try:
        return get_tte_service().list_artifacts(study_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/artifacts/{artifact_id}", response_model=TTEArtifact)
async def get_artifact(artifact_id: str) -> TTEArtifact:
    try:
        return get_tte_service().get_artifact(artifact_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/artifacts/{artifact_id}/apply", response_model=ArtifactApplyResponse)
async def apply_artifact(artifact_id: str, request: ArtifactApplyRequest) -> ArtifactApplyResponse:
    try:
        return get_tte_service().apply_artifact(
            artifact_id, request.targetSections, request.baseStudyVersion
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/jobs/{job_id}", response_model=TTEJob)
async def get_job(job_id: str) -> TTEJob:
    try:
        return get_tte_service().get_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/cache/criterion-mapping")
async def clear_criterion_cache():
    """Clear the criterion mapping cache and return previous stats."""
    from src.agents.agent2.criterion_cache import get_criterion_cache

    cache = get_criterion_cache()
    stats = cache.stats()
    cleared = cache.clear()
    return {
        "cleared": cleared,
        "message": "Criterion mapping cache cleared",
        "previous_stats": stats,
    }


@router.get("/cache/criterion-mapping/stats")
async def get_criterion_cache_stats():
    """Return current criterion mapping cache statistics."""
    from src.agents.agent2.criterion_cache import get_criterion_cache

    return get_criterion_cache().stats()


_VALID_ROLES = ("main", "supplement")


@router.post("/papers/{nct_id}/upload")
async def upload_paper(
    nct_id: str,
    file: UploadFile = File(...),
    role: str = Query("supplement"),
):
    """Upload a supplement/design paper PDF for an NCT trial."""
    normalized = nct_id.strip().upper()

    if role not in _VALID_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid role '{role}'. Must be one of: {', '.join(_VALID_ROLES)}",
        )

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    save_dir = PAPERS_DIR / normalized
    save_dir.mkdir(parents=True, exist_ok=True)

    # Remove any existing file with the same role prefix
    for existing in save_dir.glob(f"{role}_*.pdf"):
        existing.unlink()

    prefixed_name = f"{role}_{file.filename}"
    dest = save_dir / prefixed_name
    content = await file.read()
    dest.write_bytes(content)
    return {"name": prefixed_name, "nctId": normalized, "role": role, "path": str(dest)}


@router.get("/papers/{nct_id}/status")
async def get_paper_status(nct_id: str):
    """Check paper availability status for an NCT ID without downloading.

    Returns local file info if PDFs exist, otherwise looks up DOI via PubMed
    and builds download URLs for manual retrieval.
    """
    import requests as _requests
    from src.agents.agent1.paper_url_mapper import build_paper_urls, extract_doi_from_pubmed
    from src.agents.agent1.pubmed_linker import get_design_paper_pmids, search_pubmed_for_nct
    from src.api.models.tte import DownloadUrl, PaperDownloadInfo, PaperStatus
    from src.agents.agent1.pmc_supplement import classify_supplement

    normalized = nct_id.strip().upper()
    papers_dir = PAPERS_DIR / normalized

    # Step 1: Check for local PDF files
    if papers_dir.exists():
        pdfs = sorted(papers_dir.glob("*.pdf"))
        if pdfs:
            papers_found = []
            for pdf in pdfs:
                # Uploaded files use {role}_ prefix; fall back to classify_supplement
                stem = pdf.name
                if stem.startswith("main_"):
                    role = "main"
                elif stem.startswith("supplement_"):
                    role = "supplement"
                else:
                    role = classify_supplement(stem)
                papers_found.append(PaperDownloadInfo(name=pdf.name, role=role, source="local"))
            roles_filled = list(set(p.role for p in papers_found))
            return PaperStatus(
                source="local",
                papers_found=papers_found,
                supplement_available=True,
                manual_download_needed=False,
                download_urls=[],
                roles_filled=roles_filled,
            )

    # Step 2: Prefer design/protocol papers from NCT referencesModule
    # (BACKGROUND type contains eligibility criteria, RESULT type typically does not)
    import asyncio
    import logging

    logger = logging.getLogger(__name__)
    pmids: list[str] = []
    try:
        resp = await asyncio.to_thread(
            _requests.get,
            f"https://clinicaltrials.gov/api/v2/studies/{normalized}",
            timeout=10,
        )
        if resp.ok:
            pmids = get_design_paper_pmids(resp.json())
    except Exception:
        logger.warning("Failed to fetch NCT references for %s", normalized, exc_info=True)

    # Step 3: Fallback to PubMed esearch if no references in NCT data
    if not pmids:
        pmids = search_pubmed_for_nct(normalized)

    if not pmids:
        return PaperStatus(
            source="nct_only",
            papers_found=[],
            supplement_available=False,
            manual_download_needed=True,
            download_urls=[],
        )

    # Step 4: Get DOI from first (highest-priority) PMID
    doi = extract_doi_from_pubmed(pmids[0])
    if not doi:
        return PaperStatus(
            source="nct_only",
            papers_found=[],
            supplement_available=False,
            manual_download_needed=True,
            download_urls=[],
        )

    # Step 5: Build download URLs from DOI
    raw_urls = build_paper_urls(doi)
    download_urls = [
        DownloadUrl(
            journal=u.get("journal"),
            doi=u.get("doi"),
            article_url=u["url"],
            supplement_hint=u.get("hint"),
            role=u.get("role", "main"),
        )
        for u in raw_urls
    ]

    return PaperStatus(
        source="nct_only",
        papers_found=[],
        supplement_available=False,
        manual_download_needed=True,
        download_urls=download_urls,
    )


@router.get("/papers/{nct_id}")
async def list_papers(nct_id: str):
    """List uploaded papers for an NCT trial."""
    from src.agents.agent1.pmc_supplement import classify_supplement

    normalized = nct_id.strip().upper()
    papers_dir = PAPERS_DIR / normalized
    if not papers_dir.exists():
        return {"nctId": normalized, "files": []}

    files = []
    for pdf in sorted(papers_dir.glob("*.pdf")):
        name = pdf.name
        if name.startswith("main_"):
            role = "main"
        elif name.startswith("supplement_"):
            role = "supplement"
        else:
            role = classify_supplement(name)
        files.append({"name": name, "role": role})
    return {"nctId": normalized, "files": files}
