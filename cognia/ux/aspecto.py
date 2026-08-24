# -*- coding: utf-8 -*-
"""
cognia/ux/aspecto.py -- el REGISTRO de estilos por elemento del CLI (2026-08-24).

QUE: un modulo de DATOS + resolucion. Declara cada elemento visual del REPL
(banner, prompt, barra, menu, spinner, tools, respuesta, pensando, avisos,
footer, paneles, diff, separador, sistema, agentes) con las propiedades que
ACEPTA (Cap), su aspecto por DEFECTO (el de hoy, con @refs a paleta.py), si
esta vivo (puede animarse) y si es contrato bajo COGNIA_REMOTO. Encima de ese
default se apila el fichero ~/.cognia/estilo.json (P2) y los cambios en
memoria del editor /estilo (P10+), y de la pila salen las tres salidas que
consumen los que pintan: `clases_pt` (el dict del PTStyle del prompt),
`tema_rich` (el dict del Theme de rich) y `estilo_resuelto` (colores en hex,
glifo ya elegido por encoding, booleanos ya decididos).

REGLA NUMERO UNO: sin fichero ni cambios, la salida es BYTE-IDENTICA al
aspecto actual. Se protege por tres lados: tests/golden/aspecto (P0),
`clases_pt(v) == dict literal de cli._estilo_prompt` y
`tema_rich(v) == paleta.tema_cli(v)` (tests/test_ux_aspecto.py).

CONTRATO:
- Importable sin cli.py, sin rich ni prompt_toolkit en el import (como
  paleta.py). rich se importa DENTRO de las funciones que traducen nombres de
  color; si no esta, esas funciones lanzan y validar() lo reporta.
- Un color es: '#rrggbb' | '@rampa.<escalon>' | '@semantico.<k>' |
  '@superficie.<k>' | '@menu.<k>' | '@diff.<k>' | '@token.<token_rich>' |
  '@mi.<nombre>' (paleta local del fichero) | 'terminal' (heredar; '' en PT,
  'default' en rich) | 'rich' (no declarar: deja el default de rich; solo
  respuesta.markdown) | 'ansi<nombre>' de prompt_toolkit | un dict
  {'oscuro':..,'claro':..,'alto_contraste':..}.
- None en un campo de Estilo = "no toca el default": el fichero es un
  OVERRIDE parcial.
- Degradacion: nada aqui lanza por un adorno salvo error del programador
  (id desconocido en elemento(): KeyError ruidoso con ids parecidos). Los
  fallos de datos del dueno salen como Aviso(nivel='error'|'aviso') de
  validar()/poner(), nunca en silencio; quien los enruta a
  cli._aviso_degradado es el consumidor (P4).
- Bajo COGNIA_REMOTO=1 los elementos con contrato_remoto=True devuelven el
  glifo y el texto por DEFECTO aunque el fichero diga otra cosa: son marcas
  que el clasificador del movil (remoto/sesiones.py) reconoce.

Lo que NO esta aqui: el motor de glow/barrido (ux/glow.py, P3), el editor
(ux/editor_aspecto.py, P10) y los enganches en cli.py (P4-P9).
"""
from __future__ import annotations

import dataclasses
import difflib
import os
import sys
from dataclasses import dataclass, field
from enum import Enum

from . import paleta

# Version del formato del fichero estilo.json que este modulo entiende.
VERSION_FICHERO = 1

ORDEN_VARIANTES = tuple(paleta.ORDEN_VARIANTES)
VARIANTE_DEFECTO = "oscuro"

# velocidad (1..5) -> periodo del barrido en segundos (seccion 1.1 del diseno)
PERIODO_S = {1: 3.0, 2: 2.0, 3: 1.5, 4: 1.0, 5: 0.6}
TIPOS_ANIMACION = ("barrido", "pulso")
DIRECCIONES = ("derecha", "izquierda", "ida_vuelta")
CAJAS = ("rounded", "square", "heavy", "double", "none")
GLIFOS_GLOBAL = ("auto", "unicode", "ascii")
# Piso de contraste WCAG: texto 4,5 (AA); reglas/bordes/bandas 3,0 (1.4.11).
PISO_TEXTO = 4.5
PISO_GRAFICO = 3.0


# ---------------------------------------------------------------------------
# 1. Tipos
# ---------------------------------------------------------------------------
class Cap(str, Enum):
    """Que propiedades ACEPTA un elemento."""
    TEXTO = "texto"
    COLOR = "color"
    FONDO = "fondo"
    NEGRITA = "negrita"
    ITALICA = "italica"
    SUBRAYADO = "subrayado"
    GLOW = "glow"
    ANIMACION = "animacion"
    GLIFO = "glifo"
    POSICION = "posicion"
    ALINEACION = "alineacion"
    VISIBLE = "visible"
    GRADIENTE = "gradiente"     # solo banner.arte
    SEPARADOR = "separador"     # barra.estado, footer, spinner: el ' · '


@dataclass(frozen=True)
class Glow:
    color: str | None = None    # hex | @ref | None = derivado del color base
    intensidad: int = 0         # 0 nada, 1 mezcla 25%, 2 50%+negrita, 3 75%+negrita+halo


@dataclass(frozen=True)
class Animacion:
    activa: bool = False
    tipo: str = "barrido"       # barrido | pulso
    direccion: str = "derecha"  # derecha | izquierda | ida_vuelta
    velocidad: int = 2          # 1..5 -> PERIODO_S
    ancho: int = 5              # semiancho de la ventana en celdas
    repetir: int = 0            # 0 = infinito mientras el elemento este vivo
    cada_s: float = 0.0         # pausa entre barridos (0 = continuo)
    solo_al_llegar: bool = False


@dataclass(frozen=True)
class Estilo:
    """El objeto COMPLETO de propiedades, igual para todos los elementos.
    None = no toca el default. `texto` es str (un solo texto) o dict
    clave->str (varios textos editables, p.ej. banner.guia). `estados` son
    sub-estilos (activo/meta/ok/error/h1...) con estas mismas claves."""
    texto: str | dict | None = None
    color: str | dict | None = None
    fondo: str | dict | None = None
    negrita: bool | None = None
    italica: bool | None = None
    subrayado: bool | None = None
    glow: Glow | None = None
    animacion: Animacion | None = None
    glifo: str | None = None
    glifo_ascii: str | None = None
    posicion: str | None = None
    alineacion: str | None = None
    visible: bool | None = None
    gradiente: tuple | None = None
    separador: str | None = None
    estados: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Elemento:
    id: str
    nombre: str
    grupo: str
    caps: frozenset
    default: Estilo
    vivo: bool = False                  # True = se redibuja: puede animarse
    contrato_remoto: bool = False       # texto/glifo vuelven al default bajo remoto
    posiciones: tuple = ()
    alineaciones: tuple = ()
    glifos: tuple = ()                  # valores validos de 'glifo' si es un enum (cajas)
    estados: tuple = ()                 # sub-estados que declara
    grafico: bool = False               # piso de contraste 3,0 en vez de 4,5
    nota: str = ""
    # E8: False hasta que el paso que lo cablea lo ponga en True; /estilo
    # avisa "se aplica en la proxima version" para los que siguen en False.
    enganchado: bool = False


@dataclass(frozen=True)
class Aviso:
    nivel: str          # 'error' (se rechaza) | 'aviso' (se acepta y se avisa)
    texto: str
    id: str = ""

    def __str__(self) -> str:
        return f"{self.nivel}: {self.id + ': ' if self.id else ''}{self.texto}"


@dataclass(frozen=True)
class EstiloResuelto:
    """Lo que un consumidor pinta: colores ya en hex / nombre ansi de
    prompt_toolkit ('' = heredar de la terminal), glifo ya decidido por el
    encoding, booleanos ya decididos (el token del tema aporta bold/italic
    /dim si el elemento no dice nada)."""
    id: str
    variante: str
    texto: str | dict | None
    color: str
    fondo: str
    negrita: bool
    italica: bool
    subrayado: bool
    tenue: bool                 # el token base lleva 'dim'
    glow_color: str             # hex del glow (derivado si no se declaro)
    glow_intensidad: int
    animacion: Animacion
    glifo: str
    posicion: str | None
    alineacion: str | None
    visible: bool
    gradiente: tuple | None     # (hex_desde, hex_hasta) o None
    separador: str | None
    token: str                  # token de rich del que sale el color ('' si ninguno)
    estados: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 2. Registro: 43 ids del diseno (seccion 1.3) + enmiendas E1, E2 y E9
# ---------------------------------------------------------------------------
_TODAS = frozenset(Cap)


def _caps(*c: Cap) -> frozenset:
    return frozenset(c)


def _E(id: str, nombre: str, caps: frozenset, default: Estilo, **kw) -> Elemento:
    return Elemento(id=id, nombre=nombre, grupo=id.split(".")[0] if "." in id else kw.pop("grupo"),
                    caps=caps, default=default, **kw)


_SIN_ANIM = Animacion()

# Los sub-estados de las secciones de la barra: hoy TODOS al mismo verde
# (aplanados, byte-identico); los logicos de barra_estado.py se ofrecen como
# preset 'barra-color'.
_SECCIONES_BARRA = ("modelo", "dir", "rama", "sucio", "ctx", "ctx_alto",
                    "ctx_critico", "tokens")
_MARKDOWN_CLAVES = ("h1", "h2", "h3", "code", "link", "strong", "em", "hr", "item")
# 2026-08-24 (9f9c74e8): paleta.TOKENS_CLI declara los estilos 'markdown.*' y
# el Theme del CLI ya no deja titulos/codigo/enlaces/regla a los defaults de
# rich. El DEFAULT del registro es el aspecto ACTUAL, asi que cada sub-estado
# con token apunta a SU token; lo que la paleta no declara (strong/em/item)
# sigue en 'rich' (= no declarar).
_MARKDOWN_DEFAULT = {"h1": "@token.markdown.h1", "h2": "@token.markdown.h2",
                     "h3": "@token.markdown.h3", "code": "@token.markdown.code",
                     "link": "@token.markdown.link", "hr": "@token.markdown.hr"}

