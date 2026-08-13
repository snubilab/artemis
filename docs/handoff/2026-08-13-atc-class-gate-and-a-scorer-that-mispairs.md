# Handoff — ATC 클래스 게이트, 그리고 짝을 잘못 짓는 채점기 — 2026-08-13

## Goal / context

`2026-08-12-the-preference-that-never-reached-the-ranking.md`의 후속. 그 문서가 검색
선호 스케일을 고쳤고 매크로 recall은 안 움직였다. 이번 세션은 "왜 안 움직이나"를 파다가
**약물 클래스 확장이 임계값 하나에 막혀 있던 것**을 찾아 고쳤고, 마지막에 **채점기 자체가
gold를 엉뚱한 생성 집합에 붙이고 있다**는 것을 발견했다.

가장 중요한 인계 사항은 세 번째다. 지금까지의 모든 판단이 그 채점기 숫자 위에 서 있다.

## Current state

- 브랜치 `fix/tte-a-drug-anchored-entry` · HEAD `93f3c62` · PR 없음 (`gh` 미인증)
- **이번 세션 커밋 6건** (아래 "Done"). 그 아래로 **이전 세션들의 미커밋 변경이 그대로
  남아 있다** — 섞지 말 것:
  ```
   M src/agents/agent2/critic.py      logic.py      reranker.py      workflow.py
   M src/services/tte_service.py
   M scripts/build_conceptset_dashboard.py  build_diagnosis_dashboard.py
   M output/conceptset_overlap/dashboard.html
  ?? tests/ 6종, docs/handoff/ 4종, docs/experiments/ 1종
  ```
- 실행 중: vLLM PID `134304` (`google/gemma-4-E4B-it`, 32k, `:8000`),
  컨테이너 `artemis-api` / `ohdsi-webapi` / `broadsea-atlasdb` / `artemis-neo4j-v2` Up
- 이번 세션 산출물:
  `tmp/atc_fix/` (콜드 캐시 store) · `output/circe_atc_fix/` ·
  `output/conceptset_overlap/scoped_atc_fix.json` · `output/atc_fix.log` ·
  `output/seed_arms.log` + `output/_seed_arms.json` ·
  `output/_offered_gold.json` · `output/_ceiling.json`
- 비교 기준선: `output/conceptset_overlap/scoped_scale_fix.json` (직전 arm)
- 테스트: **100 failed / 2082 passed** (기존 100 + 신규 6). 회귀 0.

## Done this session

| 커밋 | 내용 |
| --- | --- |
| `7d0bb4b` | `AGENT2_ATC_DISTANCE_THRESHOLD` 기본값 0.4 → **0.75** + 테스트 6건 |
| `e6214ce` | 핸드오프 갱신 (ATC 측정 결과 + 채점기 결함 + 씨앗 실험) |
| `93f3c62` | todolist 마감 (D1~D3만 열려 있음) |
| `728adc5` | (앞 세션 이어받아 오늘 커밋) 검색 선호 스케일 수정 |
| `2956e13` `ebb0693` `1ffdb76` | 그 수정의 핸드오프 · 측정 결과 · 자기정정 |

## Key decisions & why

- **ATC 임계값 0.4 → 0.75.** 앞선 재매핑 로그의 ATC 판정 31건 전체를 거리순으로 뽑아
  결정했다. 통과 4건(최대 0.134), 기각 27건(최소 0.453), 그리고 **기각된 0.453~0.735
  구간은 전부 정답**(DPP-4 0.456, SGLT2 0.462/0.469/0.490, GLP-1 0.499/0.618/0.646,
  insulin 0.453/0.607/0.636, corticoid 0.537, anti-obesity 0.627). 그 구간의 유일한
  오답은 `CYP3A inhibitors → Pi3K inhibitors`(0.760)이므로 0.75가 안전 상한이다.
  **0.4는 클러스터를 가른 게 아니라 그 너머를 아무도 안 본 채 정해진 값이었다.**
- **테스트에 관측 거리를 썼다.** 결함이 "경계를 어디 두었나"에 있으므로 합성값으로는
  재현되지 않는다. `tests/test_atc_class_distance_threshold.py`.
- **기존 테스트 `test_atc_distance_above_threshold_is_rejected`를 통과시키려고 느슨하게
  만들지 않았다.** 그 테스트는 거리 0.55(합성값)와 옛 임계값을 하드코딩하고 있었다.
  시나리오를 **관측된 오답** `Drug-naïve → OTHER NERVOUS SYSTEM DRUGS`(0.957)로 옮겨
  "임계값 초과는 기각"이라는 원래 의도를 새 경계에서 유지시켰다.
- **`top_n=3 → 5`를 이번 arm에 넣지 않았다.** 오프라인으로 효과가 확인됐지만(아래)
  ATC와 같은 arm에 섞으면 무엇이 숫자를 움직였는지 귀속할 수 없다.
- **상수 재조정(게인 스윕)은 시도하고 기각했다.** 앞 핸드오프의 표 참조. 조정셋은 1.5를,
  검증셋은 0.20을 최적이라 했고 검증 곡선이 지그재그였다. **다시 시도하지 말 것.**
