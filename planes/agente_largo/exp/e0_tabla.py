# -*- coding: utf-8 -*-
"""Las tablas de E0 a partir de `e0_out.json`. Separado del que corre para
poder re-analizar sin volver a gastar 54 min de GPU.

LO QUE IMPRIME Y POR QUE:
  1. Tabla por brazo (medias) -- para orientarse, NADA MAS. La varianza ENTRE
     corridas de este proyecto llego a +-34 puntos: una media entre corridas no
     es evidencia de nada.
  2. NETOS APAREADOS intra-corrida (TX menos cada rival, misma semilla, misma
     tarea, mismas observaciones). ESTO es la evidencia.
  3. Signo: en cuantas de las n corridas TX gana / empata / pierde.

CORRER:
  venv312\\Scripts\\python.exe planes/agente_largo/exp/e0_tabla.py
"""

import json
import os
import sys

RUTA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "e0_out.json")

METRICAS = (
    ("recall", "recall_restricciones@N", 1),
    ("demandas_pct", "demandas satisfechas", 1),
    ("objetivo_pct", "sondas de objetivo vivas", 1),
    ("maq_tok", "tokens de maquinaria", -1),
    ("maq_seg", "segundos de maquinaria", -1),
    ("trabajo_tok", "tokens de trabajo (prompt+salida)", -1),
    ("segundos", "segundos de pared", -1),
)


def derivar(f):
    maq = f.get("maquinaria") or {}
    tra = f.get("trabajo") or {}
    sondas = f.get("objetivo_sondas") or []
    return {
        "brazo": f["brazo"],
        "corrida": f["corrida"],
        "recall": f["recall"],
        "primaria_cortada": bool(f.get("primaria_cortada")),
        "cortes": int(f.get("cortes_no_recuperados") or 0),
        "reintentos": int(f.get("reintentos_por_corte") or 0),
        "demandas_pct": (f["demandas_ok"] / float(f["demandas_n"])
                         if f["demandas_n"] else None),
        "objetivo_pct": (sum(1 for s in sondas if s["vivo"]) / float(len(sondas))
                         if sondas else None),
        "maq_tok": int(maq.get("prompt", 0)) + int(maq.get("salida", 0)),
        "maq_seg": round(float(maq.get("seg", 0.0)) + float(f.get("maq_seg_no_llm", 0.0)), 1),
        "trabajo_tok": int(tra.get("prompt", 0)) + int(tra.get("salida", 0)),
        "segundos": f["segundos_corrida"],
        "ciclo_perdida": f.get("ciclo_perdida_objetivo"),
        "resets": f.get("resets"),
        "anchos": f.get("anchos"),
        "truncados_izq": f.get("truncados_izq"),
        "salidas": f.get("salidas_commit"),
        "finish": f.get("finish_reason") or {},
        "errores": f.get("errores_backend") or [],
    }


