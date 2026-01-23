"""
Control Flow Graph (CFG) builder for Python functions.

Builds a simplified CFG suitable for localization analysis:
- Basic blocks with statements
- Branch edges (if/else, loops, try/except)
- Exit points

This is a v0 implementation focusing on correctness over completeness.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import List, Dict, Set, Optional, Tuple, Any


@dataclass
class BasicBlock:
    """A sequence of statements with single entry/exit (except for branches)."""
    id: str
    statements: List[ast.stmt] = field(default_factory=list)
    line_start: int = 0
    line_end: int = 0
    
    # Successors: block_id → edge_type
    successors: Dict[str, str] = field(default_factory=dict)
    
    # Predecessors: block_id → edge_type
    predecessors: Dict[str, str] = field(default_factory=dict)
    
    def add_successor(self, block_id: str, edge_type: str = "fall") -> None:
        self.successors[block_id] = edge_type
    
    def add_predecessor(self, block_id: str, edge_type: str = "fall") -> None:
        self.predecessors[block_id] = edge_type
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "id": self.id,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "statement_count": len(self.statements),
            "successors": self.successors,
            "predecessors": self.predecessors,
        }


@dataclass
class BranchInfo:
    """Information about a branch point."""
    block_id: str
    condition_line: int
    condition_code: str
    true_block: str
    false_block: Optional[str]  # None for loops without else
    branch_type: str  # "if", "while", "for", "try", "match"


@dataclass
class LoopInfo:
    """Information about a loop."""
    header_block: str
    body_blocks: Set[str]
    exit_block: str
    loop_type: str  # "while", "for"
    iterator_line: Optional[int]


@dataclass
class CFG:
    """Control Flow Graph for a function."""
    function_name: str
    file_path: str
    line_start: int
    line_end: int
    
    # Blocks
    entry_block: str
    exit_blocks: Set[str] = field(default_factory=set)
    blocks: Dict[str, BasicBlock] = field(default_factory=dict)
    
    # Structural info
    branches: List[BranchInfo] = field(default_factory=list)
    loops: List[LoopInfo] = field(default_factory=list)
    
    # Exception handling
    try_blocks: List[Dict[str, Any]] = field(default_factory=list)
    
    def get_block(self, block_id: str) -> Optional[BasicBlock]:
        return self.blocks.get(block_id)
    
    def get_successors(self, block_id: str) -> List[str]:
        block = self.blocks.get(block_id)
        return list(block.successors.keys()) if block else []
    
    def get_predecessors(self, block_id: str) -> List[str]:
        block = self.blocks.get(block_id)
        return list(block.predecessors.keys()) if block else []
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "function_name": self.function_name,
            "file_path": self.file_path,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "entry_block": self.entry_block,
            "exit_blocks": list(self.exit_blocks),
            "blocks": {k: v.to_dict() for k, v in self.blocks.items()},
            "branches": [
                {
                    "block_id": b.block_id,
                    "condition_line": b.condition_line,
                    "true_block": b.true_block,
                    "false_block": b.false_block,
                    "branch_type": b.branch_type,
                }
                for b in self.branches
            ],
            "loops": [
                {
                    "header_block": l.header_block,
                    "exit_block": l.exit_block,
                    "loop_type": l.loop_type,
                }
                for l in self.loops
            ],
        }


class CFGBuilder(ast.NodeVisitor):
    """
    Build a CFG from a Python function AST.
    
    Usage:
        builder = CFGBuilder("my_func", "path/to/file.py")
        cfg = builder.build(func_node)
    """
    
    def __init__(self, function_name: str, file_path: str):
        self.function_name = function_name
        self.file_path = file_path
        self.blocks: Dict[str, BasicBlock] = {}
        self.branches: List[BranchInfo] = []
        self.loops: List[LoopInfo] = []
        self.try_blocks: List[Dict[str, Any]] = []
        
        self._block_counter = 0
        self._current_block: Optional[BasicBlock] = None
        self._entry_block: Optional[str] = None
        self._exit_blocks: Set[str] = set()
        
        # Context stack for break/continue
        self._loop_stack: List[Tuple[str, str]] = []  # (header_block, exit_block)
    
    def _new_block(self, prefix: str = "B") -> BasicBlock:
        """Create a new basic block."""
        block_id = f"{prefix}{self._block_counter}"
        self._block_counter += 1
        block = BasicBlock(id=block_id)
        self.blocks[block_id] = block
        return block
    
    def _link(self, from_block: BasicBlock, to_block: BasicBlock, edge_type: str = "fall") -> None:
        """Link two blocks with an edge."""
        from_block.add_successor(to_block.id, edge_type)
        to_block.add_predecessor(from_block.id, edge_type)
    
    def build(self, func_node: ast.FunctionDef) -> CFG:
        """Build CFG from function AST node."""
        # Create entry block
        entry = self._new_block("entry")
        self._entry_block = entry.id
        self._current_block = entry
        
        if func_node.body:
            entry.line_start = func_node.body[0].lineno
        
        # Process function body
        self._process_stmts(func_node.body)
        
        # Mark current block as exit if not already linked
        if self._current_block and not self._current_block.successors:
            self._exit_blocks.add(self._current_block.id)
        
        # Update line ranges for blocks
        for block in self.blocks.values():
            if block.statements:
                block.line_start = min(s.lineno for s in block.statements)
                block.line_end = max(
                    getattr(s, 'end_lineno', s.lineno) or s.lineno 
                    for s in block.statements
                )
        
        return CFG(
            function_name=self.function_name,
            file_path=self.file_path,
            line_start=func_node.lineno,
            line_end=getattr(func_node, 'end_lineno', func_node.lineno) or func_node.lineno,
            entry_block=self._entry_block,
            exit_blocks=self._exit_blocks,
            blocks=self.blocks,
            branches=self.branches,
            loops=self.loops,
            try_blocks=self.try_blocks,
        )
    
    def _process_stmts(self, stmts: List[ast.stmt]) -> None:
        """Process a list of statements."""
        for stmt in stmts:
            if self._current_block is None:
                # Unreachable code after return/raise/break/continue
                break
            self._process_stmt(stmt)
    
    def _process_stmt(self, stmt: ast.stmt) -> None:
        """Process a single statement."""
        if isinstance(stmt, ast.If):
            self._process_if(stmt)
        elif isinstance(stmt, ast.While):
            self._process_while(stmt)
        elif isinstance(stmt, ast.For):
            self._process_for(stmt)
        elif isinstance(stmt, ast.Try):
            self._process_try(stmt)
        elif isinstance(stmt, ast.Return):
            self._process_return(stmt)
        elif isinstance(stmt, ast.Raise):
            self._process_raise(stmt)
        elif isinstance(stmt, ast.Break):
            self._process_break(stmt)
        elif isinstance(stmt, ast.Continue):
            self._process_continue(stmt)
        elif isinstance(stmt, ast.With):
            self._process_with(stmt)
        elif isinstance(stmt, ast.Match):
            self._process_match(stmt)
        else:
            # Regular statement: add to current block
            if self._current_block:
                self._current_block.statements.append(stmt)
    
    def _process_if(self, node: ast.If) -> None:
        """Process if statement."""
        if not self._current_block:
            return
        
        # Add condition to current block
        self._current_block.statements.append(node)
        cond_block = self._current_block
        
        # Create blocks for branches
        true_block = self._new_block("if_true")
        merge_block = self._new_block("if_merge")
        
        # Link condition → true
        self._link(cond_block, true_block, "true")
        
        # Process true branch
        self._current_block = true_block
        self._process_stmts(node.body)
        if self._current_block:
            self._link(self._current_block, merge_block)
        
        # Process false branch (else/elif)
        if node.orelse:
            false_block = self._new_block("if_false")
            self._link(cond_block, false_block, "false")
            self._current_block = false_block
            self._process_stmts(node.orelse)
            if self._current_block:
                self._link(self._current_block, merge_block)
            
            self.branches.append(BranchInfo(
                block_id=cond_block.id,
                condition_line=node.lineno,
                condition_code=ast.unparse(node.test) if hasattr(ast, 'unparse') else "",
                true_block=true_block.id,
                false_block=false_block.id,
                branch_type="if",
            ))
        else:
            # No else: condition → merge on false
            self._link(cond_block, merge_block, "false")
            self.branches.append(BranchInfo(
                block_id=cond_block.id,
                condition_line=node.lineno,
                condition_code=ast.unparse(node.test) if hasattr(ast, 'unparse') else "",
                true_block=true_block.id,
                false_block=merge_block.id,
                branch_type="if",
            ))
        
        self._current_block = merge_block
    
    def _process_while(self, node: ast.While) -> None:
        """Process while loop."""
        if not self._current_block:
            return
        
        # Header block (condition check)
        header = self._new_block("while_header")
        self._link(self._current_block, header)
        header.statements.append(node)
        
        # Body block
        body = self._new_block("while_body")
        exit_block = self._new_block("while_exit")
        
        self._link(header, body, "true")
        self._link(header, exit_block, "false")
        
        # Push loop context
        self._loop_stack.append((header.id, exit_block.id))
        
        # Process body
        self._current_block = body
        self._process_stmts(node.body)
        if self._current_block:
            self._link(self._current_block, header, "back")
        
        # Pop loop context
        self._loop_stack.pop()
        
        # Process else (runs if loop completes normally)
        if node.orelse:
            else_block = self._new_block("while_else")
            self._link(header, else_block, "else")
            self._current_block = else_block
            self._process_stmts(node.orelse)
            if self._current_block:
                self._link(self._current_block, exit_block)
        
        self.loops.append(LoopInfo(
            header_block=header.id,
            body_blocks={body.id},
            exit_block=exit_block.id,
            loop_type="while",
            iterator_line=node.lineno,
        ))
        
        self.branches.append(BranchInfo(
            block_id=header.id,
            condition_line=node.lineno,
            condition_code=ast.unparse(node.test) if hasattr(ast, 'unparse') else "",
            true_block=body.id,
            false_block=exit_block.id,
            branch_type="while",
        ))
        
        self._current_block = exit_block
    
    def _process_for(self, node: ast.For) -> None:
        """Process for loop."""
        if not self._current_block:
            return
        
        # Header block (iterator advance)
        header = self._new_block("for_header")
        self._link(self._current_block, header)
        header.statements.append(node)
        
        # Body block
        body = self._new_block("for_body")
        exit_block = self._new_block("for_exit")
        
        self._link(header, body, "next")
        self._link(header, exit_block, "exhausted")
        
        # Push loop context
        self._loop_stack.append((header.id, exit_block.id))
        
        # Process body
        self._current_block = body
        self._process_stmts(node.body)
        if self._current_block:
            self._link(self._current_block, header, "back")
        
        # Pop loop context
        self._loop_stack.pop()
        
        # Process else
        if node.orelse:
            else_block = self._new_block("for_else")
            self._link(header, else_block, "else")
            self._current_block = else_block
            self._process_stmts(node.orelse)
            if self._current_block:
                self._link(self._current_block, exit_block)
        
        self.loops.append(LoopInfo(
            header_block=header.id,
            body_blocks={body.id},
            exit_block=exit_block.id,
            loop_type="for",
            iterator_line=node.lineno,
        ))
        
        self._current_block = exit_block
    
    def _process_try(self, node: ast.Try) -> None:
        """Process try/except/finally."""
        if not self._current_block:
            return
        
        # Try block
        try_block = self._new_block("try")
        self._link(self._current_block, try_block)
        
        merge_block = self._new_block("try_merge")
        
        # Process try body
        self._current_block = try_block
        self._process_stmts(node.body)
        if self._current_block:
            self._link(self._current_block, merge_block)
        
        # Process except handlers
        handler_blocks = []
        for handler in node.handlers:
            handler_block = self._new_block("except")
            handler_blocks.append(handler_block.id)
            
            # Try block can jump to any handler
            self._link(try_block, handler_block, "exception")
            
            self._current_block = handler_block
            self._process_stmts(handler.body)
            if self._current_block:
                self._link(self._current_block, merge_block)
        
        # Process else (runs if no exception)
        if node.orelse:
            else_block = self._new_block("try_else")
            self._link(try_block, else_block, "no_exception")
            self._current_block = else_block
            self._process_stmts(node.orelse)
            if self._current_block:
                self._link(self._current_block, merge_block)
        
        # Process finally (always runs)
        if node.finalbody:
            finally_block = self._new_block("finally")
            # Everything merges through finally
            if merge_block.predecessors:
                self._link(merge_block, finally_block)
            
            self._current_block = finally_block
            self._process_stmts(node.finalbody)
            
            final_merge = self._new_block("finally_merge")
            if self._current_block:
                self._link(self._current_block, final_merge)
            self._current_block = final_merge
        else:
            self._current_block = merge_block
        
        self.try_blocks.append({
            "try_block": try_block.id,
            "handlers": handler_blocks,
            "line": node.lineno,
        })
    
    def _process_return(self, node: ast.Return) -> None:
        """Process return statement."""
        if not self._current_block:
            return
        self._current_block.statements.append(node)
        self._exit_blocks.add(self._current_block.id)
        self._current_block = None  # Unreachable after return
    
    def _process_raise(self, node: ast.Raise) -> None:
        """Process raise statement."""
        if not self._current_block:
            return
        self._current_block.statements.append(node)
        self._exit_blocks.add(self._current_block.id)
        self._current_block = None  # Unreachable after raise
    
    def _process_break(self, node: ast.Break) -> None:
        """Process break statement."""
        if not self._current_block or not self._loop_stack:
            return
        self._current_block.statements.append(node)
        _, exit_block = self._loop_stack[-1]
        self._link(self._current_block, self.blocks[exit_block], "break")
        self._current_block = None
    
    def _process_continue(self, node: ast.Continue) -> None:
        """Process continue statement."""
        if not self._current_block or not self._loop_stack:
            return
        self._current_block.statements.append(node)
        header_block, _ = self._loop_stack[-1]
        self._link(self._current_block, self.blocks[header_block], "continue")
        self._current_block = None
    
    def _process_with(self, node: ast.With) -> None:
        """Process with statement (simplified: treat as linear)."""
        if not self._current_block:
            return
        self._current_block.statements.append(node)
        self._process_stmts(node.body)
    
    def _process_match(self, node: ast.Match) -> None:
        """Process match statement (Python 3.10+)."""
        if not self._current_block:
            return
        
        match_block = self._current_block
        match_block.statements.append(node)
        
        merge_block = self._new_block("match_merge")
        
        for case in node.cases:
            case_block = self._new_block("match_case")
            self._link(match_block, case_block, "pattern")
            
            self._current_block = case_block
            self._process_stmts(case.body)
            if self._current_block:
                self._link(self._current_block, merge_block)
        
        self._current_block = merge_block


def build_cfg(
    source_code: str,
    function_name: str,
    file_path: str = "<string>",
) -> Optional[CFG]:
    """
    Build a CFG for a function in the given source code.
    
    Args:
        source_code: Python source code
        function_name: Name of the function to analyze
        file_path: Path to source file (for error messages)
    
    Returns:
        CFG for the function, or None if not found
    """
    try:
        tree = ast.parse(source_code)
    except SyntaxError:
        return None
    
    # Find the function
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == function_name:
                builder = CFGBuilder(function_name, file_path)
                return builder.build(node)
    
    return None


def build_cfg_for_file(file_path: str) -> Dict[str, CFG]:
    """
    Build CFGs for all functions in a file.
    
    Returns:
        Dict mapping function name → CFG
    """
    try:
        with open(file_path) as f:
            source = f.read()
        tree = ast.parse(source)
    except (OSError, SyntaxError):
        return {}
    
    cfgs = {}
    
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            builder = CFGBuilder(node.name, file_path)
            cfgs[node.name] = builder.build(node)
    
    return cfgs

