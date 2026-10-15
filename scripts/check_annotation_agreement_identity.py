"""Are production's four annotation calls byte-identical to the prompts the over-fill A/B measured?

Since 2026-10-15 a row gets four calls: 1 and 2 are stage 2's `current` and `placebo`
(``overfill/ab_runs/stage2_*/plan.json``), 3 and 4 the re-check's `cf` and `pf`
(``overfill/ab_runs/cfpf_*/plan.json``, arms registered by ``overfill/prompts_record_change.py``).
One run of this script checks one plan: ``--arms`` names two of its arms and ``--calls`` which
production calls (0-based) send them -- ``--arms current,placebo --calls 0,1 --harness-module
prompts`` against stage 2's plan, ``--arms cf,pf --calls 2,3`` (the defaults) against the
re-check's. Production is recorded the same way in both: every row's call 1 and call 3 are
answered with a fill (no_entity and record_change, each with the row's own line as its
fragment), so every row makes all four calls. Before the four calls the script read:

Are production's two annotation prompts byte-identical to stage 2's `current` and `placebo`?

The over-fill A/B's stage 2 (``overfill/ab_runs/stage2_*/plan.json``) records, per arm, the system
prompt and the user template it sent, and the rows it sent them for. The harness rendered each row
with its own ``render`` over the measured ``src`` (``ab_harness.EXPECTED_SHA``), applying the run
directory's legacy-suffix strip to the rows it flags. The annotation step now makes its first call
with the `current` wording and, when that answer fills a field the agreement rule compares, a
second call with the `placebo` wording. This script renders the plan's rows twice, in two child
processes so the two ``src`` trees never share an interpreter:

* ``harness``: each plan row rendered with the harness's ``render`` over the measured ``src``,
  once with the plan's `current` (system, template) and once with its `placebo` (system,
  template) -- what stage 2 sent. It also confirms the plan's two arms are still what the
  harness's ``arm_prompts`` builds from the measured module, and that the harness renderer
  equals the measured ``render_prompt`` for the row.
* ``production``: this tree's ``annotate_eligibility`` -- the real call path, ``_complete``'s system
  and user messages included -- with the chat model replaced by a recorder (cache off, one worker,
  so the calls arrive in job order). The recorder answers every first call with a ``no_entity``
  fill whose fragment is the row's own line, so every row with a line gets its second call. Each
  store is prepared as the P3 driver prepares it: where ``--repair`` names a store, the run's own
  ``legacy_suffix.repair_store`` is applied to a scratch copy first.

It reports, per arm, how many plan rows render identical (system + user): production's first call
against `current`, production's second call against `placebo`. No model is called by either side;
no store, cache or run file is written (the repaired copy lives under ``--scratch``), and both
children run with ``-B`` and ``PYTHONDONTWRITEBYTECODE`` so nothing is compiled into the run dir.

usage:
  RUN=/home/bilab/work/projects/Broadsea/artemis/output/site_gap/2026-10-12_p3_dry
  P2=/home/bilab/work/projects/Broadsea/artemis/output/site_gap/2026-10-12_p2_new
  .venv/bin/python scripts/check_annotation_agreement_identity.py \\
      --harness-dir $RUN/overfill --plan $RUN/overfill/ab_runs/cfpf_<stamp>/plan.json \\
      --measured-src /home/bilab/work/projects/Broadsea/.worktrees/p3dry-smoke \\
      --rows $RUN/overfill/rows_smoke.jsonl $RUN/overfill/rows_a.jsonl \\
             $RUN/overfill/rows_b.jsonl $RUN/overfill/rows_p2new.jsonl \\
      --store smoke=$RUN/arm_smoke/store/studies.json --store a=$RUN/arm_a/store/studies.json \\
      --store b=$RUN/arm_b/store/studies.json \\
      --store p2new=$P2/store/studies.json --repair p2new --scratch /tmp/identity
"""

from __future__ import annotations

