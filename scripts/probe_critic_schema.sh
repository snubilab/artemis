#!/usr/bin/env bash
# Does a real JSON schema cut the critic's cost without changing what it selects?
#
# The critic dominates every run: 55 of 121 requests, and on hari-q3-8b one call
# emitted 14,934 output tokens over 1,480s. The code downstream keeps only the entries
# with relevant=true and never reads the reflection fields at all, so most of that
# output is discarded after one logger.debug line.
#
# An earlier attempt appended "omit non-relevant concepts, drop these fields" to
# the system prompt. It was 3x SLOWER and produced zero parseable entries: the
# prompt already carries two full-format few-shot examples, and json_object mode
# permits any JSON, so the model went off-format. That attempt asked. A json_schema
# response_format constrains the decoder instead -- fields absent from the schema
# cannot be emitted.
#
# Measured on the live server before writing this (Qwen2.5-7B-Instruct), asking
# the model to emit a <think> block:
#   json_object                        -> narration relocated into a "think" KEY, 50 tok
#   json_schema additionalProperties:0 -> narration gone entirely,               23 tok
# json_object enforces "is a JSON object" and nothing more; extra keys are legal,
# so a reasoning model narrates *inside* the object. The schema closes that door.
#
# Three variants, ONE prompt -- the real 9.2 KB critic system prompt imported from
# src, few-shot examples and self-reflection section and format_instructions
# included, byte for byte. Nothing is appended or removed. If the schema variants
# hold format anyway, the schema beat the few-shot examples, which is the claim.
#   current  json_object, prompt unchanged            (baseline)
#   noreason json_schema without the reasoning field
#   idsonly  json_schema of {"selected_ids": [int]}
#
# The number that decides adoption is not the speedup, it is whether the selected
# id set changes.
#
# RESULT (2026-07-30, Qwen2.5-7B-Instruct, 130 candidates over 3 queries, queue
# contending for the GPU so read tokens and ignore seconds) -- DO NOT ADOPT:
#
#   variant        tokens   vs current   parsed   pooled jaccard
#   current          1090        1.0x      3/3        1.00
#   current_rerun    1090        1.0x      3/3        1.00   <- noise floor is ZERO
#   capped           2654    2.4x MORE     3/3        0.56
#   noreason         1476    1.4x MORE     3/3        0.41
#   idsonly           716        1.5x      3/3        0.17
#
# The mechanism works -- 3/3 parsed on every schema variant against the two
# full-format few-shot examples, where the prompt-append attempt got zero. The
# schema does beat the few-shot examples. It just does not pay.
#
# Under json_object this model is already terse: 3-6 entries for 40-50
# candidates, ~10 tok/candidate, not one object per candidate. There is nothing
# to squeeze. Every schema then made it enumerate all 50 instead, so `capped` and
# `noreason` cost MORE. `idsonly` is the only saving and it is worthless: on query
# 1 it returned all 50 candidates including all 18 deliberate distractors
# (myocardial infarction, fracture of femur, cataract) for a chronic-kidney-disease
# query. Per-item `reasoning` is load-bearing chain-of-thought; strip it and the
# model stops discriminating. current_rerun is byte-identical to current, so the
# 0.17 is signal, not sampling noise.
#
# And the premise was wrong. hari's 14,934 tokens is not verbosity:
#   probe prompt, chat-templated  =  1,450 tokens  (server /tokenize)
#   --max-model-len               = 16,384
#   16,384 - 1,450                = 14,934        <- exactly hari's output
# hari never emitted a stop token. It decoded to the context ceiling and was
# truncated, so its response cannot have parsed, so every hari critic call landed
# in critic.py's `except Exception -> return seed_concept_ids`. hari was not slow
# and verbose; hari's Agent 2 was off, silently, for the whole run. No output
# schema fixes non-termination -- an unbounded array can repeat forever.
#
#   nohup artemis/scripts/probe_critic_schema.sh > /tmp/critic_schema_probe.log 2>&1 &
#
set -uo pipefail

ART=/home/bilab/work/projects/Broadsea/artemis
PY="$ART/.venv/bin/python"
OUT=/tmp/critic_schema_probe.json

