"""Turning a parsed entity exception into `isExcluded` items.

The two halves meet here, the same shape as `route_qualifier` ->
`route_subtraction`: :mod:`entity_exception` says which entity the criterion
asked to leave out, the mapper says which concepts that entity is, and this
decides what the concept set carries as `isExcluded`.

Every fixture below is real. The CAROLINA ids are the 20 members of the
delivered `carolina_treatment.circe.json` codeset 45; which 19 of them are
non-melanoma skin cancers was decided by `concept_ancestor` in
`synthea_cdm_benchmark` (descendant of 4155297 `Malignant neoplasm of skin` or
444209 `Neoplasm of skin`, and not of 141232 `Malignant melanoma of skin`), not
by reading the names. The LEADER ids are codeset 12's 26 members.
"""

from src.services.entity_subtraction import ExceptedConcept, apply_entity_subtraction

# codeset 45, verbatim from output/site_gap/2026-09-14/DELIVERY/carolina_treatment.circe.json
CAROLINA_45 = [
    (606563, "Carcinoma of meibomian gland"),
    (761019, "Merkel cell carcinoma of neck"),
    (761035, "Torré-Muir syndrome co-occurrent with malignant sebaceous neoplasm"),
    (766258, "Exacerbation of non-melanoma skin malignancy"),
    (4031105, "Melanoma in situ of non-skin site"),
    (4111932, "Adenoid cystic eccrine carcinoma of skin"),
    (4111933, "Mucoepidermoid carcinoma of skin"),
    (4112744, "Acantholytic squamous cell carcinoma of skin"),
    (4113636, "Carcinoma of skin of head/neck"),
    (4129078, "Neoplasm of skin of face"),
    (4155296, "Carcinoma of skin of trunk"),
    (4216914, "Keratoacanthoma of skin"),
    (4295624, "Squamous cell carcinoma of skin of ear"),
    (4298028, "Squamous cell carcinoma of skin of lower extremity"),
    (4298128, "Apocrine adenocarcinoma of skin"),
    (4300557, "Squamous cell carcinoma of skin of trunk"),
    (4300574, "Ceruminous gland adenocarcinoma"),
    (4308621, "Squamous cell carcinoma of skin of neck"),
    (37018963, "Primary adenocarcinoma of skin"),
    (40487139, "Carcinoma of skin of anus"),
]
# The 19 the vocabulary places under skin neoplasm and not under melanoma.
CAROLINA_NMSC = [cid for cid, _ in CAROLINA_45 if cid != 4031105]

# codeset 12 'human NPH insulin', which codesets 54 and 56 duplicate byte for byte.
LEADER_12 = [
    1513843, 1513876, 1516976, 1531601, 1544838, 1562586, 1586346, 1586369,
    1588986, 1590165, 19013926, 19013951, 19090180, 19090187, 19090204,
    19090221, 19090226, 19090229, 19090244, 19090247, 19090249, 19091621,
    35198096, 35602717, 40170911, 44506754,
]


def _items(pairs):
    return [{"concept": {"CONCEPT_ID": cid, "CONCEPT_NAME": name, "DOMAIN_ID": "Condition"},
             "isExcluded": False, "includeDescendants": True, "includeMapped": False}
            for cid, name in pairs]


def _excluded_ids(items):
    return sorted(i["concept"]["CONCEPT_ID"] for i in items if i.get("isExcluded"))


def _included_ids(items):
    return sorted(i["concept"]["CONCEPT_ID"] for i in items if not i.get("isExcluded"))


class TestCarolinaCodeset45:
    """'cancer other than non-melanoma skin cancer', 20 items, 0 excluded as
    delivered. Nineteen of the twenty ARE non-melanoma skin cancers."""

    def test_the_nineteen_non_melanoma_skin_cancers_become_excluded(self):
        result = apply_entity_subtraction(
            _items(CAROLINA_45),
            [ExceptedConcept(cid, "") for cid in CAROLINA_NMSC],
        )
        assert result.refused == ""
        assert _excluded_ids(result.items) == sorted(CAROLINA_NMSC)
        assert len(result.excluded_in_place) == 19
        assert result.appended == []

    def test_only_melanoma_in_situ_of_non_skin_site_is_still_included(self):
        result = apply_entity_subtraction(
            _items(CAROLINA_45),
            [ExceptedConcept(cid, "") for cid in CAROLINA_NMSC],
        )
        assert _included_ids(result.items) == [4031105]

    def test_a_patient_with_only_squamous_cell_carcinoma_of_skin_is_no_longer_matched(self):
        """The question this whole change exists to answer. 4295624 'Squamous
        cell carcinoma of skin of ear' is currently an included member of an
        ABSENCE rule, so such a patient is removed from the cohort. After the
        subtraction it is excluded, so the set no longer matches them."""
        result = apply_entity_subtraction(
            _items(CAROLINA_45),
            [ExceptedConcept(cid, "") for cid in CAROLINA_NMSC],
        )
        scc = next(i for i in result.items if i["concept"]["CONCEPT_ID"] == 4295624)
        assert scc["isExcluded"] is True
        assert 4295624 not in _included_ids(result.items)


