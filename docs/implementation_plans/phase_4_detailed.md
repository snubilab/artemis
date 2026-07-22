# Phase 4: Reporting & Validation - Detailed Execution Plan

**Timeline**: W11-W13  
**Goal**: 시각화, 리포트 생성, End-to-End 검증

---

## Sub-Phase 4.1: Visualization Suite
**Goal**: Publication-quality 시각화 생성

- [ ] **Task 4.1.1: Forest Plot**
  - Create `src/reporting/plots/forest.py`
  - Input: List of `(study_name, HR, CI_lower, CI_upper)`
  - Output: Forest plot with reference line at HR=1
  - Library: `matplotlib`

- [ ] **Task 4.1.2: Kaplan-Meier Curve**
  - Create `src/reporting/plots/km_curve.py`
  - Input: KaplanMeierFitter objects per group
  - Output: Survival curves with confidence bands
  - Include: median survival, log-rank p-value

- [ ] **Task 4.1.3: Love Plot (SMD Balance)**
  - Create `src/reporting/plots/love.py`
  - Input: SMD values before/after matching
  - Output: Dot plot with threshold line at 0.1

- [ ] **Task 4.1.4: Propensity Score Distribution**
  - Create `src/reporting/plots/ps_dist.py`
  - Overlapping histograms for treated/control PS

---

## Sub-Phase 4.2: Report Generation
**Goal**: WeasyPrint 기반 PDF 리포트

- [ ] **Task 4.2.1: Report Template**
  - Create `src/reporting/templates/report.html`
  - Sections:
    1. Executive Summary
    2. Study Design (Target Trial Protocol)
    3. Cohort Characteristics
    4. Balance Diagnostics
    5. Outcome Analysis
    6. Appendix (ConceptSets, SQL)

- [ ] **Task 4.2.2: Template Data Model**
  - Create `src/reporting/models.py`
  - Define `ReportData` Pydantic model:
    ```python
    class ReportData(BaseModel):
        study_title: str
        cohort_sizes: Dict[str, int]
        balance_table: List[CovariateBalance]
        hazard_ratio: HazardRatioResult
        km_plot_path: str
        forest_plot_path: str
    ```

- [ ] **Task 4.2.3: PDF Generator**
  - Create `src/reporting/pdf_generator.py`
  - Render HTML template with Jinja2
  - Convert to PDF with WeasyPrint:
    ```python
    from weasyprint import HTML
    HTML(string=rendered_html).write_pdf(output_path)
    ```

- [ ] **Task 4.2.4: Comparative Validation Section**
  - Add comparison table: Simulated HR vs Published RCT HR
  - Statistical concordance check (overlapping CI)

---

## Sub-Phase 4.3: End-to-End Validation
**Goal**: MIMIC-IV 기반 Full Pipeline 검증

- [ ] **Task 4.3.1: Validation Scenario Selection**
  - Select 3+ well-known clinical studies with published RCT results
  - Document expected outcomes:
    | Study | Drug A vs B | Expected HR |
    |-------|-------------|-------------|
    | EMPA-REG | Empagliflozin vs Placebo | ~0.86 CV Death |
    | DECLARE | Dapagliflozin vs Placebo | ~0.93 MACE |

- [ ] **Task 4.3.2: E2E Test Script**
  - Create `scripts/e2e_validation.py`
  - Pipeline: NL Query → IR → Mapping → Assembly → Validation → Analysis → Report
  - Measure: Latency per stage, total runtime

- [ ] **Task 4.3.3: Accuracy Metrics**
  - Calculate concordance: % of studies where simulated HR CI overlaps published HR CI
  - Log mapping completeness, JSON validity rate

- [ ] **Task 4.3.4: Performance Optimization**
  - Profile bottlenecks (feature extraction, PS estimation)
  - Implement parallelization where possible
  - Target: < 5 min for full pipeline

---

## Sub-Phase 4.4: Documentation & Deployment Prep
**Goal**: 문서화 및 배포 준비

- [ ] **Task 4.4.1: API Documentation**
  - Generate OpenAPI spec from FastAPI
  - Add examples for each endpoint

- [ ] **Task 4.4.2: User Guide**
  - Create `docs/user_guide.md`
  - Installation, configuration, usage examples

- [ ] **Task 4.4.3: Docker Production Build**
  - Create `Dockerfile.prod`
  - Multi-stage build for smaller image
  - Health check endpoints

---

## 📊 Phase 4 Deliverables

| Deliverable | File |
|-------------|------|
| Forest Plot | `src/reporting/plots/forest.py` |
| KM Curve | `src/reporting/plots/km_curve.py` |
| Love Plot | `src/reporting/plots/love.py` |
| Report Template | `src/reporting/templates/report.html` |
| PDF Generator | `src/reporting/pdf_generator.py` |
| E2E Validation | `scripts/e2e_validation.py` |
| User Guide | `docs/user_guide.md` |

---

## 🎯 Final KPIs (Project-wide)

| KPI | Target | Measurement |
|-----|--------|-------------|
| Semantic Precision | > 95% | LLM Reranking 중의성 해결률 |
| Mapping Completeness | 100% | 복합제 성분 포함률 |
| JSON Validity | > 98% | ATLAS 로딩 성공률 |
| Confounder Control | SMD < 0.1 | 공변량 밸런스 달성률 |
| Evidence Reliability | CI Overlap | RCT 결과와 통계적 일치 |
