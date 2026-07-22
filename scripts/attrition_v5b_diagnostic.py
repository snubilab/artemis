#!/usr/bin/env python3
"""
Attrition v5b: Full ARTEMIS L2 patch (all 3 bugs).

Patches the ARTEMIS JSON in-memory to fix:
  Bug 1: Time windows — normalize Days < 0 to Days=abs, Coeff=-1 (NOT flip)
  Bug 2: No window inversion (simply set correct Days/Coeff per Circe convention)
  
This is a DIAGNOSTIC run: only L2_HbA1c comparison.
We run 3 variants to isolate each bug's impact:
  A) Window-only fix (correct -365→0 window)
  B) Window + remove Occurrence filter (Type:2→Type:2 is fine if we have no value filter)
  C) Window + match TROY's exact rule structure (clone TROY L2 rule onto ARTEMIS concept set)
"""
import json
import time
import copy
import urllib.request
import urllib.error

WEBAPI_URL = "http://127.0.0.1/WebAPI"
SOURCE_KEY = "SYNTHEA23M"

TROY_PATH = "artemis/data/sample/LEADER/[TROY] Liraglutide (LEADER) v3.4.json"
ARTEMIS_PATH = "artemis/data/sample/LEADER/ARTEMIS_LEADER_design_paper_e2e.json"


def load_circe(path):
    with open(path) as f:
        data = json.load(f)
    if isinstance(data.get("expression"), str):
        return json.loads(data["expression"])
    if "PrimaryCriteria" in data:
        return data
    raise ValueError(f"Cannot parse: {path}")


def find_cs_ids(obj):
    ids = set()
    if isinstance(obj, dict):
        if "CodesetId" in obj:
            ids.add(obj["CodesetId"])
        for v in obj.values():
            ids |= find_cs_ids(v)
    elif isinstance(obj, list):
        for item in obj:
            ids |= find_cs_ids(item)
    return ids


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
        print(f"    HTTP {e.code} on {method} {endpoint}")
        return None
    except Exception as e:
        print(f"    Error: {e}")
        return None


def register_cohort(payload):
    name = payload["name"]
    all_defs = api_request("GET", "cohortdefinition")
    cid = None
    if isinstance(all_defs, list):
        for d in all_defs:
            if d["name"] == name:
                cid = d["id"]
                break
    if cid:
        api_request("PUT", f"cohortdefinition/{cid}", payload)
        return cid
    else:
        resp = api_request("POST", "cohortdefinition", payload)
        if isinstance(resp, dict) and "id" in resp:
            return resp["id"]
    return None


def generate_and_wait(cid, timeout=600):
    time.sleep(3)
    resp = api_request("GET", f"cohortdefinition/{cid}/generate/{SOURCE_KEY}")
    if resp is None:
        return None, "TRIGGER_FAILED"
    start = time.time()
    while time.time() - start < timeout:
        time.sleep(5)
        info_list = api_request("GET", f"cohortdefinition/{cid}/info")
        if isinstance(info_list, list):
            for info in info_list:
                gid = info.get("id", {})
                if isinstance(gid, dict) and gid.get("sourceId") == 3:
                    if info.get("failMessage"):
                        return None, "FAILED"
                    if info.get("status") == "COMPLETE":
                        return info.get("personCount", 0) or 0, "COMPLETE"
                    if info.get("status") == "FAILED":
                        return None, "FAILED"
                    break
    return None, "TIMEOUT"


def build_l2_cohort(original, label, hba1c_rule_override=None, rule_indices=None):
    """Build L2 cohort (Age + HbA1c) with optional rule override."""
    all_rules = original["InclusionRules"]
    
    if rule_indices is None:
        rule_indices = []
    
    selected_rules = []
    for i in rule_indices:
        if i < len(all_rules):
            if hba1c_rule_override and i == rule_indices[-1]:
                # Override the HbA1c rule (last one)
                selected_rules.append(copy.deepcopy(hba1c_rule_override))
            else:
                selected_rules.append(copy.deepcopy(all_rules[i]))

    # Entry criteria
    entry_csid = None
    entry_domain = None
    for crit in original["PrimaryCriteria"]["CriteriaList"]:
        for key in crit:
            entry_domain = key
            entry_csid = crit[key].get("CodesetId")
            break
        break

    needed_cs_ids = {entry_csid}
    for rule in selected_rules:
        needed_cs_ids |= find_cs_ids(rule)
    needed_cs_ids.discard(None)

    cs_map = {cs["id"]: cs for cs in original["ConceptSets"]}
    pruned_cs = [copy.deepcopy(cs_map[csid]) for csid in sorted(needed_cs_ids) if csid in cs_map]

    cohort = {
        "ConceptSets": pruned_cs,
        "PrimaryCriteria": {
            "CriteriaList": [{entry_domain: {"CodesetId": entry_csid}}],
            "ObservationWindow": {"PriorDays": 0, "PostDays": 0},
            "PrimaryCriteriaLimit": {"Type": "All"}
        },
        "QualifiedLimit": {"Type": "First"},
        "ExpressionLimit": {"Type": "All"},
        "InclusionRules": selected_rules,
        "CensoringCriteria": [],
        "CollapseSettings": {"CollapseType": "ERA", "EraPad": 0},
        "CensorWindow": {}
    }

    return {
        "name": label,
        "description": f"L2 diagnostic: {label}",
        "expressionType": "SIMPLE_EXPRESSION",
        "expression": cohort
    }


