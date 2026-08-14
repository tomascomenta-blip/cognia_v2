# -*- coding: utf-8 -*-
"""Tests de scripts/banco_cerebro.py — el INSTRUMENTO, no el modelo (CPU puro).

POR QUE: este banco decide que cerebro sirve. Si sus postcondiciones aprueban a
quien no hizo la tarea, cada numero que produzca es ruido — y eso no es
hipotetico: la version del 2026-08-13 daba por buena la tarea m2 con un
`def resumen(): pass`, porque miraba la FORMA del fichero (que compile, que las
lineas esten) y nunca su comportamiento.

Nada de esto toca un modelo ni un llama-server: se escriben ficheros en un
workspace temporal y se llama a la postcondicion. Es exactamente lo que corre
`scripts\\banco_cerebro.py --dry-run`.
"""
import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def mod():
    ruta = REPO_ROOT / "scripts" / "banco_cerebro.py"
    spec = importlib.util.spec_from_file_location("banco_cerebro", ruta)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _post(mod, tid, escribir, tmp_path):
    tarea = next(t for t in mod.TAREAS if t["id"] == tid)
    ws = tmp_path / tid
    ws.mkdir()
    if tarea.get("preparacion"):
        tarea["preparacion"](ws)
    if escribir:
        escribir(ws)
    return tarea["postcondicion"](ws)


# ── El chequeo completo: golden aprueba, mentiroso y trampas reprueban ──

def test_autoverificacion_completa(mod):
    """Lo mismo que --dry-run: si esto falla, el banco no mide nada."""
    assert mod.autoverificar() is True


def test_todas_las_tareas_tienen_lo_que_promete_el_encargo(mod):
    ids = [t["id"] for t in mod.TAREAS]
    assert len(ids) == len(set(ids)) == 12
    for t in mod.TAREAS:
        assert t["dificultad"] in mod.PESOS
        assert callable(t["postcondicion"])
        assert t.get("pasos", 0) > 0
        assert t["id"] in mod.GOLDEN          # sin golden no hay autoverificacion
    assert sum(mod.PESOS[t["dificultad"]] for t in mod.TAREAS) == 26


# ── Regresion del agujero real (m2 aprobaba codigo roto) ───────────────

@pytest.mark.parametrize("nota,fuente", [
    ("resumen vaciada", 'TIMEOUT = 60\nREINTENTOS = 3\nHOST = "127.0.0.1"\n\n'
                        'def resumen():\n    return ""\n'),
    ("resumen con pass", 'TIMEOUT = 60\nREINTENTOS = 3\nHOST = "127.0.0.1"\n\n'
                         'def resumen():\n    pass\n'),
    ("TIMEOUT reasignado abajo",
     'TIMEOUT = 60\nREINTENTOS = 3\nHOST = "127.0.0.1"\n\n'
     'def resumen():\n    return f"{HOST}:{TIMEOUT} x{REINTENTOS}"\nTIMEOUT = 30\n'),
])
def test_m2_reprueba_lo_que_compila_pero_no_funciona(mod, tmp_path, nota, fuente):
    assert _post(mod, "m2_editar_sin_romper",
                 lambda ws: (ws / "config.py").write_text(fuente, encoding="utf-8"),
                 tmp_path) is False


def test_m2_aprueba_la_edicion_minima(mod, tmp_path):
    assert _post(mod, "m2_editar_sin_romper",
                 mod.GOLDEN["m2_editar_sin_romper"], tmp_path) is True


def test_m2_aprueba_si_deja_el_viejo_comentado(mod, tmp_path):
    fuente = mod._CONFIG_PY.replace("TIMEOUT = 30",
                                    "# TIMEOUT = 30 (viejo)\nTIMEOUT = 60")
    assert _post(mod, "m2_editar_sin_romper",
                 lambda ws: (ws / "config.py").write_text(fuente, encoding="utf-8"),
                 tmp_path) is True


# ── d4: elegir fuente. La prosa no puede costar 3 puntos ───────────────

def test_d4_aprueba_con_prosa_que_menciona_un_dos(mod, tmp_path):
    """'not _tiene_numero(txt, 2.0)' reprobaba a quien resolvio bien y explico:
    cualquier '2' del texto ('la otra fuente tiene 2 valores') tumbaba la tarea."""
    assert _post(mod, "d4_elegir_fuente",
                 lambda ws: (ws / "promedio.txt").write_text(
                     "promedio 18.0 (use datos_b; datos_a corrupto, 2 lineas)",
                     encoding="utf-8"), tmp_path) is True


def test_d4_reprueba_la_fuente_corrupta(mod, tmp_path):
    assert _post(mod, "d4_elegir_fuente",
                 lambda ws: (ws / "promedio.txt").write_text("2.0\n",
                                                             encoding="utf-8"),
                 tmp_path) is False


# ── El contrato con el arnes de barrido (comparar_modelos.py) ──────────

def test_medir_acepta_los_kwargs_que_pasa_el_arnes(mod):
    """comparar_modelos.correr_banco() hace exactamente esto y llama fn(**kwargs).
    Con la firma vieja (correr_banco, `ai` posicional) salia TypeError y el
    barrido anotaba 'banco FALLO' para todos los modelos."""
    import inspect
    acepta = set(inspect.signature(mod.medir).parameters)
    assert {"url", "puerto"} <= acepta


def test_el_puntaje_que_lee_el_arnes_es_el_graduado(mod):
    """comparar_modelos._puntaje se queda con el ULTIMO 'N/M' del stdout."""
    import re
    salida = ("BANCO CEREBRO: 5/12 OK (13/26 pts) en 31.0 min\n"
              "  facil    3/3\n  media    2/4\n  dificil  0/5\n"
              "FALLARON: m1, d1\n"
              "RESULTADO BANCO CEREBRO: 13/26 pts\n")
    a, b = re.findall(r"(\d+)\s*/\s*(\d+)", salida)[-1]
    assert (a, b) == ("13", "26")
