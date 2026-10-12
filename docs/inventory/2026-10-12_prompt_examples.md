# Examples in LLM-bound prompts — inventory, 2026-10-12

Scope: every example in any string the pipeline sends to an LLM, at artemis `fix/0923-reply` **ec0cf51**.
Read-only investigation. Machine-readable companion: `2026-10-12_prompt_examples.json` (one object per row below).

**205 example occurrences across LLM-bound prompts; 106 are on the production rebuild → CIRCE-export path.**
They are concentrated in Agent 1's NCT_SYSTEM_PROMPT (46) and NCT_DECOMPOSITION_PROMPT (37), the planner (14) and
the Agent 1 Step 7/8b prompts (4). The critic's own text at 2befcbc is example-free, but its rendered prompt still
carries LangChain's generic `foo/bar/baz` sample and counterexample.

## Where the measurements contradict or extend the brief

- **Critic F2 (2befcbc):** `git diff 2befcbc HEAD -- critic.py` is empty and its own instructions/self-reflection contain
  no examples. But the rendered prompt appends `{format_instructions}` (critic.py:274, :439), which pulls in from
  langchain-core 0.1.53: `As an example, for the schema {"properties": {"foo": …}} the object {"foo": ["bar", "baz"]} is a
  well-formatted instance … The object {"properties": {"foo": ["bar", "baz"]}} is not well-formatted.` That is a sample
  JSON plus a counterexample. Verified by rendering the prompt with a stubbed LLM; the artemis-api container runs the
  same 0.1.53 and contains the same text. The same block reaches the NLU router and the single-select reranker.
- **`src/models/ir.py` never reaches a prompt.** No `get_format_instructions()`/`model_json_schema()` on IR models;
  `parser.py:231` `JsonOutputParser()` is parse-only. Agent 1's schema is hand-written in the prompt.
- **No LLM call in** concept_set_refiner, query_expander, map_entity, logic, kg_expander, drug_class_expander,
  umls_synonym_expander, agent4/validator. workflow.py only calls the reranker (`rerank_topn` / `rerank_topn_batch`)
  and the critic.
- **Not used in production:**
  - the single-select reranker prompt with the abbreviation list (`reranker.rerank` / `rerank_batch`) has no caller in
    `src/` or `scripts/`;
  - `criteria_dedup_judge` has no importer in `src/` (only `scripts/run_orgroup_judge_arms.py`; default arm lexical);
  - `threshold_classifier` is only called by `scripts/eval_threshold_classifier.py`;
  - `EXTRACTION_PROMPT` is unused.
- **Defects inside the examples:**
  - prompts.py:726 and :733 say "forces Age >= 20" / "satisfy >= 20" while the JSON uses 21.0 — 623e663 changed the
    values and left the 4d30ddf prose.
  - NCT_DECOMPOSITION_PROMPT ends with a literal `"""` (prompts.py:795; confirmed in the rendered string).
  - Side-tool taxonomy prompt line 65 quotes CAROLINA (NCT01243424) and line 93 quotes CARMELINA (NCT01897532);
    both texts match those trials' Agent-1 IR caches — the evaluated-corpus contamination 623e663 removed from Agent 1.

## 1. LLM call sites

| Call | Prompt | Stage | Production? |
|---|---|---|---|
| agent1/parser.py:389 → :1367 | NCT_SYSTEM_PROMPT (prompts.py:226) + NCT_DECOMPOSITION_PROMPT (:484); criteria via `_format_criteria` + `annotate_value_constraints` (value_constraint.py:1334) | Agent 1 NCT extraction | YES (`run_generate_from_nct` → tte_service.py:12011) |
| parser.py:661 | THRESHOLD_REVIEW_PROMPT (:797) | Agent 1 Step 7 | YES (`verify_thresholds=True` default) |
| parser.py:839 | THRESHOLD_MATCH_PROMPT (:822) | Agent 1 Step 8b | YES, only when Step 7 flags a miss and 8a refuses |
| parser.py:252 → :1367 | SYSTEM_PROMPT (:28) + DECOMPOSITION_PROMPT (:86) | Agent 1 free-text `parse()` | No; description path only (tte_service.py:1470/1519, supervisor*.py) |
| agent1/pubmed_fetcher.py:1087 | `_LLM_CRITERIA_PROMPT` (:1030) | PDF/PubMed criteria split | YES, only when regex finds <5 items in >200 chars |
| planner/decomposer.py:371 | PLANNER_SYSTEM_PROMPT (planner/prompts.py:6) + DECOMPOSITION_PROMPT (:48) | Planner (Agent 1.5) | YES (tte_service.py:11888) |
| agent2/reranker.py:175, :339 | TOPN_SYSTEM_PROMPT (:43) | Agent 2 top-N seed | YES (workflow.py:799, :1099) |
| agent2/critic.py:436 | system (:258) + `_SELF_REFLECTION_INSTRUCTIONS` (:213) + LangChain format instructions | Agent 2 critic | YES (workflow.py:1018) |
| agent2/reranker.py:133, :261 | single-select (:90) + `_DOMAIN_GROUNDING_INSTRUCTION` (:16) + format instructions | Agent 2 single-select | No caller |
| conceptset/nlu_router.py:111 | `IntentSeparator.SYSTEM_PROMPT` (:72) + format instructions | ConceptSet RAG fallback | YES, only when Agent 2 raises or returns empty (tte_service.py:8823) and no temporal keyword |
| conceptset/clinical_reranker.py:201 | prompt (:81) | Same fallback, plus HITL re-recommend (tte_service.py:9148) | YES, only when cross-encoder confidence is low |
| comparator/recommender.py:114, :315 | `_CLASSIFY_PROMPT` (:62), `_LIT_EXTRACT_PROMPT` (:215) | Comparator proposal (ADR-028) | Side (tte_service.py:7013) |
| tte_service.py:2653 | analysis-strategy finalizer (:2638) | TTE analysis | Side |
| tte_service.py:9910 | report narrative `system_prompt` (:9774) + `prompt` (:9821) | TTE report | Side |
| agent1/criteria_dedup_judge.py:469 | `_JUDGE_PROMPT` (:196) | OR-group judge | Side (not wired) |
| agent1/threshold_classifier.py:395 | docs/daily_notes/tte_value_taxonomy.prompt.txt + `_HEAD_RULES` (:88) | ADR-032 classifier | Side (scripts only) |

