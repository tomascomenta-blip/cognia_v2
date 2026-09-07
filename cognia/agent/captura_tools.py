# -*- coding: utf-8 -*-
"""
cognia/agent/captura_tools.py
=============================
Familia `captura_*` (2026-09-07): que el agente pueda MIRAR una imagen o una
captura sin un VLM (y con el si esta). Pedido del dueno: "se queja de que no le
dejan probar; darle muchas cosas para ver que renderiza bien". `renderizar`
deja un PNG; sin estas tools el modelo solo sabia la ruta y "N colores en
miniatura". Ahora puede: inspeccionar (vacia o con contenido, colores, brillo),
comparar dos capturas (que cambio y donde), recortar y ampliar una region,
armar un mosaico de varias, ponerle una cuadricula con coordenadas para pedir
clics exactos, comprobar el color de un pixel, y leer texto (OCR) si hay
tesseract.

Todo va por PIL (dependencia base). Las salidas caen en el scratchpad de la
tarea via pruebas_comun.ruta_salida. Sin VLM se dice; sin tesseract se dice
como instalarlo. Nada se inventa.
"""
from __future__ import annotations

import glob as _glob
import os
import re
import time
from pathlib import Path

from cognia.agent import pruebas_comun as _pc

_EXT_IMAGEN = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff")

# Ultima operacion (puerta /probar estado).
_ULTIMO: dict = {"tool": "", "entrada": "", "salida": "", "detalle": "", "ts": 0.0}


def _marcar(tool: str, entrada: str, salida: str = "", detalle: str = "") -> None:
    _ULTIMO.update({"tool": tool, "entrada": str(entrada), "salida": str(salida or ""),
                    "detalle": detalle[:200], "ts": time.time()})


def ultimo() -> dict:
    return dict(_ULTIMO)


def _ruta(ruta, ctx=None):
    """Como pruebas_comun.resolver_ruta, pero mirando PRIMERO en el scratchpad
    de la tarea: las salidas de esta familia caen ahi, y el modelo las vuelve a
    nombrar en relativo ('prueba.wav'); sin esto, escribir y leer el mismo
    nombre daba 'no existe'."""
    f = (ruta or "").strip().strip("\"'")
    scratch = (ctx or {}).get("_scratchpad") if isinstance(ctx, dict) else None
    if f and scratch and not Path(f).is_absolute() and (Path(str(scratch)) / f).exists():
        return (Path(str(scratch)) / f).resolve()
    return _pc.resolver_ruta(f)


def _hex(c) -> str:
    return "#%02x%02x%02x" % tuple(int(v) for v in c[:3])


def _abrir(ruta: str, ctx=None):
    """PIL.Image abierta o ValueError legible (no existe / no es imagen)."""
    Image = _pc.importar("PIL.Image")
    p = _ruta(ruta, ctx)
    try:
        im = Image.open(str(p))
        im.load()
    except Exception as exc:
        raise ValueError("%s no es una imagen legible (%s: %s)" % (p.name, type(exc).__name__, str(exc)[:80]))
    return p, im


def _colores_frecuentes(im, n: int = 5) -> list:
    """[(hex, fraccion)] de los n colores mas frecuentes en miniatura 96x96.
    Se cuantiza a 32 niveles por canal para que 'casi el mismo rojo' cuente
    como uno: sin eso un degradado da 9000 colores al 0,01% cada uno."""
    mini = im.convert("RGB").copy()
    mini.thumbnail((96, 96))
    mini = mini.quantize(colors=32, method=2).convert("RGB")
    colores = mini.getcolors(96 * 96) or []
    total = sum(c for c, _ in colores) or 1
    colores.sort(reverse=True)
    return [(_hex(col), round(cnt / total, 3)) for cnt, col in colores[:n]]


