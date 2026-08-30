# -*- coding: utf-8 -*-
"""
tests/test_cli_visibilidad.py
=============================
Guardianes del reparto de comandos en tres cubos (PEDIDO 1, 2026-08-29).

Lo que defienden, en orden de importancia:

1. LA PARTICION NO SE DESINCRONIZA. `cognia/cli_visibilidad.py` enumera a mano
   las ~280 claves de `_CMD_DESCRIPTIONS`. Una lista escrita a mano se pudre en
   una semana: el test 1 lee el catalogo REAL del fuente de `cli.py` con `ast`
   (nunca importando el monolito) y exige que la union de los tres cubos sea
   exactamente ese catalogo. Un comando nuevo sin clasificar pone esto rojo el
   mismo dia en que se registra.

2. OCULTAR NO ES DESACTIVAR. El test 4 comprueba por regex sobre el fuente que
   los comandos de LABORATORIO siguen teniendo su rama en el despachador. Si
   alguien "optimiza" filtrando ahi, un comando que hoy funciona respondera
   "Comando desconocido" en el modo por defecto, indistinguible de una errata.

3. EL AUTOCOMPLETADO NO TOCA DISCO. `get_completions` corre en CADA pulsacion
   de tecla; el test 7 cuenta las lecturas de `first_run._load_config` en 500
   llamadas y exige como mucho una.

Dos tests estan en `xfail(strict=False)` a proposito: comprueban cambios sobre
`cognia/cli.py` y `cognia/user_prefs.py`, que son de la fase de cableado
(F-CABLE / F-REMOTO) y todavia no han aterrizado. `strict=False` para que se
pongan en VERDE solos (xpass) en cuanto esa fase entre, sin tener que volver
aqui a borrar la marca: son la lista de pendientes ejecutable, no un permiso
para no hacerlo.
"""
from __future__ import annotations

import ast
import os
import re
from pathlib import Path

import pytest

from cognia import cli_visibilidad as vis

RAIZ = Path(__file__).resolve().parents[1]


def _catalogo_real() -> dict:
    """_CMD_DESCRIPTIONS leido del fuente de cli.py (sin importarlo).

    Copiado de tests/test_harness_ayuda.py:37-46 a proposito: el dato REAL, sin
    arrastrar el import del monolito de 23.000 lineas a esta suite.
    """
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
    assert len(d) > 190, "el catalogo real deberia tener ~280 comandos"
    return d


@pytest.fixture(scope="module")
def fuente_cli() -> str:
    return (RAIZ / "cognia" / "cli.py").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _cache_limpio(monkeypatch):
    """El cache de nivel es global al modulo: sin esto, un test contamina al
    siguiente segun el orden de coleccion. Tambien se aisla la env var para no
    depender del ~/.cognia/config.env real del dueno."""
    # setenv antes de delenv a proposito: asi monkeypatch anota el estado
    # previo y, al deshacer, BORRA la clave que un test haya podido escribir en
    # os.environ (set_nivel_cmds escribe ahi de verdad).
    monkeypatch.setenv(vis.K_CMD_NIVEL, "")
    monkeypatch.delenv(vis.K_CMD_NIVEL, raising=False)
    vis.invalidar_cache()
    yield
    vis.invalidar_cache()


# ---------------------------------------------------------------------------
# 1. LA PARTICION
# ---------------------------------------------------------------------------

