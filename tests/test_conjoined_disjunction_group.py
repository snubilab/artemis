"""LEADER rule 2, a disjunction emitted as a conjunction, read by an independent check.

The 2026-09-11 conversion audit's largest logical-defect class was AND/OR inversion; its
clearest case is LEADER store group `4a712697`, `groupType: "ALL"` under the line
"Anti-diabetic drug naive or treated with one or more oral anti-diabetic drugs (OADs) or
treated with human NPH insulin ...", delivered as `InclusionRules[2]`.

This file used to also pin the rule that repaired it by reading "or" / "either" in the
group's protocol line (`circe_lint.states_flat_disjunction`, `list_cardinality`, the
`conjoined_disjunction_rules` gate (o), and `tte_service._effective_group_type`'s ALL->ANY
branch). That rule read natural language to decide grouping and is removed (RFC-016 step 2,
inventory A18): the group's Type now comes from the relation its label states, verified
against the line (`tests/test_relation_timing_build.py`). What stays is the measurement
that does not depend on how the Type is decided: flipping rule 2 to ANY is what makes it
satisfiable, as an independent check (gate (n)) reads it.
"""

from __future__ import annotations

import copy
import json
import pathlib

import pytest

from src.utils.circe_lint import aliased_concept_sets, contradictory_presence_absence_criteria

REPO = pathlib.Path(__file__).resolve().parents[1]
BATCH = REPO / "output" / "site_gap" / "2026-09-14" / "DELIVERY"


@pytest.mark.skipif(not BATCH.is_dir(), reason=f"delivered batch not present: {BATCH}")
class TestAgainstTheDeliveredBatch:
    def test_flipping_leader_rule_2_to_any_makes_it_satisfiable(self):
        """The direct answer to "does rule 2 become satisfiable", read by an
        INDEPENDENT check rather than by the one added here.

        `_conjoined_entries` does not descend into `ANY`, so after the flip the
        codeset-10 / codeset-11 pair is no longer a conjunction and
        `contradictory_presence_absence_criteria` stops reporting it. A patient with
        zero OAD exposures now satisfies the rule through its first alternative,
        which is what the protocol line asks for.

        All FOUR findings go, not one, and the reason is worth stating rather than
        glossing: every presence the check pairs against lives in rule 2, so the two
        `InclusionRules[24]` findings -- the separate dropped-negation defect, where
        codesets 54 and 56 named "insulin other than X" hold the identical 26 ids as
        codeset 12 -- stop being PROVABLE contradictions once rule 2's presences stop
        being mandatory. The negation defect itself is untouched by the flip, and
        `aliased_concept_sets` still reports it. A reader who took the empty list as
        "rule 24 is fixed" would be reading this backwards."""
        expression = json.loads((BATCH / "leader_treatment.circe.json").read_text())
        before = contradictory_presence_absence_criteria(expression)
        internal = [f for f in before if "codeset 10" in f and "codeset 11" in f]
        assert len(internal) == 1, before
        assert len(before) == 4, before

        flipped = copy.deepcopy(expression)
        flipped["InclusionRules"][2]["expression"]["Type"] = "ANY"

        assert contradictory_presence_absence_criteria(flipped) == []
        assert len(aliased_concept_sets(flipped)) == 1, "the negation defect remains"
