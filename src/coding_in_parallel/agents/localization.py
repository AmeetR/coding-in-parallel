"""
LangGraph Localization Agent: Graph-guided "Explore-and-Judge" loop.

Architecture:
    BASELINE → (SELECT → CLASSIFY → RECONCILE → PROPOSE)* → DONE

Each node in the graph is a pure function that:
1. Reads from AgentState
2. Performs deterministic work OR makes a bounded LLM call
3. Returns state updates

The LLM never controls the loop - it only classifies evidence and suggests candidates.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any, List, Optional, Literal

from langgraph.graph import StateGraph, END

from pydantic import ValidationError

from coding_in_parallel.agents.state import AgentState, QueueItem, create_initial_state
from coding_in_parallel.agents.ledger import EvidenceLedger, LocalEvidence
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
from coding_in_parallel.agents.models import (
    ClassificationResult,
    ProposeResult,
)
from coding_in_parallel.agents.prompts import (
    format_baseline_prompt,
    format_classify_prompt,
    format_propose_prompt,
)
from coding_in_parallel import llm


# =============================================================================
# Node Functions
# =============================================================================

def baseline_node(state: AgentState) -> Dict[str, Any]:
    """
    BASELINE: Gather comprehensive context, create investigation summary.
    
    This runs once at the start to:
    1. Parse traceback and extract error info
    2. Identify failing tests and their code
    3. Build K-hop call graph around stack frames
    4. Seed initial suspects from code-grounded analysis
    5. Generate high-level investigation summary (LLM call)
    """
    from coding_in_parallel import ast_index as ast_index_module
    from coding_in_parallel import localize as localize_module
    from coding_in_parallel import trace_parser

    repo_root = Path(state["repo_root"])
    traceback = state.get("traceback_output", "")
    failing_tests = state.get("failing_tests", [])

    # 1. Parse traceback
    parse_result = trace_parser.parse_pytest_output(traceback, repo_root=repo_root)

    # 2. Extract assertion strings
    assertions = trace_parser.extract_assertion_strings(traceback)

    # 3. Build AST index
    index = ast_index_module.build_index(repo_root)

    # 4. Run code-grounded localization
    loc_result = localize_module.localize(
        repo_path=str(repo_root),
        failing_tests=list(failing_tests),
        test_output=traceback,
    )
    
    # 5. Build context structures
    error_analysis = ErrorAnalysis(
        error_type=parse_result.error_type or "Unknown",
        error_message=parse_result.error_message or "",
        assertion_strings=list(assertions),
        stack_frames=[
            {
                "file": f.file,
                "line": f.line,
                "function": f.function,
                "code": f.code,
            }
            for f in parse_result.frames
        ],
    )
    
    # Build test contexts
    test_contexts: List[FailingTestInfo] = []
    for test_id in failing_tests:
        # Parse test_file::test_func format
        if "::" in test_id:
            test_file, test_func = test_id.split("::", 1)
            test_class = None
            if "::" in test_func:
                test_class, test_func = test_func.split("::", 1)
        else:
            test_file = test_id
            test_func = ""
            test_class = None
        
        # Try to read test code
        test_code = ""
        test_path = repo_root / test_file
        if test_path.exists():
            try:
                test_code = test_path.read_text()
            except Exception:
                pass
        
        test_contexts.append(FailingTestInfo(
            test_file=test_file,
            test_function=test_func,
            test_class=test_class,
            test_code=test_code[:2000],  # Bounded
            fixtures_used=[],
            parametrize_values=None,
        ))
    
    # Build K-hop call graph around stack frames
    center_nodes: List[str] = [s.qualname for s in loc_result.suspects if s.qualname]
    if not center_nodes:
        for frame in parse_result.frames:
            infos = index.find_symbol_info_covering(frame.file, frame.line)
            for info in infos:
                if info.qualname not in center_nodes:
                    center_nodes.append(info.qualname)
    
    # Get K-hop subgraph
    k_hop = 2  # configurable
    nodes, edges = index.build_call_subgraph(center_nodes, max_hops=k_hop)
    node_files = {}
    for node in nodes:
        span = index.lookup_by_qualname(node)
        if span:
            node_files[node] = span.file
    
    call_graph_slice = CallGraphSlice(
        center_nodes=center_nodes,
        nodes=set(nodes),
        edges=[(src, dst, kind) for (src, dst, kind) in edges],
        node_files=node_files,
        depth=k_hop,
    )
    
    # Build code structure
    modules = set()
    packages = set()
    for suspect in loc_result.suspects:
        if suspect.file:
            modules.add(suspect.file)
            parts = suspect.file.replace("/", ".").replace(".py", "").split(".")
            if len(parts) > 1:
                packages.add(parts[0])
    
    code_structure = CodeStructure(
        packages=list(packages),
        modules=list(modules),
        classes=[],  # TODO: extract from AST
        imports={},  # TODO: extract from AST
    )
    
    # Build initial suspects
    initial_suspects: List[InitialSuspect] = []
    for suspect in loc_result.suspects[:10]:  # Top 10
        initial_suspects.append(InitialSuspect(
            qualname=suspect.qualname or f"{suspect.file}:{suspect.span.start_line}-{suspect.span.end_line}",
            file_path=suspect.file,
            line_start=suspect.span.start_line,
            line_end=suspect.span.end_line,
            reason=suspect.reason,
            evidence_kinds=[item.kind for item in suspect.evidence.items],
            score=suspect.score,
        ))
    
    # Build baseline context
    baseline_context = BaselineContext(
        error_analysis=error_analysis,
        test_contexts=test_contexts,
        call_graph_slice=call_graph_slice,
        code_structure=code_structure,
        initial_suspects=initial_suspects,
        raw_traceback=traceback[:5000],  # Bounded
    )
    
    # Initialize ledger with initial suspects
    ledger = EvidenceLedger()
    qualname_to_span: Dict[str, Dict[str, Any]] = {}
    for suspect in loc_result.suspects:
        key = suspect.qualname or f"{suspect.file}:{suspect.span.start_line}-{suspect.span.end_line}"
        qualname_to_span[key] = {
            "file": suspect.file,
            "line_start": suspect.span.start_line,
            "line_end": suspect.span.end_line,
            "symbol": suspect.span.symbol or "",
        }
        for item in suspect.evidence.items:
            ledger.add_local_evidence(LocalEvidence(
                qualname=key,
                kind=item.kind,
                source=item.source,
                reason=item.reason,
                weight=item.weight,
                data=item.data,
            ))
    
    # Build initial queue from suspects
    queue: List[QueueItem] = []
    for i, suspect in enumerate(initial_suspects):
        queue.append(QueueItem(
            qualname=suspect.qualname,
            file_path=suspect.file_path,
            priority=suspect.score,
            reason=suspect.reason,
            added_by="BASELINE",
        ))
    
    # Sort by priority (highest first)
    queue.sort(key=lambda x: x.priority, reverse=True)
    
    # Generate investigation summary (placeholder for LLM call)
    investigation_summary = _generate_investigation_summary(baseline_context)
    try:
        prompt = format_baseline_prompt(baseline_context.to_prompt_sections())
        investigation_summary = llm.complete(prompt).strip() or investigation_summary
    except Exception:
        pass
    
    return {
        "baseline_context": baseline_context,
        "investigation_summary": investigation_summary,
        "ledger": ledger,
        "queue": queue,
        "step_count": 0,
        "qualname_to_span": qualname_to_span,
    }


def select_node(state: AgentState) -> Dict[str, Any]:
    """
    SELECT: Pick the next node from the queue to investigate.
    
    Pure deterministic function - no LLM call.
    """
    queue = list(state.get("queue", []))
    ledger = state.get("ledger", EvidenceLedger())
    
    # Skip nodes we've already visited
    while queue and queue[0].qualname in ledger.visited:
        queue.pop(0)
    
    if not queue:
        return {
            "current_node": None,
            "done": True,
            "done_reason": "queue_empty",
            "final_suspects": ledger.get_ranked_suspects(),
        }
    
    # Pop highest priority item
    next_item = queue.pop(0)
    
    return {
        "current_node": next_item.qualname,
        "queue": queue,
    }


def classify_node(state: AgentState) -> Dict[str, Any]:
    """
    CLASSIFY: Build context packet, LLM classifies evidence.
    
    This is where the bounded LLM call happens. The LLM sees:
    1. Investigation summary (stable background)
    2. Node context packet (focused on this node)
    
    The LLM outputs:
    - Classification: suspect / cleared / root_cause
    - Evidence items with reasons
    - Confidence score
    """
    current_node = state.get("current_node")
    if not current_node:
        return {}
    
    repo_root = state["repo_root"]
    baseline = state.get("baseline_context")
    ledger = state.get("ledger", EvidenceLedger())
    
    # Build context packet for this node
    context_packet = _build_node_context_packet(
        qualname=current_node,
        repo_root=repo_root,
        baseline=baseline,
        ledger=ledger,
        qualname_to_span=state.get("qualname_to_span"),
    )
    
    # Get investigation summary
    investigation_summary = state.get("investigation_summary", "")
    
    # Make bounded LLM call for classification
    classification = _llm_classify_node(
        investigation_summary=investigation_summary,
        context_packet=context_packet,
    )
    
    return {
        "current_context_packet": context_packet.to_prompt_sections() if context_packet else None,
        "_classification": classification,  # Internal, consumed by reconcile
    }


def reconcile_node(state: AgentState) -> Dict[str, Any]:
    """
    RECONCILE: Merge classification results into ledger.
    
    Pure deterministic function:
    1. Add new evidence to ledger
    2. Update node label (with monotone enforcement)
    3. Mark node as visited
    4. Recompute frontier
    """
    current_node = state.get("current_node")
    if not current_node:
        return {}
    
    ledger = state.get("ledger", EvidenceLedger())
    classification = state.get("_classification", None)
    if isinstance(classification, dict):
        try:
            classification = ClassificationResult.model_validate(classification)
        except ValidationError:
            classification = ClassificationResult()
    elif classification is None:
        classification = ClassificationResult()
    
    # Add evidence from classification
    for evidence_item in classification.evidence:
        ledger.add_local_evidence(LocalEvidence(
            qualname=current_node,
            kind=evidence_item.kind,
            source="CLASSIFY",
            reason=evidence_item.reason,
            weight=evidence_item.weight,
            data=evidence_item.data,
        ))
    
    # Update label
    new_label = classification.label
    ledger.set_label(current_node, new_label)
    
    # Mark visited
    ledger.mark_visited(current_node)
    
    # Recompute frontier
    ledger.compute_frontier()
    
    # Check for root causes
    root_causes = [q for q, label in ledger.labels.items() if label == "root_cause"]
    
    return {
        "ledger": ledger,
        "root_causes": root_causes,
        "step_count": state.get("step_count", 0) + 1,
    }


def propose_node(state: AgentState) -> Dict[str, Any]:
    """
    PROPOSE: LLM suggests next candidates or probes.
    
    Based on current state, the LLM can:
    1. Suggest new nodes to add to queue
    2. Request targeted test probes
    3. Declare investigation complete
    """
    ledger = state.get("ledger", EvidenceLedger())
    baseline = state.get("baseline_context")
    queue = list(state.get("queue", []))
    step_count = state.get("step_count", 0)
    max_steps = state.get("max_steps", 20)
    
    # Check termination conditions
    if step_count >= max_steps:
        return {
            "done": True,
            "done_reason": "max_steps",
            "final_suspects": ledger.get_ranked_suspects(),
        }
    
    # Check if we have high-confidence root causes
    root_causes = [q for q, label in ledger.labels.items() if label == "root_cause"]
    if root_causes:
        return {
            "done": True,
            "done_reason": "root_cause_found",
            "final_suspects": ledger.get_ranked_suspects(),
        }
    
    # LLM proposes next steps
    proposals = _llm_propose_next(
        ledger=ledger,
        baseline=baseline,
        current_queue=queue,
        investigation_summary=state.get("investigation_summary", ""),
    )
    
    # Add new candidates to queue
    if proposals.action == "conclude":
        return {
            "done": True,
            "done_reason": proposals.conclusion_reason or "llm_conclude",
            "final_suspects": ledger.get_ranked_suspects(),
        }

    for candidate in proposals.candidates:
        queue.append(QueueItem(
            qualname=candidate.qualname,
            file_path=candidate.file_path,
            priority=candidate.priority,
            reason=candidate.reason or "LLM proposed",
            added_by=f"PROPOSE:step_{step_count}",
        ))
    
    # Sort queue
    queue.sort(key=lambda x: x.priority, reverse=True)
    
    # Handle probe requests
    pending_probes = state.get("pending_probes", [])
    for probe in proposals.probes:
        pending_probes.append(probe.model_dump())

    if not queue:
        return {
            "done": True,
            "done_reason": "queue_empty",
            "final_suspects": ledger.get_ranked_suspects(),
        }

    return {
        "queue": queue,
        "pending_probes": pending_probes,
    }


# =============================================================================
# Router Functions
# =============================================================================

def should_continue(state: AgentState) -> Literal["select", "done"]:
    """Decide whether to continue the loop or finish."""
    if state.get("done"):
        return "done"
    if not state.get("queue"):
        return "done"
    return "select"


def after_propose(state: AgentState) -> Literal["select", "done"]:
    """After PROPOSE, check if we should continue."""
    if state.get("done"):
        return "done"
    if not state.get("queue"):
        return "done"
    return "select"


# =============================================================================
# Helper Functions (will be replaced with actual implementations)
# =============================================================================

def _generate_investigation_summary(baseline: BaselineContext) -> str:
    """Generate a high-level investigation summary from baseline context."""
    # TODO: Replace with actual LLM call
    sections = baseline.to_prompt_sections()
    
    summary_parts = [
        "## Investigation Summary\n",
        f"**Error**: {sections.get('ERROR', 'Unknown')}\n",
        f"\n**Failing Tests**:\n{sections.get('FAILING_TESTS', 'None')}\n",
        f"\n**Initial Suspects**:\n{sections.get('INITIAL_SUSPECTS', 'None')}\n",
    ]
    
    return "".join(summary_parts)


def _build_node_context_packet(
    qualname: str,
    repo_root: str,
    baseline: Optional[BaselineContext],
    ledger: EvidenceLedger,
    qualname_to_span: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Optional[NodeContextPacket]:
    """Build a bounded context packet for a node."""
    from coding_in_parallel import ast_index as ast_index_module
    from pathlib import Path

    index = ast_index_module.build_index(Path(repo_root))

    file_path = ""
    line_start = 0
    line_end = 0
    code = ""

    if qualname_to_span and qualname in qualname_to_span:
        meta = qualname_to_span[qualname]
        file_path = meta.get("file", "")
        line_start = int(meta.get("line_start", 0) or 0)
        line_end = int(meta.get("line_end", 0) or 0)

    if not file_path:
        span = index.lookup_by_qualname(qualname)
        if span:
            file_path = span.file
            line_start = span.start_line
            line_end = span.end_line

    if file_path and line_start and line_end:
        code = index.slice_numbered(file_path, line_start, line_end)

    # Get callers and callees
    callers = index.get_callers(qualname)
    callee_names = index.get_callees(qualname)
    callees: List[str] = []
    for name in callee_names:
        infos = index.lookup_symbol_info(name)
        if infos:
            callees.append(infos[0].qualname)
        else:
            callees.append(name)
    
    caller_callee = CallerCalleeInfo(
        callers=[{"qualname": c, "file": "", "code_snippet": "", "call_site_line": 0} for c in callers],
        callees=[{"qualname": c, "file": "", "code_snippet": "", "call_site_line": 0} for c in callees],
    )
    
    # Get existing evidence
    existing_evidence = []
    for ev in ledger.local_evidence.get(qualname, []):
        existing_evidence.append({
            "kind": ev.kind,
            "reason": ev.reason,
            "weight": ev.weight,
        })
    
    return NodeContextPacket(
        qualname=qualname,
        file_path=file_path,
        line_start=line_start,
        line_end=line_end,
        code=code,
        code_with_line_numbers=code,
        caller_callee=caller_callee,
        existing_evidence=existing_evidence,
        investigation_reason=f"Node in investigation queue",
    )


def _llm_classify_node(
    investigation_summary: str,
    context_packet: Optional[NodeContextPacket],
) -> ClassificationResult:
    """
    Make bounded LLM call to classify a node.
    """
    if not context_packet:
        return ClassificationResult()
    try:
        prompt = format_classify_prompt(
            investigation_summary=investigation_summary,
            node_sections=context_packet.to_prompt_sections(),
        )
        response = llm.complete(prompt)
        data = json.loads(response or "{}")
        return ClassificationResult.model_validate(data)
    except (json.JSONDecodeError, ValidationError, Exception):
        return ClassificationResult()


def _llm_propose_next(
    ledger: EvidenceLedger,
    baseline: Optional[BaselineContext],
    current_queue: List[QueueItem],
    investigation_summary: str,
) -> ProposeResult:
    """
    Make LLM call to propose next investigation steps.
    """
    if not baseline:
        return ProposeResult(action="continue")
    try:
        evidence_summary = json.dumps(ledger.get_ranked_suspects(top_k=5), ensure_ascii=False)
        prompt = format_propose_prompt(
            investigation_summary=investigation_summary or baseline.to_prompt_sections().get("ERROR", ""),
            evidence_summary=evidence_summary,
            frontier=list(ledger.frontier),
            visited=list(ledger.visited),
            queue=[q.qualname for q in current_queue],
        )
        response = llm.complete(prompt)
        data = json.loads(response or "{}")
        return ProposeResult.model_validate(data)
    except (json.JSONDecodeError, ValidationError, Exception):
        return ProposeResult(action="continue")


# =============================================================================
# Graph Builder
# =============================================================================

def build_localization_graph() -> StateGraph:
    """
    Build the LangGraph for localization.
    
    Graph structure:
        BASELINE → SELECT → CLASSIFY → RECONCILE → PROPOSE → (loop or END)
    """
    graph = StateGraph(AgentState)
    
    # Add nodes
    graph.add_node("baseline", baseline_node)
    graph.add_node("select", select_node)
    graph.add_node("classify", classify_node)
    graph.add_node("reconcile", reconcile_node)
    graph.add_node("propose", propose_node)
    
    # Set entry point
    graph.set_entry_point("baseline")
    
    # Add edges
    graph.add_edge("baseline", "select")
    graph.add_edge("select", "classify")
    graph.add_edge("classify", "reconcile")
    graph.add_edge("reconcile", "propose")
    
    # Conditional edge from propose
    graph.add_conditional_edges(
        "propose",
        after_propose,
        {
            "select": "select",
            "done": END,
        }
    )
    
    return graph


def create_localization_agent():
    """Create a compiled localization agent."""
    graph = build_localization_graph()
    return graph.compile()


# =============================================================================
# Public API
# =============================================================================

def run_localization(
    repo_root: str,
    test_command: str,
    failing_tests: List[str],
    traceback_output: str,
    max_steps: int = 20,
) -> Dict[str, Any]:
    """
    Run the localization agent to find root causes.
    
    Returns:
        Dict with:
        - root_causes: List of qualnames identified as root causes
        - final_suspects: Ranked list of suspects with evidence
        - done_reason: Why investigation ended
        - ledger: Full evidence ledger for debugging
    """
    # Create initial state
    state = create_initial_state(
        repo_root=repo_root,
        test_command=test_command,
        failing_tests=failing_tests,
        traceback_output=traceback_output,
        max_steps=max_steps,
    )
    
    # Create and run agent
    agent = create_localization_agent()
    final_state = agent.invoke(state)
    
    return {
        "root_causes": final_state.get("root_causes", []),
        "final_suspects": final_state.get("final_suspects", []),
        "done_reason": final_state.get("done_reason", ""),
        "ledger": final_state.get("ledger"),
        "step_count": final_state.get("step_count", 0),
        "baseline_context": final_state.get("baseline_context"),
        "investigation_summary": final_state.get("investigation_summary", ""),
        "qualname_to_span": final_state.get("qualname_to_span", {}),
    }
