"""AST-based indexing utilities for localisation."""

from __future__ import annotations

import ast
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Set, Tuple

from . import types


@dataclass(frozen=True)
class SymbolInfo:
    """Extended symbol information with qualname."""

    span: types.AstSpan
    qualname: str  # e.g., "pkg.module.ClassName.method"
    kind: str  # "function", "method", "class", "module"
    parent_qualname: Optional[str] = None  # qualname of containing class/function


@dataclass(frozen=True)
class CallEdge:
    """A call edge from caller to callee."""

    caller_qualname: str
    callee_name: str  # short name (may not be fully qualified)
    caller_span: types.AstSpan
    call_span: types.AstSpan


@dataclass
class AstIndex:
    """In-memory representation of symbols and call-sites with qualnames."""

    root: Path
    _symbols: Mapping[str, List[types.AstSpan]]
    _calls: Mapping[str, List[types.AstSpan]]
    _file_cache: Mapping[str, List[str]]

    # Enhanced data structures
    _symbol_info: Mapping[str, List[SymbolInfo]] = field(default_factory=dict)
    _qualname_to_span: Mapping[str, types.AstSpan] = field(default_factory=dict)
    _call_edges: List[CallEdge] = field(default_factory=list)
    _callers: Mapping[str, List[str]] = field(default_factory=dict)  # callee -> [caller qualnames]
    _callees: Mapping[str, List[str]] = field(default_factory=dict)  # caller -> [callee names]

    def lookup_symbol(self, symbol: str) -> List[types.AstSpan]:
        return list(self._symbols.get(symbol, []))

    def lookup_calls(self, name: str) -> List[types.AstSpan]:
        return list(self._calls.get(name, []))

    def lookup_by_qualname(self, qualname: str) -> Optional[types.AstSpan]:
        """Look up a symbol by its fully qualified name."""
        return self._qualname_to_span.get(qualname)

    def lookup_symbol_info(self, symbol: str) -> List[SymbolInfo]:
        """Look up extended symbol info including qualname."""
        return list(self._symbol_info.get(symbol, []))

    def get_callers(self, symbol: str) -> List[str]:
        """Get qualnames of functions/methods that call this symbol.

        This is the reverse edge lookup - given a callee name,
        find all callers.
        """
        # Accept either a short name or a qualname; normalize to short name.
        short_name = symbol.split(".")[-1] if "." in symbol else symbol
        return list(self._callers.get(short_name, []))

    def get_callees(self, caller_qualname: str) -> List[str]:
        """Get names of functions called by this caller."""
        return list(self._callees.get(caller_qualname, []))

    def slice(self, file: str, start_line: int, end_line: int, padding: int = 0) -> str:
        lines = self._file_cache.get(file, [])
        if not lines:
            return ""
        start = max(start_line - 1 - padding, 0)
        end = min(end_line + padding, len(lines))
        return "".join(lines[start:end])

    def slice_numbered(
        self,
        file: str,
        start_line: int,
        end_line: int,
        padding: int = 0,
    ) -> str:
        """Return a slice with line numbers for prompts."""
        lines = self._file_cache.get(file, [])
        if not lines:
            return ""
        start = max(start_line - 1 - padding, 0)
        end = min(end_line + padding, len(lines))
        numbered = []
        for i, line in enumerate(lines[start:end], start=start + 1):
            numbered.append(f"{i:4d}: {line.rstrip()}")
        return "\n".join(numbered)

    # Public helpers for localization
    def iter_symbol_spans(self) -> Iterable[types.AstSpan]:
        """Yield all symbol spans indexed in the repository."""
        for spans in self._symbols.values():
            for span in spans:
                yield span

    def iter_symbol_info(self) -> Iterable[SymbolInfo]:
        """Yield all symbol info objects."""
        for infos in self._symbol_info.values():
            for info in infos:
                yield info

    def spans_in_file(self, file: str) -> List[types.AstSpan]:
        """Return all symbol spans that belong to a given relative file path."""
        return [s for s in self.iter_symbol_spans() if s.file == file]

    def find_spans_covering(self, file: str, line: int) -> List[types.AstSpan]:
        """Find symbol spans in `file` that enclose `line` (1-based)."""
        return [
            s
            for s in self.spans_in_file(file)
            if s.start_line <= line <= s.end_line
        ]

    def find_symbol_info_covering(self, file: str, line: int) -> List[SymbolInfo]:
        """Find SymbolInfo objects that enclose a line."""
        return [
            info
            for info in self.iter_symbol_info()
            if info.span.file == file and info.span.start_line <= line <= info.span.end_line
        ]

    def build_call_subgraph(
        self,
        seed_symbols: List[str],
        *,
        max_hops: int = 2,
        max_nodes: int = 50,
        direction: str = "both",  # "callers", "callees", or "both"
    ) -> Tuple[Set[str], List[Tuple[str, str, str]]]:
        """Build a bounded subgraph around seed symbols.

        Args:
            seed_symbols: Starting symbol names or qualnames
            max_hops: Maximum BFS hops from seeds
            max_nodes: Maximum nodes in the subgraph
            direction: "callers" (upstream), "callees" (downstream), or "both"

        Returns:
            Tuple of (node qualnames, edges as (src, dst, kind))
        """
        nodes: Set[str] = set()
        edges: List[Tuple[str, str, str]] = []

        # Queue: (symbol, current_hop)
        queue: deque[Tuple[str, int]] = deque()

        # Seed with initial symbols
        for sym in seed_symbols:
            # Try as qualname first, then as short name
            if sym in self._qualname_to_span:
                queue.append((sym, 0))
                nodes.add(sym)
            else:
                # Find all qualnames for this short name
                for info in self.lookup_symbol_info(sym):
                    queue.append((info.qualname, 0))
                    nodes.add(info.qualname)

        visited: Set[str] = set(nodes)

        while queue and len(nodes) < max_nodes:
            current, hop = queue.popleft()

            if hop >= max_hops:
                continue

            # Expand callers (reverse edges)
            if direction in ("callers", "both"):
                # Get short name from qualname
                short_name = current.split(".")[-1] if "." in current else current
                for caller in self.get_callers(short_name):
                    edges.append((caller, current, "calls"))
                    if caller not in visited:
                        visited.add(caller)
                        nodes.add(caller)
                        if len(nodes) < max_nodes:
                            queue.append((caller, hop + 1))

            # Expand callees (forward edges)
            if direction in ("callees", "both"):
                for callee in self.get_callees(current):
                    # Find qualnames for this callee
                    for info in self.lookup_symbol_info(callee):
                        edges.append((current, info.qualname, "calls"))
                        if info.qualname not in visited:
                            visited.add(info.qualname)
                            nodes.add(info.qualname)
                            if len(nodes) < max_nodes:
                                queue.append((info.qualname, hop + 1))

        return nodes, edges


