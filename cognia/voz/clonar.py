# -*- coding: utf-8 -*-
"""Backend de clonacion de voz: OpenVoice v2 por subprocess (venv312gpu).

POR QUE OpenVoice v2 y no XTTS ni F5-TTS (decision congelada en el plan):
MIT en codigo Y pesos, espanol nativo via MeloTTS-Spanish, y corre en CPU
sin pelear la VRAM con el cerebro. XTTS es CPML no comercial; F5-TTS tiene
checkpoint CC-BY-NC y sin espanol nativo.

POR QUE subprocess y no import: la regla dura del repo es que cognia/ no
importa torch. Todo lo pesado corre en scripts/voz_clonar_cli.py con el
python de gpu_env.gpu_python(), contrato stdout = UNA linea JSON
{"ok","wav","seg"} y progreso a stderr (patron expert_forge/cli_train.py).

POR QUE las rutas se leen del env en CALL-time y no en import-time: leccion
de _root_actual (dev_tools.py, campana 2026-07-21) — una constante fijada
al importar ancla el proceso largo al PRIMER valor y los tests no pueden
redirigirla con monkeypatch.setenv.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def _dir_openvoice() -> Path:
    """Directorio de pesos OpenVoice v2 (COGNIA_OPENVOICE_DIR).

    POR QUE el doble default: el plan integrado fija ~/.cognia/models/
    openvoice_v2, pero la guia de instalacion del diseno original decia
    ~/.cognia/voces/openvoice_v2. Si el primario no tiene el checkpoint y
    el alterno si, se usa el alterno — un mismatch de instalacion no puede
    convertirse en un 'faltan pesos' falso. Con COGNIA_OPENVOICE_DIR
    fijado no se adivina nada.
    """
    env = os.environ.get("COGNIA_OPENVOICE_DIR", "").strip()
    if env:
        return Path(env)
    primario = Path.home() / ".cognia" / "models" / "openvoice_v2"
    if (primario / "converter" / "checkpoint.pth").is_file():
        return primario
    alterno = Path.home() / ".cognia" / "voces" / "openvoice_v2"
    if (alterno / "converter" / "checkpoint.pth").is_file():
        return alterno
    return primario


def _gpu_python() -> str:
    """Python que corre el CLI pesado.

    POR QUE la cadena: el helper canonico es gpu_env.gpu_python() (agente
    A3 de la ola 1 — import perezoso tolerante porque en paralelo puede no
    existir aun); el fallback replica su contrato exacto: COGNIA_GPU_PYTHON
    (flag EXISTENTE, pulidor.py) o venv312gpu del repo.
    """
    try:
        from cognia.gpu_env import gpu_python
        return gpu_python()
    except ImportError:
        pass
    propio = os.environ.get("COGNIA_GPU_PYTHON", "").strip()
    if propio:
        return propio
    repo = Path(__file__).resolve().parents[2]
    return str(repo / "venv312gpu" / "Scripts" / "python.exe")


def clonar_disponible() -> tuple[bool, str]:
    """(ok, motivo). Chequeo BARATO: pesos + python GPU, sin cargar nada.

    POR QUE sin imports pesados: esto se llama desde la tool en el proceso
    principal para degradar con un motivo legible ANTES de reservar VRAM o
    lanzar el subprocess. torch/openvoice/melo se cargan SOLO en el CLI.
    """
    d = _dir_openvoice()
    if not (d / "converter" / "checkpoint.pth").is_file():
        return False, (
            f"faltan los pesos OpenVoice v2 en {d} (converter/checkpoint.pth; "
            "descargalos de HF myshell-ai/OpenVoiceV2 o fija COGNIA_OPENVOICE_DIR)")
    if not (d / "converter" / "config.json").is_file():
        return False, (f"falta converter/config.json en {d} "
                       "(los pesos estan incompletos)")
    py = Path(_gpu_python())
    if not py.is_file():
        return False, (f"no existe el python GPU {py} "
                       "(crea venv312gpu con torch/CUDA o fija COGNIA_GPU_PYTHON)")
    return True, ""


def clonar_voz(referencia: str, texto: str, salida: str, *, idioma: str = "es",
               device: str = "cpu", timeout: float = 600) -> str:
    """Sintetiza `texto` con el timbre del WAV `referencia`. Devuelve la ruta WAV.

    Delega en scripts/voz_clonar_cli.py (venv312gpu). Levanta RuntimeError
    con un motivo legible (timeout, exit code, stdout contaminado) — jamas
    cuelga: el subprocess muere con proc.kill() al vencer el timeout, y
    jamas devuelve una ruta que no existe (contrato verificado, no creido).
    """
    referencia = str(Path(referencia).resolve())
    if not Path(referencia).is_file():
        raise RuntimeError(f"voz: no existe el WAV de referencia {referencia}")
    if not (texto or "").strip():
        raise RuntimeError("voz: texto vacio, nada que sintetizar")
    destino = Path(salida).resolve()
    destino.parent.mkdir(parents=True, exist_ok=True)

    repo = Path(__file__).resolve().parents[2]
    cmd = [
        _gpu_python(),
        str(repo / "scripts" / "voz_clonar_cli.py"),
        "--referencia", referencia,
        "--texto", texto,
        "--salida", str(destino),
        "--idioma", idioma,
        "--device", device,
    ]
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace")
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.communicate(timeout=10)
        except Exception:
            pass
        raise RuntimeError(
            f"voz: timeout tras {timeout:.0f}s clonando hacia {destino} "
            "(subproceso matado; en CPU una frase larga puede tardar - sube timeout=)")

    # Contrato: UNA linea JSON en stdout. Tomamos la ULTIMA no vacia por si
    # algo del vendor se escapo antes del redirect — degradacion visible.
    lineas = [l for l in (out or "").splitlines() if l.strip()]
    datos = None
    if lineas:
        try:
            datos = json.loads(lineas[-1])
        except (json.JSONDecodeError, ValueError):
            datos = None

    if proc.returncode != 0:
        detalle = ""
        if isinstance(datos, dict) and datos.get("error"):
            detalle = str(datos["error"])
        else:
            detalle = (err or "").strip()[-800:]
        raise RuntimeError(
            f"voz: el CLI salio con codigo {proc.returncode}: "
            f"{detalle or '(sin detalle)'}")
    if not lineas:
        raise RuntimeError(
            "voz: el CLI no imprimio nada por stdout (contrato JSON roto)")
    if datos is None:
        raise RuntimeError(
            "voz: stdout contaminado, la ultima linea no es JSON: "
            f"{lineas[-1][:200]!r}")
    if not datos.get("ok"):
        raise RuntimeError(
            f"voz: el CLI reporto fallo: {datos.get('error', '(sin detalle)')}")
    wav = str(datos.get("wav") or destino)
    if not Path(wav).is_file():
        raise RuntimeError(
            f"voz: el CLI dijo ok pero el WAV no existe: {wav} (contrato roto)")
    return wav
