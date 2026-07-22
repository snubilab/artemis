# SHARED_CONTEXT: v6_cohort_benchmark

## 1. Global Types / Interfaces

### Data Structures for Benchmark Outputs
```python
from typing import Dict, Any, List
from pydantic import BaseModel

class CohortMetrics(BaseModel):
    gold_count: int
    agent_count: int
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    jaccard_similarity: float
    f1_score: float

class BenchmarkResult(BaseModel):
    trial_name: str
    run_mode: str
    metrics: CohortMetrics
    gold_cohort_id: int
    agent_cohort_id: int
    execution_time_seconds: float
    timestamp: str
```

## 2. Environment & Constants
- `WEBAPI_URL`: "http://127.0.0.1/WebAPI"
- `DB_SCHEMA`: "synthea23m"
- `RESULTS_SCHEMA`: "synthea23m_results"
- Benchmark Cache File: `artemis/output/v6_cohort_cache.json` (Stores gold cohort IDs mapped to JSON hash)
