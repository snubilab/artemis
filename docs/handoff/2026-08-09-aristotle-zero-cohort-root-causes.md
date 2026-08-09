# Handoff — ARISTOTLE 0명 코호트의 네 가지 원인 — 2026-08-09

## Goal / context

ARISTOTLE(NCT00412984) 코호트가 gold 1,113명에 대해 **0명**으로 나오는 이유를 찾고 고치는 일.
이 세션은 그 중 하나를 고치고, 나머지 세 개를 특정했다.

**선행 문서 두 개는 진단이 틀렸거나 불완전하다. 이 문서가 최신이다.**
- `docs/handoff/2026-08-06-or-group-and-duplicate-rules.md` — 진단 오류 (문서 상단에 정정 배너 추가함)
- `docs/handoff/2026-08-07-or-group-duplicate-rules-fixed.md` — 코드 변경과 2팔 실험의 상세.
  이 문서와 중복되지만 측정치 원본이 거기 있다. 세부가 필요하면 참조.

## Current state

- Git root: `/home/bilab/work/projects/Broadsea/artemis` (Broadsea 워크스페이스는 git root 가 아님)
- Branch: `fix/tte-a-drug-anchored-entry` · HEAD: `4300eec` · **PR 없음** (`gh` 미설치/원격 없음)
- **전부 미커밋.** `git status --short`:
  ```
   M scripts/reingest_protocol_pdfs.sh
   M src/agents/agent1/enricher.py
   M src/agents/agent1/pubmed_fetcher.py
   M tests/test_08_pubmed_fetcher.py
   M tests/test_parse_criteria_items.py
  ?? src/agents/agent1/criteria_dedup.py
  ?? scripts/verify_orgroup_dedup_two_arm.sh
  ?? tests/test_and_explosion_invariant.py
  ?? tests/test_corpus_regression.py
  ?? tests/test_criteria_dedup.py
  ?? tests/test_dry_or_group_contract.py
  ?? tests/test_or_group_header_trigger.py
  ?? docs/handoff/2026-08-0{6,7,9}-*.md
  ```
- **stash 2개는 건드리지 말 것** — 2026-08-03 에 반증된 슬라이딩 창 변경. `stash@{0}` 테스트 /
  `stash@{1}` 구현, 인덱스로 참조되므로 `git stash push` 를 하면 번호가 밀린다.
  이 세션은 워킹트리에 `git stash`/`git checkout` 을 쓰지 않았다 (되돌리기는 파일 복사로 함).
- 서버: vLLM 은 실험 종료 시 스크립트가 내렸다. `pgrep -af '[v]llm.entrypoints'` 로 확인할 것.
- 컨테이너 가동 중: `artemis-api`, `broadsea-atlasdb`, `ohdsi-webapi`, `broadsea-hades` 등

## ARISTOTLE 0명의 네 가지 원인

| # | 원인 | 상태 |
| --- | --- | --- |
| 1 | enricher 의 중복 판정이 포함 관계를 못 봄 → OR 그룹의 대안이 최상위 AND 규칙으로 중복 | **고침** |
| 2 | `procedure_occurrence` 가 전체 0행 → `ECG at enrollment` 매칭 불가 | 미해결 (CDM 데이터 부재) |
| 3 | 개념집합 과확장이 등록 조건을 부정 → 규칙 28 이 3,100명 중 39명 | **원인 특정**, 미수정 |
| 4 | 규칙 17 ∧ 27 의 통과 집합이 서로소 | 미진단 |

3과 4는 이 세션의 수정 범위 밖이다. 1을 고쳐도 코호트는 여전히 0인데, 그건 수정 실패가
아니라 **원인이 하나가 아니었기 때문**이다.

## Done this session

### 원인 1 수정 (커밋 안 됨)

같은 "이게 중복인가" 판단이 네 곳에 복제돼 있었고 전부 전체 문자열 `SequenceMatcher` 라
포함 관계를 못 봤다. 66자 자식 vs 330자 그룹 줄은 길이 차만으로 모든 임계값 아래다.

