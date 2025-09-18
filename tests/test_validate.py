import pytest

from coding_in_parallel import types, validate


VALID_DIFF = """diff --git a/mod.py b/mod.py
@@
-def add(x, y):
-    return x - y
+def add(x, y):
+    return x + y
"""


def test_validate_diff_succeeds_for_well_formed_diff():
    validate.require_unified_diff(VALID_DIFF)


def test_within_limits_counts_changed_lines():
    span = types.AstSpan(file="mod.py", start_line=1, end_line=4, node_type="FunctionDef")
    validate.ensure_within_limits(
        VALID_DIFF,
        allowed_files={"mod.py"},
        max_loc=6,
        max_files=1,
        target_spans=[span],
    )


def test_within_limits_raises_for_too_many_files():
    diff = VALID_DIFF.replace("b/mod.py", "b/other.py")
    span = types.AstSpan(file="mod.py", start_line=1, end_line=4, node_type="FunctionDef")
    with pytest.raises(validate.ValidationError):
        validate.ensure_within_limits(
            diff,
            allowed_files={"mod.py"},
            max_loc=6,
            max_files=1,
            target_spans=[span],
        )


