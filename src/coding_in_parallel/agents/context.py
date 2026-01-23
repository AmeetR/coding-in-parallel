"""
Context Contracts: Bounded context packets for LLM calls.

BaselineContext: Comprehensive context gathered once at investigation start.
NodeContextPacket: Focused context for investigating a single node.

Key principle: These packets bound what the LLM sees, preventing context overflow.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Set, Tuple


@dataclass
class ErrorAnalysis:
    """Parsed error information from test failure."""
    error_type: str  # e.g., "AssertionError", "TypeError"
    error_message: str
    assertion_strings: List[str]  # extracted assertion values
    stack_frames: List[Dict[str, Any]]  # file, line, function, code


@dataclass
class FailingTestInfo:
    """Information about a failing test."""
    test_file: str
    test_function: str
    test_class: Optional[str]
    test_code: str  # full test source
    fixtures_used: List[str]
    parametrize_values: Optional[List[Any]]


@dataclass
class CallGraphSlice:
    """K-hop subgraph around the failing tests."""
    center_nodes: List[str]  # qualnames of starting points
    nodes: Set[str]  # all qualnames in subgraph
    edges: List[Tuple[str, str, str]]  # (from, to, edge_type)
    node_files: Dict[str, str]  # qualname → file path
    depth: int  # K in K-hop


@dataclass
class CodeStructure:
    """Module and package structure relevant to the failure."""
    packages: List[str]  # package names involved
    modules: List[str]  # module paths involved
    classes: List[str]  # class qualnames involved
    imports: Dict[str, List[str]]  # module → list of imports


@dataclass
class InitialSuspect:
    """A suspect identified from code-grounded analysis (not LLM speculation)."""
    qualname: str
    file_path: str
    line_start: int
    line_end: int
    reason: str  # why this was flagged (e.g., "stack_hit at line 42")
    evidence_kinds: List[str]  # ["stack_hit", "token_hit", etc.]
    score: float


@dataclass
class HistoricalContext:
    """Git history context for suspects."""
    recent_commits: List[Dict[str, Any]]  # commits touching suspect files
    blame_info: Dict[str, List[Dict[str, Any]]]  # file → blame entries
    related_issues: List[str]  # issue references from commits


@dataclass
class TypeContext:
    """Type information for data flow analysis."""
    function_signatures: Dict[str, str]  # qualname → signature string
    return_types: Dict[str, str]  # qualname → return type
    parameter_types: Dict[str, Dict[str, str]]  # qualname → {param: type}


@dataclass
class BaselineContext:
    """
    Comprehensive context gathered at investigation start.
    
    This is created once by the BASELINE node and provides the stable
    background for all subsequent investigation steps.
    """
    
    # Error analysis from traceback
    error_analysis: ErrorAnalysis
    
    # Failing test details
    test_contexts: List[FailingTestInfo]
    
    # K-hop call graph around failing tests
    call_graph_slice: CallGraphSlice
    
    # Module/package structure
    code_structure: CodeStructure
    
    # Initial suspects from code-grounded analysis
    initial_suspects: List[InitialSuspect]
    
    # Historical context (optional, may be empty)
    historical_context: Optional[HistoricalContext] = None
    
    # Type information (optional)
    type_context: Optional[TypeContext] = None
    
    # Raw traceback for reference
    raw_traceback: str = ""
    
    def to_prompt_sections(self) -> Dict[str, str]:
        """Format context as sections for BASELINE prompt."""
        sections = {}
        
        # Error section
        ea = self.error_analysis
        sections["ERROR"] = (
            f"Type: {ea.error_type}\n"
            f"Message: {ea.error_message}\n"
            f"Assertions: {', '.join(ea.assertion_strings) or 'none'}"
        )
        
        # Stack trace section
        frames = "\n".join(
            f"  {i+1}. {f.get('file')}:{f.get('line')} in {f.get('function')}"
            for i, f in enumerate(ea.stack_frames)
        )
        sections["STACK_TRACE"] = frames
        
        # Failing tests section
        tests = "\n".join(
            f"  - {tc.test_file}::{tc.test_function}"
            for tc in self.test_contexts
        )
        sections["FAILING_TESTS"] = tests
        
        # Call graph section
        cg = self.call_graph_slice
        sections["CALL_GRAPH"] = (
            f"Center: {', '.join(cg.center_nodes)}\n"
            f"Nodes ({len(cg.nodes)}): {', '.join(list(cg.nodes)[:10])}{'...' if len(cg.nodes) > 10 else ''}\n"
            f"Depth: {cg.depth}-hop"
        )
        
        # Initial suspects section
        suspects = "\n".join(
            f"  {i+1}. {s.qualname} (score={s.score:.2f})\n"
            f"      File: {s.file_path}:{s.line_start}-{s.line_end}\n"
            f"      Reason: {s.reason}"
            for i, s in enumerate(self.initial_suspects[:5])
        )
        sections["INITIAL_SUSPECTS"] = suspects or "No suspects identified yet"
        
        # Code structure section
        cs = self.code_structure
        sections["CODE_STRUCTURE"] = (
            f"Packages: {', '.join(cs.packages)}\n"
            f"Modules: {', '.join(cs.modules[:5])}{'...' if len(cs.modules) > 5 else ''}\n"
            f"Classes: {', '.join(cs.classes[:5])}{'...' if len(cs.classes) > 5 else ''}"
        )
        
        return sections


@dataclass
class ControlFlowInfo:
    """Control flow graph for a function."""
    entry_block: str
    blocks: List[Dict[str, Any]]  # block_id, statements, successors
    branches: List[Dict[str, Any]]  # condition, true_block, false_block
    loops: List[Dict[str, Any]]  # loop_type, header, body, exit


@dataclass
class DataFlowInfo:
    """Data flow analysis for a function."""
    definitions: Dict[str, List[int]]  # variable → lines where defined
    uses: Dict[str, List[int]]  # variable → lines where used
    def_use_chains: List[Tuple[str, int, int]]  # (var, def_line, use_line)
    tainted_vars: List[str]  # variables that flow from inputs


@dataclass
class CallerCalleeInfo:
    """Immediate callers and callees with their code."""
    callers: List[Dict[str, Any]]  # qualname, file, code_snippet, call_site_line
    callees: List[Dict[str, Any]]  # qualname, file, code_snippet, call_site_line


@dataclass
class TestCoverageInfo:
    """Test coverage information for a node."""
    covered_by_tests: List[str]  # test qualnames that cover this node
    coverage_lines: List[int]  # lines covered by failing tests
    branch_coverage: Dict[int, bool]  # line → was branch taken by failing test


@dataclass
class NodeContextPacket:
    """
    Bounded context packet for investigating a single node.
    
    Created fresh for each CLASSIFY call, containing only what's needed
    to reason about this specific node.
    """
    
    # Node identity
    qualname: str
    file_path: str
    line_start: int
    line_end: int
    
    # The actual code
    code: str
    code_with_line_numbers: str
    
    # Control flow (if available)
    control_flow: Optional[ControlFlowInfo] = None
    
    # Data flow (if available)
    data_flow: Optional[DataFlowInfo] = None
    
    # Immediate callers/callees with code
    caller_callee: Optional[CallerCalleeInfo] = None
    
    # Test coverage
    test_coverage: Optional[TestCoverageInfo] = None
    
    # Related tests (tests that cover this node)
    related_tests: List[str] = field(default_factory=list)
    
    # Evidence already collected for this node
    existing_evidence: List[Dict[str, Any]] = field(default_factory=list)
    
    # Why we're investigating this node
    investigation_reason: str = ""
    
    def to_prompt_sections(self) -> Dict[str, str]:
        """Format context as sections for CLASSIFY prompt."""
        sections = {}
        
        # Node identity
        sections["NODE"] = (
            f"Qualname: {self.qualname}\n"
            f"File: {self.file_path}:{self.line_start}-{self.line_end}"
        )
        
        # Code with line numbers
        sections["CODE"] = self.code_with_line_numbers
        
        # Investigation reason
        sections["REASON"] = self.investigation_reason
        
        # Callers/callees
        if self.caller_callee:
            cc = self.caller_callee
            callers = "\n".join(
                f"  - {c['qualname']} (calls at line {c.get('call_site_line', '?')})"
                for c in cc.callers[:5]
            )
            callees = "\n".join(
                f"  - {c['qualname']} (called at line {c.get('call_site_line', '?')})"
                for c in cc.callees[:5]
            )
            sections["CALLERS"] = callers or "None"
            sections["CALLEES"] = callees or "None"
        
        # Test coverage
        if self.test_coverage:
            tc = self.test_coverage
            sections["TEST_COVERAGE"] = (
                f"Covered by: {', '.join(tc.covered_by_tests[:3])}\n"
                f"Lines covered: {len(tc.coverage_lines)}"
            )
        
        # Existing evidence
        if self.existing_evidence:
            evidence = "\n".join(
                f"  - [{e['kind']}] {e['reason']}"
                for e in self.existing_evidence[:5]
            )
            sections["EXISTING_EVIDENCE"] = evidence
        
        return sections

