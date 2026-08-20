# -*- coding: utf-8 -*-
"""GATES -- las comparaciones mecanicas que abren o cierran el reset.

EL CRITICO DE ESTE SISTEMA NO ES UN LLM: es codigo que ejecuta. Un critico que
solo opina midio exactitud balanceada 0,517 (azar); el adjetivo del prompt movio
la deteccion 21x. En la ruta critica del commit no hay ni una llamada de juicio:
sha256, exit codes, substring literal, GROUP BY, igualdad de bytes. Nada mas.

TODOS los gates corren con el CONTEXTO VIEJO TODAVIA VIVO (fase PREPARE), menos
G2, que por definicion se mide DESPUES de destruir, sobre la primera respuesta
de la sesion nueva (ESPEC 6.5, P0-4).

Cada gate devuelve el mismo dict: {gate, ok, detalle, banda, datos}. `banda` es
la banda implicada -- la usa la escalera de aborto para saber a quien robarle
topes; sin ese campo el escalon 1 seria adivinar.
"""

import os
import re
import time

from cognia.tx import bandas
from cognia.tx import claves as _claves

# El fuzzy (canal.conservacion, cobertura de tokens al 0,6) SE CALCULA, SE
# MUESTRA y NO VOTA (ESPEC 6.4): una parafrasis puntua "presente" con el ID
# perdido. El gate solo admite igualdad de bytes, igualdad de ID exacto o exit
# code. Esta constante existe para que quede escrito que la decision fue
# deliberada y no un olvido.
EL_FUZZY_NO_VOTA = True


def veredicto(gate, ok, detalle, banda=None, **datos):
    return {"gate": gate, "ok": bool(ok), "detalle": str(detalle),
            "banda": banda, "datos": datos}


# --------------------------------------------------------------------- G1

def g1_banda_permanente(eventos, sha_p0):
    """G1: sha(banda P) == sha_P0. IGUALDAD DE BYTES, no de sentido.

    Es el gate que sostiene todo el diseno: si la cabecera permanente no se
    re-emite byte a byte, el reset esta perdiendo el contrato y ningun otro
    gate lo notaria (todos los demas miran el mundo, no la memoria). La
    seleccion de restricciones midio recall 0,526 y la cascada de resumenes
    0,083, siempre en silencio -- por eso aqui no hay tolerancia ninguna.
    """
    actual = bandas.sha_banda_permanente(eventos)
    ok = bool(sha_p0) and actual == sha_p0
    if not sha_p0:
        return veredicto("G1", False,
                         "no hay sha_P0 sembrado: no se puede comprobar que la "
                         "banda P sobreviva. Un gate sin referencia no aprueba",
                         banda="P", sha=actual)
    return veredicto("G1", ok,
                     "sha P %s (esperado %s)" % (actual, sha_p0),
                     banda="P", sha=actual, esperado=sha_p0)


# --------------------------------------------------------------------- G2

def g2_trazadores(estado_canal, respuesta):
    """G2: cuantos trazadores cito el MODELO en su primera respuesta tras el
    reset. Se mide sobre la RESPUESTA, jamas sobre la proyeccion (ESPEC 6.5).

    Comprobar los trazadores contra la salida de una funcion pura que acaba de
    escribirlos verbatim es una tautologia: 6/6 en el ciclo 1 y en el 500,
    informacion cero. Sobre la respuesta si mide algo: si el modelo LEYO.
    """
    try:
        from cognia.estado import canal
    except Exception as exc:
        return veredicto("G2", False,
                         "no pude importar estado.canal: %r" % exc, banda="T")
    d = canal.g2_sobre_respuesta(estado_canal or {}, respuesta or "")
    total = d.get("n") or 0
    presentes = len(d.get("presentes") or [])
    if not total:
        # Sin trazadores sembrados no hay medida. NO es un aprobado: es que el
        # instrumento no esta puesto, y decir OK aqui seria el vacio silencioso.
        return veredicto("G2", False,
                         "0 trazadores sembrados: G2 no puede medir nada",
                         banda="T", presentes=0, total=0)
    if not d.get("mide_lectura"):
        return veredicto("G2", False,
                         d.get("motivo") or "la respuesta no mide lectura",
                         banda="T", presentes=presentes, total=total)
    return veredicto("G2", presentes == total,
                     "trazadores en la respuesta %d/%d (perdidos: %s)"
                     % (presentes, total, ",".join(d.get("perdidos") or []) or "-"),
                     banda="T", presentes=presentes, total=total,
                     perdidos=list(d.get("perdidos") or []))


