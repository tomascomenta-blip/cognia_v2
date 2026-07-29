"""
juez_ejecutable.py — el arbitro EJECUTA el producto. No lo mira.

POR QUE EXISTE (2026-07-25). El juez del lazo era un VLM de 3B mirando un PNG
(cognia/program_creator/arbitro_visual.py). Caso medido que lo rompe todo:
pulidos/un_juego_de_memoria_4_4_con_piezas_de_an saco 7.5/10 con las 16 cartas
DESTAPADAS desde el primer frame. El VLM vio una cuadricula bonita y firmo. Un
juego de memoria en el que ves todas las cartas no es un juego de memoria.

Eso no es un bug del VLM: es el gradiente. El juez es la unica senal de
aprendizaje del lazo, asi que si premia apariencia el lazo optimiza apariencia —
y es exactamente lo que se ve en los productos: cada vez mas lindos, y siguen
sin funcionar.

Este juez abre el producto en un navegador real (Playwright + Chromium),
INTERACTUA (click, teclado) y comprueba el estado. Devuelve APROBADO/FALLIDO con
la traza de lo que hizo. La estetica sigue puntuando aparte, en arbitro_visual,
pero no entra en el veredicto.

REGLA DURA: un producto FALLIDO no tiene puntaje. `puntaje_ejecucion` es None
cuando no aprueba. Un numero al lado de un producto roto es como se llego a
"7.8/10" para un random-walk; el vacio es mas honesto que el numero.

    python -m cognia.program_creator.juez_ejecutable <ruta a index.html o dir>

El CONTRATO (opcional) vive junto al producto como `.contrato.json` y dice que
tiene que cumplir ESE producto — el estado inicial esperado y las interacciones.
Sin contrato solo corren los checks universales, que detectan una pagina muerta
pero no una mecanica rota: el contrato es lo que hace al juez especifico.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

NOMBRE_CONTRATO = ".contrato.json"

# Tiempo de asentamiento tras cargar: mismo criterio que vista_navegador.py
# (validacion_1_1200ms) — con menos, las animaciones de entrada aun corren y el
# DOM que se mide no es el estado inicial real.
MS_ASENTAR = 1200
MS_TIMEOUT_CARGA = 20000


# ── Resultado ────────────────────────────────────────────────────────────────

@dataclass
class Check:
    nombre: str
    ok: bool
    detalle: str = ""
    critico: bool = False


@dataclass
class Veredicto:
    producto: str
    aprobado: bool = False
    # None cuando NO aprueba: un producto roto no tiene puntaje (ver docstring).
    puntaje_ejecucion: Optional[float] = None
    checks: list = field(default_factory=list)
    traza: list = field(default_factory=list)
    motivo: str = ""
    con_contrato: bool = False
    error: str = ""

    def a_dict(self) -> dict:
        d = asdict(self)
        d["checks"] = [asdict(c) if not isinstance(c, dict) else c
                       for c in self.checks]
        return d

    @property
    def estado(self) -> str:
        """
        APROBADO exige contrato. Sin contrato el juez solo puede decir VIVO:
        carga, tiene contenido y reacciona. Llamar "aprobado" a eso es el mismo
        error de siempre con otra palabra.
        """
        if not self.aprobado:
            return "FALLIDO"
        return "APROBADO" if self.con_contrato else "VIVO"

    def resumen(self) -> str:
        estado = self.estado
        nota = (f"{self.puntaje_ejecucion:.1f}/10"
                if self.puntaje_ejecucion is not None else "sin puntaje")
        return f"{estado} ({nota}) — {self.motivo}"


# ── JS de medicion (corre dentro de la pagina) ───────────────────────────────

# "Muestra su contenido" = tiene texto Y ese texto se VE. Un juego de memoria
# correcto tapa el simbolo con color:transparent / visibility:hidden / opacity:0,
# asi que mirar solo textContent daria un falso positivo.
_JS_CON_TEXTO_VISIBLE = """
(sel) => Array.from(document.querySelectorAll(sel)).filter(el => {
    const t = (el.innerText || el.textContent || '').trim();
    if (!t) return false;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none') return false;
    if (parseFloat(cs.opacity || '1') < 0.05) return false;
    if (cs.color === 'rgba(0, 0, 0, 0)' || cs.color === 'transparent') return false;
    if (cs.color === cs.backgroundColor) return false;
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return false;
    return true;
}).length
"""

# Huella del DOM: sirve para decir "algo cambio tras el click" sin saber que.
_JS_HUELLA = """
() => {
    const partes = [];
    document.querySelectorAll('*').forEach(el => {
        partes.push(el.tagName + '|' + (el.className || '') + '|' +
                    (el.textContent || '').slice(0, 40));
    });
    return partes.join('\\n').length + ':' + partes.length + ':' +
           document.body.innerText.trim().slice(0, 2000);
}
"""

_JS_CLICKABLES = """
() => document.querySelectorAll(
    'button, a[href], [onclick], input, select, .tile, .card, [role=button]'
).length
"""


# ── Motor ────────────────────────────────────────────────────────────────────

def _contar_visible(page, selector: str, estable_ms: int = 250,
                    tope_ms: int = 2500) -> int:
    """
    Cuantos elementos MUESTRAN su texto, esperando a que la cifra se ESTABILICE.

    POR QUE el poll y no una lectura seca (medido 2026-07-25, tercer fallo del
    juez): en un filtro de lista correcto, al volver a mostrar un <li> que
    estaba en display:none la animacion CSS de entrada se reinicia desde
    opacity 0. Leyendo a los 400ms se veian 0 de 1 y 4 de 5 — y el juez acusaba
    de rotos a dos productos que funcionaban (UIGEN y gpt-oss escribieron ambos
    un filtro correcto). Se lee hasta que dos lecturas seguidas coinciden.

    No enmascara fallos reales: un estado que nunca cambia es estable desde la
    primera lectura, y los checks que esperan un cambio diferido (una carta que
    se vuelve a tapar) lo piden con un paso "esperar" explicito.
    """
    previo = int(page.evaluate(_JS_CON_TEXTO_VISIBLE, selector))
    gastado = 0
    while gastado < tope_ms:
        page.wait_for_timeout(estable_ms)
        gastado += estable_ms
        ahora = int(page.evaluate(_JS_CON_TEXTO_VISIBLE, selector))
        if ahora == previo:
            return ahora
        previo = ahora
    return previo


def _ejecutar_paso(page, paso: dict, traza: list) -> Check:
    """
    Un paso del contrato. Acciones soportadas (las que un LLM puede escribir):

      click            selector, indice=0
      tecla            key ('ArrowUp', 'Enter', 'a'...)
      esperar          ms
      contar           selector, esperado|min|max         (cuantos existen)
      contar_visible   selector, esperado|min|max         (cuantos MUESTRAN texto)
      texto            selector, contiene                 (texto de un elemento)
      existe           selector
      no_existe        selector
      js               expr, esperado (opcional)          (escotilla de escape)
    """
    # Forma anidada {"nombre":..., "critico":..., "acciones":[{...}, {...}]}.
    # Se soporta porque es la que produce el pensador (gpt-oss-20b) por su
    # cuenta al generar contratos, y es la correcta: un CHECK ("la tecla derecha
    # cambia la ciudad") suele necesitar varias acciones. El check pasa solo si
    # pasan todas.
    if isinstance(paso.get("acciones"), list):
        nombre = paso.get("nombre") or "check"
        critico = bool(paso.get("critico", False))
        detalles = []
        for sub in paso["acciones"]:
            r = _ejecutar_paso(page, {**sub, "nombre": f"{nombre} >",
                                      "critico": False}, traza)
            detalles.append(r.detalle)
            if not r.ok:
                traza.append(f"  FALLA {nombre} :: {r.detalle}")
                return Check(nombre, False, r.detalle, critico)
        return Check(nombre, True, "; ".join(detalles[-2:]), critico)

    accion = (paso.get("accion") or "").strip()
    nombre = paso.get("nombre") or accion
    critico = bool(paso.get("critico", False))
    sel = paso.get("selector", "")

    def ok(detalle=""):
        traza.append(f"  OK   {nombre} :: {detalle}")
        return Check(nombre, True, detalle, critico)

    def falla(detalle):
        traza.append(f"  FALLA {nombre} :: {detalle}")
        return Check(nombre, False, detalle, critico)

    def _comparar(valor: int, etiqueta: str) -> Check:
        if "esperado" in paso:
            esp = int(paso["esperado"])
            return (ok(f"{etiqueta}={valor} (esperado {esp})") if valor == esp
                    else falla(f"{etiqueta}={valor}, esperaba {esp}"))
        if "min" in paso and valor < int(paso["min"]):
            return falla(f"{etiqueta}={valor}, minimo {paso['min']}")
        if "max" in paso and valor > int(paso["max"]):
            return falla(f"{etiqueta}={valor}, maximo {paso['max']}")
        return ok(f"{etiqueta}={valor}")

    try:
        if accion == "click":
            elems = page.query_selector_all(sel)
            i = int(paso.get("indice", 0))
            if len(elems) <= i:
                return falla(f"no hay elemento {i} para '{sel}' "
                             f"(encontrados {len(elems)})")
            elems[i].click(timeout=5000)
            page.wait_for_timeout(int(paso.get("tras_ms", 400)))
            return ok(f"click en '{sel}'[{i}]")

        if accion == "tecla":
            page.keyboard.press(paso.get("key", "Enter"))
            page.wait_for_timeout(int(paso.get("tras_ms", 400)))
            return ok(f"tecla {paso.get('key')}")

        if accion == "escribir":
            el = page.query_selector(sel)
            if el is None:
                return falla(f"no existe el campo '{sel}'")
            el.fill(str(paso.get("texto", "")))
            page.wait_for_timeout(int(paso.get("tras_ms", 400)))
            return ok(f"escrito {paso.get('texto')!r} en '{sel}'")

        if accion == "esperar":
            page.wait_for_timeout(int(paso.get("ms", 500)))
            return ok(f"espera {paso.get('ms', 500)}ms")

        if accion == "contar":
            return _comparar(len(page.query_selector_all(sel)), f"count('{sel}')")

        if accion == "contar_visible":
            return _comparar(_contar_visible(page, sel), f"visibles('{sel}')")

        if accion == "texto":
            el = page.query_selector(sel)
            if el is None:
                return falla(f"no existe '{sel}'")
            txt = (el.inner_text() or "").strip()
            if "contiene" in paso:
                sub = str(paso["contiene"])
                return (ok(f"'{txt[:60]}' contiene '{sub}'") if sub in txt
                        else falla(f"'{txt[:60]}' no contiene '{sub}'"))
            return ok(f"texto='{txt[:60]}'")

        if accion == "existe":
            return (ok(f"existe '{sel}'") if page.query_selector(sel)
                    else falla(f"no existe '{sel}'"))

        if accion == "no_existe":
            return (ok(f"no existe '{sel}'") if not page.query_selector(sel)
                    else falla(f"existe '{sel}' y no deberia"))

        if accion == "js":
            valor = page.evaluate(f"() => ({paso['expr']})")
            if "esperado" in paso:
                return (ok(f"js={valor!r}") if valor == paso["esperado"]
                        else falla(f"js={valor!r}, esperaba {paso['esperado']!r}"))
            return (ok(f"js={valor!r}") if valor else falla(f"js={valor!r} (falsy)"))

        return falla(f"accion desconocida: {accion!r}")

    except Exception as exc:
        return falla(f"excepcion: {type(exc).__name__}: {exc}")


def juzgar_web(html: Path, contrato: Optional[dict] = None,
               headless: bool = True) -> Veredicto:
    """Abre el HTML en Chromium real, corre los checks y devuelve el veredicto."""
    html = Path(html).resolve()
    v = Veredicto(producto=str(html))
    if not html.is_file():
        v.error = f"no existe {html}"
        v.motivo = "el producto no existe"
        return v

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        v.error = "playwright no instalado en este venv"
        v.motivo = ("sin Playwright no hay juez ejecutable -- instalar con: "
                    "venv312\\Scripts\\python.exe -m pip install playwright && "
                    "python -m playwright install chromium")
        return v

    errores_js: list = []
    traza = v.traza

    with sync_playwright() as p:
        navegador = p.chromium.launch(headless=headless)
        page = navegador.new_page(viewport={"width": 1280, "height": 900})
        page.on("pageerror", lambda e: errores_js.append(str(e)))
        page.on("console", lambda m: errores_js.append(f"console.error: {m.text}")
                if m.type == "error" else None)

        # ── checks universales ────────────────────────────────────────────
        try:
            page.goto(html.as_uri(), wait_until="load",
                      timeout=MS_TIMEOUT_CARGA)
            page.wait_for_timeout(MS_ASENTAR)
            traza.append(f"  cargado {html.name}")
            v.checks.append(Check("carga", True, "la pagina carga", critico=True))
        except Exception as exc:
            v.checks.append(Check("carga", False, f"{type(exc).__name__}: {exc}",
                                  critico=True))
            v.motivo = "la pagina no carga"
            navegador.close()
            return _cerrar(v)

        v.checks.append(Check(
            "sin_errores_js", not errores_js,
            "; ".join(errores_js[:3]) if errores_js else "sin excepciones"))

        try:
            texto = page.evaluate("() => document.body.innerText.trim()")
            elementos = page.evaluate("() => document.body.querySelectorAll('*').length")
        except Exception:
            texto, elementos = "", 0
        # Umbral BAJO a proposito: este check pregunta "¿hay algo?", no "¿hay
        # bastante?". Con 20 chars / 15 elementos (calibrado mirando dashboards)
        # vetaba productos SANOS: un contador correcto —con sus 13 checks de
        # contrato en verde— tiene 5 chars de texto visible ("0 + -") y 5
        # elementos, y salia FALLIDO por un critico mio. Medido 2026-07-25.
        # Un juez que reprueba lo que funciona es tan inutil como uno que
        # aprueba lo que no.
        hay = len(texto) >= 1 or elementos >= 3
        v.checks.append(Check("contenido", hay,
                              f"{len(texto)} chars de texto, {elementos} elementos",
                              critico=True))

        # Interactivo: clickear el primer clickable y ver si el DOM cambia.
        # Una pagina que no reacciona a nada no es un producto, es una captura.
        try:
            n_click = int(page.evaluate(_JS_CLICKABLES))
            if n_click == 0:
                v.checks.append(Check("interactivo", False,
                                      "no hay ningun elemento clickeable"))
            else:
                antes = page.evaluate(_JS_HUELLA)
                page.query_selector(
                    "button, a[href], [onclick], input, .tile, .card, [role=button]"
                ).click(timeout=4000)
                page.wait_for_timeout(600)
                despues = page.evaluate(_JS_HUELLA)
                v.checks.append(Check(
                    "interactivo", antes != despues,
                    f"{n_click} clickeables; el DOM "
                    f"{'cambia' if antes != despues else 'NO cambia'} al clickear"))
        except Exception as exc:
            v.checks.append(Check("interactivo", False,
                                  f"{type(exc).__name__}: {exc}"))

        # ── contrato ──────────────────────────────────────────────────────
        if contrato and contrato.get("pasos"):
            v.con_contrato = True
            traza.append(f"  contrato: {contrato.get('nombre', 'sin nombre')}")
            # Se recarga: los checks universales ya clickearon y ensuciaron el
            # estado inicial, que es justo lo que el contrato va a medir.
            page.goto(html.as_uri(), wait_until="load", timeout=MS_TIMEOUT_CARGA)
            page.wait_for_timeout(MS_ASENTAR)
            for paso in contrato["pasos"]:
                v.checks.append(_ejecutar_paso(page, paso, traza))

        navegador.close()

    return _cerrar(v)


def _cerrar(v: Veredicto) -> Veredicto:
    """Calcula veredicto y puntaje a partir de los checks."""
    criticos_fallados = [c for c in v.checks if c.critico and not c.ok]
    v.aprobado = not criticos_fallados

    if not v.aprobado:
        v.puntaje_ejecucion = None      # regla dura: roto = sin puntaje
        v.motivo = "falla critica: " + "; ".join(
            f"{c.nombre} ({c.detalle})" for c in criticos_fallados[:3])
        return v

    univ = [c for c in v.checks if c.nombre in
            ("carga", "sin_errores_js", "contenido", "interactivo")]
    resto = [c for c in v.checks if c not in univ]

    if not resto:
        # SIN CONTRATO no hay puntaje. Los checks universales solo dicen que la
        # pagina esta VIVA (carga, tiene contenido, reacciona a un click) — no
        # que haga lo que se pidio. Poner un numero ahi seria repetir el error
        # que se acaba de cortar: 7.5/10 a un juego de memoria con las 16 cartas
        # destapadas era exactamente eso, un juicio de apariencia con forma de
        # nota. Sin especificacion no hay medida.
        v.puntaje_ejecucion = None
        v.motivo = ("VIVO pero SIN CONTRATO: nadie verifico su mecanica. "
                    f"universales {sum(1 for c in univ if c.ok)}/{len(univ)}")
        return v

    p_univ = 4.0 * (sum(1 for c in univ if c.ok) / len(univ)) if univ else 0.0
    p_resto = 6.0 * (sum(1 for c in resto if c.ok) / len(resto))
    v.puntaje_ejecucion = round(p_univ + p_resto, 1)
    v.motivo = (f"{sum(1 for c in v.checks if c.ok)}/{len(v.checks)} checks OK "
                f"({sum(1 for c in resto if c.ok)}/{len(resto)} del contrato)")
    return v


# ── Contratos ────────────────────────────────────────────────────────────────

def cargar_contrato(ruta: Path) -> Optional[dict]:
    """Busca .contrato.json junto al producto (o en su directorio)."""
    ruta = Path(ruta)
    dirs = [ruta if ruta.is_dir() else ruta.parent]
    for d in dirs:
        f = d / NOMBRE_CONTRATO
        if f.is_file():
            try:
                return json.loads(f.read_text(encoding="utf-8"))
            except Exception as exc:
                print(f"[juez] contrato ilegible en {f}: {exc}", file=sys.stderr)
    return None


def entrypoint_web(ruta: Path) -> Optional[Path]:
    """El HTML a juzgar: la ruta misma, o index.html dentro del directorio."""
    ruta = Path(ruta)
    if ruta.is_file() and ruta.suffix.lower() in (".html", ".htm"):
        return ruta
    if ruta.is_dir():
        for nombre in ("index.html", "programa.html", "program.html"):
            if (ruta / nombre).is_file():
                return ruta / nombre
        htmls = sorted(ruta.glob("*.html"))
        if htmls:
            return htmls[0]
    return None


def juzgar(ruta: Path, headless: bool = True) -> Veredicto:
    """Punto de entrada: resuelve el HTML y su contrato, y juzga."""
    html = entrypoint_web(ruta)
    if html is None:
        v = Veredicto(producto=str(ruta))
        v.motivo = "no encontre HTML que juzgar (¿es un producto Python? " \
                   "ese camino lo cubre cognia/autoprueba.py)"
        v.error = "sin entrypoint web"
        return v
    return juzgar_web(html, cargar_contrato(ruta), headless=headless)


# ── Generacion de contratos ──────────────────────────────────────────────────

_JS_INVENTARIO = """
() => {
    const clases = {}, ids = [], tags = {};
    document.querySelectorAll('*').forEach(el => {
        tags[el.tagName.toLowerCase()] = (tags[el.tagName.toLowerCase()] || 0) + 1;
        if (el.id) ids.push('#' + el.id);
        (el.className && typeof el.className === 'string' ? el.className : '')
            .split(/\\s+/).filter(Boolean).forEach(c => {
                clases['.' + c] = (clases['.' + c] || 0) + 1;
            });
    });
    return {clases, ids: ids.slice(0, 40), tags};
}
"""

_SISTEMA_CONTRATO = (
    # "Reasoning: low" es la directiva Harmony de esfuerzo para gpt-oss. Sin
    # ella, ESTE prompt lo manda a una espiral de overthinking medida el
    # 2026-07-26: 13k chars de razonamiento a max_tokens=3000 (contenido: 0) y
    # 33k a 9000 (contenido: 395, aun length). Con ella termina en ~2900
    # tokens con JSON valido. Para modelos sin Harmony es una linea inerte.
    "Reasoning: low\n\n"
    "Eres un ingeniero de QA. Escribes contratos de prueba EJECUTABLES para "
    "productos web. Respondes SOLO con JSON valido, sin explicaciones ni fences."
)

_PLANTILLA_CONTRATO = """\
Escribe el contrato de prueba para este producto.