_ELEMENTOS = (
    # -- banner ---------------------------------------------------------------
    _E("banner.arte", "Gato Braille + logotipo",
       _caps(Cap.COLOR, Cap.GRADIENTE, Cap.GLOW, Cap.ANIMACION, Cap.ALINEACION, Cap.VISIBLE),
       Estilo(color="@rampa.profundo", gradiente=("@rampa.profundo", "@rampa.matrix"),
              alineacion="izquierda", glow=Glow(), animacion=_SIN_ANIM, visible=True),
       vivo=True, alineaciones=("izquierda", "derecha"), grafico=True,
       nota="identidad: el default no lo esconde (D6); vivo solo al arrancar"),
    _E("banner.marco", "Panel del banner (borde, titulo, subtitulo)",
       _caps(Cap.TEXTO, Cap.COLOR, Cap.NEGRITA, Cap.GLIFO, Cap.VISIBLE),
       Estilo(texto={"titulo": "COGNIA", "subtitulo": "sistema cognitivo local"},
              color="@token.marca", glifo="rounded", visible=True,
              estados={"titulo": Estilo(color="@token.marca_fuerte"),
                       "version": Estilo(color="@token.marca_dim"),
                       "subtitulo": Estilo(color="@token.marca_dim")}),
       glifos=CAJAS, estados=("titulo", "version", "subtitulo"), grafico=True),
    _E("banner.guia", "Columna 'Para empezar'",
       _caps(Cap.TEXTO, Cap.COLOR, Cap.VISIBLE),
       Estilo(texto={"cabecera": "Para empezar", "chat": "escribe y conversa",
                     "hacer": "<tarea> agente autonomo", "crear": "<idea> genera un programa",
                     "modelo": "elegir modelo o flota", "memoria": "estado de memoria",
                     "grafo": "<concepto> del saber", "tutor": "aprende cualquier tema",
                     "doctor": "diagnostico del sistema", "tab": "completar",
                     "historial": "historial", "ayuda": "todo"},
              color="@token.mod", visible=True,
              estados={"cabecera": Estilo(color="@token.marca_fuerte"),
                       "regla": Estilo(color="@token.marca_dim"),
                       "descripcion": Estilo(color="@token.detail"),
                       "atajo": Estilo(color="@token.marca"),
                       "atajo_accion": Estilo(color="@token.info_dim")}),
       estados=("cabecera", "regla", "descripcion", "atajo", "atajo_accion")),
    _E("banner.linea_modelo", "'modelo X (:puerto)   modo Y   tema Z'",
       _caps(Cap.TEXTO, Cap.COLOR, Cap.VISIBLE),
       Estilo(texto={"modelo": "modelo", "modo": "modo", "tema": "tema",
                     "sin_backend": "sin backend en {url} — arranca: cognia flota arrancar"},
              color="@token.info_dim", visible=True,
              estados={"sin_backend": Estilo(color="@token.warn_cl")}),
       estados=("sin_backend",)),
    # -- prompt ---------------------------------------------------------------
    _E("prompt.marco", "Reglas superior e inferior del marco",
       _caps(Cap.COLOR, Cap.FONDO, Cap.GLIFO, Cap.GLOW, Cap.ANIMACION, Cap.POSICION, Cap.VISIBLE),
       Estilo(color="@rampa.marco", glifo="─", glifo_ascii="-", glow=Glow(),
              animacion=_SIN_ANIM, posicion="ambos", visible=True),
       vivo=True, posiciones=("ambos", "arriba", "abajo", "ninguno"), grafico=True),
    _E("prompt.etiqueta", "La etiqueta del prompt ('cognia')",
       _caps(Cap.TEXTO, Cap.COLOR, Cap.NEGRITA, Cap.ITALICA, Cap.SUBRAYADO, Cap.GLOW,
             Cap.ANIMACION, Cap.POSICION, Cap.VISIBLE),
       Estilo(texto="cognia", color="@rampa.prompt", negrita=True, glow=Glow(),
              animacion=_SIN_ANIM, posicion="linea", visible=True),
       vivo=True, posiciones=("linea", "arriba"),
       nota="el que compone antepone el espacio: ' ' + texto (hoy ' cognia')"),
    _E("prompt.flecha", "La flecha del prompt",
       _caps(Cap.GLIFO, Cap.COLOR, Cap.NEGRITA, Cap.GLOW, Cap.ANIMACION, Cap.VISIBLE),
       Estilo(glifo="➤ ", glifo_ascii="> ", color="@rampa.texto", negrita=True,
              glow=Glow(), animacion=_SIN_ANIM, visible=True),
       vivo=True),
    _E("prompt.texto", "Lo que escribe el dueno",
       _caps(Cap.COLOR, Cap.FONDO, Cap.NEGRITA, Cap.ITALICA, Cap.SUBRAYADO),
       Estilo(color="@rampa.texto", negrita=True),
       nota="es el buffer de prompt_toolkit: no se anima"),
    _E("prompt.continuacion", "Sangria de la linea continuada con '\\'",
       _caps(Cap.TEXTO, Cap.COLOR),
       Estilo(texto="   ", color="@rampa.texto")),
    _E("prompt.espera", "Prompt del carril de fondo ('corrida 5s  F2 agentes...')",
       _caps(Cap.TEXTO, Cap.COLOR, Cap.GLOW, Cap.ANIMACION),
       Estilo(texto="F2 agentes · Ctrl-C corta la corrida", color="@rampa.prompt",
              glow=Glow(), animacion=_SIN_ANIM,
              estados={"aviso": Estilo(color="@rampa.estado")}),
       vivo=True, estados=("aviso",),
       nota="E3: se anima por pulso finito, nunca con refresh_interval=1/fps"),
    _E("prompt.busqueda", "Busqueda inversa Ctrl-R",
       _caps(Cap.COLOR, Cap.FONDO, Cap.NEGRITA, Cap.ITALICA),
       Estilo(color="terminal"),
       nota="E2: el prefijo lo pone prompt_toolkit; default = 'noinherit' / ''"),
    _E("prompt.seleccion", "Texto seleccionado en el prompt",
       _caps(Cap.COLOR, Cap.FONDO),
       Estilo(color="terminal"),
       nota="E2: default = 'reverse' de prompt_toolkit"),
    # -- barra ----------------------------------------------------------------
    _E("barra.estado", "Linea de estado bajo el marco",
       _caps(Cap.COLOR, Cap.FONDO, Cap.NEGRITA, Cap.ITALICA, Cap.GLOW, Cap.ANIMACION,
             Cap.POSICION, Cap.ALINEACION, Cap.SEPARADOR, Cap.VISIBLE),
       Estilo(color="@rampa.estado", glow=Glow(), animacion=_SIN_ANIM, posicion="abajo",
              alineacion="izquierda", separador=" · ", visible=True),
       vivo=True, posiciones=("abajo", "arriba"), alineaciones=("izquierda", "derecha"),
       nota="hoy MONOCROMA: todas las secciones al mismo verde"),
    _E("barra.estado.secciones", "Colores por seccion de la barra",
       _caps(Cap.COLOR),
       Estilo(color="@rampa.estado",
              estados={s: Estilo(color="@rampa.estado") for s in _SECCIONES_BARRA}),
       vivo=True, estados=_SECCIONES_BARRA,
       nota="los logicos de barra_estado.py (rama=mod, ctx_alto=warn_cl...) son el preset 'barra-color'"),
    _E("barra.atajos", "'tab completa · ↑↓ historial · ...'",
       _caps(Cap.TEXTO, Cap.COLOR, Cap.SEPARADOR, Cap.VISIBLE),
       Estilo(texto={"tab": "completa", "historial": "historial", "@": "archivo",
                     "/": "comandos", "f2": "agentes"},
              color="@rampa.estado", separador=" · ", visible=True,
              estados={"tecla": Estilo(color="@rampa.estado"),
                       "accion": Estilo(color="@rampa.estado")}),
       vivo=True, estados=("tecla", "accion")),
    _E("barra.modo", "Insignia PLAN / auto / manual",
       _caps(Cap.TEXTO, Cap.COLOR, Cap.NEGRITA, Cap.GLOW, Cap.ANIMACION),
       Estilo(texto={"plan": "PLAN", "auto": "auto", "manual": "manual"},
              color="@rampa.estado", glow=Glow(), animacion=_SIN_ANIM,
              estados={"plan": Estilo(color="@rampa.estado"),
                       "auto": Estilo(color="@rampa.estado"),
                       "manual": Estilo(color="@rampa.estado")}),
       vivo=True, estados=("plan", "auto", "manual")),
    # -- menu -----------------------------------------------------------------
    _E("menu.completado", "Menu flotante de '/' y '@'",
       _caps(Cap.COLOR, Cap.FONDO, Cap.NEGRITA),
       Estilo(color="@menu.texto", fondo="@menu.fondo",
              estados={"activo": Estilo(color="@menu.texto_activo", fondo="@menu.fondo_activo"),
                       "meta": Estilo(color="@menu.meta", fondo="@menu.fondo"),
                       "meta_activo": Estilo(color="@menu.meta_activo", fondo="@menu.fondo_activo"),
                       "coincidencia": Estilo(color="rich"),
                       "scrollbar": Estilo(fondo="@menu.scrollbar_fondo"),
                       "scrollbar_boton": Estilo(fondo="@menu.scrollbar_boton")}),
       estados=("activo", "meta", "meta_activo", "coincidencia", "scrollbar", "scrollbar_boton")),
    _E("menu.selector", "Selector con flechas (/tema, F3, permisos)",
       _caps(Cap.GLIFO, Cap.COLOR, Cap.FONDO, Cap.NEGRITA),
       Estilo(glifo="❯", glifo_ascii=">", color="terminal", negrita=True,
              estados={"activo": Estilo(color="terminal"),
                       "descripcion": Estilo(color="ansibrightblack")}),
       estados=("activo", "descripcion"),
       nota="sin animacion por diseno (seguridad: no distraer); 'activo' = reverse"),
    # -- spinner --------------------------------------------------------------
    _E("spinner.tool", "'· Leyendo motor.py… (12s · ~340 tok · ctrl+c corta)'",
       _caps(Cap.GLIFO, Cap.TEXTO, Cap.COLOR, Cap.NEGRITA, Cap.ITALICA, Cap.GLOW,
             Cap.ANIMACION, Cap.SEPARADOR),
       Estilo(glifo="·", glifo_ascii="o",
              texto={"hint": "ctrl+c corta", "tok": "tok", "spinner_rich": "dots"},
              color="@token.spinner", glow=Glow(), animacion=_SIN_ANIM, separador=" · "),
       vivo=True, nota="'spinner_rich' = nombre de rich.spinner.SPINNERS"),
    _E("spinner.pensar", "'· <verbo gato>… (Ns · ...)'",
       _caps(Cap.GLIFO, Cap.TEXTO, Cap.COLOR, Cap.NEGRITA, Cap.ITALICA, Cap.GLOW,
             Cap.ANIMACION, Cap.SEPARADOR),
       Estilo(glifo="·", glifo_ascii="o",
              texto={"pensando": "pensando…", "hint": "ctrl+c corta", "tok": "tok",
                     "spinner_rich": "dots"},
              color="@token.pensar", glow=Glow(), animacion=_SIN_ANIM, separador=" · "),
       vivo=True, nota="los verbos gato siguen en /spinner verbos"),
    _E("spinner.comando", "'Procesando...' / 'Mejorando el prompt...'",
       _caps(Cap.TEXTO, Cap.COLOR, Cap.GLIFO),
       Estilo(texto={"procesando": "Procesando...", "mejorando": "Mejorando el prompt...",
                     "spinner_rich": "dots"},
              color="@token.spinner", glifo="dots"),
       vivo=True, nota="'glifo' aqui = spinner de rich"),
    # -- tool -----------------------------------------------------------------
    _E("tool.ok", "Marca de tool terminada",
       _caps(Cap.GLIFO, Cap.COLOR, Cap.NEGRITA),
       Estilo(glifo="●", glifo_ascii="+", color="@token.ok_cl"),
       contrato_remoto=True,
       nota="render colapsado '●' (render_tools); el clasico '⏺' es contrato del remoto"),
    _E("tool.error", "Marca de tool fallida",
       _caps(Cap.GLIFO, Cap.COLOR),
       Estilo(glifo="●", glifo_ascii="x", color="@token.err_cl"),
       contrato_remoto=True, nota="el clasico '✗' es contrato del remoto"),
    _E("tool.curso", "Marca de tool en curso",
       _caps(Cap.GLIFO, Cap.COLOR),
       Estilo(glifo="·", glifo_ascii="o", color="@token.info_dim"),
       contrato_remoto=True),
    _E("tool.verbo", "'Leyendo'",
       _caps(Cap.COLOR, Cap.NEGRITA, Cap.ITALICA),
       Estilo(color="@token.tool_verbo")),
    _E("tool.objeto", "'motor.py'",
       _caps(Cap.COLOR, Cap.NEGRITA, Cap.ITALICA, Cap.SUBRAYADO),
       Estilo(color="@token.tool_obj")),
    _E("tool.resultado", "'  ⎿ 46 lineas' / '… +197 lineas (/expandir 3)'",
       _caps(Cap.GLIFO, Cap.COLOR, Cap.TEXTO),
       Estilo(glifo="⎿", glifo_ascii="|_", color="@token.info_dim",
              texto={"lineas": "lineas", "sin_salida": "sin salida", "expandir": "/expandir"}),
       contrato_remoto=True),
    _E("tool.intencion", "'  Voy a leer...'",
       _caps(Cap.COLOR, Cap.ITALICA, Cap.NEGRITA, Cap.VISIBLE),
       Estilo(color="@token.intencion", italica=True, visible=True)),
    # -- respuesta ------------------------------------------------------------
    _E("respuesta.texto", "Lo que contesta el modelo",
       _caps(Cap.COLOR, Cap.FONDO, Cap.NEGRITA, Cap.ITALICA, Cap.GLOW),
       Estilo(color="@token.respuesta", glow=Glow()),
       vivo=True,
       nota="E10: sin ANIMACION (solo glow estatico); la sangria es global.respuesta_sangria"),
    _E("respuesta.markdown", "Titulos, codigo inline, enlaces, negritas del markdown",
       _caps(Cap.COLOR, Cap.NEGRITA, Cap.ITALICA),
       Estilo(color="rich", estados={k: Estilo(color=_MARKDOWN_DEFAULT.get(k, "rich"))
                                     for k in _MARKDOWN_CLAVES}),
       estados=_MARKDOWN_CLAVES,
       nota="h1/h2/h3/code/link/hr = los tokens markdown.* de la paleta (9f9c74e8); "
            "strong/em/item = 'rich' (no declarar: el default de rich, byte-identico)"),
    _E("respuesta.codigo", "Bloques de codigo (tema pygments)",
       _caps(Cap.TEXTO),
       Estilo(texto="monokai"),
       nota="espejo de la config 'markdown_tema' (/markdown tema)"),
    # -- pensando -------------------------------------------------------------
    _E("pensando.prosa", "Razonamiento en vivo ('∴ ...')",
       _caps(Cap.GLIFO, Cap.COLOR, Cap.ITALICA, Cap.NEGRITA, Cap.VISIBLE),
       Estilo(glifo="∴", glifo_ascii="*", color="@token.pensar", italica=True, visible=False),
       contrato_remoto=True,
       nota="visible=False = plegado (hoy lo decide COGNIA_PENSAR=ver); FlujoSuave imprime: no se anima"),
    _E("pensando.plegado", "'∴ pensó 4s (ctrl+o ...)'",
       _caps(Cap.TEXTO, Cap.GLIFO, Cap.COLOR),
       Estilo(texto={"penso": "pensó"}, glifo="∴", glifo_ascii="*", color="@token.pensar"),
       contrato_remoto=True),
    # -- aviso ----------------------------------------------------------------
    _E("aviso.degradado", "'  ⚠ degradado — x: motivo' + '  → accion'",
       _caps(Cap.GLIFO, Cap.TEXTO, Cap.COLOR, Cap.NEGRITA),
       Estilo(glifo="⚠", glifo_ascii="!", texto={"degradado": "degradado — ", "accion": "→"},
              color="@token.warn_cl"),
       contrato_remoto=True),
    _E("aviso.info", "Avisos tenues",
       _caps(Cap.COLOR, Cap.ITALICA),
       Estilo(color="@token.info_dim")),
    _E("aviso.error", "Errores de comandos y logs ERROR",
       _caps(Cap.COLOR, Cap.NEGRITA),
       Estilo(color="@token.err_cl")),
    # -- footer ---------------------------------------------------------------
    _E("footer.turno", "'  ✓ 12.3s · 840 tokens · 3 pasos'",
       _caps(Cap.GLIFO, Cap.TEXTO, Cap.COLOR, Cap.SEPARADOR, Cap.VISIBLE),
       Estilo(glifo="✓", glifo_ascii="v", texto={"tokens": "tokens", "pasos": "pasos", "paso": "paso"},
              color="@token.footer", separador=" · ", visible=True,
              estados={"ok": Estilo(glifo="✓", glifo_ascii="v", color="@token.ok_cl"),
                       "error": Estilo(glifo="✗", glifo_ascii="x", color="@token.err_cl")}),
       contrato_remoto=True, estados=("ok", "error"),
       nota="bajo remoto el formato es fijo (_RE_FOOTER_RENDERER)"),
    # -- panel ----------------------------------------------------------------
    _E("panel.borde", "Bordes de los paneles de chrome",
       _caps(Cap.COLOR, Cap.GLIFO),
       Estilo(color="@token.borde", glifo="rounded"),
       glifos=CAJAS, grafico=True),
    _E("panel.titulo", "Titulos de paneles y secciones",
       _caps(Cap.COLOR, Cap.NEGRITA, Cap.TEXTO),
       Estilo(color="@token.titulo",
              texto={"interacciones": "Ultimas interacciones", "modulos": "Modulos activos",
                     "costo": "Costo de sesion", "stats": "Stats de sesion",
                     "skills": "Skills disponibles"})),
    _E("panel.cuerpo", "Cuerpo de listados (/ayuda, /config, /sesiones)",
       _caps(Cap.COLOR, Cap.ITALICA),
       Estilo(color="@token.listado")),
    # -- diff -----------------------------------------------------------------
    _E("diff.mas", "Lineas '+' del preview",
       _caps(Cap.COLOR, Cap.FONDO, Cap.GLIFO, Cap.NEGRITA),
       Estilo(color="@token.respuesta", fondo="@diff.mas", glifo="+", negrita=True,
              estados={"marca": Estilo(color={"oscuro": "@semantico.ok", "claro": "@rampa.solido",
                                              "alto_contraste": "@semantico.ok"}, negrita=True),
                       "intra": Estilo(fondo="@diff.mas_intra")}),
       estados=("marca", "intra"), grafico=True),
    _E("diff.menos", "Lineas '-' del preview",
       _caps(Cap.COLOR, Cap.FONDO, Cap.GLIFO, Cap.NEGRITA),
       Estilo(color="@token.respuesta", fondo="@diff.menos", glifo="-", negrita=True,
              estados={"marca": Estilo(color={"oscuro": "@semantico.error", "claro": "@token.err_cl",
                                              "alto_contraste": "@semantico.error"}, negrita=True),
                       "intra": Estilo(fondo="@diff.menos_intra")}),
       estados=("marca", "intra"), grafico=True),
    # -- separador ------------------------------------------------------------
    _E("separador.regla", "Regla fina de /ayuda y console.rule",
       _caps(Cap.GLIFO, Cap.COLOR),
       Estilo(glifo="─", glifo_ascii="-", color="@token.info_dim"),
       grafico=True),
    # -- sistema --------------------------------------------------------------
    _E("sistema.ok", "Confirmaciones [ok_cl]",
       _caps(Cap.COLOR, Cap.NEGRITA),
       Estilo(color="@token.ok_cl")),
    _E("sistema.detalle", "Prosa secundaria [detail]",
       _caps(Cap.COLOR, Cap.ITALICA),
       Estilo(color="@token.detail")),
    # E9: los enlaces OSC-8 de harness/enlaces.py (style 'link').
    _E("enlace", "Rutas con hyperlink OSC-8 (ctrl+click)",
       _caps(Cap.COLOR, Cap.SUBRAYADO, Cap.VISIBLE),
       Estilo(color="terminal", visible=True),
       grupo="sistema", nota="E9: visible=False apaga el OSC-8"),
    # -- agentes (E1: la vista F2, cognia/tui/agentes.py via tui/theme.COLORS)
    _E("agentes.acento", "Vista F2: acento (identidad)",
       _caps(Cap.COLOR, Cap.FONDO),
       Estilo(color="@rampa.prompt"),
       nota="E1: tui/theme.COLORS['accent']"),
    _E("agentes.panel", "Vista F2: paneles",
       _caps(Cap.COLOR, Cap.FONDO),
       Estilo(color="@semantico.texto", fondo="@superficie.panel"),
       nota="E1: COLORS['panel'] / ['text']"),
    _E("agentes.borde", "Vista F2: bordes",
       _caps(Cap.COLOR, Cap.FONDO),
       Estilo(color="@superficie.borde"),
       grafico=True, nota="E1: COLORS['border']"),
    _E("agentes.texto", "Vista F2: texto y fondo de la app",
       _caps(Cap.COLOR, Cap.FONDO),
       Estilo(color="@semantico.texto", fondo="@superficie.fondo"),
       nota="E1: COLORS['text'] / ['bg']"),
)

