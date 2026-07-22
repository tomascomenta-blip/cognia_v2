"""
generator.py — Generador de ideas y código para el módulo de programación hobby de Cognia.

CAMBIOS v2:
  - Cognia genera sus PROPIAS ideas usando el LLM (70% del tiempo)
  - Programas NO interactivos: corren solos de inicio a fin
  - Rechaza código que use input() antes de llegar al sandbox
  - Fallback a lista predefinida si el LLM no genera idea válida
"""

import json
import os
import random
import re
import urllib.request as _req
from dataclasses import dataclass
from typing import Callable, List, Optional

from cognia.compresion_salidas import comprimir_error
from cognia.llm_local import generar

# ── Configuración ──────────────────────────────────────────────────────────────

# El camino PRIMARIO es el backend real inyectado por el caller (llm=...):
# run_program_hobby lo construye sobre el orquestador del REPL (llama-server
# GGUF). Le sigue llm_local (detecta llama-server y Ollama) y, como ultimo
# recurso, Ollama directo con OLLAMA_URL (antes hardcodeado a localhost).
OLLAMA_URL   = (os.environ.get("OLLAMA_URL", "http://localhost:11434")
                .rstrip("/") + "/api/generate")
OLLAMA_MODEL = os.environ.get("COGNIA_OLLAMA_MODEL", "llama3.2:1b")
TIMEOUT_SEC  = 500

# Firma del backend inyectable: (prompt, system, max_tokens, temperature) -> texto|None
LlmFn = Callable[[str, str, int, float], Optional[str]]


FALLBACK_CATEGORIES = [
    "ASCII art generator that runs automatically",
    "cellular automata simulator with auto-display",
    "maze generator that solves itself and prints the result",
    "procedural story generator with built-in templates",
    "fractal pattern renderer in terminal",
    "prime number visualizer with ASCII chart",
    "reaction-diffusion pattern simulator",
    "Conway's Game of Life that runs N generations automatically",
    "simple Markov chain text generator with sample corpus",
    "ASCII-based bar chart generator with sample data",
    "number theory explorer that prints interesting patterns",
    "cipher encoder demo with example text",
    "L-system plant generator",
    "sorting algorithm visualizer that shows steps automatically",
    "concept relationship mapper using built-in sample concepts",
    "text similarity analyzer with sample texts",
    "mathematical sequence visualizer",
    "text statistics analyzer with built-in sample paragraph",
    "word association chain generator",
    "knowledge graph demo with sample nodes",
]

COMPLEXITY_HINTS = [
    "Keep it simple, under 60 lines. Must run fully automatically.",
    "Medium complexity, around 80-100 lines. No user input required.",
    "Add configurable constants at the top but no runtime user input.",
    "Use object-oriented design. Run a demo automatically in __main__.",
    "Make it visually interesting using ASCII art or ANSI colors.",
    "Make it data-driven with tunable constants defined at the top.",
    "Demonstrate itself with built-in sample data and print results.",
]


# ── Dataclass de resultado ─────────────────────────────────────────────────────

@dataclass
class GeneratedProgram:
    title:         str
    description:   str
    code:          str
    category:      str
    self_proposed: bool = False
    raw_response:  str  = ""
    lenguaje:      str  = "python"   # "python" | "html"


# ── Deteccion de ideas web ─────────────────────────────────────────────────────
#
# Medido el 2026-07-19: pedirle "pagina web que simule un dashboard de
# inversiones" devolvia un programa Python de terminal con barras ASCII. No era
# un fallo del modelo sino del prompt: _build_prompt exige "Terminal only, no
# GUI" y el parser solo aceptaba fences ```python. El pipeline era incapaz de
# producir una web aunque se la pidieras explicitamente.

# Pistas FUERTES: nombran el artefacto a producir. Si aparecen, es una web.
_PISTAS_WEB = (
    "pagina web", "página web", "web page", "sitio web", "website", "webapp",
    "web app", "aplicacion web", "aplicación web", "landing", "dashboard web",
    "frontend",
)

# Pistas DEBILES: tecnologias que una idea de Python puede nombrar de pasada.
# "html.parser" es stdlib de Python; "browser"/"navegador" salen en cualquier
# scraper. Solo deciden si no hay ninguna senal de que se pide Python.
_PISTAS_WEB_DEBILES = (
    "html", "css", "javascript", "navegador", "browser",
)

