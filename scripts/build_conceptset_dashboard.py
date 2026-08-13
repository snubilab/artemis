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
        --gemma output/conceptset_overlap/scoped_gemma.json \
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
                + (f". gold 자체의 중복 {len(dup)}쌍이 같은 수정을 다시 센다." if dup else ".")
            )
        else:
            status, verdict = "complete", (
                f"recall {ra:.3f}, precision {qa:.3f}. 두 arm 차이가 **정확히 0.000**이다. "
                "이 trial의 CIRCE 파일은 두 arm 사이에서 바이트 동일하고, 그것이 arm parity의 증거다."
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
                    + (f" ({', '.join(s['name'] for s in oos)})" if oos else " (없음)"),
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


# Model routing joined the board on 2026-08-10: the concept sets on this page were
# produced by an LLM, so "which model actually ran" and "did its prompt fit the served
# window" are links in this argument, not neighbouring infrastructure. A backlog that
# lists only the concept-set work hides that those links were broken while the numbers
# above were being read.
PLAN_GROUPS = ("Concept-set quality", "Model routing & measurement integrity")


def build_plan(note_dates: set[str]) -> list[dict]:
    """Reuse the rows already curated on the omx_wiki plan board.

    ``note_dates`` is the set of dates this page's notes pane actually renders. The board
    is shared with other dashboards, so a row can carry a link to a note that exists there
    and not here — clicking it would filter the calendar to an empty day, and the renderer
    treats the dangling reference as fatal. Dropping the unresolvable link is the fix; the
    row keeps its evidence requirement through the fallback below.
    """
    if not WIKI_PLAN.exists():
        return []
    rows = [
        dict(r) for r in json.loads(WIKI_PLAN.read_text())
        if r.get("group", "").startswith(PLAN_GROUPS)
    ]
    for r in rows:
        r["links"] = [
            l for l in (r.get("links") or [])
            if l.get("pane") != "pane-notes" or l.get("date") in note_dates
        ]
        # planView refuses a done/running row with nothing to point at, which is the right
        # rule: a finished row with no evidence is the one a reader trusts most.
        if r["status"] in ("done", "running", "partial") and not r["links"]:
            r["links"] = [{"pane": "pane-notes", "date": "2026-08-09",
                           "label": "짝지은 2-arm 측정"}]
        if not r["links"]:
            del r["links"]
    return rows


def build_notes(a: dict, b: dict, gemma: dict, rows: list[dict]) -> list[dict]:
    ra, rb = _macro(a, "recall_mean"), _macro(b, "recall_mean")
    moved = [r for r in rows if abs(r["fix_rec"] - r["ctl_rec"]) > 1e-9]
    return [
        {
            "date": "2026-08-09",
            "time": "23:10",
            "status": "완료",
            "title": "entry 약물 exact match의 실제 효과",
            "key": (
                f"수정은 유효하지만 **구별되는 수정은 2건**이다. macro recall {rb:.3f} → {ra:.3f}, "
                f"겹침 0인 쌍 {_zero(b)} → {_zero(a)}. 움직인 {len(moved)}쌍 가운데 3쌍은 gold 자체의 "
                "참조되지 않는 중복이라, 같은 수정을 두 번 센 것이다."
            ),
            "sections": [
                {"h": "Decision Question", "items": [
                    "`expected_domain in (\"Drug\", None)`으로 게이트를 넓힌 991c11c가 gold 대비 concept set 품질을 실제로 올리는가, "
                    "그리고 그 변화가 게이트에 귀속되는가."]},
                {"h": "Hypothesis", "items": [
                    "linagliptin 쌍이 0.0 → ~1.0으로 가고 나머지는 그대로, 6-trial macro recall은 약 +0.03. "
                    "이보다 크게 움직이면 게이트 말고 다른 것이 바뀐 셈이니 숫자를 믿지 않는다. 채점하기 전에 적어둔 예측이다."]},
                {"h": "Run Identity", "items": [
                    "arm A = `output/circe_arm_a`, arm B = `output/circe_arm_b`. 둘 다 같은 store "
                    "`tmp/tte_six_deliver/studies.json` (2026-08-04)에서 같은 exporter로 같은 날 만들었다.",
                    "채점: `scripts/conceptset_overlap_eval.py --mode closure --vocab-schema synthea23m`, 두 arm 동일 플래그.",
                    "arm A는 `scripts/rebuild_entry_concept_sets.py`로 만들었고, 입력 store는 건드리지 않는다."]},
                {"h": "Live Snapshot", "items": [
                    "두 arm 모두 exit 0. 6개 export 파일 중 4개가 바이트 동일하고 CARMELINA·CAROLINA만 다르다. md5로 확인했다.",
                    "전면 재생성은 기각했다. 게이트는 study당 concept set 1개만 지나가므로, 6개 trial을 다시 만들면 "
                    "변하지도 않을 ~370개를 새로 굽는 동안 store 생성 이후의 커밋이 전부 섞여 귀속이 무너진다."]},
                {"h": "Results", "table": {
                    "head": ["trial", "recall B", "recall A", "Δ"],
                    "rows": [[t["trial"],
                              f"{{:.3f}}".format([x for x in b["trials"] if x["trial"] == t["trial"]][0]["per_criterion"]["recall_mean"]),
                              f"{t['per_criterion']['recall_mean']:.3f}",
                              "**{:+.3f}**".format(t["per_criterion"]["recall_mean"] - [x for x in b["trials"] if x["trial"] == t["trial"]][0]["per_criterion"]["recall_mean"])]
                             for t in a["trials"]] + [["**6-trial macro**", f"**{rb:.3f}**", f"**{ra:.3f}**", f"**{ra - rb:+.3f}**"]]},
                    "items": ["손대지 않은 4개 trial은 정확히 0.000 움직였고, 그것이 parity의 증거다."]},
                {"h": "Interpretation", "items": [
                    "예측이 그대로 맞았다(+0.030 포함). 다만 쌍 수는 수정 수가 아니다. gold의 비-ATC "
                    "`[TROY intervention] <drug>` 집합은 `PrimaryCriteria`가 참조하는 `(ATC)` 집합의 중복이고 "
                    "어떤 기준도 이것을 참조하지 않는다. 238개 가운데 14개가 그런 고아다.",
                    "귀속의 폭은 좁다. 그 폭을 2026-08-10에 쟀다"
                    "(`docs/experiments/2026-08-10_exact_vs_embedding_attribution.md`). "
                    "유효 테스트된 entry seed 5개 중 3개(liraglutide/ticagrelor/apixaban)는 임베딩이 이미 정답을 냈고, "
                    "exact match가 답을 바꾼 것은 linagliptin 하나뿐이다(시험 2개). 검색기가 sitagliptin을 1위로 주고 "
                    "top-20에 linagliptin이 없으며, 리랭커는 후보를 전부 기각(`0 selected`)했는데 "
                    "그 기각을 `Force-included Top-1` 폴백이 덮는다."]},
                {"h": "Decision", "items": [
                    "채택. 991c11c를 유지한다. 보고 규칙은 `AGENTS.md` EVALUATION에 고정했다. 쌍 수가 아니라 구별되는 수정 수를 인용한다.",
                    "다음: `glimepiride` sourceText 한정어 탈락, `BI 10773` 개발코드 경로."]},
            ],
        },
        {
            "date": "2026-08-10",
            "time": "16:40",
            "status": "완료",
            "title": "exact match가 임베딩보다 나은가 (entry seed 전수)",
            "key": (
                "**\"임베딩이 고유명사에 약하다\"는 일반 명제는 기각됐다.** 유효 테스트된 seed 5개 중 "
                "3개는 임베딩이 이미 정답을 냈고, exact match가 답을 바꾼 것은 linagliptin 하나다. "
                "리랭커를 gpt-4o에서 gemma로 바꿔도 결과가 같아서, 결론은 리랭커에 기대지 않는다."
            ),
            "sections": [
                {"h": "Decision Question", "items": [
                    "exact RxNorm-Ingredient 매칭을 유지할 근거가 있는가. 임베딩 경로가 약물 고유명사에서 "
                    "실제로 실패하는가, 아니면 이미 맞히고 있어 게이트가 필요 없는가."]},
                {"h": "Hypothesis", "items": [
                    "기록된 반증 근거가 이미 있었다. apixaban·liraglutide·ticagrelor는 임베딩이 맞혔다. "
                    "그래서 일반 명제는 성립하지 않고 소수 seed에서만 갈릴 것으로 예측했다. "
                    "여러 seed가 갈리면 다른 것이 함께 바뀐 셈이니 숫자를 믿지 않는다."]},
                {"h": "Run Identity", "items": [
                    "`_recommend_seeded_concept_set(seed, expected_domain=None)`를 seed마다 exact ON 1회, "
                    "OFF 3회 호출했다. 토글은 `ARTEMIS_DISABLE_EXACT_INGREDIENT_MATCH`이고 게이트는 `tte_service.py:6176`에 있다.",
                    "컨테이너에서 실행했다. `.venv`에는 `torch`가 없어 MedCPT 벡터 검색이 죽고, ablate할 대상 자체가 사라진다.",
                    "양쪽 arm 모두 `CRITERION_CACHE_ENABLED=false`로 뒀다. 캐시는 exact보다 뒤에 있어서 과거 exact 결과를 되돌려준다.",
                    "2회 실행했다. 리랭커 gpt-4o(OpenRouter), 그다음 gemma-4-E4B-it(vLLM). 후자는 "
                    "`resolved_model`을 로그에 남겼고 LLM 호출 19건이 전부 vLLM, OpenRouter는 0건이다."]},
                {"h": "Live Snapshot", "items": [
                    "24/24 호출을 마쳤고 두 번 모두 exit 0. 대조군은 6개 seed 전부 3회 반복이 같다. 컨테이너에서는 결정적이다.",
                    "`.venv`에서 같은 대조군을 5회 돌리면 서로 겹치지 않는 5개 결과가 나온다(모든 실행 공통 개념 0개). "
                    "임베딩이 죽어 lexical 후보 10개를 LLM이 마음대로 고르기 때문이고, 이 환경에서 잰 숫자는 잡음이다."]},
                {"h": "Results", "table": {
                    "head": ["seed", "exact ON", "대조군 (임베딩) ×3", "판정"],
                    "rows": [
                        ["liraglutide", "liraglutide (40170911)", "동일 ×3", "임베딩이 이미 맞힘"],
                        ["ticagrelor", "ticagrelor (40241186)", "동일 ×3", "임베딩이 이미 맞힘"],
                        ["apixaban", "apixaban (43013024)", "동일 ×3", "임베딩이 이미 맞힘"],
                        ["`BI 10773`", "CHF-6366 .beta.-2 metabolite (1254065)", "동일 ×3",
                         "**테스트되지 않음** (`alias_candidates` 미전달)"],
                        ["Linagliptin", "linagliptin (40239216)", "**sitagliptin (1580747)** ×3", "**exact match가 가름**"],
                        ["linagliptin", "linagliptin (40239216)", "**sitagliptin (1580747)** ×3", "**exact match가 가름**"],
                    ]},
                    "items": [
                        "리랭커를 바꾼 뒤에도 반환 개념이 전부 같았다. 2/6, 같은 개념, 3/3 결정적.",
                        "`BI 10773` 행은 MeSH 별칭 경로를 두고는 아무것도 말해주지 않는다. 프로브가 "
                        "`alias_candidates`를 넘기지 않아 양쪽 arm 모두 임베딩으로 떨어졌다."]},
                {"h": "Interpretation", "items": [
                    "기전이 로그에 3단으로 남았다. 검색기가 `linagliptin` 질의에 sitagliptin을 1위로 주고 "
                    "(top-20에 linagliptin 없음, 같은 DPP-4 계열이 벡터 공간 이웃), 리랭커가 후보를 전부 기각하고"
                    "(`reranker → 0 selected`), 그 위에서 `Force-included Top-1` 폴백이 그 기각을 덮는다.",
                    "결함은 임베딩 하나로 끝나지 않는다. \"매치 없음\"을 \"자신 있게 틀림\"으로 바꾸는 폴백이 겹쳤다. "
                    "리랭커를 바꿔도 결과가 같은 이유도 여기에 있다. 후보에 정답이 없으면 어떤 모델도 고를 수 없다."]},
                {"h": "Decision", "items": [
                    "exact match는 유지한다. 다만 근거를 \"임베딩이 고유명사에 약해서\"에서 성분명 1건을 받치는 "
                    "안전망으로 좁혀 적는다. 대시보드와 실험 문서의 표현도 그에 맞게 고쳤다.",
                    "다음: `Force-included Top-1`을 끄면 오답이 무답으로 바뀌는지 확인한다. 그렇다면 고칠 대상은 폴백이다."]},
            ],
        },
    ] + _build_gemma_remap_note(a, b, gemma) + _build_similarity_floor_note()


def _build_similarity_floor_note() -> list[dict]:
    """2026-08-11: can a retriever distance threshold separate real criteria from noise?

    Standalone probe against artemis-api's retriever.search — does not depend on the
    arm A/B/gemma reports, unlike the two notes above."""
    return [
        {
            "date": "2026-08-11",
            "time": "01:30",
            "status": "완료",
            "title": "유사도 거리 임계값이 진짜 기준과 무의미한 질의를 가르는가",
            "key": (
                "**아니다 — 두 구간이 겹쳐서 단일 임계값이 통하지 않는다.** 무의미한 질의 "
                "`zzzz not a real thing at all`(54.750)이 실제 기준 `Acute coronary syndrome`"
                "(59.457)보다 검색기에 더 가깝다."
            ),
            "sections": [
                {"h": "Decision Question", "items": [
                    "retriever의 top-1 벡터 거리에 임계값을 그어 실제 임상 용어와 무의미한 질의를 가를 수 있는가."]},
                {"h": "Hypothesis", "items": [
                    "실제 임상 용어는 거리 분포가 낮은 쪽에, 무의미한 문자열은 높은 쪽에 몰려 두 구간 사이에 여백이 "
                    "있어야 임계값이 의미가 있다. 구간이 겹치면 이 접근은 기각된다."]},
                {"h": "Run Identity", "items": [
                    "`artemis-api` 컨테이너 안에서 `retriever.search(term, domain_hint=\"Condition\")`를 호출해 "
                    "top-1 벡터 거리(낮을수록 가까움)를 읽었다.",
                    "실제 임상 용어 6개, 무의미한 문자열 4개를 같은 방식으로 질의했다."]},
                {"h": "Live Snapshot", "items": [
                    "10건 모두 결과를 반환했다(예외 없음). 실제 용어와 무의미한 문자열 모두 top-1 결과가 존재한다 — "
                    "벡터 검색 자체는 '못 찾음'을 표현할 방법이 없다."]},
                {"h": "Results",
                 "table": {
                     "head": ["실제 임상 용어", "top-1 거리", "top-1 개념"],
                     "rows": [
                         ["Stroke", "38.640", "Stroke volume"],
                         ["Atrial fibrillation", "42.711", "Atrial fibrillation"],
                         ["Type 2 diabetes mellitus", "53.001", "Type 2 diabetes mellitus with ulcer…"],
                         ["Chronic heart failure", "54.369", "Chronic heart failure"],
                         ["Chronic kidney disease", "55.338", "Chronic kidney disease"],
                         ["Acute coronary syndrome", "59.457", "Acute coronary syndrome"],
                     ],
                 },
                 "items": ["실제 임상 용어 6개의 top-1 거리 범위는 38.640–59.457이다."],
                 "blocks": [
                     {
                         "h": "무의미한 문자열의 top-1 거리",
                         "table": {
                             "head": ["무의미한 질의", "top-1 거리", "top-1 개념"],
                             "rows": [
                                 ["zzzz not a real thing at all", "54.750", "metolazone 5 MG Oral Tablet [Zarox…"],
                                 ["asdfgh qwerty zxcvbn", "65.540", "eculizumab-aagh 10 MG/ML Injection"],
                                 ["qqzzxx nonexistent clinical term", "89.886", "Non-Q wave myocardial infarction"],
                                 ["wibble wobble frobnicate", "97.768", "Carbuncle of perineum"],
                             ],
                         },
                         "items": ["무의미한 문자열 4개의 top-1 거리 범위는 54.750–97.768이다."],
                     }
                 ]},
                {"h": "Interpretation", "items": [
                    "실제 38.6–59.5, 무의미 54.8–97.8로 두 구간이 겹친다. `zzzz not a real thing at all`(54.750)이 "
                    "실제 기준 `Acute coronary syndrome`(59.457)보다 검색기에 더 가깝다. 60 근처에 임계값을 그으면 "
                    "무의미한 질의를 통과시키면서 실제 기준 하나를 버리게 된다."]},
                {"h": "Decision", "items": [
                    "기각. 단일 거리 임계값을 매핑 파이프라인의 관련성 필터로 채택하지 않는다.",
                    "다음: 리랭커에 던지는 질문의 모양을 바꾼다 — '이 후보 중 어느 것이 최선인가'가 아니라 "
                    "'이 후보 중 질의와 같은 뜻인 것이 있는가'를 명시적으로 묻는다."]},
            ],
        }
    ]


# The gemma re-map compares against arm A only (both are post-entry-drug-fix), and the
# per-trial "changed sets" counts come from a direct criterion-level diff of the two
# regenerated structured expressions — a wider population than the 232 gold-paired rows
# the eval report scores, so they cannot be re-derived from scoped_*.json alone and are
# recorded here as measured facts. Δrecall/Δprecision ARE re-derived from the reports.
_GEMMA_CHANGED_SETS = {
    "CAROLINA": (17, 70),
    "LEADER": (10, 54),
    "EMPA-REG OUTCOME": (13, 68),
    "ARISTOTLE": (12, 39),
    "PLATO": (18, 86),
    "CARMELINA": (3, 28),
}


def _build_gemma_remap_note(a: dict, b: dict, gemma: dict) -> list[dict]:
    rb, ra, rg = _macro(b, "recall_mean"), _macro(a, "recall_mean"), _macro(gemma, "recall_mean")
    qb, qa, qg = _macro(b, "precision_mean"), _macro(a, "precision_mean"), _macro(gemma, "precision_mean")
    zb, za, zg = _zero(b), _zero(a), _zero(gemma)
    changed_total = sum(c for c, _ in _GEMMA_CHANGED_SETS.values())
    all_total = sum(n for _, n in _GEMMA_CHANGED_SETS.values())
    pct = round(100 * changed_total / all_total)

    per_trial = {t["trial"]: t["per_criterion"] for t in a["trials"]}
    per_trial_g = {t["trial"]: t["per_criterion"] for t in gemma["trials"]}
    trial_rows = []
    for trial, (changed, total) in _GEMMA_CHANGED_SETS.items():
        d_rec = per_trial_g[trial]["recall_mean"] - per_trial[trial]["recall_mean"]
        d_prec = per_trial_g[trial]["precision_mean"] - per_trial[trial]["precision_mean"]
        trial_rows.append([trial, f"{changed}/{total}", f"{d_rec:+.3f}", f"{d_prec:+.3f}"])

    return [
        {
            "date": "2026-08-10",
            "time": "19:30",
            "status": "완료",
            "title": "매핑 모델을 gemma로 통째로 바꿔 6개 시험을 재매핑",
            "key": (
                f"concept set {all_total}개 중 {changed_total}개({pct}%)가 바뀌었는데도 "
                f"6-trial macro recall {ra:.3f} → {rg:.3f}, zero-overlap 쌍 {za} → {zg}로 "
                "**arm A와 사실상 같다.** 이 지표에서 매핑 모델은 병목이 아니다."
            ),
            "sections": [
                {"h": "Decision Question", "items": [
                    "concept-set 품질의 병목이 매핑에 쓰는 LLM 자체인가. 매핑 모델을 OpenAI 계열에서 로컬 "
                    "`vllm/google/gemma-4-E4B-it`로 바꾸면 gold 대비 macro recall/precision이 움직이는가."]},
                {"h": "Hypothesis", "items": [
                    "모델 교체가 개별 concept set의 구성은 흔들더라도, 6-trial macro recall/precision은 arm A 대비 "
                    "크게 움직이지 않을 것으로 예상한다. 매핑 단계의 모델이 이 지표의 주요 병목이라면 이 예측은 기각된다."]},
                {"h": "Run Identity", "items": [
                    "`regenerate_structured_expression.py --apply`를 `tmp/tte_six_deliver/studies.json`(2026-08-04)의 "
                    "사본 `/app/tmp/tte_vllm_remap2/studies.json`에 적용했다. `artemis-api` 컨테이너 안에서 돌렸고, "
                    "모델은 `vllm/google/gemma-4-E4B-it`, vLLM 서빙은 `--max-model-len 32768`이다.",
                    "채점은 arm A/B와 동일 플래그: `scripts/conceptset_overlap_eval.py --mode closure "
                    "--vocab-schema synthea23m` → `output/conceptset_overlap/scoped_gemma.json`.",
                    "이전 8,192-컨텍스트 시도(176/268 기준이 critic 400 뒤 seed로 조용히 되돌아간 것)는 무효로 처리하고 "
                    "증거로만 남겼다. 위 'critic 프롬프트가 서빙 컨텍스트를 넘겨' 이슈를 참고."]},
                {"h": "Live Snapshot", "items": [
                    "6/6 study를 기록했다. study 1(LEADER)은 vLLM 재기동 전에 이미 저장됐고, 재기동 뒤 "
                    "`--studies 2,3,8,9,10`으로 이어 돌려 resume 로그가 `written: 5 studies`로 끝났다.",
                    "두 로그(`output/remap_gemma_32k.log`, `output/remap_gemma_32k_resume.log`) 모두 "
                    "`Critic] Evaluation failed` 0건, `traceback` 0건이고, manifest의 HARD CHECK를 통과했다"
                    "(`output/remap_gemma_32k.manifest.txt`)."]},
                {"h": "Results",
                 "table": {
                     "head": ["arm", "macro recall", "macro precision", "zero-overlap 쌍"],
                     "rows": [
                         ["arm B", f"{rb:.3f}", f"{qb:.3f}", str(zb)],
                         ["arm A", f"{ra:.3f}", f"{qa:.3f}", str(za)],
                         ["gemma 전체 재매핑", f"**{rg:.3f}**", f"**{qg:.3f}**", f"**{zg}**"],
                     ],
                 },
                 "items": [
                     f"gemma는 zero-overlap 쌍 수까지 arm A와 정확히 같다({za} = {zg})."
                 ],
                 "blocks": [
                     {
                         "h": "trial별로 바뀐 concept set 수와 점수 이동 (gemma vs arm A)",
                         "table": {
                             "head": ["trial", "바뀐 concept set", "Δrecall", "Δprecision"],
                             "rows": trial_rows,
                         },
                         "items": [
                             f"{all_total}개 concept set 중 {changed_total}개({pct}%)가 바뀌었지만 macro 점수는 움직이지 않았다.",
                             "'바뀐 concept set' 수는 재매핑된 두 study의 structured_expression을 criterion 단위로 직접 "
                             "비교한 값이다. gold와 짝지어 채점한 232개 쌍(위 표)보다 넓은 모집단이라 `scoped_*.json`만으로는 "
                             "다시 뽑아낼 수 없다. Δrecall/Δprecision은 `scoped_arm_a.json`과 `scoped_gemma.json`의 "
                             "`per_criterion`에서 그대로 다시 계산했다.",
                         ],
                     }
                 ]},
                {"h": "Interpretation", "items": [
                    f"CAROLINA만 recall·precision이 함께 내려갔고({trial_rows[0][2]}/{trial_rows[0][3]}), 나머지 5개 "
                    "trial은 ±0.01 안쪽에서 흩어지며 방향도 trial마다 다르다(LEADER는 recall이 오르고 precision은 "
                    "내려가는 식). 345개 중 73개(21%) concept set이 실제로 바뀌었는데 macro 점수가 그대로인 것은 "
                    "모순이 아니다. 바뀐 것들이 서로 다른 방향으로 상쇄됐다.",
                    "매핑 모델은 이 지표의 병목이 아니다. 남은 gap(macro recall 0.598, 1.0까지 약 0.4)은 "
                    "모델을 바꿔서 줄어들지 않는다. 상류에, 곧 gold 정의와 criterion sourceText 정규화, PHOEBE 확장처럼 "
                    "위에 기록해둔 이슈들에 있다.",
                    "경계가 하나 있다. 이 비교는 모델만 바뀐 순수 대조군이 아니다. arm A의 non-entry concept set은 "
                    "2026-08-04 store 빌드 기준이라, gemma 재매핑은 그 이후의 모든 커밋(entry-drug 게이트, censoring "
                    "제외 등) 위에서 돌았다. gemma-vs-A 델타에는 모델 교체 효과와 그 사이 코드 변경 효과가 함께 들어 있다."]},
                {"h": "Decision", "items": [
                    "채택. plan board의 'Re-map all six studies on the local model' 행을 done으로 닫는다. "
                    "매핑 모델 교체는 이 지표 기준으로 더 파볼 우선순위가 아니다.",
                    "다음: 남은 zero-overlap 원인(criterion sourceText 관계어, PLATO description/sourceText 불일치, "
                    "`Force-included Top-1` 폴백)을 계속 좇는다. 'Concept-set quality' 그룹에 남은 todo 항목이다."]},
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
                "한정어를 잃은 기준은 모두 이름만으로 엉뚱한 gold 집합과 짝지어질 수 있다."]},
            {"h": "Observed Symptom", "items": [
                "저장된 concept set 이름이 `glimepiride`이고 내용은 Condition 개념 3개 "
                "(`Poisoning caused by sulfonylurea`, `Hypoglycemic event due to diabetes`, `Drug-induced hypoglycemia`)."]},
            {"h": "Evidence", "items": [
                "기준 원문: description = \"Hypersensitivity to investigational product or glimepiride\", domain = `Condition`, sourceText = `glimepiride`.",
                "저장된 `sourceText`는 잘린 원문이 아니라 Agent 1이 정규화한 `entity_text`다. 덮어쓰는 지점은 "
                "`_criterion_dict_from_ir_item` (`tte_service.py:9692`)의 `source_text = entity_text`이고, "
                "축자 원문 `Criteria.source_text` (`ir.py:87`)는 읽히지도 않는다. 18MB store 전체에 `\"source_text\"`가 0건이다.",
                "`sourceText`는 매핑 쿼리의 1순위 입력이다 (`tte_service.py:4474`, `:5753`, `api/tte.py:259` 모두 "
                "`sourceText or description`)."]},
            {"h": "Hypotheses", "items": [
                "기각. \"축자 원문을 복원하면 된다\"는 방향은 회귀다. store 653개 기준 중 `sourceText`가 description과 "
                "다른 것이 429개(더 짧은 것 292개)이고, `eGFR < 60 (MDRD)` → `eGFR`처럼 벗기는 게 맞는 경우가 대부분이다.",
                "domain = `Condition`은 방어할 수 있다. 과민반응은 실제로 Condition이고, 매퍼는 충실히 동작했다."]},
            {"h": "Root Cause", "items": [
                "확정. Agent 1이 한정어가 아니라 관계어를 벗겼다. `\"Asymptomatic cardiac ischemia\" → \"cardiac ischemia\"`는 "
                "옳지만 `\"Hypersensitivity to X\" → \"X\"`는 알레르기를 투약으로 바꾼다. 필드는 그대로 있고 이름만 잘못 붙었다.",
                "범위는 1건이다. 관계어 스캔에서 6개 시험 통틀어 5건이 걸렸고 그중 3건(`Contraindication due to <질환>`)은 "
                "벗기는 게 맞으며, 1건은 별개의 PLATO 불일치라 남는 것이 glimepiride 하나다."]},
            {"h": "Resolution", "items": [
                "해당 없음. 코드는 고치지 않았다. 다만 하면 안 되는 것이 무엇인지는 측정해뒀다. domain 게이트를 풀어 "
                "성분 매칭을 강제하면 `Calcitonin`, `Creatinine`, `Glucose`, `glucose`(분석물 이름을 가진 Measurement 기준)가 "
                "약물 노출로 잘못 분류된다."]},
            {"h": "Verification", "items": [
                "domain 게이트를 유지한 채로 남는다. 게이트야말로 이 1건을 가려내는 신호다. "
                "domain이 `Condition`인데 entity가 Drug 성분이면 관계어가 탈락한 것이다."]},
            {"h": "Closure", "items": [
                "조사는 종결한다. 진단은 확정했고 코드 수정은 보류한다. 6개 시험에서 얻을 것이 1건이라 값어치가 얇고, "
                "이 문서가 원래 제안했던 축자 복원은 429건을 흔든다."]},
        ],
    },
    {
        "date": "2026-08-10", "status": "완화",
        "title": "개발코드 `BI 10773`이 무관한 대사체로 매핑된다",
        "key": "EMPA-REG의 entry 약물이 `1254065 CHF-6366 .beta.-2 metabolite`로 해석된다. empagliflozin이 아니다. "
               "별칭 수정은 들어갔지만 **수집 경로에서만 살아 있고**, 저장된 스터디를 다시 매핑할 때는 발동하지 않는다.",
        "sections": [
            {"h": "Impact", "items": [
                "EMPA-REG OUTCOME의 entry 약물 concept set 전체가 잘못된 물질이다. 2026-08-09 이전 어떤 기록에도 없던 결함."]},
            {"h": "Observed Symptom", "items": [
                "`targetCohortName` = `BI 10773` → 저장된 concept set id=1 = `1254065 'CHF-6366 .beta.-2 metabolite'`."]},
            {"h": "Evidence", "items": [
                "`BI 10773`은 empagliflozin의 개발코드다. RxNorm Ingredient에 그 이름을 가진 개념이 없어 "
                "`_exact_ingredient_mapping`이 `None`을 반환하고 임베딩 경로로 정상 fall-through한다. 그 임베딩 답이 틀렸을 뿐이다.",
                "다른 5개 trial의 entry 약물(apixaban, liraglutide, ticagrelor, linagliptin ×2)은 모두 정확히 해석된다."]},
            {"h": "Hypotheses", "items": [
                "개발코드·동의어를 정식 성분명으로 먼저 해석하는 경로가 필요하다. 후보: RxNorm 동의어 테이블, 또는 시험 메타데이터의 개입 약물명."]},
            {"h": "Root Cause", "items": [
                "확정. 개발코드는 어휘 안에서 풀리지 않는다. `BI 10773`은 630만 개념 중 0건이고 "
                "empagliflozin 성분에는 동의어 행이 0개다. 답은 어휘가 아니라 시험 기록에 있었다."]},
            {"h": "Resolution", "items": [
                "커밋 `7837274`. `_alias_ingredient_mapping` (`tte_service.py:5882`)이 시험의 "
                "`derivedSection.interventionBrowseModule.meshes`(NLM 파생 MeSH 대표어)로 시드를 해석한다. "
                "스폰서가 쓴 모든 필드는 `BI 10773`인데 그 필드만 `empagliflozin`이다.",
                "MeSH는 RxNorm과 다른 어휘라서 별칭도 같은 ingredient 검사를 통과해야 하고, "
                "정확히 하나만 통과할 때 채택한다. 둘이면 모호한 시험이니 추측하지 않고 임베딩으로 넘긴다."]},
            {"h": "Verification", "items": [
                "6개 시험의 MeSH 용어 9개 전부가 유일 RxNorm 성분으로 해석된다. 별칭 해석 로직 자체는 맞다.",
                "그런데 산출물은 바뀌지 않았다. 2026-08-10 전면 재매핑을 production 매퍼로 거친 뒤에도 "
                "EMPA-REG의 저장된 entry concept set은 여전히 `1254065 CHF-6366 .beta.-2 metabolite`, 재매핑 전과 같다.",
                "경로를 끝까지 따라가면 이유가 나온다. 별칭은 `tte_service.py:3443`에서 "
                "`eligibility[\"_interventionAliases\"]`로 수집 중 메모리에만 기록되고 `4381`에서 `pop`으로 소비된다. "
                "store의 6개 스터디 모두 이 키가 없다. `_recommend_seeded_concept_set` 호출 지점 8곳 중 "
                "`alias_candidates`를 넘기는 곳은 `4395` 하나뿐이다.",
                "그래서 store에서 다시 매핑하는 경로(`regenerate_structured_expression.py`, re-recommend API)에는 "
                "넘길 별칭이 애초에 없다. 2026-08-10 귀속 실험이 이 행을 \"프로브가 인자를 안 넘겨서\"로 적었는데 "
                "절반만 맞았다. 넘길 값이 저장돼 있지 않다."]},
            {"h": "Closure", "items": [
                "미해결. 수집 경로에서만 동작한다. 종결하려면 별칭이 store에 남아야 하고(`pop` 대신 보존), "
                "재매핑 경로가 그것을 읽어 넘겨야 한다. 그 뒤 EMPA-REG entry가 empagliflozin으로 바뀌는지로 확인한다."]},
        ],
    },
    {
        "date": "2026-08-10", "status": "모니터링",
        "title": "critic 프롬프트가 서빙 컨텍스트를 넘겨 268개 중 176개가 조용히 seed로 되돌아갔다",
        "key": "gemma가 8,192 컨텍스트로 서빙 중인데 critic 프롬프트가 넘쳐 400을 받았고, 그 실패가 삼켜져 "
               "KG 확장분을 버린 축소된 개념집합이 남았다. 로그는 `written: 5 studies`로 성공을 찍었다.",
        "sections": [
            {"h": "Impact", "items": [
                "전 스터디 재매핑 1회분이 통째로 무효다. 268개 기준 중 176개(66%)가 영향받았다.",
                "축소된 집합을 보고 \"gemma가 보수적인 모델\"이라고 잘못 해석해 사용자에게 보고했다. "
                "측정 결과가 아니라 고장이었다. 그대로 채점했다면 모델 비교 결론이 뒤집혔을 것이다."]},
            {"h": "Observed Symptom", "items": [
                "개념집합이 일관되게 줄었다: Albuminuria 15→3, CABG 8→2, Insulin dose change 9→4, ACS 4→1.",
                "스크립트는 정상 종료하며 `written: 5 studies`를 출력했다."]},
            {"h": "Evidence", "table": {
                "head": ["항목", "값"],
                "rows": [
                    ["`Critic] Evaluation failed`", "176"],
                    ["`maximum context length is 8192`", "176"],
                    ["처리한 기준", "268"],
                    ["서버 설정", "`--max-model-len 8192`"],
                    ["모델이 지원하는 컨텍스트", "131,072 (`max_position_embeddings`)"],
                    ["요청 출력 예약", "`max_tokens=4096` (`critic.py:297`, `:467`)"],
                ]},
                "items": [
                    "오류 본문: `you requested 4096 output tokens and your prompt contains at least 4097 "
                    "input tokens, for a total of at least 8193`.",
                    "삼켜지는 지점이 로그에 연속으로 남는다. `[Critic] Evaluation failed: 400` 바로 다음 줄이 "
                    "`Critic selected: 3 from 59 candidates`이고, KG로 확장한 56개가 버려진다."]},
            {"h": "Hypotheses", "items": [
                "기각. \"gemma가 보수적이라 적게 고른다\"는 설명은 성립하지 않는다. critic이 실행조차 되지 않았으니 모델 판단이 아니다.",
                "채택. 출력 예약 4,096이 8,192 창의 절반을 먹어 입력에 4,096만 남고, 후보 59~90개가 그것을 넘는다."]},
            {"h": "Root Cause", "items": [
                "구조적 원인은 스키마다. `CriticResult`가 후보 하나당 `CriticSelection` 엔트리"
                "(`concept_id`, `relevant`, 자유서술 `reasoning`, `confidence` …)를 내므로 "
                "출력 길이가 후보 수에 비례한다. 그래서 `max_tokens=4096`이 필요해지고, 8,192 창에서는 반이 사라진다.",
                "설정 쪽 원인은 서버가 모델 능력(131,072)의 6%인 8,192로 떠 있었다는 점이다."]},
            {"h": "Resolution", "items": [
                "vLLM을 `--max-model-len 32768`로 재기동했다(GB10이므로 `env -u PYTHONPATH -u PYTHONHOME`). "
                "입력 여유가 4,096 → 28,672가 된다.",
                "`max_tokens`를 줄이는 쪽은 기각했다. 후보 90개면 출력이 3,600토큰대라, 줄이면 JSON이 잘려 "
                "파싱이 깨지는 다른 실패로 바뀐다. 4,096은 스키마에 맞게 잡힌 값이다.",
                "오염된 산출물은 채점하지 않고 `/app/tmp/tte_vllm_remap/`에 증거로 남겼다. 재실행은 새 디렉터리에서 "
                "시작해 criterion 캐시까지 새로 만든다. 캐시 키가 `LLM_MODEL`이라 같은 모델이면 고장난 결과를 그대로 돌려준다."]},
            {"h": "Verification", "items": [
                "양성 대조: 약 5k 토큰 입력 + 4,096 출력 예약이 통과한다. 8,192에서는 즉시 400이던 조합이다.",
                "재실행 중 `Critic] Evaluation failed`는 0건을 유지했고, 같은 기준이 `3 concepts`(seed 복귀)에서 "
                "`Selected 10/53 concepts, 10 from 59 candidates`로 바뀌었다.",
                "KV 캐시 사용률은 5.3%다. 컨텍스트를 4배로 늘린 대가가 이 워크로드에서는 없다."]},
            {"h": "Closure", "items": [
                "미해결. 재매핑이 아직 진행 중이라 전 구간 0건을 확인하지 못했다. 끝나면 "
                "`rg -c 'Critic] Evaluation failed' output/remap_gemma_32k.log`가 0이어야 종결한다.",
                "종결해도 구조는 남는다. 후보 수가 늘면 32,768도 같은 벽이 된다. 계획의 "
                "\"카테고리별 선택 + 짧은 reason\" 항목이 그 뿌리를 없앤다."]},
        ],
    },
    {
        "date": "2026-08-10", "status": "완화",
        "title": "`.venv`에는 torch가 없어 임베딩 검색이 죽고, 로그가 원인을 잘못 지목한다",
        "key": "벡터 경로는 MedCPT용 PyTorch를 요구하는데 `.venv`에 없다. 실패 메시지가 "
               "`\"Vector search failed (DB might be empty)\"`라 비어 있지 않은 컬렉션을 의심하게 만든다.",
        "sections": [
            {"h": "Impact", "items": [
                "핸드오프의 재현 명령이 `.venv/bin/python`을 쓰므로, 임베딩을 대조군으로 쓰는 측정은 "
                "ablate할 대상이 없는 채로 실행된다.",
                "그 상태의 대조군은 재현되지 않는다. 같은 조건으로 5회 돌렸더니 서로 겹치지 않는 5개 결과가 나왔다."]},
            {"h": "Observed Symptom", "items": [
                "`[Stage 1] RAG: 0, Ontology: 10`. 벡터 검색이 0건이고 후보가 전부 lexical 경로에서 온다.",
                "`Vector search failed (DB might be empty): PyTorch is required for MedCPT embeddings.`"]},
            {"h": "Evidence", "table": {
                "head": ["확인 항목", "`.venv`", "`artemis-api` 컨테이너"],
                "rows": [
                    ["`torch`", "없음", "2.11.0+cu130"],
                    ["`sentence_transformers`", "없음", "없음"],
                    ["Chroma `omop_concepts`", "440,790개", "440,790개"],
                    ["대조군 5회 반복", "5개 결과 모두 다름, 공통 개념 0", "6개 seed 전부 3/3 동일"],
                ]},
                "items": [
                    "컬렉션이 멀쩡하므로 `\"DB might be empty\"`는 원인을 잘못 짚은 것이다. 실제 요구 조건은 `torch`다"
                    "(`src/utils/medcpt_embedding.py:36`).",
                    "메시지를 내는 곳은 `src/agents/agent2/retriever.py:124`."]},
            {"h": "Hypotheses", "items": [
                "기각. Chroma 컬렉션이 비었다는 설명은 틀렸다. 두 환경 모두 440,790개다.",
                "채택. 실행 환경 차이다. 파이프라인에 임베딩이 빠진 게 아니라 `.venv`에 없을 뿐이다."]},
            {"h": "Root Cause", "items": [
                "`.venv`는 테스트·스크립트용으로 만들어졌고 임베딩 의존성을 담지 않는다. 컨테이너가 실제 실행 환경이다.",
                "실패가 조용한 이유는 예외를 삼키고 빈 결과로 계속 진행하기 때문이다. 게다가 메시지가 다른 원인을 "
                "지목해 진단을 반대 방향으로 보낸다."]},
            {"h": "Resolution", "items": [
                "임베딩이 관여하는 측정은 `docker exec artemis-api`로 실행한다. 2026-08-10 귀속 실험을 그렇게 다시 돌렸다.",
                "실험 문서와 핸드오프에 \"반드시 컨테이너에서\"를 실행 조건으로 명시했다."]},
            {"h": "Verification", "items": [
                "컨테이너 실행에서 `MedCPT Query Encoder loaded`가 뜨고 대조군이 6개 seed 전부 3/3 동일하게 재현된다.",
                "같은 seed가 `.venv`에서는 5회 모두 다른 답을 낸다. 두 환경의 차이가 측정으로 갈린다."]},
            {"h": "Closure", "items": [
                "미해결. 절차로만 막았다. `retriever.py:124`의 잘못된 메시지가 그대로라 다음 사람이 같은 곳에서 헤맨다. "
                "메시지가 `torch` 부재를 짚게 하거나, 임베딩이 필수인 경로에서 크게 실패하도록 바꾸는 일이 남았다."]},
        ],
    },
    {
        "date": "2026-08-10", "status": "모니터링",
        "title": "PHOEBE가 조회하는 스키마에 `concept_recommended`가 없다",
        "key": "테이블은 `demo_cdm`에 있는데 `PHOEBE_SCHEMA`는 `omop_vocab`을 가리켜, 매 매핑마다 "
               "쿼리 10회가 실패하고 확장이 0건이었다. 스키마만 바꾸면 **에러 없이 0건**이 되는 함정이 있다.",
        "sections": [
            {"h": "Impact", "items": [
                "동시발생 기반 확장 단계가 통째로 빠진 채 모든 매핑이 돌았다.",
                "2026-08-10 귀속 실험의 결론에는 영향이 없다. 그 경로는 PHOEBE를 부르지 않는다."]},
            {"h": "Observed Symptom", "items": [
                "`[PHOEBE] Query error: (psycopg2.errors.UndefinedTable)` ×10 후 `Expanded to 0 unique concepts`."]},
            {"h": "Evidence", "table": {
                "head": ["추천 테이블", "concept 테이블", "linagliptin 추천"],
                "rows": [
                    ["`omop_vocab`", "`omop_vocab`", "UndefinedTable (원래 상태)"],
                    ["`demo_cdm`", "`demo_cdm`", "**0건, 에러 없음**"],
                    ["`demo_cdm`", "`omop_vocab`", "5건 (glimepiride, glipizide, sitagliptin …)"],
                ]},
                "items": [
                    "물리 테이블은 `demo_cdm.concept_recommended`에 3,768,447행·개념 597,788개로 존재한다.",
                    "`demo_cdm.concept`는 444행뿐이라, 같은 스키마끼리 조인하면 조용히 0건이 된다."]},
            {"h": "Hypotheses", "items": [
                "기각. `PHOEBE_SCHEMA`를 `demo_cdm`으로 바꾸는 것만으로는 안 된다. 위 표의 2행이 그 결과이고 오히려 더 나쁘다(무증상 0건).",
                "채택. 추천 테이블과 어휘가 서로 다른 스키마에 있는데, 쿼리는 둘을 같은 스키마에서 조인한다."]},
            {"h": "Root Cause", "items": [
                "`phoebe_client.py:76-77`이 `{schema}.concept_recommended`와 `{schema}.concept`를 하나의 스키마 변수로 "
                "조인한다. 이 배치에서는 두 테이블이 서로 다른 스키마에 있어 어떤 단일 값도 맞지 않는다.",
                "같은 파일의 주석이 이 부류의 사고를 이미 기록해뒀다. 과거에는 `PHOEBE_SCHEMA`가 설정됐는데도 무시되고 "
                "조용히 `demo_cdm`을 쿼리했다."]},
            {"h": "Resolution", "items": [
                "코드를 건드리지 않고 뷰로 붙였다: "
                "`CREATE OR REPLACE VIEW omop_vocab.concept_recommended AS SELECT * FROM demo_cdm.concept_recommended;`",
                "되돌리기는 `DROP VIEW omop_vocab.concept_recommended;`다. 뷰 주석에 이 함정과 함께 적어뒀다."]},
            {"h": "Verification", "items": [
                "뷰가 3,768,447행을 노출하고, linagliptin 추천이 0건 → 5건이 된다(glimepiride, glipizide, sitagliptin).",
                "SQL 층위에서만 확인했다."]},
            {"h": "Closure", "items": [
                "미해결. 파이프라인 안에서는 확인하지 못했다. `_recommend_seeded_concept_set`은 "
                "`agents/agent2/workflow.py`를 타고 PHOEBE는 `agents/conceptset/stage2_pipeline.py`에 있어 서로 다른 경로다. "
                "stage2 경로를 한 번 태워 확장이 0이 아닌 것을 봐야 종결한다."]},
        ],
    },
    {
        "date": "2026-08-10", "status": "완화",
        "title": "ablation 스크립트가 플래그 게이트를 우회해, 켠 적 없는 노브에서 결론이 나올 뻔했다",
        "key": "`rebuild_entry_concept_sets.py`는 `_exact_ingredient_mapping`을 직접 호출한다. 플래그를 검사하는 "
               "게이트를 지나가지 않으므로 `ARTEMIS_DISABLE_EXACT_INGREDIENT_MATCH`를 켜든 끄든 출력이 같다.",
        "sections": [
            {"h": "Impact", "items": [
                "이 스크립트로 대조군을 만들면 두 arm이 바이트 동일해지고, 그것은 "
                "\"ablation 효과 없음 = exact match는 불필요\"로 읽힌다. 반대 결론이다.",
                "실행 전에 잡아 실제 오측정은 없었다."]},
            {"h": "Observed Symptom", "items": [
                "정적 확인에서 드러났다. 스크립트가 부르는 함수와 플래그를 검사하는 위치가 다르다."]},
            {"h": "Evidence", "items": [
                "`scripts/rebuild_entry_concept_sets.py:81` → `svc._exact_ingredient_mapping(target)` 직접 호출.",
                "플래그 게이트는 `tte_service.py:6176`의 "
                "`if expected_domain in (\"Drug\", None) and self._exact_ingredient_match_enabled():`.",
                "같은 스크립트의 docstring은 \"through the production mapper "
                "(`TTEService._recommend_seeded_concept_set`)\"라고 적어뒀는데 코드는 그렇게 하지 않는다."]},
            {"h": "Hypotheses", "items": [
                "채택. 스크립트는 entry 집합만 다시 만들려고 최단 경로를 부르는데, 그 경로에 게이트가 없다."]},
            {"h": "Root Cause", "items": [
                "문서와 코드의 불일치. docstring이 production 매퍼를 부른다고 약속하는데 실제로는 그 아래 단계를 직접 부른다. "
                "노브가 배선되지 않은 경로를 배선된 것으로 읽게 만든다."]},
            {"h": "Resolution", "items": [
                "귀속 실험은 `_recommend_seeded_concept_set`을 직접 호출하는 프로브로 했다. 게이트를 지나는 경로다.",
                "실험 문서와 핸드오프에 \"이 스크립트로는 ablation을 할 수 없다\"를 근거와 함께 명시했다."]},
            {"h": "Verification", "items": [
                "게이트를 지나는 프로브에서는 플래그가 답을 바꾼다. linagliptin이 exact ON에서 `40239216`, "
                "OFF에서 `1580747 sitagliptin`이다. 노브가 실제로 배선됐다는 확인이다."]},
            {"h": "Closure", "items": [
                "미해결. 스크립트는 그대로다. docstring을 코드에 맞게 고치거나, 코드를 docstring에 맞게 "
                "`_recommend_seeded_concept_set` 경유로 바꾸는 일이 남았다. 둘 중 무엇이든 다음 사람이 "
                "같은 함정에 걸리지 않게 한다."]},
        ],
    },
    {
        "date": "2026-08-11", "status": "신규",
        "title": "매퍼가 무의미한 질의에도 자신 있게 개념을 답한다",
        "key": "질의 자체가 무의미한데도 파이프라인은 concept id를 반환한다 — 리랭커는 후보를 거절하지 않고 그중 최선을 고른다.",
        "sections": [
            {"h": "Impact", "items": [
                "이것이 1.0까지 남은 gap의 가장 유력한 지점이다. 매핑 모델을 통째로 바꿨을 때 concept set의 21%가 "
                "바뀌었는데도 macro recall은 0.000 움직였다 — 이것이 무엇이든 항상 반환하는 파이프라인의 모습이다."]},
            {"h": "Observed Symptom", "items": [
                "`_build_seeded_target_circe`, criterion domain `Condition`, seed `qqzzxx nonexistent clinical term`:",
                "`Using 60 pre-fetched candidates for 'qqzzxx nonexistent clinical term'`",
                "`retriever → 60 candidates. Top-5: [(4200113, 'Non-Q wave myocardial infarction', 89.886), ...]`",
                "`reranker → 3 selected: [(4145721, 'Acute non-Q wave infarction'), (4124685, ...)]`",
                "`Critic selected: 6 from 55 candidates`",
                "`FINAL 'qqzzxx nonexistent clinical term' → [4200113, 4145721, 4124685, 4119...]`"]},
            {"h": "Evidence", "items": [
                "같은 리랭커가 `linagliptin`에서는 후보 20개를 전부 기각했다(`reranker → 0 selected`) — '아니오'라고 "
                "말할 능력은 있다. 다만 강제 선택('이 중 어느 것이 최선인가')만 받고, "
                "'이 중 질의와 같은 뜻인 것이 있는가'는 받지 않는다.",
                "`_recommend_seeded_concept_set`을 같은 문자열로 직접 호출하면 `ValueError: No concept mapping "
                "found for '...'`가 난다. 두 경로가 갈리는 이유는 빌더가 배치로 미리 가져온 후보 60개를 리랭커에 "
                "그대로 넘기기 때문이다 — 실제로 일치하는 것이 없는 질의도 이 경로로는 후보 60개를 들고 리랭커에 도착한다."]},
            {"h": "Hypotheses", "items": [
                "채택. 관련성 바닥(relevance floor)이 파이프라인 어디에도 없다. 같은 날 실험 노트에서 거리 임계값은 "
                "이미 기각됐다 — 그 바닥이 될 수 없다."]},
            {"h": "Root Cause", "items": [
                "관련성 바닥의 부재. 거리 임계값은 기각됐고, 리랭커는 강제 선택 형태의 질문만 받아 '없음'을 답할 길이 없다."]},
            {"h": "Resolution", "items": [
                "미확정. 해결책의 형태 자체가 아직 정해지지 않았다. 유력한 방향은 리랭커에게 강제 선택 대신 "
                "'후보 중 질의와 같은 뜻인 것이 있는가'를 명시적으로 묻는 것이다."]},
            {"h": "Verification", "items": [
                "확인 중. 아직 코드 변경이 없어 검증할 대상이 없다."]},
            {"h": "Closure", "items": [
                "미확정. 이 이슈는 후속 조사 대상으로 열어둔다. 매핑 모델 교체가 macro 점수를 움직이지 않았다는 "
                "사실과 결합하면, 관련성 바닥의 부재가 남은 gap의 유력한 원인이다."]},
        ],
    },
    {
        "date": "2026-08-11", "status": "해결",
        "title": "리랭커의 기각을 retriever의 top-1으로 강제 포함시켰다",
        "key": "`workflow.py`가 리랭커 선택과 무관하게 candidates[0]을 무조건 삽입했다 — 이제 정확 이름 일치가 있거나, "
               "리랭커가 무언가 골랐는데 top-1이 그 안에 없을 때만 강제 포함한다.",
        "sections": [
            {"h": "Impact", "items": [
                "`if not top_concepts: return []` 분기가 무조건 삽입 코드 아래에 있어 도달 불가능했다. 후보가 하나라도 "
                "존재하면 파이프라인은 절대 빈 결과를 반환하지 않았다 — CIRCE 산출물 374개 중 374개가 비어 있지 않았다.",
                "주석은 이 삽입을 `_COMMON_RELIABLE_CONCEPTS`를 위한 '보호' 장치라고 정당화했는데, 그 식별자는 "
                "코드베이스 어디에도 없다."]},
            {"h": "Observed Symptom", "items": [
                "`linagliptin` 질의에서 리랭커가 `reranker → 0 selected`를 로그에 남겼는데도 최종 결과는 "
                "`sitagliptin (1580747)`이었다."]},
            {"h": "Evidence", "items": [
                "`workflow.py`가 리랭킹 뒤 `candidates[0]`을 무조건 삽입하고, 그 아래의 "
                "`if not top_concepts: return []` 분기는 후보가 하나라도 있으면 도달하지 않는다."]},
            {"h": "Hypotheses", "items": [
                "채택. 강제 포함이 '아무것도 못 찾음'을 '자신 있게 틀림'으로 바꾸고 있었다."]},
            {"h": "Root Cause", "items": [
                "확정. `workflow.py`가 리랭킹 뒤 `candidates[0]`을 무조건 삽입했고, `if not top_concepts: return []` "
                "분기는 그 삽입 아래에 있어 후보가 하나라도 있으면 도달할 수 없었다. 그래서 파이프라인에는 무엇도 "
                "반환하지 않는 경로가 없었다 — CIRCE 산출물 374개 전부가 비어 있지 않았다. 주석은 이 삽입을 "
                "`_COMMON_RELIABLE_CONCEPTS`로 '보장된' 개념을 보호하기 위해서라고 적어뒀는데, 그 식별자는 "
                "코드베이스 어디에도 없다."]},
            {"h": "Resolution", "items": [
                "`src/agents/agent2/workflow.py`에 함수 두 개를 새로 넣었다. `_exact_name_concept(query_text, "
                "domain_hint)`는 질의를 표준 `concept_name`의 문자 그대로 조회해 정확히 한 행만 일치할 때만 "
                "받아들인다(모호하면 기각 — MeSH 별칭 경로와 같은 규칙). `_seeds_after_rerank(candidates, "
                "top_concepts, exact_concept)`는 강제 포함을 원래 대상이던 경우로만 제한한다 — 리랭커가 무언가 "
                "선택했고 top-1이 그 선택 안에 없는 경우."]},
            {"h": "Verification", "items": [
                "컨테이너에서 `ARTEMIS_DISABLE_EXACT_INGREDIENT_MATCH=1`(entry-drug 지름길을 끈 상태)로 "
                "`linagliptin`을 호출하면 이제 `reranker → 0 selected` 다음에 "
                "`Exact concept_name match: 'linagliptin' → linagliptin (40239216)`가 찍히고 `[40239216]`을 "
                "반환한다. 같은 호출이 수정 전에는 `[1580747]`(sitagliptin)이었다.",
                "`tests/test_agent2_reranker_rejection.py`에 새 테스트 11개(그중 5개는 실제 어휘 대상 통합 테스트). "
                "전체 스위트를 변경 전후로 돌렸다: 213 failed(변경 전후 동일), passed 1806 → 1817 — 정확히 새 "
                "테스트 11개만큼 늘었고 회귀는 없다."]},
            {"h": "Closure", "items": [
                "해결. 2026-08-10 귀속 노트가 열어둔 질문을 닫는다 — 정확 성분 매칭은 이 결함 위에 덮인 안전망이었지, "
                "유일한 수정이 아니었다."]},
        ],
    },
    {
        "date": "2026-08-11", "status": "해결",
        "title": "매핑 실패한 기준이 산출물에 흔적 없이 사라졌다",
        "key": "실패한 기준은 `logging.warning`으로 로그만 찍고 `None`이 되어 하위 소비자에서 조용히 스킵됐다 — 이제 "
               "`_unmappedCriteria`로 항상 기록한다.",
        "sections": [
            {"h": "Impact", "items": [
                "`_build_seeded_target_circe`가 스레드 풀에서 기준을 매핑한다. 실패는 잡혀서 `logging.warning`으로만 "
                "남고 `None`이 되며, 아래 모든 소비자가 `if result is not None`으로 건너뛴다. 제외 기준 하나가 "
                "조용히 빠지면 저장된 스터디는 완전해 보이는 채로 프로토콜보다 넓은 코호트가 된다."]},
            {"h": "Observed Symptom", "items": [
                "매핑에 실패한 기준이 로그에만 남고 저장된 study 아티팩트에는 어떤 필드에도 나타나지 않았다."]},
            {"h": "Evidence", "items": [
                "except 블록이 예외를 잡아 경고 로그만 남기고 `None`을 반환했다. 소비자 쪽 필터 "
                "`if result is not None`이 그 `None`을 조용히 건너뛴다."]},
            {"h": "Hypotheses", "items": [
                "채택. 기록이 빠진 것은 관측 결함이지 매핑 결함이 아니다 — 기준을 드롭하는 결정 자체는 유지해도 "
                "된다(기준 하나를 못 맵핑했다고 스터디 전체를 실패시킬 필요는 없다)."]},
            {"h": "Root Cause", "items": [
                "except 블록이 실패를 로그로만 남기고 결과를 `None`으로 바꿨으며, 하위의 모든 소비자가 "
                "`if result is not None`으로 건너뛰게 짜여 있어 드롭된 기준이 산출물 어디에도 기록되지 않았다."]},
            {"h": "Resolution", "items": [
                "except 블록이 이제 `{criterionId, role, label, domain, reason}`을 기록하고, "
                "`_build_seeded_target_circe`는 항상 `_unmappedCriteria`를 반환한다(아무것도 실패하지 않았으면 "
                "빈 리스트라, 키가 없는 것과 '깨끗한 실행'을 혼동할 수 없다). 기준을 드롭하는 동작 자체는 "
                "유지했다 — 못 맵핑한 줄 하나 때문에 스터디 전체를 버릴 이유는 없다."]},
            {"h": "Verification", "items": [
                "`tests/test_unmapped_criteria_are_recorded.py`에 테스트 4개. 전체 스위트를 변경 전후로 돌렸다: "
                "100 failed(변경 전후 동일), passed 2048 → 2052 — 정확히 새 테스트 4개만큼 늘었다."]},
            {"h": "Closure", "items": [
                "해결. 다만 한계는 정직하게 적는다 — 기록 자체는 맞지만 거의 발동하지 않는다. 위 '신규' 이슈대로 "
                "파이프라인이 거의 실패하지 않고 항상 무언가를 반환하기 때문이다. 두 이슈는 같은 결함의 "
                "다른 얼굴이다."]},
        ],
    },
    {
        "date": "2026-08-11", "status": "해결",
        "title": "로컬 가상환경이 requirements.txt와 어긋나 있었다",
        "key": "`torch`/`pandas`/`langgraph` 등이 `.venv`에 없어 임베딩 검색·테스트 수집이 조용히 무너졌다 — "
               "`.venv`를 requirements.txt와 맞추고 게이트 테스트를 추가했다.",
        "sections": [
            {"h": "Impact", "items": [
                "한 세션에서 측정 세 가지가 어긋났다. `torch`가 없어 MedCPT 임베딩이 아무것도 반환하지 않았는데 "
                "`retriever.py`는 440,790개 개념이 있는 컬렉션을 두고 `\"Vector search failed (DB might be "
                "empty)\"`라고 보고했고, 같은 조건의 대조군 5회 실행이 서로 겹치지 않는 5개 결과를 냈다.",
                "`pandas`/`langgraph`가 없어 테스트 모듈 10개가 import 단계에서 실패했는데, 그 실행은 여전히 통과 "
                "개수를 출력했다."]},
            {"h": "Observed Symptom", "items": [
                "`Vector search failed (DB might be empty)` — 컬렉션은 비어 있지 않았다.",
                "pytest 수집 오류 10건이 나면서도 실행 요약에는 pass 카운트가 찍혔다."]},
            {"h": "Evidence", "items": [
                "`Dockerfile.tte-api`는 `uv pip install --system --no-cache -r requirements.txt`로 컨테이너를 빌드해 "
                "구조적으로 맞는 반면, `.venv`는 수작업으로 만들어져 그 뒤로 어긋났다. `numpy`가 고정 버전 1.26.4 "
                "대신 2.5.0이 깔려 있었다."]},
            {"h": "Hypotheses", "items": [
                "기각. 코드나 파이프라인 결함이 아니라 환경 어긋남이다.",
                "채택. 눈에 띄게 없는 패키지만 골라 설치하면 상황이 더 나빠진다 — `langgraph==0.0.28`이 "
                "`packaging`을 26.2→23.2로, `tenacity`를 9.1.4→8.5.0으로 끌어내렸고 실패가 213 → 321로 늘었다."]},
            {"h": "Root Cause", "items": [
                "`.venv`가 `requirements.txt`와 별개로 손으로 조립되어 드리프트했다. 컨테이너는 그 파일 하나로 "
                "빌드되므로 구조적으로 정확하다."]},
            {"h": "Resolution", "items": [
                "`.venv`를 같은 파일로 맞췄다: `uv pip install --python .venv/bin/python -r requirements.txt`. "
                "`uv pip sync`는 여기서 틀린 명령이다 — `requirements.txt`에 pytest가 없어 sync가 테스트 러너 "
                "자체를 지운다."]},
            {"h": "Verification", "items": [
                "failed 213 → 100, passed 1817 → 2048, collection error 10 → 0. `.venv`가 이제 torch "
                "2.11.0+cu130을 보고하고 MedCPT를 로컬에서 import한다.",
                "새 게이트 `tests/test_environment_matches_requirements.py`(테스트 7개)가 `requirements.txt`를 "
                "파싱해 어긋나면 패키지별 결과를 이름으로 지목하며 실패한다. 컨테이너와 정렬된 `.venv` 양쪽에서 "
                "통과한다 — 둘 다 그 파일 하나에서 나오기 때문이다."]},
            {"h": "Closure", "items": [
                "해결. 환경 정합성이 코드 게이트로 고정됐다."]},
        ],
    },
]


