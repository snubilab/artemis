# Standing facts for delegated work

Every line here cost something to learn in a real session. Read this instead of
rediscovering it; cite it in a brief rather than retyping it.

## The project's question

Does the system turn natural-language eligibility criteria into CIRCE JSON
**correctly**, and is the JSON **free of logical defects**? That is answerable
from the protocol text and the JSON alone, with no database. A patient count
answers "what is in this database", never "did we read the protocol correctly".

## Every CDM on this host is synthetic

`ajou_cdm` / `donga_cdm` / `keimyung_cdm` are built by
`scripts/synthesize_site_cdm.py --persons 10000` — **exactly 10,000 persons each,
which is the tell**. `*_results` are ACHILLES re-run on those stand-ins.
`synthea_cdm` is generator output. Details and the three gaps that each silently
zero a class of criteria: `CLAUDE.md` → EVERY CDM ON THIS HOST IS SYNTHETIC.

A count from any of them is a fact about a fixture. Use them for concept-set
composition and unit codes; never as evidence about a site.

## Shell

- **`cd` does not persist between Bash calls.** Prefix every command, or the
  second one runs in the parent directory and reads the wrong tree.
- **`pgrep -f PATTERN` matches the waiting shell itself**, so a wait loop never
  exits and `pkill -f` can kill the session. Bracket the first character —
  `pgrep -af '[r]eingest'` — in *every* occurrence, including inside echo
  strings. One unbracketed copy re-arms the self-match.
- Wait on a PID captured at launch (`nohup … & PID=$!`, then
  `while kill -0 $PID; do sleep 60; done`), never on a pattern. A completion
  marker proves only that *some* run wrote that path.

## The test suite

Baseline arms are the single largest repeated cost. Use
`scripts/make_baseline_arm.sh` rather than building one by hand.

- `git archive HEAD` alone is **not** a valid arm: ~69 tests resolve paths
  outside the repo (`atlas-dev/`), and others need `.env`, `data/`,
  `chroma_db/`, `tmp/`, `.venv`.
- **`output/` cannot be symlinked wholesale** — `output/circe_be/2026-08-03/` is
  tracked, so `git archive` creates a real directory and the symlink silently
  fails. Overlay its untracked children individually.
- **The tell that an arm is wrong is a skip-count mismatch, not a failure-count
  mismatch.** One arm under-ran 15 corpus-gated tests before anyone noticed;
  another reported three false "new failures" that were `.env`-dependent schema
  reads and live-LLM tests skipping.
- Three tests read their schema from `.env` or make live LLM calls. Without
  `.env` on both arms they show as new failures and are not.
- A full run is ~10 minutes per arm.

## Extraction and the caches

- The Agent 1 IR cache key hashes **the system prompt and the criteria text**, so
  any prompt edit — including a comment — re-extracts every cached trial. A full
  six-study reingest measured 132 minutes.
- **A prompt edit re-rolls roughly a third of a trial's criteria regardless of
  what it says.** A placebo edit (one trailing space) churned more than a real
  one. A whole-batch before/after count is therefore never evidence about a
  prompt change. Use `scripts/prompt_ab.py`, which makes the placebo arm
  mandatory and reports per row.
- **An instruction naming one criterion does not reach it.** A mandatory verbatim
  rename produced a marker appearing **0 times** in the entire IR cache while the
  original name appeared 187. Global, structural instructions do fire. Before
  writing prompt prose for a specific row, check whether a mechanical path owns
  that row instead.
- **Do not run two `prompt_ab.py` arms concurrently** — they share one vLLM and
  halve each other's throughput.

## Reading the corpus

- **Production converts PDFs with plain `pdftotext`, no `-layout`**
  (`src/agents/agent1/parser.py:879`). The two renderings differ *structurally*,
  not cosmetically: `-layout` has indentation and marker hierarchy, production has
  neither. A diagnosis reproduced with `-layout` can be a complete no-op on the
  path production runs. Reuse the harness in `tests/test_corpus_regression.py`.
- **A criterion's `name` is not a stable signal** — the same name string appears
  with both operators across runs. `source_text` is copied verbatim from the
  document and is.

## Document order is destroyed before extraction

`src/agents/agent1/parser.py:80` sorts the criteria list alphabetically, inside a
function named `_normalize_trial_data_for_stable_hash`. Line 289 **rebinds**
`trial_data` to that sorted copy, and lines 302-307 build the model prompt from it —
so the alphabetised list is what the model actually sees, not just what gets hashed.
Deduplication is done by the `seen` set and does not need the sort.

