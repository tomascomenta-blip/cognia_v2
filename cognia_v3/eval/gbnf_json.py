# -*- coding: utf-8 -*-
"""Generador + validador de gramáticas GBNF: JSON con schema EXACTO.

Palanca cero-GPU para el gap de FORMATO del diagnóstico JSON (diag_json
N=24: 3/24 fallos de schema — clave traducida 'dependencias'→'dependencies',
{} en vez de {empty:{}}, {} en vez de {nulo:null}). La grammar viaja como
string GBNF en el campo "grammar" de /completion (llama-server b9391; ver
node/llama_backend.py generate()) y el server restringe el SAMPLING: el
modelo NO PUEDE emitir otra clave, ni omitirla, ni envolver en ```json —
no_json y schema quedan imposibles POR CONSTRUCCIÓN (el único escape
residual es truncamiento por max_tokens). OJO: el impl in-process
(llama-cpp-python) IGNORA grammar — diag_json --grammar aborta si el
backend no es llama-server.

esquema_a_gbnf({clave: tipo}) fuerza un objeto con EXACTAMENTE esas claves,
en CUALQUIER orden (permutaciones enumeradas, tope _PERM_MAX), cada una con
su tipo JSON. Tipos soportados: los mismos que usan los schemas de
diag_json — str, int, float, bool, list, dict, type(None) y tuplas de esos
(unión; (int, float) colapsa a number). Nota: float acepta también la forma
entera "7" (number de JSON); los schemas del diag siempre usan (int, float),
donde eso es lo correcto.

Verificación SIN server (no hay llama-gbnf-validator en node/): este módulo
trae su propio parser del subset GBNF que emitimos (literales con escapes,
clases de caracteres con rangos/negación/\\xNN, grupos, alternancia |,
sufijos * + ?, comentarios #) y un matcher por backtracking con avance
obligatorio en repeticiones (termina siempre; suficiente para los JSON
cortos del diagnóstico, no es un motor general). validar_gbnf() chequea
sintaxis + referencias definidas + root; coincide() prueba cadenas
concretas; autocomprobar() cierra el lazo con positivos y negativos.

Uso: .\\venv312\\Scripts\\python.exe -m cognia_v3.eval.gbnf_json
     (autocomprueba las grammars de TODOS los schemas de diag_json.TAREAS)
"""
import itertools
import json
import sys

# Tope de claves para el "cualquier orden": se enumeran n! permutaciones.
# 5 claves = 120 alternativas (la gramática sigue chica); los schemas del
# diagnóstico usan <= 4. Más allá: ValueError explícito — NO degradar a
# orden fijo en silencio (cambiaría QUÉ mide el instrumento).
_PERM_MAX = 5

# tipo Python del schema -> regla GBNF del valor JSON correspondiente
_TIPO_A_REGLA = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
    type(None): "null",
}

# Reglas base JSON (adaptadas de grammars/json.gbnf de llama.cpp; sin
# repetición acotada {n} ni '_' en nombres, para máxima compatibilidad con
# el parser del b9391). string = cualquier char salvo control/quote/backslash
# crudos, más los escapes JSON estándar.
_REGLAS_BASE = r'''ws ::= [ \t\n\r]*
hex ::= [0-9a-fA-F]
string ::= "\"" ( [^"\\\x00-\x1F] | "\\" (["\\/bfnrt] | "u" hex hex hex hex) )* "\""
integer ::= "-"? ("0" | [1-9] [0-9]*)
number ::= "-"? ("0" | [1-9] [0-9]*) ("." [0-9]+)? ([eE] [-+]? [0-9]+)?
boolean ::= "true" | "false"
null ::= "null"
value ::= object | array | string | number | boolean | null
object ::= "{" ws ( string ws ":" ws value ( ws "," ws string ws ":" ws value )* )? ws "}"
array ::= "[" ws ( value ( ws "," ws value )* )? ws "]"'''


