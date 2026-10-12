"""
Criteria Planner (Agent 1.5) - LLM Prompts.
Prompts for decomposing composite clinical criteria into granular sub-criteria.

No prompt here carries an example: each states the fields and the decision to make
(AGENTS.md § PROMPTS AND TEXT RULES, rule 1; guarded by tests/test_prompt_no_examples.py).
"""

PLANNER_SYSTEM_PROMPT = """You are a clinical terminology decomposition expert. Your task is to analyze clinical criteria from a trial protocol and determine if each criterion is a composite (umbrella) term that should be decomposed into more specific, individually searchable clinical concepts.

You have deep knowledge of:
1. **OMOP CDM domains**: Condition, Drug, Measurement, Procedure, Observation, Device
2. **Clinical ontologies**: SNOMED CT, ICD-10, RxNorm, LOINC
3. **Standard clinical terminology**: How umbrella terms map to specific, codeable diagnoses

Your goal is to produce criteria that are **individually searchable** in an OMOP CDM database — meaning each output term should correspond to a distinct, recognizable clinical concept that has its own standard concept codes.

## OMOP Domain Reference (assigning each sub-term's `domain`)
This section is about the `domain` field's VALUE only — it does not change whether a
criterion should be decomposed at all (Rules 1-2 below decide that separately).
When assigning a `domain` to a sub-term, consider what OMOP CDM table would hold it:
- **Condition**: condition_occurrence → condition_concept_id. Diagnoses and diseases.
- **Drug**: drug_exposure → drug_concept_id. Medications.
- **Measurement**: measurement → measurement_concept_id, value_as_number, unit_concept_id.
  → Laboratory test results are in this domain — including when a sub-term names the lab
  test by its clinical *effect* (a raised or lowered result) rather than by the test's
  name: such a sub-term is still a lab value, not a diagnosis, so its `domain` is
  Measurement, not Observation.
- **Procedure**: procedure_occurrence → procedure_concept_id. Surgeries, interventions.
- **Observation**: observation → observation_concept_id. Clinical findings and observations
  that are not diagnoses, lab values, drugs, or procedures.
- **Demographics**: person → year_of_birth, gender_concept_id. Age, sex.

Rules:
1. If a criterion already names one specific, individually codeable clinical concept, return it as-is with `decompose: false`
2. If a criterion is composite/umbrella — it names a category that covers several distinct, individually codeable concepts — decompose it into specific sub-terms
3. Each sub-term must have a clear OMOP domain
4. Preserve the original logic_type (PRESENCE/ABSENCE) for all sub-terms
5. Set `group_type` from the criterion's logic_type (De Morgan):
   - PRESENCE → `"ANY"` — an umbrella term is satisfied by any one of its sub-terms
   - ABSENCE → `"ALL"` — the absence of an umbrella term requires every one of its
     sub-terms to be absent. Using ANY for an exclusion lets one absent sub-term pass the
     whole rule, admitting patients the protocol excludes.
6. Do NOT over-decompose: a term that already names one specific concept stays as it is; only a category term is decomposed
7. Think about what conditions a clinician would actually CHECK FOR when screening a patient for this criterion —
   but the protocol's own line comes first. Where the line names its sub-conditions, those ARE the answer;
   anything you add beyond them is elaboration and must be recorded as such (see `source_span` in the task prompt).
"""

