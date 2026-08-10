"""
tests/test_selector.py
======================
Tests del selector con flechas (cognia/ux/selector.py).

POR QUE solo se testea el fallback texto: en CI no hay tty, y el contrato
del modulo dice que la Application de prompt_toolkit se construye LAZY y
SOLO con tty real — input_fn inyectada fuerza siempre el modo texto, que
es determinista. El camino interactivo real se verifica a mano en un
terminal de verdad, no aca.
"""

from __future__ import annotations

import sys

from cognia.ux import selector


# Opciones de ejemplo con la forma congelada (valor, etiqueta, descripcion)
_TEMAS = [
    ("oscuro", "oscuro", "colores vivos sobre fondo oscuro"),
    ("claro", "claro", "paleta para terminal con fondo claro"),
    ("alto_contraste", "alto contraste", "maxima legibilidad"),
]


def _fn(respuestas):
    """input_fn de mentira: devuelve las respuestas en orden; se agota en
    StopIteration (que el selector trata como cancelacion)."""
    it = iter(respuestas)
    return lambda _prompt="": next(it)


def _fn_prohibida(*_a, **_k):
    raise AssertionError("input_fn no debia llamarse en este caso")


# ── elegir(): fallback texto ─────────────────────────────────────────────────

def test_elegir_fallback_numero():
    assert selector.elegir("Tema:", _TEMAS, input_fn=_fn(["2"])) == "claro"


def test_elegir_fallback_valor_textual():
    # acepta el VALOR textual ademas del numero
    assert selector.elegir("Tema:", _TEMAS, input_fn=_fn(["oscuro"])) == "oscuro"


def test_elegir_fallback_etiqueta_textual_case_insensitive():
    # tambien la ETIQUETA, sin distinguir mayusculas
    assert selector.elegir("Tema:", _TEMAS, input_fn=_fn(["Alto Contraste"])) == "alto_contraste"


def test_elegir_invalido_reintenta_y_acepta():
    # dos invalidas (fuera de rango, texto que no matchea) y una valida
    assert selector.elegir("Tema:", _TEMAS, input_fn=_fn(["99", "zzz", "1"])) == "oscuro"


def test_elegir_invalido_reintento_acotado_devuelve_none():
    # 3 invalidas agotan los reintentos: None, jamas un loop infinito
    assert selector.elegir("Tema:", _TEMAS, input_fn=_fn(["x", "y", "z"])) is None


def test_elegir_vacio_devuelve_default():
    assert selector.elegir("Tema:", _TEMAS, default=1, input_fn=_fn([""])) == "claro"


def test_elegir_default_fuera_de_rango_cae_a_cero():
    assert selector.elegir("Tema:", _TEMAS, default=99, input_fn=_fn([""])) == "oscuro"


def test_elegir_eof_devuelve_none():
    def _eof(_prompt=""):
        raise EOFError
    assert selector.elegir("Tema:", _TEMAS, input_fn=_eof) is None


def test_elegir_opciones_vacias_devuelve_none():
    assert selector.elegir("Nada:", [], input_fn=_fn_prohibida) is None
    assert selector.elegir("Nada:", None, input_fn=_fn_prohibida) is None


def test_elegir_una_opcion_devuelve_directo_sin_preguntar():
    # con UNA sola opcion no hay nada que elegir: valor directo, sin input
    unica = [("unico", "la unica", "no hay mas")]
    assert selector.elegir("Elegi:", unica, input_fn=_fn_prohibida) == "unico"


def test_elegir_input_fn_fuerza_fallback_sin_tocar_tty(monkeypatch):
    # con input_fn inyectada NUNCA se consulta hay_tty ni prompt_toolkit
    monkeypatch.setattr(selector, "hay_tty", _fn_prohibida)
    assert selector.elegir("Tema:", _TEMAS, input_fn=_fn(["3"])) == "alto_contraste"


def test_elegir_imprime_lista_numerada(capsys):
    selector.elegir("Tema del CLI:", _TEMAS, input_fn=_fn(["1"]))
    out = capsys.readouterr().out
    assert "Tema del CLI:" in out
    assert "1) oscuro" in out
    assert "3) alto contraste" in out


# ── confirmar(): fallback texto ──────────────────────────────────────────────

def test_confirmar_s():
    assert selector.confirmar("Ejecutar?", input_fn=_fn(["s"])) is True
    assert selector.confirmar("Ejecutar?", input_fn=_fn(["si"])) is True
    assert selector.confirmar("Ejecutar?", input_fn=_fn(["YES"])) is True


def test_confirmar_n():
    assert selector.confirmar("Ejecutar?", input_fn=_fn(["n"])) is False
    assert selector.confirmar("Ejecutar?", input_fn=_fn(["no"])) is False


def test_confirmar_vacio_usa_default():
    assert selector.confirmar("Ejecutar?", default=True, input_fn=_fn([""])) is True
    assert selector.confirmar("Ejecutar?", default=False, input_fn=_fn([""])) is False


def test_confirmar_basura_es_false():
    # cualquier cosa que no sea s/si/y/yes es False (como el input() de hoy)
    assert selector.confirmar("Ejecutar?", default=True, input_fn=_fn(["quizas"])) is False


def test_confirmar_eof_es_false():
    def _eof(_prompt=""):
        raise EOFError
    assert selector.confirmar("Ejecutar?", default=True, input_fn=_eof) is False


def test_confirmar_pregunta_con_sufijo_sn(capsys):
    # el fallback conserva la forma '(s/n) > ' que ven los pipes
    prompts = []

    def _espia(prompt=""):
        prompts.append(prompt)
        return "s"

    selector.confirmar("[permiso] borrar x — ejecutar?", input_fn=_espia)
    assert prompts and prompts[0].endswith("(s/n) > ")


# ── hay_tty() ────────────────────────────────────────────────────────────────

class _NoTty:
    def isatty(self):
        return False


class _SinIsatty:
    pass


def test_hay_tty_false_con_stdin_no_tty(monkeypatch):
    monkeypatch.setattr(sys, "stdin", _NoTty())
    assert selector.hay_tty() is False


def test_hay_tty_false_con_stdout_no_tty(monkeypatch):
    # ambos lados cuentan: stdout redirigido tambien apaga el selector
    monkeypatch.setattr(sys, "stdout", _NoTty())
    assert selector.hay_tty() is False


def test_hay_tty_false_si_isatty_revienta(monkeypatch):
    # un stdin reemplazado sin isatty() cuenta como "sin tty", no como crash
    monkeypatch.setattr(sys, "stdin", _SinIsatty())
    assert selector.hay_tty() is False


def test_elegir_sin_tty_cae_a_texto(monkeypatch):
    # sin input_fn pero sin tty: fallback texto leyendo de input() builtin
    monkeypatch.setattr(sys, "stdin", _NoTty())
    import builtins
    monkeypatch.setattr(builtins, "input", _fn(["2"]))
    assert selector.elegir("Tema:", _TEMAS) == "claro"


def test_confirmar_sin_tty_cae_a_texto(monkeypatch):
    monkeypatch.setattr(sys, "stdin", _NoTty())
    import builtins
    monkeypatch.setattr(builtins, "input", _fn(["s"]))
    assert selector.confirmar("Ejecutar?") is True
