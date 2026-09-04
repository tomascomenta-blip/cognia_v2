# -*- coding: utf-8 -*-
"""Contrato de `cognia/harness/extraccion_codigo.py` (DeepSeek-Coder:
extract_program(last_only), estimate_pass_at_k, _truncate_code_at_stopwords)."""
from __future__ import annotations

import math

from cognia.harness import extraccion_codigo as ec


def test_ultimo_bloque_toma_el_ultimo_cerrado():
    t = "pienso:\n```python\nx = 1\n```\nmejor:\n```python\nx = 2\n```\n"
    assert ec.ultimo_bloque(t) == "x = 2"
    assert ec.ultimo_bloque(t, "py") == "x = 2"


def test_ignora_el_bloque_sin_cerrar_y_las_fences_en_prosa():
    t = "ejemplo con ``` dentro del texto\n```\nsin lenguaje\n```\n```js\nlet a\n```\n```python\ndef f():\n    return 1"
    assert ec.ultimo_bloque(t, "python") == "sin lenguaje"          # el último cerrado sin lang cuenta como python
    assert ec.ultimo_bloque(t, "javascript") == "let a"
    assert ec.ultimo_bloque("nada", "python") is None
    assert ec.ultimo_bloque("", None) is None


def test_bloques_en_orden_con_lenguaje():
    assert ec.bloques("```a\n1\n```\n```b\n2\n3\n```") == [("a", "1"), ("b", "2\n3")]


def test_cortar_en_stopwords():
    code = "    return x + 1\n\ndef otra():\n    pass\nprint(1)"
    assert ec.cortar_en_stopwords(code) == "    return x + 1\n"
    assert ec.cortar_en_stopwords("    return 1") == "    return 1"


def test_pass_at_k_valores_conocidos():
    assert ec.pass_at_k(1, 1, 1) == 1.0
    assert ec.pass_at_k(1, 0, 1) == 0.0
    assert math.isclose(ec.pass_at_k(10, 1, 1), 0.1)
    assert math.isclose(ec.pass_at_k(10, 1, 10), 1.0)
    # n=5, c=2, k=2: 1 - C(3,2)/C(5,2) = 1 - 3/10
    assert math.isclose(ec.pass_at_k(5, 2, 2), 0.7)
    assert ec.pass_at_k(0, 0, 1) == 0.0


def test_pass_at_k_medio():
    assert math.isclose(ec.pass_at_k_medio([(1, 1), (1, 0)], 1), 0.5)
    assert ec.pass_at_k_medio([], 1) == 0.0