def _escapar_gbnf(s: str) -> str:
    """Escapa s para un literal GBNF "..." (\\" \\\\ \\n \\r \\t; el resto va
    crudo — UTF-8 válido, acentos incluidos, que el b9391 decodifica)."""
    out = []
    for ch in s:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        else:
            out.append(ch)
    return "".join(out)


def _regla_de_tipo(tipo) -> str:
    """Expresión GBNF del valor para un tipo del schema (type o tupla=unión)."""
    if isinstance(tipo, tuple):
        reglas = []
        for t in tipo:
            r = _regla_de_tipo(t)
            if r not in reglas:
                reglas.append(r)
        # integer ⊂ number: la unión colapsa (evita alternancia redundante)
        if "number" in reglas and "integer" in reglas:
            reglas.remove("integer")
        return reglas[0] if len(reglas) == 1 else "(" + " | ".join(reglas) + ")"
    if tipo not in _TIPO_A_REGLA:
        raise ValueError(f"tipo no soportado en schema: {tipo!r}")
    return _TIPO_A_REGLA[tipo]


def esquema_a_gbnf(schema: dict) -> str:
    """Gramática GBNF que fuerza {EXACTAMENTE las claves de schema, en
    cualquier orden, cada una con su tipo}.

    root arranca en "{" (sin ws inicial) y termina en "}" (sin ws final):
    tras cerrar el objeto el único token legal es EOS — evita loops de
    whitespace en greedy al principio y al final de la generación.
    """
    if not isinstance(schema, dict) or not schema:
        raise ValueError("schema debe ser un dict {clave: tipo} no vacío")
    claves = list(schema.keys())
    if any(not isinstance(k, str) for k in claves):
        raise ValueError("las claves del schema deben ser strings")
    if len(claves) > _PERM_MAX:
        raise ValueError(
            f"schema con {len(claves)} claves > _PERM_MAX={_PERM_MAX}: "
            f"el 'cualquier orden' enumera n! permutaciones")
    lineas = []
    for i, k in enumerate(claves):
        # json.dumps produce el string JSON que DEBE emitir el modelo
        # ("título", comillas incluidas) y _escapar_gbnf lo re-escapa para
        # el literal de la gramática (doble nivel: JSON dentro de GBNF).
        lit = _escapar_gbnf(json.dumps(k, ensure_ascii=False))
        lineas.append(f'kv{i} ::= "{lit}" ws ":" ws {_regla_de_tipo(schema[k])}')
    perms = [' ws "," ws '.join(f"kv{i}" for i in p)
             for p in itertools.permutations(range(len(claves)))]
    lineas.append("pares ::= " + " | ".join(perms))
    return ('root ::= "{" ws pares ws "}"\n'
            + "\n".join(lineas) + "\n" + _REGLAS_BASE + "\n")


# ── Parser GBNF propio (validador sin server) ────────────────────────────────

