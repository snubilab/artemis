#!/usr/bin/env python
"""The one sanctioned per-arm CIRCE export for hospital/site delivery.

Supersedes the three 2026-08-31 scratch scripts (``tmp/gen_carmelina_seeded.py``,
``tmp/gen_all_seeded_v2.py``, ``tmp/gen_flag0_only.py``), which each read
``TTE_STORE_PATH`` from the environment as a silent fallback. The
artemis-api container sets that variable to its own default store, so all
three exported from a stale store without warning — see
``docs/wiki/content/`` (site-gap incident) and ``AGENTS.md``.

This script:

1. Requires an explicit ``--store`` path and aborts via
   :func:`src.utils.store_resolution.resolve_store_path` if ``TTE_STORE_PATH``
   disagrees with it — no silent fallback, no override flag.
2. Pins drug-anchored entry via
   :func:`src.utils.delivery_mode.resolve_drug_anchored_entry` and prints the mode
   it resolved. For a delivery export a treatment arm entering on its own drug is
   not an option but the definition of a treatment arm, so the mode is not left to
   the caller's memory: it is set here, said out loud, and recorded in the
   manifest. On 2026-09-08 the same run without ``TTE_DRUG_ANCHORED_ENTRY`` in the
   environment produced six disease-anchored treatment arms and two arms that could
   not be built at all.
3. Records the nine further environment settings that change what a concept set
   CONTAINS -- refiner, KG expansion mode, includeDescendants policy, route forcing,
   embedding model, domain pre-check, footprint guard and its threshold, mapper
   worker cap -- under ``mapping_env`` in the manifest, each with whether the value
   came from the environment or from a default, and prints them before the run. See
   :mod:`src.utils.mapping_flags`.
4. Builds each requested study's per-arm CIRCE the same way the scratch
   scripts did: call ``TTEService._build_seeded_cohort_artifact_payload``
   with ``WebAPIClient.create_cohort_definition`` monkeypatched to capture
   ``(name, expression)`` instead of touching the live WebAPI.
5. Lints every emitted file with ``src.utils.circe_lint`` before approving
   the batch: a no-op exclusion rule, or an entry concept-set that does not
   match the store's own entry (see ``entry_matches_expected`` for the one
   sanctioned exception — a disease-anchored comparator), is a violation.
   A batch with any violation writes no ``manifest.json`` — an export with a
   violation is not deliverable, even though the individual per-arm files
   stay on disk for inspection.
6. Reads the drop records the generator writes into each payload
   (``_unmappedCriteria``, ``_skippedCriteria``, ``_generationCensus``) via
   ``verify_circe_delivery.criterion_accounting``, which owns the rule. Until this
   was added nothing in either script mentioned those keys, so an arm carrying
   unmapped protocol exclusions was written, linted clean and approved — see check
   (i) in ``scripts/verify_circe_delivery.py``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import subprocess
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Resolve the store path (and validate it against any ambient TTE_STORE_PATH)
# BEFORE importing anything from src.services — those modules read
# TTE_STORE_PATH-adjacent state at import/construction time, and the whole
# point of this script is that the explicit --store path wins or the run
# aborts, never a silent env fallback.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.utils.delivery_mode import (  # noqa: E402
    DeliveryModeConflictError,
    resolve_drug_anchored_entry,
)
from src.utils.mapping_flags import (  # noqa: E402
    mapping_flags_manifest,
    mapping_flags_summary,
)
from src.utils.store_resolution import StoreMismatchError, resolve_store_path  # noqa: E402


def _slugify(name: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in name.strip())
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-") or "study"


def _parse_slug_map(raw: str | None) -> dict[int, str]:
    if not raw:
        return {}
    mapping: dict[int, str] = {}
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        study_id_str, _, slug = part.partition("=")
        mapping[int(study_id_str.strip())] = slug.strip()
    return mapping


def _git_head(repo_dir: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_dir), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(
    *,
    store_path: Path,
    drug_anchored_source: str,
    manifest_studies: list[dict[str, Any]],
    manifest_files: list[dict[str, Any]],
    repo_dir: Path,
) -> dict[str, Any]:
    """Assemble ``manifest.json``: what was exported, and under which mode.

    Split out of :func:`main` so the recorded provenance can be asserted without
    running an export. The provenance is the point of the file -- a delivered batch
    whose mode cannot be recovered afterwards is what both this script's gates exist
    to prevent.

    :param store_path: the resolved store the export read from.
    :param drug_anchored_source: ``DeliveryMode.source`` -- whether the entry-anchor
        mode came from the environment or was set by this script.
    :param manifest_studies: per-study rows collected during the run.
    :param manifest_files: per-file rows collected during the run.
    :param repo_dir: repository root, for the recorded git HEAD.
    :returns: the manifest document, ready to serialise.
    """
    return {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "store_path": str(store_path),
        "store_sha256": _file_sha256(store_path),
        "store_mtime": datetime.fromtimestamp(
            store_path.stat().st_mtime, tz=timezone.utc
        ).isoformat(),
        "env_TTE_STORE_PATH": os.environ.get("TTE_STORE_PATH"),
        "TTE_DRUG_ANCHORED_ENTRY": os.environ.get("TTE_DRUG_ANCHORED_ENTRY"),
        "TTE_DRUG_ANCHORED_ENTRY_source": drug_anchored_source,
        # The other nine settings that change what a cohort CONTAINS. Until this was
        # added none of them was printed or recorded, so "which mode produced this
        # batch" had no answer after the fact -- the same gap TTE_DRUG_ANCHORED_ENTRY
        # left on 2026-09-08, and the reason that one is recorded on the line above.
        "mapping_env": mapping_flags_manifest(),
        "git_head": _git_head(repo_dir),
        "studies": manifest_studies,
        "files": manifest_files,
    }


def _collect_build_failures(generated: Any) -> dict[str, str]:
    """Map arm role -> recorded build error, from the generation diagnostics.

    The service reports a failed expression build as an item with
    ``status == "failed"`` and an ``error``. Reading it here is what makes an
    omitted arm legible after the fact instead of merely absent; the structure is
    walked rather than indexed so a diagnostics reshape degrades to "no detail"
    instead of masking the violation with a traceback.
    """
    found: dict[str, str] = {}

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("status") == "failed" and node.get("error"):
                role = str(node.get("role") or "")
                if role and role not in found:
                    found[role] = str(node["error"])
            for value in node.values():
                walk(value)
        elif isinstance(node, (list, tuple)):
            for value in node:
                walk(value)

    try:
        walk(json.loads(json.dumps(generated, default=str)))
    except Exception:
        return found
    return found


class _OwnRecordsOnly(logging.Filter):
    """Admit this project's own log records and nothing else.

    ``src.services.tte_service`` reports through the bare ``logging.*`` module functions,
    which land on the root logger, while the rest of ``src`` uses
    ``getLogger(__name__)``. Both are ours; every other logger name belongs to a library.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        return record.name == "root" or record.name.startswith("src.")


