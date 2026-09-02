#!/usr/bin/env bash
# ARK con el codigo final y 45 minutos de reloj, en cuanto termine la ronda de 20 min.
set -u
cd /c/Users/usuario/Desktop/cognia_v2
PY=./venv312/Scripts/python.exe
echo "[ark] $(date +%H:%M) espero al informe de la ronda de 20 min"
while [ ! -f banco_largo/INFORME_R20.md ]; do sleep 30; done
sleep 30
echo "[ark] $(date +%H:%M) ARK, 45 minutos, codigo final"
BANCO_PRESUPUESTO=2700 $PY -m banco_largo.runner --ronda ark_45min --cwd-cli /c/Users/usuario/Desktop/cognia_v2 --tareas ark-supervivencia >> banco_largo/ark_45min.log 2>&1
echo "[ark] $(date +%H:%M) FIN"
