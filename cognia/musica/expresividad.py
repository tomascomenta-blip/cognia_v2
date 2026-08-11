# -*- coding: utf-8 -*-
"""Post-procesador de expresividad para los MIDIs de SymphonyGen (v1).

POR QUE existe: el vocabulario del vendor (arch/vocab.py) solo tiene
Pitch/Pos/Dur/Legato -- el modelo NO puede generar dinamicas -- y su
exportador escribe TODO a velocity 100 fija, sin tempo, cuantizado a fusas.
El resultado suena plano. Este modulo agrega dinamicas (velocity), fraseo
(CC11), mezcla (CC7) y respiracion (mapa de tempo) SIN tocar el vendor y
SIN mover ninguna nota: el unico contrato con el resto de Cognia es que las
rutas .mid que el caller ya tiene siguen siendo validas (reescritura
in-place atomica).

POR QUE el gate antes del rename: la expresividad jamas puede romper una
entrega. Cada archivo se procesa a un temporal, se re-lee y se compara
contra el original (conteo de notas, onsets tick a tick, rangos de
velocity/CC/tempo); si CUALQUIER chequeo falla, el temporal se descarta y
sale el MIDI plano de siempre.

POR QUE hash sin estado y no random.Random: cada decision aleatoria se
deriva de sha256(seed|etiqueta|pista|nota), asi la salida es byte-identica
para la misma entrada+seed aunque se refactorice el orden de iteracion.

Solo depende de miditoolkit (y mido para la sanidad de bytes del gate),
ambos en venv312 y venv312gpu. Sin torch (regla del repo). Import perezoso:
el proceso principal puede vivir sin miditoolkit y degradar con motivo.
"""
from __future__ import annotations

import argparse
import hashlib
import math
import os
import shutil
import sys
from bisect import bisect_right
from pathlib import Path
from statistics import median, pstdev

MARKER = "COGNIA-EXPR"  # prefijo del marker de idempotencia (tick 0)

# Bases de velocity por rol (constantes de la v1: si algun dia necesitan ser
# configurables, primero se demuestra con oidos, no se abre el knob).
_BASE = {"MELODIA": 88, "CONTRAMELODIA": 78, "BAJO": 74,
         "ACOMPANAMIENTO": 64, "DRUMS": 78, "OUTLINE": 44}
_CC7 = {"MELODIA": 100, "CONTRAMELODIA": 96, "BAJO": 96,
        "ACOMPANAMIENTO": 84, "DRUMS": 100, "OUTLINE": 50}

_NOMBRES_OUTLINE = {"Harmonic Outline", "Reference Outline"}


def _miditoolkit():
    """Import perezoso y tolerante: el motivo legible viaja en el ImportError."""
    try:
        import miditoolkit
        return miditoolkit
    except ImportError as e:
        raise ImportError(
            "expresividad: falta miditoolkit en este python "
            f"({sys.executable}): {e}. Instalalo con pip install miditoolkit") from e


def _u(seed: int, etiqueta: str, idx_pista: int, idx_nota: int) -> float:
    """Uniforme [0,1) sin estado: mismo (seed, etiqueta, pista, nota) => mismo valor."""
    h = hashlib.sha256(f"{seed}|{etiqueta}|{idx_pista}|{idx_nota}".encode()).digest()
    return int.from_bytes(h[:8], "big") / 2 ** 64


def _es_outline(inst) -> bool:
    """Nombre exacto + program 0: un piano real con otro nombre JAMAS cae aqui."""
    return inst.program == 0 and not inst.is_drum and inst.name in _NOMBRES_OUTLINE


def _cc11_elegible(program: int) -> bool:
    """Solo timbres GM que sostienen: cuerdas/ensembles (40-55), vientos (56-79),
    pads (88-95). Pianos, guitarras, organos y leads quedan fuera: su modelo de
    volumen es percusivo o plano y el CC11 les mete bombeo (suena a error)."""
    return 40 <= program <= 79 or 88 <= program <= 95


def _compases(midi, max_tick: int) -> list[dict]:
    """Grilla de compases desde time_signature_changes (4/4 implicito si no hay).

    pulso: negra con puntillo en compuestos (num%3==0 y num>3), si no 4/den.
    Un cambio de metrica corta el compas en curso: la grilla arranca de nuevo
    en el tick del cambio (asi el acento metrico no se corre de fase).
    """
    tpq = midi.ticks_per_beat
    cambios = sorted(midi.time_signature_changes, key=lambda t: t.time)
    if not cambios or cambios[0].time > 0:
        # miditoolkit dumpea 4/4 por defecto; aca lo asumimos igual de explicito.
        class _TS:  # noqa: N801 -- contenedor minimo, no vale un import mas
            numerator, denominator, time = 4, 4, 0
        cambios = [_TS()] + cambios
    out = []
    for i, ts in enumerate(cambios):
        num, den = ts.numerator, ts.denominator
        largo = max(1, round(tpq * 4 * num / den))
        if num % 3 == 0 and num > 3:
            pulso = round(3 * tpq * 4 / den)  # compas compuesto: 720 en x/8
        else:
            pulso = round(tpq * 4 / den)
        fin_tramo = cambios[i + 1].time if i + 1 < len(cambios) else max(max_tick, ts.time + largo)
        t = ts.time
        while t < fin_tramo:
            out.append({"ini": t, "fin": t + largo, "num": num, "den": den,
                        "pulso": pulso, "largo": largo})
            t += largo
    return out


def _idx_compas(tick: int, compases: list[dict]) -> int:
    inicios = [c["ini"] for c in compases]
    return max(0, min(len(compases) - 1, bisect_right(inicios, tick) - 1))


def _grupos_onset(notas) -> list[list]:
    """Notas de una pista agrupadas por onset (ya ordenadas por (start, pitch))."""
    grupos, actual = [], []
    for n in notas:
        if actual and n.start != actual[0].start:
            grupos.append(actual)
            actual = []
        actual.append(n)
    if actual:
        grupos.append(actual)
    return grupos


def _voz_superior(notas) -> list:
    """Una nota por onset: la mas aguda. Es la voz que el oido sigue."""
    return [max(g, key=lambda n: n.pitch) for g in _grupos_onset(notas)]


# ------------------------------------------------------------ clasificacion

def _es_escasa(inst, compases) -> bool:
    """<8 notas, o >=80% de onsets son acordes en bloque de >=1 compas.

    POR QUE: un colchon estatico con arco de frase o swell encima suena a
    error, no a intencion; solo recibe base + acento + balance.
    """
    notas = inst.notes
    if len(notas) < 8:
        return True
    grupos = _grupos_onset(sorted(notas, key=lambda n: (n.start, n.pitch)))
    bloques = 0
    for g in grupos:
        largo = compases[_idx_compas(g[0].start, compases)]["largo"]
        if len(g) >= 2 and min(n.end - n.start for n in g) >= largo:
            bloques += 1
    return bloques / len(grupos) >= 0.8


