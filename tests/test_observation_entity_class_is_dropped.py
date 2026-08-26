"""Wrong-entity Observation-domain concepts must be dropped from a mapped set.

SPEC-INFRA-005 root cause: `ConceptRetriever.batch_search()` applies `domain_hint`
as a hard ChromaDB `where` filter, but unlike Condition
(`drop_wrong_entity_class_for_condition`) and Measurement
(`drop_qualitative_findings`), Observation domain has no downstream
entity-class/specificity filter at all. Two CAROLINA (NCT01243424) criteria were
mapped to wrong OMOP concepts as a result:

1. "Elevated ALT or AST" (Observation, wrong domain extraction) mapped to SNOMED
   `Substance`-class concepts (`Dehydrogenase`, `Aminotransferase`) and a SNOMED
   `Procedure`-class concept (`Metabolic monitoring`) — a chemical/enzyme name and
   a clinical activity are never the correct entity type for a clinical-status
   Observation criterion. Live-DB verified (2026-08-26, `synthea23m.concept` and
   `omop_vocab.concept` agree): concept ids 4032019/4035061 are `Substance`,
   4056825 is `Procedure` — all `domain_id = 'Observation'`. Zero of the 763
   distinct concept ids referenced across `artemis/data/gold/` carry
   `domain_id = 'Observation' AND concept_class_id IN ('Substance', 'Procedure')`
   (mirrors the 0-instance verification `drop_wrong_entity_class_for_condition`
   performed for its own predicate) — the only class gold ever uses in
   Observation domain is `Clinical Finding` (17 instances). Unconditional
   exclusion is therefore safe.

2. "Cigarette smoking" (Observation, correctly extracted) mapped to 4 LOINC
   candidates, live-DB verified as 3x `Clinical Observation` class + 1x `Survey`
   class — NOT homogeneously Survey/Question as spec.md's investigation-narrative
   citation loosely implied. Per plan.md Decision Point 1 / B-2 (Observation
   legitimately contains patient-reported Survey/Question concepts sometimes —
   `logic.py:370-374`'s docstring for the Condition filter states this
   explicitly), Survey/Question is dropped ONLY when a competing non-Survey
   candidate exists in the same selection — never blanket-excluded the way
   Condition excludes it. Per spec.md §2.3/§4 item C, gold's Observation smoking
   concepts are absent from the vector index entirely (out of scope), so this
   filter converts the wrong 4-candidate set into a still-wrong 3-candidate set
   for the smoking shape specifically — an honest, documented partial outcome,
   not a full fix (AC-002 is SHOULD, not MUST, for exactly this reason).

Gate applies only when domain_hint == "Observation"; the workflow wires it there.
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


# Real synthea23m/omop_vocab OMOP ids (2026-08-26 DB check), verified against the
# actual CAROLINA ALT/AST wrong mapping (conceptSetId=72,
# "Elevated alanine aminotransferase (ALT) or aspartate aminotransferase (AST)"):
DEHYDROGENASE_SUBSTANCE = 4032019      # SNOMED Substance — wrong entity
AMINOTRANSFERASE_SUBSTANCE = 4035061   # SNOMED Substance — wrong entity
METABOLIC_MONITORING_PROCEDURE = 4056825  # SNOMED Procedure — wrong entity
WARFARIN_MONITORING_CLINICAL_FINDING = 4086755  # SNOMED Clinical Finding — correct entity class

# Real synthea23m/omop_vocab OMOP ids, verified against the actual CAROLINA
# smoking wrong mapping (conceptSetId=6, "Cigarette smoking"):
SMOKING_PREGNANCY_CLINICAL_OBS = 1469816     # LOINC Clinical Observation
TOBACCO_FREQ_CLINICAL_OBS = 1617710          # LOINC Clinical Observation
HISTORY_TOBACCO_CLINICAL_OBS = 3012697       # LOINC Clinical Observation
TOBACCO_DAILY_SURVEY = 3046963               # LOINC Survey — the sole Survey-class member


# --------------------------------------------------------------------------- #
# Core drop behaviour — AC-001 (Substance/Procedure, unconditional)
# --------------------------------------------------------------------------- #

class TestDropsSubstanceClassConcepts:
    def test_should_drop_snomed_substance_from_an_observation_set(self):
        """SNOMED Substance class (a chemical/enzyme name) is never the correct
        entity type for a clinical-status Observation criterion."""
        session = _mock_db_session(rows=[
            (DEHYDROGENASE_SUBSTANCE, "Observation", "Substance"),
            (WARFARIN_MONITORING_CLINICAL_FINDING, "Observation", "Clinical Finding"),
        ])
        with patch("src.agents.agent2.logic._check_db", return_value=True), \
             patch("src.utils.db.get_db", return_value=iter([session])):
            kept = ConceptLogician().drop_wrong_entity_class_for_observation(
                [WARFARIN_MONITORING_CLINICAL_FINDING, DEHYDROGENASE_SUBSTANCE]
            )
        assert DEHYDROGENASE_SUBSTANCE not in kept

    def test_should_keep_clinical_finding_concept(self):
        """Correct Clinical Finding concept is preserved."""
        session = _mock_db_session(rows=[
            (DEHYDROGENASE_SUBSTANCE, "Observation", "Substance"),
            (WARFARIN_MONITORING_CLINICAL_FINDING, "Observation", "Clinical Finding"),
        ])
        with patch("src.agents.agent2.logic._check_db", return_value=True), \
             patch("src.utils.db.get_db", return_value=iter([session])):
            kept = ConceptLogician().drop_wrong_entity_class_for_observation(
                [WARFARIN_MONITORING_CLINICAL_FINDING, DEHYDROGENASE_SUBSTANCE]
            )
        assert WARFARIN_MONITORING_CLINICAL_FINDING in kept


class TestDropsProcedureClassConcepts:
    """`Metabolic monitoring` (4056825) is domain_id='Observation' AND
    concept_class_id='Procedure' — a clinical activity, not a status. Live-DB
    verification corrected spec.md's loose citation (it grouped this concept
    under "Substance"-shape); the actual class is Procedure."""

    def test_should_drop_procedure_class_from_an_observation_set(self):
        session = _mock_db_session(rows=[
            (METABOLIC_MONITORING_PROCEDURE, "Observation", "Procedure"),
            (WARFARIN_MONITORING_CLINICAL_FINDING, "Observation", "Clinical Finding"),
        ])
        with patch("src.agents.agent2.logic._check_db", return_value=True), \
             patch("src.utils.db.get_db", return_value=iter([session])):
            kept = ConceptLogician().drop_wrong_entity_class_for_observation(
                [WARFARIN_MONITORING_CLINICAL_FINDING, METABOLIC_MONITORING_PROCEDURE]
            )
        assert METABOLIC_MONITORING_PROCEDURE not in kept
        assert WARFARIN_MONITORING_CLINICAL_FINDING in kept

    def test_should_drop_the_full_carolina_alt_ast_wrong_mapping_in_one_pass(self):
        """Reproduces the actual CAROLINA ALT/AST wrong mapping (conceptSetId=72):
        Dehydrogenase (Substance) + Aminotransferase (Substance) +
        Metabolic monitoring (Procedure), alongside a correctly-classed candidate."""
        session = _mock_db_session(rows=[
            (DEHYDROGENASE_SUBSTANCE, "Observation", "Substance"),
            (AMINOTRANSFERASE_SUBSTANCE, "Observation", "Substance"),
            (METABOLIC_MONITORING_PROCEDURE, "Observation", "Procedure"),
            (WARFARIN_MONITORING_CLINICAL_FINDING, "Observation", "Clinical Finding"),
        ])
        with patch("src.agents.agent2.logic._check_db", return_value=True), \
             patch("src.utils.db.get_db", return_value=iter([session])):
            kept = ConceptLogician().drop_wrong_entity_class_for_observation([
                DEHYDROGENASE_SUBSTANCE,
                AMINOTRANSFERASE_SUBSTANCE,
                METABOLIC_MONITORING_PROCEDURE,
                WARFARIN_MONITORING_CLINICAL_FINDING,
            ])
        assert kept == [WARFARIN_MONITORING_CLINICAL_FINDING]


# --------------------------------------------------------------------------- #
# AC-002 — smoking shape: conditional Survey/Question drop (non-sole class only)
# --------------------------------------------------------------------------- #

class TestConditionalSurveyQuestionDrop:
    """Per plan.md Decision Point 1 / B-2: Observation legitimately contains
    patient-reported Survey/Question concepts sometimes, so this class is NOT
    blanket-excluded the way Condition excludes it (`drop_wrong_entity_class_for_condition`).
    A Survey/Question candidate is dropped only when a competing non-Survey/Question
    Observation-domain candidate exists in the same selection.

    Reproduces the actual CAROLINA smoking wrong mapping (conceptSetId=6):
    3x Clinical Observation + 1x Survey. Per this predicate, the sole Survey
    member is dropped (a competing non-Survey candidate exists); the 3 Clinical
    Observation members are retained. This does NOT reach gold overlap (item C,
    out of scope) — an honest partial fix, exactly as AC-002 (SHOULD) anticipates.
    """

    def test_should_drop_survey_class_when_competing_non_survey_candidate_exists(self):
        session = _mock_db_session(rows=[
            (SMOKING_PREGNANCY_CLINICAL_OBS, "Observation", "Clinical Observation"),
            (TOBACCO_FREQ_CLINICAL_OBS, "Observation", "Clinical Observation"),
            (HISTORY_TOBACCO_CLINICAL_OBS, "Observation", "Clinical Observation"),
            (TOBACCO_DAILY_SURVEY, "Observation", "Survey"),
        ])
        with patch("src.agents.agent2.logic._check_db", return_value=True), \
             patch("src.utils.db.get_db", return_value=iter([session])):
            kept = ConceptLogician().drop_wrong_entity_class_for_observation([
                SMOKING_PREGNANCY_CLINICAL_OBS,
                TOBACCO_FREQ_CLINICAL_OBS,
                HISTORY_TOBACCO_CLINICAL_OBS,
                TOBACCO_DAILY_SURVEY,
            ])
        assert TOBACCO_DAILY_SURVEY not in kept
        assert kept == [
            SMOKING_PREGNANCY_CLINICAL_OBS,
            TOBACCO_FREQ_CLINICAL_OBS,
            HISTORY_TOBACCO_CLINICAL_OBS,
        ]

    def test_should_keep_sole_survey_class_when_no_competing_candidate_exists(self):
        """B-2's caution in action: a Survey-only selection is NOT emptied —
        Observation legitimately contains patient-reported instruments sometimes."""
        session = _mock_db_session(rows=[
            (TOBACCO_DAILY_SURVEY, "Observation", "Survey"),
        ])
        with patch("src.agents.agent2.logic._check_db", return_value=True), \
             patch("src.utils.db.get_db", return_value=iter([session])):
            kept = ConceptLogician().drop_wrong_entity_class_for_observation(
                [TOBACCO_DAILY_SURVEY]
            )
        assert kept == [TOBACCO_DAILY_SURVEY]


# --------------------------------------------------------------------------- #
# AC-005 — sole all-wrong-entity input fails closed
# --------------------------------------------------------------------------- #

class TestSoleMappingIsDropped:
    """Mirrors drop_wrong_entity_class_for_condition's corrected sole-mapping
    behaviour (logic.py:418-436) — per plan.md Decision Point 2, an
    all-wrong-entity Observation set fails closed (returns []) rather than
    silently keeping a known-wrong concept."""

    def test_sole_substance_concept_is_dropped(self):
        session = _mock_db_session(rows=[
            (DEHYDROGENASE_SUBSTANCE, "Observation", "Substance"),
        ])
        with patch("src.agents.agent2.logic._check_db", return_value=True), \
             patch("src.utils.db.get_db", return_value=iter([session])):
            kept = ConceptLogician().drop_wrong_entity_class_for_observation(
                [DEHYDROGENASE_SUBSTANCE]
            )
        assert kept == [], (
            "Sole Substance concept must be dropped, not kept to avoid an empty list"
        )

    def test_all_substance_and_procedure_set_is_dropped(self):
        session = _mock_db_session(rows=[
            (DEHYDROGENASE_SUBSTANCE, "Observation", "Substance"),
            (METABOLIC_MONITORING_PROCEDURE, "Observation", "Procedure"),
        ])
        with patch("src.agents.agent2.logic._check_db", return_value=True), \
             patch("src.utils.db.get_db", return_value=iter([session])):
            kept = ConceptLogician().drop_wrong_entity_class_for_observation(
                [DEHYDROGENASE_SUBSTANCE, METABOLIC_MONITORING_PROCEDURE]
            )
        assert kept == []


# --------------------------------------------------------------------------- #
# AC-004 — DB-down / edge cases: fail-open only on connectivity
# --------------------------------------------------------------------------- #

class TestFailOpenOnConnectivityOnly:
    def test_should_return_input_when_database_is_unavailable(self):
        """No DB, no change — fail-open on connectivity to preserve mappings."""
        with patch("src.agents.agent2.logic._check_db", return_value=False):
            concepts = [DEHYDROGENASE_SUBSTANCE, WARFARIN_MONITORING_CLINICAL_FINDING]
            kept = ConceptLogician().drop_wrong_entity_class_for_observation(concepts)
        assert kept == concepts

    def test_should_return_empty_for_empty_input(self):
        assert ConceptLogician().drop_wrong_entity_class_for_observation([]) == []

    def test_should_pass_through_when_no_wrong_entity_found(self):
        """A clean Observation set is not mutated."""
        session = _mock_db_session(rows=[
            (WARFARIN_MONITORING_CLINICAL_FINDING, "Observation", "Clinical Finding"),
        ])
        with patch("src.agents.agent2.logic._check_db", return_value=True), \
             patch("src.utils.db.get_db", return_value=iter([session])):
            concepts = [WARFARIN_MONITORING_CLINICAL_FINDING]
            kept = ConceptLogician().drop_wrong_entity_class_for_observation(concepts)
        assert kept == concepts

    def test_should_preserve_order_and_deduplicate(self):
        session = _mock_db_session(rows=[
            (WARFARIN_MONITORING_CLINICAL_FINDING, "Observation", "Clinical Finding"),
            (SMOKING_PREGNANCY_CLINICAL_OBS, "Observation", "Clinical Observation"),
        ])
        with patch("src.agents.agent2.logic._check_db", return_value=True), \
             patch("src.utils.db.get_db", return_value=iter([session])):
            kept = ConceptLogician().drop_wrong_entity_class_for_observation([
                WARFARIN_MONITORING_CLINICAL_FINDING,
                SMOKING_PREGNANCY_CLINICAL_OBS,
                WARFARIN_MONITORING_CLINICAL_FINDING,
            ])
        assert kept == [WARFARIN_MONITORING_CLINICAL_FINDING, SMOKING_PREGNANCY_CLINICAL_OBS]


# --------------------------------------------------------------------------- #
# AC-008 / AC-009 — DB query shape + no identity-/name-keyed special case
# --------------------------------------------------------------------------- #

class TestQueryShape:
    def test_should_query_all_candidates_in_one_call(self):
        """The gate is a single DB round-trip regardless of candidate count."""
        session = _mock_db_session(rows=[
            (WARFARIN_MONITORING_CLINICAL_FINDING, "Observation", "Clinical Finding"),
        ])
        with patch("src.agents.agent2.logic._check_db", return_value=True), \
             patch("src.utils.db.get_db", return_value=iter([session])):
            ConceptLogician().drop_wrong_entity_class_for_observation(
                [WARFARIN_MONITORING_CLINICAL_FINDING]
            )
        call_sql = str(session.execute.call_args.args[0])
        assert session.execute.call_count == 1
        assert "domain_id" in call_sql
        assert "concept_class_id" in call_sql

    def test_should_fire_logger_info_on_non_empty_drop(self, caplog):
        import logging
        session = _mock_db_session(rows=[
            (DEHYDROGENASE_SUBSTANCE, "Observation", "Substance"),
            (WARFARIN_MONITORING_CLINICAL_FINDING, "Observation", "Clinical Finding"),
        ])
        with patch("src.agents.agent2.logic._check_db", return_value=True), \
             patch("src.utils.db.get_db", return_value=iter([session])), \
             caplog.at_level(logging.INFO, logger="src.agents.agent2.logic"):
            ConceptLogician().drop_wrong_entity_class_for_observation(
                [WARFARIN_MONITORING_CLINICAL_FINDING, DEHYDROGENASE_SUBSTANCE]
            )
        assert any("Dropped" in r.message for r in caplog.records)


class TestNoIdentityOrNameKeyedSpecialCase:
    """AC-009: verify the implementation contains no literal concept-name
    special case, mirroring SPEC-INFRA-004 AC-011's inspection-based check."""

    def test_no_hardcoded_literal_names_in_source(self):
        import inspect

        from src.agents.agent2.logic import ConceptLogician

        source = inspect.getsource(ConceptLogician.drop_wrong_entity_class_for_observation)
        for banned in ("Dehydrogenase", "Aminotransferase", "Metabolic monitoring"):
            assert banned not in source, f"literal name special-case found: {banned}"


