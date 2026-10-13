# ruff: noqa
# Text-rule probe: one function per syntactic shape a natural-language text rule takes.
# Never imported or executed. tests/test_text_rule_detectors.py parses it with ast and
# requires tests/test_no_text_rules.py to flag every shape listed there as a violation.
# Copied verbatim from the 2026-10-13 blind-spot audit (53 shapes; s37b is the helper
# s37 calls); s54-s58 were added on 2026-10-14 for text used as the key of a dict that is
# not a literal (built at run time, or passed in). The parameter name `text` stands for
# protocol / criterion / entity text.
import difflib
import fnmatch
import re
import unicodedata
from difflib import SequenceMatcher


class QueryExpander:
    _MAX_ABBREV_LENGTH = 6

    def s01_len_threshold_class_constant(self, text):
        return len(text) <= self._MAX_ABBREV_LENGTH


def s02_len_threshold_literal(text):
    return len(text.strip()) <= 6


def s03_isupper(text):
    return text.isupper()


def s04_istitle_isalpha_isdigit(text):
    return text.istitle() or text.isalpha() or text.isdigit() or text.isalnum()


def s05_word_count_split_noarg(text):
    return len(text.split()) > 3


def s06_space_count(text):
    return text.count(" ") >= 2


def s07_char_class_count(text):
    return sum(ch.isupper() for ch in text) >= 2


def s08_digit_count(text):
    return sum(1 for ch in text if ch.isdigit()) > 0


def s09_sequence_matcher(a, b):
    return SequenceMatcher(None, a, b).ratio() >= 0.7


def s10_difflib_module(a, b):
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio() > 0.8


def s11_get_close_matches(word, words):
    return difflib.get_close_matches(word, words, cutoff=0.8)


def s12_literal_in_raw_text(text):
    return "placebo" in text


def s13_literal_in_attribute(arm):
    return "placebo" in arm.name


def s14_literal_in_subscript(arm):
    return "placebo" in arm["name"]


def s15_literal_in_attribute_lowered(arm):
    return "placebo" in arm.name.lower()


def s16_eq_raw_text(text):
    return text == "stable"


def s17_startswith_raw(text):
    return text.startswith("cv")


def s18_endswith_raw_tuple(text):
    return text.endswith(("ine", "ide"))


def s19_literal_in_lowered_split(text):
    return "or" in text.lower().split()


def s20_literal_in_token_name(text):
    tokens = text.lower().split()
    return "either" in tokens


def s21_custom_normaliser_helper(text):
    def _norm(s):
        return " ".join(s.lower().split())

    return "other than" in _norm(text)


def s22_unicodedata_normalise(text):
    folded = unicodedata.normalize("NFKC", text)
    return "other than" in folded


def s23_normalised_slice_eq(text):
    return text.lower()[:4] == "fast"


def s24_singleton_set_membership(text):
    return text.lower() in {"placebo"}


def s25_singleton_tuple_membership(text):
    return text.lower() in ("placebo",)


def s26_normalised_in_named_set(text, words):
    return text.lower() in words


WORDS_FROM_STRING = "prior previous before within".split()


def s27_runtime_split_word_list(text):
    return any(w in text.lower() for w in WORDS_FROM_STRING)


WORDS_FROM_COMMA_STRING = "prior,previous,before".split(",")


def s28_comma_split_word_list(text):
    return text.lower() in WORDS_FROM_COMMA_STRING


class Route:
    ORAL = 1
    IV = 2


ROUTE_TABLE = {"oral": Route.ORAL, "intravenous": Route.IV}


def s29_dict_with_name_values(text):
    return ROUTE_TABLE.get(text.lower())


def s30_match_statement(word):
    match word.lower():
        case "or":
            return "ANY"
        case _:
            return "ALL"


def s31_removeprefix(text):
    return text.removeprefix("history of ")


def s32_fnmatch(text):
    return fnmatch.fnmatch(text.lower(), "*insulin*")


def s33_jaccard(a, b):
    sa, sb = set(a.lower().split()), set(b.lower().split())
    return len(sa & sb) / max(1, len(sa | sb)) >= 0.5


def s34_comprehension_word_set(text):
    stop = {w for w in ("of",)}
    return text in stop


def s35_maketrans_letters(text):
    return text.translate(str.maketrans("", "", "aeiou"))


def s36_isascii(text):
    return text.isascii()


def s37_text_to_helper(text):
    return s37b_len_helper(text)


def s37b_len_helper(s):
    return len(s) < 7


def s38_index_first_word(text):
    return text.split()[0].lower() == "no"


def s39_word_list_from_json(text, path):
    import json

    words = json.load(open(path))
    return text.lower() in words


def s40_ord_range(text):
    return all(65 <= ord(c) <= 90 for c in text)


def s41_unicodedata_category(text):
    return any(unicodedata.category(c) == "Lu" for c in text)


def s42_regex_third_party(text):
    import regex  # type: ignore

    return regex.search(r"\bor\b", text)


def s43_operator_contains(text):
    import operator

    return operator.contains(text.lower(), "other than")


def s44_re_function_alias(text):
    finder = re.compile
    return finder(r"\bor\b").search(text)


def s45_lowered_attr_then_in(self_obj, text):
    self_obj.low = text.lower()
    return "or" in self_obj.low


def s46_eq_after_strip_chars(text):
    return text.strip("()").lower() == "or"


def s47_split_space_len(text):
    return len(text.split(" ")) == 1


def s48_rapidfuzz(a, b):
    from rapidfuzz import fuzz  # type: ignore

    return fuzz.ratio(a, b) > 90


def s49_upper_ratio(text):
    upper = sum(c.isupper() for c in text)
    return upper / max(1, len(text)) > 0.6


def s50_literal_in_param_already_lowered(lowered):
    return "or" in lowered


def s51_normalised_eq_literal_control(text):
    return text.lower() == "placebo"


def s52_literal_in_normalised_control(text):
    return "placebo" in text.lower()


def s53_two_member_set_control(text):
    return text in {"oral", "iv"}


# 2026-10-14: a dict that is not a literal, keyed or looked up by text. `text.lower() in
# table` is already s26 (caught as textmatch), so it is not repeated here.
def s54_runtime_dict_get_lowered(text, table):
    return table.get(text.lower())


def s55_runtime_dict_subscript_casefolded(text, table):
    return table[text.casefold()]


def s56_comprehension_keyed_by_text_then_get(entities, failures):
    by_text = {ent["text"]: ent for ent in entities}
    return [by_text.get(failure.entity_text) for failure in failures]


def s57_filled_by_text_then_in(entities, text):
    by_text = {}
    for ent in entities:
        by_text[ent["text"]] = ent
    return text in by_text


def s58_grouped_by_text(items):
    groups = {}
    for item in items:
        groups.setdefault(item["text"], []).append(item)
    return list(groups.values())
