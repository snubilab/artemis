"""Two mapper calls instead of one, with the mapper stubbed.

The single call is the defect. Handed the whole string "insulin other than human
NPH insulin", the mapper returns the NPH set -- `_criterionMappingMetadata` in
the store records `queryUsed` verbatim as that whole string, and the delivered
codeset 54 holds codeset 12's 26 ids byte for byte.

No live LLM or embedding here: `map_phrase` is injected. End-to-end behaviour is
NOT covered by this file and is not claimed to be.
"""

from src.services.entity_exception import detect_entity_exception
from src.services.entity_subtraction import resolve_entity_exception

LEADER_NPH = [1513843, 1516976, 35198096, 35602717]
LEADER_OTHER = [1502905, 1550023]


def _mapping(name, ids):
    return {
        "name": name,
        "domain": "Drug",
        "expression": {"items": [
            {"concept": {"CONCEPT_ID": cid, "CONCEPT_NAME": f"c{cid}"},
             "isExcluded": False, "includeDescendants": True} for cid in ids]},
    }


def _stub(table):
    def map_phrase(phrase):
        if phrase not in table:
            raise LookupError(f"no mapping for {phrase!r}")
        return _mapping(phrase, table[phrase])
    return map_phrase


class TestTheRepairedLeaderCase:
    """What the two-call design produces once the mapper stops returning a
    generic insulin class for 'human NPH insulin'."""

    def test_the_excepted_concepts_are_excluded_and_the_rest_survive(self):
        exception = detect_entity_exception("insulin other than human NPH insulin")
        result = resolve_entity_exception(exception, _stub({
            "insulin": LEADER_NPH + LEADER_OTHER,
            "human NPH insulin": LEADER_NPH,
        }))
        assert result.fallback_reason == ""
        items = result.mapping["expression"]["items"]
        excluded = sorted(i["concept"]["CONCEPT_ID"] for i in items if i["isExcluded"])
        included = sorted(i["concept"]["CONCEPT_ID"] for i in items if not i["isExcluded"])
        assert excluded == sorted(LEADER_NPH)
        assert included == sorted(LEADER_OTHER)

    def test_the_concept_set_keeps_the_criterion_s_own_name(self):
        exception = detect_entity_exception("insulin other than human NPH insulin")
        result = resolve_entity_exception(exception, _stub({
            "insulin": LEADER_NPH + LEADER_OTHER, "human NPH insulin": LEADER_NPH}))
        assert result.mapping["name"] == "insulin other than human NPH insulin"


class TestEveryFailureFallsBack:
    """A partial subtraction is a claim the pipeline cannot support. Falling back
    leaves the existing over-inclusion, which the negation lints still see."""

    def test_a_base_that_does_not_map(self):
        exception = detect_entity_exception("insulin other than human NPH insulin")
        result = resolve_entity_exception(exception, _stub({"human NPH insulin": LEADER_NPH}))
        assert result.mapping is None
        assert "base phrase 'insulin' did not map" in result.fallback_reason

    def test_an_excepted_phrase_that_does_not_map(self):
        exception = detect_entity_exception("insulin other than human NPH insulin")
        result = resolve_entity_exception(exception, _stub({"insulin": LEADER_NPH + LEADER_OTHER}))
        assert result.mapping is None
        assert "excepted phrase 'human NPH insulin' did not map" in result.fallback_reason

    def test_an_excepted_phrase_that_maps_to_nothing(self):
        exception = detect_entity_exception("insulin other than human NPH insulin")
        result = resolve_entity_exception(exception, _stub({
            "insulin": LEADER_NPH + LEADER_OTHER, "human NPH insulin": []}))
        assert result.mapping is None
        assert "mapped to no concepts" in result.fallback_reason

    def test_a_base_and_excepted_that_collapse_onto_the_same_set(self):
        """The shape the 2026-09-14 delivery actually shipped. Codeset 12
        'human NPH insulin' holds a generic insulin class, so mapping 'insulin'
        and 'human NPH insulin' separately is expected to return it twice."""
        exception = detect_entity_exception("insulin other than human NPH insulin")
        result = resolve_entity_exception(exception, _stub({
            "insulin": LEADER_NPH, "human NPH insulin": LEADER_NPH}))
        assert result.mapping is None
        assert "mapped to its own exception" in result.fallback_reason

    def test_a_multi_entity_exception_needs_every_phrase_to_map(self):
        exception = detect_entity_exception(
            "antidiabetic drugs (excluding GLP-1/DPP-4/SGLT-2)")
        result = resolve_entity_exception(exception, _stub({
            "antidiabetic drugs": [1, 2, 3, 4], "GLP-1": [1], "DPP-4": [2]}))
        assert result.mapping is None
        assert "excepted phrase 'SGLT-2' did not map" in result.fallback_reason

    def test_every_phrase_mapping_subtracts_the_union(self):
        exception = detect_entity_exception(
            "antidiabetic drugs (excluding GLP-1/DPP-4/SGLT-2)")
        result = resolve_entity_exception(exception, _stub({
            "antidiabetic drugs": [1, 2, 3, 4], "GLP-1": [1], "DPP-4": [2], "SGLT-2": [3]}))
        assert result.fallback_reason == ""
        items = result.mapping["expression"]["items"]
        assert sorted(i["concept"]["CONCEPT_ID"] for i in items if i["isExcluded"]) == [1, 2, 3]


