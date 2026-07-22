# 2026-03-20: TTE integration progress, runtime recovery, and local env drift

## 오늘 완료

- [x] TTE backend capability shell을 typed contract 중심으로 확장
  - `mappingQuality`, validation, analysis, report payload shape 정리
  - provisional IR 기반 `suggest_*` 경로 정리
- [x] validation / execution / analysis / report capability 흐름 보강
  - execution precheck 추가
  - analysis/report gating helper 추가
  - artifact apply semantics 강화
- [x] frontend artifact pane 렌더링 보강
  - validation / execution / analysis / report artifact를 typed UI로 분리 렌더링
- [x] live `artemis-api` runtime mismatch 복구
  - bind-mounted source 대비 uvicorn hot reload 부재로 old route set이 살아 있던 상태 확인
  - `artemis-api` 컨테이너 재시작으로 live route mismatch 해소
- [x] browser smoke 재검증
  - existing study route에서 `Generate Draft -> Apply -> Validate` 확인
  - new-study route `#/tte/0 -> #/tte/{id}` sync bug 수정 및 재현 확인
- [x] Agent 5 / Agent 6 wrapper runtime fallback 제거
  - container image에 `numpy`, `pandas`, `scikit-learn`, `lifelines`, `jinja2` 추가
  - browser에서 `Run Analysis` / `Generate Report Summary`가 `Ok`로 보이는 것 확인
- [x] local dev/test dependency drift 정리
  - `.venv`에 `pip` bootstrap
  - local env를 `pyproject.toml` 기준으로 재정렬
  - `pydantic-settings`와 `lifelines` constraint 보강
- [x] supervisor / agent4 / agent5-6 local tests 복구
  - `langgraph 0.0.28`에 맞는 graph entry/finish wiring 정리
  - installed `pandas`가 있을 때 fake stub를 주입하지 않도록 테스트 보강
  - 결과: `66 passed, 1 skipped`
- [x] Pydantic deprecation warning 제거
  - `Settings` class-based `Config` -> `ConfigDict`
- [x] Mapping Agent real quality signal adapter wiring 완료
  - root cause:
    - `_run_section_suggestion(...)`가 heuristic helper만 호출해서
      `_build_real_mapping_quality_signal(...)` runtime path가 무시되고 있었음
  - fix:
    - `suggest_*` 공통 경로를 real helper로 연결
    - empty seed text / Agent 2 unavailable / Agent 2 failure는 helper 내부 safe fallback 유지
  - 결과:
    - `test_suggest_eligibility_creates_section_specific_artifact`
    - `test_suggest_treatment_creates_section_specific_artifact`
    - 둘 다 복구됨
- [x] `httpx` TestClient deprecation warning 정리
  - root cause:
    - `starlette.testclient.TestClient`가 `httpx` deprecated `app` shortcut을 사용
  - fix:
    - local compatibility test client 추가
    - `test_tte_api.py`를 compatibility client로 전환
    - warning 재현/부재 regression test 추가
  - 결과:
    - `pytest tests/test_tte_api.py -q` -> `19 passed`
- [x] artifact detail pane Knockout runtime bug fix
  - root cause:
    - `tte-manager.html` analysis/report detail block에서 `if`와 `with`를 같은 element에 같이 사용
  - fix:
    - `if` / `with`를 nested wrapper로 분리
    - frontend regression test 추가: `artemis/tests/test_tte_frontend_bindings.py`
  - 결과:
    - browser runtime binding error 제거
- [x] Playwright 기반 TTE browser smoke 추가
  - files:
    - `atlas-dev/playwright.config.js`
    - `atlas-dev/tests/e2e/tte-smoke.spec.js`
  - scope:
    - new study `Generate Draft -> Apply`
    - fresh fixture `Validate -> Execute -> Apply -> Run Analysis -> Apply -> Generate Report Summary`
    - suggestion artifact `mappingQuality` signal rendering
  - local env:
    - `atlas-dev`에 `@playwright/test` dev dependency 추가
  - 결과:
    - `cd atlas-dev && npx playwright test tests/e2e/tte-smoke.spec.js --config=playwright.config.js`
    - `3 passed`
- [x] `mappingQuality` fallback evidence handling 결정
  - decision:
    - shared local runtime에서는 forced reproduction을 하지 않음
  - 이유:
    - Agent 2 import/runtime failure를 의도적으로 유발해야 해서 비용 대비 위험이 큼
  - 정리:
    - fallback은 문서화 기준으로 관리
    - 필요 시 isolated backend test로만 추가 검증
