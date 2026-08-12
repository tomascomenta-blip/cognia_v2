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
# septimas y power chord: los GENEROS los piden explicitos (el pad de
# electro "luce las septimas"; _5 queda como vocabulario disponible)
_m7, _M7, _7, _5 = (0, 3, 7, 10), (0, 4, 7, 11), (0, 4, 7, 10), (0, 7)

# rejilla de los patrones de genero: 32 fusas por compas de 4/4
FUSA = TPQ // 8

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

# celdas ritmicas de melodia; 0 = UNA negra de silencio, asi que la
# OCUPACION (contando cada 0 como 1) debe sumar 4 exactas -- una celda de 5
# planta su ultima nota en el downbeat del compas siguiente y la melodia
# queda con dos notas simultaneas (_validar_celdas lo corta al importar)
_CELDAS = [
    [1, 1, 1, 1], [2, 1, 1], [1, 1, 2], [2, 2], [3, 1],
    [1.5, 0.5, 1, 1], [1, 0.5, 0.5, 2], [0.5, 0.5, 1, 1, 1],
    [2, 1.5, 0.5], [1, 2, 1], [4], [1, 1, 0, 1], [1, 0, 2],
]

# GENEROS: idiomas completos (escala, progresiones, bajo, bateria, celdas,
# paleta GM). A diferencia de CARACTERES (esqueleto para que SymphonyGen
# orqueste), un genero produce el ARREGLO entero: SymphonyGen solo sabe
# musica sinfonica y estos idiomas se tocan tal cual.
# - escala_pasos: semitonos sobre la tonica (reemplaza mayor/menor).
# - patron_bajo: (fusa, dur_fusas, rol, vel) con rol fund/quinta/octava/
#   tercera sobre el acorde vigente, registro tonica-24..tonica-12; se
#   repite por compas cambiando de fundamental con el acorde.
# - patron_drums: (pitch_GM, [fusas], vel_o_lista); pista is_drum, por compas.
# - drop_hat: indice de la linea de hats que la humanizacion varia (sin esa
#   variacion la bateria clona compases y el banco de monotonia la castiga).
# - crash: (vel, secciones) para el platillo del primer compas de seccion.
GENEROS = {
    # accion chiptune/orquestal hibrido: eolico oscuro-heroico, bajo en
    # galope, fills de toms cerrando cada frase de 4
    "videojuegos": {
        "escala_pasos": (0, 2, 3, 5, 7, 8, 10), "tonica": 52, "bpm": 140,  # mi menor
        "progresiones": [
            [(0, _m), (8, _M), (3, _M), (10, _M)],    # i VI III VII (himno de nivel)
            [(0, _m), (10, _M), (8, _M), (10, _M)],   # i VII VI VII (loop de empuje)
            [(0, _m), (3, _M), (10, _M), (7, _M)],    # i III VII V (cadencia heroica)
        ],
        # galope: corchea + 2 semicorcheas por beat; el beat 4 sube a la
        # quinta como impulso al acorde siguiente
        "patron_bajo": [
            (0, 4, "fund", 100), (4, 2, "fund", 84), (6, 2, "fund", 84),
            (8, 4, "fund", 100), (12, 2, "fund", 84), (14, 2, "fund", 84),
            (16, 4, "fund", 100), (20, 2, "fund", 84), (22, 2, "fund", 84),
            (24, 4, "fund", 100), (28, 2, "quinta", 88), (30, 2, "quinta", 88),
        ],
        "patron_drums": [
            (36, [0, 6, 16, 22], 112),   # el 6 y 22 sincopan contra el galope
            (38, [8, 24], 106),
            (42, list(range(0, 32, 2)),  # fuerte en la fusa par de beat
             [76 if f % 4 == 0 else 56 for f in range(0, 32, 2)]),
            (46, [30], 88),
        ],
        "drop_hat": 2,
        "crash": (115, ("A", "B", "A2")),
        "celdas": [
            [0.5, 0.25, 0.25, 0.5, 0.25, 0.25, 1, 1],  # galope pleno
            [0.5, 0.5, 1, 0.5, 0.5, 1],                # marcha corchea
            [1, 0.5, 0.5, 0.5, 0.5, 1],                # sincopa central
            [2, 0.5, 0.5, 1],                          # nota larga + arranque
            [0.5, 0.5, 0.5, 0.5, 2],                   # carrera y clavada
        ],
        "paleta": {"melodia": 80, "contra": 81, "armonia": 81, "bajo": 38},
    },
    # huayno: pentatonica menor (la melodia SOLO pisa esos 5 grados),
    # bombo en 1 y 3.5, charango repicado, zampona que respira
    "andina": {
        "escala_pasos": (0, 3, 5, 7, 10), "tonica": 57, "bpm": 96,  # la menor penta
        "progresiones": [
            [(0, _m), (3, _M), (0, _m), (7, _M)],     # i III i V
            [(0, _m), (10, _M), (3, _M), (0, _m)],    # i VII III i
            [(0, _m), (5, _m), (3, _M), (7, _M)],     # i iv III V
        ],
        # bombo-esque: fundamental larga en 1, quinta sincopada en 3.5
        "patron_bajo": [
            (0, 12, "fund", 92), (20, 8, "quinta", 78),
        ],
        "patron_drums": [
            (36, [0, 20], 72),                       # dobla al bajo = bombo leguero
            (42, [0, 4, 8, 12, 16, 20, 24, 28], 34),  # chispa suave en corcheas
        ],
        "drop_hat": 1,
        "crash": (42, ("A", "B", "A2")),             # platillo lavado
        "celdas": [
            [1, 0.5, 0.5, 1, 1],           # la celula madre del huayno
            [1, 0.5, 0.5, 1, 0.5, 0.5],    # doblada
            [1.5, 0.5, 1, 1],              # puntillo llanero
            [0.5, 0.5, 1, 0.5, 0.5, 1],    # sincopa de fuga
            [1, 1, 2],                     # cierre de frase
            [1, 1, 0, 1],                  # respiro interno (la zampona respira)
        ],
        "paleta": {"melodia": 75, "contra": 73, "armonia": 24, "bajo": 32},
    },
    # memphis/drift: frigia (el b2 ES el sonido), half-time, 808 larga y
    # cowbell riff hipnotico
    "phonk": {
        "escala_pasos": (0, 1, 3, 5, 7, 8, 10), "tonica": 53, "bpm": 132,  # fa frigio
        "progresiones": [
            [(0, _m), (1, _M), (0, _m), (1, _M)],     # i bII i bII (vaiven frigio)
            [(0, _m), (5, _m), (1, _M), (0, _m)],     # i iv bII i
            [(0, _m), (8, _M), (10, _M), (0, _m)],    # i VI VII i (color para B)
        ],
        # 808: largas graves encadenadas SIN solape (aproxima el slide)
        "patron_bajo": [
            (0, 14, "fund", 108), (14, 2, "fund", 90), (16, 16, "quinta", 100),
        ],
        "patron_drums": [
            (36, [0, 10], 114),                       # el 10 sincopa (trap)
            (38, [16], 108),                          # half-time: SOLO beat 3
            (42, list(range(0, 28, 2)), 62),
            (42, [28, 29, 30, 31], [50, 58, 66, 74]),  # rollo en escalera
            (46, [24], 84),
            (56, [0, 4, 10, 16, 22, 28],              # cowbell riff: el gancho
             [98, 84, 90, 98, 84, 90]),
        ],
        "drop_hat": 2,
        "celdas": [
            [0.75, 0.75, 0.5, 1, 1],                # bounce de puntillos
            [0.5, 0.5, 0.5, 0.5, 1, 0.5, 0.5],      # metralla + apoyo
            [1.5, 0.5, 1.5, 0.5],                   # vaiven largo-corto
            [1, 0.75, 0.75, 1.5],                   # arrastre final
            [4],                                    # pedal (dejar sonar el b2)
        ],
        "paleta": {"melodia": 81, "contra": 38, "armonia": 39, "bajo": 38},
    },
    # house/electro 128: four-on-floor, bajo en octavas al contratiempo,
    # pad que luce las septimas
    "electro": {
        "escala_pasos": (0, 2, 3, 5, 7, 8, 10), "tonica": 57, "bpm": 128,  # la menor
        "progresiones": [
            [(0, _m7), (8, _M7), (3, _M7), (10, _7)],   # i7 VImaj7 IIImaj7 VII7
            [(0, _m7), (5, _m7), (8, _M7), (7, _m7)],   # i7 iv7 VImaj7 v7
            [(0, _m7), (10, _7), (8, _M7), (10, _7)],   # i7 VII7 VImaj7 VII7
        ],
        # octavas en corcheas: la octava (offbeat) SIEMPRE mas fuerte que la
        # fundamental -- el bombeo va al contratiempo
        "patron_bajo": [
            (0, 4, "fund", 96), (4, 4, "octava", 104),
            (8, 4, "fund", 96), (12, 4, "octava", 104),
            (16, 4, "fund", 96), (20, 4, "octava", 104),
            (24, 4, "fund", 96), (28, 4, "octava", 104),
        ],
        "patron_drums": [
            (36, [0, 8, 16, 24], 112),
            (39, [8, 24], 100),
            (42, [4, 12, 20, 28], 82),                     # el "ts" del house
            (42, [2, 6, 10, 14, 18, 22, 26, 30], 44),      # ghost de semicorchea
        ],
        "drop_hat": 3,
        "crash": (110, ("A", "A2")),
        "celdas": [
            [0.5, 1, 1, 1, 0.5],           # entra y sale en offbeat
            [0.5, 0.5, 1, 0.5, 0.5, 1],    # stab sincopado
            [1, 0.5, 1, 0.5, 1],           # cruce de acentos
            [0.5, 1.5, 0.5, 1.5],          # dos apoyos anticipados
            [0, 1, 1, 1],                  # calla el beat 1 (habla el kick)
        ],
        "paleta": {"melodia": 80, "contra": 81, "armonia": 90, "bajo": 38},
    },
}

