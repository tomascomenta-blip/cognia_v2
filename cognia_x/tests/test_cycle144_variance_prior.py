r"""
CYCLE 144 / H-V4-10p — regresión (MIXTA, post-verificación adversarial de 2 agentes). Mi hipótesis (w·v·ctrl es la elección robusta
que bate a AMBOS -keystone y efe-) REFUTADA: la forma robusta a través de los regímenes es la EFE-completa w²·v·ctrl. 'incluir v' es
casi definicional (el oracle contiene v) + v̂=Var(x) contaminado por el control (daña a baja-het); el cuadrado es REGIME-DEPENDENT
(daña con ŵ ruidoso -138 confirmado-, ayuda a baja-het).

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle144_variance_prior.py -q
"""
from cognia_x.experiments.exp128_variance_prior import run as X


def _g(n_seeds=120):
    grid = X.run(n_seeds)
    return grid, X.build_summary(grid)


def test_mixta_mapa_de_regimen():
    grid, sm = _g()
    assert sm["status"] == "mixta", sm["verdict"]
    assert sm["v_modulates"], sm["v_pays_strong_clean"]
    # las acotaciones que refutan mi hipótesis
    assert sm["square_harms_noisy"], sm["square_harms_noisy_sgmax"]      # 138 confirmado con ŵ ruidoso
    assert sm["efe_dominates"], "la EFE-completa domina el eje"          # la forma robusta es w²·v·ctrl


def test_cuadrado_dania_con_w_ruidoso_138_confirmado():
    # con σ_g alto (ŵ ruidoso) el cuadrado DAÑA: v_corr > efe (138 confirmado, no refutado)
    grid, sm = _g()
    sg_hi = grid["by_sigma_g"][str(X.SIGMA_GS[-1])]
    assert (sg_hi["v_corr"] - sg_hi["efe"]) > 0.03, (sg_hi["v_corr"], sg_hi["efe"])
    # con σ_g bajo (ŵ limpio) es ~wash
    sg_lo = grid["by_sigma_g"][str(X.SIGMA_GS[0])]
    assert abs(sg_lo["v_corr"] - sg_lo["efe"]) < 0.03, (sg_lo["v_corr"], sg_lo["efe"])


def test_cuadrado_ayuda_a_baja_heterogeneidad():
    # a baja heterogeneidad estimada, efe (cuadrado completo) bate a v_corr -> el cuadrado AYUDA (regime-dependent)
    grid, sm = _g()
    lowh = grid["by_het_est_fine"][str(X.HET_FINE[1])]
    assert (lowh["efe"] - lowh["v_corr"]) > 0.02, (lowh["efe"], lowh["v_corr"])


def test_vhat_contaminado_por_control_y_dania_baja_het():
    # v̂=Var(x) está correlacionado con b² (contaminación por control) y DAÑA a baja heterogeneidad (keystone > v_corr)
    grid, sm = _g()
    assert sm["corr_vhat_b2"] > 0.1, sm["corr_vhat_b2"]
    assert sm["vhat_harms_lowhet"], sm["vhat_lowhet_penalty"]


def test_incluir_v_es_definicional():
    # 'v_corr bate al keystone' bajo params clean es definicional: el oracle (w²·v·ctrl) contiene v
    grid, sm = _g()
    assert sm["v_pays_strong_clean"] > 0.10, sm["v_pays_strong_clean"]   # existe la 'ventaja' clean
    # pero en el régimen ESTIMADO a baja heterogeneidad se invierte (v̂ contaminado daña)
    lowh = grid["by_het_est_fine"][str(X.HET_FINE[0])]
    assert lowh["v_corr"] < lowh["keystone"], (lowh["v_corr"], lowh["keystone"])
