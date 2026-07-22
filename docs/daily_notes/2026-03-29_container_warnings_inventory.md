# Container Warnings Inventory — 2026-03-29

## Summary

Three recurring warnings observed in `artemis-api` container logs. None are blocking, but two warrant follow-up.

| # | Warning | Severity | Action Required |
|---|---------|----------|-----------------|
| 1 | Redis connection refused (localhost:6379) | Low | Optional: add Redis or suppress warning |
| 2 | Neo4j `MAPS_TO` relationship type does not exist | Medium | Import missing vocab relationships or remove from query |
| 3 | ONNX Runtime cpuid_info + no providers | Informational | No action needed |

---

## 1. Redis Connection Refused (localhost:6379)

**Log message (example):**
```
ConnectionRefusedError: [Errno 111] Connection refused
RegistryStore: Redis unavailable, falling back to in-memory store
```

**Impact:**
No functional impact on concept mapping or cohort generation. The in-memory fallback works correctly for single-instance deployments. However, registry state (e.g., running job metadata) is not persisted across container restarts.

**Root cause:**
No Redis container is defined in `docker-compose.yml`. The `RegistryStore` implementation attempts a Redis connection at startup and silently falls back to in-memory.

**Fix options:**
- Option A (preferred for dev): Suppress the warning if in-memory is acceptable. Add a config flag like `REGISTRY_BACKEND=memory` to skip the Redis attempt entirely.
- Option B (for production): Add a Redis service to `docker-compose.yml` and set `REDIS_URL=redis://redis:6379`.

**Status:** No immediate action required. In-memory mode is sufficient for current development usage.

---

## 2. Neo4j `MAPS_TO` Relationship Type Does Not Exist

**Log message (example):**
```
WARNING: Relationship type `MAPS_TO` does not exist in the database.
KG expander query returned 0 results for MAPS_TO traversal.
```

**Impact:**
KG expansion misses `MAPS_TO` traversals during concept set building. This reduces mapping coverage for criteria where the target concept is reachable only via `MAPS_TO` edges (e.g., non-standard → standard concept bridging). Effect is a slight undercount of mapped concepts — criteria that rely on this path may resolve to fewer standard concepts.

**Root cause:**
The Neo4j database (`artemis-neo4j-v2`) was populated from OMOP vocabulary tables but the `concept_relationship` import did not include rows where `relationship_id = 'Maps to'`. The KG expander in `artemis/src/agents/conceptset/` queries:

```cypher
MATCH (c1:Concept)-[:MAPS_TO]->(c2:Concept) WHERE c1.concept_id = $id
```

Because the `MAPS_TO` edge type was never created, Neo4j issues a warning and returns zero rows.

**Fix options:**
- Option A (recommended): Re-import OMOP `concept_relationship` rows filtered to `relationship_id IN ('Maps to', 'Mapped from')` into Neo4j and create `MAPS_TO` relationship edges.
- Option B: Remove `MAPS_TO` from KG expander traversal queries if the ChromaDB + UMLS path already covers this mapping path sufficiently. Validate against gold standard before removing.

**Status:** Needs investigation. Ablation study recommended to measure recall impact before deciding.

---

## 3. ONNX Runtime cpuid_info Warning + No Providers

**Log messages (example):**
```
onnxruntime: Unknown CPU vendor, falling back to generic implementation
onnxruntime: No ONNX providers provided, defaulting to available providers: ['CPUExecutionProvider']
```

**Impact:**
Performance only. ONNX Runtime falls back to the CPU execution provider, which is the correct and expected behavior for the development environment (Apple Silicon Mac running inside a Docker container via Colima). No correctness impact on embeddings or reranking.

**Root cause:**
ONNX Runtime's `cpuid_info` module does not recognize the ARM architecture reported by the Apple Silicon CPU (via Colima's VM). This is a known upstream limitation. The "No ONNX providers provided" message is a secondary informational log — ONNX selects `CPUExecutionProvider` automatically as the default.

**Fix:**
No fix required. This is expected behavior in the local development environment. If GPU acceleration becomes a requirement in production, configure `CUDAExecutionProvider` or `CoreMLExecutionProvider` explicitly via the ONNX session options.

**Status:** Informational only. No action needed.

---

## References

- `artemis/src/agents/conceptset/` — KG expander implementation
- `artemis/src/utils/vector.py` — ChromaDB + embedding client
- `artemis/src/agents/conceptset/rag_search.py` — retrieval pipeline
- `CLAUDE.md` section "ChromaDB for Mapping Agent" — volume mount and collection details
