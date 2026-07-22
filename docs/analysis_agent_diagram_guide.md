# Analysis Agent — Internal Architecture 다이어그램 가이드

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
| 타이틀 | ⚙️ 톱니바퀴 | "Analysis Agent" 옆 |
| 데이터베이스 | 🛢️ 실린더 | PostgreSQL (OMOP CDM) |
| LLM/AI | 🤖 AI 칩 | 해당 없음 (통계 기반) |
| 코드 | `</>`  | FeatureExtractor, SQL Generator |
| 입력 | 📥 데이터 | Cohort Definition + OMOP CDM |
| 출력 | 📊 차트 | HR, CI, KM Curves |
| 검증 | ✓ 체크 | Balance Checker (SMD) |
| 통계 모델 | 📈 그래프 | PropensityScore, CoxModel, KM |

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
- **피드백/에러 흐름**: 점선 (있는 경우)

---

## 📐 레이아웃 (1400 x 1100px 권장)

```
┌──────────────────────────────────────────────────────────────────────┐
│  ⚙ Analysis Agent (Agent 5) — Internal Architecture                 │
│                                                                      │
│  INPUT                                                               │
│  ┌──────────────┐     STEP 1                                        │
│  │ Cohort Def   │    ┌──────────────────────────────────────────┐   │
│  │ + OMOP CDM   │──▶│  Data Extraction (OMOPConnector)         │   │
│  │              │    │  🛢️ PostgreSQL                            │   │
│  └──────────────┘    └───────────────────┬──────────────────────┘   │
│                                          ▼                           │
│                      STEP 2                                          │
│                      ┌──────────────────────────────────────────┐   │
│                      │  Feature Extraction (HDPS)               │   │
│                      │  ┌COVARIATE_GROUPS──────────────────────┐│   │
│                      │  │Condition│Drug│Procedure│Demographics ││   │
│                      │  └─────────┴────┴─────────┴────────────┘│   │
│                      └───────────────────┬──────────────────────┘   │
│                                          ▼                           │
│                      STEP 3                                          │
│                      ┌──────────────────────────────────────────┐   │
│                      │  Propensity Score Model                  │   │
│                      │  📈 LogisticRegression (sklearn)         │   │
│                      └───────────────────┬──────────────────────┘   │
│                                          ▼                           │
│                      STEP 4 ─── Method Router ──────────────        │
│                      ┌──────────────┬───────────────────────┐       │
│                 IPTW │              │ PSM                    │       │
│                      ▼              ▼                        │       │
│              ┌──────────────┐ ┌──────────────────┐          │       │
│              │ IPTW Weights │ │  PS Matching     │          │       │
│              │ (stabilized) │ │ (Nearest-Neighbor│          │       │
│              │ trim @99%ile │ │  caliper=0.2)    │          │       │
│              └──────┬───────┘ └────────┬─────────┘          │       │
│                     └──────────┬───────┘                    │       │
│                                ▼                             │       │
│                      STEP 5                                          │
│                      ┌──────────────────────────────────────────┐   │
│                      │  ✓ Balance Check (SMD)                   │   │
│                      │  before vs after adjustment               │   │
│                      │  threshold: 0.1                           │   │
│                      └───────────────────┬──────────────────────┘   │
│                                          ▼                           │
│                      STEP 6                                          │
│                      ┌──────────────────────────────────────────┐   │
│                      │  Outcome Modeling                        │   │
│                      │  ┌──────────────┐  ┌─────────────────┐  │   │
│                      │  │ Cox PH Model │  │ KM Analysis     │  │   │
│                      │  │ (lifelines)  │  │ + Log-rank Test │  │   │
│                      │  └──────────────┘  └─────────────────┘  │   │
│                      └───────────────────┬──────────────────────┘   │
│                                          ▼                           │
│                                 ┌────────────────────┐  OUTPUT      │
│                                 │ ■ AnalysisResult   │              │
│                                 │   HR, CI, p-value  │              │
│                                 │   KM Curves        │              │
│                                 │   Balance Table    │              │
│                                 └────────────────────┘              │
│                                                          ⚙ BILab    │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 📝 각 박스별 상세 내용

### INPUT (좌상단)
```
┌─ 📥 ─────────────────────────┐
│  INPUT                        │
│  Cohort Definition + OMOP CDM │
│                               │
│  target_cohort_id             │
│  comparator_cohort_id         │
│  outcome_concept_ids          │
│  outcome_window_days          │
│  analysis_method: "IPTW"|"PSM"│
└───────────────────────────────┘
  ↑ "from Extraction Agent" 라벨
