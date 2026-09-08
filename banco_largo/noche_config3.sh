#!/usr/bin/env bash
# Brazo 8: la COMBINACION candidata a default (catalogo chico + sin thinking + esfuerzo alto).
set -u
cd /c/Users/usuario/Desktop/cognia_v2
PY=./venv312/Scripts/python.exe
TAREAS=web-dashboard,py-cli-tareas,node-cli-generador
export BANCO_PRESUPUESTO=600
esfuerzo () {
  $PY -c "import json,pathlib;p=pathlib.Path.home()/'.cognia_config.json';c=json.loads(p.read_text(encoding='utf-8'));c['esfuerzo']='$1';p.write_text(json.dumps(c,indent=2,ensure_ascii=False),encoding='utf-8');print('esfuerzo ->','$1')"
}
while ! grep -q "FIN brazo 7" banco_largo/noche_config2_cadena.log 2>/dev/null; do sleep 30; done
esfuerzo alto
echo "[noche3] $(date +%H:%M) brazo combo (chico + sin thinking + esfuerzo alto)"
env COGNIA_THINKING=off $PY -m banco_largo.runner --ronda cfg_combo --cwd-cli /c/Users/usuario/Desktop/_cognia_noche_chico --tareas $TAREAS --forzar >> banco_largo/noche_config.log 2>&1
esfuerzo medio
echo "[noche3] $(date +%H:%M) FIN brazo 8"