class _SymbolVisitor(ast.NodeVisitor):
    """Visitor that tracks scope for qualified names."""

    def __init__(
        self,
        file: str,
        module_qualname: str,
        symbols: Dict[str, List[types.AstSpan]],
        symbol_info: Dict[str, List[SymbolInfo]],
        qualname_map: Dict[str, types.AstSpan],
    ):
        self.file = file
        self.module_qualname = module_qualname
        self.symbols = symbols
        self.symbol_info = symbol_info
        self.qualname_map = qualname_map
        self.scope_stack: List[str] = []  # Stack of class/function names
        self.scope_kinds: List[str] = []  # Parallel stack of scope kinds

    def _current_qualname(self, name: str) -> str:
        """Build qualname from current scope."""
        parts = [self.module_qualname] + self.scope_stack + [name]
        return ".".join(parts)

    def _parent_qualname(self) -> Optional[str]:
        """Get qualname of parent scope."""
        if not self.scope_stack:
            return self.module_qualname
        parts = [self.module_qualname] + self.scope_stack
        return ".".join(parts)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        qualname = self._current_qualname(node.name)
        span = types.AstSpan(
            file=self.file,
            start_line=node.lineno,
            end_line=getattr(node, "end_lineno", node.lineno),
            node_type="ClassDef",
            symbol=node.name,
        )
        self.symbols.setdefault(node.name, []).append(span)
        info = SymbolInfo(
            span=span,
            qualname=qualname,
            kind="class",
            parent_qualname=self._parent_qualname(),
        )
        self.symbol_info.setdefault(node.name, []).append(info)
        self.qualname_map[qualname] = span

        # Visit children with this class in scope
        self.scope_stack.append(node.name)
        self.scope_kinds.append("class")
        self.generic_visit(node)
        self.scope_stack.pop()
        self.scope_kinds.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        qualname = self._current_qualname(node.name)
        span = types.AstSpan(
            file=self.file,
            start_line=node.lineno,
            end_line=getattr(node, "end_lineno", node.lineno),
            node_type="FunctionDef",
            symbol=node.name,
        )
        self.symbols.setdefault(node.name, []).append(span)

        # Determine if this is a method (directly inside a class)
        kind = "method" if (self.scope_kinds and self.scope_kinds[-1] == "class") else "function"

        info = SymbolInfo(
            span=span,
            qualname=qualname,
            kind=kind,
            parent_qualname=self._parent_qualname(),
        )
        self.symbol_info.setdefault(node.name, []).append(info)
        self.qualname_map[qualname] = span

        # Visit children with this function in scope
        self.scope_stack.append(node.name)
        self.scope_kinds.append("function")
        self.generic_visit(node)
        self.scope_stack.pop()
        self.scope_kinds.pop()


