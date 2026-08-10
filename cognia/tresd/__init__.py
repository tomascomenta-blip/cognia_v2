# -*- coding: utf-8 -*-
"""Subsistema 3D de Cognia (TripoSR imagen -> malla).

POR QUE un paquete propio: la regla dura del repo es que cognia/ no importa
torch; este paquete solo contiene la fachada liviana (chequeos de disco +
subprocess) y el trabajo pesado corre en scripts/tresd_generar_cli.py con el
python de venv312gpu. Reexporta la API congelada del plan integrado para que
la tool (cognia/agent/tresd_tools.py) importe `from cognia.tresd import ...`.
"""
from cognia.tresd.triposr_backend import generar_malla, tresd_disponible

__all__ = ["generar_malla", "tresd_disponible"]
