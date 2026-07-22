"""
PDF Report Generator.
Phase 4.2.3: WeasyPrint-based PDF generation.
"""
from pathlib import Path
from typing import Optional
from jinja2 import Template
from src.reporting.models import ReportData


# Default HTML template
DEFAULT_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{{ data.study_title }} - TTE Report</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: 'Helvetica Neue', Arial, sans-serif;
            margin: 0; padding: 40px 48px;
            line-height: 1.65; color: #2c3e50;
            background: #fff;
        }
        h1 { font-size: 28px; color: #1a3a5c; border-bottom: 3px solid #2980b9; padding-bottom: 12px; margin-bottom: 8px; }
        h2 { font-size: 20px; color: #2c3e50; margin: 32px 0 12px; padding-bottom: 6px; border-bottom: 1px solid #d5dfe8; }
        h3 { font-size: 16px; color: #34495e; margin: 20px 0 8px; }
        p { margin: 6px 0; font-size: 14px; }
        .meta { color: #7f8c8d; font-size: 13px; margin-bottom: 24px; }
        .summary-box {
            background: linear-gradient(135deg, #f0f6fc 0%, #e8f0f8 100%);
            border: 1px solid #bcd4e6; border-radius: 10px;
            padding: 24px 28px; margin: 20px 0;
        }
        .summary-grid { display: flex; gap: 20px; flex-wrap: wrap; margin-top: 12px; }
        .summary-card {
            flex: 1; min-width: 140px;
            background: #fff; border-radius: 8px;
            padding: 16px; text-align: center;
            border: 1px solid #d5dfe8;
        }
        .summary-card .label { font-size: 12px; color: #7f8c8d; text-transform: uppercase; letter-spacing: 0.5px; }
        .summary-card .value { font-size: 24px; font-weight: 700; color: #1a3a5c; margin: 4px 0; }
        .summary-card .sub { font-size: 12px; color: #95a5a6; }
        .significant { color: #27ae60; font-weight: 600; }
        .not-significant { color: #e74c3c; font-weight: 600; }
        table { border-collapse: collapse; width: 100%; margin: 16px 0; font-size: 13px; }
        th { background: #2980b9; color: #fff; padding: 10px 14px; text-align: left; font-weight: 600; }
        td { padding: 8px 14px; border-bottom: 1px solid #e8eef3; }
        tr:nth-child(even) td { background: #f8fafc; }
        .plot-section { margin: 24px 0; }
        .plot-container {
            text-align: center; margin: 16px 0;
            border: 1px solid #e0e8f0; border-radius: 8px;
            padding: 16px; background: #fafcfe;
        }
        .plot-container img { max-width: 100%; height: auto; border-radius: 4px; }
        .plot-container h3 { margin-bottom: 8px; }
        .badge-good { display: inline-block; padding: 2px 8px; border-radius: 4px; background: #d4edda; color: #155724; font-size: 12px; }
        .badge-fair { display: inline-block; padding: 2px 8px; border-radius: 4px; background: #fff3cd; color: #856404; font-size: 12px; }
        .badge-poor { display: inline-block; padding: 2px 8px; border-radius: 4px; background: #f8d7da; color: #721c24; font-size: 12px; }
        footer {
            margin-top: 48px; padding-top: 16px;
            border-top: 2px solid #d5dfe8;
            font-size: 12px; color: #95a5a6;
            display: flex; justify-content: space-between;
        }
        @media print {
            body { padding: 20px; }
            .plot-container { break-inside: avoid; }
            h2 { break-after: avoid; }
        }
    </style>
</head>
<body>
    <h1>{{ data.study_title }}</h1>
    <p class="meta">Generated: {{ data.generated_at.strftime('%Y-%m-%d %H:%M UTC') }} &middot; Analysis Method: {{ data.analysis_method }}</p>

    <div class="summary-box">
        <h2 style="margin-top:0; border:none;">Executive Summary</h2>
        <div class="summary-grid">
            <div class="summary-card">
                <div class="label">Target Cohort</div>
                <div class="value">{{ "{:,}".format(data.target_cohort_size) }}</div>
                <div class="sub">{{ data.target_name }}</div>
            </div>
            <div class="summary-card">
                <div class="label">Comparator Cohort</div>
                <div class="value">{{ "{:,}".format(data.comparator_cohort_size) }}</div>
                <div class="sub">{{ data.comparator_name }}</div>
            </div>
            {% if data.hazard_ratio %}
            <div class="summary-card">
                <div class="label">Hazard Ratio</div>
                <div class="value">{{ "%.2f"|format(data.hazard_ratio.hr) }}</div>
                <div class="sub">95% CI: {{ "%.2f"|format(data.hazard_ratio.ci_lower) }}&ndash;{{ "%.2f"|format(data.hazard_ratio.ci_upper) }}</div>
            </div>
            <div class="summary-card">
                <div class="label">p-value</div>
                <div class="value {% if data.hazard_ratio.p_value < 0.05 %}significant{% else %}not-significant{% endif %}">
                    {{ "%.4f"|format(data.hazard_ratio.p_value) }}
                </div>
                <div class="sub">{% if data.hazard_ratio.p_value < 0.05 %}Statistically Significant{% else %}Not Significant{% endif %}</div>
            </div>
            {% endif %}
        </div>
    </div>

    <h2>Study Design</h2>
    <table>
        <tr><th>Parameter</th><th>Value</th></tr>
        <tr><td>Analysis Method</td><td>{{ data.analysis_method }}</td></tr>
        <tr><td>Primary Outcome</td><td>{{ data.outcome_name }}</td></tr>
        {% if data.median_followup_days %}<tr><td>Median Follow-up</td><td>{{ "%.0f"|format(data.median_followup_days) }} days</td></tr>{% endif %}
        {% if data.rct_study_name %}<tr><td>RCT Reference</td><td>{{ data.rct_study_name }}</td></tr>{% endif %}
    </table>

    {% if data.balance_summary %}
    <h2>Covariate Balance</h2>
    <table>
        <tr><th>Covariate</th><th>SMD Before</th><th>SMD After</th><th>Status</th></tr>
        {% for item in data.balance_summary %}
        <tr>
            <td>{{ item.name }}</td>
            <td>{{ "%.3f"|format(item.smd_before) }}</td>
            <td>{{ "%.3f"|format(item.smd_after) }}</td>
            <td>{% if item.smd_after|abs < 0.1 %}<span class="badge-good">Balanced</span>{% elif item.smd_after|abs < 0.2 %}<span class="badge-fair">Fair</span>{% else %}<span class="badge-poor">Imbalanced</span>{% endif %}</td>
        </tr>
        {% endfor %}
    </table>
    {% endif %}

    <h2>Visualizations</h2>
    <div class="plot-section">
        {% if data.km_plot_base64 %}
        <div class="plot-container">
            <h3>Kaplan-Meier Survival Curves</h3>
            <img src="data:image/png;base64,{{ data.km_plot_base64 }}" alt="Kaplan-Meier Curves">
        </div>
        {% elif data.km_plot_path %}
        <div class="plot-container">
            <h3>Kaplan-Meier Survival Curves</h3>
            <img src="{{ data.km_plot_path }}" alt="Kaplan-Meier Curves">
        </div>
        {% endif %}

        {% if data.forest_plot_base64 %}
        <div class="plot-container">
            <h3>Forest Plot</h3>
            <img src="data:image/png;base64,{{ data.forest_plot_base64 }}" alt="Forest Plot">
        </div>
        {% elif data.forest_plot_path %}
        <div class="plot-container">
            <h3>Forest Plot</h3>
            <img src="{{ data.forest_plot_path }}" alt="Forest Plot">
        </div>
        {% endif %}

        {% if data.love_plot_base64 %}
        <div class="plot-container">
            <h3>Covariate Balance (Love Plot)</h3>
            <img src="data:image/png;base64,{{ data.love_plot_base64 }}" alt="Love Plot">
        </div>
        {% elif data.love_plot_path %}
        <div class="plot-container">
            <h3>Covariate Balance (Love Plot)</h3>
            <img src="{{ data.love_plot_path }}" alt="Love Plot">
        </div>
        {% endif %}

        {% if data.ps_dist_plot_base64 %}
        <div class="plot-container">
            <h3>Propensity Score Distribution</h3>
            <img src="data:image/png;base64,{{ data.ps_dist_plot_base64 }}" alt="PS Distribution">
        </div>
        {% elif data.ps_dist_plot_path %}
        <div class="plot-container">
            <h3>Propensity Score Distribution</h3>
            <img src="{{ data.ps_dist_plot_path }}" alt="PS Distribution">
        </div>
        {% endif %}
    </div>

    <footer>
        <span>ARTEMIS 3.1 &mdash; Target Trial Emulation System</span>
        <span>{{ data.generated_at.strftime('%Y-%m-%d %H:%M') }}</span>
    </footer>
</body>
</html>'''


class PDFGenerator:
    """Generate PDF reports from ReportData."""
    
    def __init__(self, template_path: Optional[str] = None):
        """
        Args:
            template_path: Path to custom HTML template. Uses default if None.
        """
        if template_path and Path(template_path).exists():
            with open(template_path) as f:
                self.template = Template(f.read())
        else:
            self.template = Template(DEFAULT_TEMPLATE)
    
    def render_html(self, report_data: ReportData) -> str:
        """Render HTML from report data."""
        return self.template.render(data=report_data)
    
    def generate(self, report_data: ReportData, output_path: str):
        """
        Generate PDF from report data.
        
        Args:
            report_data: ReportData instance
            output_path: Path to save PDF
        """
        from weasyprint import HTML
        
        html_content = self.render_html(report_data)
        HTML(string=html_content).write_pdf(output_path)
    
    def generate_html_only(self, report_data: ReportData, output_path: str):
        """Save as HTML instead of PDF (for debugging)."""
        html_content = self.render_html(report_data)
        with open(output_path, 'w') as f:
            f.write(html_content)
