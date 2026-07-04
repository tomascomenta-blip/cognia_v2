"""
Regresion de las tools AI-nativas de EDICION TOTAL de LCD
(cognia_x/lcd/tools_lcd.py): agregar/quitar/duplicar/mover/rotar/escalar/
material/capa/camara/luz/fondo/alinear/distribuir/relacionar/fisica.
Plan 12 (herramientas virtuales para IAs) — misma familia que test_lcd_tools.py
(escena_crear/editar/consultar), ahora con la escena ya viva.
"""
import cognia_x.lcd.tools_lcd as lcd_tools   # noqa: F401 -- registra las tools
from cognia.agent.tools import run_tool, TOOLS
from cognia_x.lcd.physics import physics_report
from cognia_x.lcd.tools_lcd import _relation_ok


def _ctx():
    return {"working_memory": {}, "agent_state": {}}


def _crear(ctx, desc="a red cup on a blue table"):
    """escena_crear + devuelve la escena viva (cup sobre table, plan de reglas)."""
    out = run_tool("escena_crear", desc, ctx)
    assert "ERROR" not in out
    return ctx["working_memory"]["_lcd_scene"]["escena"]


# ── registro ──────────────────────────────────────────────────────────────

def test_tools_nuevas_registradas_en_el_registry():
    nuevas = ("escena_agregar", "escena_quitar", "escena_duplicar", "escena_mover",
              "escena_rotar", "escena_escalar", "escena_material", "escena_capa",
              "escena_camara", "escena_luz", "escena_fondo", "escena_alinear",
              "escena_distribuir", "escena_relacionar", "escena_fisica")
    for t in nuevas:
        assert t in TOOLS, f"{t} no registrada"


def test_load_lcd_tools_cuenta_todas():
    assert lcd_tools.load_lcd_tools() == 21   # 6 originales + 15 de edicion total


# ── escena_agregar ────────────────────────────────────────────────────────

def test_escena_agregar_sube_el_conteo_y_setea_atributos():
    ctx = _ctx()
    scene = _crear(ctx)
    n0 = len(scene.objects)
    out = run_tool("escena_agregar", "silla | x=0.2 y=0.6 color=green", ctx)
    assert "ERROR" not in out
    assert len(scene.objects) == n0 + 1
    o = scene.get("silla")
    assert o is not None
    assert abs(o.x - 0.2) < 1e-9 and abs(o.y - 0.6) < 1e-9
    assert o.color == (70, 180, 90)          # verde


def test_escena_agregar_usa_defaults_de_shapes():
    ctx = _ctx()
    scene = _crear(ctx)
    run_tool("escena_agregar", "libro | x=0.1 y=0.1", ctx)
    o = scene.get("libro")
    assert (o.shape, round(o.w, 2), round(o.h, 2)) == ("rect", 0.12, 0.16)


def test_escena_agregar_vocabulario_desconocido_es_error():
    ctx = _ctx()
    _crear(ctx)
    out = run_tool("escena_agregar", "objetoxyz | x=0.1 y=0.1", ctx)
    assert "ERROR" in out


def test_escena_agregar_sin_escena_activa():
    assert "ERROR" in run_tool("escena_agregar", "silla | x=0.1 y=0.1", _ctx())


# ── escena_quitar ─────────────────────────────────────────────────────────

def test_escena_quitar_baja_el_conteo():
    ctx = _ctx()
    scene = _crear(ctx)
    n0 = len(scene.objects)
    out = run_tool("escena_quitar", "cup", ctx)
    assert "ERROR" not in out
    assert len(scene.objects) == n0 - 1
    assert scene.get("cup") is None


def test_escena_quitar_inexistente_es_error():
    ctx = _ctx()
    _crear(ctx)
    assert "ERROR" in run_tool("escena_quitar", "avion", ctx)


# ── escena_duplicar ───────────────────────────────────────────────────────

def test_escena_duplicar_desambigua_la_key():
    ctx = _ctx()
    scene = _crear(ctx)
    n0 = len(scene.objects)
    out = run_tool("escena_duplicar", "cup | dx=0.1 dy=0.0", ctx)
    assert "ERROR" not in out
    assert len(scene.objects) == n0 + 1
    dup = scene.get("cup_2")
    assert dup is not None
    assert abs(dup.x - (scene.get("cup").x)) > 1e-9   # desplazado del original


def test_escena_duplicar_inexistente_es_error():
    ctx = _ctx()
    _crear(ctx)
    assert "ERROR" in run_tool("escena_duplicar", "avion", ctx)


# ── escena_mover ──────────────────────────────────────────────────────────

def test_escena_mover_ambos_ejes():
    ctx = _ctx()
    scene = _crear(ctx)
    out = run_tool("escena_mover", "cup | x=0.1 y=0.2", ctx)
    assert "ERROR" not in out
    o = scene.get("cup")
    assert abs(o.x - 0.1) < 1e-9 and abs(o.y - 0.2) < 1e-9


