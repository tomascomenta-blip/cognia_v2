# -*- coding: utf-8 -*-
"""COMMIT -- el protocolo de dos fases del reset (ESPEC 2.3, 9.1, 9.3).

LA IDEA QUE DEFINE ESTE FICHERO: la compuerta corre ANTES de destruir el
contexto, con el contexto viejo TODAVIA VIVO. La ventana es una CACHE del
LIBRO; destruirla solo es seguro si es reconstruible, y el commit *es* la
prueba de reconstruibilidad, hecha antes de destruir (invariante I1).

Y EL MODO DE FALLO NO ES ABORTAR LA TAREA: es NO RESETEAR (MODO ANCHO) y
seguir trabajando en la misma ventana. Esa es una salida LEGITIMA, no un
parche: el brazo "no hacer nada" es el que midio recall 1,000, contra 0,526 de
la seleccion desde almacen y 0,083 de la cascada de resumenes. Va acotado
(<=3 seguidos, <=10 % de los ciclos) porque el brazo ancho no es caro: DEGRADA
EN SILENCIO -- pasados ~20 ciclos anchos el contexto llega a 0,8*n_ctx y entra
`loop._recortar_mensajes`, que trunca in-place a 200 chars sin resumen y sin
recuperabilidad.

    MAQUINA DE ESTADOS

    PREPARE  (contexto viejo VIVO, nada destruido)
      p0 quiesce  -> ninguna tool en vuelo
      p1 flush    -> las observaciones pendientes al LIBRO
      p2 append tx/prepare + fsync
      p3 proy = bandas.proyectar(libro)        PURA, 0 tokens de LLM
      p4 G1 . G3 . G4 . G5 . G6                ninguno llama al LLM
      p5 fuzzy (canal.conservacion): SE CALCULA, SE MUESTRA, NO VOTA
      GATE = G1 and G3 and G4 and G5 and G6
        verde -> COMMIT
        rojo  -> escalera:  1 robar topes (<=2)
                            2 MODO ANCHO (<=3 seguidos, <=10 %)
                            3 HARD_STOP
    COMMIT   (a partir de aqui la ventana YA no existe)
      c1 append tx/commit + fsync
      c2 destruir()  -> history = [system, proy]
      c3 Q1..Q3 en la sesion NUEVA + G2 sobre LA RESPUESTA
      c4 Q<3/3 -> recitacion verbatim + 1 reintento -> ANCHO. NUNCA mata
    HECHO
"""

import sys
import time

from cognia.tx import bandas, gates
from cognia.tx.errores import LibroCaido

# Escalera de aborto (ESPEC 9.3).
MAX_ROBOS = 2                   # escalon 1: reintentos robando topes
MAX_ANCHOS_SEGUIDOS = 3         # escalon 2
MAX_FRACCION_ANCHOS = 0.10      # escalon 2

# El limite del 10 % no se aplica antes de este numero de ciclos: 1 ancho en el
# ciclo 1 es el 100 % de la tarea y dispararia HARD_STOP en el primer tropiezo.
# El limite existe para cazar una DEGRADACION SOSTENIDA, no un caso aislado.
MIN_CICLOS_PARA_FRACCION = 10

# G6 dos ciclos seguidos en rojo = corte duro (ESPEC 10.1, C6). Un ciclo de
# pura prosa no tiene firma que repetir: es un punto fijo determinista que
# LOOP-A/B/C no ven, y G6 es la unica defensa contra el.
MAX_MUDOS_SEGUIDOS = 2

# LOOP-A / LOOP-ALT a la tercera = FALLO-LOOP (ESPEC 9.2).
MAX_LOOPS = 3

SALIDAS = ("HECHO", "ANCHO", "HARD_STOP")


def _aviso_degradado(motivo):
    """Toda degradacion se dice. Prohibido el `except: pass` mudo: "no lo
    cablearon" y "se rompio" no pueden verse igual desde fuera."""
    try:
        sys.stderr.write("[TX] commit degradado: %s\n" % motivo)
    except Exception:
        pass


