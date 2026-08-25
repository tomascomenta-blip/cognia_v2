# -*- coding: utf-8 -*-
"""
cognia/ux/editor_aspecto.py -- el MODELO puro del editor interactivo /estilo
(paso P10 del sistema de estilos por elemento, 2026-08-24).

QUE: `EditorModelo` es una maquina de estados SIN prompt_toolkit: recibe
nombres de tecla (`tecla('down')`, `tecla('c-s')`) y expone lo que hay que
pintar (`filas_elementos()`, `filas_propiedades()`, `filas_flotante()`,
`preview()`, `estado_pie()`, `mensaje()`). La Application full-screen (P11)
es una capa fina: KeyBindings -> `modelo.tecla(...)`, y tres Windows que
pintan las filas. Asi los tests recorren el editor ENTERO sin consola.

CONTRATO:
- Todo cambio va por `aspecto.poner` / `aspecto.reset` SOBRE LA MEMORIA del
  registro: nada toca ~/.cognia/estilo.json hasta Ctrl-S (que llama al
  callback `guardar` inyectado; por defecto `aspecto.guardar`). Esc con
  cambios sin guardar pide Guardar / Descartar / Volver; Descartar restaura
  la instantanea tomada al abrir.
- La validacion RUIDOSA de aspecto se muestra siempre en `mensaje()`: un
  valor rechazado (nivel 'error') no se escribe y el motivo queda a la
  vista; un 'aviso' (contraste bajo el piso, glifo no codificable, animacion
  en un elemento no vivo) se acepta y se muestra. Nunca se traga.
- Undo/redo: pila de instantaneas del estado en memoria (max MAX_UNDO=100),
  solo de cambios CONFIRMADOS (los movimientos del sub-selector de color o
  del preview de presets no entran hasta Enter).
- La vista previa usa las MISMAS funciones del motor que el REPL
  (glow.estilizar / frame_estatico / gradiente_lineas) con un reloj FIJO
  (`t_preview`): el frame es determinista y cambia cuando cambia la
  propiedad. Mientras calcula, fuerza capacidades truecolor: el editor pinta
  en su Application, no en el stdout del proceso (que en un pipe daria
  nivel 'none' y borraria los colores).

TABLA DE TECLAS (nombres que acepta `tecla`; los mismos que emitira P11):
  up/down, j/k          mover en el panel activo (o en la lista flotante)
  pageup/pagedown       saltar 10 filas
  home/end, g/G         primera / ultima fila
  left/right            cambiar de panel; en una propiedad numerica o
                        enumerada, ajustar (-/+ o ciclar)
  tab / s-tab           cambiar de panel (elementos <-> propiedades)
  enter                 lista: plegar/desplegar grupo o ir a propiedades;
                        propiedad: editar segun tipo (bool alterna, numero
                        abre entrada, enum cicla, texto/glifo abre buffer,
                        color abre el sub-selector, 'estilo rapido' abre
                        buffer con el style string)
  space                 alternar bool (en bool); en enum cicla
  + / -                 ajustar numero (intensidad 0-3, velocidad 1-5,
                        ancho 1-20, repetir 0-99, cada_s 0-60 de 0,5)
  /                     filtrar la lista por texto (Enter fija, Esc limpia)
  a / A                 interruptor GLOBAL de animacion (callback
                        `poner_config`) / animacion del elemento actual
  v                     ciclar la variante de la vista previa
  r / R                 reset del elemento / de TODO (R pide confirmacion)
  c-z / c-y             deshacer / rehacer
  c-s                   guardar (validar + callback `guardar` + `aplicar`)
  c-p                   presets: listar y aplicar en memoria (Enter)
  c-l                   presets con preview de TODA la pantalla al mover;
                        Esc revierte, Enter se queda
  c-n                   guardar el estado como preset (pide nombre)
  c-e                   exportar a una ruta (pide ruta)
  c-g                   en un glifo: lista de glifos que Cognia ya usa
  ?  / f1               ayuda de teclas
  esc / q               salir (con cambios: Guardar / Descartar / Volver);
                        en un sub-modo: cancelar
  backspace, delete     en los buffers de texto
  <un caracter>         en los buffers: escribe; en el sub-selector de
                        color: 't' = terminal, tab = siguiente pestana
"""
from __future__ import annotations

import re
import sys
import time
from dataclasses import dataclass

from . import aspecto as A
from . import paleta

MAX_UNDO = 100
# Los glifos que Cognia ya usa en el REPL (seccion 5.5 del diseno).
GLIFOS_COGNIA = ("➤ ", "─", "═", "●", "⏺", "✗", "⚠", "→", "⎿", "∴", "❯", "·", "…", "✓", "░",
                 "> ", "-", "=", "+", "x", "*", "|_", "!")
PESTANAS_COLOR = ("refs", "mi", "hex")
_RE_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_VARIANTE_CORTA = {"oscuro": "oscuro", "claro": "claro", "alto_contraste": "ac"}

# Atajos del modo normal en su orden de PINTADO y, en cada uno, el orden de
# DESCARTE (mayor = se cae antes). Medido 2026-08-24: la barra entera son
# 192 celdas; a 120 columnas se cortaba en "^L previ" y "? ayuda / Esc salir"
# (las dos salidas del editor) no se veian. Mismo criterio que
# harness/barra_estado.barra_atajos_partes: recortar por atajos enteros, de
# menos a mas importante; "?" y "Esc" (prioridad 0) NUNCA se caen, porque
# sin ellos el dueno no sabe ni como pedir ayuda ni como salir.
_ATAJOS_NORMAL = (
    ("Tab panel", 2), ("Enter editar", 1), ("Space alternar", 3), ("+/- ajustar", 6),
    ("/ filtrar", 8), ("^Z/^Y deshacer/rehacer", 5), ("^S guardar", 1), ("^P preset", 7),
    ("^L previsualizar", 9), ("^E exportar", 11), ("a anim", 10), ("v variante", 4),
    ("r/R reset", 12), ("? ayuda", 0), ("Esc salir", 0),
)
_SEP_ATAJOS = "  "


def _ancho_visual(texto: str) -> int:
    """Celdas de una cadena: CJK 2, combinantes 0 (los glifos de esta barra
    son ASCII y flechas de 1 celda; la funcion existe para no mentir si un
    dia un texto del pie trae un glifo ancho)."""
    import unicodedata
    return sum(0 if unicodedata.combining(ch) else
               (2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1) for ch in texto)


def barra_atajos_normal(ancho: int = 0) -> str:
    """La barra de atajos del modo normal que CABE en `ancho` celdas
    (0 = entera). Se quitan atajos completos por prioridad hasta que entra;
    '? ayuda' y 'Esc salir' se quedan siempre, aunque el ancho sea ridiculo."""
    vivos = list(_ATAJOS_NORMAL)

    def texto(lista):
        return _SEP_ATAJOS.join(t for t, _ in lista)
    if ancho <= 0:
        return texto(vivos)
    while _ancho_visual(texto(vivos)) > ancho:
        candidatos = [i for i, (_, pr) in enumerate(vivos) if pr > 0]
        if not candidatos:
            break                      # solo quedan los fijos: se pintan enteros
        peor = max(candidatos, key=lambda i: vivos[i][1])
        del vivos[peor]
    return texto(vivos)


def _cortar(texto: str, ancho: int, elip: str = "\u2026") -> str:
    """Recorta `texto` a `ancho` celdas marcando con la elipsis que FALTA
    algo; si cabe, vuelve intacto (la elipsis solo cuando se corto)."""
    if ancho <= 0 or _ancho_visual(texto) <= ancho:
        return texto
    if _ancho_visual(elip) >= ancho:
        elip = ""
    cupo = max(0, ancho - _ancho_visual(elip))
    out, usado = [], 0
    for ch in texto:
        w = _ancho_visual(ch)
        if usado + w > cupo:
            break
        out.append(ch)
        usado += w
    return "".join(out).rstrip() + elip
# Datos de muestra FIJOS para que el frame de la vista previa sea determinista.
MUESTRA_BARRA = ("qwythos-27b", "~/proy", "main", "ctx 12.4k/65.5k (80% libre)", "3.2k tok")
MUESTRA_GATO = (
    "⠀⠀⠀⠀⣀⣀⣀⣀⣀⣀⠀⠀⠀⠀",
    "⠀⠀⣰⣿⣿⣿⣿⣿⣿⣿⣿⣆⠀⠀",
    "⠀⢠⣿⣿⡿⠋⠁⠈⠙⢿⣿⣿⡄⠀",
)

