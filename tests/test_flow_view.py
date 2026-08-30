# -*- coding: utf-8 -*-
"""Lienzo visual de flujos estilo n8n (flow_view.py)."""
from cognia.agent.flow_view import build_layout, render_html


FLUJO = {"nombre": "demo", "nodos": [
    {"id": "a", "tool": "listar", "args": "x/", "wires": ["b", "c"]},
    {"id": "b", "tool": "buscar", "args": "TODO", "wires": ["d"]},
    {"id": "c", "tool": "tests", "args": "correr", "wires": ["d"]},
    {"id": "d", "tool": "responder", "args": "fin", "wires": []}]}


def test_layout_niveles_y_cables():
    lay = build_layout(FLUJO)
    assert len(lay["cajas"]) == 4
    assert len(lay["cables"]) == 4          # a->b,a->c,b->d,c->d
    xs = {c["id"]: c["x"] for c in lay["cajas"]}
    assert xs["a"] < xs["b"] and xs["b"] < xs["d"]   # columnas por profundidad


def test_render_autocontenido():
    h = render_html(FLUJO, "Prueba")
    assert "<svg" in h and "listar" in h and "responder" in h
    assert "http://" not in h and "https://" not in h and "src=" not in h
    assert "Prueba" in h and "4 pasos" in h


# ---------------------------------------------------------------------------
# Posiciones manuales (editor visual). Sin `pos`, nada cambia.
# ---------------------------------------------------------------------------

def test_sin_pos_el_layout_es_identico():
    """SNAPSHOT del layout automatico, campo a campo.

    `build_layout` gano un parametro `pos` para el editor visual. Este test
    es el que impide que ese parametro cambie el dibujo de los flujos que NO
    tienen posiciones manuales, que son todos los de antes del editor: la
    geometria, el orden de las cajas, la numeracion y los cables tienen que
    salir exactamente iguales. Lo unico nuevo es la clave "pos_manual", que
    aqui es False en todas.

    El color no se escribe a mano: sale de `_color_modelo`, que consulta la
    identidad de la oficina. Fijarlo aqui haria fallar el test cuando cambie
    la paleta, que no es lo que este test vigila.
    """
    from cognia.agent.flow_view import _color_modelo
    color, modelo = _color_modelo(None, None)

    esperado = {
        "cajas": [
            {"id": "a", "x": 40, "y": 56, "w": 210, "h": 66, "n": 1,
             "tool": "listar", "args": "x/", "color": color,
             "modelo": modelo, "pos_manual": False},
            {"id": "b", "x": 346, "y": 56, "w": 210, "h": 66, "n": 2,
             "tool": "buscar", "args": "TODO", "color": color,
             "modelo": modelo, "pos_manual": False},
            {"id": "c", "x": 346, "y": 156, "w": 210, "h": 66, "n": 3,
             "tool": "tests", "args": "correr", "color": color,
             "modelo": modelo, "pos_manual": False},
            {"id": "d", "x": 652, "y": 56, "w": 210, "h": 66, "n": 4,
             "tool": "responder", "args": "fin", "color": color,
             "modelo": modelo, "pos_manual": False},
        ],
        "cables": [
            {"x1": 250, "y1": 89.0, "x2": 346, "y2": 89.0},
            {"x1": 250, "y1": 89.0, "x2": 346, "y2": 189.0},
            {"x1": 556, "y1": 89.0, "x2": 652, "y2": 89.0},
            {"x1": 556, "y1": 189.0, "x2": 652, "y2": 89.0},
        ],
        "w": 902, "h": 262,
        "modelos": {modelo: color} if modelo else {},
    }

    assert build_layout(FLUJO) == esperado
    assert build_layout(FLUJO, None) == esperado
    assert build_layout(FLUJO, {}) == esperado


