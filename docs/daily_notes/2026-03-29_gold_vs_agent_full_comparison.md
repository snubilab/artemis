# Gold vs Agent CIRCE -- Full Concept Set Comparison (LEADER Trial)

**Date**: 2026-03-29
**Data Source**: `LEADER_BENCHMARK` (synthea_cdm_leader, 10,000 persons)
**Gold CIRCE**: `artemis/data/gold/LEADER/LEADER_GOLD.json` (17 rules, 54 concept sets, 232 unique concepts)
**Agent CIRCE**: `artemis/tmp/tte/studies.json` study 420 (18 rules, 79 concept sets, 337 unique concepts)

---

## Summary

| Metric | Gold | Agent |
|---|---|---|
| Total inclusion rules | 17 | 18 |
| Total concept sets | 54 | 79 |
| Total unique concept IDs | 232 | 337 |
| Concept ID overlap | 51 | 51 |
| Concept IDs only in Gold | 181 | -- |
| Concept IDs only in Agent | -- | 286 |

**Key finding**: Only 51 out of 232 Gold concept IDs (22%) appear in the Agent CIRCE. Despite this low overlap, many Agent concept sets use different but semantically related OMOP concepts that are hierarchically related. The critical failures are in **HbA1c** (wrong measurement concepts) and **Stroke/TIA** (wrong condition concepts with zero data match).

---

## Semantic Rule Mapping

| Gold Rule | Agent Rule | Match Quality |
|---|---|---|
| Entry: DrugEra liraglutide | Entry: DrugEra liraglutide | Exact |
| R0: Age >= 50 | R0: Age >= 50 + CV; R1: Age >= 60 + risk | Structural diff |
| R1: HbA1c >= 7% | R3: HbA1c >= 7.0% | **BROKEN** |
| (implicit T2DM) | R2: Type 2 diabetes | Agent-only rule |
| R2: Prior CV disease (inclusion) | R8: CV disease or risk factors | Partial overlap |
| R3: No T1DM | R4: Type 1 diabetes | Match |
| R4: No calcitonin >= 50 | -- | **Missing in Agent** |
| R5: No GLP-1 RA/DPP-4/pramlintide | R9: GLP-1 RA/DPP-4 | **Mapping errors** |
| R6: No insulin | R10: Insulin | Partial overlap |
| R7: No acute glycemic decomp | R11: DKA+Hyperosmolar+Hypoglycemia | Broader |
| R8: No acute coronary/cerebrovascular | R12: Acute events | Close match |
| -- | R13: Planned revascularization | Agent-only rule |
| R9: No CHF (NYHA IV) | R5: Chronic HF NYHA IV | Structural diff |
| R10: No renal replacement | R6: Renal replacement | Close match |
| R11: No ESLD | R14: End-stage liver disease | Close match |
| R12: No transplant | R15: Solid organ transplant | Close match |
| R13: No malignant (5yr) | R16: Malignant neoplasm | Close match |
| R14: No MTC/MEN2 | R17: MTC/MEN2 | Close match |
| R15: No substance abuse | -- | **Missing in Agent** |
| R16: No pregnancy | -- | **Missing in Agent** |
| -- | R7: Anti-diabetic drug rules | Agent-only rule |

---

## Rule-by-Rule Comparison

### Entry Event: Liraglutide DrugEra

| | Gold | Agent |
|---|---|---|
| Concept set | CS32: liraglutide (40170911) | CS1: liraglutide (855765, 855816, 40170911) |
| Include descendants | Yes | Yes |
| Patients | 1,403 | 1,403 |
| **Verdict** | **Exact match** -- identical patient capture |

---

### R0 (Gold): Age >= 50 vs R0/R1 (Agent): Age + CV composites

**Gold R0**: Simple demographic filter -- age >= 50 at index date. 3,743 persons qualify.

**Agent R0**: Age >= 50 AND has cardiovascular disease (no concept sets, purely demographic + condition composite).
**Agent R1**: Age >= 60 AND has cardiovascular risk factors.

**Gap**: Gold uses a single simple age criterion. Agent splits into two age-gated rules with CV conditions attached, which is structurally different from the LEADER protocol. The LEADER protocol uses age >= 50 as one criterion and CV disease as a separate criterion (Gold R2). Combining them creates logical coupling that may produce different results.

**Impact**: Low on this dataset -- the CV criteria in R0/R1 overlap with R8, so the net effect may be similar. But the structural difference means the Agent CIRCE is not a faithful representation of the protocol logic.

---

### R1 (Gold): HbA1c >= 7% vs R3 (Agent): HbA1c >= 7.0%

