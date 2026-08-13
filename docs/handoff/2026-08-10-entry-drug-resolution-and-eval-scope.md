# Handoff — entry 약물 해석과 평가 범위 — 2026-08-10

## Goal / context

`2026-08-09-session-handoff.md`의 open work #1("wrong-entity 매핑 7건")을 파고들었다. 결과적으로
**7건은 하나의 결함이 아니었고**, 그중 실제로 고칠 수 있는 것을 고쳤으며, 파고드는 과정에서
**평가 스크립트 자체의 범위 결함**이 나와 그것도 고쳤다. 그 과정에서 전날 보고된 숫자 하나를
스스로 깎았다.

## Current state

- Repo: `/home/bilab/work/projects/Broadsea/artemis` (git root)
- Branch: `fix/tte-a-drug-anchored-entry` · HEAD: `7837274` · remote 없음 (`gh pr list` → "no git remotes found")
- Uncommitted: clean
- Stash 2개 — **건드리지 말 것** (sliding-window eligibility + 그 테스트, 짝으로만 복원)
- 워크스페이스 루트 `/home/bilab/work/projects/Broadsea`는 **2026-08-09부터 git 저장소다**
  (`1351d03`에서 초기화). HEAD `59c4b85`, clean. 화이트리스트 방식이라 `omx_wiki/`, `AGENTS.md`,
  `CLAUDE.md` 세 가지만 추적한다 — 자세한 것은 아래 Gotchas.

### 실행 중인 프로세스 2개

| 무엇 | PID | 상태 | 정지 |
| --- | --- | --- | --- |
| 문서 서버 (`python3 -m http.server 8898`) | `4173532` | 실행 중 | `kill $(cat /tmp/omx-serve/server.pid)` |
| vLLM `google/gemma-4-E4B-it` (`:8000`) | `3672578` | 18시간+ **유휴** | `kill 3672578` |

vLLM은 이번 세션에서 한 번도 쓰지 않았다. GPU가 필요하면 회수해도 된다.

## Done this session (8 commits, `862a04f..7837274`)

1. `8f1f50a` docs(handoff): 전날 핸드오프가 스스로를 낡게 만들던 문제 + 오인용 게이트 정정
2. `be57342` fix(tte): exact ingredient match를 실행되게 함
3. `991c11c` fix(tte): entry 약물은 domain 없이 오므로 `None`도 수용
4. `86adac9` test(eval): 짝지은 arm으로 측정, 그 과정에서 발견을 분리
5. `10034d5` fix(eval): gold의 censoring 집합을 eligibility 코호트와 짝짓지 않음
6. `215f200` docs(AGENTS): 고아 gold 집합을 분모에 유지하되 함정을 규칙으로 고정
7. `3f2b3c8` feat(eval): 짝지은 측정용 대시보드
8. `7837274` feat(tte): 개발코드 시드를 시험의 MeSH 용어로 해석

루트 저장소: `36f8322`, `95d0b6e`, `59c4b85` (위키 페이지 + plan 보드 + 대시보드 재빌드)

## Key decisions & why

### "wrong-entity 7건"은 세 가지 다른 것이었다

전날 문서의 분류표가 틀렸다. 실제로는:

| 행 | 실제 결함 | 상태 |
| --- | --- | --- |
| 5행 (linagliptin) | entry 약물이 `expected_domain=None`으로 와서 게이트를 못 통과 | **수정됨** (`991c11c`) |
| 2행 (glimepiride) | 기준 원문 `"Hypersensitivity to investigational product or glimepiride"`의 한정어가 `sourceText`에서 탈락 | **미해결** |
| — (BI 10773) | 개발코드, 원래 표에 없던 6번째 | **수정됨** (`7837274`) |

### 게이트를 두 번 고쳐야 했다

