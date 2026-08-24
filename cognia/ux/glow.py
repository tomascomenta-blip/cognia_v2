"""
cognia/ux/glow.py
=================
MOTOR de glow y barrido de los elementos del CLI (P3 del sistema de estilos
por elemento, 2026-08-24). Es el nucleo PURO: no importa cli.py, no abre
ninguna Live propia, no crea hilos permanentes.

CONTRATO
--------
1. Byte-identico por defecto. Un EstiloGlow sin glow (intensidad 0) y sin
   animacion se pinta como UN solo span con el token/estilo base: exactamente
   lo que el CLI imprime hoy. Todo lo de este modulo es opt-in por elemento.
2. Independiente del registro (aspecto.py, paso P1). El motor consume
   EstiloGlow (dataclass de aqui). Los ids ('prompt.etiqueta') se resuelven
   por INYECCION: P4+ pone `glow.RESOLVER = aspecto.estilo_glow` (callable
   (id, variante, estado) -> EstiloGlow) y `glow.VERSION = aspecto.version`
   (callable -> int; la memo caduca cuando sube). Sin RESOLVER, un id se pinta
   sin estilo y se AVISA por _aviso_degradado('glow', ...): nunca en silencio.
3. Un solo reloj (RELOJ) e inyectable: `RELOJ.ahora` se reemplaza en tests y
   todas las funciones aceptan `t=` o `cuadro=` explicitos -> frame
   determinista. Los consumidores VIVOS (LineaViva, BannerVivo, pulso del
   prompt) miden el tiempo desde que el elemento aparecio, no desde el import.
4. Degradacion en el orden D8 (capacidades()): COGNIA_ANIMACION=0 > config
   estilo_animacion=off > NO_COLOR > sin tty por fd > COGNIA_REMOTO=1 >
   SSH > consola Windows legacy > color_system None. Siempre queda un frame
   ESTATICO (frame_estatico) con el glow fijo; por niveles: truecolor mezcla
   hex; 256 la degrada rich/PT solos; 16 va a tres escalones (dim / normal /
   bold sobre el nombre ANSI); none = sin color, glow = negrita, sin animar.
5. Cero hilos permanentes: el redibujado lo hacen los drivers que YA existen
   (el console.status del renderer para LineaViva, una Live SOLO al arrancar
   para BannerVivo, y el pulso finito de app.invalidate() para el prompt,
   acotado a PULSO_MAX_S; nunca refresh_interval fijo: medido 17% de CPU
   sostenido, enmienda E3).
6. Toda animacion termina en frame_estatico (sin esto la ventana queda a
   mitad de recorrido: medido). Nada de este modulo lanza hacia el turno:
   la config invalida SI es ruidosa (EstiloGlow valida al construirse).

MEDIDO (scratchpad/estilos, esta maquina, Windows Terminal, 2026-08-24):
barrido 0,17 ms/frame con estilos cacheados; prompt por pulso de 2 s a 15 fps
= 32 renders y 7,8% de CPU durante el pulso, 0 renders despues; rich Live
con 3 lineas vivas a 15 fps = 2,3%. PT llama al callable del message ~10
veces por render: la memo por cuadro deja UN calculo por frame.
"""
from __future__ import annotations

import math
import os
import sys
import threading
import time
from dataclasses import dataclass, replace
from functools import lru_cache

from . import paleta
# rich es dependencia dura del CLI y LineaViva HEREDA de Text (ver su
# docstring): es el unico import de rich a nivel de modulo.
from rich.text import Text as _Text

# Cuadros por segundo del reloj de animacion (global.fps del fichero de
# estilo; P4 lo puede pisar). 12: bastante para que el barrido sea fluido,
# poco para que PT (9 ms por render) no pese.
FPS = 12
# velocidad 1..5 -> periodo del barrido en segundos (tabla 1.1 del diseno)
VELOCIDAD_PERIODO = {1: 3.0, 2: 2.0, 3: 1.5, 4: 1.0, 5: 0.6}
# Relleno del barrido (Codex shimmer.rs): la ventana ENTRA por la izquierda y
# SALE por la derecha en vez de aparecer de golpe.
RELLENO = 10
# k cuantizado a 32 niveles: 32 Styles por par de colores, cacheados.
NIVELES = 32
# La ventana del barrido nunca llega al 100% del glow: deja ver el tono base.
FUERZA_BARRIDO = 0.9
# Tope del pulso del prompt (D5): nunca CPU permanente.
PULSO_MAX_S = 3.0
# Desfase entre lineas del banner: el barrido baja en diagonal.
DESFASE_LINEA_S = 0.08

DIRECCIONES = ("derecha", "izquierda", "ida_vuelta")
TIPOS = ("barrido", "pulso")
CURVAS = ("campana", "triangulo", "meseta")
NIVELES_COLOR = ("truecolor", "256", "16", "none")

_SANGRIA = "  "

# Los 16 nombres de rich -> nombres de prompt_toolkit (tabla fija, 1.2).
_PT_ANSI = {
    "black": "ansiblack", "red": "ansired", "green": "ansigreen",
    "yellow": "ansiyellow", "blue": "ansiblue", "magenta": "ansimagenta",
    # el blanco normal de PT es 'ansigray' y el brillante 'ansiwhite';
    # 'ansibrightwhite' no existe (cazado en P5 con /tema alto_contraste)
    "cyan": "ansicyan", "white": "ansigray",
    "bright_black": "ansibrightblack", "bright_red": "ansibrightred",
    "bright_green": "ansibrightgreen", "bright_yellow": "ansibrightyellow",
    "bright_blue": "ansibrightblue", "bright_magenta": "ansibrightmagenta",
    "bright_cyan": "ansibrightcyan", "bright_white": "ansiwhite",
    "grey": "ansigray", "gray": "ansigray",
}

# ---------------------------------------------------------------------------
# Inyeccion del registro (P4+ los conecta; aqui solo se documenta el hueco)
# ---------------------------------------------------------------------------
# callable(id: str, variante: str | None, estado: str | None) -> EstiloGlow
RESOLVER = None
# callable() -> int: contador del registro; la memo caduca cuando cambia
VERSION = None
# callable() -> str: variante activa ('oscuro'/'claro'/'alto_contraste');
# sin inyeccion se mira COGNIA_THEME y cli._variante_actual() a call-time
VARIANTE = None
# callable() -> dict: la config persistida del CLI (clave 'estilo_animacion');
# sin inyeccion se mira sys.modules['cognia.cli']._load_config a call-time
LEER_CONFIG = None


