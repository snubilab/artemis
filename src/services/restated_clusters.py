"""SPEC-INFRA-003 REQ-005: detect restated-cluster duplication in agent1 IR.

Agent1 emits several near-duplicate top-level criteria from one protocol eligibility
sentence. Each duplicate is mapped independently -- keyed on its own paraphrased
`description`, because `sourceText` is empty -- and the resulting concept sets diverge
sharply. Every duplicate becomes a separate top-level CIRCE `InclusionRule`, so the
cohort is filtered on the *union* of those divergent sets rather than on one coherent
set (`spec.md` §2.2, measured: pairwise Jaccard 0.00-0.75, union 11 concepts against
4-7 for any single criterion).

This module supplies the measurement, not the fix.

The signal (`spec.md` §2.5) is a compound of three conditions, all required. Within one
study and one role, two or more criteria form a restated cluster when they

1. share the same `domain`, **and**
2. all carry `valueConstraint: null`, **and**
3. share the same description **stem** -- the description with a single trailing
   parenthetical suffix stripped.

It is deliberately narrower than description similarity, which `plan.md` §G forbids
outright: this is exact equality on a mechanically derived stem, gated behind two
structural predicates. No fuzzy matching, no edit distance, no threshold, and no
criterion-id or study-id special cases (AC-013).

Condition 2 is the load-bearing one. CARMELINA exclusion #3 emits three criteria whose
descriptions differ only by an `(AST)` / `(AP)` suffix -- the same surface shape as the
`(<= 1 year)` / `(General)` suffixes that ARE duplicates. Similarity cannot separate
them. The analytes each carry `{op: gte, value: 3.0, unitText: "x ULN"}` bound to a
different named entity and the restatements carry nothing, so condition 2 rules the
analytes out without judgment (`spec.md` §2.3.3).

Verified against the live reference store: 10 clusters over 162 criteria across three
trials, zero false positives, one known false negative -- EMPA-REG's heading plus
merged-content pair shares no stem, so no cluster forms for it (`spec.md` §2.5.2). That
shape is covered by enumeration, not by this detector.
"""
from __future__ import annotations

import re
from typing import Any

# `spec.md` §2.5 condition 3, verbatim: s/\s*\([^()]*\)\s*$//
# `[^()]*` cannot span a nested `)`, so a description ending in two parenthetical
# groups loses only the last one -- "one trailing suffix", as specified.
_TRAILING_PARENTHETICAL = re.compile(r"\s*\([^()]*\)\s*$")


def description_stem(description: str | None) -> str:
    """Return a criterion description with a single trailing parenthetical stripped.

    Args:
        description: The criterion's `description` field; None is treated as empty.

    Returns:
        The stem used for condition 3's exact-equality test. Descriptions with no
        trailing parenthetical are returned unchanged.
    """
    return _TRAILING_PARENTHETICAL.sub("", description or "", count=1)


def cluster_key(criterion: dict[str, Any]) -> tuple[str, str] | None:
    """Return the `(domain, stem)` key a criterion clusters under, or None.

    This is conditions 1 through 3 of the `spec.md` §2.5 signal minus its two-or-more
    threshold: condition 2 decides eligibility, and conditions 1 and 3 supply the key.
    A criterion carrying any `valueConstraint` has no key at all, which is how the
    distinct-entity case (`spec.md` §2.3.3) is kept out without inspecting its ids.

    The threshold is what makes this worth exposing separately. Cluster detection needs
    it -- one criterion is not a duplication. Stability measurement (REQ-006) must not
    have it: a sentence that has converged emits exactly one criterion, and a sentence
    that vanished emits none, and both are reported by a thresholded detector as the
    same nothing.

    Args:
        criterion: A top-level IR criterion.

    Returns:
        `(domain, description stem)` when the criterion is eligible to cluster, or None
        when it carries a `valueConstraint`.
    """
    # An absent key and an explicit null are the same thing here.
    if criterion.get("valueConstraint") is not None:
        return None
    return (criterion.get("domain") or "", description_stem(criterion.get("description")))


def detect_restated_clusters(
    criteria: list[dict[str, Any]],
    *,
    role: str,
) -> list[dict[str, Any]]:
    """Find every restated cluster among one role's top-level criteria.

    Applies the `spec.md` §2.5 signal exactly: same `domain`, `valueConstraint: null`
    on every member, identical description stem. A criterion carrying any
    `valueConstraint` is excluded from consideration entirely, which is how the
    distinct-entity case (`spec.md` §2.3.3) is kept out without inspecting its ids.

    Args:
        criteria: Top-level criteria for a single role of a single study.
        role: The role these criteria belong to, "inclusion" or "exclusion". Recorded
            on each cluster; clusters never span roles.

    Returns:
        One dict per detected cluster, in first-appearance order, each carrying
        `role`, `domain`, `stem`, and `criterionIds` (member order as encountered).
        Sets of fewer than two members are not clusters and are not reported.
    """
    by_stem: dict[tuple[str, str], list[Any]] = {}
    for criterion in criteria or []:
        # Condition 2 rules a constrained criterion out; conditions 1 and 3 key the
        # bucket together, so a stem shared across two domains never forms a cluster.
        key = cluster_key(criterion)
        if key is None:
            continue
        by_stem.setdefault(key, []).append(criterion.get("id"))

    return [
        {"role": role, "domain": domain, "stem": stem, "criterionIds": ids}
        for (domain, stem), ids in by_stem.items()
        if len(ids) >= 2
    ]


def detect_all_restated_clusters(
    *,
    inclusion_criteria: list[dict[str, Any]],
    exclusion_criteria: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Find restated clusters across both roles of one study.

    Args:
        inclusion_criteria: The study's top-level inclusion criteria.
        exclusion_criteria: The study's top-level exclusion criteria.

    Returns:
        Inclusion-role clusters followed by exclusion-role clusters. Roles are
        detected independently, so a stem shared between an inclusion and an
        exclusion criterion never forms a cluster.
    """
    return (
        detect_restated_clusters(inclusion_criteria, role="inclusion")
        + detect_restated_clusters(exclusion_criteria, role="exclusion")
    )
