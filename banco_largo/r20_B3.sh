#!/usr/bin/env bash
# Repite con el codigo FINAL las tres tareas de la ronda B que corrieron con el
# codigo intermedio (antes del aviso de racha y del techo con reloj). Espera a
# que terminen la ronda B y el brazo A para no compartir la GPU.
set -u
cd /c/Users/usuario/Desktop/cognia_v2
PY=./venv312/Scripts/python.exe
export BANCO_PRESUPUESTO=1200
echo "[r20B3] $(date +%H:%M) espero a la ronda B (5) y al brazo A (3)"
while [ "$(ls banco_largo/corridas/r20_B_lazo/ 2>/dev/null | grep -c '^[a-z0-9-]*\.json$')" -lt 5 ] || \
      [ "$(ls banco_largo/corridas/r20_A_pypi/ 2>/dev/null | grep -c '^[a-z0-9-]*\.json$')" -lt 5 ]; do sleep 60; done
echo "[r20B3] $(date +%H:%M) repito node-cli, py-cli y juego con el codigo final"
$PY -m banco_largo.runner --ronda r20_B3_final --cwd-cli /c/Users/usuario/Desktop/cognia_v2 --tareas node-cli-generador,py-cli-tareas,juego-tower-defense >> banco_largo/r20_B3.log 2>&1
# la ronda final completa = B3 (3 tareas con codigo final) + B (las 2 que ya corrieron con el)
mkdir -p banco_largo/corridas/r20_B_final
cp banco_largo/corridas/r20_B3_final/*.json banco_largo/corridas/r20_B_final/ 2>/dev/null
cp banco_largo/corridas/r20_B_lazo/py-servidor-api.json banco_largo/corridas/r20_B_lazo/web-kanban.json banco_largo/corridas/r20_B_final/ 2>/dev/null
rm -f banco_largo/corridas/r20_B_final/corrida.json
$PY -m banco_largo.informe --antes r20_A_pypi --despues r20_B_final --salida banco_largo/INFORME_R20.md >> banco_largo/r20_B3.log 2>&1
echo "[r20B3] $(date +%H:%M) FIN"
