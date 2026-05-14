"""
cognia/__main__.py
==================
Subcommand router. Entry point for the `cognia` CLI after `pip install cognia`.

Usage:
    cognia                  -- first-run wizard (once), then REPL
    cognia init             -- re-run setup wizard
    cognia server           -- start FastAPI web server (port 8000)
    cognia node             -- start as a shard node in the swarm
    cognia coordinator      -- start the swarm coordinator (port 8001)
    cognia download-weights -- download and convert Qwen2.5 weights
    cognia status           -- show swarm and system status
"""

from __future__ import annotations

import os
import sys


def _cmd_init(force: bool = True) -> None:
    from cognia.first_run import run_wizard
    run_wizard(force=force)


def _cmd_server() -> None:
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    print(f"Iniciando servidor en http://0.0.0.0:{port}")
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=False)


def _cmd_node() -> None:
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _root not in sys.path:
        sys.path.insert(0, _root)
    from node.main import main as node_main
    node_main()


def _cmd_coordinator() -> None:
    import uvicorn
    port = int(os.environ.get("PORT", 8001))
    print(f"Iniciando coordinador en http://0.0.0.0:{port}")
    uvicorn.run("coordinator.app:app", host="0.0.0.0", port=port, reload=False)


def _cmd_download_weights() -> None:
    from cognia.first_run import _download_weights, _ask
    hf_token = _ask("HuggingFace token (Enter para omitir)", default="")
    try:
        shard_dir = _download_weights(hf_token)
        print(f"Pesos listos en {shard_dir}")
    except Exception as exc:
        print(f"[ERROR] {exc}")
        sys.exit(1)


def _cmd_status() -> None:
    coord_url = (
        os.environ.get("COGNIA_COORDINATOR_URL", "")
        or os.environ.get("COORDINATOR_URL", "")
    ).rstrip("/")

    if not coord_url:
        print("COGNIA_COORDINATOR_URL no configurada -- modo standalone")
        _print_ollama_status()
        return

    try:
        import urllib.request
        import json
        with urllib.request.urlopen(
            f"{coord_url}/api/swarm/status?model_name=qwen-coder-3b-q4",
            timeout=4,
        ) as r:
            data = json.loads(r.read())
        ready = data.get("ready", False)
        nodes = data.get("nodes_online", "?")
        shards = data.get("shards_covered", "?")
        print(f"Coordinador: {coord_url}")
        print(f"  Swarm listo     : {'si' if ready else 'no'}")
        print(f"  Nodos online    : {nodes}")
        print(f"  Shards cubiertos: {shards}")
    except Exception as exc:
        print(f"Coordinador no disponible ({coord_url}): {exc}")

    _print_ollama_status()


def _print_ollama_status() -> None:
    ollama_url = os.environ.get("OLLAMA_URL", "http://localhost:11434")
    try:
        import urllib.request
        urllib.request.urlopen(f"{ollama_url}/api/tags", timeout=3)
        print(f"Ollama: disponible en {ollama_url}")
    except Exception:
        print(f"Ollama: no disponible en {ollama_url}")


_HELP = """\
Uso: cognia [comando]

Comandos:
  (ninguno)          Iniciar REPL (lanza wizard en primer uso)
  init               Re-ejecutar wizard de configuracion
  server             Servidor web FastAPI (puerto 8000)
  node               Iniciar como nodo del swarm distribuido
  coordinator        Iniciar coordinador del swarm (puerto 8001)
  download-weights   Descargar y convertir pesos Qwen2.5-Coder-3B
  status             Estado del swarm y Ollama
  help / --help      Mostrar esta ayuda

Variables de entorno clave:
  COGNIA_COORDINATOR_URL   URL del coordinador (activa modo distribuido)
  OLLAMA_URL               URL de Ollama (default: http://localhost:11434)
  COGNIA_MODEL             Modelo Ollama a usar (default: llama3.2)
  SHARD_WEIGHTS_DIR        Ruta a los shards .npz del modelo
"""


def main() -> None:
    from cognia.first_run import apply_config
    apply_config()

    cmd = sys.argv[1] if len(sys.argv) > 1 else ""

    if cmd in ("help", "--help", "-h"):
        print(_HELP)
    elif cmd == "init":
        _cmd_init(force=True)
    elif cmd == "server":
        _cmd_server()
    elif cmd == "node":
        _cmd_node()
    elif cmd == "coordinator":
        _cmd_coordinator()
    elif cmd == "download-weights":
        _cmd_download_weights()
    elif cmd == "status":
        _cmd_status()
    elif cmd == "":
        from cognia.first_run import run_wizard
        run_wizard(force=False)
        from cognia.cli import repl
        repl()
    else:
        print(f"Comando desconocido: '{cmd}'. Usa 'cognia help' para ver opciones.")
        sys.exit(1)


if __name__ == "__main__":
    main()
