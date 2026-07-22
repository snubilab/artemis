from typing import List, Optional, Literal, Union, Any, Dict
from pydantic import BaseModel, Field

# --- Part 1: OHDSI ConceptSet Structure (matches docs/sample.json) ---

class OMOPConcept(BaseModel):
    """
    Represents a standard OMOP CDM Concept.
    Matches the structure found in docs/sample.json.
    """
    CONCEPT_ID: int
    CONCEPT_NAME: str
    STANDARD_CONCEPT: Optional[str] = None
    STANDARD_CONCEPT_CAPTION: Optional[str] = None
    INVALID_REASON: Optional[str] = None
    INVALID_REASON_CAPTION: Optional[str] = None
    CONCEPT_CODE: str
    DOMAIN_ID: str
    VOCABULARY_ID: str
    CONCEPT_CLASS_ID: str

class ConceptSetItem(BaseModel):
    """
    An item within a Concept Set expression.
    """
    concept: OMOPConcept
    includeDescendants: bool = False
    isExcluded: bool = False

class ConceptSetExpression(BaseModel):
    items: List[ConceptSetItem]

class ConceptSet(BaseModel):
    """
    Represents a full OHDSI Concept Set.
    """
    id: int
    name: str
    expression: ConceptSetExpression

# --- Part 2: ARTEMIS 3.1 Internal Representation (Logic Layer) ---

class TemporalWindow(BaseModel):
    """
    Defines a time window relative to an Index Date.
    e.g., 365 days before (start: -365) to 0 days after (end: 0).
    """
    start: int # Days relative to index
    end: int   # Days relative to index

class ValueConstraint(BaseModel):
    """
    For Measurements (e.g., HbA1c > 6.5).
    """
    op: Literal["gt", "lt", "eq", "gte", "lte"]
    value: float
    unit_text: Optional[str] = None
    unit_concept_id: Optional[int] = None

class Criteria(BaseModel):
    """
    Represents a single logical criterion (Inclusion/Exclusion rule).
    Supports composite criteria via sub_criteria (fan-out).
    """
    name: str
    domain: str # Condition, Drug, Measurement, Procedure, Observation...
    
    # The entity key is the text term (e.g., "T2DM") initially.
    # After Agent 2, it is mapped to a concept_set_id.
    entity_text: Optional[str] = None 
    concept_set_id: Optional[int] = None
    
    # Logic details
    logic_type: Literal["PRESENCE", "ABSENCE"] = "PRESENCE"
    window: Optional[TemporalWindow] = None
    value_constraint: Optional[ValueConstraint] = None
    
    # Composite criteria: fan-out into sub-criteria
    sub_criteria: List["Criteria"] = Field(default_factory=list)
    group_type: Literal["ALL", "ANY"] = "ALL"

    # If True, criterion is gated on a patient subgroup and must be skipped in CIRCE
    conditional: bool = False

class PrimaryCriteria(BaseModel):
    """
    Defines the entry event for the cohort.
    """
    domain: str
    entity_text: Optional[str] = None
    concept_set_id: Optional[int] = None
    limit: Literal["First", "All"] = "First"
    observation_window: Optional[Dict[str, int]] = Field(
        default_factory=lambda: {"prior": 365, "post": 0}
    )

class CohortOutcome(BaseModel):
    name: str
    domain: str
    entity_text: Optional[str] = None
    concept_set_id: Optional[int] = None
    time_at_risk: TemporalWindow


class CustomEraConfig(BaseModel):
    """Configuration for CustomEra EndStrategy (matches TROY pattern)."""
    drug_codeset_id: int
    gap_days: int = 30
    offset: int = 0


class ExitStrategy(BaseModel):
    """Structured EndStrategy supporting OBSERVATION_END, FIXED_DURATION, CUSTOM_ERA."""
    strategy_type: Literal["OBSERVATION_END", "FIXED_DURATION", "CUSTOM_ERA"]
    date_offset_days: Optional[int] = None      # For FIXED_DURATION
    custom_era: Optional[CustomEraConfig] = None  # For CUSTOM_ERA


class CohortDefinition(BaseModel):
    """
    Full definition of a cohort (Target or Comparator).
    """
    primary_criteria: PrimaryCriteria
    inclusion_rules: List[Criteria] = []
    exclusion_rules: List[Criteria] = [] # Added for explicit exclusions
    exit_strategy: Union[str, ExitStrategy] = "OBSERVATION_END"



class ARTEMISRequest(BaseModel):
    """
    The root object for a study request.
    """
    target: CohortDefinition
    comparator: CohortDefinition
    outcome: CohortOutcome

    
    # Container for all resolved ConceptSets used in this request
    concept_sets: List[ConceptSet] = []


