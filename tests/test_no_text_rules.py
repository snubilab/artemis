"""No new rule may read natural language through a regex, a word list or a literal test.

The user's standing rule (``AGENTS.md`` § PROMPTS AND TEXT RULES, rule 2): no regex,
word list, keyword set, substring, similarity or length test over protocol, criterion,
description, entity text, LLM free text or OMOP concept names may decide what that text
means. Meaning belongs in an extraction schema field whose source span the code checks
against ``protocolLine``. Parsing a machine format (UCUM, JSON, ids, CIRCE / OMOP field
names, LOINC structured attributes, numbers) is not covered by the rule.

The rules that existed on 2026-10-12 are inventoried in
``docs/inventory/2026-10-12_text_rules.{md,json}``. Every site the collector below finds
is listed in ``tests/fixtures/text_rule_ledger.json`` -- as ``allowed`` (machine format,
with a one-line reason) or as ``pending`` (a text rule scheduled for removal).

WHAT IS SCANNED
---------------
Every ``.py`` file under ``src/``, the four delivery-path scripts (:data:`DELIVERY_SCRIPTS`),
every ``.py`` file a ledger entry names (so a pending rule is always looked for where it
lives), and every data file under ``src/`` (:data:`DATA_SUFFIXES`).

WHAT IS COLLECTED
-----------------
Syntactic detectors, on any receiver:

(a) ``re:`` -- the pattern argument of ``re`` / ``regex`` ``compile / search / match /
    fullmatch / sub / subn / findall / finditer / split``, including a name bound to one
    of those functions (``finder = re.compile``). A name bound once to a string
    expression in the same module (or the enclosing function) is resolved, so a pattern
    kept in a module-level constant is fingerprinted by its text. An argument that cannot
    be resolved is fingerprinted by its source, in braces.
    ``sql:`` -- a string constant or f-string (docstrings excepted) that tests
    ``concept_name`` / ``concept_synonym_name`` -- or UMLS ``mrconso.str`` -- with ``=``,
    ``<>``, ``LIKE``, ``ILIKE``, ``~``, ``SIMILAR TO``, ``= ANY``, ``IN (``, Cypher
    ``CONTAINS / STARTS WITH / ENDS WITH / =~``, or passes it to a similarity function,
    optionally through ``LOWER / UPPER / TRIM``. A name lookup in SQL is the same rule as
    a name lookup in Python. A predicate on ``concept_id``, ``cui``, ``sab``, ``tty`` or any
    other id / enum column is not collected.
(b) ``strings:`` -- a set, list or tuple literal holding two or more string constants,
    except a LangChain ``(role, "...")`` chat message (prompts have their own guard);
    ``keys:`` -- a dict literal with two or more string-constant keys whose values are all
    constant (a lookup table; a dict with a computed value is a record being built);
    ``wordlist:`` -- a string literal split at run time into two or more alphabetic words
    (``\"\"\"a an the\"\"\".split()``, ``"a,b".split(",")``);
    ``datafile:`` -- a data file under ``src/`` holding two or more word keys or word array
    members (an id-keyed file is not collected).
(c) ``in: / startswith: / endswith: / eq:`` -- a literal test on *normalised* text
    (``.lower() / .casefold() / .upper() / .strip() / .lstrip() / .rstrip() / .title()`` or
    a name assigned from one), whatever the text is;
    ``fuzzy:`` -- ``difflib.SequenceMatcher`` / ``get_close_matches`` and any call into
    rapidfuzz / fuzzywuzzy / thefuzz / Levenshtein / jellyfish / textdistance /
    editdistance / strsimpy.
(d) ``split: / rsplit: / replace: / find: / rfind: / count: / partition: / rpartition: /
    index: / rindex:`` -- that string method called with a first argument that is a
    string literal containing a letter.

Taint detectors, within one module: natural-language *text* flowing into a test.

Sources: a parameter, attribute, dict key (``x["..."]``, ``x.get("...")``,
``getattr(x, "...")``) or LLM response field whose identifier names text
(:data:`TEXT_FIELDS`, :data:`TEXT_FIELD_ENDINGS`; ``entity_text``, ``sourceText``,
``CONCEPT_NAME``, ``description``, ``name``, ``label``, ``content`` ...). Text flows through
assignment (including ``obj.attr = text``), any string method, slicing and indexing,
``split`` / ``join`` / regex ``sub / findall``, ``str / list / set / sorted / enumerate``,
``unicodedata.normalize``, comprehensions and ``for`` loops, and into the parameters and
out of the return value of a function, method or nested function of the same module (a
helper whose own parameter names text returns text whatever it is called with).
Sinks:

- ``length:`` -- ``len()`` of text, a character / substring count, ``ord()`` of a
  character, or arithmetic on those, compared with a number or a named numeric constant.
  ``len(x) == 0`` / ``> 0`` / ``>= 1`` is an emptiness test and is not collected.
- ``charclass:`` -- ``isupper / islower / istitle / isalpha / isdigit / isalnum /
  isnumeric / isdecimal / isspace / isascii / isidentifier / isprintable`` or
  ``unicodedata.category`` on text.
- ``literal:`` -- text tested against a string literal or a literal string collection
  (or a name bound to one, or a member of one): ``in``, ``==``, ``!=``, ``startswith``,
  ``endswith``, ``removeprefix``, ``removesuffix``, ``match / case``, ``operator.contains``,
  ``fnmatch``, ``translate(str.maketrans(...letters...))``. Comparing with ``""`` is an
  emptiness test and is not collected.
- ``lookup:`` -- ``TABLE.get(text)`` / ``TABLE[text]`` on a dict literal keyed by strings.
- ``textmatch:`` -- two texts compared after case-folding or Unicode normalisation (directly
  or by a same-module helper that returns such a value): ``a.lower() == b.lower()``,
  ``text.lower() in collection``. Equal after ``strip()`` is the same text, not a match.
- ``fuzzy:`` -- a token-overlap ratio ``len(a & b) / ...`` over word bags (text, or a value
  built by ``split`` / ``lower`` / ``findall``); an overlap of id sets is not collected.

A site already collected by (c) is not collected again by the taint pass.

A site is keyed by ``(file, fingerprint)``. The fingerprint is the pattern text, the
sorted string members, the tested literal, or the test's source -- never a line number,
so editing unrelated code does not churn the ledger. A site also carries its *symbol*
(the enclosing function or method; a module-level constant's name) and its *sink* (the
fingerprint's prefix).

WHAT IT MISSES
--------------
Text-ness is read from identifiers, so text held under a name that does not say so
(``item``, ``candidate``, ``value``) is a source only if a same-module caller passes text
into it. Flow across modules is not followed: a helper imported from another module is
opaque. A raw (un-normalised) equality or membership between two texts -- a join on the
same string -- is not collected. Splitting or replacing on punctuation (``text.split(",")``)
is tokenisation, not a sink. A lambda body is not analysed. A lookup table whose values
are names or attributes is collected only where text is looked up in it.

THE CHECKS
----------
1. Every collected site has a ledger entry: ``allowed`` by ``(file, fingerprint)``, or
   ``pending`` by ``(file, symbol, sink)``. This is what blocks a new rule.
2. Every ``pending`` entry still has a site with its sink in its symbol. A pending rule
   stays pending while any of its sinks remains; delete the entry when the last one goes.
3. No ``allowed`` entry lives in a module whose only role is a text rule.
4. The pending list only shrinks. Every pending key must be in the recorded baseline
   ``tests/fixtures/text_rule_pending_baseline.json``, and the baseline's keys must hash
   to :data:`PENDING_BASELINE_SHA256`. Adding a pending entry therefore takes two edits
   in one reviewed commit -- the baseline file and the hash in this module -- and cannot
   happen by editing the ledger alone. Deleting a pending entry needs neither.
"""

from __future__ import annotations

import ast
import functools
import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER_PATH = ROOT / "tests" / "fixtures" / "text_rule_ledger.json"
BASELINE_PATH = ROOT / "tests" / "fixtures" / "text_rule_pending_baseline.json"
SCAN_DIRECTORY = ROOT / "src"
DELIVERY_SCRIPTS = tuple(
    ROOT / "scripts" / name
    for name in (
        "export_seeded_cohorts.py",
        "export_circe_from_store.py",
        "verify_circe_delivery.py",
        "reingest_protocol_pdfs.py",
    )
)
DATA_SUFFIXES = frozenset({".json", ".yaml", ".yml", ".txt", ".csv", ".tsv"})

# sha256 of the baseline's sorted pending keys (see check 4). Changing it is the growth step.
PENDING_BASELINE_SHA256 = "29817585cc861cd9c2100f275aba5271ef9b201c4bf6cf78e642a673d35a531f"

RE_MODULES = frozenset({"re", "regex"})
RE_FUNCTIONS = frozenset(
    {"compile", "search", "match", "fullmatch", "sub", "subn", "findall", "finditer", "split"}
)
NORMALISERS = frozenset({"lower", "casefold", "upper", "strip", "lstrip", "rstrip", "title"})
SEARCH_METHODS = frozenset(
    {"split", "rsplit", "replace", "find", "rfind", "count", "partition", "rpartition"}
    | {"index", "rindex"}
)
CHAT_ROLES = frozenset({"system", "user", "human", "ai", "assistant"})
CONSTANT_CONTAINERS = frozenset({"frozenset", "set", "tuple"})
KINDS = frozenset({"allowed", "pending"})
STATUSES = frozenset({"live", "dormant"})