def _animacion(im) -> dict:
    """{fotogramas, duracion_ms} para GIF/APNG/WebP animados; {} si no."""
    n = getattr(im, "n_frames", 1)
    if n <= 1:
        return {}
    dur = 0
    try:
        for i in range(n):
            im.seek(i)
            dur += int(im.info.get("duration", 0) or 0)
        im.seek(0)
    except Exception:
        pass
    return {"fotogramas": n, "duracion_ms": dur}


def _exif_basico(im) -> str:
    try:
        exif = im.getexif()
    except Exception:
        return ""
    if not exif:
        return ""
    partes = []
    for tag, nombre in ((0x010F, "camara"), (0x0110, "modelo"), (0x0132, "fecha"), (0x0112, "orientacion")):
        v = exif.get(tag)
        if v:
            partes.append("%s=%s" % (nombre, str(v)[:30]))
    return ", ".join(partes)


# ---------------------------------------------------------------------------
# Operaciones (API sin el decorador, para tests y para `probar`)
# ---------------------------------------------------------------------------

def inspeccionar(ruta: str, ctx=None) -> str:
    p, im = _abrir(ruta, ctx)
    info = _pc.resumen_imagen(p)
    partes = [_pc.texto_resumen_imagen(info)]
    frec = _colores_frecuentes(im)
    if frec:
        partes.append("colores: " + ", ".join("%s %d%%" % (h, int(f * 100)) for h, f in frec))
    anim = _animacion(im)
    if anim:
        partes.append("animada: %d fotogramas, %d ms en total" % (anim["fotogramas"], anim["duracion_ms"]))
    ex = _exif_basico(im)
    if ex:
        partes.append("exif: " + ex)
    partes.append("%d bytes" % p.stat().st_size)
    _marcar("captura_inspeccionar", p, "", info.get("veredicto", ""))
    return " · ".join(partes)


def diff(a: str, b: str, salida: str = "", umbral: int = 24, ctx=None) -> str:
    pa = _ruta(a, ctx)
    pb = _ruta(b, ctx)
    png = _pc.ruta_salida(ctx, "diff_" + pa.stem, ".png", salida)
    d = _pc.diff_imagenes(pa, pb, salida=png, umbral=umbral)
    pct = d["fraccion"] * 100
    if pct < 0.1:
        veredicto = "IDENTICAS (menos del 0,1% distinto)"
    elif pct < 5:
        veredicto = "cambio leve"
    else:
        veredicto = "cambio GRANDE"
    partes = ["%.2f%% de pixeles distintos" % pct, veredicto]
    if d["caja"]:
        x0, y0, x1, y1 = d["caja"]
        partes.append("caja del cambio x=%d..%d y=%d..%d (%dx%d)" % (x0, x1, y0, y1, x1 - x0, y1 - y0))
    if not d["mismo_tamano"]:
        partes.append("TAMANOS DISTINTOS %dx%d vs %dx%d (b reescalada para comparar)"
                      % (d["tamano_a"][0], d["tamano_a"][1], d["tamano_b"][0], d["tamano_b"][1]))
    partes.append("diff en %s (rojo = cambia)" % d["png"])
    _marcar("captura_diff", "%s vs %s" % (pa.name, pb.name), d["png"], veredicto)
    return " · ".join(partes)


_REGIONES = {"centro": (0.25, 0.25, 0.5, 0.5), "arriba": (0, 0, 1, 0.5), "abajo": (0, 0.5, 1, 0.5),
             "izquierda": (0, 0, 0.5, 1), "derecha": (0.5, 0, 0.5, 1)}


