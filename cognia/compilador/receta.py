"""
cognia/compilador/receta.py
===========================
LA RECETA: como se da de alta un comando del CLI de Cognia, escrita para que
la ejecute una MAQUINA y no solo para que la lea un humano.

POR QUE EXISTE. El duenio pidio literalmente que "el proceso que hagas para
hacer las clases, ese mismo proceso de forma detallada, lo pongas en Cognia
para que ella misma haga sus propias herramientas". Esto es ese proceso. No
es documentacion: es el dato de entrada del compilador (`injertador.py` lee
SITIOS para saber que tocar, `evaluador.py` lee GUARDIANES para saber que
tiene que pasar, y `generador.py` mete RECETA_PROSA en el prompt del modelo).

DE DONDE SALE. De leer el repo entero el 2026-08-31 y de haber dado de alta
/ventana a mano el dia anterior: /ventana existe en EXACTAMENTE los 5 sitios
obligatorios y en ninguno mas, y los tres guardianes cazaron las dos veces
que me salte uno. O sea que la receta esta VERIFICADA por haberla ejecutado y
por haber fallado en ella.

EL PRINCIPIO QUE LA GOBIERNA. Un comando no esta entregado cuando el codigo
existe: esta entregado cuando tiene PUERTA VISIBLE (sale en /ayuda, esta
clasificado, se puede teclear) y los guardianes siguen verdes. Por eso los
5 sitios son obligatorios y no "recomendados": saltarse uno deja un comando
fantasma, que es peor que no tenerlo porque nadie sabe que esta ahi.
"""

from __future__ import annotations

import ast
import io
import re
from pathlib import Path

# Raiz del repo (este fichero vive en cognia/compilador/).
RAIZ = Path(__file__).resolve().parent.parent.parent

CLI = "cognia/cli.py"
VISIBILIDAD = "cognia/cli_visibilidad.py"
AYUDA = "cognia/harness/ayuda.py"


# ── Los 5 sitios obligatorios ────────────────────────────────────────────────
#
# `clave` es el identificador que usa el injertador; `ancla` es la marca de
# texto tras la cual insertar (elegida por ser estable: son lineas que no
# cambian de forma cuando el fichero crece).
SITIOS = (
    {
        "clave": "descripcion",
        "fichero": CLI,
        "obligatorio": True,
        "que": "Una linea en el dict _CMD_DESCRIPTIONS: la puerta visible.",
        "ancla": '    "/ventana":',
        "forma": '    "{cmd}":{relleno}"{descripcion}",',
        "guardian": "el catalogo se lee con ast: el valor tiene que ser un "
                    "literal constante (nada de f-strings ni concatenacion), "
                    "la clave no puede repetirse, y ninguna linea del dict "
                    "puede empezar por '}' en columna 0",
    },
    {
        "clave": "funcion",
        "fichero": CLI,
        "obligatorio": True,
        "que": "La funcion _slash_<nombre>(arg: str = '') -> None, a nivel de "
               "modulo y ANTES del bucle del REPL.",
        "ancla": "def _slash_horizonte(",
        "forma": "def _slash_{nombre}(arg: str = \"\") -> None:",
        "guardian": "la funcion NUNCA puede lanzar: el import del modulo va en "
                    "try/except que llama a _aviso_degradado y hace return, "
                    "porque una excepcion aqui se lleva por delante el REPL",
    },
    {
        "clave": "despacho",
        "fichero": CLI,
        "obligatorio": True,
        "que": "La rama elif del REPL que encamina el comando.",
        "ancla": '            elif raw == "/ventana" or raw.startswith("/ventana "):',
        "forma": ('            elif raw == "{cmd}" or raw.startswith("{cmd} "):\n'
                  '                _slash_{nombre}(\n'
                  '                    raw[len("{cmd} "):] if raw.startswith("{cmd} ") else "")'),
        "guardian": "un SOLO handler por comando; tiene que quedar antes del "
                    "fallback 'Comando desconocido'; y si el nombre es prefijo "
                    "de otro ya existente, va ANTES que el corto o se lo come",
    },
    {
        "clave": "cubo",
        "fichero": VISIBILIDAD,
        "obligatorio": True,
        "que": "El comando en EXACTAMENTE UNO de los frozensets NUCLEO / "
               "AVANZADO / LABORATORIO.",
        "ancla": '    "/ventana", "/ver-contexto",',
        "forma": '"{cmd}"',
        "guardian": "la union de los tres cubos tiene que ser EXACTAMENTE el "
                    "catalogo; un comando sin cubo pone roja la suite el mismo "
                    "dia (test_los_tres_cubos_particionan_el_catalogo)",
    },
    {
        "clave": "categoria",
        "fichero": AYUDA,
        "obligatorio": True,
        "que": "El comando como patron EXACTO en la tupla de UNA categoria de "
               "CATEGORIAS.",
        "ancla": '        "/capacidades", "/activar", "/vram", "/ventana",',
        "forma": '"{cmd}"',
        "guardian": "el patron no puede estar en dos categorias; ninguna "
                    "categoria puede pasar de TOPE_CATEGORIA (25); ningun "
                    "comando puede acabar en 'Otros'",
    },
)

