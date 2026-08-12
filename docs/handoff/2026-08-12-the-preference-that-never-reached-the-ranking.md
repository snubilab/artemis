# Handoff — 랭킹에 닿은 적 없는 선호, 그리고 두 번의 자기정정 — 2026-08-12 (2)

## Goal / context

같은 날 앞선 핸드오프(`2026-08-12-no-match-gate-and-a-measurement-instability.md`)의
**next step 1** — "Measurement 기준에 LOINC Lab Test를 우선 포함시키는 규칙을 `logic.py`의
finding-drop과 같은 자리에" — 를 구현하려 했다. 구현할 수 없었다. 대신 그 규칙이 이미
`retriever.py`에 존재하며 **수치적으로 죽어 있다**는 것을 찾아 고쳤다.

가장 값나가는 산출물은 수정 자체가 아니라 그 결함의 모양이다: **설정이 옳고, 코드가 있고,
테스트가 초록이고, 프로덕션에서 아무 일도 하지 않는다.**

## Current state

- **artemis**: 브랜치 `fix/tte-a-drug-anchored-entry` · HEAD `728adc5`
  (이번 세션 커밋 1건; 그 아래 이전 세션들의 미커밋 변경은 **그대로 남아 있다**)
- **커밋된 것** (`728adc5` `fix(agent2): the vocabulary preference never reached the ranking`):
  ```
   M src/agents/agent2/retriever.py                       -25줄 (중복 제거 포함)
  ?? tests/test_retriever_preference_scale.py             5건
  ?? tests/fixtures/retriever_platelet_candidates.json    실제 60후보 픽스처
  ```
- **여전히 미커밋** (이전 세션분, 섞지 말 것): `critic.py`, `logic.py`, `reranker.py`,
  `workflow.py`, `tte_service.py`, `scripts/build_*_dashboard.py`, 테스트 6종
- **테스트**: 100 failed / 2076 passed. 기준선 100/2071 + 신규 5건. **회귀 0.**
- **실행 중**: vLLM PID `134304` (`google/gemma-4-E4B-it`, 32k, `:8000`),
  `artemis-api` 컨테이너 Up
- **🔴 돌고 있는 작업**: 6개 시험 재매핑. 로그 `output/scale_fix.log`,
  store `tmp/scale_fix/studies.json`(콜드 캐시). 시작 2026-08-12T09:05Z.
  끝나면 아래 "채점 2단계"를 이어서 돌릴 것.

## 핵심 발견 — 선호 상수가 거리 스케일 대비 10배 작다

`_VOCAB_PREFERENCE`, `_PREFERRED_CLASSES`, `_PENALIZED_CLASSES`는 ±0.03~0.50의 **절대
상수**다. 정규화된 임베딩(거리 ~[0,2])에 맞춰진 값이다. 그런데 실제 컬렉션은
`omop_concepts_medcpt`이고 L2 거리가 **47.6~56.1**이다.

ARISTOTLE "Platelet count"에서:

```
1위 SNOMED Procedure          dist 47.637
...
9위 LOINC 3024929  (gold)     dist 51.481
12위 LOINC 3007461 (gold)     dist 52.019
```

간격 4.4. LOINC가 받을 수 있는 총 보정은 vocab −0.30 + preferred class −0.03 + 이름
−0.06 = **−0.39**. 약 10배 부족하다. 정렬은 사실상 순수 벡터 거리였고,
`"Measurement": {"LOINC": -0.30, "SNOMED": 0.20}`는 장식이었다.

**같은 원인의 부작용 둘:**
- `+0.50` 도메인 불일치 패널티도 거리 ~50 대비 1%다. `search()`는 `where` 절 없이 이
  패널티에만 의존하므로 **도메인 격리가 작동하지 않았다.**
- `standard_concept`가 Chroma 메타데이터에 **없다.** 191-198행의 표준 개념 선호
  (−0.10/+0.15)는 스케일과 무관하게 한 번도 실행된 적이 없다. **이건 안 고쳤다.**

## 왜 `logic.py`로는 불가능한가 (앞 핸드오프 1번 기각 근거)

생성 개념 → gold LOINC 사이에 **vocabulary 경로가 없다.** `omop_vocab`에서 측정:

| 확인 | 결과 |
|---|---|
| `concept_relationship` (4267147/37208696/4273307 ↔ 3007461/3024929) | **0행** |
| `concept_ancestor` (양방향) | **0행** |
| 4267147의 전체 관계 189+개 중 LOINC 대상 | **0개** |
| 4267147/37208696/4273307의 closure 안에 LOINC | **0개** |

`logic.py`는 *선택된* concept_ids만 받는다. 걸어갈 다리가 없으므로 어떤 사후 규칙으로도
LOINC를 만들어낼 수 없다. 고칠 수 있는 유일한 지점은 후보가 아직 살아 있는 검색 단계다.

## Key decisions & why

