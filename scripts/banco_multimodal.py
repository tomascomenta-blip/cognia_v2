# -*- coding: utf-8 -*-
"""
scripts/banco_multimodal.py — bateria de tareas MULTIMODALES para trazas selladas.

POR QUE: banco_trazas.py cubre el filesystem; este banco ejercita las tools
multimodales de la ola 1 (voz_decir, imagen_generar, vlm_mirar) mas web_buscar
y pantalla_captura, con el MISMO patron probado de scripts/e2e_happy_path.py:
tarea en lenguaje natural + verificar(ws) con POSTCONDICION REAL sobre el
filesystem (un WAV con cabecera RIFF, un PNG con magic bytes, un texto no
vacio) — nunca la palabra del modelo sobre si mismo.

CUANDO CORRE: ola 3, con GPU y los backends arriba (cerebro :8080, VLM :8081,
worker de imagen). En ola 2 este script solo debe IMPORTAR limpio y listar sus
tareas con --listar (sin tocar cognia ni la GPU).

FLAGS: las tools opt-in se evaluan a IMPORT-TIME de cognia.agent.tools
(reiniciar proceso para cambiarlas). Por eso correr() aplica la UNION de los
env_extra de las tareas seleccionadas ANTES de importar cognia — encender un
flag entre tarea y tarea no tendria efecto.

SELLO: si COGNIA_TRAZAS=1 dejo trazas, se sellan con
``{"verificar_ws": bool, "banco": "banco_multimodal"}`` via traza_chatml.sellar
(mismo diff-de-directorio que banco_trazas). Sin traza no se degrada en
silencio: se avisa por stdout.

Uso:
  venv312\\Scripts\\python.exe scripts\\banco_multimodal.py --listar
  venv312\\Scripts\\python.exe scripts\\banco_multimodal.py [--solo voz_saludo ...] [--pasos 8]

Exit: 0 corrio (los fallos de verificacion se sellan como false, no abortan);
con --listar siempre 0.
"""
from __future__ import annotations

import argparse
import os
import re
import struct
import sys
import tempfile
import time
import zlib
from pathlib import Path

os.environ.setdefault("PYTHONUTF8", "1")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


# ── Helpers de postcondicion (stdlib puro; sin cognia) ─────────────────

def _lee(ws: Path, nombre: str) -> str:
    hits = list(Path(ws).rglob(nombre))
    return hits[0].read_text(encoding="utf-8", errors="replace") if hits else ""


def _bytes_de(ws: Path, patron: str) -> list:
    """Contenido binario de todos los archivos del ws que casan el patron."""
    out = []
    for p in Path(ws).rglob(patron):
        try:
            out.append(p.read_bytes())
        except OSError:
            pass
    return out


def _hay_wav(ws: Path) -> bool:
    """Algun WAV REAL en el ws: cabecera RIFF y mas que la cabecera (44 B).
    Un archivo vacio o de texto con extension .wav NO cuenta."""
    return any(len(b) > 44 and b[:4] == b"RIFF" for b in _bytes_de(ws, "*.wav"))


def _hay_png(ws: Path, minimo: int = 1) -> bool:
    """`minimo` PNGs reales (magic bytes) en el ws."""
    magia = b"\x89PNG\r\n\x1a\n"
    return sum(1 for b in _bytes_de(ws, "*.png")
               if b[:8] == magia) >= minimo


def _texto_no_trivial(ws: Path, nombre: str, largo: int = 10) -> bool:
    return len(_lee(ws, nombre).strip()) >= largo


def _png_solido(ruta: Path, ancho: int = 64, alto: int = 64,
                rgb: tuple = (200, 40, 40)) -> None:
    """PNG valido de color solido, stdlib puro (zlib+struct): el setup del
    banco no puede depender de Pillow ni de la GPU para fabricar su input."""
    def chunk(tipo: bytes, datos: bytes) -> bytes:
        return (struct.pack(">I", len(datos)) + tipo + datos
                + struct.pack(">I", zlib.crc32(tipo + datos) & 0xFFFFFFFF))
    fila = b"\x00" + bytes(rgb) * ancho
    ihdr = struct.pack(">IIBBBBB", ancho, alto, 8, 2, 0, 0, 0)
    Path(ruta).write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
                           + chunk(b"IDAT", zlib.compress(fila * alto))
                           + chunk(b"IEND", b""))


