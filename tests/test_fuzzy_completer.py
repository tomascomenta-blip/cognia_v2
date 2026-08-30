"""
tests/test_fuzzy_completer.py
=============================
Paleta fuzzy de /comandos (fzf-style): FuzzyCompleter de prompt_toolkit
envolviendo al _CogniaCompleter real de cli.py.

POR QUE se testea el envoltorio directo y no la PromptSession: el fuzzy
es pura composicion (FuzzyCompleter(inner)) y get_completions funciona
con un Document sintetico, sin tty ni consola Win32 -- el mismo camino
que recorre el REPL al teclear.

NOTA sobre '/hz' -> '/hacer' (pedido original): el fuzzy de
prompt_toolkit exige SUBSECUENCIA (letras en orden) y 'hacer' no
contiene 'z', asi que ese par es imposible por diseno del matcher. Se
prueban pares reales equivalentes: '/hcr' -> '/hacer', '/plr' ->
'/pulir', '/esfz' -> '/esfuerzo'.

ENMIENDA 2026-08-29 -- EL COMPLETER YA NO OFRECE TODO EL CATALOGO
-----------------------------------------------------------------
QUE CAMBIO: `_CogniaCompleter.get_completions` (cognia/cli.py) recorre
`_cmds_visibles()` y ya no `_CMD_DESCRIPTIONS`.

QUE FASE LO CAMBIO: la obra del editor visual de flujos (2026-08-29)
introdujo `cognia/cli_visibilidad.py` y el comando `/avanzado`.

QUE RASGO LO JUSTIFICA: el dueno pidio ocultar los comandos de nicho.
`_CMD_DESCRIPTIONS` tiene 280 entradas; en el nivel por defecto
("nucleo") se ANUNCIAN 82. `/pulir` vive en AVANZADO, asi que en modo
nucleo el completer NO lo ofrece -- ni tecleado entero ni por fuzzy.
Eso NO es una regresion: es la feature.

QUE ESTABA MAL EN ESTE FICHERO: dos tests (`test_fuzzy_plr_ofrece_pulir`
y `test_match_exacto_va_primero`) fijaban el contrato viejo usando
`/pulir`, y se pusieron rojos. Peor: sus hermanos seguian verdes POR
CASUALIDAD, porque `/hacer` y `/esfuerzo` resultan ser de NUCLEO y nadie
lo habia escrito en ninguna parte. Ahora el nivel se fija a proposito en
cada caso y el comando se elige declarando su cubo (`cli_visibilidad.NUCLEO`
/ `AVANZADO`), nunca por casualidad.

COMO SE FIJA EL NIVEL: por el `override` de `cli_visibilidad`, que es su
puerta declarada "sin disco". NO se escribe ~/.cognia/config.env: el
disco del dueno no es un fixture.
"""

import pytest

pytest.importorskip("prompt_toolkit")

from prompt_toolkit.completion import CompleteEvent, FuzzyCompleter
from prompt_toolkit.document import Document

import cognia.cli as cli
from cognia import cli_visibilidad as vis

# Comandos elegidos por su CUBO, no por costumbre. Las aserciones de abajo
# los verifican: si manana alguien mueve /hacer a AVANZADO, este fichero
# falla diciendo por que, en vez de fallar por un '[]' misterioso.
CMD_NUCLEO = "/hacer"         # NUCLEO: se ofrece en los dos niveles
CMD_NUCLEO_2 = "/esfuerzo"    # NUCLEO
CMD_OCULTO = "/pulir"         # AVANZADO: oculto en el nivel por defecto


def test_los_comandos_de_este_fichero_estan_en_el_cubo_que_se_supone():
    """Guardian del guardian: los tests de abajo solo significan algo si el
    cubo de cada comando es el que dicen. Antes esto era una casualidad."""
    assert CMD_NUCLEO in vis.NUCLEO
    assert CMD_NUCLEO_2 in vis.NUCLEO
    assert CMD_OCULTO in vis.AVANZADO
    assert CMD_OCULTO not in vis.NUCLEO