def salud_nueva():
    """El estado de salud que el driver arrastra entre ciclos. Es TODO lo que
    el commit recuerda; el resto lo re-lee del LIBRO en cada ciclo."""
    return {
        "ciclos": 0,
        "anchos": 0,              # metrica de salud VISIBLE, no contador oculto
        "anchos_seguidos": 0,
        "mudos_seguidos": 0,
        "loops": 0,
        "historial": [],          # [{ciclo, firma, criterios}] para LOOP-A/ALT
        "progreso": None,         # satisfied_count del ciclo anterior (G5)
        "tx": 0,
        "topes": {},
        "ultimo": "",
    }


def _tx_id(salud):
    return "TX-%04X" % ((int(salud.get("tx") or 0) + 1) & 0xFFFF)


def _append_tx(libro, ciclo, texto, clave=None, valor=None, tx_id=None):
    """Un evento `t=tx` en el LIBRO. Si esto no se puede escribir, LibroCaido
    sube y el ciclo PARA: continuar significaria decidir sobre un pasado
    incompleto sin saberlo."""
    ev = {
        "t": "tx", "op": "add", "banda": "E", "quien": "harness",
        "origen": "derivado", "texto": str(texto)[:400],
        "prov": {"tipo": "derivada", "fn": "commit", "base": ["libro.jsonl"]},
    }
    if tx_id:
        ev["id"] = tx_id
    if clave:
        ev["clave"] = clave
        ev["valor"] = valor
    return libro.append(ev, ciclo=ciclo)


def _fuzzy(estado_canal, proyeccion):
    """`canal.conservacion` SE CALCULA, SE MUESTRA y NO VOTA (ESPEC 6.4).

    Usa cobertura de tokens al 0,6: una parafrasis puntua "presente" con el ID
    perdido. Si el fuzzy da 0,92 y los exactos pasan -> commit y se anota la
    discrepancia; si el fuzzy pasa y un exacto falla -> aborta. Nunca al reves.
    """
    try:
        from cognia.estado import canal
        return canal.conservacion(estado_canal or {}, proyeccion or "")
    except Exception as exc:
        _aviso_degradado("no pude calcular el fuzzy de conservacion: %r" % exc)
        return None


