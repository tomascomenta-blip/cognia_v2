# -*- coding: utf-8 -*-
"""Scraper de MIDIs por genero para el futuro fine-tune multi-genero de SymphonyGen.

POR QUE existe: SymphonyGen (vendor, no editable) solo sabe musica sinfonica.
Para atacar generos nuevos (videojuegos, electro, phonk, andina) necesitamos
datos reales por genero. Este script descarga MIDIs de fuentes publicas a
    C:/Users/usuario/.cognia/data/midi_generos/<genero>/
de forma honesta y educada: user-agent normal, pausa 0.3-0.5 s entre archivos,
salta errores sin reintentar agresivo, y valida cada archivo (firma MThd,
tamano 500 B - 500 KB, dedupe por sha256 global por genero).

FUENTES (verificadas 2026-08-11):
- videojuegos: vgmusic.com -- indices HTML por consola con links .mid directos.
  Es EL dataset fuerte (miles de archivos). Elegimos nes/snes/n64/ps1.
- electro: midiworld.com (busqueda, links /download/NNN) y
  freemidi.org (genre-electronic-dance, flujo download3-XXXX -> getter-XXXX
  con Referer). bitmidi.com daba 521 (Cloudflare) el dia de la corrida.
- phonk: se intenta busqueda en midiworld/freemidi; genero muy nuevo,
  se documenta si no hay fuente decente (honestidad > relleno).
- andina: idem phonk; se intentan terminos huayno/andean/quena/latin.

Es una herramienta de una sola vez (sin tests); tiene --limite y --solo-listar
para probar barato, y --presupuesto-seg para time-boxear la corrida entera.

Uso:
    venv312/Scripts/python.exe scripts/musica_datos_generos.py --solo-listar --limite 5
    venv312/Scripts/python.exe scripts/musica_datos_generos.py --limite 120 --presupuesto-seg 840
"""

import argparse
import hashlib
import json
import random
import re
import sys
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, quote

import requests

DESTINO = Path.home() / ".cognia" / "data" / "midi_generos"

# User-agent de navegador normal: no nos disfrazamos de bot raro ni de scraper,
# pero tampoco mentimos con headers exoticos. Es el UA tipico de un Chrome en Windows.
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

TAM_MIN = 500          # bytes: por debajo suele ser un stub o una pagina de error
TAM_MAX = 500 * 1024   # bytes: por encima no es un MIDI tipico de estas fuentes

sesion = requests.Session()
sesion.headers.update({"User-Agent": UA})


def pausa():
    """Pausa educada entre requests: 0.3-0.5 s, aleatoria para no parecer metralleta."""
    time.sleep(random.uniform(0.3, 0.5))


class _ExtractorLinks(HTMLParser):
    """Saca todos los href de una pagina. Parser de la stdlib: sin dependencias nuevas."""

    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            for k, v in attrs:
                if k == "href" and v:
                    self.links.append(v)


def links_de(url, timeout=20):
    """Devuelve los href absolutos de una pagina de indice, o [] si falla."""
    try:
        r = sesion.get(url, timeout=timeout)
        r.raise_for_status()
    except Exception as e:
        print(f"  [WARN] indice inaccesible {url}: {type(e).__name__}: {e}")
        return []
    p = _ExtractorLinks()
    try:
        p.feed(r.text)
    except Exception as e:
        print(f"  [WARN] HTML raro en {url}: {e}")
        return []
    return [urljoin(url, h) for h in p.links]


def midi_valido(datos):
    """Un MIDI real empieza con la firma MThd y tiene un tamano plausible."""
    return (datos is not None
            and datos[:4] == b"MThd"
            and TAM_MIN <= len(datos) <= TAM_MAX)


def descargar(url, referer=None, timeout=30):
    """Baja un archivo; devuelve bytes o None. Nunca lanza: un error se salta."""
    headers = {"Referer": referer} if referer else {}
    try:
        r = sesion.get(url, headers=headers, timeout=timeout)
        r.raise_for_status()
        return r.content
    except Exception:
        return None


def nombre_seguro(texto, hash_corto):
    """Nombre de archivo estable y sin caracteres invalidos de Windows."""
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", texto).strip("_")[:80] or "midi"
    if not base.lower().endswith(".mid"):
        base += ".mid"
    # el hash corto evita colisiones de nombre entre fuentes distintas
    return f"{base[:-4]}_{hash_corto}.mid"


