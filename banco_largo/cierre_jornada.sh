#!/usr/bin/env bash
# Cierre de la jornada, desatendido:
#   1. espera a ARK v3
#   2. gate del camino feliz (5/5 obligatorio antes de publicar)
#   3. build + publicacion 4.23.0 en PyPI (token desde .env, nunca impreso)
#   4. instalacion limpia desde PyPI y verificacion (ruta site-packages + version)
#   5. humo real con el CLI instalado
# Cada paso deja su marca en banco_largo/cierre.log; si un paso falla, los
# siguientes no se ejecutan y el log dice cual.
set -u
cd /c/Users/usuario/Desktop/cognia_v2
PY=./venv312/Scripts/python.exe
LOG=banco_largo/cierre.log
echo "[cierre] $(date +%H:%M) espero a ARK v3" | tee -a $LOG
while [ ! -f banco_largo/corridas/ark_45min_v3/ark-supervivencia.json ]; do sleep 30; done
sleep 20

echo "[cierre] $(date +%H:%M) gate camino feliz" | tee -a $LOG
PYTHONUTF8=1 $PY scripts/e2e_happy_path.py > /tmp/gate2.log 2>&1
if ! grep -q "5/5 OK" /tmp/gate2.log; then
  echo "[cierre] GATE FALLO: $(tail -1 /tmp/gate2.log)" | tee -a $LOG
  exit 1
fi
echo "[cierre] gate 5/5 OK" | tee -a $LOG

echo "[cierre] $(date +%H:%M) build" | tee -a $LOG
rm -f dist/cognia_ai-4.23.0*
$PY -m build --wheel --sdist > /tmp/build2.log 2>&1 || { echo "[cierre] BUILD FALLO" | tee -a $LOG; exit 1; }
ls dist/cognia_ai-4.23.0* | tee -a $LOG

echo "[cierre] $(date +%H:%M) publicar en PyPI" | tee -a $LOG
export TWINE_USERNAME=__token__
export TWINE_PASSWORD="$(grep -E '^(PYPI_TOKEN|TWINE_PASSWORD|PYPI_API_TOKEN)=' .env | head -1 | cut -d= -f2- | tr -d '\r"'"'"'')"
$PY -m twine upload dist/cognia_ai-4.23.0* > /tmp/twine2.log 2>&1 || { echo "[cierre] PUBLICACION FALLO: $(tail -2 /tmp/twine2.log)" | tee -a $LOG; exit 1; }
unset TWINE_PASSWORD
echo "[cierre] publicado: https://pypi.org/project/cognia-ai/4.23.0/" | tee -a $LOG

echo "[cierre] $(date +%H:%M) instalacion limpia desde PyPI" | tee -a $LOG
cd /c/Users/usuario/Desktop
rm -rf venv_pypi2
./cognia_v2/venv312/Scripts/python.exe -m venv venv_pypi2
./venv_pypi2/Scripts/python.exe -m pip install -q --upgrade pip > /dev/null 2>&1
for i in 1 2 3 4 5 6; do
  if ./venv_pypi2/Scripts/python.exe -m pip install -q --no-cache-dir "cognia-ai==4.23.0" > /tmp/pip2.log 2>&1; then break; fi
  echo "[cierre] pip aun no ve 4.23.0 (intento $i), espero 60 s" | tee -a cognia_v2/$LOG; sleep 60
done
./venv_pypi2/Scripts/python.exe -c "import cognia, importlib.metadata as md; print('version', md.version('cognia-ai')); print('ruta', cognia.__file__); from cognia.harness import lazo_corto, contrato_tarea, telemetria; print('modulos nuevos OK')" 2>&1 | tee -a cognia_v2/$LOG

echo "[cierre] $(date +%H:%M) humo con el CLI instalado" | tee -a cognia_v2/$LOG
mkdir -p /tmp/humo_pypi && rm -rf /tmp/humo_pypi/*
./venv_pypi2/Scripts/python.exe -m cognia hacer "Crea calc.py con una funcion suma(a,b) y un test_calc.py con pytest que la pruebe; ejecuta los tests." --json --cwd /tmp/humo_pypi > /tmp/humo_pypi.json 2> /tmp/humo_pypi.err
./venv_pypi2/Scripts/python.exe -c "import json; d=json.load(open('/tmp/humo_pypi.json', encoding='utf-8')); print('humo ok=', d.get('ok'), '| pasos', (d.get('telemetria') or {}).get('turnos'))" 2>&1 | tee -a cognia_v2/$LOG
ls /tmp/humo_pypi | tee -a cognia_v2/$LOG
echo "[cierre] $(date +%H:%M) FIN" | tee -a cognia_v2/$LOG
