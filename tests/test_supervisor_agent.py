"""
Unit tests for ARTEMIS Supervisor Agent — LangGraph graph structure + review logic.
DB/LLM 의존성 없음. Mock 기반.
"""
import sys
import types
import pytest

# ── pandas stub ──
_injected_pandas = False
try:
    import pandas  # noqa: F401
except Exception:
    pd_stub = types.ModuleType("pandas")
    pd_stub.DataFrame = type("DataFrame", (), {
        "__init__": lambda self, *a, **k: None,
        "__len__": lambda self: 0,
    })
    sys.modules["pandas"] = pd_stub
    _injected_pandas = True

from src.pipeline.supervisor_agent import (
    build_graph,
    compile_graph,
    ArtemisState,
    SupervisorDecision,
    mapping_node,
    review_trial,
    review_mapping,
    review_assembly,
    review_extraction,
    review_analysis,
    review_reporting,
    route_after_trial,
    route_after_mapping,
    route_after_assembly,
    route_after_extraction,
    _check_domain_mismatches,
    audit_high_risk_entities,
    audit_mapping_results,
    MAX_RETRY,
)
from src.pipeline.supervisor import Agent2MappingTelemetry
from src.models.ir import (
    ARTEMISRequest,
    CohortDefinition,
    PrimaryCriteria,
    CohortOutcome,
    TemporalWindow,
    GapReport,
)
from langgraph.graph import END


def teardown_module():
    if _injected_pandas:
        sys.modules.pop("pandas", None)


# ── Fixtures ──

def _make_ir(target_entity="Metformin", comparator_entity="Sulfonylurea"):
    return ARTEMISRequest(
        target=CohortDefinition(
            primary_criteria=PrimaryCriteria(domain="Drug", entity_text=target_entity),
        ),
        comparator=CohortDefinition(
            primary_criteria=PrimaryCriteria(domain="Drug", entity_text=comparator_entity),
        ),
        outcome=CohortOutcome(
            name="Death", domain="Condition", entity_text="Death",
            time_at_risk=TemporalWindow(start=0, end=365),
        ),
    )


# ══════════════════════════════════════════════════════════════
# Graph Structure Tests
# ══════════════════════════════════════════════════════════════

class TestGraphStructure:

    def test_all_nodes_present(self):
        g = build_graph()
        expected = {
            "trial", "mapping", "assembly", "extraction", "analysis", "reporting",
            "review_trial", "review_mapping", "review_assembly",
            "review_extraction", "review_analysis", "review_reporting",
        }
        assert expected == set(g.nodes.keys())

    def test_compiles_without_error(self):
        app = compile_graph()
        assert app is not None

    def test_reporting_is_reviewed_before_finish(self):
        g = build_graph()
        assert ("reporting", "review_reporting") in g.edges
        assert ("review_reporting", END) in g.edges

class TestExecutionNodes:

    def test_mapping_node_passes_registry_dependencies_to_register(self, monkeypatch):
        calls = {}

        class FakeSupervisor:
            def _step2_map(self, ir):
                return ([{"name": "Metformin", "concept_ids": [1], "domain": "Drug"}], GapReport(), [], Agent2MappingTelemetry())

            def post_agent2_check(self, mapped_sets, gap, entities):
                return types.SimpleNamespace(retries_triggered=0)

            def _step2_5_consolidate(self, mapped_sets):
                return mapped_sets

            def _step3_register(self, mapped_sets, registry, registered_concept):
                calls["args"] = (mapped_sets, registry, registered_concept)
                return ["registered"]

        fake_supervisor_module = types.ModuleType("src.pipeline.supervisor")
        fake_supervisor_module.get_supervisor = lambda: FakeSupervisor()
        monkeypatch.setitem(sys.modules, "src.pipeline.supervisor", fake_supervisor_module)

        fake_registry_models = types.ModuleType("src.registry.models")
        fake_registry_models.RegisteredConcept = type("RegisteredConcept", (), {})
        monkeypatch.setitem(sys.modules, "src.registry.models", fake_registry_models)

        fake_registry_store = types.ModuleType("src.registry.store")
        fake_registry_store.registry = object()
        monkeypatch.setitem(sys.modules, "src.registry.store", fake_registry_store)

        result = mapping_node({"ir": object()})

        assert result["registered_sets"] == ["registered"]
        assert calls["args"][1] is fake_registry_store.registry
        assert calls["args"][2] is fake_registry_models.RegisteredConcept

