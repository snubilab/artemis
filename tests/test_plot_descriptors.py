"""Unit tests for plot descriptor builders: KM curve, Forest plot, PS distribution."""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Lightweight stubs so we can import the service without heavy dependencies.
# ---------------------------------------------------------------------------
_STUB_MODULES = [
    "chromadb",
    "langchain",
    "langchain.chat_models",
    "langchain.schema",
    "openai",
    "pandas",
    "scipy",
    "scipy.stats",
    "sklearn",
    "sklearn.linear_model",
]


@pytest.fixture(autouse=True)
def _stub_heavy_deps(monkeypatch: pytest.MonkeyPatch):
    """Inject lightweight stubs for heavy third-party packages."""
    for mod_name in _STUB_MODULES:
        if mod_name not in sys.modules:
            stub = types.ModuleType(mod_name)
            # Provide commonly accessed attributes so downstream imports don't fail
            if mod_name == "openai":
                stub.OpenAI = type("OpenAI", (), {})  # type: ignore[attr-defined]
            monkeypatch.setitem(sys.modules, mod_name, stub)


# ---------------------------------------------------------------------------
# Import the models we actually test against.
# ---------------------------------------------------------------------------
from src.api.models.tte import (
    AnalysisPlotDescriptor,
    AnalysisPlotPoint,
    AnalysisPlotSeries,
    AnalysisResultPayload,
    CovariateBalanceItem,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_service():
    """Create a minimal TTEService instance for calling private helpers."""
    from src.services.tte_service import TTEService

    return TTEService.__new__(TTEService)


# ===========================================================================
# AnalysisPlotDescriptor model tests
# ===========================================================================

class TestPlotTypeEnum:
    def test_accepts_km_curve(self):
        d = AnalysisPlotDescriptor(key="k", title="t", plotType="km_curve")
        assert d.plotType == "km_curve"

    def test_accepts_forest(self):
        d = AnalysisPlotDescriptor(key="k", title="t", plotType="forest")
        assert d.plotType == "forest"

    def test_accepts_ps_distribution(self):
        d = AnalysisPlotDescriptor(key="k", title="t", plotType="ps_distribution")
        assert d.plotType == "ps_distribution"

    def test_rejects_unknown_type(self):
        with pytest.raises(Exception):
            AnalysisPlotDescriptor(key="k", title="t", plotType="unknown_type")


class TestAnalysisResultPayloadNewFields:
    def test_default_ps_scores_empty(self):
        p = AnalysisResultPayload(generatedBy="test")
        assert p.psScores == []

    def test_default_treatment_array_empty(self):
        p = AnalysisResultPayload(generatedBy="test")
        assert p.treatmentArray == []

    def test_ps_scores_round_trip(self):
        p = AnalysisResultPayload(generatedBy="test", psScores=[0.1, 0.9], treatmentArray=[1, 0])
        d = p.model_dump()
        assert d["psScores"] == [0.1, 0.9]
        assert d["treatmentArray"] == [1, 0]


# ===========================================================================
# _compute_km_series tests
# ===========================================================================

class TestComputeKmSeries:
    def test_empty_input_returns_empty(self):
        svc = _make_service()
        assert svc._compute_km_series([], []) == []

    def test_no_events_returns_flat_survival(self):
        svc = _make_service()
        points = svc._compute_km_series([10, 20, 30], [0, 0, 0])
        # First point is always (0, 1.0); no events means no additional drops
        assert points[0].x == 0
        assert points[0].y == 1.0
        assert len(points) == 1  # only the initial point

    def test_all_events_survival_decreases(self):
        svc = _make_service()
        points = svc._compute_km_series([10, 20, 30], [1, 1, 1])
        assert points[0].y == 1.0
        # Each event drops survival
        assert points[-1].y < 1.0

    def test_km_first_event_probability(self):
        """With 3 subjects and event at first time, S(t1) = 1 - 1/3 = 0.6667."""
        svc = _make_service()
        points = svc._compute_km_series([5, 10, 15], [1, 0, 0])
        # point[0] = (0, 1.0), point[1] = (5, ~0.6667)
        assert len(points) == 2
        assert points[1].x == 5.0
        assert abs(points[1].y - 0.6667) < 0.001

    def test_km_sorted_by_time(self):
        """Times should be sorted before processing."""
        svc = _make_service()
        points = svc._compute_km_series([30, 10, 20], [1, 1, 0])
        xs = [p.x for p in points]
        assert xs == sorted(xs)

    def test_km_mismatched_lengths_uses_min(self):
        svc = _make_service()
        points = svc._compute_km_series([10, 20], [1, 1, 1])
        # Should use min(2, 3) = 2 subjects
        assert len(points) >= 1


# ===========================================================================
# Forest plot descriptor tests
# ===========================================================================

class TestForestPlotDescriptor:
    def test_forest_plot_created_with_hr(self):
        svc = _make_service()
        plots = svc._build_analysis_plot_descriptors(
            [],
            {},
            hazard_ratio={"hr": 0.75, "ci_lower": 0.6, "ci_upper": 0.95, "p_value": 0.01},
        )
        forest = [p for p in plots if p.key == "forest_plot_hr"]
        assert len(forest) == 1
        assert forest[0].plotType == "forest"

    def test_forest_plot_has_hr_and_ci_series(self):
        svc = _make_service()
        plots = svc._build_analysis_plot_descriptors(
            [],
            {},
            hazard_ratio={"hr": 1.2, "ci_lower": 0.9, "ci_upper": 1.5, "p_value": 0.2},
        )
        forest = [p for p in plots if p.key == "forest_plot_hr"][0]
        assert len(forest.series) == 2
        assert forest.series[0].name == "HR"
        assert forest.series[0].points[0].x == 1.2
        assert forest.series[1].name == "CI"
        assert forest.series[1].points[0].x == 0.9
        assert forest.series[1].points[1].x == 1.5

    def test_forest_plot_not_created_without_hr(self):
        svc = _make_service()
        plots = svc._build_analysis_plot_descriptors([], {})
        forest = [p for p in plots if p.key == "forest_plot_hr"]
        assert len(forest) == 0

    def test_forest_plot_not_created_with_none_hr(self):
        svc = _make_service()
        plots = svc._build_analysis_plot_descriptors(
            [],
            {},
            hazard_ratio={"hr": None, "ci_lower": None, "ci_upper": None, "p_value": None},
        )
        forest = [p for p in plots if p.key == "forest_plot_hr"]
        assert len(forest) == 0


# ===========================================================================
# KM survival curve descriptor tests
# ===========================================================================

class TestKmSurvivalDescriptor:
    def test_km_descriptor_created_with_survival_data(self):
        svc = _make_service()
        survival = {
            "times_treated": [5, 10, 15],
            "events_treated": [1, 0, 1],
            "times_control": [5, 10, 15],
            "events_control": [0, 1, 0],
        }
        plots = svc._build_analysis_plot_descriptors([], survival)
        km = [p for p in plots if p.key == "km_survival_curve"]
        assert len(km) == 1
        assert km[0].plotType == "km_curve"

    def test_km_descriptor_has_two_series(self):
        svc = _make_service()
        survival = {
            "times_treated": [5, 10],
            "events_treated": [1, 0],
            "times_control": [5, 10],
            "events_control": [0, 1],
        }
        plots = svc._build_analysis_plot_descriptors([], survival)
        km = [p for p in plots if p.key == "km_survival_curve"][0]
        assert len(km.series) == 2
        assert km.series[0].name == "Treatment"
        assert km.series[1].name == "Comparator"

    def test_km_descriptor_not_created_with_empty_survival(self):
        svc = _make_service()
        plots = svc._build_analysis_plot_descriptors([], {})
        km = [p for p in plots if p.key == "km_survival_curve"]
        assert len(km) == 0


# ===========================================================================
# PS distribution descriptor tests
# ===========================================================================

class TestPsDistributionDescriptor:
    def test_ps_distribution_created_with_scores(self):
        svc = _make_service()
        plots = svc._build_analysis_plot_descriptors(
            [],
            {},
            ps_scores=[0.2, 0.5, 0.8, 0.3, 0.7],
            treatment_flags=[1, 1, 0, 0, 1],
        )
        ps = [p for p in plots if p.key == "ps_distribution"]
        assert len(ps) == 1
        assert ps[0].plotType == "ps_distribution"

    def test_ps_distribution_has_treated_and_control(self):
        svc = _make_service()
        plots = svc._build_analysis_plot_descriptors(
            [],
            {},
            ps_scores=[0.2, 0.8],
            treatment_flags=[1, 0],
        )
        ps = [p for p in plots if p.key == "ps_distribution"][0]
        assert len(ps.series) == 2
        assert ps.series[0].name == "Treated"
        assert ps.series[1].name == "Control"

    def test_ps_distribution_10_bins(self):
        svc = _make_service()
        plots = svc._build_analysis_plot_descriptors(
            [],
            {},
            ps_scores=[0.15, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85],
            treatment_flags=[1, 1, 1, 1, 0, 0, 0, 0],
        )
        ps = [p for p in plots if p.key == "ps_distribution"][0]
        assert len(ps.series[0].points) == 10
        assert len(ps.series[1].points) == 10

    def test_ps_distribution_bin_centers(self):
        svc = _make_service()
        plots = svc._build_analysis_plot_descriptors(
            [],
            {},
            ps_scores=[0.05],
            treatment_flags=[1],
        )
        ps = [p for p in plots if p.key == "ps_distribution"][0]
        # Bin centers: 0.05, 0.15, 0.25, ..., 0.95
        assert ps.series[0].points[0].x == 0.05
        assert ps.series[0].points[9].x == 0.95

    def test_ps_distribution_not_created_without_scores(self):
        svc = _make_service()
        plots = svc._build_analysis_plot_descriptors([], {})
        ps = [p for p in plots if p.key == "ps_distribution"]
        assert len(ps) == 0

    def test_ps_distribution_not_created_with_mismatched_lengths(self):
        svc = _make_service()
        plots = svc._build_analysis_plot_descriptors(
            [],
            {},
            ps_scores=[0.5, 0.6],
            treatment_flags=[1],
        )
        ps = [p for p in plots if p.key == "ps_distribution"]
        assert len(ps) == 0

    def test_ps_distribution_counts_correct(self):
        """Score 0.15 -> bin 1 (center 0.15), score 0.85 -> bin 8 (center 0.85)."""
        svc = _make_service()
        plots = svc._build_analysis_plot_descriptors(
            [],
            {},
            ps_scores=[0.15, 0.85],
            treatment_flags=[1, 0],
        )
        ps = [p for p in plots if p.key == "ps_distribution"][0]
        treated = ps.series[0]  # Treated
        control = ps.series[1]  # Control
        # Bin index 1 (center 0.15) should have 1 treated
        assert treated.points[1].y == 1.0
        # Bin index 8 (center 0.85) should have 1 control
        assert control.points[8].y == 1.0


# ===========================================================================
# _build_ps_distribution_series unit tests
# ===========================================================================

class TestBuildPsDistributionSeries:
    def test_empty_returns_empty(self):
        svc = _make_service()
        assert svc._build_ps_distribution_series([], []) == []

    def test_boundary_score_1_goes_to_last_bin(self):
        svc = _make_service()
        series = svc._build_ps_distribution_series([1.0], [1])
        # Score 1.0 -> min(int(1.0/0.1), 9) = min(10, 9) = 9
        assert series[0].points[9].y == 1.0

    def test_boundary_score_0_goes_to_first_bin(self):
        svc = _make_service()
        series = svc._build_ps_distribution_series([0.0], [0])
        assert series[1].points[0].y == 1.0  # Control


# ===========================================================================
# Integration: all plots together
# ===========================================================================

class TestAllPlotsIntegration:
    def test_all_plot_types_generated(self):
        svc = _make_service()
        balance = [CovariateBalanceItem(name="Age", beforePS=0.2, afterPS=0.05)]
        survival = {
            "times_treated": [5, 10, 15],
            "events_treated": [1, 0, 1],
            "times_control": [5, 10, 15],
            "events_control": [0, 1, 0],
        }
        plots = svc._build_analysis_plot_descriptors(
            balance,
            survival,
            hazard_ratio={"hr": 0.8, "ci_lower": 0.6, "ci_upper": 1.0, "p_value": 0.05},
            ps_scores=[0.3, 0.5, 0.7],
            treatment_flags=[1, 0, 1],
        )
        keys = {p.key for p in plots}
        assert "love_plot_after_matching" in keys
        assert "cumulative_mortality_28d" in keys
        assert "km_survival_curve" in keys
        assert "forest_plot_hr" in keys
        assert "ps_distribution" in keys
