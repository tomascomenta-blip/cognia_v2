r"""
CYCLE 141 / H-V4-9h — regresión (POWERED, MIXTA post-verificación adversarial de 3 agentes). Intentó resolver el underpowered de
la MIXTA de 140 corriendo el lazo torch real a N=8. SOBREVIVE: la ventaja de RANKING base-rate-INVARIANTE del durable EXISTE. NO
SOBREVIVE (cazado por la verificación): la SIGNIFICANCIA es FRÁGIL (sign-test no-paramétrico NO significativo, magnitud diluyéndose
con N), el 'base-rate emparejado' es FALSO (la defensa es invariancia empírica corr(nc,auroc)≈0), y el 'mecanismo crece/previene el
colapso' es ARTEFACTO del cero-estructural de la ronda-1 (sin ella la pendiente flipea; el efecto real es una ventaja INMEDIATA que
se erosiona). Como X.run es un lazo torch lento, la regresión valida la LÓGICA DE VEREDICTO de build_summary sobre per_seed sintético.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle141_decisional_powered.py -q
"""
import numpy as np

from cognia_x.experiments.exp125_decisional_powered import run as X


def _mk_per_seed(auroc_gap, nc_durable=220, nc_naive=215, nseed=8, nrounds=8, grow=True, jitter=0.008, neg_seeds=0):
    """per_seed sintético: durable AUROC = naive + auroc_gap; la ronda 0 (=ronda 1 del lazo) es SIEMPRE gap 0 (cero estructural,
    ambos brazos idénticos pre-divergencia); si grow, el gap CRECE en las rondas 1..N-1. neg_seeds: cuántos seeds tienen gap
    NEGATIVO (para simular el caso frágil 7/8 del dato real)."""
    per = []
    for s in range(nseed):
        jit = jitter * ((s % 3) - 1)
        sign = -1.0 if s < neg_seeds else 1.0
        hist = {a: {"auroc": [], "lift_f1": [], "corr": [], "ncorrect": [], "npool": []} for a in X.ARMS}
        for r in range(nrounds):
            if r == 0:
                g = 0.0                                  # cero estructural de la ronda 1
            else:
                ramp = (r / max(1, nrounds - 1)) if grow else 1.0
                g = sign * auroc_gap * ramp + jit
            hist["naive"]["auroc"].append(0.80); hist["durable"]["auroc"].append(0.80 + g)
            hist["naive"]["lift_f1"].append(0.30); hist["durable"]["lift_f1"].append(0.30 + 0.05)
            hist["naive"]["corr"].append(0.30); hist["durable"]["corr"].append(0.34)
            hist["naive"]["ncorrect"].append(nc_naive); hist["durable"]["ncorrect"].append(nc_durable)
            for a in X.ARMS:
                hist[a]["npool"].append(512)
        per.append({"seed": s, "base": {"real_acc": 0.55}, "hist": hist})
    return per


def test_mixta_significancia_fragil_7_de_8():
    # caso frágil REAL: 7/8 seeds positivos (uno negativo) -> sign-test p=0.07 -> NO robusto -> MIXTA (no APOYADA)
    sm = X.build_summary(_mk_per_seed(auroc_gap=0.06, nseed=8, grow=True, neg_seeds=1), nrounds=8)
    assert sm["status"] == "mixta", sm["verdict"]
    assert sm["auroc_positive"], sm["auroc_gap_stats"]
    assert not sm["significant_robust"], (sm["sign_test_p"], sm["auroc_t_sig"])   # sign-test frágil rompe la robustez


def test_refutada_sin_ventaja():
    sm = X.build_summary(_mk_per_seed(auroc_gap=0.0, nseed=8), nrounds=8)
    assert sm["status"] == "refutada", sm["verdict"]
    assert not sm["auroc_positive"]


def test_signtest_p_no_significativo_a_7_de_8():
    # el sign-test 7/8 da p=0.070 (NO significativo) -- la corrección clave de la verificación
    assert X._signtest_p(7, 8) == 0.0703 or abs(X._signtest_p(7, 8) - 0.0703) < 0.001, X._signtest_p(7, 8)
    assert X._signtest_p(8, 8) < 0.01          # 8/8 sí significativo
    assert X._signtest_p(4, 8) == 1.0          # 4/8 = azar


def test_invariancia_empirica_baserate():
    # corr(nc,auroc) dentro de un brazo ≈ 0 cuando el AUROC es constante (invariante al base-rate) -> baserate_invariant True
    sm = X.build_summary(_mk_per_seed(auroc_gap=0.06, nc_durable=220, nc_naive=215, nseed=8), nrounds=8)
    assert sm["baserate_invariant"], (sm["corr_nc_auroc_durable"], sm["corr_nc_auroc_naive"])


def test_slope_sin_ronda1_no_se_infla_por_cero_estructural():
    # con gap PLANO (mismo gap todas las rondas salvo la ronda-1=0), la pendiente CON ronda-1 sería positiva (artefacto);
    # la pendiente per-seed SIN ronda-1 debe ser ~0 (plano), demostrando la corrección
    sm = X.build_summary(_mk_per_seed(auroc_gap=0.08, nseed=8, grow=False), nrounds=8)
    assert abs(sm["perseed_slope_no_r1"]["mean"]) < 0.01, sm["perseed_slope_no_r1"]


def test_perseed_slope_helper_excluye_primera_ronda():
    per = _mk_per_seed(auroc_gap=0.08, nseed=4, grow=False)
    sl = X._perseed_slope(per, "auroc", skip_first=True)
    sl_with = X._perseed_slope(per, "auroc", skip_first=False)
    # incluir la ronda-1=0 INFLA la pendiente; excluirla la baja a ~0 (gap plano)
    assert sl_with["mean"] > sl["mean"], (sl_with["mean"], sl["mean"])
