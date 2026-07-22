# Trial Agent — Internal Architecture 다이어그램 가이드

## 🎨 디자인 시스템 (확정 스타일)

### 색상 팔레트
| 용도 | HEX | 설명 |
|------|-----|------|
| 캔버스 배경 | `#F5F7FA` | 연한 회색 |
| 메인 섹션 배경 | `#E8F4FD` | 연한 파란색 (Agent 등 큰 블록) |
| 서브 섹션 배경 | `#DCEEFB` | 약간 진한 연파랑 (그룹 블록) |
| 내부 컴포넌트 배경 | `#FFFFFF` | 흰색 (개별 박스) |
| 헤더/타이틀 텍스트 | `#1A1A2E` | 거의 검정 |
| 강조 텍스트 | `#1565C0` | 진한 파랑 (이름, 키워드) |
| 점선 테두리 | `#90CAF9` | 밝은 파랑 (dashed border, 큰 섹션 감싸기) |
| 실선 테두리 | `#1565C0` | 진한 파랑 (solid border, 개별 박스) |
| 화살표 | `#37474F` | 진한 회색 |
| DATABASE 아이콘 | `#1565C0` | 파란색 |
| OUTPUT 배경 | `#263238` | 어두운 칩 스타일 (최종 출력 블록, 흰색 텍스트) |
| STEP 라벨 | `#B0BEC5` | 회색 (STEP 1, STEP 2...) |

### 폰트
- **타이틀**: Bold, 28-32pt (Inter, Pretendard, 또는 Noto Sans KR)
- **섹션 헤더**: SemiBold, 16-18pt
- **본문**: Regular, 11-13pt
- **코드/필드명**: Monospace (SF Mono, Fira Code), 10-12pt, *이탤릭*

### 아이콘
| 위치 | 아이콘 | 설명 |
|------|-------|------|
| 타이틀 | ⚙️ 톱니바퀴 | "Trial Agent" 옆 |
| 데이터베이스 | 🛢️ 실린더 | NCT 캐시, PubMed |
| LLM/AI | 🤖 AI 칩 | LogicDecomposer (LLM 파서) |
| 코드 | `</>` | JSON 파서, IR 빌더 |
| 입력 | 🧠 뇌 | NCT ID 또는 자연어 쿼리 |
| 출력 | 📄 문서 | ARTEMISRequest (IR) |
| 외부 API | 🌐 글로브 | ClinicalTrials.gov, PubMed |
| 검색 | 🔍 돋보기 | PubMed Linker (esearch) |

### 박스 스타일
- **모서리 반경**: 8px
- **메인 섹션**: `#E8F4FD` 배경, `#90CAF9` 점선 테두리 (dash: 4,4)
- **내부 컴포넌트**: `#FFFFFF` 배경, `#1565C0` 실선 테두리
- **서브 그룹**: `#DCEEFB` 배경, `#90CAF9` 점선 테두리
- **OUTPUT 블록**: `#263238` 배경, 흰색 텍스트, 실선 테두리
- **그림자**: 없음 (flat design)

### 화살표 스타일
- **색상**: `#37474F`
- **굵기**: 2px
- **머리**: filled triangle (▶ 스타일)
- **데이터 흐름**: 실선
- **선택적 흐름**: 점선 (있는 경우)

---

## 📐 레이아웃 (1400 x 1000px 권장)

