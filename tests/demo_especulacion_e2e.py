# -*- coding: utf-8 -*-
"""Verificacion REAL fuera de pytest: el lazo completo sobre el repo de verdad.

Traza real -> predecir (bigrama) -> especular en un hilo MIENTRAS 'el modelo
piensa' -> el modelo pide el EQUIVALENTE por comando -> aceptar.
Mide la pared con y sin especulacion.
"""
import os, sys, time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ); os.chdir(RAIZ)
from cognia.agent.tools import run_tool
from cognia.multiverso import especulacion as E

E.reiniciar()
D = os.path.join(RAIZ, "cognia", "multiverso")

# traza REAL de un agente: tras 'listar' pidio 'leer_archivo' 2 de 3 veces
traza = [
    {"tool": "listar", "args": D},
    {"tool": "leer_archivo", "args": os.path.join(D, "__init__.py")},
    {"tool": "buscar", "args": "def | %s" % D},
    {"tool": "listar", "args": D},
    {"tool": "leer_archivo", "args": os.path.join(D, "__init__.py")},
    {"tool": "git_estado", "args": ""},
    {"tool": "listar", "args": D},          # <- paso actual
]
pred = E.predecir({"historial": traza}, k=3)
print("1) PREDICCION (bigrama, sin modelo):")
for p in pred:
    print("   %-14s %-60s prob=%.2f (%d/%d)"
          % (p.tool, p.args[-58:], p.meta["prob"], p.meta["conteo"], p.meta["de"]))
print("   cubo de cada una:", [E.cubo_de(p) for p in pred])

print("\n2) ESPECULACION mientras 'el modelo piensa' 400 ms:")
t0 = time.perf_counter()
cache = E.ejecutar_especulativo(pred, run_tool, {"cwd": RAIZ})
time.sleep(0.40)                                  # el modelo grande pensando
cache["esperar"](5)
pensar_ms = (time.perf_counter() - t0) * 1000
print("   pared del turno de pensar: %.1f ms; especuladas %d; vetadas %d"
      % (pensar_ms, len(cache["entradas"]), len(cache["vetadas"])))
for f, e in cache["entradas"].items():
    print("   cacheada %-70s %.2f ms  efecto=%s" % (f[-68:], e["ms"], e["efecto"][0]))

print("\n3) EL MODELO PIDE OTRA SINTAXIS (cat en vez de leer_archivo):")
real = ("ejecutar", 'cat "%s"' % os.path.join(D, "__init__.py"))
t1 = time.perf_counter()
r = E.aceptar(real, cache)
acept_ms = (time.perf_counter() - t1) * 1000
print("   aceptada=%s via=%s en %.3f ms" % (r["aceptada"], r["via"], acept_ms))
print("   regla especulada=%s -> regla real=%s | riesgo=%s"
      % (r["evidencia"]["regla_especulada"], r["evidencia"]["regla_real"],
         r["evidencia"]["riesgo"]))
print("   condiciones:", r["evidencia"].get("condiciones"))
print("   resultado servido (80 chars): %r" % (r["resultado"] or "")[:80])

print("\n4) CONTRAFACTUAL: lo que habria costado ejecutarla de verdad")
t2 = time.perf_counter()
texto_real = run_tool(*real, {})
real_ms = (time.perf_counter() - t2) * 1000
print("   ejecutar '%s' -> %.1f ms" % (real[1][:40], real_ms))
ef = E.efecto_observable(real, RAIZ)
a = E.normalizar_contenido("LEER", r["resultado"], ef["efecto"])
b = E.normalizar_contenido("LEER", texto_real, ef["efecto"])
print("   el contenido servido es IGUAL al real:", E.contenidos_iguales("LEER", a, b))
print("   latencia ESCONDIDA por la especulacion: %.1f ms -> %.3f ms (%.0fx)"
      % (real_ms, acept_ms, real_ms / max(acept_ms, 1e-9)))

print("\n5) UNA EQUIVALENCIA FALSA (cat de OTRO fichero):")
r2 = E.aceptar(("ejecutar", 'cat "%s"' % os.path.join(D, "especulacion.py")), cache)
print("   aceptada=%s motivo=%s" % (r2["aceptada"], r2["evidencia"]["motivo"][:90]))

print("\n6) UNA ACCION NO PURA JAMAS SE ESPECULA:")
c2 = E.ejecutar_especulativo([("ejecutar", "git push origin main"),
                              ("escribir_archivo", "x.txt | hola")],
                             run_tool, {}, esperar=True)
print("   entradas=%d vetadas=%s" % (len(c2["entradas"]),
                                     [v["accion"]["tool"] for v in c2["vetadas"]]))

print("\n7) estadisticas():")
for k, v in sorted(E.estadisticas().items()):
    print("   %-24s %s" % (k, v))