class TestTheServiceCallsItOnce:
    """The seeded mapper recurses for the two halves; the recursion must
    terminate and must not re-enter on the sub-phrases."""

    def test_the_base_phrase_carries_no_exception_of_its_own(self):
        exception = detect_entity_exception("insulin other than human NPH insulin")
        assert detect_entity_exception(exception.base) is None
        for phrase in exception.excepted:
            assert detect_entity_exception(phrase) is None


class TestThroughTheServiceMethod:
    """The real branch in `TTEService._recommend_seeded_concept_set`, with only
    the inner per-phrase mapping stubbed. No LLM, no embedding, no database."""

    @staticmethod
    def _service(table):
        from unittest.mock import MagicMock

        from src.services.tte_service import TTEService

        class _Stubbed(TTEService):
            calls: list = []

            def _recommend_seeded_concept_set(self, seed_text, **kwargs):
                if kwargs.get("resolving_entity_exception"):
                    self.calls.append(seed_text)
                    if seed_text not in table:
                        raise LookupError(f"no mapping for {seed_text!r}")
                    return _mapping(seed_text, table[seed_text])
                return super()._recommend_seeded_concept_set(seed_text, **kwargs)

        svc = _Stubbed(store=MagicMock())
        svc.calls = []
        return svc

    def test_the_whole_phrase_is_never_mapped_as_one_string(self):
        svc = self._service({"insulin": LEADER_NPH + LEADER_OTHER,
                             "human NPH insulin": LEADER_NPH})
        svc._recommend_seeded_concept_set(
            "insulin other than human NPH insulin", expected_domain="Drug")
        assert svc.calls == ["insulin", "human NPH insulin"]

    def test_the_returned_set_carries_the_exclusions(self):
        svc = self._service({"insulin": LEADER_NPH + LEADER_OTHER,
                             "human NPH insulin": LEADER_NPH})
        result = svc._recommend_seeded_concept_set(
            "insulin other than human NPH insulin", expected_domain="Drug")
        items = result["expression"]["items"]
        excluded = sorted(i["concept"]["CONCEPT_ID"] for i in items if i["isExcluded"])
        assert excluded == sorted(LEADER_NPH)
        assert result["name"] == "insulin other than human NPH insulin"

    # A plain seed must not enter the branch at all. Asserted on the parser
    # (TestTheServiceCallsItOnce) rather than here: calling the service method
    # with a non-exception seed runs the real Agent 2 pipeline -- Neo4j, Chroma
    # and an LLM critic -- which this file must not do.
