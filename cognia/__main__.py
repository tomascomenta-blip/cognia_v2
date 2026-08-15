"""
cognia/__main__.py
==================
Subcommand router. Entry point for the `cognia` CLI after `pip install cognia`.

Usage:
    cognia empezar          -- camino unico: instala lo que falte, verifica y abre el REPL
    cognia                  -- first-run wizard (once), then REPL
    cognia doctor           -- diagnostico de la instalacion
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


def _cmd_contribucion() -> None:
    """
    Estado de la contribucion de este nodo en la economia del enjambre.

    Consulta /api/contribution/{node_id} (ledger propio: params aportados,
    tier, requests servidos) y /api/tiers (que desbloquea cada tier).
    """
    from cognia.first_run import _load_config

    config      = _load_config()
    coord_url   = (config.get("COGNIA_COORDINATOR_URL", "")
                   or os.environ.get("COGNIA_COORDINATOR_URL", "")).rstrip("/")
    node_id     = config.get("COGNIA_NODE_ID", "") or os.environ.get("COGNIA_NODE_ID", "")
    contrib_tok = (config.get("COGNIA_CONTRIBUTOR_TOKEN", "")
                   or os.environ.get("COGNIA_CONTRIBUTOR_TOKEN", ""))

    if not coord_url:
        print("Sin coordinador configurado (COGNIA_COORDINATOR_URL).")
        print("Registra este equipo primero: cognia install-weights --coordinator <URL>")
        return

    # Tabla de tiers (que gana cada nivel de contribucion)
    try:
        with urllib.request.urlopen(f"{coord_url}/api/tiers", timeout=5) as r:
            tiers = json.loads(r.read()).get("tiers", {})
        print(f"Tiers de contribucion ({coord_url})")
        print("-" * 64)
        for name, t in tiers.items():
            modelos = ", ".join(t["allowed_models"]) if t["allowed_models"] else "-"
            if modelos == "*":
                modelos = "todos"
            print(f"  {name:<9} >={t['min_params_b']:.1f}B  {t['rpm']:>3} RPM  modelos: {modelos}")
    except Exception as exc:
        print(f"No se pudo consultar los tiers: {exc}")
        return

    # Ledger propio (requiere estar registrado)
    if not node_id:
        print()
        print("Este equipo no esta registrado como nodo (sin COGNIA_NODE_ID).")
        return
    try:
        req = urllib.request.Request(
            f"{coord_url}/api/contribution/{node_id}",
            headers={"X-Contributor-Token": contrib_tok} if contrib_tok else {},
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            entry = json.loads(r.read())
        print()
        print(f"Tu contribucion (node {node_id[:12]}...)")
        print("-" * 64)
        print(f"  Parametros aportados : {entry['total_params_b']:.3f}B")
        print(f"  Tier                 : {entry['tier']}")
        print(f"  Requests servidos    : {entry['requests_served']}")
        rpm = entry.get("tier_info", {}).get("rpm")
        if rpm is not None:
            print(f"  Limite               : {rpm} RPM")
    except Exception as exc:
        print()
        print(f"No se pudo consultar tu ledger: {exc}")


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


def _cmd_flota() -> int:
    """Levanta/consulta/detiene la flota por roles (cognia/flota.py).

    Antes esto solo existia como scripts/servir_flota.py, que no viaja en el
    wheel: el doctor instalado pedia "arranca la flota" con una orden que el
    usuario instalado no tenia (WP6 2026-08-09)."""
    from cognia.flota import main as flota_main
    return flota_main(sys.argv[2:])


def _cmd_bbrain() -> None:
    """Regenera bbrain.md introspectando el entorno vivo.

    DONDE se escribe depende de como esta instalada Cognia: en el repo (hay
    .git) va a la raiz del repo, que es lo que espera el que lo lee versionado.
    Instalada por pip, la "raiz" es site-packages: escribir ahi ensucia el
    entorno, suele ser de solo lectura (Program Files, entornos gestionados) y
    el usuario nunca encuentra el archivo. En ese caso va a COGNIA_HOME
    (~/.cognia), que ya es el sitio de todo lo que Cognia escribe."""
    from cognia.bbrain import generate_bbrain, write_bbrain
    root = Path(__file__).parent.parent
    destino = _ruta_bbrain(root)
    if destino.parent == root:
        path = write_bbrain(root)
    else:
        destino.parent.mkdir(parents=True, exist_ok=True)
        # La introspeccion sigue mirando el arbol instalado (root); solo cambia
        # el destino de la escritura.
        destino.write_text(generate_bbrain(root), encoding="utf-8")
        path = destino
    print(f"bbrain.md regenerado: {path}")


def _ruta_bbrain(root: Path) -> Path:
    """Donde va bbrain.md: raiz del repo si es un checkout, si no COGNIA_HOME."""
    if (Path(root) / ".git").exists():
        return Path(root) / "bbrain.md"
    from cognia.first_run import COGNIA_HOME
    return Path(COGNIA_HOME) / "bbrain.md"


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
    print(f"Backend local (GGUF): configurado ({gguf})")
    # 8080: puerto unico del backend (ver node/llama_backend._DEFAULT_PORT y
    # scripts/servir_flota.py). Antes decia 8088 y reportaba "no corriendo"
    # aunque la flota estuviera servida.
    port = os.environ.get("LLAMA_SERVER_PORT", "8080")
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2)
        print(f"  llama-server: corriendo en 127.0.0.1:{port}")
    except Exception:
        print(f"  llama-server: no corriendo (arranca on-demand al usar el REPL)")
        return

    # Lo que el server SIRVE, que puede no ser lo que config.env dice.
    # 2026-08-15: con Nemotron servido en :8080, `cognia status` imprimia
    # "Qwythos" porque leia la CONFIGURACION en vez del server vivo. Un
    # estado que informa del modelo equivocado es peor que no informar: es
    # exactamente la averia historica del :8088 (un server rancio atribuido
    # al combo que no era), y hoy la volvio a producir el propio comando de
    # diagnostico.
    try:
        from cognia.backend_activo import props
        p = props(f"http://127.0.0.1:{port}", forzar=True) or {}
    except Exception as exc:
        print(f"  (no pude leer /props: {exc})")
        return
    servido = p.get("modelo") or "?"
    n_ctx = p.get("n_ctx")
    print(f"  SIRVIENDO   : {servido}"
          + (f"  (ventana {int(n_ctx):,} tokens)" if n_ctx else ""))
    import os.path as _op
    if servido != "?" and _op.basename(str(gguf)).lower() != servido.lower():
        print(f"  OJO: la configuracion apunta a {_op.basename(str(gguf))} "
              f"pero el server sirve OTRO modelo. Manda el servido.")


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
  empezar / start    EL CAMINO UNICO para dejar Cognia lista: instala lo que falte,
                     verifica el backend y abre el REPL. Si no sabes que correr, esto.
  (ninguno)          Iniciar REPL (lanza wizard en primer uso)
  doctor             Diagnostico de la instalacion (backend GGUF, flota, velocidad)
  init               Re-ejecutar wizard de configuracion
  modo               Ver o cambiar el modo (local/compartido/memoria) y personalizacion
  install-model      Descargar GGUF 3B + llama-server + expertos (recomendado)
  install-weights    Descargar shards y configurar este dispositivo como nodo
  server             Servidor web FastAPI (puerto 8000)
  node               Iniciar como nodo del swarm distribuido
  coordinator        Iniciar coordinador del swarm (puerto 8001)
  status             Estado del backend local (GGUF), swarm y Ollama
  flota              Flota por roles: arrancar [combo] | estado | parar
  leave              Salir de la red y liberar el fragmento alojado
  contribucion       Tu ledger en la economia del enjambre (tier, params, RPM)
  bbrain             Regenerar bbrain.md (doc viva del repo y su entorno)
  fleet              Estado de la flota local de modelos GGUF
  tui                Interfaz TUI a pantalla completa (textual)
  voz                Asistente de voz Jarvis (requiere extra [voz])
  remoto             Servidor de control remoto desde el movil
  tutor              Tutor web que ensena cualquier tema (localhost:8899)  [--lan]
  rlm <ruta> "<pregunta>"  Pregunta sobre contexto mas grande que la ventana
  responder "<pregunta>"   Responde con CONFIANZA (no si/no); si le falta,
                           investiga en la web y cita. [--segundos N]
  --version          Mostrar la version instalada (solo el numero)
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

    cmd = sys.argv[1] if len(sys.argv) > 1 else ""

    if cmd in ("--version", "-V", "version"):
        # ANTES de apply_config: la version es la unica salida esperada
        # (el launcher y el check de instalacion limpia la capturan) y
        # apply_config puede imprimir avisos [config] que la ensuciarian.
        from cognia import __version__
        print(__version__)
        return

    from cognia.first_run import apply_config
    apply_config()

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
    elif cmd == "doctor":
        # Estaba documentado en README y el propio REPL manda aqui cuando el
        # backend falla ("revisa el backend con: cognia doctor", cli.py:9822 y
        # :9847), pero el dispatcher nunca tuvo la rama: respondia "Comando
        # desconocido: 'doctor'". El modulo existe desde siempre y solo se
        # podia correr con `python -m cognia.doctor`.
        from cognia.doctor import main as _doc_main
        raise SystemExit(_doc_main())
    elif cmd in ("empezar", "start"):
        # Camino unico de arranque (cognia/arranque.py). Import perezoso y con
        # mensaje legible: si el modulo no esta en esta instalacion, el usuario
        # tiene que ver QUE falta, no un ImportError crudo con traceback.
        try:
            from cognia.arranque import main as _arranque_main
        except Exception as exc:
            print(f"[cognia] 'empezar' no esta disponible en esta instalacion: {exc}")
            print("  Mientras tanto: 'cognia install-model' y luego 'cognia doctor'.")
            raise SystemExit(1)
        raise SystemExit(_arranque_main(sys.argv[2:]))
    elif cmd == "leave":
        _cmd_leave()
    elif cmd in ("contribucion", "contribution"):
        _cmd_contribucion()
    elif cmd == "bbrain":
        _cmd_bbrain()
    elif cmd == "fleet":
        _cmd_fleet()
    elif cmd == "flota":
        raise SystemExit(_cmd_flota())
    elif cmd == "tui":
        from cognia.tui.__main__ import main as _tui_main
        _tui_main()
    elif cmd == "voz":
        from cognia.voz.jarvis import main as _voz_main
        raise SystemExit(_voz_main(sys.argv[2:]))
    elif cmd == "remoto":
        from cognia.remoto.servidor import main as _remoto_main
        raise SystemExit(_remoto_main())
    elif cmd in ("tutor", "estudiar"):
        from cognia.tutor.servidor import main as _tutor_main
        raise SystemExit(_tutor_main(sys.argv[2:]))
    elif cmd == "rlm":
        # Modo RLM por CLI directa: pregunta sobre un contexto (archivo o
        # directorio) que no entra en la ventana del modelo. El informe del
        # contexto efectivo se imprime SIEMPRE (parte del contrato del modo).
        if len(sys.argv) < 4:
            print('Uso: cognia rlm <ruta> "<pregunta>"')
            sys.exit(2)
        try:
            # Import perezoso: si el modulo RLM no carga, el resto de la CLI
            # sigue funcionando y el usuario ve el motivo real.
            from cognia.agent.rlm import correr_rlm
        except Exception as exc:
            print(f"[cognia] el modo RLM no esta disponible: {exc}")
            sys.exit(1)
        _res = correr_rlm(" ".join(sys.argv[3:]), sys.argv[2], print_fn=print)
        print(_res.get("texto") or "")
        _informe = _res.get("informe") or ""
        if _informe:
            print(_informe)
        sys.exit(0 if _res.get("ok") else 1)
    elif cmd in ("responder", "confianza"):
        # Responder con CONFIANZA en vez de con si/no, y si no la hay, ir a
        # buscar. El grado NO se le pregunta al modelo (contesta 0,9 casi
        # siempre): sale de senales verificables -- cita literal comprobada
        # en su pagina, dominios independientes, contradicciones.
        if len(sys.argv) < 3:
            print('Uso: cognia responder "<pregunta>" [--segundos N]')
            sys.exit(2)
        _seg = 120.0
        _args = sys.argv[2:]
        if "--segundos" in _args:
            _i = _args.index("--segundos")
            try:
                _seg = float(_args[_i + 1])
            except (IndexError, ValueError):
                print("--segundos necesita un numero")
                sys.exit(2)
            _args = _args[:_i] + _args[_i + 2:]
        try:
            from cognia.search.responder import responder as _responder
        except Exception as exc:
            print(f"[cognia] el modo responder no esta disponible: {exc}")
            sys.exit(1)
        _v = _responder(" ".join(_args), presupuesto_s=_seg)
        print(_v.frase())
        if _v.fuentes:
            print(f"fuentes: {', '.join(_v.fuentes)}")
        # Exit code con SIGNIFICADO: 0 respondio, 3 no le alcanzo la
        # confianza (no es un error del programa, es un no-se honesto).
        sys.exit(0 if _v.accion == "responder" else 3)
    elif cmd == "":
        from cognia.first_run import run_wizard
        run_wizard(force=False)
        # Chequeo de arranque (2026-07-25): decir QUE backend hay antes de que
        # el usuario escriba nada. "Cognia degrada en silencio" llevaba meses
        # escrito como leccion y volvio a pasar igual, porque una leccion en
        # prosa no se ejecuta. Esta es la misma leccion como chequeo.
        try:
            from cognia import backend_activo
            backend_activo.chequeo_arranque()
        except Exception:
            pass
        from cognia.cli import repl
        repl()
    else:
        print(f"Comando desconocido: '{cmd}'. Usa 'cognia help' para ver opciones.")
        sys.exit(1)


if __name__ == "__main__":
    main()