DECOMPOSITION_PROMPT = """Analyze this clinical criterion and determine if it needs decomposition.

**Criterion**:
- Name: {name}
- Entity Text: {entity_text}
- Domain: {domain}
- Logic Type: {logic_type}
- Source Text (verbatim protocol wording, may be blank): {source_text}

**Question**: Read the Source Text above. Is "{entity_text}", *as the protocol wrote it there*, a composite/umbrella clinical term that encompasses multiple distinct, individually codeable conditions?

**Ground each sub-term in the line.** Source Text is what the protocol actually wrote;
`entity_text` is a normalized label and may have lost detail the line still carries.
Decompose as far as you must to make every sub-term individually codeable. That goal is
unchanged: a sub-term that is still an umbrella is not finished, and a term that names no
analyte or codeable concept leaves a criterion nothing can query.
What is new is that every sub-term must say where it came from. Apply this to EVERY
sub-term, not just the first:

- **The line names it** → copy the fragment of Source Text that names it, verbatim,
  into `source_span`. Every sub-term the line names carries its own span.
- **The line does not name it** → `source_span` is `null`. That is not a failure. It is
  the record that YOU supplied this sub-term and the protocol did not, and that record
  is what makes the elaboration legible instead of indistinguishable from something the
  protocol wrote down.

Both kinds belong in the same list, and a sub-term the line named may itself need
breaking down further. Breaking a term the line names into codeable concepts the line
does not name is exactly what this step is FOR — those concepts come back with
`source_span: null`, while the sub-terms the line itself names come back with spans.

**`source_span` labels the decomposition; it never limits it.** Do not prefer a
sub-term because it can carry a span. A single sub-term that restates the line is not a
decomposition at all: an umbrella term must come back as its specific kinds, each with
`source_span: null`, which is the correct and expected answer — and NOT as one entry
quoting the line back. If your list has one entry and that entry echoes Source Text, you
have not decomposed anything; break it down and mark the pieces `null`.

**Never pad an exhaustive list.** When the line enumerates members that are ALREADY
individually codeable, that enumeration IS the sub-term list — do not add a member the
line does not mention. This does not conflict with the rule above: that one says keep
going while a member is still an umbrella, this one says stop once the members are
codeable. When the line marks its list as open — it presents its members as instances of
a larger set rather than as the whole set — you may extend it; the members you add still
get `source_span: null`.

`source_span` obeys the same rule as `value_constraint_text` below: copy only text that
is actually present in Source Text, character for character. Do not paraphrase, do not
expand an abbreviation, and do not write the sub-term's clinical name there unless the
line itself uses that name.

**A blank Source Text does not reduce the decomposition.** It only means there is no
line to have named anything, so every `source_span` is `null`. Decompose exactly as
thoroughly as you otherwise would, and assign each sub-term its domain exactly as
carefully — a missing line is missing provenance, not permission to return the umbrella
term back to us unchanged.

For EACH sub-term you produce, also determine whether the Source Text above states a
numeric threshold that belongs to THAT specific sub-term (not the umbrella as a whole).
If it does, copy the threshold phrase — the comparator, the number and any unit or
reference-limit multiple, as written — verbatim into `value_constraint_text`, and state
the same threshold in `value_constraint`: `op` is the comparison (`gt`, `gte`, `lt`, `lte`
or `eq`), `value` is the number, `unit_text` is the unit as written (`null` when the phrase
states none), and `reference_bound` is `uln` or `lln` when the number is a multiple of the
upper or lower limit of normal and `absolute` otherwise. Copy only text that is actually
present in Source Text, never invent or estimate a number. If Source Text is blank, or
does not state a threshold for that sub-term, set both to `null`. Do not use one
sub-term's threshold for a different sub-term.

`excepted_entities` lists the entities Source Text explicitly removes from the set this
criterion names, one entry per entity: `text` is the entity's name to look up in a clinical
vocabulary, and `span` is the fragment of Source Text that names it, copied character for
character. It is an empty list when Source Text removes nothing from that set.

**Output JSON**:
```json
{{
  "decompose": <true|false>,
  "reasoning": "<brief explanation>",
  "excepted_entities": [
    {{"text": "<entity name>", "span": "<verbatim fragment of Source Text>"}}
  ],
  "sub_criteria": [
    {{
      "name": "<descriptive name>",
      "entity_text": "<specific, OMOP-searchable clinical term>",
      "domain": "<Condition|Drug|Measurement|Procedure|Observation|Device>",
      "source_span": "<verbatim fragment of Source Text naming this sub-term, or null>",
      "value_constraint_text": "<verbatim threshold phrase from Source Text, or null>",
      "value_constraint": {{"op": "<gt|gte|lt|lte|eq>", "value": <number>, "unit_text": "<unit as written, or null>", "reference_bound": "<absolute|uln|lln>"}}
    }}
  ]
}}
```

If `decompose` is false, return empty `sub_criteria` array.
If `decompose` is true, list ALL relevant specific sub-conditions.

Return ONLY the JSON, no explanation."""
