"""
scripts/tokenizar_fichero.py
============================
Mide ficheros con el TOKENIZADOR del server (POST /tokenize), no con el contador
del generador. Existe porque el contador de `generate_long` es una suma de
`tokens_predicted` del propio generador: sirve para presupuestar, pero un
resultado que se declara en tokens tiene que medirse con el tokenizador y sobre
el fichero que quedo en disco.

Diferencia MEDIDA contra el contador (2026-08-17/18): +1 token por worker que
cerro por eos (el `<|im_end|>` que el server cuenta y el texto no lleva), +0 en
los que cortaron por cap, y de mas los encabezados que el script de la corrida
escribe por su cuenta. Sobre un smoke de 3 tareas: 3.064 tokenizados vs 3.000
contados.

Trocea en 6.000 chars porque un POST de un fichero de 200k tokens no entra en el
n_ctx del server (16.384 en :8080). El troceo no cambia la suma de forma
apreciable: parte en limites de chars, no de tokens, asi que puede sumar algun
token de borde por trozo (~1 cada 6.000 chars, < 0,03%).

Uso:
  venv312/Scripts/python.exe scripts/tokenizar_fichero.py fichero1.txt fichero2.txt
  COGNIA_TOKENIZE_URL=http://127.0.0.1:8081/tokenize ... (otro server)
"""

import json
import os
import sys
import urllib.request
from pathlib import Path

URL = os.environ.get("COGNIA_TOKENIZE_URL", "http://127.0.0.1:8080/tokenize")
TROZO = 6000


def tokens_de(texto: str) -> int:
    """Cuenta los tokens de `texto` preguntandole al server, por trozos."""
    n = 0
    for i in range(0, len(texto), TROZO):
        req = urllib.request.Request(
            URL, data=json.dumps({"content": texto[i:i + TROZO]}).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            n += len(json.load(r)["tokens"])
    return n


def main(argv: list) -> int:
    if not argv:
        print(__doc__.strip().splitlines()[-2].strip())
        return 2
    total_tok = total_chars = 0
    for ruta in argv:
        p = Path(ruta)
        if not p.is_file():
            print(f"{'FALTA':>9}  {ruta}")
            return 1
        txt = p.read_text(encoding="utf-8")
        n = tokens_de(txt)
        print(f"{n:9d} tok  {len(txt):10d} chars  {p.name}")
        total_tok += n
        total_chars += len(txt)
    if len(argv) > 1:
        print(f"{total_tok:9d} tok  {total_chars:10d} chars  TOTAL ({len(argv)} ficheros)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