REGISTRO: dict = {e.id: e for e in _ELEMENTOS}
assert len(REGISTRO) == len(_ELEMENTOS), "id duplicado en el registro"

GRUPOS: list = []
for _e in _ELEMENTOS:
    if not GRUPOS or GRUPOS[-1][0] != _e.grupo:
        GRUPOS.append((_e.grupo, []))
    GRUPOS[-1][1].append(_e.id)
del _e

# Que tokens del Theme de rich RETINE cada elemento cuando se le cambia el
# color/negrita/italica (tema_rich). Un token compartido (ok_cl lo usan
# sistema.ok, tool.ok y footer.turno.ok) lo manda el PRIMERO de la lista que
# tenga override, en el orden del registro. Es la tabla que P6 consume.
TOKENS_POR_ELEMENTO: dict = {
    "banner.marco": ("marca",),
    "banner.guia": ("mod",),
    "banner.linea_modelo": ("info_dim",),
    "spinner.tool": ("spinner",),
    "spinner.pensar": ("pensar",),
    "tool.ok": ("ok_cl",),
    "tool.error": ("err_cl",),
    "tool.curso": ("info_dim",),
    "tool.verbo": ("tool_verbo",),
    "tool.objeto": ("tool_obj",),
    "tool.resultado": ("info_dim",),
    "tool.intencion": ("intencion",),
    "respuesta.texto": ("respuesta",),
    "pensando.prosa": ("pensar",),
    "pensando.plegado": ("pensar",),
    "aviso.degradado": ("warn_cl",),
    "aviso.info": ("info_dim",),
    "aviso.error": ("err_cl",),
    "footer.turno": ("footer",),
    "panel.borde": ("borde",),
    "panel.titulo": ("titulo",),
    "panel.cuerpo": ("listado",),
    "separador.regla": ("info_dim",),
    "sistema.ok": ("ok_cl", "ok"),
    "sistema.detalle": ("detail",),
}

# Campo de Estilo -> capacidad que lo autoriza.
_CAP_DE_CAMPO = {
    "texto": Cap.TEXTO, "color": Cap.COLOR, "fondo": Cap.FONDO,
    "negrita": Cap.NEGRITA, "italica": Cap.ITALICA, "subrayado": Cap.SUBRAYADO,
    "glow": Cap.GLOW, "animacion": Cap.ANIMACION, "glifo": Cap.GLIFO,
    "glifo_ascii": Cap.GLIFO, "posicion": Cap.POSICION, "alineacion": Cap.ALINEACION,
    "visible": Cap.VISIBLE, "gradiente": Cap.GRADIENTE, "separador": Cap.SEPARADOR,
}
_CAMPOS_ESTILO = tuple(f.name for f in dataclasses.fields(Estilo))
_CAMPOS_GLOW = tuple(f.name for f in dataclasses.fields(Glow))
_CAMPOS_ANIM = tuple(f.name for f in dataclasses.fields(Animacion))


# ---------------------------------------------------------------------------
# 3. Estado del modulo: la pila default <- fichero <- memoria
# ---------------------------------------------------------------------------
# 'doc' es el fichero cargado (P2: cargar()); 'overrides' lo que /estilo o el
# editor pusieron sin guardar; 'version' sube en cada cambio (los memo del
# motor la miran); 'paleta_local' son los @mi.* del fichero.
_estado = {"doc": {}, "overrides": {}, "version": 0, "paleta_local": {}}


def version() -> int:
    """Contador que sube en cada poner()/cargar()/reset(): clave de memo."""
    return _estado["version"]


def _subir_version() -> None:
    _estado["version"] += 1


def variante_activa() -> str:
    """COGNIA_THEME -> cli._variante_actual() (si el CLI esta cargado) -> 'oscuro'."""
    nombre = os.environ.get("COGNIA_THEME", "").strip()
    if nombre in ORDEN_VARIANTES:
        return nombre
    cli = sys.modules.get("cognia.cli")
    if cli is not None:
        try:
            v = cli._variante_actual()
            if v in ORDEN_VARIANTES:
                return v
        except Exception:
            pass
    return VARIANTE_DEFECTO


def _remoto() -> bool:
    return os.environ.get("COGNIA_REMOTO", "").strip() == "1"


def animacion_global() -> tuple:
    """(activa, motivo) del interruptor GLOBAL de animacion: COGNIA_ANIMACION=0
    gana; despues la config 'estilo_animacion' (default 'on'; la clave la
    agrega P4 a _CONFIG_DEFAULTS, hasta entonces se lee con default). Es el
    primer escalon del orden D8; el resto (tty, remoto, ssh...) lo decide
    glow.capacidades() (P3)."""
    v = os.environ.get("COGNIA_ANIMACION", "").strip().lower()
    if v in ("0", "off", "false", "no"):
        return False, "COGNIA_ANIMACION=0"
    cli = sys.modules.get("cognia.cli")
    if cli is not None:
        try:
            cfg = cli._load_config()
            if str(cfg.get("estilo_animacion", "on")).strip().lower() in ("off", "0", "false", "no"):
                return False, "config estilo_animacion=off"
        except Exception as exc:
            return True, f"config ilegible ({type(exc).__name__}): se asume on"
    return True, ""


def elemento(id: str) -> Elemento:
    """KeyError RUIDOSO con los ids parecidos si no existe."""
    try:
        return REGISTRO[id]
    except KeyError:
        parecidos = difflib.get_close_matches(id, REGISTRO, n=3, cutoff=0.5)
        pista = f"; ids parecidos: {', '.join(parecidos)}" if parecidos else ""
        raise KeyError(f"elemento desconocido '{id}'{pista}") from None


def ids() -> list:
    return list(REGISTRO)


# -- fusion de un Estilo con un dict de cambios -----------------------------
def _fusionar(base: Estilo, cambios: dict) -> Estilo:
    """`cambios` es un dict (forma del fichero): solo pisa lo que trae."""
    if not cambios:
        return base
    kw = {}
    for campo, valor in cambios.items():
        if campo not in _CAMPOS_ESTILO:
            continue
        if campo == "glow":
            actual = base.glow or Glow()
            kw["glow"] = dataclasses.replace(actual, **{k: v for k, v in (valor or {}).items()
                                                        if k in _CAMPOS_GLOW})
        elif campo == "animacion":
            actual = base.animacion or Animacion()
            kw["animacion"] = dataclasses.replace(actual, **{k: v for k, v in (valor or {}).items()
                                                             if k in _CAMPOS_ANIM})
        elif campo == "estados":
            nuevos = dict(base.estados)
            for nombre, sub in (valor or {}).items():
                nuevos[nombre] = _fusionar(nuevos.get(nombre, Estilo()), sub or {})
            kw["estados"] = nuevos
        elif campo == "texto" and isinstance(base.texto, dict) and isinstance(valor, dict):
            kw["texto"] = {**base.texto, **valor}
        elif campo == "gradiente" and valor is not None:
            kw["gradiente"] = tuple(valor)
        else:
            kw[campo] = valor
    return dataclasses.replace(base, **kw)


def _a_dict(estilo: Estilo) -> dict:
    """Estilo -> dict con la forma del fichero (sin claves None)."""
    d = {}
    for campo in _CAMPOS_ESTILO:
        v = getattr(estilo, campo)
        if v is None or (campo == "estados" and not v):
            continue
        if campo in ("glow", "animacion"):
            # sin claves None (glow.color=None = derivado): el schema no admite null
            d[campo] = {k: x for k, x in dataclasses.asdict(v).items() if x is not None}
        elif campo == "estados":
            d[campo] = {k: _a_dict(sub) for k, sub in v.items()}
        elif campo == "gradiente":
            d[campo] = list(v)
        elif isinstance(v, dict):
            d[campo] = dict(v)
        else:
            d[campo] = v
    return d


def _cambios_de(id: str) -> dict:
    """Los cambios apilados sobre el default (fichero y luego memoria)."""
    doc = (_estado["doc"].get("elementos") or {}).get(id) or {}
    mem = _estado["overrides"].get(id) or {}
    return _fusionar_dicts(doc, mem)


def _fusionar_dicts(a: dict, b: dict) -> dict:
    out = dict(a)
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _fusionar_dicts(out[k], v)
        else:
            out[k] = v
    return out


