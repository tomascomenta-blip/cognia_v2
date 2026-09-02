#!/usr/bin/env bash
# Cadena FINAL del A/B a 20 min, con esperas por FICHERO (no por cuenta: la cuenta
# incluia corrida.json y arranco una ronda encima de otra).
#   1. espera a que el brazo A termine web-kanban (contaminado: se repite limpio)
#   2. repite web-kanban en A (4.22.0)
#   3. B con el codigo final: node-cli, py-cli, juego, py-servidor
#   4. carpeta final B = esas 4 + web-kanban de la ronda B, e informe
set -u
cd /c/Users/usuario/Desktop/cognia_v2
PY=./venv312/Scripts/python.exe
PYPI=/c/Users/usuario/Desktop/venv_pypi/Scripts/python.exe
export BANCO_PRESUPUESTO=1200

echo "[final] $(date +%H:%M) espero a que A termine web-kanban"
while [ ! -f banco_largo/corridas/r20_A_pypi/web-kanban.json ]; do sleep 30; done
sleep 60
echo "[final] $(date +%H:%M) A: repito web-kanban limpio"
mv banco_largo/corridas/r20_A_pypi/web-kanban.json banco_largo/corridas/r20_A_pypi/web-kanban.contaminado.json.bak
$PY -m banco_largo.runner --ronda r20_A_pypi --python $PYPI --cwd-cli /c/Users/usuario/Desktop --tareas web-kanban >> banco_largo/r20_A.log 2>&1

echo "[final] $(date +%H:%M) B con el codigo final: 4 tareas"
rm -rf banco_largo/corridas/r20_B3_final
$PY -m banco_largo.runner --ronda r20_B3_final --cwd-cli /c/Users/usuario/Desktop/cognia_v2 --tareas node-cli-generador,py-cli-tareas,juego-tower-defense,py-servidor-api >> banco_largo/r20_B3.log 2>&1

rm -rf banco_largo/corridas/r20_B_final; mkdir -p banco_largo/corridas/r20_B_final
cp banco_largo/corridas/r20_B3_final/*.json banco_largo/corridas/r20_B_final/
cp banco_largo/corridas/r20_B_lazo/web-kanban.json banco_largo/corridas/r20_B_final/
rm -f banco_largo/corridas/r20_B_final/corrida.json
$PY -m banco_largo.informe --antes r20_A_pypi --despues r20_B_final --salida banco_largo/INFORME_R20.md >> banco_largo/r20_final.log 2>&1
echo "[final] $(date +%H:%M) FIN"