# ---------------------------------------------------------------------------
# Tipos
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EstiloGlow:
    """Lo que el motor necesita saber de UN elemento, ya resuelto (colores en
    hex o nombre ANSI de rich, booleanos decididos). aspecto.estilo_resuelto
    (P1) produce esto; los tests lo construyen a mano.

    token: nombre del token del Theme de rich ('spinner', 'ok_cl') que pinta
    el elemento HOY. Con glow 0 y sin animacion el motor devuelve el token tal
    cual (byte-identico); solo cuando hay que mezclar colores usa `color`.
    color/fondo: '#rrggbb', nombre de rich ('green', 'grey74') o '' (terminal).
    glow_color: '' = derivado (color aclarado 60% hacia blanco en oscuro y
    alto_contraste, hacia negro en claro: un glow mas claro sobre fondo claro
    vuelve invisible el elemento).
    gradiente: (hex, hex) solo para banner.arte; None = paleta.gradiente_banner.
    La validacion es RUIDOSA: un valor fuera de rango lanza ValueError al
    construir (regla del repo: config invalida nunca se acepta en silencio)."""
    token: str = ""
    color: str = ""
    fondo: str = ""
    negrita: bool = False
    italica: bool = False
    subrayado: bool = False
    glow_color: str = ""
    glow_intensidad: int = 0
    anim_activa: bool = False
    anim_tipo: str = "barrido"
    anim_direccion: str = "derecha"
    anim_velocidad: int = 2
    anim_ancho: int = 5
    anim_curva: str = "campana"
    anim_repetir: int = 0
    anim_cada_s: float = 0.0
    anim_solo_al_llegar: bool = False
    gradiente: tuple | None = None

    def __post_init__(self):
        if not 0 <= int(self.glow_intensidad) <= 3:
            raise ValueError(f"glow_intensidad {self.glow_intensidad!r} fuera de 0..3")
        if self.anim_tipo not in TIPOS:
            raise ValueError(f"anim_tipo {self.anim_tipo!r}; validos: {', '.join(TIPOS)}")
        if self.anim_direccion not in DIRECCIONES:
            raise ValueError(f"anim_direccion {self.anim_direccion!r}; "
                             f"validos: {', '.join(DIRECCIONES)}")
        if self.anim_curva not in CURVAS:
            raise ValueError(f"anim_curva {self.anim_curva!r}; validos: {', '.join(CURVAS)}")
        if int(self.anim_velocidad) not in VELOCIDAD_PERIODO:
            raise ValueError(f"anim_velocidad {self.anim_velocidad!r} fuera de 1..5")
        if not 1 <= int(self.anim_ancho) <= 20:
            raise ValueError(f"anim_ancho {self.anim_ancho!r} fuera de 1..20")
        if int(self.anim_repetir) < 0:
            raise ValueError(f"anim_repetir {self.anim_repetir!r} negativo")
        if float(self.anim_cada_s) < 0:
            raise ValueError(f"anim_cada_s {self.anim_cada_s!r} negativo")
        for nombre in ("color", "fondo", "glow_color"):
            v = getattr(self, nombre)
            if v and _rgb(v) is None:
                raise ValueError(f"{nombre} {v!r} no es un color (hex #rrggbb o nombre de rich)")
        if self.gradiente is not None:
            g = tuple(self.gradiente)
            if len(g) != 2 or any(_rgb(c) is None for c in g):
                raise ValueError(f"gradiente {self.gradiente!r}: se esperan dos colores")
            object.__setattr__(self, "gradiente", g)

    @property
    def periodo_s(self) -> float:
        return VELOCIDAD_PERIODO[int(self.anim_velocidad)]

    @property
    def ciclo_s(self) -> float:
        """Un barrido completo: ida (o ida y vuelta) en segundos."""
        return self.periodo_s * (2.0 if self.anim_direccion == "ida_vuelta" else 1.0)

    @property
    def repeticiones(self) -> int:
        """0 = infinito mientras el elemento viva; solo_al_llegar = 1."""
        return 1 if self.anim_solo_al_llegar else int(self.anim_repetir)

    def duracion_s(self, tope_s: float = PULSO_MAX_S) -> float:
        """Cuanto tiene que correr un driver finito para que esta animacion
        termine sola (repetir*ciclo + pausas), acotado a `tope_s`. Con
        repetir=0 devuelve el tope: en el prompt nunca hay CPU permanente."""
        if not self.anim_activa:
            return 0.0
        n = self.repeticiones
        if n <= 0:
            return float(tope_s)
        total = n * self.ciclo_s + max(0, n - 1) * float(self.anim_cada_s)
        return float(min(tope_s, total))


@dataclass(frozen=True)
class Caps:
    """Que puede hacer la terminal: nivel de color y si se anima. `motivo`
    dice POR QUE no se anima (vacio si se anima): el editor lo muestra."""
    nivel: str
    animar: bool
    motivo: str = ""


class Reloj:
    """UNICO reloj de animacion del proceso. `ahora` es inyectable
    (glow.RELOJ.ahora = lambda: 3.25) y `t()` cuenta desde t0, asi que un
    test fija el instante sin tocar time. `cuadro(fps)` es la clave de memo
    por frame: dos llamadas dentro del mismo cuadro comparten el calculo."""

    def __init__(self, ahora=time.monotonic):
        self.ahora = ahora
        self.t0 = ahora()

    def t(self) -> float:
        return self.ahora() - self.t0

    def cuadro(self, fps: int | None = None) -> int:
        return int(self.t() * (fps or FPS))

    def reiniciar(self) -> None:
        self.t0 = self.ahora()

    def fijar(self, t: float) -> None:
        """Tests: congela el reloj en t segundos desde t0."""
        t0 = self.t0
        self.ahora = lambda: t0 + float(t)


RELOJ = Reloj()


# ---------------------------------------------------------------------------
# Degradacion visible (canal unico del repo)
# ---------------------------------------------------------------------------
_AVISOS_STDERR: set = set()


