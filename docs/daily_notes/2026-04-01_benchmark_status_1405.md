# 2026-04-01 Benchmark Status Handoff — 14:05 KST

## Summary

Multi-model concept mapping benchmark is in progress across 3 parallel tracks.
One LLM model (gpt-5-chat) has completed the full 7,945-item run.
Gold cohorts: LEADER and PLATO complete, ARISTOTLE still running.

---

## Current Status Snapshot (14:05 KST)

### Agent2 — 4 Shards (container: artemis-api)

| Shard | Progress | Total | % | Log Path |
|-------|----------|-------|---|----------|
| shard0 | 110 | 1987 | 5.5% | `/tmp/bench_agent2_shard0.log` |
| shard1 | 120 | 1987 | 6.0% | `/tmp/bench_agent2_shard1.log` |
| shard2 | 120 | 1987 | 6.0% | `/tmp/bench_agent2_shard2.log` |
| shard3 | 120 | 1984 | 6.0% | `/tmp/bench_agent2_shard3.log` |

- **Started**: 12:12 KST (2026-04-01 03:12 UTC)
- **Speed**: ~1 item/min per shard
- **ETA**: ~2026-04-02 20:00 KST (~30 hours from now)
- **Critic errors**: 0 (fixed by adding `AGENT2_CRITIC_MODEL_TIER` to `ALLOWED_RUNTIME_ENV`)
- **Result save path**: `/tmp/bench_agent2_shard{N}.json` (written on completion of each shard)
- **Note**: MAPS_TO relationship warnings from Neo4j are non-fatal (KG relation not populated)

### LLM Direct — 6 Models (host processes)

| Model | Progress | Total | % | Status | Save Path |
|-------|----------|-------|---|--------|-----------|
| gpt-5-chat | 7945 | 7945 | **100%** | **DONE** | `artemis/data/benchmark_results/bench_llm_gpt_5_chat_full_20260401_103722.json` |
| gpt-4.1 | 7150 | 7945 | 90% | Running | `bench_llm_gpt_4_1_full_20260401_103722.json` |
| gpt-5.1 | 5130 | 7945 | 65% | Running | `bench_llm_gpt_5_1_full_20260401_103722.json` |
| gpt-5.2 | 5130 | 7945 | 65% | Running | `bench_llm_gpt_5_2_full_20260401_103722.json` |
| gpt-4o | 5130 | 7945 | 65% | Running | `bench_llm_gpt_4o_full_20260401_103722.json` |
| gpt-5.4 | 3220 | 7945 | 41% | Running | `bench_llm_gpt_5_4_full_20260401_103722.json` |

- Logs: `/private/tmp/bench_llm_{model}_full.log`
- ETA: gpt-4.1 ~14:30 KST, gpt-5.1/5.2/4o ~16:00 KST, gpt-5.4 ~19:00 KST

### RAG — Full Run (container: artemis-api)

| Progress | Total | % | Log Path | Save Path |
|----------|-------|---|----------|-----------|
| 80 | 7945 | 1% | `/tmp/bench_rag_rerun.log` | `/tmp/bench_rag_full_rerun.json` |

- **Started**: Shortly before 14:05 KST
- **Speed**: ~1 item/min
- **ETA**: ~2026-04-02 02:00 KST (~12 hours from now)
- **Note**: There is already a completed RAG result in `bench_rag_agent2_20260401_093640.json` (n=100), but the full 7945-item run is needed.

### Gold Cohorts (WebAPI)

| Study | Cohort ID | Data Source | Status | Persons |
|-------|-----------|-------------|--------|---------|
| LEADER | 1136 | LEADER_BENCHMARK | **COMPLETE** | 1,222 |
| PLATO | 1137 | PLATO_BENCHMARK | **COMPLETE** | 436 |
| ARISTOTLE | 1138 | ARISTOTLE_BENCHMARK | RUNNING | — |

- ARISTOTLE statement_timeout set to 60 minutes (increased from 30min after previous failure).

---

## Completed Results

### gpt-5-chat Full Run (7,945 items) — DONE

| Metric | Value |
|--------|-------|
| Recall | 0.131 |
| F1 | 0.046 |
| Hit@1 | 0.240 |
| Latency | 1,579ms |

**By domain:**

| Domain | Recall | F1 |
|--------|--------|----|
| Condition | 0.148 | 0.055 |
| Drug | 0.114 | 0.025 |
| Procedure | 0.004 | 0.002 |
| Measurement | 0.241 | 0.112 |

### 100-Sample Results (reference)

| Model | Recall | F1 | Hit@1 | Latency |
|-------|--------|-----|-------|---------|
| **Agent2** | **0.341** | **0.287** | 0.270 | 24,822ms |
| gpt-5.4 | 0.167 | 0.106 | 0.270 | 2,456ms |
| gpt-5.2 | 0.162 | 0.095 | 0.260 | 2,257ms |
| gpt-4.1 | 0.149 | 0.035 | 0.240 | 3,265ms |
| gpt-5-chat | 0.136 | 0.059 | 0.260 | 1,527ms |
| gpt-5.1 | 0.134 | 0.037 | 0.260 | 2,239ms |
| RAG (MedCPT) | 0.292 | 0.076 | 0.148 | ~898ms |
| gpt-4o | 0.064 | 0.046 | 0.300 | 1,154ms |