# --------------------------------------------------------------------- G3

def g3_artefactos(eventos, workspace=None):
    """G3: el sha de cada artefacto vivo, RELEIDO DEL DISCO.

    MVP: se re-hashea TODO, criticos y no criticos. La ESPEC permite el atajo
    mtime+size para los no criticos, pero un atajo que debilita el gate sin que
    su ahorro este MEDIDO es exactamente "el test que pasa por el motivo
    equivocado". Entra cuando el coste se mida por encima del 1 % del ciclo.

    Una fila ya marcada `sospechoso` (stale) NO vuelve a suspender: su
    divergencia ya esta registrada y la proyeccion ya lleva el aviso de
    RE-LEER. Si volviese a suspender, el ciclo se quedaria abortando para
    siempre por el mismo hecho ya conocido.
    """
    estado = bandas.fold(eventos)
    filas = [v for v in estado["vivos"].values()
             if v.get("banda") == "A" and v.get("id") not in estado["invalidados"]]
    ok_n, divergen, ausentes, saltadas = 0, [], [], 0
    for f in filas:
        ruta = _claves.ruta_de_clave(f.get("clave"))
        if not ruta:
            continue
        if f.get("estado") == "sospechoso":
            saltadas += 1
            continue
        absoluta = _claves.normalizar_ruta(ruta, workspace)
        actual = _claves.sha_de_fichero(absoluta)
        esperado = f.get("valor")
        if actual is None:
            ausentes.append((f.get("id"), ruta))
        elif esperado is not None and actual != esperado:
            divergen.append((f.get("id"), ruta, esperado, actual))
        else:
            ok_n += 1
    total = ok_n + len(divergen) + len(ausentes)
    ok = not divergen and not ausentes
    partes = ["artefactos %d/%d" % (ok_n, total)]
    if not total and not saltadas:
        # BANDA A VACIA. El veredicto sigue siendo verde a proposito -- una
        # tarea de lectura no escribe ficheros y ponerlo en rojo la mandaria a
        # HARD_STOP a los 3 anchos por no haber hecho nada malo -- pero NO
        # puede leerse como "los artefactos estan bien": no hay ninguno que
        # mirar. `vacia` lo dice y el CLI lo pinta en ambar, igual que hace con
        # G5 cuando no ejecuto ningun criterio.
        return veredicto("G3", True,
                         "banda A VACIA: G3 no esta midiendo nada (ninguna "
                         "tool ha escrito un fichero todavia)",
                         banda="A", divergen=[], ausentes=[], total=0, ok_n=0,
                         vacia=True)
    if divergen:
        partes.append("sha cambio: " + "; ".join(
            "%s %s %s->%s" % (i, r, e, a) for i, r, e, a in divergen))
    if ausentes:
        partes.append("no estan en disco: " + "; ".join(
            "%s %s" % (i, r) for i, r in ausentes))
    if saltadas:
        partes.append("%d ya marcados stale" % saltadas)
    return veredicto("G3", ok, " | ".join(partes), banda="A",
                     divergen=divergen, ausentes=ausentes, total=total, ok_n=ok_n)


# --------------------------------------------------------------------- G4

