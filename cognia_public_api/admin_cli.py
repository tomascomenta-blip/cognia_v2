#!/usr/bin/env python
"""
Uso:
  python admin_cli.py create-key    # genera y guarda una key nueva
  python admin_cli.py list-keys     # lista todas las keys
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

# Use local data dir when running outside Docker
os.environ.setdefault("DATA_DIR", os.path.join(os.path.dirname(__file__), "data"))

from key_store import create_key, list_keys, init_db

if len(sys.argv) < 2:
    print("Uso: python admin_cli.py [create-key|list-keys]")
    sys.exit(1)

init_db()
cmd = sys.argv[1]
if cmd == "create-key":
    key = create_key()
    print(f"API Key creada: {key}")
    print("Guarda esta key -- es tu acceso a la API publica de Cognia.")
elif cmd == "list-keys":
    keys = list_keys()
    if not keys:
        print("No hay keys registradas.")
    for k in keys:
        print(f"  {k['key']} | usos: {k['request_count']} | ultimo: {k['last_used']}")
else:
    print(f"Comando desconocido: {cmd}")
    sys.exit(1)