DIFFLIB_MATCHERS = frozenset({"SequenceMatcher", "get_close_matches"})
FUZZY_MODULES = frozenset(
    {
        "rapidfuzz",
        "fuzzywuzzy",
        "thefuzz",
        "Levenshtein",
        "jellyfish",
        "textdistance",
        "editdistance",
        "strsimpy",
    }
)

# Identifiers that hold natural-language text. Matched on the identifier's words, so
# ``entity_text``, ``sourceText`` and ``CONCEPT_NAME`` all match.
TEXT_FIELDS = frozenset(
    {
        "text",
        "description",
        "protocol_line",
        "concept_name",
        "query",
        "term",
        "phrase",
        "seed",
        "span",
        "quote",
        "verbatim",
        "synonym",
        "alias",
        "abbr",
        "abbrev",
        "abbreviation",
        "sentence",
        "snippet",
        "mention",
        "content",
        "completion",
        "word",
        "words",
        "token",
        "tokens",
        "lowered",
        "normalised",
        "normalized",
        "folded",
        "name",
        "label",
        "title",
    }
)
# ... or whose last word says it does: ``query_text``, ``rule_description``, ``cand_tokens``.
TEXT_FIELD_ENDINGS = frozenset(
    {
        "text",
        "texts",
        "description",
        "descriptions",
        "line",
        "lines",
        "span",
        "spans",
        "phrase",
        "phrases",
        "term",
        "terms",
        "synonym",
        "synonyms",
        "alias",
        "aliases",
        "token",
        "tokens",
        "word",
        "words",
        "seed",
        "abbr",
        "abbrev",
        "lowered",
        "normalised",
        "normalized",
        "folded",
    }
)
TEXT_FIELD_PAIR_ENDINGS = frozenset({("concept", "name"), ("concept", "names")})
# Identifiers whose last word matches but whose value is a machine format.
NOT_TEXT_FIELDS = frozenset({"unit_text"})
# A text-named collection whose last word is one of these gathers separate texts -- one per
# record -- so its len() counts records, not words of one text (``len(descriptions) == 1``).
GATHERED_ENDINGS = frozenset(
    {
        "texts",
        "descriptions",
        "names",
        "labels",
        "lines",
        "spans",
        "phrases",
        "terms",
        "synonyms",
        "aliases",
        "titles",
        "seeds",
        "quotes",
        "mentions",
        "queries",
        "snippets",
        "sentences",
    }
)
NORMALISED_WORDS = frozenset(
    {"lowered", "lower", "normalised", "normalized", "folded", "casefolded", "norm"}
)

# What makes two texts compare equal across spellings: case and Unicode form. Trimming
# whitespace is not one -- equal after ``strip()`` is the same text.
CASE_NORMALISERS = frozenset(
    {"lower", "casefold", "upper", "title", "swapcase", "capitalize", "normalize"}
)
STR_PREDICATES = frozenset(
    {
        "isupper",
        "islower",
        "istitle",
        "isalpha",
        "isdigit",
        "isalnum",
        "isnumeric",
        "isdecimal",
        "isspace",
        "isascii",
        "isidentifier",
        "isprintable",
    }
)
AFFIX_METHODS = frozenset({"startswith", "endswith", "removeprefix", "removesuffix"})
MEASURE_METHODS = frozenset({"count", "find", "rfind", "index", "rindex"})
NON_TEXT_METHODS = MEASURE_METHODS | STR_PREDICATES | {"startswith", "endswith", "__len__"}
TEXT_BUILTINS = frozenset(
    {
        "str",
        "list",
        "set",
        "frozenset",
        "tuple",
        "sorted",
        "reversed",
        "iter",
        "next",
        "enumerate",
        "zip",
        "filter",
    }
)
TEXT_FUNCTIONS = frozenset(
    {"normalize", "unescape", "unquote", "dedent", "fill", "shorten", "wrap"}
)
MATCH_METHODS = frozenset(
    {
        "sub",
        "subn",
        "findall",
        "finditer",
        "split",
        "search",
        "match",
        "fullmatch",
        "group",
        "groups",
        "expand",
    }
)
MEASURE_WRAPPERS = frozenset({"max", "min", "abs", "round", "float", "int"})
COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)
ORDERINGS = (ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Eq, ast.NotEq)

# Modules whose only role is a text rule of inventory class A, S or C, so none of their
# sites may be ``allowed``. A module leaves this list when its rule is replaced; check 3
# fails while a listed module holds no pending entry, so the list cannot go stale.
# Emptied 2026-10-13: criterion_seed.py (A10, RFC-016 step 2) and disease_anchor.py (C8,
# 37bd1d8) no longer hold a rule, and the extended collector finds no site in either.
RULE_MODULES: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Site:
    file: str
    fingerprint: str
    line: int
    scope: str
    symbol: str = ""

    @property
    def sink(self) -> str:
        return self.fingerprint.split(":", 1)[0]


def _is_str(node: ast.AST | None) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _fingerprint_list(values: Iterable[str]) -> str:
    return json.dumps(sorted(set(values)), ensure_ascii=False)


def _compact(node: ast.AST) -> str:
    return " ".join(ast.unparse(node).split())


def _own_statements(body: list[ast.stmt]) -> Iterator[ast.AST]:
    """Nodes of ``body`` that belong to its scope, not to a nested def, class or lambda."""
    stack: list[ast.AST] = list(body)
    while stack:
        node = stack.pop()
        yield node
        for child in ast.iter_child_nodes(node):
            if not isinstance(
                child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
            ):
                stack.append(child)


def _is_text_expression(node: ast.AST | None) -> bool:
    """A string constant, a concatenation, an f-string, or a name that may resolve to one."""
    return (
        _is_str(node)
        or isinstance(node, (ast.Name, ast.JoinedStr))
        or (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add))
    )


def _is_constant(node: ast.AST | None) -> bool:
    """A value a lookup table could hold: a literal, or a container of literals."""
    if isinstance(node, ast.Constant):
        return not isinstance(node.value, bytes)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        return _is_constant(node.operand)
    if isinstance(node, ast.BinOp) and isinstance(
        node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow)
    ):
        return _is_constant(node.left) and _is_constant(node.right)
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return all(_is_constant(element) for element in node.elts)
    if isinstance(node, ast.Dict):
        return all(_is_constant(value) for value in node.values)
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in CONSTANT_CONTAINERS
        and not node.keywords
    ):
        return all(_is_constant(argument) for argument in node.args)
    return False


def _is_chat_message(node: ast.Tuple) -> bool:
    """A LangChain ``(role, "text")`` message tuple."""
    return (
        len(node.elts) == 2
        and _is_str(node.elts[0])
        and node.elts[0].value in CHAT_ROLES  # type: ignore[attr-defined]
        and _is_str(node.elts[1])
    )


def _is_normaliser_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in NORMALISERS
    )


# -- (a) SQL name predicates ----------------------------------------------------------
_SQL_WRAP = r"(?:(?:lower|upper|trim|btrim|unaccent|tolower|toupper)\s*\(\s*)*"
_SQL_OPERATOR = (
    r"(?:=\s*any\b|not\s+i?like\b|i?like\b|similar\s+to\b|starts\s+with\b|ends\s+with\b"
    r"|contains\b|=~|!~\*?|~\*?|<>|!=|=|\bin\s*\(|%\s)"
)
_SQL_SIMILARITY = (
    r"(?:similarity|word_similarity|strict_word_similarity|levenshtein|levenshtein_less_equal"
    r"|soundex|difference|metaphone|dmetaphone|jarowinkler)"
)


def sql_name_predicates(text: str) -> list[str]:
    """Predicates in ``text`` that test a concept name (or a UMLS ``mrconso.str``) as text.

    :param text: a string constant from the source, f-string holes rendered as ``{}``.
    :returns: the matched predicate snippets, whitespace-collapsed and sorted.
    """
    columns = "concept_name|concept_synonym_name"
    if "mrconso" in text.lower():
        columns += "|str"
    column = rf"(?:\b\w+\.)?\b(?:{columns})\b"
    patterns = (
        rf"{_SQL_WRAP}{column}(?:\s*\))*\s*{_SQL_OPERATOR}",
        rf"{_SQL_OPERATOR}\s*{_SQL_WRAP}{column}",
        rf"\b{_SQL_SIMILARITY}\s*\(\s*{_SQL_WRAP}{column}",
    )
    collapsed = " ".join(text.split())
    found = {
        " ".join(match.group(0).split())
        for pattern in patterns
        for match in re.finditer(pattern, collapsed, re.IGNORECASE)
    }
    return sorted(found)


def _words_of_literal_split(receiver: str, separator: str | None) -> list[str]:
    """The alphabetic words a literal ``receiver.split(separator)`` produces."""
    tokens = receiver.split(separator)
    return [token for token in tokens if token.replace("-", "").replace("'", "").isalpha()]


