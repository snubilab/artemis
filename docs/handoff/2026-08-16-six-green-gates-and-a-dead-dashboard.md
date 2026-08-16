# Handoff — 초록 게이트 여섯 개와 죽은 대시보드 — 2026-08-16

## Goal / context

앞선 핸드오프(`2026-08-14-four-of-five-diagnoses-were-wrong.md`)의 Next steps 중
**항목 3(드롭 계측)** 을 사용자가 선택해 수행한 세션. 그 뒤 다른 세션이 남긴 미커밋
변경 전부를 검토하고 커밋했다.

관통 주제는 앞 세션의 연장이다. 앞 세션은 "그럴듯한데 틀린 진단"이었다. 이번 세션은
**"확인했다고 말하지만 확인하지 않은 검사"** 다. 두 사례가 같은 모양이다 — 손으로 센
73은 어느 스토어로도 재현되지 않았고, 발행된 대시보드는 정적 게이트 여섯 개가 전부
초록인 채로 브라우저에서 죽어 있었다.

## Current state

- artemis: 브랜치 `fix/tte-a-drug-anchored-entry` · HEAD `e82b364` · 작업 트리 **깨끗**
- 루트 저장소: `main` · HEAD `c45499c` · **깨끗**
- 두 저장소 모두 **remote 없음** — `gh pr` 계열 불가
- 테스트: **100 failed / 2175 passed / 10 skipped** (`-p no:randomly`).
  실패 100건은 세션 시작 시점과 동일, **회귀 0**. 늘어난 통과분 2142 → 2175 는
  이번 세션 신규 10건 + 다른 세션 23건
- wiki 게이트: **9/9 PASS** (세션 중반 2건 FAIL이었다 — 아래)
- 실행 중: `artemis-api` / `ohdsi-webapi` / `broadsea-atlasdb` / `artemis-neo4j-v2` /
  `broadsea-hades` / `broadsea-content` / `tte-atlas-ts` / `tte-proxy`
- **vLLM은 여전히 죽어 있다.** 이번 세션의 어떤 작업도 LLM을 쓰지 않았으므로 결과에는
  영향이 없다. 재생성·재매핑을 돌릴 거라면 먼저 띄울 것:
  ```
  env -u PYTHONPATH -u PYTHONHOME /home/bilab/work/projects/vllm/venv/bin/python \
    -m vllm.entrypoints.openai.api_server --model google/gemma-4-E4B-it \
    --served-model-name google/gemma-4-E4B-it --host 0.0.0.0 --port 8000 \
    --max-model-len 32768 --dtype auto --enforce-eager \
    --gpu-memory-utilization 0.55 --enable-auto-tool-choice --tool-call-parser gemma4
  ```
  (`env -u` 는 GB10 필수 — `docs/debugging/2026-07-29_gb10_vllm_serving_facts.md`)
- **`artemis-api` 컨테이너는 아직 옛 `tte_service.py`를 들고 있다.** 앞 핸드오프와 동일하게
  미해결. 재생성을 하지 않기로 한 결정이 유지되므로 배포 타이밍 문제이지 검증 문제가 아니다

## Done this session

| 커밋 | 저장소 | 내용 |
| --- | --- | --- |
| `1f811b9` | artemis | **criterion 드롭 계측** — `_skippedCriteria` + `_generationCensus`, 항등식 게이트, 테스트 10건 |
| `b6e0b08` | artemis | 앞 핸드오프 정정 — 73 → 82, 4번째 드롭 경로, 항목 3 완료 표기 |
| `b5e3650` | artemis | (다른 세션 작업) Condition wrong-entity 게이트 |
| `e82b364` | artemis | (다른 세션 작업) ±0.02 해상 한계 `delta_verdict` |
| `c45499c` | root | 누락 노트 `note-007` + wiki 재빌드 — 죽어 있던 대시보드 복구 |

## Key decisions & why

### 73은 두 스토어를 섞은 수였다

앞 핸드오프는 39와 30을 "어떤 정의로도 재현 불가"로 판정하고 그 자리에 73을 놓았다.
**73도 재현되지 않는다.** 61(`isGroupLabel`)은 `tmp/mesh_fix`에서, 12(demographic-no-rule)는
`tmp/tte`에서 나온 값인데 `tmp/tte`의 `isGroupLabel`은 56이라 두 항이 같은 스토어에서
나올 수 없다. 그 문서가 Gotchas에 직접 적어둔 함정(두 스토어는 criterion id가 안 맞는다)을
자기 수치에서 밟았다.

