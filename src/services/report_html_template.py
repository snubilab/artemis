"""HTML report template for TTE analysis reports.

The single public constant ``REPORT_HTML_TEMPLATE`` is rendered with safe
string replacement (NOT ``.format()``).  Placeholders use ``{key}`` syntax
and the caller performs:

    html = REPORT_HTML_TEMPLATE
    for key, value in context.items():
        html = html.replace("{" + key + "}", value)
    html = html.replace("{{", "{").replace("}}", "}")

All CSS literal braces are therefore escaped as ``{{`` / ``}}`` so that
the double-brace replacement step restores them correctly.

Context keys
------------
  title            -- Study/report title (h1)
  generated_at     -- ISO timestamp string
  source_key       -- Data source label (e.g. SYNTHEA_CDM_BENCHMARK)
  analysis_method  -- Method badge text (e.g. IPTW-Cox)
  nct_id_row_html  -- Pre-rendered NCT-ID span, or empty string
  brief_title_html -- Pre-rendered brief-title paragraph, or empty string
  llm_report_html  -- LLM-generated 8-section report content (h2/h3/p/ul/table)
  plot_images_html -- Pre-rendered base64 <img> blocks for appendix figures
"""

REPORT_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{title}</title>
  <style>
    /* ------------------------------------------------------------------ */
    /* Reset / base                                                          */
    /* ------------------------------------------------------------------ */
    *, *::before, *::after {{
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }}

    body {{
      font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
      font-size: 14px;
      line-height: 1.7;
      color: #1a1a2e;
      background: #ffffff;
    }}

    /* ------------------------------------------------------------------ */
    /* Layout                                                                */
    /* ------------------------------------------------------------------ */
    .page {{
      max-width: 900px;
      margin: 0 auto;
      padding: 36px 28px 64px;
    }}

    /* ------------------------------------------------------------------ */
    /* Typography — global                                                   */
    /* ------------------------------------------------------------------ */
    h1 {{
      font-size: 22px;
      font-weight: 700;
      color: #0d1b4b;
      margin-bottom: 4px;
      line-height: 1.3;
    }}

    p {{
      margin-bottom: 10px;
      color: #2d3748;
    }}

    strong {{
      color: #0d1b4b;
    }}

    em {{
      font-style: italic;
      color: #4a5568;
    }}

    /* ------------------------------------------------------------------ */
    /* Header block                                                          */
    /* ------------------------------------------------------------------ */
    .report-header {{
      padding-bottom: 18px;
      border-bottom: 3px solid #3b5bdb;
      margin-bottom: 4px;
    }}

    .report-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 16px;
      margin-top: 12px;
      font-size: 13px;
      color: #4a5568;
    }}

    .report-meta span {{
      display: flex;
      align-items: center;
      gap: 4px;
    }}

    .badge {{
      display: inline-block;
      padding: 2px 9px;
      border-radius: 3px;
      font-size: 12px;
      font-weight: 600;
      background: #ebf0ff;
      color: #3b5bdb;
      border: 1px solid #c5d0f5;
    }}

    /* ------------------------------------------------------------------ */
    /* LLM report wrapper                                                    */
    /* ------------------------------------------------------------------ */
    .llm-report {{
      margin-top: 8px;
    }}

    /* Section headings inside the LLM report */
    .llm-report h2 {{
      font-size: 17px;
      font-weight: 700;
      color: #0d1b4b;
      padding-bottom: 8px;
      border-bottom: 2px solid #d0d8f0;
      margin-top: 40px;
      margin-bottom: 16px;
    }}

    .llm-report h3 {{
      font-size: 14px;
      font-weight: 600;
      color: #2c3e80;
      margin-top: 18px;
      margin-bottom: 8px;
    }}

    .llm-report p {{
      margin-bottom: 10px;
      color: #2d3748;
      font-size: 14px;
    }}

    /* Lists inside the LLM report */
    .llm-report ul,
    .llm-report ol {{
      margin: 8px 0 14px 0;
      padding-left: 0;
      list-style: none;
    }}

    .llm-report ul li,
    .llm-report ol li {{
      padding: 6px 0 6px 22px;
      position: relative;
      font-size: 13px;
      border-bottom: 1px solid #edf0f7;
      color: #2d3748;
    }}

    .llm-report ul li::before {{
      content: "\\2022";
      position: absolute;
      left: 0;
      color: #3b5bdb;
      font-weight: 700;
    }}

    .llm-report ol {{
      counter-reset: llm-ol;
    }}

    .llm-report ol li {{
      counter-increment: llm-ol;
    }}

    .llm-report ol li::before {{
      content: counter(llm-ol) ".";
      position: absolute;
      left: 0;
      color: #3b5bdb;
      font-weight: 600;
      font-size: 13px;
    }}

    .llm-report strong {{
      color: #0d1b4b;
    }}

    .llm-report em {{
      font-style: italic;
      color: #4a5568;
    }}

    /* ------------------------------------------------------------------ */
    /* Tables inside the LLM report                                          */
    /* ------------------------------------------------------------------ */
    .llm-report table {{
      width: 100%;
      border-collapse: collapse;
      margin: 16px 0;
      font-size: 13px;
      overflow-x: auto;
      display: block;
    }}

    .llm-report thead tr {{
      background: #0d1b4b;
      color: #ffffff;
    }}

    .llm-report thead th {{
      padding: 9px 14px;
      text-align: left;
      font-weight: 600;
      white-space: nowrap;
    }}

    .llm-report tbody tr:nth-child(even) {{
      background: #f0f4ff;
    }}

    .llm-report tbody tr:hover {{
      background: #e4eaff;
    }}

    .llm-report tbody td {{
      padding: 7px 14px;
      border-bottom: 1px solid #e2e8f0;
      color: #2d3748;
      vertical-align: top;
    }}

    /* ------------------------------------------------------------------ */
    /* Callout / warning box                                                 */
    /* ------------------------------------------------------------------ */
    .llm-report .caution-box {{
      background: #fff3cd;
      border-left: 4px solid #ffc107;
      padding: 12px 16px;
      margin: 14px 0;
      border-radius: 4px;
      font-size: 13px;
      color: #5a4600;
    }}

    /* ------------------------------------------------------------------ */
    /* Interpretation level badge                                            */
    /* ------------------------------------------------------------------ */
    .llm-report .interpretation-badge {{
      display: inline-block;
      padding: 4px 12px;
      border-radius: 4px;
      font-weight: 600;
      font-size: 13px;
    }}

    .llm-report .interpretation-badge.feasibility {{
      background: #f8d7da;
      color: #721c24;
    }}

    .llm-report .interpretation-badge.exploratory {{
      background: #fff3cd;
      color: #856404;
    }}

    .llm-report .interpretation-badge.directional {{
      background: #d4edda;
      color: #155724;
    }}

    .llm-report .interpretation-badge.informative {{
      background: #cce5ff;
      color: #004085;
    }}

    /* ------------------------------------------------------------------ */
    /* Appendix figures                                                      */
    /* ------------------------------------------------------------------ */
    .appendix-heading {{
      font-size: 17px;
      font-weight: 700;
      color: #0d1b4b;
      padding-bottom: 8px;
      border-bottom: 2px solid #d0d8f0;
      margin-top: 52px;
      margin-bottom: 18px;
    }}

    .figures-container {{
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 24px;
      margin: 16px 0;
    }}

    .figure-block {{
      text-align: center;
    }}

    .figure-block img {{
      max-width: 100%;
      height: auto;
      border: 1px solid #d0d8f0;
      border-radius: 4px;
    }}

    .figure-block figcaption {{
      font-size: 12px;
      color: #718096;
      margin-top: 6px;
    }}

    /* ------------------------------------------------------------------ */
    /* Footer                                                                */
    /* ------------------------------------------------------------------ */
    .report-footer {{
      margin-top: 52px;
      padding-top: 16px;
      border-top: 1px solid #d0d8f0;
      font-size: 12px;
      color: #718096;
      text-align: center;
    }}

    /* ------------------------------------------------------------------ */
    /* Print overrides (WeasyPrint compatible)                               */
    /* ------------------------------------------------------------------ */
    @media print {{
      body {{
        font-size: 12px;
      }}

      .page {{
        padding: 0;
        max-width: 100%;
      }}

      .llm-report h2,
      .appendix-heading {{
        page-break-after: avoid;
      }}

      .llm-report table,
      .figure-block {{
        page-break-inside: avoid;
      }}

      .llm-report .caution-box {{
        page-break-inside: avoid;
      }}

      .figures-container {{
        grid-template-columns: 1fr;
      }}
    }}
  </style>