log() { echo "[$(TZ=Asia/Seoul date '+%H:%M:%S KST')] $*"; }

log "probing against whatever model is currently served on :8000"
curl -s --max-time 15 http://127.0.0.1:8000/v1/models | "$PY" -c \
  "import json,sys; print('  model:', [m['id'] for m in json.load(sys.stdin)['data']])" 2>/dev/null

# The benchmark queue is on the same GPU. Wall clock here is contended; token
# counts are not. Read the tokens, treat the seconds as an upper bound.
log "note: queue running concurrently — see 'Running: N reqs' in /tmp/vllm_*.log"

cd "$ART" || exit 1
# ConceptCritic.__init__ builds the LLM, so VLLM_BASE_URL has to be set even
# though this script never uses the chain -- it only borrows the prompt.
VLLM_BASE_URL="${VLLM_BASE_URL:-http://127.0.0.1:8000/v1}" \
OPENAI_API_KEY="${OPENAI_API_KEY:-EMPTY}" \
"$PY" - "$OUT" <<'PYEOF'
import json, os, sys, time, urllib.request

OUT = sys.argv[1]
BASE = "http://127.0.0.1:8000"
URL = f"{BASE}/v1/chat/completions"

served = json.load(urllib.request.urlopen(f"{BASE}/v1/models", timeout=30))
MODEL = served["data"][0]["id"]
os.environ.setdefault("LLM_MODEL", f"vllm/{MODEL}")

# The real prompt, not a paraphrase of it. The earlier prompt-append attempt
# failed *because* of what is in here (two full-format few-shot examples plus
# JsonOutputParser's format_instructions naming every field); a probe that
# reconstructs a shorter prompt would test a system that does not exist.
from src.agents.agent2.critic import ConceptCritic  # noqa: E402

critic = ConceptCritic()
FORMAT_INSTRUCTIONS = critic.parser.get_format_instructions()


def real_messages(query: str, candidates_text: str) -> list[dict]:
    msgs = critic.prompt.format_messages(
        query=query,
        candidates_text=candidates_text,
        format_instructions=FORMAT_INSTRUCTIONS,
    )
    out = [{"role": "system" if i == 0 else "user", "content": m.content}
           for i, m in enumerate(msgs)]
    # ReasoningStrippedChatModel appends this to the last human turn on every
    # real call. Both models ignore it, but leaving it out changes the prompt.
    out[-1]["content"] += "\n/no_think"
    return out


# ── candidate sets ───────────────────────────────────────────────────────────
# Three queries, ~50 candidates each, deliberately MIXED: clear matches, ancestor
# concepts, plausible siblings, and concepts a careful critic should reject. A set
# where every candidate is obviously relevant makes the Jaccard comparison
# vacuous -- every variant selects everything and agreement is 1.00 by
# construction. Ids are synthetic; the critic only echoes them back.
def build(query: str, relevant: list[str], borderline: list[str], reject: list[str],
          domain: str) -> tuple[str, str]:
    rows, cid = [], 4000000
    for group, vocab in ((relevant, "SNOMED"), (borderline, "SNOMED"), (reject, "SNOMED")):
        for name in group:
            rel = "seed" if cid == 4000000 else ("child" if cid % 3 else "2-hop")
            rows.append(f"- ID: {cid} | Name: {name} | Domain: {domain} "
                        f"| Vocab: {vocab} | Relationship: {rel}")
            cid += 1
    return query, "\n".join(rows)


