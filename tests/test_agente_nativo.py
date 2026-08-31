"""
Tests del nucleo nativo del agente (WP1, obra 2026-08-09).

Regresiones que cubren:
- El baseline 2026-08-09: el modelo respondia bien en harmony y el loop
  ACCION:/regex lo contaba como "2 pasos sin ACCION valida" -> cierre por
  prosa degradado. bucle_nativo consume message.tool_calls y termina cuando
  no hay tool calls (fin natural) — sin marco ACCION.
- La leccion 'presupuesto-tokens-razonamiento': ningun max_tokens del camino
  agente por debajo de MIN_TOKENS_RAZONADOR con perfil razonador.
- El contrafactual del plan: COGNIA_AGENT_LEGACY=1 fuerza el perfil texto
  aunque el modelo servido sea nativo.
- A6: los auxiliares LLM (budget-rating, wants_more_steps) apagados por
  defecto (solo heuristica; env para reactivar).

Sin modelo real: completar se simula con dobles deterministas. El e2e real
contra :8080 es la verificacion de cierre del paquete (no vive en pytest).
"""
import os

import pytest

from cognia.agent import loop as loop_mod
from cognia.agent.chat_client import (RespuestaChat, ToolCall,
                                      mensaje_assistant, mensaje_tool)
from cognia.agent.model_profiles import (MIN_TOKENS_RAZONADOR,
                                         perfil_del_agente,
                                         verificar_arranque)
from cognia.agent.tool_schemas import args_legacy, schemas_para


# ── model_profiles ──────────────────────────────────────────────────────────

def _con_props(monkeypatch, modelo, n_ctx=16384, sonda=True):
    """Simula backend_activo.props Y la SONDA de capacidad, sin red.

    Stubear solo `props` dejo de alcanzar el 2026-08-13: desde el commit
    6db4b53c el regimen (nativo/texto) lo decide `capacidad.soporta_tools`,
    que hace un POST REAL. En una maquina con el llama-server vivo en la url
    por defecto la sonda contestaba True y estos tests median la maquina, no
    el codigo (test_perfil_texto_* rojos con 'nativo' != 'texto'). `sonda` es
    el veredicto que se le inyecta.
    """
    import cognia.backend_activo as ba
    from cognia.agent import capacidad
    monkeypatch.setattr(ba, "props",
                        lambda url, forzar=False: {"modelo": modelo,
                                                   "n_ctx": n_ctx,
                                                   "puerto": 8080})
    monkeypatch.setattr(capacidad, "soporta_tools",
                        lambda url, forzar=False: sonda)
    monkeypatch.setattr(capacidad, "medicion",
                        lambda url: {"nativo": sonda, "motivo": "sonda stub"})


def test_perfil_nativo_para_gpt_oss(monkeypatch):
    monkeypatch.delenv("COGNIA_AGENT_LEGACY", raising=False)
    monkeypatch.delenv("COGNIA_AGENT_TOOLS", raising=False)
    _con_props(monkeypatch, "gpt-oss-20b-MXFP4.gguf")
    p = perfil_del_agente()
    assert p["tools"] == "nativo"
    assert p["temperature"] == 1.0 and p["top_p"] == 1.0
    assert p["max_tokens"] >= MIN_TOKENS_RAZONADOR
    assert verificar_arranque(p) == []


def test_perfil_nativo_para_qwythos(monkeypatch):
    # Cerebro principal desde 2026-08-09: Qwythos hace tool-calling nativo
    # (verificado a mano). Sampling Qwen (0.7/0.8), NO el 1.0/1.0 de harmony,
    # y sin reasoning_effort (no es harmony: lo aceptaba pero era no-op).
    monkeypatch.delenv("COGNIA_AGENT_LEGACY", raising=False)
    monkeypatch.delenv("COGNIA_AGENT_TOOLS", raising=False)
    monkeypatch.delenv("COGNIA_REASONING_EFFORT", raising=False)
    _con_props(monkeypatch,
               "Huihui-Qwythos-9B-Claude-Mythos-5-1M-abliterated-Q4_K.gguf")
    p = perfil_del_agente()
    assert p["tools"] == "nativo"
    assert p["temperature"] == 0.7 and p["top_p"] == 0.8
    assert p["reasoning_effort"] == ""       # familia sin effort de harmony
    assert p["max_tokens"] >= MIN_TOKENS_RAZONADOR
    assert verificar_arranque(p) == []