def _avisar(motivo: str) -> None:
    """Degradacion VISIBLE por _aviso_degradado('glow', motivo) del CLI, que
    de-duplica por turno; sin cli cargado (tests, scripts) sale por stderr una
    vez por motivo. Jamas se calla (regla del repo)."""
    try:
        _cli = sys.modules.get("cognia.cli")
        if _cli is not None:
            _cli._aviso_degradado("glow", motivo)
            return
    except Exception:
        pass
    if motivo in _AVISOS_STDERR:
        return
    _AVISOS_STDERR.add(motivo)
    try:
        print(f"{_SANGRIA}degradado — glow: {motivo}", file=sys.stderr)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Colores
# ---------------------------------------------------------------------------

@lru_cache(maxsize=512)
def _rgb(color: str):
    """(r, g, b) de un hex o nombre de rich; None si no es color / terminal."""
    if not color or color == "terminal":
        return None
    try:
        from rich.color import Color
        t = Color.parse(str(color)).get_truecolor()
        return (t.red, t.green, t.blue)
    except Exception:
        return None


def _hex(rgb) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(c)))) for c in rgb)


def _mezcla(a, b, k: float):
    k = max(0.0, min(1.0, k))
    return tuple(a[i] + (b[i] - a[i]) * k for i in range(3))


@lru_cache(maxsize=256)
def _nombre16(color: str) -> str:
    """El nombre ANSI (de los 16) mas cercano a un color: nivel '16'."""
    try:
        from rich.color import Color, ColorSystem, ANSI_COLOR_NAMES
        c = Color.parse(color)
        if c.is_system_defined and c.number is not None and c.number < 16:
            return ANSI_COLOR_NAMES[c.number]
        n = c.downgrade(ColorSystem.STANDARD).number
        return ANSI_COLOR_NAMES[int(n or 0)]
    except Exception:
        return "white"


def _variante(variante: str | None) -> str:
    if variante:
        return variante
    try:
        if VARIANTE is not None:
            return str(VARIANTE())
    except Exception as exc:
        _avisar(f"VARIANTE inyectada fallo ({type(exc).__name__}: {exc}); 'oscuro'")
    v = (os.environ.get("COGNIA_THEME") or "").strip()
    if v in paleta.ORDEN_VARIANTES:
        return v
    try:
        _cli = sys.modules.get("cognia.cli")
        if _cli is not None:
            return str(_cli._variante_actual())
    except Exception:
        pass
    return "oscuro"


def _fondo(variante: str):
    return _rgb(paleta.FONDO_VARIANTE.get(variante, paleta.FONDO_VARIANTE["oscuro"]))


def color_glow(estilo: EstiloGlow, variante: str | None = None):
    """(r, g, b) del glow: el declarado, o el color base aclarado 60% (hacia
    blanco en oscuro/alto_contraste, hacia NEGRO en claro). None si el
    elemento no tiene color propio (hereda el de la terminal: no hay nada que
    mezclar; el glow queda en negrita)."""
    if estilo.glow_color:
        return _rgb(estilo.glow_color)
    base = _rgb(estilo.color)
    if base is None:
        return None
    hacia = (0, 0, 0) if _variante(variante) == "claro" else (255, 255, 255)
    return _mezcla(base, hacia, 0.6)


# ---------------------------------------------------------------------------
# Capacidades (orden D8)
# ---------------------------------------------------------------------------
_CAPS = {"clave": None, "caps": None, "rich_t": 0.0, "rich": None}
_CAPS_FORZADAS = None


def forzar_capacidades(caps: Caps | None) -> None:
    """Tests y demos: fija el resultado de capacidades() (None = detectar)."""
    global _CAPS_FORZADAS
    _CAPS_FORZADAS = caps
    _CAPS["clave"] = None


def _config_animacion() -> str:
    """Valor de la clave 'estilo_animacion' de la config del CLI ('on' si no
    hay config). LEER_CONFIG inyectable; sin ella, cli._load_config a
    call-time via sys.modules (patron spinner_vivo.config)."""
    try:
        if LEER_CONFIG is not None:
            cfg = LEER_CONFIG()
        else:
            _cli = sys.modules.get("cognia.cli")
            cfg = _cli._load_config() if _cli is not None else {}
        return str((cfg or {}).get("estilo_animacion", "on")).strip().lower()
    except Exception as exc:
        _avisar(f"config estilo_animacion ilegible ({type(exc).__name__}: {exc}); 'on'")
        return "on"


def _deteccion_rich() -> tuple:
    """(color_system, legacy_windows) de una Console de rich, cacheado 1 s
    (crear una Console no es gratis y capacidades() se llama por frame)."""
    ahora = time.monotonic()
    if _CAPS["rich"] is None or ahora - _CAPS["rich_t"] > 1.0:
        try:
            from rich.console import Console
            c = Console()
            _CAPS["rich"] = (c.color_system, bool(c.legacy_windows))
        except Exception:
            _CAPS["rich"] = (None, False)
        _CAPS["rich_t"] = ahora
    return _CAPS["rich"]


def _es_tty() -> bool:
    try:
        return bool(sys.stdout.isatty())
    except Exception:
        return False


