# Phase 1: Semantic Intelligence - Detailed Execution Plan

This document breaks down Phase 1 into granular, executable tasks.

## Sub-Phase 1.1: Foundation & Infrastructure
**Goal**: Set up the project skeleton, dependencies, and local development environment.

- [ ] **Task 1.1.1: Project Skeleton**
  - Create directory structure (`src/`, `tests/`, `config/`).
  - Set up `pyproject.toml` (Dependency Management).
  - Create `.env.example` and `.gitignore`.
- [ ] **Task 1.1.2: Docker Environment**
  - Create `docker-compose.yml`.
  - Services:
    - `postgres`: For OMOP CDM (MIMIC-IV subset).
    - `chromadb`: For Vector Search.
    - `redis`: For caching/registry.
- [ ] **Task 1.1.3: Core Utilities**
  - Implement `src/utils/db.py` (Postgres connection).
  - Implement `src/utils/vector.py` (ChromaDB connection).
  - Implement `src/utils/llm.py` (LLM Client wrapper).

## Sub-Phase 1.2: Agent 1 (Logic Decomposer)
**Goal**: Convert Natural Language to Internal Representation (IR).

- [ ] **Task 1.2.1: IR Schema Definition**
  - Create `src/models/ir.py`.
  - Define Pydantic models for `Cohort`, `Criteria`, `Limit`, `Outcome`.
- [ ] **Task 1.2.2: NLU Module**
  - Create `src/agents/agent1/prompts.py` (System prompts).
  - Create `src/agents/agent1/parser.py` (LLM call + JSON parsing).
- [ ] **Task 1.2.3: Agent 1 Unit Tests**
  - Create `tests/agents/test_agent1.py`.
  - Verify NL -> IR conversion with sample inputs.

## Sub-Phase 1.3: Agent 2 (Intelligent Mapper)
**Goal**: Map text terms to OMOP Concept IDs using Hybrid Search & Reranking.

- [ ] **Task 1.3.1: Regex Pre-processor**
  - Create `src/agents/agent2/regex_rules.py`.
  - Implement pattern matching for ICD10 (`[A-Z]\d{...}`) and RxNorm.
- [ ] **Task 1.3.2: Vector Search Implementation**
  - Create `src/agents/agent2/retriever.py`.
  - Implement `search_vector_db(query: str) -> List[Candidate]`.
- [ ] **Task 1.3.3: Context Reranking (The Judge)**
  - Create `src/agents/agent2/reranker.py`.
  - Implement LLM logic to select best concept from candidates.
- [ ] **Task 1.3.4: Logic & Pruning**
  - Implement decomposition logic for Combination Drugs.
  - Implement `prune_candidates(concept_ids)` using SQL checks.
- [ ] **Task 1.3.5: Agent 2 Integration**
  - Create `src/agents/agent2/workflow.py` combining the above steps.

## Sub-Phase 1.4: Integration & Verification
- [ ] **Task 1.4.1: Pipeline Test**
  - Create a script that takes NL -> Agent 1 -> Agent 2 -> List of Concept IDs.
