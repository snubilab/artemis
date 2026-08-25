"""SPEC-INFRA-004 AC-010 / REQ-003: collapse output is invariant under grouping-state change.

The property form of REQ-003, and the strongest available evidence that grouping state is not
load-bearing on the safety path. AC-002 and AC-003 test two specific clusters; this tests the
whole corpus and would catch a `groupId` dependency introduced anywhere in the generalized
path, including one added later.

`spec.md` §2.3 is why this matters rather than being a nicety. CARMELINA's ALT/AST/AP triple —
three genuinely distinct analytes — moved from `groupId: null` to a shared non-null `groupId`
between two regenerations of the same pipeline, with no membership change. Grouping state is a
model choice that moves run to run, so a safety property resting on it is not a safety
property.

**Scoped to generalized-path records, which is necessary rather than a weakening.** The
comparison tuple contains `stem` and the distinctness key, and a Demographics-path record
carries neither — `SPEC-INFRA-003`'s collapse is whole-role, so it has no stem and forms no
class. The tuple is not computable for those records, and including them would make the
criterion ill-defined rather than stricter. The Demographics path's own gate 3 reads `groupId`
**by design**, so permuting grouping state legitimately changes which criteria it claims;
REQ-013's disjointness is what keeps that legitimate movement from reaching this path's
output.
"""
from __future__ import annotations

from src.services.restated_distinctness import collapse_all_restated_criteria
from tests.infra_004_store_fixture import (
    criteria,
    group_every_stem_group,
    studies,
    transform_store,
    ungroup_everything,
)


def _record_set(study_list: list[dict]) -> set[tuple]:
    """Generalized-path records across a whole store, keyed on grouping-independent fields."""
    out = set()
    for study in study_list:
        _, records, _ = collapse_all_restated_criteria(
            inclusion_criteria=criteria(study, "inclusion"),
            exclusion_criteria=criteria(study, "exclusion"),
        )
        for r in records:
            out.add(
                (
                    study.get("nctId") or f"study{study['studyId']}",
                    r["role"],
                    r["domain"],
                    r["stem"],
                    r["distinctnessKey"]["sourceText"],
                    tuple(sorted(str(i) for i in r["droppedIds"])),
                )
            )
    return out


class TestTheRecordSetIsIdenticalAcrossGroupingPermutations:
    def test_should_be_identical_between_the_store_and_a_fully_ungrouped_transformation(self):
        original = _record_set(studies())
        cleared = _record_set(transform_store(studies(), ungroup_everything))
        assert cleared == original, {
            "only-when-ungrouped": sorted(cleared - original),
            "only-when-stored": sorted(original - cleared),
        }

    def test_should_be_identical_between_the_store_and_a_fully_grouped_transformation(self):
        original = _record_set(studies())
        grouped = _record_set(transform_store(studies(), group_every_stem_group))
        assert grouped == original, {
            "only-when-grouped": sorted(grouped - original),
            "only-when-stored": sorted(original - grouped),
        }

    def test_should_be_identical_across_all_three_runs_at_once(self):
        """The criterion as `acceptance.md` states it: one record set, three stores."""
        sets = [
            _record_set(studies()),
            _record_set(transform_store(studies(), ungroup_everything)),
            _record_set(transform_store(studies(), group_every_stem_group)),
        ]
        assert sets[0] == sets[1] == sets[2]

    def test_should_actually_move_the_grouping_state_it_claims_to_permute(self):
        """The test of the test. A transformation that changed nothing would make the three
        criteria above pass without exercising anything."""
        original = studies()
        cleared = transform_store(original, ungroup_everything)
        grouped = transform_store(original, group_every_stem_group)

        def group_ids(store):
            return [
                c.get("groupId")
                for s in store
                for role in ("inclusion", "exclusion")
                for c in criteria(s, role)
            ]

        assert any(g is not None for g in group_ids(original)), "fixture carries no grouping"
        assert all(g is None for g in group_ids(cleared))
        assert all(g is not None for g in group_ids(grouped))
        assert group_ids(original) != group_ids(grouped)


class TestTheCategoryTwoClustersSurviveEveryPermutation:
    """The specific consequence AC-002 and AC-003 test on two clusters, asserted here across
    every permutation at once."""

    def test_should_never_emit_a_record_for_a_category_two_cluster_in_any_permutation(self):
        forbidden = {"Cardiovascular Disease", "Thyroid Disorders", "Adrenal Disorders"}
        for store in (
            studies(),
            transform_store(studies(), ungroup_everything),
            transform_store(studies(), group_every_stem_group),
        ):
            stems = {r[3] for r in _record_set(store)}
            assert not (stems & forbidden), stems & forbidden
