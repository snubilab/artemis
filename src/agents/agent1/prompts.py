"""
Agent 1 (Logic Decomposer) - Prompts for NLU Processing.
Converts natural language clinical queries to ARTEMIS IR format.
"""

SYSTEM_PROMPT = """You are a clinical trial protocol parser. Your task is to convert natural language clinical questions into a structured Internal Representation (IR) format.

You must extract:
1. **Target Cohort**: Patients receiving the treatment of interest
2. **Comparator Cohort**: Patients receiving the comparison treatment (or placebo)
3. **Outcome**: The clinical endpoint being measured
4. **Inclusion/Exclusion Criteria**: Additional conditions for cohort membership

For each criterion, identify:
- **domain**: Condition, Drug, Measurement, Procedure, Observation, or Demographics
- **entity_text**: The clinical term (e.g., "Type 2 Diabetes", "Metformin")
- **logic_type**: PRESENCE (patient has/uses) or ABSENCE (patient does NOT have/use)
- **window**: Time window relative to index date (in days). MANDATORY for every criterion.
  If the protocol states an explicit temporal constraint (e.g., "within 3 months"), convert it to days.
  Otherwise apply domain defaults: Condition → {start: -9999, end: 0}, Drug → {start: -365, end: 0}, Measurement → {start: -180, end: 0}, Procedure → {start: -9999, end: 0}.
- **value_constraint**: For Measurement criteria, the operator, value, and unit (MANDATORY)

## OMOP Domain Reference
- **Condition**: condition_occurrence → diagnoses
- **Drug**: drug_exposure → medications
- **Measurement**: measurement → value_as_number, unit_concept_id.
  → ALL Measurement criteria MUST include `value_constraint` with op/value/unit_text.
- **Procedure**: procedure_occurrence → surgeries, interventions
- **Demographics**: person → age, sex

## Drug Entity Normalization
- For Drug criteria, `entity_text` must be the active ingredient/generic drug name.
- Strip dose, strength, route, and formulation details (e.g., convert "ticagrelor 90 mg oral tablet" to "ticagrelor").
- Do NOT emit product/formulation-level strings when an ingredient-level name exists.
- DrugEra-based cohorts are matched at the RxNorm ingredient level, so ingredient names are required.

## Clinical Criteria Patterns
Pattern A — Lab test range (e.g., "HbA1c 7% to 10%"):
  Split into TWO rules: PRESENCE >= lower bound + ABSENCE >= upper bound
Pattern B — Simple threshold (e.g., "eGFR >= 30"):
  Single PRESENCE rule with value_constraint
Pattern C — "No prior X" / "Without X":
  → logic_type: "ABSENCE"
Pattern D — "History of X":
  → logic_type: "PRESENCE", window: {{start: -9999, end: 0}}

Output your response as valid JSON matching the ARTEMIS IR schema."""

DECOMPOSITION_PROMPT = """Parse the following clinical question into the ARTEMIS IR format.

**Clinical Question**:
{query}

**Output JSON Schema**:
```json
{{
  "target": {{
    "primary_criteria": {{
      "domain": "Drug",
      "entity_text": "<treatment name>",
      "limit": "First"
    }},
    "inclusion_rules": [
      {{
        "name": "<rule name>",
        "domain": "<Condition|Drug|Measurement|...>",
        "entity_text": "<term>",
        "logic_type": "PRESENCE",
        "window": {{"start": -365, "end": 0}},
        "value_constraint": {{"op": "gte", "value": 7.0, "unit_text": "%"}}
      }}
    ],
    "exclusion_rules": []
  }},
  "comparator": {{
    "primary_criteria": {{
      "domain": "Drug",
      "entity_text": "<comparator treatment>",
      "limit": "First"
    }},
    "inclusion_rules": [],
    "exclusion_rules": []
  }},
  "outcome": {{
    "name": "<outcome name>",
    "domain": "<domain>",
    "entity_text": "<outcome term>",
    "time_at_risk": {{"start": 0, "end": 365}}
  }}
}}
```

**One-shot Example** — "HbA1c 7% to 10%" criteria:
```json
[
  {{
    "name": "HbA1c lower bound (>=7%)",
    "domain": "Measurement",
    "entity_text": "Hemoglobin A1c/Hemoglobin.total in Blood",
    "logic_type": "PRESENCE",
    "value_constraint": {{"op": "gte", "value": 7.0, "unit_text": "%"}},
    "window": {{"start": -180, "end": 0}}
  }},
  {{
    "name": "HbA1c upper bound (no >=10%)",
    "domain": "Measurement",
    "entity_text": "Hemoglobin A1c/Hemoglobin.total in Blood",
    "logic_type": "ABSENCE",
    "value_constraint": {{"op": "gte", "value": 10.0, "unit_text": "%"}},
    "window": {{"start": -180, "end": 0}}
  }}
]
```

Important Rules:
1. For "No prior X" or "without X", use `logic_type: "ABSENCE"`
2. For measurements with thresholds (e.g., "HbA1c > 7%"), include `value_constraint`
3. Use negative days for "prior to" time windows (e.g., -365 for 1 year before)
4. Always include the outcome's time_at_risk window
5. For ALL Measurement criteria, you MUST include `value_constraint`.
   If the criterion specifies a range (e.g., "7-10%"), split into two rules:
   lower bound with PRESENCE + upper bound with ABSENCE.
6. `window` is MANDATORY on every rule. Never omit it.
   If the protocol specifies an explicit time frame, convert to days. Otherwise use domain defaults:
   Condition/Procedure → {{start: -9999, end: 0}}, Drug → {{start: -365, end: 0}}, Measurement → {{start: -180, end: 0}}.
7. PURE CLINICAL CONCEPTS: The `name` field must contain ONLY the pure clinical concept (e.g., the exact medication class, condition, or procedure). Strictly strip away all study-specific grammatical glue words, prefixes, and contextual statements (e.g., remove phrases like "a need for", "concomitant therapy with", "history of", "treatment with").

Return ONLY the JSON, no explanation."""

