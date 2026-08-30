# -*- coding: utf-8 -*-
"""
autoprueba.py — Cognia prueba end-to-end sus PROPIOS productos y los evalua.

POR QUE EXISTE: la biblioteca de cognia/program_creator/generated_programs/ se
llena en el momento de generar (evaluator.py puntua el programa con el resultado
de ESA corrida) y despues nadie la vuelve a mirar. Nada garantiza que lo
archivado siga compilando, arrancando y teniendo cuerpo: el propio repo ya se
mordio dos veces con programas guardados que reventaban en runtime (ver las dos
"compuertas duras" de evaluator.py, 2026-07-20 y 2026-07-21). Esto es la
verificacion POSTERIOR: agarra lo que hay en disco, lo corre de verdad y le pone
nota con criterios explicitos.

QUE VERIFICA, en orden, parando en el primer fallo duro:
  1. compila   — ast.parse de TODOS sus .py (cuantos de cuantos)
  2. importa   — carga el entrypoint en un SUBPROCESO aislado, con __name__ != "__main__"
  3. arranca   — ejecuta el entrypoint en SUBPROCESO, cwd en su carpeta, CON GUION
                 de teclado, y otra vez con OTRO guion (BRAZO B)
  4. sin_stubs — heuristica de vacio (archivos de <5 lineas utiles, funciones pass/TODO)

DE INICIO A FIN, Y NO SOLO "NO REVIENTA" (2026-08-29):
  Hasta hoy el arranque se lanzaba con stdin=DEVNULL y el EOFError se PERDONABA,
  asi que 9 de los 43 productos python de la biblioteca "arrancaban" muriendo de
  teclado sin ejecutar UNA sola de sus funciones. Ahora:
    - si el fuente lee teclado, se le fabrica un GUION de stdin a partir de los
      prompts de sus input() (regex), o el generico ["1","1","2","0","q"] si no
      se puede leer ninguno. Se cachea en <producto>/.autoprueba.json y se puede
      editar a mano: el fichero MANDA sobre lo derivado.
    - BRAZO B obligatorio (el patron de agf/agents/tester.py:jugar(control=True),
      corregido): la MISMA corrida con OTRO guion, no sin guion. Si stdout no
      cambia, la salida del producto no depende del valor tecleado
      (no_reacciona=True). Es un DATO del sello, no un fallo: ver abajo.
    - la excusa del EOFError se retira SOLO donde toca: con guion suministrado un
      EOFError significa "el guion se quedo corto" -> INDETERMINADO (ok=None), que
      no es culpa del producto pero tampoco es "arranco". Sin guion posible, la
      regla vieja sigue viva.

POR QUE EL SEGUNDO BRAZO LLEVA GUION Y NO STDIN CERRADO (medido 2026-08-30):
  la primera version comparaba "con guion" contra "con stdin=DEVNULL". Eso NO
  media si el producto usa el valor: media si SOBREVIVE al EOF. Todo producto
  con un input() que no sea lo ultimo muere de EOFError en el brazo nulo antes
  de imprimir el resto, asi que los dos stdout diferian SIEMPRE. Sobre 7 formas
  con verdad conocida el detector acertaba 5/7 (aprobaba a dos que tiran el
  valor) y — peor — CONDENABA A 3 SANOS, entre ellos el patron mas comun de un
  script de consola: imprimir el informe entero y acabar en
  `input("Pulsa Enter para salir...")`. Ese programa imprime su prompt ANTES de
  leer y muere ahi en el brazo nulo, asi que los dos stdout salian identicos
  byte a byte -> "no ejecuta su logica, solo imprime", que es falso.
  Con los DOS brazos guionados el EOF cae en el mismo punto en ambos y la
  diferencia mide el VALOR: 7/7 con verdad conocida (ver abajo).

Y POR QUE `no_reacciona` NO REPRUEBA (la decision, con su dato):
  `print("hola mundo"); input("pulsa enter para salir")` y el informe de ventas
  de 40 lineas que acaba igual son INDISTINGUIBLES para cualquier medida de
  stdout: los dos imprimen algo fijo y tiran lo tecleado. Uno se considera un
  cascaron y el otro es sano, y la diferencia no esta en como responden al
  teclado sino en cuanto cuerpo tienen — que es exactamente lo que ya mide la
  fase sin_stubs. No existe corte en esta metrica que condene al primero y
  perdone al segundo. Por eso `no_reacciona` se publica en el sello, se cuenta
  en el reporte y NO fuerza `ok=False`: la memoria de esta casa dice que un
  contrato que condena sanos acaba apagado, y con el se va lo que si servia.

DOS TRAMPAS QUE YA NOS MORDIERON Y ESTAN CONTEMPLADAS:
  - Un juego interactivo se queda esperando input(): el TIMEOUT NO es fallo, es
    la prueba de que arranco. Solo un Traceback o un error de sintaxis lo son.
  - Un SyntaxError del script principal NO imprime "Traceback": Python lo reporta
    con "  File ..." + "SyntaxError:". Buscar solo "Traceback" da falso verde.
    Por eso _hay_error_python() busca tambien SyntaxError/IndentationError/TabError.

NADA de codigo generado se importa en el proceso principal: es codigo no
confiable. Todo va a subproceso con timeout.

Las paginas HTML se revisan con revisar_html() de sandbox_runner, se abren en un
navegador real, y desde 2026-08-29 pasan ademas un CONTRATO GENERICO ejecutable
con Playwright (contar controles, clicar hasta 3, exigir que el DOM cambie o que
la pagina se anime sola) y el GATE DE PIXELES de frames_gate.py (frame negro y
lienzo uniforme se rechazan con motivo). El contrato es GENERICO a proposito: la
memoria de esta casa dice que el contrato "por idea" esta al nivel del azar y
reprueba el 88-94% de las paginas SANAS.
"""

import ast
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from .program_creator.sandbox_runner import revisar_html

# Carpeta canonica de la biblioteca de productos.
DIR_PRODUCTOS = Path(__file__).resolve().parent / "program_creator" / "generated_programs"

TIMEOUT_ARRANQUE_SEG = 6      # corto a proposito: solo queremos ver si levanta
TIMEOUT_IMPORT_SEG   = 6
MAX_SALIDA_CHARS     = 4000
# Codigos de retorno propios de _correr(), nombrados: eran -3 y -4 magicos y eso
# fue justo lo que dejo pasar el bug de "culpar al producto por un fallo del SO".
RC_TIMEOUT  = -3   # el producto seguia vivo al vencer el timeout (NO es fallo)
RC_NO_LANZO = -4   # el SO no pudo crear el proceso: indeterminado, no del producto

# Un archivo con menos de esto no es codigo, es un placeholder. Medido: el
# main.py de cognia_game es literalmente `print("hello")`.
MIN_LINEAS_UTILES = 5

# Firmas de que el interprete murio. "Traceback" NO alcanza (ver cabecera).
_PATRONES_ERROR = (
    "Traceback (most recent call last)",
    "SyntaxError",
    "IndentationError",
    "TabError",
)

_RE_MAIN_GUARD = re.compile(r"""if\s+__name__\s*==\s*['"]__main__['"]""")

# ── Guion de teclado (el "de inicio a fin" de un script de consola) ────────────

# Cache del guion, JUNTO al producto. Es editable a mano y MANDA sobre lo que
# derive el regex: si el dueno sabe que su juego se juega con "w/a/s/d", lo
# escribe una vez y la autoprueba lo respeta para siempre.
NOMBRE_CACHE_GUION = ".autoprueba.json"

# Guion de respaldo cuando el fuente lee teclado pero no se puede extraer NI UN
# prompt (input() con la pregunta en una variable, sys.stdin.read(), readline()).
GUION_GENERICO = ["1", "1", "2", "0", "q"]

# Tope de lineas que se teclean. Un menu en `while True:` tiene UN solo input()
# en el fuente y necesita muchas respuestas para llegar a su salida.
MAX_LINEAS_GUION = 14

# Cola que se le pega a todo guion para llegar a la rama de salida: sin ella un
# menu se come el timeout entero y nunca se ve su despedida.
#
# POR QUE HAY DOS COLAS (medido 2026-08-29 sobre la biblioteca real): con la cola
# fija ["0","q"], stem_encryptor —que pide numeros— reventaba con
# `ValueError: invalid literal for int() with base 10: 'q'`. Ese rojo lo
# fabricaba la PRUEBA, no el producto. Si todo lo que el programa pide son
# numeros, la cola tambien es numerica.
_COLA_NUMERICA = ["0", "0"]
_COLA_MIXTA    = ["0", "q"]

# Un producto lee teclado si aparece cualquiera de estas. `input(` no alcanza:
# hay productos que leen con sys.stdin directamente.
_RE_LEE_TECLADO = re.compile(r"\binput\s*\(|sys\.stdin|\.readline\s*\(")

# El literal de la pregunta de cada input(), en orden de aparicion. Solo casa
# el prompt CONSTANTE (str o f-string): con la pregunta en una variable cae al
# guion generico, que es exactamente lo que hay que hacer.
_RE_INPUT_PROMPT = re.compile(
    r"""\binput\s*\(\s*(?:[rRbBuUfF]{0,2})(?P<q>['"])(?P<txt>(?:\\.|(?!(?P=q))[^\\])*)(?P=q)""")

