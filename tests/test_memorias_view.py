# -*- coding: utf-8 -*-
"""Tests del dashboard Memorias (cognia/memory/memorias_view.py).

El test que justifica el fichero es
`test_todas_las_acciones_existen_en_el_cli`. La primera version de la tabla
_ACCIONES sugeria CUATRO comandos que no existen (`/programs borrar`,
`/receta ver`, `/receta borrar`, `/workflow ver`). Un dashboard que manda al
dueno a teclear algo que falla es peor que uno sin botones: le hace dudar de
todo lo demas que ve. Este test compara contra el dispatch REAL de cli.py.
"""
from __future__ import annotations

import inspect
import json
import re
from pathlib import Path

import pytest

from cognia.memory import catalogo as C
from cognia.memory import memorias_view as V


RAIZ = Path(__file__).resolve().parent.parent
CLI_SRC = (RAIZ / "cognia" / "cli.py").read_text(encoding="utf-8", errors="replace")


def _cat_de_prueba():
    cat = C.Catalogo()
    cat.filas = [
        C.Fila(id="mi_programa", familia="programa", titulo="Mi Programa",
               resumen="hace algo util", ruta="/tmp/mi_programa",
               creado="2026-08-01T10:00:00", modificado="2026-08-02T11:00:00",
               bytes=2048, etiquetas=["demo"], estado="verificado",
               fuente="test"),
        C.Fila(id="mi_skill", familia="skill", titulo="mi-skill",
               resumen="una skill", ruta="/tmp/mi-skill.md",
               modificado="2026-08-03T12:00:00", fuente="test"),
    ]
    cat.ms = 7
    return cat


# ------------------------------------------------- las acciones son reales

def _comando_existe(cmd: str) -> tuple:
    """(existe, motivo). Comprueba contra el dispatch REAL del CLI.

    Dos vias, porque el CLI despacha de dos maneras: comandos con handler
    propio (`_slash_receta`, donde el subcomando se compara con `cmd ==`) y
    comandos despachados inline en el bucle del REPL (`/programs ver`, que
    aparece como literal `startswith("/programs ver `).
    """
    from cognia import cli

    partes = cmd.split()
    base = partes[0]
    sub = partes[1] if len(partes) > 1 and not partes[1].startswith("{") else ""

    registrado = (base in getattr(cli, "_CMD_DESCRIPTIONS", {})
                  or base in getattr(cli, "_CMD_DETAILS", {}))
    despachado = bool(re.search(
        r'raw\s*==\s*"%s"|raw\.startswith\("%s |raw in \([^)]*"%s"'
        % (re.escape(base), re.escape(base), re.escape(base)), CLI_SRC))
    if not (registrado or despachado):
        return False, f"el comando base {base} no esta registrado ni despachado"

    if not sub:
        return True, ""

    # (a) literal completo en el dispatch inline
    if f'"{base} {sub} ' in CLI_SRC or f'"{base} {sub}"' in CLI_SRC:
        return True, ""

    # (b) subcomando comparado dentro del handler _slash_<nombre>
    nombre = "_slash_" + base.lstrip("/").replace("-", "_")
    handler = getattr(cli, nombre, None)
    if handler is not None:
        try:
            cuerpo = inspect.getsource(handler)
        except OSError:
            cuerpo = ""
        if re.search(r'(cmd|sub|accion|partes\[0\])\s*(==|in)\s*\(?[^)\n]*"%s"'
                     % re.escape(sub), cuerpo):
            return True, ""
        return False, (f"{nombre} no compara el subcomando '{sub}' "
                       f"(subcomandos que si compara: "
                       f"{sorted(set(re.findall(chr(34) + r'([a-z_-]+)' + chr(34), cuerpo)))[:12]})")
    return False, f"no encuentro donde se despacha '{base} {sub}'"


def test_todas_las_acciones_existen_en_el_cli():
    """REGRESION. Cada comando de _ACCIONES tiene que existir de verdad."""
    fallos = []
    for familia, acciones in V._ACCIONES.items():
        for etiqueta, plantilla in acciones.items():
            # se quitan los placeholders para quedarse con el comando pelado
            cmd = plantilla.split("{")[0].strip()
            ok, motivo = _comando_existe(cmd)
            if not ok:
                fallos.append(f"{familia}/{etiqueta}: '{plantilla}' -> {motivo}")
    assert not fallos, ("el dashboard sugiere comandos que no existen:\n  "
                        + "\n  ".join(fallos))


def test_el_test_de_acciones_caza_un_comando_inventado(monkeypatch):
    """Contrafactual: el test de arriba no pasa por casualidad."""
    monkeypatch.setitem(V._ACCIONES, "familia_falsa",
                        {"borrar": "/comando-que-no-existe-jamas {id}"})
    with pytest.raises(AssertionError):
        test_todas_las_acciones_existen_en_el_cli()


def test_toda_familia_con_acciones_esta_en_el_catalogo():
    """Una accion para una familia que el catalogo no produce es codigo
    muerto que nadie ve fallar."""
    for familia in V._ACCIONES:
        assert familia in C.FAMILIAS, f"'{familia}' no es una familia del catalogo"


