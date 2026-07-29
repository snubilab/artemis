# ADR-031 value-constraint A/B — six Gold trials, Qwen3.5-4B

Run: `scripts/benchmark_value_constraint_arms.py`, arms assembled from one shared
criterion list per study, `LLM_MODEL=vllm/Qwen/Qwen3.5-4B`, artemis-api container
against the live WebAPI/Neo4j/ChromaDB stack.

## Result

| Study | role | gold RHR | ULN inputs | adr031 RHR | legacy RHR | adr031 VAN | legacy VAN |
|---|---|---|---|---|---|---|---|
| LEADER | control | 0 | 0 | 0 | 0 | 4 | 4 |
| PLATO | control | 8 | 0 | 0 | 0 | 1 | 1 |
| ARISTOTLE | control | 6 | 0 | 0 | 0 | 3 | 3 |
| EMPA-REG OUTCOME | treatment | 6 | 3 | **3** | **0** | 5 | 8 |
| CARMELINA | treatment | 6 | 3 | **3** | **0** | 4 | 7 |
| CAROLINA | control | 6 | 0 | 0 | 0 | 5 | 5 |
| **total** | | **32** | **6** | **6** | **0** | 22 | 28 |

RHR = `RangeHighRatio`, VAN = `ValueAsNumber`. "ULN inputs" counts criteria whose
stored `valueConstraint.unitText` is `x ULN`.

On every constraint it was given, the fix is right and the pre-fix builder is
wrong: 6/6 versus 0/6. Totals conserve — EMPA-REG's VAN drops 8 to 5 and
CARMELINA's 7 to 4, exactly the three that became ratios in each.

The failure being removed is not a formatting difference. `ALT > 3x ULN` compiled
to `ValueAsNumber {Value: 3.0, Op: gt}` — an absolute 3 U/L, which essentially
every patient exceeds. Measured earlier against three hospitals\' CDM, that
emptied the cohort: 2,841 of 2,841 excluded against 24 correct.

## The treatment/control split was not designed, it was discovered

`x ULN` appears in exactly two studies, three times each, on ALT, AST and ALP.
The other four studies carry no reference-bound constraint at all, so both arms
must agree there — and all four did. That is the control this run needed, and it
came free.

## The larger finding: 26 of 32 never reach the builder

Gold uses `RangeHighRatio` 32 times. The pipeline delivered 6 constraints capable
of producing one. The gap is upstream of everything measured here:

- PLATO: gold 8, extracted 0
- ARISTOTLE: gold 6, extracted 0
- CAROLINA: gold 6, extracted 0

These three studies\' stored criteria contain no reference-bound constraint of any
kind, so no builder change could have helped them. The fix is complete for what
it receives, and the remaining 81% is an extraction problem, not an assembly one.

This is also why the arm comparison alone would overstate progress if read as
"the defect is closed". It is closed on the path from IR to Circe. It is open on
the path from protocol text to IR.

## Instrument notes

All 34 stored `valueConstraint` objects have `reference_bound = None` — they
predate ADR-031\'s field. The fix still recovers them because
`build_measurement_value_filter` falls back to `split_reference_bound(unit_text)`
for legacy IR. Had it not, this run would have measured nothing and printed the
same clean table.

The legacy arm reproduces `_build_value_constraint` at 5379743 verbatim rather
than checking that commit out, because 5379743 predates the model-routing and
reasoning-preprocessing fixes and cannot run a local model at all. Those are
instrument defects, not the intervention.

Concept mapping contributes no signal to this contrast: `install_arm()` swaps a
function that runs after mapping, and both arms share one mapping via the
criterion cache. Mapping is what the run spends its time on, not what it measures.

## Open

- 204 `Ingredient rollup skipped` warnings during this run (Postgres
  `connect_timeout=3` under high mapping concurrency). Harmless to the arm
  contrast — both arms share the mapping and RHR does not depend on rollup — but
  it silently changes concept sets, so a *model* comparison would read it as a
  model difference. Concurrency is now bounded at 48 (89b0b71); the effect has
  not been re-measured.
- `_apply_self_reflection_filter` has never dropped anything: the critic emits
  `concept_id`, `relevant` and `reasoning`, and none of the reflection fields the
  filter reads. The 1,830 `assessment=correct` log lines are `.get()` defaults.
- Only one model measured. hari and gemma3 not yet run.
