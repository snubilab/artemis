# Prompt examples — what happened to each inventory row (P1)

Companion to `2026-10-12_prompt_examples.{md,json}` (205 rows, artemis `fix/0923-reply` @ ec0cf51).
P1 of `todolist/20261012_095201_remove_examples_and_text_rules.md`. Guard: `tests/test_prompt_no_examples.py`.

Each row is either **deleted** (it only illustrated) or **decision kept as** the abstract sentence that now
carries the decision the example made, quoted from the prompt as it stands after this change. P2 reads this
table to name the criteria whose extraction may move: a "decision kept" row changes the wording the model
sees for that decision; a "deleted" row removes an instance and leaves the rule beside it untouched.

No LLM, re-extraction or rebuild was run for this change. Every edited prompt changes its cache key
(Agent 1 IR cache, critic `_CRITIC_PROMPT_VERSION`, classifier span cache).

## Agent 1 — `src/agents/agent1/prompts.py` (105 rows)

### NCT_SYSTEM_PROMPT (production)

| ID | Class | Outcome |
|---|---|---|
| N1 | CE | deleted |
| N2 | CX | decision kept as: "a `name` is a phrase written for a human, which resolves to whatever domain's concepts happen to share its words" |
| N3 | HP | deleted |
| N4 | CE (IO) | decision kept as: "If the protocol states an explicit temporal constraint, convert it to days." |
| N5 | CE | deleted |
| N6 | CX | decision kept as: "a DRUG DOSE — an amount of a drug given or permitted. … Emit the drug, drop the number." |
| N7 | CX | decision kept as: "a DISEASE DURATION — how long a condition has been present. … `window` and `source_text` carry it." |
| N8 | CX | decision kept as: "an ANATOMIC or IMAGING PERCENTAGE on a Procedure or Condition criterion — the extent of a lesion or of tissue involvement." |
| N9 | CX | decision kept as: "a COUNT of risk factors, conditions or prior episodes. That is an occurrence count and belongs to the criterion's structure, never to `value_constraint`." |
| N10 | CX | decision kept as: "an AGE. Demographics carries age from `year_of_birth`; a Demographics criterion never takes a `value_constraint`." (see Contradictions) |
| N11 | TW | decision kept as: "The test: if you cannot name the lab or observation that would produce this number for one patient on one day, it is not a `value_constraint`." |
| N12 | HP | deleted |
| N13 | CE | deleted |
| N14 | CX | decision kept as: "Written in the lab's own unit, the multiplier reads as an absolute value far below the normal range, so as an exclusion it removes nearly every patient who ever had that test." |
| N15 | CE | decision kept as: "→ Laboratory test results are in this domain." |
| N16 | CX | decision kept as: "When the sentence asserts a clinical state and names a drug or other agent only as what that state is about, the entity is the state, in the state's domain, with the agent folded into `entity_text` as its qualifier — the agent is never looked up on its own." |
| N17 | CX | decision kept as: "A statement about whether or how a patient takes a drug is a Drug criterion, never a Measurement of that drug." |
| N18 | TW | decision kept as: "Decide the domain from what the description asserts about the patient: … taking, receiving, starting, stopping or changing a treatment ⇒ Drug. … having or having had a diagnosis, disorder or reaction ⇒ Condition. … a quantity measured on the patient ⇒ Measurement." |
| N19 | CE (IO) | decision kept as: "Strip dose, strength, route, and formulation details, leaving the ingredient name." |
| N20 | CE | decision kept as: "Pattern A — A measured value bounded on both sides (a range)" |
| N21 | CE (IO) | decision kept as: "Pattern B — A measured value bounded on one side: Single rule: PRESENCE of Measurement with a value_constraint carrying that bound." |
| N22 | TW | decision kept as: "Pattern C — The criterion states the patient has NOT had, does not have, or is not using something" |
| N23 | TW | decision kept as: "The negation may be a separate word or may be fused to the drug as a modifier; either way the patient has NOT had the drug, and the rule takes logic_type "ABSENCE"." |
| N24 | CE | decision kept as: "it names the DRUG ALONE — the ingredient the line implies or the class it names." |
| N25 | TW | decision kept as: "When the line offers a CHOICE between never having had a drug and having had it, Pattern E governs and this rule applies INSIDE it" |
| N26 | TW | decision kept as: "Pattern D — Any past occurrence, with no time limit stated: → logic_type: "PRESENCE", window covering all prior history (start -9999 days, end 0)" |
| N27 | TW | decision kept as: "Pattern E — Composite OR condition: the criterion lists alternatives, any one of which qualifies the patient, including disease sub-types that each qualify on their own" |
| N28 | TW | decision kept as: "When a protocol states such alternatives, you MUST emit a SINGLE rule with `sub_criteria` array and `group_type: "ANY"`." |
| N29 | CE (IO) | deleted |
| N30 | CE (IO) | deleted |
| N31 | CE (IO) | deleted |
| N32 | CE (IO) | decision kept as: "A lab criterion naming several analytes is one ANY group with one sub_criterion PER ANALYTE, each carrying its own value_constraint — a threshold shared by two analytes is written on both. Count the sub_criteria from the analytes the line names, not from the thresholds it states." |
| N33 | CE (IO) | decision kept as: the same sentence as N32 |
| N34 | CX (HP) | decision kept as: "the GROUP LABEL never carries the `value_constraint` … Write the bound out once per member it can honestly measure, even when that repeats the same number several times." |
| N35 | CE | decision kept as: "A member measured in a DIFFERENT UNIT from the threshold does not belong in that group — give it its own criterion with its own bound in its own unit, or leave it out." |
| N36 | SJ | decision kept as: "When the protocol names exactly one analyte, Pattern H applies and the right answer is ONE flat Measurement criterion carrying the bound — no group at all." |
| N37a | TW | decision kept as: "Pattern F — Conditional criterion: a requirement that applies only to a subgroup of patients" |
| N37 | CE | decision kept as: "When a criterion's requirement applies only to the patients in a subgroup the line names, and not to every patient, set `conditional: true` on that criterion." |
| N38 | TW | deleted |
| N39 | CE | decision kept as: "Pattern G — Region/subgroup-conditional VALUE (the requirement applies to everyone, but the NUMBER differs by an explicit subgroup the line names)." |
| N40 | CE (IO) | decision kept as: "Each variant is one sub_criterion carrying its own value and a name stating which subgroup it is for, and every variant carries the full original sentence as source_text" |
| N41 | CE (IO) | decision kept as: "A criterion whose alternatives are near-synonyms or facets of the SAME clinical entity cluster is ONE criterion … Emit it flat — one rule, no sub_criteria — and emit it exactly ONCE." |
| N42 | CE | decision kept as: "Pattern G needs a differing NUMBER for a named subgroup. A parenthetical that states no second threshold DEFINES the population the whole criterion applies to." |
| N43 | CX | decision kept as: "A scoping parenthetical read as a subgroup variant produces copies of one criterion, each mapped on its own paraphrased name, and the cohort is then filtered on the UNION of their divergent concept sets" |
| N44 | HP | deleted |
| N45 | CE | decision kept as: "A line naming several distinct analytes, each carrying its own value_constraint, is governed by Pattern E and Pattern H does not touch it" |