```
- 스타일: 흰색 배경, 밝은 파란 테두리, 둥근 모서리 (8px)
- 필드명은 monospace 이탤릭
- `AnalysisConfig` 데이터클래스 필드가 표시됨

---

### STEP 1: Data Extraction — OMOPConnector (상단)
```
┌─ 🛢️ ─────────────────────────────────────────────┐
│  Data Extraction (OMOPConnector)                   │
│                                                    │
│  Connects to PostgreSQL OMOP CDM via SQLAlchemy    │
│  Schema: synthea100k                               │
│                                                    │
│  ┌─ Query Pipeline ──────────────────────────┐    │
│  │ 1. extract_drug_cohort(drug_concept_ids)   │    │
│  │ 2. extract_demographics(person_ids)        │    │
│  │ 3. extract_conditions(person_ids, 365d)    │    │
│  │ 4. extract_outcome(person_ids, index_dates)│    │
│  │ 5. build_analysis_dataset() → merge all    │    │
│  └────────────────────────────────────────────┘    │
│                                                    │
│  Output: pd.DataFrame                              │
│  (person_id, treatment, covariates, time, event)   │
└────────────────────────────────────────────────────┘
```
- 스타일: `#E8F4FD` 배경, 점선 파란 테두리
- 안쪽 Query Pipeline 블록: `#FFFFFF` 배경, 실선 테두리
- DB 실린더 아이콘 (🛢️)
- 쿼리 단계는 monospace

---

### STEP 2: Feature Extraction — HDPS Covariates (중앙 상단)

이 블록은 OMOP CDM에서 대규모 공변량(covariate)을 추출하는 핵심 모듈.

```
┌─ </> ─────────────────────────────────────────────┐
│  Feature Extraction (HDPS)                         │
│                                                    │
│  FeatureExtractor + CovariateSettings             │
│  lookback_days: 365, min_prevalence: 1%           │
│                                                    │
│  ┌─ COVARIATE_GROUPS ────────────────────────┐    │
│  │ ┌───────────┐ ┌──────┐ ┌─────────┐       │    │
│  │ │ Condition │ │ Drug │ │Procedure│       │    │
│  │ │ condition_│ │drug_ │ │proc_    │       │    │
│  │ │ occurrence│ │expos.│ │occur.   │       │    │
│  │ └───────────┘ └──────┘ └─────────┘       │    │
│  │ ┌──────────────────────────────────┐      │    │
│  │ │ Demographics                     │      │    │
│  │ │ year_of_birth, gender, race      │      │    │
│  │ └──────────────────────────────────┘      │    │
│  └────────────────────────────────────────────┘    │
│                                                    │
│  Output: Sparse Matrix (Patient × Feature)         │
└────────────────────────────────────────────────────┘
```
- 스타일: `#E8F4FD` 배경, 점선 파란 테두리
- COVARIATE_GROUPS 서브 블록: `#DCEEFB` 배경
- 4개의 공변량 블록은 흰색 배경, 실선 테두리
- 테이블/필드명은 monospace 이탤릭

---

### STEP 3: Propensity Score Model (중앙)
```
┌─ 📈 ─────────────────────────────────────────────┐
│  Propensity Score Model                            │
│                                                    │
│  PropensityScoreModel                             │
│  (sklearn LogisticRegression)                     │
│                                                    │
│  ┌─ Parameters ──────────────────────────────┐    │
│  │ max_iter: 1000                             │    │
│  │ regularization (C): 1.0                    │    │
│  │ solver: 'lbfgs'                            │    │
│  └────────────────────────────────────────────┘    │
│                                                    │
│  Input : X (Covariate Matrix) + y (Treatment 0/1) │
│  Output: ps_scores (P(Treatment=1|X))              │
└────────────────────────────────────────────────────┘
```
- 스타일: 흰색 배경, 실선 파란 테두리
- 파라미터 블록: `#DCEEFB` 배경
- 코드 참조: `PropensityScoreModel.fit()`, `PropensityScoreModel.predict()`

---

### STEP 4: Adjustment Method (분기점, 중앙)

이 단계에서 `analysis_method` 설정에 따라 IPTW 또는 PSM 경로를 선택.

