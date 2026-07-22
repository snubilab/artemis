"""
Unit tests for Phase 4.1: Visualization Suite.
TDD: Tests written BEFORE implementation.
"""
import pytest
import numpy as np
from unittest.mock import Mock, patch
import os


class TestForestPlot:
    """Tests for Forest Plot generation."""
    
    def test_forest_plot_creation(self):
        """Forest plot should be creatable from HR data."""
        from src.reporting.plots.forest import ForestPlot
        
        data = [
            {"study": "Study A", "hr": 0.85, "ci_lower": 0.70, "ci_upper": 1.03},
            {"study": "Study B", "hr": 0.92, "ci_lower": 0.82, "ci_upper": 1.04},
        ]
        
        plot = ForestPlot(data)
        assert plot is not None
    
    def test_forest_plot_saves_to_file(self, tmp_path):
        """Forest plot should save to file."""
        from src.reporting.plots.forest import ForestPlot
        
        data = [
            {"study": "Treatment", "hr": 0.75, "ci_lower": 0.60, "ci_upper": 0.93},
        ]
        
        plot = ForestPlot(data)
        output_path = tmp_path / "forest.png"
        plot.save(str(output_path))
        
        assert output_path.exists()
    
    def test_forest_plot_reference_line(self):
        """Forest plot should include reference line at HR=1."""
        from src.reporting.plots.forest import ForestPlot
        
        data = [{"study": "Test", "hr": 0.9, "ci_lower": 0.8, "ci_upper": 1.0}]
        plot = ForestPlot(data)
        
        assert plot.reference_line == 1.0


class TestKMCurvePlot:
    """Tests for Kaplan-Meier survival curve plotting."""
    
    def test_km_curve_creation(self):
        """KM curve plot should accept fitted KM data."""
        from src.reporting.plots.km_curve import KMCurvePlot
        
        # Mock survival data
        times = [10, 20, 30, 40, 50]
        survival = [1.0, 0.9, 0.8, 0.7, 0.6]
        
        plot = KMCurvePlot()
        plot.add_curve(times, survival, label="Treatment")
        
        assert len(plot.curves) == 1
    
    def test_km_curve_multiple_groups(self):
        """KM plot should support multiple treatment groups."""
        from src.reporting.plots.km_curve import KMCurvePlot
        
        plot = KMCurvePlot()
        plot.add_curve([10, 20, 30], [1.0, 0.9, 0.8], label="Target")
        plot.add_curve([10, 20, 30], [1.0, 0.85, 0.7], label="Comparator")
        
        assert len(plot.curves) == 2
    
    def test_km_curve_saves_to_file(self, tmp_path):
        """KM curve should save to file."""
        from src.reporting.plots.km_curve import KMCurvePlot
        
        plot = KMCurvePlot()
        plot.add_curve([10, 20, 30], [1.0, 0.9, 0.8], label="Test")
        
        output_path = tmp_path / "km_curve.png"
        plot.save(str(output_path))
        
        assert output_path.exists()


class TestLovePlot:
    """Tests for Love Plot (SMD balance visualization)."""
    
    def test_love_plot_creation(self):
        """Love plot should accept SMD data."""
        from src.reporting.plots.love import LovePlot
        
        smd_data = {
            "age": {"before": 0.15, "after": 0.05},
            "bmi": {"before": 0.20, "after": 0.08},
        }
        
        plot = LovePlot(smd_data)
        assert plot is not None
    
    def test_love_plot_threshold(self):
        """Love plot should show threshold line at 0.1."""
        from src.reporting.plots.love import LovePlot
        
        smd_data = {"age": {"before": 0.15, "after": 0.05}}
        plot = LovePlot(smd_data)
        
        assert plot.threshold == 0.1


class TestPSDistPlot:
    """Tests for Propensity Score distribution plot."""
    
    def test_ps_dist_creation(self):
        """PS distribution plot should accept treated/control PS."""
        from src.reporting.plots.ps_dist import PSDistPlot
        
        ps_treated = np.array([0.3, 0.5, 0.7, 0.6])
        ps_control = np.array([0.2, 0.4, 0.5, 0.3])
        
        plot = PSDistPlot(ps_treated, ps_control)
        assert plot is not None
    
    def test_ps_dist_saves_to_file(self, tmp_path):
        """PS distribution should save to file."""
        from src.reporting.plots.ps_dist import PSDistPlot
        
        plot = PSDistPlot(
            ps_treated=np.array([0.5, 0.6, 0.7]),
            ps_control=np.array([0.3, 0.4, 0.5])
        )
        
        output_path = tmp_path / "ps_dist.png"
        plot.save(str(output_path))
        
        assert output_path.exists()
