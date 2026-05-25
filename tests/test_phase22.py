"""
tests/test_phase22.py — Phase 22: Tool Registry + SymbolicPlanner
"""

import pytest
from cognia.agents.tool_registry import ToolRegistry, Tool, ToolResult, get_tool_registry
from cognia.agents.planner import (
    SubTask, classify_task, plan_task, TASK_TEMPLATES, _build_from_template,
)


# ── ToolRegistry ─────────────────────────────────────────────────────────────

class TestToolRegistry:
    def test_register_and_execute(self):
        reg = ToolRegistry()
        reg.register(Tool(
            name="add",
            description="Add two numbers",
            fn=lambda x, y: x + y,
        ))
        result = reg.execute("add", x=2, y=3)
        assert result.success is True
        assert result.output == 5
        assert result.error == ""

    def test_unknown_tool_returns_failure(self):
        reg = ToolRegistry()
        result = reg.execute("nonexistent")
        assert result.success is False
        assert "Unknown tool" in result.error

    def test_exception_in_fn_returns_failure(self):
        reg = ToolRegistry()
        def boom():
            raise ValueError("intentional error")
        reg.register(Tool(name="boom", description="", fn=boom))
        result = reg.execute("boom")
        assert result.success is False
        assert "intentional error" in result.error

    def test_duration_ms_is_positive(self):
        reg = ToolRegistry()
        reg.register(Tool(name="noop", description="", fn=lambda: None))
        result = reg.execute("noop")
        assert result.duration_ms >= 0.0

    def test_names_returns_registered(self):
        reg = ToolRegistry()
        reg.register(Tool(name="a", description="", fn=lambda: None))
        reg.register(Tool(name="b", description="", fn=lambda: None))
        assert set(reg.names()) == {"a", "b"}

    def test_singleton_has_real_tools(self):
        reg = get_tool_registry()
        # Al menos validate_python y execute_python deben registrarse
        assert "validate_python" in reg.names()
        assert "execute_python" in reg.names()

    def test_validate_python_blocks_dangerous_import(self):
        reg = get_tool_registry()
        result = reg.execute("validate_python", code="import subprocess\nprint('hi')")
        assert result.success is True          # la herramienta corrió OK
        r = result.output
        assert r["valid"] is False or len(r["errors"]) > 0  # el código es inválido

    def test_execute_python_runs_safe_code(self):
        reg = get_tool_registry()
        result = reg.execute("execute_python", code="print('hello')")
        assert result.success is True
        assert "hello" in result.output["output"]

    def test_execute_python_blocked_import(self):
        reg = get_tool_registry()
        result = reg.execute("execute_python", code="import subprocess")
        assert result.success is True          # herramienta corrió
        assert result.output["success"] is False  # ejecución rechazada


# ── SymbolicPlanner ──────────────────────────────────────────────────────────

class TestClassifyTask:
    def test_classify_code_task(self):
        assert classify_task("analiza el archivo main.py") == "analyze_file"

    def test_classify_run_code(self):
        assert classify_task("ejecuta este script de Python") == "run_code"

    def test_classify_research(self):
        assert classify_task("investiga qué es el teorema de Bayes") == "research_topic"

    def test_classify_find_bugs(self):
        assert classify_task("hay un bug en la función login") == "find_bugs"

    def test_classify_explain(self):
        assert classify_task("como funciona el garbage collector") == "explain_concept"

    def test_unclassifiable_returns_none(self):
        assert classify_task("xyzzy foobar qux") is None

    def test_empty_string_returns_none(self):
        assert classify_task("") is None


class TestPlanTask:
    def test_returns_list_of_subtasks(self):
        plan = plan_task("analiza el archivo foo.py", task_id="t1")
        assert isinstance(plan, list)
        assert len(plan) > 0
        assert all(isinstance(s, SubTask) for s in plan)

    def test_subtask_ids_contain_task_id(self):
        plan = plan_task("busca el bug en login.py", task_id="t42")
        for s in plan:
            assert s.id.startswith("t42_")

    def test_dependencies_form_chain(self):
        plan = plan_task("ejecuta el script test.py", task_id="t1")
        for i, s in enumerate(plan[1:], 1):
            assert plan[i - 1].id in s.dependencies

    def test_last_step_is_synthesize(self):
        for task_type in TASK_TEMPLATES:
            steps = TASK_TEMPLATES[task_type]
            assert steps[-1][2] == "synthesize"

    def test_no_circular_dependencies(self):
        plan = plan_task("analiza y ejecuta el código de app.py", task_id="t99")
        ids = {s.id for s in plan}
        for s in plan:
            for dep in s.dependencies:
                assert dep in ids
                assert dep != s.id

    def test_generic_fallback_for_unknown_task(self):
        plan = plan_task("xyzzy foobar abstract quantum bloop", task_id="unk")
        assert len(plan) == 2
        assert plan[0].tool_required == "research_llm"
        assert plan[1].tool_required == "synthesize"

    def test_episodic_memory_miss_uses_template(self):
        class FakeMemory:
            def search(self, q, top_k=1):
                return []
        plan = plan_task("investiga Python async", task_id="t2", episodic_memory=FakeMemory())
        assert any(s.tool_required == "search_wikipedia" for s in plan)

    def test_episodic_memory_hit_reuses_plan(self):
        class FakeEpisode:
            similarity = 0.95
            metadata = {"agent_plan": [
                {"description": "step A", "tool_required": "execute_python"},
                {"description": "step B", "tool_required": "synthesize"},
            ]}
        class FakeMemory:
            def search(self, q, top_k=1):
                return [FakeEpisode()]
        plan = plan_task("cualquier tarea", task_id="cached", episodic_memory=FakeMemory())
        assert len(plan) == 2
        assert plan[0].tool_required == "execute_python"

    def test_episodic_memory_low_similarity_ignores_cache(self):
        class FakeEpisode:
            similarity = 0.50
            metadata = {"agent_plan": [{"description": "x", "tool_required": "synthesize"}]}
        class FakeMemory:
            def search(self, q, top_k=1):
                return [FakeEpisode()]
        plan = plan_task("busca el bug en auth.py", task_id="t3", episodic_memory=FakeMemory())
        # Debe usar template, no el plan cacheado con sim baja
        assert len(plan) > 1
        assert plan[0].tool_required != "synthesize"
