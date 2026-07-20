r"""
CYCLE 142 / H-V4-10n — regresión (MIXTA, post-verificación adversarial de 2 agentes). El producto R-VALOR (ctrl×rel, keystone 129)
importa bajo la INTERACCIÓN de capacidad escasa (K bajo) × disociación (ctrl≠rel); decae por ambos ejes; explica el K=1-load-bearing
de 139. ACOTADO: el decaimiento-en-K es parcialmente trivial (random también decae a K=D), es una RECOMBINACIÓN (forma universal),
y vale sólo para (b,w) graduados (binarios invierten el orden).

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle142_capacity_keystone.py -q
"""
from cognia_x.experiments.exp126_capacity_keystone import run as X


def _grid(n_seeds=120):
    return X.run(n_seeds)


def test_mixta_nucleo_y_acotaciones():
    grid = _grid(); sm = X.build_summary(grid)
    assert sm["status"] == "mixta", sm["verdict"]
    assert sm["core_organizing"], (sm["decays_where_present"], sm["dissoc_scales"], sm["kstar"])
    # las 3 acotaciones que bajan de APOYADA a MIXTA
    assert sm["random_also_decays"], sm["rand_decay"]          # decaimiento parcialmente trivial
    assert sm["is_recombination"], sm["universal_shape_maxdiff"]   # forma universal -> recombinación
    assert sm["binary_inverts"], (sm["binary_auc_anti"], sm["binary_auc_indep"])   # validity-limit


def test_nucleo_capacidad_x_disociacion():
    # la ventaja escala con la disociación: AUC anti > indep > corr
    grid = _grid(); sm = X.build_summary(grid)
    a = sm["auc_advantage"]
    assert a["anti"] > a["indep"] + 0.03 and a["indep"] > a["corr"] + 0.03, a
    # K* relativo a D escala con la disociación (anti >= indep >= corr)
    kr = sm["kstar_rel"]
    assert kr["anti"] >= kr["indep"] >= kr["corr"], kr


def test_decaimiento_es_parcialmente_trivial():
    # la (1-payoff) de random también decae a ~0 en K=D -> el 'vanishes@D' es genérico de top-K
    grid = _grid()
    rand = grid["anti"]["random"]
    assert (1.0 - rand[-1]) < 0.05, rand[-1]          # random llega a payoff~1 en K=D
    assert (1.0 - rand[0]) > 0.30, rand[0]            # random es malo a K=1 (hay algo que decae)


def test_forma_universal_recombinacion():
    # las curvas de ventaja anti/indep normalizadas por adv(K=1) son ~idénticas -> el eje-K es una forma universal
    grid = _grid(); sm = X.build_summary(grid)
    assert sm["universal_shape_maxdiff"] < 0.15, sm["universal_shape_maxdiff"]


def test_validity_limit_binario_invierte():
    # con (b,w) binarios el orden anti>indep se INVIERTE (el resultado vale sólo para marginales graduadas)
    grid = _grid(); sm = X.build_summary(grid)
    assert sm["binary_auc_anti"] <= sm["binary_auc_indep"] + 0.02, (sm["binary_auc_anti"], sm["binary_auc_indep"])


def test_producto_es_oracle_por_construccion():
    # el producto = valor verdadero -> payoff 1.0 a todo K (declarado; lo medido es el payoff de los factores-solos)
    grid = _grid()
    for name in ("anti", "indep", "corr"):
        assert all(p > 0.999 for p in grid[name]["product"]), (name, grid[name]["product"])