def test_toda_familia_del_catalogo_tiene_etiqueta_legible():
    """El dueno no tiene por que saber que es una 'corrida'."""
    for familia in C.familias_disponibles():
        assert familia in V._FAMILIAS_UI, f"falta la etiqueta UI de '{familia}'"


# ------------------------------------------------------------ build_data

def test_build_memorias_data_resuelve_los_comandos():
    d = V.build_memorias_data(_cat_de_prueba())
    prog = [f for f in d["filas"] if f["familia"] == "programa"][0]
    cmds = [a["cmd"] for a in prog["acciones"]]
    assert "/programs ver mi_programa" in cmds
    assert not any("{" in c for c in cmds), "quedo un placeholder sin resolver"


def test_el_programa_ofrece_abrir_el_producto():
    """REGRESION 2026-08-29. La ficha de un programa solo sabia ensenar el
    CODIGO ('/programs ver'), que es lo que le interesa a quien programa y no
    a quien quiere USAR lo que Cognia le construyo. '/biblioteca abrir <id>'
    lanza el producto: la web en el navegador, el .py con la app del sistema,
    la carpeta si no hay entrypoint.

    El orden importaba y por eso esto es un test: la accion se anadio DESPUES
    de que el dispatch existiera en cli.py -- al reves,
    test_todas_las_acciones_existen_en_el_cli habria puesto la suite en rojo,
    que es exactamente su trabajo."""
    d = V.build_memorias_data(_cat_de_prueba())
    prog = [f for f in d["filas"] if f["familia"] == "programa"][0]
    cmds = [a["cmd"] for a in prog["acciones"]]
    assert "/biblioteca abrir mi_programa" in cmds
    # y sigue existiendo de verdad en el CLI (la via corta del guardian)
    ok, motivo = _comando_existe("/biblioteca abrir")
    assert ok, motivo


def test_build_memorias_data_solo_lista_familias_con_contenido():
    d = V.build_memorias_data(_cat_de_prueba())
    claves = [f["clave"] for f in d["familias"]]
    assert claves == ["programa", "skill"]
    assert d["total"] == 2


def test_build_memorias_data_arrastra_los_avisos():
    cat = _cat_de_prueba()
    cat.avisos = ["algo no se pudo leer"]
    cat.familias_fallidas = ["sesion"]
    d = V.build_memorias_data(cat)
    assert d["avisos"] == ["algo no se pudo leer"]
    assert d["familias_fallidas"] == ["sesion"]


# ------------------------------------------------------------ render_html

def test_render_html_no_deja_placeholders():
    html = V.render_html(V.build_memorias_data(_cat_de_prueba()))
    assert "__TITLE__" not in html and "__DATA__" not in html


def test_render_html_escapa_el_cierre_de_script():
    """Un artefacto cuyo resumen contenga la cadena de cierre de script
    rompia la pagina ENTERA. Y este catalogo lee texto que Cognia misma
    genero, HTML incluido: no es un caso hipotetico."""
    cat = _cat_de_prueba()
    cat.filas[0].resumen = 'malicioso </script><script>window.roto=1</script>'
    html = V.render_html(V.build_memorias_data(cat))
    # exactamente un cierre: el del script real de la pagina
    assert html.count("</script>") == 1
    assert "window.roto" not in html or "<\\/script>" in html


def test_render_html_es_autocontenido():
    """Cero CDN: la pagina tiene que abrir sin red (regla de la casa,
    heredada de graph_view.py y flow_view.py)."""
    html = V.render_html(V.build_memorias_data(_cat_de_prueba()))
    for prohibido in ("http://", "https://", "src=", "@import"):
        assert prohibido not in html, f"la pagina depende de '{prohibido}'"


def test_render_html_define_los_dos_temas():
    """Modo oscuro y claro REALES: los dos redefinen los mismos tokens."""
    html = V.render_html(V.build_memorias_data(_cat_de_prueba()))
    assert ":root{" in html
    assert ':root[data-tema="claro"]{' in html
    tokens_oscuro = set(re.findall(r"--([a-z0-9]+):",
                                   html.split(":root{")[1].split("}")[0]))
    tokens_claro = set(re.findall(r"--([a-z0-9]+):",
                                  html.split(':root[data-tema="claro"]{')[1].split("}")[0]))
    faltan = tokens_oscuro - tokens_claro
    assert not faltan, f"el tema claro no redefine: {faltan} (heredaria el oscuro)"


def test_export_escribe_y_no_abre(tmp_path):
    destino = tmp_path / "memorias.html"
    ruta = V.export(_cat_de_prueba(), str(destino), open_browser=False)
    assert Path(ruta) == destino and destino.exists()
    assert destino.read_text(encoding="utf-8").startswith("<!doctype html>")


def test_export_crea_el_directorio(tmp_path):
    destino = tmp_path / "sub" / "dir" / "m.html"
    V.export(_cat_de_prueba(), str(destino), open_browser=False)
    assert destino.exists()


def test_datos_embebidos_son_json_valido(tmp_path):
    destino = tmp_path / "m.html"
    V.export(_cat_de_prueba(), str(destino), open_browser=False)
    html = destino.read_text(encoding="utf-8")
    crudo = re.search(r"const DATOS = (.*?);\n", html, re.S).group(1)
    datos = json.loads(crudo.replace("<\\/", "</"))
    assert datos["total"] == 2
