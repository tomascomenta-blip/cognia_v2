"""
cognia/first_run.py
===================
First-run setup wizard. Runs once when no config exists at ~/.cognia/config.env.

Detects whether the user wants to run standalone or join the distributed network.
In network mode, downloads the shard assigned by the coordinator automatically.
"""

from __future__ import annotations

import os
import sys
import json
import shutil
import subprocess
import urllib.request
import urllib.error
from pathlib import Path


# ── Paths ─────────────────────────────────────────────────────────────────────

# Overrideable por env (portabilidad + tests de instalación limpia): en una
# máquina nueva no hace falta setear nada, default = ~/.cognia
COGNIA_HOME  = Path(os.environ["COGNIA_HOME"]) if os.environ.get("COGNIA_HOME") \
    else Path.home() / ".cognia"
CONFIG_FILE  = COGNIA_HOME / "config.env"
SHARDS_DIR   = COGNIA_HOME / "shards"
DATA_DIR     = COGNIA_HOME / "data"
FIRST_RUN_OK = COGNIA_HOME / ".setup_done"

HF_REPO   = "Qwen/Qwen2.5-Coder-3B-Instruct"
MODEL_KEY = "qwen-coder-3b-q4"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        answer = input(f"{prompt}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)
    return answer or default


def _ask_yn(prompt: str, default: bool = True) -> bool:
    default_str = "Y/n" if default else "y/N"
    try:
        answer = input(f"{prompt} [{default_str}]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)
    if not answer:
        return default
    return answer in ("y", "yes", "si", "s")


def _http_get(url: str, timeout: int = 5) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read())


def _coordinator_reachable(url: str) -> bool:
    try:
        _http_get(f"{url.rstrip('/')}/health", timeout=4)
        return True
    except Exception:
        try:
            _http_get(f"{url.rstrip('/')}/ready", timeout=4)
            return True
        except Exception:
            return False


def _hf_cli_available() -> bool:
    return shutil.which("huggingface-cli") is not None


def _safetensors_available() -> bool:
    try:
        import safetensors   # noqa: F401
        return True
    except ImportError:
        return False


# ── Weight download ────────────────────────────────────────────────────────────

def _download_weights(hf_token: str = "") -> Path:
    """Download Qwen2.5-Coder-3B from HuggingFace and convert to INT4 shards."""
    download_dir = COGNIA_HOME / "hf_cache" / "qwen"
    out_dir      = SHARDS_DIR / MODEL_KEY
    out_dir.mkdir(parents=True, exist_ok=True)

    # Check if already converted
    if (out_dir / "shard_0.npz").exists():
        print(f"  Shards ya existen en {out_dir}")
        return out_dir

    # Need safetensors for conversion
    if not _safetensors_available():
        print("  Instalando safetensors...")
        subprocess.check_call([sys.executable, "-m", "pip", "install",
                               "safetensors", "huggingface_hub", "-q"])

    # Download from HuggingFace
    download_dir.mkdir(parents=True, exist_ok=True)
    print(f"\n  Descargando {HF_REPO} (~6GB)...")
    print("  Esto puede tardar varios minutos dependiendo de tu conexion.")

    cmd = [
        sys.executable, "-m", "huggingface_hub", "snapshot_download",
        "--repo-id", HF_REPO,
        "--local-dir", str(download_dir),
        "--repo-type", "model",
    ]
    if hf_token:
        cmd += ["--token", hf_token]

    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError:
        # Fallback to huggingface-cli if available
        if _hf_cli_available():
            cli_cmd = ["huggingface-cli", "download", HF_REPO,
                       "--local-dir", str(download_dir)]
            if hf_token:
                cli_cmd += ["--token", hf_token]
            subprocess.check_call(cli_cmd)
        else:
            raise

    # Convert to INT4 shards
    print(f"\n  Convirtiendo a INT4 shards -> {out_dir}")
    print("  Esto puede tardar 5-15 minutos...")

    # Find the convert script relative to this file or installed package
    script = _find_convert_script()
    if script:
        subprocess.check_call([
            sys.executable, str(script),
            "--hf-dir",  str(download_dir),
            "--out-dir", str(out_dir),
        ])
    else:
        print("  [ERROR] No se encontro convert_hf_to_shards.py")
        print("  Ejecuta manualmente:")
        print(f"    python scripts/convert_hf_to_shards.py --hf-dir {download_dir} --out-dir {out_dir}")
        sys.exit(1)

    print(f"  Shards listos en {out_dir}")
    return out_dir


def _find_convert_script() -> Path | None:
    """Find convert_hf_to_shards.py relative to the package or installed location."""
    candidates = [
        Path(__file__).parent.parent / "scripts" / "convert_hf_to_shards.py",
        Path(sys.prefix) / "scripts" / "cognia_convert_shards.py",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _download_npz_shards_standalone(hf_token: str = "") -> Path:
    """Download the 4 pre-built INT4 .npz shards for standalone (local) inference."""
    _root = Path(__file__).parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
    from node.downloader import download_npz_shard
    from shattering.model_constants import QWEN25_CODER_3B

    n_shards  = QWEN25_CODER_3B["n_shards"]
    shard_dir = SHARDS_DIR / MODEL_KEY
    shard_dir.mkdir(parents=True, exist_ok=True)

    def _progress(pct: float, msg: str) -> None:
        bar = "#" * int(pct * 30) + "-" * (30 - int(pct * 30))
        print(f"\r  [{bar}] {pct:5.1%} {msg[:40]}", end="", flush=True)

    for i in range(n_shards):
        dest = shard_dir / f"shard_{i}.npz"
        print(f"\n  Shard {i}/{n_shards - 1}:")
        result = download_npz_shard(i, str(dest), hf_token=hf_token, on_progress=_progress)
        print()
        if not result.ok:
            raise RuntimeError(f"Shard {i}: {result.error}")
        print(f"  {result.size_mb:.0f} MB")

    # tokenizer.json REAL del modelo (fix 2026-07-08): sin este archivo el
    # pipeline de shards caia a LightTokenizer (simulacion) y Qwen "no
    # funcionaba" aunque los pesos estuvieran descargados.
    tok_dest = shard_dir / "tokenizer.json"
    if not tok_dest.is_file():
        try:
            from huggingface_hub import hf_hub_download
            print("  Descargando tokenizer.json...")
            hf_hub_download(repo_id=HF_REPO, filename="tokenizer.json",
                            local_dir=str(shard_dir), token=hf_token or None)
        except Exception as exc:
            print(f"  [WARN] tokenizer.json no descargado ({exc}); "
                  f"la inferencia por shards necesita ese archivo para funcionar.")

    print(f"\n  Shards en {shard_dir}")
    return shard_dir


# ── Config file ───────────────────────────────────────────────────────────────

def _write_config(vars: dict[str, str]) -> None:
    """Escribe config.env MERGEANDO con lo existente (nunca lo pisa entero).

    Fix auditoria 2026-07-15: el wizard reescribia el archivo con SOLO sus
    claves y borraba LLAMA_GGUF_PATH/LLAMA_SERVER_PATH que `cognia
    install-model` acababa de persistir (y al reves) — correr los dos flujos
    en cualquier orden rompia al otro."""
    COGNIA_HOME.mkdir(parents=True, exist_ok=True)
    combinado = _load_config()
    combinado.update({k: v for k, v in vars.items() if v})
    lines = [f"{k}={v}\n" for k, v in combinado.items() if v]
    CONFIG_FILE.write_text("".join(lines), encoding="utf-8")
    print(f"\n  Configuracion guardada en {CONFIG_FILE}")


def _load_config() -> dict[str, str]:
    if not CONFIG_FILE.exists():
        return {}
    config = {}
    for line in CONFIG_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            config[k.strip()] = v.strip()
    return config


def apply_config() -> None:
    """Load ~/.cognia/config.env into os.environ (call at startup).

    Una env var pre-existente GANA sobre config.env (permite overrides por
    sesion), pero si difiere se AVISA una linea: una var stale del sistema
    pisando un config.env fresco era invisible y muy dificil de diagnosticar
    (auditoria 2026-07-15; el caso real: LLAMA_LORA_PATH de User mataba el
    fleet sin sintoma)."""
    config = _load_config()
    for k, v in config.items():
        if k not in os.environ:
            os.environ[k] = v
        elif os.environ[k] != v and k.startswith(("LLAMA_", "COGNIA_",
                                                  "HEAVY_CODE_", "SHARD_")):
            print(f"  [config] {k} del entorno "
                  f"({os.environ[k][:40]!r}) pisa el valor de config.env "
                  f"({v[:40]!r}); si no es a proposito, borra la env var.")
    # El loop de arriba solo ve claves PRESENTES en config.env: una var
    # peligrosa residual del sistema que no este en el archivo seguia matando
    # el fleet en mudo (el caso exacto de la auditoria: LLAMA_LORA_PATH de
    # User aplica UN adapter estatico y desactiva el hot-swap de expertos).
    for k in ("LLAMA_LORA_PATH",):
        if k in os.environ and k not in config:
            print(f"  [config] {k} viene del entorno del sistema (no de "
                  f"config.env): fija un solo adapter y DESACTIVA el fleet "
                  f"de expertos; si no es a proposito, borra la env var.")


def set_config_value(key: str, value: str) -> None:
    """
    Persist a single key=value in ~/.cognia/config.env, updating it in place if
    present and preserving every other line (including comments). Also reflects
    it in os.environ so it takes effect immediately this session.
    """
    COGNIA_HOME.mkdir(parents=True, exist_ok=True)
    out_lines: list[str] = []
    found = False
    if CONFIG_FILE.exists():
        for line in CONFIG_FILE.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                k = stripped.partition("=")[0].strip()
                if k == key:
                    out_lines.append(f"{key}={value}")
                    found = True
                    continue
            out_lines.append(line)
    if not found:
        out_lines.append(f"{key}={value}")
    CONFIG_FILE.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    os.environ[key] = value


# ── Main wizard ───────────────────────────────────────────────────────────────

def run_wizard(force: bool = False) -> None:
    """
    Interactive first-run wizard.
    Safe to call every startup — skips if already configured unless force=True.
    """
    if FIRST_RUN_OK.exists() and not force:
        return

    print("\n" + "=" * 55)
    print("  Cognia -- Bienvenido")
    print("=" * 55)
    print("""
Cognia es una IA que corre en TUS equipos. Tus conversaciones
nunca salen de aca. Elegi como queres usarla:
""")

    print("  1. Local  (este equipo)             [recomendado]")
    print("     Descarga el modelo y lo corre en este equipo.")
    print("     Funciona sin internet. La opcion mas simple.")
    print()
    print("  2. Compartido  (red local)")
    print("     Varios equipos de tu red juntan su memoria para")
    print("     correr un modelo mas grande entre todos.")
    print()
    print("  3. Solo memoria  (sin modelo de IA)")
    print("     Aprendizaje, grafo de conocimiento y memoria, sin LLM.")
    print()

    mode = _ask("Elegi una opcion (1/2/3)", default="1")

    config: dict[str, str] = {}
    COGNIA_HOME.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SHARDS_DIR.mkdir(parents=True, exist_ok=True)
    config["COGNIA_DATA_DIR"] = str(DATA_DIR)

    if mode == "2":
        config["COGNIA_RUN_MODE"] = "compartido"
        _wizard_join_network(config)
    elif mode == "3":
        config["COGNIA_RUN_MODE"] = "memoria"
        _wizard_memory_only(config)
    else:
        mode = "1"
        config["COGNIA_RUN_MODE"] = "local"
        _wizard_standalone(config)

    _wizard_personalize(config)

    _write_config(config)
    FIRST_RUN_OK.touch()
    _wizard_print_done(mode, config)


def _wizard_personalize(config: dict) -> None:
    """Optional personalization: name, reply language, reply style.

    Everything is Enter-to-skip. Persisted to config.env and folded into the
    system prompt by cognia/user_prefs.personalize_prompt at chat time.
    """
    print("\n-- Personalizacion (opcional, Enter para saltar) --")

    name = _ask("Tu nombre")
    if name:
        config["COGNIA_USER_NAME"] = name

    lang = _ask("Idioma de las respuestas (espanol/ingles)", default="espanol").strip().lower()
    if lang in ("espanol", "ingles"):
        config["COGNIA_LANG"] = lang

    print("  Estilo de respuesta:  1) breve   2) detallada   3) tecnica   4) amigable")
    style_map = {"1": "breve", "2": "detallada", "3": "tecnica", "4": "amigable"}
    s = _ask("Elegi estilo (Enter para el default)", default="").strip().lower()
    if s in style_map:
        config["COGNIA_STYLE"] = style_map[s]
    elif s in style_map.values():
        config["COGNIA_STYLE"] = s


def _wizard_join_network(config: dict) -> None:
    print("\n-- Compartido (red local) --")
    print("Tu equipo aloja un fragmento del modelo; entre varios equipos")
    print("de la red corren un modelo mas grande del que entraria en uno solo.")
    print("El coordinador asigna que fragmento le toca a cada equipo.\n")

    coord_url = _ask("URL del coordinador")
    if not coord_url:
        print("  Se requiere la URL del coordinador.")
        print("  Si no tienes una, vuelve a ejecutar 'cognia init' y elige el modo 2.")
        sys.exit(1)

    config["COGNIA_COORDINATOR_URL"] = coord_url.rstrip("/")

    print(f"\n  Verificando coordinador en {coord_url}...")
    if _coordinator_reachable(coord_url):
        print("  Coordinador accesible.")
    else:
        print("  [WARN] El coordinador no responde ahora.")
        if not _ask_yn("  Continuar de todos modos?", default=False):
            sys.exit(0)

    if _ask_yn("\nDescargar tu fragmento asignado ahora (~300MB)?", default=True):
        _download_shard_from_coordinator(coord_url, config)

    if _ask_yn("\nConfigurar Ollama como fallback cuando la red no este disponible?", default=False):
        config["OLLAMA_URL"]   = _ask("URL de Ollama", default="http://localhost:11434")
        config["COGNIA_MODEL"] = _ask("Modelo Ollama", default="llama3.2")


def _wizard_standalone(config: dict) -> None:
    print("\n-- Local (este equipo) --")
    print("Cognia descarga el modelo y lo corre aca, sin cuenta.")
    print("Recomendado: GGUF + llama-server + expertos (~2GB, el stack validado).\n")

    # Camino DEFAULT: stack GGUF (llama-server b9391 + Q4_K_M + fleet de
    # expertos LoRA), el unico con gates medidos (GATES_CLI_VNEXT.md). Los
    # shards NPZ quedan como opcion avanzada: su pipeline caia a un tokenizer
    # de simulacion cuando faltaba tokenizer.json / transformers ("el modelo
    # esta descargado pero Qwen no funciona").
    if _ask_yn("Descargar el modelo Qwen2.5-Coder-3B GGUF + expertos (~2GB)?", default=True):
        hf_token = _ask("HuggingFace token (opcional, Enter para omitir)", default="")
        try:
            from cognia.model_install import install_model
            install_model(hf_token=hf_token)
            return   # install_model ya persistio LLAMA_GGUF_PATH/LLAMA_SERVER_PATH
        except Exception as exc:
            print(f"\n  [ERROR] Instalacion GGUF fallo: {exc}")
            print("  Podes reintentar luego con: cognia install-model")

    if _ask_yn("\n(Avanzado) Descargar los 4 shards NPZ (~1.2GB) en su lugar?", default=False):
        hf_token = _ask("HuggingFace token (opcional, Enter para omitir)", default="")
        try:
            shard_dir = _download_npz_shards_standalone(hf_token)
            config["SHARD_WEIGHTS_DIR"] = str(shard_dir)
        except Exception as exc:
            print(f"\n  [ERROR] Descarga fallo: {exc}")
            print("  Puedes descargar los pesos luego con: cognia install-weights --standalone")

    if _ask_yn("\nConfigurar Ollama como fallback adicional?", default=False):
        config["OLLAMA_URL"]   = _ask("URL de Ollama", default="http://localhost:11434")
        config["COGNIA_MODEL"] = _ask("Modelo Ollama", default="llama3.2")


def _wizard_memory_only(config: dict) -> None:
    print("\n-- Solo memoria --")
    print("Cognia funcionara sin LLM: aprendizaje, grafo y memoria activos.")
    print("Puedes activar un LLM mas adelante con: cognia init\n")


def _wizard_print_done(mode: str, config: dict) -> None:
    run_mode = config.get("COGNIA_RUN_MODE", "local")
    is_shared = run_mode == "compartido"

    print("\n" + "=" * 55)
    print("  Listo. Cognia esta configurado.")
    print("=" * 55)
    name = config.get("COGNIA_USER_NAME")
    print(f"\n  Modo: {'Compartido (red local)' if is_shared else ('Solo memoria' if run_mode == 'memoria' else 'Local (este equipo)')}")
    if name:
        print(f"  Hola, {name}.")
    print(f"  Datos en: {COGNIA_HOME}")
    print()
    print("  Para empezar a chatear, ejecuta:")
    print("      cognia")
    print()
    print("  Otros comandos utiles:")
    print("    cognia modo         -- ver o cambiar el modo y la personalizacion")
    if is_shared:
        print("    cognia node         -- contribuir tu fragmento a la red")
        print("    cognia leave        -- salir de la red")
    print("    cognia init         -- repetir esta configuracion")
    print()
    if is_shared and config.get("COGNIA_NODE_SHARD") is not None:
        print("  Para contribuir tu fragmento a la red, en otra terminal:")
        print("      cognia node")
        print()


def _download_shard_from_coordinator(coord_url: str, config: dict) -> None:
    """Register with coordinator and download the assigned shard."""
    try:
        import platform

        hardware = platform.processor()[:40] or platform.machine()
        try:
            import psutil
            hardware += f" | {psutil.virtual_memory().total / 1e9:.1f}GB RAM"
        except ImportError:
            pass

        reg_url = f"{coord_url.rstrip('/')}/api/node/register"
        data    = json.dumps({"hardware_info": hardware, "model_name": MODEL_KEY}).encode()
        req     = urllib.request.Request(
            reg_url, data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            result = json.loads(r.read())

        shard     = result["shard"]
        node_id   = result["node_id"]
        contrib_t = result.get("contributor_token", "")

        print(f"  Registrado -- shard asignado: {shard} (node_id: {node_id[:8]}...)")
        print(f"  Fragmento shard {shard} sera alojado en este dispositivo.")

        config["COGNIA_NODE_ID"] = node_id
        if contrib_t:
            config["COGNIA_CONTRIBUTOR_TOKEN"] = contrib_t

        # Use the downloader if available
        shard_dir = SHARDS_DIR / MODEL_KEY
        shard_dir.mkdir(parents=True, exist_ok=True)

        # Check if shard already exists
        if (shard_dir / f"shard_{shard}.npz").exists():
            print(f"  Shard {shard} ya existe localmente.")
            config["SHARD_WEIGHTS_DIR"] = str(shard_dir)
            config["COGNIA_NODE_SHARD"] = str(shard)
            return

        try:
            _root = Path(__file__).parent.parent
            if str(_root) not in sys.path:
                sys.path.insert(0, str(_root))
            from node.downloader import download_npz_shard

            hf_token = _ask("HuggingFace token (Enter para omitir)", default="")

            def _progress(pct: float, msg: str):
                bar = "#" * int(pct * 30) + "-" * (30 - int(pct * 30))
                print(f"\r  [{bar}] {pct:5.1%} {msg[:40]}", end="", flush=True)

            npz_dest = shard_dir / f"shard_{shard}.npz"
            print(f"\n  Descargando shard {shard} (~300MB)...")
            result_dl = download_npz_shard(
                shard_index=shard,
                dest_path=str(npz_dest),
                hf_token=hf_token,
                on_progress=_progress,
            )
            print()

            if result_dl.ok:
                print(f"  Shard {shard} listo ({result_dl.size_mb:.0f}MB)")
                config["SHARD_WEIGHTS_DIR"] = str(shard_dir)
                config["COGNIA_NODE_SHARD"] = str(shard)
            else:
                print(f"  [WARN] Descarga fallo: {result_dl.error}")
                print("  El nodo arrancara en modo simulacion hasta que los pesos esten disponibles.")

        except ImportError:
            print("  [WARN] Downloader no disponible. Descarga los pesos manualmente.")

    except Exception as exc:
        print(f"  [WARN] No se pudo registrar con el coordinador: {exc}")
        print("  La configuracion se guardo. El nodo se registrara al arrancar.")


# ── Standalone entry point ────────────────────────────────────────────────────

def main():
    """Entry point for `cognia init` command."""
    run_wizard(force=True)


if __name__ == "__main__":
    main()
