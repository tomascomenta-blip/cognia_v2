# -*- coding: utf-8 -*-
"""
frames_gate.py — gate de PIXELES solo-stdlib (zlib + struct): rechaza el frame
negro y el lienzo uniforme, y mide cuanto cambia una pagina entre dos frames.

PROCEDENCIA (esto es codigo VENDORIZADO, no original de Cognia):
  origen : C:/Users/usuario/Desktop/ai_game_factory/agf/core/frames.py
           (+ las primitivas de agf/core/png.py: FIRMA, CANALES, paeth, desfiltrar)
  commit : 75725366901acef73c3bca2fdbe4a0b9e4d09f72  (2026-08-11 16:03:12 -0500)
  copiado: 2026-08-29

POR QUE VENDORIZADO Y NO IMPORTADO: agf NO esta instalado en venv312
(importlib.util.find_spec('agf') -> None), asi que sin copiar no hay reuso
posible; y meter Desktop/ai_game_factory en sys.path acopla Cognia a un repo
ajeno que puede moverse o borrarse. El precio es la desincronizacion: si AGF
cambia frames.py, esta copia NO se entera. Se acepta a cambio de que Cognia
siga siendo instalable con `pip install cognia-ai` y sin dependencias nuevas.

QUE SE COPIO: las primitivas de decodificacion PNG, medir() y los tres
umbrales del gate. QUE NO: elegir_frames, montar_lado_a_lado y data_uri, que
sirven al VLM de AGF y aqui no tienen consumidor.

QUE SE ANADIO AQUI (no existe en AGF): fraccion_pixeles_distintos(), la
metrica observable del brazo BASE/ACTIVO para paginas — AGF la mide dentro de
Godot con desplazamiento_jugador/colisiones, que en una pagina web no existen.

POR QUE existe el rechazo de negro (razon literal del original): el precedente
del repo (bot de TSB) es una captura que entregaba negro y nadie lo noto; y el
arbitro visual de Cognia le saco 9,5 "Excelente" a un PNG de 1x1. Un frame
negro o un lienzo uniforme NO se puntuan: se rechazan con motivo. Puntuar un
negro como "juego oscuro" es fabricar un veredicto.
"""

import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

# ── Primitivas PNG (de agf/core/png.py) ────────────────────────────────────────

FIRMA_PNG = b"\x89PNG\r\n\x1a\n"

# Muestras por pixel segun el tipo de color del IHDR.
# 0=gris, 2=RGB, 3=paleta indexada, 4=gris+alfa, 6=RGBA.
CANALES = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}

# ── Umbrales del gate (los tres son de AGF, con su valor medido) ───────────────

# Un frame es NEGRO si NINGUN pixel muestreado supera esta luma (0-255): no es
# "oscuro", es que no se renderizo nada.
UMBRAL_NEGRO = 12.0
# Un frame es UNIFORME (lienzo plano, sin nada dibujado) si su luma casi no varia.
UMBRAL_UNIFORME = 1.0
# Lado minimo juzgable, heredado de arbitro_visual.MIN_LADO_SCREENSHOT.
MIN_LADO = 100
# Fraccion MINIMA de los frames muestreados que tiene que ser juzgable para que
# una captura cuente como "hay algo que mirar".
FRACCION_JUZGABLE_MINIMA = 0.5

# Un pixel cuenta como CAMBIADO si su luma se movio mas que esto. 8/255 deja
# fuera el ruido de compresion y el antialiasing del texto, que en dos capturas
# consecutivas de la MISMA pagina quieta ya movia 2-3 niveles.
UMBRAL_CAMBIO_LUMA = 8.0


class FrameError(Exception):
    """PNG ilegible o con un formato que no sabemos decodificar."""


@dataclass
class InfoPNG:
    """Cabecera IHDR de un PNG."""
    ancho: int
    alto: int
    profundidad: int
    colortype: int


