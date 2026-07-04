"""
Regresion del harness de AUTO-PRUEBAS de escena (cognia_x/lcd/selfplay.py):
metrica de similitud + motor 'un agente intenta reproducir la escena objetivo'.
"""
from cognia_x.lcd.planner import plan
from cognia_x.lcd.scene import Obj, Scene
from cognia_x.lcd.selfplay import (
    attempt_reproduce, scripted_from_scene, similarity,
)


def test_similitud_identica_es_1():
    t = plan("a red cup on a blue table")
    assert similarity(t, plan("a red cup on a blue table"))["score"] == 1.0


def test_similitud_ordena_bien_los_casos():
    t = plan("a red cup on a blue table")
    casi = plan("a red cup on a blue table"); casi.get("cup").x = 0.55
    falta = Scene(objects=[t.get("table")])
    dist = plan("a green ball to the left of a yellow box")
    s_casi = similarity(casi, t)["score"]
    s_falta = similarity(falta, t)["score"]
    s_dist = similarity(dist, t)["score"]
    # identica > casi-igual > falta-objeto > distinta
    assert 1.0 > s_casi > s_falta > s_dist
    assert s_dist == 0.0


def test_similitud_color_penaliza():
    t = plan("a red cup on a blue table")
    otro = plan("a red cup on a blue table"); otro.edit("cup", color="green")
    s = similarity(otro, t)
    assert s["color"] == 0.5 and s["score"] < 1.0


def test_similitud_relacion_rota():
    t = plan("a red cup on a blue table")
    inv = plan("a red cup on a blue table"); inv.get("cup").y = 0.95  # taza abajo
    assert similarity(inv, t)["rel"] == 0.0


def test_scripted_agent_genera_acciones_de_agregar():
    t = plan("a red cup on a blue table")
    agent = scripted_from_scene(t)
    a1 = agent("", [], "")
    assert a1.startswith("escena_agregar")


def test_attempt_reproduce_con_runtool_mock():
    """Motor de auto-prueba con un run_tool MOCK que agrega objetos: el agente
    scripted reproduce el target -> similitud alta. Prueba el LAZO sin depender
    de las tools reales de edicion (que estan en otro archivo)."""
    import re
    from cognia_x.lcd.scene import SHAPES

    from cognia_x.lcd.scene import COLORS

    def mock_run_tool(name, args, ctx):
        scene = ctx["working_memory"]["_lcd_scene"]["escena"]
        if name == "escena_agregar":
            parts = re.split(r"\s*\|\s*", args, maxsplit=1)
            obj_name = parts[0].strip()
            kv = dict(re.findall(r"(\w+)=([\d.]+|\w+)", parts[1] if len(parts) > 1 else ""))
            shape, w, h = SHAPES.get(obj_name, ("rect", 0.15, 0.15))
            color = COLORS.get(str(kv.get("color", "")).lower(), (150, 150, 150))
            scene.add(Obj(name=obj_name, shape=shape,
                          x=float(kv.get("x", 0.5)), y=float(kv.get("y", 0.5)),
                          w=float(kv.get("w", w)), h=float(kv.get("h", h)), color=color))
            return f"RESULTADO escena_agregar: {obj_name} ok"
        return f"RESULTADO {name} ERROR: desconocida"

    target = plan("a red cup on a blue table")
    agent = scripted_from_scene(target)
    r = attempt_reproduce(target, "a red cup on a blue table", agent, mock_run_tool)
    assert r["built"]
    # reproduce las posiciones exactas -> IoU alto, obj_match perfecto
    assert r["similarity"]["obj_match"] == 1.0
    assert r["similarity"]["score"] > 0.9


def test_attempt_reproduce_agente_que_no_hace_nada():
    def noop(desc, hist, summ):
        return "FIN"
    t = plan("a red cup on a blue table")
    r = attempt_reproduce(t, "x", noop, lambda *a: "")
    assert r["similarity"]["score"] == 0.0     # escena vacia vs target
