# Handoff — 값이 사라지는 문제 추적 + 감지/자동수리 파이프라인 — 2026-08-21

## Goal / context

TTE 에이전트 현재 상황 정리 요청에서 시작해, agent1(문헌 추출)·agent2(컨셉 매핑) 버그 2건을 고치고, 검증차 vLLM을 켜서 6-study 전체 재생성을 여러 번 돌리는 과정에서 **"임상 기준 문장에 있는 숫자(threshold)가 구조화 IR로 변환되는 도중 조용히 사라지는"** 별도의 실패 유형을 발견했다. 이 문서는 그 발견 → 감지(Step 6/7) → 자동수리(Step 8a/8b) → 새 패턴 추가(Pattern G)까지의 흐름과, 아직 안 끝난 부분을 넘기기 위한 것.

## Current state

- 저장소: `artemis/` (nested git repo, `Broadsea/` 자체는 최상위 저장소 아님)
- 브랜치: `fix/tte-a-drug-anchored-entry` · HEAD: `506ffaf` · remote 없음, PR 없음(로컬 전용)
- `git status`: clean
- vLLM: `google/gemma-4-E4B-it`가 `:8000`에 떠 있음(`--max-model-len 32768`) — **이게 `.env`의 `LLM_MODEL`이 실제로 가리키는 모델**. `snuh/hari-q3-8b`(포트 `:8000`의 "production" 모델, 다른 용도의 tool-calling용)로 착각해서 세션 초반에 잘못 띄웠다가 사용자가 바로잡음 — **다시 hari로 돌리지 말 것**. `:8001`에도 같은 모델이 떠 있는데 이건 내가 안 띄운 것(tmux 세션 없음, 다른 프로세스/세션 소유로 추정) — 안 건드림.
- `artemis-api` 컨테이너 정상, `docker exec artemis-api`로 접근

## Done this session (커밋 순서대로)

1. `32d02d6` — agent1 `pubmed_fetcher.py`: `follow-up` 종결어가 문장 중간에도 매칭돼서 CAROLINA exclusion 기준이 잘림 (원래 요청한 버그 1)
2. `0e77f07` — agent2 `logic.py`: Observation "history of" 개념(Context-dependent/Clinical Observation class)이 Condition 기준에 잘못 매핑되는 것 필터링 (원래 요청한 버그 2)
3. `c0dcf9d` — `vllm_serve.sh`의 `serve()` 함수 bash 문법 버그(`${$(free_gib)}`), 항상 조용히 죽어서 아무것도 안 떴음
4. `4a42454` — `reingest_protocol_pdfs.py`: study 1개 실패(예외)가 배치 전체를 죽이던 것 → study 단위 try/except
5. `d2f2e0b` — 프롬프트에 WRONG/RIGHT 예시 추가: Pattern E(공유 threshold) sub_criteria에 원문 verbatim 안 베끼는 문제
6. `1fa4afe` — **Step 6**: study 전체 threshold 개수 합산 비교(입력 vs 출력), 부족하면 경고. 한계: 한쪽에서 잃고 다른 쪽에서 남으면 상쇄돼서 못 잡음(실측 확인됨)
7. `dd7e998` — **Step 7**: 두 번째 LLM pass로 기준 하나하나를 개별로 봐서 Step 6가 놓치는 걸 잡음 (`THRESHOLD_REVIEW_PROMPT`)
8. `9e835ae` — **Step 8a**: LLM 재호출 없이, 이미 결정론적으로 파싱된 숫자를 기계적으로 재부착. 후보 개수==파싱된 숫자 개수일 때만 (모호하면 거부)
9. `de977b4` — **Step 8b**: 8a가 거부하는 "공유 threshold"(ALT/AST가 숫자 하나 공유) 케이스를, LLM한테 "숫자 재추출"이 아니라 "이미 맞는 숫자를 어느 규칙에 붙일지 매칭"만 시켜서 해결 (`THRESHOLD_MATCH_PROMPT`)
10. `506ffaf` — **Pattern G**: "지역/하위군별로 값이 다른" 케이스(CARMELINA "Age >= 18, 일본만 20") — Step 7이 라이브 재현 중 실제로 잡아낸 것. 값 자체가 통째로 사라지던 걸 프롬프트에 새 패턴 추가로 막음

## Key decisions & why

