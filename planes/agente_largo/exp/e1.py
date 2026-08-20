# -*- coding: utf-8 -*-
"""E1 -- LA MUTACION DEL GATE (ESPEC agente largo, seccion 15.5).

PREGUNTA: cuando la proyeccion se corrompe, .el gate lo caza?
LISTON PRE-REGISTRADO: tasa de deteccion 1,000. Un gate que no caza una
restriccion borrada no protege nada y el diseno NO se despliega.

Y LA OTRA MITAD, que sin ella el 1,000 no vale: FALSOS POSITIVOS sobre
proyecciones SANAS. Un gate que aborta siempre tambien mide 1,000 de deteccion
y no sirve para nada. Por eso cada tarea sintetica se corre DOS veces -- sana y
mutada -- y las dos tienen que dar lo suyo. Eso es `discrimina`.

DISENO
  n = 12 tareas TX REALES (driver.iniciar -> LIBRO en disco -> gates de
  produccion), con la forma variada a proposito: 2..6 restricciones, 2..6
  trazadores, 1..4 artefactos con sha medido del disco. Nada de mocks: si el
  gate solo funciona con la forma que yo elegi, quiero que se vea.

  Por tarea se corren 5 controles SANOS (G1,G2,G3,G4,G6) y 4 MUTACIONES:
    M1 restriccion borrada de la banda P      -> G1
    M2 un digito del trazador cambiado en LA  -> G2
       RESPUESTA (no en la proyeccion: medir
       sobre la proyeccion es la tautologia
       que P0-4 vino a matar)
    M3 sha de un artefacto vivo falseado      -> G3
    M4 ciclo mudo (se le quitan al ciclo los  -> G6
       eventos origen='medido')
    M5 una restriccion reescrita con OTRAS     -> G1
       palabras y el MISMO sentido (la
       parafrasis fiel: el modo de fallo real
       del resumidor, no el borrado)

  M1..M3 se corren POR LA RUTA ENVIADA, `driver.mutar()`, que es literalmente
  lo que ejecuta `/tx mutar` en el REPL: si midiera con una copia mia del
  mutador estaria midiendo mi copia, no el producto. M4 va aparte porque
  `/tx mutar` NO la trae, y ese hueco se reporta.

CORRER:
  venv312\\Scripts\\python.exe planes/agente_largo/exp/e1.py
"""

import json
import os
import shutil
import sys
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

# El experimento es un CONSUMIDOR de TX: declara el flag el mismo para que la
# orden de correrlo sea una sola linea y no dependa de que el shell lo lleve.
os.environ["COGNIA_TX"] = "1"

from cognia.tx import bandas, claves, driver, gates      # noqa: E402
from cognia.tx import libro as almacen                   # noqa: E402

N_TAREAS = 12
PREFIJO = "e1-mut"


# ------------------------------------------------------------ el banco

def _forma(i):
    """La forma de la tarea i. Variada A PROPOSITO: un gate que solo pasa con
    3 restricciones y 4 trazadores no esta probado, esta ajustado."""
    return {
        "restricciones": 2 + (i % 5),
        "trazadores": 2 + ((i * 3) % 5),
        "artefactos": 1 + (i % 4),
    }