Zero examples in: the critic's own text, clinical_reranker, pubmed_fetcher, the dedup judge, the finalizer,
EXTRACTION_PROMPT.

## 2. Example occurrences

Class: CE = clinical example, CX = counterexample, TW = trigger-word list, HP = history/provenance prose,
SJ = sample JSON; IO = input→output pair (shown as a secondary class). Commit = first commit from
`git log -S<needle> --reverse -- <file>`. 6ffd07c (2026-07-22) is the root "baseline snapshot", so those examples
predate this repository's history. 623e663 = 2026-09-12; 8bbd50d and 738be93 = 2026-09-10. TS6/TS7 are counted as
CE but are non-clinical examples.

#### NCT_SYSTEM_PROMPT — production — `src/agents/agent1/prompts.py` — 46 rows

| ID | Line | Verbatim | Class | Commit |
|---|---|---|---|---|
| N1 | 241 | (e.g., "Type 2 Diabetes", "Metformin") | CE | 6ffd07c 2026-07-22 — line reworded in 8bbd50d; e.g. text present since root |
| N2 | 244-245 | ("Anti-diabetic therapy naive", "At least one specified risk factor", "Stable Background Medication") | CX | 623e663 2026-09-12 |
| N3 | 246-247 | Measured on the 2026-09-10 six-trial store: 44 of the 369 leaf criteria carried no `entity_text` at all. | HP | 8bbd50d 2026-09-10 |
| N4 | 250 | (e.g., "within 8 weeks prior to enrolment"), convert it to days (e.g., {start: -90, end: 0}) | CE (IO) | 623e663 2026-09-12 |
| N5 | 260 | (e.g. "ferritin >= 30 ng/mL", "ceruloplasmin > 60 mg/l") | CE | 623e663 2026-09-12 |
| N6 | 269 | a DRUG DOSE — "colchicine > 1.2 mg/day", "bupivacaine > 2 mg/kg" | CX | 623e663 2026-09-12 |
| N7 | 273-274 | "psoriasis duration > 14 years", "eczema >= 7 years" | CX | 623e663 2026-09-12 |
| N8 | 277 | "arthroplasty ... >60% cartilage loss" | CX | 623e663 2026-09-12 |
| N9 | 279 | a COUNT — "at least two CV risk factors", "> 1 prior episode" | CX | 738be93 2026-09-10 |
| N10 | 281 | an AGE — "age >= 18 years" | CX | 738be93 2026-09-10 |
| N11 | 283-284 | The unit is the tell: mg/day, mg/kg, years-of-disease, % stenosis and "risk factors" | TW | 623e663 2026-09-12 |
| N12 | 288-295 | Measured on criteria of exactly these three shapes: a "required treatment with <drug> > <dose>/day" line became… | HP | 623e663 2026-09-12 |
| N13 | 297 | ("ferritin > 4x ULN", "ceruloplasmin above 6 times the upper limit of normal") | CE | 623e663 2026-09-12 |
| N14 | 299-301 | "4x ULN" sent as {op: "gt", value: 4.0, unit_text: "ng/mL"} … real ferritin runs 30-300 ng/mL | CX | 623e663 2026-09-12 |
| N15 | 308 | Lab tests (HbA1c, creatinine, eGFR, etc.) are in this domain | CE | 6ffd07c 2026-07-22 |
| N16 | 320-328 | "Documented allergy to bupivacaine…" emitted as domain=Condition … "Hypersensitivity to bupivacaine" | CX | 623e663 2026-09-12 |
| N17 | 329-333 | "Adjustment of colchicine dosage in the 8 weeks before enrolment" … "Colchicine level" | CX | 623e663 2026-09-12 |
| N18 | 334-336 | "dose", "treatment with", "use of", "therapy" ⇒ Drug. "hypersensitivity", "allergy", "history of"… | TW | 738be93 2026-09-10 |
| N19 | 340 | convert "ticagrelor 90 mg oral tablet" to "ticagrelor" | CE (IO) | 6ffd07c 2026-07-22 |
| N20 | 345 | Pattern A … (e.g., "ferritin 30 ng/mL to 300 ng/mL") | CE | 623e663 2026-09-12 |
| N21 | 350-351 | Pattern B (e.g., "ceruloplasmin >= 20") … {{op: "gte", value: 20}} | CE (IO) | 623e663 2026-09-12 |
| N22 | 353 | "No prior X" / "Without X" / "X-naive" | TW | 8bbd50d 2026-09-10 |
| N23 | 356-357 | "treatment-naive", "drug-naive", "biologic-naive", "insulin-naïve", "no prior use of", … "washout of" | TW | 623e663 2026-09-12 |
| N24 | 361 | ("insulin", "metformin") or the class it names ("anti-diabetic agent") | CE | 8bbd50d 2026-09-10 |
| N25 | 365 | ("drug naive OR pre-treated with X") | TW | 8bbd50d 2026-09-10 |
| N26 | 369 | Pattern D — "History of X" | TW | 6ffd07c 2026-07-22 |
| N27 | 372-373 | ("≥1 of A, B, C ...", "at least one of", "with or without X", "either X or Y", …) | TW | 6ffd07c 2026-07-22 |
| N28 | 374-375 | "one or more of", "≥1 of", "with or without", "either...or", "including ... or" | TW | 6ffd07c 2026-07-22 |
| N29 | 379-380 | "Age ≥ 50 with ≥1 of: psoriasis, vitiligo, chronic urticaria, alopecia areata" → … | CE (IO) | 623e663 2026-09-12 |
| N30 | 381-383 | "Aortic valve disease with or without regurgitation" → aortic stenosis, … | CE (IO) | 623e663 2026-09-12 |
| N31 | 384-385 | "Aortic stenosis patients requiring valve replacement OR aortic regurgitation patients" → | CE (IO) | 623e663 2026-09-12 |
| N32 | 389-391 | "Ferritin or ceruloplasmin > 4X ULN or a serum haptoglobin >= 6.5X ULN" → three sub_criteria | CE (IO) | 623e663 2026-09-12 |
| N33 | 392-394 | "Prolactin, cortisol, or growth hormone above 1X ULN" → | CE (IO) | 623e663 2026-09-12 |
| N34 | 399-405 | "Uncontrolled hypercalcaemia with a serum calcium level > 13 mg/dl" … Parathyroid hormone, Ionised calcium… | CX (HP) | 623e663 2026-09-12 |
| N35 | 406-407 | 13 mg/dL is a serum-calcium number; parathyroid hormone is reported in pg/mL | CE | 623e663 2026-09-12 |
| N36 | 410-412 | entity_text "Calcium", value_constraint {op: "gt", value: 13, unit_text: "mg/dl"} | SJ | 623e663 2026-09-12 |
| N37a | 417 | ("If [subgroup] → [requirement]") | TW | 6ffd07c 2026-07-22 |
| N37 | 419-421 | (e.g., "females of childbearing potential must have negative pregnancy test", … methotrexate …) | CE | 6ffd07c 2026-07-22 — methotrexate item added in 623e663 |
| N38 | 424-425 | "females must", "women of childbearing", "patients with X must also", "if the patient has", … | TW | 6ffd07c 2026-07-22 |
| N39 | 428-430 | "Age >= 18 years. For Iceland only: Age >= 21 years", "ferritin >= 60 ng/mL (>= 45 …)", "ceruloplasmin <= 9 mg/dL…" | CE | 623e663 2026-09-12 |
| N40 | 445-449 | Example: "Age >= 18 years. For Iceland only: Age >= 21 years" → Age (general, >= 18), Age (Iceland, >= 21) | CE (IO) | 623e663 2026-09-12 |
| N41 | 459-462 | "Patients with symptomatic orthostatic hypotension, postural dizziness, or … syncopal episode" → ONE rule | CE (IO) | 623e663 2026-09-12 |
| N42 | 464 | ("Age >= 18 years. For Iceland only: Age >= 21 years" — 18 against 21) | CE | 623e663 2026-09-12 |
| N43 | 466-467 | copies suffixed "(within 3 minutes)" and "(General)" | CX | 623e663 2026-09-12 |
| N44 | 467-471 | measured on a sentence of exactly this shape: three copies, 4 to 7 concepts each, … union 11 | HP | 623e663 2026-09-12 |
| N45 | 477-480 | "Ferritin (FERR), ceruloplasmin (CP), or haptoglobin (HP) >= 6 x upper limit of normal" | CE | 623e663 2026-09-12 |

