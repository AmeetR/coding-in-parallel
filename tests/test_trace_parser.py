"""Tests for trace_parser using real pytest output."""

import pytest
from pathlib import Path

from coding_in_parallel import trace_parser


# Real pytest output captured from running tests/fixtures/test_failing_example.py
PYTEST_LONG_OUTPUT = """
============================= test session starts ==============================
platform darwin -- Python 3.14.2, pytest-9.0.2, pluggy-1.6.0 -- /Users/ameet/Documents/projects/coding-in-parallel/.venv/bin/python
cachedir: .pytest_cache
rootdir: /Users/ameet/Documents/projects/coding-in-parallel
configfile: pytest.ini
collecting ... collected 5 items

tests/fixtures/test_failing_example.py::test_calculate_sum_basic FAILED  [ 20%]
tests/fixtures/test_failing_example.py::test_calculate_sum_negative FAILED [ 40%]
tests/fixtures/test_failing_example.py::test_helper_function FAILED      [ 60%]
tests/fixtures/test_failing_example.py::TestCalculator::test_add FAILED  [ 80%]
tests/fixtures/test_failing_example.py::TestCalculator::test_process FAILED [100%]

=================================== FAILURES ===================================
___________________________ test_calculate_sum_basic ___________________________

    def test_calculate_sum_basic():
        \"\"\"This test will fail because calculate_sum subtracts instead of adds.\"\"\"
        result = calculate_sum(5, 3)
>       assert result == 8, f"Expected 8 but got {result}"
E       AssertionError: Expected 8 but got 2
E       assert 2 == 8

tests/fixtures/test_failing_example.py:10: AssertionError
_________________________ test_calculate_sum_negative __________________________

    def test_calculate_sum_negative():
        \"\"\"Another failing test.\"\"\"
        result = calculate_sum(-2, 5)
>       assert result == 3, f"Expected 3 but got {result}"
E       AssertionError: Expected 3 but got -7
E       assert -7 == 3

tests/fixtures/test_failing_example.py:16: AssertionError
_____________________________ test_helper_function _____________________________

    def test_helper_function():
        \"\"\"Test helper_function which calls calculate_sum.\"\"\"
        result = helper_function(5)
>       assert result == 15, f"Expected 15 but got {result}"
E       AssertionError: Expected 15 but got -5
E       assert -5 == 15

tests/fixtures/test_failing_example.py:22: AssertionError
___________________________ TestCalculator.test_add ____________________________

self = <fixtures.test_failing_example.TestCalculator object at 0x105de5e50>

    def test_add(self):
        \"\"\"Test Calculator.add method.\"\"\"
        calc = Calculator()
        result = calc.add(10, 20)
>       assert result == 30, f"Expected 30 but got {result}"
E       AssertionError: Expected 30 but got -10
E       assert -10 == 30

tests/fixtures/test_failing_example.py:32: AssertionError
_________________________ TestCalculator.test_process __________________________

self = <fixtures.test_failing_example.TestCalculator object at 0x105de5f90>

    def test_process(self):
        \"\"\"Test Calculator.process method.\"\"\"
        calc = Calculator()
        result = calc.process(5)
>       assert result == 15, f"Expected 15 but got {result}"
E       AssertionError: Expected 15 but got -5
E       assert -5 == 15

tests/fixtures/test_failing_example.py:38: AssertionError
=========================== short test summary info ============================
FAILED tests/fixtures/test_failing_example.py::test_calculate_sum_basic - Ass...
FAILED tests/fixtures/test_failing_example.py::test_calculate_sum_negative - ...
FAILED tests/fixtures/test_failing_example.py::test_helper_function - Asserti...
FAILED tests/fixtures/test_failing_example.py::TestCalculator::test_add - Ass...
FAILED tests/fixtures/test_failing_example.py::TestCalculator::test_process
============================== 5 failed in 0.02s ===============================
"""