# ── Bateria ────────────────────────────────────────────────────────────
# Cada tarea: nombre, tarea (lenguaje natural para /hacer), verificar(ws) con
# postcondicion real, setup(ws)|None, env_extra (flags opt-in que la tool
# exige — nombres REALES del repo: voz_decir/COGNIA_VOZ_TOOLS, NO 'hablar').

def tareas() -> list:
    return [
        {"nombre": "voz_saludo",
         "tarea": "usa la tool voz_decir para decir el texto 'banco "
                  "multimodal listo' y guarda el audio en saludo.wav "
                  "(voz_decir guardar=saludo.wav | banco multimodal listo)",
         "verificar": _hay_wav,
         "setup": None,
         "env_extra": {"COGNIA_VOZ_TOOLS": "1"}},
        {"nombre": "imagen_circulo",
         "tarea": "genera con la tool imagen_generar una imagen de un "
                  "circulo rojo sobre fondo blanco y deja el PNG en el "
                  "directorio de trabajo",
         "verificar": _hay_png,
         "setup": None,
         "env_extra": {"COGNIA_IMG_TOOLS": "1"}},
        {"nombre": "vlm_describe",
         "tarea": "mira la imagen muestra.png con la tool vlm_mirar y "
                  "guarda su descripcion en descripcion.txt",
         "verificar": lambda ws: _texto_no_trivial(ws, "descripcion.txt"),
         "setup": lambda ws: _png_solido(Path(ws) / "muestra.png"),
         "env_extra": {"COGNIA_VLM_TOOLS": "1"}},
        {"nombre": "imagen_mas_vlm",
         "tarea": "genera con imagen_generar una imagen de un cuadrado azul, "
                  "despues mirala con vlm_mirar y guarda lo que ves en "
                  "informe.txt",
         "verificar": lambda ws: _hay_png(ws)
         and _texto_no_trivial(ws, "informe.txt"),
         "setup": None,
         "env_extra": {"COGNIA_IMG_TOOLS": "1", "COGNIA_VLM_TOOLS": "1"}},
        {"nombre": "web_autor",
         "tarea": "busca en la web quien escribio Don Quijote de la Mancha "
                  "y guarda el apellido del autor en autor.txt",
         "verificar": lambda ws: "cervantes" in _lee(ws, "autor.txt").lower(),
         "setup": None,
         "env_extra": {"COGNIA_BROWSER": "1"}},
        {"nombre": "pantalla_foto",
         "tarea": "captura la pantalla con la tool pantalla_captura y deja "
                  "la imagen como captura.png en el directorio de trabajo",
         "verificar": _hay_png,
         "setup": None,
         "env_extra": {"COGNIA_SCREEN": "1"}},
    ]


def listar() -> int:
    """--listar: la bateria sin correr nada (ni un import de cognia)."""
    print("Tareas de banco_multimodal (se corren en ola 3, con GPU):")
    for t in tareas():
        flags = ",".join(sorted(t["env_extra"]))
        print(f"  {t['nombre']:16s} [{flags}]")
        print(f"                   {t['tarea'][:76]}")
    return 0


# ── Ejecucion (patron e2e_happy_path/banco_trazas; exige GPU + backends) ─

def _sellar_nuevas(previas: set, ok: bool):
    """Sella los volcados NUEVOS del dir de trazas (mismo diff-de-directorio
    que banco_trazas; no depende del hook del loop). Best-effort: sin
    traza_chatml o sin trazas devuelve ([], set()) y el caller avisa."""
    try:
        from cognia.agent import traza_chatml
    except Exception:
        return [], set()
    nuevos = {p.name for p in traza_chatml.dir_trazas().glob("*.json")} - previas
    ids = set()
    for nombre in nuevos:
        ids.add(re.sub(r"-c\d\d$", "", Path(nombre).stem))
    sellados = []
    for tid in sorted(ids):
        if traza_chatml.sellar(tid, {"verificar_ws": bool(ok),
                                     "banco": "banco_multimodal"}):
            sellados.append(tid)
    return sellados, nuevos


