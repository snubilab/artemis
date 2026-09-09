"""A criterion the extraction gave no window gets its DOMAIN's lookback, and says so.

`window` is MANDATORY in `agent1/prompts.NCT_SYSTEM_PROMPT` and the model omits it
anyway: 57 of the 557 criteria in `tmp/tte_cold6_20260908/studies.json` (10%) carry
`window: null`, in nine of the ten studies (5/49, 14/46, 6/39, 8/85, 4/19, 8/85, 1/8,
0/73, 6/39, 5/114). So the emitter needs a default. What it had was a flat 365-day
lookback applied to every domain alike -- an unnamed literal at the emit site, no
comment, and no record anywhere that a default had fired -- while the prompt documented
four different per-domain values to the model. One decision, two homes, and the
emitter's won silently.

It was wrong in both directions. The measured control pair is two `ConditionOccurrence`
exclusions in one delivered file,
`output/site_gap/2026-09-09/deliver_v3/aristotle_treatment.circe.json`:

    Active infective endocarditis        Start = 9999d   window present in the store
    Prosthetic mechanical heart valve    Start =  365d   window null -> flat default

A prosthetic mechanical heart valve is permanent. "Implanted within the last 365 days"
excludes almost nobody, so that exclusion was effectively not applied and the cohort
silently admitted patients the protocol excludes. In the other direction a Measurement
got 365 where the documented default is 180.

Narrowing is the quiet failure and it is the one these tests are pointed at: a cohort
that empties is noticed at the first generation, a cohort that excludes nobody never is.

Defaulting is kept rather than refusing, unlike the value-filter refusals in the same
builder. A window is a QUALIFIER on a claim, not the claim: refusing would drop an
exclusion the protocol actually made, while emitting the domain's lookback keeps the
claim and only loosens its timing. The value-filter case is the opposite -- emitting
without the threshold turns "ALT > 3x ULN" into "any ALT at all", which inverts the
rule. What defaulting owes in exchange is the record, which is the second half of this
file.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest

from src.agents.agent1 import prompts
from src.services.tte_service import TTEService
from src.utils.circe_lint import (
    DEFAULT_WINDOW_SOURCE_DOMAIN_TABLE,
    DEFAULT_WINDOW_SOURCE_UNLISTED_DOMAIN,
    DEFAULT_WINDOW_START_DAYS_BY_DOMAIN,
    DEFAULTED_WINDOW_CRITERIA_KEY,
    render_default_window_prompt_line,
)

# ARISTOTLE exclusion 3 and its neighbour, the measured pair. Concept ids are real but
# incidental -- nothing here depends on the vocabulary, only on the domain.
ENDOCARDITIS = 4132546
MECHANICAL_VALVE = 4052537


def _stub_concept_set(name: str, domain: str, concept_id: int = 201826) -> dict[str, Any]:
    return {
        "name": name,
        "domain": domain,
        "expression": {
            "items": [
                {
                    "concept": {
                        "CONCEPT_ID": concept_id,
                        "CONCEPT_NAME": name,
                        "CONCEPT_CODE": str(concept_id),
                        "DOMAIN_ID": domain,
                        "VOCABULARY_ID": "SNOMED",
                        "CONCEPT_CLASS_ID": "Clinical Finding",
                    },
                    "includeDescendants": True,
                    "isExcluded": False,
                }
            ]
        },
        "mapping_metadata": None,
    }


def _service(monkeypatch, domain: str) -> TTEService:
    """A service whose mapper answers in `domain`, so the criterion's own domain and the
    mapper's never contradict and `refuse_domain_contradiction` stays out of the way."""
    svc = TTEService.__new__(TTEService)
    monkeypatch.setattr(
        svc,
        "_recommend_seeded_concept_set",
        lambda seed, **kwargs: _stub_concept_set(str(seed).strip(), domain),
    )
    return svc


def _start_window(rule: dict[str, Any]) -> dict[str, Any]:
    return rule["rule"]["expression"]["CriteriaList"][0]["StartWindow"]


