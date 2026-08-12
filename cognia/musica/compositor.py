# -*- coding: utf-8 -*-
"""Compositor de esqueletos armonicos ESTRUCTURADOS para SymphonyGen.

POR QUE existe: el banco de monotonia midio que la repeticion viene sobre
todo de la CONDICION (esqueleto en loop -> rep_ritmo 0.91; sin condicion ->
0.28). Este modulo genera condiciones con forma A-B-A', ritmo armonico
variable, celdas ritmicas distintas por compas y respiraciones -- variedad
que el modelo orquesta en vez de clonar compases.

Tambien es el text-to-song minimo: texto_a_esqueleto() mapea una descripcion
("una cancion epica de batalla") a caracter por palabras clave, sin LLM.
El planner LLM puede reemplazar ese mapeo mas adelante; el contrato
(caracter + semilla -> esqueleto determinista) no cambia.

Grados en semitonos sobre la tonica; acordes como (grado, [intervalos]).
Todo determinista via sha256(semilla|etiqueta) -- mismo caracter y semilla,
mismo esqueleto byte a byte.
"""
from __future__ import annotations

import sys
from hashlib import sha256
from pathlib import Path

TPQ = 480
COMPAS = TPQ * 4

# acordes: intervalos sobre la fundamental
_M, _m, _d = (0, 4, 7), (0, 3, 7), (0, 3, 6)

# progresiones por caracter: listas de (semitono_sobre_tonica, triada).
# 2 o 3 opciones por caracter para que la semilla elija.
CARACTERES = {
    "triste": {
        "modo": "menor", "bpm": 72, "tonica": 57,  # la menor
        "progresiones": [
            [(0, _m), (8, _M), (3, _M), (7, _M)],          # i VI III VII
            [(0, _m), (5, _m), (7, _M), (0, _m)],          # i iv V i
            [(0, _m), (8, _M), (5, _m), (7, _M)],          # i VI iv V
        ],
    },
    "epica": {
        "modo": "menor", "bpm": 100, "tonica": 50,  # re menor
        "progresiones": [
            [(0, _m), (10, _M), (8, _M), (0, _m)],         # i VII VI i
            [(0, _m), (5, _m), (10, _M), (7, _M)],         # i iv VII V
            [(0, _m), (8, _M), (10, _M), (0, _m)],         # i VI VII i
        ],
    },
    "alegre": {
        "modo": "mayor", "bpm": 116, "tonica": 60,  # do mayor
        "progresiones": [
            [(0, _M), (7, _M), (9, _m), (5, _M)],          # I V vi IV
            [(0, _M), (5, _M), (7, _M), (0, _M)],          # I IV V I
            [(0, _M), (9, _m), (5, _M), (7, _M)],          # I vi IV V
        ],
    },
    "misteriosa": {
        "modo": "menor", "bpm": 84, "tonica": 52,  # mi menor
        "progresiones": [
            [(0, _m), (1, _M), (0, _m), (7, _M)],          # i bII i V
            [(0, _m), (6, _d), (8, _M), (7, _M)],          # i bV° VI V
            [(0, _m), (3, _M), (1, _M), (0, _m)],          # i III bII i
        ],
    },
    "calma": {
        "modo": "mayor", "bpm": 80, "tonica": 55,  # sol mayor
        "progresiones": [
            [(0, _M), (5, _M), (9, _m), (7, _M)],          # I IV vi V
            [(0, _M), (7, _M), (5, _M), (0, _M)],          # I V IV I
        ],
    },
}

# celdas ritmicas de melodia (duraciones en negras, suman 4); 0 = silencio
_CELDAS = [
    [1, 1, 1, 1], [2, 1, 1], [1, 1, 2], [2, 2], [3, 1],
    [1.5, 0.5, 1, 1], [1, 0.5, 0.5, 2], [0.5, 0.5, 1, 1, 1],
    [2, 1.5, 0.5], [1, 2, 1], [4], [2, 1, 0, 1], [1, 0, 1, 2],
]

