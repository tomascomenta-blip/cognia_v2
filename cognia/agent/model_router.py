"""
cognia/agent/model_router.py
============================
Router dinámico de modelo por DIFICULTAD de tarea (corrida-2 tarea 4).

"Cambiar de modelo según la tarea para ahorrar recursos": estimar EX-ANTE
(antes de generar, cero LLM) qué tan dura es una tarea de código y despachar
la barata (3B, ~8 tok/s) para lo fácil y la cara (7B, ~2.2 tok/s, +calidad)
SOLO para lo difícil. Complementa la cascada REACTIVA existente
(benchmark_code.swap_server_model: corre 3B, reintenta 7B los que fallan) con
una decisión PREDICTIVA: saltar el intento 3B desperdiciado en lo que ya se
predice difícil.

El estimador es una heurística barata (longitud + señales algorítmicas +
restricciones tramposas), calibrada contra las etiquetas easy/medium/hard de
las tasks embebidas de benchmark_code. Cero red neuronal, cero LLM — el punto
es AHORRAR recursos, no gastar otro modelo para decidir.
"""
from __future__ import annotations

import re

# Señales de dificultad algorítmica (peso alto): estructuras/técnicas que el
# 3B falla más seguido y el 7B resuelve.
_HARD_SIGNALS = re.compile(
    r"\b(recursi|dynamic\s*program|memoiz|backtrack|graph|arbol|tree|"
    r"matriz|matrix|spiral|permuta|combina|subsequence|subsecuencia|"
    r"longest|shortest\s*path|dijkstra|dfs|bfs|parse|parser|regex|"
    r"expresi[oó]n\s*regular|state\s*machine|aut[oó]mata|balanced|"
    r"binary\s*search|divide\s*and\s*conquer|optimi[zc]|efficient|"
    r"eficiente|O\(|complejidad|invert.*arbol|merge\s*sort|quicksort)\b",
    re.IGNORECASE)

# Restricciones "tramposas" que suben la dificultad aunque el problema parezca chico.
_TRICKY = re.compile(
    r"\b(without\s+importing|sin\s+importar|in\s*place|in-place|"
    r"sin\s+usar|edge\s*case|caso\s*borde|no\s+leading\s*zero|"
    r"overflow|precision|numerical|thread|concurren|async)\b",
    re.IGNORECASE)


def estimate_difficulty(task: str) -> float:
    """Dificultad estimada en [0,1] (0=trivial, 1=muy dura). Heurística barata.

    Combina: longitud (proxy de nº de requisitos), señales algorítmicas
    fuertes, restricciones tramposas, y nº de casos borde/ejemplos citados."""
    if not task:
        return 0.0
    t = task.strip()
    score = 0.0
    # longitud: 0 en <120 chars, satura ~0.30 en >=400
    score += min(len(t), 400) / 400 * 0.30
    # señales algorítmicas fuertes (cada match cuenta, satura)
    n_hard = len(_HARD_SIGNALS.findall(t))
    score += min(n_hard, 3) / 3 * 0.40
    # restricciones tramposas
    n_tricky = len(_TRICKY.findall(t))
    score += min(n_tricky, 2) / 2 * 0.20
    # varios ejemplos/casos citados (== -> asserts o "example") sugiere borde-heavy
    n_examples = len(re.findall(r"==|example|ejemplo|->", t))
    score += min(n_examples, 4) / 4 * 0.10
    return round(min(score, 1.0), 3)


def pick_model(task: str, threshold: float = 0.30,
               cheap: str = "3b", expensive: str = "7b") -> str:
    """Clave del GGUF a usar: 'expensive' si la dificultad supera el umbral,
    'cheap' si no. threshold calibrado (0.30) contra las etiquetas de las
    tasks embebidas (ver test_model_router)."""
    return expensive if estimate_difficulty(task) >= threshold else cheap


def route_tasks(tasks: list, threshold: float = 0.30) -> dict:
    """Parte una lista de tasks (dicts con 'prompt') en {'3b': [...], '7b':
    [...]} por dificultad. Devuelve tambien la dificultad por id para el log.
    Sirve para correr cada partición en su modelo con UN solo swap (no
    swap-por-tarea, que thrashea el llama-server)."""
    partition = {"3b": [], "7b": []}
    difficulty = {}
    for tk in tasks:
        d = estimate_difficulty(tk.get("prompt", ""))
        m = "7b" if d >= threshold else "3b"
        partition[m].append(tk)
        difficulty[tk.get("id", "?")] = {"difficulty": d, "model": m}
    return {"partition": partition, "difficulty": difficulty}
