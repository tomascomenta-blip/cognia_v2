# -*- coding: utf-8 -*-
"""
Regresion de las cinco piezas portadas de deepagents 0.7.8 al bucle nativo
(2026-08-24), todas SIN modelo:

  P2   args de escribir/editar/apendar viejos se truncan ANTES de compactar
       (summarization.py::_truncate_tool_call): sin perdida, el contenido ya
       esta en disco. El ULTIMO assistant no se toca.
  P5b  recorte DIRIGIDO de leer_archivo con puntero (_overflow_clip.py):
       4000 chars + "leer_archivo <ruta> offset=N".
  P1   tool_calls huerfanos (middleware/patch_tool_calls.py): cada call sin
       turno tool recibe uno sintetico antes del corte y en la traza.
  P12  bucle POR FICHERO (LoopDetectionMiddleware / dcode "DO NOT loop more
       than 3 times"): N ediciones al mismo fichero con args DISTINTOS ->
       nudge de reconsideracion, exactamente una vez por umbral.
  P8   shim de tool-calls por familia (NemotronToolCallShim +
       HarnessProfile.system_prompt_suffix): renombres/defaults/sufijo.
"""

from __future__ import annotations

import copy
import json

import pytest

from cognia.agent import loop as loop_mod
from cognia.agent import model_profiles as mp
from cognia.agent import traza_chatml as trz
from cognia.agent.chat_client import (RespuestaChat, ToolCall, mensaje_assistant,
                                      mensaje_tool)
from cognia.agent.tool_schemas import args_legacy, schemas_para
from cognia.harness import repeticion as rep


@pytest.fixture(autouse=True)
def _aislado(monkeypatch):
    for var in ("COGNIA_COMPACT", "COGNIA_COMPACT_UMBRAL", "COGNIA_COMPACT_RETENCION",
                "COGNIA_COMPACT_CAP", rep.ENV_ACTIVO, rep.ENV_UMBRALES,
                rep.ENV_UMBRAL_FICHERO, "COGNIA_TRAZAS", "COGNIA_TRAZAS_DIR",
                "COGNIA_TRACE"):
        monkeypatch.delenv(var, raising=False)
    # El run_tool falso no toca el disco: el gobernador por progreso (estado/
    # presupuesto_progreso, umbral_arranque=6) veria 6 vueltas sin un solo
    # avance MEDIDO y cortaria el bucle antes del 4o edit + cierres. No es lo
    # que se mide aqui.
    monkeypatch.setenv("COGNIA_ESTADO", "0")
    rep._AVISADO[0] = False
    rep._ULTIMO_FICHERO.clear()
    rep._TOTAL_FICHERO[0] = 0
    rep._GLOBAL.reset()


# ── arnes comun: el bucle con un completar guionado ──────────────────────────

def _perfil(**extra):
    p = {"nombre": "razonador_nativo", "modelo": "gpt-oss-20b.gguf",
         "url": "http://127.0.0.1:9", "tools": "nativo", "n_ctx": 16384,
         "temperature": 1.0, "top_p": 1.0, "reasoning_effort": "low",
         "max_tokens": 4096}
    p.update(extra)
    return p


def _resp_tools(*calls, prompt_tokens=100):
    return RespuestaChat(
        texto="", finish_reason="tool_calls",
        usage={"completion_tokens": 20, "prompt_tokens": prompt_tokens},
        tool_calls=[ToolCall(id=i, nombre=n, argumentos=a,
                             argumentos_crudos=json.dumps(a))
                    for i, n, a in calls])


def _resp_fin(texto="Listo."):
    return RespuestaChat(texto=texto, finish_reason="stop",
                         usage={"completion_tokens": 5, "prompt_tokens": 200})


def _correr(respuestas, run_tool, perfil=None, max_turns=10, capturar=None,
            legacy=args_legacy):
    """Corre bucle_nativo con las respuestas en orden. `capturar` (lista)
    recibe una copia de `mensajes` en CADA llamada a completar."""
    it = iter(respuestas)

    def _completar(mensajes, tools=None, **kw):
        if capturar is not None:
            capturar.append(copy.deepcopy(mensajes))
        return next(it)

    avisos = []
    history, trace = ["TAREA: arregla a.py"], []
    out = loop_mod.bucle_nativo(
        "arregla a.py", "sos el agente", _completar, schemas_para(),
        legacy, mensaje_assistant, mensaje_tool, run_tool, {},
        perfil or _perfil(), history, trace,
        lambda m, *a, **k: avisos.append(str(m)), max_turns)
    return out, avisos


