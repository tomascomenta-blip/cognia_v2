r"""
CYCLE 137 / H-V4-10k — regresión (APOYADA): el agente DESCUBRE el R-VALOR de un sustrato ACOPLADO de UN solo stream -- la
controlabilidad (b̂), el ACOPLE (Â por system-ID) y la relevancia (ŵ por credit-assignment)-, y los COMPONE en la REACH-relevancia
|b̂·(I-Â)^{-T}ŵ| que 133 mostró necesaria. El keystone LOCAL (b̂·ŵ) falla bajo acople; el reach COMPLETO es necesario; la
colinealidad del credit-assignment NO confunde ŵ. Unifica 128+133+134.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle137_coupled_discovery.py -q
"""
from cognia_x.experiments.exp121_coupled_discovery import run as X


def test_apoyada_descubre_el_rvalor_acoplado():
    grid = X.run(n_seeds=60)
    sm = X.build_summary(grid)
    assert sm["status"] == "apoyada", sm["verdict"]
    assert sm["indep_recovers"], (sm["k0_composed"], sm["k0_local"])
    assert sm["composed_recovers_hi"], sm["khi_composed"]
    assert sm["composed_robust_struct"], sm["struct_composed"]


def test_forma_necesaria_transpuesta_incorrecta_falla():
    # falsador anti-tautología: la transpuesta INCORRECTA (reach hacia adelante) FALLA -> composed≢oracle por construcción
    grid = X.run(n_seeds=60)
    sm = X.build_summary(grid)
    assert sm["wrongform_fails"], (sm["khi_composed"], sm["khi_composed_noT"])
    assert sm["khi_composed"] - sm["khi_composed_noT"] > 0.15, (sm["khi_composed"], sm["khi_composed_noT"])


def test_reach_net_sobre_control_puro_baseline_justo():
    # baseline JUSTO: la contribución NETA del reach es sobre control puro (|b̂|), no sobre el local que se auto-sabotea
    grid = X.run(n_seeds=60)
    sm = X.build_summary(grid)
    assert sm["reach_beats_ctrl"], sm["reach_net"]
    assert sm["reach_net"] > 0.15, sm["reach_net"]
    # el local cae por DEBAJO de control puro (se auto-sabotea bajo acople)
    assert sm["khi_local"] < sm["khi_ctrl_only"] + 0.05, (sm["khi_local"], sm["khi_ctrl_only"])


def test_composed_recupera_y_local_falla_bajo_acople():
    grid = X.run(n_seeds=60)
    bk = grid["by_kappa"]
    k0 = bk[str(X.KAPPAS[0])]; khi = bk[str(X.KAPPA_FIXED)]
    # κ=0: composed y local coinciden (recupera 134)
    assert k0["composed"] > 0.9 and k0["local"] > 0.9, (k0["composed"], k0["local"])
    # κ alto: composed recupera, el local FALLA por margen grande
    assert khi["composed"] > 0.9, khi["composed"]
    assert khi["composed"] - khi["local"] > 0.2, (khi["composed"], khi["local"])
    assert khi["corr_m"] > 0.9, khi["corr_m"]


def test_reach_completo_necesario_1hop_falla_en_multihop():
    grid = X.run(n_seeds=60)
    bs = grid["by_struct"]
    # en multihop (driver a 2 saltos) el reach de 1-salto FALLA, el completo recupera
    assert bs["multihop"]["composed"] > 0.9, bs["multihop"]["composed"]
    assert bs["multihop"]["composed"] - bs["multihop"]["reach_1hop"] > 0.15, bs["multihop"]
    # en base (1 salto) el 1-hop SÍ basta -> no es straw-man
    assert bs["base"]["reach_1hop"] > 0.9, bs["base"]["reach_1hop"]


def test_colinealidad_no_confunde_la_relevancia():
    # bajo acople fuerte el credit-assignment recupera la relevancia DIRECTA limpiamente (OLS sobre el estado completo)
    grid = X.run(n_seeds=60)
    khi = grid["by_kappa"][str(X.KAPPA_FIXED)]
    assert khi["corr_w"] > 0.9, khi["corr_w"]


def test_composed_converge_desde_abajo_no_oracle_relabeled():
    # el costo de datos está en estimar Â: a T bajo composed es genuinamente < oracle (NO oracle-relabeled)
    grid = X.run(n_seeds=60)
    gT = grid["by_T"]
    assert gT[str(X.TS[0])]["composed"] < 0.9, gT[str(X.TS[0])]["composed"]   # T chico: degradado
    assert gT[str(X.TS[-1])]["composed"] > 0.95, gT[str(X.TS[-1])]["composed"]  # T grande: recupera