def sembrar(i, tmp):
    """Una tarea TX real, con artefactos reales en disco. Devuelve la sesion."""
    forma = _forma(i)
    ws = os.path.join(tmp, "ws%02d" % i)
    os.makedirs(ws, exist_ok=True)
    ses = driver.iniciar(
        "consolidar el modulo %02d sin perder el contrato" % i,
        criterios=[sys.executable + " -c \"pass\""],
        restricciones=["R%02d: no tocar el fichero legado_%02d.py bajo ningun "
                       "concepto" % (j, j) for j in range(1, forma["restricciones"] + 1)],
        pasos=8, horas=1, workspace=ws,
        task_id="%s-%02d-%d" % (PREFIJO, i, int(time.time())),
        semilla=1000 + i, k_trazadores=forma["trazadores"])

    # Artefactos REALES: el fichero existe y el sha se MIDE del disco. Con un
    # sha inventado, G3 suspenderia el control sano y el experimento estaria
    # midiendo mi siembra en vez del gate.
    for a in range(forma["artefactos"]):
        ruta = os.path.join(ws, "art%02d.txt" % a)
        with open(ruta, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("artefacto %d de la tarea %d\n" % (a, i))
        ses["libro"].append({
            "t": "fichero", "op": "add", "banda": "A", "id": "A-%02d" % a,
            "quien": "ejecutor", "origen": "medido", "estado": "verificado",
            "clave": "archivo:" + ruta.replace("\\", "/"),
            "valor": claves.sha_de_fichero(ruta),
            "texto": "artefacto %d escrito por la tarea" % a,
            "prov": {"tipo": "ejecutada", "fn": "e1.sembrar",
                     "cmd": "sha_de_fichero", "base": [ruta]},
        }, ciclo=ses["ciclo"])

    # Un evento MEDIDO en el ciclo vivo: es lo que hace que G6 pueda aprobar.
    # Sin el, el control sano de G6 suspenderia y la tarea no tendria control.
    ses["libro"].append({
        "t": "comando", "op": "add", "banda": "F", "id": "F-CMD",
        "quien": "ejecutor", "origen": "medido", "estado": "verificado",
        "clave": "cmd:pytest -q", "valor": 0,
        "texto": "la suite paso en el ciclo %d" % ses["ciclo"],
        "prov": {"tipo": "ejecutada", "fn": "e1.sembrar",
                 "cmd": "pytest -q", "exit": 0, "base": ["subprocess"]},
    }, ciclo=ses["ciclo"])
    return ses


# --------------------------------------------------- controles SANOS (FP)

def respuesta_sana(ses):
    """La respuesta que un modelo que SI leyo la cabecera escribiria: los
    trazadores citados verbatim. Es la misma cadena que usa `driver.mutar`
    como version sana de M2, para que el sano y el mutado difieran en UN
    caracter y en nada mas."""
    trzs = (ses["estado_canal"] or {}).get("trazadores") or []
    return " ".join(t.get("texto", "") for t in trzs)


def controles_sanos(ses):
    """G1,G2,G3,G4,G6 sobre el LIBRO INTACTO. Cualquier ok=False aqui es un
    FALSO POSITIVO: el gate aborta un reset que no tenia nada roto."""
    eventos = ses["libro"].leer()
    return [
        gates.g1_banda_permanente(eventos, ses["sha_p0"]),
        gates.g2_trazadores(ses["estado_canal"], respuesta_sana(ses)),
        gates.g3_artefactos(eventos, workspace=ses["workspace"]),
        gates.g4_contradicciones(eventos),
        gates.g6_ciclo_mudo(eventos, ses["ciclo"]),
    ]


# ------------------------------------------------------------ M4: el mudo

def mut_ciclo_mudo(ses):
    """M4 (ESPEC 15.5, cuarta mutacion): al ciclo se le quitan los eventos
    `origen='medido'`. G6 tiene que abortar.

    POR QUE VA AQUI Y NO EN `/tx mutar`: el mutador enviado trae 3 mutaciones
    y esta no. El hueco se reporta en RESULTADOS.md en vez de taparse
    midiendolo por fuera y contandolo como si `/tx mutar` lo hiciera.
    """
    eventos = ses["libro"].leer()
    ciclo = ses["ciclo"]
    mut = [e for e in eventos
           if not (int(e.get("ciclo", -1)) == int(ciclo)
                   and e.get("origen") == "medido")]
    sano = gates.g6_ciclo_mudo(eventos, ciclo)
    roto = gates.g6_ciclo_mudo(mut, ciclo)
    return {"nombre": "ciclo mudo", "gate": "G6",
            "que": "quitados los %d eventos medidos del ciclo %d"
                   % (len(eventos) - len(mut), ciclo),
            "sano": sano, "mutado": roto,
            "aborta": (not roto["ok"]),
            "discrimina": bool(sano["ok"]) and (not roto["ok"]),
            "via": "e1.mut_ciclo_mudo (NO esta en /tx mutar)"}


# ------------------------------------------------- M5: la parafrasis fiel

def mut_parafrasis(ses):
    """M5: una restriccion se reescribe con OTRAS PALABRAS y el MISMO sentido.

    POR QUE ESTA MUTACION Y NO SOLO EL BORRADO: contra un borrado, cualquier
    gate que cuente filas acierta. El modo de fallo REAL de este sistema no es
    que la restriccion desaparezca, es que el resumidor la reescriba "igual
    pero mejor" -- y ahi la cascada de resumenes midio recall 0,083 sin que
    nadie emitiera un error. G1 compara BYTES, asi que tiene que abortar
    tambien aqui; si tolerase la parafrasis, el gate no protegeria de nada de
    lo que de verdad pasa.
    """
    eventos = ses["libro"].leer()
    victima = None
    mut = []
    for e in eventos:
        if victima is None and e.get("banda") == "P" and e.get("t") == "restriccion":
            victima = e
            texto = str(e.get("texto") or "")
            # Mismo sentido, otros bytes. Es lo que escribiria un resumidor.
            reescrito = (texto.replace("no tocar el fichero", "queda prohibido modificar")
                             .replace("bajo ningun concepto", "en ningun caso"))
            if reescrito == texto:
                reescrito = texto + " (idem)"
            mut.append(dict(e, texto=reescrito))
            continue
        mut.append(e)
    if victima is None:
        return {"nombre": "parafrasis fiel", "gate": "G1",
                "que": "la tarea no tiene restricciones: no aplica",
                "sano": gates.veredicto("G1", False, "sin restricciones"),
                "mutado": gates.veredicto("G1", False, "sin restricciones"),
                "aborta": False, "discrimina": False, "via": "e1.mut_parafrasis"}
    sano = gates.g1_banda_permanente(eventos, ses["sha_p0"])
    roto = gates.g1_banda_permanente(mut, ses["sha_p0"])
    return {"nombre": "parafrasis fiel", "gate": "G1p",
            "que": "%s reescrito con el mismo sentido" % victima.get("id"),
            "sano": sano, "mutado": roto,
            "aborta": (not roto["ok"]),
            "discrimina": bool(sano["ok"]) and (not roto["ok"]),
            "via": "e1.mut_parafrasis (NO esta en /tx mutar)"}


# ---------------------------------------------------------------- corrida

def corrida():
    tmp = os.path.join(os.environ.get("TEMP") or "/tmp", "e1_ws_%d" % os.getpid())
    os.makedirs(tmp, exist_ok=True)
    filas = []
    tareas = []
    try:
        for i in range(N_TAREAS):
            ses = sembrar(i, tmp)
            tareas.append(ses["task_id"])
            sanos = controles_sanos(ses)
            t0 = time.perf_counter()
            drill = driver.mutar()          # LA RUTA ENVIADA: /tx mutar
            ms = (time.perf_counter() - t0) * 1000.0
            pruebas = list(drill["pruebas"])
            for p in pruebas:
                p["via"] = "driver.mutar (/tx mutar)"
            pruebas.append(mut_ciclo_mudo(ses))
            pruebas.append(mut_parafrasis(ses))
            filas.append({
                "tarea": i,
                "forma": _forma(i),
                "task_id": ses["task_id"],
                "ms_mutar": round(ms, 1),
                "sanos": [{"gate": v["gate"], "ok": v["ok"],
                           "detalle": v["detalle"]} for v in sanos],
                "mutaciones": [{"gate": p["gate"], "nombre": p["nombre"],
                                "que": p["que"], "via": p["via"],
                                "sano_ok": bool(p["sano"]["ok"]),
                                "mutado_ok": bool(p["mutado"]["ok"]),
                                "aborta": bool(p["aborta"]),
                                "discrimina": bool(p["discrimina"]),
                                "detalle_mutado": p["mutado"]["detalle"]}
                               for p in pruebas],
            })
            driver.cerrar()
    finally:
        try:
            driver.cerrar()
        except Exception as exc:
            print("[e1] no pude cerrar la sesion: %r" % exc, file=sys.stderr)
        shutil.rmtree(tmp, ignore_errors=True)
        for tid in tareas:
            shutil.rmtree(almacen.dir_tarea(tid), ignore_errors=True)
    return filas


def resumir(filas):
    por_gate = {}
    sanos_total = sanos_fp = 0
    for f in filas:
        for s in f["sanos"]:
            sanos_total += 1
            if not s["ok"]:
                sanos_fp += 1
        for m in f["mutaciones"]:
            d = por_gate.setdefault(m["gate"], {"gate": m["gate"],
                                                "nombre": m["nombre"],
                                                "via": m["via"], "n": 0,
                                                "detecta": 0, "discrimina": 0,
                                                "sano_falla": 0})
            d["n"] += 1
            d["detecta"] += 1 if m["aborta"] else 0
            d["discrimina"] += 1 if m["discrimina"] else 0
            d["sano_falla"] += 0 if m["sano_ok"] else 1
    orden = sorted(por_gate.values(), key=lambda d: d["gate"])
    n_mut = sum(d["n"] for d in orden)
    det = sum(d["detecta"] for d in orden)
    dis = sum(d["discrimina"] for d in orden)
    return {
        "n_tareas": len(filas),
        "por_gate": orden,
        "mutaciones": n_mut,
        "deteccion": (det / float(n_mut)) if n_mut else None,
        "discriminacion": (dis / float(n_mut)) if n_mut else None,
        "controles_sanos": sanos_total,
        "falsos_positivos": sanos_fp,
        "tasa_fp": (sanos_fp / float(sanos_total)) if sanos_total else None,
        "ms_mutar_medio": (round(sum(f["ms_mutar"] for f in filas)
                                 / float(len(filas)), 1) if filas else None),
    }


def main():
    t0 = time.time()
    filas = corrida()
    res = resumir(filas)
    salida = {"experimento": "E1", "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
              "segundos": round(time.time() - t0, 1),
              "resumen": res, "filas": filas}
    ruta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "e1_out.json")
    with open(ruta, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(salida, fh, ensure_ascii=True, indent=1)

    print("E1 -- mutacion del gate. n=%d tareas, %d mutaciones, %d controles sanos"
          % (res["n_tareas"], res["mutaciones"], res["controles_sanos"]))
    print("")
    print("%-4s %-28s %-28s %5s %10s %12s" %
          ("gate", "mutacion", "via", "n", "deteccion", "discrimina"))
    for d in res["por_gate"]:
        print("%-4s %-28s %-28s %5d %10.3f %12.3f" %
              (d["gate"], d["nombre"][:28], d["via"][:28], d["n"],
               d["detecta"] / float(d["n"]), d["discrimina"] / float(d["n"])))
    print("")
    print("TASA DE DETECCION GLOBAL : %.3f  (liston pre-registrado 1,000)"
          % res["deteccion"])
    print("DISCRIMINACION           : %.3f" % res["discriminacion"])
    print("FALSOS POSITIVOS         : %d/%d = %.3f"
          % (res["falsos_positivos"], res["controles_sanos"], res["tasa_fp"]))
    print("coste de /tx mutar       : %.1f ms de media" % res["ms_mutar_medio"])
    veredicto = "PASA" if (res["deteccion"] == 1.0 and res["tasa_fp"] == 0.0) else "FALLA"
    print("")
    print("VEREDICTO E1: %s" % veredicto)
    if res["falsos_positivos"]:
        for f in filas:
            for s in f["sanos"]:
                if not s["ok"]:
                    print("  FP tarea %d %s: %s" % (f["tarea"], s["gate"], s["detalle"]))
    print("(detalle completo en %s)" % ruta)
    return 0 if veredicto == "PASA" else 1


if __name__ == "__main__":
    sys.exit(main())