# ── P2: args viejos de escritura ─────────────────────────────────────────────

def _historial_con_args_grandes(n_pares=3, chars=50_000):
    msgs = [{"role": "system", "content": "S"},
            {"role": "user", "content": "OBJETIVO: crea los ficheros"}]
    for i in range(n_pares):
        args = json.dumps({"path": f"f{i}.txt", "contenido": "x" * chars})
        msgs.append({"role": "assistant", "content": "",
                     "tool_calls": [{"type": "function", "id": f"c{i}",
                                     "function": {"name": "escribir_archivo",
                                                  "arguments": args}}]})
        msgs.append({"role": "tool", "tool_call_id": f"c{i}",
                     "content": f"RESULTADO escribir_archivo f{i}.txt: OK"})
    return msgs


def test_p2_args_de_escritura_viejos_se_truncan_y_el_ultimo_assistant_no():
    msgs = _historial_con_args_grandes(n_pares=3)
    ultimo = msgs[-2]["tool_calls"][0]["function"]["arguments"]
    liberados = loop_mod._recortar_mensajes(msgs, 16384, 15000)
    assert liberados > 40_000
    for i in (2, 4):               # los dos assistant viejos
        arg = msgs[i]["tool_calls"][0]["function"]["arguments"]
        assert arg.startswith('{"path": "f')
        assert loop_mod._MARCA_ARG_TRUNCADO in arg
        assert len(arg) < 160
        # POR VALOR (deepagents value[:20]): sigue siendo JSON y la ruta vive.
        d = json.loads(arg)
        assert d["path"] == f"f{i // 2 - 1}.txt"
        assert d["contenido"] == "x" * 20 + loop_mod._MARCA_ARG_TRUNCADO
    # El ULTIMO assistant (turno en curso) conserva sus args byte a byte.
    assert msgs[-2]["tool_calls"][0]["function"]["arguments"] == ultimo
    # Una segunda pasada no vuelve a liberar por los args (idempotente).
    assert loop_mod._truncar_args_escritura(msgs, len(msgs) - 2) == 0


def test_p2_solo_tools_de_escritura_y_solo_sobre_el_umbral():
    msgs = _historial_con_args_grandes(n_pares=2, chars=1000)     # < 2000
    msgs[2]["tool_calls"][0]["function"]["name"] = "leer_archivo"
    msgs[2]["tool_calls"][0]["function"]["arguments"] = "x" * 10_000
    antes = copy.deepcopy(msgs)
    assert loop_mod._truncar_args_escritura(msgs, len(msgs) - 2) == 0
    assert msgs == antes


def test_p2_bajo_el_umbral_de_contexto_no_toca_los_args():
    msgs = _historial_con_args_grandes(n_pares=2)
    antes = copy.deepcopy(msgs)
    assert loop_mod._recortar_mensajes(msgs, 16384, 100) == 0
    assert msgs == antes


def test_p2_la_pasada_corre_antes_de_compactar_sobre_la_cola(monkeypatch):
    from cognia.harness import compactacion as comp
    visto = {}

    def _compactar_stub(mensajes, n_ctx, prompt_tokens, estado=None, **kw):
        visto["args"] = [tc["function"]["arguments"]
                         for m in mensajes if m.get("role") == "assistant"
                         for tc in (m.get("tool_calls") or [])]
        return {"aplicada": False, "liberados": 0, "tokens_antes": prompt_tokens,
                "tokens_despues": prompt_tokens, "descartados": 0,
                "motivo": "stub"}

    monkeypatch.setattr(comp, "compactar", _compactar_stub)
    msgs = _historial_con_args_grandes(n_pares=3)
    r = loop_mod._compactar_por_resumen(msgs, 16384, 15000, None, lambda *a: None)
    assert r is not None and r > 80_000
    # compactar() ya recibio la cola con los args viejos truncados.
    assert loop_mod._MARCA_ARG_TRUNCADO in visto["args"][0]
    assert loop_mod._MARCA_ARG_TRUNCADO in visto["args"][1]
    assert len(visto["args"][2]) > 50_000        # el ultimo, intacto


