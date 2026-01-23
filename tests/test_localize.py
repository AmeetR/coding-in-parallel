"""Tests for the localization module."""

import pytest
from pathlib import Path

from coding_in_parallel import localize, types_localize


# Real pytest output for testing
PYTEST_OUTPUT = """
============================= test session starts ==============================
platform darwin -- Python 3.14.2, pytest-9.0.2, pluggy-1.6.0

tests/fixtures/test_failing_example.py::test_calculate_sum_basic FAILED

=================================== FAILURES ===================================
___________________________ test_calculate_sum_basic ___________________________

    def test_calculate_sum_basic():
        result = calculate_sum(5, 3)
>       assert result == 8, f"Expected 8 but got {result}"
E       AssertionError: Expected 8 but got 2
E       assert 2 == 8

tests/fixtures/test_failing_example.py:10: AssertionError
=========================== short test summary info ============================
FAILED tests/fixtures/test_failing_example.py::test_calculate_sum_basic
============================== 1 failed in 0.02s ===============================
"""


@pytest.fixture
def sample_repo(tmp_path: Path) -> Path:
    """Create a sample repo with a bug for localization testing."""
    # Create a module with a bug
    src = tmp_path / "calculator.py"
    src.write_text('''"""Calculator module with a bug."""


def calculate_sum(a: int, b: int) -> int:
    """Add two numbers - but has a bug!"""
    return a - b  # BUG: should be a + b


def helper(x: int) -> int:
    """Helper that calls calculate_sum."""
    return calculate_sum(x, 10)


class Calculator:
    """Calculator class."""

    def add(self, a: int, b: int) -> int:
        """Add method."""
        return calculate_sum(a, b)
''')

    # Create a test file
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "__init__.py").write_text("")
    test_file = tests_dir / "test_calculator.py"
    test_file.write_text('''"""Tests for calculator."""

from calculator import calculate_sum


def test_calculate_sum_basic():
    result = calculate_sum(5, 3)
    assert result == 8, f"Expected 8 but got {result}"
''')

    return tmp_path


class TestLocalize:
    """Tests for the localize function."""

    def test_localize_returns_result(self, sample_repo: Path):
        """Basic test that localize returns a LocalizationResult."""
        result = localize.localize(
            repo_path=str(sample_repo),
            failing_tests=["tests/test_calculator.py::test_calculate_sum_basic"],
            test_output=PYTEST_OUTPUT,
        )

        assert isinstance(result, types_localize.LocalizationResult)
        assert result.suspects is not None
        assert result.subgraph is not None
        assert result.ledger_seed is not None

    def test_localize_finds_suspects_from_test_name(self, sample_repo: Path):
        """Test-to-module heuristic should find related symbols."""
        result = localize.localize(
            repo_path=str(sample_repo),
            failing_tests=["tests/test_calculator.py::test_calculate_sum_basic"],
            test_output=PYTEST_OUTPUT,
        )

        # Should find calculate_sum from the test name heuristic
        suspect_symbols = [s.symbol for s in result.suspects if s.symbol]
        assert "calculate_sum" in suspect_symbols or len(result.suspects) > 0

    def test_suspects_have_reasons(self, sample_repo: Path):
        """Every suspect should have a reason for remediation context."""
        result = localize.localize(
            repo_path=str(sample_repo),
            failing_tests=["tests/test_calculator.py::test_calculate_sum_basic"],
            test_output=PYTEST_OUTPUT,
        )

        for suspect in result.suspects:
            assert suspect.reason, f"Suspect {suspect.id} missing reason"
            # Evidence items should also have reasons
            for item in suspect.evidence.items:
                assert item.reason, f"Evidence item {item.kind} missing reason"

    def test_reasons_for_remediation_helper(self, sample_repo: Path):
        """Test the reasons_for_remediation helper method."""
        result = localize.localize(
            repo_path=str(sample_repo),
            failing_tests=["tests/test_calculator.py::test_calculate_sum_basic"],
            test_output=PYTEST_OUTPUT,
        )

        reasons = result.reasons_for_remediation()
        assert isinstance(reasons, dict)

        # Each suspect should have reasons
        for suspect in result.suspects:
            assert suspect.id in reasons
            suspect_reasons = reasons[suspect.id]
            assert len(suspect_reasons) > 0
            # First reason should be the top-level reason
            assert suspect_reasons[0] == suspect.reason

    def test_slices_generated_for_suspects(self, sample_repo: Path):
        """Slices should be generated for each suspect's file."""
        result = localize.localize(
            repo_path=str(sample_repo),
            failing_tests=["tests/test_calculator.py::test_calculate_sum_basic"],
            test_output=PYTEST_OUTPUT,
        )

        if result.suspects:
            # Should have slices for files containing suspects
            suspect_files = {s.file for s in result.suspects}
            for f in suspect_files:
                assert f in result.slices, f"Missing slice for {f}"

    def test_ledger_seed_populated(self, sample_repo: Path):
        """Ledger seed should be populated with suspects and labels."""
        result = localize.localize(
            repo_path=str(sample_repo),
            failing_tests=["tests/test_calculator.py::test_calculate_sum_basic"],
            test_output=PYTEST_OUTPUT,
        )

        ledger = result.ledger_seed
        assert len(ledger.suspects) == len(result.suspects)
        assert len(ledger.posterior) == len(result.suspects)

        # Each suspect should have labels
        for suspect in result.suspects:
            assert suspect.id in ledger.labels

    def test_hammocks_stage_a_present(self, sample_repo: Path):
        """Stage‑A hammocks should be extracted for Python files."""
        result = localize.localize(
            repo_path=str(sample_repo),
            failing_tests=["tests/test_calculator.py::test_calculate_sum_basic"],
            test_output=PYTEST_OUTPUT,
        )
        assert result.hammocks, "Expected hammock blocks to be extracted"
        # At least one hammock should cover calculate_sum
        found = False
        for blocks in result.hammocks.values():
            for block in blocks:
                if block.start_line <= 5 <= block.end_line:
                    found = True
        assert found

    def test_allowlists_include_hammock_ranges(self, sample_repo: Path):
        """Ledger allowlists should include hammock ranges when available."""
        result = localize.localize(
            repo_path=str(sample_repo),
            failing_tests=["tests/test_calculator.py::test_calculate_sum_basic"],
            test_output=PYTEST_OUTPUT,
        )
        ledger = result.ledger_seed
        assert ledger.allowlists, "Expected allowlists populated"
        # Each suspect should have at least one allowlist range
        for suspect in result.suspects:
            assert suspect.id in ledger.allowlists
            assert len(ledger.allowlists[suspect.id]) >= 1


class TestTestToModuleHeuristic:
    """Tests for the test-to-module name extraction."""

    def test_extracts_from_test_function_name(self):
        """Should extract module name from test function."""
        name = localize._test_to_module_name("tests/test_foo.py::test_bar")
        assert name == "bar"

    def test_extracts_from_test_file_name(self):
        """Should extract module name from test file."""
        name = localize._test_to_module_name("tests/test_calculator.py::test_add")
        # Should get "add" from test_add
        assert name == "add"

    def test_handles_class_tests(self):
        """Should handle class-based tests."""
        name = localize._test_to_module_name("tests/test_foo.py::TestBar::test_baz")
        assert name == "baz"
