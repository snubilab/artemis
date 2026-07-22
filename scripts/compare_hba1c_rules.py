#!/usr/bin/env python3
"""Compare TROY HbA1c rule (index 1) vs ARTEMIS HbA1c rule (index 3)."""
import json

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

troy = load_circe(TROY_PATH)
artemis = load_circe(ARTEMIS_PATH)

# Build CS lookup
troy_cs = {cs["id"]: cs for cs in troy["ConceptSets"]}
artemis_cs = {cs["id"]: cs for cs in artemis["ConceptSets"]}

print("=" * 70)
print("TROY HbA1c Rule (index 1):")
print("=" * 70)
troy_rule = troy["InclusionRules"][1]
print(f"Name: {troy_rule['name']}")
print(json.dumps(troy_rule, indent=2)[:2000])

# Show referenced concept sets
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

troy_csids = find_cs_ids(troy_rule)
print(f"\nReferenced CS IDs: {troy_csids}")
for csid in troy_csids:
    cs = troy_cs.get(csid)
    if cs:
        concepts = [item["concept"]["CONCEPT_ID"] for item in cs["expression"]["items"]]
        print(f"  CS[{csid}] {cs['name']}: concepts={concepts}")

print("\n" + "=" * 70)
print("ARTEMIS HbA1c Rule (index 3):")
print("=" * 70)
artemis_rule = artemis["InclusionRules"][3]
print(f"Name: {artemis_rule['name']}")
print(json.dumps(artemis_rule, indent=2)[:2000])

artemis_csids = find_cs_ids(artemis_rule)
print(f"\nReferenced CS IDs: {artemis_csids}")
for csid in artemis_csids:
    cs = artemis_cs.get(csid)
    if cs:
        concepts = [item["concept"]["CONCEPT_ID"] for item in cs["expression"]["items"]]
        print(f"  CS[{csid}] {cs['name']}: concepts={concepts}")
