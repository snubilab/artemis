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