- `be57342` — `_exact_ingredient_mapping`은 2026-07-23부터 있었지만 `TTE_DRUG_ANCHORED_ENTRY`
  뒤에 있었고 그 플래그는 **어디서도 켜지지 않는다**. `docs/reviews/2026-07-30_fallback_audit.md:239`
  (SVC-03)가 이미 "constant-False in production"이라 기록해뒀지만, 그 뒤에 정합성 수정이 숨어
  있다는 걸 놓쳤던 것.
- `991c11c` — 플래그를 떼도 여전히 안 됐다. `_build_seeded_target_circe`(`tte_service.py:4374`)가
  entry 약물을 **`expected_domain` 없이** 매핑하므로 `== "Drug"`가 여전히 False였다.
  현재 게이트는 `tte_service.py:6176`의 `expected_domain in ("Drug", None)`.

**domain 검사를 아예 없애면 안 된다.** 663개 시드 중 5개가 non-Drug domain인데 성분명과 정확히
일치한다: `Calcitonin`, `Creatinine`, `Glucose`, `glucose`(전부 분석물 이름을 가진 Measurement
기준), 그리고 `glimepiride`. 검사를 빼면 혈액검사가 투약 기록으로 바뀐다.

### 개발코드는 어휘로 풀 수 없고, 시험 기록으로 풀린다

`BI 10773`은 630만 개념 중 0건이고 empagliflozin 성분에는 동의어 행이 0개다(`concept_synonym`
자체는 270만 행). **어휘 안에서 푸는 시도는 전부 실패한다.**

답은 `data/nct_cache/NCT01131676.json`의 `derivedSection.interventionBrowseModule.meshes` —
NLM이 파생시킨 MeSH 대표어다. 스폰서가 쓴 모든 필드(`briefTitle`, `armsInterventionsModule`,
arm 라벨)는 `BI 10773`인데 여기만 `empagliflozin`이다. 통제 어휘의 존재 이유가 동의어를
대표어로 모으는 것이므로, 색인기가 스폰서가 할 이유 없던 정규화를 대신 해줬다.

측정: 6개 시험의 MeSH 용어 9개 **전부**가 유일 RxNorm 성분으로 해석된다.

**중간에 틀렸던 판단**: 처음엔 "구조화된 `armsInterventionsModule`이 자유 텍스트 제목보다 튼튼한
출처"라고 봤는데 정반대였다. 그 필드엔 `BI 10773 low dose`뿐이고 `otherNames`도 비어 있다.
각 칸을 실제로 열어본 것만이 답을 줬다.

### 평가 스크립트의 범위가 틀려 있었다

`conceptset_overlap_eval.py`의 모듈 헤더가 이미 "gold의 arm 약물 집합은 out of scope"라고
적어뒀는데 **코드가 강제하지 않았다.** 채점 대상 gold 집합 중 6개가 `CensoringCriteria`에서만
참조되는데, 생성 산출물은 eligibility 코호트라 그 섹션 자체가 없다. `10034d5`에서
`censoring_only_codeset_keys()`(`conceptset_overlap_eval.py:196`)로 분리했고, 리포트에
`out_of_scope_gold`로 나온다.

CAROLINA의 과민반응 제외기준이 gold의 glimepiride **검열용** 집합과 이름만으로 짝지어져 있던 게
이것 때문이다.

### 고아 gold 집합은 분모에 남긴다 — 2026-08-10 결정, 다시 논의하지 말 것

채점 대상 gold 집합 238개 중 **14개가 어떤 기준도 참조하지 않는다.** 대부분 `PrimaryCriteria`가
실제로 쓰는 `(ATC)` 집합의 비-ATC 중복이다.

유지하기로 결정했다(이 평가의 질문이 "gold의 개념집합을 우리가 만들었는가"이고 TROY가 라이브러리로
내보내므로). 대신 **비용은 보고 단계에서 치른다** — `AGENTS.md:96` EVALUATION에 고정:
**하나의 수정이 여러 쌍으로 채점될 수 있으니 쌍 수가 아니라 구별되는 수정 수를 인용할 것.**

이게 전날 숫자를 깎았다. entry 약물 수정이 5쌍을 움직였지만 3쌍은 고아 중복이라 **정직한 값은
2건**이다.

