r"""
CYCLE 145 / H-V4-10q — regresión (MIXTA, post-verificación adversarial de 2 agentes). Bajo capacidad CONTINUA (water-filling) la
ventaja del criterio de VALOR sobre el mejor factor-solo SOBREVIVE a presupuesto escaso y ESCALA con la disociación -> NO es
específica del top-K discreto. RE-ACOTADO: escaso-continuo ES CONCENTRADO (~soft top-k) -> el K=1 se reinterpreta como
concentración-bajo-escasez, no se disuelve; residual permanente; decaimiento g-dependiente (g=√a plana).

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle145_continuous_capacity.py -q
"""
from cognia_x.experiments.exp129_continuous_capacity import run as X


def _g(n_seeds=120):
    grid = X.run(n_seeds)
    return grid, X.build_summary(grid)


def test_mixta_nucleo_y_reacotacion():
    grid, sm = _g()
    assert sm["status"] == "mixta", sm["verdict"]
    assert sm["core"], (sm["cont_survives"], sm["dissoc_both"])
    # las acotaciones que bajan de APOYADA a MIXTA
    assert sm["scarce_is_concentrated"], sm["pr_scarce"]      # escaso-continuo es soft top-k
    assert sm["sqrt_flat"], sm["adv_cont_sqrt"]               # decaimiento g-dependiente


def test_nucleo_sobrevive_continuo_y_escala_con_disociacion():
    # la ventaja del valor sobrevive presupuesto escaso bajo capacidad continua, y NO es discreto-específica
    grid, sm = _g()
    assert sm["adv_cont"]["anti"][0] > 0.10, sm["adv_cont"]["anti"][0]
    assert sm["adv_cont"]["indep"][0] > 0.05, sm["adv_cont"]["indep"][0]
    # escala con la disociación: AUC anti > indep > corr
    assert sm["auc_cont"]["anti"] > sm["auc_cont"]["indep"] > sm["auc_cont"]["corr"], sm["auc_cont"]


def test_escaso_continuo_es_concentrado_softtopk():
    # a presupuesto escaso el water-filling concentra (ratio de participación bajo) -> winner-take-all blando
    grid, sm = _g()
    assert sm["pr_scarce"] < 2.5, sm["pr_scarce"]            # ~soft top-2
    assert sm["pr_abund"] > sm["pr_scarce"] + 2.0, (sm["pr_scarce"], sm["pr_abund"])   # se esparce al crecer B


def test_decaimiento_g_dependiente_sqrt_plana():
    # con g=√a (marginal infinita en 0) la ventaja es invariante en B (no decae) -> el paralelo continuo≈discreto es g-dependiente
    grid, sm = _g()
    cs = sm["adv_cont_sqrt"]["anti"]
    assert abs(cs[0] - cs[-1]) < 0.03, (cs[0], cs[-1])
    # mientras la continua con g=log SÍ decae sustancialmente
    cl = sm["adv_cont"]["anti"]
    assert (cl[0] - cl[-1]) > 0.15, (cl[0], cl[-1])


def test_residual_permanente_vs_discreta_trivial():
    # la continua (log) NO llega a 0; la discreta llega a 0 sólo en K=D (trivial select-all)
    grid, sm = _g()
    assert sm["cont_residual"] > 0.04, sm["cont_residual"]   # residual permanente continuo
    assert sm["adv_disc"]["anti"][-1] < 0.02, sm["adv_disc"]["anti"][-1]   # discreta=0 a K=D (trivial)
