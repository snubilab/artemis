# Mapping Agent — Internal Architecture 다이어그램 가이드

## 🎨 디자인 시스템 (Trial Agent 스타일 기준)

### 색상 팔레트
| 용도 | HEX | 설명 |
|------|-----|------|
| 배경 | `#F5F7FA` | 연한 회색 (캔버스) |
| 메인 섹션 배경 | `#E8F4FD` | 연한 파란색 (Agent 2 등 큰 블록) |
| 서브 섹션 배경 | `#FFFFFF` | 흰색 (내부 컴포넌트) |
| 헤더/타이틀 | `#1A1A2E` | 거의 검정 |
| 강조 텍스트 | `#1565C0` | 진한 파랑 |
| 점선 테두리 | `#90CAF9` | 밝은 파랑 (dashed border) |
| 실선 테두리 | `#1565C0` | 진한 파랑 (solid border) |
| 화살표 | `#37474F` | 진한 회색 |
| DATABASE 아이콘 | `#1565C0` | 파란색 |
| OUTPUT 배경 | `#263238` | 거의 검정 (칩/JSON 블록) |
| STEP 라벨 | `#B0BEC5` | 회색 (STEP 1, STEP 2...) |

### 폰트
- **타이틀**: Bold, 28-32pt (예: Inter, Pretendard, Noto Sans)
- **섹션 헤더**: SemiBold, 16-18pt
- **본문**: Regular, 11-13pt
- **코드/필드명**: Monospace (예: SF Mono, Fira Code), 10-12pt, *이탤릭*

### 아이콘
| 위치 | 아이콘 | 설명 |
|------|-------|------|
| 타이틀 | ⚙️ 톱니바퀴 | "Mapping Agent" 옆 |
| 데이터베이스 | 🛢️ 실린더 | ChromaDB, Neo4j, Registry |
| LLM | 🤖 AI 칩 | Complexity Router, LLM Critic |
| 코드 | `</>` | JSON Parser, Assembler |
| 입력 | 🧠 뇌 | ARTEMISRequest |
| 출력 | 📄 문서 | Circe-be JSON |
| 검증 | ✓ 체크 | Validator |

---

## 📐 레이아웃 (1400 x 1100px 권장)

```
┌────────────────────────────────────────────────────────────────────┐
│  ⚙ Mapping Agent — Internal Architecture                          │
│                                                                    │
│  INPUT                           STEP 2                            │
│  ┌──────────┐                   ┌─────────────────────────────────┐│
│  │ARTEMISReq  │    STEP 1         │   Agent 2 — Intelligent Mapper ││
│  │(IR)      │──▶┌──────────┐──▶│                                 ││
│  └──────────┘   │Criteria  │    │  ┌Pre-processing──────────────┐ ││
│                 │Planner   │    │  │Abbrev│Drug Class│Code Patt │ ││
│                 │(Ag 1.5)  │    │  └──────┴─────────┴──────────┘ ││
│                 └──────────┘    │         ▼                       ││
│                                 │  ┌Complexity Router──────┐     ││
│                                 │  │    SpaCy NLP          │     ││
│                                 │  └───┬──────────────┬────┘     ││
│                                 │ FAST │              │ SLOW     ││
│                                 │  ▼   │              │  ▼       ││
│                                 │ Rule │              │ UMLS     ││
│                                 │ Ext  │              │ Synonym  ││
│                                 │  ▼   │              │  ▼       ││
│                                 │Vector│              │Multi-Q   ││
│                                 │Search│              │Reranker  ││
│                                 │  ▼   │              │  ▼       ││
│                                 │Top-1 │              │Force T-1 ││
│                                 │  └───┴──────┬───────┘          ││
│                                 │             ▼                   ││
│                                 │     Logician (decompose+prune) ││
│                                 │             ▼                   ││
│                                 │  ┌KG-RAG Post-processing────┐  ││
│                                 │  │KG Expander │ LLM Critic  │  ││
│                                 │  │(Neo4j)     │(Multi-sel)  │  ││
│                                 │  └────────────┴─────────────┘  ││
│                                 └────────────┬────────────────────┘│
│                                              ▼                     │
│  STEP 3              STEP 4              STEP 5                    │
│  ┌──────────┐  ──▶  ┌──────────┐  ──▶  ┌──────────────────┐      │
│  │Consolid- │       │Registry  │       │Agent 3 — Cohort  │      │
│  │ator      │       │          │       │Assembler         │      │
│  └──────────┘       └──────────┘       └────────┬─────────┘      │
│                                                  ▼                 │
│                     STEP 6              ┌────────────────┐ OUTPUT  │
│                     ┌──────────┐       │                │  ┌────┐ │
│                     │Agent 4 — │──────▶│ Circe-be JSON  │  │JSON│ │
│                     │Validator │       │                │  └────┘ │
│                     └──────────┘       └────────────────┘         │
│                                                         ⚙ BILab  │
└────────────────────────────────────────────────────────────────────┘
```

---

