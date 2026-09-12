#!/usr/bin/env python3
"""Per-row A/B/placebo harness for an Agent 1 system-prompt edit.

WHY THIS EXISTS
---------------
A whole-batch before/after criteria count is not evidence about a prompt edit,
and never will be. Two measurements say so:

  * On PLATO, a *placebo* edit (one trailing space in a heading, semantically
    null) churned MORE than a real edit: real lost 15 / gained 15, placebo lost
    17 / gained 14.
  * In the 2026-09-11 full run, four studies received byte-identical Agent 1
    input under a changed system prompt and still churned 8-43%; CARMELINA went
    from 36 to 66 store criteria on identical input.

The Agent 1 IR cache key hashes the system prompt (``parser.py``
``_ir_cache_key``), so ANY prompt edit -- a comment included -- invalidates
every cached trial and forces a fresh sample from the model. Re-sampling alone
moves roughly a third of a trial's rows. So a batch delta measures the cache
key, not the edit.

This harness asks the only question a prompt edit can be held to: *did these
named rows change, and did they change for a reason a null edit cannot
reproduce?* The caller names the target rows BEFORE running.

THE THREE ARMS
--------------
  baseline   the prompts exactly as they are on disk
  candidate  the prompts with the caller's edit (read from a file, so the live
             module is never touched by a run)
  placebo    the baseline prompt with a semantically null perturbation
             (a trailing space appended to a "## " heading)

The placebo arm is MANDATORY. It is the only thing separating "the edit did
something" from "the cache key changed". A run without it refuses to print a
verdict.

THE VERDICT RULE (per row -- never aggregated, never averaged, never scored)
---------------------------------------------------------------------------
  differs(baseline, candidate) AND NOT differs(baseline, placebo)
      -> EFFECT
  differs(baseline, candidate) AND differs(baseline, placebo)
      -> INDISTINGUISHABLE FROM CACHE-KEY CHURN
  NOT differs(baseline, candidate)
      -> NO EFFECT

WHAT A ROW'S STATE INCLUDES (and why the group structure is part of it)
-----------------------------------------------------------------------
A row is compared on its emitted substance -- section, name, domain, entity_text --
AND on the group structure it sits in: whether it heads a group, what that group's
``group_type`` is, which group it is a member of, and what THAT group's type is.

Without the group fields an edit that flips a group from ANY to ALL, or that turns
two flat rules into one group, reads as NO EFFECT: every name, domain and
entity_text is unchanged and only the logic connecting them moved. That is the
exact class of edit this harness was extended to measure, so an instrument blind
to it would answer the wrong question confidently.

A group's identity (``group_id``) is CONTENT-DERIVED, never a uuid: a uuid is
minted per run and would differ between arms for a group that did not change,
making every group look moved. The identity is a short hash of the group label's
own text (name, entity_text, source_text) plus the sorted normalized text of its
members. So:

  * the same group emitted by two arms hashes to the same id;
  * a group whose MEMBERSHIP or LABEL changed hashes to a different id -- which is
    a structural difference the verdict should see, not noise to be smoothed over;
  * ``group_type`` is deliberately NOT part of the id, so a pure type flip shows up
    in the ``group_type`` field rather than by silently renaming the group.

Members carry ``member_of`` (their group's id) and ``member_of_type`` (their
group's type), so a type flip is visible on every member as well as on the label.
Nested groups fall out of this: a sub-criterion that itself has sub_criteria
carries both its own ``group_id``/``group_type`` and its parent's.

WHAT IT DOES NOT MEASURE
------------------------
Agent 1 only. ``parse_nct`` output, before ``TTEService.process_eligibility``,
before criteria dedup, before mapping, before Circe export. A row present here
and absent in the study store is a downstream question this harness cannot
answer.

COST (measured 2026-09-11, CAROLINA on vllm/google/gemma-4-E4B-it)
------------------------------------------------------------------
A fresh arm is one Agent 1 call and took 1770-1830 s. An arm whose
(model, system prompt, human prompt) triple was already sampled is a cache HIT
and costs nothing. So the FIRST run of a new edit is ~1 hour (candidate +
placebo fresh, baseline usually a hit), and every later run that reuses the same
baseline and placebo is ~30 min for the candidate alone. This is a fast loop
relative to a 132-minute six-study reingest, not relative to a minute.

USAGE
-----
    .venv/bin/python scripts/prompt_ab.py \
        --nct NCT01243424 \
        --target-row "Signed ICF :: Signed and dated written informed consent" \
        --target-row "Stable background med :: Stable anti-diabetic background medication" \
        --candidate-prompt /tmp/candidate_system_prompt.txt

``--targets-file`` takes the same ``LABEL :: MATCH_TEXT`` lines, one per line
(``#`` comments and blank lines ignored). Without ``::`` the whole line is the
match text and the label is a truncation of it.

Write the candidate prompt file with ``--dump-baseline-prompt PATH`` first, then
edit that copy.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

# The whole point of an arm is a different system prompt, so the cache must be
# ON: the key already includes the system prompt, which gives each arm its own
# file and makes a re-run of the same arm free. Set before any src import so the
# module-level default cannot be read first.
os.environ.setdefault("AGENT1_IR_CACHE_ENABLED", "true")

_WS = re.compile(r"\s+")


def norm(text: str | None) -> str:
    """Casefolded, whitespace-collapsed, NFKC form for matching.

    Not for display and not for hashing -- only for deciding whether two strings
    name the same protocol line.
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text).replace("\u00a0", " ")
    return _WS.sub(" ", text).strip().casefold()


