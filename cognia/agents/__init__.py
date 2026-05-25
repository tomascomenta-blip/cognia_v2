"""
cognia/agents — Agent runtime package (Phase 22+)

Phase 22: Tool Registry + SymbolicPlanner        DONE 2026-05-24
Phase 23: Supervisor + TaskQueue + Verifier       DONE 2026-05-24
Phase 24: Workers deterministas + Synthesizer     DONE 2026-05-24
Phase 25: Autonomous Daemon                       DONE 2026-05-24
Phase 26: Safe Self-Improvement                   DONE 2026-05-24
"""

from cognia.agents.tool_registry import Tool, ToolResult, ToolRegistry, get_tool_registry
from cognia.agents.planner import SubTask, plan_task, classify_task, TASK_TEMPLATES
from cognia.agents.task_queue import TaskQueue, TaskRecord
from cognia.agents.verifier import verify, VerifyResult
from cognia.agents.supervisor import CogniaAgentRuntime
from cognia.agents.daemon import AgentDaemon, get_fatigue_score
from cognia.agents.self_improvement import (
    TunableParams, BenchmarkMetrics, Benchmark,
    SandboxedExperiment, SafeImprover, ImprovementResult,
)

__all__ = [
    "Tool", "ToolResult", "ToolRegistry", "get_tool_registry",
    "SubTask", "plan_task", "classify_task", "TASK_TEMPLATES",
    "TaskQueue", "TaskRecord",
    "verify", "VerifyResult",
    "CogniaAgentRuntime",
    "AgentDaemon", "get_fatigue_score",
    "TunableParams", "BenchmarkMetrics", "Benchmark",
    "SandboxedExperiment", "SafeImprover", "ImprovementResult",
]
