"""
llm_local.py — Cliente unico para el LLM local de Cognia.

POR QUE EXISTE: nueve modulos de Cognia tenian hardcodeada la URL de Ollama
(localhost:11434), pero Ollama NO esta instalado en esta maquina. El backend
real es llama-server (~/.cognia/llama/llama-server.exe) sirviendo
qwen2.5-coder-14b en el puerto 8080 con API compatible con OpenAI.

Consecuencia medida el 2026-07-19: TODOS los caminos con LLM de Cognia
degradaban en silencio a su fallback. El planificador de busquedas, el
resumen de investigacion, la generacion de programas y las hipotesis nunca
llamaron a un modelo. No estaban rotos de forma visible: simplemente nunca
hacian su trabajo, que es el peor modo de fallar.

Este modulo detecta el backend disponible en vez de asumirlo. Orden:
  1. COGNIA_LLM_URL, si el dueno la fija a mano
  2. llama-server, API OpenAI (/v1/chat/completions)
  3. Ollama (/api/generate), por si algun dia se instala

Sin dependencias externas: solo stdlib.
"""

import json
import os
import urllib.error
import urllib.request
from typing import Optional

LLAMA_URL_DEFECTO  = "http://127.0.0.1:8080"
OLLAMA_URL_DEFECTO = "http://localhost:11434"

TIMEOUT_SONDEO = 2


def _timeout_gen_defecto() -> int:
    """Timeout de generacion, override por COGNIA_LLM_TIMEOUT (segundos).

    120 s era un tope PLANO que no miraba cuanto se pidio generar. Con
    max_tokens=12000 a ~59 tok/s (medido 2026-08-02 en la 5060 Ti con
    Qwythos-9B) una pagina web entera necesita ~200 s: la generacion moria en
    "[llm] Error: timed out" y el lazo lo leia como "sin backend LLM vivo",
    degradando hasta el 404 de Ollama. node/llama_backend.py ya escalaba su
    timeout con max_tokens (_request_timeout_s); este camino no.
    urlopen(timeout) es de SOCKET, asi que un tope holgado NO ralentiza nada:
    solo deja de matar las generaciones legitimamente largas.
    """
    try:
        return max(30, int(os.environ.get("COGNIA_LLM_TIMEOUT", "").strip() or 120))
    except ValueError:
        return 120


TIMEOUT_GEN = _timeout_gen_defecto()


def timeout_para(max_tokens: int) -> int:
    """Timeout holgado para `max_tokens`: el plano de arriba, o ~4x el tiempo
    estimado a 30 tok/s (piso pesimista de decode), lo que sea mayor."""
    return max(TIMEOUT_GEN, int(max_tokens / 30 * 4) + 60)

# Detalle de la ULTIMA generacion: {'finish_reason': 'stop'|'length'|..., 'tokens': int}.
#
# POR QUE EXISTE: generar() devuelve solo el texto, asi que "la respuesta se
# corto por presupuesto" era INDISTINGUIBLE de "no hay backend" — con un modelo
# de razonamiento y un max_tokens corto, el content vuelve VACIO (se gasto todo
# pensando) y el llamador reportaba "sin backend LLM vivo" teniendo el server
# sano. Otro degradado disfrazado, y encima el que impedia reintentar con mas
# presupuesto: sin este dato no hay forma de saber que ESO era lo que fallaba.
#
# Estado de modulo y no valor de retorno para no cambiar la firma de generar()
# en sus ~40 call sites. Vale porque la generacion aqui es SECUENCIAL; si algun
# dia se paraleliza, esto hay que pasarlo por parametro.
ultimo_detalle: dict = {}

# Cache del backend detectado. None = todavia no se sondeo.
_backend = None


def _sondear(url: str, ruta: str) -> bool:
    try:
        req = urllib.request.Request(url.rstrip("/") + ruta)
        with urllib.request.urlopen(req, timeout=TIMEOUT_SONDEO) as r:
            return r.status == 200
    except Exception:
        return False


