# Fallback Audit — artemis/src

**Date:** 2026-07-30
**Scope:** `artemis/src` (133 Python files, 39,073 LOC) — services, api, agents/{agent1,agent2,agent3,agent5,comparator,conceptset}, utils, models
**Read-only — no code changes made.**

Every finding below has already been re-verified against the actual source (file:line quoted, reachability traced, caller checked) by an independent pass; three originally-reported findings (SVC-03, SVC-05, API-03) were dropped as wrong or unreachable and are recorded at the bottom so they are not re-derived. One finding's severity was raised on re-verification (MISC-01, P2→P1); all others match the originally-assigned severity after the second pass.

---

## Summary Table

| ID | File:Line | From → To | Trigger | SILENT? | Severity | Recommendation |
|----|-----------|-----------|---------|---------|----------|----------------|
| CS-01 | `agents/conceptset/phoebe_client.py:35,45,70-71` | live `settings.CDM_SCHEMA` (`synthea_cdm`) → hardcoded `SCHEMA="demo_cdm"` | every production call (no schema arg ever passed) | YES | **P1** | Source schema from `settings.CDM_SCHEMA`; log resolved schema per call |
| API-01 | `api/main.py:31-37` | conceptset router mounted → silently omitted | any exception importing `conceptset.api` | YES | **P1** | Narrow to `(ImportError, ModuleNotFoundError)`; log at ERROR |
| CS-02 | `api/main.py:31-37` (same lines as API-01) | entire conceptset REST domain → vanishes with zero trace | same as above | YES | **P1** | Same fix as API-01 |
| A2-01 | `agents/agent2/kg_expander.py:663-700,566-585` | real descendant counts → `{}` → IC filter fails **open** (broadens, not narrows) | any DB exception in `_get_pg_descendant_counts` | YES (warn logged, but decision not recorded) | **P1** | try/finally on connection; fail-closed on missing counts, not `compute_ic(0)=20.0` |
| A2-03 | `agents/agent2/retriever.py:117-125` | real ChromaDB result → `print()` + `return []`, indistinguishable from "no OMOP concept exists" | any exception in `collection.query()` | YES | **P1** | Replace `print()` with `logger.error`; flag Chroma-outage separately from genuine no-match |
| A2-04 | `agents/agent2/drug_name_normalizer.py` (241 lines, dead) | purpose-built fix for dev-code drug names (e.g. "BI 10773") → never wired into `workflow.py`/`retriever.py` | any dev-code drug term with no `concept_synonym` row | YES | **P1** | Call `DrugNameNormalizer.normalize()` before `retriever.search()` in the Drug-domain path |
| A1-01 | `agents/agent1/parser.py:172-197,590-620,646-684` | actual PDF-extraction success → `enriched=True`/`PaperStatus(source=...)` set unconditionally whenever a PDF merely exists/downloads | pdftotext missing, <100 chars extracted, no eligibility section found, etc. | YES (Python `warnings.warn`, deduped after first occurrence, never logged) | **P1** | Only set `enriched=True`/`source=...` when criteria count actually increased |
| A1-03 | `agents/agent1/parser.py:1014-1023` | LLM-specified operator/value → `.get("operator","gt")` / `.get("value",0)` defaults when keys are missing, producing a fully-valid, indistinguishable `ValueConstraint` | LLM JSON has `value_constraint` present but missing `operator`/`value` keys | YES | **P1** | Only construct `ValueConstraint` when both `operator` and `value` are actually present; else leave `None` so the existing "missing constraint" warning fires |
| MISC-01 | `agents/agent3/assembler.py:409,579,615` | `Criteria.domain` string → silently mapped to `"ConditionOccurrence"` when it doesn't match one of 8 known keys | any typo'd/hallucinated/case-variant domain string from Agent 1 (no enum constraint anywhere upstream) | YES | **P1** (raised from P2 on re-verification) | Log a warning (and add a `HealAction`) on every `.get(key, default)` miss, matching the sibling `CodesetId==0` check in the same file |
| MISC-03 | `agents/comparator/recommender.py:300-336` | 0 PubMed docs → LLM still invoked on `"(no literature retrieved)"` placeholder, output returned as a literature-grounded recommendation | PubMed `esearch` failure/rate-limit or genuine 0-hit query | YES | **P1** | Check `len(docs)==0` before invoking the LLM; short-circuit with a caveat the way the vLLM-unreachable branch already does |
| API-02 | `api/tte.py:171-198` | exact criterion_id match → Fallback 2 reconstructs a positional index and returns a **different** criterion's cached mapping candidates | legacy artifact missing `ruleIndexMeta`, current eligibility criteria include any ungrouped demographic rule or any `groupId` grouping (near-universal) | YES | **P1** | Add `resolvedVia` field to `CriterionMappingMetadata`; log WARNING when the reconstruction path fires |
| CS-04 | `agents/conceptset/nlu_router.py:110-121` | LLM include/exclude separation → entire raw query silently becomes one INCLUDE term, exclude list dropped | LLM timeout / malformed JSON in intent parsing | YES (logged, but `fallback_to` stays `None`, unlike the sibling temporal-negation branch) | **P1** | Set `fallback_to`/`fallback_reason` on parse failure, reusing the temporal-negation branch's propagation path |
| CS-05 | `agents/conceptset/expression_builder.py:212-231` | standard-concept validation → "assume all valid", every candidate passed through unfiltered | DB error on validation query (already has a QueuePool retry, meaning this failure mode is observed in production) | YES | **P1** | Do not pass candidates through as validated on failure; propagate a typed error or a visible degraded-validation marker |
| SVC-01 | `services/tte_store.py:175-198,245-318` | real `studies.json` → hardcoded demo study (`create_sample_study()`), then permanently written back over real data on the next mutation | `studies.json` fails `json.load()` on all 3 retry attempts | Partially (ERROR-level log; demo study is distinctively named) | P2 | Never let a corrupted-read flow into a subsequent `_write()`; back up corrupted file; surface degraded status to API callers |
| SVC-02 | `services/tte_service.py:5282-5332` | real ATC-4th class → `""` | DB connect/query failure in `_treatment_atc_class` | YES (no log at all) | P2 | Add `logger.warning` in both except blocks |
| SVC-04 | `services/tte_service.py:5106-5115` | real clinical HITL review → auto-approved by `_mock_hitl_approve_comparator` (docstring admits "not wired yet") | every literature-based comparator recommendation | Partially (`logging.info` only; no field in persisted artifact) | P2 | Carry a `reviewStatus` field through to the persisted study so a reviewer can see this was never human-reviewed |
| SVC-06 | `services/value_constraint.py:235-263` | protocol lab-value threshold → no value filter at all | `valueConstraint` present but `value`/`op` unparseable | YES | P2 | Have `build_measurement_value_filter` signal (not silently drop) when a constraint was present but unusable |
| SVC-07 | `services/tte_service.py:8353-8379` | fitted subgroup HR → `None` (row omitted), same as deliberate small-sample guards | `cox.fit()`/`get_hazard_ratio()` raises (non-convergence, singular matrix) | YES | P2 | Log distinctly from the deliberate n<20/single-arm guards |
| A2-02 | `agents/agent2/workflow.py:831-833,902-904` | `critic_skipped=True` (deliberate anchor≤10 bypass) → reused as `False` for both genuine success AND KG/critic exceptions | Neo4j down/timeout, or exception inside refiner/critic call | Partially (`logger.warning` with real exception text) | P2 | Use a 3-state `critic_status` instead of reusing `False` for both success and failure |
| A2-05 | `agents/agent2/logic.py:111-113` | resolved ingredient concept_id → `[]` on SQL error, indistinguishable from a genuine zero-row match | any exception in `_resolve_ingredient_by_name`'s DB query | Weakly (logger.debug, but this deployment runs at DEBUG level so it is emitted) | P2 | Raise to `logger.warning` to match the outer handler; not contingent on `DEBUG=true` staying default |
| A2-06 | `agents/agent2/concept_set_refiner.py:77-105` | data-driven `includeDescendants` decision → hardcoded `domain=="Condition"` default | DB query failure in `_get_single_descendant_count` | Partially (WARNING logged, but decision not recorded in `RefinementResult`) | P2 | Thread a `used_db_fallback` flag through to `RefinementResult` |
| A1-02 | `agents/planner/decomposer.py:93-143` | genuine LLM "atomic" decision → same terminal state on LLM exception or JSON parse failure | `llm.invoke()` raises, or JSON unparseable | Partially (distinct `print()` messages at failure time, but not persisted in the IR artifact) | P2 | Track decomposition attempts vs. failures; log via `logger`, not `print` |
| A1-05 | `agents/agent1/pubmed_linker.py:31-37,94-100` | Strategy-1 (design/background paper PMIDs) → silently `[]`, Strategy-2 (live search) masks the failure with no signal Strategy-1 broke | `AttributeError`/`TypeError` walking a malformed `referencesModule` | YES (zero print/log — the one fully silent path in this module) | P2 | Log the caught exception with `nct_id` before returning `[]` |
| CS-03 | `agents/conceptset/clinical_reranker.py:36,53-69,130-143` | advertised "BioLinkBERT Cross-Encoder" reranking → always LLM-judge/score-sort (sentence-transformers not installed); model name also hardcoded wrong even if installed | every `rerank()` call with >1 candidate | Partially (INFO log on one path; `rerankMethod`/`rerankConfidence` surfaced to HITL UI on the other) | P2 | Log cross-encoder init failure at WARNING/ERROR; wire `model_name` into `CrossEncoder(...)` or drop the unused parameter |
| CS-06 | `agents/conceptset/expression_builder.py:233-286` | overbroad-ancestor exclusion guard → no filtering at all on DB failure | DB error counting `concept_ancestor` descendants | Partially (WARNING logged, no retry unlike sibling CS-05) | P2 | Fail closed for this guard; flag "overbroad-check-skipped" on the item |
| CS-08 | `agents/conceptset/rag_search.py:73-75; ontology_search.py:103-105; stage2_pipeline.py:70-72; recommender.py:206-210,53-58` | genuine "no OMOP concept found" → byte-identical response when ChromaDB + ontology Postgres are both down (PHOEBE not even reached) | independent `except Exception: return []` in RAG + Ontology search | Partially (`logger.warning` + unconditional `print()` + INFO-level `includes=0` in request log) | P2 | Distinguish "searched, zero matches" from "backend raised"; surface in `RecommendationResponse.fallback` instead of `null` |
| CS-09 | `agents/conceptset/phoebe_client.py:145-169; stage2_pipeline.py:93-127 vs recommender.py:206` | documented "Circuit Breaker" timeout protection → never reached; production path uses the sync, unbounded method | any PHOEBE query that hangs during a real `/recommend` request | Effectively silent (a hang, not a fallback substitution, but the *protection* is silently absent) | P2 | Wire the sync production path through a bounded timeout, or correct the docstring |
| MISC-04 | `agents/comparator/recommender.py:330` | LLM candidate `same_setting` omitted → defaults to `True` (passes the eligibility gate) instead of `False` | LLM JSON response omits `same_setting` for a candidate | YES | P2 | Default missing `same_setting` to `False` (fail closed) |
| MISC-05 | `agents/comparator/literature.py:68-81` | PubMed `esearch` network/HTTP failure → `[]`, identical shape to a genuine zero-result search | any exception in `requests.get`/`raise_for_status` | Partially (`logger.warning`, visible) | P2 | Add an `acquisition_error` field to distinguish transport failure from true empty result |
| A2-07 | `agents/agent2/kg_expander.py:136-142` | persisted KG-expansion cache → silently reset to empty in-memory cache | corrupt/unreadable `kg_cache.json` | YES, but benign (forces a real re-query, no wrong data) | P3 | Add a `logger.warning` (cheap, low priority) |
| A2-08 | `agents/agent2/map_entity.py:146-152` | — positive template — | any exception in `process_with_details` | NO | P3 | None — reuse this explicit-error-field pattern elsewhere |
| A1-04 | `agents/agent1/pubmed_fetcher.py:80-82,101-103` | PubMed fetch failure → `print()` + `None`/`{}` | network/HTTP/XML error | Mixed — single-fetch path is signalled via `PaperStatus(source="nct_only")`; batch path is not | P3 | Switch both to `logger.warning`/`error` |
| A1-06 | `agents/agent1/paper_url_mapper.py:173-225` | — positive template — | any journal PDF download failure | NO | P3 | None |
| A1-07 | `agents/agent1/threshold_classifier.py:296-345` | — positive template — | any classifier gate failure | NO | P3 | None |
| CS-07 | `agents/conceptset/expression_builder.py:288-343` | roll-up compression → returns flat, uncompressed (but still real) candidate list on DB failure | DB error checking descendant relationships | NO | P3 | None |
| MISC-02 | `agents/comparator/recommender.py:105-106,164-171,196-200` | `verdict='unknown'` caveat hardcodes "vLLM/Qwen unreachable" regardless of actual cause | any reason `cv_effect_evidence` is empty | NO (surfaced, just mislabeled) | P3 (dead code — `recommend_comparator` unreachable outside `__main__`) | Track actual cause per-candidate before wiring this up |
| MISC-06 | `utils/llm.py:499-518` | vLLM `/models` unreachable → entries omitted from dropdown | vLLM down when `GET /tte/models` called | YES, but low impact (fewer UI choices, no fabricated entry) | P3 | Add `logger.debug`/`warning` |
| MISC-07 | `agents/agent3/assembler.py:427-488,698-740` | — positive template — | unresolved entity_text / `CodesetId==0` | NO | P3 | None |
| MISC-08 | `agents/agent5/workflow.py:196-247` | — positive template — | PSM 0 matched pairs at both calipers | NO | P3 | None |
| MISC-09 | `utils/cache.py:52-158` | — positive template — | Redis unavailable | NO | P3 | None |
| MISC-10 | `models/ir.py:159-183` | — positive template (schema-level) — | N/A | NO | P3 | None |

