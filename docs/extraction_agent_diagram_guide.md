# Extraction Agent — Internal Architecture 다이어그램 가이드

## 🎨 디자인 시스템 (Mapping Agent 스타일 확장)

### 색상 팔레트
| 용도 | HEX | 설명 |
|------|-----|------|
| 배경 | `#F5F7FA` | 연한 회색 (캔버스) |
| 메인 섹션 배경 | `#FFF8E1` | 연한 노란색 (Extraction Agent 블록) |
| 서브 섹션 배경 | `#FFFFFF` | 흰색 (내부 컴포넌트) |
| 헤더/타이틀 | `#1A1A2E` | 거의 검정 |
| 강조 텍스트 | `#F57F17` | 진한 주황 (Extraction 테마) |
| 점선 테두리 | `#FFE082` | 밝은 노란 (dashed border) |
| 실선 테두리 | `#F57F17` | 진한 주황 (solid border) |
| 화살표 | `#37474F` | 진한 회색 |
| DATABASE 아이콘 | `#1565C0` | 파란색 (OMOP CDM) |
| 피드백 화살표 | `#E53935` | 빨간색 (retry loop) |
| OUTPUT 배경 | `#263238` | 거의 검정 (칩/DataFrame 블록) |
| STEP 라벨 | `#B0BEC5` | 회색 (STEP 1, STEP 2...) |
| 진단 블록 배경 | `#FFF3E0` | 연한 주황 (진단/검증 영역) |
| 성공 | `#E8F5E9` | 연한 초록 |

### 폰트
- **타이틀**: Bold, 28-32pt (예: Inter, Pretendard, Noto Sans)
- **섹션 헤더**: SemiBold, 16-18pt
- **본문**: Regular, 11-13pt
- **코드/필드명**: Monospace (예: SF Mono, Fira Code), 10-12pt, *이탤릭*
- **SQL 쿼리**: Monospace, 10pt, 회색 배경

### 아이콘
| 위치 | 아이콘 | 설명 |
|------|-------|------|
| 타이틀 | ⚙️ 톱니바퀴 | "Extraction Agent" 옆 |
| 입력 | 📄 문서 | Circe-be JSON |
| DB | 🛢️ 실린더 | OMOP CDM (PostgreSQL) |
| SQL | `</>`  | SQL Query Builder |
| 진단 | 🔍 돋보기 | Diagnostic Query |
| 확장 | 🌳 나무 | Descendant Expansion |
| 체크 | ✓✗ | Extraction Check |
| 출력 | 📊 차트 | Patient DataFrame |
| 피드백 | ↺ 화살표 | Retry Loop |

---

## 📐 레이아웃 (1400 x 1100px 권장)

