"""
Cohort Executor - Converts Circe JSON to patient data via WebAPI + OMOP CDM.
Bridge between Agent 4 (Validation) and Agent 5 (Analysis).

V2: Uses WebAPI for proper Circe JSON → SQL → cohort generation,
    then reads cohort from results table for downstream analysis.
"""
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
import os
import logging

import pandas as pd
import numpy as np

from src.analysis.omop_connector import OMOPConnector
from src.models.ir import ExtractionDiagnostic
from src.pipeline.webapi_client import (
    WebAPIClient,
    WebAPIError,
    CohortTableReference,
)

logger = logging.getLogger(__name__)

# Fallback mode: "auto" (default) | "always" (skip DB) | "never" (raise on failure)
# Read at runtime via property, not module load time


@dataclass
class ExecutionResult:
    """Result of cohort execution with optional diagnostics (Loop 4)."""
    data: Optional[pd.DataFrame]
    patient_count: int = 0
    target_count: int = 0
    comparator_count: int = 0
    diagnostics: List[ExtractionDiagnostic] = field(default_factory=list)
    used_fallback: bool = False
    cohort_ref: Optional[CohortTableReference] = None
    error: Optional[str] = None

    @property
    def is_empty(self) -> bool:
        return self.patient_count == 0

    @property
    def has_diagnostics(self) -> bool:
        return len(self.diagnostics) > 0


