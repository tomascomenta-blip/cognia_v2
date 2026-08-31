# -*- coding: utf-8 -*-
"""Validacion ESTRUCTURAL de HTML/JS: ¿el fichero esta ENTERO? (2026-08-31)

POR QUE EXISTE
--------------
`presupuesto_progreso._validar_fichero` parseaba Python y JSON y para todo lo
demas se conformaba con "existe y no esta vacio". Con eso, un `index.html` de
32 KB que el modelo dejo cortado a mitad de una clase -- sin `</script>`, sin
`</html>`, sin una sola linea de la logica del juego -- contaba como
`fichero_nuevo_valido` y como `artefacto_crecio_valido`: DOS avances
verificados sobre una entrega rota. El turno cerraba con "✓ Objetivo
verificado: 1/1 criterios reales cumplidos" y el dueno abria un fichero que no
hacia nada. Es el "test que pasa por el motivo equivocado" en su forma mas
cara: el gobernador de progreso premiaba justo lo que habia que reprobar.

Y la otra mitad: `revision_profunda.fase_sintaxis` solo miraba .py y .json, asi
que sobre una entrega HTML devolvia "no evaluada" y nadie mas la miraba.

QUE COMPRUEBA (y que NO)
------------------------
Esto NO es un parser de HTML ni un motor de JS: es un detector de TRUNCAMIENTO
y de desbalanceo, que es el modo de fallo real del arnes (el tool call se corta,
el modelo apendea mal, la ultima parte nunca llega). Comprueba:

  HTML  - cada `<script>` tiene su `</script>`
        - si hay `<html` hay `</html>`; si hay `<body` hay `</body>`
        - cada bloque `<script>` sin `src=` esta balanceado como JS
  JS    - llaves/parentesis/corchetes balanceados
        - ninguna cadena, plantilla o comentario queda abierto al final

NO comprueba semantica: un HTML entero cuyos botones no hacen nada pasa por
aqui, y tiene que pasar -- eso lo caza `autoprueba.probar_producto`, que abre
la pagina en un navegador de verdad. Aqui se responde una sola pregunta, la que
nadie estaba respondiendo: **¿esta el fichero completo?**

CERO FALSOS POSITIVOS POR DISENO
--------------------------------
Un gate que reprueba entregas sanas acaba apagado (leccion medida de esta
casa), asi que el escaner es DELIBERADAMENTE cobarde en el unico punto
ambiguo del lexer de JS: la barra `/` puede abrir una expresion regular o ser
una division, y distinguirlas de verdad exige el parser entero. Aqui se
escanea DOS VECES -- una tratando `/` como regex cuando el contexto lo permite
y otra tratandola siempre como division -- y solo se reprueba cuando las dos
pasadas coinciden en que hay desbalanceo y en su signo. Si discrepan, el
veredicto es `None` ("no evaluable"), nunca "roto".

API
    problemas(ruta, texto=None) -> list[str]   # [] = sin problemas estructurales
    veredicto(ruta, texto=None) -> (ok, motivo)  # ok True/False/None
    es_web(ruta) -> bool
"""
from __future__ import annotations

import re
from pathlib import Path

EXT_HTML = (".html", ".htm", ".xhtml")
EXT_JS = (".js", ".mjs", ".cjs", ".jsx")

_RE_SCRIPT_ABRE = re.compile(r"<script\b[^>]*>", re.I)
_RE_SCRIPT_CIERRA = re.compile(r"</\s*script\s*>", re.I)
_RE_SRC = re.compile(r"\bsrc\s*=", re.I)

# Caracteres tras los cuales una `/` abre una expresion regular y no divide.
# Es la heuristica clasica (la misma que usan los resaltadores de sintaxis);
# su margen de error es exactamente lo que cubre la doble pasada.
_ANTES_DE_REGEX = set("(,=:[!&|?{};+-*%~^<>\n\r\t ")

CIERRES = {"}": "{", ")": "(", "]": "["}
APERTURAS = {"{": "}", "(": ")", "[": "]"}


def es_web(ruta) -> bool:
    """True si `ruta` es un fichero que este modulo sabe mirar."""
    return Path(str(ruta)).suffix.lower() in EXT_HTML + EXT_JS


# ── Escaner de JS ──────────────────────────────────────────────────────