# Senales de que lo pedido es un modulo/script de Python, no una pagina.
_PISTAS_PYTHON = (
    "stdlib", "unittest", "pytest", "urllib", "html.parser", "modulo python",
    "módulo python", "funcion python", "función python", "script python",
    "def ", "import ", "libreria python", "librería python",
)


def _es_idea_web(texto: str) -> bool:
    """
    True si la idea pide algo que se ve en un navegador, no en la terminal.

    POR QUE NO ES UNA LISTA PLANA: lo era hasta el 2026-07-20, y casaba "html"
    como subcadena en cualquier posicion. Se pidio un modulo Python de busqueda
    web que mencionaba "html.parser" (que es stdlib de Python) y "respuestas
    HTML de ejemplo": el detector dijo "web", el generador produjo una PAGINA
    que simulaba un buscador, y la vista de navegador se puso a reprochar que
    "no cambia sola" — evaluando una animacion que nadie habia pedido. No fallo
    nada: se entrego con confianza algo que no era lo pedido.

    Cualquier peticion de codigo Python que roce lo web (scraping, cliente
    HTTP, parseo de HTML) caia en la misma trampa.
    """
    t = (texto or "").lower()
    if any(pista in t for pista in _PISTAS_WEB):
        decision = True
    elif any(pista in t for pista in _PISTAS_PYTHON):
        decision = False    # pidieron Python explicitamente: mandan ellos
    else:
        decision = any(pista in t for pista in _PISTAS_WEB_DEBILES)

    # La colonia opina como SEGUNDA VOZ (regla del plan de la flota: el
    # experto no manda hasta que su feromona lo sostenga). Una discrepancia
    # confiada se registra como rastro; la decision sigue siendo de la
    # heuristica. Nunca puede romper la generacion.
    try:
        from ..colonia import feromona, opinar
        clase, confianza = opinar("idea_router", texto or "")
        if clase and confianza >= 0.9:
            opina_web = (clase == "web")
            if opina_web != decision:
                feromona.registrar_discrepancia(
                    "idea_router", texto or "", clase,
                    "web" if decision else "no-web")
                logger_colonia = __import__("logging").getLogger(__name__)
                logger_colonia.info(
                    "Colonia discrepa en idea_router (%.2f): experto=%s "
                    "heuristica=%s", confianza, clase, decision)
            if feromona.el_experto_manda("idea_router"):
                return opina_web
    except Exception:
        pass

    return decision


# ── Generación autónoma de ideas ───────────────────────────────────────────────

def _generate_idea_autonomously(seed_concepts: Optional[list] = None,
                                llm: Optional[LlmFn] = None) -> Optional[str]:
    """Pide al LLM que proponga su propia idea, inspirada en lo que ha aprendido."""
    context = ""
    if seed_concepts and len(seed_concepts) >= 2:
        context = (
            f"You have been learning about: {', '.join(seed_concepts[:8])}. "
            f"You can use these as inspiration or think of something different. "
        )

    prompt = (
        f"You are an AI with a hobby of writing small Python programs. "
        f"{context}\n\n"
        f"Propose ONE original idea for a small Python terminal program. "
        f"IMPORTANT: It must run completely automatically — no user input, no input() calls.\n"
        f"It can be a simulation, visualizer, generator, analyzer, or creative tool.\n\n"
        f"Respond with ONLY the idea in 5-15 words. No explanation.\n"
        f"Example: 'philosophical argument mapper that visualizes logical connections'\n"
        f"Your idea:"
    )

    # Backend real primero (inyectado); llm_local (llama-server→Ollama) despues.
    if llm is not None:
        try:
            raw = llm(prompt, "", 50, 0.95)
            if raw:
                idea = raw.split("\n")[0].strip().strip('"').strip("'").strip(".")
                if 5 < len(idea) < 200:
                    return idea
        except Exception as exc:
            print(f"[generator] backend real fallo generando idea: {exc}")

    texto = generar(prompt, temperature=0.95, max_tokens=50)
    if not texto:
        print("[generator] Sin LLM local: no pude generar idea propia.")
        return None
    idea = texto.split("\n")[0].strip().strip('"').strip("'").strip(".")
    return idea if 5 < len(idea) < 200 else None


