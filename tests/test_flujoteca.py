# -*- coding: utf-8 -*-
"""
tests/test_flujoteca.py
=======================
Tests de la biblioteca de flujos (cognia/agent/flujoteca.py).

Sin modelo y sin red: el modulo es puro disco + JSON, asi que se prueba
entero en seco. Lo unico que entra de fuera es `flows.validar`, que es
determinista.

REGLA CRITICA DE ESTE FICHERO: la flujoteca escribe en ~/.cognia/flujoteca
por defecto. La fixture `biblioteca` es AUTOUSE para que ningun test -- ni
uno que se anada manana y se olvide de pedirla -- pueda tocar la biblioteca
real del dueno.

OJO AL EDITAR: los casos de slugificar llevan tildes de verdad (el modulo
las quita, y sin ellas el test no probaria nada). Este fichero es UTF-8; una
reescritura en Latin-1 las convertiria en mojibake y el test seguiria verde
comprobando otra cosa. Si se toca, verificar los bytes, no la vista.
"""

import json

import pytest

from cognia.agent import flujoteca as F
from cognia.agent.flows import FlowError


# ---------------------------------------------------------------------------
# Aislamiento y utilidades
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def biblioteca(tmp_path, monkeypatch):
    """Redirige la biblioteca ENTERA a tmp_path. Autouse por seguridad."""
    d = tmp_path / "flujoteca"
    monkeypatch.setenv("COGNIA_FLUJOTECA_DIR", str(d))
    return d


