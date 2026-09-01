# -*- coding: utf-8 -*-
"""
cognia/clases/widget_icono.py
=============================
EL CEREBRITO, en PNG. Dibuja con Pillow el icono que el widget de escritorio
(widget.py) le da a Tk, en sus cinco estados y con los fotogramas del latido.

POR QUE SE DIBUJA Y NO SE CONVIERTE EL SVG
------------------------------------------
`assets/cerebro.svg` es la FUENTE DE DISENIO, pero Tk no sabe pintar SVG y en
esta maquina no hay cairosvg ni tksvg (medido 2026-08-31). Asi que aqui se
redibuja la misma figura con `PIL.ImageDraw`. La consecuencia es que hay DOS
dibujos de la misma cosa, y por eso la regla de la casa:

    LOS COLORES SON UN TOKEN CON UNA SOLA FUENTE: `assets/cerebro.svg`.
    `PALETA` de abajo esta copiada literalmente de sus `stop-color`. Cambiar
    la paleta se hace EN EL SVG y se copia aqui. Dos paletas darian dos
    cerebritos distintos -- uno en la pagina del cuaderno y otro en el
    escritorio -- que es el fallo que este comentario existe para evitar.

EL HALO: POR QUE EL BORDE ES DURO A PROPOSITO
---------------------------------------------
MEDIDO Y ASUMIDO. Tk NO tiene alfa por pixel: una ventana `overrideredirect`
se hace transparente con `-transparentcolor`, que es transparencia POR CLAVE
DE COLOR (el pixel que vale EXACTAMENTE ese color desaparece; todos los demas
se pintan opacos). Un icono con el borde suavizado -- que es lo que sale de
reducir con antialias -- tiene un anillo de pixeles a medio camino entre el
dibujo y el fondo: ninguno vale exactamente la clave, asi que ninguno
desaparece y el resultado contra el escritorio es un HALO del color clave
(magenta) rodeando la esfera.

Aqui se resuelve con las dos mitades a la vez:

  1. PRECOMPONER. El dibujo se hace sobre un lienzo OPACO (el color exterior
     de la esfera), nunca sobre transparencia. Asi todo el suavizado interno
     -- los surcos, el degradado, el tallo -- mezcla colores del icono con
     colores del icono, y sale suave de verdad.
  2. BORDE DURO SOLO EN LA SILUETA. La mascara del disco se reduce con
     antialias y despues se UMBRALIZA a 0/255 (`UMBRAL_SILUETA`). El
     contorno de la esfera queda escalonado -- se ve si uno se acerca -- pero
     no hay un solo pixel intermedio que pueda convertirse en halo.

O sea: se cambia un borde perfecto (imposible) por un borde dentado (feo de
cerca, invisible a 24-48 px) en vez de por un halo magenta (visible siempre).

EL CACHE
--------
Dibujar los ~10 PNG cuesta decimas de segundo, pero el widget arranca cada vez
que el duenio enciende el equipo y el latido pide un fotograma cada 120 ms:
regenerar ahi seria trabajo inutil en el hilo de Tk. Los PNG se guardan en
`<raiz de clases>/iconos/` con la VERSION del dibujo en el nombre, asi que
tocar este fichero (y subir `VERSION`) invalida el cache solo, sin borrar
nada. `dibujos()` cuenta cuantas veces se ha dibujado DE VERDAD: es la puerta
de diagnostico que distingue "el cache funciona" de "se redibuja cada vez".
"""

from __future__ import annotations

import logging
import math
import os
import tempfile
import threading
import time
from pathlib import Path

from cognia.clases import almacen as alm

log = logging.getLogger(__name__)

# Sube al tocar el dibujo: va en el nombre del PNG, asi que un cambio aqui
# invalida el cache sin que nadie tenga que borrar la carpeta a mano.
VERSION = 1

# Subcarpeta del cuaderno donde viven los PNG. Dentro de `almacen.raiz()` para
# que COGNIA_CLASES_DIR la mueva tambien (los tests no pueden escribir en el
# cuaderno real del duenio).
DIR_ICONOS = "iconos"

