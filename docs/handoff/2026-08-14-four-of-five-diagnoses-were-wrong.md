# Handoff — 다섯 진단 중 넷이 틀렸다 — 2026-08-14

## Goal / context

앞선 핸드오프(`2026-08-13-three-machines-that-were-never-switched-on.md`)가 남긴
Next steps 6건을 처리한 세션. 1번을 직접 조사하고, 나머지 2~6번은 workflow로
병렬 조사한 뒤 **각 결과를 별도 에이전트가 반증**하게 했다.

관통 주제는 앞 세션과 다르다. 앞 세션은 "구현됐는데 아무도 호출하지 않는 기계"였다.
이번 세션은 **"그럴듯한데 틀린 진단"** 이다. 핸드오프가 지목한 원인 6건 중 실측을
버틴 것은 1건뿐이고, 내가 세션 중 만든 측정도 두 번 틀렸다. 전부 재유도해서 잡았다.

## Current state

- 브랜치 `fix/tte-a-drug-anchored-entry` · HEAD `72ecd87` · **PR 없음** (`git remote` 없음)
- 작업 트리 **깨끗** (uncommitted 0). 루트 저장소도 깨끗 (`main`, `5ef3fd1`)
- 테스트: **100 failed / 2142 passed / 10 skipped** — 실패 100건은 세션 시작 시점과
  동일, 회귀 0. 늘어난 통과분(2118 → 2142)은 전부 이번 세션 신규 테스트
- 실행 중:
  - vLLM PID `3708833` — `google/gemma-4-E4B-it`, `:8000`, max-model-len 32768,
    `--gpu-memory-utilization 0.55`
  - 컨테이너 `artemis-api` / `ohdsi-webapi` / `broadsea-atlasdb` / `artemis-neo4j-v2` Up
- 새 아티팩트:
  - `scripts/analyze_alias_tier_refusals.py` (읽기 전용, 재실행 가능)
  - `scripts/assets/dashboard-template.html` (vendoring된 대시보드 템플릿)
  - `output/conceptset_overlap/scoped_mesh_fix_retiredfwd.json` (폐기개념 정규화 후 재채점)
  - `output/conceptset_overlap/dashboard.html` 재생성 (plan 20 → 22행)
- **`artemis-api` 컨테이너는 아직 옛 `tte_service.py`를 들고 있다.** 프로덕션 반영은 별건

## Done this session

| 커밋 | 내용 |
| --- | --- |
| `909a31c` | 앞 세션 핸드오프 커밋 (untracked였음) |
| `952fab8` | **alias 거부 원인 분해 측정** + 스크립트 + 테스트, 전제 반증 |
| `816da96` | **성분 이름 브릿지** — 순서 있는 3단계 probe |
| `cf40ddc` | **내 측정 오류 정정** — seed 컬럼·스토어 착오 |
| `df4ba0a` | **대시보드 silent fallback** + 템플릿 고정 + 데모데이터 게이트 |
| `7aa017c` | **`_VOCAB_PREFERENCE` 사문 항목 삭제** + 발화 불가능 테스트 교체 |
| `72ecd87` | **채점기 어휘 버전 정규화** (폐기개념 → 표준 대체) |

## Key decisions & why

### 항목 1 — 거부 원인은 모호성 게이트가 아니었다

핸드오프는 55% 거부를 `len(resolved) != 1` 탓으로 보고 그 분기를 지목했다. 이 tier가
실제로 필요한 94개 시험(arm·intervention·otherNames 어디에도 일반명이 없는 EMPA-REG형)
에서 재보니:

| 결과 | 건수 |
| --- | ---: |
| 통과 (정확히 하나 해결) | 9 |
| 거부 — **하나도 해결 안 됨** | **84** |
| 거부 — 둘 이상 해결 (모호) | **1** |

게이트를 풀었다면 1건을 얻고 `8692a55`(비교약이 시험약 슬롯에 들어가던 결함)를
되돌렸을 것이다. **게이트는 손대지 않았다.**

미해결 88개 용어의 정체: 대부분 회수 대상이 아니다 — 약이 아니거나(`Office Visits`,
`Watchful Waiting`), MeSH가 개발코드를 그대로 색인했거나(`SB 223412`), IUPAC 조직명
(PubChem이 이미 기각된 구간). 죽인 가설 셋: OMOP 내부 MeSH 어휘(**미적재**),
`concept_synonym` 경로(**0건**), MeSH 도치 표목 복원(**0건** — `Natriuretic Peptide,
Brain`을 뒤집으면 검사 항목이 나온다).

### 브릿지는 순서 있는 probe여야 한다

`_resolve_ingredient_concept_id`가 RxNorm → RxNorm Extension →
`Precise Ingredient --Maps to--> Ingredient` 순으로 묻고, **각 단계가 종결적**이다.
RxNorm에서 모호한 이름은 여전히 거부하고 아래로 새지 않는다. 그래서 "지금 아무것도
아니던 이름"만 새로 풀린다 — MeSH 용어 +33 해결, **0 손실**.

