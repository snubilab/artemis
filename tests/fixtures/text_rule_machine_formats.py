# ruff: noqa
# Machine-format shapes the text-rule detectors must NOT flag (AGENTS.md § PROMPTS AND TEXT
# RULES, rule 4: ids, enum values, CIRCE / OMOP field names, structured vocabulary
# attributes, UCUM, JSON, numbers). Never imported or executed: parsed with ast by
# tests/test_text_rule_detectors.py, which fails when a detector added on 2026-10-13
# (sql, wordlist, fuzzy, length, charclass, literal, lookup, textmatch) fires here.
# The SQL is copied from src/ at 79b9a3f; the location is on each function.
import difflib


# src/agents/agent2/critic.py:65 -- predicate on concept_id, not concept_name
def m01_sql_by_id(cur, schema, ids):
    cur.execute(
        "SELECT concept_id, concept_name, domain_id, vocabulary_id FROM {}.concept WHERE concept_id = ANY(%s)".format(schema),
        (ids,),
    )


# src/agents/agent2/drug_class_expander.py:367 -- mrconso read by cui / sab / lat / tty
def m02_sql_umls_by_cui(cur, cui):
    cur.execute(
        "SELECT DISTINCT str FROM mrconso WHERE cui = ? AND sab = 'RXNORM' AND lat = 'ENG' "
        "AND tty IN ('IN', 'PIN', 'MIN', 'BN') LIMIT 1",
        (cui,),
    )


# src/services/loinc_specimen.py:660 (shape) -- concept_name selected, grouped and ordered,
# never tested
def m03_sql_name_in_select_list(cur, schema, ids):
    cur.execute(
        f"""SELECT c.concept_id, c.concept_name,
                   MAX(CASE WHEN r.relationship_id = 'Has component' THEN x.concept_name END)
            FROM {schema}.concept c
            JOIN {schema}.concept_relationship r ON r.concept_id_1 = c.concept_id
            JOIN {schema}.concept x ON x.concept_id = r.concept_id_2
            WHERE c.concept_id = ANY(%s)
            GROUP BY c.concept_id, c.concept_name
            ORDER BY c.concept_name""",
        (ids,),
    )


def m04_enum_and_field_tests(rule, concept, domain_id, concept_code, vocabulary_id):
    if domain_id == "Condition":
        return 1
    if concept["domain_id"] == "Drug" and concept.get("vocabulary_id") in ("RxNorm",):
        return 2
    if concept_code.isdigit() and len(concept_code) > 5:
        return 3
    if rule.get("codesetId") is None and "CodesetId" in rule:
        return 4
    return 0


def m05_counts_of_ids(concept_ids, rows):
    if len(concept_ids) > 1000:
        return concept_ids[:1000]
    if len(rows) >= 2:
        return rows
    return []


def m06_format_strings():
    parts = "%Y-%m-%d".split("-")
    columns = "concept_id concept_name domain_id".split()
    return parts, columns


def m07_diff_display(before, after):
    return list(difflib.unified_diff(before, after))


def m08_emptiness(text):
    if len(text) == 0:
        return None
    if text == "":
        return None
    return text


# src/agents/agent2/drug_class_expander.py:508 _share -- an overlap of two concept-id sets
def m09_id_set_overlap(_ingredients, child, parent):
    held = set(_ingredients(parent.concept_id))
    return len(held & set(_ingredients(child.concept_id))) / len(held) if held else 0.0
