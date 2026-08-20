# -*- coding: utf-8 -*-
"""PROYECTOR -- `proyectar(eventos) -> texto`. Esto es TODO el "compresor".

FUNCION PURA del LIBRO (invariante I2, ESPEC 1.4 y 5.1): mismo libro, misma
salida byte a byte. Sin LLM, sin red, sin mas disco que el LIBRO. Eso convierte
"aqui no hay compresion acumulativa" en un TEOREMA ESTRUCTURAL en vez de en una
disciplina: no existe la operacion resumen->resumen porque `proyectar` nunca es
entrada de nada que escriba.

POR QUE IMPORTA TANTO: la cascada de resumenes midio recall 0,083 con 24 -> 2
restricciones en UN paso; la seleccion desde almacen inmutable, 0,526; el
verbatim en ventana, 1,000. La banda P se re-emite ENTERA y VERBATIM o el
sistema se planta (HARD_STOP), nunca se recorta.

ORDEN MONOTONO DE `n`, NUNCA POR RECENCIA (ESPEC 5.2): el corte de la cache de
llama.cpp es distancia absoluta ~512 tokens, asi que insertar una linea en
mitad del prefijo cuesta la rehidratacion entera. Reordenar por recencia
reescribiria el principio en cada ciclo.
"""

import re

from cognia.tx.claves import sha14

# Topes en TOKENS por banda (ESPEC 3.6). La banda P NO esta aqui a proposito:
# no pasa por topes. Si no cabe, HARD_STOP (ESPEC 5.1 y 9.4).
TOPES = {
    "T": 120,
    "N": 300,
    "D": 600,
    "F": 750,
    "A": 540,
    "E": 250,      # las contradicciones vivas van SIN TOPE (ESPEC 7.6)
    "Q": 90,
}

# Tope de la banda P. No recorta: es el umbral de HARD_STOP.
TOPE_P = 900

# El orden de emision. X no se emite JAMAS: es lo que muere en el reset.
ORDEN = ("P", "T", "N", "D", "F", "A", "E", "Q")

# 4 chars por token. Aproximacion DECLARADA, no medida: se usa solo para
# decidir topes de render, nunca para contabilidad que se reporte como medida.
# Si algun dia hace falta el numero real, se tokeniza; hasta entonces el sesgo
# es conservador (recorta antes de tiempo, nunca despues).
CHARS_POR_TOKEN = 4

_ETIQUETA = {
    "P": "PERMANENTE (objetivo, restricciones, definicion de hecho, criterios)",
    "T": "TRAZADORES (canarios: si no los citas, no leiste)",
    "N": "NEGATIVO (lecciones y contador firma->n)",
    "D": "DECISIONES",
    "F": "HECHOS",
    "A": "ARTEFACTOS (ruta + sha)",
    "E": "ESTADO (posicion, solo falta, contradicciones vivas)",
    "Q": "CONTROL",
}


def _tokens(texto):
    return (len(texto) + CHARS_POR_TOKEN - 1) // CHARS_POR_TOKEN


