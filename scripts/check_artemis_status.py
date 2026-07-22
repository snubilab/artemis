#!/usr/bin/env python3
"""Check final status of all ATT3 ARTEMIS cohorts."""
import json
import urllib.request

WEBAPI_URL = "http://127.0.0.1/WebAPI"

def api_get(endpoint):
    url = f"{WEBAPI_URL}/{endpoint}"
    with urllib.request.urlopen(url) as resp:
        return json.loads(resp.read().decode())

# Get all ATT3 ARTEMIS cohorts
all_defs = api_get("cohortdefinition")
artemis_defs = [d for d in all_defs if d["name"].startswith("[ATT3] ARTEMIS")]

print(f"{'ID':>4} {'Name':<40} {'Status':<12} {'Count':>8} {'Duration':>8}")
print("-" * 80)

for d in sorted(artemis_defs, key=lambda x: x["name"]):
    cid = d["id"]
    info_list = api_get(f"cohortdefinition/{cid}/info")
    status, count, dur, fail = "?", "?", "?", ""
    if isinstance(info_list, list):
        for i in info_list:
            gid = i.get("id", {})
            if isinstance(gid, dict) and gid.get("sourceId") == 3:
                status = i.get("status", "?")
                count = i.get("personCount")
                dur = i.get("executionDuration")
                fail = (i.get("failMessage") or "")[:60]
                if count is None:
                    count = "null"
                if dur:
                    dur = f"{dur/1000:.0f}s"
                break
    print(f"{cid:>4} {d['name']:<40} {status:<12} {str(count):>8} {str(dur):>8}")
    if fail:
        print(f"     ⚠ {fail}")