### 전면 재생성을 기각한 이유

게이트는 study당 concept set 1개만 지나간다. 6개 trial 재생성은 변하지 않을 ~370개를 다시 만들며
store 생성(2026-08-04) 이후의 모든 커밋을 섞어 귀속을 파괴한다. 대신 **같은 store에서 같은
exporter로 두 arm을 export**했고, 6개 CIRCE 중 4개가 바이트 동일함을 md5로 확인했다.

**`tmp/circe_b/`를 대조군으로 쓰면 안 된다.** 다른 store 산출물이다 — deliverable을 새로
export하면 ARISTOTLE이 43 concept set / 35 rule인데 그 manifest는 40 / 31이다.

## 측정 결과 (모두 짝지은 arm, 동일 조건)

| | 대조군 | +entry 게이트 | +eval 범위 | +MeSH 별칭 |
| --- | ---: | ---: | ---: | ---: |
| 6-trial macro recall | 0.567 | 0.597 | 0.598 | **0.610** |
| zero-overlap 쌍 | 109 | 104 | 99 | **96** |
| 쌍 수 | 238 | 238 | 232 | 232 |

**구별되는 수정 3건** (linagliptin ×2, empagliflozin ×1) + 분류 교정 1건.
손대지 않은 4개 trial이 정확히 0.000 움직인 것이 arm parity의 증거다.

## 후속 조사 — `sourceText`는 버려진 필드가 아니라 이름이 잘못된 필드다

위 Next steps 1번을 파고든 결과, **이 문서가 적어둔 진단 자체가 틀렸다.**

정규화 지점은 `_criterion_dict_from_ir_item`(`tte_service.py:9692`)의 `source_text = entity_text`다.
IR의 `Criteria.source_text`(`src/models/ir.py:87`)는 **읽히지도 않고** 덮어써진다 — 18MB store 전체에
`"source_text"` 문자열이 0건이다. Agent 1 프롬프트는 이 필드를 MANDATORY로 요구하지만
(`src/agents/agent1/prompts.py:161`), 유일한 소비자는 `threshold_classifier.py:427`뿐이다.

**그런데 이걸 "복원"하면 회귀다.** `sourceText`는 매핑 쿼리의 1순위 입력이고
(`tte_service.py:4474`, `tte_service.py:5753`, `src/api/tte.py:259` 전부 `sourceText or description`),
지금 담긴 정규화 엔티티가 개념집합 검색에는 **맞는 입력**이다:

| description | sourceText | 벗긴 게 맞나 |
| --- | --- | --- |
| `eGFR < 60 (MDRD)` | `eGFR` | 맞음 — 한정어는 `valueConstraint`로 간다 |
| `Asymptomatic cardiac ischemia` | `cardiac ischemia` | 맞음 |
| `Contraindication due to severe renal impairment` | `Severe renal impairment` | 맞음 — 개념집합은 질환이지 "금기"가 아니다 |
| `Hypersensitivity to investigational product or glimepiride` | `glimepiride` | **틀림 — 알레르기가 투약이 된다** |

store 653개 기준 중 `sourceText`가 description과 다른 것이 **429개**(더 짧은 것 292개)다. 축자 원문을
넣으면 그 429개의 매핑 쿼리가 전부 바뀐다. 필드 이름이 `sourceText`라 버그처럼 보였을 뿐이다.

**진짜 결함의 범위는 1건이다.** 관계어(hypersensitivity/allergy/intolerance/contraindication) 스캔에서
6개 시험 통틀어 5건이 걸렸고, 그중 3건(`Contraindication due to <질환>`)은 벗기는 게 맞으며 1건은
아래 별개 결함, 남는 건 glimepiride 하나다. 이 문서가 "건드리지 말라"고 한 domain 게이트가 바로 이
1건을 가려내는 신호다 — domain이 `Condition`인데 entity가 Drug 성분이면 관계어가 탈락한 것이다.
같은 이유로 나머지 non-Drug 시드 4개(`Calcitonin` ×3, `Creatinine`, `Glucose`/`glucose`)는 전부
Measurement이고 description이 분석물+임계값이라 정상이다.

