"""How `expand_drug_class_via_vocab` picks an ATC class and what it returns from it.

Each scenario below is a failure observed on the 2026-09-22 verify5 store's Drug class
seeds (diagnosis 2026-10-08), reduced to the ranking or ingredient structure that
produced it:

- broader parent outranks the right child: "Systemic corticosteroid" -> H02 (0.2752,
  carries the antiadrenals ketoconazole/osilodrostat/trilostane via H02C) with H02A
  "..., PLAIN" second at 0.3194.
- identical names in one subtree: B01 and B01A are both "ANTITHROMBOTIC AGENTS".
- a too-small class rejected without looking at its parent: "Anti-obesity drug" ->
  A08AX "Other antiobesity drugs" (1 ingredient), while A08A holds the class.
- a route-specific small class that climbing would destroy: "Inhaled insulin" ->
  A10AF "Insulins and analogues for inhalation" (1 ingredient).
- combination codes leaking partners: A08AA62 bupropion+naltrexone puts bupropion
  under A08; A08AA56 ephedrine combinations put ephedrine there.

Selection rules and DB access are separate functions so the rules are tested without a
database; the DB-backed behaviour is pinned against the local vocabulary at the end.
"""
import pytest

from src.agents.agent2 import drug_class_expander as dce
from src.agents.agent2.drug_class_expander import AtcHit

H02 = AtcHit(21602722, "H02", "CORTICOSTEROIDS FOR SYSTEMIC USE", 0.2752)
H02A = AtcHit(21602723, "H02A", "CORTICOSTEROIDS FOR SYSTEMIC USE, PLAIN", 0.3194)
H02B = AtcHit(21602745, "H02B", "CORTICOSTEROIDS FOR SYSTEMIC USE, COMBINATIONS", 0.3282)
H02AB = AtcHit(21602728, "H02AB", "Glucocorticoids", 0.3300)
S02B = AtcHit(1, "S02B", "CORTICOSTEROIDS", 0.3586)
S03B = AtcHit(2, "S03B", "CORTICOSTEROIDS", 0.3586)
B01 = AtcHit(21600960, "B01", "ANTITHROMBOTIC AGENTS", 0.5738)
B01A = AtcHit(21600961, "B01A", "ANTITHROMBOTIC AGENTS", 0.5738)
B01AX = AtcHit(21601027, "B01AX", "Other antithrombotic agents", 0.5976)

THRESHOLD = 0.75

# Ingredient counts from the local vocabulary after combination-partner removal:
# H02A keeps 20 of H02's 23 (H02 = H02A + the antiadrenals H02C); A10AE keeps 6 of
# A10A's 29 (one duration among four).
SIZES = {"H02": 23, "H02A": 20, "H02B": 0, "H02AB": 17, "A10A": 29, "A10AE": 6,
         "A10AC": 8, "A10AB": 14, "S01C": 22, "X01": 9, "X01A": 9}


def _share(child, parent):
    return SIZES[child.code] / SIZES[parent.code]


def _select(hits, threshold=THRESHOLD, band=0.10, gap=0.10):
    return dce.select_atc_class(hits, threshold, band, gap, share_of_parent=_share)


# ── B: selection ──────────────────────────────────────────────────────────────

def test_should_take_the_closest_class_when_it_is_within_threshold():
    assert _select([B01AX, H02]) == H02


def test_should_prefer_the_descendant_whose_name_extends_the_best_hit_when_both_are_within_reach():
    chosen = _select([H02, H02A, H02B])

    assert chosen.code == "H02A", (
        "H02 'CORTICOSTEROIDS FOR SYSTEMIC USE' also holds the antiadrenals (H02C); its "
        "child H02A '..., PLAIN' is the same wording made specific and is within threshold"
    )


def test_should_keep_the_parent_when_the_extending_child_holds_a_minority_of_its_ingredients():
    # Observed for the query "insulin": A10A 0.4527, then its children, every one of whose
    # names extends "INSULINS AND ANALOGUES" -- A10AE long-acting 0.5974, A10AC 0.6003,
    # A10AB 0.6061. The closest child is one duration among four, not insulin made specific.
    a10a = AtcHit(21600713, "A10A", "INSULINS AND ANALOGUES", 0.4527)
    a10ae = AtcHit(21600759, "A10AE", "Insulins and analogues for injection, long-acting", 0.5974)
    a10ac = AtcHit(21600729, "A10AC",
                   "Insulins and analogues for injection, intermediate-acting", 0.6003)
    a10ab = AtcHit(21600714, "A10AB", "Insulins and analogues for injection, fast-acting", 0.6061)

    assert _select([a10a, a10ae, a10ac, a10ab]) == a10a


def test_should_keep_the_best_hit_when_no_descendant_extends_its_name():
    # H02AB "Glucocorticoids" is a descendant within threshold but names something else.
    assert _select([H02, H02AB]).code == "H02"


