#!/usr/bin/env bash
# A/B con presupuesto REALISTA (20 min por tarea):
#   A = la version publicada 4.22.0 (venv_pypi)   B = el repo local con el lazo corto.
# Dos tareas de familias distintas para que el veredicto no sea de un solo tipo.
set -u
cd /c/Users/usuario/Desktop/cognia_v2
PY=./venv312/Scripts/python.exe
PYPI=/c/Users/usuario/Desktop/venv_pypi/Scripts/python.exe
TAREAS=juego-tower-defense,py-servidor-api
export BANCO_PRESUPUESTO=1200

echo "[ab] $(date +%H:%M) espero a que termine la reproduccion exploratoria"
while [ ! -f banco_largo/corridas/repro_juego_20min/juego-tower-defense.json ]; do sleep 30; done

echo "[ab] $(date +%H:%M) brazo A (PyPI 4.22.0)"
$PY -m banco_largo.runner --ronda ab20_A_pypi --python $PYPI --cwd-cli /c/Users/usuario/Desktop --tareas $TAREAS >> banco_largo/ab20.log 2>&1
echo "[ab] $(date +%H:%M) brazo B (local, lazo corto)"
$PY -m banco_largo.runner --ronda ab20_B_lazo --cwd-cli /c/Users/usuario/Desktop/cognia_v2 --tareas $TAREAS >> banco_largo/ab20.log 2>&1
echo "[ab] $(date +%H:%M) informe"
$PY -m banco_largo.informe --antes ab20_A_pypi --despues ab20_B_lazo --salida banco_largo/INFORME_AB20.md >> banco_largo/ab20.log 2>&1
echo "[ab] $(date +%H:%M) FIN"