def preparar(ctx, topes=None):
    """FASE PREPARE. NO destruye nada. Devuelve el informe con los gates.

    Se puede llamar sola: es lo que hace `/tx probar` (corre los gates AHORA
    contra el contexto vivo, sin resetear).
    """
    libro = ctx["libro"]
    ciclo = int(ctx.get("ciclo") or 0)
    # `diag` y no `leer()` a secas: `Libro.leer` devuelve el PREFIJO VALIDO MAS
    # LARGO y deja la corrupcion en el diagnostico, pero los dos consumidores de
    # la ruta caliente lo llamaban sin `diag` y nadie miraba. Un libro de 500
    # eventos corrompido en n=50 devolvia 49 en silencio: G1 seguia verde (las
    # filas de la banda P son las primeras y el sha_P0 no se mueve), G3 y G4 ya
    # eran vacuos, y el UNICO gate que reaccionaba era G6 diciendo "0 eventos
    # medidos en el ciclo 41" -- un mensaje que apunta a "el ciclo no hizo
    # nada" cuando lo que paso es que se perdieron 450 eventos. Dos ciclos asi
    # = HARD_STOP con el motivo equivocado.
    diag = {}
    eventos = libro.leer(diag=diag)

    fallos_previos = []
    if diag.get("truncadas") or diag.get("ilegibles") or diag.get("cadena_rota"):
        fallos_previos.append(gates.veredicto(
            "p2", False,
            "LIBRO CORRUPTO: solo se leyeron %d evento(s); %d byte(s) "
            "descartados (%s). Corre /libro fsck ANTES de mirar ningun otro "
            "gate: lo que sigue se decide sobre un pasado incompleto"
            % (len(eventos), diag.get("bytes_descartados") or 0,
               diag.get("motivo") or "?"),
            banda="E", **{k: diag.get(k) for k in
                          ("truncadas", "ilegibles", "cadena_rota",
                           "bytes_descartados", "motivo")}))
    # p0 -- quiesce. Destruir con una tool en vuelo perderia su observacion:
    # la escritura llegaria al LIBRO despues del corte y el evento quedaria
    # colgando de un ciclo que ya no existe.
    en_vuelo = int(ctx.get("tools_en_vuelo") or 0)
    if en_vuelo:
        fallos_previos.append(gates.veredicto(
            "p0", False, "%d tool(s) en vuelo: no se quiesce" % en_vuelo,
            banda="E"))

    # p1 -- flush de observaciones pendientes.
    flush = ctx.get("flush")
    if callable(flush):
        try:
            flush()
        except LibroCaido:
            raise
        except Exception as exc:
            _aviso_degradado("el flush del ciclo fallo: %r" % exc)
            fallos_previos.append(gates.veredicto(
                "p1", False, "flush fallido: %r" % exc, banda="E"))
        else:
            eventos = libro.leer(diag=diag)

    # p3 -- la proyeccion. PURA: 0 tokens de LLM, 0 red, 0 disco fuera del LIBRO.
    informe = {}
    t0 = time.perf_counter()
    proy = bandas.proyectar(eventos, topes=topes, informe=informe)
    ms_proy = int((time.perf_counter() - t0) * 1000)

    # p4 -- los gates. Ninguno llama al LLM. G2 NO esta: se mide despues de
    # destruir, sobre la respuesta de la sesion nueva (ESPEC 6.5).
    t1 = time.perf_counter()
    veredictos = [
        gates.g1_banda_permanente(eventos, ctx.get("sha_p0")),
        gates.g3_artefactos(eventos, workspace=ctx.get("workspace")),
        gates.g4_contradicciones(eventos),
        gates.g5_monotonia(ctx.get("contrato"),
                           progreso_previo=(ctx.get("salud") or {}).get("progreso"),
                           evidencia=ctx.get("evidencia")),
        gates.g6_ciclo_mudo(eventos, ciclo),
    ]
    ms_gates = int((time.perf_counter() - t1) * 1000)

    fallos = fallos_previos + [v for v in veredictos if not v["ok"]]
    return {
        "proyeccion": proy,
        "eventos": eventos,
        "informe": informe,
        "gates": fallos_previos + veredictos,
        "fallos": fallos,
        "abre": not fallos,
        "ms_proy": ms_proy,
        "ms_gates": ms_gates,
        # El fuzzy va en el informe y NO en `abre`. Ver `_fuzzy`.
        "fuzzy": _fuzzy(ctx.get("estado_canal"), proy),
        "p_desborda": bool(informe.get("p_desborda")),
        "p_tokens": informe.get("p_tokens"),
        "diag": dict(diag),
    }


def _puede_ancho(salud):
    """Si MODO ANCHO sigue disponible, y por que no si no lo esta."""
    seguidos = int(salud.get("anchos_seguidos") or 0)
    if seguidos >= MAX_ANCHOS_SEGUIDOS:
        return False, ("%d ciclos anchos CONSECUTIVOS (tope %d): el brazo ancho "
                       "degrada en silencio, no es gratis"
                       % (seguidos, MAX_ANCHOS_SEGUIDOS))
    ciclos = int(salud.get("ciclos") or 0)
    anchos = int(salud.get("anchos") or 0) + 1
    if ciclos >= MIN_CICLOS_PARA_FRACCION and anchos > MAX_FRACCION_ANCHOS * ciclos:
        return False, ("%d anchos sobre %d ciclos supera el %d %%"
                       % (anchos, ciclos, int(MAX_FRACCION_ANCHOS * 100)))
    return True, ""


