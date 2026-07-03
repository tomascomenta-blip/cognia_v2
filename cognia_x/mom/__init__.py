"""MoM (Mixture of Models) de CogniaX — flota de expertos densos ~97.5M + selector.

Construido sobre los veredictos MEDIDOS del programa X1-X4 (construccion/xhundred/04_MOM_GROKKING.md §9):
expertos densos por dominio PAGAN su nicho (X3), el calibrador es un SELECTOR (X4: n-grams
estático ≈ oracle en 2/3 dominios, <5ms), y fuera de nicho el experto se derrumba → fallback
al generalista bajo umbral de confianza. Corre LOCAL con venv312 (torch CPU); NO se sirve en
nodos de la red (sin PyTorch en nodos; export GGUF banded no validado — P6).
"""
from .selector import Selector  # noqa: F401
from .fleet import Fleet  # noqa: F401