def test_gpt_oss_conserva_su_effort_de_harmony(monkeypatch):
    # El cambio de familia NO toca a gpt-oss: sigue con effort low por defecto.
    monkeypatch.delenv("COGNIA_AGENT_LEGACY", raising=False)
    monkeypatch.delenv("COGNIA_AGENT_TOOLS", raising=False)
    monkeypatch.delenv("COGNIA_REASONING_EFFORT", raising=False)
    _con_props(monkeypatch, "gpt-oss-20b-MXFP4.gguf")
    assert perfil_del_agente()["reasoning_effort"] == "low"


def test_perfil_texto_para_modelo_desconocido(monkeypatch):
    # Desde 6db4b53c el NOMBRE ya no decide: manda la sonda. Un modelo fuera de
    # las tablas cuyo server no parsea tool_calls tiene que caer a texto.
    monkeypatch.delenv("COGNIA_AGENT_LEGACY", raising=False)
    monkeypatch.delenv("COGNIA_AGENT_TOOLS", raising=False)
    _con_props(monkeypatch, "qwen2.5-coder-3b-instruct-q4.gguf", sonda=False)
    assert perfil_del_agente()["tools"] == "texto"


def test_perfil_texto_sin_backend(monkeypatch):
    # Sin backend, la sonda REAL no alcanza a nadie y devuelve False (medido:
    # capacidad.soporta_tools('http://127.0.0.1:9') -> False en ~2s). Se stubea
    # para que el test no dependa de que la maquina tenga un server vivo.
    monkeypatch.delenv("COGNIA_AGENT_LEGACY", raising=False)
    monkeypatch.delenv("COGNIA_AGENT_TOOLS", raising=False)
    import cognia.backend_activo as ba
    from cognia.agent import capacidad
    monkeypatch.setattr(ba, "props", lambda url, forzar=False: {})
    monkeypatch.setattr(capacidad, "soporta_tools",
                        lambda url, forzar=False: False)
    assert perfil_del_agente()["tools"] == "texto"


def test_contrafactual_legacy_forzado(monkeypatch):
    """El contrafactual del plan: legacy forzado sobre el 20B apaga el nativo."""
    _con_props(monkeypatch, "gpt-oss-20b-MXFP4.gguf")
    monkeypatch.setenv("COGNIA_AGENT_LEGACY", "1")
    assert perfil_del_agente()["tools"] == "texto"


def test_verificar_arranque_grita_presupuesto_chico():
    avisos = verificar_arranque({"tools": "nativo", "max_tokens": 256,
                                 "modelo": "gpt-oss-20b.gguf"})
    assert any("max_tokens" in a for a in avisos)


# ── tool_schemas ────────────────────────────────────────────────────────────

def test_schemas_formato_openai_y_sin_responder():
    schemas = schemas_para()
    assert schemas, "el registry TOOLS deberia producir schemas"
    nombres = set()
    for s in schemas:
        assert s["type"] == "function"
        fn = s["function"]
        assert fn["name"] and fn["parameters"]["type"] == "object"
        nombres.add(fn["name"])
    # responder NO es tool en regimen nativo: el cierre es prosa sin calls.
    assert "responder" not in nombres
    assert "escribir_archivo" in nombres


def test_schemas_respeta_allowed():
    permitidas = {"leer_archivo", "listar"}
    nombres = {s["function"]["name"] for s in schemas_para(permitidas)}
    assert nombres == permitidas


def test_args_legacy_reconstruye_formato_pipe():
    assert args_legacy("escribir_archivo",
                       {"path": "hola.txt", "contenido": "hola mundo"}) \
        == "hola.txt | hola mundo"
    bloque = args_legacy("editar_archivo", {"path": "m.py", "buscar": "a=1",
                                            "reemplazar": "a=2"})
    assert bloque.startswith("m.py | <<<<<<< SEARCH\na=1\n=======\na=2")
    assert args_legacy("ejecutar", {"comando": "python x.py"}) == "python x.py"
    assert args_legacy("fecha", {}) == ""
    # generico: pasa 'args' tal cual; dict raro no lanza
    assert args_legacy("cuaderno", {"args": "consultar tema"}) == "consultar tema"
    assert args_legacy("desconocida", {"a": "x", "b": "y"}) == "x | y"


