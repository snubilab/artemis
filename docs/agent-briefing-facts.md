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

## Reading the gold standard

`data/gold/<TRIAL>/` (TROY v1.1) is the reference, **not an oracle**. Measured
defects in it: `gte` where a protocol says "above N x ULN"; ARISTOTLE's SBP/DBP
sets referenced with no bound at all; EMPA-REG's HbA1c carrying an `Extent` that
`gte` ignores; four Measurement-absence criteria with no value filter. Where you
and gold disagree, **the protocol line decides**.

## What the delivery gate does and does not check

It checks whether a **missing** criterion is accounted for. It does not check
whether a **surviving** criterion is clinically sound. ARISTOTLE passed at 2/12
while carrying an exclusion that removed every patient who had ever had a platelet
count. The lints in `src/utils/circe_lint.py` are where soundness checks belong.

## Measures

- Concept-set quality is scored **per eligibility criterion, 1:1,
  macro-averaged** — never micro or pooled. The two invert.
- **The macro resolution floor is about ±0.02.** A single near-tie concept pick
  moves a trial by 0.022. Report a smaller delta as below the floor, not as an
  improvement.
- **`conceptset_overlap_eval.py` reads only concept sets.** It cannot see a value
  bound, so every bound correction scores exactly 0.0000 — not "no improvement",
  *not measurable*. `bound_agreement` in the same script is the measure for that.
