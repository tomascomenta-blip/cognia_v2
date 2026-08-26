# -*- coding: utf-8 -*-
"""
tests/test_hermes_errores.py
============================
Casos con textos de error REALES de llama-server, Ollama y OpenAI-compatibles.

De donde salio cada texto:
  * `exceed_context_size`      -> node/llama_backend.py:113, :699 y :1354 (la
                                  averia A/B medida el 2026-08-17).
  * `errno 111` / refused      -> app/routes/chat.py:81, la lista de strings a
                                  mano que este modulo reemplaza.
  * `<urlopen error timed out>`-> los WARNING de arbitro_visual en los .log del
                                  repo (2026-07-27).
  * `No inference backend available` -> cognia/cli.py:12095.
  * Anthropic / DashScope / vLLM -> hermes-agent/agent/model_metadata.py:1439,
                                  :1470 y :1536, los ejemplos verbatim que su
                                  parser de output-cap documenta.

Nada aqui necesita modelo ni red: el modulo es texto -> dict.
"""

import json

import pytest

from cognia.hermes.errores_backend import RAZONES, accion_sugerida, clasificar


# ── 1..10: textos reales, uno por razon ─────────────────────────────────

def test_llama_server_exceed_context_size_comprime():
    """El 400 de llama-server que mataba las generaciones largas."""
    crudo = ('HTTP Error 400: Bad Request {"error":{"code":400,"message":'
             '"the request exceeds the available context size. try increasing '
             'the context size or enable context shift",'
             '"type":"exceed_context_size"}}')
    d = clasificar(crudo)
    assert d["razon"] == "contexto_excedido"
    assert d["comprimir_contexto"] is True
    assert d["cambiar_backend"] is False


def test_connection_refused_windows_es_servidor_caido():
    crudo = ("<urlopen error [WinError 10061] No connection could be made "
             "because the target machine actively refused it>")
    d = clasificar(crudo)
    assert d["razon"] == "servidor_caido"
    assert d["cambiar_backend"] is True
    assert d["esperar_s"] > 0


def test_errno_111_es_servidor_caido():
    """El caso que app/routes/chat.py:81 resuelve hoy con cinco strings."""
    d = clasificar("URLError: <urlopen error [Errno 111] Connection refused>")
    assert d["razon"] == "servidor_caido"


def test_urlopen_timed_out_es_timeout_no_servidor_caido():
    """El texto real de los .log: 'urlopen error' y 'timed out' juntos.

    Si gana 'urlopen error' se diagnostica un server muerto que en realidad
    esta vivo y ocupado (--parallel 1). Por eso el timeout va primero.
    """
    d = clasificar("<urlopen error timed out>")
    assert d["razon"] == "timeout"
    assert d["reintentable"] is True
    assert d["cambiar_backend"] is False


def test_ollama_modelo_no_encontrado_no_es_reintentable():
    crudo = ('HTTP Error 404: Not Found {"error":"model '
             '\'qwen2.5-coder\' not found, try pulling it first"}')
    d = clasificar(crudo, {"modelo": "qwen2.5-coder"})
    assert d["razon"] == "modelo_no_encontrado"
    assert d["reintentable"] is False
    assert d["cambiar_backend"] is True


def test_ollama_memoria_insuficiente():
    crudo = ('HTTP Error 500: Internal Server Error {"error":"model requires '
             'more system memory (9.1 GiB) than is available (5.4 GiB)"}')
    d = clasificar(crudo)
    assert d["razon"] == "memoria_insuficiente"
    assert d["reintentable"] is False
    assert d["comprimir_contexto"] is False


def test_openai_context_length_exceeded():
    crudo = ("This model's maximum context length is 8192 tokens. However, "
             "your messages resulted in 8500 tokens. Please reduce the length "
             "of the messages.")
    d = clasificar(crudo, {"status": 400})
    assert d["razon"] == "contexto_excedido"
    assert d["comprimir_contexto"] is True


