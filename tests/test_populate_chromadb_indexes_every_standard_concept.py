"""The vector index must hold every standard concept of every eligibility domain.

``scripts/populate_chromadb.py`` capped Observation at 50,000 rows and sliced them
with ``ORDER BY concept_id``, so the index ended at concept_id 4,144,455 and every
standard Observation concept above that id was simply absent. Measured against the
live vocabulary (``synthea23m``) and the live production collection on 2026-09-09::

    domain       standard    cap       indexed    dropped   slice ends at
    Condition      105,666   None       105,666         0   -
    Drug         2,048,627   100,000    100,000 1,948,627   2,042,837
    Procedure       58,158   None        58,158         0   -
    Measurement     94,798   None        94,798         0   -
    Observation    132,423   50,000      50,000    82,423   4,144,455
    Device          32,168   None        32,168         0   -

    omop_concepts_medcpt (production, EMBEDDING_MODEL=medcpt): 440,790 documents
    Observation documents in it: 50,000, min id 8,715, max id 4,144,455

The 82,423 dropped Observation concepts are SNOMED 67,646 / LOINC 13,767 /
HCPCS 951 / OMOP Extension 59, and include 812 of the 1,352 Observation concepts
naming a contraindication, intolerance, allergy or history-of (60%).

That is the measured cause of a real mapping failure. "Contraindication to
clopidogrel" could not map, and the three concepts that answer it are standard,
valid, Observation-domain, and all sit above the slice boundary::

    4170410   Adverse reaction to clopidogrel   SNOMED  Observation  S
    4248529   Clopidogrel contraindicated       SNOMED  Observation  S
    44811047  Clopidogrel not tolerated         SNOMED  Observation  S

    docker exec artemis-api ... col.get(ids=[...]) -> []   (none indexed)

``test_should_index_the_clopidogrel_concepts_the_50000_row_cap_dropped`` runs that
case against the real vocabulary rather than a fixture: it reads what the old capped
query returned, what the uncapped query returns, and pins the boundary between them.

Deliberately NOT changed: the Drug cap. 100,000 of 2,048,627 standard Drug concepts,
the same ``ORDER BY concept_id`` slice ending at id 2,042,837, which holds 5,860 of
33,218 Ingredients and 30,157 of 570,985 Marketed Products. Removing it is a
mapping-quality decision that has to be measured per criterion against ``data/gold/``
with ``scripts/conceptset_overlap_eval.py``; it is not this defect and must not ride
into a re-extraction unattributed.

Two guards replace the "collection is non-empty, skip everything" early return, which
is what let the cap survive a re-run:

* the sync is incremental -- it reads which ids a batch already holds and adds only
  the rest, so a re-index costs the missing rows and not the whole universe;
* it verifies. ``chromadb`` 1.5.5 ``add()`` silently accepts an id the collection
  already holds and returns nothing, so ``len(missing)`` is not evidence that
  ``len(missing)`` rows landed. What is counted as added is what a read-back
  confirms, and a domain that ends short of the row count the vocabulary promised
  raises rather than printing a smaller number.

The two populate scripts share one domain table. Production reads
``omop_concepts_medcpt`` (``EMBEDDING_MODEL=medcpt`` on the host and inside
``artemis-api``), so a fix confined to ``populate_chromadb.py`` while
``populate_chromadb_medcpt.py`` keeps its own copy of ``DOMAIN_LIMITS`` is a no-op
for delivery. ``test_should_share_one_domain_table_between_the_two_populate_scripts``
pins that they are the same objects, not two tables that happen to agree today.
"""

from __future__ import annotations

import pytest

# The three standard Observation concepts that answer "Contraindication to
# clopidogrel". Every one sits above the 50,000-row slice boundary below.
CLOPIDOGREL_CONCEPT_IDS = frozenset({4248529, 4170410, 44811047})

# The last concept_id the 50,000-row Observation slice reached, measured 2026-09-09
# against synthea23m and against the live omop_concepts_medcpt collection.
OBSERVATION_SLICE_BOUNDARY_ID = 4144455

# The cap this change removes, kept here so the integration test can reproduce what
# the old query read without the module still carrying it.
RETIRED_OBSERVATION_CAP = 50000


def _row(concept_id, name="Clopidogrel contraindicated", domain="Observation"):
    """One row in the shape ``fetch_concepts`` returns."""
    return (concept_id, name, "SNOMED", "Clinical Finding", domain)


