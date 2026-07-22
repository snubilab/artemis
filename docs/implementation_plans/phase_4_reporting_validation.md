# Phase 4: Reporting & Validation Implementation Plan

**Timeline**: Weeks 11-13
**Focus**: Agent 6 (Reporting Agent), Visualization & Full System Test

## 1. Visualization Module
- [ ] **KM Curve Generator**:
  - Use `matplotlib` or `seaborn` (or `lifelines` built-in) to plot Kaplan-Meier survival curves.
  - Style for publication quality (risk table, confidence bands).
- [ ] **Forest Plot**:
  - Visualize the Hazard Ratio and CI.
- [ ] **Love Plot (Balance Plot)**:
  - Visualize SMD reduction (Unadjusted vs. Adjusted) to demonstrate matching quality.

## 2. Agent 6: Reporting Agent
- [ ] **Narrative Generation**:
  - Use LLM to generate text explaining the methodology and results.
  - Inputs: Study parameters (from IR), statistical results (HR, p-value), SMD summary.
  - Template: "We conducted a cohort study... The propensity score matched analysis showed..."
- [ ] **Report Assembly**:
  - Use `WeasyPrint` (HTML to PDF).
  - Design HTML/CSS templates for the Clinical Report.
  - Embed generated plots (as images) and narrative text.

## 3. Comparative Validation
- [ ] **RCT Comparison**:
  - If a "Gold Standard" RCT is provided/retrieved, parse its results.
  - Compare the System's HR with the RCT's HR.
  - Generate an interpretation of consistency.

## 4. End-to-End System Validation
- [ ] **Full Pipeline Test**:
  - Run the complete flow: Question -> Report.
  - Dataset: MIMIC-IV (mapped to OMOP CDM).
  - Scenarios: Replicate 3-5 known clinical studies (e.g., Metformin vs. Sulfonylurea).
- [ ] **Performance Tuning**:
  - Identify bottlenecks (e.g., Vector Search, Feature Extraction SQL).
  - Optimize via caching or query tuning.

## 5. Deliverables
- `Agent 6` producing PDF reports.
- Visualization library.
- Final "ARTEMIS 3.1" Release Candidate.
- Validation Report comparing system output vs. known evidence.
