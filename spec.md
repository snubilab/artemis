# ARTEMIS 3.1: End-to-End Automated Clinical Evidence Generation System

**Technical Specification & Implementation Guide (Final Production Version)**

---

## 1. 시스템 개요 (System Overview)

ARTEMIS 3.1은 자연어로 기술된 임상 질문을 받아 OHDSI 표준 코호트를 생성(Agent 1~4)하고, 인과추론 기반의 통계 분석(Agent 5)과 리포트 생성(Agent 6)까지 자동화하는 **Digital CRO(임상시험수탁기관)** 플랫폼이다.

v3.0의 기반 위에 **지능형 의미 검색(Semantic Intelligence)**과 **데이터 기반 최적화(Data-Driven Optimization)**를 탑재하여, 단순 검색의 한계(중의성 오류, 복합제 누락 등)를 극복하고 분석 결과의 임상적 신뢰도를 극대화한다.

---

## 2. 아키텍처 다이어그램 (v3.1 Enhanced Architecture)

```mermaid
graph TD
    User[User Input / NCT Protocol] --> A1[Agent 1: Logic Decomposer]
    
    subgraph "Cohort Definition Phase (Agent 1-4)"
        A1 -->|IR v3.1| A2[Agent 2: Intelligent Mapper]
        
        subgraph "Agent 2 Internal Logic"
            A2_In[Input Term] --> Check{Is Code Pattern?}
            Check -- Yes (Regex) --> SQL[Direct DB Lookup]
            Check -- No (Text) --> VDB[Vector Search Top-20]
            SQL & VDB --> Candidates
            Candidates --> Rank[LLM Context Reranking]
            Rank --> Best[Best Anchor Concept]
            Best --> Logic{Logic Check}
            Logic -- Combination --> Decomp[Decompose to Ingredients]
            Logic -- Standard --> Expand[Expand Descendants]
            Logic -- Hx/Obs --> Single[Keep Single]
            Decomp & Expand & Single --> Prune[Data-Driven Pruning]
        end
        
        Prune -->|Valid Concept Sets| REG[Global Registry]
        REG --> A3[Agent 3: Assembler]
        A3 -->|Circe JSON| A4[Agent 4: Validator]
        A4 -->|Execute SQL| DB[(MIMIC-IV / CDM)]
    end
    
    subgraph "Evidence Generation Phase (Agent 5-6)"
        DB -->|T/C Cohort + Outcome Cohort| A5[Agent 5: Analysis Agent]
        A5 -->|1. Large-Scale Covariates| FE[Auto Feature Extraction]
        A5 -->|2. Propensity Score| PSM[PSM / IPTW Engine]
        PSM -->|3. Outcome Model| COX[Cox / KM Analysis]
        
        COX -->|Stats Results| A6[Agent 6: Reporting Agent]
        User -.->|Gold Standard (RCT Results)| A6
        A6 -->|Visualizer| PLOT[Forest Plot / KM Curve]
        A6 -->|Narrative Gen| RPT[Final Clinical Report]
    end
```

---

## 3. 모듈별 상세 설계 (Component Details)

### Module 1. Logic Decomposer (Agent 1)

**역할**: 자연어 기준을 분석하여 코호트 진입/종료 시점과 포함/제외 기준의 논리적 성격을 정의.

#### v3.1 핵심 기능

| 기능 | 설명 |
|------|------|
| **Primary Limit** | 코호트 진입을 '최초(First)'로 할지 '전체(All)'로 할지 명시 |
| **Exit Strategy** | 관찰 종료 시점 정의 (Default: Observation Period End) |
| **Negation Duality** | '개념 자체의 제외(Exclude Concept)'와 '사건의 부재(Absence of Event)' 구분 |
| **Outcome Definition** | 분석을 위한 결과 변수(Outcome Cohort) 및 Time-at-Risk 정의 |

#### 최종 IR 스키마 (v3.1 Schema)

```json
{
  "cohorts": {
    "target": {
      "primary_criteria": {
        "domain": "Condition",
        "entity_key": "T2DM",
        "limit": "First",
        "observation_window": { "prior": 365, "post": 0 }
      },
      "inclusion_rules": [
        {
          "name": "No Metformin Use",
          "domain": "Drug",
          "entity_key": "Metformin",
          "logic_type": "ABSENCE",
          "window": { "start": -30, "end": 0 }
        },
        {
          "name": "HbA1c > 6.5%",
          "domain": "Measurement",
          "entity_key": "HbA1c",
          "value_constraint": {
            "op": "gt",
            "value": 6.5,
            "unit_text": "%"
          }
        }
      ],
      "exit_strategy": "OBSERVATION_END"
    },
    "comparator": { /* ... Structure same as target ... */ },
    "outcome": {
      "name": "All-cause Mortality",
      "domain": "Condition",
      "entity_key": "Death",
      "time_at_risk": { "start": 0, "end": 365 }
    }
  },
  "analysis_settings": {
    "adjustment_strategy": "PSM",
    "covariate_window": { "prior": 365, "post": 0 }
  }
}
```

