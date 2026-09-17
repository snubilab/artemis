#!/usr/bin/env python3
"""Refuse a delivery whose entry event is excluded by one of its own inclusion rules.

A cohort can name the same concept in two places that contradict each other: the
entry event admits a patient on concept X, and an inclusion rule then requires
the ABSENCE of a concept set whose closure contains X. Every patient the entry
admits is thrown out by the rule, so the cohort returns zero people on ANY
database -- a correct CDM, a complete ETL and a perfect vocabulary change
nothing. The defect is visible in the definition file alone.

The measured instance is `deliveries/2026-09-12/empa-reg_comparator.circe.json`:

    entry event   ConditionOccurrence, codeset 2 'Type 2 diabetes mellitus',
                  concepts [201826, 44793113], includeDescendants
    rule #14      'Endocrine disorder (excluding T2DM)' requires codeset 29
                  'Endocrine disorder' at Occurrence {Type: 0, Count: 0}
    codeset 29    23 members, ZERO isExcluded, includes 201820 'Diabetes
                  mellitus' with includeDescendants -- and 201826 is a
                  descendant of 201820

Rule 14 returned 0 people (0.00% satisfied) at BOTH Ajou and Dong-A, while the
treatment arm of the same trial -- same file shape, same rule, but entering on a
DrugEra of empagliflozin instead of T2DM -- returned 874 and 786. The rule name
says what was intended ("excluding T2DM"); the concept set does not implement it.

Why the vocabulary is mandatory. 201826 never appears in codeset 29's member
list. It arrives through `concept_ancestor` under 201820. Comparing concept ids
or names as written would report this file clean, which is the entire failure
this gate exists to prevent -- so an unreachable vocabulary is a hard error here,
never a downgrade to a name-based comparison.

Three conditions must hold together before this is called a FAIL, and each one
is reported so a reader can disagree with it:

  1. the absence set covers the ENTIRE entry closure -- partial coverage is a
     silent population cut, reported as WARN with its percentage, not a defect;
  2. the criterion's window covers index day 0, so the entry event itself falls
     inside the window being required empty;
  3. every group between the rule root and the criterion is Type ALL, so no
     sibling branch can satisfy the rule instead.

Read-only. Never writes or fixes anything.

Usage:
    python3 scripts/verify_entry_exclusion_conflict.py <dir-or-file> [...]

Exit codes: 0 clean (WARNs allowed), 1 at least one FAIL, 2 could not run.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.services.conceptset_closure import (  # noqa: E402
    DEFAULT_VOCAB_SCHEMA,
    ConceptSetItem,
    VocabularyLookup,
    items_of_cohort,
    resolve_concept_set,
)

# The traversal below is shared verbatim with the export-time repair
# (`src.services.entry_exclusion_repair`), which keys on exactly the conditions
# this gate computes. Kept in one module so the gate and the repair cannot drift
# into disagreeing about what an unsatisfiable rule is.
from src.services.entry_exclusion_repair import (  # noqa: E402
    domain_of,
    entry_codeset_ids,
    iter_absence_criteria,
    window_covers_index,
)

#: Same home as `scripts/conceptset_overlap_eval.py` and
#: `scripts/audit_delivery_poison.py` -- one env var for the vocabulary DSN
#: across the repo rather than a third private one.
DEFAULT_DSN = os.environ.get(
    "ARTEMIS_VOCAB_DSN", "postgresql://postgres:mypass@localhost:5432/postgres"
)

#: How many overlapping concepts to name per finding.
SAMPLE = 5


@dataclass
class Finding:
    severity: str  # "FAIL" | "WARN"
    rule_number: int  # 1-based, as Atlas numbers inclusion rules
    rule_index: int  # 0-based index into InclusionRules
    rule_name: str
    domain: str
    codeset_id: int
    codeset_name: str
    n_entry: int
    n_overlap: int
    sample_ids: list[int]
    window: str
    covers_index: bool
    conjunctive: bool
    notes: list[str] = field(default_factory=list)

    @property
    def fraction(self) -> float:
        return self.n_overlap / self.n_entry if self.n_entry else 0.0


# --------------------------------------------------------------------------
# the check
# --------------------------------------------------------------------------

def check_cohort(cohort: dict, lookup: VocabularyLookup) -> tuple[list[Finding], list[str]]:
    """Findings plus any structural notes. ``lookup`` is the substitutable seam."""
    notes: list[str] = []
    by_id = {int(cs["id"]): cs for cs in cohort.get("ConceptSets") or [] if "id" in cs}

    entries = entry_codeset_ids(cohort)
    if not entries:
        return [], ["no PrimaryCriteria entry event with a CodesetId -- nothing to check"]

    entry_ids: set[int] = set()
    entry_labels: list[str] = []
    for domain, codeset in entries:
        cs = by_id.get(codeset)
        if cs is None:
            notes.append(f"entry event references missing codeset {codeset}")
            continue
        resolved = resolve_concept_set(cs, lookup).concept_ids
        entry_ids |= resolved
        entry_labels.append(
            f"{domain} codeset {codeset} {cs.get('name')!r} -> {len(resolved)} concepts"
        )
    notes.extend(entry_labels)
    if not entry_ids:
        return [], notes + ["entry event resolved to zero concepts -- nothing to check"]

    findings: list[Finding] = []
    for index, rule in enumerate(cohort.get("InclusionRules") or []):
        expression = rule.get("expression") or {}
        for criterion, conjunctive in iter_absence_criteria(expression):
            inner = criterion.get("Criteria") or {}
            found = domain_of(inner)
            if not found:
                continue
            domain, body = found
            codeset = body.get("CodesetId")
            if codeset is None:
                continue
            cs = by_id.get(int(codeset))
            if cs is None:
                notes.append(f"rule #{index + 1} references missing codeset {codeset}")
                continue
            absence_ids = resolve_concept_set(cs, lookup).concept_ids
            overlap = entry_ids & absence_ids
            if not overlap:
                continue

            covers, window = window_covers_index(criterion)
            full = overlap == entry_ids
            severity = "FAIL" if (full and covers and conjunctive) else "WARN"
            extra: list[str] = []
            if full and not covers:
                extra.append("full coverage, but the window excludes index day 0")
            if full and not conjunctive:
                extra.append("full coverage, but the criterion sits under a non-ALL group")

            findings.append(
                Finding(
                    severity=severity,
                    rule_number=index + 1,
                    rule_index=index,
                    rule_name=str(rule.get("name")),
                    domain=domain,
                    codeset_id=int(codeset),
                    codeset_name=str(cs.get("name")),
                    n_entry=len(entry_ids),
                    n_overlap=len(overlap),
                    sample_ids=sorted(overlap)[:SAMPLE],
                    window=window,
                    covers_index=covers,
                    conjunctive=conjunctive,
                    notes=extra,
                )
            )
    return findings, notes


# --------------------------------------------------------------------------
# reporting
# --------------------------------------------------------------------------

def _name_map(conn, schema: str, ids: list[int]) -> dict[int, str]:
    if not ids:
        return {}
    cur = conn.cursor()
    cur.execute(
        f"SELECT concept_id, concept_name FROM {schema}.concept WHERE concept_id = ANY(%s)",
        (sorted(set(ids)),),
    )
    out = {cid: name for cid, name in cur.fetchall()}
    cur.close()
    return out


def report(path: Path, findings: list[Finding], notes: list[str], names: dict[int, str]) -> None:
    fails = [f for f in findings if f.severity == "FAIL"]
    warns = [f for f in findings if f.severity == "WARN"]
    if fails:
        head = f"FAIL  {path.name}  ({len(fails)} unsatisfiable rule(s), {len(warns)} warning(s))"
    elif warns:
        head = f"WARN  {path.name}  ({len(warns)} partial overlap(s))"
    else:
        head = f"PASS  {path.name}"
    print(head)
    for note in notes:
        label = "entry" if "->" in note else "note"
        print(f"        {label}: {note}")
    for f in fails + warns:
        pct = 100.0 * f.fraction
        print(
            f"        {f.severity}  rule #{f.rule_number} {f.rule_name!r}"
            f"  absence on {f.domain} codeset {f.codeset_id} {f.codeset_name!r}"
        )
        print(
            f"               covers {f.n_overlap}/{f.n_entry} of the entry closure"
            f" ({pct:.1f}%)  window {f.window}"
            f"  covers_index={f.covers_index}  conjunctive={f.conjunctive}"
        )
        shown = ", ".join(f"{cid} {names.get(cid, '?')!r}" for cid in f.sample_ids)
        print(f"               overlapping e.g. {shown}")
        for note in f.notes:
            print(f"               note: {note}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("paths", nargs="*", help="directory or *.circe.json file(s)")
    parser.add_argument("--dsn", default=DEFAULT_DSN,
                        help="read-only vocabulary DSN (default: $ARTEMIS_VOCAB_DSN)")
    parser.add_argument("--vocab-schema", default=DEFAULT_VOCAB_SCHEMA)
    args = parser.parse_args(argv)

    if not args.paths:
        parser.print_help()
        return 2

    files: list[Path] = []
    for arg in args.paths:
        p = Path(arg)
        files.extend(sorted(p.glob("*.circe.json")) if p.is_dir() else [p])
    if not files:
        print("no *.circe.json found")
        return 2

    # The whole point of this gate is the ancestry hop (201826 under 201820) that
    # only the vocabulary knows. An unreachable database is fatal, never a
    # downgrade to comparing ids or names as written.
    try:
        from src.services.conceptset_closure import PostgresVocabulary

        vocab = PostgresVocabulary(args.dsn, args.vocab_schema)
    except Exception as exc:  # noqa: BLE001 -- re-raised as a named, loud failure
        print(
            f"CANNOT RUN: vocabulary unreachable at DSN {args.dsn!r} "
            f"(schema {args.vocab_schema}): {exc}\n"
            f"This check resolves concept ancestry through {args.vocab_schema}."
            f"concept_ancestor; without it the conflict it exists to catch is invisible. "
            f"Refusing to fall back to a name- or id-only comparison.",
            file=sys.stderr,
        )
        return 2

    bad = 0
    warned = 0
    with vocab:
        for f in files:
            cohort = json.loads(f.read_text())
            items: list[ConceptSetItem] = items_of_cohort(cohort)
            lookup = vocab.prefetch(items)
            findings, notes = check_cohort(cohort, lookup)
            sample = [cid for fnd in findings for cid in fnd.sample_ids]
            names = _name_map(vocab._conn, args.vocab_schema, sample)  # noqa: SLF001
            report(f, findings, notes, names)
            if any(x.severity == "FAIL" for x in findings):
                bad += 1
            elif findings:
                warned += 1

    print(
        f"\n{len(files) - bad - warned}/{len(files)} files clean, "
        f"{warned} with partial overlap, {bad} with an unsatisfiable rule"
    )
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