# ── LA PALETA. Copiada literalmente de assets/cerebro.svg ─────────────────────
# UNICA FUENTE: el SVG. Ver el encabezado.
PALETA = {
    # <radialGradient id="esfera">
    "esfera_alta": "#3a3f47",
    "esfera_media": "#16181c",
    "esfera_baja": "#050506",
    # <linearGradient id="verde">
    "verde_claro": "#6ef7a8",
    "verde": "#35d67f",
    "verde_oscuro": "#18a35c",
    # surcos y tallo
    "surco": "#0b3f26",
    "tallo": "#18a35c",
}

# EL UNICO COLOR QUE NO SALE DEL SVG, y por eso se declara aparte: el aviso de
# captura rota. El SVG no tiene estado de error porque en la pagina del
# cuaderno el error se cuenta con texto; en un icono de 32 px no cabe texto.
ROJO_AVISO = "#ff5a52"

# La clave de transparencia de Tk. Un magenta que NO existe en la paleta (ver
# `colisiones_clave`, que lo comprueba de verdad en vez de confiar).
COLOR_CLAVE = "#ff00fe"

# Por encima de esto el pixel de la silueta es icono; por debajo, transparente.
# 128 es la mitad exacta: el contorno queda donde la mascara suavizada cruza el
# 50 %, que es la posicion honesta del borde.
UMBRAL_SILUETA = 128

# Fotogramas del latido. 6 a 120 ms dan un ciclo de 0,72 s -- ritmo de pulso
# tranquilo, no de alarma -- y son 6 PNG, no 60.
PASOS_LATIDO = 6

# Cuanto sube y baja el brillo en el latido. +-17 %: se nota de reojo y no
# parpadea.
LATIDO_MIN = 0.83
LATIDO_MAX = 1.17

ESTADOS = ("apagado", "grabando", "pausada", "muteado", "fallo")

# (saturacion, brillo) por estado. El estado se PINTA con el mismo dibujo:
# tenerlo asi (y no como cinco dibujos) es lo que garantiza que el cerebrito
# apagado y el que graba son el mismo cerebrito.
AJUSTES = {
    "apagado": (0.30, 0.45),    # sin jornada: ahi esta, pero no hace nada
    "grabando": (1.00, 1.00),   # el brillo lo modula el latido
    "pausada": (0.60, 0.68),    # apagado a medias: sigue habiendo jornada
    "muteado": (0.00, 0.62),    # gris literal: el audio no entra
    "fallo": (1.00, 0.95),      # el aviso lo da el anillo rojo, no el brillo
}

# Reintentos del os.replace al publicar el PNG. MEDIDO en este repo (ver
# jornada._reescribir_jsonl, 2026-08-31): en Windows `os.replace` sobre un
# destino que otro proceso tiene ABIERTO para leer falla con PermissionError
# [WinError 5/32]. Aqui el lector es el propio Tk cargando el PhotoImage, que
# lo tiene abierto microsegundos: reintentar poco y rapido basta.
_REINTENTOS_REPLACE = 20
_ESPERA_REPLACE = 0.025

# Serializa dibujar-y-publicar. NO ES ADORNO: el widget precalienta los iconos
# EN UN HILO mientras el hilo de Tk pide el primero, o sea que los dos generan
# el MISMO PNG a la vez. Sin este lock los dos escriben, cada uno mira si el
# cache vale antes de que el otro termine, y ademas se pisan el temporal --
# reproducido en la suite el 2026-08-31: `PermissionError [WinError 32]` al
# renombrar, y el icono sin cargar. Con el lock el segundo encuentra el
# fichero ya bueno y no dibuja nada.
_LOCK_DIBUJO = threading.RLock()

_DIBUJOS = [0]
_MEMO: dict = {}


def dibujos() -> int:
    """Cuantos PNG se han dibujado DE VERDAD en este proceso.

    Puerta de diagnostico (CLAUDE.md): con el cache sano este numero se queda
    quieto tras el arranque. Si crece con cada latido, el cache no vale y el
    widget esta quemando CPU en el hilo de Tk -- y eso, sin contador, se ve
    exactamente igual que un widget sano.
    """
    return int(_DIBUJOS[0])


