# -*- coding: utf-8 -*-
"""Tests del motor de animación (F5): matemática determinista, sin GPU ni navegador."""
import importlib
import math

eng = importlib.import_module("cognia.anim.engine")


def _rig():
    return {
        "fps": 10,
        "bones": [
            {"name": "root", "parent": None, "x": 0, "y": 0, "rot": 0, "sx": 1, "sy": 1},
            {"name": "brazo", "parent": "root", "x": 10, "y": 0, "rot": 0, "sx": 1, "sy": 1},
        ],
        "slots": [
            {"name": "mano", "bone": "brazo", "asset": "m", "x": 0, "y": 0, "z": 1, "w": 20, "h": 20},
        ],
        "animations": {
            "swing": {"duration": 1.0, "loop": True,
                      "tracks": {"brazo": {"rot": [{"t": 0, "v": 0}, {"t": 1.0, "v": 90}]},
                                 "root": {"x": [{"t": 0, "v": 0}, {"t": 1.0, "v": 100}]}}},
        },
    }


def test_mat_trs_identidad():
    assert eng.mat_trs(0, 0, 0, 1, 1) == (1, 0, 0, 1, 0, 0)


def test_mat_trs_traslacion_y_rotacion():
    # rot 90 grados: (1,0) -> (0,1)
    a, b, c, d, e, f = eng.mat_trs(5, 7, 90, 1, 1)
    x, y = 1, 0
    assert math.isclose(a * x + c * y + e, 5, abs_tol=1e-9)
    assert math.isclose(b * x + d * y + f, 8, abs_tol=1e-9)   # 7 + 1


def test_mat_mul_composicion():
    p = eng.mat_trs(10, 0, 0, 1, 1)     # traslada +10 en x
    c = eng.mat_trs(0, 0, 90, 1, 1)     # rota 90
    m = eng.mat_mul(p, c)
    # punto (1,0): rota -> (0,1), luego traslada -> (10,1)
    a, b, cc, d, e, f = m
    assert math.isclose(a * 1 + cc * 0 + e, 10, abs_tol=1e-9)
    assert math.isclose(b * 1 + d * 0 + f, 1, abs_tol=1e-9)


def test_sample_extremos_y_medio():
    keys = [{"t": 0, "v": 0}, {"t": 1.0, "v": 10}]
    assert eng._sample(keys, -1, None) == 0        # antes -> primer valor
    assert eng._sample(keys, 2, None) == 10        # después -> último valor
    assert math.isclose(eng._sample(keys, 0.5, None), 5)   # linear medio


def test_sample_easing_smoothstep():
    keys = [{"t": 0, "v": 0}, {"t": 1.0, "v": 10, "ease": "ease"}]
    # smoothstep en 0.5 -> 0.5 exacto; en 0.25 < lineal
    assert math.isclose(eng._sample(keys, 0.5, None), 5, abs_tol=1e-9)
    assert eng._sample(keys, 0.25, None) < 2.5


def test_posar_t0_setup():
    capas = eng.posar(_rig(), "swing", 0.0)
    assert len(capas) == 1 and capas[0]["slot"] == "mano"
    # en t=0: root x=0, brazo x=10 rot=0 -> mano en (10,0)
    m = capas[0]["m"]
    assert math.isclose(m[4], 10, abs_tol=1e-4)
    assert math.isclose(m[5], 0, abs_tol=1e-4)


def test_posar_fk_compone_padre_e_hijo():
    # en t=1 (==0 por loop) es setup; probamos t=0.5: root x=50, brazo rot=45
    capas = eng.posar(_rig(), "swing", 0.5)
    m = capas[0]["m"]
    # traslado del root (50) + brazo local (10,0) rotado 45 desde root:
    # world = translate(50) ∘ rotate(45)@root? root no rota; brazo hereda root.
    # root world = translate(50,0). brazo local = translate(10,0)*rot(45).
    # mano en origen de brazo -> world tx = 50 + 10 = 60 aprox (rot no mueve el origen)
    assert math.isclose(m[4], 60, abs_tol=1e-4)


def test_posar_loop_envuelve():
    r = _rig()
    a = eng.posar(r, "swing", 0.0)
    b = eng.posar(r, "swing", 1.0)   # loop dur=1 -> t=0
    assert a[0]["m"] == b[0]["m"]


def test_bake_estructura():
    baked = eng.bake(_rig(), "swing")
    assert baked["fps"] == 10 and baked["loop"] is True
    assert len(baked["frames"]) == 10        # 1.0s * 10fps
    assert baked["frames"][0][0]["asset"] == "m"
    # cada capa lleva matriz de 6 y tamaño
    c = baked["frames"][0][0]
    assert len(c["m"]) == 6 and c["w"] == 20 and c["h"] == 20


def test_posar_ordena_por_z():
    r = _rig()
    r["slots"].append({"name": "fondo", "bone": "root", "asset": "f", "z": -5, "w": 5, "h": 5})
    capas = eng.posar(r, "swing", 0.0)
    assert [c["slot"] for c in capas] == ["fondo", "mano"]   # z -5 antes que z 1