## 📝 각 박스별 상세 내용

### INPUT (좌상단)
```
┌─ 🧠 ─────────────────────┐
│  INPUT                    │
│  ARTEMISRequest (IR)        │
│                           │
│  t/Comparator/outcome     │
│  inclusion_rules          │
│  exclusion_rules          │
│  measurement_rules        │
└───────────────────────────┘
  ↑ "from Trial Agent" 라벨
```
- 스타일: 흰색 배경, 밝은 파란 테두리, 둥근 모서리 (8px)
- 필드명은 monospace 이탤릭

---

### STEP 1: Criteria Planner (Agent 1.5)
```
┌─ 🧠 ─────────────────────────────────────────┐
│  Criteria Planner (Agent 1.5)                 │
│                                               │
│  Analyzes each criterion, decomposes          │
│  composite terms into sub-criteria            │
│                                               │
│  ┌─ LLM-powered ─────────────────────────┐   │
│  │ "Is it atomic or composite?"           │   │
│  │                                        │   │
│  │ DPP-4 inhibitors →                    │   │
│  │   [Sitagliptin, Saxagliptin,          │   │
│  │    Linagliptin, ...]                   │   │
│  └────────────────────────────────────────┘   │
│                                               │
│  Output: Decomposed IR with                   │
│          sub_criteria and group_type='ANY'     │
└───────────────────────────────────────────────┘
```
- 스타일: `#E8F4FD` 배경, 점선 파란 테두리
- 안쪽 LLM 블록: 흰색 배경, 실선 테두리
- 예시 코드는 monospace

---

### STEP 2: Agent 2 — Intelligent Mapper (중앙, 가장 큰 블록)

이 블록이 다이어그램의 **핵심**. 전체 폭의 ~60%를 차지.

#### 2-1. Pre-processing (상단 가로 줄)
```
┌─ Step 0: Pre-processing ──────────────────────────────────┐
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐ │
│  │ Abbreviation │  │  Drug Class  │  │  Code Pattern    │ │
│  │  Expander    │  │  Expander    │  │  Matcher         │ │
│  └──────────────┘  └──────────────┘  └──────────────────┘ │
└───────────────────────────────────────────────────────────┘
```
- 3개의 흰색 박스를 가로로 배치
- 섹션 배경: `#E8F4FD` 보다 약간 진한 `#DCEEFB`

#### 2-2. Complexity Router (분기점)
```
         ┌─────────────────────────┐
         │  Complexity Router      │
         │  ┌───────┐              │
         │  │ SpaCy │ NLP          │
         │  └───────┘              │
         └─────────┬───────────────┘
              ┌────┴────┐
         FAST PATH   SLOW PATH
```
- SpaCy 아이콘/로고 삽입
- 좌/우 분기 화살표에 "FAST PATH" / "SLOW PATH" 라벨

#### 2-3. FAST PATH (좌측)
```
  ┌──────────────────┐
  │  Rule Extractor  │
  └────────┬─────────┘
           ▼
  ┌──────────────────┐
  │  Vector Search   │
  │  🛢️ (ChromaDB)   │
  └────────┬─────────┘
           ▼
  ┌──────────────────┐
  │  Top-1 Direct    │
  └────────┬─────────┘
           ▼
  ┌──────────────────┐
  │  Logician        │
  │  (decompose+     │
  │   prune)         │
  └──────────────────┘
```

#### 2-4. SLOW PATH (우측)
```
  ┌──────────────────────────┐
  │  UMLS Synonym            │
  │  Expander                │
  └────────┬─────────────────┘
           ▼
  ┌──────────────────────────┐
  │  Multi-query Vector      │
  │  LLM Reranker (Top-3)   │
  └────────┬─────────────────┘
           ▼
  ┌──────────────────────────┐
  │  Force Top-1 inclusion   │
  └────────┬─────────────────┘
           ▼
  ┌──────────────────────────┐
  │  Logician                │
  │  (decompose+prune)       │
  └──────────────────────────┘
```

> **TIP**: FAST/SLOW의 Logician은 같은 모듈이므로, 
> 합류 화살표로 하나의 Logician 박스에 모이게 그리면 더 깔끔합니다.