#### NCT_DECOMPOSITION_PROMPT — production — `src/agents/agent1/prompts.py` — 37 rows

| ID | Line | Verbatim | Class | Commit |
|---|---|---|---|---|
| C1 | 513-514 | "window": {{"start": -365, "end": 0}}, "value_constraint": {{"op": "gte", "value": 7.0, "unit_text": "%"}} | SJ | 6ffd07c 2026-07-22 — filled values also at 518, 536, 553 |
| C2 | 558-581 | One-shot: "Serum ferritin 30 ng/mL to 300 ng/mL at screening" → PRESENCE ≥30 + ABSENCE ≥300 | SJ (IO) | 623e663 2026-09-12 |
| C3 | 583-608 | One-shot: "Serum ferritin or ceruloplasmin > 4x upper limit of normal" → 2 rules "x ULN" | SJ (IO) | 623e663 2026-09-12 |
| C4 | 610-618 | // WRONG {"name": "Ferritin elevation", "source_text": "Ferritin", …} // RIGHT … | CX (SJ) | d2f2e0b 2026-08-20 — example text reworded in 623e663 |
| C5 | 631-634 | The illustrative line "Ferritin or ceruloplasmin > 4X ULN or a serum haptoglobin >= 6.5X ULN" | CE | 623e663 2026-09-12 |
| C6 | 635-636 | Emitting two rules and dropping ceruloplasmin is the specific failure | CX | 623e663 2026-09-12 |
| C7 | 640 | "No T1DM", "No prior transplant", "No renal dialysis" | CE | 6ffd07c 2026-07-22 |
| C8 | 645-646 | (orthostatic hypotension, postural dizziness, syncope on standing — one … cluster) | CE | 623e663 2026-09-12 |
| C9 | 652 | e.g., "MI OR stroke OR revascularization OR CHF" | CE | 6ffd07c 2026-07-22 |
| C10 | 654 | (e.g., "must have psoriasis" AND "must have ferritin>=30 ng/mL") | CE | 623e663 2026-09-12 |
| C11 | 656-658 | Bullet lists… → OR; Separate numbered… → AND; "≥1 of", "at least one", "or", "with or without" | TW | 6ffd07c 2026-07-22 |
| C12 | 660 | For "No prior X" or "without X" | TW | 6ffd07c 2026-07-22 |
| C13 | 666 | (e.g., -365 for 1 year before) | CE | 6ffd07c 2026-07-22 |
| C14 | 667 | (e.g., "informed consent") | CE | 6ffd07c 2026-07-22 |
| C15 | 669 | ("4x ULN", "below the lower limit of normal") | CE | 623e663 2026-09-12 |
| C16 | 672 | (e.g., "7-10%") | CE | 6ffd07c 2026-07-22 |
| C17 | 675 | (e.g., "within 8 weeks prior to enrolment"), convert to days ({{start: -90, end: 0}}) | CE (IO) | 623e663 2026-09-12 |
| C18 | 678 | (e.g., "ticagrelor", "clopidogrel") | CE | 6ffd07c 2026-07-22 |
| C19 | 679-680 | Use "ticagrelor", not "ticagrelor 90 mg oral tablet" | CX | 6ffd07c 2026-07-22 |
| C20 | 683-684 | "≥1 of: ...", "at least one of", "with or without X", "either X or Y", "including X, Y, or Z" | TW | 6ffd07c 2026-07-22 |
| C21 | 685 | (e.g., "Aortic stenosis patients requiring valve replacement OR aortic regurgitation patients") | CE | 623e663 2026-09-12 |
| C22 | 701 | "Aortic valve disease with or without regurgitation" → sub_criteria=[aortic stenosis, …] | CE (IO) | 623e663 2026-09-12 |
| C23 | 702 | "Aortic stenosis patients OR aortic regurgitation patients" → … | CE (IO) | 623e663 2026-09-12 |
| C24a | 703-704 | "[subgroup] must [requirement]" or "if [condition] then [requirement]" | TW | 6ffd07c 2026-07-22 |
| C24 | 705-707 | "females of childbearing potential must have negative pregnancy test" → conditional: true (+ women…, warfarin…) | CE (IO) | 6ffd07c 2026-07-22 |
| C25 | 711-712 | "Age >= 18 years. For Iceland only: Age >= 21 years", "ferritin >= 60 (>= 45 for age > 75)" | CE | 623e663 2026-09-12 |
| C26 | 717-718 | (e.g. "Age (general)", "Age (Iceland)") | CE | 623e663 2026-09-12 |
| C27 | 726-731 | WRONG — two separate top-level rules … Age (general) 18.0 / Age (Iceland) 21.0 | CX (SJ) | 4d30ddf 2026-08-23 — values changed to 21.0 in 623e663; prose still says >= 20 |
| C28 | 732-739 | RIGHT — one rule, group_type "ANY", two sub_criteria … | SJ | 4d30ddf 2026-08-23 — values changed to 21.0 in 623e663 |
| C29 | 750 | "(<= 1 year)", "(General)" | CX | e8cb29d 2026-08-24 |
| C30 | 751 | "(Exclusion)", "(Demographics)" | CX | e8cb29d 2026-08-24 |
| C31 | 752-754 | "Orthostatic Hypotension/Postural Dizziness/Syncope" followed by "Postural Dizziness/Syncope on Standing/…" | CX | 623e663 2026-09-12 |
| C32 | 760-762 | "Age >= 18 … Age >= 21 years"; "(on standing, within 3 minutes of upright posture)" | CE | 623e663 2026-09-12 |
| C33 | 767-774 | WRONG — one sentence emitted three times … "…Syncope (within 3 minutes)" … "(General)" | CX (SJ) | 57ca225 2026-08-24 — clinical names replaced in 623e663 |
| C34 | 775-782 | WRONG — the same violation with the suffixes removed … | CX (SJ) | e8cb29d 2026-08-24 |
| C35 | 783-789 | RIGHT … "source_text": "Patients with symptomatic orthostatic hypotension, …" | SJ | 57ca225 2026-08-24 |
| C36 | 790-793 | RIGHT (contrast) — "Ferritin (FERR), ceruloplasmin (CP), or haptoglobin (HP) >= 6 x upper limit of normal" | CE | 623e663 2026-09-12 |