def guardar_lote(genero, candidatos, limite, solo_listar, deadline, vistos):
    """Descarga y valida una lista de (url, referer, nombre_sugerido).

    `vistos` es el set de sha256 ya guardados para ese genero (dedupe global).
    Devuelve cuantos archivos NUEVOS validos se guardaron.
    """
    carpeta = DESTINO / genero
    carpeta.mkdir(parents=True, exist_ok=True)
    nuevos = 0
    for url, referer, sugerido in candidatos:
        if nuevos >= limite:
            break
        if time.monotonic() > deadline:
            print(f"  [TIME] presupuesto agotado en {genero}")
            break
        if solo_listar:
            print(f"  [LISTAR] {url}")
            nuevos += 1
            continue
        datos = descargar(url, referer=referer)
        pausa()
        if not midi_valido(datos):
            continue
        h = hashlib.sha256(datos).hexdigest()
        if h in vistos:
            continue
        vistos.add(h)
        destino = carpeta / nombre_seguro(sugerido, h[:10])
        destino.write_bytes(datos)
        nuevos += 1
    return nuevos


def cargar_hashes_existentes(genero):
    """Dedupe tambien contra corridas anteriores: hashea lo que ya esta en disco."""
    carpeta = DESTINO / genero
    vistos = set()
    if carpeta.is_dir():
        for f in carpeta.glob("*.mid"):
            try:
                vistos.add(hashlib.sha256(f.read_bytes()).hexdigest())
            except OSError:
                pass
    return vistos


# ---------------------------------------------------------------------------
# Fuente: vgmusic.com (videojuegos). Indices planos con <a href="xxx.mid">.
# ---------------------------------------------------------------------------

CONSOLAS_VGMUSIC = [
    "https://www.vgmusic.com/music/console/nintendo/nes/",
    "https://www.vgmusic.com/music/console/nintendo/snes/",
    "https://www.vgmusic.com/music/console/nintendo/n64/",
    "https://www.vgmusic.com/music/console/sony/ps1/",
]


def candidatos_vgmusic(limite_por_consola):
    cands = []
    for indice in CONSOLAS_VGMUSIC:
        links = [u for u in links_de(indice) if u.lower().endswith(".mid")]
        pausa()
        print(f"  vgmusic {indice.rsplit('/', 3)[-3]}/{indice.rsplit('/', 2)[-2]}: "
              f"{len(links)} .mid en el indice")
        # muestreo aleatorio determinista: variedad de juegos, reproducible
        rnd = random.Random(20260811)
        rnd.shuffle(links)
        for u in links[:limite_por_consola]:
            cands.append((u, indice, u.rsplit("/", 1)[-1]))
    return cands


# ---------------------------------------------------------------------------
# Fuente: midiworld.com. La busqueda devuelve links a /download/NNN.
# ---------------------------------------------------------------------------

def candidatos_midiworld(terminos, max_paginas=3):
    cands = []
    for termino in terminos:
        for pagina in range(1, max_paginas + 1):
            url = f"https://www.midiworld.com/search/{pagina}/?q={quote(termino)}"
            links = [u for u in links_de(url) if "/download/" in u]
            pausa()
            if not links:
                break
            print(f"  midiworld q={termino!r} p{pagina}: {len(links)} downloads")
            for u in links:
                num = u.rstrip("/").rsplit("/", 1)[-1]
                cands.append((u, url, f"midiworld_{termino}_{num}"))
    return cands


# ---------------------------------------------------------------------------
# Fuente: freemidi.org. Paginas de genero listan download3-XXXX-titulo;
# el archivo real sale de getter-XXXX con Referer de la pagina de la cancion.
# ---------------------------------------------------------------------------

def candidatos_freemidi(paginas_genero, terminos_busqueda=()):
    cands = []
    paginas = list(paginas_genero)
    for t in terminos_busqueda:
        paginas.append(f"https://freemidi.org/search?q={quote(t)}")
    for pagina in paginas:
        links = links_de(pagina)
        pausa()
        canciones = [u for u in links if "download3-" in u]
        print(f"  freemidi {pagina}: {len(canciones)} canciones")
        for u in canciones:
            m = re.search(r"download3-(\d+)-(.*)", u)
            if not m:
                continue
            getter = urljoin(u, f"getter-{m.group(1)}")
            cands.append((getter, u, f"freemidi_{m.group(2)}"))
    return cands


# ---------------------------------------------------------------------------
# Fuente: bitmidi.com. Hoy (2026-08-11) devolvia 521; se intenta igual y se
# documenta el resultado en el reporte.
# ---------------------------------------------------------------------------