@dataclass
class _ScopeInfo:
    assignments: dict[str, list[ast.expr]]
    normalised: set[str]


def _scope_info(body: list[ast.stmt], parameters: ast.arguments | None = None) -> _ScopeInfo:
    assignments: dict[str, list[ast.expr]] = defaultdict(list)
    normalised: set[str] = set()
    if parameters is not None:
        # A parameter is bound by the caller: it shadows a module constant of the same
        # name and resolves to nothing.
        for arg in [
            *parameters.posonlyargs,
            *parameters.args,
            *parameters.kwonlyargs,
            *([parameters.vararg] if parameters.vararg else []),
            *([parameters.kwarg] if parameters.kwarg else []),
        ]:
            marker = ast.Name(id=arg.arg)
            assignments[arg.arg].extend([marker, marker])
    for node in _own_statements(body):
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        elif isinstance(node, ast.NamedExpr):
            targets, value = [node.target], node.value
        elif isinstance(node, (ast.AugAssign, ast.For, ast.AsyncFor)):
            # A rebinding the resolver cannot follow: mark the name ambiguous.
            for name in ast.walk(node.target):
                if isinstance(name, ast.Name):
                    assignments[name.id].extend([name, name])
            continue
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                assignments[target.id].append(value)
                if _is_normaliser_call(value):
                    normalised.add(target.id)
            else:
                for name in ast.walk(target):
                    if isinstance(name, ast.Name):
                        assignments[name.id].append(name)
    return _ScopeInfo(dict(assignments), normalised)


class _Collector(ast.NodeVisitor):
    """The syntactic detectors (a)-(d)."""

    def __init__(self, rel: str, tree: ast.Module) -> None:
        self.rel = rel
        self.sites: list[Site] = []
        self.reported: set[int] = set()
        self.names: list[str] = []
        self.function_depth = 0
        self.target: str | None = None
        self.scopes: list[_ScopeInfo] = [_scope_info(tree.body)]
        self.re_modules: set[str] = set()
        self.re_functions: dict[str, str] = {}
        self.difflib_modules: set[str] = set()
        self.difflib_functions: set[str] = set()
        self.fuzzy_roots: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    bound = alias.asname or root
                    if alias.name in RE_MODULES:
                        self.re_modules.add(alias.asname or alias.name)
                    elif alias.name == "difflib":
                        self.difflib_modules.add(bound)
                    elif root in FUZZY_MODULES:
                        self.fuzzy_roots.add(bound)
            elif isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".")[0]
                for alias in node.names:
                    bound = alias.asname or alias.name
                    if node.module in RE_MODULES and alias.name in RE_FUNCTIONS:
                        self.re_functions[bound] = alias.name
                    elif node.module == "difflib" and alias.name in DIFFLIB_MATCHERS:
                        self.difflib_functions.add(bound)
                    elif root in FUZZY_MODULES:
                        self.fuzzy_roots.add(bound)
        for node in ast.walk(tree):
            # ``finder = re.compile``: the alias is called like the function it names.
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Attribute)
                and isinstance(node.value.value, ast.Name)
                and node.value.value.id in self.re_modules
                and node.value.attr in RE_FUNCTIONS
            ):
                self.re_functions[node.targets[0].id] = node.value.attr

    # -- scope bookkeeping ---------------------------------------------------------
    def _add(self, node: ast.AST, fingerprint: str) -> None:
        scope = ".".join([*self.names, *([self.target] if self.target else [])]) or "<module>"
        symbol = ".".join(self.names) if self.function_depth else scope
        self.sites.append(Site(self.rel, fingerprint, getattr(node, "lineno", 0), scope, symbol))
        self.reported.add(id(node))

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.names.append(node.name)
        self.function_depth += 1
        self.scopes.append(_scope_info(node.body, node.args))
        saved, self.target = self.target, None
        self.generic_visit(node)
        self.target = saved
        self.scopes.pop()
        self.function_depth -= 1
        self.names.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._function(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.names.append(node.name)
        saved, self.target = self.target, None
        self.generic_visit(node)
        self.target = saved
        self.names.pop()

    def _assignment(self, targets: list[ast.expr], node: ast.AST) -> None:
        first = targets[0] if targets else None
        saved = self.target
        if isinstance(first, ast.Name):
            self.target = first.id
        elif isinstance(first, ast.Attribute):
            self.target = first.attr
        self.generic_visit(node)
        self.target = saved

    def visit_Assign(self, node: ast.Assign) -> None:
        self._assignment(node.targets, node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._assignment([node.target], node)

    # -- resolution ----------------------------------------------------------------
    def _lookup(self, name: str) -> ast.expr | None:
        for info in reversed(self.scopes):
            values = info.assignments.get(name)
            if values:
                return values[0] if len(values) == 1 else None
        return None

    def _text(self, expr: ast.expr, depth: int = 0) -> str:
        if _is_str(expr):
            return expr.value  # type: ignore[attr-defined]
        if depth < 8:
            if isinstance(expr, ast.Name):
                value = self._lookup(expr.id)
                if _is_text_expression(value) and not (
                    isinstance(value, ast.Name) and value.id == expr.id
                ):
                    return self._text(value, depth + 1)  # type: ignore[arg-type]
            if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Add):
                return self._text(expr.left, depth + 1) + self._text(expr.right, depth + 1)
            if isinstance(expr, ast.JoinedStr):
                parts = []
                for part in expr.values:
                    if _is_str(part):
                        parts.append(part.value)  # type: ignore[attr-defined]
                    elif isinstance(part, ast.FormattedValue):
                        parts.append(self._text(part.value, depth + 1))
                return "".join(parts)
        return "{" + ast.unparse(expr) + "}"

    def _normalised(self, expr: ast.expr) -> bool:
        if _is_normaliser_call(expr):
            return True
        return isinstance(expr, ast.Name) and any(
            expr.id in info.normalised for info in self.scopes
        )

    def _fuzzy_matcher(self, func: ast.expr) -> bool:
        if isinstance(func, ast.Name):
            return func.id in self.difflib_functions or func.id in self.fuzzy_roots
        if isinstance(func, ast.Attribute):
            if (
                func.attr in DIFFLIB_MATCHERS
                and isinstance(func.value, ast.Name)
                and func.value.id in self.difflib_modules
            ):
                return True
            root: ast.expr = func
            while isinstance(root, ast.Attribute):
                root = root.value
            return isinstance(root, ast.Name) and root.id in self.fuzzy_roots
        return False

    # -- (a) SQL name predicates; docstrings and bare string statements are skipped ----
    def visit_Expr(self, node: ast.Expr) -> None:
        if _is_str(node.value) or isinstance(node.value, ast.JoinedStr):
            return
        self.generic_visit(node)

    def _sql(self, node: ast.AST, text: str) -> None:
        predicates = sql_name_predicates(text)
        if predicates:
            self._add(node, "sql:" + json.dumps(predicates, ensure_ascii=False))

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str):
            self._sql(node, node.value)

    def visit_JoinedStr(self, node: ast.JoinedStr) -> None:
        rendered = "".join(
            part.value if _is_str(part) else "{}"
            for part in node.values  # type: ignore[attr-defined]
        )
        self._sql(node, rendered)
        for part in node.values:
            if isinstance(part, ast.FormattedValue):
                self.visit(part)

    # -- (a) regex, (b) word lists, (c) prefix tests and fuzzy matchers, (d) methods ---
    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        is_re = (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id in self.re_modules
            and func.attr in RE_FUNCTIONS
        ) or (isinstance(func, ast.Name) and func.id in self.re_functions)
        if is_re:
            pattern = node.args[0] if node.args else None
            if pattern is None:
                pattern = next((kw.value for kw in node.keywords if kw.arg == "pattern"), None)
            if pattern is not None:
                self._add(node, "re:" + self._text(pattern))
        if (
            isinstance(func, ast.Attribute)
            and func.attr in ("startswith", "endswith")
            and node.args
            and self._normalised(func.value)
        ):
            argument = node.args[0]
            if _is_str(argument):
                self._add(node, f"{func.attr}:" + _fingerprint_list([argument.value]))  # type: ignore[attr-defined]
            elif isinstance(argument, ast.Tuple) and any(_is_str(e) for e in argument.elts):
                self._add(
                    node,
                    f"{func.attr}:"
                    + _fingerprint_list(e.value for e in argument.elts if _is_str(e)),  # type: ignore[attr-defined]
                )
        # -- (d) string-method calls with a word, on any receiver but the re module ------
        if (
            isinstance(func, ast.Attribute)
            and func.attr in SEARCH_METHODS
            and node.args
            and _is_str(node.args[0])
            and any(character.isalpha() for character in node.args[0].value)  # type: ignore[attr-defined]
            and not is_re
        ):
            self._add(node, f"{func.attr}:" + json.dumps(node.args[0].value, ensure_ascii=False))  # type: ignore[attr-defined]
        # -- (b) a word list kept as one string and split at run time --------------------
        if (
            isinstance(func, ast.Attribute)
            and func.attr in ("split", "rsplit")
            and _is_str(func.value)
        ):
            separator = node.args[0] if node.args else None
            if separator is None or _is_str(separator):
                words = _words_of_literal_split(
                    func.value.value,  # type: ignore[attr-defined]
                    separator.value if separator is not None else None,  # type: ignore[attr-defined]
                )
                if len(words) >= 2:
                    self._add(node, "wordlist:" + _fingerprint_list(words))
        # -- (c) similarity and fuzzy matching ------------------------------------------
        if self._fuzzy_matcher(func):
            self._add(node, "fuzzy:" + _compact(func))
        self.generic_visit(node)

    # -- (c) membership and equality tests -----------------------------------------
    def visit_Compare(self, node: ast.Compare) -> None:
        operands = [node.left, *node.comparators]
        for left, op, right in zip(operands, node.ops, operands[1:]):
            if isinstance(op, (ast.In, ast.NotIn)) and _is_str(left) and self._normalised(right):
                self._add(node, "in:" + json.dumps(left.value, ensure_ascii=False))  # type: ignore[attr-defined]
            if isinstance(op, (ast.Eq, ast.NotEq)):
                for literal, other in ((left, right), (right, left)):
                    if _is_str(literal) and self._normalised(other):
                        self._add(node, "eq:" + json.dumps(literal.value, ensure_ascii=False))  # type: ignore[attr-defined]
        self.generic_visit(node)

    # -- (b) literal collections ---------------------------------------------------
    def _sequence(self, node: ast.Set | ast.List | ast.Tuple) -> None:
        members = [e.value for e in node.elts if _is_str(e)]  # type: ignore[attr-defined]
        if len(members) >= 2 and not (isinstance(node, ast.Tuple) and _is_chat_message(node)):
            self._add(node, "strings:" + _fingerprint_list(members))
        self.generic_visit(node)

    def visit_Set(self, node: ast.Set) -> None:
        self._sequence(node)

    def visit_List(self, node: ast.List) -> None:
        self._sequence(node)

    def visit_Tuple(self, node: ast.Tuple) -> None:
        self._sequence(node)

    def visit_Dict(self, node: ast.Dict) -> None:
        keys = [k.value for k in node.keys if _is_str(k)]  # type: ignore[attr-defined]
        if len(keys) >= 2 and all(_is_constant(value) for value in node.values):
            self._add(node, "keys:" + _fingerprint_list(keys))
        self.generic_visit(node)


