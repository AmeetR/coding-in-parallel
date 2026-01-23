"""Tests that will deliberately fail - for trace parser testing."""

import pytest
from .failing_example import Calculator, calculate_sum, helper_function


def test_calculate_sum_basic():
    """This test will fail because calculate_sum subtracts instead of adds."""
    result = calculate_sum(5, 3)
    assert result == 8, f"Expected 8 but got {result}"


def test_calculate_sum_negative():
    """Another failing test."""
    result = calculate_sum(-2, 5)
    assert result == 3, f"Expected 3 but got {result}"


def test_helper_function():
    """Test helper_function which calls calculate_sum."""
    result = helper_function(5)
    assert result == 15, f"Expected 15 but got {result}"


class TestCalculator:
    """Test class for Calculator."""

    def test_add(self):
        """Test Calculator.add method."""
        calc = Calculator()
        result = calc.add(10, 20)
        assert result == 30, f"Expected 30 but got {result}"

    def test_process(self):
        """Test Calculator.process method."""
        calc = Calculator()
        result = calc.process(5)
        assert result == 15, f"Expected 15 but got {result}"

