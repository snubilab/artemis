"""
Static attribute mappings for Agent 3 (Cohort Assembler).
Maps IR values to OMOP Concept IDs and Circe-be format values.
"""

# Gender Concept IDs (standard OMOP)
GENDER_MAP = {
    "MALE": 8507,
    "FEMALE": 8532,
    "M": 8507,
    "F": 8532
}

# Race Concept IDs (standard OMOP)
RACE_MAP = {
    "WHITE": 8527,
    "BLACK": 8516,
    "ASIAN": 8515,
    "HISPANIC": 38003563,
    "OTHER": 8522
}

# Comparison operators: IR format -> Circe format
OPERATOR_MAP = {
    "lt": "lt",      # Less than
    "gt": "gt",      # Greater than  
    "eq": "eq",      # Equal to
    "lte": "lte",    # Less than or equal
    "gte": "gte",    # Greater than or equal
    "neq": "neq",    # Not equal
    "bt": "bt",      # Between
    "nbt": "!bt"     # Not between
}

# OMOP Domain ID to Circe criteria type
DOMAIN_TO_CRITERIA_TYPE = {
    "Condition": "ConditionOccurrence",
    "Drug": "DrugExposure",
    "Measurement": "Measurement",
    "Procedure": "ProcedureOccurrence",
    "Observation": "Observation",
    "Visit": "VisitOccurrence",
    "Device": "DeviceExposure",
    "Death": "Death",
    "Demographics": "DemographicCriteria",
}

# Keywords that indicate demographic criteria (case-insensitive)
DEMOGRAPHIC_KEYWORDS = {"age", "gender", "sex", "race", "ethnicity"}

# PrimaryCriteria uses Era-based types for Drug/Condition domains
DOMAIN_TO_PRIMARY_CRITERIA_TYPE = {
    "Condition": "ConditionOccurrence",
    "Drug": "DrugEra",
    "Measurement": "Measurement",
    "Procedure": "ProcedureOccurrence",
    "Observation": "Observation",
    "Visit": "VisitOccurrence",
    "Device": "DeviceExposure",
    "Death": "Death"
}

# Common unit text to OMOP Unit Concept ID
UNIT_MAP = {
    "%": 8554,       # Percent
    "mg/dL": 8840,   # Milligram per deciliter
    "mmol/L": 8753,  # Millimole per liter
    "kg": 9529,      # Kilogram
    "kg/m2": 9531,   # Kilogram per square meter (BMI)
    "mmHg": 8876,    # Millimeter of mercury
    "year": 9448,    # Year
    "day": 8512,     # Day
    "mg": 8587,      # Milligram
}

# Occurrence type mapping for logic
OCCURRENCE_TYPE = {
    "PRESENCE": {"Type": 2, "Count": 1},   # At least 1
    "ABSENCE": {"Type": 0, "Count": 0},    # Exactly 0
    "FIRST": {"Type": 1, "Count": 1},      # First occurrence
    "ALL": {"Type": 2, "Count": 0}         # All occurrences
}

# Era types for drug/condition grouping
ERA_TYPE = {
    "DrugEra": True,
    "ConditionEra": True
}
