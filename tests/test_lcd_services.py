"""
Regresion de los servicios AI-nativos de LCD (cognia/lcd/exporters.py,
history.py, templates.py, tools_services.py): export/import SVG+JSON,
undo/redo por escena, plantillas listas, y las tools ACCION que los exponen.
"""
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

import cognia.lcd.tools_lcd as lcd_tools          # noqa: F401 -- registra escena_crear/etc
import cognia.lcd.tools_services as svc_tools     # noqa: F401 -- registra las tools de servicio
from cognia.agent.tools import TOOLS, run_tool
from cognia.lcd.exporters import export_scene, import_scene_json, scene_to_svg
from cognia.lcd.history import SceneHistory
from cognia.lcd.scene import Obj, Scene
from cognia.lcd.templates import get_template, list_templates
from cognia.lcd.tools_services import load_service_tools


def _ctx():
    return {"working_memory": {}, "agent_state": {}}


# ── A. exporters.py ──────────────────────────────────────────────────────────

def test_scene_to_svg_un_elemento_por_objeto_y_xml_valido():
    scene = get_template("cielo")            # sol(circle) + nube(ellipse) + pajaro(triangle)
    svg = scene_to_svg(scene)
    root = ET.fromstring(svg)                # lanza ParseError si no es XML bien formado
    assert len(list(root)) == len(scene.objects) + 1   # +1 = el rect de fondo


def test_scene_to_svg_formas_correctas():
    scene = get_template("mesa_servida")     # mesa(rect) + plato/taza(ellipse) + libro(rect)
    svg = scene_to_svg(scene)
    assert svg.count("<rect") >= 1 and "<ellipse" in svg


def test_scene_to_svg_aplica_rotacion():
    scene = Scene(objects=[Obj(name="caja", shape="rect", x=0.5, y=0.5, w=0.2, h=0.2,
                                rotation=45.0)])
    svg = scene_to_svg(scene)
    assert "rotate(45" in svg


def test_scene_to_svg_sin_rotacion_no_agrega_transform():
    scene = Scene(objects=[Obj(name="caja", shape="rect", x=0.5, y=0.5, w=0.2, h=0.2)])
    svg = scene_to_svg(scene)
    assert "rotate(" not in svg


def test_export_json_roundtrip_preserva_objetos():
    scene = get_template("mesa_servida")
    texto = export_scene(scene, "json")
    reconstruida = Scene.from_json(texto)
    assert reconstruida == scene


def test_export_formato_invalido_lanza():
    scene = get_template("cielo")
    with pytest.raises(ValueError):
        export_scene(scene, "bmp")


def test_export_scene_a_archivo_y_import_scene_json(tmp_path):
    scene = get_template("sala")
    ruta = tmp_path / "escena.json"
    escrito = export_scene(scene, "json", str(ruta))
    assert Path(escrito).exists()
    cargada = import_scene_json(str(ruta))
    assert cargada == scene


# ── B. history.py ─────────────────────────────────────────────────────────────

def test_history_push_3_undo_da_el_2do_redo_vuelve_al_3ro():
    h = SceneHistory()
    a, b, c = get_template("cielo"), get_template("sala"), get_template("naturaleza")
    h.push(a)
    h.push(b)
    h.push(c)
    vuelto = h.undo()
    assert vuelto == b
    rehecho = h.redo()
    assert rehecho == c


def test_history_undo_en_pila_vacia_da_none():
    h = SceneHistory()
    assert h.undo() is None
    assert h.redo() is None


def test_history_un_solo_push_no_tiene_a_donde_volver():
    h = SceneHistory()
    h.push(get_template("cielo"))
    assert h.undo() is None            # no hay estado ANTERIOR al unico pusheado


def test_history_push_limpia_el_redo_stack():
    h = SceneHistory()
    h.push(get_template("cielo"))
    h.push(get_template("sala"))
    h.undo()
    assert len(h.redo_stack) == 1
    h.push(get_template("naturaleza"))     # nuevo cambio invalida el redo pendiente
    assert h.redo_stack == []
    assert h.redo() is None


def test_history_tope_descarta_los_mas_viejos():
    h = SceneHistory(max_snapshots=5)
    for _ in range(10):
        h.push(get_template("cielo"))
    assert len(h.undo_stack) == 5
    assert len(h) == 5


# ── C. templates.py ───────────────────────────────────────────────────────────

