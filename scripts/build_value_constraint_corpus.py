"""Build the value-constraint test corpus from cached ClinicalTrials.gov protocols.

Every ``source_text`` is lifted verbatim from ``data/nct_cache/`` rather than
transcribed by hand, so the corpus cannot silently drift from the protocols.
The curation table below supplies only the locator and the expected parse; if a
locator stops matching exactly one criterion line the build fails loudly.

Usage:
    .venv/bin/python scripts/build_value_constraint_corpus.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "nct_cache"
OUT = ROOT / "tests" / "fixtures" / "value_constraint_corpus.yaml"

# Verified against synthea_cdm_benchmark.concept (domain_id='Unit', vocabulary_id='UCUM',
# standard_concept='S') on 2026-07-28. See the header comment emitted into the YAML.
PCT, MGDL, MMOLL, UMOLL, KGM2, MLMIN, EGFR = 8554, 8840, 8753, 8749, 9531, 8795, 720870
MV, NGL, NGML, PGML, GDL, GL, KG, CM, MMHG = 720843, 8725, 8842, 8845, 8713, 8636, 9529, 8582, 8876
YEAR, MONTH, WEEK, DAY, HOUR, MSEC = 9448, 9580, 8511, 8512, 8505, 9593
PERMM3, BILLIONL, UPERL, IUPERML, ML, LITER, MG, RATIO = 8785, 9444, 8645, 8985, 8587, 8519, 8576, 8523

# (entry_id, nct_id, locator, threshold_phrase, expect)
# `locator` must appear in exactly one criterion line of that protocol.
CURATION: list[tuple[str, str, str, str, dict[str, Any]]] = []


def _add(
    entry_id: str,
    nct: str,
    locator: str,
    phrase: str,
    kind: str,
    *,
    op: str | None = None,
    value: float | None = None,
    bound: str | None = None,
    unit_text: str | None = None,
    unit_concept_id: int | None = None,
    note: str | None = None,
) -> None:
    expect: dict[str, Any] = {"kind": kind}
    if kind != "not_a_constraint":
        expect.update(
            {
                "op": op,
                "value": value,
                "reference_bound": bound,
                "unit_text": unit_text,
                "unit_concept_id": unit_concept_id,
            }
        )
    if note:
        expect["note"] = note
    CURATION.append((entry_id, nct, locator, phrase, expect))


U = "uln_multiple"
L = "lln_multiple"
A = "absolute_with_unit"
N = "absolute_no_unit"
X = "absolute_unresolvable_unit"
NOT = "not_a_constraint"

# --------------------------------------------------------------------------
# ULN multiples - one entry per distinct phrasing variant found in the corpus.
# --------------------------------------------------------------------------
_add("uln-x-spaced", "NCT01131676", "above 3 x upper limit of normal (ULN) as determined at screening",
     "above 3 x upper limit of normal (ULN)", U, op="gt", value=3.0, bound="uln")
_add("uln-escaped-gte", "NCT01897532", "alkaline phosphatase (AP) =\\> 3 x upper limit of normal",
     "=\\> 3 x upper limit of normal (ULN)", U, op="gte", value=3.0, bound="uln",
     note="ClinicalTrials.gov escapes comparators as '=\\>' / '\\>' / '\\<'.")
_add("uln-times-sign-nospace", "NCT03526471", "Alkalic Phosphatase \\>2\u00d7 upper limit of normal",
     "\\>2\u00d7 upper limit of normal", U, op="gt", value=2.0, bound="uln")
_add("uln-times-sign-glued", "NCT03576066", "Direct bilirubin \\>1.2\u00d7upper limit of normal (ULN)",
     "\\>1.2\u00d7upper limit of normal (ULN)", U, op="gt", value=1.2, bound="uln",
     note="U+00D7 MULTIPLICATION SIGN with no surrounding whitespace.")
_add("uln-abbrev-glued", "NCT03576066", "Alanine aminotransferase (ALT) \\>5\u00d7ULN at screening",
     "\\>5\u00d7ULN", U, op="gt", value=5.0, bound="uln")
_add("uln-inr-glued", "NCT03577171", "International Normalized Ratio (INR) \\>1.5\u00d7ULN",
     "\\>1.5\u00d7ULN", U, op="gt", value=1.5, bound="uln")
_add("uln-capital-x-nospace", "NCT03674658", "2. Total bilirubin \u2265 2X ULN",
     "\u2265 2X ULN", U, op="gte", value=2.0, bound="uln",
     note="Capital ASCII 'X' as the multiplier, not the letter of a unit.")
_add("uln-capital-x-long", "NCT03674658", "1. AST or ALT \u2265 3X upper limit of normal (ULN)",
     "\u2265 3X upper limit of normal (ULN)", U, op="gte", value=3.0, bound="uln")
_add("uln-lab-ref-range", "NCT03833362", "Serum aspartate aminotransferase (AST) / alanine aminotransferase (ALT) \\>5 x ULN",
     "\\>5 x ULN", U, op="gt", value=5.0, bound="uln")
_add("uln-implicit-one", "NCT03833362", "Serum creatinine \\>ULN of the laboratory reference at Screening;",
     "\\>ULN", U, op="gt", value=1.0, bound="uln",
     note="No multiplier written: the implied comparison is value > 1 x ULN.")
_add("uln-no-multiplier-token", "NCT03833362", "Thyroid stimulating hormone (TSH) \\>1.2 ULN or \\<0.8 LLN;",
     "\\>1.2 ULN", U, op="gt", value=1.2, bound="uln",
     note="Multiplier written with no 'x'/'times' token at all.")
_add("lln-no-multiplier-token", "NCT03833362", "Thyroid stimulating hormone (TSH) \\>1.2 ULN or \\<0.8 LLN;",
     "\\<0.8 LLN", L, op="lt", value=0.8, bound="lln",
     note="Second constraint on the same line; a one-match-per-line parser loses it.")
_add("uln-times-higher-than", "NCT04429646", "AST / ALT is 5 times higher than the upper limit of normal value",
     "5 times higher than the upper limit of normal value", U, op="gt", value=5.0, bound="uln",
     note="'N times higher than' carries the comparator inside the phrase.")
_add("uln-times-the", "NCT04437654", "alanine transaminase \\> 3 times the upper limit of normal",
     "\\> 3 times the upper limit of normal", U, op="gt", value=3.0, bound="uln")
_add("uln-institutional-implicit-one", "NCT04809103", "Total bilirubin \u2264 institutional upper limit of normal (ULN)",
     "\u2264 institutional upper limit of normal (ULN)", U, op="lte", value=1.0, bound="uln",
     note="'institutional' qualifier plus implicit multiplier 1.")
_add("uln-institutional-times-sign", "NCT04809103", "Aspartate aminotransferase /Alanine aminotransferase \u22643 \u00d7 institutional upper limit of normal",
     "\u22643 \u00d7 institutional upper limit of normal", U, op="lte", value=3.0, bound="uln")
_add("uln-abbrev-institutional", "NCT04809103", "Creatinine \u2264 institutional ULN",
     "\u2264 institutional ULN", U, op="lte", value=1.0, bound="uln")
_add("uln-escaped-lte-capital-x", "NCT04826341", "AST(SGOT)/ALT(SGPT) \\<=2.5 X institutional upper limit of normal",
     "\\<=2.5 X institutional upper limit of normal", U, op="lte", value=2.5, bound="uln")
_add("uln-two-on-one-line", "NCT04939662", "in which case it must be \u2264 5x ULN",
     "\u2264 5x ULN", U, op="lte", value=5.0, bound="uln",
     note="Conditional second threshold; the first (2.5 x institutional ULN) is uln-25-institutional.")
_add("uln-25-institutional", "NCT04939662", "in which case it must be \u2264 5x ULN",
     "\u2264 2.5 x institutional upper limit of normal", U, op="lte", value=2.5, bound="uln")
_add("uln-x-the", "NCT04952792", "aspartate aminotransferase (AST)\\> 2x the upper limit of normal",
     "\\> 2x the upper limit of normal", U, op="gt", value=2.0, bound="uln")
_add("uln-bare-value-abbrev", "NCT04952792", "or total bilirubin\\> 1.5 ULN)",
     "\\> 1.5 ULN", U, op="gt", value=1.5, bound="uln")
_add("uln-escaped-lte-institutional", "NCT04954885", "Partial thromboplastin time (PTT) =\\< institutional upper limit of normal (ULN)",
     "=\\< institutional upper limit of normal (ULN)", U, op="lte", value=1.0, bound="uln")
_add("uln-bracketed-analyte", "NCT04954885", "(alanine aminotransferase \\[ALT\\]) \\< 5 X upper limit of normal ULN",
     "\\< 5 X upper limit of normal ULN", U, op="lt", value=5.0, bound="uln")
_add("uln-times-of", "NCT05753280", "2. Alanine transaminase \\>10 times of upper limit of normal(ULN)",
     "\\>10 times of upper limit of normal(ULN)", U, op="gt", value=10.0, bound="uln",
     note="'times of' plus no space before the parenthesised abbreviation.")
_add("uln-times-of-abbrev", "NCT05753280", "2. Alanine transaminase \\>10 times of upper limit of normal(ULN)",
     "\\>2 times of ULN", U, op="gt", value=2.0, bound="uln")
_add("uln-glued-no-separator", "NCT06544551", "For treatment naive patients: ALT \u2264 5ULN at screening.",
     "\u2264 5ULN", U, op="lte", value=5.0, bound="uln",
     note="Number glued straight onto ULN with no multiplier token or space.")
_add("uln-glued-no-separator-2", "NCT06544551", "For NAs treated patients: ALT \u2264 2ULN at screening.",
     "\u2264 2ULN", U, op="lte", value=2.0, bound="uln")
_add("uln-times-the-uln", "NCT06604858", "alanine transaminase (ALT) \u2264 2.5 times ULN.",
     "\u2264 2.5 times ULN", U, op="lte", value=2.5, bound="uln")
_add("uln-times-sign-spaced", "NCT06710990", "Total serum bilirubin \u22641.5\u00d7 the upper limit of normal (ULN);",
     "\u22641.5\u00d7 the upper limit of normal (ULN)", U, op="lte", value=1.5, bound="uln")
_add("uln-equal-or-above", "NCT05419635", "equal or above 4 times the upper limit of normal (ULN)",
     "equal or above 4 times the upper limit of normal (ULN)", U, op="gte", value=4.0, bound="uln",
     note="'equal or above' spells out gte in words.")
_add("uln-above-value", "NCT05419635", "or total bilirubin) above 1.5 x ULN at screening.",
     "above 1.5 x ULN", U, op="gt", value=1.5, bound="uln")
_add("uln-ck-glued", "NCT06544551", "serum creatine kinase (CK) \\>3\u00d7ULN",
     "\\>3\u00d7ULN", U, op="gt", value=3.0, bound="uln")
_add("uln-scr-one-times", "NCT06544551", "serum creatinine (SCr) \\> 1\u00d7ULN.",
     "\\> 1\u00d7ULN", U, op="gt", value=1.0, bound="uln",
     note="Explicit 1x ULN - must still be a ratio, not an absolute 1.")
_add("uln-at-or-below", "NCT06299111", "aPTT values at or below the upper limit of normal as defined by the local lab",
     "at or below the upper limit of normal", U, op="lte", value=1.0, bound="uln")
_add("uln-higher-than-range", "NCT07691203", "Participant with Serum Lactate higher than upper limit of normal range.",
     "higher than upper limit of normal range", U, op="gt", value=1.0, bound="uln")
_add("uln-times-sign-space", "NCT07154901", "1. ALT or AST \\> 1.5 \u00d7 ULN",
     "\\> 1.5 \u00d7 ULN", U, op="gt", value=1.5, bound="uln")
_add("uln-tsh", "NCT07421232", "Thyroid Stimulating Hormone (TSH) \\> 1.5 \u00d7 ULN at Screening Period",
     "\\> 1.5 \u00d7 ULN", U, op="gt", value=1.5, bound="uln")
_add("uln-transaminases", "NCT07671547", "Adequate hepatic function (transaminases \u2264 2.5 \u00d7 upper limit of normal)",
     "\u2264 2.5 \u00d7 upper limit of normal", U, op="lte", value=2.5, bound="uln")
_add("uln-egfr-glued-2", "NCT07163624", "2. Hepatic or renal impairment: ALT and/or AST \u22652.5\u00d7ULN",
     "\u22652.5\u00d7ULN", U, op="gte", value=2.5, bound="uln")
_add("uln-x-lowercase-3x", "NCT07255820", "Acute liver disease or ALT/AST levels \\> 3\u00d7 the upper limit of normal",
     "\\> 3\u00d7 the upper limit of normal", U, op="gt", value=3.0, bound="uln")

# --------------------------------------------------------------------------
# LLN multiples.
# --------------------------------------------------------------------------
_add("lln-implicit-one", "NCT03576066", "Albumin \\<lower limit of normal (LLN)",
     "\\<lower limit of normal (LLN)", L, op="lt", value=1.0, bound="lln",
     note="Implicit multiplier 1 against the low reference bound -> RangeLowRatio.")
_add("lln-spaced", "NCT03833362", "Serum albumin \\< lower limit of normal (LLN) of laboratory reference range",
     "\\< lower limit of normal (LLN)", L, op="lt", value=1.0, bound="lln")
_add("lln-below-the", "NCT04783753", "Platelets, white blood cell count or hemoglobin below the lower limit of normal",
     "below the lower limit of normal", L, op="lt", value=1.0, bound="lln")
_add("lln-below-plain", "NCT05753280", "4. White blood cells or Platelet below the lower limit of normal",
     "below the lower limit of normal", L, op="lt", value=1.0, bound="lln")
_add("lln-hemoglobin", "NCT06544551", "hemoglobin below the lower limit of normal;",
     "below the lower limit of normal", L, op="lt", value=1.0, bound="lln")

# --------------------------------------------------------------------------
# Absolute values with a resolvable unit - one per distinct unit spelling.
# --------------------------------------------------------------------------
_add("abs-pct-hba1c", "NCT01131676", "3. Glycosylated haemoglobin (HbA1c) of \\>= 7.0% and \\<=10%",
     "\\>= 7.0%", A, op="gte", value=7.0, bound="absolute", unit_text="%", unit_concept_id=PCT)
_add("abs-pct-lvef", "NCT00412984", "left ventricular ejection fraction (LVEF) \u2264 40%",
     "\u2264 40%", A, op="lte", value=40.0, bound="absolute", unit_text="%", unit_concept_id=PCT)
_add("abs-kgm2-superscript", "NCT01243424", "4. BMI =\\< 45kg/m\u00b2",
     "=\\< 45kg/m\u00b2", A, op="lte", value=45.0, bound="absolute", unit_text="kg/m\u00b2", unit_concept_id=KGM2,
     note="U+00B2 SUPERSCRIPT TWO, no space before the unit.")
_add("abs-kgm2-plain", "NCT01897532", "6. Body Mass Index (BMI) \\<= 45 kg/m2 at Visit 1 (screening)",
     "\\<= 45 kg/m2", A, op="lte", value=45.0, bound="absolute", unit_text="kg/m2", unit_concept_id=KGM2)
_add("abs-mgdl-lower", "NCT01131676", "a glucose level \\>240 mg/dl (\\>13.3 mmol/L) after an overnight fast",
     "\\>240 mg/dl", A, op="gt", value=240.0, bound="absolute", unit_text="mg/dl", unit_concept_id=MGDL)
_add("abs-mgdl-upper", "NCT03674658", "3. Creatinine \u2265 2.5 mg/dL",
     "\u2265 2.5 mg/dL", A, op="gte", value=2.5, bound="absolute", unit_text="mg/dL", unit_concept_id=MGDL)
_add("abs-mmoll", "NCT06544551", "blood phosphorus \\<0.8 mmol/L;",
     "\\<0.8 mmol/L", A, op="lt", value=0.8, bound="absolute", unit_text="mmol/L", unit_concept_id=MMOLL)
_add("abs-umol-greek-mu", "NCT07472855", "Significant renal insufficiency (creatinine \u22651.5 mg/dL or 133 \u03bcmol/L)",
     "133 \u03bcmol/L", A, op="gte", value=133.0, bound="absolute", unit_text="\u03bcmol/L", unit_concept_id=UMOLL,
     note="U+03BC GREEK SMALL LETTER MU - distinct codepoint from U+00B5 MICRO SIGN below.")
_add("abs-umol-micro-sign", "NCT03833362", "Total bilirubin \\>1.6 mg/dL (\\>27.36 \u00b5mol/L)",
     "\\>27.36 \u00b5mol/L", A, op="gt", value=27.36, bound="absolute", unit_text="\u00b5mol/L", unit_concept_id=UMOLL,
     note="U+00B5 MICRO SIGN. NFKC-normalises to U+03BC; a byte-equality unit table misses one of the two.")
_add("abs-mlmin", "NCT01131676", "Glomerular Filtration Rate \\<30 ml/min (severe renal impairment",
     "\\<30 ml/min", A, op="lt", value=30.0, bound="absolute", unit_text="ml/min", unit_concept_id=MLMIN)
_add("abs-mlmin-upper", "NCT04905316", "Measured creatinine clearance (CL) \\>40 mL/min",
     "\\>40 mL/min", A, op="gt", value=40.0, bound="absolute", unit_text="mL/min", unit_concept_id=MLMIN)
_add("abs-egfr-spaced", "NCT01897532", "Estimated Glomerular filtration Rate (eGFR) \\<15 ml/min/1.73 m2",
     "\\<15 ml/min/1.73 m2", A, op="lt", value=15.0, bound="absolute",
     unit_text="ml/min/1.73 m2", unit_concept_id=EGFR,
     note="Resolves to 720870 'mL/min/(173.10*-2.m2)'. The literal code 'mL/min/{1.73_m2}' does not "
          "exist, and 9117/9062 carry invalid_reason='U' - do not use those.")
_add("abs-egfr-nospace", "NCT06878638", "glomerular filtration rate \\<60 mL/min/1.73m2,",
     "\\<60 mL/min/1.73m2", A, op="lt", value=60.0, bound="absolute",
     unit_text="mL/min/1.73m2", unit_concept_id=EGFR)
_add("abs-egfr-middot-superscript", "NCT07163624", "eGFR \\<60 mL\u00b7min-\u00b9\u00b71.73 m-\u00b2.",
     "\\<60 mL\u00b7min-\u00b9\u00b71.73 m-\u00b2", A, op="lt", value=60.0, bound="absolute",
     unit_text="mL\u00b7min-\u00b9\u00b71.73 m-\u00b2", unit_concept_id=EGFR,
     note="U+00B7 MIDDLE DOT and U+00B9/U+00B2 superscripts spelling the same eGFR unit.")
_add("abs-gdl-upper", "NCT03674658", "4. Hemoglobin \\< 10 g/dL",
     "\\< 10 g/dL", A, op="lt", value=10.0, bound="absolute", unit_text="g/dL", unit_concept_id=GDL)
_add("abs-gdl-nospace", "NCT03833362", "Serum hemoglobin of \\<13g/dL for males and \\<12g/dL for females;",
     "\\<13g/dL", A, op="lt", value=13.0, bound="absolute", unit_text="g/dL", unit_concept_id=GDL)
_add("abs-gl", "NCT06544551", "serum albumin \\<35g/L;",
     "\\<35g/L", A, op="lt", value=35.0, bound="absolute", unit_text="g/L", unit_concept_id=GL)
_add("abs-gl-lower", "NCT07124819", "Hemoglobin \\< 105 g/l in women or \\< 115 g/l in men.",
     "\\< 105 g/l", A, op="lt", value=105.0, bound="absolute", unit_text="g/l", unit_concept_id=GL)
_add("abs-kg", "NCT04905316", "Body weight \\> 30 kg",
     "\\> 30 kg", A, op="gt", value=30.0, bound="absolute", unit_text="kg", unit_concept_id=KG)
_add("abs-mmhg-nospace", "NCT04939662", "systolic blood pressure \\> 150mmHg",
     "\\> 150mmHg", A, op="gt", value=150.0, bound="absolute", unit_text="mmHg", unit_concept_id=MMHG)
_add("abs-mmhg-spaced", "NCT04939662", "diastolic blood pressure \\> 100 mmHg",
     "\\> 100 mmHg", A, op="gt", value=100.0, bound="absolute", unit_text="mmHg", unit_concept_id=MMHG)
_add("abs-permm3-thousands", "NCT03576066", "Platelet count \\<100,000/mm3",
     "\\<100,000/mm3", A, op="lt", value=100000.0, bound="absolute", unit_text="/mm3", unit_concept_id=PERMM3,
     note="Comma is a thousands separator, not a decimal point.")
_add("abs-permm3-plain", "NCT06027957", "Absolute lymphocyte count \u2265 100/mm3 (0.1 G/l)",
     "\u2265 100/mm3", A, op="gte", value=100.0, bound="absolute", unit_text="/mm3", unit_concept_id=PERMM3)
_add("abs-billion-per-l-spaced", "NCT04939662", "Absolute neutrophil count (ANC) \u2265 1.5 x 109/L",
     "\u2265 1.5 x 109/L", A, op="gte", value=1.5, bound="absolute", unit_text="x 10^9/L", unit_concept_id=BILLIONL,
     note="The caret is stripped upstream: '1.5 x 10^9/L' arrives as '1.5 x 109/L'. Reading 109 as the "
          "magnitude would be off by nine orders.")
_add("abs-billion-per-l-glued", "NCT04939662", "White blood cells (WBC) \\> 3x109/L",
     "\\> 3x109/L", A, op="gt", value=3.0, bound="absolute", unit_text="x 10^9/L", unit_concept_id=BILLIONL,
     note="'3x109/L' - the same 'x' token that means 'multiple of' in '3x ULN' here means 'times ten to the'.")
_add("abs-billion-per-l-escaped", "NCT06544551", "White blood cell count \\<3\u00d710\\^9/L;",
     "\\<3\u00d710\\^9/L", A, op="lt", value=3.0, bound="absolute", unit_text="x 10^9/L", unit_concept_id=BILLIONL)
_add("abs-giga-per-l", "NCT06027957", "Absolute neutrophil count (ANC) \u2265 1,000/mm3 (1 G/l) without filgrastim",
     "1 G/l", A, op="gte", value=1.0, bound="absolute", unit_text="G/l", unit_concept_id=BILLIONL,
     note="'G/l' (giga per litre) is the same quantity as 10^9/L.")
_add("abs-ngml", "NCT03577171", "Serum alpha fetoprotein (AFP) \u2265100 ng/mL.",
     "\u2265100 ng/mL", A, op="gte", value=100.0, bound="absolute", unit_text="ng/mL", unit_concept_id=NGML)
_add("abs-pgml", "NCT07527767", "NT-proBNP \u2265 600 pg/mL at Visit 1",
     "\u2265 600 pg/mL", A, op="gte", value=600.0, bound="absolute", unit_text="pg/mL", unit_concept_id=PGML)
_add("abs-pgml-calcitonin", "NCT07163624", "3. Serum calcitonin \u226550 pg/mL.",
     "\u226550 pg/mL", A, op="gte", value=50.0, bound="absolute", unit_text="pg/mL", unit_concept_id=PGML)
_add("abs-iu-per-ml", "NCT03577171", "Hepatitis B surface antigen (HBsAg) \\>1000 IU/mL at screening",
     "\\>1000 IU/mL", A, op="gt", value=1000.0, bound="absolute", unit_text="IU/mL", unit_concept_id=IUPERML)
_add("abs-cm2", "NCT03526471", "3. Significant mitral valve stenosis (i.e. mitral valve area \\<1.5 cm2)",
     "\\<1.5 cm2", X, op="lt", value=1.5, bound="absolute", unit_text="cm2", unit_concept_id=None,
     note="cm2 has no standard UCUM Unit concept in this vocabulary; leave Unit unset rather than "
          "collapsing to cm (8582), which would filter on a different quantity.")
_add("abs-ml-volume", "NCT07154901", "any blood donation/blood loss \\> 500 mL within",
     "\\> 500 mL", A, op="gt", value=500.0, bound="absolute", unit_text="mL", unit_concept_id=ML)
_add("abs-mg-dose", "NCT06027957", "except for \u2264 30 mg prednisolone or equivalent",
     "\u2264 30 mg", A, op="lte", value=30.0, bound="absolute", unit_text="mg", unit_concept_id=MG,
     note="Milligram is 8576. src/agents/agent3/mappings.py maps 'mg' to 8587, which is millilitre.")
_add("abs-msec-qtc", "NCT04939662", "10. Resting ECG with QTc \\> 470msec on 2 or more time points",
     "\\> 470msec", A, op="gt", value=470.0, bound="absolute", unit_text="msec", unit_concept_id=MSEC,
     note="'msec' spelling; the UCUM code is 'ms' (9593).")
_add("abs-years-age", "NCT01131676", "4. Age \\>= 18 years",
     "\\>= 18 years", A, op="gte", value=18.0, bound="absolute", unit_text="years", unit_concept_id=YEAR,
     note="Year is concept 9448 but its concept_code is 'a', not 'year' - a code-keyed lookup misses it.")
_add("abs-years-escaped", "NCT01243424", "OR age =\\> 70 years OR two or more specified cardiovascular risk factor",
     "=\\> 70 years", A, op="gte", value=70.0, bound="absolute", unit_text="years", unit_concept_id=YEAR)
_add("abs-months", "NCT01243424", "20. stroke or Transient Ischemic Attack (TIA) =\\< 3 months prior to ICF",
     "=\\< 3 months", A, op="lte", value=3.0, bound="absolute", unit_text="months", unit_concept_id=MONTH)
_add("abs-weeks", "NCT01897532", "unchanged daily dose) for at least 8 weeks prior to randomization",
     "at least 8 weeks", A, op="gte", value=8.0, bound="absolute", unit_text="weeks", unit_concept_id=WEEK,
     note="'at least' spells out gte.")
_add("abs-hours", "NCT07529600", "or consumption of any such beverages within 48 ho",
     "within 48 hours", A, op="lte", value=48.0, bound="absolute", unit_text="hours", unit_concept_id=HOUR)

# --------------------------------------------------------------------------
# Absolute values with no meaningful unit.
# --------------------------------------------------------------------------
_add("no-unit-inr", "NCT04939662", "the activity of the agent results in an INR \\< 1.5 x ULN",
     "INR \\< 1.5", N, op="lt", value=1.5, bound="absolute", unit_text=None, unit_concept_id=None,
     note="INR is dimensionless. This line ALSO carries 'x ULN' - see uln-inr-ratio for the correct read.")
_add("uln-inr-ratio", "NCT04939662", "the activity of the agent results in an INR \\< 1.5 x ULN",
     "\\< 1.5 x ULN", U, op="lt", value=1.5, bound="uln",
     note="Same phrase as no-unit-inr; the 'x ULN' suffix wins. Kept as a pair to pin the precedence.")
_add("no-unit-child-pugh", "NCT06544551", "Child-Pugh score B/C grade.",
     "Child-Pugh score B/C", NOT,
     note="A graded scale with no numeric threshold at all.")
_add("no-unit-lines-of-therapy", "NCT05321147", "1. Treatment with \\> 8 lines of systemic therapies prior to enrollment.",
     "\\> 8 lines", N, op="gt", value=8.0, bound="absolute", unit_text=None, unit_concept_id=None,
     note="A count of therapy lines - a number with no unit and no measurement concept.")
_add("no-unit-inr-absolute", "NCT04954885", "Prothrombin time (PT)/international normalized ratio (INR) =\\< 1.5 (within 14 days of randomization)",
     "=\\< 1.5", N, op="lte", value=1.5, bound="absolute", unit_text=None, unit_concept_id=None,
     note="INR with no ULN suffix - genuinely dimensionless, unlike uln-inr-ratio.")
_add("no-unit-ecog", "NCT05321147", "7. ECOG performance status ≤ 2;",
     "≤ 2", N, op="lte", value=2.0, bound="absolute", unit_text=None, unit_concept_id=None,
     note="Ordinal performance score. Numeric but unitless; must not acquire a Unit filter.")
_add("no-unit-ecog-gte", "NCT06027957", "ECOG performance status ≥ 3 points at the time of screening",
     "≥ 3 points", N, op="gte", value=3.0, bound="absolute", unit_text=None, unit_concept_id=None,
     note="'points' is a scale word, not a unit.")

# --------------------------------------------------------------------------
# Units that cannot be pinned to a standard UCUM Unit concept.
# --------------------------------------------------------------------------
_add("unresolvable-bpm", "NCT03526471", "16. Resting heart rate \\>110 bpm",
     "\\>110 bpm", X, op="gt", value=110.0, bound="absolute", unit_text="bpm", unit_concept_id=None,
     note="No 'beats per minute' Unit concept exists. '/min' (8541) and '{counts}/min' (8483) are both "
          "plausible and neither is correct; guessing would silently drop every row. Emit ValueAsNumber "
          "with no Unit filter.")
_add("unresolvable-bpm-pulse", "NCT07154901", "supine pulse rate \u2265 100 bpm or \u2264 45 bpm.",
     "\u2265 100 bpm", X, op="gte", value=100.0, bound="absolute", unit_text="bpm", unit_concept_id=None)
_add("unresolvable-dipstick", "NCT04939662", "All subjects with \u2265 2 + protein on dipstick urinalysis at baseline",
     "\u2265 2 + protein on dipstick", X, op="gte", value=2.0, bound="absolute",
     unit_text="+ protein on dipstick", unit_concept_id=None,
     note="Ordinal dipstick grade, not a quantity. No Unit concept can express it.")
_add("unresolvable-cups", "NCT07529600", "more than 8 cups per day, 1 cup = 250 mL",
     "more than 8 cups per day", X, op="gt", value=8.0, bound="absolute",
     unit_text="cups per day", unit_concept_id=None)

# --------------------------------------------------------------------------
# Negatives: threshold-looking numbers that must NOT become value constraints.
# --------------------------------------------------------------------------
_add("neg-hba1c-range", "NCT01243424", "Elevated glycosylated haemoglobin (HbA1c): 6.5 - 8.5%, inclusive",
     "6.5 - 8.5%", NOT,
     note="An inclusive range, not one threshold. A greedy parser emits '>= 6.5' or '<= 8.5' and drops "
          "the other half.")
_add("neg-unit-conversion", "NCT01131676", "a glucose level \\>240 mg/dl (\\>13.3 mmol/L) after an overnight fast",
     "(\\>13.3 mmol/L)", NOT,
     note="A parenthetical restatement of the SAME threshold in other units. Emitting it as a second "
          "criterion ANDs two mutually exclusive filters and returns zero patients.")
_add("neg-cup-definition", "NCT07529600", "more than 8 cups per day, 1 cup = 250 mL",
     "1 cup = 250 mL", NOT,
     note="A definitional equality inside a parenthetical, not an eligibility threshold.")
_add("neg-blood-donation-window", "NCT07691203", "loss of blood 50 ml to 100 ml within 30 days",
     "within 30 days", NOT,
     note="A temporal window, not a value constraint. Belongs in StartWindow.")
_add("neg-hiv-duration", "NCT04826341", "Patients with long-standing (\\>5 years) HIV on antiretroviral therapy",
     "(\\>5 years)", NOT,
     note="Duration of a condition, not a measured value.")
_add("neg-24h-collection", "NCT04939662", "or \\> 1.0 g of protein in a 24-hour urine collection",
     "24-hour urine collection", NOT,
     note="'24-hour' names the collection protocol; only the '> 1.0 g' is a threshold.")
_add("neg-prior-lines-count", "NCT05541328", "received at least three lines of therapy",
     "at least three lines of therapy", NOT,
     note="Spelled-out count with no digits; must not be coerced into a numeric constraint.")
_add("neg-gilbert-carveout", "NCT04905316", "Serum bilirubin \u22641.5 x institutional upper limit of normal (ULN). This will not apply to patients",
     "This will not apply to patients with confirmed Gilbert's syndrome", NOT,
     note="A carve-out clause attached to a real threshold; contains no threshold of its own.")

# --------------------------------------------------------------------------
# Units that reach the IR only through the paper-derived criteria of the six
# original trials, so they never appear in ClinicalTrials.gov eligibility text.
# Verbatim from data/cache/agent1_ir/ (checked-in pipeline output).
# (entry_id, nct_id, locator, threshold_phrase, expect)
# --------------------------------------------------------------------------
IR_SOURCED: list[tuple[str, str, str, str, dict[str, Any]]] = [
    ("abs-mv-st-elevation", "NCT00391872", "ST-segment elevation of at least 0.1 mV",
     "at least 0.1 mV",
     {"kind": A, "op": "gte", "value": 0.1, "reference_bound": "absolute",
      "unit_text": "mV", "unit_concept_id": MV,
      "note": "Millivolt is 720843. Absent from src/agents/agent3/mappings.py UNIT_MAP entirely."}),
    ("abs-ngl-calcitonin", "NCT01179048", "Calcitonin ≥50 ng/L",
     "≥50 ng/L",
     {"kind": A, "op": "gte", "value": 50.0, "reference_bound": "absolute",
      "unit_text": "ng/L", "unit_concept_id": NGL,
      "note": "Same analyte as abs-pgml-calcitonin (50 pg/mL) in different units - 50 ng/L == 50 pg/mL."}),
    ("abs-mlmin-crcl", "NCT00412984", "creatinine clearance < 25 mL/min",
     "< 25 mL/min",
     {"kind": A, "op": "lt", "value": 25.0, "reference_bound": "absolute",
      "unit_text": "mL/min", "unit_concept_id": MLMIN}),
    ("abs-kgm2-superscript-ir", "NCT01243424", "BMI <= 45 kg/m²",
     "<= 45 kg/m²",
     {"kind": A, "op": "lte", "value": 45.0, "reference_bound": "absolute",
      "unit_text": "kg/m²", "unit_concept_id": KGM2,
      "note": "The IR stores both 'kg/m2' and 'kg/m²'; UNIT_MAP has only the ASCII spelling."}),
]

# Paper-sourced statistical negatives (verbatim via pdftotext).
PAPER_NEGATIVES: list[tuple[str, str, str, str, str]] = [
    ("neg-stat-upper-boundary", "paper:NCT01131676/NEJMoa1504720.pdf",
     "the primary outcome was determined if the upper boundary of the two-sided 95.02% confidence "
     "interval was less than 1.3",
     "upper boundary of the two-sided 95.02% confidence interval was less than 1.3",
     "A statistical decision rule. 'upper boundary ... less than 1.3' looks exactly like a lab "
     "threshold and is the highest-risk false positive in the whole corpus."),
    ("neg-stat-margin", "paper:NCT01131676/NEJMoa1504720.pdf",
     "the test of noninferiority for the primary outcome with a margin of 1.3 at a one-sided level of 0.025",
     "margin of 1.3", "A noninferiority margin on a hazard ratio, not an eligibility threshold."),
    ("neg-stat-ci-hr", "paper:NCT01179048/NEJMoa1603827.pdf",
     "with a margin of 1.30 for the upper boundary of the 95% confidence interval of the hazard ratio",
     "1.30 for the upper boundary of the 95% confidence interval",
     "Hazard-ratio bound. 'upper boundary' shares surface form with 'upper limit of normal'."),
    ("neg-stat-alpha", "paper:NCT01730534/NEJMoa1812389.pdf",
     "each at a two-sided alpha level of 0.05",
     "two-sided alpha level of 0.05", "Type I error rate, not a measurement."),
    ("neg-stat-mace-ci", "paper:NCT01730534/NEJMoa1812389.pdf",
     "criterion for noninferiority to placebo with respect to MACE (upper boundary of the 95% "
     "confidence interval [CI], <1.30)",
     "upper boundary of the 95% confidence interval [CI], <1.30",
     "Comparator plus number plus 'upper ... of' - a greedy parser reads it as an exclusion."),
]


def _criterion_lines(text: str) -> list[str]:
    out = []
    for raw in text.replace("\r", "").split("\n"):
        line = raw.strip().lstrip("*-\u2022o ").strip()
        if len(line) > 3:
            out.append(line)
    return out


def _load_lines(nct: str) -> list[str]:
    record = json.loads((CACHE / f"{nct}.json").read_text(encoding="utf-8"))
    text = record["protocolSection"]["eligibilityModule"]["eligibilityCriteria"]
    return _criterion_lines(text)


def _ir_criterion_names(nct: str) -> list[str]:
    """Collect every criterion `name` from the stored Agent-1 IR for one trial."""
    names: list[str] = []
    for path in (ROOT / "data" / "cache" / "agent1_ir").glob(f"{nct}_*.json"):
        blob = json.loads(path.read_text(encoding="utf-8"))

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                if isinstance(node.get("name"), str):
                    names.append(node["name"])
                for child in node.values():
                    walk(child)
            elif isinstance(node, list):
                for child in node:
                    walk(child)

        walk(blob)
    return names


def main() -> None:
    entries: list[str] = []
    errors: list[str] = []
    kinds: dict[str, int] = {}

    for entry_id, nct, locator, phrase, expect in CURATION:
        matches = [line for line in _load_lines(nct) if locator in line]
        if len(matches) != 1:
            errors.append(f"{entry_id}: locator matched {len(matches)} lines in {nct}")
            continue
        source_text = matches[0]
        if phrase not in source_text and expect["kind"] != NOT:
            errors.append(f"{entry_id}: threshold_phrase not a substring of source_text")
            continue
        kinds[expect["kind"]] = kinds.get(expect["kind"], 0) + 1
        entries.append(_emit(entry_id, nct, source_text, phrase, expect))

    for entry_id, nct, locator, phrase, expect in IR_SOURCED:
        matches = [name for name in _ir_criterion_names(nct) if locator in name]
        if len(matches) != 1:
            errors.append(f"{entry_id}: IR locator matched {len(matches)} names for {nct}")
            continue
        kinds[expect["kind"]] = kinds.get(expect["kind"], 0) + 1
        entries.append(_emit(entry_id, f"ir:{nct}", matches[0], phrase, expect))

    for entry_id, source, source_text, phrase, note in PAPER_NEGATIVES:
        kinds[NOT] = kinds.get(NOT, 0) + 1
        entries.append(_emit(entry_id, source, source_text, phrase, {"kind": NOT, "note": note}))

    if errors:
        raise SystemExit("corpus build failed:\n  " + "\n  ".join(errors))

    header = (
        "# Value-constraint parsing corpus.\n"
        "#\n"
        "# GENERATED by scripts/build_value_constraint_corpus.py - do not hand-edit.\n"
        "# Every `source_text` is lifted verbatim from data/nct_cache/ (or the cited paper);\n"
        "# ClinicalTrials.gov escapes comparators as '\\>' '\\<' '=\\>' '=\\<' and those escapes\n"
        "# are preserved deliberately - they are real parser input.\n"
        "#\n"
        "# kinds:\n"
        "#   absolute_with_unit          value + unit that resolves to a standard UCUM Unit concept\n"
        "#   absolute_no_unit            value with no meaningful unit (INR, indices, counts)\n"
        "#   uln_multiple                multiple of the upper limit of normal -> Circe RangeHighRatio\n"
        "#   lln_multiple                multiple of the lower limit of normal -> Circe RangeLowRatio\n"
        "#   absolute_unresolvable_unit  value + unit text with no standard UCUM Unit concept\n"
        "#   not_a_constraint            a threshold-shaped number that must NOT become a constraint\n"
        "#\n"
        "# Unit-resolution policy for absolute_unresolvable_unit: emit ValueAsNumber and leave Unit\n"
        "# UNSET. Do not fall back to a 'nearest' concept - an incorrect Unit filter matches no rows,\n"
        "# which is the same silent-zero failure mode as defect #10, only harder to spot.\n"
        "#\n"
        "# unit_concept_id values were resolved against synthea_cdm_benchmark.concept\n"
        "# (domain_id='Unit', vocabulary_id='UCUM', standard_concept='S') on 2026-07-28.\n"
        "# Three lookups that are easy to get wrong (U/L has no corpus entry - ALT/AST are\n"
        "# reported in U/L but no protocol in the corpus states an absolute U/L threshold):\n"
        "#   mL/min/1.73 m2 -> 720870 (code 'mL/min/(173.10*-2.m2)'). Codes 'mL/min/1.73.m2' (9117)\n"
        "#     and 'mL/min/{1.73}m' (9062) exist but carry invalid_reason='U'.\n"
        "#   U/L            -> 8645   (code '[U]/L'). The literal code 'U/L' is SNOMED 4118000,\n"
        "#     non-standard.\n"
        "#   year           -> 9448   (code 'a'). Looking up by the code 'year' finds nothing.\n"
        "\n"
        "entries:\n"
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(header + "\n".join(entries) + "\n", encoding="utf-8")
    print(f"wrote {OUT} ({sum(kinds.values())} entries)")
    for kind, count in sorted(kinds.items(), key=lambda kv: -kv[1]):
        print(f"  {kind:28} {count}")


def _yaml_str(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return repr(value)
    return json.dumps(value, ensure_ascii=False)


def _emit(entry_id: str, source: str, source_text: str, phrase: str, expect: dict[str, Any]) -> str:
    lines = [
        f"  - id: {entry_id}",
        f"    source: {source}",
        f"    source_text: {_yaml_str(source_text)}",
        f"    threshold_phrase: {_yaml_str(phrase)}",
        "    expect:",
    ]
    for key in ("kind", "op", "value", "reference_bound", "unit_text", "unit_concept_id", "note"):
        if key in expect:
            lines.append(f"      {key}: {_yaml_str(expect[key])}")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
