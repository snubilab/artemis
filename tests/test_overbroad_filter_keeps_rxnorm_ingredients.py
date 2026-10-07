"""An RxNorm Ingredient is not "overbroad" because it has many products.

`ExpressionBuilder._filter_overbroad` drops any candidate with more than
`AGENT2_ROLLUP_MAX_DESCENDANTS` (default 500) descendants. That guard exists for
ancestors such as 'Clinical finding' (133,526 descendants) that would swallow a
specific condition. For an RxNorm Ingredient, though, the descendant count is its
product count, so the guard removed exactly the most-prescribed drugs: metformin
(8,197), sitagliptin (760), insulin glargine (945), aspirin (10,719). Delivered DPP-4
sets held 7 of ATC A10BH's 8 ingredients -- sitagliptin was the missing one -- and
A10 'DRUGS USED IN DIABETES' came out as 71 of 84.

Live vocabulary: the exemption is decided by the concept table, so a mocked session
could only echo back whatever the test told it.
"""
import pytest

from src.agents.conceptset.expression_builder import ExpressionBuilder
from src.agents.conceptset.rag_search import ConceptCandidate
from src.settings import settings

pytestmark = pytest.mark.integration

METFORMIN = (1503297, "metformin", "Drug", "RxNorm", "Ingredient")          # 8,197 descendants
SITAGLIPTIN = (1580747, "sitagliptin", "Drug", "RxNorm", "Ingredient")      # 760
SAXAGLIPTIN = (40166035, "saxagliptin", "Drug", "RxNorm", "Ingredient")     # 273
ATC_A10 = (21600712, "DRUGS USED IN DIABETES", "Drug", "ATC", "ATC 2nd")    # 31,582
# 133,526 descendants
CLINICAL_FINDING = (441840, "Clinical finding", "Condition", "SNOMED", "Clinical Finding")
CEREBRAL_INFARCTION = (443454, "Cerebral infarction", "Condition", "SNOMED", "Disorder")    # 75


def _candidates(*concepts):
    return [ConceptCandidate(concept_id=cid, concept_name=name, domain_id=dom,
                             vocabulary_id=voc, concept_class_id=cls)
            for cid, name, dom, voc, cls in concepts]


def _filter(*concepts):
    builder = ExpressionBuilder(schema=settings.CDM_SCHEMA)
    return [c.concept_id for c in builder._filter_overbroad(_candidates(*concepts))]


def test_should_keep_an_rxnorm_ingredient_when_it_has_more_than_500_descendants():
    assert _filter(SITAGLIPTIN, SAXAGLIPTIN, METFORMIN) == [
        SITAGLIPTIN[0], SAXAGLIPTIN[0], METFORMIN[0]]


def test_should_still_filter_a_drug_class_concept_when_it_has_more_than_500_descendants():
    # Same Drug domain, but an ATC class, not an Ingredient: still subject to the guard.
    assert _filter(ATC_A10, SAXAGLIPTIN) == [SAXAGLIPTIN[0]]


def test_should_still_filter_a_condition_ancestor_when_it_has_more_than_500_descendants():
    assert _filter(CLINICAL_FINDING, CEREBRAL_INFARCTION) == [CEREBRAL_INFARCTION[0]]
