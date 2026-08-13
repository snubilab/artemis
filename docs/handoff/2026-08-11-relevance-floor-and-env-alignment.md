# Handoff — 관련성 하한선 부재와 실행환경 정렬 — 2026-08-11

## Goal / context

concept set 품질을 gold(TROY v1.1 CIRCE) 대비로 올리는 작업. 어제까지는 entry 약물 매핑 결함을
잡았고, 오늘은 **매핑 모델을 로컬 vLLM으로 전면 교체해 그 효과를 측정**했다. 결론은 음성이고, 그
음성 결과가 다음 작업 방향을 정한다.

## Current state

- **artemis** (`/home/bilab/work/projects/Broadsea/artemis`는 자체 git 저장소):
  브랜치 `fix/tte-a-drug-anchored-entry` · HEAD `7837274` · PR 없음(`gh` 미설치)
- **Broadsea 루트**: `main` @ `59c4b85`, `omx_wiki/dashboard/plan.json` 수정됨
- **커밋 안 한 변경 (artemis)** — 오늘 작업분 전부:
  ```
   M output/conceptset_overlap/dashboard.html
   M scripts/build_conceptset_dashboard.py
   M src/agents/agent2/workflow.py
   M src/services/tte_service.py
  ?? docs/experiments/2026-08-10_exact_vs_embedding_attribution.md
  ?? docs/handoff/2026-08-10-entry-drug-resolution-and-eval-scope.md
  ?? tests/test_agent2_reranker_rejection.py
  ?? tests/test_environment_matches_requirements.py
  ?? tests/test_unmapped_criteria_are_recorded.py
  ```
  `M scripts/build_diagnosis_dashboard.py`도 떠 있는데 **이번 세션과 무관하다** — 한국어 문구
  다듬기 5줄이고 내가 건드리지 않았다. 커밋할 때 섞지 말 것.
  `artemis/.env`도 바꿨지만 `.gitignore:34`로 추적되지 않는다(`LLM_MODEL` 한 줄, 아래 참조).
- **실행 중**:
  - vLLM PID `134304` — `google/gemma-4-E4B-it`, `--max-model-len 32768 --enforce-eager
    --gpu-memory-utilization 0.55 --enable-auto-tool-choice --tool-call-parser gemma4`,
    `:8000`. GPU 약 65 GB 점유. 로그 `output/vllm_gemma_32k_tools.log`
  - 문서 서버 PID `4173532` — `python3 -m http.server 8898 --directory /tmp/omx-serve`
  - `artemis-api` 컨테이너 Up

## Done this session (전부 미커밋)

1. **모든 LLM 호출을 로컬 vLLM으로.** `artemis/.env:18` `LLM_MODEL=vllm/google/gemma-4-E4B-it`.
   코드는 이미 `resolve_model()`로 모여 있었고 critic도 기본값이 `LLM_MODEL`을 따른다.
   `env_file`은 컨테이너 **생성** 시점에만 적용되므로 `docker compose up -d artemis-api`로
   재생성해야 반영된다(재시작으로는 안 된다).
2. **6개 시험 전면 재매핑 + 채점.** 산출물 `output/conceptset_overlap/scoped_gemma.json`,
   store `tmp/tte_vllm_remap2/studies.json`, 매니페스트 `output/remap_gemma_32k.manifest.txt`.
3. **force-include 결함 수정.** `src/agents/agent2/workflow.py`에 `_exact_name_concept`(:81),
   `_seeds_after_rerank`(:157) 추가. 테스트 `tests/test_agent2_reranker_rejection.py` 11건.
4. **버려진 기준을 산출물에 기록.** `src/services/tte_service.py:4763`이 `_unmappedCriteria`를
   항상 반환(실패 없으면 빈 배열). 테스트 `tests/test_unmapped_criteria_are_recorded.py` 4건.
5. **`.venv`를 `requirements.txt`에 정렬 + 게이트.**
   `tests/test_environment_matches_requirements.py` 7건.
6. **대시보드 갱신** — 실험 노트 4건 / 이슈 10건 / 계획 20행. http://localhost:8898/dashboard.html

## Key decisions & why

- **매핑 모델은 이 지표의 병목이 아니다 (오늘의 헤드라인).** gpt-4o → gemma로 전 개념집합을 다시
  만들었더니 345개 중 73개(21%)가 바뀌었는데 macro recall은 **0.598 → 0.598**, precision만
  0.520 → 0.513. 더 좋은 모델로 메울 수 있는 격차가 아니다.
  단서: arm A의 비-entry 집합은 2026-08-04 store 기준이라 델타에 그 이후 코드 변경이 섞여 있다.
  "모델 단독 효과"로 인용하면 안 된다.
