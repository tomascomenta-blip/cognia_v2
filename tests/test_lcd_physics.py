"""
Regresion de la fisica local determinista de LCD (cognia_x/lcd/physics.py):
gravedad/soporte, colision/no-overlap, apilamiento, estabilidad. Sin GPU.
"""
from cognia_x.lcd.physics import (
    GROUND, is_stable, physics_report, settle, support_of,
)
from cognia_x.lcd.scene import Obj, Scene


def _obj(name, x, y, w=0.12, h=0.12, shape="rect"):
    return Obj(name=name, shape=shape, x=x, y=y, w=w, h=h)


def test_objeto_solo_cae_al_suelo():
    s = Scene(objects=[_obj("pelota", 0.5, 0.2, shape="circle")])
    settle(s)
    assert abs(s.objects[0].bottom() - GROUND) < 0.01


def test_objeto_flotando_se_detecta_y_se_corrige():
    s = Scene(objects=[_obj("caja", 0.5, 0.1)])
    assert physics_report(s)["plausible"] is False   # flotando
    settle(s)
    assert physics_report(s)["plausible"] is True


def test_apilamiento_objeto_chico_sobre_soporte_ancho():
    # mesa ancha abajo + taza chica arriba -> la taza descansa sobre la mesa
    s = Scene(objects=[
        _obj("mesa", 0.5, 0.3, w=0.55, h=0.12),
        _obj("taza", 0.5, 0.05, w=0.10, h=0.12, shape="ellipse"),
    ])
    settle(s)
    mesa, taza = s.get("mesa"), s.get("taza")
    assert abs(mesa.bottom() - GROUND) < 0.01           # mesa en el suelo
    assert support_of(s, taza) is mesa                  # taza sobre la mesa
    assert physics_report(s)["plausible"]


def test_objeto_ancho_no_se_apoya_sobre_uno_angosto():
    # una mesa (ancha) NO descansa sobre un libro (angosto): cae al suelo
    s = Scene(objects=[
        _obj("libro", 0.5, 0.9, w=0.12, h=0.16),
        _obj("mesa", 0.5, 0.3, w=0.55, h=0.12),
    ])
    settle(s)
    assert support_of(s, s.get("mesa")) is None         # la mesa va al suelo


def test_colision_horizontal_se_separa():
    # dos cajas al mismo nivel encimadas -> se empujan aparte
    s = Scene(objects=[
        _obj("caja1", 0.48, 0.9, w=0.16, h=0.16),
        _obj("caja2", 0.52, 0.9, w=0.16, h=0.16),
    ])
    settle(s)
    r = physics_report(s)
    assert r["solapando"] == []
    assert abs(s.get("caja1").x - s.get("caja2").x) >= (0.16 - 0.02)


def test_objetos_flotantes_no_caen():
    # sol/nube no les aplica gravedad (cielo)
    s = Scene(objects=[_obj("sol", 0.5, 0.15, shape="circle"),
                       _obj("pelota", 0.5, 0.15, shape="circle")])
    settle(s)
    assert s.get("sol").y == 0.15                       # el sol no se movio
    assert s.get("pelota").bottom() > 0.5               # la pelota cayo


def test_estabilidad_centro_fuera_del_soporte():
    # objeto cuyo centro se sale del soporte -> inestable
    s = Scene(objects=[
        _obj("base", 0.3, 0.9, w=0.14, h=0.10),
        _obj("encima", 0.6, 0.7, w=0.10, h=0.10),   # centro lejos de la base
    ])
    # forzar 'encima' apoyado sobre 'base' en altura pero descentrado
    s.get("encima").y = s.get("base").top() - 0.05
    assert is_stable(s, s.get("encima")) is False


def test_settle_es_determinista():
    def build():
        return Scene(objects=[_obj("mesa", 0.5, 0.3, w=0.55, h=0.12),
                              _obj("taza", 0.48, 0.05, w=0.10, h=0.12),
                              _obj("libro", 0.55, 0.1, w=0.12, h=0.16)])
    a, b = build(), build()
    settle(a); settle(b)
    assert [(o.name, round(o.x, 4), round(o.y, 4)) for o in a.objects] == \
           [(o.name, round(o.x, 4), round(o.y, 4)) for o in b.objects]


def test_settle_reporta_convergencia():
    s = Scene(objects=[_obj("caja", 0.5, 0.1)])
    rep = settle(s)
    assert rep["iters"] >= 1 and rep["moved"] >= 1 and rep["unstable"] == []