| | Gold | Agent |
|---|---|---|
| Concepts | CS78: 3004410 (LOINC), 2212392 | CS3: 37171451, 37392408, 37395558 (SNOMED) |
| Descendants | No | No |
| Patients | **1,382** | **0** |

**Root cause**: The Agent uses SNOMED measurement concepts (37171451 = "HbA1c percent in blood") while the actual Synthea CDM data uses LOINC concept 3004410 ("Hemoglobin A1c/Hemoglobin.total in Blood"). SNOMED measurement concepts are technically Standard in OMOP but Synthea exclusively generates LOINC-mapped measurements.

**This is the #1 attrition-killing bug.** At Gold R3 (HbA1c step), every patient is excluded because 0 patients have measurements under the Agent's SNOMED concepts.

**Fix**: Replace Agent CS3 concepts with LOINC 3004410 (and optionally 2212392 for coverage).

---

### R2 (Agent only): Type 2 Diabetes

| | Agent |
|---|---|
| Concept set | CS2: 201826 (T2DM) + descendants |
| Patients | 3,262 |

**Note**: Gold does not have an explicit T2DM inclusion rule -- it is implied by the entry event (liraglutide is a diabetes drug) and the T1DM exclusion. Agent adds an explicit T2DM requirement, which is reasonable but slightly more restrictive than Gold.

---

### R2 (Gold): Prior CV Disease vs R8 (Agent): CV Disease or Risk Factors

This is the most complex rule in both CIRCEs. Gold R2 is a massive composite with 16 concept sets covering:

| Sub-criterion | Gold CS | Gold Patients | Agent CS | Agent Patients |
|---|---|---|---|---|
| Stroke/TIA | CS73 (10 concepts) | **501** | CS12 (27 concepts) | **0** |
| ACS | CS126 (5 concepts) | 277 | -- | -- |
| IHD/Coronary | CS85 (317576) | 0 | CS16 (4185932) | 277 |
| Heart Failure NYHA II-III | CS81 (315295, 316139) | 285 | CS17 (444031, 44782718) | 285 |
| Hypertension | CS87 (316866) | 169 | -- | -- |
| Revascularization | CS97 (46 concepts) | 211 | CS13 (49 concepts) | 108 |
| Arterial stenosis | CS80 (4 concepts) | 429 | CS14 (4069183, 37111502) | 270 |
| eGFR | CS116 (3 meas concepts) | 117 | -- | -- |
| CKD 4-5 | CS119 (443612, 443611) | 270 | CS18 (4030518, 4134595) | 0 |
| LV dysfunction | CS125 (2 concepts) | 163 | -- | -- |
| LV hypertrophy | CS124 (4184746) | 169 | -- | -- |
| Microalbuminuria | CS122 (2 concepts) | 156 | -- | -- |
| Claudication/ABI | CS123 (2 concepts) | 159 | -- | -- |
| Carotid stenting | CS120 (3 concepts) | -- | CS41 (3 concepts) | -- |
| Limb surgery | CS121 (10 concepts) | -- | CS42 (12 concepts) | -- |

**Critical gaps in Agent R8**:

1. **Stroke/TIA (501 patients)**: Agent CS12 has 27 concepts but **none** match data in synthea_cdm_leader. Only 4 of Agent's 27 concepts are descendants of Gold's 10 concepts. The Gold concept 372924 ("Cerebral artery occlusion") alone captures all 501 stroke patients; the Agent uses more granular concepts that are not present in this dataset.

2. **Hypertension missing**: Gold includes hypertension (316866, 169 patients) as a CV risk factor. Agent does not have this.

3. **eGFR measurement missing**: Gold checks eGFR measurements (117 patients). Agent has no measurement-based CV criterion.

4. **CKD 4-5**: Gold uses 443612/443611 (270 patients). Agent uses 4030518/4134595 ("Renal impairment") with no descendants, yielding 0 patients.

5. **LV dysfunction/hypertrophy missing**: Gold checks for these (163 and 169 patients respectively). Agent omits them.

6. **Microalbuminuria/proteinuria missing**: Gold checks this (156 patients). Agent omits it.

7. **Ankle brachial index / claudication missing**: Gold checks this (159 patients). Agent omits it.

8. **Milia mapping error**: Agent CS11 is named "Multiple eruptive milia" -- this is a **skin condition**, not cardiovascular. Likely the mapping agent confused "MI" (myocardial infarction) with "milia". This concept set contains 0 cardiovascular concepts.