def test_dashscope_range_of_max_tokens_es_tope_salida_y_no_comprime():
    """Hermes #55546: comprimir reenvia el mismo max_tokens y muere en bucle."""
    d = clasificar("Range of max_tokens should be [1, 65536]")
    assert d["razon"] == "tope_salida"
    assert d["comprimir_contexto"] is False
    assert d["reintentable"] is True


def test_anthropic_available_tokens_es_tope_salida():
    crudo = ("max_tokens: 32768 > context_window: 200000 - input_tokens: "
             "190000 = available_tokens: 10000")
    d = clasificar(crudo)
    assert d["razon"] == "tope_salida"
    assert d["comprimir_contexto"] is False


def test_vllm_input_gigante_gana_contexto_aunque_hable_de_salida():
    """La guarda de Hermes: si el INPUT tambien desborda, se comprime."""
    crudo = ("This model's maximum context length is 131072 tokens. However, "
             "you requested 65536 output tokens and your prompt contains at "
             "least 65537 input tokens, for a total of at least 131073 tokens. "
             "Please reduce the length of the input prompt or the number of "
             "requested output tokens.")
    d = clasificar(crudo)
    assert d["razon"] == "contexto_excedido"
    assert d["comprimir_contexto"] is True


def test_openai_rate_limit_lee_la_espera_declarada():
    crudo = ("Rate limit reached for gpt-4 in organization org-abc123 on "
             "tokens per min. Limit: 40000 / min. Please try again in 1.5s. "
             "Contact us through our help center if you continue to have "
             "issues.")
    d = clasificar(crudo, {"status": 429})
    assert d["razon"] == "rate_limit"
    assert d["esperar_s"] == pytest.approx(1.5)


def test_json_invalido_por_tipo_de_excepcion():
    try:
        json.loads("")
    except json.JSONDecodeError as exc:
        d = clasificar(exc)
    assert d["razon"] == "json_invalido"
    assert d["reintentable"] is True
    assert d["comprimir_contexto"] is False


def test_sin_backend_de_cognia_es_servidor_caido():
    """cli.py:12095 recibe este aviso como TEXTO, no como excepcion."""
    d = clasificar("No inference backend available")
    assert d["razon"] == "servidor_caido"
    assert "flota arrancar" in accion_sugerida(d)


def test_llama_server_cargando_es_servidor_caido_reintentable():
    d = clasificar('{"error":{"code":503,"message":"Loading model",'
                   '"type":"unavailable_error"}}')
    assert d["razon"] == "servidor_caido"
    assert d["reintentable"] is True


def test_cancelado_no_es_fallo_de_backend():
    d = clasificar(KeyboardInterrupt())
    assert d["razon"] == "cancelado"
    assert d["reintentable"] is False
    assert d["cambiar_backend"] is False


# ── La separacion input/output ──────────────────────────────────────────

def test_respuesta_vacia_con_finish_length_NO_comprime():
    """LA prueba que motiva la razon separada.

    Medido en cognia/llm_local.py: 6 de 6 sondas con gpt-oss murieron en
    finish=length con 22-53k chars de razonamiento y contenido 0. Comprimir el
    INPUT no devuelve ni un token de salida; lo que hay que mover es max_tokens
    o el reasoning_effort. Es la misma separacion que Hermes documenta en
    model_metadata.py:1550.
    """
    d = clasificar("", {"finish_reason": "length"})
    assert d["razon"] == "respuesta_vacia"
    assert d["comprimir_contexto"] is False
    assert d["cambiar_backend"] is False
    assert "max_tokens" in d["mensaje_humano"]


def test_respuesta_vacia_sin_finish_reason():
    d = clasificar(None, {"respuesta": "   "})
    assert d["razon"] == "respuesta_vacia"
    assert d["comprimir_contexto"] is False


def test_respuesta_truncada_con_finish_length_es_tope_salida():
    d = clasificar("", {"respuesta": "def suma(a, b):\n    return a +",
                        "finish_reason": "length"})
    assert d["razon"] == "tope_salida"
    assert d["comprimir_contexto"] is False


