# ARTEMIS 3.1

> **T**arget **T**rial **E**mulation **S**ystem  
> End-to-End Automated Clinical Evidence Generation

[![Tests](https://img.shields.io/badge/tests-67%20passed-success)](./tests)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-green)](./LICENSE)

## Overview

ARTEMIS 3.1 is a multi-agent system that translates natural language clinical questions into OHDSI-standard cohorts, performs causal inference analysis, and generates publication-quality reports.

### Key Features

- 🧠 **Natural Language Processing**: Parse complex clinical trial criteria
- 🗺️ **Semantic Mapping**: Hybrid search (Regex + BioLinkBERT + LLM Judge) 
- 📊 **Causal Inference**: Propensity Score Matching (PSM) & IPTW
- 📈 **Survival Analysis**: Cox Proportional Hazards with weighted regression
- 📑 **Automated Reporting**: Kaplan-Meier curves, Forest plots, Love plots, PDF

### Architecture

```
┌────────────────────────────────────────────────────────────────┐
│                    ARTEMIS 3.1 Multi-Agent System                │
├────────────────────────────────────────────────────────────────┤
│  Phase 1: Cohort Definition                                    │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │ Agent 1  │→ │ Agent 2  │→ │ Agent 3  │→ │ Agent 4  │       │
│  │ NLU/IR   │  │ Mapper   │  │ Assembler│  │ Validator│       │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘       │
├────────────────────────────────────────────────────────────────┤
│  Phase 2: Evidence Generation                                  │
│  ┌──────────┐  ┌──────────┐                                   │
│  │ Agent 5  │→ │ Agent 6  │                                   │
│  │ Analyst  │  │ Reporter │                                   │
│  └──────────┘  └──────────┘                                   │
└────────────────────────────────────────────────────────────────┘
```

## Quick Start

### Installation

```bash
# Clone repository
git clone https://github.com/your-org/artemis.git
cd artemis

# Create environment
conda create -n artemis python=3.12
conda activate artemis

# Install dependencies
pip install -e .
```

### What git does not carry

The repository holds code only. A fresh clone needs the following before the pipeline runs.

| Path | Size (2026-09-23) | Used by | How to get it |
|------|-------------------|---------|---------------|
| `.env` | — | Credentials and endpoints for every agent | Copy `.env.example` and fill it in. Never commit it. |
| `chroma_db/` | 3.0 GB | Agent 2 concept search | Lab shared storage: `<path to be filled>` |
| `data/pubchem/pubchem_synonyms.sqlite` | 22 GB | Agent 2 drug-name normalizer | Rebuild with `scripts/build_pubchem_synonym_db.py`, or copy from lab shared storage |
| `data/gold/` | 2.6 MB | Per-criterion evaluation (TROY v1.1 CIRCE gold) | Lab shared storage. Keep it inside the lab until its licence is confirmed. |
| OMOP vocabulary | — | Mounted at `/omop_vocab` by the Broadsea compose stack | Athena download, or lab shared storage |

The pipeline also connects to an OMOP CDM PostgreSQL (`OMOP_DB_*`), Neo4j for the
knowledge-graph expander (`NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`; these three are
not in `.env.example`), and an LLM endpoint (`OPENROUTER_API_KEY`, or `VLLM_BASE_URL`
for a local model).

**Never copy `data/site_snapshots/`.** It holds the prevalence snapshots received from
partner hospitals. It is gitignored and must stay out of every copy of this repository.

### Run E2E Demo

```bash
python scripts/e2e_demo.py
```

**Output:**
```
============================================================
ARTEMIS 3.1 End-to-End Demo
============================================================

[1/4] Generating synthetic clinical trial data...
  - Total patients: 1000
  
[2/4] Running Agent 5 (Analysis Agent)...
  - Hazard Ratio: 0.820
  - 95% CI: [0.685, 0.982]
  - p-value: 0.0310

[3/4] Running Agent 6 (Reporting Agent)...
  - Generated plots: forest, km, love, ps_dist

[4/4] Generating report...
  - Report saved: output/e2e_demo/report.html

✅ E2E Demo Complete!
```

### Docker

```bash
# Production
docker-compose -f docker-compose.prod.yml up -d

# Development
docker-compose up -d
```

## Documentation

- [User Guide](./docs/user_guide.md) - Complete usage documentation
- [Spec](./docs/spec.md) - Technical specification
- [ADR](./docs/adr/) - Architecture Decision Records

## Per-Site CDM Adaptation (사이트별 코호트 적응)

같은 코호트 정의라도 병원마다 vocabulary 매핑·코딩 세분도·데이터 밀도가 달라
그대로 배포할 수 없다. 병원 CDM에 접근하지 않고 **ACHILLES 집계 파일만 받아**
코호트를 사이트별로 적응시킨다. 설계는 [ADR-030](./docs/adr/ADR-030_Per_Site_CDM_Adaptation_Layer.md).

**문서**
- [현재상태·재개 가이드](./docs/site_data_request/현재상태_및_재개가이드.md) — 무엇이 되어 있고 어디서 이어가는지 (여기부터 읽기)
- [ACHILLES 데이터 요청서](./docs/site_data_request/ACHILLES_데이터_요청서.md) — 병원 담당자에게 보내는 문서
- [수령 데이터 정규화](./docs/site_data_request/수령데이터_정규화.md) — 받은 파일 → 표준 스냅샷 변환 기록

**수령 데이터 → 표준 스냅샷** (사이트마다 형식이 달라 정규화가 필요하다)

```bash
python3 scripts/normalize_site_achilles.py \
  --input <수령 폴더> --output data/site_snapshots \
  --run-date <ACHILLES 실행일> --small-cell-count <사이트 억제 임계값>
```

`data/site_snapshots/<site>.zip` = `achilles_prevalence.csv` + `manifest.json`
(gitignore 대상 — 코드만 커밋되고 데이터는 위 명령으로 재생성한다)

**적응 실행**

```bash
python3 scripts/adapt_site_cdm.py \
  --snapshot data/site_snapshots/<site>.zip --circe <코호트>.json \
  --vocabulary-map <site vocabulary map>.json --output site_report.json
```

리포트는 `status: "proposed"` — 자동 적용하지 않고 담당자 검토용 제안만 낸다.

## Project Structure

```
artemis/
├── src/
│   ├── agents/          # Multi-agent components
│   │   ├── agent1/      # NLU / Logic Decomposer
│   │   ├── agent2/      # Intelligent Mapper
│   │   ├── agent3/      # Cohort Assembler
│   │   ├── agent4/      # Validator
│   │   ├── agent5/      # Analysis Agent
│   │   └── agent6/      # Reporting Agent
│   ├── analysis/        # Causal inference engine
│   │   ├── propensity.py
│   │   ├── balance.py
│   │   ├── cox.py
│   │   └── feature_extraction.py
│   ├── reporting/       # Visualization & PDF
│   │   ├── plots/
│   │   └── pdf_generator.py
│   └── registry/        # Global concept registry
├── tests/               # 67+ unit tests
├── scripts/             # CLI tools
├── docs/                # Documentation
└── output/              # Generated reports
```

## Test Status

| Phase | Tests | Description |
|-------|-------|-------------|
| 1 | 6 | NLU, IR, Registry |
| 2 | 20 | Mapping, Assembly, Validation |
| 3 | 19 | PSM, IPTW, Cox, Balance |
| 4 | 24 | Plots, PDF, Agent 5/6 |
| **Total** | **67 passed** | All phases verified |

```bash
pytest tests/ -v
# ================== 67 passed, 4 skipped, 5 warnings ==================
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Run tests: `pytest tests/ -v`
4. Submit a pull request

## License

MIT License - See [LICENSE](./LICENSE) for details.

---

<p align="center">
  <sub>Built with ❤️ for Real-World Evidence generation</sub>
</p>
