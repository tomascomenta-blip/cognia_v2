# -*- coding: utf-8 -*-
"""
tests/test_harness_ayuda.py
===========================
Regresion de la ayuda navegable (2026-08-12).

Sin `cognia/harness/ayuda.py` el modulo no importa y TODO este fichero falla en
la coleccion; con el, pasa. Lo que se defiende:

- el catalogo REAL (240 entradas de `_CMD_DESCRIPTIONS`) se clasifica ENTERO y
  ninguna categoria pasa de 25 comandos (la promesa "cada categoria cabe en una
  pantalla" es un chequeo, no una frase en el docstring);
- la portada CABE en 25 lineas y NO vuelca los 240 comandos (el bug de origen:
  13.438 px de pared de texto);
- las dos columnas quedan ALINEADAS (columna 2 siempre en la misma posicion);
- la busqueda tolera acentos y ordena por calidad de coincidencia;
- el fallback ASCII de los glifos deja la salida imprimible en una consola
  Windows cp437 (sin esto, /ayuda revienta con UnicodeEncodeError).

El dict del catalogo se saca de `cognia/cli.py` con `ast` a proposito: es el
dato REAL, sin importar el monolito (el modulo bajo prueba tampoco lo importa).
"""
from __future__ import annotations

import ast
import importlib
import os
from pathlib import Path

import pytest

from cognia.harness import ayuda

RAIZ = Path(__file__).resolve().parents[1]


def _catalogo_real() -> dict:
    """_CMD_DESCRIPTIONS leido del fuente de cli.py (sin importarlo)."""
    src = (RAIZ / "cognia" / "cli.py").read_text(encoding="utf-8")
    for nodo in ast.walk(ast.parse(src)):
        if isinstance(nodo, ast.Assign) and any(
                getattr(t, "id", "") == "_CMD_DESCRIPTIONS"
                for t in nodo.targets):
            return ast.literal_eval(nodo.value)
    raise AssertionError("no se encontro _CMD_DESCRIPTIONS en cognia/cli.py")


@pytest.fixture(scope="module")
def catalogo() -> dict:
    d = _catalogo_real()
    assert len(d) > 190, "el catalogo real deberia tener ~240 comandos"
    return d


# fixture chico e independiente del repo, para las reglas puras
MINI = {
    "/hacer": "Modo agente: ejecuta tarea con herramientas <tarea>",
    "/buscar": "Buscar patron en archivos  <patron> [dir]",
    "/buscar-kg": "Buscar en grafo de conocimiento local    <concepto>",
    "/buscar-web": "Buscar en web (DuckDuckGo)               <query>",
    "/buscar-historial": "Buscar en el historial por keyword      <keyword>",
    "/contexto": "Buscar en el mapa de contexto   <consulta>",
    "/contexto-semantico": "Ver contexto de conversacion relacionado semanticamente",
    "/dormir": "Ciclo de consolidación tipo sueño",
    "/modelo": "Ver/cambiar modelo GGUF del backend  [patron | unico | flota]",
    "/salir": "Salir del REPL",
}


# ---------------------------------------------------------------------------
# API y clasificacion
# ---------------------------------------------------------------------------
def test_api_publica_existe():
    for nombre in ("clasificar", "indice", "portada", "seccion", "todo",
                   "buscar", "sugerir", "desbordes", "resolver_categoria",
                   "mensaje_desconocido"):
        assert callable(getattr(ayuda, nombre)), nombre
    assert isinstance(ayuda.CATEGORIAS, dict) and len(ayuda.CATEGORIAS) >= 8
    assert list(ayuda.CATEGORIAS)[-1] == "Otros", "Otros va SIEMPRE al final"


def test_clasificar_exacto_le_gana_al_prefijo():
    # el caso que motiva la regla del patron mas largo: cinco '/buscar*'
    assert ayuda.clasificar("/buscar", MINI["/buscar"]) == "Codigo y ficheros"
    assert ayuda.clasificar("/buscar-kg", "") == "Grafo de conocimiento"
    assert ayuda.clasificar("/buscar-web", "") == "Web e investigacion"
    assert ayuda.clasificar("/buscar-historial", "") == "Sesion e historial"
    assert ayuda.clasificar("/contexto", "") == "Sesion e historial"
    assert ayuda.clasificar("/contexto-semantico", "") == "Memoria y notas"


