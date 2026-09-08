#!/usr/bin/env python
"""Delivery gate for an existing per-arm CIRCE export directory.

Run this against a directory produced by ``export_seeded_cohorts.py`` (or any
other directory of ``*.circe.json`` files) before anything in it is sent to a
site. It never writes or fixes anything — it only checks and reports.

Checks per file:

(a) zero no-op exclusion rules (see ``src.utils.circe_lint.noop_exclusion_rules``)
(b) the file's InclusionRules names equal the store study's rule names as a
    multiset, allowing at most one extra rule (the appended arm drug rule)
(c) the file's PrimaryCriteria entry concept ids equal the store study's
    entry set, OR — for a comparator — the entry may legitimately be either
    a disease-anchored ``ConditionOccurrence`` set (the placebo-comparator
    design) or a ``DrugEra`` set naming the study's own second treatment arm
    (the active-comparator design, e.g. CAROLINA's comparator is legitimately
    "glimepiride", not linagliptin)
(d) if a ``manifest.json`` sits beside the files, its recorded md5s match the
    files on disk and its ``store_sha256`` matches the ``--store`` file
(h) a disease-anchored comparator entry is the trial's OWN registered condition.
    Check (c) accepts ANY ``ConditionOccurrence`` entry on a comparator, because the
    swap itself is legitimate -- so it passed LEADER's comparator entering on
    ``LV systolic or diastolic dysfunction`` (one of several alternative
    cardiovascular-risk qualifiers) instead of type 2 diabetes, which is a fraction of
    the trial population. The expected anchor comes from
    ``src.utils.disease_anchor.expected_anchor_concept_ids``, the same function the
    generator chooses with, against ``trialMetadata.conditions``. A study with no
    registered condition FAILS rather than passing unchecked -- backfill it with
    ``scripts/backfill_registered_conditions.py``.

(g) every criterion's concept set shares at least one OMOP domain with the CDM
    table that criterion reads. A ``ConditionOccurrence`` criterion over a Drug
    concept set joins ``condition_occurrence.condition_concept_id`` against drug
    products and matches nothing; as an ABSENCE rule that means everyone
    satisfies it and the exclusion is never applied. CAROLINA shipped that shape
    ("Glimepiride", codeset 56) and passed checks (a) to (f), because none of
    them reads a criterion's domain against its own concept set. Measured
    against WebAPI rather than reasoned — see
    ``src.utils.circe_lint.domain_mismatched_criteria`` and
    ``output/site_gap/2026-09-06/plan048_domain_repair/``.

And one check across files rather than per file:

(f) no rule requires zero occurrences of a concept set that intersects the
    cohort's own entry set. Such a rule empties the cohort by construction, and
    every other per-file check reads one property in isolation, so none of them
    can see it. CARMELINA shipped that shape and passed.

(e) every arm a mapped study declares in the store produced a file. Checks (a)
    to (d) all read a file that exists, so a delivery that is SHORT an arm
    passes all of them -- which is what happened on 2026-09-05, when a five-file
    export with a silently dropped EMPA-REG comparator exited 0. Only studies
    that produced at least one file are checked, so a deliberate single-study
    export still passes; the expected arm set comes from the store's own
    ``treatmentArms``, so a genuinely single-arm study needs no opt-out.

The 2026-08-31 delivery (``artemis/output/circe_be/2026-08-31/``) is the
counterexample this gate exists to catch — see ``AGENTS.md``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.utils.circe_lint import (  # noqa: E402
    contradictory_absence_rules,
    domain_mismatched_criteria,
    entry_concept_ids,
    entry_concept_set_name,
    entry_matches_expected,
    missing_arm_roles,
    noop_exclusion_rules,
    rule_names,
)
from src.utils.delivery_mode import (  # noqa: E402
    DeliveryModeConflictError,
    resolve_drug_anchored_entry,
)
from src.utils.disease_anchor import DiseaseAnchorError, expected_anchor_concept_ids
from src.utils.store_resolution import StoreMismatchError, resolve_store_path  # noqa: E402

DEFAULT_MAP = "carmelina=9,empa-reg=8,carolina=10,aristotle=3,plato=2,leader=1"


def _parse_map(raw: str) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        slug, _, study_id_str = part.partition("=")
        mapping[slug.strip()] = int(study_id_str.strip())
    return mapping


def _split_filename(path: Path) -> tuple[str, str] | None:
    """Return (slug, role) for '<slug>_treatment.circe.json' /
    '<slug>_comparator.circe.json', or None if the name doesn't match."""
    stem = path.name
    if stem.endswith(".circe.json"):
        stem = stem[: -len(".circe.json")]
    for role in ("treatment", "comparator"):
        suffix = f"_{role}"
        if stem.endswith(suffix):
            return stem[: -len(suffix)], role
    return None