def test_should_not_prefer_an_extending_name_outside_the_best_hit_subtree():
    other = AtcHit(9, "S01C", "CORTICOSTEROIDS FOR SYSTEMIC USE, OPHTHALMIC", 0.30)
    assert _select([H02, other]).code == "H02"


def test_should_ignore_an_extending_descendant_beyond_threshold():
    far = AtcHit(H02A.concept_id, "H02A", H02A.name, 0.80)
    assert _select([H02, far]).code == "H02"


def test_should_treat_identical_names_in_one_subtree_as_one_candidate():
    merged = dce.merge_identical_names([B01, B01A, B01AX])

    assert [h.code for h in merged] == ["B01", "B01AX"]


def test_should_keep_identical_names_in_different_subtrees_apart():
    merged = dce.merge_identical_names([S02B, S03B])

    assert [h.code for h in merged] == ["S02B", "S03B"]


def test_should_measure_the_margin_against_the_next_distinct_class_not_a_duplicate_name():
    # Rank 1 just over threshold; its identical-name parent sits at the same distance.
    a = AtcHit(10, "X01", "SOME CLASS", 0.78)
    a_child = AtcHit(11, "X01A", "SOME CLASS", 0.78)
    other = AtcHit(12, "Y02", "ANOTHER", 0.95)

    assert _select([a, a_child, other]).code == "X01"


def test_should_accept_rank_one_just_over_threshold_when_the_gap_to_rank_two_is_large():
    first = AtcHit(21600783, "A10BH", "Dipeptidyl peptidase 4 (DPP-4) inhibitors", 0.78)
    second = AtcHit(5, "L04AC", "Interleukin inhibitors", 0.92)

    assert _select([first, second]) == first


def test_should_reject_rank_one_just_over_threshold_when_the_gap_to_rank_two_is_small():
    first = AtcHit(1, "L01EM", "Phosphatidylinositol-3-kinase (Pi3K) inhibitors", 0.78)
    second = AtcHit(2, "L01EF", "Cyclin-dependent kinase (CDK) inhibitors", 0.82)

    assert _select([first, second]) is None


def test_should_reject_rank_one_far_over_threshold_whatever_the_gap():
    first = AtcHit(1, "B01AX", "Other antithrombotic agents", 0.95)
    second = AtcHit(2, "B01", "ANTITHROMBOTIC AGENTS", 1.40)

    assert _select([first, second]) is None


def test_should_reject_when_there_are_no_hits():
    assert _select([]) is None


# ── C: ingredients of a class ─────────────────────────────────────────────────

def test_should_drop_ingredients_that_reach_the_class_only_as_combination_partners():
    # bupropion: on its own elsewhere (antidepressant), never on its own under A08.
    kept = dce.drop_combination_partners(
        ingredients=[10, 20, 30], alone_in_class={10, 30}, alone_anywhere={10, 20, 30})

    assert kept == [10, 30]


def test_should_keep_an_ingredient_that_never_exists_on_its_own():
    # insulin aspart protamine: only ever sold premixed, so premixing is what it is.
    kept = dce.drop_combination_partners(
        ingredients=[10, 40], alone_in_class={10}, alone_anywhere={10})

    assert kept == [10, 40]


# ── C: climbing and the route qualifier ───────────────────────────────────────

A08AX = AtcHit(21600695, "A08AX", "Other antiobesity drugs", 0.6588)
A10AF = AtcHit(21600742, "A10AF", "Insulins and analogues for inhalation", 0.3583)
PARENTS = {
    21600695: (21600680, "A08A", "ANTIOBESITY PREPARATIONS, EXCL. DIET PRODUCTS", "ATC 3rd"),
    21600680: (21600679, "A08", "ANTIOBESITY PREPARATIONS, EXCL. DIET PRODUCTS", "ATC 2nd"),
    21600679: (21600676, "A", "ALIMENTARY TRACT AND METABOLISM", "ATC 1st"),
    21600742: (21600713, "A10A", "INSULINS AND ANALOGUES", "ATC 3rd"),
}
INGREDIENTS = {21600695: [1], 21600680: [1, 2, 3, 4], 21600679: [1, 2, 3, 4],
               21600742: [7], 21600713: [7, 8, 9, 10], 21600676: list(range(100))}


