#!/usr/bin/env bash
set -u
cd /c/Users/usuario/Desktop/cognia_v2
PY=./venv312/Scripts/python.exe
echo "[cola] $(date +%H:%M) ARK, 45 minutos, codigo final"
rm -rf banco_largo/corridas/ark_45min
BANCO_PRESUPUESTO=2700 $PY -m banco_largo.runner --ronda ark_45min --cwd-cli /c/Users/usuario/Desktop/cognia_v2 --tareas ark-supervivencia >> banco_largo/ark_45min.log 2>&1
echo "[cola] $(date +%H:%M) web-kanban con el codigo final, 20 min"
BANCO_PRESUPUESTO=1200 $PY -m banco_largo.runner --ronda r20_B3_final --cwd-cli /c/Users/usuario/Desktop/cognia_v2 --tareas web-kanban >> banco_largo/r20_B3.log 2>&1
rm -rf banco_largo/corridas/r20_B_final; mkdir -p banco_largo/corridas/r20_B_final
cp banco_largo/corridas/r20_B3_final/*.json banco_largo/corridas/r20_B_final/
rm -f banco_largo/corridas/r20_B_final/corrida.json
$PY -m banco_largo.informe --antes r20_A_pypi --despues r20_B_final --salida banco_largo/INFORME_R20.md >> banco_largo/r20_final.log 2>&1
echo "[cola] $(date +%H:%M) FIN"