def _modelos_ollama(url: str) -> list:
    """Nombres de modelos INSTALADOS segun /api/tags. [] si no responde o esta
    vacio. Un 200 en /api/tags no prueba nada: el 2026-08-01 el sondeo decia
    'hay backend' con la lista vacia y OLLAMA_MODEL default 'llama3.2' que no
    existia (lo instalado era 'llama3.2:3b') — todo /api/generate daba 404."""
    try:
        req = urllib.request.Request(url.rstrip("/") + "/api/tags")
        with urllib.request.urlopen(req, timeout=TIMEOUT_SONDEO) as r:
            data = json.loads(r.read().decode("utf-8", errors="replace"))
        return [m.get("name", "") for m in data.get("models", []) if m.get("name")]
    except Exception:
        return []


def _elegir_modelo_ollama(modelos: list) -> str:
    """El OLLAMA_MODEL pedido si esta instalado; si no, el instalado con el
    mismo nombre base ('llama3.2' -> 'llama3.2:3b'); si no, el primero."""
    pref = os.environ.get("OLLAMA_MODEL", "").strip()
    if pref:
        if pref in modelos:
            return pref
        base = pref.split(":")[0]
        for m in modelos:
            if m.split(":")[0] == base:
                return m
    return modelos[0]


def detectar_backend(forzar: bool = False) -> Optional[dict]:
    """
    Devuelve {'tipo': 'llama'|'ollama', 'url': ..., ['modelo': ...]} o None si
    no hay ninguno. Para Ollama, 'modelo' es uno REALMENTE instalado (leido de
    /api/tags); tags vacio cuenta como SIN backend.

    Se cachea: sondear en cada llamada costaria 2 s de timeout por fallo.
    """
    global _backend
    if _backend is not None and not forzar:
        return _backend or None

    manual = os.environ.get("COGNIA_LLM_URL", "").strip()
    if manual:
        tipo = "ollama" if "11434" in manual else "llama"
        _backend = {"tipo": tipo, "url": manual.rstrip("/")}
        if tipo == "ollama":
            modelos = _modelos_ollama(manual)
            if modelos:
                _backend["modelo"] = _elegir_modelo_ollama(modelos)
        return _backend

    llama = os.environ.get("LLAMA_SERVER_URL", LLAMA_URL_DEFECTO)
    if _sondear(llama, "/health"):
        _backend = {"tipo": "llama", "url": llama.rstrip("/")}
        return _backend

    ollama = os.environ.get("OLLAMA_URL", OLLAMA_URL_DEFECTO)
    modelos = _modelos_ollama(ollama)
    if modelos:
        _backend = {"tipo": "ollama", "url": ollama.rstrip("/"),
                    "modelo": _elegir_modelo_ollama(modelos)}
        return _backend

    _backend = {}
    return None


def disponible() -> bool:
    return detectar_backend() is not None


def _post(url: str, payload: dict, timeout: int = TIMEOUT_GEN) -> Optional[dict]:
    datos = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=datos, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        print(f"[llm] HTTP {e.code} en {url}")
        return None
    except Exception as exc:
        print(f"[llm] Error: {exc}")
        return None