Upstream, `pubmed_fetcher.py:202` sorts blocks by character offset, so the enriched
list reaches line 80 **in document order**. The sort is where that order is lost.

The cost, measured on LEADER's IR cache (`NCT01179048_..._53197d558aff3e94.json`):
20 top-level inclusion rules in alphabetical `source_text` order, of which eleven are
members of an "≥1 of the following" list and two are the orphaned list headers whose
`source_text` still ends in `of the following criteria:`. Circe AND-combines top-level
InclusionRules, so the delivered cohort demands ankle-brachial index **and**
asymptomatic ischemia **and** heart failure **and** renal failure **and** eight more,
simultaneously. It is empty.

This one line accounts for four of the twelve cohort-blocking findings in
`output/site_gap/2026-09-14/conversion_audit.json`.

Two things follow for anyone working here:

- **A criterion's position is evidence and the pipeline throws it away.** A list header
  ends in a colon and names its cardinality ("≥1 of the following", "at least two of").
  Its members are the items that followed it in the document — a relationship that exists
  only in the order.
- **Removing the sort changes the prompt, so it changes the Agent-1 IR cache key.** Budget
  the full six-study re-extraction (~132 min). Any fix here pays that once; there is no
  variant that avoids it.

Not verified: whether `_merge_parsed_items` preserves order when it folds a lighter block
into the heaviest one. Only the heaviest block's own order was confirmed.

## Reading the gold standard

`data/gold/<TRIAL>/` (TROY v1.1) is the reference, **not an oracle**. Measured
defects in it: `gte` where a protocol says "above N x ULN"; ARISTOTLE's SBP/DBP
sets referenced with no bound at all; EMPA-REG's HbA1c carrying an `Extent` that
`gte` ignores; four Measurement-absence criteria with no value filter. Where you
and gold disagree, **the protocol line decides**.

## The prompts quoted the corpus they are evaluated on

Fixed in 623e663; **every score recorded before it is suspect.** All six evaluated
trials had text of their own in the few-shot examples — CAROLINA 10 spans, ARISTOTLE 9,
CARMELINA 8, EMPA-REG 6, PLATO 4, LEADER 2. Full list of affected criteria and the
reasoning in `AGENTS.md` § EVALUATION; do not restate it elsewhere.

Two working rules follow:

- **Count contamination one trial at a time.** A combined run keeps only the longest
  shared span per prompt position and awards it to one document, so a trial that words a
  criterion briefly disappears behind one that words it at length. EMPA-REG read as clean
  that way and is not.
- **A prompt experiment must use a trial outside `EVALUATED_TRIALS`** —
  `data/papers/NCT01730534` (DECLARE-TIMI 58) has protocol text and no gold, which costs
  nothing when the measures are computed against protocol text and the arms themselves.

`tests/test_prompt_corpus_contamination.py` is the gate. Any prompt edit re-runs it for
free (file reads plus `pdftotext`, ~2 s, no LLM, no DB). **Any prompt edit also
invalidates the Agent-1 IR cache key**, so the next extraction re-runs all six trials
(~132 min measured).

## The coverage-gap warning counts across the grouping boundary

`parser.py` Step 5 warns when `output_count < input_count * 0.5`, comparing **input
lines** against **top-level output rules**. A group of k members is k input lines and one
output rule, so the ratio understates coverage by construction.

Measured on the delivery's own reingest: it fired once, on CAROLINA, as
`59 input criteria -> 25 output rules`. The IR for that run holds 30 top-level rules and
**48 nodes** once sub_criteria are counted, against roughly 55 real input lines. A ~13%
gap was reported as 58%.

Two things follow:

- **Do not read that warning as a measured loss.** Count nodes, not top-level rules, and
  subtract the input lines that are not criteria.
- **It is wrong in both directions.** Here it overstated; where a group genuinely absorbs
  a dropped member it will stay silent. A warning that overstates gets ignored, and the
  habit of ignoring it carries into the run where it is right.

Four of CAROLINA's 59 input lines are not criteria at all: the Boehringer copyright
footer, `Criteria for`, `Test product:` and `dose:`. The last two are colon-terminated
headers, which is the shape that produces empty group labels — see the 2026-09-10
colon-header note.

## Condition or Measurement is a real fork, and nothing decides it