@dataclass
class MedidaFrame:
    """Histograma barato de un frame: lo justo para decidir si es juzgable."""
    ruta: str = ""
    ancho: int = 0
    alto: int = 0
    luminancia: float = 0.0
    desviacion: float = 0.0
    maximo: int = 0
    colores: int = 0
    negro: bool = False
    uniforme: bool = False
    error: str = None

    @property
    def juzgable(self):
        """True si el frame tiene tamano y contenido como para juzgarlo."""
        return (self.error is None and not self.negro and not self.uniforme
                and min(self.ancho, self.alto) >= MIN_LADO)

    def motivo(self):
        """Por que NO es juzgable, en una linea. Cadena vacia si lo es."""
        if self.error:
            return self.error
        if self.negro:
            return f"frame NEGRO (luma maxima {self.maximo} <= {UMBRAL_NEGRO})"
        if self.uniforme:
            return f"lienzo UNIFORME (desviacion {self.desviacion:.2f} < {UMBRAL_UNIFORME})"
        if min(self.ancho, self.alto) < MIN_LADO:
            return f"captura diminuta {self.ancho}x{self.alto} (min {MIN_LADO})"
        return ""


def paeth(a, b, c):
    """Predictor Paeth del filtro 4 (izquierda, arriba, diagonal)."""
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def desfiltrar(crudo, alto, stride, bpp):
    """Deshace los cinco filtros de scanline del PNG sobre los datos inflados."""
    salida = bytearray(alto * stride)
    previa = bytearray(stride)
    pos = 0
    for y in range(alto):
        filtro = crudo[pos]
        pos += 1
        fila = bytearray(crudo[pos:pos + stride])
        pos += stride
        if filtro == 0:
            pass
        elif filtro == 1:
            for i in range(bpp, stride):
                fila[i] = (fila[i] + fila[i - bpp]) & 0xFF
        elif filtro == 2:
            for i in range(stride):
                fila[i] = (fila[i] + previa[i]) & 0xFF
        elif filtro == 3:
            for i in range(stride):
                izq = fila[i - bpp] if i >= bpp else 0
                fila[i] = (fila[i] + ((izq + previa[i]) >> 1)) & 0xFF
        elif filtro == 4:
            for i in range(stride):
                izq = fila[i - bpp] if i >= bpp else 0
                diag = previa[i - bpp] if i >= bpp else 0
                fila[i] = (fila[i] + paeth(izq, previa[i], diag)) & 0xFF
        else:
            raise FrameError(f"filtro de scanline desconocido: {filtro} (fila {y})")
        salida[y * stride:(y + 1) * stride] = fila
        previa = fila
    return salida


def chunk(tipo, cuerpo):
    """Serializa un chunk PNG completo (largo + tipo + cuerpo + CRC)."""
    return (struct.pack(">I", len(cuerpo)) + tipo + cuerpo
            + struct.pack(">I", zlib.crc32(tipo + cuerpo) & 0xFFFFFFFF))


# ── Decodificacion ─────────────────────────────────────────────────────────────

def _leer_chunks(datos):
    """Itera (tipo, cuerpo) sobre los chunks del PNG."""
    pos, total = 8, len(datos)
    while pos + 8 <= total:
        (largo,) = struct.unpack(">I", datos[pos:pos + 4])
        tipo = datos[pos + 4:pos + 8]
        yield tipo, datos[pos + 8:pos + 8 + largo]
        pos += largo + 12


def _cabecera(datos, nombre):
    """Parsea el IHDR o levanta FrameError."""
    if not datos.startswith(FIRMA_PNG) or len(datos) < 33:
        raise FrameError(f"{nombre}: no es un PNG (firma invalida)")
    ancho, alto, prof, color, _comp, _filt, entrelazado = struct.unpack(
        ">IIBBBBB", datos[16:29])
    if ancho <= 0 or alto <= 0:
        raise FrameError(f"{nombre}: dimensiones invalidas {ancho}x{alto}")
    if prof != 8:
        raise FrameError(f"{nombre}: profundidad {prof} no soportada (solo 8 bits)")
    if entrelazado:
        raise FrameError(f"{nombre}: PNG entrelazado no soportado")
    if color not in CANALES:
        raise FrameError(f"{nombre}: tipo de color {color} desconocido")
    return InfoPNG(ancho=ancho, alto=alto, profundidad=prof, colortype=color)