def _contar_ancho(salud):
    salud["anchos"] = int(salud.get("anchos") or 0) + 1
    salud["anchos_seguidos"] = int(salud.get("anchos_seguidos") or 0) + 1


def _resultado(salida, fase, destruido, detalle, prep, salud, **extra):
    r = {
        "salida": salida,
        "fase": fase,
        "destruido": bool(destruido),
        "detalle": detalle,
        "gates": prep.get("gates") if prep else [],
        "fallos": prep.get("fallos") if prep else [],
        "proyeccion": prep.get("proyeccion") if prep else "",
        "informe": prep.get("informe") if prep else {},
        "fuzzy": prep.get("fuzzy") if prep else None,
        "ms_proy": (prep or {}).get("ms_proy"),
        "ms_gates": (prep or {}).get("ms_gates"),
        "diag": (prep or {}).get("diag") or {},
        "salud": salud,
    }
    r.update(extra)
    salud["ultimo"] = "%s %s" % (salida, detalle)
    return r


def ejecutar(ctx):
    """EL COMMIT ENTERO. Devuelve un dict con `salida` en SALIDAS.

    NUNCA lanza por un gate en rojo: un gate rojo es una decision de no
    resetear, no una averia. Lo unico que sube es `LibroCaido` (no se pudo
    dejar constancia) porque continuar sin constancia significaria decidir
    sobre un pasado incompleto sin saberlo.
    """
    libro = ctx["libro"]
    ciclo = int(ctx.get("ciclo") or 0)
    salud = ctx.setdefault("salud", salud_nueva())
    salud["ciclos"] = int(salud.get("ciclos") or 0) + 1
    topes = dict(salud.get("topes") or {})

    # p2 -- constancia del PREPARE, antes de mirar nada.
    _append_tx(libro, ciclo, "prepare ciclo %d" % ciclo,
               clave="cfg:tx.prepare", valor=ciclo)

    prep = preparar(ctx, topes=topes)

    # --- anti-loop: la firma del ciclo entra en el historial SIEMPRE, resetee
    # o no. Un detector que solo mira los ciclos que resetean se ciega justo en
    # los ciclos anchos, que son los que mas se repiten.
    criterios = frozenset(ctx.get("criterios_satisfechos") or ())
    firma = gates.firma_ciclo(prep["eventos"], ciclo, criterios)
    salud.setdefault("historial", []).append(
        {"ciclo": ciclo, "firma": firma, "criterios": criterios})
    salud["historial"] = salud["historial"][-12:]
    bucle = gates.detectar_loop(salud["historial"])
    if bucle.get("loop"):
        salud["loops"] = int(salud.get("loops") or 0) + 1
        _leccion_anti_loop(libro, ciclo, bucle, firma)
        if salud["loops"] >= MAX_LOOPS:
            return _parar(libro, ciclo, prep, salud,
                          "FALLO-LOOP: %s x%d. %s"
                          % (bucle["loop"], salud["loops"], bucle["detalle"]))

    # --- G6 dos veces seguidas: corte duro.
    mudo = [v for v in prep["gates"] if v["gate"] == "G6" and not v["ok"]]
    salud["mudos_seguidos"] = (int(salud.get("mudos_seguidos") or 0) + 1) if mudo else 0
    if salud["mudos_seguidos"] >= MAX_MUDOS_SEGUIDOS:
        return _parar(libro, ciclo, prep, salud,
                      "FALLO-LOOP: %d ciclos mudos seguidos (G6). Un ciclo de "
                      "pura prosa es un punto fijo que ningun otro detector ve"
                      % salud["mudos_seguidos"])

    # --- banda P que no cabe: HARD_STOP directo, SIN escalera. Antes que
    # truncar la banda P prefiero un agente que se planta a uno que olvida en
    # silencio (ESPEC 9.3 escalon 3, 9.4 puerta 3).
    if prep["p_desborda"]:
        return _parar(libro, ciclo, prep, salud,
                      "HARD_STOP: la banda P ocupa %s tokens (tope %d). NO se "
                      "recorta: hace falta poda humana o partir la tarea"
                      % (prep["p_tokens"], bandas.TOPE_P))

    # --- ESCALON 1: robar topes. Solo si el fallo lo CAUSO un tope.
    robos = 0
    while prep["fallos"] and robos < MAX_ROBOS:
        culpable = gates.banda_culpable(prep["fallos"], prep["informe"])
        if not culpable:
            break
        topes = bandas.robar_topes(topes, culpable)
        robos += 1
        _append_tx(libro, ciclo,
                   "escalera 1: robo topes para la banda %s (intento %d)"
                   % (culpable, robos),
                   clave="cfg:tx.robo_topes", valor=culpable)
        prep = preparar(ctx, topes=topes)
    if robos:
        salud["topes"] = topes

    # --- ESCALON 2: MODO ANCHO. NO se destruye nada.
    if prep["fallos"]:
        motivo = "; ".join("%s: %s" % (f["gate"], f["detalle"])
                           for f in prep["fallos"])
        puede, porque = _puede_ancho(salud)
        if not puede:
            # --- ESCALON 3
            return _parar(libro, ciclo, prep, salud,
                          "HARD_STOP: la compuerta sigue en rojo y el MODO "
                          "ANCHO se agoto (%s). Gates: %s" % (porque, motivo))
        _contar_ancho(salud)
        _append_tx(libro, ciclo,
                   "ANCHO (no destruyo): %s" % motivo[:300],
                   clave="cfg:tx.ancho", valor=salud["anchos_seguidos"])
        return _resultado(
            "ANCHO", "prepare", False,
            "no reseteo, sigo en la misma ventana. %s" % motivo, prep, salud,
            anchos_seguidos=salud["anchos_seguidos"])

    # =================== COMMIT: a partir de aqui se destruye ===============
    # c3 necesita poder preguntar. Sin canal de respuesta no se puede medir Q,
    # y destruir sin poder medir seria exactamente el vacio silencioso.
    responder = ctx.get("responder")
    if not callable(responder):
        _aviso_degradado("no hay `responder`: no puedo medir Q1..Q3 tras el "
                         "reset, asi que no destruyo")
        puede, porque = _puede_ancho(salud)
        if not puede:
            return _parar(libro, ciclo, prep, salud,
                          "HARD_STOP: sin canal de respuesta y sin ANCHO "
                          "disponible (%s)" % porque)
        _contar_ancho(salud)
        return _resultado("ANCHO", "prepare", False,
                          "sin canal de respuesta: no puedo medir Q, no destruyo",
                          prep, salud)

    salud["tx"] = int(salud.get("tx") or 0) + 1
    tx_id = "TX-%04X" % (salud["tx"] & 0xFFFF)
    sha_proy = prep["informe"].get("sha")
    _append_tx(libro, ciclo, "commit %s sha_proy %s" % (tx_id, sha_proy),
               clave="cfg:tx.commit", valor=sha_proy, tx_id=tx_id)

    # c2 -- DESTRUIR. history = [system, proy]. Muere la banda X entera.
    destruido = True
    destruir = ctx.get("destruir")
    if callable(destruir):
        try:
            destruir(prep["proyeccion"])
        except Exception as exc:
            # No se pudo destruir: el estado real es "no reseteado", y decir
            # HECHO aqui dejaria al driver creyendo que la ventana es nueva.
            _aviso_degradado("no pude destruir la ventana: %r" % exc)
            _contar_ancho(salud)
            return _resultado("ANCHO", "commit", False,
                              "el reset no se pudo aplicar: %r" % exc, prep, salud)
    else:
        destruido = False
        _aviso_degradado("no hay `destruir` cableado: el commit se registro "
                         "pero la ventana sigue igual")

    # c3 -- Q1..Q3 + G2 sobre LA RESPUESTA (nunca sobre la proyeccion).
    preguntas = gates.preguntas_de_control(prep["eventos"])
    q, g2, respuesta, reintentos = _preguntar(
        responder, prep["proyeccion"], preguntas, ctx)

    ok_q = q["ok"] and g2["ok"]
    _append_tx(libro, ciclo,
               "%s Q %d/%d %s trz %s/%s" % (
                   tx_id, q["aciertos"], q["total"],
                   "ok" if ok_q else "FALLO",
                   g2["datos"].get("presentes"), g2["datos"].get("total")),
               clave="cfg:tx.control", valor=q["aciertos"])

    if ok_q:
        salud["anchos_seguidos"] = 0
        salud["progreso"] = _progreso(prep)
        return _resultado("HECHO", "commit", destruido,
                          "reset ok, Q %d/%d, trazadores %s/%s"
                          % (q["aciertos"], q["total"],
                             g2["datos"].get("presentes"), g2["datos"].get("total")),
                          prep, salud, q=q, g2=g2, tx=tx_id,
                          respuesta=respuesta, reintentos=reintentos)

    # c4 -- Q<3/3 NUNCA mata la tarea. Se cuenta como ancho (el ciclo se gasto
    # en maquinaria) y el driver deja de resetear hasta que se recupere.
    _contar_ancho(salud)
    salud["progreso"] = _progreso(prep)
    return _resultado("ANCHO", "commit", destruido,
                      "Q %d/%d y G2 %s tras %d reintento(s): NO mata la tarea, "
                      "cuenta como ciclo ancho"
                      % (q["aciertos"], q["total"], g2["detalle"], reintentos),
                      prep, salud, q=q, g2=g2, tx=tx_id,
                      respuesta=respuesta, reintentos=reintentos)