def g4_contradicciones(eventos):
    """G4: `GROUP BY clave HAVING COUNT(DISTINCT valor) > 1` entre filas
    VIGENTES y `verificado`. Determinista, microsegundos, cero LLM.

    `dec:` y `nota:` quedan FUERA (ESPEC 3.4 y 7.6): son prosa del modelo, y
    dos opiniones distintas no son una contradiccion medible. Punto ciego
    DECLARADO, no escondido -- meterlas dentro haria que G4 abortase resets por
    desacuerdos del modelo consigo mismo, que es justo el juicio que este
    diseno saca de la ruta critica.

    EL FILTRO SIGUE SIENDO `estado == 'verificado'` (C3 de la ESPEC 7.6 lo dice
    literalmente: "dos filas vigentes y verificado"), y NO "origen medido".
    Cambiarlo a origen convertiria en contradiccion lo que es trabajo normal:
    el mismo pytest medido en rojo antes del arreglo y en verde despues son dos
    valores de la misma clave, y G4 abortaria todos los commits del dia. Lo que
    SI estaba roto era que nadie escribiera filas verificadas con clave -- el
    interceptor no ponia `estado` en ninguna -- asi que G4 salia verde
    midiendo cero y desde fuera se veia igual que "no hay contradicciones".
    Por eso `candidatos` va en el detalle: 0 claves y 0 contradicciones son dos
    cosas distintas y ahora se distinguen.
    """
    estado = bandas.fold(eventos)
    por_clave = {}
    candidatos = 0
    for v in estado["vivos"].values():
        if v.get("id") in estado["invalidados"]:
            continue
        if v.get("estado") != "verificado":
            continue
        clave = v.get("clave")
        if not clave or not _claves.cuenta_para_contradiccion(clave):
            continue
        candidatos += 1
        por_clave.setdefault(clave, {}).setdefault(repr(v.get("valor")), []).append(v.get("id"))
    choques = [(k, vs) for k, vs in por_clave.items() if len(vs) > 1]
    choques.sort()
    if not choques:
        return veredicto("G4", True,
                         "0 contradicciones vivas (%d fila(s) verificada(s) "
                         "sobre %d clave(s) candidatas)"
                         % (candidatos, len(por_clave)),
                         banda="E", candidatos=candidatos,
                         claves=len(por_clave), vacia=not candidatos)
    detalle = "; ".join(
        "%s -> %s" % (k, " vs ".join("%s%s" % (val, ids) for val, ids in sorted(vs.items())))
        for k, vs in choques)
    return veredicto("G4", False, "contradicciones vivas: " + detalle,
                     banda="E", choques=choques, candidatos=candidatos,
                     claves=len(por_clave), vacia=False)


# --------------------------------------------------------------------- G5

def g5_monotonia(contrato, progreso_previo=None, evidencia=None):
    """G5: el progreso verificado no RETROCEDE. Retroceso = deriva, por
    definicion (ESPEC 10.2).

    Corre `GoalContract.check(solo_baratos=True)`: el criterio POR CICLO tiene
    que costar <5 s o G5 se come el 31 % del ciclo. Los criterios caros no
    cuentan ni como PASS ni como FAIL -- se saltan y se dicen. `cwd=workspace`
    lo resuelve el propio contrato (P0-3): sin eso, `file_exists` mediria un
    homonimo del CWD del proceso y daria un PASS sobre un artefacto que la
    tarea nunca produjo.

    Sin contrato NO hay aprobado. `/tx iniciar` se para si no hay criterio
    verificable (ESPEC 9.4, puerta 1) precisamente para que este caso no
    exista; si aun asi llega aqui, es una averia y se dice.
    """
    if contrato is None:
        return veredicto("G5", False,
                         "sin GoalContract: no se puede medir monotonia. "
                         "/tx iniciar exige al menos un criterio verificable",
                         banda="E")
    t0 = time.perf_counter()
    try:
        estado = contrato.check(evidence=evidencia, solo_baratos=True)
    except Exception as exc:
        return veredicto("G5", False, "el contrato reviento: %r" % exc, banda="E")
    gastado = int((time.perf_counter() - t0) * 1000)
    ahora = int(estado.satisfied_count)
    # Los caros no se reejecutan pero SI cuentan con su ultimo veredicto
    # (ESPEC 9.5). Se dice cuantos, porque "3/3 medidos ahora" y "3/3 con dos
    # heredados" no significan lo mismo y el numero solo no los distingue.
    heredados = int(getattr(estado, "heredados", 0) or 0)
    cola = ("  [%d heredado(s), no reejecutados este ciclo]" % heredados
            if heredados else "")
    # Un criterio que se paso de timeout es un flaky del INSTRUMENTO (ESPEC
    # 9.5 y C2), no un FAIL: no puede disparar ni el aborto ni un rollback.
    flaky = [r.criterion.description for r in estado.results if getattr(r, "timeout", False)]
    if progreso_previo is None:
        return veredicto("G5", True,
                         "progreso %d/%d (primera medida, sin referencia previa) "
                         "%d ms%s" % (ahora, estado.total, gastado, cola),
                         banda="E", progreso=ahora, total=estado.total,
                         ms=gastado, flaky=flaky, heredados=heredados)
    ok = ahora >= int(progreso_previo)
    if not ok and flaky:
        # Retroceso explicado por un timeout: no cuenta. Distinguirlo importa
        # porque las dos situaciones piden decisiones opuestas (abortar el
        # reset contra reintentar el criterio).
        return veredicto("G5", True,
                         "progreso %d -> %d con %d criterio(s) en timeout "
                         "(flaky de instrumento, no FAIL): %s"
                         % (progreso_previo, ahora, len(flaky), "; ".join(flaky)),
                         banda="E", progreso=ahora, total=estado.total,
                         ms=gastado, flaky=flaky, heredados=heredados)
    return veredicto("G5", ok,
                     "progreso %s -> %d de %d (%d ms)%s"
                     % (progreso_previo, ahora, estado.total, gastado, cola),
                     banda="E", progreso=ahora, total=estado.total,
                     ms=gastado, flaky=flaky, heredados=heredados)


