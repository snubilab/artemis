#!/usr/bin/env python3
"""Build a self-contained HTML dashboard for the gold-vs-generated Circe diagnosis.

Reads the computed diagnosis.json + comparison.json (numbers stay in sync with the
source) and emits dashboard.html with all data/CSS/JS inlined (no external refs).

Usage: python3 artemis/scripts/build_diagnosis_dashboard.py
"""
from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "output" / "gold_vs_generated"


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
    html = TEMPLATE.replace("/*__DATA__*/", json.dumps(diag, ensure_ascii=False))
    html = html.replace("/*__SIMDATA__*/", json.dumps(sim, ensure_ascii=False))
    html = html.replace("/*__NOTES__*/", json.dumps(notes, ensure_ascii=False))
    html = html.replace("/*__ISSUES__*/", json.dumps(issues, ensure_ascii=False))
    html = html.replace("/*__LAB__*/", json.dumps(lab, ensure_ascii=False))
    (OUT / "dashboard.html").write_text(html)
    print("wrote", OUT / "dashboard.html", f"({len(html)} bytes)")


TEMPLATE = r"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Gold vs Generated — Circe Cohort Diagnosis</title>
<style>
:root{
  --bg:#f4f5f7;--surface:#fcfcfb;--surface-2:#eef0f3;--ink:#1a1d21;--ink-2:#4a5058;--ink-3:#767d87;
  --line:#dfe3e8;--line-2:#c9ced6;
  --c-0:#2563C4;--c-1:#E07A0F;--c-2:#0E9488;
  --status:#B8791A;--status-bg:#f6ead5;--status-line:#e6c894;--good:#0E8A5F;--bad:#C0392B;--accent:#0E7490;
  --crit-bg:#fbe9e7;--crit-line:#e6b0a8;
  --mono:ui-monospace,"SF Mono","Cascadia Code",Menlo,monospace;--sans:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
}
:root[data-theme="dark"]{
  --bg:#111315;--surface:#1a1a19;--surface-2:#212427;--ink:#e9ecef;--ink-2:#a7aeb6;--ink-3:#727984;
  --line:#2c3035;--line-2:#3a4046;--c-0:#5590D0;--c-1:#C9821F;--c-2:#35A89A;
  --status:#E0A94A;--status-bg:#2a2213;--status-line:#4d3d1c;--good:#3FB98A;--bad:#E4695C;--accent:#3FB3C9;
  --crit-bg:#2b1614;--crit-line:#5a2c26;}
@media(prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --bg:#111315;--surface:#1a1a19;--surface-2:#212427;--ink:#e9ecef;--ink-2:#a7aeb6;--ink-3:#727984;
  --line:#2c3035;--line-2:#3a4046;--c-0:#5590D0;--c-1:#C9821F;--c-2:#35A89A;
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
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:right;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th:first-child,td:first-child{text-align:left}
thead th{font-size:10.5px;letter-spacing:.05em;text-transform:uppercase;color:var(--ink-3);font-weight:600}
tbody tr:last-child td{border-bottom:none}
.tag{display:inline-block;font-family:var(--mono);font-size:10.5px;padding:1px 6px;border-radius:5px;font-weight:600}
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
.tabpanel[hidden]{display:none}
.log-inc td.zero,.log-inc .zero{color:var(--bad);font-weight:700}
</style></head><body><div class="wrap">
<header>
  <div><div class="eyebrow">OHDSI · Circe cohort QA</div>
  <h1>Gold vs Generated — Cohort Definition Diagnosis</h1>
  <div class="sub">AI-generated TROY v1.1 study cohorts (CAROLINA / CARMELINA / EMPA-REG OUTCOME) run on real hospital CDM via CohortGenerator. Why the patient counts collapsed.</div></div>
  <button class="toggle" id="themeBtn">Theme</button>
</header>
<nav class="tabs" role="tablist">
  <button class="tab active" data-tab="diagnosis">Diagnosis</button>
  <button class="tab" data-tab="log">Issue Log</button>
  <button class="tab" data-tab="notes">Daily Notes</button>
  <button class="tab" data-tab="lab">실험노트</button>
</nav>
<div id="tab-diagnosis" class="tabpanel">
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

<div id="tab-log" class="tabpanel" hidden>
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

<div id="tab-notes" class="tabpanel" hidden>
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

<div id="tab-lab" class="tabpanel" hidden>
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

</div><div class="tip" id="tip"></div>
<button id="toTop" title="맨 위로" aria-label="맨 위로">↑</button>
<script id="data" type="application/json">/*__DATA__*/</script>
<script id="simdata" type="application/json">/*__SIMDATA__*/</script>
<script id="notesdata" type="application/json">/*__NOTES__*/</script>
<script id="issuesdata" type="application/json">/*__ISSUES__*/</script>
<script id="labdata" type="application/json">/*__LAB__*/</script>
<script>
const D=JSON.parse(document.getElementById('data').textContent);
const SIM=JSON.parse(document.getElementById('simdata').textContent);
const NOTES=JSON.parse(document.getElementById('notesdata').textContent);
const ISSUES=JSON.parse(document.getElementById('issuesdata').textContent);
const LAB=JSON.parse(document.getElementById('labdata').textContent);
const root=document.documentElement;
document.querySelectorAll('.tab').forEach(t=>t.addEventListener('click',()=>{
  document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('active',x===t));
  document.querySelectorAll('.tabpanel').forEach(p=>{p.hidden=(p.id!=='tab-'+t.dataset.tab);});
}));
const cssvar=v=>getComputedStyle(root).getPropertyValue(v).trim();
const tip=document.getElementById('tip');
function showTip(h,e){tip.innerHTML=h;tip.style.opacity=1;const p=12;let x=e.clientX+p,y=e.clientY+p;const r=tip.getBoundingClientRect();if(x+r.width>innerWidth)x=e.clientX-r.width-p;if(y+r.height>innerHeight)y=e.clientY-r.height-p;tip.style.left=x+'px';tip.style.top=y+'px';}
const hideTip=()=>tip.style.opacity=0;
const esc=s=>String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));

