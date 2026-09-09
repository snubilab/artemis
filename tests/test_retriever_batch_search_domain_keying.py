"""`batch_search` is asked (text, domain_hint) and must not answer on text alone.

The hint is not decoration: it becomes ChromaDB's ``where={"domain_id": hint}``
filter, so the same expanded text under two hints is two different searches over
two different candidate pools, scored under two different `domain_hint` values.
Returning ``Dict[str, List[CandidateConcept]]`` collapsed both into one key and
the later domain group overwrote the earlier one silently.

That pool is a hard short-circuit downstream — `agent2/workflow.py:738-745` logs
"skipping primary ChromaDB search" and uses it as the ENTIRE primary candidate
set — so the overwritten criterion was mapped against a pool retrieved under a
domain filter it never asked for, and `_score_candidates` had already run with
the *writing* group's hint, so the +0.50 domain-mismatch penalty
(`retriever.py:288-289`) never fired on the mismatch it exists for.

Two more writes had the same shape and the same fix: the ChromaDB-error path and
the empty-response path both wrote ``result[qt] = []``, so one failing domain
group erased another group's real results under a shared text.
"""
import pytest

from src.agents.agent2.retriever import ConceptRetriever

DRUG_ROW = {
    "id": "1503297",
    "name": "metformin",
    "domain_id": "Drug",
    "vocabulary_id": "RxNorm",
    "concept_class_id": "Ingredient",
}
CONDITION_ROW = {
    "id": "201826",
    "name": "Type 2 diabetes mellitus",
    "domain_id": "Condition",
    "vocabulary_id": "SNOMED",
    "concept_class_id": "Disorder",
}


class FakeCollection:
    """Answers per `where={"domain_id": ...}`, the way the real one does."""

    def __init__(self, rows_by_hint, raise_for=(), empty_for=()):
        self.rows_by_hint = rows_by_hint
        self.raise_for = set(raise_for)
        self.empty_for = set(empty_for)
        self.calls = []

    def query(self, query_texts, n_results, include, where=None):
        hint = (where or {}).get("domain_id")
        self.calls.append((tuple(query_texts), hint))
        if hint in self.raise_for:
            raise RuntimeError(f"chroma exploded for {hint}")
        if hint in self.empty_for:
            return {"ids": []}
        row = self.rows_by_hint[hint]
        n = len(query_texts)
        return {
            "ids": [[row["id"]] for _ in range(n)],
            "metadatas": [[{
                "domain_id": row["domain_id"],
                "vocabulary_id": row["vocabulary_id"],
                "concept_class_id": row["concept_class_id"],
            }] for _ in range(n)],
            "distances": [[50.0] for _ in range(n)],
            "documents": [[row["name"]] for _ in range(n)],
        }


def _retriever(collection) -> ConceptRetriever:
    r = ConceptRetriever.__new__(ConceptRetriever)
    r.concept_weights = {}
    r.collection = collection
    return r


@pytest.fixture
def two_hints():
    return FakeCollection({"Drug": DRUG_ROW, "Condition": CONDITION_ROW})


