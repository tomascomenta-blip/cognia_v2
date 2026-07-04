"""
Regresion de los wires del loop /hacer (_run_agent_task en cognia/cli.py):
- repair dirigido tras un error de EJECUCION real (palanca #4);
- monitor GoalContract: verifica criterios REALES de la tarea al cierre;
- record_skill_use: registra si la skill aplicada llevo a exito.

Fake orch guionado (sin modelo). Patron tomado de test_agent_no_backend.py.
"""
import types

import cognia.cli as cli


class _R:
    def __init__(self, text): self.text = text


class _ScriptedOrch:
    """Devuelve textos en orden; el primero (rating de budget) fijo a '1'
    para un presupuesto chico y determinista. Ignora kwargs."""
    def __init__(self, steps):
        self._steps = list(steps)
        self.calls = 0

    def infer(self, prompt, *a, **k):
        self.calls += 1
        if not self._steps:
            return _R("ACCION: responder listo")
        return _R(self._steps.pop(0))


class _FakeAI:
    _orchestrator = None
    def observe(self, *a, **k): pass


def _run(steps, task, tmp_path, monkeypatch):
    ai = _FakeAI(); ai._orchestrator = _ScriptedOrch(["1"] + steps)
    monkeypatch.setattr(cli.Path, "home", lambda: tmp_path)
    out = []
    result = cli._run_agent_task(ai, task, out.append, max_steps=6)
    return result, "\n".join(out)


def test_repair_dirigido_tras_error_de_ejecucion(tmp_path, monkeypatch):
    # El agente corre py_validar sobre un .py con sintaxis rota -> el loop debe
    # inyectar el hint de repair dirigido (clasificado 'syntax').
    bad = tmp_path / "roto.py"
    bad.write_text("def f(:\n    pass\n", encoding="utf-8")
    steps = [
        f"ACCION: py_validar {bad}",
        "ACCION: responder listo",
    ]
    result, log = _run(steps, "revisa roto.py", tmp_path, monkeypatch)
    assert "repair dirigido" in log.lower()


def test_monitor_goalcontract_detecta_archivo_faltante(tmp_path, monkeypatch):
    # La tarea promete crear salida.txt pero el agente NO lo crea -> el monitor
    # debe declarar el objetivo NO verificado (anti alucinacion de progreso).
    faltante = (tmp_path / "salida.txt").as_posix()
    steps = ["ACCION: responder ya esta hecho (mentira)"]
    result, log = _run(steps, f"crea el archivo {faltante} con un resumen",
                       tmp_path, monkeypatch)
    assert "no verificado" in log.lower()


def test_monitor_goalcontract_confirma_archivo_creado(tmp_path, monkeypatch):
    # La tarea pide crear salida.txt y el agente lo crea via escribir_archivo
    # (dentro del workspace) -> objetivo verificado.
    import cognia.agents.workers.dev_tools as dv
    monkeypatch.setattr(dv, "AGENT_WORKSPACE_ROOT", str(tmp_path))
    target = (tmp_path / "salida.txt").as_posix()
    steps = [
        f"ACCION: escribir_archivo {target} | contenido real",
        "ACCION: responder listo",
    ]
    result, log = _run(steps, f"crea el archivo {target} con contenido",
                       tmp_path, monkeypatch)
    assert "objetivo verificado" in log.lower()