# ── Color ────────────────────────────────────────────────────────────────────

def rgb(hexa: str) -> tuple:
    """'#35d67f' -> (53, 214, 127)."""
    t = str(hexa).lstrip("#")
    return (int(t[0:2], 16), int(t[2:4], 16), int(t[4:6], 16))


def mezclar(fondo, frente, alfa: float) -> tuple:
    """`frente` sobre `fondo` con opacidad `alfa`, en RGB opaco.

    Es lo que sustituye a `stroke-opacity`/`fill-opacity` del SVG: aqui no hay
    canal alfa (ver el encabezado), asi que la transparencia del diseno se
    resuelve ANTES, mezclando numeros.
    """
    a = max(0.0, min(1.0, float(alfa)))
    return tuple(int(round(f * (1.0 - a) + p * a)) for f, p in zip(fondo, frente))


def color_en(paradas: list, t: float) -> tuple:
    """El color de un degradado en la posicion `t` (0..1).

    `paradas` es [(offset, '#rrggbb'), ...] tal cual sale de los `<stop>` del
    SVG, lo que permite copiarlas sin traducir nada.
    """
    t = max(0.0, min(1.0, float(t)))
    previo = paradas[0]
    for parada in paradas:
        if t <= parada[0]:
            if parada[0] == previo[0]:
                return rgb(parada[1])
            f = (t - previo[0]) / (parada[0] - previo[0])
            return mezclar(rgb(previo[1]), rgb(parada[1]), f)
        previo = parada
    return rgb(paradas[-1][1])


def colisiones_clave(img, silueta=None) -> int:
    """Cuantos pixeles DE DENTRO DEL ICONO valen exactamente el color clave.

    Tiene que ser 0. Cada uno seria un agujero transparente en mitad del
    cerebrito, y como el color clave es magenta se veria el escritorio por
    dentro de la esfera. Se comprueba en vez de razonarlo: la paleta la cambia
    quien edite el SVG, que no tiene por que acordarse de este fichero.

    `silueta` es la mascara del disco. SIN ELLA NO SIRVE DE NADA: fuera del
    disco el icono es color clave A PROPOSITO (es lo que hace transparente el
    fondo cuadrado de la ventana), asi que contar la imagen entera devuelve
    siempre cientos de "colisiones" que no lo son. Se pide explicitamente para
    que nadie la olvide creyendo que el defecto es seguro.
    """
    clave = rgb(COLOR_CLAVE)
    plano = img.convert("RGB")
    px = plano.load()
    mask = silueta.load() if silueta is not None else None
    ancho, alto = plano.size
    n = 0
    for y in range(alto):
        for x in range(ancho):
            if mask is not None and not mask[x, y]:
                continue
            if px[x, y] == clave:
                n += 1
    return n


# ── Degradados (PIL no los tiene) ────────────────────────────────────────────

def _radial(lado: int, centro: tuple, radio: float, paradas: list):
    from PIL import Image
    img = Image.new("RGB", (lado, lado))
    px = img.load()
    cx, cy = centro
    radio = max(1e-6, float(radio))
    for y in range(lado):
        dy = y + 0.5 - cy
        for x in range(lado):
            dx = x + 0.5 - cx
            px[x, y] = color_en(paradas, math.hypot(dx, dy) / radio)
    return img


def _lineal(lado: int, p0: tuple, p1: tuple, paradas: list):
    from PIL import Image
    img = Image.new("RGB", (lado, lado))
    px = img.load()
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    den = max(1e-6, dx * dx + dy * dy)
    for y in range(lado):
        for x in range(lado):
            t = ((x + 0.5 - p0[0]) * dx + (y + 0.5 - p0[1]) * dy) / den
            px[x, y] = color_en(paradas, t)
    return img


# ── El dibujo, en coordenadas del SVG (viewBox 0 0 128 128) ──────────────────
# Se trabaja en las MISMAS unidades que cerebro.svg y se escala al final: asi
# cualquier cifra de aqui se puede comparar con el SVG a ojo, que es lo que
# hace que las dos figuras no se separen con el tiempo.

