# -*- coding: utf-8 -*-
"""BANCO de aceptacion: 24 pares (accion especulada, accion real) REALES.

Corre las dos acciones de verdad con run_tool de cognia.agent.tools sobre un
fixture controlado y sobre directorios reales del repo, y mide:
  - aceptacion por IGUALDAD (politica estricta)  <- linea base de la literatura
  - aceptacion por EQUIVALENCIA (condicionada)   <- lo que aporta el modulo
  - aceptacion permisiva (tabla a ciegas)        <- techo, y sus FALSOS
  - la VERDAD de cada par: contenido normalizado igual o no (ejecutando ambas)
"""
import os, sys, time, json

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

from cognia.agent.tools import run_tool
from cognia.multiverso import especulacion as E

import tempfile
SCR = os.path.join(tempfile.gettempdir(), "banco_especulacion")
os.makedirs(SCR, exist_ok=True)
FIX = os.path.join(SCR, "fixture")
FIX_OCULTO = os.path.join(SCR, "fixture_oculto")

def preparar():
    for d in (FIX, FIX_OCULTO):
        os.makedirs(d, exist_ok=True)
    for i, n in enumerate(["alfa.py", "beta.py", "gamma.txt", "delta.md"]):
        with open(os.path.join(FIX, n), "w", encoding="utf-8") as f:
            f.write("linea uno %d\nCLAVE_UNICA_%d aqui\nfinal\n" % (i, i))
    os.makedirs(os.path.join(FIX, "sub"), exist_ok=True)
    with open(os.path.join(FIX, "sub", "hondo.py"), "w", encoding="utf-8") as f:
        f.write("nada\nCLAVE_UNICA_9 hondo\n")
    # el mismo fixture pero CON un dotfile: aqui `ls` y `listar` divergen
    for n in ["uno.py", "dos.py"]:
        with open(os.path.join(FIX_OCULTO, n), "w", encoding="utf-8") as f:
            f.write("x\n")
    with open(os.path.join(FIX_OCULTO, ".secreto"), "w", encoding="utf-8") as f:
        f.write("oculto\n")

def q(p):
    return '"%s"' % p if " " in p else p

def pares():
    F, O = q(FIX), q(FIX_OCULTO)
    UN = os.path.join(FIX, "alfa.py")
    return [
        # ---- LISTAR (9) ----
        ("L1", ("listar", FIX), ("listar", FIX)),                       # igualdad
        ("L2", ("listar", FIX), ("ejecutar", "ls %s" % F)),
        ("L3", ("listar", FIX), ("ejecutar", "dir %s" % F)),
        ("L4", ("listar", FIX), ("ejecutar", "find %s -maxdepth 1" % F)),
        ("L5", ("listar", FIX), ("ejecutar",
                'python -c "import os; print(os.listdir(\'%s\'))"'
                % FIX.replace("\\", "/"))),
        ("L6", ("ejecutar", "ls %s" % F), ("listar", FIX)),             # inversa
        ("L7", ("listar", FIX_OCULTO), ("ejecutar", "ls %s" % O)),      # TRAMPA: dotfile
        ("L8", ("listar", FIX), ("listar", SCR)),                       # TRAMPA: otro dir
        ("L9", ("listar", FIX), ("ejecutar", "ls %s" % q(SCR))),        # TRAMPA: ls de otro dir
        # ---- LEER (7) ----
        ("R1", ("leer_archivo", UN), ("leer_archivo", UN)),             # igualdad
        ("R2", ("leer_archivo", UN), ("ejecutar", "cat %s" % q(UN))),
        ("R3", ("leer_archivo", UN), ("ejecutar", "type %s" % q(UN))),
        ("R4", ("ejecutar", "cat %s" % q(UN)), ("leer_archivo", UN)),   # inversa
        ("R5", ("leer_archivo", os.path.join(RAIZ, "MANIFEST.in")),
               ("ejecutar", "cat %s" % q(os.path.join(RAIZ, "MANIFEST.in")))),
        ("R6", ("leer_archivo", UN),
               ("ejecutar", "cat %s" % q(os.path.join(FIX, "beta.py")))),  # TRAMPA
        ("R7", ("leer_archivo", UN), ("leer_archivo", UN + " offset=2")),  # TRAMPA parcial
        # ---- BUSCAR (8) ----
        ("B1", ("buscar", "CLAVE_UNICA | %s" % FIX), ("buscar", "CLAVE_UNICA | %s" % FIX)),
        ("B2", ("buscar", "CLAVE_UNICA | %s" % FIX), ("ejecutar", "rg CLAVE_UNICA %s" % F)),
        ("B3", ("buscar", "CLAVE_UNICA | %s" % FIX), ("ejecutar", "grep -r CLAVE_UNICA %s" % F)),
        ("B4", ("ejecutar", "rg CLAVE_UNICA %s" % F), ("buscar", "CLAVE_UNICA | %s" % FIX)),
        ("B5", ("buscar", "CLAVE_UNICA | %s" % FIX), ("ejecutar", "findstr /s CLAVE_UNICA %s" % F)),
        ("B6", ("buscar", "CLAVE_UNICA | %s" % FIX), ("buscar", "CLAVE_UNICA | %s" % FIX_OCULTO)),  # TRAMPA
        ("B7", ("buscar", "CLAVE_UNICA | %s" % FIX), ("ejecutar", "rg OTRA_COSA %s" % F)),  # TRAMPA
        ("B8", ("buscar", "def | %s" % q(os.path.join(RAIZ, "cognia", "multiverso"))),
               ("ejecutar", "rg def %s" % q(os.path.join(RAIZ, "cognia", "multiverso")))),
    ]


