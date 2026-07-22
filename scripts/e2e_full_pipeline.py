#!/usr/bin/env python
"""
E2E Full Pipeline Script.
NL Query → Cohort Definition → Analysis → Report.

Usage:
    python scripts/e2e_full_pipeline.py --query "Compare drug A vs drug B for outcome X"
"""
import argparse
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def main():
    parser = argparse.ArgumentParser(description="ARTEMIS 3.1 Full Pipeline")
    parser.add_argument(
        "--query", 
        type=str,
        default="Compare patients on Metformin versus Sulfonylurea for cardiovascular events in Type 2 Diabetes",
        help="Natural language clinical question"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="./output/full_pipeline",
        help="Output directory for results"
    )
    parser.add_argument(
        "--db-connection",
        type=str,
        default="postgresql://postgres:mypass@localhost:5432/postgres",
        help="PostgreSQL connection string"
    )
    parser.add_argument(
        "--schema",
        type=str,
        default="demo_cdm",
        help="OMOP CDM schema name"
    )
    parser.add_argument(
        "--method",
        type=str,
        choices=["IPTW", "PSM"],
        default="IPTW",
        help="Analysis method"
    )
    parser.add_argument(
        "--followup",
        type=int,
        default=365,
        help="Follow-up period in days"
    )
    args = parser.parse_args()
    
    print("\n" + "=" * 70)
    print("ARTEMIS 3.1 - Full Pipeline Execution")
    print("=" * 70)
    print(f"Query: {args.query}")
    print(f"Output: {args.output_dir}")
    print(f"Method: {args.method}")
    print("=" * 70 + "\n")
    
    # Import here to avoid slow startup if just checking --help
    from src.pipeline.orchestrator import ArtemisPipeline
    
    # Initialize pipeline
    pipeline = ArtemisPipeline(
        db_connection=args.db_connection,
        schema=args.schema
    )
    
    # Run
    try:
        result = pipeline.run(
            query=args.query,
            output_dir=args.output_dir,
            analysis_method=args.method,
            followup_days=args.followup
        )
        
        print("\n" + "=" * 70)
        print("✅ Pipeline Complete!")
        print("=" * 70)
        print(f"\nReport: {result.report_path}")
        print(f"Plots: {list(result.plot_paths.keys())}")
        
        hr = result.hazard_ratio
        print(f"\nKey Finding:")
        print(f"  HR = {hr.get('hr', 0):.2f} (95% CI: {hr.get('ci_lower', 0):.2f}-{hr.get('ci_upper', 0):.2f})")
        print(f"  p-value = {hr.get('p_value', 1):.4f}")
        
        return 0
        
    except Exception as e:
        print(f"\n❌ Pipeline failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