def test_templates_pedidas_estan_presentes():
    nombres = set(list_templates())
    for esperado in ("mesa_servida", "cielo", "sala", "escritorio",
                      "naturaleza", "pila_cajas"):
        assert esperado in nombres


def test_templates_todas_tienen_al_menos_2_objetos():
    for nombre in list_templates():
        scene = get_template(nombre)
        assert isinstance(scene, Scene)
        assert len(scene.objects) >= 2, nombre


def test_get_template_nombre_invalido_da_none():
    assert get_template("esto_no_existe") is None
    assert get_template("") is None


def test_pila_cajas_apiladas_de_abajo_hacia_arriba():
    scene = get_template("pila_cajas")
    ys = [o.y for o in scene.objects]
    assert ys == sorted(ys, reverse=True)      # la de mas arriba tiene menor y


# ── D. tools_services.py (tools ACCION) ──────────────────────────────────────

def test_tools_de_servicio_registradas():
    for t in ("escena_exportar", "escena_importar", "escena_deshacer",
              "escena_rehacer", "escena_plantilla"):
        assert t in TOOLS, f"{t} no registrada"
    assert load_service_tools() == 5


def test_escena_plantilla_carga_una_escena_con_objetos():
    ctx = _ctx()
    out = run_tool("escena_plantilla", "cielo", ctx)
    assert "ERROR" not in out
    scene = ctx["working_memory"]["_lcd_scene"]["escena"]
    assert len(scene.objects) >= 2


def test_escena_plantilla_nombre_invalido_es_error():
    out = run_tool("escena_plantilla", "no_existe", _ctx())
    assert "ERROR" in out


def test_escena_exportar_sin_escena_activa_es_error():
    assert "ERROR" in run_tool("escena_exportar", "svg", _ctx())


def test_escena_exportar_svg_sin_archivo_da_extracto():
    ctx = _ctx()
    run_tool("escena_plantilla", "cielo", ctx)
    out = run_tool("escena_exportar", "svg", ctx)
    assert "ERROR" not in out
    assert "<svg" in out


def test_escena_exportar_json_a_archivo(tmp_path):
    ctx = _ctx()
    run_tool("escena_plantilla", "mesa_servida", ctx)
    dest = str(tmp_path / "escena.json")
    out = run_tool("escena_exportar", f"json | {dest}", ctx)
    assert "ERROR" not in out
    assert Path(dest).exists()


def test_escena_exportar_formato_invalido_es_error():
    ctx = _ctx()
    run_tool("escena_plantilla", "cielo", ctx)
    assert "ERROR" in run_tool("escena_exportar", "bmp", ctx)


def test_escena_importar_tras_exportar_hace_roundtrip(tmp_path):
    ctx = _ctx()
    run_tool("escena_plantilla", "sala", ctx)
    original = ctx["working_memory"]["_lcd_scene"]["escena"]
    dest = str(tmp_path / "sala.json")
    out_export = run_tool("escena_exportar", f"json | {dest}", ctx)
    assert "ERROR" not in out_export

    ctx2 = _ctx()
    out_import = run_tool("escena_importar", dest, ctx2)
    assert "ERROR" not in out_import
    importada = ctx2["working_memory"]["_lcd_scene"]["escena"]
    assert importada == original


def test_escena_importar_archivo_inexistente_es_error():
    out = run_tool("escena_importar", "esto_no_existe_seguro.json", _ctx())
    assert "ERROR" in out


def test_escena_deshacer_rehacer_cambian_la_escena_activa():
    ctx = _ctx()
    run_tool("escena_plantilla", "cielo", ctx)          # push A, activa=A
    run_tool("escena_plantilla", "sala", ctx)           # push B, activa=B
    activa = ctx["working_memory"]["_lcd_scene"]["escena"]
    assert activa == get_template("sala")

    out = run_tool("escena_deshacer", "", ctx)
    assert "ERROR" not in out
    activa = ctx["working_memory"]["_lcd_scene"]["escena"]
    assert activa == get_template("cielo")              # vuelve a A

    out = run_tool("escena_rehacer", "", ctx)
    assert "ERROR" not in out
    activa = ctx["working_memory"]["_lcd_scene"]["escena"]
    assert activa == get_template("sala")               # rehace a B


def test_escena_deshacer_sin_historial_es_error():
    assert "ERROR" in run_tool("escena_deshacer", "", _ctx())


def test_escena_rehacer_sin_historial_es_error():
    assert "ERROR" in run_tool("escena_rehacer", "", _ctx())
