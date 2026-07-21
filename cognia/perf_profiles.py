"""
cognia/perf_profiles.py
=======================
Perfiles de optimizacion CPU/GPU para el backend llama.cpp.

Cada perfil es un dict de perillas (variable de entorno -> valor). El default
es 'cpu' por directiva del dueno: en maquinas sin GPU real la iGPU medida fue
MAS LENTA que el CPU (ver node/llama_backend.py, 3.8 vs 8.8 tok/s en i3-10110U).

apply_profile() persiste cada perilla en ~/.cognia/config.env via
cognia.first_run.set_config_value (que ademas la refleja en os.environ, asi
toma efecto en esta sesion). node/llama_backend.py lee estas variables al
construir el backend, por lo que un llama-server YA corriendo no se entera:
restart_backend_hint() avisa de eso y kill_llama_server() lo termina.

Sin dependencias nuevas: psutil es opcional (para nucleos fisicos y para
matar el server); sin psutil se degrada a os.cpu_count()//2 y taskkill/pkill.
"""

from __future__ import annotations

import logging
import os
import subprocess

from . import first_run

logger = logging.getLogger(__name__)

DEFAULT_PROFILE = "cpu"

# Puerto por defecto del llama-server (mismo default que node/llama_backend.py)
_DEFAULT_PORT = 8088

# Nombres exactos del binario llama-server (no tocar otros procesos)
_SERVER_PROC_NAMES = ("llama-server", "llama-server.exe",
                      "llama_server", "llama_server.exe")


# -- Calculo de threads --------------------------------------------------------

def _physical_cpu_count() -> int:
    """Nucleos fisicos via psutil; sin psutil, os.cpu_count()//2 (minimo 1)."""
    try:
        import psutil
        n = psutil.cpu_count(logical=False)
        if n:
            return n
    except ImportError:
        pass
    return max(1, (os.cpu_count() or 4) // 2)


def _build_profiles() -> dict:
    """Construye PROFILES con los threads calculados para esta maquina."""
    logical = os.cpu_count() or 4
    return {
        # DEFAULT: CPU puro. Threads = nucleos fisicos (hyperthreading no ayuda
        # en el GEMM de llama.cpp; los threads logicos extra solo pisan cache).
        "cpu": {
            "LLAMA_N_GPU_LAYERS":  "0",
            "LLAMA_CTX_SIZE":      "4096",
            "LLAMA_N_THREADS":     str(_physical_cpu_count()),
            "COGNIA_PERF_PROFILE": "cpu",
        },
        # GPU real (CUDA/Metal): offload total, contexto grande, todos los
        # threads logicos (el CPU solo alimenta a la GPU).
        # 32768 = n_ctx_train nativo del Qwen2.5 (sin RoPE OOD, sin perdida de
        # calidad). En el 7B Q4_K_M la KV cache pasa de ~1.8GB (16k) a ~3.7GB
        # (32k); con pesos ~4.7GB + buffers cabe holgado en una GPU de 16GB.
        # Env-overridable: bajar a 16384 en GPUs de <=12GB.
        "gpu": {
            "LLAMA_N_GPU_LAYERS":  "99",
            "LLAMA_CTX_SIZE":      "32768",
            "LLAMA_N_THREADS":     str(logical),
            "COGNIA_PERF_PROFILE": "gpu",
        },
    }


PROFILES = _build_profiles()


# -- API -----------------------------------------------------------------------

def current_profile() -> str:
    """
    Perfil activo segun COGNIA_PERF_PROFILE (config.env ya cargada en
    os.environ por first_run.apply_config al arranque). Default 'cpu'.
    """
    name = os.environ.get("COGNIA_PERF_PROFILE", "").strip().lower()
    return name if name in PROFILES else DEFAULT_PROFILE


def apply_profile(name: str) -> dict:
    """
    Aplica un perfil: persiste CADA perilla en ~/.cognia/config.env y en
    os.environ (via first_run.set_config_value). Devuelve el dict aplicado.
    Lanza ValueError si el perfil no existe.
    """
    if name not in PROFILES:
        raise ValueError(
            f"Perfil desconocido: {name!r}. Validos: {', '.join(sorted(PROFILES))}"
        )
    applied = dict(PROFILES[name])
    for env, value in applied.items():
        first_run.set_config_value(env, value)
    logger.info("[perf_profiles] perfil '%s' aplicado: %s", name, applied)
    return applied


def profile_summary(name: str) -> str:
    """
    Texto imprimible con cada perilla del perfil: valor actual -> valor del
    perfil ('=' si ya coinciden). Lanza ValueError si el perfil no existe.
    """
    if name not in PROFILES:
        raise ValueError(
            f"Perfil desconocido: {name!r}. Validos: {', '.join(sorted(PROFILES))}"
        )
    activo = " (activo)" if current_profile() == name else ""
    lines = [f"Perfil '{name}'{activo}:"]
    for env, value in PROFILES[name].items():
        actual = os.environ.get(env, "(sin definir)")
        marker = "=" if actual == value else "->"
        lines.append(f"  {env}: {actual} {marker} {value}")
    return "\n".join(lines)


# -- llama-server corriendo ----------------------------------------------------

def _server_port() -> int:
    """Puerto del llama-server (LLAMA_SERVER_PORT o 8088, como llama_backend)."""
    try:
        return int(os.environ.get("LLAMA_SERVER_PORT", "").strip() or _DEFAULT_PORT)
    except ValueError:
        return _DEFAULT_PORT


def _server_running(port: int) -> bool:
    """True si un llama-server responde /health (patron _LlamaServerBackend._ping)."""
    import urllib.request
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1)
        return True
    except Exception:
        return False


def restart_backend_hint() -> str:
    """
    Si hay un llama-server vivo, devuelve el aviso de que el perfil recien
    aplicado toma efecto en el PROXIMO arranque del backend. Si no hay server
    corriendo devuelve cadena vacia (nada que avisar: el proximo arranque ya
    lee los valores nuevos).
    """
    port = _server_port()
    if _server_running(port):
        return (
            f"Hay un llama-server corriendo en :{port}. El perfil aplica al "
            "proximo arranque del backend: cerralo (kill_llama_server) o "
            "reinicia Cognia para que tome efecto."
        )
    return ""


def kill_llama_server() -> bool:
    """
    Termina el llama-server local buscando SOLO por nombre exacto de binario.
    Con psutil: terminate() con espera y kill() de respaldo. Sin psutil:
    taskkill (Windows) o pkill -x (POSIX). Devuelve True si mato algo.
    Nunca lanza: cualquier fallo se loguea y devuelve False.
    """
    try:
        import psutil
    except ImportError:
        psutil = None

    if psutil is not None:
        killed = False
        for proc in psutil.process_iter(["name"]):
            name = (proc.info.get("name") or "").lower()
            if name not in _SERVER_PROC_NAMES:
                continue
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except psutil.TimeoutExpired:
                    proc.kill()
                killed = True
            except psutil.Error as exc:
                logger.warning("[perf_profiles] no pude terminar pid=%s: %s",
                               proc.pid, exc)
        return killed

    # Fallback sin psutil: por nombre exacto, nada de patrones amplios
    if os.name == "nt":
        cmd = ["taskkill", "/IM", "llama-server.exe", "/F"]
    else:
        cmd = ["pkill", "-x", "llama-server"]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=10)
        return result.returncode == 0
    except Exception as exc:
        logger.warning("[perf_profiles] kill_llama_server fallo: %s", exc)
        return False