---

## Severity Summary

| Severity | Count | IDs |
|----------|-------|-----|
| **P1** — silent, substitutes wrong/fake data as if real | 13 | CS-01, API-01, CS-02, A2-01, A2-03, A2-04, A1-01, A1-03, MISC-01, MISC-03, API-02, CS-04, CS-05 |
| **P2** — partially signalled, easy to miss / confusable with "no data" | 16 | SVC-01, SVC-02, SVC-04, SVC-06, SVC-07, A2-02, A2-05, A2-06, A1-02, A1-05, CS-03, CS-06, CS-08, CS-09, MISC-04, MISC-05 |
| **P3** — benign by design / positive template | 12 | A2-07, A2-08, A1-04, A1-06, A1-07, CS-07, MISC-02, MISC-06, MISC-07, MISC-08, MISC-09, MISC-10 |
| **Total** | **41** | |

Dropped on re-verification (see bottom section): SVC-03, SVC-05, API-03.

---

## Top P1 Findings (Detail)

Ordered by (blast radius) × (invisibility), not alphabetically — see the Korean prioritization section at the end for the reasoning.

### 1. CS-01 — PHOEBE client hardcoded to `demo_cdm` on every call
**File**: `artemis/src/agents/conceptset/phoebe_client.py:35,45,70-71`
**Trigger**: Fires on every production call, unconditionally — `PhoebeClient()` is constructed with zero args on the only production path (`get_phoebe_client()` → `Stage2Pipeline.phoebe`), so `schema` is always `None → self.SCHEMA`.
**Impact**: Live-verified against the running `artemis-api` container: `settings.CDM_SCHEMA = "synthea_cdm"`, `demo_cdm.concept_recommended` exists, `synthea_cdm.concept_recommended` does not (`to_regclass` NULL). Every PHOEBE co-occurrence expansion silently queries the demo/reference dataset instead of the live CDM, returns real-looking concept names/IDs, and is RRF-merged into the final candidate list with no distinguishing flag. `tests/test_phoebe.py:28` even asserts `client.schema == "demo_cdm"` as correct, so CI encodes the bug as expected behavior.
**Snippet**:
```python
class PhoebeClient:
    SCHEMA = "demo_cdm"          # line 35
    def __init__(self, schema=None, ...):
        self.schema = schema or self.SCHEMA   # line 45 — never receives settings.CDM_SCHEMA
    ...
    query = f"SELECT ... FROM {self.schema}.concept_recommended ..."  # lines 70-71
```
**Fix**: `self.schema = schema or settings.CDM_SCHEMA` (matching how `OntologySearch`/`ExpressionBuilder` already source their schema); log the resolved schema per call; fix `tests/test_phoebe.py:28`.