**Impact**: The Agent's CV composite rule captures significantly fewer patients than Gold's, primarily due to missing stroke concepts, hypertension, renal criteria, and LV criteria. However, since HbA1c already eliminates everyone at R3, this difference is masked in practice.

---

### R3 (Gold): No T1DM vs R4 (Agent): Type 1 Diabetes

| | Gold | Agent |
|---|---|---|
| Concepts | CS90: 201254, 435216, 40484648 | CS19: 201254 |
| Patients | 0 | 0 |
| **Verdict** | **Functionally equivalent** on this dataset (no T1DM patients) |

Gold includes 3 concepts; Agent only uses 201254. The extra Gold concepts (435216 = "Diabetes mellitus without complication", 40484648 = "Type 1 diabetes mellitus uncontrolled") provide broader coverage but do not matter here.

---

### R4 (Gold): No Calcitonin >= 50 ng/L -- **Missing in Agent**

| | Gold | Agent |
|---|---|---|
| Concepts | CS92: 3010989 | -- |
| Patients with measurement | 1,396 | -- |
| **Verdict** | **Agent missing** -- calcitonin screening criterion not implemented |

The LEADER trial requires calcitonin < 50 ng/L. Agent omits this measurement-based exclusion entirely.

---

### R5 (Gold): No GLP-1 RA/DPP-4/Pramlintide vs R9 (Agent): GLP-1 RA/DPP-4

| | Gold | Agent |
|---|---|---|
| GLP-1 RA | CS93: 6 concepts (albiglutide, dulaglutide, exenatide, liraglutide, etc.) | CS20/21: glimepiride (1597756) -- **wrong drug class!** |
| DPP-4 | CS117: 5 concepts | CS22: sitagliptin (8 concepts) |
| Pramlintide | CS52: 1517998 | -- |
| GLP-1 RA patients | 1,403 | 0 (glimepiride is a sulfonylurea, not GLP-1) |
| DPP-4 patients | 0 | 0 |

**Critical mapping error**: Agent CS20/CS21 is labeled "glimepiride" which is a **sulfonylurea**, not a GLP-1 receptor agonist. The Agent completely fails to exclude prior GLP-1 RA use. This is masked because the drug_era table on this dataset shows 0 glimepiride patients anyway.

---

### R6 (Gold): No Insulin vs R10 (Agent): Insulin

| | Gold | Agent |
|---|---|---|
| Concepts | CS95: 19 concepts | CS23-28: 31 unique concepts |
| Patients | 1,403 | 1,403 |
| **Verdict** | **Match** -- both capture the same patient set |

The Agent has broader insulin coverage (more specific insulin types) but the net patient capture is identical.

---

### R7 (Gold): No DKA vs R11 (Agent): Glycemic Decompensation

| | Gold | Agent |
|---|---|---|
| Gold | CS54: DKA only (443727) | CS29-32: DKA + Hyperosmolar + Hypoglycemia |
| Patients | 0 | 0 |
| **Verdict** | Agent is **broader** (includes hypoglycemia, hyperosmolar states) |

No impact on this dataset but Agent is more conservative.

---

### R8 (Gold): No Acute Coronary/Cerebrovascular vs R12 (Agent): Acute Events

| | Gold | Agent |
|---|---|---|
| MI | CS115: 312327, 4329847, 314666 | CS33-34: 312327, 381316, 4215140, 4329847 |
| Stroke | CS96: 9 concepts | CS36-38: cerebral infarction + hemorrhage + TIA |
| Unstable angina | (in CS96/115) | CS35: 315296, 4078531, 4119942 |
| Patients | 277 (MI) | 277 (combined) |
| **Verdict** | **Close match** |

---

### R13 (Agent only): Planned Revascularization

| | Agent |
|---|---|
| Concepts | CS39-42: limb, coronary, carotid, femoral (28 concepts) |
| Patients | 112 |

Gold does not have a separate "planned revascularization" exclusion. This is an Agent addition that would exclude 112 additional patients.

---

### R9 (Gold): No CHF NYHA IV vs R5 (Agent): Chronic HF NYHA IV

| | Gold | Agent |
|---|---|---|
| HF concepts | CS81: 315295, 316139 | CS43: 444031 |
| + O2 therapy | CS98: 4239130 | -- |
| HF patients | 285 | 285 |
| O2 patients | 0 | -- |
| **Verdict** | **Close match** -- Gold uses NYHA II-III codes, Agent uses generic chronic HF |

Gold's approach is more specific (NYHA class codes) while Agent uses generic "Chronic heart failure" (444031) which catches the same patients in this dataset.

---

### R10 (Gold): No Renal Replacement vs R6 (Agent): Renal Replacement