def parsear_gbnf(texto: str) -> dict:
    """Parsea GBNF (el subset emitido acá + el de benchmark_code) a un AST:
    {nombre: alternativas}, alternativas = tupla de secuencias, secuencia =
    tupla de elementos, elemento = (clase, dato, repetición) con clase en
    {"lit","clase","ref","grupo"} y repetición en {None,"*","+","?"}.
    Levanta ValueError con línea si la sintaxis está rota."""
    n = len(texto)

    def error(msg, p):
        linea = texto.count("\n", 0, min(p, n)) + 1
        raise ValueError(f"GBNF inválido (línea {linea}): {msg}")

    def saltar(p, con_nl):
        # espacios + comentarios; el \n solo se consume si con_nl (a nivel
        # de regla el \n es el TERMINADOR, igual que el parser de llama.cpp)
        while p < n:
            ch = texto[p]
            if ch in " \t\r" or (con_nl and ch == "\n"):
                p += 1
            elif ch == "#":
                while p < n and texto[p] != "\n":
                    p += 1
            else:
                break
        return p

    def nombre(p):
        ini = p
        if p >= n or not texto[p].isalpha():
            error("se esperaba nombre de regla", p)
        while p < n and (texto[p].isalnum() or texto[p] in "-_"):
            p += 1
        return texto[ini:p], p

    _ESC = {"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\",
            "'": "'", "/": "/", "]": "]", "[": "[", "-": "-", "^": "^"}

    def escape(p):
        # texto[p] es el char TRAS la barra: decodifica -> (char, pos)
        if p >= n:
            error("escape truncado", p)
        ch = texto[p]
        if ch in "xuU":
            largo = {"x": 2, "u": 4, "U": 8}[ch]
            cuerpo = texto[p + 1:p + 1 + largo]
            if len(cuerpo) != largo or any(
                    c not in "0123456789abcdefABCDEF" for c in cuerpo):
                error(f"escape \\{ch} malformado", p)
            return chr(int(cuerpo, 16)), p + 1 + largo
        if ch in _ESC:
            return _ESC[ch], p + 1
        error(f"escape desconocido \\{ch}", p)

    def literal(p):
        # texto[p] == '"'; devuelve (string decodificado, pos tras cerrar)
        p += 1
        out = []
        while p < n and texto[p] != '"':
            if texto[p] == "\n":
                error("literal sin cerrar", p)
            if texto[p] == "\\":
                ch, p = escape(p + 1)
            else:
                ch = texto[p]
                p += 1
            out.append(ch)
        if p >= n:
            error("literal sin cerrar", p)
        return "".join(out), p + 1

    def clase(p):
        # texto[p] == '['; devuelve ((negado, rangos), pos tras cerrar)
        p += 1
        negado = False
        if p < n and texto[p] == "^":
            negado = True
            p += 1
        rangos = []
        while p < n and texto[p] != "]":
            if texto[p] == "\n":
                error("clase sin cerrar", p)
            if texto[p] == "\\":
                c1, p = escape(p + 1)
            else:
                c1 = texto[p]
                p += 1
            if p + 1 < n and texto[p] == "-" and texto[p + 1] != "]":
                p += 1
                if texto[p] == "\\":
                    c2, p = escape(p + 1)
                else:
                    c2 = texto[p]
                    p += 1
                rangos.append((c1, c2))
            else:
                rangos.append((c1, c1))
        if p >= n:
            error("clase sin cerrar", p)
        return (negado, tuple(rangos)), p + 1

    def sufijo(p, el):
        if p < n and texto[p] in "*+?":
            return (el[0], el[1], texto[p]), p + 1
        return el, p

    def secuencia(p, anidado):
        # elementos hasta terminador: EOF, '\n' (nivel regla), '|' o ')'.
        # El PRIMER salto admite \n (como llama.cpp tras '::=' y tras '|').
        elems = []
        primera = True
        while True:
            p = saltar(p, anidado or primera)
            primera = False
            if p >= n:
                break
            ch = texto[p]
            if ch == "\n" or ch == "|" or ch == ")":
                break
            if ch == '"':
                s, p = literal(p)
                el, p = sufijo(p, ("lit", s, None))
            elif ch == "[":
                d, p = clase(p)
                el, p = sufijo(p, ("clase", d, None))
            elif ch == "(":
                alts, p = alternativas(p + 1, True)
                if p >= n or texto[p] != ")":
                    error("falta ')'", p)
                el, p = sufijo(p + 1, ("grupo", alts, None))
            elif ch.isalpha():
                nom, p2 = nombre(p)
                # lookahead: '¿nombre ::=' = arranque de la PRÓXIMA regla?
                q = saltar(p2, True)
                if texto[q:q + 3] == "::=":
                    break
                el, p = sufijo(p2, ("ref", nom, None))
            else:
                error(f"carácter inesperado {ch!r}", p)
            elems.append(el)
        if not elems:
            error("secuencia vacía", p)
        return tuple(elems), p

    def alternativas(p, anidado):
        alts = []
        seq, p = secuencia(p, anidado)
        alts.append(seq)
        while p < n and texto[p] == "|":
            seq, p = secuencia(p + 1, anidado)
            alts.append(seq)
        return tuple(alts), p

    reglas = {}
    pos = 0
    while True:
        pos = saltar(pos, True)
        if pos >= n:
            break
        nom, pos = nombre(pos)
        pos = saltar(pos, True)
        if texto[pos:pos + 3] != "::=":
            error(f"falta '::=' tras {nom!r}", pos)
        alts, pos = alternativas(pos + 3, False)
        if nom in reglas:
            error(f"regla duplicada: {nom!r}", pos)
        reglas[nom] = alts
    if not reglas:
        raise ValueError("GBNF inválido: sin reglas")
    return reglas