# ══════════════════════════════════════════════════════════════
# Review Node Tests
# ══════════════════════════════════════════════════════════════

class TestReviewTrial:

    def test_valid_ir_proceeds(self):
        state = {"ir": _make_ir(), "decisions": [], "error_log": []}
        result = review_trial(state)
        assert result["decisions"][0].action == "PROCEED"
        assert result["decisions"][0].status == "SUCCESS"

    def test_none_ir_escalates(self):
        state = {"ir": None, "decisions": [], "error_log": []}
        result = review_trial(state)
        assert result["decisions"][0].action == "ESCALATE"
        assert "escalate_reason" in result

    def test_empty_target_entity_partial(self):
        ir = _make_ir(target_entity="")
        state = {"ir": ir, "decisions": [], "error_log": []}
        result = review_trial(state)
        assert result["decisions"][0].action == "PROCEED"
        assert result["decisions"][0].status == "PARTIAL"


class TestReviewMapping:

    def test_good_mapping_proceeds(self):
        gap = GapReport(total_criteria=10, mapped_count=9)
        state = {
            "gap_report": gap,
            "mapped_sets": [{"name": f"c{i}"} for i in range(9)],
            "retry_counts": {},
            "decisions": [],
            "error_log": [],
        }
        result = review_mapping(state)
        assert result["decisions"][0].action == "PROCEED"

    def test_low_rate_retries(self):
        gap = GapReport(total_criteria=10, mapped_count=6)
        state = {
            "gap_report": gap,
            "mapped_sets": [{"name": f"c{i}"} for i in range(6)],
            "retry_counts": {"mapping": 0},
            "decisions": [],
            "error_log": [],
        }
        result = review_mapping(state)
        assert result["decisions"][0].action == "RETRY"
        assert result["retry_counts"]["mapping"] == 1
        # loop_results telemetry
        assert len(result["loop_results"]) == 1
        lr = result["loop_results"][0]
        assert lr.loop_id == "LOOP_2_MAPPING"
        assert lr.attempt == 1
        assert lr.status == "FAILED"

    def test_very_low_rate_escalates(self):
        gap = GapReport(total_criteria=10, mapped_count=3)
        state = {
            "gap_report": gap,
            "mapped_sets": [{"name": f"c{i}"} for i in range(3)],
            "retry_counts": {},
            "decisions": [],
            "error_log": [],
        }
        result = review_mapping(state)
        assert result["decisions"][0].action == "ESCALATE"

    def test_max_retry_exhausted_proceeds(self):
        gap = GapReport(total_criteria=10, mapped_count=7)
        state = {
            "gap_report": gap,
            "mapped_sets": [{"name": f"c{i}"} for i in range(7)],
            "retry_counts": {"mapping": MAX_RETRY},
            "decisions": [],
            "error_log": [],
        }
        result = review_mapping(state)
        assert result["decisions"][0].action == "PROCEED"


