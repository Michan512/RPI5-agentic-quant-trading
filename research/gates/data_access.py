"""
Gate 1 check: a strategy may see prices ONLY through the PriceView it is given.

Why: the look-ahead test scrambles future prices in the panel it hands the
strategy. A strategy holding its own copy of the data (read from files, kept in a
global or a class attribute, or reached through PriceView's private fields) is
invisible to that test. A planted strategy doing this passed 10 of 11 gate checks
(research/MISTAKES.md #13). Owner chose this static check on 2026-11-26.

Limits: a static scan catches the plain ways to do it; a determined author can hide
it. Stage B's sandbox (no data files visible to agent code) is the stronger fix.

Scans the strategy's module plus every module it imports from research.strategies
(e.g. a combo's parts). `shared.*` is fixed, trusted code and is not scanned.
"""

from __future__ import annotations

import ast
import importlib
import inspect
from types import ModuleType

import numpy as np
import pandas as pd

from shared.strategy import Strategy

# Modules that give a way to files, the network, other processes or the raw data.
BANNED_MODULES = (
    "os", "sys", "io", "pathlib", "shutil", "glob", "tempfile", "pickle", "shelve", "marshal",
    "sqlite3", "subprocess", "socket", "http", "urllib", "requests", "importlib", "builtins",
    "ctypes", "inspect", "gc", "yfinance", "joblib",
    "research.data", "research.engine", "research.gates", "research.trials", "live",
)
BANNED_CALLS = {"open", "eval", "exec", "compile", "__import__", "getattr", "setattr",
                "delattr", "globals", "locals", "vars"}
SCANNED_PREFIXES = ("research.strategies",)
_DATA_TYPES = (pd.DataFrame, pd.Series, np.ndarray)


def _banned(mod: str) -> bool:
    return any(mod == b or mod.startswith(b + ".") for b in BANNED_MODULES)


def _scan_source(tree: ast.AST, where: str) -> tuple[list[str], set[str]]:
    problems, imported = [], set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                imported.add(a.name)
                if _banned(a.name):
                    problems.append(f"{where}:{node.lineno}: imports {a.name}")
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
            if _banned(node.module):
                problems.append(f"{where}:{node.lineno}: imports from {node.module}")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in BANNED_CALLS:
            problems.append(f"{where}:{node.lineno}: calls {node.func.id}()")
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("read_") or node.attr in {"to_pickle", "from_pickle"}:
                problems.append(f"{where}:{node.lineno}: uses .{node.attr} (reads data from outside)")
            elif (node.attr.startswith("_") and not node.attr.startswith("__")
                  and not (isinstance(node.value, ast.Name) and node.value.id in {"self", "cls"})):
                problems.append(f"{where}:{node.lineno}: reaches into private field .{node.attr}")
    return problems, imported


def _modules_to_scan(start: ModuleType) -> list[ModuleType]:
    seen, todo, out = set(), [start], []
    while todo:
        m = todo.pop()
        if m.__name__ in seen:
            continue
        seen.add(m.__name__)
        out.append(m)
        _, imported = _scan_source(ast.parse(inspect.getsource(m)), m.__name__)
        for name in imported:
            if name.startswith(SCANNED_PREFIXES) and name not in seen:
                try:
                    todo.append(importlib.import_module(name))
                except ImportError:
                    pass
    return out


def data_access_violations(strategy_cls) -> list[str]:
    """Empty list = the strategy only sees prices through its PriceView."""
    problems = []
    for m in _modules_to_scan(inspect.getmodule(strategy_cls)):
        p, _ = _scan_source(ast.parse(inspect.getsource(m)), m.__name__)
        problems += p
        for k, v in vars(m).items():                       # data stashed in a module global
            if isinstance(v, _DATA_TYPES):
                problems.append(f"{m.__name__}: module global {k} holds {type(v).__name__}")
    for klass in strategy_cls.__mro__:                      # data stashed on the class
        if klass in (Strategy, object):
            continue
        for k, v in vars(klass).items():
            if isinstance(v, _DATA_TYPES):
                problems.append(f"{klass.__name__}.{k} holds {type(v).__name__}")
    for k, v in vars(strategy_cls()).items():               # ... or on a fresh instance
        if isinstance(v, _DATA_TYPES):
            problems.append(f"new {strategy_cls.__name__}().{k} holds {type(v).__name__}")
    return problems