---

### Module 2. Semantic Mapper (Agent 2) - The Intelligence Core

**역할**: 텍스트/코드를 OMOP Concept ID로 변환. 문맥 인지(Context-Aware) 및 도메인 규칙(Domain Rules) 적용 후 Registry에 등록.

#### 핵심 로직 (3-Step Intelligence)

##### Step 2-1: Hybrid Search (Code + Text)

- **Regex Pre-processor**: 입력값 패턴 감지
  - Matches `[A-Z]\d{2,}` (예: `I21.9`) → Direct DB Lookup (Vector Search Skip)
  - Else → Vector Search (Top-20 Candidates 추출)

##### Step 2-2: Context-Aware Reranking (LLM Judge)

- **문제**: "Depression" (우울증 vs ST분절 하강)
- **해결**: LLM에게 사용자 문맥(Context)과 후보 리스트를 제공하여 최적의 하나를 선택

```
Prompt: "User context is 'Cardiovascular risk'. 
Candidates are [1. Major Depressive Disorder, 2. ST segment depression]. 
Select the ID that fits the context best."
```

##### Step 2-3: Intelligent Logic & Pruning

| 로직 | 설명 |
|------|------|
| **Decomposition** | Concept Class = 'Combination Drug' 감지 시, CONCEPT_ANCESTOR를 역추적하여 구성 성분(Ingredient) ID들로 자동 분해 |
| **Domain Rules** | "Family History" 키워드 감지 시, Descendant 확장 차단 (Single Concept 유지) |
| **Data-Driven Pruning** | Registry 등록 전, `SELECT 1 FROM data_table WHERE concept_id IN (...) LIMIT 1` 쿼리를 수행하여 실제 데이터가 존재하는 ID만 남기고 가지치기 |

##### Step 2-4: Global Registry Registration

- **Dedup**: 정제된 ID 리스트를 Hashing하여 고유 ID 생성. 중복된 ConceptSet 생성을 방지.

---

### Module 3. Cohort Assembler (Agent 3)

**역할**: 정제된 ConceptSet(Registry)과 IR을 결합하여 Circe-be JSON 조립.

#### 핵심 기능

| 기능 | 설명 |
|------|------|
| **Static Attribute Map** | 성별, 인종 등 정적 속성 하드코딩 매핑 (속도 최적화) |
| **Negation Handling** | ABSENCE 타입 → Circe Criteria Occurrence Count: 0<br>Exclude Flag → ConceptSet Expression isExcluded: true |
| **Measurement Template** | Pydantic 모델을 사용하여 ValueAsNumber, Operator, UnitConceptId 필드를 정확히 조립 |

```json
{"MALE": 8507, "LT": "lt", "GT": "gt"}
```

---

### Module 4. Validator (Agent 4)

**역할**: JSON 문법 검사 및 OHDSI 호환성 확인.

#### 기능

| 검사 항목 | 설명 |
|-----------|------|
| **Registry Integrity Check** | JSON 본문의 ConceptSet ID 참조 무결성 확인 |
| **Limit/Exit Check** | 필수 필드(Primary Limit 등) 누락 여부 검사 |
| **Dry Run** | OHDSI WebAPI(또는 R 패키지)를 통해 SQL 생성 시뮬레이션. SQL 생성 실패 시 에러 로그를 분석하여 Feedback Loop 가동 |

---

### Module 5. Analysis Agent (The Statistician)

**역할**: Target, Comparator, Outcome 코호트를 기반으로 인과추론 수행.

#### v3.1 핵심 업그레이드

##### Feature 1: Automated Large-Scale Covariate Extraction (HDPS)

- **Action**: OHDSI FeatureExtraction 로직 구현. Index Date 이전 365일 내의 **모든 진단명(Condition Group)**과 **모든 약물(Drug Group)**을 Binary Feature로 자동 추출
- **효과**: 수천 개의 변수를 사용하여 잠재적 교란변수(Confounder)를 강력하게 통제

