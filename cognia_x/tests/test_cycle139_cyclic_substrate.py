r"""
CYCLE 139 / H-V4-10m — regresión (MIXTA, post-verificación adversarial de 4 agentes). Bajo un sustrato con CICLOS (radio
espectral->1) la reach de estado-estacionario CRUDA del 137 ((I-A)^{-1}) es NUMÉRICAMENTE FRÁGIL cerca de radio 1 (mis-rankea bajo
K=1); una REGULARIZACIÓN (horizonte-finito R_H=Σ_{k<H}A^k, descontada, o cap-de-autovalor SIN H) la cura; es la forma (reach_inf_TRUE
también falla); estimable leakage-free. PERO 4 overclaims retractados: (1) el gap es artefacto de K=1 (evapora a K>=2); (2) la forma
horizonte NO es privilegiada (reach_inf_reg SIN H la iguala); (3) la relevancia es COLINEAL (ŵ≡unos no colapsa a ctrl_only); (4)
'falla cerca de radio 1' requiere competencia de escalas temporales (con un único lazo reach_inf no falla).

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle139_cyclic_substrate.py -q
"""
from cognia_x.experiments.exp123_cyclic_substrate import run as X


def test_mixta_nucleo_y_overclaims():
    grid = X.run(n_seeds=120)
    sm = X.build_summary(grid)
    assert sm["status"] == "mixta", sm["verdict"]
    assert sm["core"], (sm["inf_fragile_crude"], sm["form_not_estimation"], sm["regularization_fixes"],
                        sm["estimable"], sm["zeroA_collapses"], sm["sim_ok"])
    assert sm["n_overclaims"] >= 2, sm["n_overclaims"]


def test_nucleo_reach_inf_cruda_fragil_es_la_forma():
    # NÚCLEO: a radio bajo reach_inf reproduce 137; a radio→1 la reach-∞ cruda cae y ES LA FORMA (reach_inf_true también)
    grid = X.run(n_seeds=120)
    rlo = grid["by_rho"][str(X.SPECRADII[0])]; rhi = grid["by_rho"][str(X.RHO_FIXED)]
    assert rlo["reach_inf"] > 0.90, rlo["reach_inf"]                                   # radio bajo: coincide
    assert (rhi["reach_H"] - rhi["reach_inf"]) > 0.15, (rhi["reach_H"], rhi["reach_inf"])
    assert (rhi["reach_H_true"] - rhi["reach_inf_true"]) > 0.15, (rhi["reach_H_true"], rhi["reach_inf_true"])
    # la regularización la cura (descontada y cap-de-autovalor SIN H)
    assert rhi["reach_disc"] > rhi["reach_inf"] + 0.15, (rhi["reach_disc"], rhi["reach_inf"])
    assert rhi["reach_inf_reg"] > rhi["reach_inf"] + 0.15, (rhi["reach_inf_reg"], rhi["reach_inf"])


def test_overclaim1_gap_es_artefacto_de_k1():
    # el gap titular EVAPORA a K>=2 (reach_inf identifica el conjunto correcto; sólo invierte #1<->#2)
    grid = X.run(n_seeds=120)
    sm = X.build_summary(grid)
    assert sm["gap_k1_true"] > 0.15, sm["gap_k1_true"]
    assert sm["gap_k2_true"] < 0.05, sm["gap_k2_true"]
    assert sm["gap_is_k1_artifact"], (sm["gap_k1_true"], sm["gap_k2_true"])


def test_overclaim2_forma_horizonte_no_privilegiada():
    # una reach-∞ regularizada por cap-de-autovalor SIN conocer H IGUALA a reach_H -> la novedad es regularizar, no el horizonte
    grid = X.run(n_seeds=120)
    rhi = grid["by_rho"][str(X.RHO_FIXED)]
    assert abs(rhi["reach_inf_reg"] - rhi["reach_H"]) < 0.05, (rhi["reach_inf_reg"], rhi["reach_H"])


def test_overclaim3_relevancia_colineal():
    # control nulo CORRECTO: ŵ≡unos (relevancia ELIMINADA) NO colapsa a ctrl_only -> la relevancia es colineal/no-aislada
    grid = X.run(n_seeds=120)
    ones = grid["ctrl"]["ones"]["reach_H"]; cto = grid["by_rho"][str(X.RHO_FIXED)]["ctrl_only"]
    assert ones > cto + 0.20, (ones, cto)


def test_overclaim4_requiere_competencia():
    # 'falla cerca de radio 1' requiere COMPETENCIA: con un único lazo reach_inf no falla (slow_only / fast_only)
    grid = X.run(n_seeds=120)
    bs = grid["by_struct"]
    assert bs["slow_only"]["reach_inf"] > 0.85, bs["slow_only"]["reach_inf"]
    assert bs["fast_only"]["reach_inf"] > 0.85, bs["fast_only"]["reach_inf"]


def test_estimable_leakage_free_y_dinamica_loadbearing():
    # reach_H se estima de un stream y converge desde abajo; Â:=0 colapsa (la dinámica es load-bearing); sim_check valida la física
    grid = X.run(n_seeds=120)
    sm = X.build_summary(grid)
    assert sm["Tmax_reachH"] - sm["Tmin_reachH"] > 0.05 and sm["Tmax_reachH"] > 0.90, (sm["Tmin_reachH"], sm["Tmax_reachH"])
    assert sm["zeroA_collapses"], sm["zeroA_reach_H"]
    assert grid["sim_check_lo"] > 0.9 and grid["sim_check_hi"] > 0.9, (grid["sim_check_lo"], grid["sim_check_hi"])