def fold(eventos):
    """El fold de la ESPEC 5.1: un solo paso, O(n). Devuelve el estado vivo.

    `vivos` es {id: evento}, `invalidados` el conjunto de ids muertos y
    `firmas` el contador `clave -> n` de la senal negativa comprimida (los
    comandos fallidos son la unica senal no correlacionada que existe: lo que
    muere es la TRAZA CRUDA, no el conocimiento).
    """
    vivos, invalidados, firmas = {}, set(), {}
    orden = {}
    # n -> id. Sin este mapa la poda por dependencia NO DISPARABA NUNCA: aqui
    # `invalidados` lleva IDS ('F-0100') y el unico productor real de
    # decisiones, `tools._decidir`, escribe `prov.base = ['n:813','n:815']`
    # (lo dice su propio comentario: "la provenance la escribe la MAQUINA con
    # los n que se validaron"). 'n:813' nunca esta en un conjunto de ids, asi
    # que la comparacion era False siempre y una decision sobrevivia intacta al
    # hecho medido que la sostenia -- el agujero por el que entra la
    # alucinacion PERSISTENTE, abierto de par en par. Un solo namespace.
    por_n = {}
    for e in eventos or []:
        ident = e.get("id")
        if ident and e.get("n") is not None:
            try:
                por_n[int(e["n"])] = ident
            except (TypeError, ValueError):
                pass
        op = e.get("op")
        if op in ("invalidate", "supersede") and ident:
            invalidados.add(ident)
        if op == "stale":
            if ident in vivos:
                vivos[ident] = dict(vivos[ident], estado="sospechoso")
            continue
        if e.get("t") == "comando":
            clave = e.get("clave")
            if clave:
                firmas[clave] = firmas.get(clave, 0) + 1
        if op in ("add", "amend", "supersede") and ident:
            if ident not in orden:
                # La POSICION la fija el PRIMER add: un `amend` posterior
                # actualiza el contenido en su sitio y NO lo manda al final.
                # Mandarlo al final reescribiria el prefijo y pagaria la
                # rehidratacion entera (ESPEC 5.2).
                orden[ident] = int(e.get("n") or 0)
            vivos[ident] = e

    # PODA POR DEPENDENCIA: una decision cae SOLA si su base murio. Es lo que
    # impide que una conclusion sobreviva al hecho que la sostenia -- el agujero
    # por el que entra la alucinacion persistente (ESPEC 7.3).
    #
    # EN PUNTO FIJO y no en una pasada: una decision B que se apoya en una
    # decision A recien podada tiene que caer tambien, o la cadena se corta en
    # el primer eslabon y B sobrevive sin nada debajo.
    decisiones = [v for v in vivos.values() if v.get("t") == "decision"]
    for _ in range(len(decisiones) + 1):
        cayo = False
        for d in decisiones:
            if d.get("id") in invalidados:
                continue
            if any(_base_muerta(b, invalidados, por_n)
                   for b in ((d.get("prov") or {}).get("base") or [])):
                invalidados.add(d.get("id"))
                cayo = True
        if not cayo:
            break

    return {"vivos": vivos, "invalidados": invalidados, "firmas": firmas,
            "orden": orden, "por_n": por_n}


def _base_muerta(base, invalidados, por_n):
    """True si esta entrada de `prov.base` apunta a algo ya invalidado.

    Acepta las DOS formas que hay en el repo: el id crudo ('F-0100', lo que
    escriben los tests y `cli./libro retractar`) y 'n:<num>' (lo que escribe
    `tools._decidir`, el unico productor real). Que convivan dos formas es lo
    que dejo la poda muerta durante todo el subsistema.
    """
    texto = str(base)
    if texto in invalidados:
        return True
    if texto.startswith("n:"):
        try:
            ident = por_n.get(int(texto[2:]))
        except (TypeError, ValueError):
            return False
        return bool(ident) and ident in invalidados
    return False


def _filas(estado, banda):
    filas = [v for v in estado["vivos"].values() if v.get("banda") == banda]
    filas.sort(key=lambda v: estado["orden"].get(v.get("id"), int(v.get("n") or 0)))
    return filas


def _linea(evento, muerta):
    """Una fila de la proyeccion. Una fila invalidada NO se quita: se marca en
    su sitio con '+' delante (ESPEC 5.2, regla 2). Quitarla moveria todo lo de
    abajo y reescribiria el prefijo."""
    marca = "+" if muerta else " "
    ident = str(evento.get("id") or "?")
    texto = re.sub(r"\s+", " ", str(evento.get("texto") or "")).strip()
    clave = evento.get("clave")
    cola = ""
    if clave:
        cola = "  [%s=%s]" % (clave, evento.get("valor"))
    est = evento.get("estado")
    if est and est != "hipotesis":
        cola += "  <%s>" % est
    return "%s[%s] %s%s" % (marca, ident, texto, cola)


def render_banda_permanente(eventos):
    """La banda P sola, VERBATIM y entera. Es lo que hashea G1 y lo que se
    guarda en `cabecera.txt` (doble soporte, ESPEC 8.4).

    Se separa de `proyectar` porque G1 tiene que poder comprobarla sin
    depender de los topes ni del resto del libro: si G1 leyera de la
    proyeccion completa, un desbordamiento en la banda F cambiaria el sha de P
    y G1 abortaria por el motivo equivocado.
    """
    estado = fold(eventos)
    filas = _filas(estado, "P")
    out = ["== P " + _ETIQUETA["P"] + " =="]
    for f in filas:
        out.append(_linea(f, f.get("id") in estado["invalidados"]))
    return "\n".join(out) + "\n"


def sha_banda_permanente(eventos):
    """sha256[:14] de la banda P renderizada. La constante `sha_P0` de la tarea."""
    return sha14(render_banda_permanente(eventos))