def test_p2_trunca_por_valor_y_el_json_sigue_siendo_json():
    """Revision adversarial 2026-08-24: cortar el STRING a 20 chars dejaba
    '{"path": "src/app.py… (argumento truncado...' sin cierre; llama-server
    (:8080) respondia HTTP 500 'Failed to parse tool call arguments as JSON'
    a TODA la peticion siguiente y el agente moria tras la primera
    compactacion. Y compactacion._ruta_de_args perdia la ruta (ARTEFACTOS
    salia basura). deepagents trunca cada VALOR: value[:20]."""
    args = json.dumps({"path": "cognia/agent/fichero_0.py",
                       "contenido": "z" * 2500, "crear_dirs": True})
    nuevo = loop_mod._truncar_valores_args(args)
    d = json.loads(nuevo)                                   # no lanza
    assert d["path"] == "cognia/agent/fichero_0.py"        # la ruta vive
    assert d["crear_dirs"] is True                          # no-str intacto
    assert d["contenido"] == "z" * 20 + loop_mod._MARCA_ARG_TRUNCADO
    assert len(nuevo) < loop_mod._ARGS_TRUNCAR_MIN
    # editar_archivo: buscar corto se conserva, reemplazar largo se trunca.
    args2 = json.dumps({"path": "a.py", "buscar": "x = 1", "reemplazar": "y" * 3000})
    d2 = json.loads(loop_mod._truncar_valores_args(args2))
    assert d2["buscar"] == "x = 1" and d2["reemplazar"].startswith("y" * 20)
    # Protocolo texto 'ruta | contenido': la ruta sobrevive delante del '|'.
    txt = loop_mod._truncar_valores_args("src/app.py | " + "w" * 3000)
    assert txt.startswith("src/app.py | ") and txt.endswith(loop_mod._MARCA_ARG_TRUNCADO)
    from cognia.harness.compactacion import _ruta_de_args
    assert _ruta_de_args(nuevo) == "cognia/agent/fichero_0.py"
    assert _ruta_de_args(txt) == "src/app.py"
    # Un JSON > 2000 de valores CORTOS no achica: se deja como esta (sin
    # contar liberados falsos).
    muchos = json.dumps({f"k{i}": "v" * 100 for i in range(30)})
    msgs = [{"role": "assistant", "content": "",
             "tool_calls": [{"type": "function", "id": "z",
                             "function": {"name": "escribir_archivo",
                                          "arguments": muchos}}]}]
    assert loop_mod._truncar_args_escritura(msgs, 5) == 0
    assert msgs[0]["tool_calls"][0]["function"]["arguments"] == muchos


def test_p2_artefactos_del_resumen_conservan_las_rutas_tras_truncar():
    from cognia.harness import compactacion as comp
    msgs = [{"role": "system", "content": "S"}, {"role": "user", "content": "TAREA: x"}]
    for i in range(3):
        args = json.dumps({"path": f"cognia/agent/fichero_{i}.py", "contenido": "z" * 5000})
        msgs.append({"role": "assistant", "content": "",
                     "tool_calls": [{"type": "function", "id": f"c{i}",
                                     "function": {"name": "escribir_archivo",
                                                  "arguments": args}}]})
        msgs.append({"role": "tool", "tool_call_id": f"c{i}",
                     "content": f"RESULTADO escribir_archivo cognia/agent/fichero_{i}.py: OK"})
    for i in range(6):
        msgs.append({"role": "assistant", "content": "",
                     "tool_calls": [{"type": "function", "id": f"l{i}",
                                     "function": {"name": "leer_archivo",
                                                  "arguments": json.dumps({"path": f"f{i}.py"})}}]})
        msgs.append({"role": "tool", "tool_call_id": f"l{i}",
                     "content": f"RESULTADO leer_archivo f{i}.py: " + "q" * 3000})
    msgs.append({"role": "assistant", "content": "sigo"})
    comp._ULTIMA.clear()
    r = loop_mod._compactar_por_resumen(msgs, 8000, 20000, None, lambda *a: None)
    assert r and r > 15000
    resumen = next(m["content"] for m in msgs if comp._MARCA in str(m.get("content") or ""))
    assert "ARTEFACTOS (3 rutas tocadas" in resumen
    for i in range(3):
        assert f"  ~ cognia/agent/fichero_{i}.py" in resumen
    assert '* escribir_archivo({"path": "cognia/agent/fichero_0.py"' in resumen
    assert "(argumento truncado" not in resumen.split("ARTEFACTOS")[1].split("PROXIMOS")[0]


# ── P5b: leer_archivo con puntero ────────────────────────────────────────────