# Los lobulos, como cumulos de circulos (cx, cy, r) en el espacio del SVG. El
# `path` del SVG no se puede reusar: parsear Bezier a mano para un icono de
# 32 px seria mas codigo que dibujo, y a ese tamanio la silueta es lo unico
# que se lee.
_LOBULO = [(50, 41, 13), (40, 51, 12), (36, 64, 12), (40, 77, 12),
           (51, 86, 12), (58, 51, 14), (56, 67, 14), (58, 80, 11)]

# Surcos: (bbox, angulo_inicio, angulo_fin) del lobulo izquierdo.
_SURCOS = [((38, 36, 58, 52), 30, 175),
           ((32, 52, 54, 70), 20, 170),
           ((36, 70, 58, 88), 20, 160)]


def _espejo_caja(caja: tuple) -> tuple:
    x0, y0, x1, y1 = caja
    return (128 - x1, y0, 128 - x0, y1)


def _lienzo_2x(lado2x: int, alarma: bool):
    """(imagen RGB, mascara del disco) del cerebrito a 2x, sin estado.

    Devuelve el dibujo BASE: la esfera, el cerebro y los surcos. El estado
    (gris, apagado, latido) se aplica despues como ajuste de brillo/color
    sobre esta misma imagen, para que los cinco estados sean literalmente el
    mismo cerebrito y no cinco dibujos que se van separando.

    `alarma` es la unica variante estructural: el anillo pasa a rojo. Va aqui
    y no en el ajuste porque un anillo rojo no se puede conseguir subiendole
    el brillo a uno verde.
    """
    from PIL import Image, ImageDraw
    s = lado2x / 128.0

    def e(v):
        return v * s

    def caja(c):
        return [e(c[0]), e(c[1]), e(c[2]), e(c[3])]

    # 1. la esfera: radialGradient id="esfera" cx=38% cy=30% r=78%
    lienzo = _radial(lado2x, (e(128 * 0.38), e(128 * 0.30)), e(128 * 0.78),
                     [(0.0, PALETA["esfera_alta"]),
                      (0.55, PALETA["esfera_media"]),
                      (1.0, PALETA["esfera_baja"])])
    dib = ImageDraw.Draw(lienzo)

    # 2. el anillo (stroke #35d67f a 0.28 sobre el borde oscuro de la esfera)
    borde = rgb(PALETA["esfera_baja"])
    color_anillo = (rgb(ROJO_AVISO) if alarma
                    else mezclar(borde, rgb(PALETA["verde"]), 0.28))
    grosor = max(1, int(round(e(3 if alarma else 2))))
    dib.ellipse(caja((5, 5, 123, 123)), outline=color_anillo, width=grosor)

    # 3. los dos lobulos, con el degradado verde del SVG
    mascara_cerebro = Image.new("L", (lado2x, lado2x), 0)
    dc = ImageDraw.Draw(mascara_cerebro)
    for cx, cy, r in _LOBULO:
        for x in (cx, 128 - cx):
            dc.ellipse([e(x - r), e(cy - r), e(x + r), e(cy + r)], fill=255)
    verde = _lineal(lado2x, (e(128 * 0.20), 0.0), (e(128 * 0.80), e(128.0)),
                    [(0.0, PALETA["verde_claro"]),
                     (0.55, PALETA["verde"]),
                     (1.0, PALETA["verde_oscuro"])])
    lienzo.paste(verde, (0, 0), mascara_cerebro)

    # 4. surcos: #0b3f26 a 0.55 sobre el verde medio (ver `mezclar`)
    color_surco = mezclar(rgb(PALETA["verde"]), rgb(PALETA["surco"]), 0.55)
    ancho = max(1, int(round(e(2.6))))
    dib.line([e(64), e(31), e(64), e(95)], fill=color_surco, width=ancho)
    for c, ini, fin in _SURCOS:
        dib.arc(caja(c), ini, fin, fill=color_surco, width=ancho)
        dib.arc(caja(_espejo_caja(c)), 180 - fin, 180 - ini,
                fill=color_surco, width=ancho)

    # 5. el tallo
    dib.polygon([(e(60), e(97)), (e(68), e(97)), (e(68), e(104)),
                 (e(64), e(109)), (e(60), e(104))],
                fill=rgb(PALETA["tallo"]))

    # 6. la silueta: el disco de r=60 del SVG
    disco = Image.new("L", (lado2x, lado2x), 0)
    ImageDraw.Draw(disco).ellipse(caja((4, 4, 124, 124)), fill=255)
    return lienzo, disco