def _progreso(prep):
    for v in prep["gates"]:
        if v["gate"] == "G5":
            return v["datos"].get("progreso")
    return None


def _preguntar(responder, proyeccion, preguntas, ctx):
    """c3 + c4: pregunta, corrige por igualdad exacta normalizada y, si falla,
    re-emite la RECITACION VERBATIM y reintenta UNA vez."""
    texto = proyeccion + "\n" + _enunciado(preguntas)
    respuesta = _llamar(responder, texto, ctx)
    q = gates.corregir(preguntas, respuesta)
    g2 = gates.g2_trazadores(ctx.get("estado_canal"), respuesta)
    if q["ok"] and g2["ok"]:
        return q, g2, respuesta, 0
    # La recitacion no es un recordatorio en prosa ("acuerdate del objetivo"):
    # son las cadenas exactas del LIBRO re-emitidas byte a byte. Recordar mas
    # fuerte no arregla nada -- la adherencia medida es PLANA con el contexto.
    texto2 = gates.recitacion(preguntas) + "\n" + _enunciado(preguntas)
    respuesta2 = _llamar(responder, texto2, ctx)
    q2 = gates.corregir(preguntas, respuesta2)
    g2b = gates.g2_trazadores(ctx.get("estado_canal"), respuesta2)
    return q2, g2b, respuesta2, 1


