#!/usr/bin/env python3
"""Materialise a *comparable* test arm from a git revision, and refuse to hand it
over until it is proved comparable.

WHY THIS EXISTS
---------------
Diffing the suite against a revision needs a second checkout to run the suite in.
`git archive <rev>` alone does not give you one: this suite reaches outside the
repository and outside git's index, so a bare archive runs a strict subset of the
tests and reports a confident, wrong diff. Six-plus attempts in one session each
rediscovered the same three traps independently:

  1. ``tests/test_tte_frontend_bindings.py`` resolves ``Path(__file__).parents[2]``
     -- the *parent of the repo root* -- to reach ``atlas-dev/``. An arm extracted
     to a flat directory has no such sibling, so those tests fail or vanish.
  2. ``output/`` is PARTIALLY tracked (13 files under ``output/circe_be/2026-08-03/``
     and ``output/conceptset_overlap/dashboard.html``). ``git archive`` therefore
     creates a real ``output/`` directory, and a wholesale ``ln -s`` silently
     does nothing -- ``os.symlink`` raises FileExistsError, or, worse, a shell
     ``ln -s`` quietly nests the link *inside* the existing directory. Fifteen
     corpus-gated tests then skip instead of running.
  3. ``.env``, ``data/``, ``chroma_db/``, ``tmp/``, ``artifacts/`` and ``.venv``
     are untracked and all carry tests.

THE GATE: COMPARE THE SKIP SET, NOT THE FAILURE COUNT
-----------------------------------------------------
The corpus tests gate with ``@pytest.mark.skipif(not BATCH.is_dir(), ...)``. Such a
test is still COLLECTED when its corpus is missing -- it merely turns into a skip.
So a collected-count check cannot see the damage, and a failure-count check sees it
only as noise. The one signal that moves is the SKIP SET.

This script therefore compares the *set* of ``(location, reason)`` skip pairs, not
the aggregate count. Comparing the set rather than the number is what lets the
failure name itself: the skip reason of a corpus-gated test is literally
``delivered batch not present: <path>``, so an under-running arm reports the exact
path it is missing instead of an unattributed "expected 10, got 25".

Paths inside skip reasons are normalised (arm root and working-tree root both
collapse to ``<ROOT>``) before comparison, or every reason would differ trivially.

WHY PYTHON RATHER THAN SHELL
----------------------------
Two parts of the job are genuinely awkward in shell and are where the earlier
hand-rolled attempts went wrong: the recursive merge-symlink of a partially
tracked directory (trap 2), and parsing/normalising pytest's skip report into a
comparable set. Both are a few clear lines in Python. The rest (git archive, tar,
symlinks) is equally easy either way, and ``scripts/`` is already Python.

USAGE
-----
    # build + verify against a fresh working-tree reference run
    scripts/make_baseline_arm.py --rev HEAD --dest /tmp/arm

    # reuse an already-captured reference run instead of re-running it
    scripts/make_baseline_arm.py --rev HEAD --dest /tmp/arm \
        --reference-log /tmp/worktree.log

    # build only, no suite runs (structural preflight still enforced)
    scripts/make_baseline_arm.py --rev HEAD --dest /tmp/arm --no-verify

    # prove the gate fires: deliberately omit a dependency
    scripts/make_baseline_arm.py --rev HEAD --dest /tmp/broken --omit output

Read-only with respect to the working tree: it runs `git archive` and creates
symlinks pointing INTO the working tree, and writes only under --dest.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path

#: Untracked top-level entries the suite reads. Everything else untracked at the
#: repo root is deliberately NOT wired: `.git` (a symlink would let a test mutate
#: real repository state) and the various caches.
DENY = {".git", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".ipynb_checkpoints"}

#: Partially tracked directories that must be merge-symlinked child by child rather
#: than linked wholesale (trap 2). This is an ALLOWLIST on purpose, and the choice
#: is load-bearing: merging every partially tracked directory would pull the working
#: tree's untracked `tests/` and `src/` files into an arm that is supposed to BE the
#: revision -- silently making the baseline contain the very changes being diffed.
#: The rule is: code comes from the revision, corpora come from the working tree.
#: `output/` holds only produced corpora that tests read, so it is the sole entry.
MERGE_PARTIALLY_TRACKED = {"output"}

SUMMARY_RE = re.compile(
    r"^(?:=+\s*)?(?:(\d+) failed)?(?:,? ?(\d+) passed)?(?:,? ?(\d+) skipped)?"
    r"(?:,? ?(\d+) xfailed)?(?:,? ?(\d+) errors?)?.*in [\d.]+s",
)
SKIPPED_RE = re.compile(r"^SKIPPED \[(\d+)\] (.+?): (.*)$")
FAILED_RE = re.compile(r"^FAILED (\S+)")


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, text=True, capture_output=True, **kw)


# --------------------------------------------------------------------------- build


def merge_symlink(src: Path, dst: Path, created: list[Path]) -> None:
    """Link every entry of `src` into `dst` that `dst` does not already provide.

    Where both sides are real directories, recurse instead of linking, so a
    directory that `git archive` materialised (because part of it is tracked)
    still gains its untracked siblings. This is the fix for trap 2.
    """
    for entry in sorted(src.iterdir()):
        target = dst / entry.name
        if not target.exists() and not target.is_symlink():
            target.symlink_to(entry)
            created.append(target)
        elif entry.is_dir() and target.is_dir() and not target.is_symlink():
            merge_symlink(entry, target, created)
        # else: a tracked file the archive already provided -- leave the archive's copy


def assert_dest_is_safe(repo: Path, dest: Path) -> None:
    """`build_arm` rmtree's --dest. Resolve exactly what that would delete first.

    rmtree unlinks symlinks rather than following them, so a wired arm is safe to
    remove -- but a mistyped --dest is not, and the arm wires symlinks straight into
    a 22GB data/ and the working tree itself. Refuse anything that is not plainly a
    scratch directory.
    """
    for bad, why in (
        (dest == repo, "is the repository itself"),
        (repo.is_relative_to(dest), "contains the repository"),
        (dest.is_relative_to(repo), "is inside the repository"),
        (dest == repo.parent, "is the repository's parent"),
        (dest == Path(dest.anchor), "is a filesystem root"),
        (dest.is_symlink(), "is a symlink (rmtree would act on the link's target)"),
        ((dest / ".git").exists(), "contains a .git directory"),
    ):
        if bad:
            raise SystemExit(
                f"refusing to build in {dest}: it {why}.\n"
                f"--dest is deleted and recreated; point it at a scratch directory."
            )


def build_arm(repo: Path, rev: str, dest: Path, omit: set[str]) -> Path:
    """Extract `rev` into `dest/<repo-name>/` and wire every outside dependency."""
    assert_dest_is_safe(repo, dest)
    outer = repo.parent
    arm_root = dest / repo.name
    if dest.exists():
        shutil.rmtree(dest)
    arm_root.mkdir(parents=True)

    tar = dest / "_archive.tar"
    with tar.open("wb") as fh:
        subprocess.run(["git", "archive", rev], cwd=repo, check=True, stdout=fh)
    run(["tar", "-xf", str(tar), "-C", str(arm_root)])
    tar.unlink()

    wired: list[Path] = []
    skipped_by_request: list[str] = []
    unmerged: list[str] = []

    # (a) siblings of the repo root, reached by tests via parents[2] (trap 1)
    for sib in sorted(outer.iterdir()):
        if sib.name == repo.name or sib.name in DENY:
            continue
        if dest == sib or dest.is_relative_to(sib):
            continue
        if sib.name in omit:
            skipped_by_request.append(f"sibling:{sib.name}")
            continue
        link = dest / sib.name
        if not link.exists() and not link.is_symlink():
            link.symlink_to(sib)
            wired.append(link)

    # (b) untracked top-level entries inside the repo (traps 2 and 3)
    tracked_top = {
        line.split("/", 1)[0]
        for line in run(["git", "ls-tree", "--name-only", rev], cwd=repo).stdout.splitlines()
        if line
    }
    for entry in sorted(repo.iterdir()):
        if entry.name in DENY or dest.is_relative_to(entry):
            continue
        if entry.name in omit:
            skipped_by_request.append(entry.name)
            continue
        target = arm_root / entry.name
        if entry.name in tracked_top and target.exists():
            # Tracked at this revision. Only a named corpus directory is merged with
            # the working tree; every other tracked path stays exactly as `rev` has
            # it, so the arm is the revision and not a blend of it and the worktree.
            if entry.name in MERGE_PARTIALLY_TRACKED and entry.is_dir() and target.is_dir():
                merge_symlink(entry, target, wired)
            else:
                unmerged.append(entry.name)
            continue
        if not target.exists() and not target.is_symlink():
            target.symlink_to(entry)
            wired.append(target)

    if skipped_by_request:
        print(f"  !! deliberately omitted (--omit): {', '.join(sorted(skipped_by_request))}")

    # Advisory, not a gate: a tracked directory that is deliberately NOT merged but
    # does carry untracked working-tree content is where the next "the arm quietly
    # under-ran" surprise will come from. Name it now rather than discover it later.
    for name in sorted(unmerged):
        d = repo / name
        if not d.is_dir():
            continue
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard", "--", name],
            cwd=repo, text=True, capture_output=True,
        ).stdout.split()
        if untracked:
            print(f"  note: {name}/ has {len(untracked)} untracked file(s) NOT in the arm "
                  f"(by design -- code comes from the revision), e.g. {untracked[0]}")

    print(f"  wired {len(wired)} dependency links into {arm_root}")
    return arm_root


# ----------------------------------------------------------------------- preflight


def preflight(repo: Path, arm_root: Path) -> list[str]:
    """Structural checks that do not need a suite run. Returns a list of problems."""
    problems: list[str] = []

    for name in ("tests", "src", "scripts", "pyproject.toml"):
        if not (arm_root / name).exists():
            problems.append(f"archive is incomplete: {name} missing from the arm")

    # every dangling symlink is a dependency that will read as "absent" to a test
    for dirpath, dirnames, filenames in os.walk(arm_root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in DENY]
        for n in list(dirnames) + filenames:
            p = Path(dirpath) / n
            if p.is_symlink() and not p.exists():
                problems.append(f"dangling link: {p} -> {os.readlink(p)}")

    # trap 1: the sibling the frontend-binding tests reach through parents[2]
    for sib in ("atlas-dev",):
        if (repo.parent / sib).exists() and not (arm_root.parent / sib).exists():
            problems.append(f"sibling {sib!r} not reachable at parents[2] of the arm's tests")

    # trap 3: every top-level entry of the working tree must be reachable in the arm.
    # This validates an arm built by ANY means, not only by this script -- a hand-built
    # `git archive` tree fails here immediately instead of under-running quietly.
    # Note what this canNOT see: a directory that EXISTS in the arm but is missing its
    # untracked contents (trap 2, `output/`). Presence is not completeness, which is why
    # the skip-set comparison downstream is the real gate and not a redundant one.
    for entry in sorted(repo.iterdir()):
        if entry.name in DENY or arm_root == entry:
            continue
        if not (arm_root / entry.name).exists():
            problems.append(
                f"top-level dependency {entry.name!r} is absent from the arm "
                f"(tests that read it would skip or fail)"
            )

    # the silent-wrongness guard: prove `import src` resolves INSIDE the arm and
    # not back into the working tree (an editable install would do exactly that).
    py = arm_root / ".venv" / "bin" / "python"
    if py.exists():
        got = subprocess.run(
            [str(py), "-c", "import src, pathlib; print(pathlib.Path(src.__file__).resolve())"],
            cwd=arm_root, text=True, capture_output=True,
        )
        resolved = got.stdout.strip()
        if got.returncode != 0:
            problems.append(f"arm cannot import src: {got.stderr.strip().splitlines()[-1:]}")
        elif not resolved.startswith(str(arm_root.resolve())):
            problems.append(
                f"arm imports src from OUTSIDE the arm ({resolved}) -- the arm would "
                f"silently test working-tree code"
            )
    return problems


# -------------------------------------------------------------------------- verify


def pytest_run(python: Path, cwd: Path, log: Path, targets: list[str]) -> Path:
    print(f"  running {' '.join(targets)} in {cwd} -> {log}")
    with log.open("w") as fh:
        subprocess.run(
            # -rfs, NOT -rs: -rs reports only skips, so no "FAILED ..." line is ever
            # emitted and the failure comparison silently compares two empty sets.
            [str(python), "-m", "pytest", *targets, "-q", "-rfs", "-p", "no:cacheprovider"],
            cwd=cwd, stdout=fh, stderr=subprocess.STDOUT,
        )
    return log


def normalise(text: str, roots: list[Path], repo_name: str) -> str:
    """Collapse every checkout path to <ROOT> so two arms' reasons are comparable.

    The explicit roots handle the common case. The regex is the one that matters
    when a log was captured against a DIFFERENT arm directory than the one being
    verified now (`--arm-log`): the reason strings still carry the old arm's
    absolute path, and without this every reason would differ trivially and the
    gate would report spurious mismatches on a perfectly good arm.
    """
    for r in roots:
        text = text.replace(str(r.resolve()), "<ROOT>").replace(str(r), "<ROOT>")
    return re.sub(r"/[^\s:]*/" + re.escape(repo_name) + r"(?=/)", "<ROOT>", text)


def parse(log: Path, roots: list[Path], repo_name: str = "") -> dict:
    """Extract the skip set, the failed set, and the summary counts from a run log."""
    text = log.read_text(errors="replace")
    if repo_name:
        text = normalise(text, roots, repo_name)
        roots = []
    skips: Counter = Counter()
    failed: set[str] = set()
    counts = {}
    for line in text.splitlines():
        m = SKIPPED_RE.match(line.strip())
        if m:
            n, loc, reason = int(m.group(1)), m.group(2), m.group(3)
            for r in roots:
                reason = reason.replace(str(r.resolve()), "<ROOT>").replace(str(r), "<ROOT>")
                loc = loc.replace(str(r.resolve()), "<ROOT>").replace(str(r), "<ROOT>")
            skips[(loc, reason)] += n
            continue
        f = FAILED_RE.match(line.strip())
        if f:
            failed.add(f.group(1))
    for line in reversed(text.splitlines()):
        s = SUMMARY_RE.match(line.strip().strip("= "))
        if s and any(s.groups()):
            counts = {
                k: int(v or 0)
                for k, v in zip(("failed", "passed", "skipped", "xfailed", "errors"), s.groups())
            }
            break
    return {"skips": skips, "failed": failed, "counts": counts}


def compare(arm: dict, ref: dict) -> list[str]:
    """The gate. Returns a list of problems; empty means the arm is comparable."""
    problems = []
    a, r = arm["skips"], ref["skips"]
    extra = {k: a[k] - r.get(k, 0) for k in a if a[k] > r.get(k, 0)}
    missing = {k: r[k] - a.get(k, 0) for k in r if r[k] > a.get(k, 0)}

    for (loc, reason), n in sorted(extra.items()):
        problems.append(
            f"arm skips {n} test(s) the reference runs -- {loc}: {reason}\n"
            f"      -> this dependency is MISSING from the arm; the arm under-runs here"
        )
    for (loc, reason), n in sorted(missing.items()):
        problems.append(f"reference skips {n} test(s) the arm runs -- {loc}: {reason}")

    if arm["counts"].get("skipped") != ref["counts"].get("skipped"):
        problems.append(
            f"skip TOTAL differs: arm={arm['counts'].get('skipped')} "
            f"reference={ref['counts'].get('skipped')}"
        )
    if not arm["counts"] or not ref["counts"]:
        problems.append("could not parse a pytest summary line from one of the runs")

    # A comparison that was never actually made must not be reported as agreement.
    # pytest emits one "FAILED <nodeid>" line per failure only under -rf/-rfs/-rA; a
    # log captured with -rs alone yields an EMPTY failed set, and diffing two empty
    # sets prints "FAILED only in arm (0)" -- which reads exactly like a clean result.
    # This bit the author of this script: the first verified arm reported 0/0 while
    # both runs had 145 failures nobody had compared.
    for label, d in (("arm", arm), ("reference", ref)):
        declared = d["counts"].get("failed", 0)
        parsed = len(d["failed"])
        if declared and not parsed:
            problems.append(
                f"{label} run reports {declared} failures but NO 'FAILED <nodeid>' "
                f"lines were parsed -- the log was captured without -rf/-rfs/-rA, so "
                f"the failure comparison would be vacuous. Re-run with -rfs."
            )
        elif declared and parsed != declared:
            problems.append(
                f"{label} run reports {declared} failures but {parsed} FAILED lines "
                f"were parsed -- the failure list is incomplete; do not trust the diff."
            )
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--rev", default="HEAD", help="revision to materialise (default: HEAD)")
    ap.add_argument("--dest", required=True, help="directory to build the arm in (RECREATED)")
    ap.add_argument("--repo", default=None, help="repo root (default: git toplevel of cwd)")
    ap.add_argument("--arm-log", default=None,
                    help="an already-captured pytest log FOR THIS ARM, to verify without "
                         "re-running it (lets the two runs be done in parallel)")
    ap.add_argument("--reference-log", default=None,
                    help="an existing working-tree pytest log to compare against "
                         "(default: run the working-tree suite now)")
    ap.add_argument("--no-verify", action="store_true",
                    help="build + structural preflight only; skip the suite runs")
    ap.add_argument("--tests", action="append", default=None,
                    help="narrow both runs to these pytest targets (default: tests/). "
                         "Useful to exercise the gate quickly; the headline numbers "
                         "still need the whole suite.")
    ap.add_argument("--omit", action="append", default=[],
                    help="deliberately do not wire this dependency (to prove the gate fires)")
    args = ap.parse_args()

    repo = Path(args.repo).resolve() if args.repo else Path(
        run(["git", "rev-parse", "--show-toplevel"]).stdout.strip()).resolve()
    dest = Path(args.dest).resolve()
    sha = run(["git", "rev-parse", args.rev], cwd=repo).stdout.strip()

    print(f"repo {repo}")
    print(f"rev  {args.rev} -> {sha}")
    print(f"dest {dest}")

    arm_root = build_arm(repo, sha, dest, set(args.omit))
    (dest / "ARM_REV").write_text(f"{sha}\n{args.rev}\n")

    problems = preflight(repo, arm_root)
    if problems:
        print("\nPREFLIGHT FAILED -- the arm is not comparable:")
        for p in problems:
            print(f"  - {p}")
        return 2
    print("  preflight OK")

    if args.no_verify:
        print(f"\nARM BUILT (UNVERIFIED -- --no-verify was passed): {arm_root}")
        return 0

    py = arm_root / ".venv" / "bin" / "python"
    if not py.exists():
        print(f"\nFAILED: no interpreter at {py}")
        return 2

    targets = args.tests or ["tests/"]
    if args.arm_log:
        arm_log = Path(args.arm_log).resolve()
        print(f"  reusing arm log {arm_log}")
    else:
        arm_log = pytest_run(py, arm_root, dest / "arm_pytest.log", targets)
    if args.reference_log:
        ref_log = Path(args.reference_log).resolve()
        print(f"  reusing reference log {ref_log}")
    else:
        ref_log = pytest_run(repo / ".venv" / "bin" / "python", repo,
                             dest / "reference_pytest.log", targets)

    roots = [arm_root, repo]
    arm = parse(arm_log, roots, repo.name)
    ref = parse(ref_log, roots, repo.name)

    print("\n                 failed  passed  skipped")
    for label, d in (("arm      ", arm), ("reference", ref)):
        c = d["counts"]
        print(f"  {label}    {c.get('failed', '?'):>5}  {c.get('passed', '?'):>6}  "
              f"{c.get('skipped', '?'):>7}")

    problems = compare(arm, ref)
    if problems:
        print("\nARM REJECTED -- it is NOT comparable to the working tree:")
        for p in problems:
            print(f"  - {p}")
        print("\nA diff taken against this arm would be wrong. Fix the wiring and rebuild.")
        return 1

    only_arm = sorted(arm["failed"] - ref["failed"])
    only_ref = sorted(ref["failed"] - arm["failed"])
    print(f"\n  skip sets match ({sum(arm['skips'].values())} skips, "
          f"{len(arm['skips'])} distinct reasons) -- arm is comparable")
    print(f"  FAILED only in arm       ({len(only_arm)}):")
    for t in only_arm:
        print(f"      {t}")
    print(f"  FAILED only in reference ({len(only_ref)}):")
    for t in only_ref:
        print(f"      {t}")
    print(f"\nARM VERIFIED: {arm_root}")
    print(f"  arm log       {arm_log}")
    print(f"  reference log {ref_log}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