def _validar_celdas() -> None:
    """Chequeo al importar: cada celda ritmica ocupa EXACTAMENTE 4 negras,
    contando cada 0 como una negra de silencio. POR QUE es un chequeo y no
    un comentario: cuatro celdas llegaron a sumar 5 ([2,1,0,1] y compania)
    y su ultima nota caia en el downbeat del compas SIGUIENTE, dejando dos
    notas de melodia simultaneas -- la prosa no lo impidio, esto si."""
    for origen, celdas in ([("_CELDAS", _CELDAS)] +
                           [(f"GENEROS[{g!r}]", conf["celdas"])
                            for g, conf in GENEROS.items()]):
        for celda in celdas:
            ocupa = sum(d if d else 1 for d in celda)
            if ocupa != 4:
                raise ValueError(f"celda {celda} de {origen} ocupa {ocupa} "
                                 "negras (deben ser 4: pisa el compas siguiente)")


_validar_celdas()

# variantes de acompanamiento por genero: listas de (fusa, dur_fusas).
# POR QUE variantes: el patron unico del idioma en loop dispara rep_ritmo
# del banco (compas identico al anterior); sortear entre 2-3 realizaciones
# del MISMO color lo rompe (la leccion del sorteo bloque/arpegio de
# componer_esqueleto). La variante 0 es siempre la base del spec.
_ARMO_GENERO = {
    "videojuegos": [[(0, 16), (16, 16)],                       # blancas (base)
                    [(0, 32)],
                    [(4, 4), (12, 4), (20, 4), (28, 4)]],
    "andina": [[(f, 4) for f in range(0, 32, 4)],              # repicado corcheas
               [(0, 8), (8, 8), (16, 8), (24, 8)],
               [(0, 16), (16, 16)]],
    "phonk": [[(0, 32)],                                       # tenido grave (base)
              [(0, 16), (16, 16)],
              [(0, 28), (28, 4)]],
    "electro": [[(0, 32)],                                     # redonda (base)
                [(0, 16), (16, 16)],
                [(0, 28), (28, 4)]],
}
# registro y velocity base de la armonia por genero (expresividad modula despues)
_ARMO_OCT = {"videojuegos": 0, "andina": 12, "phonk": -12, "electro": 0}
_ARMO_VEL = {"videojuegos": 72, "andina": 48, "phonk": 60, "electro": 58}

