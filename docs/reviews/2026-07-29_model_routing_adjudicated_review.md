# Model-routing review — adjudicated
Three adversarial reviewers, then an adjudicator that reproduced or refuted every
finding by executing it. Outbound HTTP was intercepted so no billed call was made.
Verdicts are CONFIRMED / REFUTED / UNSETTLED, not opinions.

---

# Review 1 — the critic fix

Done. Report below.

---

# Silent-substitution audit: ARTEMIS main + eval-baseline

Method: every claim below marked **REPRODUCED** was executed. Claims marked **MECHANISM CONFIRMED / CANNOT FIRE TODAY** were executed and shown to be inert under the current config. Nothing was modified.

---

## 1. REPRODUCED — The two benchmark arms resolve `VLLM_BASE_URL` to different machines, and `run_model.py`'s own guard against this is skipped

The highest-ranked finding: it changes what a two-arm results table means, and the recorded provenance is empty rather than wrong.

Each checkout has its own `.env`, and they disagree:

| checkout | `VLLM_BASE_URL` | live status |
|---|---|---|
| `artemis` (arm 2) | `http://100.66.233.6:8000/v1` | serving `google/gemma-4-31B-it` |
| `artemis-eval-baseline` (arm 1) | `http://61.107.200.12:8000/v1` | **dead, HTTP 000** |

Reproduced with a clean env (`env -u VLLM_BASE_URL -u LLM_MODEL`), running `src.settings` from each directory:

```
cwd=.../artemis                 settings.VLLM_BASE_URL = 'http://100.66.233.6:8000/v1'
cwd=.../artemis-eval-baseline   settings.VLLM_BASE_URL = 'http://61.107.200.12:8000/v1'
```

The chain that makes this invisible, in `artemis-eval-baseline/scripts/model_eval/run_model.py`:

```python
base_url = args.vllm_base_url or os.environ.get("VLLM_BASE_URL", "")
...
probe = probe_server(base_url, args.model) if base_url else None
if probe is not None and not probe.get("matches_requested"):
    parser.error(...)
```

The shell has `VLLM_BASE_URL` unset (verified). With no `--vllm-base-url`, `base_url` is `""`, so `probe` is `None` and the comment's promise — *"Refuse to start against a server that is not serving the requested model"* — never executes. The child then gets `env = dict(os.environ)` (no `VLLM_BASE_URL`) and `cwd=str(checkout)`, so `load_dotenv()` in `src/settings.py` picks up **that checkout's** `.env`.

This is not hypothetical — both real runs on disk show it:

```
output/model_eval/baseline/gpt-4o/run_meta.json
   vllm_base_url = ""
   server_probe  = null
```

Those two runs used `--model gpt-4o`, so the endpoint was irrelevant *for them*. The mechanism is armed for the next `vllm/` sweep.

Mitigating: the baseline's endpoint being fully dead means that arm would fail every call and trip `MAX_LLM_ERROR_RATE`, aborting loudly. The silent case is the one that matters — two arms, two *live* servers with different weights, quantization or `max_model_len`. `run_meta.json` records `""` and `null`, so nothing in the output would distinguish it.

Files: `artemis/.env`, `artemis-eval-baseline/.env`, `artemis-eval-baseline/scripts/model_eval/run_model.py` (`main()`), `artemis/src/settings.py:6`.

---

## 2. REPRODUCED — Criterion cache key omits the LLM model; the container has it enabled with 61 live entries

`src/agents/agent2/criterion_cache.py` — key is `SHA256(normalize(text) | domain | EMBEDDING_MODEL)`. The LLM model is not in it. Executed:

```
LLM_MODEL=gpt-4o                     -> b4267468bf0c20d4dbbeaf22
LLM_MODEL=vllm/snuh/hari-q3-8b       -> b4267468bf0c20d4dbbeaf22
LLM_MODEL=vllm/google/gemma-4-31B-it -> b4267468bf0c20d4dbbeaf22
```

Live cache state (`artemis/tmp/tte/criterion_cache.sqlite`, root-owned, written by the container):

```
61 entries, 61 unexpired; last_accessed 2026-07-22 14:57 .. 2026-07-29 00:35
```

All 61 were produced under the container's `LLM_MODEL=gpt-4o`. TTL is 24h. Change the container's `LLM_MODEL` to a local model and re-run through Atlas within the window, and Agent 2 mapping results come back from gpt-4o with a `[CACHE HIT]` log at INFO and an artifact that looks entirely normal.

Two things make this worse than it first appears:

- **The disable flag is unreachable from the shell in one harness.** `CRITERION_CACHE_ENABLED` is *not* in `ALLOWED_RUNTIME_ENV` in `scripts/quick_concept_benchmark_v2.py`, which does `os.environ.clear()` then refills only from that allowlist. Exporting `CRITERION_CACHE_ENABLED=false` before that harness is deleted, and the value reverts to its `"true"` default.
- **`run_model.py` is protected by accident.** It sets `CRITERION_CACHE_ENABLED=false` (which *is* honoured — `tte_service.py:5871` gates both `get` and `put` correctly), and separately `TTE_STORE_PATH` is a fresh per-repeat directory so `_default_db_path()` lands on a new DB anyway. Two independent protections, neither documented as load-bearing.

Note `CRITERION_CACHE_ENABLED` is read inside the cache class only in `stats()` — `get()` and `put()` do not check it. The gating lives entirely in the caller. Any future caller that forgets is unguarded.

---

## 3. MECHANISM CONFIRMED / CANNOT FIRE TODAY — `get_llm` silently substitutes `gpt-4o-mini` for any model name not containing "gpt"

`src/utils/llm.py:300`, inside the OpenAI-direct branch:

```python
model=model if "gpt" in model else "gpt-4o-mini",
```

Executed, forcing the fall-through:

```
=== VLLM_BASE_URL present (normal) ===
  vllm/x        -> ChatOpenAI(model='google/gemma-4-31B-it', base='http://100.66.233.6:8000/v1')
=== VLLM_BASE_URL dropped ===
  vllm/x        -> ChatOpenAI(model='vllm/google/gemma-4-31B-it', base='https://openrouter.ai/api/v1')
=== ...and OPENROUTER absent, OPENAI present ===
  vllm/x        -> ChatOpenAI(model='gpt-4o-mini', base='None')
  Qwen/Qwen3-8B -> ChatOpenAI(model='gpt-4o-mini', base='None')
```

No exception, no log line, no record. Real completions from the wrong model.

**It cannot fire in the current configuration**: `OPENAI_API_KEY` is unset and `OPENROUTER_API_KEY` is set, so Option 2 short-circuits before Option 4 is ever reached (verified — `OPENAI key set = False` in both checkouts). It is one `.env` edit away, and it is the same defect class as the critic literal, sitting in the file designated as the single source of routing truth.

Second-order, same lines: **`ReasoningStrippedChatModel` is applied only in the vLLM branch.** In the run above, path A returned an object with `.inner`; paths B and C returned a bare `ChatOpenAI`. Routing a reasoning model through OpenRouter (`qwen/qwen3-8b` is a valid OpenRouter id) means no `/no_think` is appended and `<think>` blocks are not stripped — straight into `JsonOutputParser`, which is the failure the wrapper's docstring exists to prevent.

---

## 4. REPRODUCED — The container pins the critic to gpt-4o, so the fix does not apply inside `artemis-api`

`compose/artemis-api.yml:31`:

```yaml
# gpt-4o-mini not deployed on Azure AI Foundry — force gpt-4o for critic
AGENT2_CRITIC_MODEL_TIER: gpt-4o
```

Verified live:

```
artemis-api  LLM_MODEL                = gpt-4o
artemis-api  VLLM_BASE_URL            = http://61.107.200.12:8000/v1   <-- the dead one
artemis-api  AGENT2_CRITIC_MODEL_TIER = gpt-4o
artemis-api  CRITERION_CACHE_ENABLED  = <unset in container>
```

Under the new `select_critic_model()`, `tier="gpt-4o"` hits the final `return tier` → literal `"gpt-4o"` → no `vllm/` prefix → OpenRouter. So inside the container, `LLM_MODEL` still does not move the critic — the exact property the fix was meant to establish. Less severe than the original (it is a single pin, not a domain-conditional split, and it is declared in version-controlled compose), but no recorder runs in the container, so nothing in an Atlas-generated artifact reveals it.

Also note the container's `VLLM_BASE_URL` matches the **baseline** `.env`, not the host's — a third value in circulation for the same setting.

---