class CohortExecutor:
    """
    Executes cohort definitions against OMOP CDM via WebAPI.

    V2 Flow (WebAPI-first):
        1. Send Circe JSON to WebAPI → Circe-be generates SQL
        2. WebAPI executes SQL → writes to results_schema.cohort
        3. Read cohort from DB table → build analysis dataset with HDPS covariates

    Fallback:
        If WebAPI fails and ARTEMIS_FALLBACK_MODE != "never",
        falls back to synthetic data generation.

    Controlled by ARTEMIS_FALLBACK_MODE env var:
        - "never" (default): Raise error on WebAPI/DB failure, no fallback
        - "auto": WebAPI first, fallback to synthetic on failure
        - "always": Always use synthetic fallback data, skip WebAPI/DB, raise on any failure
    """

    def __init__(
        self,
        connector: Optional[OMOPConnector] = None,
        webapi_client: Optional[WebAPIClient] = None,
    ):
        self.connector = connector or OMOPConnector()
        self.webapi_client = webapi_client or WebAPIClient()

    @property
    def fallback_mode(self) -> str:
        """Read FALLBACK_MODE at runtime so env var changes take effect."""
        return os.environ.get("ARTEMIS_FALLBACK_MODE", "never")

    def execute(
        self,
        circe_json: Dict[str, Any],
        comparator_circe_json: Optional[Dict[str, Any]] = None,
        outcome_concept_ids: Optional[List[int]] = None,
        followup_days: int = 365,
        cohort_name: str = "ARTEMIS Auto-generated",
    ) -> ExecutionResult:
        """
        Execute cohort definition and extract analysis-ready data.

        V2: Uses WebAPI to properly convert Circe JSON (including
        InclusionRules, temporal windows, occurrence counts) to SQL.

        Args:
            circe_json: Validated Circe-be JSON from Agent 4
            outcome_concept_ids: OMOP concept IDs for outcome event
            followup_days: Maximum follow-up period
            cohort_name: Human-readable name for WebAPI registration

        Returns:
            ExecutionResult with DataFrame and optional diagnostics
        """
        # Short-circuit: always fallback
        if self.fallback_mode == "always":
            logger.info("ARTEMIS_FALLBACK_MODE=always → using synthetic data")
            fallback = self._generate_fallback_data()
            return ExecutionResult(
                data=fallback,
                patient_count=len(fallback),
                target_count=int((fallback['treatment'] == 1).sum()),
                comparator_count=int((fallback['treatment'] == 0).sum()),
                used_fallback=True,
            )

        # Default outcome if not provided
        if not outcome_concept_ids:
            outcome_concept_ids = self._extract_outcome_concepts(circe_json)

        # --- WebAPI-first path ---
        try:
            return self._execute_via_webapi(
                circe_json, outcome_concept_ids, followup_days, cohort_name,
                comparator_circe_json=comparator_circe_json,
            )
        except (WebAPIError, Exception) as e:
            if self.fallback_mode == "never":
                raise RuntimeError(
                    f"[CohortExecutor] WebAPI/DB failed and "
                    f"ARTEMIS_FALLBACK_MODE=never: {e}"
                ) from e

            logger.warning(f"WebAPI path failed: {e}")
            logger.info("Falling back to synthetic data")
            fallback = self._generate_fallback_data()
            return ExecutionResult(
                data=fallback,
                patient_count=len(fallback),
                target_count=int((fallback['treatment'] == 1).sum()),
                comparator_count=int((fallback['treatment'] == 0).sum()),
                used_fallback=True,
            )

    def _execute_via_webapi(
        self,
        circe_json: Dict[str, Any],
        outcome_concept_ids: List[int],
        followup_days: int,
        cohort_name: str,
        comparator_circe_json: Optional[Dict[str, Any]] = None,
    ) -> ExecutionResult:
        """
        WebAPI cohort generation path.

        Steps:
            1. Generate cohort via WebAPI (Circe JSON → SQL → execute)
            2. Read patient IDs + index dates from results table
            3. Build analysis dataset with full covariates
        """
        logger.info("[CohortExecutor] Using WebAPI path for cohort generation")

        # 1. Generate cohort via WebAPI
        cohort_ref = self.webapi_client.generate_cohort(
            circe_json=circe_json,
            name=cohort_name,
        )
        logger.info(
            f"  Cohort generated: ID={cohort_ref.cohort_definition_id}, "
            f"patients={cohort_ref.person_count}"
        )

        if cohort_ref.is_empty:
            # Run diagnostics on concept IDs
            all_concept_ids = self._collect_all_concept_ids(circe_json)
            diagnostics = self._run_diagnostics(all_concept_ids)
            for d in diagnostics:
                logger.info(
                    f"    Concept {d.concept_id}: "
                    f"{d.patient_count} patients → {d.suggestion}"
                )

            if self.fallback_mode == "never":
                raise RuntimeError(
                    f"[CohortExecutor] WebAPI returned 0 patients and "
                    f"ARTEMIS_FALLBACK_MODE=never. "
                    f"Diagnostics: {[(d.concept_id, d.patient_count, d.suggestion) for d in diagnostics]}"
                )

            # CRITICAL: do not attach synthetic rows to a zero-patient result.
            # Callers must check result.error and handle empty cohort explicitly.
            return ExecutionResult(
                data=None,
                patient_count=0,
                target_count=0,
                comparator_count=0,
                diagnostics=diagnostics,
                used_fallback=False,
                cohort_ref=cohort_ref,
                error=(
                    "WebAPI returned 0 patients for this cohort definition. "
                    "No analysis can be performed. "
                    f"Diagnostics: {[(d.concept_id, d.patient_count, d.suggestion) for d in diagnostics]}"
                ),
            )

        # 2. Generate comparator cohort (if provided)
        comparator_ref = None
        if comparator_circe_json is not None:
            logger.info("[CohortExecutor] Generating comparator cohort...")
            comparator_ref = self.webapi_client.generate_cohort(
                circe_json=comparator_circe_json,
                name=f"{cohort_name} - Comparator",
            )
            logger.info(
                f"  Comparator cohort: ID={comparator_ref.cohort_definition_id}, "
                f"patients={comparator_ref.person_count}"
            )

        # 3. Build analysis dataset from cohort table(s)
        data = self.connector.build_analysis_dataset_from_cohort(
            cohort_ref=cohort_ref,
            outcome_concept_ids=outcome_concept_ids,
            followup_days=followup_days,
            comparator_ref=comparator_ref,
        )

        if data.empty:
            logger.warning("Analysis dataset empty despite non-zero cohort")
            if self.fallback_mode == "never":
                raise RuntimeError(
                    f"[CohortExecutor] Analysis dataset empty (cohort had "
                    f"{cohort_ref.person_count} patients) and "
                    f"ARTEMIS_FALLBACK_MODE=never."
                )
            # CRITICAL: do not attach synthetic rows to a zero-patient result.
            return ExecutionResult(
                data=None,
                patient_count=0,
                used_fallback=False,
                cohort_ref=cohort_ref,
                error=(
                    f"Analysis dataset is empty despite cohort having "
                    f"{cohort_ref.person_count} patients. "
                    "This may indicate a CDM schema connectivity issue."
                ),
            )

        target_n = int((data['treatment'] == 1).sum())
        comp_n = int((data['treatment'] == 0).sum())
        logger.info(
            f"  ✓ Extracted {len(data)} patients "
            f"(target={target_n}, comparator={comp_n})"
        )

        return ExecutionResult(
            data=data,
            patient_count=len(data),
            target_count=target_n,
            comparator_count=comp_n,
            cohort_ref=cohort_ref,
        )

    # ----------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------

    def _collect_all_concept_ids(
        self, circe_json: Dict[str, Any]
    ) -> List[int]:
        """Collect all concept IDs from all ConceptSets."""
        concept_ids = []
        for cs in circe_json.get("ConceptSets", []):
            for item in cs.get("expression", {}).get("items", []):
                cid = item.get("concept", {}).get("CONCEPT_ID")
                if cid:
                    concept_ids.append(cid)
        return concept_ids

    def _run_diagnostics(
        self, concept_ids: List[int]
    ) -> List[ExtractionDiagnostic]:
        """Run Loop 4 diagnostic queries for zero-patient scenarios."""
        raw = self.connector.diagnose_concepts(concept_ids)
        return [
            ExtractionDiagnostic(
                concept_id=d["concept_id"],
                concept_name=d.get("concept_name", ""),
                patient_count=d["patient_count"],
                domain=d.get("domain", "Unknown"),
                suggestion=d.get("suggestion", "CHECK_MAPPING"),
            )
            for d in raw
        ]

    def _extract_outcome_concepts(
        self, circe_json: Dict[str, Any]
    ) -> List[int]:
        """Extract outcome concept IDs from Circe JSON."""
        concept_sets = circe_json.get("ConceptSets", [])

        for cs in concept_sets:
            name = cs.get("name", "").lower()
            if "outcome" in name or "event" in name or "death" in name:
                items = cs.get("expression", {}).get("items", [])
                return [
                    item.get("concept", {}).get("CONCEPT_ID", 0)
                    for item in items
                    if item.get("concept", {}).get("CONCEPT_ID")
                ]

        # Default: common outcome concept ID
        return [260139]

    def _generate_fallback_data(
        self,
        n_treated: int = 500,
        n_control: int = 500,
    ) -> pd.DataFrame:
        """
        WARNING: FOR DEVELOPMENT/DEMO USE ONLY.
        Generates synthetic patient data with fixed seed 42.
        Never used in production (requires ARTEMIS_FALLBACK_MODE=auto|always).
        All returned data is fabricated and must not be used for real analysis.
        """
        logger.warning(
            "SYNTHETIC FALLBACK: generating %d fake patients (n_treated=%d, n_control=%d). "
            "This is NOT real OMOP data. ARTEMIS_FALLBACK_MODE=%s",
            n_treated + n_control,
            n_treated,
            n_control,
            self.fallback_mode,
        )
        logger.info("Generating synthetic fallback data...")

        np.random.seed(42)
        n_total = n_treated + n_control

        treatment = np.array([1] * n_treated + [0] * n_control)
        age = np.concatenate([
            np.random.normal(62, 10, n_treated),
            np.random.normal(60, 10, n_control),
        ])
        gender_male = np.random.binomial(1, 0.55, n_total)

        # Generate synthetic HDPS covariates (binary)
        covariates = {}
        cov_names = [
            "cond_diabetes", "cond_hypertension", "cond_obesity",
            "cond_ckd", "cond_chf", "cond_cad", "cond_afib",
            "drug_metformin", "drug_statin", "drug_ace_inhibitor",
            "drug_beta_blocker", "drug_aspirin", "drug_insulin",
            "proc_hba1c_test", "proc_lipid_panel", "proc_ecg",
        ]
        prevalences = [0.95, 0.65, 0.35, 0.15, 0.12, 0.20, 0.08,
                        0.70, 0.55, 0.40, 0.30, 0.45, 0.25,
                        0.60, 0.50, 0.20]
        for name, prev in zip(cov_names, prevalences):
            # Slightly different prevalence for treatment groups
            prev_t = min(prev * 1.1, 0.99)
            prev_c = prev
            vals = np.concatenate([
                np.random.binomial(1, prev_t, n_treated),
                np.random.binomial(1, prev_c, n_control),
            ])
            covariates[name] = vals

        # Survival times
        times = []
        events = []
        for i in range(n_total):
            risk = 0.001 * (1 + 0.02 * (age[i] - 60))
            if treatment[i] == 1:
                risk *= 0.8  # Treatment protective effect
            t = np.random.exponential(1 / risk)
            if t > 365:
                times.append(365)
                events.append(0)
            else:
                times.append(t)
                events.append(1)

        data = {
            "person_id": range(n_total),
            "treatment": treatment,
            "age": age,
            "gender_male": gender_male,
            "time": times,
            "event": events,
        }
        data.update(covariates)
        return pd.DataFrame(data)