def test_los_tres_cubos_particionan_el_catalogo(catalogo):
    """Union == catalogo (mas PENDIENTES) y los tres disjuntos dos a dos."""
    n, a, l = vis.NUCLEO, vis.AVANZADO, vis.LABORATORIO

    assert not (n & a), f"en NUCLEO y AVANZADO a la vez: {sorted(n & a)}"
    assert not (n & l), f"en NUCLEO y LABORATORIO a la vez: {sorted(n & l)}"
    assert not (a & l), f"en AVANZADO y LABORATORIO a la vez: {sorted(a & l)}"

    cubos = n | a | l
    real = set(catalogo)

    sin_clasificar = real - cubos
    assert not sin_clasificar, (
        "comandos registrados en _CMD_DESCRIPTIONS que ningun cubo reclama "
        f"(clasificalos en cognia/cli_visibilidad.py): {sorted(sin_clasificar)}")

    fantasmas = cubos - real
    assert fantasmas <= vis.PENDIENTES, (
        "comandos clasificados que ya no existen en _CMD_DESCRIPTIONS "
        f"(borralos del cubo): {sorted(fantasmas - vis.PENDIENTES)}")

    # PENDIENTES es una lista de espera, no un cajon de sastre: cada clave que
    # esta ahi tiene que estar tambien en algun cubo.
    assert vis.PENDIENTES <= cubos
    assert "/avanzado" in vis.NUCLEO
    assert "/sesion-a-workflow" in vis.AVANZADO


# ---------------------------------------------------------------------------
# 2. EL TAMANO DEL NUCLEO
# ---------------------------------------------------------------------------

def test_nucleo_es_chico():
    """El punto entero del pedido: la portada por defecto tiene que caber en la
    cabeza de una persona. Con el tope alto tambien, porque un NUCLEO que se
    vacia (por un merge malo) romperia el CLI en silencio."""
    assert len(vis.NUCLEO) <= 85, f"NUCLEO se esta engordando: {len(vis.NUCLEO)}"
    assert len(vis.NUCLEO) >= 60, f"NUCLEO se quedo sin comandos: {len(vis.NUCLEO)}"


# ---------------------------------------------------------------------------
# 3. EL FILTRO
# ---------------------------------------------------------------------------

def test_visibles_en_sencillo_recorta_y_en_avanzado_no(catalogo):
    completo = vis.visibles(catalogo, avanzado=True)
    assert completo == catalogo

    corto = vis.visibles(catalogo, avanzado=False)
    assert len(corto) < len(completo)
    assert set(corto) <= vis.NUCLEO

    # el orden del catalogo original se conserva (la portada de /ayuda lo usa)
    orden_original = [k for k in catalogo if k in corto]
    assert list(corto) == orden_original

    # casos concretos que el dueno reconoce: lo de diario se queda, el
    # experimento se va, y las descripciones no se tocan.
    assert "/hacer" in corto and "/leer" in corto and "/memoria" in corto
    assert "/flujoteca" in corto and "/biblioteca" in corto
    assert "/kg-inferir" not in corto and "/multiverso" not in corto
    for k, v in corto.items():
        assert v == catalogo[k]

    assert vis.contar_ocultos(catalogo, avanzado=False) == len(catalogo) - len(corto)
    assert vis.contar_ocultos(catalogo, avanzado=True) == 0


# ---------------------------------------------------------------------------
# 4. OCULTAR NO ES DESACTIVAR
# ---------------------------------------------------------------------------

_MUESTRA_LABORATORIO = (
    "/dormir", "/olvido", "/kg-stats", "/multiverso", "/mesh_estado", "/vocabulario",
)


def test_ocultar_no_desactiva(fuente_cli):
    """Los comandos ocultos siguen teniendo su rama en el despachador.

    Se comprueba por regex sobre el TEXTO de cli.py (no importandolo): lo que
    se defiende es que nadie meta el filtro de visibilidad dentro del if/elif.
    """
    for cmd in _MUESTRA_LABORATORIO:
        assert vis.nivel(cmd) == "laboratorio", f"{cmd} deberia ser de laboratorio"
        rx = re.compile(
            r"raw\s*(?:==|\.startswith\()\s*\(?[\"']" + re.escape(cmd) + r"(?:[\"']|\s)")
        assert rx.search(fuente_cli), (
            f"{cmd} esta oculto pero ya no tiene rama en el despachador de "
            "cli.py: ocultar no es desactivar")


# ---------------------------------------------------------------------------
# 5. /avanzado REGISTRADO  (lo pone en verde F-CABLE, sobre cognia/cli.py)
# ---------------------------------------------------------------------------

@pytest.mark.xfail(strict=False, reason=(
    "F-CABLE registra '/avanzado' en _CMD_DESCRIPTIONS (cli.py) y lo "
    "categoriza en harness/ayuda.py; ese fichero es de otro agente. Este test "
    "pasa a xpass solo cuando aterrice."))
