# -*- coding: utf-8 -*-
"""
b3_humo_lcb.py — control POSITIVO del arnés de LiveCodeBench.

Sin esto, un arnés roto se lee como "el modelo no sabe": exactamente el modo
de fallo que costó cuatro auto-correcciones el 2026-07-30. Se escriben A MANO
dos soluciones correctas (una `stdin`, una `functional`) y se exige que pasen
TODOS sus casos privados. También se exige que una solución rota falle.
"""
from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts"))

from b3_codigo import carga_lcb, juzga_lcb

# abc387_b "9x9 Sum": de los 81 productos i*j (1<=i,j<=9), sumar los != X.
SOL_STDIN = """
X = int(input())
total = 0
for i in range(1, 10):
    for j in range(1, 10):
        if i * j != X:
            total += i * j
print(total)
"""

# 3708 zigzagTraversal: recorrido en zigzag tomando uno de cada dos.
SOL_FUNC = """
class Solution:
    def zigzagTraversal(self, grid):
        orden = []
        for i, fila in enumerate(grid):
            orden.extend(fila if i % 2 == 0 else fila[::-1])
        return orden[::2]
"""

ROTO = "def nada():\n    return 0\n"

# --- REGRESIÓN de los dos bugs de arnés que cazó la revisión adversarial ---
# Sin el fix, el 10.3% de LCB (módulo) y el 64% (AtCoder stdin rápido)
# puntuaban 0 por INSTRUMENTO, facturado al modelo.
SOL_POW = """
X = int(input())
total = 0
for i in range(1, 10):
    for j in range(1, 10):
        if i * j != X:
            total += i * j
print(total % pow(10, 9, 1000000007) if False else total)
"""

SOL_BUFFER = """
import sys
data = sys.stdin.buffer.read().split()
X = int(data[0])
total = 0
for i in range(1, 10):
    for j in range(1, 10):
        if i * j != X:
            total += i * j
print(total)
"""


def regresion(tareas):
    """pow(a,b,MOD) y sys.stdin.buffer.read() tienen que funcionar."""
    t = tareas.get("abc387_b")
    fallos = 0
    for nombre, sol in (("pow(a,b,MOD)", SOL_POW),
                        ("sys.stdin.buffer", SOL_BUFFER)):
        n, _ = juzga_lcb(sol, t, t["privados"])
        ok = n == len(t["privados"])
        print(f"[{'OK ' if ok else 'FAL'}] regresión {nombre}: "
              f"{n}/{len(t['privados'])}")
        fallos += 0 if ok else 1
    return fallos


def main():
    tareas = {t["task_id"]: t for t in carga_lcb()}
    fallos = 0

    for tid, sol in (("abc387_b", SOL_STDIN), ("3708", SOL_FUNC)):
        t = tareas.get(tid)
        if t is None:
            print(f"[!] tarea {tid} no está en el banco post-corte")
            fallos += 1
            continue
        pub, _ = juzga_lcb(sol, t, t["publicos"])
        priv, _ = juzga_lcb(sol, t, t["privados"])
        mal, _ = juzga_lcb(ROTO, t, t["privados"])
        modo = "functional" if t["starter_code"].strip() else "stdin"
        ok = (pub == len(t["publicos"]) and priv == len(t["privados"])
              and mal == 0)
        print(f"[{'OK ' if ok else 'FAL'}] {tid} ({modo}): "
              f"publicos {pub}/{len(t['publicos'])}  "
              f"privados {priv}/{len(t['privados'])}  "
              f"roto {mal}/{len(t['privados'])}")
        if not ok:
            fallos += 1

    fallos += regresion(tareas)
    print(f"\nCONTROL POSITIVO DEL ARNÉS LCB: "
          f"{'PASA' if fallos == 0 else f'FALLA ({fallos})'}")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
