r"""
CYCLE 140 / H-V4-9g — regresión (MIXTA, post-verificación adversarial de 4 agentes). SALIR DEL ORÁCULO: intento de aterrizar el
payoff decisional del R-VALOR en el lazo torch REAL. La verificación cazó un CONFOUND DE BASE-RATE (los dos brazos generan pools
con distinto #correctas; precision@m es base-rate-sensible) -> corregido con AUROC (ranking, base-rate-INVARIANTE) + lift + base-rate
de AMBOS brazos. El veredicto honesto es MIXTA: existe una ventaja de ranking del durable (AUROC, signo-consistente) pero es MODESTA,
UNDERPOWERED a N=4, y con un TRADE-OFF GENERACIÓN/RANKING (el unlikelihood hace al durable peor generador).

Como X.run es un lazo torch lento (~30 min), la regresión valida la LÓGICA DE VEREDICTO sobre per_seed SINTÉTICO + un smoke torch
MÍNIMO (marcado slow).

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle140_decisional_real_loop.py -q -m "not slow"
"""
import pytest

from cognia_x.experiments.exp124_decisional_real_loop import run as X


def _mk_per_seed(auroc_gap, lift_gap=0.05, nc_durable=200, nc_naive=200, nseed=4, nrounds=6, auroc_base=0.80):
    """per_seed sintético: durable AUROC = naive AUROC + auroc_gap (+ jitter por-seed para varianza realista); idem lift."""
    per = []
    for s in range(nseed):
        jit = 0.01 * ((s % 3) - 1)        # jitter determinista por-seed (±0.01) -> varianza no-nula, todos los gaps positivos
        hist = {a: {"payoff_f": {f: [] for f in X.F_GRID}, "auroc": [], "lift_f1": [], "corr": [],
                    "ncorrect": [], "npool": []} for a in X.ARMS}
        for r in range(nrounds):
            hist["naive"]["auroc"].append(auroc_base); hist["durable"]["auroc"].append(auroc_base + auroc_gap + jit)
            hist["naive"]["lift_f1"].append(0.30); hist["durable"]["lift_f1"].append(0.30 + lift_gap + jit)
            hist["naive"]["corr"].append(0.30); hist["durable"]["corr"].append(0.36)
            hist["naive"]["ncorrect"].append(nc_naive); hist["durable"]["ncorrect"].append(nc_durable)
            for a in X.ARMS:
                hist[a]["npool"].append(512)
                for f in X.F_GRID:
                    hist[a]["payoff_f"][f].append(0.80 + (0.05 if a == "durable" else 0.0))
        per.append({"seed": s, "base": {"real_acc": 0.55}, "hist": hist})
    return per


def test_mixta_underpowered_a_n4():
    # ventaja AUROC consistente PERO N=4 (underpowered) -> MIXTA, no APOYADA (no se puede reclamar significancia con 4 seeds)
    sm = X.build_summary(_mk_per_seed(auroc_gap=0.08, nseed=4, nc_durable=200, nc_naive=200))
    assert sm["status"] == "mixta", sm["verdict"]
    assert sm["auroc_advantage"], sm["auroc_gap_stats"]
    assert sm["underpowered"], sm["n_seeds"]
    assert not sm["significant"], "no debe reclamar significancia a N=4"


def test_refutada_sin_ventaja_auroc():
    # AUROC gap ~0 -> el payoff aparente era el confound de base-rate, no calibración -> REFUTADA
    sm = X.build_summary(_mk_per_seed(auroc_gap=0.0, nseed=4))
    assert sm["status"] == "refutada", sm["verdict"]
    assert not sm["auroc_advantage"], sm["auroc_gap_stats"]


def test_generation_tradeoff_fuerza_mixta_aun_con_n8():
    # con N=8 y AUROC significativo PERO el durable genera MUCHAS menos correctas (trade-off) -> MIXTA, no APOYADA
    sm = X.build_summary(_mk_per_seed(auroc_gap=0.10, nseed=8, nc_durable=40, nc_naive=200))
    assert sm["status"] == "mixta", sm["verdict"]
    assert sm["generation_tradeoff"], sm["baserate_gap_stats"]


def test_apoyada_requiere_n8_sin_tradeoff_y_significativo():
    # única ruta a APOYADA: ventaja AUROC + lift + significativo a N>=8 + SIN trade-off de generación
    sm = X.build_summary(_mk_per_seed(auroc_gap=0.10, lift_gap=0.08, nseed=8, nc_durable=200, nc_naive=200))
    assert sm["status"] == "apoyada", sm["verdict"]
    assert sm["auroc_advantage"] and sm["lift_survives"] and sm["significant"] and not sm["generation_tradeoff"]


def test_baserate_confound_se_reporta():
    # el base-rate de AMBOS brazos se mide (la 1ra versión sólo logueaba el durable -> confound irrecuperable)
    sm = X.build_summary(_mk_per_seed(auroc_gap=0.05, nc_durable=40, nc_naive=200))
    assert sm["baserate_confound"], sm["baserate_gap_stats"]
    assert sm["mean_ncorrect_durable"] < sm["mean_ncorrect_naive"]


def test_auroc_invariante_al_baserate_y_lift_y_payoff():
    import numpy as np
    # AUROC=1.0 si la confianza rankea perfecto (correctas arriba), independiente de cuántas correctas haya
    conf = np.array([0.1, 0.2, 0.8, 0.9]); strong = np.array([0.0, 0.0, 1.0, 1.0])
    assert abs(X._auroc(conf, strong) - 1.0) < 1e-9
    conf2 = np.array([0.9, 0.2, 0.8, 0.1]); strong2 = np.array([0.0, 0.0, 1.0, 1.0])  # 1 mal-rankeada
    assert X._auroc(conf2, strong2) < 1.0
    assert X._auroc(conf, np.zeros(4)) is None        # sin correctas -> AUROC indefinido
    # lift@f1 = payoff@nc − base_rate
    lf = X._lift_at_f1(conf, strong)
    assert lf is not None and lf == pytest.approx(1.0 - 0.5)   # payoff perfecto 1.0, base_rate 2/4
    assert X._payoff_at_m(conf, strong, 2) == 1.0


@pytest.mark.slow
def test_smoke_torch_loop_corre_end_to_end():
    import argparse
    from cognia_x.experiments.exp018_real_verifier import expression_task as E
    from cognia_x.experiments.exp018_real_verifier.run import LO, HI
    args = argparse.Namespace(seeds="0", rounds=2, K=6, pool=24, budget_frac=0.15, temp=1.3, replay_frac=0.5,
                              neg_w=0.5, top_k=None, steps=40, n_seed=150, base_steps=150, base_lr=1e-3, lr=5e-4,
                              warmup=30, batch=32, test_frac=0.30)
    train_targets, test_targets = E.build_split(LO, HI, args.test_frac)
    per_seed = [X.run_seed(0, args, test_targets, train_targets, lambda m: None)]
    sm = X.build_summary(per_seed)
    assert sm["status"] in ("apoyada", "mixta", "refutada")
    assert "auroc_gap_stats" in sm and "baserate_gap_stats" in sm