`vocabulary_id IN (...)`로 한 번에 넓혔다면 "RxNorm에서 유일한데 Extension에도 있는
이름"이 모호해져 조용히 퇴행한다. 현 모집단에선 그런 이름이 0개였지만, 순서를 두면
**모집단과 무관하게** 그 위험이 사라진다.

**7건 회수** (8건이 아니다). NCT07531173은 염 표목이 둘이라 0 → 2로 가서 거부에 남는다 —
브릿지가 모호성을 없애는 게 아니라 만들 수도 있다.

### 내가 두 번 틀렸고 재유도로 잡았다

1. **blast radius를 잘못된 컬럼으로 쟀다.** 매핑 seed는 `sourceText or description`
   (`tte_service.py:5827`)인데 `conceptSetName`으로 쟀다. 게다가 채점 아티팩트는
   `tmp/tte`가 아니라 **`tmp/mesh_fix`**에서 나왔고 둘은 criterion id가 안 맞는다.
   바로잡으니 새로 풀리는 seed가 스토어별로 하나씩, 그것도 다른 이름이었다.
2. **"8건 회수"가 과대였다.** tier 자신의 "정확히 하나" 규칙을 적용 안 했다.

### 폐기개념은 덧붙이지 말고 치환해야 한다

첫 구현은 폐기 id를 대체 개념 **옆에** 남겼다("옛 CDM에서도 맞아야 하니까"). 재보니
전달은 **gold만** 건드린다 — generated는 6개 시험 전부 0건(파이프라인이 표준 개념으로만
만든다). 그래서 덧붙이기는 gold 분모에 파이프라인이 **구조적으로 낼 수 없는** id를
남겼고 움직인 6쌍 중 **5쌍이 내려갔다**. 치환으로 바꾸니 내려가는 쌍이 사라졌다.

### `Device` 선호는 지우지 않았다

에이전트는 "스토어에 Device 도메인 기준이 0개니 지워도 된다"고 했다. 그러나
`effective_domain = domain_hint or domain`이라 힌트 없는 질의에서는 **후보 자신의
도메인**이 쓰이고, 컬렉션에 Device 후보가 실재한다(SNOMED·HCPCS·NDC). 지웠다면
−0.05가 +0.05로 뒤집힌다.

## 반증된 진단 4건 (workflow, 10 에이전트)

| 항목 | 핸드오프의 진단 | 실측 |
| --- | --- | --- |
| 2 `_VOCAB_PREFERENCE` | "567개 전체 측정 필요" | 도달 범위가 1/3. Measurement 30개 중 10개가 top-3를 바꾸고 채점 쌍에 드는 건 4개 |
| 3 무기록 드롭 39/9 | "30건이 무기록" | 39도 30도 **어떤 정의로도 재현 불가**. 진짜 수는 **73** (demographic-no-rule 12 + isGroupLabel 61) |
| 4 반복 누락 4종 | "체계적, 규칙 하나로 회수" | 귀무분포 셔플 2000회: 기대 19.10±2.35, 관측 21, **p=0.276** — 기저율이다 |
| 5 원문 폐기 | "원문형 5/5 vs 맨 약어 0/5" | `eGFR < 60 (Cockcroft-Gault)`는 **이미 스토어에 있는 `description`**이지 버려지는 원문이 아니다. 진짜 프로토콜 문장은 **0/5** |
| 6 대시보드 staleness | "채점기 반영 필요" | staleness 델타는 분모 아티팩트. arm A−B 격차는 두 채점기에서 **소수점 4자리까지 동일** |

항목 5의 대안이던 "`description`을 seed로"는 공식 채점기로 재니 매크로 recall
**0.3876 → 0.3171 (−0.0705)**. 하면 손해다.

## 측정

폐기개념 정규화 전후 (mesh_fix arm, 동일 채점기):

| | matched-only | 고정 모집단(232개 gold) |
| --- | --- | --- |
| MACRO recall | 0.6417 → 0.6420 | 0.3878 → 0.3879 |

다섯 쌍이 전부 위로, 최대 PLATO `PCI and CABG` 0.365 → 0.385. **±0.02 아래라 개선으로
주장하지 않는다.** 이 변경의 값은 앞으로의 비교에서 제거한 아티팩트에 있다.

## Next steps (ordered, concrete)

1. **T2DM 정의** — 노이즈 위 유일한 레버(+0.0267, 중복제거 기준, p=0.064). 생성 세트가
   201826(closure 15)인데 gold는 201820+442793+443238 − T1DM(closure 393)이라 진부분집합.
   개념 15 → 393으로 넓히는 **의미론적 결정**이므로 ADR + 캐시 끈 재실행 필요. precision이
   0.875에서 떨어지고, 같은 시험들이 들고 있는 T1DM 제외 기준(CARMELINA csid 53,
   CAROLINA excl 9)과 충돌할 수 있다. **사용자가 이번 세션에서 보류하기로 결정.**
2. **`substance abuse`는 생성이 없다.** 5개 시험 전부 `no_counterpart` — 채점기가 아니라
   추출/매핑 문제. 채점기를 다시 손대지 말 것.