# --------------------------------------------------------------------------
# targets
# --------------------------------------------------------------------------

def parse_target(raw: str) -> tuple[str, str]:
    if "::" in raw:
        label, _, match = raw.partition("::")
        label, match = label.strip(), match.strip()
    else:
        match = raw.strip()
        label = (match[:48] + "...") if len(match) > 48 else match
    if not match:
        raise SystemExit(f"empty target-row match text in {raw!r}")
    if len(norm(match)) < 12:
        raise SystemExit(
            f"target-row match text {match!r} is under 12 normalized characters. "
            f"A fragment that short matches rows it does not name; give more of "
            f"the protocol line."
        )
    return label, match


def load_targets(args) -> list[tuple[str, str]]:
    raw: list[str] = list(args.target_row or [])
    if args.targets_file:
        for line in Path(args.targets_file).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                raw.append(line)
    if not raw:
        raise SystemExit(
            "no target rows given. Name the rows BEFORE running -- that is the "
            "entire discipline this harness enforces. Use --target-row or "
            "--targets-file."
        )
    targets, seen = [], set()
    for r in raw:
        label, match = parse_target(r)
        if norm(match) in seen:
            raise SystemExit(f"duplicate target row: {match!r}")
        seen.add(norm(match))
        targets.append((label, match))
    return targets


def cell(value) -> str:
    """One comparable cell of a row's state.

    ``None`` becomes a visible sentinel rather than an empty string: a criterion
    with no ``entity_text`` and a criterion with an empty one are different
    defects, and a tuple mixing ``None`` with ``str`` cannot be sorted at all.
    """
    return "∅" if value is None else str(value)


# --------------------------------------------------------------------------
# group structure
# --------------------------------------------------------------------------

def group_id(rule) -> str:
    """Content-derived identity of the group *rule* heads. Stable across arms.

    NOT a uuid: a uuid is minted per run, so two arms emitting the identical group
    would disagree on it and every group would read as moved. The id is derived
    from what the group IS -- the label's own text plus the sorted text of its
    members -- so an unchanged group hashes the same in every arm, and a group
    whose membership or label really changed hashes differently.

    ``group_type`` is excluded on purpose: a pure ANY<->ALL flip must show up as a
    changed ``group_type`` on a group that is otherwise recognisably the same
    group, not as a different group appearing where one vanished.

    Members are identified by ``entity_text`` and ``name`` together because either
    alone is routinely reworded between arms while the pair is the member.
    """
    parts = [norm(rule.name), norm(rule.entity_text), norm(rule.source_text)]
    parts += sorted(
        f"{norm(sc.entity_text)} {norm(sc.name)}" for sc in rule.sub_criteria
    )
    blob = "\x1f".join(parts).encode("utf-8")
    return hashlib.sha1(blob).hexdigest()[:10]