def _gris_a_rgb(gris):
    rgb = bytearray(len(gris) * 3)
    rgb[0::3] = gris
    rgb[1::3] = gris
    rgb[2::3] = gris
    return rgb


def _a_rgb(datos, info, paleta, nombre):
    """Normaliza cualquier tipo de color soportado a RGB de 8 bits."""
    if info.colortype == 2:
        return datos
    if info.colortype == 6:
        del datos[3::4]          # descarta alfa
        return datos
    if info.colortype == 4:
        del datos[1::2]
        return _gris_a_rgb(datos)
    if info.colortype == 0:
        return _gris_a_rgb(datos)
    if len(paleta) < 3:
        raise FrameError(f"{nombre}: PNG con paleta sin chunk PLTE")
    tabla = [paleta[i:i + 3] for i in range(0, len(paleta) - 2, 3)]
    ultimo = tabla[-1]
    return bytearray(b"".join(tabla[b] if b < len(tabla) else ultimo for b in datos))


def decodificar_rgb(origen):
    """PNG (ruta o bytes) -> (ancho, alto, pixeles RGB de 8 bits, fila por fila)."""
    if isinstance(origen, (bytes, bytearray)):
        datos, nombre = bytes(origen), "<bytes>"
    else:
        ruta = Path(origen)
        nombre = ruta.name
        try:
            datos = ruta.read_bytes()
        except OSError as exc:
            raise FrameError(f"no pude leer {ruta}: {exc}") from exc
    info = _cabecera(datos, nombre)
    idat, paleta = bytearray(), b""
    for tipo, cuerpo in _leer_chunks(datos):
        if tipo == b"IDAT":
            idat += cuerpo
        elif tipo == b"PLTE":
            paleta = cuerpo
        elif tipo == b"IEND":
            break
    if not idat:
        raise FrameError(f"{nombre}: PNG sin datos de imagen (IDAT vacio)")
    try:
        crudo = zlib.decompress(bytes(idat))
    except zlib.error as exc:
        raise FrameError(f"{nombre}: IDAT corrupto ({exc})") from exc
    canales = CANALES[info.colortype]
    stride = info.ancho * canales
    if len(crudo) < (stride + 1) * info.alto:
        raise FrameError(f"{nombre}: datos incompletos ({len(crudo)} bytes para "
                         f"{info.ancho}x{info.alto}x{canales})")
    lineas = desfiltrar(crudo, info.alto, stride, canales)
    return info.ancho, info.alto, _a_rgb(lineas, info, paleta, nombre)


def escribir_png(ancho, alto, pixeles, ruta):
    """Escribe un PNG RGB de 8 bits (filtro 0). Los tests fabrican frames con esto."""
    ruta = Path(ruta)
    stride = ancho * 3
    crudo = bytearray()
    for y in range(alto):
        crudo.append(0)
        crudo += bytes(pixeles[y * stride:(y + 1) * stride])
    ihdr = struct.pack(">IIBBBBB", ancho, alto, 8, 2, 0, 0, 0)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(FIRMA_PNG
                     + chunk(b"IHDR", ihdr)
                     + chunk(b"IDAT", zlib.compress(bytes(crudo), 6))
                     + chunk(b"IEND", b""))
    return ruta


# ── Medicion ───────────────────────────────────────────────────────────────────

