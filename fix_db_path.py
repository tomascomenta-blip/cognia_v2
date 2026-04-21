"""
fix_db_path.py — Diagnóstico y fix del problema de ruta relativa
================================================================
Ejecutar UNA VEZ antes de correr web_app.py.

El problema: DB_PATH = "cognia_memory.db" es relativa.
Cuando Flask corre, el cwd puede no ser el directorio del proyecto,
así que SQLite crea/lee una DB diferente a la que crees.

Este script:
1. Detecta dónde está realmente escribiendo Cognia
2. Muestra la ruta absoluta correcta
3. Parchea cognia_v3.py para usar ruta absoluta
"""

import os
import sqlite3
import re

# ── Paso 1: detectar el directorio real del proyecto ──────────────────
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
DB_RELATIVA = "cognia_memory.db"
DB_ABSOLUTA = os.path.join(THIS_DIR, DB_RELATIVA)
CWD_DB = os.path.join(os.getcwd(), DB_RELATIVA)

print("=" * 60)
print("DIAGNÓSTICO DE RUTAS")
print("=" * 60)
print(f"Directorio actual (cwd)  : {os.getcwd()}")
print(f"Directorio del script    : {THIS_DIR}")
print(f"DB que Cognia DEBERÍA usar: {DB_ABSOLUTA}")
print(f"DB que Cognia USA si cwd!=dir: {CWD_DB}")
print()

# Verificar si son distintos
if os.path.abspath(os.getcwd()) != os.path.abspath(THIS_DIR):
    print("⚠️  PROBLEMA DETECTADO: cwd != directorio del script")
    print("   Cognia está escribiendo en una DB diferente a la que ves.")
else:
    print("✅ cwd == directorio del script (rutas coinciden)")

# Contar filas en la DB correcta
if os.path.exists(DB_ABSOLUTA):
    conn = sqlite3.connect(DB_ABSOLUTA)
    c = conn.cursor()
    ep = c.execute("SELECT COUNT(*) FROM episodic_memory").fetchone()[0]
    sem = c.execute("SELECT COUNT(*) FROM semantic_memory").fetchone()[0]
    conn.close()
    print(f"\n📊 DB en {DB_ABSOLUTA}")
    print(f"   episodic_memory : {ep} filas")
    print(f"   semantic_memory : {sem} filas")
else:
    print(f"\n❌ No existe: {DB_ABSOLUTA}")

# ── Paso 2: parchear cognia_v3.py ─────────────────────────────────────
cognia_path = os.path.join(THIS_DIR, "cognia_v3.py")

if not os.path.exists(cognia_path):
    print(f"\n❌ No se encontró cognia_v3.py en {THIS_DIR}")
    exit(1)

with open(cognia_path, "r", encoding="utf-8") as f:
    contenido = f.read()

# Línea a reemplazar
LINEA_VIEJA = 'DB_PATH = "cognia_memory.db"'
# Usamos forward slashes para evitar problemas con backslashes en f-strings de Python
db_abs_escaped = DB_ABSOLUTA.replace("\\", "\\\\")
LINEA_NUEVA = f'DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cognia_memory.db")'

if LINEA_VIEJA not in contenido:
    if "os.path.abspath(__file__)" in contenido:
        print("\n✅ cognia_v3.py ya tiene ruta absoluta — no se necesita parche.")
    else:
        print(f"\n⚠️  No se encontró la línea exacta '{LINEA_VIEJA}' en cognia_v3.py")
        print("   Busca manualmente DB_PATH y cámbiala a:")
        print(f"   {LINEA_NUEVA}")
    exit(0)

# Hacer backup
backup_path = cognia_path + ".backup_fix_db"
with open(backup_path, "w", encoding="utf-8") as f:
    f.write(contenido)
print(f"\n💾 Backup guardado en: {backup_path}")

# Verificar que 'import os' ya está
if "import os" not in contenido:
    print("⚠️  'import os' no encontrado — añadiéndolo...")
    contenido = "import os\n" + contenido

# Aplicar parche
contenido_nuevo = contenido.replace(LINEA_VIEJA, LINEA_NUEVA)

with open(cognia_path, "w", encoding="utf-8") as f:
    f.write(contenido_nuevo)

print(f"\n✅ PARCHE APLICADO en cognia_v3.py")
print(f"   Antes : {LINEA_VIEJA}")
print(f"   Ahora : {LINEA_NUEVA}")
print()
print("🚀 Ahora reinicia Flask:")
print("   python web_app.py")
print()
print("Y verifica enviando un mensaje y luego ejecutando:")
print("   python diagnostico.py")
