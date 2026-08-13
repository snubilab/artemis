# exact-ingredient match vs 임베딩 — entry seed 귀속 측정 (2026-08-10)

`2026-08-10-entry-drug-resolution-and-eval-scope.md`의 Next step 2. 가설:
**"임베딩이 고유명사에 약하다"** — 미증명 상태였고, 반증 근거(apixaban/liraglutide/ticagrelor는
임베딩이 이미 맞힘)도 함께 적혀 있었다.

## 결론

**가설은 일반 명제로는 성립하지 않는다.** 유효하게 테스트된 5개 seed 중 3개는 임베딩이 이미
정답을 냈고, exact match가 답을 바꾼 것은 **linagliptin 하나**(대소문자 변형 2건 = 시험 2개)다.

| seed | exact ON | 대조군(임베딩) ×3 | 판정 |
| --- | --- | --- | --- |
| liraglutide | `40170911 liraglutide` | 동일 ×3 | 임베딩이 이미 맞힘 |
| ticagrelor | `40241186 ticagrelor` | 동일 ×3 | 임베딩이 이미 맞힘 |
| apixaban | `43013024 apixaban` | 동일 ×3 | 임베딩이 이미 맞힘 |
| `BI 10773` | `1254065 CHF-6366 .beta.-2 metabolite` | 동일 ×3 | **테스트되지 않음** (아래) |
| `Linagliptin` | `40239216 linagliptin` | **`1580747 sitagliptin`** ×3 | exact match가 가름 |
| `linagliptin` | `40239216 linagliptin` | **`1580747 sitagliptin`** ×3 | exact match가 가름 |

대조군은 6개 seed 전부에서 3회 반복 결과가 동일했다 — 컨테이너 실행은 결정적이다.

### BI 10773은 이 실행에서 테스트되지 않았다

프로브가 `_recommend_seeded_concept_set(seed, expected_domain=None)`를 호출하며
`alias_candidates`를 넘기지 않았다. MeSH 별칭 경로(`_alias_ingredient_mapping`,
`tte_service.py:5882`)는 그 인자가 있어야 동작하므로 **양쪽 arm 모두 임베딩으로 떨어졌고**,
둘 다 같은 값이 나온 것이다. 이 행은 커밋 `7837274`(MeSH 별칭)의 효과에 대해 아무것도 말하지 않는다.
다만 별칭 경로가 없을 때 임베딩이 개발코드에 무엇을 답하는지는 재확인해준다 —
`CHF-6366 .beta.-2 metabolite`. 이는 `_alias_ingredient_mapping` docstring이 이미 적어둔 값과 같다.

## 리랭커를 gemma(vLLM)로 바꿔 재측정 — 결과 동일

1차 측정의 리랭커는 **OpenRouter의 gpt-4o**였다(`LLM_MODEL=gpt-4o`). 로컬 모델로 바꿔야 하므로
`artemis/.env`의 `LLM_MODEL`을 `vllm/google/gemma-4-E4B-it`로 교체하고 전 구간을 재측정했다.

| | gpt-4o 리랭커 | gemma-4-E4B-it 리랭커 |
| --- | --- | --- |
| 답이 바뀐 seed | 2/6 (linagliptin ×2) | **2/6 (동일)** |
| 반환 개념 | 위 표와 동일 | **전부 동일** |
| 대조군 3회 재현 | 6/6 seed 동일 | **6/6 seed 동일** |
| LLM 목적지 | OpenRouter | **vLLM 19건, OpenRouter 0건** |

**결론은 리랭커에 의존하지 않는다.** 검색기가 linagliptin을 후보 20개에 아예 올리지 않으므로
어떤 리랭커도 고를 수 없다 — 모델을 바꾸는 것은 이 결함을 건드리지 못한다.

`resolve_model()`이 해석한 값을 실행 로그에 `PROVENANCE resolved_model=...`로 남겼다.
`vllm/` 접두사가 없으면 OpenRouter로 조용히 넘어가므로(`src/utils/llm.py`), 접두사 없는 모델명으로
측정하고 로컬 모델이라 라벨링하는 사고를 막으려면 이 줄이 있어야 한다.

## linagliptin이 실패하는 기전

로그가 3단으로 보여준다.

```
[Retriever] 'linagliptin' → top: sitagliptin 32.1 MG (ID=1235494, dist=83.470, ...)
[Agent 2][LINEAGE] retriever → 20 candidates. Top-5: [sitagliptin 32.1 MG, dapagliflozin/
    metformin/saxagliptin ..., saxagliptin 2.5 MG ...]
[Agent 2][LINEAGE] reranker → 0 selected: []
[Agent 2] Force-included Top-1: sitagliptin 32.1 MG
[Logician] Rolled up drug concepts to RxNorm ingredients: [1235494] -> [1580747]
```

1. MedCPT 검색기가 `linagliptin` 질의에 **sitagliptin을 1위로** 반환한다. top-20 후보에
   linagliptin 자신이 **없다**. 같은 DPP-4 계열이 임베딩 공간에서 서로 이웃이다.
2. 리랭커는 후보 전부를 **기각한다**(`0 selected`). 판단 자체는 옳았다.
3. 그 위에서 **`Force-included Top-1`** 폴백이 기각을 덮고 1위를 집어넣는다.

