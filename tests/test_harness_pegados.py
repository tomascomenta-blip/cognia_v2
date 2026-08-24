# -*- coding: utf-8 -*-
"""Tests de harness/pegados: pastes largos colapsados en el input.

Regresion de la feature entera (2026-08-23): sin harness/pegados y sin el
binding _manejar_pegado de cli.py, todo este fichero falla en el import o en
las aserciones. Cubre lo que pide la entrega:
 - paste corto -> literal; largo -> marca + sustitucion al enviar
 - normalizacion \r\n
 - marcas multiples en una linea
 - degradacion: un registro roto no pierde el texto del dueno
 - binding REAL de prompt_toolkit via pipe win32 (\x1b[200~...\x1b[201~),
   porque un pipe de stdin al REPL no dispara bracketed paste: esta es la
   prueba honesta del binding.
"""
from __future__ import annotations

import pytest

from cognia.harness import pegados


@pytest.fixture(autouse=True)
def _limpio(monkeypatch):
    # Umbral y estado deterministas: sin envs del entorno del dueno y con el
    # registro de sesion vacio en cada test.
    for var in ("COGNIA_PEGADO", "COGNIA_PEGADO_LINEAS", "COGNIA_PEGADO_CHARS"):
        monkeypatch.delenv(var, raising=False)
    pegados.limpiar()
    yield
    pegados.limpiar()


# ---------------------------------------------------------------------------
# Normalizacion y umbrales
# ---------------------------------------------------------------------------

def test_normalizar_crlf_y_cr_sueltos():
    assert pegados.normalizar("a\r\nb\rc\nd") == "a\nb\nc\nd"
    assert pegados.normalizar("") == ""
    assert pegados.normalizar(None) == ""


def test_es_largo_por_lineas():
    cfg = {"pegado_lineas": "5", "pegado_chars": "800"}
    assert not pegados.es_largo("a\nb\nc\nd", cfg)          # 4 lineas: corto
    assert pegados.es_largo("a\nb\nc\nd\ne", cfg)           # 5 lineas: largo


def test_es_largo_por_chars_en_una_linea():
    cfg = {"pegado_lineas": "5", "pegado_chars": "800"}
    assert not pegados.es_largo("x" * 800, cfg)
    assert pegados.es_largo("x" * 801, cfg)


def test_umbrales_env_ganan_a_config(monkeypatch):
    monkeypatch.setenv("COGNIA_PEGADO_LINEAS", "2")
    assert pegados.umbral_lineas({"pegado_lineas": "9"}) == 2
    monkeypatch.setenv("COGNIA_PEGADO_CHARS", "50")
    assert pegados.umbral_chars({"pegado_chars": "900"}) == 50


def test_activo_env_gana(monkeypatch):
    assert pegados.activo({}) is True                        # default on
    assert pegados.activo({"pegado": "off"}) is False
    monkeypatch.setenv("COGNIA_PEGADO", "0")
    assert pegados.activo({"pegado": "on"}) is False
    monkeypatch.setenv("COGNIA_PEGADO", "1")
    assert pegados.activo({"pegado": "off"}) is True


# ---------------------------------------------------------------------------
# Registro y expansion al enviar
# ---------------------------------------------------------------------------

def test_registrar_devuelve_marca_y_expandir_sustituye():
    texto = "linea1\nlinea2\nlinea3\nlinea4\nlinea5\nlinea6"
    marca = pegados.registrar(texto)
    assert marca == "[pegado #1: +6 lineas]"
    linea = f"resume esto: {marca} gracias"
    assert pegados.expandir(linea) == f"resume esto: {texto} gracias"


def test_marca_casa_con_su_propio_regex():
    marca = pegados.registrar("a\nb")
    assert pegados._RX_MARCA.fullmatch(marca)


def test_marcas_multiples_en_una_linea():
    m1 = pegados.registrar("uno\ndos")
    m2 = pegados.registrar("tres\ncuatro")
    linea = f"compara {m1} con {m2}"
    assert pegados.expandir(linea) == "compara uno\ndos con tres\ncuatro"


def test_marca_desconocida_queda_literal():
    linea = "esto [pegado #99: +7 lineas] no existe"
    assert pegados.expandir(linea) == linea


