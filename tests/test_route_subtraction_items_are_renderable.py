"""A route-subtraction exclusion must be a concept Atlas can draw, built from its vocabulary row.

``_apply_route_subtraction`` appends ``isExcluded`` Clinical Drug Form items. Until this fix it
built each one by hand with fixed values ("Clinical Drug Form", "S", "RxNorm", CONCEPT_CODE "")
and no ``STANDARD_CONCEPT_CAPTION``. Since 907ab84 writes them back into the returned concept
set, the 2026-10-08 dry rebuild carried 1,756 such members in each CAROLINA arm and 18 in each
EMPA-REG arm, and ``scripts/verify_atlas_renderable.py`` fell from 6/6 to 2/6 -- every one
"missing ['STANDARD_CONCEPT_CAPTION']". Atlas aborts the whole concept-set table on the first.

The item's concept now comes from the CONCEPT row, through the same ``ConceptRecord`` the
export repairs use (``as_circe_concept``, the shape the expression builder emits).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.services.overbroad_absence_repair import ConceptRecord
from src.services.route_subtraction import DrugForm
from src.services.tte_service import TTEService

REPO = Path(__file__).resolve().parents[1]

INGREDIENT_ID = 1001
ORAL = DrugForm(2001, "prednisolone Oral Tablet", "Oral Tablet")
TOPICAL = DrugForm(2002, "prednisolone Topical Cream", "Topical Cream")
SEED = "Systemic corticosteroid"


def _atlas_checker():
    spec = importlib.util.spec_from_file_location(
        "verify_atlas_renderable", REPO / "scripts" / "verify_atlas_renderable.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ingredient_items() -> list[dict[str, Any]]:
    return [
        {
            "concept": ConceptRecord(
                INGREDIENT_ID, "prednisolone", "Drug", "RxNorm", "Ingredient", "S", "8638", None
            ).as_circe_concept(),
            "isExcluded": False,
            "includeDescendants": True,
            "includeMapped": False,
        }
    ]


def _row(form: DrugForm, **overrides: Any) -> ConceptRecord:
    fields = dict(
        concept_id=form.concept_id,
        concept_name=form.concept_name,
        domain_id="Drug",
        vocabulary_id="RxNorm",
        concept_class_id="Clinical Drug Form",
        standard_concept="S",
        concept_code=f"code-{form.concept_id}",
        invalid_reason=None,
    )
    fields.update(overrides)
    return ConceptRecord(**fields)


def _subtract(forms: list[DrugForm], rows: dict[int, ConceptRecord]) -> list[dict[str, Any]]:
    items = _ingredient_items()
    service = TTEService(store=MagicMock())
    with patch.object(TTEService, "_fetch_drug_forms", return_value=forms), \
         patch.object(TTEService, "_fetch_concept_records", return_value=rows, create=True):
        service._apply_route_subtraction(items, SEED, "Drug")
    return items


def _excluded(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [i for i in items if i.get("isExcluded")]


def test_should_emit_every_field_atlas_reads_when_route_subtraction_excludes_a_form(tmp_path):
    items = _subtract([ORAL, TOPICAL], {TOPICAL.concept_id: _row(TOPICAL)})

    assert [i["concept"]["CONCEPT_ID"] for i in _excluded(items)] == [TOPICAL.concept_id]
    path = tmp_path / "arm.circe.json"
    concept_set = {"id": 1, "name": SEED, "expression": {"items": items}}
    path.write_text(json.dumps({"ConceptSets": [concept_set]}))
    assert _atlas_checker().check_file(path) == []


def test_should_take_each_field_from_the_vocabulary_row_when_building_an_excluded_form():
    row = _row(TOPICAL, vocabulary_id="RxNorm Extension", concept_code="OMOP4711")
    items = _subtract([ORAL, TOPICAL], {TOPICAL.concept_id: row})

    (excluded,) = _excluded(items)
    assert excluded["concept"] == row.as_circe_concept()
    assert excluded["isExcluded"] is True
    assert excluded["includeDescendants"] is True
    assert excluded["includeMapped"] is False


def test_should_raise_when_the_vocabulary_has_no_row_for_an_excluded_form():
    """The form came from the same CONCEPT table one query earlier; a missing row is an
    inconsistency to stop on, not a member to invent fields for."""
    with pytest.raises(RuntimeError, match=str(TOPICAL.concept_id)):
        _subtract([ORAL, TOPICAL], {})


def test_should_not_query_the_vocabulary_when_route_subtraction_excludes_nothing():
    items = _ingredient_items()
    service = TTEService(store=MagicMock())
    fetch = MagicMock(return_value={})
    with patch.object(TTEService, "_fetch_drug_forms", return_value=[ORAL]), \
         patch.object(TTEService, "_fetch_concept_records", fetch, create=True):
        service._apply_route_subtraction(items, SEED, "Drug")

    assert items == _ingredient_items()
    fetch.assert_not_called()