#### THRESHOLD_REVIEW_PROMPT (Step 7) — production — `src/agents/agent1/prompts.py` — 2 rows

| ID | Line | Verbatim | Class | Commit |
|---|---|---|---|---|
| T1 | 801-802 | (a comparator like >, <, >=, <=, a percentage, a lab unit, "x ULN"/"x LLN", a specific number) | TW | dd7e998 2026-08-20 |
| T2 | 803 | (e.g. "informed consent", "type 2 diabetes") | CE | dd7e998 2026-08-20 |

#### THRESHOLD_MATCH_PROMPT (Step 8b) — production — `src/agents/agent1/prompts.py` — 2 rows

| ID | Line | Verbatim | Class | Commit |
|---|---|---|---|---|
| M1 | 836-837 | "ferritin or ceruloplasmin > 4X ULN" means BOTH analytes get that same threshold index | CE | 623e663 2026-09-12 |
| M2 | 838-839 | "... or a serum haptoglobin >= 6.5X ULN" is haptoglobin's own | CE | 623e663 2026-09-12 |

#### PLANNER_SYSTEM_PROMPT — production — `src/agents/planner/prompts.py` — 7 rows

| ID | Line | Verbatim | Class | Commit |
|---|---|---|---|---|
| PS1 | 22 | Lab tests (HbA1c, creatinine, eGFR, ALT, AST, bilirubin, albumin, INR, etc.) | CE | 745ea83 2026-08-27 |
| PS2 | 24-26 | a sub-term "Alanine aminotransferase (ALT) elevation" is `domain: "Measurement"`, not `"Observation"` | CE | 745ea83 2026-08-27 |
| PS3 | 33 | (e.g., "Type 2 Diabetes Mellitus", "Myocardial Infarction") | CE | 6ffd07c 2026-07-22 |
| PS4 | 34 | (e.g., "cardiovascular disease", "significant organ disease") | CE | 6ffd07c 2026-07-22 |
| PS5 | 38 | "cardiovascular disease" is satisfied by any one sub-term | CE | 23570e6 2026-07-28 |
| PS6 | 39 | "no drug abuse" requires alcohol AND opioid AND cannabis to all be absent | CE | 23570e6 2026-07-28 |
| PS7 | 42 | "hypertension" is already specific, "cardiovascular disease" is not | CE | 6ffd07c 2026-07-22 |

#### planner DECOMPOSITION_PROMPT — production — `src/agents/planner/prompts.py` — 7 rows

| ID | Line | Verbatim | Class | Commit |
|---|---|---|---|---|
| PD1 | 62-63 | "impaired adrenal reserve" names no analyte | CE | 623e663 2026-09-12 |
| PD2 | 68-70 | The illustrative line "Ferritin or ceruloplasmin > 4X ULN or a serum haptoglobin >= 6.5X ULN" | CE | 623e663 2026-09-12 |
| PD3 | 76-77 | Decomposing "impaired adrenal reserve" into cortisol, ACTH and aldosterone | CE (IO) | 623e663 2026-09-12 |
| PD4 | 83-86 | "moderate or severe psoriasis" → plaque, erythrodermic, pustular psoriasis … NOT as one "psoriasis" entry | CE (IO+CX) | 623e663 2026-09-12 |
| PD5 | 90 | ("ferritin or ceruloplasmin or haptoglobin") | CE | 623e663 2026-09-12 |
| PD6 | 94 | ("including", "such as", "e.g.") | TW | 45fa9d6 2026-09-10 |
| PD7 | 110-111 | (e.g. "> 4 x ULN", "< 90 ng/mL", ">= 12 mg/dL") | CE | 623e663 2026-09-12 |