#### 4-1. Method Router (분기점)
```
                 ┌───────────────────────────────┐
                 │  Method Router                │
                 │  config.analysis_method       │
                 └───────────┬───────────────────┘
                        ┌────┴────┐
                   IPTW          PSM
```
- 분기 라벨: "IPTW" / "PSM"
- `AnalysisConfig.analysis_method` 값으로 결정

#### 4-2. IPTW 경로 (좌측)
```
  ┌──────────────────────────┐
  │  IPTW Weights            │
  │  calculate_iptw_weights  │
  │                          │
  │  Treated: 1/PS           │
  │  Control: 1/(1-PS)       │
  │  stabilized=True         │
  │                          │
  │  trim_weights @99%ile    │
  └────────────┬─────────────┘
               ▼
  ┌──────────────────────────┐
  │  Weighted Cox Regression │
  │  weights_col="_weights"  │
  └──────────────────────────┘
```

#### 4-3. PSM 경로 (우측)
```
  ┌──────────────────────────┐
  │  PropensityMatcher       │
  │  (Nearest-Neighbor)      │
  │                          │
  │  caliper: 0.2            │
  │  ratio: 1:1              │
  │  metric: manhattan       │
  │  (sklearn NearestNeighb.)│
  └────────────┬─────────────┘
               ▼
  ┌──────────────────────────┐
  │  Matched Subset          │
  │  MatchedPair dataclass   │
  │  (treated_idx,           │
  │   control_idx, distance) │
  └────────────┬─────────────┘
               ▼
  ┌──────────────────────────┐
  │  Unweighted Cox          │
  │  Regression              │
  └──────────────────────────┘
```

> **TIP**: IPTW/PSM의 결과가 합류하여 동일한 Balance Check (STEP 5)로 진행됩니다.
> 합류 화살표로 양쪽을 하나의 Balance Check 박스로 연결하면 깔끔합니다.

---

### STEP 5: Balance Check — SMD (중앙 하단)
```
┌─ ✓ ──────────────────────────────────────────────┐
│  Balance Check (Covariate Balance Diagnostics)    │
│                                                    │
│  BalanceChecker (threshold: 0.1)                  │
│                                                    │
│  ┌─ Before Adjustment ───────────────────────┐    │
│  │ calculate_balance_table()                  │    │
│  │ SMD = (mean_T - mean_C) / pooled_std      │    │
│  └────────────────────────────────────────────┘    │
│                                                    │
│  ┌─ After Adjustment ────────────────────────┐    │
│  │ IPTW: calculate_weighted_balance_table()   │    │
│  │ PSM : calculate_balance_table(matched)     │    │
│  │ weighted_smd uses reliability-weighted var │    │
│  └────────────────────────────────────────────┘    │
│                                                    │
│  Output: {covariate: {smd_before, smd_after,      │
│           balanced: smd < 0.1}}                    │
└────────────────────────────────────────────────────┘
```
- 스타일: `#E8F4FD` 배경, 점선 테두리
- Before/After 서브블록: `#FFFFFF` 배경, 실선 테두리
- ✓ 체크 아이콘
- 임계값 `0.1`은 **볼드** 강조

---

### STEP 6: Outcome Modeling (하단)

이 블록은 두 개의 병렬 서브 컴포넌트로 구성.

#### 6-1. Cox Proportional Hazards Model (좌측)
```
┌─ 📈 ─────────────────────────┐
│  Cox PH Model (CoxModel)     │
│                               │
│  lifelines.CoxPHFitter       │
│  penalizer: 0.0 (L2 reg.)   │
│                               │
│  Input : DataFrame           │
│  (time, event, treatment,    │
│   covariates, [_weights])    │
│                               │
│  Output:                      │
│  • HR (Hazard Ratio)         │
│  • 95% CI (lower, upper)    │
│  • p-value                   │
│  • Concordance Index         │
└───────────────────────────────┘
```

#### 6-2. Kaplan-Meier Analysis (우측)
```
┌─ 📈 ─────────────────────────┐
│  KM Analysis                  │
│  (KaplanMeierAnalysis)       │
│                               │
│  lifelines.KaplanMeierFitter │
│                               │
│  • Survival curves per group │
│  • Median survival time      │
│  • Confidence intervals      │
│                               │
│  Log-rank Test               │
│  (compare_survival_curves)   │
│  → logrank_statistic, p-val  │
│  → significant: p < 0.05    │
└───────────────────────────────┘
```
- 두 박스 모두 흰색 배경, 실선 파란 테두리
- 📈 그래프 아이콘
- `lifelines` 라이브러리명은 monospace 이탤릭

