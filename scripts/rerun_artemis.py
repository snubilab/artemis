#!/usr/bin/env python3
"""Cancel stuck ARTEMIS cohorts and re-generate sequentially."""
import json
import time
import urllib.request
import urllib.error

WEBAPI_URL = "http://127.0.0.1/WebAPI"
SOURCE_KEY = "SYNTHEA23M"

# ARTEMIS cohort IDs in order
ARTEMIS_IDS = [95, 96, 97, 98, 99]

def api_request(method, endpoint, data=None):
    url = f"{WEBAPI_URL}/{endpoint}"
    req = urllib.request.Request(url, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
        req.data = json.dumps(data).encode("utf-8")
    try:
        with urllib.request.urlopen(req) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code} on {method} {endpoint}")
        return None
    except Exception as e:
        print(f"  Error: {e}")
        return None


def get_status(cid):
    info_list = api_request("GET", f"cohortdefinition/{cid}/info")
    if isinstance(info_list, list):
        for i in info_list:
            gid = i.get("id", {})
            if isinstance(gid, dict) and gid.get("sourceId") == 3:
                return i.get("status", "?"), i.get("personCount"), i.get("failMessage")
    return "?", None, None


def cancel_cohort(cid):
    """Cancel a running cohort generation."""
    resp = api_request("DELETE", f"cohortdefinition/{cid}/cancel/{SOURCE_KEY}")
    return resp


def generate_and_wait(cid, timeout=600):
    """Generate one cohort and wait for completion."""
    time.sleep(3)
    resp = api_request("GET", f"cohortdefinition/{cid}/generate/{SOURCE_KEY}")
    if resp is None:
        return None, "TRIGGER_FAILED"
    
    start = time.time()
    while time.time() - start < timeout:
        time.sleep(10)
        status, count, fail = get_status(cid)
        elapsed = int(time.time() - start)
        print(f"    [{elapsed}s] {status} count={count}")
        
        if fail:
            return None, f"FAILED: {fail[:60]}"
        if status == "COMPLETE":
            return count or 0, "COMPLETE"
        if status == "FAILED":
            return None, f"FAILED: {fail or 'unknown'}"
    
    return None, "TIMEOUT"


def main():
    print("=" * 60)
    print("  Cancel stuck + Re-generate ARTEMIS cohorts")
    print("=" * 60)
    
    # Step 1: Cancel any running ARTEMIS
    print("\n1️⃣ Cancelling stuck generations...")
    for cid in ARTEMIS_IDS:
        status, count, fail = get_status(cid)
        print(f"  ID={cid}: {status} (count={count})")
        if status == "RUNNING":
            print(f"    Cancelling...")
            cancel_cohort(cid)
    
    # Wait for cancellations to take effect
    print("\n  Waiting 10s for cancellations...")
    time.sleep(10)
    
    # Step 2: Re-generate one by one
    print("\n2️⃣ Generating ARTEMIS cohorts one at a time...")
    results = {}
    
    for idx, cid in enumerate(ARTEMIS_IDS):
        # Get cohort name
        d = api_request("GET", f"cohortdefinition/{cid}")
        name = d.get("name", f"ID={cid}") if isinstance(d, dict) else f"ID={cid}"
        
        print(f"\n  [{idx+1}/{len(ARTEMIS_IDS)}] {name}")
        count, status = generate_and_wait(cid, timeout=600)
        print(f"  → {status}: {count}")
        results[name] = count
    
    # Print summary
    print(f"\n{'=' * 60}")
    print(f"  📊 ARTEMIS RESULTS")
    print(f"{'=' * 60}")
    for name, count in results.items():
        print(f"  {name}: {count}")
    
    print(f"\n✅ Done!")


if __name__ == "__main__":
    main()