_PALABRAS = {
    "triste": ("triste", "melanc", "sad", "llor", "pena", "funebre", "lament"),
    "epica": ("epic", "batalla", "guerra", "heroic", "victoria", "combate"),
    "alegre": ("alegre", "feliz", "happy", "fiesta", "bail", "celebr"),
    "misteriosa": ("misterio", "oscur", "suspenso", "terror", "tenebr", "noche"),
    "calma": ("calma", "relax", "paz", "tranquil", "suave", "dormir", "sereno"),
}


def _u(semilla: int, *etiquetas) -> float:
    """Uniforme [0,1) determinista (mismo patron que expresividad)."""
    clave = f"{semilla}|" + "|".join(str(e) for e in etiquetas)
    return int.from_bytes(sha256(clave.encode()).digest()[:8], "big") / 2 ** 64


def _elegir(semilla, etiqueta, opciones):
    return opciones[int(_u(semilla, etiqueta) * len(opciones)) % len(opciones)]


def _escala(tonica: int, modo: str) -> list[int]:
    pasos = (0, 2, 4, 5, 7, 9, 11) if modo == "mayor" else (0, 2, 3, 5, 7, 8, 10)
    return [tonica + p for p in pasos]


def _nota_cercana(objetivo: float, permitidas: list[int]) -> int:
    return min(permitidas, key=lambda p: abs(p - objetivo))


def texto_a_caracter(texto: str) -> str:
    """Descripcion libre -> caracter, por palabras clave (sin LLM)."""
    bajo = texto.lower()
    for caracter, palabras in _PALABRAS.items():
        if any(p in bajo for p in palabras):
            return caracter
    return "epica"  # el default mas orquestal