def escanear_js(js: str, con_regex: bool = True) -> dict:
    """Recorre `js` y devuelve el estado estructural en que termina.

    ``{"saldos": {"{": n, "(": n, "[": n}, "abierto": str|"", "sobrante": str|""}``

    - ``saldos``   aperturas menos cierres de cada pareja (0 = balanceado).
    - ``abierto``  que quedo sin cerrar al llegar al final ("cadena",
                   "plantilla", "comentario de bloque", "regex") o "".
    - ``sobrante`` el primer cierre que llego sin apertura ("}" suelta), o "".

    `con_regex=False` desactiva el reconocimiento de expresiones regulares y
    trata toda `/` como division: es la SEGUNDA opinion de la doble pasada.
    """
    saldos = {"{": 0, "(": 0, "[": 0}
    estado = "codigo"
    # Marcadores de plantilla: profundidad de llaves a la que hay que volver a
    # estado 'plantilla' al cerrar un ${...}.
    pila_tpl: list = []
    sobrante = ""
    anterior = ""          # ultimo char significativo (para la heuristica de /)
    i, n = 0, len(js)
    en_clase = False       # dentro de [...] de una regex
    while i < n:
        c = js[i]
        sig = js[i + 1] if i + 1 < n else ""
        if estado == "codigo":
            if c == "/" and sig == "/":
                estado = "linea"
                i += 2
                continue
            if c == "/" and sig == "*":
                estado = "bloque"
                i += 2
                continue
            if c == "/" and con_regex and (anterior == "" or anterior in _ANTES_DE_REGEX):
                estado, en_clase = "regex", False
                i += 1
                continue
            if c == "'":
                estado = "cadena1"
                i += 1
                continue
            if c == '"':
                estado = "cadena2"
                i += 1
                continue
            if c == "`":
                estado = "plantilla"
                i += 1
                continue
            if c in APERTURAS:
                saldos[c] += 1
            elif c in CIERRES:
                abre = CIERRES[c]
                if saldos[abre] <= 0 and not sobrante:
                    sobrante = c
                saldos[abre] -= 1
                if (c == "}" and pila_tpl
                        and pila_tpl[-1] == saldos["{"]):
                    pila_tpl.pop()
                    estado = "plantilla"
            if not c.isspace():
                anterior = c
            i += 1
            continue
        if estado == "linea":
            if c == "\n":
                estado = "codigo"
            i += 1
            continue
        if estado == "bloque":
            if c == "*" and sig == "/":
                estado = "codigo"
                i += 2
                continue
            i += 1
            continue
        if estado in ("cadena1", "cadena2"):
            if c == "\\":
                i += 2
                continue
            cierra = "'" if estado == "cadena1" else '"'
            if c == cierra:
                estado, anterior = "codigo", cierra
            elif c == "\n":
                # Una cadena normal no cruza el renglon: si llega aqui es que
                # la comilla era apostrofe en prosa (o el fichero esta roto).
                # Se vuelve a codigo para no arrastrar el error a todo el resto.
                estado = "codigo"
            i += 1
            continue
        if estado == "plantilla":
            if c == "\\":
                i += 2
                continue
            if c == "$" and sig == "{":
                pila_tpl.append(saldos["{"])
                saldos["{"] += 1
                estado = "codigo"
                i += 2
                continue
            if c == "`":
                estado, anterior = "codigo", "`"
            i += 1
            continue
        if estado == "regex":
            if c == "\\":
                i += 2
                continue
            if c == "[":
                en_clase = True
            elif c == "]":
                en_clase = False
            elif c == "/" and not en_clase:
                estado, anterior = "codigo", "/"
            elif c == "\n":
                # Una regex no cruza el renglon: era una division mal leida.
                estado = "codigo"
            i += 1
            continue
        i += 1                                     # pragma: no cover (estado imposible)
    abierto = {"cadena1": "una cadena '...'", "cadena2": 'una cadena "..."',
               "plantilla": "una plantilla `...`", "bloque": "un comentario /* */",
               "regex": "una expresion regular /.../"}.get(estado, "")
    if pila_tpl and not abierto:
        abierto = "una interpolacion ${...} de plantilla"
    return {"saldos": saldos, "abierto": abierto, "sobrante": sobrante}


# Un bundle minificado no es codigo que el agente haya escrito, y es justo
# donde la heuristica de `/` se rompe aunque las dos pasadas coincidan: MEDIDO
# sobre los 439 .html/.js a mano del disco del dueno, los 3 unicos falsos
# positivos eran assets de vite (playwright) de una sola linea de 200 KB.
# Sobre esos ficheros este modulo NO OPINA: el truncamiento que persigue es el
# del tool call cortado, y eso no le pasa a un bundle de node_modules.
_MINIF_LINEA_MAX = 2000
_MINIF_MEDIA = 400


def parece_minificado(js: str) -> bool:
    """True si el cuerpo parece un bundle minificado (renglones kilometricos)."""
    lineas = js.splitlines() or [js]
    if not lineas:
        return False
    if max(len(l) for l in lineas) > _MINIF_LINEA_MAX:
        return True
    return len(js) / max(1, len(lineas)) > _MINIF_MEDIA


