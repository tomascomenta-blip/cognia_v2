# -*- coding: utf-8 -*-
"""Cierres del A/B: latencia por POSICION (para comprobar que el intercalado
neutralizo el prefill frio), netos apareados y test de signos exacto."""
import json
import os
import statistics

AQUI = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(AQUI, "crudo.json"), encoding="utf-8") as fh:
    filas = json.load(fh)

print("--- latencia (ms) por brazo y POSICION dentro de la tarea ---")
for brazo in ("v1", "v2"):
    for pos in range(4):
        lat = [f["ms"] for f in filas if f["brazo"] == brazo and f["posicion"] == pos]
        if lat:
            print("{} pos{}  n={}  mediana={}  {}".format(
                brazo, pos, len(lat), int(statistics.median(lat)), sorted(lat)))

print("\n--- primera llamada de cada tarea (la que come prefill frio) ---")
for brazo in ("v1", "v2"):
    lat = [f["ms"] for f in filas if f["posicion"] == 0 and f["brazo"] == brazo]
    print("{}: n={} mediana={}".format(brazo, len(lat), int(statistics.median(lat))))

print("\n--- aceptacion apareada por tarea (replica 1 = la que va a pares.json) ---")
tareas = []
for f in filas:
    if f["tarea"] not in tareas:
        tareas.append(f["tarea"])
disc_v2, disc_v1 = 0, 0
for t in tareas:
    a = [f for f in filas if f["tarea"] == t and f["brazo"] == "v1" and f["replica"] == 1][0]
    b = [f for f in filas if f["tarea"] == t and f["brazo"] == "v2" and f["replica"] == 1][0]
    if a["ok"] and not b["ok"]:
        disc_v1 += 1
    if b["ok"] and not a["ok"]:
        disc_v2 += 1
    print("{:>11}  v1={:5}  v2={:5}".format(t, str(a["ok"]), str(b["ok"])))
print("discordantes: v2 gana {}, v1 gana {}".format(disc_v2, disc_v1))
n = disc_v1 + disc_v2
if n:
    print("test de signos exacto (dos colas) p = {:.2e}".format(2 * (0.5 ** n)))

print("\n--- las 2 llamadas de v1 que SI pasaron el guardia ---")
for f in filas:
    if f["brazo"] == "v1" and f["ok"]:
        print("  {} r{}: '{}' -> '{}'".format(
            f["tarea"], f["replica"], f["original"], f["texto"]))

print("\n--- replicas que NO coinciden dentro del mismo brazo ---")
inestables = 0
for t in tareas:
    for brazo in ("v1", "v2"):
        rr = [f for f in filas if f["tarea"] == t and f["brazo"] == brazo]
        if rr[0]["ok"] != rr[1]["ok"]:
            inestables += 1
            print("  {} {}: r1 ok={} r2 ok={}".format(
                t, brazo, rr[0]["ok"], rr[1]["ok"]))
print("  celdas inestables: {}".format(inestables))

# --- lo que la ronda 2 NO derivo y publico al reves -------------------------
# El "+10" salia de contar las 12 filas, pero en 10 de ellas v1 no produjo
# ninguna reescritura: esas comparan "reescribir" contra "no hacer nada", no un
# estilo contra otro. El cara a cara REAL son las filas donde AMBOS brazos
# escribieron algo, y hay que decir cuantas son antes de leer el marcador.
print("\n--- filas COMPARABLES (ambos brazos produjeron una reescritura) ---")
comparables = []
for t in tareas:
    a = [f for f in filas if f["tarea"] == t and f["brazo"] == "v1"
         and f["replica"] == 1][0]
    b = [f for f in filas if f["tarea"] == t and f["brazo"] == "v2"
         and f["replica"] == 1][0]
    if a["ok"] and b["ok"]:
        comparables.append(t)
        print("  {}:".format(t))
        print("    v1: " + a["texto"])
        print("    v2: " + b["texto"])
print("  n comparable = {} de {} tareas".format(len(comparables), len(tareas)))
print("  las otras {} filas NO comparan estilos: son 'v2 entrega y v1 no'"
      .format(len(tareas) - len(comparables)))

# --- por celda, con LAS DOS replicas ----------------------------------------
# La ronda 2 juzgo solo la replica 1 y no reporto la 2, que en las celdas
# decisivas dice lo contrario.
print("\n--- todas las celdas, r1 y r2 (la r2 nunca se reporto) ---")
for t in tareas:
    for brazo in ("v1", "v2"):
        rr = sorted([f for f in filas if f["tarea"] == t and f["brazo"] == brazo],
                    key=lambda x: x["replica"])
        print("  {:>11} {}: r1 ok={:5} {:4}c | r2 ok={:5} {:4}c".format(
            t, brazo, str(rr[0]["ok"]), rr[0]["chars"],
            str(rr[1]["ok"]), rr[1]["chars"]))
