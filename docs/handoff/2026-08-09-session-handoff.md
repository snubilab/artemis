# Handoff — ARISTOTLE zero-cohort causes + evaluation method change — 2026-08-09

## Goal / context

Diagnose why ARISTOTLE (one of the six-trial benchmark corpus) generates a
0-patient cohort, and fix what's fixable. Along the way, the session found
that the metric used to judge pipeline quality (patient counts against the
Synthea benchmark CDMs) was measuring the wrong thing, and replaced it.

## Current state

- Repo: `/home/bilab/work/projects/Broadsea/artemis` (git root). The
  workspace root `/home/bilab/work/projects/Broadsea` is **not** a git repo
  (`git status` there returns "not a git repository").
- Branch: `fix/tte-a-drug-anchored-entry` · HEAD at correction time: `862a04f`
  (point-in-time; later handoff/doc commits may advance it) · no remote
  configured (`gh pr list` fails with "no git remotes found") — nothing is
  pushed anywhere.
- Uncommitted in the git repo: clean (`git status --short` empty).
- Two stashes exist and must **not** be touched:
  - `stash@{0}` — "PAIR of stash@{1}: tests for sliding-window eligibility (restore both together)"
  - `stash@{1}` — "sliding-window eligibility (ADR-031 CAROLINA misdiagnosis; provably no-op on all 6 studies — see 2026-08-03 handoff)"