AYUDA = (
    ("↑↓ j k", "mover"), ("PgUp PgDn g G", "saltar / extremos"),
    ("←→ Tab", "cambiar de panel; ←→ ajusta numeros y enums"),
    ("Enter", "editar (bool alterna, numero entrada, enum cicla, texto/glifo buffer, color selector)"),
    ("Space", "alternar bool"), ("+ -", "ajustar numero"), ("/", "filtrar la lista"),
    ("a / A", "animacion global / del elemento"), ("v", "variante de la vista previa"),
    ("r / R", "reset del elemento / de todo"), ("^Z ^Y", "deshacer / rehacer"),
    ("^S", "guardar"), ("^P", "presets: aplicar"), ("^L", "presets: previsualizar (Esc revierte)"),
    ("^N", "guardar como preset"), ("^E", "exportar"), ("^G", "lista de glifos (en un glifo)"),
    ("Esc / q", "salir (con cambios: Guardar / Descartar / Volver)"),
)


@dataclass(frozen=True)
class Prop:
    """Una fila del panel de propiedades."""
    ruta: str               # 'texto' | 'texto.titulo' | 'glow.intensidad' | 'estados.activo.color' | 'rapido'
    etiqueta: str
    tipo: str               # bool | numero | enum | texto | color | glifo | rapido
    opciones: tuple = ()
    minimo: float = 0.0
    maximo: float = 0.0
    paso: float = 1.0
    atenuada: bool = False
    nota: str = ""


def _props_de(e: A.Elemento) -> list:
    """Las filas de propiedades que ofrece un elemento, en orden fijo,
    derivadas de sus caps y de su default (nunca una que no acepte)."""
    d = e.default
    caps = e.caps
    filas = []
    if A.Cap.TEXTO in caps:
        if isinstance(d.texto, dict):
            for k in d.texto:
                filas.append(Prop(f"texto.{k}", f"texto.{k}", "texto"))
        else:
            filas.append(Prop("texto", "texto", "texto"))
    if A.Cap.COLOR in caps:
        filas.append(Prop("color", "color", "color"))
    if A.Cap.FONDO in caps:
        filas.append(Prop("fondo", "fondo", "color"))
    for b in ("negrita", "italica", "subrayado"):
        if A.Cap(b) in caps:
            filas.append(Prop(b, b, "bool"))
    if A.Cap.GLOW in caps:
        filas.append(Prop("glow.color", "glow.color", "color"))
        filas.append(Prop("glow.intensidad", "glow.intensidad", "numero", minimo=0, maximo=3))
    if A.Cap.ANIMACION in caps:
        at = not e.vivo
        nota = "no animable: linea impresa; se guarda pero no corre" if at else ""
        filas += [
            Prop("animacion.activa", "animacion.activa", "bool", atenuada=at, nota=nota),
            Prop("animacion.tipo", "animacion.tipo", "enum", opciones=A.TIPOS_ANIMACION, atenuada=at),
            Prop("animacion.direccion", "animacion.direccion", "enum", opciones=A.DIRECCIONES, atenuada=at),
            Prop("animacion.velocidad", "animacion.velocidad", "numero", minimo=1, maximo=5, atenuada=at),
            Prop("animacion.ancho", "animacion.ancho", "numero", minimo=1, maximo=20, atenuada=at),
            Prop("animacion.repetir", "animacion.repetir", "numero", minimo=0, maximo=99, atenuada=at),
            Prop("animacion.cada_s", "animacion.cada_s", "numero", minimo=0, maximo=60, paso=0.5, atenuada=at),
            Prop("animacion.solo_al_llegar", "animacion.solo_al_llegar", "bool", atenuada=at),
        ]
    if A.Cap.GLIFO in caps:
        if e.glifos:
            filas.append(Prop("glifo", "glifo (caja)", "enum", opciones=tuple(e.glifos)))
        else:
            filas.append(Prop("glifo", "glifo", "glifo"))
            filas.append(Prop("glifo_ascii", "glifo_ascii", "glifo"))
    if A.Cap.POSICION in caps:
        filas.append(Prop("posicion", "posicion", "enum", opciones=tuple(e.posiciones)))
    if A.Cap.ALINEACION in caps:
        filas.append(Prop("alineacion", "alineacion", "enum", opciones=tuple(e.alineaciones)))
    if A.Cap.VISIBLE in caps:
        filas.append(Prop("visible", "visible", "bool"))
    if A.Cap.GRADIENTE in caps:
        filas.append(Prop("gradiente", "gradiente", "texto", nota="dos colores separados por coma"))
    if A.Cap.SEPARADOR in caps:
        filas.append(Prop("separador", "separador", "texto"))
    for n in e.estados:
        sub = d.estados.get(n, A.Estilo())
        campos = [c for c in ("color", "fondo", "negrita", "italica", "subrayado", "glifo")
                  if getattr(sub, c) is not None] or ["color"]
        for c in campos:
            tipo = "color" if c in ("color", "fondo") else ("glifo" if c == "glifo" else "bool")
            filas.append(Prop(f"estados.{n}.{c}", f"{n}.{c}", tipo))
    filas.append(Prop("rapido", "estilo rapido", "rapido",
                      nota="style string: bold fg:@rampa.prompt glow:@mi.lima/1 anim:barrido>2"))
    return filas


def _codificable(s: str) -> bool:
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        s.encode(enc)
        return True
    except (UnicodeEncodeError, LookupError):
        return False


def _fmt_ratio(r: float) -> str:
    return f"{r:.1f}:1".replace(".", ",")


