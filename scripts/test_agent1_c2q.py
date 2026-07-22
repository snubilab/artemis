#!/usr/bin/env python3
"""
Test Agent 1 with C2Q-improved prompts on LEADER trial.
Focuses on HbA1c rule output: should produce PRESENCE(>=7) + ABSENCE(>=10).
"""
import sys
import json

sys.path.insert(0, ".")

from src.agents.agent1.parser import LogicDecomposer

NCT_ID = "NCT01179048"  # LEADER trial

print("=" * 60)
print("  Agent 1 Re-run: LEADER (C2Q-improved prompts)")
print("=" * 60)

# Run Agent 1
agent1 = LogicDecomposer()
ir = agent1.parse_nct(NCT_ID)

# Dump full IR for inspection
print("\n" + "=" * 60)
print("  Full IR Output")
print("=" * 60)

all_rules = ir.target.inclusion_rules + ir.target.exclusion_rules
for i, rule in enumerate(all_rules):
    rule_type = "INC" if rule in ir.target.inclusion_rules else "EXC"
    vc_str = ""
    if rule.value_constraint:
        vc = rule.value_constraint
        vc_str = f" VC({vc.op} {vc.value} {vc.unit_text})"
    win_str = ""
    if rule.window:
        win_str = f" W({rule.window.start}→{rule.window.end})"
    print(f"  [{rule_type}] {rule.name}: {rule.domain}/{rule.logic_type}{vc_str}{win_str}")

# Check HbA1c rules specifically
print("\n" + "=" * 60)
print("  HbA1c Rule Check")
print("=" * 60)

hba1c_rules = [
    r for r in all_rules
    if any(kw in (r.entity_text or "").lower() for kw in ["hba1c", "hemoglobin a1c", "a1c", "glycated"])
    or any(kw in (r.name or "").lower() for kw in ["hba1c", "a1c", "glycated"])
]

if not hba1c_rules:
    print("  ❌ NO HbA1c rules found in output!")
    sys.exit(1)

print(f"  Found {len(hba1c_rules)} HbA1c rule(s):")

has_lower = False
has_upper = False

for r in hba1c_rules:
    print(f"\n  Rule: {r.name}")
    print(f"    domain: {r.domain}")
    print(f"    logic_type: {r.logic_type}")
    print(f"    entity_text: {r.entity_text}")
    if r.value_constraint:
        vc = r.value_constraint
        print(f"    value_constraint: {vc.op} {vc.value} {vc.unit_text}")
        if vc.op in ("gte", "gt") and vc.value <= 8 and r.logic_type == "PRESENCE":
            has_lower = True
            print("    → ✅ Lower bound (PRESENCE ≥ 7%)")
        elif vc.op in ("gte", "gt") and vc.value >= 9 and r.logic_type == "ABSENCE":
            has_upper = True
            print("    → ✅ Upper bound (ABSENCE ≥ 10%)")
    else:
        print("    value_constraint: ❌ MISSING")
    if r.window:
        print(f"    window: {r.window.start} → {r.window.end}")

print("\n" + "=" * 60)
if has_lower and has_upper:
    print("  🎉 SUCCESS: HbA1c range correctly split into PRESENCE + ABSENCE")
elif has_lower:
    print("  ⚠ PARTIAL: Has lower bound but missing upper bound ABSENCE rule")
elif has_upper:
    print("  ⚠ PARTIAL: Has upper bound but missing lower bound PRESENCE rule")
else:
    print("  ❌ FAIL: HbA1c rules don't match expected pattern")

# Save IR as JSON for comparison
ir_dict = {
    "target": {
        "primary_criteria": {
            "domain": ir.target.primary_criteria.domain,
            "entity_text": ir.target.primary_criteria.entity_text,
        },
        "inclusion_rules": [
            {
                "name": r.name, "domain": r.domain, "entity_text": r.entity_text,
                "logic_type": r.logic_type,
                "value_constraint": {"op": r.value_constraint.op, "value": r.value_constraint.value,
                                     "unit_text": r.value_constraint.unit_text} if r.value_constraint else None,
                "window": {"start": r.window.start, "end": r.window.end} if r.window else None,
            }
            for r in ir.target.inclusion_rules
        ],
        "exclusion_rules": [
            {
                "name": r.name, "domain": r.domain, "entity_text": r.entity_text,
                "logic_type": r.logic_type,
                "value_constraint": {"op": r.value_constraint.op, "value": r.value_constraint.value,
                                     "unit_text": r.value_constraint.unit_text} if r.value_constraint else None,
                "window": {"start": r.window.start, "end": r.window.end} if r.window else None,
            }
            for r in ir.target.exclusion_rules
        ],
    }
}

out_path = "data/sample/LEADER/ARTEMIS_LEADER_c2q_improved_ir.json"
with open(out_path, "w") as f:
    json.dump(ir_dict, f, indent=2)
print(f"\n  Saved IR to: {out_path}")
