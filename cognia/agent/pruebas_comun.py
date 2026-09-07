# -*- coding: utf-8 -*-
"""
cognia/agent/pruebas_comun.py
=============================
Piezas compartidas por la FAMILIA DE PRUEBAS del agente (2026-09-07, pedido del
dueno: "mas herramientas para que Cognia pueda testear y probar sus propios
resultados; se queja de que no le dejan probar"). Las familias que la usan:

  pagina_*    inspeccion y prueba de paginas web con sesion persistente
  captura_*   inspeccion, diff, recorte y mosaico de imagenes/capturas
  audio_* / video_*   inspeccion de medios (ffprobe/soundfile)
  formato_* / diff_texto / sql_probar / pdf_* / docx_* / xlsx_* / modelo3d_*
  app_*       aplicaciones GRAFICAS lanzadas en el escritorio propio de Cognia
  probar      la puerta unica que decide que prueba toca por tipo de fichero

Convenciones (las mismas que renderizar / ejecutar_guion):
  - Cada tool devuelve "RESULTADO <tool> ...: ..." o "RESULTADO <tool> ERROR: ...".
  - Los args llegan como texto: '<objetivo> [| clave=valor]...' o con las
    claves separadas por espacio (asi las arma tools.armar_args desde JSON).
  - Las rutas relativas se resuelven contra el workspace del agente y luego
    contra el cwd; las salidas (PNG, mosaicos) van al scratchpad de la tarea
    (ctx['_scratchpad']) o a <workspace>/.cognia_capturas/.
  - Sin dependencia opcional se dice EXACTAMENTE que falta y como instalarlo.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Args
# ---------------------------------------------------------------------------

def partir_args(args: str, claves) -> tuple:
    """(objetivo, opciones) desde 'obj | a=1 | b=x' o 'obj a=1 b=x'.

    Se come el ULTIMO token clave=valor y repite, asi 'a=1 b=2' da dos claves
    y no a='1 b=2' (misma regla que renderizador.partir_args). `claves` es la
    lista de nombres admitidos; lo que no este ahi queda dentro del objetivo."""
    s = (args or "").strip()
    opts: dict = {}
    if not claves:
        return s, opts
    patron = re.compile(r"(?:\|\s*|\s+)(%s)\s*=\s*" % "|".join(re.escape(c) for c in claves), re.I)
    while True:
        ms = list(patron.finditer(s))
        if not ms:
            break
        m = ms[-1]
        val = s[m.end():].strip().strip("|").strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        opts[m.group(1).lower()] = val
        s = s[:m.start()].strip().rstrip("|").strip()
    s = s.strip()
    # Solo se quitan las comillas si ENVUELVEN todo el objetivo: en un comando
    # como `python "C:\ruta con espacios\x.py"` el strip ciego dejaba la
    # primera comilla colgando y shlex partia mal (cazado por formato_tools).
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'" and s.count(s[0]) == 2:
        s = s[1:-1].strip()
    return s, opts


def entero(valor, defecto: int, minimo: int = None, maximo: int = None) -> int:
    try:
        v = int(str(valor).strip())
    except Exception:
        v = defecto
    if minimo is not None:
        v = max(minimo, v)
    if maximo is not None:
        v = min(maximo, v)
    return v


# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------

def bases_relativas() -> list:
    """Workspace del agente y cwd, sin duplicados (como renderizador)."""
    bases = []
    try:
        from cognia.agents.workers.dev_tools import _workspace
        bases.append(Path(_workspace()))
    except Exception:
        pass
    cwd = Path(os.getcwd())
    if not any(os.path.normcase(str(b)) == os.path.normcase(str(cwd)) for b in bases):
        bases.append(cwd)
    return bases


def resolver_ruta(ruta: str, debe_existir: bool = True, ctx=None) -> Path:
    """Ruta absoluta resuelta contra el scratchpad de la tarea (si `ctx` lo
    trae), el workspace y el cwd, en ese orden. ValueError si no existe.

    El scratchpad va PRIMERO (cazado en el humo de medios_tools): el modelo
    escribe `prueba.wav` con una tool que guarda en el scratchpad y al leerla
    en relativo recibia "no existe" porque solo se miraba workspace y cwd."""
    f = (ruta or "").strip().strip("\"'")
    if not f:
        raise ValueError("falta la ruta")
    if re.match(r"^file:", f, re.I):
        from urllib.parse import unquote, urlparse
        u = urlparse(f)
        f = unquote(u.path)
        if re.match(r"^/[A-Za-z]:", f):
            f = f[1:]
    p = Path(f)
    if p.is_absolute():
        if debe_existir and not p.exists():
            raise ValueError("no existe: %s" % f)
        return p.resolve() if p.exists() else p
    bases = bases_relativas()
    scratch = (ctx or {}).get("_scratchpad") if isinstance(ctx, dict) else None
    if scratch:
        bases = [Path(str(scratch))] + bases
    for base in bases:
        cand = base / p
        if cand.exists():
            return cand.resolve()
    if debe_existir:
        raise ValueError("no existe: %s (buscado en %s)" % (f, " y ".join(str(b) for b in bases)))
    return (bases[0] / p)


def carpeta_salida(ctx) -> Path:
    """Donde dejar PNG/mosaicos: scratchpad de la tarea o .cognia_capturas."""
    scratch = (ctx or {}).get("_scratchpad") if isinstance(ctx, dict) else None
    base = Path(str(scratch)) if scratch else (bases_relativas()[0] / ".cognia_capturas")
    base.mkdir(parents=True, exist_ok=True)
    return base


def ruta_salida(ctx, nombre: str, ext: str = ".png", salida: str = "") -> Path:
    """Ruta de salida: la pedida (relativa al scratchpad/workspace) o una con
    marca de hora en la carpeta de salida."""
    if salida:
        p = Path(str(salida).strip().strip("\"'"))
        if not p.is_absolute():
            # El modelo suele pedir `salida=.cognia_scratch/<id>/x.png` (la
            # ruta del scratchpad RELATIVA al workspace, tal como la vio en
            # otro resultado): pegarla al scratchpad otra vez anidaba
            # .cognia_scratch/<id>/.cognia_scratch/<id>/x.png (visto en la
            # tarea del contador, 2026-09-07). Esa forma va contra el workspace.
            base = carpeta_salida(ctx)
            if p.parts and p.parts[0] == ".cognia_scratch":
                base = bases_relativas()[0]
            p = base / p
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
    limpio = re.sub(r"[^A-Za-z0-9_.-]", "_", nombre)[:40]
    return carpeta_salida(ctx) / ("%s_%s%s" % (limpio, time.strftime("%H%M%S"), ext))


# ---------------------------------------------------------------------------
# Dependencias opcionales
# ---------------------------------------------------------------------------

_PIP = {
    "PIL": "pillow", "numpy": "numpy", "fitz": "pymupdf", "pymupdf": "pymupdf",
    "trimesh": "trimesh", "docx": "python-docx", "openpyxl": "openpyxl",
    "markdown": "markdown", "soundfile": "soundfile", "playwright": "playwright",
    "pyvda": "pyvda", "uiautomation": "uiautomation", "pyte": "pyte",
    "matplotlib": "matplotlib", "yaml": "pyyaml", "lxml": "lxml", "pyflakes": "pyflakes",
    "coverage": "coverage", "win32gui": "pywin32", "psutil": "psutil",
}


def importar(modulo: str):
    """Importa o lanza ValueError con el `pip install` exacto."""
    import importlib
    try:
        return importlib.import_module(modulo)
    except Exception as exc:
        pip = _PIP.get(modulo, modulo)
        raise ValueError("falta el paquete '%s' (%s: %s). Instalalo con: pip install %s"
                         % (modulo, type(exc).__name__, str(exc)[:80], pip))


def binario(nombre: str, pista: str = "") -> str:
    """Ruta de un ejecutable externo (ffmpeg, ffprobe, node) o ValueError."""
    exe = shutil.which(nombre)
    if not exe and os.name == "nt":
        # winget deja ffmpeg fuera del PATH de algunos shells
        for base in (os.environ.get("LOCALAPPDATA", ""),):
            if not base:
                continue
            for cand in Path(base).glob("Microsoft/WinGet/Packages/*/*/bin/%s.exe" % nombre):
                exe = str(cand)
                break
            if exe:
                break
    if not exe:
        raise ValueError("no se encontro '%s' en el PATH%s" % (nombre, (". " + pista) if pista else ""))
    return exe


def correr(cmd: list, timeout: int = 60, cwd: str = None, entrada: str = None) -> tuple:
    """(exit, stdout, stderr) con timeout y texto UTF-8 tolerante."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd,
                           input=entrada, encoding="utf-8", errors="replace")
        return r.returncode, r.stdout or "", r.stderr or ""
    except subprocess.TimeoutExpired:
        return -1, "", "timeout de %ds" % timeout
    except FileNotFoundError as exc:
        return -2, "", str(exc)