def walk_rule(rule, section: str, *, parent_id: str | None = None,
              parent_type: str | None = None) -> list[dict]:
    """One record per criterion in *rule*'s tree, group structure included.

    Sub-criteria are emitted as rows of their own. Before this, only top-level
    rules were recorded, so a group's members were invisible and an edit that
    changed what a group CONTAINS could not be told from one that changed nothing.
    """
    is_group = bool(rule.sub_criteria)
    gid = group_id(rule) if is_group else None
    out = [{
        "section": section,
        "name": rule.name,
        "domain": rule.domain,
        "entity_text": rule.entity_text,
        "source_text": rule.source_text,
        # The group this criterion HEADS, if any.
        "group_id": gid,
        "group_type": rule.group_type if is_group else None,
        # The group this criterion BELONGS TO, if any. Both are set at once only
        # for a nested group -- a member that is itself a group.
        "member_of": parent_id,
        "member_of_type": parent_type,
    }]
    for sc in rule.sub_criteria:
        out.extend(walk_rule(sc, section, parent_id=gid, parent_type=rule.group_type))
    return out


def role_of(record: dict) -> str:
    """How this record sits in the group structure, for display only."""
    if record["group_id"] and record["member_of"]:
        return "nested-group"
    if record["group_id"]:
        return "group-label"
    if record["member_of"]:
        return "member"
    return "flat"


# --------------------------------------------------------------------------
# placebo
# --------------------------------------------------------------------------

def make_placebo(system_prompt: str, index: int) -> tuple[str, str]:
    """Baseline prompt with a semantically null perturbation applied.

    A trailing space on a markdown heading: it changes the bytes the cache key
    hashes and changes nothing a reader of the prompt could act on. This is the
    established form -- it is the perturbation that churned 17 rows on PLATO
    while saying nothing.

    :returns: (perturbed prompt, human-readable description of what was done)
    """
    lines = system_prompt.split("\n")
    headings = [i for i, ln in enumerate(lines) if ln.startswith("## ")]
    if not headings:
        raise SystemExit(
            "the baseline system prompt has no '## ' heading to perturb, so no "
            "null placebo can be built. Refusing to run: without a placebo arm "
            "this harness cannot tell an effect from cache-key churn."
        )
    if index >= len(headings):
        raise SystemExit(
            f"--placebo-heading-index {index} but the prompt has only "
            f"{len(headings)} '## ' headings (0-{len(headings) - 1})."
        )
    ln = headings[index]
    lines[ln] = lines[ln] + " "
    return "\n".join(lines), f"trailing space appended to line {ln + 1}: {lines[ln].strip()!r}"


# --------------------------------------------------------------------------
# running one arm
# --------------------------------------------------------------------------

class _Tee(io.TextIOBase):
    """Records everything written while still letting the run be watched."""

    def __init__(self, passthrough):
        self.buf: list[str] = []
        self.passthrough = passthrough

    def write(self, s):  # noqa: D102
        self.buf.append(s)
        if self.passthrough:
            self.passthrough.write(s)
            self.passthrough.flush()
        return len(s)

    def text(self) -> str:
        return "".join(self.buf)