- **신규** `src/agents/agent1/criteria_dedup.py` — 단일 권위 술어
  `restates_or_group_alternative(candidate, items)` + OR-GROUP 와이어 포맷 상수.
  내용어 커버리지 + 퍼지 토큰 + 두문자 규칙(`TIA` ↔ `transient ischemic attack`), 임계 0.70.
  안전성을 지탱하는 두 조기 반환: OR 그룹 후보는 절대 중복이 아님 / `items` 에 OR 그룹이
  없으면 무조건 False.
  `ARTEMIS_DISABLE_ORGROUP_DEDUP=1` 은 **명명된 ablation** — 대조군 전용, 기본값 켜짐.
- `src/agents/agent1/pubmed_fetcher.py` — `_header_trigger` 를 좁혀 `any of` 갈래에만 리스트
  예고어를 요구. `_merge_parsed_items` 라우팅. 와이어 포맷을 공용 상수로.
- `src/agents/agent1/enricher.py` — `_merge_criteria`(전방 + **역방향 스윕 필수**),
  `_supplement_priority_merge`, `_pick_richer` 모두 공용 술어로 라우팅.
- `scripts/reingest_protocol_pdfs.sh` — ablation env 전달 + `REINGEST_RUN_LOG` 오버라이드 (2줄)
- **신규** `scripts/verify_orgroup_dedup_two_arm.sh` — 2팔 대조 실험 러너
- 테스트 79개 신규, 5개 파일 (아래 "How to verify"). 기존 테스트 1개는 **의도적으로 반전** —
  `TestLeaderSupplementStyle::test_llm_items_are_merged_with_the_headers` 의 `len(result) >= 12`
  단언이 바로 제거 대상인 append-everything 동작이었다.

### 2팔 실측 (2026-08-07 야간, 로컬 vLLM `google/gemma-4-E4B-it`)

두 팔은 기준 목록 외 모든 것이 같다 — 같은 모델·프롬프트·스토어 계보·소스(`ARISTOTLE_BENCHMARK`).

| | 팔 A (수정 전) | 팔 B (수정 후) |
| --- | --- | --- |
| 분해기 입력 기준 | 13 | **9** |
| 스토어 inclusion 규칙 | 23 | **11** |
| ANY 그룹 | 5 (중복 4개 포함) | **1** (자식 5) |
| 0명 규칙 | **3** — ECG, LVEF, TIA+SE | **1** — ECG |
| 환자 수 | base 3,100 → 0 | base 3,100 → 0 |

두 생성 모두 캐시가 아니다 — `ohdsi-webapi` 로그에 `Cache is absent for cohort id = 3402.
Calculating with design hash = 2020650619` (팔 B) / `= -1347131814` (팔 A).

ECG 규칙만 빼고 재생성해 CDM 제약을 상수로 두면: 팔 A 는 0명 규칙 2개, **팔 B 는 0개**.
그런데도 양쪽 다 환자 0명 — 개별 규칙은 매칭되지만 30개의 논리곱이 공집합이다.

### 원인 3 특정 (Fable 서브에이전트 + 독립 재검증)

`Drug-induced arrhythmia` 개념집합(id 18)에 `44784217 Cardiac arrhythmia` 가
`includeDescendants=True` 로 들어 있고, `313217 Atrial fibrillation` 이 그 자손이다(2단계).
그 자손 폐포에 걸린 조건 발생 **8,360건이 전부 AF 하나**(3,696명).

규칙 28 은 "이 개념집합이 0회" 를 요구하는 부정 조건이므로 **"심방세동이 있으면 제외"** 가
된다 — 이 시험의 등록 요건이 심방세동인데. 규칙 2(AF 요구)와 규칙 28 이 서로의 부정이라
논리곱이 구조적으로 공집합이다. 살아남은 39명은 AF 기록이 **없는** 환자들이다.

**Circe 의미론은 무죄.** WebAPI 에 SQL 을 렌더링시켜 확인했고 `HAVING COUNT(...) = 0` 으로
올바른 NOT-EXISTS 를 낸다. 9999일 창과 `IgnoreObservationPeriod: false` 도 무죄
(관찰기간 가설은 반증: 9999일 이상인 환자가 1,885명).

## Key decisions & why

