#!/usr/bin/env python3
"""
Trigger and poll cohort generation on SYNTHEA100K.
Usage: python3 scripts/trigger_cohort_generation.py
"""
import json
import time
import sys
import urllib.request

WEBAPI = "http://127.0.0.1/WebAPI"
SOURCE_KEY = "SYNTHEA23M"
COHORTS = {5: "TROY LEADER", 7: "ARTEMIS LEADER"}
POLL_INTERVAL = 30
MAX_WAIT = 900  # 15 min


def api_get(path: str):
    r = urllib.request.urlopen(f"{WEBAPI}/{path}", timeout=30)
    return json.loads(r.read())


def main():
    # Health check
    try:
        info = api_get("info")
        print(f"✅ WebAPI {info['version']} online")
    except Exception as e:
        print(f"❌ WebAPI not ready: {e}")
        sys.exit(1)

    # Trigger generation for each cohort
    for cid, name in COHORTS.items():
        print(f"\n🚀 Triggering {name} (id={cid}) on {SOURCE_KEY}...")
        try:
            result = api_get(f"cohortdefinition/{cid}/generate/{SOURCE_KEY}")
            print(f"  status={result.get('status')}, execId={result.get('executionId')}")
        except Exception as e:
            print(f"  ❌ Failed: {e}")

    # Poll for completion
    print(f"\n⏳ Polling every {POLL_INTERVAL}s (max {MAX_WAIT}s)...")
    start = time.time()

    while time.time() - start < MAX_WAIT:
        time.sleep(POLL_INTERVAL)
        elapsed = int(time.time() - start)
        all_done = True

        statuses = {}
        for cid, name in COHORTS.items():
            try:
                info_list = api_get(f"cohortdefinition/{cid}/info")
                for g in info_list:
                    gid = g.get("id", {})
                    if isinstance(gid, dict) and gid.get("sourceId") == 3:
                        s = g["status"]
                        c = g.get("personCount", "?")
                        d = g.get("executionDuration", "?")
                        f = (g.get("failMessage") or "")[:60]
                        statuses[name] = f"{s} count={c} dur={d}ms"
                        if f:
                            statuses[name] += f" ERR={f}"
                        if s not in ("COMPLETE", "FAILED"):
                            all_done = False
                        break
                else:
                    statuses[name] = "PENDING"
                    all_done = False
            except Exception as e:
                statuses[name] = f"ERROR: {e}"
                all_done = False

        line = f"[{elapsed:>4}s] " + " | ".join(f"{n}: {s}" for n, s in statuses.items())
        print(line, flush=True)

        if all_done:
            print("\n✅ All cohort generations complete!")
            # Final summary
            for cid, name in COHORTS.items():
                info_list = api_get(f"cohortdefinition/{cid}/info")
                for g in info_list:
                    gid = g.get("id", {})
                    if isinstance(gid, dict) and gid.get("sourceId") == 3:
                        print(f"  {name}: count={g.get('personCount')}, "
                              f"dur={g.get('executionDuration')}ms, "
                              f"status={g['status']}")
                        if g.get("failMessage"):
                            print(f"    FAIL: {g['failMessage'][:200]}")
            return

    print(f"\n⚠ Timeout after {MAX_WAIT}s — generation still running")


if __name__ == "__main__":
    main()
