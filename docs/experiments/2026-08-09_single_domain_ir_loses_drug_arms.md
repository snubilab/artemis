# Experiment Log — 2026-08-09: a one-domain IR field loses gold's drug arms

## Question

Concept-set recall against gold is 0.141 across the six trials. Is the loss in
extraction (Agent 1 never sees the criterion) or downstream (Agent 2 maps it badly)?

## Method

Closure overlap against `data/gold/<TRIAL>/`, resolved the way Circe resolves
(`src/services/conceptset_closure.py`), no CDM involved. Then trace the largest
misses back through the generated CIRCE and the arm-B IR store.

Artifacts: `output/conceptset_overlap/closure_circe_b.json`,
`/app/tmp/circe_b/` (artemis-api), `/app/tmp/tte_arm_b_postfix/studies.json`.

## Result — six trials

| trial | gold sets | ours | matched | recall | precision |
| --- | --- | --- | --- | --- | --- |
| ARISTOTLE | 38 | 40 | 24 | 0.087 | 0.863 |
| CARMELINA | 37 | 30 | 20 | 0.286 | 0.433 |
| CAROLINA | 56 | 77 | 38 | 0.228 | 0.664 |
| EMPA-REG | 39 | 76 | 23 | 0.051 | 0.316 |
| LEADER | 45 | 58 | 26 | 0.196 | 0.484 |
| PLATO | 23 | 90 | 13 | 0.700 | 0.235 |
| **union** | | | | **0.141** | **0.503** |

The averages hide that the trials fail in opposite directions: ARISTOTLE is
precision 0.86 / recall 0.09, PLATO is recall 0.70 / precision 0.24. Two separable
failure modes, not one.

**Recall is dominated by missing drug-class sets.** 24 unmatched gold sets are drug
sets, 243,208 concepts. For ARISTOTLE the unmatched gold sets are 92.7% of the gold
union, and two sets are 87% of it on their own: `Antihypertensive drugs` (111,910)
and `OADs and injectable diabetes medicine` (31,576).

**Precision is spent on over-expanded labs.** Gold uses one concept where we use
tens to hundreds: `Old MI` 1 → 211, `Fasting glucose` 1 → 205, `Systolic blood
pressure` 1 → 34. 26 lab sets over-expanded, 542 excess concepts.

## Where the drug arms go

Not a domain-coverage problem: we emit a comparable number of drug sets
(ARISTOTLE gold 8 / ours 4, CAROLINA 16 / 18, PLATO 7 / 8), and the ones we do emit
can be exact — our `Aspirin` closure is 10,720, byte-for-byte gold's `[TROY] aspirin`.

Gold's ARISTOTLE risk-factor rule pairs a condition with a drug:

```
r0  AT_LEAST 1 of:
 ├─ ConditionOccurrence  cs88   Stroke, TIAs, and systemic embolism
 ├─ ConditionOccurrence  cs89   CHF or LV dysfunction
 ├─ ALL[ ConditionOccurrence cs92  hypertension
 │       DrugExposure        cs93  Antihypertensive drugs ]
 └─ ALL[ ConditionOccurrence cs90  Diabetes mellitus
         DrugExposure        cs117 OADs and injectable diabetes medicine ]
```

"Hypertension **requiring pharmacological treatment**" is a condition AND a drug
exposure, because the protocol requires the patient to be on treatment.

Our IR for the same criterion:

```json
{
  "id": 11,
  "description": "Hypertension requiring pharmacological treatment",
  "sourceText": "Hypertension",
  "domain": "Condition"
}
```

Three lines, three facts:

1. `description` **retains** `requiring pharmacological treatment`. Agent 1 read the
   protocol correctly — this is not an extraction failure.
2. `sourceText` is truncated to `Hypertension`, and concept-set mapping reads
   `sourceText`. The drug signal is discarded before Agent 2 sees anything.
3. `domain` is a single string, `Condition`. The IR **cannot represent** a criterion
   that needs two domains, so Agent 2 was never asked for antihypertensives.

Diabetes (`id=10`) is identical. Agent 2 did not map badly; it was not asked.

## A second, different shape — LEADER

LEADER does emit a drug set for the same requirement (`Naive or OADs/Insulin`,
6,214 concepts) but gold's is 21,487 — under-expanded ~3.5x. So LEADER is "asked and
answered too narrowly", not "never asked". Any fix must handle both.

Also seen: LEADER emits `Naive or OADs/Insulin` **twice** as two separate concept
sets. Not investigated.

## Conclusion

The dominant recall loss is a **representation** limit, not a model limit. One
`domain` string per criterion cannot express gold's routine "condition AND drug"
idiom. Prompt tuning cannot fix it; the IR schema has to carry more than one domain,
and the mapper has to read the richer text.

## Open before changing anything

- Blast radius of a multi-domain IR field: `domain` is read by `tte_service`
  (`DEMOGRAPHIC_DOMAINS`, `_seeded_criteria_key`, the mapping fan-out), Agent 2, the
  Atlas TTE UI via `src/api/models/tte.py`, and the tests.
- Is `sourceText` truncation a separate, independently shippable fix? It may recover
  part of the loss without touching the schema.
- How general is the condition+drug idiom across all six gold trials? ARISTOTLE
  shows 2 instances; the count elsewhere is unmeasured.
- Whether the lab over-expansion (precision) shares a cause with any of this, or is
  wholly separate.

Related: `docs/debugging/2026-08-09_benchmark_cdm_is_not_an_oracle.md`,
`../omx_wiki/benchmark-cdm-not-an-oracle.md`.
