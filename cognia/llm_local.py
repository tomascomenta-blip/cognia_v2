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
TIMEOUT_GEN    = 120

# Cache del backend detectado. None = todavia no se sondeo.
_backend = None


def _sondear(url: str, ruta: str) -> bool:
    try:
        req = urllib.request.Request(url.rstrip("/") + ruta)
        with urllib.request.urlopen(req, timeout=TIMEOUT_SONDEO) as r:
            return r.status == 200
    except Exception:
        return False


def detectar_backend(forzar: bool = False) -> Optional[dict]:
    """
    Devuelve {'tipo': 'llama'|'ollama', 'url': ...} o None si no hay ninguno.

    Se cachea: sondear en cada llamada costaria 2 s de timeout por fallo.
    """
    global _backend
    if _backend is not None and not forzar:
        return _backend or None

    manual = os.environ.get("COGNIA_LLM_URL", "").strip()
    if manual:
        tipo = "ollama" if "11434" in manual else "llama"
        _backend = {"tipo": tipo, "url": manual.rstrip("/")}
        return _backend

    llama = os.environ.get("LLAMA_SERVER_URL", LLAMA_URL_DEFECTO)
    if _sondear(llama, "/health"):
        _backend = {"tipo": "llama", "url": llama.rstrip("/")}
        return _backend

    ollama = os.environ.get("OLLAMA_URL", OLLAMA_URL_DEFECTO)
    if _sondear(ollama, "/api/tags"):
        _backend = {"tipo": "ollama", "url": ollama.rstrip("/")}
        return _backend

    _backend = {}
    return None


def disponible() -> bool:
    return detectar_backend() is not None


def _post(url: str, payload: dict) -> Optional[dict]:
    datos = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=datos, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_GEN) as r:
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
) -> Optional[str]:
    """
    Genera texto con el backend que haya. None si no hay ninguno o si fallo.

    El que llama DEBE manejar el None: que no haya modelo es un estado normal
    en esta maquina, no una excepcion.
    """
    backend = detectar_backend()
    if not backend:
        return None

    if backend["tipo"] == "llama":
        mensajes = ([{"role": "system", "content": system}] if system else [])
        mensajes.append({"role": "user", "content": prompt})
        data = _post(backend["url"] + "/v1/chat/completions", {
            "model":       "local",
            "messages":    mensajes,
            "temperature": temperature,
            "max_tokens":  max_tokens,
        })
        if not data:
            return None
        try:
            return data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError):
            return None

    data = _post(backend["url"] + "/api/generate", {
        "model":   os.environ.get("OLLAMA_MODEL", "llama3.2"),
        "prompt":  prompt,
        "system":  system,
        "stream":  False,
        "options": {"temperature": temperature, "num_predict": max_tokens},
    })
    return (data or {}).get("response", "").strip() or None


def describir() -> str:
    """Una linea con el backend en uso, para diagnostico."""
    b = detectar_backend()
    return f"{b['tipo']} en {b['url']}" if b else "ninguno (sin LLM local)"