- **원인 1 의 진짜 현장은 `enricher` 였다.** 선행 문서는 `_collapse_hierarchical_groups` 를
  지목했지만 그 함수는 정상이다. 접기가 **성공해서** 항목 수가 1로 줄었고, 그 때문에
  `_parse_criteria_items` 의 LLM 폴백 게이트(`< 5 items and > 200 chars`)가 발동해 LLM 이
  원문을 다시 평평하게 파싱한 것이 "7개" 의 정체다. 그리고 그것조차 0명의 원인은 아니었다.
- **헤더 트리거 수정이 중복 제거보다 먼저 가야 한다.** CAROLINA 의
  `"...hypersensitivity to any of the components"` 가 오검출로 독립 배제기준 10개를 삼키는데,
  그 위에 중복 제거를 얹으면 오류가 영구히 고착된다. (다만 이 오검출은 오늘 프로덕션에
  도달하지 않는다 — `_collapse_hierarchical_groups` 호출부는 `_parse_criteria_items` 하나뿐이고
  실제 CT.gov 경로는 `nct_fetcher._parse_items` 라 접기가 없다. 잠재 결함 수정.)
- **게이트 재계산(LLM 게이트가 OR 그룹 자식 수를 세게 하는 안)은 폐기했다.** 자식 4개 < 5 라
  ARISTOTLE 에서 안 켜지고, 유일하게 켜지는 CAROLINA 에선 진짜 기준 17개 복구를 막는다.
- **전체 문자열 포함관계(naive containment)도 폐기했다.** 그룹 헤더가 지닌 필수 AND 조건
  (`Atrial fibrillation (AF)`, `Males and females >= 18 yrs`)까지 지운다.
- **ablation 을 env 플래그로 만든 이유** — 2~3시간 무인 실행 중 소스 파일을 바꿔치기하면
  중단 시 트리가 수정 전 상태로 남는다. AGENTS.md 가 "과학적으로 필요한 fallback 은 명명된
  ablation 으로 만들고 그렇게 보고하라" 고 명시한다.
- **사전등록을 먼저 썼다.** 실행 전에 성공/실패/null 세 판정을 적어두지 않았으면
  "0명 규칙 3→1" 만 보고 성공이라 쓰거나 "여전히 0명" 만 보고 실패라 쓰기 쉬웠다.
  실제 답은 제3의 것 — **수정은 동작했고 원가설은 틀렸다.**

## Next steps (ordered, concrete)

1. **원인 3 을 고친다.** 부정(ABSENCE) 개념집합의 자손 폐포가 등록 조건 개념집합과 교집합인지
   검사하는 게이트가 어디에도 없다. 이것이 구조적 구멍이다.
   - 조상 게이트: `src/agents/agent2/concept_set_refiner.py:105`
     `return 1 < desc_count < 50000` — 44784217 은 자손 356개라 통과한다.
     호출부는 같은 파일 `:214`.
   - 프롬프트가 조상 선호를 **적극 권장**한다: `src/agents/agent2/critic.py:244`,
     `:320`, `:325`, `:328` (`"A single ancestor concept with includeDescendants=true is
     often better than ..."`).
   - 규칙 구조 자체는 정상: `src/services/tte_service.py:5776-5780`
     (`{"Type": 0, "Count": 0} if exclusion or criterion.get("logicType") == "ABSENCE"`).
   - Fable 이 측정한 최소 수정: 개념집합 18 에서 `44784217` 제거(또는
     `includeDescendants: false`) → 규칙 28 이 **39 → 3,100**. 나머지 세 항목
     {3655437, 4103295, 4262316} 은 자손 포함해도 `condition_occurrence` 에 0건.
2. **원인 4 를 진단한다.** 규칙 28 을 고쳐도 코호트는 0이다. 규칙 17 `Platelet count`(812명)와
   규칙 27 `Prior stroke, TIA or SE + CHF or LV dysfunction + Diabetes`(789명)의 통과 집합이
   **완전히 서로소**(교집합 0명)다. 값 제약 문제인지 매핑 문제인지 미진단.
3. **원인 2 를 결정한다.** `synthea_cdm_aristotle.procedure_occurrence` 가 전체 0행이다
   (환자 21,000명). 벤치마크 CDM 생성 쪽에서 채울지, ECG 류 기준을 이 CDM 에서 평가 불가로
   표시할지 정할 것.
