"""Decompose why ``TTEService._alias_ingredient_mapping`` refuses.

Why this exists
---------------
The MeSH alias tier resolves a sponsor development code through the trial's MeSH
intervention terms, and it declines far more often than it accepts. A handoff read
that refusal rate as the tier's "exactly one alias may resolve" guard being too
strict, which invites loosening the guard -- the same guard whose absence put the
comparator's drug in the study drug's slot (PLATO, fixed in ``8692a55``).

The refusals are two different failures with two different fixes, and they have to be
counted apart before anything is changed:

* **nothing resolves** -- no MeSH term for the trial is a standard RxNorm Ingredient
  name. Loosening the ambiguity guard cannot help; the tier has no candidate at all.
* **more than one resolves** -- the trial indexed both arms. Only here does the guard
  bind, and only a signal that separates study drug from comparator would help.

The script also measures the population that *depends* on the tier: a trial where some
sponsor-authored field already spells the generic name never reaches it, because the
seed matches an ingredient directly one tier earlier. "Sponsor-silent" trials -- no
MeSH term appears in any arm label, intervention name, or otherName -- are the
'BI 10773' shape the tier was built for, and are the honest denominator.

Read-only: it queries the CDM and the local NCT cache and writes nothing.

Usage::

    .venv/bin/python scripts/analyze_alias_tier_refusals.py
    .venv/bin/python scripts/analyze_alias_tier_refusals.py --json out.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_CACHE_DIR = REPO_ROOT / "data" / "nct_cache"


def load_trials(cache_dir: Path) -> list[dict[str, Any]]:
    """Read every cached trial that carries at least one MeSH intervention term.

    :param cache_dir: Directory holding ``<NCT>.json`` registry payloads.
    :returns: One dict per trial with its MeSH terms and sponsor-authored drug names.
    """
    trials: list[dict[str, Any]] = []
    for path in sorted(cache_dir.glob("NCT*.json")):
        raw = json.loads(path.read_text())
        browse = (raw.get("derivedSection") or {}).get("interventionBrowseModule") or {}
        terms = [t for t in ((m.get("term") or "").strip() for m in (browse.get("meshes") or [])) if t]
        if not terms:
            continue
        arms_module = (raw.get("protocolSection") or {}).get("armsInterventionsModule") or {}
        arm_groups = arms_module.get("armGroups") or []
        interventions = arms_module.get("interventions") or []
        # Only the fields a targetCohortName is derived from. Titles are excluded on
        # purpose: a generic name in the official title does not stop the sponsor from
        # naming every arm after the development code, which is what the seed follows.
        sponsor_names = " | ".join(
            filter(
                None,
                [
                    *((a.get("label") or "") for a in arm_groups),
                    *((i.get("name") or "") for i in interventions),
                    *(o for i in interventions for o in (i.get("otherNames") or [])),
                ],
            )
        ).lower()
        trials.append({"nct": path.stem, "terms": terms, "sponsor_names": sponsor_names})
    return trials


def unique_ingredients(cur: Any, schema: str, names: list[str], vocabulary: str) -> set[str]:
    """Names that match exactly one standard Ingredient in the given vocabulary.

    Mirrors ``_exact_ingredient_mapping``'s own test, including its ``len(rows) != 1``
    rejection of ambiguous names.

    :param cur: An open psycopg2 cursor.
    :param schema: CDM schema holding the ``concept`` table.
    :param names: Lower-cased names to test.
    :param vocabulary: ``vocabulary_id`` to restrict to.
    :returns: The subset of names with exactly one matching concept.
    """
    if not names:
        return set()
    cur.execute(
        f"""
        SELECT LOWER(concept_name), COUNT(*)
        FROM {schema}.concept
        WHERE LOWER(concept_name) = ANY(%s)
          AND standard_concept = 'S'
          AND concept_class_id = 'Ingredient'
          AND vocabulary_id = %s
          AND invalid_reason IS NULL
        GROUP BY 1
        """,
        (sorted(names), vocabulary),
    )
    return {name for name, count in cur.fetchall() if count == 1}


def precise_ingredient_bridge(cur: Any, schema: str, names: list[str]) -> set[str]:
    """Names that are a salt/ester heading mapping to exactly one standard Ingredient.

    MeSH indexes 'Quetiapine Fumarate' where RxNorm's ingredient is 'Quetiapine'. OMOP
    already carries that edge as ``Precise Ingredient --Maps to--> Ingredient``, so the
    hop needs no new data.

    :param cur: An open psycopg2 cursor.
    :param schema: CDM schema holding ``concept`` and ``concept_relationship``.
    :param names: Lower-cased names to test.
    :returns: The subset reaching exactly one standard Ingredient.
    """
    if not names:
        return set()
    cur.execute(
        f"""
        SELECT LOWER(c.concept_name), COUNT(DISTINCT t.concept_id)
        FROM {schema}.concept c
        JOIN {schema}.concept_relationship cr ON cr.concept_id_1 = c.concept_id
        JOIN {schema}.concept t ON t.concept_id = cr.concept_id_2
        WHERE LOWER(c.concept_name) = ANY(%s)
          AND c.concept_class_id = 'Precise Ingredient'
          AND cr.relationship_id = 'Maps to'
          AND cr.invalid_reason IS NULL
          AND t.standard_concept = 'S'
          AND t.concept_class_id = 'Ingredient'
          AND t.invalid_reason IS NULL
        GROUP BY 1
        """,
        (sorted(names),),
    )
    return {name for name, count in cur.fetchall() if count == 1}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR))
    ap.add_argument("--json", dest="json_out", help="also write the summary as JSON")
    args = ap.parse_args(argv)

    import psycopg2

    from src.settings import settings

    cache_dir = Path(args.cache_dir)
    if not cache_dir.is_dir():
        raise SystemExit(f"no NCT cache at {cache_dir}")

    trials = load_trials(cache_dir)
    cached_total = len(list(cache_dir.glob("NCT*.json")))
    all_terms = sorted({t.lower() for tr in trials for t in tr["terms"]})

    conn = psycopg2.connect(settings.DATABASE_URL)
    try:
        with conn.cursor() as cur:
            schema = settings.CDM_SCHEMA
            resolving = unique_ingredients(cur, schema, all_terms, "RxNorm")

            for tr in trials:
                tr["resolving"] = [t for t in tr["terms"] if t.lower() in resolving]
            # The tier is only reached when the seed itself is not an ingredient name,
            # which in practice means the sponsor never wrote the generic anywhere.
            depends = [
                tr for tr in trials
                if not any(t.lower() in tr["sponsor_names"] for t in tr["terms"])
            ]
            none_resolve = [tr for tr in depends if len(tr["resolving"]) == 0]
            one_resolves = [tr for tr in depends if len(tr["resolving"]) == 1]
            many_resolve = [tr for tr in depends if len(tr["resolving"]) > 1]

            stuck_terms = sorted({t.lower() for tr in none_resolve for t in tr["terms"]})
            lever_extension = unique_ingredients(cur, schema, stuck_terms, "RxNorm Extension")
            lever_precise = precise_ingredient_bridge(cur, schema, stuck_terms)
    finally:
        conn.close()

    recoverable = lever_extension | lever_precise
    newly_served = [tr for tr in none_resolve if any(t.lower() in recoverable for t in tr["terms"])]

    print(f"cached trials                                  : {cached_total}")
    print(f"  carrying >=1 MeSH intervention term          : {len(trials)}")
    print(f"  sponsor-silent (the tier is the only bridge) : {len(depends)}")
    print()
    print("what the tier does with the trials that depend on it:")
    print(f"  accepts  (exactly one MeSH term resolves)    : {len(one_resolves)}")
    print(f"  refuses  (no MeSH term resolves)             : {len(none_resolve)}")
    print(f"  refuses  (more than one resolves: ambiguous) : {len(many_resolve)}")
    print()
    print(f"unresolvable MeSH terms in the refused population: {len(stuck_terms)}")
    print(f"  reachable as a standard Ingredient in RxNorm Extension : "
          f"{len(lever_extension)}  {sorted(lever_extension)}")
    print(f"  reachable via Precise Ingredient --Maps to--> Ingredient: "
          f"{len(lever_precise)}  {sorted(lever_precise)}")
    print(f"\ntrials those two bridges would newly serve      : "
          f"{len(newly_served)}/{len(none_resolve)}")
    for tr in newly_served:
        print(f"    {tr['nct']}  {tr['terms']}")

    if args.json_out:
        payload = {
            "cached_trials": cached_total,
            "with_mesh_terms": len(trials),
            "sponsor_silent": len(depends),
            "accepts": len(one_resolves),
            "refuses_none_resolve": len(none_resolve),
            "refuses_ambiguous": len(many_resolve),
            "unresolvable_terms": stuck_terms,
            "lever_rxnorm_extension": sorted(lever_extension),
            "lever_precise_ingredient": sorted(lever_precise),
            "newly_served": [tr["nct"] for tr in newly_served],
        }
        Path(args.json_out).write_text(json.dumps(payload, ensure_ascii=False, indent=2))
        print(f"\nwrote {args.json_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
