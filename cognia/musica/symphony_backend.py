# -*- coding: utf-8 -*-
"""Backend SymphonyGen: orquestacion sinfonica por subprocess (venv312gpu).

POR QUE subprocess y no import: la regla dura del repo es que cognia/ no
importa torch. El vendor (dos etapas: arch/harmo = esqueleto armonico,
arch/symph = orquestacion condicionada) corre ENTERO en el python de GPU via
scripts/musica_orquestar_cli.py, que devuelve UNA linea JSON por stdout y
manda todo el progreso (incluidos los print del vendor) a stderr.

POR QUE las rutas se leen del env en CALL-time y no en import-time: leccion
de _root_actual (dev_tools.py, campana 2026-07-21) -- una constante fijada al
importar ancla el proceso largo al PRIMER valor y los tests no pueden
redirigirla con monkeypatch.setenv.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional


def _dir_vendor() -> Path:
    """Fuente del vendor SymphonyGen (COGNIA_SYMPHONYGEN_SRC)."""
    return Path(os.environ.get(
        "COGNIA_SYMPHONYGEN_SRC",
        str(Path.home() / ".cognia" / "vendors" / "symphonygen")))


def _dir_pesos():
    """Checkpoints .pt empaquetados (COGNIA_SYMPHONYGEN_PESOS)."""
    return Path(os.environ.get(
        "COGNIA_SYMPHONYGEN_PESOS",
        str(Path.home() / ".cognia" / "models" / "symphonygen")))


def _dir_trabajo() -> Path:
    """WORK_DIR que arch/config.py del vendor consume (crea tmp/ al importar)."""
    return Path.home() / ".cognia" / "data" / "symphonygen_work"


def _gpu_python() -> str:
    """Python que corre el CLI pesado.

    POR QUE esta cadena: COGNIA_SYMPHONYGEN_PY es la contingencia documentada
    (venv dedicado torch 2.8 si torch 2.11 revienta en el smoke); despues el
    helper canonico gpu_env.gpu_python() (agente A3 de la ola 1 -- import
    perezoso tolerante porque en paralelo puede no existir aun); el fallback
    replica su contrato: COGNIA_GPU_PYTHON (flag EXISTENTE, pulidor.py) o
    venv312gpu del repo.
    """
    dedicado = os.environ.get("COGNIA_SYMPHONYGEN_PY", "").strip()
    if dedicado:
        return dedicado
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


def musica_disponible() -> tuple[bool, str]:
    """(ok, motivo). Chequeo BARATO: presencia de vendor+pesos+python+torch.

    POR QUE sin imports pesados: esto se llama desde la tool en el proceso
    principal para degradar con un motivo legible ANTES de reservar VRAM o
    lanzar el subprocess; torch se verifica por presencia en site-packages
    del venv GPU, jamas importandolo aqui.
    """
    vendor = _dir_vendor()
    if not (vendor / "arch" / "symph" / "generator.py").is_file():
        return False, (f"vendor SymphonyGen no esta en {vendor} "
                       "(clonalo o fija COGNIA_SYMPHONYGEN_SRC)")
    pesos = _dir_pesos()
    for pt in ("stage_one_pretrained.pt", "grpo_clamp+track_epoch_6.pt"):
        if not (pesos / pt).is_file():
            return False, (f"falta el checkpoint {pt} en {pesos} "
                           "(fija COGNIA_SYMPHONYGEN_PESOS)")
    py = Path(_gpu_python())
    if not py.is_file():
        return False, (f"no existe el python GPU {py} "
                       "(fija COGNIA_GPU_PYTHON o COGNIA_SYMPHONYGEN_PY)")
    # torch sin cargarlo: layout estandar de venv Windows. Si el layout no es
    # el esperado no podemos verificar barato -- no bloqueamos por eso.
    site = py.parent.parent / "Lib" / "site-packages"
    if site.is_dir() and not (site / "torch" / "__init__.py").is_file():
        return False, (f"el venv GPU {py.parent.parent.name} no tiene torch "
                       "(pip install torch --index-url "
                       "https://download.pytorch.org/whl/cu128)")
    return True, ""


def _post_expresividad(midis: list[str]) -> list[str]:
    """Capa de expresividad (velocity/CC/tempo) sobre los MIDIs recien generados.

    POR QUE aqui y no en el CLI GPU: expresividad.py solo necesita miditoolkit
    (instalado en venv312), asi corre en el proceso principal sin reservar la
    GPU un segundo mas. Guarda el original como <nombre>.crudo.mid al lado.
    POR QUE jamas levanta: el post-proceso es cosmetico frente a la
    generacion -- si algo falla (miditoolkit ausente, gate reprobado) se
    degrada VISIBLEMENTE por stderr y salen los MIDIs planos de siempre.
    Opt-out: COGNIA_MUSICA_EXPRESIVIDAD=0.
    """
    if os.environ.get("COGNIA_MUSICA_EXPRESIVIDAD", "").strip() == "0":
        return midis
    try:
        from cognia.musica.expresividad import aplicar_expresividad
    except ImportError as e:
        print(f"musica: expresividad no disponible ({e}); salen MIDIs crudos",
              file=sys.stderr)
        return midis
    for ruta in midis:
        try:
            aplicar_expresividad(ruta, escribir_crudo=True)
        except Exception as e:
            print(f"musica: expresividad fallo en {ruta}: {e}; queda el crudo",
                  file=sys.stderr)
    return midis


def orquestar(midi_cond: Optional[str], salida_dir: str, *, grupo: int = 2,
              checkpoint: str = "grpo_clamp+track_epoch_6.pt",
              timeout: float = 900) -> list[str]:
    """Genera una sinfonia (>=1 MIDI multi-pista) en salida_dir.

    Sin midi_cond el CLI inventa el esqueleto armonico (etapa 1) y lo
    orquesta (etapa 2); con midi_cond re-orquesta ESA pieza (analyze_harmo).
    Devuelve las rutas .mid generadas o levanta RuntimeError con un motivo
    legible (timeout, exit code, stdout contaminado) -- jamas cuelga: el
    subprocess muere con proc.kill() al vencer el timeout.
    """
    if midi_cond:
        midi_cond = str(Path(midi_cond).resolve())
        if not Path(midi_cond).is_file():
            raise RuntimeError(f"musica: no existe el MIDI de condicion {midi_cond}")
    salida = Path(salida_dir).resolve()
    salida.mkdir(parents=True, exist_ok=True)

    repo = Path(__file__).resolve().parents[2]
    cmd = [
        _gpu_python(),
        str(repo / "scripts" / "musica_orquestar_cli.py"),
        "--salida", str(salida),
        "--grupo", str(int(grupo)),
        "--checkpoint", checkpoint,
    ]
    if midi_cond:
        cmd += ["--midi", midi_cond]

    # arch/config.py del vendor lee ASSET_DIR/WORK_DIR del env; PYTHONPATH
    # hace importable `arch` sin instalar nada.
    env = {
        **os.environ,
        "PYTHONPATH": str(_dir_vendor()),
        "ASSET_DIR": str(_dir_pesos()),
        "WORK_DIR": str(_dir_trabajo()),
    }

    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
        env=env, cwd=str(_dir_vendor()))
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.communicate(timeout=10)
        except Exception:
            pass
        raise RuntimeError(
            f"musica: timeout tras {timeout:.0f}s generando en {salida} "
            "(subproceso matado; sube timeout= o baja grupo=)")

    if proc.returncode != 0:
        cola = (err or "").strip()[-800:]
        raise RuntimeError(
            f"musica: el CLI salio con codigo {proc.returncode}: {cola or '(sin stderr)'}")

    # Contrato: UNA linea JSON en stdout. Tomamos la ULTIMA no vacia por si
    # algo del vendor se escapo antes del redirect -- degradacion visible.
    lineas = [l for l in (out or "").splitlines() if l.strip()]
    if not lineas:
        raise RuntimeError("musica: el CLI no imprimio nada por stdout (contrato JSON roto)")
    try:
        datos = json.loads(lineas[-1])
    except (json.JSONDecodeError, ValueError):
        raise RuntimeError(
            "musica: stdout contaminado, la ultima linea no es JSON: "
            f"{lineas[-1][:200]!r}")
    if not datos.get("ok"):
        raise RuntimeError(f"musica: el CLI reporto fallo: {datos.get('error', '(sin detalle)')}")
    midis = [str(m) for m in datos.get("midis", [])]
    if not midis:
        raise RuntimeError("musica: el CLI dijo ok pero sin MIDIs (contrato roto)")
    return _post_expresividad(midis)
