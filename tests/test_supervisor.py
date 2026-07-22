"""
Unit tests for PipelineSupervisor — Post-Agent2 quality gate.
DB 의존성 없음. Mock 기반.
"""
import sys
import types
import threading
import time
import pytest

# ── pandas stub to avoid import error from cohort_executor ──
_injected_pandas = False
try:
    import pandas  # noqa: F401
except Exception:
    pd_stub = types.ModuleType("pandas")
    pd_stub.DataFrame = type("DataFrame", (), {"__init__": lambda self, *a, **k: None})  # type: ignore
    sys.modules["pandas"] = pd_stub
    _injected_pandas = True

from src.pipeline.supervisor import (
    PipelineSupervisor,
    SupervisorReport,
    RetryReason,
    MIN_SEED_COUNT,
)
from src.models.ir import GapReport


def teardown_module():
    if _injected_pandas:
        sys.modules.pop("pandas", None)


def _make_parallel_mapping_ir():
    from src.models.ir import (
        ARTEMISRequest,
        CohortDefinition,
        CohortOutcome,
        Criteria,
        PrimaryCriteria,
        TemporalWindow,
    )

    return ARTEMISRequest(
        target=CohortDefinition(
            primary_criteria=PrimaryCriteria(domain="Drug", entity_text="TargetDrug"),
            inclusion_rules=[
                Criteria(name="Rule 1", domain="Condition", entity_text="RetryCondition"),
                Criteria(name="Rule 2", domain="Condition", entity_text="SlowCondition"),
            ],
        ),
        comparator=CohortDefinition(
            primary_criteria=PrimaryCriteria(domain="Drug", entity_text="ComparatorDrug"),
        ),
        outcome=CohortOutcome(
            name="Primary outcome",
            domain="Condition",
            entity_text="OutcomeCondition",
            time_at_risk=TemporalWindow(start=0, end=365),
        ),
    )


class _FakeEntityMappingResult:
    def __init__(self, *, concept_ids=None, error=None, route_path="slow", processing_time_ms=0.0):
        self.concept_ids = concept_ids or []
        self.overbroad_concept_ids = []
        self.route_path = route_path
        self.atc_expanded = False
        self.critic_skipped = False
        self.domain_overridden = None
        self.error = error
        self.processing_time_ms = processing_time_ms

    @property
    def success(self):
        return bool(self.concept_ids) and self.error is None

    def to_mapped_set(self, *, entity_id, entity_text, domain, source="inclusion", parent_rule=None, entity_key=None):
        mapped = {
            "id": entity_id,
            "name": entity_text,
            "domain": domain,
            "concept_ids": self.concept_ids,
            "source": source,
        }
        if parent_rule:
            mapped["parent_rule"] = parent_rule
        if entity_key:
            mapped["entity_key"] = entity_key
        return mapped


class TestSupervisorConfig:
    """Configuration tests."""

    def test_min_seed_count_default_is_1(self):
        """Lab Meeting 결론: MIN_SEED_COUNT=1 (empty gate only)."""
        assert MIN_SEED_COUNT == 1