class EditorModelo:
    """El modelo del editor. Ver el docstring del modulo para la tabla de
    teclas. `guardar` es el callback de Ctrl-S (por defecto aspecto.guardar);
    `aplicar` se llama tras guardar (P11: aplicar en caliente);
    `poner_config(clave, valor)` escribe la config global (tecla 'a')."""

    def __init__(self, *, guardar=None, aplicar=None, poner_config=None, variante=None,
                 ancho: int = 80, t_preview: float = 0.75, elemento_inicial: str | None = None,
                 ancho_flotante: int | None = None):
        A.conectar_glow()
        self._guardar_cb = guardar or A.guardar
        self._aplicar_cb = aplicar
        self._poner_config = poner_config
        self.ancho = int(ancho)
        # Ancho INTERIOR del panel flotante (selector de color, glifos,
        # presets). editor_app lo pone en Float(left=2, right=2) dentro de un
        # Frame de 2 bordes sobre la terminal entera (= ancho + 2): quedan
        # ancho - 4 celdas. Antes las filas del selector de color se componian
        # a ciegas (nombre 24 + hex 8 + tres ratios ~ 60 celdas) y a 80
        # columnas la cola con el veredicto de contraste se salia del panel.
        self.ancho_flotante = int(ancho_flotante) if ancho_flotante else max(20, self.ancho - 4)
        self.t_preview = float(t_preview)
        self.variante_preview = variante or A.variante_activa()
        if self.variante_preview not in A.ORDEN_VARIANTES:
            self.variante_preview = A.VARIANTE_DEFECTO
        self.panel = "elementos"
        self.modo = "normal"
        self.cursor_elementos = 0
        self.cursor_props = 0
        self.filtro = ""
        self.plegados: set = set()
        self.pila_undo: list = []
        self.pila_redo: list = []
        self.buffer = ""
        self.cursor_flotante = 0
        self.color: dict = {}
        self._inst_temporal = None      # instantanea al entrar a un sub-modo que aplica al mover
        self._prop_en_edicion = None
        self._base = A.instantanea()   # para Descartar
        self._doc_guardado = A.documento()
        self._mensaje = ""
        self.cerrado = False
        self.resultado = None           # 'guardado' | 'descartado' | 'cerrado'
        self.guardado_en = ""
        self.animacion_global, _ = A.animacion_global()
        self._presets: list = []
        if elemento_inicial:
            self.ir_a(elemento_inicial)

    # ------------------------------------------------------------------
    # Estado derivado
    # ------------------------------------------------------------------
    def _lista(self) -> list:
        """Filas del panel de elementos: ('grupo', nombre) | ('elemento', id)."""
        f = self.filtro.strip().lower()
        out = []
        for grupo, ids_ in A.GRUPOS:
            if f:
                for id in ids_:
                    if f in id.lower() or f in A.REGISTRO[id].nombre.lower():
                        out.append(("elemento", id))
                continue
            out.append(("grupo", grupo))
            if grupo not in self.plegados:
                out.extend(("elemento", id) for id in ids_)
        return out

    @property
    def elemento_id(self) -> str | None:
        lista = self._lista()
        if not lista:
            return None
        self.cursor_elementos = max(0, min(self.cursor_elementos, len(lista) - 1))
        tipo, valor = lista[self.cursor_elementos]
        if tipo == "elemento":
            return valor
        for g, ids_ in A.GRUPOS:
            if g == valor:
                return ids_[0]
        return None

    @property
    def elemento(self) -> A.Elemento | None:
        id = self.elemento_id
        return A.REGISTRO[id] if id else None

    def props(self) -> list:
        e = self.elemento
        return _props_de(e) if e else []

    def prop_actual(self) -> Prop | None:
        ps = self.props()
        if not ps:
            return None
        self.cursor_props = max(0, min(self.cursor_props, len(ps) - 1))
        return ps[self.cursor_props]

    @property
    def sucio(self) -> bool:
        return A.documento() != self._doc_guardado

    def mensaje(self) -> str:
        return self._mensaje

    def ir_a(self, id: str) -> None:
        """Pone el cursor en un elemento (desplegando su grupo)."""
        e = A.elemento(id)
        self.plegados.discard(e.grupo)
        for i, (tipo, valor) in enumerate(self._lista()):
            if tipo == "elemento" and valor == id:
                self.cursor_elementos = i
                self.cursor_props = 0
                return

    # ------------------------------------------------------------------
    # Valores
    # ------------------------------------------------------------------
    def _valor_crudo(self, prop: Prop):
        """El valor tal como esta en la pila (default <- fichero <- memoria)."""
        est = A.estilo_de(self.elemento_id)
        partes = prop.ruta.split(".")
        if partes[0] == "estados":
            est = est.estados.get(partes[1], A.Estilo())
            partes = partes[2:]
        if partes[0] == "texto" and len(partes) == 2:
            return (est.texto or {}).get(partes[1]) if isinstance(est.texto, dict) else None
        obj = est
        for p in partes:
            obj = getattr(obj, p, None) if obj is not None else None
        return obj

    def _resuelto(self, prop: Prop | None = None):
        r = A.estilo_resuelto(self.elemento_id, self.variante_preview)
        if prop is not None and prop.ruta.startswith("estados."):
            r = r.estados.get(prop.ruta.split(".")[1], r)
        return r

    def _bool_actual(self, prop: Prop) -> bool:
        partes = prop.ruta.split(".")
        campo = partes[-1]
        if partes[0] == "animacion":
            return bool(getattr(self._resuelto().animacion, campo))
        return bool(getattr(self._resuelto(prop), campo))

    def _numero_actual(self, prop: Prop):
        v = self._valor_crudo(prop)
        if v is None:
            partes = prop.ruta.split(".")
            v = getattr(self._resuelto().animacion, partes[-1]) if partes[0] == "animacion" else 0
        return v

    def _fondo_del_elemento(self, variante: str) -> str:
        try:
            r = A.estilo_resuelto(self.elemento_id, variante)
            if r.fondo and r.fondo.startswith("#"):
                return r.fondo
        except Exception:
            pass
        return paleta.FONDO_VARIANTE[variante]

    def _ratios(self, valor, ancho_max: int = 0) -> str:
        """'7,9:1 oscuro  4,9:1 claro  9,1:1 ac  ok' para un color crudo.

        Veredicto: '!' si alguna variante queda bajo el piso del elemento;
        en un elemento GRAFICO (reglas, marco, arte del banner) que pasa el
        piso 3,0 pero no el 4,5 de texto, 'decorativo (3,0)' en vez de 'ok':
        el 'ok' a 3,0:1 hacia creer que el color valia para leer, y el gato
        a 3,0:1 solo vale como adorno (WCAG 1.4.11 vs 1.4.3).

        `ancho_max` > 0: se caen variantes hasta que cabe, y la que se queda
        es la que EXPLICA el veredicto: la peor si hay '!' (ver "16,0:1  !"
        sin la variante que suspende desconcierta), la previsualizada si no;
        el veredicto no se cae nunca."""
        e = self.elemento
        piso = A.PISO_GRAFICO if e.grafico else A.PISO_TEXTO
        partes, flojo, peor, ratios = [], False, None, {}
        for v in A.ORDEN_VARIANTES:
            try:
                hexa = A.hex_medible(valor, v)
            except Exception:
                hexa = None
            if hexa is None:
                continue
            r = A.contraste(hexa, self._fondo_del_elemento(v))
            flojo = flojo or r < piso
            peor = r if peor is None else min(peor, r)
            ratios[v] = r
            partes.append((v, f"{_fmt_ratio(r)} {_VARIANTE_CORTA[v]}"))
        if not partes:
            return ""
        if flojo:
            veredicto = "!"
        elif e.grafico and peor < A.PISO_TEXTO:
            veredicto = f"decorativo ({str(A.PISO_GRAFICO).replace('.', ',')})"
        else:
            veredicto = "ok"

        def compuesto(lista):
            return "  ".join(t for _, t in lista) + "  " + veredicto
        # orden de descarte: primero las que no explican nada
        clave = {v: r for v, r in ratios.items()}
        if flojo:
            def importancia(v):
                return (clave[v] < piso, -clave[v])       # las flojas primero, la peor la ultima
        else:
            def importancia(v):
                return (v == self.variante_preview, 0)
        while ancho_max > 0 and len(partes) > 1 and _ancho_visual(compuesto(partes)) > ancho_max:
            idx = min(range(len(partes)), key=lambda i: importancia(partes[i][0]))
            del partes[idx]
        if ancho_max > 0 and _ancho_visual(compuesto(partes)) > ancho_max:
            # panel estrecho: el ratio de la variante que se ve, sin etiqueta;
            # y si ni eso, el veredicto solo (con 'decorativo' sin su piso)
            corto = veredicto.split(" ")[0]
            for cand in (partes[0][1].split(" ")[0] + "  " + veredicto,
                         partes[0][1].split(" ")[0] + "  " + corto, veredicto, corto):
                if _ancho_visual(cand) <= ancho_max:
                    return cand
            return corto
        return compuesto(partes)

    def _texto_valor(self, prop: Prop) -> str:
        e = self.elemento
        if prop.tipo == "rapido":
            return A.a_style_string(A.estilo_de(e.id))
        if prop.tipo == "bool":
            return "[x]" if self._bool_actual(prop) else "[ ]"
        if prop.tipo == "numero":
            v = self._numero_actual(prop)
            return f"{v:g}" if isinstance(v, float) else str(v)
        if prop.tipo == "enum":
            v = self._valor_crudo(prop)
            otros = [o for o in prop.opciones if o != v]
            return f"{v}" + (f"   ({' / '.join(otros)})" if otros else "")
        if prop.tipo == "color":
            v = self._valor_crudo(prop)
            if v is None:
                if prop.ruta == "glow.color":
                    return f"derivado   {self._resuelto().glow_color}"
                return "terminal"
            if isinstance(v, dict):
                crudo = "por variante"
            else:
                crudo = str(v)
            try:
                hexa = A.hex_medible(v, self.variante_preview) or ""
            except Exception:
                hexa = ""
            return f"{crudo:<20} {hexa:<8} {self._ratios(v)}".rstrip()
        if prop.tipo == "glifo":
            v = self._valor_crudo(prop)
            s = f"'{v}'" if v is not None else "(ninguno)"
            if v and not _codificable(v):
                s += f"   no codificable en {getattr(sys.stdout, 'encoding', None) or 'utf-8'}: se usara glifo_ascii"
            return s
        v = self._valor_crudo(prop)
        if isinstance(v, (list, tuple)):
            return ", ".join(str(x) for x in v)
        return "(vacio)" if v in (None, "") else str(v)

    # ------------------------------------------------------------------
    # Filas para pintar
    # ------------------------------------------------------------------
    def _marcas(self, id: str) -> str:
        e = A.REGISTRO[id]
        m = []
        try:
            est = A.estilo_de(id)
            if e.vivo and est.animacion and est.animacion.activa:
                m.append("*")
        except Exception:
            pass
        if A.tiene_override(id):
            m.append("mod")
            avisos = A.validar({"version": A.VERSION_FICHERO, "elementos": {id: A.cambios(id)}})
            if any("contraste" in a.texto for a in avisos):
                m.append("!")
        return " ".join(m)

    def filas_elementos(self) -> list:
        """[(texto, clase_pt, seleccionado)] del panel izquierdo."""
        lista = self._lista()
        self.cursor_elementos = max(0, min(self.cursor_elementos, max(0, len(lista) - 1)))
        out = []
        activo = self.panel == "elementos"
        for i, (tipo, valor) in enumerate(lista):
            sel = i == self.cursor_elementos
            if tipo == "grupo":
                flecha = "▸" if valor in self.plegados else "▾"
                out.append((f"{flecha} {valor}", "class:grupo" + (".activo" if sel and activo else ""), sel))
            else:
                e = A.REGISTRO[valor]
                corto = valor[len(e.grupo) + 1:] if valor.startswith(e.grupo + ".") else valor
                pref = "> " if sel else "  "
                clase = "class:elemento" + (".activo" if sel and activo else (".cursor" if sel else ""))
                out.append((f"{pref}{corto:<18} {self._marcas(valor)}".rstrip(), clase, sel))
        if not out:
            out.append((f"  (nada coincide con '{self.filtro}')", "class:elemento.atenuado", False))
        return out

    def titulo_propiedades(self) -> str:
        e = self.elemento
        if not e:
            return "PROPIEDADES"
        return f"PROPIEDADES: {e.id} ({e.nombre})" + (f"  — {e.nota}" if e.nota else "")

    def filas_propiedades(self) -> list:
        """[(texto, clase_pt, seleccionado)] del panel derecho."""
        ps = self.props()
        out = []
        activo = self.panel == "propiedades"
        for i, p in enumerate(ps):
            sel = i == self.cursor_props
            texto = f"{p.etiqueta:<20} {self._texto_valor(p)}"
            if p.nota and p.atenuada:
                texto += f"   ({p.nota})"
            clase = "class:prop"
            if p.atenuada:
                clase += ".atenuada"
            if sel and activo:
                clase += ".activa"
            out.append((texto, clase, sel))
        return out

    def titulo_flotante(self) -> str:
        return {
            "color": f"COLOR: {self._prop_en_edicion.etiqueta if self._prop_en_edicion else ''} "
                     f"[{' | '.join(('*' if p == self.color.get('pestana') else '') + p for p in PESTANAS_COLOR)}]  "
                     "Tab pestana · t terminal · Enter fija · Esc vuelve",
            "glifos": "GLIFOS de Cognia (Enter elige, Esc vuelve)",
            "presets": "PRESETS (Enter aplica en memoria, Esc vuelve)",
            "presets_preview": "PRESETS (preview al mover; Enter se queda, Esc revierte)",
            "ayuda": "AYUDA",
            "confirmar_salir": "Hay cambios sin guardar: [g]uardar / [d]escartar / [v]olver (Enter y Esc vuelven)",
            "confirmar_reset": "Volver TODO al default: [s]i / [n]o",
            "texto": f"{self._prop_en_edicion.etiqueta if self._prop_en_edicion else 'texto'} (Enter confirma, Esc cancela)",
            "numero": f"{self._prop_en_edicion.etiqueta if self._prop_en_edicion else 'numero'} (Enter confirma, Esc cancela)",
            "rapido": "estilo rapido (Enter confirma, Esc cancela)",
            "filtro": "filtro (Enter fija, Esc limpia)",
            "exportar": "exportar a ruta (Enter escribe, Esc cancela)",
            "preset_nombre": "guardar como preset: nombre (Enter escribe, Esc cancela)",
        }.get(self.modo, "")

    def filas_flotante(self) -> list:
        """Las filas del sub-modo activo (selector de color, glifos, presets,
        ayuda, confirmaciones, buffers). Vacio en modo normal."""
        m = self.modo
        if m == "color":
            return self._filas_color()
        if m == "glifos":
            enc = getattr(sys.stdout, "encoding", None) or "utf-8"
            out = []
            for i, g in enumerate(GLIFOS_COGNIA):
                sel = i == self.cursor_flotante
                aviso = "" if _codificable(g) else f"   no codificable en {enc}"
                out.append((f"{'> ' if sel else '  '}'{g}'{aviso}", "class:flotante" + (".activo" if sel else ""), sel))
            return out
        if m in ("presets", "presets_preview"):
            out = []
            for i, (nombre, ruta, origen, nota) in enumerate(self._presets):
                sel = i == self.cursor_flotante
                out.append((f"{'> ' if sel else '  '}{nombre:<16} {origen:<8} {nota}".rstrip(),
                            "class:flotante" + (".activo" if sel else ""), sel))
            if not out:
                out.append(("  (no hay presets)", "class:flotante", False))
            return out
        if m == "ayuda":
            return [(f"{k:<16} {v}", "class:flotante", False) for k, v in AYUDA]
        if m == "confirmar_salir":
            return [("[g] guardar y salir", "class:flotante", False),
                    ("[d] descartar los cambios y salir", "class:flotante", False),
                    ("[v] volver al editor", "class:flotante", False)]
        if m == "confirmar_reset":
            return [("[s] si, volver todo al default", "class:flotante", False),
                    ("[n] no", "class:flotante", False)]
        if m in ("texto", "numero", "rapido", "filtro", "exportar", "preset_nombre"):
            return [(self.buffer + "▏", "class:flotante.buffer", True)]
        return []

    def _refs_color(self) -> list:
        v = self.variante_preview
        refs = [f"@rampa.{k}" for k in paleta.RAMPA[v]]
        refs += [f"@semantico.{k}" for k in paleta.SEMANTICO]
        refs += [f"@superficie.{k}" for k in paleta.SUPERFICIE]
        refs += [f"@menu.{k}" for k in paleta.MENU_PROMPT]
        refs.append("terminal")
        return refs

    def _mi_color(self) -> list:
        return [f"@mi.{k}" for k in A.paleta_local()] + ["terminal"]

    def _candidatos_color(self) -> list:
        p = self.color.get("pestana")
        if p == "refs":
            return self._refs_color()
        if p == "mi":
            return self._mi_color()
        return [self.color.get("buffer", "")]

    def _filas_color(self) -> list:
        p = self.color.get("pestana")
        out = []
        ancho = self.ancho_flotante
        if p == "hex":
            b = self.color.get("buffer", "")
            ok = bool(_RE_HEX.match(b))
            cabeza = f"{b}▏   "
            cola = self._ratios(b, ancho - _ancho_visual(cabeza)) if ok else "(#rrggbb)"
            out.append((_cortar(cabeza + cola, ancho), "class:flotante.buffer", True))
            return out
        cands = self._candidatos_color()
        if p == "mi" and len(cands) == 1:
            out.append((_cortar("  (sin paleta local: clave 'paleta' en estilo.json)", ancho),
                        "class:flotante", False))
        # columna del nombre: la del candidato mas largo (tope 24); en un
        # panel de 40 celdas las 3 de relleno decidian si entraba el veredicto
        col = min(24, max((len(c) for c in cands), default=8))
        for i, c in enumerate(cands):
            sel = i == self.cursor_flotante
            try:
                hexa = A.hex_medible(c, self.variante_preview) or ""
            except Exception:
                hexa = "?"
            cabeza = f"{'> ' if sel else '  '}{c:<{col}} {hexa:<7} "
            cola = self._ratios(c, ancho - _ancho_visual(cabeza)) if c != "terminal" else ""
            # _cortar es la red por si el nombre de una @ref ya se come el
            # panel entero: la fila jamas rebasa el borde del flotante
            out.append((_cortar((cabeza + cola).rstrip(), ancho),
                        "class:flotante" + (".activo" if sel else ""), sel))
        return out

    def estado_pie(self) -> str:
        """Las teclas disponibles en el contexto actual + estado de guardado."""
        m = self.modo
        if m == "normal":
            # recortada al ancho del editor: ver _ATAJOS_NORMAL
            base = barra_atajos_normal(self.ancho)
        else:
            base = {
                "color": "↑↓ mover  Tab pestana  t terminal  Enter fijar  Esc volver",
                "glifos": "↑↓ mover  Enter elegir  Esc volver",
                "presets": "↑↓ mover  Enter aplicar  Esc volver",
                "presets_preview": "↑↓ previsualizar  Enter quedarse  Esc revertir",
                "ayuda": "cualquier tecla cierra",
                "confirmar_salir": "g guardar  d descartar  v/Enter/Esc volver",
                "confirmar_reset": "s si  n no",
                "texto": "escribe  Enter confirmar  Esc cancelar  (^G glifos)" if (
                    self._prop_en_edicion and self._prop_en_edicion.tipo == "glifo") else "escribe  Enter confirmar  Esc cancelar",
                "numero": "escribe un numero  Enter confirmar  Esc cancelar",
                "rapido": "escribe el style string  Enter confirmar  Esc cancelar",
                "filtro": "escribe  Enter fijar  Esc limpiar",
                "exportar": "escribe la ruta  Enter escribir  Esc cancelar",
                "preset_nombre": "escribe el nombre  Enter escribir  Esc cancelar",
            }.get(m, "")
        n = len(A.documento().get("elementos") or {})
        estado = (f"guardado {self.guardado_en}" if self.guardado_en else "sin guardar")
        estado += f" · {n} elemento{'s' if n != 1 else ''} con cambios"
        estado += " · CAMBIOS SIN GUARDAR" if self.sucio else ""
        estado += f" · variante {self.variante_preview}"
        estado += f" · animacion global {'on' if self.animacion_global else 'off'}"
        return f"{base}\n{estado}"

    # ------------------------------------------------------------------
    # Vista previa (con las funciones del motor y el reloj fijo)
    # ------------------------------------------------------------------
    def _pieza(self, id: str, texto: str, estado: str | None = None, t=None):
        from . import glow as G
        return G.estilizar(id, texto, t=self.t_preview if t is None else t,
                           variante=self.variante_preview, estado=estado)

    def preview(self, t=None):
        """rich.Text con el elemento seleccionado EN SU CONTEXTO, calculado
        con glow.estilizar/gradiente_lineas y el reloj fijo `t_preview` (o
        `t`). Fuerza capacidades truecolor mientras calcula."""
        from . import glow as G
        from rich.text import Text
        e = self.elemento
        if e is None:
            return Text("")
        previas = G._CAPS_FORZADAS
        G.forzar_capacidades(G.Caps("truecolor", True, "editor"))
        try:
            lineas = self._lineas_preview(e, self.t_preview if t is None else t)
        finally:
            G.forzar_capacidades(previas)
        return Text("\n").join(lineas)

    def preview_pt(self, t=None) -> list:
        """Los mismos frames como fragmentos de prompt_toolkit [(estilo, trozo)]."""
        from . import glow as G
        from rich.text import Text
        texto = self.preview(t)
        out = []
        for linea in texto.split("\n"):
            for seg in linea.render(self._consola_muda()):
                out.append((G._pt_de_style(seg.style, self.variante_preview) if seg.style else "", seg.text))
            out.append(("", "\n"))
        return out[:-1] if out else out

    @staticmethod
    def _consola_muda():
        from rich.console import Console
        import io
        return Console(file=io.StringIO(), force_terminal=True, color_system="truecolor",
                       legacy_windows=False, width=200)

    def _lineas_preview(self, e: A.Elemento, t: float) -> list:
        from rich.text import Text
        from . import glow as G
        v = self.variante_preview
        P = lambda id, txt, estado=None: self._pieza(id, txt, estado, t)  # noqa: E731
        R = lambda id: A.estilo_resuelto(id, v)  # noqa: E731
        g = e.grupo
        L = []
        if g == "banner":
            arte = R("banner.arte")
            if arte.visible:
                L.extend(G.gradiente_lineas("banner.arte", list(MUESTRA_GATO), t=t, variante=v))
            marco = R("banner.marco")
            tit = A.texto("banner.marco", "titulo")
            sub = A.texto("banner.marco", "subtitulo")
            if marco.visible:
                caja = {"rounded": "╭─ ", "square": "┌─ ", "heavy": "┏━ ", "double": "╔═ ", "none": "   "}.get(marco.glifo or "rounded", "╭─ ")
                lin = Text()
                lin.append_text(P("banner.marco", caja))
                lin.append_text(P("banner.marco", tit, "titulo"))
                lin.append_text(P("banner.marco", " v4.9.0", "version"))
                lin.append_text(P("banner.marco", f" — {sub}", "subtitulo"))
                L.append(lin)
            guia = R("banner.guia")
            if guia.visible:
                lin = Text()
                lin.append_text(P("banner.guia", A.texto("banner.guia", "cabecera") + "  ", "cabecera"))
                lin.append_text(P("banner.guia", "/hacer "))
                lin.append_text(P("banner.guia", A.texto("banner.guia", "hacer"), "descripcion"))
                L.append(lin)
            lm = R("banner.linea_modelo")
            if lm.visible:
                L.append(P("banner.linea_modelo", f"{A.texto('banner.linea_modelo', 'modelo')} qwythos-27b (:8080)   "
                                                  f"{A.texto('banner.linea_modelo', 'modo')} auto   "
                                                  f"{A.texto('banner.linea_modelo', 'tema')} {v}"))
        elif g in ("prompt", "barra", "menu"):
            marco = R("prompt.marco")
            et = R("prompt.etiqueta")
            fl = R("prompt.flecha")
            barra = R("barra.estado")
            sep = barra.separador or " · "
            regla = (marco.glifo or "─") * self.ancho
            etiqueta_txt = " " + A.texto("prompt.etiqueta")

            def regla_con_etiqueta():
                if et.visible and et.posicion == "arriba":
                    lin = Text()
                    lin.append_text(P("prompt.marco", (marco.glifo or "─") * 2))
                    lin.append_text(P("prompt.etiqueta", etiqueta_txt + " "))
                    lin.append_text(P("prompt.marco", (marco.glifo or "─") * max(0, self.ancho - 3 - len(etiqueta_txt))))
                    return lin
                return P("prompt.marco", regla)

            def linea_barra():
                lin = Text()
                lin.append_text(P("barra.estado", sep.join(MUESTRA_BARRA)))
                lin.append_text(Text("  "))
                lin.append_text(P("barra.modo", A.texto("barra.modo", "plan"), "plan"))
                return lin
            if barra.visible and barra.posicion == "arriba":
                L.append(linea_barra())
            if marco.visible and (marco.posicion or "ambos") in ("ambos", "arriba"):
                L.append(regla_con_etiqueta())
            lin = Text()
            if et.visible and et.posicion != "arriba":
                lin.append_text(P("prompt.etiqueta", etiqueta_txt))
            if fl.visible:
                lin.append_text(P("prompt.flecha", fl.glifo or "➤ "))
            lin.append_text(P("prompt.texto", "hola gato"))
            L.append(lin)
            if marco.visible and (marco.posicion or "ambos") in ("ambos", "abajo"):
                L.append(P("prompt.marco", regla))
            if barra.visible and barra.posicion != "arriba":
                L.append(linea_barra())
            at = R("barra.atajos")
            if at.visible:
                sep_at = at.separador or " · "
                tx = A.textos("barra.atajos")
                L.append(P("barra.atajos", sep_at.join(f"{k if k != 'historial' else '↑↓'} {x}" for k, x in tx.items())))
            if g == "menu" or e.id.startswith("menu."):
                lin = Text()
                lin.append_text(P("menu.completado", " /hacer   ", "activo"))
                lin.append_text(P("menu.completado", "tarea autonoma ", "meta_activo"))
                L.append(lin)
                lin = Text()
                lin.append_text(P("menu.completado", " /crear   "))
                lin.append_text(P("menu.completado", "genera un programa ", "meta"))
                L.append(lin)
                sel = R("menu.selector")
                lin = Text()
                lin.append_text(P("menu.selector", (sel.glifo or "❯") + " oscuro   ", "activo"))
                lin.append_text(P("menu.selector", "verde profundo", "descripcion"))
                L.append(lin)
            L.append(P("prompt.espera", "corrida 5s  " + A.texto("prompt.espera")))
        elif g == "spinner":
            for id in ("spinner.tool", "spinner.pensar"):
                r = R(id)
                sep = r.separador or " · "
                tx = A.textos(id)
                cuerpo = "Leyendo motor.py…" if id == "spinner.tool" else tx.get("pensando", "pensando…")
                L.append(P(id, f"{r.glifo or '·'} {cuerpo} (12s{sep}~340 {tx.get('tok', 'tok')}{sep}{tx.get('hint', 'ctrl+c corta')})"))
            L.append(P("spinner.comando", A.texto("spinner.comando", "procesando")))
        elif g == "tool":
            lin = Text()
            lin.append_text(P("tool.ok", R("tool.ok").glifo or "●"))
            lin.append_text(Text(" "))
            lin.append_text(P("tool.verbo", "Leyendo"))
            lin.append_text(Text(" "))
            lin.append_text(P("tool.objeto", "motor.py"))
            L.append(lin)
            tr = R("tool.resultado")
            L.append(P("tool.resultado", f"  {tr.glifo or '⎿'} 46 {A.texto('tool.resultado', 'lineas')}"))
            lin = Text()
            lin.append_text(P("tool.error", R("tool.error").glifo or "●"))
            lin.append_text(Text(" "))
            lin.append_text(P("tool.verbo", "Ejecutando"))
            lin.append_text(Text(" "))
            lin.append_text(P("tool.objeto", "pytest -q"))
            L.append(lin)
            lin = Text()
            lin.append_text(P("tool.curso", R("tool.curso").glifo or "·"))
            lin.append_text(Text(" "))
            lin.append_text(P("tool.verbo", "Buscando"))
            L.append(lin)
            if R("tool.intencion").visible:
                L.append(P("tool.intencion", "  Voy a leer el motor para ver el bucle"))
        elif g == "respuesta":
            L.append(P("respuesta.texto", "  Hola gato: esta es la respuesta del modelo."))
            L.append(P("respuesta.markdown", "  # Titulo", "h1"))
            L.append(P("respuesta.markdown", "  codigo inline", "code"))
            L.append(P("respuesta.texto", f"  bloque de codigo (tema {A.texto('respuesta.codigo')})"))
        elif g == "pensando":
            pr = R("pensando.prosa")
            L.append(P("pensando.prosa", f"  {pr.glifo or '∴'} pensando en voz alta sobre el bucle…"))
            pl = R("pensando.plegado")
            L.append(P("pensando.plegado", f"  {pl.glifo or '∴'} {A.texto('pensando.plegado', 'penso')} 4s (ctrl+o muestra)"))
        elif g == "aviso":
            d = R("aviso.degradado")
            L.append(P("aviso.degradado", f"  {d.glifo or '⚠'} {A.texto('aviso.degradado', 'degradado')}estilo: motivo"))
            L.append(P("aviso.degradado", f"  {A.texto('aviso.degradado', 'accion')} accion sugerida"))
            L.append(P("aviso.info", "  aviso tenue"))
            L.append(P("aviso.error", "  error: comando desconocido"))
        elif g == "footer":
            f = R("footer.turno")
            if f.visible:
                sep = f.separador or " · "
                lin = Text("  ")
                lin.append_text(P("footer.turno", f.estados["ok"].glifo or "✓", "ok"))
                lin.append_text(P("footer.turno", f" 12.3s{sep}840 {A.texto('footer.turno', 'tokens')}{sep}3 {A.texto('footer.turno', 'pasos')}"))
                L.append(lin)
        elif g == "panel":
            b = R("panel.borde")
            caja = {"rounded": ("╭", "╮", "╰", "╯", "─", "│"), "square": ("┌", "┐", "└", "┘", "─", "│"),
                    "heavy": ("┏", "┓", "┗", "┛", "━", "┃"), "double": ("╔", "╗", "╚", "╝", "═", "║"),
                    "none": (" ", " ", " ", " ", " ", " ")}.get(b.glifo or "rounded")
            tit = A.texto("panel.titulo", "interacciones")
            lin = Text()
            lin.append_text(P("panel.borde", caja[0] + caja[4] + " "))
            lin.append_text(P("panel.titulo", tit))
            lin.append_text(P("panel.borde", " " + caja[4] * max(1, 40 - len(tit) - 4) + caja[1]))
            L.append(lin)
            lin = Text()
            lin.append_text(P("panel.borde", caja[5] + " "))
            lin.append_text(P("panel.cuerpo", f"{'/hacer tarea corta':<37}"))
            lin.append_text(P("panel.borde", caja[5]))
            L.append(lin)
            L.append(P("panel.borde", caja[2] + caja[4] * 40 + caja[3]))
        elif g == "diff":
            for id, txt in (("diff.mas", "linea nueva"), ("diff.menos", "linea vieja")):
                r = R(id)
                lin = Text()
                lin.append_text(P(id, (r.glifo or "+") + " ", "marca"))
                lin.append_text(P(id, txt))
                L.append(lin)
        elif g == "separador":
            L.append(P("separador.regla", (R("separador.regla").glifo or "─") * self.ancho))
        elif g == "sistema":
            L.append(P("sistema.ok", "  ok: guardado en ~/.cognia/estilo.json"))
            L.append(P("sistema.detalle", "  detalle: 3 elementos cambiados"))
            if R("enlace").visible:
                L.append(P("enlace", "  ~/proy/motor.py:42"))
        elif g == "agentes":
            lin = Text()
            lin.append_text(P("agentes.acento", " agentes "))
            lin.append_text(P("agentes.borde", "│ "))
            lin.append_text(P("agentes.panel", " tarea 1: leyendo motor.py "))
            lin.append_text(P("agentes.borde", " │ "))
            lin.append_text(P("agentes.texto", "F2 vuelve"))
            L.append(lin)
        else:
            L.append(P(e.id, e.nombre))
        return L or [Text("")]

    # ------------------------------------------------------------------
    # Transacciones
    # ------------------------------------------------------------------
    def _push_undo(self, inst: dict) -> None:
        self.pila_undo.append(inst)
        if len(self.pila_undo) > MAX_UNDO:
            del self.pila_undo[0]
        self.pila_redo.clear()

    def _avisos_a_mensaje(self, avisos: list, exito: str) -> None:
        textos = [str(a) for a in avisos]
        self._mensaje = "; ".join(textos) if textos else exito

    def _poner(self, ruta: str, valor, inst=None) -> bool:
        """aspecto.poner con undo: con un 'error' no escribe y lo muestra."""
        id = self.elemento_id
        antes = inst if inst is not None else A.instantanea()
        avisos = A.poner(id, ruta, valor)
        if A.errores(avisos):
            self._avisos_a_mensaje(avisos, "")
            return False
        self._push_undo(antes)
        self._avisos_a_mensaje(avisos, f"{id}.{ruta} = {valor}")
        return True

    def _poner_rapido(self, s: str) -> bool:
        id = self.elemento_id
        antes = A.instantanea()
        try:
            avisos = A.poner_style_string(id, s)
        except Exception as exc:
            self._mensaje = f"error: estilo rapido: {exc}"
            return False
        if A.errores(avisos):
            self._avisos_a_mensaje(avisos, "")
            return False
        self._push_undo(antes)
        self._avisos_a_mensaje(avisos, f"{id} <- {s}")
        return True

    def deshacer(self) -> bool:
        if not self.pila_undo:
            self._mensaje = "nada que deshacer"
            return False
        self.pila_redo.append(A.instantanea())
        A.restaurar(self.pila_undo.pop())
        self._mensaje = f"deshecho ({len(self.pila_undo)} mas)"
        return True

    def rehacer(self) -> bool:
        if not self.pila_redo:
            self._mensaje = "nada que rehacer"
            return False
        self.pila_undo.append(A.instantanea())
        A.restaurar(self.pila_redo.pop())
        self._mensaje = f"rehecho ({len(self.pila_redo)} mas)"
        return True

    def guardar(self) -> bool:
        """Ctrl-S: validar documento() -> callback guardar -> aplicar."""
        doc = A.documento()
        avisos = A.validar(doc)
        if A.errores(avisos):
            self._avisos_a_mensaje(avisos, "")
            return False
        try:
            ruta = self._guardar_cb()
        except Exception as exc:
            self._mensaje = f"error al guardar: {type(exc).__name__}: {exc}"
            return False
        self._doc_guardado = A.documento()
        self.guardado_en = time.strftime("%H:%M")
        self._avisos_a_mensaje(avisos, f"guardado {self.guardado_en}" + (f" en {ruta}" if ruta else ""))
        if self._aplicar_cb is not None:
            try:
                self._aplicar_cb()
            except Exception as exc:
                self._mensaje += f"; aplicar en caliente fallo: {type(exc).__name__}: {exc}"
        return True

    def _cerrar(self, resultado: str) -> None:
        self.cerrado = True
        self.resultado = resultado
        self.modo = "normal"

    def _aplicar_preset_en_memoria(self, indice: int) -> bool:
        if not self._presets:
            return False
        nombre, ruta, origen, nota = self._presets[max(0, min(indice, len(self._presets) - 1))]
        try:
            doc = A.leer_doc(ruta)
            avisos = A.aplicar_en_memoria(doc)
        except A.EstiloInvalido as exc:
            self._mensaje = f"preset '{nombre}' invalido: " + "; ".join(str(a) for a in exc.avisos[:3])
            return False
        except Exception as exc:
            self._mensaje = f"preset '{nombre}': {type(exc).__name__}: {exc}"
            return False
        self._avisos_a_mensaje(avisos, f"preset '{nombre}' aplicado en memoria (Ctrl-S para guardar)")
        return True

    # ------------------------------------------------------------------
    # Teclas
    # ------------------------------------------------------------------
    def tecla(self, nombre: str) -> None:
        """Aplica una tecla (tabla en el docstring del modulo)."""
        if self.cerrado:
            return
        if nombre == " ":
            nombre = "space"
        m = self.modo
        if m == "normal":
            self._tecla_normal(nombre)
        elif m in ("texto", "numero", "rapido", "filtro", "exportar", "preset_nombre"):
            self._tecla_buffer(nombre)
        elif m == "color":
            self._tecla_color(nombre)
        elif m == "glifos":
            self._tecla_lista(nombre, len(GLIFOS_COGNIA), self._elegir_glifo)
        elif m in ("presets", "presets_preview"):
            self._tecla_presets(nombre)
        elif m == "ayuda":
            self.modo = "normal"
        elif m == "confirmar_salir":
            self._tecla_confirmar_salir(nombre)
        elif m == "confirmar_reset":
            if nombre in ("s", "S", "enter", "y"):
                self._push_undo(A.instantanea())
                A.reset()
                self._mensaje = "todo vuelve al default (Ctrl-S para guardar)"
                self.modo = "normal"
            elif nombre in ("n", "N", "esc", "q"):
                self.modo = "normal"
                self._mensaje = "reset cancelado"

    def escribir(self, texto: str) -> None:
        """Teclea un string caracter a caracter (comodidad para tests/P11)."""
        for ch in texto:
            self.tecla(ch)

    # -- modo normal ----------------------------------------------------
    def _mover(self, delta: int) -> None:
        if self.panel == "elementos":
            n = len(self._lista())
            self.cursor_elementos = max(0, min(self.cursor_elementos + delta, n - 1))
            self.cursor_props = min(self.cursor_props, max(0, len(self.props()) - 1))
        else:
            n = len(self.props())
            self.cursor_props = max(0, min(self.cursor_props + delta, n - 1))

    def _tecla_normal(self, k: str) -> None:
        if k in ("down", "j"):
            self._mover(1)
        elif k in ("up", "k"):
            self._mover(-1)
        elif k == "pagedown":
            self._mover(10)
        elif k == "pageup":
            self._mover(-10)
        elif k in ("home", "g"):
            self._mover(-10 ** 6)
        elif k in ("end", "G"):
            self._mover(10 ** 6)
        elif k in ("tab", "s-tab"):
            self.panel = "propiedades" if self.panel == "elementos" else "elementos"
        elif k == "right":
            if self.panel == "elementos":
                self.panel = "propiedades"
            else:
                self._ajustar(+1) or setattr(self, "panel", "elementos")
        elif k == "left":
            if self.panel == "propiedades":
                self._ajustar(-1) or setattr(self, "panel", "elementos")
        elif k == "enter":
            self._enter()
        elif k == "space":
            p = self.prop_actual()
            if self.panel == "propiedades" and p and p.tipo == "bool":
                self._poner(p.ruta, not self._bool_actual(p))
            elif self.panel == "propiedades" and p and p.tipo == "enum":
                self._ajustar(+1)
            elif self.panel == "elementos":
                self._enter()
        elif k in ("+", "="):
            self._ajustar(+1) or self._nota_ajuste()
        elif k == "-":
            self._ajustar(-1) or self._nota_ajuste()
        elif k == "/":
            self.modo = "filtro"
            self.buffer = self.filtro
        elif k == "v":
            i = A.ORDEN_VARIANTES.index(self.variante_preview)
            self.variante_preview = A.ORDEN_VARIANTES[(i + 1) % len(A.ORDEN_VARIANTES)]
            self._mensaje = f"vista previa: variante {self.variante_preview}"
        elif k == "a":
            self._alternar_animacion_global()
        elif k == "A":
            e = self.elemento
            if e and A.Cap.ANIMACION in e.caps:
                est = A.estilo_de(e.id)
                activa = bool(est.animacion and est.animacion.activa)
                self._poner("animacion.activa", not activa)
            else:
                self._mensaje = f"'{e.id if e else '?'}' no tiene animacion"
        elif k == "r":
            e = self.elemento
            if e:
                self._push_undo(A.instantanea())
                A.reset(e.id)
                self._mensaje = f"{e.id}: vuelve al default (Ctrl-S para guardar)"
        elif k == "R":
            self.modo = "confirmar_reset"
        elif k == "c-z":
            self.deshacer()
        elif k == "c-y":
            self.rehacer()
        elif k == "c-s":
            self.guardar()
        elif k in ("c-p", "c-l"):
            self._presets = A.presets_detalle()
            self.cursor_flotante = 0
            self.modo = "presets" if k == "c-p" else "presets_preview"
            self._inst_temporal = A.instantanea() if k == "c-l" else None
            if not self._presets:
                self._mensaje = "no hay presets"
        elif k == "c-n":
            self.modo = "preset_nombre"
            self.buffer = ""
        elif k == "c-e":
            self.modo = "exportar"
            self.buffer = str(A.DIR_COGNIA / "estilo-exportado.json")
        elif k in ("?", "f1"):
            self.modo = "ayuda"
        elif k in ("esc", "q"):
            if self.sucio:
                self.modo = "confirmar_salir"
            else:
                self._cerrar("cerrado")

    def _nota_ajuste(self) -> None:
        p = self.prop_actual()
        if self.panel != "propiedades" or p is None:
            return
        if p.tipo not in ("numero", "enum"):
            self._mensaje = f"'{p.etiqueta}' no se ajusta con +/-: es {p.tipo} (Enter edita)"

    def _ajustar(self, delta: int) -> bool:
        """+/-, ←/→ sobre numero o enum. False si la fila no se ajusta."""
        p = self.prop_actual()
        if self.panel != "propiedades" or p is None:
            return False
        if p.tipo == "numero":
            actual = self._numero_actual(p)
            try:
                actual = float(actual)
            except (TypeError, ValueError):
                actual = 0.0
            nuevo = actual + delta * p.paso
            nuevo = max(p.minimo, min(p.maximo, nuevo))
            if p.paso == int(p.paso):
                nuevo = int(nuevo)
            if nuevo == actual:
                self._mensaje = f"{p.etiqueta}: limite {p.minimo:g}..{p.maximo:g}"
                return True
            self._poner(p.ruta, nuevo)
            return True
        if p.tipo == "enum" and p.opciones:
            actual = self._valor_crudo(p)
            ops = list(p.opciones)
            i = ops.index(actual) if actual in ops else -1
            self._poner(p.ruta, ops[(i + delta) % len(ops)])
            return True
        return False

    def _enter(self) -> None:
        if self.panel == "elementos":
            lista = self._lista()
            if not lista:
                return
            tipo, valor = lista[self.cursor_elementos]
            if tipo == "grupo":
                if valor in self.plegados:
                    self.plegados.discard(valor)
                else:
                    self.plegados.add(valor)
            else:
                self.panel = "propiedades"
            return
        p = self.prop_actual()
        if p is None:
            return
        self._prop_en_edicion = p
        if p.tipo == "bool":
            self._poner(p.ruta, not self._bool_actual(p))
        elif p.tipo == "enum":
            self._ajustar(+1)
        elif p.tipo == "numero":
            self.modo = "numero"
            v = self._numero_actual(p)
            self.buffer = f"{v:g}" if isinstance(v, float) else str(v)
        elif p.tipo in ("texto", "glifo"):
            self.modo = "texto"
            v = self._valor_crudo(p)
            self.buffer = ", ".join(v) if isinstance(v, (list, tuple)) else ("" if v is None else str(v))
        elif p.tipo == "rapido":
            self.modo = "rapido"
            self.buffer = A.a_style_string(A.estilo_de(self.elemento_id))
        elif p.tipo == "color":
            self._abrir_color(p)

    def _alternar_animacion_global(self) -> None:
        nuevo = not self.animacion_global
        if self._poner_config is None:
            self._mensaje = ("animacion global: sin acceso a la config desde aqui; "
                             "usa /estilo animacion on|off")
            return
        try:
            self._poner_config("estilo_animacion", "on" if nuevo else "off")
        except Exception as exc:
            self._mensaje = f"no se pudo escribir la config: {type(exc).__name__}: {exc}"
            return
        self.animacion_global = nuevo
        self._mensaje = f"animacion global {'on' if nuevo else 'off'}"

    # -- buffers --------------------------------------------------------
    def _tecla_buffer(self, k: str) -> None:
        m = self.modo
        if k == "esc":
            if m == "filtro":
                self.filtro = ""
                self.cursor_elementos = 0
            self.buffer = ""
            self.modo = "normal"
            self._mensaje = "cancelado" if m != "filtro" else "filtro limpiado"
            return
        if k == "enter":
            self._confirmar_buffer()
            return
        if k == "c-g" and m == "texto" and self._prop_en_edicion and self._prop_en_edicion.tipo == "glifo":
            self.modo = "glifos"
            self.cursor_flotante = 0
            return
        if k == "backspace":
            self.buffer = self.buffer[:-1]
        elif k == "delete" or k == "c-u":
            self.buffer = ""
        elif k == "space":
            self.buffer += " "
        elif k == "tab":
            return
        elif len(k) == 1 and k.isprintable():
            self.buffer += k
        else:
            return
        if m == "filtro":
            self.filtro = self.buffer
            self.cursor_elementos = 0

    def _confirmar_buffer(self) -> None:
        m = self.modo
        b = self.buffer
        if m == "filtro":
            self.filtro = b
            self.modo = "normal"
            self.panel = "elementos"
            return
        if m == "numero":
            self.modo = "normal"
            self._poner(self._prop_en_edicion.ruta, b.strip())
            return
        if m == "texto":
            self.modo = "normal"
            p = self._prop_en_edicion
            if p.tipo == "glifo" and b and not _codificable(b):
                enc = getattr(sys.stdout, "encoding", None) or "utf-8"
                self._poner(p.ruta, b)
                if "error" not in self._mensaje:
                    self._mensaje += f"; glifo no codificable en {enc}: se usara glifo_ascii"
                return
            self._poner(p.ruta, b)
            return
        if m == "rapido":
            self.modo = "normal"
            self._poner_rapido(b)
            return
        if m == "exportar":
            self.modo = "normal"
            try:
                ruta = A.exportar(b.strip())
                self._mensaje = f"exportado a {ruta}"
            except Exception as exc:
                self._mensaje = f"error al exportar: {type(exc).__name__}: {exc}"
            return
        if m == "preset_nombre":
            self.modo = "normal"
            try:
                ruta = A.guardar_preset(b.strip())
                self._mensaje = f"preset guardado en {ruta}"
            except Exception as exc:
                self._mensaje = f"error al guardar el preset: {exc}"
            return

    # -- listas flotantes ----------------------------------------------
    def _tecla_lista(self, k: str, n: int, elegir) -> None:
        if k in ("down", "j"):
            self.cursor_flotante = min(self.cursor_flotante + 1, max(0, n - 1))
        elif k in ("up", "k"):
            self.cursor_flotante = max(self.cursor_flotante - 1, 0)
        elif k in ("home", "g"):
            self.cursor_flotante = 0
        elif k in ("end", "G"):
            self.cursor_flotante = max(0, n - 1)
        elif k == "enter":
            elegir(self.cursor_flotante)
        elif k in ("esc", "q"):
            self.modo = "texto" if elegir == self._elegir_glifo else "normal"

    def _elegir_glifo(self, i: int) -> None:
        self.buffer = GLIFOS_COGNIA[i]
        self.modo = "texto"
        self._confirmar_buffer()

    def _tecla_presets(self, k: str) -> None:
        n = len(self._presets)
        preview = self.modo == "presets_preview"
        if k in ("down", "j", "up", "k", "home", "end", "g", "G"):
            self._tecla_lista(k, n, lambda i: None)
            if preview and n:
                A.restaurar(self._inst_temporal)
                self._aplicar_preset_en_memoria(self.cursor_flotante)
        elif k == "enter":
            if not n:
                self.modo = "normal"
                return
            if preview:
                A.restaurar(self._inst_temporal)
            antes = A.instantanea()
            if self._aplicar_preset_en_memoria(self.cursor_flotante):
                self._push_undo(antes)
            self._inst_temporal = None
            self.modo = "normal"
        elif k in ("esc", "q"):
            if preview and self._inst_temporal is not None:
                A.restaurar(self._inst_temporal)
                self._mensaje = "preview revertido"
            self._inst_temporal = None
            self.modo = "normal"

    # -- selector de color ---------------------------------------------
    def _abrir_color(self, p: Prop) -> None:
        self.modo = "color"
        actual = self._valor_crudo(p)
        try:
            hexa = A.hex_medible(actual, self.variante_preview) if actual else None
        except Exception:
            hexa = None
        self.color = {"pestana": "refs", "buffer": hexa or "#", "inst": A.instantanea(), "valor": actual}
        refs = self._refs_color()
        self.cursor_flotante = refs.index(actual) if isinstance(actual, str) and actual in refs else 0
        if isinstance(actual, str) and actual.startswith("@mi."):
            self.color["pestana"] = "mi"
            mi = self._mi_color()
            self.cursor_flotante = mi.index(actual) if actual in mi else 0
        elif isinstance(actual, str) and _RE_HEX.match(actual):
            self.color["pestana"] = "hex"

    def _aplicar_color_tentativo(self, valor) -> None:
        """Aplica al mover (contraste vivo en la preview) SIN entrar en undo."""
        A.restaurar(self.color["inst"])
        avisos = A.poner(self.elemento_id, self._prop_en_edicion.ruta, valor)
        self._avisos_a_mensaje(avisos, f"{self._prop_en_edicion.etiqueta}: {valor} (Enter fija)")
        self.color["valor"] = valor

    def _tecla_color(self, k: str) -> None:
        p = self.color.get("pestana", "refs")
        if k == "esc":
            A.restaurar(self.color["inst"])
            self.modo = "normal"
            self._mensaje = "color: sin cambios"
            return
        if k in ("tab", "s-tab"):
            i = PESTANAS_COLOR.index(p)
            self.color["pestana"] = PESTANAS_COLOR[(i + (1 if k == "tab" else -1)) % len(PESTANAS_COLOR)]
            self.cursor_flotante = 0
            return
        if k == "t":
            self._aplicar_color_tentativo("terminal")
            return
        if k == "enter":
            valor = self.color.get("valor")
            if p == "hex":
                b = self.color.get("buffer", "")
                if not _RE_HEX.match(b):
                    self._mensaje = f"error: color invalido '{b}' (forma #rrggbb)"
                    return
                valor = b
            elif p in ("refs", "mi"):
                cands = self._candidatos_color()
                valor = cands[self.cursor_flotante] if cands else valor
            A.restaurar(self.color["inst"])
            self.modo = "normal"
            if valor is None:
                self._mensaje = "color: sin cambios"
                return
            self._poner(self._prop_en_edicion.ruta, valor, inst=self.color["inst"])
            return
        if p == "hex":
            if k == "backspace":
                self.color["buffer"] = self.color["buffer"][:-1]
            elif len(k) == 1 and k.isprintable():
                self.color["buffer"] += k
            else:
                return
            b = self.color["buffer"]
            if _RE_HEX.match(b):
                self._aplicar_color_tentativo(b)
            return
        cands = self._candidatos_color()
        antes = self.cursor_flotante
        self._tecla_lista(k, len(cands), lambda i: None)
        if cands and (self.cursor_flotante != antes or k in ("down", "up", "j", "k")):
            self._aplicar_color_tentativo(cands[self.cursor_flotante])

    # -- salir ----------------------------------------------------------
    def _tecla_confirmar_salir(self, k: str) -> None:
        # Enter NO guarda: un Enter distraido escribia estilo.json (juez visual
        # 2026-08-24). Enter/Esc = volver, igual que /estilo reset (Enter = No).
        if k in ("g", "G"):
            if self.guardar():
                self._cerrar("guardado")
            else:
                self.modo = "normal"
        elif k in ("d", "D"):
            A.restaurar(self._base)
            self._mensaje = "cambios descartados"
            self._cerrar("descartado")
        elif k in ("v", "V", "esc", "q", "enter"):
            self.modo = "normal"


def texto_plano(filas: list) -> str:
    """Las filas [(texto, clase, sel)] como texto plano (puerta / depuracion)."""
    return "\n".join(t for t, _, _ in filas)


def abrir_editor(**kw) -> tuple:
    """Puerta del editor full-screen (P11, cognia/ux/editor_app.py): importa
    prompt_toolkit SOLO aqui, a call-time, para que este modulo siga siendo
    puro. Firma y guardas: editor_app.abrir_editor."""
    from .editor_app import abrir_editor as _abrir
    return _abrir(**kw)
