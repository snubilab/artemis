#!/usr/bin/env python3
"""Per-row A/B/placebo harness for ONE edit to the planner's DECOMPOSITION_PROMPT.

WHY THIS EXISTS RATHER THAN ``scripts/prompt_ab.py``
-----------------------------------------------------
``prompt_ab.py`` patches ``parser.NCT_SYSTEM_PROMPT`` and stops at ``parse_nct``.
It measures Agent 1. Some defects are not Agent 1's: CARMELINA's delivered
``Elevated Total Bilirubin`` exclusion appears **0 times** in all 11 recorded
CARMELINA Agent 1 IR caches and 0 times in the NCT record. It is minted one stage
later, by ``CriteriaPlanner._decompose_criterion``, from ``DECOMPOSITION_PROMPT``.
A harness that cannot see that stage cannot contain the defect, and a run at a
stage that cannot contain the defect measures nothing -- it reports 0 ungrounded
and reads like a clean result.

So this harness drives the decomposer directly. Three consequences, all good:

  * **The input is held fixed structurally, not checked afterwards.** Every arm
    receives the *same* ``Criteria`` field values, loaded verbatim from the Agent 1
    IR cache file that produced the delivered store. ``prompt_ab.py`` needs an
    input-identity gate because it re-runs Agent 1 and cannot guarantee this.
  * **There is no planner cache**, so no cache-key confound. The placebo arm
    therefore controls for the thing that actually remains: that *any*
    perturbation of the prompt bytes moves the answer.
  * **An arm is one LLM call per criterion, not a 30-minute Agent 1 run.** That
    buys REPLICATES, which is the difference between "this one sample differed"
    and "the rate differed beyond the baseline's own run-to-run variance".

THE THREE ARMS (placebo MANDATORY, as in prompt_ab.py)
------------------------------------------------------
  baseline   DECOMPOSITION_PROMPT exactly as it is on disk
  candidate  the edited prompt, read from a file so the live module is never
             touched by a run
  placebo    baseline with a semantically null perturbation (trailing space on a
             '**...**:' marker line)

INTERLEAVING
------------
Arms are NOT run block-by-block. For each replicate, each criterion is put to all
three arms before moving on, and the arm order rotates per replicate. Running
36 baseline calls, then 36 candidate calls, would confound arm with wall-clock
position in the vLLM server's batching state.

THE VERDICT RULE (per row, on RATES across replicates -- never pooled across rows)
----------------------------------------------------------------------------------
  rate(candidate) != rate(baseline) AND rate(placebo) == rate(baseline)
      -> EFFECT
  rate(candidate) != rate(baseline) AND rate(placebo) != rate(baseline)
      -> INDISTINGUISHABLE FROM PROMPT-BYTE CHURN
  rate(candidate) == rate(baseline)
      -> NO EFFECT

USAGE
-----
    .venv/bin/python scripts/planner_example_ab.py --dump-baseline-prompt P.txt
    .venv/bin/python scripts/planner_example_ab.py \
        --ir-cache data/cache/agent1_ir/NCT01897532_..._7ae74b822cdf141a.json \
        --targets-file targets.txt \
        --candidate-prompt candidate.txt --replicates 6 --json out.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

_WS = re.compile(r"\s+")

# The .format() keys DECOMPOSITION_PROMPT must still accept after an edit. A
# candidate that drops or renames one raises at format() time inside the planner,
# where the exception is swallowed by _decompose_criterion's bare except and the
# arm silently returns every criterion undecomposed -- which looks exactly like a
# candidate that suppressed the defect.
_FORMAT_KEYS = {"name": "N", "entity_text": "E", "domain": "D",
                "logic_type": "ABSENCE", "source_text": "S"}


def norm(text) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", str(text)).replace(" ", " ")
    return _WS.sub(" ", text).strip().casefold()


# --------------------------------------------------------------------------
# targets: criteria named BEFORE the run, matched against the IR by source_text
# --------------------------------------------------------------------------

def parse_target(raw: str) -> tuple[str, str]:
    if "::" in raw:
        label, _, match = raw.partition("::")
        label, match = label.strip(), match.strip()
    else:
        match = raw.strip()
        label = (match[:48] + "...") if len(match) > 48 else match
    if len(norm(match)) < 12:
        raise SystemExit(f"target match text {match!r} is under 12 normalized chars")
    return label, match


def load_targets(args) -> list[tuple[str, str]]:
    raw = list(args.target_row or [])
    if args.targets_file:
        for line in Path(args.targets_file).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                raw.append(line)
    if not raw:
        raise SystemExit("no target rows given. Name them BEFORE running.")
    out, seen = [], set()
    for r in raw:
        label, match = parse_target(r)
        if norm(match) in seen:
            raise SystemExit(f"duplicate target: {match!r}")
        seen.add(norm(match))
        out.append((label, match))
    return out


def load_ir_criteria(ir_path: Path):
    """Every criterion in the IR cache, as raw dicts plus the Criteria class.

    Loaded from the cache FILE rather than retyped, so the three arms provably
    receive the input the delivered store was built from.
    """
    from src.models.ir import Criteria
    d = json.loads(ir_path.read_text(encoding="utf-8"))
    out = []
    for coh in ("target", "comparator"):
        c = d.get(coh) or {}
        for kind in ("inclusion_rules", "exclusion_rules"):
            for r in c.get(kind, []):
                out.append((f"{coh}.{kind.split('_')[0]}", r))
    return out, Criteria


def match_ir(records, match_text):
    want = norm(match_text)
    hits = []
    for sec, r in records:
        got = norm(r.get("source_text"))
        if not got or min(len(want), len(got)) < 20:
            continue
        if want in got or got in want:
            hits.append((sec, r))
    return hits


# --------------------------------------------------------------------------
# placebo
# --------------------------------------------------------------------------

def make_placebo(prompt: str, index: int) -> tuple[str, str]:
    lines = prompt.split("\n")
    marks = [i for i, ln in enumerate(lines)
             if ln.strip().startswith("**") and ln.rstrip().endswith(":")]
    if not marks:
        raise SystemExit(
            "the baseline DECOMPOSITION_PROMPT has no '**...**:' marker line to "
            "perturb, so no null placebo can be built. Refusing to run: without a "
            "placebo arm this harness cannot tell an effect from prompt-byte churn."
        )
    if index >= len(marks):
        raise SystemExit(f"--placebo-marker-index {index} but only {len(marks)} markers")
    ln = marks[index]
    lines[ln] = lines[ln] + " "
    return "\n".join(lines), f"trailing space appended to line {ln+1}: {lines[ln].strip()!r}"


# --------------------------------------------------------------------------
# observation of one decomposition
# --------------------------------------------------------------------------

def observe(crit) -> dict:
    """What one decomposition produced, in comparable form."""
    from src.utils.naming_words import naming_words
    from src.utils.circe_lint import _line_names_the_criterion

    line_words = naming_words(crit.source_text or "")
    members = []
    for sc in crit.sub_criteria:
        claimed = naming_words(sc.entity_text) | naming_words(sc.name)
        # The lint's own predicate, not a re-implementation of it: this is the
        # same question `circe_lint.ungrounded_criteria` asks of a delivered
        # artifact, asked one stage earlier where the member is minted.
        lint_grounded = bool(line_words and claimed
                             and _line_names_the_criterion(claimed, line_words))
        vc = sc.value_constraint
        members.append({
            "entity_text": sc.entity_text,
            "name": sc.name,
            "domain": sc.domain,
            # verified span (decomposer._grounded_span), not the model's claim
            "span": sc.source_span,
            "grounded_span": sc.source_span is not None,
            "lint_grounded": lint_grounded,
            "vc_op": getattr(vc, "op", None),
            "vc_value": getattr(vc, "value", None),
            "vc_bound": getattr(vc, "reference_bound", None),
        })
    members.sort(key=lambda m: norm(m["entity_text"]))
    return {
        "decomposed": bool(crit.sub_criteria),
        "group_type": crit.group_type,
        "n_members": len(members),
        "n_grounded_span": sum(1 for m in members if m["grounded_span"]),
        "n_lint_ungrounded": sum(1 for m in members if not m["lint_grounded"]),
        "member_key": tuple(norm(m["entity_text"]) for m in members),
        "members": members,
    }


def run_one(arm_prompt: str, raw: dict, Criteria, planner) -> dict:
    """One decomposition of one criterion under one prompt arm."""
    import contextlib
    import io
    import src.agents.planner.decomposer as dec_mod

    crit = Criteria(
        name=raw.get("name") or "Unnamed",
        domain=raw.get("domain"),
        entity_text=raw.get("entity_text"),
        source_text=raw.get("source_text"),
        logic_type=raw.get("logic_type"),
        window=raw.get("window"),
    )
    saved = dec_mod.DECOMPOSITION_PROMPT
    buf = io.StringIO()
    t0 = time.time()
    try:
        dec_mod.DECOMPOSITION_PROMPT = arm_prompt
        with contextlib.redirect_stdout(buf):
            out = planner._decompose_criterion(crit)
    finally:
        dec_mod.DECOMPOSITION_PROMPT = saved
    rec = observe(out)
    rec["elapsed_s"] = round(time.time() - t0, 1)
    rec["log"] = buf.getvalue().strip()
    return rec


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ir-cache", help="Agent 1 IR cache json the arms read their input from")
    ap.add_argument("--target-row", action="append", metavar="'LABEL :: TEXT'")
    ap.add_argument("--targets-file", metavar="PATH")
    ap.add_argument("--candidate-prompt", metavar="PATH")
    ap.add_argument("--dump-baseline-prompt", metavar="PATH")
    ap.add_argument("--placebo-marker-index", type=int, default=0)
    ap.add_argument("--replicates", type=int, default=6)
    ap.add_argument("--json", metavar="PATH")
    args = ap.parse_args()

    os.environ.setdefault("AGENT1_IR_CACHE_ENABLED", "true")
    from src.agents.planner.prompts import DECOMPOSITION_PROMPT as BASELINE

    if args.dump_baseline_prompt:
        Path(args.dump_baseline_prompt).write_text(BASELINE, encoding="utf-8")
        print(f"baseline DECOMPOSITION_PROMPT ({len(BASELINE)} chars) -> "
              f"{args.dump_baseline_prompt}")
        return 0

    for req in ("ir_cache", "candidate_prompt"):
        if not getattr(args, req):
            ap.error(f"--{req.replace('_', '-')} is required")

    candidate = Path(args.candidate_prompt).read_text(encoding="utf-8")
    placebo, placebo_desc = make_placebo(BASELINE, args.placebo_marker_index)

    if candidate == BASELINE:
        raise SystemExit("candidate is byte-identical to baseline. Refusing.")
    if candidate == placebo:
        raise SystemExit("candidate is byte-identical to placebo. Refusing.")
    if placebo == BASELINE:
        raise SystemExit("the placebo perturbation changed nothing. Refusing.")

    # Template-compatibility gate. A candidate that breaks a {placeholder} or an
    # unescaped brace raises inside _decompose_criterion, whose bare `except`
    # swallows it and returns the criterion undecomposed -- indistinguishable, in
    # the results table, from a candidate that suppressed the defect.
    for label, text in (("candidate", candidate), ("placebo", placebo)):
        try:
            text.format(**_FORMAT_KEYS)
        except (KeyError, IndexError, ValueError) as exc:
            raise SystemExit(
                f"{label} prompt does not .format() with the keys the planner "
                f"passes ({sorted(_FORMAT_KEYS)}): {exc!r}. Refusing -- this would "
                f"fail silently as 'no decomposition' in every row."
            )

    targets = load_targets(args)
    records, Criteria = load_ir_criteria(Path(args.ir_cache))

    resolved = []
    for label, match in targets:
        hits = match_ir(records, match)
        if len(hits) != 1:
            raise SystemExit(
                f"target {label!r} matched {len(hits)} IR criteria, need exactly 1. "
                f"Refusing: an ambiguous target cannot be a named row."
            )
        resolved.append((label, match, hits[0][0], hits[0][1]))

    from src.agents.planner.decomposer import CriteriaPlanner
    from src.utils.llm import resolve_model
    planner = CriteriaPlanner()
    model = resolve_model()

    arms = {"baseline": BASELINE, "candidate": candidate, "placebo": placebo}
    order = ["baseline", "candidate", "placebo"]

    print("=" * 78)
    print(f"PLANNER DECOMPOSITION_PROMPT A/B  --  model {model}")
    print("=" * 78)
    print(f"IR cache        : {args.ir_cache}")
    print(f"placebo         : {placebo_desc}")
    print(f"prompt lengths  : baseline={len(BASELINE)} candidate={len(candidate)} "
          f"placebo={len(placebo)}")
    print(f"replicates      : {args.replicates}   (arms interleaved, order rotated)")
    print(f"target rows     : {len(resolved)}  (named before the run)")
    for label, match, sec, raw in resolved:
        print(f"  - {label}  [{sec}]  entity={raw.get('entity_text')!r}")
    total = args.replicates * len(resolved) * 3
    print(f"total LLM calls : {total}")
    print("-" * 78, flush=True)

    obs: dict = {label: {a: [] for a in arms} for label, *_ in resolved}
    done = 0
    t_start = time.time()
    for rep in range(args.replicates):
        rot = order[rep % 3:] + order[:rep % 3]
        for label, match, sec, raw in resolved:
            for arm in rot:
                rec = run_one(arms[arm], raw, Criteria, planner)
                rec["replicate"] = rep
                obs[label][arm].append(rec)
                done += 1
                el = time.time() - t_start
                print(f"  [{done:3d}/{total}] rep{rep} {arm:<9} {label:<22} "
                      f"n={rec['n_members']} span_ok={rec['n_grounded_span']} "
                      f"lint_ung={rec['n_lint_ungrounded']} {rec['elapsed_s']}s "
                      f"(elapsed {el/60:.1f}m)", flush=True)

    # ----------------------------------------------------------------- report
    print("\n" + "=" * 78)
    print("PER-ROW RESULT   (each row stands alone -- nothing here is pooled)")
    print("=" * 78)

    out = {"model": model, "ir_cache": args.ir_cache, "replicates": args.replicates,
           "placebo_perturbation": placebo_desc, "rows": []}

    for label, match, sec, raw in resolved:
        print(f"\nROW: {label}")
        print(f"  section   : {sec}")
        print(f"  line      : {(raw.get('source_text') or '')[:150]}")
        per_arm = {}
        for arm in order:
            recs = obs[label][arm]
            uniq: dict = {}
            for r in recs:
                uniq[r["member_key"]] = uniq.get(r["member_key"], 0) + 1
            per_arm[arm] = {
                "n": len(recs),
                "member_sets": [{"members": list(k), "count": c}
                                for k, c in sorted(uniq.items(), key=lambda kv: -kv[1])],
                "mean_members": round(sum(r["n_members"] for r in recs) / len(recs), 2),
                "mean_lint_ungrounded": round(
                    sum(r["n_lint_ungrounded"] for r in recs) / len(recs), 2),
                "total_lint_ungrounded": sum(r["n_lint_ungrounded"] for r in recs),
                "decomposed_rate": f"{sum(1 for r in recs if r['decomposed'])}/{len(recs)}",
                "group_types": sorted({str(r["group_type"]) for r in recs}),
            }
            print(f"  {arm:<9}: members/run={per_arm[arm]['mean_members']}  "
                  f"lint_ungrounded/run={per_arm[arm]['mean_lint_ungrounded']}  "
                  f"decomposed={per_arm[arm]['decomposed_rate']}  "
                  f"group_type={per_arm[arm]['group_types']}")
            for ms in per_arm[arm]["member_sets"]:
                print(f"             {ms['count']}/{len(recs)}  {ms['members']}")
        out["rows"].append({"label": label, "match": match, "section": sec,
                            "line": raw.get("source_text"),
                            "entity_text": raw.get("entity_text"),
                            "arms": per_arm,
                            "raw": {a: obs[label][a] for a in order}})

    print("\n" + "=" * 78)
    print("Scope: CriteriaPlanner._decompose_criterion only -- the stage that mints")
    print("the member. Downstream dedup, mapping and Circe export are not exercised.")
    print("=" * 78)

    if args.json:
        Path(args.json).write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
        print(f"\nfull result -> {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