def _enunciado(preguntas):
    lineas = ["PREGUNTAS DE CONTROL (responde citando LITERALMENTE; se corrigen "
              "por igualdad de bytes, no por sentido):"]
    for p in preguntas or []:
        lineas.append("  %s. %s" % (p.get("id"), p.get("pregunta")))
    # G2 SE MIDE SOBRE ESTA MISMA RESPUESTA (ESPEC 6.5), asi que hay que
    # PEDIR los trazadores. Sin esta linea, `preguntas_de_control` gastaba
    # las 3 preguntas en objetivo + restricciones, el modelo contestaba
    # solo eso, y G2 suspendia SIEMPRE: todo commit salia ANCHO con Q 3/3 y
    # a los 3 seguidos, HARD_STOP. Medido al cablear E0 el 2026-08-19 (2 de
    # 2 commits ANCHO con Q 3/3 y G2 0/4). No revela ninguna respuesta: los
    # identificadores estan en la banda T de la cabecera que el modelo
    # tiene delante, y de eso se trata -- G2 mide si LEYO, no si adivina.
    lineas.append("  T. Copia ademas, uno por linea, los identificadores de "
                  "TODOS los trazadores de la banda T de la cabecera.")
    return "\n".join(lineas) + "\n"


def _llamar(responder, texto, ctx):
    try:
        return responder(texto) or ""
    except Exception as exc:
        _aviso_degradado("la sesion nueva no contesto: %r" % exc)
        return ""