# --------------------------------------------------------------------------- #
# AC-003 — Workflow integration: domain gate
# --------------------------------------------------------------------------- #

class TestWorkflowGating:
    """The gate must be wired only on Observation domain in workflow.py."""

    def _run_workflow_post_processing(self, concept_ids, domain_hint, class_rows):
        """Simulate just the post-processing block from process_with_details."""
        from src.agents.agent2 import logic as logic_mod

        logician = logic_mod.ConceptLogician()

        session = _mock_db_session(rows=class_rows)
        with patch.object(logic_mod, "_check_db", return_value=True), \
             patch("src.utils.db.get_db", return_value=iter([session])):
            if domain_hint == "Observation":
                return logician.drop_wrong_entity_class_for_observation(concept_ids)
            return concept_ids

    def test_gate_fires_on_observation_domain(self):
        result = self._run_workflow_post_processing(
            [WARFARIN_MONITORING_CLINICAL_FINDING, DEHYDROGENASE_SUBSTANCE],
            domain_hint="Observation",
            class_rows=[
                (WARFARIN_MONITORING_CLINICAL_FINDING, "Observation", "Clinical Finding"),
                (DEHYDROGENASE_SUBSTANCE, "Observation", "Substance"),
            ],
        )
        assert DEHYDROGENASE_SUBSTANCE not in result
        assert WARFARIN_MONITORING_CLINICAL_FINDING in result

    def test_gate_does_not_fire_on_condition_domain(self):
        result = self._run_workflow_post_processing(
            [DEHYDROGENASE_SUBSTANCE], domain_hint="Condition", class_rows=[],
        )
        assert result == [DEHYDROGENASE_SUBSTANCE]

    def test_gate_does_not_fire_on_drug_domain(self):
        result = self._run_workflow_post_processing(
            [DEHYDROGENASE_SUBSTANCE], domain_hint="Drug", class_rows=[],
        )
        assert result == [DEHYDROGENASE_SUBSTANCE]

    def test_gate_does_not_fire_on_measurement_domain(self):
        result = self._run_workflow_post_processing(
            [DEHYDROGENASE_SUBSTANCE], domain_hint="Measurement", class_rows=[],
        )
        assert result == [DEHYDROGENASE_SUBSTANCE]

    def test_gate_does_not_fire_on_procedure_domain(self):
        result = self._run_workflow_post_processing(
            [DEHYDROGENASE_SUBSTANCE], domain_hint="Procedure", class_rows=[],
        )
        assert result == [DEHYDROGENASE_SUBSTANCE]

    def test_gate_does_not_fire_on_device_domain(self):
        result = self._run_workflow_post_processing(
            [DEHYDROGENASE_SUBSTANCE], domain_hint="Device", class_rows=[],
        )
        assert result == [DEHYDROGENASE_SUBSTANCE]

    def test_gate_does_not_fire_on_none_domain(self):
        result = self._run_workflow_post_processing(
            [DEHYDROGENASE_SUBSTANCE], domain_hint=None, class_rows=[],
        )
        assert result == [DEHYDROGENASE_SUBSTANCE]
