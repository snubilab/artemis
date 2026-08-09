#!/usr/bin/env python3
"""
Simplified TROY vs ARTEMIS Comparison.

Strips down both TROY and ARTEMIS to their core criteria (entry + T2DM),
generates cohorts on SYNTHEA23M (SOURCE_KEY), and compares patient counts.

This reveals whether the CONCEPT MAPPING differences between expert (TROY)
and auto-generated (ARTEMIS) affect patient capture, independent of
the complex inclusion rules.

NOT A QUALITY MEASURE (note added 2026-08-09). What this IS for: asking whether a
mapping difference is materially visible in patient capture at all, on SYNTHEA23M --
an independent CDM (SOURCE_KEY below), NOT one of the synthea_cdm_{aristotle,leader,plato,benchmark}
sets that are generated from data/gold/ and therefore cannot referee mapping quality.
What its output is NOT evidence of: which mapping is better. A TROY-vs-ARTEMIS count
table reads like a verdict; it is a sensitivity probe. Equal counts mean the difference
did not move this CDM, not that the mappings agree.

Measure of record for mapping quality: per-eligibility-criterion 1:1 concept-set overlap
against data/gold/, macro-averaged -- scripts/conceptset_overlap_eval.py --mode closure
(see AGENTS.md EVALUATION).
"""
import json
import time
import urllib.request
import urllib.error
import sys
import copy

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


def find_concept_set_by_keywords(concept_sets, keywords):
    """Find a concept set whose name contains any of the keywords (case-insensitive).
    Keywords are checked in order, so put more specific keywords first.
    """
    # First pass: try exact match with each keyword in order
    for kw in keywords:
        for cs in concept_sets:
            name = cs["name"].lower()
            if kw.lower() in name:
                return cs
    return None


def build_simplified(label, original, entry_keywords, inclusion_keywords_list=None):
    """
    Build a simplified cohort from the original Circe JSON.
    
    - Keeps only the entry event concept set
    - Optionally adds inclusion rules for specified concept sets
    - Preserves ORIGINAL concept IDs (no remapping)
    """
    concept_sets = original["ConceptSets"]
    
    # Find entry concept set
    entry_cs = find_concept_set_by_keywords(concept_sets, entry_keywords)
    if not entry_cs:
        print(f"  ⚠ Cannot find entry CS for {label} with keywords {entry_keywords}")
        print(f"  Available CS: {[cs['name'] for cs in concept_sets]}")
        return None
    
    print(f"  Entry CS: [{entry_cs['id']}] {entry_cs['name']}")
    print(f"    Concepts: {[i['concept']['CONCEPT_ID'] for i in entry_cs['expression']['items']]}")
    
    # Determine entry domain from original PrimaryCriteria
    # Circe supports: DrugExposure, DrugEra, ConditionOccurrence, ConditionEra,
    # ProcedureOccurrence, Observation, Measurement, DeviceExposure, etc.
    entry_domain = None
    original_entry_csid = None
    for crit in original["PrimaryCriteria"]["CriteriaList"]:
        # Dynamically detect the domain key (first key in the crit dict)
        for key in crit:
            entry_domain = key
            original_entry_csid = crit[key].get("CodesetId")
            break
        break
    
    if not entry_domain:
        print(f"  ⚠ Cannot determine entry domain for {label}")
        return None
    
    print(f"  Entry Domain: {entry_domain}, Original CodesetId: {original_entry_csid}")

    # Build simplified cohort
    used_cs = [copy.deepcopy(entry_cs)]
    
    # Primary Criteria uses the entry concept set
    primary_criteria = {
        "CriteriaList": [{entry_domain: {"CodesetId": entry_cs["id"]}}],
        "ObservationWindow": {"PriorDays": 0, "PostDays": 0},
        "PrimaryCriteriaLimit": {"Type": "All"}
    }
    
    # Inclusion Rules
    inclusion_rules = []
    if inclusion_keywords_list:
        for inc_keywords in inclusion_keywords_list:
            inc_cs = find_concept_set_by_keywords(concept_sets, inc_keywords)
            if inc_cs:
                print(f"  Inclusion CS: [{inc_cs['id']}] {inc_cs['name']}")
                print(f"    Concepts: {[i['concept']['CONCEPT_ID'] for i in inc_cs['expression']['items']]}")
                
                if inc_cs["id"] != entry_cs["id"]:
                    used_cs.append(copy.deepcopy(inc_cs))
                
                # Determine domain for inclusion
                inc_domain = "ConditionOccurrence"  # default for conditions
                inc_items = inc_cs["expression"]["items"]
                if inc_items:
                    domain = inc_items[0]["concept"].get("DOMAIN_ID", "")
                    if domain == "Drug":
                        inc_domain = "DrugExposure"
                
                inclusion_rules.append({
                    "name": f"Has {inc_cs['name']}",
                    "expression": {
                        "Type": "ALL",
                        "CriteriaList": [{
                            "Criteria": {inc_domain: {"CodesetId": inc_cs["id"]}},
                            "StartWindow": {
                                "Start": {"Coeff": -1},
                                "End": {"Coeff": 1},
                                "UseIndexEnd": False,
                                "UseEventEnd": False
                            },
                            "Occurrence": {"Type": 2, "Count": 1}
                        }],
                        "DemographicCriteriaList": [],
                        "Groups": []
                    }
                })
    
    circe = {
        "ConceptSets": used_cs,
        "PrimaryCriteria": primary_criteria,
        "QualifiedLimit": {"Type": "First"},
        "ExpressionLimit": {"Type": "All"},
        "InclusionRules": inclusion_rules,
        "CensoringCriteria": [],
        "CollapseSettings": {"CollapseType": "ERA", "EraPad": 0},
        "CensorWindow": {}
    }
    
    return {
        "name": label,
        "description": f"Simplified {label}",
        "expressionType": "SIMPLE_EXPRESSION",
        "expression": circe
    }