`tmp/mesh_fix` 단독, criterion 653개:

| 경로 | 건수 |
| --- | ---: |
| `isGroupLabel` (inc 27 + exc 34) | 61 |
| demographic-no-rule (inclusion) | 13 |
| **exclusion-demographic** | **8** |
| **합계** | **82** |

### 드롭 경로는 3종이 아니라 4종이었다

exclusion 기준이 인구통계 도메인이면 `_build_demographic_rule`을 **호출조차 하지 않고**
버려진다. 그래서 만들 수 있었을 건까지 함께 사라지고, 어떤 집계에도 잡히지 않았다.
내용은 `Nursing or pregnant`, `Pre-menopausal women` 같은 **실제 제외 기준**이고,
제외를 잃으면 코호트가 프로토콜보다 넓어진다 — `_unmappedCriteria`가 막으려던 바로 그
실패인데 매퍼 이전 단계라 구조적으로 못 본다.

**이번 세션은 기록만 했고 동작은 바꾸지 않았다.** 고치면 코호트 인원이 바뀌므로 재생성 +
재채점이 따라오고, 그건 별개 결정이다.

### 게이트는 리스트가 아니라 항등식이다

`_skippedCriteria`가 리스트만 내놓으면 "빠뜨린 분기"는 잡히지 않는다. 그래서 반환되는
것은 합계 대조다:

```
total == mapped + unmapped + demographicRules + skipped
```

기록 없는 `continue`가 하나 더 생기면 어느 통에도 안 들어가 `total`과 어긋난다.
`test_should_balance_the_census_when_every_drop_shape_is_present`가 그걸 잡는다.
스토어 10개 시험 전부에서 성립을 확인했다.

손으로 셀 때마다 답이 달랐던 이유도 여기 있다: 13건 중 4건이 인구통계이면서 동시에
`isGroupLabel`이라 어느 통에 넣을지가 **분기 순서**로 결정되지 사람의 정의로 결정되지
않는다. 그래서 `_skippedCriteria`는 `reason`과 함께 `isGroupLabel`을 같이 싣는다.

### 정적 게이트 여섯 개가 초록인 채로 발행물이 죽어 있었다

다른 세션이 `plan-044`·`plan-045`에 2026-08-16 노트를 가리키는 evidence 링크 3개를 넣고
**그 노트를 만들지 않았다.** 링크는 pane+date로 해소되므로 `planView`가 던지고, 계획 행
46개가 전부 사라지고, `#record-fatal`(`position:fixed; z-index:1000`)이 발행 진입점
`docs/dashboard.html`을 덮어 클릭까지 막았다.

그동안 통과한 것들: 레코드 파싱, 양 surface 최신성, 템플릿 정합, 레거시 소유권 해소,
발행본 바이트 동일성. 빌드조차 `plan_rows=46 notes=6`으로 건강하게 보고했다.
**빌드는 링크를 해소하지 않는다. 브라우저만 해소한다.**

`note-007`을 써서 복구했고, 게이트 통과만 믿지 않고 브라우저를 직접 열어 확인했다 —
pageerror 2 → 0, `#record-fatal` hidden, 계획 행 **0 → 61**.

### 남의 작업을 커밋할 때 경로 지정으로만 스테이징했다

마지막 상태 확인(깨끗)과 커밋 사이에 작업 트리가 바뀌어 있었다. 다른 세션이 02:01–02:52에
artemis 6건 + 루트 34건을 만들었다. `git add .`나 `commit -a`를 썼다면 검토 없이 남의 작업을
삼켰을 것이다. 전부 diff를 읽고 테스트를 돌린 뒤 논리 단위로 나눠 커밋했다.

`ruff`는 파일별로 HEAD 대비 차분을 냈다. 신규 지적은 `I001`(import 정렬) 2건뿐이고,
남의 코드라 **고치지 않고 그대로 커밋했다** — `logic.py`, `build_conceptset_dashboard.py`.

## 측정

이번 세션은 **품질을 측정하지 않았다.** 계측·게이트·문서만 바뀌었다.