document.getElementById('verdictText').textContent=
 "Four independent defects: (A) every cohort enters on Type 2 Diabetes instead of the index drug; (B) the study-drug ConceptSets contain the WRONG drug (linagliptin->sitagliptin, empagliflozin->an unrelated metabolite); (C) each comparator is defined as 'NOT the treatment drug' rather than the real active comparator; (D) uncodeable inclusion rules (EMPA #11 diet/exercise regimen, CARMELINA #9 albuminuria/UACR) drop every patient. Even CAROLINA's non-zero counts are on the wrong drug, so no cohort is usable.";

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
}
document.getElementById('themeBtn').onclick=()=>{const dark=!(root.getAttribute('data-theme')==='dark'||(!root.getAttribute('data-theme')&&matchMedia('(prefers-color-scheme:dark)').matches));root.setAttribute('data-theme',dark?'dark':'light');draw();};
matchMedia('(prefers-color-scheme:dark)').addEventListener('change',()=>{if(!root.getAttribute('data-theme'))draw();});
draw();
function noteView(listId, calId, filtId, data){
  const el=document.getElementById(listId); if(!el||!Array.isArray(data)) return;
  const cal=document.getElementById(calId), filt=document.getElementById(filtId);
  const pad=n=>String(n).padStart(2,'0');
  const days=[...data].sort((a,b)=>(String(a.date)<String(b.date)?1:-1));
  const noteDates=new Set(days.map(d=>String(d.date)));
  let selected=null;  // null = 전체
  const tableHtml=t=>`<table class="datatable"><thead><tr>${(t.head||[]).map(h=>`<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${(t.rows||[]).map(r=>`<tr>${(r||[]).map(c=>`<td>${esc(c)}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
  const secBody=s=>`${(s.items&&s.items.length)?`<ul style="margin:5px 0 0;padding-left:18px;font-size:13px;color:var(--ink-2)">${s.items.map(i=>`<li style="margin:3px 0">${esc(i)}</li>`).join('')}</ul>`:''}${s.table?tableHtml(s.table):''}`;
  const cardHtml=d=>`<div class="card" style="margin-bottom:16px">
    <div style="display:flex;justify-content:space-between;align-items:baseline;gap:8px">
      <div class="chart-t" style="margin:0">${esc(d.title||'')}</div>
      <span class="tag" style="background:var(--surface-2);color:var(--ink-2)">${esc(d.date||'')}</span></div>
    ${(d.sections||[]).map(s=>s.collapsed
      ? `<details class="note-details"><summary>${esc(s.h||'')}</summary><div style="margin-top:6px">${secBody(s)}</div></details>`
      : `<div style="margin-top:11px"><div style="color:var(--accent);font-weight:700;font-size:11px;text-transform:uppercase;letter-spacing:.06em">${esc(s.h||'')}</div>${secBody(s)}</div>`).join('')}
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
    cal.innerHTML=`<div class="notecal-head"><button class="notecal-nav" id="calPrev">‹</button><div class="notecal-title">${y}.${pad(m+1)}</div><button class="notecal-nav" id="calNext">›</button></div><div class="notecal-grid">${cells}</div>`;
    document.getElementById('calPrev').onclick=()=>{if(--ym.m<0){ym.m=11;ym.y--;}drawCal();};
    document.getElementById('calNext').onclick=()=>{if(++ym.m>11){ym.m=0;ym.y++;}drawCal();};
    cal.querySelectorAll('.notecal-day.has').forEach(c=>c.onclick=()=>{selected=selected===c.dataset.d?null:c.dataset.d;drawCal();renderNotes();});
  }
  drawCal(); renderNotes();
}
noteView('notes','cal','notesFilter',NOTES);
noteView('issues','ical','issFilter',ISSUES);
noteView('lab','lcal','labFilter',LAB);
const _toTop=document.getElementById('toTop');
if(_toTop){addEventListener('scroll',()=>_toTop.classList.toggle('show',scrollY>400),{passive:true});_toTop.onclick=()=>scrollTo({top:0,behavior:'smooth'});}
</script></body></html>
"""


if __name__ == "__main__":
    main()