class TestSameTextUnderTwoDomainHints:
    def test_should_keep_both_results_when_one_text_is_queried_under_two_hints(self, two_hints):
        r = _retriever(two_hints)
        results = r.batch_search(
            ["metformin", "metformin"], n_results=5, domain_hints=["Drug", "Condition"],
        )
        assert len(results.by_index) == 2
        assert [c.concept_id for c in results.by_index[0]] == [1503297], \
            "position 0 asked under the Drug filter and must get the Drug pool"
        assert [c.concept_id for c in results.by_index[1]] == [201826], \
            "position 1 asked under the Condition filter and must get the Condition pool"

    def test_should_key_by_the_pair_the_query_was_made_under(self, two_hints):
        r = _retriever(two_hints)
        results = r.batch_search(
            ["metformin", "metformin"], n_results=5, domain_hints=["Drug", "Condition"],
        )
        assert [c.domain_id for c in results[("metformin", "Drug")]] == ["Drug"]
        assert [c.domain_id for c in results[("metformin", "Condition")]] == ["Condition"]
        assert results.get(("metformin", "Observation"), []) == []

    def test_should_record_the_text_whose_key_is_ambiguous(self, two_hints):
        r = _retriever(two_hints)
        results = r.batch_search(
            ["metformin", "metformin"], n_results=5, domain_hints=["Drug", "Condition"],
        )
        assert results.colliding_texts == ["metformin"], \
            "a text-keyed read on this batch cannot be correct; it must not be silent"

    def test_should_not_call_a_text_ambiguous_when_the_hint_is_the_same(self, two_hints):
        r = _retriever(two_hints)
        results = r.batch_search(
            ["metformin", "metformin"], n_results=5, domain_hints=["Drug", "Drug"],
        )
        assert results.colliding_texts == []
        assert [c.concept_id for c in results.by_index[0]] == [1503297]
        assert [c.concept_id for c in results.by_index[1]] == [1503297]


class TestOneFailingGroupDoesNotEraseAnother:
    def test_should_not_let_a_chromadb_error_blank_another_hints_results(self):
        """Group order is first-appearance, so Condition runs first and succeeds;
        the Drug group then raises. Its `result[qt] = []` used to land on the same
        text key and wipe the Condition pool."""
        collection = FakeCollection(
            {"Drug": DRUG_ROW, "Condition": CONDITION_ROW}, raise_for=("Drug",),
        )
        r = _retriever(collection)
        results = r.batch_search(
            ["metformin", "metformin"], n_results=5, domain_hints=["Condition", "Drug"],
        )
        assert [c.concept_id for c in results.by_index[0]] == [201826]
        assert results.by_index[1] == []

    def test_should_not_let_an_empty_response_blank_another_hints_results(self):
        collection = FakeCollection(
            {"Drug": DRUG_ROW, "Condition": CONDITION_ROW}, empty_for=("Drug",),
        )
        r = _retriever(collection)
        results = r.batch_search(
            ["metformin", "metformin"], n_results=5, domain_hints=["Condition", "Drug"],
        )
        assert [c.concept_id for c in results.by_index[0]] == [201826]
        assert results.by_index[1] == []


class TestBackwardCompatibleTextKeyedView:
    def test_should_still_answer_a_text_key_for_the_existing_consumer(self, two_hints):
        """tte_service.py:4800 does `batch_results.get(text, [])`. That consumer is
        unchanged by this fix and must keep working on the non-colliding case."""
        r = _retriever(two_hints)
        results = r.batch_search(
            ["metformin", "type 2 diabetes"], n_results=5,
            domain_hints=["Drug", "Condition"],
        )
        assert [c.concept_id for c in results.get("metformin", [])] == [1503297]
        assert [c.concept_id for c in results.get("type 2 diabetes", [])] == [201826]
        assert results.get("never queried", []) == []

    def test_should_behave_as_a_mapping(self, two_hints):
        r = _retriever(two_hints)
        results = r.batch_search(["metformin"], n_results=5, domain_hints=["Drug"])
        assert "metformin" in results
        assert len(results) == 1
        assert list(results.keys()) == ["metformin"]

    def test_should_return_an_empty_result_for_no_queries(self, two_hints):
        r = _retriever(two_hints)
        results = r.batch_search([], n_results=5)
        assert len(results) == 0
        assert results.by_index == []
        assert two_hints.calls == []

    def test_should_default_a_missing_hint_to_none(self, two_hints):
        """`domain_hints` may be shorter than `query_texts`; the tail is unhinted
        and must be queried with no `where` clause."""
        collection = FakeCollection({None: DRUG_ROW, "Drug": DRUG_ROW})
        r = _retriever(collection)
        results = r.batch_search(
            ["metformin", "aspirin"], n_results=5, domain_hints=["Drug"],
        )
        assert ("aspirin", None) in results.by_pair
        assert (None,) in [(hint,) for _, hint in collection.calls]
