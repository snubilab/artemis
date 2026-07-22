#!/usr/bin/env python3
"""Quick check: get all ATT cohort statuses and retry failed ones."""
import json
import time
import urllib.request
import urllib.error

WEBAPI_URL = "http://127.0.0.1/WebAPI"
SOURCE_KEY = "SYNTHEA23M"

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
        return {"error": e.code}
    except Exception as e:
        return {"error": str(e)}


def main():
    # Get all cohort definitions
    all_defs = api_request("GET", "cohortdefinition")
    att_defs = [d for d in all_defs if d["name"].startswith("[ATT]")]
    
    print(f"Found {len(att_defs)} ATT cohorts\n")
    print(f"{'ID':>4} {'Name':<45} {'Status':<12} {'Count':>8}")
    print("-" * 75)
    
    failed_ids = []
    for d in sorted(att_defs, key=lambda x: x["name"]):
        cid = d["id"]
        info = api_request("GET", f"cohortdefinition/{cid}/info")
        
        status = "?"
        count = "?"
        if isinstance(info, list):
            for i in info:
                gid = i.get("id", {})
                if isinstance(gid, dict) and gid.get("sourceId") == 3:
                    status = i.get("status", "?")
                    count = i.get("personCount", "null")
                    if i.get("failMessage"):
                        status = "FAILED"
                    break
        
        print(f"{cid:>4} {d['name']:<45} {status:<12} {str(count):>8}")
        
        if status == "FAILED" or (status == "COMPLETE" and count is None):
            failed_ids.append(cid)
    
    # Re-trigger failed
    if failed_ids:
        print(f"\n🔄 Re-triggering {len(failed_ids)} failed cohorts: {failed_ids}")
        for cid in failed_ids:
            print(f"  Triggering ID={cid}...")
            api_request("GET", f"cohortdefinition/{cid}/generate/{SOURCE_KEY}")
        
        # Poll
        print("\n⏳ Polling...")
        start = time.time()
        while time.time() - start < 600:
            all_done = True
            for cid in failed_ids:
                info = api_request("GET", f"cohortdefinition/{cid}/info")
                if isinstance(info, list):
                    for i in info:
                        gid = i.get("id", {})
                        if isinstance(gid, dict) and gid.get("sourceId") == 3:
                            s = i.get("status", "?")
                            c = i.get("personCount", "?")
                            print(f"  [{int(time.time()-start)}s] ID={cid}: {s} ({c})")
                            if s not in ("COMPLETE", "FAILED"):
                                all_done = False
                            break
            if all_done:
                print("✅ All retries complete!")
                break
            time.sleep(10)
    else:
        print("\n✅ No failed cohorts!")


if __name__ == "__main__":
    main()
