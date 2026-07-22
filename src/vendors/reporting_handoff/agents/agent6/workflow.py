"""
Agent 6: Reporting Agent.
Phase 4.3: Generates visualizations and PDF reports from analysis results.
"""
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from pathlib import Path
import numpy as np


@dataclass
class ReportConfig:
    """Configuration for Agent 6 reporting."""
    output_dir: str = "./output"
    include_km_plot: bool = True
    include_forest_plot: bool = True
    include_love_plot: bool = True
    include_ps_dist: bool = True


class Agent6Workflow:
    """
    Reporting Agent - generates visualizations and reports.
    
    Steps:
    1. Accept analysis results from Agent 5
    2. Generate visualizations (KM, Forest, Love, PS dist)
    3. Compile PDF report
    """
    
    def __init__(self, config: Optional[ReportConfig] = None):
        self.config = config or ReportConfig()
        self.results: Optional[Dict[str, Any]] = None
        self.study_title: str = "Untitled Study"
        self.plot_paths: Dict[str, str] = {}
    
    def set_results(
        self,
        study_title: str,
        hazard_ratio: Any,
        target_n: int,
        comparator_n: int,
        balance: Optional[Dict] = None,
        ps_scores: Optional[np.ndarray] = None,
        treatment: Optional[np.ndarray] = None,
        survival_data: Optional[Dict] = None
    ) -> "Agent6Workflow":
        """Set the analysis results for report generation."""
        self.study_title = study_title
        self.results = {
            "hazard_ratio": hazard_ratio,
            "target_n": target_n,
            "comparator_n": comparator_n,
            "balance": balance,
            "ps_scores": ps_scores,
            "treatment": treatment,
            "survival_data": survival_data
        }
        return self
    
    def generate_plots(self, output_dir: Optional[str] = None) -> Dict[str, str]:
        """Generate all visualization plots."""
        from src.vendors.reporting_handoff.reporting.plots import (
            ForestPlot,
            KMCurvePlot,
            LovePlot,
            PSDistPlot,
        )
        
        output_path = Path(output_dir or self.config.output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        # Forest Plot
        if self.config.include_forest_plot and self.results.get("hazard_ratio"):
            hr = self.results["hazard_ratio"]
            forest = ForestPlot([{
                "study": self.study_title,
                "hr": hr.hr,
                "ci_lower": hr.ci_lower,
                "ci_upper": hr.ci_upper
            }])
            forest_path = str(output_path / "forest_plot.png")
            forest.save(forest_path)
            self.plot_paths["forest"] = forest_path
        
        # PS Distribution
        if self.config.include_ps_dist and self.results.get("ps_scores") is not None:
            ps = self.results["ps_scores"]
            treatment = self.results.get("treatment")
            if treatment is not None:
                ps_treated = ps[treatment == 1]
                ps_control = ps[treatment == 0]
                ps_plot = PSDistPlot(ps_treated, ps_control)
                ps_path = str(output_path / "ps_distribution.png")
                ps_plot.save(ps_path)
                self.plot_paths["ps_dist"] = ps_path
        
        # Love Plot - now uses before/after SMDs from Agent 5
        if self.config.include_love_plot and self.results.get("balance"):
            balance = self.results["balance"]
            # Convert balance dict to required format with before/after
            smd_data = {}
            for k, v in balance.items():
                if isinstance(v, dict):
                    smd_data[k] = {
                        "before": v.get("smd_before", v.get("smd", 0)),
                        "after": v.get("smd_after", v.get("smd", 0))
                    }
            if smd_data:
                love = LovePlot(smd_data)
                love_path = str(output_path / "love_plot.png")
                love.save(love_path)
                self.plot_paths["love"] = love_path
        
        # Kaplan-Meier Curve
        if self.config.include_km_plot and self.results.get("survival_data"):
            from lifelines import KaplanMeierFitter
            
            survival = self.results["survival_data"]
            km_plot = KMCurvePlot()
            
            # Fit and add treated curve
            kmf_treated = KaplanMeierFitter()
            kmf_treated.fit(survival["times_treated"], survival["events_treated"])
            km_plot.add_curve(
                times=kmf_treated.survival_function_.index.tolist(),
                survival=kmf_treated.survival_function_.values.flatten().tolist(),
                label="Target"
            )
            
            # Fit and add control curve
            kmf_control = KaplanMeierFitter()
            kmf_control.fit(survival["times_control"], survival["events_control"])
            km_plot.add_curve(
                times=kmf_control.survival_function_.index.tolist(),
                survival=kmf_control.survival_function_.values.flatten().tolist(),
                label="Comparator"
            )
            
            km_path = str(output_path / "km_curve.png")
            km_plot.save(km_path)
            self.plot_paths["km"] = km_path
        
        return self.plot_paths
    
    def generate_report(
        self, 
        output_path: str,
        generate_plots: bool = True
    ) -> str:
        """
        Generate the final PDF report.
        
        Args:
            output_path: Path for the output PDF
            generate_plots: Whether to generate plots first
            
        Returns:
            Path to the generated report
        """
        from src.vendors.reporting_handoff.reporting.pdf_generator import PDFGenerator
        from src.vendors.reporting_handoff.reporting.models import ReportData
        
        # Generate plots if requested
        if generate_plots:
            plot_dir = Path(output_path).parent / "plots"
            self.generate_plots(str(plot_dir))
        
        # Build report data
        hr = self.results.get("hazard_ratio")
        report_data = ReportData(
            study_title=self.study_title,
            target_cohort_size=self.results["target_n"],
            comparator_cohort_size=self.results["comparator_n"],
            hazard_ratio=hr,
            forest_plot_path=self.plot_paths.get("forest"),
            love_plot_path=self.plot_paths.get("love"),
            ps_dist_plot_path=self.plot_paths.get("ps_dist")
        )
        
        # Generate PDF
        generator = PDFGenerator()
        generator.generate(report_data, output_path)
        
        return output_path
    
    def generate_html_report(self, output_path: str) -> str:
        """Generate HTML report (no WeasyPrint dependency)."""
        from src.vendors.reporting_handoff.reporting.pdf_generator import PDFGenerator
        from src.vendors.reporting_handoff.reporting.models import ReportData

        hr = self.results.get("hazard_ratio")
        report_data = ReportData(
            study_title=self.study_title,
            target_cohort_size=self.results["target_n"],
            comparator_cohort_size=self.results["comparator_n"],
            hazard_ratio=hr
        )
        
        generator = PDFGenerator()
        generator.generate_html_only(report_data, output_path)
        
        return output_path
