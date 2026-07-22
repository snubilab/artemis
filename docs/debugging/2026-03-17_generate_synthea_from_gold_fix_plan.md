# `generate_synthea_from_gold.py` Fix Plan

**작성일**: 2026-03-17  
**상태**: PARTIALLY IMPLEMENTED  
**대상**: `artemis/scripts/generate_synthea_from_gold.py`

### Progress
- 2026-03-17 구현 완료:
  - `ValueAsNumber.Op` 파싱 수정
  - strict/inclusive comparator 오매핑 수정
  - nested demographic/group 재귀 추출 수정
  - nested group 재귀 classification 수정
  - `Occurrence` / window / `VisitType` metadata 보존 추가
  - fixed two-encounter builder를 timeline builder로 교체
  - `Occurrence.Count > 1`, `VisitType(IP)`, relative time window를 builder에서 직접 반영
  - leaf 내부 `CorrelatedCriteria` 재귀 추출 추가
  - `RangeHighRatio`, `EndWindow`, `UseIndexEnd` unsupported tagging 추가
  - `ANY` / `AT_LEAST`를 단일 satisfying branch 선택이 아니라 path-set compiler로 승격
  - path 조합을 module `distributed_transition` branch로 내리는 full-semantics compiler 골격 추가
  - unsupported semantics reporting + `--strict` 추가
  - 회귀 테스트 `artemis/tests/test_generate_synthea_from_gold.py` 추가
- 2026-03-17 검증 완료:
  - `python -m pytest -q artemis/tests/test_generate_synthea_from_gold.py` → `11 passed`
  - `python artemis/scripts/generate_synthea_from_gold.py --gold artemis/data/gold/LEADER/LEADER_GOLD.json --out /tmp/leader_synthea_module.json --name leader_test` 성공
  - `python artemis/scripts/generate_synthea_from_gold.py --gold artemis/data/gold/ARISTOTLE/ARISTOTLE_GOLD.json --out /tmp/aristotle_synthea_module.json --name aristotle_test --strict --or-strategy random --seed 0` 성공
  - `python artemis/scripts/generate_synthea_from_gold.py --gold artemis/data/gold/LEADER/LEADER_GOLD.json --out /tmp/leader_compiler.json --name leader_test --strict` 성공
  - LEADER 산출물에 `path_count=14`, `distributed_transition` 존재 확인
  - `python artemis/scripts/generate_synthea_from_gold.py --gold artemis/data/gold/PLATO/PLATO_GOLD.json --out /tmp/plato_compiler.json --name plato_test --strict` → `RangeHighRatio` unsupported로 의도적 실패
- 남은 범위:
  - benchmark module 산출물(`data/synthea/.../artemis_*.json`) 재생성 여부 결정
  - `generate_synthea_modules.py` 기반 산출물과 문서 설명의 정합성 정리
  - `RangeHighRatio`, `EndWindow`, `UseIndexEnd`의 실제 compiler lowering 설계
  - `Days` 누락 window endpoint에 대한 default-free 해석 원칙 고정

### Goal
Gold JSON(Circe cohort definition)에서 Synthea module로 변환할 때, 현재 스크립트가 조용히 왜곡하거나 누락하는 조건들을 명시적으로 교정한다. 목표는 "Synthea가 읽는 JSON 생성"이 아니라, **현재 지원하는 Circe semantics는 정확히 반영하고, 지원하지 못하는 semantics는 조용히 무시하지 않고 드러내는 것**이다.

### Assumptions
- 현재 스크립트는 GMF v2 JSON 자체는 생성하며, `artemis_leader` 모듈은 Synthea에서 파싱된다.
- 하지만 아래 결함이 이미 확인됐다.
  - `ValueAsNumber.Op`를 읽지 않아 numeric comparator가 `EQ`로 붕괴한다.
  - nested `Groups` / `DemographicCriteriaList`를 재귀적으로 처리하지 않아 branch별 age/risk 조건이 누락된다.
  - `Occurrence.Count`, `StartWindow`, `EndWindow`를 requirement IR과 module emission에서 사실상 무시한다.
  - 전용 회귀 테스트가 없다.
- 이 계획의 기준은 "Gold 의미 보존"이다. 단순히 LEADER 한 케이스에서 환자가 나오게 만드는 편법은 허용하지 않는다.
- Synthea로 정확히 표현할 수 없는 Circe semantics가 있으면, fallback 생성보다 **명시적 경고 또는 strict 실패**가 우선이다.

