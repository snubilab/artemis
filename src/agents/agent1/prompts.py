"""
Agent 1 (Logic Decomposer) - Prompts for NLU Processing.
Converts natural language clinical queries to ARTEMIS IR format.

No prompt here carries an example: no protocol line, real or invented, no filled-in
JSON, no input->output pair, no word list to recognise, no measurement history. Each
states the fields and the decision to make (AGENTS.md § PROMPTS AND TEXT RULES, rule 1;
guarded by tests/test_prompt_no_examples.py).
"""

from src.utils.circe_lint import render_default_window_prompt_line

# The per-domain window defaults these prompts instruct the model to apply, rendered
# from `circe_lint.DEFAULT_WINDOW_START_DAYS_BY_DOMAIN` -- the same table the emitter
# reads when the model omits `window` anyway (10% of the 557 criteria in the cold-6
# store). Retyping the numbers here is the defect: the emitter used to carry a flat
# unnamed 365 for every domain, so the prompt promised four values and the file shipped
# one, with nothing comparing them. Both renderings below are byte-identical to the text
# these prompts already carried, because `NCT_SYSTEM_PROMPT` and the rendered
# `NCT_DECOMPOSITION_PROMPT` are hashed into the Agent 1 IR cache key (`parser.py`):
# rewording them re-extracts every cached trial, and the defect was never the prose.
_DEFAULT_WINDOWS_BY_DOMAIN = render_default_window_prompt_line(
    [["Condition"], ["Drug"], ["Measurement"], ["Procedure"]]
)
#: Same table, the shape the two ``str.format``-consumed prompts state it in: Condition
#: and Procedure collapsed (the renderer refuses to collapse them if their defaults ever
#: diverge), braces doubled so ``.format`` passes them through.
_DEFAULT_WINDOWS_BY_DOMAIN_FORMAT_SAFE = render_default_window_prompt_line(
    [["Condition", "Procedure"], ["Drug"], ["Measurement"]], escape_braces=True
)