def _pick_idea(seed_concepts: Optional[list] = None,
               llm: Optional[LlmFn] = None) -> tuple[str, str, bool]:
    """70% autónoma, 30% fallback a lista predefinida."""
    complexity = random.choice(COMPLEXITY_HINTS)

    if random.random() < 0.70:
        idea = _generate_idea_autonomously(seed_concepts, llm=llm)
        if idea:
            print(f"[generator] 🧠 Idea propia: {idea}")
            return idea, complexity, True

    pool     = _custom_ideas + FALLBACK_CATEGORIES if _custom_ideas else FALLBACK_CATEGORIES
    category = random.choice(pool)
    thematic = ""
    if seed_concepts and len(seed_concepts) >= 2:
        picked   = random.sample(seed_concepts, min(2, len(seed_concepts)))
        thematic = f"Optionally incorporate the themes: {', '.join(picked)}."
    return category, f"{complexity} {thematic}".strip(), False


def _build_prompt(category: str, extra_hint: str) -> str:
    return (
        f"You are a creative Python programmer making small, fun terminal programs.\n\n"
        f"Write a complete Python program for: **{category}**\n\n"
        f"CRITICAL RULES — all must be followed:\n"
        f"- Standard library ONLY (no pip packages, no numpy, no pandas)\n"
        f"- Terminal only, no GUI\n"
        f"- Maximum 180 lines\n"
        f"- NEVER use input(), sys.stdin, or ANY function waiting for user input\n"
        f"- Program must run 100% automatically from start to finish\n"
        f"- Use built-in sample data, constants, or random generation — never ask the user\n"
        f"- Must print visible, interesting output when run with: python program.py\n"
        f"- No file writes outside /tmp\n"
        f"- No network access\n"
        f"- Do NOT import os, subprocess, socket, shutil, signal, ctypes\n"
        f"- To clear terminal: print('\\033[2J\\033[H', end='') NOT os.system\n"
        f"- {extra_hint}\n\n"
        f"Respond EXACTLY in this format:\n\n"
        f"Title: <short title>\n"
        f"Description: <one sentence>\n"
        f"Python Code:\n"
        f"```python\n"
        f"<complete working code>\n"
        f"```"
    )


# ── Completitud contra la idea (campana 2026-07-21) ───────────────────────
# Medido en 20 tareas web duras: el patron nº1 de fallo (11/20) era OMITIR
# componentes pedidos (animaciones, validacion, drag&drop, stepper...) y
# paginas cortas. Estas pistas tecnicas mapean lo que la IDEA pide a la
# evidencia minima que el HTML debe contener; lo que falte entra como defecto
# al bucle de reparacion (mismo canal que los defectos visuales).
_PISTAS_COMPONENTES = [
    (r"drag\s*(and|&)\s*drop|arrastrabl", r"draggable|dragstart",
     "drag and drop pedido: falta draggable/dragstart"),
    (r"localstorage|persistencia", r"localStorage",
     "persistencia pedida: falta localStorage"),
    (r"animad|animacion|animación|keyframes|transicion|transición|parpade",
     r"animation|transition|@keyframes",
     "animacion pedida: no hay animation/transition/@keyframes en el CSS"),
    (r"grafic|gráfic|velas|sparkline|dona|barras|linea de|línea de",
     r"<svg|<canvas|conic-gradient",
     "grafico pedido: no hay <svg>/<canvas>"),
    (r"\bmodal\b", r"modal|<dialog", "modal pedido: no hay modal/dialog"),
    (r"validad|validaci", r"required|pattern=|checkValidity|setCustomValidity",
     "validacion pedida: no hay required/pattern/checkValidity"),
    (r"teclado|flechas del teclado|con escape",
     r"keydown|keyup|ArrowLeft|ArrowRight|Escape",
     "teclado pedido: no hay keydown/Arrow*/Escape"),
    (r"stepper|3 pasos|tres pasos", r"step",
     "stepper/pasos pedidos: no hay steps"),
    (r"formulario", r"<form|<input", "formulario pedido: no hay form/input"),
    (r"cronometro|cronómetro|temporizador|en vivo|actualizandose|cada segundo",
     r"setInterval|requestAnimationFrame",
     "actualizacion en vivo pedida: no hay setInterval/rAF"),
    (r"buscador|busqueda|búsqueda|filtro|filtrar",
     r"filter|includes\(|indexOf|toLowerCase",
     "buscador/filtro pedido: no hay logica de filtrado en JS"),
    (r"\b3d\b|rotan|voltea|volteo|se voltea",
     r"rotateY|rotateX|rotate3d|perspective",
     "efecto 3D pedido: no hay rotateX/rotateY/perspective"),
    (r"ordenar por columna|ordenable", r"sort\(",
     "orden por columna pedido: no hay sort()"),
    (r"colapsable|deslizante|lateral", r"translateX|translateY|width|toggle",
     "panel colapsable/deslizante pedido: no hay mecanica de colapso"),
]