def capacidades() -> Caps:
    """Nivel de color y permiso de animar, en el orden D8 del diseno. Se
    cachea por (env relevante, tty, deteccion de rich a 1 s): cambiar una
    variable con /estilo animacion se ve en el siguiente frame.

    COGNIA_ANIMACION=1 FUERZA la animacion sobre tty/remoto/SSH/legacy (para
    capturas y demos; como COGNIA_SPINNER=1), pero no sobre NO_COLOR ni sobre
    una consola sin color: sin color no hay nada que barrer."""
    if _CAPS_FORZADAS is not None:
        return _CAPS_FORZADAS
    env = os.environ
    cs, legacy = _deteccion_rich()
    cfg = _config_animacion()
    clave = (env.get("COGNIA_ANIMACION"), env.get("NO_COLOR"), env.get("COGNIA_REMOTO"),
             env.get("SSH_TTY"), env.get("SSH_CONNECTION"), env.get("COLORTERM"),
             env.get("WT_SESSION"), env.get("TERM_PROGRAM"), _es_tty(), cs, legacy, cfg)
    if clave == _CAPS["clave"] and _CAPS["caps"] is not None:
        return _CAPS["caps"]
    truecolor = (str(env.get("COLORTERM", "")).lower() in ("truecolor", "24bit")
                 or bool(env.get("WT_SESSION"))
                 or env.get("TERM_PROGRAM") in ("vscode", "iTerm.app", "WezTerm")
                 or cs == "truecolor")
    if cs is None:
        nivel = "none"
    elif truecolor:
        nivel = "truecolor"
    elif cs == "256":
        nivel = "256"
    else:
        nivel = "16"
    forzada = str(env.get("COGNIA_ANIMACION", "")).strip()
    animar, motivo = True, ""
    if forzada == "0":
        animar, motivo = False, "COGNIA_ANIMACION=0"
    elif forzada != "1" and cfg in ("off", "0", "false", "no"):
        animar, motivo = False, "config estilo_animacion=off (/estilo animacion on)"
    elif env.get("NO_COLOR"):
        nivel, animar, motivo = "none", False, "NO_COLOR"
    elif nivel == "none":
        animar, motivo = False, "sin color (rich color_system None)"
    elif forzada == "1":
        pass
    elif not _es_tty():
        animar, motivo = False, "sin tty (stdout no es una terminal)"
    elif str(env.get("COGNIA_REMOTO", "")).strip() == "1":
        animar, motivo = False, "COGNIA_REMOTO=1"
    elif env.get("SSH_TTY") or env.get("SSH_CONNECTION"):
        animar, motivo = False, "sesion SSH"
    elif legacy:
        animar, motivo = False, "consola Windows legacy (sin VT)"
    caps = Caps(nivel=nivel, animar=animar, motivo=motivo)
    _CAPS["clave"], _CAPS["caps"] = clave, caps
    return caps


# ---------------------------------------------------------------------------
# Resolucion id -> EstiloGlow
# ---------------------------------------------------------------------------
_NEUTRO = EstiloGlow()


def _resolver(id_o_estilo, variante: str | None, estado: str | None) -> EstiloGlow:
    if isinstance(id_o_estilo, EstiloGlow):
        return id_o_estilo
    if RESOLVER is None:
        _avisar(f"sin registro de aspecto: '{id_o_estilo}' se pinta sin estilo "
                "(falta conectar glow.RESOLVER)")
        return _NEUTRO
    try:
        e = RESOLVER(str(id_o_estilo), variante, estado)
    except Exception as exc:
        _avisar(f"'{id_o_estilo}': {type(exc).__name__}: {exc}; se pinta sin estilo")
        return _NEUTRO
    if not isinstance(e, EstiloGlow):
        _avisar(f"'{id_o_estilo}': RESOLVER devolvio {type(e).__name__}, no EstiloGlow")
        return _NEUTRO
    return e


def _version() -> int:
    try:
        return int(VERSION()) if VERSION is not None else 0
    except Exception as exc:
        _avisar(f"VERSION inyectada fallo ({type(exc).__name__}: {exc})")
        return 0


# ---------------------------------------------------------------------------
# Styles cacheados
# ---------------------------------------------------------------------------

@lru_cache(maxsize=4096)
def _style(color, fondo: str, bold: bool, italic: bool, underline: bool, dim: bool):
    from rich.style import Style
    return Style(color=color or None, bgcolor=fondo or None,
                 bold=bold or None, italic=italic or None,
                 underline=underline or None, dim=dim or None)


@lru_cache(maxsize=4096)
def _style_mezcla(base, glow, nivel32: int, fondo: str, bold: bool,
                  italic: bool, underline: bool):
    """Style del caracter con k = nivel32/(NIVELES-1) de mezcla base->glow.
    Cacheado por tupla: rich guarda el ANSI dentro del Style (Style._ansi),
    asi que un frame de 45 caracteres son 45 lookups y cero formateo."""
    k = nivel32 / (NIVELES - 1)
    return _style(_hex(_mezcla(base, glow, k)), fondo, bold, italic, underline, False)


@lru_cache(maxsize=64)
def _perfil(semiancho: int, curva: str) -> tuple:
    """Curva de intensidad muestreada por distancia entera 0..semiancho."""
    s = float(max(1, semiancho))
    out = []
    for d in range(int(s) + 1):
        if curva == "triangulo":
            k = 1.0 - d / s
        elif curva == "meseta":
            k = 1.0 if d <= s / 2 else 0.5 * (1 + math.cos(math.pi * (d - s / 2) / (s / 2)))
        else:
            k = 0.5 * (1 + math.cos(math.pi * d / s))
        out.append(max(0.0, min(1.0, k)))
    return tuple(out)


def _estilo_plano(estilo: EstiloGlow, nivel: str = "truecolor"):
    """El estilo de UNA pieza sin trabajo por caracter: el token del Theme si
    lo hay y no hace falta mezclar (byte-identico), si no un Style. No mira
    la terminal: rich y prompt_toolkit degradan un color plano por su cuenta
    (256/16/NO_COLOR); solo con nivel 'none' explicito se quitan los colores
    (glow = negrita)."""
    bold = bool(estilo.negrita) or int(estilo.glow_intensidad) >= 2
    if estilo.token and not estilo.color and not estilo.fondo:
        if bold == bool(estilo.negrita) and not estilo.italica and not estilo.subrayado:
            return estilo.token
        from rich.style import Style
        if " " in estilo.token:
            return Style.parse(estilo.token)
        return _style(None, "", bold, estilo.italica, estilo.subrayado, False)
    if nivel == "none":
        return _style(None, "", bold, estilo.italica, estilo.subrayado, False)
    return _style(estilo.color or None, estilo.fondo, bold, estilo.italica,
                  estilo.subrayado, False)


# ---------------------------------------------------------------------------
# El frame: lista de tramos (Style|str, texto)
# ---------------------------------------------------------------------------

def _fase(estilo: EstiloGlow, t: float):
    """('estatico'|'barrido'|'pulso', fase 0..1) para el instante t (segundos
    desde que el elemento aparecio). repetir=N -> estatico tras N ciclos;
    cada_s -> estatico en la pausa entre ciclos; izquierda invierte;
    ida_vuelta es un triangulo sobre 2*periodo."""
    if not estilo.anim_activa or t < 0:
        return "estatico", 0.0
    ciclo = estilo.ciclo_s
    pausa = float(estilo.anim_cada_s)
    n = estilo.repeticiones
    if n > 0 and t >= n * ciclo + max(0, n - 1) * pausa:
        return "estatico", 0.0
    local = t % (ciclo + pausa)
    if local >= ciclo:
        return "estatico", 0.0
    f = local / ciclo
    if estilo.anim_tipo == "pulso":
        return "pulso", f
    if estilo.anim_direccion == "ida_vuelta":
        f = 2 * f if f < 0.5 else 2 - 2 * f
    elif estilo.anim_direccion == "izquierda":
        f = 1.0 - f
    return "barrido", f