IDEA PEDIDA: {idea}

SELECTORES QUE EXISTEN EN LA PAGINA (inventario del DOM, con cuantos hay):
{inventario}

Escribe los hechos que ESTE producto tiene que cumplir para que la idea este
cumplida de verdad. Piensa en el ESTADO INICIAL correcto y en que pasa al
INTERACTUAR. No escribas checks de estetica. No escribas checks que se cumplan
solos (como "existe el body").

Acciones disponibles:
  {{"accion":"contar","selector":".x","esperado":N}}            cuantos existen
  {{"accion":"contar_visible","selector":".x","esperado":N}}    cuantos MUESTRAN texto visible

  "esperado" es igualdad EXACTA. Para "al menos N" usa {{"min":N}}; para "como
  mucho N" usa {{"max":N}}. Medido 2026-07-25: escribir "esperado":1 queriendo
  decir "al menos 1" hizo fallar productos SANOS — el contrato estaba mal, no
  el producto.

  NUNCA inventes el valor literal de un texto que no puedas deducir del
  inventario (nombres de ciudad, cifras, titulos). Un {{"contiene":"City"}}
  contra una pagina que dice "Madrid, ES" acusa al producto de un error tuyo.
  Si no sabes el literal, comprueba la FORMA (que no este vacio, que tenga una
  unidad, que CAMBIE tras la interaccion) en vez del contenido.

  EXCEPCION unica: si la IDEA declara selectores OBLIGATORIOS (un id o class
  concreto), usalos en los checks AUNQUE no aparezcan en el inventario. Que
  falten es un fallo del PRODUCTO, no del contrato — un contador que la idea
  exige con <span id="valor"> y no lo tiene esta mal aunque muestre numeros.

  {{"accion":"click","selector":".x","indice":0}}
  {{"accion":"tecla","key":"ArrowRight"}}
  {{"accion":"texto","selector":"#x","contiene":"..."}}
  {{"accion":"existe","selector":".x"}}  /  {{"accion":"no_existe","selector":".x"}}
  {{"accion":"esperar","ms":1000}}
  {{"accion":"js","expr":"document.querySelectorAll('.x').length","esperado":N}}