class TestDomainMismatch:
    """Tests for _check_domain_mismatches helper."""

    def test_no_mismatch(self):
        mapped = [
            {"name": "Metformin", "domain": "Drug", "concept_ids": [1, 2]},
        ]
        # Simulate registered sets with concepts
        from unittest.mock import MagicMock
        rc1, rc2 = MagicMock(), MagicMock()
        rc1.concept_id, rc1.domain_id = 1, "Drug"
        rc2.concept_id, rc2.domain_id = 2, "Drug"
        rs = MagicMock()
        rs.concepts = [rc1, rc2]

        result = _check_domain_mismatches(mapped, [rs])
        assert result == []

    def test_mismatch_detected(self):
        mapped = [
            {"name": "Metformin", "domain": "Drug", "concept_ids": [1, 2]},
        ]
        from unittest.mock import MagicMock
        rc1, rc2 = MagicMock(), MagicMock()
        rc1.concept_id, rc1.domain_id = 1, "Drug"
        rc2.concept_id, rc2.domain_id = 2, "Observation"  # WRONG!
        rs = MagicMock()
        rs.concepts = [rc1, rc2]

        result = _check_domain_mismatches(mapped, [rs])
        assert len(result) == 1
        assert result[0]["entity"] == "Metformin"
        assert result[0]["mismatch_count"] == 1
        assert "Observation" in result[0]["concept_domains"]

    def test_no_registered_sets_no_crash(self):
        mapped = [
            {"name": "X", "domain": "Drug", "concept_ids": [1]},
        ]
        result = _check_domain_mismatches(mapped, [])
        assert result == []  # can't check without metadata

    def test_empty_domain_skipped(self):
        mapped = [
            {"name": "X", "domain": "", "concept_ids": [1]},
        ]
        result = _check_domain_mismatches(mapped, [])
        assert result == []

    def test_mismatch_records_domain_frequency(self):
        mapped = [
            {"name": "Metformin", "domain": "Drug", "concept_ids": [1, 2, 3, 4], "entity_key": "target:primary:0:0"},
        ]
        from unittest.mock import MagicMock
        rc1, rc2, rc3, rc4 = MagicMock(), MagicMock(), MagicMock(), MagicMock()
        rc1.concept_id, rc1.domain_id = 1, "Observation"
        rc2.concept_id, rc2.domain_id = 2, "Observation"
        rc3.concept_id, rc3.domain_id = 3, "Condition"
        rc4.concept_id, rc4.domain_id = 4, "Drug"
        rs = MagicMock()
        rs.concepts = [rc1, rc2, rc3, rc4]

        mismatches = _check_domain_mismatches(mapped, [rs])

        assert mismatches[0]["concept_domains"] == ["Observation", "Observation", "Condition"]
        assert mismatches[0]["expected_domain_count"] == 1
        assert mismatches[0]["known_concept_count"] == 4
        assert mismatches[0]["unknown_domain_count"] == 0
        assert mismatches[0]["domain_counts"] == {"Observation": 2, "Condition": 1, "Drug": 1}
        assert mismatches[0]["dominant_domain"] == "Observation"
        assert mismatches[0]["dominant_ratio"] == 0.5


class TestReviewAssembly:

    def test_valid_assembly_proceeds(self):
        from unittest.mock import MagicMock
        val = MagicMock()
        val.valid = True
        val.errors = []
        state = {
            "validation": val,
            "heal_log": [],
            "retry_counts": {},
            "decisions": [],
            "error_log": [],
        }
        result = review_assembly(state)
        assert result["decisions"][0].action == "PROCEED"

    def test_no_validation_escalates(self):
        state = {
            "validation": None,
            "heal_log": [],
            "retry_counts": {},
            "decisions": [],
            "error_log": [],
        }
        result = review_assembly(state)
        assert result["decisions"][0].action == "ESCALATE"

    def test_invalid_at_max_retry_escalates(self):
        """Valid=False + max retries → ESCALATE, not PROCEED."""
        from unittest.mock import MagicMock
        val = MagicMock()
        val.valid = False
        val.errors = ["test error"]
        state = {
            "validation": val,
            "heal_log": [],
            "retry_counts": {"assembly": MAX_RETRY},
            "decisions": [],
            "error_log": [],
        }
        result = review_assembly(state)
        assert result["decisions"][0].action == "ESCALATE"