Measured against the live vocabulary: **518 standard concept names exist in more than
one of `Condition` / `Measurement` / `Meas Value`.** `Anemia` is both 439777 (Condition,
SNOMED) and 45878117 (Meas Value, LOINC); `Proteinuria` is both 75650 and 45880869. The
pipeline is not choosing badly at random — the vocabulary genuinely offers both and
nothing in the mapping path disambiguates.

**The signal is whether the protocol states a threshold.** A named clinical state with no
number ("known clinically important thrombocytopenia", "acute decompensation of glycemic
control") is a Condition. A measured quantity with a bound ("platelet count ≤
100,000/mm3") is a Measurement **with a value filter**. Sent the wrong way, a Condition
becomes a Measurement with no value condition — and combined with `ABSENCE` that reads as
"the patient has never had this test", which empties the cohort.

**The concept usually exists; the exact name does not.** "Thrombocytopenia" has no
standard concept under that name — only qualified variants (Fetal, Immune, Cyclic,
Uremic, Primary). The canonical one is **432870 `Thrombocytopenic disorder`**. An exact-
name lookup misses it and falls through to platelet LOINC codes, which is how ARISTOTLE's
exclusion came to remove every patient who had ever had a platelet count.

**The bound is often not recoverable, so do not plan to recover it.** Checked in the
store: `Elevated HbA1c` has protocolLine "Acute decompensation of glycemic control";
`Thrombocytopenia` has "Known clinically important thrombocytopenia". Neither line carries
a number, because the protocol leaves the threshold to clinical judgement. The repair is
the domain, not the missing value.

## What the delivery gate does and does not check

It checks whether a **missing** criterion is accounted for. It does not check
whether a **surviving** criterion is clinically sound. ARISTOTLE passed at 2/12
while carrying an exclusion that removed every patient who had ever had a platelet
count. The lints in `src/utils/circe_lint.py` are where soundness checks belong.

## Where a delivery lives

**`output/circe_be/<date>/` is the only delivery location — never invent a
second one.** A run in `output/site_gap/<date>/` is the audit trail and is
never edited after the run; a prepared export in `output/circe_be/<date>/` is
what goes out. **The default delivery is three studies (CARMELINA, CAROLINA,
EMPA-REG), not six** — build the six-study zip only when asked. **Being filed
in `circe_be/` is not evidence anything was sent**: the 2026-08-31 export sat
there complete, with its zip, and was never sent, while the delivery ledger
had recorded it as sent on inference alone until the user corrected it on
2026-09-12. A delivery counts as sent only when the user says so. Full
convention (including the 21-directory/five-spelling anti-pattern this
replaced) and the export command in `AGENTS.md` § WHERE A DELIVERY LIVES; do
not restate it elsewhere.

## Measures

- Concept-set quality is scored **per eligibility criterion, 1:1,
  macro-averaged** — never micro or pooled. The two invert.
- **The macro resolution floor is about ±0.02.** A single near-tie concept pick
  moves a trial by 0.022. Report a smaller delta as below the floor, not as an
  improvement.
- **`conceptset_overlap_eval.py` reads only concept sets.** It cannot see a value
  bound, so every bound correction scores exactly 0.0000 — not "no improvement",
  *not measurable*. `bound_agreement` in the same script is the measure for that.

## Never `git stash` in this checkout

The stash is **repository-global**, so `git stash push` with no pathspec sweeps every
uncommitted file in the tree — including the ones another agent is holding. It happened:
one run swept a concurrent agent's 147-line `scripts/prompt_ab.py` while trying to
snapshot its own three files. It was recovered by `git stash pop`, but the two
measurements taken between the stash and the pop were also wrong, because both arms were
reading the same reverted tree.

To compare against HEAD, copy your own files aside and `git checkout --` only your own
paths, or extract HEAD's version with `git show HEAD:<path> > <somewhere-else>`. Never a
bare `git stash`, and never `git add -A` / `git add .` for the same reason.

Two pre-existing stash entries live here and are paired — `stash@{0}` is labelled
"PAIR of stash@{1} … restore both together". A stray `git stash pop` in the wrong order
destroys that pairing.

## Running work in parallel on this checkout

One agent at a time runs the full test suite. Three concurrent pytest processes
took a 10-minute suite to **34 minutes**, and two `prompt_ab.py` arms on the one
vLLM halved each other's throughput — a 30-minute arm became 95. Both were
self-inflicted by fanning out without asking what the agents would contend for.

Read-only investigation parallelises freely. Anything that runs the suite, holds
the GPU, or writes `src/` does not.