Cada paso lleva "nombre" (que afirma) y "critico": true si el producto NO SIRVE
sin eso.

ESCRIBE COMO MUCHO 8 PASOS. Un JSON de una sola linea por paso. Nada mas.

Responde SOLO este JSON:
{{"nombre": "...", "pasos": [ ... ]}}
"""

# Variante AMPLIA (dirección CodeRM, arXiv:2501.01054: más aserciones por
# contrato = +5-8 pp, y los modelos chicos se benefician más). Medido el
# 2026-07-27 (PREREG_CONTRATO_AMPLIO_20260727.md): con la plantilla clásica
# de ≤8 pasos el sello interno queda al nivel del AZAR contra el examen del
# banco en tareas composicionales (FP 32-50%, FN 50%, n=196) — los contratos
# del banco tienen 14-24 pasos y los bugs composicionales aparecen en el
# paso 10+. Esta plantilla NO reemplaza a la clásica hasta que el A/B
# pre-registrado la apruebe: se selecciona con generar_contrato(modo=).
_PLANTILLA_CONTRATO_AMPLIO = _PLANTILLA_CONTRATO.replace(
    "ESCRIBE COMO MUCHO 8 PASOS. Un JSON de una sola linea por paso. Nada mas.",
    """\
COBERTURA OBLIGATORIA (un examen corto aprueba productos rotos):
- ENUMERA mentalmente las reglas de la idea; CADA regla lleva al menos un check.
- El ESTADO INICIAL exacto lleva su check ANTES de la primera interaccion.
- Una regla de HISTORIA (cascada, tope, limite, undo, "no puede volver a...")
  se prueba con una SECUENCIA de al menos 6 acciones encadenadas, y se
  comprueba el estado DESPUES de la secuencia, no solo tras el primer paso.
