# The trial benchmark CDMs are not an oracle — 2026-08-09

Evidence behind the evaluation rule in `AGENTS.md`: patient counts against
`synthea_cdm_{aristotle,leader,plato}` measure the benchmark generator's
conventions as much as they measure the pipeline. Concept-set overlap against
`data/gold/` does not.

## How those CDMs are built

`scripts/generate_synthea_from_gold.py` reads the gold CIRCE, inverts each value
constraint so a generated patient *satisfies* the rule, and injects the result as
a Synthea observation. `_negate_value_in_requirements` does the inversion:
`LE → GT` adds `1.0`, `LT → GE` adds `0.5`, `GT → LE` subtracts `0.5`.

Running that backwards over `synthea_cdm_aristotle.measurement` recovers gold's
thresholds exactly:

| lab | injected value | gold op | recovered gold threshold | our extraction | match |
| --- | --- | --- | --- | --- | --- |
| Platelets (3007461) | 101.0 | `lte` | 100 | **100,000** | **1000x off** |
| Creatinine (3016723) | 2.0 | `gt` | 2.5 | 2.5 | ok |
| Hemoglobin (3027484) | 9.5 | `lt` | 9 | 9 | ok |
| CrCl (3027108) | 25.5 | `lt` | 25 | 25 | ok |

Each lab is a single constant repeated across 2,458 rows, placed one generator
step on the "not excluded" side of its threshold. The benchmark's intended answer
is *no lab criterion excludes anybody*.

## Why platelets diverges, and why nobody is wrong

Gold writes `100` — the lab/OMOP convention, thousands per microlitre. The
ARISTOTLE protocol PDF writes `100,000/mm3` — the clinical-paper convention. Both
state the same clinical threshold. The CDM is generated *from gold*, so its values
carry gold's convention; Agent 1 reads the *protocol*, so it carries the paper's.
The three other labs agree only because gold and the paper happen to share a unit
there.

Nothing records the unit anywhere machine-readable. `unit_concept_id` is `0` and
`unit_source_value` is the literal string `unit`, which is
`generate_synthea_from_gold.py:958`'s fallback firing — proof that gold carries no
`Unit` for these constraints either. The information never existed outside a
human's head.

## Value distributions cannot recover it

Two schemes were tried and both fail, for the same structural reason: an exclusion
threshold is a cutoff *in the abnormal tail*, so sitting outside the observed range
is what a correct threshold looks like.

- "rescale by a power of 10 into `[min, max]`" — unsatisfiable. No power of 10 puts
  100,000 inside `[101, 101]` (this CDM) or inside `[168.6, 447.3]`
  (`synthea_cdm_results` Achilles 1815, the correctly-united reference).
- "nearest power of 10 of threshold/median" — the residual conflates the unit
  factor with the tail position, and the ordering inverts:

| case | correct action | residual from nearest 10^k |
| --- | --- | --- |
| platelets, this CDM (median 101) | rescale /1000 | 0.0043 |
| platelets, reference CDM (median 258.4) | rescale /1000 | 0.4123 |
| creatinine mg/dL vs umol/L (88.4x) | **do not rescale** | 0.0535 |

The case that must be refused scores better than the case that must be accepted, so
no tolerance separates them. This is an identifiability limit, not a tuning problem.

Achilles 1815 remains a sound *detector* — a 990x gap is unambiguous evidence of a
problem — and an unsound *repairer*. Populate it per CDM with
`scripts/achilles_measurement_dist.R`.

## Other ways these CDMs mislead

- `synthea_cdm_aristotle.procedure_occurrence` has 0 rows against 21,000 persons,
  so every ProcedureOccurrence exclusion passes everyone for free.
- Generated concept sets can be clinically sound and still match nothing: cs5
  "Prior stroke, TIA or systemic embolus" resolves to 275 concepts and 0 persons,
  while gold's counterpart matches 584 — the CDM only codes `372924 Cerebral artery
  occlusion`, which cs5 never names. Judged by patient count this reads as a total
  failure; judged by concept overlap it is a recall gap of one concept.

## What to use instead

Closure-level overlap against `data/gold/<TRIAL>/`, expanded through
`concept_ancestor` with `invalid_reason IS NULL` on the descendant side and
`isExcluded` items subtracted (this matches Circe's rendered codeset SQL — verified
by POSTing the expression to `WebAPI /cohortdefinition/sql`).

ARISTOTLE arm B vs `_TROY v1.1_ Apixaban (ARISTOTLE).json`: micro recall 0.087,
precision 0.863, 9 of 38 gold sets with zero overlap. Report per-set recall and
precision; a "best Jaccard match" with no true counterpart must be reported as
*no counterpart*, not as a weak match.
