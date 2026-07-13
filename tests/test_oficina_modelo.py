# -*- coding: utf-8 -*-
"""Vínculo tarea↔modelo en la oficina (para pintar por identidad)."""
from cognia.oficina.estado import Oficina


def test_crear_tarea_con_modelo(tmp_path):
    o = Oficina(str(tmp_path / "of.json"))
    tid = o.crear_tarea("trabajador", "codear", "hace x", modelo="qwen35_4b")
    t = o.data["tareas"][tid]
    assert t["modelo"] == "qwen35_4b"


def test_set_modelo(tmp_path):
    o = Oficina(str(tmp_path / "of.json"))
    tid = o.crear_tarea("trabajador", "t", "d")
    assert o.data["tareas"][tid]["modelo"] is None
    assert o.set_modelo(tid, "qwen3_4b") is True
    assert o.data["tareas"][tid]["modelo"] == "qwen3_4b"
    assert o.set_modelo("noexiste", "x") is False


def test_modelo_persiste_en_snapshot(tmp_path):
    o = Oficina(str(tmp_path / "of.json"))
    tid = o.crear_tarea("trabajador", "t", "d", modelo="vibethinker15b")
    snap = o.snapshot()
    assert snap["tareas"][tid]["modelo"] == "vibethinker15b"
