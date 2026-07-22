#!/usr/bin/env python3
"""Analyze inclusion rules from TROY and ARTEMIS for grouping."""
import json

with open("artemis/data/sample/LEADER/[TROY] Liraglutide (LEADER) v3.4.json") as f:
    troy = json.load(f)
with open("artemis/data/sample/LEADER/ARTEMIS_LEADER_design_paper_e2e.json") as f:
    artemis = json.load(f)


def find_cs_ids(obj):
    cs_ids = set()
    if isinstance(obj, dict):
        if "CodesetId" in obj:
            cs_ids.add(obj["CodesetId"])
        for v in obj.values():
            cs_ids |= find_cs_ids(v)
    elif isinstance(obj, list):
        for item in obj:
            cs_ids |= find_cs_ids(item)
    return cs_ids


def cs_name_map(definition):
    return {cs["id"]: cs["name"] for cs in definition["ConceptSets"]}


print("=== TROY Inclusion Rules (18) ===")
troy_cs_map = cs_name_map(troy)
for i, r in enumerate(troy["InclusionRules"]):
    cs_ids = find_cs_ids(r)
    cs_names = [f'{cid}:{troy_cs_map.get(cid,"?")[:35]}' for cid in sorted(cs_ids)]
    print(f'  [{i:2d}] {r["name"]}')
    print(f'       CS: {cs_names}')

print()
print("=== ARTEMIS Inclusion Rules (32) ===")
artemis_cs_map = cs_name_map(artemis)
for i, r in enumerate(artemis["InclusionRules"]):
    cs_ids = find_cs_ids(r)
    cs_names = [f'{cid}:{artemis_cs_map.get(cid,"?")[:35]}' for cid in sorted(cs_ids)]
    print(f'  [{i:2d}] {r["name"]}')
    print(f'       CS: {cs_names}')
