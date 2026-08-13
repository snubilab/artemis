"""A Measurement concept set must hold things that can carry a value.

`Platelet count - finding` (4273307) and `Platelets [#/volume] in Blood` (3007461) are
both standard, both `domain_id = Measurement`, and both come back from a Measurement
search — so no domain filter separates them. Only `concept_class_id` does, and the
difference matters: the LOINC Lab Test is a measurement a threshold can be applied to,
while the SNOMED Clinical Finding is a qualitative statement *about* one, whose 177
descendants are findings like thrombocytopenia.

Measured on ARISTOTLE 2026-08-11: whichever of the two the reranker happened to pick
swung that criterion's closure between 8 and 184 concepts and its recall against the
gold lab set between 0.500 and 0.000. Repeated draws at temperature 0 showed the
reranker picking the finding 4 times in 5 — so this was never a stable choice to leave
to the model, and a prompt edit only changed which side of the coin came up.

The domain gate is the load-bearing part of this rule. `Clinical Finding` is the
CORRECT class for most of the Condition domain — Myocardial infarction is one — so
applying this outside Measurement would delete most condition mappings.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.agents.agent2.logic import ConceptLogician


def _mock_db_session(rows):
    """Build a SQLAlchemy-session-like mock for get_db()."""
    session = MagicMock()
    session.__enter__.return_value = session
    session.__exit__.return_value = False
    result = MagicMock()
    result.fetchall.return_value = rows
    session.execute.return_value = result
    return session


LOINC_LAB_TEST = 3007461
SNOMED_FINDING = 4273307
SNOMED_PROCEDURE = 4267147
SNOMED_OBSERVABLE = 37208696


class TestDropsTheFindingClass:
    def test_should_drop_the_finding_class_concept_from_a_measurement_set(self):
        session = _mock_db_session(rows=[(SNOMED_FINDING,)])
        with patch("src.agents.agent2.logic._check_db", return_value=True), \
             patch("src.utils.db.get_db", return_value=iter([session])):
            kept = ConceptLogician().drop_qualitative_findings(
                [SNOMED_OBSERVABLE, SNOMED_FINDING, SNOMED_PROCEDURE, LOINC_LAB_TEST]
            )
        assert SNOMED_FINDING not in kept

    def test_should_keep_every_concept_that_can_carry_a_value(self):
        session = _mock_db_session(rows=[(SNOMED_FINDING,)])
        with patch("src.agents.agent2.logic._check_db", return_value=True), \
             patch("src.utils.db.get_db", return_value=iter([session])):
            kept = ConceptLogician().drop_qualitative_findings(
                [SNOMED_OBSERVABLE, SNOMED_FINDING, SNOMED_PROCEDURE, LOINC_LAB_TEST]
            )
        assert kept == [SNOMED_OBSERVABLE, SNOMED_PROCEDURE, LOINC_LAB_TEST]

    def test_should_query_only_for_the_finding_class(self):
        session = _mock_db_session(rows=[])
        with patch("src.agents.agent2.logic._check_db", return_value=True), \
             patch("src.utils.db.get_db", return_value=iter([session])):
            ConceptLogician().drop_qualitative_findings([LOINC_LAB_TEST])
        assert "Clinical Finding" in str(session.execute.call_args.args[0])


class TestNeverMakesThingsWorse:
    def test_should_not_empty_a_set_that_is_all_findings(self):
        """Dropping everything would turn a mapped criterion into a silent gap."""
        session = _mock_db_session(rows=[(SNOMED_FINDING,)])
        with patch("src.agents.agent2.logic._check_db", return_value=True), \
             patch("src.utils.db.get_db", return_value=iter([session])):
            kept = ConceptLogician().drop_qualitative_findings([SNOMED_FINDING])
        assert kept == [SNOMED_FINDING]

    def test_should_return_the_input_when_the_database_is_unavailable(self):
        with patch("src.agents.agent2.logic._check_db", return_value=False):
            kept = ConceptLogician().drop_qualitative_findings([SNOMED_FINDING, LOINC_LAB_TEST])
        assert kept == [SNOMED_FINDING, LOINC_LAB_TEST]

    def test_should_return_empty_for_empty_input(self):
        assert ConceptLogician().drop_qualitative_findings([]) == []

    def test_should_preserve_order_and_deduplicate(self):
        session = _mock_db_session(rows=[])
        with patch("src.agents.agent2.logic._check_db", return_value=True), \
             patch("src.utils.db.get_db", return_value=iter([session])):
            kept = ConceptLogician().drop_qualitative_findings(
                [LOINC_LAB_TEST, SNOMED_PROCEDURE, LOINC_LAB_TEST]
            )
        assert kept == [LOINC_LAB_TEST, SNOMED_PROCEDURE]
