# -*- coding: utf-8 -*-
"""Gate de la paleta del editor de flujos (cognia/agent/catalogo_nodos.py).

QUE VIGILA, Y POR QUE ESTE FICHERO EXISTE
-----------------------------------------
La paleta es una TABLA A MANO cruzada con un registro que cambia solo: cada
tool nueva del repo entra en `tools.TOOLS` sin pasar por aqui. El modo de
fallo no es una excepcion, es el silencio -- la tool aparece en el cajon
"Otros" (o peor, la tabla nombra una tool que ya no existe) y nadie se
entera hasta que el dueno no la encuentra en el editor. Los dos guardianes
que impiden eso son `test_ninguna_tool_registrada_cae_en_otros` y
`test_la_tabla_no_nombra_tools_inventadas`.

LO QUE ESTOS TESTS NO HACEN EN ESTE PROCESO, A PROPOSITO
--------------------------------------------------------
1. NO activan familias AQUI. `familias.activar()` pone la variable de entorno
   y carga modulos en el registro GLOBAL: dejaria el proceso de pytest con
   134 tools registradas y reventaria a los tests que cuentan el catalogo por
   defecto (tests/test_catalogo_flags_off.py es literalmente eso). En este
   proceso las familias opt-in se comprueban por la via estatica
   (`flag_de_optin`); el barrido que SI las enciende todas corre en un
   SUBPROCESO limpio (`test_ninguna_tool_registrable_en_caliente_cae_en_otros`).
2. NO fijan el numero de tools ni el de categorias. Un test que diga "70"
   se rompe con cada tool nueva sin haber cazado nada.

EL AGUJERO QUE ESTO TENIA, Y COMO SE TAPO (2026-08-29)
------------------------------------------------------
`test_ninguna_tool_registrada_cae_en_otros` mira `tools.TOOLS` TAL COMO ESTE
en este proceso, y en un pytest en frio eso son las tools de importacion. Una
tool que se registra EN CALIENTE es invisible para el: `mensaje_bot` la mete
`tools.sincronizar_mensaje_bot()` cuando hay bot activo, y `cli._run_agent_task`
la llama al arrancar cada corrida. El resultado fue un test que pasaba en
aislado y solo caia con `tests/test_bots_ejecutor.py` delante (que deja un bot
activo), y un dueno que tras `/bots chat <bot>` veia un cajon gris "Otros" con
`mensaje_bot` suelto. El anticuerpo es el test del subproceso: registra el
mismo TODO lo registrable -- todo `sincronizar_*`, TODA familia de
`familias.FAMILIAS`, y los registradores sin familia -- y exige 0 huerfanas.
Es INDEPENDIENTE del orden de la suite en las dos direcciones: no depende de
que otro test haya encendido nada, y no ensucia el registro de este proceso.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys

import pytest

from cognia.agent import catalogo_nodos as cn
from cognia.agent import tools as tools_mod


_RX_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _todas() -> list:
    return sorted(tools_mod.TOOLS)


def _patrones_de(cat: dict) -> list:
    """[(patron, es_prefijo)] declarados por una categoria."""
    fuera = [(t, False) for t in cat.get("tools") or ()]
    fuera += [(p, True) for p in cat.get("prefijos") or ()]
    return fuera


def _es_optin(patron: str, es_prefijo: bool) -> bool:
    """Un patron es opt-in si su flag existe en la tabla de tools.py.

    Para un prefijo se pregunta por un nombre imposible con ese prefijo:
    `flag_de_optin` resuelve prefijos, asi que 'escena_zzz' -> COGNIA_LCD.
    """
    nombre = (patron + "zzz") if es_prefijo else patron
    return bool(tools_mod.flag_de_optin(nombre))


_RX_REGISTRO = re.compile(r"""(?:^|[^\w.])tool\(\s*["']([a-z][a-z0-9_]*)["']""")
_EN_EL_FUENTE: set = set()


def _registrada_en_el_fuente(nombre: str) -> bool:
    """Existe una llamada `tool("<nombre>", ...)` en algun modulo de cognia/.

    El TERCER modo de registro, que ni el registro vivo ni `flag_de_optin`
    ven: `mensaje_bot` no la enciende ningun flag sino un BOT ACTIVO
    (`tools.sincronizar_mensaje_bot()`), asi que en un pytest en frio no esta
    registrada y `flag_de_optin` devuelve "". Preguntarle al FUENTE es la
    unica prueba que cubre los tres modos a la vez, y de paso endurece el
    anticuerpo: una tool inventada no aparece en ningun fichero del repo.
    """
    if not _EN_EL_FUENTE:
        raiz = pathlib.Path(tools_mod.__file__).resolve().parents[1]
        for ruta in raiz.rglob("*.py"):
            try:
                texto = ruta.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            _EN_EL_FUENTE.update(_RX_REGISTRO.findall(texto))
    return nombre in _EN_EL_FUENTE


# ---------------------------------------------------------------------------
# 1. Cobertura contra el registro REAL
# ---------------------------------------------------------------------------
def test_toda_tool_registrada_tiene_categoria():
    """categoria_de() nunca devuelve vacio y siempre nombra un cajon real."""
    ids = {c["id"] for c in cn.CATEGORIAS} | {cn.OTROS["id"]}
    for nombre in _todas():
        cat = cn.categoria_de(nombre)
        assert cat, "categoria_de(%r) devolvio vacio" % nombre
        assert cat in ids, "categoria_de(%r) = %r, que no es un cajon" % (
            nombre, cat)


def test_ninguna_tool_registrada_cae_en_otros():
    """El guardian de la desincronizacion: 0 huerfanas en el registro vivo.

    Si esto se pone rojo es porque entro una tool nueva al repo y nadie la
    dio de alta en CATEGORIAS. El arreglo es la tabla, no el test.
    """
    huerfanas = [n for n in _todas()
                 if cn.categoria_de(n) == cn.OTROS["id"]]
    assert huerfanas == [], (
        "%d tool(s) sin cajon en la paleta: %s. Dalas de alta en "
        "catalogo_nodos.CATEGORIAS." % (len(huerfanas), ", ".join(huerfanas)))


# El barrido corre en un SUBPROCESO: `familias.activar()` escribe en el
# registro GLOBAL y en las variables de entorno del proceso, asi que hacerlo
# aqui dejaria a los tests que cuentan el catalogo por defecto contando 134.
# El subproceso es tambien lo que hace al test independiente del orden de la
# suite: no depende de que nadie haya encendido nada antes, ni deja nada
# encendido despues.
_BARRIDO = """
import importlib
import json
import os


def barrido():
    # Un bot activo es la unica manera de que `mensaje_bot` exista: no hay
    # flag que la encienda. COGNIA_BOTS_DIR ya apunta a un tmp del test.
    from cognia.bots import registro as _R
    _R.crear("paleta_barrido", titulo="barrido",
             descripcion="bot de usar y tirar del test de la paleta")
    os.environ["COGNIA_BOT"] = "paleta_barrido"

    from cognia.agent import tools as _T
    from cognia.agent import catalogo_nodos as _cn

    origen = dict.fromkeys(_T.TOOLS, "import")
    fallos = []

    def _apuntar(antes, etiqueta):
        for n in sorted(set(_T.TOOLS) - set(antes)):
            origen[n] = etiqueta

    # 1) TODO sincronizador del registry. Por introspeccion y no por una lista
    #    a mano: el proximo `sincronizar_*` entra solo en el barrido.
    sincros = sorted(n for n in dir(_T)
                     if n.startswith("sincronizar_") and callable(getattr(_T, n)))
    for nombre in sincros:
        antes = set(_T.TOOLS)
        try:
            getattr(_T, nombre)()
        except Exception as exc:
            fallos.append("%s: %s: %s" % (nombre, type(exc).__name__, exc))
            continue
        _apuntar(antes, nombre + "()")

    # 2) TODAS las familias opt-in, recorriendo la TABLA. Una familia nueva en
    #    familias.FAMILIAS queda cubierta sin tocar este test.
    from cognia.harness import familias as _F
    for fam in sorted(_F.FAMILIAS):
        antes = set(_T.TOOLS)
        try:
            _F.activar(fam)
        except Exception as exc:
            fallos.append("familia %s: %s: %s" % (fam, type(exc).__name__, exc))
            continue
        _apuntar(antes, "familia " + fam)

    # 3) Los registradores que NO tienen familia (TX, RLM, plan, flujos, MCP,
    #    arnes). Los flags COGNIA_TX / COGNIA_MCP los pone el test en el env.
    for etiqueta, mod, fn in (("tx", "cognia.tx.tools", "register"),
                              ("rlm", "cognia.agent.rlm", "register"),
                              ("plan", "cognia.agent.plan_artifact", "register"),
                              ("flujos", "cognia.agent.flows", "register"),
                              ("mcp", "cognia.agent.tools_mcp", ""),
                              ("arnes", "cognia.harness.tools_harness", "")):
        antes = set(_T.TOOLS)
        try:
            m = importlib.import_module(mod)
            if fn:
                getattr(m, fn)(_T.tool)
        except Exception as exc:
            fallos.append("%s: %s: %s" % (etiqueta, type(exc).__name__, exc))
            continue
        _apuntar(antes, etiqueta)

    otros = _cn.OTROS["id"]
    huerfanas = sorted(n for n in _T.TOOLS if _cn.categoria_de(n) == otros)
    cajones = [c["id"] for c in _cn.paleta()["categorias"]]
    return {
        "total": len(_T.TOOLS),
        "sincros": sincros,
        "mensaje_bot": "mensaje_bot" in _T.TOOLS,
        "huerfanas": [[n, origen.get(n, "?")] for n in huerfanas],
        "otros_pintado": otros in cajones,
        "fuentes": sorted(set(origen.values())),
        "fallos": fallos,
    }


print("__BARRIDO__" + json.dumps(barrido()))
"""


def _correr_barrido(tmp_path) -> dict:
    """Lanza el barrido en un interprete limpio y devuelve su informe."""
    raiz = pathlib.Path(cn.__file__).resolve().parents[2]
    env = dict(os.environ)
    env["COGNIA_BOTS_DIR"] = str(tmp_path)      # ningun bot real se toca
    env["COGNIA_TX"] = "1"
    env["COGNIA_MCP"] = "1"
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = os.pathsep.join(
        [str(raiz)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    env.pop("COGNIA_BOT", None)
    r = subprocess.run([sys.executable, "-c", _BARRIDO], env=env, cwd=str(raiz),
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=300)
    marca = [l for l in (r.stdout or "").splitlines()
             if l.startswith("__BARRIDO__")]
    assert marca, (
        "el barrido no llego a imprimir su JSON (rc=%s).\n--- stdout ---\n%s"
        "\n--- stderr ---\n%s" % (r.returncode, r.stdout, r.stderr))
    return json.loads(marca[-1][len("__BARRIDO__"):])


def test_ninguna_tool_registrable_en_caliente_cae_en_otros(tmp_path):
    """EL ANTICUERPO. Se registra TODO lo registrable y NADA cae en "Otros".

    Es el guardian que faltaba: `test_ninguna_tool_registrada_cae_en_otros`
    solo ve el registro de ESTE proceso, y las tools que entran en caliente
    (`sincronizar_mensaje_bot`) o bajo flag son invisibles para el en un
    pytest en frio. Si esto se pone rojo es porque entro una tool dinamica
    nueva y nadie la dio de alta: el arreglo es CATEGORIAS, no el test.
    """
    r = _correr_barrido(tmp_path)
    # Sin esto el test podria pasar por no haber encendido NADA (un banco sin
    # cablear mide cero): `mensaje_bot` es justo la tool que se escapo.
    assert r["mensaje_bot"] is True, (
        "el barrido no llego a registrar mensaje_bot: esta midiendo en vacio. "
        "sincronizadores vistos: %s; fallos: %s" % (r["sincros"], r["fallos"]))
    assert "sincronizar_mensaje_bot" in r["sincros"]
    assert r["huerfanas"] == [], (
        "%d tool(s) registrables caen en el cajon Otros:\n%s\n"
        "Dalas de alta en catalogo_nodos.CATEGORIAS."
        % (len(r["huerfanas"]),
           "\n".join("  - %-28s <- %s" % (n, o) for n, o in r["huerfanas"])))


def test_la_paleta_no_pinta_otros_ni_con_todo_encendido(tmp_path):
    """El sintoma que ve el dueno: `/bots chat <bot>` + editor = cajon gris.

    Separado del de arriba a proposito: son dos afirmaciones distintas (una
    tool sin cajon vs. la paleta pintando el cajon de respaldo) y cuando esto
    cae, el mensaje dice cual de las dos fallo.
    """
    r = _correr_barrido(tmp_path)
    assert r["otros_pintado"] is False, (
        "con todo encendido la paleta pinta el cajon Otros con: %s"
        % ", ".join(n for n, _ in r["huerfanas"]))


def test_la_tabla_no_nombra_tools_inventadas():
    """Anticuerpo del ejemplo con la tool INVENTADA: cada nombre exacto de la
    tabla o esta registrado, o es de una familia opt-in conocida."""
    vivas = set(_todas())
    inventadas = []
    for cat in cn.CATEGORIAS:
        for nombre in cat.get("tools") or ():
            if nombre in vivas:
                continue
            if _es_optin(nombre, False):
                continue
            # Tercer modo: registrada EN CALIENTE, sin flag que la anuncie
            # (mensaje_bot y su bot activo). El fuente es quien lo sabe.
            if _registrada_en_el_fuente(nombre):
                continue
            inventadas.append("%s (%s)" % (nombre, cat["id"]))
    assert inventadas == [], (
        "la tabla nombra tools que no existen ni son opt-in: "
        + ", ".join(inventadas))


def test_ninguna_categoria_esta_vacia_contra_el_registro_real():
    """Cada cajon tiene contenido: o tools vivas, o tools opt-in declaradas.

    Un cajon que no puede llenarse NUNCA es ruido en el panel lateral.
    """
    vivas = _todas()
    for cat in cn.CATEGORIAS:
        n = sum(1 for t in vivas if cn.categoria_de(t) == cat["id"])
        if n:
            continue
        patrones = _patrones_de(cat)
        assert patrones, "la categoria %r no declara ni un patron" % cat["id"]
        assert any(_es_optin(p, pref) for p, pref in patrones), (
            "la categoria %r no tiene ninguna tool viva y ninguno de sus "
            "patrones es opt-in: es un cajon muerto" % cat["id"])


# ---------------------------------------------------------------------------
# 2. La regla de clasificacion
# ---------------------------------------------------------------------------
def test_patron_mas_largo_gana():
    """ctx_grep -> contexto (prefijo ctx_), no otros; y los cuatro 'buscar*'
    caen en cajones distintos por su nombre exacto, igual que en ayuda.py."""
    assert cn.categoria_de("ctx_grep") == "contexto"
    assert cn.categoria_de("rlm_llamar") == "contexto"
    assert cn.categoria_de("git_commit") == "codigo"
    assert cn.categoria_de("buscar") == "lectura"
    assert cn.categoria_de("buscar_ficheros") == "lectura"
    assert cn.categoria_de("buscar_en_repo") == "codigo"
    assert cn.categoria_de("buscar_herramientas") == "ia"


def test_exacto_le_gana_al_prefijo_de_la_misma_longitud():
    """La mitad de la regla que el registro real no puede ejercitar hoy: se
    prueba sobre el nucleo con patrones falsos, no inventando una tool."""
    patrones = [("ctx_grep", True, "porPrefijo", 0),
                ("ctx_grep", False, "porExacto", 1)]
    assert cn._clasificar("ctx_grep", patrones) == "porExacto"
    # y el mas largo sigue ganando aunque el corto sea exacto
    patrones = [("ctx", True, "corto", 0),
                ("ctx_grep_largo", True, "largo", 1)]
    assert cn._clasificar("ctx_grep_largo", patrones) == "largo"


def test_lo_que_no_casa_cae_en_otros_y_nunca_explota():
    assert cn.categoria_de("tool_que_no_existe_2099") == cn.OTROS["id"]
    assert cn.categoria_de("") == cn.OTROS["id"]
    assert cn.categoria_de(None) == cn.OTROS["id"]


# ---------------------------------------------------------------------------
# 3. Forma de la tabla
# ---------------------------------------------------------------------------
def test_colores_son_hex_de_7_chars_en_ambos_temas():
    for cat in list(cn.CATEGORIAS) + [cn.OTROS]:
        for clave in ("color", "color_osc"):
            valor = cat.get(clave, "")
            assert _RX_HEX.match(valor), (
                "%s.%s = %r no es un hex de 7 chars" % (cat["id"], clave, valor))


def test_cada_categoria_tiene_id_nombre_e_icono_unicos():
    ids, nombres, = [], []
    for cat in list(cn.CATEGORIAS) + [cn.OTROS]:
        for clave in ("id", "nombre", "icono"):
            assert str(cat.get(clave, "")).strip(), (
                "la categoria %r no tiene %s" % (cat.get("id"), clave))
        ids.append(cat["id"])
        nombres.append(cat["nombre"])
    assert len(set(ids)) == len(ids), "ids repetidos: %s" % ids
    assert len(set(nombres)) == len(nombres), "nombres repetidos: %s" % nombres


def test_ninguna_tool_esta_declarada_en_dos_cajones():
    visto = {}
    for cat in cn.CATEGORIAS:
        for nombre in cat.get("tools") or ():
            assert nombre not in visto, (
                "%r esta en %r y en %r" % (nombre, visto.get(nombre), cat["id"]))
            visto[nombre] = cat["id"]


# ---------------------------------------------------------------------------
# 4. catalogo()
# ---------------------------------------------------------------------------
def test_catalogo_cubre_el_registro_entero_sin_inventar_nada():
    nodos = cn.catalogo()
    assert [n["nombre"] for n in nodos] == _todas()


def test_cada_nodo_trae_lo_que_el_editor_pinta():
    claves = ("nombre", "descripcion", "categoria", "color", "color_osc",
              "icono", "danger", "familia", "flag", "activa", "params")
    for n in cn.catalogo():
        for k in claves:
            assert k in n, "el nodo %r no trae %r" % (n.get("nombre"), k)
        assert isinstance(n["danger"], bool)
        assert isinstance(n["activa"], bool)
        assert isinstance(n["params"], list)
        assert _RX_HEX.match(n["color"]) and _RX_HEX.match(n["color_osc"])


def test_la_descripcion_es_UNA_linea_y_sin_la_plantilla_de_uso():
    for n in cn.catalogo():
        d = n["descripcion"]
        assert "\n" not in d, "%s tiene salto de linea" % n["nombre"]
        assert len(d) <= 160, "%s: %d chars" % (n["nombre"], len(d))
        assert d.strip() == d
    por_nombre = {n["nombre"]: n for n in cn.catalogo()}
    # el doc de una linea trae "arbol <directorio>   -- arbol de archivos":
    # a la tarjeta va lo de DESPUES del guion, no la plantilla de argumentos.
    assert not por_nombre["arbol"]["descripcion"].startswith("arbol <")
    assert por_nombre["arbol"]["descripcion"]


def test_los_params_salen_del_schema_de_la_tool():
    por_nombre = {n["nombre"]: n for n in cn.catalogo()}
    params = {p["nombre"]: p for p in por_nombre["leer_archivo"]["params"]}
    assert "path" in params
    assert params["path"]["requerido"] is True
    assert params["path"]["tipo"] == "string"
    assert params["offset"]["requerido"] is False


def test_danger_sale_del_registro_y_no_de_una_lista_a_mano():
    por_nombre = {n["nombre"]: n for n in cn.catalogo()}
    for nombre, spec in tools_mod.TOOLS.items():
        assert por_nombre[nombre]["danger"] == bool(spec.get("danger"))
    assert por_nombre["borrar_archivo"]["danger"] is True


def test_allowed_filtra_el_catalogo():
    nodos = cn.catalogo(allowed={"leer_archivo", "ejecutar"})
    assert [n["nombre"] for n in nodos] == ["ejecutar", "leer_archivo"]
    assert cn.catalogo(allowed=set()) == []


def test_una_tool_del_nucleo_esta_activa_y_una_opt_in_apagada_no():
    por_nombre = {n["nombre"]: n for n in cn.catalogo()}
    assert por_nombre["leer_archivo"]["activa"] is True
    assert por_nombre["leer_archivo"]["flag"] == ""
    # `workflow` esta REGISTRADA siempre pero solo se anuncia con su flag:
    # la paleta la muestra apagada con el flag al lado (ocultar no es
    # desactivar). Si la suite corriera con el flag puesto, seguiria siendo
    # coherente: activa <-> flag encendido.
    wf = por_nombre["workflow"]
    assert wf["flag"] == "COGNIA_WORKFLOW_TOOL"
    assert wf["activa"] is cn._flag_activo("COGNIA_WORKFLOW_TOOL")


def test_catalogo_no_explota_si_familias_estado_falla(monkeypatch):
    """El cruce con familias es DECORACION; sin el, la paleta sigue entera.

    Un catalogo que revienta deja al editor sin panel lateral y sin motivo
    visible, que es el modo de fallo de la casa.
    """
    from cognia.harness import familias

    def _revienta():
        raise RuntimeError("familias rota a proposito")

    monkeypatch.setattr(familias, "estado", _revienta)
    nodos = cn.catalogo()
    assert [n["nombre"] for n in nodos] == _todas()
    por_nombre = {n["nombre"]: n for n in nodos}
    assert por_nombre["leer_archivo"]["activa"] is True
    assert por_nombre["leer_archivo"]["familia"] == ""
    # y la que depende de un flag cae a la variable de entorno, no a True
    wf = por_nombre["workflow"]
    assert wf["activa"] is cn._flag_activo("COGNIA_WORKFLOW_TOOL")


def test_catalogo_no_explota_si_la_oficina_no_esta(monkeypatch):
    from cognia.oficina import identidad

    def _revienta(*a, **k):
        raise RuntimeError("oficina rota a proposito")

    monkeypatch.setattr(identidad, "roster", _revienta)
    monkeypatch.setattr(identidad, "recomendar_modelo", _revienta)
    nodos = cn.catalogo()
    assert len(nodos) == len(tools_mod.TOOLS)
    assert nodos[0]["modelo"] == ""
    assert nodos[0]["modelo_color"] == ""


# ---------------------------------------------------------------------------
# 5. paleta()
# ---------------------------------------------------------------------------
def test_paleta_agrupa_en_el_orden_de_categorias_y_no_pierde_nodos():
    p = cn.paleta()
    orden_tabla = [c["id"] for c in cn.CATEGORIAS]
    orden_paleta = [c["id"] for c in p["categorias"]]
    # mismo orden relativo (las vacias siguen ahi; `otros` solo si hay algo)
    assert [c for c in orden_paleta if c != "otros"] == [
        c for c in orden_tabla if c in orden_paleta]
    sueltos = sorted(n["nombre"] for c in p["categorias"] for n in c["nodos"])
    assert sueltos == _todas()
    assert p["total"] == len(sueltos)
    assert sum(c["n"] for c in p["categorias"]) == p["total"]


def test_paleta_no_pinta_el_cajon_otros_si_esta_vacio():
    p = cn.paleta()
    vacio = [c for c in p["categorias"] if c["id"] == "otros"]
    assert vacio == [], "otros aparece en la paleta con %r" % (
        [n["nombre"] for n in vacio[0]["nodos"]] if vacio else [])


def test_paleta_trae_los_cajones_humanos_que_pidio_el_dueno():
    """Memoria, busqueda web, archivos... con nombre de persona, no de modulo."""
    por_id = {c["id"]: c for c in cn.paleta()["categorias"]}
    for cid in ("lectura", "escritura", "memoria", "web", "ejecucion", "ia"):
        assert cid in por_id
    assert por_id["memoria"]["nombre"] == "Memoria y notas"
    assert por_id["web"]["nombre"] == "Web e investigacion"
    assert por_id["lectura"]["n"] >= 5
    for c in por_id.values():
        assert "_" not in c["nombre"], "%r parece un id, no un nombre" % (
            c["nombre"],)


@pytest.mark.parametrize("nombre,cat", [
    ("leer_archivo", "lectura"),
    ("escribir_archivo", "escritura"),
    ("borrar_archivo", "escritura"),
    ("git_diff", "codigo"),
    ("ejecutar", "ejecucion"),
    ("http_get", "web"),
    ("recordar", "memoria"),
    ("delegar_subtarea", "ia"),
    ("ctx_ver", "contexto"),
    ("imagen_generar", "medios"),
    ("pantalla_click", "pantalla"),
    ("escena_crear", "escena"),
    ("render_aprox", "escena"),
    ("atribuir_fallo", "escena"),
    ("reejecutar_etapa", "escena"),
    ("libro_grep", "horizonte"),
    ("decidir", "horizonte"),
    ("calcular", "util"),
])
def test_las_tools_caen_donde_un_humano_las_buscaria(nombre, cat):
    assert cn.categoria_de(nombre) == cat


# ---------------------------------------------------------------------------
# 6. El cajon de ENTRADA (PLAN2, PEDIDO 3)
# ---------------------------------------------------------------------------
# `prompt` y `prompt_fijo` son las dos tools de entrada de un flujo. Antes de
# esta tabla `categoria_de("prompt")` caia en "otros", que es el cajon gris
# de "no se donde ponerlo": el nodo por el que EMPIEZA cada flujo aparecia en
# el desvan de la paleta. Estos tests fijan las cuatro cosas que el editor
# necesita para poder dibujarlo: que tiene cajon propio, que ese cajon va el
# PRIMERO, que su icono lo sabe dibujar `editor_html`, y que el catalogo
# entrega los params (para la firma que ve el modelo en el prompt).

def test_prompt_y_prompt_fijo_no_caen_en_otros():
    assert cn.categoria_de("prompt") == "entrada"
    assert cn.categoria_de("prompt_fijo") == "entrada"
    assert cn.categoria_de("prompt") != cn.OTROS["id"]
    assert cn.categoria_de("prompt_fijo") != cn.OTROS["id"]


def test_la_entrada_es_el_primer_cajon_de_la_paleta():
    """Es por donde EMPIEZA un flujo: si sale el septimo, el dueno que abre
    el editor por primera vez no encuentra por donde entra su objetivo."""
    assert cn.CATEGORIAS[0]["id"] == "entrada"
    ids = [c["id"] for c in cn.paleta()["categorias"]]
    assert ids[0] == "entrada", ids


def test_el_cajon_de_entrada_trae_las_dos_tools_con_sus_params():
    """Contra el registro REAL: si `flows.register` deja de registrarlas, o
    les cambia el nombre, esto se pone rojo aqui y no en el navegador."""
    vivas = set(_todas())
    faltan = {"prompt", "prompt_fijo"} - vivas
    assert not faltan, (
        "las tools de entrada no estan registradas: %s. Las registra "
        "flows.register() (PLAN2 PEDIDO 3)" % sorted(faltan))
    por_nombre = {n["nombre"]: n for n in cn.catalogo()}
    for nombre in ("prompt", "prompt_fijo"):
        n = por_nombre[nombre]
        assert n["categoria"] == "entrada"
        assert n["danger"] is False
        assert n["descripcion"], "%s sin descripcion en la paleta" % nombre
        assert len(n["params"]) >= 1, (
            "%s no declara ni un param: la firma que ve el modelo saldria "
            "vacia" % nombre)
    cajon = {c["id"]: c for c in cn.paleta()["categorias"]}["entrada"]
    assert cajon["n"] == 2 and cajon["n_activas"] == 2
    assert cajon["apagada"] is False


_RX_ICONOS_JS = re.compile(r"var ICONOS = \{(.*?)\n\};", re.S)


def _iconos_del_html() -> set:
    """Las claves del mapa JS `ICONOS` de editor_html, leidas del fuente.

    Es la lista de iconos que la pagina SABE dibujar: `icono()` cae a
    `ICONOS.box` con cualquier otro nombre, o sea que un icono inventado se
    ve exactamente igual que el cajon "Otros" -- el aspecto que la paleta
    viene a quitar, y sin un solo error en consola que lo delate.
    """
    from cognia.agent import editor_html
    m = _RX_ICONOS_JS.search(editor_html.HTML)
    assert m, "no encuentro el mapa ICONOS en editor_html.HTML"
    return set(re.findall(r"^\s{2}([a-z_]+):", m.group(1), re.M))


def test_todo_icono_de_la_tabla_lo_sabe_dibujar_editor_html():
    conocidos = _iconos_del_html()
    assert len(conocidos) >= 10, conocidos
    for cat in list(cn.CATEGORIAS) + [cn.OTROS]:
        assert cat["icono"] in conocidos, (
            "la categoria %r pide el icono %r y editor_html solo dibuja %s"
            % (cat["id"], cat["icono"], sorted(conocidos)))