# ── chat_client: presupuesto del razonador y mensajes ───────────────────────

def test_completar_clampa_max_tokens_razonador(monkeypatch):
    """Regresion 'presupuesto-tokens-razonamiento': un max_tokens chico en el
    camino del agente se clampa a MIN_TOKENS_RAZONADOR antes de salir."""
    import json as _json
    import urllib.request as _url
    capturado = {}

    class _Resp:
        def read(self):
            return _json.dumps({"choices": [{"finish_reason": "stop",
                                             "message": {"content": "ok"}}],
                                "usage": {}}).encode()
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    def _fake_urlopen(req, timeout=None):
        capturado.update(_json.loads(req.data.decode("utf-8")))
        return _Resp()

    monkeypatch.setattr(_url, "urlopen", _fake_urlopen)
    from cognia.agent.chat_client import completar
    resp = completar([{"role": "user", "content": "hola"}], max_tokens=16,
                     razonador=True, url="http://127.0.0.1:9")
    assert resp.ok and resp.texto == "ok"
    assert capturado["max_tokens"] >= MIN_TOKENS_RAZONADOR


def test_mensaje_assistant_preserva_cot_y_calls():
    resp = RespuestaChat(
        texto="", reasoning_content="pienso...",
        tool_calls=[ToolCall(id="abc", nombre="listar",
                             argumentos={"directorio": "."},
                             argumentos_crudos='{"directorio":"."}')])
    m = mensaje_assistant(resp)
    assert m["role"] == "assistant"
    assert m["reasoning_content"] == "pienso..."
    assert m["tool_calls"][0]["function"]["arguments"] == '{"directorio":"."}'
    t = mensaje_tool("abc", "RESULTADO listar: x")
    assert t == {"role": "tool", "tool_call_id": "abc",
                 "content": "RESULTADO listar: x"}


# ── bucle_nativo (la regresion del baseline) ────────────────────────────────

def _perfil_test():
    return {"nombre": "razonador_nativo", "modelo": "gpt-oss-20b.gguf",
            "url": "http://127.0.0.1:9", "tools": "nativo", "n_ctx": 16384,
            "temperature": 1.0, "top_p": 1.0, "reasoning_effort": "low",
            "max_tokens": 4096}


def _correr(respuestas, run_tool, max_turns=8, avisos=None, schemas=None):
    """Corre bucle_nativo con un `completar` doble que devuelve la lista
    `respuestas` en orden. `avisos` (lista) recoge lo que el bucle imprime.
    `schemas` se puede forzar a [] para el caso "no se ofrecio ninguna tool"."""
    it = iter(respuestas)

    def _completar(mensajes, tools=None, **kw):
        return next(it)

    def _print(msg, *a, **k):
        if avisos is not None:
            avisos.append(str(msg))

    history, trace = ["TAREA: crea hola.txt con 'hola mundo'"], []
    out = loop_mod.bucle_nativo(
        "crea hola.txt", "sos el agente", _completar,
        schemas_para() if schemas is None else schemas,
        args_legacy, mensaje_assistant, mensaje_tool, run_tool, {},
        _perfil_test(), history, trace, _print, max_turns)
    return out, history, trace


