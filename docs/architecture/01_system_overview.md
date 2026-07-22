# System Architecture Overview

## Introduction
ARTEMIS 3.1 is designed as a modular, multi-agent system. It leverages the OHDSI tech stack (OMOP CDM, Circe, FeatureExtraction) while adding a layer of "Semantic Intelligence" to automate the translation of clinical questions into rigorous evidence.

## High-Level Architecture
The system operates in a linear flow managed by a **LangGraph** orchestrator.

### 1. Input Layer
- **User Interface**: CLI or Web Frontend (TBD).
- **Input**: Natural Language Question or Clinical Trial Protocol (NCT ID).

### 2. Cohort Definition Phase (The "Translator")
Responsible for converting vague text into executable SQL.
- **Agent 1 (Logic Decomposer)**: Natural Language Understanding (NLU).
- **Agent 2 (Intelligent Mapper)**: Terminology Mapping (Text -> Concept ID).
- **Agent 3 (Assembler)**: JSON Construction (Concept ID -> Circe JSON).
- **Agent 4 (Validator)**: Quality Assurance (JSON Syntax & Logic Check).

### 3. Evidence Generation Phase (The "Researcher")
Responsible for executing the study on patient data.
- **Agent 5 (Analysis Agent)**: Statistical Analysis (Covariate Extraction -> PSM -> Cox).
- **Agent 6 (Reporting Agent)**: Interpretation & visualization.

## Key Infrastructure
- **Orchestration**: LangGraph (State Machine).
- **Knowledge Graph**: Redis (Global Concept Registry).
- **Data Layer**:
  - **Vector DB**: ChromaDB (for semantic search).
  - **CDM**: PostgreSQL (MIMIC-IV / OMOP CDM).
