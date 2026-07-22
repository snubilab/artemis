# ARTEMIS 3.1 Documentation

> End-to-End Automated Clinical Evidence Generation System

---

## 📁 Directory Structure

```
docs/
├── README.md                  ← 이 파일
├── ROADMAP.md                 ← 프로젝트 로드맵
├── user_guide.md              ← 사용자 가이드
│
├── architecture/              ← 시스템 아키텍처
│   └── 01_system_overview.md
│
├── implementation_plans/      ← Phase별 구현 계획
│   ├── phase_1_*.md           ← Phase 1: Semantic Intelligence
│   ├── phase_2_*.md           ← Phase 2: Assembler & Registry
│   ├── phase_3_*.md           ← Phase 3: Analysis Engine
│   └── phase_4_*.md           ← Phase 4: Reporting & Validation
│
├── adr/                       ← Architecture Decision Records
│   ├── ADR-002                ← KG RAG 구현 전략
│   ├── ADR-010                ← Broadsea DB 연결
│   ├── ADR-011                ← Agent 2 Concept Boosting
│   └── ADR-012                ← UMLS Synonym Expansion
│
├── rfc/                       ← Requests for Comments (기술 제안서)
│   ├── RFC-001                ← TROY-ARTEMIS Gap Closing 전략
│   ├── RFC-002                ← EHR Navigator Pattern
│   ├── RFC-003                ← KG RAG Agent 2 Concept Expansion
│   └── RFC-004                ← Multi-Concept Expansion (includeDescendants)
│
├── experiments/               ← 실험 결과 및 벤치마크
│   ├── agent2_benchmark_report.md  ← Agent 2 매핑 성능 추이 보고서
│   ├── 2026-01-27.md               ← 프로젝트 초기화 로그
│   └── benchmarks/                 ← 원본 벤치마크 데이터
│       ├── v1_*.{log,json}         ← V1: Hierarchy-aware 비교
│       └── v2_*.{log,json}         ← V2: Resolved-set 비교
│
├── agent1_enhancement/        ← Agent 1 개선 작업 (Strict-Modular-TDD)
│   ├── 000_ARCH_MAP.md
│   ├── 001_SHARED_CONTEXT.md
│   └── 01~03_*.md             ← NCT→PMID, PubMed Parser, Multi-Source Merge
│
├── ohdsi_data_collection.md   ← OHDSI 데이터 수집 가이드
└── sample.json                ← TROY ConceptSet 샘플 (참조용)
```

---

## 🔗 Quick Links

| 문서 유형 | 용도 | 주요 파일 |
|----------|------|----------|
| **아키텍처** | 시스템 전체 구조 이해 | [System Overview](architecture/01_system_overview.md) |
| **ADR** | 왜 이 기술 결정을 했는지 | [ADR 목록](adr/) |
| **RFC** | 새로운 기능 제안 및 검토 | [RFC 목록](rfc/) |
| **실험 결과** | Agent 2 벤치마크 성능 추적 | [Benchmark Report](experiments/agent2_benchmark_report.md) |
| **구현 계획** | Phase별 상세 태스크 | [Implementation Plans](implementation_plans/) |

---

## 📊 Latest Benchmark (2026-02-11)

LEADER Trial TROY v3.4 대비 46개 concept set 매핑 성능:

| Metric | V1 (Raw ID + Hierarchy) | V2 (Resolved Set) |
|--------|------------------------|-------------------|
| ✅ Full Match | 24 (52%) | 21 (46%) |
| 🟡 Partial | 10 (22%) | 15 (33%) |
| ⚠ Wrong | 12 (26%) | 10 (22%) |
| Avg Recall | — | 59.4% |

→ 상세: [Agent 2 Benchmark Report](experiments/agent2_benchmark_report.md)