```
┌────────────────────────────────────────────────────────────────────┐
│  ⚙ Extraction Agent — Internal Architecture                       │
│                                                                    │
│  INPUT                                                             │
│  ┌──────────────┐                                                  │
│  │ Circe-be JSON│                                                  │
│  │ (from Agent 4)│                                                 │
│  └──────┬───────┘                                                  │
│         ▼                                                          │
│  STEP 1                                                            │
│  ┌──────────────────────────────────────────────────────┐          │
│  │  Parse ConceptSets                                    │          │
│  │  ┌──────────────┐  ┌──────────────┐                  │          │
│  │  │ Target Drug  │  │ Comparator   │  ┌────────────┐  │          │
│  │  │ Concept IDs  │  │ Drug IDs     │  │ Outcome    │  │          │
│  │  └──────────────┘  └──────────────┘  │ Concept IDs│  │          │
│  │                                       └────────────┘  │          │
│  └──────────────────────────┬───────────────────────────┘          │
│                             ▼                                      │
│  STEP 2                                                            │
│  ┌──────────────────────────────────────────────────────┐          │
│  │  SQL Query Builder (OMOPConnector)                    │          │
│  │                                                       │          │
│  │  ┌─ extract_drug_cohort ──────────────────────┐      │          │
│  │  │ SELECT person_id, drug_exposure_start_date │      │          │
│  │  │ FROM {schema}.drug_exposure                │      │          │
│  │  │ WHERE drug_concept_id IN (:ids)            │      │          │
│  │  └────────────────────────────────────────────┘      │          │
│  │                                                       │          │
│  │  ┌─ extract_demographics ─────────────────────┐      │          │
│  │  │ SELECT person_id, year_of_birth, gender... │      │          │
│  │  └────────────────────────────────────────────┘      │          │
│  │                                                       │          │
│  │  ┌─ extract_outcome ──────────────────────────┐      │          │
│  │  │ SELECT person_id, condition_start_date     │      │          │
│  │  │ time-to-event calculation                  │      │          │
│  │  └────────────────────────────────────────────┘      │          │
│  └──────────────────────────┬───────────────────────────┘          │
│                             ▼                                      │
│  STEP 3           ┌─────── 🛢️ ──────────────────────┐              │
│                   │  OMOP CDM Query                   │              │
│                   │  PostgreSQL ({schema})            │              │
│                   │                                   │              │
│                   │  Tables:                          │              │
│                   │  • drug_exposure                  │              │
│                   │  • condition_occurrence           │              │
│                   │  • person                         │              │
│                   │  • concept_ancestor               │              │
│                   └───────────────┬───────────────────┘              │
│                                   ▼                                  │
│  STEP 4   ┌───────────────────────────────────────────────┐         │
│           │  Extraction Check                              │         │
│           │                                                │         │
│           │  ┌───────────── Decision ──────────────────┐   │         │
│           │  │                                         │   │         │
│           │  │   n_target ≥ MIN_PATIENTS (10)?        │   │         │
│           │  │   n_comparator ≥ MIN_PATIENTS?         │   │         │
│           │  │                                         │   │         │
│           │  └───────┬───────────────────┬─────────────┘   │         │
│           │     YES  │                   │  NO             │         │
│           │          ▼                   ▼                  │         │
│           │  ┌────────────┐  ┌─────────────────────────┐   │         │
│           │  │ ✓ PASS     │  │ ✗ DIAGNOSE              │   │         │
│           │  │ Continue   │  │                         │   │         │
│           │  └────────────┘  │  ┌───────────────────┐  │   │         │
│           │                  │  │ diagnose_concepts()│  │   │         │
│           │                  │  │ concept in DB?     │  │   │         │
│           │                  │  │ patients exist?    │  │   │         │
│           │                  │  └─────────┬─────────┘  │   │         │
│           │                  │       ┌────┴────┐       │   │         │
│           │                  │  Concept│   No   │       │   │         │
│           │                  │  Exists │Concept │       │   │         │
│           │                  │       ▼       ▼         │   │         │
│           │                  │  ┌────────┐┌──────────┐ │   │         │
│           │                  │  │Relax   ││Descendant│ │   │         │
│           │                  │  │min_exp ││Expansion │ │   │         │
│           │                  │  │_days=0 ││🌳 ANCESTOR│ │   │         │
│           │                  │  └────────┘└──────────┘ │   │         │
│           │                  └─────────────────────────┘   │         │
│           └───────────────────────────────────────────────┘         │
│                                   │                                  │
│                                   ▼                                  │
│               ┌──────────┐                                          │
│               │ Build    │                                          │
│               │ Analysis │                                          │
│               │ Dataset  │                                          │
│               └────┬─────┘                                          │
│                    │                                                 │
│                    ▼                                                 │
│  OUTPUT                                                             │
│  ┌─────────────────────────────────────────────────┐                │
│  │  📊 Patient DataFrame                            │                │
│  │                                                  │                │
│  │  Columns:                                        │                │
│  │  person_id | treatment | age | gender_male |     │                │
│  │  race_concept_id | time | event                  │                │
│  │                                                  │                │
│  │  Ready for Agent 5 (Analysis)                    │                │
│  └─────────────────────────────────────────────────┘                │
│                                                                      │
│  ┌─ Feedback Loops (점선 빨간 화살표) ──────────────────────────┐    │
│  │                                                               │    │
│  │  Loop 4: Extraction Check FAIL                               │    │
│  │    → Diagnose → Descendant Expansion → SQL 재실행            │    │
│  │    ↺ (STEP 4 → STEP 2, max 2 retries)                       │    │
│  │                                                               │    │
│  │  Loop 5: Schema/Query Error                                  │    │
│  │    → Agent 4 재검증 요청 (Mapping Sub-Supervisor로 복귀)     │    │
│  │    ↺ (STEP 3 → Agent 4 Validator)                            │    │
│  │                                                               │    │
│  └───────────────────────────────────────────────────────────────┘    │
│                                                          ⚙ BILab    │
└────────────────────────────────────────────────────────────────────┘
```

