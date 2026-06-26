r"""
CYCLE 133 / H-V4-10g — regresión (versión HONESTA/ACOTADA tras verificación adversarial de 4 agentes): el keystone (valor=
ctrl×rel) sobrevive a un SUSTRATO ACOPLADO PERO sólo con controlabilidad de ALCANCE-POR-LA-RED + selección ADAPTATIVA
(reach_greedy robusto en todas las estructuras); el keystone LOCAL 129 (valor_local) recupera 129 sin acople pero FALLA bajo
acople (relevancia directa = proxy infiel del alcance, robusto con distractor); el reach naive top-K colapsa bajo redundancia
submodular; el reach de 1-hop falla bajo multi-hop. Generaliza el alcance-al-esfuerzo de 132 al acople del sustrato.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle133_coupled_substrate.py -q
"""
from cognia_x.experiments.exp117_coupled_substrate import run as X


def test_mixta_reach_por_red_mas_seleccion_adaptativa():
    grid = X.run(n_seeds=60)
    sm = X.build_summary(grid)
    assert sm["status"] == "mixta", sm["verdict"]
    assert sm["principle_robust"], sm["greedy_min"]            # reach_greedy robusto en TODAS las estructuras
    assert sm["local_ok_indep"], sm["local_base0"]            # κ=0 recupera 129
    assert sm["local_fails_coupled"], (sm["local_baseM"], sm["greedy_baseM"])   # local ciego al acople en base
    assert sm["topk_not_robust"], (sm["topk_redun"], sm["greedy_redun"])        # selección debe ser adaptativa
    assert sm["onehop_not_enough"], (sm["onehop_multi"], sm["greedy_multi"])    # controlabilidad de horizonte completo


def test_principle_robusto_todas_las_estructuras():
    grid = X.run(n_seeds=60)
    sm = X.build_summary(grid)
    assert sm["greedy_min"] > 0.85, sm["greedy_min"]
    for st in ("multihop", "redundant", "distractor"):
        assert grid[st]["reach_greedy"] > 0.85, (st, grid[st]["reach_greedy"])


def test_indep_recupera_129():
    # sin acople (κ=0) todos los criterios de control coinciden: el keystone lineal 129 vale cuando los modos son independientes
    grid = X.run(n_seeds=60)
    base0 = grid["base"][str(X.KAPPAS[0])]
    assert base0["valor_local"] > 0.90, base0
    assert base0["reach_greedy"] > 0.90 and base0["reach_topk"] > 0.90, base0


def test_local_falla_es_robusto_no_knife_edge():
    # la falla del LOCAL no es un filo de w_driver=0: con un DISTRACTOR (vanidad ctrl+rel-directo sin acople) sigue fallando
    grid = X.run(n_seeds=60)
    dist = grid["distractor"]
    assert dist["reach_greedy"] - dist["valor_local"] > 0.10, (dist["valor_local"], dist["reach_greedy"])
    # y el sweep de w_driver documenta el knife-edge: con fuga de relevancia directa el local SE RECUPERA
    wd0 = grid["wdriver"][str(X.W_DRIVER_SWEEP[0])]
    wd_hi = grid["wdriver"][str(X.W_DRIVER_SWEEP[-1])]
    assert wd0["valor_local"] < 0.60, wd0["valor_local"]            # w_driver=0 exacto: falla
    assert wd_hi["valor_local"] > 0.95, wd_hi["valor_local"]        # w_driver>0: se recupera


def test_reach_naive_colapsa_bajo_redundancia():
    # el criterio IMPLEMENTADO naive (top-K-standalone) NO es robusto: colapsa bajo redundancia submodular
    grid = X.run(n_seeds=60)
    redun = grid["redundant"]
    assert redun["reach_topk"] < 0.75, redun["reach_topk"]
    assert redun["reach_greedy"] > 0.95, redun["reach_greedy"]      # el greedy adaptativo se mantiene óptimo
