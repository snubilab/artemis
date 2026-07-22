# Task: Relax Penalized Classes for Exact Matches

## 1. Specification (Strict)
- Input: query_text, candidate concept_name, concept_class_id
- Output: Adjusted penalty score (0 instead of penalty if exact match)
- Logic:
  1. In `retriever.py`, find where `_PENALIZED_CLASSES` penalty is applied
  2. Add exception: if normalized `concept_name` matches normalized `query_text`, skip penalty
  3. This ensures "Malignant neoplasm" (Clinical Finding class) is NOT penalized when query IS "malignant neoplasm"

## 2. TDD Strategy
- [ ] Test Case A: "malignant neoplasm" query → "Malignant neoplasm" concept is NOT penalized
- [ ] Test Case B: "diabetes" query → "Clinical Finding" class concept IS still penalized (not exact match)

## 3. Implementation Log
- (pending)

## 4. Final Status
- [PENDING]
