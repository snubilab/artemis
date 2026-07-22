#!/usr/bin/env python3
"""Debug ATT cohort L0 (TROY Entry Only) returning 0 patients.
Check the Circe JSON expression stored in WebAPI and compare with
the simplified test that returned 1238."""
import json
import urllib.request

WEBAPI_URL = "http://127.0.0.1/WebAPI"

def api_get(endpoint):
    url = f"{WEBAPI_URL}/{endpoint}"
    with urllib.request.urlopen(url) as resp:
        return json.loads(resp.read().decode())

# Get cohort 23 (ATT TROY L0) definition
d23 = api_get("cohortdefinition/23")
expr23 = json.loads(d23["expression"]) if isinstance(d23.get("expression"), str) else d23.get("expression", {})

# Get cohort 19 (SIMPLE TROY Lira Only) definition
d19 = api_get("cohortdefinition/19")
expr19 = json.loads(d19["expression"]) if isinstance(d19.get("expression"), str) else d19.get("expression", {})

print("=== ATT TROY L0 (ID=23, returns 0) ===")
print(f"ConceptSets: {len(expr23.get('ConceptSets',[]))}")
print(f"InclusionRules: {len(expr23.get('InclusionRules',[]))}")
print(f"PrimaryCriteria:")
print(json.dumps(expr23["PrimaryCriteria"], indent=2))
if "EndStrategy" in expr23 and expr23["EndStrategy"]:
    print(f"EndStrategy: {json.dumps(expr23['EndStrategy'], indent=2)}")
if "AdditionalCriteria" in expr23 and expr23["AdditionalCriteria"]:
    print(f"AdditionalCriteria: present")

print()
print("=== SIMPLE TROY (ID=19, returns 1238) ===")
print(f"ConceptSets: {len(expr19.get('ConceptSets',[]))}")
print(f"InclusionRules: {len(expr19.get('InclusionRules',[]))}")
print(f"PrimaryCriteria:")
print(json.dumps(expr19["PrimaryCriteria"], indent=2))

# Check for differences
print()
print("=== KEY DIFFERENCES ===")

# Check EndStrategy
es23 = expr23.get("EndStrategy")
es19 = expr19.get("EndStrategy")
print(f"EndStrategy L0: {json.dumps(es23)}")
print(f"EndStrategy Simple: {json.dumps(es19)}")

# Check AdditionalCriteria
ac23 = expr23.get("AdditionalCriteria")
ac19 = expr19.get("AdditionalCriteria")
print(f"AdditionalCriteria L0: {json.dumps(ac23)[:200] if ac23 else 'None'}")
print(f"AdditionalCriteria Simple: {json.dumps(ac19)[:200] if ac19 else 'None'}")

# Check CensoringCriteria
cc23 = expr23.get("CensoringCriteria", [])
cc19 = expr19.get("CensoringCriteria", [])
print(f"CensoringCriteria L0: {len(cc23)}")
print(f"CensoringCriteria Simple: {len(cc19)}")

# Check all keys
print()
print("=== ALL TOP-LEVEL KEYS ===")
print(f"L0: {sorted(expr23.keys())}")
print(f"Simple: {sorted(expr19.keys())}")