---

## 📝 각 박스별 상세 내용

### INPUT (상단)
```
┌─ 📄 ─────────────────────┐
│  INPUT                    │
│  Circe-be JSON            │
│  (from Agent 4 Validator) │
│                           │
│  {                        │
│    "ConceptSets": [...],  │
│    "PrimaryCriteria": {}  │
│  }                        │
└───────────────────────────┘
  ↑ "from Mapping Sub-Supervisor" 라벨
```
- 스타일: 흰색 배경, 밝은 주황 테두리, 둥근 모서리 (8px)
- JSON 미리보기는 monospace 이탤릭

---

### STEP 1: Parse ConceptSets
```
┌─ 📄 ─────────────────────────────────────────────────┐
│  Parse ConceptSets                                    │
│                                                       │
│  _extract_drug_concepts(circe_json)                   │
│  _extract_outcome_concepts(circe_json)                │
│                                                       │
│  ┌──────────────────────┐ ┌──────────────────────┐   │
│  │ Target Drug IDs      │ │ Comparator Drug IDs  │   │
│  │ e.g. [40166035, ...] │ │ e.g. [1502809, ...]  │   │
│  └──────────────────────┘ └──────────────────────┘   │
│                                                       │
│  ┌──────────────────────────────────────────────┐    │
│  │ Outcome Concept IDs                          │    │
│  │ e.g. [260139] (default: upper resp infection)│    │
│  │                                               │    │
│  │ Strategy: name-based detection               │    │
│  │   "outcome" | "event" | "death" in CS name   │    │
│  └──────────────────────────────────────────────┘    │
│                                                       │
│  ⚠ Heuristic: cs_id=0 → target, cs_id=1 → comparator│
│     Fallback: first=target, second=comparator         │
└───────────────────────────────────────────────────────┘
```
- 스타일: `#FFF8E1` 배경, 점선 주황 테두리
- 함수명은 monospace 이탤릭
- ⚠ 경고는 주황색 텍스트

---