PYTEST_NATIVE_TRACEBACK = """
============================= test session starts ==============================
platform darwin -- Python 3.14.2, pytest-9.0.2, pluggy-1.6.0 -- /Users/ameet/Documents/projects/coding-in-parallel/.venv/bin/python
cachedir: .pytest_cache
rootdir: /Users/ameet/Documents/projects/coding-in-parallel
configfile: pytest.ini
collecting ... collected 1 item

tests/fixtures/test_failing_example.py::test_helper_function FAILED      [100%]

=================================== FAILURES ===================================
_____________________________ test_helper_function _____________________________
Traceback (most recent call last):
  File "/Users/ameet/Documents/projects/coding-in-parallel/.venv/lib/python3.14/site-packages/_pytest/runner.py", line 353, in from_call
    result: TResult | None = func()
                             ~~~~^^
  File "/Users/ameet/Documents/projects/coding-in-parallel/.venv/lib/python3.14/site-packages/_pytest/runner.py", line 245, in <lambda>
    lambda: runtest_hook(item=item, **kwds),
            ~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^
  File "/Users/ameet/Documents/projects/coding-in-parallel/.venv/lib/python3.14/site-packages/pluggy/_hooks.py", line 512, in __call__
    return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)
           ~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/ameet/Documents/projects/coding-in-parallel/.venv/lib/python3.14/site-packages/_pytest/python.py", line 166, in pytest_pyfunc_call
    result = testfunction(**testargs)
  File "/Users/ameet/Documents/projects/coding-in-parallel/tests/fixtures/test_failing_example.py", line 22, in test_helper_function
    assert result == 15, f"Expected 15 but got {result}"
AssertionError: Expected 15 but got -5
assert -5 == 15
=========================== short test summary info ============================
FAILED tests/fixtures/test_failing_example.py::test_helper_function - Asserti...
============================== 1 failed in 0.01s ===============================
"""


SIMPLE_PYTHON_TRACEBACK = """
Traceback (most recent call last):
  File "/path/to/script.py", line 10, in main
    result = calculate(x, y)
  File "/path/to/module.py", line 25, in calculate
    return helper(x) + helper(y)
  File "/path/to/module.py", line 30, in helper
    raise ValueError("Invalid input")
ValueError: Invalid input
"""


class TestParseTraceback:
    """Tests for parse_traceback function."""

    def test_parses_simple_traceback(self):
        """Parse a simple Python traceback."""
        result = trace_parser.parse_traceback(SIMPLE_PYTHON_TRACEBACK)

        assert len(result.frames) == 3
        assert result.error_type == "ValueError"
        assert result.error_message == "Invalid input"

        # Check first frame
        assert result.frames[0].file == "/path/to/script.py"
        assert result.frames[0].line == 10
        assert result.frames[0].function == "main"
        assert "calculate" in result.frames[0].code

        # Check last frame
        assert result.frames[2].file == "/path/to/module.py"
        assert result.frames[2].line == 30
        assert result.frames[2].function == "helper"

    def test_parses_native_pytest_traceback(self):
        """Parse pytest --tb=native output with full stack."""
        result = trace_parser.parse_traceback(PYTEST_NATIVE_TRACEBACK)

        # Should find frames from the traceback
        assert len(result.frames) > 0

        # Should find the test file frame
        test_frames = [f for f in result.frames if "test_failing_example.py" in f.file]
        assert len(test_frames) >= 1

        # Check the test file frame
        test_frame = test_frames[-1]  # Last one should be the actual test
        assert test_frame.line == 22
        assert test_frame.function == "test_helper_function"

        # Check error extraction
        assert result.error_type == "AssertionError"

    def test_frames_have_reasons(self):
        """Every frame should have a reason string."""
        result = trace_parser.parse_traceback(SIMPLE_PYTHON_TRACEBACK)

        for frame in result.frames:
            assert frame.reason, f"Frame {frame} missing reason"
            assert "line" in frame.reason.lower()

    def test_repo_relative_paths(self):
        """Paths should be made relative to repo root if provided."""
        repo_root = Path("/Users/ameet/Documents/projects/coding-in-parallel")
        result = trace_parser.parse_traceback(PYTEST_NATIVE_TRACEBACK, repo_root=repo_root)

        # Find frames from the project (not from site-packages)
        project_frames = [
            f for f in result.frames
            if "test_failing_example.py" in f.file and "site-packages" not in f.file
        ]

        # At least one should be repo-relative
        assert any(not f.file.startswith("/") for f in project_frames)


