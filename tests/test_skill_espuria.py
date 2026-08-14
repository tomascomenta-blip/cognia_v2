# -*- coding: utf-8 -*-
"""La skill auto-capturada que hundió el camino feliz (2026-08-14).

CASO REAL, no inventado. El gate del repo (scripts/e2e_happy_path.py) pasó de
5/5 a 2-4/5 y las tareas terminaban con "presupuesto de 8 pasos agotado sin
cierre". Medido con brazos apareados sobre el mismo llama-server:

    HEAD con las 2 skills auto-capturadas      4/5, 2/5
    HEAD con las firmas nuevas apagadas        3/5, 4/5   (descarta las firmas)
    HEAD moviendo SOLO esas 2 skills           5/5
    BASE en worktree (que no las tenía)        5/5, 5/5

La traza lo mostró: para «escribí un archivo llamado nota.txt con el texto
exacto: bateria ok», el agente escribía nota.txt en el paso 1 —y a continuación
creaba largas.py y buscaba palabras.txt hasta agotar el presupuesto— porque se
le inyectaba la skill 'palabras-txt-tiene-palabra-por'.

Dos defectos, uno en cada punta, y este fichero cubre los dos:
  1. Se capturó como "procedimiento verificado" una traza de ATASCO (repetía
     escribir_archivo largas.py 3 veces y editar_archivo 2).
  2. Esa skill GANÓ el match con dos tokens genéricos ('escribi', 'txt'),
     porque su descripción es la tarea original entera y el score léxico es
     absoluto: más palabras = más probabilidad de llegar al mínimo.
"""
from __future__ import annotations

from cognia.agent.skill_capture import (build_skill_body, maybe_capture_skill,
                                        pasos_procedimentales)
from cognia.agent.skills import SkillSpec, find_skill

TAREA_GATE = "escribí un archivo llamado nota.txt con el texto exacto: bateria ok"

DESC_ESPURIA = ("palabras.txt tiene una palabra por línea. Hacé estas cuatro "
                "cosas: (1) escribí en largas.txt las palabras de MÁS de 5 le")


def _skill(nombre, desc, auto):
    return SkillSpec(name=nombre, description=desc, body="cuerpo",
                     source="/tmp/x.md", kind="cognia", auto_generated=auto)


# ── 1. El match: la espuria ya no secuestra una tarea que no es suya ────────

def test_la_skill_auto_capturada_no_se_aplica_a_una_tarea_ajena():
    """El caso exacto que rompió el gate. Solape = {'escribi', 'txt'}."""
    espuria = _skill("palabras-txt-tiene-palabra-por", DESC_ESPURIA, True)
    assert find_skill(TAREA_GATE, {espuria.name: espuria},
                      semantic_fallback=False) is None


def test_una_skill_CURADA_con_el_mismo_solape_si_se_aplica():
    """El endurecimiento pesa SOLO sobre las auto-capturadas: si castigara a
    todas, esto sería 'romper el match' y no 'corregir un sesgo'."""
    curada = _skill("palabras-txt-tiene-palabra-por", DESC_ESPURIA, False)
    assert find_skill(TAREA_GATE, {curada.name: curada},
                      semantic_fallback=False) is curada


def test_la_auto_capturada_sigue_ganando_cuando_la_tarea_SI_es_la_suya():
    """No se trata de apagar las skills auto-capturadas: con la tarea de
    verdad el solape es grande y tiene que dispararse."""
    espuria = _skill("palabras-txt-tiene-palabra-por", DESC_ESPURIA, True)
    suya = ("palabras.txt tiene una palabra por línea, escribí en largas.txt "
            "las palabras de más de 5 letras")
    assert find_skill(suya, {espuria.name: espuria},
                      semantic_fallback=False) is espuria


# ── 2. La captura: una traza de atasco no asciende a procedimiento ──────────

def _traza_atascada():
    """La forma real de la traza que produjo la skill espuria."""
    esc = {"action": "escribir_archivo", "args": "largas.py | def escribir_largas",
           "ok": True, "result_head": "OK"}
    edi = {"action": "editar_archivo", "args": "largas.py | <<<<<<< SEARCH",
           "ok": True, "result_head": "OK"}
    return [{"action": "leer_archivo", "args": "palabras.txt", "ok": True,
             "result_head": "hola"},
            esc, edi, dict(esc), dict(edi), dict(esc),
            {"action": "tests", "args": ".", "ok": True,
             "result_head": "3 passed in 0.1s"}]


def test_los_pasos_repetidos_no_cuentan_como_procedimiento():
    unicos = pasos_procedimentales(_traza_atascada())
    acciones = [(p["action"], p["args"]) for p in unicos]
    assert len(acciones) == len(set(acciones)), acciones
    assert len(unicos) == 4      # leer, escribir, editar, tests


def test_el_cuerpo_de_la_skill_no_repite_pasos():
    cuerpo = build_skill_body("tarea cualquiera", _traza_atascada())
    assert cuerpo.count("ACCION: escribir_archivo largas.py") == 1
    assert cuerpo.count("ACCION: editar_archivo largas.py") == 1


def test_una_traza_con_menos_de_4_pasos_DISTINTOS_no_se_captura():
    """Siete tool-calls 'ok' pero solo tres cosas hechas: no es una skill.

    Con el oráculo duro presente (tests verdes), antes esto se capturaba: el
    umbral miraba la cantidad de llamadas, no cuántas eran distintas.
    """
    traza = [p for p in _traza_atascada() if p["action"] != "leer_archivo"]
    assert len([p for p in traza if p["ok"]]) >= 4        # pasa el umbral viejo
    res = maybe_capture_skill("una tarea", traza)
    assert res["captured"] is False
    assert "DISTINTOS" in res["reason"], res


def test_una_traza_sana_se_sigue_capturando():
    """La contraprueba: sin esto, el fix podría ser 'no capturar nunca'."""
    traza = [{"action": "leer_archivo", "args": "a.txt", "ok": True,
              "result_head": "x"},
             {"action": "escribir_archivo", "args": "b.py | codigo", "ok": True,
              "result_head": "OK"},
             {"action": "ejecutar", "args": "python b.py", "ok": True,
              "result_head": "listo"},
             {"action": "tests", "args": ".", "ok": True,
              "result_head": "5 passed in 0.2s"}]
    assert len(pasos_procedimentales(traza)) == 4
