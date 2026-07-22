# ARTEMIS 3.1 User Guide

> **T**arget **T**rial **E**mulation **S**ystem - End-to-End Automated Clinical Evidence Generation

## Table of Contents
1. [Overview](#overview)
2. [Installation](#installation)
3. [Configuration](#configuration)
4. [Quick Start](#quick-start)
5. [Usage Examples](#usage-examples)
6. [API Reference](#api-reference)
7. [Troubleshooting](#troubleshooting)

---

## Overview

ARTEMIS 3.1 is a multi-agent system that:
1. **Parses** natural language clinical questions into structured representations
2. **Maps** clinical concepts to OMOP CDM standard vocabulary
3. **Assembles** OHDSI Circe-compatible cohort definitions
4. **Validates** the generated JSON schemas
5. **Analyzes** treatment effects using causal inference (PSM/IPTW, Cox regression)
6. **Reports** results with publication-quality visualizations

### Architecture

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  Agent 1    │ -> │  Agent 2    │ -> │  Agent 3    │ -> │  Agent 4    │
│  NLU/IR     │    │  Mapper     │    │  Assembler  │    │  Validator  │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
                                            │
                                            v
┌─────────────┐    ┌─────────────┐
│  Agent 6    │ <- │  Agent 5    │
│  Reporter   │    │  Analyst    │
└─────────────┘    └─────────────┘
```

---

## Installation

### Prerequisites
- Python 3.10+
- PostgreSQL with OMOP CDM schema
- Redis (for state management)
- Docker & Docker Compose (optional)

### Option 1: Local Installation

```bash
# Clone the repository
git clone https://github.com/your-org/artemis.git
cd artemis

# Create virtual environment
conda create -n artemis python=3.12
conda activate artemis

# Install dependencies
pip install -e .

# Install optional dependencies for PDF generation
pip install weasyprint  # Requires system libraries (gobject, pango)
```

### Option 2: Docker

```bash
# Start all services
docker-compose up -d

# Check status
docker-compose ps
```

---

## Configuration

### Environment Variables

Create a `.env` file in the project root:

```env
# Database
DATABASE_URL=postgresql://user:password@localhost:5432/omop

# Redis
REDIS_URL=redis://localhost:6379/0

# LLM API
OPENAI_API_KEY=sk-xxx
ANTHROPIC_API_KEY=xxx

# Vector Store
CHROMA_PERSIST_DIR=./data/chroma

# Output
OUTPUT_DIR=./output
```

### Config Files

ARTEMIS uses YAML configuration for advanced settings:

```yaml
# config/artemis.yaml
analysis:
  default_method: IPTW  # or PSM
  ps_clipping: [0.01, 0.99]
  smd_threshold: 0.1

reporting:
  include_km_plot: true
  include_forest_plot: true
  include_love_plot: true
  pdf_template: default
```

---

## Quick Start

### Basic Usage

```python
from src.pipeline.orchestrator import ArtemisPipeline

# Initialize pipeline
pipeline = ArtemisPipeline()

# Run analysis
result = pipeline.run(
    query="Patients on metformin vs sulfonylurea with cardiovascular outcome within 2 years",
    output_dir="./output/my_study"
)

print(f"Report generated: {result['report_path']}")
```

### Using Individual Agents

```python
# Agent 1: Parse natural language
from src.agents.agent1 import Agent1Workflow
agent1 = Agent1Workflow()
ir = agent1.process("Patients with Type 2 diabetes on metformin")

# Agent 2: Map to OMOP concepts
from src.agents.agent2 import Agent2Workflow
agent2 = Agent2Workflow()
mapped_ir = agent2.process(ir)

# Agent 3: Assemble cohort JSON
from src.agents.agent3 import Agent3Workflow
agent3 = Agent3Workflow()
cohort_json = agent3.process(mapped_ir)

# Agent 4: Validate
from src.agents.agent4 import Agent4Workflow
agent4 = Agent4Workflow()
validation_result = agent4.validate(cohort_json)
```

---

## Usage Examples

### Example 1: SGLT2i vs DPP4i Cardiovascular Study

```python
from src.pipeline.orchestrator import ArtemisPipeline

pipeline = ArtemisPipeline()
result = pipeline.run(
    query="""
    Compare SGLT2 inhibitors (empagliflozin, dapagliflozin, canagliflozin) 
    versus DPP-4 inhibitors (sitagliptin, saxagliptin, linagliptin)
    in patients with Type 2 diabetes mellitus and established cardiovascular disease.
    
    Primary outcome: 3-point MACE (cardiovascular death, myocardial infarction, stroke)
    Follow-up: 365 days
    """,
    output_dir="./output/sglt2i_study"
)
```

### Example 2: Custom Analysis with Agent 5

```python
import pandas as pd
from src.agents.agent5 import Agent5Workflow
from src.agents.agent6 import Agent6Workflow

# Prepare your data
data = pd.read_csv("my_cohort_data.csv")

# Run analysis
agent5 = Agent5Workflow()
agent5.configure(target_cohort_id=1, comparator_cohort_id=2)
results = agent5.run(data=data)

print(f"Hazard Ratio: {results['hazard_ratio']['hr']:.2f}")
print(f"95% CI: [{results['hazard_ratio']['ci_lower']:.2f}, {results['hazard_ratio']['ci_upper']:.2f}]")

# Generate report
agent6 = Agent6Workflow()
agent6.set_results(
    study_title="My Custom Study",
    hazard_ratio=results['hazard_ratio'],
    target_n=results['n_target'],
    comparator_n=results['n_comparator'],
    balance=results['balance'],
    ps_scores=results['ps_scores'],
    treatment=results['treatment'],
    survival_data=results['survival_data']
)
agent6.generate_plots("./output/plots")
agent6.generate_html_report("./output/report.html")
```

---

## API Reference

### Agent 5: Analysis Agent

```python
class Agent5Workflow:
    def configure(
        self,
        target_cohort_id: int,
        comparator_cohort_id: int,
        outcome_definition: Optional[Dict] = None,
        analysis_method: str = "IPTW"  # or "PSM"
    ) -> Agent5Workflow

    def run(self, data: Optional[pd.DataFrame] = None) -> Dict[str, Any]
        """
        Returns:
            {
                "hazard_ratio": {"hr", "ci_lower", "ci_upper", "p_value"},
                "balance": {covariate: {"smd_before", "smd_after", ...}},
                "ps_scores": np.ndarray,
                "weights": np.ndarray,
                "survival_data": {...},
                "n_target": int,
                "n_comparator": int
            }
        """
```

### Agent 6: Reporting Agent

```python
class Agent6Workflow:
    def set_results(
        self,
        study_title: str,
        hazard_ratio: Any,
        target_n: int,
        comparator_n: int,
        balance: Optional[Dict] = None,
        ps_scores: Optional[np.ndarray] = None,
        treatment: Optional[np.ndarray] = None,
        survival_data: Optional[Dict] = None
    ) -> Agent6Workflow

    def generate_plots(self, output_dir: str) -> Dict[str, str]
    def generate_report(self, output_path: str) -> str
    def generate_html_report(self, output_path: str) -> str
```

### Visualization Classes

```python
from src.reporting.plots import ForestPlot, KMCurvePlot, LovePlot, PSDistPlot

# Forest Plot
forest = ForestPlot([{"study": "Main", "hr": 0.85, "ci_lower": 0.72, "ci_upper": 0.99}])
forest.save("forest.png")

# KM Curve
km = KMCurvePlot()
km.add_curve(times=[...], survival=[...], label="Treatment")
km.add_curve(times=[...], survival=[...], label="Control")
km.save("km_curve.png")

# Love Plot
love = LovePlot({"age": {"before": 0.15, "after": 0.05}})
love.save("love.png")
```

---

## Troubleshooting

### Common Issues

**Q: WeasyPrint fails with "cannot load library 'libgobject'"**
```bash
# macOS
brew install glib pango

# Ubuntu
apt-get install libpango-1.0-0 libgdk-pixbuf2.0-0
```

**Q: ChromaDB import error**
```bash
pip install chromadb
```

**Q: Redis connection refused**
```bash
# Start Redis
docker run -d --name redis -p 6379:6379 redis:alpine
```

**Q: Cox model convergence warning**

This is expected for small datasets or when treatment perfectly predicts outcome. Consider:
- Increasing sample size
- Using regularization: `CoxModel(penalizer=0.1)`

---

## License

MIT License - See LICENSE file for details.