def main():
    ruta = sys.argv[1] if len(sys.argv) > 1 else RUTA
    with open(ruta, "r", encoding="utf-8") as fh:
        crudo = json.load(fh)
    filas = [derivar(f) for f in crudo["filas"]]
    brazos = []
    for f in filas:
        if f["brazo"] not in brazos:
            brazos.append(f["brazo"])
    corridas = sorted(set(f["corrida"] for f in filas))
    idx = {(f["brazo"], f["corrida"]): f for f in filas}

    print("E0 -- %d ciclos, %d corridas, reset cada %d, n_ctx estrecho %d"
          % (crudo["n_ciclos"], crudo["n_corridas"], crudo["cada"], crudo["w_ctx"]))
    print("n = %d corridas por brazo, PAREADAS por semilla" % len(corridas))
    aparte = sorted(set(f["brazo"] for f in crudo["filas"]
                        if f.get("anadido_aparte")))
    if aparte:
        # Se DICE: un brazo anadido despues comparte semilla (sigue pareado)
        # pero NO comparte el intercalado en el tiempo. Callarlo seria contar
        # como intercalado algo que no lo fue.
        print("AVISO: %s se anadio en una pasada aparte (misma semilla -> "
              "sigue pareado; NO intercalado en el tiempo con los demas)"
              % ", ".join(aparte))
    print("")

    # --- 1. medias por brazo (orientacion, NO evidencia)
    print("== 1. Medias por brazo (orientacion; la evidencia es la tabla 3) ==")
    cab = "%-11s" % "brazo"
    for _, nombre, _ in METRICAS:
        cab += " %>18s".replace(">", "") % nombre[:18]
    print("%-11s %8s %8s %8s %10s %8s %10s %8s"
          % ("brazo", "recall", "demanda", "objetiv", "maq_tok", "maq_s",
             "trab_tok", "pared_s"))
    for b in brazos:
        fs = [idx[(b, c)] for c in corridas if (b, c) in idx]
        def m(k):
            vs = [f[k] for f in fs if f[k] is not None]
            return sum(vs) / float(len(vs)) if vs else float("nan")
        print("%-11s %8.3f %8.3f %8.3f %10.0f %8.1f %10.0f %8.0f"
              % (b, m("recall"), m("demandas_pct"), m("objetivo_pct"),
                 m("maq_tok"), m("maq_seg"), m("trabajo_tok"), m("segundos")))
    print("")

    # --- 2. la primaria, corrida a corrida
    print("== 2. La PRIMARIA corrida a corrida: recall_restricciones@N ==")
    print("%-11s %s" % ("brazo", " ".join("c%d" % c for c in corridas)))
    for b in brazos:
        vs = []
        for c in corridas:
            f = idx.get((b, c))
            vs.append("%.3f" % f["recall"] if f else "  -  ")
        print("%-11s %s" % (b, " ".join(vs)))
    print("")

    # --- 3. NETOS APAREADOS: TX menos cada rival, dentro de la MISMA corrida
    print("== 3. NETOS APAREADOS intra-corrida (TX menos el rival) -- LA EVIDENCIA ==")
    for clave, nombre, signo in METRICAS:
        print("-- %s  (%s es mejor para TX)"
              % (nombre, "positivo" if signo > 0 else "negativo"))
        for b in brazos:
            if b == "TX":
                continue
            netos = []
            for c in corridas:
                a, r = idx.get(("TX", c)), idx.get((b, c))
                if not a or not r or a[clave] is None or r[clave] is None:
                    continue
                netos.append(a[clave] - r[clave])
            if not netos:
                continue
            gana = sum(1 for x in netos if x * signo > 0)
            pierde = sum(1 for x in netos if x * signo < 0)
            empata = len(netos) - gana - pierde
            print("   TX - %-11s n=%d  media %+9.3f  rango [%+.3f, %+.3f]  "
                  "gana %d / empata %d / pierde %d"
                  % (b, len(netos), sum(netos) / float(len(netos)),
                     min(netos), max(netos), gana, empata, pierde))
        print("")

    # --- 4. lo que hay que mirar ANTES de atribuir nada al modelo
    malas = [f for f in filas if f["primaria_cortada"]]
    if malas:
        # Una fila cuya sonda de la PRIMARIA salio cortada NO mide memoria:
        # mide el tope de tokens. Se dice y se ve, en vez de promediarla.
        print("!! %d fila(s) con la sonda de la PRIMARIA cortada: %s"
              % (len(malas), ", ".join("%s c%d" % (f["brazo"], f["corrida"])
                                       for f in malas)))
        print("")

    print("== 4. Instrumento: finish_reason, errores de backend, salidas de commit ==")
    for b in brazos:
        fin, err, sal, tru = {}, 0, [], 0
        for c in corridas:
            f = idx.get((b, c))
            if not f:
                continue
            for k, v in (f["finish"] or {}).items():
                fin[k] = fin.get(k, 0) + v
            err += len(f["errores"])
            if f["salidas"]:
                sal += f["salidas"]
            tru += int(f["truncados_izq"] or 0)
        rei = sum(idx[(b, c)]["reintentos"] for c in corridas if (b, c) in idx)
        cor = sum(idx[(b, c)]["cortes"] for c in corridas if (b, c) in idx)
        print("%-11s finish=%s  errores_backend=%d  reintentos_por_corte=%d  "
              "cortes_no_recuperados=%d  truncados_izq=%d  commits=%s"
              % (b, fin, err, rei, cor, tru, sal or "-"))
    print("")
    print("== 5. ciclo en que se pierde el objetivo (None = no se perdio) ==")
    for b in brazos:
        print("%-11s %s" % (b, [idx[(b, c)]["ciclo_perdida"]
                                for c in corridas if (b, c) in idx]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
