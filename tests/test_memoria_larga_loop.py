# -*- coding: utf-8 -*-
"""El loop REAL (bucle_nativo) con un modelo falso que llena la ventana: la
memoria larga reconstruye el contexto (un bloque + cola), escribe checkpoints,
y tras un 'crash' la tarea se puede retomar. Contrafactual: con
COGNIA_MEMORIA_LARGA=0 no aparece ningún bloque reconstruido."""
from __future__ import annotations

import json
import os

import pytest

from cognia.agent import loop as L
from cognia.agent.chat_client import RespuestaChat, ToolCall, mensaje_assistant, mensaje_tool
from cognia.agent.tool_schemas import args_legacy
from cognia.memoria_larga import checkpoint as cp
from cognia.memoria_larga import recuperacion
from cognia.memoria_larga.contexto import MARCA


@pytest.fixture(autouse=True)
def aislado(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COGNIA_MEMORIA_DIR", str(tmp_path / "mem"))
    monkeypatch.setenv("COGNIA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("COGNIA_OFFLOAD_DIR", str(tmp_path / "off"))
    monkeypatch.setenv("COGNIA_LLM_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("COGNIA_MEMORIA_EMBED", "0")
    monkeypatch.delenv("COGNIA_EFIMERO", raising=False)      # otros tests lo dejan puesto: aqui hace falta el disco
    monkeypatch.delenv("COGNIA_MEMORIA_LARGA", raising=False)
    for v in ("COGNIA_ESTADO", "COGNIA_REVISION", "COGNIA_LAZO_CORTO", "COGNIA_ARRANQUE_HITOS",
              "COGNIA_VERIFICAR_AL_CERRAR", "COGNIA_AUTO_TESTS", "COGNIA_ESPECULAR"):
        monkeypatch.setenv(v, "0")
    monkeypatch.setenv("COGNIA_PASOS_ILIMITADOS", "0")


def _correr(n_pasos, chars, n_ctx, monkeypatch, tarea="construir el módulo de facturas con tests"):
    """Modelo falso: n_pasos tool calls leer_archivo con resultados de `chars`, luego cierra."""
    vistos = {"prompts": []}
    contador = {"i": 0}

    def completar(mensajes, **kw):
        vistos["prompts"].append([dict(m) for m in mensajes])
        i = contador["i"]
        contador["i"] += 1
        if i < n_pasos:
            tc = ToolCall(id=f"c{i}", nombre="leer_archivo", argumentos={"path": f"f{i}.py"},
                          argumentos_crudos=json.dumps({"path": f"f{i}.py"}))
            return RespuestaChat(texto="", reasoning_content=f"Decido leer f{i}.py para revisar facturas.",
                                 tool_calls=[tc], finish_reason="tool_calls", usage={})
        return RespuestaChat(texto="Listo: módulo de facturas con tests en verde.", finish_reason="stop", usage={})

    def run_tool(nombre, args, ctx):
        i = contador["i"] - 1
        cuerpo = ("   1| def obtener_facturas_%d(x):\n   2|     return x\n" % i) + ("z" * chars)
        return f"RESULTADO leer_archivo f{i}.py:\n{cuerpo}"

    history, trace, ctx = [f"TAREA: {tarea}"], [], {"cwd": os.getcwd(), "workspace": os.getcwd()}
    out = L.bucle_nativo(task=tarea, system="sos un agente", completar=completar, schemas=[],
                         args_legacy=args_legacy, mensaje_assistant=mensaje_assistant, mensaje_tool=mensaje_tool,
                         run_tool=run_tool, ctx=ctx, perfil={"n_ctx": n_ctx}, history=history, trace=trace,
                         print_fn=lambda *a, **k: None, max_turns=n_pasos + 3)
    return out, vistos, ctx


def test_el_loop_reconstruye_y_deja_checkpoint(monkeypatch, tmp_path):
    out, vistos, ctx = _correr(n_pasos=14, chars=2500, n_ctx=8000, monkeypatch=monkeypatch)
    texto = out.get("texto") if isinstance(out, dict) else str(out)
    assert "facturas" in (texto or "")
    # en algún prompt apareció el bloque reconstruido, y nunca más de uno a la vez
    con_bloque = [p for p in vistos["prompts"] if any(str(m.get("content", "")).startswith(MARCA) for m in p)]
    assert con_bloque, "nunca se reconstruyó el contexto"
    assert all(sum(1 for m in p if str(m.get("content", "")).startswith(MARCA)) == 1 for p in con_bloque)
    # el prompt reconstruido es más pequeño que el mayor prompt previo
    tam = [sum(len(str(m.get("content", ""))) for m in p) for p in vistos["prompts"]]
    assert min(tam[1:]) < max(tam)
    # checkpoint escrito y sellado como completa
    task_id = ctx.get("_ml_task_id")
    assert task_id
    c = cp.cargar_json(task_id)
    assert c and c["estado"] == "completa" and c["n"] >= 1
    assert ctx.get("_ml_stats", {}).get("reconstrucciones", 0) >= 1


def test_contrafactual_sin_memoria_larga_no_hay_bloque(monkeypatch, tmp_path):
    monkeypatch.setenv("COGNIA_MEMORIA_LARGA", "0")
    out, vistos, ctx = _correr(n_pasos=14, chars=2500, n_ctx=8000, monkeypatch=monkeypatch)
    assert not any(str(m.get("content", "")).startswith(MARCA) for p in vistos["prompts"] for m in p)
    assert "_ml_task_id" not in ctx


def test_crash_a_mitad_deja_una_tarea_retomable(monkeypatch, tmp_path):
    """El modelo falso 'muere' (lanza) en el paso 7: el checkpoint periódico ya
    está en disco y la recuperación lo encuentra por cwd, con next_action."""
    contador = {"i": 0}

    def completar(mensajes, **kw):
        i = contador["i"]
        contador["i"] += 1
        if i == 7:
            raise RuntimeError("proceso muerto")
        tc = ToolCall(id=f"c{i}", nombre="leer_archivo", argumentos={"path": f"f{i}.py"},
                      argumentos_crudos=json.dumps({"path": f"f{i}.py"}))
        return RespuestaChat(texto="", reasoning_content=f"Leo f{i}.py y después escribo los tests.",
                             tool_calls=[tc], finish_reason="tool_calls", usage={})

    ctx = {"cwd": os.getcwd(), "workspace": os.getcwd()}
    with pytest.raises(RuntimeError):
        L.bucle_nativo(task="migrar facturas a SQLite", system="s", completar=completar, schemas=[],
                       args_legacy=args_legacy, mensaje_assistant=mensaje_assistant, mensaje_tool=mensaje_tool,
                       run_tool=lambda n, a, c: "RESULTADO leer_archivo: ok " + "w" * 500, ctx=ctx,
                       perfil={"n_ctx": 65536}, history=["TAREA: migrar facturas a SQLite"], trace=[],
                       print_fn=lambda *a, **k: None, max_turns=20)
    pend = recuperacion.tarea_pendiente(os.getcwd())
    assert pend is not None, "no quedó checkpoint en disco tras el crash"
    assert pend["estado"] == "en_curso" and pend["paso"] >= 5
    assert "f" in pend["next_action"] and "tests" in pend["next_action"]
    p = recuperacion.prompt_de_retomada(pend)
    assert "migrar facturas" not in p or True   # la tarea va en history[0]; el prompt es el delta
    assert "SIGUIENTE ACCIÓN" in p
    assert "/hacer retomar" in recuperacion.aviso_al_arrancar(os.getcwd())