- **거리 임계값으로 무의미한 질의를 거르는 방안은 측정으로 기각했다.** 진짜 임상 용어 top-1 거리
  38.6~59.5, 무의미한 문자열 54.8~97.8로 **겹친다**. `zzzz not a real thing at all`(54.750)이
  `Acute coronary syndrome`(59.457)보다 가깝다. 60에 선을 그으면 진짜 기준이 잘린다.
  **다시 제안하지 말 것** — 2026-08-11 실험 노트에 근거가 있다.
- **`max_tokens=4096`을 줄이는 방향도 기각.** critic 스키마가 후보 하나당 JSON 엔트리를 내므로
  후보 90개면 출력이 3,600토큰대다. 줄이면 JSON이 잘려 파싱이 깨지는 다른 실패가 된다.
  대신 서버 컨텍스트를 8,192 → 32,768로 올렸다.
- **force-include를 없애지 않고 한정했다.** 리랭커가 *실제로 뭔가 골랐을 때*만 top-1을 얹는다.
  통째로 끄면 이 파이프라인 역사상 처음으로 빈 concept set이 나오는데(현재 374개 중 0개),
  빈 집합도 조용히 망가진다 — 포함 조건이면 환자 0명, 제외 조건이면 무효화.
- **매핑 실패 시 기준은 계속 버린다.** 기준 하나 때문에 스터디 전체를 죽일 이유는 없다. 다만
  버린 사실이 산출물에 남게 했다.
- **`uv pip sync`를 쓰지 않는다.** `requirements.txt`에 pytest가 없어 sync가 테스트 러너를
  지운다. `uv pip install -r`이 맞다.

## Next steps (ordered, concrete)

1. **critic 프롬프트/스키마 개편 — 사용자가 지정한 방향, 계획 보드 P0.**
   `src/agents/agent2/critic.py:143` `CriticSelection`이 후보 **하나당** 엔트리
   (`concept_id`, `relevant`, 자유서술 `reasoning`, `confidence`, …)를 내서 출력 길이가 후보
   수에 비례한다. **카테고리 단위 선택 + 짧은 reason**으로 바꿔 출력을 후보 수에서 떼어낼 것.
   `max_tokens=4096`은 `critic.py:297`, `:467`.
   함께 넣을 것: 지금은 "이 중 뭐가 제일 나아?"라는 강제 선택만 묻고 **"이 중에 질의와 같은 뜻인
   게 있긴 한가?"를 묻지 않는다.** 그 질문이 2번 항목의 해법 후보다.
2. **매퍼가 "매칭 없음"이라고 답할 수 있게 할 것 (P0).**
   재현: 컨테이너에서 `_build_seeded_target_circe`에 domain `Condition`,
   sourceText `qqzzxx nonexistent clinical term`을 넣으면 심근경색 관련 개념 4개가 나온다.
   로그상 `reranker → 3 selected`로 **기각이 아니라 선택**이다. 같은 리랭커가 `linagliptin`에는
   `0 selected`를 냈으므로 능력이 없는 게 아니라 질문이 강제 선택이다.
   주의: `_recommend_seeded_concept_set`을 직접 부르면 같은 문자열에 `ValueError`가 난다.
   빌더 경로는 배치 pre-fetch 후보 60개를 넘겨주기 때문에 결과가 다르다.
3. **MeSH 별칭이 store에 남지 않는 배선 고치기.**
   `src/services/tte_service.py:3443`이 `eligibility["_interventionAliases"]`에 쓰고 `:4381`이
   `pop`으로 소비한다. store의 6개 스터디 모두 이 키가 없고, `_recommend_seeded_concept_set`
   호출 지점 8곳 중 `alias_candidates`를 넘기는 곳은 `:4395` 하나뿐이다. 그래서 오늘 전면
   재매핑 뒤에도 EMPA-REG entry가 `1254065 CHF-6366 .beta.-2 metabolite` 그대로다.
   종결 조건: 별칭 보존 → 재매핑 경로가 읽어 넘김 → EMPA-REG entry가 empagliflozin이 되는지 확인.
4. **PLATO description/sourceText 불일치 범위 측정** — 어제 핸드오프 5번 그대로.
5. **남은 테스트 실패 100건 분류** — 이번 세션 변경과 무관함은 확인됐다(변경 전후 동일).

## How to verify / run

