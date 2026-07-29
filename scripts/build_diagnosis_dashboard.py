#!/usr/bin/env python3
"""Build a self-contained HTML dashboard for the gold-vs-generated Circe diagnosis.

Reads the computed diagnosis.json + comparison.json (numbers stay in sync with the
source) and emits dashboard.html with all data/CSS/JS inlined (no external refs).

Usage: python3 artemis/scripts/build_diagnosis_dashboard.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "output" / "gold_vs_generated"


def build_adaptation_data() -> dict:
    repository = str(OUT.parents[1])
    if repository not in sys.path:
        sys.path.insert(0, repository)
    from src.services.site_cdm_adaptation import (
        compile_site_adaptation,
        load_achilles_snapshot,
    )

    fixture_dir = OUT.parents[1] / "tests" / "fixtures" / "site_adaptation"
    circe = json.loads((fixture_dir / "circe.json").read_text())
    comparator = json.loads((fixture_dir / "comparator_candidates.json").read_text())
    descendants = {
        int(key): {int(value) for value in values}
        for key, values in json.loads(
            (fixture_dir / "vocabulary_map.json").read_text()
        ).items()
    }
    profiles = {
        "hospital_a": "대학병원형",
        "hospital_b": "하위형 코딩",
        "hospital_c": "희소 약물 커버리지",
    }
    concept_names = {
        1127433: "entry drug",
        201826: "Type 2 diabetes",
        3001802: "UACR",
        3044370: "dietary intervention",
        1580747: "DPP-4 inhibitor",
        1597756: "Sulfonylurea",
    }
    sites = []
    items = []
    for site_key, profile in profiles.items():
        snapshot = load_achilles_snapshot(fixture_dir / f"{site_key}.zip")
        report = compile_site_adaptation(
            circe,
            snapshot,
            descendants,
            comparator_artifact=comparator,
        ).model_dump(mode="json", by_alias=True)
        changes = report["proposedChanges"]
        change_map: dict[tuple[str, int], list[str]] = {}
        for change in changes:
            change_map.setdefault(
                (change["path"], change["conceptId"]), []
            ).append(change["action"])
        request_map: dict[str, list[str]] = {}
        for request in report["verificationRequests"]:
            request_map.setdefault(request["path"], []).append(request["reason"])
        grounding = {
            row["candidate"]: row["status"]
            for row in report["comparatorGrounding"]
        }
        exact_zero = sum(
            row["state"] == "exact_concept_zero"
            for row in report["criteriaEvidence"]
        )
        granularity = sum(
            change["action"] == "USE_POPULATED_DESCENDANTS"
            for change in changes
        )
        sites.append(
            {
                "site": site_key,
                "profile": profile,
                "snapshotRows": len(snapshot.counts),
                "changes": len(changes),
                "tier2": len(report["verificationRequests"]),
                "exactZero": exact_zero,
                "granularityChanges": granularity,
                "dpp4": grounding.get("DPP-4 inhibitor", "absent"),
                "sulfonylurea": grounding.get("Sulfonylurea", "absent"),
                "signature": report["inputSignature"][:12],
            }
        )
        for index, evidence in enumerate(report["criteriaEvidence"]):
            concept_id = evidence["conceptId"]
            path = evidence["path"]
            items.append(
                {
                    "id": f"{site_key}-criterion-{index}",
                    "site": site_key,
                    "kind": "criterion",
                    "label": concept_names.get(concept_id, str(concept_id)),
                    "path": path,
                    "role": evidence.get("role", ""),
                    "polarity": evidence.get("polarity", ""),
                    "conceptId": concept_id,
                    "state": evidence["state"],
                    "count": evidence.get("countValue"),
                    "upperBound": evidence.get("upperBound"),
                    "action": " + ".join(change_map.get((path, concept_id), []))
                    or "KEEP",
                    "tier2": ", ".join(request_map.get(path, [])) or "—",
                }
            )
        for index, row in enumerate(report["comparatorGrounding"]):
            concept_id = row["conceptIds"][0]
            upper_bound = next(
                (
                    value.get("upperBound")
                    for value in row["evidence"]
                    if value["state"] == "populated_descendant_upper_bound"
                ),
                None,
            )
            items.append(
                {
                    "id": f"{site_key}-comparator-{index}",
                    "site": site_key,
                    "kind": "comparator",
                    "label": row["candidate"],
                    "path": "Comparator grounding",
                    "role": "comparator",
                    "polarity": "presence",
                    "conceptId": concept_id,
                    "state": row["status"],
                    "count": None,
                    "upperBound": upper_bound,
                    "action": "GROUND" if row["status"] == "populated" else "NO_GROUNDING",
                    "tier2": "—",
                }
            )
    return {
        "sites": sites,
        "items": items,
        "plan": [
            {
                "group": "Foundation contract",
                "what": "ACHILLES ZIP loader and suppression-safe evidence",
                "why": "사이트 원자료 없이도 concept evidence를 같은 계약으로 판정한다.",
                "status": "done",
                "date": "2026-07-27",
                "cost": "implemented",
                "priority": "P0",
                "evidence": "사이트 비교",
                "pane": "adaptation",
            },
            {
                "group": "Foundation contract",
                "what": "A/B/C deterministic simulation",
                "why": "동일 CIRCE가 사이트별로 다른 제안을 내는지 검증한다.",
                "status": "done",
                "date": "2026-07-27",
                "cost": "24 focused tests",
                "priority": "P0",
                "evidence": "실험노트",
                "pane": "lab",
            },
            {
                "group": "Real-site evidence",
                "what": "아주대·계명대 snapshot 수령 및 재컴파일",
                "why": "fixture 결과가 아니라 실제 사이트 feasibility를 확정한다.",
                "status": "waiting",
                "date": "—",
                "cost": "site coordination",
                "priority": "P0",
            },
            {
                "group": "Real-site evidence",
                "what": "사이트 vocabulary descendant map",
                "why": "현장 vocabulary 버전에 맞는 granularity와 comparator grounding을 계산한다.",
                "status": "planned",
                "date": "—",
                "cost": "small",
                "priority": "P0",
            },
            {
                "group": "Tier-2 and review",
                "what": "joint/value/time-window query pack",
                "why": "ACHILLES marginal count로 증명할 수 없는 조건을 현장에서 확인한다.",
                "status": "planned",
                "date": "—",
                "cost": "medium",
                "priority": "P1",
            },
            {
                "group": "Tier-2 and review",
                "what": "API persistence and Atlas HITL review",
                "why": "제안을 자동 적용하지 않고 담당자가 근거와 함께 승인하도록 한다.",
                "status": "planned",
                "date": "—",
                "cost": "large",
                "priority": "P1",
            },
        ],
    }


def main() -> None:
    # diagnosis.json is produced by build_diagnosis_data.py (rows + defects w/ code_cause)
    diag = json.loads((OUT / "diagnosis.json").read_text())
    sim = json.loads((OUT / "simulation.json").read_text()) if (OUT / "simulation.json").exists() else {"rows": []}
    notes_path = OUT.parents[1] / "docs" / "daily_notes" / "tte_dashboard_notes.json"
    notes = json.loads(notes_path.read_text()) if notes_path.exists() else []
    issues_path = OUT.parents[1] / "docs" / "daily_notes" / "tte_issue_log.json"
    issues = json.loads(issues_path.read_text()) if issues_path.exists() else []
    lab_path = OUT.parents[1] / "docs" / "daily_notes" / "tte_lab_notes.json"
    lab = json.loads(lab_path.read_text()) if lab_path.exists() else []
    # Related work is reference material, not a journal — no date, so it gets its own
    # renderer rather than the dated calendar shell the other three share.
    refs_path = OUT.parents[1] / "docs" / "daily_notes" / "tte_related_work.json"
    refs = json.loads(refs_path.read_text()) if refs_path.exists() else []
    adaptation = build_adaptation_data()
    html = TEMPLATE.replace("/*__DATA__*/", json.dumps(diag, ensure_ascii=False))
    html = html.replace("/*__SIMDATA__*/", json.dumps(sim, ensure_ascii=False))
    html = html.replace("/*__NOTES__*/", json.dumps(notes, ensure_ascii=False))
    html = html.replace("/*__ISSUES__*/", json.dumps(issues, ensure_ascii=False))
    html = html.replace("/*__LAB__*/", json.dumps(lab, ensure_ascii=False))
    html = html.replace("/*__REFS__*/", json.dumps(refs, ensure_ascii=False))
    html = html.replace("/*__ADAPT__*/", json.dumps(adaptation, ensure_ascii=False))
    (OUT / "dashboard.html").write_text(html)
    print("wrote", OUT / "dashboard.html", f"({len(html)} bytes)")


TEMPLATE = r"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="TTE cohort defect diagnosis and ADR-030 per-site CDM adaptation evidence dashboard">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>⚕️</text></svg>">
<title>TTE Cohort QA — Diagnosis &amp; Site Adaptation</title>
<style>
:root{
  --bg:#f4f5f7;--surface:#fcfcfb;--surface-2:#eef0f3;--ink:#1a1d21;--ink-2:#4a5058;--ink-3:#767d87;
  --line:#dfe3e8;--line-2:#c9ced6;
  --c-0:#0072B2;--c-1:#E69F00;--c-2:#CC79A7;
  --status:#B8791A;--status-bg:#f6ead5;--status-line:#e6c894;--good:#0E8A5F;--bad:#C0392B;--accent:#0E7490;
  --crit-bg:#fbe9e7;--crit-line:#e6b0a8;
  --mono:ui-monospace,"SF Mono","Cascadia Code",Menlo,monospace;--sans:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
}
:root[data-theme="dark"]{
  --bg:#111315;--surface:#1a1a19;--surface-2:#212427;--ink:#e9ecef;--ink-2:#a7aeb6;--ink-3:#727984;
  --line:#2c3035;--line-2:#3a4046;--c-0:#56B4E9;--c-1:#E69F00;--c-2:#CC79A7;
  --status:#E0A94A;--status-bg:#2a2213;--status-line:#4d3d1c;--good:#3FB98A;--bad:#E4695C;--accent:#3FB3C9;
  --crit-bg:#2b1614;--crit-line:#5a2c26;}
@media(prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --bg:#111315;--surface:#1a1a19;--surface-2:#212427;--ink:#e9ecef;--ink-2:#a7aeb6;--ink-3:#727984;
  --line:#2c3035;--line-2:#3a4046;--c-0:#56B4E9;--c-1:#E69F00;--c-2:#CC79A7;
  --status:#E0A94A;--status-bg:#2a2213;--status-line:#4d3d1c;--good:#3FB98A;--bad:#E4695C;--accent:#3FB3C9;
  --crit-bg:#2b1614;--crit-line:#5a2c26;}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);line-height:1.5;-webkit-font-smoothing:antialiased}
.wrap{max-width:1080px;margin:0 auto;padding:32px 24px 80px}
.num{font-family:var(--mono);font-variant-numeric:tabular-nums}
h1{font-size:26px;font-weight:650;letter-spacing:-.02em;margin:0;text-wrap:balance}
h2{font-size:15px;font-weight:620;letter-spacing:.02em;margin:0 0 2px;text-transform:uppercase}
.eyebrow{font-family:var(--mono);font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:var(--accent);font-weight:600}
.sub{color:var(--ink-2);font-size:14px;margin-top:6px}
header{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;flex-wrap:wrap;margin-bottom:24px}
.toggle{border:1px solid var(--line-2);background:var(--surface);color:var(--ink-2);border-radius:8px;padding:7px 12px;font:inherit;font-size:12px;cursor:pointer}
.toggle:hover{border-color:var(--accent);color:var(--ink)}
.verdict{display:flex;gap:14px;align-items:flex-start;background:var(--crit-bg);border:1px solid var(--crit-line);border-radius:12px;padding:16px 18px;margin-bottom:28px}
.verdict .dot{flex:none;width:10px;height:10px;border-radius:50%;background:var(--bad);margin-top:6px;box-shadow:0 0 0 4px color-mix(in srgb,var(--bad) 22%,transparent)}
.verdict h3{margin:0 0 3px;font-size:15px;font-weight:640}.verdict p{margin:0;font-size:13.5px;color:var(--ink-2);max-width:82ch}
section{margin-bottom:34px}.sec-head{margin-bottom:14px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:18px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}@media(max-width:720px){.grid2{grid-template-columns:1fr}}
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{text-align:right;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th:first-child,td:first-child{text-align:left}
thead th{font-size:10.5px;letter-spacing:.05em;text-transform:uppercase;color:var(--ink-3);font-weight:600}
tbody tr:last-child td{border-bottom:none}
.tag{display:inline-block;font-family:var(--mono);font-size:10.5px;padding:1px 6px;border-radius:5px;font-weight:600}
.refverdict{flex:none;font-family:var(--mono);font-size:10.5px;padding:2px 8px;border-radius:5px;font-weight:700;border:1px solid var(--line-2);color:var(--ink-3)}
.refverdict.ok{background:color-mix(in srgb,var(--good) 14%,transparent);color:var(--good);border-color:color-mix(in srgb,var(--good) 34%,transparent)}
.refverdict.warn{background:var(--status-bg);color:var(--status);border-color:var(--status-line)}
.refverdict.bad{background:color-mix(in srgb,var(--bad) 14%,transparent);color:var(--bad);border-color:color-mix(in srgb,var(--bad) 34%,transparent)}
.refcite{font-size:12px;color:var(--ink-3);margin-top:6px;line-height:1.5}
.refcite a{color:var(--accent);text-decoration:none;border-bottom:1px solid color-mix(in srgb,var(--accent) 34%,transparent)}
.refcite a:hover{border-bottom-color:var(--accent)}
.tag.bad{background:color-mix(in srgb,var(--bad) 16%,transparent);color:var(--bad)}
.tag.ok{background:color-mix(in srgb,var(--good) 16%,transparent);color:var(--good)}
.tag.warn{background:var(--status-bg);color:var(--status);border:1px solid var(--status-line)}
.zero{color:var(--bad);font-weight:700}
.chart-t{font-size:13px;font-weight:600;margin-bottom:1px}.chart-s{font-size:12px;color:var(--ink-3);margin-bottom:10px}
svg{display:block;width:100%;overflow:visible}.axis{font-family:var(--mono);font-size:10px;fill:var(--ink-3)}
.gridline{stroke:var(--line);stroke-width:1}
.defect{border-left:4px solid var(--bad);background:var(--surface);border:1px solid var(--line);border-left:4px solid var(--bad);border-radius:10px;padding:14px 16px;margin-bottom:12px}
.defect h4{margin:0 0 4px;font-size:14.5px}.defect p{margin:6px 0 0;font-size:13px;color:var(--ink-2);max-width:88ch}
.ccause{margin-top:10px;background:var(--surface-2);border:1px solid var(--line);border-radius:8px;padding:11px 13px}
.ccause .lbl{font-family:var(--mono);font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:var(--accent);font-weight:700}
.ccause .where{font-family:var(--mono);font-size:12px;color:var(--ink);margin:2px 0 8px;font-weight:600}
.ccause .mech{font-size:12.5px;color:var(--ink-2);max-width:90ch;margin:0 0 8px}
.ccause .ev{font-size:12px;color:var(--ink-2);border-left:3px solid var(--good);padding-left:9px;margin-top:6px}
.ccause .refs{display:flex;flex-wrap:wrap;gap:5px;margin-top:4px}
.ccause .ref{font-family:var(--mono);font-size:10.5px;background:var(--surface);border:1px solid var(--line);border-radius:5px;padding:2px 7px;color:var(--ink-2)}
.sev{font-family:var(--mono);font-size:10.5px;text-transform:uppercase;letter-spacing:.05em;padding:1px 7px;border-radius:5px;margin-left:8px;font-weight:700}
.sev.critical{background:color-mix(in srgb,var(--bad) 18%,transparent);color:var(--bad)}
.sev.blocker{background:#000;color:#fff}
:root[data-theme="dark"] .sev.blocker,@media(prefers-color-scheme:dark){:root:not([data-theme="light"]) .sev.blocker{background:#fff;color:#000}}
.kv{display:grid;grid-template-columns:120px 1fr;gap:4px 12px;font-size:12.5px;margin-top:4px}
.kv .k{color:var(--ink-3)}.kv .v{color:var(--ink)}
.mono{font-family:var(--mono);font-size:12px}
.arrow{color:var(--ink-3)}
.pill-row{display:flex;flex-wrap:wrap;gap:5px;margin-top:5px}
.pill{font-size:11px;background:var(--surface-2);border:1px solid var(--line);border-radius:20px;padding:2px 9px;color:var(--ink-2)}
.foot{font-size:12px;color:var(--ink-3);margin-top:10px;max-width:90ch}
details summary{cursor:pointer;font-size:12.5px;color:var(--accent);font-weight:600;margin-top:8px}
.legend{display:flex;gap:16px;flex-wrap:wrap;font-size:12.5px;color:var(--ink-2);margin:2px 0 12px}
.legend span{display:flex;align-items:center;gap:7px}.swatch{display:inline-block;width:9px;height:9px;border-radius:2px}
.tip{position:fixed;pointer-events:none;background:var(--surface);border:1px solid var(--line-2);border-radius:8px;padding:8px 10px;font-size:12px;box-shadow:0 6px 20px #0003;opacity:0;transition:opacity .1s;z-index:20}
.tabs{display:flex;gap:2px;border-bottom:1px solid var(--line);margin-bottom:26px}
.tab{background:none;border:none;border-bottom:2px solid transparent;color:var(--ink-3);font:inherit;font-size:14px;font-weight:600;padding:9px 16px;cursor:pointer;margin-bottom:-1px}
.tab:hover{color:var(--ink)}.tab.active{color:var(--ink);border-bottom-color:var(--accent)}
.tab:focus-visible,.toggle:focus-visible,.chip:focus-visible,.sortbtn:focus-visible{outline:3px solid color-mix(in srgb,var(--accent) 38%,transparent);outline-offset:2px}
.tabgroup{display:flex;align-items:stretch;position:relative;margin-right:14px}
.tabgroup::before{content:attr(data-glabel);align-self:center;font-family:var(--mono);font-size:9px;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-3);margin-right:4px}
.tabgroup+.tabgroup{border-left:1px solid var(--line-2);padding-left:14px}
.tabpanel[hidden]{display:none}
.log-inc td.zero,.log-inc .zero{color:var(--bad);font-weight:700}
.framing{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:22px}
.frame-card{padding:15px}.frame-card .frame-k{font-family:var(--mono);font-size:10px;letter-spacing:.09em;text-transform:uppercase;color:var(--accent);font-weight:700}.frame-card p{font-size:13.5px;color:var(--ink-2);margin:6px 0 0}
.tiles{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:22px}
.tile{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:15px}.tile .n{font-family:var(--mono);font-size:25px;font-weight:720;line-height:1.15;font-variant-numeric:tabular-nums}.tile .l{font-size:12px;color:var(--ink-3);margin-top:5px}
.filterbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:0 0 12px}.filterbar input{min-width:220px;flex:1;border:1px solid var(--line-2);border-radius:8px;background:var(--surface);color:var(--ink);font:inherit;padding:8px 10px}.chip{border:1px solid var(--line-2);background:var(--surface);color:var(--ink-2);border-radius:999px;padding:5px 10px;font:inherit;font-size:12px;cursor:pointer}.chip.on{background:var(--accent);border-color:var(--accent);color:#fff}
.scrolltbl{overflow:auto;max-height:min(78vh,1100px)}.sortbtn{border:0;background:none;color:inherit;font:inherit;font-size:inherit;font-weight:inherit;text-transform:inherit;letter-spacing:inherit;cursor:pointer;padding:0}
.state{display:inline-flex;align-items:center;gap:5px;font-family:var(--mono);font-size:10.5px;font-weight:650}.state::before{content:"";width:7px;height:7px;border-radius:50%;background:var(--ink-3)}.state.populated::before{background:var(--good)}.state.zero::before{background:var(--bad)}.state.query::before{background:var(--status)}.state.descendant::before{background:var(--c-0)}
.matrix{display:grid;grid-template-columns:minmax(130px,1fr) repeat(2,minmax(110px,.8fr));gap:1px;background:var(--line);border:1px solid var(--line);border-radius:9px;overflow:hidden}.matrix>*{background:var(--surface);padding:9px 11px;font-size:12px}.matrix .mh{font-family:var(--mono);font-size:10px;text-transform:uppercase;color:var(--ink-3);font-weight:700}
.plan-group td{background:var(--surface-2);color:var(--accent);font-weight:700;text-align:left!important}.plan-status{font-family:var(--mono);font-size:10px;border-radius:999px;padding:2px 7px;background:var(--surface-2);white-space:nowrap}.plan-status.done{color:var(--good)}.plan-status.waiting{color:var(--status)}.plan-status.planned{color:var(--ink-3)}.evidence-link{color:var(--accent);font-weight:650;text-decoration:none}.evidence-link:hover{text-decoration:underline}
@media(max-width:840px){.framing,.tiles{grid-template-columns:1fr 1fr}.tabs{overflow-x:auto}.tabgroup{flex:none}}
@media(max-width:560px){.framing,.tiles{grid-template-columns:1fr}.tabgroup::before{display:none}.tab{padding:9px 11px}.matrix{grid-template-columns:minmax(110px,1fr) repeat(2,minmax(92px,.8fr))}}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{scroll-behavior:auto!important;transition:none!important}}
</style></head><body><div class="wrap">
<header>
  <div><div class="eyebrow">OHDSI · Circe cohort QA</div>
  <h1>TTE Cohort QA — Diagnosis &amp; Site Adaptation</h1>
  <div class="sub">실 병원에서 드러난 코호트 결함과 ADR-030 사이트별 적응 foundation을 한 화면에서 추적합니다.</div></div>
  <button class="toggle" id="themeBtn">Theme</button>
</header>
<nav class="tabs" role="tablist">
  <span class="tabgroup" role="presentation" data-glabel="Results">
    <button class="tab active" id="tab-diagnosis-btn" role="tab" aria-selected="true" aria-controls="tab-diagnosis" data-tab="diagnosis">Diagnosis</button>
    <button class="tab" id="tab-adaptation-btn" role="tab" aria-selected="false" aria-controls="tab-adaptation" data-tab="adaptation">사이트 적응</button>
  </span>
  <span class="tabgroup" role="presentation" data-glabel="Record">
    <button class="tab" id="tab-log-btn" role="tab" aria-selected="false" aria-controls="tab-log" data-tab="log">Issue Log</button>
    <button class="tab" id="tab-notes-btn" role="tab" aria-selected="false" aria-controls="tab-notes" data-tab="notes">Daily Notes</button>
    <button class="tab" id="tab-lab-btn" role="tab" aria-selected="false" aria-controls="tab-lab" data-tab="lab">실험노트</button>
    <button class="tab" id="tab-refs-btn" role="tab" aria-selected="false" aria-controls="tab-refs" data-tab="refs">관련 연구</button>
  </span>
</nav>
<div id="tab-diagnosis" class="tabpanel" role="tabpanel" aria-labelledby="tab-diagnosis-btn">
<div class="verdict"><div class="dot"></div><div>
  <h3>All 6 generated cohorts are invalid. The 0-patient counts are only the most visible symptom.</h3>
  <p id="verdictText"></p></div></div>

<section><div class="sec-head"><h2>Defects &amp; solutions (in general terms)</h2>
  <div class="chart-s" style="margin-top:4px">Plain-language summary of the four defects and how each was resolved, in portable OMOP-cohort terms — no code or file references.</div></div>
  <div class="grid2">
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:baseline;gap:8px">
        <div class="chart-t" style="margin-bottom:0">Defect A · Wrong cohort entry event</div>
        <span class="tag ok">Fixed</span></div>
      <div class="kv" style="margin-top:8px">
        <div class="k">What went wrong</div><div class="v">Cohorts entered patients at a disease diagnosis instead of at study-drug initiation, so the treatment and comparator arms became nearly identical and returned zero or invalid patients.</div>
        <div class="k">Root cause</div><div class="v">A benchmark-only shortcut swapped the drug-based entry event for a disease anchor, and that shortcut was mistakenly applied to real studies.</div>
        <div class="k">Solution</div><div class="v">Keep the drug-anchored, new-user entry event, matching the gold-standard cohort design.</div>
        <div class="k">Status</div><div class="v">Fixed (behind a mode flag).</div>
      </div>
    </div>
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:baseline;gap:8px">
        <div class="chart-t" style="margin-bottom:0">Defect B · Wrong drug concept mapping</div>
        <span class="tag warn">Partial</span></div>
      <div class="kv" style="margin-top:8px">
        <div class="k">What went wrong</div><div class="v">Drug names were mapped to the wrong OMOP concept — for example, a drug mapped to a different drug of the same class, or even to a lab test instead of the medication.</div>
        <div class="k">Root cause</div><div class="v">Mapping relied on semantic/embedding nearest-neighbor search with no exact-name check, so similar-sounding drugs and investigational codes resolved incorrectly.</div>
        <div class="k">Solution</div><div class="v">Match the exact standard RxNorm ingredient by name first, and fall back to search only when no exact match exists; also re-map stale drug concept sets already stored on the cohort.</div>
        <div class="k">Status</div><div class="v">Fixed for named ingredients; investigational codes and combination names still pending.</div>
      </div>
    </div>
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:baseline;gap:8px">
        <div class="chart-t" style="margin-bottom:0">Defect C · Comparator was not the real comparator</div>
        <span class="tag warn">Partial</span></div>
      <div class="kv" style="margin-top:8px">
        <div class="k">What went wrong</div><div class="v">The comparator arm was defined as "patients not on the treatment drug" instead of new users of the actual comparator drug — an internally contradictory, confounded contrast.</div>
        <div class="k">Root cause</div><div class="v">A "target minus treatment" (benchmark-era) design reused the treatment drug plus a drug-absence rule instead of the real comparator.</div>
        <div class="k">Solution</div><div class="v">Build the comparator as a new-user cohort on the real active comparator drug. For placebo-controlled trials (no real-world placebo cohort), recommend a cardiovascular-neutral active comparator, grounded in the literature and confirmed by a human.</div>
        <div class="k">Status</div><div class="v">Active-comparator trials fixed; placebo-trial recommender in progress.</div>
      </div>
    </div>
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:baseline;gap:8px">
        <div class="chart-t" style="margin-bottom:0">Defect D · Infeasible eligibility criteria</div>
        <span class="tag warn">Designed</span></div>
      <div class="kv" style="margin-top:8px">
        <div class="k">What went wrong</div><div class="v">Some inclusion rules required data that real-world databases don't capture (e.g. lifestyle "diet and exercise" records, specific urine lab ratios), so every patient was dropped.</div>
        <div class="k">Root cause</div><div class="v">Every protocol eligibility phrase was turned into a mandatory coded rule with no check that the data actually exists in the target database — faithful extraction, but no feasibility judgment (which human gold-builders applied).</div>
        <div class="k">Solution</div><div class="v">Measure each criterion's real prevalence on the target CDM — a fast precomputed summary (ACHILLES) triages "zero" candidates, then a direct patient count confirms them (precomputed counts suppress small numbers, so they can flag a zero but never prove adequacy). Verdicts are polarity-aware: a <b>required inclusion with no data drops everyone</b> (flag), but a <b>0-match exclusion ("No X") excludes nobody and is kept</b>; a missing index/entry concept is a hard blocker to remap, not a drop. The real 0-patient test runs the inclusion rules <b>together</b> (some collapse only in combination). Flagged rules are proposed to a human to exclude/relax — never auto-changed.</div>
        <div class="k">Status</div><div class="v">Design hardened (adversarially reviewed — ADR-029); empirically validated on Synthea (diet/exercise/UACR = 0%); implementation pending.</div>
      </div>
    </div>
  </div>
  <div class="foot">Note: feasibility (Defect D) is CDM-specific — measured on every target database (Synthea &ne; Ajou &ne; Keimyung). Prevalence lookups reuse precomputed ACHILLES summaries where available (cost scales with the number of concepts, not the number of patients — ~0.2s vs tens of minutes of raw scanning); keeping those summaries current is each site's operational responsibility, and if they are absent the counts are measured directly.</div>
</section>

<section><div class="sec-head"><h2>Overview — 6 cohorts</h2></div>
  <div class="card" style="margin-bottom:16px;overflow-x:auto">
    <table id="ovTbl"><thead></thead><tbody></tbody></table>
    <div class="foot">Patient counts reported by two independent sites running the same generated JSON. "Entry event" is the cohort-index event; "Drug concept" is the concept actually contained in the study-drug ConceptSet.</div>
  </div>
  <div class="grid2">
    <div class="card"><div class="chart-t">Reported patient counts</div><div class="chart-s">Two sites; 4 of 6 cohorts return exactly 0.</div><svg id="barPt" viewBox="0 0 440 240"></svg>
      <div class="legend" id="ptLegend"></div></div>
    <div class="card"><div class="chart-t">Concept overlap with gold (Jaccard)</div><div class="chart-s">Shared concepts / union. 1.0 = identical concept set.</div><svg id="barJac" viewBox="0 0 440 240"></svg></div>
  </div>
</section>

<section><div class="sec-head"><h2>Root-cause defects</h2></div><div id="defects"></div></section>

<section><div class="sec-head"><h2>Defect A fix — simulation (definition level)</h2>
  <div class="chart-s" style="margin-top:4px">What the A fix (disable disease-swap → drug-anchored entry, like gold) does to each study's TREATMENT cohort. No DB run; definition-level prediction across all 9 trials incl. LEADER/PLATO/ARISTOTLE.</div></div>
  <div class="card" style="overflow-x:auto"><table id="simTbl"><thead></thead><tbody></tbody></table>
    <div class="note" id="simNote"></div>
  </div>
</section>

<section><div class="sec-head"><h2>Per-cohort detail</h2></div><div id="detail"></div></section>
</div><!-- /tab-diagnosis -->

<div id="tab-adaptation" class="tabpanel" role="tabpanel" aria-labelledby="tab-adaptation-btn" hidden>
  <div class="verdict"><div class="dot" style="background:var(--status)"></div><div>
    <h3>Foundation은 작동한다. 하지만 세 사이트 결과는 서로 다르고, 아직 실 병원 결과는 아니다.</h3>
    <p>A/B/C fixture는 같은 CIRCE에서 다른 feasibility·granularity·comparator 제안을 생성했다. 모든 결과는 <b>proposed</b> 상태이며 CIRCE를 자동 변경하지 않는다.</p>
  </div></div>

  <section class="framing" data-component="framing">
    <div class="card frame-card"><div class="frame-k">Goal</div><p>사이트 ACHILLES snapshot만으로 안전한 코호트 적응 제안과 확인 요청을 만든다.</p></div>
    <div class="card frame-card"><div class="frame-k">Prior work</div><p>Defect A~D 진단, 문헌 우선 comparator 추천, polarity-aware feasibility 원칙이 이미 마련됐다.</p></div>
    <div class="card frame-card"><div class="frame-k">Gap</div><p>병원별 vocabulary·granularity·데이터 밀도 차이를 같은 CIRCE 정의가 흡수하지 못했다.</p></div>
    <div class="card frame-card"><div class="frame-k">Contribution</div><p>ZIP 계약, suppression-safe evidence, 비변경 제안 compiler와 A/B/C 검증을 제공한다. 실 사이트 유효성은 아직 주장하지 않는다.</p></div>
  </section>

  <div class="tiles" id="adaptTiles"></div>

  <section id="adaptation-sites"><div class="sec-head"><h2>Site-level overview</h2>
    <div class="chart-s">동일한 CIRCE와 vocabulary map을 세 snapshot에 적용한 결과. 색상은 사이트를 고정적으로 나타낸다.</div></div>
    <div class="card scrolltbl" style="margin-bottom:16px"><table id="adaptSiteTbl"><thead></thead><tbody></tbody></table></div>
    <div class="grid2">
      <div class="card"><div class="chart-t">제안 변경 수</div><div class="chart-s">B는 exact-zero와 descendant evidence가 함께 있어 제안이 가장 많다.</div><svg id="adaptChangeChart" viewBox="0 0 440 240"></svg></div>
      <div class="card"><div class="chart-t">Tier-2 확인 요청</div><div class="chart-s">세 fixture가 같은 value/time-window 구조를 써서 요청 수가 동일하다.</div><svg id="adaptTier2Chart" viewBox="0 0 440 240"></svg></div>
    </div>
    <div class="card" style="margin-top:16px"><div class="chart-t">Comparator grounding matrix</div><div class="chart-s">ingredient exact row가 없어도 populated descendant product가 있으면 grounded로 표시한다.</div><div class="matrix" id="adaptMatrix"></div></div>
  </section>

  <section id="adaptation-detail"><div class="sec-head"><h2>Criterion and comparator detail</h2>
    <div class="chart-s">행 단위 evidence와 제안을 검색·필터·정렬한다. descendant 합은 distinct patient 수가 아니라 상한값이다.</div></div>
    <div class="filterbar">
      <input id="adaptSearch" type="search" placeholder="criterion, concept ID, action 검색" aria-label="사이트 적응 상세 검색">
      <div id="adaptSiteChips"></div>
      <div id="adaptStateChips"></div>
    </div>
    <div class="card scrolltbl"><table id="adaptDetailTbl"><thead></thead><tbody></tbody></table></div>
  </section>

  <section><div class="sec-head"><h2>Plan and evidence gaps</h2>
    <div class="chart-s">완료 항목도 남겨 근거를 보존하고, 아직 실행하지 않은 현장·Tier-2 작업을 같은 표에서 보여준다.</div></div>
    <div class="card scrolltbl"><table id="adaptPlanTbl"><thead></thead><tbody></tbody></table></div>
  </section>
</div><!-- /tab-adaptation -->

<div id="tab-log" class="tabpanel" role="tabpanel" aria-labelledby="tab-log-btn" hidden>
  <div class="sec-head" style="margin-bottom:10px">
    <span class="eyebrow">Issue Log</span>
    <h2 style="text-transform:none;font-size:20px;margin:4px 0 0">발견된 문제점 · 조치사항</h2>
    <div class="sub">데이터 기반 이슈 로그 — 각 문제의 <b>기존 output → 새 output</b>. 아래 캘린더에서 날짜(하이라이트)를 클릭하면 그 날만 볼 수 있고, <span class="mono">artemis/docs/daily_notes/tte_issue_log.json</span> 편집 후 리빌드하면 반영됩니다.</div>
  </div>
  <div class="notes-layout">
    <div class="notes-main">
      <div id="issFilter" class="notes-filter" hidden></div>
      <div id="issues"></div>
    </div>
    <aside class="notes-side"><div id="ical" class="notecal"></div></aside>
  </div>
</div><!-- /tab-log -->

<div id="tab-notes" class="tabpanel" role="tabpanel" aria-labelledby="tab-notes-btn" hidden>
  <div class="sec-head" style="margin-bottom:10px">
    <span class="eyebrow">Daily Research Notes</span>
    <h2 style="text-transform:none;font-size:20px;margin:4px 0 0">데일리 연구노트</h2>
    <div class="sub">날짜별 진행 기록. 아래 캘린더에서 노트가 있는 날짜(하이라이트)를 클릭하면 그 날 노트만 볼 수 있습니다. 새 날짜는 <span class="mono">artemis/docs/daily_notes/tte_dashboard_notes.json</span>에 항목을 추가하고 리빌드하면 반영됩니다.</div>
  </div>
  <style>
    .notecal{max-width:344px;margin:0;user-select:none}
    .notecal-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:8px}
    .notecal-title{font-weight:700;font-size:14px}
    .notecal-nav{background:none;border:1px solid var(--line);color:var(--ink-2);border-radius:6px;cursor:pointer;width:28px;height:28px;font:inherit;line-height:1}
    .notecal-nav:hover{color:var(--ink);border-color:var(--accent)}
    .notecal-grid{display:grid;grid-template-columns:repeat(7,1fr);gap:3px}
    .notecal-dow{text-align:center;font-size:10px;color:var(--ink-3);padding:2px 0}
    .notecal-day{text-align:center;font-size:12px;padding:7px 0;border-radius:6px;color:var(--ink-3)}
    .notecal-day.cur{color:var(--ink-2)}
    .notecal-day.has{color:var(--ink);font-weight:800;background:var(--surface-2);cursor:pointer;position:relative}
    .notecal-day.has:hover{background:var(--accent);color:#fff}
    .notecal-day.has::after{content:"";position:absolute;bottom:4px;left:50%;transform:translateX(-50%);width:4px;height:4px;border-radius:50%;background:var(--accent)}
    .notecal-day.has.sel{background:var(--accent);color:#fff}
    .notecal-day.has.sel::after{background:#fff}
    .notes-filter{margin:0 0 12px;font-size:13px;color:var(--ink-2)}
    .notes-filter a{color:var(--accent);cursor:pointer;text-decoration:underline}
    .notes-layout{display:flex;gap:28px;align-items:flex-start;justify-content:space-between}
    .notes-main{flex:1 1 auto;min-width:0;max-width:900px}
    .notes-side{flex:0 0 300px;position:sticky;top:20px}
    .datatable{margin-top:8px}
    .datatable th,.datatable td{text-align:left;white-space:normal}
    .note-details{margin-top:11px;border:1px solid var(--line);border-radius:8px;padding:6px 12px;background:var(--surface-2)}
    .note-details>summary{cursor:pointer;color:var(--accent);font-weight:700;font-size:11px;text-transform:uppercase;letter-spacing:.06em;list-style:none;outline:none}
    .note-details>summary::-webkit-details-marker{display:none}
.note-details>summary::before{content:"▸ ";color:var(--ink-3)}
.note-details[open]>summary::before{content:"▾ "}
    .note-stamp{font-family:var(--mono);font-size:10.5px;color:var(--ink-2);background:var(--surface-2);border-radius:999px;padding:2px 8px;white-space:nowrap}
    .note-key{font-size:14px;font-weight:650;color:var(--ink);border-left:3px solid var(--accent);padding:7px 10px;margin-top:11px;background:color-mix(in srgb,var(--accent) 7%,transparent)}
    /* wide: progressively slide the sticky calendar into the right margin (no hard breakpoint jump) */
    @media(min-width:1200px){.notes-layout{margin-right:min(0px,calc((1080px - 100vw)/2 + 24px))}}
    @media(max-width:1000px){.notes-layout{flex-direction:column-reverse;justify-content:flex-start}.notes-main{max-width:none}.notes-side{flex-basis:auto;width:100%;position:static}}
    #toTop{position:fixed;right:24px;bottom:24px;width:42px;height:42px;border-radius:50%;border:1px solid var(--line-2);background:var(--surface);color:var(--ink);font-size:18px;line-height:1;cursor:pointer;opacity:0;pointer-events:none;transition:opacity .2s;z-index:50;box-shadow:0 2px 10px rgba(0,0,0,.14)}
    #toTop.show{opacity:1;pointer-events:auto}
    #toTop:hover{border-color:var(--accent);color:var(--accent)}
  </style>
  <div class="notes-layout">
    <div class="notes-main">
      <div id="notesFilter" class="notes-filter" hidden></div>
      <div id="notes"></div>
    </div>
    <aside class="notes-side"><div id="cal" class="notecal"></div></aside>
  </div>
  <div class="foot">추가 형식: <span class="mono">{ "date":"YYYY-MM-DD", "title":"...", "sections":[ {"h":"한 일","items":["..."]}, ... ] }</span></div>
</div><!-- /tab-notes -->

<div id="tab-lab" class="tabpanel" role="tabpanel" aria-labelledby="tab-lab-btn" hidden>
  <div class="sec-head" style="margin-bottom:10px">
    <span class="eyebrow">Lab Notebook</span>
    <h2 style="text-transform:none;font-size:20px;margin:4px 0 0">실험노트</h2>
    <div class="sub">그날 수행한 실험을 목적·방법·관찰·결과·결론으로 세부 기록. 아래 캘린더에서 날짜(하이라이트)를 클릭하면 그 날만 볼 수 있고, <span class="mono">artemis/docs/daily_notes/tte_lab_notes.json</span> 편집 후 리빌드하면 반영됩니다.</div>
  </div>
  <div class="notes-layout">
    <div class="notes-main">
      <div id="labFilter" class="notes-filter" hidden></div>
      <div id="lab"></div>
    </div>
    <aside class="notes-side"><div id="lcal" class="notecal"></div></aside>
  </div>
</div><!-- /tab-lab -->

<div id="tab-refs" class="tabpanel" role="tabpanel" aria-labelledby="tab-refs-btn" hidden>
  <div class="sec-head" style="margin-bottom:10px">
    <span class="eyebrow">Related Work</span>
    <h2 style="text-transform:none;font-size:20px;margin:4px 0 0">관련 연구</h2>
    <div class="sub">임계값이 <b>값 조건인지 시간창인지</b> 가르는 문제에 대한 문헌 조사. 인용은 전부 원문을 받아 확인했고, 확인 못 한 부분은 그렇게 적어뒀습니다. <span class="mono">artemis/docs/daily_notes/tte_related_work.json</span> 편집 후 리빌드하면 반영됩니다.</div>
  </div>
  <div id="refs"></div>
</div><!-- /tab-refs -->

</div><div class="tip" id="tip"></div>
<button id="toTop" title="맨 위로" aria-label="맨 위로">↑</button>
<script id="data" type="application/json">/*__DATA__*/</script>
<script id="simdata" type="application/json">/*__SIMDATA__*/</script>
<script id="notesdata" type="application/json">/*__NOTES__*/</script>
<script id="issuesdata" type="application/json">/*__ISSUES__*/</script>
<script id="labdata" type="application/json">/*__LAB__*/</script>
<script id="refsdata" type="application/json">/*__REFS__*/</script>
<script id="adaptdata" type="application/json">/*__ADAPT__*/</script>
<script>
const D=JSON.parse(document.getElementById('data').textContent);
const SIM=JSON.parse(document.getElementById('simdata').textContent);
const NOTES=JSON.parse(document.getElementById('notesdata').textContent);
const ISSUES=JSON.parse(document.getElementById('issuesdata').textContent);
const LAB=JSON.parse(document.getElementById('labdata').textContent);
const REFS=JSON.parse(document.getElementById('refsdata').textContent);
const ADAPT=JSON.parse(document.getElementById('adaptdata').textContent);
const root=document.documentElement;
const tabNames=new Set([...document.querySelectorAll('.tab')].map(t=>t.dataset.tab));
function activateTab(name,updateHash=true){
  if(!tabNames.has(name))name='diagnosis';
  const y=scrollY;
  document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('active',x.dataset.tab===name));
  document.querySelectorAll('.tab').forEach(x=>x.setAttribute('aria-selected',String(x.dataset.tab===name)));
  document.querySelectorAll('.tabpanel').forEach(p=>{p.hidden=(p.id!=='tab-'+name);});
  if(updateHash)history.replaceState(null,'','#'+name);
  scrollTo(0,y);
}
document.querySelectorAll('.tab').forEach(t=>t.addEventListener('click',()=>activateTab(t.dataset.tab)));
document.addEventListener('click',event=>{const link=event.target.closest('[data-pane-link]');if(link){event.preventDefault();activateTab(link.dataset.paneLink);}});
const cssvar=v=>getComputedStyle(root).getPropertyValue(v).trim();
const tip=document.getElementById('tip');
function showTip(h,e){tip.innerHTML=h;tip.style.opacity=1;const p=12;let x=e.clientX+p,y=e.clientY+p;const r=tip.getBoundingClientRect();if(x+r.width>innerWidth)x=e.clientX-r.width-p;if(y+r.height>innerHeight)y=e.clientY-r.height-p;tip.style.left=x+'px';tip.style.top=y+'px';}
const hideTip=()=>tip.style.opacity=0;
const esc=s=>String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const mdN=s=>esc(s??'')
  .replace(/`([^`]+)`/g,'<code>$1</code>')
  .replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>')
  .replace(/\*([^*]+)\*/g,'<em>$1</em>');

document.getElementById('verdictText').textContent=
 "Four independent defects: (A) every cohort enters on Type 2 Diabetes instead of the index drug; (B) the study-drug ConceptSets contain the WRONG drug (linagliptin->sitagliptin, empagliflozin->an unrelated metabolite); (C) each comparator is defined as 'NOT the treatment drug' rather than the real active comparator; (D) uncodeable inclusion rules (EMPA #11 diet/exercise regimen, CARMELINA #9 albuminuria/UACR) drop every patient. Even CAROLINA's non-zero counts are on the wrong drug, so no cohort is usable.";

const adaptSiteColors=['--c-0','--c-1','--c-2'];
const adaptFilters={site:'all',state:'all',query:'',sort:'site',asc:true};
const stateClass=s=>s==='populated'||s==='populated_exact_concept'?'populated':s==='exact_concept_zero'||s==='absent'?'zero':s==='populated_descendant_upper_bound'?'descendant':'query';
const stateLabel=s=>({
  populated_exact_concept:'exact populated',
  exact_concept_zero:'exact zero',
  populated_descendant_upper_bound:'descendant upper bound',
  suppressed_or_absent:'suppressed / absent',
  unknown_vocabulary:'unknown vocabulary',
  populated:'populated',
  absent:'absent',
  site_query_required:'site query required'
}[s]||s);
const stateHtml=s=>`<span class="state ${stateClass(s)}">${esc(stateLabel(s))}</span>`;
function renderAdaptation(){
  const sites=ADAPT.sites||[],items=ADAPT.items||[];
  const totalChanges=sites.reduce((sum,row)=>sum+row.changes,0);
  document.getElementById('adaptTiles').innerHTML=[
    ['3','simulated sites'],['1,212','source ACHILLES rows'],[String(totalChanges),'review proposals'],['0','automatic CIRCE changes']
  ].map(([n,l])=>`<div class="tile"><div class="n">${n}</div><div class="l">${l}</div></div>`).join('');
  document.querySelector('#adaptSiteTbl thead').innerHTML='<tr><th>Site profile</th><th>Snapshot rows</th><th>Proposals</th><th>Tier-2</th><th>Exact zero</th><th>Granularity</th><th>DPP-4i</th><th>SU</th><th>Signature</th></tr>';
  document.querySelector('#adaptSiteTbl tbody').innerHTML=sites.map(row=>`<tr>
    <td><b>${esc(row.site)}</b><br><span style="color:var(--ink-3)">${esc(row.profile)}</span></td>
    <td class="num">${row.snapshotRows}</td><td class="num">${row.changes}</td><td class="num">${row.tier2}</td><td class="num">${row.exactZero}</td>
    <td>${row.granularityChanges?'<span class="tag ok">descendant</span>':'<span style="color:var(--ink-3)">—</span>'}</td>
    <td>${stateHtml(row.dpp4)}</td><td>${stateHtml(row.sulfonylurea)}</td><td class="mono">${esc(row.signature)}</td></tr>`).join('');
  document.getElementById('adaptMatrix').innerHTML=[
    '<div class="mh">Site</div><div class="mh">DPP-4 inhibitor</div><div class="mh">Sulfonylurea</div>',
    ...sites.flatMap(row=>[
      `<div><b>${esc(row.site)}</b></div>`,
      `<div>${stateHtml(row.dpp4)}</div>`,
      `<div>${stateHtml(row.sulfonylurea)}</div>`
    ])
  ].join('');
  const siteNames=['all',...sites.map(row=>row.site)];
  document.getElementById('adaptSiteChips').innerHTML=siteNames.map(site=>`<button class="chip${adaptFilters.site===site?' on':''}" data-adapt-site="${site}">${site==='all'?'모든 사이트':esc(site)}</button>`).join('');
  const states=['all',...new Set(items.map(row=>row.state))];
  document.getElementById('adaptStateChips').innerHTML=states.map(state=>`<button class="chip${adaptFilters.state===state?' on':''}" data-adapt-state="${state}">${state==='all'?'모든 상태':esc(stateLabel(state))}</button>`).join('');
  document.querySelectorAll('[data-adapt-site]').forEach(button=>button.onclick=()=>{adaptFilters.site=button.dataset.adaptSite;renderAdaptation();});
  document.querySelectorAll('[data-adapt-state]').forEach(button=>button.onclick=()=>{adaptFilters.state=button.dataset.adaptState;renderAdaptation();});
  const search=document.getElementById('adaptSearch');
  search.value=adaptFilters.query;
  search.oninput=()=>{adaptFilters.query=search.value.toLowerCase();renderAdaptDetail();};
  renderAdaptDetail();
  renderAdaptPlan();
}
function renderAdaptDetail(){
  const cols=[
    ['site','Site'],['kind','Kind'],['label','Criterion / comparator'],['conceptId','Concept ID'],
    ['state','Evidence state'],['count','Count'],['upperBound','Upper bound'],['action','Proposal'],['tier2','Tier-2']
  ];
  document.querySelector('#adaptDetailTbl thead').innerHTML='<tr>'+cols.map(([key,label])=>`<th><button class="sortbtn" data-adapt-sort="${key}">${label}${adaptFilters.sort===key?(adaptFilters.asc?' ↑':' ↓'):''}</button></th>`).join('')+'</tr>';
  document.querySelectorAll('[data-adapt-sort]').forEach(button=>button.onclick=()=>{
    const key=button.dataset.adaptSort;
    adaptFilters.asc=adaptFilters.sort===key?!adaptFilters.asc:true;
    adaptFilters.sort=key;
    renderAdaptDetail();
  });
  const query=adaptFilters.query;
  const rows=(ADAPT.items||[]).filter(row=>
    (adaptFilters.site==='all'||row.site===adaptFilters.site)&&
    (adaptFilters.state==='all'||row.state===adaptFilters.state)&&
    (!query||Object.values(row).join(' ').toLowerCase().includes(query))
  ).sort((a,b)=>{
    const av=a[adaptFilters.sort]??'',bv=b[adaptFilters.sort]??'';
    const result=typeof av==='number'&&typeof bv==='number'?av-bv:String(av).localeCompare(String(bv));
    return adaptFilters.asc?result:-result;
  });
  document.querySelector('#adaptDetailTbl tbody').innerHTML=rows.map(row=>`<tr>
    <td><b>${esc(row.site)}</b></td><td>${esc(row.kind)}</td><td style="text-align:left"><b>${esc(row.label)}</b><br><span class="mono" style="color:var(--ink-3)">${esc(row.role)} ${esc(row.polarity)}</span></td>
    <td class="num">${row.conceptId}</td><td>${stateHtml(row.state)}</td><td class="num">${row.count??'—'}</td><td class="num">${row.upperBound??'—'}</td>
    <td style="text-align:left"><span class="tag ${/DROP|REMAP|NO_GROUNDING/.test(row.action)?'warn':'ok'}">${esc(row.action)}</span></td><td style="text-align:left">${esc(row.tier2)}</td></tr>`).join('')||'<tr><td colspan="9" style="text-align:center;color:var(--ink-3)">조건에 맞는 evidence가 없습니다.</td></tr>';
}
function renderAdaptPlan(){
  const rows=ADAPT.plan||[];
  document.querySelector('#adaptPlanTbl thead').innerHTML='<tr><th>What</th><th style="text-align:left">Why</th><th>Status / date</th><th>Cost</th><th>Priority</th><th>Evidence</th></tr>';
  let group='';
  document.querySelector('#adaptPlanTbl tbody').innerHTML=rows.map(row=>{
    if(['done','running'].includes(row.status)&&!row.evidence)throw new Error(`plan evidence missing: ${row.what}`);
    const header=row.group!==group?`<tr class="plan-group"><td colspan="6">${esc(row.group)}</td></tr>`:'';
    group=row.group;
    const evidence=row.evidence?`<a class="evidence-link" href="#${row.pane}" data-pane-link="${row.pane}">${esc(row.evidence)}</a>`:'—';
    return header+`<tr><td><b>${esc(row.what)}</b></td><td style="text-align:left">${esc(row.why)}</td><td><span class="plan-status ${row.status}">${esc(row.status)}</span><br><span class="mono">${esc(row.date)}</span></td><td>${esc(row.cost)}</td><td><b>${esc(row.priority)}</b></td><td>${evidence}</td></tr>`;
  }).join('');
}
function drawAdaptBars(id,key,label){
  const rows=ADAPT.sites||[],svg=document.getElementById(id),W=440,H=240,ml=44,mr=14,mt=18,mb=52;
  const hi=Math.max(1,...rows.map(row=>row[key])),gw=(W-ml-mr)/rows.length,y=value=>mt+(H-mt-mb)*(1-value/(hi*1.2));
  let html='';
  for(let tick=0;tick<=4;tick++){const value=hi*tick/4,yy=y(value);html+=`<line class="gridline" x1="${ml}" y1="${yy}" x2="${W-mr}" y2="${yy}"/><text class="axis" x="${ml-7}" y="${yy+3}" text-anchor="end">${value.toFixed(value%1?1:0)}</text>`;}
  rows.forEach((row,index)=>{
    const value=row[key],bw=Math.min(58,gw*.48),x=ml+index*gw+(gw-bw)/2,yy=y(value),color=cssvar(adaptSiteColors[index]);
    html+=`<rect x="${x}" y="${yy}" width="${bw}" height="${H-mb-yy}" rx="5" fill="${color}" data-site="${esc(row.site)}" data-label="${esc(label)}" data-value="${value}"/>`;
    html+=`<text class="axis" x="${x+bw/2}" y="${yy-6}" text-anchor="middle" style="fill:var(--ink);font-weight:700">${value}</text><text class="axis" x="${x+bw/2}" y="${H-mb+20}" text-anchor="middle" style="fill:var(--ink-2)">${esc(row.site.replace('hospital_','site '))}</text>`;
  });
  svg.innerHTML=html;
  svg.querySelectorAll('rect[data-site]').forEach(mark=>{mark.style.cursor='pointer';mark.onmousemove=e=>showTip(`<b>${mark.dataset.site}</b><br>${mark.dataset.label}: <b>${mark.dataset.value}</b>`,e);mark.onmouseleave=hideTip;});
}
renderAdaptation();

/* ---- overview table ---- */
(function(){
  const cols=[['label','Cohort'],['pt','Patients (Ajou / Keimyung)'],['entry','Entry event'],['drug','Study-drug concept'],['killer','Killer rule'],['jac','Jaccard vs gold']];
  const th=document.querySelector('#ovTbl thead');
  th.innerHTML='<tr>'+cols.map((c,i)=>`<th style="${i===0?'text-align:left':i===1?'':'text-align:left'}">${c[1]}</th>`).join('')+'</tr>';
  const body=D.rows.map(r=>{
    const z=(r.patients_ajou===0&&r.patients_keimyung===0);
    const drugBad=/sitagliptin|metabolite/i.test(r.gen_drug_concept);
    return `<tr>
      <td><b>${esc(r.trial)}</b><br><span class="mono" style="color:var(--ink-3)">${r.role}</span></td>
      <td style="text-align:left"><span class="num ${z?'zero':''}">${r.patients_ajou}</span> <span class="arrow">/</span> <span class="num ${z?'zero':''}">${r.patients_keimyung}</span></td>
      <td style="text-align:left"><span class="tag bad">Diabetes</span><br><span class="mono" style="color:var(--ink-3)">gold: DrugEra ${esc(r.gold_drug_expected)}</span></td>
      <td style="text-align:left"><span class="tag ${drugBad?'bad':'ok'}">${esc(r.gen_drug_concept)}</span></td>
      <td style="text-align:left">${r.killer_rule?`<span class="tag warn">${esc(r.killer_rule.split(' ').slice(0,1)[0])}</span> ${esc(r.killer_rule.replace(/^#\d+\s*/,''))}`:'<span style="color:var(--ink-3)">—</span>'}</td>
      <td><span class="num">${r.jaccard.toFixed(2)}</span></td></tr>`;
  }).join('');
  document.querySelector('#ovTbl tbody').innerHTML=body;
})();

/* ---- bar: patient counts (grouped: 2 sites) ---- */
function groupedBar(id,series,valFns,fmt){
  const svg=document.getElementById(id),W=440,H=240,ml=42,mr=12,mt=12,mb=64;
  const labels=D.rows.map(r=>r.trial.replace(' OUTCOME','')+'\n'+r.role.slice(0,4));
  let hi=Math.max(1,...D.rows.flatMap(r=>series.map(s=>valFns[s.i](r))));hi*=1.15;
  const n=D.rows.length,gw=(W-ml-mr)/n,x=i=>ml+i*gw;
  const y=v=>mt+(H-mt-mb)*(1-v/hi);let s='';
  for(let t=0;t<=4;t++){const val=hi*t/4,yy=y(val);s+=`<line class="gridline" x1="${ml}" y1="${yy}" x2="${W-mr}" y2="${yy}"/><text class="axis" x="${ml-6}" y="${yy+3}" text-anchor="end">${fmt(val)}</text>`;}
  D.rows.forEach((r,i)=>{
    const bw=gw*0.30, gap=gw*0.06, x0=x(i)+gw*0.5-(bw+gap/2)*series.length/2;
    series.forEach((se,k)=>{
      const val=valFns[se.i](r),yy=y(val),col=cssvar(se.c),bx=x0+k*(bw+gap);
      const h=Math.max(0.5,(H-mb)-yy);
      s+=`<rect x="${bx}" y="${yy}" width="${bw}" height="${h}" rx="3" fill="${col}" data-l="${esc(r.trial+' '+r.role)}" data-s="${se.label}" data-v="${fmt(val)}"/>`;
      if(val===0)s+=`<text class="axis" x="${bx+bw/2}" y="${(H-mb)-3}" text-anchor="middle" style="fill:var(--bad);font-weight:700">0</text>`;
    });
    labels[i].split('\n').forEach((ln,li)=>{s+=`<text class="axis" x="${x(i)+gw/2}" y="${H-mb+16+li*12}" text-anchor="middle" style="fill:var(--ink-2)">${esc(ln)}</text>`;});
  });
  svg.innerHTML=s;
  svg.querySelectorAll('rect[data-l]').forEach(rc=>{rc.style.cursor='pointer';
    rc.onmousemove=e=>showTip(`<b>${rc.dataset.l}</b><br><span style="color:var(--ink-3)">${rc.dataset.s}</span> <b>${rc.dataset.v}</b>`,e);rc.onmouseleave=hideTip;});
}
/* ---- bar: jaccard single ---- */
function jacBar(){
  const svg=document.getElementById('barJac'),W=440,H=240,ml=42,mr=12,mt=12,mb=64;
  const hi=Math.max(0.12,...D.rows.map(r=>r.jaccard))*1.2;
  const n=D.rows.length,gw=(W-ml-mr)/n,x=i=>ml+i*gw,y=v=>mt+(H-mt-mb)*(1-v/hi);let s='';
  for(let t=0;t<=4;t++){const val=hi*t/4,yy=y(val);s+=`<line class="gridline" x1="${ml}" y1="${yy}" x2="${W-mr}" y2="${yy}"/><text class="axis" x="${ml-6}" y="${yy+3}" text-anchor="end">${val.toFixed(2)}</text>`;}
  D.rows.forEach((r,i)=>{const val=r.jaccard,yy=y(val),bw=gw*0.5,bx=x(i)+gw*0.5-bw/2,col=cssvar('--c-2');
    s+=`<rect x="${bx}" y="${yy}" width="${bw}" height="${(H-mb)-yy}" rx="3" fill="${col}" data-l="${esc(r.trial+' '+r.role)}" data-v="${val.toFixed(3)}"/>`;
    s+=`<text class="axis" x="${bx+bw/2}" y="${yy-4}" text-anchor="middle" style="fill:var(--ink);font-weight:600">${val.toFixed(2)}</text>`;
    (r.trial.replace(' OUTCOME','')+'\n'+r.role.slice(0,4)).split('\n').forEach((ln,li)=>{s+=`<text class="axis" x="${x(i)+gw/2}" y="${H-mb+16+li*12}" text-anchor="middle" style="fill:var(--ink-2)">${esc(ln)}</text>`;});});
  svg.innerHTML=s;
  svg.querySelectorAll('rect[data-l]').forEach(rc=>{rc.style.cursor='pointer';
    rc.onmousemove=e=>showTip(`<b>${rc.dataset.l}</b><br><span style="color:var(--ink-3)">Jaccard</span> <b>${rc.dataset.v}</b>`,e);rc.onmouseleave=hideTip;});
}
document.getElementById('ptLegend').innerHTML=
  `<span><span class="swatch" style="background:var(--c-0)"></span>Ajou (김청수)</span><span><span class="swatch" style="background:var(--c-1)"></span>Keimyung (조재형)</span>`;

/* ---- defects ---- */
document.getElementById('defects').innerHTML=D.defects.map(d=>{
  const cc=d.code_cause;
  const ccHtml=cc?`<div class="ccause">
      <div class="lbl">Code root cause</div>
      <div class="where">${esc(cc.where)}</div>
      <div class="mech">${esc(cc.mechanism)}</div>
      <div class="refs">${(cc.refs||[]).map(r=>`<span class="ref">${esc(r)}</span>`).join('')}</div>
      <div class="ev"><b>Evidence:</b> ${esc(cc.evidence)}</div>
    </div>`:'';
  return `<div class="defect"><h4>Defect ${d.id} · ${esc(d.title)}<span class="sev ${d.severity}">${d.severity}</span>
   <span class="tag" style="margin-left:8px;color:var(--ink-3)">affects: ${esc(d.affects)}</span></h4>
   <p>${esc(d.detail)}</p>${ccHtml}</div>`;}).join('');

/* ---- Defect A fix simulation ---- */
(function(){
  const rows=SIM.rows||[];
  if(!rows.length){document.querySelectorAll('section').forEach(s=>{if(s.querySelector('#simTbl'))s.style.display='none';});return;}
  const th=document.querySelector('#simTbl thead');
  th.innerHTML='<tr><th>Study</th><th style="text-align:left">Entry: current → fixed (gold)</th><th>Rules cur/fix/gold</th><th>Jaccard vs gold</th><th style="text-align:left">Drug concept (B)</th></tr>';
  const body=rows.map(r=>{
    const curBad=r.cur_entry.slice(0,4)!=='Drug';
    const fixOk=r.fixed_entry.slice(0,4)==='Drug';
    const jImp=r.fixed_jaccard>r.cur_jaccard;
    return `<tr>
      <td><b>${esc(r.study)}</b></td>
      <td style="text-align:left">
        <span class="tag ${curBad?'bad':'ok'}">${esc(r.cur_entry.slice(0,9))}</span>
        <span class="arrow">→</span>
        <span class="tag ${fixOk?'ok':'bad'}">${esc(r.fixed_entry.slice(0,7))}</span>
        <span class="mono" style="color:var(--ink-3)">(${esc(r.gold_entry.slice(0,7))})</span></td>
      <td class="num">${r.cur_rules} / ${r.fixed_rules} / ${r.gold_rules}</td>
      <td class="num">${r.cur_jaccard.toFixed(2)} <span class="arrow">→</span> <span style="color:${jImp?'var(--good)':'var(--ink-3)'};font-weight:${jImp?'700':'400'}">${r.fixed_jaccard.toFixed(2)}</span></td>
      <td style="text-align:left"><span class="tag ${r.drug_concept_ok?'ok':'bad'}">${r.drug_concept_ok?'OK':'WRONG'}</span> <span class="mono" style="color:var(--ink-3);font-size:11px">${esc((r.base_drug_concept||'').slice(0,22))}</span></td></tr>`;
  }).join('');
  document.querySelector('#simTbl tbody').innerHTML=body;
  document.getElementById('simNote').innerHTML=
    "<b>Reading the simulation.</b> (1) The A fix restores a <b>DrugEra (drug-anchored) entry for all 9 cohorts</b> — matching gold's paradigm. "+
    "(2) For the CV trials (LEADER/PLATO/ARISTOTLE) the current disease-swap path had <b>stripped every eligibility rule (0)</b>; the fix restores them (→ gold-like rule counts) and raises Jaccard. "+
    "(3) For the diabetes trials (CAROLINA/CARMELINA/EMPA) the entry is fixed but <b>Jaccard is flat</b> — that residual gap is driven by Defect B (wrong drug concept) and Defect D (over-restrictive / infeasible rules), so <b>A alone is not sufficient</b> for them; B and D must be fixed too.";
})();

/* ---- per-cohort detail ---- */
document.getElementById('detail').innerHTML=D.rows.map(r=>{
  const drugBad=/sitagliptin|metabolite/i.test(r.gen_drug_concept);
  return `<div class="card" style="margin-bottom:12px">
   <div style="display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:8px">
     <div><b style="font-size:15px">${esc(r.trial)}</b> <span class="mono" style="color:var(--ink-3)">${r.role}</span></div>
     <div><span class="tag ${(r.patients_ajou===0&&r.patients_keimyung===0)?'bad':'warn'}">patients ${r.patients_ajou} / ${r.patients_keimyung}</span></div>
   </div>
   <div class="kv">
     <div class="k">Entry (gen)</div><div class="v"><span class="tag bad">${esc(r.gen_entry)}</span></div>
     <div class="k">Entry (gold)</div><div class="v mono">${esc(r.gold_entry)}</div>
     <div class="k">Drug concept</div><div class="v"><span class="mono ${drugBad?'':''}" style="color:${drugBad?'var(--bad)':'var(--good)'}">${esc(r.gen_drug_concept)}</span> <span class="arrow">— expected</span> <span class="mono">${esc(r.gold_drug_expected)}</span></div>
     <div class="k">Comparator design</div><div class="v">${esc(r.comparator_design)}</div>
     <div class="k">Killer rule</div><div class="v">${r.killer_rule?`<span style="color:var(--bad)">${esc(r.killer_rule)}</span>`:'<span style="color:var(--ink-3)">none</span>'}</div>
     <div class="k">ConceptSets</div><div class="v mono">gen ${r.gen_concept_sets} · gold ${r.gold_concept_sets}</div>
     <div class="k">InclusionRules</div><div class="v mono">gen ${r.gen_rules} · gold ${r.gold_rules}</div>
     <div class="k">Concepts</div><div class="v mono">shared ${r.shared} · gold-only ${r.gold_only} · gen-only ${r.gen_only} (Jaccard ${r.jaccard.toFixed(2)})</div>
   </div>
   <details><summary>Concept overlap examples</summary>
     <div style="font-size:12px;color:var(--ink-3);margin-top:6px">In gold but missing from generated (sample):</div>
     <div class="pill-row">${r.gold_only_ex.map(x=>`<span class="pill">${esc(x)}</span>`).join('')||'<span style="color:var(--ink-3)">—</span>'}</div>
     <div style="font-size:12px;color:var(--ink-3);margin-top:8px">Generated only, not in gold (sample):</div>
     <div class="pill-row">${r.gen_only_ex.map(x=>`<span class="pill">${esc(x)}</span>`).join('')||'<span style="color:var(--ink-3)">—</span>'}</div>
   </details>
  </div>`;}).join('');

function draw(){
  groupedBar('barPt',[{i:0,c:'--c-0',label:'Ajou'},{i:1,c:'--c-1',label:'Keimyung'}],
    [r=>r.patients_ajou,r=>r.patients_keimyung],v=>Math.round(v));
  jacBar();
  drawAdaptBars('adaptChangeChart','changes','proposed changes');
  drawAdaptBars('adaptTier2Chart','tier2','Tier-2 requests');
}
document.getElementById('themeBtn').onclick=()=>{const dark=!(root.getAttribute('data-theme')==='dark'||(!root.getAttribute('data-theme')&&matchMedia('(prefers-color-scheme:dark)').matches));root.setAttribute('data-theme',dark?'dark':'light');draw();};
matchMedia('(prefers-color-scheme:dark)').addEventListener('change',()=>{if(!root.getAttribute('data-theme'))draw();});
draw();
function noteView(listId, calId, filtId, data){
  const el=document.getElementById(listId); if(!el||!Array.isArray(data)) return;
  const cal=document.getElementById(calId), filt=document.getElementById(filtId);
  if(!cal||!filt||!cal.closest('.notes-side'))throw new Error(`dated narrative shell missing: ${listId}`);
  data.forEach(entry=>{if(!/^\d{4}-\d{2}-\d{2}$/.test(entry.date||''))throw new Error(`invalid note date: ${entry.date}`);if(!entry.key)throw new Error(`note key missing: ${entry.title}`);});
  const pad=n=>String(n).padStart(2,'0');
  const days=[...data].sort((a,b)=>(String(a.date)+(a.time||'')<String(b.date)+(b.time||'')?1:-1));
  const noteDates=new Set(days.map(d=>String(d.date)));
  let selected=null;  // null = 전체
  const tableHtml=t=>`<table class="datatable"><thead><tr>${(t.head||[]).map(h=>`<th>${mdN(h)}</th>`).join('')}</tr></thead><tbody>${(t.rows||[]).map(r=>`<tr>${(r||[]).map(c=>`<td>${mdN(c)}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
  const secBody=s=>`${(s.items&&s.items.length)?`<ul style="margin:5px 0 0;padding-left:18px;font-size:14px;color:var(--ink-2)">${s.items.map(i=>`<li style="margin:3px 0">${mdN(i)}</li>`).join('')}</ul>`:''}${s.table?tableHtml(s.table):''}`;
  const cardHtml=d=>`<div class="card" style="margin-bottom:16px">
    <div style="display:flex;justify-content:space-between;align-items:baseline;gap:8px">
      <div class="chart-t" style="margin:0">${mdN(d.title||'')}</div>
      <span class="note-stamp">${esc(d.date||'')}${d.time?' · '+esc(d.time):''}</span></div>
    <div class="note-key">${mdN(d.key)}</div>
    ${(d.sections||[]).map(s=>s.collapsed
      ? `<details class="note-details"><summary>${mdN(s.h||'')}</summary><div style="margin-top:6px">${secBody(s)}</div></details>`
      : `<div style="margin-top:11px"><div style="color:var(--accent);font-weight:700;font-size:11px;text-transform:uppercase;letter-spacing:.06em">${mdN(s.h||'')}</div>${secBody(s)}</div>`).join('')}
  </div>`;
  function renderNotes(){
    const list=selected?days.filter(d=>String(d.date)===selected):days;
    filt.hidden=!selected;
    if(selected) filt.innerHTML=`<b>${selected}</b> 노트 ${list.length}건 · <a id="showAll">전체 보기</a>`;
    el.innerHTML=list.map(cardHtml).join('')||'<div class="chart-s">이 날짜엔 노트가 없습니다.</div>';
    const sa=document.getElementById('showAll'); if(sa) sa.onclick=()=>{selected=null;drawCal();renderNotes();};
  }
  const DOW=['일','월','화','수','목','금','토'];
  let ym;
  if(days[0]){const p=String(days[0].date).split('-').map(Number);ym={y:p[0],m:p[1]-1};}
  else ym={y:2026,m:6};
  function drawCal(){
    const {y,m}=ym;
    const startDow=new Date(Date.UTC(y,m,1)).getUTCDay();
    const dim=new Date(Date.UTC(y,m+1,0)).getUTCDate();
    let cells=DOW.map(d=>`<div class="notecal-dow">${d}</div>`).join('');
    for(let i=0;i<startDow;i++) cells+='<div class="notecal-day"></div>';
    for(let day=1;day<=dim;day++){
      const ds=`${y}-${pad(m+1)}-${pad(day)}`, has=noteDates.has(ds), sel=selected===ds;
      cells+=`<div class="notecal-day cur${has?' has':''}${sel?' sel':''}"${has?` data-d="${ds}"`:''}>${day}</div>`;
    }
    cal.innerHTML=`<div class="notecal-head"><button class="notecal-nav" data-cal-prev aria-label="이전 달">‹</button><div class="notecal-title">${y}.${pad(m+1)}</div><button class="notecal-nav" data-cal-next aria-label="다음 달">›</button></div><div class="notecal-grid">${cells}</div>`;
    cal.querySelector('[data-cal-prev]').onclick=()=>{if(--ym.m<0){ym.m=11;ym.y--;}drawCal();};
    cal.querySelector('[data-cal-next]').onclick=()=>{if(++ym.m>11){ym.m=0;ym.y++;}drawCal();};
    cal.querySelectorAll('.notecal-day.has').forEach(c=>c.onclick=()=>{selected=selected===c.dataset.d?null:c.dataset.d;drawCal();renderNotes();});
  }
  drawCal(); renderNotes();
}
// Related work has no date, so it reuses the section body shape (h / items / table)
// without the calendar shell. A verdict badge carries the only thing a reader needs
// up front: whether we took the source, and if not, why it does not settle the question.
function refView(listId, data){
  const el=document.getElementById(listId); if(!el||!Array.isArray(data)) return;
  const VERDICT={adopt:['채택','ok'],partial:['부분','warn'],reject:['불채택','bad']};
  const tableHtml=t=>`<table class="datatable"><thead><tr>${(t.head||[]).map(h=>`<th>${mdN(h)}</th>`).join('')}</tr></thead><tbody>${(t.rows||[]).map(r=>`<tr>${(r||[]).map(c=>`<td>${mdN(c)}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
  const secBody=s=>`${(s.items&&s.items.length)?`<ul style="margin:5px 0 0;padding-left:18px;font-size:14px;color:var(--ink-2)">${s.items.map(i=>`<li style="margin:3px 0">${mdN(i)}</li>`).join('')}</ul>`:''}${s.table?tableHtml(s.table):''}`;
  el.innerHTML=data.map(r=>{
    const [vlabel,vcls]=VERDICT[r.verdict]||[r.verdict_label||'',''];
    return `<div class="card" style="margin-bottom:16px">
      <div style="display:flex;justify-content:space-between;align-items:baseline;gap:8px;flex-wrap:wrap">
        <div class="chart-t" style="margin:0">${mdN(r.name||'')}</div>
        <span class="refverdict ${vcls}">${esc(r.verdict_label||vlabel)}</span></div>
      <div class="note-key">${mdN(r.summary||'')}</div>
      <div class="refcite">${r.url?`<a href="${esc(r.url)}" target="_blank" rel="noopener">${mdN(r.full||'')}</a>`:mdN(r.full||'')}${r.venue?` · <span class="mono">${esc(r.venue)}</span>`:''}</div>
      ${(r.sections||[]).map(s=>`<div style="margin-top:11px"><div style="color:var(--accent);font-weight:700;font-size:11px;text-transform:uppercase;letter-spacing:.06em">${mdN(s.h||'')}</div>${secBody(s)}</div>`).join('')}
    </div>`;
  }).join('')||'<div class="chart-s">관련 연구 항목이 없습니다.</div>';
}

noteView('notes','cal','notesFilter',NOTES);
noteView('issues','ical','issFilter',ISSUES);
noteView('lab','lcal','labFilter',LAB);
refView('refs',REFS);
activateTab(location.hash.slice(1),false);
scrollTo(0,0);
const _toTop=document.getElementById('toTop');
if(_toTop){addEventListener('scroll',()=>_toTop.classList.toggle('show',scrollY>400),{passive:true});_toTop.onclick=()=>scrollTo({top:0,behavior:'smooth'});}
</script></body></html>
"""


if __name__ == "__main__":
    main()