@pytest.fixture
def nivel(monkeypatch):
    """fijar("nucleo"|"todo") -> el nivel del catalogo, sin tocar disco.

    Se monkeypatchea `get_nivel_cmds` para que delegue en la funcion REAL con
    su `override` (la puerta que el propio modulo documenta como libre de
    disco), y se fija `_ui_simple()` a True porque es la OTRA entrada de
    `es_avanzado()`: sin fijarla, el resultado dependeria del `/modo` de la
    maquina que corre los tests. El resto del camino (es_avanzado ->
    visibles -> _cmds_visibles -> el completer) es el de produccion.
    """
    real = vis.get_nivel_cmds

    def fijar(valor: str):
        monkeypatch.setattr(vis, "get_nivel_cmds",
                            lambda override=None, _v=valor: real(_v))
        monkeypatch.setattr(vis, "_ui_simple", lambda: True)
        vis.invalidar_cache()

    yield fijar
    vis.invalidar_cache()


def _completer_fuzzy():
    inner_cls = getattr(cli, "_CogniaCompleter", None)
    if inner_cls is None:  # sin prompt_toolkit el REPL cae a input() plano
        pytest.skip("cli sin prompt_toolkit: no hay _CogniaCompleter")
    return FuzzyCompleter(inner_cls())


def _textos(entrada: str) -> list:
    doc = Document(entrada, len(entrada))
    comps = list(_completer_fuzzy().get_completions(doc, CompleteEvent()))
    return [c.text for c in comps]


# ---------------------------------------------------------------------------
# 1. El fuzzy, sobre comandos de NUCLEO (visibles en cualquier nivel)
# ---------------------------------------------------------------------------

def test_fuzzy_hcr_ofrece_hacer(nivel):
    # subsecuencia h-c-r dentro de 'hacer': el typo/atajo no castiga.
    # /hacer es de NUCLEO, asi que esto vale en el nivel POR DEFECTO.
    nivel("nucleo")
    assert CMD_NUCLEO in _textos("/hcr")


def test_fuzzy_esfz_ofrece_esfuerzo(nivel):
    # idem: /esfuerzo es de NUCLEO.
    nivel("nucleo")
    assert CMD_NUCLEO_2 in _textos("/esfz")


def test_prefijo_exacto_sigue_funcionando(nivel):
    # regresion: lo que el completer viejo ofrecia por prefijo debe
    # seguir apareciendo envuelto en fuzzy
    nivel("nucleo")
    assert CMD_NUCLEO in _textos("/hac")


# ---------------------------------------------------------------------------
# 2. El fuzzy, sobre un comando OCULTO: el rasgo y su contraparte
# ---------------------------------------------------------------------------

def test_fuzzy_no_ofrece_un_comando_oculto_en_nucleo(nivel):
    """EL RASGO (2026-08-29): en el nivel por defecto, /pulir no se anuncia.

    Este test es la mitad que el fichero no tenia y por eso el cambio salio
    como 'regresion' en vez de como feature. Si manana alguien vuelve a
    ofrecer el catalogo entero en el completer, esto se pone rojo."""
    nivel("nucleo")
    assert CMD_OCULTO not in _textos("/plr")
    # ni siquiera tecleado entero: ocultar es ocultar del ANUNCIO
    assert CMD_OCULTO not in _textos(CMD_OCULTO)


def test_fuzzy_plr_ofrece_pulir_en_avanzado(nivel):
    """LA CONTRAPARTE: con /avanzado el fuzzy sigue haciendo su trabajo.

    Es lo que demuestra que en nucleo falta por el FILTRO y no porque el
    matcher se haya roto: mismo texto, mismo completer, otro nivel."""
    nivel("todo")
    assert CMD_OCULTO in _textos("/plr")


# ---------------------------------------------------------------------------
# 3. Orden: el match exacto arriba
# ---------------------------------------------------------------------------