- **커버리지를 프롬프트로 지시하는 접근도 기각.** 아래 씨앗 실험 C/D arm.

## 측정 (scale_fix → atc_fix, 공통 gold 집합 기준 짝지음)

| trial | recall | precision |
| --- | --- | --- |
| ARISTOTLE | 0.662 → 0.670 (+0.008) | 0.405 → 0.399 |
| CARMELINA | 0.550 → 0.619 (+0.069) | 0.561 → 0.582 |
| CAROLINA | 0.579 → 0.600 (+0.021) | 0.594 → 0.585 |
| EMPA-REG | 0.442 → 0.443 (+0.002) | 0.439 → 0.439 |
| LEADER | 0.625 → 0.625 (0.000) | 0.604 → 0.602 |
| PLATO | 0.807 → 0.807 (0.000) | 0.734 → 0.729 |
| **MACRO** | **0.611 → 0.627 (+0.017, 1.52 SE, 5/6)** | **0.556 → 0.556** |

대상 기준에서 인과가 직접 보인다는 점이 앞선 두 세션과 다르다:

| 기준 | recall | precision |
| --- | --- | --- |
| SGLT2 inhibitors | 0.25 → **1.00** | 0.48 → 0.97 |
| GLP-1 RA (2개 시험) | 0.41 → **1.00** | 1.00 → 1.00 |
| DPP-4 inhibitor (올바른 짝) | 0.131 → **0.621** | 0.577 → **1.000** |
| `[CKim] any insulin` | 0.00 → 0.20 | 1.00 → 0.63 |

## 🔴 채점기가 짝을 잘못 짓는다 — 원인까지 확인됨

`scoped_atc_fix.json`은 gold `[TROY intervention] DPP4 inhibitors`를 생성 집합
**`SGLT-2 inhibitors`**에 붙이고(recall 0.07), 맞는 상대인 생성 집합 `DPP-4 inhibitor`
(gliptin 7성분)를 `unmatched_generated`로 버린다. 올바른 짝으로 채점하면 **0.621**이다.

원인은 `scripts/conceptset_overlap_eval.py:250 normalize_set_name` +
`:256 name_similarity`. 이름 유사도가 **토큰 집합 Jaccard**인데, `_NON_ALNUM`으로 쪼개므로:

```
gold  '[TROY intervention] DPP4 inhibitors' → {dpp4, inhibitors}
gen   'DPP-4 inhibitor'                     → {4, dpp, inhibitor}    name_sim = 0.000
gen   'SGLT-2 inhibitors'                   → {2, inhibitors, sglt}  name_sim = 0.250
```

`DPP4` vs `DPP-4`는 하이픈 때문에 **공유 토큰이 하나도 없고**, 단수/복수(`inhibitor` vs
`inhibitors`)도 안 맞는다. 반면 SGLT-2는 `inhibitors`를 그대로 공유한다. **변별 토큰이
0점을 받고 어미가 매칭을 결정한다.** 쌍 선택은 `:317-330`.

즉 위 매크로 `+0.017`은 **과소평가**이고, 같은 부류가 몇 건 더 있는지 모른다.

## Next steps (ordered, concrete)

1. **D2 먼저 — 오짝짓기 건수 집계.** 6개 시험 전체에서 `unmatched_generated`에 남은
   집합 중, 어떤 gold와 토큰 정규화만 다르게 생긴 것이 몇 건인지 센다. 매크로 수치의
   신뢰도가 여기 걸려 있다. 파이프라인을 더 건드리기 전에 할 것.
2. **D1 — `normalize_set_name` 수정.** 최소 두 가지: (a) 하이픈/숫자 경계를 분리하지
   않거나 `dpp4`/`dpp-4`를 같은 토큰으로 접기, (b) 단순 복수형 정규화. 수정 후
   `name_sim`이 위 세 줄에서 어떻게 바뀌는지 먼저 찍어볼 것.
3. **D3 — 과거 arm 전부 재채점.** `scoped_gate_fix` / `scoped_scale_fix` /
   `scoped_atc_fix`를 같은 채점기로 다시 돌려야 비교가 성립한다. CIRCE 파일은 이미
   있으므로 재매핑은 불필요하고 채점만 다시 하면 된다.
4. **`standard_concept` 재색인.** 사용자가 요청했다가 중단한 항목. ChromaDB
   `omop_concepts_medcpt` 메타데이터에 `standard_concept` 키가 없어
   `src/agents/agent2/retriever.py`의 표준 개념 선호(−0.10/+0.15) 분기가 한 번도 실행된
   적이 없다. 스케일 문제가 아니라 데이터 부재이므로 재색인 외에 방법이 없다.
   **미착수** — 벡터는 그대로 두고 메타데이터만 갱신할 수 있는지부터 확인할 것.
5. **`top_n=3 → 5`가 다음 파이프라인 arm.** 근거는 아래 씨앗 실험. precision 영향이
   미측정이므로 재매핑으로 확인할 것.