#### TOPN_SYSTEM_PROMPT — production — `src/agents/agent2/reranker.py` — 1 rows

| ID | Line | Verbatim | Class | Commit |
|---|---|---|---|---|
| R1 | 52-55 | Example where none fit: "qqzzxx nonexistent clinical term" / Candidates: Myocardial infarction, Acute coronary syndrome / Answer {…} | SJ | b437d20 2026-08-13 — few-shot; candidate line at :54 |

#### Critic (rendered LangChain format_instructions only) — production — `src/agents/agent2/critic.py` — 1 rows

| ID | Line | Verbatim | Class | Commit |
|---|---|---|---|---|
| K1 | 439 | LangChain: {"foo": ["bar", "baz"]} is well-formatted … {"properties": {"foo": …}} is not | SJ (CX) | langchain-core 0.1.53 (library text) — format_instructions passed since 6ffd07c; placeholder at critic.py:274 |

#### IntentSeparator.SYSTEM_PROMPT (NLU router) — production (RAG fallback) — `src/agents/conceptset/nlu_router.py` — 2 rows

| ID | Line | Verbatim | Class | Commit |
|---|---|---|---|---|
| U1 | 79 | "exclude", "without", "no", "but not" | TW | 6ffd07c 2026-07-22 |
| U2 | 80 | (e.g., "TZD" → "Thiazolidinediones") | CE | 6ffd07c 2026-07-22 |

#### NLU router (rendered LangChain format_instructions) — production (RAG fallback) — `src/agents/conceptset/nlu_router.py` — 1 rows

| ID | Line | Verbatim | Class | Commit |
|---|---|---|---|---|
| U3 | 113 | the same LangChain foo/bar/baz block | SJ (CX) | langchain-core 0.1.53 (library text) — format_instructions passed since 6ffd07c; placeholder at nlu_router.py:83 |

#### SYSTEM_PROMPT (Agent 1 free-text `parse()`) — side — `src/agents/agent1/prompts.py` — 10 rows

| ID | Line | Verbatim | Class | Commit |
|---|---|---|---|---|
| S1 | 38 | (e.g., "Type 2 Diabetes", "Metformin") | CE | 6ffd07c 2026-07-22 |
| S2 | 41 | (e.g., "within 3 months") | CE | 6ffd07c 2026-07-22 |
| S3 | 50 | (e.g. "ferritin >= 30 ng/mL", "ceruloplasmin >= 20") | CE | 623e663 2026-09-12 |
| S4 | 54 | ("ferritin > 4x ULN", "ceruloplasmin above 6 times the upper limit of normal") | CE | 623e663 2026-09-12 |
| S5 | 56-58 | "4x ULN" sent as {op: "gt", value: 4.0, unit_text: "ng/mL"} reads as "ferritin above 4 ng/mL"… | CX | 623e663 2026-09-12 |
| S6 | 69 | convert "ticagrelor 90 mg oral tablet" to "ticagrelor" | CE (IO) | 6ffd07c 2026-07-22 |
| S7 | 74 | Pattern A … (e.g., "ferritin 30 ng/mL to 300 ng/mL") | CE | 623e663 2026-09-12 |
| S8 | 77 | Pattern B — Simple threshold (e.g., "ceruloplasmin >= 20") | CE | 623e663 2026-09-12 |
| S9 | 79 | Pattern C — "No prior X" / "Without X" | TW | 6ffd07c 2026-07-22 |
| S10 | 81 | Pattern D — "History of X" | TW | 6ffd07c 2026-07-22 |

#### DECOMPOSITION_PROMPT (Agent 1 free-text `parse()`) — side — `src/agents/agent1/prompts.py` — 8 rows

| ID | Line | Verbatim | Class | Commit |
|---|---|---|---|---|
| D1 | 107-108 | "window": {{"start": -365, "end": 0}}, "value_constraint": {{"op": "gte", "value": 7.0, "unit_text": "%"}} | SJ | 6ffd07c 2026-07-22 — filled values also at 126 |
| D2 | 131-154 | One-shot: "Serum ferritin 30 ng/mL to 300 ng/mL at screening" → PRESENCE ≥30 + ABSENCE ≥300 | SJ (IO) | 623e663 2026-09-12 |
| D3 | 156-181 | One-shot: "Serum ferritin or ceruloplasmin > 4x upper limit of normal" → 2 rules "x ULN" | SJ (IO) | 623e663 2026-09-12 |
| D4 | 184 | For "No prior X" or "without X" | TW | 6ffd07c 2026-07-22 |
| D5 | 190 | (e.g., -365 for 1 year before) | CE | 6ffd07c 2026-07-22 |
| D6 | 193 | ("4x ULN", "below the lower limit of normal") | CE | 623e663 2026-09-12 |
| D7 | 196 | (e.g., "7-10%") | CE | 6ffd07c 2026-07-22 |
| D8 | 201 | remove phrases like "a need for", "concomitant therapy with", "history of", "treatment with" | TW | 6ffd07c 2026-07-22 |

#### Single-select reranker `_DOMAIN_GROUNDING_INSTRUCTION` — side (no caller) — `src/agents/agent2/reranker.py` — 4 rows

| ID | Line | Verbatim | Class | Commit |
|---|---|---|---|---|
| R2 | 18 | MI = Myocardial Infarction, TIA = …, CHF, CKD, CAD, PAD, CVA expansions | CE | 6ffd07c 2026-07-22 |
| R3 | 19 | GLP-1 = …, DPP-4 = …, SGLT2 = … | CE | 6ffd07c 2026-07-22 |
| R4 | 20 | HbA1c = Hemoglobin A1c, eGFR = …, LDL = … | CE | 6ffd07c 2026-07-22 |
| R5 | 21 | For example, "MI" in the Condition domain must NOT match "milia" (a skin condition) | CX | 6ffd07c 2026-07-22 |

#### Single-select reranker (rendered LangChain format_instructions) — side (no caller) — `src/agents/agent2/reranker.py` — 1 rows

