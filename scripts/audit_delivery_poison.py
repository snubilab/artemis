#!/usr/bin/env python3
"""Poison check: can each cohort, and each bounded rule in it, match anything at a site?

EVERY CDM THIS SCRIPT READS IS SYNTHETIC. THERE IS NO HOSPITAL DATA ON THIS HOST.
================================================================================
`ajou_cdm`, `donga_cdm` and `keimyung_cdm` are stand-ins built locally by
`scripts/synthesize_site_cdm.py --persons 10000` from the ACHILLES prevalence
snapshots in `data/site_snapshots/*.zip`. The hospitals' real tables have never
been observed by anything in this repo; all they ever sent is a prevalence
snapshot. So **every count this script prints is a fact about a fixture and
nothing else** -- not evidence about the site, and not evidence about the
pipeline. The banner is repeated at the head and foot of the text report and
recorded under `provenance` in the JSON, because a count lifted out of this
output and pasted somewhere else is otherwise indistinguishable from a site fact.

That is not a hypothetical: on 2026-09-13 nine of twelve cohorts measured empty
"at the three hospitals" and "the hospital ETL is missing a step" was reported
before anyone noticed the schemas were ours. See CLAUDE.md, EVERY CDM ON THIS
HOST IS SYNTHETIC.

The four fixture markers below silently zero whole classes of criteria. This
script MEASURES them per CDM at startup and prints the result, so the claim is
observed here rather than taken from a document that may have drifted:

    drug_era / condition_era      0 rows      -> era-anchored criteria match nothing
    range_high                    NULL        -> every "x ULN" RangeHighRatio is dead
    unit_concept_id               0           -> every unit-filtered criterion is dead
    measurement values            synthetic   -> every threshold is uncalibrated

WHY: the delivery is a PIPELINE TEST. Three hospitals run the twelve cohorts and
report patient counts. A rule that matches EVERY row or NO row at a site poisons
that test -- the site reads the empty (or unfiltered) result as "your system does
not work" when in fact one criterion is wrong.

WHAT IS PROVED vs WHAT IS INDICATED
-----------------------------------
Every count below ignores StartWindow, because a window needs an index date, which
needs the cohort generated. So each person count is an UPPER BOUND on what the real
windowed rule matches. Only one direction is therefore a PROOF:

  a PRESENCE criterion (Occurrence AT-LEAST-N) whose unwindowed person count is 0
  can never be satisfied -> provably FALSE for every person -> propagates up
  (ALL-group: any false child => false;  ANY-group: all false children => false)
  -> an InclusionRule that is provably FALSE makes the cohort provably EMPTY.

The other direction (an ABSENCE criterion matching ~everyone) is an INDICATION, not
a proof: the window can only shrink the matched set. It is reported as attrition
pressure with the person fraction, never as proved emptiness.

FIXTURE FIDELITY -- READ THIS BEFORE BELIEVING A THRESHOLD RESULT
-----------------------------------------------------------------
ajou_cdm / donga_cdm / keimyung_cdm are SYNTHESIZED fixtures
(scripts/synthesize_site_cdm.py) built from each site's ACHILLES snapshot. Concept
PREVALENCE is site-faithful. Measurement VALUES and UNITS are not: they come from an
11-row keyword table, and any analyte not matching a keyword falls back to
value ~U(0.1,100) with unit_concept_id = 0. Consequently:

  site-faithful   concept presence/absence at the site  (ACHILLES-derived)
  site-faithful   unit filters on the keyword analytes  (hba1c/bmi/egfr/glucose/
                  aminotransferase/creatinine/hemoglobin/cholesterol/electrolytes)
  NOT faithful    unit filters on every other analyte (fixture writes unit 0)
  NOT faithful    threshold calibration (values are a triangular draw)
  NOT faithful    range_low / range_high  (NULL in all three fixtures, so every
                  RangeHighRatio "x ULN" rule is dead here by construction)
  NOT faithful    drug_era / condition_era (both empty in all three fixtures)

Each flagged finding carries `fidelity`, so a fixture artifact is never reported as
a delivery defect.

Read-only. Issues SELECT statements only.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import psycopg2  # noqa: E402

from src.services.conceptset_closure import (  # noqa: E402
    PostgresVocabulary,
    iter_concept_sets,
    iter_items,
    resolve_concept_set,
)

#: Same home as `scripts/conceptset_overlap_eval.py` -- one env var for the vocabulary
#: DSN across the repo rather than a second private one.
DEFAULT_DSN = os.environ.get(
    "ARTEMIS_VOCAB_DSN", "postgresql://postgres:mypass@localhost:5432/postgres"
)
DEFAULT_CDMS = ["ajou_cdm", "donga_cdm", "keimyung_cdm"]

FIXTURE_BANNER = (
    "!!! EVERY CDM BELOW IS SYNTHETIC -- there is no hospital data on this host.\n"
    "!!! ajou_cdm / donga_cdm / keimyung_cdm are stand-ins built by\n"
    "!!!   scripts/synthesize_site_cdm.py --persons 10000\n"
    "!!! from ACHILLES prevalence snapshots. Concept PREVALENCE is site-faithful;\n"
    "!!! measurement values, most units, range_high and the era tables are NOT.\n"
    "!!! Every count in this report is a fact about a fixture, not about a site."
)

# domain -> (table, concept column, can the table carry a numeric value?)
DOMAINS = {
    "Measurement": ("measurement", "measurement_concept_id", True),
    "Observation": ("observation", "observation_concept_id", True),
    "ConditionOccurrence": ("condition_occurrence", "condition_concept_id", False),
    "ProcedureOccurrence": ("procedure_occurrence", "procedure_concept_id", False),
    "DrugExposure": ("drug_exposure", "drug_concept_id", False),
    "DeviceExposure": ("device_exposure", "device_concept_id", False),
    "VisitOccurrence": ("visit_occurrence", "visit_concept_id", False),
    "ConditionEra": ("condition_era", "condition_concept_id", False),
    "DrugEra": ("drug_era", "drug_concept_id", False),
    "DoseEra": ("dose_era", "drug_concept_id", False),
    "Specimen": ("specimen", "specimen_concept_id", False),
    "Death": ("death", "cause_concept_id", False),
    "ObservationPeriod": (None, None, False),
    "PayerPlanPeriod": (None, None, False),
}
VALUE_KEYS = {"ValueAsNumber", "RangeLow", "RangeHigh", "RangeLowRatio", "RangeHighRatio"}
FILTER_KEYS = VALUE_KEYS | {"Unit", "ValueAsConcept"}
RATIO_KEYS = {"RangeLowRatio", "RangeHighRatio"}

# analytes whose fixture unit is clinically chosen (site-faithful); everything else -> 0
KEYWORD_ANALYTES = (
    "hemoglobin a1c", "hba1c", "body mass index", "glomerular filtration", "ratio",
    "glucose", "aminotransferase", "alkaline phosphatase", "creatinine", "hemoglobin",
    "cholesterol", "triglyceride", "sodium", "potassium", "chloride", "bicarbonate",
)


def num_pred(expr: str, spec: dict) -> str:
    op = str(spec.get("Op", "")).lower()
    if spec.get("Value") is None:
        raise ValueError(f"numeric filter on {expr!r} carries no Value: {spec!r}")
    v = float(spec.get("Value"))
    ex = spec.get("Extent")
    table = {
        "lt": f"{expr} < {v}", "lte": f"{expr} <= {v}",
        "gt": f"{expr} > {v}", "gte": f"{expr} >= {v}",
        "eq": f"{expr} = {v}", "neq": f"{expr} <> {v}", "!eq": f"{expr} <> {v}",
        "bt": f"{expr} BETWEEN {v} AND {float(ex) if ex is not None else v}",
        "!bt": f"{expr} NOT BETWEEN {v} AND {float(ex) if ex is not None else v}",
    }
    if op not in table:
        raise ValueError(
            f"unknown comparison Op {op!r} on {expr!r}; known: {sorted(table)}. "
            f"Refusing to guess -- a wrong predicate would silently mis-measure the rule."
        )
    return table[op]


def occurrence_kind(w: dict) -> str:
    occ = w.get("Occurrence") or {}
    t, c = occ.get("Type"), occ.get("Count")
    if t == 0 and c == 0:
        return "ABSENCE"
    return {0: f"EXACTLY-{c}", 1: f"AT-MOST-{c}", 2: f"AT-LEAST-{c}"}.get(t, f"T{t}C{c}")


class Site:
    """One CDM's answers, memoised per (codeset, predicate)."""

    def __init__(self, cur, cdm, n_persons):
        self.cur, self.cdm, self.n = cur, cdm, n_persons
        self.cache: dict = {}

    def count(self, table, ccol, idlist, where_pred, vp, up):
        key = (table, idlist, where_pred, vp, up)
        if key in self.cache:
            return self.cache[key]
        sql = (
            f"SELECT count(*), count(DISTINCT m.person_id), "
            f"count(*) FILTER (WHERE {where_pred}), "
            f"count(DISTINCT m.person_id) FILTER (WHERE {where_pred}), "
            f"count(*) FILTER (WHERE {vp}), count(*) FILTER (WHERE {up}) "
            f"FROM {self.cdm}.{table} m WHERE m.{ccol} IN ({idlist})"
        )
        self.cur.execute(sql)
        r = self.cur.fetchone()
        self.cache[key] = r
        return r


