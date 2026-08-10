"""
Tests del outer loop de horizonte (cognia/agent/horizonte.py) SIN GPU.

El parametro ``bucle=`` inyecta un fake guionado con la MISMA firma que
bucle_nativo: cada "ciclo" del guion puede crear archivos (para que el
GoalContract real los selle), apendear RESULTADO al history y devolver el
dict {"texto","pasos","ok","tokens","finish"} que el outer loop clasifica.
"""

import pytest

from cognia.agent import estado_tarea as et
from cognia.agent.horizonte import ciclos_con_contrato, max_ciclos_env


@pytest.fixture
def tareas_tmp(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIA_TAREAS_DIR", str(tmp_path / "estado"))
    return tmp_path


def _criterios(*paths):
    return [{"kind": "file_exists", "path": str(p),
             "description": f"debe existir {p}"} for p in paths]


class BucleFake:
    """Guion por ciclo: lista de dicts {crea: [paths], nat: {...}}."""

    def __init__(self, guion):
        self.guion = list(guion)
        self.llamadas = []          # (history_snapshot, max_turns)

    def __call__(self, task, system, completar, schemas, args_legacy,
                 mensaje_assistant, mensaje_tool, run_tool, ctx, perfil,
                 history, trace, print_fn, max_turns):
        paso = self.guion[len(self.llamadas)]
        self.llamadas.append((list(history), max_turns))
        for p in paso.get("crea", []):
            p.write_text("x\n", encoding="utf-8")
            history.append(f"RESULTADO escribir_archivo: OK escrito {p}")
            trace.append({"action": "escribir_archivo", "args": f"{p} | x",
                          "ok": True,
                          "result_head": f"RESULTADO escribir_archivo: {p}"})
        nat = {"texto": "cerrado", "pasos": 3, "ok": True, "tokens": 50,
               "finish": "stop"}
        nat.update(paso.get("nat", {}))
        return nat


def _correr(fake, criterios, tarea="tarea", max_ciclos=2):
    estado = et.nuevo("20260809-120000-test", tarea, criterios)
    history = [f"TAREA: {tarea}"]
    trace = []
    out = ciclos_con_contrato(
        tarea, "system", None, [], None, None, None, None, {}, {},
        history, trace, lambda *_: None, 8,
        criterios=criterios, task_id="20260809-120000-test", estado=estado,
        max_ciclos=max_ciclos, bucle=fake)
    return out, estado, history, trace


def test_relevo_completa_lo_que_falta(tareas_tmp):
    a, b = tareas_tmp / "a.py", tareas_tmp / "b.py"
    fake = BucleFake([
        {"crea": [a], "nat": {"finish": "stop"}},    # ciclo 1: 1 de 2
        {"crea": [b]},                                # ciclo 2: completa
    ])
    out, estado, history, trace = _correr(fake, _criterios(a, b))
    assert out["contrato_ok"] is True
    assert out["ciclos"] == 2
    # El history del ciclo 2 es FRESCO: [objetivo, delta CONTINUACION].
    h2, _ = fake.llamadas[1]
    assert h2[0].startswith("TAREA:")
    assert "CONTINUACION" in h2[1] and "SOLO FALTA" in h2[1]
    # Las lineas de faltan se capan a 100 chars (la ruta tmp es larga):
    # se chequea por basename dentro de la seccion SOLO FALTA.
    _solo_falta = h2[1].split("SOLO FALTA")[1]
    assert "b.py" in _solo_falta
    assert "a.py" not in _solo_falta
    # Los RESULTADO del ciclo 2 volvieron al history real (post-procesado).
    assert any(str(b) in h for h in history if h.startswith("RESULTADO"))
    # pasos/tokens agregados entre ciclos
    assert out["pasos"] == 6 and out["tokens"] == 100


def test_contrato_completo_en_ciclo_1_no_releva(tareas_tmp):
    a = tareas_tmp / "solo.py"
    fake = BucleFake([{"crea": [a]}, {"crea": []}])
    out, _, _, _ = _correr(fake, _criterios(a))
    assert out["contrato_ok"] is True and out["ciclos"] == 1
    assert len(fake.llamadas) == 1


def test_sin_criterios_un_solo_ciclo(tareas_tmp):
    fake = BucleFake([{}, {}])
    out, estado, _, _ = _correr(fake, [])
    assert out["contrato_ok"] is None and out["ciclos"] == 1
    assert len(fake.llamadas) == 1
    assert len(estado["ciclos"]) == 1        # el ciclo igual quedo registrado


def test_infra_caida_no_releva(tareas_tmp):
    a = tareas_tmp / "nunca.py"
    fake = BucleFake([
        {"nat": {"texto": "(el agente no pudo hablar con el modelo: x)",
                 "ok": False, "finish": ""}},
        {"crea": [a]},
    ])
    out, _, _, _ = _correr(fake, _criterios(a))
    assert out["contrato_ok"] is False and out["ciclos"] == 1
    assert len(fake.llamadas) == 1


def test_progreso_monotono_corta(tareas_tmp):
    a, b = tareas_tmp / "a.py", tareas_tmp / "b.py"
    fake = BucleFake([
        {"crea": [a]},                # ciclo 1: 1/2
        {"crea": []},                 # ciclo 2: sigue 1/2 -> sin progreso
        {"crea": [b]},                # ciclo 3: NO debe llegar
    ])
    out, _, _, _ = _correr(fake, _criterios(a, b), max_ciclos=3)
    assert out["ciclos"] == 2 and out["contrato_ok"] is False
    assert len(fake.llamadas) == 2


def test_estancamiento_si_releva_con_contexto_fresco(tareas_tmp):
    # El contexto fresco es la CURA del estancamiento: un ciclo interrumpido
    # por tool repetida debe relevar (si hay progreso posible), no cortar.
    a, b = tareas_tmp / "a.py", tareas_tmp / "b.py"
    fake = BucleFake([
        {"crea": [a], "nat": {"texto": "(interrumpida por estancamiento: x)",
                              "ok": False, "finish": ""}},
        {"crea": [b]},
    ])
    out, estado, _, _ = _correr(fake, _criterios(a, b))
    assert out["contrato_ok"] is True and out["ciclos"] == 2
    assert estado["ciclos"][1]["motivo_relevo"] == "estancamiento"


def test_criterios_congelados_anti_a6(tareas_tmp):
    # Aunque el ciclo 1 devuelva basura harmony en los resultados, los
    # criterios del sello del ciclo 2 son EL MISMO objeto congelado.
    a, b = tareas_tmp / "a.py", tareas_tmp / "b.py"
    criterios = _criterios(a, b)
    congelados = [dict(c) for c in criterios]
    fake = BucleFake([
        {"crea": [a], "nat": {"texto": "<|channel|>analysis basura<|end|>"}},
        {"crea": [b]},
    ])
    out, estado, _, _ = _correr(fake, criterios)
    assert out["contrato_ok"] is True
    assert criterios == congelados            # nadie muto los specs
    assert estado["criterios"] == congelados


def test_shape_de_retorno(tareas_tmp):
    a = tareas_tmp / "s.py"
    fake = BucleFake([{"crea": [a]}])
    out, _, _, _ = _correr(fake, _criterios(a))
    for clave in ("texto", "pasos", "ok", "tokens", "finish",
                  "ciclos", "contrato_ok", "task_id"):
        assert clave in out
    assert out["task_id"] == "20260809-120000-test"


def test_max_ciclos_env(monkeypatch):
    monkeypatch.delenv("COGNIA_HORIZONTE_CICLOS", raising=False)
    assert max_ciclos_env() == 0
    monkeypatch.setenv("COGNIA_HORIZONTE_CICLOS", "2")
    assert max_ciclos_env() == 2
    monkeypatch.setenv("COGNIA_HORIZONTE_CICLOS", "9")
    assert max_ciclos_env() == 3              # techo duro
    monkeypatch.setenv("COGNIA_HORIZONTE_CICLOS", "rara")
    assert max_ciclos_env() == 0


def test_tools_de_horizonte_degradan_sin_ctx(tareas_tmp, monkeypatch):
    from cognia.agent.tools import run_tool
    out = run_tool("tarea_estado", "", {})
    assert "ERROR" in out and "COGNIA_HORIZONTE" in out
    out = run_tool("bitacora_buscar", "patron", {})
    assert "ERROR" in out and "COGNIA_HORIZONTE" in out


def test_trace_fresco_por_ciclo(tareas_tmp):
    # bucle_nativo corta por no-progreso mirando trace[-3:]: los fallos del
    # ciclo anterior NO deben contar contra el ciclo fresco (revision
    # 2026-08-09). El fake registra el largo del trace recibido por ciclo.
    a, b = tareas_tmp / "a.py", tareas_tmp / "b.py"
    largos = []

    class BucleConFallos(BucleFake):
        def __call__(self, task, system, completar, schemas, args_legacy,
                     mensaje_assistant, mensaje_tool, run_tool, ctx, perfil,
                     history, trace, print_fn, max_turns):
            largos.append(len(trace))
            if not self.llamadas:       # ciclo 1: crea a + deja 3 fallos
                for _ in range(3):
                    trace.append({"action": "ejecutar", "args": "x",
                                  "ok": False, "result_head": "ERROR"})
            return super().__call__(
                task, system, completar, schemas, args_legacy,
                mensaje_assistant, mensaje_tool, run_tool, ctx, perfil,
                history, trace, print_fn, max_turns)

    fake = BucleConFallos([
        {"crea": [a], "nat": {"finish": "stop"}},
        {"crea": [b]},
    ])
    out, _, _, trace = _correr(fake, _criterios(a, b))
    assert out["contrato_ok"] is True and out["ciclos"] == 2
    assert largos[1] == 0                  # el ciclo 2 arranco con trace VACIO
    # y el trace real acumulo lo de ambos ciclos para el post-procesado
    assert sum(1 for t in trace if not t["ok"]) == 3
    assert any(str(b) in t["args"] for t in trace)


def test_bitacora_buscar_patron_con_pipe(tareas_tmp, monkeypatch):
    # El patron es un regex: 'error|fallo' NO debe partirse por el separador
    # legacy (revision 2026-08-09: se buscaba solo 'error' en silencio).
    from cognia.agent import bitacora
    from cognia.agent.tool_schemas import args_legacy
    from cognia.agent.tools import run_tool
    monkeypatch.setenv("COGNIA_TAREAS_DIR", str(tareas_tmp / "estado"))
    tid = bitacora.iniciar("t", {})
    try:
        from cognia.ux import events as ev
        ev.emitir(ev.ToolFin(tool="ejecutar", args="x", ok=False,
                             resumen="hubo un fallo feo", paso=1))
        ev.emitir(ev.ToolFin(tool="leer_archivo", args="y", ok=True,
                             resumen="42 lineas", paso=2))
        ctx = {"_horizonte_task_id": tid}
        out = run_tool("bitacora_buscar", "fallo|leer_archivo", ctx)
        assert "fallo feo" in out and "leer_archivo" in out
        # el armador nativo pone n ADELANTE y el patron (con '|') ULTIMO
        assert args_legacy("bitacora_buscar",
                           {"patron": "a|b", "n": 5}) == "5 | a|b"
        out = run_tool("bitacora_buscar", "1 | fallo|leer_archivo", ctx)
        assert out.count("\n") == 1        # cabecera + 1 sola coincidencia
    finally:
        bitacora.cerrar()


def test_tools_de_horizonte_con_estado(tareas_tmp, monkeypatch):
    from cognia.agent import bitacora
    from cognia.agent.tools import run_tool
    monkeypatch.setenv("COGNIA_TAREAS_DIR", str(tareas_tmp / "estado"))
    tid = bitacora.iniciar("tarea con estado", {})
    try:
        est = et.nuevo(tid, "tarea con estado", _criterios("x.py"))
        ctx = {"_horizonte_task_id": tid}
        out = run_tool("tarea_estado", "", ctx)
        assert "tarea con estado" in out and "[--]" in out
        from cognia.ux import events as ev
        ev.emitir(ev.ToolFin(tool="ejecutar", args="ls", ok=True,
                             resumen="listado", paso=1))
        out = run_tool("bitacora_buscar", "ejecutar", ctx)
        assert "ejecutar" in out and "listado" in out
    finally:
        bitacora.cerrar()