def test_bucle_nativo_tool_call_y_fin_natural():
    """El caso del baseline: tool call bien formado -> se EJECUTA (no '2
    pasos sin ACCION valida'), y la respuesta sin tool calls cierra."""
    ejecutadas = []

    def _run_tool(name, args, ctx):
        ejecutadas.append((name, args))
        return f"RESULTADO {name}: OK (10 chars)"

    r1 = RespuestaChat(
        texto="", finish_reason="tool_calls",
        usage={"completion_tokens": 50, "prompt_tokens": 100},
        tool_calls=[ToolCall(id="t1", nombre="escribir_archivo",
                             argumentos={"path": "hola.txt",
                                         "contenido": "hola mundo"},
                             argumentos_crudos="{}")])
    r2 = RespuestaChat(texto="Listo: hola.txt creado.", finish_reason="stop",
                       usage={"completion_tokens": 10, "prompt_tokens": 200})
    out, history, trace = _correr([r1, r2], _run_tool)
    assert ejecutadas == [("escribir_archivo", "hola.txt | hola mundo")]
    assert out["ok"] and out["texto"].startswith("Listo: hola.txt creado.")
    # El cierre lleva ademas el bloque ENTREGA (2026-08-31): lo que quedo EN
    # DISCO. Aqui el `run_tool` es un doble que no escribe nada, asi que la
    # entrega dice justamente eso — el modelo declaro un fichero que no esta.
    assert "ENTREGA" in out["texto"] and "hola.txt" in out["texto"]
    assert out["pasos"] == 2
    assert out["tokens"] == 60           # usage REAL, no len//4
    assert history[-1] == "RESULTADO escribir_archivo: OK (10 chars)"
    assert trace[0]["ok"] is True


def test_bucle_nativo_error_de_server_degrada_con_causa():
    """Un 503 es TRANSITORIO (llama-server contesta 503 mientras carga el
    modelo): desde el arnes Hermes (2026-08-19) se reintenta hasta 2 veces
    antes de degradar, y la vuelta gastada se devuelve al presupuesto porque
    no gasto razonamiento. Por eso el doble tiene que dar 3 respuestas: el
    intento y los dos reintentos. La causa sigue llegando al texto final."""
    err = RespuestaChat(error="HTTP 503 de :9")
    out, _, _ = _correr([err, err, err], lambda *a: "no llega")
    assert not out["ok"]
    assert "HTTP 503" in out["texto"]
    assert out["razon"] == "error_backend"


def test_bucle_nativo_error_no_reintentable_no_gasta_reintentos():
    """El otro lado de la moneda: un contexto excedido NO se reintenta (la
    misma peticion da el mismo error, mas caro). Una sola respuesta basta."""
    out, _, _ = _correr(
        [RespuestaChat(error="HTTP 400: the request exceeds the available "
                             "context size, try increasing it")],
        lambda *a: "no llega")
    assert not out["ok"]
    assert "context" in out["texto"]
    assert out["razon"] == "error_backend"


def test_bucle_nativo_estancamiento_corta_honesto():
    """El agente atascado se corta -- pero AVISANDO antes (2026-08-26).

    Antes cortaba register_action a la 3ra repeticion, en seco. Ese corte
    contaba el par (tool,args) en TODA la tarea, sin ventana y sin respetar
    las EXENTAS, y en tareas largas era un falso positivo garantizado: dos
    turnos reales murieron asi el 2026-08-26 ('repite ejecutar', pasos=6 y
    pasos=7). Ahora manda GuardiaBucle, que detecta lo mismo Y MAS
    (ping-pong, ciclos) pero le habla al modelo max_avisos=2 veces antes de
    matar la tarea. Lo que se fija aca: sigue cortando, y ejecuta mas antes
    de rendirse."""
    tc = ToolCall(id="t", nombre="listar", argumentos={"directorio": "."},
                  argumentos_crudos="{}")
    paso = RespuestaChat(texto="", finish_reason="tool_calls",
                         usage={}, tool_calls=[tc])
    out, _, trace = _correr([paso] * 8,
                            lambda n, a, c: "RESULTADO listar: x")
    assert not out["ok"]
    assert "bucle" in out["texto"].lower(), out["texto"]
    # Corta de verdad: no se comio las 8 vueltas que se le ofrecieron.
    assert 2 <= len(trace) <= 6, len(trace)


