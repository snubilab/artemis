"""The ATC distance threshold must admit a correct class match.

`expand_drug_class_via_vocab` accepts an ATC class only when the ChromaDB distance
is under `AGENT2_ATC_DISTANCE_THRESHOLD`. At 0.4 that gate rejected every match
that was not a near-verbatim name. From the 2026-08-12 six-trial remap log, all 31
decisions sorted by distance:

    accepted  4, max distance 0.134
    rejected 27, min distance 0.453

and the rejected 0.453-0.735 band is correct matches, every one:

    0.456  DPP-4 inhibitors        -> Dipeptidyl peptidase 4 (DPP-4) inhibitors
    0.462  SGLT-2 inhibitors       -> Sodium-glucose co-transporter 2 (SGLT2) inhibitors
    0.618  GLP-1 receptor agonists -> Glucagon-like peptide-1 (GLP-1) analogues
    0.636  OADs/Insulin            -> INSULINS AND ANALOGUES

The first genuinely wrong match in that region is at 0.760
(`Concomitant strong CYP3A inhibitors` -> `Phosphatidylinositol-3-kinase (Pi3K)
inhibitors`), so 0.75 admits 14 correct matches and no incorrect one.

Cost of the old value, measured against gold: `[TROY intervention] DPP4 inhibitors`
scored recall 0.04 over a 2093-concept gold closure while ATC A10BH expands to 8 of
its 10 gold ingredients with nothing extra.

The distances here are the observed ones, not invented: a synthetic value would not
have caught this, since the defect is entirely in where the boundary sits.
"""
import pytest

from src.agents.agent2 import drug_class_expander as dce

# (query text, matched ATC name, observed ChromaDB distance) straight from the remap log
DPP4 = ("DPP-4 inhibitors", "Dipeptidyl peptidase 4 (DPP-4) inhibitors", 0.456)
GLP1 = ("GLP-1 receptor agonists", "Glucagon-like peptide-1 (GLP-1) analogues", 0.618)
INSULIN = ("OADs/Insulin", "INSULINS AND ANALOGUES", 0.636)
CYP3A = ("Concomitant strong CYP3A inhibitors",
         "Phosphatidylinositol-3-kinase (Pi3K) inhibitors", 0.760)
NAIVE = ("Naive", "VARIOUS", 1.396)

INGREDIENTS = [40239216, 43013884, 40166035, 1580747, 19122137]


class _Collection:
    def __init__(self, name, distance):
        self._name, self._distance = name, distance

    def query(self, query_texts, n_results):
        return {
            "documents": [[self._name]],
            "metadatas": [[{"concept_id": 21600783, "concept_code": "A10BH"}]],
            "distances": [[self._distance]],
        }


class _Cursor:
    def execute(self, *_args, **_kwargs):
        pass

    def fetchall(self):
        return [(i,) for i in INGREDIENTS]


class _Conn:
    def cursor(self):
        return _Cursor()


@pytest.fixture
def atc(monkeypatch):
    """Route the expander at a stub ATC collection and a stub OMOP connection.

    UMLS is stubbed to find nothing, matching production: the remap logged
    "MRREL/MRCONSO SQLite not available" 37 times, so ATC is the only live path.
    """
    def _install(name, distance):
        monkeypatch.setattr(dce, "expand_drug_class_via_umls",
                            lambda *a, **k: (None, []))
        collection = _Collection(name, distance)
        monkeypatch.setattr("src.utils.vector.get_chroma_client",
                            lambda: type("C", (), {"get_collection": lambda _s, _n: collection})())
        return _Conn()
    return _install


@pytest.mark.parametrize("case", [DPP4, GLP1, INSULIN],
                         ids=lambda c: c[0].replace(" ", "-"))
def test_should_accept_the_class_when_the_match_is_correct_at_its_observed_distance(case, atc):
    text, name, distance = case
    conn = atc(name, distance)

    matched, ingredient_ids = dce.expand_drug_class_via_vocab(text, conn, schema="cdm")

    assert matched == name, (
        f"'{text}' -> '{name}' at distance {distance} was rejected; this is a correct "
        f"ATC class match and the gate is what stands between it and the ingredients"
    )
    assert ingredient_ids == INGREDIENTS


@pytest.mark.parametrize("case", [CYP3A, NAIVE], ids=lambda c: c[0].split()[0])
def test_should_still_reject_the_class_when_the_match_is_wrong(case, atc):
    """The gate earns its place above 0.75 — these two are genuinely wrong matches."""
    text, name, distance = case
    conn = atc(name, distance)

    matched, ingredient_ids = dce.expand_drug_class_via_vocab(text, conn, schema="cdm")

    assert matched is None, f"'{text}' -> '{name}' at {distance} should not be accepted"
    assert ingredient_ids == []


def test_should_reject_a_match_that_expands_to_fewer_than_three_ingredients(atc, monkeypatch):
    """A correct-looking name that yields 2 ingredients is not a class. Unchanged by
    the threshold move, and worth pinning so raising it does not weaken this guard."""
    conn = atc(*DPP4[1:])
    monkeypatch.setattr(_Cursor, "fetchall", lambda _s: [(1,), (2,)])

    matched, ingredient_ids = dce.expand_drug_class_via_vocab(DPP4[0], conn, schema="cdm")

    assert matched is None
    assert ingredient_ids == []
