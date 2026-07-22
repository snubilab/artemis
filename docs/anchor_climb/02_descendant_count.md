# Task: Add descendant_count to KGConcept

## 1. Specification (Strict)
- Input: Each `KGConcept` returned by expand()
- Output: `KGConcept.descendant_count: int` populated for ancestor candidates
- Logic:
  1. Add `descendant_count: int = 0` field to `KGConcept` dataclass
  2. In `get_ancestors()`, extend the Neo4j query to also count descendants:
     ```cypher
     MATCH (a:Concept)-[r:HAS_DESCENDANT]->(d:Concept {concept_id: $concept_id})
     WHERE r.min_levels_of_separation <= $max_sep
     OPTIONAL MATCH (a)-[:HAS_DESCENDANT]->(desc:Concept)
     WITH a, r, count(desc) AS desc_count
     RETURN a.concept_id AS cid, a.concept_name AS name, ..., desc_count
     ```
  3. Populate `descendant_count` in the returned `KGConcept` objects

## 2. TDD Strategy
- [ ] Test Case A: get_ancestors() returns objects with descendant_count > 0
- [ ] Test Case B: KGConcept dataclass accepts descendant_count field

## 3. Implementation Log
- (pending)

## 4. Final Status
- [PENDING]