def componentes_faltantes(idea: str, html: str) -> list:
    """Componentes que la IDEA pide y el HTML no evidencia. Cada entrada es
    una pista accionable para el prompt de reparacion."""
    idea_l = (idea or "").lower()
    faltas = []
    for re_idea, re_html, mensaje in _PISTAS_COMPONENTES:
        if re.search(re_idea, idea_l) and not re.search(re_html, html or "",
                                                        re.I):
            faltas.append(mensaje)
    return faltas


def _componentes_de_idea(category: str) -> list:
    """Trocea la idea en sus componentes pedidos (por comas y ' y ') para
    enumerarlos en el prompt como checklist obligatoria."""
    t = re.sub(r"^\s*pagina web (de|del|con)?\s*", "", (category or ""),
               flags=re.I)
    partes = [p.strip(" .") for p in re.split(r",| y (?=[a-z])", t)
              if len(p.strip()) > 8]
    return partes[:10]


def _build_prompt_web(category: str, extra_hint: str) -> str:
    """
    Prompt para paginas web. Un solo index.html autocontenido.

    Sin recursos externos a proposito: el resultado tiene que abrir igual desde
    file:// que servido por Railway, sin CDN que pueda caerse ni pedir red.
    """
    return (
        f"You are a creative front-end developer making self-contained web pages.\n\n"
        f"Write a complete HTML page for: **{category}**\n\n"
        f"CRITICAL RULES — all must be followed:\n"
        f"- ONE single self-contained .html file\n"
        f"- Inline <style> and <script> — no external files\n"
        f"- NO external resources: no CDN, no <link href=http...>, no fetch(), "
        f"no remote images or fonts. It must work fully offline.\n"
        f"- All data simulated in JavaScript (Math.random, setInterval)\n"
        f"- It must ANIMATE on its own: values updating live, no user click needed\n"
        # SVG y no canvas, a proposito: el verificador de navegador puede LEER
        # el contenido de un SVG (¿tiene <text> de ejes?) pero un canvas es
        # una caja opaca de pixeles — la regla de "ejes visibles" quedaba sin
        # policia. Y el canvas estirado por CSS (300x150 -> borroso) es el bug
        # mas repetido del corpus generado.
        f"- Draw charts as inline <svg> — NOT <canvas>, and never a chart "
        f"library\n"
        f"- Responsive and legible on a phone screen\n"
        f"- If you color-code state (up/down, green/red), put the state class on "
        f"the SAME element your CSS selector targets. A rule like `.row.up span` "
        f"only works if the class lands on `.row`, not on the inner span.\n"
        f"- Set colors with a rule that matches the element you actually modify, "
        f"and prefer setting style/class on the element you create in JS\n"
        # Reglas de calidad anadidas el 2026-07-20 tras comparar lado a lado
        # con una pagina de referencia: la de Cognia sacaba 7.7 con un grafico
        # aplastado sin ejes y dos filas de texto. El modelo SI sabe hacerlo
        # mejor: nadie se lo estaba pidiendo.
        f"- Write ALL visible text in the SAME language as the page topic above\n"
        f"- Structure the page in at least 3 distinct sections (for a "
        f"dashboard: summary numbers on top, a chart, and a detail table)\n"
        f"- A chart MUST have visible axis labels (numeric y-axis values) and "
        f"light gridlines. Compute the scale from the data min/max — never "
        f"hardcode the range\n"
        f"- If you use <canvas>: set canvas.width = canvas.clientWidth and "
        f"canvas.height = canvas.clientHeight BEFORE drawing, and redraw on "
        f"resize. A canvas stretched by CSS from its default 300x150 renders "
        f"squashed and blurry. Inline <svg> avoids this entirely and is "
        f"preferred\n"
        f"- Format numbers for humans: thousands separators, 2 decimals, "
        f"currency symbol where money (toLocaleString)\n"
        f"- Render a complete first frame IMMEDIATELY on load — never a blank "
        f"page waiting for the first setInterval tick\n"
        # Campana 2026-07-21 (11/20 fallos por omision): la idea multi-
        # componente se ENUMERA y se exige completa. Paginas grandes valen.
        + "".join(
            f"- REQUIRED component {i}: {c}\n"
            for i, c in enumerate(_componentes_de_idea(category), start=1))
        + f"- Implement EVERY required component above — a page that skips "
        f"any of them is WRONG. Prefer a LONGER page over an incomplete "
        f"one; there is no size limit.\n"
        f"- {extra_hint}\n\n"
        f"Respond EXACTLY in this format:\n\n"
        f"Title: <short title>\n"
        f"Description: <one sentence>\n"
        f"HTML Code:\n"
        f"```html\n"
        f"<!DOCTYPE html>\n"
        f"<complete working page>\n"
        f"```"
    )