def test_match_exacto_va_primero(nivel):
    # el comando tipeado completo debe quedar arriba: si el fuzzy
    # reordenara el match exacto, el Tab del usuario elegiria otro.
    # Con un comando de NUCLEO, para que valga en el nivel POR DEFECTO
    # (antes se probaba con /pulir y el caso murio al ocultarse).
    nivel("nucleo")
    textos = _textos(CMD_NUCLEO)
    assert textos and textos[0] == CMD_NUCLEO


def test_match_exacto_va_primero_en_avanzado(nivel):
    # el orden no puede depender del tamano del catalogo: con los 280
    # comandos anunciados hay muchos mas candidatos ('/deshacer',
    # '/mesh_publicar'...) y el exacto tiene que seguir primero.
    nivel("todo")
    textos = _textos(CMD_NUCLEO)
    assert textos and textos[0] == CMD_NUCLEO
    textos_ocultos = _textos(CMD_OCULTO)
    assert textos_ocultos and textos_ocultos[0] == CMD_OCULTO


# ---------------------------------------------------------------------------
# 4. OCULTAR NO ES DESACTIVAR
# ---------------------------------------------------------------------------

def test_ocultar_no_borra_el_comando_del_catalogo_fuente(nivel):
    """Un comando oculto sigue EXISTIENDO para el que lo teclea entero.

    Que la rama `elif raw == "/pulir"` del despachador siga ahi (y que
    ninguna rama del if/elif consulte la visibilidad) lo vigila
    tests/test_cli_visibilidad.py::test_ocultar_no_desactiva, por regex sobre
    el fuente; no se duplica aqui.

    Lo que SI se vigila aqui, y no vigila nadie mas, es la otra mitad del
    contrato: que el filtro del completer sea un FILTRO SOBRE UNA COPIA y no
    un borrado. `_cmds_visibles()` corre en CADA pulsacion de tecla; si
    `visibles()` mutase el dict fuente, la primera letra que teclease el
    dueno dejaria a /pulir fuera de `_CMD_DESCRIPTIONS` -- y con el, fuera de
    `/ayuda todo` y de la sugerencia de `mensaje_desconocido`, que leen ese
    dict entero (cli.py, rama `elif raw.startswith("/")`).
    """
    nivel("nucleo")
    antes = dict(cli._CMD_DESCRIPTIONS)
    assert CMD_OCULTO in antes

    visibles = cli._cmds_visibles()
    assert CMD_OCULTO not in visibles, "el rasgo: oculto del anuncio"
    assert len(visibles) < len(antes)

    # y teclear (lo que dispara el completer una vez por letra) no lo borra
    _textos("/p")
    _textos(CMD_OCULTO)
    assert cli._CMD_DESCRIPTIONS == antes, (
        "el filtro de visibilidad MUTO el catalogo fuente: ocultar se "
        "convirtio en desactivar")
    assert CMD_OCULTO in cli.COMMANDS


# ---------------------------------------------------------------------------
# 5. Limites del matcher (independientes del nivel)
# ---------------------------------------------------------------------------

def test_sin_slash_no_explota_y_no_sugiere(nivel):
    # el inner solo se activa con '/': texto libre no debe sugerir nada
    nivel("nucleo")
    assert _textos("hola mundo") == []


def test_letra_inexistente_no_matchea(nivel):
    # documenta el limite del matcher: 'z' no esta en 'hacer', asi que
    # '/hz' NO puede ofrecer /hacer (subsecuencia estricta). Se mide en
    # 'todo' para que el catalogo grande no sea la excusa del vacio.
    nivel("todo")
    assert CMD_NUCLEO not in _textos("/hz")