def componer_esqueleto(caracter: str, ruta_mid, *, compases: int = 24,
                       semilla: int = 0) -> dict:
    """Esqueleto A-B-A' con ritmo armonico variable. Devuelve metadatos.

    A (tercio 1): progresion base, ritmo armonico 1 acorde/compas.
    B (tercio 2): OTRA progresion transportada al relativo, 2 acordes en los
      compases pares, registro de melodia mas agudo.
    A' (tercio 3): vuelve la base con melodia re-sorteada y cierre.
    El ultimo compas de cada seccion respira (solo acorde tenido).
    """
    import miditoolkit

    if caracter not in CARACTERES:
        raise ValueError(f"caracter {caracter!r} (vale {sorted(CARACTERES)})")
    conf = CARACTERES[caracter]
    tonica, modo = conf["tonica"], conf["modo"]
    escala = _escala(tonica, modo)
    permitidas = sorted({p + o for p in escala for o in (0, 12, 24)})

    prog_a = _elegir(semilla, "prog_a", conf["progresiones"])
    prog_b = _elegir(semilla + 1, "prog_b", conf["progresiones"])
    # B al relativo: +3 semitonos desde menor, -3 desde mayor
    despl_b = 3 if modo == "menor" else -3

    midi = miditoolkit.MidiFile(ticks_per_beat=TPQ)
    midi.time_signature_changes = [miditoolkit.TimeSignature(4, 4, 0)]
    melo = miditoolkit.Instrument(program=0, is_drum=False, name="Melody")
    armo = miditoolkit.Instrument(program=0, is_drum=False, name="Piano")

    tercio = max(4, compases // 3)
    centro_prev = tonica + 12

    for c in range(compases):
        t = c * COMPAS
        if c < tercio:
            seccion, prog, despl = "A", prog_a, 0
        elif c < 2 * tercio:
            seccion, prog, despl = "B", prog_b, despl_b
        else:
            seccion, prog, despl = "A2", prog_a, 0

        pos_seccion = c - (0 if seccion == "A" else tercio if seccion == "B" else 2 * tercio)
        respiracion = pos_seccion == tercio - 1

        # ritmo armonico: en B los compases pares llevan 2 acordes
        grados = [prog[pos_seccion % len(prog)]]
        if seccion == "B" and pos_seccion % 2 == 0 and not respiracion:
            grados.append(prog[(pos_seccion + 1) % len(prog)])

        # cierre: el ultimo compas de la pieza cae a la tonica tenida
        if c == compases - 1:
            grados = [prog[0]]

        # el acompanamiento tambien varia su patron por compas: acordes en
        # bloque SIEMPRE producian una orquestacion que los eco-clonaba
        # (medido: rep_ritmo 0.64 con bloques vs 0.28 sin condicion); el
        # patron se sortea por compas entre bloque/arpegio/mitades/contra
        paso = COMPAS // len(grados)
        patron_armo = ("bloque" if respiracion or c == compases - 1 else
                       _elegir(semilla + c, ("armo", seccion),
                               ["bloque", "arpegio", "mitades", "contra"]))
        for gi, (grado, triada) in enumerate(grados):
            raiz = tonica + despl + grado
            ini = t + gi * paso
            armo.notes.append(miditoolkit.Note(100, raiz - 12, ini, ini + paso))
            pitches = [raiz + iv for iv in triada]
            if patron_armo == "bloque":
                for p in pitches:
                    armo.notes.append(miditoolkit.Note(100, p, ini, ini + paso))
            elif patron_armo == "arpegio":
                sub = paso // 4
                orden = pitches + [pitches[1]]
                for k in range(4):
                    armo.notes.append(miditoolkit.Note(
                        100, orden[k % len(orden)], ini + k * sub, ini + (k + 1) * sub))
            elif patron_armo == "mitades":
                for mitad in range(2):
                    for p in pitches:
                        armo.notes.append(miditoolkit.Note(
                            100, p, ini + mitad * paso // 2, ini + (mitad + 1) * paso // 2))
            else:  # contra: acordes al contratiempo de negra
                negra = TPQ
                for k in range(max(1, paso // negra)):
                    off = ini + k * negra + negra // 2
                    if off + negra // 2 <= ini + paso:
                        for p in pitches:
                            armo.notes.append(miditoolkit.Note(
                                100, p, off, off + negra // 2))

        if respiracion or c == compases - 1:
            # acorde tenido, melodia larga: la respiracion es parte de la frase
            objetivo = tonica + despl + grados[0][0] + 12
            p = _nota_cercana(objetivo, permitidas)
            melo.notes.append(miditoolkit.Note(100, p, t, t + COMPAS))
            centro_prev = p
            continue

        # melodia: celda ritmica sorteada por compas, contorno hacia el
        # climax de la seccion (sube hasta 2/3, baja al final)
        celda = _elegir(semilla + c, ("celda", seccion), _CELDAS)
        arco = 1.0 - abs(pos_seccion / max(1, tercio - 1) - 0.66) * 1.5
        objetivo = tonica + 12 + despl + (7 if seccion == "B" else 0) + arco * 7
        pos = 0.0
        for i, dur in enumerate(celda):
            if dur == 0:
                pos += 1
                continue
            deriva = (_u(semilla, "melo", c, i) - 0.5) * 6
            p = _nota_cercana((centro_prev + objetivo) / 2 + deriva, permitidas)
            ini = t + int(pos * TPQ)
            melo.notes.append(miditoolkit.Note(
                100, p, ini, ini + int(dur * TPQ) - 20))
            centro_prev = p
            pos += dur

    midi.instruments = [melo, armo]
    ruta = Path(ruta_mid)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    midi.dump(str(ruta))
    return {"ruta": str(ruta), "caracter": caracter, "bpm": conf["bpm"],
            "compases": compases, "semilla": semilla}


def texto_a_esqueleto(texto: str, ruta_mid, *, compases: int = 24,
                      semilla: int = 0) -> dict:
    """Text-to-song minimo: descripcion libre -> esqueleto compuesto."""
    return componer_esqueleto(texto_a_caracter(texto), ruta_mid,
                              compases=compases, semilla=semilla)


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m cognia.musica.compositor",
        description="Esqueleto armonico estructurado para condicionar SymphonyGen")
    ap.add_argument("caracter", help="caracter o descripcion libre "
                                     f"({', '.join(sorted(CARACTERES))})")
    ap.add_argument("--salida", default="esqueleto.mid")
    ap.add_argument("--compases", type=int, default=24)
    ap.add_argument("--semilla", type=int, default=0)
    args = ap.parse_args(argv)
    meta = texto_a_esqueleto(args.caracter, args.salida,
                             compases=args.compases, semilla=args.semilla)
    print(f"esqueleto {meta['caracter']} en {meta['ruta']} "
          f"({meta['compases']} compases, bpm sugerido {meta['bpm']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
