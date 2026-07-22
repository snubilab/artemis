# Gold vs Agent CV Concept Set Comparison - LEADER Trial

**Date**: 2026-03-29
**Gold Rule**: Rule 2 "prior CV disease" (AT_LEAST 1 of 10 criteria groups)
**Agent Rule**: Rule 8 "Cardiovascular disease or risk factors" (9 CriteriaList entries)

## Summary

| Metric | Gold | Agent |
|--------|------|-------|
| Combined unique patients | **2198** | **1210** |
| Criteria count | 10 | 9 |
| Total concept IDs | 94 | 98 |
| Patient gap | -- | **-988 (45% miss)** |

The agent CV composite catches only ~55% of the patients that the gold standard captures.

## Root Cause Analysis

### Critical Failures (0 patients matched)

| Agent Criterion | Expected Match | Agent Concepts | Problem |
|---|---|---|---|
| CS#10 "High risk CV disease" | General CV | `601865` Fear of heart disease, etc. | **Completely wrong concepts** - mapped to "Fear of heart disease" and observation concepts, not actual CV disease conditions |
| CS#11 "Prior MI" | MI (277 patients) | `4033859` Multiple eruptive milia | **Catastrophic mismatch** - mapped to "milia" (skin condition) instead of "myocardial infarction" |
| CS#12 "Stroke/TIA" | Stroke (501 patients) | 27 stroke-specific concepts | **Too narrow** - used only named stroke subtypes (e.g., "CVA due to occlusion of left posterior communicating artery") instead of broad categories like `443454` Cerebral infarction with descendants |
| CS#15 "Symptomatic CHD" | CHD | `1075487` CHD8 overgrowth syndrome, `601630` Assessment of risk | **Wrong concepts** - "CHD8 overgrowth" is a genetic syndrome, not coronary heart disease |

### Partial Matches

| Agent Criterion | Patients | Gold Equivalent | Gold Patients | Gap |
|---|---|---|---|---|
| CS#13 Revascularization | 108 | CS#97+120+121 (319 combined) | 319 | -211 |
| CS#14 Stenosis | 270 | CS#80 Arterial stenosis | 429 | -159 |
| CS#16 Ischemic heart disease | 277 | CS#126 ACS | 277 | 0 |
| CS#17 CHF | 285 | CS#81 Heart Failure | 285 | 0 |
| CS#18 Renal impairment | 270 | CS#119 CKD 4-5 | 270 | 0 |

### Concept-Level Comparison

#### 1. ACS / MI -- Gold CS#126 vs Agent CS#11 + CS#16

**Gold CS#126 "ACS" (277 patients):**
- `312327` Acute myocardial infarction (descendants=True)
- `434376` Acute MI of anterior wall (descendants=True)
- `438170` Acute MI of inferior wall (descendants=True)
- `444406` Acute subendocardial infarction (descendants=True)
- `315296` Preinfarction syndrome (descendants=True)

**Agent CS#16 "Ischemic heart disease" (277 patients) -- GOOD MATCH:**
- `4185932` Ischemic heart disease (descendants=True) -- broad parent that captures MI via concept_ancestor

**Agent CS#11 "Prior MI" (0 patients) -- COMPLETELY WRONG:**
- `4033859` Multiple eruptive milia -- SKIN CONDITION, not MI
- `4112750` Secondary milia
- `4115283` Primary milia
- `4299135` Neonatal milia
- `4338757` Milia of eyelid
- `36714391` Absence of fingerprints with congenital milia syndrome

**Diagnosis**: The mapping agent confused "MI" (myocardial infarction) with "milia" (dermatological condition). The ChromaDB embedding similarity search matched the wrong medical term.

#### 2. Stroke/TIA -- Gold CS#96+73 vs Agent CS#12

**Gold CS#96 "Stroke" + CS#73 "Stroke, TIAs" (501 patients):**
Uses broad ancestor concepts with descendants:
- `443454` Cerebral infarction (descendants=True) -- THIS is the key concept
- `373503` Transient cerebral ischemia (descendants=True)
- Plus individual hemorrhagic stroke concepts (descendants=False)

**Agent CS#12 (0 patients):**
Uses 27 very specific descendant concepts like:
- `603206` CVA due to occlusion of left posterior communicating artery
- `609313` CVA due to embolism of right carotid artery
- etc.