def _clasificar(midi, compases, outs) -> tuple[list[list[str]], list[bool]]:
    """Roles por pista x ventana de 4 compases + bandera 'escasa' por pista.

    POR QUE por ventana: en musica orquestal el rol MIGRA entre secciones
    (la melodia pasa de cuerdas a vientos); una etiqueta global la pierde.
    outs: bandera de outline por pista, congelada ANTES de tocar el program
    (en modo atenuar el program cambia a 48 y _es_outline dejaria de verla).
    """
    tpq = midi.ticks_per_beat
    fusa = max(1, tpq // 8)
    n_vent = max(1, (len(compases) + 3) // 4)
    escasas = []
    for ip, inst in enumerate(midi.instruments):
        escasas.append(not inst.is_drum and not outs[ip]
                       and _es_escasa(inst, compases))

    roles: list[list[str]] = [["ACOMPANAMIENTO"] * n_vent for _ in midi.instruments]
    for ip, inst in enumerate(midi.instruments):
        if inst.is_drum:
            roles[ip] = ["DRUMS"] * n_vent
        elif outs[ip]:
            roles[ip] = ["OUTLINE"] * n_vent

    for w in range(n_vent):
        ini = compases[w * 4]["ini"]
        ultimo = compases[min(w * 4 + 4, len(compases)) - 1]
        fin = ultimo["fin"]
        n_comp = min(4, len(compases) - w * 4)

        rasgos = {}  # ip -> (pitch_med, densidad, polifonia, var_int)
        for ip, inst in enumerate(midi.instruments):
            if inst.is_drum or outs[ip]:
                continue
            notas = [n for n in inst.notes if ini <= n.start < fin]
            if not notas:
                continue
            pitch_med = median(n.pitch for n in notas)
            densidad = len(notas) / n_comp
            # polifonia: fraccion de muestras (cada fusa) con >=2 notas sonando,
            # sobre las muestras donde suena algo -- mide acordes, no silencio.
            con_algo = con_dos = 0
            for t in range(ini, fin, fusa):
                cuantas = sum(1 for n in notas if n.start <= t < n.end)
                if cuantas >= 1:
                    con_algo += 1
                    if cuantas >= 2:
                        con_dos += 1
            polif = con_dos / con_algo if con_algo else 0.0
            sup = _voz_superior(sorted(notas, key=lambda n: (n.start, n.pitch)))
            saltos = [b.pitch - a.pitch for a, b in zip(sup, sup[1:])]
            var_int = pstdev(saltos) if len(saltos) >= 2 else 0.0
            rasgos[ip] = (pitch_med, densidad, polif, var_int)

        if not rasgos:
            continue

        # BAJO primero: el mas grave, si es grave de verdad y casi monofonico.
        bajo = min(rasgos, key=lambda ip: rasgos[ip][0])
        if rasgos[bajo][0] < 55 and rasgos[bajo][2] < 0.3:
            roles[bajo][w] = "BAJO"
        else:
            bajo = None

        candidatos = [ip for ip in rasgos if ip != bajo]
        if candidatos:
            def _norm(vals):
                lo, hi = min(vals), max(vals)
                # una sola candidata (o empate exacto): 0.5 neutro, no 0/0
                return [(v - lo) / (hi - lo) if hi > lo else 0.5 for v in vals]
            np_, nd, nv = (_norm([rasgos[ip][k] for ip in candidatos]) for k in (0, 1, 3))
            S = {ip: 0.40 * np_[i] + 0.25 * nd[i] + 0.20 * nv[i]
                 + 0.15 * (1 - rasgos[ip][2]) for i, ip in enumerate(candidatos)}
            orden = sorted(candidatos, key=lambda ip: -S[ip])
            if S[orden[0]] >= 0.45:
                mel = orden[0]
                roles[mel][w] = "MELODIA"
                if (len(orden) > 1 and S[orden[1]] >= 0.40
                        and abs(rasgos[orden[1]][0] - rasgos[mel][0]) >= 5):
                    roles[orden[1]][w] = "CONTRAMELODIA"
            # si nadie llega a 0.45 la ventana es tutti homofonico sin melodia

    # Anti-parpadeo: MELODIA en i-1 e i+1 pero no en i => promover en i.
    for ip in range(len(midi.instruments)):
        for w in range(1, n_vent - 1):
            if (roles[ip][w] != "MELODIA" and roles[ip][w - 1] == "MELODIA"
                    and roles[ip][w + 1] == "MELODIA"
                    and roles[ip][w] not in ("DRUMS", "OUTLINE")):
                roles[ip][w] = "MELODIA"
    return roles, escasas


def _rol_dominante(roles_pista: list[str]) -> str:
    """Para el CC7 estatico (un fader por canal): el rol mas frecuente,
    desempatado por importancia."""
    prioridad = ["MELODIA", "CONTRAMELODIA", "BAJO", "DRUMS", "OUTLINE", "ACOMPANAMIENTO"]
    cuentas = {r: roles_pista.count(r) for r in set(roles_pista)}
    return max(cuentas, key=lambda r: (cuentas[r], -prioridad.index(r)))


# ------------------------------------------------------------------- frases

def _detectar_frases(midi, roles, compases) -> list[dict]:
    """Frases sobre la melodia (voz superior); las demas pistas las heredan.

    Devuelve [{ini, fin, p, climax, ultima}] cubriendo [0, fin de la pieza).
    p = posicion del climax REAL (nota mas aguda) clampeada a [0.3, 0.85]:
    el arco de una frase apunta a su nota cumbre, no a una posicion
    estadistica fija.
    """
    tpq = midi.ticks_per_beat
    tol = max(1, round(tpq * 15 / 480))
    fin_pieza = compases[-1]["fin"]

    # Linea melodica global: en cada ventana, la voz superior de SU melodia.
    seq = []
    n_vent = len(roles[0]) if roles else 0
    for w in range(n_vent):
        ini = compases[w * 4]["ini"]
        fin = compases[min(w * 4 + 4, len(compases)) - 1]["fin"]
        for ip, inst in enumerate(midi.instruments):
            if roles[ip][w] == "MELODIA":
                notas = [n for n in inst.notes if ini <= n.start < fin]
                seq.extend(_voz_superior(sorted(notas, key=lambda n: (n.start, n.pitch))))
                break
    seq.sort(key=lambda n: n.start)

    candidatas = []  # (tick, puntaje) de TODAS las fronteras posibles
    barra_prev = 0
    for k in range(len(seq) - 1):
        a, b = seq[k], seq[k + 1]
        ic = _idx_compas(b.start, compases)
        pulso = compases[ic]["pulso"]
        punt = 0
        hueco = b.start - a.end
        if hueco >= pulso:
            punt += 3
        elif hueco >= pulso // 2:
            punt += 2
        ultimas = [n.end - n.start for n in seq[max(0, k - 7):k + 1]]
        if (a.end - a.start) >= 2 * median(ultimas):
            punt += 2
        if abs(b.pitch - a.pitch) >= 7:
            punt += 1
        en_barra = abs(b.start - compases[ic]["ini"]) <= tol
        if en_barra:
            punt += 1
            if ic > barra_prev and (ic - barra_prev) % 4 == 0:
                punt += 1
        if punt >= 3:
            barra_prev = ic
        if punt >= 1:
            candidatas.append((b.start, punt))

    limites = [t for t, p in candidatas if p >= 3]

    def _n_compases(ini, fin):
        return _idx_compas(max(ini, fin - 1), compases) - _idx_compas(ini, compases) + 1

    if not limites:
        # Fallback: sin melodia o sin fronteras => frases fijas de 4 compases.
        cortes = [compases[i]["ini"] for i in range(0, len(compases), 4)]
    else:
        # Minimo 2 compases: una frontera que deja una frase corta se fusiona
        # hacia atras (se descarta la frontera, no la musica).
        cortes = [0]
        for t in limites:
            if _n_compases(cortes[-1], t) >= 2:
                cortes.append(t)
        if len(cortes) > 1 and _n_compases(cortes[-1], fin_pieza) < 2:
            cortes.pop()

    # Maximo 12 compases: cortar en la mejor candidata interna; sin candidata,
    # en la barra a 8 compases exactos del inicio de la frase.
    finales = []
    i = 0
    while i < len(cortes):
        ini = cortes[i]
        fin = cortes[i + 1] if i + 1 < len(cortes) else fin_pieza
        while _n_compases(ini, fin) > 12:
            ic0 = _idx_compas(ini, compases)
            techo = compases[min(ic0 + 12, len(compases) - 1)]["ini"]
            piso = compases[min(ic0 + 2, len(compases) - 1)]["ini"]
            internas = [(t, p) for t, p in candidatas if piso <= t < techo and t > ini]
            if internas:
                corte = max(internas, key=lambda tp: tp[1])[0]
            else:
                corte = compases[min(ic0 + 8, len(compases) - 1)]["ini"]
            if corte <= ini:
                break
            finales.append((ini, corte))
            ini = corte
        finales.append((ini, fin))
        i += 1

    frases = []
    for j, (ini, fin) in enumerate(finales):
        dentro = [n for n in seq if ini <= n.start < fin]
        if dentro:
            climax = max(dentro, key=lambda n: (n.pitch, n.end - n.start, n.start))
            p = (climax.start - ini) / max(1, fin - ini)
        else:
            climax, p = None, 0.5
        frases.append({"ini": ini, "fin": fin, "p": min(0.85, max(0.3, p)),
                       "climax": climax, "ultima": j == len(finales) - 1})
    return frases


def _frase_de(tick: int, frases: list[dict]) -> dict:
    for f in frases:
        if f["ini"] <= tick < f["fin"]:
            return f
    return frases[-1]


def _arco(tick: int, frases: list[dict]) -> float:
    """Offset del arco de frase: -6 -> +10 en el climax -> -8 (-12 la ultima)."""
    f = _frase_de(tick, frases)
    x = (tick - f["ini"]) / max(1, f["fin"] - f["ini"])
    p, fin = f["p"], (-12.0 if f["ultima"] else -8.0)
    if x <= p:
        return -6.0 + 16.0 * (x / p)
    return 10.0 + (fin - 10.0) * ((x - p) / max(1e-9, 1.0 - p))


# ----------------------------------------------------------------- velocity

def _acento_metrico(tick: int, compases: list[dict], tpq: int, drums: bool) -> int:
    """Acento por posicion en el compas. Drums con negativos suavizados: el
    groove necesita las subdivisiones vivas; los ghost notes quedan livianos."""
    tol = max(1, round(tpq * 15 / 480))
    c = compases[_idx_compas(tick, compases)]
    off = tick - c["ini"]
    pulso, num, den = c["pulso"], c["num"], c["den"]

    def _cerca(a, b):
        return abs(a - b) <= tol

    if _cerca(off, 0):
        return 10 if drums else 8
    # fuerte secundario: tiempo 3 en x/4 par; 2o pulso en compuestos; en 3/4 ninguno
    sec = None
    if num % 3 == 0 and num > 3:
        sec = pulso
    elif den == 4 and num % 2 == 0 and num >= 4:
        sec = (num // 2) * pulso
    if sec is not None and _cerca(off, sec):
        return 3 if drums else 4
    if _cerca(off % pulso, 0) or _cerca(off % pulso, pulso):
        return 3 if drums else 0
    corchea = tpq // 2
    if _cerca(off % corchea, 0) or _cerca(off % corchea, corchea):
        return -2 if drums else -3
    return -4 if drums else -5


def _velocidades(midi, roles, escasas, frases, compases, outs, seed, intens,
                 atenuar_outline):
    """Pipeline de velocity (§4). Devuelve por pista los Δduracion diferidos
    de articulacion (se aplican en el paso 6, despues de fijar velocities)."""
    tpq = midi.ticks_per_beat
    corta = round(tpq * 120 / 480)
    tol = max(1, round(tpq * 15 / 480))
    duraciones = {}  # (ip, id(nota)) -> dur nueva candidata

    for ip, inst in enumerate(midi.instruments):
        notas = sorted(inst.notes, key=lambda n: (n.start, n.pitch))
        inst.notes = notas
        if not notas:
            continue

        if outs[ip]:
            if atenuar_outline:
                for n in notas:
                    n.velocity = 44  # colchon fijo: sin vida propia, por diseño
            continue

        rol_v = roles[ip]
        escasa = escasas[ip]
        elegible = (not inst.is_drum and not escasa and _cc11_elegible(inst.program))
        grupos = _grupos_onset(notas)

        # contorno por voz superior: media movil de las ultimas 8 notas
        contornos = []
        pitches_sup = []
        for g in grupos:
            pitches_sup.append(max(n.pitch for n in g))
            ventana = pitches_sup[-8:]
            media = sum(ventana) / len(ventana)
            contornos.append(max(-6, min(6, round((pitches_sup[-1] - media) / 2))))

        # cadenas de repeticion (mismo pitch, onsets monofonicos, hueco < 1/4 pulso)
        repes = [0] * len(grupos)  # posicion en la cadena (0 = no repetida)
        for i in range(1, len(grupos)):
            a, b = grupos[i - 1], grupos[i]
            pulso = compases[_idx_compas(b[0].start, compases)]["pulso"]
            if (len(a) == 1 and len(b) == 1 and a[0].pitch == b[0].pitch
                    and 0 <= b[0].start - a[0].end < pulso // 4):
                repes[i] = repes[i - 1] + 1

        idx_nota = {id(n): k for k, n in enumerate(notas)}
        for gi, g in enumerate(grupos):
            t = g[0].start
            w = min(_idx_compas(t, compases) // 4, len(rol_v) - 1)
            rol = rol_v[w]
            base = float(_BASE[rol])
            # transicion de rol: interpolar la base durante el primer compas
            # de la ventana nueva (un salto seco de 88->64 se OYE como corte)
            if w > 0 and _BASE[rol_v[w - 1]] != _BASE[rol]:
                c0 = compases[min(w * 4, len(compases) - 1)]
                if c0["ini"] <= t < c0["fin"]:
                    frac = (t - c0["ini"]) / c0["largo"]
                    base = _BASE[rol_v[w - 1]] + (base - _BASE[rol_v[w - 1]]) * frac

            acento = _acento_metrico(t, compases, tpq, inst.is_drum)
            arco = 0.0
            if not escasa:
                arco = _arco(t, frases) * (0.5 if inst.is_drum else 1.0)

            pulso = compases[_idx_compas(t, compases)]["pulso"]
            en_downbeat = abs(t - compases[_idx_compas(t, compases)]["ini"]) <= tol
            ordenado = sorted(g, key=lambda n: n.pitch)
            for n in g:
                k = idx_nota[id(n)]
                dur = n.end - n.start
                extra = float(acento) + arco
                if not inst.is_drum:
                    if not escasa:
                        extra += contornos[gi]
                    # balance interno del acorde: punta y fondo se oyen, el
                    # relleno cede -- esto solo limpia media papilla
                    if len(g) >= 2:
                        if n is ordenado[-1]:
                            extra += 3
                        elif n is ordenado[0]:
                            extra += 1
                        else:
                            extra += -5
                    if not escasa:
                        if repes[gi]:
                            extra += max(-8, -4 * repes[gi])
                        if dur <= corta:
                            extra += -2 if en_downbeat else -6
                        if elegible and dur >= pulso:
                            extra += -8  # el cuerpo lo pone el CC11, no el ataque
                extra += round((2 * _u(seed, "jitter", ip, k) - 1) * 3)

                v = base + intens * extra
                if v > 106:
                    v = 106 + (v - 106) * 0.5  # rodilla: no pelear contra 127
                lo = 30 if inst.is_drum else 20
                n.velocity = int(max(lo, min(112, round(v))))

            # ---- duraciones diferidas (se aplican en el paso 6) ----
            ioi = grupos[gi + 1][0].start - t if gi + 1 < len(grupos) else None
            if not inst.is_drum and not escasa:
                if repes[gi] and ioi:
                    nueva = min(g[0].end - g[0].start,
                                round(0.85 * ioi), ioi - round(tpq * 30 / 480))
                    duraciones[(ip, id(g[0]))] = nueva
                if rol == "MELODIA" and len(g) == 1 and ioi and gi + 1 < len(grupos):
                    sig = grupos[gi + 1]
                    misma_frase = _frase_de(t, frases) is _frase_de(sig[0].start, frases)
                    # legato solo DENTRO de la frase: la separacion en la
                    # frontera ES la respiracion, no un defecto. Delta-pitch 0
                    # queda FUERA: la re-articulacion en unisono ES la frase
                    # ("ta-ta-ta"); alargarla a 0.98*IOI funde las repetidas
                    # en una sola nota. Y jamas pisar una duracion que la rama
                    # anti-repeticion ya deposito para esta misma nota.
                    if (len(sig) == 1 and misma_frase
                            and 1 <= abs(sig[0].pitch - g[0].pitch) <= 2
                            and (ip, id(g[0])) not in duraciones):
                        nueva = round(0.98 * ioi)
                        if nueva > g[0].end - g[0].start:
                            duraciones[(ip, id(g[0]))] = nueva

        # fin de frase: la ultima nota respira (si dura al menos un pulso)
        if not inst.is_drum and not escasa:
            for f in frases:
                dentro = [g for g in grupos if f["ini"] <= g[0].start < f["fin"]]
                if not dentro:
                    continue
                pulso = compases[_idx_compas(dentro[-1][0].start, compases)]["pulso"]
                for n in dentro[-1]:
                    if (n.end - n.start) >= pulso and (ip, id(n)) not in duraciones:
                        duraciones[(ip, id(n))] = round(0.9 * (n.end - n.start))

    # chequeo global: la media de la MELODIA debe caer en [80, 92]; si no,
    # desplazar TODAS las pistas melodicas por el mismo entero (preserva el
    # balance relativo en vez de re-tunear pista por pista)
    if intens > 0:
        mel = []
        for ip, inst in enumerate(midi.instruments):
            if inst.is_drum or outs[ip]:
                continue
            for n in inst.notes:
                w = min(_idx_compas(n.start, compases) // 4, len(roles[ip]) - 1)
                if roles[ip][w] == "MELODIA":
                    mel.append(n.velocity)
        if mel:
            media = sum(mel) / len(mel)
            d = 0
            if media < 80:
                d = math.ceil(80 - media)
            elif media > 92:
                d = -math.ceil(media - 92)
            if d:
                for ip, inst in enumerate(midi.instruments):
                    if inst.is_drum or outs[ip]:
                        continue
                    for n in inst.notes:
                        n.velocity = int(max(20, min(112, n.velocity + d)))
    return duraciones


def _aplicar_duraciones(midi, duraciones):
    """Paso 6: cambios de duracion acotados. Nunca <30 ticks, nunca <50% de la
    original, nunca >1.02*IOI -- si el candidato viola el piso, se descarta el
    cambio (mejor la nota original que una nota rota)."""
    tpq = midi.ticks_per_beat
    piso_abs = round(tpq * 30 / 480)
    for ip, inst in enumerate(midi.instruments):
        grupos = _grupos_onset(inst.notes)
        for gi, g in enumerate(grupos):
            ioi = grupos[gi + 1][0].start - g[0].start if gi + 1 < len(grupos) else None
            for n in g:
                clave = (ip, id(n))
                if clave not in duraciones:
                    continue
                dur = n.end - n.start
                nueva = duraciones[clave]
                piso = max(piso_abs, round(0.5 * dur))
                techo = round(1.02 * ioi) if ioi else dur
                nueva = min(nueva, techo)
                if nueva < piso or nueva == dur:
                    continue
                n.end = n.start + nueva


def _micro_timing(midi, roles, escasas, compases, outs, seed):
    """Opt-in (§7): desplaza GRUPOS de onset enteros (jamas se arpegia un
    acorde) en MELODIA/CONTRA/ACOMP. Drums, bajo y outline no se tocan: son
    el reloj. La melodia lidera con sesgo -4 ticks."""
    tpq = midi.ticks_per_beat
    lim = round(tpq * 8 / 480)
    sesgo = round(tpq * 4 / 480)
    primer_onset = min((n.start for i in midi.instruments for n in i.notes), default=0)
    for ip, inst in enumerate(midi.instruments):
        if inst.is_drum or outs[ip] or escasas[ip]:
            continue
        for gi, g in enumerate(_grupos_onset(inst.notes)):
            t = g[0].start
            w = min(_idx_compas(t, compases) // 4, len(roles[ip]) - 1)
            rol = roles[ip][w]
            if rol not in ("MELODIA", "CONTRAMELODIA", "ACOMPANAMIENTO"):
                continue
            if t == primer_onset:
                continue  # el arranque de la pieza no se mueve
            shift = round((2 * _u(seed, "micro", ip, gi) - 1) * 6)
            if rol == "MELODIA":
                shift -= sesgo
            shift = max(-lim, min(lim, shift))
            if t + shift < 0:
                shift = -t
            for n in g:
                n.start += shift
                n.end += shift  # duracion preservada: el grupo se mueve en bloque


# ---------------------------------------------------------------- CC7/CC11

def _canales(midi) -> list[int]:
    """Replica EXACTA de la asignacion de canales del dump de miditoolkit
    (canal = idx % 15 saltando el 9; drums = 9). CC es por canal: hay que
    saber quien comparte canal para no emitir un CC que contamine otra pista."""
    libres = [c for c in range(16) if c != 9]
    return [9 if i.is_drum else libres[idx % len(libres)]
            for idx, i in enumerate(midi.instruments)]


def _generar_cc(midi, roles, escasas, frases, outs, atenuar_outline):
    """CC7 estatico (fader de mezcla, UN evento) + curva CC11 por frase/nota."""
    mt = _miditoolkit()
    tpq = midi.ticks_per_beat
    canales = _canales(midi)
    repetidos = {c for c in canales if canales.count(c) > 1 and c != 9}
    if canales.count(9) > 1:
        repetidos.add(9)
    paso_base = max(1, tpq // 8)  # 60 ticks a 480 tpq
    swell_min = tpq // 2          # 240: por debajo el swell no llega a oirse
    swell_pleno = tpq * 2         # solo la nota larga de verdad respira entera

    for ip, inst in enumerate(midi.instruments):
        inst.control_changes = []
        inst.pitch_bends = []  # invariante duro: cero pitch bends
        if canales[ip] in repetidos:
            continue  # dos curvas en un canal se pisan: nada de CC aqui
        if outs[ip]:
            if atenuar_outline:
                inst.control_changes.append(mt.ControlChange(7, 50, 0))
            continue
        rol = _rol_dominante(roles[ip]) if not inst.is_drum else "DRUMS"
        inst.control_changes.append(mt.ControlChange(7, _CC7[rol], 0))
        if inst.is_drum or not _cc11_elegible(inst.program):
            continue
        # estado conocido: GM arranca CC11 en 127; sin el evento inicial el
        # primer swell sonaria como un escalon hacia abajo
        eventos = [mt.ControlChange(11, 96, 0)]
        if escasas[ip]:
            inst.control_changes.extend(eventos)  # baseline fijo, sin swell
            continue

        notas = inst.notes
        # intervalos donde suena algo (merge): el CC11 solo se muestrea ahi
        intervalos = []
        for n in sorted(notas, key=lambda x: x.start):
            if intervalos and n.start <= intervalos[-1][1]:
                intervalos[-1][1] = max(intervalos[-1][1], n.end)
            else:
                intervalos.append([n.start, n.end])

        def _baseline(t):
            f = _frase_de(t, frases)
            x = (t - f["ini"]) / max(1, f["fin"] - f["ini"])
            p, fin = f["p"], (64.0 if f["ultima"] else 78.0)
            if x <= p:
                return 84.0 + (110.0 - 84.0) * (x / p)
            return 110.0 + (fin - 110.0) * ((x - p) / max(1e-9, 1.0 - p))

        def _swell(t):
            sonando = [n for n in notas
                       if n.start <= t < n.end and (n.end - n.start) >= swell_min]
            if not sonando:
                return 1.0
            n = max(sonando, key=lambda x: x.end - x.start)
            f = _frase_de(n.start, frases)
            pico = 1.15 if (f["climax"] is not None
                            and n.start == f["climax"].start
                            and n.pitch == f["climax"].pitch) else 1.10
            D = n.end - n.start
            # la excursion plena (0.90->pico) es SOLO para notas largas: la
            # misma curva en CADA negra de una linea normal es un serrucho
            # periodico a ~2 Hz -- el mismo bombeo que _cc11_elegible excluye
            # en pianos ("suena a error"). En notas cortas se escala a ~1/3
            # (pico ~1.035): forma sutil sin serruchar el arco de frase.
            esc = 1.0 if D >= swell_pleno else 0.35
            pico = 1.0 + (pico - 1.0) * esc
            dip = 1.0 - 0.10 * esc
            d = t - n.start
            atk = min(round(tpq * 120 / 480), round(0.25 * D))
            if d < atk:
                return dip + (1.0 - dip) * (d / max(1, atk))
            cima = 0.6 * D
            if d < cima:
                return 1.0 + (pico - 1.0) * ((d - atk) / max(1.0, cima - atk))
            return pico + (dip - pico) * ((d - cima) / max(1.0, 0.4 * D))

        paso = paso_base
        while True:
            curva = list(eventos)
            ultimo = 96
            for a, b in intervalos:
                t = a
                while t < b:
                    v = int(max(40, min(118, round(_baseline(t) * _swell(t)))))
                    if abs(v - ultimo) >= 2:
                        curva.append(mt.ControlChange(11, v, t))
                        ultimo = v
                    t += paso
            if len(curva) <= 2000 or paso >= paso_base * 8:
                break
            paso *= 2  # presupuesto excedido: degradar la resolucion, no cortar
        inst.control_changes.extend(curva)
        inst.control_changes.sort(key=lambda c: (c.time, c.number))


# -------------------------------------------------------------------- tempo

def _generar_tempo(midi, frases, compases, seed, bpm_base):
    """Mapa de tempo (§6): rubato senoidal ±1.5%, respiracion entre frases,
    ritardando final. NUNCA mueve ticks: el rubato es solo set_tempo."""
    mt = _miditoolkit()
    tpq = midi.ticks_per_beat
    fase = 2 * math.pi * _u(seed, "fase_tempo", 0, 0)
    fin_pieza = compases[-1]["fin"]
    n = len(compases)
    rit_ini = compases[max(0, n - 2)]["ini"]

    def _rubato(i):
        return bpm_base * (1 + 0.015 * math.sin(2 * math.pi * i / 4 + fase))

    eventos = [(0, float(bpm_base), 0)]  # (tick, bpm, prioridad) -- base explicita
    for i, c in enumerate(compases[1:], start=1):
        if c["ini"] >= rit_ini:
            break
        eventos.append((c["ini"], _rubato(i), 1))

    # respiracion: dip x0.95 en el ultimo pulso antes de cada frontera de
    # frase; el downbeat siguiente (evento de rubato) la deshace solo
    ultima_resp = -10
    for f in frases[:-1]:
        b = f["fin"]
        ic = _idx_compas(b, compases)
        if compases[ic]["ini"] >= rit_ini or ic - ultima_resp < 4:
            continue
        t = b - compases[ic]["pulso"]
        if t <= 0:
            continue
        eventos.append((t, _rubato(_idx_compas(t, compases)) * 0.95, 2))
        ultima_resp = ic

    # ritardando final: rampa 1.00 -> 0.85 en los 2 ultimos compases; si la
    # ultima nota es larga (>= 1 compas), calderon implicito a 0.78
    pulso_fin = compases[-1]["pulso"]
    ultima_nota = max((n_ for i_ in midi.instruments for n_ in i_.notes),
                      key=lambda x: x.end, default=None)
    calderon = (ultima_nota is not None
                and (ultima_nota.end - ultima_nota.start) >= compases[-1]["largo"])
    ts = list(range(rit_ini, fin_pieza, max(1, pulso_fin // 2)))
    for j, t in enumerate(ts):
        factor = 1.0 - 0.15 * (t - rit_ini) / max(1, fin_pieza - rit_ini)
        if calderon and j == len(ts) - 1:
            factor = 0.78
        eventos.append((t, bpm_base * factor, 3))

    # colision de tick: rit > respiracion > rubato; espaciado minimo 120 ticks
    eventos.sort(key=lambda e: (e[0], -e[2]))
    limpios = []
    esp = round(tpq * 120 / 480)
    for t, bpm, pr in eventos:
        if limpios and t - limpios[-1][0] < esp:
            if pr > limpios[-1][2] and limpios[-1][0] != 0:
                limpios[-1] = (t, bpm, pr)
            continue
        limpios.append((t, bpm, pr))
    # presupuesto: <=400 eventos (piezas kilometricas: ralear el rubato)
    while len(limpios) > 400:
        rubatos = [e for e in limpios if e[2] == 1]
        if not rubatos:
            limpios = limpios[:400]
            break
        quitar = set(id(e) for e in rubatos[::2])
        limpios = [e for e in limpios if id(e) not in quitar]

    midi.tempo_changes = [mt.TempoChange(round(bpm, 3), t) for t, bpm, _ in limpios]


# --------------------------------------------------------------------- gate

def _segundos(tempos, hasta: int, tpq: int) -> float:
    ts = sorted(tempos, key=lambda t: t.time)
    total = 0.0
    for i, tc in enumerate(ts):
        ini = max(0, tc.time)
        fin = ts[i + 1].time if i + 1 < len(ts) else hasta
        fin = min(fin, hasta)
        if fin > ini:
            total += (fin - ini) / tpq * 60.0 / tc.tempo
    return total


def _sanear_solapes(midi) -> int:
    """Normaliza solapes de MISMO pitch dentro de cada pista. Devuelve cuantas
    notas se tocaron.

    POR QUE: el vendor emite notas del mismo pitch solapadas (segundo note_on
    antes del note_off anterior; visto en song_2 real: dos pitch 75 arrancando
    juntas en el tick 15360). Al escribir y re-leer, el apareamiento on/off se
    re-baraja y las duraciones "cambian solas" -- el gate veria fantasmas que
    esta capa jamas escribio. En GM ademas ese re-ataque es irreproducible:
    el synth corta la voz de esa tecla. Regla: mismo onset -> queda solo la
    mas larga; solape parcial -> la anterior se trunca 1 tick antes del onset
    siguiente (1 tick ~ 1 ms: inaudible, y deja el apareamiento biyectivo).
    """
    total = 0
    for inst in midi.instruments:
        por_pitch = {}
        for n in inst.notes:
            por_pitch.setdefault(n.pitch, []).append(n)
        vivos_pista = []
        for ns in por_pitch.values():
            # a igual onset, la larga primero: las siguientes son duplicados
            ns.sort(key=lambda x: (x.start, x.start - x.end))
            vivos = []
            for n in ns:
                if vivos and n.start == vivos[-1].start:
                    total += 1
                    continue
                if vivos and vivos[-1].end > n.start:
                    vivos[-1].end = n.start - 1
                    total += 1
                    if vivos[-1].end <= vivos[-1].start:
                        vivos.pop()
                vivos.append(n)
            vivos_pista.extend(vivos)
        inst.notes[:] = sorted(vivos_pista, key=lambda x: (x.start, x.pitch))
    return total


def _gate(ruta_orig, ruta_tmp, *, outline_modo, micro, ref_bpm,
          tempo_gen=True, bypass=False) -> str | None:
    """Compara entrada vs temporal RE-LEIDOS. Devuelve el motivo del fallo o
    None si pasa. POR QUE re-leer y no confiar en los objetos en memoria: lo
    que importa es lo que quedo en los BYTES, no lo que creimos escribir."""
    mt = _miditoolkit()
    import mido
    try:
        mido.MidiFile(str(ruta_tmp))  # sanidad de bytes GM
    except Exception as e:
        return f"el temporal no re-abre con mido: {e}"

    o, n = mt.MidiFile(str(ruta_orig)), mt.MidiFile(str(ruta_tmp))
    if not bypass:
        # el mismo saneo que aplico el pipeline: comparar el original crudo
        # (con solapes) contra el temporal saneado reprobaria archivos sanos
        _sanear_solapes(o)
    tpq = o.ticks_per_beat
    lim_micro = round(tpq * 8 / 480)
    piso_abs = round(tpq * 30 / 480)

    if not any(m.text.startswith(MARKER) for m in n.markers):
        return "falta el marker de idempotencia"

    if bypass:
        # bypass exacto (intensidad<=0): el UNICO cambio legal es el marker.
        # Los chequeos de rango del exportador NO aplican: un .mid ajeno puede
        # traer tempo 90 o velocity 127 y eso no es un fallo NUESTRO -- el
        # invariante del control es IGUALDAD estricta contra el original.
        if len(n.instruments) != len(o.instruments):
            return (f"bypass: conteo de pistas {len(n.instruments)} vs "
                    f"{len(o.instruments)}")
        for ip, (a, b) in enumerate(zip(o.instruments, n.instruments)):
            if a.is_drum != b.is_drum or a.name != b.name or a.program != b.program:
                return f"bypass: pista {ip} cambio is_drum/name/program"
            ka = sorted((x.start, x.end, x.pitch, x.velocity) for x in a.notes)
            kb = sorted((x.start, x.end, x.pitch, x.velocity) for x in b.notes)
            if ka != kb:
                return f"bypass: pista {ip} cambio alguna nota"
            if ([(c.number, c.value, c.time) for c in a.control_changes]
                    != [(c.number, c.value, c.time) for c in b.control_changes]):
                return f"bypass: pista {ip} cambio algun CC"
            if ([(p.pitch, p.time) for p in a.pitch_bends]
                    != [(p.pitch, p.time) for p in b.pitch_bends]):
                return f"bypass: pista {ip} cambio algun pitch bend"
        if ([(round(t.tempo, 4), t.time) for t in o.tempo_changes]
                != [(round(t.tempo, 4), t.time) for t in n.tempo_changes]):
            return "bypass: cambio el mapa de tempo"
        return None

    orig_insts = list(o.instruments)
    esperados = orig_insts
    if outline_modo == "quitar":
        esperados = [i for i in orig_insts if not _es_outline(i)]
        if len(esperados) == len(orig_insts):
            esperados = orig_insts  # no habia outline: nada que quitar
    if len(n.instruments) != len(esperados):
        return (f"conteo de pistas: {len(n.instruments)} vs {len(esperados)} esperadas")

    # 4/4 implicito == 4/4 explicito: el dump de miditoolkit escribe el default
    # si no habia evento, y eso NO es un cambio real de metrica
    ts_o = [(t.numerator, t.denominator, t.time)
            for t in o.time_signature_changes] or [(4, 4, 0)]
    ts_n = [(t.numerator, t.denominator, t.time)
            for t in n.time_signature_changes] or [(4, 4, 0)]
    if ts_o != ts_n:
        return f"time signatures cambiaron: {ts_o} vs {ts_n}"

    for ip, (a, b) in enumerate(zip(esperados, n.instruments)):
        es_out = _es_outline(a)
        if a.is_drum != b.is_drum or a.name != b.name:
            return f"pista {ip}: is_drum/name cambiaron"
        if a.program != b.program and not (es_out and outline_modo == "atenuar"):
            return f"pista {ip}: program {a.program} -> {b.program}"

        na = sorted(a.notes, key=lambda x: (x.start, x.pitch))
        nb = sorted(b.notes, key=lambda x: (x.start, x.pitch))
        if len(na) != len(nb):
            return f"pista {ip}: {len(na)} notas -> {len(nb)}"
        onsets = sorted({x.start for x in na})
        sig_onset = {onsets[i]: (onsets[i + 1] if i + 1 < len(onsets) else None)
                     for i in range(len(onsets))}
        for x, y in zip(na, nb):
            if x.pitch != y.pitch:
                return f"pista {ip}: pitch {x.pitch} -> {y.pitch} en tick {x.start}"
            if micro:
                if abs(y.start - x.start) > lim_micro:
                    return f"pista {ip}: onset movido {x.start} -> {y.start}"
            elif y.start != x.start:
                return f"pista {ip}: onset movido {x.start} -> {y.start}"
            do, dn = x.end - x.start, y.end - y.start
            if dn != do:
                sig = sig_onset.get(x.start)
                techo = round(1.02 * (sig - x.start)) if sig else do
                if dn < max(piso_abs, round(0.5 * do)) or dn > techo:
                    return (f"pista {ip}: duracion {do} -> {dn} fuera de banda "
                            f"en tick {x.start}")

        lo, hi = (30, 112) if b.is_drum else (20, 112)
        if es_out and outline_modo == "atenuar":
            lo, hi = 28, 56
        for y in nb:
            if not (lo <= y.velocity <= hi):
                return f"pista {ip}: velocity {y.velocity} fuera de [{lo},{hi}]"

        if b.pitch_bends:
            return f"pista {ip}: hay pitch bends"
        cc11 = [c for c in b.control_changes if c.number == 11]
        for c in b.control_changes:
            if c.number not in (7, 11):
                return f"pista {ip}: CC{c.number} no permitido"
        if cc11:
            if b.is_drum:
                return f"pista {ip}: CC11 en drums (canal 9)"
            if not _cc11_elegible(b.program):
                return f"pista {ip}: CC11 en program {b.program} no elegible"
            if len(cc11) > 2000:
                return f"pista {ip}: {len(cc11)} eventos CC11 (>2000)"
            for c in cc11:
                if not (40 <= c.value <= 118):
                    return f"pista {ip}: CC11={c.value} fuera de [40,118]"

    if not tempo_gen:
        # sin curva generada, el mapa de tempo del archivo (vacio o propio)
        # tiene que salir INTACTO: bandear un tempo ajeno contra ref_bpm
        # reprobaria archivos sanos que este modulo jamas toco
        if ([(round(t.tempo, 4), t.time) for t in o.tempo_changes]
                != [(round(t.tempo, 4), t.time) for t in n.tempo_changes]):
            return "el mapa de tempo cambio sin curva de tempo activa"
        return None

    if len(n.tempo_changes) > 400:
        return f"{len(n.tempo_changes)} eventos de tempo (>400)"
    compases_n = _compases(n, max((x.end for i in n.instruments for x in i.notes),
                                  default=n.ticks_per_beat * 4))
    rit_ini = compases_n[max(0, len(compases_n) - 2)]["ini"]
    for tc in n.tempo_changes:
        lo = 0.92 if tc.time < rit_ini else 0.78
        if not (lo * ref_bpm - 0.01 <= tc.tempo <= 1.03 * ref_bpm + 0.01):
            return f"tempo {tc.tempo:.1f} en tick {tc.time} fuera de banda"

    # duracion total: misma linea de ticks bajo ambos mapas; se compara contra
    # bpm_base constante para medir SOLO el efecto de la curva
    hasta = max((x.end for i in o.instruments for x in i.notes), default=0)
    if hasta > 0:
        ref = [type("T", (), {"tempo": ref_bpm, "time": 0})()]
        ratio = _segundos(n.tempo_changes or ref, hasta, tpq) / _segundos(ref, hasta, tpq)
        if not (0.995 <= ratio <= 1.125):
            return f"duracion total x{ratio:.3f} fuera de [1.00, 1.12]"
    return None


# ---------------------------------------------------------------- principal

def aplicar_expresividad(ruta_mid, *, semilla: int = 0, intensidad: float = 1.0,
                         outline: str = "quitar", curva_tempo: bool = True,
                         micro_timing: bool = False,
                         bpm_base: float | None = None,
                         escribir_crudo: bool = True) -> str:
    """Aplica la capa de expresividad v1 in-place (temporal + rename atomico).

    Devuelve la ruta escrita (la misma que entro). Si el archivo ya fue
    procesado (marker COGNIA-EXPR) no hace nada: reaplicar in-place es
    irreversible, asi que se rehusa siempre. Si el gate falla levanta
    RuntimeError y el original queda intacto.
    """
    if outline not in ("quitar", "atenuar", "dejar"):
        raise ValueError(f"outline={outline!r} (vale quitar/atenuar/dejar)")
    mt = _miditoolkit()
    ruta = Path(ruta_mid)
    midi = mt.MidiFile(str(ruta))

    if any(m.text.startswith(MARKER) for m in midi.markers):
        print(f"expresividad: {ruta.name} ya procesado (marker), intacto",
              file=sys.stderr)
        return str(ruta)

    # bpm_base=None (default) deriva la base del ARCHIVO: pisar los 90 BPM de
    # un .mid ajeno con 120 cambiaria la velocidad de la pieza en silencio.
    # Un bpm_base EXPLICITO gana sobre el tempo unico del archivo: el unico
    # evento que deja el exportador del vendor es el 120 de fabrica de
    # miditoolkit, un artefacto, no una intencion musical -- sin esto,
    # --bpm 72 se ignoraba sin aviso. Con varios tempos distintos no hay base
    # honesta: se conserva su mapa tal cual (sin curva) y se avisa.
    tempos_orig = sorted(midi.tempo_changes, key=lambda t: t.time)
    if len({round(t.tempo, 3) for t in tempos_orig}) > 1 and curva_tempo:
        print(f"expresividad: {ruta.name} trae su propio mapa de tempo "
              "(varios tempos); se conserva intacto, sin curva de tempo",
              file=sys.stderr)
        curva_tempo = False
    if bpm_base is None:
        bpm_base = tempos_orig[0].tempo if tempos_orig else 120

    marca = mt.Marker(f"{MARKER} v1 seed={semilla} intens={intensidad}", 0)

    if intensidad <= 0:
        # bypass EXACTO para el A/B apareado: solo el marker, ni una nota, ni
        # un CC, ni el outline se tocan -- el control tiene que ser control
        midi.markers.append(marca)
        modo_outline, con_tempo = "dejar", False
    else:
        # los solapes de mismo pitch del vendor rompen la biyeccion on/off del
        # write+read y el gate veria duraciones fantasma; en bypass NO se
        # sanea (el control exige igualdad estricta contra el original)
        saneadas = _sanear_solapes(midi)
        if saneadas:
            print(f"expresividad: {ruta.name}: {saneadas} solapes de mismo "
                  "pitch saneados (defecto del exportador del vendor)",
                  file=sys.stderr)
        if outline == "quitar":
            midi.instruments = [i for i in midi.instruments if not _es_outline(i)]
        # outs se congela ANTES de tocar el program: en atenuar el outline pasa
        # a 48 y _es_outline dejaria de reconocerlo aguas abajo
        outs = [_es_outline(i) for i in midi.instruments]
        if outline == "atenuar":
            for ip, i in enumerate(midi.instruments):
                if outs[ip]:
                    i.program = 48  # colchon de cuerdas, no piano martillado

        max_tick = max((n.end for i in midi.instruments for n in i.notes),
                       default=midi.ticks_per_beat * 4)
        compases = _compases(midi, max_tick)
        roles, escasas = _clasificar(midi, compases, outs)
        frases = _detectar_frases(midi, roles, compases)
        duraciones = _velocidades(midi, roles, escasas, frases, compases, outs,
                                  semilla, float(intensidad), outline == "atenuar")
        _aplicar_duraciones(midi, duraciones)
        if micro_timing:
            _micro_timing(midi, roles, escasas, compases, outs, semilla)
        _generar_cc(midi, roles, escasas, frases, outs, outline == "atenuar")
        if curva_tempo:
            _generar_tempo(midi, frases, compases, semilla, bpm_base)
        midi.markers.append(marca)
        modo_outline, con_tempo = outline, curva_tempo

    tmp = ruta.with_name(f"{ruta.stem}.tmp{os.getpid()}.mid")
    try:
        midi.dump(str(tmp))
        motivo = _gate(ruta, tmp, outline_modo=modo_outline, micro=micro_timing,
                       ref_bpm=(bpm_base if con_tempo else 120),
                       tempo_gen=con_tempo, bypass=(intensidad <= 0))
        if motivo:
            raise RuntimeError(f"expresividad: gate fallo en {ruta.name}: {motivo}")
        if escribir_crudo:
            shutil.copy2(ruta, ruta.with_suffix(".crudo.mid"))
        os.replace(tmp, ruta)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
    return str(ruta)


# ---------------------------------------------------------------------- CLI

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m cognia.musica.expresividad",
        description="Aplica la capa de expresividad v1 a MIDIs de SymphonyGen (in-place)")
    ap.add_argument("ruta", help="archivo .mid o directorio con .mid")
    ap.add_argument("--semilla", type=int, default=0)
    ap.add_argument("--intensidad", type=float, default=1.0)
    ap.add_argument("--outline", choices=["quitar", "atenuar", "dejar"], default="quitar")
    ap.add_argument("--sin-tempo", action="store_true", help="desactiva la curva de tempo")
    ap.add_argument("--micro-timing", action="store_true")
    ap.add_argument("--bpm", type=float, default=None,
                    help="bpm base de la curva de tempo (explicito GANA sobre "
                         "el tempo unico del archivo); sin el, la base sale "
                         "del archivo o 120")
    ap.add_argument("--sin-crudo", action="store_true",
                    help="no guardar la copia <nombre>.crudo.mid")
    args = ap.parse_args(argv)

    ruta = Path(args.ruta)
    if ruta.is_dir():
        # rglob y no glob: la salida real de SymphonyGen anida en cond_*/song_N.mid.
        # .crudo.mid son los respaldos que este mismo modulo deja: procesarlos
        # duplicaria la copia y confundiria el A/B
        archivos = sorted(p for p in ruta.rglob("*.mid")
                          if not p.name.endswith(".crudo.mid"))
    elif ruta.is_file():
        archivos = [ruta]
    else:
        print(f"expresividad: no existe {ruta}", file=sys.stderr)
        return 2
    if not archivos:
        print(f"expresividad: sin .mid en {ruta}", file=sys.stderr)
        return 2

    fallos = 0
    for p in archivos:
        try:
            aplicar_expresividad(
                p, semilla=args.semilla, intensidad=args.intensidad,
                outline=args.outline, curva_tempo=not args.sin_tempo,
                micro_timing=args.micro_timing, bpm_base=args.bpm,
                escribir_crudo=not args.sin_crudo)
            print(f"expresividad: OK {p}")
        except Exception as e:
            fallos += 1
            print(f"expresividad: FALLO {p}: {e}", file=sys.stderr)
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