### NCT_DECOMPOSITION_PROMPT (production)

| ID | Class | Outcome |
|---|---|---|
| C1 | SJ | decision kept as: schema values are placeholders (`<days relative to index>`, `<number>`, `<PRESENCE\|ABSENCE>`, `<domain>`), plus rule 10: "The outcome's time_at_risk is in days after index: the follow-up the protocol states for the primary outcome, or start 0 and end 365 when it states none." (the template's 0/365 made explicit; the -365/-9999 windows and `7.0 %` deleted) |
| C2 | SJ (IO) | decision kept as rule 9: "If the criterion specifies a range, split into two rules: lower bound with PRESENCE + upper bound with ABSENCE." |
| C3 | SJ (IO) | decision kept as rule 9: "For a multiple of a reference range, keep the marker in `unit_text` as `"x ULN"` / `"x LLN"`" |
| C4 | CX (SJ) | decision kept as: "every rule and sub_criterion produced from one criterion line carries that whole line as `source_text`, byte-identical across all of them. Never the analyte's own name, never a shortened or tidied copy." |
| C5 | CE | decision kept as rule 0: "A line can carry fewer annotations than it names analytes: every analyte still becomes its own sub_criterion carrying the threshold that applies to it." |
| C6 | CX | decision kept as rule 0: "Dropping an analyte, or collapsing the whole criterion into one label with no constraint at all, is the failure this rule exists to stop." |
| C7 | CE | decision kept as rule 2: "ALL exclusion_rules MUST have logic_type: "ABSENCE" (never "PRESENCE"), however the exclusion criterion is worded." |
| C8 | CE | decision kept as rule 3: "When a single criterion line names several near-synonyms or facets of ONE clinical cluster, representing it means ONE rule naming that cluster." |
| C9 | CE | deleted |
| C10 | CE | deleted |
| C11 | TW | decision kept as rule 3: "Alternatives listed under one heading → OR (sub_criteria) … Separately numbered criteria → AND (separate rules) … A line that states its items as alternatives → OR (sub_criteria)" |
| C12 | TW | decision kept as rule 5: "When a criterion states the patient has NOT had or is not using something, use `logic_type: "ABSENCE"`" |
| C13 | CE | decision kept as rule 7: "Use negative days for time windows before the index date." |
| C14 | CE | decision kept as rule 8: "If a criterion is purely administrative — it states no clinical property of the patient — skip it." |
| C15 | CE | deleted |
| C16 | CE | deleted |
| C17 | CE (IO) | decision kept as rule 10: "If the protocol specifies an explicit time frame, convert it to days." |
| C18 | CE | decision kept as rule 11: "If a criterion lists specific drugs, keep those exact drugs, but strip strength, route, and formulation text." |
| C19 | CX | decision kept as: the same rule 11 sentence |
| C20 | TW | decision kept as rule 12: "lists multiple sub-conditions as alternatives — any one of which qualifies the patient, including sub-type paths that each qualify on their own" |
| C21 | CE | deleted |
| C22 | CE (IO) | deleted |
| C23 | CE (IO) | deleted |
| C24a | TW | decision kept as rule 13: "When a criterion's requirement applies only to a subgroup of patients the line names, set `conditional: true`." |
| C24 | CE (IO) | decision kept as: the same rule 13 sentence |
| C25 | CE | decision kept as rule 14: "When a criterion states a DIFFERENT number for a named subgroup while the requirement itself applies to every patient" |
| C26 | CE | decision kept as rule 14: "each carrying its own value_constraint and a name stating which subgroup it is for" |
| C27 | CX (SJ) | decision kept as rule 14: "do not emit the variants as separate top-level inclusion_rules/exclusion_rules entries; those are AND-combined downstream and silently force the strictest variant onto every patient" |
| C28 | SJ | decision kept as rule 14: "Emit ONE group with `group_type: "ANY"` … and a sub_criterion PER VARIANT" |
| C29 | CX | decision kept as rule 15: "a suffix that reads like a subgroup variant" |
| C30 | CX | decision kept as rule 15: "a suffix that tags the section, role, or domain" |
| C31 | CX | decision kept as rule 15: "no suffix at all, but a reworded name foregrounding a facet the first name omitted" |
| C32 | CE | decision kept as rule 15: "Pattern G requires a DIFFERING NUMBER for a named subgroup; a parenthetical that states no second threshold has no variant to emit." |
| C33 | CX (SJ) | decision kept as rule 15: "If that line describes one cluster and you have already emitted a rule for it, do not emit another — and do not resolve the urge to emit another by renaming it." |
| C34 | CX (SJ) | decision kept as: the same rule 15 sentence |
| C35 | SJ | decision kept as rule 15: "The single criterion is flat — no sub_criteria, no parenthetical suffix on its name — and carries the whole sentence verbatim as source_text." |
| C36 | CE | decision kept as rule 15: "A line naming several DISTINCT analytes, each carrying its own value_constraint, is governed by rule 12 and this rule does not reach it" |

The literal `"""` that ended the rendered prompt (prompts.py:795 at ec0cf51) is gone; the guard asserts no
rendered prompt contains one.

### THRESHOLD_REVIEW_PROMPT (Step 7) and THRESHOLD_MATCH_PROMPT (Step 8b) (production)

| ID | Class | Outcome |
|---|---|---|
| T1 | TW | decision kept as: "find criteria whose sentence states a numeric threshold — a number the criterion compares a patient value against" |
| T2 | CE | deleted |
| M1 | CE | decision kept as: "A threshold may be shared by more than one rule when the original text places several analytes under one comparator as alternatives: each of those analytes gets that same threshold index." |
| M2 | CE | decision kept as: "A rule gets its OWN threshold only when the text states a separate comparator for its analyte, and then it carries that comparator's index." |

### SYSTEM_PROMPT and DECOMPOSITION_PROMPT (free-text `parse()`, side)

| ID | Class | Outcome |
|---|---|---|
| S1 | CE | deleted |
| S2 | CE | decision kept as: "If the protocol states an explicit temporal constraint, convert it to days." |
| S3 | CE | deleted |
| S4 | CE | deleted |
| S5 | CX | decision kept as: "Written in the lab's own unit, the multiplier reads as an absolute value far below the normal range, so as an exclusion it removes nearly every patient who ever had that test." |
| S6 | CE (IO) | decision kept as: "Strip dose, strength, route, and formulation details, leaving the ingredient name." |
| S7 | CE | decision kept as: "Pattern A — A measured value bounded on both sides (a range)" |
| S8 | CE | decision kept as: "Pattern B — A measured value bounded on one side" |
| S9 | TW | decision kept as: "Pattern C — The criterion states the patient has NOT had, does not have, or is not using something" |
| S10 | TW | decision kept as: "Pattern D — Any past occurrence, with no time limit stated: → logic_type: "PRESENCE", window covering all prior history (start -9999 days, end 0)" |
| D1 | SJ | decision kept as: schema placeholders, plus rule 4: "Always include the outcome's time_at_risk window, in days after index: the follow-up the question states for the outcome, or start 0 and end 365 when it states none." |
| D2 | SJ (IO) | decision kept as rule 5: "If the criterion specifies a range, split into two rules: lower bound with PRESENCE + upper bound with ABSENCE, both carrying the same verbatim `source_text`." |
| D3 | SJ (IO) | decision kept as rule 5: "For a multiple of a reference range, keep the marker in `unit_text` as `"x ULN"` / `"x LLN"`" |
| D4 | TW | decision kept as rule 1: "When the question states the patient has NOT had or is not using something, use `logic_type: "ABSENCE"`" |
| D5 | CE | decision kept as rule 3: "Use negative days for time windows before the index date." |
| D6 | CE | deleted |
| D7 | CE | deleted |
| D8 | TW | deleted |

### Other wording the lint required in the Agent 1 prompts (not inventory rows)

- `drop the "  1. " numbering only` → "drop only the line's leading list number" (a quoted instance of the format).
- "(a range, or a line naming three analytes at once)" → "several analytes".
- Pattern G's scare-quoted phrases ("The requirement is universal", "apply whichever variant matches this
  patient", "close enough") reworded without quotes; rule 3's quoted restatement of itself likewise.
- "Two criteria that got this backwards, and what each cost:" (the N16/N17 lead-in) deleted with them.
- DECOMPOSITION_PROMPT rule 7: "(e.g., the exact medication class, condition, or procedure)" → "— the
  medication class, condition, or procedure itself".

### Contradictions found, left as they were

- N10 keeps "a Demographics criterion never takes a `value_constraint`", while Pattern G / rule 14 tell the
  model to give each subgroup variant its own `value_constraint` — and the variants C27/C28 illustrated were
  ages. `TTEService._build_demographic_rule` (tte_service.py) builds the CIRCE age rule FROM `valueConstraint`.
  Both prompt statements predate this change and both are kept verbatim in substance; resolving which one
  holds is a decision, not an example removal.

## Planner — `src/agents/planner/prompts.py` (14 rows, production)

| ID | Class | Outcome |
|---|---|---|
| PS1 | CE | decision kept as: "→ Laboratory test results are in this domain" |
| PS2 | CE | decision kept as: "including when a sub-term names the lab test by its clinical *effect* (a raised or lowered result) rather than by the test's name: such a sub-term is still a lab value, not a diagnosis, so its `domain` is Measurement, not Observation." |
| PS3 | CE | decision kept as rule 1: "If a criterion already names one specific, individually codeable clinical concept, return it as-is with `decompose: false`" |
| PS4 | CE | decision kept as rule 2: "If a criterion is composite/umbrella — it names a category that covers several distinct, individually codeable concepts — decompose it into specific sub-terms" |
| PS5 | CE | decision kept as rule 5: "PRESENCE → `"ANY"` — an umbrella term is satisfied by any one of its sub-terms" |
| PS6 | CE | decision kept as rule 5: "ABSENCE → `"ALL"` — the absence of an umbrella term requires every one of its sub-terms to be absent." |
| PS7 | CE | decision kept as rule 6: "Do NOT over-decompose: a term that already names one specific concept stays as it is; only a category term is decomposed" |
| PD1 | CE | decision kept as: "a sub-term that is still an umbrella is not finished, and a term that names no analyte or codeable concept leaves a criterion nothing can query." |
| PD2 | CE | decision kept as: "Every sub-term the line names carries its own span." |
| PD3 | CE (IO) | decision kept as: "Breaking a term the line names into codeable concepts the line does not name is exactly what this step is FOR — those concepts come back with `source_span: null`, while the sub-terms the line itself names come back with spans." |
| PD4 | CE (IO+CX) | decision kept as: "an umbrella term must come back as its specific kinds, each with `source_span: null`, which is the correct and expected answer — and NOT as one entry quoting the line back." |
| PD5 | CE | decision kept as: "When the line enumerates members that are ALREADY individually codeable, that enumeration IS the sub-term list — do not add a member the line does not mention." |
| PD6 | TW | decision kept as: "When the line marks its list as open — it presents its members as instances of a larger set rather than as the whole set — you may extend it" |
| PD7 | CE | decision kept as: "copy the threshold phrase — the comparator, the number and any unit or reference-limit multiple, as written — verbatim into `value_constraint_text`." |

Lint-required wording outside the inventory: `"composite"` unquoted; the output schema's `"decompose": true/false`
and `"reasoning": "brief explanation"` became `<true|false>` / `"<brief explanation>"`.

## Agent 2 and the ConceptSet NLU router (10 rows)

The three LangChain-rendered rows (K1, U3, R6) are removed by no longer passing
`get_format_instructions()`; each prompt now carries a hand-written output contract naming every field of the
pydantic model the parser reads (asserted by the guard), with types and allowed values and no sample object.
`JsonOutputParser` still parses. The library block also leaked `CriticSelection`'s and `IntentResult`'s
docstrings into the prompts; that is gone with it.

| ID | Prompt | Class | Outcome |
|---|---|---|---|
| R1 | TOPN_SYSTEM_PROMPT (production) | SJ | decision kept as: "If none fit, set query_has_match to false and selected_ids to an empty array. Selecting nothing is a correct answer, not a failure." |
| K1 | critic, rendered (production) | SJ (CX) | decision kept as: "Return ONLY a JSON object with these keys: … recommended_action: one of keep, drop, rerank." (library text deleted) |
| U1 | IntentSeparator.SYSTEM_PROMPT (production, RAG fallback) | TW | decision kept as: "Every concept the request says the patient must not have goes in 'exclude', whatever words express the negation." |
| U2 | IntentSeparator.SYSTEM_PROMPT | CE | decision kept as: "Expand abbreviations to their full clinical names when possible." |
| U3 | NLU router, rendered | SJ (CX) | decision kept as: "Return ONLY a JSON object with these keys: … fallback_reason: string or null, the reason for the fallback." (library text deleted) |
| R2 | `_DOMAIN_GROUNDING_INSTRUCTION` (side, no caller) | CE | decision kept as: "When the domain_hint is provided, interpret every medical abbreviation in the sense it has within that domain." |
| R3 | `_DOMAIN_GROUNDING_INSTRUCTION` | CE | decision kept as: the same sentence as R2 |
| R4 | `_DOMAIN_GROUNDING_INSTRUCTION` | CE | decision kept as: the same sentence as R2 |
| R5 | `_DOMAIN_GROUNDING_INSTRUCTION` | CX | decision kept as: "Do NOT select concepts from an unrelated clinical domain, even when a candidate's name shares letters or an abbreviation with the term." |
| R6 | single-select reranker, rendered (side, no caller) | SJ (CX) | decision kept as: "Return ONLY a JSON object with these keys: … reasoning: string, a brief explanation of why this concept was selected." (library text deleted) |

Lint-required wording outside the inventory: TOPN_SYSTEM_PROMPT's JSON template, which showed filled values
(`true`, `false`), now describes the two keys in prose — its first two lines, which the code comment pins as
measured, are unchanged. `_CRITIC_PROMPT_VERSION` is bumped to `2026-10-12-no-library-format-instructions`, so
both critic caches re-key.

## Side tools (76 rows)

### Comparator — `src/agents/comparator/recommender.py`

| ID | Prompt | Class | Outcome |
|---|---|---|---|
| CM1 | `_CLASSIFY_PROMPT` | CE | decision kept as: "<the main reservation about this class as a comparator, at most 12 words>" |
| CM2 | `_LIT_EXTRACT_PROMPT` | CE | decision kept as: "REJECT wrong-modality drugs, whose route or duration of use differs from the treatment's" |

Lint-required wording outside the inventory: `"confidence": 0.0-1.0` → `<number from 0.0 to 1.0>`; the literature
template's `"ingredient1","ingredient2"`, `"same_setting":true` and `"one line with PMIDs"` → placeholders.

### TTE report narrative — `src/services/tte_service.py` (`_generate_report_narrative`)

| ID | Prompt | Class | Outcome |
|---|---|---|---|
| TS1 | `system_prompt` | CX | decision kept as: "and the report must not describe any direction or size of effect." |
| TS2 | `system_prompt` | CX | decision kept as: "If p-value >= 0.05, call the result non-significant and the estimate imprecise, and do not describe it as moving in any direction." |
| TS3 | `system_prompt` | CX | decision kept as: "Do NOT use language that asserts the treatment caused or prevented the outcome; report the hazard ratio as an estimated effect." |
| TS4 | `system_prompt` | CX | decision kept as: "For the outcome, give the exact definition, or state that the outcome definition was not verified; never present it as assumed to match the original trial." |
| TS5 | `system_prompt` | CX | decision kept as: "TTE targets a causal estimand, so do NOT dismiss the result as merely associational; when causal interpretation is not supported, say so and give the specific reasons." |
| TS6 | `prompt` | CE | decision kept as: "Include an emulation scope statement: whether this is a full replication of the target trial or a partial emulation, and in what respect it is partial." |
| TS7 | `prompt` | CE | decision kept as: "Then recommend next analyses that would address the limitations listed in Section 7." |

Lint-required wording outside the inventory: `"robust"` unquoted ("robust to confounding"). The required output
phrases the report must state verbatim ("insufficient events for reliable estimation", "weighting FAILED to achieve
adequate balance", and three others) are kept; the guard declares them as output tokens of this prompt. TS2's first
rewording ("the result is not statistically significant") shared a 32-character span with CAROLINA's JAMA paper
and failed the contamination gate's Gate B; it was reworded again.

### Threshold classifier — `src/agents/agent1/threshold_classifier.py` `_HEAD_RULES` and the taxonomy prompt

The taxonomy prompt (`docs/daily_notes/tte_value_taxonomy.prompt.txt`) is a pure function of
`scripts/build_value_taxonomy.py`; it was changed there and regenerated, together with
`docs/daily_notes/tte_value_taxonomy.json` (the checked-in JSON was confirmed equal to the HEAD script's `build()`
output first, so the regeneration carries only this change). `render_prompt` now renders the task, the output
schema (placeholders), the rules, each class's `definition` and a new `boundaries` list, and the NON_CRITERION
families' `what`. Corpus counts, `why_llm`, Circe destinations, signals, hazards, worked examples, the comparator
spelling table and the notation block stay in the JSON for the dashboard and no longer reach the model. Class
definitions and two family `what` lines were rewritten without instances; the dashboard shows those same strings.
`scripts/probe_criterion_classifier.py`'s `INSTRUCTION_TAIL` was kept byte-identical to the classifier's tail
(checked: equal).

| ID | Class | Outcome |
|---|---|---|
| TC1 | TW | decision kept as: "Never supply a head for a bare unit. A span is an AGE span only when the criterion's own words say the number is the patient's age." |
| TX1 | CE (HP) | deleted |
| TX2 | HP | deleted |
| TX3 | HP | deleted |
| TX4 | CE | decision kept as: "A time unit or a dimensionless index does not move a number out of this class." |
| TX5 | CE | decision kept as: "The number is the result of a measurement or observation made on the patient: a laboratory result, a vital sign, an imaging or electrophysiology measurement, or a body metric." |
| TX6 | CE | decision kept as: the same sentence as TX5 |
| TX7 | CE | decision kept as: the same sentence as TX5 |
| TX8 | TW | decision kept as: "A bound stated against the upper or lower limit of normal belongs here: only measurements have laboratory reference ranges." |
| TX9 | TW | deleted |
| TX10 | CX | decision kept as: "The head is a graded clinical scale -> SCORE_GRADE." |
| TX11 | HP | deleted |
| TX12 | CE | deleted |
| TX13 | CE | deleted |
| TX14 | CE | deleted |
| TX15 | CE (HP) | decision kept as: "a time unit whose head is the patient's age is an AGE span, not a temporal one." |
| TX16 | TW | decision kept as: the same sentence as TX15 |
| TX17 | CE | decision kept as: "An anchor phrase may still be present; the head test runs first and wins." |
| TX18 | CX | decision kept as: "A time unit whose head is a measurement -> MEASUREMENT_VALUE." |
| TX19 | HP | deleted |
| TX20 | CE | deleted |
| TX21 | CE | deleted |
| TX22 | TW | decision kept as: "The number measures the distance in time between a qualifying event and the index date or another anchor." |
| TX23 | TW | decision kept as: "The anchor is often elided in exclusion criteria, so absence of an explicit anchor does not rule this class out." |
| TX24 | CE | decision kept as: "the head is an event, not a quantity." |
| TX25 | CX | decision kept as: "The time expression is an attributive modifier of a procedure name -> NON_CRITERION / protocol_or_procedure_name." |
| TX26 | HP (CE) | deleted |
| TX27 | CE | deleted |
| TX28 | CE | deleted |
| TX29 | HP | deleted |
| TX30 | TW | decision kept as: "a condition or exposure is required to have held continuously for N units, and the criterion is satisfied by a span of time, not by an event occurring inside one." |
| TX31 | HP | deleted |
| TX32 | CE | deleted |
| TX33 | CE | deleted |
| TX34 | CE | decision kept as: "its head is a drug name or drug class." |
| TX35 | TW | decision kept as: "The unit, when there is one, is a dose attached to the drug, not a concentration in a specimen." |
| TX36 | TW | decision kept as: "The number is an amount of drug administered, permitted or prohibited" |
| TX37 | CX | decision kept as: "The unit is a concentration in a specimen -> MEASUREMENT_VALUE." |
| TX38 | HP | deleted |
| TX39 | CE | deleted |
| TX40 | CE | decision kept as: "The number is a point on a named clinical scale or grading system. It is ordinal, not a physical quantity" |
| TX41 | CE | deleted |
| TX42 | CE | decision kept as: the same sentence as TX40 |
| TX43 | TW | decision kept as: "it carries no unit even when a scale word stands where a unit would be." |
| TX44 | CE | decision kept as: "The scale's range is small and bounded, unlike a laboratory range." |
| TX45 | CE | deleted |
| TX46 | CE | deleted |
| TX47 | CE | decision kept as: "The number says how much of something happened or how many times, attached to a procedure, treatment episode or exposure event rather than to a measured biological quantity." |
| TX48 | TW | decision kept as: "Nothing was measured on the patient; something was counted or dispensed." |
| TX49 | CE | decision kept as: "A volume or amount belongs here when it belongs to the event, not to a specimen." |
| TX50 | HP (CE) | deleted |
| TX51 | CE | deleted |
| TX52 | CE | deleted |
| TX53 | CE | decision kept as: "a self-reported or lifestyle quantity with no coded representation" |
| TX54 | CE | deleted |
| TX55 | CX | decision kept as: "[statistical_decision_rule] A number from the trial's statistical analysis plan or reported results, compared against a study conclusion rather than against a property of the patient." |
| TX56 | TW | decision kept as: the same sentence as TX55 |
| TX57 | TW | deleted |
| TX58 | CE | deleted |
| TX59 | TW | deleted |
| TX60 | TW | deleted |
| TX61 | CE | deleted |
| TX62 | CE | deleted |
| TX63 | CE | deleted |
| TX64 | TW (HP) | deleted |
| TX65 | CE | deleted |
| TX66 | HP (CE) | decision kept as two RULES: "A reference bound stated with no numeral is still a threshold: emit its span, do not skip it. … When a span's comparator sits outside it, in a sibling disjunction or a parenthetical, widen the threshold_phrase to a verbatim substring that includes the comparator." |

Lint-required wording outside the inventory: the OUTPUT schema's description values became `<...>` placeholders,
including `"confidence": "<high|low>"`.

Contradiction found, left as it was: the taxonomy's AGE definition keeps the elided-head rule ("When a bare time
unit appears with no other head anywhere in the criterion, the head is the patient's age"), while `_HEAD_RULES`
(TC1) tells the model never to supply a head for a bare unit. The tail was written to override the taxonomy, and
both predate this change.

## Gaps

- `scripts/prompt_ab.py`, `example_value_ab.py` and `planner_example_ab.py` send whatever prompt file is named on
  the command line; those files are not in the tree and were not checked (inventory §4).
- The guard renders prompts under `src/` only. `scripts/` prompts other than the classifier probe's tail were not
  linted.
- The dashboard built by `scripts/build_diagnosis_dashboard.py` reads the regenerated taxonomy JSON; the dashboard
  HTML was not rebuilt here.
- ADR-032 D3 still quotes the earlier `_HEAD_RULES` wording; it is a decision record and was not edited.
