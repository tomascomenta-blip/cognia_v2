# -*- coding: utf-8 -*-
"""Contrato de `cognia/harness/validacion_tool_call.py` (FunctionCallingParser
de SWE-agent con códigos de error, 2026-09-04): falta_argumento,
argumento_vacio, argumento_inesperado, tipo_incorrecto; el passthrough
`{"args": ...}` y las tools sin schema pasan; la firma sale en el mensaje;
kill-switch; y el cableado en `bucle_nativo`: una llamada sin `contenido` NO
escribe nada y el resultado que ve el modelo es el error de formato.
"""
from __future__ import annotations

import pytest

from cognia.harness import validacion_tool_call as v


@pytest.fixture(autouse=True)
def encendido(monkeypatch):
    monkeypatch.delenv(v.ENV_ACTIVO, raising=False)
    v.olvidar_cache()


def test_escribir_sin_contenido_es_falta_argumento():
    r = v.validar("escribir_archivo", {"path": "x.py"})
    assert r and r[0] == "falta_argumento"
    assert "'contenido'" in r[1] and "escribir_archivo(path*, contenido*)" in r[1]
    assert "NO se ejecutó" in r[1]


def test_llamada_completa_pasa():
    assert v.validar("escribir_archivo", {"path": "x.py", "contenido": "print(1)"}) is None
    assert v.validar("leer_archivo", {"path": "x.py"}) is None
    assert v.validar("editar_archivo", {"path": "a", "buscar": "b", "reemplazar": ""}) is None


def test_path_vacio_es_argumento_vacio():
    r = v.validar("leer_archivo", {"path": "   "})
    assert r and r[0] == "argumento_vacio"


def test_clave_inventada_es_argumento_inesperado():
    r = v.validar("leer_archivo", {"ruta": "x.py"})
    assert r and r[0] == "falta_argumento"          # primero lo que falta
    r = v.validar("leer_archivo", {"path": "x.py", "modo": "r"})
    assert r and r[0] == "argumento_inesperado" and "'modo'" in r[1] and "path" in r[1]


def test_passthrough_args_y_tools_sin_schema_pasan():
    assert v.validar("escribir_archivo", {"args": "x.py | hola"}) is None
    assert v.validar("tool_que_no_existe", {"lo": "que sea"}) is None
    assert v.validar("leer_archivo", "no es dict") is None


def test_tipos(monkeypatch):
    monkeypatch.setattr(v, "_SCHEMAS", {"t": {"type": "object", "properties": {
        "n": {"type": "integer"}, "x": {"type": "number"}, "b": {"type": "boolean"}, "s": {"type": "string"}},
        "required": ["n"]}})
    assert v.validar("t", {"n": 3}) is None
    assert v.validar("t", {"n": "42"}) is None            # string numérico vale (hermes coerce)
    assert v.validar("t", {"n": 2.0, "x": "3.5", "b": "true"}) is None
    assert v.validar("t", {"n": "tres"})[0] == "tipo_incorrecto"
    assert v.validar("t", {"n": True})[0] == "tipo_incorrecto"
    assert v.validar("t", {"n": 1, "b": "quizás"})[0] == "tipo_incorrecto"
    assert v.validar("t", {"n": 1, "x": "abc"})[0] == "tipo_incorrecto"


def test_normalizar_resuelve_alias_reales():
    # `ruta` por `path` (lo que mandan los modelos de verdad, ver test_agente_streaming)
    assert v.normalizar("escribir_archivo", {"ruta": "a.py", "contenido": "x"}) == {"path": "a.py", "contenido": "x"}
    assert v.normalizar("leer_archivo", {"file_path": "a.py"}) == {"path": "a.py"}
    # una sola propiedad en el schema y una sola clave con otro nombre
    assert v.normalizar("listar", {"path": "x"}) == {"directorio": "x"}
    # un required que falta y una clave que sobra -> se renombra
    assert v.normalizar("apendar_archivo", {"path": "a", "contenido": "t"}) == {"path": "a", "texto": "t"}
    # lo que ya es correcto no se toca; el passthrough tampoco
    assert v.normalizar("leer_archivo", {"path": "a.py"}) == {"path": "a.py"}
    assert v.normalizar("leer_archivo", {"args": "a.py"}) == {"args": "a.py"}
    # dos claves de mas y una que falta: ambiguo, se deja para que validar lo diga
    assert v.normalizar("leer_archivo", {"a": 1, "b": 2}) == {"a": 1, "b": 2}
    assert v.validar("leer_archivo", v.normalizar("leer_archivo", {"a": 1, "b": 2}))[0] == "falta_argumento"


