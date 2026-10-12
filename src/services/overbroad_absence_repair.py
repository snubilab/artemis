"""Concept identity by id: the CONCEPT row fields a Circe concept-set item carries.

What remains of the over-broad-absence repair after RFC-016 §4 (C7). That repair
replaced the single member of an absence concept set with the standard concept whose
``concept_name`` equalled the set's NAME -- a model-written free-text name matched
against vocabulary names, which is a text rule -- and it is deleted. An over-broad
absence set is the critic's question, decided from candidates rather than from a name.

The by-id catalog stays: the route subtraction reads it
(``TTEService`` builds ``isExcluded`` items from :meth:`ConceptRecord.as_circe_concept`).
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol

#: The caption Atlas renders beside ``STANDARD_CONCEPT``. Mirrors
#: ``ConceptSetExpression._standard_concept_caption`` in
#: :mod:`src.agents.conceptset.expression_builder`, so an item built from a record here is
#: indistinguishable in shape from one the builder wrote.
_STANDARD_CAPTIONS = {"S": "Standard", "C": "Classification"}


# --------------------------------------------------------------------------
# the concept seam
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ConceptRecord:
    """The CONCEPT row fields a Circe concept-set item carries."""

    concept_id: int
    concept_name: str
    domain_id: str
    vocabulary_id: str
    concept_class_id: str
    standard_concept: str | None
    concept_code: str
    invalid_reason: str | None

    @property
    def is_standard_and_valid(self) -> bool:
        return self.standard_concept == "S" and self.invalid_reason is None

    def as_circe_concept(self) -> dict[str, Any]:
        """The item's ``concept`` object, in the shape the expression builder emits."""
        return {
            "CONCEPT_ID": self.concept_id,
            "CONCEPT_NAME": self.concept_name,
            "DOMAIN_ID": self.domain_id,
            "VOCABULARY_ID": self.vocabulary_id,
            "CONCEPT_CLASS_ID": self.concept_class_id,
            "STANDARD_CONCEPT": self.standard_concept,
            "STANDARD_CONCEPT_CAPTION": _STANDARD_CAPTIONS.get(
                self.standard_concept or "", "Non-Standard"
            ),
            "CONCEPT_CODE": self.concept_code,
            "INVALID_REASON": self.invalid_reason,
            "INVALID_REASON_CAPTION": None,
        }


class ConceptCatalog(Protocol):
    """Concept identity by id. Deliberately free of any DB import."""

    def concepts_by_id(self, concept_ids: Iterable[int]) -> dict[int, ConceptRecord]:
        """The CONCEPT rows for these ids. Absent ids are absent from the result."""


@dataclass
class PrefetchedConcepts:
    """Pure-Python :class:`ConceptCatalog` over a bag of :class:`ConceptRecord`."""

    records: dict[int, ConceptRecord] = field(default_factory=dict)

    def concepts_by_id(self, concept_ids: Iterable[int]) -> dict[int, ConceptRecord]:
        return {cid: self.records[cid] for cid in concept_ids if cid in self.records}


class PostgresConceptCatalog:
    """:class:`ConceptCatalog` over an OMOP vocabulary, one batched query.

    ``psycopg2`` is imported inside ``__init__`` so importing this module -- and
    therefore ``python -m src.boot_check`` -- never needs a database driver, exactly as
    :class:`~src.services.conceptset_closure.PostgresVocabulary` does.
    """

    _COLUMNS = (
        "concept_id, concept_name, domain_id, vocabulary_id, concept_class_id, "
        "standard_concept, concept_code, invalid_reason"
    )

    def __init__(self, dsn: str, schema: str) -> None:
        import psycopg2  # noqa: PLC0415 -- deliberately lazy; see docstring

        self.schema = schema
        self._conn = psycopg2.connect(dsn)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "PostgresConceptCatalog":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _rows(self, sql: str, params: tuple) -> list[ConceptRecord]:
        cur = self._conn.cursor()
        try:
            cur.execute(sql, params)
            return [ConceptRecord(*row) for row in cur.fetchall()]
        finally:
            cur.close()

    def concepts_by_id(self, concept_ids: Iterable[int]) -> dict[int, ConceptRecord]:
        ids = sorted({int(c) for c in concept_ids})
        if not ids:
            return {}
        rows = self._rows(
            f"SELECT {self._COLUMNS} FROM {self.schema}.concept WHERE concept_id = ANY(%s)",
            (ids,),
        )
        return {r.concept_id: r for r in rows}