class TestPostAgent2Check:
    """post_agent2_check() quality gate tests."""

    def setup_method(self):
        self.supervisor = PipelineSupervisor()

    def test_empty_entity(self):
        """매핑 안 된 entity → reason='empty'."""
        entities = [
            {"text": "Liraglutide", "domain": "Drug", "source": "target"},
            {"text": "Unknown Disease", "domain": "Condition", "source": "target"},
        ]
        mapped_sets = [
            {"name": "Liraglutide", "concept_ids": [1234], "domain": "Drug"},
        ]
        gap = GapReport()

        report = self.supervisor.post_agent2_check(mapped_sets, gap, entities)

        assert report.entities_checked == 2
        assert report.entities_ok == 1
        assert report.retries_triggered == 1
        assert report.retry_reasons[0].entity_text == "Unknown Disease"
        assert report.retry_reasons[0].reason == "empty"

    def test_all_ok(self):
        """모든 entity 매핑 성공 → retries_triggered=0."""
        entities = [
            {"text": "Metformin", "domain": "Drug", "source": "target"},
            {"text": "Type 2 Diabetes", "domain": "Condition", "source": "target"},
        ]
        mapped_sets = [
            {"name": "Metformin", "concept_ids": [1503297], "domain": "Drug"},
            {"name": "Type 2 Diabetes", "concept_ids": [201826, 443238], "domain": "Condition"},
        ]
        gap = GapReport()

        report = self.supervisor.post_agent2_check(mapped_sets, gap, entities)

        assert report.retries_triggered == 0
        assert report.entities_ok == 2

    def test_disabled(self):
        """ENABLE_SUPERVISOR=0 → 빈 report."""
        self.supervisor.enabled = False
        entities = [{"text": "Test", "domain": "Drug", "source": "target"}]
        gap = GapReport()

        report = self.supervisor.post_agent2_check([], gap, entities)

        assert report.entities_checked == 0
        assert report.retries_triggered == 0

    def test_single_seed_is_ok(self):
        """seed_count=1 → OK (MIN_SEED_COUNT=1이므로 low_seeds 아님)."""
        entities = [
            {"text": "Empagliflozin", "domain": "Drug", "source": "target"},
        ]
        mapped_sets = [
            {"name": "Empagliflozin", "concept_ids": [43009032], "domain": "Drug"},
        ]
        gap = GapReport()

        report = self.supervisor.post_agent2_check(mapped_sets, gap, entities)

        assert report.entities_ok == 1
        assert report.retries_triggered == 0


