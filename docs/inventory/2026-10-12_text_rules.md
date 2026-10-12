# Text-rule inventory — `src/` and the delivery gate (2026-10-12)

Repo state: HEAD `ec0cf51`. Machine-readable twin: `docs/inventory/2026-10-12_text_rules.json`.

**Inventory complete. `src/` plus the two gate files hold 30 on-path Class A rows (29 distinct rule sources), 9 document-segmentation rules, 10 off-path or dead Class A groups, 10 Class C rules and about 140 Class B items.** Both known violations are live in the current candidate, not dead code.

(After this report was written, `src/services/emission_stability.py` was added as off-path entry D11 during the file reconciliation for the JSON twin: a measurement-only module whose description word lists decide nothing in a delivered artifact. Total off-path/dead groups: 11.)

**Repo:** `/home/bilab/work/projects/Broadsea/.worktrees/artemis-0923-reply` @ `ec0cf51`. Paths below are relative to that root.

**How "what breaks" was measured.** The candidate is `output/site_gap/2026-10-12_prompt_f2`, built from code `d7dc2bb`. `git diff d7dc2bb ec0cf51 -- src scripts/verify_circe_delivery.py` is empty, so the line numbers below apply to the candidate. Firing counts come from three sources:
- its `rebuild.log` and `export.log`;
- its 12 `DELIVERY/*.circe.json` files;
- running the pure rule functions directly on its `store/studies.json` (read-only, no LLM, no DB).

**The candidate is a dry rebuild.** `rebuild_driver.py` runs process_eligibility and apply only; Agent 1, the planner and segmentation were not re-run. Deleting a rule from those stages changes nothing in this candidate until the next reingest. For those rows I report the effects frozen in the store instead. All 12 candidate files already FAIL the gate.

## Things that contradict or extend the brief
- **The IR already has an LLM-filled `conditional: bool`** (`src/models/ir.py:222`, Agent 1 prompt Pattern F). `_criteria_from_ir` (`tte_service.py:12234`) drops `conditional` rows silently: no `_skippedCriteria` record and no span. This overlaps RFC-015's `record_requirement=conditional`. `dose_stability` exists because the model did not set it on CARMELINA inclusion 7.
- `dose_stability` reads `description`+`sourceText`, not `protocolLine`.
- `entity_exception` has a fifth caller beyond the RFC's four: `entry_exclusion_repair` reads the CIRCE rule *name*. In this candidate it fires on EMPA-REG rule #15.
- A1 is notation-only (`<=`, `≤`, `N–M`), with one word ("to").
- A20 (the analyte→unit table) currently changes nothing in this candidate: 0 bounds propagate through it and 2 strand. Deleting it reproduces today's output for this store.

## 1. Class A — reads protocol or criterion language to decide meaning (on the delivery path)
"Reingest" = runs only on reingest, not in the dry-rebuild candidate.