def estilo_de(id: str, variante: str | None = None) -> Estilo:
    """default <- estilo.json <- overrides en memoria. Sin resolver colores."""
    return _fusionar(elemento(id).default, _cambios_de(id))


def tiene_override(id: str) -> bool:
    return bool(_cambios_de(id))


def cambios(id: str) -> dict:
    """Lo que difiere del default (forma del fichero), para guardar()/ver."""
    return _cambios_de(id)


# ---------------------------------------------------------------------------
# 4. Colores: referencias '@' y traduccion a hex / nombre ansi
# ---------------------------------------------------------------------------
# rich -> prompt_toolkit para los 16 basicos (PT no entiende 'bright_cyan').
_ANSI_RICH_A_PT = {
    "black": "ansiblack", "red": "ansired", "green": "ansigreen", "yellow": "ansiyellow",
    "blue": "ansiblue", "magenta": "ansimagenta", "cyan": "ansicyan", "white": "ansiwhite",
    "bright_black": "ansibrightblack", "bright_red": "ansibrightred",
    "bright_green": "ansibrightgreen", "bright_yellow": "ansibrightyellow",
    "bright_blue": "ansibrightblue", "bright_magenta": "ansibrightmagenta",
    "bright_cyan": "ansibrightcyan", "bright_white": "ansibrightwhite",
}
_ANSI_PT_A_RICH = {v: k for k, v in _ANSI_RICH_A_PT.items()}
# 'dim' no existe en prompt_toolkit: mezcla del color hacia el fondo.
MEZCLA_DIM = 0.45
_RE_HEX = __import__("re").compile(r"^#[0-9a-fA-F]{6}$")


def _ref(valor: str, variante: str) -> str:
    """'@rampa.prompt' -> '#7ee62a' (o el estilo del token). KeyError si no existe."""
    if "." not in valor:
        raise KeyError(f"referencia sin punto: '{valor}' (forma: @tabla.clave)")
    tabla, clave = valor[1:].split(".", 1)
    if tabla == "rampa":
        return paleta.RAMPA[variante][clave]
    if tabla == "semantico":
        return paleta.SEMANTICO[clave]
    if tabla == "superficie":
        return paleta.SUPERFICIE[clave]
    if tabla == "menu":
        return paleta.MENU_PROMPT[clave]
    if tabla == "diff":
        return paleta.DIFF_FONDO[variante][clave]
    if tabla == "token":
        return paleta.tema_cli(variante)[clave]
    if tabla == "mi":
        v = _estado["paleta_local"][clave]
        if isinstance(v, dict):
            v = v[variante]
        return v
    raise KeyError(f"tabla de referencia desconocida '@{tabla}' "
                   f"(rampa, semantico, superficie, menu, diff, token, mi)")


