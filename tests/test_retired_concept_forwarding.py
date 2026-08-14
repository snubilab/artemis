"""A gold set built from retired concepts scored 0.000 whatever the pipeline produced.

TROY's `[TROY condition] substance abuse` is three SNOMED concepts, all retired, none
carrying a CONCEPT_ANCESTOR row: 436954 'Drug abuse' (invalid_reason D), 440069 'Drug
dependence' (U), 4279309 'Substance abuse' (D). Circe resolves that set to exactly those
three ids -- correct for running a cohort, and fatal for comparison, because no set built
from current standard concepts can share a single id with it. The pair's recall was a
measurement of the vocabulary's age.

`standard_replacements` forwards a retired id to the standard concept it was replaced by,
and `forward_retired_concepts` applies that to BOTH sides of the comparison. These tests
pin the two properties that make it a normalisation rather than a thumb on the scale: only
retired ids move, and the retired ids are kept alongside their replacements.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

from conceptset_overlap_eval import ResolvedSet, forward_retired_concepts  # noqa: E402

from src.services.conceptset_closure import PrefetchedVocabulary  # noqa: E402

# The real set, and the standard concepts OMOP forwards it to.
DRUG_ABUSE, DRUG_DEPENDENCE, SUBSTANCE_ABUSE = 436954, 440069, 4279309
HARMFUL_PATTERN, SUBSTANCE_DEPENDENCE = 1448779, 37165431


def _vocab() -> PrefetchedVocabulary:
    return PrefetchedVocabulary(
        concept_invalid_reason={
            DRUG_ABUSE: "D", DRUG_DEPENDENCE: "U", SUBSTANCE_ABUSE: "D",
            HARMFUL_PATTERN: None, SUBSTANCE_DEPENDENCE: None,
        },
        replacement_edges={
            DRUG_ABUSE: {HARMFUL_PATTERN},
            DRUG_DEPENDENCE: {SUBSTANCE_DEPENDENCE},
            SUBSTANCE_ABUSE: {HARMFUL_PATTERN},
        },
    )


def _set(concept_ids: set[int], key: str = "1") -> ResolvedSet:
    return ResolvedSet(key=key, name="substance abuse", concept_ids=set(concept_ids))


def test_should_forward_a_retired_concept_to_its_standard_replacement():
    rs = _set({DRUG_ABUSE})
    changed, replaced = forward_retired_concepts([rs], _vocab())
    assert (changed, replaced) == (1, 1)
    assert rs.concept_ids == {HARMFUL_PATTERN}


def test_should_replace_the_retired_id_rather_than_keep_it_beside_the_replacement():
    """Keeping it grows gold's denominator with ids the pipeline cannot produce.

    Forwarding only ever touches gold in practice -- the pipeline builds from standard
    concepts and emitted no retired id in any of the six trials -- so an additive rule
    would make a gold set unreachable by construction and push recall down. Canonicalising
    is what puts both sides in the same space.
    """
    rs = _set({DRUG_ABUSE})
    forward_retired_concepts([rs], _vocab())
    assert DRUG_ABUSE not in rs.concept_ids


def test_should_leave_a_valid_concept_untouched():
    rs = _set({HARMFUL_PATTERN})
    changed, added = forward_retired_concepts([rs], _vocab())
    assert (changed, added) == (0, 0)
    assert rs.concept_ids == {HARMFUL_PATTERN}


def test_should_not_forward_a_concept_absent_from_the_vocabulary():
    # Absent is unresolvable, not valid. A plain `.get(cid) is None` would read the
    # missing key as "valid" and exempt it silently; it must simply have no replacement.
    rs = _set({999999})
    changed, added = forward_retired_concepts([rs], _vocab())
    assert (changed, added) == (0, 0)
    assert rs.concept_ids == {999999}


def test_should_make_the_real_substance_abuse_pair_overlap_at_all():
    """The case that motivated this: gold retired-only vs generated standard-only."""
    gold = _set({DRUG_ABUSE, DRUG_DEPENDENCE, SUBSTANCE_ABUSE}, key="g")
    generated = _set({HARMFUL_PATTERN}, key="x")
    assert not (gold.concept_ids & generated.concept_ids), "precondition: zero overlap"

    lookup = _vocab()
    forward_retired_concepts([gold], lookup)
    forward_retired_concepts([generated], lookup)

    # Three retired ids canonicalise onto two standard ones.
    assert gold.concept_ids == {HARMFUL_PATTERN, SUBSTANCE_DEPENDENCE}
    shared = gold.concept_ids & generated.concept_ids
    assert shared == {HARMFUL_PATTERN}
    assert len(shared) / len(gold.concept_ids) == 0.5


def test_should_be_a_no_op_without_a_lookup():
    rs = _set({DRUG_ABUSE})
    assert forward_retired_concepts([rs], None) == (0, 0)
    assert rs.concept_ids == {DRUG_ABUSE}
