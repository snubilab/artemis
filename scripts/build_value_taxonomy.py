#!/usr/bin/env python3
"""Derive the stage-2 value-threshold classification taxonomy from the corpus.

Emits ``docs/daily_notes/tte_value_taxonomy.json``, which is the single source for
both the stage-2 classifier prompt and the dashboard's 분류 체계 tab.

Why a generator and not a hand-written JSON: every count in the artifact is a query
over ``tests/fixtures/value_constraint_corpus.yaml``. Hand-maintained counts drift
away from the corpus silently, and a taxonomy that misstates its own evidence is
worse than none. The class assignment (``CLASS_OF``) is the only hand-authored
judgement here; counts, examples, op spellings and notation tallies are computed.

    python scripts/build_value_taxonomy.py            # write the JSON
    python scripts/build_value_taxonomy.py --prompt   # render the classifier prompt
    python scripts/build_value_taxonomy.py --check    # coverage + invariant self-check

``--prompt`` is the anti-drift mechanism: the prompt is a pure function of the JSON,
so there is no second copy of the taxonomy to keep in sync.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "tests" / "fixtures" / "value_constraint_corpus.yaml"
OUT = ROOT / "docs" / "daily_notes" / "tte_value_taxonomy.json"

Entry = dict[str, Any]

# Every class other than MEASUREMENT_VALUE, listed explicitly. MEASUREMENT_VALUE is
# the default because it is 88 of 114 entries and listing it would be noise — but
# defaulting is only safe for positives, so _check asserts that every corpus entry
# with kind ``not_a_constraint`` appears here by name.
CLASS_OF: dict[str, str] = {
    "abs-years-age": "AGE",
    "abs-years-escaped": "AGE",
    "neg-blood-donation-window": "TEMPORAL_WINDOW",
    "neg-tia-window": "TEMPORAL_WINDOW",
    "neg-beverage-window": "TEMPORAL_WINDOW",
    "neg-hiv-duration": "STATE_DURATION",
    "neg-stable-dose-window": "STATE_DURATION",
    "abs-mg-dose": "DRUG_DOSE",
    "no-unit-ecog": "SCORE_GRADE",
    "no-unit-ecog-gte": "SCORE_GRADE",
    "unresolvable-dipstick": "SCORE_GRADE",
    "abs-ml-volume": "EVENT_QUANTITY",
    "no-unit-lines-of-therapy": "EVENT_QUANTITY",
    "unresolvable-cups": "REVIEW",
    "neg-stat-upper-boundary": "NON_CRITERION",
    "neg-stat-margin": "NON_CRITERION",
    "neg-stat-ci-hr": "NON_CRITERION",
    "neg-stat-alpha": "NON_CRITERION",
    "neg-stat-mace-ci": "NON_CRITERION",
    "neg-hba1c-range": "NON_CRITERION",
    "neg-unit-conversion": "NON_CRITERION",
    "neg-cup-definition": "NON_CRITERION",
    "neg-24h-collection": "NON_CRITERION",
    "neg-prior-lines-count": "NON_CRITERION",
    "neg-gilbert-carveout": "NON_CRITERION",
    "no-unit-child-pugh": "NON_CRITERION",
}

DEFAULT_CLASS = "MEASUREMENT_VALUE"

CLASSES: list[dict[str, Any]] = [
    {
        "id": "MEASUREMENT_VALUE",
        "label_ko": "측정값",
        "summary_ko": "환자에게서 측정된 양. 단위가 시간이든 무차원이든 상관없이 head가 검사·활력징후·체격이면 여기.",
        "definition": (
            "The number is the result of a measurement or observation made on the "
            "patient: a laboratory analyte, a vital sign, an imaging or ECG "
            "measurement, or a body metric such as weight or BMI. Decide by the head "
            "-- what the number modifies -- never by the unit. A time unit (msec, "
            "years) or a dimensionless index (INR) does not move a number out of this "
            "class."
        ),
        "circe_destination": (
            "Measurement criterion. reference_bound=absolute -> ValueAsNumber with a "
            "sibling Unit array; uln -> RangeHighRatio; lln -> RangeLowRatio."
        ),
        "stage3": "src/services/value_constraint.py :: build_measurement_value_filter",
        "signals": {
            "positive": [
                "The head is a named analyte, panel term or abbreviation (ALT, AST, bilirubin, creatinine, TSH, HbA1c, INR, ANC, platelets, hemoglobin, AFP, NT-proBNP, HBsAg, calcitonin).",
                "The head is a vital sign or physiologic measurement (systolic/diastolic blood pressure, heart rate, LVEF, QTc, mitral valve area, ST-segment elevation).",
                "The head is a body metric (body weight, BMI).",
                "The phrase names a reference bound (ULN, LLN, upper/lower limit of normal, institutional ULN) -- only measurements have laboratory reference ranges.",
                "The unit is a laboratory or physiologic unit (mg/dL, mmol/L, g/L, /mm3, 10^9/L, mmHg, mL/min, mL/min/1.73m2, ng/mL, pg/mL, IU/mL, mV, msec, %).",
            ],
            "negative": [
                "The head names a graded clinical scale (ECOG, Child-Pugh, dipstick protein) -> SCORE_GRADE.",
                "The head is a drug and the number is how much of it is given -> DRUG_DOSE.",
                "The head is 'age', or the only head is a bare time unit -> AGE.",
                "The number counts events or says how much was administered, donated or lost -> EVENT_QUANTITY.",
                "The number is the distance in time from an anchor event -> TEMPORAL_WINDOW.",
            ],
        },
        "hazard": (
            "A uln/lln span must emit only the ratio operand. Circe ANDs siblings, so a "
            "RangeHighRatio plus a ValueAsNumber on the same value leaves defect #10 "
            "intact. An unrecognised unit must leave Unit unset, never fall back to a "
            "near neighbour -- a wrong Unit filter matches zero rows."
        ),
        "draft_verdict": "correct",
        "example_ids": ["uln-x-spaced", "abs-msec-qtc", "abs-mgdl-upper"],
    },
    {
        "id": "AGE",
        "label_ko": "나이",
        "summary_ko": "환자 나이. 시간 단위를 달고 있어도 측정값이 아니라 인구통계 조건이다.",
        "definition": (
            "The number is the patient's age. This is the case Chia settles against "
            "the unit: 'Men with age >= 18 years' is a Value, not a Temporal, because "
            "the head is 'age'. Criteria2Query 3.0 definition 8 adds the elided-head "
            "rule -- when a bare time unit appears with no other head ('patients who "
            "are at least 18 years old'), supply 'age' as the head."
        ),
        "circe_destination": (
            "DemographicCriteria.Age inside a DemographicCriteriaList. Not a "
            "Measurement, so no ValueAsNumber and no Unit."
        ),
        "stage3": "demographic path; must bypass build_measurement_value_filter",
        "signals": {
            "positive": [
                "An explicit 'age' / 'aged' / 'years old' head.",
                "A time unit with no competing head anywhere in the criterion (elided-head rule).",
                "An anchor phrase may still be present ('age >= 18 years at screening') -- the head test runs first and wins.",
            ],
            "negative": [
                "A time unit whose head is a measurement (QTc in msec) -> MEASUREMENT_VALUE.",
                "A time unit measuring the distance to an anchor event -> TEMPORAL_WINDOW.",
                "A time unit measuring how long a state has held -> STATE_DURATION.",
            ],
        },
        "hazard": (
            "The corpus 'expect' for abs-years-age carries unit_concept_id 9448 (year). "
            "That is the value-constraint IR's view of the span, not a routing "
            "instruction. Feeding an AGE span to build_measurement_value_filter emits "
            "ValueAsNumber + Unit(year) on a Measurement criterion, which matches "
            "nothing. AGE must leave the measurement path before stage 3."
        ),
        "draft_verdict": "correct",
        "example_ids": ["abs-years-age", "abs-years-escaped"],
    },
    {
        "id": "TEMPORAL_WINDOW",
        "label_ko": "시간창",
        "summary_ko": "기준 사건과 index date 사이의 시간 거리. 사건이 타임라인 위에 놓인다.",
        "definition": (
            "The number measures the distance in time between a qualifying event and "
            "the index date or another anchor. Something happened, and the criterion "
            "constrains when. Chia's Temporal requires a Reference_point linked by "
            "has_index; in eligibility text that anchor is often elided in exclusion "
            "criteria, so absence of an explicit anchor does not rule this class out."
        ),
        "circe_destination": (
            "StartWindow / EndWindow on the correlated criterion, expressed in days. "
            "Never ValueAsNumber."
        ),
        "stage3": "window path; not a value constraint",
        "signals": {
            "positive": [
                "A relative-time preposition plus a time unit: within / prior to / before / after / since / in the past N days|weeks|months|years.",
                "A named anchor: randomization, first dose, screening, ICF, enrollment, Day -1, index date.",
                "The head is an event (a donation, a stroke, a dose), not a quantity.",
            ],
            "negative": [
                "The criterion requires a state to have persisted for N units -> STATE_DURATION.",
                "The time expression is an attributive modifier of a procedure name ('24-hour urine collection') -> NON_CRITERION / protocol_or_procedure_name.",
                "The head is 'age' -> AGE.",
            ],
        },
        "hazard": (
            "Only 3 corpus instances carry this class, and all three come from "
            "not_a_constraint entries recorded to keep them out of the value path. The "
            "boundary this whole design exists to police is empirically tested by three "
            "examples. The anchor vocabulary is open ('since transplant', 'post-MI', "
            "'from the time of diagnosis') and must be logged when it misses."
        ),
        "draft_verdict": "correct",
        "example_ids": ["neg-tia-window", "neg-beverage-window"],
    },
    {
        "id": "STATE_DURATION",
        "label_ko": "상태 지속기간",
        "summary_ko": "질환·투약 같은 상태가 얼마나 오래 유지됐는지. 앵커 유무로는 시간창과 안 갈린다.",
        "definition": (
            "The number measures how long a state has persisted -- a disease's duration "
            "since onset, or how long a treatment has been unchanged. Unlike "
            "TEMPORAL_WINDOW there is no event being placed on the timeline; a "
            "condition or exposure is required to have held continuously for N units."
        ),
        # Settled by ADR-031-A against synthea_cdm and the four site CDMs. Do not
        # revert this to era length: ConditionEra.EraLength measures how densely the
        # condition was *recorded*, not how long it was *held*, so the same JSON gives
        # different answers per site's coding habits. Measured: all 30 synthea HIV eras
        # are 1 day long, so EraLength > 1826 returns 0 patients, and condition_era is
        # absent from three of the four site CDMs (hard SQL error, not an empty result).
        "circe_destination": (
            "ConditionOccurrence with a StartWindow open into the past and ending "
            "before index -- Start {Coeff:-1}, End {Days:N, Coeff:-1}, UseEventEnd "
            "false. Gold uses this exact shape 28 times. NOT ConditionEra.EraLength, "
            "which carries no index date and measures record density. The drug "
            "analogue (DrugEra) needs the same window plus an EndWindow with "
            "UseEventEnd true, so the era is still open at index. See ADR-031-A."
        ),
        "stage3": (
            "window builder, not a value filter; ADR-031-A specifies the fragment. "
            "Verify the site's observation periods reach back N days before trusting a "
            "zero -- Start {Coeff:-1} is not minus-infinity, the SQL still bounds it by "
            "OP_START_DATE."
        ),
        "signals": {
            "positive": [
                "A stative head: long-standing, stable, unchanged, ongoing, duration of, since diagnosis.",
                "The criterion is satisfied by a span of time, not by an event occurring inside one.",
            ],
            "negative": [
                "A discrete event is being located in time -> TEMPORAL_WINDOW.",
                "The head is a measured quantity -> MEASUREMENT_VALUE.",
            ],
        },
        "hazard": (
            "This is the class the literature leaves open. Chia's Temporal requires a "
            "Reference_point, which a bare disease duration does not have, so Chia "
            "cannot hold it; TrialGenie's Value definition absorbs 'the duration of "
            "drugs' and would mis-route it to a value filter."
        ),
        "draft_verdict": (
            "renamed from the draft's CONDITION_DURATION. Only one of the two corpus "
            "instances is a condition duration; the other is a stable-therapy duration. "
            "'Condition' is too narrow."
        ),
        "example_ids": ["neg-hiv-duration", "neg-stable-dose-window"],
    },
    {
        "id": "DRUG_DOSE",
        "label_ko": "약물 용량",
        "summary_ko": "투여되는 약의 양. 측정값 경로로 보내면 Measurement에서 아무와도 안 맞는다.",
        "definition": (
            "The number is an amount of drug administered, permitted or prohibited, and "
            "its head is a drug name or drug class."
        ),
        "circe_destination": (
            "DrugExposure criterion: EffectiveDrugDose + DoseUnit, or Quantity. Not a "
            "Measurement value filter."
        ),
        "stage3": "drug path; must bypass build_measurement_value_filter",
        "signals": {
            "positive": [
                "A drug or drug-class name adjacent to the number (prednisolone, insulin, 'or equivalent').",
                "A dose unit (mg, mg/kg, mg/day, IU) attached to a drug rather than to a specimen.",
                "Dosing verbs: receiving, taking, treated with, on a stable dose of.",
            ],
            "negative": [
                "The unit is a concentration in a specimen (mg/dL, ng/mL) -> MEASUREMENT_VALUE.",
                "The number is how long the dose has been stable -> STATE_DURATION.",
            ],
        },
        "hazard": (
            "src/agents/agent3/mappings.py maps 'mg' to concept 8587, which is "
            "millilitre. A dose routed through that table gets a wrong DoseUnit and "
            "matches zero rows. Recorded in the corpus note on abs-mg-dose."
        ),
        "draft_verdict": "correct, but supported by a single corpus instance",
        "example_ids": ["abs-mg-dose"],
    },
    {
        "id": "SCORE_GRADE",
        "label_ko": "점수·등급",
        "summary_ko": "명명된 임상 척도 위의 눈금. 단위를 붙이면 안 되고, 서열 등급은 숫자로도 안 된다.",
        "definition": (
            "The number is a point on a named clinical scale or grading system (ECOG, "
            "dipstick protein, Child-Pugh, NYHA). It is ordinal, not a physical "
            "quantity, and it carries no unit even when a scale word follows it "
            "('points', '+')."
        ),
        "circe_destination": (
            "Observation or Measurement criterion. Numeric scales -> ValueAsNumber with "
            "no Unit. Ordinal labels ('2+ on dipstick', Child-Pugh B/C) are stored in "
            "OMOP as value_as_concept_id -> ValueAsConcept, not ValueAsNumber."
        ),
        "stage3": "build_measurement_value_filter with unit_text=None for numeric scales only",
        "signals": {
            "positive": [
                "A named scale precedes the number: ECOG, WHO performance status, Child-Pugh, NYHA, mRS, Karnofsky.",
                "A scale word stands where a unit would be: 'points', 'grade', 'class', a trailing '+'.",
                "The scale's range is small and bounded (0-5), unlike a laboratory range.",
            ],
            "negative": [
                "The head is an analyte with a real unit -> MEASUREMENT_VALUE.",
                "The grade is referenced by letter with no number at all -> NON_CRITERION / non_numeric_grade.",
            ],
        },
        "hazard": (
            "Two different failures. Attaching a Unit to a score filters on a unit the "
            "row does not carry. Emitting ValueAsNumber for an ordinal label filters on "
            "a column the row leaves null. Both return zero patients with no error."
        ),
        "draft_verdict": (
            "correct. ECOG and the dipstick grade both belong here; the draft's "
            "suspicion about the dipstick was right -- it is not a measurement value."
        ),
        "example_ids": ["no-unit-ecog", "unresolvable-dipstick"],
    },
    {
        "id": "EVENT_QUANTITY",
        "label_ko": "사건 수량",
        "summary_ko": "얼마나 많이 / 몇 번. 검사값이 아니라 시술·치료 사건에 붙는 수량이다.",
        "definition": (
            "The number says how much of something happened or how many times, attached "
            "to a procedure, treatment episode or exposure event rather than to a "
            "measured biological quantity. Nothing was measured on the patient; "
            "something was counted or dispensed."
        ),
        "circe_destination": (
            "Amounts -> ProcedureOccurrence/Observation Quantity or ValueAsNumber. "
            "Counts of episodes -> a nested criteria group with an Occurrence count, "
            "not a value filter."
        ),
        "stage3": "unimplemented; route to review",
        "signals": {
            "positive": [
                "A countable clinical noun follows the number: lines of therapy, cycles, prior regimens, transfusions.",
                "The head is an event verb phrase: donated, lost, received, administered.",
                "A volume or amount that belongs to the event, not to a specimen ('blood donation > 500 mL').",
            ],
            "negative": [
                "The volume is a specimen measurement -> MEASUREMENT_VALUE.",
                "The amount is a drug dose -> DRUG_DOSE.",
            ],
        },
        "hazard": (
            "Both instances have laboratory-looking shapes ('> 500 mL', '> 8'), so the "
            "draft taxonomy would have sent them to a Measurement value filter. There is "
            "no Measurement concept for 'volume of blood donated' or 'number of therapy "
            "lines', so that filter matches zero rows."
        ),
        "draft_verdict": "added -- missing from the draft; both instances would have become MEASUREMENT_VALUE",
        "example_ids": ["abs-ml-volume", "no-unit-lines-of-therapy"],
    },
    {
        "id": "REVIEW",
        "label_ko": "검토 필요",
        "summary_ko": "진짜 임계값이지만 대상 CDM에 갈 곳이 없다. 기본값으로 밀어넣지 말 것.",
        "definition": (
            "The span is a genuine eligibility threshold but has no representable "
            "destination in the target CDM, or the class cannot be decided from the "
            "text available. Emit REVIEW rather than guessing."
        ),
        "circe_destination": "none -- human review queue",
        "stage3": "n/a",
        "signals": {
            "positive": [
                "The head is a lifestyle or self-reported quantity with no coded OMOP representation (cups of coffee per day, packs per day, drinks per week).",
                "The head cannot be resolved because the decomposer split the criterion and the analyte stayed in another span.",
                "Two classes are equally defensible from the text.",
            ],
            "negative": [
                "A class is decidable -- do not use REVIEW as a low-confidence default for a resolvable head.",
            ],
        },
        "hazard": (
            "REVIEW is cheap; a wrong class is not. The failure mode of every other "
            "class is a silent zero, so REVIEW is strictly safer than a guess."
        ),
        "draft_verdict": "correct, and now has corpus support (1 instance)",
        "example_ids": ["unresolvable-cups"],
    },
    {
        "id": "NON_CRITERION",
        "label_ko": "조건 아님",
        "summary_ko": "임계값처럼 생겼지만 어떤 criteria 속성도 되면 안 되는 구문. 8개 계열이 각각 다르게 인식된다.",
        "definition": (
            "The span is threshold-shaped but must not become any criterion attribute. "
            "Eight families sit here and they are recognised differently, so treat the "
            "family as part of the answer."
        ),
        "circe_destination": "none -- drop the span",
        "stage3": "n/a",
        "signals": {
            "positive": [
                "See the per-family signals; there is no single cue.",
            ],
            "negative": [
                "The span constrains a patient property that a CDM row can hold -> one of the positive classes.",
            ],
        },
        "hazard": (
            "The statistical family is the highest-risk false positive in the corpus: "
            "'the upper boundary of the two-sided 95.02% confidence interval was less "
            "than 1.3' has the same surface shape as 'above the upper limit of normal'."
        ),
        "naming_caveat": (
            "2 of the 12 members are genuine eligibility criteria -- 'Child-Pugh score "
            "B/C grade' and 'at least three lines of therapy'. They land here because "
            "they carry no parseable numeric threshold, not because they are not "
            "criteria. The draft name NON_CRITERION overstates that; the class means "
            "'not a numeric value span'."
        ),
        "draft_verdict": "kept, but the name overstates -- see naming_caveat",
        "example_ids": ["neg-stat-upper-boundary", "neg-unit-conversion"],
    },
]

NON_CRITERION_FAMILIES: list[dict[str, Any]] = [
    {
        "id": "statistical_decision_rule",
        "label_ko": "통계적 판정 규칙",
        "what": "A confidence-interval bound, a noninferiority margin, an alpha level or a hazard-ratio threshold from the trial's analysis plan.",
        "signals": [
            "confidence interval, CI, upper/lower boundary, margin, noninferiority, alpha level, two-sided, one-sided, hazard ratio",
            "The number is compared against a study conclusion, not against a patient property.",
            "The surrounding text is a Methods/Statistics paragraph rather than an eligibility list.",
        ],
        "entry_ids": [
            "neg-stat-upper-boundary",
            "neg-stat-margin",
            "neg-stat-ci-hr",
            "neg-stat-alpha",
            "neg-stat-mace-ci",
        ],
    },
    {
        "id": "inclusive_range",
        "label_ko": "구간",
        "what": "Two thresholds bounding one analyte, written as a range.",
        "signals": [
            "N - M with a shared unit, or 'between N and M', often followed by 'inclusive'.",
            "No single comparator token.",
        ],
        "entry_ids": ["neg-hba1c-range"],
    },
    {
        "id": "unit_conversion_restatement",
        "label_ko": "단위 환산 반복",
        "what": "A parenthetical restatement of a threshold already captured, in a different unit.",
        "signals": [
            "Parenthesised, immediately adjacent to a threshold on the same analyte, different unit.",
            "Requires sibling context: in isolation the span is indistinguishable from a real threshold.",
        ],
        "entry_ids": ["neg-unit-conversion"],
    },
    {
        "id": "definitional_equality",
        "label_ko": "정의문",
        "what": "A definition of a term used elsewhere in the criterion.",
        "signals": [
            "An '=' with a quantity on both sides, inside a parenthetical.",
            "The left side is a word being defined, not a patient property.",
        ],
        "entry_ids": ["neg-cup-definition"],
    },
    {
        "id": "protocol_or_procedure_name",
        "label_ko": "프로토콜 이름",
        "what": "A number that is an attributive modifier of a procedure name.",
        "signals": [
            "The number sits before a procedure noun with a hyphen ('24-hour urine collection').",
            "No comparator anywhere in the span.",
        ],
        "entry_ids": ["neg-24h-collection"],
    },
    {
        "id": "spelled_out_count",
        "label_ko": "숫자어 카운트",
        "what": "A count written as a number word rather than digits.",
        "signals": [
            "one, two, three ... with no digit in the span.",
        ],
        "entry_ids": ["neg-prior-lines-count"],
    },
    {
        "id": "carve_out_clause",
        "label_ko": "예외 조항",
        "what": "An exception attached to a real threshold, carrying no threshold of its own.",
        "signals": [
            "this will not apply to, except for, unless, with the following exception.",
            "No number in the span.",
        ],
        "entry_ids": ["neg-gilbert-carveout"],
    },
    {
        "id": "non_numeric_grade",
        "label_ko": "숫자 없는 등급",
        "what": "A graded scale referenced by letter or class, with no numeric threshold.",
        "signals": [
            "A scale name followed by letters or classes (Child-Pugh B/C, NYHA III/IV).",
        ],
        "entry_ids": ["no-unit-child-pugh"],
    },
]

# surface spelling -> (circe op, ambiguous, note). Counts come from the corpus.
OP_SPELLINGS: list[tuple[str, str, bool, str]] = [
    ("\\>", "gt", False, "ClinicalTrials.gov escape for '>'."),
    ("\\<", "lt", False, "ClinicalTrials.gov escape for '<'."),
    ("=\\>", "gte", False, "ClinicalTrials.gov escape; de-escapes to '=>', which is not a standard spelling and must also be in the table."),
    ("=\\<", "lte", False, "ClinicalTrials.gov escape; de-escapes to '=<'."),
    ("\\>=", "gte", False, "Escape placed on the first character only."),
    ("\\<=", "lte", False, "Escape placed on the first character only."),
    (">", "gt", False, "Plain ASCII; reached after upstream de-escaping."),
    ("<", "lt", False, "Plain ASCII; reached after upstream de-escaping."),
    (">=", "gte", False, "Plain ASCII."),
    ("<=", "lte", False, "Plain ASCII."),
    ("=>", "gte", False, "De-escaped form of '=\\>'. Zero corpus entries spell it directly."),
    ("=<", "lte", False, "De-escaped form of '=\\<'. Zero corpus entries spell it directly."),
    ("≥", "gte", False, "U+2265 GREATER-THAN OR EQUAL TO."),
    ("≤", "lte", False, "U+2264 LESS-THAN OR EQUAL TO."),
    ("above", "gt", False, "Strict in the corpus."),
    ("below", "lt", False, "Strict in the corpus."),
    ("more than", "gt", False, ""),
    ("at least", "gte", False, ""),
    ("at or below", "lte", False, ""),
    ("equal or above", "gte", False, "Spells gte in words."),
    ("higher than", "gt", False, "Bare form; see 'times higher than' for the ambiguous one."),
    (
        "times higher than",
        "gt",
        True,
        "AMBIGUOUS on the value, not the operator. '5 times higher than the ULN' is read "
        "by the corpus as gt 5.0, but careful English makes 'N times higher than X' mean "
        "(N+1)*X. Both readings are defensible and the corpus commits to 5.0.",
    ),
    ("eq", "eq", True, "Zero corpus instances. Retained only because Circe accepts it; unvalidated."),
]

NOTATION_SECTIONS: list[dict[str, Any]] = [
    {
        "id": "reference_bound",
        "label_ko": "기준범위(ULN/LLN) 표기",
        "what": "Spellings of the upper/lower limit of normal that stage 3 must fold into reference_bound.",
        "rule": "Fold every spelling to reference_bound in {absolute, uln, lln} and clear unit_text; the bound is not a unit.",
    },
    {
        "id": "implicit_multiplier_one",
        "label_ko": "암묵적 배수 1",
        "what": "Entries that write no multiplier at all: the implied comparison is against 1 x the bound.",
        "rule": (
            "When a reference bound appears with no numeral, emit value 1.0. Do not skip the span. "
            "AMBIGUOUS: 'below the lower limit of normal' is read here as RangeLowRatio lt 1.0, but "
            "Circe's Abnormal attribute expresses the same clinical intent and defers the judgement "
            "to the source lab's own flag. The corpus commits to the ratio; both are defensible."
        ),
    },
    {
        "id": "overloaded_x",
        "label_ko": "중의적 x 토큰",
        "what": "The same x / × / X token means 'multiple of the reference bound' and 'times ten to the'.",
        "rule": "x followed by 10 (with or without ^ / * / superscript) is scientific notation and belongs to the unit; x followed by ULN/LLN or a bound phrase is a ratio.",
    },
    {
        "id": "comparator_escapes",
        "label_ko": "비교연산자 이스케이프",
        "what": "ClinicalTrials.gov backslash escapes and their unicode alternatives.",
        "rule": "Strip backslashes before matching, but keep '=<' and '=>' in the operator table -- they are what the escapes de-escape to.",
    },
    {
        "id": "unit_spellings",
        "label_ko": "단위 철자",
        "what": "Distinct unit_text spellings and the UCUM concepts they resolve to.",
        "rule": "NFKC-normalise, drop whitespace, match case-sensitively first (G/l is giga-per-litre, g/l is gram-per-litre). An unrecognised unit leaves Unit unset.",
    },
    {
        "id": "unresolvable_units",
        "label_ko": "해석 불가 단위",
        "what": "Unit texts with no standard UCUM Unit concept in the vocabulary.",
        "rule": "Emit ValueAsNumber and leave Unit unset. Never substitute a near neighbour.",
    },
    {
        "id": "numeral_notation",
        "label_ko": "수 표기",
        "what": "Thousands separators, superscripts and the middle dot inside units.",
        "rule": "A comma inside a run of digits is a thousands separator, not a decimal point.",
    },
    {
        "id": "comparator_elision",
        "label_ko": "비교연산자 생략",
        "what": "Spans whose comparator lives outside the span, in a sibling disjunction or parenthetical.",
        "rule": "The classifier must return the comparator's scope with the span, or stage 3 has nothing to read.",
    },
    {
        "id": "multi_span_lines",
        "label_ko": "한 줄 다중 구문",
        "what": "Source lines that carry more than one threshold.",
        "rule": "Stage 2 output is a list of spans per criterion, never one span per line.",
    },
]

LIMITS: list[dict[str, str]] = [
    {
        "id": "multi_label_spans",
        "what": "One criterion needing two destinations at once -- 'LVEF < 40% measured within 6 months' is a ValueAsNumber and a StartWindow on the same Measurement.",
        "corpus_evidence": "No single corpus entry carries both. The pattern shows only across entries: abs-ml-volume is the quantity half of a blood-donation line and neg-blood-donation-window is the window half of the same construction in another trial.",
        "consequence": "A single-label output silently drops one half. The classifier output must be a list of spans per criterion with independent classes, which this taxonomy allows, but nothing in the corpus validates the co-occurring case.",
    },
    {
        "id": "elided_head_across_bullets",
        "what": "ClinicalTrials.gov nests the analyte in a parent bullet and the threshold in child bullets.",
        "corpus_evidence": "Zero corpus entries. Every entry's source_text is a single line, so the corpus cannot test this at all.",
        "consequence": "The head test has nothing to resolve, the elided-head rule fires, and a lab threshold is classified AGE. This is the taxonomy's largest untested blind spot and it is a corpus construction artefact, not an oversight in the classes.",
    },
    {
        "id": "ranges_need_bt",
        "what": "An inclusive range is a real value constraint that stage 3 cannot emit.",
        "corpus_evidence": "neg-hba1c-range ('6.5 - 8.5%'). Circe does support it: src/agents/agent3/mappings.py maps 'bt' -> 'bt' and '!bt' appears in docs/sample.json, but value_constraint._CIRCE_OPS admits only gt/gte/lt/lte/eq.",
        "consequence": "Classifying ranges as NON_CRITERION permanently drops a real inclusion rule. The correct fix is a stage-3 bt operand, not a taxonomy class.",
    },
    {
        "id": "conditional_thresholds",
        "what": "A threshold that applies only under a stated condition.",
        "corpus_evidence": "uln-two-on-one-line and uln-25-institutional are the two halves of 'ALT <= 2.5 x ULN unless liver metastases are present in which case <= 5x ULN'.",
        "consequence": "The class is right for both spans, but the condition attaching one to the other has nowhere to go. Both thresholds get emitted unconditionally and Circe ANDs them, which is stricter than the protocol.",
    },
    {
        "id": "sex_conditioned_thresholds",
        "what": "One analyte with different thresholds by sex.",
        "corpus_evidence": "abs-gdl-nospace ('<13g/dL for males and <12g/dL for females') and abs-gl-lower ('< 105 g/l in women or < 115 g/l in men'). Only the first half of each is in the corpus.",
        "consequence": "The sex qualifier is not part of the span, so both halves become unconditional thresholds on the same concept set.",
    },
    {
        "id": "carve_out_attachment",
        "what": "An exception clause modifies a threshold it does not contain.",
        "corpus_evidence": "neg-gilbert-carveout is classified NON_CRITERION correctly, but the threshold it modifies (bilirubin <= 1.5 x ULN) is a separate span.",
        "consequence": "The exception is dropped and the threshold applies to patients the protocol exempts.",
    },
    {
        "id": "sibling_context_dependency",
        "what": "unit_conversion_restatement cannot be recognised from the span alone.",
        "corpus_evidence": "neg-unit-conversion ('(>13.3 mmol/L)') is identical in form to abs-mmoll ('<0.8 mmol/L'), a real threshold.",
        "consequence": "If stage 1 splits the criterion, the restatement becomes a second threshold, and Circe ANDs two mutually exclusive filters -> zero patients.",
    },
    {
        "id": "thin_classes",
        "what": "Five classes rest on three or fewer corpus instances: TEMPORAL_WINDOW (3), SCORE_GRADE (3), STATE_DURATION (2), EVENT_QUANTITY (2), DRUG_DOSE (1), REVIEW (1).",
        "corpus_evidence": "Counts are computed from the corpus by this generator.",
        "consequence": "Their boundaries are asserted from the literature and from Circe's shape, not measured. Any accuracy figure quoted per class below n=5 is noise.",
    },
    {
        "id": "age_surface_coverage",
        "what": "Both AGE instances are spelled 'Age <op> N years'.",
        "corpus_evidence": "abs-years-age, abs-years-escaped.",
        "consequence": "'18 years of age or older', 'aged 18-75', 'adult', and the adjectival 'N-year-old' form -- the exact form TIMEX2 and SUTime mis-tag as a duration -- have no corpus instance and are unvalidated.",
    },
    {
        "id": "eq_unvalidated",
        "what": "The eq operator has zero corpus instances.",
        "corpus_evidence": "Computed: no entry maps to eq.",
        "consequence": "Retained in the op table because Circe accepts it, but nothing exercises it. Circe's neq / bt / !bt are likewise absent.",
    },
    {
        "id": "statistical_family_provenance",
        "what": "All 5 statistical_decision_rule instances come from 3 NEJM papers, none from a protocol.",
        "corpus_evidence": "Sources beginning 'paper:'.",
        "consequence": "The family exists because papers were mixed into the corpus. If stage 1 only ever sees ClinicalTrials.gov eligibility text, this family never fires; if it sees publication text, it fires often and is the highest-risk false positive.",
    },
]


def load_entries() -> list[Entry]:
    import yaml

    return yaml.safe_load(CORPUS.read_text())["entries"]


def class_of(entry: Entry) -> str:
    return CLASS_OF.get(entry["id"], DEFAULT_CLASS)


def example_block(entries_by_id: dict[str, Entry], entry_id: str) -> dict[str, Any]:
    entry = entries_by_id[entry_id]
    return {
        "id": entry_id,
        "source": entry["source"],
        "source_text": entry["source_text"],
        "threshold_phrase": entry["threshold_phrase"],
        "kind": entry["expect"]["kind"],
        "op": entry["expect"].get("op"),
        "value": entry["expect"].get("value"),
        "reference_bound": entry["expect"].get("reference_bound"),
        "unit_text": entry["expect"].get("unit_text"),
    }


# Every notation count is a callable so the query that produced it can be printed
# next to the number. (label, query text, function over the entry list).
def notation_variants() -> dict[str, Callable[[list[Entry]], dict[str, Any]]]:
    op_alt = (
        r"(?:=\\<|=\\>|\\<=|\\>=|\\<|\\>|<=|>=|≤|≥|<|>|at or below"
        r"|equal or above|higher than|above|below|at least|more than)"
    )

    def reference_bound(entries: list[Entry]) -> dict[str, Any]:
        bound = [e for e in entries if e["expect"].get("reference_bound") in ("uln", "lln")]
        tails = collections.Counter()
        for entry in bound:
            tail = re.sub(r"^\s*" + op_alt + r"\s*", "", entry["threshold_phrase"], flags=re.I)
            tails[re.sub(r"\d+(?:\.\d+)?", "N", tail)] += 1
        return {
            "count": len(tails),
            "over": len(bound),
            "query": "distinct numeral-abstracted tails of threshold_phrase after the comparator, over entries with reference_bound in (uln, lln)",
            "variants": [{"form": k, "n": v} for k, v in sorted(tails.items(), key=lambda kv: (-kv[1], kv[0]))],
        }

    def implicit_one(entries: list[Entry]) -> dict[str, Any]:
        hits = [e for e in entries if e["expect"].get("value") == 1.0 and not re.search(r"\d", e["threshold_phrase"])]
        explicit = [e for e in entries if e["expect"].get("value") == 1.0 and re.search(r"\d", e["threshold_phrase"])]
        return {
            "count": len(hits),
            "over": len(entries),
            "query": "expect.value == 1.0 and no digit in threshold_phrase",
            "variants": [{"form": e["threshold_phrase"], "n": 1, "id": e["id"]} for e in hits],
            "note": (
                f"{len(explicit)} further entries carry value 1.0 with the digit written "
                f"({', '.join(e['id'] for e in explicit)}); an explicit '1x ULN' must still be a ratio, not an absolute 1."
            ),
        }

    def overloaded_x(entries: list[Entry]) -> dict[str, Any]:
        mul = re.compile(r"(?:\d\s*[x×X]|[x×X]\s*(?:\d|the\b|institutional\b|ULN|LLN|upper|lower))")
        hits = [e for e in entries if mul.search(e["threshold_phrase"])]
        ratio = [e for e in hits if e["expect"].get("reference_bound") in ("uln", "lln")]
        sci = [e for e in hits if e["expect"].get("reference_bound") == "absolute"]
        return {
            "count": len(hits),
            "over": len(entries),
            "query": "threshold_phrase matches an x/×/X token adjacent to a digit or to a bound word, split by expect.reference_bound",
            "variants": [
                {"form": "x = multiple of the reference bound", "n": len(ratio)},
                {"form": "x = times ten to the (scientific notation)", "n": len(sci),
                 "note": ", ".join(e["id"] for e in sci)},
            ],
        }

    def escapes(entries: list[Entry]) -> dict[str, Any]:
        return {
            "count": sum(1 for e in entries if "\\" in e["threshold_phrase"]),
            "over": len(entries),
            "query": "backslash present in threshold_phrase",
            "variants": [
                {"form": "backslash-escaped comparator", "n": sum(1 for e in entries if "\\" in e["threshold_phrase"])},
                {"form": "unicode ≥ / ≤", "n": sum(1 for e in entries if re.search(r"[≥≤]", e["threshold_phrase"]))},
                {"form": "plain ASCII < > <= >=", "n": sum(1 for e in entries if re.search(r"[<>]", e["threshold_phrase"]) and "\\" not in e["threshold_phrase"])},
                {"form": "word form (above/below/at least/...)", "n": sum(1 for e in entries if re.search(r"(?i)\b(above|below|at least|more than|higher than|at or below|equal or above)\b", e["threshold_phrase"]))},
            ],
        }

    def unit_spellings(entries: list[Entry]) -> dict[str, Any]:
        by_concept: dict[int, set[str]] = collections.defaultdict(set)
        for entry in entries:
            unit, concept = entry["expect"].get("unit_text"), entry["expect"].get("unit_concept_id")
            if unit and concept:
                by_concept[concept].add(unit)
        spellings = sum(len(v) for v in by_concept.values())
        return {
            "count": spellings,
            "over": len(by_concept),
            "query": "distinct expect.unit_text values that resolve to a unit_concept_id, grouped by concept",
            "variants": [
                {"form": f"{concept}", "n": len(units), "note": " | ".join(sorted(units))}
                for concept, units in sorted(by_concept.items())
                if len(units) > 1
            ],
            "note": f"{spellings} spellings for {len(by_concept)} UCUM concepts; only the multi-spelling concepts are listed.",
        }

    def unresolvable(entries: list[Entry]) -> dict[str, Any]:
        hits = sorted({
            e["expect"]["unit_text"] for e in entries
            if e["expect"].get("unit_text") and not e["expect"].get("unit_concept_id")
        })
        return {
            "count": len(hits),
            "over": len(entries),
            "query": "expect.unit_text set but expect.unit_concept_id null",
            "variants": [{"form": form, "n": 1} for form in hits],
        }

    def numerals(entries: list[Entry]) -> dict[str, Any]:
        thousands = [e["id"] for e in entries if re.search(r"\d,\d{3}", e["threshold_phrase"])]
        supers = [e["id"] for e in entries if re.search(r"[²¹·]", e["expect"].get("unit_text") or "")]
        micro = [e["id"] for e in entries if re.search(r"[µμ]", e["expect"].get("unit_text") or "")]
        return {
            "count": len(thousands) + len(supers) + len(micro),
            "over": len(entries),
            "query": "thousands separator in threshold_phrase; superscript/middle-dot in unit_text; micro sign vs greek mu in unit_text",
            "variants": [
                {"form": "thousands separator (comma inside digits)", "n": len(thousands), "note": ", ".join(thousands)},
                {"form": "superscript ¹/² or middle dot · in the unit", "n": len(supers), "note": ", ".join(supers)},
                {"form": "U+00B5 micro sign vs U+03BC greek mu", "n": len(micro), "note": ", ".join(micro)},
            ],
        }

    def elision(entries: list[Entry]) -> dict[str, Any]:
        pattern = re.compile(op_alt, re.I)
        hits = [e for e in entries if e["expect"].get("op") and not pattern.search(e["threshold_phrase"])]
        return {
            "count": len(hits),
            "over": sum(1 for e in entries if e["expect"].get("op")),
            "query": "expect.op set but no comparator spelling found anywhere in threshold_phrase",
            "variants": [{"form": e["threshold_phrase"], "n": 1, "id": e["id"], "note": e["expect"]["op"]} for e in hits],
        }

    def multi_span(entries: list[Entry]) -> dict[str, Any]:
        counts = collections.Counter(e["source_text"] for e in entries)
        multi = {k: v for k, v in counts.items() if v > 1}
        return {
            "count": len(multi),
            "over": len(counts),
            "query": "source_text values shared by more than one corpus entry",
            "variants": [{"form": f"{v} spans on one line", "n": sum(1 for x in multi.values() if x == v)}
                         for v in sorted(set(multi.values()), reverse=True)],
            "note": f"{sum(multi.values())} of {len(entries)} spans come from {len(multi)} shared lines; the densest line carries {max(counts.values())}.",
        }

    return {
        "reference_bound": reference_bound,
        "implicit_multiplier_one": implicit_one,
        "overloaded_x": overloaded_x,
        "comparator_escapes": escapes,
        "unit_spellings": unit_spellings,
        "unresolvable_units": unresolvable,
        "numeral_notation": numerals,
        "comparator_elision": elision,
        "multi_span_lines": multi_span,
    }


def build_op_table(entries: list[Entry]) -> list[dict[str, Any]]:
    pattern = re.compile(
        r"(=\\<|=\\>|\\<=|\\>=|\\<|\\>|<=|>=|≤|≥|<|>|at or below|equal or above"
        r"|times higher than|higher than|at least|more than|above|below)",
        re.I,
    )
    seen: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    example: dict[str, str] = {}
    for entry in entries:
        if not entry["expect"].get("op"):
            continue
        match = pattern.search(entry["threshold_phrase"])
        if match is None:
            continue
        surface = match.group(1)
        seen[surface][entry["expect"]["op"]] += 1
        example.setdefault(surface, entry["id"])
    rows = []
    for surface, circe_op, ambiguous, note in OP_SPELLINGS:
        observed = seen.get(surface, collections.Counter())
        if observed and set(observed) != {circe_op}:
            raise ValueError(f"{surface!r} maps to {circe_op} but corpus shows {dict(observed)}")
        rows.append({
            "surface": surface,
            "circe_op": circe_op,
            "corpus_count": observed[circe_op],
            "example_id": example.get(surface),
            "ambiguous": ambiguous,
            "note": note,
        })
    matched = sum(row["corpus_count"] for row in rows)
    total = sum(1 for e in entries if e["expect"].get("op"))
    if matched > total:
        raise ValueError(f"op table over-counts: {matched} > {total}")
    return rows


UNRESOLVED: list[dict[str, str]] = [
    {
        "entry_id": "neg-hba1c-range",
        "class_assigned": "NON_CRITERION / inclusive_range",
        "tension": "By head this is an HbA1c measurement value, so the class dimension says MEASUREMENT_VALUE. The corpus marks it not_a_constraint because a single-threshold parser emits half the range.",
        "disposition": "Follows the corpus. Recorded as a stage-3 capability gap, not a genuine non-criterion: Circe has bt/!bt and value_constraint._CIRCE_OPS simply does not admit them.",
    },
    {
        "entry_id": "neg-prior-lines-count",
        "class_assigned": "NON_CRITERION / spelled_out_count",
        "tension": "It refers to exactly what no-unit-lines-of-therapy refers to (lines of therapy), which is EVENT_QUANTITY. The two entries have the same class and opposite kind; only the digits differ.",
        "disposition": "Follows the corpus. This is the clearest demonstration that kind and class are different axes.",
    },
    {
        "entry_id": "no-unit-inr / uln-inr-ratio",
        "class_assigned": "MEASUREMENT_VALUE (both)",
        "tension": "One threshold_phrase, two readings of the same line: 'INR < 1.5' absolute versus 'INR < 1.5 x ULN'. The class dimension cannot separate them.",
        "disposition": "Kept in one class. The separation belongs to reference_bound, and the corpus pins the precedence: the 'x ULN' suffix wins.",
    },
    {
        "entry_id": "neg-stable-dose-window",
        "class_assigned": "STATE_DURATION",
        "tension": "It carries an explicit anchor ('prior to randomization'), so the router's anchor test would send it to StartWindow, and the router's condition-duration test requires no reference event.",
        "disposition": "Assigned by state-vs-event, not by anchor presence. This is a direct counterexample to rule 4's precondition in the synthesis note.",
    },
    {
        "entry_id": "abs-ml-volume",
        "class_assigned": "EVENT_QUANTITY",
        "tension": "Its source line is 'blood donation/blood loss > 500 mL within ...' -- a quantity and a window on one event. A single label keeps only the quantity.",
        "disposition": "Assigned to the quantity. The window half of the same construction appears separately as neg-blood-donation-window from another trial, which is why the output must be a list of spans.",
    },
    {
        "entry_id": "no-unit-child-pugh",
        "class_assigned": "NON_CRITERION / non_numeric_grade",
        "tension": "It is a real exclusion criterion with no number at all, so 'NON_CRITERION' is literally false about it.",
        "disposition": "Kept, with the class naming_caveat recorded. It is out of scope for a numeric-threshold classifier, not out of scope for the cohort.",
    },
    {
        "entry_id": "uln-two-on-one-line / uln-25-institutional",
        "class_assigned": "MEASUREMENT_VALUE (both)",
        "tension": "The second threshold applies only when liver metastases are present. Both spans classify correctly and the condition binding them is unrepresentable.",
        "disposition": "Both emitted; the conditional is lost. Listed under limits as conditional_thresholds.",
    },
    {
        "entry_id": "abs-gdl-nospace / abs-gl-lower",
        "class_assigned": "MEASUREMENT_VALUE (both)",
        "tension": "Each line states a different threshold per sex and the corpus keeps only one half of each.",
        "disposition": "Classified as plain measurement values; the sex qualifier is outside the span. Listed under limits as sex_conditioned_thresholds.",
    },
]


def build() -> dict[str, Any]:
    entries = load_entries()
    by_id = {e["id"]: e for e in entries}
    assignments = {e["id"]: class_of(e) for e in entries}
    counts = collections.Counter(assignments.values())
    total = len(entries)

    classes = []
    for spec in CLASSES:
        block = {k: v for k, v in spec.items() if k != "example_ids"}
        block["corpus_count"] = counts.get(spec["id"], 0)
        block["corpus_share"] = round(counts.get(spec["id"], 0) / total, 4)
        block["examples"] = [example_block(by_id, i) for i in spec["example_ids"]]
        if spec["id"] == "NON_CRITERION":
            block["families"] = [
                {**family, "corpus_count": len(family["entry_ids"]),
                 "examples": [example_block(by_id, family["entry_ids"][0])]}
                for family in NON_CRITERION_FAMILIES
            ]
        classes.append(block)

    variants = notation_variants()
    notation = []
    for section in NOTATION_SECTIONS:
        notation.append({**section, **variants[section["id"]](entries)})

    return {
        "meta": {
            "artifact": "stage-2 value-threshold classification taxonomy",
            "generated_by": "scripts/build_value_taxonomy.py",
            "corpus": "tests/fixtures/value_constraint_corpus.yaml",
            "corpus_entries": total,
            "corpus_sources": len({e["source"] for e in entries}),
            "pipeline": [
                "1. decompose (LLM): eligibility text -> atomic criteria",
                "2. classify (LLM): criterion -> per-span {class, head, threshold_phrase}  <- this artifact",
                "3. structure (code): span -> (op, value, reference_bound, unit) -> Circe",
            ],
            "why_llm": (
                "Chia classifies by the head -- what the number modifies -- not by the unit. "
                "A regex evaluation of the head rule resolved heads for only 62% of value "
                "constraints because splitting on 'or' destroys lines like 'ALT, AST, or "
                "alkaline phosphatase > 3x ULN'. Head identification is semantic."
            ),
            "prompt_contract": {
                "renderer": "scripts/build_value_taxonomy.py --prompt",
                "invariant": "The prompt is a pure function of this file. Do not hand-edit a prompt alongside it.",
                "sections": [
                    {"id": "task", "source": "meta.pipeline + meta.why_llm"},
                    {"id": "output_schema", "source": "meta.output_schema"},
                    {"id": "classes", "source": "classes[].{id,definition,circe_destination,signals,hazard}"},
                    {"id": "non_criterion_families", "source": "classes[id=NON_CRITERION].families[].{id,what,signals}"},
                    {"id": "operators", "source": "op_table[].{surface,circe_op,ambiguous,note}"},
                    {"id": "notation", "source": "notation[].{label_ko,what,rule}"},
                    {"id": "worked_examples", "source": "classes[].examples[].{threshold_phrase,source_text}"},
                    {"id": "hard_rules", "source": "meta.hard_rules"},
                ],
            },
            "output_schema": {
                "spans": [
                    {
                        "threshold_phrase": "verbatim substring of the criterion",
                        "head": "the noun the number modifies, verbatim, or null when elided",
                        "class": "one of classes[].id",
                        "family": "one of classes[id=NON_CRITERION].families[].id, only when class is NON_CRITERION",
                        "confidence": "high | low",
                    }
                ]
            },
            "hard_rules": [
                "Return a list of spans per criterion, never one span per line. 12 corpus lines carry more than one threshold.",
                "Decide by the head, not by the unit. A time unit does not make a span temporal.",
                "Never default to a class to avoid REVIEW. Every wrong class fails silently as a zero-patient cohort.",
                "Do not normalise, convert or compute. Emit the verbatim phrase; stage 3 owns op, value, bound and unit.",
                "A parenthetical restating a threshold already emitted in another unit is not a second span.",
            ],
        },
        "dimensions": {
            "class": {"purpose": "what the number measures, and hence its Circe destination", "closed": True, "count": len(CLASSES)},
            "op": {"purpose": "comparator spelling -> Circe operator", "closed": True, "count": len(OP_SPELLINGS)},
            "notation": {"purpose": "surface variation stage 3 must absorb", "closed": False, "count": len(NOTATION_SECTIONS)},
        },
        "classes": classes,
        "op_table": build_op_table(entries),
        "notation": notation,
        "assignments": assignments,
        "unresolved": UNRESOLVED,
        "limits": LIMITS,
    }


def render_prompt(taxonomy: dict[str, Any]) -> str:
    """Render the stage-2 classifier prompt from the artifact, so neither can drift."""
    meta = taxonomy["meta"]
    out: list[str] = [
        "You classify numeric thresholds in clinical trial eligibility criteria.",
        "",
        "PIPELINE",
        *(f"  {step}" for step in meta["pipeline"]),
        "",
        meta["why_llm"],
        "",
        "OUTPUT",
        json.dumps(meta["output_schema"], indent=2, ensure_ascii=False),
        "",
        "RULES",
        *(f"  - {rule}" for rule in meta["hard_rules"]),
        "",
        "CLASSES",
    ]
    for block in taxonomy["classes"]:
        out += [
            "",
            f"### {block['id']}  (corpus n={block['corpus_count']})",
            block["definition"],
            f"Circe destination: {block['circe_destination']}",
            "Choose it when:",
            *(f"  + {s}" for s in block["signals"]["positive"]),
            "Do not choose it when:",
            *(f"  - {s}" for s in block["signals"]["negative"]),
            f"Hazard: {block['hazard']}",
        ]
        for family in block.get("families", []):
            out += [
                f"  [{family['id']}] {family['what']}",
                *(f"      + {s}" for s in family["signals"]),
            ]
        for example in block["examples"]:
            out.append(f"  e.g. {example['threshold_phrase']!r}  in  {example['source_text'][:150]!r}")
    out += ["", "COMPARATOR SPELLINGS (stage 3 reads these; you only copy the phrase verbatim)"]
    for row in taxonomy["op_table"]:
        flag = "  [AMBIGUOUS]" if row["ambiguous"] else ""
        out.append(f"  {row['surface']!r:22} -> {row['circe_op']:4} n={row['corpus_count']:<3}{flag} {row['note']}")
    out += ["", "NOTATION"]
    for section in taxonomy["notation"]:
        out.append(f"  {section['id']} (n={section['count']}): {section['what']} -- {section['rule']}")
    return "\n".join(out)


def check(taxonomy: dict[str, Any]) -> None:
    entries = load_entries()
    ids = {e["id"] for e in entries}
    class_ids = {c["id"] for c in CLASSES}

    unknown = set(CLASS_OF) - ids
    assert not unknown, f"CLASS_OF names entries not in the corpus: {sorted(unknown)}"
    bad = {c for c in CLASS_OF.values() if c not in class_ids}
    assert not bad, f"CLASS_OF uses undeclared classes: {sorted(bad)}"

    # Defaulting to MEASUREMENT_VALUE is safe for positives only: a new negative must
    # never acquire a measurement filter by omission.
    negatives = {e["id"] for e in entries if e["expect"]["kind"] == "not_a_constraint"}
    missing = negatives - set(CLASS_OF)
    assert not missing, f"not_a_constraint entries need an explicit class: {sorted(missing)}"

    assert set(taxonomy["assignments"]) == ids, "assignment does not cover the corpus exactly once"
    total = sum(c["corpus_count"] for c in taxonomy["classes"])
    assert total == len(entries), f"class counts sum to {total}, corpus has {len(entries)}"

    non_criterion = next(c for c in taxonomy["classes"] if c["id"] == "NON_CRITERION")
    family_total = sum(f["corpus_count"] for f in non_criterion["families"])
    assert family_total == non_criterion["corpus_count"], (
        f"NON_CRITERION families sum to {family_total}, class has {non_criterion['corpus_count']}"
    )
    family_ids = [i for f in NON_CRITERION_FAMILIES for i in f["entry_ids"]]
    assert len(family_ids) == len(set(family_ids)), "an entry appears in two NON_CRITERION families"

    for block in taxonomy["classes"]:
        assert len(block["examples"]) >= 2 or block["corpus_count"] < 2, (
            f"{block['id']} has {block['corpus_count']} entries but only {len(block['examples'])} example(s)"
        )
    assert render_prompt(taxonomy), "prompt renderer produced nothing"
    print(f"ok: {len(entries)} entries, {len(class_ids)} classes, "
          f"{len(taxonomy['op_table'])} op spellings, {len(taxonomy['notation'])} notation sections")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt", action="store_true", help="render the classifier prompt to stdout")
    parser.add_argument("--check", action="store_true", help="run the coverage self-check only")
    args = parser.parse_args()

    taxonomy = build()
    check(taxonomy)
    if args.prompt:
        print(render_prompt(taxonomy))
        return
    if args.check:
        return
    OUT.write_text(json.dumps(taxonomy, ensure_ascii=False, indent=2) + "\n")
    print("wrote", OUT, f"({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