| # | file:line | symbol | words / pattern (abridged) | input | decides | call sites | delivery path | introduced | replacement without a rule | if deleted (candidate) |
|---|---|---|---|---|---|---|---|---|---|---|
| **Agent 1 parsing/repair** |
| A1 | agent1/parser.py:137,145,161,1571 | `_INCLUSIVE_UPPER_OP`,`_RANGE`,`inclusive_upper_bounds` | `<=`,`=<`,`≤`,`≦`; `N - M`/`N to M` | IR `source_text` | rewrites inclusion ABSENCE `gte X`→`gt X` | parser.py:1483,1643 | reingest | 9ec4b3a 2026-09-11 | `value_constraint` + LLM `bound_span` (substring check) | none now; 3 stored rows revert on reingest (EMPA-REG 2, CARMELINA 1) |
| A2 | parser.py:2014-2056,2260 | `_PATTERN_E_CLUSTERS`,`_match_cluster`,`_repair_pattern_e` | stemi, nstemi, unstable angina, mi, stroke, tia, cabg, coronary, heart failure, ckd, microalbuminuria, hypertension, lvh, abi, egfr, diabetes, t2dm, obesity… | `entity_text`+`name` | merges ≥2 flat inclusion rules into an ANY group | parser.py:1503 | reingest | 6ffd07c 2026-07-22 (repo baseline) | RFC-014 `relation`+`relation_span`; Agent 1 `group_type`/`sub_criteria` already exist | none now; 3 labels, 12 demoted members in store (LEADER 9, PLATO 3; neither is in the 3-study default) |
| A3 | parser.py:2448-2470 | `_normalize_drug_entity_text` | strip `(…)`; trailing `or other <w>…` | Drug `entity_text` | mapper seed | parser.py:2382 | reingest | 6ffd07c | none needed (`entity_text` is already the bare entity) | none now; not measured |
| A4 | agent1/temporal_grounding.py:39-100,136,236; parser.py:1682,1772,190 | `_UNIT_DAYS`,`_OLDER_THAN`,`_INTERVAL`,`_BACKWARD`,`_FORWARD`,`_AGE`,`_CLAUSE_BREAK`,`_MAX_ANCHOR_GAP`,`_direction`; `re.search(r"[0-9]")` | prior, previous, before, within, last, past, ago, since, history, screening, randomization, consent, baseline, index, for at least / next, following, planned, expectancy, after, post, follow-up / >, more than, greater than, longer than / age, aged, old | `source_text`+`name` | rewrites or drops windows (start/end, older-than shape) | parser.py:1524-1534 | reingest | a2ecba6 2026-09-12 | RFC-014 `timing` + LLM `window` with `window_span` substring check; keep N×unit→days (B) | none now; 7 regrounded windows in store (CAROLINA 5, CARMELINA 2) |
| A5a | services/value_constraint.py:945,953-971,980,1063,1246 | `_BOUND_RE`,`_COMPARATOR_SPELLINGS`,`_MULTIPLIER_FILLER`,`_PHRASE_SPLIT_RE`, parenthesised-aside rule | upper/lower limit of normal, ULN/LLN; greater/less/higher/lower/more than, at least/most, no more/less than, up to, above/below; filler: times, fold, institutional, local, central, site…; split on `;`, and/or, or, and, `,` | protocol line (Agent 1 prompt annotation, Step 6 count, Step 8a/8b reattach); planner `value_constraint_text` | op, value, ULN multiplier, constraint count | parser.py:576,590,784,814; decomposer.py:408 | reingest | 114af5a 2026-07-29 | Agent 1/planner already emit structured `value_constraint`; add `threshold_span` | none now; deleting changes the Agent 1 prompt, so the IR cache key changes (~132 min re-extraction) and Step 8a/8b re-attachment disappears |
| A5b | value_constraint.py:936,989-1012,1030,1057 (`_is_unmeasurable`, `is_item_count`) | `_STATISTICAL_MARKER_RE`,`_WINDOW_UNITS`+`_RELATIVE_TIME_ANCHOR_RE`,`_DURATION_MARKER_RE`,`_ANATOMIC_SEVERITY_RE`,`_DOSE_CONTEXT_RE`,`_ITEM_COUNT_UNIT_RE` | confidence interval, boundary, two-sided, margin, hazard ratio, non-inferiority; within, prior to, before, after, since, ago; duration, consecutive, life expectancy, long-standing; stenosis, narrowing, occlusion, luminal; dose, dosing, treated with, receiving, taking, daily; `^of` | same as A5a, plus stored `unitText` | rejects a threshold (criterion carries no value) | as A5a; value_constraint.py:908 | reingest; item-count also in build | 114af5a / 738be93 2026-09-10 / 864e0b8 2026-09-10 | LLM `quantity_kind` + span (not in schema) | none measured |
| A6 | agent1/pubmed_fetcher.py:516-748 (573,595) | `_collapse_hierarchical_groups`: `_header_trigger`,`_all_quantifier` | ≥1, at least one…five of, one or more of, either of, any (one) of the following/below/listed; all/each/both of | PDF/paper eligibility text | collapses header + children into one `[OR-GROUP]` criterion | pubmed_fetcher.py:766 ← `extract_eligibility_from_text` ← parser | reingest | 6ffd07c / c261759 2026-09-11 | RFC-014 relation + cardinality at extraction | none now; 7 store rows carry `[OR-GROUP]` lines |
| A7 | agent1/criteria_dedup.py:89,112,156,160 | `_STOPWORDS`,`_NEGATORS`,`_CONJUNCTION_MARKER`,`_DISJUNCTION_MARKER` | ~70 stopwords; no, not, without, absence, free, never, non, excluding, lack…; and, plus, as well as, combined with, together with, in addition to, concomitant; or, either, any of | merged criterion strings | DROP/KEEP a criterion as a duplicate | `structural_verdict` ← enricher.py, pubmed_fetcher `_merge_parsed_items` | reingest | ab91c60 2026-08-09 | LLM judge arm exists (`criteria_dedup_judge.py`, off path) | not measured |
| **Planner** |
| A8 | planner/decomposer.py:99-187 (160,174) | `_exception_kept_whole` (uses A11) | builds "X other than Y" | name, entity_text, source_text, LLM members | declines a split; rewrites `entity_text` | decomposer.py:350 | reingest | d0ee924 2026-09-12 | RFC-015 `excepted_entities` | none now |
| A9 | utils/naming_words.py:32 (decomposer.py:93-94 gate 2; circe_lint.py:3950) | `FUNCTION_WORDS` | or, of, and, the, a, an, in, with, to, for, by, on, at, as, is, are, be, not, no, any, other, due, from | LLM `source_span` vs member text; protocolLine vs description, sourceText, conceptSetName | keeps or drops `source_span`; gate (p) | decomposer.py:446; verify_circe_delivery.py:2901 | reingest; gate report-only | 45fa9d6 2026-09-10 (moved ffb2d26 2026-09-12) | this is the verifier: RFC = substring only; dropping gate 2 re-admits the "umbrella span" case (decomposer.py:55-64) | none now (167 store rows carry protocolSpan) |
| **Agent 2 mapping / seed (process_eligibility — runs in the candidate)** |
| A10 | utils/criterion_seed.py:42-97,143 | `_UNIT`,`_MILESTONE`,`_COMPARATOR`,`_TEMPORAL_PATTERNS`,`_DANGLING_EDGE` | (with)in the last/past/previous N unit; for (at least) N unit; N unit prior to <randomization, screening, enrolment, baseline, index, consent, first dose, visit…> | `sourceText`→`description` | strips temporal qualifier from the mapper seed | tte_service.py:5680,7290; criterion_seed.py:236 | yes | 738be93 2026-09-10 | mandatory `entity_text` (exists); refuse and record instead of stripping | 4 seeds change: PLATO incl "…onset in previous 24 hours…", CARMELINA incl 7, CARMELINA excl "CABG within 2 months prior to consent", CAROLINA "cancer … within last 3 years" |
| A11 | services/entity_exception.py:51-96,132,173 | `_CONNECTIVE`,`_PARENTHESISED`,`_ADJACENT`,`_TRAILING_WINDOW`,`_ANAPHORIC_HEAD/_WORD`,`_SPLIT_STOPWORDS`,`_LEADING_CONJUNCTION`,`_GROUP_LABEL_JOIN`; `detect_entity_exception`,`description_stated_exception` | other than, except (for), excluding, apart from, but not, exclusive of; above, following, specified, allowed, these… | seed, `description`, rule `name` | base + excepted → `isExcluded` subtraction | tte_service.py:7297,8595; decomposer.py:160,174; entry_exclusion_repair.py:398 | yes | c75085c 2026-09-12; c588aa7 2026-10-07 | RFC-015 `excepted_entities` | 5 seeds: EMPA-REG excl 30 loses T2DM exclusion (the 09-23 zero-patient shape); CAROLINA cancer loses 5 appended exclusions; LEADER insulin long-acting (6) and premixed (14) exclusions lost |
| A12 | services/route_qualifier.py:32-84 | `_ROUTE_LEXICON` (15 routes),`_SYSTEMIC_INTENT`,`_SYSTEMIC_NOT_A_ROUTE`,`_LOCAL_INTENT` | oral(ly), by mouth, inject, IV/IM/SC, infusion, inhal, nebuli, topical, cream, ointment, transdermal, patch, vaginal, rectal…; "systemic" unless followed by embol/infection/…/disease | Drug seed | dose-form routes kept → `isExcluded` forms; blocks ATC climb | tte_service.py:8501; drug_class_expander.py:266,513 | yes | 192e306 2026-08-03 (ATC use 239c0b5 2026-10-08) | LLM `route` enum + `route_span` | 7 seeds / 10 rows lose subtraction (LEADER oral anti-diabetics ×4, PLATO oral anticoagulant, EMPA-REG systemic steroids, CAROLINA systemic corticosteroid / patch / oral & injectable contraceptives) |
| A13 | agent2/query_expander.py:46-51 | `_CURATED_EXPANSIONS` | eGFR, NSTEMI, TIA, Stroke → full forms | seed ≤6 chars | rewrites the retrieval query | workflow.py:391; tte_service.py:5667 | yes (`AGENT2_QUERY_EXPAND` defaults true) | ccb8ca8 2026-08-13 | Agent 1 `entity_text` expanded form, or a vocabulary synonym path | 24 expansions revert (eGFR 4, NSTEMI 4, Stroke 8, TIA 8); docstring measured eGFR 0/5 gold bare |
| A14 | agent2/workflow.py:413 | `re.split(r'\s+or\s+')` | " or " | Drug seed | per-part ATC expansion | workflow.py:399-430 | yes | 6ffd07c | Agent 1/planner `sub_criteria` | 0 multi-part ATC hits → no change |
| A15 | agents/conceptset/nlu_router.py:47-59 | `TEMPORAL_KEYWORDS` | history of, prior, previous, currently, within, before, after, at least/most, days, months, years | seed on the RAG fallback | refuses with `intent-unparsed` | recommender.py:156 ← tte_service.py:8845, raised at 8874 | yes (fallback) | 6ffd07c | none needed | 0 `intent-unparsed` → no change |
| A16 | services/tte_service.py:660-893 | `_seed_is_unmappable_placeholder` + `_PLACEHOLDER_ORDINAL_STEMS`, `_PLACEHOLDER_ORDINAL_PREFIXES`(cv, cvd, sub), `_DOCUMENT_POINTER_WORDS`, `_TALLIED_PLACEHOLDER_NOUNS`, `_BARE_QUALIFIERS`, `_UNMAPPABLE_DRUG_CATEGORIES`, `_DRUG_CATEGORY_TRAILING_FILLER` | risk factor N, table/appendix/figure + id, conditions count, contraindication, investigational drug/product/agent, study drug/medication, use | seed | `unmappable-placeholder` (the only refusal code the gate permits); also refuses seeds that did map | tte_service.py:936,1006,8888 | yes | 16ff3fc 2026-09-09; da8e7a8, 1e6ec58 2026-09-10 | LLM `no_entity`/`refers_elsewhere` + span (not in schema) | 2 refusals lose their permit (ARISTOTLE "Investigational drug use", CAROLINA "Investigational drug"), adding a FAIL reason |
| A17 | services/loinc_specimen.py:68,127,203-219 | `_STATED_CHALLENGES {"fast":"cfst"}`; prefix-4 match of criterion words to LOINC System tokens | "fast…" | seed + `description` | keeps or removes challenge variants and specimens | tte_service.py:7421→7554; circe_lint.py:4064 (gate u) | yes | d97397e 2026-10-08 | LLM `specimen`/`challenge` + span | 37 refinements logged; the `fast` branch's share not determined |
| **TTEService build** |
| A18 | utils/circe_lint.py:3156-3259; services/tte_service.py:490-575 | `_DISJUNCTIVE_CONNECTIVE`,`_LIST_CARDINALITY`,`_CARDINALITY_WORDS`; `list_cardinality`,`states_flat_disjunction`,`_effective_group_expression_type` | or, either; at least N of, N or more of, ≥N of, (any) one (or more) of the following; one…ten | group `protocolLine` | group Type ALL→ANY, →AT_LEAST N | tte_service.py:487,5391; circe_lint.py:3390 (gate o) | yes | 3cf55f6, c0df6db 2026-09-12 | RFC-014 `relation`+`relation_span` (+ cardinality) | LEADER groups 4a712697 and 9a021f8e revert ANY→ALL; 0 AT_LEAST in candidate |
| A19 | services/dose_stability.py:70-111 | `_STABILITY`,`_THERAPY` | stable, unchanged, stabilised, no (dose) change + background, therapy, medication, treatment, dose, dosing, regimen | `description`+`sourceText` | skips an inclusion Drug rule | tte_service.py:5518,5562; verify_circe_delivery.py:1580,1634 | yes | 26119e9 2026-10-07 | RFC-015 `record_requirement`+`conditional_span` (see the existing `conditional` field) | 4 rows re-emitted as DrugExposure PRESENCE, both arms: CARMELINA incl 7, CAROLINA incl 37/38/41 |
| A20 | value_constraint.py:710-858 (+`is_item_count` 1157) | `_ANALYTE_CONVENTIONAL_UNITS`,`_match_analyte`,`check_analyte_unit` | HbA1c spellings, glucose, hemoglobin, platelet, creatinine, eGFR/GFR/CrCl, ALT/SGPT, AST/SGOT, ALP, GGT, bilirubin, cholesterol/LDL/HDL, triglyceride, blood pressure, BMI, troponin | member `sourceText`/`description` | propagate a group-label bound or strand (refuse) the member | tte_service.py:643,7372,12367; assembler.py:638; verify_circe_delivery.py:1423 | yes | 997da1b 2026-09-09 | LOINC Property / unit-dimension check (already in loinc_specimen) | measured: 0 propagated, 2 stranded → no change in this candidate |
| A21 | value_constraint.py:315,423,457 | `_REFERENCE_BOUND_RE`/`split_reference_bound` | x / times the upper/lower limit(s) of normal, ULN/LLN | stored `unitText` (LLM field) | ULN-relative vs absolute bound | `resolve_reference_bound` ← value-filter build | yes | 25c53ac 2026-07-28 | existing `reference_bound` field (needs a store backfill) | 12 store rows hold ULN only in `unitText` (EMPA-REG 2, ARISTOTLE 3, CARMELINA+CAROLINA 4, PLATO 3); they would read as absolute bounds with an unresolvable unit (inferred, not run) |
| A22 | tte_service.py:1236,1256 | `_is_placebo_arm`,`_PLACEBO_ARM_NAMES` | "placebo" substring; sugar pill, sham | arm name | derived (disease-based) comparator | tte_service.py:4788,4795 | yes (export) | 2f1ca57 2026-07-23 | CT.gov `armGroups[].type` (not verified that the store carries it) | 3 placebo comparator builds (LEADER, EMPA-REG, CARMELINA) would treat "Placebo" as a drug |
| A23 | tte_service.py:5239-5276 | `_extract_eligibility_concept_ids_for_outcome` | split on or / and / `,` / `;` + substring match | outcome label vs `description` | outcome-cohort prefetch | tte_service.py:4898,4936 | export payload only | 6ffd07c | none obvious | none on the 12 per-arm files (outcomes are not in DELIVERY) |
| A24 | tte_service.py:12510-12541 | `_parse_description` | compare, vs, versus, compared with/to, against, for, in, among | study description/name | provisional-IR fragments, only when arms/outcomes/eligibility are empty | tte_service.py:11358 (process_eligibility), 11691/11728/11783 | yes (fallback) | 6ffd07c | none needed | not determined; inert by code when the fields are populated |
| **Export repairs** |
| A25 | services/entry_exclusion_repair.py:366-405 | A11 on rule `name`/`description` | (A11) | CIRCE rule name | triggers the residual-after-exception repair | tte_service.py:7976 | yes | 686c9cb 2026-09-17 | RFC-015 `excepted_entities` | fires on EMPA-REG rule #15 'Endocrine disorder (excluding T2DM)' (2 log lines); output effect not determined |
| A26 | services/range_disjunction_repair.py:97 | `_BOUND_LANGUAGE` | at least/most, no more/less than, greater/less/more than, or equal to, up to, and, to, above, below, over, under, from, between, numbers, symbols | rule-name halves split on " + " | collapse ANY of two bounds into one `bt` | tte_service.py:7980 | yes | 4bf73ec 2026-09-18 | structural: same store group/protocolLine + closure check | 0 applied |
| A27 | services/restated_absence_repair.py:159-180 | `_DIRECTION_LOW/_HIGH`,`_LIMIT_NOUNS` | below, lower, less, under, min, floor / above, upper, higher, greater, exceed, max, ceiling / limit, bound, threshold, range, value, cutoff | rule-name halves | remove a complementary absence | tte_service.py:7989 | yes | 37d519c 2026-09-19 | structured ops already present | 0 applied (`_restatedAbsenceRemovals` empty in all 12 files) |
| A28 | utils/circe_lint.py:1806-1896 | `CONFUSABLE_ANALYTES.states/also_states_other` | ldl / low-density vs hdl; a1c / glycated haemoglobin vs HbA1 / A1 total; systolic vs diastolic | concept-set `name` | removes member 3007070/3005446/40758413 (repair) and FAILs (gate) | confusable_member_repair.py:158 ← tte_service.py:7996; verify_circe_delivery.py:2730 | yes | f42a7c7 2026-09-18 | LOINC `Has component` of the set's own members | 12 removals of 3005446 from HbA1c sets revert; gate loses 2 ARISTOTLE SBP findings |
| **Gate/lint** |
| A29 | circe_lint.py:1046,1066 | `_BOUND_ASSERTION_RE` | elevated, raised, increased, decreased, reduced, depressed, abnormal, impaired, uncontrolled, level(s), ULN, LLN, `<>≤≥` | concept-set name + rule name | gate (j) FAIL | verify_circe_delivery.py:2638 | yes | 0e410be 2026-09-09 | Agent 1 `threshold_span` verified, then FAIL if no value filter emitted | 4 findings vanish (CARMELINA UACR ×2, "Elevated HbA1c" ×2) |

