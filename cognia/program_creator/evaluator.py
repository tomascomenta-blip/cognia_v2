"""
evaluator.py — Evaluador de programas generados por Cognia.

Analiza un programa generado + su resultado de ejecución y produce
una puntuación multi-dimensional:

  - functionality_score : ¿El programa corrió y produjo output?
  - creativity_score    : ¿El código usa técnicas interesantes?
  - error_score         : Penalización por errores / crashes
  - total_score         : 0–10

Programas con total_score >= STORE_THRESHOLD se consideran dignos de guardar.

Este módulo NO modifica ninguna memoria de Cognia.
"""

import ast
import re
from dataclasses import dataclass

from .generator     import GeneratedProgram
from .sandbox_runner import ExecutionResult

# ── Configuración ──────────────────────────────────────────────────────────────

STORE_THRESHOLD = 5.0   # Puntuación mínima para guardar el programa

# Palabras clave que sugieren complejidad / creatividad en el código
CREATIVE_KEYWORDS = [
    # Estructuras de datos interesantes
    "deque", "defaultdict", "Counter", "namedtuple", "dataclass",
    # Algoritmos
    "recursive", "recursion", "fibonacci", "factorial", "permutation",
    "sort", "bisect", "heapq",
    # Visualización ASCII
    "curses", "shutil.get_terminal_size", "\\x1b[", "\033[",  # escape codes ANSI
    "chr(", "ord(",
    # Generación procedural
    "random.choice", "random.randint", "random.sample",
    "itertools", "functools",
    # Matemáticas
    "math.", "complex(", "cmath",
    # Cadenas / texto
    "textwrap", "difflib", "re.",
    # Tiempo
    "time.sleep", "datetime",
]

# Patrones que indican código interactivo o animado
INTERACTIVE_PATTERNS = [
    r"input\s*\(",
    r"time\.sleep\s*\(",
    r"while\s+True",
    r"for\s+\w+\s+in\s+range",
    r"print\s*\(.*\\r",       # carriage return → animación en terminal
]

# Errores Python comunes que bajan mucho la puntuación
FATAL_ERROR_PATTERNS = [
    "SyntaxError",
    "IndentationError",
    "NameError",
    "ModuleNotFoundError",
    "ImportError",
    "AttributeError",
]

MINOR_ERROR_PATTERNS = [
    "TypeError",
    "ValueError",
    "KeyError",
    "IndexError",
    "ZeroDivisionError",
    "RecursionError",
]


# ── Dataclass de resultado ─────────────────────────────────────────────────────

@dataclass
class EvaluationResult:
    """Puntuación completa de un programa."""
    functionality_score: float   # 0–4  (¿corrió y produjo output?)
    creativity_score:    float   # 0–4  (¿es creativo/interesante?)
    error_score:         float   # 0–2  (penalización por errores, inverso)
    total_score:         float   # 0–10
    should_store:        bool
    notes:               list    # Observaciones textuales del evaluador


# ── Evaluadores internos ───────────────────────────────────────────────────────

def _evaluate_functionality(program: GeneratedProgram,
                             result: ExecutionResult) -> tuple[float, list]:
    """
    Puntúa qué tan bien funcionó el programa (0–4).
    """
    score = 0.0
    notes = []

    if result.success:
        score += 2.0
        notes.append("Program ran successfully.")
    elif result.timed_out and result.execution_output.strip():
        score += 1.5
        notes.append("Program ran but was interrupted by timeout (likely interactive/infinite).")
    elif result.exit_code == 0 and not result.execution_output.strip():
        score += 0.5
        notes.append("Program ran without errors but produced no output.")
    else:
        notes.append(f"Program failed (exit={result.exit_code}).")

    # Bonus por output significativo
    output_len = len(result.execution_output.strip())
    if output_len > 500:
        score += 1.5
        notes.append(f"Rich output ({output_len} chars).")
    elif output_len > 100:
        score += 1.0
        notes.append(f"Moderate output ({output_len} chars).")
    elif output_len > 10:
        score += 0.5
        notes.append(f"Minimal output ({output_len} chars).")

    # Bonus por código de tamaño adecuado (no trivial)
    if result.code_length > 500:
        score += 0.5
        notes.append("Code has substantial length (>500 chars).")

    return min(score, 4.0), notes


