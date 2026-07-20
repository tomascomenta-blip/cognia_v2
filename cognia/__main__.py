"""
cognia/__main__.py
==================
Subcommand router. Entry point for the `cognia` CLI after `pip install cognia`.

Usage:
    cognia                  -- first-run wizard (once), then REPL
    cognia init             -- re-run setup wizard
    cognia install-model    -- download GGUF 3B + llama-server + expertos (recomendado)
    cognia install-weights  -- download shards and configure this machine as a node
    cognia server           -- start FastAPI web server (port 8000)
    cognia node             -- start as a shard node in the swarm
    cognia coordinator      -- start the swarm coordinator (port 8001)
    cognia status           -- show swarm and system status
    cognia leave            -- leave the swarm and release the hosted shard
    cognia bbrain           -- regenerate bbrain.md (live repo/environment doc)
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path


# ── Helpers ───────────────────────────────────────────────────────────────────

def _progress_bar(pct: float, msg: str) -> None:
    bar = "#" * int(pct * 30) + "-" * (30 - int(pct * 30))
    print(f"\r  [{bar}] {pct:5.1%}  {msg[:38]}", end="", flush=True)


def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        answer = input(f"{prompt}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)
    return answer or default


# ── Subcommands ───────────────────────────────────────────────────────────────

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


def _cmd_install_weights() -> None:
    """
    Descarga el shard asignado por el coordinador y configura este
    dispositivo como nodo del swarm. Sin wizard completo.

    Uso minimo:
        cognia install-weights
        cognia install-weights --coordinator http://192.168.1.50:8001
        cognia install-weights --standalone   (descarga los 4 shards para uso local)
    """
    from cognia.first_run import COGNIA_HOME, SHARDS_DIR, DATA_DIR, CONFIG_FILE, FIRST_RUN_OK

    args = sys.argv[2:]
    standalone = "--standalone" in args

    # Resolver URL del coordinador
    coord_url = ""
    if "--coordinator" in args:
        idx = args.index("--coordinator")
        if idx + 1 < len(args):
            coord_url = args[idx + 1].rstrip("/")
    if not coord_url:
        coord_url = (
            os.environ.get("COGNIA_COORDINATOR_URL", "")
            or os.environ.get("COORDINATOR_URL", "")
        ).rstrip("/")
    if not coord_url and not standalone:
        coord_url = _ask("URL del coordinador", default="http://localhost:8001")

    print("\nCognia -- install-weights")
    print("-" * 40)

    # Crear directorios
    COGNIA_HOME.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SHARDS_DIR.mkdir(parents=True, exist_ok=True)

    _root = Path(__file__).parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

    from node.downloader import download_npz_shard
    from shattering.model_constants import QWEN25_CODER_3B

    model_key  = os.environ.get("COGNIA_SWARM_MODEL", "qwen-coder-3b-q4")
    n_shards   = QWEN25_CODER_3B["n_shards"]
    shard_dir  = SHARDS_DIR / model_key
    shard_dir.mkdir(parents=True, exist_ok=True)

    config: dict[str, str] = {
        "COGNIA_DATA_DIR":    str(DATA_DIR),
        "SHARD_WEIGHTS_DIR":  str(shard_dir),
    }
    if coord_url:
        config["COGNIA_COORDINATOR_URL"] = coord_url

    hf_token = os.environ.get("HF_TOKEN", "")

    if standalone:
        # Descargar los 4 shards para inferencia local completa
        print(f"Modo standalone: descargando {n_shards} shards (~1.2GB total)\n")
        for i in range(n_shards):
            dest = shard_dir / f"shard_{i}.npz"
            print(f"Shard {i}:")
            result = download_npz_shard(i, str(dest), hf_token=hf_token,
                                        on_progress=_progress_bar)
            print()
            if not result.ok:
                print(f"  [ERROR] {result.error}")
                sys.exit(1)
            print(f"  OK ({result.size_mb:.0f} MB)")
    else:
        # Registrar con el coordinador y descargar solo el shard asignado
        print(f"Coordinador: {coord_url}")
        print("Registrando este dispositivo...")
        try:
            import platform
            hw = platform.processor()[:40] or platform.machine()
            try:
                import psutil
                hw += f" | {psutil.virtual_memory().total / 1e9:.1f}GB RAM"
            except ImportError:
                pass

            data = json.dumps({"hardware_info": hw, "model_name": model_key}).encode()
            req  = urllib.request.Request(
                f"{coord_url}/api/node/register", data=data,
                headers={"Content-Type": "application/json"}, method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                reg = json.loads(r.read())

            shard      = reg["shard"]
            node_id    = reg["node_id"]
            contrib_t  = reg.get("contributor_token", "")

            print(f"  Shard asignado : {shard}")
            print(f"  Node ID        : {node_id[:12]}...")

            config["COGNIA_NODE_SHARD"] = str(shard)
            if contrib_t:
                config["COGNIA_CONTRIBUTOR_TOKEN"] = contrib_t

        except Exception as exc:
            print(f"  [ERROR] No se pudo conectar al coordinador: {exc}")
            print("  Verifica que el coordinador este corriendo y la URL sea correcta.")
            sys.exit(1)

        dest = shard_dir / f"shard_{shard}.npz"
        print(f"\nDescargando shard {shard} (~300MB)...")
        result = download_npz_shard(shard, str(dest), hf_token=hf_token,
                                    on_progress=_progress_bar)
        print()
        if not result.ok:
            print(f"  [ERROR] {result.error}")
            sys.exit(1)
        print(f"  OK ({result.size_mb:.0f} MB)")

    # Guardar config
    lines = [f"{k}={v}\n" for k, v in config.items()]
    CONFIG_FILE.write_text("".join(lines), encoding="utf-8")
    FIRST_RUN_OK.touch()

    print("\n" + "-" * 40)
    print("Listo. Arranca el nodo con:")
    print()
    print("    cognia node")
    print()


def _cmd_leave() -> None:
    """
    Salir de la red distribuida voluntariamente.
    Notifica al coordinador, el shard queda disponible para redistribucion.
    Limpia la configuracion de nodo local.
    """
    from cognia.first_run import CONFIG_FILE, FIRST_RUN_OK, _load_config

    config = _load_config()
    coord_url    = config.get("COGNIA_COORDINATOR_URL", "").rstrip("/")
    node_id      = config.get("COGNIA_NODE_ID", "")
    contrib_tok  = config.get("COGNIA_CONTRIBUTOR_TOKEN", "")
    shard        = config.get("COGNIA_NODE_SHARD", "?")

    if not coord_url or not node_id:
        print("Este dispositivo no esta registrado como nodo en ningun coordinador.")
        return

    print(f"\nSaliendo de la red...")
    print(f"  Coordinador : {coord_url}")
    print(f"  Node ID     : {node_id[:12]}...")
    print(f"  Fragmento   : shard {shard}")
    print()

    try:
        data    = json.dumps({"node_id": node_id}).encode()
        headers = {"Content-Type": "application/json"}
        if contrib_tok:
            headers["X-Contributor-Token"] = contrib_tok
        req = urllib.request.Request(
            f"{coord_url}/api/node/leave",
            data=data,
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            json.loads(r.read())
        print(f"  Fragmento shard {shard} liberado. Queda disponible para otro nodo.")
    except Exception as exc:
        print(f"  No se pudo contactar al coordinador: {exc}")
        print("  El coordinador detectara la desconexion automaticamente por TTL.")

    # Conservar OLLAMA_URL, COGNIA_MODEL, COGNIA_DATA_DIR; eliminar vars de nodo
    _node_keys = {
        "COGNIA_COORDINATOR_URL", "COGNIA_NODE_ID",
        "COGNIA_NODE_SHARD", "COGNIA_CONTRIBUTOR_TOKEN", "SHARD_WEIGHTS_DIR",
    }
    new_config = {k: v for k, v in config.items() if k not in _node_keys}
    CONFIG_FILE.write_text(
        "".join(f"{k}={v}\n" for k, v in new_config.items()), encoding="utf-8"
    )
    FIRST_RUN_OK.unlink(missing_ok=True)

    print()
    print("  Configuracion de nodo eliminada.")
    print("  El fragmento permanece en disco. Puedes borrarlo en:")
    shard_path = Path.home() / ".cognia" / "shards"
    print(f"  {shard_path}")
    print()
    print("  La proxima vez que ejecutes 'cognia' se iniciara el wizard.")
    print()


def _cmd_modo() -> None:
    """
    Ver o cambiar el modo de uso y la personalizacion.

    Uso:
        cognia modo                 -- mostrar modo + personalizacion actual
        cognia modo local           -- correr el modelo en este equipo
        cognia modo compartido      -- unirse a la red local (swarm)
        cognia modo memoria         -- sin LLM (solo memoria/grafo)
    """
    from cognia.user_prefs import (
        load_prefs, save_pref, K_RUN_MODE, K_USER_NAME, K_LANG, K_STYLE, MODE_LABELS,
    )
    from cognia.first_run import SHARDS_DIR

    args  = sys.argv[2:]
    prefs = load_prefs()

    if args:
        target = args[0].strip().lower()
        if target not in MODE_LABELS:
            print(f"Modo desconocido: '{target}'. Opciones: local, compartido, memoria.")
            sys.exit(1)
        save_pref(K_RUN_MODE, target)
        print(f"Modo cambiado a: {MODE_LABELS[target]}")
        if target == "local":
            # GGUF-first: el stack recomendado es llama-server + GGUF
            # (cognia install-model); los shards NPZ son el camino avanzado.
            # Antes esto solo miraba shard_0.npz y mandaba a install-weights
            # aunque el GGUF ya estuviera instalado y funcionando.
            gguf = None
            try:
                from node.llama_backend import _find_gguf
                gguf = _find_gguf()
            except Exception:
                pass
            if gguf is not None:
                print(f"  Backend local listo (GGUF: {gguf})")
            else:
                model_key = os.environ.get("COGNIA_SWARM_MODEL", "qwen-coder-3b-q4")
                has_shards = (SHARDS_DIR / model_key / "shard_0.npz").exists()
                if not has_shards:
                    print("  Falta el modelo local. Instala el stack recomendado con:")
                    print("      cognia install-model")
                    print("  (avanzado: shards numpy con 'cognia install-weights --standalone')")
        elif target == "compartido":
            print("  Conecta a un coordinador con:")
            print("      cognia install-weights --coordinator <URL>")
        return

    mode  = prefs.get(K_RUN_MODE) or ""
    label = MODE_LABELS.get(mode, mode or "(sin configurar -- ejecuta 'cognia init')")
    print("Cognia -- modo y personalizacion")
    print("-" * 42)
    print(f"  Modo actual : {label}")
    print(f"  Nombre      : {prefs.get(K_USER_NAME) or '(no definido)'}")
    print(f"  Idioma      : {prefs.get(K_LANG) or '(default)'}")
    print(f"  Estilo      : {prefs.get(K_STYLE) or '(default)'}")
    print()
    print("  Cambiar modo:")
    print("    cognia modo local        -- correr en este equipo")
    print("    cognia modo compartido   -- unirse a la red local")
    print("    cognia modo memoria      -- sin LLM")
    print("    cognia init              -- reconfigurar todo (incluida personalizacion)")


def _cmd_status() -> None:
    # Backend real primero: antes status solo reportaba swarm + Ollama
    # (sistemas legacy/opcionales) y una instalacion sana decia
    # "modo standalone / Ollama: no disponible".
    _print_backend_status()

    coord_url = (
        os.environ.get("COGNIA_COORDINATOR_URL", "")
        or os.environ.get("COORDINATOR_URL", "")
    ).rstrip("/")

    if not coord_url:
        print("Swarm: apagado (COGNIA_COORDINATOR_URL no configurada) -- modo local")
        _print_ollama_status()
        return

    try:
        with urllib.request.urlopen(
            f"{coord_url}/api/swarm/status?model_name=qwen-coder-3b-q4",
            timeout=4,
        ) as r:
            data = json.loads(r.read())
        ready  = data.get("ready", False)
        nodes  = data.get("nodes_online", "?")
        shards = data.get("shards_covered", "?")
        print(f"Coordinador: {coord_url}")
        print(f"  Swarm listo     : {'si' if ready else 'no'}")
        print(f"  Nodos online    : {nodes}")
        print(f"  Shards cubiertos: {shards}")
    except Exception as exc:
        print(f"Coordinador no disponible ({coord_url}): {exc}")

    _print_ollama_status()


def _cmd_bbrain() -> None:
    """Regenera bbrain.md en la raiz del repo introspectando el entorno vivo."""
    from cognia.bbrain import write_bbrain
    root = Path(__file__).parent.parent
    path = write_bbrain(root)
    print(f"bbrain.md regenerado: {path}")


def _cmd_fleet() -> None:
    """Muestra la flota local de modelos GGUF y su estado en disco."""
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _root not in sys.path:
        sys.path.insert(0, _root)
    from node.fleet import fleet_status, models_dir

    print(f"Flota local ({models_dir()})")
    print("-" * 64)
    for m in fleet_status():
        estado = f"OK {m['gb']:.2f} GB" if m["presente"] else "FALTA"
        print(f"  {m['key']:<12} {m['params']:>5}  [{estado:>12}]  {m['rol']}")
    print()
    print("  El modelo activo del chat lo decide LLAMA_GGUF_PATH (.env).")

def _print_backend_status() -> None:
    """Estado del backend de inferencia REAL (llama-server + GGUF)."""
    gguf = None
    try:
        from node.llama_backend import _find_gguf
        gguf = _find_gguf()
    except Exception:
        pass
    if gguf is None:
        print("Backend local (GGUF): no instalado -- instala con: cognia install-model")
        return
    print(f"Backend local (GGUF): instalado ({gguf})")
    port = os.environ.get("LLAMA_SERVER_PORT", "8088")
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2)
        print(f"  llama-server: corriendo en 127.0.0.1:{port}")
    except Exception:
        print(f"  llama-server: no corriendo (arranca on-demand al usar el REPL)")


def _print_ollama_status() -> None:
    ollama_url = os.environ.get("OLLAMA_URL", "http://localhost:11434")
    try:
        urllib.request.urlopen(f"{ollama_url}/api/tags", timeout=3)
        print(f"Ollama (opcional): disponible en {ollama_url}")
    except Exception:
        print(f"Ollama (opcional): no disponible")


# ── Help ──────────────────────────────────────────────────────────────────────

_HELP = """\
Uso: cognia [comando] [opciones]