# ---------------------------------------------------------------------------
# Imagenes: resumen, diff, mosaico
# ---------------------------------------------------------------------------

def resumen_imagen(ruta) -> dict:
    """Metadatos + firma visual de una imagen: tamano, modo, colores en
    miniatura, fraccion del color dominante, brillo medio, transparencia."""
    Image = importar("PIL.Image")
    im = Image.open(str(ruta))
    info = {"ancho": im.width, "alto": im.height, "modo": im.mode, "formato": im.format or "",
            "fotogramas": getattr(im, "n_frames", 1)}
    rgba = im.convert("RGBA")
    mini = rgba.copy()
    mini.thumbnail((96, 96))
    rgb = mini.convert("RGB")
    colores = rgb.getcolors(96 * 96) or []
    total = sum(c for c, _ in colores) or 1
    colores.sort(reverse=True)
    info["colores_miniatura"] = len(colores)
    info["dominante"] = colores[0][1] if colores else None
    info["fraccion_dominante"] = round(colores[0][0] / total, 3) if colores else 1.0
    gris = rgb.convert("L")
    hist = gris.histogram()
    n = sum(hist) or 1
    info["brillo_medio"] = round(sum(i * h for i, h in enumerate(hist)) / n, 1)
    if rgba.mode == "RGBA":
        alfa = mini.getchannel("A").histogram()
        info["fraccion_transparente"] = round(alfa[0] / (sum(alfa) or 1), 3)
    else:
        info["fraccion_transparente"] = 0.0
    if info["colores_miniatura"] <= 1:
        info["veredicto"] = "UN solo color: imagen vacia o sin pintar"
    elif info["fraccion_dominante"] > 0.97:
        info["veredicto"] = "casi uniforme (%d%% de un color): probablemente vacia" % int(info["fraccion_dominante"] * 100)
    elif info["colores_miniatura"] >= 24:
        # una pagina blanca con texto tiene brillo alto pero MUCHOS colores:
        # eso es contenido, no una pagina vacia (aviso del fork de pagina_tools)
        info["veredicto"] = "tiene contenido (%d colores en miniatura, fondo %s)" % (
            info["colores_miniatura"], "claro" if info["brillo_medio"] > 200 else ("oscuro" if info["brillo_medio"] < 55 else "medio"))
    elif info["brillo_medio"] < 8:
        info["veredicto"] = "casi negra"
    elif info["brillo_medio"] > 247:
        info["veredicto"] = "casi blanca"
    else:
        info["veredicto"] = "tiene contenido (%d colores en miniatura)" % info["colores_miniatura"]
    return info