- **hari-q3-8b vs gemma-4-E4B-it**: `.env`의 `LLM_MODEL=vllm/google/gemma-4-E4B-it`가 정답. hari는 `:8000`의 "production" 이름표를 달고 있지만 그건 tool-calling 목적의 다른 컨슈머용 — TTE IR 생성엔 원래 gemma-4-E4B-it를 써왔음. 이 프로젝트의 `docs/debugging/2026-07-29_gb10_vllm_serving_facts.md`가 hari를 "production port"라고만 적어놔서 헷갈리기 쉬움 — 실제 재생성 파이프라인이 쓰는 모델은 `.env`의 `LLM_MODEL` 확인이 우선.
- **Step 6이 아니라 Step 7이 필요했던 이유**: study 전체 합산(input=10, output=11 같은 식)이 실제로 한쪽 손실을 다른 쪽 과잉생산이 상쇄하는 걸 라이브로 확인함 (오래된 캐시 응답으로 재현). 그래서 기준 단위로 보는 두 번째 pass가 필요했음.
- **Step 8a가 왜 "모호하면 거부"인지**: ALT/AST/Bilirubin처럼 후보 규칙 3개, 파싱된 숫자 2개(ALT·AST가 공유)인 경우, 순서대로 zip하면 AST한테 Bilirubin 숫자가 잘못 붙을 수 있음. 잘못된 숫자를 조용히 붙이는 게 아예 안 붙이는 것보다 나쁘다고 판단해서, 개수가 정확히 안 맞으면 아무것도 안 건드리고 8b로 넘김.
- **Step 8b가 LLM을 다시 쓰면서도 "안전한" 이유**: 원래 실패는 "원문에서 숫자를 뽑아 sourceText에 베끼기"라는 열린 추출 과제에서 모델이 못 지킨 것. 8b는 "이미 뽑혀 있는 숫자 N개를 규칙 M개에 매칭"만 시키는, 훨씬 좁고 제약된 과제라 같은 실패가 재발할 이유가 적음 — 실제로 라이브 테스트에서 ALT=AST=2.0(공유), Bilirubin=1.5(개별)를 정확히 맞춤.
- **Pattern G를 `NCT_SYSTEM_PROMPT`엔 산문으로만 쓴 이유**: 이 프롬프트는 `.format()`을 절대 안 거침(`SystemMessage(content=NCT_SYSTEM_PROMPT)`로 그대로 씀) — `NCT_DECOMPOSITION_PROMPT`처럼 `{{...}}` 이스케이프된 JSON 예시를 쓰면 실제로 모델한테 이중 중괄호가 그대로 보임. 기존 Pattern E도 이 프롬프트 쪽에선 JSON 없이 산문 예시만 씀 — 그 관례를 따름.
- **CARMELINA age 케이스, 완전히 안 끝남**: Pattern G로 "Age >= 18 (General)"과 "Age >= 20 (Japan)" 둘 다 나오게는 됐는데, 둘 다 최상위 `InclusionRules`로 들어가서 CIRCE가 AND로 묶음 → 사실상 전체 환자한테 20세 기준이 적용됨(원래 의도와 다름, 그리고 애초에 이 CDM에 "일본 소속" 같은 지역 속성이 있는지도 미확인). "값이 사라지는 것"은 막았지만 "지역별로 올바르게 분기"는 별도의 더 어려운 문제로 남김 — 아래 Next steps 참고.

## Next steps (우선순위 순)

1. **CARMELINA age AND-결합 문제**: `_build_seeded_target_circe` (`artemis/src/services/tte_service.py:4442`)와 `_build_grouped_inclusion_rule` (`:4393`)를 확인해서, agent1 IR의 `groupId`/`group_type`이 설정 안 된 두 규칙을 CIRCE가 왜 OR이 아니라 AND로 묶는지 **직접 추적 필요(미확인 — 추측하지 말 것)**. 이 CDM(synthea23m/synthea_cdm)에 지역/국가 속성이 실제로 있는지도 별도 확인 필요.
2. **6-study 전체 재생성 여부 결정**: Pattern G 프롬프트 반영한 전체 6-study 재실행은 아직 안 함(CARMELINA 단독 targeted rerun만 검증). 필요하면 아래 "How to verify" 명령으로 전체 재실행.
3. **"자연어→코드 변환시 발생 가능한 상황" 전수조사는 미완**: 오늘 발견/수정한 건 Pattern E(공유 threshold)와 Pattern G(지역별 값) 2가지뿐. 사용자의 원래 요청("발생할 수 있는 상황들을 파악")은 이 2건 외에 evidence-driven하게 더 찾을 여지가 있음 — 다만 오늘은 실제 재현된 것만 다뤘고 추측성 패턴은 안 넣음.
4. **gold 대비 최종 재점수화**: Pattern G 반영 전 마지막 6-study 전체 점수는 `/app/tmp/tte_six_20260821_final_eval.json`(컨테이너 내부 경로)에 있음 — recall/precision은 이전 run과 거의 동일(ULN 값 정확도는 concept-overlap 점수엔 안 잡히는 축이라 정상).

## How to verify / run