def generar(
    prompt:      str,
    system:      str   = "",
    temperature: float = 0.4,
    max_tokens:  int   = 600,
    via:         str   = "llm_local",
    # 120s alcanzaba para 600 tokens; una generacion larga (un contrato de
    # prueba, ~1400 tokens) se cortaba a mitad y el llamador lo veia como
    # "no hay backend" — otro degradado disfrazado. Configurable por llamada.
    timeout:     int   = TIMEOUT_GEN,
    # Esfuerzo de razonamiento para modelos Harmony (gpt-oss) via
    # chat_template_kwargs de llama-server. Medido 2026-07-26 con el prompt
    # de reparar_web: sin esto, 6 de 6 sondas mueren en finish=length con
    # 22-53k chars de razonamiento y contenido 0 (los 12000 tokens INTEGROS
    # pensando); con "low", 2 de 2 terminan en finish=stop con la pagina
    # completa en ~3000 tokens y 25s. La linea "Reasoning: low" en el system
    # NO lo consigue (3 de 3 sondas igual de muertas): el esfuerzo real lo
    # fija el template, no el developer message. None = no tocar el template
    # (comportamiento de siempre); servers sin el kwarg lo ignoran.
    reasoning_effort: Optional[str] = None,
) -> Optional[str]:
    """
    Genera texto con el backend que haya. None si no hay ninguno o si fallo.

    El que llama DEBE manejar el None. Pero desde 2026-07-25 el None YA NO ES
    SILENCIOSO: toda llamada deja quien la atendio (modelo + puerto) y toda
    ausencia de backend grita por stderr y queda en ~/.cognia/backend_audit.jsonl.
    "Que no haya modelo es un estado normal" fue justamente lo que dejo que el
    sistema degradara durante meses sin que se notara en la salida.

    `via` identifica al llamador en la auditoria ('create_program', 'critico',
    'mockup', ...). El default sirve para los que todavia no lo pasan.
    """
    from . import backend_activo

    backend = detectar_backend()
    if not backend:
        backend_activo.sin_backend(
            via, "ni llama-server (:8080) ni Ollama (:11434) responden")
        return None
    backend_activo.registrar(via, backend["url"])

    if backend["tipo"] == "llama":
        mensajes = ([{"role": "system", "content": system}] if system else [])
        mensajes.append({"role": "user", "content": prompt})
        payload = {
            "model":       "local",
            "messages":    mensajes,
            "temperature": temperature,
            "max_tokens":  max_tokens,
        }
        if reasoning_effort:
            payload["chat_template_kwargs"] = {
                "reasoning_effort": reasoning_effort}
        data = _post(backend["url"] + "/v1/chat/completions", payload,
                     timeout=timeout)
        if not data:
            return None
        try:
            eleccion = data["choices"][0]
            ultimo_detalle.clear()
            ultimo_detalle.update({
                "finish_reason": eleccion.get("finish_reason"),
                "tokens": (data.get("usage") or {}).get("completion_tokens"),
                "pedidos": max_tokens,
            })
            return eleccion["message"]["content"].strip()
        except (KeyError, IndexError):
            return None

    # 'modelo' viene de /api/tags (instalado de verdad); el env es solo el
    # ultimo recurso para URLs manuales donde tags no respondio.
    modelo = backend.get("modelo") or os.environ.get("OLLAMA_MODEL", "llama3.2")
    data = _post(backend["url"] + "/api/generate", {
        "model":   modelo,
        "prompt":  prompt,
        "system":  system,
        "stream":  False,
        "options": {"temperature": temperature, "num_predict": max_tokens},
    })
    texto = (data or {}).get("response", "").strip()
    if not texto:
        # El sondeo dijo "hay backend" pero /api/generate dio 404/error/vacio:
        # ES una degradacion y tiene que quedar en el audit, no un None mudo.
        backend_activo.sin_backend(
            via, f"ollama en {backend['url']} no genero "
                 f"(modelo={modelo}; 404 o error en /api/generate)")
        return None
    return texto


def describir() -> str:
    """Una linea con el backend en uso, para diagnostico."""
    b = detectar_backend()
    return f"{b['tipo']} en {b['url']}" if b else "ninguno (sin LLM local)"


# ── Perfil barato por NOMBRE del GGUF servido (obra 2026-08-09, WP4) ─────────
# POR QUE AQUI: el fast-path del chat desviaba turnos al 0.5B/4B y pegaba CoT
# dirigido de 3B aunque el server sirviera un razonador grande (gpt-oss-20b) —
# el turno lo respondia un modelo menor SIN decirlo (evidencia baseline
# 2026-08-09). Estos helpers son el guard BARATO por nombre; los perfiles
# formales por familia llegan con cognia/agent/model_profiles.py (WP1) y
# cuando existan, esto queda como fallback.