def _leer(n_lineas=900, ruta="src/a.py"):
    return (f"RESULTADO leer_archivo {ruta}: "
            + "\n".join(f"linea {i}" for i in range(1, n_lineas + 1)))


def test_p5b_recorte_de_leer_archivo_conserva_ruta_y_offset_correcto():
    content = _leer()
    msgs = [{"role": "assistant", "content": "",
             "tool_calls": [{"type": "function", "id": "t1",
                             "function": {"name": "leer_archivo",
                                          "arguments": '{"path": "src/a.py", "offset": 50}'}}]},
            {"role": "tool", "tool_call_id": "t1", "content": content}]
    liberados = loop_mod._recortar_mensajes(msgs, 16384, 15000)
    nuevo = msgs[1]["content"]
    assert liberados > 0 and len(nuevo) <= loop_mod._RECORTE_LEER + 200
    assert nuevo.startswith("RESULTADO leer_archivo src/a.py: linea 1\n")
    marca = nuevo[nuevo.rfind("\n[... recortado;"):]
    assert "el fichero completo esta en src/a.py: leer_archivo src/a.py offset=" in marca
    # El offset apunta a la linea SIGUIENTE a la ultima conservada, contando
    # desde el offset con el que se pidio (50): si se conservaron k lineas,
    # N = 50 + k.
    cuerpo = nuevo[len("RESULTADO leer_archivo src/a.py: "):nuevo.rfind("\n[... recortado;")]
    k = cuerpo.count("\n") + 1
    assert cuerpo.splitlines()[-1] == f"linea {k}"      # ninguna linea partida
    assert marca.rstrip().endswith(f"offset={50 + k} ...]")


def test_p5b_sin_offset_en_los_args_arranca_en_1_y_el_generico_sigue_a_200():
    msgs = [{"role": "tool", "tool_call_id": "t9", "content": _leer(300)},
            {"role": "tool", "tool_call_id": "t8", "content": "T" * 5000}]
    loop_mod._recortar_mensajes(msgs, 16384, 15000)
    cuerpo = msgs[0]["content"]
    k = cuerpo[len("RESULTADO leer_archivo src/a.py: "):cuerpo.rfind("\n[...")].count("\n") + 1
    assert cuerpo.rstrip().endswith(f"offset={1 + k} ...]")
    # Cualquier otra tool: el recorte generico de hoy, byte-identico.
    assert msgs[1]["content"] == "T" * 200 + "\n[... recortado por presupuesto de contexto ...]"


def test_p5b_un_leer_ya_recortado_no_gasta_plaza_de_la_pasada():
    """Revision adversarial 2026-08-24 (clase A3): un leer_archivo recortado
    a 200 + puntero mide 430-540 chars con una ruta larga (> _RECORTE_MIN) y
    se re-recortaba byte-identico: liberados += 0 pero gastaba una de las 3
    plazas. Con 3 leer al principio del historial la pasada devolvia 0 con
    el ejecutar de 9 KB y el reasoning de 9 KB intactos y el llamador
    cortaba su while: overflow silencioso."""
    ruta = "cognia/agent/" + "x" * 30 + "/fichero.py"
    cuerpo = "\n".join(f"linea {i} " + "k" * 20 for i in range(1, 400))
    msgs = [{"role": "system", "content": "S"}, {"role": "user", "content": "TAREA"}]
    for i in range(3):
        msgs.append({"role": "assistant", "content": "",
                     "tool_calls": [{"type": "function", "id": f"r{i}",
                                     "function": {"name": "leer_archivo",
                                                  "arguments": json.dumps({"path": ruta})}}]})
        msgs.append({"role": "tool", "tool_call_id": f"r{i}",
                     "content": f"RESULTADO leer_archivo {ruta}: {cuerpo}"})
    msgs.append({"role": "assistant", "content": "",
                 "tool_calls": [{"type": "function", "id": "e",
                                 "function": {"name": "ejecutar", "arguments": "ls"}}]})
    msgs.append({"role": "tool", "tool_call_id": "e", "content": "RESULTADO ejecutar: " + "y" * 9000})
    msgs.append({"role": "assistant", "content": "", "reasoning_content": "r" * 9000})
    msgs.append({"role": "assistant", "content": "fin"})
    tools = lambda: [len(m["content"]) for m in msgs if m["role"] == "tool"]
    assert loop_mod._recortar_mensajes(msgs, 8000, 10 ** 9) > 0      # 3 leer -> 4000
    assert loop_mod._recortar_mensajes(msgs, 8000, 10 ** 9) > 0      # 3 leer -> 200
    t = tools()
    assert all(loop_mod._RECORTE_MIN < n < 600 for n in t[:3]) and t[3] == 9020
    # Tercera pasada: los 3 leer ya no achican -> NO gastan plaza; caen el
    # ejecutar y el reasoning.
    assert loop_mod._recortar_mensajes(msgs, 8000, 10 ** 9) > 17000
    assert tools()[:3] == t[:3]
    assert tools()[3] < 300 and len(msgs[-2]["reasoning_content"]) < 300
    assert loop_mod._recortar_mensajes(msgs, 8000, 10 ** 9) == 0      # nada mas


