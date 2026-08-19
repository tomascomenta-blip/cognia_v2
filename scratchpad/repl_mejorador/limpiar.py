# -*- coding: utf-8 -*-
"""Deja legible el volcado del ConPTY: quita ANSI y colapsa los repintados.

prompt_toolkit repinta la pantalla entera decenas de veces por segundo, asi que
el volcado crudo tiene la misma linea cientos de veces. Aqui solo se pide
LEGIBILIDAD para pegar en el log; el crudo se conserva aparte.
"""
import re
import sys

CRUDO = sys.argv[1]
DESDE = sys.argv[2] if len(sys.argv) > 2 else ""

s = open(CRUDO, encoding="utf-8", errors="replace").read()
s = re.sub(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)", "", s)   # OSC
s = re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", s)              # CSI
s = re.sub(r"\x1b[()][A-Z0-9]", "", s)
s = s.replace("\x1b", "").replace("\x07", "").replace("\x00", "")
s = s.replace("\r\n", "\n").replace("\r", "\n")

if DESDE:
    i = s.find(DESDE)
    if i >= 0:
        s = s[i:]

vistas = []
previa = None
for linea in s.split("\n"):
    linea = linea.rstrip()
    if linea == previa:            # repintado identico consecutivo
        continue
    previa = linea
    vistas.append(linea)

# colapsa rachas de lineas en blanco
out = []
for linea in vistas:
    if not linea.strip() and out and not out[-1].strip():
        continue
    out.append(linea)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
print("\n".join(out))
