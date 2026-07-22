# Shared Context: Anchor & Climb

## Key Types (from existing codebase)

### KGConcept (src/agents/agent2/kg_expander.py)
```python
@dataclass
class KGConcept:
    concept_id: int
    concept_name: str
    domain_id: str
    vocabulary_id: str
    concept_class_id: str = ""
    relationship: str = ""       # e.g., "descendant", "sibling", "ancestor"
    separation: int = 0
    # NEW field to add:
    descendant_count: int = 0    # Number of descendants in CONCEPT_ANCESTOR
```

## Files to Modify
1. `src/agents/agent2/kg_expander.py` — Add ancestors to `expand()`, add `descendant_count`
2. `src/agents/agent2/retriever.py` — Relax `_PENALIZED_CLASSES` for exact query matches
3. `src/agents/agent2/workflow.py` — Already has adaptive limit, may need minor adjustments

## Neo4j Queries for Reference

### Get ancestors (already exists)
```cypher
MATCH (a:Concept)-[r:HAS_DESCENDANT]->(d:Concept {concept_id: $concept_id})
WHERE r.min_levels_of_separation <= $max_sep
RETURN a.concept_id AS cid, a.concept_name AS name, ...
```

### Count descendants (NEW)
```cypher
MATCH (c:Concept {concept_id: $concept_id})-[r:HAS_DESCENDANT]->(d:Concept)
RETURN count(d) AS descendant_count
```

## Constants
- MAX_ANCESTOR_SEP = 2 (climb at most 2 levels up)
- ANCESTOR_LIMIT = 5 (max ancestors to add as candidates)