4. **커밋 여부를 결정한다.** 원인 1 수정은 검증 완료 상태로 미커밋이다.
5. **병원 산출물 재생성 여부.** `output/circe_be/*` 는 이 수정 이전 코드의 결과다.

## How to verify / run

```bash
cd /home/bilab/work/projects/Broadsea/artemis

# 신규 + 손댄 테스트 (반드시 파일별 개별 프로세스 — 아래 Gotchas 참조)
for f in test_or_group_header_trigger test_criteria_dedup test_and_explosion_invariant \
         test_dry_or_group_contract test_corpus_regression test_parse_criteria_items \
         test_08_pubmed_fetcher test_09_enricher; do
  printf "%-32s %s\n" "$f" "$(.venv/bin/python -m pytest tests/$f.py -q --no-header -p no:randomly | tail -1)"
done
# 기대: 27 / 30 / 8 / 7 / 7 / 30(+1 deselected) / 6 / 3 — 전부 pass

# 기존 9파일 기준선 (465 passed / 0 failed 여야 정상)
for f in test_parse_criteria_items test_pdf_role_strategy test_08_pubmed_fetcher \
         test_09_enricher test_agent1 test_value_constraint \
         test_dose_form_route test_route_qualifier test_route_subtraction; do
  .venv/bin/python -m pytest tests/$f.py -q --no-header -p no:randomly | tail -1
done

# 원인 3 재현: AF 가 Cardiac arrhythmia 의 자손인가
docker exec broadsea-atlasdb psql -U postgres -d postgres -tAc "
SELECT ancestor_concept_id, descendant_concept_id, min_levels_of_separation
FROM synthea_cdm_aristotle.concept_ancestor
WHERE ancestor_concept_id=44784217 AND descendant_concept_id=313217;"
# → 44784217|313217|2

# 개념집합 18 의 자손 폐포에 걸리는 조건이 무엇인가 (전부 AF 하나)
docker exec broadsea-atlasdb psql -U postgres -d postgres -tAc "
SELECT co.condition_concept_id, c.concept_name, count(*), count(DISTINCT co.person_id)
FROM synthea_cdm_aristotle.condition_occurrence co
JOIN synthea_cdm_aristotle.concept_ancestor ca ON ca.descendant_concept_id=co.condition_concept_id
JOIN synthea_cdm_aristotle.concept c ON c.concept_id=co.condition_concept_id
WHERE ca.ancestor_concept_id=44784217 GROUP BY 1,2 ORDER BY 3 DESC;"
# → 313217|Atrial fibrillation|8360|3696

# 원인 4 재현: 규칙 17 과 27 의 통과 집합이 서로소
docker exec broadsea-atlasdb psql -U postgres -d postgres -tAc "
SELECT
  sum(CASE WHEN (inclusion_rule_mask >> 17) & 1 = 1 THEN person_count ELSE 0 END) AS pass_17,
  sum(CASE WHEN (inclusion_rule_mask >> 27) & 1 = 1 THEN person_count ELSE 0 END) AS pass_27,
  sum(CASE WHEN (inclusion_rule_mask >> 17) & 1 = 1
             AND (inclusion_rule_mask >> 27) & 1 = 1 THEN person_count ELSE 0 END) AS both
FROM synthea_cdm_aristotle_results.cohort_inclusion_result
WHERE cohort_definition_id=3402 AND mode_id=1;"
# → 812|789|0

# 원인 2 재현: procedure_occurrence 가 비었는가
docker exec broadsea-atlasdb psql -U postgres -d postgres -tAc "
SELECT count(*) FROM synthea_cdm_aristotle.procedure_occurrence;"   # → 0
docker exec broadsea-atlasdb psql -U postgres -d postgres -tAc "
SELECT count(*) FROM synthea_cdm_aristotle.person;"                 # → 21000

# 2팔 실험 재실행 (GPU. 팔 B ~40분, 팔 A 는 IR 캐시라 즉시)
nohup scripts/verify_orgroup_dedup_two_arm.sh > /tmp/twoarm/driver.log 2>&1 &
```

산출물(이 세션): `/tmp/twoarm/` (driver.log, progress.jsonl, 팔별 reingest/circe/cohort 로그),
스토어 `/app/tmp/tte_arm_{a,b}_*`, circe `/app/tmp/circe_{a,b}{,_noecg}` (컨테이너 경로).