def _recortar(texto: str, ancho) -> str:
    if not ancho:
        return texto
    try:
        from rich.cells import cell_len
        while texto and cell_len(texto) > int(ancho):
            texto = texto[:-1]
    except Exception:
        texto = texto[:int(ancho)]
    return texto


def _tramos(estilo: EstiloGlow, texto: str, t, nivel: str, variante: str) -> list:
    """El frame como tramos [(estilo, trozo)] con tramos vecinos iguales ya
    fundidos. t=None -> sin animacion (frame estatico)."""
    if not texto:
        return []
    modo, f = ("estatico", 0.0) if t is None else _fase(estilo, t)
    intensidad = int(estilo.glow_intensidad)
    if nivel == "none" or (intensidad == 0 and modo == "estatico"):
        return [(_estilo_plano(estilo, nivel), texto)]
    base = _rgb(estilo.color)
    glow = color_glow(estilo, variante)
    n = len(texto)
    # k por caracter: campana estatica (glow) combinada en 'pantalla' con la
    # ventana del barrido o el pulso uniforme
    ks = [0.0] * n
    if intensidad > 0:
        amp = intensidad / 3.0
        for i in range(n):
            x = (i / max(1, n - 1)) * 2 - 1
            ks[i] = amp * 0.5 * (1 + math.cos(math.pi * x))
    bold_anim = False
    if modo == "pulso":
        k = 0.5 * (1 + math.sin(2 * math.pi * f - math.pi / 2)) * FUERZA_BARRIDO
        ks = [1 - (1 - a) * (1 - k) for a in ks]
        bold_anim = True
    elif modo == "barrido":
        semi = int(estilo.anim_ancho)
        perfil = _perfil(semi, estilo.anim_curva)
        pos = f * (n + 2 * RELLENO)
        # el centro de la celda i es i+RELLENO+0.5: asi 'izquierda' es el
        # espejo EXACTO de 'derecha' (celda i <-> celda n-1-i)
        for i in range(n):
            d = abs((i + RELLENO + 0.5) - pos)
            if d <= semi:
                j = int(d)
                k = perfil[j]
                if j + 1 <= semi:
                    k += (perfil[j + 1] - k) * (d - j)     # interpolado: sin escalones
                ks[i] = 1 - (1 - ks[i]) * (1 - k * FUERZA_BARRIDO)
        bold_anim = True
    bold = bool(estilo.negrita) or intensidad >= 2 or bold_anim
    fondo = estilo.fondo if nivel != "16" else ""
    tramos = []
    if base is None or glow is None or nivel == "16":
        # sin color mezclable: tres escalones sobre el nombre base (nivel 16)
        # o sobre el estilo heredado (elemento sin color propio)
        nombre = _nombre16(estilo.color) if (nivel == "16" and base is not None) \
            else (estilo.color or None)
        for i, ch in enumerate(texto):
            k = ks[i]
            if k >= 0.6:
                st = _style(nombre, fondo, True, estilo.italica, estilo.subrayado, False)
            elif k >= 0.2 or modo == "estatico":
                st = _style(nombre, fondo, bold, estilo.italica, estilo.subrayado, False)
            else:
                st = _style(nombre, fondo, bold and not bold_anim, estilo.italica,
                            estilo.subrayado, bool(bold_anim))
            _fundir(tramos, st, ch)
        return tramos
    for i, ch in enumerate(texto):
        st = _style_mezcla(base, glow, int(round(ks[i] * (NIVELES - 1))), fondo,
                           bold, estilo.italica, estilo.subrayado)
        _fundir(tramos, st, ch)
    return tramos


def _fundir(tramos: list, st, ch: str) -> None:
    if tramos and tramos[-1][0] is st:
        tramos[-1] = (st, tramos[-1][1] + ch)
    else:
        tramos.append((st, ch))


# ---------------------------------------------------------------------------
# Conversion a rich.Text y a fragmentos de prompt_toolkit
# ---------------------------------------------------------------------------

def _a_text(tramos: list):
    from rich.text import Text
    out = Text()
    for st, trozo in tramos:
        out.append(trozo, st)
    return out


@lru_cache(maxsize=4096)
def _pt_de_style(st, variante: str) -> str:
    """Style de rich -> style string de prompt_toolkit ('fg:#7ee62a bold').
    Los 16 nombres van por tabla; greyNN/orange4 a hex; 'dim' no existe en
    PT y se traduce a mezcla 45% hacia el fondo de la variante (1.2)."""
    if isinstance(st, str):
        return st
    partes = []
    color = st.color
    if color is not None:
        if color.triplet is not None:
            rgb = (color.triplet.red, color.triplet.green, color.triplet.blue)
            if st.dim:
                rgb = _mezcla(rgb, _fondo(variante), 0.45)
            partes.append("fg:" + _hex(rgb))
        elif color.name in _PT_ANSI:
            partes.append("fg:" + _PT_ANSI[color.name])
        elif color.is_default:
            pass
        else:
            try:
                t = color.get_truecolor()
                partes.append("fg:" + _hex((t.red, t.green, t.blue)))
            except Exception:
                pass
    bg = st.bgcolor
    if bg is not None and not bg.is_default:
        if bg.triplet is not None:
            partes.append("bg:" + _hex((bg.triplet.red, bg.triplet.green, bg.triplet.blue)))
        elif bg.name in _PT_ANSI:
            partes.append("bg:" + _PT_ANSI[bg.name])
        else:
            try:
                t = bg.get_truecolor()
                partes.append("bg:" + _hex((t.red, t.green, t.blue)))
            except Exception:
                pass
    if st.bold:
        partes.append("bold")
    if st.italic:
        partes.append("italic")
    if st.underline:
        partes.append("underline")
    return " ".join(partes)


def _a_pt(tramos: list, variante: str) -> list:
    return [(_pt_de_style(st, variante) if not isinstance(st, str) else f"class:{st}",
             trozo) for st, trozo in tramos]