def test_pos_manual_gana_al_layout_topologico():
    lay = build_layout(FLUJO, {"b": {"x": 800, "y": 400}})
    cajas = {c["id"]: c for c in lay["cajas"]}

    assert (cajas["b"]["x"], cajas["b"]["y"]) == (800, 400)
    assert cajas["b"]["pos_manual"] is True
    assert cajas["a"]["pos_manual"] is False
    # el lienzo crece para que el nodo movido siga dentro
    assert lay["w"] >= 800 + 210 and lay["h"] >= 400 + 66


def test_mover_un_nodo_no_mueve_a_sus_vecinos():
    """`c` comparte columna con `b`. Si el layout automatico se recalculara
    sin `b`, `c` subiria de fila sola: el dueno arrastra un nodo y se le
    reordena medio flujo."""
    base = {c["id"]: (c["x"], c["y"]) for c in build_layout(FLUJO)["cajas"]}
    movido = {c["id"]: (c["x"], c["y"])
              for c in build_layout(FLUJO, {"b": {"x": 800, "y": 400}})["cajas"]}

    assert movido["c"] == base["c"]
    assert movido["a"] == base["a"] and movido["d"] == base["d"]


def test_los_cables_siguen_al_nodo_movido():
    lay = build_layout(FLUJO, {"d": {"x": 900, "y": 500}})
    # a->b, a->c, b->d, c->d: los dos ultimos entran en el nodo movido
    entradas = [k for k in lay["cables"] if (k["x2"], k["y2"]) == (900, 533.0)]
    assert len(entradas) == 2


def test_una_posicion_a_medias_o_con_basura_cae_al_automatico():
    """Colocar el nodo en la x que dijo el navegador y en la y calculada lo
    pondria donde no lo puso nadie: se descarta la entrada entera."""
    base = {c["id"]: (c["x"], c["y"]) for c in build_layout(FLUJO)["cajas"]}
    lay = build_layout(FLUJO, {"a": {"x": 700},
                               "b": {"x": "no", "y": 1},
                               "c": "ni siquiera un dict",
                               "d": {"x": "660", "y": 12.6}})
    cajas = {c["id"]: c for c in lay["cajas"]}

    for nid in ("a", "b", "c"):
        assert (cajas[nid]["x"], cajas[nid]["y"]) == base[nid]
        assert cajas[nid]["pos_manual"] is False
    # el texto numerico si es una posicion: es lo que manda un <input>
    assert (cajas["d"]["x"], cajas["d"]["y"]) == (660, 13)
    assert cajas["d"]["pos_manual"] is True


def test_pos_de_un_id_que_ya_no_existe_no_estorba():
    """El flujo se edito y el nodo desaparecio, pero su posicion sigue en la
    meta: sobra, no rompe."""
    assert build_layout(FLUJO, {"borrado": {"x": 1, "y": 2}}) == build_layout(FLUJO)


# ---------------------------------------------------------------------------
# El lienzo NO revienta por el tipo de un campo (bug e2e 2026-08-29)
#
# build_layout lee lo que hay EN DISCO. Con `args` dict reventaba con
# `KeyError: slice(None, 46, None)` y /api/flujo devolvia 404 PARA SIEMPRE:
# el flujo quedaba guardado e inabrible en el editor. La validacion ya
# rechaza esos flujos al guardar (tests en test_flows.py), pero la vista
# tiene que poder abrir igual los que YA estan escritos.
# ---------------------------------------------------------------------------

def _flujo(args):
    return {"nombre": "raro", "nodos": [
        {"id": "a", "tool": "listar", "args": args, "wires": ["b"]},
        {"id": "b", "tool": "responder", "args": "fin", "wires": []}]}


def test_build_layout_sobrevive_a_args_de_cualquier_tipo():
    for args in ({"ruta": "."}, ["a", "b"], 42, 1.5, None, True, object()):
        lay = build_layout(_flujo(args))
        cajas = {c["id"]: c for c in lay["cajas"]}
        assert len(lay["cajas"]) == 2 and len(lay["cables"]) == 1
        assert isinstance(cajas["a"]["args"], str)
        assert len(cajas["a"]["args"]) <= 46
    # y el dict se ve, no se traga: el dueno tiene que poder arreglarlo
    caja_a = {c["id"]: c for c in build_layout(_flujo({"ruta": "."}))["cajas"]}["a"]
    assert "ruta" in caja_a["args"]


