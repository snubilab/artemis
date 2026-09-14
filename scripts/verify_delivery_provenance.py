#!/usr/bin/env python3
"""Gate: every send recorded in deliveries/INDEX.json must be recoverable from git.

A delivery is a "send" only when the user said it was sent. This script never
decides that -- it reads the ledger and checks that each recorded send is still
recoverable. It never writes or fixes anything.

Four checks per recorded send:

  F1  every file named in the ledger exists under deliveries/<date>/
  F2  its bytes still hash to the md5 the ledger recorded
  F3  the file is TRACKED by git (an untracked file is not recoverable)
  T1  an annotated tag <tag> exists and contains all of those files at the
      recorded md5 -- this is the recovery point

Exit 0 = every recorded send is recoverable. Exit 1 = at least one is not,
and the reason names the send and the file.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "deliveries" / "INDEX.json"


def git(*args: str) -> tuple[int, str]:
    p = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True)
    return p.returncode, p.stdout.strip()


def main() -> int:
    if not LEDGER.exists():
        print(f"FAIL  ledger missing: {LEDGER.relative_to(ROOT)}")
        return 1

    ledger = json.loads(LEDGER.read_text())
    sends = [s for s in ledger.get("sends", []) if s.get("sent_confirmed_by_user")]
    if not sends:
        print("FAIL  ledger records no confirmed send -- a send is recorded only on the user's word")
        return 1

    failures: list[str] = []

    for s in sends:
        date, tag = s["date"], s["tag"]
        rel_dir = Path("deliveries") / date

        # T1a -- the recovery point must exist, and be an annotated tag
        rc, kind = git("cat-file", "-t", tag)
        if rc != 0:
            failures.append(f"{date}: no recovery point -- tag {tag!r} does not exist")
            tag_ok = False
        elif kind != "tag":
            failures.append(f"{date}: tag {tag!r} is {kind}, not an annotated tag")
            tag_ok = False
        else:
            tag_ok = True

        for f in s["files"]:
            rel = rel_dir / f["name"]
            p = ROOT / rel

            # F1
            if not p.exists():
                failures.append(f"{date}: {rel} is missing from the working tree")
                continue

            # F2
            got = hashlib.md5(p.read_bytes()).hexdigest()
            if got != f["md5"]:
                failures.append(
                    f"{date}: {rel} content changed -- ledger md5 {f['md5'][:8]}, on disk {got[:8]}"
                )

            # F3
            rc, out = git("ls-files", "--error-unmatch", str(rel))
            if rc != 0:
                failures.append(f"{date}: {rel} is not tracked by git, so it is not recoverable")

            # T1b -- the bytes must be reachable from the tag, not just from HEAD
            if tag_ok:
                rc, blob = git("show", f"{tag}:{rel.as_posix()}")
                if rc != 0:
                    failures.append(f"{date}: {rel} is not present at tag {tag}")
                else:
                    _, sha = git("rev-parse", f"{tag}:{rel.as_posix()}")
                    blob = subprocess.run(
                        ["git", "-C", str(ROOT), "cat-file", "blob", sha], capture_output=True
                    ).stdout
                    at_tag = hashlib.md5(blob).hexdigest()
                    if at_tag != f["md5"]:
                        failures.append(
                            f"{date}: {rel} at tag {tag} hashes {at_tag[:8]}, "
                            f"ledger says {f['md5'][:8]}"
                        )

    for s in sends:
        n = s["file_count"]
        print(f"  {s['date']}  {n:2d} files  tag={s['tag']}")

    if failures:
        print(f"\nFAIL  {len(failures)} problem(s):")
        for x in failures:
            print(f"  - {x}")
        return 1

    print(f"\nPASS  {len(sends)} recorded send(s), all recoverable from their tags")
    return 0


if __name__ == "__main__":
    sys.exit(main())