> Source: `bench_agent2_20260401_094702.json`, `bench_gpt54.json`, etc.

---

## What To Do When Each Completes

### When gpt-4.1 finishes (~14:30 KST)

```bash
python3 -c "
import json
with open('artemis/data/benchmark_results/bench_llm_gpt_4_1_full_20260401_103722.json') as f:
    d = json.load(f)
print('n=', d['sample_size'])
for m, v in d['aggregate'].items():
    print(m, 'recall=%.3f f1=%.3f hit@1=%.3f' % (v['recall'], v['f1'], v['hit_at_1']))
"
```

### When gpt-5.1, gpt-5.2, gpt-4o finish (~16:00 KST)

Run the same snippet above for each model. Update the results table in this document.

### When gpt-5.4 finishes (~19:00 KST)

Same as above. At this point all 6 LLM models have full results.

### When RAG full run finishes (~02:00 KST Apr 2)

```bash
docker exec artemis-api python3 -c "
import json
with open('/tmp/bench_rag_full_rerun.json') as f:
    d = json.load(f)
print('n=', d['sample_size'])
for m, v in d['aggregate'].items():
    print(m, 'recall=%.3f f1=%.3f hit@1=%.3f' % (v['recall'], v['f1'], v['hit_at_1']))
for dom, dv in d['by_domain'].items():
    for m, v in dv.items():
        print(dom, m, 'recall=%.3f' % v['recall'])
"
```

### When ARISTOTLE cohort finishes

```bash
curl -s "http://127.0.0.1/WebAPI/cohortdefinition/1138/info" | \
  python3 -c "import sys,json,re; raw=re.sub(r'[\x00-\x1f]',' ',sys.stdin.read()); d=json.loads(raw); [print(g['status'],g.get('personCount')) for g in d]"
```

Then run the Gold vs AI HR comparison script:
```bash
cd /Users/kyh/Workspace/Broadsea
python3 artemis/scripts/run_gold_vs_ai_comparison.py
```

### When ALL Agent2 shards finish (~Apr 2, 20:00 KST)

#### Step 1 — Merge 4 shard JSON files

```python
import json, glob
from pathlib import Path
from collections import defaultdict

shard_files = [f"/tmp/bench_agent2_shard{i}.json" for i in range(4)]
# Copy from container first:
# docker cp artemis-api:/tmp/bench_agent2_shard0.json .
# docker cp artemis-api:/tmp/bench_agent2_shard1.json .
# docker cp artemis-api:/tmp/bench_agent2_shard2.json .
# docker cp artemis-api:/tmp/bench_agent2_shard3.json .

shards = []
for f in shard_files:
    with open(f) as fp:
        shards.append(json.load(fp))

# Merge per_item results
all_items = []
for s in shards:
    all_items.extend(s["per_item"])

# Re-compute aggregate metrics
from collections import defaultdict
import numpy as np

metric_keys = ["precision", "recall", "f1", "hit_at_1", "hit_at_5", "hit_at_10", "latency_ms"]
agg = defaultdict(lambda: defaultdict(list))
for item in all_items:
    for mapper, mv in item.items():
        if isinstance(mv, dict) and "recall" in mv:
            for k in metric_keys:
                if k in mv:
                    agg[mapper][k].append(mv[k])

aggregate = {}
for mapper, metrics in agg.items():
    aggregate[mapper] = {k: sum(v)/len(v) for k, v in metrics.items()}

print("=== AGENT2 FULL 7945-ITEM RESULTS ===")
for mapper, v in aggregate.items():
    print(f"{mapper}: recall={v['recall']:.3f}, f1={v['f1']:.3f}, hit@1={v['hit_at_1']:.3f}")
```

#### Step 2 — Copy shards from container to host

```bash
for i in 0 1 2 3; do
  docker cp artemis-api:/tmp/bench_agent2_shard${i}.json \
    /Users/kyh/Workspace/Broadsea/artemis/data/benchmark_results/bench_agent2_shard${i}_20260401.json
done
```

#### Step 3 — Write final comparison document

Once all results are in, create `artemis/docs/daily_notes/2026-04-01_benchmark_final_results.md` with:
- Full comparison table (RAG, 6 LLM models, Agent2) at 7,945 items
- Domain breakdown (Condition/Drug/Procedure/Measurement)
- Latency comparison
- Key findings

---

## Monitoring Commands

