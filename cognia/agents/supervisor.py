"""
cognia/agents/supervisor.py — Phase 23

Supervisor: state machine síncrona para ejecutar tareas del agent runtime.
Sin asyncio, sin AgentBus. Llama funciones directamente.

Lifecycle:  CREATED → PLANNING → EXECUTING → VERIFYING → DONE | FAILED | ABORTED

Presupuesto por tarea:
  MAX_SUBTASK_RETRIES = 3
  MAX_TASK_RETRIES    = 2
  TIME_BUDGET_SECONDS = 300
  LOOP_DETECTOR: hash(subtask_id + attempt) previene bucles

Integración con cognia_idle.py:
  runtime = CogniaAgentRuntime()
  runtime.tick()   # llamar desde el daemon loop
"""

from __future__ import annotations

import hashlib
import time
from typing import Any, Dict, List, Optional, Set

from cognia.agents.planner import SubTask, plan_task
from cognia.agents.task_queue import (
    TaskQueue, TaskRecord,
    PLANNING, EXECUTING, VERIFYING, DONE, FAILED, ABORTED,
)
from cognia.agents.tool_registry import get_tool_registry
from cognia.agents.verifier import verify
from cognia.agents.synthesizer import synthesize

# ── Presupuestos ─────────────────────────────────────────────────────────────

MAX_SUBTASK_RETRIES  = 3
MAX_TASK_RETRIES     = 2
TIME_BUDGET_SECONDS  = 300
AGENTS_DB_PATH       = "cognia_agents.db"

# Tools que producen código Python (para que el Verifier sepa qué tipo es)
_CODE_TOOLS = {"execute_python", "validate_python"}


class CogniaAgentRuntime:
    """
    Punto de entrada del agent runtime. Llama tick() desde cognia_idle.py.

    Ejemplo:
        runtime = CogniaAgentRuntime()
        runtime.submit("analiza el archivo main.py")
        runtime.tick()   # procesa una tarea
    """

    def __init__(
        self,
        db_path: str = AGENTS_DB_PATH,
        episodic_memory=None,
        vector_cache=None,
        orchestrator=None,
    ) -> None:
        self._queue        = TaskQueue(db_path)
        self._episodic     = episodic_memory
        self._vcache       = vector_cache
        self._registry     = get_tool_registry()
        self._orchestrator = orchestrator

    def submit(self, description: str, priority: float = 0.0, deadline: float = None) -> str:
        """Encola una tarea. Retorna task_id."""
        return self._queue.submit(description, priority=priority, deadline=deadline)

    def tick(self) -> Optional[str]:
        """
        Procesa la tarea de mayor prioridad si hay alguna pendiente.
        Retorna task_id procesado o None si no había tareas.
        Diseñado para ser llamado desde el loop síncrono de cognia_idle.py.
        """
        task = self._queue.pop()
        if task is None:
            return None
        _Executor(
            task, self._queue, self._registry,
            self._episodic, self._vcache, self._orchestrator,
        ).run()
        return task.task_id

    def pending(self) -> int:
        return self._queue.pending_count()

    def status(self, task_id: str) -> Optional[TaskRecord]:
        return self._queue.get(task_id)


# ── Ejecutor de una sola tarea ────────────────────────────────────────────────

