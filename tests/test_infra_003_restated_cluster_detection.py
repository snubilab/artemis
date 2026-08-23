"""SPEC-INFRA-003 REQ-005: restated-cluster detection is observable.

Agent1 emits N near-duplicate top-level criteria from one protocol sentence. Each is
mapped independently and the cohort ends up filtered on the union of divergent concept
sets (`spec.md` §2.2). Before any behavior changes, the duplication has to be
*measurable* -- REQ-005 makes it so.

The signal is `spec.md` §2.5, a compound of three conditions, all required. Within one
study and one role, two or more criteria form a restated cluster when they

1. share the same `domain`, **and**
2. all carry `valueConstraint: null`, **and**
3. share the same description **stem** -- the description with a single trailing
   parenthetical suffix stripped (`s/\\s*\\([^()]*\\)\\s*$//`).

Condition 2 is what carries the whole thing. Description similarity alone cannot work:
CARMELINA's ALT/AST/AP triple differs only by an `(AST)` / `(AP)` suffix, which is the
same surface shape as the `(<= 1 year)` / `(General)` suffixes that ARE duplicates
(`plan.md` §G). The `valueConstraint` gate separates them without judgment -- the
analytes each carry `{op: gte, value: 3.0, unitText: "x ULN"}` and the pregnancy
restatements carry nothing.

**Fixture provenance.** These fixtures are synthetic reconstructions of the inventory
`spec.md` §2.5.1 verified against the live reference store
(`/app/tmp/tte_six_20260823_patternG_v2/studies.json`, read inside `artemis-api`):
10 clusters over 162 criteria, zero false positives, one known false negative. They
reproduce the documented field shape (§2.1), domains, ids, stems, and parenthetical
suffixes recorded there. They are *not* the store itself; reproducing AC-006 against
the real IR needs the container and is out of scope here.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from src.services.restated_clusters import (
    description_stem,
    detect_all_restated_clusters,
    detect_restated_clusters,
)

# ---------------------------------------------------------------------------
# Fixture helpers -- field shape per spec.md §2.1
# ---------------------------------------------------------------------------

def _criterion(
    *,
    id: int,
    description: str,
    domain: str,
    value_constraint: dict[str, Any] | None = None,
    group_id: str | None = None,
    group_type: str = "ALL",
    logic_type: str = "ABSENCE",
    window: dict[str, Any] | None = None,
    is_group_label: bool = False,
    source_text: str = "",
) -> dict[str, Any]:
    """Build a top-level IR criterion in the shape `spec.md` §2.1 documents.

    Args:
        id: Criterion id, unique within a (study, role) scope.
        description: The paraphrased description the mapper falls back to.
        domain: OMOP-ish domain label, e.g. "Demographics" / "Measurement".
        value_constraint: `{op, value, unitText}` when the criterion carries one.
        group_id: Non-null when the criterion belongs to a group.
        group_type: CIRCE group type, "ALL" or "ANY".
        logic_type: "PRESENCE" or "ABSENCE".
        window: `{start, end}` day offsets.
        is_group_label: True for a heading-only group label criterion.
        source_text: Verbatim protocol text; empty on every affected criterion.

    Returns:
        A criterion dict.
    """
    return {
        "id": id,
        "description": description,
        "domain": domain,
        "groupId": group_id,
        "groupType": group_type,
        "valueConstraint": value_constraint,
        "logicType": logic_type,
        "window": window,
        "isGroupLabel": is_group_label,
        "sourceText": source_text,
    }


def _ids(clusters: list[dict[str, Any]]) -> list[list[int]]:
    return [c["criterionIds"] for c in clusters]


# ---------------------------------------------------------------------------
# The §2.5.1 inventory, reconstructed per cluster
# ---------------------------------------------------------------------------

# CARMELINA exclusion #10 -- one sentence, three criteria (spec.md §2.1, §2.2).
# The suffixes are the ones the store actually holds; `(<= 1 year)` came from the
# protocol's scoping parenthetical being read as a Pattern G subgroup variant.
PREGNANCY_STEM = "Pregnancy/Nursing/Uncontrolled Contraception"
# Stems recorded in the §2.5.1 inventory, named here so the fixtures stay readable.
CAROLINA_PREGNANCY_STEM = "Pre-menopausal women/Nursing/Pregnant/Not using contraception"
TRIAL_PARTICIPATION_STEM = "Participation in another trial"
BACKGROUND_MED_STEM = "Stable Background Medication"
CARMELINA_PREGNANCY = [
    _criterion(id=11, description=PREGNANCY_STEM, domain="Demographics"),
    _criterion(id=12, description=f"{PREGNANCY_STEM} (<= 1 year)", domain="Demographics"),
    _criterion(id=18, description=f"{PREGNANCY_STEM} (General)", domain="Demographics"),
]

# CARMELINA exclusion #3 -- ALT / AST / alkaline phosphatase >= 3 x ULN.
# Same surface shape as a restated cluster; separated only by condition 2.
CARMELINA_ANALYTES = [
    _criterion(
        id=1, description="Liver enzyme elevation (ALT)", domain="Measurement",
        value_constraint={"op": "gte", "value": 3.0, "unitText": "x ULN"},
    ),
    _criterion(
        id=2, description="Liver enzyme elevation (AST)", domain="Measurement",
        value_constraint={"op": "gte", "value": 3.0, "unitText": "x ULN"},
    ),
    _criterion(
        id=3, description="Liver enzyme elevation (AP)", domain="Measurement",
        value_constraint={"op": "gte", "value": 3.0, "unitText": "x ULN"},
    ),
]

# CARMELINA inclusion ids 1/2/3 -- the Pattern G region-conditional Age group.
# Shares a groupId, carries numeric constraints, and is legitimate (AC-007).
CARMELINA_AGE_GROUP = [
    _criterion(
        id=1, description="Age >= 18 years (General)", domain="Demographics",
        value_constraint={"op": "gte", "value": 18}, group_id="g1", group_type="ANY",
        logic_type="PRESENCE",
    ),
    _criterion(
        id=2, description="Age >= 18 years (Japan)", domain="Demographics",
        value_constraint={"op": "gte", "value": 20}, group_id="g1", group_type="ANY",
        logic_type="PRESENCE",
    ),
    _criterion(
        id=3, description="Age >= 18 years (Korea)", domain="Demographics",
        value_constraint={"op": "gte", "value": 19}, group_id="g1", group_type="ANY",
        logic_type="PRESENCE",
    ),
]

# EMPA-REG exclusion #11 -- heading (id 27) + merged content (id 28), spec.md §2.5.2.
EMPA_REG_PREGNANCY = [
    _criterion(id=27, description="Pre-menopausal women criteria", domain="Demographics"),
    _criterion(id=28, description="Pre-menopausal women contraception/pregnancy status",
               domain="Demographics"),
]


class TestDescriptionStem:
    """Condition 3's mechanical derivation: strip one trailing parenthetical."""

    def test_should_strip_a_single_trailing_parenthetical_when_present(self):
        assert description_stem("Pregnancy/Nursing/Uncontrolled Contraception (<= 1 year)") == (
            "Pregnancy/Nursing/Uncontrolled Contraception"
        )

    def test_should_return_the_description_unchanged_when_no_parenthetical_trails(self):
        assert description_stem("Alcohol or drug abuse") == "Alcohol or drug abuse"

    def test_should_leave_an_interior_parenthetical_alone_when_it_is_not_trailing(self):
        assert description_stem("ALT (SGPT) elevation") == "ALT (SGPT) elevation"

    def test_should_strip_only_the_outermost_trailing_group_when_two_trail(self):
        # `[^()]*` cannot span the inner `)`, so only the last group is removed.
        assert description_stem("Trial participation (IMP) (given)") == "Trial participation (IMP)"