def main():
    print("=" * 70)
    print("  Attrition v5b: L2 HbA1c Diagnostic (isolate each bug)")
    print("=" * 70)

    troy = load_circe(TROY_PATH)
    artemis = load_circe(ARTEMIS_PATH)

    # Show original ARTEMIS HbA1c rule
    artemis_hba1c = copy.deepcopy(artemis["InclusionRules"][3])  # index 3
    print(f"\n📋 Original ARTEMIS HbA1c rule:")
    for crit in artemis_hba1c.get("expression", {}).get("CriteriaList", []):
        print(f"  StartWindow: {json.dumps(crit.get('StartWindow'))}")
        print(f"  Occurrence:  {json.dumps(crit.get('Occurrence'))}")
        print(f"  Criteria:    {json.dumps({k:v for k,v in crit.get('Criteria',{}).items()})}")

    # Show TROY HbA1c rule for reference
    troy_hba1c = troy["InclusionRules"][1]  # index 1
    print(f"\n📋 TROY HbA1c rule (reference):")
    for crit in troy_hba1c.get("expression", {}).get("CriteriaList", []):
        print(f"  StartWindow: {json.dumps(crit.get('StartWindow'))}")
        print(f"  Occurrence:  {json.dumps(crit.get('Occurrence'))}")
        print(f"  Criteria:    {json.dumps({k:v for k,v in crit.get('Criteria',{}).items()})}")

    # ── Variant A: Fix window only ──
    # Set correct window: -365d to 0d (past to index)
    fix_a = copy.deepcopy(artemis_hba1c)
    for crit in fix_a.get("expression", {}).get("CriteriaList", []):
        crit["StartWindow"] = {
            "Start": {"Days": 365, "Coeff": -1},   # 365 days before
            "End": {"Days": 0, "Coeff": 1},          # up to index
            "UseEventEnd": False
        }
    print(f"\n  Variant A: Window-only fix (365d prior → 0d)")

    # ── Variant B: Fix window + match TROY semantics ──
    # TROY checks "absence of HbA1c >= 10%" (upper bound safety check)
    # Use same window, same occurrence type
    fix_b = copy.deepcopy(artemis_hba1c)
    for crit in fix_b.get("expression", {}).get("CriteriaList", []):
        crit["StartWindow"] = {
            "Start": {"Days": 365, "Coeff": -1},
            "End": {"Days": 0, "Coeff": 1},
            "UseEventEnd": False
        }
        # Keep PRESENCE (Type:2, Count:1) — check if HbA1c measurement exists
        # This is actually different from TROY (ABSENCE of >=10%)
        # but let's see if just having a valid window finds patients

    # ── Variant C: Use TROY's exact HbA1c rule but with ARTEMIS concept set ID ──
    # Get ARTEMIS's HbA1c concept set ID
    artemis_hba1c_csid = None
    for crit in artemis_hba1c.get("expression", {}).get("CriteriaList", []):
        for k, v in crit.get("Criteria", {}).items():
            artemis_hba1c_csid = v.get("CodesetId")
            break
    
    fix_c = copy.deepcopy(troy_hba1c)
    fix_c["name"] = "HbA1c (TROY-style on ARTEMIS CS)"
    # Replace TROY's concept set ID with ARTEMIS's
    for crit in fix_c.get("expression", {}).get("CriteriaList", []):
        for k, v in crit.get("Criteria", {}).items():
            v["CodesetId"] = artemis_hba1c_csid

    # Build cohorts
    specs = []
    
    # Reference: TROY L2 (Age + HbA1c)
    specs.append(("TROY_ref", build_l2_cohort(troy, "[v5b] TROY L2 ref", rule_indices=[0, 1])))
    
    # Original ARTEMIS (unpatched, should be 0)
    specs.append(("ARTEMIS_orig", build_l2_cohort(artemis, "[v5b] ARTEMIS L2 orig", rule_indices=[0, 3])))
    
    # Variant A: Window-only fix
    specs.append(("fix_A", build_l2_cohort(artemis, "[v5b] Fix A: window", 
                                           hba1c_rule_override=fix_a, rule_indices=[0, 3])))
    
    # Variant B: Window fix (same as A for now since we keep PRESENCE)
    # Skip B, same as A since we keep PRESENCE
    
    # Variant C: TROY-style rule on ARTEMIS concept set
    specs.append(("fix_C", build_l2_cohort(artemis, "[v5b] Fix C: TROY-style",
                                           hba1c_rule_override=fix_c, rule_indices=[0, 3])))

    print(f"\n📝 Registering {len(specs)} cohorts...")
    registered = []
    for key, payload in specs:
        cid = register_cohort(payload)
        if cid:
            registered.append((key, cid))
            print(f"  {payload['name']}: ID={cid}")

    print(f"\n🔄 Generating {len(registered)} cohorts sequentially...\n")
    results = {}
    for idx, (key, cid) in enumerate(registered, 1):
        print(f"  [{idx}/{len(registered)}] {key}...", end=" ", flush=True)
        count, status = generate_and_wait(cid)
        print(f"{status} → {count}")
        results[key] = count

    # Results summary
    print(f"\n{'=' * 70}")
    print(f"  📊 L2 HbA1c BUG ISOLATION RESULTS")
    print(f"{'=' * 70}")
    print(f"  TROY L2 (reference):       {results.get('TROY_ref', '?')}")
    print(f"  ARTEMIS L2 (original/buggy): {results.get('ARTEMIS_orig', '?')}")
    print(f"  Fix A (window only):       {results.get('fix_A', '?')}")
    print(f"  Fix C (TROY-style rule):   {results.get('fix_C', '?')}")
    print(f"{'=' * 70}")
    print(f"\n✅ Done!")


if __name__ == "__main__":
    main()