def test_las_tools_que_se_repiten_por_diseno_no_cortan_la_tarea():
    """`tests`, `ver_salida` y `procesos` son EXENTAS: su trabajo ES
    repetirse (correr la suite tras cada arreglo, seguir un proceso de
    fondo). register_action las contaba igual y mataba la tarea a la 3ra.

    Es el bucle de desarrollo de cualquier cosa larga -- y por eso estaba en
    la lista de exentas de guardia_bucle.py desde el principio, sin que el
    corte del bucle nativo la mirara."""
    for tool in ("tests", "ver_salida", "procesos"):
        tc = ToolCall(id="t", nombre=tool, argumentos={"x": "1"},
                      argumentos_crudos="{}")
        repite = RespuestaChat(texto="", finish_reason="tool_calls",
                               usage={}, tool_calls=[tc])
        fin = RespuestaChat(texto="Listo.", finish_reason="stop", usage={})
        # 4 repeticiones y no 6: con 6 corta el gobernador por progreso
        # (umbral_arranque=6 vueltas sin un avance verificado), que es otra
        # guarda y es correcta -- correr la suite seis veces sin tocar nada
        # SI es estar atascado. Lo que se mide aca es que el corte por
        # repeticion ya no dispara a la 3ra.
        out, _, trace = _correr([repite] * 4 + [fin],
                                lambda n, a, c: f"RESULTADO {n}: ok",
                                max_turns=8)
        assert out["ok"], f"{tool}: {out['texto']}"
        assert len(trace) == 4, f"{tool}: se ejecutaron {len(trace)} de 4"


def test_bucle_nativo_presupuesto_agotado_cierra_con_evidencia(monkeypatch):
    # 2026-08-30: por defecto el techo ya no es fijo -- se AMPLIA mientras el
    # gobernador diga que la corrida esta sana (ver
    # test_arnes_ampliacion_pasos.py), asi que la rama de agotamiento solo se
    # alcanza con el interruptor apagado o al llegar al techo duro. Lo que se
    # mide aqui es esa rama: que cierra CON evidencia y no con un parentesis
    # vacio.
    monkeypatch.setenv("COGNIA_TAREAS_LARGAS", "0")
    tc = ToolCall(id="t", nombre="ejecutar", argumentos={"comando": "x"},
                  argumentos_crudos="{}")
    pasos = [RespuestaChat(texto="", finish_reason="tool_calls", usage={},
                           tool_calls=[ToolCall(id=f"t{i}", nombre="ejecutar",
                                                argumentos={"comando": f"x{i}"},
                                                argumentos_crudos="{}")])
             for i in range(3)]
    out, _, _ = _correr(pasos, lambda n, a, c: f"RESULTADO ejecutar: ok {a}",
                        max_turns=3)
    assert "presupuesto de 3 pasos agotado" in out["texto"]
    assert "RESULTADO ejecutar" in out["texto"]   # evidencia, no volcado vacio


# ── A3-bucle: el cierre en falso del regimen nativo (2026-08-13) ────────────
# Tres defectos del MISMO bucle, medidos leyendo el codigo y reproducidos aca
# antes de tocarlo. Los tres se ven igual desde afuera ("la tarea salio ok" con
# nada util adentro), que es la firma de la degradacion silenciosa del repo.

def test_cierre_vacio_con_reasoning_no_se_marca_ok():
    """(1) El razonador emitio SOLO reasoning_content: chat_client devuelve
    texto='' (content ausente) y el bucle lo tomaba como FIN NATURAL ->
    {'texto': '', 'ok': True}. Una tarea sin una sola letra de respuesta no es
    una tarea cumplida: se cae al reasoning con aviso, y ok=False."""
    avisos = []
    r1 = RespuestaChat(texto="", finish_reason="stop",
                       reasoning_content="El usuario pide crear hola.txt. "
                                         "Deberia usar escribir_archivo.",
                       usage={"completion_tokens": 30, "prompt_tokens": 100})
    out, _, _ = _correr([r1], lambda *a: "no llega", avisos=avisos)
    assert out["texto"], "no se puede devolver texto vacio como respuesta final"
    assert out["ok"] is False, "cierre sin texto NO es una tarea cumplida"
    assert "hola.txt" in out["texto"]      # se rescato el razonamiento
    assert any("vac" in a for a in avisos), avisos