def recortar(ruta: str, caja: str = "", region: str = "", zoom: int = 1, salida: str = "", ctx=None) -> str:
    Image = _pc.importar("PIL.Image")
    p, im = _abrir(ruta, ctx)
    im = im.convert("RGB")
    W, H = im.size
    if region:
        r = _REGIONES.get(region.strip().lower())
        if not r:
            raise ValueError("region: centro | arriba | abajo | izquierda | derecha")
        x, y, w, h = int(r[0] * W), int(r[1] * H), int(r[2] * W), int(r[3] * H)
    else:
        nums = re.findall(r"-?\d+", caja or "")
        if len(nums) != 4:
            raise ValueError("caja: x,y,ancho,alto (o region=centro|arriba|abajo|izquierda|derecha)")
        x, y, w, h = (int(n) for n in nums)
    x, y = max(0, x), max(0, y)
    w, h = max(1, min(w, W - x)), max(1, min(h, H - y))
    if x >= W or y >= H:
        raise ValueError("la caja cae fuera de la imagen (%dx%d)" % (W, H))
    zoom = _pc.entero(zoom, 1, 1, 16)
    rec = im.crop((x, y, x + w, y + h))
    if zoom > 1:
        rec = rec.resize((w * zoom, h * zoom), Image.NEAREST)
    png = _pc.ruta_salida(ctx, "recorte_" + p.stem, ".png", salida)
    rec.save(str(png))
    info = _pc.resumen_imagen(png)
    _marcar("captura_recortar", p, png, "%dx%d zoom %d" % (w, h, zoom))
    return ("recorte x=%d y=%d %dx%d zoom x%d -> %s · %s"
            % (x, y, w, h, zoom, png, _pc.texto_resumen_imagen(info)))


def _expandir_rutas(spec: str, maximo: int = 24, ctx=None) -> list:
    """Rutas de imagen desde 'a.png,b.png', globs y directorios; ValueError si
    ninguna existe. Se ordena por nombre para que un mosaico de fotogramas
    salga en orden."""
    out = []
    for trozo in [t.strip().strip("\"'") for t in spec.split(",") if t.strip()]:
        try:
            p = _ruta(trozo, ctx)
        except ValueError:
            # glob relativo al scratchpad, workspace y cwd
            hallado = []
            scratch = (ctx or {}).get("_scratchpad") if isinstance(ctx, dict) else None
            for base in ([Path(str(scratch))] if scratch else []) + _pc.bases_relativas():
                hallado += _glob.glob(str(base / trozo))
            if not hallado:
                raise ValueError("no existe: %s" % trozo)
            out += sorted(Path(h) for h in hallado if Path(h).suffix.lower() in _EXT_IMAGEN)
            continue
        if p.is_dir():
            out += sorted(q for q in p.iterdir() if q.suffix.lower() in _EXT_IMAGEN)
        else:
            out.append(p)
    if not out:
        raise ValueError("ninguna imagen en: %s" % spec)
    return out[:maximo]


def mosaico(spec: str, etiquetas: str = "", salida: str = "", columnas: int = 0, ctx=None) -> str:
    rutas = _expandir_rutas(spec, ctx=ctx)
    etq = [e.strip() for e in etiquetas.split(",")] if etiquetas else [r.name for r in rutas]
    png = _pc.ruta_salida(ctx, "mosaico", ".png", salida)
    _pc.mosaico(rutas, png, etiquetas=etq, columnas=_pc.entero(columnas, 0, 0, 6))
    info = _pc.resumen_imagen(png)
    _marcar("captura_mosaico", spec, png, "%d imagenes" % len(rutas))
    return "mosaico de %d imagenes en %s (%dx%d): %s" % (
        len(rutas), png, info["ancho"], info["alto"], ", ".join(etq[:len(rutas)]))