| 항목 | 값 |
| --- | --- |
| 조용한 드롭 (mesh_fix 653 criteria) | **82** (61 + 13 + 8) |
| 항등식 성립 | 10/10 시험 |
| 테스트 | 100 F / 2175 P / 10 S (`-p no:randomly`) |
| wiki 게이트 | 9/9 PASS |
| 대시보드 계획 행 | 0 → 61 |

`_generationCensus.unmapped`가 스토어 probe에서 0으로 나온 것은 **매퍼를 스텁으로 막았기
때문이지 실측이 아니다.** 이 필드는 다음 실제 생성 실행에서 처음 채워진다.

## Next steps (ordered, concrete)

1. **vLLM을 띄우고 6개 시험 재매핑** — `plan-044`(wrong-entity 게이트)와 `plan-045`가
   둘 다 **품질 이동 미측정** 상태다. 게이트가 실제로 recall/precision을 움직이는지는
   아직 아무도 모른다. `plan-044`가 `partial`인 유일한 이유가 이것이다.
   측정할 땐 `CRITERION_CACHE_ENABLED=false`.
2. **`_generationCensus.unmapped` 첫 실측** — 위 재매핑에서 같이 나온다. 0이 아니면
   매핑 예외가 실제로 발생하고 있다는 뜻이고, `_unmappedCriteria`와 수가 맞아야 한다.
3. **exclusion-demographic 8건 결정** — 기록만 되고 여전히 버려진다. 고치려면 exclusion
   분기에서도 `_build_demographic_rule`을 부르고, 제외쪽 `DemographicCriteriaList`를 CIRCE에
   어떻게 넣을지 설계해야 한다(`_build_grouped_inclusion_rule`은 inclusion 전제).
   코호트 인원이 바뀌므로 재생성 + 재채점 필요.
4. **T2DM 정의** — 앞 핸드오프 항목 1 그대로 보류 중. 노이즈 위 유일한 레버(+0.0267,
   p=0.064)이고 ADR + 캐시 끈 재실행이 필요한 의미론적 결정.
5. **프로덕션 반영 결정** — `artemis-api`가 옛 `tte_service.py`를 들고 있다. 배포 타이밍
   문제이지 검증 문제가 아니다.
6. **`I001` 2건** — 원한다면 `ruff check --fix src/agents/agent2/logic.py
   scripts/build_conceptset_dashboard.py`. 다른 세션 코드라 이번엔 손대지 않았다.

## How to verify / run

```bash
cd /home/bilab/work/projects/Broadsea/artemis

# 실행환경 게이트 — 다른 무엇보다 먼저
.venv/bin/python -m pytest tests/test_environment_matches_requirements.py -q

# 이번 세션 신규 테스트
.venv/bin/python -m pytest \
  tests/test_generation_census_accounts_for_every_criterion.py \
  tests/test_unmapped_criteria_are_recorded.py -q -p no:randomly
# 기대: 14 passed

# 다른 세션 신규 테스트
.venv/bin/python -m pytest \
  tests/test_wrong_entity_class_is_dropped.py \
  tests/test_conceptset_overlap_eval.py -q -p no:randomly
# 기대: 49 passed

# 전체 (기준선: 100 failed / 2175 passed / 10 skipped)
.venv/bin/python -m pytest tests/ -q -p no:randomly
```

**인구조사가 실제 스토어에서 82를 내는지** (DB·LLM 불필요, 매퍼 스텁):

```bash
.venv/bin/python - <<'PY'
import json, logging
logging.disable(logging.WARNING)
import src.agents.agent2.retriever as _r
class _Boom:
    def __init__(self, *a, **k): raise RuntimeError("probe: prefetch disabled")
_r.ConceptRetriever = _Boom
from src.services.tte_service import TTEService
from collections import Counter
svc = TTEService.__new__(TTEService)
svc._recommend_seeded_concept_set = lambda t, **k: {
    "name": t, "domain": "Drug",
    "expression": {"items": [{"concept": {"CONCEPT_ID": 1}}]}, "mapping_metadata": None}
svc._build_seeded_eligibility_rule = lambda **kw: {
    "rule": {"expression": {"CriteriaList": []}},
    "conceptSet": {"id": kw["codeset_id"], "name": "x",
                   "expression": {"items": [{"concept": {"CONCEPT_ID": 1}}]}},
    "_mapping_metadata": None}
agg, reasons = Counter(), Counter()
for s in json.load(open("tmp/mesh_fix/studies.json"))["studies"]:
    e = s.get("eligibility") or {}
    if not isinstance(e, dict): continue
    e = json.loads(json.dumps(e)); e.pop("structuredExpression", None)
    c = svc._build_seeded_target_circe(e)["_generationCensus"]
    assert c["total"] == c["mapped"] + c["unmapped"] + c["demographicRules"] + c["skipped"], s["id"]
    for k in ("total","mapped","unmapped","demographicRules","skipped"): agg[k] += c[k]
    reasons.update(c["skippedByReason"])
print(dict(agg)); print(dict(reasons))
PY
# 기대: skipped 82 / group-label 61 / demographic-no-rule 13 / exclusion-demographic 8
```