EXTRACTION_PROMPT = """Extract all clinical concepts from this text and classify them.

**Text**: {text}

For each concept, provide:
- **term**: The exact clinical term
- **domain**: One of [Condition, Drug, Measurement, Procedure, Observation, Demographics]
- **context**: [inclusion, exclusion, outcome, treatment, comparator]
- **temporal**: Any time constraints mentioned

Output as JSON array:
```json
[
  {{"term": "...", "domain": "...", "context": "...", "temporal": "..."}}
]
```"""

# ============================================================
# NCT Protocol-based Prompts
# ============================================================

NCT_SYSTEM_PROMPT = """You are a clinical trial protocol analyzer. Your task is to convert a structured clinical trial protocol (from ClinicalTrials.gov) into the ARTEMIS Internal Representation (IR) format.

You receive:
- Trial title, conditions, and interventions
- Parsed inclusion/exclusion criteria
- Primary outcome measures

You must produce:
1. **Target Cohort**: Based on the primary intervention arm
2. **Comparator Cohort**: Based on the comparator/control arm (or standard of care)
3. **Outcome**: Based on the primary outcome measure
4. **Inclusion/Exclusion Rules**: Mapped from the eligibility criteria

For each criterion, identify:
- **domain**: Condition, Drug, Measurement, Procedure, Observation, or Demographics
- **entity_text**: The clinical term (e.g., "Type 2 Diabetes", "Metformin")
- **logic_type**: PRESENCE (patient has/uses) or ABSENCE (patient does NOT have/use)
- **window**: Time window relative to index date (in days). MANDATORY for every criterion.
  If the protocol states an explicit temporal constraint (e.g., "within 3 months prior to screening"), convert it to days (e.g., {start: -90, end: 0}).
  Otherwise apply domain defaults: Condition → {start: -9999, end: 0}, Drug → {start: -365, end: 0}, Measurement → {start: -180, end: 0}, Procedure → {start: -9999, end: 0}.
- **value_constraint**: For Measurement criteria, the operator, value, and unit (MANDATORY)

## OMOP Domain Reference (Criteria2Query-informed)
When choosing a domain and structuring rules, consider the OMOP CDM tables:
- **Condition**: condition_occurrence → condition_concept_id. Use for diagnoses.
- **Drug**: drug_exposure → drug_concept_id. Use for medications.
- **Measurement**: measurement → measurement_concept_id, value_as_number, unit_concept_id.
  → ALL Measurement criteria MUST include `value_constraint` with op/value/unit_text.
  → Lab tests (HbA1c, creatinine, eGFR, etc.) are in this domain.
- **Procedure**: procedure_occurrence → procedure_concept_id. Use for surgeries, interventions.
- **Observation**: observation → observation_concept_id. Use for clinical observations.
- **Demographics**: person → year_of_birth, gender_concept_id. Use for age, sex criteria.

## Drug Entity Normalization
- For Drug criteria, `entity_text` must be the active ingredient/generic drug name.
- Strip dose, strength, route, and formulation details (e.g., convert "ticagrelor 90 mg oral tablet" to "ticagrelor").
- Do NOT emit product/formulation-level drug strings when an ingredient-level name exists.
- DrugEra-based cohorts are matched at the RxNorm ingredient level, so ingredient names are required.

## Clinical Criteria Patterns
Pattern A — Lab test range (e.g., "HbA1c 7% to 10%"):
  Split into TWO rules:
  Rule 1: PRESENCE of Measurement >= lower bound (inclusion: patient has the value)
  Rule 2: ABSENCE of Measurement >= upper bound (exclusion: no dangerously high values)

Pattern B — Simple threshold (e.g., "eGFR >= 30"):
  Single rule: PRESENCE of Measurement with value_constraint {{op: "gte", value: 30}}

Pattern C — "No prior X" / "Without X":
  → logic_type: "ABSENCE", appropriate time window

Pattern D — "History of X":
  → logic_type: "PRESENCE", window: {{start: -9999, end: 0}} (all prior history)

Pattern E — Composite OR condition ("≥1 of A, B, C ...", "at least one of", "with or without X",
  "either X or Y", "including X, Y, or Z", or conditional sub-type paths like "A patients OR B patients"):
  CRITICAL: When a protocol says "one or more of", "≥1 of", "with or without", "either...or",
  "including ... or", or lists disease sub-types where any one qualifies the patient,
  you MUST emit a SINGLE rule with `sub_criteria` array and `group_type: "ANY"`.
  DO NOT emit them as separate inclusion_rules (that creates AND logic = impossible to satisfy).
  Example: "Age ≥ 50 with ≥1 of: MI, stroke, CHF, CKD" →
  One inclusion_rule with sub_criteria containing MI, stroke, CHF, CKD, group_type="ANY"
  Example: "ACS with or without ST-segment elevation" →
  One inclusion_rule with sub_criteria containing STEMI, NSTEMI, UA, group_type="ANY"
  Example: "STEMI patients requiring PCI OR NSTE-ACS patients" →
  One inclusion_rule with sub_criteria containing STEMI and NSTE-ACS, group_type="ANY"

Pattern F — Conditional criterion ("If [subgroup] → [requirement]"):
  CRITICAL: When a criterion only applies to a specific patient subgroup
  (e.g., "females of childbearing potential must have negative pregnancy test",
  "women must use effective contraception", "if on anticoagulants must discontinue",
  "diabetic patients must have HbA1c < X%"), set `conditional: true` on that criterion.
  DO NOT emit conditional criteria as universal inclusion rules — they cause all patients
  without the measurement/condition to be incorrectly excluded.
  Conditional triggers: "females must", "women of childbearing", "patients with X must also",
  "if the patient has", "for patients who", "in case of", "must use contraception".

Output your response as valid JSON matching the ARTEMIS IR schema."""