- Al menos un check NEGATIVO: algo que NO debe pasar (un tope que no se
  supera, un boton deshabilitado que no actua, un estado que no retrocede).

ESCRIBE ENTRE 10 Y 16 PASOS. Un JSON de una sola linea por paso. Nada mas.""")


# Variante CORREGIDA (PREREG_SENAL_CONTRATO_20260727.md, resultado 1a).
# La medición de FN por tipo de paso sobre 48 contratos en disco encontró que
# el peor tipo es estructural, no estocástico: la aserción de texto sobre un
# <input> falla SIEMPRE (55/55 en páginas sanas, 0/6 de acierto en rotas —
# inner_text de un campo de formulario es vacío) y el pensador la usa porque
# la plantilla no le documenta la acción `escribir` (0 de 48 contratos la
# usan; los pasos "Ingresar valor..." improvisan con `texto`/`contiene`).
# Además 7/24 contratos clásicos no marcan NINGÚN paso critico y aprueban
# por vacuidad. Fixes que entraron por la regla pre-registrada: F1 (escribir
# documentado + Tab), F2 (leer inputs con js .value), F5 (criticidad).
# NO reemplaza a la clásica hasta que su A/B pase: generar_contrato(modo=).
_PLANTILLA_CONTRATO_CORREGIDO = _PLANTILLA_CONTRATO.replace(
    """  {{"accion":"click","selector":".x","indice":0}}
  {{"accion":"tecla","key":"ArrowRight"}}
  {{"accion":"texto","selector":"#x","contiene":"..."}}""",
    """  {{"accion":"click","selector":".x","indice":0}}
  {{"accion":"tecla","key":"ArrowRight"}}
  {{"accion":"escribir","selector":"#x","texto":"..."}}
  {{"accion":"texto","selector":"#x","contiene":"..."}}

  Para ESCRIBIR en un campo usa "escribir". "texto" NO escribe: solo LEE y
  compara. "escribir" deja el campo ENFOCADO: si el producto reacciona al
  salir del campo, pulsa despues {{"accion":"tecla","key":"Tab"}}.

  El VALOR de un <input>/<textarea>/<select> NO es texto del DOM: "texto" y
  "contar_visible" lo ven SIEMPRE vacio, aunque el campo tenga contenido.
  Un valor de campo se lee con js:
  {{"accion":"js","expr":"document.querySelector('#x').value","esperado":"..."}}""").replace(
    """Cada paso lleva "nombre" (que afirma) y "critico": true si el producto NO SIRVE
