"""No new rule may read natural language through a regex, a word list or a literal test.

The user's standing rule (``AGENTS.md`` § PROMPTS AND TEXT RULES, rule 2): no regex,
word list, keyword set or substring test over protocol, criterion, description, entity
or LLM free text may decide what that text means. Meaning belongs in an extraction
schema field whose source span the code checks against ``protocolLine``. Parsing a
machine format (UCUM, JSON, ids, CIRCE / OMOP field names, LOINC attributes, numbers)
is not covered by the rule.

The rules that existed on 2026-10-12 are inventoried in
``docs/inventory/2026-10-12_text_rules.{md,json}``. Each site they produce is listed in
``tests/fixtures/text_rule_ledger.json`` as ``pending`` (scheduled for removal) and every
machine-format site as ``allowed`` with a one-line reason.

WHAT IS COLLECTED
-----------------
Every ``.py`` file under ``src/`` plus ``scripts/verify_circe_delivery.py`` is parsed
with ``ast``. A *text-rule site* is one of:

(a) ``re:`` -- the pattern argument of ``re.compile / search / match / fullmatch / sub /
    subn / findall / finditer / split``. A name bound once to a string expression in
    the same module (or the enclosing function) is resolved, so a pattern kept in a
    module-level constant is fingerprinted by its text. An argument that cannot be
    resolved is fingerprinted by its source, in braces.
(b) ``strings:`` -- a set, list or tuple literal holding two or more string constants,
    at module, class or function level, except a LangChain chat message
    ``(role, "...")`` whose role is system / user / human / ai / assistant (prompts have
    their own guard); ``keys:`` -- a dict literal with two or more string-constant keys
    whose values are all constant: a str / number / bool / None, constant arithmetic on
    numbers, or a tuple / list / set / frozenset / dict of those. That is a lookup
    table, the shape a word-to-meaning rule takes; a dict with a computed value is a
    record being built (a JSON payload) and is not collected.
(c) ``in: / startswith: / endswith: / eq:`` -- a literal test on normalised text:
    ``"lit" in X``, ``X.startswith(lit)``, ``X.endswith(lit)`` and ``X == "lit"``
    (or ``!=`` / ``not in``), where ``X`` is a ``.lower() / .casefold() / .upper() /
    .strip() / .lstrip() / .rstrip() / .title()`` call, or a name assigned from such a
    call in the same or an enclosing scope. Normalising case or whitespace is what code
    does to free text before testing it for words; a dict-key test (``"CodesetId" in
    payload``) is not normalised and is not collected.
(d) ``split: / rsplit: / replace: / find: / rfind: / count: / partition: /
    rpartition: / index: / rindex:`` -- that string method called, on any receiver,
    with a first argument that is a string literal containing a letter. ``re.split`` is
    already a site under (a) and is not collected again.

A site is keyed by ``(file, fingerprint)``. The fingerprint is the pattern text, the
sorted string members, or the tested literal -- never a line number, so editing
unrelated code does not churn the ledger.

WHAT IT MISSES
--------------
Literal ``in / startswith / endswith / ==`` tests on text that was not normalised first; a lookup
table whose values are names or attributes rather than constants; a word list held as a
single delimited string and split at run time, unless it reaches ``re``, a collection
literal or a (d) call; names imported from another module, which a pattern argument
does not resolve (fingerprinted as ``{NAME}``).

THE THREE CHECKS
----------------
1. Every collected site has a ledger entry. This is what blocks a new rule.
2. Every ``pending`` entry still exists in the code, so the pending list only shrinks
   and stays honest: delete the entry when its rule is removed.
3. No ``allowed`` entry lives in a module whose only role is a text rule, so a rule
   cannot be reclassified as machine-format parsing to make check 1 pass.
"""

from __future__ import annotations

import ast
import json
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER_PATH = ROOT / "tests" / "fixtures" / "text_rule_ledger.json"
SCAN_DIRECTORY = ROOT / "src"
EXTRA_FILES = (ROOT / "scripts" / "verify_circe_delivery.py",)

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

# Modules whose only role is a text rule of inventory class A, S or C (or a dead
# Class-A-shaped rule), so none of their sites may be ``allowed``. Some hold machine-format
# sites as well; those stay ``pending`` until the module's rule is replaced, and the module
# leaves this list then.
RULE_MODULES = frozenset(
    {
        "src/services/dose_stability.py",
        "src/services/entity_exception.py",
        "src/services/route_qualifier.py",
        "src/agents/agent1/temporal_grounding.py",
        "src/utils/criterion_seed.py",
        "src/utils/naming_words.py",
        "src/agents/agent1/eligibility_section.py",
        "src/services/range_disjunction_repair.py",
        "src/services/restated_absence_repair.py",
        "src/services/dose_form_route.py",
        "src/utils/disease_anchor.py",
        "src/agents/agent2/complexity_router.py",
        "src/agents/agent2/rule_extractor.py",
        "src/services/emission_stability.py",
    }
)


@dataclass(frozen=True)
class Site:
    file: str
    fingerprint: str
    line: int
    scope: str


