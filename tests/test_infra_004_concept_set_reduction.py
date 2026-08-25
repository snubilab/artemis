"""SPEC-INFRA-004 AC-015: the reduction is measured, per cluster and in aggregate.

AC-015 asks for a figure rather than an estimate, so the numbers below are pinned as
assertions rather than written into a report that nothing re-checks. A regression that
quietly stops collapsing one cluster moves a row here, which is the point -- `plan.md` §G
records agent1 emission as run-to-run unstable, and a measurement no test defends decays
into a claim about a store that no longer exists.

**What one concept set means here.** Every top-level criterion that reaches the mapper
yields one concept set, so a cluster's pre-collapse concept-set count is its member count
and its post-collapse count is the number of survivors. That identity is not assumed
here: test_infra_004_collapse_reaches_the_circe_build.py builds real CIRCE over the
multi-class liver cluster and measures six criteria in against three mapped and three
skipped -- the (6, 3) row below, observed end to end. The table is therefore anchored to
an emitted CIRCE count rather than resting on arithmetic over collapse records.

**Per stem group, not per class.** A group holding a collapsible class *and* singletons --
CAROLINA inclusion `Elevated HbA1c`, four members in three classes -- reduces by one, not to
one. Reporting per class would hide that, and the per-cluster figure AC-015 asks for is the
one a reader compares against a regenerated store.
"""
from __future__ import annotations

import pytest

from src.services.restated_distinctness import analyze_restated_groups
from tests.infra_004_store_fixture import ROLES, criteria, studies

CAROLINA = "NCT01243424"
EMPA_REG = "NCT01131676"

# Cluster key is (study, role, domain, stem); value is (concept sets before, after).
# Keyed on identity fields rather than on ids, per acceptance.md Conventions: ids shift
# across regenerations and a table keyed on them fails AC-011 in spirit even where it
# passes mechanically. Measured against the store extract at commit 3e38b64.
EXPECTED_REDUCTION: dict[tuple[str, str, str, str], tuple[int, int]] = {
    # Three analytes emitted twice: the SPEC's largest single harm, and the only corpus
    # cluster whose correct outcome is neither "unchanged" nor "one" (AC-006).
    (EMPA_REG, "exclusion", "Measurement", "Liver disease"): (6, 3),
    # Demographics domain with a non-null valueConstraint, so SPEC-INFRA-003's gate 2
    # rejects it and only the REQ-013 predicate gate lets this path see it (AC-016 f3).
    (CAROLINA, "inclusion", "Demographics", "Age >= 70 years"): (2, 1),
    # Four members, three classes: the collapsible pair sits inside a Pattern G group.
    (CAROLINA, "inclusion", "Measurement", "Elevated HbA1c"): (4, 3),
    (CAROLINA, "exclusion", "Observation", "Alcohol or drug abuse"): (2, 1),
    (CAROLINA, "exclusion", "Condition", "Alcohol Use Disorder"): (2, 1),
    (CAROLINA, "exclusion", "Condition", "Opioid Use Disorder"): (2, 1),
    (CAROLINA, "exclusion", "Condition", "Cannabis Use Disorder"): (2, 1),
    (CAROLINA, "exclusion", "Condition", "Cocaine Use Disorder"): (2, 1),
    (CAROLINA, "exclusion", "Drug", "Other antidiabetic drugs"): (2, 1),
    # The three-member class: distinguishes first-in-document-order from last and from
    # lowest-id in one fixture (AC-013).
    (CAROLINA, "exclusion", "Drug", "GLP-1 Receptor Agonists"): (3, 1),
    (CAROLINA, "exclusion", "Drug", "SGLT2 Inhibitors"): (2, 1),
    (CAROLINA, "exclusion", "Drug", "DPP-4 Inhibitors"): (2, 1),
    (CAROLINA, "exclusion", "Drug", "Thiazolidinediones"): (2, 1),
}

AGGREGATE_PRE = 33
AGGREGATE_POST = 17
AGGREGATE_REDUCTION = 16


def _measure() -> dict[tuple[str, str, str, str], tuple[int, int]]:
    """Return per-cluster (pre, post) concept-set counts over the reference store.

    `pre` counts the criteria the REQ-013 gate admits into the group, which is what would
    have reached the mapper without this SPEC. `post` subtracts only the members of
    collapsible classes, so singletons and REQ-004-withheld classes count as surviving.
    """
    measured: dict[tuple[str, str, str, str], tuple[int, int]] = {}
    for study in studies():
        nct = study.get("nctId")
        for role in ROLES:
            for group in analyze_restated_groups(criteria(study, role), role=role):
                if not group["collapses"]:
                    continue
                pre = len(group["consideredIds"])
                dropped = sum(
                    len(cls["droppedIds"]) for cls in group["classes"] if cls["collapsible"]
                )
                measured[(nct, role, group["domain"], group["stem"])] = (pre, pre - dropped)
    return measured


class TestPerClusterConceptSetCounts:
    """AC-015's first clause: pre- and post-collapse counts, per cluster."""

    def test_should_collapse_exactly_the_thirteen_measured_clusters(self):
        assert set(_measure()) == set(EXPECTED_REDUCTION)

    @pytest.mark.parametrize("cluster", sorted(EXPECTED_REDUCTION), ids=lambda c: f"{c[0]}-{c[3]}")
    def test_should_reproduce_the_measured_counts_for_each_cluster(self, cluster):
        assert _measure()[cluster] == EXPECTED_REDUCTION[cluster]

    def test_should_never_reduce_a_cluster_below_one_survivor(self):
        """A post count of zero would mean a cluster vanished rather than collapsed."""
        assert all(post >= 1 for _, post in _measure().values())

    def test_should_leave_the_liver_group_at_three_not_one(self):
        """The AC-006 failure mode restated as a count. One would mean the implementation
        reduced the stem group instead of partitioning it, destroying two real analytes."""
        assert _measure()[(EMPA_REG, "exclusion", "Measurement", "Liver disease")] == (6, 3)


class TestAggregateReduction:
    """AC-015's second clause: the aggregate stated as a measured figure."""

    def test_should_sum_to_the_measured_aggregate(self):
        measured = _measure().values()
        assert (sum(pre for pre, _ in measured), sum(post for _, post in measured)) == (
            AGGREGATE_PRE,
            AGGREGATE_POST,
        )

    def test_should_reduce_by_the_measured_figure(self):
        assert sum(pre - post for pre, post in _measure().values()) == AGGREGATE_REDUCTION

    def test_should_agree_with_the_per_cluster_table(self):
        """Guards the table against drifting out of step with the aggregate constants."""
        assert (
            sum(pre for pre, _ in EXPECTED_REDUCTION.values()),
            sum(post for _, post in EXPECTED_REDUCTION.values()),
        ) == (AGGREGATE_PRE, AGGREGATE_POST)