- **거리를 후보 집합 평균으로 나눈다** (`_distance_unit`). 곱셈 스케일에 **정확히** 불변
  (k·dist / k·mean)이고, 근소차를 뭉개지 않는다.
- **spread 비례 방식은 시도하고 버렸다.** 처음엔 `adj × (span/2)`로 넣었고 신규 테스트는
  전부 통과했다. 그런데 기존 `test_hba1c_loinc_beats_snomed`가 깨졌다 — 후보 2개가
  0.30/0.32로 거의 동점일 때 span=0.02라 선호가 **100배 축소**됐다. 원래 버그의 거울상이고,
  근소차야말로 선호가 결정해야 하는 자리다. **다시 spread로 돌아가지 말 것.**
- **평행이동 불변은 일부러 포기했다.** 모든 거리에 100을 더하면 실제로 전부 멀다는 뜻이고,
  그 국면에서는 선호가 결정하는 게 맞다. 어차피 순수 offset을 내는 임베딩 모델은 없다.
- **`search()`의 채점 사본을 제거**하고 `_score_candidates` 하나로 합쳤다. `reranker.py`의
  `rerank_topn`/`rerank_topn_batch`가 이미 같은 함정이었다(앞 핸드오프 2번).
  `search()`는 workflow를, `batch_search()`는 tte_service를 먹인다. 둘 다 살아 있다.

## 이번 세션에 두 번 틀렸다 (둘 다 결론이 바뀌는 종류)

1. **`allCandidates`를 검색 후보 풀로 읽었다.** 실제로는 `tte_service.py:6248`에서
   `_fetch_concept_candidates(mapping_result.concept_ids)` — Agent 2의 **출력**으로 사후
   구성된다(그래서 `score`가 전부 0.0이었다). 그 위에 "gold가 풀에 있으면 recall>0,
   26/26 대 5/5 완벽한 분리"를 세웠는데, **사실상 동어반복**이었다.
   완벽한 분리를 의심해 closure 반례는 확인했지만 필드 출처를 확인하지 않았다.
   → **`allCandidates`로 검색 품질을 논하지 말 것.** 후보 풀은 어디에도 기록되지 않는다.
2. **도메인 패널티가 dropout의 원인이라고 추정했다.** 아니다. LEADER "Chronic heart
   failure"의 gold 316139는 chroma domain이 `Condition`으로 힌트와 일치해 패널티를 안 받는다.
   실제 원인은 이름 정확일치 보정(−0.15)이 이제 강력해져서, 질의와 글자 그대로 맞는 좁은
   개념이 넓은 gold를 추월한 것이다.

## 측정 — 검색 랭킹만, 품질 지표는 아직 아니다

6개 시험 · gold와 짝지어진 125개 기준 · `queryUsed` 기록이 있는 것 전부.
"before"는 구공식 복제본, "after"는 **수정된 프로덕션 `search()` 자체**.
복제본이 프로덕션을 재현하는지 4개 프로브로 자기검증한 뒤에만 비교했다
(첫 시도에서 복제본이 어긋나 스크립트가 비교를 거부했다 — word-stem 보정이 매칭되는
**질의 단어마다** −0.06을 누적하는데 복제본은 한 번만 뺐다).

| 도메인 | n | gold@5 | gold@15 | MRR |
|---|---|---|---|---|
| **Measurement** | 31 | 11 → **29** | 19 → **30** | 0.253 → **0.876** |
| Condition | 70 | 19 → 21 | 26 → **33** | 0.152 → 0.188 |
| Drug | 14 | 1 → 2 | 1 → 2 | 0.071 → 0.107 |
| Procedure | 9 | 1 → 0 | 5 → 6 | 0.076 → 0.079 |

125건 중 **45 개선 / 16 악화.** recall 0이던 Measurement 5건 중 4건이 gold를 1~2위로
올렸다(Platelet 9→1, CrCl 5→2, eGFR ×2 None→1). 남은 1건은 CAROLINA "Glucose"로
여전히 top-15 밖이다.

**대가**: 3건이 top-15 **밖으로** 떨어졌다 — LEADER Procedure "Peripheral artery bypass
OR Angioplasty" 4→None, LEADER Condition "Chronic heart failure" 13→None (2건).
리랭커가 아예 못 보게 된다.

**아직 모르는 것**: 최종 recall/precision. 검색 랭킹은 리랭커 선택의 상류일 뿐이다.
Platelet은 수정 전에도 gold가 top-15 안(9위)이었는데 리랭커가 SNOMED를 골랐다 —
랭킹 개선이 선택 개선을 보장하지 않는다. 그래서 재매핑을 돌리고 있다.

## Next steps (ordered, concrete)

1. **돌고 있는 재매핑을 채점하고 앞 arm과 비교할 것.** 아래 "채점 2단계".
   비교 기준은 `output/conceptset_overlap/scoped_gate_fix.json`(= 앞 세션 최종 arm).
   **±0.02 해상도 규칙은 그대로 유효하다** — 1뽑기로 작은 델타를 주장하지 말 것.