CASES = [
    build(
        "Chronic kidney disease",
        ["Chronic kidney disease", "Chronic renal impairment",
         "Chronic kidney disease stage 3", "Chronic kidney disease stage 4",
         "Chronic kidney disease stage 5", "End stage renal disease",
         "Renal failure syndrome", "Chronic renal failure",
         "Hypertensive renal disease with renal failure",
         "Diabetic nephropathy", "Glomerulonephritis",
         "Nephrotic syndrome", "Renal osteodystrophy",
         "Anemia of chronic renal failure", "Chronic kidney disease stage 2"],
        ["Acute renal failure syndrome", "Renal cyst", "Hydronephrosis",
         "Proteinuria", "Microalbuminuria", "Reduced glomerular filtration rate",
         "Renal transplant recipient", "Dependence on renal dialysis",
         "Renal artery stenosis", "Polycystic kidney disease",
         "Renal impairment due to contrast", "Kidney stone",
         "Pyelonephritis", "Renal tubular acidosis", "Nephrocalcinosis",
         "Solitary kidney", "Renal papillary necrosis"],
        ["Myocardial infarction", "Type 2 diabetes mellitus", "Essential hypertension",
         "Atrial fibrillation", "Chronic obstructive lung disease",
         "Malignant tumor of breast", "Fracture of femur", "Asthma",
         "Cerebral infarction", "Osteoarthritis of knee", "Cataract",
         "Iron deficiency anemia", "Gastroesophageal reflux disease",
         "Hypothyroidism", "Benign prostatic hyperplasia",
         "Seasonal allergic rhinitis", "Migraine", "Depressive disorder"],
        "Condition",
    ),
    build(
        "Estimated glomerular filtration rate < 30 mL/min/1.73m2",
        ["Glomerular filtration rate", "Estimated glomerular filtration rate",
         "GFR/1.73 sq M.predicted", "eGFR by Creatinine-based formula (MDRD)",
         "eGFR by Creatinine-based formula (CKD-EPI)",
         "Glomerular filtration rate/1.73 sq M.predicted in Serum or Plasma"],
        ["Creatinine [Mass/volume] in Serum or Plasma", "Creatinine renal clearance",
         "Creatinine [Moles/volume] in Serum or Plasma", "Cystatin C in Serum",
         "eGFR by Cystatin C-based formula", "Urea nitrogen in Serum or Plasma",
         "Albumin/Creatinine ratio in Urine", "Creatinine clearance measurement",
         "24 hour creatinine clearance", "Protein/Creatinine ratio in Urine",
         "Urine albumin excretion rate", "Serum creatinine raised",
         "eGFR by Creatinine-based formula (Schwartz)",
         "GFR/1.73 sq M.predicted among blacks"],
        ["Hemoglobin A1c/Hemoglobin.total in Blood", "Body mass index",
         "Systolic blood pressure", "Diastolic blood pressure",
         "Alanine aminotransferase in Serum", "Aspartate aminotransferase in Serum",
         "Platelet count", "Hemoglobin in Blood", "Leukocytes in Blood",
         "Cholesterol in LDL", "Triglyceride in Serum", "Sodium in Serum",
         "Potassium in Serum", "Bilirubin.total in Serum",
         "Thyrotropin in Serum", "C reactive protein in Serum",
         "Prothrombin time", "Glucose in Serum", "Heart rate",
         "Oxygen saturation in Arterial blood"],
        "Measurement",
    ),
    build(
        "Adjustable gastric banding",
        ["Laparoscopic adjustable gastric banding", "Gastric banding",
         "Partitioning of stomach using band",
         "Laparoscopic placement of adjustable gastric band",
         "Adjustment of gastric band"],
        ["Partitioning of stomach using staples", "Gastric bypass",
         "Roux-en-Y gastric bypass", "Sleeve gastrectomy",
         "Vertical banded gastroplasty", "Biliopancreatic diversion",
         "Bariatric surgery", "Revision of gastric band",
         "Removal of gastric band", "Gastric balloon insertion",
         "Laparoscopic sleeve gastrectomy", "Duodenal switch procedure",
         "Endoscopic sleeve gastroplasty", "Gastroplasty",
         "Reduction of stomach volume"],
        ["Appendectomy", "Cholecystectomy", "Inguinal hernia repair",
         "Coronary artery bypass graft", "Total knee replacement",
         "Cataract extraction", "Colonoscopy", "Transplantation of kidney",
         "Hysterectomy", "Tonsillectomy", "Thyroidectomy",
         "Percutaneous coronary intervention", "Hemodialysis",
         "Cesarean section", "Splenectomy", "Mastectomy",
         "Prostatectomy", "Craniotomy", "Skin graft", "Bronchoscopy"],
        "Procedure",
    ),
]