class ProvisionalSectionSource(BaseModel):
    section: Literal["eligibility", "treatment", "outcomes"]
    source: Literal["structured_section", "study_description", "study_name", "empty"] = "empty"
    text: str = ""
    fragments: List[str] = Field(default_factory=list)
    fallback_used: bool = False


class ProvisionalStudyIR(BaseModel):
    study_type: Literal["comparative", "safety", "single_arm"] = "comparative"
    title: str = ""
    description: str = ""
    source_text: str = ""
    target_text: str = ""
    comparator_text: str = ""
    primary_outcome_text: str = ""
    eligibility: ProvisionalSectionSource = Field(
        default_factory=lambda: ProvisionalSectionSource(section="eligibility")
    )
    treatment: ProvisionalSectionSource = Field(
        default_factory=lambda: ProvisionalSectionSource(section="treatment")
    )
    outcomes: ProvisionalSectionSource = Field(
        default_factory=lambda: ProvisionalSectionSource(section="outcomes")
    )


# --- Part 3: Gap Analysis (Pattern 3 from artemis_agent) ---

class GapItem(BaseModel):
    """
    Represents a single unmapped or failed item in the pipeline.
    Used for Gap Analysis reporting.
    """
    item_id: str = Field(description="Identifier for the item (e.g., 'INC_01', 'EXC_02')")
    section: Literal["inclusion", "exclusion", "primary", "outcome"] = "inclusion"
    original_text: str = Field(description="Original criteria text")
    domain: Optional[str] = None
    reason: str = Field(description="Reason for mapping failure")
    attempted_searches: List[str] = Field(default_factory=list, description="Search terms attempted")


class GapReport(BaseModel):
    """
    Collection of unmapped items with statistics.
    Enables clinician review of pipeline gaps.
    """
    unmapped_items: List[GapItem] = Field(default_factory=list)
    
    # Statistics
    total_criteria: int = 0
    mapped_count: int = 0
    unmapped_count: int = 0
    
    @property
    def mapping_rate(self) -> float:
        """Calculate mapping success rate as percentage."""
        if self.total_criteria == 0:
            return 0.0
        return (self.mapped_count / self.total_criteria) * 100
    
    def add_gap(
        self,
        item_id: str,
        original_text: str,
        reason: str,
        section: str = "inclusion",
        domain: Optional[str] = None,
        attempted_searches: Optional[List[str]] = None
    ) -> None:
        """Add an unmapped item to the report."""
        self.unmapped_items.append(GapItem(
            item_id=item_id,
            section=section,  # type: ignore
            original_text=original_text[:500],  # Truncate long texts
            domain=domain,
            reason=reason,
            attempted_searches=attempted_searches or []
        ))
        self.unmapped_count += 1
    
    def to_summary(self) -> Dict[str, Any]:
        """Generate summary for logging/reporting."""
        return {
            "total_criteria": self.total_criteria,
            "mapped_count": self.mapped_count,
            "unmapped_count": self.unmapped_count,
            "mapping_rate": f"{self.mapping_rate:.1f}%",
            "gap_items": [
                {"id": g.item_id, "text": g.original_text[:50], "reason": g.reason}
                for g in self.unmapped_items[:10]  # Limit to first 10
            ]
        }


# --- Part 4: Mapping Result (Enhanced workflow output) ---

class MappingResult(BaseModel):
    """
    Result from Agent 2 mapping workflow.
    Includes both successful mappings and gap analysis.
    """
    concept_ids: List[int] = Field(default_factory=list)
    overbroad_concept_ids: List[int] = Field(
        default_factory=list,
        description="Concept IDs flagged as overbroad by ConceptSetRefiner. "
                    "Assembler should set includeDescendants=false for these."
    )
    concept_sets: List[ConceptSet] = Field(default_factory=list)
    gap_report: GapReport = Field(default_factory=GapReport)
    
    # Routing statistics
    fast_path_count: int = 0
    slow_path_count: int = 0
    
    # Path metadata — tracks how this entity was processed
    route_path: Optional[str] = Field(
        default=None,
        description="Routing path taken: 'fast', 'slow', or 'atc'"
    )
    atc_expanded: bool = Field(
        default=False,
        description="Whether ATC drug class expansion was used (early return)"
    )
    critic_skipped: bool = Field(
        default=False,
        description="Whether LLM critic was skipped (anchor count ≤ 10)"
    )
    domain_overridden: Optional[str] = Field(
        default=None,
        description="Original domain_hint if pre-check overrode it, else None"
    )
    
    # Processing metadata
    processing_time_ms: float = 0.0


# --- Part 5: Pipeline Feedback Loop Models (RFC-001) ---

class FailureSeverity(str):
    """Classification of pipeline failures for Loop 1-5 decision-making."""
    BLOCKER = "BLOCKER"      # Schema corruption, primary criteria failure → full stop
    RETRYABLE = "RETRYABLE"  # Re-mapping or expansion may fix → trigger loop
    DEGRADED = "DEGRADED"    # Partial result acceptable → warn and continue


