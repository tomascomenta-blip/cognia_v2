# -*- coding: utf-8 -*-
"""
cognia/model_install.py
=======================
Instalación del stack de inferencia VALIDADO (2026-07-08, GATES_CLI_VNEXT.md):
GGUF Q4_K_M + llama-server b9391 pineado + fleet de expertos LoRA (adapters.json).

Es el camino DEFAULT de una instalación limpia (reemplaza a los shards NPZ, cuyo
pipeline caía a un tokenizer de simulación cuando faltaban tokenizer.json /
transformers — el bug "el modelo está descargado pero Qwen no funciona").

Todo va a ~/.cognia (portable a cualquier máquina):
  ~/.cognia/models/qwen-coder-3b-q4/qwen2.5-coder-3b-instruct-q4_k_m.gguf
  ~/.cognia/models/qwen-coder-3b-q4/adapters.json + cognia3b_v2_f16.gguf
  ~/.cognia/bin/llama-b9391/llama-server.exe (+ dlls)
  ~/.cognia/config.env: LLAMA_GGUF_PATH + LLAMA_SERVER_PATH (apply_config()
  las carga al arrancar; node/llama_backend las lee).

Uso CLI:  cognia install-model  [--skip-gguf] [--skip-server] [--skip-fleet]
          [--skip-portero] [--with-heavy-code]   (7B de código, ~4.7 GB, opt-in)
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

from cognia.first_run import COGNIA_HOME, set_config_value

MODELS_DIR = COGNIA_HOME / "models" / "qwen-coder-3b-q4"
BIN_DIR = COGNIA_HOME / "bin" / "llama-b9391"

# GGUF oficial de Qwen (verificado 2026-07-08 vía API de HF)
GGUF_REPO = "Qwen/Qwen2.5-Coder-3B-Instruct-GGUF"
GGUF_FILE = "qwen2.5-coder-3b-instruct-q4_k_m.gguf"

# llama-server pineado b9391 (el binario del deploy; b9414 midió -37%)
LLAMA_TAG = "b9391"
_LLAMA_ASSETS = {
    ("Windows", "AMD64"): f"llama-{LLAMA_TAG}-bin-win-cpu-x64.zip",
    ("Windows", "ARM64"): f"llama-{LLAMA_TAG}-bin-win-cpu-arm64.zip",
}
LLAMA_RELEASE_BASE = f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_TAG}"

# Fleet de expertos (adapters LoRA GGUF): release del repo de Cognia.
# Override con COGNIA_FLEET_URL (dir base que contiene adapters.json).
FLEET_URL_DEFAULT = ("https://github.com/tomascomenta-blip/cognia_v2/"
                     "releases/download/fleet-v1")

# Portero 0.5B (PREREG_PORTERO_FASE2): modelo APARTE que atiende los turnos
# triviales del chat (saludo/identidad/cortesía) a ~4× la velocidad del 3B.
# Base GGUF oficial de Qwen (HF) + LoRA de identidad del release fleet-v1.
# Q8_0 y no Q4_K_M: con Q4 el G3 en deploy cae 95→80 (medido; el error de
# cuantización pesa más en un 0.5B), con Q8_0 da 90 y el decode casi no baja.
PORTERO_DIR = COGNIA_HOME / "models" / "qwen-0.5b-portero"
PORTERO_GGUF_REPO = "Qwen/Qwen2.5-0.5B-Instruct-GGUF"
PORTERO_GGUF_FILE = "qwen2.5-0.5b-instruct-q8_0.gguf"
PORTERO_LORA_FILE = "cognia_portero05b_f16.gguf"

# Especialista de CAPACIDAD 7B para código duro (MoM fase 4): base pura Qwen2.5-
# Coder-7B Q4_K_M (~4.7 GB). OPT-IN (--with-heavy-code): son 7× el 3B, no se
# fuerza en cada instalación. El escalado reactivo 3B→7B sube el código duro
# 37.5→57.5% pass@1 (+20pp medido). Sin él, el CLI corre igual (cae al 3B).
HEAVY_DIR = COGNIA_HOME / "models" / "qwen-coder-7b-q4"
HEAVY_GGUF_REPO = "Qwen/Qwen2.5-Coder-7B-Instruct-GGUF"
HEAVY_GGUF_FILE = "qwen2.5-coder-7b-instruct-q4_k_m.gguf"


def _progreso(nombre: str):
    ultimo = [-1]

    def hook(bloques, tam_bloque, total):
        done = bloques * tam_bloque
        if total > 0:
            pct = min(100, done * 100 // total)
            # solo cada 5pp: sin esto un download grande spamea miles de
            # lineas \r en consolas no-TTY (logs, subprocess)
            if pct - ultimo[0] >= 5 or pct == 100:
                ultimo[0] = pct
                print(f"\r  {nombre}: {pct}% ({done // (1 << 20)} MB)", end="", flush=True)
    return hook


def _descarga(url: str, dest: Path) -> Path:
    """Descarga con timeout de socket y limpieza del .part ante fallo
    (auditoria 2026-07-15: urlretrieve sin timeout colgaba con red caida y
    dejaba .part huerfanos que confundian re-corridas)."""
    import socket
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    viejo_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(60)
    try:
        urllib.request.urlretrieve(url, tmp, _progreso(dest.name))
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        raise
    finally:
        socket.setdefaulttimeout(viejo_timeout)
    print()
    tmp.replace(dest)
    return dest


def install_gguf(dest_dir: Path = MODELS_DIR, hf_token: str = "") -> Path:
    """Baja el GGUF Q4_K_M oficial (~1.9 GB) vía huggingface_hub. Idempotente."""
    dest = dest_dir / GGUF_FILE
    if dest.is_file() and dest.stat().st_size > 1 << 30:
        print(f"  GGUF ya presente: {dest}")
        return dest
    from huggingface_hub import hf_hub_download   # dependencia base del paquete
    dest_dir.mkdir(parents=True, exist_ok=True)
    print(f"  Descargando {GGUF_FILE} (~1.9 GB) de {GGUF_REPO}...")
    path = hf_hub_download(repo_id=GGUF_REPO, filename=GGUF_FILE,
                           local_dir=str(dest_dir),
                           token=hf_token or None)
    return Path(path)


def install_llama_server(dest_dir: Path = BIN_DIR) -> Path:
    """Baja y extrae llama-server b9391 para esta plataforma. Idempotente."""
    exe = dest_dir / ("llama-server.exe" if platform.system() == "Windows" else "llama-server")
    if exe.is_file():
        print(f"  llama-server ya presente: {exe}")
        return exe
    clave = (platform.system(), platform.machine().upper())
    asset = _LLAMA_ASSETS.get(clave)
    if asset is None:
        # No-Windows: binario del sistema o el extra pip [llama]
        which = shutil.which("llama-server")
        if which:
            print(f"  llama-server del sistema: {which}")
            return Path(which)
        raise RuntimeError(
            f"No hay binario pineado para {clave}. Instalá llama.cpp del sistema "
            f"o usá: pip install 'cognia-ai[llama]' (llama-cpp-python in-process).")
    url = f"{LLAMA_RELEASE_BASE}/{asset}"
    zpath = dest_dir.parent / asset
    print(f"  Descargando {asset}...")
    _descarga(url, zpath)
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zpath) as z:
        z.extractall(dest_dir)
    zpath.unlink()
    # algunos zips traen los binarios bajo un subdir: aplanar si hace falta
    if not exe.is_file():
        hits = list(dest_dir.rglob(exe.name))
        if hits:
            for f in hits[0].parent.iterdir():
                shutil.move(str(f), str(dest_dir / f.name))
    if not exe.is_file():
        raise RuntimeError(f"el zip {asset} no contenía {exe.name}")
    return exe


def install_fleet(dest_dir: Path = MODELS_DIR) -> int:
    """Baja adapters.json + los adapters GGUF del fleet. Devuelve cuántos quedaron.

    Best-effort: si el release no está publicado todavía, avisa y devuelve 0
    (el CLI funciona igual con la base pelada; el fleet es la mejora medida).
    """
    base = os.environ.get("COGNIA_FLEET_URL", FLEET_URL_DEFAULT).rstrip("/")
    dest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = dest_dir / "adapters.json"
    try:
        _descarga(f"{base}/adapters.json", manifest_path)
    except Exception as exc:
        print(f"  [WARN] fleet no disponible ({exc}); el CLI corre con la base sola.")
        return 0
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"  [WARN] adapters.json ilegible: {exc}")
        manifest_path.unlink(missing_ok=True)
        return 0
    ok = 0
    for entry in data.get("adapters", []):
        f = (entry.get("file") or "").strip()
        if not f or "/" in f or "\\" in f or ".." in f:
            print(f"  [WARN] entrada de manifiesto inválida: {entry!r}")
            continue
        try:
            _descarga(f"{base}/{f}", dest_dir / f)
            ok += 1
        except Exception as exc:
            print(f"  [WARN] no se pudo bajar {f}: {exc}")
    if ok == 0:
        # sin adapters el manifiesto solo mete warnings al arrancar: fuera
        manifest_path.unlink(missing_ok=True)
    return ok


def install_portero(dest_dir: Path = PORTERO_DIR, hf_token: str = "") -> bool:
    """Baja el portero 0.5B: base GGUF de HF (~650 MB) + LoRA del release.

    Best-effort e idempotente: si falta cualquier pieza avisa y devuelve False
    — el CLI funciona igual (el router cae al 3B cuando el portero no está).
    """
    base = dest_dir / PORTERO_GGUF_FILE
    lora = dest_dir / PORTERO_LORA_FILE
    if base.is_file() and base.stat().st_size > 300 << 20:
        print(f"  portero base ya presente: {base}")
    else:
        try:
            from huggingface_hub import hf_hub_download
            dest_dir.mkdir(parents=True, exist_ok=True)
            print(f"  Descargando {PORTERO_GGUF_FILE} (~650 MB) de {PORTERO_GGUF_REPO}...")
            hf_hub_download(repo_id=PORTERO_GGUF_REPO, filename=PORTERO_GGUF_FILE,
                            local_dir=str(dest_dir), token=hf_token or None)
        except Exception as exc:
            print(f"  [WARN] portero base no disponible ({exc}); el chat sigue 100% en el 3B.")
            return False
    if lora.is_file():
        print(f"  portero LoRA ya presente: {lora}")
    else:
        url_base = os.environ.get("COGNIA_FLEET_URL", FLEET_URL_DEFAULT).rstrip("/")
        try:
            _descarga(f"{url_base}/{PORTERO_LORA_FILE}", lora)
        except Exception as exc:
            print(f"  [WARN] LoRA del portero no disponible ({exc}); el chat sigue 100% en el 3B.")
            return False
    return True


def install_heavy_code(dest_dir: Path = HEAVY_DIR, hf_token: str = "") -> Path | None:
    """Baja el 7B de código (~4.7 GB) de HF y persiste HEAVY_CODE_GGUF_PATH.

    Best-effort e idempotente: si falla la descarga avisa y devuelve None — el
    escalado 3B→7B queda inactivo y el código duro se resuelve solo en el 3B
    (heavy_code_backend cae a None). Solo se llama con --with-heavy-code."""
    dest = dest_dir / HEAVY_GGUF_FILE
    if dest.is_file() and dest.stat().st_size > 3 << 30:
        print(f"  7B de código ya presente: {dest}")
        set_config_value("HEAVY_CODE_GGUF_PATH", str(dest))
        return dest
    try:
        from huggingface_hub import hf_hub_download
        dest_dir.mkdir(parents=True, exist_ok=True)
        print(f"  Descargando {HEAVY_GGUF_FILE} (~4.7 GB) de {HEAVY_GGUF_REPO}...")
        path = hf_hub_download(repo_id=HEAVY_GGUF_REPO, filename=HEAVY_GGUF_FILE,
                               local_dir=str(dest_dir), token=hf_token or None)
        set_config_value("HEAVY_CODE_GGUF_PATH", str(path))
        return Path(path)
    except Exception as exc:
        print(f"  [WARN] 7B de código no disponible ({exc}); el código duro se "
              "queda en el 3B (sin escalado).")
        return None


def _check_espacio(with_heavy_code: bool) -> None:
    """Aborta ANTES de descargar si el disco no alcanza (auditoria
    2026-07-15: sin chequeo, la descarga de 1.9-4.7 GB moria a la mitad con
    un error crudo de urllib). Margen 1 GB sobre lo estimado."""
    import shutil as _sh
    necesario = 2_600_000_000 + (5_000_000_000 if with_heavy_code else 0)
    try:
        libre = _sh.disk_usage(str(Path.home())).free
    except Exception:
        return
    if libre < necesario:
        raise RuntimeError(
            f"espacio insuficiente en disco: libres {libre / 1e9:.1f} GB, "
            f"necesarios ~{necesario / 1e9:.1f} GB. Libera espacio y "
            "reintenta cognia install-model.")


def install_model(skip_gguf: bool = False, skip_server: bool = False,
                  skip_fleet: bool = False, skip_portero: bool = False,
                  with_heavy_code: bool = False, hf_token: str = "") -> dict:
    """Instala el stack completo y persiste config.env. Devuelve resumen.

    with_heavy_code (opt-in): baja además el 7B de código (~4.7 GB) para el
    escalado reactivo 3B→7B en código duro (+20pp). Default OFF por el tamaño."""
    resumen = {}
    if not skip_gguf:
        _check_espacio(with_heavy_code)
        gguf = install_gguf(hf_token=hf_token)
        set_config_value("LLAMA_GGUF_PATH", str(gguf))
        resumen["gguf"] = str(gguf)
    if not skip_server:
        try:
            exe = install_llama_server()
            set_config_value("LLAMA_SERVER_PATH", str(exe))
            resumen["llama_server"] = str(exe)
        except RuntimeError as exc:
            print(f"  [WARN] {exc}")
            resumen["llama_server"] = None
    if not skip_fleet:
        resumen["fleet_adapters"] = install_fleet()
    if not skip_portero:
        resumen["portero"] = install_portero(hf_token=hf_token)
    if with_heavy_code:
        hc = install_heavy_code(hf_token=hf_token)
        resumen["heavy_code"] = str(hc) if hc else None
    print("\n  Stack instalado. Arrancá con: cognia")
    return resumen


_FLAGS_VALIDOS = {"--skip-gguf", "--skip-server", "--skip-fleet",
                  "--skip-portero", "--with-heavy-code"}


def main(argv: list[str] | None = None) -> None:
    args = set(argv if argv is not None else sys.argv[1:])
    # un typo en un flag NO puede instalar en silencio otra cosa
    desconocidos = args - _FLAGS_VALIDOS
    if desconocidos:
        print(f"flags desconocidos: {' '.join(sorted(desconocidos))}\n"
              f"validos: {' '.join(sorted(_FLAGS_VALIDOS))}")
        sys.exit(2)
    try:
        install_model(skip_gguf="--skip-gguf" in args,
                      skip_server="--skip-server" in args,
                      skip_fleet="--skip-fleet" in args,
                      skip_portero="--skip-portero" in args,
                      with_heavy_code="--with-heavy-code" in args)
    except Exception as exc:
        # mensaje accionable, no traceback crudo (sin red / 401 / disco)
        print(f"\ninstall-model FALLO: {exc}\n"
              "Revisa: conexion a internet, espacio en disco, y si el modelo "
              "requiere token de HuggingFace (HF_TOKEN). Reintenta con: "
              "cognia install-model")
        sys.exit(1)


if __name__ == "__main__":
    main()
