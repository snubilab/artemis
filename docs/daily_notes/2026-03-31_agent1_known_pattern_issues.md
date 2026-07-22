# Agent1 Known Pattern Issues — 2026-03-31

## Issue 1: Pattern E — OR Group Detection (FIXED)

**Status**: Fixed in `fix/agent1-pattern-e-or-logic` branch  
**File**: `artemis/src/agents/agent1/prompts.py`

### Problem
Agent1 emitted OR-type eligibility criteria as separate flat AND inclusion rules.

**Trigger phrases NOT covered before fix:**
- `"with or without X"` (e.g., "ACS with or without ST-elevation")
- Conditional sub-type paths (e.g., "STEMI patients requiring PCI OR NSTE-ACS patients")

**Before fix (PLATO example):**
```
Rule 3: ST-Elevation Myocardial Infarction  → ALL (AND)
Rule 4: Non-ST-Elevation Myocardial Infarction → ALL (AND)
Rule 5: Unstable Angina → ALL (AND)
→ Impossible to satisfy simultaneously → 0 patients
```

**After fix:**
```
Rule 2: ACS type (Type=ANY, 3 sub-groups: STEMI OR NSTEMI OR UA)
→ 75 patients pass through ✅
```

**Root cause**: `NCT_DECOMPOSITION_PROMPT` Rule 12 only covered `"≥1 of"` / `"at least one of"` patterns. Added `"with or without"`, `"either...or"`, `"including X, Y, or Z"`, conditional sub-type path patterns.

**Affected studies**: PLATO (NCT00391872). LEADER/ARISTOTLE unaffected (stable at 387/395 patients).

---

## Issue 2: Conditional Criterion — NOT YET FIXED

**Status**: Open  
**File**: `artemis/src/agents/agent1/prompts.py`

### Problem
Eligibility criteria that are **conditional on patient subgroup** (e.g., only applies to female patients) are generated as **universal inclusion rules** applying to all patients.

**Example (PLATO L03):**
```
Original trial criterion:
  "Females of childbearing potential must have a negative pregnancy test"
  → Condition: ONLY if patient is female AND of childbearing age
  → Male patients: criterion is irrelevant (auto-satisfied)

Agent-generated CIRCE:
  InclusionRule: "Negative pregnancy test"  ← applied to ALL patients
  → Patients without a pregnancy measurement record → excluded
  → 75 patients → 0 patients
```

### Pattern Types
This applies to any criterion with structure:
- `"If [condition], then [requirement]"` — e.g., "If female → pregnancy test"
- `"[Subgroup] must have [requirement]"` — e.g., "Females must have..."
- `"[Requirement] for [subgroup]"` — e.g., "Contraception required for women of childbearing potential"

### Correct CIRCE Representation
Conditional criteria should be modeled as:
```json
{
  "name": "Negative pregnancy test (females of childbearing age only)",
  "expression": {
    "Type": "ANY",
    "Groups": [
      { "Type": "ALL", "CriteriaList": [{"Gender": "Female"}, {"HasMeasurement": "pregnancy_test_negative"}] },
      { "Type": "ALL", "CriteriaList": [{"Gender": "Male"}] }
    ]
  }
}
```
OR simply exclude this criterion entirely if it cannot be modeled correctly (many datasets lack pregnancy test records).

### Impact
- PLATO: L03 = 0 (all 75 patients lost)
- Potentially affects any trial with conditional criteria for female patients, pediatric patients, etc.
- Common in: cardiovascular trials, oncology trials, trials with drug-drug interaction warnings

### Recommended Fix
Add Pattern F to `NCT_DECOMPOSITION_PROMPT`:
> When a criterion is conditional ("if [subgroup], then [requirement]"), model it as an OR group:
> (subgroup AND requirement) OR (NOT subgroup)
> OR flag it with `conditional: true` and skip CIRCE generation for it.

---

## Summary Table

| Issue | Pattern | PLATO Impact | Fix Status |
|---|---|---|---|
| OR group detection | Pattern E | L02: 0→75 patients ✅ | **Fixed** |
| Conditional criterion | Pattern F (new) | L03: 75→0 patients ❌ | **Open** |