# ── response formats ─────────────────────────────────────────────────────────
# additionalProperties:false is the whole mechanism. Without it the model can add
# an unrequested narration key and the schema saves nothing -- verified: under
# json_object an explicit <think> request came back as a "think" key.
SCHEMA_NOREASON = {
    "type": "object",
    "properties": {
        "selected_concepts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "concept_id": {"type": "integer"},
                    "relevant": {"type": "boolean"},
                },
                "required": ["concept_id", "relevant"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["selected_concepts"],
    "additionalProperties": False,
}

SCHEMA_IDSONLY = {
    "type": "object",
    "properties": {"selected_ids": {"type": "array", "items": {"type": "integer"}}},
    "required": ["selected_ids"],
    "additionalProperties": False,
}

# The variant that addresses hari specifically. hari's cost is ~299 tokens per
# ENTRY against Qwen3.5-4B's ~60 on a prompt that pinned both to one entry per
# candidate -- per-entry bloat, not entry count. Keeping `reasoning` keeps
# whatever chain-of-thought conditions the verdict; maxLength caps the bloat.
# additionalProperties:false separately blocks the narration key that a Qwen3
# thinking model would otherwise open under json_object.
SCHEMA_CAPPED = {
    "type": "object",
    "properties": {
        "selected_concepts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "concept_id": {"type": "integer"},
                    "relevant": {"type": "boolean"},
                    "reasoning": {"type": "string", "maxLength": 120},
                },
                "required": ["concept_id", "relevant", "reasoning"],
                "additionalProperties": False,
            },
        },
        "overall_reasoning": {"type": "string", "maxLength": 200},
    },
    "required": ["selected_concepts", "overall_reasoning"],
    "additionalProperties": False,
}

VARIANTS = [
    ("current", {"type": "json_object"}),
    # Same request as `current`, byte for byte. Any disagreement between these two
    # is the noise floor: temperature 0 is not bitwise deterministic under vLLM
    # continuous batching, so without this control a schema variant's Jaccard has
    # nothing to be compared against.
    ("current_rerun", {"type": "json_object"}),
    ("capped", {"type": "json_schema",
                "json_schema": {"name": "capped", "schema": SCHEMA_CAPPED}}),
    ("noreason", {"type": "json_schema",
                  "json_schema": {"name": "sel", "schema": SCHEMA_NOREASON}}),
    ("idsonly", {"type": "json_schema",
                 "json_schema": {"name": "ids", "schema": SCHEMA_IDSONLY}}),
]
TAGS = [t for t, _ in VARIANTS]


def tokenize(text: str) -> int:
    """Token count from the server's own tokenizer, so it matches usage.*."""
    req = urllib.request.Request(
        f"{BASE}/tokenize", data=json.dumps({"model": MODEL, "prompt": text}).encode(),
        headers={"Content-Type": "application/json"})
    try:
        return json.load(urllib.request.urlopen(req, timeout=60))["count"]
    except Exception:
        return -1


def dissect(payload: dict) -> dict:
    """Where did the tokens go: entry count, or bytes per entry, or extra keys?"""
    entries = payload.get("selected_concepts", [])
    ids = ({int(i) for i in payload.get("selected_ids", [])} if "selected_ids" in payload
           else {int(c["concept_id"]) for c in entries
                 if c.get("relevant", True) and c.get("concept_id") is not None})
    reason_chars = sum(len(str(c.get("reasoning", ""))) for c in entries)
    # Any key the code never reads. This is where a reasoning model hides.
    known = {"selected_concepts", "overall_reasoning", "selected_ids"}
    extra = {k: len(json.dumps(v)) for k, v in payload.items() if k not in known}
    return {
        "n_entries": len(entries),
        "n_relevant_true": sum(1 for c in entries if c.get("relevant") is True),
        "ids": sorted(ids),
        "reason_chars": reason_chars,
        "reason_chars_per_entry": round(reason_chars / len(entries), 1) if entries else 0,
        "overall_reasoning_chars": len(str(payload.get("overall_reasoning", ""))),
        "extra_keys": extra,
        "emitted_fields": sorted({k for c in entries for k in c}) if entries else [],
    }


