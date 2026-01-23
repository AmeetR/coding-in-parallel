"""
Tests for the LangGraph localization agent components.
"""

import pytest
from coding_in_parallel.agents.ledger import (
    EvidenceLedger,
    LocalEvidence,
    PropagatedEvidence,
    LABEL_ORDER,
)
from coding_in_parallel.agents.context import (
    BaselineContext,
    NodeContextPacket,
    ErrorAnalysis,
    FailingTestInfo,
    CallGraphSlice,
    CodeStructure,
    InitialSuspect,
    CallerCalleeInfo,
)
from coding_in_parallel.agents.state import (
    AgentState,
    QueueItem,
    create_initial_state,
)


class TestEvidenceLedger:
    """Tests for EvidenceLedger functionality."""
    
    def test_add_local_evidence(self):
        """Adding local evidence updates scores and labels."""
        ledger = EvidenceLedger()
        
        evidence = LocalEvidence(
            qualname="module.func",
            kind="stack_hit",
            source="traceback:line:42",
            reason="Function appears in stack trace at line 42",
            weight=1.0,
            data={"line": 42},
        )
        
        ledger.add_local_evidence(evidence)
        
        assert "module.func" in ledger.local_evidence
        assert len(ledger.local_evidence["module.func"]) == 1
        assert ledger.scores["module.func"] == 1.0
        assert ledger.labels["module.func"] == "suspect"
    
    def test_add_propagated_evidence(self):
        """Adding propagated evidence updates causal graph."""
        ledger = EvidenceLedger()
        
        evidence = PropagatedEvidence(
            from_node="caller.func",
            to_node="callee.func",
            direction="forward",
            kind="blame_propagation",
            reason="Caller passes tainted data to callee",
            weight=0.5,
        )
        
        ledger.add_propagated_evidence(evidence)
        
        assert len(ledger.propagated_fwd) == 1
        assert ("caller.func", "callee.func", "blame_propagation") in ledger.causal_graph
        assert ledger.scores["callee.func"] == 0.25  # weight * 0.5 decay
    
    def test_monotone_label_demotion(self):
        """Labels can only be demoted, not promoted."""
        ledger = EvidenceLedger()
        
        # Start as unknown
        assert ledger.labels["node"] == "unknown"
        
        # Can set to suspect
        assert ledger.set_label("node", "suspect") is True
        assert ledger.labels["node"] == "suspect"
        
        # Can set to cleared (higher order)
        assert ledger.set_label("node", "cleared") is True
        assert ledger.labels["node"] == "cleared"
        
        # Cannot go back to suspect (lower order)
        assert ledger.set_label("node", "suspect") is False
        assert ledger.labels["node"] == "cleared"
        
        # Can set to root_cause (highest order)
        assert ledger.set_label("node", "root_cause") is True
        assert ledger.labels["node"] == "root_cause"
    
    def test_label_order_values(self):
        """Label order is correct for monotone enforcement."""
        assert LABEL_ORDER["unknown"] < LABEL_ORDER["suspect"]
        assert LABEL_ORDER["suspect"] < LABEL_ORDER["cleared"]
        assert LABEL_ORDER["cleared"] < LABEL_ORDER["root_cause"]
    
    def test_mark_visited(self):
        """Marking a node as visited updates the set."""
        ledger = EvidenceLedger()
        
        ledger.mark_visited("node1")
        ledger.mark_visited("node2")
        
        assert "node1" in ledger.visited
        assert "node2" in ledger.visited
        assert "node3" not in ledger.visited
    
    def test_compute_frontier_single_suspect(self):
        """Single suspect with no edges is its own frontier."""
        ledger = EvidenceLedger()
        ledger.labels["node1"] = "suspect"
        
        frontier = ledger.compute_frontier()
        
        assert frontier == {"node1"}
    
    def test_compute_frontier_with_edges(self):
        """Frontier excludes suspects with incoming edges from suspects."""
        ledger = EvidenceLedger()
        
        # Add suspects
        ledger.labels["caller"] = "suspect"
        ledger.labels["callee"] = "suspect"
        
        # Add edge: caller → callee
        ledger.causal_graph.add(("caller", "callee", "call"))
        
        frontier = ledger.compute_frontier()
        
        # Only caller should be in frontier (callee has incoming from caller)
        assert frontier == {"caller"}
    
    def test_get_evidence_summary(self):
        """Evidence summary includes all relevant data."""
        ledger = EvidenceLedger()
        
        evidence = LocalEvidence(
            qualname="module.func",
            kind="stack_hit",
            source="traceback:line:42",
            reason="In stack trace",
            weight=1.0,
        )
        ledger.add_local_evidence(evidence)
        ledger.mark_visited("module.func")
        
        summary = ledger.get_evidence_summary("module.func")
        
        assert summary["qualname"] == "module.func"
        assert summary["label"] == "suspect"
        assert summary["score"] == 1.0
        assert len(summary["local_evidence"]) == 1
        assert summary["visited"] is True
    
    def test_get_ranked_suspects(self):
        """Ranked suspects are sorted by score."""
        ledger = EvidenceLedger()
        
        # Add suspects with different scores
        ledger.add_local_evidence(LocalEvidence(
            qualname="low", kind="test", source="", reason="", weight=0.5
        ))
        ledger.add_local_evidence(LocalEvidence(
            qualname="high", kind="test", source="", reason="", weight=2.0
        ))
        ledger.add_local_evidence(LocalEvidence(
            qualname="medium", kind="test", source="", reason="", weight=1.0
        ))
        
        ranked = ledger.get_ranked_suspects(top_k=3)
        
        assert len(ranked) == 3
        assert ranked[0]["qualname"] == "high"
        assert ranked[1]["qualname"] == "medium"
        assert ranked[2]["qualname"] == "low"


