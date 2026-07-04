"""Regresion de figuras detalladas + edicion de vertices/figuras (plan 12 pulido).
Verifica que la taza/mesa/plato tienen drawer detallado, el polygon dibuja desde
vertices custom, y las tools escena_forma/escena_vertices editan la figura."""
import cognia_x.lcd.tools_lcd as _lcd   # noqa: F401 -- registra las tools
from cognia.agent.tools import TOOLS, run_tool
from cognia_x.lcd.detailed_shapes import DETAILED, detailed_drawer
from cognia_x.lcd.renderer import render
from cognia_x.lcd.scene import Obj, Scene


def _ctx():
    return {"working_memory": {}, "agent_state": {}}


def test_taza_tiene_figura_detallada():
    assert "cup" in DETAILED
    assert detailed_drawer("taza") is not None      # sinonimo es -> cup
    assert detailed_drawer("cup") is not None
    assert detailed_drawer("pelota") is None        # sin drawer detallado


def test_render_taza_no_crashea_y_produce_imagen():
    s = Scene(objects=[Obj(name="taza", shape="ellipse", x=0.5, y=0.5, w=0.3, h=0.3,
                           color=(220, 60, 50))])
    img = render(s, labels=False)
    assert img.size == (512, 512)


def test_render_labels_toggle():
    s = Scene(objects=[Obj(name="taza", shape="ellipse", x=0.5, y=0.5, w=0.2, h=0.2)])
    # con y sin labels ambos renderizan sin error (el pixel exacto no se fija)
    assert render(s, labels=True).size == render(s, labels=False).size


def test_tools_forma_y_vertices_registradas():
    assert "escena_forma" in TOOLS and "escena_vertices" in TOOLS
    assert _lcd.load_lcd_tools() == 23      # 21 + forma + vertices


def test_escena_vertices_define_poligono():
    ctx = _ctx()
    run_tool("escena_crear", "a red cup on a blue table", ctx)
    out = run_tool("escena_vertices", "cup | 0,-0.5 0.5,0 0,0.5 -0.5,0", ctx)
    assert "ERROR" not in out and "4 vertices" in out
    cup = ctx["working_memory"]["_lcd_scene"]["escena"].get("cup")
    assert cup.shape == "polygon" and len(cup.points) == 4


def test_escena_vertices_valida_minimo_y_formato():
    ctx = _ctx()
    run_tool("escena_crear", "a red cup on a blue table", ctx)
    assert "ERROR" in run_tool("escena_vertices", "cup | 0,0 1,1", ctx)       # <3
    assert "ERROR" in run_tool("escena_vertices", "cup | 0,0 x,y 1,1", ctx)   # mal formado


def test_escena_forma_cambia_la_figura():
    ctx = _ctx()
    run_tool("escena_crear", "a red cup on a blue table", ctx)
    out = run_tool("escena_forma", "cup | triangle", ctx)
    assert "ERROR" not in out
    assert ctx["working_memory"]["_lcd_scene"]["escena"].get("cup").shape == "triangle"
    assert "ERROR" in run_tool("escena_forma", "cup | hexagono", ctx)   # invalida


def test_poligono_desde_vertices_renderiza():
    s = Scene(objects=[Obj(name="cristal", shape="polygon", x=0.5, y=0.5, w=0.3, h=0.3,
                           color=(60, 110, 220),
                           points=[[0, -0.5], [0.5, 0], [0, 0.5], [-0.5, 0]])])
    assert render(s, labels=False).size == (512, 512)


def test_roundtrip_json_preserva_vertices():
    s = Scene(objects=[Obj(name="cristal", shape="polygon", x=0.5, y=0.5, w=0.3, h=0.3,
                           points=[[0, -0.5], [0.5, 0], [0, 0.5]])])
    s2 = Scene.from_json(s.to_json())
    assert s2.get("cristal").points == [[0, -0.5], [0.5, 0], [0, 0.5]]


# ── fidelidad de render: supersampling + shading + lapiz ──────────────────

def test_supersampling_no_crashea_y_mantiene_tamano():
    s = Scene(objects=[Obj(name="lapiz", shape="rect", x=0.5, y=0.5, w=0.8, h=0.1)])
    img = render(s, labels=False, scale=3)
    assert img.size == (512, 512)      # baja de 3x a la resolucion pedida


def test_lapiz_tiene_figura_detallada():
    assert detailed_drawer("lapiz") is not None
    assert detailed_drawer("pencil") is not None


def test_cylinder_gradient_da_volumen():
    from cognia_x.lcd.shading import cylinder_gradient
    import numpy as np
    patch = cylinder_gradient((240, 195, 40), 40, 20, axis="y")
    arr = np.array(patch)
    # el sombreado varia a lo largo del eje y (no es color plano)
    col_top = arr[2, 20, :3].astype(int)
    col_bot = arr[17, 20, :3].astype(int)
    assert abs(int(col_top.sum()) - int(col_bot.sum())) > 20


def test_specular_streak_tiene_pico():
    from cognia_x.lcd.shading import specular_streak
    import numpy as np
    st = specular_streak(20, 40, pos=0.3, width=0.08, axis="y")
    alpha = np.array(st)[:, 10, 3]
    assert alpha.max() > 100 and alpha[0] < alpha.max()   # pico interior


def test_lapiz_render_no_crashea_con_shading():
    s = Scene(objects=[Obj(name="lapiz", shape="rect", x=0.5, y=0.5, w=0.82, h=0.11)])
    img = render(s, labels=False, scale=2)
    assert img.size == (512, 512)