# --------------------------------------------------------------------- G6

def g6_ciclo_mudo(eventos, ciclo):
    """G6: el ciclo produjo al menos UN evento medido (origen='medido').

    POR QUE ES IMPRESCINDIBLE: un ciclo de pura prosa no tiene firma que
    repetir. Proyeccion identica -> respuesta identica -> punto fijo
    determinista y silencioso, y LOOP-A/B/C no lo ven. G6 es la unica defensa
    contra ese punto fijo, y por eso entra bajo `/tx mutar`.

    `origen='medido'` y no "hubo eventos": con P0-1, `medido` significa que
    hubo un exit code entero de verdad. Un comando bloqueado por el sentinel
    baja a `derivado` y NO cuenta como actividad -- si contase, un ciclo entero
    de llamadas bloqueadas pasaria por productivo.
    """
    medidos = [e for e in (eventos or [])
               if int(e.get("ciclo", -1)) == int(ciclo)
               and e.get("origen") == "medido"]
    if medidos:
        return veredicto("G6", True,
                         "%d evento(s) medido(s) en el ciclo %s"
                         % (len(medidos), ciclo),
                         banda="E", medidos=len(medidos))
    # QUE HACER, no solo que falta. Lo PRIMERO que ve quien sigue la ESPEC al
    # pie de la letra es este gate en rojo, porque el ciclo 1 todavia no ha
    # ejecutado nada: es correcto y es desmoralizante. El aviso dice por que
    # esta rojo y como se pone verde, en vez de dejar al dueno pensando que el
    # subsistema esta roto en su primera pantalla.
    return veredicto("G6", False,
                     "0 evento(s) medido(s) en el ciclo %s: ninguna tool con "
                     "exit real todavia. Se pone verde en cuanto el agente "
                     "ejecute algo; no es una averia del gate" % ciclo,
                     banda="E", medidos=0, vacia=True)


# ------------------------------------------------------------------ loops

def firma_ciclo(eventos, ciclo, criterios_satisfechos=()):
    """LOOP-A (ESPEC 10.1): sha del conjunto ORDENADO de (tool, ruta_destino)
    del ciclo + el conjunto de criterios satisfechos.

    Conjunto y no lista: repetir las mismas 8 acciones en otro orden es el
    mismo ciclo. Y los criterios entran en la firma porque repetir acciones
    mientras el progreso AVANZA no es un bucle, es un bucle util.
    """
    pares = set()
    for e in eventos or []:
        if int(e.get("ciclo", -1)) != int(ciclo):
            continue
        prov = e.get("prov") or {}
        tool = str(prov.get("cmd") or e.get("t") or "")
        ruta = str(prov.get("ruta_destino") or e.get("clave") or "")
        if tool or ruta:
            pares.add((tool, ruta))
    cuerpo = "|".join(sorted("%s>%s" % p for p in pares))
    cuerpo += "||" + "|".join(sorted(str(c) for c in criterios_satisfechos or ()))
    return _claves.sha14(cuerpo)