def register_and_generate(payload):
    """Register cohort and trigger generation."""
    name = payload["name"]
    
    # Check existing
    all_defs = api_request("GET", "cohortdefinition")
    cid = None
    if isinstance(all_defs, list):
        for d in all_defs:
            if d["name"] == name:
                cid = d["id"]
                break
    
    if cid:
        print(f"  Updating existing ID={cid}")
        api_request("PUT", f"cohortdefinition/{cid}", payload)
    else:
        print(f"  Creating new...")
        resp = api_request("POST", "cohortdefinition", payload)
        if isinstance(resp, dict) and "id" in resp:
            cid = resp["id"]
            print(f"  Created ID={cid}")
        else:
            print(f"  ❌ Failed to create")
            return None
    
    # Generate
    print(f"  Generating on {SOURCE_KEY}...")
    api_request("GET", f"cohortdefinition/{cid}/generate/{SOURCE_KEY}")
    return cid


def poll_all(cohort_ids, timeout=600):
    """Poll all cohorts until complete."""
    print(f"\n⏳ Polling {len(cohort_ids)} cohorts...")
    start = time.time()
    
    while True:
        all_done = True
        lines = []
        
        for cid, name in cohort_ids.items():
            info_list = api_request("GET", f"cohortdefinition/{cid}/info")
            found = False
            if isinstance(info_list, list):
                for info in info_list:
                    gid = info.get("id", {})
                    if isinstance(gid, dict) and gid.get("sourceId") == 3:
                        found = True
                        status = info.get("status", "?")
                        count = info.get("personCount", "?")
                        lines.append(f"{name}: {status} ({count})")
                        if status not in ("COMPLETE", "FAILED"):
                            all_done = False
                        break
            if not found:
                lines.append(f"{name}: PENDING")
                all_done = False
        
        elapsed = int(time.time() - start)
        print(f"[{elapsed}s] " + " | ".join(lines))
        
        if all_done:
            break
        if elapsed > timeout:
            print("⚠ Timeout!")
            break
        time.sleep(10)
    
    # Final results
    results = {}
    for cid, name in cohort_ids.items():
        info_list = api_request("GET", f"cohortdefinition/{cid}/info")
        if isinstance(info_list, list):
            for info in info_list:
                gid = info.get("id", {})
                if isinstance(gid, dict) and gid.get("sourceId") == 3:
                    results[name] = {
                        "count": info.get("personCount", 0),
                        "status": info.get("status", "?"),
                        "duration": info.get("executionDuration", "?")
                    }
    return results


