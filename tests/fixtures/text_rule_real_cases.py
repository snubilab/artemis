# ruff: noqa
# Real text rules the guard read green over on 2026-10-13, copied verbatim (bodies cut to
# the rule) from src/ at 79b9a3f so the detector tests keep their real case after the
# src/ copy is removed. r09 was added on 2026-10-14 from src/ at 3c6fd4f. Never imported or executed: tests/test_text_rule_detectors.py
# parses it with ast. Each function name says which detector must flag it.
import os
import re
from difflib import SequenceMatcher
from typing import Any, List, Optional, Sequence


# src/agents/agent2/workflow.py:116 _exact_name_concept -- detector (a) sql
def r01_sql_exact_concept_name(query_text: str, domain_hint: Optional[str]):
    if not query_text or not query_text.strip():
        return None

    sql = """
        SELECT concept_id, concept_name, domain_id, vocabulary_id, concept_class_id
        FROM {schema}.concept
        WHERE LOWER(concept_name) = LOWER(%s)
          AND standard_concept = 'S'
          AND invalid_reason IS NULL
    """
    params: list[Any] = [query_text.strip()]
    return sql, params


# src/agents/conceptset/ontology_search.py:62 search_by_name -- detector (a) sql, f-string
def r02_sql_like_fstring(self, query_text: str, n_results: int = 20):
    query = f"""
            SELECT
                c.concept_id,
                c.concept_name,
                c.domain_id,
                c.vocabulary_id,
                c.concept_class_id
            FROM {self.schema}.concept c
            WHERE c.standard_concept = 'S'
              AND c.invalid_reason IS NULL
              AND LOWER(c.concept_name) LIKE LOWER(:pattern)
        """

    params = {"pattern": f"%{query_text}%", "limit": n_results}
    return query, params


# src/services/tte_service.py:6490 -- detector (a) sql, = ANY over lowered names
def r03_sql_lower_any(cur, settings, names):
    cur.execute(
        f"""
                        SELECT concept_id FROM {settings.CDM_SCHEMA}.concept
                        WHERE LOWER(concept_name) = ANY(%s)
                          AND standard_concept = 'S'
                          AND concept_class_id = 'Ingredient'
                          AND vocabulary_id = 'RxNorm'
                          AND invalid_reason IS NULL
                        """,
        (names,),
    )


# src/agents/agent2/umls_synonym_expander.py:236 get_cuis -- detector (a) sql, UMLS str
def r04_sql_umls_str(cur, query):
    cur.execute(
        "SELECT DISTINCT cui FROM mrconso WHERE str = ? COLLATE NOCASE",
        (query,),
    )
    cur.execute(
        "SELECT DISTINCT cui FROM mrconso WHERE str LIKE ? COLLATE NOCASE LIMIT 10",
        (f"%{query}%",),
    )


# src/agents/agent1/criteria_dedup.py:96 and :120 -- detector (b) wordlist
_STOPWORDS = frozenset("""a an the of or and with to for in on at by is are was were be
been being that this those these not no if as from than then must may can shall should
will either both any all each per within prior previous documented enough least one more
year years yrs old due cause separate occasions apart month months week weeks patient
patients subject subjects who has have had time""".split())
_NEGATORS = frozenset("""no not without absence absent free never neither nor non
excluding exclude excluded lack lacking unable negative""".split())


# src/agents/agent1/enricher.py:107 _merge_criteria -- detector (c) fuzzy
def r05_fuzzy_sequence_matcher(nct_criteria, pubmed_criteria, similarity_threshold=0.7):
    merged = list(nct_criteria)
    for pub_item in pubmed_criteria:
        is_duplicate = False
        for nct_item in nct_criteria:
            similarity = SequenceMatcher(
                None, pub_item.lower(), nct_item.lower()
            ).ratio()
            if similarity >= similarity_threshold:
                is_duplicate = True
                break
        if not is_duplicate:
            merged.append(pub_item)
    return merged


# src/agents/agent1/criteria_dedup.py:111 _content_tokens -- detector (d) length + literal
_WORD = re.compile(r"[a-z]+|\d+(?:\.\d+)?|<=|>=|[<>]")


def _normalize(text: str) -> str:
    return str(text).strip().casefold()


def r06_content_tokens(text: str) -> list[str]:
    """:param text: raw criterion text. :returns: meaning-bearing tokens, in order."""
    return [t for t in _WORD.findall(_normalize(text))
            if len(t) > 1 and t not in _STOPWORDS]


# src/agents/agent1/criteria_dedup.py:181 _initialism_run -- detector (d) length + charclass,
# reached only through the caller's tainted arguments (same-module helper parameters)
def r07_initialism_run(abbr: str, words: Sequence[str]) -> int:
    n = len(abbr)
    if n < 2 or n > 6 or not abbr.isalpha():
        return -1
    for i in range(0, len(words) - n + 1):
        if "".join(w[0] for w in words[i:i + n]) == abbr:
            return i
    return -1


def r07_caller(candidate: str, alternative: str) -> int:
    tokens = r06_content_tokens(alternative)
    return max(r07_initialism_run(tok, tokens) for tok in r06_content_tokens(candidate))


# src/agents/agent2/query_expander.py:18 and :45 -- detector (d) length vs a named constant
_MAX_ABBREV_LENGTH = 6


class QueryExpander:
    def expand(self, query: str, domain_hint: Optional[str] = None) -> str:
        if not domain_hint:
            return query

        stripped = query.strip()
        if not stripped:
            return query
        if len(stripped) > _MAX_ABBREV_LENGTH:
            return query
        return stripped


# src/agents/agent2/umls_synonym_expander.py:194 and :340 -- detector (d) length
def r08_umls_short_query(query, domain_hint, strict):
    if strict and domain_hint and len(query.strip()) <= 5:
        return []
    query = query.strip()
    if not query or len(query) < 2:
        return []
    return [query]


# src/pipeline/supervisor.py:611-613 and :641-648 PipelineSupervisor._step4_5_assemble_validate
# (3c6fd4f) -- taint lookup: a dict filled at run time keyed by lower-cased entity text, then
# read with another lower-cased entity text to recover the failed entity's domain
def r09_entity_lookup_by_lowered_text(assembly_result, entities_to_map=None):
    # Build entity lookup for domain/parent_rule recovery during re-mapping
    entity_lookup: dict = {}
    for ent in (entities_to_map or []):
        entity_lookup[ent["text"].lower()] = ent

    failed_entities = [
        {
            "text": h.entity_text,
            "domain": entity_lookup.get(h.entity_text.lower(), {}).get("domain"),
            "parent_rule": entity_lookup.get(h.entity_text.lower(), {}).get("parent_rule"),
        }
        for h in assembly_result.heal_log if h.action == "SKIP"
    ]
    return failed_entities