def test_render_html_sobrevive_a_args_de_cualquier_tipo():
    h = render_html(_flujo({"ruta": "."}), "Raro")
    assert "<svg" in h and "listar" in h and "ruta" in h


def test_build_layout_sobrevive_a_los_demas_campos_raros():
    """Mismo genero que el de args: nada de lo que venga del JSON puede
    tumbar la vista. `wires` como string es UN cable (la misma errata que ya
    arregla flujo_ia cuando la comete el modelo), no tres letras."""
    flujo = {"nodos": [
        {"id": 1, "tool": {"nombre": "listar"}, "args": "x", "wires": "b"},
        {"id": "b", "tool": "responder", "args": "fin", "wires": None,
         "modelo": {"x": 1}, "color": 123},
        "esto no es un nodo",
        {"tool": "sin id", "args": "x"}]}
    lay = build_layout(flujo)
    ids = [c["id"] for c in lay["cajas"]]
    assert ids == ["1", "b"]                      # el id numerico se dibuja
    assert len(lay["cables"]) == 1                # 1 -> b, no tres cables
    assert all(isinstance(c["tool"], str) for c in lay["cajas"])
    assert "<svg" in render_html(flujo)


def test_build_layout_con_un_flujo_que_no_es_un_flujo():
    vacio = {"cajas": [], "cables": [], "w": 440, "h": 240, "modelos": {}}
    for basura in ({}, {"nodos": None}, {"nodos": "abc"}, [], None, "texto"):
        assert build_layout(basura) == vacio


# ---------------------------------------------------------------------------
# INTEGRACION: el ciclo completo guardar -> abrir
# ---------------------------------------------------------------------------

def test_un_flujo_con_args_dict_ya_escrito_en_disco_SE_PUEDE_ABRIR(tmp_path,
                                                                   monkeypatch):
    """El caso caro: el flujo ya esta guardado (lo escribio una version sin
    el chequeo, un import o un fichero tecleado a mano). Si la vista revienta
    al releerlo, el dueno no lo puede ni abrir ni arreglar."""
    monkeypatch.setenv("COGNIA_FLUJOTECA_DIR", str(tmp_path / "flujoteca"))
    from cognia.agent import flujoteca as ft

    ft.guardar(_flujo({"ruta": "."}), nombre="bug args dict", validar=False)
    guardado = ft.cargar("bug args dict")
    # Por ID y no por posicion: `flujoteca.guardar` antepone el nodo de
    # ENTRADA (`flows.asegurar_prompt`, PLAN2 PEDIDO 3), asi que `nodos[0]`
    # es ese nodo nuevo y no el que escribio este test.
    por_id = {n["id"]: n for n in guardado["nodos"]}
    assert isinstance(por_id["a"]["args"], dict)            # esta en disco asi

    lay = build_layout(guardado, {})                        # antes: KeyError
    ids = [c["id"] for c in lay["cajas"]]
    assert ids[-2:] == ["a", "b"], ids
    assert "<svg" in render_html(guardado)


def test_guardar_hoy_un_flujo_con_args_dict_se_rechaza_y_no_escribe(tmp_path,
                                                                    monkeypatch):
    """La otra punta: hoy no llega a disco, y el motivo se lee (es el mismo
    texto que /api/guardar devuelve con 400)."""
    monkeypatch.setenv("COGNIA_FLUJOTECA_DIR", str(tmp_path / "flujoteca"))
    import pytest
    from cognia.agent import flujoteca as ft
    from cognia.agent.flows import FlowError

    with pytest.raises(FlowError) as exc:
        ft.guardar(_flujo({"ruta": "."}), nombre="bug args dict")
    assert "'a'" in str(exc.value) and "dict" in str(exc.value)
    assert ft.listar() == []                       # nada escrito
