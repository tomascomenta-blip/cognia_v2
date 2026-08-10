# -*- coding: utf-8 -*-
"""Backend TripoSR: imagen -> malla 3D por subprocess (venv312gpu).

POR QUE subprocess y no import: la regla dura del repo es que cognia/ no
importa torch. TripoSR (vendor en ~/.cognia/vendors/TripoSR) corre ENTERO en
el python de GPU via scripts/tresd_generar_cli.py, que devuelve UNA linea
JSON por stdout y manda todo el progreso (barras de HF incluidas) a stderr.

POR QUE las rutas se leen del env en CALL-time y no en import-time: leccion
de _root_actual (dev_tools.py, campana 2026-07-21) — una constante fijada al
importar ancla el proceso largo al PRIMER valor y los tests no pueden
redirigirla con monkeypatch.setenv.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

# Formatos que trimesh exporta sin sorpresas y que el server de la oficina ya
# sirve (model/gltf-binary para .glb).
_FORMATOS = ("glb", "obj")


def _dir_vendor() -> Path:
    """Fuente del vendor TripoSR (COGNIA_TRIPOSR_SRC)."""
    return Path(os.environ.get(
        "COGNIA_TRIPOSR_SRC",
        str(Path.home() / ".cognia" / "vendors" / "TripoSR")))


def _gpu_python() -> str:
    """Python que corre el CLI pesado.

    POR QUE la cadena de fallbacks: gpu_env es el helper canonico (agente A3
    de la ola 1 — import perezoso tolerante porque en paralelo puede no
    existir aun); el fallback replica su contrato exacto: COGNIA_GPU_PYTHON
    (flag EXISTENTE, pulidor.py:211) o venv312gpu del repo.
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


def tresd_disponible() -> tuple[bool, str]:
    """(ok, motivo). Chequeo BARATO: vendor + python GPU + deps criticas.

    POR QUE sin imports pesados: esto se llama desde la tool en el proceso
    principal para degradar con un motivo legible ANTES de reservar VRAM o
    lanzar el subprocess. torch/skimage/trimesh se verifican por PRESENCIA en
    site-packages del venv GPU, jamas importandolos aqui. Los pesos NO se
    chequean: se auto-descargan de HF (stabilityai/TripoSR) al primer uso.
    """
    vendor = _dir_vendor()
    if not (vendor / "tsr" / "system.py").is_file():
        return False, (
            f"vendor TripoSR no esta en {vendor} (git clone "
            "https://github.com/VAST-AI-Research/TripoSR o fija "
            "COGNIA_TRIPOSR_SRC)")
    py = Path(_gpu_python())
    if not py.is_file():
        return False, (f"no existe el python GPU {py} "
                       "(crea venv312gpu o fija COGNIA_GPU_PYTHON)")
    # Deps sin cargarlas: layout estandar de venv Windows. Si el layout no es
    # el esperado no podemos verificar barato — no bloqueamos por eso.
    site = py.parent.parent / "Lib" / "site-packages"
    if site.is_dir():
        for paquete, pista in (
                ("torch", "pip install torch --index-url "
                          "https://download.pytorch.org/whl/cu128"),
                ("skimage", "pip install scikit-image (shim torchmcubes)"),
                ("trimesh", "pip install trimesh (exporta glb/obj)")):
            if not (site / paquete / "__init__.py").is_file():
                return False, (f"el venv GPU {py.parent.parent.name} no "
                               f"tiene {paquete} ({pista})")
    return True, ""


def generar_malla(imagen: str, salida: str, *, formato: str = "glb",
                  resolucion: int = 256, timeout: float = 600) -> dict:
    """Convierte una imagen de objeto en una malla 3D con TripoSR.

    Devuelve {'ruta', 'verts', 'caras', 'seg'} o levanta RuntimeError con un
    motivo legible (timeout, exit code, stdout contaminado) — jamas cuelga:
    el subprocess muere con proc.kill() al vencer el timeout. El input ideal
    es un PNG RGBA de imagen_quitar_fondo (BiRefNet); sin canal alfa el CLI
    usa la imagen tal cual y lo AVISA por stderr (no hay rembg en la casa).
    """
    formato = str(formato).strip().lower()
    if formato not in _FORMATOS:
        raise RuntimeError(
            f"tresd: formato '{formato}' no soportado (usa {'/'.join(_FORMATOS)})")
    imagen = str(Path(imagen).resolve())
    if not Path(imagen).is_file():
        raise RuntimeError(f"tresd: no existe la imagen {imagen}")
    destino = Path(salida).resolve()
    if destino.suffix.lower() != f".{formato}":
        # Coherencia visible: un .glb con bytes OBJ dentro es una trampa
        # silenciosa para el visor; mejor abortar con el motivo.
        raise RuntimeError(
            f"tresd: la salida {destino.name} no termina en .{formato}")
    destino.parent.mkdir(parents=True, exist_ok=True)

    repo = Path(__file__).resolve().parents[2]
    cmd = [
        _gpu_python(),
        str(repo / "scripts" / "tresd_generar_cli.py"),
        "--imagen", imagen,
        "--salida", str(destino),
        "--formato", formato,
        "--resolucion", str(int(resolucion)),
    ]

    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", env={**os.environ})
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.communicate(timeout=10)
        except Exception:
            pass
        raise RuntimeError(
            f"tresd: timeout tras {timeout:.0f}s generando la malla "
            "(subproceso matado; sube timeout= o baja resolucion=)")

    if proc.returncode != 0:
        cola = (err or "").strip()[-800:]
        # El CLI reporta su error como JSON por stdout incluso al fallar; si
        # esta, es mas util que la cola de stderr.
        detalle = _ultimo_json(out)
        if detalle and detalle.get("error"):
            cola = str(detalle["error"])[-800:]
        raise RuntimeError(
            f"tresd: el CLI salio con codigo {proc.returncode}: "
            f"{cola or '(sin detalle)'}")

    # Contrato: UNA linea JSON en stdout. Tomamos la ULTIMA no vacia por si
    # algo del vendor se escapo antes del redirect — degradacion visible.
    lineas = [l for l in (out or "").splitlines() if l.strip()]
    if not lineas:
        raise RuntimeError(
            "tresd: el CLI no imprimio nada por stdout (contrato JSON roto)")
    try:
        datos = json.loads(lineas[-1])
    except (json.JSONDecodeError, ValueError):
        raise RuntimeError(
            "tresd: stdout contaminado, la ultima linea no es JSON: "
            f"{lineas[-1][:200]!r}")
    if not datos.get("ok"):
        raise RuntimeError(
            f"tresd: el CLI reporto fallo: {datos.get('error', '(sin detalle)')}")
    ruta = str(datos.get("ruta") or "")
    if not ruta:
        raise RuntimeError("tresd: el CLI dijo ok pero sin ruta (contrato roto)")
    return {
        "ruta": ruta,
        "verts": int(datos.get("verts", 0)),
        "caras": int(datos.get("caras", 0)),
        "seg": float(datos.get("seg", 0.0)),
    }


def _ultimo_json(out: str) -> dict:
    """Ultima linea JSON de un stdout, o {} — para rescatar el error del CLI."""
    for linea in reversed((out or "").splitlines()):
        linea = linea.strip()
        if not linea:
            continue
        try:
            datos = json.loads(linea)
        except (json.JSONDecodeError, ValueError):
            return {}
        return datos if isinstance(datos, dict) else {}
    return {}