| ID | Line | Verbatim | Class | Commit |
|---|---|---|---|---|
| R6 | 136 | the same LangChain foo/bar/baz block | SJ (CX) | langchain-core 0.1.53 (library text) — format_instructions passed since 6ffd07c; placeholder at reranker.py:96; also :248 |

#### Comparator `_CLASSIFY_PROMPT` — side — `src/agents/comparator/recommender.py` — 1 rows

| ID | Line | Verbatim | Class | Commit |
|---|---|---|---|---|
| CM1 | 67 | "caveat": "<=12 words, e.g. a heart-failure signal" | CE | d26a73e 2026-07-23 |

#### Comparator `_LIT_EXTRACT_PROMPT` — side — `src/agents/comparator/recommender.py` — 1 rows

| ID | Line | Verbatim | Class | Commit |
|---|---|---|---|---|
| CM2 | 217 | (e.g. an acute parenteral drug standing in for a chronic oral one) | CE | d26a73e 2026-07-23 |

#### TTE report narrative `system_prompt` — side — `src/services/tte_service.py` — 5 rows

| ID | Line | Verbatim | Class | Commit |
|---|---|---|---|---|
| TS1 | 9786-9787 | Do NOT use words like "trend", "promising", or "suggests benefit" | CX | 6ffd07c 2026-07-22 |
| TS2 | 9788-9789 | do NOT say "trend toward". Say "not statistically significant" and "estimate is imprecise" | CX | 6ffd07c 2026-07-22 |
| TS3 | 9793-9794 | Do NOT use causal language ("caused", "prevents", "leads to") — use "associated with", "estimated effect" | CX | 6ffd07c 2026-07-22 |
| TS4 | 9799 | Do NOT write 'assumed similar' for outcome — write 'not verified' | CX | 6ffd07c 2026-07-22 |
| TS5 | 9802-9803 | do NOT write 'associations, not causal effects'. Instead write: 'causal interpretation is not supported because …' | CX | 6ffd07c 2026-07-22 |

#### TTE report narrative `prompt` — side — `src/services/tte_service.py` — 2 rows

| ID | Line | Verbatim | Class | Commit |
|---|---|---|---|---|
| TS6 | 9828 | (e.g., 'short-horizon emulation, not full replication') | CE | 6ffd07c 2026-07-22 — non-clinical example |
| TS7 | 9900 | (longer follow-up, sensitivity analyses, etc.) | CE | 6ffd07c 2026-07-22 — non-clinical example |

#### Threshold classifier `_HEAD_RULES` — side (scripts only) — `src/agents/agent1/threshold_classifier.py` — 1 rows

| ID | Line | Verbatim | Class | Commit |
|---|---|---|---|---|
| TC1 | 94-95 | Do NOT supply "age" as a head for a bare unit. If the text does not say age/aged/years old… | TW | d1747e0 2026-07-29 |

#### Threshold classifier taxonomy system prompt — side (scripts only) — `docs/daily_notes/tte_value_taxonomy.prompt.txt` (whole file added in d1747e0) — 66 rows

