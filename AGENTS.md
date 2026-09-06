# ARTEMIS BACKEND AGENT GUIDE

## OVERVIEW

- ARTEMIS is the Python/FastAPI TTE backend for Broadsea.
- Edit this tree for backend API, agent, pipeline, analysis, and report behavior.
- Root `../AGENTS.md` owns workspace-wide Compose, TTE reporting, and generated-gold cache policy.
- Keep this file backend-local; do not repeat root workspace prose.

## WHERE TO LOOK

| Task | Location | Notes |
| --- | --- | --- |
| FastAPI app | `src/api/main.py` | `create_app()` wires `/health`, TTE routes, optional conceptset routes, Spark startup check |
| TTE API contract | `src/api/tte.py`, `src/api/models/tte.py` | Request/response models used by Atlas TTE UI |
| TTE orchestration | `src/services/tte_service.py` | Main service boundary for studies, generation, mapping, execution, analysis, reports |
| TTE persistence | `src/services/tte_store.py` | Local store/concurrency behavior |
| Agent stages | `src/agents/agent1` through `src/agents/agent6` | Extraction, mapping, assembly, validation, analysis/report stage workers |
| Concept sets | `src/agents/conceptset/` | NLU, search, ranking, expression building |
| Pipeline runtime | `src/pipeline/` | Supervisor, WebAPI client, cohort execution, Spark execution |
| Analysis | `src/analysis/` | OMOP access, propensity, KM, Cox, balance, covariates |
| Reporting | `src/reporting/`, `src/services/report_*` | PDF/HTML/report plot generation |
| Scripts | `scripts/` | Benchmarks, loaders, generated-gold eval, diagnostics, one-off repair tools |
| Gold cohort definitions | `data/gold/<TRIAL>/` | TROY v1.1 CIRCE JSON; the reference for concept-set quality |
| Gold vs generated compare | `scripts/compare_gold_vs_generated_circe.py` | Definition-level only, no DB. `PAIRS` currently omits ARISTOTLE/LEADER/PLATO |
| Achilles value distributions | `scripts/achilles_measurement_dist.R` | Populates analysis 1815 for one CDM; runs in `broadsea-hades` |
| Tests | `tests/` | Unit tests plus Docker-backed integration tests |
| Docs | `docs/` | ADRs, daily notes, debugging logs, benchmark history |

## CONVENTIONS

- Use `src/services/tte_service.py` as the orchestration boundary before adding new API route logic.
- Keep Pydantic API shapes in `src/api/models/tte.py`; avoid ad hoc response dicts in routes.
- Put WebAPI/cohort runtime concerns in `src/pipeline/`, not in `src/agents/`.
- Put statistical execution in `src/analysis/`; put presentation assembly in `src/reporting/` or existing `report_*` services.
- Use existing script patterns under `scripts/` for benchmark and data-maintenance entrypoints.
- Treat `.venv/`, `chroma_db/`, `data/cache/`, `tmp/`, and `.pytest_cache/` as runtime or generated state.
- `pyproject.toml` sets `pytest` `asyncio_mode = "auto"`.
- Tests marked `integration` require Docker infrastructure: WebAPI, PostgreSQL, and Neo4j.

## EVALUATION

Judge concept-set and criteria quality by **closure overlap against `data/gold/`**,
not by patient counts against `synthea_cdm_{aristotle,leader,plato}`.

Those CDMs are generated *from gold* by `scripts/generate_synthea_from_gold.py`,
which inverts each gold value constraint and injects one constant per lab. So a
patient count partly measures that generator's conventions. Worked example: gold
writes the platelet threshold as `100` (thousands/uL) and the protocol PDF writes
`100,000/mm3`; both are correct, nothing records a unit, and the 1000x gap alone
takes the ARISTOTLE cohort to 0. Details and the other traps (empty
`procedure_occurrence`, clinically-sound concept sets that match 0 rows) in
`docs/debugging/2026-08-09_benchmark_cdm_is_not_an_oracle.md`.

