"""Pydantic models for the TTE integration MVP."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, computed_field, field_validator

from src.utils.llm import _is_vllm_model


def utc_now_iso() -> str:
    """Return a UTC ISO-8601 timestamp compatible with the ATLAS UI."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def default_created_by() -> dict[str, str]:
    return {"name": "current_user"}


class TTEModel(BaseModel):
    """Shared model config for TTE payloads."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)


DEMOGRAPHIC_DOMAINS = frozenset({"Demographics", "Demographic", "Age", "Gender", "Race", "Ethnicity"})


def _reject_non_local_model_override(value: str | None) -> str | None:
    """Refuse a per-request model override that isn't a local vLLM model.

    ``model`` reaches ``TTEService`` as ``model_name`` and ``get_llm()`` honors it
    literally, bypassing ``settings.LLM_MODEL`` entirely — that escape hatch is the
    TTE UI's model-comparison selector (``GET /tte/models`` lists remote OpenAI/
    Azure/OpenRouter entries alongside the local fleet for exactly this). Without
    this check, that same field lets any caller bill a hosted provider directly
    from a public-facing endpoint with no server-side control over which provider
    or how much. Restrict it to what ``get_llm()`` would otherwise select on its
    own.
    """
    if value is not None and not _is_vllm_model(value):
        raise ValueError(
            f"model override {value!r} must be a local vLLM model ('vllm/...') or omitted"
        )
    return value


def is_demographic_domain_but_not_a_demographic_rule(
    *,
    domain: str,
    is_group_label: bool,
    value_constraint_value: Any,
) -> bool:
    """True when a criterion's domain is demographic, it is not a group label, and it
    carries no usable numeric valueConstraint -- i.e. no real Age/Gender/etc. CIRCE
    DemographicCriteria rule can be built from it.

    Such a criterion should be treated as an ordinary mappable criterion (routed to
    concept-set mapping like any non-demographic criterion) instead of being silently
    dropped or gated as demographic-only. A criterion that DOES carry a real numeric
    valueConstraint (e.g. ``Age >= 65``) correctly stays demographic-only and this
    returns False for it.

    This mirrors only the cheap, dependency-free guard
    ``TTEService._build_demographic_rule`` itself opens with (``not vc or
    vc.get("value") is None``) -- it does NOT re-derive the full CIRCE rule (operator
    mapping, exclusion inversion, etc). ``_build_demographic_rule`` lives on
    ``TTEService`` in ``src/services/tte_service.py``, which this module must not
    import (that module already imports FROM here; importing back would cycle), so
    this helper is the one shared, dependency-free predicate both ``tte_service.py``
    and ``tte.py`` import instead of re-writing the same domain/isGroupLabel/
    valueConstraint check at each call site (see the exclusion-loop fallthrough in
    ``TTEService._build_seeded_target_circe`` for the fuller, rule-building version
    of this same decision).
    """
    if is_group_label:
        return False
    if (domain or "").strip() not in DEMOGRAPHIC_DOMAINS:
        return False
    return value_constraint_value is None


# ---------------------------------------------------------------------------
# Paper download / enrichment status models (SPEC-UI-011)
# ---------------------------------------------------------------------------


class DownloadResult(BaseModel):
    """Result of a single paper download attempt."""

    url: str
    role: str  # "main" | "supplement"
    status: str  # "downloaded" | "paywalled" | "unavailable" | "error"
    saved_path: str | None = None  # Local path if downloaded


class DownloadUrl(BaseModel):
    """URL info for manual paper download."""

    journal: str | None = None  # "NEJM" | "Lancet" | "JAMA" | etc.
    doi: str | None = None  # "10.1056/NEJMoa1107039"
    article_url: str  # DOI resolver URL
    supplement_hint: str | None = None  # Journal-specific guidance text
    role: str = "supplement"  # "main" | "supplement"


class PaperDownloadInfo(BaseModel):
    """Info about a successfully found/downloaded paper."""

    name: str  # Filename
    role: str  # "supplement" | "appendix" | "main" | "protocol"
    source: str  # "local" | "pmc" | "journal_download"


class PaperStatus(BaseModel):
    """Paper enrichment status from Agent1 pipeline."""

    source: str = "nct_only"  # "local" | "pmc_supplement" | "pmc_fulltext" | "journal_download" | "pubmed_abstract" | "nct_only"
    papers_found: list[PaperDownloadInfo] = []
    supplement_available: bool = False
    manual_download_needed: bool = True
    download_urls: list[DownloadUrl] = []
    download_results: list[DownloadResult] = []
    roles_filled: list[str] = []


# ---------------------------------------------------------------------------


#: The key under which a criterion records the protocol line it was extracted from.
#: Spelled once here, in the module that owns the criterion wire format, for the same
#: reason :data:`~src.utils.circe_lint.DROPPED_CRITERIA_KEY` is spelled once there: a
#: key retyped at a second site is a key that half-survives its own rename.
#: ``src/services/tte_service.py`` imports this rather than writing the string again.
CRITERION_PROTOCOL_LINE_KEY = "protocolLine"


class CriterionValueConstraint(TTEModel):
    op: str = ""
    value: float | None = None
    unitText: str = ""


class Criterion(TTEModel):
    id: int | None = None
    description: str = ""
    domain: str = ""
    valueConstraint: CriterionValueConstraint | None = None
    sourceText: str = ""
    #: The protocol's own line, verbatim, as Agent 1 recorded it in the IR's
    #: ``source_text`` -- NOT a second spelling of ``sourceText`` above, which carries
    #: the criterion's entity ("Alanine aminotransferase") because
    #: ``_criterion_dict_from_ir_item`` assigns it from ``entity_text``, and which
    #: several concept-mapping seeds read as such.
    #:
    #: One line can yield one criterion or several, and until this field existed the
    #: store could not tell those apart: a line that collapsed from four criteria to
    #: one left no trace in any other field, and a threshold the model supplied itself
    #: was indistinguishable from one the protocol wrote down. Grouping rows by this
    #: value makes the line-to-criterion cardinality readable, and reading it next to
    #: the row's ``valueConstraint`` shows whether the number is in the line at all.
    #:
    #: Empty for a study whose IR predates ``Criteria.source_text`` (documented
    #: Optional there for the same reason) and for any criterion not built from an IR.
    #: The key is :data:`CRITERION_PROTOCOL_LINE_KEY`.
    protocolLine: str = ""
    window: dict[str, int] | None = None
    conceptSetId: int | None = None
    conceptSetName: str = ""
    logicType: str = "PRESENCE"  # "PRESENCE" or "ABSENCE"
    groupId: str | None = None
    groupType: str = "ALL"
    isGroupLabel: bool = False

    @computed_field
    @property
    def mappable(self) -> bool:
        if self.isGroupLabel:
            return False
        if not self.description.strip():
            return False
        domain = self.domain.strip()
        if domain not in DEMOGRAPHIC_DOMAINS:
            return True
        return is_demographic_domain_but_not_a_demographic_rule(
            domain=domain,
            is_group_label=self.isGroupLabel,
            value_constraint_value=(self.valueConstraint.value if self.valueConstraint else None),
        )


class Eligibility(TTEModel):
    targetCohortId: int | None = None
    targetCohortName: str = ""
    inclusionCriteria: list[Criterion] = Field(default_factory=list)
    exclusionCriteria: list[Criterion] = Field(default_factory=list)
    observationWindow: dict[str, int] | None = None
    structuredExpression: dict[str, Any] | None = None


class TreatmentArm(TTEModel):
    id: int
    name: str
    cohortId: int | None = None
    cohortName: str = ""


class Outcome(TTEModel):
    id: int | None = None
    cohortId: int | None = None
    cohortName: str = ""
    description: str = ""
    domain: str = ""
    timeAtRisk: dict[str, int] | None = None
    conceptSetId: int | None = None
    source: str = ""  # "nct" | "ai" | "manual" | ""


class Outcomes(TTEModel):
    primary: Outcome = Field(default_factory=Outcome)
    secondary: list[Outcome] = Field(default_factory=list)


class TimeParams(TTEModel):
    followUpDuration: int = 30
    followUpUnit: Literal["days", "weeks", "months", "years"] = "days"
    washoutPeriod: int = 180
    gracePeriod: int = 30
    minDaysAtRisk: int = 1


class AnalysisSettings(TTEModel):
    outcomeModel: Literal["cox", "logistic", "poisson"] = "cox"
    adjustForCovariates: bool = True
    psMethod: Literal["matching", "stratification", "weighting", "mahalanobis"] = "matching"
    psCaliper: float = 0.2
    trimByPs: bool = True
    trimFraction: float = 0.05


class ExecutionRecord(TTEModel):
    id: int
    sourceKey: str
    status: Literal["QUEUED", "RUNNING", "COMPLETED", "FAILED"]
    startTime: str
    endTime: str | None = None


class AnalysisStrategyPayload(TTEModel):
    method: Literal["PSM", "IPTW", "MAHALANOBIS", "STRATIFICATION"]
    selectedCovariates: list[str]
    followupDays: int
    reasoning: dict[str, str]  # keys: "method", "covariates", "followup"
    warnings: list[str]
    diagnosisTitle: str = ""
    diagnosisSummary: str = ""
    diagnosisFacts: list[str] = Field(default_factory=list)
    proposedParameters: dict[str, Any] = Field(default_factory=dict)
    rejectedAlternatives: list[dict[str, str]] = Field(default_factory=list)
    rationaleSections: list[dict[str, str]] = Field(default_factory=list)
    candidateMethods: list[dict[str, Any]] = Field(default_factory=list)
    recommendationSource: str = "heuristic_fallback"
    finalizer: dict[str, Any] = Field(default_factory=dict)
    recommendationStage: Literal["draft", "final"] = "draft"
    requestedPsMethod: Literal["matching", "stratification", "weighting", "mahalanobis"] | None = None


class EvaluateAnalysisStrategyRequest(TTEModel):
    requestedPsMethod: Literal["matching", "stratification", "weighting", "mahalanobis"] | None = None
    stage: Literal["draft", "final"] = "draft"


class TTEArtifact(TTEModel):
    id: str
    studyId: int
    studyVersion: int
    kind: Literal[
        "draft_generation",
        "eligibility_suggestion",
        "eligibility_processing",
        "treatment_suggestion",
        "outcome_suggestion",
        "seeded_cohort_generation",
        "design_validation",
        "execution_result",
        "analysis_result",
        "analysis_strategy",
        "report_summary",
    ]
    status: Literal["queued", "running", "completed", "failed", "dismissed"] = "completed"
    source: str = "artemis"
    capability: str
    summary: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    createdAt: str = Field(default_factory=utc_now_iso)
    appliedAt: str | None = None


class TTEJob(TTEModel):
    id: str
    studyId: int
    studyVersion: int
    capability: str
    status: Literal["queued", "running", "completed", "failed", "cancelled"]
    createdAt: str = Field(default_factory=utc_now_iso)
    startedAt: str | None = None
    finishedAt: str | None = None
    artifactId: str | None = None
    error: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class TTEStudy(TTEModel):
    id: int | None = None
    version: int = 1
    name: str = ""
    description: str = ""

    @field_validator("version", mode="before")
    @classmethod
    def _coerce_null_version(cls, v: object) -> int:
        return v if v is not None else 1
    studyType: Literal["comparative", "safety", "single_arm"] = "comparative"
    comparisonMode: Literal["treatment_vs_rest", "explicit_comparator", "target_minus_treatment"] = "target_minus_treatment"
    status: Literal["draft", "ready", "running", "completed", "failed"] = "draft"
    createdDate: str = Field(default_factory=utc_now_iso)
    modifiedDate: str = Field(default_factory=utc_now_iso)
    createdBy: dict[str, Any] = Field(default_factory=default_created_by)
    eligibility: Eligibility = Field(default_factory=Eligibility)
    treatmentArms: list[TreatmentArm] = Field(
        default_factory=lambda: [
            TreatmentArm(id=1, name="Treatment", cohortId=None, cohortName=""),
            TreatmentArm(id=2, name="Comparator", cohortId=None, cohortName=""),
        ]
    )
    outcomes: Outcomes = Field(default_factory=Outcomes)
    timeParams: TimeParams = Field(default_factory=TimeParams)
    analysisSettings: AnalysisSettings = Field(default_factory=AnalysisSettings)
    trialMetadata: dict[str, Any] | None = None
    executions: list[ExecutionRecord] = Field(default_factory=list)
    results: dict[str, Any] | None = None


class GenerateRequest(TTEModel):
    naturalLanguageDescription: str = Field(
        ...,
        min_length=3,
        max_length=2000,
        validation_alias=AliasChoices("naturalLanguageDescription", "natural_language_description"),
    )
    model: str | None = None  # Optional LLM model override — local vLLM only

    @field_validator("model")
    @classmethod
    def _validate_model(cls, v: str | None) -> str | None:
        return _reject_non_local_model_override(v)


class NCTGenerateRequest(TTEModel):
    nctId: str = Field(
        ...,
        min_length=3,
        max_length=32,
        validation_alias=AliasChoices("nctId", "nct_id"),
    )
    forceRefresh: bool = False
    model: str | None = None  # Optional LLM model override — local vLLM only

    @field_validator("model")
    @classmethod
    def _validate_model(cls, v: str | None) -> str | None:
        return _reject_non_local_model_override(v)


class GenerationSuggestion(TTEModel):
    type: Literal["info", "success", "warning"] = "info"
    icon: str
    text: str


class CapabilitySignal(TTEModel):
    owner: str
    fidelity: Literal["high", "medium", "non_agent"]
    fidelityNote: str
    stageKind: Literal["agent", "execution", "review_loop"]


class MappingQualitySignal(TTEModel):
    status: Literal["ok", "warning", "fallback"] = "ok"
    seedCount: int = 0
    reason: str | None = None
    domainMismatch: bool = False
    minSeedCount: int = 1
    retryReasons: list[str] = Field(default_factory=list)


class SuggestionArtifactMeta(TTEModel):
    generationMode: Literal["trial_agent", "heuristic", "provisional_ir", "warning_only"] = (
        "provisional_ir"
    )
    fallbackReason: str | None = None
    sourceSection: str = "none"
    usedFallback: bool = False
    sourceFragments: list[str] = Field(default_factory=list)
    mappingQuality: MappingQualitySignal = Field(default_factory=MappingQualitySignal)
    capabilitySignal: CapabilitySignal | None = None


class MappingCandidateItem(TTEModel):
    """A single OMOP concept candidate surfaced by the mapping pipeline."""

    conceptId: int
    conceptName: str
    # Relative rank score within ONE criterion, higher is better. None means the
    # candidate never went through the retriever (KG/ATC expansion), so it has no
    # embedding distance -- distinct from a low score. Not comparable across
    # criteria: the underlying adjusted_score is normalised per query.
    score: float | None = None
    source: str  # "rag", "expansion", "ontology", or "phoebe"
    included: bool = False  # True if this candidate made it into the final expression


class CriterionMappingMetadata(TTEModel):
    """Intermediate mapping pipeline data for a single criterion (HITL transparency)."""

    allCandidates: list[MappingCandidateItem] = Field(default_factory=list)
    rerankConfidence: float | None = None
    rerankMethod: str | None = None  # "cross_encoder", "llm", or "score"
    queryUsed: str | None = None
    selectedConceptIds: list[int] = Field(default_factory=list)


class ReRecommendRequest(TTEModel):
    """Request body for the HITL re-recommend endpoint."""

    hint: str = ""
    topK: int = Field(default=10, ge=1, le=100)


class ProcessEligibilityCriterionDiagnostic(TTEModel):
    criterionId: int | None = None
    criterionRole: Literal["target", "inclusion", "exclusion"]
    status: Literal["processed", "preserved", "warning", "failed", "skipped"] = "processed"
    description: str = ""
    conceptSetId: int | None = None
    conceptSetName: str = ""
    structuredExpression: dict[str, Any] | None = None
    reason: str | None = None
    warning: str | None = None
    error: str | None = None
    mappingMetadata: CriterionMappingMetadata | None = None


class ProcessEligibilityArtifactMeta(TTEModel):
    status: Literal["ok", "warning", "partial", "failed"] = "ok"
    processedCount: int = 0
    preservedCount: int = 0
    warningCount: int = 0
    failedCount: int = 0
    diagnostics: list[ProcessEligibilityCriterionDiagnostic] = Field(default_factory=list)
    capabilitySignal: CapabilitySignal | None = None


class ProcessEligibilityPayload(TTEModel):
    proposedChanges: dict[str, Eligibility] = Field(default_factory=dict)
    rationale: list[str] = Field(default_factory=list)
    meta: ProcessEligibilityArtifactMeta = Field(default_factory=ProcessEligibilityArtifactMeta)


class SeededCohortGenerationItem(TTEModel):
    section: Literal["eligibility", "treatmentArms", "outcomes"]
    itemKey: str
    role: str
    label: str
    status: Literal["created", "skipped", "failed"]
    seedText: str = ""
    cohortDefinitionId: int | None = None
    cohortDefinitionName: str = ""
    reason: str | None = None
    error: str | None = None


class SeededCohortSectionDiagnostic(TTEModel):
    section: Literal["eligibility", "treatmentArms", "outcomes"]
    status: Literal["completed", "warning", "failed", "skipped"] = "completed"
    generatedCount: int = 0
    failedCount: int = 0
    skippedCount: int = 0
    items: list[SeededCohortGenerationItem] = Field(default_factory=list)


class SeededCohortGenerationMeta(TTEModel):
    status: Literal["ok", "warning", "failed"] = "ok"
    generatedCount: int = 0
    failedCount: int = 0
    skippedCount: int = 0
    sectionStatuses: dict[str, str] = Field(default_factory=dict)
    capabilitySignal: CapabilitySignal | None = None


class ValidationIssue(TTEModel):
    field: str
    message: str
    severity: Literal["blocker", "warning", "error"] = "warning"


class ValidationPayload(TTEModel):
    valid: bool = False
    blockers: list[ValidationIssue] = Field(default_factory=list)
    warnings: list[ValidationIssue] = Field(default_factory=list)
    actionableLoops: dict[str, list[ValidationIssue]] = Field(default_factory=dict)


class ValidatorPayload(TTEModel):
    status: Literal["validator", "fallback"] = "fallback"
    valid: bool = False
    conceptSetCount: int = 0
    inclusionRuleCount: int = 0
    errors: list[ValidationIssue] = Field(default_factory=list)
    warnings: list[ValidationIssue] = Field(default_factory=list)
    actionableLoops: dict[str, list[ValidationIssue]] = Field(default_factory=dict)
    circeJson: dict[str, Any] = Field(default_factory=dict)


class ExecutionArtifactMeta(TTEModel):
    status: Literal["ok", "warning", "failed"] = "ok"
    sourceKey: str = ""
    sourceName: str = ""
    resultsSchema: str | None = None
    generatedCohortSummary: dict[str, Any] = Field(default_factory=dict)
    rawInfo: dict[str, Any] = Field(default_factory=dict)
    failureMessage: str | None = None
    capabilitySignal: CapabilitySignal | None = None


class AnalysisConfidenceInterval(TTEModel):
    lower: float | None = None
    upper: float | None = None


class CovariateBalanceItem(TTEModel):
    name: str
    beforePS: float | None = None
    afterPS: float | None = None


class AnalysisPlotPoint(TTEModel):
    x: float | int | None = None
    y: float | None = None
    label: str | None = None


class AnalysisPlotSeries(TTEModel):
    name: str
    points: list[AnalysisPlotPoint] = Field(default_factory=list)


class AnalysisPlotDescriptor(TTEModel):
    key: str
    title: str
    plotType: Literal["line", "love_plot", "km_curve", "forest", "ps_distribution"] = "line"
    xLabel: str = ""
    yLabel: str = ""
    windowDays: int | None = None
    series: list[AnalysisPlotSeries] = Field(default_factory=list)


class AnalysisArtifactMeta(TTEModel):
    status: Literal["ok", "warning", "fallback", "error"] = "warning"
    reason: str | None = None
    summary: str = ""
    capabilitySignal: CapabilitySignal | None = None


class AnalysisResultPayload(TTEModel):
    mode: Literal["analysis"] = "analysis"
    generatedBy: str
    analysisMethod: str | None = None
    matchedPairs: int | None = None
    hazardRatio: float | None = None
    CI: AnalysisConfidenceInterval = Field(default_factory=AnalysisConfidenceInterval)
    hrLower95: float | None = None
    hrUpper95: float | None = None
    pValue: float | None = None
    covariateBalance: list[CovariateBalanceItem] = Field(default_factory=list)
    n_target: int | None = None
    n_comparator: int | None = None
    treatmentN: int | None = None
    comparatorN: int | None = None
    treatmentEvents: int | None = None
    comparatorEvents: int | None = None
    survivalData: dict[str, list[float | int]] = Field(default_factory=dict)
    plots: list[AnalysisPlotDescriptor] = Field(default_factory=list)
    psScores: list[float] = Field(default_factory=list)
    treatmentArray: list[int] = Field(default_factory=list)


class ReportPreviewMetadata(TTEModel):
    resultMode: str | None = None
    sourceKey: str | None = None
    generatedBy: str | None = None
    analysisMethod: str | None = None
    matchedPairs: int | None = None
    hazardRatio: float | None = None
    ciLower: float | None = None
    ciUpper: float | None = None
    pValue: float | None = None
    plots: list[AnalysisPlotDescriptor] = Field(default_factory=list)


class ReportSummaryData(TTEModel):
    title: str
    text: str
    status: Literal["ok", "warning", "fallback"] = "warning"
    reason: str | None = None
    preview: ReportPreviewMetadata | None = None


class ReportArtifactMeta(TTEModel):
    status: Literal["ok", "warning", "fallback"] = "warning"
    reason: str | None = None
    summary: str = ""
    capabilitySignal: CapabilitySignal | None = None


class ReportHtmlExportResponse(TTEModel):
    filename: str
    html: str
    generatedBy: str | None = None
    status: Literal["ok", "fallback"] = "ok"


class ReportPdfExportResponse(TTEModel):
    filename: str
    contentBase64: str
    contentType: Literal["application/pdf"] = "application/pdf"
    generatedBy: str | None = None
    status: Literal["ok", "fallback"] = "ok"


class GenerateResponse(TTEModel):
    study: TTEStudy
    suggestions: list[GenerationSuggestion] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


class CapabilityRunResponse(TTEModel):
    status: Literal["queued", "running", "completed", "failed", "cancelled"]
    artifactId: str | None = None
    jobId: str | None = None
    summary: str = ""
    meta: dict[str, Any] = Field(default_factory=dict)


class DrugEntryPreview(TTEModel):
    conceptSetName: str
    conceptCount: int = 0
    includeDescendants: bool = False


class TimeParametersPreview(TTEModel):
    washout: int
    grace: int
    followUp: int
    unit: str = "days"


class RulePreview(TTEModel):
    index: int
    name: str
    domain: str
    timeWindow: str | None = None
    conceptSetName: str | None = None
    conceptCount: int = 0


class ArmPreview(TTEModel):
    armName: str
    role: str
    drugEntry: DrugEntryPreview | None = None
    rules: list[RulePreview] = []


class CircePreviewResponse(TTEModel):
    status: Literal["preview"] = "preview"
    previewHash: str
    treatmentArm: ArmPreview
    comparatorArm: ArmPreview | None = None
    timeParameters: TimeParametersPreview


class ExecuteRequest(TTEModel):
    sourceKey: str = Field(..., min_length=1)


class ExecuteResponse(TTEModel):
    execution: ExecutionRecord
    results: dict[str, Any]
    artifactId: str | None = None
    jobId: str | None = None


class FullPipelineStage(TTEModel):
    capability: Literal["execute_study", "run_analysis", "generate_report_summary"]
    status: Literal["queued", "running", "completed", "failed", "cancelled"]
    artifactId: str | None = None
    jobId: str | None = None
    artifactKind: str | None = None
    appliedArtifactId: str | None = None
    appliedStudyVersion: int | None = None
    summary: str = ""
    meta: dict[str, Any] = Field(default_factory=dict)


class FullPipelineStages(TTEModel):
    execution: FullPipelineStage
    analysis: FullPipelineStage
    reportSummary: FullPipelineStage


class SupervisorHookPoint(TTEModel):
    name: Literal[
        "before_execute_study",
        "after_execute_study",
        "after_run_analysis",
        "after_generate_report_summary",
    ]
    status: Literal["not_connected", "queued", "running", "completed", "failed"] = (
        "not_connected"
    )
    decisions: list[dict[str, Any]] = Field(default_factory=list)


class SupervisorHooks(TTEModel):
    status: Literal["not_connected", "queued", "running", "completed", "failed"] = (
        "not_connected"
    )
    decisions: list[dict[str, Any]] = Field(default_factory=list)
    hookPoints: list[SupervisorHookPoint] = Field(default_factory=list)


class FullPipelineResponse(TTEModel):
    studyId: int
    studyVersion: int
    sourceKey: str
    status: Literal["queued", "running", "completed", "failed", "cancelled"]
    summary: str = ""
    stages: FullPipelineStages
    supervisor: SupervisorHooks


class ArtifactApplyRequest(TTEModel):
    targetSections: list[str] = Field(default_factory=list)
    baseStudyVersion: int


class ArtifactApplyResponse(TTEModel):
    studyId: int
    newVersion: int
    appliedArtifactId: str


class DataSourceOption(TTEModel):
    sourceKey: str
    sourceName: str
    id: str
    name: str
    resultsSchema: str | None = None
