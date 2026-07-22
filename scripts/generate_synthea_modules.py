import os
import json

MODULES_DIR = "/Users/kyh/Workspace/Broadsea/data/synthea/synthea/src/main/resources/modules"

def create_target_module(name, age_low, age_high, conditions, observations=None):
    states = {
        "Initial": {
            "type": "Initial",
            "direct_transition": "Wait for target age"
        },
        "Terminal": {
            "type": "Terminal"
        },
        "Wait for target age": {
            "type": "Delay",
            "exact": {"quantity": age_low, "unit": "years"},
            "direct_transition": "Trigger Encounter"
        },
        "Trigger Encounter": {
            "type": "Encounter",
            "encounter_class": "ambulatory",
            "reason": "Target Condition Encounter",
            "codes": [{"system": "SNOMED-CT", "code": "185349003", "display": "Encounter for check up (procedure)"}],
            "direct_transition": "Condition 0" if conditions else ("Observation 0" if observations else "End Encounter")
        }
    }
    
    current_state = "Condition 0"
    for i, cond in enumerate(conditions):
        next_state = f"Condition {i+1}" if i < len(conditions) - 1 else ("Observation 0" if observations else "End Encounter")
        states[f"Condition {i}"] = {
            "type": "ConditionOnset",
            "codes": [{"system": "SNOMED-CT", "code": cond["code"], "display": cond["display"]}],
            "target_encounter": "Trigger Encounter",
            "direct_transition": next_state
        }
        
    if observations:
        for i, obs in enumerate(observations):
            next_state = f"Observation {i+1}" if i < len(observations) - 1 else "End Encounter"
            states[f"Observation {i}"] = {
                "type": "Observation",
                "category": "laboratory",
                "unit": obs["unit"],
                "codes": [{"system": "LOINC", "code": obs["code"], "display": obs["display"]}],
                "exact": {"quantity": obs["value"]},
                "target_encounter": "Trigger Encounter",
                "direct_transition": next_state
            }
            
    states["End Encounter"] = {
        "type": "EncounterEnd",
        "direct_transition": "Terminal"
    }

    module = {
        "name": name,
        "remarks": [f"Custom module for {name} generated for testing."],
        "states": states,
        "gmf_version": 2
    }
    
    out_path = os.path.join(MODULES_DIR, f"artemis_{name.lower()}.json")
    with open(out_path, "w") as f:
        json.dump(module, f, indent=2)
    print(f"Generated {out_path}")

def main():
    # 1. LEADER Target (T2DM, MI, HbA1c >= 7.0)
    create_target_module(
        name="LEADER",
        age_low=62,
        age_high=65,
        conditions=[
            {"code": "44054006", "display": "Type 2 diabetes mellitus (disorder)"},
            {"code": "22298006", "display": "Myocardial infarction (disorder)"}
        ],
        observations=[
            {"code": "4548-4", "display": "Hemoglobin A1c/Hemoglobin.total in Blood", "value": 8.5, "unit": "%"}
        ]
    )
    
    # 2. PLATO Target (ACS / MI)
    # Covers both STEMI and NSTEMI/LBBB patient sub-types:
    #   - STEMI (SNOMED 401303003 → OMOP 312327): acute ST-elevation MI
    #   - Generic MI (SNOMED 22298006 → OMOP 4329847): covers NSTEMI path
    #   - LBBB (SNOMED 63467002 → OMOP 316998): satisfies ST-elevation/LBBB inclusion rule
    #   - Systolic BP (LOINC 8480-6, value=130 mmHg): satisfies BP < 160 exclusion guard
    create_target_module(
        name="PLATO",
        age_low=55,
        age_high=60,
        conditions=[
            {"code": "401303003", "display": "Acute ST segment elevation myocardial infarction (disorder)"},  # → OMOP 312327 STEMI
            {"code": "22298006", "display": "Myocardial infarction (disorder)"},
            {"code": "63467002", "display": "Left bundle branch block (disorder)"},  # → OMOP 316998
        ],
        observations=[
            {"code": "8480-6", "display": "Systolic blood pressure", "value": 130, "unit": "mmHg"},
        ]
    )
    
    # 3. ARISTOTLE Target (Atrial Fibrillation + Risk Factor like Stroke or old age)
    create_target_module(
        name="ARISTOTLE",
        age_low=76, # Forces age risk factor automatically
        age_high=80,
        conditions=[
            {"code": "49436004", "display": "Atrial fibrillation (disorder)"},
            {"code": "230690007", "display": "Cerebrovascular accident (disorder)"}
        ]
    )

if __name__ == "__main__":
    main()