# Tokens de familia que delatan un razonador aunque el nombre no traiga tamano.
_TOKENS_RAZONADOR = ("gpt-oss", "gpt_oss", "qwq", "-r1", "deepseek-r",
                     "thinking", "reasoning")

# Umbrales en billones de parametros. <=4B: los perfiles chicos medidos con
# stepwise/cascada. >=8B: grande (la flota actual: 9B, 14B, 20B); el 7B esta
# RETIRADO por auditoria y no define frontera.
_CHICO_MAX_B = 4.0
_GRANDE_MIN_B = 8.0


def _tamano_b(nombre: str) -> Optional[float]:
    """Parametros en B extraidos del nombre del GGUF, o None si no trae.
    Substrings pelados ('3b' in nombre) clasificaban '21b' como chico: el
    regex exige que el numero no siga a otro digito ni la b a una letra."""
    import re
    m = re.findall(r"(?<![0-9.])(\d+(?:[._]\d+)?)\s*[bB](?![a-z0-9])",
                   nombre or "")
    if not m:
        return None
    return max(float(x.replace("_", ".")) for x in m)


def es_modelo_chico(nombre: str) -> bool:
    """True si el nombre declara <=4B (perfil chico: stepwise/cascada valen)."""
    t = _tamano_b(nombre)
    return t is not None and t <= _CHICO_MAX_B


def es_razonador_grande(nombre: str) -> bool:
    """True si el nombre delata un modelo grande (>=8B) o una familia
    razonadora. Un nombre sin senal devuelve False: el guard solo se activa
    con deteccion POSITIVA (comportamiento historico intacto para el 3B y
    para /props caido)."""
    n = (nombre or "").lower()
    if not n:
        return False
    t = _tamano_b(n)
    if t is not None and t <= _CHICO_MAX_B:
        return False              # el tamano declarado manda: "qwen3-4b-thinking" es chico
    if t is not None and t >= _GRANDE_MIN_B:
        return True
    return any(tok in n for tok in _TOKENS_RAZONADOR)


def nombre_modelo_servido(backend=None) -> str:
    """Basename del GGUF que REALMENTE sirve el backend, '' si no se sabe.

    Fuente primaria: /props del server (via backend_activo, cacheado). Un
    server ADOPTADO (arrancado externo) conserva el _gguf_path con el que se
    construyo el OBJETO, no lo que sirve — la averia historica del :8088
    (dos-backends-cognia). El gguf_path solo se usa de ultimo recurso."""
    from pathlib import Path
    from . import backend_activo

    url = ""
    if backend is not None:
        impl = getattr(backend, "_impl", None) or backend
        url = str(getattr(impl, "_base", "") or "")
    if not url:
        b = detectar_backend()
        if b and b.get("tipo") == "llama":
            url = b["url"]
    if url:
        try:
            nombre = backend_activo.props(url).get("modelo") or ""
        except Exception:
            nombre = ""
        if nombre and nombre != "desconocido":
            return nombre
    try:
        ruta = getattr(backend, "gguf_path", None)
        if ruta is None:
            impl = getattr(backend, "_impl", None) or backend
            ruta = getattr(impl, "_gguf_path", None)
        return Path(str(ruta)).name if ruta else ""
    except Exception:
        return ""


def presupuesto_chat(base: int, razonador_grande: bool,
                     piso_razonador: int = 4096) -> int:
    """max_tokens del turno de chat. Con un razonador el presupuesto tiene que
    cubrir PENSAMIENTO + respuesta (la leccion de los 9 bugs identicos:
    medido 2026-07-26, 6/6 sondas muertas en finish=length con el pensamiento
    comiendose los tokens INTEGROS). medio=1024 se queda corto para el 20B."""
    return max(int(base), piso_razonador) if razonador_grande else int(base)