## 5. REPRODUCED — `git_commit` in `run_meta.json` is dirty-blind

`run_model.py` records `git rev-parse HEAD`. The baseline worktree:

```
recorded git_commit = bc33ccca183eae23a62155d4e2a00be29687da7b
actual HEAD         = bc33ccca183eae23a62155d4e2a00be29687da7b
tree dirty?         = 9 modified/untracked entries
git diff --stat src/agents/agent2/critic.py -> 1 file changed, 28 insertions(+), 12 deletions(-)
```

The recorded commit asserts a tree state that did not run. `prompt_fingerprint` *does* hash `critic.py` (it is in `PROMPT_SOURCES`), so a reader who knows to compare fingerprints can detect it — but `git_commit` alone is a false provenance claim, and it is the field a reader will reach for first.

This directly affects the decision described in the brief: applying the critic fix inside the baseline worktree is defensible as an instrument repair, but the artifact records the arm as `bc33ccc`, which is the unfixed code.

---

## 6. REPRODUCED — `LLMCostTracker` prices unknown models at gpt-4o rates

`src/utils/llm.py:36` — `costs = _MODEL_COSTS.get(model, _MODEL_COSTS["gpt-4o"])`. Executed:

```
1M in + 1M out on a LOCAL model billed as: 12.5 USD
same tokens on gpt-4o                    : 12.5 USD
```

`result["llmCostTracker"]` is written into every per-study `result.json`. A local-model run reports fabricated OpenAI pricing for tokens that cost nothing. A cost column in a model-comparison table would be meaningless and would look plausible.

`score_run.py` gets this right (`rate = PRICE_PER_TOKEN.get(model); if rate:` — unknown models contribute 0), so the scorer is clean. Only the per-run file lies.

---

## 7. REPRODUCED — Main checkout's `quick_concept_benchmark_v2.py` still drops `VLLM_BASE_URL`, and its results file records no model

The allowlist fix exists **only in the baseline worktree, uncommitted**. In the main checkout:

```
rg VLLM scripts/quick_concept_benchmark_v2.py  ->  NO VLLM REFERENCE AT ALL
```

`ALLOWED_RUNTIME_ENV` ends at `AGENT2_CRITIC_MODEL_TIER`; `bootstrap_runtime_env()` does `os.environ.clear()` then refills only allowlisted keys from shell and `.env`. So `VLLM_BASE_URL` is destroyed from both sources, and `LLM_MODEL=vllm/...` takes the path verified in finding 3B — a literal `vllm/...` model name sent to OpenRouter.

Provenance in the results file: the only `LLM_MODEL` occurrence in the whole script is the allowlist entry at line 77. The `critic_model_tier` field that the baseline's uncommitted diff adds to `save_progress`/`save_results` is **not** in main. Main writes `mappers`, `domains`, `aggregate` — and no record of which model produced any of it.

---

## 8. REPRODUCED — Timeouts and errors become empty predictions, scored as wrong answers

`scripts/quick_concept_benchmark_v2.py:363`:

```python
if worker.is_alive():
    return [], latency_ms, f"timeout after {timeout_s:.1f}s"
```

`DEFAULT_LLM_TIMEOUT_S = 45.0` is unchanged. An empty prediction set scores 0.000 on recall — in the score column, indistinguishable from a model that answered and was wrong. The same applies to every caught exception (`except BaseException` → `pred_ids = []`).

Partially mitigated: `error_count` *is* aggregated per mapper and per domain (lines 926, 957) and per-row `error` is retained (line 1011). The information is in the file. It is not in the score.

Also at line 1105: `run_llm_rag_pass(sample, args.llm_timeout, results["GPT54 RAG"], "gpt-5.4", checkpoint)` — a hardcoded model literal. Labelled by the arm name, so honest, but it bypasses `LLM_MODEL` and if `gpt-5.4` is not a valid OpenRouter id every call errors into the empty-prediction path above and that arm scores 0.000 across the board.

---

## 9. Remaining hardcoded models and no-provenance results writers

Of the scripts that both invoke an LLM and write a results file:

| script | model provenance in output |
|---|---|
| `scripts/quick_concept_benchmark_v2.py` | 1 ref (allowlist only — none in results) |
| `scripts/quick_concept_benchmark.py` | none |
| `scripts/run_medgemma_benchmark.py` | none (hardcodes `vllm/medgemma-27b-it`, `vllm/medgemma-1.5-4b-it` at lines 40-41) |
| `scripts/probe_criterion_classifier.py` | none (`MODEL = "vllm/snuh/hari-q3-8b"` at line 39 → `get_llm(MODEL)` at 328) |
| `scripts/build_diagnosis_data.py` | none |

`scripts/compare_criteria_across_models.py` hardcodes `"gpt-4o"` as the reference arm in seven places (lines 265-462).

`probe_criterion_classifier.py` is currently inert: the served model is `google/gemma-4-31B-it`, and vLLM rejects a mismatched id (see below), so it 404s loudly rather than substituting.

---

## Checked and ruled out

These looked like candidates and are not:

- **vLLM silently answering with whatever it has loaded.** Tested with a live POST of `model: "snuh/hari-q3-8b"` to the gemma server: `404 NotFoundError — "The model 'snuh/hari-q3-8b' does not exist."` It refuses. This is why `run_model.py`'s missing probe (finding 1) degrades to a loud failure rather than a silent one when the model is simply absent.
- **`.env` overriding exported environment variables.** `load_dotenv()` defaults to `override=False`, and pydantic-settings ranks env above dotenv. Verified: shell-exported `LLM_MODEL`/`VLLM_BASE_URL` win. The leak in finding 1 is the *absence* of the shell value, not an override.
- **MedCPT querying a MiniLM-indexed collection.** Host `.env` and container both say `EMBEDDING_MODEL=medcpt`, and `src/utils/vector.py:63` routes medcpt to a separate collection `f"{name}_medcpt"` with its own embedding function. No cross-space query.
- **`score_run.py` cost fabrication.** Correctly skips unknown models.
- **Criterion cache gating in `tte_service.py`.** Both the lookup (5871) and the store (5952) are inside `if _cache_enabled`.
- **`select_critic_model` divergence between checkouts.** Now logically identical. One cosmetic difference: the baseline's signature is still `-> str` while it can return `None`; main's is `-> str | None`. No runtime effect.

---

## Ranking, by "could this silently change what a results table means"

1. **Finding 1** — different endpoints per arm, guard skipped, provenance blank. Armed now for the next `vllm/` sweep.
2. **Finding 2** — model-blind cache, live in the container with 61 unexpired entries, disable flag unreachable in one harness.
3. **Finding 7** — main's harness still drops `VLLM_BASE_URL` and records no model at all.
4. **Finding 4** — container critic pinned, no recorder to reveal it.
5. **Finding 5** — `git_commit` claims a tree that did not run; directly affects the baseline-arm fix decision.
6. **Finding 6** — fabricated cost in every `result.json`.
7. **Finding 8** — timeout/error becomes a score rather than an exclusion.
8. **Finding 3** — inert today, one `.env` edit from being the worst of the set.
9. **Finding 9** — hardcoded models in scripts whose outputs carry no model label.

The load-bearing observation across findings 1, 2 and 7: **the same setting has three different values in circulation** (`VLLM_BASE_URL` = `100.66.233.6` on host, `61.107.200.12` in baseline `.env` and in the container), and the mechanism that was supposed to catch that — `probe_server` — is gated behind the very variable that is missing.

---

# Review 2 — leak hunt

## Verdict on the critic fix itself

The fix is correct. `select_critic_model() -> None -> get_llm(None)` genuinely reaches the local server, the caller branch is right, and the main checkout's log line is honest in both branches. Verified by construction, not by reading:

```
$ LLM_MODEL="vllm/snuh/hari-q3-8b" artemis/.venv/bin/python /tmp/criticprobe/probe_route.py .../artemis Condition
  select_critic_model: null
  llm_object: {wrapper: ReasoningStrippedChatModel, callable_type: ChatOpenAI,
               model: "snuh/hari-q3-8b", base_url: "http://100.66.233.6:8000/v1"}
```

`/tmp/criticprobe/probe_e2e.py` runs `ConceptCritic.evaluate()` end to end with `BaseChatOpenAI._generate` stubbed, and compares the model the log **claims** against the model that **actually generated**. Honest in all four (checkout × tier) cells.

Everything below is what surrounds it.

---

## Findings, ranked by how silently they fail

