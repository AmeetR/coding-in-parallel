"""Parse stack traces and pytest output to extract (file, line) frames."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass(frozen=True)
class StackFrame:
    """A single frame extracted from a traceback."""

    file: str  # repo-relative or absolute path
    line: int
    function: Optional[str] = None
    code: Optional[str] = None
    reason: str = ""  # human-readable reason for inclusion

    def with_reason(self, reason: str) -> "StackFrame":
        """Return a copy with the reason field set."""
        return StackFrame(
            file=self.file,
            line=self.line,
            function=self.function,
            code=self.code,
            reason=reason,
        )


@dataclass(frozen=True)
class TraceParseResult:
    """Result of parsing stderr/stdout for stack traces."""

    frames: List[StackFrame]
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    raw_traceback: Optional[str] = None


# Regex patterns for Python tracebacks
# Standard traceback line: '  File "/path/to/file.py", line 42, in function_name'
_TRACEBACK_LINE_RE = re.compile(
    r'^\s*File\s+"([^"]+)",\s+line\s+(\d+)(?:,\s+in\s+(\S+))?',
    re.MULTILINE,
)

# Code line following a traceback frame (indented, not starting with "File")
_CODE_LINE_RE = re.compile(r"^\s{4,}(\S.*)$")

# Error line at end of traceback: "ExceptionType: message"
# Must end with Error, Exception, or Warning to avoid matching "FAILED" etc.
_ERROR_LINE_RE = re.compile(r"^(\w+(?:\.\w+)*(?:Error|Exception|Warning)):\s*(.*)$", re.MULTILINE)

# Pytest "E" prefixed error line: "E       AssertionError: message"
_PYTEST_E_ERROR_RE = re.compile(r"^E\s+(\w+(?:\.\w+)*(?:Error|Exception|Warning)):\s*(.*)$", re.MULTILINE)

# Pytest short test summary line: "FAILED tests/test_foo.py::test_bar - AssertionError: ..."
_PYTEST_FAILED_RE = re.compile(
    r"^FAILED\s+([^\s:]+)::([^\s]+)\s*-?\s*(.*)$",
    re.MULTILINE,
)

# Pytest collection/location line: "tests/test_foo.py:42: AssertionError"
_PYTEST_LOCATION_RE = re.compile(
    r"^([^\s:]+\.py):(\d+):\s*(\w+.*)?$",
    re.MULTILINE,
)


def parse_traceback(text: str, repo_root: Optional[Path] = None) -> TraceParseResult:
    """Parse a Python traceback string and extract stack frames.

    Args:
        text: Raw stderr/stdout containing traceback
        repo_root: If provided, convert absolute paths to repo-relative

    Returns:
        TraceParseResult with frames, error info, and raw traceback
    """
    frames: List[StackFrame] = []
    lines = text.splitlines()

    i = 0
    while i < len(lines):
        line = lines[i]
        match = _TRACEBACK_LINE_RE.match(line)
        if match:
            file_path = match.group(1)
            line_no = int(match.group(2))
            func_name = match.group(3)

            # Try to get the code line (next line if indented)
            code = None
            if i + 1 < len(lines):
                code_match = _CODE_LINE_RE.match(lines[i + 1])
                if code_match:
                    code = code_match.group(1).strip()
                    i += 1

            # Convert to repo-relative if possible
            if repo_root:
                try:
                    abs_path = Path(file_path)
                    if abs_path.is_absolute():
                        file_path = abs_path.relative_to(repo_root).as_posix()
                except (ValueError, RuntimeError):
                    pass  # Keep original path

            frames.append(
                StackFrame(
                    file=file_path,
                    line=line_no,
                    function=func_name,
                    code=code,
                    reason=f"Appears in stack trace at line {line_no}",
                )
            )
        i += 1

    # Extract error type and message
    error_type = None
    error_message = None

    # Try standard error line format first
    for match in _ERROR_LINE_RE.finditer(text):
        # Take the last error line (usually the actual exception)
        error_type = match.group(1)
        error_message = match.group(2).strip() if match.group(2) else None

    # Also try pytest "E" prefixed format
    if not error_type:
        for match in _PYTEST_E_ERROR_RE.finditer(text):
            error_type = match.group(1)
            error_message = match.group(2).strip() if match.group(2) else None

    return TraceParseResult(
        frames=frames,
        error_type=error_type,
        error_message=error_message,
        raw_traceback=text if frames else None,
    )


def parse_pytest_output(text: str, repo_root: Optional[Path] = None) -> TraceParseResult:
    """Parse pytest output to extract failure locations and stack frames.

    Handles both verbose tracebacks and short summary lines.

    Args:
        text: Raw pytest output (stdout + stderr)
        repo_root: If provided, convert absolute paths to repo-relative

    Returns:
        TraceParseResult with frames from failures
    """
    # First, try to parse standard tracebacks embedded in pytest output
    result = parse_traceback(text, repo_root)
    frames = list(result.frames)

    # Also parse pytest-specific failure lines
    for match in _PYTEST_FAILED_RE.finditer(text):
        test_file = match.group(1)
        test_name = match.group(2)
        error_info = match.group(3)

        # Try to find line number from the test file reference
        # This gives us the test location, not the failure location
        frames.append(
            StackFrame(
                file=test_file,
                line=1,  # Will be refined by traceback if available
                function=test_name,
                code=None,
                reason=f"Pytest failure in {test_name}: {error_info[:50]}..." if error_info else f"Pytest failure in {test_name}",
            )
        )

    # Parse location lines like "tests/test_foo.py:42: AssertionError"
    for match in _PYTEST_LOCATION_RE.finditer(text):
        file_path = match.group(1)
        line_no = int(match.group(2))
        error_info = match.group(3)

        if repo_root:
            try:
                abs_path = Path(file_path)
                if abs_path.is_absolute():
                    file_path = abs_path.relative_to(repo_root).as_posix()
            except (ValueError, RuntimeError):
                pass

        frames.append(
            StackFrame(
                file=file_path,
                line=line_no,
                function=None,
                code=None,
                reason=f"Pytest location {file_path}:{line_no}" + (f" ({error_info})" if error_info else ""),
            )
        )

    # Deduplicate frames by (file, line)
    seen = set()
    unique_frames = []
    for frame in frames:
        key = (frame.file, frame.line)
        if key not in seen:
            seen.add(key)
            unique_frames.append(frame)

    return TraceParseResult(
        frames=unique_frames,
        error_type=result.error_type,
        error_message=result.error_message,
        raw_traceback=result.raw_traceback,
    )


def extract_assertion_strings(text: str) -> List[str]:
    """Extract assertion failure messages and error strings from output.

    These can be used for token matching in source files.

    Returns:
        List of strings that might appear in source code (assertion messages, etc.)
    """
    strings: List[str] = []

    # AssertionError messages: "AssertionError: expected X got Y"
    for match in re.finditer(r"AssertionError:\s*(.+?)(?:\n|$)", text):
        msg = match.group(1).strip()
        if msg and len(msg) < 200:  # Reasonable length
            strings.append(msg)

    # Assert statement patterns: "assert x == y" extracted from code lines
    for match in re.finditer(r"^\s{4,}(assert\s+.+?)(?:\n|$)", text, re.MULTILINE):
        stmt = match.group(1).strip()
        if stmt:
            strings.append(stmt)

    # Quoted strings in error messages (potential variable names, etc.)
    for match in re.finditer(r"['\"]([a-zA-Z_][a-zA-Z0-9_]{2,})['\"]", text):
        name = match.group(1)
        if name not in ("True", "False", "None"):
            strings.append(name)

    # Function/method names mentioned in errors
    for match in re.finditer(r"\b([a-z_][a-z0-9_]*)\s*\(", text):
        name = match.group(1)
        if len(name) > 2 and name not in ("def", "class", "for", "if", "in", "is", "not", "and", "or"):
            strings.append(name)

    return list(set(strings))  # Deduplicate


def frames_to_file_lines(frames: List[StackFrame]) -> List[tuple[str, int]]:
    """Convert stack frames to simple (file, line) tuples."""
    return [(f.file, f.line) for f in frames]

