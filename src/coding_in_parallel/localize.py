"""Localization: discover suspects from failing tests.

This module implements the localization spec from docs/localize_spec.md.
It produces resolvable suspects, bounded subgraphs, slices, and a ledger seed.
"""

from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path
from typing import Iterable, List, Optional

from . import ast_index, trace_parser, token_search, types, types_localize as loc_types

_BLOCK_NODES = (
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
    ast.If,
    ast.For,
    ast.While,
    ast.Try,
    ast.With,
    ast.Match,
)


def extract_hammocks_stage_a(repo_root: Path) -> dict[str, list[loc_types.HammockBlock]]:
    """Extract Stage‑A hammock blocks using AST node spans.

    Stage‑A hammocks are approximate edit regions derived from AST block nodes
    (functions, classes, control‑flow blocks). This provides pragmatic edit
    windows before CFG‑based SESE detection.
    """
    hammocks: dict[str, list[loc_types.HammockBlock]] = {}
    for path in repo_root.rglob("*.py"):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        rel = path.relative_to(repo_root).as_posix()
        try:
            text = path.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        blocks: list[loc_types.HammockBlock] = []
        for node in ast.walk(tree):
            if not isinstance(node, _BLOCK_NODES):
                continue
            start = getattr(node, "lineno", None)
            end = getattr(node, "end_lineno", None)
            if not start:
                continue
            end = end or start
            blocks.append(
                loc_types.HammockBlock(
                    file=rel,
                    start_line=int(start),
                    end_line=int(end),
                    kind="approx",
                    entry_id=None,
                    exit_id=None,
                )
            )
        if blocks:
            hammocks[rel] = blocks
    return hammocks


def _pick_symbol_info(
    infos: Iterable[ast_index.SymbolInfo],
    *,
    prefer_symbol: str | None = None,
) -> Optional[ast_index.SymbolInfo]:
    """Pick a symbol info candidate, preferring the matching symbol name."""
    infos_list = list(infos)
    if not infos_list:
        return None
    if prefer_symbol:
        for info in infos_list:
            if info.span.symbol == prefer_symbol or info.qualname.endswith(f".{prefer_symbol}"):
                return info
    # Fall back to the smallest span (most specific scope)
    return min(infos_list, key=lambda i: (i.span.end_line - i.span.start_line, i.span.start_line))


def _merge_evidence(
    evidence: loc_types.SuspectEvidence,
    *,
    item: loc_types.EvidenceItem,
    stack_hit: Optional[dict] = None,
    token_hit: Optional[dict] = None,
    heuristic: Optional[str] = None,
) -> loc_types.SuspectEvidence:
    """Return a new SuspectEvidence with a new item merged in."""
    items = list(evidence.items) + [item]
    stack_hits = list(evidence.stack_hits)
    token_hits = list(evidence.token_hits)
    heuristics = list(evidence.heuristics)
    if stack_hit:
        stack_hits.append(stack_hit)
    if token_hit:
        token_hits.append(token_hit)
    if heuristic:
        heuristics.append(heuristic)
    return loc_types.SuspectEvidence(
        items=items,
        stack_hits=stack_hits,
        token_hits=token_hits,
        callgraph_hops_from_stack=evidence.callgraph_hops_from_stack,
        heuristics=heuristics,
        sbfl=dict(evidence.sbfl),
    )


