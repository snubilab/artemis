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
    """Route the expander at a stub ATC collection and a stub OMOP connection."""
    def _install(name, distance):
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


def test_should_reject_a_small_class_that_has_no_therapeutic_parent_to_climb_to(atc, monkeypatch):
    """A correct-looking name that yields 2 ingredients is not a class. Since
    2026-10-08 its parent is tried instead (tests/test_atc_class_selection.py); with
    only the anatomical main group above it, there is nothing to try and the guard
    still rejects."""
    conn = atc(*DPP4[1:])
    monkeypatch.setattr(_Cursor, "fetchall", lambda _s: [(1,), (2,)])
    top = (21600673, "A", "ALIMENTARY TRACT AND METABOLISM", "ATC 1st")
    monkeypatch.setattr(dce, "atc_parent", lambda *_a: top)

    matched, ingredient_ids = dce.expand_drug_class_via_vocab(DPP4[0], conn, schema="cdm")

    assert matched is None
    assert ingredient_ids == []


# ── Rank-1 is not the only candidate ───────────────────────────────────────────
#
# For antidiabetic wording the nearest ATC entries are A10X / A10XX ('OTHER DRUGS USED
# IN DIABETES', 2 and 1 ingredients) at an exact distance tie, and A10 'DRUGS USED IN
# DIABETES' (84 ingredients) sits only a hair further away. Querying one result meant
# the <3-ingredient rule rejected A10X and A10 was never looked at, so the seed fell
# to the product path and shipped as two or three drugs. Rankings below are the
# observed ChromaDB output for the store's own seeds (atc_drug_classes, 2026-10-07).

A10X = (21600797, "A10X", "OTHER DRUGS USED IN DIABETES")
A10XX = (955112, "A10XX", "Other drugs used in diabetes")
A10 = (21600712, "A10", "DRUGS USED IN DIABETES")
A08AX = (21600695, "A08AX", "Other antiobesity drugs")
V06A = (21605343, "V06A", "DIET FORMULATIONS FOR TREATMENT OF OBESITY")
A08A = (21600680, "A08A", "ANTIOBESITY PREPARATIONS, EXCL. DIET PRODUCTS")
A10BX = (21600788, "A10BX", "Other blood glucose lowering drugs, excl. insulins")
A10BH = (21600783, "A10BH", "Dipeptidyl peptidase 4 (DPP-4) inhibitors")
L04AK = (954954, "L04AK", "Dihydroorotate dehydrogenase (DHODH) inhibitors")

INGREDIENTS_BY_CLASS = {
    A10X[0]: [1, 2],
    A10XX[0]: [1],
    A10[0]: [1503297, 1580747, 1597756, 1502905, 44785829],
    A08AX[0]: [1],
    A08A[0]: [1, 3, 4, 5],
    V06A[0]: [],
    A10BH[0]: INGREDIENTS,
    L04AK[0]: [7, 8],
    # Within threshold beside A10 in the first ranking below, so whether it is the same
    # class as A10 is asked (RFC-016 §4, C5: by ingredients, not by name).
    A10BX[0]: [1503297],
}


class _RankedCollection:
    """Answers with the observed ranking, truncated to ``n_results`` like Chroma."""

    def __init__(self, ranking):
        self._ranking = ranking

    def query(self, query_texts, n_results):
        top = self._ranking[:n_results]
        return {
            "documents": [[name for (_cid, _code, name), _d in top]],
            "metadatas": [[{"concept_id": cid, "concept_code": code}
                           for (cid, code, _n), _d in top]],
            "distances": [[d for _c, d in top]],
        }


class _ClassCursor:
    """Returns the ingredients of whichever ATC concept the expander asks about."""

    def __init__(self):
        self.asked = []
        self._rows = []

    def execute(self, _sql, params=None):
        atc_id = params[0]
        self.asked.append(atc_id)
        self._rows = [(i,) for i in INGREDIENTS_BY_CLASS[atc_id]]

    def fetchall(self):
        return self._rows


class _ClassConn:
    def __init__(self):
        self.cur = _ClassCursor()

    def cursor(self):
        return self.cur


@pytest.fixture
def ranked_atc(monkeypatch):
    # Since 2026-10-08 a class too small to be one is replaced by its ATC parent.
    parents = {A10X[0]: (*A10, "ATC 2nd"), A10XX[0]: (*A10X, "ATC 3rd"),
               A08AX[0]: (*A08A, "ATC 3rd")}

    def _install(ranking):
        monkeypatch.setattr(dce, "atc_parent", lambda _c, _s, cid: parents.get(cid))
        collection = _RankedCollection(ranking)
        monkeypatch.setattr("src.utils.vector.get_chroma_client",
                            lambda: type("C", (), {"get_collection": lambda _s, _n: collection})())
        return _ClassConn()
    return _install


def test_should_reach_the_diabetes_class_when_rank_one_has_fewer_than_three_ingredients(ranked_atc):
    # "Anti-diabetic medication": A10X 0.3977 (2), A10XX 0.3977 (1), A10 0.4054 (84).
    # A10X is rank 1 and too small, and its parent is A10. (A10XX holds 1 of A10X's 2
    # ingredients, so it is a different class, and not the 2/3 needed to replace it.)
    conn = ranked_atc([(A10X, 0.3977), (A10XX, 0.3977), (A10, 0.4054),
                       (A10BX, 0.7116)])

    matched, ingredient_ids = dce.expand_drug_class_via_vocab(
        "Anti-diabetic medication", conn, schema="cdm")

    assert matched == "DRUGS USED IN DIABETES"
    assert ingredient_ids == INGREDIENTS_BY_CLASS[A10[0]]


def test_should_climb_from_the_residual_antiobesity_bucket_not_jump_to_a_far_class(ranked_atc):
    # "Anti-obesity drug": A08AX 0.6588 (1), V06A 0.7016 (0), A10X 0.8125, A10XX 0.8125,
    # A10 0.8353 (84). Until 2026-10-08 this returned nothing: A08AX was too small and
    # the old rule moved on to the next candidate instead of up to A08A. A10 has enough
    # ingredients but sits past 0.75 -- the distance gate still keeps it out.
    conn = ranked_atc([(A08AX, 0.6588), (V06A, 0.7016), (A10X, 0.8125), (A10XX, 0.8125),
                       (A10, 0.8353)])

    matched, ingredient_ids = dce.expand_drug_class_via_vocab(
        "Anti-obesity drug", conn, schema="cdm")

    assert matched == "ANTIOBESITY PREPARATIONS, EXCL. DIET PRODUCTS"
    assert ingredient_ids == INGREDIENTS_BY_CLASS[A08A[0]]
    assert A10[0] not in conn.cur.asked, "a class beyond the threshold must not be expanded"


def test_should_keep_rank_one_when_rank_one_already_passes(ranked_atc):
    # "DPP-4 inhibitors": A10BH 0.4557 (8), then L04AK 0.9150 -- nothing past rank 1 is consulted.
    conn = ranked_atc([(A10BH, 0.4557), (L04AK, 0.9150)])

    matched, ingredient_ids = dce.expand_drug_class_via_vocab(
        "DPP-4 inhibitors", conn, schema="cdm")

    assert matched == "Dipeptidyl peptidase 4 (DPP-4) inhibitors"
    assert ingredient_ids == INGREDIENTS
    assert set(conn.cur.asked) == {A10BH[0]}