def run_arm(nct_id: str, system_prompt: str, arm: str, *, verify_thresholds: bool,
            quiet: bool) -> dict:
    """Run Agent 1 once with *system_prompt* as NCT_SYSTEM_PROMPT.

    The live module is restored afterwards, and the candidate text came from a
    file, so a run never leaves an edited prompt on disk.
    """
    import contextlib
    import src.agents.agent1.parser as parser_mod
    from src.agents.agent1.parser import LogicDecomposer

    saved_prompt = parser_mod.NCT_SYSTEM_PROMPT
    saved_key = LogicDecomposer.__dict__["_ir_cache_key"].__func__
    captured: dict = {}

    def key_wrapper(model_key, sys_prompt, prompt):
        h = saved_key(model_key, sys_prompt, prompt)
        captured.update(model_key=model_key, human_prompt=prompt, ir_hash=h)
        return h

    tee = _Tee(None if quiet else sys.__stdout__)
    try:
        parser_mod.NCT_SYSTEM_PROMPT = system_prompt
        LogicDecomposer._ir_cache_key = staticmethod(key_wrapper)
        print(f"\n===== ARM {arm}: running Agent 1 on {nct_id} =====", file=sys.__stdout__)
        with contextlib.redirect_stdout(tee):
            dec = LogicDecomposer()
            ir = dec.parse_nct(nct_id, verify_thresholds=verify_thresholds)
    finally:
        parser_mod.NCT_SYSTEM_PROMPT = saved_prompt
        LogicDecomposer._ir_cache_key = staticmethod(saved_key)

    log = tee.text()
    if "ir_hash" not in captured:
        raise SystemExit(
            f"arm {arm}: the IR cache key was never computed, so the human prompt "
            f"could not be captured and cross-arm input identity cannot be "
            f"checked. Refusing to report."
        )

    def rules(section: str, cohort) -> list[dict]:
        out = []
        for kind in ("inclusion_rules", "exclusion_rules"):
            for r in getattr(cohort, kind):
                out.extend(walk_rule(r, f"{section}.{kind.split('_')[0]}"))
        return out

    return {
        "arm": arm,
        "ir_hash": captured["ir_hash"],
        "model_key": captured["model_key"],
        "human_prompt": captured["human_prompt"],
        "system_prompt_len": len(system_prompt),
        "cache_hit": "Cache HIT" in log,
        "llm_called": "calling LLM" in log,
        "rules": rules("target", ir.target) + rules("comparator", ir.comparator),
    }


# --------------------------------------------------------------------------
# per-row matching
# --------------------------------------------------------------------------

_MIN_OVERLAP = 20


def match_rows(rules: list[dict], match_text: str, *, include_comparator: bool) -> list[dict]:
    """Rules whose ``source_text`` names the same protocol line as *match_text*.

    Containment either direction, because the model sometimes copies a prefix of
    a long line -- guarded by a minimum length so a short shared fragment cannot
    match an unrelated row. Matching is on ``source_text`` alone: ``name`` is a
    phrase written for a human and two unrelated rows routinely share one.
    """
    want = norm(match_text)
    hits = []
    for r in rules:
        if not include_comparator and r["section"].startswith("comparator"):
            continue
        got = norm(r["source_text"])
        if not got:
            continue
        shorter = min(len(want), len(got))
        if shorter < _MIN_OVERLAP:
            continue
        if want in got or got in want:
            hits.append(r)
    return hits


_STATE_FIELDS = ("section", "name", "domain", "entity_text",
                 "group_id", "group_type", "member_of", "member_of_type")


def row_state(hits: list[dict]) -> list[tuple]:
    """The comparable state of a row: absent (empty) or its emitted substance.

    Includes ``entity_text`` and ``domain`` so a row that survives in name but
    changes in substance registers as a difference rather than as stability, and
    the four group fields so a row that survives in substance but changes in the
    LOGIC connecting it to its neighbours registers as one too. An ANY->ALL flip
    changes no name, no domain and no entity_text; without the group fields it
    read as stability, which is the one answer that would be wrong.
    """
    return sorted(
        tuple(cell(h[f]) for f in _STATE_FIELDS) for h in hits
    )