##### Feature 2: Outcome Cohort Integration

- **Process**: Target/Comparator 환자 중 Outcome Cohort에 속하는 자(Event)와 시점(Time-to-Event) 식별
- Time-at-Risk 윈도우 내 발생만 유효 사건으로 간주

##### Feature 3: Causal Modeling

- **Method**: 대규모 공변량을 이용한 PSM(Propensity Score Matching) 또는 IPTW
- **Model**: Cox Proportional Hazards Model (Survival Analysis)

---

### Module 6. Reporting Agent (The Medical Writer)

**역할**: 통계 분석 결과와 문헌 정보를 통합하여 시각화 및 리포트 생성.

#### 기능

| 기능 | 설명 |
|------|------|
| **Visualization** | Forest Plot(HR 시각화), KM Curve(생존곡선), Love Plot(SMD 밸런스 점검) |
| **Comparative Validation** | 시뮬레이션 결과(Simulated HR)와 원본 RCT 결과(Published HR)를 비교하여 통계적 일치 여부 해석 |
| **Report Gen** | WeasyPrint를 이용한 PDF 리포트 산출 |

---

## 4. 확장된 기술 스택 (Full Tech Stack)

| 구분 | 기술/도구 | 비고 |
|------|-----------|------|
| **Orchestration** | LangGraph | Multi-Agent 상태 관리 및 순환 루프 |
| **Global State** | Redis | Concept Registry 및 캐싱 |
| **Search Intelligence** | Regex + BioLinkBERT + LLM Judge | Hybrid Search & Reranking |
| **Data Optimization** | SQL Pruning | 실제 데이터 존재 여부 확인 (속도 최적화) |
| **Semantic DB** | ChromaDB | 의료 용어 및 단위 임베딩 |
| **CDM DB** | PostgreSQL (MIMIC-IV) | OMOP CDM 및 Raw Data |
| **Code Generation** | Pydantic + Jinja2 | Circe JSON 및 리포트 템플릿 생성 |
| **Analysis** | Python lifelines, sklearn, causalml | Cox, PSM, Large-scale Feature Eng. |
| **Visualization** | matplotlib, seaborn | Publication-quality Plots |
| **Reporting** | WeasyPrint | PDF Report Generation |

---

## 5. 개발 로드맵 (Final Roadmap)

### Phase 1: Semantic Intelligence 구축 (W1-W3)

- **Hybrid Search**: Regex 패턴 매칭 및 Direct Lookup 로직 구현
- **Reranking**: LLM Context Judge 프롬프트 및 파이프라인 구축
- **Logic Layer**: 복합제 분해(Decomposition) 및 Pruning SQL 쿼리 최적화

### Phase 2: Assembler & Registry 통합 (W4-W6)

- **Registry**: 전역 Concept ID 관리 및 상태 공유 시스템 구현
- **Assembler**: v3.1 IR 스키마(Outcome 포함)에 맞춘 Jinja2 템플릿 고도화
- **Integration**: Agent 1 → 2 → 3 데이터 흐름 연결

### Phase 3: Analysis Engine 고도화 (W7-W10)

- **Feature Extraction**: SQL 기반 대규모 공변량(Drug/Condition Groups) 자동 추출 모듈 개발
- **Outcome Processing**: Time-at-Risk 윈도우 적용 및 Censoring 로직 구현
- **Causal Pipeline**: PSM → Matching → Balance Check → Cox 모델링 자동화

### Phase 4: Reporting & Validation (W11-W13)

- **Visualization**: KM Plot, Love Plot 자동 생성 함수 구현
- **Full Test**: MIMIC-IV 데이터셋 대상 End-to-End(질문~리포트) 시나리오 검증
- **Optimization**: 전체 파이프라인 Latency 최적화

---

## 6. 핵심 성공 지표 (KPIs)

| 지표 | 설명 | 목표 |
|------|------|------|
| **Semantic Precision** | LLM Reranking 도입 후 단어 중의성 해결 비율 | > 95% |
| **Mapping Completeness** | 복합제 입력 시 구성 성분이 모두 ConceptSet에 포함되는가? | 100% |
| **JSON Validity** | 생성된 JSON이 Atlas에서 경고 없이 로딩되며 SQL로 변환되는가? | > 98% |
| **Confounder Control** | 대규모 공변량 적용 후 SMD < 0.1 달성 비율 | > 90% |
| **Evidence Reliability** | 생성된 결과(HR)가 기존 문헌과 통계적 유의성 내에서 일치하는가? | - |
ㄴ