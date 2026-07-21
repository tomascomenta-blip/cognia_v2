# -*- coding: utf-8 -*-
"""
E2E de razonamiento profundo (/pensar) — goal 2026-07-21.

Muchas preguntas LARGAS y complejas con POSTCONDICION verificable (el numero o
elemento exacto que debe aparecer en la RESPUESTA final, no en el pensamiento).
Corre contra el razonador real (GPU: Qwen3-4B-Thinking; CPU: Qwen3-1.7B).

    PYTHONUTF8=1 PYTHONPATH=. venv312/Scripts/python.exe scripts/e2e_razonamiento.py
    ... --cpu           (fuerza el perfil CPU, subset acotado: es mas lento)
    ... --solo N        (solo la pregunta N, para depurar)

Familias: aritmetica multi-paso, logica, edades, combinatoria, probabilidad,
ritmo/trabajo, temporal, geometria, contexto largo con distractores,
planificacion con restricciones. El check es un regex sobre la respuesta.
"""
import argparse
import os
import re
import sys
import time

# ── preguntas: (nombre, pregunta, regex_que_debe_aparecer) ────────────────
LARGO_CONTEXTO = (
    "Una empresa tiene tres almacenes. El almacen Norte tiene 1240 cajas y "
    "recibe 85 cajas por dia. El almacen Sur tiene 2100 cajas y DESPACHA 35 "
    "cajas por dia. El almacen Este tiene 640 cajas y recibe 120 cajas por "
    "dia. Ademas, la oficina central (que no almacena nada) procesa 500 "
    "ordenes diarias, el gerente se llama Rodrigo, y los camiones son azules. "
    "Cada 7 dias, el almacen Norte transfiere 100 cajas al Sur (cuenta como "
    "salida de Norte y entrada de Sur ese dia). ¿Cuantas cajas tiene CADA "
    "almacen al final del dia 14? Razona paso a paso y da los tres numeros."
)
# Norte: 1240 + 85*14 - 200 = 2230 ; Sur: 2100 - 35*14 + 200 = 1810 ; Este: 640+120*14 = 2320

PREGUNTAS = [
    ("trenes", "Un tren sale de A hacia B a las 9:00 a 80 km/h. Otro sale de "
     "B hacia A a las 9:30 a 100 km/h. La distancia A-B es 490 km. ¿A que "
     "hora exacta se cruzan? Razona paso a paso.", r"12[:.]?00|las 12|mediod"),
    ("gatos", "Si 3 gatos cazan 3 ratones en 3 minutos, ¿cuantos gatos hacen "
     "falta para cazar 100 ratones en 100 minutos? Razona con cuidado.", r"\b3\b"),
    ("edades", "Hoy la edad de un padre es el triple de la de su hijo. Hace 5 "
     "anos era el cuadruple. ¿Que edad tiene el hijo hoy? Paso a paso.", r"\b15\b"),
    ("interes", "Deposito 10000 al 10% de interes compuesto anual. ¿Cuanto "
     "tengo tras 3 anos? Da el numero exacto.", r"13[.,\s]?310"),
    ("combinatoria", "¿De cuantas formas puedo ordenar las letras de la "
     "palabra CASA (contando que las dos A son identicas)? Explica.", r"\b12\b"),
    ("probabilidad", "Lanzo dos dados justos. ¿Cual es la probabilidad de que "
     "la suma sea 8? Da la fraccion exacta.",
     # acepta 5/36 plano o \frac{5}{36} en LaTeX (el thinking emite LaTeX)
     r"5\s*/\s*36|frac\{5\}\{36\}"),
    ("grifos", "Un grifo llena un tanque en 6 horas y otro en 3 horas. El "
     "desague lo vacia en 4 horas. Con los tres abiertos a la vez y el tanque "
     "vacio, ¿en cuantas horas se llena? Fraccion o decimal exacto.", r"\b4\b"),
    ("geometria", "Un rectangulo tiene perimetro 46 y area 120. ¿Cuales son "
     "sus lados? Paso a paso.", r"\b8\b.*\b15\b|\b15\b.*\b8\b"),
    ("logica", "Ana, Beto y Carla: uno siempre miente, uno siempre dice la "
     "verdad, uno alterna. Ana dice 'Beto miente siempre'. Beto dice 'Carla "
     "alterna'. Carla dice 'Ana dice la verdad siempre'. Si Ana es la que "
     "alterna y su frase de ahora es falsa, ¿quien dice siempre la verdad? "
     "Analiza los casos.", r"[Bb]eto"),
    ("serie", "¿Que numero sigue en la serie 2, 6, 12, 20, 30, 42...? "
     "Explica el patron.", r"\b56\b"),
    ("largo_contexto", LARGO_CONTEXTO, r"2[.,\s]?230.*1[.,\s]?810.*2[.,\s]?320"),
    ("mcm", "Tres semaforos parpadean cada 12, 18 y 30 segundos. Si parpadean "
     "juntos ahora, ¿en cuantos segundos vuelven a parpadear juntos? Paso a "
     "paso.", r"\b180\b"),
]

# En CPU (1.7B, mas lento y mas chico) correr un subset representativo.
SUBSET_CPU = ["trenes", "gatos", "edades", "probabilidad", "mcm"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cpu", action="store_true", help="forzar perfil CPU")
    ap.add_argument("--solo", default="", help="correr solo esta pregunta")
    args = ap.parse_args()

    if args.cpu:
        os.environ["LLAMA_N_GPU_LAYERS"] = "0"
        os.environ["LLAMA_CTX_SIZE"] = "8192"
        import cognia.razonador as rz
        rz._PUERTO = 8094      # no adoptar el server GPU
    from cognia.razonador import razonar, gguf_razonador, _es_gpu

    preguntas = PREGUNTAS
    if args.solo:
        preguntas = [p for p in PREGUNTAS if p[0] == args.solo]
    elif args.cpu:
        preguntas = [p for p in PREGUNTAS if p[0] in SUBSET_CPU]

    gguf = gguf_razonador()          # aplica config.env ANTES de leer el perfil
    modo = "GPU" if _es_gpu() else "CPU"
    print(f"== E2E razonamiento [{modo}] modelo={gguf.name} "
          f"({len(preguntas)} preguntas) ==")
    ok = 0
    fallos = []
    t_ini = time.time()
    for nombre, pregunta, patron in preguntas:
        t0 = time.time()
        out = razonar(pregunta, print_fn=None,
                      max_tokens=(20000 if modo == "GPU" else 5000))
        dt = time.time() - t0
        if out is None:
            print(f"  [FAIL] {nombre} ({dt:.0f}s) — backend devolvio None")
            fallos.append(nombre)
            continue
        resp = out["respuesta"]
        paso = re.search(patron, resp, re.S) is not None
        marca = "OK " if paso else "FAIL"
        print(f"  [{marca}] {nombre:16} {dt:5.0f}s  {out['tokens']:>6} toks  "
              f"{out['rounds']} ronda(s)  stop={out['stop_reason']}")
        if paso:
            ok += 1
        else:
            fallos.append(nombre)
            print(f"         esperaba /{patron}/ ; respuesta (cola): "
                  f"...{resp[-220:]!r}")
    total = len(preguntas)
    print(f"\nE2E RAZONAMIENTO [{modo}]: {ok}/{total} OK "
          f"en {(time.time()-t_ini)/60:.1f} min")
    if fallos:
        print("FALLARON:", fallos)
    return 0 if ok == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
