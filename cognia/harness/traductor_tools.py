# -*- coding: utf-8 -*-
"""Cuando el modelo inventa el nombre de una herramienta, traducirlo en vez de castigarlo.

POR QUE (2026-08-13): la tabla `wanted_tools` de este repo tiene 41 nombres que
el modelo pidio y no existen. El campeon es `crear_archivo`, **42 veces**, con
argumentos asi:

    crear_archivo   "nota1.txt | Contenido del archivo 1 sobre planetas..."

Es decir: el modelo sabia la tarea, sabia los argumentos y hasta el formato
exacto del protocolo (`ruta | contenido`) — solo erro el NOMBRE. Lo que recibia
a cambio era `ERROR: herramienta 'crear_archivo' no existe. Validas: <las 54>`:
un volcado enorme en el peor momento, y encima contradiciendo lo que este mismo
repo tiene medido (46 tools en el catalogo bajan el camino feliz de 4,25/5 a
2,5/5). Se le castigaba con mas ruido justo cuando estaba perdido.

QUE HACE: mapea el nombre inventado al real por tres vias, de mas fiable a menos:
  1. ALIAS explicitos, escritos a partir de los nombres REALES de wanted_tools.
  2. Parecido literal del nombre (difflib) — caza typos y variaciones morfologicas.
  3. Busqueda semantica sobre las descripciones del registry (BM25 de
     cognia/harness/registro_dinamico.py) — caza el caso "querian esto pero lo
     llaman de otra forma".

QUE NO HACE: **no ejecuta la traduccion por su cuenta**. Devuelve una sugerencia
para que el mensaje de error diga "no existe X; querias Y — llamala asi". Ejecutar
lo que el harness ADIVINA que el modelo queria es un tiro en el pie: si la
adivinanza falla, se escribe un fichero que nadie pidio. El modelo reintenta con
el nombre bueno en el paso siguiente, que cuesta un paso y es reversible.

DELIBERADAMENTE SIN MODELO: traducir `crear_archivo` -> `escribir_archivo` es
comparar cadenas. Meter un LLM chico aqui anadiria latencia, VRAM y un punto de
fallo no determinista a un problema que difflib resuelve exacto.
"""

from __future__ import annotations

import difflib

# Alias observados EN PRODUCCION (tabla wanted_tools, 2026-08-13). No son
# inventados: cada uno es un nombre que el modelo pidio de verdad.
ALIAS = {
    "crear_archivo": "escribir_archivo",        # 42 hits
    "crear_fichero": "escribir_archivo",
    "nuevo_archivo": "escribir_archivo",
    "guardar_archivo": "escribir_archivo",
    "validar_python": "py_validar",
    "verificar_python": "py_validar",
    "validar_json": "json_validar",
    "verificar_existencia": "listar",
    "existe_archivo": "listar",
    "screenshot": "pantalla_captura",
    "captura_pantalla": "pantalla_captura",
    "instalar": "ejecutar",
    "instalar_pip_modulo": "ejecutar",
    "pip_install": "ejecutar",
    "correr_tests": "tests",
    "ejecutar_tests": "tests",
    "run_tests": "tests",
    "leer_fichero": "leer_archivo",
    "abrir_archivo": "leer_archivo",
    "modificar_archivo": "editar_archivo",
    "reemplazar_en_archivo": "editar_archivo",
    "eliminar_archivo": "borrar_archivo",
    "buscar_archivo": "buscar",
    "buscar_texto": "buscar",
    "shell": "ejecutar",
    "bash": "ejecutar",
    "cmd": "ejecutar",
    "terminal": "ejecutar",
}

# Umbral de difflib. 0.72 sale de exigir que 'crear_archivo'/'escribir_archivo'
# NO pase por parecido literal (0.69: comparten el sufijo pero no la raiz) y que
# 'leer_archivos'/'leer_archivo' si (0.96). O sea: el parecido literal solo caza
# typos y plurales; el resto lo tiene que ganar un alias o la semantica.
UMBRAL_LITERAL = 0.72
MAX_SUGERENCIAS = 3


def traducir(nombre: str, disponibles) -> str:
    """El nombre real que el modelo probablemente queria, o '' si no hay uno claro.

    `disponibles` son las herramientas que el modelo PUEDE llamar ahora mismo:
    sugerirle una que esta apagada por su flag seria mandarlo a otro error.
    """
    if not nombre:
        return ""
    disponibles = set(disponibles or ())
    clave = nombre.strip().lower()
    if clave in disponibles:
        return ""                      # existe: no hay nada que traducir
    alias = ALIAS.get(clave)
    if alias and alias in disponibles:
        return alias
    cercanos = difflib.get_close_matches(clave, sorted(disponibles), n=1,
                                         cutoff=UMBRAL_LITERAL)
    return cercanos[0] if cercanos else ""


