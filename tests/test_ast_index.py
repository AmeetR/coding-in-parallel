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


def test_qualname_support(sample_repo: Path):
    """Test that symbols have qualified names."""
    index = ast_index.build_index(sample_repo)

    # Check greet function has qualname
    infos = index.lookup_symbol_info("greet")
    assert infos, "Expected greet symbol info"
    assert any("module.greet" in info.qualname for info in infos)
    assert infos[0].kind == "function"

    # Check Speaker class has qualname
    class_infos = index.lookup_symbol_info("Speaker")
    assert class_infos, "Expected Speaker symbol info"
    assert any("module.Speaker" in info.qualname for info in class_infos)
    assert class_infos[0].kind == "class"

    # Check say method has qualname with class prefix
    method_infos = index.lookup_symbol_info("say")
    assert method_infos, "Expected say symbol info"
    assert any("Speaker.say" in info.qualname for info in method_infos)
    assert method_infos[0].kind == "method"


def test_lookup_by_qualname(sample_repo: Path):
    """Test looking up symbols by fully qualified name."""
    index = ast_index.build_index(sample_repo)

    # Look up greet by qualname
    span = index.lookup_by_qualname("module.greet")
    assert span is not None
    assert span.symbol == "greet"

    # Look up Speaker.say by qualname
    span = index.lookup_by_qualname("module.Speaker.say")
    assert span is not None
    assert span.symbol == "say"


def test_reverse_edges_callers(sample_repo: Path):
    """Test that we can find callers of a function (reverse edges)."""
    index = ast_index.build_index(sample_repo)

    # Speaker.say calls greet, so greet's callers should include Speaker.say
    callers = index.get_callers("greet")
    assert callers, "Expected callers for greet"
    assert any("Speaker.say" in caller for caller in callers)


def test_callees_forward_edges(sample_repo: Path):
    """Test that we can find what a function calls."""
    index = ast_index.build_index(sample_repo)

    # Find the qualname for Speaker.say
    say_infos = index.lookup_symbol_info("say")
    assert say_infos
    say_qualname = say_infos[0].qualname

    # Speaker.say should call greet
    callees = index.get_callees(say_qualname)
    assert "greet" in callees


def test_build_call_subgraph(sample_repo: Path):
    """Test building a bounded subgraph around seed symbols."""
    index = ast_index.build_index(sample_repo)

    # Build subgraph starting from greet
    nodes, edges = index.build_call_subgraph(["greet"], max_hops=1)

    # Should include greet
    assert any("greet" in n for n in nodes)

    # Should include Speaker.say as a caller (if direction includes callers)
    assert any("Speaker.say" in n for n in nodes)


def test_slice_numbered(sample_repo: Path):
    """Test numbered slice output for prompts."""
    index = ast_index.build_index(sample_repo)

    numbered = index.slice_numbered("module.py", 1, 2)
    assert "1:" in numbered or "   1:" in numbered
    assert "def greet" in numbered


def test_build_call_subgraph_retains_multiple_edges(tmp_path: Path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "module.py").write_text(
        """def target(x):\n    return x\n\n\ndef caller_a():\n    return target(1)\n\n\ndef caller_b():\n    return target(2)\n"""
    )
    index = ast_index.build_index(pkg)
    nodes, edges = index.build_call_subgraph(["target"], max_hops=1)
    # Expect edges from both callers to target
    edge_set = {(src, dst) for (src, dst, _k) in edges}
    assert any("caller_a" in src and "target" in dst for (src, dst) in edge_set)
    assert any("caller_b" in src and "target" in dst for (src, dst) in edge_set)


def test_find_symbol_info_covering(sample_repo: Path):
    """Test finding symbol info that covers a line."""
    index = ast_index.build_index(sample_repo)

    # Line 6 should be inside Speaker.say method
    infos = index.find_symbol_info_covering("module.py", 6)
    assert infos, "Expected symbol info covering line 6"

    # Should find both Speaker class and say method
    qualnames = [info.qualname for info in infos]
    assert any("Speaker" in q for q in qualnames)
    assert any("say" in q for q in qualnames)