class _CallEdgeVisitor(ast.NodeVisitor):
    """Visitor that extracts call edges with caller context."""

    def __init__(
        self,
        file: str,
        module_qualname: str,
        calls: Dict[str, List[types.AstSpan]],
        call_edges: List[CallEdge],
        callers: Dict[str, List[str]],
        callees: Dict[str, List[str]],
        qualname_map: Dict[str, types.AstSpan],
    ):
        self.file = file
        self.module_qualname = module_qualname
        self.calls = calls
        self.call_edges = call_edges
        self.callers = callers
        self.callees = callees
        self.qualname_map = qualname_map
        self.scope_stack: List[str] = []

    def _current_qualname(self) -> str:
        """Get qualname of current scope (caller context)."""
        parts = [self.module_qualname] + self.scope_stack
        return ".".join(parts)

    def _current_span(self) -> Optional[types.AstSpan]:
        """Get span of current scope."""
        return self.qualname_map.get(self._current_qualname())

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.scope_stack.append(node.name)
        self.generic_visit(node)
        self.scope_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.scope_stack.append(node.name)
        self.generic_visit(node)
        self.scope_stack.pop()

    def visit_Call(self, node: ast.Call) -> None:
        name = self._call_name(node.func)
        if name:
            call_span = types.AstSpan(
                file=self.file,
                start_line=node.lineno,
                end_line=getattr(node, "end_lineno", node.lineno),
                node_type="Call",
                symbol=name,
            )
            self.calls.setdefault(name, []).append(call_span)

            # Record call edge
            caller_qualname = self._current_qualname()
            caller_span = self._current_span()

            if caller_span:
                edge = CallEdge(
                    caller_qualname=caller_qualname,
                    callee_name=name,
                    caller_span=caller_span,
                    call_span=call_span,
                )
                self.call_edges.append(edge)

                # Update caller/callee maps
                self.callers.setdefault(name, []).append(caller_qualname)
                self.callees.setdefault(caller_qualname, []).append(name)

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
        if path.is_file() and "__pycache__" not in path.parts:
            yield path


def _file_to_module_qualname(rel_path: str) -> str:
    """Convert a relative file path to a module qualname.

    Examples:
        "pkg/module.py" -> "pkg.module"
        "pkg/__init__.py" -> "pkg"
        "script.py" -> "script"
    """
    # Remove .py extension
    if rel_path.endswith(".py"):
        rel_path = rel_path[:-3]

    # Convert path separators to dots
    parts = rel_path.replace("/", ".").replace("\\", ".").split(".")

    # Handle __init__
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]

    return ".".join(parts) if parts else "unnamed"


def build_index(repo_path: Path | str) -> AstIndex:
    """Build an :class:`AstIndex` for the given repository.

    This enhanced version includes:
    - Qualified names (module.Class.method)
    - Reverse edges (callers lookup)
    - Call edge tracking
    """

    root = Path(repo_path)
    symbol_map: Dict[str, List[types.AstSpan]] = {}
    symbol_info: Dict[str, List[SymbolInfo]] = {}
    qualname_map: Dict[str, types.AstSpan] = {}
    call_map: Dict[str, List[types.AstSpan]] = {}
    call_edges: List[CallEdge] = []
    callers: Dict[str, List[str]] = {}
    callees: Dict[str, List[str]] = {}
    file_cache: Dict[str, List[str]] = {}

    for file_path in _walk_python_files(root):
        rel = file_path.relative_to(root).as_posix()
        try:
            text = file_path.read_text()
        except (OSError, UnicodeDecodeError):
            continue

        file_cache[rel] = text.splitlines(keepends=True)

        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue

        module_qualname = _file_to_module_qualname(rel)

        # Record module span for module-scope call edges
        if rel in file_cache:
            module_span = types.AstSpan(
                file=rel,
                start_line=1,
                end_line=max(1, len(file_cache[rel])),
                node_type="Module",
                symbol=module_qualname,
            )
            qualname_map[module_qualname] = module_span

        # First pass: collect symbols with qualnames
        symbol_visitor = _SymbolVisitor(
            rel, module_qualname, symbol_map, symbol_info, qualname_map
        )
        symbol_visitor.visit(tree)

        # Second pass: collect call edges
        call_visitor = _CallEdgeVisitor(
            rel, module_qualname, call_map, call_edges, callers, callees, qualname_map
        )
        call_visitor.visit(tree)

    return AstIndex(
        root=root,
        _symbols=symbol_map,
        _calls=call_map,
        _file_cache=file_cache,
        _symbol_info=symbol_info,
        _qualname_to_span=qualname_map,
        _call_edges=call_edges,
        _callers=callers,
        _callees=callees,
    )