Gate rows that reuse sources above:
- (o) conjoined disjunction = A18, 0 findings.
- confusable = A28, 2 findings.
- (u) specimen = A17 + C3, 0 FAIL.
- (p) ungrounded = A9, report only.
- dose-stability permit re-judgement = A19.
- stranded-group re-judgement = A20 + A5b (4 "stranded" mentions in `gate_final.txt`).

**Segmentation rules** (Agent 1, before the LLM; decide which text becomes a criterion line). All run on reingest only. No replacement is obvious beyond an LLM section/boundary pass returning spans checked as substrings.

| # | file:line | words / pattern | introduced |
|---|---|---|---|
| S1 | agent1/eligibility_section.py:27-46,149-183 | headings: (key/main/major/study) inclusion and exclusion / eligibility / inclusion / exclusion criteria, criteria for inclusion; prefixes appendix/section/table/part/annex; terminators: Figure/Table S#, Clinical event definitions, Definitions of clinical, Analysis/Methods/Results/References/Discussion/Sensitivity, Supplementary | ef28410 2026-09-07 |
| S2 | pubmed_fetcher.py:432-490 | criteria_keywords; `_section_end` (conclusion, result, discussion, statistical, definition, endpoint, study procedure/design, appendix, reference, supplement, figure, randomization, treatment period, follow-up…); eligible / ineligible / excluded patients/subjects/if | 6ffd07c |
| S3 | pubmed_fetcher.py:832-953 | plain-mode split on `;`, `, and`, `, or`, `,`; header filter including sponsor names (bristol, astra, pfizer, novo, merck, sanofi, bayer, lilly, boehringer); leading and/or stripped | 6ffd07c |
| S4 | pubmed_fetcher.py:141,243 | `_HEADING_LINE_PREFIX`, `_SECTION_HEADER_RE` | 08d2522 2026-08-04 |
| S5 | pubmed_fetcher.py:1004 | `_FLOW_ROW_RE` | 31126e4 2026-09-07 |
| S6 | pubmed_fetcher.py:290,300 | stranded superscript rejoin (rewrites criterion text) | e8daa37 2026-09-12 |
| S7 | agent1/nct_fetcher.py:218-266 | "(exclusion\|non-inclusion) criteria" split, bullets, " - " | 6ffd07c |
| S8 | agent1/pmc_fetcher.py:17-31,139-185 | ELIGIBILITY_KEYWORDS / METHODS_KEYWORDS | 6ffd07c |
| S9 | parser.py:884-891,1024-1026 | PDF filename role (appendix/supp/protocol); "Downloaded from", "Copyright ©" lines | 6ffd07c |

