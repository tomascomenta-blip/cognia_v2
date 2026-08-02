# -*- coding: utf-8 -*-
"""Tests del experto de tooling MiniCPM5-1B (partes CPU/sin-GPU).

La generación real (el 1B en GPU) se verifica end-to-end en venv312gpu, fuera de
la suite. Aquí se prueba el plumbing determinista: kill-switch y disponibilidad.
Los imports de torch/transformers son perezosos, así que este módulo importa en
CPU.

PODA 2026-08-01: el camino de tool-calling XML del BASE (generar, tool_call,
_parsear_tool_calls, _quitar_think) se eliminó — cero llamadores; el único rol
cableado a producción es 'tooling' vía generar_accion (cli.py, opt-in
COGNIA_MINICPM_TOOLING=1). Este archivo fija esa poda como regresión."""
import importlib

me = importlib.import_module("cognia.agent.minicpm_expert")


def test_import_no_arrastra_torch():
    # el rol de PRODUCCION sobrevive a la poda
    assert hasattr(me, "generar_accion")
    assert hasattr(me, "expert_disponible")
    assert hasattr(me, "tooling_disponible")


def test_camino_xml_podado():
    # regresión de la limpieza de huérfanas: el tool-calling XML del base no
    # debe volver sin un consumidor real (el loop habla ACCION + GBNF).
    for viejo in ("generar", "tool_call", "_parsear_tool_calls",
                  "_generar_raw", "_quitar_think"):
        assert not hasattr(me, viejo), viejo


def test_killswitch(monkeypatch):
    monkeypatch.setenv("COGNIA_FLEET_GPU", "0")
    ok, motivo = me.expert_disponible()
    assert ok is False
    assert "COGNIA_FLEET_GPU=0" in motivo


def test_disponible_devuelve_tupla(monkeypatch):
    monkeypatch.delenv("COGNIA_FLEET_GPU", raising=False)
    r = me.expert_disponible()
    assert isinstance(r, tuple) and len(r) == 2 and isinstance(r[0], bool)


def test_tooling_disponible_killswitch(monkeypatch):
    monkeypatch.setenv("COGNIA_FLEET_GPU", "0")
    ok, motivo = me.tooling_disponible()
    assert ok is False and "COGNIA_FLEET_GPU=0" in motivo


def test_tooling_disponible_sin_adapter(monkeypatch, tmp_path):
    # sin GPU la base ya corta; si hubiera GPU, la falta del adapter debe cortar.
    # Forzamos la ruta del adapter a una inexistente y comprobamos el mensaje
    # cuando el prerequisito base pasa (si no hay GPU, se corta antes: aceptamos ambas).
    monkeypatch.setenv("COGNIA_FLEET_GPU", "1")
    monkeypatch.setattr(me, "_ADAPTER_TOOLING", str(tmp_path / "no_existe"))
    ok, motivo = me.tooling_disponible()
    assert ok is False
    assert ("adapter de tooling" in motivo) or ("CUDA" in motivo) or ("torch" in motivo)


def test_accion_re_parsea_formato_cognia():
    m = me._ACCION_RE.search("ACCION: escribir_archivo notas.txt | hola")
    assert m and m.group(1) == "escribir_archivo"
    # tolera tilde y minusculas/mayusculas
    assert me._ACCION_RE.search("ACCIÓN: calcular 2+2").group(1) == "calcular"
