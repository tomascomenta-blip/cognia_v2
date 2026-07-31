# -*- coding: utf-8 -*-
"""
b3_humo_contraejemplo.py — control positivo del CONTRAEJEMPLO.

Sin esto, un arnés que devolviera siempre `obtenido=""` daría un brazo de
reparación que en realidad no ve nada, y el KILL sería del INSTRUMENTO, no de
la idea — el modo de fallo que ya mató el descubridor metamórfico. Aquí se
comprueba que la salida obtenida llega de verdad, en los tres casos que
importan: salida distinta, excepción, y código correcto (sin contraejemplo).
"""
from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts"))

from b3_codigo import _ejecuta_lote
from b3_reparacion import contraejemplo

fallos = []


def check(nombre, cond, detalle=""):
    print(f"[{'OK ' if cond else 'FALLA'}] {nombre}  {detalle}")
    if not cond:
        fallos.append(nombre)


# --- 1. stdin: la salida obtenida difiere de la esperada -----------------
casos = [{"input": "2 3\n", "output": "5\n"},
         {"input": "10 20\n", "output": "30\n"}]
malo = "a,b = map(int, input().split())\nprint(a*b)"
det = {}
res, motivo = _ejecuta_lote(malo, casos, "stdin", timeout=30, detalle=det)
check("stdin: ambos casos fallan", res == [False, False], f"res={res}")
check("stdin: motivo limpio", motivo == "", f"motivo={motivo!r}")
check("stdin: obtenido del caso 0 es '6'",
      (det.get(0) or {}).get("obtenido") == "6", f"det0={det.get(0)}")
check("stdin: obtenido del caso 1 es '200'",
      (det.get(1) or {}).get("obtenido") == "200", f"det1={det.get(1)}")

ce = contraejemplo({}, casos, res, det)
check("contraejemplo: coge el PRIMER fallo", ce.get("i") == 0, f"i={ce.get('i')}")
check("contraejemplo: lleva entrada/esperada/obtenida",
      ce.get("entrada") == "2 3\n" and ce.get("esperada") == "5\n"
      and ce.get("obtenida") == "6", str(ce)[:160])

# --- 2. el código revienta: el contraejemplo degrada a EXCEPCIÓN ---------
revienta = "raise ValueError('boom')"
det2 = {}
res2, _ = _ejecuta_lote(revienta, casos, "stdin", timeout=30, detalle=det2)
check("excepción: falla", res2 == [False, False], f"res={res2}")
check("excepción: se captura tipo+mensaje",
      "ValueError" in (det2.get(0) or {}).get("excepcion", ""),
      f"det0={det2.get(0)}")
check("excepción: NO se cuela una traza de pila",
      "Traceback" not in (det2.get(0) or {}).get("excepcion", ""))

# --- 3. código correcto: NO hay contraejemplo ---------------------------
bueno = "a,b = map(int, input().split())\nprint(a+b)"
det3 = {}
res3, _ = _ejecuta_lote(bueno, casos, "stdin", timeout=30, detalle=det3)
check("correcto: pasa los dos", res3 == [True, True], f"res={res3}")
check("correcto: sin detalle", det3 == {}, f"det={det3}")
check("correcto: contraejemplo vacío",
      contraejemplo({}, casos, res3, det3) == {})

# --- 4. functional: el valor devuelto -----------------------------------
casosf = [{"input": "[1, 2, 3]", "output": "6", "testtype": "functional"}]
malof = "class Solution:\n    def suma(self, xs):\n        return len(xs)"
det4 = {}
res4, _ = _ejecuta_lote(malof, casosf, "functional", func_name="suma",
                        timeout=30, detalle=det4)
check("functional: falla", res4 == [False], f"res={res4}")
check("functional: obtenido es el valor devuelto (3)",
      (det4.get(0) or {}).get("obtenido") == "3", f"det0={det4.get(0)}")

# --- 5. SIN el flag, el arnés se comporta EXACTAMENTE como antes ---------
res5, motivo5 = _ejecuta_lote(malo, casos, "stdin", timeout=30)
check("sin flag: mismos resultados", res5 == [False, False], f"res={res5}")
check("sin flag: mismo motivo", motivo5 == "", f"motivo={motivo5!r}")

# --- 6. un fallo SIN detalle no produce un contraejemplo inventado -------
check("sin detalle: contraejemplo vacío (no se inventa '(no output)')",
      contraejemplo({}, casos, [False, False], {}) == {})

# --- 7. RECORTE: el control positivo original no lo cazaba porque todos sus
# casos eran de 4 caracteres. La revisión adversarial midió que con la política
# vieja el 24.4% de los contraejemplos llegaba con la entrada truncada Y SIN
# MARCA, y 6 de 41 con el patrón patológico (entrada cortada + salida esperada
# completa). Esto lo fija en el instrumento.
from b3_reparacion import TOPE_CAMPO, prompt_reparar

largo = "9 " * 4000                       # ~8000 chars, muy por encima del tope
casos_l = [{"input": largo, "output": "0\n"},
           {"input": "1 2\n", "output": "3\n"}]
malo_l = "import sys\nsys.stdin.read()\nprint(-1)"
det7 = {}
res7, _ = _ejecuta_lote(malo_l, casos_l, "stdin", timeout=30, detalle=det7)
ce7 = contraejemplo({}, casos_l, res7, det7)
check("recorte: elige el caso de entrada MAS CORTA, no el primero",
      ce7.get("i") == 1, f"i={ce7.get('i')} (0 = el largo, 1 = el corto)")
check("recorte: el corto NO va marcado como recortado",
      ce7.get("recortado") is False, f"recortado={ce7.get('recortado')}")

# y si el UNICO fallo es el largo, tiene que ir MARCADO en el prompt
det8 = {}
res8, _ = _ejecuta_lote(malo_l, casos_l[:1], "stdin", timeout=30, detalle=det8)
ce8 = contraejemplo({}, casos_l[:1], res8, det8)
check("recorte: cuando no hay alternativa, marca recortado=True",
      ce8.get("recortado") is True, f"recortado={ce8.get('recortado')}")
check("recorte: guarda la longitud REAL de la entrada",
      ce8.get("entrada_len") == len(largo),
      f"entrada_len={ce8.get('entrada_len')} vs real {len(largo)}")
check("recorte: la entrada guardada esta capada al tope",
      len(ce8.get("entrada", "")) == TOPE_CAMPO,
      f"len={len(ce8.get('entrada',''))}")
p8 = prompt_reparar({"enunciado": "x", "starter_code": ""}, "codigo", ce8)
check("recorte: la MARCA aparece en el prompt que ve el modelo",
      "ENTRADA RECORTADA" in p8 and str(len(largo)) in p8,
      f"...{p8[p8.find('Input:'):p8.find('Input:')+90]}...")

print()
if fallos:
    print(f"CONTROL DEL CONTRAEJEMPLO: FALLA ({len(fallos)}): {fallos}")
    sys.exit(1)
print("CONTROL POSITIVO DEL CONTRAEJEMPLO: PASA")
