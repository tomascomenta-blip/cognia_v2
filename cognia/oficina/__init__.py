"""Oficina de trabajo agéntica de 3 escalas (jefe / directores / trabajadores).

Dashboard localhost para VER, EDITAR y DETENER lo que hacen los agentes,
con el flujo completo visible. Construida SOBRE la maquinaria agéntica real
de Cognia: los trabajadores corren `cli._run_agent_task` con tools acotadas
por rol (ROLE_TOOLS) y el jefe/directores planifican con `orch.infer`.

Arrancar: python -m cognia.oficina  →  http://127.0.0.1:8765
"""