@pytest.fixture
def expander(monkeypatch):
    """Stub the collection, the class ingredients and the parent lookup."""
    asked = []

    def _install(hits, ingredients=INGREDIENTS):
        monkeypatch.setattr(dce, "expand_drug_class_via_umls", lambda *a, **k: (None, []))

        class _Collection:
            def query(self, query_texts, n_results):
                top = hits[:n_results]
                return {"documents": [[h.name for h in top]],
                        "metadatas": [[{"concept_id": h.concept_id, "concept_code": h.code}
                                       for h in top]],
                        "distances": [[h.distance for h in top]]}

        def _get(_self, name):
            asked.append(name)
            return _Collection()

        monkeypatch.setattr("src.utils.vector.get_chroma_client",
                            lambda: type("C", (), {"get_collection": _get})())
        monkeypatch.setattr(dce, "class_ingredients", lambda _c, _s, cid: list(ingredients[cid]))
        monkeypatch.setattr(dce, "atc_parent", lambda _c, _s, cid: PARENTS.get(cid))
        return type("Conn", (), {"cursor": lambda _s: None})()
    _install.asked = asked
    return _install


def test_should_climb_to_the_parent_when_the_class_is_too_small(expander):
    conn = expander([A08AX])

    name, ids = dce.expand_drug_class_via_vocab("Anti-obesity drug", conn, schema="cdm")

    assert name == "ANTIOBESITY PREPARATIONS, EXCL. DIET PRODUCTS"
    assert ids == [1, 2, 3, 4]


def test_should_not_climb_when_the_seed_states_a_route(expander):
    conn = expander([A10AF])

    name, ids = dce.expand_drug_class_via_vocab("Inhaled insulin", conn, schema="cdm")

    assert name == "Insulins and analogues for inhalation", (
        "climbing to A10A would replace 'inhaled insulin' with every insulin"
    )
    assert ids == [7]


def test_should_give_up_when_a_route_qualified_class_has_no_ingredients(expander):
    conn = expander([A10AF], ingredients={**INGREDIENTS, 21600742: []})

    assert dce.expand_drug_class_via_vocab("Inhaled insulin", conn, schema="cdm") == (None, [])


def test_should_not_climb_into_the_anatomical_main_group(expander):
    small = {**INGREDIENTS, 21600680: [1], 21600679: [1]}
    conn = expander([A08AX], ingredients=small)

    assert dce.expand_drug_class_via_vocab("Anti-obesity drug", conn, schema="cdm") == (None, [])


def test_should_report_the_atc_name_not_the_indexed_document(expander, monkeypatch):
    enriched = AtcHit(21600783, "A10BH",
                      "Dipeptidyl peptidase 4 (DPP-4) inhibitors; "
                      "Dipeptidyl peptidase IV inhibitor",
                      0.40)
    conn = expander([enriched], ingredients={21600783: [1, 2, 3]})

    class _Collection:
        def query(self, query_texts, n_results):
            return {"documents": [[enriched.name]],
                    "metadatas": [[{"concept_id": 21600783, "concept_code": "A10BH",
                                    "concept_name": "Dipeptidyl peptidase 4 (DPP-4) inhibitors"}]],
                    "distances": [[0.40]]}

    monkeypatch.setattr("src.utils.vector.get_chroma_client",
                        lambda: type("C", (), {"get_collection": lambda _s, _n: _Collection()})())

    name, ids = dce.expand_drug_class_via_vocab("DPP-IV inhibitors", conn, schema="cdm")

    assert name == "Dipeptidyl peptidase 4 (DPP-4) inhibitors"
    assert ids == [1, 2, 3]


# ── D: which collection is read ───────────────────────────────────────────────

def test_should_read_the_production_collection_when_none_is_configured(expander, monkeypatch):
    monkeypatch.delenv("AGENT2_ATC_COLLECTION", raising=False)
    conn = expander([H02A], ingredients={H02A.concept_id: [1, 2, 3]})

    dce.expand_drug_class_via_vocab("Systemic corticosteroid", conn, schema="cdm")

    assert expander.asked == ["atc_drug_classes"]


def test_should_read_the_configured_collection_when_one_is_set(expander, monkeypatch):
    monkeypatch.setenv("AGENT2_ATC_COLLECTION", "atc_drug_classes_v2")
    conn = expander([H02A], ingredients={H02A.concept_id: [1, 2, 3]})

    dce.expand_drug_class_via_vocab("Systemic corticosteroid", conn, schema="cdm")

    assert expander.asked == ["atc_drug_classes_v2"]


# ── against the local vocabulary ──────────────────────────────────────────────

def _vocab_cursor():
    psycopg2 = pytest.importorskip("psycopg2")
    from src.settings import settings
    try:
        conn = psycopg2.connect(settings.DATABASE_URL, connect_timeout=3)
    except psycopg2.OperationalError as e:
        pytest.skip(f"OMOP vocabulary unreachable: {e}")
    return conn, conn.cursor(), settings.CDM_SCHEMA


def _class_and_names(cur, schema, code):
    cur.execute(f"SELECT concept_id FROM {schema}.concept WHERE vocabulary_id='ATC' "
                f"AND concept_code=%s AND invalid_reason IS NULL", (code,))
    class_id = cur.fetchone()[0]
    ids = dce.class_ingredients(cur, schema, class_id)
    cur.execute(f"SELECT concept_name FROM {schema}.concept WHERE concept_id = ANY(%s)", (ids,))
    return class_id, {r[0] for r in cur.fetchall()}