def _evaluate_creativity(program: GeneratedProgram,
                          result: ExecutionResult) -> tuple[float, list]:
    """
    Puntúa la creatividad e interés del código (0–4).
    """
    score = 0.0
    notes = []
    code  = program.code

    # ── Análisis de keywords creativos ────────────────────────────────
    found_keywords = [kw for kw in CREATIVE_KEYWORDS if kw in code]
    keyword_score  = min(len(found_keywords) * 0.3, 1.5)
    score += keyword_score
    if found_keywords:
        notes.append(f"Uses interesting constructs: {', '.join(found_keywords[:5])}.")

    # ── Análisis de patrones interactivos ─────────────────────────────
    interactive_count = sum(
        1 for pat in INTERACTIVE_PATTERNS
        if re.search(pat, code)
    )
    if interactive_count >= 2:
        score += 1.0
        notes.append("Interactive or animated behavior detected.")
    elif interactive_count == 1:
        score += 0.5

    # ── Análisis sintáctico con AST ───────────────────────────────────
    try:
        tree = ast.parse(code)

        # Contar funciones y clases → complejidad estructural
        func_count  = sum(1 for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
        class_count = sum(1 for n in ast.walk(tree) if isinstance(n, ast.ClassDef))

        if func_count >= 3:
            score += 0.5
            notes.append(f"Well-structured: {func_count} functions.")
        if class_count >= 1:
            score += 0.5
            notes.append(f"Uses OOP: {class_count} class(es).")

        # Conteo de líneas efectivas
        lines = [l for l in code.splitlines() if l.strip() and not l.strip().startswith("#")]
        if len(lines) > 80:
            score += 0.5
            notes.append(f"Non-trivial length: {len(lines)} effective lines.")

    except SyntaxError:
        notes.append("AST parse failed — code may have syntax errors.")

    # ── Bonus por descripción informativa ─────────────────────────────
    if len(program.description) > 30:
        score += 0.2

    # ── Bonus por título original (no genérico) ────────────────────────
    generic_titles = {"untitled", "program", "script", "test", "main"}
    if not any(g in program.title.lower() for g in generic_titles):
        score += 0.3
        notes.append("Original program title.")

    return min(score, 4.0), notes


def _evaluate_errors(program: GeneratedProgram,
                     result: ExecutionResult) -> tuple[float, list]:
    """
    Evalúa penalización por errores (0–2, donde 2 = sin errores).
    """
    score = 2.0   # Empezamos con puntuación perfecta y penalizamos
    notes = []
    stderr = result.execution_errors or ""

    if not stderr.strip():
        notes.append("No errors detected.")
        return 2.0, notes

    # Errores fatales → penalización máxima
    for pat in FATAL_ERROR_PATTERNS:
        if pat in stderr:
            score -= 1.5
            notes.append(f"Fatal error detected: {pat}.")
            break

    # Errores menores → penalización moderada
    for pat in MINOR_ERROR_PATTERNS:
        if pat in stderr:
            score -= 0.5
            notes.append(f"Minor error detected: {pat}.")
            break

    # Solo warnings → penalización mínima
    if "Warning" in stderr and score == 2.0:
        score -= 0.2
        notes.append("Warnings present.")

    # El timeout en sí no es un error de código
    if result.timed_out:
        score = max(score, 1.0)   # No penalizamos demasiado por timeout
        notes.append("Timed out (not necessarily a code error).")

    return max(score, 0.0), notes


# ── API pública ────────────────────────────────────────────────────────────────

def evaluate_program(program: GeneratedProgram,
                     result: ExecutionResult) -> EvaluationResult:
    """
    Evalúa un programa generado y su resultado de ejecución.

    Args:
        program : GeneratedProgram con título, descripción y código
        result  : ExecutionResult con output, errors, exit_code, etc.

    Returns:
        EvaluationResult con puntuaciones detalladas y recomendación de almacenamiento.
    """
    func_score,  func_notes  = _evaluate_functionality(program, result)
    creat_score, creat_notes = _evaluate_creativity(program, result)
    error_score, error_notes = _evaluate_errors(program, result)

    total = round(func_score + creat_score + error_score, 2)
    all_notes = func_notes + creat_notes + error_notes

    should_store = total >= STORE_THRESHOLD

    evaluation = EvaluationResult(
        functionality_score=round(func_score,  2),
        creativity_score=   round(creat_score, 2),
        error_score=        round(error_score, 2),
        total_score=        total,
        should_store=       should_store,
        notes=              all_notes,
    )

    verdict = "💾 GUARDAR" if should_store else "🗑️  DESCARTAR"
    print(
        f"[evaluator] {verdict} | total={total:.1f}/10 "
        f"(func={func_score:.1f} creat={creat_score:.1f} err={error_score:.1f})"
    )

    return evaluation


def format_evaluation_text(eval_result: EvaluationResult) -> str:
    """
    Genera el texto plano que se almacenará en evaluation.txt.
    """
    lines = [
        "=== PROGRAM EVALUATION ===",
        "",
        f"Total Score       : {eval_result.total_score:.1f} / 10",
        f"Functionality     : {eval_result.functionality_score:.1f} / 4.0",
        f"Creativity        : {eval_result.creativity_score:.1f} / 4.0",
        f"Error Penalty     : {eval_result.error_score:.1f} / 2.0  (higher = fewer errors)",
        f"Store Decision    : {'YES — kept in library' if eval_result.should_store else 'NO — did not meet threshold'}",
        "",
        "--- Notes ---",
    ]
    for note in eval_result.notes:
        lines.append(f"  • {note}")
    return "\n".join(lines)
