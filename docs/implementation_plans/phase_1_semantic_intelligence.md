# Phase 1: Semantic Intelligence Implementation Plan

**Timeline**: Weeks 1-3
**Focus**: Agent 2 (Intelligent Mapper) & Logic Decomposition

## 1. Environment Setup
- [ ] Initialize Python project with `poetry` or `pip`.
- [ ] Set up Docker containers for:
  - PostgreSQL (MIMIC-IV subset for testing).
  - ChromaDB (Vector Database).
  - Redis (for caching/state, initially for testing).
- [ ] Configure LLM API access (Gemini/OpenAI).

## 2. Agent 1: Logic Decomposer (Basic Implementation)
- [ ] Define the Internal Representation (IR) Schema using Pydantic.
  - See `spec.md` Section 3, Module 1 for schema details.
- [ ] Implement a basic parser (LLM-based) to convert Natural Language -> IR.
  - Input: "New users of Metformin with T2DM..."
  - Output: JSON IR with `primary_criteria`, `inclusion_rules`, etc.

## 3. Agent 2: Intelligent Mapper (Core Logic)
### 3.1 Hybrid Search Module
- [ ] **Regex Pre-processor**:
  - Implement regex to detect ICD/RxNorm codes (e.g., `[A-Z]\d{2,}`).
  - Create a function to lookup exact code matches in the CDM `CONCEPT` table.
- [ ] **Vector Search**:
  - Ingest OMOP Concepts (Condition, Drug, Measurement) into ChromaDB.
  - Implement embedding generation (BioLinkBERT or similar).
  - Create retrieval function to get Top-20 candidates for text queries.

### 3.2 Context-Aware Reranking (The Judge)
- [ ] Design the LLM Prompt for reranking.
  - Input: User Context (from IR), Candidate List (ID, Name, Class).
  - Output: Selected Best Concept ID.
- [ ] Implement the ranking pipeline.

### 3.3 Logic Layer & Decomposition
- [ ] **Decomposition Logic**:
  - Detect `Concept Class == 'Combination Drug'`.
  - Implement SQL query to find `CONCEPT_ANCESTOR` -> Ingredients.
- [ ] **Domain Rules**:
  - Implement checks for specific keywords (e.g., "Family History") to enforce "Single Concept" mode.

### 3.4 Data-Driven Pruning
- [ ] Implement the "Pruner":
  - Takes a list of candidate Concept IDs.
  - Executes `SELECT 1 FROM ...` queries against the target DB (MIMIC-IV) to check existence.
  - Filters out IDs with 0 counts.

## 4. Deliverables
- Functional `Agent 1` that produces IR.
- Functional `Agent 2` that takes text/code -> returns validated, pruned OMOP Concept IDs.
- Unit tests for Regex, Search, and Decomposition logic.