- Outside the git repo (workspace root, not committed anywhere because the
  root isn't a git checkout):
  - `/home/bilab/work/projects/Broadsea/omx_wiki/` — compiled knowledge
    layer, includes today's new/updated pages `benchmark-cdm-not-an-oracle.md`,
    `conceptset-eval-unit.md`, `orgroup-judge-experiment.md`, and a rebuilt
    `dashboard.html`.
  - `/home/bilab/work/projects/Broadsea/AGENTS.md` — root-level agent notes
    (distinct from `artemis/AGENTS.md`, which **is** committed in this repo).
- A local vLLM server is **still running**: PID `3672578`,
  `google/gemma-4-E4B-it`, listening on `0.0.0.0:8000`, ~2h50m uptime at
  time of writing (`ps -p 3672578` confirms; `ss -ltnp` confirms the
  listener). Kill with `kill 3672578` if the GPU is needed for something else.
- Test count: **705 or 707, both correct, over different file sets** — resolved
  by re-running per file with `-p no:randomly` (whole-suite numbers are
  explicitly *not* a regression signal in this repo):

  | file set | passed |
  | --- | --- |
  | the 19 files touched by this session's source changes | 705 |
  | + `tests/test_dashboard_site_adaptation.py` (2) | **707** |

  0 failed either way. The earlier `705` in
  `docs/handoff/2026-08-09-state-plain.md` predates the deprecation sweep,
  which is when the dashboard test became relevant to run.
  Note for whoever re-verifies: `pytest` is not on the host `python3` nor in
  the `artemis-api` container — use `.venv/bin/python -m pytest` from
  `/home/bilab/work/projects/Broadsea/artemis`.

## Done this session (11 substantive commits, fixed range `4300eec..a655469`, oldest first)

1. `ab91c60` fix(agent1): route every duplicate decision through one predicate that can see containment
2. `ee921fb` test(scripts): make the OR-group dedup ablation runnable as a two-arm experiment
3. `dc74c60` feat(eval): score concept sets by closure overlap against gold, not by patient count
4. `0736a87` feat(scripts): populate ACHILLES analysis 1815 per CDM for measurement scale checks
5. `11924cf` feat(agent1): add an LLM judge arm for the OR-group decision, and the audit that says not to ship it
6. `ae33f20` docs: record the evaluation rule, the unit provenance, and this session's state
7. `95dc47f` docs(experiments): a one-domain IR field is what loses gold's drug arms
8. `14fe812` feat(eval): make per-criterion 1:1 overlap the measure of record, not concept mass
9. `3a16164` docs(experiments): banner the superseded claims rather than leaving them to be read
10. `8fd1b7f` docs(AGENTS): pin the unit of evaluation, not just its source
11. `a655469` docs(scripts): deprecate the superseded evaluators and relabel the ones with a live consumer

(Verified: `git log --oneline 4300eec..a655469 | wc -l` = 11. Handoff/doc
commits land above `a655469`, so `git log --oneline 4300eec..HEAD | wc -l`
is 12 or more as those commits accumulate. The commissioning brief's 12 did
not match the 11 substantive commits.)

## Key decisions & why

- **ARISTOTLE's 0-patient cohort has five distinct causes**, not one — see
  `docs/handoff/2026-08-09-aristotle-zero-cohort-root-causes.md` (causes 1–4)
  and the plain-language rollup in `docs/handoff/2026-08-09-state-plain.md`
  (adds cause 5). Fixing causes 3+4 together takes the cohort 0 → 788
  (gold: 1,113 patients); either alone leaves it at 0. This is exact bitmask
  arithmetic on the generated CIRCE, not an estimate. Only cause 1 (OR-group
  dedup) has been fixed in code; causes 2, 3, 4, 5 are diagnosed but
  unfixed.

- **Cause 1 fix (`ab91c60`) went through adversarial review** (Codex + a
  Fable workflow) after the first cut, which found three further defects,
  all reproduced then fixed in the same commit:
  1. The "an OR-GROUP candidate is never a duplicate" early return existed
     but wasn't enforced by its callers — `_merge_criteria` dropped the
     richer group anyway via a legacy SequenceMatcher-ratio gate. Both
     merge sites now reach the structural comparison first.
  2. The stopword list erased polarity/conjunction, so "no prior stroke"
     tokenized identically to the positive disjunction and got deleted —
     silently widening the cohort (opposite direction from the original
     bug, harder to notice).
  3. `MIN_CONTENT_TOKENS` had been relaxed 2→1; measured that every verdict
     is identical at 1 vs 2 and that 1 additionally deletes bare criteria
     like "Hypertension"/"Diabetes"/"Stroke". Reverted to 2
     (`src/agents/agent1/criteria_dedup.py:83`), measurement recorded in
     the adjacent comment.
  `ARTEMIS_DISABLE_ORGROUP_DEDUP=1` is a named ablation for a control arm,
  not a fallback.

- **The evaluation method changed, and this is the biggest result of the
  session.** Patient counts against `synthea_cdm_{aristotle,leader,plato}`
  are no longer the measure of record: those CDMs are generated *from*
  `data/gold/` (`scripts/generate_synthea_from_gold.py` inverts each gold
  value constraint and injects one constant per lab), so a patient count
  partly measures the generator's own conventions, not the pipeline. Sharpest
  example: gold writes the platelet exclusion as `100` (thousands/µL), the
  ARISTOTLE protocol PDF writes `100,000/mm3` — both correct, no unit is
  recorded anywhere machine-readable, and the 1000x gap alone zeroes the
  cohort. Full argument in
  `docs/debugging/2026-08-09_benchmark_cdm_is_not_an_oracle.md`.
  The new measure of record: **per-eligibility-criterion 1:1 concept-set
  closure overlap against `data/gold/`, macro-averaged** — not pooled
  concept-mass (micro) overlap. Pinned in `artemis/AGENTS.md` (EVALUATION
  section), implemented in `scripts/conceptset_overlap_eval.py`
  (`per_criterion_macro()` at line 355; `per_criterion` printed above the
  micro numbers in output), and mirrored in
  `omx_wiki/conceptset-eval-unit.md`.
  **The two units disagree in direction, not just magnitude**: overall
  micro 0.141 recall / 0.503 precision vs per-criterion 0.542 / 0.484; for
  ARISTOTLE specifically, micro says worst-recall/best-precision
  (0.087/0.863) and per-criterion says the **opposite**
  (0.749 median recall / 0.153 median precision). Do not quote the micro
  number as a headline for anything going forward.

- **14 zero-overlap concept-set pairs** (both sides exist, share no
  concept) fall into three causes, detailed in the Addendum of
  `docs/experiments/2026-08-09_single_domain_ir_loses_drug_arms.md`
  (**read the Addendum, not the body — the body's original conclusions are
  banner-corrected as wrong, computed on the wrong micro unit**):
  - **Wrong entity (7 of 14)**: our `linagliptin` resolves to `sitagliptin`
    (different DPP-4 inhibitor, CAROLINA/CARMELINA); our `glimepiride`
    resolves to three unrelated Condition concepts (CAROLINA). These are the
    trials' own study/comparator drugs — cheapest and most severe defect
    class.
  - **Wrong vocabulary axis (4 of 14)**: gold uses LOINC, we use SNOMED (or
    vice versa) for the same clinical concept (eGFR x2, CrCl, substance
    abuse) — closures never intersect even though both sides mean the same
    thing.
  - **Dropped qualifier (3 of 14)**: gold names one fasting-glucose LOINC
    (3004501); our 205-concept glucose set substitutes OGTT timepoint
    variants and omits the exact one gold wants. Size is not the defect.

- **An LLM judge for the OR-group dedup decision was built, audited, and
  explicitly NOT shipped.** Three arms (lexical/current, local vLLM
  `google/gemma-4-E4B-it`, `gpt-4o`) scored at n=28 against the same rubric:
  not statistically separable (McNemar p=0.6875), and the table structurally
  can never separate them (only 4 of 28 rows are discriminating regardless
  of how many more are drawn — diagnosed as a corpus/procurement problem,
  not a judge-quality problem: the gold six trials contain zero of the
  "exclusion-vs-exclusion comparison" cases that would be needed).
  `DEFAULT_ARM = ARM_LEXICAL` in
  `src/agents/agent1/criteria_dedup_judge.py:78`; the LLM arm is reachable
  only via env var `ARTEMIS_ORGROUP_JUDGE` (confirmed in that file and in
  `tests/test_criteria_dedup_judge.py`). Two things the experiment did
  establish, worth keeping: (1) the lexical defect is real — same gold
  concept set, same group, "Peripheral occlusive arterial disease" fires
  but "Peripheral artery disease" doesn't, word-order-sensitive; (2) the
  local 4B model's verdicts were byte-identical to `gpt-4o`'s on all 28
  rows, i.e. this particular judgment doesn't need a paid model.

- **Do NOT change the IR schema to a list-valued `domain`.** The IR already
  expresses condition+drug conjunction via `Criteria.sub_criteria` +
  `group_type="ALL"` (confirmed: `src/models/ir.py:95-96`). A list-valued
  `domain` would silently disable Agent 2's scalar gates —
  `domain_hint == "Drug"` (`workflow.py:297`,
  `concept_set_refiner.py:205`) and `domain_hint in ("Drug", None)`
  (`workflow.py:421`) — and reintroduce the exact drug-arm loss under
  investigation, plus crash `atlas-dev` `tte-manager.js:2339` on
  study load. The actual gap is an Agent 1 prompt gap (`prompts.py:480-489`
  teaches `sub_criteria` only under `group_type:"ANY"`), not a schema gap.

- **Do NOT switch the concept mapper from `sourceText` to `description`.**
  Measured on a 36-criterion A/B: ARISTOTLE antihypertensives recovered 0 of
  111,910 concepts; PLATO's exact ingredient closures went 2,879 → 0; noise
  +45%. The stored `sourceText` is not a truncation — it's Agent 1's
  normalized `entity_text` (`tte_service.py:9574`); the genuinely verbatim
  `Criteria.source_text` (`ir.py:87`) is dropped before it reaches the
  store, so no consumer can read it today either way.

- **Superseded evaluators were deprecated in place, not deleted**: header
  comments + `__main__`-guarded stderr banners added to
  `scripts/run_gold_vs_ai_comparison.py`,
  `scripts/run_gold_vs_ai_injection_analysis.py`,
  `scripts/benchmark_v6_cohort.py`,
  `scripts/plot_gold_vs_ai_survival_curves.py` (all four confirmed to carry
  a `# DEPRECATED 2026-08-09.` header). 11 more scripts were relabelled
  (not deprecated — they still have a live consumer). The dashboard chain
  was re-run afterward and `comparison.json` md5 was reported unchanged
  (not independently re-verified in this session's checks above).

## Open work (in the order the session's docs recommend)

1. **The 7 wrong-entity mappings** — cheapest, most severe, start here.
   `_exact_ingredient_mapping` exists at `src/services/tte_service.py:5804`
   (confirmed); find why it did not fire for `linagliptin`/`glimepiride`.
   Hypothesis in the experiment doc: embedding search returns a semantic
   neighbour for same-class drugs, and a proper noun needs exact match
   first — but this needs verification, not just implementation.
2. **Cause 3 gate**: exclusion concept set swallowing the enrollment
   condition — diagnosed, no code written.
3. **Cause 5 gate**: concept set that's clinically sound but matches 0 rows
   in the target CDM — diagnosed, no code written.
4. **Cause 2**: `synthea_cdm_aristotle.procedure_occurrence` has 0 rows
   against 21,000 persons. Decide: populate it, or mark ProcedureOccurrence
   criteria unevaluable for this CDM.
5. **Agent 1 conjunction extraction** (`prompts.py` Rule 12b) — recovers
   ARISTOTLE's two condition+drug nodes specifically; low value elsewhere
   (the pattern occurs exactly twice in the whole six-trial corpus, both in
   ARISTOTLE, though those two nodes are 87.9% of ARISTOTLE's gold concept
   mass).
6. **Agent 2 drug-class decomposition** — the general lever behind the 23
   under-expanded drug arms across all six trials (broader payoff than #5).
7. Kill the orphaned vLLM job (PID 3672578) if the GPU is needed, or leave
   it if more `orgroup_judge` arm runs are planned.
8. Decide whether/how to get `omx_wiki/` and the workspace-root `AGENTS.md`
   under version control — they currently have no home in any git history.

## How to verify / run

```bash
cd /home/bilab/work/projects/Broadsea/artemis
git log --oneline 4300eec..HEAD | cat        # session commit list
git stash list                                # confirm both stashes still present, untouched
ps -p 3672578 -o pid,etime,cmd                # confirm/kill the orphaned vLLM job
kill 3672578                                  # only if GPU is needed elsewhere

# Tests: per-file with -p no:randomly (repo convention; requires pytest,
# not available on this host or in the artemis-api container as checked —
# find the right venv/container before trusting any run)
pytest tests/<file>.py -p no:randomly -v

# Re-derive the metric-direction table (micro vs per-criterion)
python scripts/conceptset_overlap_eval.py   # check --help for trial/output flags
```

Key docs to read in full before touching code (all under
`/home/bilab/work/projects/Broadsea/artemis/`, not the decoy checkouts
`artemis-eval-baseline/` or `artemis-codex-fixes/`):
- `docs/handoff/2026-08-09-state-plain.md` — plain-language rollup of all 5 causes
- `docs/handoff/2026-08-09-aristotle-zero-cohort-root-causes.md` — causes 1–4 detail
- `docs/experiments/2026-08-09_single_domain_ir_loses_drug_arms.md` — **read the Addendum, the body above it is banner-corrected as wrong**
- `docs/debugging/2026-08-09_benchmark_cdm_is_not_an_oracle.md` — why patient counts against the benchmark CDMs mislead
- `AGENTS.md` EVALUATION section — the pinned evaluation rule
- `output/orgroup_judge/` — LLM-judge experiment raw data (28-row JSONL per arm + manifest)

## Gotchas / constraints

- Never cite paths under `artemis-eval-baseline/` or `artemis-codex-fixes/`
  — decoy near-identical checkouts, not the working tree.
- Never quote the micro (pooled concept-mass) overlap number as a headline
  — it inverts ARISTOTLE's conclusion. Per-criterion 1:1 macro-average is
  the measure of record.
- Don't touch `stash@{0}`/`stash@{1}` — they're a paired sliding-window
  eligibility change + its tests, deliberately shelved (provably a no-op on
  all 6 studies per the 2026-08-03 handoff), meant to be restored together
  or not at all.
- `omx_wiki/` and the workspace-root `AGENTS.md` live outside any git
  checkout (the Broadsea workspace root itself is not a git repo) — edits
  there are not protected by version control.
- Whole-test-suite pass/fail counts are explicitly not trusted as a
  regression signal in this repo; run affected files individually with
  `-p no:randomly`.
