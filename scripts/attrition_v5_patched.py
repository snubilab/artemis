#!/usr/bin/env python3
"""
Attrition Analysis v5: Re-run with PATCHED ARTEMIS definition.

Applies the P0/P1 fixes (from lab meeting 2026-02-17) directly to the
existing ARTEMIS JSON before running the attrition analysis:

1. Fix time window sign: Days:-365,Coeff:-1 → Days:365,Coeff:-1
2. Validate all windows for inversion (Start > End)

This script patches the JSON in-memory and re-runs L0~L4 comparison.
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

TROY_GROUPS = [
    ("L0_Entry",       []),
    ("L1_Age",         [0]),
    ("L2_HbA1c",       [1]),
    ("L3_CVRisk",      [2]),
    ("L4_Exclusions",  [3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17]),
]

ARTEMIS_GROUPS = [
    ("L0_Entry",       []),
    ("L1_Age",         [0]),
    ("L2_HbA1c",       [3]),
    ("L3_CVRisk",      [1, 2, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]),
    ("L4_Exclusions",  [16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31]),
]


# ─── P0 Fix: Patch all time windows in ARTEMIS JSON ───────────────────

def normalize_window_element(elem):
    """Fix Days/Coeff so Days >= 0. 
    If Days < 0, flip sign and invert Coeff."""
    if "Days" in elem and elem["Days"] < 0:
        elem["Days"] = abs(elem["Days"])
        elem["Coeff"] = -elem.get("Coeff", 1)  # flip direction
    return elem


def validate_window(window):
    """Ensure Start <= End temporally. Swap if inverted."""
    start_eff = window["Start"]["Days"] * window["Start"]["Coeff"]
    end_eff = window["End"]["Days"] * window["End"]["Coeff"]
    if start_eff > end_eff:
        window["Start"], window["End"] = window["End"], window["Start"]
    return window


def patch_windows_recursive(obj, stats):
    """Recursively find and fix all StartWindow/EndWindow in the JSON."""
    if isinstance(obj, dict):
        for key in ("StartWindow", "EndWindow"):
            if key in obj and isinstance(obj[key], dict):
                w = obj[key]
                if "Start" in w:
                    normalize_window_element(w["Start"])
                if "End" in w:
                    normalize_window_element(w["End"])
                validate_window(w)
                stats["patched"] += 1
        for v in obj.values():
            patch_windows_recursive(v, stats)
    elif isinstance(obj, list):
        for item in obj:
            patch_windows_recursive(item, stats)


def patch_artemis(artemis):
    """Apply P0 fix: normalize all time windows in ARTEMIS definition."""
    stats = {"patched": 0}
    patch_windows_recursive(artemis, stats)
    print(f"  🔧 Patched {stats['patched']} time windows in ARTEMIS definition")
    return artemis


# ─── Reused from attrition_analysis.py v4 ────────────────────────────

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


def build_cohort(original, level_name, rule_indices, label_prefix):
    all_rules = original["InclusionRules"]
    selected_rules = [copy.deepcopy(all_rules[i]) for i in rule_indices if i < len(all_rules)]

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

    name = f"[ATT5] {label_prefix}: {level_name}"
    return {
        "name": name,
        "description": f"Attrition v5 patched: {label_prefix} {level_name} ({len(selected_rules)} rules, {len(pruned_cs)} CS)",
        "expressionType": "SIMPLE_EXPRESSION",
        "expression": cohort
    }


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
                    status = info.get("status", "?")
                    if info.get("failMessage"):
                        return None, "FAILED"
                    if status == "COMPLETE":
                        return info.get("personCount", 0) or 0, "COMPLETE"
                    if status == "FAILED":
                        return None, "FAILED"
                    break
    return None, "TIMEOUT"


# ─── Main ────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("  Attrition Analysis v5: PATCHED ARTEMIS (P0 time window fix)")
    print("=" * 70)

    troy = load_circe(TROY_PATH)
    artemis_raw = load_circe(ARTEMIS_PATH)

    # Apply P0 patch to ARTEMIS
    artemis = patch_artemis(artemis_raw)

    # Quick diagnostic: show ARTEMIS HbA1c rule (index 3) after patch
    if len(artemis["InclusionRules"]) > 3:
        hba1c = artemis["InclusionRules"][3]
        print(f"\n  📋 ARTEMIS HbA1c rule (index 3) after patch:")
        expr = hba1c.get("expression", {})
        for crit in expr.get("CriteriaList", []):
            sw = crit.get("StartWindow", {})
            occ = crit.get("Occurrence", {})
            print(f"     StartWindow: {json.dumps(sw)}")
            print(f"     Occurrence:  {json.dumps(occ)}")

    # Build cohort definitions  
    specs = []
    # Only rebuild ARTEMIS (TROY was fine in v4)
    # But include TROY L2 for direct comparison
    print("\n📦 Building cohort definitions...")

    # TROY L2 only (for comparison)
    troy_l2_rules = [0, 1]  # Age + HbA1c
    p = build_cohort(troy, "L2_HbA1c", troy_l2_rules, "TROY")
    specs.append(("TROY", "L2_HbA1c", p))
    print(f"  TROY L2_HbA1c: {len(p['expression']['InclusionRules'])} rules, {len(p['expression']['ConceptSets'])} CS")

    # ARTEMIS L0~L4 (full attrition with patched windows)
    artemis_cumul = []
    for level_name, new_rules in ARTEMIS_GROUPS:
        artemis_cumul = artemis_cumul + new_rules
        p = build_cohort(artemis, level_name, artemis_cumul, "ARTEMIS_P")
        specs.append(("ARTEMIS_P", level_name, p))
        n_cs = len(p["expression"]["ConceptSets"])
        n_rules = len(p["expression"]["InclusionRules"])
        print(f"  ARTEMIS_P {level_name}: {n_rules} rules, {n_cs} CS")

    # Register & Generate
    print(f"\n📝 Registering {len(specs)} cohorts...")
    registered = []
    for prefix, level, payload in specs:
        cid = register_cohort(payload)
        if cid:
            registered.append((prefix, level, cid))
            print(f"  {payload['name']}: ID={cid}")

    print(f"\n🔄 Generating {len(registered)} cohorts sequentially...\n")
    results = {}
    for idx, (prefix, level, cid) in enumerate(registered, 1):
        label = f"[ATT5] {prefix}: {level}"
        print(f"  [{idx}/{len(registered)}] {label}...", end=" ", flush=True)
        count, status = generate_and_wait(cid)
        print(f"{status} → {count}")
        results[label] = {"count": count if count is not None else "?", "status": status}

    # Results
    print(f"\n{'=' * 70}")
    print(f"  📊 PATCHED ARTEMIS ATTRITION TABLE (v5)")
    print(f"{'=' * 70}")

    levels = ["L0_Entry", "L1_Age", "L2_HbA1c", "L3_CVRisk", "L4_Exclusions"]
    
    # Show TROY L2 reference
    troy_l2 = results.get("[ATT5] TROY: L2_HbA1c", {}).get("count", "?")
    print(f"\n  TROY L2 Reference: {troy_l2}")
    
    # ARTEMIS_P attrition
    print(f"\n{'Level':<18} {'ARTEMIS_P':>8} {'Drop':>12}")
    print("-" * 42)

    prev_e = None
    for level in levels:
        ec = results.get(f"[ATT5] ARTEMIS_P: {level}", {}).get("count", "?")
        ed = ""
        if prev_e is not None and isinstance(ec, int):
            d = ec - prev_e
            pct = (d / prev_e * 100) if prev_e > 0 else 0
            ed = f"{d:+d} ({pct:+.0f}%)"
        print(f"{level:<18} {str(ec):>8} {ed:>12}")
        prev_e = ec if isinstance(ec, int) else prev_e

    # Key comparison  
    artemis_l2 = results.get("[ATT5] ARTEMIS_P: L2_HbA1c", {}).get("count", "?")
    print(f"\n{'=' * 70}")
    print(f"  🔑 KEY COMPARISON: TROY L2={troy_l2} vs ARTEMIS_P L2={artemis_l2}")
    if isinstance(troy_l2, int) and isinstance(artemis_l2, int):
        delta = artemis_l2 - troy_l2
        print(f"     Δ = {delta:+d} ({'MATCH!' if delta == 0 else 'still divergent'})")
    print(f"{'=' * 70}")
    print(f"\n✅ Done!")


if __name__ == "__main__":
    main()