3. **항목 3 계측** — `_skippedCriteria` + `_generationCensus`를
   `_build_seeded_target_circe`에 추가해 73건을 세게 만들기. `_unmappedCriteria`는 건드리지
   말 것(`tests/test_unmapped_criteria_are_recorded.py`가 길이를 고정).
4. **프로덕션 반영 결정** — `artemis-api`가 옛 `tte_service.py`를 들고 있다.
5. **항목 5는 닫혔다.** 굳이 하려면 원문을 아무도 안 읽는 새 키(`protocolText`)로 저장만
   해서 ADR-032 분류기에 주는 것까지. 질의는 바꾸지 말 것.

## How to verify / run

```bash
cd /home/bilab/work/projects/Broadsea/artemis

# 실행환경 게이트 — 다른 무엇보다 먼저
.venv/bin/python -m pytest tests/test_environment_matches_requirements.py -q

# 이번 세션 신규 테스트
.venv/bin/python -m pytest \
  tests/test_alias_tier_refusal_analysis.py \
  tests/test_ingredient_name_bridges.py \
  tests/test_retired_concept_forwarding.py \
  tests/test_map_retriever_scoring.py -q -p no:randomly

# 전체 (기준선: 100 failed / 2142 passed / 10 skipped)
.venv/bin/python -m pytest tests/ -q -p no:randomly

# alias tier 거부 분해 (읽기 전용, DB 필요)
.venv/bin/python scripts/analyze_alias_tier_refusals.py
# 기대: sponsor-silent 94 / accepts 9 / no-resolve 84 / ambiguous 1 / 브릿지 7건 회수
```

**브릿지가 실제 어휘에서 먹는지:**

```bash
.venv/bin/python -c "
from unittest.mock import MagicMock
from src.services.tte_service import TTEService
svc = TTEService(store=MagicMock())
for s in ('linagliptin','Quetiapine Fumarate','prothrombin complex concentrate','BI 10773','Office Visits'):
    print(f'{s:34s} -> {svc._resolve_ingredient_concept_id(s)}')
"
# 기대: 40239216 / 766814 / 1254255 / None / None
```

**대시보드 재생성 + 렌더 확인** (데모데이터 게이트 포함):

```bash
.venv/bin/python scripts/build_conceptset_dashboard.py
# plan 22행이어야 한다. 0행이면 docs/wiki 레코드 경로가 또 움직인 것 — 이제는 조용히
# 지나가지 않고 예외로 죽는다.
```

## Gotchas / constraints

- 🔴 **매크로는 matched 쌍만 평균한다** (`conceptset_overlap_eval.py:472`). 짝 없는 gold는
  0점이 아니라 **분모에서 빠진다**. 채점기의 짝짓기를 바꾸는 변경은 품질과 무관하게
  매크로를 움직인다. 아크 대 아크(같은 채점기) 비교는 안전하고, mesh_fix 결과는 그 경우다 —
  EMPA-REG 분자가 11.04 → 14.03으로 올랐고 고정 모집단 기준 이득은 +0.079다.
  **채점기가 바뀐 비교는 고정 모집단으로 인용하거나 인용하지 말 것.**
- **매핑 seed는 `sourceText or description`이지 `conceptSetName`이 아니다.**
  이 착오를 이번 세션에 한 번 했다.
- **채점 아티팩트는 `tmp/mesh_fix/studies.json`에서 나왔다**, `tmp/tte/studies.json`이
  아니다. criterion id가 안 맞는다.
- **미등록 어휘는 중립이 아니라 +0.05 페널티다** (`vocab_prefs.get(vocab, 0.05)`).
  `_VOCAB_PREFERENCE`에서 항목을 지우는 건 값이 이미 0.05거나 그 어휘가 해당 도메인에
  없을 때만 no-op이다.
- **대시보드 템플릿은 이제 저장소 안에 있다** (`scripts/assets/`). 스킬 쪽 템플릿을 다시
  가져오려면 의도적으로 vendoring할 것. 스크립트가 안 채우는 데이터 블록이 남으면
  빌드가 죽는다 — `litdata`가 데모 2,041바이트를 싣고 나갈 뻔했다.
- **`pgrep -f`의 괄호는 명령 안 모든 사본에 있어야 한다.** 이번에도
  `echo "=== vllm ==="`의 괄호 없는 사본 하나 때문에 자기 명령을 잡았다.
- **warm criterion 캐시가 매핑 수정을 통째로 가린다** (앞 핸드오프와 동일). 측정할 땐
  `CRITERION_CACHE_ENABLED=false`.
- **임베딩 경로는 실행 간 비결정적이다.** 1뽑기로 ±0.02 미만 델타를 주장하지 말 것.
- **`artemis/tmp/`는 root 소유.** 호스트에서 store를 못 고친다.
- 이 저장소는 **remote가 없다** — `gh pr` 계열은 쓸 수 없다.
- `ruff`는 이 `.venv`에 없고 설치하면 안 된다(환경 게이트가 `requirements.txt` 일치를
  강제). 이번 세션 코드는 린트를 돌리지 못했다.