def candidatos_bitmidi(terminos):
    cands = []
    for t in terminos:
        url = f"https://bitmidi.com/search?q={quote(t)}"
        links = links_de(url)
        pausa()
        midis = [u for u in links if u.lower().endswith("-mid")]
        print(f"  bitmidi q={t!r}: {len(midis)} canciones")
        for u in midis:
            # la pagina de cancion /foo-mid sirve el archivo en /uploads via
            # un link directo .mid dentro; para no doblar requests usamos el
            # patron conocido: pagina + '/download' no existe, asi que abrimos
            # la pagina y sacamos el primer .mid
            sub = [x for x in links_de(u) if x.lower().endswith(".mid")]
            pausa()
            if sub:
                cands.append((sub[0], u, u.rsplit("/", 1)[-1]))
    return cands


# ---------------------------------------------------------------------------
# Plan por genero: lista de (nombre_fuente, funcion_que_da_candidatos)
# ---------------------------------------------------------------------------

def plan_para(genero, limite):
    if genero == "videojuegos":
        # limite repartido entre 4 consolas, con margen porque algunos fallan
        por_consola = max(5, (limite // 4) * 2)
        return [("vgmusic", lambda: candidatos_vgmusic(por_consola))]
    if genero == "electro":
        return [
            ("midiworld", lambda: candidatos_midiworld(
                ["electronic", "dance", "techno", "house"])),
            ("freemidi", lambda: candidatos_freemidi(
                ["https://freemidi.org/genre-electronic-dance"])),
            ("bitmidi", lambda: candidatos_bitmidi(["techno", "electronic"])),
        ]
    if genero == "phonk":
        return [
            ("midiworld", lambda: candidatos_midiworld(["phonk", "memphis rap"])),
            ("freemidi", lambda: candidatos_freemidi([], ["phonk"])),
            ("bitmidi", lambda: candidatos_bitmidi(["phonk"])),
        ]
    if genero == "andina":
        return [
            ("midiworld", lambda: candidatos_midiworld(
                ["huayno", "andean", "quena", "el condor pasa", "peru", "bolivia"])),
            ("freemidi", lambda: candidatos_freemidi([], ["condor pasa", "andean"])),
            ("bitmidi", lambda: candidatos_bitmidi(["condor pasa", "huayno"])),
        ]
    raise ValueError(f"genero desconocido: {genero}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--limite", type=int, default=150,
                    help="max archivos validos NUEVOS por genero (default 150)")
    ap.add_argument("--solo-listar", action="store_true",
                    help="solo lista candidatos, no descarga nada")
    ap.add_argument("--presupuesto-seg", type=int, default=840,
                    help="tope duro de tiempo total en segundos (default 840 = 14 min)")
    ap.add_argument("--generos", nargs="*",
                    default=["videojuegos", "electro", "phonk", "andina"])
    args = ap.parse_args()

    deadline = time.monotonic() + args.presupuesto_seg
    reporte = {}

    for genero in args.generos:
        if time.monotonic() > deadline:
            print(f"[TIME] presupuesto global agotado antes de {genero}")
            reporte[genero] = {"total_validos": 0, "fuentes": {},
                               "nota": "sin tiempo: presupuesto agotado"}
            continue
        print(f"\n=== {genero} ===")
        vistos = cargar_hashes_existentes(genero)
        ya_en_disco = len(vistos)
        detalles = {}
        total = 0
        for nombre_fuente, gen_candidatos in plan_para(genero, args.limite):
            if total >= args.limite or time.monotonic() > deadline:
                break
            try:
                cands = gen_candidatos()
            except Exception as e:
                print(f"  [WARN] fuente {nombre_fuente} exploto: {e}")
                detalles[nombre_fuente] = {"candidatos": 0, "guardados": 0,
                                           "error": str(e)}
                continue
            n = guardar_lote(genero, cands, args.limite - total,
                             args.solo_listar, deadline, vistos)
            detalles[nombre_fuente] = {"candidatos": len(cands), "guardados": n}
            total += n
        reporte[genero] = {"total_validos_nuevos": total,
                           "ya_en_disco_antes": ya_en_disco,
                           "fuentes": detalles}
        print(f"  -> {genero}: {total} validos nuevos "
              f"({ya_en_disco} ya estaban en disco)")

    print("\n===== REPORTE FINAL =====")
    print(json.dumps(reporte, indent=2, ensure_ascii=False))
    # conteo real en disco (la verdad final, no lo que creemos haber guardado)
    print("\nConteo REAL en disco:")
    for genero in args.generos:
        carpeta = DESTINO / genero
        n = len(list(carpeta.glob("*.mid"))) if carpeta.is_dir() else 0
        print(f"  {genero}: {n} archivos .mid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