# ── P1: tool_calls huerfanos ─────────────────────────────────────────────────

def test_p1_un_nudge_user_entre_resultados_paralelos_no_duplica():
    """bucle_nativo apende el user de nudge (_aviso_guardia/_aviso_fichero/
    verdict warn) DENTRO del for de tool_calls: con 3 calls paralelas y el
    nudge tras la primera, c1 y c2 tienen su resultado real DESPUES del
    user. Mirar solo el bloque contiguo insertaba dos '(cancelada...)' con
    tool_call_id duplicado (revision adversarial 2026-08-24)."""
    msgs = [{"role": "assistant", "content": "",
             "tool_calls": [{"type": "function", "id": f"c{i}",
                             "function": {"name": "leer_archivo"}} for i in range(3)]},
            {"role": "tool", "tool_call_id": "c0", "content": "ok0"},
            {"role": "user", "content": "[RECORDATORIO DE REPETICION] ..."},
            {"role": "tool", "tool_call_id": "c1", "content": "ok1"},
            {"role": "tool", "tool_call_id": "c2", "content": "ok2"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"type": "function", "id": "d0", "function": {"name": "tests"}},
                {"type": "function", "id": "d1", "function": {"name": "tests"}}]},
            {"role": "tool", "tool_call_id": "d0", "content": "okd0"},
            {"role": "user", "content": "AVISO: ..."}]
    antes = copy.deepcopy(msgs)
    # Solo d1 es huerfano (corte tras el nudge): va tras el ULTIMO tool real
    # de su tramo, antes del user.
    assert trz.parchear_huerfanos(msgs) == 1
    ids = [m.get("tool_call_id") for m in msgs if m["role"] == "tool"]
    assert ids == ["c0", "c1", "c2", "d0", "d1"] and len(set(ids)) == 5
    assert msgs[:5] == antes[:5]
    assert msgs[7]["tool_call_id"] == "d1" and msgs[7]["content"] == trz.CONTENIDO_HUERFANO
    assert msgs[8]["role"] == "user"
    assert trz.parchear_huerfanos(msgs) == 0


def test_p1_parchear_huerfanos_inserta_un_tool_por_cada_id_sin_resultado():
    msgs = [{"role": "assistant", "content": "",
             "tool_calls": [{"type": "function", "id": "a", "function": {"name": "listar"}},
                            {"type": "function", "id": "b", "function": {"name": "leer_archivo"}},
                            {"type": "function", "id": "c", "function": {"name": "tests"}}]},
            {"role": "tool", "tool_call_id": "a", "content": "RESULTADO listar: x"},
            {"role": "user", "content": "AVISO"}]
    assert trz.parchear_huerfanos(msgs) == 2
    assert [m["role"] for m in msgs] == ["assistant", "tool", "tool", "tool", "user"]
    assert [m["tool_call_id"] for m in msgs[1:4]] == ["a", "b", "c"]
    assert msgs[2]["name"] == "leer_archivo"
    assert msgs[2]["content"] == trz.CONTENIDO_HUERFANO
    assert trz.parchear_huerfanos(msgs) == 0          # idempotente