def localize(
    repo_path: str,
    failing_tests: List[str],
    test_output: str,
    *,
    max_suspects: int = 12,
    max_hops: int = 2,
    slice_padding: int = 10,
) -> loc_types.LocalizationResult:
    """Run the full localization pipeline.

    Args:
        repo_path: Path to the repository root
        failing_tests: List of failing test node IDs
        test_output: Raw pytest output (stdout + stderr)
        max_suspects: Maximum number of suspects to return
        max_hops: Maximum callgraph hops from stack-seeded symbols
        slice_padding: Lines of context around spans for slices

    Returns:
        LocalizationResult with suspects, subgraph, slices, and ledger seed
    """
    root = Path(repo_path)

    # Step 1: Parse stack traces to get (file, line) frames
    trace_result = trace_parser.parse_pytest_output(test_output, repo_root=root)

    # Step 2: Extract assertion strings for token matching
    assertion_strings = trace_parser.extract_assertion_strings(test_output)

    # Step 3: Build AST index
    index = ast_index.build_index(root)

    # Stage‑A hammocks (AST blocks)
    hammocks = extract_hammocks_stage_a(root)

    # Step 4: Seed suspects from stack frames
    suspect_by_id: dict[str, loc_types.Suspect] = {}

    for frame in trace_result.frames:
        # Skip non-project files (site-packages, stdlib, etc.)
        if "site-packages" in frame.file or frame.file.startswith("/"):
            # Try to make it relative
            try:
                rel_path = Path(frame.file).relative_to(root).as_posix()
            except ValueError:
                continue
        else:
            rel_path = frame.file

        # Find enclosing symbol
        spans = index.find_spans_covering(rel_path, frame.line)
        if not spans:
            continue

        for span in spans:
            suspect_id = f"sus-{rel_path}:{span.start_line}-{span.end_line}"
            if suspect_id in suspect_by_id:
                # Merge evidence into existing suspect
                existing = suspect_by_id[suspect_id]
                merged = _merge_evidence(
                    existing.evidence,
                    item=loc_types.EvidenceItem(
                        kind="stack_hit",
                        source=f"traceback:{frame.file}:{frame.line}",
                        reason=frame.reason or f"Appears in stack trace at line {frame.line}",
                        weight=1.0,
                        data={"frame_line": frame.line, "frame_function": frame.function},
                    ),
                    stack_hit={"file": frame.file, "line": frame.line, "function": frame.function},
                )
                suspect_by_id[suspect_id] = replace(
                    existing,
                    evidence=merged,
                    score=min(1.0, (existing.score or 0.0) + 1.0),
                )
                continue

            # Determine kind + qualname from symbol info
            symbol_info = _pick_symbol_info(
                index.find_symbol_info_covering(rel_path, frame.line),
                prefer_symbol=span.symbol,
            )
            kind: loc_types.Suspect.__dataclass_fields__["kind"].type = (
                symbol_info.kind if symbol_info else ("class" if span.node_type == "ClassDef" else "function")
            )
            qualname = symbol_info.qualname if symbol_info else (
                f"{rel_path.replace('/', '.').replace('.py', '')}.{span.symbol}"
                if span.symbol else None
            )

            # Build evidence
            evidence = loc_types.SuspectEvidence(
                items=[
                    loc_types.EvidenceItem(
                        kind="stack_hit",
                        source=f"traceback:{frame.file}:{frame.line}",
                        reason=frame.reason or f"Appears in stack trace at line {frame.line}",
                        weight=1.0,
                        data={"frame_line": frame.line, "frame_function": frame.function},
                    )
                ],
                stack_hits=[{"file": frame.file, "line": frame.line, "function": frame.function}],
            )

            suspect = loc_types.Suspect(
                id=suspect_id,
                file=rel_path,
                span=span,
                kind=kind,
                qualname=qualname,
                symbol=span.symbol,
                reason=frame.reason or f"Function appears in stack trace at line {frame.line}",
                anchors={"def_line": span.start_line},
                evidence=evidence,
                score=1.0,  # Stack hits get high base score
            )
            suspect_by_id[suspect_id] = suspect

    # Step 5: Token matching
    if assertion_strings:
        token_result = token_search.search_directory(root, assertion_strings)

        for hit in token_result.hits:
            # Skip test files for suspects (but could be useful as evidence)
            if "test_" in hit.file or "/tests/" in hit.file:
                continue

            spans = index.find_spans_covering(hit.file, hit.line)
            for span in spans:
                suspect_id = f"sus-{hit.file}:{span.start_line}-{span.end_line}"
                if suspect_id in suspect_by_id:
                    existing = suspect_by_id[suspect_id]
                    merged = _merge_evidence(
                        existing.evidence,
                        item=loc_types.EvidenceItem(
                            kind="token_hit",
                            source=f"grep:{hit.query}",
                            reason=hit.reason,
                            weight=0.7,
                            data={"query": hit.query, "matched_text": hit.matched_text},
                        ),
                        token_hit={"file": hit.file, "line": hit.line, "query": hit.query},
                    )
                    suspect_by_id[suspect_id] = replace(
                        existing,
                        evidence=merged,
                        score=min(1.0, (existing.score or 0.0) + 0.7),
                    )
                    continue

                symbol_info = _pick_symbol_info(
                    index.find_symbol_info_covering(hit.file, hit.line),
                    prefer_symbol=span.symbol,
                )
                kind = symbol_info.kind if symbol_info else ("class" if span.node_type == "ClassDef" else "function")
                qualname = symbol_info.qualname if symbol_info else (
                    f"{hit.file.replace('/', '.').replace('.py', '')}.{span.symbol}"
                    if span.symbol else None
                )

                evidence = loc_types.SuspectEvidence(
                    items=[
                        loc_types.EvidenceItem(
                            kind="token_hit",
                            source=f"grep:{hit.query}",
                            reason=hit.reason,
                            weight=0.7,
                            data={"query": hit.query, "matched_text": hit.matched_text},
                        )
                    ],
                    token_hits=[{"file": hit.file, "line": hit.line, "query": hit.query}],
                )

                suspect = loc_types.Suspect(
                    id=suspect_id,
                    file=hit.file,
                    span=span,
                    kind=kind,
                    qualname=qualname,
                    symbol=span.symbol,
                    reason=hit.reason,
                    anchors={"def_line": span.start_line},
                    evidence=evidence,
                    score=0.7,  # Token hits get medium score
                )
                suspect_by_id[suspect_id] = suspect

    # Step 6: Test-to-module heuristic
    for test_nodeid in failing_tests:
        module_name = _test_to_module_name(test_nodeid)
        if module_name:
            for span in index.lookup_symbol(module_name) or []:
                suspect_id = f"sus-{span.file}:{span.start_line}-{span.end_line}"
                if suspect_id in suspect_by_id:
                    continue

                symbol_info = _pick_symbol_info(
                    index.find_symbol_info_covering(span.file, span.start_line),
                    prefer_symbol=span.symbol,
                )
                kind = symbol_info.kind if symbol_info else ("class" if span.node_type == "ClassDef" else "function")
                qualname = symbol_info.qualname if symbol_info else (
                    f"{span.file.replace('/', '.').replace('.py', '')}.{span.symbol}"
                    if span.symbol else None
                )

                evidence = loc_types.SuspectEvidence(
                    items=[
                        loc_types.EvidenceItem(
                            kind="heuristic",
                            source=f"test_to_module:{test_nodeid}",
                            reason=f"Module '{module_name}' linked from test '{test_nodeid}'",
                            weight=0.5,
                            data={"test_nodeid": test_nodeid, "module_name": module_name},
                        )
                    ],
                    heuristics=[f"test_to_module:{module_name}"],
                )

                suspect = loc_types.Suspect(
                    id=suspect_id,
                    file=span.file,
                    span=span,
                    kind=kind,
                    qualname=qualname,
                    symbol=span.symbol,
                    reason=f"Module '{module_name}' linked from failing test",
                    anchors={"def_line": span.start_line},
                    evidence=evidence,
                    score=0.5,
                )
                suspect_by_id[suspect_id] = suspect

    # Step 7: Sort by score and limit
    # Refresh suspects from dict to reflect merged evidence
    suspects = list(suspect_by_id.values())
    suspects.sort(key=lambda s: s.score, reverse=True)
    suspects = suspects[:max_suspects]

    # Step 8: Build slices for prompts
    slices: dict[str, list[loc_types.Slice]] = {}
    for suspect in suspects:
        file_slices = slices.setdefault(suspect.file, [])
        file_slices.append(
            loc_types.Slice(
                file=suspect.file,
                start_line=max(1, suspect.span.start_line - slice_padding),
                end_line=suspect.span.end_line + slice_padding,
                kind="span",
            )
        )

    # Step 9: Build subgraph (callgraph edges + suspect nodes)
    seed_symbols = [s.qualname or s.symbol or "" for s in suspects if (s.qualname or s.symbol)]
    for test_nodeid in failing_tests:
        name = _test_to_module_name(test_nodeid)
        if name:
            seed_symbols.append(name)
    # Deduplicate while preserving order
    seen = set()
    seed_symbols = [s for s in seed_symbols if not (s in seen or seen.add(s))]
    nodes, edges = index.build_call_subgraph(seed_symbols, max_hops=max_hops)
    node_dicts = []
    for node in nodes:
        span = index.lookup_by_qualname(node)
        file = span.file if span else ""
        symbol = span.symbol if span else node.split(".")[-1]
        infos = [i for i in index.lookup_symbol_info(symbol) if not file or i.span.file == file]
        info = _pick_symbol_info(infos)
        node_dicts.append(
            {
                "id": node,
                "qualname": node,
                "file": file,
                "symbol": symbol,
                "kind": info.kind if info else "function",
                "score": next((s.score for s in suspects if s.qualname == node), 0.0),
            }
        )
    subgraph = loc_types.SupportedSubgraph(
        nodes=node_dicts,
        edges=edges,
        hammocks=hammocks,
    )

    # Step 10: Build ledger seed
    allowlists: dict[str, list[tuple[str, int, int]]] = {}
    for s in suspects:
        blocks = [
            b
            for b in hammocks.get(s.file, [])
            if b.start_line <= s.span.start_line and b.end_line >= s.span.end_line
        ]
        if blocks:
            allowlists[s.id] = [(b.file, b.start_line, b.end_line) for b in blocks]
        else:
            allowlists[s.id] = [(s.file, s.span.start_line, s.span.end_line)]

    ledger_seed = loc_types.LedgerSeed(
        suspects=suspects,
        labels={
            s.id: [item.kind for item in s.evidence.items]
            for s in suspects
        },
        frontier=[s.id for s in suspects[max_suspects // 2:]],  # Second half as frontier
        allowlists=allowlists,
        posterior={s.id: s.score for s in suspects},
    )

    return loc_types.LocalizationResult(
        suspects=suspects,
        subgraph=subgraph,
        slices=slices,
        hammocks=hammocks,
        ledger_seed=ledger_seed,
    )


def _test_to_module_name(test_nodeid: str) -> Optional[str]:
    """Extract likely module/function name from test node ID.

    Examples:
        tests/test_foo.py::test_bar -> foo, bar
        tests/test_calculator.py::TestCalc::test_add -> calculator, add
    """
    # Extract test file and function
    parts = test_nodeid.split("::")
    if not parts:
        return None

    # Try to extract from test function name
    if len(parts) >= 2:
        test_name = parts[-1]
        # Remove common prefixes
        for prefix in ("test_", "Test"):
            if test_name.startswith(prefix):
                return test_name[len(prefix):]

    # Try to extract from test file
    test_file = parts[0]
    if "/" in test_file:
        test_file = test_file.split("/")[-1]
    if test_file.startswith("test_") and test_file.endswith(".py"):
        return test_file[5:-3]  # Remove "test_" and ".py"

    return None
