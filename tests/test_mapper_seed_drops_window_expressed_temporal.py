"""The seed handed to the mapper carries no temporal qualifier the ``window`` holds.

Four CARMELINA rows shipped 2026-09-09 as ``intent-unparsed``::

    [9] excl #13  window={start: -1095, end: 0}
                  description='Cancer other than nonmelanoma skin cancer within 3 years'
    [9] incl #10  'Drug-naïve or pre-treated excluding GLP-1/DPP-4/SGLT-2 inhibitors (7 days)'
    [9] incl #11  '... inhibitors (>= 7 days)'
    [9] incl #13  'Stable background medication for 8 weeks prior to randomization (...)'

The window on each of them is CORRECT — extraction converted the qualifier to days and
stored it. The defect is that the same qualifier is still in the text handed to the
mapper, where :func:`src.agents.conceptset.nlu_router.detect_temporal_negation` sees
``within`` / ``days`` / ``prior`` and refuses to route it at all. The number is asserted
twice and only the second assertion breaks anything.

The gate that matters is the last class here: the real detector that produced the
refusal is run over the real seeds, rather than a synthetic string that merely looks
similar.
"""
from __future__ import annotations

import pytest

from src.utils.criterion_seed import criterion_mapper_seed, strip_window_expressed_temporal


def _crit(text: str, *, window: dict | None = {"start": -365, "end": 0}, source: str = ""):
    return {"sourceText": source, "description": text, "window": window}


class TestTheQualifierTheWindowAlreadyHoldsIsDropped:
    @pytest.mark.parametrize(
        "text,expected",
        [
            (
                "Cancer other than nonmelanoma skin cancer within 3 years",
                "Cancer other than nonmelanoma skin cancer",
            ),
            (
                "Drug-naïve or pre-treated excluding GLP-1/DPP-4/SGLT-2 inhibitors (7 days)",
                "Drug-naïve or pre-treated excluding GLP-1/DPP-4/SGLT-2 inhibitors",
            ),
            (
                "Drug-naïve or pre-treated excluding GLP-1/DPP-4/SGLT-2 inhibitors (>= 7 days)",
                "Drug-naïve or pre-treated excluding GLP-1/DPP-4/SGLT-2 inhibitors",
            ),
            (
                "Stable background medication for 8 weeks prior to randomization "
                "(Insulin change <= 10%)",
                "Stable background medication (Insulin change <= 10%)",
            ),
            ("Stable background medication for 8 weeks prior to screening",
             "Stable background medication"),
            ("CABG within 2 months prior to consent", "CABG"),
            ("Fibrinolytic therapy within 24 hours", "Fibrinolytic therapy"),
            ("Use of other insulin within 3 months", "Use of other insulin"),
            ("Bariatric surgery in the past 12 months", "Bariatric surgery"),
            ("Myocardial infarction 30 days prior to randomisation", "Myocardial infarction"),
        ],
    )
    def test_should_drop_the_duration_when_the_window_carries_it(self, text, expected):
        assert strip_window_expressed_temporal(text) == expected


class TestANumberThatIsNotADurationSurvives:
    """A bound the window does NOT express is not a temporal qualifier."""

    @pytest.mark.parametrize(
        "text",
        [
            "Age >= 18 years",            # a Demographics bound, not a lookback
            "Life expectancy < 5 years",  # a forward prognosis, not a lookback
            "History of MEN2 or FMT2",
            "Prior stroke, TIA or systemic embolus",
            "Previous MI or CABG",
            "PCI after index event",
            "Cv Prior (OR group)",
            "At least two CV risk factors",
            "Pre-planned coronary artery re-vascularisation (PCI, CABG) or any previous PCI and/or",
        ],
    )
    def test_should_return_the_seed_byte_identical_when_nothing_temporal_matched(self, text):
        assert strip_window_expressed_temporal(text) == text


class TestTheSeedIsNeverLeftEmptyOrUnanchored:
    def test_should_keep_the_original_when_stripping_would_leave_no_entity(self):
        assert strip_window_expressed_temporal("within 3 years") == "within 3 years"

    def test_should_keep_the_original_when_the_criterion_has_no_window_to_carry_it(self):
        crit = _crit("Cancer other than nonmelanoma skin cancer within 3 years", window=None)
        assert criterion_mapper_seed(crit) == (
            "Cancer other than nonmelanoma skin cancer within 3 years"
        )

    def test_should_return_empty_for_a_criterion_with_neither_field(self):
        assert criterion_mapper_seed({"sourceText": "", "description": ""}) == ""


class TestTheSeedFieldPrecedenceIsUnchanged:
    def test_should_prefer_source_text_when_it_is_present(self):
        crit = _crit("Cancer other than nonmelanoma skin cancer within 3 years", source="Cancer")
        assert criterion_mapper_seed(crit) == "Cancer"

    def test_should_fall_back_to_description_when_source_text_is_empty(self):
        crit = _crit("Cancer other than nonmelanoma skin cancer within 3 years")
        assert criterion_mapper_seed(crit) == "Cancer other than nonmelanoma skin cancer"


class TestTheRealRouterNoLongerRefusesTheFourCarmelinaSeeds:
    """The detector that produced `intent-unparsed`, run over the rows that produced it.

    A stripper that satisfies its own assertions but still trips the real predicate
    would fix nothing, so the predicate is imported rather than restated.
    """

    CARMELINA = [
        "Cancer other than nonmelanoma skin cancer within 3 years",
        "Drug-naïve or pre-treated excluding GLP-1/DPP-4/SGLT-2 inhibitors (7 days)",
        "Drug-naïve or pre-treated excluding GLP-1/DPP-4/SGLT-2 inhibitors (>= 7 days)",
        "Stable background medication for 8 weeks prior to randomization (Insulin change <= 10%)",
    ]

    def test_should_have_tripped_the_router_before_the_strip(self):
        from src.agents.conceptset.nlu_router import detect_temporal_negation

        assert all(detect_temporal_negation(s) for s in self.CARMELINA), (
            "if the router no longer refuses these, this fix is aimed at the wrong defect"
        )

    def test_should_not_trip_the_router_after_the_strip(self):
        from src.agents.conceptset.nlu_router import detect_temporal_negation

        still_refused = [
            s
            for s in self.CARMELINA
            if detect_temporal_negation(strip_window_expressed_temporal(s))
        ]
        assert still_refused == []