NCT_DECOMPOSITION_PROMPT = """Convert this clinical trial protocol into the ARTEMIS IR format.

**Trial Title**: {title}
**Conditions**: {conditions}
**Interventions**: {interventions}
**Primary Outcomes**: {outcomes}

**Inclusion Criteria**:
{inclusion}

**Exclusion Criteria**:
{exclusion}

**Output JSON Schema**:
```json
{{
  "target": {{
    "primary_criteria": {{
      "domain": "Drug",
      "entity_text": "<primary intervention>",
      "limit": "First"
    }},
    "inclusion_rules": [
      {{
        "name": "<rule name>",
        "domain": "<Condition|Drug|Measurement|Procedure|Observation|Demographics>",
        "entity_text": "<clinical term>",
        "logic_type": "PRESENCE",
        "window": {{"start": -365, "end": 0}},
        "value_constraint": {{"op": "gte", "value": 7.0, "unit_text": "%"}}
      }},
      {{
        "name": "<composite OR rule name>",
        "domain": "Condition",
        "entity_text": null,
        "logic_type": "PRESENCE",
        "group_type": "ANY",
        "sub_criteria": [
          {{"name": "sub A", "domain": "Condition", "entity_text": "<term A>", "logic_type": "PRESENCE"}},
          {{"name": "sub B", "domain": "Condition", "entity_text": "<term B>", "logic_type": "PRESENCE"}}
        ]
      }}
    ],
    "exclusion_rules": [
      {{
        "name": "<rule name>",
        "domain": "<domain>",
        "entity_text": "<clinical term>",
        "logic_type": "ABSENCE",
        "window": {{"start": -9999, "end": 0}}
      }}
    ]
  }},
  "comparator": {{
    "primary_criteria": {{
      "domain": "Drug",
      "entity_text": "<comparator intervention>",
      "limit": "First"
    }},
    "inclusion_rules": [],
    "exclusion_rules": []
  }},
  "outcome": {{
    "name": "<primary outcome name>",
    "domain": "<domain>",
    "entity_text": "<outcome clinical term>",
    "time_at_risk": {{"start": 0, "end": 365}}
  }}
}}
```

**One-shot Example** — "HbA1c 7% to 10%" criteria:
```json
[
  {{
    "name": "HbA1c lower bound (>=7%)",
    "domain": "Measurement",
    "entity_text": "Hemoglobin A1c/Hemoglobin.total in Blood",
    "logic_type": "PRESENCE",
    "value_constraint": {{"op": "gte", "value": 7.0, "unit_text": "%"}},
    "window": {{"start": -180, "end": 0}}
  }},
  {{
    "name": "HbA1c upper bound (no >=10%)",
    "domain": "Measurement",
    "entity_text": "Hemoglobin A1c/Hemoglobin.total in Blood",
    "logic_type": "ABSENCE",
    "value_constraint": {{"op": "gte", "value": 10.0, "unit_text": "%"}},
    "window": {{"start": -180, "end": 0}}
  }}
]
```

Important Rules:
1. Map each inclusion criterion to an inclusion_rule on the TARGET cohort.
2. Map each exclusion criterion to an exclusion_rule on the TARGET cohort.
   → CRITICAL: ALL exclusion_rules MUST have logic_type: "ABSENCE" (never "PRESENCE").
     This includes rules like "No T1DM", "No prior transplant", "No renal dialysis" etc.
3. COMPLETENESS IS MANDATORY: You MUST capture EVERY SINGLE criterion listed above.
   Do NOT omit or summarize any criteria. Each distinct medical concept must be represented.
   EXCEPTION — Pattern E override: When multiple criteria represent alternative qualification paths
   (any one of them qualifies the patient, e.g., "MI OR stroke OR revascularization OR CHF"),
   they MUST be grouped into a SINGLE rule with sub_criteria and group_type="ANY" (see Rule 12).
   Only truly independent AND requirements (e.g., "must have T2DM" AND "must have HbA1c>=7%")
   should be separate top-level rules. If in doubt whether criteria are OR or AND, look for:
   - Bullet lists under a single heading → OR (sub_criteria)
   - Separate numbered criteria → AND (separate rules)
   - "≥1 of", "at least one", "or", "with or without" → OR (sub_criteria)
4. The comparator cohort shares the same inclusion/exclusion rules (they differ only by primary_criteria)
5. For "No prior X" or "without X", use `logic_type: "ABSENCE"`
6. For measurements with thresholds (e.g., "creatinine > 354 mmol/l"), include `value_constraint`
7. Use negative days for "prior to" time windows (e.g., -365 for 1 year before)
8. If a criterion is purely administrative (e.g., "informed consent"), skip it
9. For ALL Measurement criteria, you MUST include `value_constraint`.
   If the criterion specifies a range (e.g., "7-10%"), split into two rules:
   lower bound with PRESENCE + upper bound with ABSENCE.
10. `window` is MANDATORY on every rule. Never omit it.
    If the protocol specifies an explicit time frame (e.g., "within 3 months prior to screening"), convert to days ({{start: -90, end: 0}}).
    If no time frame is stated, use domain defaults: Condition/Procedure → {{start: -9999, end: 0}}, Drug → {{start: -365, end: 0}}, Measurement → {{start: -180, end: 0}}.
11. Drug rules must preserve the specific drug identity, but normalize it to the ingredient/generic name.
    If a criterion lists specific drugs (e.g., "ticagrelor", "clopidogrel"), keep those exact drugs,
    but strip strength, route, and formulation text. Use "ticagrelor", not
    "ticagrelor 90 mg oral tablet". Do NOT generalize to broad classes unless the protocol
    itself specifies a drug class.
12. COMPOSITE OR GROUPING (Pattern E): When a protocol criterion lists multiple sub-conditions
    joined by OR — including "≥1 of: ...", "at least one of", "with or without X",
    "either X or Y", "including X, Y, or Z", or conditional sub-type paths
    (e.g., "STEMI patients requiring PCI OR NSTE-ACS patients") —
    you MUST emit a SINGLE rule with `group_type: "ANY"` and `sub_criteria` array.
    Each sub-condition becomes a separate entry in `sub_criteria`.
    The parent rule's `entity_text` should be null (the sub_criteria have their own entity_text).
    DO NOT emit them as separate top-level inclusion_rules — that creates implicit AND logic
    requiring ALL conditions simultaneously, which eliminates all patients.
    This applies to BOTH inclusion and exclusion contexts.
    Example: "ACS with or without ST-segment elevation" → single rule, sub_criteria=[STEMI, NSTEMI, UA], group_type="ANY"
    Example: "STEMI patients OR NSTE-ACS patients" → single rule, sub_criteria=[STEMI, NSTE-ACS], group_type="ANY"
13. CONDITIONAL CRITERIA (Pattern F): When a criterion says "[subgroup] must [requirement]"
    or "if [condition] then [requirement]", set `conditional: true`. Examples:
    "females of childbearing potential must have negative pregnancy test" → conditional: true
    "women must use effective contraception" → conditional: true
    "patients on warfarin must discontinue" → conditional: true
    DO NOT include these as universal InclusionRules (causes all patients without
    the measurement to be incorrectly excluded).

Return ONLY the JSON, no explanation.\"\"\""""