---

### OUTPUT (하단 우측)
```
┌─────────────────────────────────┐
│  ■ AnalysisResult               │  ← 어두운 칩 스타일 (#263238)
│                                 │
│  hazard_ratio:                  │
│    hr, ci_lower, ci_upper,      │
│    p_value                      │
│  balance:                       │
│    {cov: {smd_before,           │
│     smd_after, balanced}}       │
│  survival_data:                 │
│    KM curves (T vs C)           │
│  analysis_method: "IPTW"|"PSM"  │
│  n_target / n_comparator        │
└─────────────────────────────────┘
```
- 어두운 배경(`#263238`)에 흰색 텍스트
- Agent 6 (Reporting Agent)로 전달됨을 화살표 라벨로 표기

---

## 🔗 화살표 & 연결 규칙

| From | To | 라벨 | 스타일 |
|------|----|------|--------|
| INPUT | STEP 1 | - | 실선, `#37474F` 화살표 |
| STEP 1 | STEP 2 | "pd.DataFrame (raw cohort)" | 실선 |
| STEP 2 | STEP 3 | "Covariate Matrix (X) + Treatment (y)" | 실선 |
| STEP 3 | STEP 4 | "ps_scores" | 실선 |
| STEP 4 Router | IPTW Path | "IPTW" | 실선, 좌측 |
| STEP 4 Router | PSM Path | "PSM" | 실선, 우측 |
| IPTW Path | STEP 5 | 합류 | 실선 |
| PSM Path | STEP 5 | 합류 | 실선 |
| STEP 5 | STEP 6 | "Balance Table + Adjusted Data" | 실선 |
| STEP 6 Cox | OUTPUT | "HR, CI, p-value" | 실선 |
| STEP 6 KM | OUTPUT | "KM Curves, Log-rank" | 실선 |
| OUTPUT | Agent 6 | "to Reporting Agent" | 점선 (외부 연결) |

> **STEP 라벨**: 각 박스 좌상단 또는 상단에 회색 (`#B0BEC5`)으로 "STEP 1", "STEP 2" 표기

---

## 📦 데이터 구조 미리보기

### AnalysisConfig (입력 설정)
```python
@dataclass
class AnalysisConfig:
    target_cohort_id: int = 0
    comparator_cohort_id: int = 0
    outcome_concept_ids: List[int] = field(default_factory=list)
    outcome_window_days: int = 365
    analysis_method: str = "IPTW"  # "IPTW" | "PSM"
    ps_model_covariates: List[str] = field(
        default_factory=lambda: ["age", "gender"]
    )
```

### Analysis Result (출력)
```python
{
    "hazard_ratio": {
        "hr": 0.87,
        "ci_lower": 0.78,
        "ci_upper": 0.97,
        "p_value": 0.01
    },
    "balance": {
        "age": {"smd_before": 0.15, "smd_after": 0.03, "balanced": True},
        "gender": {"smd_before": 0.08, "smd_after": 0.02, "balanced": True}
    },
    "analysis_method": "IPTW",
    "n_target": 1500,
    "n_comparator": 3200,
    "survival_data": {
        "treated": {"times": [...], "events": [...]},
        "control": {"times": [...], "events": [...]}
    }
}
```

### CovariateSettings
```python
@dataclass
class CovariateSettings:
    lookback_days: int = 365
    min_prevalence: float = 0.01
    max_covariates: int = 10000
    included_groups: List[str] = [
        "Condition", "Drug", "Procedure", "Demographics"
    ]
```

### COVARIATE_GROUPS
```python
COVARIATE_GROUPS = {
    "Condition": {
        "table": "condition_occurrence",
        "concept_column": "condition_concept_id",
        "date_column": "condition_start_date"
    },
    "Drug": {
        "table": "drug_exposure",
        "concept_column": "drug_concept_id",
        "date_column": "drug_exposure_start_date"
    },
    "Procedure": {
        "table": "procedure_occurrence",
        "concept_column": "procedure_concept_id",
        "date_column": "procedure_date"
    },
    "Demographics": {
        "table": "person",
        "columns": ["year_of_birth", "gender_concept_id", "race_concept_id"]
    }
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
