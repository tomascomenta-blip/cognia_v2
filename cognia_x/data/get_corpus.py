"""
Descarga el corpus de CYCLE 7 (char-LM): prosa de DOMINIO PÚBLICO de Project Gutenberg.
Reproducible — el corpus en sí NO se commitea (gitignored), este script lo reconstruye.

Español (Quijote + 3 más) + inglés (Shakespeare completo + 9 clásicos) ≈ 17 MB de lenguaje
natural diverso (≈22× el corpus de markdown del CYCLE 5). Multi-dominio y bilingüe a propósito:
demuestra que el híbrido byte-level aprende ESTRUCTURA de lenguaje, no un solo registro.

Uso: .\\venv312\\Scripts\\python.exe -m cognia_x.data.get_corpus
"""
import os
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "corpus")

# nombre -> id de Gutenberg (URL: https://www.gutenberg.org/cache/epub/<id>/pg<id>.txt)
BOOKS = {
    "es_quijote": 2000, "es_17073": 17073, "es_15532": 15532, "es_49836": 49836,
    "en_shakespeare": 100, "en_moby": 2701, "en_great_expectations": 1400,
    "en_dracula": 345, "en_tale_two_cities": 98, "en_pride_prejudice": 1342,
    "en_huck_finn": 76, "en_sherlock": 1661, "en_dorian_gray": 174,
    "en_frankenstein": 84, "en_alice": 11,
}


def main():
    os.makedirs(OUT, exist_ok=True)
    total = 0
    for name, gid in BOOKS.items():
        path = os.path.join(OUT, name + ".txt")
        if os.path.exists(path) and os.path.getsize(path) > 50_000:
            total += os.path.getsize(path)
            print(f"  ya está   {name:24s} {os.path.getsize(path):>9,} bytes")
            continue
        url = f"https://www.gutenberg.org/cache/epub/{gid}/pg{gid}.txt"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "cognia-x-lab/1.0"})
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
            if len(data) < 50_000:
                print(f"  CHICO     {name:24s} {len(data)} bytes (¿error?), salto")
                continue
            with open(path, "wb") as fh:
                fh.write(data)
            total += len(data)
            print(f"  bajado    {name:24s} {len(data):>9,} bytes")
            time.sleep(1)  # cortés con Gutenberg
        except Exception as e:  # noqa: BLE001
            print(f"  FALLO     {name:24s} {e!r}")
    print(f"\nTOTAL corpus: {total:,} bytes en {OUT}")


if __name__ == "__main__":
    main()