def cuadricula(ruta: str, paso: int = 100, salida: str = "", ctx=None) -> str:
    Image = _pc.importar("PIL.Image")
    ImageDraw = _pc.importar("PIL.ImageDraw")
    p, im = _abrir(ruta, ctx)
    base = im.convert("RGBA")
    paso = _pc.entero(paso, 100, 10, 1000)
    W, H = base.size
    capa = Image.new("RGBA", base.size, (0, 0, 0, 0))
    dib = ImageDraw.Draw(capa)
    for x in range(0, W, paso):
        dib.line([(x, 0), (x, H)], fill=(255, 0, 255, 110), width=1)
        dib.text((x + 2, 2), str(x), fill=(255, 0, 255, 255))
    for y in range(0, H, paso):
        dib.line([(0, y), (W, y)], fill=(0, 200, 255, 110), width=1)
        dib.text((2, y + 2), str(y), fill=(0, 200, 255, 255))
    # sub-marcas cada paso/2 para afinar sin llenar de numeros
    for x in range(paso // 2, W, paso):
        dib.line([(x, 0), (x, H)], fill=(255, 0, 255, 45), width=1)
    for y in range(paso // 2, H, paso):
        dib.line([(0, y), (W, y)], fill=(0, 200, 255, 45), width=1)
    res = Image.alpha_composite(base, capa).convert("RGB")
    png = _pc.ruta_salida(ctx, "cuadricula_" + p.stem, ".png", salida)
    res.save(str(png))
    _marcar("captura_cuadricula", p, png, "paso %d" % paso)
    return ("cuadricula cada %d px (magenta = x, celeste = y) sobre %dx%d -> %s. "
            "Las coordenadas de la rejilla son pixeles de la imagen original." % (paso, W, H, png))


def comparar_color(ruta: str, punto: str, esperado: str, tolerancia: int = 24, ctx=None) -> str:
    p, im = _abrir(ruta, ctx)
    im = im.convert("RGB")
    nums = re.findall(r"-?\d+", punto or "")
    if len(nums) != 2:
        raise ValueError("punto: x,y")
    x, y = int(nums[0]), int(nums[1])
    if not (0 <= x < im.width and 0 <= y < im.height):
        raise ValueError("(%d,%d) cae fuera de la imagen %dx%d" % (x, y, im.width, im.height))
    m = re.match(r"^#?([0-9a-fA-F]{6})$", (esperado or "").strip())
    if not m:
        raise ValueError("color esperado: #rrggbb")
    esp = tuple(int(m.group(1)[i:i + 2], 16) for i in (0, 2, 4))
    real = im.getpixel((x, y))
    # media 3x3: un pixel de borde antialiasado no representa la zona
    acc = [0, 0, 0]
    n = 0
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            xx, yy = x + dx, y + dy
            if 0 <= xx < im.width and 0 <= yy < im.height:
                px = im.getpixel((xx, yy))
                for i in range(3):
                    acc[i] += px[i]
                n += 1
    media = tuple(int(v / n) for v in acc)
    tol = _pc.entero(tolerancia, 24, 0, 255)
    dist = max(abs(real[i] - esp[i]) for i in range(3))
    dist_m = max(abs(media[i] - esp[i]) for i in range(3))
    ok = dist <= tol or dist_m <= tol
    veredicto = "COINCIDE" if ok else "NO coincide"
    _marcar("captura_comparar_color", p, "", veredicto)
    return ("pixel (%d,%d) = %s, media 3x3 = %s, esperado %s, tolerancia %d -> %s (distancia %d)"
            % (x, y, _hex(real), _hex(media), _hex(esp), tol, veredicto, min(dist, dist_m)))


def describir(ruta: str, pregunta: str = "", ctx=None) -> str:
    p, _ = _abrir(ruta, ctx)
    tecnico = inspeccionar(str(p))
    activo = os.environ.get("COGNIA_VLM_TOOLS", "").strip().lower() in ("1", "on", "true", "yes")
    try:
        from cognia.agent.tools import TOOLS, run_tool
        hay_vlm = activo and "vlm_mirar" in TOOLS
    except Exception:
        hay_vlm = False
    if hay_vlm:
        args = str(p) + ((" | " + pregunta) if pregunta else "")
        semantico = run_tool("vlm_mirar", args, ctx or {})
        _marcar("captura_describir", p, "", "con VLM")
        return "%s\nTECNICO: %s" % (semantico, tecnico)
    _marcar("captura_describir", p, "", "sin VLM")
    return ("%s\nsin VLM: activa la familia vlm (/activar vlm, o COGNIA_VLM_TOOLS=1 con el VLM "
            "servido) para una descripcion semantica; lo de arriba es solo el analisis tecnico."
            % tecnico)


def texto(ruta: str, ctx=None) -> str:
    p, im = _abrir(ruta, ctx)
    try:
        import pytesseract  # type: ignore
    except Exception:
        raise ValueError("OCR no disponible: falta pytesseract. Instala tesseract (winget install "
                         "UB-Mannheim.TesseractOCR) y luego: pip install pytesseract")
    import shutil
    exe = shutil.which("tesseract") or (
        r"C:\Program Files\Tesseract-OCR\tesseract.exe" if os.path.isfile(r"C:\Program Files\Tesseract-OCR\tesseract.exe") else "")
    if not exe:
        raise ValueError("OCR no disponible: pytesseract esta pero no el binario tesseract. Instalalo con: "
                         "winget install UB-Mannheim.TesseractOCR")
    pytesseract.pytesseract.tesseract_cmd = exe
    try:
        t = pytesseract.image_to_string(im.convert("RGB"), lang="spa+eng")
    except Exception:
        t = pytesseract.image_to_string(im.convert("RGB"))
    t = re.sub(r"\n{3,}", "\n\n", t or "").strip()
    _marcar("captura_texto", p, "", "%d chars" % len(t))
    if not t:
        return "OCR no encontro texto en %s" % p.name
    return "texto OCR de %s (%d chars):\n%s" % (p.name, len(t), t[:4000])


# ---------------------------------------------------------------------------
# Registro
# ---------------------------------------------------------------------------

def _envolver(nombre, fn):
    """Envuelve una operacion en el contrato RESULTADO/ERROR uniforme."""
    def _t(args, ctx):
        try:
            return "RESULTADO %s: %s" % (nombre, fn(args, ctx))
        except ValueError as exc:
            return "RESULTADO %s ERROR: %s" % (nombre, exc)
        except Exception as exc:
            return "RESULTADO %s ERROR: %s: %s" % (nombre, type(exc).__name__, str(exc)[:200])
    _t.__name__ = "_t_" + nombre
    return _t


def _p(nombre, tipo, desc, requerido=False, clave=False):
    d = {"nombre": nombre, "tipo": tipo, "requerido": requerido, "descripcion": desc}
    if clave:
        d["clave"] = True
    return d


def register(tool) -> None:
    tool("captura_inspeccionar",
         "captura_inspeccionar <ruta>          -- que hay en una imagen: tamano, colores, brillo, vacia o con contenido, animacion",
         desc="Analiza una imagen o captura (PNG/JPG/GIF/WebP/BMP) sin necesidad de VLM: tamano y modo, "
              "los 5 colores mas frecuentes, brillo medio, transparencia, si es un GIF animado (fotogramas "
              "y duracion) y un VEREDICTO: 'UN solo color / casi uniforme' (la pagina o el canvas no pinto "
              "nada) o 'tiene contenido'. Usala despues de renderizar o de app_ver para saber si la captura "
              "muestra algo antes de dar por buena una interfaz.",
         params=[_p("ruta", "string", "ruta de la imagen", True)],
         timeout_s=60)(_envolver("captura_inspeccionar", lambda a, c: inspeccionar(_pc.partir_args(a, [])[0], ctx=c)))

    def _diff(a, ctx):
        obj, o = _pc.partir_args(a, ["salida", "umbral"])
        partes = [t.strip() for t in obj.split("|") if t.strip()]
        if len(partes) != 2:
            raise ValueError("uso: captura_diff <a> | <b> [| salida=X.png] [| umbral=N]")
        return diff(partes[0], partes[1], salida=o.get("salida", ""),
                    umbral=_pc.entero(o.get("umbral"), 24, 0, 255), ctx=ctx)
    tool("captura_diff",
         "captura_diff <a> | <b> [| salida=X.png] [| umbral=N]  -- compara dos imagenes: % de pixeles distintos, caja del cambio y PNG de diferencias",
         desc="Compara dos capturas (antes/despues, esperado/obtenido): porcentaje de pixeles que cambian, "
              "la caja (x,y) donde esta el cambio, si los tamanos difieren, y guarda un PNG con el cambio en "
              "rojo. Veredicto: IDENTICAS (<0,1%), cambio leve (<5%) o cambio GRANDE. Sirve para comprobar "
              "que una tecla o un clic cambio la pantalla, o que un refactor no altero el render.",
         params=[_p("a", "string", "primera imagen", True), _p("b", "string", "segunda imagen", True),
                 _p("salida", "string", "ruta del PNG de diferencias", clave=True),
                 _p("umbral", "integer", "diferencia minima por canal para contar un pixel (default 24)", clave=True)],
         timeout_s=60)(_envolver("captura_diff", _diff))

    def _rec(a, ctx):
        obj, o = _pc.partir_args(a, ["zoom", "salida", "region"])
        partes = [t.strip() for t in obj.split("|") if t.strip()]
        if not partes:
            raise ValueError("uso: captura_recortar <ruta> | x,y,ancho,alto [| zoom=N] [| salida=X.png]")
        caja = partes[1] if len(partes) > 1 else ""
        return recortar(partes[0], caja=caja, region=o.get("region", ""), zoom=_pc.entero(o.get("zoom"), 1, 1, 16),
                        salida=o.get("salida", ""), ctx=ctx)
    tool("captura_recortar",
         "captura_recortar <ruta> | x,y,ancho,alto [| zoom=N] [| region=centro|arriba|abajo|izquierda|derecha] [| salida=X.png]  -- recorta y amplia una zona para mirarla en detalle",
         desc="Recorta una region de la imagen (x,y,ancho,alto en pixeles, o un atajo region=centro|arriba|"
              "abajo|izquierda|derecha) y la amplia zoom veces sin suavizar, para inspeccionar un boton, un "
              "texto pequeno o un sprite. Devuelve la ruta del recorte y su analisis (colores, vacio o no).",
         params=[_p("ruta", "string", "imagen de origen", True), _p("caja", "string", "x,y,ancho,alto"),
                 _p("zoom", "integer", "factor de ampliacion 1-16 (default 1)", clave=True),
                 _p("region", "string", "atajo: centro|arriba|abajo|izquierda|derecha", clave=True),
                 _p("salida", "string", "ruta del PNG recortado", clave=True)],
         timeout_s=60)(_envolver("captura_recortar", _rec))

    def _mos(a, ctx):
        obj, o = _pc.partir_args(a, ["etiquetas", "salida", "columnas"])
        if not obj:
            raise ValueError("uso: captura_mosaico <ruta1>,<ruta2>,... [| etiquetas=a,b] [| salida=X.png] [| columnas=N]")
        return mosaico(obj, etiquetas=o.get("etiquetas", ""), salida=o.get("salida", ""),
                       columnas=_pc.entero(o.get("columnas"), 0, 0, 6), ctx=ctx)
    tool("captura_mosaico",
         "captura_mosaico <ruta1>,<ruta2>,... [| etiquetas=a,b,c] [| salida=X.png] [| columnas=N]  -- une varias imagenes (o un glob/directorio) en una hoja de contactos rotulada",
         desc="Arma una sola imagen con varias capturas escaladas y rotuladas (hoja de contactos), para ver de "
              "un vistazo una secuencia (fotogramas, antes/despues, tres anchos de pantalla). Acepta rutas "
              "separadas por coma, globs (*.png) y directorios (todas sus imagenes por nombre, maximo 24).",
         params=[_p("imagenes", "string", "rutas separadas por coma, glob o directorio", True),
                 _p("etiquetas", "string", "rotulos separados por coma", clave=True),
                 _p("salida", "string", "ruta del PNG del mosaico", clave=True),
                 _p("columnas", "integer", "columnas del mosaico (auto por defecto)", clave=True)],
         timeout_s=90)(_envolver("captura_mosaico", _mos))

    def _cuad(a, ctx):
        obj, o = _pc.partir_args(a, ["paso", "salida"])
        if not obj:
            raise ValueError("uso: captura_cuadricula <ruta> [| paso=100] [| salida=X.png]")
        return cuadricula(obj, paso=_pc.entero(o.get("paso"), 100, 10, 1000), salida=o.get("salida", ""), ctx=ctx)
    tool("captura_cuadricula",
         "captura_cuadricula <ruta> [| paso=100] [| salida=X.png]  -- dibuja una rejilla con coordenadas sobre la imagen para nombrar posiciones exactas",
         desc="Superpone una cuadricula rotulada (cada `paso` pixeles, x en magenta, y en celeste) sobre una "
              "captura, para que tu o el VLM podais decir 'el boton esta en (340,220)' y pasar esa coordenada "
              "a un clic (app_clic, renderizar con guion 'clic x,y').",
         params=[_p("ruta", "string", "imagen", True), _p("paso", "integer", "separacion en px (default 100)", clave=True),
                 _p("salida", "string", "ruta del PNG", clave=True)],
         timeout_s=60)(_envolver("captura_cuadricula", _cuad))

    def _col(a, ctx):
        obj, o = _pc.partir_args(a, ["tolerancia"])
        partes = [t.strip() for t in obj.split("|") if t.strip()]
        if len(partes) != 3:
            raise ValueError("uso: captura_comparar_color <ruta> | x,y | #rrggbb [| tolerancia=N]")
        return comparar_color(partes[0], partes[1], partes[2], tolerancia=_pc.entero(o.get("tolerancia"), 24, 0, 255), ctx=ctx)
    tool("captura_comparar_color",
         "captura_comparar_color <ruta> | x,y | #rrggbb [| tolerancia=N]  -- el color real de un pixel (y su media 3x3) contra el esperado",
         desc="Lee el color del pixel (x,y) y la media de su vecindad 3x3 y lo compara con un color esperado "
              "#rrggbb con tolerancia por canal (default 24). Veredicto COINCIDE / NO coincide. Para comprobar "
              "que el fondo, un sprite o un boton se pintaron del color que pediste.",
         params=[_p("ruta", "string", "imagen", True), _p("punto", "string", "x,y", True),
                 _p("esperado", "string", "#rrggbb", True),
                 _p("tolerancia", "integer", "diferencia maxima por canal (default 24)", clave=True)],
         timeout_s=30)(_envolver("captura_comparar_color", _col))

    def _desc(a, ctx):
        obj, o = _pc.partir_args(a, ["pregunta"])
        if not obj:
            raise ValueError("uso: captura_describir <ruta> [| pregunta=...]")
        return describir(obj, pregunta=o.get("pregunta", ""), ctx=ctx)
    tool("captura_describir",
         "captura_describir <ruta> [| pregunta=...]  -- descripcion de la imagen: con el VLM si esta activo, si no el analisis tecnico",
         desc="Describe que se ve en una imagen. Si la familia vlm esta activa (COGNIA_VLM_TOOLS=1 y el VLM "
              "servido) delega en vlm_mirar y anade el analisis tecnico; si no, devuelve solo el analisis "
              "tecnico y lo dice. Nunca inventa lo que no puede ver.",
         params=[_p("ruta", "string", "imagen", True), _p("pregunta", "string", "que quieres saber de la imagen", clave=True)],
         timeout_s=180)(_envolver("captura_describir", _desc))

    tool("captura_texto",
         "captura_texto <ruta>                 -- lee el texto de una imagen por OCR (tesseract); si no esta, dice como instalarlo",
         desc="OCR de una captura o imagen con tesseract (pytesseract). Devuelve el texto leido; si tesseract "
              "no esta instalado devuelve ERROR con el comando exacto para instalarlo, nunca texto inventado.",
         params=[_p("ruta", "string", "imagen", True)],
         timeout_s=120)(_envolver("captura_texto", lambda a, c: texto(_pc.partir_args(a, [])[0], ctx=c)))


NOMBRES = ("captura_inspeccionar", "captura_diff", "captura_recortar", "captura_mosaico",
           "captura_cuadricula", "captura_comparar_color", "captura_describir", "captura_texto")
