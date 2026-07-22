# Task: Add Ancestors to KG Expand Candidates

## 1. Specification (Strict)
- Input: `concept_id: int`, `strategy: str = "clinical"`, `max_sep: int = 3`, `limit: int = 50`
- Output: `List[KGConcept]` — now includes ancestors with `relationship="ancestor"`
- Logic:
  1. In `KGExpander.expand()`, after the existing clinical strategy logic (descendants, siblings, maps_to)
  2. Call `self.get_ancestors(concept_id, max_sep=2)` 
  3. Add returned ancestors to the `results` list
  4. Existing dedup logic handles the rest

## 2. TDD Strategy
- [ ] Test Case A: expand() on a known leaf concept → ancestors appear in results
- [ ] Test Case B: expand() on a top-level concept → no ancestors added (already root)
- [ ] Test Case C: ancestors are properly deduped if also found via siblings

## 3. Implementation Log
- (pending)

## 4. Final Status
- [PENDING]