def evaluate_criterion(w, resolved, sites, records, path):
    """Measure one Criteria wrapper at every site.

    Returns {cdm: 'FALSE'|'UNKNOWN'} -- 'FALSE' only when provable.
    """
    crit = w.get("Criteria") or w
    dom = next(iter(crit))
    body = crit[dom] or {}
    occ = occurrence_kind(w)
    present = sorted(k for k in FILTER_KEYS if k in body and body[k] not in (None, [], {}))
    cs_id = body.get("CodesetId")
    name, cids = resolved.get(cs_id, (None, set()))
    spec = DOMAINS.get(dom, (None, None, False))
    table, ccol, has_val = spec

    rec = {
        "path": path, "domain": dom, "occurrence": occ, "codeset_id": cs_id,
        "codeset_name": name, "n_concepts": len(cids), "filters": present,
        "filter_detail": {k: body[k] for k in present if k not in ("Unit", "ValueAsConcept")},
        "unit_concept_ids": [u.get("CONCEPT_ID") for u in (body.get("Unit") or [])],
        "sites": {},
    }
    verdicts = {}

    if table is None:
        for s in sites:
            verdicts[s.cdm] = "UNKNOWN"
            rec["sites"][s.cdm] = {"verdict": "NOT-MEASURED",
                                   "reason": f"{dom} has no concept-keyed table"}
        records.append(rec)
        return verdicts

    if cs_id is None or not cids:
        for s in sites:
            verdicts[s.cdm] = "FALSE" if occ.startswith("AT-LEAST") else "UNKNOWN"
            rec["sites"][s.cdm] = {"n_rows": 0, "n_pass": 0, "persons_pass": 0,
                                   "person_frac": 0.0, "verdict": "EMPTY-CONCEPT-SET",
                                   "fidelity": "site-faithful"}
        records.append(rec)
        return verdicts

    preds, val_preds, unit_preds = [], [], []
    dropped = []
    for k in present:
        if k in VALUE_KEYS and not has_val:
            dropped.append(k)   # Circe drops a value filter a domain cannot read
            continue
        if k == "ValueAsNumber":
            p = num_pred("m.value_as_number", body[k])
            val_preds.append(p)
        elif k == "RangeLow":
            p = num_pred("m.range_low", body[k])
            val_preds.append(p)
        elif k == "RangeHigh":
            p = num_pred("m.range_high", body[k])
            val_preds.append(p)
        elif k == "RangeLowRatio":
            p = ("m.range_low IS NOT NULL AND m.range_low <> 0 AND "
                 + num_pred("(m.value_as_number / m.range_low)", body[k]))
            val_preds.append(p)
        elif k == "RangeHighRatio":
            p = ("m.range_high IS NOT NULL AND m.range_high <> 0 AND "
                 + num_pred("(m.value_as_number / m.range_high)", body[k]))
            val_preds.append(p)
        elif k == "Unit":
            ids = [int(u["CONCEPT_ID"]) for u in body["Unit"] if u.get("CONCEPT_ID")]
            p = f"m.unit_concept_id IN ({','.join(map(str, ids))})" if ids else "FALSE"
            unit_preds.append(p)
        elif k == "ValueAsConcept":
            ids = [int(u["CONCEPT_ID"]) for u in body["ValueAsConcept"] if u.get("CONCEPT_ID")]
            p = f"m.value_as_concept_id IN ({','.join(map(str, ids))})" if ids else "FALSE"
            unit_preds.append(p)
        else:
            continue
        preds.append(p)
    if dropped:
        rec["circe_drops"] = dropped

    idlist = ",".join(str(c) for c in sorted(cids))
    where_pred = " AND ".join(f"({p})" for p in preds) if preds else "TRUE"
    vp = " AND ".join(f"({p})" for p in val_preds) if val_preds else "TRUE"
    up = " AND ".join(f"({p})" for p in unit_preds) if unit_preds else "TRUE"

    lname = (name or "").lower()
    kw = any(k in lname for k in KEYWORD_ANALYTES)
    if set(present) & RATIO_KEYS:
        fidelity = "FIXTURE-ARTIFACT(range_high NULL in all fixtures)"
    elif not present:
        fidelity = "site-faithful"
    elif set(present) & VALUE_KEYS and not kw:
        fidelity = "FIXTURE-ARTIFACT(non-keyword analyte: synthetic value+unit 0)"
    elif set(present) & VALUE_KEYS:
        fidelity = "partial(keyword analyte: unit site-faithful, threshold synthetic)"
    else:
        fidelity = "partial(unit only)"
    rec["fidelity"] = fidelity

    for s in sites:
        n_rows, p_rows, n_pass, p_pass, n_val, n_unit = s.count(
            table, ccol, idlist, where_pred, vp, up)
        if n_rows == 0:
            verdict = "NO-DATA"
        elif n_pass == 0:
            verdict = "DEAD-BOUND"
        elif preds and n_pass == n_rows:
            verdict = "VACUOUS-BOUND"
        else:
            verdict = "ok"
        cause = None
        if verdict == "DEAD-BOUND":
            if unit_preds and n_unit == 0 and (not val_preds or n_val > 0):
                cause = "unit-absent"
            elif val_preds and n_val == 0 and (not unit_preds or n_unit > 0):
                cause = "threshold-unmet"
            elif unit_preds and val_preds and n_unit == 0 and n_val == 0:
                cause = "unit-absent+threshold-unmet"
            else:
                cause = "combination-unmet"
        # provable falsity: only for presence criteria with zero matching persons
        verdicts[s.cdm] = "FALSE" if (occ.startswith("AT-LEAST") and p_pass == 0) else "UNKNOWN"
        rec["sites"][s.cdm] = {
            "n_rows": n_rows, "n_pass": n_pass, "n_pass_value_only": n_val,
            "n_pass_unit_only": n_unit, "persons_with_concept": p_rows,
            "persons_pass": p_pass, "person_frac": round(p_pass / s.n, 4) if s.n else None,
            "pass_rate_rows": round(n_pass / n_rows, 4) if n_rows else None, "verdict": verdict,
            "dead_cause": cause, "fidelity": fidelity,
        }
    records.append(rec)
    return verdicts