def test_normalizar_no_pisa_una_clave_que_ya_vino():
    assert v.normalizar("leer_archivo", {"path": "a.py", "ruta": "b.py"})["path"] == "a.py"


def test_kill_switch(monkeypatch):
    monkeypatch.setenv(v.ENV_ACTIVO, "0")
    assert v.validar("escribir_archivo", {"path": "x.py"}) is None


def test_firma():
    assert v.firma("editar_archivo") == "editar_archivo(path*, buscar*, reemplazar*)"


# ── Cableado en el loop: la tool no corre ─────────────────────────────────

def test_cableado_en_bucle_nativo_no_escribe(tmp_path, monkeypatch):
    """El loop, ante {"path": "x.py"} sin contenido, devuelve el error de
    formato al modelo y NO llama a run_tool. Se simula un backend que primero
    manda ese tool call y luego cierra con texto."""
    import json
    from cognia.agent import loop as L
    from cognia.agent.chat_client import RespuestaChat, ToolCall

    def TC(nombre, argumentos):
        return ToolCall(id="call_1", nombre=nombre, argumentos=argumentos,
                        argumentos_crudos=json.dumps(argumentos))

    def Resp(tool_calls, content="", finish="tool_calls"):
        return RespuestaChat(texto=content, tool_calls=tool_calls, finish_reason=finish,
                             usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15})

    respuestas = [Resp([TC("escribir_archivo", {"path": "x.py"})]),
                  Resp([], content="listo", finish="stop")]
    llamadas = []

    def completar(mensajes, **kw):
        return respuestas.pop(0)

    def run_tool(nombre, args, ctx):
        llamadas.append((nombre, args))
        return "RESULTADO escribir_archivo: ok"

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COGNIA_HERMES", "0")
    monkeypatch.setenv("COGNIA_ESTADO", "0")
    monkeypatch.setenv("COGNIA_REVISION", "0")
    monkeypatch.setenv("COGNIA_LAZO_CORTO", "0")
    monkeypatch.setenv("COGNIA_ARRANQUE_HITOS", "0")
    monkeypatch.setenv("COGNIA_VERIFICAR_AL_CERRAR", "0")
    import inspect
    firma = inspect.signature(L.bucle_nativo)
    kwargs = {}
    for nombre_p in ("completar", "run_tool"):
        assert nombre_p in firma.parameters, f"bucle_nativo sin parámetro {nombre_p}: adaptar el test"
    from cognia.agent.chat_client import mensaje_assistant, mensaje_tool
    from cognia.agent.tool_schemas import args_legacy
    kwargs = dict(task="escribe x.py", completar=completar, run_tool=run_tool,
                  print_fn=lambda *a, **k: None, max_turns=4)
    for nombre_p, valor in (("mensaje_assistant", mensaje_assistant), ("mensaje_tool", mensaje_tool),
                            ("args_legacy", args_legacy), ("history", []), ("trace", []),
                            ("schemas", []), ("ctx", {"cwd": str(tmp_path)}), ("perfil", {}),
                            ("system", "sos un agente")):
        if nombre_p in firma.parameters:
            kwargs[nombre_p] = valor
    faltan = [p.name for p in firma.parameters.values()
              if p.default is inspect._empty and p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)
              and p.name not in kwargs]
    assert not faltan, f"bucle_nativo exige {faltan}: adaptar el test"
    out = L.bucle_nativo(**kwargs)
    assert llamadas == [], "la tool se ejecutó con argumentos incompletos"
    assert not (tmp_path / "x.py").exists()
    texto = out.get("texto") if isinstance(out, dict) else str(out)
    assert "listo" in (texto or "")