def _leccion_anti_loop(libro, ciclo, bucle, firma):
    """La linea en banda N + la prohibicion. El contador `firma -> n` NO es
    evidencia y NO asciende nada: es un anti-loop y nada mas."""
    libro.append({
        "t": "leccion", "op": "add", "banda": "N", "quien": "harness",
        "origen": "derivado",
        "texto": ("PROHIBIDO repetir el conjunto de acciones %s: %s"
                  % (firma[:8], bucle.get("detalle", "")))[:400],
        "firma": "loop:" + firma[:8],
        "n_veces": int(bucle.get("repeticiones") or 2),
        "prov": {"tipo": "derivada", "fn": "gates.detectar_loop",
                 "base": ["libro.jsonl"]},
    }, ciclo=ciclo)


def _parar(libro, ciclo, prep, salud, motivo):
    """HARD_STOP. Se para y se pide al humano PARTIR LA TAREA o RETIRAR
    RESTRICCIONES. Antes que truncar la banda P."""
    _append_tx(libro, ciclo, ("HARD_STOP: " + motivo)[:400],
               clave="cfg:tx.hard_stop", valor=ciclo)
    return _resultado("HARD_STOP", "prepare", False, motivo, prep, salud)


def _corrupto(res):
    """El aviso de LIBRO CORRUPTO para la linea del ciclo, o '' si esta sano."""
    d = (res or {}).get("diag") or {}
    if not (d.get("truncadas") or d.get("ilegibles") or d.get("cadena_rota")):
        return ""
    return "LIBRO CORRUPTO (%s: %d bytes) -> /libro fsck" % (
        d.get("motivo") or "?", d.get("bytes_descartados") or 0)


def linea_repl(res, ciclo):
    """La UNA linea por ciclo del REPL (ESPEC 14.2). Sin colores ni adornos:
    es lo que el dueno lee para saber si el sistema esta sano."""
    inf = res.get("informe") or {}
    salud = res.get("salud") or {}
    g = {v["gate"]: v for v in (res.get("gates") or [])}
    trozos = ["[TX] c%d %s" % (ciclo, res.get("salida"))]
    if _corrupto(res):
        # ANTES que cualquier otra cosa: si el LIBRO perdio eventos, el resto
        # de la linea se calculo sobre un pasado incompleto.
        trozos.append(_corrupto(res))
    if res.get("tx"):
        trozos.append(str(res["tx"]))
    if "G1" in g:
        trozos.append("P %s" % (g["G1"]["datos"].get("sha") or "?")[:6])
    if res.get("g2"):
        d = res["g2"]["datos"]
        trozos.append("trz %s/%s" % (d.get("presentes"), d.get("total")))
    if "G3" in g:
        trozos.append("art %s/%s" % (g["G3"]["datos"].get("ok_n"),
                                     g["G3"]["datos"].get("total")))
    if res.get("q"):
        trozos.append("Q %d/%d" % (res["q"]["aciertos"], res["q"]["total"]))
    trozos.append("proy %s tok" % inf.get("tokens"))
    trozos.append("anchos %d/%d" % (salud.get("anchos_seguidos") or 0,
                                    MAX_ANCHOS_SEGUIDOS))
    if res.get("salida") != "HECHO":
        trozos.append(str(res.get("detalle") or "")[:160])
    return " . ".join(trozos)