def texto_resumen_imagen(info: dict) -> str:
    dom = info.get("dominante")
    dom_txt = "#%02x%02x%02x" % tuple(dom[:3]) if dom else "?"
    partes = ["%dx%d %s%s" % (info["ancho"], info["alto"], info["modo"],
                              (" " + info["formato"]) if info.get("formato") else ""),
              "dominante %s (%d%%)" % (dom_txt, int(info.get("fraccion_dominante", 0) * 100)),
              "brillo medio %s/255" % info.get("brillo_medio")]
    if info.get("fotogramas", 1) > 1:
        partes.append("%d fotogramas" % info["fotogramas"])
    if info.get("fraccion_transparente"):
        partes.append("%d%% transparente" % int(info["fraccion_transparente"] * 100))
    partes.append(info.get("veredicto", ""))
    return " · ".join(p for p in partes if p)


def diff_imagenes(a, b, salida=None, umbral: int = 24) -> dict:
    """Fraccion de pixeles distintos, caja del cambio y (opcional) PNG del diff."""
    Image = importar("PIL.Image")
    ImageChops = importar("PIL.ImageChops")
    ia = Image.open(str(a)).convert("RGB")
    ib = Image.open(str(b)).convert("RGB")
    mismo_tamano = ia.size == ib.size
    if not mismo_tamano:
        ib = ib.resize(ia.size)
    d = ImageChops.difference(ia, ib).convert("L")
    mascara = d.point(lambda v: 255 if v > umbral else 0)
    hist = mascara.histogram()
    cambiados = hist[255] if len(hist) > 255 else 0
    total = ia.width * ia.height or 1
    caja = mascara.getbbox()
    out = {"fraccion": round(cambiados / total, 4), "caja": caja, "mismo_tamano": mismo_tamano,
           "tamano_a": ia.size, "tamano_b": ib.size, "png": ""}
    if salida:
        vis = Image.merge("RGB", (mascara, d, d))
        vis.save(str(salida))
        out["png"] = str(salida)
    return out


def mosaico(rutas: list, salida, etiquetas: list = None, columnas: int = 0, celda: int = 420) -> str:
    """Hoja de contactos: N imagenes escaladas a `celda` px de ancho, con su
    etiqueta encima. Devuelve la ruta del PNG."""
    Image = importar("PIL.Image")
    ImageDraw = importar("PIL.ImageDraw")
    ims = []
    for r in rutas:
        try:
            im = Image.open(str(r)).convert("RGB")
        except Exception:
            im = Image.new("RGB", (celda, celda // 2), (80, 0, 0))
        esc = celda / float(im.width)
        im = im.resize((celda, max(1, int(im.height * esc))))
        ims.append(im)
    if not ims:
        raise ValueError("mosaico sin imagenes")
    etiquetas = list(etiquetas or [Path(str(r)).name for r in rutas])
    cols = columnas or (1 if len(ims) == 1 else (2 if len(ims) <= 4 else 3))
    filas = (len(ims) + cols - 1) // cols
    alto_fila = max(im.height for im in ims) + 22
    lienzo = Image.new("RGB", (cols * (celda + 8) + 8, filas * (alto_fila + 8) + 8), (34, 34, 40))
    dib = ImageDraw.Draw(lienzo)
    for i, im in enumerate(ims):
        x = 8 + (i % cols) * (celda + 8)
        y = 8 + (i // cols) * (alto_fila + 8)
        dib.text((x + 2, y + 2), str(etiquetas[i] if i < len(etiquetas) else i)[:60], fill=(230, 230, 230))
        lienzo.paste(im, (x, y + 20))
    lienzo.save(str(salida))
    return str(salida)


def fraccion_cambio(a, b) -> float:
    try:
        return diff_imagenes(a, b)["fraccion"]
    except Exception:
        return -1.0