### 조사 중 발견한 별개 결함 — PLATO의 description/sourceText 불일치

`ticagrelor vs clopidogrel` 스터디에 description이 기준 6개가 `+`로 뭉친 문자열
(`Contraindication to clopidogrel + Allergy to clopidogrel + Active bleeding + History of intracranial
hemorrhage + Severe hepatic impairment + Thrombotic thrombocytopenic purpura`)인데 `sourceText`는
`ST-segment elevation`이다. **둘이 서로 다른 기준을 가리킨다.** domain은 `Measurement`.
glimepiride보다 심각할 수 있고 범위는 아직 미측정이다.

## Next steps (ordered, concrete)

1. ~~**glimepiride 한정어 탈락**~~ — **조사 완료, 수정 방향이 틀렸었다 (아래 "후속 조사" 참조).**
   정규화 지점은 `_criterion_dict_from_ir_item`(`tte_service.py:9692`)의 `source_text = entity_text`가
   맞다. 하지만 **거기를 고치면 안 된다** — 축자 원문 복원은 429개 기준의 매핑 쿼리를 한꺼번에 바꾼다.
   실제 결함은 훨씬 좁고 1건이며, 코드 수정의 값어치가 얇다.
2. ~~**exact-vs-embedding 귀속 실험**~~ — **실행 완료.
   `docs/experiments/2026-08-10_exact_vs_embedding_attribution.md`**
   가설 "임베딩이 고유명사에 약하다"는 **일반 명제로는 기각**됐다. 유효 테스트된 5개 seed 중 3개
   (liraglutide/ticagrelor/apixaban)는 임베딩이 이미 정답이고, exact match가 답을 바꾼 것은
   **linagliptin 하나**(시험 2개)다. 기전은 3단이다 — 검색기가 sitagliptin을 1위로 주고
   (top-20에 linagliptin 없음), 리랭커가 후보를 **전부 기각**하고(`0 selected`), 그 위에서
   **`Force-included Top-1`** 폴백이 기각을 덮는다. "매치 없음"이 "자신 있게 틀림"이 되는 지점이다.
   - **반드시 컨테이너에서 돌릴 것.** `.venv`에는 `torch`가 없어 MedCPT 벡터 검색이 죽고
     (`medcpt_embedding.py:36`), `retriever.py:124`가 그것을 `"DB might be empty"`로 오귀속한다.
     그 상태의 대조군은 동일 5회 실행이 서로 겹치지 않는 5개 결과를 낸다.
   - **`scripts/rebuild_entry_concept_sets.py`로는 ablation이 안 된다** — `_exact_ingredient_mapping`을
     직접 호출해 플래그 게이트(`tte_service.py:6176`)를 우회한다. 플래그와 무관하게 출력이 같다.
   - 양쪽 arm 모두 `CRITERION_CACHE_ENABLED=false` 필요(캐시가 exact보다 뒤에 있어 오염된다).
3. **critic 프롬프트/스키마를 개편할 것 — 카테고리별 선택 + 짧은 reason** (2026-08-10 결정).
   현재 `CriticResult`는 후보 **하나당** `CriticSelection` 엔트리를 낸다(`concept_id`, `relevant`,
   자유서술 `reasoning`, `confidence`, `potential_issue`, `assessment`, `recommended_action` —
   `critic.py:143`). 그래서 **출력 길이가 후보 수에 비례**하고, 후보 90개면 3,600토큰대까지 가서
   `max_tokens=4096`(`critic.py:297`, `:467`)이 필요해진다.
   - 이것이 8,192 컨텍스트에서 268개 중 **176개**의 critic 400 실패를 만든 구조적 원인이다.
     서버를 32,768로 올려 당장은 풀리지만, 후보 수가 늘면 같은 벽에 다시 닿는다.
   - 개편 방향: **개념을 카테고리로 묶어 카테고리 단위로 선택**하고, reason은 항목마다 길게 쓰지 말고
     **짤막하게**. 출력 길이를 후보 수에서 떼어내는 것이 목적이다.
   - 함께 볼 것: 실패가 조용하다. `[Critic] Evaluation failed` 다음 줄이 그대로
     `Critic selected: 3 from 59 candidates`로 이어져 KG 확장분을 버리고 seed로 되돌아간다.
     축소된 개념집합이 "모델이 보수적"으로 오독됐다 — 실제로는 critic이 실행되지 않은 것이다.
     실패 건수를 집계해 크게 드러내거나, 재매핑 스크립트가 실패가 있으면 성공으로 보고하지 않게 할 것.
