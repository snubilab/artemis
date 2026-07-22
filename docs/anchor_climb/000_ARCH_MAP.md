# Anchor & Climb: Broad Condition Hierarchy Enhancement

## Project Goal
Add ancestor concept climbing to KG Expander so that broad parent concepts appear
as candidates for the LLM Critic. When the query is "malignant neoplasm", the Critic
should see both specific children AND the broad parent, selecting the right level.

## Tech Stack
- Python 3.11
- Neo4j 5.x (OMOP KG)
- ChromaDB (vector search)
- LLM Critic (Azure OpenAI)
- pytest

## Sub-tasks

| # | Task | Status |
|---|------|--------|
| 01 | Modify `KGExpander.expand()` to include ancestors as candidates | ✅ DONE |
| 02 | Add `descendant_count` metadata to `KGConcept` | ✅ DONE |
| 03 | Relax `_PENALIZED_CLASSES` in retriever for exact query matches | ✅ DONE |
| 04 | Integration test with benchmark V2 | ✅ DONE — Full 24, Wrong 5, Recall 68.3% |

## Dependencies
- 01 and 02 are independent, can be done in parallel
- 03 depends on 02 (needs descendant_count)
- 04 depends on all