class _FakeCollection:
    """A collection that answers ``get``/``add``/``count`` and records what it was asked.

    ``drop_adds`` reproduces the ``chromadb`` behaviour the verification exists for:
    ``add`` returns without raising and the rows are not there afterwards.
    """

    def __init__(self, preloaded_ids=(), drop_adds=False):
        self._documents = {str(i): ("preloaded", {}) for i in preloaded_ids}
        self.drop_adds = drop_adds
        self.add_calls: list[list[str]] = []
        self.get_calls: list[list[str]] = []

    def count(self):
        return len(self._documents)

    def get(self, ids=None, include=None, **_kwargs):
        if ids is None:
            return {"ids": list(self._documents)}
        self.get_calls.append(list(ids))
        return {"ids": [i for i in ids if i in self._documents]}

    def add(self, ids, documents, metadatas):
        self.add_calls.append(list(ids))
        if self.drop_adds:
            return
        for concept_id, document, metadata in zip(ids, documents, metadatas):
            self._documents[concept_id] = (document, metadata)


def _metadata_for(row):
    return {
        "concept_id": row[0],
        "vocabulary_id": row[2],
        "concept_class_id": row[3],
        "domain_id": row[4],
    }


def _single_domain(monkeypatch, module, rows, domain="Observation", limit=None):
    """Point the module's sync loop at one domain served from ``rows``."""
    monkeypatch.setattr(module, "RELEVANT_DOMAINS", [domain])
    monkeypatch.setattr(module, "DOMAIN_LIMITS", {domain: limit})
    monkeypatch.setattr(
        module,
        "fetch_concepts",
        lambda requested_domain, requested_limit: rows if requested_domain == domain else [],
    )


def test_should_not_cap_observation_when_the_domain_table_is_read():
    import scripts.populate_chromadb as module

    assert module.DOMAIN_LIMITS["Observation"] is None


def test_should_cap_only_drug_when_the_domain_table_is_read():
    import scripts.populate_chromadb as module

    capped = {domain for domain, limit in module.DOMAIN_LIMITS.items() if limit is not None}
    assert capped == {"Drug"}
    assert module.DOMAIN_LIMITS["Drug"] == 100000

    # Every relevant domain states its own limit, so an unlisted domain is a KeyError
    # rather than a silent 50,000-row slice.
    assert set(module.DOMAIN_LIMITS) == set(module.RELEVANT_DOMAINS)
    assert not hasattr(module, "DEFAULT_LIMIT")


def test_should_emit_no_limit_clause_when_the_domain_is_uncapped():
    import scripts.populate_chromadb as module

    uncapped = module.concept_query("Observation", None)
    assert "LIMIT" not in uncapped.upper()

    capped = module.concept_query("Drug", 100000)
    assert capped.rstrip().endswith("LIMIT 100000")
    # The slice is only deterministic because of the ordering; the Drug cap is kept
    # byte-identical to today's on purpose.
    assert "ORDER BY concept_id" in capped
    assert capped.index("ORDER BY concept_id") < capped.index("LIMIT 100000")

    # `if limit:` made 0 mean "no limit". A zero or negative cap is a mistake, not a
    # request for the whole table.
    with pytest.raises(ValueError):
        module.concept_query("Observation", 0)
    with pytest.raises(ValueError):
        module.concept_query("Observation", -1)


def test_should_add_only_the_ids_the_collection_lacks_when_it_is_already_populated(monkeypatch):
    import scripts.populate_chromadb as module

    rows = [_row(4144455), _row(4170410), _row(4248529)]
    _single_domain(monkeypatch, module, rows)
    collection = _FakeCollection(preloaded_ids=[4144455, 4170410])

    report = module.sync_collection(collection, batch_size=5000, metadata_for=_metadata_for)

    # The old code returned here because the collection was non-empty.
    assert collection.add_calls == [["4248529"]]
    assert report == {"Observation": (3, 2, 1)}
    assert collection.count() == 3


def test_should_fail_loud_when_a_domain_ends_short_of_its_expected_count(monkeypatch):
    import scripts.populate_chromadb as module

    rows = [_row(4144455), _row(4170410), _row(4248529)]
    _single_domain(monkeypatch, module, rows)
    collection = _FakeCollection(preloaded_ids=[4144455, 4170410], drop_adds=True)

    with pytest.raises(RuntimeError) as raised:
        module.sync_collection(collection, batch_size=5000, metadata_for=_metadata_for)

    message = str(raised.value)
    assert "Observation" in message
    assert "3" in message  # expected
    assert "2" in message  # actually indexed


def test_should_fail_loud_when_the_collection_holds_more_than_the_domains_promised(monkeypatch):
    import scripts.populate_chromadb as module

    rows = [_row(4248529)]
    _single_domain(monkeypatch, module, rows)
    # A stray document from some other load: every domain reconciles, the total does not.
    collection = _FakeCollection(preloaded_ids=[4248529, 999999999])

    with pytest.raises(RuntimeError) as raised:
        module.sync_collection(collection, batch_size=5000, metadata_for=_metadata_for)

    message = str(raised.value)
    assert "1" in message and "2" in message