def test_aviso_de_respuesta_vacia_del_proveedor_no_dispara_compresion():
    """Hermes error_classifier.py:475: el aviso menciona max_tokens."""
    d = clasificar("Provider returned an empty response (very low max_tokens?)")
    assert d["razon"] == "respuesta_vacia"
    assert d["comprimir_contexto"] is False


# ── Contrato del Diagnostico ────────────────────────────────────────────

_CLAVES = {"razon", "reintentable", "comprimir_contexto", "cambiar_backend",
           "esperar_s", "mensaje_humano"}


@pytest.mark.parametrize("entrada,ctx", [
    ("cualquier cosa", None),
    ("", None),
    (None, None),
    (ValueError("boom"), {"status": 418}),
    ({"no": "soy texto"}, {"intento": 2}),
    (object(), {"finish_reason": "stop"}),
])
def test_clasificar_nunca_lanza_y_devuelve_el_contrato(entrada, ctx):
    d = clasificar(entrada, ctx)
    assert set(d) == _CLAVES
    assert d["razon"] in RAZONES
    assert isinstance(d["reintentable"], bool)
    assert isinstance(d["comprimir_contexto"], bool)
    assert isinstance(d["cambiar_backend"], bool)
    assert isinstance(d["esperar_s"], float)
    assert isinstance(d["mensaje_humano"], str) and d["mensaje_humano"]


def test_texto_no_reconocido_cae_en_desconocido_reintentable():
    d = clasificar("Segmentation fault (core dumped)")
    assert d["razon"] == "desconocido"
    assert d["reintentable"] is True


def test_backoff_exponencial_acotado():
    base = clasificar("connection refused")["esperar_s"]
    con_dos = clasificar("connection refused", {"intento": 2})["esperar_s"]
    assert con_dos == pytest.approx(base * 4)
    assert clasificar("connection refused", {"intento": 20})["esperar_s"] <= 30.0


def test_el_codigo_http_solo_decide_cuando_el_texto_calla():
    """Un 500 pelado es servidor_caido; con cuerpo de ctx gana el cuerpo."""
    assert clasificar("", {"status": 500,
                           "cuerpo": "boom"})["razon"] == "servidor_caido"
    d = clasificar("", {"status": 500,
                        "cuerpo": "the request exceeds the available context size"})
    assert d["razon"] == "contexto_excedido"


# ── accion_sugerida ─────────────────────────────────────────────────────

def test_accion_sugerida_cubre_todas_las_razones_y_es_accionable():
    for razon in RAZONES:
        texto = accion_sugerida({"razon": razon, "esperar_s": 5.0})
        assert isinstance(texto, str) and texto.strip()
        assert len(texto.splitlines()) == 1


def test_accion_sugerida_lleva_el_comando_literal():
    caidos = accion_sugerida(clasificar("connection refused"))
    assert "python -m cognia flota arrancar" in caidos
    tope = accion_sugerida(clasificar("Range of max_tokens should be [1, 65536]"))
    assert "COGNIA_MAX_TOKENS" in tope
    modelo = accion_sugerida(clasificar("model not found, try pulling it first"))
    assert "install-model" in modelo or "ollama pull" in modelo


def test_accion_sugerida_no_lanza_con_basura():
    assert accion_sugerida({}).strip()
    assert accion_sugerida(None).strip()
    assert accion_sugerida({"razon": "inventada"}).strip()


def test_400_sin_cuerpo_no_es_reintentable():
    """llm_local.py:167 tira el cuerpo y solo deja "HTTP 400 en <url>".

    No hay nada que nombrar (queda 'desconocido'), pero repetir la MISMA
    peticion recibe el MISMO 400: el bucle que Hermes llama "request flood".
    """
    d = clasificar("HTTP Error 400: Bad Request", {"status": 400})
    assert d["razon"] == "desconocido"
    assert d["reintentable"] is False