sin eso.""",
    """Cada paso lleva "nombre" (que afirma) y "critico": true si el producto NO SIRVE
sin eso. Los pasos que verifican la mecanica que la idea exige LLEVAN
"critico": true. Un contrato donde ningun paso es critico no verifica nada:
se aprueba solo, este roto o no.""")


# Validador de aserciones contra el ENUNCIADO (séptima enmienda de
# PREREG_SENAL_CONTRATO_20260727.md). El FN residual del contrato
# autogenerado son expectativas INVENTADAS (literales supuestos, formatos
# no dictados, posiciones de elementos aleatorios) que acusan a páginas
# sanas. El validador ve SOLO la idea y los pasos — nunca la página ni el
# inventario: no puede re-anclar al DOM.
_SISTEMA_VALIDADOR = (
    "Reasoning: low\n\n"
    "Eres un auditor de contratos de prueba. Respondes SOLO con JSON "
    "valido, sin explicaciones ni fences.")

_PLANTILLA_VALIDADOR = """\
Un contrato de prueba se genero para esta idea. Audita CADA paso: ¿el
enunciado de la idea EXIGE lo que el paso afirma?

IDEA PEDIDA: {idea}

PASOS DEL CONTRATO (numerados):
{pasos}

Un paso se CONSERVA solo si la idea lo exige: estado inicial dictado,
comportamiento pedido, selector declarado OBLIGATORIO, valor que el
enunciado dicta literalmente o que se deduce con certeza de sus reglas.
Un paso se DESCARTA si afirma algo que la idea NO pide: literales
supuestos (textos, cifras, posiciones concretas de elementos aleatorios),
formatos que el enunciado no dicta, comportamientos imaginados.