def _base(lado: int, alarma: bool):
    """El cerebrito ya reducido a `lado`, con la silueta UMBRALIZADA.

    Aqui pasan las dos cosas que evitan el halo (ver el encabezado): la
    reduccion con LANCZOS sobre un lienzo opaco, y el umbral 0/255 sobre la
    mascara. Memoizado por (lado, alarma) porque el latido pide seis
    fotogramas del mismo dibujo.
    """
    from PIL import Image
    clave = ("base", int(lado), bool(alarma))
    if clave not in _MEMO:
        lienzo, disco = _lienzo_2x(int(lado) * 2, alarma)
        pequeno = lienzo.resize((int(lado), int(lado)), Image.LANCZOS)
        silueta = disco.resize((int(lado), int(lado)), Image.LANCZOS)
        silueta = silueta.point(
            lambda v: 255 if v >= UMBRAL_SILUETA else 0)
        _MEMO[clave] = (pequeno, silueta)
    return _MEMO[clave]


def factor_latido(paso: int, pasos: int = PASOS_LATIDO) -> float:
    """El brillo del fotograma `paso`, entre LATIDO_MIN y LATIDO_MAX.

    Coseno y no rampa: una rampa lineal da un salto seco al volver al primer
    fotograma y el icono "parpadea"; el coseno cierra el ciclo con la misma
    pendiente con la que lo abre y se ve como una respiracion.
    """
    pasos = max(1, int(pasos))
    fase = (1.0 - math.cos(2.0 * math.pi * (int(paso) % pasos) / pasos)) / 2.0
    return LATIDO_MIN + (LATIDO_MAX - LATIDO_MIN) * fase


def pasos_de(estado: str) -> int:
    """Cuantos fotogramas tiene un estado. Solo 'grabando' late.

    Existe para que el cache no guarde seis copias identicas de los estados
    quietos, y para que el widget sepa cuando NO tiene que animar nada.
    """
    return PASOS_LATIDO if estado == "grabando" else 1


def componer(estado: str, lado: int, paso: int = 0):
    """La imagen RGB final: cerebrito sobre el color clave, borde duro."""
    from PIL import Image, ImageEnhance
    estado = estado if estado in AJUSTES else "apagado"
    base, silueta = _base(lado, alarma=(estado == "fallo"))
    saturacion, brillo = AJUSTES[estado]
    if estado == "grabando":
        brillo *= factor_latido(paso)
    img = ImageEnhance.Color(base).enhance(saturacion)
    img = ImageEnhance.Brightness(img).enhance(brillo)
    fuera = Image.new("RGB", img.size, rgb(COLOR_CLAVE))
    fuera.paste(img, (0, 0), silueta)
    return fuera


# ── Cache en disco ───────────────────────────────────────────────────────────

def dir_cache() -> Path:
    d = alm.raiz() / DIR_ICONOS
    d.mkdir(parents=True, exist_ok=True)
    return d


def ruta_cache(estado: str, lado: int, paso: int = 0) -> Path:
    """El PNG de ese (estado, tamanio, fotograma). La VERSION va en el nombre.

    Con la version dentro, un cambio del dibujo NO deja iconos viejos
    mandando: el fichero nuevo tiene otro nombre y el viejo simplemente deja
    de mirarse. Es preferible a comprobar fechas, que con un reloj mal puesto
    da la respuesta contraria.
    """
    if estado not in ESTADOS:
        estado = "apagado"
    paso = int(paso) % pasos_de(estado)
    return dir_cache() / ("cerebro_%s_%dpx_%d_v%d.png"
                          % (estado, int(lado), paso, VERSION))