Resolve a concept set the way Circe does, or the overlap is not comparable: direct
items as listed, descendants joined through `concept_ancestor` filtered by
`invalid_reason IS NULL`, `isExcluded` items subtracted as an anti-join. Confirm
against the rendered SQL by POSTing the expression to
`WebAPI /cohortdefinition/sql` rather than assuming.

Score **per eligibility criterion, 1:1, macro-averaged**. Never lead with a micro
average over pooled concept ids. On this corpus the two disagree in DIRECTION, not just
magnitude:

| | micro (concept mass) | per criterion 1:1 |
| --- | --- | --- |
| overall recall / precision | 0.141 / 0.503 | 0.542 / 0.484 |
| ARISTOTLE | 0.087 / 0.863 | 0.749 / 0.153 |

ARISTOTLE reads "worst recall, best precision" under micro and the opposite per
criterion. Its micro recall was set by one 111,910-concept antihypertensive set we never
build; its micro precision by one 10,720-concept aspirin set that matches gold exactly.
Neither describes the other forty criteria, and per criterion 48 of 144 matched pairs
reach full recall — erased by the pooled figure.

Report per-set recall and precision, and the recall distribution rather than only a
mean. Report three populations separately: matched pairs, gold sets with no counterpart
(94 of 238 here), and generated sets with no counterpart. A "best Jaccard match" against
a gold set that has no real counterpart must be reported as *no counterpart*, not as a
weak match.

Always surface **zero-overlap pairs** — both sides exist and share no concept. They are
the sharpest defect class and are invisible in any pooled number: our "linagliptin" set
resolves to sitagliptin, "glimepiride" to three Condition concepts, and our 205-concept
glucose set omits gold's one fasting-glucose LOINC.

`scripts/conceptset_overlap_eval.py` emits this as `per_criterion` and prints it above
the micro block; micro is labelled "concept mass — do not quote as quality".

Gold sets referenced **only** from `CensoringCriteria` are out of scope and reported
under `out_of_scope_gold`, not paired: gold censors at initiation of either arm's drug,
and the generated eligibility cohort has no such section. Six of the scored sets are in
this class. Without the exclusion, CAROLINA's "Hypersensitivity to investigational
product or glimepiride" was matched to gold's glimepiride censoring set by name alone.

**Unreferenced gold sets are kept in the denominator — decided 2026-08-10, do not
silently change it.** 14 of 238 scored gold sets are orphans that no criterion
references, nearly all non-ATC duplicates of the `(ATC)` set PrimaryCriteria actually
uses. They stay because the question this eval asks is whether we built gold's concept
sets, and TROY exports them as a library. The cost of that choice must be paid at
reporting time: **one correction can score as several pairs.** Fixing the entry drug
moved five pairs, but three were orphan duplicates of the other two — the honest count
is two, one per affected trial. Report distinct corrections, not pair counts, and say
which pairs are duplicates when quoting a delta.

## NAME RESOLUTION OWNERSHIP

Name resolution is owned by `TTEService._recommend_seeded_concept_set`, which funnels
every criterion and target string through one fixed precedence — **exact RxNorm
ingredient → trial-MeSH alias → criterion cache → Agent2Workflow (QueryExpander curated
expansion → ATC drug-class → `ConceptRetriever.batch_search` → reranker) → RAGSearch
fallback** — first tier returning non-None wins outright. Add a new resolver as a tier
there, never as a second lookup inside a consumer.

Three mechanisms in this tree were fully implemented and switched off, each failing
silently. Check the switch before concluding a path is broken:

- The MeSH alias tier needs `trialMetadata.interventionMeshTerms`, written only when a
  study is imported with the raw registry payload present. Backfill an older store with
  `scripts/backfill_intervention_mesh_terms.py`; `regenerate_structured_expression.py`
  now warns loudly when a study has none.