# Que se teclea segun lo que PREGUNTA el prompt. Se recorre en orden: la primera
# que casa gana. Es una tabla y no un if-chain justamente para que anadir un
# caso nuevo sea una linea.
_RESPUESTAS_POR_PROMPT = (
    (re.compile(r"s\s*/\s*n|y\s*/\s*n|si\s*/\s*no|yes\s*/\s*no|\(s\)|\[s\]|\(y\)|\[y\]"), "s"),
    (re.compile(r"nombre|name|jugador|player|usuario|user|apodo|nick"), "Cognia"),
    (re.compile(r"opci|option|men[uú]|elige|elegi|escoge|choose|select|selecci"), "1"),
    (re.compile(r"archivo|fichero|ruta|file|path|carpeta|directorio"), "datos.txt"),
    (re.compile(r"texto|frase|palabra|mensaje|text\b|word|phrase|oraci|sentence"),
     "hola mundo cognia hola"),
    (re.compile(r"n[uú]mero|number|edad|age|cantidad|cu[aá]nt|entero|integer|valor|size|tama"), "7"),
    (re.compile(r"salir|quit|exit|terminar"), "1"),
)

# ── Brazo B: el MISMO guion con OTROS valores ─────────────────────────────────

# Tokens que no son un VALOR sino la SALIDA del programa. Cambiarlos en el brazo
# B cambiaria el CAMINO (el menu no llegaria a su despedida, se comeria el
# timeout) y la comparacion mediria otra cosa. Se dejan intactos a proposito.
_SENTINELAS_GUION = frozenset({"0", "q", "quit", "exit", "salir", "fin"})

# LA OPCION DE SALIDA DEL MENU, leida del propio fuente (2026-08-30).
#
# POR QUE: la cola fija ["0","q"] asume que todo menu sale con 0 o q, y el menu
# mas comun que escribe un modelo no es ese: "1. Agregar  2. Listar  3. Buscar
# 4. Salir". Ese programa nunca recibe su "4", da vueltas hasta quedarse sin
# guion y la fase 'arranca' cierra INDETERMINADO ("el guion se quedo corto").
# Medido en la tarea real de la agenda de contactos: 11 tests en verde, el
# producto perfecto, y la prueba de punta a punta sin poder emitir veredicto —
# que es justo la forma de producto de consola mas frecuente. Leer el numero de
# su opcion de salida convierte ese indeterminado en un veredicto de verdad.
#
# Dos formas, porque las dos aparecen: "4. Salir" / "[4] Exit" / "4) terminar"
# y "Salir (4)" / "Salir = 4". Se toma la PRIMERA que case; sin ninguna, la cola
# de siempre (que sigue siendo correcta para los menus que salen con 0 o q).
_RE_SALIDA_NUM_PRIMERO = re.compile(
    r"""["'\s\[(]\s*(\d)\s*[.)\]:=-]\s*(?:salir|quit|exit|terminar|finalizar|adios|cerrar)""",
    re.IGNORECASE)
_RE_SALIDA_PALABRA_PRIMERO = re.compile(
    r"""(?:salir|quit|exit|terminar|finalizar|adios|cerrar)\s*[\[(:=-]\s*(\d)\s*[\])]?""",
    re.IGNORECASE)


def salida_de_menu(codigo) -> str:
    """El numero con el que se sale del menu del programa, o "" si no se ve ninguno.

    Solo mira el FUENTE (los rotulos que imprime y su comparacion), nunca ejecuta.
    Devuelve "" tambien para "0", que ya esta en la cola de siempre.
    """
    for rx in (_RE_SALIDA_NUM_PRIMERO, _RE_SALIDA_PALABRA_PRIMERO):
        m = rx.search(codigo or "")
        if m and m.group(1) != "0":
            return m.group(1)
    return ""

# Pareja de cada respuesta que fabrica _RESPUESTAS_POR_PROMPT y GUION_GENERICO.
# La regla es "mismo tipo, otro valor": a un int(input(...)) se le sigue dando
# un numero, a un nombre otro nombre, a una ruta otra ruta.
_PAREJA_VARIANTE = {
    "1": "2", "2": "3", "3": "4", "4": "5", "5": "6",
    "6": "7", "7": "3", "8": "9", "9": "1",
    "s": "n", "y": "n", "si": "no", "yes": "no",
    "Cognia": "Zenta",
    "datos.txt": "otros.txt",
    "hola mundo cognia hola": "gato luna piedra gato",
}


def _variar(token, salida=""):
    """El valor alterno de UNA linea del guion. Determinista y del mismo tipo.

    `salida` es la opcion con la que ESTE programa sale de su menu (leida del
    fuente por salida_de_menu). Se trata como un sentinela mas: cambiarla en el
    brazo B dejaria al menu sin su salida y los dos brazos mediran caminos
    distintos, que es exactamente lo que guion_variante existe para evitar."""
    t = str(token)
    if t.strip().lower() in _SENTINELAS_GUION or (salida and t == salida):
        return t
    if t in _PAREJA_VARIANTE:
        return _PAREJA_VARIANTE[t]
    if t.isdigit():
        # (n+3)%9+1 no tiene punto fijo en 1..9 y nunca devuelve 0 (que es
        # sentinela de salida en casi todo menu).
        return str((int(t) + 3) % 9 + 1)
    if "." in t and " " not in t:            # parece un nombre de fichero
        return "alt_" + t
    return "z" + t[1:] if len(t) > 1 else "z"


def guion_variante(guion, salida=""):
    """
    El mismo guion con otros VALORES: mismas lineas, mismos tokens de salida.

    Mismo numero de lineas a proposito: asi el EOF (si lo hay) cae en el mismo
    punto en los dos brazos y la diferencia de stdout solo puede venir del
    contenido tecleado. Esa es toda la razon de ser de esta funcion.

    `salida` (opcional) es la opcion de salida del menu de ESE programa; se
    respeta igual que 0/q. Sin ella el comportamiento es el de siempre.
    """
    return [_variar(t, salida) for t in (guion or [])]


# Margen del brazo BASE vs ACTIVO, tomado literal de agf/agents/tester.py
# (_MARGEN = 1.15): la actividad CON entrada tiene que superar a la actividad
# SIN entrada por un 15% para poder decir que el producto responde al teclado.
MARGEN_JUEGO = 1.15

# Palabras que no aportan al cotejo descripcion<->codigo (es/en mezclados porque
# el index tiene descripciones en los dos idiomas).
_VACIAS = frozenset({
    "a", "an", "and", "based", "con", "de", "del", "el", "en", "for", "in",
    "la", "las", "los", "para", "program", "programa", "que", "simple",
    "terminal", "that", "the", "una", "with", "your",
})

# Se importa el modulo por ruta y con un __name__ que NO es "__main__", asi un
# script bien formado carga sus definiciones sin lanzar su bucle principal.
_CODIGO_IMPORT = (
    "import importlib.util, sys\n"
    "spec = importlib.util.spec_from_file_location('_producto_bajo_prueba', sys.argv[1])\n"
    "mod = importlib.util.module_from_spec(spec)\n"
    "sys.modules['_producto_bajo_prueba'] = mod\n"
    "spec.loader.exec_module(mod)\n"
)


# ── Descubrimiento ─────────────────────────────────────────────────────────────

def _leer(ruta):
    """Lee un archivo de texto sin explotar por encoding (hay productos con emojis)."""
    try:
        return Path(ruta).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _elegir_entrypoint(directorio, archivos_py):
    """
    Elige el .py que se ejecuta. Orden: main.py, unico .py, el que tenga guarda
    __main__, program.py, y si no el primero alfabetico.

    OJO: main.py gana aunque sea un stub (cognia_game tiene main.py con un
    print("hello") al lado de game.py, que es el programa de verdad). Se
    respeta igual porque es la convencion; la fase sin_stubs lo delata.
    """
    nombres = sorted(p.name for p in archivos_py)
    if "main.py" in nombres:
        return Path(directorio) / "main.py"
    if len(nombres) == 1:
        return Path(directorio) / nombres[0]
    con_guarda = [n for n in nombres if _RE_MAIN_GUARD.search(_leer(Path(directorio) / n))]
    if con_guarda:
        return Path(directorio) / con_guarda[0]
    if "program.py" in nombres:
        return Path(directorio) / "program.py"
    return Path(directorio) / nombres[0] if nombres else None


# Carpetas que NO son un producto sino un CAJON de productos: /construir escribe
# en construidos/<slug>/index.html y /pulir en pulidos/<slug>/index.html. Sin
# descender un nivel, descubrir_productos veia UNA entrada 'construidos' de
# lenguaje 'vacio' y los 7 productos de dentro eran invisibles para /autoprueba
# (medido 2026-08-29: construidos/ tiene 1 y pulidos/ 6).
CAJONES_ANIDADOS = ("construidos", "pulidos")

# Salidas de bancos, no productos del dueno: 68 de las 138 carpetas de
# generated_programs empiezan asi y solo ensucian el catalogo (todas salen
# 'vacio' y arrastran la media hacia abajo). Es una tupla y no un `if` enterrado
# para que anadir un banco nuevo sea una linea.
PREFIJOS_BANCO = ("b1_", "b2_", "b3_")


def _es_de_banco(nombre):
    """True si la carpeta es salida de un banco (b1_/b2_/b3_), no un producto."""
    return any(nombre.startswith(p) for p in PREFIJOS_BANCO)


