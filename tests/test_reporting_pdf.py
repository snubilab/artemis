"""
Unit tests for Phase 4.2: Report Generation.
TDD: Tests written BEFORE implementation.
"""
import base64
import pytest
from pathlib import Path


class TestReportDataModel:
    """Tests for report data model."""
    
    def test_report_data_creation(self):
        """ReportData should be creatable with required fields."""
        from src.reporting.models import ReportData
        
        report = ReportData(
            study_title="Metformin vs Sulfonylurea for T2DM",
            target_cohort_size=1000,
            comparator_cohort_size=1000,
        )
        
        assert report.study_title == "Metformin vs Sulfonylurea for T2DM"
    
    def test_report_data_with_results(self):
        """ReportData should include analysis results."""
        from src.reporting.models import ReportData, HazardRatioSummary
        
        hr_result = HazardRatioSummary(
            hr=0.85,
            ci_lower=0.72,
            ci_upper=0.99,
            p_value=0.038
        )
        
        report = ReportData(
            study_title="Test Study",
            target_cohort_size=500,
            comparator_cohort_size=500,
            hazard_ratio=hr_result
        )
        
        assert report.hazard_ratio.hr == 0.85
    
    def test_report_data_with_paths(self):
        """ReportData should store plot file paths."""
        from src.reporting.models import ReportData
        
        report = ReportData(
            study_title="Test",
            target_cohort_size=100,
            comparator_cohort_size=100,
            km_plot_path="/path/to/km.png",
            forest_plot_path="/path/to/forest.png"
        )
        
        assert "km.png" in report.km_plot_path


class TestPDFGenerator:
    """Tests for PDF report generation."""
    
    def test_pdf_generator_initialization(self):
        """PDF generator should initialize with template."""
        from src.reporting.pdf_generator import PDFGenerator
        
        generator = PDFGenerator()
        assert generator is not None
    
    def test_render_html(self):
        """Generator should render HTML from data."""
        from src.reporting.pdf_generator import PDFGenerator
        from src.reporting.models import ReportData
        
        report_data = ReportData(
            study_title="Test Study",
            target_cohort_size=100,
            comparator_cohort_size=100
        )
        
        generator = PDFGenerator()
        html = generator.render_html(report_data)
        
        assert "Test Study" in html
        assert "<html" in html.lower()
    
    @pytest.mark.skip(reason="Requires WeasyPrint system libraries (gobject)")
    def test_generate_pdf(self, tmp_path):
        """Generator should produce PDF file."""
        from src.reporting.pdf_generator import PDFGenerator
        from src.reporting.models import ReportData
        
        report_data = ReportData(
            study_title="Test Study",
            target_cohort_size=100,
            comparator_cohort_size=100
        )
        
        generator = PDFGenerator()
        output_path = tmp_path / "report.pdf"
        generator.generate(report_data, str(output_path))
        
        assert output_path.exists()
        assert output_path.stat().st_size > 0


class TestReportSections:
    """Tests for individual report sections."""
    
    def test_executive_summary_section(self):
        """Executive summary should include key findings."""
        from src.reporting.sections import ExecutiveSummary
        from src.reporting.models import ReportData, HazardRatioSummary
        
        report_data = ReportData(
            study_title="TTE Study",
            target_cohort_size=1000,
            comparator_cohort_size=1000,
            hazard_ratio=HazardRatioSummary(hr=0.85, ci_lower=0.72, ci_upper=0.99, p_value=0.03)
        )
        
        summary = ExecutiveSummary(report_data)
        html = summary.render()
        
        assert "0.85" in html  # HR value
        assert "significant" in html.lower() or "p" in html.lower()
    
    def test_cohort_characteristics_section(self):
        """Cohort section should include demographics."""
        from src.reporting.sections import CohortCharacteristics

        section = CohortCharacteristics(
            target_n=1000,
            comparator_n=950,
            mean_age_target=65.2,
            mean_age_comparator=64.8
        )

        html = section.render()

        assert "1000" in html
        assert "950" in html


class TestReportDataBase64Fields:
    """Tests for base64 plot fields on ReportData."""

    def test_report_data_has_base64_fields(self):
        """ReportData should accept base64 plot strings."""
        from src.reporting.models import ReportData

        report = ReportData(
            study_title="Base64 Test",
            target_cohort_size=100,
            comparator_cohort_size=100,
            km_plot_base64="aGVsbG8=",
            forest_plot_base64="d29ybGQ=",
        )

        assert report.km_plot_base64 == "aGVsbG8="
        assert report.forest_plot_base64 == "d29ybGQ="
        assert report.love_plot_base64 is None
        assert report.ps_dist_plot_base64 is None

    def test_report_data_base64_defaults_to_none(self):
        """Base64 fields should default to None when not provided."""
        from src.reporting.models import ReportData

        report = ReportData(
            study_title="Defaults Test",
            target_cohort_size=50,
            comparator_cohort_size=50,
        )

        assert report.km_plot_base64 is None
        assert report.forest_plot_base64 is None
        assert report.love_plot_base64 is None
        assert report.ps_dist_plot_base64 is None


