#!/usr/bin/env python3
"""
Create and run 3 simplified cohorts to debug attrition.
1. [DEBUG] Liraglutide (Entry Only)
2. [DEBUG] T2DM (Entry Only)
3. [DEBUG] Liraglutide + T2DM (Entry + 1 Rule)
"""
import json
import time
import urllib.request
import urllib.error
import urllib.parse
import sys

WEBAPI_URL = "http://127.0.0.1/WebAPI"
SOURCE_KEY = "SYNTHEA23M"
RESULTS_SCHEMA = "synthea23m_results"

# Concept Set Definitions (Simplified)
# Liraglutide (Ingredient)
CS_LIRAGLUTIDE = {
    "id": 1,
    "name": "Liraglutide (Ingredient)",
    "expression": {
        "items": [
            {
                "concept": {
                    "CONCEPT_ID": 40170911,
                    "CONCEPT_NAME": "Liraglutide",
                    "STANDARD_CONCEPT": "S",
                    "STANDARD_CONCEPT_CAPTION": "Standard",
                    "INVALID_REASON": "V",
                    "INVALID_REASON_CAPTION": "Valid",
                    "CONCEPT_CODE": "475968",
                    "DOMAIN_ID": "Drug",
                    "VOCABULARY_ID": "RxNorm",
                    "CONCEPT_CLASS_ID": "Ingredient"
                },
                "includeDescendants": True
            }
        ]
    }
}

# T2DM (Condition) - Using SNOMED 201820
CS_T2DM = {
    "id": 2,
    "name": "Type 2 Diabetes Mellitus",
    "expression": {
        "items": [
            {
                "concept": {
                    "CONCEPT_ID": 201820,
                    "CONCEPT_NAME": "Type 2 diabetes mellitus",
                    "STANDARD_CONCEPT": "S",
                    "STANDARD_CONCEPT_CAPTION": "Standard",
                    "INVALID_REASON": "V",
                    "INVALID_REASON_CAPTION": "Valid",
                    "CONCEPT_CODE": "44054006",
                    "DOMAIN_ID": "Condition",
                    "VOCABULARY_ID": "SNOMED",
                    "CONCEPT_CLASS_ID": "Clinical Finding"
                },
                "includeDescendants": True
            }
        ]
    }
}

def create_cohort_payload(name, entry_cs, entry_domain, inclusion_cs=None):
    # (Same logic as before, but wrapped)
    pc_list = []
    if entry_domain == 'Drug':
        pc_list.append({"DrugExposure": {"CodesetId": entry_cs['id']}})
    elif entry_domain == 'Condition':
        pc_list.append({"ConditionOccurrence": {"CodesetId": entry_cs['id']}})

    concept_sets = [entry_cs]
    if inclusion_cs and inclusion_cs['id'] != entry_cs['id']:
        concept_sets.append(inclusion_cs)

    inclusion_rules = []
    if inclusion_cs:
        crit = {}
        if inclusion_cs == CS_T2DM:
             crit = {"ConditionOccurrence": {"CodesetId": inclusion_cs['id']}}
        elif inclusion_cs == CS_LIRAGLUTIDE:
             crit = {"DrugExposure": {"CodesetId": inclusion_cs['id']}}
        
        inclusion_rules.append({
            "name": f"Has {inclusion_cs['name']}",
            "expression": {
                "Type": "ALL",
                "CriteriaList": [
                    {
                        "Criteria": crit,
                        "StartWindow": {
                            "Start": {"Coeff": -1},
                            "End": {"Coeff": 1},
                            "UseIndexEnd": False,
                            "UseEventEnd": False
                        },
                        "Occurrence": {"Type": 2, "Count": 1}
                    }
                ],
                "DemographicCriteriaList": [],
                "Groups": []
            }
        })

    circe_json = {
        "ConceptSets": concept_sets,
        "PrimaryCriteria": {
            "CriteriaList": pc_list,
            "ObservationWindow": {"PriorDays": 0, "PostDays": 0},
            "PrimaryCriteriaLimit": {"Type": "All"}
        },
        "QualifiedLimit": {"Type": "First"},
        "ExpressionLimit": {"Type": "All"},
        "InclusionRules": inclusion_rules,
        "CensoringCriteria": [],
        "CollapseSettings": {"CollapseType": "ERA", "EraPad": 0},
        "CensorWindow": {}
    }
    
    return {
        "name": name,
        "description": "Auto-generated debug cohort",
        "expressionType": "SIMPLE_EXPRESSION",
        "expression": circe_json
    }