class TestStep2MapParallelFallback:
    def _install_fake_map_module(self, monkeypatch, fn):
        fake_map_entity = types.ModuleType("src.agents.agent2.map_entity")
        fake_map_entity.map_single_entity = fn
        monkeypatch.setitem(sys.modules, "src.agents.agent2.map_entity", fake_map_entity)

    def test_parallel_mapping_preserves_entity_order(self, monkeypatch):
        monkeypatch.setenv("SUPERVISOR_AGENT2_PARALLEL", "1")
        monkeypatch.setenv("SUPERVISOR_AGENT2_MAX_WORKERS", "4")
        thread_names = []
        sleep_by_text = {
            "TargetDrug": 0.03,
            "RetryCondition": 0.01,
            "SlowCondition": 0.04,
            "ComparatorDrug": 0.02,
            "OutcomeCondition": 0.01,
        }

        def fake_map_single_entity(entity_text, **kwargs):
            thread_names.append(threading.current_thread().name)
            time.sleep(sleep_by_text[entity_text])
            return _FakeEntityMappingResult(concept_ids=[len(entity_text)])

        self._install_fake_map_module(monkeypatch, fake_map_single_entity)

        mapped_sets, gap, entities, telemetry = PipelineSupervisor._step2_map(_make_parallel_mapping_ir(), lambda: None)

        assert gap.unmapped_count == 0
        assert [item["name"] for item in mapped_sets] == [entity["text"] for entity in entities]
        assert any(name != threading.main_thread().name for name in thread_names)
        assert telemetry.mode == "parallel"
        assert telemetry.parallel_enabled is True
        assert telemetry.max_workers_used >= 1
        assert telemetry.entity_count == len(entities)
        assert telemetry.success_count == len(entities)
        assert telemetry.sequential_retry_count == 0
        assert telemetry.pool_fallback is False
        assert telemetry.wall_time_ms > 0
        assert telemetry.route_counts["slow"] == len(entities)

    def test_parallel_mapping_retries_failed_entity_sequentially(self, monkeypatch):
        monkeypatch.setenv("SUPERVISOR_AGENT2_PARALLEL", "1")
        monkeypatch.setenv("SUPERVISOR_AGENT2_MAX_WORKERS", "4")
        attempts = {"RetryCondition": 0}

        def fake_map_single_entity(entity_text, **kwargs):
            if entity_text == "RetryCondition":
                attempts["RetryCondition"] += 1
                if threading.current_thread() is not threading.main_thread():
                    return _FakeEntityMappingResult(error="parallel failure")
            return _FakeEntityMappingResult(concept_ids=[len(entity_text)])

        self._install_fake_map_module(monkeypatch, fake_map_single_entity)

        mapped_sets, gap, entities, telemetry = PipelineSupervisor._step2_map(_make_parallel_mapping_ir(), lambda: None)

        assert attempts["RetryCondition"] == 2
        assert gap.unmapped_count == 0
        assert [item["name"] for item in mapped_sets] == [entity["text"] for entity in entities]
        assert telemetry.sequential_retry_count == 1
        assert telemetry.success_count == len(entities)
        retry_report = next(item for item in telemetry.entity_reports if item.entity_key == "target:inclusion:0:0")
        assert retry_report.used_sequential_retry is True
        assert retry_report.final_status == "success"

    def test_parallel_mapping_pool_failure_falls_back_to_sequential(self, monkeypatch):
        monkeypatch.setenv("SUPERVISOR_AGENT2_PARALLEL", "1")
        thread_names = []

        def fake_map_single_entity(entity_text, **kwargs):
            thread_names.append(threading.current_thread().name)
            return _FakeEntityMappingResult(concept_ids=[len(entity_text)])

        class ExplodingExecutor:
            def __init__(self, *args, **kwargs):
                raise RuntimeError("pool unavailable")

        self._install_fake_map_module(monkeypatch, fake_map_single_entity)
        monkeypatch.setattr("src.pipeline.supervisor.ThreadPoolExecutor", ExplodingExecutor, raising=False)

        mapped_sets, gap, entities, telemetry = PipelineSupervisor._step2_map(_make_parallel_mapping_ir(), lambda: None)

        assert gap.unmapped_count == 0
        assert len(mapped_sets) == len(entities)
        assert thread_names
        assert all(name == threading.main_thread().name for name in thread_names)
        assert telemetry.pool_fallback is True
        assert telemetry.pool_fallback_error == "pool unavailable"
        assert telemetry.mode == "sequential"

    def test_parallel_mapping_can_be_disabled_via_env(self, monkeypatch):
        monkeypatch.setenv("SUPERVISOR_AGENT2_PARALLEL", "0")
        thread_names = []

        def fake_map_single_entity(entity_text, **kwargs):
            thread_names.append(threading.current_thread().name)
            return _FakeEntityMappingResult(concept_ids=[len(entity_text)])

        self._install_fake_map_module(monkeypatch, fake_map_single_entity)

        mapped_sets, gap, entities, telemetry = PipelineSupervisor._step2_map(_make_parallel_mapping_ir(), lambda: None)

        assert gap.unmapped_count == 0
        assert len(mapped_sets) == len(entities)
        assert thread_names
        assert all(name == threading.main_thread().name for name in thread_names)
        assert telemetry.parallel_enabled is False
        assert telemetry.mode == "sequential"
        assert telemetry.pool_fallback is False

    def test_parallel_mapping_trace_and_slow_warning(self, monkeypatch, caplog):
        monkeypatch.setenv("SUPERVISOR_AGENT2_PARALLEL", "1")
        monkeypatch.setenv("SUPERVISOR_AGENT2_PARALLEL_TRACE", "1")
        monkeypatch.setenv("SUPERVISOR_AGENT2_PARALLEL_SLOW_MS", "1")

        def fake_map_single_entity(entity_text, **kwargs):
            time.sleep(0.01)
            return _FakeEntityMappingResult(
                concept_ids=[len(entity_text)],
                route_path="slow",
                processing_time_ms=12.0,
            )

        self._install_fake_map_module(monkeypatch, fake_map_single_entity)

        with caplog.at_level("INFO"):
            _mapped_sets, _gap, entities, telemetry = PipelineSupervisor._step2_map(
                _make_parallel_mapping_ir(), lambda: None
            )

        assert telemetry.entity_count == len(entities)
        assert "Agent 2 parallel batch start" in caplog.text
        assert "Agent 2 parallel batch summary" in caplog.text
        assert "Agent 2 entity trace" in caplog.text
        assert "Agent 2 slow entity" in caplog.text