```
┌──────────────────────────────────────────────────────────────────────────┐
│  ⚙ Trial Agent (Agent 1) — Internal Architecture                        │
│                                                                          │
│  INPUT ─── Input Router ────────────────────────────────────            │
│  ┌─────────────┐  ┌─────────────────────────────────────────────────┐   │
│  │ NCT ID      │  │ Free-text                                       │   │
│  │ or JSON path│  │ Clinical Query                                  │   │
│  └──────┬──────┘  └──────────────────────┬──────────────────────────┘   │
│    NCT  │                           TEXT │                               │
│         ▼                                ▼                               │
│  STEP 1                           STEP 1'                               │
│  ┌──────────────────────┐        ┌──────────────────────┐              │
│  │ 🌐 NCT Fetcher       │        │ 🤖 LLM Parser        │              │
│  │ (ClinicalTrials.gov) │        │ (DECOMPOSITION_      │              │
│  │ + Local JSON Cache   │        │  PROMPT)              │              │
│  └──────────┬───────────┘        └──────────┬───────────┘              │
│             ▼                                │                           │
│  STEP 2                                      │                           │
│  ┌──────────────────────────────────────┐    │                           │
│  │ 📚 PubMed Enrichment                 │    │                           │
│  │ ┌────────────┐ ┌────────────┐       │    │                           │
│  │ │ PubMed     │ │ PubMed     │       │    │                           │
│  │ │ Linker     │→│ Fetcher    │       │    │                           │
│  │ │ (PMID검색) │ │(Abstract)  │       │    │                           │
│  │ └────────────┘ └─────┬──────┘       │    │                           │
│  │                      ▼              │    │                           │
│  │              ┌──────────────┐       │    │                           │
│  │              │  Enricher    │       │    │                           │
│  │              │ replace|merge│       │    │                           │
│  │              └──────────────┘       │    │                           │
│  └──────────────────┬───────────────────┘    │                           │
│                     ▼                        │                           │
│  STEP 3                                      │                           │
│  ┌──────────────────────────────────────┐    │                           │
│  │ 🤖 LLM Decomposition                 │    │                           │
│  │ NCT_DECOMPOSITION_PROMPT             │◀───┘                           │
│  │ SystemMessage + HumanMessage         │ (합류)                         │
│  │ → LLM.invoke()                       │                                │
│  └──────────────────┬───────────────────┘                                │
│                     ▼                                                    │
│  STEP 4                                                                  │
│  ┌──────────────────────────────────────┐                                │
│  │ </> IR Builder                        │                                │
│  │ _extract_json() → _build_artemis_req() │                                │
│  │ _build_cohort_definition()           │                                │
│  │ _build_criteria()                    │                                │
│  │ _validate_measurement_rules()        │                                │
│  └──────────────────┬───────────────────┘                                │
│                     ▼                                                    │
│            ┌────────────────────┐  OUTPUT                                │
│            │ ■ ARTEMISRequest(IR) │                                        │
│            │  target / comparator│                                        │
│            │  outcome            │                                        │
│            └────────────────────┘                                        │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 📝 각 박스별 상세 내용

### INPUT — Input Router (좌상단)

두 가지 입력 모드를 지원. 런타임에 하나를 선택.

#### INPUT-A: NCT Protocol Input
```
┌─ 🧠 ─────────────────────────┐
│  INPUT (NCT Mode)             │
│                               │
│  nct_id: "NCT01730534"        │
│  json_path: (optional)        │
│  enrich_from_pubmed: True     │
│                               │
│  → parse_nct() 호출           │
└───────────────────────────────┘
```
- 스타일: 흰색 배경, 밝은 파란 테두리, 둥근 모서리 (8px)
- 필드명은 monospace 이탤릭

#### INPUT-B: Free-text Query Input
```
┌─ 🧠 ─────────────────────────┐
│  INPUT (Text Mode)            │
│                               │
│  query: "Compare liraglutide  │
│   vs DPP-4 inhibitors in      │
│   T2DM patients with HbA1c   │
│   7-10%..."                   │
│                               │
│  → parse() 호출               │
└───────────────────────────────┘
```
- 동일 스타일
- 자연어 쿼리 전체가 입력

---

### STEP 1: NCT Fetcher — Data Acquisition (NCT 경로)
```
┌─ 🌐 ─────────────────────────────────────────────┐
│  NCT Fetcher (nct_fetcher.py)                     │
│                                                    │
│  ClinicalTrials.gov API v2                        │
│  + Local JSON Cache (data/nct_cache/)             │
│                                                    │
│  ┌─ fetch_or_load_trial_data() ──────────────┐   │
│  │ 1. Check cache: data/nct_cache/{nct_id}.json│   │
│  │ 2. If miss → fetch from API (timeout: 30s) │   │
│  │ 3. _parse_protocol_to_trial_data()         │   │
│  │ 4. _parse_criteria_text()                  │   │
│  │    → split "Inclusion/Exclusion Criteria:"  │   │
│  └─────────────────────────────────────────────┘   │
│                                                    │
│  Output: TrialData (Pydantic)                     │
│  (nct_id, title, conditions, interventions,       │
│   inclusion_criteria, exclusion_criteria,          │
│   primary_outcomes, study_type, phase)             │
└────────────────────────────────────────────────────┘
```
- 스타일: `#E8F4FD` 배경, 점선 파란 테두리
- 🌐 글로브 아이콘 (외부 API)
- 내부 함수 호출 블록: `#FFFFFF` 배경, 실선 테두리