# ---------------------------------------------------------------------------------------
# Taint: natural-language text reaching a length, character-class, literal or lookup test
# ---------------------------------------------------------------------------------------


def _identifier_words(name: str) -> tuple[str, ...]:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    return tuple(word for word in spaced.lower().split("_") if word)


def is_text_field(name: str) -> bool:
    """Whether an identifier names natural-language text (see :data:`TEXT_FIELDS`)."""
    words = _identifier_words(name)
    if not words:
        return False
    joined = "_".join(words)
    if joined in NOT_TEXT_FIELDS:
        return False
    return (
        joined in TEXT_FIELDS
        or words[-1] in TEXT_FIELD_ENDINGS
        or (len(words) >= 2 and words[-2:] in TEXT_FIELD_PAIR_ENDINGS)
    )


def _is_normalised_name(name: str) -> bool:
    return any(word in NORMALISED_WORDS for word in _identifier_words(name))


def _scope_nodes(body: Iterable[ast.AST]) -> Iterator[ast.AST]:
    """Nodes of one scope: a nested def / class is yielded but its body is not entered."""
    stack: list[ast.AST] = list(body)
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        stack.extend(ast.iter_child_nodes(node))


@dataclass(eq=False)
class _Class:
    name: str
    methods: dict[str, "_Unit"] = field(default_factory=dict)
    constants: dict[str, list[ast.expr]] = field(default_factory=lambda: defaultdict(list))
    text_attrs: set[str] = field(default_factory=set)


@dataclass(eq=False)
class _Unit:
    """One scope the taint pass analyses: the module, a class body, or a function."""

    node: ast.AST
    qualname: str
    body: list[ast.stmt]
    parent: "_Unit | None"
    owner: _Class | None
    params: list[str]
    is_function: bool
    is_method: bool
    nested: dict[str, "_Unit"] = field(default_factory=dict)
    assignments: dict[str, list[ast.expr]] = field(default_factory=lambda: defaultdict(list))
    tainted_params: set[str] = field(default_factory=set)
    returns_intrinsic: bool = False
    returns_normalised: bool = False
    return_params: frozenset[str] = frozenset()
    env: "_Env | None" = None

    def text_named_params(self) -> set[str]:
        return {p for p in self.params if p not in ("self", "cls") and is_text_field(p)}

    def data_params(self) -> set[str]:
        return {p for p in self.params if p not in ("self", "cls")}


@dataclass
class _Env:
    unit: _Unit
    tainted: set[str]
    measures: set[str] = field(default_factory=set)
    normalised: set[str] = field(default_factory=set)
    elements: set[str] = field(default_factory=set)
    attrs: set[str] = field(default_factory=set)
    gathered: set[str] = field(default_factory=set)
    real: bool = False

    def size(self) -> tuple[int, ...]:
        return (
            len(self.tainted),
            len(self.measures),
            len(self.normalised),
            len(self.elements),
            len(self.attrs),
            len(self.gathered),
        )