def eval_group(node, resolved, sites, records, path):
    """Three-valued evaluation of a Circe group. Returns {cdm: 'FALSE'|'UNKNOWN'}."""
    gtype = str(node.get("Type", "ALL")).upper()
    child_verdicts = []
    for i, w in enumerate(node.get("CriteriaList") or []):
        # Every child is measured, bounded or not: an unbounded child still carries a
        # verdict that has to propagate for the group's verdict to be sound.
        child_verdicts.append(evaluate_criterion(w, resolved, sites, records, f"{path}/C{i}"))
    for i, g in enumerate(node.get("Groups") or []):
        child_verdicts.append(eval_group(g, resolved, sites, records, f"{path}/G{i}"))
    # DemographicCriteriaList is never provably false here
    out = {}
    for s in sites:
        vs = [cv.get(s.cdm, "UNKNOWN") for cv in child_verdicts]
        if not vs:
            out[s.cdm] = "UNKNOWN"
        elif gtype in ("ALL", "AT_LEAST_ALL"):
            out[s.cdm] = "FALSE" if any(v == "FALSE" for v in vs) else "UNKNOWN"
        elif gtype == "ANY":
            out[s.cdm] = "FALSE" if all(v == "FALSE" for v in vs) else "UNKNOWN"
        else:
            out[s.cdm] = "UNKNOWN"
    return out


