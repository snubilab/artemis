# 2026-03-09 KG Expansion Overgeneration Fix

## 작업 내용

Lab meeting (2026-03-05) 합의에 따라 KG Expansion overgeneration 4-phase 수정 구현 및 ablation 수행.

### 변경 파일

- `src/agents/agent2/kg_expander.py`: `clinical_anchor` strategy 추가
- `src/agents/agent2/workflow.py`: `KG_EXPAND_MODE` env var + domain-aware caps + Critic skip
- `src/agents/consolidator/consolidator.py`: `KG_CONSOLIDATOR_AGGRESSIVE` env var + IC guard

### Ablation 결과

| Phase     | Config                       | Raw     | Recall    | Prec.     | F1        |
| --------- | ---------------------------- | ------- | --------- | --------- | --------- |
| Baseline  | clinical (legacy)            | 572     | 50.8%     | 48.3%     | 39.9%     |
| P1        | clinical_anchor              | 307     | 58.3%     | 38.3%     | 37.8%     |
| **P2 ✅** | **+domain caps**             | **418** | **63.7%** | **41.9%** | **42.4%** |
| P3 ❌     | +rel caps+cap120             | 293     | 60.7%     | 27.6%     | 28.3%     |
| P4        | +aggressive consolidator     | 413     | 61.6%     | 39.6%     | 39.6%     |
| **P2.1**  | **P2 + ancestor_climb 복원** | **491** | **61.3%** | **46.1%** | **45.0%** |

### M-TROY (A_direct) Ablation

| Phase                   | Config                       | Recall    | Prec.     | F1        | Full   |
| ----------------------- | ---------------------------- | --------- | --------- | --------- | ------ |
| Baseline (Maps to 이전) | clinical + ancestor_climb    | 83.1%     | 53.3%     | 55.8%     | —      |
| +Maps to                | +2.75M Maps to rels          | 88.8%     | 43.3%     | 47.8%     | 14     |
| **+Dynamic IC**         | **+`max(8.0, seed_ic-2.5)`** | **91.2%** | **44.1%** | **49.0%** | **15** |
| +Desc-Gated Critic      | +desc>500→Critic forced      | 88.7%     | 45.5%     | 51.0%     | 14     |
| **+includeDesc gating** | **desc>5000→includeDesc=F**  | **90.3%** | **47.0%** | **52.3%** | **15** |

### 결론

- **Phase 2.1** (`clinical_anchor` + domain caps + ancestor_climb) = E2E 최종 설정
  - E2E: Recall 50.8% → 61.3%, F1 39.9% → 45.0%
- **Dynamic IC threshold** = M-TROY 최적
  - M-TROY: Recall 88.8% → 91.2%, F1 47.8% → 49.0%
  - `No pregnant` P: 2% → 100% (broad seed climb 차단)
- Phase 3 (relation-level caps) 은 Precision 회귀로 revert
- Phase 4 (Consolidator) 는 benchmark 경로에서 neutral impact

### 벤치마크 기준 정리

> **중요**: 83.1% Recall (M-TROY)은 `benchmark_a_direct` 결과 — Agent 1을 거치지 않고
> TROY CS name을 Agent 2에 직접 입력한 것. `benchmark_v5`(E2E, Agent 1→Agent 2)와는
> 다른 벤치마크.

| 벤치마크                | Agent 1 | 최고 Recall | 비고                     |
| ----------------------- | ------- | ----------- | ------------------------ |
| **M-TROY** (`a_direct`) | ❌ 없음 | **83.1%**   | Agent 2 순수 매핑 상한   |
| **benchmark_v5** (E2E)  | ✅ 사용 | **63.7%**   | Agent 1 분해 품질이 병목 |

### Neo4j `Maps to` relationship 부재

Neo4j에 `HAS_DESCENDANT` relationship만 존재. `Maps to` 미로딩.

- `get_maps_to()` 호출 시 항상 빈 결과 → non-standard concept의 standard 변환 불가
- 현재 ancestor/sibling 경로로 우회 중이므로 즉각 Recall에 큰 영향은 없으나, 향후 수정 필요

### 새 Env Vars

- `KG_EXPAND_MODE`: `clinical_anchor` (default) / `clinical`
- `KG_CONSOLIDATOR_AGGRESSIVE`: `true` / unset