# Sitios que NO son obligatorios. Se listan para que el generador sepa que
# existen y NO para que los use por defecto: /ventana no usa ninguno.
SITIOS_OPCIONALES = (
    ("_CMD_DETAILS", CLI, "ficha larga que sale con '/ayuda /xxx'"),
    ("_CONFIG_DEFAULTS", CLI, "OBLIGATORIO si el comando escribe config: sin "
                              "darla de alta, la clave no sale en /config ver"),
    ("_SLASH_AL_CHAT_REMOTO", CLI, "solo si es informativo, sincrono, corto y "
                                   "no pregunta s/n"),
    ("_SLASH_CON_MENCIONES", CLI, "solo si el argumento admite @ficheros"),
    ("_CANON_COMANDOS_NEUTROS", CLI, "solo si debe correr con un bot abierto"),
)


# ── Las trampas (cada una costo una suite roja de verdad) ────────────────────
TRAMPAS = (
    "La DESCRIPCION decide la categoria si no la das de alta a mano. "
    "harness/ayuda._REGLAS_DESC manda a 'Agente y tareas' cualquier "
    "descripcion cuya cabeza lleve 'tarea', 'agente', 'plan ' o 'paso'. Esa "
    "categoria esta LLENA (25/25): una palabra mal elegida en la primera "
    "frase pone roja la suite sin tocar nada mas.",

    "Dos categorias estan a 25/25 HOY ('Agente y tareas' y 'Sistema y "
    "diagnostico'). Meter ahi un comando revienta el guardian de desbordes. "
    "El compilador tiene que ELEGIR una categoria con hueco, y comprobarlo "
    "ejecutando, no suponiendo.",

    "'Consola y arnes' tiene la cuenta EXACTA cableada en un test "
    "(test_harness_ayuda: una tupla de 12 nombres y un assert de longitud). "
    "Elegir esa categoria obliga a tocar ese test. Evitala.",

    "El filtro de visibilidad JAMAS entra en el if/elif del despacho. "
    "'Ocultar no es desactivar': un comando de LABORATORIO tecleado a mano "
    "tiene que seguir funcionando. Hay dos tests que lo comprueban por regex "
    "sobre el fuente.",

    "El nombre no puede colisionar por PREFIJO con un comando ya despachado. "
    "Si /xxx-yyy extiende a /xxx, su rama va ANTES en la cadena elif o el "
    "prefijo comun se la come.",

    "Todo lo que se inserta en _CMD_DESCRIPTIONS se lee con ast.literal_eval: "
    "un valor que no sea un literal constante rompe TRES tests a la vez.",
)


# ── Los guardianes: lo que hay que pasar para poder decir que esta hecho ─────
GUARDIANES = (
    "tests/test_cli_visibilidad.py",
    "tests/test_harness_ayuda.py",
    "tests/test_cli_bots.py",
    "tests/test_cli_comandos_tapados.py",
)