# ---------------------------------------------------------------------------
# Memo por cuadro
# ---------------------------------------------------------------------------
_MEMO: dict = {}
_MEMO_MAX = 512
# contador de frames CALCULADOS (no servidos de memo): lo miran los tests
CALCULOS = 0


def vaciar_memo() -> None:
    _MEMO.clear()


def _frame(id_o_estilo, texto: str, t, cuadro, variante, estado, fps, ancho, salida: str):
    """Un frame memoizado por (id/estilo, texto, cuadro|t, version, variante,
    estado, nivel, fps, salida). t explicito -> determinista; cuadro explicito
    -> t = cuadro/fps; ninguno -> el cuadro actual del RELOJ."""
    global CALCULOS
    fps = int(fps or FPS)
    variante = _variante(variante)
    caps = capacidades()
    estilo = _resolver(id_o_estilo, variante, estado)
    texto = _recortar(texto, ancho)
    animar = estilo.anim_activa and caps.animar and caps.nivel != "none"
    if not animar:
        clave_t = None
    elif t is not None:
        clave_t = float(t)
    else:
        if cuadro is None:
            cuadro = RELOJ.cuadro(fps)
        clave_t = int(cuadro)
        t = cuadro / fps
    clave = (id_o_estilo, texto, clave_t, _version(), variante, estado, caps.nivel, salida)
    hit = _MEMO.get(clave)
    if hit is not None:
        return hit
    CALCULOS += 1
    tramos = _tramos(estilo, texto, t if animar else None, caps.nivel, variante)
    out = _a_text(tramos) if salida == "rich" else _a_pt(tramos, variante)
    if len(_MEMO) >= _MEMO_MAX:
        _MEMO.clear()
    _MEMO[clave] = out
    return out


# ---------------------------------------------------------------------------
# API publica
# ---------------------------------------------------------------------------

def estilizar(id_o_estilo, texto: str, *, t=None, cuadro=None, variante=None,
              estado=None, fps=None, ancho=None):
    """rich.Text del elemento en el instante t (o cuadro). Sin t ni cuadro:
    el cuadro actual del RELOJ. Sin animacion posible (capacidades, elemento
    sin anim) devuelve el frame estatico. Se devuelve una COPIA: el memo no
    se ensucia si el consumidor le hace append."""
    return _frame(id_o_estilo, texto, t, cuadro, variante, estado, fps, ancho, "rich").copy()


def estilizar_pt(id_o_estilo, texto: str, *, t=None, cuadro=None, variante=None,
                 estado=None, fps=None, ancho=None) -> list:
    """Fragmentos de prompt_toolkit [('fg:#hex bold', trozo), ...] del mismo
    frame. Sin t ni cuadro: el instante del PULSO del prompt si esta vivo
    (animando()), y el frame estatico si no: asi _mensaje_prompt lo llama
    siempre igual y el pulso decide."""
    if t is None and cuadro is None:
        if not animando():
            return frame_estatico_pt(id_o_estilo, texto, variante=variante, estado=estado,
                                     ancho=ancho)
        t = t_pulso()
        cuadro = int(t * int(fps or FPS))
        t = None
    return list(_frame(id_o_estilo, texto, t, cuadro, variante, estado, fps, ancho, "pt"))


def frame_estatico(id_o_estilo, texto: str, *, variante=None, estado=None, ancho=None):
    """El ULTIMO frame: glow fijo (campana) sin barrido. Es lo que queda en el
    scrollback y lo que se pinta sin tty."""
    estilo = _resolver(id_o_estilo, _variante(variante), estado)
    quieto = replace(estilo, anim_activa=False)
    return _frame(quieto, texto, None, None, variante, estado, None, ancho, "rich").copy()


def frame_estatico_pt(id_o_estilo, texto: str, *, variante=None, estado=None, ancho=None) -> list:
    estilo = _resolver(id_o_estilo, _variante(variante), estado)
    quieto = replace(estilo, anim_activa=False)
    return list(_frame(quieto, texto, None, None, variante, estado, None, ancho, "pt"))


def estilo_rich(id_o_estilo, variante=None, estado=None):
    """Estilo de rich para una LINEA COMITEADA (sin glow por caracter): el
    token del Theme si el elemento no tiene override (byte-identico), un
    Style si lo tiene. Acepta str|Style todo lo que acepta rich."""
    estilo = _resolver(id_o_estilo, _variante(variante), estado)
    return _estilo_plano(estilo)


def clase_pt(id_o_estilo, variante=None, estado=None) -> str:
    """Style string de prompt_toolkit del elemento ('fg:#7ee62a bold'), para
    el dict de PTStyle.from_dict. Un token sin color propio da '' (hereda)."""
    variante = _variante(variante)
    estilo = _resolver(id_o_estilo, variante, estado)
    plano = _estilo_plano(estilo)
    if isinstance(plano, str):
        from rich.style import Style
        try:
            plano = Style.parse(plano) if " " in plano else Style(
                bold=(estilo.negrita or estilo.glow_intensidad >= 2) or None,
                italic=estilo.italica or None, underline=estilo.subrayado or None)
        except Exception:
            return ""
    return _pt_de_style(plano, variante)


def gradiente_lineas(id_o_estilo, lineas, *, t=None, cuadro=None, variante=None,
                     estado=None, fps=None, ancho=None) -> list:
    """Banner: un tono por linea (el gradiente del elemento o
    paleta.gradiente_banner de la variante, como hoy) y glow/barrido por
    columna encima, con DESFASE_LINEA_S entre lineas (baja en diagonal).
    Sin glow ni animacion devuelve exactamente Text(linea, style=tono)."""
    lineas = list(lineas)
    variante = _variante(variante)
    estilo = _resolver(id_o_estilo, variante, estado)
    tonos = _tonos(estilo, len(lineas), variante)
    out = []
    for i, (linea, tono) in enumerate(zip(lineas, tonos)):
        e = replace(estilo, token="", color=tono)
        ti, ci = t, cuadro
        if estilo.anim_activa and t is None and ci is None:
            ci = RELOJ.cuadro(fps) - int(i * DESFASE_LINEA_S * int(fps or FPS))
        elif estilo.anim_activa and t is not None:
            ti = t - i * DESFASE_LINEA_S
        out.append(estilizar(e, linea, t=ti, cuadro=ci, variante=variante,
                             estado=estado, fps=fps, ancho=ancho))
    return out