**Off-path or dead Class A** (10 groups in the report; D11 added at reconciliation):
- `threshold_classifier.py:148,159` `_COMPARATOR`/`_AGE_WORDS`: reached only from `scripts/eval_threshold_classifier.py`; production imports only `deescape`.
- `rule_extractor.py`: fast path is dead. `workflow.py:487` forces "slow" and `process_batch` has no caller.
- `complexity_router.py` COMPLEX_PATTERNS/AMBIGUOUS_TERMS: `route()` runs, but its result is overwritten at `workflow.py:487`.
- `workflow.py:479` `_DRUG_CLASS_PATTERNS`: its use is commented out.
- `tte_service.py:9052` `_infer_placeholder_seeded_domain`: dead, because `_should_use_placeholder_seeded_mapping` always returns False.
- `tte_service.py:1124-1142` STRUCTURED_TARGET_* stopwords: warnings only, not reached.
- `agent3/assembler.py:503-510,846-905` + `mappings.py:49`: DEMOGRAPHIC_KEYWORDS, GENDER_MAP-in-text and fuzzy concept-set matching; legacy supervisor pipeline only.
- `agent4/validator.py:201` DEMOGRAPHIC_NAMES: API validator warnings.
- `comparator/literature.py:31` `_CV_TERMS` and `recommender.py:175`: the recommendation is only logged; the derived fallback is always used (`tte_service.py:7027-7030`).
- `pipeline/cohort_executor.py:303-315`: concept-set names containing outcome/event/death, default concept 260139; analysis execution only.
- (D11, added at reconciliation) `services/emission_stability.py:117,148,158,221,471`: `description_watch`/`topic_watch`/`PREGNANCY_CLUSTER_TOPICS` match criterion `description`; imported only by `scripts/measure_emission_stability.py` and tests; counts for a report, decides nothing in a delivered artifact.