def _configure_logging() -> None:
    """Send this export's own INFO lines to stderr.

    Nothing configured logging here, so the root logger kept its default WARNING level
    and every ``logging.info`` this run makes was discarded. The one that matters is
    ``_build_emittable_expression``'s "Ended N washout rule(s) a day before index": a
    correction that rewrites what is delivered and, without this, reports it into
    nothing. Establishing whether it had fired meant diffing the emitted files against a
    previous export.

    The filter, not a level change, is what keeps library chatter out. Raising the root
    level is unavoidable — the records we want are emitted on the root logger — so the
    unwanted ones are dropped at the handler instead. No library logger's level is
    touched, so anything else configuring them still decides what they do.
    """
    root = logging.getLogger()
    if any(isinstance(f, _OwnRecordsOnly) for h in root.handlers for f in h.filters):
        return
    root.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    handler.addFilter(_OwnRecordsOnly())
    root.addHandler(handler)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", required=True, type=Path, help="Explicit studies.json path")
    parser.add_argument("--out", required=True, type=Path, help="Output directory")
    parser.add_argument(
        "--study-id",
        action="append",
        type=int,
        required=True,
        dest="study_ids",
        help="Study id to export (repeatable)",
    )
    parser.add_argument(
        "--slug-map",
        default=None,
        help='Optional "id=slug,id=slug" mapping for output file names',
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    _configure_logging()

    # Resolved before the store, and reported, because it decides what a cohort
    # MEANS while the store decides which data it is built from. Printing it is the
    # point: a mode that is set silently is the hazard this replaces.
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

    # Import service modules only after the store path is resolved and
    # TTE_STORE_PATH has been pinned to it by resolve_store_path(). The delivery
    # gate owns what counts as recorded criterion loss, so `criterion_accounting`
    # is imported from it rather than reimplemented here -- and it is imported in
    # this block, not at module scope, because it pulls in src.* and must stay
    # behind the store resolution for the same reason everything else here does.
    from scripts.verify_circe_delivery import criterion_accounting
    from src.pipeline.webapi_client import prune_unused_concept_sets
    from src.services.tte_service import TTEService
    from src.services.tte_store import TTEStore
    from src.utils.circe_lint import (
        contradictory_absence_rules,
        domain_mismatched_criteria,
        entry_concept_ids,
        entry_concept_set_name,
        entry_matches_expected,
        expected_arm_roles,
        missing_arm_roles,
        noop_exclusion_rules,
        rule_names,
    )

    # Reported here, and not beside mode.summary() above, because the mapping flags
    # must be read AFTER `.env` has reached os.environ. `src.settings` calls
    # load_dotenv() at import, and that import happens in the block above -- so read
    # any earlier and a value from `.env` reports as unset. Measured, not assumed:
    # `.env` carries EMBEDDING_MODEL=medcpt, which printed as "unset" from the earlier
    # position while the manifest, built at the end, correctly said "medcpt". A record
    # that contradicts the line printed next to it is worse than no record.
    print(mapping_flags_summary(), file=sys.stderr)

    slug_map = _parse_slug_map(args.slug_map)
    out_dir: Path = args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    service = TTEService(TTEStore(str(store_path)))

    violations: list[dict[str, Any]] = []
    manifest_files: list[dict[str, Any]] = []
    manifest_studies: list[dict[str, Any]] = []

    for study_id in args.study_ids:
        study = service.store.get_study(study_id)
        study_name = study.get("name") or f"TTE Study {study_id}"
        slug = slug_map.get(study_id) or _slugify(study_name)
        comparison_mode = study.get("comparisonMode") or ""

        store_structured = (study.get("eligibility") or {}).get("structuredExpression") or {}
        store_domain, store_concept_ids = entry_concept_ids(store_structured)
        study_arms = study.get("treatmentArms") or []
        comparator_arm_name = study_arms[1].get("name") if len(study_arms) > 1 else None

        captured: list[dict[str, Any]] = []

        def _capture(
            self: Any,
            name: str,
            expression: dict[str, Any],
            description: str = "Auto-generated by ARTEMIS pipeline",
            _bucket: list[dict[str, Any]] = captured,
        ) -> dict[str, Any]:
            pruned = prune_unused_concept_sets(expression)
            _bucket.append({"name": name, "expression": pruned})
            return {"id": -1, "name": name}

        from unittest.mock import patch

        with patch(
            "src.pipeline.webapi_client.WebAPIClient.create_cohort_definition",
            _capture,
        ):
            generated = service._build_seeded_cohort_artifact_payload(study_id, study)
        build_failures = _collect_build_failures(generated)

        treatment = next((c for c in captured if "Treatment -" in c["name"]), None)
        comparator = next((c for c in captured if "Comparator -" in c["name"]), None)

        produced_roles: set[str] = set()
        for role, item in (("treatment", treatment), ("comparator", comparator)):
            if not item:
                continue
            produced_roles.add(role)
            expression = deepcopy(item["expression"])
            file_path = out_dir / f"{slug}_{role}.circe.json"
            with file_path.open("w", encoding="utf-8") as fh:
                json.dump(expression, fh, indent=2)

            noops = noop_exclusion_rules(expression)
            file_domain, file_concept_ids = entry_concept_ids(expression)
            entry_ok = entry_matches_expected(
                file_domain,
                file_concept_ids,
                store_domain,
                store_concept_ids,
                is_comparator=(role == "comparator"),
                comparison_mode=comparison_mode,
                file_entry_name=entry_concept_set_name(expression),
                comparator_arm_name=comparator_arm_name,
            )

            if noops:
                violations.append(
                    {
                        "study_id": study_id,
                        "slug": slug,
                        "arm": role,
                        "reason": "noop_rules",
                        "detail": f"{len(noops)} no-op rule(s): {', '.join(noops)}",
                    }
                )
            contradictions = contradictory_absence_rules(expression)
            if contradictions:
                violations.append(
                    dict(
                        study_id=study_id,
                        slug=slug,
                        arm=role,
                        reason="contradictory_absence",
                        detail=(
                            "rule(s) exclude a concept set intersecting the entry set, "
                            "so the cohort is empty: " + ", ".join(contradictions)
                        ),
                    )
                )
            domain_mismatches = domain_mismatched_criteria(expression)
            if domain_mismatches:
                violations.append(
                    dict(
                        study_id=study_id,
                        slug=slug,
                        arm=role,
                        reason="criterion_domain_mismatch",
                        detail=(
                            "criteri(a) whose concept set shares no domain with the CDM "
                            "table they read, so they match nothing: "
                            + "; ".join(domain_mismatches)
                        ),
                    )
                )
            # The generator records every criterion it could not turn into a rule
            # (`_unmappedCriteria`, `_skippedCriteria`, `_generationCensus`) inside
            # the payload being written here. Nothing read them, so both ARISTOTLE
            # arms were exported and approved carrying two unmapped protocol
            # exclusions -- in `output/anchor_after/` and again in the 2026-09-08
            # delivery. A cohort missing an exclusion admits patients the trial
            # excluded, which is the same class of defect as a no-op rule.
            accounting_violations, _summary = criterion_accounting(expression)
            if accounting_violations:
                violations.append(
                    {
                        "study_id": study_id,
                        "slug": slug,
                        "arm": role,
                        "reason": "criterion_loss",
                        "detail": "; ".join(accounting_violations),
                    }
                )
            if not entry_ok:
                violations.append(
                    {
                        "study_id": study_id,
                        "slug": slug,
                        "arm": role,
                        "reason": "entry_mismatch",
                        "detail": (
                            f"file entry {file_domain} {sorted(file_concept_ids)} != "
                            f"store entry {store_domain} {sorted(store_concept_ids)}"
                        ),
                    }
                )

            manifest_files.append(
                {
                    "study_id": study_id,
                    "study_name": study_name,
                    "study_modified_date": study.get("modifiedDate"),
                    "arm": role,
                    "file": file_path.name,
                    "md5": _file_md5(file_path),
                    "rule_count": len(rule_names(expression)),
                    "noop_rule_count": len(noops),
                    "domain_mismatch_count": len(domain_mismatches),
                    "entry_domain": file_domain,
                    "entry_concept_ids": sorted(file_concept_ids),
                }
            )

        # An arm that produced no file is the same class of violation as a bad file:
        # the delivery is not what it claims to be. Before this check the exporter
        # happily wrote a manifest listing five files for three two-arm studies, and
        # the gate — which only ever reads files that exist — exited 0 on it.
        for role in missing_arm_roles(study, produced_roles):
            detail = (
                f"study declares arm {role!r} "
                f"({[a.get('name') for a in study_arms]}) but no cohort was produced"
            )
            recorded = build_failures.get(role)
            if recorded:
                detail += f"; build failed: {recorded}"
            violations.append(
                {
                    "study_id": study_id,
                    "slug": slug,
                    "arm": role,
                    "reason": "missing_arm",
                    "detail": detail,
                }
            )

        manifest_studies.append(
            {
                "study_id": study_id,
                "study_name": study_name,
                "slug": slug,
                "arm_names": [a.get("name") for a in study_arms],
                "expected_arms": expected_arm_roles(study),
                "produced_arms": sorted(produced_roles),
            }
        )

    if violations:
        print("EXPORT REJECTED — violations found (no manifest written):", file=sys.stderr)
        print(
            f"{'study_id':>8}  {'slug':<16}  {'arm':<10}  {'reason':<16}  detail",
            file=sys.stderr,
        )
        for violation in violations:
            print(
                f"{violation['study_id']:>8}  {violation['slug']:<16}  {violation['arm']:<10}  "
                f"{violation['reason']:<16}  {violation['detail']}",
                file=sys.stderr,
            )
        return 1

    repo_dir = Path(__file__).resolve().parents[1]
    manifest = build_manifest(
        store_path=store_path,
        drug_anchored_source=mode.source,
        manifest_studies=manifest_studies,
        manifest_files=manifest_files,
        repo_dir=repo_dir,
    )
    manifest_path = out_dir / "manifest.json"
    with manifest_path.open("w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)

    print(f"OK — {len(manifest_files)} file(s) exported, manifest written to {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