def test_avanzado_esta_registrado(catalogo):
    from cognia.harness import ayuda
    assert "/avanzado" in catalogo, "sin entrada en _CMD_DESCRIPTIONS no hay puerta"
    assert ayuda.clasificar("/avanzado", catalogo["/avanzado"]) != "Otros"


# ---------------------------------------------------------------------------
# 6. LA CLAVE SOBREVIVE AL REINICIO  (lo pone en verde F-REMOTO, user_prefs)
# ---------------------------------------------------------------------------

@pytest.mark.xfail(strict=False, reason=(
    "F-REMOTO da de alta K_CMD_NIVEL en cognia/user_prefs.py; ese fichero es "
    "de otro agente. Anticuerpo del bug vivo de COGNIA_UI_MODE: sin el alta, "
    "/avanzado funciona en la sesion y se olvida al reiniciar SIN ERROR."))
def test_cmd_nivel_esta_en_user_prefs(tmp_path, monkeypatch):
    from cognia import first_run, user_prefs

    assert getattr(user_prefs, "K_CMD_NIVEL", None) == vis.K_CMD_NIVEL

    # no basta con que la constante exista: load_prefs tiene que DEVOLVERLA
    monkeypatch.setattr(first_run, "_load_config",
                        lambda: {vis.K_CMD_NIVEL: "todo"}, raising=True)
    assert user_prefs.load_prefs().get(vis.K_CMD_NIVEL) == "todo"


# ---------------------------------------------------------------------------
# 7. NI UNA LECTURA DE DISCO POR PULSACION DE TECLA
# ---------------------------------------------------------------------------

def test_get_nivel_no_toca_disco_en_caliente(monkeypatch):
    from cognia import first_run

    llamadas = {"n": 0}

    def _contado():
        llamadas["n"] += 1
        return {}

    monkeypatch.setattr(first_run, "_load_config", _contado, raising=True)
    vis.invalidar_cache()

    for _ in range(500):
        assert vis.get_nivel_cmds() == "nucleo"
    assert llamadas["n"] <= 1, (
        f"get_nivel_cmds leyo la config {llamadas['n']} veces: el "
        "autocompletado corre en cada tecla y esto es lag al teclear")

    # es_avanzado consulta ademas simple_mode.is_simple(), que tambien va a
    # disco: tiene que estar cacheado por la misma razon.
    antes = llamadas["n"]
    for _ in range(500):
        vis.es_avanzado()
    assert llamadas["n"] - antes <= 1, (
        f"es_avanzado leyo la config {llamadas['n'] - antes} veces")

    # y el cache se puede tirar a mano (lo hacen /avanzado y /modo)
    vis.invalidar_cache()
    vis.get_nivel_cmds()
    assert llamadas["n"] > antes


# ---------------------------------------------------------------------------
# 8. EL CATALOGO COMPLETO SIGUE VIVO DONDE HACE FALTA
# ---------------------------------------------------------------------------

def test_mensaje_desconocido_usa_catalogo_completo(catalogo):
    """`/gaf` tiene que seguir sugiriendo `/grafo` en modo sencillo.

    Es la contrapartida de ocultar: el que teclea mal un comando de nicho
    merece la sugerencia. Por eso `mensaje_desconocido` recibe el catalogo
    COMPLETO y no el filtrado -- y aqui se ve la diferencia entre los dos.
    """
    from cognia.harness import ayuda

    assert vis.nivel("/grafo") == "avanzado"

    completo = ayuda.mensaje_desconocido(catalogo, "/gaf")
    assert "/grafo" in completo

    corto = vis.visibles(catalogo, avanzado=False)
    assert "/grafo" not in ayuda.mensaje_desconocido(corto, "/gaf"), (
        "si el catalogo filtrado llegase a mensaje_desconocido, el dueno "
        "perderia la sugerencia: por eso cli.py le pasa _CMD_DESCRIPTIONS")


