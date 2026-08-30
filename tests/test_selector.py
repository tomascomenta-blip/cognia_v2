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


# ── P5: puntero y clases desde el registro de estilos (menu.selector) ────────
# Sin override, EXACTAMENTE los literales que este modulo llevaba a mano
# ('❯', 'bold', 'reverse', 'fg:ansibrightblack'); con /estilo menu.selector
# cambian; si el registro falla, los literales y un aviso (nunca silencio).

def test_puntero_y_clases_por_defecto_son_los_literales_de_siempre():
    assert selector._puntero() == "❯"
    assert selector._clases() == {"titulo": "bold", "activo": "reverse",
                                  "descripcion": "fg:ansibrightblack"}
    assert selector._CLASES_DEFECTO == selector._clases()


def test_override_del_registro_cambia_puntero_y_clases(tmp_path, monkeypatch):
    from cognia.ux import aspecto as A
    monkeypatch.setattr(A, "RUTA_ESTILO", tmp_path / "estilo.json")
    monkeypatch.delenv("COGNIA_ASCII", raising=False)
    A.reset()
    try:
        A.poner("menu.selector", "glifo", ">>")
        A.poner("menu.selector", "estados.activo.fondo", "#004466")
        A.poner("menu.selector", "estados.descripcion.color", "#ff00ff")
        A.poner("menu.selector", "negrita", False)
        assert selector._puntero() == ">>"
        assert selector._clases() == {"titulo": "", "activo": "bg:#004466",
                                      "descripcion": "fg:#ff00ff"}
    finally:
        A.reset()
    assert selector._puntero() == "❯"


def test_puntero_cae_a_ascii_si_stdout_no_lo_codifica(monkeypatch):
    class _Cp1252:
        encoding = "cp1252"

        def isatty(self):
            return False
    monkeypatch.setattr(sys, "stdout", _Cp1252())
    monkeypatch.delenv("COGNIA_ASCII", raising=False)
    assert selector._puntero() == ">"


def test_si_el_registro_falla_caen_los_literales_y_se_avisa(monkeypatch):
    from cognia.ux import aspecto as A
    avisos = []
    cli = sys.modules.get("cognia.cli")
    if cli is not None:
        monkeypatch.setattr(cli, "_aviso_degradado", lambda via, det="": avisos.append((via, det)))

    def _rota(*a, **k):
        raise RuntimeError("registro roto")
    monkeypatch.setattr(A, "clases_selector", _rota)
    monkeypatch.setattr(A, "glifo", _rota)
    assert selector._clases() == selector._CLASES_DEFECTO
    assert selector._puntero() == "❯"
    if cli is not None:
        assert len(avisos) == 2 and all(v == "selector" and "registro roto" in d for v, d in avisos)


# ── elegir_varias(): fallback texto ──────────────────────────────────────────
#
# POR QUE existen estos tests: elegir_varias() y texto_libre() se anadieron el
# 2026-08-28 PARA las encuestas del mejorador de prompts y entraron sin ni un
# test (verificado con grep sobre tests/). Son las dos funciones por las que
# pasa "varias de estas" y "escribilo vos", o sea dos de los tres tipos de
# pregunta que la encuesta sabe hacer: sin cobertura, el dia que se rompan el
# sintoma sera "la encuesta no pregunta nada" y nadie sabra por que.
#
# Lo que MAS importa fijar aqui no es el camino feliz sino la distincion entre
# [] y None (y entre "" y None): [] es "el usuario miro y no quiere ninguna" y
# None es "el usuario se fue sin contestar". encuesta.incorporar() las trata
# distinto a proposito, y confundirlas seria inventarle al usuario una decision
# que no tomo -- justo el fallo que el mejorador tiene prohibido cometer.

_SECCIONES = [
    ("inicio", "inicio", "la portada"),
    ("contacto", "contacto", "formulario y telefono"),
    ("blog", "blog", "entradas por fecha"),
]


def test_elegir_varias_numeros_separados_por_coma():
    assert selector.elegir_varias("Secciones:", _SECCIONES,
                                  input_fn=_fn(["1,3"])) == ["inicio", "blog"]


def test_elegir_varias_numeros_separados_por_espacio():
    assert selector.elegir_varias("Secciones:", _SECCIONES,
                                  input_fn=_fn(["2 3"])) == ["contacto", "blog"]


def test_elegir_varias_por_nombre_y_sin_distinguir_mayusculas():
    assert selector.elegir_varias("Secciones:", _SECCIONES,
                                  input_fn=_fn(["Blog, INICIO"])) == ["blog",
                                                                     "inicio"]


def test_elegir_varias_no_repite_la_misma_opcion():
    assert selector.elegir_varias("Secciones:", _SECCIONES,
                                  input_fn=_fn(["1,1,inicio"])) == ["inicio"]


def test_elegir_varias_todas_y_ninguna():
    assert selector.elegir_varias("Secciones:", _SECCIONES,
                                  input_fn=_fn(["todas"])) == ["inicio",
                                                               "contacto",
                                                               "blog"]
    # "ninguna" es una RESPUESTA (lista vacia), no una cancelacion.
    vacia = selector.elegir_varias("Secciones:", _SECCIONES,
                                   input_fn=_fn(["ninguna"]))
    assert vacia == [] and vacia is not None


def test_elegir_varias_enter_devuelve_lo_premarcado():
    assert selector.elegir_varias("Secciones:", _SECCIONES,
                                  marcadas=["contacto"],
                                  input_fn=_fn([""])) == ["contacto"]