class TestPositiveDetection:
    """AC-006: the signal fires on every §2.5.1 cluster."""

    def test_should_cluster_carmelina_pregnancy_when_all_three_conditions_hold(self):
        clusters = detect_restated_clusters(CARMELINA_PREGNANCY, role="exclusion")

        assert _ids(clusters) == [[11, 12, 18]]
        assert clusters[0]["domain"] == "Demographics"
        assert clusters[0]["role"] == "exclusion"
        assert clusters[0]["stem"] == PREGNANCY_STEM

    def test_should_cluster_carolina_pregnancy_when_descriptions_are_byte_identical(self):
        # CAROLINA exclusion #17 admits no variant reading at all (spec.md §2.1).
        criteria = [
            _criterion(id=21, description=CAROLINA_PREGNANCY_STEM, domain="Demographics"),
            _criterion(id=53, description=CAROLINA_PREGNANCY_STEM, domain="Demographics"),
        ]

        clusters = detect_restated_clusters(criteria, role="exclusion")

        assert _ids(clusters) == [[21, 53]]
        assert clusters[0]["stem"] == CAROLINA_PREGNANCY_STEM

    def test_should_cluster_window_variants_when_only_the_window_differs(self):
        # spec.md §2.5.3: CAROLINA {4,40} .. {8,44} differ only in `window`
        # (-90 vs -9999). `window` is not part of the signal, so they cluster.
        criteria = [
            _criterion(id=4, description="Alcohol or drug abuse", domain="Observation",
                       window={"start": -90, "end": 0}),
            _criterion(id=40, description="Alcohol or drug abuse", domain="Observation",
                       window={"start": -9999, "end": 0}),
        ]

        clusters = detect_restated_clusters(criteria, role="exclusion")

        assert _ids(clusters) == [[4, 40]]

    def test_should_report_every_cluster_when_one_role_carries_several(self):
        # CAROLINA exclusion: five stem-pairs from #15 plus #16 and #17.
        criteria = [
            _criterion(id=4, description="Alcohol or drug abuse", domain="Observation",
                       window={"start": -90, "end": 0}),
            _criterion(id=5, description="Alcohol Use Disorder", domain="Condition"),
            _criterion(id=6, description="Opioid Use Disorder", domain="Condition"),
            _criterion(id=7, description="Cannabis Use Disorder", domain="Condition"),
            _criterion(id=8, description="Cocaine Use Disorder", domain="Condition"),
            _criterion(id=19, description=f"{TRIAL_PARTICIPATION_STEM} (Investigational Drug)",
                       domain="Procedure"),
            _criterion(id=21, description=CAROLINA_PREGNANCY_STEM, domain="Demographics"),
            _criterion(id=40, description="Alcohol or drug abuse", domain="Observation",
                       window={"start": -9999, "end": 0}),
            _criterion(id=41, description="Alcohol Use Disorder", domain="Condition"),
            _criterion(id=42, description="Opioid Use Disorder", domain="Condition"),
            _criterion(id=43, description="Cannabis Use Disorder", domain="Condition"),
            _criterion(id=44, description="Cocaine Use Disorder", domain="Condition"),
            _criterion(id=51, description=f"{TRIAL_PARTICIPATION_STEM} (IMP given)",
                       domain="Procedure"),
            _criterion(id=53, description=CAROLINA_PREGNANCY_STEM, domain="Demographics"),
        ]

        clusters = detect_restated_clusters(criteria, role="exclusion")

        assert _ids(clusters) == [
            [4, 40], [5, 41], [6, 42], [7, 43], [8, 44], [19, 51], [21, 53],
        ]

    def test_should_cluster_inclusion_role_criteria_when_the_signal_holds(self):
        # CARMELINA inclusion #2 and #3 (spec.md §2.5.1) -- PRESENCE criteria still
        # cluster; the signal has no logic_type condition.
        criteria = [
            _criterion(id=8, description="Drug Naïve or Pre-treated (Excluding specific classes)",
                       domain="Drug", logic_type="PRESENCE"),
            _criterion(id=9, description="Drug Naïve or Pre-treated (7 days)",
                       domain="Drug", logic_type="PRESENCE"),
            _criterion(id=10, description=f"{BACKGROUND_MED_STEM} (8 weeks)",
                       domain="Observation", logic_type="PRESENCE"),
            _criterion(id=11, description=f"{BACKGROUND_MED_STEM} (8 weeks prior to randomization)",
                       domain="Observation", logic_type="PRESENCE"),
        ]

        clusters = detect_restated_clusters(criteria, role="inclusion")

        assert _ids(clusters) == [[8, 9], [10, 11]]