def descubrir_productos(base=None):
    """
    Lista los productos de generated_programs/ con su entrypoint real.

    La fuente de verdad es EL DISCO, no el index.json: medido hoy, el index
    tiene 53 entradas de las cuales 9 apuntan a carpetas que ya no existen, y
    hay 13 carpetas que el index no menciona. Si tomaramos el index como
    catalogo probariamos 9 fantasmas y nos perderiamos 13 productos reales.
    El index solo aporta metadatos (title/description/total_score) cuando esta.

    Devuelve una lista de dicts ordenada: primero los que tienen codigo.
    """
    base = Path(base) if base else DIR_PRODUCTOS
    if not base.is_dir():
        return []

    meta = {}
    try:
        entradas = json.loads(_leer(base / "index.json") or "[]")
        for e in entradas:
            if isinstance(e, dict) and e.get("directory"):
                meta[e["directory"]] = e
    except Exception:
        pass   # un index corrupto no puede impedir probar el codigo que SI esta

    def _producto(carpeta, clave):
        """El dict de UN producto. `clave` es como se lo nombra (id/index)."""
        archivos_py   = sorted(carpeta.glob("*.py"))
        archivos_html = sorted(carpeta.glob("*.html"))
        info = meta.get(clave, {})

        if archivos_py:
            lenguaje, entrypoint = "python", _elegir_entrypoint(carpeta, archivos_py)
        elif archivos_html:
            lenguaje, entrypoint = "html", archivos_html[0]
        else:
            lenguaje, entrypoint = "vacio", None

        descripcion = (info.get("description")
                       or _leer(carpeta / "description.txt").strip())
        return {
            "id":          info.get("id") or clave,
            "title":       info.get("title") or clave.replace("_", " "),
            "description": descripcion,
            "directorio":  str(carpeta),
            "lenguaje":    lenguaje,
            "entrypoint":  str(entrypoint) if entrypoint else None,
            "archivos_py": [str(p) for p in archivos_py],
            "en_index":    clave in meta,
            "score_index": info.get("total_score"),
        }

    productos = []
    for carpeta in sorted(p for p in base.iterdir() if p.is_dir()):
        if _es_de_banco(carpeta.name):
            continue        # salida de banco, no producto del dueno
        # Un CAJON (construidos/, pulidos/) no es un producto: sus hijos si.
        # Solo se desciende si el cajon no tiene codigo propio, para no
        # convertir en invisible un producto que se llamara asi.
        if (carpeta.name in CAJONES_ANIDADOS
                and not any(carpeta.glob("*.py")) and not any(carpeta.glob("*.html"))):
            for hijo in sorted(p for p in carpeta.iterdir() if p.is_dir()):
                if _es_de_banco(hijo.name):
                    continue
                productos.append(_producto(hijo, f"{carpeta.name}/{hijo.name}"))
            continue
        productos.append(_producto(carpeta, carpeta.name))

    # Los que tienen codigo primero: con --limite N queremos probar productos,
    # no carpetas de assets sueltas.
    productos.sort(key=lambda p: (p["lenguaje"] == "vacio", p["directorio"]))
    return productos


# ── Fases de verificacion ──────────────────────────────────────────────────────

def _hay_error_python(stderr):
    """Devuelve la firma de error hallada en stderr, o "" si no hay ninguna."""
    for pat in _PATRONES_ERROR:
        if pat in (stderr or ""):
            return pat
    return ""


def _es_falta_de_teclado(stderr):
    """
    True si lo unico que rompio fue un EOFError por tener stdin cerrado.

    Medido hoy sobre la biblioteca real: royal_favors, stem_encryptor,
    decent_dilemma y reaction_diffusion_simulator son juegos interactivos SIN
    guarda `if __name__ == "__main__"` — su input() esta al nivel del modulo. Al
    importarlos se ejecutan y mueren con EOFError, y los cuatro salian marcados
    como fallo duro en 'importa'. Eso es culpa de la prueba (no le da teclado),
    no del producto: la misma regla que hace que el timeout no sea fallo.
    """
    if "EOFError" not in (stderr or ""):
        return False
    resto = "\n".join(l for l in stderr.splitlines() if "EOFError" not in l)
    return not _hay_error_python(resto.replace("Traceback (most recent call last)", ""))


def _entorno_subproceso(tmp):
    """
    Entorno minimo para el subproceso. HOME/TEMP apuntan a un temporal propio
    para que un producto que escriba "en su carpeta de datos" no ensucie el
    perfil del usuario. NO es un sandbox: ver 'Limites' en la cabecera.
    """
    return {
        "PATH":             os.environ.get("PATH", ""),
        "SYSTEMROOT":       os.environ.get("SYSTEMROOT", ""),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8":       "1",
        # Sin esto la fase 'importa' deja un __pycache__/ dentro de cada carpeta
        # de producto (medido en la primera corrida real). Probar no debe
        # ensuciar la biblioteca que se esta probando.
        "PYTHONDONTWRITEBYTECODE": "1",
        "TERM":             "dumb",
        "HOME":             tmp,
        "USERPROFILE":      tmp,
        "TMPDIR":           tmp,
        "TEMP":             tmp,
        "TMP":              tmp,
    }


def _correr(argv, cwd, timeout, guion=None):
    """
    Corre argv en subproceso. Devuelve (rc, out, err, timeout?).

    `guion=None` -> stdin CERRADO (el brazo NULO, y el camino de siempre).
    `guion=[...]` -> se teclean esas lineas y se cierra stdin: si el programa
    pide una mas, muere con EOFError, y eso significa "el guion se quedo corto",
    no "el producto esta roto" (lo distingue _veredicto_arranque).
    """
    texto_guion = ("\n".join(guion) + "\n") if guion else None
    with tempfile.TemporaryDirectory(prefix="autoprueba_") as tmp:
        try:
            comun = dict(cwd=cwd, capture_output=True, text=True, timeout=timeout,
                         env=_entorno_subproceso(tmp), errors="replace")
            if texto_guion is None:
                proc = subprocess.run(argv, stdin=subprocess.DEVNULL, **comun)
            else:
                proc = subprocess.run(argv, input=texto_guion, **comun)
            return (proc.returncode,
                    (proc.stdout or "")[:MAX_SALIDA_CHARS],
                    (proc.stderr or "")[:MAX_SALIDA_CHARS],
                    False)
        except subprocess.TimeoutExpired as tex:
            def _txt(v):
                if isinstance(v, bytes):
                    return v.decode("utf-8", errors="replace")
                return v or ""
            return RC_TIMEOUT, _txt(tex.stdout)[:MAX_SALIDA_CHARS], _txt(tex.stderr)[:MAX_SALIDA_CHARS], True
        except Exception as exc:
            return RC_NO_LANZO, "", f"[autoprueba] no se pudo lanzar: {exc}", False


def _fase_compila(prod):
    """ast.parse de todos los .py del producto. Fallo duro si alguno no compila."""
    rutas = [Path(p) for p in prod["archivos_py"]]
    errores, ok_n = [], 0
    for ruta in rutas:
        try:
            ast.parse(_leer(ruta), filename=str(ruta))
            ok_n += 1
        except SyntaxError as exc:
            errores.append(f"{ruta.name}:{exc.lineno}: {exc.msg}")
        except Exception as exc:
            errores.append(f"{ruta.name}: {exc}")
    total = len(rutas)
    return {
        "ok": total > 0 and ok_n == total,
        "compilan": ok_n, "total": total,
        "errores": errores,
        "detalle": f"{ok_n}/{total} .py compilan" + (f" | {errores[0]}" if errores else ""),
    }


def _fase_importa(prod, timeout):
    """
    Importa el entrypoint en subproceso, con __name__ != "__main__".

    Un timeout aqui NO es fallo: significa que el script no tiene guarda
    __main__ y al importarlo se puso a correr (que es exactamente lo que hace
    la mayoria de estos programas). Lo que si es fallo es un error de import.
    """
    rc, out, err, expiro = _correr(
        [sys.executable, "-s", "-c", _CODIGO_IMPORT, prod["entrypoint"]],
        cwd=prod["directorio"], timeout=timeout)
    if expiro:
        return {"ok": True, "detalle": "timeout al importar (script sin guarda __main__, se puso a correr)",
                "stderr": err[:300]}
    if _es_falta_de_teclado(err):
        return {"ok": True, "detalle": "sin guarda __main__: se ejecuto al importar y pidio input() (EOFError)",
                "stderr": err[:300]}
    # rc == RC_NO_LANZO: el SO no pudo crear el proceso (archivo de paginacion
    # chico, sin memoria, permisos). Eso NO es culpa del producto y no puede
    # contar como fallo suyo: seria un veredicto falso, y ademas volvia flaky a
    # los tests que dependen de esta fase. Se reporta como INDETERMINADO.
    if rc == RC_NO_LANZO:
        return {"ok": None, "detalle": f"indeterminado (el SO no pudo lanzar el subproceso): {err.strip()[:160]}",
                "stderr": err[:600], "entorno": True}
    firma = _hay_error_python(err)
    if firma or rc != 0:
        primera = next((l for l in reversed((err or "").splitlines()) if l.strip()), "")
        return {"ok": False, "detalle": f"{firma or 'exit ' + str(rc)}: {primera.strip()[:160]}",
                "stderr": err[:600]}
    return {"ok": True, "detalle": "import limpio", "stderr": err[:300]}


def lee_teclado(codigo):
    """True si el fuente lee de stdin (input(), sys.stdin, readline)."""
    return bool(_RE_LEE_TECLADO.search(codigo or ""))