즉 결함은 "임베딩이 약하다" 하나가 아니라, **"매치 없음"을 "자신 있게 틀림"으로 바꾸는
force-include 폴백**이 겹친 것이다. 리랭커가 0개를 고른 경우를 빈 결과로 두었다면
exact match 없이도 오답 대신 무답이 됐을 것이다.

## 실행 방법 — 반드시 컨테이너에서

```bash
docker exec -i -e CRITERION_CACHE_ENABLED=false artemis-api python -u - <<'PY'
# svc._recommend_seeded_concept_set(seed, expected_domain=None)
# ARTEMIS_DISABLE_EXACT_INGREDIENT_MATCH 을 "0"/"1" 로 토글
PY
```

### 이 측정을 무효로 만들 뻔한 네 가지

1. **`scripts/rebuild_entry_concept_sets.py`로는 ablation을 할 수 없다.**
   그 스크립트는 `svc._exact_ingredient_mapping(target)`를 **직접** 호출한다
   (`rebuild_entry_concept_sets.py:81`). 플래그를 검사하는 게이트는 `tte_service.py:6176`이고
   스크립트는 그곳을 지나가지 않으므로, 플래그를 켜든 끄든 **출력이 동일**하다. 그 결과를
   "ablation 효과 없음"으로 읽으면 켜진 적 없는 노브에서 결론을 얻게 된다.
   (같은 스크립트의 docstring은 "through the production mapper
   (`TTEService._recommend_seeded_concept_set`)"라고 적어뒀는데 코드는 그렇게 하지 않는다.)
2. **캐시가 대조군을 오염시킨다.** production 순서는 exact → alias → 캐시 → 임베딩이고,
   exact가 캐시보다 앞인 이유가 "이전에 캐시된 잘못된 매핑을 덮어쓰기 위해"다
   (`tte_service.py:6148`). 플래그만 끄면 캐시가 과거 exact 결과를 되돌려준다.
   양쪽 arm 모두 `CRITERION_CACHE_ENABLED=false`가 필요하다.
3. **`.venv`에는 임베딩이 없다.** 벡터 경로는 MedCPT용 PyTorch를 요구하는데
   (`src/utils/medcpt_embedding.py:36`) `.venv`에 `torch`가 없다. 컨테이너에는 있다
   (torch 2.11.0+cu130). `.venv`에서 돌리면 ablate 대상 자체가 없는 채로 측정된다.
   `retriever.py:124`는 이 실패를 `"Vector search failed (DB might be empty)"`로 출력해
   **원인을 오귀속한다** — 컬렉션은 `omop_concepts` 440,790개로 멀쩡하다.
4. **`.venv`의 대조군은 재현되지 않는다.** 임베딩이 죽은 채 lexical 후보 10개를 gpt-4o가
   자유롭게 고르므로, 동일 5회 실행이 **서로 겹치지 않는 5개 결과**를 냈다(모든 실행에 공통인
   개념 0개, 합집합 18개). 컨테이너에서는 6개 seed 전부 3/3 동일하다.

## 부수 확인 — PHOEBE (복구함, 단 이 경로에는 없었다)

`phoebe_client.py:76`이 `{schema}.concept_recommended`를 조회하는데 `PHOEBE_SCHEMA=omop_vocab`이고
그 스키마에 테이블이 없었다. 실제 테이블은 `demo_cdm.concept_recommended`에 있다(3,768,447행,
597,788개 개념).

**스키마만 `demo_cdm`으로 바꾸면 안 된다.** 같은 쿼리가 `{schema}.concept`도 조인하는데
(`phoebe_client.py:77`) `demo_cdm.concept`는 444행뿐이라 **에러 없이 0건**을 반환한다. 측정으로 확인:

| 추천 테이블 | concept 테이블 | linagliptin 추천 |
| --- | --- | --- |
| `demo_cdm` | `demo_cdm` | **0건 (에러 없음)** |
| `demo_cdm` | `omop_vocab` | 5건 (glimepiride, glipizide, sitagliptin, insulin glargine …) |

그래서 코드를 건드리지 않고 뷰로 붙였다:

```sql
CREATE OR REPLACE VIEW omop_vocab.concept_recommended AS SELECT * FROM demo_cdm.concept_recommended;
-- 되돌리기: DROP VIEW omop_vocab.concept_recommended;
```

**단, PHOEBE는 이 실험의 경로에 없다.** `_recommend_seeded_concept_set`은
`agents/agent2/workflow.py`를 타고, PHOEBE는 `agents/conceptset/stage2_pipeline.py`에 있다
(`tte_service.py:6565`가 부르는 다른 경로). 위 결과에는 영향이 없으며, stage2 경로의 재측정은
따로 해야 한다.

## 남는 질문

- entry seed 6개는 전수지만 **약물 seed 전체는 아니다**. 663개 시드 중 exact match가 발동하는
  집합 전체로 넓히면 비율이 달라질 수 있다.
- `Force-included Top-1`을 끄면 linagliptin 오답이 사라지는가? exact match 없이도 고칠 수 있는
  결함인지 가르는 질문이고, 아직 안 돌렸다.
- MeSH 별칭 경로는 `alias_candidates`를 넘기는 프로브로 따로 측정해야 한다.