### Plan
1. 회귀 테스트 뼈대를 먼저 만든다
   - Files: `artemis/tests/test_generate_synthea_from_gold.py`
   - Change:
     - 신규 테스트 파일을 추가하고 LEADER, EMPA-REG, ARISTOTLE fixture 로딩 헬퍼를 만든다.
     - 현재 알려진 버그가 failing test로 고정되도록 테스트 함수 이름과 기대값을 먼저 잡는다.
   - Verify:
     - `python -m pytest -q artemis/tests/test_generate_synthea_from_gold.py`

2. numeric comparator 버그를 테스트로 고정한다
   - Files: `artemis/tests/test_generate_synthea_from_gold.py`
   - Change:
     - `ValueAsNumber.Op`가 `lt`, `gte`일 때 올바른 operator로 파싱돼야 한다는 테스트를 추가한다.
     - `_normalize_operator("GREATERTHAN") == "GT"`, `_normalize_operator("LESSTHAN") == "LT"` 테스트를 추가한다.
   - Verify:
     - `python -m pytest -q artemis/tests/test_generate_synthea_from_gold.py -k "numeric or comparator"`

3. `ValueAsNumber.Op` 파싱을 수정한다
   - Files: `artemis/scripts/generate_synthea_from_gold.py`
   - Change:
     - `_parse_numeric_value_box()`의 operator fallback chain에 `value_box.get("Op")`를 가장 앞에 추가한다.
     - `_parse_numeric_value_box()`가 LEADER/ARISTOTLE Gold JSON의 실제 key shape를 기준으로 동작하도록 맞춘다.
   - Verify:
     - `python - <<'PY'\nfrom importlib.machinery import SourceFileLoader\nmod = SourceFileLoader('g','artemis/scripts/generate_synthea_from_gold.py').load_module()\nprint(mod._parse_numeric_value_box({'ValueAsNumber': {'Value': 7, 'Op': 'lt'}}))\nprint(mod._parse_numeric_value_box({'ValueAsNumber': {'Value': 50, 'Op': 'gte'}}))\nPY`
     - `python -m pytest -q artemis/tests/test_generate_synthea_from_gold.py -k "numeric"`

4. `_normalize_operator()` 오매핑을 수정한다
   - Files: `artemis/scripts/generate_synthea_from_gold.py`
   - Change:
     - `GREATERTHAN`이 `GE`로, `LESSTHAN`이 `LE`로 먼저 매칭되는 중복을 제거한다.
     - strict comparator와 inclusive comparator 집합을 분리해 future input에서도 완화 오매핑이 나지 않게 한다.
   - Verify:
     - `python - <<'PY'\nfrom importlib.machinery import SourceFileLoader\nmod = SourceFileLoader('g','artemis/scripts/generate_synthea_from_gold.py').load_module()\nprint(mod._normalize_operator('GREATERTHAN'))\nprint(mod._normalize_operator('LESSTHAN'))\nPY`
     - `python -m pytest -q artemis/tests/test_generate_synthea_from_gold.py -k "comparator"`

5. nested demographic 누락을 테스트로 고정한다
   - Files: `artemis/tests/test_generate_synthea_from_gold.py`
   - Change:
     - LEADER `prior CV disease`에서 random branch 선택 시 nested age requirement가 함께 따라와야 한다는 테스트를 추가한다.
     - branch choice 결과가 condition만 남고 age가 빠지는 현재 실패 케이스를 seed 고정으로 재현한다.
   - Verify:
     - `python -m pytest -q artemis/tests/test_generate_synthea_from_gold.py -k "leader and demographic"`

6. extractor를 재귀적으로 바꾼다
   - Files: `artemis/scripts/generate_synthea_from_gold.py`
   - Change:
     - `CriteriaList`, `Groups`, `DemographicCriteriaList`를 한 traversal에서 함께 순회하도록 `extract_requirements()`와 하위 helper를 재구성한다.
     - branch 선택 시 해당 branch 내부의 demographic requirement도 빠지지 않게 한다.
   - Verify:
     - `python - <<'PY'\nimport json, random\nfrom pathlib import Path\nfrom importlib.machinery import SourceFileLoader\nmod = SourceFileLoader('g','artemis/scripts/generate_synthea_from_gold.py').load_module()\ndata = json.loads(Path('artemis/data/gold/LEADER/LEADER_GOLD.json').read_text())\nrule = next(r for r in data['InclusionRules'] if r['name'] == 'prior CV disease')\nprint(mod.extract_requirements(rule, or_strategy='random', rng=random.Random(0)))\nPY`
     - `python -m pytest -q artemis/tests/test_generate_synthea_from_gold.py -k "leader and demographic"`