class _Taint:
    """Same-module taint analysis; :meth:`sites` returns the sinks text reaches."""

    MAX_ROUNDS = 12

    def __init__(self, rel: str, tree: ast.Module, reported: set[int]) -> None:
        self.rel = rel
        self.reported = reported
        self.units: list[_Unit] = []
        self.classes: dict[str, _Class] = {}
        self.module = self._make_unit(tree, "<module>", tree.body, None, None, [], False, False)
        self.operator_names, self.fnmatch_names, self.unicodedata_names = self._imports(tree)

    # -- structure -----------------------------------------------------------------
    @staticmethod
    def _imports(tree: ast.Module) -> tuple[set[str], set[str], set[str]]:
        operator_names: set[str] = set()
        fnmatch_names: set[str] = set()
        unicodedata_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    bound = alias.asname or alias.name
                    {
                        "operator": operator_names,
                        "fnmatch": fnmatch_names,
                        "unicodedata": unicodedata_names,
                    }.get(alias.name, set()).add(bound)
        return operator_names, fnmatch_names, unicodedata_names

    def _make_unit(
        self,
        node: ast.AST,
        qualname: str,
        body: list[ast.stmt],
        parent: _Unit | None,
        owner: _Class | None,
        params: list[str],
        is_function: bool,
        is_method: bool,
    ) -> _Unit:
        unit = _Unit(node, qualname, body, parent, owner, params, is_function, is_method)
        self.units.append(unit)
        lexical = unit if is_function or parent is None else parent
        prefix = "" if qualname == "<module>" else qualname + "."
        for child in _scope_nodes(body):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                arguments = child.args
                names = [
                    a.arg for a in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs)
                ]
                names += [a.arg for a in (arguments.vararg, arguments.kwarg) if a is not None]
                static = any(
                    isinstance(d, ast.Name) and d.id == "staticmethod" for d in child.decorator_list
                )
                sub = self._make_unit(
                    child,
                    prefix + child.name,
                    child.body,
                    lexical,
                    owner if not is_function else None,
                    names,
                    True,
                    owner is not None and not is_function and not static,
                )
                if owner is not None and not is_function:
                    owner.methods[child.name] = sub
                else:
                    unit.nested[child.name] = sub
            elif isinstance(child, ast.ClassDef):
                info = self.classes.setdefault(child.name, _Class(child.name))
                for statement in child.body:
                    if isinstance(statement, ast.Assign):
                        for target in statement.targets:
                            if isinstance(target, ast.Name):
                                info.constants[target.id].append(statement.value)
                    elif isinstance(statement, ast.AnnAssign) and statement.value is not None:
                        if isinstance(statement.target, ast.Name):
                            info.constants[statement.target.id].append(statement.value)
                self._make_unit(
                    child, prefix + child.name, child.body, lexical, info, [], False, False
                )
            elif isinstance(child, (ast.Assign, ast.AnnAssign)) and not (
                owner is not None and not is_function
            ):
                targets = child.targets if isinstance(child, ast.Assign) else [child.target]
                if child.value is not None:
                    for target in targets:
                        if isinstance(target, ast.Name):
                            unit.assignments[target.id].append(child.value)
                        elif (
                            isinstance(target, ast.Tuple)
                            and isinstance(child.value, ast.Tuple)
                            and len(target.elts) == len(child.value.elts)
                        ):
                            for element, value in zip(target.elts, child.value.elts):
                                if isinstance(element, ast.Name):
                                    unit.assignments[element.id].append(value)
                        else:
                            for name in ast.walk(target):
                                if isinstance(name, ast.Name):
                                    unit.assignments[name.id].extend([name, name])
            elif isinstance(child, (ast.AugAssign, ast.For, ast.AsyncFor, ast.NamedExpr)):
                for name in ast.walk(child.target):
                    if isinstance(name, ast.Name):
                        unit.assignments[name.id].extend([name, name])
        for p in params:
            unit.assignments[p].extend([ast.Name(id=p), ast.Name(id=p)])
        return unit

    # -- resolution ------------------------------------------------------------------
    def _lookup(self, name: str, unit: _Unit) -> ast.expr | None:
        scope: _Unit | None = unit
        while scope is not None:
            values = scope.assignments.get(name)
            if values:
                return values[0] if len(values) == 1 else None
            scope = scope.parent
        return None

    def _class_constant(self, expr: ast.Attribute, unit: _Unit) -> ast.expr | None:
        owner = None
        if isinstance(expr.value, ast.Name):
            if expr.value.id in ("self", "cls"):
                owner = unit.owner if unit.is_method else None
            else:
                owner = self.classes.get(expr.value.id)
        if owner is not None:
            values = owner.constants.get(expr.attr)
            if values and len(values) == 1:
                return values[0]
        return None

    def _resolved(self, expr: ast.expr, unit: _Unit, depth: int = 0) -> ast.expr:
        """Follow a name or class attribute bound once to a value; else the expression."""
        while depth < 6:
            if isinstance(expr, ast.Name):
                value = self._lookup(expr.id, unit)
            elif isinstance(expr, ast.Attribute):
                value = self._class_constant(expr, unit)
            else:
                return expr
            if value is None or (
                isinstance(value, ast.Name) and isinstance(expr, ast.Name) and value.id == expr.id
            ):
                return expr
            expr, depth = value, depth + 1
        return expr

    def _callee(self, call: ast.Call, unit: _Unit) -> tuple[_Unit | None, int]:
        """The same-module function a call reaches, and how many leading parameters it skips."""
        func = call.func
        if isinstance(func, ast.Name):
            scope: _Unit | None = unit
            while scope is not None:
                if func.id in scope.nested:
                    return scope.nested[func.id], 0
                scope = scope.parent
            info = self.classes.get(func.id)
            if info is not None and "__init__" in info.methods:
                return info.methods["__init__"], 1
            return None, 0
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            if func.value.id in ("self", "cls") and unit.is_method and unit.owner is not None:
                method = unit.owner.methods.get(func.attr)
                if method is not None:
                    return method, 1 if method.is_method else 0
            info = self.classes.get(func.value.id)
            if info is not None and func.attr in info.methods:
                return info.methods[func.attr], 0
        return None, 0

    # -- expression classification -------------------------------------------------
    def _comprehension_env(self, node: ast.AST, env: _Env) -> _Env:
        inner = replace(
            env, tainted=set(env.tainted), elements=set(env.elements), gathered=set(env.gathered)
        )
        for generator in node.generators:  # type: ignore[attr-defined]
            inner.tainted |= self._bound_text(
                generator.target, generator.iter, inner, iterating=True
            )
            if self._string_collection(generator.iter, env.unit):
                inner.elements |= {
                    n.id for n in ast.walk(generator.target) if isinstance(n, ast.Name)
                }
        return inner

    def _bound_text(self, target: ast.AST, value: ast.AST, env: _Env, iterating: bool) -> set[str]:
        """Names in ``target`` that hold text once ``value`` (or, iterating, an item) is bound.

        A plain name takes the value's taint. Unpacking is element-wise when the value is a
        literal tuple, and whole when it is a string method's result (``a, b = t.split(",", 1)``);
        ``enumerate(text)`` binds its index untainted. Any other tuple -- a record, a function's
        tuple, ``d.items()`` -- is opaque, and only a name that itself names text takes its taint.
        """
        if isinstance(target, ast.Name):
            return {target.id} if self.tainted(value, env) else set()
        if isinstance(target, ast.Starred):
            return self._bound_text(target.value, value, env, iterating)
        if not isinstance(target, (ast.Tuple, ast.List)):
            return set()
        names = [n.id for n in ast.walk(target) if isinstance(n, ast.Name)]
        if not self.tainted(value, env):
            return set()
        if (
            not iterating
            and isinstance(value, (ast.Tuple, ast.List))
            and len(value.elts) == len(target.elts)
        ):
            found: set[str] = set()
            for element_target, element_value in zip(target.elts, value.elts):
                found |= self._bound_text(element_target, element_value, env, False)
            return found
        call = value if isinstance(value, ast.Call) else None
        if (
            call is not None
            and isinstance(call.func, ast.Attribute)
            and call.func.attr in ("split", "rsplit", "partition", "rpartition", "splitlines")
            and self.tainted(call.func.value, env)
        ):
            return set(names)
        if (
            iterating
            and call is not None
            and isinstance(call.func, ast.Name)
            and call.func.id == "enumerate"
        ):
            return {
                n.id
                for element in target.elts[1:]
                for n in ast.walk(element)
                if isinstance(n, ast.Name)
            }
        return {name for name in names if is_text_field(name)}

    def _iterates_text(self, node: ast.AST, env: _Env) -> bool:
        return isinstance(node, COMPREHENSIONS) and any(
            self.tainted(generator.iter, env)
            for generator in node.generators  # type: ignore[attr-defined]
        )

    def tainted(self, expr: ast.AST | None, env: _Env, depth: int = 0) -> bool:
        """Whether ``expr`` evaluates to natural-language text (or a collection of it)."""
        if expr is None or depth > 40:
            return False
        nxt = depth + 1
        if isinstance(expr, ast.Name):
            return self._name_tainted(expr.id, env)
        if isinstance(expr, ast.Attribute):
            if is_text_field(expr.attr):
                return True
            path = _compact(expr)
            if path in env.attrs:
                return True
            return (
                isinstance(expr.value, ast.Name)
                and expr.value.id == "self"
                and env.unit.owner is not None
                and path in env.unit.owner.text_attrs
            )
        if isinstance(expr, ast.Subscript):
            if _is_str(expr.slice) and is_text_field(expr.slice.value):  # type: ignore[attr-defined]
                return True
            return self.tainted(expr.value, env, nxt)
        if isinstance(expr, ast.Call):
            return self._call_tainted(expr, env, nxt)
        if isinstance(expr, ast.BinOp):
            return self.tainted(expr.left, env, nxt) or self.tainted(expr.right, env, nxt)
        if isinstance(expr, ast.BoolOp):
            return any(self.tainted(value, env, nxt) for value in expr.values)
        if isinstance(expr, ast.IfExp):
            return self.tainted(expr.body, env, nxt) or self.tainted(expr.orelse, env, nxt)
        if isinstance(expr, ast.JoinedStr):
            return any(
                isinstance(part, ast.FormattedValue) and self.tainted(part.value, env, nxt)
                for part in expr.values
            )
        if isinstance(expr, (ast.List, ast.Tuple, ast.Set)):
            return any(self.tainted(element, env, nxt) for element in expr.elts)
        if isinstance(expr, (ast.ListComp, ast.SetComp, ast.GeneratorExp)):
            return self.tainted(expr.elt, self._comprehension_env(expr, env), nxt)
        if isinstance(expr, ast.DictComp):
            inner = self._comprehension_env(expr, env)
            return self.tainted(expr.key, inner, nxt) or self.tainted(expr.value, inner, nxt)
        if isinstance(expr, (ast.Starred, ast.NamedExpr, ast.Await)):
            return self.tainted(expr.value, env, nxt)
        return False

    def _name_tainted(self, name: str, env: _Env) -> bool:
        if name in env.tainted:
            return True
        scope = env.unit.parent
        while scope is not None:
            if scope.env is not None and name in scope.env.tainted:
                return True
            scope = scope.parent
        return False

    def _call_tainted(self, call: ast.Call, env: _Env, depth: int) -> bool:
        func = call.func
        arguments = [*call.args, *(kw.value for kw in call.keywords)]
        any_argument = any(self.tainted(a, env, depth) for a in arguments)
        if isinstance(func, ast.Attribute):
            if (
                func.attr == "get"
                and call.args
                and _is_str(call.args[0])
                and is_text_field(call.args[0].value)
            ):  # type: ignore[attr-defined]
                return True
            if func.attr in TEXT_FUNCTIONS and any_argument:
                return True
            if func.attr == "join" and any_argument:
                return True
            if func.attr in MATCH_METHODS and any_argument:
                return True
            if func.attr not in NON_TEXT_METHODS and self.tainted(func.value, env, depth):
                return True
        if isinstance(func, ast.Name):
            if (
                func.id == "getattr"
                and len(call.args) >= 2
                and _is_str(call.args[1])
                and is_text_field(call.args[1].value)
            ):  # type: ignore[attr-defined]
                return True
            if (func.id in TEXT_BUILTINS or func.id in TEXT_FUNCTIONS) and any_argument:
                return True
        callee, skip = self._callee(call, env.unit)
        if callee is not None:
            return callee.returns_intrinsic or any(
                parameter in callee.return_params and self.tainted(argument, env, depth)
                for parameter, argument in self._arguments(call, callee, skip)
            )
        return False

    @staticmethod
    def _arguments(call: ast.Call, callee: _Unit, skip: int) -> Iterator[tuple[str, ast.expr]]:
        """``(parameter, argument)`` for each argument of ``call`` that binds a named parameter."""
        positional = callee.params[skip:]
        for index, argument in enumerate(call.args):
            if isinstance(argument, ast.Starred) or index >= len(positional):
                break
            yield positional[index], argument
        for keyword in call.keywords:
            if keyword.arg in callee.params:
                yield keyword.arg, keyword.value

    def measure(self, expr: ast.AST, env: _Env, depth: int = 0) -> bool:
        """Whether ``expr`` is a length or count of text, or arithmetic on one."""
        if depth > 20:
            return False
        if isinstance(expr, ast.Name):
            return expr.id in env.measures
        if isinstance(expr, ast.Call):
            func, args = expr.func, expr.args
            if isinstance(func, ast.Name):
                if func.id == "ord" and args and self.tainted(args[0], env):
                    return True
                if (
                    func.id == "len"
                    and args
                    and self.tainted(args[0], env)
                    and not self._gathered(args[0], env)
                ):
                    return True
                if func.id == "sum" and args and self._iterates_text(args[0], env):
                    return True
                if func.id in MEASURE_WRAPPERS and any(
                    self.measure(a, env, depth + 1) for a in args
                ):
                    return True
            if (
                isinstance(func, ast.Attribute)
                and func.attr in MEASURE_METHODS
                and self.tainted(func.value, env)
            ):
                return True
            return False
        if isinstance(expr, ast.BinOp):
            return self.measure(expr.left, env, depth + 1) or self.measure(
                expr.right, env, depth + 1
            )
        if isinstance(expr, ast.UnaryOp):
            return self.measure(expr.operand, env, depth + 1)
        if isinstance(expr, ast.IfExp):
            return self.measure(expr.body, env, depth + 1) or self.measure(
                expr.orelse, env, depth + 1
            )
        return False

    def _gathered(self, expr: ast.AST, env: _Env) -> bool:
        """A collection of separate texts, one per record, rather than one text or its pieces."""
        if isinstance(expr, ast.Name):
            return expr.id in env.gathered
        field_name = None
        if isinstance(expr, ast.Attribute):
            field_name = expr.attr
        elif isinstance(expr, ast.Subscript) and _is_str(expr.slice):
            field_name = expr.slice.value  # type: ignore[attr-defined]
        elif (
            isinstance(expr, ast.Call)
            and isinstance(expr.func, ast.Attribute)
            and expr.func.attr == "get"
            and expr.args
            and _is_str(expr.args[0])
        ):
            field_name = expr.args[0].value  # type: ignore[attr-defined]
        if field_name is not None:
            words = _identifier_words(field_name)
            return bool(words) and words[-1] in GATHERED_ENDINGS
        if isinstance(expr, (ast.List, ast.Tuple, ast.Set)):
            return any(self.tainted(element, env) for element in expr.elts)
        if isinstance(expr, (ast.ListComp, ast.SetComp, ast.GeneratorExp)):
            return self.tainted(expr, env) and not self._iterates_text(expr, env)
        if (
            isinstance(expr, ast.Call)
            and isinstance(expr.func, ast.Name)
            and expr.func.id in ("list", "sorted", "set", "frozenset", "tuple")
        ):
            return bool(expr.args) and self._gathered(expr.args[0], env)
        return False

    def _normalised(self, expr: ast.AST, env: _Env) -> bool:
        """Case-folded or Unicode-normalised, directly or by a same-module helper returning so."""
        for node in ast.walk(expr):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute) and node.func.attr in CASE_NORMALISERS:
                    return True
                callee = self._callee(node, env.unit)[0]
                if callee is not None and callee.returns_normalised:
                    return True
            if isinstance(node, ast.Name) and (
                node.id in env.normalised or _is_normalised_name(node.id)
            ):
                return True
        return False

    def _word_bag(self, expr: ast.AST, env: _Env) -> bool:
        """Text, or a value built by splitting / case-folding / regex-tokenising something."""
        if self.tainted(expr, env):
            return True
        resolved = self._resolved(expr, env.unit) if isinstance(expr, ast.Name) else expr
        return any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("split", "rsplit", "findall", *CASE_NORMALISERS)
            for node in ast.walk(resolved)
        )

    def _number(self, expr: ast.AST, unit: _Unit) -> float | None:
        """The value of a number constant (``nan`` for an unresolved UPPER_CASE name)."""
        resolved = (
            self._resolved(expr, unit) if isinstance(expr, (ast.Name, ast.Attribute)) else expr
        )
        if isinstance(resolved, ast.UnaryOp) and isinstance(resolved.op, ast.USub):
            inner = self._number(resolved.operand, unit)
            return None if inner is None else -inner
        if (
            isinstance(resolved, ast.Constant)
            and isinstance(resolved.value, (int, float))
            and not isinstance(resolved.value, bool)
        ):
            return float(resolved.value)
        name = (
            resolved.id
            if isinstance(resolved, ast.Name)
            else resolved.attr
            if isinstance(resolved, ast.Attribute)
            else ""
        )
        if name and name.lstrip("_").isupper():
            return float("nan")
        return None

    def _string_collection(self, expr: ast.AST, unit: _Unit, depth: int = 0) -> bool:
        """A literal collection of strings, a literal split, or a name bound to one."""
        if depth > 6:
            return False
        if isinstance(expr, (ast.Name, ast.Attribute)):
            resolved = self._resolved(expr, unit)
            return resolved is not expr and self._string_collection(resolved, unit, depth + 1)
        if isinstance(expr, (ast.Set, ast.List, ast.Tuple)):
            return (
                bool(expr.elts)
                and any(_is_str(e) for e in expr.elts)
                and all(isinstance(e, ast.Constant) for e in expr.elts)
            )
        if isinstance(expr, ast.Dict):
            return any(_is_str(k) for k in expr.keys)
        if isinstance(expr, ast.Call):
            func = expr.func
            if (
                isinstance(func, ast.Name)
                and func.id in ("frozenset", "set", "tuple", "list", "sorted")
                and len(expr.args) == 1
            ):
                return self._string_collection(expr.args[0], unit, depth + 1)
            if isinstance(func, ast.Attribute) and func.attr == "fromkeys" and expr.args:
                return self._string_collection(expr.args[0], unit, depth + 1)
            if (
                isinstance(func, ast.Attribute)
                and func.attr in ("split", "rsplit")
                and _is_str(func.value)
            ):
                return True
            return False
        if isinstance(expr, (ast.ListComp, ast.SetComp, ast.GeneratorExp)):
            return all(self._string_collection(g.iter, unit, depth + 1) for g in expr.generators)
        return False

    def _string_dict(self, expr: ast.AST, unit: _Unit) -> bool:
        resolved = (
            self._resolved(expr, unit) if isinstance(expr, (ast.Name, ast.Attribute)) else expr
        )
        return isinstance(resolved, ast.Dict) and any(_is_str(k) for k in resolved.keys)

    def _literalish(self, expr: ast.AST, env: _Env) -> bool:
        """A string literal, a name bound to one, a member of a literal collection, or a tuple."""
        if _is_str(expr):
            return expr.value != ""  # type: ignore[attr-defined]
        if isinstance(expr, ast.Name) and expr.id in env.elements:
            return True
        if isinstance(expr, ast.Tuple):
            return bool(expr.elts) and all(self._literalish(e, env) for e in expr.elts)
        if isinstance(expr, (ast.Name, ast.Attribute)):
            resolved = self._resolved(expr, env.unit)
            if resolved is not expr:
                return self._literalish(resolved, env) or self._string_collection(
                    resolved, env.unit
                )
        return False

    # -- environments --------------------------------------------------------------
    def _walk(self, node: ast.AST, env: _Env, visit: Callable[[ast.AST, _Env], None]) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            return
        if isinstance(node, COMPREHENSIONS):
            inner = self._comprehension_env(node, env)
            visit(node, env)
            for child in ast.iter_child_nodes(node):
                self._walk(child, inner, visit)
            return
        visit(node, env)
        for child in ast.iter_child_nodes(node):
            self._walk(child, env, visit)

    def _walk_unit(self, unit: _Unit, env: _Env, visit: Callable[[ast.AST, _Env], None]) -> None:
        for statement in unit.body:
            self._walk(statement, env, visit)

    def _bind(self, node: ast.AST, env: _Env) -> None:
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr, ast.AugAssign)):
            value = node.value
            if value is None:
                return
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            text = self.tainted(value, env)
            size = self.measure(value, env)
            normalised = text and self._normalised(value, env)
            for target in targets:
                if isinstance(target, ast.Attribute):
                    if text:
                        path = _compact(target)
                        env.attrs.add(path)
                        if env.real and path.startswith("self.") and env.unit.owner is not None:
                            env.unit.owner.text_attrs.add(path)
                    continue
                if isinstance(target, ast.Subscript):
                    # ``seen[key] = text`` fills a collection of text; ``rule["name"] = text``
                    # writes one field of a record, which does not make the record text.
                    # The key's own names are never bound.
                    if text and not _is_str(target.slice) and isinstance(target.value, ast.Name):
                        env.tainted.add(target.value.id)
                    continue
                bound = self._bound_text(target, value, env, iterating=False)
                env.tainted |= bound
                if isinstance(target, ast.Name):
                    if text and self._gathered(value, env):
                        env.gathered.add(target.id)
                    if size:
                        env.measures.add(target.id)
                    if normalised:
                        env.normalised.add(target.id)
                else:
                    env.normalised |= bound if normalised else set()
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            env.tainted |= self._bound_text(node.target, node.iter, env, iterating=True)
            if self._string_collection(node.iter, env.unit):
                env.elements |= {n.id for n in ast.walk(node.target) if isinstance(n, ast.Name)}

    def _environment(self, unit: _Unit, params: set[str], real: bool = False) -> _Env:
        env = _Env(unit, set(params), real=real)
        env.normalised |= {p for p in params if _is_normalised_name(p)}
        env.gathered |= {
            p
            for p in params
            if _identifier_words(p)[-1:] and _identifier_words(p)[-1] in GATHERED_ENDINGS
        }
        for _ in range(8):
            before = env.size()
            self._walk_unit(unit, env, self._bind)
            if env.size() == before:
                break
        return env

    def _returns_text(self, unit: _Unit, env: _Env) -> bool:
        found = False

        def visit(node: ast.AST, scope: _Env) -> None:
            nonlocal found
            if isinstance(node, (ast.Return, ast.Yield, ast.YieldFrom)) and node.value is not None:
                found = found or self.tainted(node.value, scope)

        self._walk_unit(unit, env, visit)
        return found

    def _propagate(self, unit: _Unit, env: _Env) -> bool:
        changed = False

        def visit(node: ast.AST, scope: _Env) -> None:
            nonlocal changed
            if not isinstance(node, ast.Call):
                return
            callee, skip = self._callee(node, unit)
            if callee is None:
                return
            for parameter, argument in self._arguments(node, callee, skip):
                if parameter not in callee.tainted_params and self.tainted(argument, scope):
                    callee.tainted_params.add(parameter)
                    changed = True

        self._walk_unit(unit, env, visit)
        return changed

    def _returns_normalised(self, unit: _Unit, env: _Env) -> bool:
        found = False

        def visit(node: ast.AST, scope: _Env) -> None:
            nonlocal found
            if isinstance(node, ast.Return) and node.value is not None:
                found = found or self._normalised(node.value, scope)

        self._walk_unit(unit, env, visit)
        return found

    def _return_summary(self, unit: _Unit) -> tuple[bool, frozenset[str]]:
        """Whether ``unit`` returns text on its own, and else which parameters it returns text from.

        A parameter that names text is a source, so a helper declaring ``text`` returns text
        whatever it is called with. Any other parameter carries text into the return value
        only when the argument bound to it is text, which is checked one parameter at a time.
        """
        named = unit.text_named_params()
        if self._returns_text(unit, self._environment(unit, named)):
            return True, frozenset()
        others = unit.data_params() - named
        if not others or not self._returns_text(unit, self._environment(unit, named | others)):
            return False, frozenset()
        return False, frozenset(
            p for p in others if self._returns_text(unit, self._environment(unit, named | {p}))
        )

    def analyse(self) -> None:
        for unit in self.units:
            unit.tainted_params = unit.text_named_params()
        for _ in range(self.MAX_ROUNDS):
            changed = False
            for unit in self.units:
                unit.env = self._environment(unit, unit.tainted_params, real=True)
                changed |= self._propagate(unit, unit.env)
                if unit.is_function:
                    summary = self._return_summary(unit)
                    if summary != (unit.returns_intrinsic, unit.return_params):
                        unit.returns_intrinsic, unit.return_params = summary
                        changed = True
                    normalised = self._returns_normalised(unit, unit.env)
                    if normalised != unit.returns_normalised:
                        unit.returns_normalised = normalised
                        changed = True
            if not changed:
                break

    # -- sinks -----------------------------------------------------------------------
    def sites(self) -> list[Site]:
        self.analyse()
        found: list[Site] = []
        for unit in self.units:
            symbol = (
                unit.qualname
                if unit.is_function
                else "<module>"
                if unit.parent is None
                else unit.qualname
            )
            seen: set[tuple[int, str]] = set()

            def add(node: ast.AST, kind: str, unit_symbol: str = symbol) -> None:
                if id(node) in self.reported or (id(node), kind) in seen:
                    return
                seen.add((id(node), kind))
                found.append(
                    Site(
                        self.rel, f"{kind}:{_compact(node)}", node.lineno, unit_symbol, unit_symbol
                    )
                )  # type: ignore[attr-defined]

            def visit(node: ast.AST, env: _Env) -> None:
                for kind in self._sink_kinds(node, env):
                    add(node, kind)

            assert unit.env is not None
            self._walk_unit(unit, unit.env, visit)
        return found

    def _sink_kinds(self, node: ast.AST, env: _Env) -> Iterator[str]:
        unit = env.unit
        if isinstance(node, ast.Compare):
            operands = [node.left, *node.comparators]
            for left, op, right in zip(operands, node.ops, operands[1:]):
                if isinstance(op, ORDERINGS):
                    for side, other, flipped in ((left, right, False), (right, left, True)):
                        value = self._number(other, unit)
                        if (
                            value is not None
                            and self.measure(side, env)
                            and not self._emptiness(op, value, flipped)
                        ):
                            yield "length"
                if isinstance(op, (ast.In, ast.NotIn)):
                    if self._literalish(left, env) and self.tainted(right, env):
                        yield "literal"
                    elif self.tainted(left, env):
                        if self._string_collection(right, unit):
                            yield "literal"
                        elif self._normalised(left, env):
                            yield "textmatch"
                if isinstance(op, (ast.Eq, ast.NotEq)):
                    for literal, other in ((left, right), (right, left)):
                        if self._literalish(literal, env) and self.tainted(other, env):
                            yield "literal"
                    if (
                        self.tainted(left, env)
                        and self.tainted(right, env)
                        and (self._normalised(left, env) or self._normalised(right, env))
                    ):
                        yield "textmatch"
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                receiver_text = self.tainted(func.value, env)
                if receiver_text and func.attr in STR_PREDICATES:
                    yield "charclass"
                if (
                    receiver_text
                    and func.attr in AFFIX_METHODS
                    and node.args
                    and self._literalish(node.args[0], env)
                ):
                    yield "literal"
                if (
                    receiver_text
                    and func.attr == "translate"
                    and node.args
                    and self._letter_table(node.args[0], unit)
                ):
                    yield "literal"
                if (
                    func.attr == "get"
                    and node.args
                    and self.tainted(node.args[0], env)
                    and self._string_dict(func.value, unit)
                ):
                    yield "lookup"
                if isinstance(func.value, ast.Name):
                    module = func.value.id
                    if (
                        module in self.unicodedata_names
                        and func.attr == "category"
                        and node.args
                        and self.tainted(node.args[0], env)
                    ):
                        yield "charclass"
                    if (
                        module in self.operator_names
                        and func.attr == "contains"
                        and len(node.args) == 2
                    ):
                        if self._containment(node.args[0], node.args[1], env):
                            yield "literal"
                    if (
                        module in self.fnmatch_names
                        and func.attr in ("fnmatch", "fnmatchcase")
                        and node.args
                    ):
                        if self.tainted(node.args[0], env):
                            yield "literal"
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            # a token-overlap ratio, len(a & b) / ..., over word bags -- not over id sets
            numerator = node.left
            if (
                isinstance(numerator, ast.Call)
                and isinstance(numerator.func, ast.Name)
                and numerator.func.id == "len"
                and numerator.args
            ):
                overlap = numerator.args[0]
                if isinstance(overlap, ast.BinOp) and isinstance(overlap.op, ast.BitAnd):
                    operands = [overlap.left, overlap.right]
                elif (
                    isinstance(overlap, ast.Call)
                    and isinstance(overlap.func, ast.Attribute)
                    and overlap.func.attr == "intersection"
                ):
                    operands = [overlap.func.value, *overlap.args]
                else:
                    operands = []
                if operands and any(self._word_bag(operand, env) for operand in operands):
                    yield "fuzzy"
        elif isinstance(node, ast.Subscript):
            if (
                isinstance(node.ctx, ast.Load)
                and self.tainted(node.slice, env)
                and self._string_dict(node.value, unit)
            ):
                yield "lookup"
        elif isinstance(node, ast.Match):
            if self.tainted(node.subject, env) and any(
                isinstance(pattern, ast.MatchValue) and _is_str(pattern.value)
                for case in node.cases
                for pattern in ast.walk(case.pattern)
            ):
                yield "literal"

    def _containment(self, container: ast.AST, member: ast.AST, env: _Env) -> bool:
        return (self.tainted(container, env) and self._literalish(member, env)) or (
            self._string_collection(container, env.unit) and self.tainted(member, env)
        )

    def _letter_table(self, expr: ast.AST, unit: _Unit) -> bool:
        resolved = self._resolved(expr, unit) if isinstance(expr, ast.Name) else expr
        return any(
            _is_str(node) and any(c.isalpha() for c in node.value)  # type: ignore[attr-defined]
            for node in ast.walk(resolved)
        )

    @staticmethod
    def _emptiness(op: ast.cmpop, value: float, flipped: bool) -> bool:
        """``len(x) == 0`` / ``> 0`` / ``>= 1`` / ``< 1`` and their mirror images."""
        if value == 0:
            return True
        if value == 1:
            if flipped:
                return isinstance(op, (ast.LtE, ast.Gt))
            return isinstance(op, (ast.GtE, ast.Lt))
        return False