def decide(moved_candidate: bool, moved_placebo: bool, blocked: bool) -> str:
    """The verdict rule, in one place so it can be exercised without an LLM call.

    An edit is credited with an effect on a row ONLY when the row moved under the
    candidate and did NOT move under a semantically null edit. Anything else is
    either no change at all, or a change a null edit reproduces -- which is not
    evidence about the edit.
    """
    if blocked:
        return "NO VERDICT"
    if not moved_candidate:
        return "NO EFFECT"
    if moved_placebo:
        return "INDISTINGUISHABLE FROM CACHE-KEY CHURN"
    return "EFFECT"


def top_level(rules: list[dict]) -> list[dict]:
    """Only the rules Agent 1 emitted at the top level, not their members."""
    return [r for r in rules if r["member_of"] is None]


def churn(a: list[dict], b: list[dict]) -> tuple[int, int]:
    sa = {norm(r["source_text"]) for r in a if r["section"].startswith("target")}
    sb = {norm(r["source_text"]) for r in b if r["section"].startswith("target")}
    return len(sa - sb), len(sb - sa)


# --------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------

def fmt_state(hits: list[dict]) -> list[str]:
    if not hits:
        return ["            (absent)"]
    out = []
    for h in hits:
        line = (f"            [{h['section']}] ({role_of(h)}) name={h['name']!r}\n"
                f"                 domain={h['domain']} entity_text={h['entity_text']!r}")
        if h["group_id"]:
            line += f"\n                 heads group {h['group_id']} group_type={h['group_type']}"
        if h["member_of"]:
            line += (f"\n                 member of group {h['member_of']} "
                     f"(group_type={h['member_of_type']})")
        out.append(line)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Per-row A/B/placebo harness for one Agent 1 prompt edit.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--nct", required=True, help="NCT id, e.g. NCT01243424")
    ap.add_argument("--target-row", action="append", metavar="'LABEL :: TEXT'",
                    help="a row to test, named BEFORE the run. Repeatable.")
    ap.add_argument("--targets-file", metavar="PATH",
                    help="file of target rows, one 'LABEL :: TEXT' per line")
    ap.add_argument("--candidate-prompt", metavar="PATH",
                    help="file holding the edited NCT_SYSTEM_PROMPT. Required "
                         "unless --dump-baseline-prompt.")
    ap.add_argument("--dump-baseline-prompt", metavar="PATH",
                    help="write the on-disk NCT_SYSTEM_PROMPT here and exit, so "
                         "the candidate is edited as a copy")
    ap.add_argument("--placebo-heading-index", type=int, default=0,
                    help="which '## ' heading the null perturbation lands on "
                         "(default 0). Use a different index from the one the "
                         "candidate file perturbs.")
    ap.add_argument("--include-comparator", action="store_true",
                    help="also match rows in the comparator cohort (off by "
                         "default: the comparator mirrors target inclusion rules)")
    ap.add_argument("--verify-thresholds", action="store_true",
                    help="run Agent 1 Step 7/8 (extra LLM calls). Off by "
                         "default: those steps reattach value constraints and "
                         "cannot add or remove a row.")
    ap.add_argument("--json", metavar="PATH", help="also write the full result here")
    ap.add_argument("--quiet", action="store_true", help="suppress Agent 1 progress output")
    args = ap.parse_args()

    from src.agents.agent1.prompts import NCT_SYSTEM_PROMPT as BASELINE

    if args.dump_baseline_prompt:
        Path(args.dump_baseline_prompt).write_text(BASELINE, encoding="utf-8")
        print(f"baseline NCT_SYSTEM_PROMPT ({len(BASELINE)} chars) -> "
              f"{args.dump_baseline_prompt}")
        print("Edit that copy, then pass it as --candidate-prompt.")
        return 0

    if not args.candidate_prompt:
        ap.error("--candidate-prompt is required (or use --dump-baseline-prompt)")

    targets = load_targets(args)
    candidate = Path(args.candidate_prompt).read_text(encoding="utf-8")
    placebo, placebo_desc = make_placebo(BASELINE, args.placebo_heading_index)

    # Refusals. Each is a case where the three arms cannot answer the question.
    if candidate == BASELINE:
        raise SystemExit(
            "the candidate prompt is byte-identical to the baseline: there is no "
            "edit to test, and both arms would share one cache key. Refusing."
        )
    if candidate == placebo:
        raise SystemExit(
            "the candidate prompt is byte-identical to the placebo arm, so the "
            "two collide on one cache key and the control is not independent. "
            "Perturb a different heading (--placebo-heading-index) or change the "
            "candidate. Refusing."
        )
    if placebo == BASELINE:
        raise SystemExit("the placebo perturbation changed nothing. Refusing.")

    arms = {}
    for name, prompt in (("baseline", BASELINE), ("candidate", candidate), ("placebo", placebo)):
        arms[name] = run_arm(args.nct, prompt, name,
                             verify_thresholds=args.verify_thresholds, quiet=args.quiet)

    # Input-identity gate. A prompt edit is only testable if Agent 1's INPUT was
    # held fixed; four studies in the 09-11 run received byte-identical input and
    # still churned, which is precisely the confound the placebo controls for --
    # but only when the input really was identical.
    hp = {k: v["human_prompt"] for k, v in arms.items()}
    input_identical = hp["baseline"] == hp["candidate"] == hp["placebo"]

    hashes = {k: v["ir_hash"] for k, v in arms.items()}
    distinct_keys = len(set(hashes.values())) == 3

    out = {
        "nct": args.nct,
        "model_key": arms["baseline"]["model_key"],
        "placebo_perturbation": placebo_desc,
        "input_identical_across_arms": input_identical,
        "distinct_cache_keys": distinct_keys,
        "arms": {k: {kk: vv for kk, vv in v.items() if kk not in ("human_prompt", "rules")}
                 for k, v in arms.items()},
        "rows": [],
        "churn_context_only": {},
    }

    print("\n" + "=" * 78)
    print(f"PROMPT A/B  --  {args.nct}  --  model {arms['baseline']['model_key']}")
    print("=" * 78)
    print(f"placebo perturbation : {placebo_desc}")
    for k in ("baseline", "candidate", "placebo"):
        a = arms[k]
        src = "cache HIT" if a["cache_hit"] else ("fresh LLM call" if a["llm_called"] else "unknown")
        print(f"  {k:<10} ir_hash={a['ir_hash']}  system_prompt={a['system_prompt_len']} chars  ({src})")
    print(f"Agent 1 input byte-identical across arms : {input_identical}")
    print(f"three distinct cache keys                : {distinct_keys}")

    # A replayed baseline and a freshly sampled arm were drawn at different
    # times, so a difference between them carries sampling drift as well as the
    # edit. The placebo arm is ALSO a fresh call, so differs(baseline, placebo)
    # absorbs that drift and the verdict rule still holds -- but the caveat is
    # printed rather than left implicit, because a silent confound is the shape
    # this harness exists to refuse.
    replay_mix = arms["baseline"]["cache_hit"] and any(
        arms[k]["llm_called"] for k in ("candidate", "placebo"))
    out["baseline_replayed_against_fresh_arms"] = replay_mix
    if replay_mix:
        print("CAVEAT: the baseline arm REPLAYED a cached IR while at least one other")
        print("  arm was sampled fresh. The placebo arm is fresh too, so it absorbs")
        print("  that drift; but a row moving in candidate AND placebo may be drift")
        print("  rather than the edit, which is why such a row reads as")
        print("  INDISTINGUISHABLE rather than as an effect.")

    blocked = []
    if not input_identical:
        blocked.append(
            "Agent 1's INPUT (the built human prompt) was NOT byte-identical "
            "across the three arms, so a row difference cannot be attributed to "
            "the system-prompt edit."
        )
    if not distinct_keys:
        blocked.append(
            "the three arms did not resolve to three distinct cache keys, so at "
            "least two arms replayed one cached answer."
        )

    print("\n" + "-" * 78)
    print("PER-ROW RESULT   (each row stands alone -- nothing here is averaged)")
    print("-" * 78)
    for label, match in targets:
        hits = {k: match_rows(arms[k]["rules"], match,
                              include_comparator=args.include_comparator)
                for k in arms}
        states = {k: row_state(v) for k, v in hits.items()}
        moved_cand = states["baseline"] != states["candidate"]
        moved_plac = states["baseline"] != states["placebo"]

        verdict = decide(moved_cand, moved_plac, bool(blocked))

        print(f"\n  ROW: {label}")
        print(f"    match text : {match!r}")
        for k in ("baseline", "candidate", "placebo"):
            print(f"    {k:<10} : {'PRESENT (' + str(len(hits[k])) + ')' if hits[k] else 'ABSENT'}")
            for line in fmt_state(hits[k]):
                print(line)
        print(f"    baseline->candidate differs : {moved_cand}")
        print(f"    baseline->placebo   differs : {moved_plac}")
        print(f"    VERDICT : {verdict}")

        # A row absent everywhere including baseline is not a prompt question at
        # all, and saying so is the whole value of naming rows in advance.
        if not any(hits.values()):
            comp = match_rows(arms["baseline"]["rules"], match, include_comparator=True)
            note = ("absent in EVERY arm including baseline -- the cause is not "
                    "this prompt edit")
            if comp and not args.include_comparator:
                note += (f"; but {len(comp)} matching rule(s) exist in the "
                         f"comparator cohort (re-run with --include-comparator)")
            print(f"    NOTE : {note}")
            out.setdefault("_notes", []).append(f"{label}: {note}")

        out["rows"].append({
            "label": label, "match_text": match, "verdict": verdict,
            "baseline_differs_candidate": moved_cand,
            "baseline_differs_placebo": moved_plac,
            "arms": {k: hits[k] for k in hits},
        })

    print("\n" + "-" * 78)
    print("CHURN TOTALS  --  CONTEXT ONLY, NOT EVIDENCE")
    print("  A placebo edit churned MORE than a real one on PLATO (17/14 vs")
    print("  15/15). These numbers cannot support a claim about the edit.")
    print("-" * 78)
    for k in ("candidate", "placebo"):
        lost, gained = churn(arms["baseline"]["rules"], arms[k]["rules"])
        n_base = len([r for r in top_level(arms['baseline']['rules'])
                      if r['section'].startswith('target')])
        n_arm = len([r for r in top_level(arms[k]['rules'])
                     if r['section'].startswith('target')])
        g_base = len([r for r in arms['baseline']['rules']
                      if r['group_id'] and r['section'].startswith('target')])
        g_arm = len([r for r in arms[k]['rules']
                     if r['group_id'] and r['section'].startswith('target')])
        print(f"  baseline -> {k:<10} top-level target rules {n_base} -> {n_arm};  "
              f"lost {lost}, gained {gained};  groups {g_base} -> {g_arm}")
        out["churn_context_only"][k] = {"lost": lost, "gained": gained,
                                        "baseline_rows": n_base, "arm_rows": n_arm,
                                        "baseline_groups": g_base, "arm_groups": g_arm}

    print("\n" + "=" * 78)
    if blocked:
        print("NO VERDICT PRINTED. The run is not interpretable:")
        for b in blocked:
            print(f"  - {b}")
    else:
        print("Verdicts above are per row. Nothing was averaged, scored, or aggregated.")
        print("Scope: Agent 1 parse_nct output only -- before dedup, mapping, and")
        print("Circe export. A row present here and absent in the study store is a")
        print("downstream question this harness does not answer.")
    print("=" * 78)

    if args.json:
        Path(args.json).write_text(json.dumps(out, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
        print(f"\nfull result -> {args.json}")

    return 2 if blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