_PALABRAS = {
    "triste": ("triste", "melanc", "sad", "llor", "pena", "funebre", "lament"),
    "epica": ("epic", "batalla", "guerra", "heroic", "victoria", "combate"),
    "alegre": ("alegre", "feliz", "happy", "fiesta", "bail", "celebr"),
    "misteriosa": ("misterio", "oscur", "suspenso", "terror", "tenebr", "noche"),
    "calma": ("calma", "relax", "paz", "tranquil", "suave", "dormir", "sereno"),
}

# palabras de genero: se chequean ANTES que las de caracter ("phonk oscuro"
# es phonk, no misteriosa)
_PALABRAS_GENERO = {
    "videojuegos": ("videojuego", "chiptune", "8-bit", "8 bit", "8bit",
                    "arcade", "nivel", "boss", "gamer", "game"),
    "andina": ("andin", "huayno", "zampon", "quena", "charango", "peru",
               "bolivia", "folclor"),
    "phonk": ("phonk", "memphis", "drift", "808", "cowbell"),
    "electro": ("electro", "house", "techno", "edm", "club", "rave"),
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
    """Descripcion libre -> caracter O genero, por palabras clave (sin LLM)."""
    bajo = texto.lower()
    for genero, palabras in _PALABRAS_GENERO.items():
        if any(p in bajo for p in palabras):
            return genero
    for caracter, palabras in _PALABRAS.items():
        if any(p in bajo for p in palabras):
            return caracter
    return "epica"  # el default mas orquestal


def componer_esqueleto(caracter: str, ruta_mid, *, compases: int = 24,
                       semilla: int = 0) -> dict:
    """Esqueleto A-B-A' con ritmo armonico variable. Devuelve metadatos.

    A (tercio 1): progresion base, ritmo armonico 1 acorde/compas.
    B (tercio 2): OTRA progresion en la MISMA tonalidad, 2 acordes en los
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

    progs = conf["progresiones"]
    prog_a = _elegir(semilla, "prog_a", progs)
    # B: OTRA progresion en la MISMA tonalidad (patron de componer_genero;
    # si el sorteo repite, tomar la siguiente). POR QUE no "al relativo"
    # sumando +-3 a las raices: el relativo COMPARTE las notas de la escala,
    # no desplaza las fundamentales; transponer cromaticamente metia acordes
    # con clases foraneas (do# en do mayor) mientras la melodia seguia
    # snapeada a la escala original -> choques de semitono ~2x (medido).
    idx_b = int(_u(semilla + 1, "prog_b") * len(progs)) % len(progs)
    if progs[idx_b] is prog_a:
        idx_b = (idx_b + 1) % len(progs)
    prog_b = progs[idx_b]

    midi = miditoolkit.MidiFile(ticks_per_beat=TPQ)
    midi.time_signature_changes = [miditoolkit.TimeSignature(4, 4, 0)]
    # el bpm del caracter va AL ARCHIVO, no solo a la metadata devuelta:
    # sin este TempoChange cualquier ruta que renderice el esqueleto directo
    # (midi_a_wav/producir) suena a 120 y los delays tempo-relativos de
    # produccion calculan la negra equivocada; para SymphonyGen sigue
    # siendo un bpm sugerido (el CLI lo imprime igual)
    midi.tempo_changes = [miditoolkit.TempoChange(conf["bpm"], 0)]
    melo = miditoolkit.Instrument(program=0, is_drum=False, name="Melody")
    armo = miditoolkit.Instrument(program=0, is_drum=False, name="Piano")

    tercio = max(4, compases // 3)
    centro_prev = tonica + 12

    for c in range(compases):
        t = c * COMPAS
        if c < tercio:
            seccion, prog = "A", prog_a
        elif c < 2 * tercio:
            seccion, prog = "B", prog_b
        else:
            seccion, prog = "A2", prog_a

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
            raiz = tonica + grado
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
            objetivo = tonica + grados[0][0] + 12
            p = _nota_cercana(objetivo, permitidas)
            melo.notes.append(miditoolkit.Note(100, p, t, t + COMPAS))
            centro_prev = p
            continue

        # melodia: celda ritmica sorteada por compas, contorno hacia el
        # climax de la seccion (sube hasta 2/3, baja al final)
        celda = _elegir(semilla + c, ("celda", seccion), _CELDAS)
        arco = 1.0 - abs(pos_seccion / max(1, tercio - 1) - 0.66) * 1.5
        objetivo = tonica + 12 + (7 if seccion == "B" else 0) + arco * 7
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


def _nota_rol(raiz: int, triada, rol: str) -> int:
    """Nota del bajo segun el rol pedido, registro tonica-24..tonica-12
    (la raiz vive en tonica..tonica+11, asi que raiz-24 cae en la banda)."""
    fund = raiz - 24
    if rol == "quinta":
        return fund + 7
    if rol == "octava":
        return fund + 12
    if rol == "tercera":
        return fund + triada[1]
    return fund


def _golpe(drums, t, pitch, fusa, vel):
    import miditoolkit
    ini = t + fusa * FUSA
    drums.notes.append(miditoolkit.Note(vel, pitch, ini, ini + FUSA // 2))


def _drums_compas(drums, genero, conf, t, c, seccion, pos, tercio, respira,
                  ultimo_pieza, semilla):
    """Bateria de UN compas: base del genero + crash de seccion + drops de
    B + fill de cierre + humanizacion determinista de hats."""
    if genero == "phonk" and respira:
        # respiracion phonk: solo el cowbell marca (la 808 sigue en el bajo)
        _golpe(drums, t, 56, 0, 98)
        _golpe(drums, t, 56, 16, 98)
        return
    if genero == "andina" and respira:
        _golpe(drums, t, 36, 0, 72)  # solo bombo: la frase toma aire
        return
    if genero == "electro" and respira:
        return  # el suspiro pre-drop: cero bateria
    if ultimo_pieza:
        if genero == "videojuegos":  # cierra con crash + fundamental tenida
            _golpe(drums, t, 49, 0, 115)
            _golpe(drums, t, 36, 0, 112)
            return
        if genero == "electro":      # kick en 0 + acorde final tenido
            _golpe(drums, t, 36, 0, 112)
            return

    cr = conf.get("crash")
    if cr and pos == 0 and seccion in cr[1]:
        _golpe(drums, t, 49, 0, cr[0])

    saltar = set()
    if genero == "phonk" and seccion == "B":
        saltar = {0, 5}      # drop invertido: caen kick y cowbell
    elif genero == "electro" and seccion == "B":
        saltar = {0, 1, 2}   # breakdown: solo quedan los ghost hats

    fill = genero == "videojuegos" and (pos % 4 == 3 or respira)

    # humanizacion determinista: en compases impares cae UN hat sorteado
    # entre las fusas que NINGUNA otra linea pisa (si cayera una compartida
    # el patron de onsets no cambia y el banco lo cuenta como clon)
    drop = None
    if pos % 2 == 1:
        di = conf["drop_hat"]
        otros = {f for idx, (_p, fs, _v) in enumerate(conf["patron_drums"])
                 if idx != di and idx not in saltar for f in fs}
        cands = [j for j, f in enumerate(conf["patron_drums"][di][1])
                 if f not in otros]
        if cands:
            drop = (di, cands[int(_u(semilla, "drophat", genero, c)
                                  * len(cands)) % len(cands)])

    for idx, (pitch, fusas, vel) in enumerate(conf["patron_drums"]):
        if idx in saltar:
            continue
        vels = vel if isinstance(vel, (list, tuple)) else [vel] * len(fusas)
        for j, (f, v) in enumerate(zip(fusas, vels)):
            if drop == (idx, j):
                continue
            if fill and f >= 24:
                continue  # el beat 4 del fill lo toman los toms
            _golpe(drums, t, pitch, f, v)

    if fill:
        # escalera de toms 96->116 cerrando la frase (el silencio de la
        # melodia lo llena el drum-fill, no el acorde tenido)
        toms = [(50, 24), (50, 25), (47, 26), (47, 27),
                (45, 28), (45, 29), (45, 30), (45, 31)]
        for k, (pitch, f) in enumerate(toms):
            _golpe(drums, t, pitch, f, 96 + round(20 * k / 7))
    if genero == "electro" and seccion != "B" and (c % 2 == 0 or seccion == "A2"):
        _golpe(drums, t, 46, 28, 92)  # open: compases pares; en el drop todos


def _bajo_compas(bajo, contra, genero, conf, t, seccion, pos, grado, triada,
                 raiz, respira, ultimo_pieza):
    """Bajo idiomatico de UN compas (y el doblaje de la 808 en phonk B)."""
    import miditoolkit
    if genero == "andina" and respira:
        return  # "solo bombo y acorde tenido del charango": el bajo calla
    pb = conf["patron_bajo"]
    if genero == "phonk" and respira:
        pb = [(0, 32, "fund", 108)]   # la 808 sola sostiene el compas
    elif genero == "electro" and seccion == "B":
        pb = [(0, 32, "fund", 70)]    # breakdown: fundamentales tenidas
    elif ultimo_pieza and genero in ("videojuegos", "electro"):
        pb = [(0, 32, "fund", 100)]   # cierre: fundamental tenida
    elif pos % 4 == 3:
        # cierre de frase: el bajo camina al proximo acorde. POR QUE: sin
        # esto el patron se clona compas a compas y rep_ritmo se dispara
        if genero == "videojuegos":
            pb = [e for e in pb if e[0] < 24] + [
                (24, 2, "fund", 100), (26, 2, "tercera", 92),
                (28, 2, "quinta", 88), (30, 2, "quinta", 88)]
        elif genero == "andina":
            pb = pb + [(28, 4, "tercera", 70)]
        elif genero == "electro":
            pb = pb[:-1] + [(28, 2, "octava", 104), (30, 2, "quinta", 96)]
        # phonk NO camina: el loop hipnotico de la 808 es el idioma
    for f, dur, rol, vel in pb:
        if genero == "phonk" and grado == 1 and rol == "quinta":
            rol = "fund"  # sobre el bII la 808 baja al semitono: ES el genero
        p = _nota_rol(raiz, triada, rol)
        ini = t + f * FUSA
        bajo.notes.append(miditoolkit.Note(vel, p, ini, ini + dur * FUSA - 5))
        if genero == "phonk" and seccion == "B" and not respira:
            # el synth contra dobla la 808 una octava arriba (tension por resta)
            contra.notes.append(miditoolkit.Note(80, p + 12, ini,
                                                 ini + dur * FUSA - 5))


def _armo_compas(armo, genero, t, c, seccion, raiz, triada, respira,
                 ultimo_pieza, semilla):
    """Armonia de UN compas: variante sorteada del idioma o acorde tenido."""
    import miditoolkit
    if genero == "phonk" and (seccion == "B" or respira):
        return  # el drop resta el pad; la respiracion phonk calla todo
    pitches = [raiz + _ARMO_OCT[genero] + iv for iv in triada]
    if (respira and genero != "videojuegos") or ultimo_pieza:
        # acorde tenido: la respiracion es parte de la frase (en videojuegos
        # el hueco lo llena el drum-fill y la armonia sigue su patron)
        var = [(0, 32)]
    else:
        var = _elegir(semilla + c, ("garmo", genero, seccion),
                      _ARMO_GENERO[genero])
    vel = _ARMO_VEL[genero]
    for f, dur in var:
        for p in pitches:
            armo.notes.append(miditoolkit.Note(vel, p, t + f * FUSA,
                                               t + (f + dur) * FUSA - 5))


def componer_genero(genero: str, ruta_mid, *, compases: int = 24,
                    semilla: int = 0) -> dict:
    """Arreglo COMPLETO idiomatico: Melody + Contra + Chords + Bass + Drums.

    Mismo contrato que componer_esqueleto (determinista via _u, forma
    A-B-A' con respiraciones) pero con el IDIOMA del genero: su escala,
    sus progresiones, su bajo, su bateria GM y su paleta de programas.
    B muta segun el genero (contramelodia en saw, fuga con quena, drop
    invertido, breakdown) y los cierres de frase llevan fill/caminata:
    el banco de monotonia castiga el loop y esas variaciones lo rompen.
    """
    import miditoolkit

    if genero not in GENEROS:
        raise ValueError(f"genero {genero!r} (vale {sorted(GENEROS)})")
    conf = GENEROS[genero]
    tonica = conf["tonica"]
    permitidas = sorted({tonica + p + o for p in conf["escala_pasos"]
                         for o in (0, 12, 24)})

    progs = conf["progresiones"]
    prog_a = _elegir(semilla, ("gen", genero, "prog_a"), progs)
    # B SIEMPRE con otra progresion: si el sorteo repite, tomar la siguiente
    idx_b = int(_u(semilla + 1, ("gen", genero, "prog_b")) * len(progs)) % len(progs)
    if progs[idx_b] is prog_a:
        idx_b = (idx_b + 1) % len(progs)
    prog_b = progs[idx_b]

    pal = conf["paleta"]
    midi = miditoolkit.MidiFile(ticks_per_beat=TPQ)
    midi.time_signature_changes = [miditoolkit.TimeSignature(4, 4, 0)]
    midi.tempo_changes = [miditoolkit.TempoChange(conf["bpm"], 0)]
    melo = miditoolkit.Instrument(program=pal["melodia"], is_drum=False,
                                  name="Melody")
    contra = miditoolkit.Instrument(program=pal["contra"], is_drum=False,
                                    name="Contra")
    armo = miditoolkit.Instrument(program=pal["armonia"], is_drum=False,
                                  name="Chords")
    bajo = miditoolkit.Instrument(program=pal["bajo"], is_drum=False,
                                  name="Bass")
    drums = miditoolkit.Instrument(program=0, is_drum=True, name="Drums")

    tercio = max(4, compases // 3)
    centro_prev = tonica + 12

    for c in range(compases):
        t = c * COMPAS
        if c < tercio:
            seccion, prog = "A", prog_a
        elif c < 2 * tercio:
            seccion, prog = "B", prog_b
        else:
            seccion, prog = "A2", prog_a
        pos = c - {"A": 0, "B": tercio, "A2": 2 * tercio}[seccion]
        ultimo_pieza = c == compases - 1
        grado, triada = prog[0] if ultimo_pieza else prog[pos % len(prog)]
        raiz = tonica + grado

        # quien respira depende del genero (ver la forma de cada idioma)
        if genero == "videojuegos":
            respira = pos == tercio - 1 and seccion in ("A", "B")
        elif genero == "electro":
            respira = pos == tercio - 1 and seccion == "B"
        else:  # andina y phonk: al final de TODAS las secciones
            respira = pos == tercio - 1 or ultimo_pieza

        _drums_compas(drums, genero, conf, t, c, seccion, pos, tercio,
                      respira, ultimo_pieza, semilla)
        _bajo_compas(bajo, contra, genero, conf, t, seccion, pos, grado,
                     triada, raiz, respira, ultimo_pieza)
        _armo_compas(armo, genero, t, c, seccion, raiz, triada, respira,
                     ultimo_pieza, semilla)

        # ---- melodia ----
        if respira or (ultimo_pieza and genero in ("videojuegos", "electro")):
            # las respiraciones callan la melodia (el genero llena el hueco);
            # videojuegos/electro cierran la pieza con la fundamental tenida
            if ultimo_pieza and genero == "videojuegos":
                p = _nota_cercana(tonica + 12, permitidas)
                melo.notes.append(miditoolkit.Note(100, p, t, t + COMPAS - 20))
            elif ultimo_pieza and genero == "electro":
                p = _nota_cercana(tonica + 12, permitidas)
                contra.notes.append(miditoolkit.Note(100, p, t, t + COMPAS - 20))
            continue

        octava_b = 0
        if seccion == "B":
            # la mutacion de registro de B es parte del idioma: sube en
            # videojuegos/andina, BAJA en phonk (tension por resta)
            octava_b = {"videojuegos": 12, "andina": 12,
                        "phonk": -12, "electro": 0}[genero]
        celdas = conf["celdas"]
        if genero == "andina" and seccion == "B":
            celdas = celdas[:2]  # la fuga usa solo las celulas mas movidas
        celda = _elegir(semilla + c, ("gcelda", genero, seccion), celdas)
        arco = 1.0 - abs(pos / max(1, tercio - 1) - 0.66) * 1.5
        objetivo = tonica + 12 + octava_b + arco * 7

        destino = melo
        if genero == "videojuegos" and seccion == "B":
            destino = contra   # la melodia sube la octava y la toma el saw
        elif genero == "electro" and seccion == "A2":
            destino = contra   # el climax del drop pasa al saw

        acordes_p = sorted({raiz + 12 + octava_b + iv + o
                            for iv in triada for o in (-12, 0, 12)})
        pos_t = 0.0
        for i, dur in enumerate(celda):
            if dur == 0:
                pos_t += 1
                continue
            deriva = (_u(semilla, "gmelo", genero, c, i) - 0.5) * 6
            bruto = (centro_prev + objetivo) / 2 + deriva
            if i == 0:
                # el arranque del compas ancla en el acorde vigente y luego
                # se ajusta a la escala del genero (la penta andina manda)
                p = _nota_cercana(_nota_cercana(bruto, acordes_p), permitidas)
            else:
                p = _nota_cercana(bruto, permitidas)
            ini = t + int(pos_t * TPQ)
            destino.notes.append(miditoolkit.Note(100, p, ini,
                                                  ini + int(dur * TPQ) - 20))
            if genero == "andina" and seccion == "B":
                # la quena dobla a la zampona una octava abajo (la fuga)
                contra.notes.append(miditoolkit.Note(88, p - 12, ini,
                                                     ini + int(dur * TPQ) - 20))
            centro_prev = p
            pos_t += dur

        if genero == "videojuegos" and seccion == "B":
            # el square (80) pasa a contramelodia simple bajo el saw
            celda2 = _elegir(semilla + c, ("gcontra", genero), conf["celdas"])
            pos_t, centro2 = 0.0, tonica + 5
            for i, dur in enumerate(celda2):
                if dur == 0:
                    pos_t += 1
                    continue
                deriva = (_u(semilla, "gcontra", genero, c, i) - 0.5) * 6
                p2 = _nota_cercana(centro2 + deriva, permitidas)
                ini = t + int(pos_t * TPQ)
                melo.notes.append(miditoolkit.Note(84, p2, ini,
                                                   ini + int(dur * TPQ) - 20))
                centro2 = p2
                pos_t += dur

    midi.instruments = [melo, contra, armo, bajo, drums]
    ruta = Path(ruta_mid)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    midi.dump(str(ruta))
    return {"ruta": str(ruta), "genero": genero, "bpm": conf["bpm"],
            "compases": compases, "semilla": semilla, "paleta": dict(pal)}


def texto_a_esqueleto(texto: str, ruta_mid, *, compases: int = 24,
                      semilla: int = 0) -> dict:
    """Text-to-song minimo: descripcion libre -> esqueleto o arreglo.

    Si el texto matchea un GENERO va al arreglo completo (componer_genero);
    si no, al esqueleto por caracter para que SymphonyGen orqueste.
    """
    etiqueta = texto_a_caracter(texto)
    if etiqueta in GENEROS:
        return componer_genero(etiqueta, ruta_mid,
                               compases=compases, semilla=semilla)
    return componer_esqueleto(etiqueta, ruta_mid,
                              compases=compases, semilla=semilla)


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m cognia.musica.compositor",
        description="Esqueleto armonico estructurado para condicionar SymphonyGen")
    ap.add_argument("caracter", help="caracter, genero o descripcion libre "
                                     f"({', '.join(sorted(CARACTERES))}; "
                                     f"generos: {', '.join(sorted(GENEROS))})")
    ap.add_argument("--salida", default="esqueleto.mid")
    ap.add_argument("--compases", type=int, default=24)
    ap.add_argument("--semilla", type=int, default=0)
    args = ap.parse_args(argv)
    meta = texto_a_esqueleto(args.caracter, args.salida,
                             compases=args.compases, semilla=args.semilla)
    que = ("arreglo " + meta["genero"] if "genero" in meta
           else "esqueleto " + meta["caracter"])
    print(f"{que} en {meta['ruta']} "
          f"({meta['compases']} compases, bpm sugerido {meta['bpm']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