class TestEnhancedTemplate:
    """Tests for the enhanced DEFAULT_TEMPLATE."""

    def _render_html(self, **kwargs):
        from src.reporting.pdf_generator import PDFGenerator
        from src.reporting.models import ReportData

        report_data = ReportData(**kwargs)
        generator = PDFGenerator()
        return generator.render_html(report_data)

    def test_template_renders_study_title(self):
        """Template should render study title in h1."""
        html = self._render_html(
            study_title="Metformin TTE Study",
            target_cohort_size=500,
            comparator_cohort_size=500,
        )

        assert "Metformin TTE Study" in html
        assert "TTE Report" in html

    def test_template_renders_executive_summary_cards(self):
        """Template should render summary cards with cohort sizes."""
        html = self._render_html(
            study_title="Card Test",
            target_cohort_size=1234,
            comparator_cohort_size=5678,
        )

        assert "1,234" in html
        assert "5,678" in html
        assert "summary-card" in html

    def test_template_renders_hazard_ratio(self):
        """Template should render HR, CI, and p-value when provided."""
        from src.reporting.models import HazardRatioSummary

        hr = HazardRatioSummary(hr=0.85, ci_lower=0.72, ci_upper=0.99, p_value=0.038)
        html = self._render_html(
            study_title="HR Test",
            target_cohort_size=100,
            comparator_cohort_size=100,
            hazard_ratio=hr,
        )

        assert "0.85" in html
        assert "0.72" in html
        assert "0.99" in html
        assert "0.0380" in html
        assert "Statistically Significant" in html

    def test_template_renders_not_significant(self):
        """Template should show Not Significant when p >= 0.05."""
        from src.reporting.models import HazardRatioSummary

        hr = HazardRatioSummary(hr=1.02, ci_lower=0.80, ci_upper=1.30, p_value=0.85)
        html = self._render_html(
            study_title="NS Test",
            target_cohort_size=100,
            comparator_cohort_size=100,
            hazard_ratio=hr,
        )

        assert "Not Significant" in html
        assert "not-significant" in html

    def test_template_renders_study_design_table(self):
        """Template should render study design as a table."""
        html = self._render_html(
            study_title="Design Test",
            target_cohort_size=100,
            comparator_cohort_size=100,
            analysis_method="PSM",
            outcome_name="MACE",
        )

        assert "PSM" in html
        assert "MACE" in html
        assert "Study Design" in html

    def test_template_renders_median_followup(self):
        """Template should render median follow-up when provided."""
        html = self._render_html(
            study_title="Followup Test",
            target_cohort_size=100,
            comparator_cohort_size=100,
            median_followup_days=365.5,
        )

        assert "366" in html  # formatted as %.0f
        assert "days" in html

    def test_template_renders_base64_km_plot(self):
        """Template should embed base64 KM plot as data URI."""
        fake_b64 = base64.b64encode(b"fake-png-data").decode("ascii")
        html = self._render_html(
            study_title="KM Base64",
            target_cohort_size=100,
            comparator_cohort_size=100,
            km_plot_base64=fake_b64,
        )

        assert f"data:image/png;base64,{fake_b64}" in html
        assert "Kaplan-Meier" in html

    def test_template_prefers_base64_over_path(self):
        """Template should use base64 when both base64 and path are provided."""
        fake_b64 = base64.b64encode(b"png-bytes").decode("ascii")
        html = self._render_html(
            study_title="Prefer Base64",
            target_cohort_size=100,
            comparator_cohort_size=100,
            km_plot_base64=fake_b64,
            km_plot_path="/path/to/km.png",
        )

        assert f"data:image/png;base64,{fake_b64}" in html
        assert "/path/to/km.png" not in html

    def test_template_falls_back_to_path(self):
        """Template should use path when base64 is not available."""
        html = self._render_html(
            study_title="Path Fallback",
            target_cohort_size=100,
            comparator_cohort_size=100,
            km_plot_path="/plots/km.png",
        )

        assert 'src="/plots/km.png"' in html

    def test_template_renders_all_four_base64_plots(self):
        """Template should embed all four plot types as base64."""
        fake_b64 = base64.b64encode(b"test").decode("ascii")
        html = self._render_html(
            study_title="All Plots",
            target_cohort_size=100,
            comparator_cohort_size=100,
            km_plot_base64=fake_b64,
            forest_plot_base64=fake_b64,
            love_plot_base64=fake_b64,
            ps_dist_plot_base64=fake_b64,
        )

        assert "Kaplan-Meier" in html
        assert "Forest Plot" in html
        assert "Love Plot" in html
        assert "Propensity Score Distribution" in html
        assert html.count("data:image/png;base64,") == 4

    def test_template_renders_balance_summary(self):
        """Template should render covariate balance table."""
        from src.reporting.models import CovariateBalance

        balance = [
            CovariateBalance(name="Age", smd_before=0.25, smd_after=0.05, mean_treated=65.0, mean_control=63.0),
            CovariateBalance(name="Gender", smd_before=0.15, smd_after=0.18, mean_treated=0.5, mean_control=0.48),
        ]
        html = self._render_html(
            study_title="Balance Test",
            target_cohort_size=100,
            comparator_cohort_size=100,
            balance_summary=balance,
        )

        assert "Covariate Balance" in html
        assert "Age" in html
        assert "0.250" in html  # smd_before
        assert "0.050" in html  # smd_after
        assert "badge-good" in html  # Age smd_after=0.05 < 0.1
        assert "badge-fair" in html  # Gender smd_after=0.18, 0.1 <= x < 0.2

    def test_template_renders_footer(self):
        """Template should have ARTEMIS footer."""
        html = self._render_html(
            study_title="Footer Test",
            target_cohort_size=100,
            comparator_cohort_size=100,
        )

        assert "ARTEMIS 3.1" in html
        assert "<footer>" in html

    def test_template_has_print_styles(self):
        """Template should include print media query."""
        html = self._render_html(
            study_title="Print Test",
            target_cohort_size=100,
            comparator_cohort_size=100,
        )

        assert "@media print" in html