# ---------------------------------------------------------------------------------------
# Data files
# ---------------------------------------------------------------------------------------


def _is_word(value: object) -> bool:
    return isinstance(value, str) and any(character.isalpha() for character in value)


def _data_words(path: Path) -> list[str]:
    """Word keys and word array members in a data file."""
    if path.suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
    elif path.suffix in (".yaml", ".yml"):
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    else:
        return [line for line in path.read_text(encoding="utf-8").splitlines() if _is_word(line)]
    words: list[str] = []
    stack: list[object] = [data]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            words.extend(key for key in item if _is_word(key))
            stack.extend(item.values())
        elif isinstance(item, list):
            words.extend(member for member in item if _is_word(member))
            stack.extend(member for member in item if isinstance(member, (dict, list)))
    return words


def data_file_sites(paths: Iterable[Path]) -> list[Site]:
    """``datafile:`` sites: a data file holding two or more word keys or word members."""
    sites = []
    for path in paths:
        if path.suffix not in DATA_SUFFIXES:
            continue
        words = _data_words(path)
        if len(words) >= 2:
            digest = hashlib.sha256("\n".join(sorted(words)).encode()).hexdigest()[:16]
            rel = path.relative_to(ROOT).as_posix()
            sites.append(
                Site(rel, f"datafile:{len(words)} words sha256={digest}", 0, "<data>", "<data>")
            )
    return sites