4. **`Force-included Top-1` 폴백을 검증할 것** — 위 실험이 새로 연 항목이며 **우선순위 높음**.
   리랭커가 `0 selected`를 반환했는데도 top-1을 강제 편입하는 코드가 linagliptin 오답의 마지막
   단계다. 이걸 끄면 exact match 없이도 오답이 무답으로 바뀌는지가 질문이다. 무답이 된다면
   exact match는 안전망이지 유일한 해법이 아니다. 같은 폴백이 663개 시드 전반에서 몇 번
   발동하는지도 미측정.
   - 함께: **PHOEBE는 이 환경에서 죽어 있다.** `concept_recommended`를 `omop_vocab`에서 찾는데
     그 스키마엔 없다(`demo_cdm`에만 존재). 매 매핑마다 10회 쿼리 실패 후 0개 확장.
   - 함께: **MeSH 별칭 경로는 아직 측정되지 않았다.** `_alias_ingredient_mapping`은
     `alias_candidates` 인자가 있어야 동작하는데 위 프로브는 넘기지 않았다.
5. **arm 유형을 별칭 모호성 해소에 쓸지 결정** — `armGroups[].type`이
   `EXPERIMENTAL`/`ACTIVE_COMPARATOR`/`PLACEBO_COMPARATOR`를 명시하고, MeSH 용어를 EXPERIMENTAL
   arm의 `interventionNames`와 대조하면 6개 중 5개에서 연구약이 가려진다. **단 EMPA-REG에서는
   arm 이름도 코드명이라 연결이 끊긴다** — 별칭 경로가 발동하는 조건이 곧 연결이 끊기는 조건이다.
   실익은 가상의 모호 케이스뿐이라 우선순위는 낮다.
   - **double-dummy 함정**: CAROLINA의 EXPERIMENTAL arm에 `Drug: glimepiride placebo`가 있다.
     단순 부분문자열 대조 시 비교약이 연구약으로 잡힌다. `placebo` 포함 항목을 반드시 걸러야 한다.
6. **PLATO description/sourceText 불일치** — 위 "후속 조사"의 별개 결함. 먼저 **범위를 측정할 것**
   (6개 시험 전체에서 description과 sourceText가 무관한 기준이 몇 건인가). glimepiride와 달리
   이건 매핑이 엉뚱한 개념을 향하므로 recall에 직접 영향이 있을 수 있다.
7. ~~**vLLM 회수**~~ — **취소. gemma는 계속 켜둔다.** 2026-08-10부터 모든 LLM이 vLLM으로 간다
   (`artemis/.env`의 `LLM_MODEL=vllm/google/gemma-4-E4B-it`). 같은 날 `--max-model-len`을
   8192 → **32768**로 올려 재기동했다 — critic 프롬프트가 8192를 넘겨 176/268이 실패했기 때문이며,
   모델 자체는 131,072를 지원한다. GB10이므로 `env -u PYTHONPATH -u PYTHONHOME`로 띄울 것.

## How to verify / run