7. complex rule classification을 테스트로 고정한다
   - Files: `artemis/tests/test_generate_synthea_from_gold.py`
   - Change:
     - EMPA-REG `Insufficient glycemic control`이 `EXCLUSION`이 아니라 mixed/positive semantics를 가진 규칙으로 판정돼야 한다는 테스트를 추가한다.
     - LEADER, EMPA-REG에서 nested group 안의 value constraint와 positive occurrence가 함께 있을 때 skip되면 안 된다는 기준을 고정한다.
   - Verify:
     - `python -m pytest -q artemis/tests/test_generate_synthea_from_gold.py -k "classification or empa"`

8. `_classify_rule()`를 재귀 판정으로 바꾼다
   - Files: `artemis/scripts/generate_synthea_from_gold.py`
   - Change:
     - top-level `CriteriaList`와 1-depth `Groups`만 보는 현재 단순화 로직을 제거한다.
     - nested branch 전체를 재귀 순회해 positive occurrence, exclusion-only, value-constraint inversion 여부를 판정한다.
   - Verify:
     - `python - <<'PY'\nimport json\nfrom pathlib import Path\nfrom importlib.machinery import SourceFileLoader\nmod = SourceFileLoader('g','artemis/scripts/generate_synthea_from_gold.py').load_module()\ndata = json.loads(Path('artemis/data/gold/EMPA-REG/EMPA_REG_GOLD.json').read_text())\nrule = next(r for r in data['InclusionRules'] if r['name'] == 'Insufficient glycemic control')\nprint(mod._classify_rule(rule))\nPY`
     - `python -m pytest -q artemis/tests/test_generate_synthea_from_gold.py -k "classification or empa"`

9. `Occurrence.Count`와 time window 보존을 테스트로 고정한다
   - Files: `artemis/tests/test_generate_synthea_from_gold.py`
   - Change:
     - ARISTOTLE `AdditionalCriteria.CriteriaList[1].Occurrence.Count == 2`가 extractor 결과에 보존돼야 한다는 테스트를 추가한다.
     - LEADER/ARISTOTLE value rules의 `StartWindow` / `EndWindow` metadata가 requirement에 남아야 한다는 테스트를 추가한다.
   - Verify:
     - `python -m pytest -q artemis/tests/test_generate_synthea_from_gold.py -k "occurrence or window or aristotle"`

10. requirement IR에 occurrence/window metadata를 추가한다
   - Files: `artemis/scripts/generate_synthea_from_gold.py`
   - Change:
     - leaf requirement에 `occurrence_count`, `occurrence_type`, `start_days`, `start_coeff`, `end_days`, `end_coeff`, `use_event_end`를 저장한다.
     - `PrimaryCriteria.AdditionalCriteria`와 InclusionRules 모두 같은 requirement IR을 사용하게 통일한다.
   - Verify:
     - `python - <<'PY'\nimport json\nfrom pathlib import Path\nfrom importlib.machinery import SourceFileLoader\nmod = SourceFileLoader('g','artemis/scripts/generate_synthea_from_gold.py').load_module()\ndata = json.loads(Path('artemis/data/gold/ARISTOTLE/ARISTOTLE_GOLD.json').read_text())\nprint(mod._extract_primary_criteria_reqs(data))\nPY`
     - `python -m pytest -q artemis/tests/test_generate_synthea_from_gold.py -k "occurrence or window or primary"`

11. unsupported semantics 정책을 문서와 코드에 반영한다
   - Files: `artemis/scripts/generate_synthea_from_gold.py`, `artemis/docs/debugging/2026-03-17_generate_synthea_from_gold_fix_plan.md`
   - Change:
     - `Occurrence.Count > 1`, non-trivial temporal windows, fixed two-encounter architecture와 충돌하는 semantics를 unsupported candidate로 명시한다.
     - 가능한 경우 `remarks` report, 불가능한 경우 `--strict` failure로 처리하는 정책을 코드와 문서에 함께 반영한다.
   - Verify:
     - `rg -n "strict|unsupported|Occurrence.Count|window" artemis/scripts/generate_synthea_from_gold.py artemis/docs/debugging/2026-03-17_generate_synthea_from_gold_fix_plan.md`