def test_clasificar_cae_a_descripcion_y_luego_a_otros():
    # comando que NO esta en la tabla: manda la descripcion
    assert ayuda.clasificar("/zzz-nuevo", "Buscar en la web algo") == \
        "Web e investigacion"
    assert ayuda.clasificar("/zzz-nuevo", "Agregar triple al knowledge graph") \
        == "Grafo de conocimiento"
    # sin pistas de ningun tipo -> Otros, nunca se pierde
    assert ayuda.clasificar("/zzz", "qwerty asdf") == "Otros"
    assert ayuda.clasificar("", "") == "Otros"


def test_ningun_patron_repetido_entre_categorias():
    vistos = {}
    for cat, patrones in ayuda.CATEGORIAS.items():
        for p in patrones:
            assert p not in vistos, (
                "%s esta en %s y en %s" % (p, vistos.get(p), cat))
            vistos[p] = cat


def test_catalogo_real_clasificado_entero(catalogo):
    idx = ayuda.indice(catalogo, 100)
    total = sum(len(e) for _, e in idx)
    assert total == len(catalogo), "se perdieron comandos al clasificar"
    nombres = {c for _, e in idx for c, _ in e}
    assert nombres == set(catalogo)


def test_ninguna_categoria_desborda_el_tope(catalogo):
    sobra = ayuda.desbordes(catalogo, ayuda.TOPE_CATEGORIA)
    assert sobra == [], "categorias mas largas que una pantalla: %s" % sobra


def test_indice_ordenado_y_descripciones_de_una_linea(catalogo):
    idx = ayuda.indice(catalogo, 100)
    orden = [c for c, _ in idx]
    assert orden == [c for c in ayuda.CATEGORIAS if c in orden]
    for _, entradas in idx:
        assert entradas == sorted(entradas, key=lambda p: ayuda.normalizar(p[0]))
        for cmd, desc in entradas:
            assert "\n" not in desc
            assert ayuda.ancho_visual(desc) <= 100 - 30
            assert "Uso:" not in desc, cmd


# ---------------------------------------------------------------------------
# Portada
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("ancho", [60, 80, 100, 120])
def test_portada_cabe_en_25_lineas_y_en_el_ancho(catalogo, ancho):
    txt = ayuda.portada(catalogo, ancho)
    lineas = txt.splitlines()
    assert len(lineas) <= 25, "la portada volvio a desbordar: %d" % len(lineas)
    assert max(ayuda.ancho_visual(l) for l in lineas) <= ancho


def test_portada_no_vuelca_el_catalogo(catalogo):
    txt = ayuda.portada(catalogo, 100)
    presentes = sum(1 for c in catalogo if c + " " in txt or c + "\n" in txt)
    assert presentes <= 20, "la portada esta listando el catalogo entero"
    # ...pero si ensena por donde seguir
    assert "/ayuda buscar" in txt and "/ayuda todo" in txt
    assert "<categoria>" in txt


def test_portada_muestra_esenciales_y_cuentas(catalogo):
    txt = ayuda.portada(catalogo, 100)
    for cmd in ("/hacer", "/pensar", "/crear", "/salir"):
        assert cmd in txt
    assert str(len(catalogo)) in txt
    for cat, entradas in ayuda.indice(catalogo, 100):
        assert "%s (%d)" % (cat, len(entradas)) in txt


def test_portada_con_catalogo_vacio_no_lanza():
    txt = ayuda.portada({}, 80)
    assert isinstance(txt, str) and "/ayuda" in txt