</head>
<body>
<div class="page">

  <!-- ================================================================== -->
  <!-- HEADER                                                               -->
  <!-- ================================================================== -->
  <header class="report-header">
    <h1>{title}</h1>
    <div class="report-meta">
      <span><strong>Generated:</strong>&nbsp;{generated_at}</span>
      {nct_id_row_html}
      <span><strong>Data source:</strong>&nbsp;{source_key}</span>
      <span><strong>Method:</strong>&nbsp;<span class="badge">{analysis_method}</span></span>
    </div>
    {brief_title_html}
  </header>

  <!-- ================================================================== -->
  <!-- LLM-GENERATED 8-SECTION REPORT                                      -->
  <!-- ================================================================== -->
  <div class="llm-report">
    {llm_report_html}
  </div>

  <!-- ================================================================== -->
  <!-- APPENDIX: FIGURES                                                    -->
  <!-- ================================================================== -->
  <h2 class="appendix-heading">Appendix: Figures</h2>
  <div class="figures-container">
    {plot_images_html}
  </div>

  <!-- ================================================================== -->
  <!-- FOOTER                                                               -->
  <!-- ================================================================== -->
  <footer class="report-footer">
    Generated by <strong>Artemis TTE Analysis Platform</strong> &mdash; {generated_at}
  </footer>

</div>
</body>
</html>
"""
