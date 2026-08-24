# -*- coding: utf-8 -*-
"""
Regresion (2026-08-24): el agente repetia la misma llamada con los mismos
argumentos y lo unico que le llegaba era un aviso generico (register_action)
o el corte seco (GuardiaBucle). Estos tests fijan el contrato de
`cognia/harness/repeticion.py` (repeat-tool-reminder de deepseek-harness):
clave canonica con key-sort recursivo, umbrales [3,5,8] con texto suave y
detallado, las fallidas/vetadas cuentan, reset por prompt humano, tools
transparentes, config invalida que GRITA en vez de callar, y el cableado
real a traves de run_tool (el test que falla sin el fix del interceptor).

Sin el modulo, el fichero entero falla en el import.
"""

from __future__ import annotations

import pytest

from cognia.harness import repeticion as rep


@pytest.fixture(autouse=True)
def aislado(monkeypatch):
    monkeypatch.delenv(rep.ENV_ACTIVO, raising=False)
    monkeypatch.delenv(rep.ENV_UMBRALES, raising=False)
    monkeypatch.setattr(rep, "_AVISADOR", None)
    rep._AVISADO[0] = False
    rep._ULTIMO.clear()
    rep._ULTIMO_ERROR.clear()
    rep._TOTAL[0] = 0
    rep._GLOBAL.reset()


# ── Clave canonica ───────────────────────────────────────────────────────────

def test_dict_con_otro_orden_es_la_misma_clave():
    a = rep.clave_canonica("editar", {"path": "a.py", "contenido": "x"})
    b = rep.clave_canonica("editar", {"contenido": "x", "path": "a.py"})
    assert a == b


def test_key_sort_es_recursivo():
    a = rep.clave_canonica("t", {"z": [{"b": 1, "a": 2}], "a": {"y": 1, "x": 2}})
    b = rep.clave_canonica("t", {"a": {"x": 2, "y": 1}, "z": [{"a": 2, "b": 1}]})
    assert a == b


def test_string_json_y_dict_coinciden_y_los_espacios_no_cuentan():
    assert (rep.clave_canonica("t", '{"b": 1, "a": 2}')
            == rep.clave_canonica("t", {"a": 2, "b": 1}))
    assert (rep.clave_canonica("leer", "a.py  |   3")
            == rep.clave_canonica("leer", "a.py | 3"))


def test_tool_distinta_o_args_distintos_clave_distinta():
    assert rep.clave_canonica("a", "x") != rep.clave_canonica("b", "x")
    assert rep.clave_canonica("a", "x") != rep.clave_canonica("a", "y")


# ── Umbrales y textos ────────────────────────────────────────────────────────

def _racha(c, n, tool="leer_archivo", args="a.py", ok=True):
    return [c.registrar(tool, args, ok) for _ in range(n)]


def test_suave_al_tercero_detallado_al_quinto_y_octavo():
    c = rep.Contador()
    r = _racha(c, 8)
    assert r[0] == r[1] == ""
    assert r[2].startswith(rep.MARCA) and "3 veces seguidas" in r[2]
    assert "leer_archivo" in r[2]
    assert r[3] == ""
    assert r[4].startswith(rep.MARCA) and "5 llamadas CONSECUTIVAS" in r[4]
    assert "a.py" in r[4] and "argumentos exactos" in r[4]
    assert r[5] == r[6] == ""
    assert "8 llamadas CONSECUTIVAS" in r[7]
    assert c.recordatorios == 3
    assert rep._ULTIMO["tipo"] == "detallado" and rep._ULTIMO["n"] == 8


def test_umbrales_configurables_por_env(monkeypatch):
    monkeypatch.setenv(rep.ENV_UMBRALES, "2, 4")
    c = rep.Contador()
    r = _racha(c, 5)
    assert r[1] and "2 veces" in r[1]
    assert r[2] == ""
    assert r[3] and "4 llamadas" in r[3]
    assert r[4] == ""


def test_args_citados_con_cap_de_500():
    c = rep.Contador()
    largo = "x" * 2000
    r = _racha(c, 5, args=largo)
    assert "x" * 500 in r[4]
    assert "x" * 501 not in r[4]
    assert "1500 chars mas" in r[4]


def test_las_fallidas_cuentan_igual():
    c = rep.Contador()
    r = _racha(c, 3, ok=False)
    assert r[2].startswith(rep.MARCA)
    assert rep._ULTIMO["ok"] is False


def test_una_llamada_distinta_rompe_la_racha():
    c = rep.Contador()
    _racha(c, 2)
    assert c.registrar("leer_archivo", "b.py") == ""
    assert c.n == 1
    assert c.registrar("leer_archivo", "b.py") == ""
    assert c.registrar("leer_archivo", "b.py").startswith(rep.MARCA)


def test_exentas_son_transparentes_ni_cuentan_ni_rompen():
    c = rep.Contador()
    _racha(c, 2)
    for _ in range(10):
        assert c.registrar("ver_salida", "proc-1") == ""
    assert c.n == 2
    assert c.registrar("leer_archivo", "a.py").startswith(rep.MARCA)