def test_timeout_con_health_ok_sigue_siendo_ocupado():
    """node/llama_backend.py:1053: /health ok + timeout = slot ocupado."""
    d = clasificar("<urlopen error timed out>", {"salud": "ok"})
    assert d["razon"] == "timeout"
    assert d["cambiar_backend"] is False


def test_timeout_con_backend_muerto_es_servidor_caido():
    """MEDIDO 2026-08-18 en esta maquina (Windows 11): un puerto de loopback
    sin nadie escuchando devuelve `TimeoutError: timed out`, NO "connection
    refused" (el firewall descarta el SYN). O sea que la falta de backend llega
    disfrazada de timeout y hay que desempatarla con /health.
    """
    for ctx in ({"salud": "caido"}, {"backend_vivo": False}, {"salud": "cargando"}):
        d = clasificar("<urlopen error timed out>", ctx)
        assert d["razon"] == "servidor_caido", ctx
        assert d["reintentable"] is True
        assert "flota arrancar" in accion_sugerida(d)


# ── Las palancas que el consejo NOMBRA tienen que existir (2026-08-26) ──────

def test_toda_env_var_citada_en_un_consejo_es_una_palanca_viva():
    """Un consejo que nombra una env var muerta es PEOR que no dar consejo.

    Regresion MEDIDA: el consejo de 'timeout' decia
    `set LLAMA_SERVER_TIMEOUT=480`. Esa variable solo la lee
    node/llama_backend.py como espera de ARRANQUE del server, no como
    timeout de peticion, y el camino que produce ese error (chat_client) no
    la mira jamas. El dueno la probaba, no cambiaba nada, y descartaba la
    hipotesis correcta -- que era justamente el presupuesto de la llamada.

    Este test es la leccion convertida en chequeo: para CADA razon, cada
    `set XXX=` del texto tiene que nombrar una variable que ALGUIEN lea, o
    sea que aparezca en el codigo fuera del propio modulo de consejos.

    LO QUE ESTE TEST **NO** PUEDE COMPROBAR, dicho para que nadie se confie:
    que la palanca sea la del camino CORRECTO. LLAMA_SERVER_TIMEOUT existia
    de verdad (node/llama_backend.py la lee), solo que en otro cliente y con
    otro significado. Ese matiz lo fija el test especifico de abajo; este
    caza el caso mas tonto, que es citar un nombre que no existe en ningun
    lado. La deteccion es por NOMBRE y no por `environ.get(...)` porque hay
    palancas leidas indirecto (harness/limites.py::_env_num).
    """
    import re
    from pathlib import Path
    from cognia.hermes.errores_backend import RAZONES, accion_sugerida

    raiz = Path(__file__).resolve().parent.parent
    codigo = []
    for sub in ("cognia", "node"):
        for p in (raiz / sub).rglob("*.py"):
            if p.name == "errores_backend.py":
                continue          # el modulo de los consejos no se cuenta
            try:
                codigo.append(p.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                pass
    codigo = "\n".join(codigo)

    citadas = set()
    for razon in RAZONES:
        texto = accion_sugerida({"razon": razon})
        citadas |= set(re.findall(r"\bset ([A-Z][A-Z0-9_]{3,})=", texto))
    assert citadas, "ningun consejo cita una env var: el test no mide nada"

    muertas = [v for v in sorted(citadas)
               if f'"{v}"' not in codigo and f"'{v}'" not in codigo]
    assert not muertas, f"env vars citadas que nadie lee: {muertas}"


def test_el_consejo_de_timeout_nombra_la_palanca_del_camino_del_agente():
    """La especifica: quien ve este error viene de chat_client."""
    from cognia.hermes.errores_backend import accion_sugerida
    consejo = accion_sugerida({"razon": "timeout"})
    assert "COGNIA_CHAT_TIMEOUT" in consejo, consejo
    assert "LLAMA_SERVER_TIMEOUT" not in consejo, consejo
