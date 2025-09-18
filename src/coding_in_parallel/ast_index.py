"""AST-based indexing utilities for localisation."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Mapping

from . import types


@dataclass
class AstIndex:
    """In-memory representation of symbols and call-sites."""

    root: Path
    _symbols: Mapping[str, List[types.AstSpan]]
    _calls: Mapping[str, List[types.AstSpan]]
    _file_cache: Mapping[str, List[str]]

    def lookup_symbol(self, symbol: str) -> List[types.AstSpan]:
        return list(self._symbols.get(symbol, []))

    def lookup_calls(self, name: str) -> List[types.AstSpan]:
        return list(self._calls.get(name, []))

    def slice(self, file: str, start_line: int, end_line: int, padding: int = 0) -> str:
        lines = self._file_cache[file]
        start = max(start_line - 1 - padding, 0)
        end = min(end_line + padding, len(lines))
        return "".join(lines[start:end])


class _CallVisitor(ast.NodeVisitor):
    def __init__(self, file: str, calls: Dict[str, List[types.AstSpan]]):
        self.file = file
        self.calls = calls

    def visit_Call(self, node: ast.Call) -> None:  # pragma: no cover - simple delegation
        name = self._call_name(node.func)
        if name:
            span = types.AstSpan(
                file=self.file,
                start_line=node.lineno,
                end_line=getattr(node, "end_lineno", node.lineno),
                node_type="Call",
                symbol=name,
            )
            self.calls.setdefault(name, []).append(span)
        self.generic_visit(node)

    @staticmethod
    def _call_name(expr: ast.AST) -> str | None:
        if isinstance(expr, ast.Name):
            return expr.id
        if isinstance(expr, ast.Attribute):
            return expr.attr
        return None


def _walk_python_files(repo_path: Path) -> Iterable[Path]:
    for path in repo_path.rglob("*.py"):
        if path.is_file():
            yield path


def build_index(repo_path: Path | str) -> AstIndex:
    """Build an :class:`AstIndex` for the given repository."""

    root = Path(repo_path)
    symbol_map: Dict[str, List[types.AstSpan]] = {}
    call_map: Dict[str, List[types.AstSpan]] = {}
    file_cache: Dict[str, List[str]] = {}

    for file_path in _walk_python_files(root):
        rel = file_path.relative_to(root).as_posix()
        text = file_path.read_text()
        file_cache[rel] = text.splitlines(keepends=True)
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                span = types.AstSpan(
                    file=rel,
                    start_line=node.lineno,
                    end_line=getattr(node, "end_lineno", node.lineno),
                    node_type="FunctionDef",
                    symbol=node.name,
                )
                symbol_map.setdefault(node.name, []).append(span)
            elif isinstance(node, ast.ClassDef):
                span = types.AstSpan(
                    file=rel,
                    start_line=node.lineno,
                    end_line=getattr(node, "end_lineno", node.lineno),
                    node_type="ClassDef",
                    symbol=node.name,
                )
                symbol_map.setdefault(node.name, []).append(span)

        visitor = _CallVisitor(rel, call_map)
        visitor.visit(tree)

    return AstIndex(root=root, _symbols=symbol_map, _calls=call_map, _file_cache=file_cache)