### 1. The main checkout's own tests make live billed OpenRouter calls, and one passes only because of it — CONFIRMED

`artemis/tests/test_interaction_regression.py:50` still patches `select_critic_model` to return `"gpt-4o"`. That was the old "use the default chain" sentinel. Under the new `if model_name is not None` branch it does the opposite: it builds a **real** chain and the carefully-injected `mock_chain` on `critic._default_chain` never runs. Commit `e719d0f` updated `test_map_002_m3_critic_reflection.py` and missed this file.

```bash
cd /home/bilab/work/projects/Broadsea/artemis
.venv/bin/python -m pytest tests/test_interaction_regression.py -q
#   9 passed, 3 warnings in 8.00s          <-- green

PYTHONPATH=/tmp/netguard .venv/bin/python -m pytest tests/test_interaction_regression.py -q
#   1 failed, 8 passed in 4.80s
#   FAILED ...::TestEvaluateKGPreservationIntegration::test_mixed_kg_non_kg_filtering
#   === NETGUARD: outbound HTTP attempted ===
#       POST https://openrouter.ai/api/v1/chat/completions
```

(`/tmp/netguard/sitecustomize.py` patches `httpx.Client.send` to record and block.)

This is the maximum-silence shape: `pytest -q` is green, three tests are non-hermetic, and one of them asserts on whatever live gpt-4o returned. The 8.0s vs 4.8s delta is the round trips. Fix is one word — `return_value=None`.

### 2. The baseline worktree has 9 failing tests and the same billed egress — CONFIRMED

`critic.py` was patched inside the worktree; its tests were not.

```bash
cd /home/bilab/work/projects/Broadsea/artemis-eval-baseline
.venv/bin/python -m pytest tests/test_perf_m4_critic_model_tiering.py \
                          tests/test_map_002_m3_critic_reflection.py -q
#   9 failed, 11 passed
PYTHONPATH=/tmp/netguard .venv/bin/python -m pytest \
  "tests/test_map_002_m3_critic_reflection.py::TestCriticSelfReflection::test_domain_mismatch_detected" -q
#   ERROR [Critic] Evaluation failed: Connection error.
#   === NETGUARD === POST https://openrouter.ai/api/v1/chat/completions
```

Seven `TestAutoModeTiering` failures are stale expectations (they assumed `auto` was the default). Two `TestCriticSelfReflection` failures are the same `"gpt-4o"` sentinel as finding 1. The measuring arm of the benchmark is currently in a state where its own suite does not pass, and nothing enforces that it does — the guard suite `test_model_selection_is_uniform.py` **does not exist in the baseline worktree**.

### 3. The baseline's benchmark harness re-pins the critic to OpenAI, so the fix is a no-op in that arm — CONFIRMED

`artemis-eval-baseline/scripts/quick_concept_benchmark_v2.py` (uncommitted) adds:

```python
os.environ.setdefault("AGENT2_CRITIC_MODEL_TIER", "gpt-4o")
```

That predates the critic fix and now defeats it. Running each checkout's own harness bootstrap verbatim under identical operator env:

```bash
env LLM_MODEL="vllm/snuh/hari-q3-8b" VLLM_BASE_URL="http://100.66.233.6:8000/v1" \
  $CO/.venv/bin/python /tmp/criticprobe/probe_bootstrap.py $CO
```

| checkout | `select_critic_model("Condition")` | wire model | endpoint | IS_LOCAL |
|---|---|---|---|---|
| `artemis` | `None` | `snuh/hari-q3-8b` | vLLM | **true** |
| `artemis-eval-baseline` | `"gpt-4o"` | `gpt-4o` | openrouter.ai | **false** |

Same operator command, same model label, two different providers on 90% of items. Before the fix both arms were contaminated the same way; now the contamination is **asymmetric**, which is worse for a comparison.

### 4. `run_model.py` force-pins the tier for both arms — CONFIRMED, partially mitigated

`artemis-eval-baseline/scripts/model_eval/run_model.py:387`:

```python
env["AGENT2_CRITIC_MODEL_TIER"] = "gpt-4o"   # unconditional; an operator export cannot win
```

`--checkout` points at either tree, so **every** `run_model.py --model vllm/...` run sends Agent-2 concept selection to OpenAI regardless of arm. The critic fix has zero effect on this benchmark.

Mitigations that exist: `run_meta.json` records `"critic_tier_forced": "gpt-4o"`, and `install_recorder` wraps `BaseChatOpenAI._generate` so critic calls land in `stage_calls.jsonl` and surface in `score_run.py`'s `models_used`. So it is *recorded*. It is not *visible* in the headline `"model"` field. Read `models_used` before believing any arm label.

### 5. The main harness silently discards an exported `VLLM_BASE_URL` — CONFIRMED

`artemis/scripts/quick_concept_benchmark_v2.py:69-101` — `ALLOWED_RUNTIME_ENV` has no `VLLM_BASE_URL` / `VLLM_API_KEY`. The baseline copy added them; the main copy never got the fix.

```bash
env LLM_MODEL="vllm/snuh/hari-q3-8b" VLLM_BASE_URL="http://somewhere-else:8000/v1" \
  artemis/.venv/bin/python /tmp/criticprobe/probe_override.py .../artemis
```
```
1_operator_exported:                 http://somewhere-else:8000/v1
2_after_os.environ.clear()+allowlist: null
3_after_src.settings_load_dotenv():  http://100.66.233.6:8000/v1
5_endpoint_actually_used:            http://100.66.233.6:8000/v1
OPERATOR_OVERRIDE_HONOURED:          false
```

No warning. The export is replaced by `.env`'s host. The two `.env` files name **different** hosts (`100.66.233.6` vs `61.107.200.12`), so the two arms silently talk to different servers.

Sub-finding, same probe: `leaked_non_allowlisted_dotenv_key(GOOGLE_CLOUD_PROJECT): true`. `load_dotenv()` resolves from `src/settings.py`'s own directory, **not** cwd — so the comment at `quick_concept_benchmark_v2.py:217-218` ("searches upward from cwd; running from a neutral directory avoids reloading") is factually wrong, the `chdir("/tmp")` does nothing, and the whole `.env` is reloaded past the allowlist. That accident is the only reason the missing `VLLM_BASE_URL` isn't already breaking runs — it fails exactly when someone tries to override.

### 6. Tier parsing is exact-match and case-sensitive; a typo silently disables the critic — CONFIRMED (both checkouts, identical)

`critic.py:55` (main) / `:63` (baseline): anything that isn't exactly `""` or `"follow"` after `.strip()` becomes a **literal model name**.

```bash
LLM_MODEL="vllm/snuh/hari-q3-8b" artemis/.venv/bin/python /tmp/criticprobe/probe_tiers.py .../artemis
```

| tier value | result |
|---|---|
| unset, `""`, `"   "`, `follow`, `follow `, ` follow` | local vLLM — correct |
| `Follow`, `FOLLOW`, `AUTO`, `Auto` | literal model `"AUTO"` → openrouter.ai |
| `None`, `none`, `null`, `off`, `0`, `true`, `gpt-4o-mimi` | literal → openrouter.ai |
| `auto`, ` auto ` | `gpt-4o-mini` / `gpt-4o` → openrouter.ai |
| `gpt-4o`, `gpt-4o-mini` | → openrouter.ai, real spend, while `LLM_MODEL` is local |

What a bogus name does downstream (`/tmp/criticprobe/probe_badtier.py`, provider 400 simulated):

| tier | concepts returned | KG expansion kept |
|---|---|---|
| `follow` | `[111, 222]` | **true** |
| `AUTO` / `None` / `off` / `gpt-4o-mimi` | `[111]` | **false** |

The blanket `except Exception` at `critic.py:457` swallows it and returns seed concepts. The Agent-2 arm silently degrades to plain vector search — KG expansion discarded, benchmark table complete, numbers lower, one `ERROR` line per item and nothing in the output. This is the third instance of the pattern in the brief.

Note the values people actually type — `AUTO`, `None`, `off`, `false` — all land in the danger column. `"follow"` and `""` are the only safe spellings.

### 7. A stale singleton serves a model nobody asked for, and the log reports the other one — CONFIRMED behaviour, narrow reachability

`_default_chain` is safe under normal operation only because `settings` is a module-level singleton frozen at import (`src/settings.py`, `settings = Settings()`). It is not safe if anything mutates or reloads it in-process. `resolve_model()` reads `settings` **live**; `_default_chain` is **frozen at construction**.