class TestReviewExtraction:

    def test_with_data_proceeds(self):
        data = list(range(100))  # anything with len() > 0
        state = {
            "patient_data": data,
            "execution_diagnostics": [],
            "retry_counts": {},
            "decisions": [],
            "error_log": [],
        }
        result = review_extraction(state)
        assert result["decisions"][0].action == "PROCEED"

    def test_no_data_retries(self):
        state = {
            "patient_data": None,
            "execution_diagnostics": [],
            "retry_counts": {"extraction": 0},
            "decisions": [],
            "error_log": [],
        }
        result = review_extraction(state)
        assert result["decisions"][0].action == "RETRY"

    def test_no_data_max_retry_escalates(self):
        state = {
            "patient_data": None,
            "execution_diagnostics": [],
            "retry_counts": {"extraction": MAX_RETRY},
            "decisions": [],
            "error_log": [],
        }
        result = review_extraction(state)
        assert result["decisions"][0].action == "ESCALATE"


class TestReviewAnalysis:

    def test_good_results_succeed(self):
        state = {
            "analysis_results": {
                "hazard_ratio": {"hr": 0.87, "p_value": 0.03},
                "n_target": 500,
                "n_comparator": 500,
            },
            "decisions": [],
            "error_log": [],
        }
        result = review_analysis(state)
        assert result["decisions"][0].action == "PROCEED"
        assert result["decisions"][0].status == "SUCCESS"

    def test_small_sample_warns(self):
        state = {
            "analysis_results": {
                "hazard_ratio": {"hr": 0.87, "p_value": 0.03},
                "n_target": 10,
                "n_comparator": 500,
            },
            "decisions": [],
            "error_log": [],
        }
        result = review_analysis(state)
        assert result["decisions"][0].status == "PARTIAL"


class TestReviewReporting:

    def test_report_path_succeeds(self):
        state = {
            "report_path": "./output/artemis_run/report.html",
            "plot_paths": {"balance": "./output/artemis_run/plots/balance.png"},
            "decisions": [],
            "error_log": [],
        }
        result = review_reporting(state)
        decision = result["decisions"][0]
        assert decision.agent_name == "reporting"
        assert decision.status == "SUCCESS"
        assert decision.action == "PROCEED"
        assert decision.metrics["has_report_path"] is True
        assert decision.metrics["plot_count"] == 1

    def test_fallback_report_summary_warns(self):
        state = {
            "report_summary": {
                "status": "fallback",
                "reason": "agent6_wrapper_unavailable:ImportError",
                "text": "Fallback report summary",
                "preview": {"generatedBy": "artemis-agent6-fallback"},
            },
            "decisions": [],
            "error_log": [],
        }
        result = review_reporting(state)
        decision = result["decisions"][0]
        assert decision.agent_name == "reporting"
        assert decision.status == "PARTIAL"
        assert decision.action == "PROCEED"
        assert "summary status=fallback" in decision.reason


# ══════════════════════════════════════════════════════════════
# Routing Tests
# ══════════════════════════════════════════════════════════════

