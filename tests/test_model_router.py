"""
Regresion del router de modelo por dificultad (corrida-2 tarea 4).

Fija: (1) el estimador de dificultad correlaciona con las etiquetas
easy<medium<hard de las tasks embebidas; (2) el umbral 0.30 rutea easy->3B
(barato) y hard->7B; (3) route_tasks parte bien.
"""
import statistics

from cognia.agent.model_router import (
    estimate_difficulty, pick_model, route_tasks,
)
from cognia_v3.eval.benchmark_code import TASKS


def test_dificultad_monotona_con_etiqueta():
    by = {"easy": [], "medium": [], "hard": []}
    for t in TASKS:
        by[t["difficulty"]].append(estimate_difficulty(t["prompt"]))
    me = statistics.mean(by["easy"])
    mm = statistics.mean(by["medium"])
    mh = statistics.mean(by["hard"])
    # el orden debe respetarse (easy < medium < hard)
    assert me < mm < mh, (me, mm, mh)
    # y en el rango [0,1]
    assert all(0.0 <= estimate_difficulty(t["prompt"]) <= 1.0 for t in TASKS)


def test_easy_va_barato_hard_va_caro():
    # NINGUNA easy debe ir al 7B (el 3B las resuelve; ahorrar es el punto)
    easy_to_7b = sum(1 for t in TASKS
                     if t["difficulty"] == "easy" and pick_model(t["prompt"]) == "7b")
    assert easy_to_7b == 0
    # ALGUNA hard debe ir al 7B
    hard_to_7b = sum(1 for t in TASKS
                     if t["difficulty"] == "hard" and pick_model(t["prompt"]) == "7b")
    assert hard_to_7b >= 1


def test_route_tasks_particiona():
    r = route_tasks(TASKS)
    p = r["partition"]
    assert len(p["3b"]) + len(p["7b"]) == len(TASKS)
    # la mayoria de las embebidas (easy/medium) va al barato
    assert len(p["3b"]) > len(p["7b"])
    # cada task tiene su dificultad registrada
    assert len(r["difficulty"]) == len(TASKS)


def test_pick_model_umbral():
    assert pick_model("hola", threshold=0.30) == "3b"
    # una tarea con muchas señales duras va al 7B
    dura = ("Implementa una funcion con programacion dinamica y memoizacion que "
            "encuentre la subsecuencia creciente mas larga de forma eficiente O(n log n), "
            "sin importar librerias, cuidando casos borde y overflow")
    assert estimate_difficulty(dura) >= 0.30
    assert pick_model(dura) == "7b"