Comandos:
  (ninguno)          Iniciar REPL (lanza wizard en primer uso)
  init               Re-ejecutar wizard de configuracion
  modo               Ver o cambiar el modo (local/compartido/memoria) y personalizacion
  install-model      Descargar GGUF 3B + llama-server + expertos (recomendado)
  install-weights    Descargar shards y configurar este dispositivo como nodo
  server             Servidor web FastAPI (puerto 8000)
  node               Iniciar como nodo del swarm distribuido
  coordinator        Iniciar coordinador del swarm (puerto 8001)
  status             Estado del backend local (GGUF), swarm y Ollama
  leave              Salir de la red y liberar el fragmento alojado
  bbrain             Regenerar bbrain.md (doc viva del repo y su entorno)
  fleet              Estado de la flota local de modelos GGUF
  help / --help      Mostrar esta ayuda

Opciones de install-weights:
  --coordinator URL  URL del coordinador (ej: http://192.168.1.50:8001)
  --standalone       Descargar los 4 shards para inferencia local completa

Configuracion:
  ~/.cognia/config.env     Fuente principal (la escribe 'cognia install-model' /
                           el wizard): LLAMA_GGUF_PATH, LLAMA_SERVER_PATH, etc.
                           Las env vars del sistema MANDAN sobre config.env.

Variables de entorno:
  LLAMA_GGUF_PATH          Ruta directa a un GGUF (prioridad sobre deteccion)
  COGNIA_COORDINATOR_URL   URL del coordinador (swarm opcional)
  OLLAMA_URL               URL de Ollama (fallback opcional)
  HF_TOKEN                 Token HuggingFace para datasets privados
"""


# ── Entry point ───────────────────────────────────────────────────────────────

def _harden_console_encoding() -> None:
    """Hace stdout/stderr a prueba de crash en la consola cp1252 de Windows.

    Muchos print() del repo llevan emojis/simbolos fuera de cp1252; sin esto,
    escribirlos LANZA UnicodeEncodeError y puede tumbar hilos de fondo (p.ej. la
    Curiosidad Pasiva) o abortar un comando. errors='replace' nunca crashea (los
    chars no representables pasan a '?'), y en terminales modernas UTF-8 se ven
    bien. Idempotente con el wrap existente del REPL (cli.py)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def main() -> None:
    _harden_console_encoding()
    from cognia.first_run import apply_config
    apply_config()

    cmd = sys.argv[1] if len(sys.argv) > 1 else ""

    if cmd in ("help", "--help", "-h"):
        print(_HELP)
    elif cmd == "init":
        _cmd_init(force=True)
    elif cmd == "install-weights":
        _cmd_install_weights()
    elif cmd in ("download-weights",):
        _cmd_install_weights()   # alias
    elif cmd in ("install-model", "install-modelo"):
        # Stack GGUF validado (llama-server b9391 + Q4_K_M + fleet de expertos):
        # el camino DEFAULT de una instalación limpia (GATES_CLI_VNEXT.md).
        from cognia.model_install import main as _im_main
        _im_main(sys.argv[2:])
    elif cmd == "server":
        _cmd_server()
    elif cmd == "node":
        _cmd_node()
    elif cmd == "coordinator":
        _cmd_coordinator()
    elif cmd in ("modo", "mode"):
        _cmd_modo()
    elif cmd == "status":
        _cmd_status()
    elif cmd == "leave":
        _cmd_leave()
    elif cmd == "bbrain":
        _cmd_bbrain()
    elif cmd == "fleet":
        _cmd_fleet()
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