class TestSupervisorReport:
    """SupervisorReport model tests."""

    def test_summary(self):
        report = SupervisorReport(entities_checked=10, entities_ok=8, retries_triggered=2)
        assert "10 checked" in report.summary
        assert "8 OK" in report.summary
        assert "2 retried" in report.summary

    def test_detailed_log_field(self):
        """detailed_log 필드 존재."""
        report = SupervisorReport()
        assert isinstance(report.detailed_log, list)
        report.detailed_log.append("Test log entry")
        assert len(report.detailed_log) == 1


class TestEntityKey:
    """Tests for stable entity_key generation."""

    def test_primary_criteria_key(self):
        """Primary criteria should get key '{source}:primary:0:0'."""
        from src.models.ir import CohortDefinition, PrimaryCriteria
        cohort = CohortDefinition(
            primary_criteria=PrimaryCriteria(domain="Drug", entity_text="Metformin"),
        )
        entities = PipelineSupervisor._collect_cohort_entities(cohort, "target")
        assert len(entities) == 1
        assert entities[0]["entity_key"] == "target:primary:0:0"

    def test_inclusion_rule_keys(self):
        """Inclusion rules should get keys '{source}:inclusion:{idx}:0'."""
        from src.models.ir import CohortDefinition, PrimaryCriteria, Criteria
        cohort = CohortDefinition(
            primary_criteria=PrimaryCriteria(domain="Drug", entity_text="Metformin"),
            inclusion_rules=[
                Criteria(name="Rule A", domain="Condition", entity_text="T2DM"),
                Criteria(name="Rule B", domain="Drug", entity_text="Aspirin"),
            ],
        )
        entities = PipelineSupervisor._collect_cohort_entities(cohort, "target")
        assert entities[0]["entity_key"] == "target:primary:0:0"
        assert entities[1]["entity_key"] == "target:inclusion:0:0"
        assert entities[2]["entity_key"] == "target:inclusion:1:0"

    def test_sub_criteria_keys(self):
        """Sub-criteria should get keys '{source}:{section}:{rule_idx}:{sub_idx}'."""
        from src.models.ir import Criteria
        rule = Criteria(
            name="Drug class",
            domain="Drug",
            entity_text="Fibrinolytic agents",
            sub_criteria=[
                Criteria(name="sc0", domain="Drug", entity_text="Alteplase"),
                Criteria(name="sc1", domain="Drug", entity_text="Tenecteplase"),
            ],
        )
        entities = PipelineSupervisor._collect_rule_entities(rule, "target", "inclusion", 2)
        # Hierarchical expansion: original text + 2 sub_criteria
        assert len(entities) == 3
        # Original gets sub_idx=-1 and is inserted at position 0
        assert entities[0]["entity_key"] == "target:inclusion:2:-1"
        assert entities[1]["entity_key"] == "target:inclusion:2:0"
        assert entities[2]["entity_key"] == "target:inclusion:2:1"

    def test_exclusion_rule_key(self):
        """Exclusion rules should use section='exclusion'."""
        from src.models.ir import CohortDefinition, PrimaryCriteria, Criteria
        cohort = CohortDefinition(
            primary_criteria=PrimaryCriteria(domain="Drug", entity_text="Metformin"),
            exclusion_rules=[
                Criteria(name="Excl", domain="Condition", entity_text="Pregnancy"),
            ],
        )
        entities = PipelineSupervisor._collect_cohort_entities(cohort, "comparator")
        assert entities[1]["entity_key"] == "comparator:exclusion:0:0"