12. builder에 `--strict`와 unsupported reporting을 추가한다
   - Files: `artemis/scripts/generate_synthea_from_gold.py`, `artemis/tests/test_generate_synthea_from_gold.py`
   - Change:
     - builder가 표현 불가능한 semantics를 감지하면 `remarks`에 남기고, `--strict`에서는 즉시 실패하게 한다.
     - 단순 event duplication으로 의미를 속이지 않도록, unsupported semantics는 침묵하지 않게 한다.
   - Verify:
     - `python artemis/scripts/generate_synthea_from_gold.py --gold artemis/data/gold/LEADER/LEADER_GOLD.json --out /tmp/leader_synthea_module.json --name leader_test`
     - `python artemis/scripts/generate_synthea_from_gold.py --gold artemis/data/gold/ARISTOTLE/ARISTOTLE_GOLD.json --out /tmp/aristotle_synthea_module.json --name aristotle_test --strict`
     - `python -m pytest -q artemis/tests/test_generate_synthea_from_gold.py -k "strict or unsupported or module"`

13. benchmark module 재생성과 smoke 검증을 분리해서 수행한다
   - Files: `data/synthea/synthea/src/main/resources/modules/artemis_leader.json`, `data/synthea/synthea/src/main/resources/modules/artemis_plato.json`, `data/synthea/synthea/src/main/resources/modules/artemis_aristotle.json`
   - Change:
     - 먼저 `/tmp/*.json`으로 generator 출력과 `remarks`를 점검한다.
     - 검증이 끝난 뒤 benchmark module 3종만 최종 경로에 덮어쓴다.
   - Verify:
     - `python artemis/scripts/generate_synthea_from_gold.py --gold artemis/data/gold/LEADER/LEADER_GOLD.json --out /tmp/artemis_leader.json --name artemis_leader --or-strategy random --code-strategy random --seed 0`
     - `java -Xmx1g -jar build/libs/synthea-with-dependencies.jar -m artemis_leader -p 1 --exporter.csv.export=false`

14. 관련 문서를 실제 산출물과 맞춘다
   - Files: `artemis/docs/synthea_benchmark_data_pipeline.md`, `artemis/docs/debugging/2026-03-17_v6_cohort_zero_patient_attrition_plan.md`, `artemis/docs/debugging/2026-03-17_generate_synthea_from_gold_fix_plan.md`
   - Change:
     - pipeline 문서의 target profile 설명이 regenerated module과 다르면 문서 또는 generator intent 중 하나로 정렬한다.
     - attrition plan에서 generator remediation 문서 링크가 최신 상태인지 확인한다.
   - Verify:
     - `git diff -- artemis/docs/synthea_benchmark_data_pipeline.md artemis/docs/debugging/2026-03-17_v6_cohort_zero_patient_attrition_plan.md artemis/docs/debugging/2026-03-17_generate_synthea_from_gold_fix_plan.md`
     - `python -m pytest -q artemis/tests/test_generate_synthea_from_gold.py`

### Risks & mitigations
- Synthea state model이 Circe temporal semantics를 1:1로 표현하지 못할 수 있다.
  - Mitigation: "best effort" silent fallback 대신 `unsupported semantics` report와 `--strict` 모드를 기본으로 설계한다.
- recursive refactor 중 LEADER는 좋아지고 EMPA/ARISTOTLE가 깨질 수 있다.
  - Mitigation: cohort별 fixture 테스트를 먼저 고정하고, LEADER/EMPA/ARISTOTLE를 각각 regression set으로 유지한다.
- comparator 수정 후 기존 생성 모듈의 임상 분포가 크게 바뀔 수 있다.
  - Mitigation: regenerated module diff와 benchmark smoke run 결과를 함께 남긴다.

### Rollback plan
- 코드 수정은 `artemis/scripts/generate_synthea_from_gold.py`와 신규 테스트 파일에 한정해 작게 나눈다.
- 각 단계는 테스트가 통과한 뒤 다음 단계로 넘어간다. 특정 단계에서 regression이 생기면 직전 커밋 또는 직전 patch 단위로 되돌린다.
- regenerated benchmark module 3종은 generator 수정이 검증되기 전까지 덮어쓰지 않는다. 먼저 `/tmp/*.json`으로 검증한 뒤 최종 산출물만 반영한다.