_SISTEMA_PYTHON = (
    "You are a creative Python programmer. Write complete, runnable programs "
    "using only the standard library. NEVER use input() or blocking calls - "
    "programs must run automatically. Follow the output format exactly."
)

_SISTEMA_WEB = (
    "You are a creative front-end developer. Write complete, self-contained "
    "HTML pages with inline CSS and JavaScript and no external resources. "
    "The page must animate by itself on load. Follow the output format exactly."
)


_SYSTEM_CODER = (
    "You are a creative Python programmer. Write complete, runnable programs "
    "using only the standard library. NEVER use input() or blocking calls — "
    "programs must run automatically. Follow the output format exactly."
)

# Firma del backend inyectable: (prompt, system, max_tokens, temperature) -> texto|None
LlmFn = Callable[[str, str, int, float], Optional[str]]


def _call_ollama(prompt: str) -> Optional[str]:
    try:
        payload = json.dumps({
            "model":   OLLAMA_MODEL,
            "prompt":  prompt,
            "system":  _SYSTEM_CODER,
            "stream":  False,
            "options": {"temperature": 0.90, "num_predict": 2000, "top_p": 0.95}
        }).encode("utf-8")

        request = _req.Request(OLLAMA_URL, data=payload,
                               headers={"Content-Type": "application/json"})
        with _req.urlopen(request, timeout=TIMEOUT_SEC) as resp:
            data = json.loads(resp.read())
            return data.get("response", "").strip()
    except Exception as exc:
        print(f"[generator] Ollama call failed: {exc}")
        return None


def _call_llm(prompt: str, lenguaje: str = "python",
              temperature: float = 0.90,
              llm: "Optional[LlmFn]" = None) -> Optional[str]:
    """
    UN solo camino de LLM, unificado en el merge 4.0: backend inyectado
    (cognia-x: funciona pip-instalado sobre el orquestador) → llm_local
    (main: detecta llama-server con draft especulativo) → Ollama directo.

    temperature 0.90 por defecto porque GENERAR es creativo; las reparaciones
    pasan 0.2 — a 0.9 el modelo "repara" reescribiendo media pagina (medido
    2026-07-20: 3 rondas descartadas con "no mejoraba").
    """
    system = _SISTEMA_WEB if lenguaje == "html" else _SISTEMA_PYTHON
    if llm is not None:
        try:
            raw = llm(prompt, system, 6000, temperature)
            if raw:
                return raw
        except Exception as exc:
            print(f"[generator] backend real fallo: {exc}")
    texto = generar(
        prompt,
        system=system,
        temperature=temperature,
        # 2000 tokens truncaban programas con tests: el fence ni se cerraba y
        # el lazo de reparacion gastaba sus intentos en "falta el resto".
        max_tokens=6000,
    )
    if texto:
        return texto
    return _call_ollama(prompt)