import argparse
import copy
import difflib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
ROLE_KEYS = {"inclusion": "inclusionCriteria", "exclusion": "exclusionCriteria"}
#: The studies ``dry_driver.py`` repairs on arm A (its ``STUDIES["a"]``).
REPAIR_STUDIES = (1, 2, 3, 8, 9, 10)
#: Plan arm -> which production call (0-based) sends it; set from ``--arms`` and ``--calls``.
ARM_CALL = {"cf": 2, "pf": 3}
#: Calls per row production makes when every fill is answered (see the docstring).
CALLS_PER_ROW = 4


def _arm_call(arms: str, calls: str) -> dict[str, int]:
    names = [a.strip() for a in arms.split(",")]
    numbers = [int(c) for c in calls.split(",")]
    if len(names) != 2 or len(numbers) != 2:
        raise SystemExit("--arms and --calls each take two comma-separated values")
    return dict(zip(names, numbers))


def _rows(paths: list[Path]) -> dict[tuple[str, str, str], dict[str, Any]]:
    out: dict[tuple[str, str, str], dict[str, Any]] = {}
    for path in paths:
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            spec = (row["trial"], row["role"], row["id"])
            if spec in out:
                raise SystemExit(f"{spec} appears twice in the --rows files")
            out[spec] = row
    return out


def _stores(pairs: list[str]) -> dict[str, Path]:
    return {tag: Path(path) for tag, _, path in (p.partition("=") for p in pairs)}


def _key(tag: str, study_id: Any, role: str, row_id: Any) -> str:
    return f"{tag}|{study_id}|{role}|{row_id}"


# --------------------------------------------------------------------------- #
# Children
# --------------------------------------------------------------------------- #


