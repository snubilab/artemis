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

---

# Addendum — the metric was wrong, and it inverted the conclusion

Everything above this line was computed as a **micro average over pooled concept ids**.
That is the wrong unit. Re-scored per eligibility criterion, 1:1, macro-averaged:

| | micro (concept mass) | per criterion 1:1 |
| --- | --- | --- |
| overall recall | 0.141 | **0.542 mean / 0.500 median** |
| overall precision | 0.503 | **0.484 mean / 0.457 median** |
| ARISTOTLE recall | 0.087 | **0.749 median** |
| ARISTOTLE precision | 0.863 | **0.153 median** |

ARISTOTLE reads as "worst recall, best precision" under micro and as the **opposite**
per criterion. Its micro recall was set by one 111,910-concept antihypertensive set we
never build; its micro precision by one 10,720-concept aspirin set that matches gold
exactly. Neither says anything about the other forty criteria.

Recall distribution over the 144 matched pairs — a third are perfect, which the pooled
number erases completely:

```
1.0  perfect   48
0.8-1.0        11
0.5-0.8        19
0.2-0.5        17
0-0.2          35
0.0            14
```

Coverage: 144 of gold's 238 concept sets (61%) got a counterpart at all; 94 got none.

## The 14 zero-overlap pairs — three distinct causes

Both sides exist, and they share **no concept**. Invisible in any pooled figure
(linagliptin's 301 concepts are under 2% of our 16,625-concept union), and the sharpest
defect class in the corpus.

### A. Mapped to the wrong entity — 7 of 14

| trial | gold wants | we built |
| --- | --- | --- |
| CAROLINA, CARMELINA (5 rows) | `linagliptin` RxNorm Ingredient | **`sitagliptin`** — a different DPP-4 inhibitor |
| CAROLINA (2 rows) | `glimepiride` RxNorm Ingredient | `Poisoning caused by sulfonylurea`, `Hypoglycemic event due to diabetes`, `Drug-induced hypoglycemia` — all **Condition** |

These are the trials' own study and comparator drugs. Not a granularity problem: a
wrong molecule and a wrong domain. Likely shape: embedding search returned a
semantic neighbour, since same-class drugs sit close in the vector space, and a proper
noun needs exact match first. `_exact_ingredient_mapping` exists at
`src/services/tte_service.py:5804` — why it did not fire is the next thing to check.

### B. Right meaning, wrong vocabulary axis — 4 of 14

| item | gold | ours |
| --- | --- | --- |
| eGFR (x2) | LOINC `Lab Test`, 5 | SNOMED `Observable Entity` / `Procedure`, 11 |
| CrCl | LOINC `Lab Test`, 3 | different LOINC + SNOMED mixed, 8 |
| substance abuse | SNOMED **Condition**, 3 | LOINC **Observation** surveys, 11 |

Both sides mean the same clinical thing and neither is an ancestor of the other, so the
closure intersection is empty. `substance abuse` is worse: the domain differs, so the
CIRCE criterion queries a different CDM table entirely.

### C. Qualifier dropped — 3 of 14

```
gold  3004501  Glucose [Mass/volume] in Serum or Plasma
ours  3028247  Glucose [Mass/volume] in Serum or Plasma --30 minutes post dose glucose
ours  1616656  Glucose [Mass/volume] in Serum or Plasma --30 minutes post dose arginine
```

Gold names one fasting-glucose LOINC. We emit 205 glucose concepts and **omit that
one**, substituting OGTT timepoints. Size is not the defect — the set is 205x gold and
still misses the answer. Smoking is the same shape (gold: one Condition + one
Observation; ours: 18 `cigarette smoking` concepts, zero shared).

## What the Fable investigation settled

**Do not change the IR schema.** The IR already represents condition+drug:
`Criteria.sub_criteria` + `group_type="ALL"` (`src/models/ir.py:95-96`),
`_criteria_from_ir` flattens a composite into sibling rows sharing a `groupId` each
keeping its own scalar `domain` (`tte_service.py:9523-9553`), and
`_build_grouped_inclusion_rule` (`4307-4352`) emits exactly gold's
`ALL[ConditionOccurrence, DrugExposure]`. We already emit 16 mixed-domain rules and 19
mixed-domain IR groups. What we emit **zero** of, across all 191 rules, is the
multi-domain presence *conjunction*. That is an Agent 1 prompt gap
(`prompts.py:480-489` teaches `sub_criteria` only with `group_type:"ANY"`), not a
schema gap.

A list-valued `domain` would have been actively harmful: every Agent 2 gate is a scalar
equality (`domain_hint == "Drug"` at `workflow.py:297` for ATC expansion, `:421` for
ingredient rollup), so a list evaluates False and **silently disables the drug
pipeline** — reintroducing the exact loss being fixed. It also crashes
`tte-manager.js:2339` on study load. An additive field is dropped by the Atlas save
whitelist (`tte-manager.js:3820-3846`).

**Do not switch the mapper from `sourceText` to `description`.** Measured over a
36-criterion A/B on local vLLM: ARISTOTLE antihypertensives recovered 0 of 111,910;
PLATO's exact ingredient closures went 2,879 → 0; noise +45%; and 93% of the apparent
gains were cross-domain concepts on criteria whose CIRCE table can never match them.
Two premises of the section above are also corrected by it: ARISTOTLE `id=10` has
`description == sourceText == "Diabetes mellitus"` (the OAD signal was lost at Agent 1,
not by truncation), and LEADER's under-expanded drug set already has an empty
`sourceText`, so it is *already* description-fed and still under-expands 3.5x.

Also: the stored `sourceText` is not a truncation but Agent 1's normalized
`entity_text` (`tte_service.py:9574`), and the genuinely verbatim `Criteria.source_text`
(`ir.py:87`) is dropped on the way into the store, so no consumer can read it today.

**Concentration, stated honestly.** The condition+drug conjunction occurs exactly twice
in the whole six-trial corpus, both in ARISTOTLE. Those two nodes are 87.9% of
ARISTOTLE's gold union and 42.5% of the six-trial gold mass, and zero elsewhere. The
multi-domain idiom is general (25 nodes) but its *pairs* are Condition+Procedure 10x,
Condition+Measurement 8x, Condition+Drug only 2x. Any general fix must handle procedure
and measurement arms, not just drug.

## Next, in order of evidence

1. **The 7 wrong-entity mappings.** Cheapest and most severe: a trial's own study drug
   resolving to a different molecule. Start at `_exact_ingredient_mapping`.
2. **Agent 1 conjunction extraction** (`prompts.py` Rule 12b) — recovers ARISTOTLE's
   two nodes, worth little elsewhere.
3. **Drug-class decomposition** in Agent 2 — the general lever behind the 23
   under-expanded arms.