def api_request(method, endpoint, data=None):
    url = f"{WEBAPI_URL}/{endpoint}"
    req = urllib.request.Request(url, method=method)
    if data:
        json_data = json.dumps(data).encode('utf-8')
        req.add_header('Content-Type', 'application/json')
        req.data = json_data
    
    try:
        with urllib.request.urlopen(req) as response:
            if response.status >= 200 and response.status < 300:
                resp_data = response.read().decode('utf-8')
                return json.loads(resp_data) if resp_data else {}
            else:
                return None
    except urllib.error.HTTPError as e:
        print(f"  HTTP Error {method} {endpoint}: {e.code} {e.reason}")
        if e.code == 409:
            return "409"
        return None
    except Exception as e:
        print(f"  Error {method} {endpoint}: {e}")
        return None

def main():
    print(f"🚀 Registering DEBUG cohorts on {WEBAPI_URL}...")

    # 1. Fetch all existing cohorts once
    print("  Fetching existing cohort list...")
    all_cohorts = api_request("GET", "cohortdefinition")
    existing_map = {item['name']: item['id'] for item in all_cohorts} if isinstance(all_cohorts, list) else {}
    print(f"  Found {len(existing_map)} existing cohorts.")

    cohorts = [
        {
            "name": "[DEBUG] Liraglutide Users (Entry Only)",
            "payload": create_cohort_payload("[DEBUG] Liraglutide Users (Entry Only)", CS_LIRAGLUTIDE, 'Drug')
        },
        {
            "name": "[DEBUG] T2DM Patients (Entry Only)",
            "payload": create_cohort_payload("[DEBUG] T2DM Patients (Entry Only)", CS_T2DM, 'Condition')
        },
        {
            "name": "[DEBUG] Liraglutide + T2DM (Intersection)",
            "payload": create_cohort_payload("[DEBUG] Liraglutide + T2DM (Intersection)", CS_LIRAGLUTIDE, 'Drug', inclusion_cs=CS_T2DM)
        }
    ]

    registered_ids = {}

    # 2. Register & Generate
    for c in cohorts:
        print(f"\n🔹 Processing: {c['name']}")
        
        cid = existing_map.get(c['name'])
        
        if cid:
            print(f"  Existing ID found: {cid}. Updating...")
            api_request("PUT", f"cohortdefinition/{cid}", c['payload'])
        else:
            print(f"  Creating new definition...")
            resp = api_request("POST", "cohortdefinition", c['payload'])
            if resp == "409":
                # Race condition or inconsistent state? try to fetch again
                print("  ⚠ 409 Conflict. Refetching list...")
                all_cohorts = api_request("GET", "cohortdefinition")
                existing_map = {item['name']: item['id'] for item in all_cohorts} if isinstance(all_cohorts, list) else {}
                cid = existing_map.get(c['name'])
                if cid:
                    print(f"  Found ID {cid} after refetch. Updating...")
                    api_request("PUT", f"cohortdefinition/{cid}", c['payload'])
                else:
                     print("  ❌ Still can't find ID after 409. Skipping.")
                     continue
            elif isinstance(resp, dict) and 'id' in resp:
                cid = resp['id']
                print(f"  ✅ Created ID: {cid}")
            else:
                print("  ❌ Failed to create definition")
                continue

        registered_ids[cid] = c['name']

        # Generate on SYNTHEA23M
        print(f"  🚀 Generating...")
        api_request("GET", f"cohortdefinition/{cid}/generate/{SOURCE_KEY}")

    # 3. Poll
    print(f"\n⏳ Polling for results...")
    start_time = time.time()
    while True:
        all_complete = True
        statuses = []
        
        for cid, name in registered_ids.items():
            info_list = api_request("GET", f"cohortdefinition/{cid}/info")
            found = False
            if isinstance(info_list, list):
                for info in info_list:
                    # Check sourceId=4 (SYNTHEA23M)
                    # Use safer .get() for dict access
                    gid = info.get('id', {})
                    if isinstance(gid, dict) and gid.get('sourceId') == 3:
                        found = True
                        status = info.get('status', 'UNKNOWN')
                        count = info.get('personCount', '?')
                        statuses.append(f"{name}: {status} ({count})")
                        
                        if status not in ['COMPLETE', 'FAILED']:
                            all_complete = False
                        elif status == 'FAILED':
                             print(f"    ❌ FAILED: {info.get('failMessage')}")
                        break
            
            if not found:
                 statuses.append(f"{name}: PENDING")
                 all_complete = False
        
        # Print status line
        elapsed = int(time.time() - start_time)
        print(f"[{elapsed}s] " + " | ".join(statuses))

        if all_complete:
            print("\n✅ All cohorts complete!")
            break
        
        if elapsed > 600: # 10 min timeout
            print("\n⚠ Timeout!")
            break
            
        time.sleep(10)

if __name__ == "__main__":
    main()