| | Gold | Agent |
|---|---|---|
| Concepts | CS99 ESRD + CS102 dialysis + CS103-104 kidney transplant | CS44: 4 concepts |
| Patients | 0 | 0 |
| **Verdict** | **Functionally equivalent** -- no patients affected |

---

### R11 (Gold): No ESLD vs R14 (Agent): End-Stage Liver Disease

| | Gold | Agent |
|---|---|---|
| Concepts | CS57 (6) + CS105 bilirubin + CS106-107 | CS45-50 (19 concepts) |
| Patients | 0 | 0 |
| **Verdict** | **Functionally equivalent** -- no patients affected |

Agent includes hepatorenal syndrome, portal pyemia, and acute liver necrosis which Gold does not. Both capture 0 patients.

---

### R12 (Gold): No Transplant vs R15 (Agent): Solid Organ Transplant

| | Gold | Agent |
|---|---|---|
| Concepts | CS108 (10 conditions) + CS109 (10 procedures) | CS51-57 (25 concepts) |
| Patients | 0 | 0 |
| **Verdict** | **Functionally equivalent** |

---

### R13 (Gold): No Malignancy (5yr) vs R16 (Agent): Malignant Neoplasm

| | Gold | Agent |
|---|---|---|
| Concepts | CS110: 443392, 42542326 (2 broad concepts) | CS58-76: 32 organ-specific concepts |
| Patients | 0 | 0 |
| Time window | 1825 days prior | Not time-windowed |
| **Verdict** | **Structurally different** -- Gold uses 2 broad ancestor concepts; Agent enumerates specific cancer types |

Gold's approach (443392 = "Malignant neoplastic disease" with descendants) should subsume all of Agent's specific cancer concepts. Agent's approach is redundant but not wrong.

---

### R14 (Gold): No MTC/MEN2 vs R17 (Agent): MTC/MEN2

| | Gold | Agent |
|---|---|---|
| Gold | CS67: MEN2 (24612) + CS68: MTC (4111011) | CS77-79: MTC (4 concepts) + MEN2 (2 concepts) |
| Patients | 0 | 0 |
| **Verdict** | **Functionally equivalent** |

---

### R15 (Gold): No Substance Abuse -- **Missing in Agent**

| | Gold | Agent |
|---|---|---|
| Concepts | CS111: 436954, 440069, 4279309 | -- |
| Patients | 0 | -- |
| **Verdict** | **Agent missing** -- no impact on this dataset |

---

### R16 (Gold): No Pregnancy -- **Missing in Agent**

| | Gold | Agent |
|---|---|---|
| Concepts | CS113: 4088927 | -- |
| Patients | 0 | -- |
| **Verdict** | **Agent missing** -- no impact on this dataset |

---

### R7 (Agent only): Anti-Diabetic Drug Rules

Agent R7 uses concept sets CS4-CS9 containing a total of 84 unique drug concepts covering the full anti-diabetic drug spectrum. CS4/CS6 are mislabeled as "teplizumab" but actually contain all insulin, GLP-1, DPP-4, SGLT2, sulfonylurea, and other anti-diabetic drug ingredients.

This appears to be an inclusion rule for anti-diabetic drug use -- verifying that patients are on some form of anti-diabetic treatment. Gold does not have an equivalent explicit rule (it is implied by the liraglutide entry event).

---

## Missing Concepts Summary

### Gold-only concepts not in Agent (181 concepts)

Most impactful categories:

| Category | Gold Concepts | Patient Impact |
|---|---|---|
| HbA1c measurement | 3004410 (LOINC) | **1,382 patients** |
| Stroke/TIA | 372924, 375557, 376713, 443454, etc. (10) | **501 patients** |
| Arterial stenosis | 442615, 4119613, 1414819, 321052 | 429 patients |
| Hypertension | 316866 | 169 patients |
| LV hypertrophy | 4184746 | 169 patients |
| LV dysfunction | 4212798, 4047088 | 163 patients |
| Claudication/ABI | 315558, 442774 | 159 patients |
| Microalbuminuria | 4195061, 75650 | 156 patients |
| eGFR measurements | 3027108, 3029859, 3049187 | 117 patients |
| Calcitonin measurement | 3010989 | 1,396 patients |
| GLP-1 RA drugs | 44816332, 45774435, 1583722, etc. | 1,403 patients |

### Agent-only concepts not in Gold (286 concepts)

Most are more granular versions of Gold concepts or erroneous mappings:

| Category | Issue |
|---|---|
| CS11 "Multiple eruptive milia" | **Mapping error** -- skin condition, not cardiovascular |
| CS4/CS6 "teplizumab" (84 concepts) | Mislabeled -- actually all anti-diabetic drugs |
| CS5 "carbetapentane" | **Mapping error** -- antitussive drug, not anti-diabetic |
| HbA1c SNOMED concepts | Wrong vocabulary -- should use LOINC |
| Stroke CS12 granular concepts | Too specific, none present in Synthea data |

---

## Patient Count Impact

| Rule | Gold Patients | Agent Patients | Delta | Impact |
|---|---|---|---|---|
| Entry: Liraglutide | 1,403 | 1,403 | 0 | None |
| HbA1c >= 7% | 1,382 | **0** | **-1,382** | **CRITICAL** |
| CV disease (inclusion) | ~1,100 composite | ~600 composite | ~-500 | **HIGH** |
| -- Stroke/TIA | 501 | 0 | -501 | HIGH |
| -- Revascularization | 211 | 108 | -103 | MEDIUM |
| -- Arterial stenosis | 429 | 270 | -159 | MEDIUM |
| -- Hypertension | 169 | missing | -169 | MEDIUM |
| -- eGFR | 117 | missing | -117 | MEDIUM |
| -- LV dysfunction | 163 | missing | -163 | MEDIUM |
| -- Microalbuminuria | 156 | missing | -156 | MEDIUM |
| T1DM exclusion | 0 | 0 | 0 | None |
| GLP-1 RA exclusion | 1,403 | 0 (wrong drug) | N/A | Masked |
| Insulin exclusion | 1,403 | 1,403 | 0 | None |
| All other exclusions | 0 | 0 | 0 | None |

---

## Key Findings (Ranked by Impact)

### 1. HbA1c Measurement Concepts (CRITICAL)

**Problem**: Agent uses SNOMED measurement concepts (37171451, 37392408, 37395558) instead of LOINC concept 3004410. Synthea data only uses LOINC.

**Impact**: 0 patients match vs 1,382 in Gold. This single error eliminates the entire cohort at the HbA1c step.

**Fix**: Replace Agent CS3 with `[3004410]` (LOINC "Hemoglobin A1c/Hemoglobin.total in Blood").

### 2. Stroke/TIA Concepts (HIGH)

**Problem**: Agent CS12 uses 27 granular stroke concepts (e.g., "Cerebrovascular accident due to occlusion of left posterior communicating artery") that are too specific. Gold uses 10 broader ancestor concepts like 372924 ("Cerebral artery occlusion") that subsume all descendants.

**Impact**: 501 patients lost from the CV inclusion criterion. Only 4 of Agent's 27 concepts are descendants of Gold's concepts.

**Fix**: Use broader stroke/TIA concepts: 372924, 443454, 376713, 373503 at minimum.

### 3. CV Composite Missing Sub-criteria (HIGH)

**Problem**: Agent R8 is missing hypertension, eGFR, LV dysfunction/hypertrophy, microalbuminuria, and claudication/ABI criteria that Gold R2 includes.

**Impact**: ~500 additional patients lost from the CV inclusion criterion across multiple sub-criteria.

**Fix**: Add these concept sets to the Agent's CV composite rule.

### 4. GLP-1 RA Mapping Error (MEDIUM -- currently masked)

**Problem**: Agent CS20/CS21 maps to glimepiride (a sulfonylurea) instead of GLP-1 receptor agonists (exenatide, dulaglutide, etc.).

**Impact**: Currently 0 for both because glimepiride is not in the data, but this would cause incorrect behavior on real-world data.

**Fix**: Replace with proper GLP-1 RA concepts from Gold CS93.

### 5. "Milia" Mapping Error (LOW -- cosmetic)

**Problem**: Agent CS11 maps "MI" to "Multiple eruptive milia" (a skin condition) instead of myocardial infarction.

**Impact**: 0 patients -- the concept set is used in the CV composite but catches no cardiovascular patients.

**Fix**: Remove CS11 or replace with proper MI concept set.

---

## Recommendations

1. **Immediate**: Fix HbA1c concepts (LOINC 3004410) to unblock the entire cohort
2. **High priority**: Replace Agent stroke concepts with broader ancestors (372924, 443454, 376713, 373503)
3. **High priority**: Add missing CV sub-criteria (hypertension, eGFR, LV dysfunction, microalbuminuria)
4. **Medium**: Fix GLP-1 RA mapping (replace glimepiride with actual GLP-1 RA concepts)
5. **Low**: Fix "milia" mapping error in CS11
6. **Low**: Add missing exclusions (calcitonin, substance abuse, pregnancy) for protocol completeness