def detectar_loop(historial, max_periodo=3):
    """Los detectores de repeticion sobre el historial de firmas de ciclo.

    `historial` = [{"ciclo": k, "firma": s, "criterios": <set>}], mas viejo
    primero.

    Detecta DOS formas, y la segunda es la que el adversario marco como no
    cazable:
      - LOOP-A  : la misma firma dos ciclos seguidos sin criterio nuevo.
      - LOOP-ALT: dos (o tres) ciclos que se ALTERNAN -- A,B,A,B. Ninguna firma
        se repite consecutivamente, asi que LOOP-A no lo ve nunca; el agente
        deshace en el ciclo par lo que hizo en el impar y el contador de
        "misma firma seguida" se queda a 1 para siempre. Se caza buscando
        PERIODO p en 2..max_periodo sobre las ultimas 2p firmas, con la
        condicion de que no haya aparecido ningun criterio nuevo en la ventana
        (si el progreso avanza, oscilar no es un bucle: es trabajo).
    """
    hist = [h for h in (historial or []) if h.get("firma")]
    if len(hist) < 2:
        return {"loop": None, "periodo": 0, "repeticiones": 0, "detalle": "sin historial"}

    def criterios(h):
        return frozenset(h.get("criterios") or ())

    # LOOP-A: misma firma consecutiva, sin criterio nuevo.
    repes = 1
    i = len(hist) - 1
    while i > 0 and hist[i]["firma"] == hist[i - 1]["firma"] \
            and criterios(hist[i]) == criterios(hist[i - 1]):
        repes += 1
        i -= 1
    if repes >= 2:
        return {"loop": "LOOP-A", "periodo": 1, "repeticiones": repes,
                "detalle": "misma firma %s en %d ciclos seguidos sin criterio nuevo"
                           % (hist[-1]["firma"], repes)}

    # LOOP-ALT: periodo p >= 2.
    for p in range(2, int(max_periodo) + 1):
        if len(hist) < 2 * p:
            break
        ventana = hist[-2 * p:]
        firmas = [h["firma"] for h in ventana]
        if len(set(firmas)) < 2:
            continue                     # eso ya lo cubre LOOP-A
        if any(firmas[j] != firmas[j + p] for j in range(p)):
            continue
        if len(set(criterios(h) for h in ventana)) != 1:
            continue                     # el progreso avanzo: no es un bucle
        return {"loop": "LOOP-ALT", "periodo": p, "repeticiones": 2,
                "detalle": "%d ciclos alternandose con periodo %d (%s): ninguna "
                           "firma se repite seguida, LOOP-A no lo ve"
                           % (2 * p, p, " -> ".join(f[:6] for f in firmas))}
    return {"loop": None, "periodo": 0, "repeticiones": repes, "detalle": "sin bucle"}


# ------------------------------------------------------- Q1..Q3 (recitacion)

# Cuantas preguntas y cuantas hay que acertar. Umbral ESTRICTO por asimetria
# declarada (ESPEC 6.3.4): un falso negativo de Q (dice OK y la memoria se
# perdio) cuesta cientos de ciclos de degradacion silenciosa; un falso positivo
# cuesta UN ciclo en MODO ANCHO. Umbral estricto y consecuencia barata.
N_PREGUNTAS = 3

_RE_ESPACIOS = re.compile(r"\s+")
_RE_BORDES = re.compile(r"^[\s\"'`.,:;!?()\[\]-]+|[\s\"'`.,:;!?()\[\]-]+$")


def _norm(texto):
    """Normalizacion de la correccion: minusculas y espacios colapsados.

    NO hay nada mas. Ni stemming, ni sinonimos, ni cobertura de tokens: el
    fuzzy de `canal._presente` puntua "presente" una parafrasis CON EL ID
    PERDIDO (ESPEC 6.4), que es exactamente el falso OK que este control
    existe para evitar.
    """
    t = _RE_ESPACIOS.sub(" ", str(texto or "")).strip().lower()
    return _RE_BORDES.sub("", t)


def acierta(esperado, dada):
    """True si la respuesta contiene la cadena esperada LITERAL (tras
    normalizar espacios y mayusculas).

    Contencion y no igualdad total de la respuesta entera porque el modelo
    contesta en una frase ("El objetivo es: ..."); lo que se exige es que la
    cadena del LIBRO aparezca ENTERA y SEGUIDA. Sigue siendo igualdad de bytes
    sobre la cadena que importa: no interviene ningun juicio del modelo.
    """
    e, d = _norm(esperado), _norm(dada)
    return bool(e) and e in d