results = []
with open(OUT, "w", encoding="utf-8") as fh:
    for query, candidates_text in CASES:
        n_cand = candidates_text.count("\n") + 1
        print(f"\n### {query}  ({n_cand} candidates)", flush=True)
        messages = real_messages(query, candidates_text)
        for tag, rf in VARIANTS:
            body = {"model": MODEL, "temperature": 0, "seed": 42,
                    "response_format": rf, "messages": messages}
            t = time.time()
            row = {"query": query, "tag": tag, "n_candidates": n_cand}
            try:
                req = urllib.request.Request(
                    URL, data=json.dumps(body).encode(),
                    headers={"Content-Type": "application/json"})
                d = json.load(urllib.request.urlopen(req, timeout=3600))
                el = time.time() - t
                content = d["choices"][0]["message"]["content"]
                out_tok = d["usage"]["completion_tokens"]
                row.update(s=round(el, 1), out_tokens=out_tok,
                           tok_s=round(out_tok / el, 2) if el else 0,
                           finish=d["choices"][0].get("finish_reason"),
                           content_tokens=tokenize(content))
                try:
                    row.update(parsed=True, **dissect(json.loads(content)))
                    row["tok_per_candidate"] = round(out_tok / n_cand, 1)
                except Exception as exc:
                    row.update(parsed=False, parse_error=f"{type(exc).__name__}: {exc}"[:120],
                               head=content[:200], ids=[])
            except Exception as e:
                detail = str(e)[:160]
                if hasattr(e, "read"):
                    detail += " || " + e.read()[:200].decode(errors="replace")
                row.update(s=round(time.time() - t, 1), error=type(e).__name__,
                           detail=detail, ids=[])
            results.append(row)
            fh.write(json.dumps(row) + "\n")
            fh.flush()
            print("  " + json.dumps({k: v for k, v in row.items()
                                     if k not in ("ids", "query", "head")}), flush=True)

# ── verdict ──────────────────────────────────────────────────────────────────
print("\n=== selection agreement vs current ===", flush=True)
by_query: dict[str, dict[str, dict]] = {}
for r in results:
    by_query.setdefault(r["query"], {})[r["tag"]] = r

agg = {t: {"inter": 0, "union": 0, "tok": 0, "s": 0.0, "parsed": 0, "n": 0} for t in TAGS}
for query, rows in by_query.items():
    base = rows.get("current", {})
    print(f"\n{query}", flush=True)
    for tag in TAGS:
        r = rows.get(tag, {})
        a, b = set(base.get("ids") or []), set(r.get("ids") or [])
        st = agg[tag]
        st["n"] += 1
        st["parsed"] += 1 if r.get("parsed") else 0
        st["tok"] += r.get("out_tokens", 0)
        st["s"] += r.get("s", 0)
        st["inter"] += len(a & b)
        st["union"] += len(a | b)
        if tag == "current":
            print(f"  current : {len(a)} selected, {base.get('out_tokens')} tok, "
                  f"{base.get('s')}s, entries={base.get('n_entries')}", flush=True)
            continue
        union = len(a | b)
        print(f"  {tag:9s}: jaccard={len(a & b) / union if union else 0:.2f} "
              f"({len(a & b)}/{union})  {r.get('out_tokens')} tok  {r.get('s')}s  "
              f"parsed={r.get('parsed')}", flush=True)
        print(f"    only in current: {sorted(a - b)}", flush=True)
        print(f"    only in {tag}:   {sorted(b - a)}", flush=True)

print("\n=== totals ===", flush=True)
base_tok = agg["current"]["tok"] or 1
for tag, st in agg.items():
    j = st["inter"] / st["union"] if st["union"] else 0
    print(f"  {tag:9s} tokens={st['tok']:6d} ({base_tok / (st['tok'] or 1):.1f}x less)  "
          f"wall={st['s']:7.1f}s  parsed={st['parsed']}/{st['n']}  "
          f"pooled_jaccard={j:.2f}", flush=True)
PYEOF

log "done — $OUT"