---

### 2. API-01 / CS-02 — conceptset router import failure swallowed at app boot
**File**: `artemis/src/api/main.py:31-37`
**Trigger**: Any exception (not just `ImportError`) raised anywhere in the transitive import chain of `src.agents.conceptset.api` (12 files, including `src/utils/db.py`'s module-level `create_engine`).
**Impact**: `/health` still returns `{"status":"ok"}` regardless. Every conceptset route then 404s exactly as if it never existed — a real regression is byte-identical to "feature intentionally not installed." `conceptset/__init__.py:36-45` does catch `ImportError` specifically and logs a warning one layer up, so this specific P1 is scoped to non-`ImportError` failures (a bad edit, a settings/DB-config error) reaching `main.py`'s own broader `except Exception`. Currently dormant (all 4 routes verified mounted in the live container) but permanent and untested.
**Snippet**:
```python
try:
    from src.agents.conceptset.api import router as conceptset_router
    app.include_router(conceptset_router)
except Exception:
    # Keep the TTE MVP bootable even when optional conceptset dependencies are unavailable.
    pass
```
**Fix**: `except (ImportError, ModuleNotFoundError) as exc:` + `logging.getLogger(__name__).error("conceptset router unavailable: %s", exc, exc_info=True)`. Anything else should crash startup loudly.

---

### 3. CS-05 — concept-set standard-concept validation "assumes all valid" on DB failure
**File**: `artemis/src/agents/conceptset/expression_builder.py:212-231`
**Trigger**: A DB error on the `standard_concept='S' AND invalid_reason IS NULL` validation query. The function already retries once specifically for `QueuePool` errors — evidence this failure mode has been observed live — but the eventual give-up path still trusts unvalidated data.
**Impact**: 5 call sites (`recommender.py:223`; `tte_service.py:5163,5803,5880,5951`) consume the returned list with no check for degraded state; every candidate then gets `includeDescendants=True` as if verified standard, indistinguishable in the emitted ConceptSet/cohort JSON from a genuinely validated concept.
**Snippet**:
```python
for attempt in range(2):
    try:
        ...  # standard_concept validation query
    except Exception as e:
        logger.warning(f"[Expression Builder] Validation error (attempt {attempt + 1}): {e}")
        return candidates  # Fallback: assume all valid
```
**Fix**: Do not pass candidates through as validated; propagate a typed error (`api.py` already has `DBQueryError` wired into `EXCEPTION_STATUS_MAP`) or attach a degraded-validation marker to `RecommendationItem.reason`.

---

### 4. A2-03 — sole live vector-retrieval call folds ChromaDB outage into "no OMOP concept"
**File**: `artemis/src/agents/agent2/retriever.py:117-125`
**Trigger**: Any exception from `self.collection.query()` inside `ConceptRetriever.search()` — the only retriever entry point on the live path (fast path hardwired off at `workflow.py:386`; `process_batch`/`_slow_path_batch` are unreferenced dead code).
**Impact**: `_slow_path` (`workflow.py:401-408`) turns the resulting `[]` into `gap_report.add_gap(..., reason="No OMOP mapping found")` — a clinician-facing artifact documented as "Enables clinician review of pipeline gaps." A ChromaDB outage during a run silently inflates the ordinary "no mapping found" count instead of surfacing as an infrastructure failure.
**Snippet**:
```python
except Exception as e:
    print(f"Vector search failed (DB might be empty): {e}")
    return []
```
(Contrast: `batch_search` in the same class, line 373-377, uses `logger.warning` for the identical failure.)
**Fix**: Replace `print()` with `logger.error`; distinguish "vector store unreachable" from "no candidates" before it reaches the gap report.

---

### 5. MISC-01 — wrong OMOP-domain default silently selects the wrong criteria table
**File**: `artemis/src/agents/agent3/assembler.py:409,579,615`
**Trigger**: `Criteria.domain`/`PrimaryCriteria.domain` (plain `str`, no `Literal`/enum anywhere in `src/models/ir.py`) holds any value outside the 8 keys `DOMAIN_TO_CRITERIA_TYPE`/`DOMAIN_TO_PRIMARY_CRITERIA_TYPE` recognize — a typo, case variant, or a domain the Agent 1 prompt never enumerates (Visit/Device/Death are valid OMOP domains missing from the prompt hint).
**Impact**: Produces a fully-formed, plausible Circe criteria block querying the **wrong OMOP table** (e.g. a Measurement/Visit rule silently run against `condition_occurrence`) with zero logging anywhere near these three call sites — contrast with `_validate_and_heal` two stages later in the same file, which does log and record a `HealAction` for `CodesetId==0`. The only downstream tell is an eventual 0-patient extraction, already treated as a generic "expand concepts" signal rather than a domain-mapping miss. This is the same shape as this audit's own calibration example #1 (a cohort quietly empties).
**Snippet**:
```python
criteria_type = DOMAIN_TO_PRIMARY_CRITERIA_TYPE.get(pc.domain, "ConditionOccurrence")   # :409
sc_criteria_type = DOMAIN_TO_CRITERIA_TYPE.get(sc.domain, "ConditionOccurrence")        # :579
criteria_type = DOMAIN_TO_CRITERIA_TYPE.get(rule.domain, "ConditionOccurrence")         # :615
```
**Fix**: Log a warning (and add a `HealAction`) on every `.get(key, default)` miss, exactly like the `CodesetId==0` check already does. Constrain `Criteria.domain` to a `Literal`/enum at the IR layer so a bad value fails fast at ingestion.

---

### 6. A1-03 — LLM value-constraint operator/value silently defaulted to `gt`/`0`
**File**: `artemis/src/agents/agent1/parser.py:1014-1023`
**Trigger**: LLM's `value_constraint` object is truthy but omits `operator` and/or `value` — plausible under Agent 1's generic `response_format={"type":"json_object"}` (no schema `required` enforcement) on a partial/truncated response.
**Impact**: Produces a fully schema-valid, non-`None` `ValueConstraint(op="gt", value=0, ...)` — e.g. "age > 65" can silently become "age > 0", or an intended `lt`/`eq` operator silently becomes `gt`, inverting the criterion. `ValidationError` (the only path that logs, at `parser.py:1026`) never fires because both fields are already valid by construction. The one downstream safety net, `_validate_measurement_rules` (`parser.py:858-878`), only warns when `value_constraint is None` — it cannot detect a present-but-fabricated constraint.
**Snippet**:
```python
normalized_vc = {
    "op": vc_data.get("op") or self._normalize_operator(vc_data.get("operator", "gt")),
    "value": vc_data.get("value", 0),
    ...
}
```
**Fix**: Only construct `ValueConstraint` when both `operator`/`op` and `value` are actually present in `vc_data`; otherwise leave `value_constraint=None` so the existing missing-constraint warning fires instead.

---

### 7. MISC-03 — comparator recommendation invokes the LLM on zero literature
**File**: `artemis/src/agents/comparator/recommender.py:300-336`
**Trigger**: `_fetch_comparator_docs` returns `docs=[]` (PubMed `esearch` failure/rate-limit — no NCBI API key configured, ~3 req/s ceiling — or a genuine zero-hit query). The only pre-LLM guard checks `_vllm_reachable()`, never `len(docs)`.
**Impact**: `lit` collapses to the literal string `"(no literature retrieved)"`; the LLM is still prompted with "Using ONLY the literature below" and can return a plausible drug-class recommendation from parametric memory. `caveat` is only set on the vLLM-unreachable branch or a JSON-parse exception — never here. The sole caller, `_mock_hitl_approve_comparator` (`tte_service.py:5106-5115`, itself a documented stub with no real human review), checks only `drug_class`/`ingredients` non-empty, never `n_papers`/`caveat`. A hallucinated-but-real-sounding comparator is CDM-grounded and written straight into the study's active-comparator CIRCE cohort, indistinguishable from a genuinely literature-backed pick.
**Fix**: Check `len(docs)==0` before invoking the LLM; short-circuit with a caveat the way the vLLM-unreachable branch already does, and have `_mock_hitl_approve_comparator` check `n_papers`.

---

### 8. API-02 — criterion mapping-candidates endpoint returns a different criterion's cached data
**File**: `artemis/src/api/tte.py:171-198`
**Trigger**: A legacy artifact missing `ruleIndexMeta` (always present in artifacts generated by current code — dormant except for pre-existing rows in `tmp/tte/studies.json`), combined with any ungrouped demographic criterion or any `groupId` grouping in the study's current eligibility (near-universal — age/sex screens are rarely grouped). Fallback 2 rebuilds a positional `mappable_ids` list that omits demographic criteria and doesn't collapse `groupId` groups, while the real rule-builder (`_build_seeded_target_circe`) inserts demographic rules first and collapses groups — so the index is offset from the moment the artifact was generated, no edit required.
**Impact**: `criterion_meta_map.get(mappable_ids[criterion_id])` returns another criterion's `allCandidates`/`rerankMethod`/`selectedConceptIds` as `CriterionMappingMetadata` with HTTP 200 and no distinguishing field. A reviewer approving "candidates for criterion N" in the HITL flow may be looking at a different criterion's candidates entirely.
**Fix**: Add a `resolvedVia: Literal["direct","rule_index_legacy"]` field; log at WARNING with study_id/criterion_id/artifact_id whenever Fallback 2 fires.

---

### 9. CS-04 — NLU include/exclude parse failure drops the exclude list silently
**File**: `artemis/src/agents/conceptset/nlu_router.py:110-121` (contrast: `:153-161`)
**Trigger**: `self.chain.invoke(...)` or `IntentResult(**result)` raises — LLM timeout, malformed/truncated JSON (same failure class as the audit's own calibration incident #3).
**Impact**: `logger.error` fires, but `fallback_to` is left at its default `None` — unlike the temporal-negation branch a few lines away, which explicitly sets `fallback_to`/`fallback_reason` and propagates it to `RecommendationResponse.fallback`. `recommend()` only short-circuits when `fallback_to` is set, so this path proceeds as an ordinary single-INCLUDE query. A query like "Heart Failure but exclude TZD" hitting this failure returns a plausible single-criterion concept set with zero indication exclude-parsing was ever attempted, and `/recommend-and-save` will POST it to the live Atlas WebAPI as a valid recommendation.
**Fix**: Set `fallback_to`/`fallback_reason` on parse failure, reusing the temporal-negation branch's existing propagation path.

---

### 10. A2-01 — KG expander descendant-count DB failure disables the over-broad-ancestor filter (fails open, not closed)
**File**: `artemis/src/agents/agent2/kg_expander.py:663-700` (leak/silent return), `:566-585` (consequence)
**Trigger**: Any exception between `psycopg2.connect()` and `conn.close()` inside `_get_pg_descendant_counts` (no `try/finally`) — reached on every seed concept under the **default** `KG_EXPAND_MODE=clinical_anchor`.
**Impact**: `desc_counts={}` → `compute_ic(0)=20.0` for every seed and every ancestor → `dynamic_threshold` also caps near 17.5 → every ancestor's `ic_ok` passes. A Postgres hiccup silently **disables** the IC-based over-broad filter (making concept sets more inclusive, not less) exactly when the safety check is supposed to prevent that — and the corrupted result is written unconditionally into the on-disk KG cache (`kg_expander.py:285-289`), poisoning future runs too. Only a `logger.warning` marks the moment of failure; nothing records that the filter was bypassed.
**Fix**: Wrap the connect/execute/fetch block in `try/finally`; fail closed (exclude unresolved ancestors) rather than defaulting `descendant_count` to 0.

---

### 11. A1-01 — PDF-enrichment "success" flag set regardless of whether any criteria were extracted
**File**: `artemis/src/agents/agent1/parser.py:172-197` (+ `:590-620`, `:646-684`)
**Trigger**: `_enrich_from_pdf` fails via any of 5 branches (missing pdftotext binary, non-zero exit, <100 chars extracted, no eligibility section found, generic exception) and returns `trial_data` completely unchanged — signalled only via `warnings.warn(RuntimeWarning)`, which Python's default filter dedupes to once per source line for the process lifetime, and the repo has zero `captureWarnings`/`filterwarnings` configuration.
**Impact**: All three call sites (papers_dir loop, PMC-supplement, journal-download) set `enriched=True`/`PaperStatus(source=...)` unconditionally after the call, without checking whether `trial_data` actually changed. This `PaperStatus` is persisted into the `draft_generation` artifact's `meta.paperStatus` (`tte_service.py:653-680`), replayed verbatim on cache hits, and rendered by the frontend (`tte-manager.js:1443-1449`) as a green "Local Upload ✓" success badge — indistinguishable from a real extraction, and it permanently blocks the lower-priority PubMed-abstract fallback that might have recovered the criteria.
**Fix**: Compare before/after criteria counts at each call site; only set `enriched=True`/`source=...` when the count actually increased; log via `logger.warning`, not `warnings.warn`.

---

### 12. A2-04 — a built, tested fix for a documented production incident is never wired in
**File**: `artemis/src/agents/agent2/drug_name_normalizer.py` (241 lines)
**Trigger**: Any clinical-trial development-code drug name (e.g. "BI 10773", "AZD6140") with no `concept_synonym` entry, reaching `retriever.search()`/`critic.py` with no prior normalization.
**Impact**: `rg` confirms zero references to `DrugNameNormalizer`/`normalize()` outside this file and its own test — not called from `workflow.py`, `retriever.py`, or `critic.py`. The module's own docstring is a war story about this exact failure already happening in production (concept 1254065, 0-patient cohorts at three hospitals). The backing data (`data/pubchem/pubchem_synonyms.sqlite`, 22GB) is fully built, not a stub — the fix was completed and then never connected.
**Fix**: Call `DrugNameNormalizer.normalize()` in the Drug-domain path (Step 0b/`_slow_path`) before `retriever.search()`; fall through unchanged if it returns `None`.

---

## Good Examples — Fallbacks That Correctly Signal (P3 templates)

| ID | Location | Pattern worth reusing |
|----|----------|------------------------|
| A2-08 | `agents/agent2/map_entity.py:146-152` | `EntityMappingResult(error=str(e), concept_ids=[], success=False)` — explicit error field, `success` requires both non-empty result AND no error; callers gate on `.success` |
| A1-06 | `agents/agent1/paper_url_mapper.py:173-225` | `DownloadAttempt(status='downloaded'\|'paywalled'\|'unavailable'\|'error')` propagated verbatim into persisted artifact meta — human/UI can see exactly which download failed and why |
| A1-07 | `agents/agent1/threshold_classifier.py:296-345` | Every gate failure (G0-G7) becomes an explicit `ThresholdSpan(span_class='REVIEW', review_reason='...')` rather than a dropped span or a guessed class |
| MISC-07 | `agents/agent3/assembler.py:427-488` | Every skip/partial-heal is logged AND recorded as a structured `HealAction` in `heal_log`, exposed via `has_failures`/`failed_entities` |
| MISC-08 | `agents/agent5/workflow.py:196-247` | PSM→IPTW fallback logs a WARNING per caliper attempt and overwrites `analysis_method` to `"IPTW (PSM fallback)"` — cannot be mistaken for a clean PSM run |
| MISC-09 | `utils/cache.py:52-158` | Redis failure → `None` (correct cache-aside semantics; a broken cache is behaviorally identical to a real miss) |
| MISC-10 | `models/ir.py:159-183` | Fallback baked into the schema itself: `source: Literal["structured_section","study_description","study_name","empty"]` + `fallback_used: bool` — no guessing required from an empty string |
| CS-07 | `agents/conceptset/expression_builder.py:288-343` | On DB failure, returns the flat *uncompressed* candidate set (a superset of already-real, already-validated concepts) rather than trusting anything new — contrast with the fail-open CS-05/CS-06 in the same file |

---

## Dropped Findings (verified wrong or unreachable — do not re-derive)

| ID | Location | Why dropped |
|----|----------|-------------|
| SVC-03 | `services/tte_service.py:3857-3863,5409-5468` | Gated by `TTE_DRUG_ANCHORED_ENTRY` env var, confirmed unset in both the live container and `.env`/compose — path is constant-False in production, not reachable. If ever enabled, each branch already logs at WARNING (P2 territory, not P1). |
| SVC-05 | `services/tte_service.py:7031-7063,7569` | The claimed fallback handler itself references an undefined `logger` name — reproduced live: any LLM invoke failure raises a fresh `NameError` before the described fallback can execute. The actual outcome is a loud job failure (`status:"failed"`) + HTTP 500, not a silent template substitution. |
| API-03 | `api/models/tte.py:290-308` | Both real constructor call sites for `SuggestionArtifactMeta` always pass `mappingQuality=` explicitly, and the computing helpers set a visible `status`/`reason` field (`"fallback"`, `"agent2_unavailable:..."`) on their own internal failures. No code path produces the claimed "artifact validated with `mappingQuality` omitted" scenario — the `default_factory` is inert boilerplate. |

---

## 왜 이 모양이 반복되는가

이번 주 실제로 터진 열다섯 건 중 열넷이 정확히 같은 모양이었다는 브리핑 자체가 힌트다. 이 코드베이스에는 **실패 신호 채널(logger/print)과 데이터 채널(pydantic 모델·캐시 파일·API 응답)이 완전히 분리되어 있다.** `except Exception:` 블록이 로그를 남기든 안 남기든, 그 블록이 리턴하는 값은 함수의 정상 리턴 타입과 완전히 같은 모양(`List[int]`, `dict`, `str`, `bool`)이다. Result/Either 같은 태그드 유니온 관례가 이 코드베이스에 존재하지 않기 때문에, 리턴값만 보고는 "정상적으로 계산된 빈 값"과 "계산이 실패해서 대체된 빈 값"을 구분할 방법이 애초에 없다. 로그가 있어도(대부분 있다) 그 로그는 리뷰어가 실제로 열어보는 산출물(코호트 JSON, ConceptSet, HITL 리뷰 화면)에는 닿지 않는다.

두 번째 구조적 요인: 이런 함수들은 대부분 API 경계에서 3~4단계 떨어진 깊은 유틸리티(`kg_expander`, `phoebe_client`, `expression_builder`, `nlu_router`, `_treatment_atc_class`, `_get_single_descendant_count`)다. 이 깊이에서 "그냥 raise 하면 파이프라인 전체가 죽는다"는 두려움이 "부드럽게 성공한 것처럼 되돌리자"는 선택으로 굳어졌고, 그 "부드러움"이 구현될 때 항상 "이 자료형의 zero-value를 리턴"으로 번역되었다 — 실패를 표시하는 별도 필드 하나 추가하는 비용보다 그게 더 짧은 코드였기 때문이다.

**같은 메커니즘이 반복된 것 (거의 동일한 코드 모양 — DB/네트워크 I/O를 감싼 `except Exception`이 자기 자료형의 빈 값을 리턴):**
SVC-02(`_treatment_atc_class`), SVC-06(`value_constraint`), SVC-07(Cox fit), A2-01(`kg_expander` desc_counts), A2-05(`_resolve_ingredient_by_name`), A2-06(`_get_single_descendant_count`), A2-03(`retriever.search`), CS-05(`_validate_standard_concepts`), CS-06(`_filter_overbroad`), CS-08(rag_search/ontology_search/stage2 3중 동일 패턴), MISC-06(`list_available_models`), MISC-05(PubMed `esearch`) — 41건 중 12건이 문자 그대로 이 한 가지 모양이다.

**같은 메커니즘의 변주 (예외가 아니라 `.get(key, default)`가 "빈 값"이 아니라 "그럴듯하지만 틀린 특정 값"을 대체하는 경우):**
MISC-01(`DOMAIN_TO_CRITERIA_TYPE.get(...,"ConditionOccurrence")`), A1-03(`vc_data.get("operator","gt")`), API-02(포지셔널 인덱스로 다른 criterion의 캐시를 재사용) — 이 세 건이 가장 위험한 이유는 "빈 데이터"가 아니라 "가짜지만 유효한 데이터"를 만들기 때문이다.

**진짜로 서로 다른 결정 (하나로 묶어 고칠 수 없는 것들):**
CS-01은 예외 처리가 전혀 아니다 — 그냥 잘못된 하드코딩 상수(`SCHEMA="demo_cdm"`)다. API-01/CS-02는 "MVP를 부팅 가능하게 유지하자"는 앱 시작 시점의 방어적 설계다. SVC-01은 데이터 복구 전략의 실수다. SVC-04와 A2-04는 실패 폴백이 아니라 "아직 연결 안 된 스텁/완성된 수정을 배선만 안 한 것"이다. A1-01은 예외 경로가 아니라 "작업이 실제로 일어났는지 확인 안 하고 성공 플래그를 세팅"하는 버그다. MISC-03/MISC-04는 예외 처리가 아니라 "입력이 불충분할 때 LLM을 호출하지 말아야 한다는 가드 자체가 없는 것"이다. CS-09는 폴백이 아니라 "만든 안전장치가 실제로 쓰이는 코드 경로에 연결되지 않은 것"이다.

정리하면: **41건 중 약 절반(12건의 P1/P2급 핵심 + 다수의 P2)이 "깊은 유틸리티 함수가 예외를 자기 자료형의 zero-value로 뭉개고, 그 값이 호출자 사슬을 타고 올라가며 계속 '정상 계산 결과'로 취급된다"는 단 하나의 관례 공백에서 나온다.** 나머지는 각각 다른 엔지니어링 판단 착오(하드코딩 상수, 미배선 스텁, 성공 플래그 오설정, 부족한 입력 가드)이며 이들은 개별적으로 고쳐야 한다.

## 무엇을 먼저 고칠지, 그리고 왜 그 순서인지

기준은 심각도 단독이 아니라 **(영향 반경) × (발견 불가능성)**이다. 스타트업 시점에 한 번 실행되는 경로의 P1보다, criterion 하나마다 반복 실행되는 경로의 P2가 실제로는 더 급하다.

1. **CS-01** (`phoebe_client.py:35,45,70-71`) — 가장 먼저. 예외 조건 없이 **모든** 요청에서 100% 발동하고, 로그가 전혀 없으며, 테스트가 이 버그를 정답으로 assert하고 있다. 고치는 비용은 한 줄(`settings.CDM_SCHEMA` 참조)이다. 영향 반경 100% × 완전 침묵 × 최저 수정 비용 — 순서상 1위가 자명하다.
2. **API-01 / CS-02** (`main.py:31-37`) — 현재는 잠들어 있지만, 발동하면 도메인 전체가 흔적 없이 사라지고 `/health`는 계속 200을 반환한다. 다음에 이 파일을 건드리는 사람이 만드는 회귀를 영구히 숨겨줄 트랩이므로, "지금 당장 터지고 있는가"와 무관하게 두 번째로 막아야 한다.
3. **CS-05 (+ CS-06 같은 파일)** — conceptset 추천 파이프라인에서 가장 뜨거운 경로(5개 호출부)에 있고, DB 장애 시 "전부 검증 통과"로 처리한다. QueuePool 재시도 로직이 이미 존재한다는 것 자체가 이 실패가 실제로 관측된 적 있다는 증거다.
4. **MISC-01** — 잘못된 OMOP 테이블을 조용히 골라 코호트 정의에 박아 넣는다. 캘리브레이션 예시 #1(코호트가 조용히 비어버림)과 정확히 같은 모양이고, 바로 다음 단계(`_validate_and_heal`)에 이미 있는 로깅 패턴을 그대로 복사만 하면 된다.
5. **A2-03** — 유일하게 살아있는 리트리버 경로. Chroma 장애를 "매핑 없음"이라는 임상의 리뷰용 gap report에 섞어 넣는다.
6. **A1-03** — criterion 단위지만 사고 하나당 피해가 크다: "age > 65"가 "age > 0"이 되어 자격 기준 전체를 무력화할 수 있다.
7. **A2-01** — 기본 실행 모드(`clinical_anchor`)에서 DB 장애 시 안전장치(과확장 방지 필터)가 방향을 반대로 뒤집어 더 넓어진다.
8. 나머지(A1-01, MISC-03, A2-04, CS-04, API-02, 그리고 P2 전체) — trial 단위/study 단위로만 발동하거나 특정 입력 모양이 필요해 영향 반경이 좁다. 위 항목들을 정리한 뒤 처리해도 된다.

**단 하나의 변경으로 가장 많은 건수를 막을 수 있는가 — 부분적으로만 그렇다.** "`except Exception`이 자기 자료형의 zero-value를 그대로 리턴하는 것을 금지하고, 실패 시 반드시 상태/출처 필드를 태깅하거나 최소 WARNING 로그를 남긴다"는 코딩 관례 하나를 리뷰 체크리스트에 박으면 SVC-02, SVC-06, SVC-07, A2-01, A2-05, A2-06, CS-05, CS-06, CS-08, MISC-05, MISC-06 — 대략 11건, 41건 중 4분의 1 이상 — 을 기계적으로 예방한다. 하지만 CS-01(예외가 아예 없는 하드코딩), API-01/CS-02(임포트 시점 스왈로), SVC-01(데이터 복구 설계), SVC-04/A2-04(미배선 스텁), A1-01(성공 플래그 오설정), MISC-03/MISC-04/CS-04(LLM 호출 전 입력 충분성 가드 부재)는 이 관례로 잡히지 않는다 — 이들은 각각 별도로 고쳐야 하는, 정직하게 말해 "같은 병이 아닌" 결함이다.
