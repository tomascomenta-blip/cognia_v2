"""Regresion de las ops de modelado AI-nativas (Blender recreado): modeling.py
puro + tools_modeling.py sobre la escena. Plan Blender->lapiz."""
import cognia_x.lcd.tools_lcd as _lcd     # noqa: F401 -- registra base
import cognia_x.lcd.tools_modeling as _mod  # noqa: F401 -- registra modeling
from cognia.agent.tools import TOOLS, run_tool
from cognia_x.lcd import modeling


def _ctx():
    return {"working_memory": {}, "agent_state": {}}


# ── funciones puras (modeling.py) ────────────────────────────────────────

def test_ngon_lados():
    assert len(modeling.ngon(6)) == 6
    assert len(modeling.ngon(3)) == 3
    assert len(modeling.ngon(2)) == 3      # minimo 3


def test_subdivide_sube_conteo():
    sq = [[0, 0], [1, 0], [1, 1], [0, 1]]
    assert len(modeling.subdivide(sq, 1)) == 8      # 1 punto por arista
    assert len(modeling.subdivide(sq, 3)) == 16


def test_bevel_duplica_esquinas():
    sq = [[0, 0], [1, 0], [1, 1], [0, 1]]
    b = modeling.bevel(sq, 0.2)
    assert len(b) == 8                              # cada vertice -> 2


def test_smooth_redondea():
    sq = [[0, 0], [1, 0], [1, 1], [0, 1]]
    s = modeling.smooth(sq, 2)
    assert len(s) > len(sq)                         # Chaikin agrega puntos


def test_mirror_invierte():
    pts = [[0.3, 0.1], [-0.2, 0.4]]
    assert modeling.mirror(pts, "x") == [[-0.3, 0.1], [0.2, 0.4]]


def test_extrude_agrega_dos_vertices():
    sq = [[0, 0], [1, 0], [1, 1], [0, 1]]
    e = modeling.extrude_edge(sq, 0, 0.0, -0.5)
    assert len(e) == 6                              # +2 (la cara nueva)


def test_inset_encoge_hacia_centro():
    sq = [[0, 0], [1, 0], [1, 1], [0, 1]]
    ins = modeling.inset(sq, 0.5)
    # todos los puntos mas cerca del centro (0.5,0.5)
    for p in ins:
        assert 0.2 < p[0] < 0.8 and 0.2 < p[1] < 0.8


def test_array_n_copias():
    from cognia_x.lcd.scene import Obj
    o = Obj(name="banda", shape="rect", x=0.2, y=0.5, w=0.05, h=0.1)
    copias = modeling.array(o, 3, 0.1, 0.0)
    assert len(copias) == 3
    assert abs(copias[2].x - 0.4) < 1e-6


# ── tools ACCION ─────────────────────────────────────────────────────────

def test_tools_modeling_registradas():
    assert _mod.load_modeling_tools() == 8


def test_biselar_convierte_a_polygon():
    ctx = _ctx()
    run_tool("escena_crear", "a red cup on a blue table", ctx)
    out = run_tool("escena_biselar", "table | 0.2", ctx)
    assert "ERROR" not in out
    o = ctx["working_memory"]["_lcd_scene"]["escena"].get("table")
    assert o.shape == "polygon" and len(o.points) == 8   # rect(4)->bevel(8)


def test_poligono_hexagono():
    ctx = _ctx()
    run_tool("escena_crear", "a red cup on a blue table", ctx)
    out = run_tool("escena_poligono", "cup | 6", ctx)
    assert "ERROR" not in out and "6 lados" in out
    assert len(ctx["working_memory"]["_lcd_scene"]["escena"].get("cup").points) == 6


def test_array_reemplaza_por_copias():
    ctx = _ctx()
    run_tool("escena_crear", "a red cup on a blue table", ctx)
    n0 = len(ctx["working_memory"]["_lcd_scene"]["escena"].objects)
    out = run_tool("escena_array", "cup | 3 0.1 0", ctx)
    assert "ERROR" not in out
    # cup reemplazada por 3 copias -> +2 objetos netos
    assert len(ctx["working_memory"]["_lcd_scene"]["escena"].objects) == n0 + 2


def test_subdividir_y_suavizar_e2e():
    ctx = _ctx()
    run_tool("escena_crear", "a red cup on a blue table", ctx)
    run_tool("escena_poligono", "table | 4", ctx)
    assert "ERROR" not in run_tool("escena_subdividir", "table | 2", ctx)
    assert "ERROR" not in run_tool("escena_suavizar", "table | 2", ctx)


def test_error_objeto_inexistente():
    ctx = _ctx()
    run_tool("escena_crear", "a red cup on a blue table", ctx)
    assert "ERROR" in run_tool("escena_biselar", "avion | 0.2", ctx)