def validar_gbnf(texto: str) -> list:
    """Lista de errores (vacía = gramática bien formada): sintaxis GBNF +
    toda referencia definida + existe root + nombres compatibles con el
    parser de llama.cpp (alfanumérico y '-'; sin '_' por compat conservadora)."""
    try:
        reglas = parsear_gbnf(texto)
    except ValueError as e:
        return [str(e)]
    errores = []
    if "root" not in reglas:
        errores.append("falta la regla root")

    def _refs(alts):
        for seq in alts:
            for el in seq:
                if el[0] == "ref":
                    yield el[1]
                elif el[0] == "grupo":
                    yield from _refs(el[1])

    for nom, alts in reglas.items():
        if "_" in nom:
            errores.append(f"nombre de regla con '_': {nom!r} (usar '-')")
        for r in _refs(alts):
            if r not in reglas:
                errores.append(f"regla {nom!r} referencia {r!r} no definida")
    return errores


# ── Matcher (¿la cadena ES generada por la gramática?) ───────────────────────

def _match_atomo(reglas, el, texto, pos):
    kind, dato, _ = el
    if kind == "lit":
        if texto.startswith(dato, pos):
            yield pos + len(dato)
    elif kind == "clase":
        negado, rangos = dato
        if pos < len(texto):
            ch = texto[pos]
            dentro = any(lo <= ch <= hi for lo, hi in rangos)
            if dentro != negado:
                yield pos + 1
    elif kind == "ref":
        yield from _match_alts(reglas, reglas[dato], texto, pos)
    elif kind == "grupo":
        yield from _match_alts(reglas, dato, texto, pos)


def _match_elem(reglas, el, texto, pos):
    rep = el[2]
    if rep is None:
        yield from _match_atomo(reglas, el, texto, pos)
        return
    if rep == "?":
        yield pos
        yield from _match_atomo(reglas, el, texto, pos)
        return
    # '*' / '+': BFS de posiciones alcanzables con avance OBLIGATORIO por
    # repetición (un match de ancho 0 se corta -> termina siempre; limitación
    # asumida: ("a"?)+ sobre vacío no matchea, no aparece en nuestro subset).
    if rep == "*":
        yield pos
    vistos = {pos}
    frontera = [pos]
    while frontera:
        nueva = []
        for p in frontera:
            for q in _match_atomo(reglas, el, texto, p):
                if q > p and q not in vistos:
                    vistos.add(q)
                    nueva.append(q)
                    yield q
        frontera = nueva


def _match_seq(reglas, seq, texto, pos):
    if not seq:
        yield pos
        return
    for p in _match_elem(reglas, seq[0], texto, pos):
        yield from _match_seq(reglas, seq[1:], texto, p)


def _match_alts(reglas, alts, texto, pos):
    for seq in alts:
        yield from _match_seq(reglas, seq, texto, pos)


def coincide(gramatica, texto: str) -> bool:
    """True si texto es generado COMPLETO por la gramática desde root.
    gramatica: string GBNF o AST ya parseado (parsear_gbnf)."""
    reglas = parsear_gbnf(gramatica) if isinstance(gramatica, str) else gramatica
    return any(fin == len(texto)
               for fin in _match_alts(reglas, reglas["root"], texto, 0))


# ── Autocomprobación (lazo cerrado sin server, con fakes) ────────────────────

# valor JSON de ejemplo por tipo, para armar positivos
_EJEMPLO_POR_TIPO = {
    str: "x", int: 7, float: -1.5, bool: True,
    list: [1, "a", True], dict: {"k": 1}, type(None): None,
}

