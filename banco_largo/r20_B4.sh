#!/usr/bin/env bash
# El servidor API tambien corrio con el codigo intermedio: se repite con el final
# cuando B3 haya terminado, y se rehace la carpeta final y el informe.
set -u
cd /c/Users/usuario/Desktop/cognia_v2
PY=./venv312/Scripts/python.exe
export BANCO_PRESUPUESTO=1200
echo "[r20B4] $(date +%H:%M) espero a B3 (3 tareas)"
while [ "$(ls banco_largo/corridas/r20_B3_final/ 2>/dev/null | grep -c '^[a-z0-9-]*\.json$')" -lt 3 ]; do sleep 60; done
sleep 90
echo "[r20B4] $(date +%H:%M) repito py-servidor-api con el codigo final"
$PY -m banco_largo.runner --ronda r20_B3_final --tareas py-servidor-api --cwd-cli /c/Users/usuario/Desktop/cognia_v2 >> banco_largo/r20_B4.log 2>&1
mkdir -p banco_largo/corridas/r20_B_final
cp banco_largo/corridas/r20_B3_final/*.json banco_largo/corridas/r20_B_final/ 2>/dev/null
cp banco_largo/corridas/r20_B_lazo/web-kanban.json banco_largo/corridas/r20_B_final/ 2>/dev/null
rm -f banco_largo/corridas/r20_B_final/corrida.json
$PY -m banco_largo.informe --antes r20_A_pypi --despues r20_B_final --salida banco_largo/INFORME_R20.md >> banco_largo/r20_B4.log 2>&1
echo "[r20B4] $(date +%H:%M) FIN"
