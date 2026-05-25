"""
cognia/agents/tool_registry.py — Phase 22

Registro centralizado de herramientas para el agent runtime.
Cada Tool es un wrapper sobre funciones existentes (code_executor, investigador,
researcher). El registro es un singleton por proceso.

Seguridad heredada: code_executor mantiene AST validation + BLOCKED_IMPORTS.
El registry no bypassea ninguna de esas guardas.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional


@dataclass
class ToolResult:
    success:     bool
    output:      Any
    error:       str
    duration_ms: float


@dataclass
class Tool:
    name:             str
    description:      str      # inyectado en system prompt del agente que lo usa
    fn:               Callable
    timeout_seconds:  int  = 30
    requires_network: bool = False


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def execute(self, name: str, **kwargs) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(False, None, f"Unknown tool: {name}", 0.0)
        t0 = time.monotonic()
        try:
            output = tool.fn(**kwargs)
            return ToolResult(True, output, "", (time.monotonic() - t0) * 1000)
        except Exception as exc:
            return ToolResult(False, None, str(exc), (time.monotonic() - t0) * 1000)

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def __len__(self) -> int:
        return len(self._tools)


def _make_registry() -> ToolRegistry:
    reg = ToolRegistry()

    # ── execute_python ──────────────────────────────────────────────────
    try:
        from code_executor import get_code_executor
        _exec = get_code_executor()

        def _execute_python(code: str) -> dict:
            r = _exec.run(code, language="python")
            return {"success": r.success, "output": r.output, "errors": r.errors,
                    "timed_out": r.timed_out}

        reg.register(Tool(
            name="execute_python",
            description="Execute Python code in a sandboxed subprocess. Returns output and errors.",
            fn=_execute_python,
            timeout_seconds=15,
            requires_network=False,
        ))
    except ImportError:
        pass

    # ── validate_python ─────────────────────────────────────────────────
    try:
        from code_executor import validate_python

        def _validate_python(code: str) -> dict:
            r = validate_python(code)
            return {"valid": r.valid, "errors": r.errors, "warnings": r.warnings}

        reg.register(Tool(
            name="validate_python",
            description="Validate Python syntax and check for blocked imports without executing.",
            fn=_validate_python,
            timeout_seconds=5,
            requires_network=False,
        ))
    except ImportError:
        pass

    # ── search_wikipedia ────────────────────────────────────────────────
    try:
        from investigador import buscar_wikipedia

        def _search_wikipedia(query: str) -> dict:
            result = buscar_wikipedia(query)
            if result is None:
                return {"found": False, "title": "", "extract": ""}
            return {
                "found": True,
                "title": result.get("title", ""),
                "extract": result.get("extract", ""),
            }

        reg.register(Tool(
            name="search_wikipedia",
            description="Search Wikipedia for a topic. Returns title and plain-text extract.",
            fn=_search_wikipedia,
            timeout_seconds=15,
            requires_network=True,
        ))
    except ImportError:
        pass

    # ── research_llm ────────────────────────────────────────────────────
    try:
        from cognia.research_engine.researcher import research_question

        def _research_llm(
            question: str,
            topic: str = "",
            question_type: str = "uncertainty",
        ) -> dict:
            proposal = {
                "id": 0,
                "question": question,
                "topic": topic,
                "question_type": question_type,
            }
            r = research_question(proposal)
            if r is None:
                return {"success": False, "answer": "", "key_concepts": [], "relations": []}
            return {
                "success": r.success,
                "answer": r.answer,
                "key_concepts": r.key_concepts,
                "relations": r.relations,
            }

        reg.register(Tool(
            name="research_llm",
            description=(
                "Research a question using the local LLM. "
                "Use only when Wikipedia and episodic memory are insufficient."
            ),
            fn=_research_llm,
            timeout_seconds=60,
            requires_network=False,
        ))
    except ImportError:
        pass

    # ── file_explorer ───────────────────────────────────────────────────
    try:
        from cognia.agents.workers.file_explorer import explore, index_to_dict

        def _file_explorer(path: str = ".") -> dict:
            return index_to_dict(explore(path))

        reg.register(Tool(
            name="file_explorer",
            description="Explore a file or directory: returns structure, Python symbols, imports.",
            fn=_file_explorer,
            timeout_seconds=30,
            requires_network=False,
        ))
    except ImportError:
        pass

    # ── research (con cache episódico) ──────────────────────────────────
    try:
        from cognia.agents.workers.research_worker import research

        def _research(query: str) -> dict:
            return research(query)

        reg.register(Tool(
            name="research",
            description="Research a topic: episodic cache → Wikipedia → LLM fallback.",
            fn=_research,
            timeout_seconds=30,
            requires_network=True,
        ))
    except ImportError:
        pass

    # ── query_episodic ──────────────────────────────────────────────────
    # Búsqueda directa en memoria episódica sin Wikipedia ni LLM
    reg.register(Tool(
        name="query_episodic",
        description="Query episodic memory for related knowledge (no network, no LLM).",
        fn=lambda query="": {"source": "episodic_stub", "content": "", "found": False},
        timeout_seconds=5,
        requires_network=False,
    ))

    return reg


_registry: Optional[ToolRegistry] = None


def get_tool_registry() -> ToolRegistry:
    global _registry
    if _registry is None:
        _registry = _make_registry()
    return _registry
