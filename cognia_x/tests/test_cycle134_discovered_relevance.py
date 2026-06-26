r"""
CYCLE 134 / H-V4-10h — regresión (versión HONESTA tras verificación adversarial de 4 agentes): el agente DESCUBRE el R-VALOR
COMPLETO (ambos factores del keystone valor=ctrl×rel) de UN solo stream de experiencia-acción -- controlabilidad del mapa
acción->estado (128) y relevancia del mapa estado->meta (credit assignment). valor_ambos bate a cada factor solo y converge al
oracle. DOS EJES de fallo COMPLEMENTARIOS: la controlabilidad es ACTION-gated (Var(u)>0) pero barata; la relevancia es el cuello
del COSTO DE DATOS (escala con el ruido de la meta) y requiere meta lineal-descomponible.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle134_discovered_relevance.py -q
"""
from cognia_x.experiments.exp118_discovered_relevance import run as X


def test_apoyada_descubre_ambos_factores():
    grid = X.run(n_seeds=60)
    sm = X.build_summary(grid)
    assert sm["status"] == "apoyada", sm["verdict"]
    assert sm["core_holds"], (sm["beats_ctrl"], sm["beats_rel"], sm["converges"], sm["grows"])
    assert sm["ctrl_action_gated"], (sm["corr_b_noaction"], sm["corr_b_action"])
    assert sm["rel_data_gated"], sm["rel_minus_ctrl_cost"]


def test_valor_ambos_bate_a_cada_factor_y_converge():
    grid = X.run(n_seeds=60)
    sm = X.build_summary(grid)
    tmax = str(X.TS[-1])
    r = grid["by_T"][tmax]
    assert r["valor_ambos"] > r["ctrl_solo"] + 0.08, r
    assert r["valor_ambos"] > r["rel_solo"] + 0.08, r
    assert r["valor_ambos"] > 0.95, r["valor_ambos"]                      # converge al oracle
    # genuinamente peor que oracle a T bajo (NO oracle relabeled, cierra el confound de 133)
    assert grid["by_T"][str(X.TS[0])]["valor_ambos"] < 0.95, grid["by_T"][str(X.TS[0])]["valor_ambos"]


def test_eje1_controlabilidad_action_gated():
    # a σ_u=0 la controlabilidad NO se identifica (necesita Var(u)>0); valor_ambos cae al azar; se recupera al actuar
    grid = X.run(n_seeds=60)
    su0 = grid["by_su"][str(X.SIGMA_US[0])]
    suHi = grid["by_su"][str(X.SIGMA_US[-1])]
    assert su0["corr_b"] < 0.40, su0["corr_b"]
    assert suHi["corr_b"] > 0.80, suHi["corr_b"]
    assert su0["valor_ambos"] < grid["random_baseline"] + 0.15, (su0["valor_ambos"], grid["random_baseline"])


def test_eje2_relevancia_es_cuello_de_costo_de_datos():
    # a ruido de meta alto, la ablación que estima ctrl rinde ~1 mientras la que estima rel se desploma (rel = el cuello)
    grid = X.run(n_seeds=60)
    sg_hi = grid["by_sg"][str(X.SIGMA_GS[-1])]
    assert sg_hi["valor_ctrl_relverd"] > 0.95, sg_hi["valor_ctrl_relverd"]      # la ctrl nunca es el cuello
    assert sg_hi["valor_rel_ctrlverd"] < sg_hi["valor_ctrl_relverd"] - 0.10, sg_hi   # la rel sí


def test_caveats_excitacion_pasiva_y_meta_lineal():
    grid = X.run(n_seeds=60)
    # sin excitación pasiva de los modos relevantes (s_rel=0, σ_u=0) la relevancia tampoco se estima (colapso simétrico)
    sr0 = grid["by_srel"][str(X.S_RELS[-1])]
    srD = grid["by_srel"][str(X.S_RELS[0])]
    assert srD["corr_w"] > 0.80 and sr0["corr_w"] < 0.40, (srD["corr_w"], sr0["corr_w"])
    # bajo meta PAR (G=Σw·x²) el credit-assignment lineal falla y valor_ambos cae a azar
    assert grid["by_goal"]["even"]["corr_w"] < 0.40, grid["by_goal"]["even"]["corr_w"]
    assert grid["by_goal"]["linear"]["valor_ambos"] > 0.95, grid["by_goal"]["linear"]["valor_ambos"]