**Diagnosis**: The agent mapped to **leaf-level** stroke concepts that are children of `443454` Cerebral infarction. These specific concepts do not exist in Synthea-generated data (Synthea generates records at the standard ancestor level, not at these granular subtypes). The gold standard correctly uses the **ancestor** concept `443454` with `includeDescendants=True`.

#### 3. Revascularization -- Gold CS#97+120+121 vs Agent CS#13

**Gold CS#97 (211 patients):** 46 coronary revascularization concepts (PTCA, stenting, CABG)
**Gold CS#120 (0 patients):** 3 carotid procedures
**Gold CS#121 (108 patients):** 10 peripheral limb procedures

**Agent CS#13 (108 patients):** 49 mixed concepts -- includes limb/intracranial procedures but MISSING all coronary procedures (PTCA, coronary stenting, CABG)

Key missing Gold concepts not in Agent:
- `4006788` Percutaneous transluminal coronary angioplasty
- `4283892` Placement of stent in coronary artery
- `4181025` PTCA with insertion of stent into coronary artery
- `4020466` Arterial bypass graft
- `2000064` PTCA
- All other coronary-specific procedures

**Diagnosis**: Agent revascularization set focuses on peripheral and intracranial vascular procedures but completely misses coronary revascularization, which is the primary source of patients in Synthea data.

#### 4. Stenosis -- Gold CS#80 vs Agent CS#14

**Gold CS#80 (429 patients):** 4 concepts with descendants
- `442615` Carotid artery stenosis
- `4119613` Coronary artery stenosis
- `1414819` Lower extremity arterial stenosis
- `321052` Peripheral vascular disease

**Agent CS#14 (270 patients):** 2 concepts
- `4069183` Subaortic stenosis -- too specific (cardiac valve, not arterial)
- `37111502` Stenosis of artery -- catches only carotid stenosis descendants (270)

**Missing**: Coronary artery stenosis (`4119613`), PVD (`321052`)

#### 5. Heart Failure -- GOOD MATCH

Gold CS#81 (285) = Agent CS#17 (285). Both capture heart failure correctly.

#### 6. Renal -- PARTIAL MATCH

Gold uses BOTH:
- CS#116 eGFR measurement (117 patients) -- Agent has NO measurement equivalent
- CS#119 CKD 4-5 condition (270 patients) -- Agent CS#18 has similar but different concepts

Agent CS#18 uses `4030518` Renal impairment (no descendants!) and `4134595` Chronic disease of genitourinary system (no descendants!). The 270 count matches because these happen to capture the same CKD population, but the agent misses the 117 eGFR measurement patients.

## Key Mapping Failures Summary

| Failure Type | Criterion | Impact | Fix |
|---|---|---|---|
| **Wrong term (homophone)** | MI -> milia | 277 patients lost | Map to `312327` Acute MI |
| **Too narrow (leaf concepts)** | Stroke subtypes | 501 patients lost | Use `443454` Cerebral infarction + `373503` TIA with descendants |
| **Missing coronary procedures** | Revascularization | 211 patients lost | Add PTCA, coronary stenting, CABG concepts |
| **Wrong ancestor** | Stenosis | 159 patients lost | Add `4119613` Coronary stenosis, `321052` PVD |
| **Observation vs Condition** | CV risk factors | N/A in data | Use actual CV condition codes |
| **Missing measurement domain** | eGFR | 117 patients lost | Add eGFR LOINC concepts as Measurement criteria |
| **Missing descendants flag** | Renal impairment | Risk of future miss | Enable includeDescendants |

## Recommendations for Mapping Agent Improvement

1. **Homophone disambiguation**: When mapping "MI", "CHD", or other medical abbreviations, verify the OMOP domain matches the clinical context. "MI" in cardiology = myocardial infarction, not milia.

2. **Ancestor preference**: For cohort definitions, prefer broad ancestor concepts with `includeDescendants=True` over lists of specific leaf concepts. Synthea data uses standard ancestor concepts.

3. **Coronary procedure coverage**: The revascularization concept set needs explicit coronary procedure concepts (PTCA, stenting, CABG) -- these are the most common revascularization procedures.

4. **Domain awareness**: The mapping agent should match the CIRCE domain requirement. A `ConditionOccurrence` criterion should not receive Observation or Measurement concepts.

5. **Vocabulary preference**: For conditions, prefer SNOMED concepts that are standard in OMOP. For procedures, include both ICD/CPT-derived and SNOMED procedure concepts.