def test_p1_el_corte_por_estancamiento_deja_la_traza_sin_huerfanos(tmp_path, monkeypatch):
    """completar devuelve 3 tool_calls y el bucle corta tras la 1a (3ra vez el
    mismo par tool+args -> register_action 'stop'): en el volcado hay un
    turno tool por cada tool_call.id."""
    monkeypatch.setenv("COGNIA_TRAZAS", "1")
    monkeypatch.setenv("COGNIA_TRAZAS_DIR", str(tmp_path))
    monkeypatch.setenv("COGNIA_HOME", str(tmp_path))
    a = ("t1", "listar", {"directorio": "."})
    respuestas = [
        _resp_tools(a), _resp_tools(("t2",) + a[1:]),
        _resp_tools(("t3",) + a[1:], ("t4", "leer_archivo", {"path": "a.py"}),
                    ("t5", "tests", {"cmd": "pytest"})),
        _resp_fin(),
    ]
    ejecutadas = []

    def _run_tool(name, args, ctx):
        ejecutadas.append(name)
        return f"RESULTADO {name}: OK"

    out, _ = _correr(respuestas, _run_tool)
    assert "estancamiento" in out["texto"]
    assert ejecutadas == ["listar", "listar"]         # t3 no se ejecuto
    trazas = list(tmp_path.glob("*.json"))
    assert len(trazas) == 1
    mensajes = json.loads(trazas[0].read_text(encoding="utf-8"))["mensajes"]
    ids_calls = [tc["id"] for m in mensajes if m.get("role") == "assistant"
                 for tc in (m.get("tool_calls") or [])]
    ids_tools = [m["tool_call_id"] for m in mensajes if m.get("role") == "tool"]
    assert ids_calls == ["t1", "t2", "t3", "t4", "t5"]
    assert sorted(ids_tools) == sorted(ids_calls)
    huerfanos = [m for m in mensajes if m.get("role") == "tool"
                 and m["content"] == trz.CONTENIDO_HUERFANO]
    assert [m["tool_call_id"] for m in huerfanos] == ["t3", "t4", "t5"]
    # Cada sintetico va pegado a SU assistant (antes del user del aviso).
    i_ass = max(i for i, m in enumerate(mensajes) if m.get("role") == "assistant")
    assert [m["role"] for m in mensajes[i_ass + 1:i_ass + 4]] == ["tool"] * 3


# ── P12: bucle por fichero ───────────────────────────────────────────────────

def test_p12_contador_fichero_nudge_una_vez_por_umbral_y_normaliza_ruta():
    # 2026-08-30: los APENDICES cuentan aparte (construir un fichero por
    # partes no es reeditarlo), asi que la racha que dispara el nudge son
    # escrituras/ediciones. Ver test_arnes_tareas_largas.py.
    c = rep.ContadorFichero()
    assert c.registrar("a.py", "editar_archivo") == ""
    assert c.registrar("./A.py", "escribir_archivo") == ""
    n3 = c.registrar("a.py", "editar_archivo")
    assert n3.startswith(rep.MARCA) and "Llevas 3 ediciones sobre a.py" in n3
    assert "relee el fichero entero" in n3 and "cambia de enfoque" in n3
    assert c.registrar("a.py", "editar_archivo") == ""          # la 4a: nada
    assert c.registrar("a.py", "editar_archivo") == ""
    assert "Llevas 6 ediciones" in c.registrar("a.py", "editar_archivo")
    # transparentes: otra tool, ruta vacia, otro fichero
    assert c.registrar("a.py", "leer_archivo") == ""
    assert c.registrar("", "editar_archivo") == ""
    assert c.registrar("b.py", "editar_archivo") == ""
    est = c.estado()
    assert est["ficheros"] == {"a.py": 6, "b.py": 1} and est["nudges"] == 2
    assert est["apendices"] == {}
    e = rep.estado()
    assert e["umbral_fichero"] == 3 and e["total_fichero"] == 2
    assert e["umbral_apendice"] == rep.UMBRAL_APENDICE_DEFECTO
    assert e["ultimo_fichero"]["ruta"] == "a.py" and e["ultimo_fichero"]["n"] == 6


def test_p12_umbral_configurable_y_validado(monkeypatch):
    monkeypatch.setenv(rep.ENV_UMBRAL_FICHERO, "2")
    c = rep.ContadorFichero()
    assert c.registrar("x.py", "editar_archivo") == ""
    assert "Llevas 2 ediciones" in c.registrar("x.py", "editar_archivo")
    for malo in ("1", "abc", "0"):
        with pytest.raises(rep.ConfigInvalida):
            rep.parsear_umbral_fichero(malo)
    assert rep.parsear_umbral_fichero("") == rep.UMBRAL_FICHERO_DEFECTO
    monkeypatch.setenv(rep.ENV_UMBRAL_FICHERO, "zzz")
    assert "no entero" in rep.estado()["config_error"]
    assert rep.estado()["umbral_fichero"] == rep.UMBRAL_FICHERO_DEFECTO


