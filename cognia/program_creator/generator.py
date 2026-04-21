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
from typing import Optional

# ── Configuración ──────────────────────────────────────────────────────────────

OLLAMA_URL   = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3.2:1b"
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

    try:
        payload = json.dumps({
            "model":  OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.95, "num_predict": 50, "top_p": 0.97}
        }).encode("utf-8")

        request = _req.Request(OLLAMA_URL, data=payload,
                               headers={"Content-Type": "application/json"})
        with _req.urlopen(request, timeout=60) as resp:
            data = json.loads(resp.read())
            idea = data.get("response", "").strip()
            idea = idea.split("\n")[0].strip().strip('"').strip("'").strip(".")
            return idea if 5 < len(idea) < 200 else None
    except Exception as exc:
        print(f"[generator] No pude generar idea propia: {exc}")
        return None


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


def _call_ollama(prompt: str) -> Optional[str]:
    try:
        payload = json.dumps({
            "model":   OLLAMA_MODEL,
            "prompt":  prompt,
            "system": (
                "You are a creative Python programmer. Write complete, runnable programs "
                "using only the standard library. NEVER use input() or blocking calls — "
                "programs must run automatically. Follow the output format exactly."
            ),
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


def _parse_response(raw: str, category: str) -> Optional[GeneratedProgram]:
    if not raw:
        return None

    lines, title, desc, code_lines, in_code = raw.splitlines(), "", "", [], False

    for line in lines:
        s = line.strip()
        if s.lower().startswith("title:"):
            title = s[6:].strip()
        elif s.lower().startswith("description:"):
            desc = s[12:].strip()
        elif s.startswith("```python"):
            in_code = True
        elif s == "```" and in_code:
            in_code = False
        elif in_code:
            code_lines.append(line)

    code = "\n".join(code_lines).strip()
    if not title:
        title = f"Untitled {category.title()}"
    if not desc:
        desc = f"A small {category} program."
    if len(code) < 30:
        return None

    # Rechazar programas que usen input() — el sandbox los mataría igual
    code_lines_clean = [l for l in code.splitlines()
                        if not l.strip().startswith("#")]
    if any("input(" in l for l in code_lines_clean):
        print("[generator] ⚠️  Rechazado: usa input() — debe ser no-interactivo.")
        return None

    return GeneratedProgram(title=title, description=desc, code=code,
                            category=category, raw_response=raw)


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

    raw     = _call_ollama(_build_prompt(category, extra_hint))
    program = _parse_response(raw, category) if raw else None

    if raw is None:
        print("[generator] ⚠️  Ollama no respondió.")
        return None
    if program is None:
        print("[generator] ⚠️  No se pudo parsear o fue rechazado.")
        return None

    program.self_proposed = self_proposed
    print(f"[generator] ✅ Programa generado: '{program.title}'")
    return program
