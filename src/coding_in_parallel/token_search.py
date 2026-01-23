"""Token/string matching in source files for localization."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional


@dataclass(frozen=True)
class TokenHit:
    """A match of a search token in a source file."""

    file: str  # repo-relative path
    line: int
    column: int
    matched_text: str
    context_line: str  # the full line containing the match
    query: str  # the original search query
    reason: str  # human-readable reason

    def with_reason(self, reason: str) -> "TokenHit":
        """Return a copy with the reason field set."""
        return TokenHit(
            file=self.file,
            line=self.line,
            column=self.column,
            matched_text=self.matched_text,
            context_line=self.context_line,
            query=self.query,
            reason=reason,
        )


@dataclass(frozen=True)
class TokenSearchResult:
    """Result of searching for tokens across a codebase."""

    hits: List[TokenHit]
    queries: List[str]  # original search queries


def _escape_for_regex(text: str) -> str:
    """Escape special regex characters for literal matching."""
    return re.escape(text)


def _build_pattern(query: str, word_boundary: bool = True) -> re.Pattern[str]:
    """Build a regex pattern from a query string.

    Args:
        query: The search string
        word_boundary: If True, only match at word boundaries
    """
    escaped = _escape_for_regex(query)
    if word_boundary and query.isidentifier():
        # Only add word boundaries for identifier-like queries
        pattern = rf"\b{escaped}\b"
    else:
        pattern = escaped
    return re.compile(pattern, re.IGNORECASE)


def search_file(
    file_path: Path,
    queries: Iterable[str],
    repo_root: Optional[Path] = None,
    max_hits_per_query: int = 20,
) -> List[TokenHit]:
    """Search a single file for token matches.

    Args:
        file_path: Path to the file to search
        queries: Strings to search for
        repo_root: If provided, paths are made relative to this
        max_hits_per_query: Cap hits per query to avoid explosion

    Returns:
        List of TokenHit objects
    """
    try:
        content = file_path.read_text()
    except (OSError, UnicodeDecodeError):
        return []

    lines = content.splitlines()
    rel_path = file_path.as_posix()
    if repo_root:
        try:
            rel_path = file_path.relative_to(repo_root).as_posix()
        except ValueError:
            pass

    hits: List[TokenHit] = []
    query_hit_counts: dict[str, int] = {}

    for query in queries:
        if not query or len(query) < 2:
            continue

        query_hit_counts[query] = 0
        pattern = _build_pattern(query)

        for line_no, line_text in enumerate(lines, start=1):
            if query_hit_counts[query] >= max_hits_per_query:
                break

            for match in pattern.finditer(line_text):
                if query_hit_counts[query] >= max_hits_per_query:
                    break

                hits.append(
                    TokenHit(
                        file=rel_path,
                        line=line_no,
                        column=match.start() + 1,
                        matched_text=match.group(),
                        context_line=line_text.strip(),
                        query=query,
                        reason=f"Token '{query}' found at {rel_path}:{line_no}",
                    )
                )
                query_hit_counts[query] += 1

    return hits


def search_directory(
    directory: Path,
    queries: Iterable[str],
    *,
    extensions: tuple[str, ...] = (".py",),
    exclude_patterns: tuple[str, ...] = ("__pycache__", ".git", "node_modules", ".venv", "venv"),
    max_hits_per_query: int = 50,
    max_files: int = 500,
) -> TokenSearchResult:
    """Search all matching files in a directory for tokens.

    Args:
        directory: Root directory to search
        queries: Strings to search for
        extensions: File extensions to include
        exclude_patterns: Directory names to skip
        max_hits_per_query: Cap total hits per query
        max_files: Cap number of files to search

    Returns:
        TokenSearchResult with all hits
    """
    queries_list = list(queries)
    if not queries_list:
        return TokenSearchResult(hits=[], queries=[])

    all_hits: List[TokenHit] = []
    query_hit_counts: dict[str, int] = {q: 0 for q in queries_list}
    files_searched = 0

    for file_path in directory.rglob("*"):
        if files_searched >= max_files:
            break

        # Skip excluded directories
        if any(ex in file_path.parts for ex in exclude_patterns):
            continue

        # Check extension
        if not file_path.is_file() or file_path.suffix not in extensions:
            continue

        files_searched += 1

        # Filter queries that haven't hit their cap
        active_queries = [q for q in queries_list if query_hit_counts[q] < max_hits_per_query]
        if not active_queries:
            break

        file_hits = search_file(file_path, active_queries, repo_root=directory)

        for hit in file_hits:
            if query_hit_counts[hit.query] < max_hits_per_query:
                all_hits.append(hit)
                query_hit_counts[hit.query] += 1

    return TokenSearchResult(hits=all_hits, queries=queries_list)


def search_for_error_strings(
    directory: Path,
    error_message: Optional[str] = None,
    assertion_strings: Optional[List[str]] = None,
    function_names: Optional[List[str]] = None,
) -> TokenSearchResult:
    """Convenience function to search for error-related tokens.

    Combines error message fragments, assertion strings, and function names
    into a single search.

    Args:
        directory: Root directory to search
        error_message: Error message to extract tokens from
        assertion_strings: Known assertion strings to search
        function_names: Function names mentioned in errors

    Returns:
        TokenSearchResult with all hits
    """
    queries: List[str] = []

    # Extract tokens from error message
    if error_message:
        # Split on common separators and filter
        tokens = re.split(r"[\s,.:;()[\]{}'\"|]+", error_message)
        for token in tokens:
            # Keep identifier-like tokens of reasonable length
            if token.isidentifier() and 3 <= len(token) <= 50:
                if token.lower() not in ("the", "and", "for", "not", "none", "true", "false"):
                    queries.append(token)

    # Add assertion strings (truncate long ones)
    if assertion_strings:
        for s in assertion_strings:
            if len(s) < 100:
                queries.append(s)
            else:
                # Just use first significant word
                words = s.split()
                for w in words:
                    if w.isidentifier() and len(w) > 3:
                        queries.append(w)
                        break

    # Add function names
    if function_names:
        queries.extend(fn for fn in function_names if fn.isidentifier())

    # Deduplicate while preserving order
    seen = set()
    unique_queries = []
    for q in queries:
        if q not in seen:
            seen.add(q)
            unique_queries.append(q)

    return search_directory(directory, unique_queries)


def hits_to_file_lines(hits: List[TokenHit]) -> List[tuple[str, int]]:
    """Convert token hits to simple (file, line) tuples."""
    return [(h.file, h.line) for h in hits]