class _Reloj:
    """Reloj monotono inyectable.

    `_ahora()` recorta a segundos, asi que dos guardados dentro del mismo
    segundo dan la MISMA marca y el orden de `listar()` quedaria a merced del
    desempate. Un test que depende de eso falla solo de vez en cuando, que es
    peor que no tenerlo.
    """

    def __init__(self):
        self.n = 0

    def __call__(self):
        self.n += 1
        return "2026-08-28T%02d:%02d:%02d" % (
            self.n // 3600, (self.n // 60) % 60, self.n % 60)


def flujo_lineal(nombre="Investigacion IA", n=2, args="paso"):
    """Flujo valido para flows.validar: ids unicos, tool en todos y wires
    encadenados sin ciclo.

    EL PRIMER NODO ES EL DE ENTRADA (`tool: "prompt"`), 2026-08-29. No es
    decorado: desde el PEDIDO 3, `flujoteca.guardar` llama a
    `flows.asegurar_prompt` y TODO flujo guardado sale con su nodo de
    entrada al inicio. Si este helper produjera flujos sin el, cada
    `guardar()` le anadiria uno y los conteos de `n_nodos` de medio fichero
    mirarian un flujo distinto del que se escribio. Dandoselo aqui, el
    helper describe el formato REAL de lo que hay en la biblioteca y los
    conteos siguen significando lo que decian."""
    return {
        "nombre": nombre,
        "nodos": [
            {"id": "n%d" % i, "tool": ("prompt" if i == 0 else "responder"),
             "args": "%s %d" % (args, i),
             "wires": (["n%d" % (i + 1)] if i < n - 1 else [])}
            for i in range(n)
        ],
    }


def flujo_con_ciclo(nombre="Con Ciclo"):
    return {
        "nombre": nombre,
        "nodos": [
            {"id": "a", "tool": "responder", "args": "", "wires": ["b"]},
            {"id": "b", "tool": "responder", "args": "", "wires": ["a"]},
        ],
    }


# ---------------------------------------------------------------------------
# 1. guardar()
# ---------------------------------------------------------------------------

def test_guardar_crea_versiones_incrementales(biblioteca):
    for i in (1, 2, 3):
        meta = F.guardar(flujo_lineal(n=i), nombre="Investigacion IA",
                         nota="version %d" % i)
        assert meta["version_actual"] == i

    d = biblioteca / "investigacion_ia"
    assert (d / "meta.json").is_file()
    for i in (1, 2, 3):
        assert (d / ("v%d.json" % i)).is_file()

    hist = F.versiones("Investigacion IA")
    assert [e["v"] for e in hist] == [3, 2, 1]          # mas nueva primero
    assert [e["n_nodos"] for e in hist] == [3, 2, 1]
    assert [e["actual"] for e in hist] == [True, False, False]
    assert hist[0]["nota"] == "version 3"


def test_guardar_sin_nombre_lanza(biblioteca):
    flujo = flujo_lineal()
    flujo.pop("nombre")
    with pytest.raises(F.FlujotecaError):
        F.guardar(flujo)
    with pytest.raises(F.FlujotecaError):
        F.guardar(flujo, nombre="   ")
    with pytest.raises(F.FlujotecaError):
        F.guardar("no soy un dict", nombre="x")
    assert F.listar() == []                             # nada se escribio


def test_guardar_nombre_manda_sobre_el_del_flujo(biblioteca):
    F.guardar(flujo_lineal(nombre="el del dict"), nombre="El Que Manda")
    assert F.existe("El Que Manda")
    assert not F.existe("el del dict")
    assert F.cargar("El Que Manda")["nombre"] == "El Que Manda"


def test_guardar_ciclo_no_escribe_nada(biblioteca):
    with pytest.raises(FlowError):
        F.guardar(flujo_con_ciclo(), nombre="Con Ciclo")
    # ni el directorio del flujo ni la raiz quedan a medias
    assert not (biblioteca / "con_ciclo").exists()
    assert F.listar() == []
    assert not F.existe("Con Ciclo")


def test_guardar_invalido_no_toca_el_flujo_existente(biblioteca):
    F.guardar(flujo_lineal(nombre="Mio", n=2), nombre="Mio")
    with pytest.raises(FlowError):
        F.guardar(flujo_con_ciclo(nombre="Mio"), nombre="Mio")
    d = biblioteca / "mio"
    assert not (d / "v2.json").exists()                 # sin version a medias
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    assert meta["version_actual"] == 1
    assert len(meta["versiones"]) == 1
    assert F.cargar("Mio")["nodos"][0]["id"] == "n0"


def test_validar_false_deja_pasar_un_flujo_invalido(biblioteca):
    roto = {"nombre": "Roto", "nodos": []}
    with pytest.raises(FlowError):
        F.guardar(roto, nombre="Roto")                  # con validacion, fuera
    meta = F.guardar(roto, nombre="Roto", validar=False)
    assert meta["version_actual"] == 1
    assert F.cargar("Roto")["nodos"] == []


def test_guardar_recorta_la_nota_a_200(biblioteca):
    F.guardar(flujo_lineal(), nombre="Notas", nota="x" * 500)
    assert len(F.versiones("Notas")[0]["nota"]) == 200


def test_descripcion_se_guarda_y_se_actualiza(biblioteca):
    F.guardar(flujo_lineal(), nombre="Desc", descripcion="la primera")
    assert F.descripcion("Desc") == "la primera"
    F.guardar(flujo_lineal(), nombre="Desc")            # sin desc: se conserva
    assert F.descripcion("Desc") == "la primera"
    F.guardar(flujo_lineal(), nombre="Desc", descripcion="la segunda")
    assert F.descripcion("Desc") == "la segunda"


# ---------------------------------------------------------------------------
# 2. slugificar()
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("crudo, esperado", [
    ("Investigación IA", "investigacion_ia"),
    ("Año Nuevo", "ano_nuevo"),
    ("Niño Pingüino", "nino_pinguino"),
    ("ÁÉÍÓÚ", "aeiou"),
    ("  hola---mundo!!!  ", "hola_mundo"),
    ("a/b\\c:d", "a_b_c_d"),
    ("", "flujo"),
    ("   ", "flujo"),
    ("!!!", "flujo"),
    (None, "flujo"),
])
def test_slugificar(crudo, esperado):
    assert F.slugificar(crudo) == esperado


def test_slugificar_recorta_a_60():
    assert F.slugificar("x" * 200) == "x" * 60


def test_dos_nombres_que_slugifican_igual_son_el_mismo_flujo(biblioteca):
    """Comportamiento DELIBERADO, documentado en el docstring de slugificar:
    quien escribe el nombre con otra caja o con tilde quiere el mismo flujo,
    no un duplicado silencioso."""
    F.guardar(flujo_lineal(n=2), nombre="Investigación IA")
    F.guardar(flujo_lineal(n=3), nombre="investigacion ia")

    assert len(F.listar()) == 1                         # un solo flujo
    hist = F.versiones("Investigacion IA")
    assert [e["v"] for e in hist] == [2, 1]
    # y la v2 (la actual) es la que guardo el segundo nombre
    assert len(F.cargar("investigación IA")["nodos"]) == 3


# ---------------------------------------------------------------------------
# 3. listar() y cargar()
# ---------------------------------------------------------------------------

def test_listar_biblioteca_inexistente_es_lista_vacia(biblioteca):
    assert not biblioteca.exists()
    assert F.listar() == []                             # no lanza


def test_listar_ignora_basura_en_la_raiz(biblioteca):
    F.guardar(flujo_lineal(), nombre="Bueno")
    biblioteca.joinpath("suelto.txt").write_text("hola", encoding="utf-8")
    biblioteca.joinpath("sin_meta").mkdir()
    biblioteca.joinpath("meta_roto").mkdir()
    biblioteca.joinpath("meta_roto", "meta.json").write_text(
        "{no soy json", encoding="utf-8")
    assert [f["nombre"] for f in F.listar()] == ["Bueno"]


def test_listar_ordena_por_modificacion(biblioteca, monkeypatch):
    monkeypatch.setattr(F, "_ahora", _Reloj())
    F.guardar(flujo_lineal(), nombre="Primero")
    F.guardar(flujo_lineal(), nombre="Segundo")
    assert [f["nombre"] for f in F.listar()] == ["Segundo", "Primero"]

    F.guardar(flujo_lineal(n=4), nombre="Primero")      # vuelve a ser el nuevo
    filas = F.listar()
    assert [f["nombre"] for f in filas] == ["Primero", "Segundo"]
    assert filas[0]["version_actual"] == 2
    assert filas[0]["n_versiones"] == 2
    assert filas[0]["n_nodos"] == 4
    assert filas[0]["slug"] == "primero"
    assert filas[0]["ruta"] == str(biblioteca / "primero")


def test_cargar_version_concreta_y_actual(biblioteca):
    F.guardar(flujo_lineal(n=2), nombre="Hist")
    F.guardar(flujo_lineal(n=5), nombre="Hist")
    assert len(F.cargar("Hist")["nodos"]) == 5
    assert len(F.cargar("Hist", 1)["nodos"]) == 2
    assert len(F.cargar("Hist", 2)["nodos"]) == 5


def test_cargar_version_inexistente_dice_que_versiones_hay(biblioteca):
    F.guardar(flujo_lineal(), nombre="Hist")
    F.guardar(flujo_lineal(), nombre="Hist")
    with pytest.raises(F.FlujotecaError) as exc:
        F.cargar("Hist", 7)
    msg = str(exc.value)
    assert "7" in msg
    assert "v1" in msg and "v2" in msg                  # el mensaje ORIENTA


def test_el_mensaje_no_ofrece_versiones_borradas(biblioteca):
    """Regresion (bug encontrado por este test): el 'hay: ...' salia del
    historial, que conserva a proposito las entradas borradas. Pedir la v2
    despues de borrarla contestaba "no tiene version 2 (hay: v1, v2, v3)" y
    mandaba a quien lo leyera a pedir otra vez la que no esta."""
    _flujo_de_tres("Hueco")
    assert F.borrar_version("Hueco", 2, quien="usuario")["ok"] is True
    with pytest.raises(F.FlujotecaError) as exc:
        F.cargar("Hueco", 2)
    msg = str(exc.value)
    assert "hay: v1, v3" in msg
    assert "v2," not in msg                             # no se ofrece la borrada


def test_cargar_flujo_inexistente_lanza(biblioteca):
    with pytest.raises(F.FlujotecaError) as exc:
        F.cargar("no existe")
    assert "no existe" in str(exc.value)


def test_versiones_de_flujo_inexistente_es_lista_vacia(biblioteca):
    assert F.versiones("fantasma") == []
    assert F.descripcion("fantasma") == ""
    assert F.existe("fantasma") is False


# ---------------------------------------------------------------------------
# 4. restaurar() -- la propiedad central del modulo
# ---------------------------------------------------------------------------

def test_restaurar_crea_version_nueva_y_no_borra_nada(biblioteca):
    F.guardar(flujo_lineal(n=1, args="uno"), nombre="Obra")
    F.guardar(flujo_lineal(n=2, args="dos"), nombre="Obra")
    F.guardar(flujo_lineal(n=3, args="tres"), nombre="Obra")

    meta = F.restaurar("Obra", 2)

    # la restauracion es un guardado mas: v4 con el contenido de la v2
    assert meta["version_actual"] == 4
    assert F.cargar("Obra", 4) == F.cargar("Obra", 2)
    assert F.cargar("Obra")["nodos"][0]["args"] == "dos 0"

    # el historial CRECE y ninguna version anterior desaparece
    hist = F.versiones("Obra")
    assert [e["v"] for e in hist] == [4, 3, 2, 1]
    assert all(e["existe"] for e in hist)
    d = biblioteca / "obra"
    assert sorted(p.name for p in d.glob("v*.json")) == [
        "v1.json", "v2.json", "v3.json", "v4.json"]
    # la v3 (la que se "deshizo") sigue intacta y accesible
    assert F.cargar("Obra", 3)["nodos"][0]["args"] == "tres 0"
    assert hist[0]["nota"] == "restaurada la v2"


def test_restaurar_dos_veces_sigue_sin_truncar(biblioteca):
    F.guardar(flujo_lineal(n=1), nombre="Obra")
    F.guardar(flujo_lineal(n=2), nombre="Obra")
    F.restaurar("Obra", 1)                              # -> v3
    F.restaurar("Obra", 2, nota="me arrepenti")         # -> v4
    assert [e["v"] for e in F.versiones("Obra")] == [4, 3, 2, 1]
    assert len(F.cargar("Obra")["nodos"]) == 2
    assert F.versiones("Obra")[0]["nota"] == "me arrepenti"


def test_restaurar_version_inexistente_lanza(biblioteca):
    F.guardar(flujo_lineal(), nombre="Obra")
    with pytest.raises(F.FlujotecaError):
        F.restaurar("Obra", 9)
    assert [e["v"] for e in F.versiones("Obra")] == [1]


# ---------------------------------------------------------------------------
# 5. comparar()
# ---------------------------------------------------------------------------

def test_comparar_anadidos_quitados_y_cambiados(biblioteca):
    # el nodo de entrada va EXPLICITO en los dos: `guardar` se lo pondria
    # igual (asegurar_prompt), y ponerlo aqui deja ver que es identico en las
    # dos versiones -- por eso sale en `iguales` y no en el diff
    v1 = {"nombre": "Diff", "nodos": [
        {"id": "p", "tool": "prompt", "args": "", "wires": ["a"]},
        {"id": "a", "tool": "responder", "args": "hola", "wires": ["b"]},
        {"id": "b", "tool": "leer_archivo", "args": "x.txt", "wires": []},
    ]}
    v2 = {"nombre": "Diff", "nodos": [
        {"id": "p", "tool": "prompt", "args": "", "wires": ["a"]},
        {"id": "a", "tool": "buscar_web", "args": "hola", "wires": ["c"],
         "reintentos": 2},
        {"id": "c", "tool": "responder", "args": "nuevo", "wires": []},
    ]}
    F.guardar(v1, nombre="Diff")
    F.guardar(v2, nombre="Diff")

    d = F.comparar("Diff", 1, 2)
    assert d["v1"] == 1 and d["v2"] == 2
    assert [n["id"] for n in d["anadidos"]] == ["c"]
    assert [n["id"] for n in d["quitados"]] == ["b"]
    assert [c["id"] for c in d["cambiados"]] == ["a"]
    campos = {c["campo"]: (c["antes"], c["despues"])
              for c in d["cambiados"][0]["campos"]}
    assert campos["tool"] == ("responder", "buscar_web")
    assert campos["wires"] == (["b"], ["c"])
    assert campos["reintentos"] == (None, 2)
    assert "args" not in campos                         # 'hola' no cambio
    assert d["iguales"] == ["p"]        # el nodo de entrada, intacto
    assert d["sin_cambios"] is False


def test_comparar_reordenar_nodos_no_es_un_cambio(biblioteca):
    """El motivo entero de comparar por id y no por texto: el orden de la
    lista no significa nada, lo dice el grafo."""
    base = flujo_lineal(nombre="Orden", n=3)
    revuelto = dict(base)
    revuelto["nodos"] = list(reversed(base["nodos"]))
    F.guardar(base, nombre="Orden")
    F.guardar(revuelto, nombre="Orden")

    d = F.comparar("Orden", 1, 2)
    assert d["sin_cambios"] is True
    assert d["anadidos"] == [] and d["quitados"] == [] and d["cambiados"] == []
    assert d["iguales"] == ["n0", "n1", "n2"]


def test_comparar_una_version_consigo_misma(biblioteca):
    F.guardar(flujo_lineal(n=3), nombre="Igual")
    assert F.comparar("Igual", 1, 1)["sin_cambios"] is True


# ---------------------------------------------------------------------------
# 6. borrar_version(): la matriz politica x quien
# ---------------------------------------------------------------------------

def _flujo_de_tres(nombre="Matriz"):
    for i in (1, 2, 3):
        F.guardar(flujo_lineal(n=i), nombre=nombre)


@pytest.mark.parametrize("politica, esperado, trozo_motivo", [
    ("nunca", False, "nunca"),
    ("preguntar", False, "confirme"),
    ("inventada", False, "desconocida"),
    ("", False, "nunca"),
    ("permitido", True, "borrada"),
    ("PERMITIDO", True, "borrada"),                     # se normaliza
])
def test_borrar_version_matriz_ia(biblioteca, politica, esperado, trozo_motivo):
    _flujo_de_tres()
    r = F.borrar_version("Matriz", 1, quien="ia", politica=politica)
    assert r["ok"] is esperado
    assert trozo_motivo in r["motivo"]
    assert (biblioteca / "matriz" / "v1.json").exists() is not esperado


@pytest.mark.parametrize("politica", ["nunca", "preguntar", "permitido",
                                      "inventada"])
def test_el_usuario_borra_con_cualquier_politica(biblioteca, politica):
    _flujo_de_tres()
    r = F.borrar_version("Matriz", 1, quien="usuario", politica=politica)
    assert r["ok"] is True
    assert not (biblioteca / "matriz" / "v1.json").exists()


@pytest.mark.parametrize("quien", ["usuario", "ia"])
def test_la_version_actual_no_se_borra_nunca(biblioteca, quien):
    _flujo_de_tres()
    r = F.borrar_version("Matriz", 3, quien=quien, politica="permitido")
    assert r["ok"] is False
    assert "ACTUAL" in r["motivo"]
    assert (biblioteca / "matriz" / "v3.json").exists()


def test_borrar_version_inexistente_o_flujo_inexistente(biblioteca):
    _flujo_de_tres()
    r = F.borrar_version("Matriz", 9, quien="usuario")
    assert r["ok"] is False and "no tiene version 9" in r["motivo"]
    r = F.borrar_version("fantasma", 1, quien="usuario")
    assert r["ok"] is False and "fantasma" in r["motivo"]


def test_borrar_flujo_entero_respeta_la_politica(biblioteca):
    _flujo_de_tres()
    assert F.borrar("Matriz", quien="ia")["ok"] is False
    assert F.existe("Matriz")
    assert F.borrar("Matriz", quien="ia", politica="permitido")["ok"] is True
    assert not F.existe("Matriz")
    assert F.listar() == []
    assert F.borrar("Matriz", quien="usuario")["ok"] is False


# ---------------------------------------------------------------------------
# 7. El historial no puede mentir
# ---------------------------------------------------------------------------

def test_version_borrada_sigue_en_el_historial(biblioteca):
    _flujo_de_tres()
    assert F.borrar_version("Matriz", 2, quien="usuario")["ok"] is True

    hist = F.versiones("Matriz")
    assert [e["v"] for e in hist] == [3, 2, 1]          # la v2 NO desaparece
    fila = [e for e in hist if e["v"] == 2][0]
    assert fila["borrada"] is True
    assert fila["existe"] is False
    assert fila["borrada_por"] == "usuario"
    assert fila["borrada_ts"]
    # las otras siguen sanas y sin marca
    assert all(e["existe"] for e in hist if e["v"] != 2)
    assert all("borrada" not in e for e in hist if e["v"] != 2)
    # la numeracion sigue desde la actual, no reusa el hueco
    assert F.guardar(flujo_lineal(), nombre="Matriz")["version_actual"] == 4
    with pytest.raises(F.FlujotecaError):
        F.cargar("Matriz", 2)                           # el cuerpo si se fue


# ---------------------------------------------------------------------------
# 8. renombrar()
# ---------------------------------------------------------------------------

def test_renombrar_mueve_el_directorio_y_actualiza_los_nombres(biblioteca):
    F.guardar(flujo_lineal(n=1), nombre="Nombre Viejo", descripcion="la desc")
    F.guardar(flujo_lineal(n=2), nombre="Nombre Viejo")

    r = F.renombrar("Nombre Viejo", "Nombre Nuevo")
    assert r["ok"] is True

    assert not (biblioteca / "nombre_viejo").exists()
    assert (biblioteca / "nombre_nuevo" / "meta.json").is_file()
    assert F.existe("Nombre Nuevo") and not F.existe("Nombre Viejo")

    meta = json.loads(
        (biblioteca / "nombre_nuevo" / "meta.json").read_text(encoding="utf-8"))
    assert meta["nombre"] == "Nombre Nuevo"
    assert meta["slug"] == "nombre_nuevo"
    assert meta["version_actual"] == 2
    assert len(meta["versiones"]) == 2                  # historial conservado
    assert F.descripcion("Nombre Nuevo") == "la desc"

    # el nombre vive TAMBIEN dentro de cada version (flows.py lo lee de ahi)
    for v in (1, 2):
        assert F.cargar("Nombre Nuevo", v)["nombre"] == "Nombre Nuevo"
    assert [f["nombre"] for f in F.listar()] == ["Nombre Nuevo"]


def test_renombrar_a_nombre_ocupado_falla(biblioteca):
    F.guardar(flujo_lineal(), nombre="Uno")
    F.guardar(flujo_lineal(), nombre="Dos")
    r = F.renombrar("Uno", "Dos")
    assert r["ok"] is False and "ya hay un flujo" in r["motivo"]
    assert F.existe("Uno") and F.existe("Dos")


def test_renombrar_inexistente_o_a_vacio_falla(biblioteca):
    r = F.renombrar("fantasma", "otro")
    assert r["ok"] is False and "fantasma" in r["motivo"]
    F.guardar(flujo_lineal(), nombre="Real")
    r = F.renombrar("Real", "   ")
    assert r["ok"] is False and "vacio" in r["motivo"]
    assert F.existe("Real")


def test_renombrar_dentro_del_mismo_slug(biblioteca):
    """Cambiar solo la caja no mueve nada, pero si actualiza el nombre
    visible: el directorio es el mismo por diseno."""
    F.guardar(flujo_lineal(), nombre="mi flujo")
    assert F.renombrar("mi flujo", "Mi Flujo")["ok"] is True
    assert [f["nombre"] for f in F.listar()] == ["Mi Flujo"]
    assert F.cargar("Mi Flujo")["nombre"] == "Mi Flujo"


# ---------------------------------------------------------------------------
# 9. duplicar()
# ---------------------------------------------------------------------------

def test_duplicar_copia_solo_la_actual_y_empieza_en_v1(biblioteca):
    F.guardar(flujo_lineal(n=1), nombre="Original", descripcion="una desc")
    F.guardar(flujo_lineal(n=2), nombre="Original")
    F.guardar(flujo_lineal(n=3), nombre="Original")

    assert F.duplicar("Original", "Copia")["ok"] is True

    hist = F.versiones("Copia")
    assert [e["v"] for e in hist] == [1]                # el duplicado nace v1
    assert hist[0]["n_nodos"] == 3
    assert "Original" in hist[0]["nota"] and "v3" in hist[0]["nota"]
    copia = F.cargar("Copia")
    assert copia["nodos"] == F.cargar("Original", 3)["nodos"]
    assert copia["nombre"] == "Copia"
    assert F.descripcion("Copia") == "una desc"
    # el original queda intacto
    assert [e["v"] for e in F.versiones("Original")] == [3, 2, 1]


def test_duplicar_a_nombre_ocupado_o_desde_inexistente_falla(biblioteca):
    F.guardar(flujo_lineal(), nombre="Original")
    F.guardar(flujo_lineal(), nombre="Ocupado")
    r = F.duplicar("Original", "Ocupado")
    assert r["ok"] is False and "ya hay un flujo" in r["motivo"]
    assert [e["v"] for e in F.versiones("Ocupado")] == [1]
    r = F.duplicar("fantasma", "Nuevo")
    assert r["ok"] is False and "fantasma" in r["motivo"]
    assert not F.existe("Nuevo")


# ---------------------------------------------------------------------------
# 10. describir()
# ---------------------------------------------------------------------------

def test_describir_en_orden_topologico_y_marca_el_fin():
    # rombo: a -> b, c -> d. La LISTA va al reves a proposito para que el
    # test solo pase si de verdad ordena por el grafo.
    flujo = {"nombre": "Rombo", "nodos": [
        {"id": "d", "tool": "responder", "args": "cierra", "wires": []},
        {"id": "c", "tool": "leer_archivo", "args": "y.txt", "wires": ["d"]},
        {"id": "b", "tool": "buscar_web", "args": "x", "wires": ["d"],
         "reintentos": 2, "modelo": "qwen"},
        {"id": "a", "tool": "responder", "args": "arranca",
         "wires": ["b", "c"], "saltar_si": "ERROR"},
    ]}
    lineas = F.describir(flujo).splitlines()

    assert lineas[0] == "Flujo: Rombo"
    ids = [ln.strip().split(":")[0] for ln in lineas[1:]]
    assert ids[0] == "a" and ids[-1] == "d"
    assert ids.index("b") < ids.index("d")
    assert ids.index("c") < ids.index("d")

    por_id = {ln.strip().split(":")[0]: ln for ln in lineas[1:]}
    assert por_id["d"].endswith("(fin)")                # el unico sin salida
    assert "(fin)" not in por_id["a"]
    assert "-> b, c" in por_id["a"]
    assert "args=arranca" in por_id["a"]
    assert "saltar_si=ERROR" in por_id["a"]
    assert "reintentos=2" in por_id["b"]
    assert "modelo=qwen" in por_id["b"]


def test_describir_flujo_vacio_e_invalido():
    assert F.describir({"nombre": "x", "nodos": []}) == "(flujo vacio)"
    assert F.describir({}) == "(flujo vacio)"
    # con ciclo no hay orden topologico: cae al orden de la lista sin explotar
    texto = F.describir(flujo_con_ciclo())
    assert "a:" in texto and "b:" in texto


# ---------------------------------------------------------------------------
# 11. Escritura atomica y raiz configurable
# ---------------------------------------------------------------------------

def test_no_quedan_tmp_tras_las_operaciones(biblioteca):
    F.guardar(flujo_lineal(n=1), nombre="Atomico")
    F.guardar(flujo_lineal(n=2), nombre="Atomico")
    F.restaurar("Atomico", 1)
    F.borrar_version("Atomico", 1, quien="usuario")
    F.duplicar("Atomico", "Atomico Copia")
    F.renombrar("Atomico Copia", "Atomico Otro")

    assert list(biblioteca.rglob("*.tmp")) == []
    for p in biblioteca.rglob("*.json"):                # y todo es JSON sano
        json.loads(p.read_text(encoding="utf-8"))


def test_la_biblioteca_vive_donde_dice_la_env(biblioteca, monkeypatch, tmp_path):
    assert F.dir_base() == biblioteca
    otra = tmp_path / "otra"
    monkeypatch.setenv("COGNIA_FLUJOTECA_DIR", str(otra))
    F.guardar(flujo_lineal(), nombre="Aqui")
    assert (otra / "aqui" / "v1.json").is_file()
    assert not biblioteca.exists()


# ---------------------------------------------------------------------------
# 12. tool_existe opcional en guardar()
# ---------------------------------------------------------------------------

def test_guardar_con_tool_existe_rechaza_tool_inventada(biblioteca):
    """El editor visual pasa el registro real: una tool que no existe se caza
    al GUARDAR, no al ejecutar tres dias despues."""
    flujo = flujo_lineal(n=2)
    flujo["nodos"][-1]["tool"] = "descargar_pdf"

    with pytest.raises(FlowError) as exc:
        F.guardar(flujo, nombre="Inventada",
                  tool_existe=lambda n: n in {"responder", "buscar", "prompt"})

    assert "descargar_pdf" in str(exc.value)
    assert not F.existe("Inventada"), "no se escribio nada"
    assert list(biblioteca.rglob("*.json")) == []


def test_guardar_sin_tool_existe_acepta_cualquier_tool(biblioteca):
    """El default TIENE que seguir siendo permisivo: hay flujos legitimos con
    tools de una familia opt-in apagada en este proceso, y convertir eso en
    un error dejaria al dueno sin poder guardar lo que ya tenia."""
    flujo = flujo_lineal(n=2)
    flujo["nodos"][-1]["tool"] = "tool_que_no_existe_en_ningun_registro"

    meta = F.guardar(flujo, nombre="Permisiva")

    assert meta["version_actual"] == 1
    assert F.cargar("Permisiva")["nodos"][-1]["tool"] == \
        "tool_que_no_existe_en_ningun_registro"


def test_guardar_con_tool_existe_deja_pasar_las_que_si_existen(biblioteca):
    meta = F.guardar(flujo_lineal(n=2), nombre="Buenas",
                     tool_existe=lambda n: n in ("responder", "prompt"))
    assert meta["version_actual"] == 1


# ---------------------------------------------------------------------------
# 13. El estado del editor: meta['ui']
# ---------------------------------------------------------------------------

def test_guardar_ui_no_crea_version(biblioteca):
    """Arrastrar un nodo NO es editar el flujo. Si cada arrastre creara una
    version, el historial (que existe para poder volver a un flujo anterior)
    quedaria enterrado bajo cientos de entradas que no cambian nada."""
    F.guardar(flujo_lineal(n=2), nombre="Con Posiciones", nota="inicial")
    antes = F.versiones("Con Posiciones")

    for i in range(20):
        F.guardar_ui("Con Posiciones",
                     {"pos": {"n0": {"x": 100 + i, "y": 40}}})

    assert F.versiones("Con Posiciones") == antes
    assert len(list((biblioteca / "con_posiciones").glob("v*.json"))) == 1
    assert F.leer_ui("Con Posiciones")["pos"]["n0"] == {"x": 119, "y": 40}


def test_guardar_ui_no_toca_la_fecha_de_modificacion(biblioteca):
    """`listar()` ordena por 'modificado'. Si mover un nodo tocara esa fecha,
    el flujo que solo se MIRO saltaria por encima del que se edito."""
    F.guardar(flujo_lineal(n=1), nombre="Quieto")
    modificado = json.loads(
        (biblioteca / "quieto" / "meta.json").read_text(encoding="utf-8")
    )["modificado"]

    F.guardar_ui("Quieto", {"pos": {"n0": {"x": 9, "y": 9}}})

    meta = json.loads(
        (biblioteca / "quieto" / "meta.json").read_text(encoding="utf-8"))
    assert meta["modificado"] == modificado
    assert meta["version_actual"] == 1


def test_las_posiciones_no_salen_en_comparar(biblioteca):
    """comparar() mira el FLUJO; el ui no es el flujo."""
    F.guardar(flujo_lineal(n=2), nombre="Comparada")
    F.guardar_ui("Comparada", {"pos": {"n0": {"x": 500, "y": 500}}})
    F.guardar(flujo_lineal(n=2), nombre="Comparada")

    assert F.comparar("Comparada", 1, 2)["sin_cambios"] is True


def test_leer_ui_flujo_sin_ui_devuelve_vacio(biblioteca):
    """Todos los flujos de antes del editor no tienen 'ui', y ese es el caso
    normal: tiene respuesta buena (el layout topologico), no es un error."""
    F.guardar(flujo_lineal(), nombre="Sin Ui")

    assert F.leer_ui("Sin Ui") == {}
    assert F.leer_ui("este flujo no existe") == {}      # tampoco lanza


def test_guardar_ui_en_flujo_inexistente_lanza(biblioteca):
    """Aqui SI hay que lanzar: quien escribe quiere saber que no se guardo."""
    with pytest.raises(F.FlujotecaError):
        F.guardar_ui("fantasma", {"pos": {}})
    assert F.listar() == []


def test_guardar_ui_fusiona_las_claves_de_primer_nivel(biblioteca):
    """Guardar solo las posiciones no puede borrar el zoom que guardo otra
    pantalla; pero dentro de 'pos' se reemplaza entero, o las posiciones de
    los nodos borrados se quedarian ahi para siempre."""
    F.guardar(flujo_lineal(n=2), nombre="Fusion")
    F.guardar_ui("Fusion", {"pos": {"n0": {"x": 1, "y": 2},
                                    "viejo": {"x": 9, "y": 9}},
                            "zoom": 1.5})

    ui = F.guardar_ui("Fusion", {"pos": {"n0": {"x": 3, "y": 4}}})

    assert ui["zoom"] == 1.5
    assert ui["pos"] == {"n0": {"x": 3, "y": 4}}
    assert F.leer_ui("Fusion") == ui


def test_guardar_ui_sanea_lo_que_llega_del_navegador(biblioteca):
    """Lo que entra por HTTP no es de fiar ni en localhost: una x de tipo
    lista rompe la vista al LEERLA, mucho despues de escribirla."""
    F.guardar(flujo_lineal(n=1), nombre="Sucia")

    ui = F.guardar_ui("Sucia", {"pos": {
        "n0": {"x": "120.7", "y": 40.2},        # texto y float -> enteros
        "n1": {"x": [1], "y": 3},               # basura -> fuera
        "n2": {"x": 5},                         # a medias -> fuera
        "n3": "no soy un dict",                 # ni eso -> fuera
    }})

    assert ui["pos"] == {"n0": {"x": 121, "y": 40}}
    assert F.leer_ui("Sucia")["pos"] == {"n0": {"x": 121, "y": 40}}


def test_guardar_ui_rechaza_lo_que_no_es_dict_o_no_es_json(biblioteca):
    F.guardar(flujo_lineal(n=1), nombre="Rara")
    with pytest.raises(F.FlujotecaError):
        F.guardar_ui("Rara", "no soy un dict")
    with pytest.raises(F.FlujotecaError):
        F.guardar_ui("Rara", {"raro": {1, 2, 3}})       # set: no es JSON
    assert F.leer_ui("Rara") == {}


def test_guardar_ui_es_atomico_y_no_deja_tmp(biblioteca):
    F.guardar(flujo_lineal(n=1), nombre="Atomica Ui")
    F.guardar_ui("Atomica Ui", {"pos": {"n0": {"x": 1, "y": 2}}})

    assert list(biblioteca.rglob("*.tmp")) == []
    for p in biblioteca.rglob("*.json"):
        json.loads(p.read_text(encoding="utf-8"))
