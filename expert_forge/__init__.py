"""
expert_forge
============
Fabrica de expertos LoRA para Cognia. Paquete TOP-LEVEL a proposito:
usa torch/peft/transformers, prohibidos dentro de cognia/ y node/ (esos
paquetes se empaquetan a PyPI sin torch). expert_forge NO esta en el
include de pyproject.toml, igual que bdraft/.

cognia/experts invoca esto SOLO via subprocess (expert_forge/cli_train.py),
nunca por import directo.
"""
