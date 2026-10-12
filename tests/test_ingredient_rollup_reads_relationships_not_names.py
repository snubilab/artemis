"""The ingredient roll-up resolves a product through the vocabulary, never its name.

RFC-016 §4 (C1): when ``concept_ancestor`` gave a product no RxNorm Ingredient,
``ConceptLogician._resolve_ingredient_by_name`` cut the dose and form off the product's
``concept_name`` with ``_DOSE_PATTERN`` and looked an Ingredient up by the remaining text.

The real row (``tests/fixtures/p3_structural_rows.json``, ``c1_rxnorm_extension_product``,
synthea23m): 2009211 '1000 ML Amino Acids 25 MG/ML Injectable Solution [AMINOFUSIN-TPN]
by Yungjin' has no RxNorm Ingredient ancestor. The name path reduced it to
'1000 ml amino acids', which names no RxNorm Ingredient, and kept the product id -- which
joins no ingredient-level drug row. Its ingredient is the RxNorm Extension Ingredient
588017 'Amino Acids', reachable through ``concept_ancestor``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from src.agents.agent2.logic import ConceptLogician

ROW = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "p3_structural_rows.json").read_text()
)["c1_rxnorm_extension_product"]
PRODUCT, PRODUCT_NAME = ROW["product"][0], ROW["product"][1]
INGREDIENT = ROW["ingredient"][0]


class _Vocabulary:
    """Answers each roll-up query the way synthea23m does for the real product."""

    def __init__(self) -> None:
        self.sql: list[str] = []

    def __enter__(self) -> "_Vocabulary":
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def execute(self, statement: Any, params: dict[str, Any] | None = None) -> MagicMock:
        text = str(statement)
        self.sql.append(text)
        cids = list((params or {}).get("cids") or [])
        if "LOWER(concept_name)" in text:
            rows: list[tuple] = list(ROW["name_lookup"]["rows"])
        elif "concept_name" in text:
            rows = [(PRODUCT, PRODUCT_NAME, ROW["product"][2], ROW["product"][3])]
        elif "'RxNorm Extension'" in text or "RxNorm has ing" in text:
            rows = [(PRODUCT, INGREDIENT)] if PRODUCT in cids else []
        elif "concept_ancestor" not in text and "'Ingredient'" in text:
            rows = [(cid,) for cid in cids if cid == INGREDIENT]
        else:
            rows = []  # no RxNorm Ingredient ancestor
        result = MagicMock()
        result.fetchall.return_value = rows
        return result


def test_should_roll_a_product_up_to_its_ingredient_through_the_vocabulary():
    vocabulary = _Vocabulary()
    with patch("src.agents.agent2.logic._check_db", return_value=True), \
         patch("src.utils.db.get_db", return_value=iter([vocabulary])):
        rolled_up = ConceptLogician().roll_up_to_rxnorm_ingredients([PRODUCT])

    assert rolled_up == [INGREDIENT]
    assert not [sql for sql in vocabulary.sql if "concept_name" in sql]