class TestLeaderCodeset54:
    """'insulin other than human NPH insulin' whose 26 members are codeset 12's
    26 members. The subtraction must refuse, not empty the set."""

    def test_a_base_identical_to_the_excepted_set_is_refused(self):
        result = apply_entity_subtraction(
            _items([(cid, "") for cid in LEADER_12]),
            [ExceptedConcept(cid, "") for cid in LEADER_12],
        )
        assert result.refused != ""
        assert result.excluded_in_place == []
        assert result.appended == []

    def test_a_refusal_changes_nothing(self):
        """Emitting a set whose every member is excluded resolves to the empty
        set -- a different wrong answer, not a repair. The over-inclusion is
        left in place so the defect stays visible."""
        original = _items([(cid, "") for cid in LEADER_12])
        result = apply_entity_subtraction(
            original, [ExceptedConcept(cid, "") for cid in LEADER_12])
        assert _excluded_ids(result.items) == []
        assert _included_ids(result.items) == sorted(LEADER_12)

    def test_a_correctly_mapped_base_subtracts_normally(self):
        """What the two-call wiring produces: base = the insulin class, excepted
        = the NPH set. Real non-NPH RxNorm ingredient ids."""
        broader = [(cid, "") for cid in LEADER_12] + [
            (1502905, "insulin glargine"), (1550023, "insulin lispro"),
        ]
        result = apply_entity_subtraction(
            _items(broader), [ExceptedConcept(cid, "") for cid in LEADER_12])
        assert result.refused == ""
        assert _included_ids(result.items) == [1502905, 1550023]
        assert len(result.excluded_in_place) == 26


class TestAnExceptedConceptTheBaseDoesNotLiterallyCarry:
    """Circe resolves an exclusion as an anti-join over the RESOLVED closure, so
    an excepted ancestor need not be a literal member to remove leaves. Gold
    relies on exactly this: its `[CKim] systemic glucocorticoid` set carries 136
    excluded `Clinical Drug Form` items with includeDescendants, covering
    thousands of leaves."""

    def test_it_is_appended_as_an_excluded_item_with_descendants(self):
        result = apply_entity_subtraction(
            _items([(4155297, "Malignant neoplasm of skin")]),
            [ExceptedConcept(141232, "Malignant melanoma of skin")],
        )
        assert result.refused == ""
        assert result.appended == [141232]
        appended = next(i for i in result.items if i["concept"]["CONCEPT_ID"] == 141232)
        assert appended["isExcluded"] is True
        assert appended["includeDescendants"] is True

    def test_a_concept_already_carried_is_flipped_not_duplicated(self):
        result = apply_entity_subtraction(
            _items(CAROLINA_45), [ExceptedConcept(4295624, "")])
        ids = [i["concept"]["CONCEPT_ID"] for i in result.items]
        assert ids.count(4295624) == 1
        assert result.appended == []
        assert result.excluded_in_place == [4295624]


class TestNoOps:

    def test_no_excepted_concepts_changes_nothing(self):
        result = apply_entity_subtraction(_items(CAROLINA_45), [])
        assert result.refused == ""
        assert _excluded_ids(result.items) == []
        assert len(result.items) == 20

    def test_no_base_items_changes_nothing(self):
        result = apply_entity_subtraction([], [ExceptedConcept(141232, "x")])
        assert result.items == []
        assert result.appended == []

    def test_an_already_excluded_base_item_is_not_counted_twice(self):
        items = _items(CAROLINA_45)
        items[0]["isExcluded"] = True
        result = apply_entity_subtraction(items, [ExceptedConcept(606563, "")])
        assert result.excluded_in_place == []
        assert result.appended == []