```bash
env -u AGENT2_CRITIC_MODEL_TIER LLM_MODEL="vllm/snuh/hari-q3-8b" \
  artemis/.venv/bin/python /tmp/criticprobe/probe_stale.py .../artemis
```
```
A_before_switch:              log "vllm/snuh/hari-q3-8b"  actual snuh/hari-q3-8b  LOCAL
settings.LLM_MODEL = "gpt-4o"
B_after_switch (singleton):   log "gpt-4o"                actual snuh/hari-q3-8b  LOCAL   <-- log lies
C_fresh ConceptCritic():      log "gpt-4o"                actual gpt-4o           REMOTE
```

Reachability, checked rather than assumed: the HTTP API's per-request `model` (`src/api/tte.py:61,68,82`) is passed as an explicit argument to `get_agent1(model_name=)` / `get_planner(model_name=)`, and both factories correctly return a fresh instance when `model_name is not None`. So this is not reachable from the API. It is reachable from any in-process script or test that mutates/reloads settings. Worth a `logger.info` sourced from the chain's own model rather than from `resolve_model`.

Related provenance gap: that per-request model reaches agent1 and planner but **never** the critic, which always uses process-wide `settings.LLM_MODEL`. A study generated with `model=gpt-4o` and then processed via `/process-eligibility` mixes two models under one label.

### 8. The two checkouts' log lines read different clocks — CONFIRMED

`select_critic_model` is behaviourally identical across all 22 tier values × 2 domains (findings 6 table reproduced identically in both). The only functional delta is the log line:

- main `critic.py:392` — `resolve_model(model_name)` → `settings.LLM_MODEL` (frozen at import)
- baseline `critic.py:397-400` — `os.environ.get('LLM_MODEL', 'gpt-4o')` (live)

```bash
$CO/.venv/bin/python /tmp/criticprobe/probe_logsrc.py $CO   # sets os.environ["LLM_MODEL"]="gpt-4o", no reload
```

| checkout | log claims | actually called | truthful |
|---|---|---|---|
| `artemis` | `vllm/snuh/hari-q3-8b` | `snuh/hari-q3-8b` | **true** |
| `artemis-eval-baseline` | `gpt-4o` | `snuh/hari-q3-8b` | **false** |

A plain `os.environ["LLM_MODEL"] = ...` — the obvious way to write a model sweep — makes the baseline log lie with no reload at all. Main is strictly better. Port `resolve_model` to the baseline, or the two arms' provenance logs are not comparable.

### 9. Latent, not currently reachable — PLAUSIBLE

- `src/utils/llm.py:300` — `model=model if "gpt" in model else "gpt-4o-mini"`. If `OPENROUTER_API_KEY` were ever unset with `OPENAI_API_KEY` set, `LLM_MODEL=vllm/snuh/hari-q3-8b` is **silently rewritten to `gpt-4o-mini`** with no error and no log. This is the same defect class the critic fix removed, still live one function away. Not reachable today (`.env` sets `OPENROUTER_API_KEY`, which wins at line 274).
- `src/utils/llm.py:36` — `_MODEL_COSTS.get(model, _MODEL_COSTS["gpt-4o"])`. Verified: `record('snuh/hari-q3-8b', 1e6, 1e6)` → `cost_usd: 12.5`. A local run reports a fabricated dollar figure at gpt-4o rates. Inert in the current config — `get_cost_tracker().record` is called only from `AzureAIFoundryChatModel._generate` (`llm.py:133`) and no Azure credentials are set.
- `artemis-eval-baseline/src/agents/agent2/critic.py:34` — annotation still `-> str` while the function returns `None`.

---

## What I could not break

- `None` → local routing: solid, constructed and read off the object.
- The `if model_name is not None` branch: correct; `_default_chain` matches `settings.LLM_MODEL` under any normal process lifecycle.
- Whitespace and empty-string tiers: handled by `.strip()`.
- Main's log line: honest in the default branch, the `auto` branch, and the literal branch.
- `test_model_selection_is_uniform.py`: 7 passed. But note it asserts only on **names** — it never constructs an LLM object, so it cannot see findings 5 or 9. And it `monkeypatch.delenv`s `AGENT2_CRITIC_MODEL_TIER`, so it validates a configuration the benchmark drivers never run in: `AGENT2_CRITIC_MODEL_TIER=gpt-4o LLM_MODEL=vllm/... pytest tests/test_model_selection_is_uniform.py -q` → **7 passed**, green, while the pipeline it is guarding routes to OpenAI.

## Files

- `/home/bilab/work/projects/Broadsea/artemis/src/agents/agent2/critic.py` — `:55` tier parse, `:386-392` caller branch + log, `:457` blanket except, `:463-471` singleton
- `/home/bilab/work/projects/Broadsea/artemis-eval-baseline/src/agents/agent2/critic.py` — `:63` tier parse, `:397-400` log
- `/home/bilab/work/projects/Broadsea/artemis/tests/test_interaction_regression.py:50` — finding 1
- `/home/bilab/work/projects/Broadsea/artemis/scripts/quick_concept_benchmark_v2.py:69-101, 217-222` — finding 5
- `/home/bilab/work/projects/Broadsea/artemis-eval-baseline/scripts/quick_concept_benchmark_v2.py` — finding 3
- `/home/bilab/work/projects/Broadsea/artemis-eval-baseline/scripts/model_eval/run_model.py:387` — finding 4
- `/home/bilab/work/projects/Broadsea/artemis/src/utils/llm.py:36, 133, 238-256, 300` — finding 9
- Probes retained at `/tmp/criticprobe/*.py`, network guard at `/tmp/netguard/sitecustomize.py`. No file in either checkout was modified.

---

# Review 3 — the LLM_MODEL claim

## Method

Wire-level recorder installed via `PYTHONPATH=/tmp/llmaudit` (`sitecustomize.py`, so it survives subprocesses and threads), patching `httpx.Client.send` — the layer *below* `get_llm`, so it sees the model string actually sent and the host actually contacted. Requests to non-local hosts were rewritten to the local vLLM: zero spend, and the fact that they were leaving is recorded. Every claim below marked **REPRODUCED** was produced by running code.

**vLLM state as found:** up. `google/gemma-4-31B-it`, pid 2176055, `0.0.0.0:8000`. This host is `100.66.233.6` (GB10), which is exactly `.env`'s `VLLM_BASE_URL`. All local calls below are real completions.

---

## The claim holds — for the case it was tested on

**REPRODUCED.** With `LLM_MODEL=vllm/google/gemma-4-31B-it` and nothing else set, I drove real work through 10 call sites. 11 wire calls, **all** `google/gemma-4-31B-it` @ `100.66.233.6:8000`. Zero egress.

That includes the `ThreadPoolExecutor` in `threshold_classifier.py`: workers `ThreadPoolExecutor-2_0/_1/_2` each resolved identically. Resolving once per batch (`threshold_classifier.py:462`) works. No module builds an LLM at import time — I spied `get_llm` and imported `retriever`, `logic`, `cohort_pipeline`, `tte_service`: zero constructions.

`tests/test_model_selection_is_uniform.py` + `test_perf_m4_critic_model_tiering.py`: 23 passed.

**What that covers:** one process, one process-global model, set before launch. **Everything below is outside it.**

---

## 1. The per-request model reaches 2 of 7 call sites — REPRODUCED

`src/api/tte.py` exposes a model picker (`GET /models`, `request.model` on `/generate`, `/generate-draft`, `/generate-from-nct`). It threads into `get_agent1(model_name=)` and `get_planner(model_name=)` at `tte_service.py:9078,9083,9088` — **and stops there.**

Simulating one API request with the live container's config (`LLM_MODEL=gpt-4o`, `AGENT2_CRITIC_MODEL_TIER=gpt-4o`), user picks `vllm/google/gemma-4-31B-it`:

```
CALL SITE                                  HOST CONTACTED   MODEL SENT              HONOURS REQUEST?
get_agent1(model_name=REQ)                 100.66.233.6     google/gemma-4-31B-it   YES
get_planner(model_name=REQ)                100.66.233.6     google/gemma-4-31B-it   YES
downstream: agent2 critic                  openrouter.ai    gpt-4o                  no
downstream: agent2 reranker                openrouter.ai    gpt-4o                  no
downstream: nlu_router                     openrouter.ai    gpt-4o                  no
downstream: threshold classifier           openrouter.ai    gpt-4o                  no
downstream: tte_service get_llm()          openrouter.ai    gpt-4o                  no
```