def test_cierre_vacio_sin_nada_que_rescatar_no_miente():
    """Sin texto Y sin reasoning tampoco hay cierre valido: el bucle lo dice
    en vez de devolver la cadena vacia con ok=True."""
    r1 = RespuestaChat(texto="", finish_reason="stop", usage={})
    out, _, _ = _correr([r1], lambda *a: "no llega")
    assert out["ok"] is False
    assert out["texto"] and "vac" in out["texto"]


def test_guard_de_sospecha_cierra_sin_usar_herramientas():
    """(2) Cerrar en el PASO 1 sin haber llamado ninguna tool es el sintoma
    exacto de un server que no parsea tool_calls (llama-server sin --jinja):
    el modelo "responde" y el bucle lo da por bueno en silencio. Ahora se
    declara por print_fn."""
    avisos = []
    r1 = RespuestaChat(texto="Listo, ya cree el archivo.", finish_reason="stop",
                       usage={"completion_tokens": 12, "prompt_tokens": 100})
    out, _, _ = _correr([r1], lambda *a: "no llega", avisos=avisos)
    assert out["ok"] is True and out["texto"]      # es un cierre valido...
    assert any("sin usar herramientas" in a for a in avisos), avisos


def test_guard_de_sospecha_no_grita_si_uso_tools():
    """El guard NO puede ensuciar el camino feliz: si hubo tool calls, callado."""
    avisos = []
    r1 = RespuestaChat(texto="", finish_reason="tool_calls", usage={},
                       tool_calls=[ToolCall(id="t1", nombre="listar",
                                            argumentos={"directorio": "."},
                                            argumentos_crudos="{}")])
    r2 = RespuestaChat(texto="Listo.", finish_reason="stop", usage={})
    _correr([r1, r2], lambda n, a, c: "RESULTADO listar: x", avisos=avisos)
    assert not any("sin usar herramientas" in a for a in avisos), avisos


def test_guard_de_sospecha_callado_si_no_se_ofrecieron_tools():
    """La tercera pata de la condicion, hasta hoy sin test: sin tools ofrecidas
    (schemas=[]) cerrar en el paso 1 es lo NORMAL — pedirle al usuario que
    'sospeche del tool-calling del server' seria ruido puro. Este test falla si
    alguien deja el guard en `if pasos == 1:` pelado."""
    avisos = []
    r1 = RespuestaChat(texto="Hola, no necesito herramientas.",
                       finish_reason="stop", usage={})
    out, _, _ = _correr([r1], lambda *a: "no llega", avisos=avisos, schemas=[])
    assert out["ok"] is True and out["texto"]
    assert not any("sin usar herramientas" in a for a in avisos), avisos


def test_llegar_al_paso_2_exige_haber_ejecutado_una_tool():
    """Fija la INVARIANTE que justifica que el guard mire `pasos == 1` y no un
    contador de tools (el `tools_ejecutadas` de la primera version de este fix
    era codigo muerto: en el paso 1 valia 0 SIEMPRE). Las dos unicas salidas de
    la rama de tool_calls son: ejecutar >=1 tool y seguir al paso 2, o cortar
    por estancamiento sin llegar al 2. Aca se mide la primera; la segunda la
    mide test_bucle_nativo_estancamiento_corta_honesto (out['pasos'] == 1)."""
    corridas = []
    r1 = RespuestaChat(texto="", finish_reason="tool_calls", usage={},
                       tool_calls=[ToolCall(id="t1", nombre="listar",
                                            argumentos={"directorio": "."},
                                            argumentos_crudos="{}")])
    r2 = RespuestaChat(texto="Listo.", finish_reason="stop", usage={})

    def _run_tool(n, a, c):
        corridas.append(n)
        return "RESULTADO listar: x"

    out, _, trace = _correr([r1, r2], _run_tool)
    assert out["pasos"] == 2 and len(corridas) == 1     # paso 2 => hubo tool
    assert len(trace) == 1

    # Y el corte por estancamiento (la otra salida) no pasa del paso 1.
    tc = ToolCall(id="t", nombre="listar", argumentos={"directorio": "."},
                  argumentos_crudos="{}")
    # Seis calls repetidas en el MISMO paso y no tres: desde el 2026-08-26
    # el corte lo da GuardiaBucle, que avisa dos veces antes de bloquear.
    rep = RespuestaChat(texto="", finish_reason="tool_calls", usage={},
                        tool_calls=[tc] * 6)
    out2, _, _ = _correr([rep], lambda n, a, c: "RESULTADO listar: x")
    assert out2["pasos"] == 1 and "bucle" in out2["texto"].lower(), out2["texto"]