def measure_fixture_markers(cur, cdm: str) -> dict:
    """Observe the four markers that make a local CDM a fixture.

    CLAUDE.md asserts these; this measures them, so the report carries evidence
    rather than a quotation from a document that may have drifted.
    """
    def scalar(sql: str):
        try:
            cur.execute(sql)
            return cur.fetchone()[0]
        except psycopg2.Error as exc:            # missing table is itself a marker
            return f"unavailable: {str(exc).splitlines()[0][:80]}"

    return {
        "persons": scalar(f"SELECT count(*) FROM {cdm}.person"),
        "measurements": scalar(f"SELECT count(*) FROM {cdm}.measurement"),
        "drug_era_rows": scalar(f"SELECT count(*) FROM {cdm}.drug_era"),
        "condition_era_rows": scalar(f"SELECT count(*) FROM {cdm}.condition_era"),
        "measurements_with_a_unit": scalar(
            f"SELECT count(*) FROM {cdm}.measurement WHERE unit_concept_id <> 0"
        ),
        "measurements_with_range_high": scalar(
            f"SELECT count(*) FROM {cdm}.measurement WHERE range_high IS NOT NULL"
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", required=True, help="directory of delivered *.circe.json files")
    ap.add_argument("--out", required=True, help="path to write the JSON report to")
    ap.add_argument("--dsn", default=DEFAULT_DSN,
                    help="read-only DSN (default: $ARTEMIS_VOCAB_DSN)")
    ap.add_argument("--cdms", default=",".join(DEFAULT_CDMS),
                    help=f"comma-separated CDM schemas (default: {','.join(DEFAULT_CDMS)})")
    args = ap.parse_args()

    cdms = [c.strip() for c in args.cdms.split(",") if c.strip()]
    files = sorted(p for p in Path(args.dir).glob("*.json") if p.name != "manifest.json")
    if not files:
        raise SystemExit(f"no *.json files under {args.dir} -- nothing to audit")

    conn = psycopg2.connect(args.dsn)
    conn.set_session(readonly=True, autocommit=True)
    cur = conn.cursor()

    print(FIXTURE_BANNER)
    print()
    markers = {c: measure_fixture_markers(cur, c) for c in cdms}
    print("measured fixture markers (observed now, not quoted from a document):")
    hdr = ("persons", "drug_era_rows", "condition_era_rows",
           "measurements", "measurements_with_a_unit", "measurements_with_range_high")
    w = 30
    print(f"  {'schema':<16}" + "".join(f"{h:>{w}}" for h in hdr))
    for c in cdms:
        print(f"  {c:<16}" + "".join(f"{str(markers[c][h]):>{w}}" for h in hdr))

    # Derive the reading from what was measured. An earlier version asserted
    # "0 eras, 0 units, 0 range_high" from CLAUDE.md and was contradicted by the
    # numbers printed directly above it: roughly a fifth of measurements DO carry a
    # unit (the keyword analytes the fixture generator assigns clinically). A tool
    # whose prose disagrees with its own table teaches the reader to skip the prose.
    for c in cdms:
        m = markers[c]
        dead = [k for k in ("drug_era_rows", "condition_era_rows",
                            "measurements_with_range_high") if m.get(k) == 0]
        tot, unit = m.get("measurements"), m.get("measurements_with_a_unit")
        note = []
        if dead:
            note.append("empty: " + ", ".join(k.replace("_rows", "") for k in dead))
        if isinstance(tot, int) and isinstance(unit, int) and tot:
            note.append(f"{unit / tot:.0%} of measurements carry a unit")
        print(f"    {c:<16} {'; '.join(note)}")
    print("  Read those as construction facts about the fixture: a criterion resting on")
    print("  an empty column is dead HERE by construction, not because the delivered")
    print("  definition is wrong. A criterion resting on a populated column is still")
    print("  measured against synthesized values, so its threshold is uncalibrated.")
    print()

    totals = {c: markers[c]["persons"] for c in cdms}
    for c, n in totals.items():
        if not isinstance(n, int):
            raise SystemExit(f"cannot read {c}.person ({n}) -- refusing to report counts")
    sites = [Site(cur, c, totals[c]) for c in cdms]

    report = {
        "provenance": {
            "all_cdms_are_synthetic": True,
            "what_they_are": "local stand-ins from scripts/synthesize_site_cdm.py "
                             "--persons 10000, built from ACHILLES prevalence snapshots "
                             "in data/site_snapshots/*.zip",
            "hospital_data_present": False,
            "how_to_read_a_count": "Every count in this report is a fact about a "
                                   "fixture. It is not evidence about the site and not "
                                   "evidence about the pipeline.",
            "site_faithful": ["concept presence/absence (ACHILLES-derived)"],
            "not_site_faithful": ["measurement values", "units", "range_low/range_high",
                                  "drug_era", "condition_era"],
            "measured_fixture_markers": markers,
            "reference": "CLAUDE.md -- EVERY CDM ON THIS HOST IS SYNTHETIC",
        },
        "cdms": cdms, "person_totals": totals, "dir": str(args.dir), "files": [],
    }

    for fp in files:
        expr = json.loads(fp.read_text())
        with PostgresVocabulary(args.dsn) as voc:
            pre = voc.prefetch([i for cs in iter_concept_sets(expr) for i in iter_items(cs)])
        resolved = {int(cs["id"]): (str(cs.get("name")), resolve_concept_set(cs, pre).concept_ids)
                    for cs in iter_concept_sets(expr)}

        recs: list = []
        # entry
        entry = {"Type": "ALL", "Groups": [],
                 "CriteriaList": expr.get("PrimaryCriteria", {}).get("CriteriaList") or []}
        for w in entry["CriteriaList"]:
            # entry is a presence by definition
            w.setdefault("Occurrence", {"Type": 2, "Count": 1})
        entry_v = eval_group(entry, resolved, sites, recs, "ENTRY")

        rule_v = {}
        for i, r in enumerate(expr.get("InclusionRules") or []):
            rule_v[f"IR{i}:{r.get('name')}"] = eval_group(
                r.get("expression") or {}, resolved, sites, recs, f"IR{i}:{r.get('name')}")

        cohort = {}
        for s in sites:
            reasons = []
            if entry_v.get(s.cdm) == "FALSE":
                reasons.append("ENTRY")
            reasons += [k for k, v in rule_v.items() if v.get(s.cdm) == "FALSE"]
            cohort[s.cdm] = {"provably_empty": bool(reasons), "reasons": reasons}

        report["files"].append({
            "file": fp.name, "entry": entry_v, "rules": rule_v,
            "cohort": cohort, "criteria": recs,
        })

    Path(args.out).write_text(json.dumps(report, indent=1))

    # ---------------- report ----------------
    print("FIXTURE persons per CDM (synthetic stand-ins, not sites): "
          + "  ".join(f"{k}={v}" for k, v in totals.items()))
    print()
    print("=== A. PROVABLY EMPTY COHORTS (a presence criterion no person can satisfy) ===")
    for f in report["files"]:
        line = []
        for c in cdms:
            co = f["cohort"][c]
            line.append(f"{c.split('_')[0]}:{'EMPTY' if co['provably_empty'] else 'non-empty'}")
        print(f"  {f['file']:<34} " + "  ".join(f"{x:<20}" for x in line))
        for c in cdms:
            co = f["cohort"][c]
            if co["provably_empty"]:
                print(f"        {c}: {', '.join(r[:70] for r in co['reasons'])}")
    print()
    print("=== B. BOUNDED RULES: zero-match / every-match ===")
    n_bounded = 0
    flags: list = []
    for f in report["files"]:
        for r in f["criteria"]:
            if not r["filters"]:
                continue
            n_bounded += 1
            vs = {c: r["sites"].get(c, {}).get("verdict") for c in cdms}
            _bad = ("DEAD-BOUND", "VACUOUS-BOUND", "NO-DATA", "EMPTY-CONCEPT-SET")
            if any(v in _bad for v in vs.values()):
                flags.append((f["file"], r))
    print(f"  bounded rules examined: {n_bounded}   flagged: {len(flags)}")
    print()
    for fn, r in flags:
        print(f"  {fn} :: {r['path'][:78]}")
        print(f"     [{r['occurrence']}] cs{r['codeset_id']} "
              f"'{str(r['codeset_name'])[:55]}' nC={r['n_concepts']}"
              f" filters={r['filters']} {r['filter_detail']} unit={r['unit_concept_ids']}")
        print(f"     fidelity: {r.get('fidelity')}")
        for c in cdms:
            s = r["sites"].get(c, {})
            print(f"       {c:<14} {str(s.get('verdict')):<18} "
                  f"rows {s.get('n_pass')}/{s.get('n_rows')}"
                  f"  persons {s.get('persons_pass')}/{totals[c]} frac={s.get('person_frac')}"
                  f"{'  cause=' + s['dead_cause'] if s.get('dead_cause') else ''}")
        print()
    print("=== C. ABSENCE RULES WITH HEAVY ATTRITION PRESSURE (person_frac >= 0.25) ===")
    for f in report["files"]:
        for r in f["criteria"]:
            if r["occurrence"] != "ABSENCE":
                continue
            hot = {c: r["sites"].get(c, {}) for c in cdms
                   if (r["sites"].get(c, {}).get("person_frac") or 0) >= 0.25}
            if hot:
                print(f"  {f['file']} :: {r['path'][:70]} [{r['occurrence']}] "
                      f"cs{r['codeset_id']} '{str(r['codeset_name'])[:40]}' "
                      f"{r['filters']} {r['filter_detail']}")
                print(f"     fidelity: {r.get('fidelity')}")
                for c, s in hot.items():
                    print(f"       {c:<14} {s['verdict']:<16} rows {s['n_pass']}/{s['n_rows']} "
                          f"persons {s['persons_pass']}/{totals[c]} frac={s['person_frac']}")
    print()
    print(FIXTURE_BANNER)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