This is the same bug in a new coordinate system. `resolve_model` cannot fix it: it reads `settings.LLM_MODEL`, which is process-global, and there is no request-scoped model context.

## 2. `compose/artemis-api.yml:31` bakes in the old mitigation — REPRODUCED, live

`AGENT2_CRITIC_MODEL_TIER: gpt-4o`. Verified present in the running container via `docker exec artemis-api env`. The container **does** carry the fixed code (`"follow"` default, `is not None` branch, `resolve_model` present) — and the compose env turns it off.

Reproduced locally: with `LLM_MODEL=vllm/google/gemma-4-31B-it` and that var set, `select_critic_model()` returns `'gpt-4o'` for **every** domain and builds `model='gpt-4o' base=https://openrouter.ai/api/v1`. With `=auto`, `Condition/Drug/Measurement → 'gpt-4o-mini'` — the original 90% bug, verbatim.

The env var that was the failed mitigation is now the contamination vector, and `ALLOWED_RUNTIME_ENV` in `scripts/quick_concept_benchmark_v2.py:100` explicitly preserves it across `os.environ.clear()`. A stale `export` survives into every benchmark subprocess.

Container also has `VLLM_BASE_URL=http://61.107.200.12:8000/v1` — different from `.env`'s `100.66.233.6`, and **unreachable from inside the container** (HTTP 000). That path at least fails loudly.

## 3. Agent 1's IR cache key is model-blind — REPRODUCED

`parser.py:88` `self.model_name = model_name or "default"` → `parser.py:256-258` uses it as the cache key *and* inside `prompt_hash`.

```
LLM_MODEL='vllm/google/gemma-4-31B-it'  wire: google/gemma-4-31B-it @ 100.66.233.6:8000
  cache file: NCT00391872_default_2470395d0631ee3b.json
LLM_MODEL='gpt-4o'                      wire: gpt-4o @ openrouter.ai
  cache file: NCT00391872_default_2470395d0631ee3b.json   <-- identical
```

`resolve_model`'s own docstring names cache keys as its reason to exist; this call site doesn't call it. All 12 entries in `data/cache/agent1_ir/` are `_default_`, and their `.meta.json` records `enrichment_source`/timestamp/criteria counts — **no model**. A second-arm benchmark run makes zero Agent-1 LLM calls and silently replays arm one. `data/cache/threshold_spans/` is keyed correctly (`vllm_snuh_hari-q3-8b_*.json` + `"model"` in the payload) — that one is clean.

## 4. `resolve_model()` can disagree with the wire — REPRODUCED

`llm.py:301` — `model=model if "gpt" in model else "gpt-4o-mini"`. Any non-`gpt` name reaching the OpenAI branch is silently rewritten:

```
resolve_model()            = 'vllm/google/gemma-4-31B-it'
model actually on the wire = 'gpt-4o-mini'
AGREE? False
```

`resolve_model` answers "what was requested", never "what was served". It is documented as "the model a call site will actually use". On a box with only `OPENAI_API_KEY`, that sentence is false and nothing logs the substitution.

## 5. Cost tracker reports $0.00 for real spend — REPRODUCED

`get_cost_tracker().record()` is called from exactly one place: `AzureAIFoundryChatModel._generate` (`llm.py:133`). The `ChatOpenAI` paths — vLLM, OpenRouter, OpenAI — never record. After one real completion:

```
real vLLM call made, response len: 2
cost tracker: {'llm_calls': 0, 'input_tokens': 0, 'output_tokens': 0, 'cost_usd': 0.0}
```

`llmCost` in TTE reports (`tte_service.py:3307,3341,3392,3452`) is structurally zero under every currently-configured provider. A run that spent money at OpenRouter reports $0 and 0 calls. Same clean-looking-result shape as the 45-second-timeout table.

## 6. The harness's env scrub is inert — REPRODUCED

`bootstrap_runtime_env()` does `os.environ.clear()` then restores only allowlisted keys. Then `src/settings.py` calls `load_dotenv()`, and python-dotenv resolves `.env` **from `settings.py`'s own directory, not cwd**. Cleared `VLLM_BASE_URL`, chdir'd to `/tmp`, imported settings:

```
env VLLM_BASE_URL before import: None
after import: os.environ VLLM_BASE_URL = http://100.66.233.6:8000/v1
              os.environ OPENROUTER_API_KEY = SET
```

The comment at `quick_concept_benchmark_v2.py:219` ("searches upward from cwd; running from a neutral directory avoids reloading...") is wrong about the mechanism. Every `artemis/.env` key comes back. Two consequences: the allowlist provides no isolation, and the effective config of any run depends on an untracked file (`git status` shows `.env` modified) rather than on the recorded command line.

Note the asymmetry: **main's** `ALLOWED_RUNTIME_ENV` still lacks `VLLM_BASE_URL`/`VLLM_API_KEY`; the **baseline worktree's** uncommitted version has them (lines 104-105). The two arms of the benchmark run under different harness code. Today it doesn't matter, but only because of the accident above.

## 7. `settings` snapshots the environment at import — REPRODUCED

```
os.environ["LLM_MODEL"]="model-A"; import src.settings  -> resolve_model() = 'model-A'
os.environ["LLM_MODEL"]="model-B"                       -> resolve_model() = 'model-A'
Settings() re-instantiated                              -> 'model-B'
```

`test_model_selection_is_uniform.py` passes *because* it `importlib.reload`s `src.settings`. In production, `LLM_MODEL` must be set before import — changing it on a running `artemis-api` requires a restart, not an env update.

---

## Provenance: can you prove model X served every call?

**No — the artifacts don't record X at all.** `save_results()` (`quick_concept_benchmark_v2.py:1050`) writes `schema_version, status, timestamp, dataset, sample_size, sample_ids, domains, mappers, progress, results_raw, aggregate, by_domain, per_item`. No model, no provider, no endpoint. Same for `save_progress()`.

And `load_resume_rows()` validates **only `sample_ids`** — `--save-path X` resumed across two `LLM_MODEL` values merges rows from both models into one table with no warning.

To make it provable, three things must be recorded that currently aren't:

1. **The served model, from the provider's response** (`response.model`), not the requested name. Points 4 and 3 are both cases where the request and the response disagree; only the response settles it.
2. **The host actually contacted, per call.** Point 1 is invisible from any per-run field, because the split happens *within* one run.
3. **Cache hit vs. LLM call, with the model that produced the cached entry.** Point 3 means a run can legitimately record "model B" and have made no B calls.

A run-level assertion — "every recorded served-model equals the configured one, count of distinct hosts == 1" — is the check that would have caught the critic literal, the dropped `VLLM_BASE_URL`, and point 1, without anyone remembering to set an env var.

---

## Smaller, by reading only (not executed as failures)

- `critic_cache.py:66` — `make_key = sha256(query|domain)`, no model. In-process TTL cache, so it only bites if one process switches models mid-run.
- `artemis-eval-baseline/src/agents/agent2/critic.py:398` logs `os.environ.get('LLM_MODEL','gpt-4o')` where main uses `resolve_model(model_name)`. Different resolution path in the two arms; agrees today only because `load_dotenv` populates `os.environ`.
- `tests/test_model_selection_is_uniform.py` is titled "One setting must move every LLM call site" but asserts on four `resolve_model(<module constant>)` return values — the three sites that were fixed, plus the classifier. It does not touch `parser`, `decomposer`, `nlu_router`, `reranker`, `clinical_reranker`, `pubmed_fetcher` or `tte_service`, and it never checks what `get_llm` builds. It is a regression test for the fix, not a test of the claim.

**Bottom line:** the fix is correct and does what the commit message says. The claim as stated — "setting `LLM_MODEL` moves the entire pipeline, with no call site left behind" — is true only for a single process, with the model set before import, with caching off, with `AGENT2_CRITIC_MODEL_TIER` unset, and with no per-request model. The deployed container violates two of those five right now.

Artifacts: `/tmp/llmaudit/sitecustomize.py`, `/tmp/llmaudit/calls.jsonl`, `/tmp/probe/{drive,cachekey,traps,fallthrough,api_model}.py`. No file in either checkout was modified.

---

# Adjudication

## 1. Findings — verdict and reproduction

Everything below was executed. Outbound HTTP was intercepted at `httpx.Client.send` via `PYTHONPATH=/tmp/rv/guard` (records model + host, blocks non-allowlisted hosts), so no billed call was made by me. No file in either checkout was modified.

### Review 1