| ID | Line | Verbatim | Class | Commit |
|---|---|---|---|---|
| TX1 | 8 | destroys lines like 'ALT, AST, or alkaline phosphatase > 3x ULN' (+ "only 62% of value constraints") | CE (HP) | d1747e0 2026-07-29 |
| TX2 | 24 | 12 corpus lines carry more than one threshold. | HP | d1747e0 2026-07-29 |
| TX3 | 32-148 | "(corpus n=88)" … "(corpus n=12)" on all 9 class headers | HP | d1747e0 2026-07-29 — grouped row: 9 class headers (lines 32,52,67,82,95,108,122,136,148) |
| TX4 | 33 | A time unit (msec, years) or a dimensionless index (INR) | CE | d1747e0 2026-07-29 |
| TX5 | 36 | (ALT, AST, bilirubin, creatinine, TSH, HbA1c, INR, ANC, platelets, hemoglobin, AFP, NT-proBNP, HBsAg, calcitonin) | CE | d1747e0 2026-07-29 |
| TX6 | 37 | (systolic/diastolic blood pressure, heart rate, LVEF, QTc, mitral valve area, ST-segment elevation) | CE | d1747e0 2026-07-29 |
| TX7 | 38 | The head is a body metric (body weight, BMI). | CE | d1747e0 2026-07-29 |
| TX8 | 39 | (ULN, LLN, upper/lower limit of normal, institutional ULN) | TW | d1747e0 2026-07-29 |
| TX9 | 40 | (mg/dL, mmol/L, g/L, /mm3, 10^9/L, mmHg, mL/min, mL/min/1.73m2, ng/mL, pg/mL, IU/mL, mV, msec, %) | TW | d1747e0 2026-07-29 |
| TX10 | 42 | Do not choose it when: … graded clinical scale (ECOG, Child-Pugh, dipstick protein) -> SCORE_GRADE | CX | d1747e0 2026-07-29 |
| TX11 | 47 | … a ValueAsNumber on the same value leaves defect #10 intact | HP | d1747e0 2026-07-29 |
| TX12 | 48 | e.g. 'above 3 x upper limit of normal (ULN)' in '2. Indication of liver disease … (ALT) …' | CE | d1747e0 2026-07-29 — corpus line |
| TX13 | 49 | e.g. '\\> 470msec' in '10. Resting ECG with QTc \\> 470msec on 2 or more time points …' | CE | d1747e0 2026-07-29 — corpus line |
| TX14 | 50 | e.g. '≥ 2.5 mg/dL' in '3. Creatinine ≥ 2.5 mg/dL' | CE | d1747e0 2026-07-29 — corpus line |
| TX15 | 53 | 'Men with age >= 18 years' is a Value … ('patients who are at least 18 years old') | CE (HP) | d1747e0 2026-07-29 |
| TX16 | 56 | An explicit 'age' / 'aged' / 'years old' head. | TW | d1747e0 2026-07-29 |
| TX17 | 58 | ('age >= 18 years at screening') | CE | d1747e0 2026-07-29 |
| TX18 | 60 | A time unit whose head is a measurement (QTc in msec) -> MEASUREMENT_VALUE | CX | d1747e0 2026-07-29 |
| TX19 | 63 | The corpus 'expect' for abs-years-age carries unit_concept_id 9448 (year)… | HP | d1747e0 2026-07-29 |
| TX20 | 64 | e.g. '\\>= 18 years' in '4. Age \\>= 18 years' | CE | d1747e0 2026-07-29 — corpus line |
| TX21 | 65 | e.g. '=\\> 70 years' in '3. Pre-existing cardiovascular disease OR specified diabetes end-organ damage OR age =\\> 70 …' | CE | d1747e0 2026-07-29 — corpus line; CAROLINA (NCT01243424) text |
| TX22 | 71 | within / prior to / before / after / since / in the past N days\|weeks\|months\|years | TW | d1747e0 2026-07-29 |
| TX23 | 72 | A named anchor: randomization, first dose, screening, ICF, enrollment, Day -1, index date | TW | d1747e0 2026-07-29 |
| TX24 | 73 | The head is an event (a donation, a stroke, a dose) | CE | d1747e0 2026-07-29 |
| TX25 | 76 | attributive modifier of a procedure name ('24-hour urine collection') -> NON_CRITERION | CX | d1747e0 2026-07-29 |
| TX26 | 78 | Only 3 corpus instances carry this class … ('since transplant', 'post-MI', 'from the time of diagnosis') | HP (CE) | d1747e0 2026-07-29 |
| TX27 | 79 | e.g. '=\\< 3 months' in '20. stroke or Transient Ischemic Attack (TIA) =\\< 3 months prior to ICF' | CE | d1747e0 2026-07-29 — corpus line |
| TX28 | 80 | e.g. 'within 48 hours' in '16\\. Consumption of excessive amounts of tea, coffee, or caffeine…' | CE | d1747e0 2026-07-29 — corpus line |
| TX29 | 84 | Gold uses this exact shape 28 times. | HP | d1747e0 2026-07-29 |
| TX30 | 86 | A stative head: long-standing, stable, unchanged, ongoing, duration of, since diagnosis | TW | d1747e0 2026-07-29 |
| TX31 | 91 | Chia's Temporal requires a Reference_point … TrialGenie's Value definition absorbs 'the duration of drugs' | HP | d1747e0 2026-07-29 |
| TX32 | 92 | e.g. '(\\>5 years)' in 'HIV positive participants … long-standing (\\>5 years) HIV …' | CE | d1747e0 2026-07-29 — corpus line |
| TX33 | 93 | e.g. 'at least 8 weeks' in '3. Stable antidiabetic background medication (unchanged daily dose) for at least 8 weeks …' | CE | d1747e0 2026-07-29 — corpus line; CARMELINA (NCT01897532) text |
| TX34 | 99 | A drug or drug-class name adjacent to the number (prednisolone, insulin, 'or equivalent') | CE | d1747e0 2026-07-29 |
| TX35 | 100 | A dose unit (mg, mg/kg, mg/day, IU) attached to a drug | TW | d1747e0 2026-07-29 |
| TX36 | 101 | Dosing verbs: receiving, taking, treated with, on a stable dose of | TW | d1747e0 2026-07-29 |
| TX37 | 103 | The unit is a concentration in a specimen (mg/dL, ng/mL) -> MEASUREMENT_VALUE | CX | d1747e0 2026-07-29 |
| TX38 | 105 | src/agents/agent3/mappings.py maps 'mg' to concept 8587, which is millilitre… | HP | d1747e0 2026-07-29 |
| TX39 | 106 | e.g. '≤ 30 mg' in 'Receiving immunosuppressive medication, except for ≤ 30 mg prednisolone or equivalent …' | CE | d1747e0 2026-07-29 — corpus line |
| TX40 | 109 | a named clinical scale … (ECOG, dipstick protein, Child-Pugh, NYHA) … ('points', '+') | CE | d1747e0 2026-07-29 |
| TX41 | 110 | Ordinal labels ('2+ on dipstick', Child-Pugh B/C) | CE | d1747e0 2026-07-29 |
| TX42 | 112 | A named scale precedes the number: ECOG, WHO performance status, Child-Pugh, NYHA, mRS, Karnofsky | CE | d1747e0 2026-07-29 |
| TX43 | 113 | A scale word stands where a unit would be: 'points', 'grade', 'class', a trailing '+' | TW | d1747e0 2026-07-29 |
| TX44 | 114 | The scale's range is small and bounded (0-5) | CE | d1747e0 2026-07-29 |
| TX45 | 119 | e.g. '≤ 2' in '7. ECOG performance status ≤ 2;' | CE | d1747e0 2026-07-29 — corpus line |
| TX46 | 120 | e.g. '≥ 2 + protein on dipstick' in 'Proteinuria, as demonstrated by urine dipstick …' | CE | d1747e0 2026-07-29 — corpus line |
| TX47 | 126 | A countable clinical noun follows the number: lines of therapy, cycles, prior regimens, transfusions | CE | d1747e0 2026-07-29 |
| TX48 | 127 | The head is an event verb phrase: donated, lost, received, administered | TW | d1747e0 2026-07-29 |
| TX49 | 128 | ('blood donation > 500 mL') | CE | d1747e0 2026-07-29 |
| TX50 | 132 | Both instances have laboratory-looking shapes ('> 500 mL', '> 8') … 'volume of blood donated' or 'number of therapy lines' | HP (CE) | d1747e0 2026-07-29 |
| TX51 | 133 | e.g. '\\> 500 mL' in '21. Receipt of blood products within 2 months prior to Day -1, …' | CE | d1747e0 2026-07-29 — corpus line |
| TX52 | 134 | e.g. '\\> 8 lines' in '1. Treatment with \\> 8 lines of systemic therapies prior to enrollment …' | CE | d1747e0 2026-07-29 — corpus line |
| TX53 | 140 | (cups of coffee per day, packs per day, drinks per week) | CE | d1747e0 2026-07-29 |
| TX54 | 146 | e.g. 'more than 8 cups per day' in '16\\. Consumption of excessive amounts of tea, coffee …' | CE | d1747e0 2026-07-29 — corpus line |
| TX55 | 155 | 'the upper boundary of the two-sided 95.02% confidence interval was less than 1.3' has the same surface shape as 'above the upper limit of normal' | CX | d1747e0 2026-07-29 |
| TX56 | 157 | confidence interval, CI, upper/lower boundary, margin, noninferiority, alpha level, two-sided, one-sided, hazard ratio | TW | d1747e0 2026-07-29 |
| TX57 | 161 | N - M with a shared unit, or 'between N and M', often followed by 'inclusive' | TW | d1747e0 2026-07-29 |
| TX58 | 170 | The number sits before a procedure noun with a hyphen ('24-hour urine collection') | CE | d1747e0 2026-07-29 |
| TX59 | 173 | one, two, three ... with no digit in the span | TW | d1747e0 2026-07-29 |
| TX60 | 175 | this will not apply to, except for, unless, with the following exception | TW | d1747e0 2026-07-29 |
| TX61 | 178 | A scale name followed by letters or classes (Child-Pugh B/C, NYHA III/IV) | CE | d1747e0 2026-07-29 |
| TX62 | 179 | e.g. 'upper boundary of the two-sided 95.02% confidence interval was less than 1.3' in 'the primary outcome …' | CE | d1747e0 2026-07-29 — corpus line |
| TX63 | 180 | e.g. '(\\>13.3 mmol/L)' in '1. Uncontrolled hyperglycaemia with a glucose level \\>240 mg/dl (\\>13.3 mmol/L) …' | CE | d1747e0 2026-07-29 — corpus line |
| TX64 | 182-205 | COMPARATOR SPELLINGS table: '\\>' -> gt n=29 … 'above', 'below', 'more than', 'at least', … 'times higher than' | TW (HP) | d1747e0 2026-07-29 — comparator-spellings table with corpus n= counts |
| TX65 | 204 | '5 times higher than the ULN' is read by the corpus as gt 5.0 | CE | d1747e0 2026-07-29 |
| TX66 | 207-216 | NOTATION n= counts … 'below the lower limit of normal' … 'G/l is giga-per-litre, g/l is gram-per-litre' | HP (CE) | d1747e0 2026-07-29 — NOTATION block with corpus n= counts |

