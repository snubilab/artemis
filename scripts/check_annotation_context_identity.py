"""Does production render the annotation prompt byte-identical to the harness's `context` arm?

The harness (``output/site_gap/2026-10-12_p3_dry/overfill/ab_harness.py`` and ``prompts.py``)
builds its ``context`` arm by editing the measured module's prompt text (``src`` at the
harness's ``EXPECTED_SHA``) and renders each row with its own ``render`` and ``context_lines``,
applying the run directory's legacy-suffix strip to the rows it flags. This script renders the
same rows twice, in two child processes so the two ``src`` trees never share an interpreter:

* ``harness``: the harness's own functions over the measured ``src`` -- the ``context`` arm and
  the ``current`` arm (the prompt production used to send);
* ``production``: this tree's ``annotate_eligibility`` -- the real call path, ``_complete``'s
  system and user messages included -- with the chat model replaced by a recorder (cache off,
  one worker, so the calls arrive in job order), over each store as the P3 driver prepares it:
  where ``--repair`` names a store, the run's own ``legacy_suffix.repair_store`` is applied to a
  scratch copy first, as ``dry_driver.py`` does before any ``src`` import.

It reports, for every row of the ``--rows`` files and for the ``--only`` subset, how many rows
render identical (system + user) in production and in the harness ``context`` arm, and how
many production renders still equal the harness ``current`` arm. No model is called by either
side; no store, cache or run file is written (the repaired copy lives under ``--scratch``).

usage:
  RUN=/home/bilab/work/projects/Broadsea/artemis/output/site_gap/2026-10-12_p3_dry
  P2=/home/bilab/work/projects/Broadsea/artemis/output/site_gap/2026-10-12_p2_new
  .venv/bin/python scripts/check_annotation_context_identity.py \\
      --harness-dir $RUN/overfill \\
      --measured-src /home/bilab/work/projects/Broadsea/.worktrees/p3dry-smoke \\
      --rows $RUN/overfill/rows_smoke.jsonl $RUN/overfill/rows_a.jsonl \\
             $RUN/overfill/rows_p2new.jsonl \\
      --store smoke=$RUN/arm_smoke/store/studies.json --store a=$RUN/arm_a/store/studies.json \\
      --store p2new=$P2/store/studies.json --repair p2new \\
      --scratch /tmp/identity --only carmelina:inclusion:7,...
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


def _rows(paths: list[Path]) -> list[dict[str, Any]]:
    return [json.loads(line) for p in paths for line in p.read_text().splitlines() if line.strip()]


def _stores(pairs: list[str]) -> dict[str, Path]:
    return {tag: Path(path) for tag, _, path in (p.partition("=") for p in pairs)}


def _key(tag: str, study_id: Any, role: str, row_id: Any) -> str:
    return f"{tag}|{study_id}|{role}|{row_id}"


# --------------------------------------------------------------------------- #
# Children
# --------------------------------------------------------------------------- #


def harness_side(args: argparse.Namespace) -> dict[str, Any]:
    """Render every row with the harness's functions over the measured src."""
    sys.path[:0] = [str(args.harness_dir), str(args.harness_dir.parent)]
    import ab_harness as harness  # noqa: PLC0415 -- imports src from PYTHONPATH
    from prompts import arm_prompts  # noqa: PLC0415

    measured = harness.A
    src_root = Path(measured.__file__).resolve().parents[2]
    head = subprocess.run(["git", "-C", str(src_root), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()
    if src_root != args.measured_src.resolve() or head != harness.EXPECTED_SHA:
        raise SystemExit(f"harness side imported src from {src_root} at {head}, not "
                         f"{args.measured_src} at {harness.EXPECTED_SHA}")
    prompts = {arm: arm_prompts(arm, measured.ANNOTATION_SYSTEM_PROMPT, measured.ANNOTATION_PROMPT)
               for arm in ("current", "context")}
    stores = {tag: json.loads(path.read_text()) for tag, path in _stores(args.store).items()}
    out: dict[str, Any] = {"_meta": {"srcRoot": str(src_root), "head": head}}
    for r in _rows(args.rows):
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
        entry = {arm: [system, harness.render(template, row, members, r["role"], context)]
                 for arm, (system, template) in prompts.items()}
        entry["rendererMatchesMeasured"] = (
            harness.render(measured.ANNOTATION_PROMPT, row, members, r["role"])
            == measured.render_prompt(row, members, r["role"])
        )
        entry["spec"] = f"{r['trial']}:{r['role']}:{r['id']}"
        entry["contextLines"] = len(context)
        out[_key(r["arm"], study_id, r["role"], r["id"])] = entry
    return out


class _Recorder:
    """The chat model, replaced: records each (system, user) pair and answers one fixed object."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def invoke(self, messages: list[Any]) -> Any:
        from langchain_core.messages import AIMessage  # noqa: PLC0415

        system, user = (str(m.content) for m in messages)
        self.calls.append((system, user))
        return AIMessage(content='{"record_requirement": "required"}')


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
    wanted = sorted({(r["arm"], r["trial"].split("@")[0]) for r in _rows(args.rows)})
    slug_to_id = json.loads(args.slug_to_id)
    out: dict[str, Any] = {"_meta": {"srcRoot": str(src_root), "repaired": repaired,
                                     "promptVersion": production.ANNOTATION_PROMPT_VERSION}}
    for tag, slug in wanted:
        study = next(s for s in stores[tag]["studies"] if s["id"] == slug_to_id[slug])
        eligibility = copy.deepcopy(study["eligibility"])
        recorder = _Recorder()
        with patch.object(production, "_build_llm", lambda _model: recorder):
            production.annotate_eligibility(eligibility, model="stub-model")
        jobs = [(role, row) for role, key in production._ROLE_ROWS
                for row in eligibility.get(key) or []
                if isinstance(row, dict) and isinstance(row.get(production._LINE), str)
                and row[production._LINE].strip()]
        if len(jobs) != len(recorder.calls):
            raise SystemExit(f"{tag}/{slug}: {len(recorder.calls)} calls for {len(jobs)} rows")
        for (role, row), (system, user) in zip(jobs, recorder.calls):
            if not user.startswith(f"Protocol line:\n{row[production._LINE]}\n\n"):
                raise SystemExit(f"{tag}/{slug} {role} {row.get('id')}: calls out of job order")
            out[_key(tag, study["id"], role, row.get("id"))] = [system, user]
    return out


# --------------------------------------------------------------------------- #
# Parent
# --------------------------------------------------------------------------- #


def _child(side: str, argv: list[str], pythonpath: Path, result: Path) -> dict[str, Any]:
    env = {**os.environ, "PYTHONPATH": str(pythonpath), "PYTHONDONTWRITEBYTECODE": "1"}
    cmd = [sys.executable, "-B", str(Path(__file__).resolve()), *argv, "--side", side,
           "--result", str(result)]
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"{side} side failed ({proc.returncode}):\n{proc.stderr[-3000:]}")
    return json.loads(result.read_text())


def _tally(keys: list[str], harness: dict[str, Any], production: dict[str, Any]) -> dict[str, int]:
    counts = {"rows": len(keys), "missingInProduction": 0, "identicalToContext": 0,
              "differentFromContext": 0, "identicalToCurrent": 0, "systemIdenticalToContext": 0,
              "harnessRendererMatchesMeasured": 0}
    for key in keys:
        h, p = harness[key], production.get(key)
        counts["harnessRendererMatchesMeasured"] += h["rendererMatchesMeasured"]
        if p is None:
            counts["missingInProduction"] += 1
            continue
        same = p == h["context"]
        counts["identicalToContext" if same else "differentFromContext"] += 1
        counts["identicalToCurrent"] += p == h["current"]
        counts["systemIdenticalToContext"] += p[0] == h["context"][0]
    return counts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--harness-dir", required=True, type=Path)
    ap.add_argument("--measured-src", required=True, type=Path)
    ap.add_argument("--rows", nargs="+", required=True, type=Path)
    ap.add_argument("--store", action="append", required=True, help="TAG=path of that arm's store")
    ap.add_argument("--repair", action="append", default=[], help="store TAG the P3 driver repairs")
    ap.add_argument("--scratch", required=True, type=Path)
    ap.add_argument("--only", default="", help="trial:role:id,... reported as its own set")
    ap.add_argument("--out", type=Path, help="write the counts and every differing key here")
    ap.add_argument("--side", choices=("harness", "production"), help=argparse.SUPPRESS)
    ap.add_argument("--result", type=Path, help=argparse.SUPPRESS)
    ap.add_argument("--slug-to-id", default="", help=argparse.SUPPRESS)
    raw = list(sys.argv[1:] if argv is None else argv)
    args = ap.parse_args(raw)

    if args.side is not None:
        result = harness_side(args) if args.side == "harness" else production_side(args)
        args.result.write_text(json.dumps(result, ensure_ascii=False))
        return 0

    args.scratch.mkdir(parents=True, exist_ok=True)
    harness = _child("harness", raw, args.measured_src, args.scratch / "harness.json")
    slug_to_id = {slug: int(key.split("|")[1]) for key, entry in harness.items() if key != "_meta"
                  for slug in [entry["spec"].split(":")[0].split("@")[0]]}
    production = _child("production", [*raw, "--slug-to-id", json.dumps(slug_to_id)], REPO,
                        args.scratch / "production.json")
    keys = [k for k in harness if k != "_meta"]
    only = {s for s in args.only.split(",") if s}
    sets = {"all rows": keys,
            "--only": [k for k in keys if harness[k]["spec"] in only]}
    if only and len(sets["--only"]) != len(only):
        found = {harness[k]["spec"] for k in sets["--only"]}
        raise SystemExit(f"--only names rows the --rows files do not hold: {sorted(only - found)}")
    print(f"harness src {harness['_meta']['srcRoot']} @ {harness['_meta']['head']}")
    print(f"production src {production['_meta']['srcRoot']} "
          f"(prompt version {production['_meta']['promptVersion']}); "
          f"repaired stores {production['_meta']['repaired']}")
    report: dict[str, Any] = {}
    for name, subset in sets.items():
        counts = _tally(subset, harness, production)
        report[name] = counts
        print(f"{name}: {json.dumps(counts)}")
    differing = [k for k in keys if production.get(k) != harness[k]["context"]]
    for key in differing[:3]:
        p, h = production.get(key) or ["", ""], harness[key]["context"]
        print(f"\nfirst difference, {harness[key]['spec']} ({key}):")
        diff = difflib.unified_diff("\n".join(h).splitlines(), "\n".join(p).splitlines(),
                                    "harness context", "production", n=1, lineterm="")
        print("\n".join(list(diff)[:40]))
    if args.out is not None:
        args.out.write_text(json.dumps({"counts": report, "differing": differing}, indent=1))
    return 0 if not differing else 1


if __name__ == "__main__":
    raise SystemExit(main())