def _file_md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rule_multiset_check(file_names: list[str], store_names: list[str]) -> tuple[bool, str]:
    file_counter = Counter(file_names)
    store_counter = Counter(store_names)
    missing = store_counter - file_counter
    extra = file_counter - store_counter
    missing_count = sum(missing.values())
    extra_count = sum(extra.values())
    if missing_count == 0 and extra_count <= 1:
        if extra_count == 0:
            detail = "matches store rule set"
        else:
            detail = f"matches + 1 extra ({next(iter(extra))!r})"
        return True, detail
    detail = f"missing={missing_count} extra={extra_count}"
    return False, detail


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", required=True, type=Path, help="Export directory to verify")
    parser.add_argument("--store", required=True, type=Path, help="Explicit studies.json path")
    parser.add_argument(
        "--map",
        default=DEFAULT_MAP,
        help='"slug=study_id,..." mapping from filename prefix to store study id',
    )
    parser.add_argument(
        "--allow-skeleton",
        action="store_true",
        help="Skip files with fewer than 2 InclusionRules instead of failing them",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    # The same resolver the exporter runs, for the same reason and in the same
    # order. Check (c) below expects a treatment arm's entry to equal the store's
    # own DrugEra entry, which is only what a drug-anchored export produces; a gate
    # resolving a different mode from the exporter compares against the wrong
    # expected entry, which is worse than no gate at all.
    try:
        mode = resolve_drug_anchored_entry()
    except DeliveryModeConflictError as exc:
        print(f"ABORT: {exc}", file=sys.stderr)
        return 2
    print(mode.summary(), file=sys.stderr)

    try:
        store_path = resolve_store_path(args.store)
    except (StoreMismatchError, FileNotFoundError) as exc:
        print(f"ABORT: {exc}", file=sys.stderr)
        return 2

    slug_to_id = _parse_map(args.map)

    with store_path.open(encoding="utf-8") as fh:
        store_payload = json.load(fh)
    studies = store_payload.get("studies") if isinstance(store_payload, dict) else store_payload
    studies_by_id = {int(s["id"]): s for s in studies}

    circe_files = sorted(args.dir.glob("*.circe.json"))
    if not circe_files:
        print(f"No *.circe.json files found under {args.dir}", file=sys.stderr)
        return 1

    manifest_path = args.dir / "manifest.json"
    manifest: dict[str, Any] | None = None
    if manifest_path.exists():
        with manifest_path.open(encoding="utf-8") as fh:
            manifest = json.load(fh)

    rows: list[dict[str, Any]] = []
    any_fail = False
    produced_roles_by_study: dict[int, set[str]] = {}

    for path in circe_files:
        parsed = _split_filename(path)
        if parsed is None:
            rows.append(
                {
                    "file": path.name,
                    "status": "FAIL",
                    "reasons": ["filename does not match '<slug>_treatment|comparator.circe.json'"],
                }
            )
            any_fail = True
            continue
        slug, role = parsed

        with path.open(encoding="utf-8") as fh:
            expression = json.load(fh)

        skeleton_study_id = slug_to_id.get(slug)
        if skeleton_study_id in studies_by_id:
            produced_roles_by_study.setdefault(skeleton_study_id, set()).add(role)

        rules = rule_names(expression)
        if len(rules) < 2 and args.allow_skeleton:
            rows.append(
                {
                    "file": path.name,
                    "status": "SKIPPED",
                    "reasons": [f"skeleton ({len(rules)} rule(s)) — allowed via --allow-skeleton"],
                }
            )
            continue

        study_id = slug_to_id.get(slug)
        if study_id is None or study_id not in studies_by_id:
            rows.append(
                {
                    "file": path.name,
                    "status": "FAIL",
                    "reasons": [f"no --map entry (or no store study) for slug {slug!r}"],
                }
            )
            any_fail = True
            continue
        study = studies_by_id[study_id]
        produced_roles_by_study.setdefault(study_id, set()).add(role)
        comparison_mode = study.get("comparisonMode") or ""
        store_structured = (study.get("eligibility") or {}).get("structuredExpression") or {}
        store_rule_names = rule_names(store_structured)
        store_domain, store_concept_ids = entry_concept_ids(store_structured)
        study_arms = study.get("treatmentArms") or []
        comparator_arm_name = study_arms[1].get("name") if len(study_arms) > 1 else None

        reasons: list[str] = []

        # (a) no-op exclusion rules
        noops = noop_exclusion_rules(expression)
        if noops:
            reasons.append(f"no-op rules ({len(noops)}): {', '.join(noops)}")

        # (b) rule-name multiset vs store, allowing one extra
        rules_ok, rules_detail = _rule_multiset_check(rules, store_rule_names)
        if not rules_ok:
            reasons.append(f"rule set mismatch: {rules_detail}")

        # (c) entry concept ids vs store, with the sanctioned comparator swaps
        file_domain, file_concept_ids = entry_concept_ids(expression)
        file_entry_name = entry_concept_set_name(expression)
        entry_ok = entry_matches_expected(
            file_domain,
            file_concept_ids,
            store_domain,
            store_concept_ids,
            is_comparator=(role == "comparator"),
            comparison_mode=comparison_mode,
            file_entry_name=file_entry_name,
            comparator_arm_name=comparator_arm_name,
        )
        if entry_ok:
            if (file_domain, file_concept_ids) == (store_domain, store_concept_ids):
                case = "exact match"
            elif file_domain == "ConditionOccurrence":
                case = "disease-anchored comparator swap (target_minus_treatment)"
            else:
                case = f"active-comparator drug entry ({file_entry_name!r} matches arm 2)"
        else:
            case = "FAIL"
            reasons.append(
                f"entry mismatch: file={file_domain} {sorted(file_concept_ids)} "
                f"store={store_domain} {sorted(store_concept_ids)}"
            )

        # (h) a disease-anchored comparator must enter on the trial's registered
        # condition, not on whichever Condition rule the file happens to carry.
        if entry_ok and file_domain == "ConditionOccurrence" and (
            (file_domain, file_concept_ids) != (store_domain, store_concept_ids)
        ):
            registered = (study.get("trialMetadata") or {}).get("conditions")
            try:
                expected_anchor = expected_anchor_concept_ids(store_structured, registered)
            except DiseaseAnchorError as exc:
                reasons.append(f"disease anchor unverifiable: {exc}")
            else:
                if file_concept_ids != expected_anchor:
                    reasons.append(
                        "disease anchor mismatch: file enters on "
                        f"{file_entry_name!r} {sorted(file_concept_ids)} but the trial's "
                        f"registered condition ({', '.join(repr(c) for c in registered or [])}) "
                        f"resolves to {sorted(expected_anchor)}"
                    )
                    case = "FAIL"

        # (f) a rule that excludes what the cohort enters on -- an empty cohort.
        contradictions = contradictory_absence_rules(expression)
        if contradictions:
            reasons.append(
                f"contradictory absence rules ({len(contradictions)}): "
                f"{', '.join(contradictions)}"
            )

        # (g) a criterion whose concept set shares no domain with the CDM table it
        # reads -- the join matches nothing, so an absence rule excludes nobody.
        domain_mismatches = domain_mismatched_criteria(expression)
        if domain_mismatches:
            reasons.append(
                f"criterion domain mismatch ({len(domain_mismatches)}): "
                f"{'; '.join(domain_mismatches)}"
            )

        # (d) manifest cross-check, if present
        if manifest is not None:
            manifest_entry = next(
                (f for f in manifest.get("files", []) if f.get("file") == path.name), None
            )
            if manifest_entry is None:
                reasons.append("manifest.json present but has no entry for this file")
            elif manifest_entry.get("md5") != _file_md5(path):
                reasons.append("manifest md5 does not match file on disk")
            manifest_store_sha = manifest.get("store_sha256")
            if manifest_store_sha is not None and manifest_store_sha != _file_sha256(store_path):
                reasons.append("manifest store_sha256 does not match --store file")

        status = "PASS" if not reasons else "FAIL"
        if status == "FAIL":
            any_fail = True
        rows.append(
            {
                "file": path.name,
                "status": status,
                "reasons": reasons or [f"entry: {case}; rules: {rules_detail}"],
            }
        )

    # (e) arm completeness, across files rather than per file.
    id_to_slug = {study_id: slug for slug, study_id in slug_to_id.items()}
    for study_id in sorted(produced_roles_by_study):
        study = studies_by_id[study_id]
        missing = missing_arm_roles(study, produced_roles_by_study[study_id])
        for role in missing:
            slug = id_to_slug.get(study_id, str(study_id))
            rows.append(
                {
                    "file": f"{slug}_{role}.circe.json",
                    "status": "MISSING",
                    "reasons": [
                        f"study {study_id} declares arm {role!r} "
                        f"({[a.get('name') for a in study.get('treatmentArms') or []]}) "
                        "but no file was produced for it"
                    ],
                }
            )
            any_fail = True

    print(f"{'file':<40}  {'status':<8}  reasons")
    for row in rows:
        print(f"{row['file']:<40}  {row['status']:<8}  {'; '.join(row['reasons'])}")

    return 1 if any_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
