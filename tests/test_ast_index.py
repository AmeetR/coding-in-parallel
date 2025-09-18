from pathlib import Path

import pytest

from coding_in_parallel import ast_index


@pytest.fixture()
def sample_repo(tmp_path: Path) -> Path:
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text("from .module import greet\n")
    (package / "module.py").write_text(
        """def greet(name: str) -> str:\n    return f'Hello {name}'\n\n\nclass Speaker:\n    def say(self, message: str) -> str:\n        return greet(message)\n"""
    )
    return package


def test_build_index_finds_definitions(sample_repo: Path):
    index = ast_index.build_index(sample_repo)
    spans = index.lookup_symbol("greet")
    assert spans, "Expected greet definition span"
    span = spans[0]
    assert span.file.endswith("module.py")
    assert span.node_type == "FunctionDef"
    calls = index.lookup_calls("greet")
    assert any(call.file.endswith("module.py") for call in calls)


def test_slice_reads_requested_lines(sample_repo: Path):
    index = ast_index.build_index(sample_repo)
    slice_text = index.slice("module.py", 1, 2)
    assert "def greet" in slice_text
    assert "return f'Hello" in slice_text

