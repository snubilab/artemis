#!/usr/bin/env python3
"""Diagnose synthea100k schema issues by comparing with synthea_cdm."""
import subprocess
import sys

CONTAINER = "broadsea-atlasdb"

def psql(sql: str) -> str:
    r = subprocess.run(
        ["docker", "exec", CONTAINER, "psql", "-U", "postgres", "-d", "ohdsi", "-t", "-A", "-c", sql],
        capture_output=True, text=True
    )
    return r.stdout.strip()

def main():
    print("=" * 60)
    print("  Diagnosing synthea100k Schema Issues")
    print("=" * 60)

    # 1. Check WebAPI error logs
    print("\n📋 Step 1: WebAPI Error Logs (last 30 lines with ERROR)")
    r = subprocess.run(
        ["docker", "logs", "ohdsi-webapi", "--tail", "200"],
        capture_output=True, text=True
    )
    errors = [l for l in r.stderr.split("\n") if "ERROR" in l or "BadSql" in l or "does not exist" in l]
    for e in errors[-10:]:
        print(f"  {e[:150]}")

    # 2. Compare tables between synthea_cdm and synthea100k
    print("\n📋 Step 2: Tables in synthea_cdm but NOT in synthea100k")
    missing_tables = psql("""
        SELECT t1.tablename FROM pg_tables t1 
        WHERE t1.schemaname = 'synthea_cdm' 
        AND NOT EXISTS (
            SELECT 1 FROM pg_tables t2 
            WHERE t2.schemaname = 'synthea100k' AND t2.tablename = t1.tablename
        )
        AND t1.tablename NOT IN ('all_visits', 'assign_all_visit_ids', 'final_visit_ids')
        ORDER BY t1.tablename;
    """)
    if missing_tables:
        for t in missing_tables.split("\n"):
            print(f"  ❌ Missing: {t}")
    else:
        print("  ✅ All CDM tables present")

    # 3. Compare columns for each existing table
    print("\n📋 Step 3: Column mismatches")
    common_tables = psql("""
        SELECT t1.tablename FROM pg_tables t1 
        WHERE t1.schemaname = 'synthea100k' 
        AND t1.tablename IN (SELECT tablename FROM pg_tables WHERE schemaname = 'synthea_cdm')
        ORDER BY t1.tablename;
    """)
    if common_tables:
        for table in common_tables.split("\n"):
            if not table.strip():
                continue
            # Columns in synthea_cdm but not in synthea100k
            diff = psql(f"""
                SELECT c1.column_name FROM information_schema.columns c1
                WHERE c1.table_schema = 'synthea_cdm' AND c1.table_name = '{table}'
                AND NOT EXISTS (
                    SELECT 1 FROM information_schema.columns c2
                    WHERE c2.table_schema = 'synthea100k' AND c2.table_name = '{table}'
                    AND c2.column_name = c1.column_name
                )
            """)
            if diff:
                print(f"  ❌ {table}: missing cols = {diff}")

    # 4. Check views
    print("\n📋 Step 4: Vocabulary views")
    for vt in ["concept", "concept_ancestor", "concept_relationship", "vocabulary",
                "domain", "concept_class", "relationship", "drug_strength"]:
        exists = psql(f"""
            SELECT COUNT(*) FROM pg_views
            WHERE schemaname = 'synthea100k' AND viewname = '{vt}';
        """)
        status = "✅" if exists == "1" else "❌"
        print(f"  {status} {vt}")

    # 5. CDM tables that WebAPI SQL typically references
    print("\n📋 Step 5: Critical CDM tables check")
    critical = [
        "person", "observation_period", "visit_occurrence", "condition_occurrence",
        "drug_exposure", "measurement", "observation", "procedure_occurrence",
        "condition_era", "drug_era", "death", "device_exposure", "specimen",
        "note", "payer_plan_period", "cost", "location", "care_site", "provider"
    ]
    for t in critical:
        count = psql(f"""
            SELECT COUNT(*) FROM pg_tables
            WHERE schemaname = 'synthea100k' AND tablename = '{t}';
        """)
        if count == "0":
            # Check in synthea_cdm
            in_cdm = psql(f"""
                SELECT COUNT(*) FROM pg_tables
                WHERE schemaname = 'synthea_cdm' AND tablename = '{t}';
            """)
            if in_cdm == "1":
                print(f"  ❌ Missing: {t} (exists in synthea_cdm)")
            else:
                print(f"  ⚠  Missing: {t} (not in synthea_cdm either)")
        else:
            print(f"  ✅ {t}")

    print("\n" + "=" * 60)

if __name__ == "__main__":
    main()