- `QueryExpander` holds a four-row curated table because the UMLS backend it was written
  for needs a licensed `MRCONSO.RRF` that is not on this host. Do not add rows without
  measuring: of the 14 abbreviations occurring in the six trials, expansion helped 4,
  did nothing for 7 and made 2 **worse**. The two that got worse are excluded by the
  6-character length gate; leave that gate alone.
- `abbreviation_expander.py` is a no-op module superseded by the above.

Linting: `.venv/bin/ruff check <paths>`, config in `pyproject.toml` under
`[tool.ruff.lint]`. **ruff is installed in `.venv` but deliberately NOT in
`requirements.txt`** — that file is what `Dockerfile.tte-api` builds the container from,
and a lint-only tool has no business in the runtime image.
`tests/test_environment_matches_requirements.py` permits this: it iterates the packages
*declared* in `requirements.txt` and checks their versions, and has no "no extra
packages" assertion. An earlier session read the gate's docstring as forbidding any
install and skipped linting an entire session's work on that basis. Lint changed files
only; `tte_service.py` and `build_conceptset_dashboard.py` carry hundreds of pre-existing
findings and cleaning them is not a drive-by.

Settled, do not re-litigate:

- **PubChem (`drug_name_normalizer.py` + the 22 GB SQLite) stays unwired.** Across the
  730-trial cache its unique *and correct* contribution is one seed (TMC435 →
  Simeprevir). "No MeSH term" and "no RxNorm ingredient" are the same condition — a
  pre-approval compound — so it resolves the code and lands where OMOP has no concept.
  The database also carries a contaminated synonym edge that answers wrongly with
  `is_ambiguous=False`, the exact failure its docstring claims to prevent. OMOP's own
  `concept_relationship` beats it on brand names at zero storage.
- **The two ChromaDB readers do not disagree in production.** `RAGSearch` only beats
  `ConceptRetriever` when handed a `domain_filter`, and no live caller passes one. What
  is duplicated is the `collection.query` call, not the ranking; keep the two score
  polarities separate (`rag_search.py` higher-is-better, `retriever.py` lower-is-better)
  because `clinical_reranker` sorts descending on the former.
- **`_VOCAB_PREFERENCE`'s Measurement LOINC −0.30 is not a defect.** It promotes the gold
  concepts (3049187, 46236952 at ranks 1–2); the SNOMED pair it demotes appears in no
  gold file. `tests/test_map_retriever_scoring.py::test_hba1c_loinc_beats_snomed` defends it.
- **An unlisted vocabulary scores +0.05, not 0.** `_score_candidates` reads
  `vocab_prefs.get(vocab, 0.05)`, so deleting an entry is only a no-op when the value was
  already 0.05 or the vocabulary never occurs in that domain. Three entries named
  vocabularies with no row in `omop_concepts_medcpt` and were removed: Condition/ICD10CM,
  Drug/ATC, Procedure/CPT4. What each domain really holds is listed at the constant.
  **Device stays** — `effective_domain = domain_hint or domain` falls back to the
  candidate's own domain, so Device rows are scored by it on any unhinted query; "no
  criterion in the store is Device-domain" is not a reason to delete it.
