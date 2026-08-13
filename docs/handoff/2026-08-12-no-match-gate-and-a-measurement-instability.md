# Handoff — "매칭 없음" 게이트, 되돌린 스키마, 그리고 평가 해상도의 한계 — 2026-08-12

## Goal / context

2026-08-11 핸드오프의 P0 두 건(계획 보드 33행 critic 스키마, 35행 no-match 게이트)을 구현하고
gold(TROY v1.1 CIRCE) 대비로 측정했다. 게이트는 남았고 스키마는 측정 후 되돌렸다. 가장 값나가는
산출물은 두 기능이 아니라 **평가 자체의 해상도가 ±0.02라는 사실**이다. 그게 다음 작업의 전제다.

## Current state

- **artemis**: 브랜치 `fix/tte-a-drug-anchored-entry` · HEAD `7837274` · 커밋 없음(전부 미커밋)
- **실행 중**: vLLM PID `134304` (`google/gemma-4-E4B-it`, 32k, `:8000`), 문서 서버 PID `4173532`,
  `artemis-api` 컨테이너 Up
- **커밋 안 한 변경** — 이번 세션분은 `logic.py`/`reranker.py`/`critic.py` + 테스트 4종:
  ```
   M src/agents/agent2/critic.py      <- 캐시 버전 장치만 (프롬프트는 HEAD 그대로)
   M src/agents/agent2/logic.py       <- drop_qualitative_findings 추가 (순수 add, 65줄)
   M src/agents/agent2/reranker.py    <- no-match 게이트 + top-N 프롬프트 중복 제거
   M src/agents/agent2/workflow.py    <- (이전 세션) + Measurement finding-drop 호출 1곳
  ?? tests/test_reranker_no_match_gate.py                 8건
  ?? tests/test_measurement_finding_class_is_dropped.py   7건
  ?? tests/test_critic_prompt_version_invalidates_cache.py 4건
  ```
  `M scripts/build_diagnosis_dashboard.py`는 이번 세션과 무관하다(어제 핸드오프와 동일). 섞지 말 것.
- **테스트**: 100 failed / 2071 passed. 실패 100건은 전부 기존 것(기준선 100/2052 + 신규 19건).

## Done this session

1. **no-match 게이트** (`reranker.py`). top-N 프롬프트에 `query_has_match` 필드와 음성 예시 1개 추가.
   6개 시험에서 6개 기준을 기각했고, 기각분은 `_unmappedCriteria`로 기록된다.
2. **top-N 프롬프트 중복 제거.** 같은 프롬프트가 `rerank_topn`과 `rerank_topn_batch`에 각각
   적혀 있었고 **파이프라인이 부르는 건 batch 쪽**이었다. `TOPN_SYSTEM_PROMPT` 하나로 통합.
   한쪽만 고치면 유닛 테스트만 초록이 되는 구조였다.
3. **Measurement finding-drop** (`logic.py:drop_qualitative_findings`). Drug의
   `roll_up_to_rxnorm_ingredients`와 같은 자리의 Measurement판.
4. **critic 캐시 버전** (`_CRITIC_PROMPT_VERSION` → `critic_signature()`). 두 캐시 모두 프롬프트를
   키에 넣지 않아, 프롬프트를 고치면 구결과가 조용히 재생된다. 전용 테스트 4건.
5. **critic 그룹 스키마: 구현 → 측정 → 되돌림.** 아래 참조.

## Key decisions & why

- **critic 그룹 스키마는 측정하고 버렸다.** 후보당 1엔트리를 그룹 단위로 바꿔 출력을 후보 수에서
  뗐고, 실제로 A/B에서 출력 2,790→1,287자(2.2배), 스모크 wall clock 695→237초(2.9배)였다.
  그런데 ARISTOTLE per-criterion recall이 gate-only 대비 **−0.043**. 속도를 정확도로 샀다.
  되돌렸고 `/tmp/artemis_arm_new/critic_grouped_REJECTED.py`에 증거로 남겼다(재부팅 시 소멸).
- **게이트 프롬프트는 최소 델타로 쓴다.** 처음엔 STEP1/STEP2로 재구성하고 "후보가 이 용어를
  *denote* 하는가"를 물었다. 그 문구가 어휘 특이성 판단과 경쟁한다고 판단해 원본 두 문장을
  글자 그대로 두고 거부 선택지 + 음성 예시만 얹는 형태로 바꿨다. **다시 장황하게 쓰지 말 것.**