def preguntas_de_control(eventos, k=N_PREGUNTAS):
    """Las k preguntas cuya respuesta LITERAL esta en el LIBRO.

    Deterministas y sacadas del propio libro (nunca inventadas por un modelo):
    objetivo, restricciones y trazadores, en ese orden de prioridad. El
    enunciado NUNCA contiene la respuesta -- si la contuviera, el modelo
    aprobaria copiando la pregunta y Q mediria cero.
    """
    estado = bandas.fold(eventos)
    vivos = [v for v in estado["vivos"].values()
             if v.get("id") not in estado["invalidados"]]
    vivos.sort(key=lambda v: int(v.get("n") or 0))
    preguntas = []

    for e in vivos:
        if e.get("t") == "objetivo" and e.get("texto"):
            preguntas.append({"id": "Q1", "n": e.get("n"),
                              "pregunta": "Cita LITERALMENTE, palabra por palabra, "
                                          "el objetivo de esta tarea.",
                              "esperado": e["texto"]})
            break
    for e in vivos:
        if len(preguntas) >= k:
            break
        if e.get("t") in ("restriccion", "definicion") and e.get("texto"):
            preguntas.append({"id": "Q%d" % (len(preguntas) + 1), "n": e.get("n"),
                              "pregunta": "Cita LITERALMENTE el texto de %s "
                                          "(banda P)." % e.get("id"),
                              "esperado": e["texto"]})
    for e in vivos:
        if len(preguntas) >= k:
            break
        if e.get("t") == "trazador" and e.get("id"):
            preguntas.append({"id": "Q%d" % (len(preguntas) + 1), "n": e.get("n"),
                              "pregunta": "Escribe el identificador del trazador "
                                          "que va en la posicion %d de la banda T."
                                          % (len([p for p in preguntas
                                                  if p.get("tipo") == "trz"]) + 1),
                              "esperado": e["id"], "tipo": "trz"})
    for e in vivos:
        if len(preguntas) >= k:
            break
        if e.get("t") in ("criterio", "hecho") and e.get("texto"):
            preguntas.append({"id": "Q%d" % (len(preguntas) + 1), "n": e.get("n"),
                              "pregunta": "Cita LITERALMENTE %s." % e.get("id"),
                              "esperado": e["texto"]})
    return preguntas[:k]


def corregir(preguntas, respuesta):
    """Correccion por igualdad exacta normalizada. Sin juez, sin modelo."""
    fallos = []
    aciertos = 0
    for p in preguntas or []:
        if acierta(p.get("esperado"), respuesta):
            aciertos += 1
        else:
            fallos.append(p.get("id"))
    total = len(preguntas or [])
    return {"aciertos": aciertos, "total": total, "fallos": fallos,
            "ok": total > 0 and aciertos == total}


def recitacion(preguntas):
    """El turno de recitacion VERBATIM que se emite cuando Q<3/3 antes de
    reintentar (ESPEC 2.3 c4). No es un recordatorio en prosa: son las cadenas
    exactas que el modelo tenia que citar, re-emitidas byte a byte."""
    lineas = ["RECITACION (verbatim, del LIBRO):"]
    for p in preguntas or []:
        lineas.append("  %s: %s" % (p.get("id"), p.get("esperado")))
    return "\n".join(lineas) + "\n"


# ----------------------------------------------------- utilidades del gate

def banda_culpable(fallos, informe):
    """La banda a la que robar topes en el escalon 1 de la escalera.

    Solo devuelve algo si la banda implicada por un gate en rojo PERDIO filas
    por su tope: robar topes solo puede arreglar un fallo causado por el tope.
    Si el fallo es otro (un sha que cambio de verdad, un contrato que
    retrocedio), el escalon 1 no aplica y se dice por que en vez de gastar dos
    reintentos identicos.
    """
    por_banda = ((informe or {}).get("bandas") or {})
    for f in fallos or []:
        banda = f.get("banda")
        if not banda or banda in ("P",):
            continue
        if int((por_banda.get(banda) or {}).get("fuera") or 0) > 0:
            return banda
    return None
