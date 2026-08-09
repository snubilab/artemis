# Experiment — 2026-08-09: what the entry-drug exact match actually buys

Paired 2-arm measurement of 991c11c (`expected_domain in ("Drug", None)`), scored
per eligibility criterion 1:1, closure overlap, against `data/gold/`.

## Question

The Addendum of `2026-08-09_single_domain_ir_loses_drug_arms.md` lists 7 zero-overlap
pairs as "mapped to the wrong entity" and names `_exact_ingredient_mapping` as the
place to start. Does ungating it fix them, and is the change attributable to the gate
rather than to anything else that landed since the store was built?

## Design

Full regeneration was rejected, not skipped. The gate is reached by exactly one concept
set per study — the PrimaryCriteria drug that `_build_seeded_target_circe` maps from
`targetCohortName`. Regenerating six trials would re-derive ~370 unchanged concept sets
to observe a change in two of them, at hours of local vLLM time, while folding in every
commit landed since 2026-08-04 and destroying the attribution.

Instead both arms are exported from the **same** deliverable store
(`tmp/tte_six_deliver/studies.json`, 2026-08-04) through the same exporter, on the same
day, against the same vocabulary:

- **Arm B (control)** — store unmodified → `output/circe_arm_b`
- **Arm A (treatment)** — entry concept set re-mapped through the production mapper by
  `scripts/rebuild_entry_concept_sets.py` → `output/circe_arm_a`

Parity was verified by md5, not assumed: of the six exported CIRCE files, **four are
byte-identical** between arms and only CARMELINA and CAROLINA differ.

Scoring: `scripts/conceptset_overlap_eval.py --mode closure --vocab-schema synthea23m`,
identical flags for both arms.

### The control that was nearly wrong

`tmp/circe_b/` was the obvious control and would have contaminated the comparison. A
fresh export of the deliverable store gives ARISTOTLE 43 concept sets / 35 inclusion
rules; `tmp/circe_b`'s manifest says 40 / 31, and the ARISTOTLE md5s differ
(`98425868…` vs `22f45104…`). It was exported from a different store. The Addendum's
baseline numbers are computed on it, so they are not comparable to the arm-B column
below.

## Pre-registered prediction

Written before scoring: the linagliptin pairs go 0.0 → ~1.0, every other pair is
unchanged, and the six-trial macro recall rises by about +0.03. A larger move would mean
something other than the gate had changed and the number should be distrusted.

## Result

| trial | recall B | recall A | Δ | precision B | precision A | Δ |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| ARISTOTLE | 0.636 | 0.636 | +0.000 | 0.357 | 0.357 | +0.000 |
| CARMELINA | 0.473 | **0.573** | **+0.100** | 0.439 | **0.539** | **+0.100** |
| CAROLINA | 0.470 | **0.548** | **+0.079** | 0.432 | **0.511** | **+0.079** |
| EMPA-REG OUTCOME | 0.370 | 0.370 | +0.000 | 0.391 | 0.391 | +0.000 |
| LEADER | 0.585 | 0.585 | +0.000 | 0.613 | 0.613 | +0.000 |
| PLATO | 0.869 | 0.869 | +0.000 | 0.717 | 0.717 | +0.000 |
| **six-trial macro** | **0.567** | **0.597** | **+0.030** | | | |

Zero-overlap pairs 109 → 104 over 238 pairs. Exactly five pairs moved, all linagliptin:

```
CARMELINA  [TROY intervention] Linagliptin        rec 0.000 -> 1.000   prec 0.000 -> 1.000
CARMELINA  [TROY intervention] Linagliptin (ATC)  rec 0.000 -> 0.997   prec 0.000 -> 1.000
CAROLINA   linagliptin                            rec 0.000 -> 1.000   prec 0.000 -> 1.000
CAROLINA   [TROY intervention] Linagliptin        rec 0.000 -> 1.000   prec 0.000 -> 1.000
CAROLINA   [TROY intervention] Linagliptin (ATC)  rec 0.000 -> 0.997   prec 0.000 -> 1.000
```

The prediction held, including the +0.030. The four untouched trials moving by exactly
0.000 is the parity evidence: nothing else drifted into the number.

## What this does NOT fix, and why not

**The 7 "wrong entity" pairs are two defects, not one.** Five are the gate. The other two
are `glimepiride` in CAROLINA, and they are misfiled in the Addendum's table.

That criterion's description is *"Hypersensitivity to investigational product or
glimepiride"* — a hypersensitivity, so Agent 1's `domain="Condition"` is defensible and
the mapper faithfully searched Condition. The defect is that its `sourceText` normalized
down to the bare drug name, which is the dropped-qualifier class C, upstream of the
mapper. Forcing an ingredient match here would require dropping the domain check, and
that measurably breaks four legitimate criteria: `Calcitonin`, `Creatinine`, `Glucose`
and `glucose` are Measurement criteria named after the analyte ("Calcitonin >= 50 ng/L",
"Creatinine > 2.5 mg/dL") that also match an ingredient name exactly.

**A sixth wrong entry drug, previously unlisted.** EMPA-REG's target is `BI 10773`,
empagliflozin's development code, and it is mapped to `1254065 CHF-6366 .beta.-2
metabolite`. Exact match cannot help — no RxNorm Ingredient carries that name, so it
correctly falls through to the embedding path that produced the wrong answer. This needs
a development-code / synonym route and is untouched here.

**Three entry drugs were already right.** apixaban, liraglutide and ticagrelor resolved
correctly on the embedding path. Five seeds newly reach the exact matcher, but only two
change an answer — worth stating because counting seeds that fire, rather than answers
that change, would have reported this as a 5-set improvement.

## Attribution

Still unproven: that embedding search fails on proper nouns *because* same-class drugs
sit close in the vector space. What is now shown is narrower — for these two seeds the
embedding path returns a different molecule of the same class, and exact matching
returns the right one. `ARTEMIS_DISABLE_EXACT_INGREDIENT_MATCH=1` exists as the control
arm for the wider claim; it has not been run.

## Reproduce

```bash
cd /home/bilab/work/projects/Broadsea/artemis
DATABASE_URL=postgresql://postgres:mypass@localhost:5432/postgres CDM_SCHEMA=synthea_cdm \
  .venv/bin/python scripts/rebuild_entry_concept_sets.py \
    --store tmp/tte_six_deliver/studies.json --out output/arm_a_store/studies.json
.venv/bin/python scripts/export_circe_from_store.py --store output/arm_a_store/studies.json --out output/circe_arm_a
.venv/bin/python scripts/export_circe_from_store.py --store tmp/tte_six_deliver/studies.json --out output/circe_arm_b
for ARM in a b; do
  .venv/bin/python scripts/conceptset_overlap_eval.py --mode closure --vocab-schema synthea23m \
    --generated-dir output/circe_arm_$ARM --out output/conceptset_overlap/closure_arm_$ARM.json
done
```

`output/` is gitignored, so the scored artifacts are not in the tree; the commands above
rebuild them. `tmp/` is root-owned and not writable by the run user, which is why the arm
stores live under `output/`.