class TestTheDefaultIsTheDomainsOwn:
    @pytest.mark.parametrize(
        ("domain", "expected_days"),
        [
            ("Condition", 9999),
            ("Drug", 365),
            ("Measurement", 180),
            ("Procedure", 9999),
        ],
    )
    def test_should_emit_the_documented_lookback_when_the_criterion_carries_no_window(
        self, monkeypatch, domain, expected_days
    ):
        """The four values `NCT_SYSTEM_PROMPT` tells the model to apply. A flat 365 for
        every domain is right for exactly one of these four rows."""
        service = _service(monkeypatch, domain)
        rule = service._build_seeded_eligibility_rule(
            criterion={
                "id": 3,
                "sourceText": "Prosthetic mechanical heart valve",
                "domain": domain,
            },
            codeset_id=11,
            exclusion=True,
        )
        assert _start_window(rule)["Start"] == {"Days": expected_days, "Coeff": -1}
        assert _start_window(rule)["End"] == {"Days": 0, "Coeff": 1}

    def test_should_widen_the_measured_aristotle_exclusion_to_all_prior_history(
        self, monkeypatch
    ):
        """The narrowing half of the control pair, on its own criterion: a permanent
        implant emitted a 365-day lookback, so the exclusion applied to almost nobody."""
        service = _service(monkeypatch, "Condition")
        rule = service._build_seeded_eligibility_rule(
            criterion={
                "id": 3,
                "sourceText": "Prosthetic mechanical heart valve",
                "domain": "Condition",
                "window": None,
            },
            codeset_id=11,
            exclusion=True,
        )
        assert _start_window(rule)["Start"]["Days"] == 9999

    def test_should_leave_the_window_alone_when_the_criterion_carries_one(self, monkeypatch):
        """The control that makes the change above mean something: the OTHER half of the
        measured pair carries a stored window and must not move by one day."""
        service = _service(monkeypatch, "Condition")
        rule = service._build_seeded_eligibility_rule(
            criterion={
                "id": 2,
                "sourceText": "Active infective endocarditis",
                "domain": "Condition",
                "window": {"start": -9999, "end": 0},
            },
            codeset_id=10,
            exclusion=True,
        )
        assert _start_window(rule)["Start"] == {"Days": 9999, "Coeff": -1}

    def test_should_leave_a_short_stored_window_alone_rather_than_widen_it(self, monkeypatch):
        """A stored 90-day window is the protocol's own claim and outranks any default --
        including on a domain whose default is wider."""
        service = _service(monkeypatch, "Condition")
        rule = service._build_seeded_eligibility_rule(
            criterion={
                "id": 7,
                "sourceText": "Stroke within 3 months",
                "domain": "Condition",
                "window": {"start": -90, "end": 0},
            },
            codeset_id=12,
            exclusion=True,
        )
        assert _start_window(rule)["Start"] == {"Days": 90, "Coeff": -1}

    def test_should_fall_back_to_all_prior_history_when_the_domain_is_unlisted(
        self, monkeypatch
    ):
        """The prompt documents four domains and is silent on the rest. An unlisted
        domain takes the reading that cannot silently narrow an unbounded criterion."""
        service = _service(monkeypatch, "Observation")
        rule = service._build_seeded_eligibility_rule(
            criterion={
                "id": 20,
                "sourceText": "Life expectancy under one year",
                "domain": "Observation",
            },
            codeset_id=13,
            exclusion=True,
        )
        assert _start_window(rule)["Start"] == {"Days": 9999, "Coeff": -1}


class TestTheDefaultLeavesARecord:
    def test_should_record_the_default_on_the_criterion_it_fired_for(self, monkeypatch):
        service = _service(monkeypatch, "Condition")
        rule = service._build_seeded_eligibility_rule(
            criterion={
                "id": 3,
                "sourceText": "Prosthetic mechanical heart valve",
                "domain": "Condition",
            },
            codeset_id=11,
            exclusion=True,
        )
        record = rule["_defaulted_window"]
        assert record["window"] == {"start": -9999, "end": 0}
        assert record["domain"] == "Condition"
        assert record["criteriaType"] == "ConditionOccurrence"
        assert record["source"] == DEFAULT_WINDOW_SOURCE_DOMAIN_TABLE

    def test_should_record_nothing_when_the_criterion_carried_its_own_window(self, monkeypatch):
        """A defaulted window used to be indistinguishable from an extracted one. It is
        the ABSENCE of a row here that makes a row mean something."""
        service = _service(monkeypatch, "Condition")
        rule = service._build_seeded_eligibility_rule(
            criterion={
                "id": 2,
                "sourceText": "Active infective endocarditis",
                "domain": "Condition",
                "window": {"start": -9999, "end": 0},
            },
            codeset_id=10,
            exclusion=True,
        )
        assert rule["_defaulted_window"] is None

    def test_should_mark_an_unlisted_domain_as_judged_rather_than_documented(
        self, monkeypatch
    ):
        """Two domains share -9999, so the number alone cannot say which default fired.
        A row carrying this source is the signal that a domain wants a documented value."""
        service = _service(monkeypatch, "Observation")
        rule = service._build_seeded_eligibility_rule(
            criterion={
                "id": 20,
                "sourceText": "Life expectancy under one year",
                "domain": "Observation",
            },
            codeset_id=13,
            exclusion=True,
        )
        assert rule["_defaulted_window"]["source"] == DEFAULT_WINDOW_SOURCE_UNLISTED_DOMAIN


