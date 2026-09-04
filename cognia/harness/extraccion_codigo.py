# -*- coding: utf-8 -*-
"""Extraer código de una respuesta y medir pass@k como lo hacen los papers.

Portado de deepseek-ai/DeepSeek-Coder (`Evaluation/PAL-Math/utils/parser.py:
extract_program(last_only=True)`, `Evaluation/HumanEval/human_eval/
evaluation.py: estimate_pass_at_k`, y `utils/utils.py:
_truncate_code_at_stopwords`) el 2026-09-04, tras leer su código.

- `ultimo_bloque(texto, lenguaje=None)`: recorre LÍNEA A LÍNEA (no regex
  DOTALL) y devuelve el ÚLTIMO bloque ``` cerrado, opcionalmente del lenguaje
  pedido. Es más robusto que `re.findall` cuando el modelo pega ejemplos con
  ``` dentro de su razonamiento o deja un bloque sin cerrar al principio.
- `bloques(texto)`: todos los bloques (lenguaje, cuerpo).
- `cortar_en_stopwords(codigo, stops)`: corta en la PRIMERA aparición de
  cualquier stop-word (el server corta por token, no por cadena decodificada).
- `pass_at_k(n, c, k)`: el estimador insesgado de Chen et al. 2021,
  `1 - C(n-c, k) / C(n, k)` calculado sin combinatoria explícita. Sin esto,
  cualquier pass@k que reporte un banco de Cognia no es comparable.
"""
from __future__ import annotations

import re

_RE_APERTURA = re.compile(r"^\s*```+\s*([A-Za-z0-9_+\-.#]*)\s*$")
_RE_CIERRE = re.compile(r"^\s*```+\s*$")

STOPS_PY = ("\ndef ", "\nclass ", "\nif __name__", "\n#", "\nprint(")


def bloques(texto: str) -> list[tuple[str, str]]:
    """[(lenguaje, cuerpo), ...] de todos los bloques ``` CERRADOS, en orden."""
    out: list[tuple[str, str]] = []
    if not texto:
        return out
    dentro = False
    lang = ""
    cuerpo: list[str] = []
    for linea in texto.splitlines():
        if not dentro:
            m = _RE_APERTURA.match(linea)
            if m:
                dentro, lang, cuerpo = True, (m.group(1) or "").lower(), []
            continue
        if _RE_CIERRE.match(linea):
            out.append((lang, "\n".join(cuerpo)))
            dentro = False
            continue
        cuerpo.append(linea)
    return out


def ultimo_bloque(texto: str, lenguaje: str | None = None) -> str | None:
    """El último bloque cerrado (del lenguaje pedido, si se pide); None si no hay."""
    bs = bloques(texto)
    if lenguaje:
        alias = {"py": "python", "python3": "python", "js": "javascript", "ts": "typescript",
                 "sh": "bash", "shell": "bash"}
        quiero = alias.get(lenguaje.lower(), lenguaje.lower())
        bs = [(l, c) for l, c in bs if alias.get(l, l) == quiero or (not l and quiero == "python")]
    return bs[-1][1] if bs else None


def cortar_en_stopwords(codigo: str, stops=STOPS_PY) -> str:
    """Corta en la primera stop-word (índice mínimo). Vacío si no hay ninguna."""
    if not codigo:
        return codigo
    indices = [codigo.find(s) for s in stops]
    indices = [i for i in indices if i >= 0]
    return codigo[: min(indices)] if indices else codigo


def pass_at_k(n: int, c: int, k: int) -> float:
    """Estimador insesgado pass@k (Chen et al. 2021) para n muestras, c correctas."""
    if k <= 0 or n <= 0:
        return 0.0
    if n - c < k:
        return 1.0
    prob_todas_fallan = 1.0
    for i in range(n - c + 1, n + 1):
        prob_todas_fallan *= 1.0 - k / i
    return 1.0 - prob_todas_fallan


def pass_at_k_medio(muestras: list[tuple[int, int]], k: int) -> float:
    """Media de pass@k sobre problemas [(n, c), ...]; 0.0 si no hay."""
    if not muestras:
        return 0.0
    return sum(pass_at_k(n, c, k) for n, c in muestras) / len(muestras)


__all__ = ["bloques", "ultimo_bloque", "cortar_en_stopwords", "pass_at_k",
           "pass_at_k_medio", "STOPS_PY"]