```bash
# Agent2 shards (all 4 at once)
for s in 0 1 2 3; do
  echo -n "shard$s: "
  docker exec artemis-api grep -oE "Agent2 [0-9]+/[0-9]+" /tmp/bench_agent2_shard${s}.log 2>/dev/null | tail -1
done

# LLM progress
for model in gpt_4o gpt_4_1 gpt_5_chat gpt_5_1 gpt_5_2 gpt_5_4; do
  echo -n "$model: "
  grep -oE "LLM [0-9]+/[0-9]+" /private/tmp/bench_llm_${model}_full.log 2>/dev/null | tail -1
done

# RAG progress
docker exec artemis-api grep -oE "RAG [0-9]+/[0-9]+" /tmp/bench_rag_rerun.log 2>/dev/null | tail -1

# ARISTOTLE cohort
curl -s "http://127.0.0.1/WebAPI/cohortdefinition/1138/info" | \
  python3 -c "import sys,json,re; raw=re.sub(r'[\x00-\x1f]',' ',sys.stdin.read()); d=json.loads(raw); [print(g['status'],g.get('personCount')) for g in d]"

# Check completed result files
ls -la /Users/kyh/Workspace/Broadsea/artemis/data/benchmark_results/bench_llm_*.json
```

---

## File Inventory

| File | Description | Status |
|------|-------------|--------|
| `artemis/data/benchmark_results/bench_llm_gpt_5_chat_full_20260401_103722.json` | gpt-5-chat 7945-item result | **DONE** |
| `artemis/data/benchmark_results/bench_llm_gpt_4_1_full_20260401_103722.json` | gpt-4.1 7945-item result | Pending ~14:30 |
| `artemis/data/benchmark_results/bench_llm_gpt_5_1_full_20260401_103722.json` | gpt-5.1 7945-item result | Pending ~16:00 |
| `artemis/data/benchmark_results/bench_llm_gpt_5_2_full_20260401_103722.json` | gpt-5.2 7945-item result | Pending ~16:00 |
| `artemis/data/benchmark_results/bench_llm_gpt_4o_full_20260401_103722.json` | gpt-4o 7945-item result | Pending ~16:00 |
| `artemis/data/benchmark_results/bench_llm_gpt_5_4_full_20260401_103722.json` | gpt-5.4 7945-item result | Pending ~19:00 |
| `/tmp/bench_rag_full_rerun.json` (container) | RAG 7945-item result | Pending ~Apr 2 02:00 |
| `/tmp/bench_agent2_shard{0-3}.json` (container) | Agent2 4x1987-item results | Pending ~Apr 2 20:00 |
| `artemis/data/benchmark_results/bench_agent2_20260401_094702.json` | Agent2 100-sample result (reference) | DONE |

---

## Infrastructure Status

| Service | Status | Notes |
|---------|--------|-------|
| artemis-api | Up | Running RAG + Agent2 shards |
| ohdsi-webapi | Up | ARISTOTLE cohort running |
| broadsea-atlasdb | Up | statement_timeout = 60min |
| artemis-neo4j-v2 | Up (healthy) | MAPS_TO relation warnings are non-fatal |
| traefik | Up | — |

---

## Key Notes

1. **MAPS_TO Neo4j warnings** are non-fatal. The KG relationship is simply not populated. Agent2 falls back to seed concepts when no KG expansion is available.

2. **Shard result JSONs** are only written at the END of each shard run. There is no intermediate save. If the container restarts, the shard must be re-run.

3. **gpt-4.1 and gpt-5-chat** started at the same time (10:37 KST) but gpt-5-chat completed first, suggesting gpt-5-chat has faster token generation.

4. **The 100-sample results** in `bench_agent2_20260401_094702.json` show Agent2 recall=0.341, significantly ahead of all LLM direct models. The full 7945-item run is expected to confirm this.

5. **RAG full run** is essentially starting from scratch (80/7945 = 1%). The earlier `bench_rag_agent2_20260401_093640.json` had a bug (RAG recall=0.0 for all domains due to vocab resolver failure). The current rerun should produce valid results.

---

## Expected Final Comparison Table (template)

| Model | Recall | F1 | Hit@1 | Latency | Status |
|-------|--------|-----|-------|---------|--------|
| Agent2 | TBD | TBD | TBD | ~25s | Pending Apr 2 |
| RAG (MedCPT) | TBD | TBD | TBD | ~900ms | Pending Apr 2 |
| gpt-5-chat | **0.131** | **0.046** | **0.240** | 1,579ms | DONE |
| gpt-4.1 | TBD | TBD | TBD | ~3s | ~14:30 KST |
| gpt-5.1 | TBD | TBD | TBD | ~2s | ~16:00 KST |
| gpt-5.2 | TBD | TBD | TBD | ~2s | ~16:00 KST |
| gpt-4o | TBD | TBD | TBD | ~1s | ~16:00 KST |
| gpt-5.4 | TBD | TBD | TBD | ~2.5s | ~19:00 KST |

> Note: 100-sample preview showed Agent2 recall=0.341 >> all LLM models (best: gpt-5.4=0.167).
> Full-run results may differ due to harder long-tail items.
