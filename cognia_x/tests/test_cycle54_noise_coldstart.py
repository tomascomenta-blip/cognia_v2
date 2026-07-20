r"""
CYCLE 54 / H-V4-2g — regresión: ruido del VERIFICADOR REAL x cold-start (CAPSTONE robustez).

Protege la lógica de veredicto de build_summary: (a) APOYADA si el guarded desde base débil bootstrapea bajo
ruido hasta ε*_coldstart>=0.15; (b) REFUTADA si el ruido destruye el cold-start; (c) ε*_coldstart se computa
por consistencia entre seeds (gain>=0.30 Y final>=0.50). Sin modelo -> instantáneo.

Correr: .\venv312\Scripts\python.exe -m pytest cognia_x/tests/test_cycle54_noise_coldstart.py -q
"""
from cognia_x.experiments.exp040_noise_coldstart import run as X


def _seed(base, finals):
    """hist[str(eps)] = [base, ..., final] (sólo el último cuenta para el veredicto)."""
    return {"base_acc": base, "hist": {str(e): [base, f] for e, f in zip(X.EPS_SWEEP, finals)}}


def test_verdict_apoyada_coexist():
    # desde base débil 0.08, bootstrapea fuerte (gain>=0.30) a todos los ε
    per_seed = [_seed(0.08, [0.92, 0.85, 0.70, 0.60]) for _ in range(3)]
    sm = X.build_summary(per_seed, m=90)
    assert sm["status"] == "apoyada"
    assert sm["clean_bootstraps"]
    assert sm["eps_star_coldstart"] == 0.50       # bootstrapea fuerte a todo el barrido


def test_verdict_refutada_noise_kills_coldstart():
    # ε=0 bootstrapea (gain 0.42), pero ε=0.15 ya no (gain 0.22 < 0.30) -> ε*_coldstart=0.0
    per_seed = [_seed(0.08, [0.50, 0.30, 0.20, 0.15]) for _ in range(3)]
    sm = X.build_summary(per_seed, m=90)
    assert sm["status"] == "refutada"
    assert sm["eps_star_coldstart"] == 0.0


def test_verdict_mixta_threshold_drops():
    # bootstrapea fuerte hasta ε=0.15 (gain 0.34) pero no a 0.30 (gain 0.22) -> ε*_coldstart=0.15 (0<x<0.30)
    per_seed = [_seed(0.08, [0.80, 0.42, 0.30, 0.25]) for _ in range(3)]
    sm = X.build_summary(per_seed, m=90)
    assert sm["clean_bootstraps"] and sm["eps_star_coldstart"] == 0.15
    assert sm["status"] == "mixta"