def main():
    print("=" * 70)
    print("  Simplified TROY vs ARTEMIS Comparison")
    print("=" * 70)
    
    # Load original definitions
    print("\n📂 Loading original definitions...")
    troy = load_circe(TROY_PATH)
    artemis = load_circe(ARTEMIS_PATH)
    
    print(f"  TROY: {len(troy['ConceptSets'])} ConceptSets, {len(troy['InclusionRules'])} Rules")
    print(f"  ARTEMIS: {len(artemis['ConceptSets'])} ConceptSets, {len(artemis['InclusionRules'])} Rules")
    
    # Build 4 simplified cohorts
    cohort_payloads = []
    
    # --- Level 1: Entry Only (Liraglutide) ---
    print("\n🔹 Building: TROY Simplified (Liraglutide Only)")
    troy_entry = build_simplified(
        "[SIMPLE] TROY: Liraglutide Only",
        troy,
        entry_keywords=["liraglutide"]
    )
    if troy_entry:
        cohort_payloads.append(troy_entry)
    
    print("\n🔹 Building: ARTEMIS Simplified (Liraglutide Only)")
    artemis_entry = build_simplified(
        "[SIMPLE] ARTEMIS: Liraglutide Only",
        artemis,
        entry_keywords=["liraglutide"]
    )
    if artemis_entry:
        cohort_payloads.append(artemis_entry)
    
    # --- Level 2: Entry + T2DM ---
    print("\n🔹 Building: TROY Simplified (Liraglutide + T2DM)")
    troy_t2dm = build_simplified(
        "[SIMPLE] TROY: Lira + T2DM",
        troy,
        entry_keywords=["liraglutide"],
        inclusion_keywords_list=[["type 2 diabetes", "t2dm"]]
    )
    if troy_t2dm:
        cohort_payloads.append(troy_t2dm)
    
    print("\n🔹 Building: ARTEMIS Simplified (Liraglutide + T2DM)")
    artemis_t2dm = build_simplified(
        "[SIMPLE] ARTEMIS: Lira + T2DM",
        artemis,
        entry_keywords=["liraglutide"],
        inclusion_keywords_list=[["type 2 diabetes", "t2dm"]]
    )
    if artemis_t2dm:
        cohort_payloads.append(artemis_t2dm)
    
    # Register and generate all
    print("\n" + "=" * 70)
    print("  Registering & Generating Cohorts")
    print("=" * 70)
    
    cohort_ids = {}
    for payload in cohort_payloads:
        print(f"\n📝 {payload['name']}")
        cid = register_and_generate(payload)
        if cid:
            cohort_ids[cid] = payload["name"]
    
    # Poll for results
    results = poll_all(cohort_ids)
    
    # Print comparison table
    print("\n" + "=" * 70)
    print("  📊 COMPARISON RESULTS")
    print("=" * 70)
    print(f"\n{'Cohort':<45} {'Count':>8} {'Status':>10}")
    print("-" * 65)
    for name, info in sorted(results.items()):
        count = info["count"] if info["count"] else 0
        print(f"{name:<45} {count:>8} {info['status']:>10}")
    
    # Compute overlap analysis
    troy_entry_count = results.get("[SIMPLE] TROY: Liraglutide Only", {}).get("count", 0) or 0
    artemis_entry_count = results.get("[SIMPLE] ARTEMIS: Liraglutide Only", {}).get("count", 0) or 0
    troy_t2dm_count = results.get("[SIMPLE] TROY: Lira + T2DM", {}).get("count", 0) or 0
    artemis_t2dm_count = results.get("[SIMPLE] ARTEMIS: Lira + T2DM", {}).get("count", 0) or 0
    
    print("\n📈 Analysis:")
    if troy_entry_count and artemis_entry_count:
        diff = artemis_entry_count - troy_entry_count
        pct = diff / troy_entry_count * 100 if troy_entry_count else 0
        print(f"  Entry (Liraglutide): TROY={troy_entry_count}, ARTEMIS={artemis_entry_count}, Diff={diff:+d} ({pct:+.1f}%)")
    
    if troy_t2dm_count and artemis_t2dm_count:
        diff = artemis_t2dm_count - troy_t2dm_count
        pct = diff / troy_t2dm_count * 100 if troy_t2dm_count else 0
        print(f"  Entry + T2DM:        TROY={troy_t2dm_count}, ARTEMIS={artemis_t2dm_count}, Diff={diff:+d} ({pct:+.1f}%)")
    
    print("\n✅ Done!")


if __name__ == "__main__":
    main()
