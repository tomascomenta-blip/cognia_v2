# -*- coding: utf-8 -*-
"""Banco de SINTESIS del modo RLM: contar, comparar y cruzar hilos.

POR QUE EXISTE (2026-08-18). Todo lo medido del RLM en este repo es
LOCALIZACION de aguja literal: e2e_rlm_smoke.py y rlm_escala.py esconden un
token hex y preguntan por el. Eso mide BUSCAR. Nadie midio SINTESIS: agregar
sobre muchos documentos (contar), poner dos documentos uno al lado del otro
(comparar) o encadenar dos saltos entre documentos distintos (cruzar hilos).
El propio docstring de cognia/agent/rlm.py declara ese limite; este banco es
el examen que lo cierra.

EL DISENO EN UNA LINEA: cuatro brazos sobre las MISMAS preguntas.

  azar_uniforme  sortea del espacio de respuestas que la pregunta declara.
  azar_marginal  sortea de la distribucion EMPIRICA de respuestas del mismo
                 tipo (leave-one-out): el adivinador que conoce el banco pero
                 NO el corpus. Es la referencia PREREGISTRADA, la dificil.
  tonto          una sola llamada con "todo lo que quepa en la ventana"
                 (truncado por la cabeza) y la pregunta al final.
  rlm            correr_rlm sobre el corpus entero.

Y dos brazos GRATIS que no gastan GPU pero deciden si el banco sirve:

  oraculo        el calificador sobre la verdad. Tiene que dar 100%: si no,
                 el banco no es respondible y cualquier numero de arriba es
                 ruido del instrumento.
  techo_tonto    el oraculo aplicado SOLO a lo que el brazo tonto alcanzo a
                 ver. Separa "el tonto fallo porque el modelo no pudo" de
                 "fallo porque la informacion no estaba en su ventana".

TRES CELDAS, LAS MISMAS PREGUNTAS. El corpus lleva los MISMOS documentos y las
MISMAS respuestas en las tres; lo unico que cambia es el relleno:

  CABE     --celda cabe     relleno 0: el corpus entra ENTERO en la ventana.
                            Aca el brazo tonto NO esta mutilado (su techo es
                            90/90): si empata, el RLM no aporta y hay que
                            decirlo. Es tambien el techo del MODELO.
  APENAS   --celda apenas   relleno autocalibrado para que el tonto vea ~90%.
                            La UNICA zona intermedia donde sigue siendo rival:
                            medido, por debajo del ~60% de visibilidad su
                            techo cae al nivel del azar.
  NO_CABE  --celda no_cabe  relleno 2 M: el corpus es decenas de veces la
                            ventana. Aca el techo del tonto es 0/90, asi que
                            ganarle NO prueba nada; el rival es el AZAR.

LA TRAMPA DEL GREP, DECLARADA. ctx_grep imprime "N de TOTAL matches", asi que
un conteo de una sola linea lo resuelve la HERRAMIENTA, no el modelo. Por eso
los tipos estan partidos: 'contar_simple' es grepeable de un patron y sirve de
diagnostico; 'contar_conjuncion' y 'cruzar_contar' exigen asociar dos lineas
DENTRO del mismo documento y ningun regex de una linea los resuelve.

Uso:
  PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\banco_rlm_sintesis.py --brazos gratis
  PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\banco_rlm_sintesis.py --celda cabe --brazos todos
Exit: 0 si corrio, 1 si el oraculo no da 100% (banco invalido), 3 sin backend.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import sys
import time
import unicodedata
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

os.environ.setdefault("PYTHONUTF8", "1")
try:
    # line_buffering: sin esto, redirigido a un fichero el banco no escribe
    # NADA hasta terminar y una corrida de horas no se puede vigilar.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace",
                           line_buffering=True)
except Exception:
    pass

SEED = 20260818
# Version del CORPUS. Se sube cada vez que cambia lo que el modelo lee, para
# que dos corridas no se comparen creyendo que vieron el mismo texto.
#   v1 (2026-08-18) primera version; el clon tenia lote propio.
#   v2 (2026-08-18) el clon COMPARTE el lote de su fuente: el par de COMPARAR
#      difiere solo en los campos declarados (ver PREREG, enmiendas).
VERSION_CORPUS = 2
HEALTH_TIMEOUT = 8
# Chars por token de ESTE corpus: 2,78 medido con /tokenize de :8080 el
# 2026-08-18 (31.988 chars = 11.503 tokens). Es solo la estimacion inicial;
# si /tokenize responde, manda el conteo real.
CHARS_POR_TOKEN = 2.78

# Los 7 campos comparables. La pregunta de comparacion los NOMBRA para que el
# espacio de respuestas sea cerrado y el azar tenga una tasa calculable.
CAMPOS = ["Planta", "Turno", "Operador", "Estado", "Temperatura",
          "Incidencias", "Firma"]

PLANTAS = ["NORTE", "SUR", "ESTE", "OESTE", "CENTRO"]
TURNOS = ["manana", "tarde", "noche"]
ESTADOS = ["OK", "ALERTA", "FALLA", "MANTENIMIENTO"]
OPERADORES = ["Amaranta", "Baltasar", "Casilda", "Demetrio",
              "Eulalia", "Fructuoso", "Genoveva", "Higinio"]
AUDITORES = ["Ildefonsa", "Jacinto", "Ludovica", "Melquiades",
             "Nicanora", "Onesimo", "Perpetua", "Quintiliano"]

# Pesos DESIGUALES a proposito: con reparto uniforme todos los conteos caen
# en el mismo numero y (a) no hay preguntas con conteo chico y verificable,
# (b) el brazo marginal se vuelve degenerado. La desigualdad da un abanico de
# conteos de 2 a 12, que es el rango donde un fallo significa "no sabe
# agregar" y no "no sabe contar hasta 40".
_PESOS_PLANTA = [5, 4, 3, 2, 1]
_PESOS_TURNO = [4, 3, 2]
_PESOS_ESTADO = [6, 3, 2, 1]
_PESOS_OPERADOR = [5, 4, 4, 3, 3, 2, 1, 1]

# Vocabulario del relleno: DISJUNTO de todo valor de campo y SIN digitos, y
# se verifica con assert al generar. Un relleno que dijera "FALLA" o "NORTE"
# cambiaria en silencio la verdad de los conteos — el modo de fallo clasico
# del banco que se mide a si mismo.
_VOCAB_RELLENO = (
    "bitacora comision expediente tramite ventanilla archivo carpeta legajo "
    "circular resolucion memorando ordenanza reglamento apartado clausula "
    "anexo protocolo procedimiento revision cotejo constancia acta minuta "
    "gestion tramo pendiente vigente conforme adjunto remitido despachado "
    "sellado foliado rubricado cotejado tramitado archivado devuelto "
    "corriente ordinario habitual rutinario preliminar posterior previo"
).split()


def _norm(s) -> str:
    """Normaliza una respuesta para comparar: minusculas, sin tildes, sin
    puntuacion de borde. Comparar 'Manana' con 'mañana' como distintos seria
    contar como fallo del modelo una diferencia de teclado."""
    t = unicodedata.normalize("NFKD", str(s))
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.lower().strip()
    return t.strip(" .,:;!?*_`\"'()[]-")


# ── 1. Corpus ──────────────────────────────────────────────────────────


def _elegir(rnd, opciones, pesos):
    return rnd.choices(opciones, weights=pesos, k=1)[0]


def _observacion(rnd) -> str:
    n = rnd.randint(9, 16)
    return " ".join(rnd.choice(_VOCAB_RELLENO) for _ in range(n))


def generar_datos(n_docs: int = 90, n_clones: int = 30, seed: int = SEED):
    """Los DATOS del banco (documentos y auditorias), sin texto todavia.

    La verdad de todas las preguntas se calcula de aqui, nunca del texto: si
    la verdad se leyera del corpus renderizado, un bug del renderizador se
    convertiria en verdad y el banco aprobaria al instrumento roto.

    Los ultimos ``n_clones`` documentos son CLONES de otros: copian todos los
    campos y hasta la observacion, y se les mutan entre 1 y 4 campos. Son los
    pares de la familia COMPARAR. Los documentos base (los primeros
    n_docs - n_clones) son los unicos que usan las familias CONTAR y CRUZAR.
    """
    rnd = random.Random(seed)
    n_base = n_docs - n_clones
    docs = []
    for i in range(n_base):
        docs.append({
            "id": i + 1,
            "Planta": _elegir(rnd, PLANTAS, _PESOS_PLANTA),
            "Turno": _elegir(rnd, TURNOS, _PESOS_TURNO),
            "Operador": _elegir(rnd, OPERADORES, _PESOS_OPERADOR),
            "Estado": _elegir(rnd, ESTADOS, _PESOS_ESTADO),
            "Temperatura": rnd.randint(18, 42),
            "Incidencias": rnd.randint(0, 5),
            "Firma": rnd.choice(OPERADORES),
            "obs": _observacion(rnd),
            "clon_de": 0,
            "difieren": 0,
        })
    # Clones: el par de COMPARAR. k=1 para los 10 primeros (familia
    # comparar_campo, respuesta = el nombre del campo) y k en 1..4 para los
    # 10 siguientes (familia comparar_ndif, respuesta = cuantos campos).
    fuentes = rnd.sample(range(n_base), n_clones)
    for j, idx in enumerate(fuentes):
        base = docs[idx]
        k = 1 if j < (n_clones // 2) else rnd.randint(1, 4)
        campos_mut = rnd.sample(CAMPOS, k)
        clon = dict(base)
        clon["id"] = n_base + j + 1
        clon["clon_de"] = base["id"]
        clon["difieren"] = k
        clon["campos_mut"] = list(campos_mut)
        for campo in campos_mut:
            actual = base[campo]
            if campo == "Planta":
                nuevo = rnd.choice([v for v in PLANTAS if v != actual])
            elif campo == "Turno":
                nuevo = rnd.choice([v for v in TURNOS if v != actual])
            elif campo == "Estado":
                nuevo = rnd.choice([v for v in ESTADOS if v != actual])
            elif campo in ("Operador", "Firma"):
                nuevo = rnd.choice([v for v in OPERADORES if v != actual])
            elif campo == "Temperatura":
                nuevo = rnd.choice([v for v in range(18, 43) if v != actual])
            else:
                nuevo = rnd.choice([v for v in range(0, 6) if v != actual])
            clon[campo] = nuevo
        docs.append(clon)
    # EL CLON COMPARTE EL LOTE DE SU FUENTE (fix 2026-08-18). Con lote unico
    # por documento, el par de COMPARAR diferia en un OCTAVO campo ('Lote
    # auditado') que la pregunta no lista, y en el piloto el modelo contesto
    # "lote auditado" 5 de 5 veces: tenia razon y el banco lo puntuaba mal.
    # Compartiendo el lote, la unica diferencia entre el par son los k campos
    # mutados y la pregunta deja de tener dos respuestas correctas.
    por_base = {}
    lotes = rnd.sample(range(1000, 9999), n_base)
    for doc, lote in zip(docs[:n_base], lotes):
        doc["Lote"] = "L-%04d" % lote
        por_base[doc["id"]] = doc["Lote"]
    for doc in docs[n_base:]:
        doc["Lote"] = por_base[doc["clon_de"]]
    auditorias = []
    for doc in docs[:n_base]:
        auditorias.append({
            "lote": doc["Lote"],
            "auditor": rnd.choice(AUDITORES),
            "sede": _elegir(rnd, PLANTAS, _PESOS_PLANTA),
        })
    rnd.shuffle(auditorias)      # las auditorias NO van en el orden de los
    # informes: si fueran paralelas, el "cruce" se resolveria por posicion.
    return {"docs": docs, "auditorias": auditorias, "n_base": n_base,
            "n_docs": len(docs)}


def _bloque_doc(d: dict) -> str:
    return ("=== INFORME %03d ===\n"
            "Planta: %s\nTurno: %s\nOperador: %s\nEstado: %s\n"
            "Temperatura: %s\nIncidencias: %s\nFirma: %s\n"
            "Lote auditado: %s\nObservacion: %s\n"
            % (d["id"], d["Planta"], d["Turno"], d["Operador"], d["Estado"],
               d["Temperatura"], d["Incidencias"], d["Firma"], d["Lote"],
               d["obs"]))


def _bloque_auditoria(a: dict) -> str:
    return ("--- AUDITORIA ---\n"
            "Lote revisado: %s\nAuditor responsable: %s\nSede: %s\n"
            % (a["lote"], a["auditor"], a["sede"]))


def _relleno(rnd, objetivo_chars: int) -> list:
    lineas, acum = [], 0
    while acum < objetivo_chars:
        n = rnd.randint(10, 18)
        linea = " ".join(rnd.choice(_VOCAB_RELLENO) for _ in range(n)) + "."
        lineas.append(linea.capitalize())
        acum += len(linea) + 1
    return lineas


def renderizar(datos: dict, filler_chars: int = 0, seed: int = SEED) -> str:
    """Texto del corpus. Los bloques van INTERCALADOS con relleno y en un
    orden barajado (semilla fija): informes y auditorias mezclados, para que
    ni la recencia ni la primacia regalen una familia entera."""
    rnd = random.Random(seed + 7)
    bloques = [_bloque_doc(d) for d in datos["docs"]]
    bloques += [_bloque_auditoria(a) for a in datos["auditorias"]]
    rnd.shuffle(bloques)
    if filler_chars <= 0:
        texto = "\n".join(bloques)
    else:
        # El relleno se genera de una y se REPARTE al azar entre los huecos,
        # no "una tanda por hueco": con 181 bloques, una tanda por hueco
        # imponia un piso de ~22.000 chars y hacia inalcanzable cualquier
        # corpus chico (la celda APENAS pedia 43.812 y salian 55.842).
        lineas = _relleno(rnd, filler_chars)
        huecos = [[] for _ in range(len(bloques) + 1)]
        for ln in lineas:
            huecos[rnd.randrange(len(huecos))].append(ln)
        partes = []
        for i, b in enumerate(bloques):
            partes.extend(huecos[i])
            partes.append("")
            partes.append(b)
        partes.extend(huecos[-1])
        texto = "\n".join(partes)
    _verificar_relleno(texto, datos)
    return texto


def _verificar_relleno(texto: str, datos: dict) -> None:
    """El relleno NO puede contener ningun valor de campo ni digitos: si los
    tuviera, cambiaria conteos en silencio. Se verifica sobre el corpus
    entero contando ocurrencias esperadas."""
    for palabra in _VOCAB_RELLENO:
        assert not any(ch.isdigit() for ch in palabra), palabra
    reservadas = set(PLANTAS) | set(TURNOS) | set(ESTADOS)
    reservadas |= set(OPERADORES) | set(AUDITORES)
    reservadas |= {"INFORME", "AUDITORIA", "Lote", "Planta", "Turno",
                   "Operador", "Estado", "Temperatura", "Incidencias",
                   "Firma", "Auditor", "Sede"}
    bajas = {r.lower() for r in reservadas}
    for palabra in _VOCAB_RELLENO:
        assert palabra.lower() not in bajas, "relleno colisiona: " + palabra
    # Invariante duro y barato: 'Estado: FALLA' aparece exactamente tantas
    # veces como documentos con ese estado.
    n = sum(1 for d in datos["docs"] if d["Estado"] == "FALLA")
    assert texto.count("Estado: FALLA") == n, "el corpus no cuadra con datos"


# ── 2. Preguntas ───────────────────────────────────────────────────────

_INSTRUCCION = ("Responde en una sola linea final con el formato exacto "
                "RESPUESTA: <valor>")


def _espacio_conteo(n_docs: int):
    return list(range(0, n_docs + 1))


def construir_preguntas(datos: dict, por_tipo: int = 15, seed: int = SEED):
    """Las 6 familias, ``por_tipo`` preguntas cada una. Determinista.

    Cada item lleva ``espacio``: el conjunto de respuestas que la pregunta
    declara posibles. Sin eso el brazo AZAR no seria calculable, y sin azar
    calculable el numero absoluto no significa nada.
    """
    rnd = random.Random(seed + 31)
    base = [d for d in datos["docs"] if not d["clon_de"]]
    clones = [d for d in datos["docs"] if d["clon_de"]]
    por_id = {d["id"]: d for d in datos["docs"]}
    aud_por_lote = {a["lote"]: a for a in datos["auditorias"]}
    n_docs = datos["n_docs"]
    esp_conteo = _espacio_conteo(n_docs)
    items = []

    def add(tipo, pregunta, respuesta, espacio, meta=None):
        items.append({"id": "%s_%02d" % (tipo, sum(
            1 for it in items if it["tipo"] == tipo) + 1),
            "tipo": tipo, "familia": tipo.split("_")[0],
            "pregunta": pregunta + "\n" + _INSTRUCCION,
            "respuesta": respuesta, "espacio": espacio,
            "meta": meta or {}})

    # --- CONTAR simple: un solo campo, GREPEABLE de un patron. Es el
    #     diagnostico de si el que cuenta es ctx_grep y no el modelo.
    cands = []
    # Se incluyen Temperatura e Incidencias (valores numericos exactos)
    # ademas de los categoricos: son los que dan conteos CHICOS (2-12), que
    # es el rango donde fallar significa "no sabe agregar" y no "no sabe
    # contar hasta 40". Sin ellos el banco se queda sin candidatos al crecer
    # el numero de documentos.
    for campo, valores in (("Planta", PLANTAS), ("Turno", TURNOS),
                           ("Estado", ESTADOS), ("Operador", OPERADORES),
                           ("Firma", OPERADORES),
                           ("Incidencias", list(range(0, 6))),
                           ("Temperatura", list(range(18, 43)))):
        for v in valores:
            c = sum(1 for d in datos["docs"] if str(d[campo]) == str(v))
            if 2 <= c <= 12:
                cands.append((campo, v, c))
    rnd.shuffle(cands)
    for campo, valor, c in cands[:por_tipo]:
        add("contar_simple",
            "En el corpus hay informes con el encabezado '=== INFORME nnn ==='. "
            "Cuenta EXACTAMENTE cuantos informes tienen el campo %s con el "
            "valor %s. Responde con un entero entre 0 y %d."
            % (campo, valor, n_docs),
            c, esp_conteo, {"campo": campo, "valor": valor})

    # --- CONTAR conjuncion: dos campos del MISMO informe. Ningun regex de
    #     una linea lo resuelve: hay que asociar lineas dentro del bloque.
    cands = []
    pares = [("Planta", PLANTAS, "Estado", ESTADOS),
             ("Turno", TURNOS, "Estado", ESTADOS),
             ("Planta", PLANTAS, "Turno", TURNOS),
             ("Operador", OPERADORES, "Estado", ESTADOS)]
    for ca, va, cb, vb in pares:
        for x in va:
            for y in vb:
                c = sum(1 for d in datos["docs"]
                        if str(d[ca]) == x and str(d[cb]) == y)
                if 2 <= c <= 10:
                    cands.append((ca, x, cb, y, c))
    rnd.shuffle(cands)
    for ca, x, cb, y, c in cands[:por_tipo]:
        add("contar_conjuncion",
            "Cuenta EXACTAMENTE cuantos informes cumplen LAS DOS condiciones "
            "a la vez EN EL MISMO informe: %s es %s y ademas %s es %s. "
            "Responde con un entero entre 0 y %d." % (ca, x, cb, y, n_docs),
            c, esp_conteo, {"a": (ca, x), "b": (cb, y)})

    # --- COMPARAR campo: el par difiere en UN solo campo.
    uno = [c for c in clones if c["difieren"] == 1]
    rnd.shuffle(uno)
    for c in uno[:por_tipo]:
        add("comparar_campo",
            "Los informes %03d y %03d tienen el mismo lote y la misma "
            "observacion. Considerando estos campos: %s, di cual es el UNICO "
            "campo en el que difieren. Responde con el nombre del campo."
            % (c["clon_de"], c["id"], ", ".join(CAMPOS)),
            c["campos_mut"][0], list(CAMPOS),
            {"par": (c["clon_de"], c["id"])})

    # --- COMPARAR cuantos: el par difiere en k campos (1..4).
    varios = [c for c in clones if c["difieren"] >= 1
              and c not in uno[:por_tipo]]
    rnd.shuffle(varios)
    for c in varios[:por_tipo]:
        add("comparar_ndif",
            "Los informes %03d y %03d tienen el mismo lote y la misma "
            "observacion. Considerando estos campos: %s, di en CUANTOS de "
            "ellos difieren. Responde con un entero entre 1 y %d."
            % (c["clon_de"], c["id"], ", ".join(CAMPOS), len(CAMPOS)),
            c["difieren"], list(range(1, len(CAMPOS) + 1)),
            {"par": (c["clon_de"], c["id"])})

    # --- CRUZAR auditor: dos saltos. informe -> lote -> bloque AUDITORIA.
    elegidos = rnd.sample(base, min(por_tipo, len(base)))
    for d in elegidos:
        aud = aud_por_lote[d["Lote"]]
        add("cruzar_auditor",
            "El informe %03d menciona un lote auditado. Busca el bloque "
            "'--- AUDITORIA ---' de ESE mismo lote y di el nombre del auditor "
            "responsable que figura ahi. Responde con el nombre." % d["id"],
            aud["auditor"], list(AUDITORES),
            {"doc": d["id"], "lote": d["Lote"]})

    # --- CRUZAR contar: join + agregacion. El caso mas duro del banco.
    cands = []
    for planta in PLANTAS:
        for auditor in AUDITORES:
            c = sum(1 for d in datos["docs"]
                    if d["Planta"] == planta
                    and aud_por_lote[d["Lote"]]["auditor"] == auditor)
            if 1 <= c <= 6:
                cands.append((planta, auditor, c))
    rnd.shuffle(cands)
    for planta, auditor, c in cands[:por_tipo]:
        add("cruzar_contar",
            "Cuenta cuantos informes de la Planta %s tienen su lote auditado "
            "por %s. Para cada informe de esa planta hay que mirar su lote y "
            "buscar el bloque de AUDITORIA de ese lote. Responde con un "
            "entero entre 0 y %d." % (planta, auditor, n_docs),
            c, esp_conteo, {"planta": planta, "auditor": auditor})

    for it in items:
        it["tipo_respuesta"] = "int" if isinstance(it["respuesta"], int) \
            else "str"
    return items


# ── 3. Calificador ─────────────────────────────────────────────────────

_RX_RESP = re.compile(r"respuesta\s*[:=]\s*(.+)", re.I)


def extraer(texto: str, tipo_respuesta: str):
    """(valor, formato_ok). formato_ok=False significa 'no dijo RESPUESTA:'
    y se CUENTA APARTE: un fallo de formato es del instrumento hasta que se
    demuestre lo contrario, no del modelo."""
    t = str(texto or "")
    ms = _RX_RESP.findall(t)
    formato_ok = bool(ms)
    if ms:
        bruto = ms[-1]
    else:
        # Respaldo declarado: la ultima linea no vacia.
        lineas = [l for l in t.strip().splitlines() if l.strip()]
        bruto = lineas[-1] if lineas else ""
    if tipo_respuesta == "int":
        nums = re.findall(r"-?\d+", bruto)
        return (int(nums[0]) if nums else None), formato_ok
    return _norm(bruto), formato_ok


def calificar(item: dict, texto: str):
    val, formato_ok = extraer(texto, item["tipo_respuesta"])
    if item["tipo_respuesta"] == "int":
        ok = (val is not None and int(val) == int(item["respuesta"]))
        cerca = (val is not None
                 and abs(int(val) - int(item["respuesta"])) <= 1)
    else:
        ok = (val == _norm(item["respuesta"]))
        cerca = ok
    return {"ok": bool(ok), "cerca": bool(cerca), "formato_ok": formato_ok,
            "extraido": val}


# ── 4. Brazos GRATIS (sin GPU) ─────────────────────────────────────────


def brazo_oraculo(items: list) -> dict:
    """El calificador sobre la verdad. DEBE dar 100%: un banco que ni con la
    respuesta correcta escrita saca 100% no mide nada."""
    res = [calificar(it, "RESPUESTA: %s" % it["respuesta"]) for it in items]
    return _resumen("oraculo", items, res)


def _prob_marginal(items: list) -> list:
    """P(acertar) del adivinador MARGINAL, item por item, leave-one-out:
    conoce la distribucion de respuestas de su tipo en el banco pero no ha
    leido el corpus. Es la referencia dificil."""
    probs = []
    for i, it in enumerate(items):
        otros = [str(o["respuesta"]) for j, o in enumerate(items)
                 if j != i and o["tipo"] == it["tipo"]]
        if not otros:
            probs.append(0.0)
            continue
        probs.append(otros.count(str(it["respuesta"])) / len(otros))
    return probs


def _prob_uniforme(items: list) -> list:
    return [1.0 / len(it["espacio"]) for it in items]


def simular_azar(items: list, probs: list, B: int = 200000, seed: int = SEED):
    """Distribucion exacta (por simulacion) del numero de aciertos del azar.

    Se simula en vez de usar una binomial porque cada item tiene su propia
    probabilidad: la suma es una Poisson-binomial, no una binomial.
    """
    rnd = random.Random(seed + 101)
    conteos = []
    for _ in range(B):
        conteos.append(sum(1 for p in probs if rnd.random() < p))
    conteos.sort()
    n = len(items)
    media = sum(conteos) / B
    return {"n": n, "B": B, "media": media, "media_frac": media / n,
            "p_media": sum(probs) / n, "dist": conteos}


def p_valor_superior(dist: list, observado: int) -> float:
    """P(azar >= observado), una cola. Con la distribucion ya ordenada."""
    import bisect as _b
    B = len(dist)
    return (B - _b.bisect_left(dist, observado)) / B


def cuantil(dist: list, q: float) -> int:
    import bisect as _b
    idx = min(len(dist) - 1, max(0, int(round(q * (len(dist) - 1)))))
    return dist[idx]


def mde(probs: list, dist: list, alpha: float = 0.05, poder: float = 0.80,
        B: int = 20000, seed: int = SEED) -> float:
    """Minimo efecto detectable: la exactitud VERDADERA mas baja que, con
    este N, se rechaza contra el azar el 80% de las veces.

    Se calcula ANTES de correr porque el repo tiene cicatrices de matar vias
    con disenos que no distinguian 'no hay efecto' de 'no lo pude ver'.
    """
    n = len(probs)
    # Umbral critico: el menor k con P(azar >= k) <= alpha.
    k_crit = None
    for k in range(0, n + 1):
        if p_valor_superior(dist, k) <= alpha:
            k_crit = k
            break
    if k_crit is None:
        return 1.0
    rnd = random.Random(seed + 202)
    for paso in range(0, n + 1):
        p1 = paso / n
        exitos = 0
        for _ in range(B):
            k = sum(1 for _ in range(n) if rnd.random() < p1)
            if k >= k_crit:
                exitos += 1
        if exitos / B >= poder:
            return p1
    return 1.0


def mcnemar_exacto(a_ok: list, b_ok: list) -> dict:
    """McNemar exacto (binomial sobre los discordantes), dos colas. Pareado
    porque los dos brazos contestan LAS MISMAS preguntas: comparar dos
    proporciones sueltas tiraria a la basura el apareamiento."""
    b = sum(1 for x, y in zip(a_ok, b_ok) if x and not y)
    c = sum(1 for x, y in zip(a_ok, b_ok) if y and not x)
    m = b + c
    if m == 0:
        return {"b": 0, "c": 0, "p": 1.0}
    k = min(b, c)
    acum = sum(math.comb(m, i) for i in range(0, k + 1)) / (2.0 ** m)
    return {"b": b, "c": c, "p": min(1.0, 2 * acum)}


def techo_tonto(items: list, datos: dict, texto: str, corte: int) -> dict:
    """El ORACULO sobre lo que el brazo tonto alcanzo a VER.

    Recalcula la verdad usando SOLO los bloques COMPLETOS que caben en los
    primeros ``corte`` chars. Separa 'el tonto fallo porque el modelo no
    pudo' de 'fallo porque la informacion no estaba en su ventana' — sin eso
    el brazo tonto seria un espantapajaros y su derrota no probaria nada.
    """
    visible = texto[:corte]
    ids_vistos = set()
    for d in datos["docs"]:
        if _bloque_doc(d) in visible:
            ids_vistos.add(d["id"])
    lotes_vistos = {}
    for a in datos["auditorias"]:
        if _bloque_auditoria(a) in visible:
            lotes_vistos[a["lote"]] = a
    docs_v = [d for d in datos["docs"] if d["id"] in ids_vistos]
    por_id = {d["id"]: d for d in datos["docs"]}
    aud_todas = {a["lote"]: a for a in datos["auditorias"]}
    res = []
    for it in items:
        t, m = it["tipo"], it["meta"]
        if t == "contar_simple":
            v = sum(1 for d in docs_v if str(d[m["campo"]]) == str(m["valor"]))
        elif t == "contar_conjuncion":
            (ca, x), (cb, y) = m["a"], m["b"]
            v = sum(1 for d in docs_v
                    if str(d[ca]) == x and str(d[cb]) == y)
        elif t in ("comparar_campo", "comparar_ndif"):
            i1, i2 = m["par"]
            if i1 in ids_vistos and i2 in ids_vistos:
                d1, d2 = por_id[i1], por_id[i2]
                dif = [c for c in CAMPOS if d1[c] != d2[c]]
                v = dif[0] if t == "comparar_campo" else len(dif)
            else:
                v = None
        elif t == "cruzar_auditor":
            lote = m["lote"]
            v = (lotes_vistos[lote]["auditor"]
                 if (m["doc"] in ids_vistos and lote in lotes_vistos)
                 else None)
        else:
            v = sum(1 for d in docs_v
                    if d["Planta"] == m["planta"]
                    and aud_todas[d["Lote"]]["lote"] in lotes_vistos
                    and lotes_vistos[d["Lote"]]["auditor"] == m["auditor"])
        res.append(calificar(it, "RESPUESTA: %s" % ("" if v is None else v)))
    return _resumen("techo_tonto", items, res)


# ── 5. Brazos con GPU ──────────────────────────────────────────────────

_SYS_TONTO = ("Sos un analista. Te dan un corpus de informes y una pregunta "
              "sobre el conjunto. Responde con precision y termina SIEMPRE "
              "con una linea 'RESPUESTA: <valor>'.")


def _tokenizar(url: str, texto: str):
    try:
        req = urllib.request.Request(
            url.rstrip("/") + "/tokenize",
            data=json.dumps({"content": texto}).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            return len(json.load(r).get("tokens") or [])
    except Exception:
        return None


def corte_para_ventana(url: str, texto: str, n_ctx: int, reserva: int = 2200):
    """Cuantos chars del corpus caben en la ventana dejando ``reserva``
    tokens para el system, la pregunta y la respuesta. Se MIDE con /tokenize
    cuando el server lo ofrece; la estimacion por chars/token es respaldo."""
    presupuesto = max(512, n_ctx - reserva)
    corte = min(len(texto), int(presupuesto * CHARS_POR_TOKEN))
    for _ in range(8):
        tk = _tokenizar(url, texto[:corte])
        if tk is None:
            return corte, None      # sin /tokenize: queda la estimacion
        if tk <= presupuesto:
            return corte, tk
        corte = int(corte * presupuesto / tk * 0.97)
    return corte, None


def brazo_tonto(items, texto, url, n_ctx, print_fn=print):
    """'Meter todo lo que quepa en la ventana': UNA llamada por pregunta con
    el prefijo del corpus truncado por la cabeza y la pregunta AL FINAL.

    La pregunta va al final a proposito: asi el prefijo es identico entre
    preguntas y el cache de prompt de llama-server lo reusa — sin eso el
    brazo costaria N prefills gigantes y seria incorrible.
    Temperatura 0: al brazo tonto se le da su mejor tiro.
    """
    from cognia.agent.chat_client import completar
    corte, tk = corte_para_ventana(url, texto, n_ctx)
    print_fn("   tonto: ve %d de %d chars (%.1f%%)%s"
             % (corte, len(texto), 100.0 * corte / max(1, len(texto)),
                "" if tk is None else " = %d tokens medidos" % tk))
    prefijo = texto[:corte]
    res, filas = [], []
    for it in items:
        t0 = time.time()
        r = completar([{"role": "system", "content": _SYS_TONTO},
                       {"role": "user",
                        "content": "CORPUS:\n" + prefijo + "\n\nPREGUNTA: "
                                   + it["pregunta"]}],
                      url=url, temperature=0.0, top_p=1.0, max_tokens=400,
                      razonador=False)
        salida = (r.texto or "") if r.ok else ""
        c = calificar(it, salida)
        c["seg"] = time.time() - t0
        c["error"] = "" if r.ok else str(r.error)[:120]
        res.append(c)
        filas.append({"id": it["id"], "ok": c["ok"], "resp": salida[-160:]})
        print_fn("   [%s] %s -> %s (esperado %s) %.0fs"
                 % ("OK " if c["ok"] else "..", it["id"], c["extraido"],
                    it["respuesta"], c["seg"]))
    return _resumen("tonto", items, res, {"corte_chars": corte,
                                          "frac_visto": corte / len(texto)})


def brazo_rlm(items, ruta, url, print_fn=print):
    """El brazo RLM. UNA corrida por pregunta sobre el corpus entero.

    UN RECHAZO NO ES UN CERO. Si correr_rlm devuelve ok=False con 0 pasos
    (backend sin tool-calling, ruta ilegible, corpus vacio) el item se marca
    INVALIDO y no cuenta como fallo del modelo: puntuarlo 0 convertiria una
    averia del instrumento en la conclusion "el RLM no sintetiza", que es
    justo el falso negativo que este banco existe para evitar.
    """
    from cognia.agent.rlm import correr_rlm
    res = []
    for it in items:
        t0 = time.time()
        invalido, motivo = False, ""
        try:
            r = correr_rlm(it["pregunta"], str(ruta), url=url)
            salida = str(r.get("texto") or "")
            med = r.get("medidor") or {}
            if not r.get("ok") and not r.get("pasos"):
                invalido = True
                motivo = salida.splitlines()[0][:140] if salida else "sin texto"
        except Exception as exc:
            salida, med = "", {}
            invalido, motivo = True, "EXCEPCION " + str(exc)[:120]
        if invalido:
            print_fn("   [XX] %s INVALIDO: %s" % (it["id"], motivo))
            if not res:
                raise RuntimeError(
                    "el brazo RLM no arranca: " + motivo +
                    " — se aborta en vez de anotar ceros")
            res.append({"ok": False, "cerca": False, "formato_ok": True,
                        "extraido": None, "invalido": True,
                        "seg": time.time() - t0, "tokens": 0,
                        "cobertura": 0.0})
            continue
        c = calificar(it, salida)
        c["seg"] = time.time() - t0
        c["tokens"] = (med.get("tokens_in_raiz", 0)
                       + med.get("tokens_out_raiz", 0)
                       + med.get("tokens_in_hijos", 0)
                       + med.get("tokens_out_hijos", 0))
        c["cobertura"] = med.get("cobertura_union", 0.0)
        res.append(c)
        print_fn("   [%s] %s -> %s (esperado %s) %.0fs %d tok cob %.2f%%"
                 % ("OK " if c["ok"] else "..", it["id"], c["extraido"],
                    it["respuesta"], c["seg"], c["tokens"],
                    100 * c["cobertura"]))
    return _resumen("rlm", items, res)


# ── 6. Resumen y estadistica ───────────────────────────────────────────


def _resumen(nombre, items, res, extra=None):
    n = len(items)
    ok = [bool(r["ok"]) for r in res]
    por_tipo = {}
    for it, r in zip(items, res):
        d = por_tipo.setdefault(it["tipo"], [0, 0])
        d[1] += 1
        d[0] += 1 if r["ok"] else 0
    invalidos = sum(1 for r in res if r.get("invalido"))
    validos = n - invalidos
    out = {"brazo": nombre, "n": n, "aciertos": sum(ok),
           "invalidos": invalidos,
           # La exactitud se calcula sobre los VALIDOS: un item que el
           # instrumento no pudo correr no es una respuesta equivocada.
           "exactitud": sum(ok) / validos if validos else 0.0,
           "cerca": sum(1 for r in res if r.get("cerca")),
           "sin_formato": sum(1 for r in res if not r.get("formato_ok", True)),
           "ok": ok, "por_tipo": por_tipo,
           "seg": sum(r.get("seg", 0.0) for r in res)}
    if extra:
        out.update(extra)
    return out


def ic_wilson(k, n, z=1.96):
    if not n:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    r = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - r) / d, (c + r) / d)


def _tabla(res_por_brazo, items):
    tipos = []
    for it in items:
        if it["tipo"] not in tipos:
            tipos.append(it["tipo"])
    filas = ["", "%-14s %6s %8s %18s  %s"
             % ("brazo", "acier", "exact", "IC95", "  ".join(
                 "%-17s" % t for t in tipos))]
    for r in res_por_brazo:
        lo, hi = ic_wilson(r["aciertos"], r["n"])
        marca = "" if not r.get("invalidos") else " !%d inval" % r["invalidos"]
        celdas = []
        for t in tipos:
            a, b = r["por_tipo"].get(t, (0, 0))
            # Los brazos de azar traen esperanzas (float), no conteos: se
            # imprimen con decimal para no redondear 0,5 aciertos a 0.
            fmt = "%.1f/%d" if isinstance(a, float) else "%d/%d"
            celdas.append("%-17s" % (fmt % (a, b)))
        filas.append("%-14s %6s %7.1f%% [%5.1f%%,%5.1f%%]  %s%s"
                     % (r["brazo"], "%d/%d" % (r["aciertos"], r["n"]),
                        100 * r["exactitud"], 100 * lo, 100 * hi,
                        "  ".join(celdas), marca))
    return "\n".join(filas)


def _salud(url: str) -> bool:
    try:
        with urllib.request.urlopen(url + "/health", timeout=HEALTH_TIMEOUT) as r:
            return r.status == 200
    except Exception:
        return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--celda", choices=["cabe", "apenas", "no_cabe"],
                    default="cabe")
    ap.add_argument("--filler", type=int, default=-1,
                    help="chars de relleno; -1 = el default de la celda")
    ap.add_argument("--docs", type=int, default=90)
    ap.add_argument("--clones", type=int, default=30)
    ap.add_argument("--por-tipo", type=int, default=15)
    ap.add_argument("--brazos", default="gratis",
                    choices=["gratis", "tonto", "rlm", "todos"])
    ap.add_argument("--ventana", type=int, default=0,
                    help="n_ctx a suponer para el techo del brazo tonto sin "
                         "backend (permite calcular el techo GRATIS)")
    ap.add_argument("--limite", type=int, default=0,
                    help="corre solo las primeras N preguntas (humo)")
    ap.add_argument("--muestra", type=int, default=0,
                    help="PILOTO: k preguntas POR TIPO, estratificado. Un "
                         "piloto con --limite tomaria 12 preguntas del mismo "
                         "tipo y no diria nada de las otras cinco familias")
    ap.add_argument("--salida", default="")
    ap.add_argument("--seed", type=int, default=SEED)
    a = ap.parse_args(argv)

    datos = generar_datos(a.docs, a.clones, a.seed)
    if a.filler >= 0:
        filler = a.filler
    elif a.celda == "cabe":
        filler = 0
    elif a.celda == "no_cabe":
        filler = 2_000_000
    else:
        # Celda APENAS: el corpus se pasa de la ventana lo justo para que el
        # brazo tonto vea ~90%. Es la UNICA zona donde el camino tonto sigue
        # siendo un rival: por debajo del 60% de visibilidad su techo de
        # informacion cae al nivel del azar (medido, ver el prereg) y ganarle
        # deja de probar nada.
        if not a.ventana:
            print("La celda APENAS necesita --ventana (o un backend vivo).")
            return 1
        visibles = int(max(512, a.ventana - 2200) * CHARS_POR_TOKEN)
        objetivo = int(visibles / 0.90)
        # Se AJUSTA por iteracion en vez de restar: _relleno sobrepasa el
        # pedido (genera lineas enteras hasta cubrirlo), asi que un filler
        # calculado de una resta daba 75% de visibilidad, no 90%.
        filler = max(0, objetivo - len(renderizar(datos, 0, a.seed)))
        for _ in range(12):
            real = len(renderizar(datos, filler, a.seed))
            if abs(real - objetivo) <= objetivo // 50 or filler <= 0:
                break
            filler = max(0, int(filler * objetivo / real))
    texto = renderizar(datos, filler, a.seed)
    items = construir_preguntas(datos, a.por_tipo, a.seed)
    if a.muestra:
        vistos, muestra = {}, []
        for it in items:
            n = vistos.get(it["tipo"], 0)
            if n < a.muestra:
                muestra.append(it)
                vistos[it["tipo"]] = n + 1
        items = muestra
    if a.limite:
        items = items[:a.limite]

    print("BANCO RLM SINTESIS — celda %s — corpus v%d"
          % (a.celda.upper(), VERSION_CORPUS))
    print("corpus: %d chars | %d informes | %d auditorias | relleno %d"
          % (len(texto), datos["n_docs"], len(datos["auditorias"]), filler))
    print("preguntas: %d (%d por tipo, 6 tipos)\n" % (len(items), a.por_tipo))

    resultados = []

    # -- oraculo: la compuerta del instrumento.
    orc = brazo_oraculo(items)
    resultados.append(orc)
    if orc["aciertos"] != orc["n"]:
        print("BANCO INVALIDO: el oraculo saca %d/%d. El calificador o las "
              "verdades estan mal; no se mide nada mas."
              % (orc["aciertos"], orc["n"]))
        return 1

    # -- azar (los dos) por simulacion.
    p_uni = _prob_uniforme(items)
    p_mar = _prob_marginal(items)
    sim_uni = simular_azar(items, p_uni, seed=a.seed)
    sim_mar = simular_azar(items, p_mar, seed=a.seed)
    for nombre, sim, probs in (("azar_uniforme", sim_uni, p_uni),
                               ("azar_marginal", sim_mar, p_mar)):
        por_tipo = {}
        for it, p in zip(items, probs):
            d = por_tipo.setdefault(it["tipo"], [0.0, 0])
            d[0] += p
            d[1] += 1
        resultados.append({
            "brazo": nombre, "n": len(items),
            "aciertos": int(round(sim["media"])),
            "exactitud": sim["media_frac"], "cerca": 0, "sin_formato": 0,
            "ok": [], "seg": 0.0,
            "por_tipo": {t: (round(v[0], 1), v[1])
                         for t, v in por_tipo.items()},
            "p95": cuantil(sim["dist"], 0.95)})

    # -- techo del brazo tonto: cuanta info le llega siquiera.
    ventana = None
    url = ""
    if a.brazos in ("tonto", "rlm", "todos"):
        from cognia.first_run import apply_config
        apply_config()
        from cognia.agent.model_profiles import url_del_backend, perfil_del_agente
        url = url_del_backend()
        if not _salud(url):
            print("SIN BACKEND: %s/health no responde." % url)
            return 3
        perfil = perfil_del_agente(forzar=True)
        ventana = perfil.get("n_ctx") or 0
        print("cerebro: %s | ventana %s tokens\n"
              % (perfil.get("modelo"), "{:,}".format(ventana)))

    if not ventana and a.ventana:
        ventana = a.ventana        # techo del tonto sin gastar GPU
    if ventana:
        corte, tk = corte_para_ventana(url, texto, ventana) if url else             (min(len(texto), int(max(512, ventana - 2200) * CHARS_POR_TOKEN)),
             None)
        print("techo del tonto: ventana %s tok -> ve %d de %d chars (%.1f%%)"
              % ("{:,}".format(ventana), corte, len(texto),
                 100.0 * corte / max(1, len(texto))))
        resultados.append(techo_tonto(items, datos, texto, corte))

    if a.brazos in ("tonto", "todos"):
        print("-- brazo TONTO (todo lo que quepa en la ventana)")
        resultados.append(brazo_tonto(items, texto, url, ventana))
    if a.brazos in ("rlm", "todos"):
        # PREVUELO: el modo RLM se toca SOLO con tools nativas. Contra un
        # server que no las parsea, correr_rlm devuelve un texto de ERROR por
        # pregunta y el banco anotaria 0/90 "del modelo". Verificado el
        # 2026-08-18: :8080 servia qwen2.5-coder-14b sin --jinja y el brazo
        # entero era ruido del instrumento.
        from cognia.agent import capacidad as _cap
        if not _cap.soporta_tools(url):
            print("SIN TOOL-CALLING en %s: el brazo RLM no se puede correr, "
                  "y NO se anota como 0.\n  causa: %s\n"
                  "Arranca el server con --jinja o servi un modelo que emita "
                  "tool_calls; re-medi con:\n"
                  "  venv312\\Scripts\\python.exe -m cognia.agent.capacidad "
                  "%s --forzar"
                  % (url, _cap.medicion(url).get("motivo", ""), url))
            return 3
        print("-- brazo RLM")
        import tempfile
        ruta = Path(tempfile.mkdtemp(prefix="rlm_sint_")) / "corpus.txt"
        ruta.write_text(texto, encoding="utf-8")
        resultados.append(brazo_rlm(items, ruta, url))

    print(_tabla(resultados, items))
    # CERCA: acierto con tolerancia +-1 en los conteos. No es la metrica
    # primaria (el banco puntua exacto) pero distingue "esta en el orden
    # correcto y se le escapa uno" de "contesta cualquier cosa" — dos fallos
    # que piden decisiones opuestas.
    cercas = [r for r in resultados
              if r["brazo"] in ("tonto", "rlm") and r["n"]]
    if cercas:
        print("cerca (+-1 en los conteos, secundario): "
              + "  ".join("%s %d/%d" % (r["brazo"], r["cerca"], r["n"])
                          for r in cercas))

    # -- estadistica preregistrada.
    por_nombre = {r["brazo"]: r for r in resultados}
    print("\nPOTENCIA (calculada con este N, antes de creerle a nadie)")
    for nombre, sim in (("azar_uniforme", sim_uni), ("azar_marginal", sim_mar)):
        m = mde(p_uni if nombre == "azar_uniforme" else p_mar, sim["dist"])
        print("  vs %-14s azar=%.1f%% p95=%d/%d  MDE(alpha .05, poder .80) = "
              "%.1f%% de exactitud"
              % (nombre, 100 * sim["media_frac"], cuantil(sim["dist"], 0.95),
                 len(items), 100 * m))
    # El p-valor se calcula para TODO brazo con GPU, no solo para el RLM: el
    # brazo tonto tambien tiene que demostrar que le gana al azar antes de
    # que su numero signifique algo.
    for clave in ("tonto", "rlm"):
        if clave not in por_nombre:
            continue
        r = por_nombre[clave]
        for nombre, sim in (("azar_uniforme", sim_uni),
                            ("azar_marginal", sim_mar)):
            p = p_valor_superior(sim["dist"], r["aciertos"])
            print("  %-5s %d/%d vs %-14s P(azar >= observado) = %.5f%s"
                  % (clave.upper(), r["aciertos"], r["n"], nombre, p,
                     "" if p > 0.05 else "   <- rechaza el nulo"))
    if "rlm" in por_nombre and "tonto" in por_nombre:
        mc = mcnemar_exacto(por_nombre["rlm"]["ok"], por_nombre["tonto"]["ok"])
        print("  RLM vs TONTO (McNemar exacto, pareado): "
              "solo-RLM=%d solo-TONTO=%d p=%.4f"
              % (mc["b"], mc["c"], mc["p"]))

    if a.salida:
        Path(a.salida).write_text(json.dumps(
            {"celda": a.celda, "corpus_version": VERSION_CORPUS,
             "filler": filler, "chars": len(texto),
             "items": [{k: v for k, v in it.items() if k != "espacio"}
                       for it in items],
             "resultados": [{k: v for k, v in r.items() if k != "dist"}
                            for r in resultados]},
            ensure_ascii=False, indent=1), encoding="utf-8")
        print("\njson -> %s" % a.salida)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