def test_reset_por_prompt_humano():
    ctx = {}
    c = rep.contador_de(ctx)
    _racha(c, 2)
    rep.nuevo_prompt_humano()
    assert rep.contador_de(ctx) is c
    assert c.registrar("leer_archivo", "a.py") == ""
    assert c.n == 1


def test_un_contador_por_ctx():
    c1, c2 = rep.contador_de({}), rep.contador_de({})
    assert c1 is not c2
    _racha(c1, 3)
    assert c2.n == 0


# ── Config invalida: grita, no calla ─────────────────────────────────────────

@pytest.mark.parametrize("basura", ["3,2", "x", "1,3", "3,x", "0", "2.5"])
def test_umbrales_invalidos_lanzan_al_cargar(basura, monkeypatch):
    monkeypatch.setenv(rep.ENV_UMBRALES, basura)
    with pytest.raises(rep.ConfigInvalida):
        rep.umbrales()
    with pytest.raises(rep.ConfigInvalida):
        rep.validar_config()


def test_config_invalida_avisa_una_vez_y_deja_el_texto_intacto(monkeypatch):
    monkeypatch.setenv(rep.ENV_UMBRALES, "3,2")
    avisos = []
    rep.registrar_avisador(lambda origen, motivo: avisos.append((origen, motivo)))
    ctx = {}
    for _ in range(4):
        assert rep.anexar("leer_archivo", "a.py", ctx, "RESULTADO ok") == "RESULTADO ok"
    assert len(avisos) == 1
    assert avisos[0][0] == "repeticion" and "invalida" in avisos[0][1]
    assert rep.estado()["config_error"]


def test_apagado_por_env_no_anexa_nada(monkeypatch):
    monkeypatch.setenv(rep.ENV_ACTIVO, "0")
    ctx = {}
    for _ in range(5):
        assert rep.anexar("leer_archivo", "a.py", ctx, "R") == "R"


def test_anexar_pone_el_recordatorio_al_final():
    ctx = {}
    rep.anexar("leer_archivo", "a.py", ctx, "R")
    rep.anexar("leer_archivo", "a.py", ctx, "R")
    out = rep.anexar("leer_archivo", "a.py", ctx, "RESULTADO leer: hola\n")
    assert out.startswith("RESULTADO leer: hola")
    assert out.rstrip().endswith("cambia los argumentos o la herramienta.")
    assert rep.MARCA in out


# ── Cableado real: a traves de run_tool ──────────────────────────────────────

@pytest.fixture
def tool_de_prueba(monkeypatch):
    from cognia.agent import tools as T
    llamadas = []

    def _fn(args, ctx):
        llamadas.append(args)
        return f"RESULTADO prueba_rep: {args}"

    monkeypatch.setitem(T.TOOLS, "prueba_rep", {
        "fn": _fn, "doc": "prueba_rep", "danger": False, "desc": "",
        "params": [], "timeout_s": 0, "timeout_interno": None})
    return llamadas


def _ctx():
    return {"working_memory": {}, "agent_state": {},
            "print_fn": lambda *a, **k: None}


def test_run_tool_anexa_el_recordatorio_a_la_tercera(tool_de_prueba):
    """El test que falla sin el enganche en interceptor.despues."""
    from cognia.agent.tools import run_tool
    ctx = _ctx()
    r1 = run_tool("prueba_rep", "x", ctx)
    r2 = run_tool("prueba_rep", "x", ctx)
    r3 = run_tool("prueba_rep", "x", ctx)
    assert rep.MARCA not in r1 and rep.MARCA not in r2
    assert r3.startswith("RESULTADO prueba_rep: x")
    assert rep.MARCA in r3 and "3 veces seguidas" in r3
    # la tool SI corrio las tres veces: advisory, nunca veta
    assert len(tool_de_prueba) == 3


def test_run_tool_cuenta_las_vetadas(tool_de_prueba, monkeypatch):
    from cognia.agent.tools import run_tool
    from cognia.harness import interceptor
    monkeypatch.setattr(interceptor, "antes",
                        lambda name, args, ctx: "BLOQUEADO por prueba")
    ctx = _ctx()
    run_tool("prueba_rep", "x", ctx)
    run_tool("prueba_rep", "x", ctx)
    r3 = run_tool("prueba_rep", "x", ctx)
    assert r3.startswith("BLOQUEADO por prueba")
    assert rep.MARCA in r3
    assert tool_de_prueba == []          # vetadas: la tool no corrio


def test_tareas_sanas_no_ensucian(tool_de_prueba):
    """Tres llamadas distintas seguidas: cero recordatorios."""
    from cognia.agent.tools import run_tool
    ctx = _ctx()
    for a in ("a", "b", "c", "a", "b", "c"):
        assert rep.MARCA not in run_tool("prueba_rep", a, ctx)
    assert rep._TOTAL[0] == 0