def main():
    preparar()
    ctx = {}
    verificar = lambda tool, args: run_tool(tool, args, ctx)
    filas = []
    for pid, esp, real in pares():
        E.reiniciar()
        cache = E.ejecutar_especulativo([esp], run_tool, ctx, esperar=True)
        ent = list(cache["entradas"].values())
        ms_esp = ent[0]["ms"] if ent else 0.0
        res = {}
        for pol in ("estricta", "condicionada", "permisiva"):
            r = E.aceptar(real, cache, politica=pol)
            res[pol] = (r["aceptada"], r["via"], r["evidencia"].get("motivo", ""))
        # VERDAD: correr la real y comparar contenido normalizado
        t0 = time.perf_counter()
        texto_real = run_tool(real[0], real[1], ctx)
        ms_real = (time.perf_counter() - t0) * 1000.0
        ef = E.efecto_observable(real, RAIZ)
        verdad = None
        if ef["efecto"] is not None and ent:
            fam = ef["familia"]
            a = E.normalizar_contenido(fam, ent[0]["resultado"], ef["efecto"])
            b = E.normalizar_contenido(fam, texto_real, ef["efecto"])
            verdad = E.contenidos_iguales(fam, a, b)
        else:
            # sin efecto canonico: verdad por comparacion cruda de texto
            verdad = (ent[0]["resultado"] == texto_real) if ent else False
        filas.append({"id": pid, "esp": "%s %s" % esp, "real": "%s %s" % real,
                      "verdad": verdad, "ms_esp": ms_esp, "ms_real": ms_real,
                      **{p: res[p] for p in res}})

    # ---------------- tabla ----------------
    print("=" * 118)
    print("BANCO DE ACEPTACION -- %d pares, ejecucion REAL (run_tool de cognia.agent.tools)" % len(filas))
    print("=" * 118)
    print("%-4s %-11s %-11s %-11s %-7s %9s %9s" %
          ("id", "estricta", "condicion.", "permisiva", "VERDAD", "ms_esp", "ms_real"))
    print("-" * 118)
    for f in filas:
        def c(p):
            ok, via, _ = f[p]
            return "OK/%s" % via if ok else "no"
        print("%-4s %-11s %-11s %-11s %-7s %9.2f %9.2f" %
              (f["id"], c("estricta"), c("condicionada"), c("permisiva"),
               "IGUAL" if f["verdad"] else "DISTINTO", f["ms_esp"], f["ms_real"]))
    print("-" * 118)
    n = len(filas)
    for pol in ("estricta", "condicionada", "permisiva"):
        acc = [f for f in filas if f[pol][0]]
        ig = [f for f in acc if f[pol][1] == "igualdad"]
        eq = [f for f in acc if f[pol][1] == "equivalencia"]
        falsos = [f["id"] for f in acc if not f["verdad"]]
        perdidos = [f["id"] for f in filas if f["verdad"] and not f[pol][0]]
        print("%-13s aceptadas %2d/%d (%5.1f%%)  igualdad %2d  equivalencia %2d"
              "  FALSOS ACEPTADOS %d %s  equivalentes PERDIDOS %d %s"
              % (pol, len(acc), n, 100.0 * len(acc) / n, len(ig), len(eq),
                 len(falsos), falsos or "", len(perdidos), perdidos or ""))
    print("-" * 118)
    verdaderos = [f for f in filas if f["verdad"]]
    print("pares realmente equivalentes en el banco: %d/%d" % (len(verdaderos), n))
    # proxy de coste: ms_esp vs ms_real en los aceptados por equivalencia
    eqs = [f for f in filas if f["condicionada"][0] and f["condicionada"][1] == "equivalencia"]
    if eqs:
        err = [abs(f["ms_esp"] - f["ms_real"]) / max(f["ms_real"], 1e-6) for f in eqs]
        print("error del proxy de ahorro (via equivalencia, n=%d): mediana %.1f%%, max %.1f%%"
              % (len(eqs), 100 * sorted(err)[len(err) // 2], 100 * max(err)))
        print("ms REALES de la accion real evitada, suma = %.1f ms; ms especulados = %.1f ms"
              % (sum(f["ms_real"] for f in eqs), sum(f["ms_esp"] for f in eqs)))

    # ---- estadisticas() acumuladas de una corrida completa condicionada ----
    E.reiniciar()
    ctx2 = {}
    for pid, esp, real in pares():
        cache = E.ejecutar_especulativo([esp], run_tool, ctx2, esperar=True)
        E.aceptar(real, cache, politica="condicionada")
    print("-" * 118)
    print("estadisticas() tras la corrida condicionada completa:")
    st = E.estadisticas()
    for k in ("especuladas", "intentos", "aceptadas", "aceptadas_igualdad",
              "aceptadas_equivalencia", "rechazadas", "tasa_aceptacion",
              "tasa_solo_igualdad", "ganancia_equivalencia", "ms_especulados",
              "ms_ahorrados", "ms_desperdiciados", "clasificador"):
        print("   %-24s %s" % (k, st[k]))
    print("   por_familia              %s" % json.dumps(st["por_familia"]))
    print("=" * 118)


if __name__ == "__main__":
    main()
