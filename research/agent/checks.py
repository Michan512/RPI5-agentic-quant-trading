"""
Static checks on agent-written strategy code. Runs on the host WITHOUT executing
the code: the source is only parsed. Anything that fails never reaches the sandbox.

An allowlist, not a blocklist: the code may import only pandas, numpy, math,
statistics, typing, dataclasses and the project's strategy interface. On top of that:
no file, network or process access; no reflection (getattr, dunder attributes,
globals); no assigning attributes on anything but `self` (so it can't monkeypatch
pandas or the engine to fake its results); no printing (output is the runner's
channel); no ticker names (rules over the universe only); no work at import time.

Why so strict: promoted code eventually runs on the Pi, in the same process that
holds the broker keys. The sandbox protects the PC; these checks plus the gates
protect the Pi.
"""

from __future__ import annotations

import ast
import hashlib
import re
from dataclasses import dataclass, field

from shared.universe import TRADABLE

ALLOWED_IMPORTS = {"__future__", "math", "statistics", "typing", "dataclasses", "numpy", "pandas",
                   "shared.strategy", "shared.universe", "shared.limits"}
SHARED_SUBMODULES = {"strategy", "universe", "limits"}
BANNED_NAMES = {"open", "eval", "exec", "compile", "__import__", "getattr", "setattr", "delattr",
                "globals", "locals", "vars", "input", "breakpoint", "help", "exit", "quit", "print",
                "memoryview", "type", "__builtins__", "dir"}
BANNED_ATTR_PREFIXES = ("read_", "to_csv", "to_pickle", "to_parquet", "to_excel", "to_json", "to_hdf",
                        "to_sql", "to_feather", "to_clipboard", "to_html", "to_latex", "to_markdown",
                        "to_stata", "to_xml", "to_orc")
BANNED_ATTRS = {"load", "save", "savez", "savetxt", "loadtxt", "fromfile", "tofile", "genfromtxt",
                "memmap", "eval", "query", "system", "popen"}
REBALANCE = {"daily", "weekly", "monthly", "once"}
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,40}$")
MAX_SOURCE_CHARS = 20_000


@dataclass
class CheckResult:
    ok: bool
    problems: list = field(default_factory=list)
    strategy_name: str = ""
    class_name: str = ""
    rebalance: str = ""
    source_sha: str = ""


def source_sha(src: str) -> str:
    return hashlib.sha256(src.encode()).hexdigest()[:12]


def _is_strategy_base(node: ast.expr) -> bool:
    return (isinstance(node, ast.Name) and node.id == "Strategy") or \
           (isinstance(node, ast.Attribute) and node.attr == "Strategy")