def _respuesta_para(prompt):
    """Que se teclea ante ESA pregunta. La primera regla que casa gana."""
    p = (prompt or "").lower()
    for patron, respuesta in _RESPUESTAS_POR_PROMPT:
        if patron.search(p):
            return respuesta
    return "1"


def derivar_guion(codigo):
    """
    (guion, origen) a partir del fuente. origen in {'derivado','generico','sin_teclado'}.

    'derivado' = se leyeron los prompts literales de sus input() y se contesto a
    cada uno segun lo que pregunta. 'generico' = lee teclado pero no se pudo
    extraer ni un prompt (pregunta en variable, sys.stdin.read()).

    El guion se ALARGA con el ciclo de sus propias respuestas hasta
    MAX_LINEAS_GUION y termina en 0/q: un menu en `while True:` tiene UN solo
    input() en el fuente y necesita muchas respuestas para llegar a su salida.
    """
    if not lee_teclado(codigo):
        return [], "sin_teclado"
    prompts = [m.group("txt") for m in _RE_INPUT_PROMPT.finditer(codigo or "")]
    if prompts:
        base, origen = [_respuesta_para(p) for p in prompts], "derivado"
    else:
        base, origen = list(GUION_GENERICO), "generico"
    # Si TODO lo que pide son numeros, la cola tambien: teclearle una "q" a un
    # int(input(...)) fabrica un ValueError que no es del producto.
    cola = _COLA_NUMERICA if all(r.isdigit() for r in base) else _COLA_MIXTA
    # La opcion de salida de SU menu encabeza la cola, REPETIDA. Repetida porque
    # el guion es POSICIONAL y no sabe en que prompt va a caer: un menu que en la
    # opcion 1 pide un dato mas ("Numero: ") se come el token de salida como si
    # fuera ese dato. Medido: con una sola copia, el menu sintetico de
    # test_un_menu_que_sale_con_4_LLEGA_a_su_despedida se tragaba el "4" en el
    # input del numero y volvia a quedar INDETERMINADO. Con tres, el token cae en
    # el prompt del menu venga de donde venga. 0/q quedan detras como respaldo
    # para los menus que si salen asi.
    salida = salida_de_menu(codigo)
    if salida:
        cola = [salida] * 3 + [c for c in cola if c != salida]
    guion = list(base)
    i = 0
    while len(guion) < MAX_LINEAS_GUION - len(cola):
        guion.append(base[i % len(base)])
        i += 1
    return guion + cola, origen


def _huella_fuente(ruta) -> str:
    """sha1 del fuente del entrypoint, para saber si un guion DERIVADO envejecio."""
    try:
        return hashlib.sha1(_leer(ruta).encode("utf-8", "replace")).hexdigest()
    except Exception:
        return ""