def test_portada_conserva_las_pistas_aunque_tenga_que_recortar(catalogo,
                                                               monkeypatch):
    """La garantia del docstring es "recorta esenciales, nunca las pistas".
    Con el corte final [:LIMITE] las pistas se perdian en cuanto el bloque de
    categorias no entraba; aca se fuerza ese escenario bajando el limite."""
    monkeypatch.setattr(ayuda, "LIMITE_PORTADA", 12)
    for ancho in (40, 100):
        txt = ayuda.portada(catalogo, ancho)
        lineas = txt.splitlines()
        assert len(lineas) <= 12, (ancho, len(lineas))
        assert "Ver mas" in txt and "/ayuda todo" in txt, ancho
        assert "/ayuda buscar" in txt, ancho
        assert max(ayuda.ancho_visual(l) for l in lineas) <= ancho


# ---------------------------------------------------------------------------
# Secciones
# ---------------------------------------------------------------------------
def _offsets_columna2(texto: str) -> set:
    offs = set()
    for linea in texto.splitlines()[2:]:
        i = linea.rfind("  /")
        if i > 0:
            offs.add(ayuda.ancho_visual(linea[:i + 2]))
    return offs


@pytest.mark.parametrize("ancho", [70, 80, 100, 120])
def test_seccion_dos_columnas_alineadas(catalogo, ancho):
    txt = ayuda.seccion(catalogo, "Sesion e historial", ancho)
    assert len(_offsets_columna2(txt)) == 1, "la segunda columna baila"
    assert max(ayuda.ancho_visual(l) for l in txt.splitlines()) <= ancho


def test_seccion_angosta_cae_a_una_columna(catalogo):
    txt = ayuda.seccion(catalogo, "Sesion e historial", 44)
    cuerpo = txt.splitlines()[2:]
    assert all(l.count("  /") <= 1 for l in cuerpo)
    assert max(ayuda.ancho_visual(l) for l in txt.splitlines()) <= 44


def test_seccion_acepta_nombre_suelto_y_acentos(catalogo):
    a = ayuda.seccion(catalogo, "memoria", 100)
    b = ayuda.seccion(catalogo, "Memoria y notas", 100)
    assert a == b
    assert ayuda.resolver_categoria("sesión") == "Sesion e historial"
    assert ayuda.resolver_categoria("CODIGO") == "Codigo y ficheros"
    assert ayuda.resolver_categoria("1") == list(ayuda.CATEGORIAS)[0]
    assert ayuda.resolver_categoria("no-existe-nada") is None


def test_seccion_desconocida_devuelve_menu_sin_lanzar(catalogo):
    txt = ayuda.seccion(catalogo, "zzzz", 100)
    assert "No hay una categoria" in txt
    assert "Agente y tareas" in txt


@pytest.mark.parametrize("ancho", [40, 44, 60, 200])
def test_todo_lo_que_se_imprime_cabe_en_el_ancho(catalogo, ancho):
    """El caso limite REAL: a 40 columnas la cabecera de la portada media 46,
    la de la seccion 41 y el menu de categorias salia de un tiron en UNA linea
    de 294. Cualquier salida del modulo tiene que caber en el ancho pedido."""
    piezas = {
        "portada": ayuda.portada(catalogo, ancho),
        "seccion": ayuda.seccion(catalogo, "Perfil y personalizacion", ancho),
        "todo": ayuda.todo(catalogo, ancho),
        "menu": ayuda.seccion(catalogo, "zzzz", ancho),
        "desconocido": ayuda.mensaje_desconocido(catalogo, "/memria",
                                                 ancho=ancho),
    }
    for nombre, txt in piezas.items():
        anchos = [ayuda.ancho_visual(l) for l in txt.splitlines()]
        assert max(anchos) <= ancho, "%s desborda: %d > %d" % (
            nombre, max(anchos), ancho)


def test_marcado_no_desborda_en_consola_angosta(catalogo):
    """Con marcado el relleno queda DENTRO del markup y el rstrip ya no lo
    quita: el bloque de categorias se pasaba del ancho sin que se viera."""
    import re
    for ancho in (40, 52, 100):
        txt = ayuda.portada(catalogo, ancho, marcado=True)
        for linea in txt.splitlines():
            limpio = re.sub(r"\[/?[a-z_]+\]", "", linea).replace("\\[", "[")
            assert ayuda.ancho_visual(limpio) <= ancho, (ancho, limpio)


