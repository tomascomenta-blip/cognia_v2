"""
cognia_v3/training/tooluse
==========================
Genera datos SFT para enseñarle a Qwen a usar las herramientas de Cognia en el
formato REAL del agent loop (cli.py:_run_agent_task): el modelo emite líneas
``ACCION: <tool> <args>`` y consume observaciones ``RESULTADO ...``.

Método (fiel a CLAUDE.md — "código que corre o no cuenta"):
  1. Banco de tareas con VERIFICADOR por ejecución (postcondición determinista).
  2. Un modelo maestro resuelve cada tarea corriendo el loop ReAct contra las
     herramientas REALES (cognia/agent/tools.py) en un workspace aislado.
  3. Se quedan SOLO las trayectorias cuya postcondición pasa -> rechazo
     automático de basura. Cada paso (prompt, completion) es un par SFT.
  4. Salida JSONL {prompt, completion} lista para el QLoRA trainer del repo.
"""
