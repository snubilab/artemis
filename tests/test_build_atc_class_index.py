"""The equivalence rule that borrows SNOMED class names into the ATC index.

Two classes are the same class when they hold the same ingredients, not when their
names look alike. The cases are reduced from the local vocabulary (synthea23m):
SNOMED 'Dipeptidyl peptidase IV inhibitor' holds 6 ingredients, all inside ATC A10BH,
whose other 2 (evogliptin, gemigliptin) SNOMED's substance hierarchy has no node for.
"""
import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "build_atc_class_index.py"
spec = importlib.util.spec_from_file_location("build_atc_class_index", SCRIPT)
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)

NAMES = {100: "Dipeptidyl peptidase IV inhibitor", 200: "Peptide hydrolase inhibitor",
         300: "Glucagon-like peptide 1 receptor agonist"}


def test_should_pair_classes_whose_ingredients_match_over_what_snomed_can_express():
    atc = {1: {1, 2, 3, 4, 5, 6, 7, 8}}          # A10BH; 7 and 8 have no SNOMED node
    snomed = {100: {1, 2, 3, 4, 5, 6}}

    assert build.equivalent_names(atc, snomed, NAMES) == {1: ["Dipeptidyl peptidase IV inhibitor"]}


def test_should_not_pair_a_broader_snomed_class():
    atc = {1: {1, 2, 3}}
    snomed = {200: {1, 2, 3, 10, 11, 12, 13, 14}}   # 3 of 8 -> Jaccard 0.375

    assert build.equivalent_names(atc, snomed, NAMES) == {}


def test_should_give_a_snomed_name_only_to_its_best_matching_atc_class():
    # parent 1 holds the child's ingredients plus another family's
    atc = {1: {1, 2, 3, 4, 5, 6, 20}, 2: {1, 2, 3, 4, 5, 6}}
    snomed = {100: {1, 2, 3, 4, 5, 6}, 300: {20, 21}}

    out = build.equivalent_names(atc, snomed, NAMES)

    assert out == {2: ["Dipeptidyl peptidase IV inhibitor"]}


def test_should_give_a_snomed_name_to_every_atc_class_with_the_identical_set():
    atc = {1: {1, 2, 3}, 2: {1, 2, 3}}          # B01 / B01A: same name, same ingredients
    snomed = {100: {1, 2, 3}}

    assert build.equivalent_names(atc, snomed, NAMES) == {
        1: ["Dipeptidyl peptidase IV inhibitor"], 2: ["Dipeptidyl peptidase IV inhibitor"]}


def test_should_index_the_bare_atc_name_when_nothing_is_equivalent():
    assert build.document_text("ANABOLIC STEROIDS", []) == "ANABOLIC STEROIDS"


def test_should_append_borrowed_names_after_the_atc_name():
    doc = build.document_text("Dipeptidyl peptidase 4 (DPP-4) inhibitors",
                              ["Dipeptidyl peptidase IV inhibitor"])

    assert doc == "Dipeptidyl peptidase 4 (DPP-4) inhibitors; Dipeptidyl peptidase IV inhibitor"


def test_should_keep_the_bare_atc_name_as_its_own_document_beside_the_enriched_one():
    # Measured 2026-10-08: indexing A10A only as "INSULINS AND ANALOGUES; Insulin;
    # Pancreatic hormone" moved the query "insulin" from 0.453 to 0.611, behind A10AE
    # (long-acting) at 0.597. The bare name must stay indexed so no class gets further away.
    docs = build.documents_for(21600713, "INSULINS AND ANALOGUES",
                               ["Insulin", "Pancreatic hormone"])

    assert docs == [("21600713", "INSULINS AND ANALOGUES"),
                    ("21600713+", "INSULINS AND ANALOGUES; Insulin; Pancreatic hormone")]


def test_should_index_one_document_when_nothing_is_equivalent():
    docs = build.documents_for(21600915, "ANABOLIC STEROIDS", [])

    assert docs == [("21600915", "ANABOLIC STEROIDS")]


def test_should_refuse_to_write_the_production_collection():
    import pytest
    with pytest.raises(SystemExit):
        build.main(["--collection", "atc_drug_classes"])