## Gotchas / constraints

- **전체 스위트 숫자는 회귀 신호가 아니다.** 이 저장소는 파일 간 간섭이 있어
  `test_09_enricher` 처럼 단독 통과 파일이 전체 실행에서 실패 목록에 오른다. HEAD 에서도
  `210 failed / 1543 passed` 다 (변경 후 `210 failed / 1622 passed` — 실패 동일, 통과만 +79).
  **반드시 파일별 개별 프로세스로** 비교할 것.
- **전체 스위트 수집 오류 10건**은 호스트 venv 의존성 누락(`pandas`×9, `langgraph`×1)이고
  `import pandas` 에서 죽으므로 이 변경과 무관하다. `--continue-on-collection-errors` 필요.
- **`pgrep -f` / `pkill -f` 에 맨 패턴을 쓰지 말 것.** `scripts/reingest_protocol_pdfs.sh:68-88`
  의 `stop_server` 가 `vllm.entrypoints.openai.api_server` 등을 맨 패턴으로 죽인다. 내
  명령줄에 그 문자열이 그대로 있으면 **내 셸이 죽는다**(과거 exit 144). 첫 글자를
  대괄호로: `pgrep -af '[v]llm.entrypoints'`.
- **`artemis/tmp/` 는 root 소유.** 컨테이너가 만든 스크래치는 호스트 셸로 못 지운다.
  `docker exec artemis-api python -c "import shutil; shutil.rmtree('/app/tmp/X')"` 를 쓸 것.
- **`/app/tests` 는 마운트되지 않는다.** 이미지에 구워진 stale 디렉터리(`fixtures` 만)가 있어
  `docker exec ... /app/tests/...` 가 조용히 엉뚱한 걸 실행할 수 있다. `pdftotext` 는 호스트에도
  있으니 코퍼스 회귀는 호스트 pytest 로 돈다. (`/app/src`, `/app/scripts`, `/app/data`,
  `/app/tmp` 는 마운트됨.)
- **`artemis-eval-baseline/` 과 `artemis-codex-fixes/`** 는 Broadsea 루트의 별도 체크아웃이고
  거의 동일한 파일을 담고 있다. codegraph/grep 이 자꾸 그쪽을 가리킨다. 이 세션에서 세 번
  잘못 짚었다.
- **CT.gov 텍스트를 `pubmed_fetcher._parse_criteria_items` 에 수동으로 넣어 측정하지 말 것.**
  `src/` 의 어떤 코드도 그렇게 하지 않는다 (CT.gov 는 `nct_fetcher._parse_criteria_text` →
  `_parse_items`). 이 함정으로 정찰·설계·검토 세 단계에서 각각 잘못된 결론이 나왔다.
- **WebAPI 정의 3402 는 두 팔이 재사용한다.** 마지막으로 덮은 것은 **팔 B(ECG 제거본)** 이다.
  비교를 다시 보려면 해당 circe 디렉터리로 재등록할 것.
- **재수집 후 `Cache HIT` 이 보이면 입력이 안 바뀐 것.** 시험 대상 팔에서는 중단 신호다
  (커밋 `4300eec` 가 "효과 없음" 으로 판정된 근거가 이것이었다). **대조군에서는 정상** —
  역사적 산출물을 GPU 없이 얻는 것이다. `verify_orgroup_dedup_two_arm.sh` 의 게이트는 팔을
  구분하지 않아 팔 A 를 잘못 중단시킨다. 다음에 쓸 때 분기할 것.
- **재수집은 로컬 vLLM 을 쓴다** (`LLM_MODEL="vllm/google/gemma-4-E4B-it"` + `VLLM_BASE_URL`).
  유료 API 가 아니다. 단 `vllm/` 접두사가 빠지면 OpenRouter 로 샌다 (`.claude/rules/broadsea/infra.md`).
- **`tests/test_08_pubmed_fetcher.py` 는 기본 실행마다 유료 LLM 호출 3건을 내고 있었다.**
  이 세션에서 autouse 픽스처로 막았다 (5.47s → 0.31s). 그 출력은 어떤 단언에도 안 쓰였다.