# ---------------------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------------------


def _ledger_entries() -> list[dict[str, str]]:
    return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))["entries"]


def scanned_files() -> list[Path]:
    """``src/**/*.py``, the delivery-path scripts, and every ``.py`` file the ledger names."""
    files = set(SCAN_DIRECTORY.rglob("*.py")) | set(DELIVERY_SCRIPTS)
    files |= {ROOT / entry["file"] for entry in _ledger_entries() if entry["file"].endswith(".py")}
    return sorted(files)


def scanned_data_files() -> list[Path]:
    return sorted(
        path
        for path in SCAN_DIRECTORY.rglob("*")
        if path.is_file() and path.suffix in DATA_SUFFIXES and "__pycache__" not in path.parts
    )


def collect_sites(files: Iterable[Path] | None = None) -> list[Site]:
    paths = tuple(files) if files is not None else (*scanned_files(), *scanned_data_files())
    return list(_scan(paths))


@functools.lru_cache(maxsize=8)
def _scan(paths: tuple[Path, ...]) -> tuple[Site, ...]:
    """:func:`scan_paths`, cached because checks 1 and 2 read the same full scan."""
    return scan_paths(paths)


def scan_paths(paths: Iterable[Path]) -> tuple[Site, ...]:
    """Every site in ``paths``, read from disk now."""
    sites: list[Site] = []
    for path in paths:
        if path.suffix != ".py":
            sites.extend(data_file_sites([path]))
            continue
        rel = path.relative_to(ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        collector = _Collector(rel, tree)
        collector.visit(tree)
        sites.extend(collector.sites)
        sites.extend(_Taint(rel, tree, collector.reported).sites())
    return tuple(sites)


# ---------------------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------------------


def _pending_key(entry: dict[str, str]) -> tuple[str, str, str]:
    return (entry["file"], entry["symbol"], entry["sink"])


def load_ledger() -> list[dict[str, str]]:
    entries = _ledger_entries()
    seen: set[tuple[str, ...]] = set()
    problems = []
    for entry in entries:
        kind = entry.get("kind")
        if kind == "pending":
            missing = [
                f
                for f in ("symbol", "sink", "decides", "status")
                if not (entry.get(f) or "").strip()
            ]
            if missing:
                problems.append(f"pending entry lacks {missing}: {entry}")
                continue
            key: tuple[str, ...] = ("pending", *_pending_key(entry))
            if entry["status"] not in STATUSES:
                problems.append(f"status must be live or dormant: {key}")
        elif kind == "allowed":
            if not (entry.get("fingerprint") or "").strip():
                problems.append(f"allowed entry lacks a fingerprint: {entry}")
                continue
            key = ("allowed", entry["file"], entry["fingerprint"])
        else:
            problems.append(f"kind must be allowed or pending: {entry}")
            continue
        if key in seen:
            problems.append(f"duplicate entry {key}")
        seen.add(key)
        if not entry.get("inventory_id"):
            problems.append(f"inventory_id missing: {key}")
        if not (entry.get("reason") or "").strip():
            problems.append(f"reason missing: {key}")
    assert not problems, "malformed ledger:\n" + "\n".join(problems)
    return entries


def _canonical_baseline_keys(keys: Iterable[Iterable[str]]) -> str:
    return json.dumps(sorted(list(k) for k in keys), ensure_ascii=False)


def baseline_digest(keys: Iterable[Iterable[str]]) -> str:
    return hashlib.sha256(_canonical_baseline_keys(keys).encode()).hexdigest()


def _covered(site: Site, allowed: set[tuple[str, str]], pending: set[tuple[str, str, str]]) -> bool:
    return (site.file, site.fingerprint) in allowed or (
        site.file,
        site.symbol,
        site.sink,
    ) in pending


def _describe(key: tuple[str, str], sites: list[Site]) -> str:
    lines = ",".join(str(s.line) for s in sorted(sites, key=lambda s: s.line))
    symbols = ", ".join(sorted({s.symbol for s in sites}))
    fingerprint = key[1] if len(key[1]) <= 240 else key[1][:240] + "..."
    return f"  {key[0]}:{lines} [{symbols}] {fingerprint}"


def test_should_list_every_text_rule_site_in_the_ledger_when_src_is_scanned():
    files = scanned_files()
    assert len(files) > 100, f"scan found only {len(files)} files under {SCAN_DIRECTORY}"
    assert all(path.is_file() for path in DELIVERY_SCRIPTS), DELIVERY_SCRIPTS
    entries = load_ledger()
    allowed = {(e["file"], e["fingerprint"]) for e in entries if e["kind"] == "allowed"}
    pending = {_pending_key(e) for e in entries if e["kind"] == "pending"}
    unlisted: dict[tuple[str, str], list[Site]] = defaultdict(list)
    for site in collect_sites():
        if not _covered(site, allowed, pending):
            unlisted[(site.file, site.fingerprint)].append(site)
    assert not unlisted, (
        f"{len(unlisted)} text-rule site(s) are not in {LEDGER_PATH.name}.\n"
        "A regex, word list, literal, length, character-class or similarity test that reads "
        "natural language to decide meaning is forbidden (AGENTS.md § PROMPTS AND TEXT RULES): "
        "put the decision in an extraction schema field with a source span instead. If the "
        "site only parses a machine format, add an `allowed` entry with a one-line reason.\n"
        + "\n".join(_describe(key, sites) for key, sites in sorted(unlisted.items()))
    )


def test_should_find_every_pending_rule_in_the_code_when_it_is_still_listed():
    present = {(site.file, site.symbol, site.sink) for site in collect_sites()}
    gone = [
        entry
        for entry in load_ledger()
        if entry["kind"] == "pending" and _pending_key(entry) not in present
    ]
    assert not gone, (
        f"{len(gone)} pending rule(s) no longer have a site with their sink in their symbol; "
        f"delete them from {LEDGER_PATH.name}:\n"
        + "\n".join(f"  {e['inventory_id']} {e['file']} {e['symbol']} {e['sink']}" for e in gone)
    )


def test_should_not_allow_any_site_when_it_lives_in_a_rule_module():
    entries = load_ledger()
    pending_files = {e["file"] for e in entries if e["kind"] == "pending"}
    stale = sorted(RULE_MODULES - pending_files)
    assert not stale, (
        f"these rule modules hold no pending rule any more; remove them from RULE_MODULES: {stale}"
    )
    allowed_in_rule_modules = [
        e for e in entries if e["kind"] == "allowed" and e["file"] in RULE_MODULES
    ]
    assert not allowed_in_rule_modules, (
        "these modules exist only to hold a text rule; their sites are pending removal, "
        "not allowed:\n"
        + "\n".join(
            f"  {e['inventory_id']} {e['file']} {e['fingerprint'][:240]}"
            for e in allowed_in_rule_modules
        )
    )


def test_should_not_grow_the_pending_list_when_the_baseline_is_unchanged():
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    keys = [tuple(key) for key in baseline["keys"]]
    assert baseline_digest(keys) == PENDING_BASELINE_SHA256, (
        f"{BASELINE_PATH.name} changed without PENDING_BASELINE_SHA256 changing. "
        "Growing the pending list is a reviewed step: change both in one commit and say why."
    )
    grown = sorted(
        _pending_key(e)
        for e in load_ledger()
        if e["kind"] == "pending" and _pending_key(e) not in set(keys)
    )
    assert not grown, (
        "pending entries that are not in the recorded baseline -- the pending list only shrinks; "
        "a new text rule is removed, not ledgered:\n" + "\n".join(f"  {key}" for key in grown)
    )