Responde SOLO este JSON:
{{"conservar": [numeros de los pasos que la idea exige]}}
"""


def _validar_contra_enunciado(idea: str, contrato: dict) -> dict:
    """
    Filtra los pasos que el enunciado no exige. NUNCA puede ser peor que
    el contrato sin filtrar por plomeria: ante fallo del pensador, JSON
    invalido, <2 pasos supervivientes o cero criticos supervivientes, se
    devuelve el contrato ORIGINAL tal cual (fallback declarado en el
    prereg).
    """
    from ..llm_local import generar

    pasos = contrato.get("pasos", [])
    lineas = "\n".join(
        f"  {i + 1}. {json.dumps(p, ensure_ascii=False)[:220]}"
        for i, p in enumerate(pasos))
    crudo = generar(
        _PLANTILLA_VALIDADOR.format(idea=idea, pasos=lineas),
        system=_SISTEMA_VALIDADOR, temperature=0.0,
        # la respuesta util son ~30 chars; el resto es presupuesto de
        # PENSAMIENTO ([[presupuesto-tokens-razonamiento]], margen 2-3x)
        max_tokens=6000, via="juez.validar_contrato", timeout=400,
        reasoning_effort="low")
    if not crudo:
        return contrato
    txt = crudo.strip()
    if "```" in txt:
        txt = txt.split("```")[1]
        txt = txt[4:] if txt.lstrip().startswith("json") else txt
    ini, fin = txt.find("{"), txt.rfind("}")
    if ini < 0 or fin <= ini:
        return contrato
    try:
        indices = json.loads(txt[ini:fin + 1]).get("conservar", [])
        keep = [pasos[i - 1] for i in indices
                if isinstance(i, int) and 1 <= i <= len(pasos)]
    except Exception:
        return contrato
    if len(keep) < 2 or not any(
            isinstance(p, dict) and p.get("critico") for p in keep):
        return contrato
    return {**contrato, "pasos": keep,
            "_validado": {"antes": len(pasos), "despues": len(keep)}}


def inventario_dom(html: Path) -> dict:
    """Que selectores hay en la pagina. Estructura, nunca logica."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        nav = p.chromium.launch(headless=True)
        page = nav.new_page()
        page.goto(Path(html).resolve().as_uri(), wait_until="load",
                  timeout=MS_TIMEOUT_CARGA)
        page.wait_for_timeout(MS_ASENTAR)
        inv = page.evaluate(_JS_INVENTARIO)
        nav.close()
    return inv