| # | Claim | Verdict |
|---|---|---|
| — | The critic fix itself is correct (`None` → local) | **CONFIRMED** |
| 1 | `test_interaction_regression.py` makes live billed calls | **CONFIRMED** (worse) |
| 2 | Baseline worktree tests red + billed | **CONFIRMED** (broader) |
| 3 | Baseline harness re-pins tier → asymmetric arms | **CONFIRMED** |
| 4 | `run_model.py` force-pins tier for both arms | **CONFIRMED as code, blast radius REFUTED** |
| 5 | Main harness discards exported `VLLM_BASE_URL` | **CONFIRMED** |
| 6 | Tier parse exact-match/case-sensitive | **CONFIRMED** |
| 7 | Stale singleton, log reports the other model | **CONFIRMED** |
| 8 | Checkouts' log lines read different clocks | **CONFIRMED** |
| 9 | Latent: `gpt-4o-mini` rewrite / cost table / `-> str` | **CONFIRMED mechanism, one consequence REFUTED** |

**R1#0 — fix correct.** `probe_tier.py` builds the object and reads the model off it:

```
TIER=None  dom=Condition  select()=None  wire=snuh/hari-q3-8b  base=http://100.66.233.6:8000/v1
```

**R1#1 — CONFIRMED, and the reviewer understated it.**
```
PYTHONPATH=/tmp/rv/guard .venv/bin/python -m pytest -q tests/test_interaction_regression.py
  1 failed, 8 passed in 4.49s
=== RV-GUARD outbound attempts ===
  httpx host=openrouter.ai model=gpt-4o     (x9)
```
Nine POSTs, not three. `test_mixed_kg_non_kg_filtering` passes live and fails blocked — a live OpenAI response decides the assertion. I also verified this is a **regression from `ed2bd8f`**, not pre-existing: `git show 6ed6a8d:.../critic.py` has `if model_name != "gpt-4o"`, so the mock's `"gpt-4o"` selected `_default_chain` (the injected mock) and the test was hermetic.

**R1#2 — CONFIRMED, three files not two.** Per-file, under the guard, in `/home/bilab/work/projects/Broadsea/artemis-eval-baseline`:
```
tests/test_perf_m4_critic_model_tiering.py   7 failed, 3 passed   egress=0
tests/test_map_002_m3_critic_reflection.py   1 failed, 9 passed   egress=15
tests/test_interaction_regression.py         1 failed, 8 passed   egress=9
tests/test_model_selection_is_uniform.py     No such file
```
R1 reported "9 failed, 11 passed"; I get different counts because they ran live and I blocked. The discrepancy *is* the finding — outcomes depend on a network response.

**R1#3 — CONFIRMED.** Same operator command, each checkout's own harness bootstrap exec'd verbatim (`/tmp/rv/probe_bootstrap.py`):

| checkout | `select_critic_model("Condition")` | wire | endpoint |
|---|---|---|---|
| `artemis` | `None` | `snuh/hari-q3-8b` | `http://100.66.233.6:8000/v1` |
| `artemis-eval-baseline` | `"gpt-4o"` | `gpt-4o` | `https://openrouter.ai/api/v1` |

**R1#4 — CONFIRMED as code, REFUTED as consequence.** `run_model.py:391` is unconditional, as claimed. But across **every** `stage_calls.jsonl` on disk (8 rep dirs, 377 calls):
```
   235  src.agents.conceptset.nlu_router:separate
   142  src.agents.conceptset.clinical_reranker:_rerank_with_llm
models x hosts: {('gpt-4o', 'https://openrouter.ai/api/v1'): 377}
```
**Zero critic calls.** Cause: no Neo4j container in `docker ps`, bolt closed on host; `KGExpander._verify_neo4j()` raises `RuntimeError`, `workflow.py:731`'s `try` swallows it, the critic branch is never reached. The pin is currently a no-op — and becomes live the instant Neo4j starts.

**R1#5 — CONFIRMED, end to end.** Operator exports a distinctive URL; the harness eats it and `.env` replaces it:
```
1_shell_exported          VLLM_BASE_URL = http://OPERATOR-OVERRIDE:8000/v1
2_after_clear+allowlist   VLLM_BASE_URL = null
3_after_import_settings   VLLM_BASE_URL = http://100.66.233.6:8000/v1
                          GOOGLE_CLOUD_PROJECT = team3-485101   <- not allowlisted
cwd_after_bootstrap       /tmp
```
The `chdir("/tmp")` at `quick_concept_benchmark_v2.py:217-222` does nothing; `load_dotenv()` resolves from `src/settings.py`'s own directory. Comment is factually wrong.

**R1#6 — CONFIRMED**, full 22-value × 2-domain table, byte-identical in both checkouts. Safe spellings are only `unset`, `""`, whitespace, `follow` (any surrounding whitespace). `Follow`, `FOLLOW`, `AUTO`, `Auto`, `none`, `None`, `null`, `off`, `0`, `false`, `true` all become **literal model names** sent to `openrouter.ai`.

**R1#6b — I generalized this past the tier and it is worse.** The failure does not need a typo'd tier; a typo'd *model* does it. With `LLM_MODEL=vllm/snuh/hari-q3-8b` — the string in the docs, in `test_model_selection_is_uniform.py`, and in `scripts/probe_criterion_classifier.py` — against the only live vLLM server (which serves `google/gemma-4-31B-it`):
```
INFO  [Critic] Model: vllm/snuh/hari-q3-8b (domain=Condition)
INFO  httpx: POST http://100.66.233.6:8000/v1/chat/completions "HTTP/1.1 404 Not Found"
ERROR [Critic] Evaluation failed: Error code: 404 - The model `snuh/hari-q3-8b` does not exist.
RESULT: [111]  seed_only= True
```
KG expansion discarded, one ERROR line, benchmark row complete.

**R1#7 — CONFIRMED.**
```
A settings.LLM_MODEL=vllm/snuh/hari-q3-8b   chain holds ('snuh/hari-q3-8b','http://100.66.233.6:8000/v1')
B settings.LLM_MODEL='gpt-4o' (same object) chain holds ('snuh/hari-q3-8b','http://100.66.233.6:8000/v1')  log says 'gpt-4o'
C fresh ConceptCritic()                     chain holds ('gpt-4o','https://openrouter.ai/api/v1')
```
Their API-unreachability check also holds: `get_agent1`/`get_planner` return a fresh instance when `model_name is not None`.

**R1#8 — CONFIRMED, with an addition.** Under `os.environ["LLM_MODEL"]="gpt-4o"` with no reload: main logs `vllm/snuh/hari-q3-8b` (truthful), baseline logs `gpt-4o` (chain is still local — lies). But under `settings.LLM_MODEL = "gpt-4o"`, **main lies too**. Main is better, not immune. Also: `resolve_model` does not exist in the baseline at all (`ImportError` on `from src.utils.llm import resolve_model`).

**R1#9 — mechanism CONFIRMED, one consequence REFUTED.** See R2#3 and R2#6 below.

---

### Review 2

| # | Claim | Verdict |
|---|---|---|
| 1 | Arms resolve `VLLM_BASE_URL` to different machines; probe skipped | **CONFIRMED** |
| 2 | Criterion cache key omits LLM model; 61 live entries | **CONFIRMED** (TTL 30× longer than stated); one sub-claim **REFUTED** |
| 3 | `get_llm` substitutes `gpt-4o-mini` | **CONFIRMED, inert today** |
| 4 | Container pins critic to gpt-4o | **CONFIRMED** |
| 5 | `git_commit` is dirty-blind | **CONFIRMED** |
| 6 | Cost tracker prices unknown models at gpt-4o rates | **code CONFIRMED, consequence REFUTED** |
| 7 | Main harness drops `VLLM_BASE_URL`, records no model | **CONFIRMED** |
| 8 | Timeout/error becomes a score | **CONFIRMED**, `gpt-5.4` arm is opt-in |
| 9 | Hardcoded models, no provenance | **CONFIRMED** |

**R2#1 — CONFIRMED.** `.env` keys (values printed only for the non-secret one):
```
artemis/.env                 VLLM_BASE_URL = http://100.66.233.6:8000/v1   -> http=200, serves google/gemma-4-31B-it
artemis-eval-baseline/.env   VLLM_BASE_URL = http://61.107.200.12:8000/v1  -> http=000 (dead)
```
`probe = probe_server(base_url, args.model) if base_url else None` with `base_url = args.vllm_base_url or os.environ.get("VLLM_BASE_URL","")`. Both runs on disk:
```
vllm_base_url = ''      port = None      server_probe = None
```