class LoopResult(BaseModel):
    """Records the outcome of a single feedback loop iteration.
    
    Used to track retry states across Loop 1-5 in the pipeline.
    """
    loop_id: str = Field(
        description="Loop type identifier, e.g. 'LOOP_1_REMAP', 'LOOP_4_EXPAND'"
    )
    attempt: int = Field(default=1, description="Current attempt number (1-indexed)")
    max_attempts: int = Field(default=3, description="Maximum allowed attempts")
    status: Literal["SUCCESS", "PARTIAL", "FAILED", "SKIPPED"] = "FAILED"
    healed_entities: List[str] = Field(
        default_factory=list,
        description="Entity texts successfully healed in this attempt"
    )
    remaining_failures: List[str] = Field(
        default_factory=list,
        description="Entity texts still failing after this attempt"
    )
    details: Optional[str] = None

    @property
    def can_retry(self) -> bool:
        """Whether another retry is possible and warranted."""
        return self.attempt < self.max_attempts and self.status == "FAILED"


class ExtractionDiagnostic(BaseModel):
    """Diagnosis result for 0-patient extraction (Loop 4).
    
    When cohort extraction yields 0 patients, this model captures
    per-concept diagnostics to guide concept expansion decisions.
    """
    concept_id: int
    concept_name: str = ""
    patient_count: int = 0
    domain: str = ""
    suggestion: Literal[
        "EXPAND_DESCENDANTS", "CHECK_MAPPING", "REMOVE", "OK"
    ] = "OK"
    suggested_parent_concepts: List[int] = Field(
        default_factory=list,
        description="Parent concept IDs to consider for expansion"
    )


class PipelineErrorClassification(BaseModel):
    """Loop 5: Classifies accumulated pipeline errors for logging/routing.
    
    Aggregates errors from all phases (mapping, assembly, validation,
    extraction) and assigns an overall severity + recommended action.
    """
    severity: Literal["BLOCKER", "RETRYABLE", "DEGRADED", "OK"] = "OK"
    error_sources: List[str] = Field(
        default_factory=list,
        description="Phase names that contributed errors, e.g. ['mapping', 'assembly']"
    )
    error_count: int = 0
    warning_count: int = 0
    recommended_action: Literal[
        "STOP", "RETRY_MAPPING", "RETRY_ASSEMBLY", "EXPAND_CONCEPTS",
        "HUMAN_REVIEW", "CONTINUE_DEGRADED", "OK"
    ] = "OK"
    summary: str = ""
    
    @classmethod
    def from_pipeline_state(
        cls,
        gap_mapping_rate: float,
        assembly_completeness: float,
        validation_error_count: int,
        extraction_patient_count: int
    ) -> "PipelineErrorClassification":
        """Factory: classify pipeline state into severity + action."""
        sources = []
        severity = "OK"
        action = "OK"
        errors = 0
        warnings = 0
        parts = []
        
        # Mapping failures
        if gap_mapping_rate < 50:
            sources.append("mapping")
            severity = "BLOCKER"
            action = "HUMAN_REVIEW"
            errors += 1
            parts.append(f"mapping rate {gap_mapping_rate:.0f}%")
        elif gap_mapping_rate < 80:
            sources.append("mapping")
            severity = "RETRYABLE"
            action = "RETRY_MAPPING"
            warnings += 1
            parts.append(f"mapping rate {gap_mapping_rate:.0f}%")
        
        # Assembly failures
        if assembly_completeness < 0.5:
            sources.append("assembly")
            if severity != "BLOCKER":
                severity = "BLOCKER"
            action = "HUMAN_REVIEW"
            errors += 1
            parts.append(f"assembly completeness {assembly_completeness:.0%}")
        elif assembly_completeness < 0.8:
            sources.append("assembly")
            if severity == "OK":
                severity = "DEGRADED"
            warnings += 1
            parts.append(f"assembly completeness {assembly_completeness:.0%}")
        
        # Validation errors
        if validation_error_count > 0:
            sources.append("validation")
            errors += validation_error_count
            if severity == "OK":
                severity = "RETRYABLE"
                action = "RETRY_ASSEMBLY"
            parts.append(f"{validation_error_count} validation errors")
        
        # Extraction failure
        if extraction_patient_count == 0:
            sources.append("extraction")
            if severity == "OK":
                severity = "RETRYABLE"
            action = "EXPAND_CONCEPTS"
            warnings += 1
            parts.append("0 patients extracted")
        
        summary = "; ".join(parts) if parts else "Pipeline healthy"
        
        return cls(
            severity=severity,
            error_sources=sources,
            error_count=errors,
            warning_count=warnings,
            recommended_action=action,
            summary=summary
        )