class TestAgent6EncodeBase64:
    """Tests for Agent6Workflow._encode_plot_base64."""

    def test_encode_existing_file(self, tmp_path):
        """Should return base64 string for an existing PNG file."""
        from src.agents.agent6.workflow import Agent6Workflow

        png_file = tmp_path / "test.png"
        png_file.write_bytes(b"\x89PNG\r\n\x1a\nfake-data")

        workflow = Agent6Workflow()
        result = workflow._encode_plot_base64(str(png_file))

        assert result is not None
        decoded = base64.b64decode(result)
        assert decoded == b"\x89PNG\r\n\x1a\nfake-data"

    def test_encode_nonexistent_file(self):
        """Should return None for a nonexistent file."""
        from src.agents.agent6.workflow import Agent6Workflow

        workflow = Agent6Workflow()
        result = workflow._encode_plot_base64("/nonexistent/path/plot.png")

        assert result is None

    def test_encode_empty_path(self):
        """Should return None for an empty path string."""
        from src.agents.agent6.workflow import Agent6Workflow

        workflow = Agent6Workflow()
        result = workflow._encode_plot_base64("")

        assert result is None


class TestAgent6BuildBalanceSummary:
    """Tests for Agent6Workflow._build_balance_summary."""

    def test_build_balance_from_dict(self):
        """Should convert balance dict to CovariateBalance list."""
        from src.agents.agent6.workflow import Agent6Workflow

        workflow = Agent6Workflow()
        workflow.results = {
            "balance": {
                "Age": {"smd_before": 0.25, "smd_after": 0.05, "mean_treated": 65.0, "mean_control": 63.0},
                "BMI": {"smd_before": 0.30, "smd_after": 0.08, "mean_treated": 28.0, "mean_control": 26.0},
            }
        }

        result = workflow._build_balance_summary()

        assert result is not None
        assert len(result) == 2
        names = {item.name for item in result}
        assert "Age" in names
        assert "BMI" in names

    def test_build_balance_returns_none_when_no_balance(self):
        """Should return None when no balance data."""
        from src.agents.agent6.workflow import Agent6Workflow

        workflow = Agent6Workflow()
        workflow.results = {"hazard_ratio": None}

        assert workflow._build_balance_summary() is None

    def test_build_balance_returns_none_when_no_results(self):
        """Should return None when results is None."""
        from src.agents.agent6.workflow import Agent6Workflow

        workflow = Agent6Workflow()
        workflow.results = None

        assert workflow._build_balance_summary() is None