RECETA_PROSA = """\
COMO SE DA DE ALTA UN COMANDO EN EL CLI DE COGNIA (receta verificada)

Un comando NO esta entregado cuando su codigo existe. Esta entregado cuando
tiene puerta visible y los guardianes siguen verdes. Son CINCO sitios, todos
obligatorios:

1. cognia/cli.py, dict _CMD_DESCRIPTIONS -- una linea:
       "/xxx":  "<frase corta que explica el comando>. Uso: /xxx [sub1 | sub2]",
   El valor tiene que ser un literal constante. La PRIMERA FRASE decide la
   categoria si no la declaras: no uses ahi 'tarea', 'agente', 'plan', 'paso'.

2. cognia/cli.py, la funcion `def _slash_xxx(arg: str = "") -> None:`
   Patron obligatorio: docstring que diga que hace y cual es el punto de
   extension; import perezoso en try/except que degrada con _aviso_degradado
   y hace return (la funcion NUNCA puede lanzar: se lleva el REPL); luego
   `arg = (arg or "").strip()` y una rama por subcomando; al final, el estado
   por defecto. Si guarda config: _load_config() / cfg[k]=v / _save_config(cfg),
   y si siembra una env var, _marcar_env_sembrada() detras o /config-resuelta
   mentira sobre el origen del valor.

3. cognia/cli.py, la rama del despachador del REPL:
       elif raw == "/xxx" or raw.startswith("/xxx "):
           _slash_xxx(raw[len("/xxx "):] if raw.startswith("/xxx ") else "")
   Un solo handler por comando, y antes del fallback de 'Comando desconocido'.

4. cognia/cli_visibilidad.py -- el comando en EXACTAMENTE UN cubo:
   NUCLEO (uso diario), AVANZADO (util pero de nicho), LABORATORIO
   (experimento). La union de los tres tiene que ser el catalogo entero.

5. cognia/harness/ayuda.py -- el comando como patron EXACTO en UNA categoria
   de CATEGORIAS, elegida entre las que TIENEN HUECO (tope 25 por categoria).

Y luego, siempre: correr los guardianes. Si alguno se pone rojo, el comando
no esta puesto -- esta a medias, que es el peor estado posible.
"""


# ── Consultas EN VIVO sobre el repo (no supongas: mide) ──────────────────────

def _fuente(rel: str) -> str:
    return io.open(RAIZ / rel, encoding="utf-8", errors="replace").read()


def catalogo() -> dict:
    """_CMD_DESCRIPTIONS leido del FUENTE con ast, como hacen los guardianes.

    Se lee del fuente y no importando cli.py a proposito: importar el CLI
    arrastra medio producto (y sus efectos de arranque), y ademas es
    exactamente lo que hacen los tests que hay que pasar. Medir con la misma
    regla con la que te van a examinar.
    """
    src = _fuente(CLI)
    arbol = ast.parse(src)
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Assign):
            for t in nodo.targets:
                if isinstance(t, ast.Name) and t.id == "_CMD_DESCRIPTIONS":
                    try:
                        return ast.literal_eval(nodo.value)
                    except ValueError:
                        return {}
    return {}


def ocupacion_categorias() -> dict:
    """{categoria: cuantos comandos tiene} AHORA MISMO, con el clasificador
    real de harness/ayuda. Es lo que decide si una categoria admite uno mas."""
    from cognia.harness import ayuda as _ay
    cuenta = {c: 0 for c in _ay.CATEGORIAS}
    cuenta["Otros"] = 0
    for cmd in catalogo():
        cat = _ay.clasificar(cmd, "") if hasattr(_ay, "clasificar") else "Otros"
        cuenta[cat] = cuenta.get(cat, 0) + 1
    return cuenta


def categorias_con_hueco(margen: int = 1) -> list:
    """Categorias donde CABE un comando mas, de la mas vacia a la mas llena.

    Se excluye 'Consola y arnes' aunque tenga sitio: su cuenta esta cableada
    en un test con una tupla literal de nombres, asi que meter uno mas obliga
    a editar ese test -- y el compilador no puede tocar los tests que lo
    examinan sin convertir el examen en una formalidad.
    """
    from cognia.harness import ayuda as _ay
    tope = getattr(_ay, "TOPE_CATEGORIA", 25)
    ocup = ocupacion_categorias()
    # 'Otros' NO es una categoria donde meter nada: es el cajon de lo NO
    # clasificado, y hay un guardian que exige que este VACIO. Salia la
    # primera de la lista por tener 25 huecos, o sea que el compilador habria
    # elegido justo la unica opcion que pone la suite roja.
    libres = [(n, tope - c) for n, c in ocup.items()
              if n in _ay.CATEGORIAS and n not in ("Consola y arnes", "Otros")
              and (tope - c) >= margen]
    libres.sort(key=lambda x: -x[1])
    return [n for n, _ in libres]


