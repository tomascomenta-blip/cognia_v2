r"""
CYCLE 146 / H-V4-10r — regresión (MIXTA, post-verificación adversarial de 2 agentes). La factorización PRODUCTO ctrl×rel es un sesgo
inductivo de BAJA CAPACIDAD útil para ESTIMAR el valor bajo ESCASEZ (bias-variance) PERO condicional a la alineación-con-el-producto
(con residuo ORTOGONAL hunde al estimador, no free lunch); anti-tautología débil (misespecificación ~colineal); decisión confundida
por la suficiencia de w·c.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle146_inductive_bias.py -q
"""
from cognia_x.experiments.exp130_inductive_bias import run as X


def _g(n_seeds=120):
    grid = X.run(n_seeds)
    return grid, X.build_summary(grid)


def test_mixta_nucleo_y_reacotacion():
    grid, sm = _g()
    assert sm["status"] == "mixta", sm["verdict"]
    assert sm["core_estimator"], (sm["mse_struct"][0], sm["mse_flex"][0])
    # las acotaciones que bajan de APOYADA a MIXTA
    assert sm["conditional_on_alignment"], sm["by_misspec"]   # se hunde con residuo ortogonal
    assert sm["weak_antitaut"], sm["colinearity_prod2"]       # anti-tautología débil


def test_nucleo_struct_gana_bajo_escasez_alineado():
    # bajo escasez (N chico) y alineado al producto, STRUCT bate a FLEX (sobreajuste) y ADD (sin producto) en MSE
    grid, sm = _g()
    assert sm["mse_struct"][0] < sm["mse_flex"][0] * 0.7, (sm["mse_struct"][0], sm["mse_flex"][0])
    assert sm["mse_struct"][0] < sm["mse_add"][0] * 0.7, (sm["mse_struct"][0], sm["mse_add"][0])
    # FLEX alcanza bajo abundancia (bias-variance)
    assert sm["mse_flex"][-1] <= sm["mse_struct"][-1] + 0.0005, (sm["mse_struct"][-1], sm["mse_flex"][-1])


def test_condicional_a_la_alineacion_ortogonal_hunde():
    # con misespecificación ORTOGONAL al producto, STRUCT es el PEOR aprendiz (el prior de baja capacidad se vuelve sesgo)
    grid, sm = _g()
    for form in ("w_only", "wmc2"):
        m = grid["by_misspec"][form]["mse"]
        assert m["struct"] > m["flex"], (form, m["struct"], m["flex"])


def test_anti_tautologia_debil_colinealidad_alta():
    # la misespecificación prod2 está ~colineal con la única feature de STRUCT (w·c) -> sesgo irreducible minúsculo por diseño
    grid, sm = _g()
    assert sm["colinearity_prod2"] > 0.85, sm["colinearity_prod2"]


def test_decision_confundida_suficiencia_y_pairwise():
    # top-K fácil no discrimina; en pairwise STRUCT gana con prod2 pero colapsa con ortogonal (suficiencia de w·c, no robustez)
    grid, sm = _g()
    assert sm["struct_pairwise_wins_aligned"], grid["by_n"][str(sm["NS"][0])]["pairwise"]
    assert sm["struct_pairwise_sinks_ortho"], grid["by_misspec"]["w_only"]["pairwise"]