class TestBaselineContext:
    """Tests for BaselineContext."""
    
    def test_to_prompt_sections(self):
        """Baseline context formats to prompt sections."""
        context = BaselineContext(
            error_analysis=ErrorAnalysis(
                error_type="AssertionError",
                error_message="expected 5, got 3",
                assertion_strings=["5", "3"],
                stack_frames=[
                    {"file": "test.py", "line": 10, "function": "test_add"},
                    {"file": "math.py", "line": 5, "function": "add"},
                ],
            ),
            test_contexts=[
                FailingTestInfo(
                    test_file="test.py",
                    test_function="test_add",
                    test_class=None,
                    test_code="def test_add(): assert add(2, 3) == 5",
                    fixtures_used=[],
                    parametrize_values=None,
                ),
            ],
            call_graph_slice=CallGraphSlice(
                center_nodes=["test.test_add"],
                nodes={"test.test_add", "math.add"},
                edges=[("test.test_add", "math.add", "call")],
                node_files={"test.test_add": "test.py", "math.add": "math.py"},
                depth=2,
            ),
            code_structure=CodeStructure(
                packages=["math"],
                modules=["math.py", "test.py"],
                classes=[],
                imports={},
            ),
            initial_suspects=[
                InitialSuspect(
                    qualname="math.add",
                    file_path="math.py",
                    line_start=1,
                    line_end=5,
                    reason="stack_hit at line 5",
                    evidence_kinds=["stack_hit"],
                    score=0.8,
                ),
            ],
            raw_traceback="...",
        )
        
        sections = context.to_prompt_sections()
        
        assert "ERROR" in sections
        assert "AssertionError" in sections["ERROR"]
        assert "STACK_TRACE" in sections
        assert "math.py:5" in sections["STACK_TRACE"]
        assert "FAILING_TESTS" in sections
        assert "test.py::test_add" in sections["FAILING_TESTS"]
        assert "INITIAL_SUSPECTS" in sections
        assert "math.add" in sections["INITIAL_SUSPECTS"]


class TestNodeContextPacket:
    """Tests for NodeContextPacket."""
    
    def test_to_prompt_sections(self):
        """Node context packet formats to prompt sections."""
        packet = NodeContextPacket(
            qualname="math.add",
            file_path="math.py",
            line_start=1,
            line_end=5,
            code="def add(a, b): return a + b",
            code_with_line_numbers="1| def add(a, b): return a + b",
            caller_callee=CallerCalleeInfo(
                callers=[{"qualname": "test.test_add", "call_site_line": 3}],
                callees=[],
            ),
            existing_evidence=[
                {"kind": "stack_hit", "reason": "In stack trace", "weight": 1.0}
            ],
            investigation_reason="High priority suspect",
        )
        
        sections = packet.to_prompt_sections()
        
        assert "NODE" in sections
        assert "math.add" in sections["NODE"]
        assert "CODE" in sections
        assert "def add" in sections["CODE"]
        assert "REASON" in sections
        assert "High priority" in sections["REASON"]
        assert "CALLERS" in sections
        assert "test.test_add" in sections["CALLERS"]
        assert "EXISTING_EVIDENCE" in sections
        assert "stack_hit" in sections["EXISTING_EVIDENCE"]


class TestAgentState:
    """Tests for AgentState and related types."""
    
    def test_create_initial_state(self):
        """Initial state has correct defaults."""
        state = create_initial_state(
            repo_root="/path/to/repo",
            test_command="pytest",
            failing_tests=["test_foo.py::test_bar"],
            traceback_output="AssertionError...",
            max_steps=10,
        )
        
        assert state["repo_root"] == "/path/to/repo"
        assert state["test_command"] == "pytest"
        assert state["failing_tests"] == ["test_foo.py::test_bar"]
        assert state["traceback_output"] == "AssertionError..."
        assert state["max_steps"] == 10
        assert state["step_count"] == 0
        assert state["done"] is False
        assert isinstance(state["ledger"], EvidenceLedger)
        assert state["queue"] == []
        assert state["qualname_to_span"] == {}
    
    def test_queue_item_attributes(self):
        """QueueItem has all required attributes."""
        item = QueueItem(
            qualname="module.func",
            file_path="module.py",
            priority=0.8,
            reason="stack_hit",
            added_by="BASELINE",
        )
        
        assert item.qualname == "module.func"
        assert item.file_path == "module.py"
        assert item.priority == 0.8
        assert item.reason == "stack_hit"
        assert item.added_by == "BASELINE"
