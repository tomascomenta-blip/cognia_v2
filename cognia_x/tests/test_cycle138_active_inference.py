r"""
CYCLE 138 / H-V4-10l — regresión (MIXTA, post-verificación adversarial). PUENTE TEÓRICO válido: el keystone (valor=ctrl×rel) es el
LÍMITE binary+uniforme del término pragmático de la EFE (w²·v·ctrl). PERO la 'emergencia empírica' es TAUTOLÓGICA (efe_pragmatic =
la métrica del eval), el '+0.43 refinamiento' es artefacto de un canónico hand-tuned (mediana ~0 en configs aleatorias), y el
mecanismo w² es FALSO -- la corrección robusta/learnable es la varianza-prior v (w·v·ctrl), no el cuadrado.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle138_active_inference.py -q
"""
from cognia_x.experiments.exp122_active_inference import run as X


def test_mixta_puente_teorico_emergencia_tautologica():
    grid = X.run(n_seeds=120)
    sm = X.build_summary(grid)
    assert sm["status"] == "mixta", sm["verdict"]
    assert sm["bridge_holds"], (sm["bridge_binary"], sm["factors_fail"], sm["converges_below"])
    assert sm["efe_is_oracle"], sm["gn_efe"]                  # tautología: efe=oracle por construcción
    assert sm["refine_is_artifact"], sm["refine_median"]      # el refinamiento es artefacto (mediana ~0 en configs aleatorias)


def test_puente_teorico_keystone_es_limite_binary():
    # el keystone (w·ctrl) es el límite binary+uniforme de la EFE pragmática (w²·v·ctrl): identidad w²=w, v=1
    grid = X.run(n_seeds=120)
    bu = grid["known"]["binary_uniform"]
    assert abs(bu["efe_pragmatic"] - bu["keystone_lab"]) < 0.02, (bu["efe_pragmatic"], bu["keystone_lab"])
    assert bu["efe_pragmatic"] > 0.95, bu["efe_pragmatic"]


def test_refinamiento_es_artefacto_mediana_nula():
    # en configs graded ALEATORIAS el refinamiento efe-keystone es ~nulo (el +0.43 era un canónico hand-tuned)
    grid = X.run(n_seeds=120)
    rc = grid["randcfg"]
    assert rc["efe_minus_keystone"]["median"] < 0.02, rc["efe_minus_keystone"]


def test_correccion_robusta_es_v_no_el_cuadrado():
    # bajo params ESTIMADOS el cuadrado DAÑA: w·v·ctrl (v_correction) >= w²·v·ctrl (efe) en T finito
    grid = X.run(n_seeds=120)
    gnT = grid["by_T"]["graded_nonuniform"]
    mid = gnT[str(X.TS[2])]                                   # T=75
    assert mid["vcorr"] >= mid["efe"] - 0.005, (mid["vcorr"], mid["efe"])
    # y v_correction supera claramente al keystone (la varianza-prior v SÍ ayuda)
    assert mid["vcorr"] - mid["keystone"] > 0.10, (mid["vcorr"], mid["keystone"])


def test_factores_fallan_y_producto_learnable():
    # las factores simples fallan (la composición es necesaria) y el producto es learnable leakage-free (converge desde abajo)
    grid = X.run(n_seeds=120)
    gn = grid["known"]["graded_nonuniform"]
    for f in ("relevancia", "control", "prediccion"):
        assert gn["efe_pragmatic"] - gn[f] > 0.10, (f, gn[f])
    gnT = grid["by_T"]["graded_nonuniform"]
    assert gnT[str(X.TS[0])]["vcorr"] < 0.9 and gnT[str(X.TS[-1])]["vcorr"] > 0.9, "discovery no converge desde abajo"