def cache_valido(ruta: Path, lado: int) -> bool:
    """Si ese PNG existe y sirve para `lado`.

    NO basta con `ruta.exists()`. Un fichero de 0 bytes (el proceso murio a
    mitad del write) o truncado existe igual, y `tk.PhotoImage` sobre el
    revienta al arrancar el widget -- o sea, el fallo aparece en el sitio mas
    lejano al que lo causo. Aqui se abre de verdad y se miden las dimensiones.
    """
    try:
        if not ruta.is_file() or ruta.stat().st_size <= 0:
            return False
        from PIL import Image
        with Image.open(ruta) as img:
            img.load()
            return img.size == (int(lado), int(lado))
    except Exception as exc:
        # No es un except mudo: el cache invalido se REDIBUJA (es lo que
        # devuelve False) y ademas queda dicho por que, que es la diferencia
        # entre "no estaba" y "estaba roto".
        log.warning("clases.widget_icono: cache invalido en %s (%s: %s), "
                    "se redibuja", ruta, type(exc).__name__, exc)
        return False


def _publicar(img, ruta: Path) -> None:
    """Deja `img` en `ruta` de una sola vez.

    Temporal UNICO (`mkstemp`) + `os.replace`. Las dos cosas importan: el
    nombre unico es lo que impide que dos escritores concurrentes -- dos
    procesos, o el hilo de precalentado y el de Tk -- usen el mismo fichero
    intermedio; el replace es lo que hace que quien lea vea siempre el PNG
    viejo o el nuevo, nunca uno a medio escribir (un PNG truncado en el cache
    revienta `tk.PhotoImage` en el arranque siguiente).
    """
    ruta.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(ruta.parent), suffix=".png.tmp")
    os.close(fd)
    try:
        img.save(tmp, format="PNG")
        for intento in range(_REINTENTOS_REPLACE):
            try:
                os.replace(tmp, str(ruta))
                return
            except PermissionError:
                if intento == _REINTENTOS_REPLACE - 1:
                    raise
                time.sleep(_ESPERA_REPLACE)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError as exc:
            log.warning("clases.widget_icono: temporal huerfano %s (%s)",
                        tmp, exc)
        raise


def icono_png(estado: str, lado: int, paso: int = 0) -> Path:
    """La ruta del PNG de ese estado. Lo dibuja solo si hace falta.

    Es la unica puerta que usa el widget: pedir el mismo icono mil veces
    (el latido lo hace) cuesta un `stat` y nada mas.

    Todo va bajo `_LOCK_DIBUJO`: la comprobacion del cache y el dibujo tienen
    que ser una sola operacion o dos hilos deciden a la vez que falta y lo
    dibujan los dos (ver el comentario del lock).
    """
    ruta = ruta_cache(estado, lado, paso)
    with _LOCK_DIBUJO:
        if cache_valido(ruta, lado):
            return ruta
        img = componer(estado, int(lado), int(paso))
        chocan = colisiones_clave(img, _base(int(lado),
                                             alarma=(estado == "fallo"))[1])
        if chocan:
            # Alguien cambio la paleta a un magenta: esos pixeles serian
            # agujeros transparentes en mitad del cerebrito. Se dibuja igual
            # (un icono con un punto raro sirve mas que ningun icono) pero
            # queda dicho.
            log.warning("clases.widget_icono: %d pixeles del icono '%s' valen "
                        "el color clave %s y se veran transparentes; revisa "
                        "PALETA", chocan, estado, COLOR_CLAVE)
        _publicar(img, ruta)
        _DIBUJOS[0] += 1
        return ruta


def precalentar(lado: int) -> list:
    """Deja en disco los iconos de todos los estados. Devuelve las rutas.

    Lo llama el widget al arrancar, EN UN HILO: dibujar los diez PNG la
    primera vez cuesta decimas de segundo y hacerlo dentro del hilo de Tk se
    ve como un arranque congelado.
    """
    rutas = []
    for estado in ESTADOS:
        for paso in range(pasos_de(estado)):
            rutas.append(icono_png(estado, lado, paso))
    return rutas


if __name__ == "__main__":
    for r in precalentar(48):
        print(r)
    print("dibujados:", dibujos())
