#!/usr/bin/env bash
# Busqueda de la configuracion por defecto de mayor calidad (noche 2026-09-07).
# Seis brazos, mismas 3 tareas (d3), mismo presupuesto de pared, paquete CONGELADO
# en Desktop/_cognia_noche (el repo se sigue editando mientras corre).
set -u
cd /c/Users/usuario/Desktop/cognia_v2
PY=./venv312/Scripts/python.exe
CWD=/c/Users/usuario/Desktop/_cognia_noche
TAREAS=web-dashboard,py-cli-tareas,node-cli-generador
export BANCO_PRESUPUESTO=600
PERFIL=/c/Users/usuario/.cognia/perfiles_modelo.json
rm -f "$PERFIL"
esfuerzo () {
  $PY -c "import json,pathlib;p=pathlib.Path.home()/'.cognia_config.json';c=json.loads(p.read_text(encoding='utf-8'));c['esfuerzo']='$1';p.write_text(json.dumps(c,indent=2,ensure_ascii=False),encoding='utf-8');print('esfuerzo ->','$1')"
}
correr () {  # nombre  [ENV=VAL ...]
  local ronda=$1; shift
  echo "[noche] $(date +%H:%M) brazo $ronda ($*)"
  env "$@" $PY -m banco_largo.runner --ronda "cfg_$ronda" --cwd-cli "$CWD" --tareas $TAREAS --forzar >> banco_largo/noche_config.log 2>&1
  echo "[noche] $(date +%H:%M) fin $ronda"
}
esfuerzo medio
correr base            COGNIA_NOCHE=1
esfuerzo alto
correr esfuerzo_alto   COGNIA_ESFUERZO=alto
esfuerzo medio
correr sin_thinking    COGNIA_THINKING=off
printf '{"qwen3.8": {"temperature": 0.6, "top_p": 0.95, "piensa": true}}' > "$PERFIL"
correr temp06          COGNIA_NOCHE=1
rm -f "$PERFIL"
esfuerzo maximo
correr esfuerzo_maximo COGNIA_ESFUERZO=max
esfuerzo medio
correr sin_revision    COGNIA_REVISION=0
echo "[noche] $(date +%H:%M) FIN DE LOS BRAZOS"
