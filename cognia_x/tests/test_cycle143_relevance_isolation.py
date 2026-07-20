r"""
CYCLE 143 / H-V4-10o — regresión (MIXTA, post-verificación adversarial de 2 agentes). Bajo un sustrato cíclico con reach≠relevancia
y capacidad ESCASA K=1 + decoys, la relevancia es LOAD-BEARING (el agente aísla la reach-relevancia leakage-free). ACOTADO: EVAPORA
a K>=#drivers (el artefacto K=1 de 139), el cierre depende de los decoys (n_decoy=0 reproduce 139), y reach=oracle es tautológico.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle143_relevance_isolation.py -q
"""
from cognia_x.experiments.exp127_relevance_isolation import run as X


def _g(n_seeds=80):
    grid = X.run(n_seeds)
    return grid, X.build_summary(grid)


def test_mixta_nucleo_k1_y_acotaciones():
    grid, sm = _g()
    assert sm["status"] == "mixta", sm["verdict"]
    assert sm["core_k1"], (sm["reach"], sm["reach_minus_ctrl"], sm["reach_minus_rel"])
    # las acotaciones que bajan de APOYADA a MIXTA
    assert sm["evaporates_at_kfull"], sm["by_K"]               # evapora a K>=#drivers
    assert sm["nodecoy_reproduces_139"], sm["nodecoy_ones_break"]   # n_decoy=0 reproduce 139


def test_nucleo_k1_aisla_ambos_factores():
    grid, sm = _g()
    assert sm["reach"] > 0.85, sm["reach"]
    assert sm["reach_minus_ctrl"] > 0.15, sm["reach_minus_ctrl"]   # la relevancia añade
    assert sm["reach_minus_rel"] > 0.15, sm["reach_minus_rel"]     # la reach añade
    assert sm["shuffle_breaks"] and sm["ones_breaks"], (sm["shuffle_reach"], sm["ones_reach"])


def test_evapora_a_k_full_artefacto_k1_de_139():
    # a K>=#drivers, ctrl_only iguala a reach y ŵ≡unos deja de romper (el artefacto K=1 que 139 retractó)
    grid, sm = _g()
    ndrv = sm["n_drivers"]
    kfull = sm["by_K"][str(ndrv)]
    assert (kfull["reach"] - kfull["ctrl_only"]) < 0.10, (kfull["reach"], kfull["ctrl_only"])
    assert (kfull["reach"] - kfull["ones_reach"]) < 0.10, (kfull["reach"], kfull["ones_reach"])


def test_nodecoy_reproduce_139():
    # con n_decoy=0 (un solo driver), ŵ≡unos NO rompe -> reproduce 139 (el cierre depende de los decoys)
    grid, sm = _g()
    assert sm["nodecoy_ones_break"] < 0.10, sm["nodecoy_ones_break"]


def test_reach_es_oracle_por_construccion_y_rel_estructural():
    # reach con params verdaderos = oracle (tautológico); rel_only=0 estructural (b,w nunca co-localizados)
    grid, sm = _g()
    assert sm["rel_only"] < 0.05, sm["rel_only"]               # rel_only siempre cae fuera del soporte
    assert sm["reach"] > 0.95, sm["reach"]                     # reach recupera el oracle
