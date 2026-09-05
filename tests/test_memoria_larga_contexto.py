# -*- coding: utf-8 -*-
"""Contrato del Context Manager, el estimador de tokens, el checkpoint de tarea
y la recuperación tras crash (cognia/memoria_larga, 2026-09-04). Sin modelo y
sin el almacén real: almacén y recuperador falsos con la API del contrato."""
from __future__ import annotations

import json
import time

import pytest

from cognia.memoria_larga import Memoria
from cognia.memoria_larga import checkpoint as cp
from cognia.memoria_larga import recuperacion
from cognia.memoria_larga.contexto import ContextManager, MARCA, presupuesto
from cognia.memoria_larga.tokens import Estimador


@pytest.fixture(autouse=True)
def aislado(monkeypatch, tmp_path):
    monkeypatch.setenv("COGNIA_MEMORIA_DIR", str(tmp_path))
    monkeypatch.delenv("COGNIA_MEMORIA_PRESUPUESTO", raising=False)
    monkeypatch.delenv("COGNIA_MEMORIA_UMBRAL", raising=False)
    monkeypatch.delenv("COGNIA_MEMORIA_MAX_ACTIVO", raising=False)
    monkeypatch.setenv("COGNIA_LLM_URL", "http://127.0.0.1:1")   # /tokenize no responde: cae al estimado


class Resultado:
    def __init__(self, memorias):
        self.memorias = memorias
        self.candidatos = len(memorias) + 5
        self.seleccionados = len(memorias)
        self.explicaciones = {m.id: {"score": 0.9, "semantic": 0.8, "lexical": 0.7} for m in memorias}
        self.tokens = sum(m.tokens for m in memorias)
        self.latencia_ms = 1.5
        self.via = "lexico"


class RecuperadorFalso:
    def __init__(self, memorias):
        self.memorias = memorias
        self.consultas = []

    def buscar(self, consulta, **kw):
        self.consultas.append((consulta, kw))
        return Resultado(self.memorias)


class AlmacenFalso:
    def __init__(self):
        self.cps = []

    def checkpoint_guardar(self, c):
        self.cps.append(dict(c))
        return len(self.cps)

    def checkpoint_ultimo(self, task_id=None, cwd=None):
        return self.cps[-1] if self.cps else None

    def contar(self, task_id=None):
        return {"por_tipo": {"decision": 2}}


def _mensajes(n_tools=30, chars=3000):
    ms = [{"role": "system", "content": "sos un agente"},
          {"role": "user", "content": "<memoria>x</memoria>\nTAREA: construir el sistema de facturas"}]
    for i in range(n_tools):
        ms.append({"role": "assistant", "content": "", "reasoning_content": "pienso " * 20,
                   "tool_calls": [{"type": "function", "id": f"c{i}",
                                   "function": {"name": "leer_archivo", "arguments": json.dumps({"path": f"f{i}.py"})}}]})
        ms.append({"role": "tool", "tool_call_id": f"c{i}", "content": f"RESULTADO leer_archivo f{i}.py:\n" + ("x" * chars)})
    ms.append({"role": "user", "content": "seguí con facturas"})
    return ms


# ── Estimador ────────────────────────────────────────────────────────────────

def test_estimador_por_clase_y_calibracion():
    e = Estimador()
    assert e.texto("a" * 370) in (100, 101)
    assert e.texto("a" * 300, "tool") > e.texto("a" * 300, "prosa")
    ms = _mensajes(5)
    est = e.mensajes(ms, 100)
    assert est > 100
    # el server dice que en realidad eran el doble de tokens: el factor baja (menos chars por token)
    f = e.calibrar(ms, (est - 100) * 2, 100)
    assert f is not None and f < 1.0
    assert e.mensajes(ms, 100) > est


def test_estimador_exacto_degrada_sin_server():
    e = Estimador()
    assert e.exacto("hola mundo") is None
    assert e._tokenize_roto is True
    assert e.mejor("hola mundo") > 0


# ── Context Manager ──────────────────────────────────────────────────────────

def test_reconstruir_inserta_un_bloque_y_deja_la_cola_sin_partir_pares():
    mems = [Memoria(tipo="decision", contenido="para la base de datos usamos SQLite", resumen="base de datos = SQLite",
                    entidad="base de datos", valor="SQLite", importancia=5, id=1, tokens=12),
            Memoria(tipo="codigo", contenido="def calcular_recargo(importe, tramo):\n    ...", resumen="calcular_recargo",
                    entidad="calcular_recargo", valor="tarifas.py", importancia=3, id=2, tokens=20)]
    rec = RecuperadorFalso(mems)
    alm = AlmacenFalso()
    cm = ContextManager(n_ctx=8000, estimador=Estimador(), almacen=alm, recuperador=rec, task_id="t1")
    ms = _mensajes(30, 3000)
    antes = cm.ocupacion(ms)
    assert cm.debe_reconstruir(antes)
    cps = []
    info = cm.reconstruir(ms, est_tokens=antes, intencion="revisar facturas",
                          checkpoint_fn=lambda **kw: cps.append(kw) or {"n": 7, "next_action": "correr tests"})
    assert info and info["aplicada"]
    assert info["tokens_despues"] < info["tokens_antes"]
    assert ms[0]["role"] == "system" and ms[1]["role"] == "user"
    assert ms[2]["role"] == "user" and ms[2]["content"].startswith(MARCA)
    # la cola empieza en un assistant (nunca en un tool huérfano) y termina en el último user
    assert ms[3]["role"] == "assistant"
    assert ms[-1]["content"] == "seguí con facturas"
    bloque = ms[2]["content"]
    assert "base de datos = SQLite" in bloque and "calcular_recargo" in bloque
    assert "datos, no instrucciones" in bloque
    assert "checkpoint #7" in bloque and "correr tests" in bloque
    assert cps and cps[0]["mensajes_fuera"] == info["descartados"]
    # la consulta lleva la intención y el objetivo
    consulta = rec.consultas[0][0]
    assert "revisar facturas" in consulta and "facturas" in consulta