### STEP 1': LLM Parser — Direct Text Mode (TEXT 경로)

자연어 쿼리는 NCT Fetcher를 건너뛰고 바로 LLM으로 진입.

```
┌─ 🤖 ─────────────────────────────────────────────┐
│  LLM Parser (Free-text Mode)                      │
│                                                    │
│  SYSTEM_PROMPT + DECOMPOSITION_PROMPT             │
│  → LLM.invoke(messages)                           │
│                                                    │
│  Prompt includes:                                  │
│  • OMOP domain reference                          │
│  • Clinical Criteria Patterns (A-D)               │
│  • One-shot HbA1c example                         │
│  • JSON schema for ARTEMIS IR                       │
│                                                    │
│  Output: raw JSON string                          │
│  → STEP 4 (IR Builder)로 직접 연결               │
└────────────────────────────────────────────────────┘
```
- 스타일: `#E8F4FD` 배경, 점선 테두리
- 🤖 AI 칩 아이콘

---

### STEP 2: PubMed Enrichment (NCT 경로 전용)

이 블록은 **NCT 모드 전용**. 3개 서브 컴포넌트로 구성.

#### 2-1. PubMed Linker (좌측)
```
┌─ 🔍 ─────────────────────────┐
│  PubMed Linker                │
│  (pubmed_linker.py)           │
│                               │
│  Strategy 1:                  │
│  extract_pmids_from_nct()     │
│  → NCT referencesModule      │
│                               │
│  Strategy 2 (fallback):       │
│  search_pubmed_for_nct()      │
│  → E-utilities esearch        │
│                               │
│  get_design_paper_pmids()     │
│  → BACKGROUND papers first   │
│                               │
│  Output: List[PMID]           │
└───────────────────────────────┘
```
- 스타일: 흰색 배경, 실선 테두리
- 🔍 돋보기 아이콘

#### 2-2. PubMed Fetcher (중앙)
```
┌─ 🌐 ─────────────────────────┐
│  PubMed Fetcher               │
│  (pubmed_fetcher.py)          │
│                               │
│  fetch_pubmed_abstract()      │
│  → E-utilities efetch (XML)   │
│  → parse <ArticleTitle> +     │
│    <AbstractText>              │
│                               │
│  extract_eligibility_         │
│  from_text()                  │
│  → Regex heuristic parsing    │
│  → inclusion/exclusion split  │
│                               │
│  Output: Dict{inclusion,      │
│          exclusion}           │
└───────────────────────────────┘
```
- 스타일: 흰색 배경, 실선 테두리
- 🌐 글로브 아이콘

#### 2-3. Enricher (우측)
```
┌─ </> ─────────────────────────┐
│  Enricher                     │
│  (enricher.py)                │
│                               │
│  enrich_trial_data()          │
│  strategy:                    │
│                               │
│  "replace" (default):         │
│   → _pick_richer()            │
│   → 더 많은 쪽 사용          │
│                               │
│  "merge":                     │
│   → _merge_criteria()         │
│   → SequenceMatcher 중복제거 │
│   → similarity ≥ 0.7 = dup   │
│                               │
│  Output: Enriched TrialData   │
└───────────────────────────────┘
```
- 스타일: 흰색 배경, 실선 테두리
- `</>` 코드 아이콘