- **Measurement에서 `Clinical Finding` 클래스는 뺀다.** `Platelet count - finding`(4273307)과
  `Platelets [#/volume] in Blood`(3007461)는 **둘 다 domain=Measurement, 둘 다 standard**라
  도메인 필터로 안 갈린다. 갈리는 건 `concept_class_id` 하나뿐이고, finding은 값 비교가 불가능한
  데다 자손 177개가 전부 소견이라 closure가 터진다.
  **도메인 게이트가 이 규칙의 핵심이다** — `Clinical Finding`은 Condition 도메인 대부분에서
  올바른 클래스다(심근경색이 그것). Measurement 밖에 적용하면 매핑이 지워진다.

## 실험 기록 — ARISTOTLE(study 3) arm 대장

숫자는 전부 `output/conceptset_overlap/`의 파일에서 다시 읽은 것이다. 모든 arm이 같은 날,
같은 vLLM(PID 134304), 같은 입력 store(`tmp/tte_vllm_remap2/studies.json`)의 사본, 콜드
criterion 캐시로 돌았고 `workflow.py`/`tte_service.py`는 arm 간 동일하게 고정했다.

| arm | critic | reranker | recall | precision | zero | 산출물 |
| --- | --- | --- | --- | --- | --- | --- |
| baseline (2026-08-10, warm cache) | HEAD | HEAD | 0.636 | 0.357 | 2 | `scoped_gemma.json` |
| **control** (오늘 재실행) | HEAD | HEAD | 0.636 | 0.356 | 2 | `scoped_gate_ctl.json` |
| grouped + gate | 그룹 스키마 | 장황 게이트 | 0.602 | 0.348 | 4 | `scoped_gate_new.json` |
| gate only (장황) | HEAD | 장황 게이트 | 0.645 | 0.353 | 3 | `scoped_gate_only.json` |
| gate minimal | HEAD | 최소 게이트 | 0.625 | 0.346 | 3 | `scoped_gate_min.json` |
| **채택** gate min + finding-drop | HEAD | 최소 게이트 | 0.625 | 0.347 | 3 | `scoped_gate_fix.json` |

읽는 법 — 이 표는 델타를 증명하지 않는다. 아래 해상도 절이 그 이유다. 그러나 **원인 분리**에는
쓸모가 있었고, 그 방법이 이 세션에서 재사용할 값어치가 있는 부분이다:

1. `control`을 저장된 baseline으로 때우지 않고 **구코드를 오늘 다시 돌렸다**. 이게 없으면
   run-to-run 변동과 캐시 온도가 코드 효과에 섞인다.
2. 두 변경이 함께 든 arm(`grouped + gate`)만으로는 어느 쪽이 손해를 냈는지 모른다.
   **`gate only` arm이 그걸 갈랐다** — 그 arm에서도 Platelet 결함이 그대로 재현돼,
   처음에 critic 스키마 탓으로 돌렸던 진단이 뒤집혔다.
3. 그다음 프롬프트 문구를 의심해 `gate minimal`을 만들었는데 **그것도 아니었다**.
   결국 후보 목록을 고정하고 리랭커만 5회 뽑아보는 프로브가 답을 줬다(아래).

교훈: arm을 하나 더 만들기 전에, **바꾼 것 하나만 다른 arm이 실제로 존재하는지** 확인할 것.
이 세션은 그걸 두 번 어겨서 두 번 잘못 귀인했다.

### critic은 실제 파이프라인에서 거의 항상 돈다 (앞선 보고 정정)

세션 중간에 "critic은 KG 앵커 ≤ 10이면 스킵되므로(`workflow.py:953`) 그룹 스키마의 영향
범위가 좁다"고 보고했는데 **틀렸다.** 그 판단은 `process_with_details`를 pre-fetch 없이 직접
부른 단발 프로브 6건에서 나온 것이고, 실제 경로는 `_build_seeded_target_circe`가 배치
pre-fetch로 후보 60개를 넘겨주므로 KG 앵커가 훨씬 많다. 6개 시험 실행 로그에서:

```
criteria processed : 296
critic ran         : 249
critic skipped     :   6      (rg -c 'Critic SKIPPED' output/gate_six_fix.log)
```

즉 **critic은 사실상 모든 기준에서 돈다.** 그룹 스키마의 −0.043은 좁은 구석이 아니라 넓은
면적에 걸린 값이고, 되돌린 판단은 그만큼 더 강해진다. 단발 프로브로 파이프라인 경로의
빈도를 추정하지 말 것 — 경로가 다르면 분포도 다르다.

## 가장 중요한 발견 — 이 지표의 해상도는 ±0.02다

arm을 세 개나 태우고도 원인을 못 찾은 뒤, **후보 목록을 고정하고 리랭커만 반복 호출**했다.
`Platelet count`(domain=Measurement)의 후보 60개를 한 번 뽑아 고정한 뒤 같은 입력으로
온도 0에서 5회씩:

```
ORIGINAL 프롬프트 (변경 전) : SNOMED-finding(4273307) 4/5,  LOINC(3007461) 1/5
MINIMAL 게이트              : SNOMED-finding(4273307) 5/5,  LOINC(3007461) 0/5
```

이 프로브가 세션에서 가장 값싼 측정이었다(LLM 호출 10회, 2분). 그전까지 태운 arm 3개는
각각 25분~2시간짜리였고, 셋 다 이 질문에 답하지 못했다. **arm을 늘리기 전에 의심하는
컴포넌트만 떼어 반복 호출해 볼 것.**

**원본 프롬프트조차 근소차에서 흔들린다.** 그리고 그 한 번의 뒤집힘이 closure를 8 vs 184로
바꾸고, ARISTOTLE 23쌍 기준 macro recall을 **0.0217** 움직인다.

여기서 나오는 규칙 세 개:

- **arm당 1뽑기로 ±0.02를 주장하지 말 것.** 이번 세션의 중간 델타(−0.011, +0.009)는 전부
  뒤집힘 1건보다 작다.
- **`control − baseline = ±0.001`을 안정성의 증거로 읽지 말 것.** 두 실행이 같은 면을 뽑았을 뿐이다.
  실제로 그렇게 읽었다가 귀인을 두 번 틀렸다(그룹 스키마 탓 → 리랭커 프롬프트 탓 → 둘 다 아님).
- **근소차를 LLM에 맡기지 말 것.** LOINC냐 SNOMED-finding이냐는 프롬프트로 밀 문제가 아니라
  결정론적 규칙으로 정할 문제다. 그래서 4번을 프롬프트가 아니라 `logic.py`에 넣었다.

## 6개 시험 최종 측정 (gate + finding-drop vs 2026-08-10 baseline)

| trial | recall | precision |
|---|---|---|
| ARISTOTLE | 0.636 → 0.625 (−0.011) | 0.357 → 0.347 (−0.010) |
| CARMELINA | 0.573 → 0.561 (−0.011) | 0.539 → 0.562 (+0.023) |
| CAROLINA | 0.552 → 0.560 (+0.007) | 0.508 → 0.517 (+0.009) |
| EMPA-REG | 0.373 → 0.370 (−0.002) | 0.387 → 0.390 (+0.003) |
| LEADER | 0.595 → 0.623 (+0.028) | 0.598 → 0.604 (+0.006) |
| PLATO | 0.858 → 0.858 (+0.000) | 0.692 → 0.699 (+0.007) |
| **MACRO** | **0.598 → 0.600 (+0.002)** | **0.513 → 0.520 (+0.006)** |

`recall +0.002 = 0.31 SE`, `precision +0.006 = 1.46 SE` (n=6 시험 기준). **둘 다 0과 구별되지 않는다.**
정직한 결론: 품질 지표는 움직이지 않았고, 나빠지지도 않았다.

지표와 무관하게 성립하는 것:

- 기각된 6개 기준은 이제 개념을 만드는 대신 갭으로 기록된다
- Measurement 집합에서 finding 6개가 빠졌다(closure 폭발 제거: Platelet 184 → 7)
- critic 실패 0건

## Next steps (ordered, concrete)

1. **Platelet 계열의 recall 손실은 아직 남아 있다.** finding-drop이 precision 피해(genN 184→7)는
   없앴지만 recall은 0.000 그대로다 — 리랭커가 LOINC `3007461`을 애초에 안 고르기 때문이다.
   baseline은 그걸 골라서 0.500이었다. Measurement 기준에 **LOINC Lab Test를 우선 포함**시키는
   규칙이 finding-drop과 짝이 되어야 한다. `logic.py`의 같은 자리.
2. **`History of X` / `Atrial fibrillation ablation` 계열 — 수식어만 맞고 개체가 틀린 매핑.**
   `History of stroke`가 LOINC 설문 개념(`History of family member diseases Narrative` 등)으로
   가고, ARISTOTLE의 gold `Atrial fibrillation and flutter`가 `Atrial fibrillation ablation`과
   짝지어진다(zero-overlap). 게이트는 이걸 못 잡는다 — 관련된 후보가 있으면 "예"라고 답한다.
3. **`BI 10773`가 이제 게이트에 기각된다.** EMPA-REG entry의 개발코드다. 어제 3번 항목(MeSH 별칭
   배선)이 미해결이라 그렇다. 틀린 분자(`1254065 CHF-6366 metabolite`)를 내는 것보다는 낫지만
   entry가 비었다. 별칭 배선을 고치면 기각이 아니라 empagliflozin이 나와야 한다.
4. **게이트 기각 6건 중 2건은 재검 대상.** `Contraindication against clopidogrel use`와
   `Drug-naïve or pre-treated (...)`는 복합 기준이라 단일 개념집합으로 표현 불가한 쪽에 가깝지만,
   전자는 실기준일 수 있다. `_unmappedCriteria`에 남아 있으니 목록으로 확인할 것.