def generar_contrato(idea: str, html: Path,
                     modo: str = "clasico") -> Optional[dict]:
    """
    Pide al pensador el contrato de ESTE producto, a partir de la IDEA.

    Deliberadamente NO se le pasa el codigo: si el juez se escribe leyendo la
    implementacion, el producto se pone su propio examen y lo aprueba siempre —
    que es como un juego de memoria con las cartas destapadas saco 7.5.
    Solo se le da el inventario de selectores, para que los pasos sean
    ejecutables contra ESTE DOM.

    modo: "clasico" (≤8 pasos, el de produccion), "amplio" (10-16 pasos,
    CodeRM; A/B dio GRIS — PREREG_CONTRATO_AMPLIO_20260727.md), "corregido"
    (clasico + escribir/inputs/criticidad; su A/B dio KILL doble) o
    "validado" (clasico + filtro de aserciones contra el ENUNCIADO;
    séptima enmienda de PREREG_SENAL_CONTRATO_20260727.md).
    """
    from ..llm_local import generar

    inv = inventario_dom(html)
    clases = sorted(inv.get("clases", {}).items(), key=lambda kv: -kv[1])[:25]
    texto_inv = "\n".join(f"  {sel}  x{n}" for sel, n in clases)
    texto_inv += "\n" + "\n".join(f"  {i}" for i in inv.get("ids", [])[:20])

    plantilla = {"amplio": _PLANTILLA_CONTRATO_AMPLIO,
                 "corregido": _PLANTILLA_CONTRATO_CORREGIDO,
                 }.get(modo, _PLANTILLA_CONTRATO)
    crudo = generar(
        plantilla.format(idea=idea, inventario=texto_inv),
        # 1400 tokens truncaban el JSON a mitad (medido: JSONDecodeError en el
        # char 4693) y el llamador lo veia como "el pensador no produjo nada".
        # 9000 y no 3000: con un pensador de RAZONAMIENTO el presupuesto cubre
        # tambien los tokens de pensamiento — a 3000, gpt-oss con "Reasoning:
        # low" termina en ~2900 y el margen era navaja (finish=length con
        # contenido 0 en 1 de 2 probes); a 6000 aun fallaba ~1 de 2 por la
        # cola de la distribucion de pensamiento. La respuesta util son ~1200
        # chars: el resto del presupuesto es para que el pensador PIENSE.
        # El modo amplio pide 10-16 pasos (~2500 chars de respuesta): margen
        # 2-3x sobre lo observado ([[presupuesto-tokens-razonamiento]]).
        system=_SISTEMA_CONTRATO, temperature=_temp_contrato(),
        max_tokens=12000 if modo == "amplio" else 9000,
        via="juez.generar_contrato", timeout=400,
        # El esfuerzo REAL lo fija el template de llama-server, no la linea
        # "Reasoning: low" del system (medido 2026-07-26 en reparar_web: la
        # linea sola no evito 3 de 3 espirales; el kwarg las cerro 2 de 2).
        # La linea se conserva por si el backend no soporta el kwarg.
        reasoning_effort="low")
    if not crudo:
        return None
    c = _json_de_respuesta(crudo)
    if c is None:
        return None
    if not _pasos_validos(c.get("pasos")):
        print("[juez] contrato con pasos malformados (campo no-string donde "
              "va un string): se descarta", file=sys.stderr)
        return None
    if not any(isinstance(p, dict) and p.get("critico")
               for p in c.get("pasos", [])):
        # Aprobaria por VACUIDAD: _cerrar hace all() sobre los criticos, y
        # sin ninguno el veredicto es APROBADO pase lo que pase. Medido
        # 2026-07-27 (PREREG_SENAL_CONTRATO): 7/24 contratos clasicos en
        # disco sin criticos, y en el A/B del mismo dia las 7 aprobaciones
        # del brazo clasico fueron TODAS vacuas. Un contrato asi es peor que
        # ninguno: sella "APROBADO" sin verificar nada; sin contrato el lazo
        # al menos dice "sin verificar", que es honesto.
        print("[juez] contrato sin ningun paso critico: aprobaria por "
              "vacuidad — se descarta", file=sys.stderr)
        return None
    if modo == "validado":
        c = _validar_contra_enunciado(idea, c)
    return c