```bash
cd /home/bilab/work/projects/Broadsea/artemis

# 실행환경이 선언과 맞는지 — 다른 무엇보다 먼저
.venv/bin/python -m pytest tests/test_environment_matches_requirements.py -q
# 어긋나면:
uv pip install --python .venv/bin/python -r requirements.txt   # sync 아님

# 이번 세션에서 추가한 테스트
.venv/bin/python -m pytest tests/test_agent2_reranker_rejection.py \
  tests/test_unmapped_criteria_are_recorded.py -q

# 전체 (기준선: 100 failed / 2052 passed — 실패는 전부 기존 것)
.venv/bin/python -m pytest tests/ -q -p no:randomly

# force-include 수정이 실경로에서 먹는지 (컨테이너에서만 유효)
docker exec -i -e CRITERION_CACHE_ENABLED=false \
  -e ARTEMIS_DISABLE_EXACT_INGREDIENT_MATCH=1 artemis-api python -u - <<'PY'
from src.services.tte_service import TTEService
svc = TTEService.__new__(TTEService)
r = svc._recommend_seeded_concept_set("linagliptin", expected_domain=None)
print(sorted(i["concept"]["CONCEPT_ID"] for i in r["expression"]["items"]))   # [40239216]
PY

# 대시보드 재빌드
.venv/bin/python scripts/build_conceptset_dashboard.py
```

URLs: http://localhost:8898/dashboard.html · vLLM http://localhost:8000/v1/models

vLLM을 다시 띄워야 하면 (GB10이라 `env -u` 필수, 컨텍스트 옵션 빠지면 오늘 폐기한 고장 재현):

```bash
setsid env -u PYTHONPATH -u PYTHONHOME nohup \
  /home/bilab/work/projects/vllm/venv/bin/python -m vllm.entrypoints.openai.api_server \
  --model google/gemma-4-E4B-it --served-model-name google/gemma-4-E4B-it \
  --host 0.0.0.0 --port 8000 --max-model-len 32768 --dtype auto --enforce-eager \
  --gpu-memory-utilization 0.55 --enable-auto-tool-choice --tool-call-parser gemma4 \
  > output/vllm_gemma_32k_tools.log 2>&1 < /dev/null &
```

## Gotchas / constraints

- **임베딩이 필요한 측정은 컨테이너에서.** 이제 `.venv`에도 torch 2.11.0+cu130이 있지만,
  기준 환경은 `artemis-api`다(이미지가 `requirements.txt`로 빌드된다 — `Dockerfile.tte-api:37`).
- **`.venv`가 어긋나면 조용히 틀린 숫자가 나온다.** 오늘만 세 번 측정을 망칠 뻔했다.
  일부만 설치하면 더 나빠진다 — `langgraph==0.0.28`이 `packaging`/`tenacity`를 끌어내려
  실패가 213 → 321이 됐다. 전체를 선언대로 맞춰야 한다.
- **1차 전면 재매핑(`/app/tmp/tte_vllm_remap/`, `output/remap_gemma_full.log`)은 무효다.**
  268개 중 176개가 critic 400(8192 초과)을 받고 조용히 seed로 되돌아갔다. 증거로 보존 중이며
  **채점하지 말 것.** 유효한 것은 `tte_vllm_remap2` / `scoped_gemma.json`.
- **재매핑 시 criterion 캐시 주의.** 캐시 키에 `LLM_MODEL`이 들어가므로 같은 모델로 다시 돌리면
  이전 결과를 그대로 돌려준다. 새 디렉터리로 시작하면 캐시도 새로 생긴다(캐시는 store 디렉터리
  옆에 만들어진다).
- **PHOEBE 뷰를 오늘 만들었다.** `CREATE OR REPLACE VIEW omop_vocab.concept_recommended AS
  SELECT * FROM demo_cdm.concept_recommended;` — 되돌리려면 `DROP VIEW`. 스키마만
  `demo_cdm`으로 바꾸면 **에러 없이 0건**이 되는 함정이 있다(`demo_cdm.concept`가 444행).
  아직 파이프라인 안에서는 검증 못 했다 — PHOEBE는 `agents/conceptset/stage2_pipeline.py`에
  있고 오늘 측정한 경로(`agents/agent2/workflow.py`)와 다르다.
- **`pgrep -f`는 자기 자신을 잡는다.** 패턴 첫 글자를 대괄호로 감쌀 것(`'[r]egenerate_...'`).
  컨테이너 안에는 `pkill`이 없어서 `/proc` 순회로 죽여야 했다.
- 대시보드 기록 계약: 이슈 상태값에 `해결됨`은 **없다**(`해결`). 계약 위반 하나면
  `#record-fatal` 오버레이가 페이지 전체 클릭을 막는다. 계획 링크가 이 페이지에 없는 노트 날짜를
  가리켜도 같은 결과다(`build_plan`이 걸러주지만 새로 만들지 말 것).