- **The MeSH alias tier's refusal rate is not its ambiguity guard.** Of the 94 cached
  trials that actually depend on the tier — no arm label, intervention name, or otherName
  spells the generic, the 'BI 10773' shape — it accepts 9, refuses 84 because *no* MeSH
  term is a standard RxNorm Ingredient, and refuses **1** because more than one resolves.
  Loosening `len(resolved) != 1` buys that single trial and reverses `8692a55`. The
  binding constraint is vocabulary coverage, and most of it is not a gap: of the 88
  unresolvable terms, the bulk are not drugs (`Office Visits`, `Watchful Waiting`),
  development codes MeSH indexed verbatim (`SB 223412`), or systematic chemical names —
  the segment PubChem was already rejected for. Two OMOP-native bridges now run inside
  `_resolve_ingredient_concept_id` and serve 7 of the 84: `Precise Ingredient --Maps to-->
  Ingredient` for salt and ester headings (`Quetiapine Fumarate`), and standard
  Ingredients that live in `RxNorm Extension` (`artenimol`, `izencitinib`). Both sit
  *below* the RxNorm probe and every probe is final, so only names that resolved to
  nothing can newly resolve — 33 more MeSH terms resolve and 0 stopped. A bridge can
  create ambiguity instead of removing it: NCT07531173 carries two salt headings, goes
  0 → 2 resolving, and stays refused, which is the guard working. Un-inverting MeSH
  headings (`Natriuretic Peptide, Brain`) recovers 0 and is not implemented. Re-measure
  with `scripts/analyze_alias_tier_refusals.py`.
- **The mapping seed is `sourceText or description`, not `conceptSetName`.**
  `_build_seeded_eligibility_rule` (`tte_service.py:5827`) builds the label that way, and
  `queryUsed` in the recorded metadata equals `sourceText` for 323 of 351 generated sets.
  A blast-radius measurement taken over `conceptSetName` is measuring the wrong column —
  that error was made once already in this session and named the wrong seed. The scored
  artifacts are also not from the obvious store: `scoped_mesh_fix_rematch.json` was
  produced from `tmp/mesh_fix/studies.json`, not `tmp/tte/studies.json`, and their
  criterion ids do not align. Measured correctly, the two ingredient-name bridges newly
  resolve one seed per store: `hemoglobin` in `tmp/mesh_fix` (a Measurement criterion,
  stopped by the domain gate) and `prothrombin complex concentrate` in `tmp/tte` (Drug,
  reaches the mapper, but that store is not the scored one). No scored pair changes
  either way.

## DISEASE ENTRY ANCHOR

A placebo comparator cannot enter on the study drug, so its entry is swapped to a
`ConditionOccurrence`. Which condition is decided by `src/utils/disease_anchor.py`
against the trial's OWN registered condition — the strings ClinicalTrials.gov carries
under `conditionsModule.conditions`, persisted as `trialMetadata.conditions`. A
candidate is a Condition concept set the study's rules read under a PRESENCE
occurrence; it wins by carrying exactly a registered condition's tokens. Nothing
matching, two matching over different concepts, or no `conditions` at all with several
candidates, all REFUSE — the arm reports `missing_arm` with the reason and the export
writes no manifest.

- Backfill an older store with `scripts/backfill_registered_conditions.py` before
  exporting or gating it. Without `conditions` the delivery gate reports
  `disease anchor unverifiable` and fails, which is deliberate: a disease-anchored
  comparator that cannot be checked is what shipped wrong on 2026-09-06.
- Do not add a per-trial table or branch here. Two have already been removed — a
  lookup keyed on NCT id, then "the first Condition set in document order", which gave
  LEADER's comparator `LV systolic or diastolic dysfunction` and studies 4/5/6
  `Asymptomatic cardiac ischemia` for the same trial, purely because their criteria are
  written in a different order.
- Studies 4/5/6 refuse because they carry no type-2-diabetes rule at all. That is a gap
  in their extracted criteria, not in the matcher; regenerating those criteria is the
  fix, not loosening the match.

## ANTI-PATTERNS

- Do not move API contract fields without checking Atlas TTE consumers under `../atlas-dev/js/pages/target-trial-emulation/`.
- Do not read `MappingCandidateItem.score` as a probability or compare it across criteria. It is a per-criterion rank score derived from the retriever's `adjusted_score`, which is normalised per query; `None` means the candidate arrived via KG/ATC expansion and was never scored, which is not the same as scoring badly.
- **`substance abuse` scores 0 because nothing is generated for it, not because the
  scorer cannot match it.** Its gold set is three retired SNOMED concepts (436954 D,
  440069 U, 4279309 D) with no `concept_ancestor` rows, which does make it unmatchable by
  any set of standard concepts — but the pair's outcome is `no_counterpart` in all five
  trials that carry it, so there is no generated set to match at all. The scorer now
  canonicalises retired concepts onto their standard replacements on both sides
  (`forward_retired_concepts`), which removes that artifact for future gold sets and is
  worth +0.0003 macro here, i.e. nothing. Fixing this criterion means generating a set
  for it; do not reach for the scorer again.