def _temp_contrato() -> float:
    """
    Temperatura de la generacion de contratos. 0.2 con gpt-oss (medido: a 0.9
    'interpreta' la idea). Los razonadores Qwen/Nemotron DEGENERAN en bucle de
    repeticion a temperatura baja (medido 2026-07-28: el mismo paso repetido
    hasta agotar 9000 tokens, JSON sin cerrar) y su tarjeta pide 0.6 —
    COGNIA_TEMP_CONTRATO permite dar a cada pensador su decodificacion
    documentada sin tocar el camino por defecto.
    """
    try:
        return float(os.environ.get("COGNIA_TEMP_CONTRATO", "0.2"))
    except ValueError:
        return 0.2


def _json_de_respuesta(crudo: str) -> Optional[dict]:
    """
    Extrae el dict del contrato de la respuesta del pensador.

    Los razonadores estilo Qwen/Nemotron devuelven el pensamiento INLINE
    (<think>...</think>) antes del contrato — y si el pensamiento contiene un
    fence o una llave, el extractor de siempre agarraba basura (medido
    2026-07-28 con OpenReasoning-Nemotron-14B: 'Expecting value: line 1').
    Se corta lo pensado primero; para gpt-oss es un no-op porque su canal de
    razonamiento lo separa el template de llama-server y no llega aqui.
    """
    txt = crudo.strip()
    if "</think>" in txt:
        txt = txt.split("</think>")[-1].strip()
    if "```" in txt:                     # por si ignora la instruccion del fence
        txt = txt.split("```")[1]
        txt = txt[4:] if txt.lstrip().startswith("json") else txt
    ini = txt.find("{")
    if ini < 0:
        return None
    # raw_decode toma el PRIMER objeto balanceado e ignora lo que siga: un
    # razonador que repite basura DESPUES de un contrato completo (medido
    # 2026-07-28 con Nemotron: 'Extra data') ya no invalida el contrato.
    try:
        c, _ = json.JSONDecoder().raw_decode(txt[ini:])
        return c if isinstance(c, dict) else None
    except json.JSONDecodeError as exc:
        print(f"[juez] el pensador no devolvio JSON valido: {exc}",
              file=sys.stderr)
        return None


def _pasos_validos(pasos) -> bool:
    """
    Forma minima de un contrato usable. El pensador a veces devuelve pasos con
    DICTS donde van strings (medido 2026-07-26: 'accion' como dict →
    AttributeError .strip() DENTRO de juzgar_web en cada ronda del lazo: un
    contrato existente pero inusable, peor que ninguno porque bloquea el
    reintento). Un contrato malformado se rechaza aqui y el llamador paga su
    reintento normal.
    """
    if not isinstance(pasos, list) or not pasos:
        return False
    for p in pasos:
        if not isinstance(p, dict):
            return False
        if isinstance(p.get("acciones"), list):
            if not _pasos_validos(p["acciones"]):
                return False
            continue
        for campo in ("accion", "nombre", "selector", "key"):
            v = p.get(campo)
            if v is not None and not isinstance(v, str):
                return False
        # texto numerico es legitimo: el ejecutor lo pasa por str().
        v = p.get("texto")
        if v is not None and not isinstance(v, (str, int, float)):
            return False
    return True


def escribir_contrato(dir_producto: Path, contrato: dict) -> Path:
    f = Path(dir_producto) / NOMBRE_CONTRATO
    f.write_text(json.dumps(contrato, indent=2, ensure_ascii=False),
                 encoding="utf-8")
    return f


def main(argv: list) -> int:
    if not argv:
        print(__doc__)
        return 1

    if argv[0] == "contrato":
        # python -m ...juez_ejecutable contrato <dir> "<idea>"
        d = Path(argv[1])
        idea = argv[2] if len(argv) > 2 else d.name.replace("_", " ")
        html = entrypoint_web(d)
        if html is None:
            print(f"sin HTML en {d}", file=sys.stderr)
            return 1
        c = generar_contrato(idea, html)
        if c is None:
            print("el pensador no produjo contrato (¿hay backend en :8080?)",
                  file=sys.stderr)
            return 1
        print(f"contrato escrito: {escribir_contrato(d, c)}")
        print(json.dumps(c, indent=2, ensure_ascii=False))
        return 0

    v = juzgar(Path(argv[0]), headless="--ver" not in argv)
    print("=" * 72)
    print(f"JUEZ EJECUTABLE — {v.producto}")
    print("=" * 72)
    for c in v.checks:
        marca = "OK   " if c.ok else "FALLA"
        crit = " [CRITICO]" if c.critico else ""
        print(f"  {marca}{crit} {c.nombre}: {c.detalle}")
    if v.traza:
        print("\n  TRAZA")
        for t in v.traza:
            print(f"  {t}")
    print("-" * 72)
    print(v.resumen())
    if not v.con_contrato:
        print("  (sin contrato: solo checks universales — no se verifico la "
              "mecanica especifica de este producto)")
    return 0 if v.aprobado else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