def parecidas(nombre: str, disponibles, catalogo=None, limite: int = MAX_SUGERENCIAS) -> list:
    """Las herramientas mas plausibles para lo que el modelo pedia.

    Primero por parecido de NOMBRE; si el catalogo trae descripciones, se
    completa con busqueda semantica sobre ellas (el caso "existe pero se llama
    de otra forma", que el parecido literal no puede ver).
    """
    disponibles = [d for d in (disponibles or ())]
    if not nombre or not disponibles:
        return []
    clave = nombre.strip().lower()
    # cutoff 0.62 y no 0.5: con 0.5 sobre las 54 tools, 'screenshot' sacaba
    # 'buscar_en_repo'. Una sugerencia irrelevante es peor que ninguna — manda
    # al modelo a probar una herramienta que no hace lo que necesita.
    salida = difflib.get_close_matches(clave, sorted(disponibles), n=limite,
                                       cutoff=0.62)
    if len(salida) < limite and catalogo:
        try:
            from cognia.harness import registro_dinamico as rd
            visibles = [e for e in catalogo if e.get("nombre") in set(disponibles)]
            if visibles:
                indice = rd.indexar(visibles)
                consulta = clave.replace("_", " ")
                for cand, score, _desc in rd.buscar(indice, consulta,
                                                    limite=limite * 2):
                    # Umbral medido: una consulta que SI casa da ~2,9 ('guardar
                    # texto en un fichero' -> escribir_archivo); por debajo de 1
                    # es ruido de BM25 sobre un termino que no esta en ninguna
                    # descripcion (el catalogo esta en espanol y el modelo a
                    # veces inventa el nombre en ingles).
                    if score < 1.0:
                        break
                    if cand not in salida:
                        salida.append(cand)
                    if len(salida) >= limite:
                        break
        except Exception:
            pass
    return salida[:limite]


def _alias_apagado(nombre: str):
    """(tool, flag) si el alias apunta a una tool registrada pero opt-in apagada.

    Sin esto, `screenshot` acababa sugiriendo la tercera cosa mas parecida del
    catalogo — cuando la respuesta correcta es "existe, se llama
    pantalla_captura, y esta apagada".
    """
    destino = ALIAS.get((nombre or "").strip().lower())
    if not destino:
        return None
    try:
        from cognia.agent.tools import TOOLS, flag_de_optin
        if destino in TOOLS:
            flag = flag_de_optin(destino)
            if flag:
                return destino, flag
    except Exception:
        pass
    return None


def mensaje_error(nombre: str, disponibles, catalogo=None) -> str:
    """El ERROR que ve el modelo cuando pide una herramienta que no existe.

    Sustituye al volcado del catalogo entero. Tres formas, de mejor a peor:
      - hay traduccion clara  -> se le da el nombre bueno y que reintente
      - hay candidatas        -> se le dan 3, no 54
      - no hay nada parecido  -> se le dice que no existe, sin lista
    """
    equivalente = traducir(nombre, disponibles)
    if equivalente:
        return (f"ERROR: '{nombre}' no existe. La que hace eso se llama "
                f"'{equivalente}': repeti la llamada con ese nombre y los "
                f"mismos argumentos.")
    # El alias apunta a una tool REAL pero apagada por su flag ('screenshot' ->
    # 'pantalla_captura'). Decirselo vale mucho mas que ofrecerle la tercera
    # cosa mas parecida del catalogo: la capacidad existe, solo esta off.
    apagada = _alias_apagado(nombre)
    if apagada:
        tool, flag = apagada
        return (f"ERROR: '{nombre}' no existe con ese nombre. Lo que buscas es "
                f"'{tool}', que SI existe pero esta DESHABILITADA — se activa "
                f"con {flag}=1. Avisale al usuario en vez de buscar un rodeo.")
    candidatas = parecidas(nombre, disponibles, catalogo)
    if candidatas:
        return (f"ERROR: '{nombre}' no existe. Las mas parecidas que SI tenes: "
                f"{', '.join(candidatas)}. Si ninguna sirve, resolvelo con las "
                f"herramientas de tu lista.")
    return (f"ERROR: '{nombre}' no existe y no hay ninguna parecida. Usa una de "
            f"las de tu lista o cierra explicando que te falta.")