class TestNegativeDetection:
    """AC-007 and the §2.5.2 known false negative."""

    def test_should_not_cluster_the_analyte_triple_when_each_carries_a_value_constraint(self):
        # AC-007. Stems are identical ("Liver enzyme elevation") -- only condition 2
        # separates these from a genuine restatement.
        clusters = detect_restated_clusters(CARMELINA_ANALYTES, role="exclusion")

        assert clusters == []

    def test_should_not_cluster_the_pattern_g_age_group_when_constraints_are_present(self):
        # AC-007: CARMELINA inclusion ids 1/2/3, the region-conditional Age group.
        clusters = detect_restated_clusters(CARMELINA_AGE_GROUP, role="inclusion")

        assert clusters == []

    def test_should_not_cluster_empa_reg_heading_and_merged_content_when_stems_differ(self):
        # spec.md §2.5.2, the one known false negative: a heading plus merged content
        # share no stem, so no cluster forms. Recorded, not tuned away.
        clusters = detect_restated_clusters(EMPA_REG_PREGNANCY, role="exclusion")

        assert clusters == []

    def test_should_not_cluster_across_domains_when_only_the_stem_matches(self):
        criteria = [
            _criterion(id=1, description="Alcohol Use Disorder", domain="Condition"),
            _criterion(id=2, description="Alcohol Use Disorder", domain="Observation"),
        ]

        assert detect_restated_clusters(criteria, role="exclusion") == []

    def test_should_not_cluster_when_one_member_carries_a_value_constraint(self):
        # "all carry valueConstraint: null" -- one non-null member breaks the set.
        criteria = [
            _criterion(id=1, description="Heart failure", domain="Condition"),
            _criterion(id=2, description="Heart failure (NYHA III)", domain="Condition",
                       value_constraint={"op": "gte", "value": 3}),
        ]

        assert detect_restated_clusters(criteria, role="exclusion") == []

    def test_should_not_report_a_singleton_when_no_other_criterion_shares_its_stem(self):
        criteria = [
            _criterion(id=1, description="Type 1 diabetes", domain="Condition"),
            _criterion(id=2, description="Acute coronary syndrome", domain="Condition"),
        ]

        assert detect_restated_clusters(criteria, role="exclusion") == []

    def test_should_not_cluster_across_roles_when_the_stem_is_shared(self):
        # "within one study and role" -- an inclusion and an exclusion criterion that
        # share a stem are not a restatement of each other.
        shared = "Metformin therapy"
        clusters = detect_all_restated_clusters(
            inclusion_criteria=[_criterion(id=1, description=shared, domain="Drug",
                                           logic_type="PRESENCE")],
            exclusion_criteria=[_criterion(id=2, description=shared, domain="Drug")],
        )

        assert clusters == []


