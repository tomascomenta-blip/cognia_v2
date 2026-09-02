#!/usr/bin/env bash
# Brazo A (PyPI 4.22.0) para las tres tareas que faltan del A/B de 20 min; espera
# a que termine la ronda B para no compartir la GPU (la maquina no se comparte).
set -u
cd /c/Users/usuario/Desktop/cognia_v2
PY=./venv312/Scripts/python.exe
PYPI=/c/Users/usuario/Desktop/venv_pypi/Scripts/python.exe
export BANCO_PRESUPUESTO=1200
echo "[r20A] $(date +%H:%M) espero a la ronda B (5 tareas)"
while [ "$(ls banco_largo/corridas/r20_B_lazo/ 2>/dev/null | grep -c '^[a-z0-9-]*\.json$')" -lt 5 ]; do sleep 60; done
echo "[r20A] $(date +%H:%M) brazo A para kanban, cli-tareas, node-cli"
$PY -m banco_largo.runner --ronda r20_A_pypi --python $PYPI --cwd-cli /c/Users/usuario/Desktop --tareas web-kanban,py-cli-tareas,node-cli-generador >> banco_largo/r20_A.log 2>&1
echo "[r20A] $(date +%H:%M) FIN"