class TestRouting:

    def test_route_trial_proceed(self):
        state = {"decisions": [SupervisorDecision("trial", "SUCCESS", "PROCEED", "ok")]}
        assert route_after_trial(state) == "mapping"

    def test_route_trial_escalate(self):
        state = {"decisions": [SupervisorDecision("trial", "FAILED", "ESCALATE", "fail")]}
        assert route_after_trial(state) == "mapping"

    def test_route_mapping_retry(self):
        state = {"decisions": [SupervisorDecision("mapping", "PARTIAL", "RETRY", "low rate")]}
        assert route_after_mapping(state) == "mapping"

    def test_route_mapping_proceed(self):
        state = {"decisions": [SupervisorDecision("mapping", "SUCCESS", "PROCEED", "ok")]}
        assert route_after_mapping(state) == "assembly"

    def test_route_mapping_escalate_still_proceeds(self):
        state = {"decisions": [SupervisorDecision("mapping", "FAILED", "ESCALATE", "fail")]}
        assert route_after_mapping(state) == "assembly"

    def test_route_assembly_retry_goes_to_mapping(self):
        state = {"decisions": [SupervisorDecision("assembly", "PARTIAL", "RETRY", "skipped")]}
        assert route_after_assembly(state) == "mapping"

    def test_route_assembly_escalate_still_proceeds(self):
        state = {"decisions": [SupervisorDecision("assembly", "FAILED", "ESCALATE", "fail")]}
        assert route_after_assembly(state) == "extraction"

    def test_route_extraction_retry(self):
        state = {"decisions": [SupervisorDecision("extraction", "PARTIAL", "RETRY", "0 pts")]}
        assert route_after_extraction(state) == "extraction"

    def test_route_extraction_escalate_still_proceeds(self):
        state = {"decisions": [SupervisorDecision("extraction", "FAILED", "ESCALATE", "fail")]}
        assert route_after_extraction(state) == "analysis"


# ══════════════════════════════════════════════════════════════
# High-Risk Entity Audit Tests
# ══════════════════════════════════════════════════════════════

class TestAuditHighRisk:
    """Tests for audit_high_risk_entities — flags entities that bypassed LLM verification."""

    def test_fast_path_flagged(self):
        mapped = [
            {"name": "Metformin", "domain": "Drug", "concept_ids": [1, 2],
             "route_path": "fast", "atc_expanded": False, "critic_skipped": False},
        ]
        result = audit_high_risk_entities(mapped)
        assert len(result) == 1
        assert result[0]["entity"] == "Metformin"
        assert "fast_path" in result[0]["triggers"]
        assert result[0]["concept_count"] == 2

    def test_atc_expanded_flagged(self):
        mapped = [
            {"name": "SGLT2 inhibitors", "domain": "Drug", "concept_ids": [10, 20, 30],
             "route_path": "atc", "atc_expanded": True, "critic_skipped": False},
        ]
        result = audit_high_risk_entities(mapped)
        assert len(result) == 1
        assert "atc_expanded" in result[0]["triggers"]
        assert result[0]["concept_count"] == 3

    def test_critic_skipped_flagged(self):
        mapped = [
            {"name": "T2DM", "domain": "Condition", "concept_ids": [100],
             "route_path": "slow", "atc_expanded": False, "critic_skipped": True},
        ]
        result = audit_high_risk_entities(mapped)
        assert len(result) == 1
        assert "critic_skipped" in result[0]["triggers"]

    def test_slow_path_not_flagged(self):
        """Slow path with full LLM verification should NOT be flagged."""
        mapped = [
            {"name": "Heart failure", "domain": "Condition", "concept_ids": [50, 51],
             "route_path": "slow", "atc_expanded": False, "critic_skipped": False},
        ]
        result = audit_high_risk_entities(mapped)
        assert result == []

    def test_audit_report_includes_high_risk(self):
        """audit_mapping_results should include high_risk_entities field."""
        mapped = [
            {"name": "Aspirin", "domain": "Drug", "concept_ids": [1],
             "route_path": "fast", "critic_skipped": True},
            {"name": "MI", "domain": "Condition", "concept_ids": [2, 3],
             "route_path": "slow", "critic_skipped": False},
        ]
        gap = GapReport(total_criteria=2, mapped_count=2)
        report = audit_mapping_results(mapped, [], gap)
        assert "high_risk_entities" in report
        assert len(report["high_risk_entities"]) == 1
        assert report["high_risk_entities"][0]["entity"] == "Aspirin"
        assert "fast_path" in report["high_risk_entities"][0]["triggers"]
        assert "critic_skipped" in report["high_risk_entities"][0]["triggers"]
        # High-risk warning should appear
        assert any("high-risk" in w for w in report["warnings"])