> **TIP**: 2-1 → 2-2 → 2-3 가로로 배치하고, 전체를 `#DCEEFB` 점선 블록으로 감싸면 그룹이 명확합니다.
> 연결: PubMed Linker →("PMIDs")→ PubMed Fetcher →("criteria Dict")→ Enricher

---

### STEP 3: LLM Decomposition (중앙)
```
┌─ 🤖 ─────────────────────────────────────────────┐
│  LLM Decomposition (LogicDecomposer)              │
│                                                    │
│  NCT_SYSTEM_PROMPT (C2Q-informed)                 │
│  + NCT_DECOMPOSITION_PROMPT                       │
│                                                    │
│  ┌─ Prompt Template ─────────────────────────┐   │
│  │ title, conditions, interventions,          │   │
│  │ outcomes, inclusion_criteria,              │   │
│  │ exclusion_criteria                         │   │
│  │ + One-shot HbA1c example                   │   │
│  │ + OMOP domain reference                    │   │
│  │ + Clinical Criteria Patterns (A-D):        │   │
│  │   A: Lab range → split TWO rules           │   │
│  │   B: Simple threshold → single rule        │   │
│  │   C: "No prior X" → ABSENCE                │   │
│  │   D: "History of X" → PRESENCE, all prior  │   │
│  └────────────────────────────────────────────┘   │
│                                                    │
│  → SystemMessage + HumanMessage                   │
│  → self.llm.invoke(messages)                      │
│                                                    │
│  Output: raw JSON string (LLM response)           │
└────────────────────────────────────────────────────┘
```
- 스타일: `#E8F4FD` 배경, 점선 파란 테두리
- 🤖 AI 칩 아이콘
- Prompt Template 세부: `#FFFFFF` 배경, 실선 테두리
- 패턴 A-D 텍스트는 Regular 11pt

---

### STEP 4: IR Builder (하단)
```
┌─ </> ─────────────────────────────────────────────┐
│  IR Builder                                        │
│                                                    │
│  ┌─ Parse Pipeline ──────────────────────────┐   │
│  │ 1. _extract_json(response.content)        │   │
│  │    → JSON 블록 추출 + validation          │   │
│  │                                            │   │
│  │ 2. _build_artemis_request(data)             │   │
│  │    → target + comparator + outcome         │   │
│  │                                            │   │
│  │ 3. _build_cohort_definition(data)         │   │
│  │    → PrimaryCriteria + inclusion/exclusion │   │
│  │    → ExitStrategy parsing                  │   │
│  │                                            │   │
│  │ 4. _build_criteria(data)                  │   │
│  │    → domain, entity_text, logic_type       │   │
│  │    → window, value_constraint              │   │
│  │    → sub_criteria + group_type (composite) │   │
│  │                                            │   │
│  │ 5. _validate_measurement_rules()          │   │
│  │    → Measurement에 value_constraint 필수  │   │
│  │      (C2Q 3.0 inspired)                    │   │
│  └────────────────────────────────────────────┘   │
│                                                    │
│  Output: ARTEMISRequest                             │
└────────────────────────────────────────────────────┘
```
- 스타일: 흰색 배경, 실선 파란 테두리
- `</>` 코드 아이콘
- Parse Pipeline 내부: `#DCEEFB` 배경

---

### OUTPUT (하단)
```
┌─────────────────────────────────────┐
│  ■ ARTEMISRequest (IR)                │  ← 어두운 칩 스타일 (#263238)
│                                     │
│  target: CohortDefinition           │
│    primary_criteria:                │
│      domain, entity_text, limit     │
│    inclusion_rules: [Criteria...]   │
│    exclusion_rules: [Criteria...]   │
│    exit_strategy: ExitStrategy      │
│                                     │
│  comparator: CohortDefinition       │
│    (same structure)                 │
│                                     │
│  outcome: CohortOutcome             │
│    name, domain, entity_text        │
│    time_at_risk: {start, end}       │
└─────────────────────────────────────┘
```
- 어두운 배경(`#263238`)에 흰색 텍스트
- Mapping Agent (Agent 2)로 전달됨을 화살표 라벨로 표기

---

## 🔗 화살표 & 연결 규칙