**wiki 게이트** (루트 저장소):

```bash
cd /home/bilab/work/projects/Broadsea
artemis/.venv/bin/python docs/wiki/build.py --content docs/wiki/content \
  --template docs/wiki/template.html --out docs/wiki/site
./docs/wiki/scripts/verify_surfaces.sh
# 기대: 9/9 PASS, exit 0
```

## Gotchas / constraints

- 🔴 **정적 게이트가 전부 초록이어도 발행물은 죽어 있을 수 있다.** 빌드는 evidence 링크를
  해소하지 않는다. wiki를 건드렸으면 `verify_surfaces.sh`를 끝까지 돌리고, 브라우저 게이트
  2개가 PASS인지 눈으로 확인할 것. `plan_rows=NN notes=NN` 빌드 출력은 건강 증명이 아니다.
- **plan 레코드에 새 날짜의 evidence 링크를 넣으면 그 날짜의 노트를 반드시 만들 것.**
  없으면 대시보드 전체가 죽는다. 링크는 pane+date로만 해소된다.
- **채점 아티팩트는 `tmp/mesh_fix/studies.json`에서 나온다**, `tmp/tte/studies.json`이
  아니다. criterion id가 안 맞는다. 앞 핸드오프가 이 함정을 적어놓고 자기 수치에서 밟았다.
- **`docs/tte_agent/` 원장의 `99 failed / 2164 passed / 7 skipped`는 재현하려 하지 말 것.**
  테스트 순서 랜덤화 때문이 아니다 — 확인해보니 `-p no:randomly` 유무와 무관하게
  **100 / 2175 / 10**으로 같다. 그 수치는 다른 세션이 자기 작업 **중간 상태**에서 찍은
  스냅샷이다(같은 원장 항목이 wrong-entity 테스트 파일을 15개 → 21개로 적고 있다).
  이제 어떤 트리에도 대응하지 않는다. 기준선은 **100 / 2175 / 10**.
- **`_generationCensus.unmapped`는 아직 실측된 적이 없다.** 스토어 probe의 0은 매퍼를
  스텁으로 막은 결과다.
- **매크로는 matched 쌍만 평균한다** (`per_criterion_macro`,
  `conceptset_overlap_eval.py:497`). 채점기가 바뀐 비교는 고정 모집단으로 인용하거나
  인용하지 말 것.
- **매핑 seed는 `sourceText or description`이지 `conceptSetName`이 아니다.**
- **±0.02 아래 델타는 이제 코드가 거부한다** — `delta_verdict()`. 단일 추출이면
  `"unresolved"`, 6뽑기 이상이어야 `"below floor"`로 수치를 인용할 수 있다.
- **`docs/tte_agent/*`는 git 제외 대상**(`.git/info/exclude`의 `/docs/*`)이라 커밋되지 않는다.
  `docs/wiki/**`와 `docs/dashboard.html`은 이미 추적 중이라 예외적으로 커밋된다.
- **`artemis/tmp/`는 root 소유.** 호스트에서 store를 못 고친다.
- **warm criterion 캐시가 매핑 수정을 통째로 가린다.** 측정할 땐 `CRITERION_CACHE_ENABLED=false`.
- **임베딩 경로는 실행 간 비결정적이다.** 1뽑기로 ±0.02 미만 델타를 주장하지 말 것.
- **`pgrep -f`의 괄호는 명령 안 모든 사본에 있어야 한다.**
- **다른 세션이 동시에 이 저장소를 편집한다.** `git add .` / `commit -a` 금지 —
  경로를 지정해 스테이징하고, 커밋 직전에 `git status`를 다시 볼 것.
