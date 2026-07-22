#!/usr/bin/env python3
"""
ARTEMIS E2E Pipeline — Synthea 23M (2.7M patients)
Query: Simvastatin vs Clopidogrel in Coronary Arteriosclerosis patients
Uses drugs that actually EXIST in Synthea data.
"""
import os
import sys

os.environ["CDM_SCHEMA"] = "synthea23m"
os.environ["ARTEMIS_FALLBACK_MODE"] = "never"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.pipeline.orchestrator import ArtemisPipeline

QUERY = """
Compare cardiovascular outcomes between patients treated with 
Simvastatin versus Clopidogrel in adults with coronary arteriosclerosis.

Primary endpoint: Acute bronchitis or Anemia (as proxy adverse events).
Follow-up period: 365 days.
"""

if __name__ == "__main__":
    print("=" * 70)
    print("  ARTEMIS E2E — Synthea 23M (Real Data)")
    print("  Simvastatin vs Clopidogrel / Coronary Arteriosclerosis")
    print("  Schema: synthea23m | Fallback: NEVER")
    print("=" * 70)
    
    pipeline = ArtemisPipeline(
        db_connection="postgresql://postgres:mypass@localhost:5432/ohdsi",
        schema="synthea23m",
    )
    
    result = pipeline.run(
        query=QUERY,
        output_dir="./output/e2e_synthea23m_v3",
        analysis_method="IPTW",
        followup_days=365,
    )
    
    print("\n" + "=" * 70)
    print("  E2E RESULT SUMMARY")
    print("=" * 70)
    print(f"  Valid cohort: {result.is_valid}")
    print(f"  Hazard ratio: {result.hazard_ratio}")
    print(f"  Report: {result.report_path}")
    print(f"  Plots: {list(result.plot_paths.keys())}")
    print("=" * 70)