def test_elegir_varias_enter_sin_premarcadas_es_lista_vacia():
    """Enter a secas con nada marcado = "ninguna", que es una respuesta. Si
    devolviera None, la encuesta anotaria "se fue" sobre alguien que contesto."""
    salida = selector.elegir_varias("Secciones:", _SECCIONES, input_fn=_fn([""]))
    assert salida == [] and salida is not None


def test_elegir_varias_cancelar_devuelve_none_no_lista_vacia():
    """LA distincion que este modulo existe para mantener: None != []."""
    assert selector.elegir_varias("Secciones:", _SECCIONES,
                                  input_fn=_fn([])) is None          # StopIteration


def test_elegir_varias_invalido_reintenta_y_acepta():
    assert selector.elegir_varias("Secciones:", _SECCIONES,
                                  input_fn=_fn(["99", "zzz", "2"])) == ["contacto"]


def test_elegir_varias_invalido_reintento_acotado_devuelve_none():
    """Un pipe con basura no puede colgar el turno: tope de reintentos."""
    assert selector.elegir_varias(
        "Secciones:", _SECCIONES,
        input_fn=_fn(["a", "b", "c", "1"])) is None


def test_elegir_varias_sin_opciones_devuelve_none_sin_preguntar():
    assert selector.elegir_varias("Nada:", [], input_fn=_fn_prohibida) is None
    assert selector.elegir_varias("Nada:", None, input_fn=_fn_prohibida) is None


def test_elegir_varias_permitir_vacio_false_no_acepta_ninguna():
    """"ninguna" cuando hace falta al menos una NO es cancelar: es una
    respuesta que no vale, y se reintenta. Devolver None ahi mezclaba las dos
    cosas que este modulo separa."""
    assert selector.elegir_varias("Secciones:", _SECCIONES,
                                  permitir_vacio=False,
                                  input_fn=_fn(["ninguna", "", "3"])) == ["blog"]


def test_elegir_varias_permitir_vacio_false_se_rinde_sin_colgarse():
    assert selector.elegir_varias("Secciones:", _SECCIONES,
                                  permitir_vacio=False,
                                  input_fn=_fn(["ninguna", "ninguna",
                                                "ninguna", "1"])) is None


def test_elegir_varias_eof_es_cancelacion():
    def _eof(_prompt=""):
        raise EOFError

    assert selector.elegir_varias("Secciones:", _SECCIONES,
                                  input_fn=_eof) is None


# ── texto_libre(): fallback texto ────────────────────────────────────────────

def test_texto_libre_devuelve_lo_escrito_recortado():
    assert selector.texto_libre("Para que va a servir?",
                                input_fn=_fn(["  vender pan  "])) == "vender pan"


def test_texto_libre_enter_vacio_sin_default_es_cadena_vacia():
    """"" es "no quiso decir nada" y None es "se fue": la encuesta omite las
    dos, pero no puede confundirlas al contarlas (una encuesta con cero
    respuestas se anuncia distinto que una cancelada)."""
    salida = selector.texto_libre("Para que?", input_fn=_fn([""]))
    assert salida == "" and salida is not None


def test_texto_libre_enter_vacio_con_default_devuelve_el_default():
    assert selector.texto_libre("Para que?", default="uso propio",
                                input_fn=_fn([""])) == "uso propio"


def test_texto_libre_lo_escrito_gana_al_default():
    assert selector.texto_libre("Para que?", default="uso propio",
                                input_fn=_fn(["para un cliente"])) == "para un cliente"


def test_texto_libre_cancelar_devuelve_none():
    assert selector.texto_libre("Para que?", input_fn=_fn([])) is None   # StopIteration

    def _ctrl_c(_prompt=""):
        raise KeyboardInterrupt

    assert selector.texto_libre("Para que?", input_fn=_ctrl_c) is None


def test_texto_libre_la_pista_y_el_default_salen_en_el_prompt():
    """La pista es como el usuario se entera de que puede saltar la pregunta
    (la encuesta pasa pista='Enter para saltar'); si no se pinta, la salida
    existe pero es invisible."""
    visto = []

    def _captura(prompt=""):
        visto.append(prompt)
        return ""

    selector.texto_libre("Para que va a servir?", default="uso propio",
                         pista="Enter para saltar", input_fn=_captura)
    assert "Para que va a servir?" in visto[0]
    assert "Enter para saltar" in visto[0]
    assert "uso propio" in visto[0]


def test_texto_libre_no_toca_prompt_toolkit_con_input_fn(monkeypatch):
    """Contrato del modulo: con input_fn inyectada NUNCA se instancia nada
    interactivo, tenga tty o no. Es lo que hace deterministas estos tests."""
    monkeypatch.setattr(selector, "hay_tty", lambda: True)
    import prompt_toolkit

    def _prohibida(*_a, **_k):
        raise AssertionError("no debia construirse una PromptSession")

    monkeypatch.setattr(prompt_toolkit, "PromptSession", _prohibida)
    assert selector.texto_libre("Para que?", input_fn=_fn(["algo"])) == "algo"


def test_elegir_varias_no_toca_prompt_toolkit_con_input_fn(monkeypatch):
    monkeypatch.setattr(selector, "hay_tty", lambda: True)
    from prompt_toolkit import application as _app

    def _prohibida(*_a, **_k):
        raise AssertionError("no debia construirse una Application")

    monkeypatch.setattr(_app, "Application", _prohibida)
    assert selector.elegir_varias("Secciones:", _SECCIONES,
                                  input_fn=_fn(["1"])) == ["inicio"]