def test_p12_tres_ediciones_al_mismo_fichero_con_args_distintos_inyectan_el_nudge():
    """register_action NO dispara (args distintos); el nudge por fichero si, y
    exactamente una vez: el 4o intento no lo repite y el bucle no corta."""
    calls = [("t%d" % i, "editar_archivo",
              {"path": "a.py", "buscar": f"v{i}", "reemplazar": f"w{i}"})
             for i in range(1, 5)]
    # 3 cierres: la parada verificada (hermes) puede pedir hasta 2 nudges de
    # verificacion tras editar sin correr nada; no es lo que se mide aqui.
    respuestas = [_resp_tools(c) for c in calls] + [_resp_fin("Arreglado.")] * 3
    capturas = []
    out, avisos = _correr(respuestas, lambda n, a, c: f"RESULTADO {n} a.py: OK (1 bloque)",
                          capturar=capturas)
    assert out["ok"] and out["texto"].startswith("Arreglado.")
    final = capturas[-1]                       # lo que vio el modelo al cerrar
    nudges = [m for m in final if m.get("role") == "user"
              and "Llevas 3 ediciones sobre a.py" in (m.get("content") or "")]
    assert len(nudges) == 1
    # Justo despues del resultado de la 3a edicion.
    i = final.index(nudges[0])
    assert final[i - 1]["role"] == "tool" and final[i - 1]["tool_call_id"] == "t3"
    assert not any("ya llamaste" in (m.get("content") or "") for m in final
                   if m.get("role") == "user")
    assert not any("estancado" in a for a in avisos)
    assert any("bucle por fichero" in a for a in avisos)


def test_p12_apagado_con_el_subsistema(monkeypatch):
    monkeypatch.setenv(rep.ENV_ACTIVO, "0")
    calls = [("t%d" % i, "editar_archivo", {"path": "a.py", "buscar": f"v{i}"})
             for i in range(1, 4)]
    capturas = []
    _correr([_resp_tools(c) for c in calls] + [_resp_fin()] * 3,
            lambda n, a, c: f"RESULTADO {n} a.py: OK", capturar=capturas)
    assert not any("Llevas 3 ediciones" in (m.get("content") or "")
                   for m in capturas[-1])


# ── P8: shim por familia ─────────────────────────────────────────────────────

def test_p8_aplicar_shim_renombra_rellena_y_sin_harness_no_copia():
    perfil = _perfil(harness={"renombres": {"file_path": "path"},
                              "defaults": {"leer_archivo": {"limit": 400}}})
    assert mp.aplicar_shim(perfil, "leer_archivo", {"file_path": "a.py"}) == \
        {"path": "a.py", "limit": 400}
    # el nombre real ya presente gana al alias; el default no pisa lo dado
    assert mp.aplicar_shim(perfil, "leer_archivo",
                           {"file_path": "x", "path": "a.py", "limit": 5}) == \
        {"file_path": "x", "path": "a.py", "limit": 5}
    assert mp.aplicar_shim(perfil, "escribir_archivo", {"path": "b"}) == {"path": "b"}
    args = {"file_path": "a.py"}
    assert mp.aplicar_shim(_perfil(), "leer_archivo", args) is args
    assert mp.aplicar_shim(perfil, "leer_archivo", "crudo") == "crudo"


def test_p8_el_bucle_aplica_el_shim_antes_de_args_legacy():
    recibidos = []

    def _legacy(nombre, argumentos):
        recibidos.append(dict(argumentos))
        return args_legacy(nombre, argumentos)

    resp = [_resp_tools(("t1", "leer_archivo", {"file_path": "a.py"})), _resp_fin()]
    _correr(list(resp), lambda n, a, c: "RESULTADO leer_archivo a.py: hola",
            perfil=_perfil(harness={"renombres": {"file_path": "path"}}),
            legacy=_legacy)
    assert recibidos == [{"path": "a.py"}]
    recibidos.clear()
    resp = [_resp_tools(("t1", "leer_archivo", {"file_path": "a.py"})), _resp_fin()]
    _correr(list(resp), lambda n, a, c: "RESULTADO leer_archivo a.py: hola",
            legacy=_legacy)
    # Sin harness el shim no toca nada, pero desde 2026-09-04 el rescate de
    # alias de harness/validacion_tool_call (hermes coerce_tool_args) resuelve
    # `file_path` -> `path` ANTES de validar contra el schema: lo que antes
    # llegaba "intacto" a args_legacy (y este salvaba juntando valores) llega
    # ahora con el nombre real. Con el kill-switch apagado vuelve a ser intacto.
    assert recibidos == [{"path": "a.py"}]
    recibidos.clear()
    import os
    os.environ["COGNIA_VALIDAR_TOOL_CALLS"] = "0"
    try:
        resp = [_resp_tools(("t1", "leer_archivo", {"file_path": "a.py"})), _resp_fin()]
        _correr(list(resp), lambda n, a, c: "RESULTADO leer_archivo a.py: hola",
                legacy=_legacy)
        assert recibidos == [{"file_path": "a.py"}]      # sin harness ni validacion: intactos
    finally:
        os.environ.pop("COGNIA_VALIDAR_TOOL_CALLS", None)