def test_expandir_no_reescanea_lo_sustituido():
    # Un paste que CONTIENE una marca vieja no se expande en cascada.
    pegados.registrar("contenido uno")                       # sera #1
    m2 = pegados.registrar("cita: [pegado #1: +1 lineas]")   # sera #2
    assert pegados.expandir(m2) == "cita: [pegado #1: +1 lineas]"


def test_listar_y_obtener():
    pegados.registrar("a\nb\nc")
    assert pegados.obtener(1)["lineas"] == 3
    assert pegados.obtener(2) is None
    assert pegados.obtener("no-numero") is None
    assert [e["n"] for e in pegados.listar()] == [1]


def test_limpiar_vacia_el_registro():
    pegados.registrar("x")
    pegados.limpiar()
    assert pegados.listar() == []
    assert pegados.obtener(1) is None


# ---------------------------------------------------------------------------
# Binding REAL de prompt_toolkit (pipe win32 con la secuencia de paste)
# ---------------------------------------------------------------------------

def _prompt_con_binding(entrada: str) -> str:
    """Una PromptSession con el binding REAL del REPL (cli._manejar_pegado)
    alimentada por pipe: la secuencia \x1b[200~...\x1b[201~ dispara
    Keys.BracketedPaste igual que un ctrl+v en la terminal."""
    from prompt_toolkit import PromptSession
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.keys import Keys
    from prompt_toolkit.output import DummyOutput
    from cognia import cli

    kb = KeyBindings()
    kb.add(Keys.BracketedPaste)(cli._manejar_pegado)
    with create_pipe_input() as pi:
        sesion = PromptSession(input=pi, output=DummyOutput(), key_bindings=kb)
        pi.send_text(f"\x1b[200~{entrada}\x1b[201~\r")
        return sesion.prompt("> ")


def test_binding_paste_corto_entra_literal(monkeypatch):
    monkeypatch.setenv("COGNIA_PEGADO_LINEAS", "5")
    monkeypatch.setenv("COGNIA_PEGADO_CHARS", "800")
    res = _prompt_con_binding("hola\r\nmundo")
    assert res == "hola\nmundo"                              # normalizado, literal
    assert pegados.listar() == []                            # nada registrado


def test_binding_paste_largo_colapsa_y_expande_al_enviar(monkeypatch):
    # env explicita: el binding lee la config REAL del CLI via _load_config y
    # este test no puede depender de lo que el dueno tenga persistido
    monkeypatch.setenv("COGNIA_PEGADO", "1")
    monkeypatch.setenv("COGNIA_PEGADO_LINEAS", "5")
    texto = "\r\n".join(f"linea {i}" for i in range(1, 8))   # 7 lineas
    res = _prompt_con_binding(texto)
    assert res == "[pegado #1: +7 lineas]"
    # al ENVIAR: la sustitucion devuelve el contenido normalizado integro
    assert pegados.expandir(res) == texto.replace("\r\n", "\n")


def test_binding_apagado_entra_literal(monkeypatch):
    monkeypatch.setenv("COGNIA_PEGADO", "0")
    texto = "\n".join(f"l{i}" for i in range(10))
    res = _prompt_con_binding(texto)
    assert res == texto
    assert pegados.listar() == []


def test_binding_degradado_no_pierde_el_texto(monkeypatch):
    """REGLA DURA: si registrar revienta, el paste entra LITERAL y se avisa
    degradado — jamas se pierde texto del dueno."""
    from cognia import cli
    monkeypatch.setenv("COGNIA_PEGADO", "1")
    monkeypatch.setenv("COGNIA_PEGADO_LINEAS", "5")
    avisos = []
    monkeypatch.setattr(cli, "_aviso_degradado",
                        lambda via, det="": avisos.append((via, det)))
    monkeypatch.setattr(pegados, "registrar",
                        lambda t: (_ for _ in ()).throw(OSError("disco roto")))
    texto = "\n".join(f"l{i}" for i in range(10))
    res = _prompt_con_binding(texto)
    assert res == texto                                      # literal, intacto
    assert avisos and avisos[0][0] == "pegado"