SYSTEM_PROMPT = """You are a clinical trial protocol parser. Your task is to convert natural language clinical questions into a structured Internal Representation (IR) format.

You must extract:
1. **Target Cohort**: Patients receiving the treatment of interest
2. **Comparator Cohort**: Patients receiving the comparison treatment (or placebo)
3. **Outcome**: The clinical endpoint being measured
4. **Inclusion/Exclusion Criteria**: Additional conditions for cohort membership

For each criterion, identify:
- **domain**: Condition, Drug, Measurement, Procedure, Observation, or Demographics
- **entity_text**: The clinical term the criterion is about
- **logic_type**: PRESENCE (patient has/uses) or ABSENCE (patient does NOT have/use)
- **window**: Time window relative to index date (in days). MANDATORY for every criterion.
  If the protocol states an explicit temporal constraint, convert it to days.
  Otherwise apply domain defaults: """ + _DEFAULT_WINDOWS_BY_DOMAIN + """.
- **source_text**: The criterion line as the protocol writes it, copied verbatim (MANDATORY).
  Keep every threshold, unit, and comparator exactly as written — do not paraphrase,
  expand abbreviations, or convert units. A later stage locates the threshold by
  substring match against this string, so a tidied-up copy loses the threshold
  silently and the criterion reaches the cohort with no value filter at all.
  If one protocol line becomes several rules, every one of them repeats that whole line.
- **value_constraint**: OPTIONAL, and never invented. Emit it when the protocol states a
  threshold outright; leave it out when you are not copying a number the text actually
  gives. `source_text` is the record of what the protocol said, so nothing is lost by
  omitting it.
  When the threshold is a multiple of a reference range rather than the measured value,
  put the reference marker in `unit_text` verbatim — `"x ULN"` or `"x LLN"` — and never
  replace it with the lab's real unit. Written in the lab's own unit, the multiplier reads
  as an absolute value far below the normal range, so as an exclusion it removes nearly
  every patient who ever had that test.

## OMOP Domain Reference
- **Condition**: condition_occurrence → diagnoses
- **Drug**: drug_exposure → medications
- **Measurement**: measurement → value_as_number, unit_concept_id.
- **Procedure**: procedure_occurrence → surgeries, interventions
- **Demographics**: person → age, sex

## Drug Entity Normalization
- For Drug criteria, `entity_text` must be the active ingredient/generic drug name.
- Strip dose, strength, route, and formulation details, leaving the ingredient name.
- Do NOT emit product/formulation-level strings when an ingredient-level name exists.
- DrugEra-based cohorts are matched at the RxNorm ingredient level, so ingredient names are required.

## Clinical Criteria Patterns
Pattern A — A measured value bounded on both sides (a range):
  Split into TWO rules: PRESENCE >= lower bound + ABSENCE >= upper bound.
  Both rules carry the same verbatim `source_text`.
Pattern B — A measured value bounded on one side:
  Single PRESENCE rule with value_constraint
Pattern C — The criterion states the patient has NOT had, does not have, or is not using something:
  → logic_type: "ABSENCE"
Pattern D — Any past occurrence, with no time limit stated:
  → logic_type: "PRESENCE", window covering all prior history (start -9999 days, end 0)

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
        "source_text": "<the protocol's own line, verbatim>",
        "logic_type": "<PRESENCE|ABSENCE>",
        "window": {{"start": <days relative to index>, "end": <days relative to index>}},
        "value_constraint": {{"op": "<gt|gte|lt|lte|eq>", "value": <number>, "unit_text": "<unit as written>"}}
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
    "time_at_risk": {{"start": <days after index>, "end": <days after index>}}
  }}
}}
```

Important Rules:
1. When the question states the patient has NOT had or is not using something, use `logic_type: "ABSENCE"`
2. `source_text` is MANDATORY on every rule and must be the protocol's own line, verbatim.
   Never put the cleaned-up `name` or `entity_text` there. A later stage finds the
   threshold by substring match against `source_text`, and a paraphrase drops the
   threshold without any error — the criterion then matches far more patients than
   the protocol allows.
3. Use negative days for time windows before the index date.
4. Always include the outcome's time_at_risk window, in days after index: the follow-up the
   question states for the outcome, or start 0 and end 365 when it states none.
5. `value_constraint` is OPTIONAL — copy a threshold the protocol states, never invent one.
   For a multiple of a reference range, keep the marker in `unit_text` as `"x ULN"` /
   `"x LLN"`; substituting the lab's real unit turns the multiplier into an absolute value
   and the rule stops meaning anything.
   If the criterion specifies a range, split into two rules:
   lower bound with PRESENCE + upper bound with ABSENCE, both carrying the same verbatim
   `source_text`.
6. `window` is MANDATORY on every rule. Never omit it.
   If the protocol specifies an explicit time frame, convert to days. Otherwise use domain defaults:
   """ + _DEFAULT_WINDOWS_BY_DOMAIN_FORMAT_SAFE + """.
7. PURE CLINICAL CONCEPTS: The `name` field must contain ONLY the pure clinical concept — the medication class, condition, or procedure itself. Strictly strip away all study-specific grammatical glue words, prefixes, and contextual statements.

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
- **entity_text**: The clinical term the criterion is about. MANDATORY on
  every criterion that has no `sub_criteria`; null ONLY on a parent row that has them.
  It is the ONLY text the concept mapper is ever given, so a leaf that omits it is mapped
  on its `name` instead -- and a `name` is a phrase written for a human, which resolves
  to whatever domain's concepts happen to share its words.
- **logic_type**: PRESENCE (patient has/uses) or ABSENCE (patient does NOT have/use)
- **window**: Time window relative to index date (in days). MANDATORY for every criterion.
  If the protocol states an explicit temporal constraint, convert it to days.
  Otherwise apply domain defaults: """ + _DEFAULT_WINDOWS_BY_DOMAIN + """.
- **source_text**: The numbered criterion line below, copied verbatim (MANDATORY).
  Keep every threshold, unit, and comparator exactly as written — do not paraphrase,
  expand abbreviations, or convert units, and drop only the line's leading list number. A
  later stage locates the threshold by substring match against this string, so a
  tidied-up copy loses the threshold silently and the criterion reaches the cohort with
  no value filter at all. If one criterion line becomes several rules (a range, or a line
  naming several analytes at once), every one of them repeats that whole line.
- **value_constraint**: OPTIONAL, and never invented. Emit it when the protocol states a
  threshold outright; leave it out when you are not copying a number the text actually
  gives. `source_text` is the record of what the protocol said, so nothing is lost by
  omitting it.
  CRITICAL — a `value_constraint` bounds a MEASURED VALUE: the number a lab or a clinical
  observation recorded for this patient, which OMOP keeps in `measurement.value_as_number`
  or `observation.value_as_number`. Only Measurement and Observation criteria have such a
  column at all. The protocol stating a threshold outright is therefore NOT the test —
  protocols state many numbers that are not measured values, and each kind below is a
  threshold you must NOT write as a `value_constraint`:
    · a DRUG DOSE — an amount of a drug given or permitted. `drug_exposure` has no
      dose-strength column Circe can filter; the one value it reads is Quantity, which is
      units DISPENSED, not strength, so a dose bound has no correct home there at all.
      Emit the drug, drop the number.
    · a DISEASE DURATION — how long a condition has been present. `condition_occurrence`
      has no value column whatsoever. A duration is a temporal fact about when the
      diagnosis started; `window` and `source_text` carry it.
    · an ANATOMIC or IMAGING PERCENTAGE on a Procedure or Condition criterion — the extent
      of a lesion or of tissue involvement. That number describes the anatomy, not a
      recorded measurement, and `procedure_occurrence` reads no value either.
    · a COUNT of risk factors, conditions or prior episodes. That is an occurrence count
      and belongs to the criterion's structure, never to `value_constraint`.
    · an AGE. Demographics carries age from `year_of_birth`; a Demographics criterion
      never takes a `value_constraint`.
  The test: if you cannot name the lab or observation that would produce this number for
  one patient on one day, it is not a `value_constraint`.
  Getting this wrong is silent and total. Circe DROPS a value condition written on a table
  that cannot read it — no error, no warning — and the rule then matches EVERY occurrence
  of its concept set while reading in the JSON as though it were filtered. Downstream
  REFUSES a criterion carrying a bound its own table cannot read, so the whole criterion
  is dropped rather than shipped vacuous: writing the number where it does not belong
  costs the criterion, while omitting it keeps the criterion.
  When the threshold is a multiple of a reference range rather than the measured value,
  put the reference marker in `unit_text` verbatim — `"x ULN"` or `"x LLN"` — and never
  replace it with the lab's real unit. Written in the lab's own unit, the multiplier reads
  as an absolute value far below the normal range, so as an exclusion it removes nearly
  every patient who ever had that test.

## OMOP Domain Reference (Criteria2Query-informed)
When choosing a domain and structuring rules, consider the OMOP CDM tables:
- **Condition**: condition_occurrence → condition_concept_id. Use for diagnoses.
- **Drug**: drug_exposure → drug_concept_id. Use for medications.
- **Measurement**: measurement → measurement_concept_id, value_as_number, unit_concept_id.
  → Laboratory test results are in this domain.
- **Procedure**: procedure_occurrence → procedure_concept_id. Use for surgeries, interventions.
- **Observation**: observation → observation_concept_id. Use for clinical observations.
- **Demographics**: person → year_of_birth, gender_concept_id. Use for age, sex criteria.

## When the description and the entity disagree, the description decides the domain
`entity_text` is the noun you look up in the vocabulary; the criterion's name/description
is what the protocol actually asserts. When the two point at different OMOP domains, the
DESCRIPTION decides `domain` — it is the whole sentence, and `entity_text` is only one word
lifted out of it. Then make `entity_text` name something that really lives in that domain:
a rule whose concept set holds none of its own domain's concepts matches nothing, and is
refused downstream, so the criterion is lost rather than merely weakened.
Decide the domain from what the description asserts about the patient:
  · taking, receiving, starting, stopping or changing a treatment ⇒ Drug. A statement about
    whether or how a patient takes a drug is a Drug criterion, never a Measurement of that
    drug.
  · having or having had a diagnosis, disorder or reaction ⇒ Condition. When the sentence
    asserts a clinical state and names a drug or other agent only as what that state is
    about, the entity is the state, in the state's domain, with the agent folded into
    `entity_text` as its qualifier — the agent is never looked up on its own.
  · a quantity measured on the patient ⇒ Measurement.

## Drug Entity Normalization
- For Drug criteria, `entity_text` must be the active ingredient/generic drug name.
- Strip dose, strength, route, and formulation details, leaving the ingredient name.
- Do NOT emit product/formulation-level drug strings when an ingredient-level name exists.
- DrugEra-based cohorts are matched at the RxNorm ingredient level, so ingredient names are required.

## Clinical Criteria Patterns
Pattern A — A measured value bounded on both sides (a range):
  Split into TWO rules, both carrying the same verbatim `source_text`:
  Rule 1: PRESENCE of Measurement >= lower bound (inclusion: patient has the value)
  Rule 2: ABSENCE of Measurement >= upper bound (exclusion: no dangerously high values)

Pattern B — A measured value bounded on one side:
  Single rule: PRESENCE of Measurement with a value_constraint carrying that bound.

Pattern C — The criterion states the patient has NOT had, does not have, or is not using something:
  → logic_type: "ABSENCE", appropriate time window
  The negation may be a separate word or may be fused to the drug as a modifier; either
  way the patient has NOT had the drug, and the rule takes logic_type "ABSENCE".
  CRITICAL — the negation belongs to `logic_type`, never to `entity_text`. `entity_text` is
  the string handed to the vocabulary, so it names the DRUG ALONE — the ingredient the line
  implies or the class it names. A seed carrying the negation is not a drug, so its concept
  set holds no Drug concept and the DrugExposure rule matches no row at all: the criterion
  is refused downstream and the protocol's requirement is lost entirely, not merely
  weakened.
  When the line offers a CHOICE between never having had a drug and having had it,
  Pattern E governs and this rule applies INSIDE it: one ANY group whose naive member is
  an ABSENCE of the drug class and whose pre-treated member is a PRESENCE of the drugs the
  line actually names.

Pattern D — Any past occurrence, with no time limit stated:
  → logic_type: "PRESENCE", window covering all prior history (start -9999 days, end 0)

Pattern E — Composite OR condition: the criterion lists alternatives, any one of which
  qualifies the patient, including disease sub-types that each qualify on their own:
  CRITICAL: When a protocol states such alternatives, you MUST emit a SINGLE rule with
  `sub_criteria` array and `group_type: "ANY"`.
  DO NOT emit them as separate inclusion_rules (that creates AND logic = impossible to satisfy).
  This applies to Measurement lists too. A lab criterion naming several analytes is one
  ANY group with one sub_criterion PER ANALYTE, each carrying its own value_constraint — a
  threshold shared by two analytes is written on both. Count the sub_criteria from the
  analytes the line names, not from the thresholds it states.
  CRITICAL — the GROUP LABEL never carries the `value_constraint`. When a criterion has
  `sub_criteria`, the parent row is a heading: it maps to no concept set of its own and
  emits no rule, so a threshold written there goes NOWHERE. Write the bound out once per
  member it can honestly measure, even when that repeats the same number several times.
  A member measured in a DIFFERENT UNIT from the threshold does not belong in that group —
  give it its own criterion with its own bound in its own unit, or leave it out. When the
  protocol names exactly one analyte, Pattern H applies and the right answer is ONE flat
  Measurement criterion carrying the bound — no group at all.
  The mechanical check before you emit a group: every sub_criterion either carries its own
  `value_constraint` in a unit that criterion is actually reported in, or the group carries
  no threshold anywhere. A number on the parent and nothing on the members is always wrong.

Pattern F — Conditional criterion: a requirement that applies only to a subgroup of patients:
  CRITICAL: When a criterion's requirement applies only to the patients in a subgroup the
  line names, and not to every patient, set `conditional: true` on that criterion.
  DO NOT emit conditional criteria as universal inclusion rules — they cause all patients
  without the measurement/condition to be incorrectly excluded.

Pattern G — Region/subgroup-conditional VALUE (the requirement applies to everyone, but the
  NUMBER differs by an explicit subgroup the line names). Unlike Pattern F (a requirement
  that only some patients face at all), here EVERY patient faces the requirement — only the
  threshold value changes for the named subgroup.
  CRITICAL: emit ONE group with `group_type: "ANY"` — NOT "ALL". That the requirement is
  universal describes who faces it, not how the variants combine: the variants are
  mutually exclusive alternatives (a patient is subject to the general value OR the named
  subgroup's value, never both), so ANY/OR is what applying whichever variant matches the
  patient means. `group_type: "ALL"` would force every patient to satisfy every variant
  simultaneously, including the strictest one — a different and stricter requirement than
  anything the protocol actually states. Emit this as a SINGLE JSON rule object carrying a
  `sub_criteria` array (one sub_criterion per subgroup variant) — never as two or more
  separate top-level rules; standalone rules are AND-combined downstream and produce the
  same wrong strictest-variant-for-everyone result that a mistaken `group_type: "ALL"`
  would. Dropping the subgroup-specific value because there is no single canonical number
  is the same silent-loss failure as dropping a shared threshold in Pattern E — the general
  case does not stand in for the subgroup case.
  Each variant is one sub_criterion carrying its own value and a name stating which
  subgroup it is for, and every variant carries the full original sentence as source_text
  (they share one line, same as Pattern E's shared-threshold rule 6).

Pattern H — One sentence restating ONE entity (the parenthetical scopes, it does not vary):
  A criterion whose alternatives are near-synonyms or facets of the SAME clinical entity
  cluster is ONE criterion, however long the sentence and however many ways it restates the
  same thing. Emit it flat — one rule, no sub_criteria — and emit it exactly ONCE. The rule
  is a count on the protocol line, not a ban on one way of naming a copy: one line
  describing one cluster yields one rule, whatever a second rule would be called. A
  variant-looking suffix, a role tag, a reworded name that foregrounds a facet the first
  name left out, and a byte-identical repeat are all the same violation.
  CRITICAL — this is NOT Pattern G. Pattern G needs a differing NUMBER for a named
  subgroup. A parenthetical that states no second threshold DEFINES the population the
  whole criterion applies to. A scoping parenthetical read as a subgroup variant produces
  copies of one criterion, each mapped on its own paraphrased name, and the cohort is then
  filtered on the UNION of their divergent concept sets — looser and less accurate at the
  same time.
  CRITICAL — this is NOT Pattern E either. Pattern E needs DISTINCT entities, each of which
  earns its own concept set. The mechanical test between them: sub-conditions that each carry
  their OWN value_constraint bound to a different named thing are distinct and keep one
  concept set each; alternatives that carry NO value_constraint at all and describe the same
  population are one cluster and collapse to a single flat criterion.
  A line naming several distinct analytes, each carrying its own value_constraint, is
  governed by Pattern E and Pattern H does not touch it — collapsing such a line is the
  opposite failure and is just as wrong.

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
        "source_text": "<the criterion line above, verbatim>",
        "logic_type": "<PRESENCE|ABSENCE>",
        "window": {{"start": <days relative to index>, "end": <days relative to index>}},
        "value_constraint": {{"op": "<gt|gte|lt|lte|eq>", "value": <number>, "unit_text": "<unit as written, or x ULN / x LLN>"}}
      }},
      {{
        "name": "<composite OR rule name>",
        "domain": "<domain>",
        "entity_text": null,
        "source_text": "<the criterion line above, verbatim>",
        "logic_type": "<PRESENCE|ABSENCE>",
        "group_type": "ANY",
        "sub_criteria": [
          {{"name": "<sub-criterion name>", "domain": "<domain>", "entity_text": "<clinical term>", "source_text": "<same line, verbatim>", "logic_type": "<PRESENCE|ABSENCE>"}},
          ...
        ]
      }}
    ],
    "exclusion_rules": [
      {{
        "name": "<rule name>",
        "domain": "<domain>",
        "entity_text": "<clinical term>",
        "source_text": "<the criterion line above, verbatim>",
        "logic_type": "ABSENCE",
        "window": {{"start": <days relative to index>, "end": <days relative to index>}}
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
    "time_at_risk": {{"start": <days after index>, "end": <days after index>}}
  }}
}}
```

**Shared source_text** — every rule and sub_criterion produced from one criterion line
carries that whole line as `source_text`, byte-identical across all of them. Never the
analyte's own name, never a shortened or tidied copy. Do not paraphrase, shorten, or
replace it with the clinical term even when the term reads as more natural — a later
deterministic stage finds each threshold by searching for it as a substring inside
`source_text`. A label has nothing to search inside, so `value_constraint` is silently
discarded downstream, even when you set it correctly.

Important Rules:
1. Map each inclusion criterion to an inclusion_rule on the TARGET cohort.
2. Map each exclusion criterion to an exclusion_rule on the TARGET cohort.
   → CRITICAL: ALL exclusion_rules MUST have logic_type: "ABSENCE" (never "PRESENCE"),
     however the exclusion criterion is worded.
3. COMPLETENESS IS MANDATORY: You MUST capture EVERY SINGLE criterion listed above.
   Do NOT omit or summarize any criteria. Each distinct medical concept must be represented.
   EXCEPTION — Pattern H override: the requirement that each distinct medical concept be
   represented counts CONCEPTS, not the words a line spends on one. When a single criterion
   line names several near-synonyms or facets of ONE clinical cluster, representing it means
   ONE rule naming that cluster. It does NOT mean one rule per phrase in the line, and it
   does NOT license a second rule to pick up a facet the first rule's name happened to leave
   out. The whole line rides on that one rule's `source_text`, so nothing is dropped by not
   restating it. Rule 15 governs; read it before splitting a line.
   EXCEPTION — Pattern E override: When multiple criteria represent alternative
   qualification paths (any one of them qualifies the patient), they MUST be grouped into a
   SINGLE rule with sub_criteria and group_type="ANY" (see Rule 12).
   Only truly independent AND requirements should be separate top-level rules. If in doubt
   whether criteria are OR or AND:
   - Alternatives listed under one heading → OR (sub_criteria)
   - Separately numbered criteria → AND (separate rules)
   - A line that states its items as alternatives → OR (sub_criteria)
4. The comparator cohort shares the same inclusion/exclusion rules (they differ only by primary_criteria)
5. When a criterion states the patient has NOT had or is not using something, use `logic_type: "ABSENCE"`
6. `source_text` is MANDATORY on every rule, including sub_criteria, and must be the
   criterion line above copied verbatim. Never put the cleaned-up `name` or
   `entity_text` there. A later stage finds the threshold by substring match against
   `source_text`, and a paraphrase drops the threshold without any error — the criterion
   then matches far more patients than the protocol allows.
7. Use negative days for time windows before the index date.
8. If a criterion is purely administrative — it states no clinical property of the
   patient — skip it.
9. `value_constraint` is OPTIONAL — copy a threshold the protocol states, never invent one.
   For a multiple of a reference range, keep the marker in `unit_text` as `"x ULN"` /
   `"x LLN"`; substituting the lab's real unit turns the multiplier into an absolute value
   and the rule stops meaning anything.
   If the criterion specifies a range, split into two rules:
   lower bound with PRESENCE + upper bound with ABSENCE.
10. `window` is MANDATORY on every rule. Never omit it.
    If the protocol specifies an explicit time frame, convert it to days.
    If no time frame is stated, use domain defaults: """ + _DEFAULT_WINDOWS_BY_DOMAIN_FORMAT_SAFE + """.
    The outcome's time_at_risk is in days after index: the follow-up the protocol states
    for the primary outcome, or start 0 and end 365 when it states none.
11. Drug rules must preserve the specific drug identity, but normalize it to the ingredient/generic name.
    If a criterion lists specific drugs, keep those exact drugs, but strip strength, route,
    and formulation text. Do NOT generalize to broad classes unless the protocol itself
    specifies a drug class.
12. COMPOSITE OR GROUPING (Pattern E): When a protocol criterion lists multiple
    sub-conditions as alternatives — any one of which qualifies the patient, including
    sub-type paths that each qualify on their own — you MUST emit a SINGLE rule with
    `group_type: "ANY"` and `sub_criteria` array.
    Each sub-condition becomes a separate entry in `sub_criteria`.
    The parent rule's `entity_text` should be null (the sub_criteria have their own entity_text).
    DO NOT emit them as separate top-level inclusion_rules — for PRESENCE sub-conditions that
    creates implicit AND logic requiring ALL of them simultaneously, which eliminates all
    patients.
    This applies to exclusion contexts as well, but the reason above is not why. Separate
    top-level ABSENCE rules AND-combine to absence from every one of them, which is absence
    from their UNION — already what an OR-ed exclusion sentence asks for, so they eliminate
    nobody. Group them for the shape, not to avoid that harm: a downstream stage emits the
    group type that reproduces absence-from-the-union, so an OR-ed exclusion sentence means
    the same thing grouped or flat.
    What grouping does NOT do is merge concept sets — N sub_criteria still map to N concept
    sets — so grouping is never the remedy for one sentence emitted more than once. That is
    rule 15.
13. CONDITIONAL CRITERIA (Pattern F): When a criterion's requirement applies only to a
    subgroup of patients the line names, set `conditional: true`.
    DO NOT include these as universal InclusionRules (causes all patients without
    the measurement to be incorrectly excluded).
14. REGION/SUBGROUP-CONDITIONAL VALUE (Pattern G): When a criterion states a DIFFERENT number
    for a named subgroup while the requirement itself applies to every patient, this is NOT
    Pattern F (nobody is exempt) and it is NOT a single number to pick. Emit ONE group with
    `group_type: "ANY"` (the variants are alternatives a patient satisfies one of, not
    requirements that all apply together — `group_type: "ALL"` would force every patient to
    satisfy the strictest variant, which no protocol states) and a sub_criterion PER VARIANT,
    each carrying its own value_constraint and a name stating which subgroup it is for.
    This MUST be a single JSON rule object with a `sub_criteria` array — do not emit the
    variants as separate top-level inclusion_rules/exclusion_rules entries; those are
    AND-combined downstream and silently force the strictest variant onto every patient,
    the same wrong result a mistaken `group_type: "ALL"` would produce. Keeping only the
    general-population number and dropping the subgroup-specific one is the same silent loss
    covered by rule 6 for a shared threshold — a number already present for the entity does
    not stand in for every number this line states.
15. RESTATED SINGLE ENTITY (Pattern H): When one criterion sentence restates ONE clinical
    entity cluster — its alternatives are near-synonyms or facets of the same thing rather
    than separately mappable entities — emit exactly ONE criterion for it, flat, with NO
    `sub_criteria`.
    COUNT PER PROTOCOL LINE, NOT PER NAME. This is a cardinality rule, not a ban on one way
    of naming a copy. Before you emit a rule, ask which numbered line above it came from. If
    that line describes one cluster and you have already emitted a rule for it, do not emit
    another — and do not resolve the urge to emit another by renaming it. What the second
    rule would be CALLED is irrelevant; all four of these are the same violation, not four
    separate cases to be avoided one at a time:
      - a suffix that reads like a subgroup variant;
      - a suffix that tags the section, role, or domain;
      - no suffix at all, but a reworded name foregrounding a facet the first name omitted;
      - a byte-identical repeat of the rule you already emitted.
    A renamed duplicate is not a second criterion; it is a duplicate with a different name.
    It is mapped on its own paraphrased name to its own divergent concept set, and the cohort
    is filtered on the union, exactly as if you had suffixed it.
    A parenthetical that scopes or defines the population is NOT a Pattern G subgroup
    variant. Pattern G requires a DIFFERING NUMBER for a named subgroup; a parenthetical that
    states no second threshold has no variant to emit.
    The mechanical test against Pattern E: sub-conditions that each carry their OWN
    `value_constraint` bound to a different named entity are DISTINCT and keep one concept set
    each (rule 12 governs them, unchanged); alternatives carrying NO `value_constraint` that
    describe the same population are ONE cluster and collapse to a single flat criterion.
    The single criterion is flat — no sub_criteria, no parenthetical suffix on its name — and
    carries the whole sentence verbatim as source_text.
    A line naming several DISTINCT analytes, each carrying its own value_constraint, is
    governed by rule 12 and this rule does not reach it: collapsing them is the opposite
    failure and is just as wrong.

Return ONLY the JSON, no explanation."""

THRESHOLD_REVIEW_PROMPT = """You are reviewing another model's extraction, not extracting yourself.

Below are numbered protocol criteria lines, followed by the rules a first pass generated
from them. Your only job: find criteria whose sentence states a numeric threshold — a
number the criterion compares a patient value against — where the corresponding generated
rule has NO value_constraint. Ignore criteria that never had a number to begin with.

A criterion counts as a MISS only when:
- the criterion line itself contains a number/comparator/unit, AND
- none of the rules whose source_text or name plausibly traces back to that line carry
  a value_constraint with a numeric value.

Do not flag a rule that correctly has no value_constraint for a criterion that never had
a number. Do not invent a number that is not in the text.

**Criteria** (numbered, as given to the first pass):
{criteria_block}

**Generated rules** (name, source_text, value_constraint — value_constraint is null when missing):
{rules_block}

Output JSON: {{"misses": [{{"criterion_line": <int>, "criterion_text": "<verbatim>", "reason": "<why this looks like a dropped threshold>"}}]}}
Return an empty "misses" list when nothing looks wrong. Output ONLY the JSON."""
