"""An exception the criterion's description states, carried to a seed that dropped it.

The 2026-09-23 delivery's ``empa-reg_treatment.circe.json`` returns 0 people on any
CDM. Rule #2 requires a T2DM diagnosis (codeset 2: 201826, 44793113, both with
descendants); rule #15 'Endocrine disorder (excluding T2DM)' forbids codeset 29, which
carries 201820 'Diabetes mellitus' with descendants and ZERO ``isExcluded`` members --
and 201826 / 44793113 are descendants of 201820.

The entity-exception path already turns "X (excluding Y)" into ``isExcluded`` members,
but it reads only the mapper SEED, and for this criterion the seed is
``sourceText`` = "Endocrine disorder" while the exception lives in
``description`` = "Endocrine disorder (excluding T2DM)". The parser never saw it.

``protocolLine`` is deliberately NOT read: measured over the whole store, the exception
on a protocol line usually belongs to a different entity on the same line.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.services.entity_exception import description_stated_exception
from src.services.tte_service import TTEService
from src.utils.criterion_seed import criterion_mapper_seed

REPO = Path(__file__).resolve().parents[1]
STORE = REPO / "output" / "site_gap" / "2026-09-22_verify5" / "store" / "studies.json"

T2DM = [201826, 44793113]
ENDOCRINE = [23986, 192963, 201820, 4028942]

# studies[7] exclusion #30 in the verify5 store, verbatim.
EMPA_REG_EXCLUSION_30 = {
    "id": 30,
    "description": "Endocrine disorder (excluding T2DM)",
    "domain": "Condition",
    "valueConstraint": None,
    "sourceText": "Endocrine disorder",
    "protocolLine": "Any uncontrolled endocrine disorder except type 2 diabetes",
    "window": {"start": -9999, "end": 0},
    "logicType": "ABSENCE",
}


class TestThePredicate:
    def test_should_carry_the_exception_when_the_description_base_is_the_seed(self):
        exception = description_stated_exception(
            "Endocrine disorder", "Endocrine disorder (excluding T2DM)"
        )
        assert exception is not None
        assert exception.base == "Endocrine disorder"
        assert exception.excepted == ["T2DM"]
        assert exception.text == "Endocrine disorder (excluding T2DM)"

    def test_should_map_the_seed_not_the_wider_base_when_the_base_qualifies_it(self):
        """'Uncontrolled' is a qualifier the seed dropped; restoring it is not this fix."""
        exception = description_stated_exception(
            "Endocrine disorder", "Uncontrolled endocrine disorder (other than T2DM)"
        )
        assert exception is not None
        assert exception.base == "Endocrine disorder"
        assert exception.excepted == ["T2DM"]

    def test_should_match_the_seed_case_and_whitespace_insensitively_when_comparing(self):
        exception = description_stated_exception(
            "endocrine   disorder", "Endocrine Disorder (excluding T2DM)"
        )
        assert exception is not None
        assert exception.base == "endocrine disorder"

    def test_should_return_none_when_the_seed_states_its_own_exception(self):
        """The existing path already reads that one; two readers would map it twice."""
        assert description_stated_exception(
            "insulin other than human NPH insulin",
            "insulin other than human NPH insulin (excluding premixed insulin)",
        ) is None

    def test_should_return_none_when_the_exception_belongs_to_another_entity(self):
        """studies[9] exclusion #65's shape: the line's exception is not about the seed."""
        assert description_stated_exception(
            "Patient reliability or life expectancy",
            "Cancer other than non-melanoma skin cancer",
        ) is None

    def test_should_return_none_when_the_description_states_no_exception(self):
        assert description_stated_exception("Endocrine disorder", "Endocrine disorder") is None

    @pytest.mark.parametrize("seed", ["", "   ", None])
    def test_should_return_none_when_the_seed_is_empty(self, seed):
        assert description_stated_exception(seed, "Endocrine disorder (excluding T2DM)") is None


@pytest.mark.skipif(not STORE.is_file(), reason=f"store not present: {STORE}")
class TestTheScopeOverTheRealStore:
    def test_should_fire_only_on_the_empa_reg_endocrine_rows_when_run_over_the_store(self):
        studies = json.loads(STORE.read_text())["studies"]
        fired = []
        for index, study in enumerate(studies):
            eligibility = study.get("eligibility") or {}
            for role in ("inclusion", "exclusion"):
                for criterion in eligibility.get(f"{role}Criteria") or []:
                    seed = criterion_mapper_seed(criterion)
                    if description_stated_exception(seed, criterion.get("description")):
                        fired.append((index, role, criterion.get("id"), criterion.get("mappable")))
        # #29 is the group label; only #30 ever reaches the mapper.
        assert fired == [(7, "exclusion", 29, False), (7, "exclusion", 30, True)]