def correr(seleccion: list, pasos: int) -> int:
    # Los flags opt-in se evaluan a IMPORT-TIME de cognia.agent.tools: la
    # UNION de env_extra se aplica ANTES de cualquier import de cognia.
    for t in seleccion:
        os.environ.update(t["env_extra"])

    # Arranque identico a scripts/e2e_happy_path.py (patron probado del gate).
    from cognia.first_run import apply_config
    apply_config()
    import cognia.agents.workers.dev_tools as dev_tools
    from cognia import cli as _cli
    from shattering.orchestrator import ShatteringOrchestrator

    try:
        from cognia.agent import traza_chatml
        dir_trazas = traza_chatml.dir_trazas
    except Exception:
        dir_trazas = None

    orch = ShatteringOrchestrator(mode="local")
    orch._try_load_llama()

    class _AI:
        pass
    ai = _AI()
    ai._orchestrator = orch

    def hacer(tarea, verificar, setup):
        ws = Path(tempfile.mkdtemp(prefix="banco_mm_")).resolve()
        if setup:
            setup(ws)
        prev_cwd, prev_root = os.getcwd(), dev_tools.AGENT_WORKSPACE_ROOT
        dev_tools.AGENT_WORKSPACE_ROOT = str(ws)
        os.chdir(ws)
        try:
            resp = _cli._run_agent_task(ai, tarea, lambda s: None,
                                        max_steps=pasos)
        except Exception as exc:
            resp = f"EXCEPTION: {exc}"
        finally:
            os.chdir(prev_cwd)
            dev_tools.AGENT_WORKSPACE_ROOT = prev_root
        try:
            return verificar(ws), (str(resp) or "")[:120]
        except Exception as exc:
            return False, f"verify exc: {exc}"

    t0 = time.time()
    oks = 0
    for t in seleccion:
        previas = ({p.name for p in dir_trazas().glob("*.json")}
                   if dir_trazas else set())
        t1 = time.time()
        ok, resp = hacer(t["tarea"], t["verificar"], t["setup"])
        sellados, nuevos = _sellar_nuevas(previas, ok)
        oks += 1 if ok else 0
        print(f"  [{'OK ' if ok else 'FAIL'}] {t['nombre']} "
              f"({time.time()-t1:.0f}s) trazas={len(nuevos)} "
              f"sellados={sellados}", flush=True)
        if not nuevos:
            print("       AVISO: la corrida no dejo traza (COGNIA_TRAZAS=1 "
                  "apagado, volcado fallido o hook ausente)", flush=True)

    print(f"\nBANCO MULTIMODAL: {oks}/{len(seleccion)} verificadas OK en "
          f"{(time.time()-t0)/60:.1f} min", flush=True)
    try:
        if getattr(orch, "_llama", None) is not None:
            orch._llama.stop()    # solo el server que arranco ESTE script
    except Exception:
        pass
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="banco de tareas multimodales")
    ap.add_argument("--listar", action="store_true",
                    help="mostrar la bateria sin correr nada")
    ap.add_argument("--solo", nargs="*", default=None,
                    help="correr solo estas tareas (por nombre)")
    ap.add_argument("--pasos", type=int, default=8)
    args = ap.parse_args(argv)

    if args.listar:
        return listar()

    todas = tareas()
    if args.solo:
        desconocidas = set(args.solo) - {t["nombre"] for t in todas}
        if desconocidas:
            print(f"Tareas desconocidas: {sorted(desconocidas)} "
                  f"(validas: {[t['nombre'] for t in todas]})",
                  file=sys.stderr)
            return 2
        seleccion = [t for t in todas if t["nombre"] in set(args.solo)]
    else:
        seleccion = todas
    return correr(seleccion, args.pasos)


if __name__ == "__main__":
    sys.exit(main())