def _mezclar(hex_a: str, hex_b: str, f: float) -> str:
    va = [int(hex_a[i:i + 2], 16) for i in (1, 3, 5)]
    vb = [int(hex_b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{int(round(a + (b - a) * f)):02x}" for a, b in zip(va, vb))


def _estilo_rich_a_partes(estilo: str, variante: str) -> dict:
    """Un estilo de rich ('bold cyan', 'dim white', '#4fd010', 'default') ->
    {color: hex|ansi_pt|'', bold, italic, underline, dim}. rich se importa
    aqui a proposito (el modulo se importa sin rich)."""
    from rich.color import ColorType
    from rich.style import Style
    st = Style.parse(estilo)
    color = ""
    c = st.color
    if c is not None and not c.is_default:
        if c.type in (ColorType.STANDARD, ColorType.WINDOWS) and c.name in _ANSI_RICH_A_PT:
            color = _ANSI_RICH_A_PT[c.name]
        else:
            t = c.get_truecolor()
            color = f"#{t.red:02x}{t.green:02x}{t.blue:02x}"
    if st.dim and color:
        if not color.startswith("#"):
            t = c.get_truecolor()
            color = f"#{t.red:02x}{t.green:02x}{t.blue:02x}"
        color = _mezclar(color, paleta.FONDO_VARIANTE[variante], MEZCLA_DIM)
    return {"color": color, "bold": bool(st.bold), "italic": bool(st.italic),
            "underline": bool(st.underline), "dim": bool(st.dim)}


def _partes_color(valor, variante: str) -> dict:
    """Cualquier valor de color -> partes (ver _estilo_rich_a_partes)."""
    vacio = {"color": "", "bold": False, "italic": False, "underline": False, "dim": False}
    if valor is None:
        return vacio
    if isinstance(valor, dict):
        if variante not in valor:
            raise KeyError(f"color por variante sin la clave '{variante}'")
        return _partes_color(valor[variante], variante)
    v = str(valor).strip()
    if v in ("", "terminal", "default", "rich"):
        return vacio
    if v.startswith("@"):
        v = _ref(v, variante)
        if isinstance(v, dict):
            return _partes_color(v, variante)
    if _RE_HEX.match(v):
        return {**vacio, "color": v.lower()}
    if v.startswith("ansi") and v in _ANSI_PT_A_RICH:
        return {**vacio, "color": v}
    return _estilo_rich_a_partes(v, variante)


def resolver_color(valor, variante: str | None = None) -> str:
    """hex, nombre ansi de prompt_toolkit ('ansibrightcyan') o '' (terminal).
    Lanza KeyError/ValueError si el valor no resuelve (validar lo reporta)."""
    variante = variante or variante_activa()
    return _partes_color(valor, variante)["color"]


def color_rich(valor_resuelto: str) -> str:
    """Un color resuelto (hex | ansi de PT | '') en vocabulario de rich."""
    if not valor_resuelto:
        return "default"
    return _ANSI_PT_A_RICH.get(valor_resuelto, valor_resuelto)


def _hex_de(color_resuelto: str, variante: str) -> str | None:
    """hex medible del color resuelto: los nombres ansi solo si el medidor de
    scripts/contraste_tema.py esta disponible (tabla Campbell/claro)."""
    if not color_resuelto:
        return None
    if color_resuelto.startswith("#"):
        return color_resuelto
    m = _medidor()
    if m is None:
        return None
    try:
        return m.resolver(color_rich(color_resuelto), variante)
    except Exception:
        return None


def hex_medible(valor, variante: str) -> str | None:
    """El hex con el que se MIDE un valor de color (validar, tests, editor):
    un hex tal cual; un @token o nombre de rich con el MISMO instrumento que
    scripts/contraste_tema.py (Campbell/claro, 'dim' = mezcla 0,4) cuando esta
    disponible, para que el numero del editor sea el del juicio visual; sin el
    medidor, un hex derivado (dim = MEZCLA_DIM) o None si es un nombre ansi."""
    if valor is None:
        return None
    if isinstance(valor, dict):
        valor = valor.get(variante)
    v = str(valor).strip()
    if v in ("", "terminal", "default", "rich"):
        return None
    if v.startswith("@"):
        v = _ref(v, variante)
        if isinstance(v, dict):
            return hex_medible(v, variante)
    if _RE_HEX.match(v):
        return v.lower()
    m = _medidor()
    if m is not None:
        try:
            return m.resolver(color_rich(v) if v.startswith("ansi") else v, variante)
        except Exception:
            pass
    return _hex_de(_partes_color(v, variante)["color"], variante)


_MEDIDOR = []


def _medidor():
    """scripts/contraste_tema.py como libreria (por ruta; scripts/ no es
    paquete y no viaja en el wheel: sin el, los nombres ansi no se miden)."""
    if _MEDIDOR:
        return _MEDIDOR[0]
    mod = None
    try:
        import importlib.util
        from pathlib import Path
        ruta = Path(__file__).resolve().parents[2] / "scripts" / "contraste_tema.py"
        if ruta.exists():
            spec = importlib.util.spec_from_file_location("contraste_tema", ruta)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.resolver("bold cyan", "oscuro")   # prueba: necesita captura_terminal_png
    except Exception:
        mod = None
    _MEDIDOR.append(mod)
    return mod


def _lin(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def contraste(hex_fg: str, hex_bg: str) -> float:
    """Ratio WCAG 2.1 (la misma formula que scripts/contraste_tema.py)."""
    def lum(h):
        r, g, b = (int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))
        return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)
    a, b = lum(hex_fg), lum(hex_bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def _aclarar(hex_base: str, f: float, variante: str) -> str:
    """Color del glow derivado: hacia blanco en fondo oscuro, hacia NEGRO en
    claro (un glow mas claro sobre fondo claro vuelve invisible el elemento)."""
    hacia = "#000000" if variante == "claro" else "#ffffff"
    return _mezclar(hex_base, hacia, f)


# ---------------------------------------------------------------------------
# 5. Glifos y textos
# ---------------------------------------------------------------------------
def _usar_ascii() -> bool:
    """COGNIA_ASCII=1 fuerza ASCII, =0 fuerza Unicode; sin la variable manda
    el encoding REAL de stdout (mismo criterio que render_tools.usar_ascii)."""
    v = os.environ.get("COGNIA_ASCII", "").strip()
    if v == "1":
        return True
    if v == "0":
        return False
    return False


def _codificable(s: str) -> bool:
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        s.encode(enc)
        return True
    except Exception:
        return False


def _elegir_glifo(est: Estilo, default: Estilo) -> str:
    """El glifo que sale por pantalla: el declarado si el encoding lo aguanta,
    si no el ascii, si no el default (y su ascii)."""
    unicode = est.glifo if est.glifo is not None else default.glifo
    ascii_ = est.glifo_ascii if est.glifo_ascii is not None else default.glifo_ascii
    if unicode is None:
        return ascii_ or ""
    if _usar_ascii() and ascii_:
        return ascii_
    if _codificable(unicode):
        return unicode
    if ascii_ and _codificable(ascii_):
        return ascii_
    if default.glifo and _codificable(default.glifo):
        return default.glifo
    return default.glifo_ascii or ""


def glifo(id: str, estado: str | None = None) -> str:
    """Glifo o glifo_ascii segun sys.stdout.encoding (patron _FLECHA de cli).
    Bajo COGNIA_REMOTO=1 los contrato_remoto devuelven el default."""
    e = elemento(id)
    est = e.default if (_remoto() and e.contrato_remoto) else estilo_de(id)
    if estado:
        sub = est.estados.get(estado)
        sub_def = e.default.estados.get(estado)
        if sub is not None and (sub.glifo is not None or (sub_def and sub_def.glifo is not None)):
            return _elegir_glifo(sub, sub_def or Estilo())
    return _elegir_glifo(est, e.default)


def texto(id: str, clave: str | None = None) -> str:
    """Texto editable de un elemento. Con textos multiples (dict) la clave es
    obligatoria y desconocida = KeyError ruidoso con las claves validas.
    Bajo COGNIA_REMOTO=1 los contrato_remoto devuelven el default."""
    e = elemento(id)
    est = e.default if (_remoto() and e.contrato_remoto) else estilo_de(id)
    t = est.texto
    if isinstance(t, dict):
        if clave is None:
            raise KeyError(f"{id}: texto multiple, pide una clave: {', '.join(t)}")
        if clave not in t:
            raise KeyError(f"{id}: clave de texto desconocida '{clave}'; tiene: {', '.join(t)}")
        return str(t[clave])
    if clave is not None and clave != "texto":
        raise KeyError(f"{id}: tiene un solo texto (sin clave)")
    return "" if t is None else str(t)


def textos(id: str) -> dict:
    """Todos los textos de un elemento como dict (uno solo -> {'texto': ...})."""
    t = estilo_de(id).texto
    if isinstance(t, dict):
        return dict(t)
    return {"texto": "" if t is None else str(t)}


def visible(id: str) -> bool:
    v = estilo_de(id).visible
    return True if v is None else bool(v)


def separador(id: str) -> str:
    """El ' · ' (o ' | ' en ASCII) del elemento; '' si no lo tiene."""
    s = estilo_de(id).separador
    if s is None:
        return ""
    if not _codificable(s) or (_usar_ascii() and s == " · "):
        return " | "
    return s


def caja(id: str):
    """rich.box.* para banner.marco / panel.borde ('none' -> None)."""
    nombre = estilo_de(id).glifo or "rounded"
    if nombre == "none":
        return None
    from rich import box
    return {"rounded": box.ROUNDED, "square": box.SQUARE, "heavy": box.HEAVY,
            "double": box.DOUBLE}[nombre]


# ---------------------------------------------------------------------------
# 6. Resolucion completa
# ---------------------------------------------------------------------------
def _resolver(id: str, est: Estilo, default: Estilo, variante: str,
              padre: EstiloResuelto | None = None) -> EstiloResuelto:
    partes = _partes_color(est.color, variante)
    fondo = _partes_color(est.fondo, variante)["color"]
    token = ""
    for c in (est.color, default.color):
        if isinstance(c, str) and c.startswith("@token."):
            token = c[len("@token."):]
            break
    negrita = est.negrita if est.negrita is not None else partes["bold"]
    italica = est.italica if est.italica is not None else partes["italic"]
    subrayado = est.subrayado if est.subrayado is not None else partes["underline"]
    color = partes["color"]
    if padre is not None:
        # un sub-estado hereda del padre lo que no declara
        if est.color is None:
            color = padre.color
            token = token or padre.token
        if est.fondo is None:
            fondo = padre.fondo
        if est.negrita is None and not partes["bold"]:
            negrita = padre.negrita
        if est.italica is None and not partes["italic"]:
            italica = padre.italica
    glow = est.glow or Glow()
    if glow.color:
        glow_color = _partes_color(glow.color, variante)["color"] or ""
    else:
        base = color if color.startswith("#") else (
            "#1f2328" if variante == "claro" else paleta.SEMANTICO["texto"])
        glow_color = _aclarar(base, 0.6, variante)
    if glow_color and not glow_color.startswith("#"):
        glow_color = _hex_de(glow_color, variante) or _aclarar(
            paleta.SEMANTICO["texto"], 0.6, variante)
    gradiente = None
    if est.gradiente:
        gradiente = tuple(resolver_color(g, variante) for g in est.gradiente)
    return EstiloResuelto(
        id=id, variante=variante, texto=est.texto, color=color, fondo=fondo,
        negrita=bool(negrita), italica=bool(italica), subrayado=bool(subrayado),
        tenue=partes["dim"], glow_color=glow_color, glow_intensidad=glow.intensidad,
        animacion=est.animacion or Animacion(),
        glifo=_elegir_glifo(est, default) if (est.glifo or default.glifo or est.glifo_ascii) else "",
        posicion=est.posicion, alineacion=est.alineacion,
        visible=True if est.visible is None else bool(est.visible),
        gradiente=gradiente, separador=est.separador, token=token)


def estilo_resuelto(id: str, variante: str | None = None) -> EstiloResuelto:
    """Colores en hex/ansi, glifo decidido por encoding, booleanos decididos,
    glow.color derivado; `estados` con los sub-estados resueltos (heredan del
    padre lo que no declaran)."""
    variante = variante or variante_activa()
    e = elemento(id)
    est = estilo_de(id)
    if _remoto() and e.contrato_remoto:
        est = dataclasses.replace(est, texto=e.default.texto, glifo=e.default.glifo,
                                  glifo_ascii=e.default.glifo_ascii)
    padre = _resolver(id, est, e.default, variante)
    subs = {}
    for nombre in e.estados:
        sub = est.estados.get(nombre, Estilo())
        sub_def = e.default.estados.get(nombre, Estilo())
        subs[nombre] = _resolver(f"{id}.{nombre}", sub, sub_def, variante, padre=padre)
    return dataclasses.replace(padre, estados=subs)


# ---------------------------------------------------------------------------
# 7. Salidas para los consumidores
# ---------------------------------------------------------------------------
# E2: los strings ACTUALES de prompt_toolkit (styles/defaults.py) para las
# clases que hasta hoy no tenian id. Se emiten tal cual mientras no haya
# override (byte-identico: PT los tenia ya por su default_ui_style).
PT_DEFAULTS_E2 = {
    "prompt.search": "noinherit",
    "prompt.search.text": "",
    "selected": "reverse",
    "validation-toolbar": "bg:#550000 #ffffff",
}
_VALIDATION_TOOLBAR = "bg:#550000 #ffffff"


def _pt(r: EstiloResuelto, con_color: bool = True, prefijo_fg: bool = False) -> str:
    """Fragmento de estilo PT a partir de un resuelto: '<color> bold italic
    underline bg:<fondo>'. Con prefijo_fg escribe 'fg:<color>'."""
    partes = []
    if con_color and r.color:
        partes.append(f"fg:{r.color}" if prefijo_fg else r.color)
    if r.negrita:
        partes.append("bold")
    if r.italica:
        partes.append("italic")
    if r.subrayado:
        partes.append("underline")
    if r.fondo:
        partes.append(f"bg:{r.fondo}")
    return " ".join(partes)


def clases_pt(variante: str | None = None) -> dict:
    """El dict que alimenta PTStyle.from_dict en cli._estilo_prompt. Sin
    overrides es EXACTAMENTE el literal de hoy + las 4 claves de E2 con los
    strings de prompt_toolkit; con overrides suma 'estado.<seccion>',
    'modo.<insignia>' y el fuzzymatch del menu."""
    variante = variante or variante_activa()
    R = lambda id: estilo_resuelto(id, variante)  # noqa: E731
    texto, marco, etiqueta, flecha = R("prompt.texto"), R("prompt.marco"), R("prompt.etiqueta"), R("prompt.flecha")
    barra, menu = R("barra.estado"), R("menu.completado")
    fondo_marco = f"bg:{marco.fondo}" if marco.fondo else "bg:default"
    d = {
        "": _pt(texto),
        "marco": _pt(marco),
        "cognia": _pt(etiqueta),
        "flecha": _pt(flecha),
        "bottom-toolbar": f"noreverse {fondo_marco} {marco.color}".rstrip(),
        "bottom-toolbar.text": f"noreverse {fondo_marco} {marco.color}".rstrip(),
        "estado": f"noreverse {'bg:' + barra.fondo if barra.fondo else 'bg:default'} "
                  f"{_pt(barra, con_color=True)}".rstrip(),
    }
    act, meta, meta_act = menu.estados["activo"], menu.estados["meta"], menu.estados["meta_activo"]
    d.update({
        "completion-menu.completion": f"bg:{menu.fondo} fg:{menu.color}" + (" bold" if menu.negrita else ""),
        "completion-menu.completion.current": f"bg:{act.fondo} fg:{act.color}" + (" bold" if act.negrita else ""),
        "completion-menu.meta.completion": f"bg:{meta.fondo} fg:{meta.color}",
        "completion-menu.meta.completion.current": f"bg:{meta_act.fondo} fg:{meta_act.color}",
        "scrollbar.background": f"bg:{menu.estados['scrollbar'].fondo}",
        "scrollbar.button": f"bg:{menu.estados['scrollbar_boton'].fondo}",
    })
    # E2
    busq, sel = R("prompt.busqueda"), R("prompt.seleccion")
    if tiene_override("prompt.busqueda"):
        d["prompt.search"] = ("noinherit " + _pt(busq, prefijo_fg=True)).strip()
        d["prompt.search.text"] = _pt(busq, prefijo_fg=True)
    else:
        d["prompt.search"] = PT_DEFAULTS_E2["prompt.search"]
        d["prompt.search.text"] = PT_DEFAULTS_E2["prompt.search.text"]
    d["selected"] = _pt(sel, prefijo_fg=True) if tiene_override("prompt.seleccion") else PT_DEFAULTS_E2["selected"]
    d["validation-toolbar"] = _VALIDATION_TOOLBAR
    # clases nuevas SOLO con override (sin override el dict es el literal)
    if tiene_override("barra.estado.secciones"):
        secc = R("barra.estado.secciones")
        for nombre, sub in secc.estados.items():
            d[f"estado.{nombre.replace('_', '-')}"] = f"noreverse bg:default {_pt(sub)}".rstrip()
    if tiene_override("barra.modo"):
        modo = R("barra.modo")
        for nombre, sub in modo.estados.items():
            d[f"modo.{nombre}"] = f"noreverse bg:default {_pt(sub)}".rstrip()
    coin = menu.estados["coincidencia"]
    if coin.color or coin.negrita:
        d["completion-menu.completion fuzzymatch.inside"] = _pt(coin, prefijo_fg=True)
        d["completion-menu.completion fuzzymatch.outside"] = f"fg:{menu.color}"
    return d


def _estilo_rich_de(r: EstiloResuelto, token_base: str | None = None) -> str:
    """Estilo de rich para el Theme. Con `token_base` (el estilo del token
    cuando el COLOR no se toco, p.ej. 'dim white') se conserva ese string y
    solo se suman los modificadores: un hex ya mezclado por 'dim' no se
    vuelve a atenuar."""
    partes = []
    if r.negrita:
        partes.append("bold")
    if r.italica:
        partes.append("italic")
    if r.subrayado:
        partes.append("underline")
    if token_base is not None:
        from rich.style import Style
        base = Style.parse(token_base)
        extra = Style(bold=r.negrita or None, italic=r.italica or None,
                      underline=r.subrayado or None,
                      bgcolor=r.fondo if r.fondo else None)
        return str(base + extra)
    partes.append(color_rich(r.color))
    if r.fondo:
        partes.append(f"on {r.fondo}")
    return " ".join(partes)


# Sub-estado de respuesta.markdown -> tokens del Theme que retine. 'link'
# retine los DOS: con hyperlinks (el default) rich pinta el texto del enlace
# con 'markdown.link_url' y solo sin hyperlinks con 'markdown.link'.
_MARKDOWN_TOKEN = {"h1": ("markdown.h1",), "h2": ("markdown.h2",), "h3": ("markdown.h3",),
                   "code": ("markdown.code",), "link": ("markdown.link", "markdown.link_url"),
                   "strong": ("markdown.strong",), "em": ("markdown.em",),
                   "hr": ("markdown.hr",), "item": ("markdown.item",)}


def tema_rich(variante: str | None = None) -> dict:
    """paleta.tema_cli(variante) + overrides de tokens (TOKENS_POR_ELEMENTO)
    + markdown.*/rule.line SOLO si hay override. Sin overrides es IGUAL a
    paleta.tema_cli(variante)."""
    variante = variante or variante_activa()
    tema = dict(paleta.tema_cli(variante))
    tocados = set()
    for id, toks in TOKENS_POR_ELEMENTO.items():
        c = _cambios_de(id)
        if not any(k in c for k in ("color", "negrita", "italica", "subrayado", "fondo")):
            continue
        r = estilo_resuelto(id, variante)
        for tok in toks:
            if tok not in tocados:
                tema[tok] = _estilo_rich_de(r, None if "color" in c else tema[tok])
                tocados.add(tok)
    if tiene_override("respuesta.markdown"):
        r = estilo_resuelto("respuesta.markdown", variante)
        for clave, sub in r.estados.items():
            c = (_cambios_de("respuesta.markdown").get("estados") or {}).get(clave)
            if c:
                for tok in _MARKDOWN_TOKEN[clave]:
                    # como TOKENS_POR_ELEMENTO: con el color sin tocar se
                    # conserva el string del token de la paleta y solo se
                    # suman modificadores; un sub-estado sin token en la
                    # paleta (strong/em/item) se declara de cero, como antes
                    tema[tok] = _estilo_rich_de(sub, None if "color" in c else tema.get(tok))
    if any(k in _cambios_de("separador.regla") for k in ("color", "negrita")):
        tema["rule.line"] = _estilo_rich_de(estilo_resuelto("separador.regla", variante))
    if any(k in _cambios_de("panel.borde") for k in ("color",)):
        tema["panel.border"] = _estilo_rich_de(estilo_resuelto("panel.borde", variante))
    return tema


# ---------------------------------------------------------------------------
# 8. Validacion RUIDOSA
# ---------------------------------------------------------------------------
def _sugerir(nombre: str, opciones) -> str:
    p = difflib.get_close_matches(nombre, list(opciones), n=3, cutoff=0.5)
    return f" (parecidos: {', '.join(p)})" if p else ""


def _validar_color(valor, id: str, campo: str, avisos: list) -> bool:
    """Color valido = resuelve en las TRES variantes. Devuelve True si vale."""
    if isinstance(valor, dict):
        faltan = [v for v in ORDEN_VARIANTES if v not in valor]
        if faltan:
            avisos.append(Aviso("error", f"{campo}: color por variante sin {', '.join(faltan)}", id))
            return False
    elif not isinstance(valor, str):
        avisos.append(Aviso("error", f"{campo}: un color es un string o un dict por variante, "
                                     f"no {type(valor).__name__}", id))
        return False
    for variante in ORDEN_VARIANTES:
        try:
            _partes_color(valor, variante)
        except KeyError as exc:
            avisos.append(Aviso("error", f"{campo}: referencia desconocida {valor!r}: {exc}", id))
            return False
        except Exception as exc:
            avisos.append(Aviso("error", f"{campo}: color invalido {valor!r} "
                                         f"({type(exc).__name__}: {exc}); vale #rrggbb, @rampa.x, "
                                         f"@semantico.x, @superficie.x, @menu.x, @diff.x, @token.x, "
                                         f"@mi.x, terminal", id))
            return False
    return True


def _validar_contraste(id: str, e: Elemento, valor, campo: str, avisos: list,
                       fondo=None) -> None:
    """Aviso si el color no llega al piso sobre el fondo de cada variante (o
    sobre el fondo PROPIO del elemento, si lo declara: el menu flotante se lee
    sobre su azul, no sobre la terminal)."""
    piso = PISO_GRAFICO if e.grafico else PISO_TEXTO
    flojos = []
    for variante in ORDEN_VARIANTES:
        try:
            hexa = hex_medible(valor, variante)
            bg = _partes_color(fondo, variante)["color"] if fondo else ""
        except Exception:
            return
        if hexa is None:
            continue
        fondo_hex = bg if bg.startswith("#") else paleta.FONDO_VARIANTE[variante]
        ratio = contraste(hexa, fondo_hex)
        if ratio < piso:
            flojos.append(f"{ratio:.1f}:1 en {variante}".replace(".", ","))
    if flojos:
        avisos.append(Aviso("aviso", f"{campo}: contraste bajo el piso {str(piso).replace('.', ',')} "
                                     f"({'; '.join(flojos)})", id))


def _validar_estilo(id: str, e: Elemento, d: dict, avisos: list, prefijo: str = "",
                    en_estado: bool = False) -> None:
    if not isinstance(d, dict):
        avisos.append(Aviso("error", f"{prefijo or 'elemento'}: se esperaba un objeto, no "
                                     f"{type(d).__name__}", id))
        return
    soportadas = sorted(c.value for c in e.caps)
    for campo, valor in d.items():
        ruta = f"{prefijo}{campo}"
        if campo == "estados":
            if not e.estados:
                avisos.append(Aviso("error", f"{ruta}: '{id}' no tiene sub-estados", id))
                continue
            if not isinstance(valor, dict):
                avisos.append(Aviso("error", f"{ruta}: se esperaba un objeto", id))
                continue
            for nombre, sub in valor.items():
                if nombre not in e.estados:
                    avisos.append(Aviso("error", f"{ruta}.{nombre}: sub-estado desconocido; tiene: "
                                                 f"{', '.join(e.estados)}{_sugerir(nombre, e.estados)}", id))
                    continue
                _validar_estilo(id, e, sub, avisos, f"{ruta}.{nombre}.", en_estado=True)
            continue
        if campo not in _CAP_DE_CAMPO:
            avisos.append(Aviso("error", f"{ruta}: propiedad desconocida; validas: "
                                         f"{', '.join(_CAMPOS_ESTILO)}{_sugerir(campo, _CAMPOS_ESTILO)}", id))
            continue
        cap = _CAP_DE_CAMPO[campo]
        if cap not in e.caps and not (en_estado and campo in ("color", "fondo", "glifo", "glifo_ascii", "negrita")):
            avisos.append(Aviso("error", f"'{id}' no tiene '{campo}'; tiene: {', '.join(soportadas)}", id))
            continue
        if campo in ("color", "fondo"):
            if _validar_color(valor, id, ruta, avisos):
                if campo == "color" and valor not in ("rich",):
                    _validar_contraste(id, e, valor, ruta, avisos,
                                       fondo=d.get("fondo", e.default.fondo))
        elif campo in ("negrita", "italica", "subrayado", "visible"):
            if not isinstance(valor, bool):
                avisos.append(Aviso("error", f"{ruta}: se esperaba true/false, no {valor!r}", id))
            elif campo == "visible" and id == "banner.arte" and valor is False:
                avisos.append(Aviso("aviso", "identidad: el banner va por defecto (se guarda, "
                                             "pero es la marca de Cognia)", id))
        elif campo == "texto":
            if isinstance(e.default.texto, dict):
                if not isinstance(valor, dict):
                    avisos.append(Aviso("error", f"{ruta}: '{id}' tiene varios textos; se esperaba un "
                                                 f"objeto con claves {', '.join(e.default.texto)}", id))
                else:
                    for k, v in valor.items():
                        if k not in e.default.texto:
                            avisos.append(Aviso("error", f"{ruta}.{k}: clave de texto desconocida; tiene: "
                                                         f"{', '.join(e.default.texto)}", id))
                        elif not isinstance(v, str):
                            avisos.append(Aviso("error", f"{ruta}.{k}: se esperaba un string", id))
            elif not isinstance(valor, str):
                avisos.append(Aviso("error", f"{ruta}: se esperaba un string", id))
        elif campo == "glow":
            if not isinstance(valor, dict):
                avisos.append(Aviso("error", f"{ruta}: se esperaba un objeto {{color, intensidad}}", id))
                continue
            for k, v in valor.items():
                if k not in _CAMPOS_GLOW:
                    avisos.append(Aviso("error", f"{ruta}.{k}: desconocido; vale: {', '.join(_CAMPOS_GLOW)}", id))
                elif k == "intensidad" and (not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= 3):
                    avisos.append(Aviso("error", f"{ruta}.intensidad: {v!r} fuera de 0..3", id))
                elif k == "color" and v is not None:
                    _validar_color(v, id, f"{ruta}.color", avisos)
        elif campo == "animacion":
            if not isinstance(valor, dict):
                avisos.append(Aviso("error", f"{ruta}: se esperaba un objeto", id))
                continue
            for k, v in valor.items():
                if k not in _CAMPOS_ANIM:
                    avisos.append(Aviso("error", f"{ruta}.{k}: desconocido; vale: {', '.join(_CAMPOS_ANIM)}", id))
                elif k in ("activa", "solo_al_llegar") and not isinstance(v, bool):
                    avisos.append(Aviso("error", f"{ruta}.{k}: se esperaba true/false", id))
                elif k == "tipo" and v not in TIPOS_ANIMACION:
                    avisos.append(Aviso("error", f"{ruta}.tipo: {v!r} no es {' | '.join(TIPOS_ANIMACION)}", id))
                elif k == "direccion" and v not in DIRECCIONES:
                    avisos.append(Aviso("error", f"{ruta}.direccion: {v!r} no es {' | '.join(DIRECCIONES)}", id))
                elif k == "velocidad" and (not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= 5):
                    avisos.append(Aviso("error", f"{ruta}.velocidad: {v!r} fuera de 1..5", id))
                elif k == "ancho" and (not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= 20):
                    avisos.append(Aviso("error", f"{ruta}.ancho: {v!r} fuera de 1..20", id))
                elif k == "repetir" and (not isinstance(v, int) or isinstance(v, bool) or v < 0):
                    avisos.append(Aviso("error", f"{ruta}.repetir: {v!r} (0 = infinito, N = N barridos)", id))
                elif k == "cada_s" and (not isinstance(v, (int, float)) or isinstance(v, bool) or v < 0):
                    avisos.append(Aviso("error", f"{ruta}.cada_s: {v!r} (segundos >= 0)", id))
            if valor.get("activa") and not e.vivo:
                avisos.append(Aviso("aviso", "no animable: linea impresa; se guarda pero no corre", id))
        elif campo in ("glifo", "glifo_ascii"):
            if not isinstance(valor, str):
                avisos.append(Aviso("error", f"{ruta}: se esperaba un string", id))
            elif e.glifos and campo == "glifo" and valor not in e.glifos:
                avisos.append(Aviso("error", f"{ruta}: {valor!r} no es {' | '.join(e.glifos)}", id))
            elif campo == "glifo" and not e.glifos and not _codificable(valor):
                enc = getattr(sys.stdout, "encoding", None) or "utf-8"
                ascii_ = d.get("glifo_ascii") or e.default.glifo_ascii
                avisos.append(Aviso("aviso", f"{ruta}: {valor!r} no se codifica en {enc}; se usara "
                                             f"{ascii_!r}" if ascii_ else
                                             f"{ruta}: {valor!r} no se codifica en {enc} y no hay "
                                             f"glifo_ascii; se usara el default", id))
        elif campo == "posicion":
            if valor not in e.posiciones:
                avisos.append(Aviso("error", f"{ruta}: {valor!r} no es {' | '.join(e.posiciones)}", id))
        elif campo == "alineacion":
            if valor not in e.alineaciones:
                avisos.append(Aviso("error", f"{ruta}: {valor!r} no es {' | '.join(e.alineaciones)}", id))
        elif campo == "gradiente":
            if not (isinstance(valor, (list, tuple)) and len(valor) == 2):
                avisos.append(Aviso("error", f"{ruta}: se esperaba [desde, hasta]", id))
            else:
                for i, c in enumerate(valor):
                    _validar_color(c, id, f"{ruta}[{i}]", avisos)
        elif campo == "separador":
            if not isinstance(valor, str):
                avisos.append(Aviso("error", f"{ruta}: se esperaba un string", id))


def validar(doc: dict) -> list:
    """Avisos (nivel 'error' = se rechaza; 'aviso' = se acepta y se avisa)
    de un documento con la forma de estilo.json. Lista vacia = limpio."""
    avisos: list = []
    if not isinstance(doc, dict):
        return [Aviso("error", f"el documento tiene que ser un objeto JSON, no {type(doc).__name__}")]
    ver = doc.get("version", VERSION_FICHERO)
    if not isinstance(ver, int) or isinstance(ver, bool):
        avisos.append(Aviso("error", f"version: se esperaba un entero, no {ver!r}"))
    elif ver > VERSION_FICHERO:
        avisos.append(Aviso("error", f"fichero de una version mas nueva ({ver} > {VERSION_FICHERO}); "
                                     f"actualiza cognia"))
    conocidas = ("$schema", "version", "nombre", "nota", "paleta", "global", "elementos")
    for k in doc:
        if k not in conocidas:
            avisos.append(Aviso("aviso", f"clave desconocida '{k}' (se conserva al guardar)"))
    pal = doc.get("paleta") or {}
    if not isinstance(pal, dict):
        avisos.append(Aviso("error", "paleta: se esperaba un objeto nombre -> color"))
        pal = {}
    previa = _estado["paleta_local"]
    _estado["paleta_local"] = {k: v for k, v in pal.items()}  # para que @mi.* resuelva
    try:
        for nombre, valor in pal.items():
            if not isinstance(nombre, str) or not nombre.isidentifier():
                avisos.append(Aviso("error", f"paleta.{nombre}: el nombre tiene que ser un identificador"))
            elif isinstance(valor, str) and valor.startswith("@mi."):
                avisos.append(Aviso("error", f"paleta.{nombre}: una entrada de la paleta no puede apuntar a @mi.*"))
            else:
                _validar_color(valor, "", f"paleta.{nombre}", avisos)
        glob = doc.get("global") or {}
        if not isinstance(glob, dict):
            avisos.append(Aviso("error", "global: se esperaba un objeto"))
        else:
            for k, v in glob.items():
                if k == "fps":
                    if not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= 30:
                        avisos.append(Aviso("error", f"global.fps: {v!r} fuera de 1..30"))
                elif k == "respuesta_sangria":
                    if not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= 8:
                        avisos.append(Aviso("error", f"global.respuesta_sangria: {v!r} fuera de 0..8"))
                elif k == "glifos":
                    if v not in GLIFOS_GLOBAL:
                        avisos.append(Aviso("error", f"global.glifos: {v!r} no es {' | '.join(GLIFOS_GLOBAL)}"))
                else:
                    avisos.append(Aviso("aviso", f"global.{k}: clave desconocida (se conserva)"))
        elems = doc.get("elementos") or {}
        if not isinstance(elems, dict):
            avisos.append(Aviso("error", "elementos: se esperaba un objeto id -> propiedades"))
            elems = {}
        for id, props in elems.items():
            if id not in REGISTRO:
                avisos.append(Aviso("error", f"elemento desconocido '{id}'{_sugerir(id, REGISTRO)}", id))
                continue
            _validar_estilo(id, REGISTRO[id], props, avisos)
    finally:
        _estado["paleta_local"] = previa
    return avisos


def errores(avisos: list) -> list:
    return [a for a in avisos if a.nivel == "error"]


# ---------------------------------------------------------------------------
# 9. Escritura en memoria
# ---------------------------------------------------------------------------
_BOOL_TXT = {"on": True, "off": False, "true": True, "false": False, "si": True, "no": False,
             "1": True, "0": False}


def _convertir(valor, campo: str, sub: str | None):
    """Un valor tecleado ('on', '2', 'jarvis') al tipo del campo."""
    if not isinstance(valor, str):
        return valor
    v = valor.strip()
    if campo in ("negrita", "italica", "subrayado", "visible") or (campo == "animacion" and sub in ("activa", "solo_al_llegar")):
        if v.lower() in _BOOL_TXT:
            return _BOOL_TXT[v.lower()]
        return valor
    if (campo == "glow" and sub == "intensidad") or (campo == "animacion" and sub in ("velocidad", "ancho", "repetir")):
        try:
            return int(v)
        except ValueError:
            return valor
    if campo == "animacion" and sub == "cada_s":
        try:
            return float(v)
        except ValueError:
            return valor
    if campo == "gradiente":
        return [p.strip() for p in v.split(",")]
    return valor


def poner(id: str, prop: str, valor) -> list:
    """Valida y escribe EN MEMORIA (no guarda). `prop` = 'texto' |
    'glow.intensidad' | 'animacion.activa' | 'estados.activo.fondo' |
    'texto.titulo'. Devuelve los avisos; con un 'error' NO escribe."""
    e = elemento(id)
    partes = prop.split(".")
    campo = partes[0]
    # el campo REAL (dentro de un sub-estado la ruta es estados.<n>.<campo>[.<sub>])
    hoja = partes[2:] if campo == "estados" else partes
    valor = _convertir(valor, hoja[0] if hoja else "", hoja[1] if len(hoja) > 1 else None)
    # construir el dict anidado {campo: {...: valor}}
    anidado = valor
    for k in reversed(partes[1:]):
        anidado = {k: anidado}
    cambio = {campo: anidado}
    if campo == "texto" and len(partes) == 1 and isinstance(e.default.texto, dict):
        return [Aviso("error", f"'{id}' tiene varios textos: usa texto.<clave> "
                               f"({', '.join(e.default.texto)})", id)]
    avisos = validar({"version": VERSION_FICHERO, "elementos": {id: cambio}})
    if errores(avisos):
        return avisos
    _estado["overrides"][id] = _fusionar_dicts(_estado["overrides"].get(id) or {}, cambio)
    _subir_version()
    return avisos


def reset(id: str | None = None) -> None:
    """Vuelve al default EN MEMORIA (y quita lo del fichero cargado para ese
    id); sin id, todo. No toca el disco: eso es guardar() (P2)."""
    if id is None:
        _estado["overrides"].clear()
        _estado["doc"] = {}
        _estado["paleta_local"] = {}
    else:
        elemento(id)
        _estado["overrides"].pop(id, None)
        (_estado["doc"].get("elementos") or {}).pop(id, None)
    _subir_version()


def _aplicar_doc(doc: dict) -> None:
    """Instala un documento validado como capa 'fichero' (lo usa cargar, P2)."""
    _estado["doc"] = doc
    _estado["paleta_local"] = dict(doc.get("paleta") or {})
    _subir_version()


# ---------------------------------------------------------------------------
# 10. El fichero: ~/.cognia/estilo.json, .bak, presets, export, hot reload
# ---------------------------------------------------------------------------
# Cascada (seccion 2.1): REGISTRO.default <- estilo.json <- memoria. Un preset
# se CARGA copiandolo a estilo.json (tras el .bak): no hay "preset activo"
# como puntero, una sola fuente de verdad. Las rutas son atributos del modulo
# para que los tests las apunten a un tmp_path.
import json  # noqa: E402
import shutil  # noqa: E402
from pathlib import Path  # noqa: E402

DIR_COGNIA = Path.home() / ".cognia"
RUTA_ESTILO = DIR_COGNIA / "estilo.json"
DIR_PRESETS = DIR_COGNIA / "estilos"
DIR_PRESETS_PAQUETE = Path(__file__).resolve().parent / "presets"
RUTA_SCHEMA = Path(__file__).resolve().parent / "estilo.schema.json"
PRESETS_PAQUETE = ("clasico", "barra-color", "neon", "sobrio", "ansi16")
_CLAVES_DOC = ("$schema", "version", "nombre", "nota", "paleta", "global", "elementos")


class EstiloInvalido(ValueError):
    """El fichero no se puede instalar: JSON roto o validar() con errores.
    `.avisos` trae la lista (los 'error' primero) y `.ruta` el fichero."""

    def __init__(self, ruta, avisos):
        self.ruta = ruta
        self.avisos = list(avisos)
        super().__init__(f"{ruta}: " + "; ".join(str(a) for a in self.avisos[:5])
                         + (f" (+{len(self.avisos) - 5} mas)" if len(self.avisos) > 5 else ""))


def _ruta(ruta=None) -> Path:
    return Path(ruta) if ruta else RUTA_ESTILO


def _mtime(ruta: Path):
    try:
        return ruta.stat().st_mtime_ns
    except OSError:
        return None


# migraciones: version N -> N+1 (una funcion por salto). Vacio en la version 1.
_MIGRACIONES: dict = {}


def _migrar(doc: dict) -> dict:
    """Un fichero sin 'version' se trata como 1; se aplican los saltos hasta
    VERSION_FICHERO. Una version MAYOR no se migra (validar la rechaza)."""
    doc = dict(doc)
    ver = doc.get("version")
    if ver is None:
        ver = 1
    if not isinstance(ver, int) or isinstance(ver, bool):
        return doc
    while ver < VERSION_FICHERO:
        paso = _MIGRACIONES.get(ver)
        if paso is None:
            break
        doc = paso(doc)
        ver += 1
        doc["version"] = ver
    doc.setdefault("version", ver)
    return doc


def leer_doc(ruta) -> dict:
    """JSON del fichero (sin instalar ni validar). EstiloInvalido si esta roto."""
    ruta = Path(ruta)
    try:
        texto = ruta.read_text(encoding="utf-8")
    except OSError as exc:
        raise EstiloInvalido(ruta, [Aviso("error", f"no se puede leer: {exc}")]) from None
    try:
        doc = json.loads(texto)
    except ValueError as exc:
        raise EstiloInvalido(ruta, [Aviso("error", f"JSON invalido: {exc}")]) from None
    if not isinstance(doc, dict):
        raise EstiloInvalido(ruta, [Aviso("error", "el fichero tiene que ser un objeto JSON")])
    return doc


_ULTIMOS_AVISOS: list = []


def ultimos_avisos() -> list:
    """Los avisos (nivel 'aviso') de la ultima cargar()/cargar_preset()."""
    return list(_ULTIMOS_AVISOS)


def cargar(ruta=None) -> dict:
    """Instala ~/.cognia/estilo.json (o `ruta`) como capa 'fichero'. Sin
    fichero -> defaults y devuelve {}. Con errores de validacion NO instala
    nada y lanza EstiloInvalido (el CLI avisa por _aviso_degradado y arranca
    con defaults: nunca sin prompt). Los avisos no bloqueantes quedan en
    ultimos_avisos(). Descarta los overrides en memoria."""
    ruta = _ruta(ruta)
    _ULTIMOS_AVISOS.clear()
    if not ruta.exists():
        _estado["overrides"].clear()
        _aplicar_doc({})
        _estado["mtime"] = None
        _estado["recarga_pendiente"] = False
        return {}
    doc = _migrar(leer_doc(ruta))
    avisos = validar(doc)
    if errores(avisos):
        raise EstiloInvalido(ruta, sorted(avisos, key=lambda a: a.nivel != "error"))
    _ULTIMOS_AVISOS.extend(avisos)
    _estado["overrides"].clear()
    _aplicar_doc(doc)
    _estado["mtime"] = _mtime(ruta)
    _estado["recarga_pendiente"] = False
    return doc


def _diff_contra_default(id: str, cambios_dict: dict) -> dict:
    """Deja SOLO las hojas que difieren del default del elemento (una clave
    puesta al mismo valor que el default no se escribe)."""
    base = _a_dict(elemento(id).default)

    def _podar(c, b):
        out = {}
        for k, v in c.items():
            bv = b.get(k) if isinstance(b, dict) else None
            if isinstance(v, dict) and isinstance(bv, dict):
                sub = _podar(v, bv)
                if sub:
                    out[k] = sub
            elif isinstance(v, dict) and bv is None:
                sub = _podar(v, {})
                if sub:
                    out[k] = sub
            elif isinstance(v, list) and isinstance(bv, (list, tuple)):
                if list(v) != list(bv):
                    out[k] = list(v)
            elif v != bv:
                out[k] = v
        return out
    return _podar(cambios_dict, base)


def documento() -> dict:
    """El estado ACTUAL con la forma del fichero: fichero cargado + memoria,
    solo lo que difiere del default, claves desconocidas conservadas."""
    previo = _estado["doc"]
    doc = {}
    for k in _CLAVES_DOC:
        if k in previo and k != "elementos":
            doc[k] = previo[k]
    for k, v in previo.items():          # claves desconocidas: se conservan
        if k not in _CLAVES_DOC:
            doc[k] = v
    doc["version"] = VERSION_FICHERO
    elems = {}
    for id in REGISTRO:
        c = _cambios_de(id)
        if not c:
            continue
        d = _diff_contra_default(id, c)
        if d:
            elems[id] = d
    doc["elementos"] = elems
    return doc


def _escribir_json(ruta: Path, doc: dict) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def guardar(ruta=None) -> Path:
    """Escribe documento() en estilo.json (o `ruta`), con copia previa en
    .bak si ya existia. La memoria pasa a ser la capa 'fichero' (los
    overrides se funden). Devuelve la ruta escrita."""
    ruta = _ruta(ruta)
    doc = documento()
    doc["$schema"] = str(RUTA_SCHEMA)
    if ruta.exists():
        shutil.copyfile(ruta, ruta.with_suffix(ruta.suffix + ".bak"))
    _escribir_json(ruta, doc)
    if ruta == RUTA_ESTILO:
        _estado["overrides"].clear()
        _aplicar_doc(doc)
        _estado["mtime"] = _mtime(ruta)
        _estado["recarga_pendiente"] = False
    return ruta


def deshacer(ruta=None) -> bool:
    """Restaura estilo.json.bak (intercambiandolo con el actual, asi un
    segundo deshacer vuelve) y lo carga. False si no hay .bak."""
    ruta = _ruta(ruta)
    bak = ruta.with_suffix(ruta.suffix + ".bak")
    if not bak.exists():
        return False
    if ruta.exists():
        tmp = ruta.with_suffix(ruta.suffix + ".deshacer")
        shutil.copyfile(ruta, tmp)
        shutil.copyfile(bak, ruta)
        shutil.move(str(tmp), str(bak))
    else:
        shutil.copyfile(bak, ruta)
    cargar(ruta)
    return True


def _ruta_preset(nombre_o_ruta) -> Path:
    """Nombre -> ~/.cognia/estilos/<n>.json o el del paquete; una ruta
    explicita solo bajo $HOME (regla 2.4) y tiene que existir."""
    s = str(nombre_o_ruta).strip()
    if not s:
        raise ValueError("preset sin nombre")
    parece_ruta = any(ch in s for ch in "/\\") or s.lower().endswith(".json")
    if parece_ruta:
        ruta = Path(s).expanduser().resolve()
        try:
            ruta.relative_to(Path.home().resolve())
        except ValueError:
            raise ValueError(f"solo se cargan ficheros bajo {Path.home()}: {ruta}") from None
        if not ruta.exists():
            raise ValueError(f"no existe: {ruta}")
        return ruta
    if not all(c.isalnum() or c in "-_" for c in s):
        raise ValueError(f"nombre de preset invalido '{s}' (letras, numeros, - y _)")
    for base in (DIR_PRESETS, DIR_PRESETS_PAQUETE):
        ruta = base / f"{s}.json"
        if ruta.exists():
            return ruta
    raise ValueError(f"preset desconocido '{s}'; hay: {', '.join(listar_presets())}"
                     + _sugerir(s, listar_presets()))


def cargar_preset(nombre_o_ruta, ruta_destino=None) -> dict:
    """Valida el preset y lo COPIA a estilo.json (tras el .bak); luego
    cargar(). Un preset invalido lanza EstiloInvalido y no toca nada."""
    origen = _ruta_preset(nombre_o_ruta)
    doc = _migrar(leer_doc(origen))
    avisos = validar(doc)
    if errores(avisos):
        raise EstiloInvalido(origen, sorted(avisos, key=lambda a: a.nivel != "error"))
    destino = _ruta(ruta_destino)
    if destino.exists():
        shutil.copyfile(destino, destino.with_suffix(destino.suffix + ".bak"))
    doc.setdefault("nombre", origen.stem)
    doc["$schema"] = str(RUTA_SCHEMA)
    _escribir_json(destino, doc)
    return cargar(destino)


def guardar_preset(nombre: str) -> Path:
    """documento() como ~/.cognia/estilos/<nombre>.json (autocontenido)."""
    nombre = str(nombre).strip()
    if not nombre or not all(c.isalnum() or c in "-_" for c in nombre):
        raise ValueError(f"nombre de preset invalido '{nombre}' (letras, numeros, - y _)")
    doc = documento()
    doc["nombre"] = nombre
    doc["$schema"] = str(RUTA_SCHEMA)
    ruta = DIR_PRESETS / f"{nombre}.json"
    _escribir_json(ruta, doc)
    return ruta


def listar_presets() -> list:
    """Nombres: primero los del dueno (~/.cognia/estilos), luego los del
    paquete; sin repetir (el del dueno tapa al del paquete)."""
    vistos = []
    for base in (DIR_PRESETS, DIR_PRESETS_PAQUETE):
        try:
            nombres = sorted(p.stem for p in base.glob("*.json"))
        except OSError:
            nombres = []
        for n in nombres:
            if n not in vistos:
                vistos.append(n)
    return vistos


def presets_detalle() -> list:
    """[(nombre, ruta, 'dueno'|'paquete', nota)] para /estilo presets."""
    salida = []
    vistos = set()
    for base, origen in ((DIR_PRESETS, "dueno"), (DIR_PRESETS_PAQUETE, "paquete")):
        try:
            rutas = sorted(base.glob("*.json"))
        except OSError:
            rutas = []
        for r in rutas:
            if r.stem in vistos:
                continue
            vistos.add(r.stem)
            try:
                nota = str(leer_doc(r).get("nota", ""))
            except EstiloInvalido as exc:
                nota = f"INVALIDO: {exc.avisos[0].texto}"
            salida.append((r.stem, r, origen, nota))
    return salida


def exportar(ruta) -> Path:
    """Fichero AUTOCONTENIDO: los 50 elementos con su Estilo completo (con
    los @refs tal cual, para que siga obedeciendo a /tema), la paleta local y
    lo global; sin $schema ni nada dependiente de la maquina."""
    ruta = Path(ruta)
    doc = {"version": VERSION_FICHERO}
    previo = _estado["doc"]
    for k in ("nombre", "nota", "paleta", "global"):
        if k in previo:
            doc[k] = previo[k]
    doc["elementos"] = {id: _a_dict(estilo_de(id)) for id in REGISTRO}
    _escribir_json(ruta, doc)
    return ruta


def recargar_si_cambio(ruta=None) -> bool:
    """SOLO detecta (un stat) y marca la recarga como pendiente. E6: la
    reconstruccion de Console/renderer NO puede correr dentro del render de
    prompt_toolkit; el CLI llama aplicar_recarga() cuando el prompt devolvio.
    True si el fichero cambio (o aparecio/desaparecio) desde la ultima carga."""
    ruta = _ruta(ruta)
    actual = _mtime(ruta)
    if actual == _estado.get("mtime"):
        return _estado.get("recarga_pendiente", False)
    _estado["mtime_visto"] = actual
    _estado["recarga_pendiente"] = True
    return True


def recarga_pendiente() -> bool:
    return bool(_estado.get("recarga_pendiente", False))


def aplicar_recarga(ruta=None) -> dict:
    """cargar() de verdad (fuera del render). Devuelve el doc; EstiloInvalido
    si el fichero editado a mano esta mal (se sigue con lo cargado antes)."""
    ruta = _ruta(ruta)
    try:
        return cargar(ruta)
    except EstiloInvalido:
        # que no se reintente en cada redibujado: se registra el mtime malo
        _estado["mtime"] = _mtime(ruta)
        _estado["recarga_pendiente"] = False
        raise


_estado.setdefault("mtime", None)
_estado.setdefault("recarga_pendiente", False)


# ---------------------------------------------------------------------------
# 11. Style string (seccion 2.3): forma compacta para /estilo <id> "<string>"
# ---------------------------------------------------------------------------
# bold|nobold italic|noitalic underline|nounderline fg:<color> bg:<color>
# glow:<color>/<0-3> anim:<barrido|pulso><</>/<>>[velocidad][,ancho][,cada_s]
# noanim glifo:"<s>" ascii:"<s>" texto:"<s>" texto.<clave>:"<s>" pos:<enum>
# align:<enum> hidden|visible sep:"<s>"
# Lo que NO cabe en la gramatica (repetir, solo_al_llegar, estados, gradiente,
# colores por variante) va por JSON o por /estilo <id> <prop> <valor>.
_DIR_A_SIMBOLO = {"derecha": ">", "izquierda": "<", "ida_vuelta": "<>"}
_SIMBOLO_A_DIR = {v: k for k, v in _DIR_A_SIMBOLO.items()}


def _q(s: str) -> str:
    """Entrecomilla como shlex lo va a leer (round-trip exacto)."""
    import shlex
    return shlex.quote(s) if s else "''"


def a_style_string(estilo: Estilo) -> str:
    partes = []
    if estilo.negrita is not None:
        partes.append("bold" if estilo.negrita else "nobold")
    if estilo.italica is not None:
        partes.append("italic" if estilo.italica else "noitalic")
    if estilo.subrayado is not None:
        partes.append("underline" if estilo.subrayado else "nounderline")
    if isinstance(estilo.color, str):
        partes.append(f"fg:{estilo.color}")
    if isinstance(estilo.fondo, str):
        partes.append(f"bg:{estilo.fondo}")
    if estilo.glow is not None:
        partes.append(f"glow:{estilo.glow.color or ''}/{estilo.glow.intensidad}")
    if estilo.animacion is not None:
        a = estilo.animacion
        if not a.activa:
            partes.append("noanim")
        else:
            partes.append(f"anim:{a.tipo}{_DIR_A_SIMBOLO[a.direccion]}{a.velocidad},{a.ancho},{a.cada_s:g}")
    if estilo.glifo is not None:
        partes.append(f"glifo:{_q(estilo.glifo)}")
    if estilo.glifo_ascii is not None:
        partes.append(f"ascii:{_q(estilo.glifo_ascii)}")
    if isinstance(estilo.texto, str):
        partes.append(f"texto:{_q(estilo.texto)}")
    elif isinstance(estilo.texto, dict):
        for k, v in estilo.texto.items():
            partes.append(f"texto.{k}:{_q(str(v))}")
    if estilo.posicion is not None:
        partes.append(f"pos:{estilo.posicion}")
    if estilo.alineacion is not None:
        partes.append(f"align:{estilo.alineacion}")
    if estilo.visible is not None:
        partes.append("visible" if estilo.visible else "hidden")
    if estilo.separador is not None:
        partes.append(f"sep:{_q(estilo.separador)}")
    return " ".join(partes)


def parsear_style_string(s: str) -> Estilo:
    """Inversa de a_style_string. ValueError ruidoso con el token que fallo."""
    import shlex
    try:
        tokens = shlex.split(s or "", posix=True)
    except ValueError as exc:
        raise ValueError(f"style string mal entrecomillado: {exc}") from None
    kw: dict = {}
    textos: dict = {}
    for tok in tokens:
        bajo = tok.lower()
        if bajo in ("bold", "nobold"):
            kw["negrita"] = bajo == "bold"
        elif bajo in ("italic", "noitalic"):
            kw["italica"] = bajo == "italic"
        elif bajo in ("underline", "nounderline"):
            kw["subrayado"] = bajo == "underline"
        elif bajo in ("visible", "hidden"):
            kw["visible"] = bajo == "visible"
        elif bajo == "noanim":
            kw["animacion"] = Animacion(activa=False)
        elif ":" in tok:
            clave, valor = tok.split(":", 1)
            clave = clave.lower()
            if clave == "fg":
                kw["color"] = valor
            elif clave == "bg":
                kw["fondo"] = valor
            elif clave == "glow":
                color, _, inten = valor.rpartition("/")
                if not inten.isdigit() or not 0 <= int(inten) <= 3:
                    raise ValueError(f"glow: '{valor}' no es <color>/<0-3>")
                kw["glow"] = Glow(color=color or None, intensidad=int(inten))
            elif clave == "anim":
                kw["animacion"] = _parsear_anim(valor)
            elif clave == "glifo":
                kw["glifo"] = valor
            elif clave == "ascii":
                kw["glifo_ascii"] = valor
            elif clave == "texto":
                kw["texto"] = valor
            elif clave.startswith("texto."):
                textos[clave[len("texto."):]] = valor
            elif clave == "pos":
                kw["posicion"] = valor
            elif clave == "align":
                kw["alineacion"] = valor
            elif clave == "sep":
                kw["separador"] = valor
            else:
                raise ValueError(f"token desconocido '{tok}' (vale: bold italic underline fg: bg: "
                                 f"glow: anim: noanim glifo: ascii: texto: pos: align: visible hidden sep:)")
        else:
            raise ValueError(f"token desconocido '{tok}'")
    if textos:
        if "texto" in kw:
            raise ValueError("texto: y texto.<clave>: no se mezclan")
        kw["texto"] = textos
    return Estilo(**kw)


def _parsear_anim(valor: str) -> Animacion:
    import re
    m = re.match(r"^(barrido|pulso)(<>|<|>)?(\d+)?(?:,(\d+))?(?:,([\d.]+))?$", valor)
    if not m:
        raise ValueError(f"anim: '{valor}' no es <barrido|pulso><</>/<>>[velocidad][,ancho][,cada_s]")
    tipo, simbolo, vel, ancho, cada = m.groups()
    a = Animacion(activa=True, tipo=tipo, direccion=_SIMBOLO_A_DIR.get(simbolo or ">", "derecha"))
    if vel:
        a = dataclasses.replace(a, velocidad=int(vel))
    if ancho:
        a = dataclasses.replace(a, ancho=int(ancho))
    if cada:
        a = dataclasses.replace(a, cada_s=float(cada))
    return a


def poner_style_string(id: str, s: str) -> list:
    """/estilo <id> "<style string>": parsea, valida y escribe en memoria
    (como poner, pero varias propiedades de golpe; con un error no escribe)."""
    e = elemento(id)
    estilo = parsear_style_string(s)
    cambio = _a_dict(estilo)
    if isinstance(cambio.get("texto"), dict) != isinstance(e.default.texto, dict) and "texto" in cambio:
        if isinstance(e.default.texto, dict):
            return [Aviso("error", f"'{id}' tiene varios textos: usa texto.<clave>: "
                                   f"({', '.join(e.default.texto)})", id)]
        return [Aviso("error", f"'{id}' tiene un solo texto: usa texto:\"...\"", id)]
    avisos = validar({"version": VERSION_FICHERO, "elementos": {id: cambio}})
    if errores(avisos):
        return avisos
    _estado["overrides"][id] = _fusionar_dicts(_estado["overrides"].get(id) or {}, cambio)
    _subir_version()
    return avisos


# ---------------------------------------------------------------------------
# 12. Transacciones en memoria (editor /estilo, P10) y puente con el motor
# ---------------------------------------------------------------------------
# El editor trabaja SOBRE la memoria del modulo (poner/reset) y nada toca el
# disco hasta guardar(): estas funciones le dan instantaneas para undo/redo
# y para "Esc descarta", y una forma de probar un preset sin copiarlo a
# estilo.json (Ctrl-L previsualiza toda la pantalla; Esc revierte).
import copy  # noqa: E402


def instantanea() -> dict:
    """Copia profunda del estado en memoria (fichero cargado + overrides +
    paleta local). Es lo que el editor apila para deshacer/rehacer."""
    return {"doc": copy.deepcopy(_estado["doc"]),
            "overrides": copy.deepcopy(_estado["overrides"]),
            "paleta_local": copy.deepcopy(_estado["paleta_local"])}


def restaurar(inst: dict) -> None:
    """Vuelve a una instantanea() (sube la version: los memo caducan)."""
    _estado["doc"] = copy.deepcopy(inst.get("doc") or {})
    _estado["overrides"] = copy.deepcopy(inst.get("overrides") or {})
    _estado["paleta_local"] = copy.deepcopy(inst.get("paleta_local") or {})
    _subir_version()


def aplicar_en_memoria(doc: dict) -> list:
    """Instala un documento (un preset) SOLO en memoria, como si el dueno lo
    hubiera tecleado: no toca estilo.json. Valida primero; con errores lanza
    EstiloInvalido y no cambia nada. Devuelve los avisos no bloqueantes. El
    siguiente guardar() lo escribe (el nombre queda como etiqueta)."""
    doc = _migrar(dict(doc))
    avisos = validar(doc)
    if errores(avisos):
        raise EstiloInvalido(doc.get("nombre", "<memoria>"),
                             sorted(avisos, key=lambda a: a.nivel != "error"))
    _estado["doc"] = {k: copy.deepcopy(v) for k, v in doc.items() if k != "elementos"}
    _estado["paleta_local"] = dict(doc.get("paleta") or {})
    _estado["overrides"] = copy.deepcopy(doc.get("elementos") or {})
    _subir_version()
    return avisos


def paleta_local() -> dict:
    """Los @mi.* del fichero cargado (nombre -> color o dict por variante)."""
    return dict(_estado["paleta_local"])


def estilo_glow(id: str, variante: str | None = None, estado: str | None = None):
    """EstiloResuelto -> glow.EstiloGlow (el tipo del motor). Es el callable
    que va en glow.RESOLVER. Byte-identico: si el elemento no tiene override
    de color/negrita/italica/subrayado, el motor recibe SOLO el token del
    Theme (color '' y modificadores False) y devuelve el token tal cual; con
    override recibe el color resuelto (hex o nombre de rich)."""
    from . import glow as _glow
    r = estilo_resuelto(id, variante)
    e = elemento(id)
    est = estilo_de(id)
    default = e.default
    if estado:
        if estado not in r.estados:
            raise KeyError(f"'{id}' no tiene el estado '{estado}'; tiene: "
                           f"{', '.join(e.estados) or 'ninguno'}")
        r = r.estados[estado]
        est = est.estados.get(estado, Estilo())
        default = default.estados.get(estado, Estilo())
    tocado = any(getattr(est, c) != getattr(default, c)
                 for c in ("color", "fondo", "negrita", "italica", "subrayado"))
    if r.token and not tocado:
        color, fondo, negrita, italica, subrayado = "", "", False, False, False
    else:
        color = color_rich(r.color) if r.color else ""
        fondo = color_rich(r.fondo) if r.fondo else ""
        negrita, italica, subrayado = r.negrita, r.italica, r.subrayado
    a = r.animacion
    return _glow.EstiloGlow(
        token=r.token, color=color, fondo=fondo, negrita=negrita, italica=italica,
        subrayado=subrayado, glow_color=r.glow_color, glow_intensidad=r.glow_intensidad,
        anim_activa=a.activa, anim_tipo=a.tipo, anim_direccion=a.direccion,
        anim_velocidad=a.velocidad, anim_ancho=a.ancho, anim_repetir=a.repetir,
        anim_cada_s=a.cada_s, anim_solo_al_llegar=a.solo_al_llegar, gradiente=r.gradiente)


def conectar_glow() -> None:
    """Cuelga este registro del motor (glow.RESOLVER/VERSION/VARIANTE) si
    nadie lo hizo antes. Idempotente: el editor y P4 lo llaman."""
    from . import glow as _glow
    if _glow.RESOLVER is None:
        _glow.RESOLVER = estilo_glow
    if _glow.VERSION is None:
        _glow.VERSION = version
    if _glow.VARIANTE is None:
        _glow.VARIANTE = variante_activa


# ---------------------------------------------------------------------------
# 13. P8 (spinner, 2026-08-24): elementos ENGANCHADOS por renderer/spinner_vivo
# ---------------------------------------------------------------------------
# E8: el renderer (_arrancar_status/_tick_spinner) y spinner_vivo leen estos
# ids a call-time: glifo, textos (hint/tok/pensando/spinner_rich), separador,
# color por token y animacion (glow.LineaViva dentro del console.status).
# spinner.comando: cli.py (_run, _mejora_generar y el camino articulado del
# repl) llama spinner_vivo.comando() desde el gancho P8 (rama estilos/banner).
ENGANCHADOS_P8 = ("spinner.tool", "spinner.pensar", "spinner.comando")
for _id in ENGANCHADOS_P8:
    REGISTRO[_id] = dataclasses.replace(REGISTRO[_id], enganchado=True)
del _id
