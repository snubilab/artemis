#!/usr/bin/env python3
"""What are Agent 1's worked examples worth? A four-arm, replicated A/B.

THE QUESTION
------------
The NCT system prompt teaches by worked example: a quoted protocol line paired
with its correct output. Seventeen of those quotations are lifted verbatim from
the six trials the pipeline is scored on, and the contamination demonstrably
leaks between studies -- ARISTOTLE's ``Total Bilirubin >= 1.5X ULN`` was minted
into CARMELINA, which has no bilirubin exclusion anywhere in its sources. So the
examples are load-bearing *and* poisoned. This measures what they are worth:

  baseline   NCT_SYSTEM_PROMPT as of HEAD -- the real corpus text
  synthetic  every corpus-derived example replaced with an invented trial line
  none       the worked examples removed, the surrounding instruction intact
  placebo    baseline with a semantically null perturbation

WHY ALL FOUR ARMS COME FROM FILES
---------------------------------
``prompt_ab.py`` reads its baseline from the live module. That is correct for its
own purpose and wrong for this one: the live module has already had the
substitution applied, so importing it would silently make "baseline" the
synthetic arm and the experiment would compare synthetic against itself. Every
arm here is read from a snapshot path named on the command line, so a concurrent
edit to ``src/`` cannot move an arm under a running measurement.

REPLICATES, AND WHY THEY NEED A PERTURBATION
--------------------------------------------
The Agent 1 IR cache key hashes the system prompt, so re-running one arm returns
the identical cached sample -- a replicate is impossible without changing the
bytes. Replicate ``r > 0`` of every arm is therefore that arm's text with ``r``
trailing spaces appended to its first ``## `` heading: a fresh draw from the
model, semantically identical to replicate 0. Every (arm, replicate) prompt is
asserted distinct before any LLM call, because two colliding on one cache key
would silently report one sample as two.

The placebo arm perturbs the LAST heading instead, so it cannot collide with any
baseline replicate.

THE VERDICT RULE (per metric, per row -- never pooled across rows)
-----------------------------------------------------------------
A row or metric moves only when it differs baseline -> arm AND does not differ
baseline -> placebo. Anything a null edit reproduces is prompt-byte churn, not
evidence about the examples.

WHAT IS MEASURED
----------------
  fabrication          circe_lint._line_names_the_criterion over every emitted
                       criterion -- the lint's own predicate, not a copy of it
  decomposition        named control rows: did each still decompose, into how
                       many members, under what group_type
  criterion count      top-level rules and total criteria
  value constraints    how many criteria carry one
  entity_text loss     leaves carrying no entity_text -- the most sensitive
                       damage signal found so far (a bad instruction took it
                       3 -> 12 where the placebo moved 3 -> 5)

SCOPE
-----
Agent 1 ``parse_nct`` only: before TTEService, before dedup, before mapping,
before Circe export. A criterion present here and absent in a study store is a
downstream question this harness cannot answer.

USAGE
-----
    .venv/bin/python scripts/example_value_ab.py \
        --nct NCT01730534 \
        --arm baseline=/tmp/exlab/arm_baseline.txt \
        --arm synthetic=/tmp/exlab/arm_synthetic.txt \
        --arm none=/tmp/exlab/arm_none.txt \
        --controls-file /tmp/exlab/controls.txt \
        --replicates 3 --json /tmp/exlab/result.json
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

# The cache must be ON: the key includes the system prompt, so each (arm,
# replicate) gets its own file and an interrupted run resumes free.
os.environ.setdefault("AGENT1_IR_CACHE_ENABLED", "true")

from scripts.prompt_ab import norm  # noqa: E402  (one definition of "same line")


# --------------------------------------------------------------------------
# arms
# --------------------------------------------------------------------------

def perturb(prompt: str, index: int, spaces: int) -> tuple[str, str]:
    """Append ``spaces`` trailing spaces to the ``index``-th '## ' heading.

    Semantically null and byte-visible: it changes what the cache key hashes and
    changes nothing a reader of the prompt could act on. This is the established
    form -- the perturbation that churned 17 rows on PLATO while saying nothing.
    """
    lines = prompt.split("\n")
    heads = [i for i, ln in enumerate(lines) if ln.startswith("## ")]
    if not heads:
        raise SystemExit(
            "this prompt has no '## ' heading to perturb, so neither a placebo "
            "nor a replicate can be built. Refusing: without them an arm cannot "
            "be told from prompt-byte churn."
        )
    ln = heads[index % len(heads)]
    lines[ln] = lines[ln] + " " * spaces
    return "\n".join(lines), f"{spaces} space(s) on line {ln + 1}: {lines[ln].strip()!r}"


def build_arms(paths: dict[str, str], replicates: int) -> dict[tuple[str, int], dict]:
    """Every (arm, replicate) prompt, with collisions refused up front."""
    base = Path(paths["baseline"]).read_text(encoding="utf-8")
    texts = {name: Path(p).read_text(encoding="utf-8") for name, p in paths.items()}

    # placebo perturbs the LAST heading; replicates perturb the FIRST, so a
    # placebo can never collide with a baseline replicate.
    n_head = sum(1 for ln in base.split("\n") if ln.startswith("## "))
    texts["placebo"], placebo_desc = perturb(base, n_head - 1, 1)
    if texts["placebo"] == base:
        raise SystemExit("the placebo perturbation changed nothing. Refusing.")

    for name, text in texts.items():
        if name in ("baseline", "placebo"):
            continue
        if text == base:
            raise SystemExit(f"arm {name!r} is byte-identical to baseline. Refusing.")
        if text == texts["placebo"]:
            raise SystemExit(f"arm {name!r} is byte-identical to the placebo. Refusing.")

    out: dict[tuple[str, int], dict] = {}
    for name, text in texts.items():
        for rep in range(replicates):
            body, desc = (text, "unperturbed") if rep == 0 else perturb(text, 0, rep)
            out[(name, rep)] = {"prompt": body, "perturbation": desc}

    seen: dict[str, tuple[str, int]] = {}
    for key, rec in out.items():
        if rec["prompt"] in seen:
            raise SystemExit(
                f"{key} and {seen[rec['prompt']]} are byte-identical, so they share one "
                f"IR cache key and one sample would be reported as two. Refusing."
            )
        seen[rec["prompt"]] = key
    return out, placebo_desc


# --------------------------------------------------------------------------
# observation
# --------------------------------------------------------------------------

def walk(rule, section: str, depth: int = 0, parent=None) -> list[dict]:
    from src.utils.circe_lint import _line_names_the_criterion
    from src.utils.naming_words import naming_words

    line_words = naming_words(rule.source_text or "")
    claimed = naming_words(rule.entity_text) | naming_words(rule.name)
    vc = rule.value_constraint
    rec = {
        "section": section,
        "depth": depth,
        "name": rule.name,
        "domain": rule.domain,
        "entity_text": rule.entity_text,
        "source_text": rule.source_text,
        "logic_type": rule.logic_type,
        "is_group": bool(rule.sub_criteria),
        "group_type": rule.group_type if rule.sub_criteria else None,
        "n_members": len(rule.sub_criteria),
        "parent_source_text": (parent.source_text if parent is not None else None),
        # The lint's own predicate, asked one stage earlier than the delivered
        # artifact -- a criterion whose own protocol line does not name what it
        # claims is a fabrication wherever it is observed.
        "lint_grounded": bool(line_words and claimed
                              and _line_names_the_criterion(claimed, line_words)),
        "has_line": bool(line_words),
        "has_claim": bool(claimed),
        "vc_op": getattr(vc, "op", None),
        "vc_value": getattr(vc, "value", None),
        "vc_unit": getattr(vc, "unit_text", None),
    }
    out = [rec]
    for sc in rule.sub_criteria:
        out.extend(walk(sc, section, depth + 1, rule))
    return out


def observe(ir, controls: list[tuple[str, str]]) -> dict:
    rows: list[dict] = []
    for coh_name in ("target", "comparator"):
        coh = getattr(ir, coh_name)
        for kind in ("inclusion_rules", "exclusion_rules"):
            for r in getattr(coh, kind):
                rows.extend(walk(r, f"{coh_name}.{kind.split('_')[0]}"))

    tgt = [r for r in rows if r["section"].startswith("target")]
    leaves = [r for r in tgt if not r["is_group"]]
    # Fabrication is only askable of a criterion that HAS a line and HAS a claim;
    # a row missing either is counted separately rather than scored as grounded.
    askable = [r for r in tgt if r["has_line"] and r["has_claim"]]

    metrics = {
        "n_top_level": sum(1 for r in tgt if r["depth"] == 0),
        "n_criteria": len(tgt),
        "n_groups": sum(1 for r in tgt if r["is_group"]),
        "n_leaves": len(leaves),
        "n_value_constraints": sum(1 for r in tgt if r["vc_op"] is not None),
        "n_leaf_no_entity_text": sum(1 for r in leaves if not r["entity_text"]),
        "n_fabricated": sum(1 for r in askable if not r["lint_grounded"]),
        "n_askable": len(askable),
        "n_unaskable": len(tgt) - len(askable),
    }

    # Named control rows: did the criterion still decompose?
    ctrl = {}
    for label, match in controls:
        want = norm(match)
        hits = [r for r in tgt
                if r["depth"] == 0
                and norm(r["source_text"])
                and min(len(want), len(norm(r["source_text"]))) >= 20
                and (want in norm(r["source_text"]) or norm(r["source_text"]) in want)]
        members = []
        for h in hits:
            members += [r["entity_text"] or r["name"] for r in tgt
                        if r["parent_source_text"] == h["source_text"] and r["depth"] > 0]
        ctrl[label] = {
            "matched": len(hits),
            "decomposed": any(h["is_group"] for h in hits),
            "group_type": sorted({str(h["group_type"]) for h in hits if h["is_group"]}),
            "n_members": max([h["n_members"] for h in hits], default=0),
            "members": sorted({norm(m) for m in members if m}),
        }
    return {"metrics": metrics, "controls": ctrl, "rows": rows}


def run_one(nct: str, prompt: str, tag: str, quiet: bool) -> dict:
    """One Agent 1 parse under one prompt. The live module is always restored."""
    import src.agents.agent1.parser as parser_mod
    from src.agents.agent1.parser import LogicDecomposer

    saved_prompt = parser_mod.NCT_SYSTEM_PROMPT
    saved_key = LogicDecomposer.__dict__["_ir_cache_key"].__func__
    cap: dict = {}

    def key_wrapper(model_key, sys_prompt, prompt_text):
        h = saved_key(model_key, sys_prompt, prompt_text)
        cap.update(model_key=model_key, human_prompt=prompt_text, ir_hash=h)
        return h

    buf = io.StringIO()
    t0 = time.time()
    try:
        parser_mod.NCT_SYSTEM_PROMPT = prompt
        LogicDecomposer._ir_cache_key = staticmethod(key_wrapper)
        with contextlib.redirect_stdout(buf):
            ir = LogicDecomposer().parse_nct(nct, verify_thresholds=False)
    finally:
        parser_mod.NCT_SYSTEM_PROMPT = saved_prompt
        LogicDecomposer._ir_cache_key = staticmethod(saved_key)

    log = buf.getvalue()
    if "ir_hash" not in cap:
        raise SystemExit(
            f"{tag}: the IR cache key was never computed, so the human prompt could "
            f"not be captured and cross-arm input identity cannot be checked. "
            f"Refusing to report."
        )
    return {
        "ir": ir,
        "ir_hash": cap["ir_hash"],
        "model_key": cap["model_key"],
        "human_prompt": cap["human_prompt"],
        "cache_hit": "Cache HIT" in log,
        "elapsed_s": round(time.time() - t0, 1),
        "log_tail": log[-600:],
    }


def load_controls(path: str) -> list[tuple[str, str]]:
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        label, _, match = line.partition("::")
        label, match = label.strip(), match.strip()
        if len(norm(match)) < 20:
            raise SystemExit(f"control {label!r} match text is under 20 normalized chars")
        out.append((label, match))
    if not out:
        raise SystemExit("no control rows given. Name them BEFORE the run.")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--nct", required=True)
    ap.add_argument("--arm", action="append", required=True, metavar="NAME=PATH",
                    help="repeatable; 'baseline' is mandatory among them")
    ap.add_argument("--controls-file", required=True)
    ap.add_argument("--replicates", type=int, default=3)
    ap.add_argument("--json", metavar="PATH")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    paths = {}
    for spec in args.arm:
        name, _, p = spec.partition("=")
        if not p:
            ap.error(f"--arm {spec!r} is not NAME=PATH")
        paths[name.strip()] = p.strip()
    if "baseline" not in paths:
        ap.error("one arm must be named 'baseline'")
    if "placebo" in paths:
        ap.error("'placebo' is built from baseline, not supplied")

    controls = load_controls(args.controls_file)
    plan, placebo_desc = build_arms(paths, args.replicates)
    order = list(paths) + ["placebo"]

    print("=" * 78)
    print(f"AGENT 1 EXAMPLE-VALUE A/B  --  {args.nct}")
    print("=" * 78)
    for name in order:
        src = paths.get(name, "(built from baseline)")
        print(f"  arm {name:<10} {len(plan[(name,0)]['prompt']):6d} chars   {src}")
    print(f"  placebo        : {placebo_desc}")
    print(f"  replicates     : {args.replicates}   (arms interleaved, order rotated)")
    print(f"  control rows   : {len(controls)}  (named before the run)")
    for label, match in controls:
        print(f"     - {label}: {match[:70]}")
    print(f"  total parses   : {len(plan)}")
    print("-" * 78, flush=True)

    results: dict = {}
    done, t_start = 0, time.time()
    for rep in range(args.replicates):
        rot = order[rep % len(order):] + order[:rep % len(order)]
        for name in rot:
            rec = run_one(args.nct, plan[(name, rep)]["prompt"], f"{name}/rep{rep}", args.quiet)
            obs = observe(rec["ir"], controls)
            m = obs["metrics"]
            results[f"{name}/rep{rep}"] = {
                "arm": name, "replicate": rep,
                "ir_hash": rec["ir_hash"], "cache_hit": rec["cache_hit"],
                "elapsed_s": rec["elapsed_s"],
                "human_prompt_sha": __import__("hashlib").sha1(
                    rec["human_prompt"].encode()).hexdigest()[:12],
                "perturbation": plan[(name, rep)]["perturbation"],
                "prompt_chars": len(plan[(name, rep)]["prompt"]),
                "metrics": m, "controls": obs["controls"], "rows": obs["rows"],
            }
            done += 1
            print(f"  [{done:2d}/{len(plan)}] {name:<10} rep{rep} "
                  f"crit={m['n_criteria']:3d} grp={m['n_groups']:2d} "
                  f"vc={m['n_value_constraints']:3d} noent={m['n_leaf_no_entity_text']:3d} "
                  f"fab={m['n_fabricated']:3d}/{m['n_askable']:3d} "
                  f"{'HIT' if rec['cache_hit'] else 'llm'} {rec['elapsed_s']:.0f}s "
                  f"(elapsed {(time.time()-t_start)/60:.1f}m)", flush=True)
            if args.json:   # written every parse, so a killed run is not lost
                Path(args.json).write_text(
                    json.dumps({"nct": args.nct, "placebo": placebo_desc,
                                "arm_paths": paths, "controls": controls,
                                "runs": results}, ensure_ascii=False, indent=1),
                    encoding="utf-8")

    # ------------------------------------------------------------- input gate
    shas = {k: v["human_prompt_sha"] for k, v in results.items()}
    if len(set(shas.values())) != 1:
        print("\n!! INPUT NOT HELD FIXED across arms -- the arms did not receive the "
              "same criteria, so no difference below is attributable to the prompt:")
        for k, v in sorted(shas.items()):
            print(f"     {k:<20} {v}")
    else:
        print(f"\ninput identity: all {len(results)} parses received the same human "
              f"prompt (sha {next(iter(shas.values()))})")
    print("=" * 78)
    if args.json:
        print(f"full result -> {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
