# -*- coding: utf-8 -*-
"""
Regresion (revision adversarial 2026-08-23): F4 y F5 TAPABAN comandos que ya
existian — la clase de bug ya pagada el 2026-08-19 ('/flujo y /vigilar YA
EXISTIAN y los estaba tapando').

  - /compactar: DOS def _slash_compactar (Python se queda con el ultimo) y la
    feature vieja ('/compactar' a secas: panel de ultimas interacciones)
    desaparecia en silencio. Hoy: a secas -> _slash_compactar_sesion; con
    args -> la puerta F4.
  - /notificar <mensaje> (popup de escritorio): el handler F5 capturaba todo
    '/notificar ...' y el uso viejo respondia 'Uso: ...'. Hoy el texto que no
    es subcomando cae a _notificar_mensaje.
  - _CMD_DESCRIPTIONS tenia "/compactar" y "/notificar" DUPLICADAS en el
    mismo dict literal (la segunda pisa a la primera sin aviso): el antibody
    de abajo recorre el AST y prohibe claves repetidas para siempre.
"""

from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

import cognia.cli as cli

_CLI_SRC = Path(inspect.getfile(cli)).read_text(encoding="utf-8")


def _claves_duplicadas_en(nombre_dict: str) -> list:
    """Claves constantes repetidas dentro del dict literal asignado a
    `nombre_dict` en cognia/cli.py (la segunda pisa a la primera en silencio:
    asi se tragaron las descripciones viejas de /compactar y /notificar)."""
    arbol = ast.parse(_CLI_SRC)
    for nodo in ast.walk(arbol):
        if (isinstance(nodo, ast.Assign) and nodo.targets
                and isinstance(nodo.targets[0], ast.Name)
                and nodo.targets[0].id == nombre_dict
                and isinstance(nodo.value, ast.Dict)):
            vistas, dupes = set(), []
            for k in nodo.value.keys:
                if isinstance(k, ast.Constant):
                    if k.value in vistas:
                        dupes.append(k.value)
                    vistas.add(k.value)
            return dupes
    raise AssertionError(f"no encontre el dict literal {nombre_dict}")


def test_cmd_descriptions_sin_claves_duplicadas():
    assert _claves_duplicadas_en("_CMD_DESCRIPTIONS") == []


def test_cmd_details_sin_claves_duplicadas():
    assert _claves_duplicadas_en("_CMD_DETAILS") == []


def test_compactar_a_secas_va_a_la_feature_vieja():
    """Las DOS features conviven: el def viejo renombrado sigue existiendo y
    la rama 'raw == "/compactar"' del repl lo llama; la puerta F4 conserva su
    firma con arg. Sin el fix, el segundo def pisaba al primero."""
    assert callable(cli._slash_compactar_sesion)
    firma = inspect.signature(cli._slash_compactar_sesion)
    assert len(firma.parameters) == 0
    # la puerta F4 sigue siendo la de arg (estado/umbral/etc.)
    assert "arg" in inspect.signature(cli._slash_compactar).parameters
    # y el dispatch de 'a secas' llama a la vieja, no a la F4
    m = re.search(r'elif raw == "/compactar":\n(.*?)elif ', _CLI_SRC, re.S)
    assert m and "_slash_compactar_sesion()" in m.group(1)
    # el handler F4 solo se engancha CON args (el 'a secas' ya se atendio)
    assert 'elif raw == "/compactar" or raw.startswith("/compactar ")' not in _CLI_SRC


def test_notificar_mensaje_libre_cae_al_popup_viejo(monkeypatch):
    """'/notificar termino el build' (el uso documentado del comando viejo)
    tiene que mandar el popup, no el usage de F5."""
    mandados = []
    monkeypatch.setattr(cli, "_notificar_mensaje",
                        lambda msg: mandados.append(msg))
    cli._slash_notificar("termino el build")
    assert mandados == ["termino el build"]
    # y los subcomandos de F5 NO caen al popup
    lineas = []
    monkeypatch.setattr(cli, "_print_line", lambda t: lineas.append(t))
    cli._slash_notificar("degradados quizas")     # subcomando invalido: usage
    assert mandados == ["termino el build"]
    assert any("degradados on|off" in l for l in lineas)


def test_notificar_estado_sigue_siendo_la_puerta_f5(monkeypatch):
    lineas = []
    monkeypatch.setattr(cli, "_print_line", lambda t: lineas.append(t))
    cli._slash_notificar("estado")
    assert any("notificaciones de escritorio" in l for l in lineas)


def test_solo_un_handler_de_notificar_en_el_dispatch():
    """El elif viejo de '/notificar <mensaje>' era un SEGUNDO handler
    inalcanzable (el nuevo iba antes en la cadena): queda prohibido tener dos."""
    patrones = re.findall(
        r'elif raw == "/notificar" or raw\.startswith\("/notificar "\)|'
        r'elif raw\.startswith\("/notificar "\) or raw == "/notificar"',
        _CLI_SRC)
    assert len(patrones) == 1
