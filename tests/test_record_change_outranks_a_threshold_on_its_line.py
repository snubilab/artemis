"""A row both annotation calls agree requires a record to stay the same is skipped for that.

CARMELINA inclusion 5 (P8 MAIN, 2026-10-20): "Stable antidiabetic background medication
(unchanged daily dose) for at least 8 weeks prior to randomization. If insulin is part of the
background therapy, the average daily insulin dose should not have changed by more than 10% ...".
Calls 3 and 4 agree on ``record_change: stable`` for every row of the group, and the line's only
threshold, ``not have changed by more than 10%``, is a tolerance on that same change. The build
checked the threshold first, so the label #11 and member #13 shipped as
``threshold-not-representable`` -- off the gate's allowlist -- while #6/#7 (the same sentence,
line 3) shipped as ``record-change-not-representable``. No threshold can make a stability
requirement representable, so the criterion is unrepresentable for the record-change reason
whatever else it states.

Real rows: ``tests/fixtures/carmelina_p8_inclusion5_rows.json`` (#11-#14 of the P8 MAIN store).
"""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from src.services.criterion_annotation import (
    RECORD_CHANGE_REASON,
    THRESHOLD_NOT_REPRESENTABLE_REASON,
)

ROWS: list[dict[str, Any]] = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "carmelina_p8_inclusion5_rows.json").read_text()
)


def _stub_recommend(seed_text: str, **kwargs: Any) -> dict[str, Any]:
    domain = kwargs.get("expected_domain") or "Drug"
    return {
        "name": seed_text,
        "domain": domain,
        "expression": {"items": [{
            "concept": {
                "CONCEPT_ID": 21600712, "CONCEPT_NAME": seed_text, "DOMAIN_ID": domain,
                "VOCABULARY_ID": "ATC", "CONCEPT_CLASS_ID": "ATC 2nd", "CONCEPT_CODE": "A10",
            },
            "includeDescendants": True, "isExcluded": False,
        }]},
        "mapping_metadata": None,
    }


def _skips() -> dict[str, str]:
    from src.services.tte_service import TTEService

    svc = TTEService.__new__(TTEService)
    svc._recommend_seeded_concept_set = _stub_recommend
    built = svc._build_seeded_target_circe(
        {"targetCohortName": "Linagliptin", "inclusionCriteria": deepcopy(ROWS),
         "exclusionCriteria": []}
    )
    skipped = built["_skippedCriteria"]
    return {r["criterionId"]: r["reason"] for r in skipped if r["role"] == "inclusion"}


def test_should_skip_the_label_and_its_duration_member_as_record_change():
    skips = _skips()

    assert skips.get("11") == RECORD_CHANGE_REASON, skips
    assert skips.get("13") == RECORD_CHANGE_REASON, skips


def test_should_leave_no_row_of_the_group_under_threshold_not_representable():
    assert THRESHOLD_NOT_REPRESENTABLE_REASON not in _skips().values()