def reparar_python(program: GeneratedProgram, error: str) -> Optional[GeneratedProgram]:
    """
    Le devuelve el traceback al modelo para que corrija su propio programa.

    Hasta ahora un fallo no se reparaba: se regeneraba desde cero y se perdia
    todo el trabajo. Documentado en planes/AUTOPROGRAMACION_COGNIA.md (G1) con
    un caso medido: un task manager de 114 LOC con SQLite, pila de undo y 4
    tests reales, generado en 22.5 s, murio en el sandbox y se descarto entero
    sin un solo intento de arreglo.

    El patron ya existia en game_manager.py:508 (_fix_runtime_error) pero
    hablaba con Ollama por URL hardcodeada, que en esta maquina no existe:
    aqui va por llm_local, que detecta el backend real.
    """
    if not error or not error.strip():
        return None

    # comprimir_error en vez de error[:600]: el corte a lo bruto se quedaba la
    # cabecera del traceback y tiraba la ultima linea, que es donde dice que
    # fallo. Al modelo hay que darle el mensaje, no las rutas de los frames.
    prompt = (
        f"This Python program failed when executed. Fix it.\n\n"
        f"ERROR:\n{comprimir_error(error)}\n\n"
        f"BROKEN CODE:\n```python\n{program.code[:4000]}\n```\n\n"
        f"Rules:\n"
        f"- Fix the actual cause of the error, do not delete the feature.\n"
        f"- Standard library only. No input(). Must run start to finish alone.\n"
        f"- Keep everything that already worked.\n\n"
        f"Respond EXACTLY in this format:\n\n"
        f"Title: {program.title}\n"
        f"Description: {program.description}\n"
        f"Python Code:\n```python\n<fixed code>\n```"
    )

    raw = _call_llm(prompt, "python", temperature=0.2)
    if not raw:
        return None

    arreglado = _parse_response(raw, program.category, "python")
    if arreglado is None:
        return None

    arreglado.self_proposed = program.self_proposed
    return arreglado


def reparar_web(program: GeneratedProgram, defectos: List[str]) -> Optional[GeneratedProgram]:
    """
    Le devuelve al modelo los defectos VISTOS en el navegador para que corrija.

    La diferencia con pedirle "revisa tu codigo" es que aqui los defectos son
    observaciones, no sospechas: la pagina se renderizo y esto es lo que hizo.
    El caso que motivo esto ("todo el texto sale del mismo color") es
    invisible leyendo el HTML, porque el HTML es valido.
    """
    if not defectos:
        return None

    lista = "\n".join(f"- {d}" for d in defectos)
    prompt = (
        f"This HTML page was rendered in a real browser and these problems were "
        f"OBSERVED (not guessed):\n{lista}\n\n"
        f"Fix ONLY those problems. Keep the design and the rest of the code.\n"
        f"Remember: a rule like `.row.up span` only applies if the class 'up' "
        f"lands on the element matching `.row`, not on the inner span.\n\n"
        f"Current page:\n```html\n{program.code}\n```\n\n"
        f"Respond EXACTLY in this format:\n\n"
        f"Title: {program.title}\n"
        f"Description: {program.description}\n"
        f"HTML Code:\n```html\n<!DOCTYPE html>\n<fixed page>\n```"
    )

    raw = _call_llm(prompt, "html", temperature=0.2)
    if not raw:
        return None

    arreglado = _parse_response(raw, program.category, "html")
    if arreglado is None:
        return None

    arreglado.self_proposed = program.self_proposed
    return arreglado


def _parse_response(raw: str, category: str,
                    lenguaje: str = "python") -> Optional[GeneratedProgram]:
    if not raw:
        return None

    # Los modelos con razonamiento (UIGEN-X) anteponen <think>...</think>.
    # Medido el 2026-07-20: con UIGEN de generador, las DOS reparaciones de la
    # sesion fallaron con "no devolvio una correccion valida" — el bloque de
    # pensamiento rompia el parseo de Title/Description/fence. La respuesta
    # real viene despues del cierre.
    if "</think>" in raw:
        raw = raw.split("</think>", 1)[1]

    # El fence depende del lenguaje pedido. Se acepta tambien el fence pelado
    # (```) porque el modelo lo omite a veces, pero solo si ya estamos dentro
    # del bloque de codigo esperado.
    fence_abre = "```html" if lenguaje == "html" else "```python"

    lines, title, desc, code_lines, in_code = raw.splitlines(), "", "", [], False
    abrio_fence = False

    for line in lines:
        s = line.strip()
        if s.lower().startswith("title:"):
            title = s[6:].strip()
        elif s.lower().startswith("description:"):
            desc = s[12:].strip()
        elif s.lower().startswith(fence_abre):
            in_code = True
            abrio_fence = True
        elif s == "```" and in_code:
            in_code = False
        elif in_code:
            code_lines.append(line)

    # Fence abierto y nunca cerrado = la respuesta se corto por limite de
    # tokens. Antes se aceptaba el trozo y el sandbox devolvia un SyntaxError
    # enganoso, contra el que el lazo de reparacion gastaba sus tres intentos
    # sin poder ganar. Truncado no es codigo con un bug: es codigo incompleto,
    # y lo que corresponde es regenerar.
    if abrio_fence and in_code:
        print("[generator] ⚠️  Respuesta truncada (fence sin cerrar): regenero.")
        return None

    code = "\n".join(code_lines).strip()
    if not title:
        title = f"Untitled {category.title()}"
    if not desc:
        desc = f"A small {category} program."
    if len(code) < 30:
        return None

    if lenguaje == "html":
        # Sin <html> no es una pagina, es un fragmento suelto.
        if "<html" not in code.lower():
            print("[generator] ⚠️  Rechazado: no es un documento HTML completo.")
            return None
    else:
        # Rechazar programas que usen input() — el sandbox los mataría igual
        code_lines_clean = [l for l in code.splitlines()
                            if not l.strip().startswith("#")]
        if any("input(" in l for l in code_lines_clean):
            print("[generator] ⚠️  Rechazado: usa input() — debe ser no-interactivo.")
            return None

    return GeneratedProgram(title=title, description=desc, code=code,
                            category=category, raw_response=raw,
                            lenguaje=lenguaje)


