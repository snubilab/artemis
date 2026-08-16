"""Modifier-matched, wrong-entity concepts must be dropped from Condition sets.

Plan-044 failure mode: the reranker's query_has_match gate says True because the
candidate name shares a substring with the criterion. Two entity types slip through:

1. LOINC Survey/Question class — 'History of stroke [USAUDIT]' is a questionnaire
   instrument, not the clinical event. The name match is on the modifier framing
   ('History of'), not the condition.
2. Procedure domain — 'Atrial fibrillation ablation' is a catheter ablation, not
   the Condition 'Atrial fibrillation and flutter'. The shared substring is the
   modifier ('ablation') that distinguishes them.

The fix mirrors test_measurement_finding_class_is_dropped.py for the Condition domain.
Gate applies only when domain_hint == "Condition"; the workflow wires it there.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.agents.agent2.logic import ConceptLogician

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

def _mock_db_session(rows):
    """Build a SQLAlchemy-session-like mock for get_db()."""
    session = MagicMock()
    session.__enter__.return_value = session
    session.__exit__.return_value = False
    result = MagicMock()
    result.fetchall.return_value = rows
    session.execute.return_value = result
    return session


# Concept IDs used throughout. These are not required to be real OMOP ids in
# unit tests; the DB is mocked. The names are chosen for readability.
STROKE_SNOMED_CONDITION = 4043839        # Cerebrovascular accident — correct Condition
HISTORY_OF_STROKE_LOINC_SURVEY = 35622  # LOINC Survey class — wrong entity
AF_AND_FLUTTER_CONDITION = 4180790       # Atrial fibrillation and flutter — correct Condition
AF_ABLATION_PROCEDURE = 4070311          # Ablation of atrial fibrillation — Procedure, wrong entity
ANOTHER_CONDITION = 4329847              # Myocardial infarction — correct, unrelated control


# --------------------------------------------------------------------------- #
# Core drop behaviour
# --------------------------------------------------------------------------- #

class TestDropsSurveyClassConcepts:
    def test_should_drop_loinc_survey_from_a_condition_set(self):
        """LOINC Survey class is a questionnaire, not a clinical event."""
        session = _mock_db_session(rows=[(HISTORY_OF_STROKE_LOINC_SURVEY,)])
        with patch("src.agents.agent2.logic._check_db", return_value=True), \
             patch("src.utils.db.get_db", return_value=iter([session])):
            kept = ConceptLogician().drop_wrong_entity_class_for_condition(
                [STROKE_SNOMED_CONDITION, HISTORY_OF_STROKE_LOINC_SURVEY]
            )
        assert HISTORY_OF_STROKE_LOINC_SURVEY not in kept

    def test_should_keep_snomed_condition_concept(self):
        """Correct Condition concept is preserved."""
        session = _mock_db_session(rows=[(HISTORY_OF_STROKE_LOINC_SURVEY,)])
        with patch("src.agents.agent2.logic._check_db", return_value=True), \
             patch("src.utils.db.get_db", return_value=iter([session])):
            kept = ConceptLogician().drop_wrong_entity_class_for_condition(
                [STROKE_SNOMED_CONDITION, HISTORY_OF_STROKE_LOINC_SURVEY]
            )
        assert STROKE_SNOMED_CONDITION in kept


class TestDropsProcedureDomainConcepts:
    def test_should_drop_procedure_concept_from_a_condition_set(self):
        """Procedure-domain concept is wrong entity type for Condition criteria."""
        session = _mock_db_session(rows=[(AF_ABLATION_PROCEDURE,)])
        with patch("src.agents.agent2.logic._check_db", return_value=True), \
             patch("src.utils.db.get_db", return_value=iter([session])):
            kept = ConceptLogician().drop_wrong_entity_class_for_condition(
                [AF_AND_FLUTTER_CONDITION, AF_ABLATION_PROCEDURE]
            )
        assert AF_ABLATION_PROCEDURE not in kept

    def test_should_keep_condition_concept_when_procedure_is_dropped(self):
        """Gold condition concept survives when the wrong-entity procedure is dropped."""
        session = _mock_db_session(rows=[(AF_ABLATION_PROCEDURE,)])
        with patch("src.agents.agent2.logic._check_db", return_value=True), \
             patch("src.utils.db.get_db", return_value=iter([session])):
            kept = ConceptLogician().drop_wrong_entity_class_for_condition(
                [AF_AND_FLUTTER_CONDITION, AF_ABLATION_PROCEDURE]
            )
        assert kept == [AF_AND_FLUTTER_CONDITION]

    def test_should_drop_both_survey_and_procedure_in_one_pass(self):
        """Both wrong-entity classes are filtered in the same DB query."""
        session = _mock_db_session(
            rows=[(HISTORY_OF_STROKE_LOINC_SURVEY,), (AF_ABLATION_PROCEDURE,)]
        )
        with patch("src.agents.agent2.logic._check_db", return_value=True), \
             patch("src.utils.db.get_db", return_value=iter([session])):
            kept = ConceptLogician().drop_wrong_entity_class_for_condition(
                [STROKE_SNOMED_CONDITION, HISTORY_OF_STROKE_LOINC_SURVEY, AF_ABLATION_PROCEDURE]
            )
        assert HISTORY_OF_STROKE_LOINC_SURVEY not in kept
        assert AF_ABLATION_PROCEDURE not in kept
        assert STROKE_SNOMED_CONDITION in kept


# --------------------------------------------------------------------------- #
# Sole-mapping: drop wrong-entity even when it is the only concept
# --------------------------------------------------------------------------- #

class TestSoleMappingIsDropped:
    """Plan-044 intent gap: the gate must fire even when the reranker returned only one
    concept and that concept is the wrong entity type.  The original fail-open (keeping
    the wrong concept to avoid an empty list) violated intent fidelity.  The correct
    behaviour is to return [] so the caller falls through to the RAG fallback and, if
    that also fails, records the miss in _unmappedCriteria via the normal path."""

    def test_sole_survey_concept_is_dropped(self):
        """A sole LOINC Survey concept ('History of stroke') must not be kept."""
        session = _mock_db_session(rows=[(HISTORY_OF_STROKE_LOINC_SURVEY,)])
        with patch("src.agents.agent2.logic._check_db", return_value=True), \
             patch("src.utils.db.get_db", return_value=iter([session])):
            kept = ConceptLogician().drop_wrong_entity_class_for_condition(
                [HISTORY_OF_STROKE_LOINC_SURVEY]
            )
        assert kept == [], (
            "Sole Survey concept must be dropped, not kept to avoid an empty list"
        )

    def test_sole_procedure_concept_is_dropped(self):
        """A sole Procedure concept ('AF ablation') must not be kept for a Condition."""
        session = _mock_db_session(rows=[(AF_ABLATION_PROCEDURE,)])
        with patch("src.agents.agent2.logic._check_db", return_value=True), \
             patch("src.utils.db.get_db", return_value=iter([session])):
            kept = ConceptLogician().drop_wrong_entity_class_for_condition(
                [AF_ABLATION_PROCEDURE]
            )
        assert kept == [], (
            "Sole Procedure concept must be dropped, not kept to avoid an empty list"
        )

    def test_all_wrong_entity_set_is_dropped(self):
        """When every concept is wrong-entity the entire set is dropped."""
        session = _mock_db_session(
            rows=[(HISTORY_OF_STROKE_LOINC_SURVEY,), (AF_ABLATION_PROCEDURE,)]
        )
        with patch("src.agents.agent2.logic._check_db", return_value=True), \
             patch("src.utils.db.get_db", return_value=iter([session])):
            kept = ConceptLogician().drop_wrong_entity_class_for_condition(
                [HISTORY_OF_STROKE_LOINC_SURVEY, AF_ABLATION_PROCEDURE]
            )
        assert kept == []


# --------------------------------------------------------------------------- #
# DB-down / edge cases: fail-open only on connectivity, not on wrong entity
# --------------------------------------------------------------------------- #

class TestFailOpenOnConnectivityOnly:
    def test_should_return_input_when_database_is_unavailable(self):
        """No DB, no change — fail-open on connectivity to preserve mappings."""
        with patch("src.agents.agent2.logic._check_db", return_value=False):
            concepts = [STROKE_SNOMED_CONDITION, HISTORY_OF_STROKE_LOINC_SURVEY]
            kept = ConceptLogician().drop_wrong_entity_class_for_condition(concepts)
        assert kept == concepts

    def test_should_return_empty_for_empty_input(self):
        assert ConceptLogician().drop_wrong_entity_class_for_condition([]) == []

    def test_should_pass_through_when_no_wrong_entity_found(self):
        """A clean Condition set is not mutated."""
        session = _mock_db_session(rows=[])
        with patch("src.agents.agent2.logic._check_db", return_value=True), \
             patch("src.utils.db.get_db", return_value=iter([session])):
            concepts = [STROKE_SNOMED_CONDITION, AF_AND_FLUTTER_CONDITION, ANOTHER_CONDITION]
            kept = ConceptLogician().drop_wrong_entity_class_for_condition(concepts)
        assert kept == concepts

    def test_should_preserve_order_and_deduplicate(self):
        session = _mock_db_session(rows=[])
        with patch("src.agents.agent2.logic._check_db", return_value=True), \
             patch("src.utils.db.get_db", return_value=iter([session])):
            kept = ConceptLogician().drop_wrong_entity_class_for_condition(
                [STROKE_SNOMED_CONDITION, AF_AND_FLUTTER_CONDITION, STROKE_SNOMED_CONDITION]
            )
        assert kept == [STROKE_SNOMED_CONDITION, AF_AND_FLUTTER_CONDITION]


# --------------------------------------------------------------------------- #
# DB query shape
# --------------------------------------------------------------------------- #

class TestQueryShape:
    def test_should_query_for_survey_and_procedure_in_one_call(self):
        """The gate is a single DB round-trip, not one per class."""
        session = _mock_db_session(rows=[])
        with patch("src.agents.agent2.logic._check_db", return_value=True), \
             patch("src.utils.db.get_db", return_value=iter([session])):
            ConceptLogician().drop_wrong_entity_class_for_condition([STROKE_SNOMED_CONDITION])
        call_sql = str(session.execute.call_args.args[0])
        assert "Survey" in call_sql
        assert "Procedure" in call_sql
        assert session.execute.call_count == 1


# --------------------------------------------------------------------------- #
# Workflow integration: domain gate
# --------------------------------------------------------------------------- #

class TestWorkflowGating:
    """The gate must be wired only on Condition domain in workflow.py."""

    def _run_workflow_post_processing(self, concept_ids, domain_hint, wrong_entity_ids):
        """Simulate just the post-processing block from process_with_details."""
        from src.agents.agent2 import logic as logic_mod

        logician = logic_mod.ConceptLogician()

        session = _mock_db_session(rows=[(cid,) for cid in wrong_entity_ids])
        with patch.object(logic_mod, "_check_db", return_value=True), \
             patch("src.utils.db.get_db", return_value=iter([session])):
            if domain_hint == "Condition":
                return logician.drop_wrong_entity_class_for_condition(concept_ids)
            return concept_ids

    def test_gate_fires_on_condition_domain(self):
        result = self._run_workflow_post_processing(
            [AF_AND_FLUTTER_CONDITION, AF_ABLATION_PROCEDURE],
            domain_hint="Condition",
            wrong_entity_ids=[AF_ABLATION_PROCEDURE],
        )
        assert AF_ABLATION_PROCEDURE not in result
        assert AF_AND_FLUTTER_CONDITION in result

    def test_gate_does_not_fire_on_procedure_domain(self):
        """Procedure criteria correctly map to Procedure concepts — do not filter."""
        result = self._run_workflow_post_processing(
            [AF_ABLATION_PROCEDURE],
            domain_hint="Procedure",
            wrong_entity_ids=[],
        )
        assert result == [AF_ABLATION_PROCEDURE]

    def test_gate_does_not_fire_on_drug_domain(self):
        """Drug criteria are handled by roll_up_to_rxnorm_ingredients, not this gate."""
        result = self._run_workflow_post_processing(
            [STROKE_SNOMED_CONDITION],  # any concept, domain not Condition
            domain_hint="Drug",
            wrong_entity_ids=[],
        )
        assert result == [STROKE_SNOMED_CONDITION]

    def test_gate_does_not_fire_on_measurement_domain(self):
        """Measurement domain is handled by drop_qualitative_findings, not this gate."""
        result = self._run_workflow_post_processing(
            [STROKE_SNOMED_CONDITION],
            domain_hint="Measurement",
            wrong_entity_ids=[],
        )
        assert result == [STROKE_SNOMED_CONDITION]
