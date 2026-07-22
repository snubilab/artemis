# Phase 2: Assembler & Registry Integration - Detailed Execution Plan

**Timeline**: W4-W6  
**Goal**: 전역 Concept Registry 구현 및 Circe-be JSON 자동 조립

---

## Sub-Phase 2.1: Global Registry System
**Goal**: 중복 없는 ConceptSet 관리 및 상태 공유

- [ ] **Task 2.1.1: Registry Data Model**
  - Create `src/registry/models.py`
  - Define `ConceptSet`, `Concept`, `RegistryEntry` Pydantic models
  - Implement hash-based deduplication logic

- [ ] **Task 2.1.2: Redis Integration**
  - Create `src/registry/store.py`
  - Implement CRUD operations: `register()`, `get()`, `exists()`, `list_all()`
  - Add TTL management for cache invalidation

- [ ] **Task 2.1.3: Registry API**
  - Create `src/api/registry.py`
  - Endpoints: `POST /registry`, `GET /registry/{id}`, `GET /registry/search`

---

## Sub-Phase 2.2: Agent 3 (Cohort Assembler)
**Goal**: IR + Registry → Circe-be JSON 변환

- [ ] **Task 2.2.1: Static Attribute Mapping**
  - Create `src/agents/agent3/mappings.py`
  - Hardcode mappings:
    ```python
    GENDER_MAP = {"MALE": 8507, "FEMALE": 8532}
    OPERATOR_MAP = {"lt": "<", "gt": ">", "eq": "=", "lte": "<=", "gte": ">="}
    ```

- [ ] **Task 2.2.2: Circe JSON Templates**
  - Create `src/agents/agent3/templates/` directory
  - Implement Jinja2 templates:
    - `cohort_definition.json.j2`
    - `concept_set.json.j2`
    - `inclusion_rule.json.j2`

- [ ] **Task 2.2.3: Assembler Logic**
  - Create `src/agents/agent3/assembler.py`
  - Implement `build_cohort_definition(ir, registry) -> CirCeJSON`
  - Handle negation: ABSENCE → `Occurrence: {Type: 0, Count: 0}`
  - Handle exclusion: `isExcluded: true`

- [ ] **Task 2.2.4: Measurement Handling**
  - Create `src/agents/agent3/measurement.py`
  - Parse `value_constraint` from IR
  - Map unit text to OMOP Unit Concept ID (e.g., "%" → 8554)

---

## Sub-Phase 2.3: Agent 4 (Validator)
**Goal**: JSON 문법 검사 및 OHDSI 호환성 확인

- [ ] **Task 2.3.1: Schema Validation**
  - Create `src/agents/agent4/validator.py`
  - Implement JSON Schema validation for Circe format
  - Check required fields: `PrimaryCriteria`, `ConceptSets`, `InclusionRules`

- [ ] **Task 2.3.2: Registry Integrity Check**
  - Validate all ConceptSet IDs referenced in JSON exist in Registry
  - Report missing references

- [ ] **Task 2.3.3: Dry Run (Optional)**
  - Create `src/agents/agent4/dry_run.py`
  - Send JSON to OHDSI WebAPI `/cohortdefinition/sql` endpoint
  - Parse and log SQL generation errors

---

## Sub-Phase 2.4: Pipeline Integration
**Goal**: Agent 1 → 2 → 3 → 4 데이터 흐름 연결

- [ ] **Task 2.4.1: Orchestration Graph**
  - Update `src/graph/workflow.py`
  - Add `registry_node`, `assembler_node`, `validator_node`
  - Define state transitions with LangGraph

- [ ] **Task 2.4.2: End-to-End Test (Agent 1-4)**
  - Create `tests/integration/test_cohort_pipeline.py`
  - Input: Natural language query
  - Output: Valid Circe-be JSON

---

## 📊 Phase 2 Deliverables

| Deliverable | File |
|-------------|------|
| Registry Store | `src/registry/store.py` |
| Assembler | `src/agents/agent3/assembler.py` |
| Circe Templates | `src/agents/agent3/templates/*.j2` |
| Validator | `src/agents/agent4/validator.py` |
| Integration Test | `tests/integration/test_cohort_pipeline.py` |
