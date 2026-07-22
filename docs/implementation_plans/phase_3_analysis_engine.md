# Phase 3: Analysis Engine Implementation Plan

**Timeline**: Weeks 7-10
**Focus**: Agent 5 (Analysis Agent) & Causal Inference

## 1. Cohort Extraction
- [ ] **SQL Execution**:
  - Implement a secure SQL executor to run the OHDSI-generated SQL (from Phase 2) against the CDM.
  - Extract the `Target`, `Comparator`, and `Outcome` cohorts into pandas DataFrames or temporary tables.

## 2. Feature Extraction (HDPS)
- [ ] **Automated Feature Construction**:
  - Implement logic to fetch *all* distinct `condition_concept_id` and `drug_concept_id` for patients in the T/C cohorts within the `covariate_window` (default: 365 days prior).
  - Create a sparse matrix (Patient x Feature).
  - **Optimization**: Use efficient SQL aggregation or Spark if data volume is massive (initially SQL + pandas/polars).

## 3. Outcome Processing
- [ ] **Time-to-Event Calculation**:
  - For each patient, determine if the Outcome occurred within the `Time-at-Risk` window.
  - Calculate `duration` (days to event or days to censor).
  - Handle **Censoring**: End of observation or end of risk window.

## 4. Causal Inference Pipeline
- [ ] **Propensity Score Modeling (PSM/IPTW)**:
  - Input: Feature Matrix + Treatment Assignment.
  - Model: Logistic Regression (or LightGBM) to estimate Propensity Score.
  - Matching/Weighting: Implement PS Matching (e.g., greedy nearest neighbor) or IPTW.
- [ ] **Balance Check**:
  - Calculate Standardized Mean Differences (SMD) for all covariates before and after adjustment.
  - Flag if major imbalances remain (SMD > 0.1).

## 5. Outcome Modeling
- [ ] **Cox Proportional Hazards**:
  - Use `lifelines` or `causalml`.
  - Input: Matched/Weighted population.
  - Model: `Hazard ~ Treatment`.
  - Output: Hazard Ratio (HR), 95% Confidence Interval, P-value.
- [ ] **Kaplan-Meier Estimation**:
  - Calculate survival curves for T and C groups.

## 6. Deliverables
- `Agent 5` capable of executing the full analysis pipeline.
- Functions for HDPS feature extraction.
- Validated statistical results (HR, CI) on test datasets.