class TestRoleAggregation:
    """`detect_all_restated_clusters` walks both roles and tags each cluster."""

    def test_should_tag_each_cluster_with_its_role_when_both_roles_cluster(self):
        clusters = detect_all_restated_clusters(
            inclusion_criteria=[
                _criterion(id=8, description="Drug Naïve or Pre-treated (Excluding classes)",
                           domain="Drug", logic_type="PRESENCE"),
                _criterion(id=9, description="Drug Naïve or Pre-treated (7 days)",
                           domain="Drug", logic_type="PRESENCE"),
            ],
            exclusion_criteria=CARMELINA_PREGNANCY,
        )

        assert [(c["role"], c["criterionIds"]) for c in clusters] == [
            ("inclusion", [8, 9]),
            ("exclusion", [11, 12, 18]),
        ]

    def test_should_return_nothing_when_no_criteria_are_supplied(self):
        assert detect_all_restated_clusters(inclusion_criteria=[], exclusion_criteria=[]) == []


class TestNoSpecialCasing:
    """AC-013: the verdict rests on the §2.5 signal, never on trial identity."""

    def test_should_cluster_criteria_from_an_untagged_study_when_the_signal_holds(self):
        # `spec.md` §2.3.1 studyId 4 / studyId 6 are untagged (`nctId: null`)
        # liraglutide-vs-placebo records, outside the three named trials. Ids here are
        # deliberately unlike any id enumerated in the SPEC.
        criteria = [
            _criterion(id=907, description="Severe hypoglycaemia", domain="Condition"),
            _criterion(id=908, description="Severe hypoglycaemia (within 6 months)",
                       domain="Condition"),
        ]

        clusters = detect_restated_clusters(criteria, role="exclusion")

        assert _ids(clusters) == [[907, 908]]

    def test_should_contain_no_criterion_id_or_study_literals_in_the_detector_source(self):
        # AC-013 is a property of the implementation, not only of its output: "any
        # id-keyed or study-keyed special case in the implementation fails this
        # criterion regardless of output". A lookup table would satisfy every
        # assertion above and still be wrong.
        import inspect
        import re

        from src.services import restated_clusters

        source = inspect.getsource(restated_clusters)
        # The docstrings cite the SPEC's trials; the executable body must not.
        body = "\n".join(
            line for line in source.splitlines()
            if not line.lstrip().startswith("#")
        )
        code = re.sub(r'"""(?:.|\n)*?"""', "", body)

        for token in ("CARMELINA", "CAROLINA", "EMPA", "NCT0", "studyId", "nctId"):
            assert token not in code, f"detector body references {token!r}"
        assert not re.search(r'\bid\b\s*==|\["id"\]\s*==|get\("id"\)\s*==', code), (
            "detector body compares a criterion id against a literal"
        )