def _stub_mapping(name, ids):
    return {
        "name": name,
        "domain": "Condition",
        "expression": {"items": [
            {"concept": {"CONCEPT_ID": cid, "CONCEPT_NAME": f"c{cid}", "DOMAIN_ID": "Condition"},
             "isExcluded": False, "includeDescendants": True, "includeMapped": False}
            for cid in ids]},
        "mapping_metadata": None,
    }


class TestTheRuleBuilderHandsItToTheMapper:
    @staticmethod
    def _capturing_service(monkeypatch):
        svc = TTEService.__new__(TTEService)
        seen: list[tuple[str, dict]] = []

        def _record(seed, **kwargs):
            seen.append((seed, kwargs))
            return _stub_mapping(seed, ENDOCRINE)

        monkeypatch.setattr(svc, "_recommend_seeded_concept_set", _record)
        return svc, seen

    def test_should_pass_the_description_exception_when_the_seed_is_its_base(self, monkeypatch):
        svc, seen = self._capturing_service(monkeypatch)
        svc._build_seeded_eligibility_rule(
            criterion=EMPA_REG_EXCLUSION_30, codeset_id=29, exclusion=True)
        [(seed, kwargs)] = seen
        assert seed == "Endocrine disorder"
        exception = kwargs.get("entity_exception")
        assert exception is not None
        assert (exception.base, exception.excepted) == ("Endocrine disorder", ["T2DM"])

    def test_should_pass_no_exception_when_the_description_states_none(self, monkeypatch):
        svc, seen = self._capturing_service(monkeypatch)
        criterion = dict(EMPA_REG_EXCLUSION_30, description="Endocrine disorder")
        svc._build_seeded_eligibility_rule(criterion=criterion, codeset_id=29, exclusion=True)
        [(_seed, kwargs)] = seen
        assert kwargs.get("entity_exception") is None


class _ResolvingStub(TTEService):
    """Stubs only the per-phrase mapping calls the exception branch makes."""

    table: dict = {}
    calls: list = []

    def _recommend_seeded_concept_set(self, seed_text, **kwargs):
        if kwargs.get("resolving_entity_exception"):
            self.calls.append(seed_text)
            if seed_text not in self.table:
                raise LookupError(f"no mapping for {seed_text!r}")
            return _stub_mapping(seed_text, self.table[seed_text])
        return super()._recommend_seeded_concept_set(seed_text, **kwargs)


class TestTheMapperAppliesIt:
    @staticmethod
    def _service(table):
        svc = _ResolvingStub(store=MagicMock())
        svc.table = table
        svc.calls = []
        return svc

    def test_should_map_seed_and_excepted_phrase_separately_when_handed_an_exception(self):
        svc = self._service({"Endocrine disorder": ENDOCRINE, "T2DM": T2DM})
        exception = description_stated_exception(
            "Endocrine disorder", "Endocrine disorder (excluding T2DM)")
        result = svc._recommend_seeded_concept_set(
            "Endocrine disorder", expected_domain="Condition", entity_exception=exception)
        assert svc.calls == ["Endocrine disorder", "T2DM"]
        items = result["expression"]["items"]
        assert sorted(i["concept"]["CONCEPT_ID"] for i in items if i["isExcluded"]) == T2DM
        assert sorted(i["concept"]["CONCEPT_ID"] for i in items if not i["isExcluded"]) == ENDOCRINE
        assert result["name"] == "Endocrine disorder (excluding T2DM)"

    def test_should_map_the_seed_alone_and_warn_when_the_excepted_phrase_does_not_map(
        self, monkeypatch, caplog
    ):
        """The existing fall-back-and-warn behaviour, unchanged: no half-applied set."""
        monkeypatch.setenv("CRITERION_CACHE_ENABLED", "false")
        svc = self._service({"Endocrine disorder": ENDOCRINE})
        asked: list[str] = []

        def _process(query_text, **kwargs):
            asked.append(query_text)
            raise RuntimeError("stubbed agent 2")

        marker = _stub_mapping("whole seed", ENDOCRINE)
        monkeypatch.setattr(
            svc, "_recommend_seeded_concept_set_rag_fallback", lambda seed, **kw: marker)
        exception = description_stated_exception(
            "Endocrine disorder", "Endocrine disorder (excluding T2DM)")

        with caplog.at_level(logging.WARNING):
            result = svc._recommend_seeded_concept_set(
                "Endocrine disorder",
                expected_domain="Condition",
                workflow=SimpleNamespace(process_with_details=_process),
                entity_exception=exception,
            )
        assert result is marker
        assert asked == ["Endocrine disorder"]
        assert "NOT applied" in caplog.text
        assert "excepted phrase 'T2DM' did not map" in caplog.text