### STEP 2: SQL Query Builder (OMOPConnector)
```
┌─ </> ─────────────────────────────────────────────────────┐
│  SQL Query Builder (OMOPConnector)                         │
│                                                            │
│  ┌─ extract_drug_cohort() ─────────────────────────────┐  │
│  │ SELECT person_id, drug_exposure_start_date,          │  │
│  │        drug_exposure_end_date                        │  │
│  │ FROM {schema}.drug_exposure de                       │  │
│  │ JOIN {schema}.person p ON de.person_id = p.person_id │  │
│  │ WHERE de.drug_concept_id IN (:drug_concept_ids)      │  │
│  │ GROUP BY de.person_id                                │  │
│  │ HAVING SUM(exposure_days) >= :min_exposure_days      │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                            │
│  ┌─ extract_demographics() ────────────────────────────┐  │
│  │ SELECT person_id,                                    │  │
│  │   EXTRACT(YEAR FROM CURRENT_DATE) - year_of_birth,  │  │
│  │   CASE WHEN gender_concept_id = 8507 THEN 1 ELSE 0  │  │
│  │ FROM {schema}.person                                 │  │
│  │ WHERE person_id IN (:person_ids)                     │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                            │
│  ┌─ extract_outcome() ─────────────────────────────────┐  │
│  │ Time-to-event:                                       │  │
│  │  • Find first condition_occurrence after index_date  │  │
│  │  • Censor at followup_days (default: 365)           │  │
│  │  • event=1 if outcome observed, else 0              │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                            │
│  Config: schema = settings.OMOP_SCHEMA (default: synthea100k) │
│  Engine: SQLAlchemy (lazy initialization)                  │
└────────────────────────────────────────────────────────────┘
```
- 스타일: 흰색 배경, 실선 주황 테두리
- SQL 블록은 monospace, 회색 배경 (#F5F5F5)
- 각 SQL 함수를 별도 내부 박스로

---

### STEP 3: OMOP CDM Query (데이터베이스)
```
┌─ 🛢️ ──────────────────────────────────────────┐
│  OMOP CDM (PostgreSQL)                         │
│                                                │
│  Schema: {schema} (e.g. synthea100k)           │
│                                                │
│  ┌─ Tables Used ──────────────────────────┐   │
│  │  • drug_exposure     (약물 노출 기록)  │   │
│  │  • condition_occurrence (진단 기록)    │   │
│  │  • person            (인구통계)        │   │
│  │  • concept_ancestor  (개념 계층)       │   │
│  │  • concept           (표준 용어)       │   │
│  └────────────────────────────────────────┘   │
│                                                │
│  Connection:                                   │
│  postgresql://postgres:mypass@localhost:5432    │
└────────────────────────────────────────────────┘
```
- 스타일: DB 실린더 아이콘 + 파란색 테두리
- 실린더 형태로 그리면 더 직관적

---

### STEP 4: Extraction Check (의사결정 다이아몬드)
```
┌─ 🔍 ──────────────────────────────────────────────────────┐
│  Extraction Check                                          │
│                                                            │
│         ┌─────────────────────────┐                       │
│         │  n_target ≥ 10?         │                       │
│         │  n_comparator ≥ 10?     │                       │
│         └─────────┬───────────────┘                       │
│              ┌────┴────┐                                   │
│          YES │         │ NO                                │
│              ▼         ▼                                   │
│         ┌────────┐ ┌────────────────────────────────────┐ │
│         │ ✓ PASS │ │ 🔍 Diagnose                        │ │
│         │        │ │                                    │ │
│         │ Build  │ │  diagnose_concepts()               │ │
│         │ final  │ │   ├── concept_id EXISTS in DB?     │ │
│         │ dataset│ │   └── patients with exposure?      │ │
│         │        │ │                                    │ │
│         └────────┘ │  ┌────────────┬───────────────┐    │ │
│                    │  │ Concept    │ No Concept     │    │ │
│                    │  │ exists,    │ in DB          │    │ │
│                    │  │ no patient │                │    │ │
│                    │  ▼            ▼                │    │ │
│                    │ ┌──────────┐ ┌──────────────┐ │    │ │
│                    │ │ Relax    │ │ 🌳 Descendant │ │    │ │
│                    │ │ min_exp  │ │  Expansion   │ │    │ │
│                    │ │ _days=0  │ │ CONCEPT_     │ │    │ │
│                    │ │          │ │ ANCESTOR     │ │    │ │
│                    │ └──────────┘ └──────────────┘ │    │ │
│                    │                                │    │ │
│                    │  ↺ Re-query (max 2 retries)    │    │ │
│                    └────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────┘
```
- 의사결정 박스: 다이아몬드 또는 둥근 노란색 박스
- YES: 초록색 화살표, NO: 빨간색 화살표
- 진단 서브 블록: `#FFF3E0` 배경

---

### OUTPUT (하단)
```
┌─────────────────────────────────────────────────┐
│  ■ DataFrame                                     │  ← 어두운 칩 스타일 (#263238)
│                                                  │
│  📊 Patient DataFrame                            │
│                                                  │
│  person_id | treatment | age | gender_male |     │
│  race_concept_id | time | event                  │
│                                                  │
│  → Ready for Agent 5 (Analysis Agent)            │
│    PSM/IPTW + Cox Proportional Hazards           │
└─────────────────────────────────────────────────┘
```
- Mapping Agent OUTPUT과 동일한 어두운 칩 스타일
- 어두운 배경에 흰색 텍스트

---

## 🔗 화살표 & 연결 규칙

| From | To | 라벨 | 스타일 |
|------|----|------|--------|
| INPUT | STEP 1 | - | 실선, 검은 화살표 |
| STEP 1 | STEP 2 | "target_ids, comparator_ids, outcome_ids" | 실선 |
| STEP 2 | STEP 3 | "SQL queries" | 실선 |
| STEP 3 | STEP 4 | "query results (DataFrames)" | 실선 |
| STEP 4 (PASS) | OUTPUT | "build_analysis_dataset()" | 실선, 초록 |
| STEP 4 (FAIL) | Diagnose | "n < MIN_PATIENTS" | 점선, 빨강 |
| Diagnose → Relax | STEP 2 | "Loop 4a: min_exposure_days=0" | 점선, 빨강 |
| Diagnose → Expand | STEP 2 | "Loop 4b: descendant concept IDs" | 점선, 빨강 |
| STEP 3 (error) | Agent 4 | "Loop 5: Schema error → re-validate" | 점선, 빨강, 외부 |
| STEP 4 (3-strikes) | ERROR | "ExtractionError raised" | 실선, 빨강 |

### 피드백 루프 화살표 스타일
| Loop | 색상 | 스타일 | 라벨 |
|------|------|--------|------|
| Loop 4a | `#E53935` | 점선, 2px, 역방향 | "Relax min_exposure" |
| Loop 4b | `#E53935` | 점선, 2px, 역방향 | "Descendant Expansion" |
| Loop 5 | `#E53935` | 점선, 2px, 외부 연결 | "→ Agent 4 Validator" |

> **STEP 라벨**: 각 박스 좌상단 또는 상단에 회색 (#B0BEC5)으로 "STEP 1", "STEP 2" 표기

---

## 📊 데이터 흐름 요약

```
Circe-be JSON
    │
    ▼
┌─ Parse ─┐
│ target: [40166035, 40239216]     (Liraglutide)
│ compar: [1502809, 1502855, ...]  (DPP-4 inhibitors)
│ outcome: [260139]                (Upper resp infection)
└────┬────┘
     ▼
┌─ SQL Builder ─┐
│ 3 queries:
│   drug_exposure  →  target_cohort, comparator_cohort
│   person         →  demographics (age, gender)
│   condition_occ  →  time-to-event outcome
└────┬──────────┘
     ▼
┌─ OMOP CDM ─┐
│ PostgreSQL (synthea100k schema)
│ ~100K patients, ~2M drug_exposure records
└────┬────────┘
     ▼
┌─ Check & Build ─┐
│ Merge: cohort + demographics + outcome
│ Result: analysis-ready DataFrame
│   person_id | treatment | age | gender_male | time | event
└─────────────┘
```

---

## 🏷️ BILab 로고

우하단에 `⚙ BILab` 로고 배치 (Mapping Agent 다이어그램과 동일 위치)

---

## 💡 그리기 도구별 팁

### Figma
- Auto Layout으로 각 STEP 블록 구성
- DB 실린더: Ellipse + Rectangle 조합
- Loop 화살표: Pen tool로 곡선 점선 그리기

### PowerPoint
- 슬라이드 크기: 33.87cm x 25.4cm (기본)
- 둥근 사각형 → 모서리 반경 8pt
- 의사결정 다이아몬드: 다이아몬드 도형 활용

### draw.io / Excalidraw
- Container 기능으로 Extraction Agent 큰 블록 생성
- Database 도형 (실린더) 사용 가능

### Keynote
- 마스터 슬라이드에서 배경색 설정
- 도형 스타일 복사-붙여넣기로 일관성 유지

---

## 🔄 Mapping Agent 다이어그램과의 연결점

Extraction Agent 다이어그램은 Mapping Agent 다이어그램과 다음 지점에서 연결된다:

```
[Mapping Agent OUTPUT] ─── Circe-be JSON ───▶ [Extraction Agent INPUT]

[Extraction Agent Loop 5] ─── Schema Error ───▶ [Agent 4 Validator]
                                                  (Mapping Agent 내부)
```

> **TIP**: 두 다이어그램을 나란히 배치하거나, 작은 참조 박스로
> Mapping Agent의 OUTPUT을 Extraction Agent INPUT 위에 표시하면
> 전체 파이프라인의 연결이 명확해진다.