class TestTheRecordReachesTheArtifact:
    """A record the builder returns and the artifact drops is not a record."""

    @pytest.fixture
    def service(self, monkeypatch) -> TTEService:
        svc = TTEService.__new__(TTEService)
        monkeypatch.setattr(
            svc,
            "_recommend_seeded_concept_set",
            lambda seed, **kw: _stub_concept_set(str(seed).strip(), "Condition"),
        )
        return svc

    def test_should_name_the_defaulted_criteria_and_only_those(self, service):
        circe = service._build_seeded_target_circe({
            "targetCohortName": "apixaban",
            "inclusionCriteria": [
                {"id": "inc-1", "domain": "Condition", "sourceText": "Atrial fibrillation",
                 "window": {"start": -9999, "end": 0}},
            ],
            "exclusionCriteria": [
                {
                    "id": "exc-3",
                    "domain": "Condition",
                    "sourceText": "Prosthetic mechanical heart valve",
                },
            ],
        })
        rows = circe[DEFAULTED_WINDOW_CRITERIA_KEY]
        assert [(r["role"], r["criterionId"]) for r in rows] == [("exclusion", "exc-3")]
        assert rows[0]["label"] == "Prosthetic mechanical heart valve"
        assert rows[0]["window"] == {"start": -9999, "end": 0}

    def test_should_report_an_empty_list_when_every_criterion_carried_a_window(self, service):
        """Present-and-empty, like `_droppedCriteria`: an absent key would be
        indistinguishable from an artifact built before the record existed."""
        circe = service._build_seeded_target_circe({
            "targetCohortName": "apixaban",
            "inclusionCriteria": [
                {"id": "inc-1", "domain": "Condition", "sourceText": "Atrial fibrillation",
                 "window": {"start": -9999, "end": 0}},
            ],
            "exclusionCriteria": [],
        })
        assert circe[DEFAULTED_WINDOW_CRITERIA_KEY] == []


class TestTheNumbersHaveOneHome:
    """The prompt is a string and cannot import an int -- but it can be BUILT from one."""

    PROMPTS_SOURCE = Path(prompts.__file__)

    def test_should_render_every_prompt_statement_from_the_table(self):
        four = render_default_window_prompt_line(
            [["Condition"], ["Drug"], ["Measurement"], ["Procedure"]]
        )
        collapsed = render_default_window_prompt_line(
            [["Condition", "Procedure"], ["Drug"], ["Measurement"]], escape_braces=True
        )
        assert prompts.SYSTEM_PROMPT.count(four) == 1
        assert prompts.NCT_SYSTEM_PROMPT.count(four) == 1
        assert prompts.DECOMPOSITION_PROMPT.count(collapsed) == 1
        assert prompts.NCT_DECOMPOSITION_PROMPT.count(collapsed) == 1

    def test_should_leave_no_retyped_domain_default_in_the_prompt_source(self):
        """The gate that keeps the count at one home. A fifth copy of these numbers is
        the defect, not the fix -- the two that existed disagreed and nothing compared
        them, which is exactly why a retyped copy has to fail here rather than at a
        hospital.

        Scoped to lines that STATE the domain table. `prompts.py` also carries two
        worked examples reading `Pattern D -- "History of X" -> window: {{start: -9999,
        end: 0}}`; those are a per-pattern instruction about what "history of" means,
        not a restatement of Condition's default, and they would stay correct if the
        table moved. Widening this gate to every `-9999` in the file would fail on them
        and teach the next reader to delete the gate.
        """
        source = io.open(self.PROMPTS_SOURCE, encoding="utf-8").read()
        offenders = [
            line.strip()
            for line in source.splitlines()
            if "default" in line.lower() and "start: -" in line
        ]
        assert offenders == [], offenders

    def test_should_refuse_to_collapse_two_domains_whose_defaults_disagree(self, monkeypatch):
        """Shown a broken case, because a gate never fired is a gate never tested. The
        collapsed rendering claims Condition and Procedure share a value; if one is
        changed without the other, the model must not be told a false claim."""
        monkeypatch.setitem(DEFAULT_WINDOW_START_DAYS_BY_DOMAIN, "Procedure", -730)
        with pytest.raises(ValueError) as excinfo:
            render_default_window_prompt_line([["Condition", "Procedure"]])
        assert "Condition/Procedure" in str(excinfo.value)
        assert "-730" in str(excinfo.value)