def test_escena_mover_un_solo_eje_no_toca_el_otro():
    ctx = _ctx()
    scene = _crear(ctx)
    y0 = scene.get("cup").y
    run_tool("escena_mover", "cup | x=0.15", ctx)
    o = scene.get("cup")
    assert abs(o.x - 0.15) < 1e-9
    assert o.y == y0


def test_escena_mover_inexistente_es_error():
    ctx = _ctx()
    _crear(ctx)
    assert "ERROR" in run_tool("escena_mover", "avion | x=0.1", ctx)


# ── escena_rotar ──────────────────────────────────────────────────────────

def test_escena_rotar_cambia_rotation():
    ctx = _ctx()
    scene = _crear(ctx)
    out = run_tool("escena_rotar", "cup | 45", ctx)
    assert "ERROR" not in out
    assert scene.get("cup").rotation == 45.0


def test_escena_rotar_no_numerico_es_error():
    ctx = _ctx()
    _crear(ctx)
    assert "ERROR" in run_tool("escena_rotar", "cup | mucho", ctx)


# ── escena_escalar ────────────────────────────────────────────────────────

def test_escena_escalar_multiplica_w_y_h():
    ctx = _ctx()
    scene = _crear(ctx)
    o = scene.get("cup")
    w0, h0 = o.w, o.h
    out = run_tool("escena_escalar", "cup | 2.0", ctx)
    assert "ERROR" not in out
    assert abs(o.w - w0 * 2.0) < 1e-9
    assert abs(o.h - h0 * 2.0) < 1e-9


def test_escena_escalar_factor_invalido_es_error():
    ctx = _ctx()
    _crear(ctx)
    assert "ERROR" in run_tool("escena_escalar", "cup | 0", ctx)
    assert "ERROR" in run_tool("escena_escalar", "cup | -1", ctx)


# ── escena_material ───────────────────────────────────────────────────────

def test_escena_material_edita_el_atributo():
    ctx = _ctx()
    scene = _crear(ctx)
    out = run_tool("escena_material", "table | madera", ctx)
    assert "ERROR" not in out
    assert scene.get("table").material == "madera"


def test_escena_material_no_listado_avisa_pero_no_falla():
    ctx = _ctx()
    scene = _crear(ctx)
    out = run_tool("escena_material", "table | chocolate", ctx)
    assert "ERROR" not in out           # acepta con aviso, no es un fallo
    assert scene.get("table").material == "chocolate"


def test_escena_material_inexistente_es_error():
    ctx = _ctx()
    _crear(ctx)
    assert "ERROR" in run_tool("escena_material", "avion | madera", ctx)


# ── escena_capa ───────────────────────────────────────────────────────────

def test_escena_capa_frente_y_fondo():
    ctx = _ctx()
    scene = _crear(ctx)
    zmax = max(o.z for o in scene.objects)
    run_tool("escena_capa", "cup | frente", ctx)
    assert scene.get("cup").z == zmax + 1
    zmin = min(o.z for o in scene.objects)
    run_tool("escena_capa", "table | fondo", ctx)
    assert scene.get("table").z == zmin - 1


def test_escena_capa_z_explicito():
    ctx = _ctx()
    scene = _crear(ctx)
    out = run_tool("escena_capa", "cup | z=7", ctx)
    assert "ERROR" not in out
    assert scene.get("cup").z == 7


# ── escena_camara ─────────────────────────────────────────────────────────

def test_escena_camara_edita_ancho_y_alto():
    ctx = _ctx()
    scene = _crear(ctx)
    out = run_tool("escena_camara", "| width=800 height=600", ctx)
    assert "ERROR" not in out
    assert scene.width == 800 and scene.height == 600


# ── escena_luz ────────────────────────────────────────────────────────────

def test_escena_luz_edita_light_dir():
    ctx = _ctx()
    scene = _crear(ctx)
    out = run_tool("escena_luz", "| 0.3,0.9", ctx)
    assert "ERROR" not in out
    assert scene.light_dir == (0.3, 0.9)


# ── escena_fondo ──────────────────────────────────────────────────────────

def test_escena_fondo_por_nombre_de_color():
    ctx = _ctx()
    scene = _crear(ctx)
    out = run_tool("escena_fondo", "| azul", ctx)
    assert "ERROR" not in out
    assert scene.background == (60, 110, 220)


def test_escena_fondo_por_rgb():
    ctx = _ctx()
    scene = _crear(ctx)
    out = run_tool("escena_fondo", "| 10,20,30", ctx)
    assert "ERROR" not in out
    assert scene.background == (10, 20, 30)


# ── escena_alinear ────────────────────────────────────────────────────────