def test_mensaje_desconocido_envuelve_y_recorta(catalogo):
    largo = "/" + "z" * 200
    txt = ayuda.mensaje_desconocido(catalogo, largo, ancho=48)
    assert max(ayuda.ancho_visual(l) for l in txt.splitlines()) <= 48
    assert "/ayuda buscar" in txt


def test_todo_cubre_los_240_comandos(catalogo):
    txt = ayuda.todo(catalogo, 120)
    faltan = [c for c in catalogo if c not in txt]
    assert faltan == [], "/ayuda todo perdio comandos: %s" % faltan[:5]
    assert max(ayuda.ancho_visual(l) for l in txt.splitlines()) <= 120


# ---------------------------------------------------------------------------
# Busqueda y sugerencias
# ---------------------------------------------------------------------------
def test_buscar_ordena_por_calidad():
    res = ayuda.buscar(MINI, "buscar")
    assert res[0][0] == "/buscar" and res[0][2] == "nombre exacto"
    motivos = [m for _, _, m in res]
    orden = ["nombre exacto", "empieza por", "en el nombre", "en la descripcion"]
    assert motivos == sorted(motivos, key=orden.index)


def test_buscar_tolera_acentos_en_los_dos_lados(catalogo):
    # la consulta con acento encuentra el comando sin acento...
    assert any(c == "/sesiones" for c, _, _ in ayuda.buscar(catalogo, "sesión"))
    # ...y la consulta sin acento encuentra la descripcion CON acento
    res = ayuda.buscar(MINI, "consolidacion")
    assert [c for c, _, _ in res] == ["/dormir"]
    assert res[0][2] == "en la descripcion"


def test_buscar_respeta_el_limite_y_la_barra(catalogo):
    assert len(ayuda.buscar(catalogo, "a", limite=5)) == 5
    assert ayuda.buscar(catalogo, "/modelo")[0][0] == "/modelo"
    assert ayuda.buscar(catalogo, "   ") == []


def test_limite_cero_no_cuela_resultados(catalogo):
    """limite=0 es "no me des nada": el max(1, ...) devolvia UN resultado."""
    assert ayuda.buscar(catalogo, "modelo", limite=0) == []
    assert ayuda.buscar(catalogo, "modelo", limite=-3) == []
    assert ayuda.sugerir(catalogo, "/memo", limite=0) == []
    assert len(ayuda.buscar(catalogo, "modelo", limite=2)) == 2


def test_sugerir_con_typo_y_con_prefijo(catalogo):
    assert "/memoria" in ayuda.sugerir(catalogo, "/memria")
    assert "/tarea-lista" in ayuda.sugerir(catalogo, "/tarea-lsta")
    assert "/memoria" in ayuda.sugerir(catalogo, "/memo")
    assert len(ayuda.sugerir(catalogo, "/memo", limite=2)) == 2
    assert ayuda.sugerir(catalogo, "/qwertyuiopasdfgh") == []
    assert ayuda.sugerir({}, "/x") == []


def test_mensaje_desconocido_propone_y_ensena(catalogo):
    txt = ayuda.mensaje_desconocido(catalogo, "/tarea")
    assert "/tarea" in txt
    assert "Quiza quisiste decir" in txt and "/tareas" in txt
    assert "/ayuda buscar" in txt