6. **UMLS MRREL SQLite 부재.** `output/atc_fix.log`에 `MRREL/MRCONSO SQLite not
   available`. 약물 클래스 확장의 1번 전략이 통째로 죽어 있고 ATC가 유일한 경로다.
   빌드하면 두 번째 경로가 생긴다.

## 씨앗 실험 (4-arm, 재매핑 없음) — `output/_seed_arms.json`

74개 기준, 네 arm이 **동일한 후보 15개**를 채점(검색은 한 번만 실행). 지표는 검색이
top-15에 올린 gold 118개 중 씨앗에 든 개수.

| arm | top_n | 커버리지 지침 | gold 씨앗 유지 |
| --- | --- | --- | --- |
| A | 3 | 없음 (현재) | 62.7% |
| B | 5 | 없음 | **72.9%** |
| C | 3 | 있음 | 63.6% |
| D | 5 | 있음 | **74.6%** |

top_n 효과는 두 조건에서 일관(+10.2 / +11.0pp). 프롬프트 한 줄은 +0.9 / +1.7pp로
gold 1~2개 차이라 0과 구별되지 않는다. **이 실험은 recall 쪽만 쟀다.**

## How to verify / run

```bash
cd /home/bilab/work/projects/Broadsea/artemis

# 실행환경 게이트 — 다른 무엇보다 먼저
.venv/bin/python -m pytest tests/test_environment_matches_requirements.py -q

# 이번 세션 테스트
.venv/bin/python -m pytest tests/test_atc_class_distance_threshold.py tests/test_drug_class_fix.py -q

# 전체 (기준선: 100 failed / 2082 passed)
.venv/bin/python -m pytest tests/ -q -p no:randomly

# 오짝짓기 재현 (D1/D2 착수점)
.venv/bin/python -c "
import sys; sys.path.insert(0,'.')
from scripts.conceptset_overlap_eval import normalize_set_name, name_similarity
g='[TROY intervention] DPP4 inhibitors'
for c in ('DPP-4 inhibitor','SGLT-2 inhibitors'):
    print(c, sorted(normalize_set_name(c)), round(name_similarity(g,c),3))
"
```

**재채점만 다시 (재매핑 불필요, CIRCE는 이미 있음):**

```bash
.venv/bin/python scripts/conceptset_overlap_eval.py --mode closure \
  --generated-dir output/circe_atc_fix \
  --out output/conceptset_overlap/scoped_atc_fix.json
```

**arm 검증 — 3시간짜리를 시작하기 전에 항상:**

```bash
docker exec -i artemis-api python -u - <<'PY'
import sys, inspect; sys.path.insert(0,'/app'); import psycopg2
from src.settings import settings
from src.agents.agent2 import drug_class_expander as dce
d = inspect.signature(dce.expand_drug_class_via_vocab).parameters['distance_threshold'].default
assert abs(d - 0.75) < 1e-9, f"threshold is {d}, not 0.75"
conn = psycopg2.connect(settings.DATABASE_URL)
name, ids = dce.expand_drug_class_via_vocab("DPP-4 inhibitors", conn, schema=settings.CDM_SCHEMA)
assert name and len(ids) >= 7, f"ATC path dead: {name} {len(ids) if ids else 0}"
print("ARM VERIFIED", name, len(ids))
PY
```

## Gotchas / constraints

- **채점기 숫자를 인용하기 전에 `unmatched_generated`를 볼 것.** DPP4가 0.07로 읽히는
  건 파이프라인이 아니라 매처 탓이다. 지금 이 저장소의 모든 매크로 수치가 이 영향 아래 있다.
- **`AGENT2_ATC_DISTANCE_THRESHOLD`는 import 시점에 바인딩된다**
  (`drug_class_expander.py:186`의 기본 인자). 환경변수를 나중에 세팅해도 안 먹는다.
  런타임에 바꾸려면 인자로 넘길 것.
- **재매핑은 in-process다** (`scripts/regenerate_structured_expression.py:98`이
  `TTEService`를 직접 import). `src`가 마운트돼 있어 `docker exec`의 새 프로세스는 새
  코드를 읽는다. 반면 **`artemis-api` 서버 자신은 모듈을 캐시**하므로 API로 확인할 때는
  재시작할 것.
- **새 store 디렉터리로 시작할 것.** criterion 캐시가 그 옆에 생기므로 새 디렉터리 = 콜드 캐시.
- **베이스라인 보존**: `tmp/tte_vllm_remap2`, `output/circe_gate_fix`,
  `output/circe_scale_fix`, `output/conceptset_overlap/scoped_{gate,scale}_fix.json`.
- **`pgrep -f`의 대괄호는 명령줄 안 모든 등장에 필요하다.** 이번에도 자기 셸을 잡았다.
  장기 작업 폴링은 PID(`kill -0`)나 로그 진행으로 할 것.
- **`omx_wiki/index.md`는 병렬 세션의 미커밋 상태다.** 루트 저장소에서 다른 세션이
  작업 중이니 커밋 전 `git log`를 확인할 것.
- **±0.02 해상도 규칙은 여전히 유효하다.** 1뽑기로 작은 델타를 주장하지 말 것.