**R2#2 — CONFIRMED, and understated.** Key is blind:
```
gpt-4o                       criterion=45a22adfa4fc2c4e02da0a0f2120  critic=2e216898bf752c682ae0eaec0774
vllm/snuh/hari-q3-8b         criterion=45a22adfa4fc2c4e02da0a0f2120  critic=2e216898bf752c682ae0eaec0774
vllm/google/gemma-4-31B-it   criterion=45a22adfa4fc2c4e02da0a0f2120  critic=2e216898bf752c682ae0eaec0774
```
Live DB (read from a copy — the original is root-owned and WAL-locked):
```
total 61   unexpired 61
expires_at   2026-08-21 23:16 .. 2026-08-28 09:35
last_accessed 2026-07-22 23:57 .. 2026-07-29 09:35
implied ttl hours: 720.0
```
R2 said "TTL is 24h". It is **720 h**, set at `compose/artemis-api.yml:33`. The contamination window is 30 days, not 1.
**Sub-claim REFUTED:** "the disable flag is unreachable from the shell in one harness" — `quick_concept_benchmark_v2.py` has **no reference to `criterion_cache` or `tte_service` at all**. The cache is reached only from `tte_service.py` and `api/tte.py`. The missing allowlist entry is real but creates no exposure in that harness.

**R2#3 — CONFIRMED, inert.** Forced fall-through:
```
B VLLM_BASE_URL dropped
   vllm/snuh/hari-q3-8b  wire=vllm/snuh/hari-q3-8b  base=https://openrouter.ai/api/v1  reasoning_stripped=false
C no OPENROUTER, OPENAI set
   vllm/snuh/hari-q3-8b  wire=gpt-4o-mini           base=None                          reasoning_stripped=false
   Qwen/Qwen3-8B         wire=gpt-4o-mini
```
Cannot fire today (`OPENROUTER_API_KEY` set, `OPENAI_API_KEY` unset). Their second-order point holds: `ReasoningStrippedChatModel` wraps only the vLLM branch — scenario A shows `Qwen/Qwen3-8B` via OpenRouter arriving unwrapped.

**R2#4 — CONFIRMED live.** `docker exec artemis-api env`: `LLM_MODEL=gpt-4o`, `AGENT2_CRITIC_MODEL_TIER=gpt-4o`, `VLLM_BASE_URL=http://61.107.200.12:8000/v1` (the dead one — a third value for the same setting), `CRITERION_CACHE_ENABLED` unset.

**R2#5 — CONFIRMED, with a sharper consequence.** `git rev-parse HEAD` = `bc33ccc`, tree has 9 dirty entries. And the fingerprint moves:
```
prompt_fingerprint at bc33ccc  = f55d2e951f305ec1   <- what both run_meta.json on disk record
prompt_fingerprint worktree-now = d176336a220c016b
```
Every baseline run already collected is at `f55d…`; any future one is at `d176…`. The existing data is not comparable to the next run regardless of anything else.

**R2#6 — code CONFIRMED, consequence REFUTED.** `record("snuh/hari-q3-8b", 1e6, 1e6) -> cost_usd 12.5` reproduces. But `get_cost_tracker().record` is reached **only** from `AzureAIFoundryChatModel._generate` (`llm.py:133`), and no Azure creds are set. Every `result.json` on disk:
```
llmCostTracker: {'llm_calls': 0, ..., 'cost_usd': 0.0}
llmCalls:       {'calls': 137, 'errors': 0, ..., 'models_used': {'gpt-4o': 137}}
```
The file reports **$0.00 against 137 real billed calls**. That is R3#5, and it is the true finding; R2's "fabricated OpenAI pricing" does not happen in this configuration. Their "score_run.py gets this right" is confirmed (`rate = PRICE_PER_TOKEN.get(model); if rate:`).

**R2#7 — CONFIRMED.** `rg VLLM scripts/quick_concept_benchmark_v2.py` in main: nothing. `save_results()`/`save_progress()` in main write no model field; the baseline's uncommitted diff adds `critic_model_tier` only — still no `LLM_MODEL`.

**R2#8 — CONFIRMED, one qualification.** `DEFAULT_LLM_TIMEOUT_S = 45.0`; timeout and `except BaseException` both yield `pred_ids = []`. The `Errors` column *is* printed in the table and per-row `error` is kept — so it is not invisible, only absent from the score. The `"gpt-5.4"` literal at line 1105 is real, but `gpt54_rag` is **not** in the default `--mappers` (`rag,llm,agent2`), so it is opt-in.

**R2#9 — CONFIRMED** by grep; `probe_criterion_classifier.py:39` hardcodes `vllm/snuh/hari-q3-8b`, which now 404s against the live server.

**R2's ruled-out items** — I re-ran the load-bearing one. vLLM refuses a mismatched id:
```
snuh/hari-q3-8b        http=404 "The model `snuh/hari-q3-8b` does not exist."
google/gemma-4-31B-it  http=200
```

---

### Review 3

| # | Claim | Verdict |
|---|---|---|
| — | `LLM_MODEL` moves everything in one clean process | **CONFIRMED** (no import-time LLM construction) |
| 1 | Per-request model reaches 2 of 7 sites | **CONFIRMED** |
| 2 | Compose bakes in the old mitigation | **CONFIRMED**; "container carries the fixed code" **REFUTED** |
| 3 | Agent-1 IR cache key is model-blind | **CONFIRMED**, with a precise nuance |
| 4 | `resolve_model()` can disagree with the wire | **CONFIRMED, inert** |
| 5 | Cost tracker reports $0.00 for real spend | **CONFIRMED** |
| 6 | Harness env scrub is inert | **CONFIRMED** |
| 7 | `settings` snapshots env at import | **CONFIRMED** |
| — | "host actually contacted, per call" is unrecorded | **REFUTED** |

**R3#0 — CONFIRMED.** Spying `get_llm` and importing all nine LLM-using modules: `LLMs constructed at import time: []`.

**R3#1 — CONFIRMED.** `rg "model_name=" src/services/tte_service.py` shows the parameter terminating at `get_agent1(...)`/`get_planner(...)` (lines 9078/9083/9088). Nothing else accepts it.

**R3#2 — CONFIRMED for the file, REFUTED for the process.** See N1 below.

**R3#3 — CONFIRMED**, and the mechanism is exactly:
```
LLM_MODEL=gpt-4o                override=None                     -> cache model_key='default'
LLM_MODEL=vllm/snuh/hari-q3-8b  override=None                     -> cache model_key='default'
LLM_MODEL=gpt-4o                override='vllm/snuh/hari-q3-8b'   -> cache model_key='vllm_snuh_hari-q3-8b'
```
The cache keys on the *explicit override*, and collapses to `"default"` whenever the model comes from `LLM_MODEL` — i.e. in every benchmark run. All 12 files on disk are `_default_`; `.meta.json` records no model. `data/cache/threshold_spans/` is correctly keyed (`vllm_snuh_hari-q3-8b_*.json`).

**R3#4 / R3#5 / R3#6 / R3#7 — CONFIRMED**, reproductions above.

**R3's provenance requirement #2 — REFUTED.** `_describe()` in `run_model.py` records `base_url` on every call, and it is on disk:
```
model_used x base_url:  ('gpt-4o', 'https://openrouter.ai/api/v1') 377
```
An intra-run host split *is* detectable from `stage_calls.jsonl`. It is only absent from `score_run.py`'s summary, which surfaces `models_used` but not hosts. Their requirements #1 (served model from the response) and #3 (cache-hit attribution) stand.

---

## 2. CONFIRMED findings, ranked by silence of failure

