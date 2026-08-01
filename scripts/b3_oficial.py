# -*- coding: utf-8 -*-
"""
b3_oficial.py — las CONDICIONES OFICIALES de LiveCodeBench, para poder (o no)
comparar con una tabla publicada.

POR QUÉ EXISTE. El goal es *"igualar a un modelo grande desde 16 GB"*, y anoche
me PROHIBÍ —con razón— comparar mi pass@1 con ninguna tabla: el prompt, el
evaluador y el cap de tests eran míos (enmiendas 1.8 y 2 del
PREREG_BANCO_CODIGO_20260730). Una prohibición no se levanta escribiendo que ya
no aplica: se levanta replicando las condiciones o declarando que no se pueden
replicar.

LO OFICIAL, verificado en red el 2026-07-31 contra el repo de LiveCodeBench
(lcb_runner/prompts/code_generation.py y evaluation/compute_code_generation_metrics.py):

  SYSTEM: "You are an expert Python programmer. You will be given a question
           (problem specification) and will generate a correct Python program
           that matches the specification and passes all tests."
  USER:   "### Question:\\n{q}\\n\\n### Format: ...\\n```python\\n...\\n```\\n\\n
           ### Answer: (use the provided format with backticks)"
  JUEZ:   TODOS los casos (públicos + privados), sin cap de tamaño ni de número.
          timeout = (6+1) * n_casos + 5 segundos para la muestra entera.
          Pasa solo si pasan TODOS.

LA REFERENCIA PUBLICADA que se usa como marcador (y sus límites, dichos aquí y
no en una nota al pie): **gpt-oss-20b, pass@1 = 70 en LCB v6, ventana
2024-08-01 → 2025-01-31, 3 muestras por problema, reasoning HIGH, 64k de
secuencia** — blog.collinear.ai/p/gpt-oss-lcb. NO es una entrada del leaderboard
oficial, no declara temperatura, y el model card de OpenAI (arXiv:2508.10925)
NO trae ninguna cifra de LiveCodeBench (comprobado). Es la mejor referencia que
existe, no una buena referencia.
"""
from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts"))

from b3_codigo import _ejecuta_lote

SYSTEM_OFICIAL = (
    "You are an expert Python programmer. You will be given a question "
    "(problem specification) and will generate a correct Python program that "
    "matches the specification and passes all tests.")

_FMT_STARTER = (
    "### Format: You will use the following starter code to write the "
    "solution to the problem and enclose your code within delimiters.\n"
    "```python\n{starter}\n```\n\n")

_FMT_STDIN = (
    "### Format: Read the inputs from stdin solve the problem and write the "
    "answer to stdout (do not directly test on the sample inputs). Enclose "
    "your code within delimiters as follows. Ensure that when the python "
    "program runs, it reads the inputs, runs the algorithm and writes output "
    "to STDOUT.\n```python\n# YOUR CODE HERE\n```\n\n")

SEG_POR_TEST_OFICIAL = 6
MARGEN_OFICIAL = 5

# TOPE DE TAMAÑO DEL LOTE, y por qué existe (medido el 2026-07-31).
# El juez oficial no capa nada, y 37 de 167 tareas traen >1 MB de entradas
# (máximo 19 MB): son tests de RENDIMIENTO. Serializar ese lote a JSON para el
# subproceso se come cientos de MB y minutos de reloj — una corrida se quedó
# 12 minutos en una sola muestra, con el proceso hijo a 849 MB.
# No se puede replicar su infraestructura en esta máquina, así que **se
# declara**: por encima de este tope la muestra NO se juzga y se marca
# `demasiado_grande`. Es un límite del banco de pruebas, no un veredicto sobre
# el modelo, y el análisis lo cuenta aparte en vez de disfrazarlo de fallo.
MAX_BYTES_LOTE = 8_000_000
SEG_MAX_LOTE = 120


def prompt_oficial(t: dict) -> str:
    """El template literal de lcb_runner. La diferencia con `prompt_lcb` (el
    mío) no es cosmética: el mío dice *"Return ONLY a Python code block"* y el
    oficial estructura la respuesta con marcadores `###`."""
    cab = f"### Question:\n{t['enunciado']}\n\n"
    if (t.get("starter_code") or "").strip():
        cab += _FMT_STARTER.format(starter=t["starter_code"])
    else:
        cab += _FMT_STDIN
    return cab + "### Answer: (use the provided format with backticks)"


def casos_oficiales(t: dict) -> list:
    """TODOS los casos: públicos + privados, SIN el cap de 15 ni el descarte
    de entradas >100 KB de la enmienda 2. Los públicos entran aunque estén
    impresos en el enunciado — así juzga el oficial, y es correcto para medir
    capacidad (otra cosa es usarlos como examen de un SELECTOR, que es lo que
    la enmienda del prereg de anoche prohibía)."""
    return list(t.get("publicos") or []) + list(t.get("privados") or [])


def juzga_oficial(code: str, t: dict, casos: list = None,
                  max_bytes: int = None, seg_max: int = None) -> tuple:
    """(pasa, motivo) con el presupuesto oficial.

    Se corta al primer fallo (`parar_al_fallar`): el veredicto oficial es un
    AND sobre todos los casos, así que parar en el primer fallo da EXACTAMENTE
    el mismo veredicto y ahorra horas de CPU. Lo que se pierde es el recuento
    de cuántos pasaron, que aquí no se usa.

    `max_bytes`/`seg_max` (enmienda 4 del diseño frontier): el re-juicio de
    los lotes `demasiado_grande` los sube a 64 MB / fórmula completa. Los
    defaults son los topes de siempre — sin pasarlos, byte a byte lo mismo.
    """
    casos = casos_oficiales(t) if casos is None else casos
    if not code.strip():
        return False, "sin_codigo"
    if not casos:
        return False, "sin_tests"
    tope_bytes = MAX_BYTES_LOTE if max_bytes is None else max_bytes
    bytes_lote = sum(len(c.get("input") or "") + len(c.get("output") or "")
                     for c in casos)
    if bytes_lote > tope_bytes:
        return False, f"demasiado_grande:{bytes_lote}"
    modo = "functional" if (casos[0].get("testtype") == "functional"
                            or t.get("func_name")) else "stdin"
    # la fórmula LITERAL del oficial: (timeout + 1) * n_casos + 5, pero con un
    # techo de pared propio: sin él una sola muestra se lleva el reloj.
    tope = min(SEG_MAX_LOTE if seg_max is None else seg_max,
               (SEG_POR_TEST_OFICIAL + 1) * len(casos) + MARGEN_OFICIAL)
    res, motivo = _ejecuta_lote(code, casos, modo, t.get("func_name", ""),
                                timeout=tope, parar_al_fallar=True)
    return (all(res) and len(res) == len(casos)), motivo