def guion_para(prod, usar_cache=True):
    """
    (guion, origen) del producto, con cache en <producto>/.autoprueba.json.

    El fichero MANDA sobre lo derivado: si el dueno escribe ahi el guion real de
    su juego, la autoprueba lo usa tal cual para siempre. Se escribe una sola vez
    (best-effort: una carpeta de solo lectura no puede romper la prueba), y
    COGNIA_AUTOPRUEBA_CACHE=0 lo desactiva para corridas que no deben tocar la
    biblioteca del dueno.

    PERO UN GUION DERIVADO CADUCA CON SU FUENTE (2026-08-30). El guion se deduce
    de los prompts de los `input()` del programa; si el programa cambia, el guion
    viejo deja de tener nada que ver con lo que pide. Sin esto la cache CONDENA A
    UN SANO, y esta medido: en la primera tarea real de /revision el modelo
    escribio un conversor que pedia texto, se cacheo el guion generico de texto
    ("hola mundo cognia hola"), la revision lo reprobo, el modelo lo REESCRIBIO
    para pedir numeros -- y la segunda revision siguio tecleandole "hola mundo"
    al programa nuevo, que respondia "necesito el monto" y salia con exit 1. El
    producto funcionaba; el instrumento estaba midiendo la version anterior.
    Por eso el registro guarda la HUELLA del fuente del que se dedujo: si no
    coincide, se vuelve a derivar. Un fichero SIN huella (escrito a mano por el
    dueno, o de una version anterior) sigue mandando, que es el contrato de
    arriba: solo caduca lo que este modulo dedujo solo.
    """
    carpeta = Path(prod["directorio"])
    ruta = carpeta / NOMBRE_CACHE_GUION
    fuente = prod.get("entrypoint") or ""
    huella = _huella_fuente(fuente) if fuente else ""
    if usar_cache:
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
            guion = datos.get("guion")
            previa = str(datos.get("huella") or "")
            rancio = bool(previa) and bool(huella) and previa != huella
            if (isinstance(guion, list) and all(isinstance(x, str) for x in guion)
                    and not rancio):
                return guion, datos.get("origen") or "cache"
        except Exception:
            pass    # sin cache o cache corrupta: se deriva de nuevo, no se rompe

    guion, origen = derivar_guion(_leer(fuente) if fuente else "")
    if guion and usar_cache and os.environ.get("COGNIA_AUTOPRUEBA_CACHE", "1").strip() != "0":
        try:
            ruta.write_text(json.dumps(
                {"guion": guion, "origen": origen, "huella": huella,
                 "nota": "guion de teclado de /autoprueba; editalo si tu programa "
                         "se maneja de otra forma (manda sobre lo que deduce el regex). "
                         "Borra la clave 'huella' para que tu guion no caduque al "
                         "cambiar el programa."},
                ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass    # best-effort: no poder cachear no cambia el veredicto
    return guion, origen


def _veredicto_arranque(rc, out, err, expiro, timeout, con_guion):
    """
    (ok, detalle) de UNA corrida. ok=None es INDETERMINADO, no fallo.

    REGLA CLAVE: timeout == arranco bien (juego interactivo o bucle de render).
    Traceback / SyntaxError / IndentationError == fallo, aunque el rc sea 0.

    LA EXCUSA DEL EOFError, y donde se retira: sin guion, morir de EOFError es
    culpa de la PRUEBA (no le dio teclado) y cuenta como "arranco" — es la regla
    de 2026-07-23 y sigue viva. CON guion, ya se le dio teclado: un EOFError
    significa que el guion se quedo corto, y eso no es ni "arranco" ni "esta
    roto": es INDETERMINADO.
    """
    if expiro:
        return True, (f"timeout {timeout}s sin reventar = arranco "
                      f"(interactivo/bucle), {len(out.strip())} chars de salida")
    if _es_falta_de_teclado(err):
        if con_guion:
            return None, ("INDETERMINADO: se le tecleo el guion entero y siguio "
                          "pidiendo entrada (EOFError). El guion se quedo corto, "
                          f"no el producto — editalo en {NOMBRE_CACHE_GUION}")
        return True, "pidio input() y stdin esta cerrado (EOFError) = arranco"
    firma = _hay_error_python(err)
    if firma:
        ultima = next((l for l in reversed(err.splitlines()) if l.strip()), "")
        return False, f"{firma} -> {ultima.strip()[:160]}"
    if rc != 0:
        return False, f"exit {rc}"
    return True, f"exit 0, {len(out.strip())} chars de salida"


def _fase_arranca(prod, timeout, guion=None, origen_guion="sin_teclado", salida=""):
    """
    Ejecuta el entrypoint en su propia carpeta con DOS guiones distintos.

    DOS BRAZOS, los dos con teclado:
      A — con el guion derivado. Es el UNICO que da el veredicto `ok`.
      B — la misma corrida con `guion_variante(guion)`: mismas lineas, otros
          valores, mismos tokens de salida.
    Si los dos stdout son identicos byte a byte, la salida del producto no
    depende del valor tecleado: `no_reacciona=True`. Es un DATO que viaja en el
    sello y se cuenta en el reporte, y NO reprueba — ver la cabecera del modulo:
    no hay corte en esta metrica que separe un cascaron de un informe honesto
    que acaba en "Pulsa Enter para salir", y un gate que condena sanos se apaga.

    Que el brazo B lleve guion (y no stdin cerrado) es lo que hace que la
    medida signifique algo: con stdin cerrado se media "sobrevive al EOF".

    Sin guion posible (el fuente no lee teclado) se corre UNA vez, como siempre,
    y no hay nada que comparar.
    """
    argv = [sys.executable, "-s", prod["entrypoint"]]
    cwd  = prod["directorio"]

    if not guion:
        rc, out, err, expiro = _correr(argv, cwd=cwd, timeout=timeout)
        ok, detalle = _veredicto_arranque(rc, out, err, expiro, timeout, con_guion=False)
        return {"rc": rc, "timeout": expiro, "stdout": out[:800], "stderr": err[:800],
                "chars_stdout": len(out.strip()), "ok": ok, "detalle": detalle,
                "guion": [], "origen_guion": origen_guion,
                "brazo_b": None, "no_reacciona": None,
                "no_reacciona_decidible": None,
                "indeterminado": ok is None}

    # BRAZO B PRIMERO, y el A DESPUES. El orden no cambia la comparacion pero si
    # lo que queda en disco: los dos brazos corren en la MISMA carpeta, asi que
    # el ultimo pisa los ficheros que escriba el producto. El que manda es el
    # brazo A (es el que da el veredicto y el que se cita en el sello), asi que
    # es el que tiene que correr al final. Con el orden al reves, un producto que
    # escribe "resultado.txt" dejaba en disco el resultado del guion VARIANTE.
    variante = guion_variante(guion, salida)
    rcb, outb, errb, expirob = _correr(argv, cwd=cwd, timeout=timeout, guion=variante)
    okb, _detb = _veredicto_arranque(rcb, outb, errb, expirob, timeout, con_guion=True)

    rc, out, err, expiro = _correr(argv, cwd=cwd, timeout=timeout, guion=guion)
    ok, detalle = _veredicto_arranque(rc, out, err, expiro, timeout, con_guion=True)
    no_reacciona = (out == outb)

    # Decidible solo si (a) se teclearon valores REALMENTE distintos — un guion
    # que es todo sentinelas de salida da los dos brazos iguales por
    # construccion — y (b) hubo algo que comparar por stdout. Sin las dos cosas
    # la metrica no midio nada, y decirlo vale mas que inventarse un veredicto.
    valores_distintos = (variante != list(guion))
    hay_evidencia = bool(out.strip()) or bool(outb.strip())
    decidible = valores_distintos and hay_evidencia

    if not decidible:
        nota = ("brazo B: no decidible ("
                + ("los DOS brazos sin salida por stdout"
                   if valores_distintos else "el guion es todo tokens de salida")
                + ")")
    elif no_reacciona:
        nota = ("brazo B: MISMO stdout con otro guion — la salida no depende del "
                "valor tecleado (dato del sello, no reprueba)")
    else:
        nota = "brazo B: stdout distinto con otro guion — usa el valor tecleado"

    return {
        "rc": rc, "timeout": expiro, "stdout": out[:800], "stderr": err[:800],
        "chars_stdout": len(out.strip()),
        "guion": list(guion), "origen_guion": origen_guion,
        "brazo_b": {"guion": list(variante), "rc": rcb, "timeout": expirob,
                    "stdout": outb[:800], "chars_stdout": len(outb.strip()), "ok": okb},
        "no_reacciona": no_reacciona,
        "no_reacciona_decidible": decidible,
        # El veredicto es el del brazo A, y SOLO el suyo.
        "ok": ok, "indeterminado": (ok is None),
        "detalle": detalle + " | " + nota,
    }


def _lineas_utiles(texto):
    """Lineas que no son vacias ni comentario. Aproximacion barata de 'cuerpo'."""
    return [l for l in texto.splitlines()
            if l.strip() and not l.strip().startswith("#")]


def _fase_sin_stubs(prod):
    """
    Heuristica de vacio: archivos sin cuerpo y funciones que no hacen nada.

    No es una fase dura (no corta la cadena): un programa puede correr perfecto
    y estar medio hueco. Lo que hace es que el puntaje lo refleje.
    """
    vacios, huecas, funcs = [], [], 0
    marcadores = 0
    for ruta_s in (prod["archivos_py"] or ([prod["entrypoint"]] if prod["entrypoint"] else [])):
        ruta = Path(ruta_s)
        texto = _leer(ruta)
        utiles = _lineas_utiles(texto)
        if len(utiles) < MIN_LINEAS_UTILES:
            vacios.append(f"{ruta.name} ({len(utiles)} lineas utiles)")
        marcadores += len(re.findall(r"\b(TODO|FIXME|pendiente de implementar)\b", texto))
        try:
            arbol = ast.parse(texto)
        except Exception:
            continue
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            funcs += 1
            cuerpo = [n for n in nodo.body
                      if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
                              and isinstance(n.value.value, str))]   # el docstring no es cuerpo
            if not cuerpo:
                huecas.append(nodo.name)
            elif len(cuerpo) == 1:
                uno = cuerpo[0]
                if isinstance(uno, ast.Pass):
                    huecas.append(nodo.name)
                elif isinstance(uno, ast.Expr) and isinstance(uno.value, ast.Constant) \
                        and uno.value.value is Ellipsis:
                    huecas.append(nodo.name)
                elif isinstance(uno, ast.Raise) and "NotImplementedError" in ast.dump(uno):
                    huecas.append(nodo.name)

    ratio = (len(huecas) / funcs) if funcs else 0.0
    ok = not vacios and ratio <= 0.2 and marcadores == 0
    partes = []
    if vacios:
        partes.append("archivos sin cuerpo: " + ", ".join(vacios[:3]))
    if huecas:
        partes.append(f"{len(huecas)}/{funcs} funciones vacias ({', '.join(huecas[:3])})")
    if marcadores:
        partes.append(f"{marcadores} marcadores TODO/FIXME")
    return {"ok": ok, "vacios": vacios, "funciones_huecas": huecas,
            "funciones": funcs, "ratio_huecas": round(ratio, 2),
            "marcadores": marcadores,
            "detalle": "; ".join(partes) or "sin senales de stub"}


def _mirar_en_navegador(codigo, dir_producto=None, idea=""):
    """Abre la pagina en Chrome headless. (ok, detalle, errores_js).

    POR QUE (2026-08-02): esta fase se llamaba 'arranca' pero NO arrancaba nada
    — solo pasaba revisar_html(), que lee TEXTO. Una landing con
    "ReferenceError: daily is not defined" en su <script> quedaba EN NEGRO de la
    mitad para abajo y aun asi se sello 'verificado: corre (9.5/10)'. Es el
    mismo caso que motivo vista_navegador.py el 2026-07-19 (8.7/10 estatico,
    pagina negra en Chrome): el modulo existia, pero nadie lo habia enchufado al
    veredicto, asi que el juez seguia sin ejecutar.

    Sin navegador instalado NO reprueba (no todos los entornos tienen Chrome),
    pero lo DICE: un chequeo que se salta en silencio es peor que no tenerlo.
    COGNIA_VERIFICAR_NAVEGADOR=0 lo apaga (util para sellar la biblioteca
    entera, donde son ~15 s por producto).
    """
    if os.environ.get("COGNIA_VERIFICAR_NAVEGADOR", "1").strip() == "0":
        return True, "navegador desactivado (COGNIA_VERIFICAR_NAVEGADOR=0)", []
    try:
        from .program_creator.vista_navegador import revisar_en_navegador
        # dir_producto (no None) hace que las capturas PERSISTAN en
        # input_images/: sin ellas el arbitro visual no tiene nada que mirar.
        inf = revisar_en_navegador(codigo, dir_programa=dir_producto)
    except Exception as exc:                  # nunca puede tumbar la verificacion
        return True, f"no se pudo mirar la pagina ({exc.__class__.__name__}): sin este chequeo", []
    errores = list(inf.errores_js or [])
    detalle_vlm = _mirar_con_vlm(inf, idea)
    if errores:
        return (False,
                "errores de JavaScript al cargar: " + "; ".join(errores[:3]) + detalle_vlm,
                errores)
    if inf.nota:                              # p.ej. "Sin navegador instalado"
        return True, inf.nota + detalle_vlm, []
    return True, "abre en el navegador sin errores de JS" + detalle_vlm, []


# (funcion_que_lo_midio, motivo) del "el VLM no esta", cacheado para el proceso.
# None = sin probar. `reiniciar_cache_vlm()` lo limpia para reintentar tras
# arrancar servir_vlm.py.
_VLM_AUSENTE = None


def reiniciar_cache_vlm():
    """Olvida el 'el VLM no esta' cacheado y vuelve a probarlo."""
    global _VLM_AUSENTE
    _VLM_AUSENTE = None


def _mirar_con_vlm(informe, idea):
    """El arbitro VLM MIRA el screenshot real. Devuelve texto para el detalle.

    NO entra en el veredicto de pase/fallo, y es deliberado: juez_ejecutable.py
    documenta el caso medido que lo justifica — un juego de memoria con las 16
    cartas DESTAPADAS saco 7.5/10 del VLM porque vio una cuadricula bonita. Si
    la estetica puntua el veredicto, el lazo optimiza apariencia. La ejecucion
    manda; el ojo informa.

    Sin VLM servido no falla: lo DICE. Un arbitro ausente en silencio es
    justamente como se llego a sellar paginas rotas con 9.5.
    """
    global _VLM_AUSENTE
    try:
        from .program_creator.arbitro_visual import (
            arbitrar_desde_informe, vlm_disponible)
        # El cache esta KEYADO por la funcion que lo midio: si alguien la
        # sustituye (un test que la parchea, o servir_vlm.py recargado), el
        # cache no aplica. Sin esa clave, el estado global de un test se filtraba
        # al siguiente y dos tests de test_verificacion_navegador se ponian rojos.
        if _VLM_AUSENTE is not None and _VLM_AUSENTE[0] is vlm_disponible:
            return f" | VLM: NO juzgo ({_VLM_AUSENTE[1]})"
        vivo, motivo = vlm_disponible()
        if not vivo:
            # Se CACHEA el "no esta" (medido: 2,0 s de urlopen que expira, por
            # producto — dos minutos enteros al sellar los 70 de la biblioteca).
            # Solo el negativo: si el VLM esta vivo se le pregunta siempre.
            _VLM_AUSENTE = (vlm_disponible, motivo)
            return f" | VLM: NO juzgo ({motivo})"
        fallo = arbitrar_desde_informe(idea or "pagina web", informe)
        if not fallo:
            return " | VLM: sin veredicto"
        defectos = fallo.get("defectos") or []
        return (f" | VLM: {fallo.get('nota', '?')}/10 {fallo.get('veredicto', '')}"
                + (f" ({len(defectos)} defectos visuales)" if defectos else ""))
    except Exception as exc:
        return f" | VLM: error al mirar ({exc.__class__.__name__})"


# ── Contrato GENERICO de una pagina + gate de pixeles ──────────────────────────
#
# PROHIBIDO generar contratos "por idea". Lo dice lo medido en esta casa: el
# contrato interno esta al nivel del azar y CONDENA SANOS (reprueba el 88-94% de
# las paginas que funcionan). Lo que hay aqui es lo unico que se puede afirmar de
# CUALQUIER pagina sin inventar una especificacion: cuantos controles clicables
# tiene, si alguno cambia el DOM, si se anima sola, y si sus capturas son algo
# mas que un rectangulo negro.

# Fraccion de pixeles muestreados que tiene que moverse para llamarlo movimiento.
# 0,005 = medio por ciento; por debajo es el cursor de un <input> parpadeando.
UMBRAL_ACTIVIDAD = 0.005

# Cuanto se deja correr la pagina en cada fase antes del segundo frame.
ESPERA_FASE_MS = 700
TIMEOUT_CONTRATO_SEG = 25

# Controles que se pueden clicar SIN navegar fuera de la pagina. Un <a href> a
# otra URL se cuenta pero no se clica: si el clic navega, el DOM cambia por
# mudarse de pagina y el contrato daria un verde que no midio nada.
_SEL_CLICABLES = ("button, [onclick], [role=button], summary, "
                  "input[type=button], input[type=submit], input[type=checkbox], "
                  "input[type=radio], a[href^='#'], a[href^='javascript']")
_SEL_CONTROLES = _SEL_CLICABLES + ", a[href], input, select, textarea, [tabindex]"

# Teclas del brazo ACTIVO. Cubren los dos esquemas de control que usa el 100% de
# los juegos web que genera este repo (flechas y WASD) mas el disparo/saltar.
_TECLAS_JUEGO = ("ArrowRight", "ArrowLeft", "ArrowUp", "ArrowDown",
                 " ", "w", "a", "s", "d", "Enter")

_RE_JUEGO_POR_NOMBRE = re.compile(
    r"\bjuego|\bgame\b|arcade|pong|snake|tetris|platformer|shooter", re.IGNORECASE)
_RE_JUEGO_POR_CODIGO = re.compile(
    r"requestAnimationFrame|addEventListener\s*\(\s*['\"]key|<canvas|"
    r"\bkeydown\b|\bgameLoop\b|\bplayer\b", re.IGNORECASE)
# Formas de RECIBIR entrada. Si no hay ninguna, la pagina no es que "ignore" el
# teclado: es que no tiene por donde oirlo.
_RE_ESCUCHA_INPUT = re.compile(
    r"addEventListener\s*\(\s*['\"](key|click|mouse|pointer|touch)|"
    r"\bon(click|keydown|keyup|keypress|mousedown|pointerdown)\s*=", re.IGNORECASE)


def juego_por_nombre(prod):
    """True si el producto SE LLAMA juego (su id/title/description lo dice)."""
    texto = " ".join(str((prod or {}).get(k) or "") for k in ("id", "title", "description"))
    return bool(_RE_JUEGO_POR_NOMBRE.search(texto))


def parece_juego(prod, codigo=""):
    """True si el producto se comporta como un juego (por nombre o por codigo)."""
    return juego_por_nombre(prod) or bool(_RE_JUEGO_POR_CODIGO.search(codigo or ""))


def _aplica_gate_juego(prod, codigo, clicables):
    """
    (bool, motivo) — si a ESTA pagina se le puede exigir que responda al input.

    MEDIDO 2026-08-29 sobre las 34 paginas reales de la biblioteca: con el gate
    aplicado a todo lo que "parece juego por codigo", reprobaba
    investment_dashboard_simulation_01 y _02 — dos dashboards que se animan
    solos, no tienen NI UN control clicable NI un addEventListener, y perdian
    por 0,0497 contra 0,0507 (un 2%, dentro del ruido de un diff de pixeles).
    Un dashboard animado que no escucha el teclado no "ignora" la entrada: no
    tiene por donde oirla, y reprobarlo es fabricar un rojo.

    Asi que el gate se aplica cuando (a) el producto SE LLAMA juego — entonces
    no poder jugarlo SI es un defecto — o (b) parece juego por su codigo Y
    ademas tiene por donde recibir entrada.
    """
    if juego_por_nombre(prod):
        return True, "el producto se llama juego"
    if not _RE_JUEGO_POR_CODIGO.search(codigo or ""):
        return False, "no parece un juego"
    if clicables > 0 or _RE_ESCUCHA_INPUT.search(codigo or ""):
        return True, "parece juego por codigo y tiene por donde recibir entrada"
    return False, ("se anima sola pero no escucha teclado ni raton: es una "
                   "animacion, no un juego que ignora la entrada")


def _contrato_web(prod, codigo):
    """
    Corre el contrato generico con Playwright. Devuelve un dict SIEMPRE, nunca lanza.

    Claves: {corrio, ok, detalle, controles, clicables, clics, cambio_dom,
             actividad_base, actividad_activo, responde_input, anima_sola,
             pixeles_ok, pixeles_detalle, errores_js}

    corrio=False (con motivo en `detalle`) cuando no hay Playwright o la pagina
    no se pudo abrir: eso NO reprueba a nadie — un chequeo que se salta en
    silencio es peor que no tenerlo, pero condenar por no poder mirar es peor aun.
    """
    from .program_creator import frames_gate as FG

    base = {"corrio": False, "ok": True, "detalle": "", "controles": 0, "clicables": 0,
            "clics": 0, "cambio_dom": False, "actividad_base": None,
            "actividad_activo": None, "responde_input": None, "anima_sola": False,
            "pixeles_ok": None, "pixeles_detalle": "", "errores_js": []}

    if os.environ.get("COGNIA_CONTRATO_WEB", "1").strip() == "0":
        base["detalle"] = "contrato desactivado (COGNIA_CONTRATO_WEB=0)"
        return base
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        base["detalle"] = (f"sin Playwright ({exc.__class__.__name__}): el contrato "
                           "generico NO se corrio (no reprueba)")
        return base

    url = Path(prod["entrypoint"]).resolve().as_uri()
    errores_js = []

    def _fase(page, con_input):
        """(frame_a, frame_b, clics, cambio_dom) de una fase completa."""
        page.goto(url, timeout=TIMEOUT_CONTRATO_SEG * 1000)
        page.wait_for_timeout(400)
        frame_a = page.screenshot(type="png")
        clics, cambio = 0, False
        if con_input:
            antes = page.evaluate("document.body ? document.body.innerHTML : ''")
            for el in page.query_selector_all(_SEL_CLICABLES)[:3]:
                try:
                    el.click(timeout=1500, force=True)
                    clics += 1
                    page.wait_for_timeout(150)
                    if page.evaluate("document.body ? document.body.innerHTML : ''") != antes:
                        cambio = True
                except Exception:
                    pass        # un control tapado no es un defecto de la pagina
            for tecla in _TECLAS_JUEGO:
                try:
                    page.keyboard.press(tecla)
                except Exception:
                    break
            page.wait_for_timeout(120)
            if not cambio and page.evaluate("document.body ? document.body.innerHTML : ''") != antes:
                cambio = True
        page.wait_for_timeout(ESPERA_FASE_MS)
        return frame_a, page.screenshot(type="png"), clics, cambio

    try:
        with sync_playwright() as pw:
            navegador = pw.chromium.launch()
            try:
                page = navegador.new_page(viewport={"width": 1000, "height": 700})
                page.on("pageerror", lambda e: errores_js.append(str(e)[:200]))
                page.set_default_timeout(TIMEOUT_CONTRATO_SEG * 1000)

                # Fase BASE: nadie toca nada. Es el BRAZO NULO de la pagina.
                a_base, b_base, _, _ = _fase(page, con_input=False)
                base["controles"] = int(page.evaluate(
                    f"document.querySelectorAll({_SEL_CONTROLES!r}).length") or 0)
                base["clicables"] = int(page.evaluate(
                    f"document.querySelectorAll({_SEL_CLICABLES!r}).length") or 0)

                # Fase ACTIVO: pagina recargada de cero y los mismos milisegundos,
                # con clics y teclas por medio. Unica diferencia: la entrada.
                a_act, b_act, clics, cambio = _fase(page, con_input=True)
            finally:
                navegador.close()
    except Exception as exc:
        base["detalle"] = (f"la pagina no se pudo pilotar ({exc.__class__.__name__}: "
                           f"{str(exc)[:120]}): contrato NO corrido (no reprueba)")
        return base

    act_base   = FG.fraccion_pixeles_distintos(a_base, b_base)
    act_activo = FG.fraccion_pixeles_distintos(a_act, b_act)
    pix_ok, pix_det, _medidas = FG.gate_capturas([a_base, b_base, a_act, b_act])

    anima_sola = act_base is not None and act_base > UMBRAL_ACTIVIDAD
    responde = bool(cambio) or (
        act_activo is not None and act_base is not None
        and act_activo > max(act_base * MARGEN_JUEGO, UMBRAL_ACTIVIDAD))

    base.update(corrio=True, clics=clics, cambio_dom=bool(cambio),
                actividad_base=act_base, actividad_activo=act_activo,
                responde_input=responde, anima_sola=anima_sola,
                pixeles_ok=pix_ok, pixeles_detalle=pix_det, errores_js=errores_js[:5])

    partes = [f"{base['clicables']} clicables de {base['controles']} controles",
              f"{clics} clicados", "DOM cambia" if cambio else "DOM no cambia",
              f"pixeles base {act_base if act_base is None else round(act_base, 4)} -> "
              f"activo {act_activo if act_activo is None else round(act_activo, 4)}"]

    # ── VEREDICTOS, los dos conservadores a proposito ──────────────────────────
    if not pix_ok:
        base.update(ok=False, detalle="GATE DE PIXELES: " + pix_det + " | " + "; ".join(partes))
        return base

    # (1) Contrato generico: reprueba solo cuando NADA de la pagina reacciona.
    # Los tres tienen que fallar a la vez (no cambia el DOM, no se anima, no se
    # mueve un pixel de mas con la entrada): con uno solo no se condena.
    if base["clicables"] > 0 and not cambio and not anima_sola and not responde:
        base.update(ok=False, detalle=(
            f"{base['clicables']} controles clicables y NINGUNO hace nada: "
            f"tras {clics} clics el innerHTML del body es identico, la pagina no "
            f"se anima sola y los pixeles no se movieron | " + "; ".join(partes)))
        return base

    # (2) Gate de JUEGO (patron AGF base/activo con margen 1.15): un juego que se
    # mueve IGUAL sin tocar nada no responde al input.
    aplica_juego, motivo_juego = _aplica_gate_juego(prod, codigo, base["clicables"])
    base["gate_juego"] = {"aplica": aplica_juego, "motivo": motivo_juego}
    if aplica_juego and anima_sola and not responde:
        base.update(ok=False, detalle=(
            f"NO RESPONDE AL INPUT: se anima sola ({round(act_base, 4)} de pixeles) "
            f"pero con clics y teclas se mueve igual "
            f"({act_activo if act_activo is None else round(act_activo, 4)}, hace falta "
            f"superar {round(act_base * MARGEN_JUEGO, 4)}) | " + "; ".join(partes)))
        return base

    base["detalle"] = "contrato generico OK | " + "; ".join(partes)
    return base


def _fases_html(prod):
    """
    Verificacion de una pagina. 'compila' es 'tiene estructura de documento' y
    'arranca' es lo que dice su nombre: la pagina se ABRE en un navegador de
    verdad (ademas del criterio estatico revisar_html de sandbox_runner) y PASA
    EL CONTRATO GENERICO ejecutable (clics, DOM, pixeles).
    """
    codigo = _leer(prod["entrypoint"])
    informe = revisar_html(codigo)
    nav_ok, nav_detalle, nav_errores = _mirar_en_navegador(
        codigo, dir_producto=Path(prod["entrypoint"]).parent,
        idea=prod.get("title") or prod.get("description") or "")
    # El contrato comparte interruptor con el navegador: apagar COGNIA_VERIFICAR_
    # NAVEGADOR tiene que apagar TODO lo que abre un navegador, o sellar la
    # biblioteca entera seguiria costando minutos por producto.
    if os.environ.get("COGNIA_VERIFICAR_NAVEGADOR", "1").strip() == "0":
        contrato = {"corrio": False, "ok": True,
                    "detalle": "contrato desactivado (COGNIA_VERIFICAR_NAVEGADOR=0)"}
    else:
        contrato = _contrato_web(prod, codigo)
    estructura = all(t in codigo.lower() for t in ("<html", "<head", "<body"))
    utiles = _lineas_utiles(codigo)
    return {
        "compila": {"ok": estructura, "compilan": 1 if estructura else 0, "total": 1,
                    "errores": [] if estructura else ["falta <html>/<head>/<body>"],
                    "detalle": "documento HTML completo" if estructura else "documento incompleto"},
        "importa": {"ok": None, "detalle": "n/a (no es Python)"},
        # 'arranca' exige LAS TRES: el criterio estatico, que la pagina abra sin
        # reventar en un navegador real, Y el contrato generico ejecutable (o que
        # el contrato no se haya podido correr, que no es lo mismo que fallar).
        "arranca": {"ok": bool(informe.success) and nav_ok and bool(contrato.get("ok", True)),
                    "rc": informe.exit_code, "timeout": False,
                    "stdout": informe.execution_output[:800],
                    "stderr": ("\n".join(nav_errores) + "\n" + informe.execution_errors)[:800]
                              if nav_errores else informe.execution_errors[:800],
                    "chars_stdout": len(informe.execution_output.strip()),
                    "navegador": {"ok": nav_ok, "detalle": nav_detalle, "errores_js": nav_errores},
                    "contrato": contrato,
                    "detalle": (("revisar_html OK" if informe.success
                                 else "revisar_html: " + (informe.execution_errors.splitlines() or [""])[0][:160])
                                + " | navegador: " + nav_detalle
                                + " | contrato: " + (contrato.get("detalle") or "sin detalle"))},
        "sin_stubs": {"ok": len(utiles) >= 20, "vacios": [] if len(utiles) >= 20 else [prod["entrypoint"]],
                      "funciones_huecas": [], "funciones": 0, "ratio_huecas": 0.0, "marcadores": 0,
                      "detalle": f"{len(utiles)} lineas utiles de HTML"},
    }


def probar_producto(prod, timeout_arranque=TIMEOUT_ARRANQUE_SEG,
                    timeout_import=TIMEOUT_IMPORT_SEG):
    """
    Corre las 4 fases sobre un producto y devuelve el resultado crudo.

    Para en el primer fallo DURO (compila, importa, arranca): si no compila no
    tiene sentido importarlo, y el resultado seria ruido. Las fases no corridas
    quedan con ok=None y detalle "no evaluado".

    `indeterminado` (clave nueva) NO es un fallo del producto: hoy solo lo pone
    el arranque cuando se le tecleo el guion entero y siguio pidiendo entrada.
    Se distingue de fallo_duro a proposito: un indeterminado no se manda a
    reparar (no hay nada medido que corregir) pero tampoco se sella "verificado".
    """
    res = {
        "id": prod["id"], "title": prod["title"], "lenguaje": prod["lenguaje"],
        "directorio": prod["directorio"], "entrypoint": prod["entrypoint"],
        "fases": {}, "fallo_duro": None, "indeterminado": None,
    }
    no_eval = {"ok": None, "detalle": "no evaluado (se corto antes)"}

    if prod["lenguaje"] == "vacio" or not prod["entrypoint"]:
        res["fallo_duro"] = "sin_codigo"
        for f in ("compila", "importa", "arranca", "sin_stubs"):
            res["fases"][f] = {"ok": False if f == "compila" else None,
                               "detalle": "la carpeta no tiene ningun .py ni .html"}
        return res

    if prod["lenguaje"] == "html":
        res["fases"] = _fases_html(prod)
        if not res["fases"]["compila"]["ok"]:
            res["fallo_duro"] = "compila"
        elif not res["fases"]["arranca"]["ok"]:
            res["fallo_duro"] = "arranca"
        return res

    res["fases"]["compila"] = _fase_compila(prod)
    if not res["fases"]["compila"]["ok"]:
        res["fallo_duro"] = "compila"
        res["fases"]["importa"] = dict(no_eval)
        res["fases"]["arranca"] = dict(no_eval)
        res["fases"]["sin_stubs"] = _fase_sin_stubs(prod)   # estatico y barato: se corre igual
        return res

    res["fases"]["importa"] = _fase_importa(prod, timeout_import)
    if not res["fases"]["importa"]["ok"]:
        res["fallo_duro"] = "importa"
        res["fases"]["arranca"] = dict(no_eval)
        res["fases"]["sin_stubs"] = _fase_sin_stubs(prod)
        return res

    guion, origen = guion_para(prod)
    res["fases"]["arranca"] = _fase_arranca(
        prod, timeout_arranque, guion=guion, origen_guion=origen,
        salida=salida_de_menu(_leer(prod["entrypoint"])))
    if res["fases"]["arranca"]["ok"] is False:
        res["fallo_duro"] = "arranca"
    elif res["fases"]["arranca"]["ok"] is None:
        res["indeterminado"] = "arranca"
    res["fases"]["sin_stubs"] = _fase_sin_stubs(prod)
    return res


# ── Evaluacion ─────────────────────────────────────────────────────────────────

def _palabras(texto):
    """Palabras significativas de una descripcion (>=4 letras, sin vacias)."""
    # [^\W\d_] = letra unicode (incluye las acentuadas de las descripciones en
    # espanol); \w sola dejaria pasar numeros y guiones bajos.
    tokens = re.findall(r"[^\W\d_]{4,}", (texto or "").lower(), re.UNICODE)
    return [t for t in tokens if t not in _VACIAS]


def _puntos_documentacion(prod):
    """1.0 por docstring o README; 0.5 por description.txt (lo escribe el pipeline solo)."""
    carpeta = Path(prod["directorio"])
    if prod["entrypoint"] and prod["lenguaje"] == "python":
        try:
            if (ast.get_docstring(ast.parse(_leer(prod["entrypoint"]))) or "").strip():
                return 1.0, "docstring de modulo en el entrypoint"
        except Exception:
            pass
    if prod["lenguaje"] == "html" and "<title" in _leer(prod["entrypoint"]).lower():
        return 0.5, "la pagina declara <title> pero no trae README"
    for nombre in ("README.md", "README.txt", "readme.md"):
        if (carpeta / nombre).is_file() and len(_leer(carpeta / nombre).strip()) > 30:
            return 1.0, f"tiene {nombre}"
    if len(_leer(carpeta / "description.txt").strip()) > 30:
        return 0.5, "solo description.txt (generado por el pipeline, no es doc del autor)"
    return 0.0, "sin documentacion"


def _puntos_descripcion(prod, resultado):
    """
    Cuanto de lo que PROMETE el index aparece de verdad en el codigo o su salida.

    Es un cotejo de palabras, no comprension: sirve para cazar el caso descarado
    (la descripcion habla de un secuenciador musical y el codigo no menciona ni
    una nota) y nada mas. Por eso vale 1 punto de 10.
    """
    claves = set(_palabras(prod.get("description")))
    if not claves:
        return 0.0, "sin descripcion contra la cual cotejar"
    texto = _leer(prod["entrypoint"]).lower()
    texto += (resultado["fases"].get("arranca", {}).get("stdout") or "").lower()
    hits = [k for k in claves if k in texto]
    frac = len(hits) / len(claves)
    if frac >= 0.5:
        return 1.0, f"cumple lo que promete ({len(hits)}/{len(claves)} palabras clave)"
    if frac >= 0.25:
        return 0.5, f"coincide a medias ({len(hits)}/{len(claves)} palabras clave)"
    return 0.0, f"el codigo no se parece a su descripcion ({len(hits)}/{len(claves)})"


def evaluar_producto(prod, resultado):
    """
    Nota 0-10 con criterios EXPLICITOS y su desglose. Nada de numero magico.

      compila (3)              — proporcional: 3 * (.py que compilan / total)
      arranca (3)              — corrio sin reventar (timeout de interactivo cuenta como si)
      sin_stubs (2)            — 2 sin senales de vacio, 1 si son leves, 0 si esta hueco
      documentacion (1)        — docstring/README (1) o solo description.txt (0.5)
      coincide_descripcion (1) — palabras clave de su description presentes en codigo/salida

    Los pesos siguen la regla del repo: "codigo que corre o no cuenta" — compilar
    y arrancar valen 6 de los 10 puntos; lo cosmetico pesa 2.
    """
    fases = resultado["fases"]
    desglose, motivos = {}, []

    comp = fases.get("compila", {})
    total = comp.get("total") or 0
    desglose["compila"] = round(3.0 * (comp.get("compilan", 0) / total), 2) if total else 0.0
    motivos.append(f"compila: {comp.get('detalle', 'no evaluado')}")

    arr = fases.get("arranca", {})
    if arr.get("ok"):
        desglose["arranca"] = 3.0
    elif arr.get("ok") is None and arr.get("indeterminado"):
        # INDETERMINADO: se le dio teclado y siguio pidiendo. No se le pueden dar
        # los 3 puntos de "arranca" (no lo sabemos) ni los 0 de "revienta" (no
        # revento). La mitad, y el motivo lo dice.
        desglose["arranca"] = 1.5
    else:
        desglose["arranca"] = 0.0
    motivos.append(f"arranca: {arr.get('detalle', 'no evaluado')}")

    stub = fases.get("sin_stubs", {})
    if stub.get("ok"):
        desglose["sin_stubs"] = 2.0
    elif stub.get("ok") is None:
        desglose["sin_stubs"] = 0.0
    elif not stub.get("vacios") and stub.get("ratio_huecas", 1.0) <= 0.4:
        desglose["sin_stubs"] = 1.0   # senales leves (TODOs o alguna funcion hueca)
    else:
        desglose["sin_stubs"] = 0.0
    motivos.append(f"sin_stubs: {stub.get('detalle', 'no evaluado')}")

    doc_p, doc_m = _puntos_documentacion(prod)
    desglose["documentacion"] = doc_p
    motivos.append(f"documentacion: {doc_m}")

    des_p, des_m = _puntos_descripcion(prod, resultado)
    desglose["coincide_descripcion"] = des_p
    motivos.append(f"descripcion: {des_m}")

    puntaje = round(min(sum(desglose.values()), 10.0), 2)
    return {
        "id": prod["id"], "title": prod["title"], "lenguaje": prod["lenguaje"],
        "directorio": prod["directorio"], "entrypoint": prod["entrypoint"],
        "puntaje": puntaje, "desglose": desglose, "motivos": motivos,
        "fallo_duro": resultado["fallo_duro"],
        "indeterminado": resultado.get("indeterminado"),
        "score_index": prod.get("score_index"),
    }


# ── Corrida completa ───────────────────────────────────────────────────────────

def probar_todos(limite=None, filtro=None, base=None, solo_codigo=False,
                 timeout_arranque=TIMEOUT_ARRANQUE_SEG, al_terminar_uno=None):
    """
    Prueba y evalua toda la biblioteca. Devuelve el reporte agregado.

    `filtro` es un substring (case-insensitive) contra id/title/carpeta.
    `solo_codigo` saca las 12 carpetas que solo tienen input_images/ (sobras del
    pipeline de assets, no productos); sirve para usar esto como compuerta.
    `al_terminar_uno(evaluacion)` se llama tras cada producto, para que el CLI
    imprima en vivo en vez de esperar al final.
    """
    productos = descubrir_productos(base)
    if solo_codigo:
        productos = [p for p in productos if p["lenguaje"] != "vacio"]
    if filtro:
        f = filtro.lower()
        productos = [p for p in productos
                     if f in p["id"].lower() or f in p["title"].lower()
                     or f in Path(p["directorio"]).name.lower()]
    if limite:
        productos = productos[:int(limite)]

    evaluaciones = []
    for prod in productos:
        resultado = probar_producto(prod, timeout_arranque=timeout_arranque)
        ev = evaluar_producto(prod, resultado)
        ev["resultado"] = resultado
        evaluaciones.append(ev)
        if al_terminar_uno:
            al_terminar_uno(ev)

    n = len(evaluaciones)
    compilan = sum(1 for e in evaluaciones if e["desglose"]["compila"] >= 3.0)
    arrancan = sum(1 for e in evaluaciones if e["desglose"]["arranca"] >= 3.0)
    sin_codigo = sum(1 for e in evaluaciones if e["fallo_duro"] == "sin_codigo")
    medio = round(sum(e["puntaje"] for e in evaluaciones) / n, 2) if n else 0.0

    ordenadas = sorted(evaluaciones, key=lambda e: e["puntaje"])
    def _resumen(e):
        if not e:
            return None
        motivo = next((m for m in e["motivos"] if m.startswith("arranca")), "")
        return {"id": e["id"], "puntaje": e["puntaje"], "lenguaje": e["lenguaje"],
                "motivo": e["motivos"][0] + " | " + motivo}

    # Los dos contadores del brazo B: sin ellos "de inicio a fin" seria una
    # afirmacion sin numero al lado. `no_reaccionan` NO baja la nota de nadie:
    # es el dato que hace visible cuantos productos ignoran lo que se les teclea.
    def _arr(e):
        return (e.get("resultado") or {}).get("fases", {}).get("arranca", {})
    no_reaccionan  = sum(1 for e in evaluaciones if _arr(e).get("no_reacciona") is True)
    indeterminados = sum(1 for e in evaluaciones if e.get("indeterminado"))
    con_guion      = sum(1 for e in evaluaciones if _arr(e).get("guion"))

    reporte = {
        "total": n,
        "compilan": compilan,
        "arrancan": arrancan,
        "sin_codigo": sin_codigo,
        "con_guion": con_guion,
        "no_reaccionan": no_reaccionan,
        "indeterminados": indeterminados,
        "puntaje_medio": medio,
        "por_lenguaje": {l: sum(1 for e in evaluaciones if e["lenguaje"] == l)
                         for l in sorted({e["lenguaje"] for e in evaluaciones})},
        "top": _resumen(ordenadas[-1] if ordenadas else None),
        "peor": _resumen(ordenadas[0] if ordenadas else None),
        "evaluaciones": evaluaciones,
    }
    return reporte


def slash_autoprueba(args="", base=None):
    """
    Cuerpo del comando /autoprueba del CLI (queda listo; el enganche lo hace el
    dueno en cli.py, que no se toca desde aca).

    args: un numero = limite de productos; cualquier otra palabra = filtro.
    Imprime el reporte y devuelve el dict por si el llamador quiere mas.
    """
    limite, filtro = None, None
    for token in (args or "").split():
        if token.isdigit():
            limite = int(token)
        else:
            filtro = token
    print(f"[autoprueba] probando productos generados"
          + (f" (limite {limite})" if limite else "")
          + (f" (filtro '{filtro}')" if filtro else "") + "...", flush=True)

    def _linea(ev):
        if ev["fallo_duro"]:
            marca = "FALLA"
        elif ev.get("indeterminado"):
            marca = "?   "
        else:
            marca = "OK  "
        print(f"  {marca} {ev['id'][:44]:<44} {ev['puntaje']:>5.1f}/10 ({ev['lenguaje']})"
              + (f" <- {ev['fallo_duro']}" if ev["fallo_duro"] else "")
              + (f" <- indeterminado en {ev['indeterminado']}"
                 if ev.get("indeterminado") else ""), flush=True)

    rep = probar_todos(limite=limite, filtro=filtro, base=base, al_terminar_uno=_linea)
    print(f"  --- {rep['arrancan']}/{rep['total']} arrancan | "
          f"{rep['compilan']}/{rep['total']} compilan | "
          f"media {rep['puntaje_medio']}/10", flush=True)
    print(f"  --- teclado: {rep['con_guion']} con guion | "
          f"{rep['no_reaccionan']} no usan el valor tecleado | "
          f"{rep['indeterminados']} indeterminados", flush=True)
    if rep["peor"]:
        print(f"  peor: {rep['peor']['id']} ({rep['peor']['puntaje']}/10) — "
              f"{rep['peor']['motivo'][:120]}", flush=True)
    return rep
