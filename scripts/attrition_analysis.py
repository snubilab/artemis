#!/usr/bin/env python3
"""
Attrition Analysis v4: Optimized ARTEMIS with pruned concept sets.

Key optimization: Only include concept sets that are actually referenced
by the selected inclusion rules + entry criteria. This reduces SQL
complexity dramatically (from 81 concept sets to ~5-20 per level).
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


def load_circe(path):
    with open(path) as f:
        data = json.load(f)
    if isinstance(data.get("expression"), str):
        return json.loads(data["expression"])
    if "PrimaryCriteria" in data:
        return data
    raise ValueError(f"Cannot parse: {path}")


def find_cs_ids(obj):
    """Recursively find all CodesetId references in an object."""
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
    """Build cohort with ONLY the concept sets needed by selected rules."""
    # Select rules
    all_rules = original["InclusionRules"]
    selected_rules = [copy.deepcopy(all_rules[i]) for i in rule_indices if i < len(all_rules)]

    # Determine entry CodesetId
    entry_csid = None
    entry_domain = None
    for crit in original["PrimaryCriteria"]["CriteriaList"]:
        for key in crit:
            entry_domain = key
            entry_csid = crit[key].get("CodesetId")
            break
        break

    # Find ALL referenced concept set IDs (entry + rules)
    needed_cs_ids = {entry_csid}
    for rule in selected_rules:
        needed_cs_ids |= find_cs_ids(rule)
    needed_cs_ids.discard(None)

    # Prune concept sets to only needed ones
    cs_map = {cs["id"]: cs for cs in original["ConceptSets"]}
    pruned_cs = [copy.deepcopy(cs_map[csid]) for csid in sorted(needed_cs_ids) if csid in cs_map]

    # Build simplified cohort
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

    name = f"[ATT4] {label_prefix}: {level_name}"
    return {
        "name": name,
        "description": f"Attrition v4: {label_prefix} {level_name} ({len(selected_rules)} rules, {len(pruned_cs)} CS)",
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
                        return None, f"FAILED"
                    if status == "COMPLETE":
                        return info.get("personCount", 0) or 0, "COMPLETE"
                    if status == "FAILED":
                        return None, "FAILED"
                    break
    return None, "TIMEOUT"


def main():
    print("=" * 70)
    print("  Attrition Analysis v4: Pruned Concept Sets")
    print("=" * 70)

    troy = load_circe(TROY_PATH)
    artemis = load_circe(ARTEMIS_PATH)

    # Build all cohort definitions
    specs = []
    troy_cumul = []
    for level_name, new_rules in TROY_GROUPS:
        troy_cumul = troy_cumul + new_rules
        p = build_cohort(troy, level_name, troy_cumul, "TROY")
        n_cs = len(p["expression"]["ConceptSets"])
        n_rules = len(p["expression"]["InclusionRules"])
        specs.append(("TROY", level_name, p))
        print(f"  TROY {level_name}: {n_rules} rules, {n_cs} CS")

    artemis_cumul = []
    for level_name, new_rules in ARTEMIS_GROUPS:
        artemis_cumul = artemis_cumul + new_rules
        p = build_cohort(artemis, level_name, artemis_cumul, "ARTEMIS")
        n_cs = len(p["expression"]["ConceptSets"])
        n_rules = len(p["expression"]["InclusionRules"])
        specs.append(("ARTEMIS", level_name, p))
        print(f"  ARTEMIS {level_name}: {n_rules} rules, {n_cs} CS")

    # Register
    print(f"\n📝 Registering {len(specs)} cohorts...")
    registered = []
    for prefix, level, payload in specs:
        cid = register_cohort(payload)
        if cid:
            registered.append((prefix, level, cid))
            print(f"  {payload['name']}: ID={cid}")

    # Generate SEQUENTIALLY
    results = {}
    total = len(registered)
    print(f"\n🔄 Generating {total} cohorts sequentially...\n")

    for idx, (prefix, level, cid) in enumerate(registered, 1):
        label = f"[ATT4] {prefix}: {level}"
        print(f"  [{idx}/{total}] {label}...", end=" ", flush=True)
        count, status = generate_and_wait(cid)
        print(f"{status} → {count}")
        results[label] = {"count": count if count is not None else "?", "status": status}

    # Attrition table
    print(f"\n{'=' * 70}")
    print(f"  📊 ATTRITION TABLE")
    print(f"{'=' * 70}")

    levels = ["L0_Entry", "L1_Age", "L2_HbA1c", "L3_CVRisk", "L4_Exclusions"]
    print(f"\n{'Level':<18} {'TROY':>8} {'Drop':>12} {'ARTEMIS':>8} {'Drop':>12} {'Δ':>6}")
    print("-" * 68)

    prev_t, prev_e = None, None
    for level in levels:
        tc = results.get(f"[ATT4] TROY: {level}", {}).get("count", "?")
        ec = results.get(f"[ATT4] ARTEMIS: {level}", {}).get("count", "?")

        td, ed = "", ""
        if prev_t is not None and isinstance(tc, int):
            d = tc - prev_t
            pct = (d / prev_t * 100) if prev_t > 0 else 0
            td = f"{d:+d} ({pct:+.0f}%)"
        if prev_e is not None and isinstance(ec, int):
            d = ec - prev_e
            pct = (d / prev_e * 100) if prev_e > 0 else 0
            ed = f"{d:+d} ({pct:+.0f}%)"

        diff = f"{ec - tc:+d}" if isinstance(tc, int) and isinstance(ec, int) else ""
        print(f"{level:<18} {str(tc):>8} {td:>12} {str(ec):>8} {ed:>12} {diff:>6}")

        prev_t = tc if isinstance(tc, int) else prev_t
        prev_e = ec if isinstance(ec, int) else prev_e

    print(f"\n✅ Done!")


if __name__ == "__main__":
    main()