# ---------------------------------------------------------------------------
# 6. La rama de '/flujoteca ' (obra 4.14.0)
# ---------------------------------------------------------------------------
# Hasta hoy `get_completions` cortaba en seco con `if " " in text: return`
# salvo para '/bots ': tecleando '/flujoteca ' no se ofrecia NADA, ni los
# subcomandos ni los nombres de flujo -- y los nombres de flujo llevan
# espacios ("Informe semanal"), o sea que son justo lo que nadie recuerda de
# memoria. La rama nueva completa las dos cosas, y lo hace CONTRA UNA CACHE:
# el completer corre en cada pulsacion y `flujoteca.listar()` abre un JSON por
# flujo.

@pytest.fixture
def biblioteca(tmp_path, monkeypatch):
    """Una flujoteca temporal con dos flujos. Devuelve el modulo."""
    from cognia.agent import flujoteca as ft
    monkeypatch.setenv("COGNIA_FLUJOTECA_DIR", str(tmp_path / "flujoteca"))
    cli._flujoteca_invalidar_completar()
    for nombre in ("Informe semanal", "pvz1"):
        ft.guardar({"nombre": nombre, "nodos": [
            {"id": "leer", "tool": "leer_archivo", "args": "x", "wires": []}]},
            nombre=nombre, nota="test")
    cli._flujoteca_invalidar_completar()
    yield ft
    cli._flujoteca_invalidar_completar()


def _textos_planos(entrada: str) -> list:
    """Sin el FuzzyCompleter: la rama de /flujoteca completa por PREFIJO (un
    nombre de flujo no es un comando y el fuzzy lo desordenaria)."""
    inner_cls = getattr(cli, "_CogniaCompleter", None)
    if inner_cls is None:
        pytest.skip("cli sin prompt_toolkit")
    doc = Document(entrada, len(entrada))
    return [c.text for c in inner_cls().get_completions(doc, CompleteEvent())]


def test_flujoteca_primer_token_ofrece_subcomandos(nivel, biblioteca):
    nivel("nucleo")
    ofrecidos = _textos_planos("/flujoteca eje")
    assert ofrecidos == ["ejecutar"]


def test_flujoteca_tras_ejecutar_ofrece_nombres_de_flujo(nivel, biblioteca):
    nivel("nucleo")
    assert _textos_planos("/flujoteca ejecutar Inf") == ["Informe semanal"]
    assert _textos_planos("/flujoteca correr p") == ["pvz1"]
    assert sorted(_textos_planos("/flujoteca editar ")) == [
        "Informe semanal", "pvz1"]


def test_flujoteca_nuevo_no_completa_nombres(nivel, biblioteca):
    """`nuevo` pide un nombre que TODAVIA no existe: ofrecerle los que ya
    estan solo puede llevar a una colision."""
    nivel("nucleo")
    assert _textos_planos("/flujoteca nuevo p") == []


def test_el_completer_no_lista_la_biblioteca_por_pulsacion(nivel, biblioteca,
                                                           monkeypatch):
    """El invariante caro: `get_completions` corre con CADA TECLA. Se teclea
    'ejecutar Informe semanal' letra a letra y se cuenta cuantas veces se
    abrio la biblioteca."""
    nivel("nucleo")
    llamadas = []
    real = biblioteca.listar
    monkeypatch.setattr(biblioteca, "listar",
                        lambda: llamadas.append(1) or real())
    base = "/flujoteca ejecutar "
    objetivo = "Informe semanal"
    for i in range(len(objetivo) + 1):
        _textos_planos(base + objetivo[:i])
    assert len(llamadas) <= 1, (
        f"{len(llamadas)} lecturas de la biblioteca para "
        f"{len(objetivo) + 1} pulsaciones")


def test_flujoteca_sin_biblioteca_no_explota(nivel, tmp_path, monkeypatch):
    """Un directorio de flujoteca que no existe no puede tumbar el prompt."""
    nivel("nucleo")
    monkeypatch.setenv("COGNIA_FLUJOTECA_DIR", str(tmp_path / "no-existe"))
    cli._flujoteca_invalidar_completar()
    assert _textos_planos("/flujoteca ejecutar x") == []