def render(a: dict, b: dict, gemma: dict, out: Path) -> None:
    rows = build_rows(a, b)
    units = build_units(a, b)
    ra, rb = _macro(a, "recall_mean"), _macro(b, "recall_mean")
    za, zb = _zero(a), _zero(b)
    rg_gemma, zg_gemma = _macro(gemma, "recall_mean"), _zero(gemma)
    gemma_changed = sum(c for c, _ in _GEMMA_CHANGED_SETS.values())
    gemma_total = sum(n for _, n in _GEMMA_CHANGED_SETS.values())
    gemma_pct = round(100 * gemma_changed / gemma_total)
    moved = [r for r in rows if abs(r["fix_rec"] - r["ctl_rec"]) > 1e-9]
    oos = sum(len(t["out_of_scope_gold"]["sets"]) for t in a["trials"])

    framing = [
        {"title": "묻는 것", "text":
            "임상시험 eligibility 기준에서 생성한 concept set이 gold(TROY v1.1 CIRCE)와 얼마나 일치하는가, "
            "그리고 `991c11c`의 게이트 수정이 그 일치도를 실제로 올렸는가."},
        {"title": "기존 방식", "text":
            "이전에는 `synthea_cdm` 계열 벤치마크 CDM의 환자 수로 품질을 판단했다. 그 CDM은 gold에서 만들어 낸 것이라 "
            "환자 수는 생성기의 관례를 반쯤 재고 있었다. 그래서 측정 기준을 `data/gold/` 대비 closure 겹침으로 바꿨다."},
        {"title": "남아 있던 구멍", "text":
            "겹침을 어느 단위로 재느냐가 정해지지 않아, 처음 측정은 pooled concept mass(micro) 평균이었고 "
            "그것이 ARISTOTLE의 결론을 뒤집었다(micro 0.087/0.863 vs 기준별 0.749/0.153). "
            "단위는 이제 **eligibility 기준별 1:1, macro 평균**으로 고정됐다."},
        {"title": "이 페이지가 뒷받침하는 것", "text":
            f"동일 store·동일 exporter·동일 채점 플래그로 만든 짝지은 2-arm 비교. macro recall {rb:.3f} → {ra:.3f}, "
            f"겹침 0인 쌍 {zb} → {za}. 손대지 않은 4개 trial이 정확히 0.000 움직였다는 것이 parity의 증거다."},
        {"title": "아직 주장하지 않는 것", "text":
            "대조군 `ARTEMIS_DISABLE_EXACT_INGREDIENT_MATCH=1`은 2026-08-10에 실행됐고, "
            "\"임베딩이 고유명사에 약하다\"는 **일반 명제로는 기각**됐다. entry seed 6개 중 답이 바뀐 것은 linagliptin뿐이다. "
            "남는 것: 663개 시드 전체로 넓히면 비율이 달라지는가, 그리고 `Force-included Top-1` 폴백을 끄면 "
            "exact match 없이도 오답이 무답이 되는가. 둘 다 아직 재보지 않았다. "
            f"매핑 모델 자체를 gemma로 통째로 바꿔 6개 시험을 재매핑한 결과도 이 페이지에 넣었다. "
            f"concept set {gemma_total}개 중 {gemma_changed}개({gemma_pct}%)가 바뀌었지만 macro recall "
            f"{ra:.3f} → {rg_gemma:.3f}, 겹침 0인 쌍 {za} → {zg_gemma}로 점수는 움직이지 않았다. "
            "다만 이 비교는 모델만 바뀐 순수 대조군이 아니다. arm A의 non-entry concept set은 2026-08-04 store "
            "빌드 기준이라, gemma 델타에는 그 이후의 모든 코드 변경이 함께 섞여 있다."},
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
    # Built first so the plan can drop links to notes this page does not carry.
    notes = build_notes(a, b, gemma, rows)
    for bid, payload in (
        ("framingdata", framing), ("unitdata", units), ("data", rows),
        ("plandata", build_plan({n["date"] for n in notes})), ("notesdata", notes), ("issuesdata", ISSUES),
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
         '      <h1>entry 약물 exact match: 짝지은 2-arm 측정</h1>\n'
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
         '손대지 않은 4개 trial이 <b>정확히 0.000</b> 움직였고, 그 trial들의 CIRCE 파일은 두 arm 사이에서 바이트 동일하다. '
         f'다른 요인이 섞이지 않았다는 증거다. 다만 움직인 {len(moved)}쌍 중 3쌍은 gold 자체의 '
         '참조되지 않는 중복 concept set이라, 같은 수정을 세 번 더 센 것이다. '
         '정직한 값은 <b>2건</b>(CARMELINA·CAROLINA 각 entry 약물 1개). study당 entry 약물이 하나이니 당연한 수다.</p></div>',
         "verdict")

    sub1(r'<div class="chart-t">Metric A by entity</div><div class="chart-s">.*?</div>',
         '<div class="chart-t">arm별 평균 recall</div><div class="chart-s">대조군은 점선 기준선.</div>', "barA title")
    sub1(r'<div class="chart-t">Metric B by entity</div><div class="chart-s">.*?</div>',
         '<div class="chart-t">arm별 평균 precision</div><div class="chart-s">대조군은 점선 기준선.</div>', "barB title")
    sub1(r'<div class="chart-t">Metric A distribution</div><div class="chart-s">.*?</div>',
         '<div class="chart-t">recall 분포</div>'
         '<div class="chart-s">두 arm이 거의 겹친다. 232쌍 중 5쌍만 움직였으니 그게 정상이다.</div>', "distA title")
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
         '어떤 기준도 참조하지 않는다(238개 중 14개). 이 중복을 분모에 남기기로 2026-08-10에 결정했으니, '
         '비용은 보고 단계에서 치른다. <b>쌍 수가 아니라 구별되는 수정 수를 인용한다.</b> '
         '규칙은 <span class="inline-code">artemis/AGENTS.md</span> EVALUATION에 고정돼 있다.</p></div>\n'
         f'        <div class="callout"><h3>범위 밖 gold 집합 {oos}개</h3><p>gold가 '
         '<span class="inline-code">CensoringCriteria</span>에서만 참조하는 약물 집합이다. Warfarin, Sulfonylureas, Glimepiride, '
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
    ap.add_argument("--gemma", default="output/conceptset_overlap/scoped_gemma.json")
    ap.add_argument("--out", default="output/conceptset_overlap/dashboard.html")
    args = ap.parse_args(argv)
    render(
        json.loads(Path(args.arm_a).read_text()),
        json.loads(Path(args.arm_b).read_text()),
        json.loads(Path(args.gemma).read_text()),
        Path(args.out),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