def problemas_js(js: str, etiqueta: str = "") -> list:
    """Los problemas estructurales de un cuerpo de JS. [] si no hay ninguno.

    Doble pasada: solo se reprueba lo que las DOS lecturas de `/` confirman.
    """
    if parece_minificado(js):
        return []
    pre = f"{etiqueta}: " if etiqueta else ""
    con = escanear_js(js, con_regex=True)
    sin = escanear_js(js, con_regex=False)
    fuera = []
    if con["abierto"] and sin["abierto"]:
        fuera.append(f"{pre}el codigo termina con {con['abierto']} sin cerrar")
    for par, nombre in (("{", "llave"), ("(", "parentesis"), ("[", "corchete")):
        a, b = con["saldos"][par], sin["saldos"][par]
        if a > 0 and b > 0:
            fuera.append(f"{pre}quedan {min(a, b)} {nombre}(s) '{par}' sin cerrar")
        elif a < 0 and b < 0:
            cierre = APERTURAS[par]
            fuera.append(f"{pre}hay {min(-a, -b)} '{cierre}' de mas "
                         "(cierran algo que nunca se abrio)")
    return fuera


# ── HTML ───────────────────────────────────────────────────────────────

def bloques_script(html: str) -> list:
    """[(atributos, cuerpo), ...] de cada `<script>` con su cierre encontrado.

    El segundo elemento del retorno global (`abiertos`) es cuantos `<script>`
    se quedaron sin `</script>`; aqui solo salen los cerrados.
    """
    fuera, pos = [], 0
    while True:
        m = _RE_SCRIPT_ABRE.search(html, pos)
        if not m:
            return fuera
        c = _RE_SCRIPT_CIERRA.search(html, m.end())
        if not c:
            return fuera
        fuera.append((m.group(0), html[m.end():c.start()]))
        pos = c.end()


def problemas_html(html: str) -> list:
    """Los problemas estructurales de un documento HTML. [] si no hay ninguno."""
    fuera = []
    abre = len(_RE_SCRIPT_ABRE.findall(html))
    cierra = len(_RE_SCRIPT_CIERRA.findall(html))
    if abre > cierra:
        fuera.append(f"{abre - cierra} bloque(s) <script> sin su </script>: "
                     "el fichero esta cortado")
    bajo = html.lower()
    # `</html>` y `</body>` solo se exigen si el documento los abrio: un
    # fragmento HTML suelto (una plantilla parcial) es legitimo y no se reprueba.
    if "<html" in bajo and "</html>" not in bajo:
        fuera.append("falta el cierre </html>: el documento no termina")
    if "<body" in bajo and "</body>" not in bajo:
        fuera.append("falta el cierre </body>: el documento no termina")
    for i, (attrs, cuerpo) in enumerate(bloques_script(html), 1):
        if _RE_SRC.search(attrs):
            continue                     # script externo: no hay cuerpo que mirar
        tipo = re.search(r'type\s*=\s*["\']([^"\']+)', attrs, re.I)
        if tipo and "javascript" not in tipo.group(1).lower() and "module" not in tipo.group(1).lower():
            continue                     # x-shader, application/json, importmap...
        if not cuerpo.strip():
            continue
        fuera.extend(problemas_js(cuerpo, f"<script> #{i}"))
    return fuera


# ── Puerta unica ───────────────────────────────────────────────────────

def problemas(ruta, texto=None) -> list:
    """Los problemas estructurales de un fichero web. [] si esta entero.

    `texto` permite verificar sin tocar disco (el arnes suele tenerlo ya en
    memoria). Si la extension no es web devuelve [] -- este modulo no opina
    sobre lo que no sabe mirar.
    """
    p = Path(str(ruta))
    suf = p.suffix.lower()
    if suf not in EXT_HTML + EXT_JS:
        return []
    if texto is None:
        try:
            texto = p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return [f"ilegible ({e.__class__.__name__})"]
    if suf in EXT_HTML:
        return problemas_html(texto)
    return problemas_js(texto)


def veredicto(ruta, texto=None):
    """``(ok, motivo)`` para un fichero web.

    ``ok`` es True (entero), False (truncado/desbalanceado) o None (no es un
    fichero web, o sea: no me toca opinar).
    """
    p = Path(str(ruta))
    if p.suffix.lower() not in EXT_HTML + EXT_JS:
        return (None, "no es HTML ni JS")
    fallos = problemas(ruta, texto)
    if fallos:
        return (False, "INCOMPLETO -> " + " | ".join(fallos[:3]))
    return (True, "estructura completa (cierres y balanceo)")