def _render_negativo(estado, tope):
    """Banda N: contador `firma -> n` + lecciones. El contador NO es evidencia
    y NO asciende nada (ESPEC 3.2, 7.2): es un anti-loop, punto."""
    lineas = []
    fallos = sorted([(k, v) for k, v in estado["firmas"].items() if v > 1],
                    key=lambda kv: (-kv[1], kv[0]))
    for clave, n in fallos[:8]:
        lineas.append(" %s x%d" % (clave, n))
    for f in _filas(estado, "N"):
        lineas.append(_linea(f, f.get("id") in estado["invalidados"]))
    return _aplicar_tope(lineas, tope)


def _aplicar_tope(lineas, tope):
    """Recorta a `tope` tokens colapsando POR EL FINAL y diciendo cuanto se
    dejo fuera. Nunca en silencio: la linea de colapso es la puerta a
    `libro_grep`, y sin ella el modelo no sabe que hay mas."""
    if tope is None:
        return lineas, 0
    fuera = 0
    while lineas and _tokens("\n".join(lineas)) > tope:
        lineas.pop()
        fuera += 1
    if fuera:
        lineas.append(" ... %d filas mas antiguas o mas nuevas fuera del tope "
                      "-> libro_grep" % fuera)
    return lineas, fuera


def proyectar(eventos, topes=None, informe=None):
    """La proyeccion completa. PURA: mismo libro -> mismo texto byte a byte.

    `informe` es un dict opcional que se rellena con tokens por banda, filas
    caidas por tope y si la banda P desborda. Se pasa por parametro y no se
    devuelve en una tupla para que el contrato de la funcion siga siendo
    "eventos -> texto" (lo que hace trivial el test de pureza).
    """
    tp = dict(TOPES)
    if topes:
        tp.update({k: v for k, v in topes.items() if k != "P"})
    estado = fold(eventos)
    partes = []
    detalle = {}
    for banda in ORDEN:
        if banda == "P":
            texto = render_banda_permanente(eventos).rstrip("\n")
            detalle["P"] = {"tokens": _tokens(texto), "fuera": 0,
                            "filas": len(_filas(estado, "P"))}
            partes.append(texto)
            continue
        if banda == "N":
            lineas, fuera = _render_negativo(estado, tp.get("N"))
        else:
            filas = _filas(estado, banda)
            crudas = [_linea(f, f.get("id") in estado["invalidados"])
                      for f in filas]
            if banda == "E":
                # Las contradicciones vivas van SIN TOPE y bloquean el cierre
                # (ESPEC 7.6). Se separan del resto de la banda E para que el
                # tope no se coma justo lo que no puede recortarse.
                contras = [c for f, c in zip(filas, crudas)
                           if f.get("t") == "contradiccion"]
                resto = [c for f, c in zip(filas, crudas)
                         if f.get("t") != "contradiccion"]
                resto, fuera = _aplicar_tope(resto, tp.get("E"))
                lineas = contras + resto
            else:
                lineas, fuera = _aplicar_tope(crudas, tp.get(banda))
        cabecera = "== %s %s ==" % (banda, _ETIQUETA[banda])
        detalle[banda] = {"tokens": _tokens("\n".join([cabecera] + lineas)),
                          "fuera": fuera, "filas": len(lineas)}
        partes.append("\n".join([cabecera] + lineas))
    texto = "\n".join(partes) + "\n"
    if isinstance(informe, dict):
        informe.clear()
        informe.update({
            "bandas": detalle,
            "tokens": _tokens(texto),
            "p_tokens": detalle["P"]["tokens"],
            "p_desborda": detalle["P"]["tokens"] > TOPE_P,
            "sha": sha14(texto),
        })
    return texto


def robar_topes(topes, culpable, victimas=("N", "A"), cuanto=120):
    """Escalon 1 de la escalera de aborto (ESPEC 9.3): sube el tope de la banda
    culpable robando de N y de A, las de MENOR persistencia.

    Devuelve un dict nuevo; no muta el que le pasan. Nunca roba de P (no tiene
    tope) ni de E (las contradicciones no se recortan).
    """
    nuevos = dict(TOPES)
    nuevos.update(topes or {})
    if culpable in ("P", "E") or culpable not in nuevos:
        return nuevos
    robado = 0
    for v in victimas:
        if v == culpable or v not in nuevos:
            continue
        # Se deja un suelo: una banda a 0 no es "mas barata", es una banda
        # apagada -- y apagar N apaga el anti-loop.
        disponible = max(0, nuevos[v] - 60)
        toma = min(disponible, cuanto - robado)
        nuevos[v] -= toma
        robado += toma
        if robado >= cuanto:
            break
    nuevos[culpable] += robado
    return nuevos
