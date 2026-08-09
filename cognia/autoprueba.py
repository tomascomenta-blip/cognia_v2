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
  3. arranca   — ejecuta el entrypoint en SUBPROCESO, cwd en su carpeta, stdin cerrado
  4. sin_stubs — heuristica de vacio (archivos de <5 lineas utiles, funciones pass/TODO)

DOS TRAMPAS QUE YA NOS MORDIERON Y ESTAN CONTEMPLADAS:
  - Un juego interactivo se queda esperando input(): el TIMEOUT NO es fallo, es
    la prueba de que arranco. Solo un Traceback o un error de sintaxis lo son.
  - Un SyntaxError del script principal NO imprime "Traceback": Python lo reporta
    con "  File ..." + "SyntaxError:". Buscar solo "Traceback" da falso verde.
    Por eso _hay_error_python() busca tambien SyntaxError/IndentationError/TabError.

NADA de codigo generado se importa en el proceso principal: es codigo no
confiable. Todo va a subproceso con timeout.

Las paginas HTML (21 de los 56 productos) no se ejecutan: se revisan con
revisar_html() de sandbox_runner, que es el criterio que ya usa el repo.
"""

import ast
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

    productos = []
    for carpeta in sorted(p for p in base.iterdir() if p.is_dir()):
        archivos_py   = sorted(carpeta.glob("*.py"))
        archivos_html = sorted(carpeta.glob("*.html"))
        info = meta.get(carpeta.name, {})

        if archivos_py:
            lenguaje, entrypoint = "python", _elegir_entrypoint(carpeta, archivos_py)
        elif archivos_html:
            lenguaje, entrypoint = "html", archivos_html[0]
        else:
            lenguaje, entrypoint = "vacio", None

        descripcion = (info.get("description")
                       or _leer(carpeta / "description.txt").strip())
        productos.append({
            "id":          info.get("id") or carpeta.name,
            "title":       info.get("title") or carpeta.name.replace("_", " "),
            "description": descripcion,
            "directorio":  str(carpeta),
            "lenguaje":    lenguaje,
            "entrypoint":  str(entrypoint) if entrypoint else None,
            "archivos_py": [str(p) for p in archivos_py],
            "en_index":    carpeta.name in meta,
            "score_index": info.get("total_score"),
        })

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


def _correr(argv, cwd, timeout):
    """Corre argv en subproceso con stdin cerrado. Devuelve (rc, out, err, timeout?)."""
    with tempfile.TemporaryDirectory(prefix="autoprueba_") as tmp:
        try:
            proc = subprocess.run(
                argv, cwd=cwd, capture_output=True, text=True, timeout=timeout,
                stdin=subprocess.DEVNULL, env=_entorno_subproceso(tmp),
                errors="replace",
            )
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


def _fase_arranca(prod, timeout):
    """
    Ejecuta el entrypoint en su propia carpeta, stdin cerrado, timeout corto.

    REGLA CLAVE: timeout == arranco bien (juego interactivo o bucle de render).
    Traceback / SyntaxError / IndentationError == fallo, aunque el rc sea 0.
    Y un EOFError por stdin cerrado tampoco cuenta como fallo del producto: es
    culpa de la prueba, que no le da teclado a un programa que pide input().
    """
    rc, out, err, expiro = _correr(
        [sys.executable, "-s", prod["entrypoint"]],
        cwd=prod["directorio"], timeout=timeout)
    salida = {"rc": rc, "timeout": expiro,
              "stdout": out[:800], "stderr": err[:800],
              "chars_stdout": len(out.strip())}

    if expiro:
        salida.update(ok=True, detalle=f"timeout {timeout}s sin reventar = arranco "
                                       f"(interactivo/bucle), {len(out.strip())} chars de salida")
        return salida
    if _es_falta_de_teclado(err):
        salida.update(ok=True, detalle="pidio input() y stdin esta cerrado (EOFError) = arranco")
        return salida
    firma = _hay_error_python(err)
    if firma:
        ultima = next((l for l in reversed(err.splitlines()) if l.strip()), "")
        salida.update(ok=False, detalle=f"{firma} -> {ultima.strip()[:160]}")
        return salida
    if rc != 0:
        salida.update(ok=False, detalle=f"exit {rc}")
        return salida
    salida.update(ok=True, detalle=f"exit 0, {len(out.strip())} chars de salida")
    return salida


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
    try:
        from .program_creator.arbitro_visual import (
            arbitrar_desde_informe, vlm_disponible)
        vivo, motivo = vlm_disponible()
        if not vivo:
            return f" | VLM: NO juzgo ({motivo})"
        fallo = arbitrar_desde_informe(idea or "pagina web", informe)
        if not fallo:
            return " | VLM: sin veredicto"
        defectos = fallo.get("defectos") or []
        return (f" | VLM: {fallo.get('nota', '?')}/10 {fallo.get('veredicto', '')}"
                + (f" ({len(defectos)} defectos visuales)" if defectos else ""))
    except Exception as exc:
        return f" | VLM: error al mirar ({exc.__class__.__name__})"


def _fases_html(prod):
    """
    Verificacion de una pagina. 'compila' es 'tiene estructura de documento' y
    'arranca' es lo que dice su nombre: la pagina se ABRE en un navegador de
    verdad (ademas del criterio estatico revisar_html de sandbox_runner).
    """
    codigo = _leer(prod["entrypoint"])
    informe = revisar_html(codigo)
    nav_ok, nav_detalle, nav_errores = _mirar_en_navegador(
        codigo, dir_producto=Path(prod["entrypoint"]).parent,
        idea=prod.get("title") or prod.get("description") or "")
    estructura = all(t in codigo.lower() for t in ("<html", "<head", "<body"))
    utiles = _lineas_utiles(codigo)
    return {
        "compila": {"ok": estructura, "compilan": 1 if estructura else 0, "total": 1,
                    "errores": [] if estructura else ["falta <html>/<head>/<body>"],
                    "detalle": "documento HTML completo" if estructura else "documento incompleto"},
        "importa": {"ok": None, "detalle": "n/a (no es Python)"},
        # 'arranca' exige LAS DOS: el criterio estatico Y que la pagina abra sin
        # reventar en un navegador real. Basta que una falle para no verificarla.
        "arranca": {"ok": bool(informe.success) and nav_ok, "rc": informe.exit_code, "timeout": False,
                    "stdout": informe.execution_output[:800],
                    "stderr": ("\n".join(nav_errores) + "\n" + informe.execution_errors)[:800]
                              if nav_errores else informe.execution_errors[:800],
                    "chars_stdout": len(informe.execution_output.strip()),
                    "navegador": {"ok": nav_ok, "detalle": nav_detalle, "errores_js": nav_errores},
                    "detalle": (("revisar_html OK" if informe.success
                                 else "revisar_html: " + (informe.execution_errors.splitlines() or [""])[0][:160])
                                + " | navegador: " + nav_detalle)},
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
    """
    res = {
        "id": prod["id"], "title": prod["title"], "lenguaje": prod["lenguaje"],
        "directorio": prod["directorio"], "entrypoint": prod["entrypoint"],
        "fases": {}, "fallo_duro": None,
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

    res["fases"]["arranca"] = _fase_arranca(prod, timeout_arranque)
    if not res["fases"]["arranca"]["ok"]:
        res["fallo_duro"] = "arranca"
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
    desglose["arranca"] = 3.0 if arr.get("ok") else 0.0
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

    reporte = {
        "total": n,
        "compilan": compilan,
        "arrancan": arrancan,
        "sin_codigo": sin_codigo,
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
        marca = "OK  " if ev["fallo_duro"] is None else "FALLA"
        print(f"  {marca} {ev['id'][:44]:<44} {ev['puntaje']:>5.1f}/10 ({ev['lenguaje']})"
              + (f" <- {ev['fallo_duro']}" if ev["fallo_duro"] else ""), flush=True)

    rep = probar_todos(limite=limite, filtro=filtro, base=base, al_terminar_uno=_linea)
    print(f"  --- {rep['arrancan']}/{rep['total']} arrancan | "
          f"{rep['compilan']}/{rep['total']} compilan | "
          f"media {rep['puntaje_medio']}/10", flush=True)
    if rep["peor"]:
        print(f"  peor: {rep['peor']['id']} ({rep['peor']['puntaje']}/10) — "
              f"{rep['peor']['motivo'][:120]}", flush=True)
    return rep
