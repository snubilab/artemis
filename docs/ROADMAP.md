# ARTEMIS 3.1 Development Roadmap

Based on the technical specification, the development of ARTEMIS 3.1 is divided into four main phases.

## Phase 1: Semantic Intelligence (Weeks 1-3)
**Goal**: Build the core intelligence for mapping natural language to OMOP Concept IDs.

- **Key Objectives**:
  - Implement Hybrid Search (Regex + Vector DB).
  - Develop LLM-based Context Reranking (The Judge).
  - Implement Logic Decomposition for combination drugs.
  - Implement Data-Driven Pruning to validate concepts against the database.

## Phase 2: Assembler & Registry Integration (Weeks 4-6)
**Goal**: Integrate the semantic mapping with the cohort assembly process.

- **Key Objectives**:
  - Build the Global Concept Registry (Redis).
  - Implement Agent 3 (Assembler) to generate Circe-be JSON.
  - Implement Agent 4 (Validator) for syntax and logic checking.
  - Establish the data flow: Agent 1 -> Agent 2 -> Agent 3.

## Phase 3: Analysis Engine (Weeks 7-10)
**Goal**: Develop the statistical analysis engine for causal inference.

- **Key Objectives**:
  - Implement Agent 5 (Analysis Agent).
  - Develop Automated Large-Scale Covariate Extraction (HDPS).
  - Implement Outcome Cohort processing (Time-at-Risk, Censoring).
  - Build the Causal Pipeline (PSM/IPTW, Cox Proportional Hazards).

## Phase 4: Reporting & Validation (Weeks 11-13)
**Goal**: Finalize the system with reporting capabilities and end-to-end validation.

- **Key Objectives**:
  - Implement Agent 6 (Reporting Agent).
  - Develop Visualization tools (KM Curves, Forest Plots, Love Plots).
  - Perform End-to-End testing with MIMIC-IV data.
  - Optimize pipeline latency and reliability.