- Do not compare a macro across a change that alters *pairing*. `per_criterion_macro`
  (`scripts/conceptset_overlap_eval.py:497`) averages over `outcome.startswith("matched")`
  only, so a gold set with no generated counterpart leaves the denominator entirely
  rather than scoring 0. Any change to the scorer's name matching therefore moves the
  macro without moving quality — dropping three badly-scoring pairs out of `matched`
  raises the mean by itself. Arm-to-arm comparisons under the *same* scorer are safe, and
  the mesh_fix headline is one: EMPA-REG's numerator rose 11.04 → 14.03 over 38 fixed
  gold sets, so its gain is +0.079 on the fixed population versus the +0.060 quoted off
  the matched-only mean. When the scorer itself changed, quote the fixed population (all
  gold sets, no-counterpart scored 0) or quote nothing.
- Do not measure a mapping change against a warm criterion cache. The cache key is built from the *unexpanded* seed and it stores the whole mapping metadata, so a fixed run replays the old concept set and reads as "no change". Use `CRITERION_CACHE_ENABLED=false` or a fresh `CRITERION_CACHE_DB_PATH`.
- Do not report a patient count from a trial benchmark CDM as evidence of pipeline quality; see EVALUATION above.
- Per-arm CIRCE for hospital/site delivery is produced only by `scripts/export_seeded_cohorts.py`
  with an explicit `--store`; a `TTE_STORE_PATH` mismatch aborts the run rather than silently
  overriding it. `scripts/verify_circe_delivery.py` must pass on the export directory before
  anything is sent. The 2026-08-31 delivery (`output/circe_be/2026-08-31/`) — stale-store export,
  62 no-op inclusion rules, a wrong EMPA-REG entry concept set — is the counterexample both gates
  exist to catch.
- Do not infer a measurement's unit from its value distribution. An exclusion threshold sits in the abnormal tail by design, so "outside the observed range" is what a *correct* threshold looks like; the molar cases that must be refused score better than the decimal cases that must be accepted. Achilles 1815 is a sound detector and an unsound repairer.
- Do not retype a wire-format constant (for example the `[OR-GROUP]` prefix, join, and separator). Import it from its owning module; `tests/test_dry_or_group_contract.py` fails if a second copy appears, and a guessed format silently makes every probe against it return `False`.
- Do not treat a passing unit test on a predicate as proof its caller honours the predicate. `restates_or_group_alternative` correctly refuses to call an OR group a duplicate, and `enricher._merge_criteria` then drops it anyway via the legacy `SequenceMatcher`.
- Do not bypass `TTEService` with parallel orchestration in routes.
- Do not commit generated cache, Chroma, tmp, virtualenv, or pytest cache contents.
- Do not duplicate generated-gold cache SQL here; use `scripts/evaluate_generated_gold_studies.py` and the parent cache rule.
- Do not mark Docker-backed tests as plain unit tests; use the existing `integration` marker.

## COMMANDS

```bash
# Local venv shell
source .venv/bin/activate

# Backend boot check
python -m src.boot_check

# Full backend suite
pytest tests/ -v

# Targeted test file
pytest tests/test_boot_check.py -v

# Targeted test name
pytest tests/test_boot_check.py::test_boot_check_reports_missing_package -v

# Integration tests only
pytest tests/integration/ -m integration -v

# Generated-gold rerun entrypoint
python scripts/evaluate_generated_gold_studies.py
```