# ---------------------------------------------------------------------------
# REQ-005: the clusters have to reach the emitted artifact, not just a function
# ---------------------------------------------------------------------------

def _stub_recommend(name: str, expected_domain: str | None = None, workflow=None, **kwargs):
    """Return a minimal concept-set recommendation stub."""
    return {
        "name": name,
        "domain": "Condition",
        "expression": {"items": [{"concept": {"CONCEPT_ID": 99999}}]},
    }


def _stub_eligibility_rule(criterion, *, codeset_id, exclusion):
    """Return a minimal eligibility-rule result stub."""
    label = criterion.get("description", "rule")
    return {
        "conceptSet": {"id": codeset_id, "name": label, "expression": {"items": []}},
        "rule": {
            "name": label,
            "expression": {
                "Type": "ALL",
                "CriteriaList": [{"ConditionOccurrence": {"CodesetId": codeset_id}}],
                "DemographicCriteriaList": [],
                "Groups": [],
            },
        },
    }


@pytest.fixture
def service():
    """A TTEService with the expensive Agent2 / vector-search methods stubbed out."""
    from src.services.tte_service import TTEService

    svc = TTEService.__new__(TTEService)
    svc._recommend_seeded_concept_set = MagicMock(side_effect=_stub_recommend)
    svc._build_seeded_eligibility_rule = MagicMock(side_effect=lambda **kw: _stub_eligibility_rule(
        kw["criterion"], codeset_id=kw["codeset_id"], exclusion=kw["exclusion"],
    ))
    svc._seeded_primary_criteria_key = MagicMock(return_value="ConditionOccurrence")
    svc._patch_codeset_id_in_rule = MagicMock()
    return svc


class TestArtifactEmission:
    """REQ-005: "record, in its emitted artifact metadata, every set ...".

    `_generationCensus` set the precedent -- a count that matters belongs in the
    artifact, emitted by the stage that produced it, rather than recomputed by
    whoever happens to ask later.
    """

    def test_should_emit_detected_clusters_when_the_signal_fires(self, service):
        eligibility = {
            "targetCohortName": "T2DM cohort",
            "inclusionCriteria": [],
            "exclusionCriteria": [
                _criterion(id=11, description=PREGNANCY_STEM, domain="Condition"),
                _criterion(id=12, description=f"{PREGNANCY_STEM} (<= 1 year)", domain="Condition"),
                _criterion(id=18, description=f"{PREGNANCY_STEM} (General)", domain="Condition"),
            ],
        }

        circe = service._build_seeded_target_circe(eligibility)

        assert circe["_restatedClusters"] == [
            {
                "role": "exclusion",
                "domain": "Condition",
                "stem": "Pregnancy/Nursing/Uncontrolled Contraception",
                "criterionIds": [11, 12, 18],
            }
        ]

    def test_should_emit_an_empty_list_when_nothing_clusters(self, service):
        # Present-and-empty rather than absent: an absent key is indistinguishable
        # from an artifact built before this existed. Same contract as
        # `_unmappedCriteria` and `_skippedCriteria`.
        eligibility = {
            "targetCohortName": "T2DM cohort",
            "inclusionCriteria": [
                _criterion(id=1, description="Type 2 diabetes", domain="Condition",
                           logic_type="PRESENCE"),
            ],
            "exclusionCriteria": [],
        }

        circe = service._build_seeded_target_circe(eligibility)

        assert circe["_restatedClusters"] == []