## 3. Counts

| Prompt | Rows | CE | CX | TW | HP | SJ |
|---|---|---|---|---|---|---|
| NCT_SYSTEM_PROMPT | 46 | 21 | 11 | 10 | 3 | 1 |
| NCT_DECOMPOSITION_PROMPT | 37 | 19 | 9 | 4 | 0 | 5 |
| THRESHOLD_REVIEW + MATCH | 4 | 3 | 0 | 1 | 0 | 0 |
| PLANNER_SYSTEM + planner DECOMPOSITION | 14 | 13 | 0 | 1 | 0 | 0 |
| TOPN reranker | 1 | 0 | 0 | 0 | 0 | 1 |
| Critic (LangChain only) | 1 | 0 | 0 | 0 | 0 | 1 |
| NLU router | 3 | 1 | 0 | 1 | 0 | 1 |
| **Production total** | **106** | 57 | 20 | 17 | 3 | 9 |
| Free-text SYSTEM + DECOMPOSITION | 18 | 10 | 1 | 4 | 0 | 3 |
| Single-select reranker | 5 | 3 | 1 | 0 | 0 | 1 |
| Comparator | 2 | 2 | 0 | 0 | 0 | 0 |
| Report narrative | 7 | 2 (non-clinical) | 5 | 0 | 0 | 0 |
| Classifier `_HEAD_RULES` + taxonomy | 67 | 36 | 5 | 16 | 10 | 0 |
| **Side total** | **99** | 53 | 12 | 20 | 10 | 4 |
| **Grand total** | **205** | 110 | 32 | 37 | 13 | 13 |

Commits behind the 106 production rows:

- 623e663: 54
- 6ffd07c: 27
- 8bbd50d: 4
- 738be93: 3
- e8cb29d: 3
- 4d30ddf: 2
- 57ca225: 2
- dd7e998: 2
- 745ea83: 2
- 23570e6: 2
- LangChain library text: 2
- d2f2e0b: 1
- 45fa9d6: 1
- b437d20: 1

## 4. Gaps (not traced)

- `scripts/prompt_ab.py`, `example_value_ab.py` and `planner_example_ab.py` send whatever prompt file is named on the
  command line; that content is not in HEAD and was not inventoried.
- `scripts/probe_criterion_classifier.py` renders the taxonomy prompt through `build_value_taxonomy.py --prompt`; a test
  reportedly asserts it is byte-equal to the checked-in prompt.txt — not run here. Its INSTRUCTION_TAIL repeats TC1.
- Script-local prompts in `quick_concept_benchmark.py:175` and `quick_concept_benchmark_v2.py:739` were read and contain
  no examples. `tests/` was not inventoried.
- Runtime data inserted into prompts (criterion lines, `[value_constraint]` annotations, candidate concept lists, PubMed
  findings, report statistics) was treated as data, not as examples.
- Borderline items not counted: prescribed markers `"x ULN"` / `"x LLN"`, default window values, the critic's retrieval
  labels ("sibling", "ancestor", "seed"), the planner's vocabulary list (SNOMED CT, ICD-10, RxNorm, LOINC), the
  comparator's "(prior emulations, comparative-effectiveness studies, methods papers)", the empty-answer JSON at
  reranker.py:50.

## Needles in the JSON companion

- Each object's `needle` is a verbatim substring of `file` at ec0cf51 that occurs there exactly once
  (`needle_count: 1`), except TX3 (below).
- 22 examples share their exact text with a twin in the same file (SYSTEM_PROMPT vs NCT_SYSTEM_PROMPT, and the two
  free-text/NCT decomposition prompts). For those, `needle` was widened line by line around the example until it was
  unique without swallowing any other row's text; the bare example text is kept in `core_needle` with `core_count`
  (2 at HEAD). Removing such an example drops `core_count` by one; a widened needle can also disappear if only its
  context lines change, so check `core_count` as well.
- TX3 is one grouped row covering nine `(corpus n=…)` class headers; its needle `(corpus n=` occurs 9 times
  (`multi_occurrence: 9`) and cannot be made unique as a single row.
- K1, U3 and R6 (LangChain format instructions) have `rendered_only: true`: `file`/`line` point at the call site and the
  needle is the text as it appears in the rendered prompt, not in the repository.