5. **`_unmappedCriteria`의 `reason`이 빈 문자열로 들어간다.** `tte_service.py`가 `str(e)`를
   쓰는데 예외 메시지가 비어 있다. 갭 기록의 값어치를 깎는다.
6. **`CriticCache.__init__`의 `ttl_hours or env_default`가 명시적 `0`을 24시간으로 바꾼다.**
   기존 100개 실패 중 `test_perf_m5_critic_cache.py::test_expired_entry_returns_none`의 원인.
   이번 세션 변경과 무관.

## How to verify / run

```bash
cd /home/bilab/work/projects/Broadsea/artemis

# 실행환경 게이트 — 다른 무엇보다 먼저
.venv/bin/python -m pytest tests/test_environment_matches_requirements.py -q

# 이번 세션 테스트 (19건)
.venv/bin/python -m pytest tests/test_reranker_no_match_gate.py \
  tests/test_measurement_finding_class_is_dropped.py \
  tests/test_critic_prompt_version_invalidates_cache.py -q

# 전체 (기준선: 100 failed / 2071 passed — 실패는 전부 기존 것)
.venv/bin/python -m pytest tests/ -q -p no:randomly

# 게이트가 실경로에서 도는지 (컨테이너)
docker exec -i -e CRITERION_CACHE_ENABLED=false artemis-api python -u - <<'PY'
import sys; sys.path.insert(0,'/app')
from src.services.tte_service import TTEService
svc = TTEService.__new__(TTEService)
circe = svc._build_seeded_target_circe({
    "targetCohortName": "apixaban",
    "observationWindow": {"PriorDays": 365, "PostDays": 0},
    "inclusionCriteria": [
        {"id":"1","domain":"Condition","sourceText":"qqzzxx nonexistent clinical term"},
        {"id":"2","domain":"Condition","sourceText":"Acute coronary syndrome"}],
    "exclusionCriteria": []})
print("unmapped:", circe.get("_unmappedCriteria"))   # 1번이 여기 있어야 한다
PY
```

**재매핑 + 채점 3단계** (arm 하나당 6개 시험 약 3시간):

```bash
docker exec artemis-api bash -lc 'mkdir -p /app/tmp/<NEW> && cp /app/tmp/tte_vllm_remap2/studies.json /app/tmp/<NEW>/studies.json'
nohup docker exec -e TTE_STORE_PATH=/app/tmp/<NEW>/studies.json artemis-api \
  python -u /app/scripts/regenerate_structured_expression.py --apply --studies 1,2,3,8,9,10 \
  > output/<LOG>.log 2>&1 &
.venv/bin/python scripts/export_circe_from_store.py --store tmp/<NEW>/studies.json --out output/circe_<NEW>
.venv/bin/python scripts/conceptset_overlap_eval.py --mode closure \
  --generated-dir output/circe_<NEW> --out output/conceptset_overlap/scoped_<NEW>.json
```

## Gotchas / constraints

- **새 store 디렉터리로 시작할 것.** criterion 캐시가 그 옆에 생기므로 새 디렉터리 = 콜드 캐시다.
  `_CRITIC_PROMPT_VERSION`도 키에 들어가지만 둘 다 걸어두는 편이 안전하다.
- **arm을 바꿀 때는 모듈 심볼로 검증할 것.** 잘못된 arm이 조용히 도는 게 유일하게 "믿을 만한
  숫자 + 오류 없음"을 만드는 실패다. 이번엔 `hasattr(critic,'CriticGroup')` /
  `hasattr(reranker,'TOPN_SYSTEM_PROMPT')`로 판정하고 불일치 시 SystemExit 했다.
- **다른 5개 시험이 arm 간 동일한지 md5로 확인할 것.** study 3만 재매핑했는데 다른 파일이
  바뀌었다면 뭔가 잘못된 것이다.
- **`tmp/`는 컨테이너가 root로 쓴다.** 호스트에서 쓰려면 `output/`을 쓸 것.
- **베이스라인 보존**: `tmp/tte_vllm_remap2`, `output/circe_gemma`,
  `output/conceptset_overlap/scoped_gemma.json`은 건드리지 말 것.
- **이번 세션 산출물**: `output/conceptset_overlap/scoped_gate_{ctl,only,min,new,fix}.json`,
  `output/gate_*.log`, `output/gate_aristotle.manifest.txt`.
  `scoped_gate_ctl`은 오늘 재실행한 OLD 코드 control arm이다 — 다음 비교의 기준으로 쓸 수 있다.
- **`pgrep -f`는 자기 자신을 잡는다.** 첫 글자를 대괄호로(`'[r]egenerate_structured'`).
```