# ---------------------------------------------------------------------------
# EXTRAS: el eje de nivel, que es codigo nuevo de este modulo
# ---------------------------------------------------------------------------

def test_nivel_de_un_comando_desconocido_es_laboratorio():
    """Nunca lanza: una excepcion aqui reventaria el autocompletado."""
    assert vis.nivel("/inventado-manana") == "laboratorio"
    assert vis.nivel("") == "laboratorio"
    assert vis.nivel(None) == "laboratorio"
    # las claves con subcomando propio ganan al recorte por la primera palabra
    assert vis.nivel("/agente estado") == "avanzado"
    assert vis.nivel("/distill run") == "laboratorio"
    assert vis.nivel("/leer README.md") == "nucleo"


def test_set_nivel_persiste_normaliza_e_invalida_el_cache(monkeypatch):
    from cognia import first_run

    escrito = {}
    monkeypatch.setattr(first_run, "set_config_value",
                        lambda k, v: escrito.__setitem__(k, v), raising=True)
    monkeypatch.setattr(first_run, "_load_config", lambda: {}, raising=True)

    assert vis.set_nivel_cmds("todo") == "todo"
    assert escrito[vis.K_CMD_NIVEL] == "todo"
    assert os.environ[vis.K_CMD_NIVEL] == "todo"
    assert vis.get_nivel_cmds() == "todo"          # sin reiniciar nada
    assert vis.es_avanzado() is True

    assert vis.set_nivel_cmds("cualquier-cosa") == "nucleo"   # default seguro
    assert vis.get_nivel_cmds() == "nucleo"
    assert vis.set_nivel_cmds("TODOS") == "todo"


def test_modo_avanzado_implica_todo_pero_sencillo_no_apaga(monkeypatch):
    """La implicacion va en UNA direccion. `/modo sencillo` no puede deshacer
    un `/avanzado on` explicito del dueno."""
    from cognia import first_run, simple_mode

    monkeypatch.setattr(first_run, "_load_config", lambda: {}, raising=True)

    monkeypatch.setattr(simple_mode, "is_simple", lambda override=None: False)
    vis.invalidar_cache()
    assert vis.es_avanzado() is True, "/modo avanzado tiene que revelar el catalogo"

    monkeypatch.setattr(simple_mode, "is_simple", lambda override=None: True)
    vis.invalidar_cache()
    assert vis.es_avanzado() is False
    assert vis.es_avanzado("todo") is True, "el nivel explicito manda sobre /modo"


# ---------------------------------------------------------------------------
# 9. /enrutador: clasificado en el MISMO cambio que lo registra (obra 4.14.0)
# ---------------------------------------------------------------------------
# El invariante de particion de arriba ya lo obliga, pero falla con un mensaje
# generico ("una clave descolgada"). Estos dos dicen QUE clave y POR QUE va
# donde va: NUCLEO esta en 82 de un tope de 85 y los tres huecos que quedan no
# se gastan en un comando de telemetria.

def test_enrutador_esta_registrado_y_clasificado(catalogo):
    assert "/enrutador" in catalogo, (
        "sin entrada en _CMD_DESCRIPTIONS el comando existe pero es INVISIBLE: "
        "no sale en /ayuda, no lo ofrece el autocompletado y el enrutador por "
        "inferencia no lo conoce (su catalogo se arma de este mismo dict)")
    assert "/enrutador" in vis.AVANZADO
    assert "/enrutador" not in vis.NUCLEO
    assert "/enrutador" not in vis.LABORATORIO


def test_enrutador_no_desborda_la_portada_de_ayuda(catalogo):
    """La portada clasifica POR TEXTO (harness/ayuda._REGLAS_DESC): una
    descripcion con la palabra "agente" mandaba /enrutador a "Agente y
    tareas", que esta a 25 de 25, y ponia rojo el guardian del tope. La
    descripcion evita esa palabra a proposito, y esto lo fija."""
    from cognia.harness import ayuda
    assert ayuda.desbordes(catalogo, ayuda.TOPE_CATEGORIA) == []
    assert ayuda.clasificar("/enrutador", catalogo["/enrutador"]) != "Otros"