# ── Ideas personalizadas ───────────────────────────────────────────────────────

_custom_ideas: list[str] = []

def get_custom_ideas() -> list[str]:   return list(_custom_ideas)
def get_all_ideas()     -> list[str]:  return list(_custom_ideas) + list(FALLBACK_CATEGORIES)

def add_custom_idea(idea: str) -> bool:
    idea = idea.strip()
    if not idea: return False
    if any(e.lower() == idea.lower() for e in _custom_ideas): return False
    _custom_ideas.append(idea)
    return True

def remove_custom_idea(idea: str) -> bool:
    for i, e in enumerate(_custom_ideas):
        if e.lower() == idea.strip().lower():
            _custom_ideas.pop(i); return True
    return False

def clear_custom_ideas() -> int:
    n = len(_custom_ideas); _custom_ideas.clear(); return n


# ── API pública ────────────────────────────────────────────────────────────────

def generate_program(seed_concepts: Optional[list] = None,
                     forced_idea:   Optional[str]  = None,
                     llm:           Optional[LlmFn] = None) -> Optional[GeneratedProgram]:
    """Genera un programa. Intenta idea autónoma primero, fallback a lista predefinida.

    llm: backend real inyectado por el caller (run_program_hobby lo construye
    sobre el orquestador del REPL); sin él se intenta Ollama (OLLAMA_URL)."""
    self_proposed = False

    if forced_idea:
        category, extra_hint = forced_idea.strip(), random.choice(COMPLEXITY_HINTS)
    else:
        category, extra_hint, self_proposed = _pick_idea(seed_concepts, llm=llm)

    if not self_proposed:
        print(f"[generator] 💡 Idea: {category}")

    # Una idea de pagina web no se puede satisfacer con un script de terminal:
    # cambia el prompt, el fence esperado y mas adelante la verificacion.
    lenguaje = "html" if _es_idea_web(category) else "python"
    if lenguaje == "html":
        print("[generator] 🌐 Idea web detectada: genero HTML autocontenido.")

    # Los patrones probados como guia: aprender de lo que ya paso la revision,
    # sin copiarlo. Es la diferencia entre pedirle al modelo que invente el
    # grafico desde cero (y recaiga en los NaN y los canvas aplastados de
    # siempre) y ensenarle uno que ya sobrevivio a la sonda y al critico.
    if lenguaje == "html":
        from .patrones import elegir_patrones
        patrones = elegir_patrones(category, max_n=3)
        if patrones:
            extra_hint += (
                "\n\nPROVEN PATTERNS from pages that already passed browser "
                "checks and professional review. ADAPT their techniques to "
                "this idea — do NOT copy them verbatim; change data, labels, "
                "colors and layout to fit:\n"
                + "\n".join(f"--- {n} ---\n{c}" for n, c in patrones))

    prompt  = (_build_prompt_web(category, extra_hint) if lenguaje == "html"
               else _build_prompt(category, extra_hint))
    raw     = _call_llm(prompt, lenguaje, llm=llm)
    program = _parse_response(raw, category, lenguaje) if raw else None

    if raw is None:
        print("[generator] ⚠️  Sin backend LLM vivo (ni orquestador ni Ollama). "
              "Instala el modelo con 'cognia install-model'.")
        return None
    if program is None:
        print("[generator] ⚠️  No se pudo parsear o fue rechazado.")
        return None

    program.self_proposed = self_proposed
    print(f"[generator] ✅ Programa generado: '{program.title}'")
    return program