## 2. Class C — reads vocabulary concept names
| # | file:line | rule | decides | on path | introduced | candidate |
|---|---|---|---|---|---|---|
| C1 | agent2/logic.py:40,207 | `_DOSE_PATTERN` strips dose/form from an RxNorm product name, then exact Ingredient-name lookup | ingredient roll-up fallback | yes | 6ffd07c | not measured |
| C2 | services/dose_form_route.py:30-94 | `_ROUTE_PATTERNS`, `_SYSTEMIC_BY_ROUTE`, `_DRUG_DEPENDENT_FORMS` on dose-form names | route of each form, which feeds A12 | yes | 0bc33ea 2026-08-03 | same 7 seeds as A12 |
| C3 | loinc_specimen.py:62,65,129 | `CIRCULATING_BLOOD_SYSTEM_WORDS`, `_CHALLENGE_TIMING` on LOINC System/component names | specimen kept or removed; gate (u) | yes | d97397e 2026-10-08 | 37 refinements |
| C4 | agent2/retriever.py:322-352 | concept_name vs query exact/substring/prefix boosts; penalised-class gate | candidate ranking | yes | 6ffd07c | not measured |
| C5 | drug_class_expander.py:77-116 | ATC name equality/prefix | ATC class selection | yes | 239c0b5 2026-10-08 | 31 ATC hits |
| C6 | workflow.py:731-735 | UMLS synonym first-word diversity | query rewrites | inactive (no `data/umls`) | 6ffd07c | — |
| C7 | overbroad_absence_repair.py:149,283-300 | set name == vocabulary concept_name | narrows an absence set | yes (tte_service.py:7975) | 350501a 2026-09-18 | 4 repairs (Infective endocarditis ×2, DKA ×2) |
| C8 | utils/disease_anchor.py:74,120-135 | token Jaccard: registry condition vs set/concept names | disease entry anchor; gate expected anchor | yes | 1e7d709 2026-09-06 | 3 PrimaryCriteria swaps |
| C9 | tte_service.py:6832 | "other"/"combinations" in ATC names | comparator candidates | off path | — | — |
| C10 | comparator/recommender.py:175 | first word of the drug class found in literature text | precedent flag | off path | — | — |

