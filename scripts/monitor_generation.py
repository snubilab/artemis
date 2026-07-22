#!/usr/bin/env python3
"""Poll cohort generation status every 30s until both complete."""
import subprocess, json, time, sys

def psql(sql):
    r = subprocess.run(
        ["docker", "exec", "broadsea-atlasdb", "psql", "-U", "postgres", "-d", "ohdsi", "-t", "-A", "-c", sql],
        capture_output=True, text=True
    )
    return r.stdout.strip()

def webapi_info(cid):
    import urllib.request
    try:
        r = urllib.request.urlopen(f"http://127.0.0.1/WebAPI/cohortdefinition/{cid}/info", timeout=10)
        return json.loads(r.read())
    except Exception as e:
        print(f"  ⚠ webapi_info fallback cid={cid} error_type={type(e).__name__} error={e}")
        return []

def active_queries():
    return psql("""
        SELECT pid || '|' || (now() - query_start)::text || '|' || LEFT(query, 60)
        FROM pg_stat_activity
        WHERE state = 'active' AND query NOT LIKE '%pg_stat%'
        ORDER BY query_start;
    """)

def main():
    print("🔄 Monitoring cohort generation (Ctrl+C to stop)")
    print("=" * 70)
    
    for i in range(60):  # max 30 min
        # Active PG queries
        aq = active_queries()
        queries = [l for l in aq.split("\n") if l.strip()] if aq else []
        
        # WebAPI info
        done_count = 0
        for cid, name in [(5, "TROY"), (7, "ARTEMIS")]:
            info = webapi_info(cid)
            for g in info:
                gid = g.get("id", {})
                if isinstance(gid, dict) and gid.get("sourceId") == 3:
                    s = g["status"]
                    c = g.get("personCount", "?")
                    d = g.get("executionDuration", "?")
                    f = (g.get("failMessage") or "")[:40]
                    tag = "✅" if s == "COMPLETE" else ("❌" if s == "FAILED" else "🔄")
                    print(f"  {tag} {name}: {s} count={c} dur={d}ms {f}")
                    if s in ("COMPLETE", "FAILED"):
                        done_count += 1
        
        # Active PG queries
        if queries:
            for q in queries:
                parts = q.split("|", 2)
                if len(parts) == 3:
                    print(f"  📊 PG PID={parts[0]} dur={parts[1]} q={parts[2]}")
        else:
            print("  📊 No active SQL queries")
        
        print(f"  ⏱  {time.strftime('%H:%M:%S')}")
        print("-" * 70)
        sys.stdout.flush()
        
        if done_count >= 2:
            print("\n✅ Both cohorts done!")
            # Final counts from DB
            cohort_count = psql("SELECT COUNT(*) FROM synthea100k_results.cohort;")
            cache_count = psql("SELECT COUNT(*) FROM synthea100k_results.cohort_cache;")
            print(f"  cohort rows: {cohort_count}")
            print(f"  cohort_cache rows: {cache_count}")
            return
        
        time.sleep(30)
    
    print("⚠ Timeout after 30 min")

if __name__ == "__main__":
    main()