class _Executor:
    """Ejecuta una TaskRecord completa hasta DONE/FAILED/ABORTED."""

    def __init__(
        self,
        task: TaskRecord,
        queue: TaskQueue,
        registry,
        episodic_memory,
        vector_cache,
        orchestrator=None,
    ) -> None:
        self._task         = task
        self._queue        = queue
        self._registry     = registry
        self._episodic     = episodic_memory
        self._vcache       = vector_cache
        self._orchestrator = orchestrator
        self._seen_hashes: Set[str] = set()   # LOOP_DETECTOR
        self._results: Dict[str, Any] = {}    # subtask_id → output

    def run(self) -> None:
        """Ejecuta la tarea completa. NUNCA deja la tarea en estado no-terminal:
        cualquier excepción no controlada (plan_task, error de DB, tool inesperada)
        se captura y la tarea se marca FAILED en vez de quedar colgada en
        PLANNING/EXECUTING y propagar el error hasta el daemon/idle loop."""
        try:
            self._run()
        except Exception as exc:
            # El contrato del lifecycle exige un estado terminal. Sin esto, una
            # tarea quedaría EXECUTING para siempre (solo recuperable tras reinicio)
            # y la excepción tumbaría el tick() del daemon.
            try:
                self._queue.update_status(
                    self._task.task_id, FAILED,
                    result=f"EXECUTOR_ERROR:{type(exc).__name__}:{str(exc)[:200]}",
                )
            except Exception:
                pass

    def _run(self) -> None:
        t_start = time.monotonic()

        # ── 1. Planning ──────────────────────────────────────────────────────
        self._queue.update_status(self._task.task_id, PLANNING)
        subtasks = plan_task(
            self._task.description,
            task_id=self._task.task_id,
            episodic_memory=self._episodic,
        )
        self._queue.save_subtasks(subtasks)

        # ── 2. Executing ─────────────────────────────────────────────────────
        self._queue.update_status(self._task.task_id, EXECUTING)
        for subtask in subtasks:
            if subtask.tool_required == "synthesize":
                continue    # synthesis se hace al final, no como subtarea normal

            elapsed = time.monotonic() - t_start
            if elapsed > TIME_BUDGET_SECONDS:
                self._queue.update_status(self._task.task_id, ABORTED,
                                          result="TIME_BUDGET_EXCEEDED")
                return

            success = self._run_subtask(subtask)
            if not success:
                self._queue.update_status(self._task.task_id, FAILED,
                                          result=f"SUBTASK_FAILED:{subtask.id}")
                return

        # ── 3. Synthesis (el único LLM call del path normal) ─────────────────
        self._queue.update_status(self._task.task_id, VERIFYING)
        final = self._synthesize(subtasks)

        self._queue.update_status(self._task.task_id, DONE, result=final)

    def _run_subtask(self, subtask: SubTask) -> bool:
        """
        Ejecuta una subtarea con retry.
        Retorna True si pasa la verificación, False si supera MAX_SUBTASK_RETRIES.
        """
        for attempt in range(MAX_SUBTASK_RETRIES):
            # LOOP_DETECTOR
            loop_key = hashlib.md5(
                f"{subtask.id}:{attempt}".encode()
            ).hexdigest()
            if loop_key in self._seen_hashes:
                self._queue.update_subtask(subtask.id, "failed",
                                           result="LOOP_DETECTED")
                return False
            self._seen_hashes.add(loop_key)

            # Ejecutar tool
            self._queue.update_subtask(subtask.id, "running")
            tool_result = self._registry.execute(
                subtask.tool_required,
                **self._build_kwargs(subtask),
            )

            output = tool_result.output if tool_result.success else tool_result.error
            output_type = "code" if subtask.tool_required in _CODE_TOOLS else "text"

            # Verificar
            vr = verify(output, output_type=output_type, vector_cache=self._vcache)

            if vr.passed:
                self._results[subtask.id] = output
                self._queue.update_subtask(subtask.id, "done",
                                           result=str(output)[:2000])
                return True

            # Falló — preparar retry
            self._queue.update_subtask(subtask.id, "retrying",
                                       result=f"ATTEMPT_{attempt}:{vr.fail_reason}")

        # Agotados los intentos
        self._queue.update_subtask(subtask.id, "failed",
                                   result=f"MAX_RETRIES:{vr.fail_reason}")
        return False

    def _build_kwargs(self, subtask: SubTask) -> dict:
        """Construye kwargs para la tool a partir de la descripción de la subtarea y resultados previos."""
        tool = subtask.tool_required

        if tool in ("execute_python", "validate_python"):
            # Extrae código de resultados de subtareas anteriores si existen
            for dep_id in subtask.dependencies:
                dep_result = self._results.get(dep_id)
                if dep_result and isinstance(dep_result, dict):
                    code = dep_result.get("output", "")
                    if code:
                        return {"code": str(code)}
            # Fallback: la descripción es el código
            return {"code": subtask.description}

        if tool == "search_wikipedia":
            # Extraer el tema de la descripción (después de ":")
            parts = subtask.description.split(":", 1)
            query = parts[1].strip() if len(parts) > 1 else subtask.description
            return {"query": query}

        if tool == "research_llm":
            parts = subtask.description.split(":", 1)
            question = parts[1].strip() if len(parts) > 1 else subtask.description
            return {"question": question}

        if tool == "file_explorer":
            # Phase 24 implementará FileExplorer; por ahora retorna dict vacío
            parts = subtask.description.split(":", 1)
            path = parts[1].strip() if len(parts) > 1 else "."
            return {"path": path}

        if tool == "query_episodic":
            parts = subtask.description.split(":", 1)
            query = parts[1].strip() if len(parts) > 1 else subtask.description
            return {"query": query}

        return {}

    def _synthesize(self, subtasks: List[SubTask]) -> str:
        return synthesize(
            task_description=self._task.description,
            subtasks=subtasks,
            results=self._results,
            orchestrator=self._orchestrator,
        )