def test_escena_alinear_deja_el_borde_comun():
    ctx = _ctx()
    scene = _crear(ctx)
    run_tool("escena_agregar", "silla | x=0.2 y=0.3", ctx)
    run_tool("escena_agregar", "libro | x=0.5 y=0.5", ctx)
    run_tool("escena_agregar", "caja | x=0.8 y=0.7", ctx)
    out = run_tool("escena_alinear", "silla,libro,caja | top", ctx)
    assert "ERROR" not in out
    tops = {round(scene.get(n).y - scene.get(n).h / 2, 6)
            for n in ("silla", "libro", "caja")}
    assert len(tops) == 1


def test_escena_alinear_inexistente_es_error():
    ctx = _ctx()
    _crear(ctx)
    assert "ERROR" in run_tool("escena_alinear", "cup,avion | top", ctx)


# ── escena_distribuir ─────────────────────────────────────────────────────

def test_escena_distribuir_equiespacia():
    ctx = _ctx()
    scene = _crear(ctx)
    run_tool("escena_agregar", "silla | x=0.1 y=0.5", ctx)
    run_tool("escena_agregar", "libro | x=0.9 y=0.5", ctx)
    run_tool("escena_agregar", "caja | x=0.4 y=0.5", ctx)   # desordenado a proposito
    out = run_tool("escena_distribuir", "silla,libro,caja | horizontal", ctx)
    assert "ERROR" not in out
    xs = sorted(scene.get(n).x for n in ("silla", "libro", "caja"))
    gaps = [round(xs[i + 1] - xs[i], 6) for i in range(len(xs) - 1)]
    assert len(set(gaps)) == 1                # mismo espaciado entre consecutivos
    assert abs(xs[0] - 0.1) < 1e-9 and abs(xs[-1] - 0.9) < 1e-9   # extremos preservados


# ── escena_relacionar ─────────────────────────────────────────────────────

def test_escena_relacionar_satisface_la_relacion():
    ctx = _ctx()
    scene = _crear(ctx)
    run_tool("escena_agregar", "silla | x=0.1 y=0.1", ctx)
    out = run_tool("escena_relacionar", "silla | left_of | table", ctx)
    assert "ERROR" not in out
    assert _relation_ok(scene, "silla", "left_of", "table")


def test_escena_relacionar_todas_las_relaciones_quedan_ok():
    for rel in ("on", "left_of", "right_of", "above", "below"):
        ctx = _ctx()
        scene = _crear(ctx)
        run_tool("escena_agregar", "silla | x=0.1 y=0.1", ctx)
        out = run_tool("escena_relacionar", f"silla | {rel} | table", ctx)
        assert "ERROR" not in out, f"{rel}: {out}"
        assert _relation_ok(scene, "silla", rel, "table"), f"{rel} no quedo satisfecha"


def test_escena_relacionar_objeto_inexistente_es_error():
    ctx = _ctx()
    _crear(ctx)
    assert "ERROR" in run_tool("escena_relacionar", "avion | on | table", ctx)


def test_escena_relacionar_relacion_invalida_es_error():
    ctx = _ctx()
    _crear(ctx)
    assert "ERROR" in run_tool("escena_relacionar", "cup | dentro_de | table", ctx)


# ── escena_fisica ─────────────────────────────────────────────────────────

def test_escena_fisica_asienta_objeto_flotando():
    ctx = _ctx()
    scene = _crear(ctx)
    run_tool("escena_agregar", "caja | x=0.5 y=0.1", ctx)   # flota (nada la sostiene ahi)
    assert physics_report(scene)["plausible"] is False
    out = run_tool("escena_fisica", "", ctx)
    assert "ERROR" not in out
    assert "plausible=True" in out
    assert physics_report(scene)["plausible"] is True


# ── errores comunes: sin escena activa (las 15 tools nuevas) ─────────────

def test_tools_nuevas_sin_escena_activa_dan_error():
    ctx = _ctx()
    casos = [
        ("escena_agregar", "silla | x=0.1 y=0.1"),
        ("escena_quitar", "cup"),
        ("escena_duplicar", "cup"),
        ("escena_mover", "cup | x=0.1"),
        ("escena_rotar", "cup | 10"),
        ("escena_escalar", "cup | 2"),
        ("escena_material", "cup | madera"),
        ("escena_capa", "cup | frente"),
        ("escena_camara", "| width=100 height=100"),
        ("escena_luz", "| 0.1,0.2"),
        ("escena_fondo", "| azul"),
        ("escena_alinear", "cup,table | top"),
        ("escena_distribuir", "cup,table | horizontal"),
        ("escena_relacionar", "cup | on | table"),
        ("escena_fisica", ""),
    ]
    for name, args in casos:
        out = run_tool(name, args, ctx)
        assert "ERROR" in out, f"{name} deberia fallar sin escena activa: {out}"
