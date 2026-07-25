"""
backend_activo.py — quien atendio cada peticion de LLM: modelo, puerto y via.

POR QUE EXISTE: hasta el 2026-07-25 Cognia tenia DOS backends y nadie lo sabia.
node/llama_backend.py arrancaba llama-server en :8088 con LLAMA_GGUF_PATH
(qwen2.5-7b, el modelo que la auditoria de flota del 24/07 marco RETIRADO) y
atendia el chat, el agente y create_program; cognia/llm_local.py sondeaba :8080,
que es donde scripts/servir_flota.py sirve la flota adoptada por gate. Los
productos salian del 7B jubilado y el diagnostico culpaba a la arquitectura.

Un sistema que no dice quien contesto no se puede medir. Toda llamada real a un
LLM pasa por registrar() y deja:
  - una linea en stderr (visible en la corrida)
  - una linea JSON en ~/.cognia/backend_audit.jsonl (auditable despues)

Y toda ausencia de backend pasa por sin_backend(), que grita en vez de devolver
None en silencio (ver cognia/llm_local.py y node/llama_backend.try_load).

Solo stdlib. Nada aqui puede lanzar: es instrumentacion, no camino critico.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from typing import Optional

AUDIT = Path.home() / ".cognia" / "backend_audit.jsonl"

# /props por URL. Sondear en cada token costaria mas que generarlo.
_props_cache: dict = {}

# Ultimo registro, para que los tests y el CLI puedan afirmar quien contesto
# sin releer el jsonl.
_ultimo: dict = {}


def _silencioso() -> bool:
    """COGNIA_BACKEND_LOG=0 apaga la linea de stderr (no el jsonl)."""
    return os.environ.get("COGNIA_BACKEND_LOG", "1").strip() == "0"


def props(url: str, forzar: bool = False) -> dict:
    """
    {'modelo': <basename del gguf>, 'n_ctx': int, 'puerto': int} del server.

    {} si no responde. Cacheado por URL: un llama-server no cambia de modelo
    sin reiniciar, y reiniciar cambia el puerto o mata el proceso.
    """
    url = url.rstrip("/")
    if not forzar and url in _props_cache:
        return _props_cache[url]
    datos = {}
    try:
        with urllib.request.urlopen(url + "/props", timeout=3) as r:
            crudo = json.loads(r.read().decode("utf-8", errors="replace"))
        ruta = crudo.get("model_path") or crudo.get("default_generation_settings", {}).get("model", "")
        datos = {
            "modelo": Path(str(ruta)).name or "desconocido",
            "n_ctx": crudo.get("default_generation_settings", {}).get("n_ctx"),
            "puerto": _puerto_de(url),
        }
    except Exception:
        datos = {}
    _props_cache[url] = datos
    return datos


def _puerto_de(url: str) -> Optional[int]:
    try:
        return int(url.rsplit(":", 1)[1].split("/")[0])
    except (ValueError, IndexError):
        return None


def _append(fila: dict) -> None:
    try:
        AUDIT.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT.open("a", encoding="utf-8") as f:
            f.write(json.dumps(fila, ensure_ascii=False) + "\n")
    except Exception:
        pass


def registrar(via: str, url: str, rol: str = "", **extra) -> dict:
    """
    Deja constancia de que `via` atendio una peticion contra `url`.

    via: 'chat', 'agente', 'create_program', 'constructor', 'pulidor', 'juez'...
    rol: el rol de flota esperado ('construir', 'pensar', ...), si se conoce.
    """
    global _ultimo
    p = props(url)
    fila = {
        "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "via": via,
        "url": url.rstrip("/"),
        "puerto": p.get("puerto") or _puerto_de(url),
        "modelo": p.get("modelo", "SIN RESPUESTA /props"),
        "rol": rol,
        **extra,
    }
    _ultimo = fila
    _append(fila)
    if not _silencioso():
        # ascii: la consola de esta maquina es cp1252.
        print(f"[backend] via={fila['via']} modelo={fila['modelo']} "
              f"puerto={fila['puerto']}" + (f" rol={rol}" if rol else ""),
              file=sys.stderr, flush=True)
    return fila


def sin_backend(via: str, detalle: str = "") -> dict:
    """
    No habia backend. Esto NO es un estado normal: es el modo de fallo caro.

    Grita siempre (aunque COGNIA_BACKEND_LOG=0) y queda en el jsonl, para que
    una corrida que degrado se pueda distinguir despues de una que no.
    """
    global _ultimo
    fila = {
        "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "via": via,
        "url": None,
        "puerto": None,
        "modelo": None,
        "degradado": True,
        "detalle": detalle,
    }
    _ultimo = fila
    _append(fila)
    print(f"[backend] DEGRADADO: '{via}' sin backend LLM -- "
          f"{detalle or 'no responde ningun servidor'}. "
          f"Arranca la flota: python scripts/servir_flota.py construir",
          file=sys.stderr, flush=True)
    return fila


def ultimo() -> dict:
    """El ultimo registro de este proceso ({} si no hubo ninguno)."""
    return dict(_ultimo)


def resetear_cache() -> None:
    """Tras reiniciar un server en el mismo puerto, el /props cacheado miente."""
    _props_cache.clear()


# ── Chequeo de arranque ──────────────────────────────────────────────────────

# El modelo que la auditoria de flota del 2026-07-24 retiro ("redundante: ni
# coder, ni thinking, ni VL; ningun modulo lo rutea") y que aun asi atendia el
# chat, el agente y create_program el 25/07.
RETIRADOS = ("qwen2.5-7b-instruct",)

PUERTO_UNICO = 8080


def estado() -> dict:
    """Que backend hay AHORA: puerto, modelo, y si algo esta mal."""
    url = os.environ.get("COGNIA_LLM_URL") or f"http://127.0.0.1:{PUERTO_UNICO}"
    p = props(url, forzar=True)
    modelo = p.get("modelo", "")
    avisos = []
    if not p:
        avisos.append(
            f"NO HAY BACKEND en {url}. Cognia va a degradar a sus fallbacks. "
            f"Arranca: python scripts/servir_flota.py construir")
    else:
        for r in RETIRADOS:
            if r in modelo.lower():
                avisos.append(
                    f"El modelo servido ({modelo}) esta RETIRADO por la "
                    f"auditoria de flota del 2026-07-24. Ningun modulo deberia "
                    f"rutear a el.")
    return {"url": url, "modelo": modelo or None,
            "puerto": p.get("puerto") or _puerto_de(url), "avisos": avisos}


def chequeo_arranque(silencioso_si_ok: bool = False) -> bool:
    """
    Se corre al arrancar Cognia. Devuelve True si el backend esta sano.

    POR QUE EXISTE: "Cognia degrada en silencio" estaba escrito como leccion
    desde hace meses y el 2026-07-25 volvio a pasar (dos backends, el retirado
    sirviendo el chat). Una leccion en prosa no impide nada: no se ejecuta. Esto
    es la misma leccion convertida en un chequeo que corre solo y que se ve.
    """
    e = estado()
    if e["avisos"]:
        print("", file=sys.stderr)
        for a in e["avisos"]:
            print(f"  [!] BACKEND: {a}", file=sys.stderr)
        print("", file=sys.stderr)
        return False
    if not silencioso_si_ok:
        print(f"  backend: {e['modelo']} en :{e['puerto']}", file=sys.stderr)
    return True


if __name__ == "__main__":
    e = estado()
    print(f"url    : {e['url']}")
    print(f"puerto : {e['puerto']}")
    print(f"modelo : {e['modelo'] or 'NINGUNO'}")
    for a in e["avisos"]:
        print(f"AVISO  : {a}")
    sys.exit(0 if not e["avisos"] else 1)
