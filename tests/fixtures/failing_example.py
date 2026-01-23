"""A deliberately failing module for testing trace parsing."""


def calculate_sum(a: int, b: int) -> int:
    """This function has a bug - it subtracts instead of adding."""
    return a - b  # BUG: should be a + b


def helper_function(x: int) -> int:
    """Helper that calls calculate_sum."""
    return calculate_sum(x, 10)


class Calculator:
    """A calculator class with a buggy method."""

    def add(self, a: int, b: int) -> int:
        """Add two numbers (but it's broken)."""
        return calculate_sum(a, b)

    def process(self, value: int) -> int:
        """Process a value through helper."""
        return helper_function(value)