# ---------------------------------------------------------------------------
# Windows / rich
# ---------------------------------------------------------------------------
def test_fallback_ascii_imprimible_en_consola_cp437(catalogo):
    """Con COGNIA_AYUDA_ASCII=1 toda la salida entra en cp437 (la consola de
    Windows por defecto). Sin esto, /ayuda muere con UnicodeEncodeError."""
    previo = os.environ.get("COGNIA_AYUDA_ASCII")
    os.environ["COGNIA_AYUDA_ASCII"] = "1"
    try:
        mod = importlib.reload(ayuda)
        assert mod.GLIFOS["regla"] == "-" and mod.GLIFOS["elipsis"] == "..."
        salida = "\n".join([
            mod.portada(catalogo, 80),
            mod.seccion(catalogo, "Codigo y ficheros", 80),
            mod.mensaje_desconocido(catalogo, "/xyz"),
        ])
        # las descripciones del catalogo traen acentos; el ARMADO es lo que se
        # exige ASCII, asi que se mira solo lo que pone este modulo
        armado = "".join(ch for ch in salida if ord(ch) < 128 or ch in "áéíóúñÁÉÍÓÚÑ")
        armado.encode("cp437")
    finally:
        if previo is None:
            os.environ.pop("COGNIA_AYUDA_ASCII", None)
        else:
            os.environ["COGNIA_AYUDA_ASCII"] = previo
        importlib.reload(ayuda)


def test_marcado_rich_escapa_corchetes():
    """Una descripcion con '[' es markup para rich: si no se escapa, rich se
    come el texto (o lanza). El caso vive aca porque resumir_desc ya recorta
    las plantillas de argumentos del catalogo real."""
    con_corchete = {"/zzz-raro": "Hace [algo] con corchetes"}
    rico = ayuda.seccion(con_corchete, "Otros", 80, marcado=True)
    assert "\\[algo]" in rico, "los corchetes de la descripcion sin escapar"


def test_marcado_rich_no_mueve_el_ancho(catalogo):
    plano = ayuda.seccion(catalogo, "Modelos y flota", 100, marcado=False)
    rico = ayuda.seccion(catalogo, "Modelos y flota", 100, marcado=True)
    assert "[mod]" in rico and "[info_dim]" in rico
    # el texto util es el mismo: quitar el markup devuelve el plano
    import re
    limpio = re.sub(r"\[/?[a-z_]+\]", "", rico).replace("\\[", "[")
    assert [l.rstrip() for l in limpio.splitlines()] == \
           [l.rstrip() for l in plano.splitlines()]


def test_los_mandos_del_arnes_tienen_categoria_propia(catalogo):
    """Revision adversarial 2026-08-24: /bucle caia por palabra clave en
    'Agente y tareas' (26 > tope 25), /pegado y /spinner en 'Otros', /offload
    en 'Modelos y flota', /expandir en 'Perfil' y /markdown, /enlaces y
    /config-resuelta en 'Codigo y ficheros'. Los ocho son mandos del ARNES de
    la consola y van juntos; y ninguno queda en el cajon de 'Otros'."""
    # Fusion 2026-08-25: /deshacer (revertir lo que escribio el agente) y
    # /remoto (la consola manejada desde el movil) tambien son mandos del
    # arnes; salieron de "Agente y tareas" (27 > tope 25) y de "Web".
    # 2026-08-25 (salvaguarda de borrado): /deshacer-borrado saca de la
    # papelera lo que el agente BORRO, hermano de /deshacer, y por la misma
    # razon: sin ponerlo aqui caia en "Agente y tareas" y la dejaba en 26.
    # 2026-08-30: /revision (la compuerta que CORRE lo construido antes de
    # entregarlo) es un mando del arnes por el mismo criterio que /bucle:
    # sin ponerlo aqui caia en "Agente y tareas" por la palabra "agente".
    esperados = ("/markdown", "/spinner", "/expandir", "/offload", "/pegado",
                 "/enlaces", "/bucle", "/config-resuelta", "/deshacer",
                 "/remoto", "/deshacer-borrado", "/revision")
    for cmd in esperados:
        assert cmd in catalogo, cmd
        assert ayuda.clasificar(cmd, catalogo[cmd]) == "Consola y arnes", cmd
    cajones = dict(ayuda.indice(catalogo, 200))
    assert len(cajones.get("Consola y arnes", [])) == len(esperados)
    assert not cajones.get(ayuda._OTROS), cajones.get(ayuda._OTROS)