1. **N3 — the benchmark exercises 2 of 10 LLM call sites (Neo4j is down).** 377/377 recorded calls are `nlu_router` + `clinical_reranker`. Produces a complete, plausible, comparable results table that is not a measurement of the pipeline. Nothing in any output says so.
2. **F11 — model-blind caches, 61 unexpired gpt-4o entries, 30-day TTL, shared between arms by symlink.** A `[CACHE HIT]` at INFO and a normal artifact. Reaches a clinician through the Atlas UI, not just a table.
3. **F6b — a wrong model name degrades Agent 2 to plain vector search.** `except Exception` at `critic.py:457` → seed concepts. One ERROR line per item, full table, lower numbers. `vllm/snuh/hari-q3-8b` — the name in the docs — triggers it against the only live server *today*.
4. **F3 — asymmetric critic routing between arms.** Same command, two providers on the 90% domains. Only fires if Neo4j comes up; when it does, it is invisible in `quick_concept_benchmark_v2.py` output entirely.
5. **F5/F7-main — the harness silently discards an operator `VLLM_BASE_URL` override and records no model.** No warning; the run is mislabelled by omission.
6. **F1 — `pytest -q` is green because of a live billed call.** Silent in the worst place: the thing you run to check nothing else is silent.
7. **N5 — `test_model_selection_is_uniform.py` is green in exactly the configuration that fails.** Verified: `AGENT2_CRITIC_MODEL_TIER=gpt-4o LLM_MODEL=vllm/... pytest ...` → `7 passed`, while the same env routes Condition to `openrouter.ai`.
8. **F10 — arms resolve to different machines, `probe_server` skipped, provenance blank.** Loud today only because `61.107.200.12` is fully dead.
9. **N1 — the deployed API runs pre-fix code while the file says otherwise.** Currently wire-identical; silent as a *reasoning* hazard.
10. **F13 — `git_commit` asserts a tree that did not run.** Detectable via `prompt_fingerprint`, but `git_commit` is the field a reader reaches for.
11. **F9b/R3#5 — `llmCost` is $0.00 against 137 billed calls.**
12. **F7/F8 — log line can disagree with the chain** (baseline on `os.environ` mutation, both on `settings` mutation).
13. **F14 — timeout/error scored as a wrong answer.** Mitigated by the `Errors` column being in the same table.
14. **F9a — `gpt-4o-mini` rewrite.** Inert; one `.env` edit from being #1.

---

## 3. What all three missed — the seams

**N1. The running `artemis-api` is executing pre-fix code.** All three reasoned about the container from the bind-mounted file. Inside the container:
```
pid=1  started=2026-07-29 00:06:05   (both --multiprocessing-fork workers: elapsed 16845s, same start)
/app/src/agents/agent2/critic.py mtime = 2026-07-29 03:43:52
cmdline: uvicorn src.api.main:app --host 0.0.0.0 --port 8080 --workers 2      # no --reload
```
The workers imported `critic.py` 3h37m before it was edited. R3's "the container **does** carry the fixed code" is true of the file and false of the process. I checked whether it currently matters: under the container's env (`LLM_MODEL=gpt-4o`, `TIER=gpt-4o`) old and new are wire-identical —
```
TIER=gpt-4o dom=Condition OLD(select='gpt-4o' wire=('gpt-4o',openrouter))  NEW(select='gpt-4o' wire=('gpt-4o',openrouter))
TIER=None   dom=Condition OLD(select='gpt-4o-mini' wire=('gpt-4o-mini',openrouter))  NEW(select=None wire=('gpt-4o',openrouter))
```
— so no live contamination, but the divergence is exactly the shape of the original bug: reading the file tells you the wrong thing about what is running.

**N2. The "isolated" baseline worktree shares five mutable stores with the arm under test.** All symlinks into the main checkout:
```
.venv -> artemis/.venv
data  -> artemis/data                      (agent1_ir, kg_cache.json, threshold_spans)
chroma_db -> artemis/chroma_db
tmp/tte/criterion_cache.sqlite -> artemis/tmp/tte/criterion_cache.sqlite
tmp/tte/real_runs -> artemis/tmp/tte/real_runs
```
Isolation is `src/` and `scripts/` only. Combined with F11 (model-blind keys), a cache written by arm 1 is readable by arm 2 and vice versa. `run_model.py` escapes this by accident twice (`TTE_STORE_PATH` per-rep redirects `_default_db_path()`, plus `CRITERION_CACHE_ENABLED=false`); nothing else does, and neither protection is documented as load-bearing.

**N3. Neo4j is not running, so the Agent-2 KG/critic branch is inert.** No neo4j container in `docker ps`; `localhost:7687` refused; `NEO4J_URI` absent from both `.env` files. `KGExpander.__init__` calls `_verify_neo4j()`, which raises `RuntimeError`, which `workflow.py:731`'s blanket `try` swallows. Every recorded run confirms it: 0 of 377 calls came from the critic. **This dominates every routing finding for validity.** The three reviewers argued at length about which model the critic uses in a configuration where the critic does not run.

**N4. `tests/test_nlu_router.py` also egresses** — 6 billed POSTs to `openrouter.ai`. It is intentional (`@pytest.mark.integration`), but `pyproject.toml` has no `addopts = -m "not integration"`, so a bare `pytest tests/` bills money. Pre-existing, not caused by the change — relevant if "run the suite" is a pre-benchmark step.

**N5. The guard test validates a configuration the drivers never run in.** R1 buried this under "what I could not break"; it deserves finding status. `_reload_with(... tier=None)` does `monkeypatch.delenv("AGENT2_CRITIC_MODEL_TIER")`, and both drivers set that variable. Reproduced above: 7 passed, pipeline routes to OpenAI.

**N6. Everything needed to detect all of the above already lands in `stage_calls.jsonl`** — `stage`, `model_used`, `base_url`, `error`, per call. `score_run.py` surfaces `models_used` but drops `base_url`. The run-level assertion R3 asked for ("distinct hosts == 1, models_used == {expected}") needs **no code change** — it is a two-line read over a file that is already written.

---

## 4. What to change before re-running, and what can wait

The benchmark has been invalidated twice today by good-faith changes. My recommendation is **zero lines changed in `src/` before the re-run.**

### Before the run — operational, not code

1. **Decide Neo4j and record the decision.** Down → say so in writing; the run measures `nlu_router` + `clinical_reranker` and nothing else, and F3/F4/F12 are all no-ops. Up → the critic fires, and then F3 and F4 become live and must be settled first. Do not discover this from the results.
2. **Pass `--vllm-base-url` explicitly and use a model the server actually serves.** `--vllm-base-url http://100.66.233.6:8000/v1 --model vllm/google/gemma-4-31B-it`. This is the single highest-leverage step: it makes `probe_server` run (closing F10), and it avoids F6b, because `vllm/snuh/hari-q3-8b` 404s on that server and the critic swallows the 404.
3. **After the run, assert on `stage_calls.jsonl` before reading any score**: `len({c["base_url"]}) == 1`, `models_used == {expected: N}`, `errors/calls` small, and the stage list is what you expected. Two lines of Python against a file that already exists. This catches F3, F4, F10, F12 and N3 after the fact without touching the pipeline.

### Before the run — code, only if you accept a small diff

- **`tests/test_interaction_regression.py:50` → `return_value=None`** (both checkouts). One word. Cannot affect a benchmark run; stops nine billed calls and a false-green suite. This is the only code change I would make today.

Everything else in `run_model.py` I would leave alone. Removing `env["AGENT2_CRITIC_MODEL_TIER"] = "gpt-4o"` is defensible on principle but is churn on an instrument that has already moved twice, and it changes nothing while Neo4j is down.

### After the run — notes for later

- F5: add `VLLM_BASE_URL`/`VLLM_API_KEY` to main's `ALLOWED_RUNTIME_ENV`, and fix the wrong comment at `quick_concept_benchmark_v2.py:217-222`.
- F15: record `LLM_MODEL`, `VLLM_BASE_URL` and `AGENT2_CRITIC_MODEL_TIER` in `save_results()`; make `load_resume_rows` refuse a resume when they differ.
- F11: put the resolved model in the criterion-cache key and in `parser.py`'s `model_key` (`self.model_name = model_name or resolve_model()`), and expire or move the 61 gpt-4o entries.
- F6: accept `follow`/`auto` case-insensitively and reject unrecognised tier values loudly instead of treating them as model names.
- F6b/critic.py:457: narrow the blanket `except Exception`, or at minimum mark the returned concept set as degraded so a caller can see it.
- F13: append `-dirty` to `git_commit` when the tree is not clean.
- F9b: either call `record()` from the `ChatOpenAI` paths or delete `llmCost` — a field that is structurally zero is worse than no field.
- F9a: `llm.py:300` — raise instead of rewriting a non-`gpt` name to `gpt-4o-mini`.
- F8: port `resolve_model` into the baseline, or accept that the two arms' provenance logs are not comparable.
- N4: add `addopts = -m "not integration"` to `[tool.pytest.ini_options]`.
- N5: add one guard-suite case with `AGENT2_CRITIC_MODEL_TIER=gpt-4o` set, asserting that the *built object's* base_url is local — the current suite only compares names and never constructs an LLM.

Probes retained at `/tmp/rv/*.py`; guard at `/tmp/rv/guard/sitecustomize.py`; call log at `/tmp/rv/calls.jsonl`.
