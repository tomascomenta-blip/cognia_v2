"""
a1_quien_atendio.py — prueba de aceptacion de FASE A1: UN SOLO BACKEND.

    PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\a1_quien_atendio.py

QUE PRUEBA: que una peticion de CHAT y una de CREATE_PROGRAM las atiende el
mismo backend, en el mismo puerto, con el modelo de la flota — y no el
qwen2.5-7b-instruct que la auditoria del 24/07 marco RETIRADO.

POR QUE EXISTE: hasta hoy habia DOS backends y nadie podia decir cual contesto.
node/llama_backend.py levantaba llama-server en :8088 con LLAMA_GGUF_PATH (el 7B
jubilado) y atendia chat/agente/create_program; cognia/llm_local.py sondeaba
:8080, donde scripts/servir_flota.py sirve la flota adoptada por gate. Los
productos de hoy (5.4/10, 7.8/10) salieron del 7B; los de pulidos/, de la flota.

CRITERIO DE ACEPTACION (el del dueno): si el log dice qwen2.5-7b, NO esta hecho.

Antes de correr: python scripts/servir_flota.py construir
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

MODELO_PROHIBIDO = "qwen2.5-7b"          # el retirado por la auditoria 24/07
PUERTO_ESPERADO = 8080                   # el unico puerto del backend


def _linea(t=""):
    print(t, flush=True)


def peticion_chat(backend) -> dict:
    """Camino real del chat: LlamaBackend.stream_chat (ver cognia/tui/backend.py)."""
    from cognia import backend_activo

    trozos = []
    for t in backend.stream_chat(
            [{"role": "user",
              "content": "Responde SOLO con la palabra: listo"}],
            max_tokens=16, temperature=0.1):
        trozos.append(t)
    respuesta = "".join(trozos).strip()
    reg = backend_activo.ultimo()
    _linea(f"  respuesta del modelo: {respuesta[:80]!r}")
    return reg


def peticion_create_program(backend) -> dict:
    """
    Camino real de create_program: generator._call_llm con el backend INYECTADO
    (que es el que ganaba y servia el 7B). Se usa la misma firma que
    program_creator._llm_de_cognia: (prompt, system, max_tokens, temperature).
    """
    from cognia import backend_activo
    from cognia.program_creator.generator import _call_llm

    def llm(prompt, system="", max_tokens=2000, temperature=0.9):
        full = f"{system}\n\n{prompt}" if system else prompt
        return backend.generate(full, max_tokens=max_tokens,
                                temperature=temperature)

    texto = _call_llm(
        "Escribe una funcion Python `suma(a, b)` que devuelva a+b. "
        "Solo el bloque de codigo.",
        lenguaje="python", temperature=0.2, llm=llm)
    reg = backend_activo.ultimo()
    _linea(f"  el modelo devolvio {len(texto or '')} chars")
    return reg


def veredicto(nombre: str, reg: dict) -> bool:
    modelo = (reg.get("modelo") or "").lower()
    puerto = reg.get("puerto")
    if reg.get("degradado"):
        _linea(f"  FALLA {nombre}: DEGRADADO sin backend -- {reg.get('detalle')}")
        return False
    ok_modelo = MODELO_PROHIBIDO not in modelo
    ok_puerto = puerto == PUERTO_ESPERADO
    _linea(f"  ATENDIO -> modelo={reg.get('modelo')}  puerto={puerto}  "
           f"via={reg.get('via')}")
    if not ok_modelo:
        _linea(f"  FALLA {nombre}: es el modelo RETIRADO ({MODELO_PROHIBIDO}).")
    if not ok_puerto:
        _linea(f"  FALLA {nombre}: puerto {puerto}, esperaba {PUERTO_ESPERADO} "
               f"(hay mas de un backend).")
    return ok_modelo and ok_puerto


def main() -> int:
    os.environ.setdefault("COGNIA_BACKEND_LOG", "1")
    # Igual que el CLI real (cognia/__main__.py:480): sin esto, LLAMA_GGUF_PATH y
    # LLAMA_SERVER_PATH de ~/.cognia/config.env no estan en os.environ y el
    # backend elige un GGUF al azar del directorio y no encuentra el binario.
    from cognia.first_run import apply_config
    apply_config()
    from node.llama_backend import LlamaBackend

    _linea("=" * 72)
    _linea("A1 -- QUIEN ATENDIO CADA PETICION")
    _linea("=" * 72)

    backend = LlamaBackend.try_load()
    if backend is None:
        _linea("try_load() devolvio None: no hay backend. "
               "Arranca: python scripts/servir_flota.py construir")
        return 1

    props = backend.server_props() or {}
    _linea(f"backend construido: {Path(str(props.get('model_path', '?'))).name}")
    _linea("")

    _linea("[1] PETICION DE CHAT")
    ok_chat = veredicto("chat", peticion_chat(backend))
    _linea("")

    _linea("[2] PETICION DE CREATE_PROGRAM")
    ok_cp = veredicto("create_program", peticion_create_program(backend))
    _linea("")

    _linea("=" * 72)
    if ok_chat and ok_cp:
        _linea("A1 PASA: las dos peticiones las atendio el mismo backend de la "
               "flota, en :8080, y ninguna toco el 7B retirado.")
        _linea(f"Auditoria completa: {Path.home() / '.cognia' / 'backend_audit.jsonl'}")
        return 0
    _linea("A1 FALLA. Ver arriba.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