def harness_side(args: argparse.Namespace) -> dict[str, Any]:
    """Render every plan row with the harness's functions over the measured src."""
    sys.path[:0] = [str(args.harness_dir), str(args.harness_dir.parent)]
    import importlib  # noqa: PLC0415

    import ab_harness as harness  # noqa: PLC0415 -- imports src from PYTHONPATH
    from prompts import arm_prompts  # noqa: PLC0415

    importlib.import_module(args.harness_module)  # registers the plan's arms (cf / pf)

    measured = harness.A
    src_root = Path(measured.__file__).resolve().parents[2]
    head = subprocess.run(
        ["git", "-C", str(src_root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if src_root != args.measured_src.resolve() or head != harness.EXPECTED_SHA:
        raise SystemExit(
            f"harness side imported src from {src_root} at {head}, not "
            f"{args.measured_src} at {harness.EXPECTED_SHA}"
        )
    plan = json.loads(args.plan.read_text())
    if plan.get("sha") != harness.EXPECTED_SHA:
        raise SystemExit(f"plan sha {plan.get('sha')} is not the measured {harness.EXPECTED_SHA}")
    sent = {
        arm: (plan["prompts"][arm]["system"], plan["prompts"][arm]["user_template"])
        for arm in ARM_CALL
    }
    rebuilt = {
        arm: arm_prompts(arm, measured.ANNOTATION_SYSTEM_PROMPT, measured.ANNOTATION_PROMPT)
        for arm in ARM_CALL
    }
    rows = _rows(args.rows)
    stores = {tag: json.loads(path.read_text()) for tag, path in _stores(args.store).items()}
    out: dict[str, Any] = {
        "_meta": {
            "srcRoot": str(src_root),
            "head": head,
            "planArmsEqualHarnessArms": {a: sent[a] == rebuilt[a] for a in ARM_CALL},
            "planRows": len(plan["rows"]),
        }
    }
    for spec in plan["rows"]:
        r = rows[(spec["trial"], spec["role"], spec["id"])]
        study_id = harness.SLUG_TO_ID[r["trial"].split("@")[0]]
        study = next(s for s in stores[r["arm"]]["studies"] if s["id"] == study_id)
        role_rows = [x for x in study["eligibility"][ROLE_KEYS[r["role"]]] if isinstance(x, dict)]
        row = next(x for x in role_rows if str(x.get("id")) == r["id"])
        members = measured._members_of(row, role_rows)
        strip = None
        if r.get("strippedLegacySuffix"):
            from legacy_suffix import strip_all as strip  # noqa: PLC0415

            row = {**row, measured._LINE: strip(row[measured._LINE])}
        context = harness.context_lines(row, role_rows, strip)
        entry: dict[str, Any] = {
            arm: [system, harness.render(template, row, members, r["role"], context)]
            for arm, (system, template) in sent.items()
        }
        entry["rendererMatchesMeasured"] = harness.render(
            measured.ANNOTATION_PROMPT, row, members, r["role"]
        ) == measured.render_prompt(row, members, r["role"])
        entry["spec"] = f"{r['trial']}:{r['role']}:{r['id']}"
        out[_key(r["arm"], study_id, r["role"], r["id"])] = entry
    return out


class _Recorder:
    """The chat model, replaced: records each (system, user) pair. Calls 1 and 3 (both sent with
    ``first_system``) are answered with a ``no_entity`` and a ``record_change`` fill whose
    fragment is the row's own line, so calls 2 and 4 follow; those get an empty object. With one
    worker the calls arrive row by row, 1-2-3-4, so each row's line is used twice."""

    def __init__(self, first_system: str, lines: list[str]) -> None:
        self.first_system = first_system
        self.lines = [line for line in lines for _ in (1, 3)]
        self.calls: list[tuple[str, str]] = []
        self._next = 0

    def invoke(self, messages: list[Any]) -> Any:
        from langchain_core.messages import AIMessage  # noqa: PLC0415

        system, user = (str(m.content) for m in messages)
        self.calls.append((system, user))
        if system != self.first_system:
            return AIMessage(content="{}")
        line = self.lines[self._next]
        self._next += 1
        return AIMessage(
            content=json.dumps({
                "no_entity": "refers_elsewhere", "no_entity_span": line,
                "record_change": "stable", "record_change_span": line,
            })
        )


def production_side(args: argparse.Namespace) -> dict[str, Any]:
    """Render every needed study through this tree's annotate_eligibility, model recorded."""
    os.environ["ARTEMIS_ANNOTATION_CACHE"] = "0"
    os.environ["ARTEMIS_ANNOTATION_WORKERS"] = "1"
    from src.services import criterion_annotation as production  # noqa: PLC0415

    src_root = Path(production.__file__).resolve().parents[2]
    if src_root != REPO:
        raise SystemExit(f"production side imported src from {src_root}, not {REPO}")
    paths = _stores(args.store)
    stores: dict[str, Any] = {}
    repaired: dict[str, dict[str, int]] = {}
    for tag, path in paths.items():
        if tag in args.repair:
            sys.path.append(str(args.harness_dir.parent))
            import legacy_suffix  # noqa: PLC0415 -- the run's own repair, as dry_driver applies it

            args.scratch.mkdir(parents=True, exist_ok=True)
            copy_path = args.scratch / f"{tag}_studies.json"
            shutil.copyfile(path, copy_path)
            repaired[tag] = legacy_suffix.repair_store(
                copy_path, args.scratch / f"{tag}_repairs.tsv", REPAIR_STUDIES, write=True
            )
            path = copy_path
        stores[tag] = json.loads(path.read_text())
    plan = json.loads(args.plan.read_text())
    rows = _rows(args.rows)
    wanted = sorted(
        {
            (rows[(p["trial"], p["role"], p["id"])]["arm"], p["trial"].split("@")[0])
            for p in plan["rows"]
        }
    )
    slug_to_id = json.loads(args.slug_to_id)
    out: dict[str, Any] = {
        "_meta": {
            "srcRoot": str(src_root),
            "repaired": repaired,
            "promptVersion": production.ANNOTATION_PROMPT_VERSION,
            "agreementPromptVersion": production.AGREEMENT_PROMPT_VERSION,
            "recordChangePromptVersions": [
                production.RECORD_CHANGE_PROMPT_VERSION,
                production.RECORD_CHANGE_AGREEMENT_PROMPT_VERSION,
            ],
        }
    }
    for tag, slug in wanted:
        study = next(s for s in stores[tag]["studies"] if s["id"] == slug_to_id[slug])
        eligibility = copy.deepcopy(study["eligibility"])
        jobs = [
            (role, row)
            for role, key in production._ROLE_ROWS
            for row in eligibility.get(key) or []
            if isinstance(row, dict)
            and isinstance(row.get(production._LINE), str)
            and row[production._LINE].strip()
        ]
        recorder = _Recorder(
            production.ANNOTATION_SYSTEM_PROMPT, [row[production._LINE] for _role, row in jobs]
        )
        with patch.object(production, "_build_llm", lambda _model: recorder):
            production.annotate_eligibility(eligibility, model="stub-model")
        if len(recorder.calls) != CALLS_PER_ROW * len(jobs):
            raise SystemExit(
                f"{tag}/{slug}: {len(recorder.calls)} calls for {len(jobs)} rows; every row's "
                f"calls 1 and 3 are answered with a fill, so each needs {CALLS_PER_ROW}"
            )
        systems = (
            production.ANNOTATION_SYSTEM_PROMPT,
            production.AGREEMENT_SYSTEM_PROMPT,
            production.RECORD_CHANGE_SYSTEM_PROMPT,
            production.RECORD_CHANGE_AGREEMENT_SYSTEM_PROMPT,
        )
        for index, (role, row) in enumerate(jobs):
            calls = recorder.calls[CALLS_PER_ROW * index:CALLS_PER_ROW * (index + 1)]
            if not all(
                c[1].startswith(f"Protocol line:\n{row[production._LINE]}\n\n") for c in calls
            ):
                raise SystemExit(f"{tag}/{slug} {role} {row.get('id')}: calls out of job order")
            if tuple(c[0] for c in calls) != systems or calls[0][1] == calls[2][1]:
                raise SystemExit(
                    f"{tag}/{slug} {role} {row.get('id')}: the four calls are not the annotation "
                    "call, its agreement call, the record_change call and its agreement call"
                )
            out[_key(tag, study["id"], role, row.get("id"))] = [list(c) for c in calls]
    return out


# --------------------------------------------------------------------------- #
# Parent
# --------------------------------------------------------------------------- #


def _child(side: str, argv: list[str], pythonpath: Path, result: Path) -> dict[str, Any]:
    env = {**os.environ, "PYTHONPATH": str(pythonpath), "PYTHONDONTWRITEBYTECODE": "1"}
    cmd = [
        sys.executable,
        "-B",
        str(Path(__file__).resolve()),
        *argv,
        "--side",
        side,
        "--result",
        str(result),
    ]
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"{side} side failed ({proc.returncode}):\n{proc.stderr[-3000:]}")
    return json.loads(result.read_text())


def _tally(keys: list[str], harness: dict[str, Any], production: dict[str, Any]) -> dict[str, Any]:
    counts: dict[str, Any] = {
        "rows": len(keys),
        "missingInProduction": 0,
        "harnessRendererMatchesMeasured": 0,
    }
    for arm, call in ARM_CALL.items():
        other = next(a for a in ARM_CALL if a != arm)
        same = [k for k in keys if k in production and production[k][call] == harness[k][arm]]
        counts[arm] = {
            "identical": len(same),
            "different": sum(1 for k in keys if k in production) - len(same),
            "alsoIdenticalToOtherArm": sum(
                1 for k in keys if k in production and production[k][call] == harness[k][other]
            ),
        }
    for key in keys:
        counts["harnessRendererMatchesMeasured"] += harness[key]["rendererMatchesMeasured"]
        counts["missingInProduction"] += key not in production
    return counts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--harness-dir", required=True, type=Path)
    ap.add_argument("--plan", required=True, type=Path, help="the stage's plan.json")
    ap.add_argument("--measured-src", required=True, type=Path)
    ap.add_argument("--rows", nargs="+", required=True, type=Path)
    ap.add_argument("--store", action="append", required=True, help="TAG=path of that arm's store")
    ap.add_argument("--repair", action="append", default=[], help="store TAG the P3 driver repairs")
    ap.add_argument("--scratch", required=True, type=Path)
    ap.add_argument("--out", type=Path, help="write the counts and every differing key here")
    ap.add_argument("--arms", default="cf,pf", help="two of the plan's arms")
    ap.add_argument("--calls", default="2,3",
                    help="the production calls (0-based) that send those arms, in the same order")
    ap.add_argument("--harness-module", default="prompts_record_change",
                    help="module in --harness-dir that registers those arms")
    ap.add_argument("--side", choices=("harness", "production"), help=argparse.SUPPRESS)
    ap.add_argument("--result", type=Path, help=argparse.SUPPRESS)
    ap.add_argument("--slug-to-id", default="", help=argparse.SUPPRESS)
    raw = list(sys.argv[1:] if argv is None else argv)
    args = ap.parse_args(raw)
    ARM_CALL.clear()
    ARM_CALL.update(_arm_call(args.arms, args.calls))

    if args.side is not None:
        result = harness_side(args) if args.side == "harness" else production_side(args)
        args.result.write_text(json.dumps(result, ensure_ascii=False))
        return 0

    args.scratch.mkdir(parents=True, exist_ok=True)
    harness = _child("harness", raw, args.measured_src, args.scratch / "harness.json")
    slug_to_id = {
        slug: int(key.split("|")[1])
        for key, entry in harness.items()
        if key != "_meta"
        for slug in [entry["spec"].split(":")[0].split("@")[0]]
    }
    production = _child(
        "production",
        [*raw, "--slug-to-id", json.dumps(slug_to_id)],
        REPO,
        args.scratch / "production.json",
    )
    keys = [k for k in harness if k != "_meta"]
    meta = harness["_meta"]
    print(
        f"harness src {meta['srcRoot']} @ {meta['head']}; plan rows {meta['planRows']}; "
        f"plan arms equal the harness's arm_prompts over the measured module: "
        f"{meta['planArmsEqualHarnessArms']}"
    )
    print(
        f"production src {production['_meta']['srcRoot']} (prompt versions "
        f"{production['_meta']['promptVersion']} / "
        f"{production['_meta']['agreementPromptVersion']});"
        f" repaired stores {production['_meta']['repaired']}"
    )
    counts = _tally(keys, harness, production)
    print(json.dumps(counts))
    differing = {
        arm: [
            k for k in keys
            if (production.get(k) or [None] * CALLS_PER_ROW)[call] != harness[k][arm]
        ]
        for arm, call in ARM_CALL.items()
    }
    for arm, call in ARM_CALL.items():
        for key in differing[arm][:2]:
            p, h = (production.get(key) or [["", ""]] * CALLS_PER_ROW)[call], harness[key][arm]
            print(f"\nfirst difference ({arm}), {harness[key]['spec']} ({key}):")
            diff = difflib.unified_diff(
                "\n".join(h).splitlines(),
                "\n".join(p).splitlines(),
                f"harness {arm}",
                "production",
                n=1,
                lineterm="",
            )
            print("\n".join(list(diff)[:40]))
    if args.out is not None:
        args.out.write_text(json.dumps({"counts": counts, "differing": differing}, indent=1))
    ok = (
        all(meta["planArmsEqualHarnessArms"].values())
        and not any(differing.values())
        and counts["missingInProduction"] == 0
        and counts["rows"] == meta["planRows"]
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