def _tonos(estilo: EstiloGlow, n: int, variante: str) -> list:
    if estilo.gradiente is None:
        return list(paleta.gradiente_banner(n, variante))
    a, b = _rgb(estilo.gradiente[0]), _rgb(estilo.gradiente[1])
    if n <= 1:
        return [_hex(a)]
    return [_hex(_mezcla(a, b, i / (n - 1))) for i in range(n)]


def fila_halo(id_o_estilo, texto: str, *, variante=None, estado=None, sombra: str = "░"):
    """Intensidad 3: la fila de sombra que va DEBAJO del texto (solo donde hay
    fila libre: banner.arte y prompt.marco; el consumidor decide). Text vacio
    si el elemento no llega a 3 o no tiene color mezclable."""
    from rich.text import Text
    variante = _variante(variante)
    estilo = _resolver(id_o_estilo, variante, estado)
    base, glow = _rgb(estilo.color), color_glow(estilo, variante)
    out = Text()
    if int(estilo.glow_intensidad) < 3 or base is None or glow is None \
            or capacidades().nivel in ("none", "16"):
        return out
    n = len(texto)
    for i in range(n):
        x = (i / max(1, n - 1)) * 2 - 1
        k = 0.35 * (1 + math.cos(math.pi * x))
        out.append(sombra, _style(_hex(_mezcla(base, glow, k)), "", False, False, False, True))
    return out


# ---------------------------------------------------------------------------
# LineaViva: el renderable que va DENTRO del console.status del renderer
# ---------------------------------------------------------------------------

class LineaViva(_Text):
    """La linea del spinner, viva. Es un rich.Text (no un renderable
    cualquiera) A PROPOSITO: rich.Spinner.render hace
    Text.assemble(frame, ' ', texto) cuando el status es un Text y cae a un
    Table.grid (otro layout, otros bytes) con cualquier otro renderable. Como
    Text.append lee primero len(texto), __len__ refresca el frame: cada
    refresh de la Live del status recoge el cuadro actual sin update() ni
    hilo propio. Con animar=False el contenido es EXACTAMENTE
    Text.from_markup('[token]marca texto[/token]'), lo que el renderer pinta
    hoy. set(texto) lo llama el ticker de 1 s del renderer (thread-safe)."""

    def __init__(self, texto: str, id_o_estilo, *, marca: str = "·", token: str = "spinner",
                 animar=None, variante=None, ancho=None, fps=None, reloj=None):
        super().__init__()
        self._lv_texto = str(texto)
        self._lv_id = id_o_estilo
        self._lv_marca = marca
        self._lv_token = token
        self._lv_variante = variante
        self._lv_ancho = ancho
        self._lv_fps = int(fps or FPS)
        self._lv_reloj = reloj or RELOJ
        self._lv_t0 = self._lv_reloj.t()
        self._lv_lock = threading.RLock()
        self._lv_cuadro = None
        self._lv_animar = animar
        self.frames = 0
        self._refrescar(forzar=True)

    @property
    def animar(self) -> bool:
        if self._lv_animar is not None:
            return bool(self._lv_animar)
        try:
            estilo = _resolver(self._lv_id, _variante(self._lv_variante), None)
            return bool(estilo.anim_activa and capacidades().animar)
        except Exception:
            return False

    @property
    def fps(self) -> int:
        """refresh_per_second para el console.status cuando anima."""
        return self._lv_fps

    def set(self, texto: str) -> None:
        with self._lv_lock:
            self._lv_texto = str(texto)
            self._lv_cuadro = None

    def _cargar(self, otro) -> None:
        self._text[:] = [otro.plain]
        self._spans[:] = list(otro._spans)
        self._length = len(otro)

    def _refrescar(self, forzar: bool = False) -> None:
        with self._lv_lock:
            texto = self._lv_texto
            if not self.animar:
                if forzar or self._lv_cuadro != -1:
                    self._lv_cuadro = -1
                    self._cargar(_Text.from_markup(
                        f"[{self._lv_token}]{self._lv_marca} {texto}[/{self._lv_token}]"))
                    self.frames += 1
                return
            cuadro = int((self._lv_reloj.t() - self._lv_t0) * self._lv_fps)
            if not forzar and cuadro == self._lv_cuadro:
                return
            self._lv_cuadro = cuadro
            try:
                frame = estilizar(self._lv_id, f"{self._lv_marca} {texto}", cuadro=cuadro,
                                  variante=self._lv_variante, fps=self._lv_fps,
                                  ancho=self._lv_ancho)
            except Exception as exc:
                _avisar(f"linea viva: {type(exc).__name__}: {exc}; frame estatico")
                self._lv_animar = False
                frame = _Text.from_markup(
                    f"[{self._lv_token}]{self._lv_marca} {texto}[/{self._lv_token}]")
            self._cargar(frame)
            self.frames += 1

    def __len__(self) -> int:
        self._refrescar()
        return self._length

    @property
    def plain(self) -> str:
        self._refrescar()
        return _Text.plain.fget(self)

    @plain.setter
    def plain(self, valor: str) -> None:
        _Text.plain.fset(self, valor)

    def frame_final(self):
        """El frame estatico (glow fijo) para dejar al parar el status."""
        return frame_estatico(self._lv_id, f"{self._lv_marca} {self._lv_texto}",
                              variante=self._lv_variante, ancho=self._lv_ancho)


# ---------------------------------------------------------------------------
# BannerVivo: Live del arranque (antes de la PromptSession)
# ---------------------------------------------------------------------------

