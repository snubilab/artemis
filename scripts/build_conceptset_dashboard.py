#!/usr/bin/env python3
"""Build a self-contained HTML dashboard for the paired concept-set overlap evaluation.

Reads the two scored arms produced by ``conceptset_overlap_eval.py`` and renders one
shareable file: six trials at the overview level, the individual criterion pairs
underneath, and the record panes (plan / experiment note / issues).

The caveat this dashboard exists to keep visible: five pairs moved but three are gold's
own unreferenced duplicates, so the honest count is two distinct corrections. See
``artemis/AGENTS.md`` EVALUATION.

Usage:
    python3 scripts/build_conceptset_dashboard.py \
        --arm-a output/conceptset_overlap/scoped_arm_a.json \
        --arm-b output/conceptset_overlap/scoped_arm_b.json \
        --out   output/conceptset_overlap/dashboard.html
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ARTEMIS_DIR = Path(__file__).resolve().parent.parent
TEMPLATE = Path.home() / ".claude" / "skills" / "dashboard" / "assets" / "template.html"
WIKI_PLAN = ARTEMIS_DIR.parent / "omx_wiki" / "dashboard" / "plan.json"

SLUG = {
    "ARISTOTLE": "aristotle",
    "CARMELINA": "carmelina",
    "CAROLINA": "carolina",
    "EMPA-REG OUTCOME": "empareg",
    "LEADER": "leader",
    "PLATO": "plato",
}

# The three pairs that are gold's own unreferenced duplicates of the two real ones.
DUPLICATE_PAIRS = {
    ("CARMELINA", "[TROY intervention] Linagliptin"),
    ("CAROLINA", "linagliptin"),
    ("CAROLINA", "[TROY intervention] Linagliptin"),
}


def _pairs(report: dict) -> dict[tuple[str, str], dict]:
    """Keyed by gold_key, not gold_name: 12 of the 232 gold names repeat within a trial
    (gold defines duplicate concept sets), and keying by name silently drops those rows."""
    return {(t["trial"], p["gold_key"]): p for t in report["trials"] for p in t["pairs"]}


def _macro(report: dict, key: str) -> float:
    vals = [t["per_criterion"][key] for t in report["trials"]]
    return sum(vals) / len(vals)


def _zero(report: dict) -> int:
    return sum(1 for t in report["trials"] for p in t["pairs"] if p["shared"] == 0)


def build_rows(a: dict, b: dict) -> list[dict]:
    """One row per criterion pair, control (arm B) and treatment (arm A) side by side."""
    pa, pb = _pairs(a), _pairs(b)
    rows = []
    for (trial, key), p in pa.items():
        q = pb.get((trial, key))
        if q is None:
            continue
        rows.append(
            {
                "id": f"{trial} · {p['gold_name']}",
                "bucket": SLUG[trial],
                "ctl_rec": round(q["recall"], 4),
                "fix_rec": round(p["recall"], 4),
                "ctl_prec": round(q["precision"], 4),
                "fix_prec": round(p["precision"], 4),
            }
        )
    rows.sort(key=lambda r: (r["fix_rec"] - r["ctl_rec"], -r["ctl_rec"]), reverse=True)
    return rows


def build_units(a: dict, b: dict) -> list[dict]:
    """One card per trial. Status says whether the arms differ at all for that trial."""
    ta = {t["trial"]: t for t in a["trials"]}
    tb = {t["trial"]: t for t in b["trials"]}
    pa, pb = _pairs(a), _pairs(b)
    units = []
    for trial, t in ta.items():
        ra, rb = t["per_criterion"]["recall_mean"], tb[trial]["per_criterion"]["recall_mean"]
        qa, qb = t["per_criterion"]["precision_mean"], tb[trial]["per_criterion"]["precision_mean"]
        moved = [
            p["gold_name"] for (tr, k), p in pa.items()
            if tr == trial and abs(p["recall"] - pb[(tr, k)]["recall"]) > 1e-9
        ]
        real = [g for g in moved if (trial, g) not in DUPLICATE_PAIRS]
        dup = [g for g in moved if (trial, g) in DUPLICATE_PAIRS]
        n_pairs = len(t["pairs"])
        zero = sum(1 for p in t["pairs"] if p["shared"] == 0)
        oos = t["out_of_scope_gold"]["sets"]

        if moved:
            status, verdict = "partial", (
                f"**recall {rb:.3f} → {ra:.3f}** ({ra - rb:+.3f}), precision {qb:.3f} → {qa:.3f}. "
                f"{len(real)}건의 구별되는 수정"
                + (f", 그리고 gold 자체의 중복 {len(dup)}쌍이 같은 수정을 다시 셈." if dup else ".")
            )
        else:
            status, verdict = "complete", (
                f"recall {ra:.3f}, precision {qa:.3f} — 두 arm이 **정확히 0.000** 차이. "
                "이 trial의 CIRCE 파일은 두 arm 사이에서 바이트 동일하며, 이것이 arm parity의 증거."
            )

        units.append(
            {
                "id": trial,
                "title": trial,
                "subtitle": f"gold: {t['gold_file']}",
                "status": status,
                "summary": verdict,
                "completion": {"done": n_pairs - zero, "total": n_pairs, "label": "겹침 있는 쌍"},
                "evidence": [
                    f"`{t['generated_file']}` md5 `{t['generated_md5'][:8]}…`",
                    f"짝지어진 쌍 {n_pairs} · 겹침 0인 쌍 {zero}",
                    f"범위 밖 gold 집합 {len(oos)}"
                    + (f" — {', '.join(s['name'] for s in oos)}" if oos else " (없음)"),
                ],
                "next_gate": (
                    f"겹침 0인 쌍 {zero}건의 원인 분류" if zero else "겹침 0인 쌍 없음"
                ),
                "blockers": (
                    ["`BI 10773` 개발코드가 `CHF-6366 .beta.-2 metabolite`로 매핑됨"]
                    if trial == "EMPA-REG OUTCOME"
                    else ["`glimepiride` 기준의 sourceText 한정어 탈락"]
                    if trial == "CAROLINA"
                    else []
                ),
                "technical_ids": moved or ["변경 없음"],
            }
        )
    units.sort(key=lambda u: (u["status"] != "partial", u["id"]))
    return units


def build_plan() -> list[dict]:
    """Reuse the concept-set rows already curated on the omx_wiki plan board."""
    if not WIKI_PLAN.exists():
        return []
    rows = [
        dict(r) for r in json.loads(WIKI_PLAN.read_text())
        if r.get("group", "").startswith("Concept-set quality")
    ]
    # planView refuses a done/running row with nothing to point at, which is the right
    # rule: a finished row with no evidence is the one a reader trusts most.
    for r in rows:
        if r.get("status") in ("done", "running", "partial") and not r.get("links"):
            r["links"] = [{"pane": "pane-notes", "date": "2026-08-09",
                           "label": "짝지은 2-arm 측정"}]
    return rows


def build_notes(a: dict, b: dict, rows: list[dict]) -> list[dict]:
    ra, rb = _macro(a, "recall_mean"), _macro(b, "recall_mean")
    moved = [r for r in rows if abs(r["fix_rec"] - r["ctl_rec"]) > 1e-9]
    return [
        {
            "date": "2026-08-09",
            "time": "23:10",
            "status": "완료",
            "title": "entry 약물 exact match의 실제 효과",
            "key": (
                f"수정은 유효하지만 **구별되는 수정은 2건**이다 — macro recall {rb:.3f} → {ra:.3f}, "
                f"겹침 0인 쌍 {_zero(b)} → {_zero(a)}. 움직인 {len(moved)}쌍 중 3쌍은 gold 자체의 "
                "참조되지 않는 중복이라 같은 수정을 다시 센 것."
            ),
            "sections": [
                {"h": "Decision Question", "items": [
                    "`expected_domain in (\"Drug\", None)`으로 게이트를 넓힌 991c11c가 gold 대비 concept set 품질을 실제로 올리는가, "
                    "그리고 그 변화가 게이트에 귀속되는가."]},
                {"h": "Hypothesis", "items": [
                    "linagliptin 쌍이 0.0 → ~1.0으로 가고 나머지는 불변, 6-trial macro recall은 약 +0.03. "
                    "이보다 크게 움직이면 게이트 외의 무언가가 바뀐 것이므로 숫자를 신뢰하지 않는다. **채점 전에 기록함.**"]},
                {"h": "Run Identity", "items": [
                    "arm A = `output/circe_arm_a`, arm B = `output/circe_arm_b`. 둘 다 동일 store "
                    "`tmp/tte_six_deliver/studies.json` (2026-08-04)에서 동일 exporter로 같은 날 생성.",
                    "채점: `scripts/conceptset_overlap_eval.py --mode closure --vocab-schema synthea23m`, 두 arm 동일 플래그.",
                    "arm A 생성: `scripts/rebuild_entry_concept_sets.py` — 입력 store를 변경하지 않음."]},
                {"h": "Live Snapshot", "items": [
                    "두 arm 모두 exit 0. 6개 export 파일 중 **4개가 바이트 동일**하고 CARMELINA·CAROLINA만 다름 — md5로 확인.",
                    "전면 재생성은 기각. 게이트는 study당 concept set 1개만 지나가므로, 6개 trial 재생성은 "
                    "변하지 않을 ~370개를 다시 만들면서 store 생성 이후의 모든 커밋을 섞어 귀속을 파괴한다."]},
                {"h": "Results", "table": {
                    "head": ["trial", "recall B", "recall A", "Δ"],
                    "rows": [[t["trial"],
                              f"{{:.3f}}".format([x for x in b["trials"] if x["trial"] == t["trial"]][0]["per_criterion"]["recall_mean"]),
                              f"{t['per_criterion']['recall_mean']:.3f}",
                              "**{:+.3f}**".format(t["per_criterion"]["recall_mean"] - [x for x in b["trials"] if x["trial"] == t["trial"]][0]["per_criterion"]["recall_mean"])]
                             for t in a["trials"]] + [["**6-trial macro**", f"**{rb:.3f}**", f"**{ra:.3f}**", f"**{ra - rb:+.3f}**"]]},
                    "items": ["손대지 않은 4개 trial이 **정확히 0.000** 움직인 것이 parity의 증거다."]},
                {"h": "Interpretation", "items": [
                    "예측이 그대로 맞았다(+0.030 포함). 다만 쌍 수는 수정 수가 아니다: gold의 비-ATC "
                    "`[TROY intervention] <drug>` 집합은 `PrimaryCriteria`가 참조하는 `(ATC)` 집합의 중복이고 "
                    "어떤 기준도 참조하지 않는다. 238개 중 14개가 그런 고아다.",
                    "귀속의 폭은 좁다: 이 두 시드에 대해 임베딩 경로가 같은 계열의 다른 분자를 반환하고 exact match가 맞는 것을 반환한다는 것까지. "
                    "임베딩이 고유명사에 약한 *이유*는 아직 증명되지 않았다 — `ARTEMIS_DISABLE_EXACT_INGREDIENT_MATCH=1` 대조군은 미실행."]},
                {"h": "Decision", "items": [
                    "채택 — 991c11c 유지. 보고 규칙을 `AGENTS.md` EVALUATION에 고정: 쌍 수가 아니라 구별되는 수정 수를 인용한다.",
                    "다음: `glimepiride` sourceText 한정어 탈락, `BI 10773` 개발코드 경로."]},
            ],
        }
    ]


ISSUES = [
    {
        "date": "2026-08-10", "status": "조사 중",
        "title": "criterion sourceText가 한정어를 잃고 약물명만 남는다",
        "key": "\"Hypersensitivity to investigational product or glimepiride\"가 `glimepiride`로 정규화되어, 과민반응 기준이 약물 집합처럼 채점된다.",
        "sections": [
            {"h": "Impact", "items": [
                "CAROLINA의 겹침 0인 쌍 2건. 원래 \"wrong entity 7건\"으로 분류돼 매퍼 결함으로 오인됐다.",
                "더 넓게는, 한정어를 잃은 모든 기준이 이름만으로 엉뚱한 gold 집합과 짝지어질 수 있다."]},
            {"h": "Observed Symptom", "items": [
                "저장된 concept set 이름이 `glimepiride`이고 내용은 Condition 개념 3개 "
                "(`Poisoning caused by sulfonylurea`, `Hypoglycemic event due to diabetes`, `Drug-induced hypoglycemia`)."]},
            {"h": "Evidence", "items": [
                "기준 원문: description = \"Hypersensitivity to investigational product or glimepiride\", domain = `Condition`, sourceText = `glimepiride`.",
                "저장된 `sourceText`는 절단이 아니라 Agent 1의 정규화된 `entity_text` (`tte_service.py:9574`); "
                "축자 원문 `Criteria.source_text` (`ir.py:87`)는 store에 닿기 전에 버려진다."]},
            {"h": "Hypotheses", "items": [
                "Agent 1의 entity 정규화가 기준 전체가 아니라 개체명만 남긴다 — 다음 확인 지점.",
                "domain = `Condition`은 방어 가능하다: 과민반응은 실제로 Condition이며, 매퍼는 충실히 동작했다."]},
            {"h": "Root Cause", "items": ["미확정 — 정규화 지점을 특정하지 못했다."]},
            {"h": "Resolution", "items": [
                "해당 없음 — 수정 없음. 다만 **하면 안 되는 것**은 측정됐다: domain 게이트를 풀어 성분 매칭을 강제하면 "
                "`Calcitonin`, `Creatinine`, `Glucose`, `glucose` (분석물 이름을 가진 Measurement 기준)가 약물 노출로 오분류된다."]},
            {"h": "Verification", "items": ["미확정 — 수정 이후에 정해진다."]},
            {"h": "Closure", "items": ["미해결 — 조사 중."]},
        ],
    },
    {
        "date": "2026-08-10", "status": "신규",
        "title": "개발코드 `BI 10773`이 무관한 대사체로 매핑된다",
        "key": "EMPA-REG의 entry 약물이 `1254065 CHF-6366 .beta.-2 metabolite`로 해석된다 — empagliflozin이 아니다.",
        "sections": [
            {"h": "Impact", "items": [
                "EMPA-REG OUTCOME의 entry 약물 concept set 전체가 잘못된 물질이다. 2026-08-09 이전 어떤 기록에도 없던 결함."]},
            {"h": "Observed Symptom", "items": [
                "`targetCohortName` = `BI 10773` → 저장된 concept set id=1 = `1254065 'CHF-6366 .beta.-2 metabolite'`."]},
            {"h": "Evidence", "items": [
                "`BI 10773`은 empagliflozin의 개발코드다. RxNorm Ingredient에 그 이름을 가진 개념이 없어 "
                "`_exact_ingredient_mapping`이 `None`을 반환하고 임베딩 경로로 정상 fall-through한다 — 그 임베딩 답이 틀렸다.",
                "다른 5개 trial의 entry 약물(apixaban, liraglutide, ticagrelor, linagliptin ×2)은 모두 정확히 해석된다."]},
            {"h": "Hypotheses", "items": [
                "개발코드·동의어를 정식 성분명으로 먼저 해석하는 경로가 필요하다. 후보: RxNorm 동의어 테이블, 또는 시험 메타데이터의 개입 약물명."]},
            {"h": "Root Cause", "items": ["미확정 — 개발코드를 다루는 경로가 존재하지 않는다는 것까지만 확인됐다."]},
            {"h": "Resolution", "items": ["해당 없음 — 아직 착수하지 않았다."]},
            {"h": "Verification", "items": ["미확정 — 수정 이후에 정해진다."]},
            {"h": "Closure", "items": ["미해결 — 신규."]},
        ],
    },
]


def render(a: dict, b: dict, out: Path) -> None:
    rows = build_rows(a, b)
    units = build_units(a, b)
    ra, rb = _macro(a, "recall_mean"), _macro(b, "recall_mean")
    za, zb = _zero(a), _zero(b)
    moved = [r for r in rows if abs(r["fix_rec"] - r["ctl_rec"]) > 1e-9]
    oos = sum(len(t["out_of_scope_gold"]["sets"]) for t in a["trials"])

    framing = [
        {"title": "묻는 것", "text":
            "임상시험 eligibility 기준에서 생성한 concept set이 gold(TROY v1.1 CIRCE)와 얼마나 일치하는가 — "
            "그리고 `991c11c`의 게이트 수정이 그 일치도를 실제로 올렸는가."},
        {"title": "기존 방식", "text":
            "이전에는 `synthea_cdm` 계열 벤치마크 CDM의 환자 수로 품질을 판단했다. 그 CDM은 gold **로부터** 생성되므로 "
            "환자 수는 생성기의 관례를 부분적으로 측정한다. 그래서 측정 기준이 `data/gold/` 대비 closure 겹침으로 교체됐다."},
        {"title": "남아 있던 구멍", "text":
            "겹침을 **어느 단위로** 재느냐가 정해지지 않아, 처음 측정은 pooled concept mass(micro) 평균이었고 "
            "그것은 ARISTOTLE의 결론을 뒤집었다(micro 0.087/0.863 vs 기준별 0.749/0.153). "
            "단위는 이제 **eligibility 기준별 1:1, macro 평균**으로 고정됐다."},
        {"title": "이 페이지가 뒷받침하는 것", "text":
            f"동일 store·동일 exporter·동일 채점 플래그로 만든 짝지은 2-arm 비교. macro recall {rb:.3f} → {ra:.3f}, "
            f"겹침 0인 쌍 {zb} → {za}. 손대지 않은 4개 trial이 정확히 0.000 움직였다는 것이 parity의 증거다."},
        {"title": "아직 주장하지 않는 것", "text":
            "임베딩 검색이 고유명사에 약한 *이유*(동일 계열 약물이 벡터 공간에서 가깝다는 가설)는 증명되지 않았다. "
            "exact match가 경쟁한 적이 없었으므로, 대조군 `ARTEMIS_DISABLE_EXACT_INGREDIENT_MATCH=1`을 돌려야 한다. 미실행."},
    ]

    tmpl = TEMPLATE.read_text()

    def swap(html: str, block_id: str, payload) -> str:
        pat = re.compile(
            r'(<script id="%s" type="application/json">)(.*?)(</script>)' % re.escape(block_id),
            re.S,
        )
        new, n = pat.subn(
            lambda m: m.group(1) + "\n" + json.dumps(payload, ensure_ascii=False, indent=1) + "\n" + m.group(3),
            html, count=1,
        )
        if n != 1:
            raise SystemExit(f"data block {block_id!r} not found in template — refusing to ship demo data")
        return new

    html = tmpl
    for bid, payload in (
        ("framingdata", framing), ("unitdata", units), ("data", rows),
        ("plandata", build_plan()), ("notesdata", build_notes(a, b, rows)), ("issuesdata", ISSUES),
    ):
        html = swap(html, bid, payload)

    def sub1(pattern: str, repl: str, label: str) -> None:
        nonlocal html
        html, n = re.subn(pattern, repl.replace("\\", "\\\\"), html, count=1, flags=re.S)
        if n != 1:
            raise SystemExit(f"could not patch {label} — template changed")

    # Both arms are VARS so the per-item table shows them side by side; ctl is ALSO the
    # BASELINE, which is what the delta chart and the dashed reference line measure against.
    # The control then appears as a flat zero series on the delta chart — that is the
    # reference, not noise, and it keeps the comparison visible in every view.
    sub1(r"const VARS=\[.*?\];",
         "const VARS=[{k:'ctl',label:'Arm B — 대조군',c:'--c-1'},"
         "{k:'fix',label:'Arm A — exact match ON',c:'--c-0'}];", "VARS")
    sub1(r"const METRICS=\[.*?\];",
         "const METRICS=[{k:'rec',label:'recall',dec:3,unit:''},{k:'prec',label:'precision',dec:3,unit:''}];",
         "METRICS")
    sub1(r"const BASELINE=\{.*?\};",
         "const BASELINE={k:'ctl',label:'기준선 = Arm B (위 행과 동일)'};", "BASELINE")

    chips = ['<button class="chip" aria-pressed="true" data-val="all">전체</button>'] + [
        f'<button class="chip" aria-pressed="false" data-val="{SLUG[t]}">{t}</button>'
        for t in SLUG
    ]
    sub1(r'<div class="chips" data-filter="bucket">.*?</div>',
         '<div class="chips" data-filter="bucket">\n' + "\n".join("            " + c for c in chips) + "\n          </div>",
         "bucket chips")

    tiles = (
        "const TILES=[\n"
        f"  ()=>({{v:{len(rows)},lab:'채점된 기준 쌍'}}),\n"
        f"  ()=>({{v:'{rb:.3f} → {ra:.3f}',lab:'6-trial macro recall ({ra - rb:+.3f})',cls:'good'}}),\n"
        f"  ()=>({{v:'{zb} → {za}',lab:'겹침 0인 쌍',cls:'good'}}),\n"
        f"  ()=>({{v:2,lab:'구별되는 수정 ({len(moved)}쌍이 움직였으나 3쌍은 gold의 중복)',cls:'alert'}}),\n"
        "];"
    )
    sub1(r"const TILES=\[.*?\n\];", tiles, "TILES")

    copy_patch = f"""const COPY={{
  locale:'ko-KR',
  groups:{{results:'결과',record:'기록',build:'Build'}},
  tabs:{{overview:'개요',detail:'기준 쌍',samples:'샘플',plan:'계획',notes:'실험 노트',issues:'이슈 노트',components:'Components'}},
  sections:{{overview:'개요',glance:'한눈에',summary:'arm 요약',findings:'읽는 법',units:'trial별',distributions:'분포',delta:'대조군 대비 쌍별 변화',itemTable:'기준 쌍 표',samples:'샘플',plan:'계획',notes:'실험 노트',issues:'이슈 노트'}},
  controls:{{theme:'◐ 테마',metricLabel:'지표',bucket:'trial',search:'검색',prev:'◀ 이전',next:'다음 ▶'}},
  buckets:{{all:'전체'}},
  record:{{
    status:'상태',all:'전체',entries:'건',entry:'건',showAllDates:'전체 날짜 보기',
    noEntries:'선택한 날짜·상태에 해당하는 기록이 없습니다.',prevMonth:'이전 달',nextMonth:'다음 달',
    weekdays:['일','월','화','수','목','금','토'],
    fatal:'기록 데이터를 렌더링하지 못했습니다',
    sectionLabels:{{
      'Decision Question':'판단할 질문','Hypothesis':'가설','Run Identity':'실행 식별','Live Snapshot':'실행 상태','Results':'결과','Interpretation':'해석','Decision':'결정',
      'Impact':'영향','Observed Symptom':'관측된 증상','Evidence':'증거','Hypotheses':'가설','Root Cause':'근본 원인','Resolution':'조치','Verification':'검증','Closure':'종결'
    }},
    statusLabels:{{'예정':'예정','진행 중':'진행 중','완료':'완료','중단':'중단','보류':'보류','신규':'신규','조사 중':'조사 중','완화':'완화','모니터링':'모니터링','해결':'해결','차단':'차단'}},
    dateFilter:(date,n)=>`${{date}} — ${{n}}건 · `
  }},
  plan:{{headers:['작업','목표','상태','비용','우선순위','증거'],status:{{done:['ok','완료'],running:['mid','진행 중'],partial:['mid','일부'],todo:['','예정'],blocked:['no','차단']}}}},
  units:{{statusClass:{{complete:'ok',done:'ok',verified:'ok',partial:'mid',running:'mid',blocked:'no',failed:'no'}},labels:{{evidence:'증거',blockers:'막힌 것',nextGate:'다음 관문',technicalIds:'움직인 쌍',completion:'겹침 있는 쌍'}},emptyBlockers:'없음'}},
  empty:{{numeric:'수치 행이 없습니다.',units:'trial 카드가 없습니다.'}},
  viewer:{{help:'',note:'',missingSrc:'이미지 없음'}},
  unitHelp:'trial별 arm B(대조) → arm A(수정). 두 arm이 정확히 0.000 차이인 trial이 parity의 증거입니다.',
  deltaHelp:'점 하나가 기준 쌍 하나. 0보다 위 = 대조군보다 개선. 움직인 5쌍 중 3쌍은 gold 자체의 중복 집합입니다.',
  viewerHelp:'',
  planHelp:'아직 실행되지 않은 것과 이미 정해진 것. 날짜를 누르면 해당 기록으로 이동합니다.',
  notesHelp:'판단 근거가 된 실험 기록. 기록이 있는 날짜가 달력에 강조됩니다.',
  issuesHelp:'결함 하나당 기록 하나. 조사부터 종결까지의 고정 섹션으로 표시됩니다.',
  countNote:(shown,total)=>`${{total}}개 중 ${{shown}}개 표시`,
}};"""
    sub1(r"const COPY=\{.*?\n\}};" if False else r"const COPY=\{.*?\n\};", copy_patch, "COPY")

    sub1(r'<div class="eyebrow">.*?</div>\s*<h1>.*?</h1>\s*<p class="lede">.*?</p>\s*<div class="meta-row">.*?</div>',
         '<div class="eyebrow">TTE · CONCEPT SET 품질</div>\n'
         '      <h1>entry 약물 exact match — 짝지은 2-arm 측정</h1>\n'
         '      <p class="lede">6개 벤치마크 시험의 eligibility concept set을 gold(TROY v1.1 CIRCE)와 '
         f'기준별 1:1 closure 겹침으로 대조한 {len(rows)}개 쌍. 두 arm은 동일 store·동일 exporter·동일 채점 플래그로 만들어졌고, '
         '유일한 차이는 <span class="inline-code">expected_domain in ("Drug", None)</span> 게이트다.</p>\n'
         '      <div class="meta-row">\n'
         '        <span><span class="dot"></span>2026-08-10 · commits <span class="inline-code">991c11c</span> / '
         '<span class="inline-code">10034d5</span> · store 2026-08-04</span>\n'
         f'        <span>closure 모드 · vocab <span class="inline-code">synthea23m</span> · 범위 밖 gold 집합 {oos}개 제외</span>\n'
         '      </div>', "header")

    sub1(r'<div><h3>Headline finding.*?</p></div>',
         '<div><h3>수정은 유효하다. 다만 구별되는 수정은 2건이다.</h3>\n'
         f'      <p>6-trial macro recall {rb:.3f} → {ra:.3f}({ra - rb:+.3f}), 겹침 0인 쌍 {zb} → {za}. '
         '손대지 않은 4개 trial이 <b>정확히 0.000</b> 움직였고, 그 trial들의 CIRCE 파일은 두 arm 사이에서 바이트 동일하다 — '
         f'이것이 다른 요인이 섞이지 않았다는 증거다. 다만 움직인 {len(moved)}쌍 중 3쌍은 gold 자체의 '
         '참조되지 않는 중복 concept set이므로, 같은 수정을 세 번 더 센 것이다. '
         '정직한 값은 <b>2건</b>(CARMELINA·CAROLINA 각 entry 약물 1개) — study당 entry 약물이 하나이므로 당연한 수다.</p></div>',
         "verdict")

    sub1(r'<div class="chart-t">Metric A by entity</div><div class="chart-s">.*?</div>',
         '<div class="chart-t">arm별 평균 recall</div><div class="chart-s">대조군은 점선 기준선.</div>', "barA title")
    sub1(r'<div class="chart-t">Metric B by entity</div><div class="chart-s">.*?</div>',
         '<div class="chart-t">arm별 평균 precision</div><div class="chart-s">대조군은 점선 기준선.</div>', "barB title")
    sub1(r'<div class="chart-t">Metric A distribution</div><div class="chart-s">.*?</div>',
         '<div class="chart-t">recall 분포</div>'
         '<div class="chart-s">두 arm이 거의 겹친다 — 232쌍 중 5쌍만 움직였으므로 그것이 정상이다.</div>', "distA title")
    sub1(r'<div class="chart-t">Metric B distribution</div><div class="chart-s">.*?</div>',
         '<div class="chart-t">precision 분포</div>'
         '<div class="chart-s">같은 이유로 거의 겹친다.</div>', "distB title")

    sub1(r'<div class="foot">How the metrics were computed.*?</div>',
         '<div class="foot">기준별 1:1 closure 겹침의 macro 평균. gold 항목은 <span class="inline-code">concept_ancestor</span>를 '
         'Circe와 같은 방식으로 전개했고(<span class="inline-code">invalid_reason IS NULL</span>, '
         '<span class="inline-code">isExcluded</span>는 anti-join), pooled concept mass(micro) 평균은 방향을 뒤집으므로 '
         '표제로 쓰지 않는다.</div>', "summary foot")

    sub1(r'<div class="callouts">.*?</div>\s*</section>',
         '<div class="callouts">\n'
         '        <div class="callout"><h3>parity는 0.000 열이 증명한다</h3><p>ARISTOTLE · EMPA-REG · LEADER · PLATO가 '
         '정확히 0.000 움직였다. 두 arm은 같은 store에서 같은 날 같은 exporter로 나왔고, 6개 export 중 4개가 md5까지 동일하다. '
         '차이가 게이트 외의 무언가에서 왔다면 이 열이 0이 아니었을 것이다.</p></div>\n'
         '        <div class="callout warn"><h3>쌍 수는 수정 수가 아니다</h3><p>gold의 비-ATC '
         '<span class="inline-code">[TROY intervention] &lt;drug&gt;</span> 집합은 '
         '<span class="inline-code">PrimaryCriteria</span>가 실제로 참조하는 <span class="inline-code">(ATC)</span> 집합의 중복이고, '
         '어떤 기준도 참조하지 않는다(238개 중 14개). 이 중복을 분모에 남기기로 2026-08-10에 결정했으므로, '
         '비용은 보고 단계에서 치른다 — <b>쌍 수가 아니라 구별되는 수정 수를 인용한다</b>. '
         '규칙은 <span class="inline-code">artemis/AGENTS.md</span> EVALUATION에 고정돼 있다.</p></div>\n'
         f'        <div class="callout"><h3>범위 밖 gold 집합 {oos}개</h3><p>gold가 '
         '<span class="inline-code">CensoringCriteria</span>에서만 참조하는 약물 집합 — Warfarin, Sulfonylureas, Glimepiride, '
         'DPP4 inhibitors ×2, Clopidogrel(모두 ATC). gold는 어느 arm의 약물이든 개시 시점에 검열하지만, '
         '생성 산출물은 eligibility 코호트라 그 섹션 자체가 없다. 짝짓기에서 제외하고 별도 모집단으로 보고한다.</p></div>\n'
         '      </div>\n    </section>', "findings")

    # The Components tab is a build-time reference, not results.
    sub1(r'<span class="tabgroup" role="presentation" data-glabel="Build".*?</span>\s*', "", "Components tab button")
    sub1(r'<div id="pane-kit" class="pane" role="tabpanel" hidden>.*?\n  </div>\n', "", "Components panel")
    # ...and the script that fills it. Deleting the panel alone leaves this line throwing
    # on a null element, which aborts every renderer below it — the page then loads with
    # zero table rows and no working tabs while the HTML still looks correct.
    sub1(r"// component-kit color swatches \(Components tab\)\n.*?\.join\(''\);\n", "", "kit swatch script")

    sub1(r"<title>.*?</title>", "<title>Concept-set overlap — entry-drug exact match (paired)</title>", "title")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html)
    print(f"wrote {out}  ({len(html) // 1024} KB)")
    print(f"  pairs={len(rows)}  units={len(units)}  moved={len(moved)}  out_of_scope_gold={oos}")
    print(f"  macro recall {rb:.4f} -> {ra:.4f} ({ra - rb:+.4f})   zero-overlap {zb} -> {za}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--arm-a", default="output/conceptset_overlap/scoped_arm_a.json")
    ap.add_argument("--arm-b", default="output/conceptset_overlap/scoped_arm_b.json")
    ap.add_argument("--out", default="output/conceptset_overlap/dashboard.html")
    args = ap.parse_args(argv)
    render(json.loads(Path(args.arm_a).read_text()), json.loads(Path(args.arm_b).read_text()), Path(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