2. **top-15 밖으로 떨어진 3건을 볼 것.** 이름 정확일치 −0.15가 이제 무차원 ~1.0 스케일에서
   지배적이다. 상수 재조정이 필요할 수 있는데, **재조정 전에 반드시 오프라인 랭킹
   시뮬레이션으로 확인할 것**(방법은 아래).
3. **`standard_concept`가 Chroma 메타데이터에 없다.** 채워 넣고 재색인하면 −0.10/+0.15
   보정이 처음으로 살아난다. 이번 수정으로 그 크기가 유의미해졌으므로 영향이 크다.
4. **CAROLINA "Glucose"는 여전히 미해결** (수정 전후 모두 top-15 밖). gold 1개짜리이고
   생성 closure는 185개다. 별도 사례로 볼 것.
5. **앞 핸드오프의 2·3·5·6번은 손대지 않았다** — 개체가 틀린 매핑(History of X /
   AF ablation), MeSH 별칭(BI 10773), `_unmappedCriteria.reason` 빈 문자열,
   `CriticCache`의 `ttl_hours or env_default`.

## How to verify / run

```bash
cd /home/bilab/work/projects/Broadsea/artemis

# 실행환경 게이트 — 다른 무엇보다 먼저
.venv/bin/python -m pytest tests/test_environment_matches_requirements.py -q

# 이번 세션 테스트 (5건)
.venv/bin/python -m pytest tests/test_retriever_preference_scale.py -q

# 이 수정이 건드리는 기존 테스트 (반드시 같이)
.venv/bin/python -m pytest tests/test_map_retriever_scoring.py tests/test_batch_prefetch.py -q

# 전체 (기준선: 100 failed / 2076 passed)
.venv/bin/python -m pytest tests/ -q -p no:randomly
```

**채점 2단계** (재매핑이 끝난 뒤):

```bash
.venv/bin/python scripts/export_circe_from_store.py \
  --store tmp/scale_fix/studies.json --out output/circe_scale_fix
.venv/bin/python scripts/conceptset_overlap_eval.py --mode closure \
  --generated-dir output/circe_scale_fix \
  --out output/conceptset_overlap/scoped_scale_fix.json
```

**arm 검증** (3시간짜리를 시작하기 전에 항상):

```bash
docker exec -i artemis-api python -u - <<'PY'
import sys, inspect; sys.path.insert(0,'/app')
from src.agents.agent2 import retriever as R
assert hasattr(R, "_distance_unit"), "OLD retriever"
assert "_score_candidates" in inspect.getsource(R.ConceptRetriever.search), "search has its own copy"
top = [c.concept_id for c in R.ConceptRetriever().search("Platelet count", n_results=5,
                                                         domain_hint="Measurement")]
assert 3024929 in top or 3007461 in top, f"gold LOINC missing from top-5: {top}"
print("ARM VERIFIED", top)
PY
```

## Gotchas / constraints

- **`allCandidates`는 검색 후보 풀이 아니다** (위 자기정정 1). 후보 풀은 어디에도 저장되지
  않으므로, 검색 단계를 평가하려면 `ConceptRetriever.search`를 직접 돌려야 한다.
- **랭킹 시뮬레이션을 다시 만들 때는 복제 스코어러가 프로덕션과 같은지 먼저 증명할 것.**
  안 그러면 허수아비와 비교하게 된다. word-stem 루프의 `break`가 **안쪽** 루프에만 걸려
  있어 질의 단어마다 −0.06이 누적되는 게 첫 함정이었다.
- **`pgrep -f`의 대괄호는 명령줄 안 모든 등장에 필요하다.** 이번에도 자기 셸을 잡았다 —
  같은 줄에 `docker exec ... regenerate_structured_expression.py`라는 괄호 없는 사본이
  있었기 때문. 장기 작업 폴링은 PID(`kill -0`)나 로그 진행으로 할 것.
- **재매핑은 in-process다** (`regenerate_structured_expression.py:98`이 `TTEService`를
  직접 import). `docker exec`가 새 프로세스를 띄우고 `src`는 마운트돼 있으므로 서버
  재시작은 불필요하다. 반면 **`artemis-api` 서버 자신은 모듈을 캐시한다** — API를 통해
  확인할 때는 재시작할 것.
- **베이스라인 보존**: `tmp/tte_vllm_remap2`, `output/circe_gate_fix`,
  `output/conceptset_overlap/scoped_gate_fix.json`은 건드리지 말 것.
- **이번 세션 산출물**: `tmp/scale_fix/`, `output/scale_fix.log`,
  (예정) `output/circe_scale_fix/`, `output/conceptset_overlap/scoped_scale_fix.json`.
- **`adjusted_score`는 이제 무차원(~1.0)이고 거리 스케일이 아니다.** 임계값으로 쓰는 코드는
  없고 같은 질의 안 후보끼리만 비교된다. 임계값을 새로 걸려면 이 점을 먼저 볼 것.