class BannerVivo:
    """Renderable dinamico para la UNICA Live del arranque: cada refresh
    recalcula el frame con el RELOJ (sin ticker). `envolver` (opcional)
    recibe el Text de las lineas y devuelve el renderable final (el Panel del
    banner, P7). mostrar(console) aplica la enmienda E7: si console.height <
    filas + 2 no abre Live y pinta el frame estatico; con Live usa
    vertical_overflow='visible' y termina SIEMPRE en frame_final()."""

    def __init__(self, lineas, id_o_estilo, *, variante=None, fps=None, envolver=None,
                 reloj=None, ancho=None):
        self.lineas = list(lineas)
        self.id = id_o_estilo
        self.variante = variante
        self.fps = int(fps or FPS)
        self.envolver = envolver
        self.reloj = reloj or RELOJ
        self.ancho = ancho
        self.t0 = self.reloj.t()
        self.frames = 0
        self._stop = threading.Event()

    @property
    def filas(self) -> int:
        return len(self.lineas)

    def _estilo(self) -> EstiloGlow:
        return _resolver(self.id, _variante(self.variante), None)

    def duracion_s(self, tope_s: float = PULSO_MAX_S) -> float:
        return self._estilo().duracion_s(tope_s)

    def frame(self, t=None):
        from rich.text import Text
        if t is None:
            t = self.reloj.t() - self.t0
        textos = gradiente_lineas(self.id, self.lineas, t=t, variante=self.variante,
                                  fps=self.fps, ancho=self.ancho)
        cuerpo = Text("\n").join(textos)
        return self.envolver(cuerpo) if self.envolver else cuerpo

    def frame_final(self):
        from rich.text import Text
        estilo = replace(self._estilo(), anim_activa=False)
        textos = gradiente_lineas(estilo, self.lineas, variante=self.variante, ancho=self.ancho)
        cuerpo = Text("\n").join(textos)
        return self.envolver(cuerpo) if self.envolver else cuerpo

    def __rich_console__(self, console, options):
        self.frames += 1
        yield self.frame()

    def parar(self) -> None:
        """Cortar la animacion (una tecla, por ejemplo): mostrar() termina."""
        self._stop.set()

    def mostrar(self, console, *, tope_s: float = PULSO_MAX_S) -> bool:
        """Pinta el banner: animado con Live si se puede (True) o estatico
        con console.print (False). Nunca deja la ventana a medio recorrido."""
        estilo = self._estilo()
        caps = capacidades()
        dur = estilo.duracion_s(tope_s)
        try:
            alto = int(console.size.height)
        except Exception:
            alto = 0
        if not (estilo.anim_activa and caps.animar) or dur <= 0:
            console.print(self.frame_final())
            return False
        if alto and alto < self.filas + 2:
            _avisar(f"banner: terminal de {alto} filas para {self.filas} lineas; sin animacion")
            console.print(self.frame_final())
            return False
        try:
            from rich.live import Live
            self.t0 = self.reloj.t()
            self._stop.clear()
            with Live(self, console=console, refresh_per_second=self.fps,
                      transient=False, vertical_overflow="visible") as live:
                # la duracion es de PARED (time.monotonic): el reloj de
                # animacion puede estar congelado (tests) y la Live termina igual
                fin = time.monotonic() + dur
                while not self._stop.wait(1.0 / self.fps):
                    if time.monotonic() >= fin:
                        break
                live.update(self.frame_final())
            return True
        except Exception as exc:
            _avisar(f"banner: {type(exc).__name__}: {exc}; frame estatico")
            console.print(self.frame_final())
            return False


# ---------------------------------------------------------------------------
# Pulso del prompt: UN hilo daemon finito de app.invalidate()
# ---------------------------------------------------------------------------
_PULSO = {"hilo": None, "stop": None, "t0": 0.0, "activo": False}
_PULSO_LOCK = threading.Lock()


def animando() -> bool:
    """True mientras el pulso corre: _mensaje_prompt devuelve frames vivos;
    despues, el frame estatico memoizado."""
    return bool(_PULSO["activo"])


def t_pulso() -> float:
    """Segundos desde que arranco el pulso vigente (0 si no hay)."""
    return max(0.0, RELOJ.t() - float(_PULSO["t0"])) if _PULSO["activo"] else 0.0


def pulso_prompt(app, segundos=None, fps=None) -> bool:
    """Arranca el UNICO hilo daemon que llama app.invalidate() a `fps` durante
    `segundos` (acotado a PULSO_MAX_S) y muere solo dejando el frame
    estatico (animando() pasa a False ANTES del ultimo invalidate). Devuelve
    False, sin hilo, si ya hay un pulso vivo, si capacidades() no anima o si
    segundos <= 0. refresh_interval de la sesion NO se toca (E3): medido
    0,4% de CPU en reposo con el pulso terminado y 7,8% durante el pulso.
    Application.invalidate es thread-safe y no hace nada si la app no corre:
    arrancarlo antes de session.prompt() es seguro."""
    fps = int(fps or FPS)
    if segundos is None:
        segundos = PULSO_MAX_S
    segundos = float(min(PULSO_MAX_S, segundos))
    if segundos <= 0 or app is None:
        return False
    if not capacidades().animar:
        return False
    with _PULSO_LOCK:
        hilo = _PULSO["hilo"]
        if hilo is not None and hilo.is_alive():
            return False
        stop = threading.Event()
        _PULSO["stop"] = stop
        _PULSO["t0"] = RELOJ.t()
        _PULSO["activo"] = True

        def _correr():
            fin = time.monotonic() + segundos      # duracion de pared, no del RELOJ
            try:
                while not stop.wait(1.0 / fps) and time.monotonic() < fin:
                    app.invalidate()
            except Exception as exc:
                _avisar(f"pulso del prompt: {type(exc).__name__}: {exc}")
            finally:
                _PULSO["activo"] = False
                try:
                    app.invalidate()      # ultimo redibujo: deja el frame estatico
                except Exception as exc:
                    _avisar(f"pulso del prompt (cierre): {type(exc).__name__}: {exc}")

        hilo = threading.Thread(target=_correr, name="cognia-pulso-prompt", daemon=True)
        _PULSO["hilo"] = hilo
        hilo.start()
    return True


def parar_pulso(timeout: float = 1.0) -> None:
    """Corta el pulso vigente y espera a que el hilo muera (tests, /estilo
    animacion off, cierre del prompt)."""
    with _PULSO_LOCK:
        stop, hilo = _PULSO["stop"], _PULSO["hilo"]
    if stop is not None:
        stop.set()
    if hilo is not None and hilo.is_alive():
        hilo.join(timeout)
    _PULSO["activo"] = False


def duracion_pulso(estilos, tope_s: float = PULSO_MAX_S) -> float:
    """Cuantos segundos de pulso piden varios elementos vivos del prompt
    (el mayor de sus duracion_s, acotado): 0 si ninguno anima."""
    return max([0.0] + [e.duracion_s(tope_s) for e in estilos if isinstance(e, EstiloGlow)])