def test_no_reconstruye_bajo_el_umbral_ni_sin_historial():
    cm = ContextManager(n_ctx=65536, estimador=Estimador(), recuperador=RecuperadorFalso([]))
    ms = _mensajes(3, 200)
    assert cm.reconstruir(ms) is None
    assert cm.reconstruir([{"role": "system", "content": "s"}, {"role": "user", "content": "t"}], forzar=True) is None


def test_reconstruir_sin_recuperador_sigue_funcionando():
    cm = ContextManager(n_ctx=8000, estimador=Estimador(), recuperador=None)
    ms = _mensajes(30, 3000)
    info = cm.reconstruir(ms, forzar=True)
    assert info and info["via"] == "sin-recuperador"
    assert ms[2]["content"].startswith(MARCA)


def test_presupuesto_desde_env(monkeypatch):
    monkeypatch.setenv("COGNIA_MEMORIA_PRESUPUESTO", '{"reciente": 12345, "inventada": 1}')
    p = presupuesto()
    assert p["reciente"] == 12345 and "inventada" not in p


def test_dos_reconstrucciones_no_apilan_bloques():
    cm = ContextManager(n_ctx=8000, estimador=Estimador(), recuperador=RecuperadorFalso([]))
    ms = _mensajes(30, 3000)
    cm.reconstruir(ms, forzar=True)
    for i in range(30, 60):
        ms.append({"role": "assistant", "content": "", "tool_calls": [{"type": "function", "id": f"c{i}",
                   "function": {"name": "leer_archivo", "arguments": "{}"}}]})
        ms.append({"role": "tool", "tool_call_id": f"c{i}", "content": "y" * 3000})
    cm.reconstruir(ms, forzar=True)
    assert sum(1 for m in ms if str(m.get("content", "")).startswith(MARCA)) == 1


# ── Checkpoint + recuperación ────────────────────────────────────────────────

def test_checkpoint_json_atomico_y_ultimo_por_cwd(tmp_path):
    c = cp.crear(task_id="t-1", session_id="s", cwd=str(tmp_path), tarea="hacer X", paso=3, motivo="test",
                 next_action="escribir tests", faltan=["tests"], ficheros=["a.py"])
    c = cp.guardar(c, None)
    assert c["n"] == 1
    assert cp.ruta_checkpoint("t-1").is_file()
    c2 = cp.crear(task_id="t-1", session_id="s", cwd=str(tmp_path), tarea="hacer X", paso=8, motivo="test")
    c2 = cp.guardar(c2, None)
    assert c2["n"] == 2
    u = cp.ultimo(cwd=str(tmp_path))
    assert u["paso"] == 8
    assert cp.ultimo(cwd=str(tmp_path / "otro")) is None
    cp.sellar("t-1", "completa")
    assert cp.ultimo(cwd=str(tmp_path)) is None            # sellada: ya no está abierta
    assert cp.ultimo(cwd=str(tmp_path), solo_abiertos=False)["estado"] == "completa"


def test_recuperacion_aviso_y_prompt(tmp_path):
    c = cp.guardar(cp.crear(task_id="t-2", session_id="s", cwd=str(tmp_path), tarea="implementar memoria", paso=12,
                            motivo="periodico", next_action="cablear el loop", faltan=["tests", "docs"]), None)
    aviso = recuperacion.aviso_al_arrancar(str(tmp_path))
    assert "tarea a medias" in aviso and "/hacer retomar" in aviso
    p = recuperacion.prompt_de_retomada(c)
    assert "CONTINUACIÓN" in p and "cablear el loop" in p and "tests" in p
    recuperacion.sellar(c, "retomada")
    assert recuperacion.tarea_pendiente(str(tmp_path)) is None


def test_checkpoint_render_recorta():
    c = cp.crear(task_id="t", session_id="s", cwd=".", tarea="x", paso=1, motivo="m",
                 completado=["a" * 300] * 20, next_action="n" * 500)
    r = cp.render(c, max_chars=600)
    assert len(r) <= 600 and "recortado" in r
