"""Regresion de la ampliacion del modelo de escena (scene.py): id/rotation/
material, add/remove/duplicate, mas formas, roundtrip JSON compat."""
from cognia_x.lcd.scene import DENSITY, SHAPES, Obj, Scene


def test_add_desambigua_keys_duplicadas():
    s = Scene()
    s.add(Obj(name="cup", shape="ellipse", x=0.3, y=0.5, w=0.1, h=0.1))
    o2 = s.add(Obj(name="cup", shape="ellipse", x=0.6, y=0.5, w=0.1, h=0.1))
    assert o2.key() == "cup_2"                  # segunda 'cup' desambiguada
    assert len(s.objects) == 2


def test_remove():
    s = Scene(objects=[Obj(name="mesa", shape="rect", x=0.5, y=0.7, w=0.5, h=0.1)])
    assert s.remove("mesa") is True
    assert s.get("mesa") is None
    assert s.remove("inexistente") is False


def test_duplicate_desplaza_y_no_pisa():
    s = Scene(objects=[Obj(name="caja", shape="rect", x=0.4, y=0.6, w=0.16, h=0.16)])
    c = s.duplicate("caja", dx=0.1)
    assert c is not None and c.key() == "caja_2"
    assert abs(c.x - 0.5) < 1e-6                 # desplazada +0.1
    assert c.z > s.get("caja").z


def test_get_por_id_y_por_name():
    a = Obj(name="cup", shape="ellipse", x=0.3, y=0.5, w=0.1, h=0.1, id="cup_A")
    s = Scene(objects=[a])
    assert s.get("cup_A") is a
    assert s.get("cup") is a


def test_edit_rotation_y_material():
    s = Scene(objects=[Obj(name="mesa", shape="rect", x=0.5, y=0.7, w=0.5, h=0.1)])
    assert s.edit("mesa", rotation=45.0, material="madera")
    assert s.get("mesa").rotation == 45.0 and s.get("mesa").material == "madera"


def test_roundtrip_json_con_campos_nuevos():
    s = Scene(objects=[Obj(name="taza", shape="ellipse", x=0.5, y=0.5, w=0.1, h=0.12,
                           rotation=30.0, material="vidrio", id="taza_1")])
    s2 = Scene.from_json(s.to_json())
    o = s2.get("taza_1")
    assert o.rotation == 30.0 and o.material == "vidrio" and o.id == "taza_1"


def test_from_json_compat_escena_vieja_sin_campos_nuevos():
    # escena guardada antes de rotation/material/id no debe romper
    viejo = '{"width":512,"height":512,"objects":[{"name":"mesa","shape":"rect","x":0.5,"y":0.7,"w":0.5,"h":0.1,"color":[60,110,220]}]}'
    s = Scene.from_json(viejo)
    assert s.get("mesa").rotation == 0.0 and s.get("mesa").material == ""


def test_vocabulario_ampliado():
    for k in ("bottle", "laptop", "clock", "cat", "window", "shelf"):
        assert k in SHAPES
    assert DENSITY.get("mesa", 1.0) > DENSITY.get("cup", 1.0)   # mesa mas pesada