#### 2-5. KG-RAG Post-processing (하단)
```
┌─ KG-RAG Post-processing (점선 박스) ──────────────────────┐
│                                                            │
│  ┌──────────────────────┐   ┌───────────────────────────┐ │
│  │ 🛢️ KG Expander        │   │ 🤖 LLM Critic             │ │
│  │ (Neo4j)              │   │ (Multi-select)            │ │
│  │                      │   │                           │ │
│  │ Adaptive limits      │   │ Evaluate each expanded    │ │
│  │ per domain:          │   │ concept                   │ │
│  │ Drug:15, Cond:40,    │   │                           │ │
│  │ default:20           │   │                           │ │
│  └──────────────────────┘   └───────────────────────────┘ │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

#### 2-6. Agent 2 Output
- 화살표 아래 라벨: **"List of OMOP Concept IDs"**

---

### STEP 3: Consolidator (좌하단)
```
┌─ ─────────────────────────────────┐
│  Consolidator                     │
│                                   │
│  • Finds Lowest Common Ancestor   │
│    (LCA) in OMOP hierarchy        │
│  • Groups by parent, rule,        │
│    merges concepts                │
│  • includeDescendants=true        │
│                                   │
│  Output: Consolidated             │
│          ConceptSets              │
└───────────────────────────────────┘
```
- 스타일: 흰색 배경, 실선 파란 테두리

---

### STEP 4: Registry (중앙 하단)
```
┌─ 🛢️ ──────────────────────────────┐
│  Registry                         │
│                                   │
│  Registers ConceptSets            │
│  with unique IDs                  │
│                                   │
│  Global ConceptSet store          │
│                                   │
│  Output: registered               │
│          ConceptSets              │
└───────────────────────────────────┘
```
- 스타일: 흰색 배경 + DB 실린더 아이콘

---

### STEP 5: Agent 3 — Cohort Assembler (우하단)
```
┌─ </> ─────────────────────────────────────────┐
│  Agent 3 — Cohort Assembler                   │
│                                               │
│  • Builds Circe-be JSON from IR               │
│    + registered ConceptSets                   │
│  • Components:                                │
│    PrimaryCriteria, InclusionRules,           │
│    ExclusionRules, EndStrategy                │
│  • Domain mappings:                           │
│    Condition → ConditionOccurrence            │
│    Drug → DrugExposure                        │
│  • Handles composite rules,                   │
│    demographic criteria,                      │
│    value constraints                          │
└───────────────────────────────────────────────┘
```
- Circe-be JSON 구조 미리보기 (Trial Agent의 ARTEMISRequest IR처럼):
```json
{
  "ConceptSets": [...],
  "PrimaryCriteria": {
    "CriteriaList": [
      {"ConditionOccurrence": {...}}
    ]
  },
  "InclusionRules": [...]
}
```

---

### STEP 6: Agent 4 — Circe Validator (하단)
```
┌─ ✓ ──────────────────────────────────────────┐
│  Agent 4 — Circe Validator                    │
│                                               │
│  • Schema validation (required fields)        │
│  • ConceptSet reference validation            │
│  • Semantic validation (CodesetId=0 check)    │
│  • Registry integrity check                   │
│                                               │
│  Output: ValidationResult                     │
│          (valid/errors/warnings)               │
└───────────────────────────────────────────────┘
```

---

### OUTPUT (우하단)
```
┌─────────────────────────────────┐
│  ■ JSON                         │  ← 어두운 칩 스타일 (#263238)
│                                 │
│  Circe-be JSON                  │
│  ATLAS-compatible               │
│  cohort definition              │
└─────────────────────────────────┘
```
- Trial Agent의 ARTEMISRequest 출력 블록과 동일한 스타일
- 어두운 배경에 흰색 텍스트

---

## 🔗 화살표 & 연결 규칙

| From | To | 라벨 | 스타일 |
|------|----|------|--------|
| INPUT | STEP 1 | - | 실선, 검은 화살표 |
| STEP 1 | STEP 2 | "Decomposed IR with sub_criteria" | 실선 |
| STEP 2 Pre-proc | Complexity Router | - | 실선 |
| Router | FAST PATH | "FAST PATH" | 실선, 좌측 |
| Router | SLOW PATH | "SLOW PATH" | 실선, 우측 |
| FAST/SLOW | Logician | 합류 | 실선 |
| Logician | KG-RAG | - | 실선 |
| KG-RAG | STEP 3 | "List of OMOP Concept IDs" | 실선 |
| STEP 3 | STEP 4 | "Consolidated ConceptSets" | 실선, 가로 |
| STEP 4 | STEP 5 | "registered ConceptSets" | 실선, 가로 |
| STEP 5 | STEP 6 | "Circe-be JSON structure" | 실선 |
| STEP 6 | OUTPUT | "valid=true" | 실선 |

> **STEP 라벨**: 각 박스 좌상단 또는 상단에 회색 (#B0BEC5)으로 "STEP 1", "STEP 2" 표기

---

## 🏷️ BILab 로고

우하단에 `⚙ BILab` 로고 배치 (Trial Agent와 동일 위치)

---

## 💡 그리기 도구별 팁

### Figma
- Auto Layout으로 각 섹션 구성
- Component로 박스 템플릿 만들어 재활용
- Stroke: Dashed 4,4 (점선 섹션용)

### PowerPoint
- 슬라이드 크기: 33.87cm x 25.4cm (기본)
- 둥근 사각형 → 모서리 반경 8pt
- 그룹화로 STEP 2 내부 관리

### draw.io / Excalidraw
- Container 기능으로 Agent 2 큰 블록 생성
- 내부 요소를 Container 안에 배치

### Keynote
- 마스터 슬라이드에서 배경색 설정
- 도형 스타일 복사-붙여넣기로 일관성 유지
