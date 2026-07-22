# Phase 2: Assembler & Registry Integration Plan

**Timeline**: Weeks 4-6
**Focus**: Agent 3 (Assembler), Agent 4 (Validator), and Concept Registry

## 1. Global Concept Registry
- [ ] **Redis Implementation**:
  - Design key-value structure for storing Concept Sets.
  - Implement Hashing logic to deduplicate Concept Sets (e.g., `hash(sorted_concept_ids)`).
- [ ] **Registry API**:
  - `register_concept_set(concepts: List[int], name: str) -> unique_set_id`
  - `get_concept_set(unique_set_id)`

## 2. Agent 3: Cohort Assembler
- [ ] **Circe-be Integration**:
  - Study the Circe-be JSON specification.
  - Create Pydantic models representing Circe constructs (`CriteriaGroup`, `ConditionOccurrence`, `DrugExposure`, etc.).
- [ ] **IR to Circe Mapping**:
  - Implement the translator: `IR Schema` + `Registry IDs` -> `Circe JSON`.
  - Handle **Negation**:
    - `logic_type: ABSENCE` -> `Occurrence Count: 0`.
  - Handle **Measurements**:
    - Map operators (`gt`, `lt`, `eq`) and units to Circe fields.
- [ ] **Static Attribute Map**:
  - Create a lookup dictionary for Gender, Race, and other static concepts.

## 3. Agent 4: Validator
- [ ] **Syntax Validation**:
  - Validate the generated JSON against the official OHDSI Circe schema (if available) or strict Pydantic models.
- [ ] **Integrity Check**:
  - Verify that all Concept Set IDs in the JSON exist in the Registry.
- [ ] **Dry Run (SQL Simulation)**:
  - Integrate with `OHDSI-SQLGenerator` (via R or Java wrapper, or Python port if exists).
  - Attempt to generate SQL from the JSON.
  - Catch and parse errors to provide feedback.

## 4. Integration (Agents 1-4)
- [ ] **LangGraph Orchestration**:
  - Define the graph: `User Input` -> `Agent 1` -> `Agent 2` -> `Agent 3` -> `Agent 4`.
  - Implement state passing between nodes.
- [ ] **End-to-End Test (Cohort Definition)**:
  - Input: Natural language query.
  - Output: Valid OHDSI JSON ready for execution.

## 5. Deliverables
- Functional Registry (Redis).
- Agent 3 producing valid Circe JSON.
- Agent 4 validating the output.
- Integrated pipeline for the "Cohort Definition Phase".