def cubos() -> dict:
    """{'NUCLEO': set, 'AVANZADO': set, 'LABORATORIO': set} del fuente."""
    src = _fuente(VISIBILIDAD)
    arbol = ast.parse(src)
    fuera = {}
    # Los cubos estan ANOTADOS ('NUCLEO: frozenset = frozenset({...})'), asi
    # que son AnnAssign y no Assign. Mirar solo Assign devolvia {} en silencio
    # -- y un {} aqui hace que 'sin_clasificar' salga vacio y que el compilador
    # crea que ya clasifico el comando cuando no ha clasificado nada.
    for nodo in ast.walk(arbol):
        destinos = []
        if isinstance(nodo, ast.Assign):
            destinos = [t for t in nodo.targets if isinstance(t, ast.Name)]
        elif isinstance(nodo, ast.AnnAssign) and isinstance(nodo.target, ast.Name):
            destinos = [nodo.target]
        for t in destinos:
            if t.id not in ("NUCLEO", "AVANZADO", "LABORATORIO"):
                continue
            # `frozenset({...})` es una LLAMADA, no un literal: literal_eval
            # sobre ella lanza y devolvia el set vacio. Hay que desenvolver el
            # argumento. El sintoma era mudo y peligroso: con los tres cubos a
            # cero, 'sin_clasificar' listaba los 283 comandos y el compilador
            # habria concluido que el catalogo entero esta sin clasificar.
            valor = nodo.value
            if (isinstance(valor, ast.Call) and isinstance(valor.func, ast.Name)
                    and valor.func.id in ("frozenset", "set") and valor.args):
                valor = valor.args[0]
            try:
                fuera[t.id] = set(ast.literal_eval(valor))
            except (ValueError, TypeError):
                fuera[t.id] = set()
    return fuera


_RE_NOMBRE = re.compile(r"^/[a-z][a-z0-9-]{1,28}$")


def validar_nombre(cmd: str) -> tuple:
    """(ok, motivo). Comprueba forma, colision exacta y colision por PREFIJO.

    La colision por prefijo es la que muerde: /clase y /clases se despachan
    con `raw.startswith(cmd + ' ')`, asi que el corto se come al largo si va
    antes en la cadena. Mejor rechazar el nombre que ordenar ramas a ciegas.
    """
    cmd = (cmd or "").strip()
    # No se normaliza a minusculas en silencio: el nombre que el duenio teclea
    # tiene que ser el que se registra, y devolver ok para '/Compilar' cuando
    # lo que se iba a escribir es '/compilar' es mentirle al llamador.
    if not _RE_NOMBRE.match(cmd):
        return False, ("nombre invalido: tiene que ser /minusculas-con-guiones, "
                       "entre 2 y 29 caracteres (recibido: %r)" % cmd)
    cat = catalogo()
    if cmd in cat:
        return False, "ya existe un comando %s" % cmd
    # Colision REAL de despacho. El elif usa `raw.startswith(otro + " ")`, con
    # ESPACIO, asi que /grabar-clase NO lo captura /grabar: '/grabar-clase x'
    # empieza por '/grabar-', no por '/grabar '. Solo hay colision cuando un
    # nombre es prefijo del otro Y el mas corto se despacha sin ese espacio.
    src = _fuente(CLI)
    for otro in cat:
        if not (cmd.startswith(otro) and cmd != otro):
            continue
        if re.search(r'raw\.startswith\("%s"\)' % re.escape(otro), src):
            return True, ("cuidado: %s lo captura %s, que se despacha por "
                          "prefijo SIN espacio; su rama tiene que ir ANTES"
                          % (cmd, otro))
    return True, ""


def estado() -> dict:
    """Foto para /compilar estado: lo que la receta VE del repo ahora mismo."""
    cub = cubos()
    return {
        "comandos": len(catalogo()),
        "cubos": {k: len(v) for k, v in cub.items()},
        "sin_clasificar": sorted(set(catalogo())
                                 - set().union(*cub.values()) if cub else set()),
        "categorias_con_hueco": categorias_con_hueco(),
        "ocupacion": ocupacion_categorias(),
        "sitios_obligatorios": [s["clave"] for s in SITIOS],
        "guardianes": list(GUARDIANES),
    }
