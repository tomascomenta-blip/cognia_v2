# -*- coding: utf-8 -*-
"""
Regresion (2026-08-24): una tool colgada congelaba el turno sin senal y el
proceso que lanzo seguia vivo ('matar el shell no mata el proceso'). Estos
tests fijan el contrato de `cognia/harness/timeout_tool.py` (timeout-policy
de deepseek-harness): precedencia del deadline (spec > global, 0 = sin
limite, el interno de ejecutar/tests manda, las tools LLM sin deadline), el
resultado TIPADO (TOOL_TIMEOUT) que baja por el pipeline normal de run_tool
sin excepcion, la quiescencia (el hijo registrado muere DE VERDAD) y la
config invalida que grita.

Sin el modulo, el fichero entero falla en el import.
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time

import pytest

from cognia.harness import timeout_tool as tt


@pytest.fixture(autouse=True)
def aislado(monkeypatch):
    monkeypatch.delenv(tt.ENV_TIMEOUT, raising=False)
    monkeypatch.delenv(tt.ENV_GRACIA, raising=False)
    monkeypatch.setattr(tt, "_AVISADOR", None)
    tt._ULTIMO.clear()
    tt._ULTIMO_ERROR.clear()
    tt._TOTAL[0] = 0
    from cognia.agent import tools as T
    T._TIMEOUT_AVISADO.clear()


def _ctx():
    return {"working_memory": {}, "agent_state": {},
            "print_fn": lambda *a, **k: None}


def _spec(fn, **extra):
    s = {"fn": fn, "doc": "p", "danger": False, "desc": "", "params": [],
         "timeout_s": None, "timeout_interno": None}
    s.update(extra)
    return s


# ── Precedencia ──────────────────────────────────────────────────────────────

def test_default_global_120_y_env_lo_mueve(monkeypatch):
    assert tt.timeout_efectivo("x", _spec(None), "") == 120
    monkeypatch.setenv(tt.ENV_TIMEOUT, "7")
    assert tt.timeout_efectivo("x", _spec(None), "") == 7
    monkeypatch.setenv(tt.ENV_TIMEOUT, "0")
    assert tt.timeout_efectivo("x", _spec(None), "") == 0


def test_spec_manda_sobre_el_global(monkeypatch):
    monkeypatch.setenv(tt.ENV_TIMEOUT, "7")
    assert tt.timeout_efectivo("x", _spec(None, timeout_s=30), "") == 30
    assert tt.timeout_efectivo("x", _spec(None, timeout_s=0), "") == 0


def test_tools_que_llaman_al_modelo_sin_deadline():
    assert tt.timeout_efectivo("delegar_subtarea", _spec(None), "") == 0
    assert tt.timeout_efectivo("rlm_llamar", _spec(None), "") == 0


def test_el_interno_de_ejecutar_manda_sobre_el_externo(monkeypatch):
    """`ejecutar ... | timeout=300` con global 120: el externo se estira a
    305 y NUNCA corta antes que el subprocess."""
    from cognia.agent.tools import TOOLS
    spec = TOOLS["ejecutar"]
    assert callable(spec.get("timeout_interno"))
    assert tt.timeout_efectivo("ejecutar", spec, "sleep 1 | timeout=300") == 305
    # con interno chico, el global (mayor) se queda
    assert tt.timeout_efectivo("ejecutar", spec, "echo hola") == 120
    assert tt.timeout_efectivo("tests", TOOLS["tests"], "tests/x.py") == 185


@pytest.mark.parametrize("basura", ["abc", "-5"])
def test_global_invalido_lanza_al_cargar(basura, monkeypatch):
    monkeypatch.setenv(tt.ENV_TIMEOUT, basura)
    with pytest.raises(tt.ConfigInvalida):
        tt.timeout_global()
    with pytest.raises(tt.ConfigInvalida):
        tt.timeout_efectivo("x", _spec(None), "")
    assert tt.estado()["config_error"]


# ── El ejecutor ──────────────────────────────────────────────────────────────

def test_vuelve_a_tiempo_y_limpia_el_ctx():
    ctx = _ctx()
    out, agotada, info = tt.correr_con_deadline(
        lambda a, c: f"ok {a}", "t", "arg", ctx, 5)
    assert out == "ok arg" and agotada is False
    assert "_cancelar_tool" not in ctx and "_deadline" not in ctx


def test_la_excepcion_de_la_tool_se_relanza():
    def _rota(a, c):
        raise RuntimeError("boom")
    with pytest.raises(RuntimeError):
        tt.correr_con_deadline(_rota, "t", "", _ctx(), 5)


def test_vence_y_devuelve_resultado_tipado(monkeypatch):
    monkeypatch.setenv(tt.ENV_GRACIA, "1")
    avisos = []
    tt.registrar_avisador(lambda o, m: avisos.append((o, m)))

    def _cuelga(a, ctx):
        ev = ctx.get("_cancelar_tool")
        ev.wait(30)                      # coopera: sale al cancelarse
        return "tarde"

    ctx = _ctx()
    t0 = time.time()
    out, agotada, info = tt.correr_con_deadline(_cuelga, "lenta", "", ctx, 1)
    assert agotada is True
    assert time.time() - t0 < 5
    assert out.startswith("RESULTADO lenta ERROR: tool agotada tras 1s (TOOL_TIMEOUT)")
    assert info["hilo_vivo"] is False    # coopero: quiescente
    assert avisos == []                  # nada que avisar
    assert tt._ULTIMO["quiescente"] is True


def test_no_quiescente_se_dice(monkeypatch):
    monkeypatch.setenv(tt.ENV_GRACIA, "1")
    avisos = []
    tt.registrar_avisador(lambda o, m: avisos.append((o, m)))
    out, agotada, info = tt.correr_con_deadline(
        lambda a, c: time.sleep(4), "terca", "", _ctx(), 1)
    assert agotada and info["hilo_vivo"] is True
    assert "NO termino en la gracia" in out
    assert avisos and avisos[0][0] == "timeout_tool"


# ── Quiescencia: el hijo muere DE VERDAD ─────────────────────────────────────

def test_el_hijo_registrado_muere_de_verdad(monkeypatch):
    monkeypatch.setenv(tt.ENV_GRACIA, "5")
    pids = []

    def _lanza(a, ctx):
        p = subprocess.Popen([sys.executable, "-c",
                              "import time; time.sleep(60)"])
        pids.append(p)
        ctx["_procesos_tool"].append(p)
        p.wait()                          # bloquea hasta que lo maten
        return "nunca"

    ctx = _ctx()
    out, agotada, info = tt.correr_con_deadline(_lanza, "hijo", "", ctx, 1)
    assert agotada
    p = pids[0]
    assert p.poll() is not None           # el Popen lo vio morir
    assert tt.pid_vivo(p.pid) is False    # y la sonda de PID tambien
    assert info["matados"] == 1 and info["vivos"] == []
    assert info["hilo_vivo"] is False     # p.wait() volvio: el hilo quiescio


# ── Por el pipeline real de run_tool ─────────────────────────────────────────

@pytest.fixture
def tool_lenta(monkeypatch):
    from cognia.agent import tools as T

    def _fn(args, ctx):
        ctx["_exit"] = 0                  # un exit rancio que NO debe salir
        ctx.get("_cancelar_tool").wait(30)
        return "RESULTADO lenta: tarde"

    monkeypatch.setitem(T.TOOLS, "lenta", {
        "fn": _fn, "doc": "lenta", "danger": False, "desc": "", "params": [],
        "timeout_s": 1, "timeout_interno": None})


def test_run_tool_timeout_baja_por_el_pipeline_sin_excepcion(tool_lenta, monkeypatch):
    """El test que falla sin el cableado en run_tool: resultado tipado, ok
    False, exit None (no 0) y el interceptor.despues SI corrio encima."""
    monkeypatch.setenv(tt.ENV_GRACIA, "1")
    from cognia.agent.tools import run_tool
    from cognia.harness import interceptor
    vistos = []
    original = interceptor.despues

    def _despues(name, args, ctx, out, ok, exit_code=None):
        vistos.append((name, ok, exit_code))
        return original(name, args, ctx, out, ok, exit_code=exit_code) + "\n[despues]"

    monkeypatch.setattr(interceptor, "despues", _despues)
    ctx = _ctx()
    out = run_tool("lenta", "x", ctx)
    assert isinstance(out, str)
    assert "TOOL_TIMEOUT" in out and out.startswith("RESULTADO lenta ERROR")
    assert out.rstrip().endswith("[despues]")
    assert vistos == [("lenta", False, None)]
    assert ctx["_ultimo_ok"] is False and ctx["_ultimo_exit"] is None
    assert tt._TOTAL[0] == 1


def test_run_tool_sin_deadline_corre_en_linea(monkeypatch):
    from cognia.agent import tools as T
    monkeypatch.setitem(T.TOOLS, "rapida", {
        "fn": lambda a, c: "RESULTADO rapida: ok", "doc": "r", "danger": False,
        "desc": "", "params": [], "timeout_s": 0, "timeout_interno": None})
    assert T.run_tool("rapida", "", _ctx()).startswith("RESULTADO rapida: ok")


def test_config_basura_avisa_y_corre_sin_deadline(tool_lenta, monkeypatch):
    """Global invalido: se grita UNA vez y la tool corre sin limite (aqui la
    tool declara 1 s, pero el spec numerico es lo que se evalua primero, asi
    que se usa una tool sin spec)."""
    monkeypatch.setenv(tt.ENV_TIMEOUT, "rapido")
    from cognia.agent import tools as T
    avisos = []
    monkeypatch.setattr(T, "_avisar_timeout_degradado",
                        lambda exc: avisos.append(str(exc)))
    monkeypatch.setitem(T.TOOLS, "sin_spec", {
        "fn": lambda a, c: "RESULTADO sin_spec: ok", "doc": "s", "danger": False,
        "desc": "", "params": [], "timeout_s": None, "timeout_interno": None})
    assert T.run_tool("sin_spec", "", _ctx()).startswith("RESULTADO sin_spec: ok")
    assert avisos and "rapido" in avisos[0]


# ── Revision adversarial 2026-08-24: permisos, pausa, huerfanos, hijos ───────

def test_pedir_al_llamador_corre_en_el_hilo_que_espera():
    """El worker sube un fn al hilo que espera en correr_con_deadline (el
    dueno de la consola): es el camino por el que el sentinel pregunta
    '[permiso]' en el despacho inline. Antes, con deadline, se auto-denegaba."""
    quien = []

    def _tool(a, ctx):
        hay, r = tt.pedir_al_llamador(
            lambda: threading.current_thread().name)
        quien.append((hay, r))
        return "ok"

    out, agotada, _ = tt.correr_con_deadline(_tool, "t", "", _ctx(), 5)
    assert out == "ok" and not agotada
    assert quien == [(True, threading.current_thread().name)]
    # fuera de un worker: nadie a quien pedir
    assert tt.pedir_al_llamador(lambda: 1) == (False, None)


def test_pausa_deadline_no_cuenta_para_el_reloj(monkeypatch):
    """El tiempo esperando al dueno (permiso) no es tiempo de la tool: con
    limite 0.6 s y 1.2 s en pausa, NO vence."""
    monkeypatch.setenv(tt.ENV_GRACIA, "0")

    def _tool(a, ctx):
        with tt.pausa_deadline():
            time.sleep(1.2)
        return "ok"

    out, agotada, _ = tt.correr_con_deadline(_tool, "t", "", _ctx(), 0.6)
    assert out == "ok" and agotada is False
    # y sin pausa el mismo sleep SI vence (control)
    out, agotada, _ = tt.correr_con_deadline(
        lambda a, c: time.sleep(1.2), "t", "", _ctx(), 0.6)
    assert agotada is True


def test_el_huerfano_no_escribe_el_exit_del_siguiente(monkeypatch):
    """Tool agotada que termina DESPUES y marca su exit: el ctx NO lo hereda
    (el 'evento sellado con el reloj rancio', otra vez)."""
    monkeypatch.setenv(tt.ENV_GRACIA, "0")
    from cognia.agent.tools import _marcar_exit
    fin = threading.Event()

    def _tool(a, ctx):
        time.sleep(0.8)
        _marcar_exit(ctx, 42)
        fin.set()
        return "tarde"

    ctx = _ctx()
    out, agotada, info = tt.correr_con_deadline(_tool, "t", "", ctx, 0.3)
    assert agotada and info["hilo_vivo"] is True
    assert fin.wait(5)
    assert "_exit" not in ctx, ctx
    assert tt.hilo_agotado() is False     # el principal no es un worker


def test_pedido_tras_el_vencimiento_no_cuelga(monkeypatch):
    """Un worker que pide DESPUES de que su llamador se fue recibe (False,
    None) al instante, no un wait eterno."""
    monkeypatch.setenv(tt.ENV_GRACIA, "0")
    caja = {}
    fin = threading.Event()

    def _tool(a, ctx):
        time.sleep(0.6)
        caja["r"] = tt.pedir_al_llamador(lambda: "nadie")
        fin.set()

    tt.correr_con_deadline(_tool, "t", "", _ctx(), 0.2)
    assert fin.wait(5)
    assert caja["r"] == (False, None)


def test_ejecutar_registra_el_popen_y_mata_el_arbol_en_su_timeout(
        tmp_path, monkeypatch):
    """'matar el shell NO mata el proceso': el nieto hereda el pipe y
    subprocess.run se quedaba en communicate() los 7 s enteros (medido: 7,0 s
    y TOOL_TIMEOUT del deadline externo). Con _correr_proceso: taskkill /T
    del arbol, vuelve en ~1 s, el nieto esta MUERTO y el exit es None."""
    from cognia.agent import tools as T
    monkeypatch.setenv("COGNIA_SENTINEL", "0")
    monkeypatch.setenv(tt.ENV_GRACIA, "1")
    pidf = tmp_path / "nieto_pid.txt"
    padre = tmp_path / "padre.py"
    padre.write_text(
        "import subprocess, sys\n"
        "subprocess.Popen([sys.executable, '-c', "
        f"\"import os,time;open('{pidf.as_posix()}','w').write(str(os.getpid()));"
        "time.sleep(7)\"]).wait()\n", encoding="utf-8")
    ctx = _ctx()
    t0 = time.time()
    out = T.run_tool("ejecutar", f'"{sys.executable}" "{padre}" | timeout=1', ctx)
    assert time.time() - t0 < 5, out
    assert "timeout tras 1s" in out and tt.CODIGO not in out
    assert ctx["_ultimo_exit"] is None
    time.sleep(0.3)
    assert pidf.exists(), "el nieto no llego a arrancar"
    assert tt.pid_vivo(int(pidf.read_text())) is False
