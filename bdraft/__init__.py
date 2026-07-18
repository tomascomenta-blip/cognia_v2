"""
bdraft — Cognia-BDraft: block-diffusion draft model (DFlash/DSpark style).

Training laboratory ONLY: runs on the training machine, never on nodes
(repo hard rule: no PyTorch on nodes). Not packaged to PyPI (not listed in
pyproject [tool.setuptools.packages.find] include).

Design doc: planes/DSPARK_GEMMA_DRAFT_MODEL.md (sections 2.2, 2.3, 3).
"""

from bdraft.model import BDraftConfig, BDraft

__all__ = ["BDraftConfig", "BDraft"]