**Text-to-text comparisons with no fixed word list** (keep; this is the substring-verification primitive itself):
- `parser.py:761`
- `decomposer.py:88-91` (gate 1)
- `temporal_grounding.py:190,207` `_squash`/`_entity_anchored`
- `tte_service.py:3743` `_target_label_looks_drug_like`
- `tte_service.py:7752`
- `restated_clusters.py:46` + `restated_distinctness.py:244`: an equal description stem collapses duplicates (16–17 `restated-distinctness-duplicate` skips per arm across trials)
- `enricher.py:136,197`: SequenceMatcher ≥0.7

## 3. Class B — machine formats (keep)
Counts are distinct constants or regexes, hand-counted (±1).
- **agent1/parser.py (5):** LLM op enum map, code-fence JSON split, whitespace, role enum, op table.
- **threshold_classifier.py (5):** numerals, `10^9` tail, null tokens, JSON, `deescape`.
- **pubmed_fetcher.py (7):** efetch XML.
- **Other Agent 1 fetch code:** pubmed_linker (1), pmc_fetcher (3, XML/HTML), pmc_supplement (5, OA XML + filename/journal role tokens), nct_fetcher (1, NCT id), paper_url_mapper (3, DOI).
- **criteria_dedup.py (4):** tokenizer, list marker, abbreviations, numerals.
- **planner/decomposer.py (3):** comparison form, JSON, op set.
- **value_constraint.py (11):** unit concept tables, UCUM aliases, number, `10^9/L`, dose-rate unit, percent, Circe ops.
- **loinc_specimen.py (10):** UCUM dimension grammar, LOINC property codes, schema identifier, tokenizer.
- **circe_lint.py (11):** CIRCE field/domain tables, op sets, arm roles.
- **verify_circe_delivery.py (6):** record keys, reason/refusal code sets, filename suffix.
- **tte_service.py (~14):** domain↔criteria-type maps, comparisonMode/psMethod enums, NCT id, name sanitizers, CIRCE key tests.
- **Agent 2 (~15):** ICD-10/numeric (log only), KG relationship names, critic enums, vocabulary_id/concept_class_id preferences (hand-tuned ranking on machine fields), UMLS STY/SAB, SQL class filters, cache-key normalisation.
- **utils/llm.py (5):** `<think>`, preamble marker, JSON scan, model prefixes.
- **Misc:** ir.py (1), api/models (1), naming_words/disease_anchor tokenizers (2), and env flags and filenames in pipeline/api/analysis (~10, off path).