| From | To | 라벨 | 스타일 |
|------|----|------|--------|
| INPUT (NCT) | STEP 1 | "nct_id" | 실선, `#37474F` 화살표 |
| INPUT (Text) | STEP 1' | "query" | 실선 |
| STEP 1 | STEP 2 | "TrialData" | 실선 |
| STEP 2 Linker | STEP 2 Fetcher | "PMIDs" | 실선, 가로 |
| STEP 2 Fetcher | STEP 2 Enricher | "criteria Dict" | 실선, 가로 |
| STEP 2 | STEP 3 | "Enriched TrialData" | 실선 |
| STEP 1' | STEP 3 | 합류 (raw JSON) | 점선 (STEP 3에서 합류) |
| STEP 3 | STEP 4 | "raw JSON string" | 실선 |
| STEP 4 | OUTPUT | "ARTEMISRequest" | 실선 |
| OUTPUT | Agent 2 | "to Mapping Agent" | 점선 (외부 연결) |

> **STEP 라벨**: 각 박스 좌상단 또는 상단에 회색 (`#B0BEC5`)으로 "STEP 1", "STEP 2" 표기

> **NOTE**: Text 모드에서는 STEP 1/2를 건너뛰고 LLM Parser(STEP 1')가 직접 JSON을 출력하여 STEP 4로 연결됩니다. 이를 점선 화살표로 표현.

---

## 📦 데이터 구조 미리보기

### TrialData (NCT Fetcher Output — Pydantic)
```python
class TrialData(BaseModel):
    nct_id: str
    title: str = ""
    conditions: List[str] = []
    interventions: List[str] = []
    inclusion_criteria: List[str] = []
    exclusion_criteria: List[str] = []
    primary_outcomes: List[str] = []
    study_type: str = ""
    phase: str = ""
```

### ARTEMISRequest (최종 출력 — Pydantic)
```python
class ARTEMISRequest(BaseModel):
    target: CohortDefinition
    comparator: CohortDefinition
    outcome: CohortOutcome
    concept_sets: List[ConceptSet] = []

class CohortDefinition(BaseModel):
    primary_criteria: PrimaryCriteria
    inclusion_rules: List[Criteria] = []
    exclusion_rules: List[Criteria] = []
    exit_strategy: Union[str, ExitStrategy] = "OBSERVATION_END"

class Criteria(BaseModel):
    name: str
    domain: str  # Condition, Drug, Measurement, ...
    entity_text: Optional[str] = None
    concept_set_id: Optional[int] = None
    logic_type: Literal["PRESENCE", "ABSENCE"] = "PRESENCE"
    window: Optional[TemporalWindow] = None
    value_constraint: Optional[ValueConstraint] = None
    sub_criteria: List["Criteria"] = []
    group_type: Literal["ALL", "ANY"] = "ALL"
```

### PubMed 관련 모델
```python
@dataclass
class PubMedPaper:
    pmid: str
    title: str = ""
    abstract: str = ""

# extract_eligibility_from_text() 출력:
{
    "inclusion": ["criterion 1", "criterion 2", ...],
    "exclusion": ["criterion 1", ...]
}
```

---

## 💡 그리기 도구별 팁

### Figma
- Auto Layout으로 각 섹션 구성
- Component로 박스 템플릿 만들어 재활용
- Stroke: Dashed 4,4 (점선 섹션용)
- Fill 색상에 위 팔레트 HEX 직접 입력

### PowerPoint
- 슬라이드 크기: 33.87cm x 25.4cm (기본)
- 둥근 사각형 → 모서리 반경 8pt
- 그룹화로 복잡한 서브 블록 관리
- 도형 서식 → 선 → 대시 유형으로 점선 설정

### draw.io / Excalidraw
- Container 기능으로 큰 블록 생성
- 내부 요소를 Container 안에 배치
- Style 탭에서 dashed=1;dashPattern=4 4 설정

### Keynote
- 마스터 슬라이드에서 배경색 #F5F7FA 설정
- 도형 스타일 복사-붙여넣기로 일관성 유지
- 도형 > 테두리 > 파선으로 점선 설정
