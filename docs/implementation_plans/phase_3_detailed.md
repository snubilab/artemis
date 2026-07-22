# Phase 3: Analysis Engine - Detailed Execution Plan

**Timeline**: W7-W10  
**Goal**: Target Trial Emulation을 위한 인과추론 파이프라인 구축

---

## Sub-Phase 3.1: Feature Extraction (HDPS)
**Goal**: 대규모 공변량 자동 추출

- [ ] **Task 3.1.1: Covariate Definition**
  - Create `src/analysis/covariates.py`
  - Define covariate groups:
    - Condition (diagnosis codes in prior 365 days)
    - Drug (prescription in prior 365 days)
    - Procedure (procedure codes in prior 365 days)
    - Demographics (age, gender)

- [ ] **Task 3.1.2: SQL-based Feature Extraction**
  - Create `src/analysis/feature_extraction.py`
  - Generate SQL for each covariate type:
    ```sql
    SELECT person_id, concept_id, 1 as feature_value
    FROM condition_occurrence
    WHERE condition_start_date BETWEEN (index_date - 365) AND index_date
    ```
  - Pivot to wide format (sparse matrix)

- [ ] **Task 3.1.3: Feature Store**
  - Create `src/analysis/feature_store.py`
  - Store extracted features in Redis or Parquet
  - Support incremental updates

---

## Sub-Phase 3.2: Outcome Processing
**Goal**: Time-at-Risk 윈도우 적용 및 Censoring

- [ ] **Task 3.2.1: Cohort Extraction**
  - Create `src/analysis/cohort_extractor.py`
  - Query Target, Comparator, Outcome cohorts from OMOP CDM
  - Extract: `person_id`, `cohort_start_date`, `cohort_end_date`

- [ ] **Task 3.2.2: Time-to-Event Calculation**
  - Create `src/analysis/survival.py`
  - Calculate:
    - `time_to_event = outcome_date - index_date`
    - `event = 1 if outcome occurred within TAR else 0`
    - `censoring_date = min(outcome_date, observation_end, TAR_end)`

- [ ] **Task 3.2.3: Outcome Table**
  - Generate survival analysis input:
    ```python
    @dataclass
    class SurvivalRecord:
        person_id: int
        treatment_group: str  # 'target' or 'comparator'
        time: float
        event: int  # 0=censored, 1=event
        covariates: Dict[str, float]
    ```

---

## Sub-Phase 3.3: Propensity Score Modeling
**Goal**: PSM/IPTW를 통한 교란변수 통제

- [ ] **Task 3.3.1: Propensity Score Estimation**
  - Create `src/analysis/propensity.py`
  - Implement logistic regression:
    ```python
    from sklearn.linear_model import LogisticRegression
    ps_model = LogisticRegression(max_iter=1000)
    ps_model.fit(X_covariates, y_treatment)
    propensity_scores = ps_model.predict_proba(X)[:, 1]
    ```

- [ ] **Task 3.3.2: Matching (PSM)**
  - Implement nearest-neighbor matching with caliper
  - Use `sklearn.neighbors.NearestNeighbors`
  - Default caliper: 0.2 * std(PS)

- [ ] **Task 3.3.3: Weighting (IPTW)**
  - Calculate inverse probability weights:
    ```python
    # Treated: 1/PS
    # Control: 1/(1-PS)
    ```
  - Apply stabilization and trimming

- [ ] **Task 3.3.4: Balance Diagnostics**
  - Create `src/analysis/balance.py`
  - Calculate Standardized Mean Difference (SMD) per covariate
  - Target: SMD < 0.1 for all covariates

---

## Sub-Phase 3.4: Outcome Modeling
**Goal**: Cox Proportional Hazards 분석

- [ ] **Task 3.4.1: Cox Model Implementation**
  - Create `src/analysis/cox.py`
  - Use `lifelines.CoxPHFitter`:
    ```python
    from lifelines import CoxPHFitter
    cph = CoxPHFitter()
    cph.fit(df, duration_col='time', event_col='event', 
            weights_col='weight' if IPTW else None)
    ```

- [ ] **Task 3.4.2: Hazard Ratio Extraction**
  - Extract HR, 95% CI, p-value
  - Log results to structured format

- [ ] **Task 3.4.3: Kaplan-Meier Estimation**
  - Create `src/analysis/km.py`
  - Use `lifelines.KaplanMeierFitter`
  - Generate survival curves per treatment group

---

## 📊 Phase 3 Deliverables

| Deliverable | File |
|-------------|------|
| Feature Extraction | `src/analysis/feature_extraction.py` |
| Survival Processing | `src/analysis/survival.py` |
| PS Modeling | `src/analysis/propensity.py` |
| Cox Analysis | `src/analysis/cox.py` |
| Balance Check | `src/analysis/balance.py` |
