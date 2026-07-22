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
    payload = json.dumps(diag, ensure_ascii=False)
    html = TEMPLATE.replace("/*__DATA__*/", payload)
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
</style></head><body><div class="wrap">
<header>
  <div><div class="eyebrow">OHDSI · Circe cohort QA</div>
  <h1>Gold vs Generated — Cohort Definition Diagnosis</h1>
  <div class="sub">AI-generated TROY v1.1 study cohorts (CAROLINA / CARMELINA / EMPA-REG OUTCOME) run on real hospital CDM via CohortGenerator. Why the patient counts collapsed.</div></div>
  <button class="toggle" id="themeBtn">Theme</button>
</header>
<div class="verdict"><div class="dot"></div><div>
  <h3>All 6 generated cohorts are invalid. The 0-patient counts are only the most visible symptom.</h3>
  <p id="verdictText"></p></div></div>

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

<section><div class="sec-head"><h2>Per-cohort detail</h2></div><div id="detail"></div></section>

</div><div class="tip" id="tip"></div>
<script id="data" type="application/json">/*__DATA__*/</script>
<script>
const D=JSON.parse(document.getElementById('data').textContent);
const root=document.documentElement;
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
</script></body></html>
"""


if __name__ == "__main__":
    main()
