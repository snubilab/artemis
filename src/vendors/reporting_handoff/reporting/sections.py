"""
Report section renderers.
Phase 4.2: Individual HTML sections for reports.
"""
from typing import Optional
from src.vendors.reporting_handoff.reporting.models import ReportData, HazardRatioSummary


class ExecutiveSummary:
    """Render executive summary section."""
    
    def __init__(self, report_data: ReportData):
        self.data = report_data
    
    def render(self) -> str:
        """Render HTML for executive summary."""
        hr_text = ""
        significance_text = ""
        
        if self.data.hazard_ratio:
            hr = self.data.hazard_ratio
            hr_text = f"<p>Hazard Ratio: <strong>{hr.format()}</strong></p>"
            
            if hr.is_significant():
                significance_text = f"<p>The result is <strong>statistically significant</strong> (p = {hr.p_value:.4f}).</p>"
            else:
                significance_text = f"<p>The result is <strong>not statistically significant</strong> (p = {hr.p_value:.4f}).</p>"
        
        return f"""
        <section class="executive-summary">
            <h2>Executive Summary</h2>
            <p>Study: <strong>{self.data.study_title}</strong></p>
            <p>Cohort sizes: {self.data.target_name} (n={self.data.target_cohort_size}), 
               {self.data.comparator_name} (n={self.data.comparator_cohort_size})</p>
            {hr_text}
            {significance_text}
        </section>
        """


class CohortCharacteristics:
    """Render cohort characteristics section."""
    
    def __init__(
        self,
        target_n: int,
        comparator_n: int,
        mean_age_target: Optional[float] = None,
        mean_age_comparator: Optional[float] = None,
        pct_female_target: Optional[float] = None,
        pct_female_comparator: Optional[float] = None
    ):
        self.target_n = target_n
        self.comparator_n = comparator_n
        self.mean_age_target = mean_age_target
        self.mean_age_comparator = mean_age_comparator
        self.pct_female_target = pct_female_target
        self.pct_female_comparator = pct_female_comparator
    
    def render(self) -> str:
        """Render HTML for cohort characteristics."""
        age_row = ""
        if self.mean_age_target and self.mean_age_comparator:
            age_row = f"<tr><td>Mean Age</td><td>{self.mean_age_target:.1f}</td><td>{self.mean_age_comparator:.1f}</td></tr>"
        
        return f"""
        <section class="cohort-characteristics">
            <h2>Cohort Characteristics</h2>
            <table>
                <thead>
                    <tr><th>Characteristic</th><th>Target</th><th>Comparator</th></tr>
                </thead>
                <tbody>
                    <tr><td>N</td><td>{self.target_n}</td><td>{self.comparator_n}</td></tr>
                    {age_row}
                </tbody>
            </table>
        </section>
        """