def _is_str(node: ast.AST | None) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _fingerprint_list(values: Iterable[str]) -> str:
    return json.dumps(sorted(set(values)), ensure_ascii=False)


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
    def __init__(self, rel: str, tree: ast.Module) -> None:
        self.rel = rel
        self.sites: list[Site] = []
        self.names: list[str] = []
        self.target: str | None = None
        self.scopes: list[_ScopeInfo] = [_scope_info(tree.body)]
        self.re_modules: set[str] = set()
        self.re_functions: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "re":
                        self.re_modules.add(alias.asname or "re")
            elif isinstance(node, ast.ImportFrom) and node.module == "re":
                for alias in node.names:
                    if alias.name in RE_FUNCTIONS:
                        self.re_functions[alias.asname or alias.name] = alias.name

    # -- scope bookkeeping ---------------------------------------------------------
    def _add(self, node: ast.AST, fingerprint: str) -> None:
        scope = ".".join([*self.names, *([self.target] if self.target else [])]) or "<module>"
        self.sites.append(Site(self.rel, fingerprint, getattr(node, "lineno", 0), scope))

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.names.append(node.name)
        self.scopes.append(_scope_info(node.body, node.args))
        saved, self.target = self.target, None
        self.generic_visit(node)
        self.target = saved
        self.scopes.pop()
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

    # -- (a) regex, (c) prefix tests and (d) string-method calls --------------------
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


def scanned_files() -> list[Path]:
    return sorted(SCAN_DIRECTORY.rglob("*.py")) + [path for path in EXTRA_FILES]


def collect_sites(files: Iterable[Path] | None = None) -> list[Site]:
    sites: list[Site] = []
    for path in files if files is not None else scanned_files():
        rel = path.relative_to(ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        collector = _Collector(rel, tree)
        collector.visit(tree)
        sites.extend(collector.sites)
    return sites


def load_ledger() -> list[dict[str, str]]:
    data = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    entries = data["entries"]
    seen: set[tuple[str, str]] = set()
    problems = []
    for entry in entries:
        key = (entry["file"], entry["fingerprint"])
        if key in seen:
            problems.append(f"duplicate entry {key}")
        seen.add(key)
        if entry.get("kind") not in KINDS:
            problems.append(f"kind must be allowed or pending: {key}")
        if not entry.get("inventory_id"):
            problems.append(f"inventory_id missing: {key}")
        if not (entry.get("reason") or "").strip():
            problems.append(f"reason missing: {key}")
    assert not problems, "malformed ledger:\n" + "\n".join(problems)
    return entries


def _grouped(sites: Iterable[Site]) -> dict[tuple[str, str], list[Site]]:
    grouped: dict[tuple[str, str], list[Site]] = defaultdict(list)
    for site in sites:
        grouped[(site.file, site.fingerprint)].append(site)
    return grouped


def _describe(key: tuple[str, str], sites: list[Site]) -> str:
    lines = ",".join(str(s.line) for s in sorted(sites, key=lambda s: s.line))
    scopes = ", ".join(sorted({s.scope for s in sites}))
    fingerprint = key[1] if len(key[1]) <= 240 else key[1][:240] + "..."
    return f"  {key[0]}:{lines} [{scopes}] {fingerprint}"


def test_should_list_every_text_rule_site_in_the_ledger_when_src_is_scanned():
    files = scanned_files()
    assert len(files) > 100, f"scan found only {len(files)} files under {SCAN_DIRECTORY}"
    assert all(path.is_file() for path in EXTRA_FILES), EXTRA_FILES
    known = {(entry["file"], entry["fingerprint"]) for entry in load_ledger()}
    unlisted = {
        key: sites for key, sites in _grouped(collect_sites(files)).items() if key not in known
    }
    assert not unlisted, (
        f"{len(unlisted)} text-rule site(s) are not in {LEDGER_PATH.relative_to(ROOT)}.\n"
        "A regex, word list or literal test that reads natural language to decide meaning is "
        "forbidden (AGENTS.md § PROMPTS AND TEXT RULES): put the decision in an extraction "
        "schema field with a source span instead. If the site only parses a machine format, "
        "add an `allowed` entry with a one-line reason.\n"
        + "\n".join(_describe(key, sites) for key, sites in sorted(unlisted.items()))
    )


def test_should_find_every_pending_rule_in_the_code_when_it_is_still_listed():
    present = set(_grouped(collect_sites()))
    gone = [
        entry
        for entry in load_ledger()
        if entry["kind"] == "pending" and (entry["file"], entry["fingerprint"]) not in present
    ]
    assert not gone, (
        f"{len(gone)} pending rule site(s) were removed; delete them from "
        f"{LEDGER_PATH.relative_to(ROOT)}:\n"
        + "\n".join(f"  {e['inventory_id']} {e['file']} {e['fingerprint'][:240]}" for e in gone)
    )


def test_should_not_allow_any_site_when_it_lives_in_a_rule_module():
    allowed_in_rule_modules = [
        entry
        for entry in load_ledger()
        if entry["kind"] == "allowed" and entry["file"] in RULE_MODULES
    ]
    assert not allowed_in_rule_modules, (
        "these modules exist only to hold a text rule; their sites are pending removal, "
        "not allowed:\n"
        + "\n".join(
            f"  {e['inventory_id']} {e['file']} {e['fingerprint'][:240]}"
            for e in allowed_in_rule_modules
        )
    )