def _chars_totales(mensajes):
    """Todo lo que VIAJA al server: content + reasoning_content de cada turno.
    _recortar_mensajes solo miraba content, y por eso el CoT reinyectado por
    chat_client.mensaje_assistant era invisible al presupuesto."""
    return sum(len(str(m.get("content") or ""))
               + len(str(m.get("reasoning_content") or ""))
               for m in mensajes)


def test_recorte_incluye_el_reasoning_de_los_assistant_viejos():
    """(3) 20 turnos assistant con 5k chars de CoT cada uno: hoy el recorte
    devolvia 0 (ningun turno role='tool') y el prompt reventaba n_ctx en
    silencio con AGENT_HARD_CAP=40 pasos."""
    mensajes = [{"role": "system", "content": "S" * 5000},
                {"role": "user", "content": "TAREA: " + "U" * 5000}]
    for i in range(20):
        mensajes.append({"role": "assistant", "content": f"paso {i}",
                         "reasoning_content": "R" * 5000})
    antes = _chars_totales(mensajes)
    liberados = loop_mod._recortar_mensajes(mensajes, 16384, 15000)
    assert liberados > 0, "el CoT acumulado tiene que entrar al recorte"
    assert _chars_totales(mensajes) < antes
    # Intocables por diseno: el system y el user del objetivo.
    assert len(mensajes[0]["content"]) == 5000
    assert len(mensajes[1]["content"]) == 5007
    # Se recorta por los MAS VIEJOS: el ultimo turno conserva su razonamiento.
    assert len(mensajes[-1].get("reasoning_content") or "") == 5000


def test_recorte_bajo_umbral_no_toca_nada():
    """Sin presion de contexto no se recorta: el CoT reciente es util."""
    mensajes = [{"role": "assistant", "content": "x",
                 "reasoning_content": "R" * 5000}]
    assert loop_mod._recortar_mensajes(mensajes, 16384, 100) == 0
    assert len(mensajes[0]["reasoning_content"]) == 5000


def test_recorte_sigue_cubriendo_los_turnos_tool():
    """El comportamiento viejo (turnos tool grandes) no se pierde."""
    mensajes = [{"role": "tool", "tool_call_id": "t", "content": "T" * 5000}]
    liberados = loop_mod._recortar_mensajes(mensajes, 16384, 15000)
    assert liberados > 4000
    assert "recortado por presupuesto" in mensajes[0]["content"]


def test_recorte_iterado_termina():
    """El llamador itera mientras `liberados` sea >0: una segunda pasada sobre
    lo ya recortado tiene que devolver 0 (si no, bucle infinito en el paso)."""
    mensajes = [{"role": "assistant", "content": "c",
                 "reasoning_content": "R" * 5000} for _ in range(4)]
    total = 0
    for _ in range(20):
        lib = loop_mod._recortar_mensajes(mensajes, 16384, 15000)
        total += lib
        if not lib:
            break
    else:
        raise AssertionError("_recortar_mensajes no converge a 0")
    assert total > 0


# ── A6: auxiliares LLM apagados por defecto ─────────────────────────────────

class _OrchQueNoDebeInferir:
    def infer(self, *a, **k):
        raise AssertionError("el auxiliar LLM no debe llamarse sin el env")


def test_estimate_step_budget_sin_llm_por_defecto(monkeypatch):
    monkeypatch.delenv("COGNIA_BUDGET_LLM", raising=False)
    n = loop_mod.estimate_step_budget("tarea cualquiera de largo medio",
                                      _OrchQueNoDebeInferir())
    assert 1 <= n <= loop_mod.AGENT_HARD_CAP


def test_wants_more_steps_apagado_por_defecto(monkeypatch):
    monkeypatch.delenv("COGNIA_WANTS_MORE", raising=False)
    assert loop_mod.wants_more_steps("t", "r", _OrchQueNoDebeInferir()) == 0
