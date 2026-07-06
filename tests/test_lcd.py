"""
Regresion del pipeline mínimo LCD (corrida-2 tarea 5): plan -> escena -> render.
Determinista, sin modelo. Fija las 2 propiedades del paper que se demuestran en
CPU: control composicional exacto (§8.1) y editabilidad selectiva (§8.2).
"""
from cognia.lcd.planner import plan
from cognia.lcd.renderer import render
from cognia.lcd.scene import Scene
from cognia.lcd.eval import eval_compositional, eval_editability


def test_plan_dos_objetos_relacion():
    s = plan("a red cup on a blue table")
    names = sorted(o.name for o in s.objects)
    assert names == ["cup", "table"]
    cup, table = s.get("cup"), s.get("table")
    assert cup.color == (220, 60, 50) and table.color == (60, 110, 220)
    # 'on': la taza esta ENCIMA de la mesa (y menor) y ~centrada
    assert cup.y < table.y and abs(cup.x - table.x) < 0.25


def test_plan_relaciones_espaciales():
    s = plan("a green ball to the left of a yellow box")
    ball, box = s.get("ball"), s.get("box")
    assert ball is not None and box is not None
    assert ball.x < box.x           # a la izquierda


def test_control_composicional_100():
    n_ok, n, _ = eval_compositional()
    assert n_ok == n == 8           # exacto por construccion


def test_editabilidad_selectiva():
    ed = eval_editability()
    assert ed["edit_applied"] and ed["target_changed"] and ed["others_untouched"]


def test_edit_no_toca_otros():
    s = plan("a red cup on a blue table")
    tc = s.get("table").color
    assert s.edit("cup", color="green")
    assert s.get("cup").color == (70, 180, 90)
    assert s.get("table").color == tc     # la mesa NO cambio


def test_render_produce_imagen():
    s = plan("a sun above a house")
    img = render(s)
    assert img.size == (512, 512) and img.mode == "RGB"


def test_scene_json_roundtrip():
    s = plan("a red cup on a blue table")
    s2 = Scene.from_json(s.to_json())
    assert len(s2.objects) == len(s.objects)
    assert s2.get("cup").color == s.get("cup").color