## 4. Totals
- **Class A on the delivery path:** 30 rows (A1–A29, with A5 split) from 29 distinct sources (A25 reuses A11), plus 6 gate reuses, plus 9 segmentation rules (S1–S9).
- **Off-path or dead Class A:** 10 groups (11 with D11 added at reconciliation).
- **Class C:** 10 (8 on path).
- **Class B:** about 140 items.
- **Text-to-text, no word list:** 7.

Per pipeline stage (Class A rows):

| Stage | Rows | Notes |
|---|---|---|
| Agent 1 parsing/repair | 8 (A1–A7, A5 split) + 9 segmentation | reingest only |
| Planner | 2 (A8, A9) | also uses A5 and A11 |
| Agent 2 mapping / seed | 8 (A10–A17) | run in the candidate |
| TTEService build | 7 (A18–A24) | |
| Export repairs | 4 (A25–A28) | |
| Delivery gate / lint | 1 distinct (A29) + 6 reuse rows | reuses A9, A17, A18, A19, A20, A28 |

## 5. Gaps
- **Reachability is approximate.** Module reach comes from a static import closure of `reingest_protocol_pdfs.py` / `export_seeded_cohorts.py` / `verify_circe_delivery.py`. Inside `tte_service` I used a name-based call graph; dynamic dispatch was traced by hand only for the rows listed.
- **Not measured** because the candidate did not re-run those stages: A3, A5a/A5b, A7, S1–S9, the `fast` branch of A17, A16's second site (`tte_service.py:1006`), and A24.
- **Effects not determined:** A25 on the EMPA-REG file; A21's consequence (inferred, not run); A22's replacement (I did not check whether the store keeps the CT.gov arm type).
- **Scope:** prompt text (`agent1/prompts.py`, `planner/prompts.py`) was not inventoried. It contains trigger-phrase lists, e.g. Pattern F "females must", "must use contraception". `utils/presence_unit_allowlist.py` is a concept-id table, so it is not a text rule but is concept-specific.
- **Dates on `6ffd07c 2026-07-22`** mean the rule predates the repository history (that commit is the baseline snapshot).
