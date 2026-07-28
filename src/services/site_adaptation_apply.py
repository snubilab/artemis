"""Apply a site adaptation report to a CIRCE cohort so it actually returns patients.

`compile_site_adaptation` only proposes; this module executes those proposals. The
goal is an executable cohort, not a faithful transcription of the protocol — a rule
matching zero patients at the target site drops everyone, so leaving it in place
means no cohort at all.

Four edits, in order of preference:

0. **Remap a mis-mapped drug concept.** Protocols name drugs by development code
   ("BI 10773"), which OMOP does not carry, so the mapper returned an unrelated
   compound (CHF-6366 metabolite) that matches nobody. Dropping such a rule would
   delete the study drug itself — the cohort would keep everyone who failed only
   that condition. Resolving the name through PubChem and repointing the concept
   set preserves the study definition, so it runs before any removal.
1. **Repoint to populated descendants.** The exact concept is empty but its children
   are not (316866 "Hypertensive disorder" is absent everywhere while sites code
   320128 "Essential hypertension"). Meaning is preserved, so this is applied first
   and always.
2. **Prune dead concepts from a concept set.** A set usually holds several concepts
   and only some are empty — of the three BMI concepts one covers 1.6M patients.
   Dropping the whole rule here would silently discard a working criterion.
3. **Drop the rule.** Only when every concept in it is empty, and only for required
   inclusions. Exclusions matching nobody exclude nobody, so they stay untouched.

Safety rails, because an over-eager pruner produces a cohort that runs but means
nothing:

- The entry criterion is never edited. An empty entry concept is a remap problem
  (`VERIFY_THEN_REMAP`), and a cohort that enters on the wrong drug is worse than
  one that returns nothing.
- Dropping more than `max_drop_ratio` of the inclusion rules aborts. Removing 15 of
  21 rules does not yield an adapted cohort, it yields a different study.
- Every edit is recorded with the evidence that justified it, so the result can be
  reported alongside the numbers it produced.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

# Above this share of inclusion rules removed, the result is no longer an
# adaptation of the original cohort and the caller must intervene.
DEFAULT_MAX_DROP_RATIO = 0.40


@dataclass
class AppliedEdit:
    """One concrete change, with the reason it was made."""

    action: str
    path: str
    detail: str
    concept_ids: tuple[int, ...] = ()


@dataclass
class ApplyResult:
    circe: dict[str, Any] | None
    edits: list[AppliedEdit] = field(default_factory=list)
    aborted: bool = False
    abort_reason: str = ""
    rules_before: int = 0
    rules_after: int = 0

    @property
    def drop_ratio(self) -> float:
        if not self.rules_before:
            return 0.0
        return (self.rules_before - self.rules_after) / self.rules_before

    def summary(self) -> dict[str, Any]:
        """Audit record — what changed, why, and whether the result is usable."""
        by_action: dict[str, int] = {}
        for edit in self.edits:
            by_action[edit.action] = by_action.get(edit.action, 0) + 1
        return {
            "status": "aborted" if self.aborted else "applied",
            "abortReason": self.abort_reason,
            "rulesBefore": self.rules_before,
            "rulesAfter": self.rules_after,
            "dropRatio": round(self.drop_ratio, 3),
            "editCounts": by_action,
            "edits": [
                {
                    "action": e.action,
                    "path": e.path,
                    "detail": e.detail,
                    "conceptIds": list(e.concept_ids),
                }
                for e in self.edits
            ],
        }


def _rule_index(path: str) -> int | None:
    """InclusionRules[7].expression... -> 7"""
    if not path.startswith("InclusionRules["):
        return None
    try:
        return int(path[len("InclusionRules[") : path.index("]")])
    except ValueError:
        return None


def _concept_items(concept_set: Mapping[str, Any]) -> list[dict[str, Any]]:
    return (concept_set.get("expression") or {}).get("items") or []


def _codeset_ids_in(expression: Mapping[str, Any]) -> set[int]:
    """Every CodesetId referenced anywhere under a rule expression."""
    found: set[int] = set()
    stack: list[Any] = [expression]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            codeset = node.get("CodesetId")
            if isinstance(codeset, int):
                found.add(codeset)
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return found


def apply_adaptation(
    circe: Mapping[str, Any],
    report: Mapping[str, Any],
    descendants: Mapping[int, Sequence[int]],
    *,
    max_drop_ratio: float = DEFAULT_MAX_DROP_RATIO,
    remap_drug_concept: Callable[[str, int], dict[str, Any] | None] | None = None,
) -> ApplyResult:
    """Rewrite `circe` so it can return patients at the site the report describes.

    descendants maps a concept id to its populated descendants, as gathered when the
    report was compiled; it is what makes a repoint possible.

    remap_drug_concept(concept_set_name, empty_concept_id) resolves a drug concept set
    whose concept matches nobody — typically because the protocol used a development
    code — and returns a replacement OMOP concept dict, or None to leave it alone.
    Without it, such a rule is dropped and the study drug disappears from its own
    cohort, so callers working with drug criteria should supply one.
    """
    adapted = deepcopy(dict(circe))
    rules = adapted.get("InclusionRules") or []
    result = ApplyResult(circe=None, rules_before=len(rules))

    # Entry criteria are off limits — collect their paths so we skip any proposal there.
    entry_paths = {
        row["path"]
        for row in report.get("criteriaEvidence", [])
        if row.get("role") == "entry"
    }

    proposals = [
        p
        for p in report.get("proposedChanges", [])
        if p.get("path") not in entry_paths
        and _rule_index(p.get("path", "")) is not None
    ]
    blocked = [
        p
        for p in report.get("proposedChanges", [])
        if p.get("path") in entry_paths and p.get("action") != "BENIGN_KEEP"
    ]
    for p in blocked:
        result.edits.append(
            AppliedEdit(
                action="SKIPPED_ENTRY",
                path=p["path"],
                detail=(
                    f"entry criterion left untouched ({p.get('action')}); "
                    "an empty entry concept needs a remap, not an edit"
                ),
                concept_ids=(p["conceptId"],) if p.get("conceptId") else (),
            )
        )

    concept_sets = {cs["id"]: cs for cs in adapted.get("ConceptSets", [])}

    # 0) Remap drug concepts that are empty because the name never resolved. A concept
    #    set named after the drug ("BI 10773") whose single concept matches nobody is
    #    a mapping failure, not a site-coverage fact — deleting it would remove the
    #    study drug from its own cohort.
    remapped: set[tuple[int, int]] = set()  # (rule_index, old_concept_id)
    if remap_drug_concept is not None:
        for p in proposals:
            if p.get("action") != "VERIFY_THEN_DROP":
                continue
            idx = _rule_index(p["path"])
            old_id = p.get("conceptId")
            for codeset_id in _codeset_ids_in(rules[idx].get("expression", {})):
                cs = concept_sets.get(codeset_id)
                if not cs:
                    continue
                items = _concept_items(cs)
                target = next(
                    (
                        i
                        for i in items
                        if i.get("concept", {}).get("CONCEPT_ID") == old_id
                    ),
                    None,
                )
                if target is None:
                    continue
                new_concept = remap_drug_concept(cs.get("name", ""), old_id)
                if not new_concept:
                    continue
                new_id = int(new_concept["CONCEPT_ID"])
                if new_id == old_id:
                    continue
                target["concept"] = new_concept
                target["includeDescendants"] = True
                remapped.add((idx, old_id))
                result.edits.append(
                    AppliedEdit(
                        action="REMAP_DRUG_CONCEPT",
                        path=p["path"],
                        detail=(
                            f"concept set '{cs.get('name', '')}' pointed at {old_id}, "
                            f"which matches nobody; resolved the name to "
                            f"{new_concept.get('CONCEPT_NAME')} ({new_id})"
                        ),
                        concept_ids=(old_id, new_id),
                    )
                )

    # 1) Repoint to populated descendants, and remember which concepts were rescued
    #    so the prune step below does not remove them.
    rescued: set[tuple[int, int]] = set()  # (rule_index, concept_id)
    for p in proposals:
        if p.get("action") != "USE_POPULATED_DESCENDANTS":
            continue
        idx = _rule_index(p["path"])
        concept_id = p.get("conceptId")
        children = [c for c in descendants.get(concept_id, ()) if c != concept_id]
        if not children:
            continue
        for codeset_id in _codeset_ids_in(rules[idx].get("expression", {})):
            cs = concept_sets.get(codeset_id)
            if not cs:
                continue
            for item in _concept_items(cs):
                if item.get("concept", {}).get("CONCEPT_ID") != concept_id:
                    continue
                # includeDescendants is what makes the children reachable at all.
                item["includeDescendants"] = True
                rescued.add((idx, concept_id))
                result.edits.append(
                    AppliedEdit(
                        action="USE_POPULATED_DESCENDANTS",
                        path=p["path"],
                        detail=(
                            f"concept {concept_id} is empty at this site; "
                            f"{len(children)} populated descendants reachable via "
                            "includeDescendants"
                        ),
                        concept_ids=(concept_id,),
                    )
                )

    # 2) Prune concepts that are empty and could not be rescued.
    drop_targets: dict[int, set[int]] = {}
    for p in proposals:
        if p.get("action") != "VERIFY_THEN_DROP":
            continue
        idx = _rule_index(p["path"])
        concept_id = p.get("conceptId")
        if (idx, concept_id) in rescued or (idx, concept_id) in remapped:
            continue
        drop_targets.setdefault(idx, set()).add(concept_id)

    emptied_rules: set[int] = set()
    for idx, dead_concepts in drop_targets.items():
        for codeset_id in _codeset_ids_in(rules[idx].get("expression", {})):
            cs = concept_sets.get(codeset_id)
            if not cs:
                continue
            items = _concept_items(cs)
            kept = [
                i
                for i in items
                if i.get("concept", {}).get("CONCEPT_ID") not in dead_concepts
            ]
            if len(kept) == len(items):
                continue
            removed = tuple(
                i["concept"]["CONCEPT_ID"] for i in items if i not in kept
            )
            if kept:
                cs["expression"]["items"] = kept
                result.edits.append(
                    AppliedEdit(
                        action="PRUNE_DEAD_CONCEPTS",
                        path=f"ConceptSets[{codeset_id}]",
                        detail=(
                            f"removed {len(removed)} concept(s) with no patients; "
                            f"{len(kept)} still populated, so the rule survives"
                        ),
                        concept_ids=removed,
                    )
                )
            else:
                # Nothing left in this set — the rule can no longer match anyone.
                emptied_rules.add(idx)

    # 3) Drop rules whose concepts are all empty.
    if emptied_rules:
        survivors = [r for i, r in enumerate(rules) if i not in emptied_rules]
        for idx in sorted(emptied_rules):
            result.edits.append(
                AppliedEdit(
                    action="DROP_RULE",
                    path=f"InclusionRules[{idx}]",
                    detail=(
                        f"'{(rules[idx].get('name') or '')[:60]}' — every concept is "
                        "empty at this site, so the rule excludes all patients"
                    ),
                    concept_ids=tuple(sorted(drop_targets.get(idx, ()))),
                )
            )
        adapted["InclusionRules"] = survivors

    result.rules_after = len(adapted.get("InclusionRules") or [])

    if result.drop_ratio > max_drop_ratio:
        result.aborted = True
        result.abort_reason = (
            f"would drop {result.rules_before - result.rules_after} of "
            f"{result.rules_before} rules ({result.drop_ratio:.0%} > "
            f"{max_drop_ratio:.0%}); the result would be a different study, "
            "not an adaptation"
        )
        return result

    result.circe = adapted
    return result