class TestParsePytestOutput:
    """Tests for parse_pytest_output function."""

    def test_parses_pytest_long_output(self):
        """Parse pytest -v --tb=long output."""
        result = trace_parser.parse_pytest_output(PYTEST_LONG_OUTPUT)

        assert len(result.frames) > 0
        assert result.error_type == "AssertionError"

        # Should find location lines like "tests/fixtures/test_failing_example.py:10"
        test_files = {f.file for f in result.frames}
        assert any("test_failing_example.py" in f for f in test_files)

    def test_extracts_failure_locations(self):
        """Should extract line numbers from pytest location output."""
        result = trace_parser.parse_pytest_output(PYTEST_LONG_OUTPUT)

        # Find frames from the test file
        test_frames = [f for f in result.frames if "test_failing_example.py" in f.file]

        # Check that we got the failure line numbers
        lines = {f.line for f in test_frames}
        # Lines 10, 16, 22, 32, 38 are the assertion lines
        expected_lines = {10, 16, 22, 32, 38}
        assert lines & expected_lines, f"Expected some of {expected_lines} but got {lines}"

    def test_deduplicates_frames(self):
        """Duplicate (file, line) pairs should be deduplicated."""
        result = trace_parser.parse_pytest_output(PYTEST_LONG_OUTPUT)

        seen = set()
        for frame in result.frames:
            key = (frame.file, frame.line)
            assert key not in seen, f"Duplicate frame: {key}"
            seen.add(key)


class TestExtractAssertionStrings:
    """Tests for extract_assertion_strings function."""

    def test_extracts_assertion_message(self):
        """Should extract assertion error messages."""
        text = "AssertionError: Expected 8 but got 2"
        strings = trace_parser.extract_assertion_strings(text)

        assert "Expected 8 but got 2" in strings

    def test_extracts_function_names(self):
        """Should extract function names mentioned in errors."""
        text = """
        result = calculate_sum(5, 3)
        helper_function(x)
        """
        strings = trace_parser.extract_assertion_strings(text)

        assert "calculate_sum" in strings
        assert "helper_function" in strings

    def test_extracts_quoted_identifiers(self):
        """Should extract quoted identifier strings."""
        text = """
        Error in 'my_function': value 'expected_value' not found
        """
        strings = trace_parser.extract_assertion_strings(text)

        assert "my_function" in strings
        assert "expected_value" in strings


class TestFramesToFileLines:
    """Tests for frames_to_file_lines helper."""

    def test_converts_frames_to_tuples(self):
        """Should convert frames to (file, line) tuples."""
        frames = [
            trace_parser.StackFrame(file="a.py", line=10),
            trace_parser.StackFrame(file="b.py", line=20, function="foo"),
        ]

        tuples = trace_parser.frames_to_file_lines(frames)

        assert tuples == [("a.py", 10), ("b.py", 20)]


class TestIntegration:
    """Integration tests using real failing test output."""

    def test_full_pipeline_with_real_output(self, tmp_path):
        """Test the full pipeline: run real tests, parse output, extract frames."""
        # Parse the real pytest output we captured
        result = trace_parser.parse_pytest_output(PYTEST_LONG_OUTPUT)

        # Should have found the failure locations
        assert len(result.frames) > 0

        # Extract assertion strings for token search
        strings = trace_parser.extract_assertion_strings(PYTEST_LONG_OUTPUT)

        # Should have extracted useful tokens
        assert len(strings) > 0
        # Should include things like "Expected", function names, etc.
        assert any("Expected" in s for s in strings) or any(s.isidentifier() for s in strings)

        # All frames should have reasons
        for frame in result.frames:
            assert frame.reason, f"Frame missing reason: {frame}"

