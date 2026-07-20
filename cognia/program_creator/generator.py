"""
generator.py — Generador de ideas y código para el módulo de programación hobby de Cognia.

CAMBIOS v2:
  - Cognia genera sus PROPIAS ideas usando el LLM (70% del tiempo)
  - Programas NO interactivos: corren solos de inicio a fin
  - Rechaza código que use input() antes de llegar al sandbox
  - Fallback a lista predefinida si el LLM no genera idea válida
"""

import json
import random
import urllib.request as _req
from dataclasses import dataclass
from typing import List, Optional

from cognia.compresion_salidas import comprimir_error
from cognia.llm_local import generar

# ── Configuración ──────────────────────────────────────────────────────────────

TIMEOUT_SEC  = 500

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
        return True
    if any(pista in t for pista in _PISTAS_PYTHON):
        return False        # pidieron Python explicitamente: mandan ellos
    return any(pista in t for pista in _PISTAS_WEB_DEBILES)


# ── Generación autónoma de ideas ───────────────────────────────────────────────

def _generate_idea_autonomously(seed_concepts: Optional[list] = None) -> Optional[str]:
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

    texto = generar(prompt, temperature=0.95, max_tokens=50)
    if not texto:
        print("[generator] Sin LLM local: no pude generar idea propia.")
        return None
    idea = texto.split("\n")[0].strip().strip('"').strip("'").strip(".")
    return idea if 5 < len(idea) < 200 else None


def _pick_idea(seed_concepts: Optional[list] = None) -> tuple[str, str, bool]:
    """70% autónoma, 30% fallback a lista predefinida."""
    complexity = random.choice(COMPLEXITY_HINTS)

    if random.random() < 0.70:
        idea = _generate_idea_autonomously(seed_concepts)
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
        f"- Draw charts with <canvas> or inline <svg> — never a chart library\n"
        f"- Responsive and legible on a phone screen\n"
        f"- If you color-code state (up/down, green/red), put the state class on "
        f"the SAME element your CSS selector targets. A rule like `.row.up span` "
        f"only works if the class lands on `.row`, not on the inner span.\n"
        f"- Set colors with a rule that matches the element you actually modify, "
        f"and prefer setting style/class on the element you create in JS\n"
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


def _call_llm(prompt: str, lenguaje: str = "python") -> Optional[str]:
    return generar(
        prompt,
        system=_SISTEMA_WEB if lenguaje == "html" else _SISTEMA_PYTHON,
        temperature=0.90,
        # 2000 tokens truncaban cualquier programa con tests. Medido el
        # 2026-07-20: al pedir un compresor con tests unitarios, la respuesta
        # cortaba a mitad de una cadena y el fence ni se cerraba, lo que
        # llegaba al sandbox como "SyntaxError: unterminated string literal".
        # El lazo de reparacion gastaba entonces sus 3 intentos en un fallo que
        # no puede arreglar: no falta un fix, falta el resto del programa.
        max_tokens=6000,
    )


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

    raw = _call_llm(prompt, "python")
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

    raw = _call_llm(prompt, "html")
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
                     forced_idea:   Optional[str]  = None) -> Optional[GeneratedProgram]:
    """Genera un programa. Intenta idea autónoma primero, fallback a lista predefinida."""
    self_proposed = False

    if forced_idea:
        category, extra_hint = forced_idea.strip(), random.choice(COMPLEXITY_HINTS)
    else:
        category, extra_hint, self_proposed = _pick_idea(seed_concepts)

    if not self_proposed:
        print(f"[generator] 💡 Idea: {category}")

    # Una idea de pagina web no se puede satisfacer con un script de terminal:
    # cambia el prompt, el fence esperado y mas adelante la verificacion.
    lenguaje = "html" if _es_idea_web(category) else "python"
    if lenguaje == "html":
        print("[generator] 🌐 Idea web detectada: genero HTML autocontenido.")

    prompt  = (_build_prompt_web(category, extra_hint) if lenguaje == "html"
               else _build_prompt(category, extra_hint))
    raw     = _call_llm(prompt, lenguaje)
    program = _parse_response(raw, category, lenguaje) if raw else None

    if raw is None:
        print("[generator] ⚠️  Ollama no respondió.")
        return None
    if program is None:
        print("[generator] ⚠️  No se pudo parsear o fue rechazado.")
        return None

    program.self_proposed = self_proposed
    print(f"[generator] ✅ Programa generado: '{program.title}'")
    return program