def check_source(src: str) -> CheckResult:
    r = CheckResult(ok=False, source_sha=source_sha(src))
    p = r.problems
    if len(src) > MAX_SOURCE_CHARS:
        p.append(f"code is {len(src)} characters; the limit is {MAX_SOURCE_CHARS}")
        return r
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        p.append(f"syntax error: {e}")
        return r

    # Module level: only imports, class/function definitions, simple constants, a docstring.
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.ClassDef, ast.FunctionDef)):
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and _is_literal(node.value):
            continue
        p.append(f"line {node.lineno}: only imports, definitions and constant values are allowed at "
                 f"module level (no code runs at import)")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name not in ALLOWED_IMPORTS:
                    p.append(f"line {node.lineno}: import {a.name} is not allowed "
                             f"(allowed: {', '.join(sorted(ALLOWED_IMPORTS))})")
        elif isinstance(node, ast.ImportFrom):
            if node.module == "shared" and not node.level and {a.name for a in node.names} <= SHARED_SUBMODULES:
                continue
            if node.level or (node.module or "") not in ALLOWED_IMPORTS:
                p.append(f"line {node.lineno}: from {node.module} import ... is not allowed")
        elif isinstance(node, ast.Name) and node.id in BANNED_NAMES:
            p.append(f"line {node.lineno}: {node.id} is not allowed")
        elif isinstance(node, ast.Attribute):
            a = node.attr
            if a.startswith("__") and a != "__init__":
                p.append(f"line {node.lineno}: dunder attribute .{a} is not allowed")
            elif a.startswith("_") and not (isinstance(node.value, ast.Name) and node.value.id == "self"):
                p.append(f"line {node.lineno}: private attribute .{a} is not allowed")
            elif a.startswith(BANNED_ATTR_PREFIXES) or a in BANNED_ATTRS:
                p.append(f"line {node.lineno}: .{a} is not allowed (file, eval or system access)")
        elif isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                for sub in ast.walk(t):
                    if isinstance(sub, ast.Attribute) and not (isinstance(sub.value, ast.Name)
                                                               and sub.value.id == "self"):
                        p.append(f"line {node.lineno}: assigning to .{sub.attr} of something other than "
                                 f"self is not allowed")
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            p.append(f"line {node.lineno}: global/nonlocal is not allowed")
        elif isinstance(node, (ast.AsyncFunctionDef, ast.Await, ast.Yield, ast.YieldFrom, ast.Lambda)) \
                and not isinstance(node, ast.Lambda):
            p.append(f"line {node.lineno}: async code and generators are not allowed")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in TRADABLE:
            p.append(f"line {node.lineno}: ticker name {node.value!r} written in the code; strategies are "
                     f"rules over the universe (use STOCKS, SECTOR_ETFS, etf('role'), etfs(...))")
        elif isinstance(node, ast.Compare) and _names_a_year(node):
            # Found by the drill: a plant that hard-coded the 2008/2020/2022 crash years passed the
            # static checks, the sandbox and the screen. Naming specific years is memorised history.
            p.append(f"line {node.lineno}: compares a date's year with a specific year; rules must be general, "
                     f"not memorised history")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and _DATE_LITERAL.match(node.value):
            p.append(f"line {node.lineno}: date literal {node.value!r}; rules must not name specific dates")

    classes = [n for n in tree.body if isinstance(n, ast.ClassDef) and any(_is_strategy_base(b) for b in n.bases)]
    if len(classes) != 1:
        p.append(f"expected exactly one class that subclasses Strategy, found {len(classes)}")
    else:
        c = classes[0]
        r.class_name = c.name
        attrs = {}
        for stmt in c.body:
            if isinstance(stmt, ast.Assign):
                for t in stmt.targets:
                    if isinstance(t, ast.Name) and isinstance(stmt.value, ast.Constant):
                        attrs[t.id] = stmt.value.value
                    if isinstance(t, ast.Tuple) and isinstance(stmt.value, ast.Tuple):
                        for k, v in zip(t.elts, stmt.value.elts):
                            if isinstance(k, ast.Name) and isinstance(v, ast.Constant):
                                attrs[k.id] = v.value
        r.strategy_name, r.rebalance = str(attrs.get("name", "")), str(attrs.get("rebalance", ""))
        if not NAME_RE.match(r.strategy_name):
            p.append("the class needs name = '<snake_case_name>' (3-41 chars, lowercase letters, digits, _)")
        if r.rebalance not in REBALANCE:
            p.append(f"the class needs rebalance = one of {sorted(REBALANCE)}")
        if not any(isinstance(s, ast.FunctionDef) and s.name == "target_weights" for s in c.body):
            p.append("the class needs a target_weights(self, data) method")
    r.ok = not p
    return r


_DATE_LITERAL = re.compile(r"^(19|20)\d\d-\d\d(-\d\d)?$")


def _names_a_year(node: ast.Compare) -> bool:
    """True for comparisons like d.year == 2008, d.year in (2020, 2022), 2019 < d.year."""
    parts = [node.left, *node.comparators]
    has_year_attr = any(isinstance(n, ast.Attribute) and n.attr in ("year", "isocalendar") for n in parts)
    if not has_year_attr:
        return False
    for n in parts:
        for sub in ast.walk(n):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, int) and 1990 <= sub.value <= 2100:
                return True
    return False


def _is_literal(node) -> bool:
    if node is None:
        return True
    try:
        ast.literal_eval(node)
        return True
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return False


def strip_comments(src: str) -> str:
    """Code with comments and docstrings removed (what gate 2 reviewers see)."""
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)) and node.body and \
                isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant) and \
                isinstance(node.body[0].value.value, str):
            node.body = node.body[1:] or [ast.Pass()]
    return ast.unparse(tree)
