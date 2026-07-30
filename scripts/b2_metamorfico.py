#!/usr/bin/env python
"""
b2_metamorfico.py — juez METAMÓRFICO: señal sin examen escrito a mano.

PREREG_METAMORFICO_20260730.md.

POR QUÉ EXISTE. Las 7 vías de señal autogenerada probadas comparten un rasgo
estructural: un LLM emite el examen, y su modo de fallo MEDIDO es siempre el
mismo — inventa VALORES que el enunciado no fija (los inventos viven en los
valores de los checks, no en los selectores; palanca medida de los selectores:
7%). Una relación metamórfica no tiene valores: es una relación entre dos
ejecuciones de la MISMA página. "Añadir un ítem y luego quitarlo devuelve el
estado anterior" se comprueba sin saber el precio, sin saber el nombre y sin
haber leído el enunciado. El modo de fallo que mató a las 7 vías no puede
ocurrir aquí por construcción.

Este módulo NO llama a ningún LLM y NO lee ningún enunciado. Recibe una página
y nada más.

LECCIONES YA PAGADAS QUE ESTE ARCHIVO RESPETA (no re-descubrir por las malas):
  - page.evaluate NO tiene timeout en la API sync: una página con JS bloqueante
    cuelga el proceso para siempre (595 s y 719 s de CPU medidos, dos veces en
    dos días). TODO va bajo con_presupuesto.  [[juez-colgado-js-bloqueante]]
  - El snapshot hay que ESTABILIZARLO. Un filtro correcto que reanima un <li>
    desde opacity 0 se lee como "0 de 1" a los 400 ms, y el juez acusó de rotos
    a dos productos SANOS. Se lee hasta que dos lecturas seguidas coinciden.
  - El value de un <input> NO es texto del DOM: innerText ve SIEMPRE vacío un
    campo de formulario (55/55 en páginas sanas). Se lee e.value.
  - Vacuidad: una página MUERTA pasa toda relación inversa trivialmente (si el
    botón no hace nada, S1 = S0 y por tanto S2 = S0). Toda relación exige que
    la acción directa CAMBIE el snapshot; si no cambia, es REPROBADA por
    inactividad, nunca "aprobada".
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from cognia.presupuesto_pared import con_presupuesto, PresupuestoAgotado  # noqa: E402

GENERADOS = RAIZ / "cognia" / "program_creator" / "generated_programs"
SALIDA = GENERADOS / "b2_metamorfico"

PRESUPUESTO_PAGINA = 300        # s de pared por página (la lección del cuelgue)
MS_CARGA = 20000
MS_ASENTAR = 1200
MS_TRAS_ACCION = 350
MS_ESTABLE = 250                # paso del poll de estabilización
MS_ESTABLE_TOPE = 2000          # tope del poll (el juez usa 2500 por aserción)
MAX_PARES = 3                   # pares inversos por página (coste acotado)
MAX_OBSERVAR = 10               # selectores observados


# ── Congelado del entorno no determinista ────────────────────────────────────
# Math.random y Date hacen que dos cargas de la MISMA página difieran, y eso
# convertiría "estado distinto" en ruido en vez de en comportamiento distinto.
# Math.random se sustituye por un PRNG semillado (mulberry32): determinista,
# pero sigue produciendo valores distintos entre sí, así que una página que
# baraja sigue barajando — solo que igual en cada carga.
# El reloj NO se congela: pararlo rompería a un temporizador correcto. Las
# páginas con vida propia se detectan empíricamente (ver _es_animada).
_JS_FREEZE = """
(() => {
  let s = 0x2F6E2B1;
  Math.random = function () {
    s |= 0; s = (s + 0x6D2B79F5) | 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
})()
"""

# Snapshot conductual. Heredado de b2_consenso_conductual._JS_SNAPSHOT (la
# canonización de ahí está MEDIDA: sin ella la firma agrupaba por formato de
# moneda "€0.00" vs "0,00 €" y por nombres de tarjeta, y dos muestras con
# veredicto OPUESTO colisionaban). Añade 'c': las clases, porque un cambio de
# estado suele vivir ahí (una celda revelada, una fila seleccionada) y R1
# necesita verlo.
_JS_SNAPSHOT = """(sel) => {
  const canon = (t) => {
    const s = String(t).trim();
    if (s === '') return '';
    const num = s.replace(/[€$\\s]/g, '').replace(/\\.(?=\\d{3}\\b)/g, '')
                 .replace(',', '.');
    if (/^-?\\d+(\\.\\d+)?$/.test(num)) return String(parseFloat(num));
    const c = s.toLowerCase().replace(/\\s+/g, ' ').trim();
    return c.length <= 10 ? c : 'T';
  };
  const vis = (e) => {
    const cs = getComputedStyle(e);
    if (cs.visibility === 'hidden' || cs.display === 'none') return false;
    if (parseFloat(cs.opacity || '1') < 0.05) return false;
    if (cs.color === cs.backgroundColor) return false;
    return true;
  };
  const els = [...document.querySelectorAll(sel)];
  return {n: els.length,
          v: els.slice(0, 25).map(e => {
            if (e.matches('input[type=checkbox],input[type=radio]'))
              return e.checked ? 'C' : 'U';
            if (!vis(e)) return '~';
            return canon(e.matches('input,textarea,select')
               ? e.value : (e.innerText || ''));
          }),
          d: els.slice(0, 25).map(e =>
            (e.disabled || e.hasAttribute('disabled') ? 'D' : '-')),
          c: els.slice(0, 25).map(e =>
            String(e.className || '').split(/\\s+/).filter(Boolean)
              .sort().join('.'))};
}"""

# Inventario para elegir QUÉ observar sin preguntarle a un LLM: las clases e
# ids que más se repiten son, por construcción, donde vive el estado de la
# lista/grilla/tabla que el producto manipula.
_JS_INVENTARIO_META = """
() => {
  const clases = {}, ids = [];
  document.querySelectorAll('*').forEach(e => {
    String(e.className || '').split(/\\s+/).filter(Boolean)
      .forEach(c => { clases[c] = (clases[c] || 0) + 1; });
    if (e.id) ids.push(e.id);
  });
  return {clases, ids: ids.slice(0, 40)};
}
"""

# Acciones disponibles, leídas del DOM. Se captura el texto Y los atributos que
# suelen llevar la intención (aria-label, title, id, value) porque un botón "+"
# real puede llamarse <button id="mas" aria-label="Añadir">.
#
# El selector es el del juez (_JS_CLICKABLES) y no uno más estrecho: MEDIDO en
# el humo del 30/07, un buscaminas correcto tiene CERO <button> — sus celdas son
# divs con onclick, y con 'button, [role=button]' el instrumento no instanciaba
# ni una sola relación (4/4 NO_CONCLUYENTE).
#
# Y no basta con una lista de tags/clases: MEDIDO en el mismo humo, un
# buscaminas correcto pinta sus celdas como <div class="c"> sin onclick inline
# ni clase reconocible. La señal universal de "esto se clica" en la práctica es
# el cursor:pointer que el propio CSS del producto declara. Se añade a los tags
# semánticos en vez de sustituirlos.
#
# Cada accionable se MARCA con data-mm-idx: el índice tiene que sobrevivir a la
# recarga y ser el mismo para descubrir y para clicar, o R0/R1 clicarían un
# elemento distinto del que analizaron.
_SEL_ACCIONABLE = ('button, [role=button], input[type=button], '
                   'input[type=submit], [onclick], a[href^="#"], '
                   '.tile, .card, .cell, .celda')
_JS_ACCIONES = """
(sel) => {
  const vis = (e) => {
    const cs = getComputedStyle(e);
    if (cs.visibility === 'hidden' || cs.display === 'none') return false;
    const r = e.getBoundingClientRect();
    return r.width >= 1 && r.height >= 1;
  };
  const todos = [...document.querySelectorAll('*')].filter(e =>
      vis(e) && (e.matches(sel) || getComputedStyle(e).cursor === 'pointer'));
  // un contenedor cuyo hijo también es accionable no cuenta: se clica el hijo
  const hojas = todos.filter(e => !todos.some(o => o !== e && e.contains(o)));
  return hojas.slice(0, 60).map((e, i) => {
    e.setAttribute('data-mm-idx', String(i));
    return {
      i,
      txt: (e.innerText || e.value || '').trim().slice(0, 40),
      aria: (e.getAttribute('aria-label') || '').trim().slice(0, 40),
      title: (e.getAttribute('title') || '').trim().slice(0, 40),
      id: (e.id || '').slice(0, 40),
      cls: String(e.className || '').slice(0, 60),
      tag: e.tagName,
      dis: !!(e.disabled || e.hasAttribute('disabled')),
    };
  });
}
"""


# ── Léxico de pares inversos (escrito UNA vez, para todas las tareas) ─────────
# Cada entrada: (regex directo, regex inverso, nombre). El orden importa: se
# prueban de arriba abajo y el primer par que casa gana.
PARES_INVERSOS = [
    (r"\b(a[ñn]adir|agregar|add|nuevo|crear|sumar|incrementar)\b",
     r"\b(quitar|eliminar|borrar|remove|restar|decrementar|del)\b", "anadir/quitar"),
    (r"(^|\W)\+($|\W)", r"(^|\W)[-−–]($|\W)", "mas/menos"),
    (r"\b(deshacer|undo)\b", r"\b(rehacer|redo)\b", "undo/redo"),
    (r"\b(marcar|check|seleccionar)\b", r"\b(desmarcar|uncheck|deseleccionar)\b",
     "marcar/desmarcar"),
    (r"\b(abrir|mostrar|expandir|ver)\b", r"\b(cerrar|ocultar|colapsar)\b",
     "abrir/cerrar"),
    (r"\b(iniciar|start|comenzar|play)\b", r"\b(pausar|pause|detener|stop)\b",
     "iniciar/pausar"),
]

# Acciones de reinicio, para R3.
RE_RESET = re.compile(r"\b(reset|reiniciar|limpiar|borrar todo|nuevo juego|"
                      r"restablecer|clear|vaciar)\b", re.I)


@dataclass
class Violacion:
    relacion: str
    detalle: str


@dataclass
class Dictamen:
    """Veredicto metamórfico de UNA página."""
    pagina: str
    estado: str = "NO_CONCLUYENTE"      # APROBADO | REPROBADO | NO_CONCLUYENTE
    violaciones: list = field(default_factory=list)
    relaciones_instanciadas: int = 0
    relaciones_ok: int = 0
    animada: bool = False
    motivo_infra: str = ""
    segundos: float = 0.0
    detalle_acciones: dict = field(default_factory=dict)

    def a_dict(self) -> dict:
        d = asdict(self)
        d["violaciones"] = [asdict(v) if not isinstance(v, dict) else v
                            for v in self.violaciones]
        return d


# ── Motor ────────────────────────────────────────────────────────────────────

def _abrir(p, html: Path):
    nav = p.chromium.launch(headless=True)
    page = nav.new_page(viewport={"width": 1280, "height": 900})
    page.add_init_script(_JS_FREEZE)
    page.goto(html.resolve().as_uri(), wait_until="load", timeout=MS_CARGA)
    page.wait_for_timeout(MS_ASENTAR)
    return nav, page


def _recargar(page, html: Path) -> None:
    """
    Reset duro al estado inicial: re-goto (el init script se re-aplica).

    Re-marca los accionables: data-mm-idx no sobrevive a la navegación, y sin
    volver a ponerlo _click no encontraría nada tras la primera recarga.
    """
    page.goto(html.resolve().as_uri(), wait_until="load", timeout=MS_CARGA)
    page.wait_for_timeout(MS_ASENTAR)
    try:
        page.evaluate(_JS_ACCIONES, _SEL_ACCIONABLE)
    except Exception:
        pass


def _observar_auto(page) -> list:
    """
    Qué selectores mirar, decidido por FRECUENCIA en el DOM. Sin LLM.

    Siempre se incluyen los campos de formulario (su estado no está en el
    texto) y los elementos con id (el enunciado los declara obligatorios).
    """
    try:
        inv = page.evaluate(_JS_INVENTARIO_META)
    except Exception:
        inv = {"clases": {}, "ids": []}
    clases = sorted((inv.get("clases") or {}).items(),
                    key=lambda kv: (-kv[1], kv[0]))
    sels = ["input,textarea,select", "[id]"]
    for c, n in clases:
        if n >= 2 and len(sels) < MAX_OBSERVAR:
            # clases con caracteres raros romperían el querySelectorAll
            if re.fullmatch(r"[A-Za-z_][\w-]*", c):
                sels.append("." + c)
    for extra in ("li", "td", "tr"):
        if len(sels) < MAX_OBSERVAR:
            sels.append(extra)
    return sels[:MAX_OBSERVAR]


def _snap_crudo(page, observar: list) -> str:
    fila = []
    for sel in observar:
        try:
            fila.append(page.evaluate(_JS_SNAPSHOT, sel))
        except Exception:
            fila.append({"err": 1})
    return json.dumps(fila, ensure_ascii=False, sort_keys=True)


def _snap(page, observar: list) -> str:
    """
    Snapshot ESTABILIZADO: se lee hasta que dos lecturas seguidas coinciden.

    Sin esto, una animación CSS de entrada hace que dos snapshots de la misma
    página en el mismo estado difieran, y toda comparación es ruido. Es la
    misma disciplina que _contar_visible del juez, por la misma razón medida.
    """
    previo = _snap_crudo(page, observar)
    gastado = 0
    while gastado < MS_ESTABLE_TOPE:
        page.wait_for_timeout(MS_ESTABLE)
        gastado += MS_ESTABLE
        ahora = _snap_crudo(page, observar)
        if ahora == previo:
            return ahora
        previo = ahora
    return previo


def _es_animada(page, observar: list) -> bool:
    """¿La página cambia sola, sin que nadie actúe? (temporizador, serpiente)"""
    a = _snap(page, observar)
    page.wait_for_timeout(1200)
    return _snap(page, observar) != a


def _click(page, indice: int) -> bool:
    """Click en el i-ésimo elemento accionable. True si aterrizó."""
    try:
        el = page.query_selector(f'[data-mm-idx="{indice}"]')
        if el is None:
            # el producto re-pintó su lista (innerHTML = ...) y se llevó la
            # marca por delante. Se re-marca y se reintenta UNA vez; si la
            # lista cambió de tamaño el índice ya no significa lo mismo, y eso
            # queda declarado como límite del emparejamiento posicional.
            page.evaluate(_JS_ACCIONES, _SEL_ACCIONABLE)
            el = page.query_selector(f'[data-mm-idx="{indice}"]')
        if el is None:
            return False
        el.click(timeout=4000)
        page.wait_for_timeout(MS_TRAS_ACCION)
        return True
    except Exception:
        return False


def _emparejar(acciones: list) -> list:
    """
    Pares (directo, inverso) descubiertos por léxico. Devuelve lista de
    (i_directo, i_inverso, nombre).

    LÍMITE DECLARADO: cuando hay varios "+" (uno por fila de una lista), se
    empareja el k-ésimo directo con el k-ésimo inverso. Es una heurística
    posicional; si el producto ordena sus filas distinto, el par puede cruzar
    filas. Por eso se toman como mucho MAX_PARES y las violaciones se auditan.
    """
    def texto(a: dict) -> str:
        return " ".join([a.get("txt", ""), a.get("aria", ""), a.get("title", ""),
                         a.get("id", ""), a.get("cls", "")])

    pares = []
    for rx_d, rx_i, nombre in PARES_INVERSOS:
        d = [a["i"] for a in acciones
             if not a["dis"] and re.search(rx_d, texto(a), re.I)]
        inv = [a["i"] for a in acciones
               if not a["dis"] and re.search(rx_i, texto(a), re.I)]
        # un botón que casa las DOS caras (p.ej. "mostrar/ocultar") no sirve
        # como par: sería su propio inverso y la relación sería trivial
        d = [i for i in d if i not in inv]
        inv = [i for i in inv if i not in d]
        for k in range(min(len(d), len(inv))):
            pares.append((d[k], inv[k], nombre))
            if len(pares) >= MAX_PARES:
                return pares
    return pares


def _resets(acciones: list) -> list:
    return [a["i"] for a in acciones
            if not a["dis"] and RE_RESET.search(
                " ".join([a.get("txt", ""), a.get("aria", ""),
                          a.get("title", ""), a.get("id", "")]))]


# ── Relaciones ───────────────────────────────────────────────────────────────

def _r1_inversa(page, html, observar, pares, dic: Dictamen) -> None:
    """S0 --A--> S1 --A⁻¹--> S2, exige S2 == S0. Con precondición de actividad."""
    for (i_d, i_i, nombre) in pares:
        _recargar(page, html)
        s0 = _snap(page, observar)
        if not _click(page, i_d):
            continue                                  # la acción no existe ya
        s1 = _snap(page, observar)
        if s1 == s0:
            dic.relaciones_instanciadas += 1
            dic.violaciones.append(Violacion(
                f"R1[{nombre}]",
                "INACTIVIDAD: la accion directa no cambia el estado"))
            continue
        if not _click(page, i_i):
            continue
        s2 = _snap(page, observar)
        dic.relaciones_instanciadas += 1
        if s2 == s0:
            dic.relaciones_ok += 1
        else:
            dic.violaciones.append(Violacion(
                f"R1[{nombre}]",
                "A seguido de su inversa NO devuelve el estado inicial"))


def _r3_reset(page, html, observar, pares, resets, dic: Dictamen) -> None:
    """Actuar y luego reset devuelve al estado inicial exacto."""
    if not resets or not pares:
        return
    i_reset = resets[0]
    i_d = pares[0][0]
    _recargar(page, html)
    s0 = _snap(page, observar)
    if not _click(page, i_d):
        return
    s1 = _snap(page, observar)
    if s1 == s0:
        dic.relaciones_instanciadas += 1
        dic.violaciones.append(Violacion(
            "R3[reset]", "INACTIVIDAD: la accion previa al reset no cambia nada"))
        return
    if not _click(page, i_reset):
        return
    s2 = _snap(page, observar)
    dic.relaciones_instanciadas += 1
    if s2 == s0:
        dic.relaciones_ok += 1
    else:
        dic.violaciones.append(Violacion(
            "R3[reset]", "reset NO devuelve al estado inicial"))


def _r4_determinismo(page, html, observar, pares, dic: Dictamen) -> None:
    """La misma secuencia desde cero da el mismo estado. Solo si no es animada."""
    if dic.animada or not pares:
        return
    i_d = pares[0][0]
    estados = []
    for _ in range(2):
        _recargar(page, html)
        if not _click(page, i_d):
            return
        estados.append(_snap(page, observar))
    dic.relaciones_instanciadas += 1
    if estados[0] == estados[1]:
        dic.relaciones_ok += 1
    else:
        dic.violaciones.append(Violacion(
            "R4[determinismo]",
            "la misma secuencia desde cero da estados distintos"))


def _r5_conmutatividad(page, html, observar, pares, dic: Dictamen) -> None:
    """A;B == B;A para dos acciones DIRECTAS distintas."""
    if dic.animada or len(pares) < 2:
        return
    a, b = pares[0][0], pares[1][0]
    if a == b:
        return
    finales = []
    for orden in ((a, b), (b, a)):
        _recargar(page, html)
        s0 = _snap(page, observar)
        if not (_click(page, orden[0]) and _click(page, orden[1])):
            return
        s = _snap(page, observar)
        if s == s0:
            return                                    # nada pasó: no instancia
        finales.append(s)
    dic.relaciones_instanciadas += 1
    if finales[0] == finales[1]:
        dic.relaciones_ok += 1
    else:
        dic.violaciones.append(Violacion(
            "R5[conmutatividad]", "A;B y B;A dejan estados distintos"))


def _r0_actividad(page, html, observar, acciones, dic: Dictamen) -> None:
    """
    Todo control HABILITADO produce algún efecto observable.

    POR QUÉ ES LA RELACIÓN MÁS VALIOSA DE ESTE CATÁLOGO (y por qué se añadió
    tras el humo del 30/07): las relaciones de par (R1, R3) solo instancian si
    el léxico encuentra la pareja, y MEDIDO en el humo, `carrito_stock` tiene
    botones `.add` y ningún inverso — 0 pares, 0 relaciones. R0 no necesita
    par ni léxico: se aplica a cualquier producto interactivo.

    Y ataca un modo de fallo REAL ya observado a mano en este repo: en
    `turnos_capacidad` "el botón de apuntar simplemente no crea el grupo".

    LÍMITE DECLARADO: hay controles legítimamente inertes (un submit que la
    validación bloquea, un "siguiente" en la última página). Por eso el
    veredicto de R0 se audita como todos los demás, y su FP se mide en el lado
    de CALIBRACIÓN antes de congelar el catálogo.
    """
    candidatos = [a for a in acciones if not a["dis"]][:MAX_CONTROLES_R0]
    if not candidatos:
        return
    inertes = []
    for a in candidatos:
        _recargar(page, html)
        s0 = _snap(page, observar)
        if not _click(page, a["i"]):
            continue
        if _snap(page, observar) == s0:
            etiqueta = (a.get("txt") or a.get("aria") or a.get("id")
                        or a.get("cls") or f"#{a['i']}")[:30]
            inertes.append(etiqueta)
    dic.relaciones_instanciadas += 1
    dic.detalle_acciones["controles_probados_r0"] = len(candidatos)
    if inertes:
        dic.violaciones.append(Violacion(
            "R0[actividad]",
            f"{len(inertes)}/{len(candidatos)} controles habilitados no "
            f"producen ningun cambio observable: {inertes}"))
    else:
        dic.relaciones_ok += 1


MAX_CONTROLES_R0 = 6

RELACIONES_ACTIVAS = {"R0": True, "R1": True, "R3": True, "R4": True,
                      "R5": False}


def dictaminar(html: Path) -> Dictamen:
    """Juzga UNA página. Sin enunciado, sin contrato, sin LLM."""
    from playwright.sync_api import sync_playwright

    dic = Dictamen(pagina=str(html))
    t0 = time.time()
    with sync_playwright() as p:
        nav = None
        try:
            nav, page = _abrir(p, html)
            observar = _observar_auto(page)
            dic.animada = _es_animada(page, observar)
            acciones = page.evaluate(_JS_ACCIONES, _SEL_ACCIONABLE)
            pares = _emparejar(acciones)
            resets = _resets(acciones)
            dic.detalle_acciones = {
                "n_accionables": len(acciones),
                "pares": [{"directo": d, "inverso": i, "nombre": n}
                          for d, i, n in pares],
                "resets": resets,
                "observar": observar,
            }

            if RELACIONES_ACTIVAS["R0"]:
                _r0_actividad(page, html, observar, acciones, dic)
            if RELACIONES_ACTIVAS["R1"]:
                _r1_inversa(page, html, observar, pares, dic)
            if RELACIONES_ACTIVAS["R3"]:
                _r3_reset(page, html, observar, pares, resets, dic)
            if RELACIONES_ACTIVAS["R4"]:
                _r4_determinismo(page, html, observar, pares, dic)
            if RELACIONES_ACTIVAS["R5"]:
                _r5_conmutatividad(page, html, observar, pares, dic)
        except Exception as exc:
            dic.motivo_infra = f"{type(exc).__name__}: {exc}"[:200]
        finally:
            if nav is not None:
                try:
                    nav.close()
                except Exception:
                    pass

    dic.segundos = round(time.time() - t0, 1)
    if dic.motivo_infra:
        dic.estado = "INFRA"
    elif dic.relaciones_instanciadas == 0:
        dic.estado = "NO_CONCLUYENTE"
    elif dic.violaciones:
        dic.estado = "REPROBADO"
    else:
        dic.estado = "APROBADO"
    return dic


def juzgar_con_presupuesto(html: Path) -> Dictamen:
    """dictaminar bajo tope de pared DURO (la lección del juez colgado)."""
    try:
        return con_presupuesto(PRESUPUESTO_PAGINA, dictaminar, html)
    except PresupuestoAgotado as exc:
        d = Dictamen(pagina=str(html), estado="INFRA",
                     motivo_infra=f"presupuesto agotado: {exc}"[:200])
        return d
    except Exception as exc:
        return Dictamen(pagina=str(html), estado="INFRA",
                        motivo_infra=f"{type(exc).__name__}: {exc}"[:200])


def _correr_corpus(args) -> int:
    """Juzga una corrida congelada entera, guardando incremental (--reanudar)."""
    dir_corrida = Path(args.corpus)
    if not dir_corrida.is_absolute():
        dir_corrida = GENERADOS / args.corpus
    items = cargar_corpus(dir_corrida)
    if args.tareas:
        quiero = {t.strip() for t in args.tareas.split(",") if t.strip()}
        items = [i for i in items if i["tarea"] in quiero]

    destino = (Path(args.salida) if args.salida
               else SALIDA / f"{dir_corrida.name}.json")
    destino.parent.mkdir(parents=True, exist_ok=True)
    hechos = {}
    if args.reanudar and destino.exists():
        try:
            hechos = {d["html"]: d for d in
                      json.loads(destino.read_text(encoding="utf-8"))["filas"]}
        except Exception:
            hechos = {}

    filas = []
    t0 = time.time()
    for k, it in enumerate(items, 1):
        if it["html"] in hechos:
            filas.append(hechos[it["html"]])
            continue
        d = juzgar_con_presupuesto(Path(it["html"]))
        fila = {**it, "meta": d.a_dict()}
        filas.append(fila)
        print(f"[{k}/{len(items)}] {it['tarea']:20s} r{it['rep']}s{it['s']} "
              f"gt={it['estricto']}  meta={d.estado:15s} "
              f"rel={d.relaciones_ok}/{d.relaciones_instanciadas} "
              f"{d.segundos:5.1f}s", flush=True)
        destino.write_text(json.dumps(
            {"corpus": str(dir_corrida), "filas": filas},
            ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nTOTAL {len(filas)} paginas en {(time.time()-t0)/60:.1f} min "
          f"-> {destino}")
    return 0


def cargar_corpus(dir_corrida: Path) -> list:
    """
    [(ruta_html, tarea, estricto)] de una corrida congelada.

    Formato `muestras[]` (b2_bon_heldout, *_duro_r2, cabecera*): cada muestra
    trae tarea/rep/s y el veredicto. La carpeta es <tarea>__r<rep>__s<s>.
    Las muestras sin held-out en línea (aprobado_heldout=null, la fase 1 de
    r1 y de las cabeceras) se devuelven con estricto=None: el llamador decide
    si las usa con el contrato original o las descarta.
    """
    res = json.loads((dir_corrida / "resultados.json").read_text(
        encoding="utf-8"))
    salida = []
    for m in res.get("muestras", []):
        carpeta = dir_corrida / f"{m['tarea']}__r{m['rep']}__s{m['s']}"
        html = carpeta / "index.html"
        if not html.exists():
            continue
        if m.get("aprobado_heldout") is None:
            estricto = None
        else:
            estricto = bool(m.get("estricto"))
        salida.append({"html": str(html), "tarea": m["tarea"],
                       "rep": m["rep"], "s": m["s"],
                       "estricto": estricto,
                       "aprobado_orig": bool(m.get("aprobado"))})
    return salida


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("paginas", nargs="*", help="rutas a index.html")
    ap.add_argument("--salida", default=None)
    ap.add_argument("--reanudar", action="store_true")
    ap.add_argument("--corpus", default=None,
                    help="directorio de corrida congelada (usa resultados.json)")
    ap.add_argument("--tareas", default=None,
                    help="coma-separadas: limita a estas tareas")
    args = ap.parse_args(argv)

    if args.corpus:
        return _correr_corpus(args)

    rutas = [Path(x) for x in args.paginas]
    if not rutas:
        print("nada que juzgar", file=sys.stderr)
        return 2

    destino = Path(args.salida) if args.salida else (SALIDA / "humo.json")
    destino.parent.mkdir(parents=True, exist_ok=True)
    hechos = {}
    if args.reanudar and destino.exists():
        hechos = {d["pagina"]: d
                  for d in json.loads(destino.read_text(encoding="utf-8"))}

    salida = []
    for r in rutas:
        if str(r) in hechos:
            salida.append(hechos[str(r)])
            continue
        d = juzgar_con_presupuesto(r)
        salida.append(d.a_dict())
        print(f"{d.estado:16s} rel={d.relaciones_ok}/{d.relaciones_instanciadas} "
              f"anim={int(d.animada)} {d.segundos:5.1f}s  {r}")
        for v in d.violaciones:
            print(f"                 - {v.relacion}: {v.detalle}")
        destino.write_text(json.dumps(salida, ensure_ascii=False, indent=1),
                           encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
