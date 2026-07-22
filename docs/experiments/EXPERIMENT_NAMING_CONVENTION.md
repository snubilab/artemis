# ARTEMIS 벤치마크 실험 명명 규칙 (Naming Convention)

> **기준 문서**: [BENCHMARK_CONSOLIDATED_REPORT.md](./BENCHMARK_CONSOLIDATED_REPORT.md)  
> **작성일**: 2026-03-04  
> **목적**: 모든 실험 노트에서 통일된 실험명 사용을 위한 단일 참조 문서 (Single Source of Truth)

---

## 1. 실험 계열 (Series)

|    계열     | 의미                                                            | Agent1  | 입력 단위               |
| :---------: | --------------------------------------------------------------- | :-----: | ----------------------- |
|    **M**    | **Mapping direct** — CS name → Agent2 직접                      | ❌ 없음 | Concept Set name (개별) |
|    **A**    | **Agent1 경유** — rule name → Agent1 분해 → Agent2              | ✅ 사용 | Rule name (1개)         |
| **A+Climb** | **Agent1 경유 + ancestor_climb** — Agent1 분해 → Agent2 + climb | ✅ 사용 | Rule name (1개)         |
|    **D**    | **End-to-End** — NCT+PDF → Agent1 → Agent2                      | ✅ 사용 | 논문 전체               |
|   **B/C**   | **Design paper 기반** 비교                                      |    —    | Design paper criteria   |

> [!IMPORTANT]
> **M vs A의 핵심 차이**: M은 concept set name을 Agent2에 **직접** 입력 (Agent1 미사용).  
> A는 rule name을 Agent1이 **분해**한 후 Agent2에 전달. A'는 A + 원본 term 유지.  
> **A+Climb**은 A와 동일하나 Agent2에 ancestor_climb이 추가된 버전. 현재 **미실행** 상태.

---

## 2. M 계열 Variants (Tier 1 Primary Benchmark)

| 실험명          | 입력 데이터                       | 파이프라인                    | 비고                |
| --------------- | --------------------------------- | ----------------------------- | ------------------- |
| **M-TROY**      | TROY v3.4 CS name (49개 개별)     | Agent2 + climb                | 전문가 약칭, 상한선 |
| **M-GOLD**      | GOLD CS name (18 rule 단위 merge) | Agent2 + climb                | v1.1+v3.4 최적 조합 |
| **M-SUPP**      | Supplement appendix 원문          | Agent2 + climb (auto routing) | 실전 시뮬레이션     |
| **M-SUPP-fast** | Supplement appendix 원문          | Agent2 fast path only         | Athena-only 매핑    |

---

## 3. 실험 목록 (전체)

|  Exp  | Input                              | Pipeline                     | 측정 대상                             |
| :---: | ---------------------------------- | ---------------------------- | ------------------------------------- |
| **M** | CS name (TROY/GOLD/SUPP)           | Agent 2 직접                 | Agent 2 순수 매핑 — **Primary**       |
| **A** | TROY rule name (1줄씩)             | Agent 1 → Agent 2 +ATC       | Agent 1 분해 + Agent 2 매핑 결합      |
| **B** | Design paper (prebuilt Circe JSON) | 기생성 결과 비교             | 전체 파이프라인 과거 출력물           |
| **C** | Design paper criteria (38개)       | Agent 2 +ATC (domain gating) | Agent 2 매핑 + ATC expansion          |
| **D** | NCT + papers_dir (appendix)        | Agent 1 → Agent 2 +ATC       | **End-to-end** (compound split + N:1) |

> **Tier 1 (Mapping Accuracy)** — Agent 2 순수 매핑 평가:  
> M-TROY / M-GOLD / M-SUPP / M-SUPP-fast — **Primary Benchmark**  
> Exp A / A' — Agent 1 경유 비교군  
> **A+Climb** — Agent 1 경유 + ancestor_climb (**미실행**)  
> Exp B / C — Design paper 비교군
>
> **Tier 2 (Emulation Accuracy)** — E2E 파이프라인 평가:  
> Exp D v2~v6: NCT + PDF → Agent 1 → Agent 2 → N:1 TROY 매칭

---

## 4. 버전 표기 규칙

각 실험 계열 내 버전은 **`vN`** 접미사로 표기한다:

- **M-TROY v2**: ancestor_climb 최초 연결 (2026-03-02)
- **M-TROY v3**: Neo4j full transitive closure + IC climb 개선 (2026-03-03)
- **Exp D v2**: Drug compound split + N:1 matching
- **Exp D v3**: Batch optimization
- **Exp D v5**: Determinism fix + Agent 1 cache
- **Exp D v6**: Precision recovery (drug guardrail)

---

## 5. 레거시 이름 → 현재 이름 매핑

> [!CAUTION]
> 아래 레거시 이름들은 더 이상 사용하지 않는다. 새 문서 작성 시 반드시 현재 이름을 사용할 것.

| 레거시 이름             | 현재 이름                    | 비고                              |
| ----------------------- | ---------------------------- | --------------------------------- |
| A_direct                | **M 계열**                   | "Agent2 직접" → M(Mapping direct) |
| A_direct v2             | **M-TROY v2**                | TROY CS name + 최초 climb 연결    |
| A_direct v3             | **M-TROY v3** (= **M-TROY**) | Neo4j full transitive + IC climb  |
| A_direct v3 (GOLD)      | **M-GOLD**                   | GOLD CS name 입력                 |
| A_direct v3 (SUPP)      | **M-SUPP**                   | Supplement 원문 입력              |
| A_direct v3 (SUPP fast) | **M-SUPP-fast**              | Fast path only                    |
| Exp A (TROY)            | **M-TROY**                   | §13 TROY vs SUPP 평가 맥락        |
| Exp A (SUPP)            | **M-SUPP**                   | §13 TROY vs SUPP 평가 맥락        |
| Exp A (SUPP fast)       | **M-SUPP-fast**              | §13 TROY vs SUPP 평가 맥락        |
| Benchmark V5            | **Exp A**                    | Agent1 경유, 순차 개선 이력       |
| Benchmark V7            | **Exp A / C 상세**           | Rule×ConceptSet hierarchical 비교 |

---

## 6. 관련 문서

| 문서                                                                   | 내용                    |
| ---------------------------------------------------------------------- | ----------------------- |
| [BENCHMARK_CONSOLIDATED_REPORT.md](./BENCHMARK_CONSOLIDATED_REPORT.md) | 종합 보고서 (§1.1 기준) |
| [ABLATION_STUDY.md](./ABLATION_STUDY.md)                               | 기능별 성능 변화 추적   |
| [LEADER_GOLD_STANDARD.md](./LEADER_GOLD_STANDARD.md)                   | GOLD 기준 정의          |