def test_should_share_one_domain_table_between_the_two_populate_scripts():
    import scripts.populate_chromadb as default_script
    import scripts.populate_chromadb_medcpt as medcpt_script

    # Production reads omop_concepts_medcpt. Two tables that merely agree today would
    # let the next cap change land in one collection and not the other.
    assert medcpt_script.DOMAIN_LIMITS is default_script.DOMAIN_LIMITS
    assert medcpt_script.RELEVANT_DOMAINS is default_script.RELEVANT_DOMAINS
    assert medcpt_script.fetch_concepts is default_script.fetch_concepts
    assert medcpt_script.sync_collection is default_script.sync_collection
    assert not hasattr(medcpt_script, "DEFAULT_LIMIT")


@pytest.mark.integration
def test_should_index_the_clopidogrel_concepts_the_50000_row_cap_dropped():
    """The real case, read from the real vocabulary rather than from a fixture."""
    import psycopg2

    import scripts.populate_chromadb as module
    from src.settings import settings

    capped = module.fetch_concepts("Observation", RETIRED_OBSERVATION_CAP)
    uncapped = module.fetch_concepts("Observation", module.DOMAIN_LIMITS["Observation"])
    capped_ids = {row[0] for row in capped}
    uncapped_ids = {row[0] for row in uncapped}

    # What the cap did: a concept_id slice, not a relevance slice.
    assert len(capped) == RETIRED_OBSERVATION_CAP
    assert max(capped_ids) == OBSERVATION_SLICE_BOUNDARY_ID
    assert capped_ids < uncapped_ids

    # The three concepts that answer "Contraindication to clopidogrel" are standard
    # and valid, and every one of them is above the boundary.
    connection = psycopg2.connect(settings.DATABASE_URL)
    try:
        cursor = connection.cursor()
        cursor.execute(
            f"SELECT concept_id FROM {settings.CDM_SCHEMA}.concept "
            "WHERE concept_id = ANY(%s) AND domain_id = 'Observation' "
            "AND standard_concept = 'S' AND invalid_reason IS NULL",
            (sorted(CLOPIDOGREL_CONCEPT_IDS),),
        )
        standard_and_valid = {row[0] for row in cursor.fetchall()}
        cursor.execute(
            f"SELECT count(*) FROM {settings.CDM_SCHEMA}.concept "
            "WHERE domain_id = 'Observation' AND standard_concept = 'S' "
            "AND invalid_reason IS NULL"
        )
        population = cursor.fetchone()[0]
        cursor.close()
    finally:
        connection.close()

    assert standard_and_valid == set(CLOPIDOGREL_CONCEPT_IDS)
    assert min(CLOPIDOGREL_CONCEPT_IDS) > OBSERVATION_SLICE_BOUNDARY_ID

    # The defect, and the fix, on the same two reads.
    assert CLOPIDOGREL_CONCEPT_IDS.isdisjoint(capped_ids)
    assert CLOPIDOGREL_CONCEPT_IDS <= uncapped_ids

    # The uncapped read is the whole standard population, not a larger slice of it.
    # Measured 2026-09-09: 132,423, i.e. 82,423 more than the cap admitted.
    assert len(uncapped) == population
    assert len(uncapped) - len(capped) == population - RETIRED_OBSERVATION_CAP


@pytest.mark.integration
def test_should_add_exactly_the_dropped_observation_concepts_to_a_capped_collection(monkeypatch):
    """Sync a collection in the state the live one is in, using the real vocabulary."""
    import scripts.populate_chromadb as module

    rows = module.fetch_concepts("Observation", module.DOMAIN_LIMITS["Observation"])
    already_indexed = [row[0] for row in rows[:RETIRED_OBSERVATION_CAP]]
    _single_domain(monkeypatch, module, rows)

    collection = _FakeCollection(preloaded_ids=already_indexed)
    report = module.sync_collection(collection, batch_size=5000, metadata_for=_metadata_for)

    expected, present, added = report["Observation"]
    assert present == RETIRED_OBSERVATION_CAP
    assert added == expected - RETIRED_OBSERVATION_CAP
    assert collection.count() == expected

    added_ids = {concept_id for call in collection.add_calls for concept_id in call}
    assert {str(i) for i in CLOPIDOGREL_CONCEPT_IDS} <= added_ids

    # And the guard fires on that same real state when the writes do not land.
    dropping = _FakeCollection(preloaded_ids=already_indexed, drop_adds=True)
    with pytest.raises(RuntimeError) as raised:
        module.sync_collection(dropping, batch_size=5000, metadata_for=_metadata_for)
    assert "Observation" in str(raised.value)
    assert str(RETIRED_OBSERVATION_CAP) in str(raised.value)