```bash
cd /home/bilab/work/projects/Broadsea/artemis

# 테스트 — 파일 단위, -p no:randomly (전체 스위트 숫자는 이 저장소에서 신뢰 대상 아님)
.venv/bin/python -m pytest tests/test_defect_b_exact_ingredient_gate.py -p no:randomly -q   # 26 passed
.venv/bin/python -m pytest tests/test_conceptset_overlap_eval.py -p no:randomly -q          # 15 passed

# 측정 재현 — arm A(수정) vs arm B(대조), 둘 다 같은 store 에서
DATABASE_URL=postgresql://postgres:mypass@localhost:5432/postgres CDM_SCHEMA=synthea_cdm \
  .venv/bin/python scripts/rebuild_entry_concept_sets.py \
    --store tmp/tte_six_deliver/studies.json --out output/arm_a_store/studies.json
.venv/bin/python scripts/export_circe_from_store.py --store output/arm_a_store/studies.json    --out output/circe_arm_a
.venv/bin/python scripts/export_circe_from_store.py --store tmp/tte_six_deliver/studies.json   --out output/circe_arm_b
for ARM in a b; do
  .venv/bin/python scripts/conceptset_overlap_eval.py --mode closure --vocab-schema synthea23m \
    --generated-dir output/circe_arm_$ARM --out output/conceptset_overlap/scoped_arm_$ARM.json
done

# 대시보드 재빌드 (수 초)
.venv/bin/python scripts/build_conceptset_dashboard.py
```

URLs (문서 서버, PID `4173532`):

- http://localhost:8898/ — 인덱스
- http://localhost:8898/dashboard.html — 짝지은 측정 대시보드 (심링크라 재빌드 시 자동 반영)
- http://localhost:8898/explain.html — 커밋 `7837274` 해설 (원본 `/tmp/2026-08-10-explanation-mesh-alias-drug-seed.html`)

## Gotchas / constraints

- **`pytest`는 호스트 `python3`에도 `artemis-api` 컨테이너에도 없다.** `.venv/bin/python -m pytest`를 쓸 것.
- **`tmp/`는 root 소유라 쓸 수 없다.** 그래서 arm store들이 `output/` 아래에 있다.
- **`artemis-api` 컨테이너에 `output/` 마운트가 없다.** 컨테이너 안에서 스크립트를 돌리면 결과
  파일이 호스트에 안 나타난다. 컨테이너 `/tmp`도 쓰기 권한이 없어 이번에 한 번 물렸다.
- **워크스페이스 루트 저장소는 화이트리스트다.** `.git/info/exclude`가 최상위를 전부 무시하고
  `omx_wiki/`, `AGENTS.md`, `CLAUDE.md`만 재포함한다. `.git/hooks/pre-commit`이 스테이징된 경로를
  재검사해 허용목록 밖이면 커밋을 거부한다(레드 테스트로 검증됨). 루트에 `secrets/`, `cacerts`,
  `certs/`가 있고 **루트 `.gitignore`는 그것들을 무시하지 않는다** — 훅과 exclude가 유일한 방어선이며
  둘 다 `.git/` 안에 있어 그 자체는 버전 관리되지 않는다.
- **`_stub_recommend` 같은 테스트 대역은 실물 시그니처를 따라가야 한다.**
  `tests/test_infra_002_demographics_grouping.py:68`이 이번에 7개 전부 깨졌다. 인자를 안 넘겨서
  대역을 달래면 새 계약이 테스트되지 않은 채 남는다.
- **커밋 `7837274` 메시지에 부정확한 표현이 하나 있다** — "MeSH does not distinguish study drug
  from comparator"를 시스템 전체의 한계처럼 읽히게 썼다. 실제로는 `armGroups[].type`에 구분이
  있다(위 Next steps 3번). 역사라 고치지 않았고, 서빙 중인 해설 문서는 정정했다.
- **`curl`이 에이전트 셸에서 "command not found"로 나올 때가 있다**(`/usr/bin/curl`은 존재).
  서버 상태 확인은 `ss -ltnp` + python `urllib`로 하면 된다. 이걸 곧이곧대로 읽으면 서버가 죽었다고
  오진한다.