- [x] isolated backend fallback regression test 추가
  - files:
    - `artemis/tests/test_tte_api.py`
  - scope:
    - `agent2_unavailable:ImportError`
    - `agent2_failed:RuntimeError`
  - 방식:
    - shared local runtime mutation 없이 test-local monkeypatch / fake module injection 사용
  - 결과:
    - `cd artemis && .venv/bin/pytest tests/test_tte_api.py tests/test_tte_frontend_bindings.py -q`
    - `22 passed`
- [x] TTE stored entries cleanup
  - rule:
    - `study id=34`만 유지
  - execution:
    - 나머지 study 전부 삭제
    - orphan artifact/job도 store JSON에서 함께 정리
  - verify:
    - study count `1`
    - artifact count `4`
    - job count `4`

## 진행중

- 없음

## 핵심 관찰

### 1. live runtime과 local test env는 다른 문제였다

- live runtime은 container rebuild/restart로 복구 가능했다
- local `.venv`는 repo dependency definition과 실제 설치 상태가 어긋나 있었고,
  별도로 정리해야 했다

### 2. wrapper runtime 경로는 이제 실제로 살아 있다

- smoke fixture study `15` 기준:
  - `run-analysis` -> `status: ok`
  - `generate-report-summary` -> `status: ok`
- browser에서도 `Run_analysis` / `Generate_report_summary`가 `Ok`로 보였다

### 3. 핵심 blocker는 wiring 문제였고, 지금은 복구됐다

- `mappingQuality` 문제의 핵심은 dependency incompatibility보다
  `_run_section_suggestion(...)` 호출 경로 누락이었다
- call site를 real helper로 연결하자 `test_tte_api.py`가 다시 녹색으로 복구됐다
- 이제 남은 일은 wiring repair가 아니라 browser-level recheck나 후속 문서화에 가깝다

## 오늘 수정한 주요 파일

### 코드

- `artemis/src/api/models/tte.py`
- `artemis/src/models/ir.py`
- `artemis/src/services/tte_service.py`
- `artemis/src/pipeline/supervisor_agent.py`
- `artemis/src/settings.py`
- `artemis/Dockerfile.tte-api`
- `artemis/pyproject.toml`
- `atlas-dev/js/pages/target-trial-emulation/tte-manager.js`
- `atlas-dev/js/pages/target-trial-emulation/tte-manager.html`
- `atlas-dev/js/pages/target-trial-emulation/tte-manager.less`

### 테스트

- `artemis/tests/test_tte_api.py`
- `artemis/tests/test_supervisor.py`
- `artemis/tests/test_supervisor_agent.py`

### 문서

- `docs/tte_agent/06_backend_atomic_todo_plan.md`
- `docs/tte_agent/07_current_status.md`

## 검증 이력

성공:

```bash
cd /Users/kyh/Workspace/Broadsea/artemis
.venv/bin/pytest tests/test_supervisor.py tests/test_supervisor_agent.py tests/test_agent4.py tests/test_agents_5_6.py -q
```

결과:

- `66 passed, 1 skipped`

성공:

```bash
cd /Users/kyh/Workspace/Broadsea/artemis
.venv/bin/pytest tests/test_tte_api.py::test_suggest_eligibility_creates_section_specific_artifact tests/test_tte_api.py::test_suggest_treatment_creates_section_specific_artifact -q
```

결과:

- `2 passed`

성공:

```bash
cd /Users/kyh/Workspace/Broadsea/artemis
.venv/bin/pytest tests/test_tte_api.py -q
```

결과:

- `18 passed, 18 warnings`

성공:

```bash
node -e "const fs=require('fs'); new Function(fs.readFileSync('atlas-dev/js/pages/target-trial-emulation/tte-manager.js','utf8')); console.log('ok')"
```

결과:

- `ok`

성공:

```bash
curl http://127.0.0.1/artemis-api/tte/studies/15/run-analysis
curl http://127.0.0.1/artemis-api/tte/studies/15/generate-report-summary
```

결과:

- both `status: ok`

참고:

- `httpx 0.27.2 / fastapi 0.109.2 / starlette 0.36.3`
- 현재는 `TestClient(...)` crash가 아니라 warning-only 상태다

## 다음 작업 후보

1. 없음
2. 이 TTE stream은 문서/검증 기준으로 마감