@pytest.mark.integration
def test_should_drop_combination_partners_from_the_antiobesity_class_against_the_vocabulary():
    conn, cur, schema = _vocab_cursor()
    try:
        _, names = _class_and_names(cur, schema, "A08A")
    finally:
        conn.close()

    assert "bupropion" not in names and "ephedrine" not in names
    assert {"orlistat", "phentermine", "lorcaserin", "sibutramine"} <= names


@pytest.mark.integration
def test_should_keep_every_insulin_and_drop_glp1_partners_from_the_insulin_class():
    conn, cur, schema = _vocab_cursor()
    try:
        _, names = _class_and_names(cur, schema, "A10A")
    finally:
        conn.close()

    assert {"insulin isophane", "insulin, regular, human", "insulin glargine",
            "insulin aspart protamine, human"} <= names
    assert "liraglutide" not in names and "lixisenatide" not in names


@pytest.mark.integration
def test_should_find_the_parent_class_in_the_vocabulary():
    conn, cur, schema = _vocab_cursor()
    try:
        class_id, _ = _class_and_names(cur, schema, "A08AX")
        parent = dce.atc_parent(cur, schema, class_id)
    finally:
        conn.close()

    assert parent[1:] == ("A08A", "ANTIOBESITY PREPARATIONS, EXCL. DIET PRODUCTS", "ATC 3rd")


# ── margin defaults, calibrated 2026-10-08 ────────────────────────────────────
#
# Every over-threshold rank 1 among the store's 40 production ATC query texts, on the
# v2 collection (rank 1 distance, gap to the next distinct class, verdict):
#   J04AM 0.7727 gap 0.051 wrong   ('treated with specific drugs')
#   B01   0.8395 gap 0.007 broader ('Anticoagulants')
#   L01EM 0.8593 gap 0.075 wrong   ('Concomitant therapy with strong CYP3A inhibitors')
#   J01ED 0.9112 gap 0.031 wrong   ('long-acting analogue')
#   B01AX 0.9502 gap 0.023 wrong   ('Oral anticoagulant therapy')
#   A10BJ 1.0272 gap 0.056 broader (compound 'DPP-4 inhibitor within 3 months + ...')
#   H01AA 1.0732 gap 0.294 wrong   ('human NPH')
# No correct match sits over the threshold once the v2 index is used. On the old index
# the only one was 'DPP-IV inhibitors' -> A10BH 0.7785 with gap 0.059, which J04AM's
# 0.051 sits too close to for any gap to separate. The known false match in its
# 2026-08-12 wording, 'Concomitant strong CYP3A inhibitors', is L01EM 0.7604 with the next
# class 0.0964 away -- inside the band, so the gap alone keeps it out. The defaults
# admit an isolated rank 1 only within 0.05 of the threshold and 0.15 clear of the next
# class: nothing in this data, with 0.05 to spare over the widest wrong gap.

PI3K = "Phosphatidylinositol-3-kinase (Pi3K) inhibitors"
CDK = "Cyclin-dependent kinase (CDK) inhibitors"


def _defaults(hits):
    return dce.select_atc_class(hits, THRESHOLD, share_of_parent=_share)


def test_should_reject_the_cyp3a_false_match_at_the_calibrated_defaults():
    assert _defaults([AtcHit(1, "L01EM", PI3K, 0.8593),
                      AtcHit(2, "L01EF", CDK, 0.9340)]) is None


def test_should_reject_the_cyp3a_false_match_in_its_original_wording_at_the_calibrated_defaults():
    assert _defaults([AtcHit(1, "L01EM", PI3K, 0.7604),
                      AtcHit(2, "L01EF", CDK, 0.8568)]) is None


def test_should_reject_the_nearest_wrong_over_threshold_match_at_the_calibrated_defaults():
    tb = "Combinations of drugs for treatment of tuberculosis"
    assert _defaults([AtcHit(1, "J04AM", tb, 0.7727),
                      AtcHit(2, "N07", "OTHER NERVOUS SYSTEM DRUGS", 0.8238)]) is None


def test_should_accept_an_isolated_rank_one_just_over_threshold_at_the_calibrated_defaults():
    first = AtcHit(1, "A10BH", "Dipeptidyl peptidase 4 (DPP-4) inhibitors", 0.78)

    assert _defaults([first, AtcHit(2, "L04AC", "Interleukin inhibitors", 0.95)]) == first


def test_should_reject_an_over_threshold_rank_one_when_no_runner_up_shows_it_is_isolated():
    # The margin rule needs evidence that nothing else is near; one result is not that.
    assert _defaults([AtcHit(1, "L01EM", PI3K, 0.760)]) is None