# valor JSON de tipo INCORRECTO por regla, para armar negativos
_MAL_TIPO = {"string": "7", "integer": '"x"', "number": '"x"',
             "boolean": '"x"', "array": "{}", "object": "[]", "null": '"x"'}


def _ejemplo(tipo):
    return _EJEMPLO_POR_TIPO[tipo[0] if isinstance(tipo, tuple) else tipo]


def _json_obj(pares) -> str:
    """'{"k": v, ...}' desde [(clave, valor_python)] — la forma canónica que
    emite json.dumps, que la gramática DEBE aceptar."""
    return "{" + ", ".join(
        json.dumps(k, ensure_ascii=False) + ": " + json.dumps(v, ensure_ascii=False)
        for k, v in pares) + "}"


def autocomprobar(schema: dict) -> list:
    """Genera la grammar del schema y la somete a positivos/negativos con el
    matcher propio. Lista de fallos (vacía = OK):
      + acepta el objeto ejemplo en TODAS las permutaciones de claves
      - rechaza: {} (fallos (b)/(c) del diagnóstico), subconjunto de claves,
        clave extra, clave renombrada (fallo (a): 'dependencias'→
        'dependencies'), y valor de tipo equivocado en la primera clave.
    """
    g = esquema_a_gbnf(schema)
    fallos = list(validar_gbnf(g))
    if fallos:
        return fallos
    reglas = parsear_gbnf(g)
    claves = list(schema.keys())
    obj = {k: _ejemplo(t) for k, t in schema.items()}

    # positivos: todas las permutaciones de orden de claves
    for p in itertools.permutations(claves):
        j = _json_obj([(k, obj[k]) for k in p])
        if not coincide(reglas, j):
            fallos.append(f"rechaza un positivo válido: {j}")
    # negativos
    if coincide(reglas, "{}"):
        fallos.append("acepta {} (claves faltantes)")
    if len(claves) > 1:
        j = _json_obj([(claves[0], obj[claves[0]])])
        if coincide(reglas, j):
            fallos.append(f"acepta subconjunto de claves: {j}")
    j = _json_obj([("X" + k if i == 0 else k, obj[k])
                   for i, k in enumerate(claves)])
    if coincide(reglas, j):
        fallos.append(f"acepta clave renombrada: {j}")
    j = _json_obj([(k, obj[k]) for k in claves])[:-1] + ', "claveextra": 1}'
    if coincide(reglas, j):
        fallos.append("acepta clave extra")
    regla0 = _regla_de_tipo(schema[claves[0]])
    if regla0 in _MAL_TIPO:
        j = "{" + json.dumps(claves[0], ensure_ascii=False) + ": " \
            + _MAL_TIPO[regla0] + (", " if len(claves) > 1 else "") \
            + ", ".join(json.dumps(k, ensure_ascii=False) + ": "
                        + json.dumps(obj[k], ensure_ascii=False)
                        for k in claves[1:]) + "}"
        if coincide(reglas, j):
            fallos.append(f"acepta tipo equivocado: {j}")
    return fallos


def main():
    # Autocomprobación de las grammars de TODOS los schemas del diagnóstico:
    # es la verificación pre-medición (sin server) que exige el método.
    from cognia_v3.eval.diag_json import TAREAS
    total = fallidos = 0
    for i, (_, schema, _) in enumerate(TAREAS):
        if not schema:
            continue  # ítems sin schema (p.ej. el array idx 9) no llevan grammar
        total += 1
        fallos = autocomprobar(schema)
        if fallos:
            fallidos += 1
            print(f"[{i:02d}] FALLA: {fallos}")
    print(f"[gbnf-json] autocomprobación: {total - fallidos}/{total} schemas OK")
    print("\n--- ejemplo: schema del fallo (a) del diagnóstico ---")
    print(esquema_a_gbnf({"version": str, "dependencias": list}))
    sys.exit(1 if fallidos else 0)


if __name__ == "__main__":
    main()