def _lumas(origen, paso):
    """(ancho, alto, [luma muestreada], paso_real) o levanta FrameError."""
    ancho, alto, pix = decodificar_rgb(origen)
    total = ancho * alto
    paso = max(1, min(paso, max(1, total // 64)))
    lumas = []
    for i in range(0, total, paso):
        p = i * 3
        lumas.append(0.299 * pix[p] + 0.587 * pix[p + 1] + 0.114 * pix[p + 2])
    return ancho, alto, lumas, paso


def medir(origen, paso=7):
    """Mide un frame muestreando 1 de cada `paso` pixeles. NUNCA lanza."""
    nombre = "<bytes>" if isinstance(origen, (bytes, bytearray)) else str(origen)
    try:
        ancho, alto, pix = decodificar_rgb(origen)
    except FrameError as exc:
        return MedidaFrame(ruta=nombre, error=str(exc))
    except Exception as exc:                # un PNG raro no puede tumbar el gate
        return MedidaFrame(ruta=nombre, error=f"{type(exc).__name__}: {exc}")
    total = ancho * alto
    paso = max(1, min(paso, max(1, total // 64)))
    suma = suma2 = 0.0
    maximo = n = 0
    colores = set()
    for i in range(0, total, paso):
        p = i * 3
        r, g, b = pix[p], pix[p + 1], pix[p + 2]
        luma = 0.299 * r + 0.587 * g + 0.114 * b
        suma += luma
        suma2 += luma * luma
        if luma > maximo:
            maximo = int(luma)
        if len(colores) < 4096:
            colores.add((r << 16) | (g << 8) | b)
        n += 1
    media = suma / n if n else 0.0
    varianza = max(0.0, (suma2 / n) - media * media) if n else 0.0
    desviacion = varianza ** 0.5
    return MedidaFrame(
        ruta=nombre, ancho=ancho, alto=alto,
        luminancia=media, desviacion=desviacion, maximo=maximo,
        colores=len(colores),
        negro=maximo <= UMBRAL_NEGRO,
        uniforme=desviacion < UMBRAL_UNIFORME,
    )


def fraccion_juzgable(medidas):
    """Proporcion de los frames MEDIDOS que tienen algo que juzgar (0,0-1,0).

    Sin medidas devuelve 0,0, pero eso NO significa "pantalla plana": significa
    que no se midio nada. Quien decide con este numero tiene que mirar antes
    cuantos frames habia; esa distincion separa "no dibuja" de "no se capturo".
    """
    if not medidas:
        return 0.0
    return sum(1 for m in medidas if m.juzgable) / len(medidas)


def gate_capturas(capturas, paso=7):
    """
    El GATE: (ok, motivo, medidas) sobre una lista de capturas (rutas o bytes).

    ok=False si no hay capturas, o si menos de FRACCION_JUZGABLE_MINIMA de
    ellas es juzgable. El motivo NOMBRA el fallo del primer frame no juzgable:
    "frame NEGRO" y "no se pudo capturar" son cosas distintas y quien puntua
    tiene que poder distinguirlas.
    """
    medidas = [medir(c, paso=paso) for c in (capturas or [])]
    if not medidas:
        return False, "no hay ninguna captura que juzgar", medidas
    buenas = sum(1 for m in medidas if m.juzgable)
    if fraccion_juzgable(medidas) < FRACCION_JUZGABLE_MINIMA:
        malos = [m.motivo() for m in medidas if not m.juzgable]
        return (False,
                f"{buenas}/{len(medidas)} capturas juzgables "
                f"(minimo {FRACCION_JUZGABLE_MINIMA}): "
                f"{malos[0] if malos else 'sin motivo'}",
                medidas)
    return True, f"{buenas}/{len(medidas)} capturas juzgables", medidas


def fraccion_pixeles_distintos(a, b, paso=7, umbral=UMBRAL_CAMBIO_LUMA):
    """
    ANADIDO EN COGNIA (no viene de AGF): fraccion 0,0-1,0 de pixeles muestreados
    cuya luma cambia mas de `umbral` entre dos frames.

    Es la METRICA OBSERVABLE del brazo BASE vs ACTIVO para una pagina: AGF mide
    desplazamiento del jugador y colisiones porque corre dentro de Godot; aqui
    lo unico que se puede medir sin inventar es cuanto se movio la imagen.

    Devuelve None (NO MEDIDO) si algun frame es ilegible o si las dos capturas
    tienen tamanos distintos. None jamas se confunde con 0.0 — regla de
    agf/core/scores.py: "un score sin evidencia no se emite".
    """
    try:
        ancho_a, alto_a, lumas_a, paso_a = _lumas(a, paso)
        ancho_b, alto_b, lumas_b, _ = _lumas(b, paso_a)
    except Exception:
        return None
    if (ancho_a, alto_a) != (ancho_b, alto_b) or not lumas_a:
        return None
    n = min(len(lumas_a), len(lumas_b))
    if not n:
        return None
    distintos = sum(1 for i in range(n) if abs(lumas_a[i] - lumas_b[i]) > umbral)
    return distintos / n