def test_p8_system_con_sufijo_y_sin_perfil_byte_identico(monkeypatch):
    # COGNIA_ENTORNO_PROMPT=0 desde el 2026-08-25: el system del agente lleva
    # UNA linea con SO/shell/cwd (system_prompt.entorno_agente) y este test
    # mide OTRA cosa — que el sufijo del harness sea lo unico que cambia el
    # texto. Apagar el entorno deja la comparacion byte a byte intacta; que la
    # linea entre en el tope y quede ANTES del sufijo lo fija
    # tests/test_agente_sabe_el_so.py.
    monkeypatch.setenv("COGNIA_ENTORNO_PROMPT", "0")
    from cognia.system_prompt import _CONDUCTA_COMPLETA, _IDENTIDAD
    hoy = "\n\n".join([_IDENTIDAD.strip(), _CONDUCTA_COMPLETA.strip(),
                       mp._ROL_AGENTE_NATIVO.strip()])
    assert mp.system_agente_nativo() == hoy
    assert mp.system_agente_nativo(None) == hoy
    assert mp.system_agente_nativo(_perfil()) == hoy
    con = mp.system_agente_nativo(_perfil(harness={"sufijo_prompt": "  Usa rutas relativas.  "}))
    assert con == hoy + "\n\nUsa rutas relativas."


def test_p8_harness_de_valida_la_forma_y_las_familias_de_la_casa_no_declaran():
    assert all(mp.harness_de(cfg) == {} for cfg in mp._FAMILIAS_NATIVAS.values())
    assert mp.harness_de({"harness": {"renombres": "path", "defaults": [],
                                      "sufijo_prompt": 3}}) == {}
    assert mp.harness_de({"harness": {"renombres": {"a": "b", "": "c", "d": 1},
                                      "defaults": {"t": {"x": 1}, "u": {}},
                                      "sufijo_prompt": " S "}}) == \
        {"renombres": {"a": "b"}, "defaults": {"t": {"x": 1}}, "sufijo_prompt": "S"}


def test_p8_familia_del_usuario_con_harness_llega_al_perfil(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIA_HOME", str(tmp_path))
    monkeypatch.delenv("COGNIA_AGENT_LEGACY", raising=False)
    monkeypatch.delenv("COGNIA_AGENT_TOOLS", raising=False)
    (tmp_path / "perfiles_modelo.json").write_text(json.dumps({
        "fakefam": {"temperature": 0.5, "top_p": 0.9,
                    "harness": {"renombres": {"file_path": "path"},
                                "sufijo_prompt": "SUFIJO"}}}), encoding="utf-8")
    import cognia.backend_activo as ba
    from cognia.agent import capacidad
    monkeypatch.setattr(ba, "props", lambda url, forzar=False: {
        "modelo": "FakeFam-7B-Q4.gguf", "n_ctx": 8192, "puerto": 8080})
    monkeypatch.setattr(capacidad, "soporta_tools", lambda url, forzar=False: True)
    monkeypatch.setattr(capacidad, "medicion", lambda url: {"motivo": "stub"})
    p = mp.perfil_del_agente()
    assert p["tools"] == "nativo" and p["familia"] == "fakefam"
    assert p["harness"] == {"renombres": {"file_path": "path"},
                            "sufijo_prompt": "SUFIJO"}
    assert p["temperature"] == 0.5
    assert mp.system_agente_nativo(p).endswith("\n\nSUFIJO")
    # Una familia de la casa no lleva la clave: perfil byte-identico a hoy.
    monkeypatch.setattr(ba, "props", lambda url, forzar=False: {
        "modelo": "gpt-oss-20b-MXFP4.gguf", "n_ctx": 8192, "puerto": 8080})
    assert "harness" not in mp.perfil_del_agente()