```bash
# vLLM 상태 확인
bash /home/bilab/work/projects/Broadsea/artemis/scripts/vllm_serve.sh status

# 단위 테스트 (Step 6/7/8a/8b 전부)
cd /home/bilab/work/projects/Broadsea/artemis
uv run pytest tests/test_llm_threshold_review.py tests/test_value_constraint_coverage_check.py \
  tests/test_corpus_regression.py tests/test_08_pubmed_fetcher.py \
  tests/test_wrong_entity_class_is_dropped.py -v

# CARMELINA만 targeted 재현 (age 케이스 확인용, 캐시 지우고)
docker exec artemis-api sh -c "mv /app/data/cache/agent1_ir/NCT01897532_vllm_google_gemma-4-E4B-it_* /app/data/cache/agent1_ir_backup_20260820/"
docker exec artemis-api sh -c "cp /app/tmp/mesh_fix_exclusion_remap/studies.json /app/tmp/<new-dir>/studies.json"
docker exec artemis-api sh -c "REINGEST_STUDIES=9 TTE_STORE_PATH=/app/tmp/<new-dir>/studies.json python3 /app/scripts/reingest_protocol_pdfs.py"

# 6-study 전체 재생성 (수 시간 소요 가능, 백그라운드 권장)
docker exec artemis-api sh -c "cp /app/tmp/mesh_fix_exclusion_remap/studies.json /app/tmp/<new-dir>/studies.json"
docker exec -d artemis-api sh -c "TTE_STORE_PATH=/app/tmp/<new-dir>/studies.json python3 /app/scripts/reingest_protocol_pdfs.py > /app/tmp/<log-dir>/run.log 2>&1; echo \$? > /app/tmp/<log-dir>/exit_code"
# 진행 확인 (exit_code 파일 존재로 판단하지 말 것 -- race 있음, 아래 Gotchas 참고)
docker top artemis-api | grep reingest_protocol_pdfs.py

# gold 대비 채점
docker exec artemis-api python3 /app/scripts/export_circe_from_store.py --store /app/tmp/<new-dir>/studies.json --out /app/tmp/<circe-dir>
docker exec artemis-api sh -c 'python3 /app/scripts/conceptset_overlap_eval.py --mode closure --generated-dir /app/tmp/<circe-dir> --dsn "$DATABASE_URL" --vocab-schema synthea23m --out /app/tmp/<eval-out>.json'
```

## Gotchas / constraints

- **`artemis/tmp/`는 root 소유**(컨테이너가 root로 씀) — 호스트 유저(bilab)는 `mkdir`/`cp` 직접 못 함. 반드시 `docker exec artemis-api sh -c "..."`로 할 것.
- **IR 캐시는 모델+프롬프트 해시로 키됨** — 프롬프트를 고쳐도 캐시가 남아있으면 재실행해도 옛날 응답을 그대로 씀(`Cache HIT` 로그로 확인 가능). 해당 NCT id의 캐시 파일을 지워야(정확히는 `agent1_ir_backup_20260820/`로 옮겨야 — 삭제 아님, 복구 가능하게) 새로 호출됨: `/app/data/cache/agent1_ir/<NCT_ID>_vllm_google_gemma-4-E4B-it_*`.
- **exit_code 파일 레이스**: `sh -c "cmd; echo $? > file"` 패턴에서 자식 프로세스만 kill하면 부모 셸이 나중에 `echo`를 실행해서, 그 직후 같은 경로로 재실행한 것과 파일 쓰기 순서가 꼬일 수 있음(오늘 실제로 겪음 — 죽은 첫 시도의 echo가 방금 재시작한 두 번째 시도보다 늦게 도착해서 "끝났다"고 착각). **완료 판정은 `docker top artemis-api | grep reingest_protocol_pdfs.py`로 프로세스 생존 여부를 볼 것, exit_code 파일 존재만으로 판단하지 말 것.**
- **사전에 존재하던, 무관한 test flakiness**: `artemis/tests/`를 ~28개 파일 정도로 크게 묶어서 돌리면 순서 의존적으로 ~74개가 실패함(단독/소규모론 안 그럼). `git stash`로 대조해서 오늘 변경분과 무관한 사전 존재 이슈임을 확인함 — 원인 조사는 안 함, 손 안 댐.
- **`CDM_SCHEMA`(컨테이너 env) = `synthea_cdm`, `VOCAB_SCHEMA`(compose 파일) = `synthea23m`** — 오늘 검증한 concept id들은 둘 다에서 일관되게 나왔지만, 서로 다른 설정 키라는 것만 기억해둘 것(같은 스키마의 다른 이름인지, 실제로 다른 스키마인지는 확인 안 함).
- **컨테이너 내부에 `rg` 없음** — 호스트에서만 됨. 컨테이너 안에서는 `grep` 쓸 것.
- **`vllm_serve.sh`의 `restore()`(hari 전용)와 `serve()`(범용)는 서로 다른 코드 경로** — `serve()`의 버그가 오늘까지 안 걸린 이유가 이거임(`restore()`만 계속 써왔어서).
- `todolist/20260819_103200_tte_agent_bug_fixes.md`, `docs/tte_agent/07_current_status.md`에 오늘 세션 앞부분(agent1/agent2 원래 버그 2건 + 정정 사항)이 이미 기록돼 있음 — 이 handoff는 그 뒤에 이어지는 내용(Step 6~8, Pattern G)만 다룸.
