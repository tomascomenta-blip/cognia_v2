# -*- coding: utf-8 -*-
"""Verificacion automatica DESPUES de cada edicion (auto-lint + auto-test de Aider/OpenHands).

Motivacion (2026-08-12): el repo ya tiene las dos piezas sueltas — la tool `tests`
(pytest sobre una ruta) y `py_validar` (sintaxis de un .py) — pero NADA las dispara.
Hoy la unica realimentacion es REACTIVA: `agent/stepwise.classify_exec_error` clasifica
el fallo *si* el modelo se acordo de correr los tests. Un modelo cuantizado chico casi
nunca se acuerda: escribe el fichero, lee "OK (2 bloques)" y sigue construyendo encima
de un fichero que ni siquiera parsea. Este modulo es el lazo que falta: tras escribir,
el HARNESS comprueba y devuelve el error real como texto de RESULTADO, sin gastar un
turno del modelo en pedirlo. Es la funcionalidad insignia de Aider (auto-lint/auto-test
tras cada edicion) y de OpenHands, y convierte al agente de "escribe y espera" en
"escribe y comprueba".

API para el integrador (el cableado al CLI lo hace otro; este modulo es autocontenido):

    from cognia.harness.verificacion import verificar_edicion, texto_resultado

    # justo despues de que escribir_archivo/editar_archivo persista `contenido`:
    v = verificar_edicion(ruta, contenido, raiz=Path.cwd())
    if not v["sintaxis_ok"] or v["tests_ok"] is False:
        history.append(texto_resultado(v))   # el error REAL es el siguiente prompt

`verificar_edicion` devuelve un dict plano (sintaxis_ok, mensaje, tests_encontrados,
tests_ok, resumen, salida_recortada, texto) y NUNCA lanza: un harness que revienta es
peor que uno que no corre.

Limites declarados (a proposito, no son deuda oculta):
  - Sintaxis: solo Python (.py/.pyi, via compile()) y JSON (.json, via json.loads).
    Cualquier otra extension devuelve ok=True con un mensaje que lo dice — este modulo
    NO trae linters externos (ruff/eslint) ni los invoca; declarar "OK" seria mentir y
    devolver "ERROR" en un .md frenaria al agente por nada.
  - `compile()` (no `ast.parse`) porque tambien caza errores que el parser deja pasar
    ('return' fuera de funcion). No ejecuta el modulo: un import roto NO se detecta aca,
    lo detectan los tests.
  - Tests: se corren los que EXISTEN por convencion de nombre; no se generan tests ni se
    adivinan (sin candidato -> lista vacia y el veredicto lo dice). Un fichero sin test
    asociado pasa la verificacion con tests_ok=None: ausencia de examen no es aprobado.
  - El anti-bucle cachea por (ruta, hash del contenido, firma de los tests) en RAM del
    proceso. La firma incluye mtime y tamano de cada test, asi que arreglar el TEST
    invalida la entrada igual que arreglar el modulo (sin eso el harness repetia
    "TESTS FALLAN" sobre un fichero ya correcto, que es el bucle que viene a evitar).
    Sigue sin ver cambios en un TERCER fichero (un import del modulo): `limpiar_cache()`.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# Extensiones con verificador de sintaxis real. Todo lo demas -> ok=True declarado.
_EXT_PY = (".py", ".pyi")
_EXT_JSON = (".json",)

# Recorte del output de pytest: la cola es la senal (traceback + linea de resumen),
# la cabeza es el banner. Mismo criterio que _head_cola de agent/tools.py, pero aqui
# la cabeza no aporta nada: se tira entera.
_MAX_LINEAS = 40
_MAX_CHARS = 3000

# Anti-bucle: veredictos de tests ya calculados, por (ruta, hash contenido, tests).
# En RAM del proceso, sin BD: el objetivo es no re-correr pytest 3 veces seguidas
# dentro de la MISMA tarea, no persistir nada entre sesiones.
_CACHE: dict = {}
_CACHE_MAX = 256


def limpiar_cache() -> None:
    """Vacia la cache anti-bucle (util entre tareas y en tests)."""
    _CACHE.clear()


def _linea_ofensora(contenido: str, lineno) -> str:
    """Texto de la linea que rompe, para que el modelo no tenga que releer el fichero."""
    if not lineno:
        return ""
    lineas = contenido.splitlines()
    if 1 <= lineno <= len(lineas):
        return lineas[lineno - 1].strip()
    return ""


def verificar_sintaxis(ruta, contenido: str) -> tuple:
    """(ok, mensaje) para el contenido que se acaba de escribir en `ruta`.

    Python: compile() con numero de linea y el TEXTO de la linea ofensora.
    JSON: json.loads con linea/columna. Otras extensiones: (True, mensaje que
    declara que no hay verificador para esa extension) — ver limites del modulo.
    """
    p = Path(ruta)
    ext = p.suffix.lower()
    if ext in _EXT_PY:
        try:
            compile(contenido, str(p), "exec")
            return True, "sintaxis OK"
        except SyntaxError as e:
            linea = _linea_ofensora(contenido, e.lineno) or (e.text or "").strip()
            detalle = f": {linea}" if linea else ""
            if not e.lineno:
                # Sin numero de linea (p.ej. bytes nulos en el fuente: en 3.12
                # compile() lanza SyntaxError con lineno=None). "ERROR linea None"
                # es basura para el modelo; se nombra SyntaxError para que
                # classify_exec_error lo siga clasificando como 'syntax'.
                return False, f"ERROR: SyntaxError: {e.msg}{detalle}"
            return False, f"ERROR linea {e.lineno}: {e.msg}{detalle}"
        except ValueError as e:
            # Fuentes que compile() rechaza sin ser SyntaxError (varia por version).
            return False, f"ERROR: SyntaxError: fuente invalido: {e}"
    if ext in _EXT_JSON:
        try:
            json.loads(contenido)
            return True, "JSON valido"
        except json.JSONDecodeError as e:
            linea = _linea_ofensora(contenido, e.lineno)
            detalle = f": {linea}" if linea else ""
            return False, f"ERROR linea {e.lineno} col {e.colno}: {e.msg}{detalle}"
        except ValueError as e:
            return False, f"ERROR: JSON invalido: {e}"
    return True, f"sin verificador de sintaxis para '{ext or 'sin extension'}' (no se comprueba)"


def _es_test(p: Path) -> bool:
    n = p.name.lower()
    return p.suffix.lower() == ".py" and (n.startswith("test_") or n.endswith("_test.py"))


def tests_asociados(ruta_editada, raiz=None) -> list:
    """Rutas de test PLAUSIBLES para el fichero editado, en orden de preferencia.

    Devuelve solo las que EXISTEN, sin duplicados, como Path absolutos. Lista vacia
    si no hay ninguna: no se inventan ni se generan tests.

    Orden (heuristica, todas requieren que el fichero exista):
      1. <raiz>/tests/test_<nombre>.py
      2. test_<nombre>.py junto al fichero editado
      3. <raiz>/tests/<paquete>/test_<nombre>.py (cada sufijo del paquete, del mas
         largo al mas corto: cognia/agent/x.py -> tests/cognia/agent/, tests/agent/)
      4. el propio fichero, si ya es un test (test_*.py o *_test.py)
      5. <raiz>/tests/test_<paquete>_<nombre>.py — convencion REAL de este repo
         (cognia/agent/tools.py -> tests/test_agent_tools.py); va al final porque
         es la mas especifica de Cognia y no la mas general.
    """
    p = Path(ruta_editada)
    raiz = Path(raiz) if raiz is not None else Path.cwd()
    try:
        p = p.resolve()
        raiz = raiz.resolve()
    except OSError:
        return []
    # .lower(): mismo criterio que verificar_sintaxis, que ya normaliza la extension.
    if p.suffix.lower() != ".py":
        return []

    nombre = p.stem
    candidatos = [raiz / "tests" / f"test_{nombre}.py",
                  p.parent / f"test_{nombre}.py"]

    # Sufijos del paquete que contiene al fichero, relativos a la raiz.
    try:
        partes = p.parent.relative_to(raiz).parts
    except ValueError:
        partes = ()
    for i in range(len(partes)):
        candidatos.append(raiz / "tests" / Path(*partes[i:]) / f"test_{nombre}.py")

    if _es_test(p):
        candidatos.append(p)

    if partes:
        candidatos.append(raiz / "tests" / f"test_{partes[-1]}_{nombre}.py")

    encontrados = []
    vistos = set()
    for c in candidatos:
        clave = str(c).lower() if os.name == "nt" else str(c)
        if clave in vistos:
            continue
        vistos.add(clave)
        if c.is_file():
            encontrados.append(c)
    return encontrados


def _recortar(salida: str) -> str:
    """Ultimas ~40 lineas (ahi vive el traceback y la linea de resumen de pytest)."""
    salida = (salida or "").strip()
    if not salida:
        return ""
    lineas = salida.splitlines()
    if len(lineas) > _MAX_LINEAS:
        omitidas = len(lineas) - _MAX_LINEAS
        lineas = [f"[... {omitidas} lineas omitidas (se conserva la cola) ...]"] + \
            lineas[-_MAX_LINEAS:]
    txt = "\n".join(lineas)
    if len(txt) > _MAX_CHARS:
        txt = f"[... recortado a {_MAX_CHARS} chars ...]\n" + txt[-_MAX_CHARS:]
    return txt


# Linea de resumen canonica de pytest: '3 passed in 0.12s', '1 failed, 2 passed in ...',
# '2 errors in ...', 'no tests ran in 0.01s'. Se busca ESTA antes que la heuristica
# suelta: un traceback con 'ValueError: 3' cumple "tiene 'error' y un digito" y se
# colaba como resumen cuando pytest escribia algo a stderr despues del sumario.
_RE_SUMARIO = re.compile(
    r"\b(\d+\s+(passed|failed|error|errors|skipped|xfailed|xpassed|deselected|warnings?)"
    r"|no tests ran)\b")


_RE_ANSI = re.compile(r"\[[0-9;]*[A-Za-z]")


def _resumen_pytest(salida: str, returncode: int) -> str:
    """La linea de resumen de pytest -q ('3 passed in 0.12s'), o el exit code.

    Se limpian los codigos ANSI ANTES de buscar: --color=no lo evita en el
    camino normal, pero esta funcion tambien recibe salidas de terceros (un
    runner del usuario, un wrapper) y no puede quedarse ciega por un color."""
    salida = _RE_ANSI.sub("", salida or "")
    lineas = [l.strip() for l in (salida or "").splitlines() if l.strip()]
    for l in reversed(lineas):
        if _RE_SUMARIO.search(l):
            return l.strip("= ").strip()
    # Sin sumario (pytest ni arranco): la ultima linea util suele ser el motivo real
    # ('No module named pytest', 'file or directory not found: ...').
    for l in reversed(lineas):
        if "error" in l.lower() or "no module named" in l.lower():
            return l.strip("= ").strip()
    if returncode == 5:
        return "pytest no colecto ningun test"
    return f"pytest termino con exit {returncode}"


def correr_tests(rutas, python_exe=None, timeout: int = 120, cwd=None) -> dict:
    """Corre `python -m pytest <rutas> -q --no-header`. NUNCA lanza.

    Devuelve {ok, resumen, salida_recortada}. `python_exe` default sys.executable
    (el interprete que corre el agente; 'python' pelado puede ser otro venv sin
    pytest — la misma razon por la que la tool `tests` usa sys.executable).
    `cwd` conviene que sea la raiz del repo para que pytest tome su pytest.ini
    y su conftest.py.

    En `{ok: False}` la clave `error_harness` distingue "el codigo del modelo falla"
    (False) de "el harness no pudo ni lanzar pytest" (True) — ver texto_resultado.
    """
    # Una ruta suelta (str/Path) NO es un iterable de rutas: sin esto, `[str(r) for r
    # in "tests/x.py"]` recorre CARACTERES y pytest devolvia un 'no tests ran' falso.
    if isinstance(rutas, (str, os.PathLike)):
        rutas = [rutas]
    rutas = [str(r) for r in (rutas or [])]
    if not rutas:
        return {"ok": True, "resumen": "sin tests que correr", "salida_recortada": "",
                "error_harness": False}

    exe = str(python_exe) if python_exe else sys.executable
    # --color=no NO es cosmetica (2026-08-18). pytest colorea cuando cree que hay
    # terminal, y entonces el sumario llega como "[32m1 passed[0m": el
    #  de _RE_SUMARIO no casa contra el ESC y el agente recibe "pytest termino
    # con exit 0" en vez de "1 failed, 2 passed". Eso es lo UNICO que lee para
    # saber si acaba de romper algo, asi que un resumen ciego convierte un fallo
    # en un visto bueno. Cazado con la propia suite del repo, donde estos tests
    # fallan cuando algo activa el color.
    cmd = [exe, "-m", "pytest", *rutas, "-q", "--no-header", "--color=no"]
    # UTF-8 forzado: en Windows el hijo hereda cp1252 y un traceback con acentos
    # llega mutilado (o revienta el decode) justo cuando mas se necesita leerlo.
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           cwd=str(cwd) if cwd else None, env=env,
                           encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired as e:
        parcial = ""
        for chunk in (e.stdout, e.stderr):
            if chunk:
                parcial += chunk if isinstance(chunk, str) else chunk.decode("utf-8", "replace")
        return {"ok": False,
                "resumen": f"ERROR: timeout tras {timeout}s corriendo los tests",
                "salida_recortada": _recortar(parcial),
                "error_harness": False}
    except OSError as e:
        # interprete inexistente / sin permisos: es fallo del HARNESS, no del codigo
        # del modelo, y hay que decirlo asi para que no intente "arreglar" su fichero.
        return {"ok": False,
                "resumen": f"ERROR: no se pudo lanzar pytest ({e})",
                "salida_recortada": "",
                "error_harness": True}

    # "\n".join y no concatenacion: si stdout no termina en salto, su ultima linea y
    # la primera de stderr quedaban pegadas y _resumen_pytest leia una linea inventada.
    salida = "\n".join(t for t in ((r.stdout or "").strip(), (r.stderr or "").strip()) if t)
    return {"ok": r.returncode == 0,
            "resumen": _resumen_pytest(salida, r.returncode),
            "salida_recortada": _recortar(salida),
            "error_harness": False}


def _firma_test(t) -> str:
    """'<ruta>@<sha256 del test>' — cambia si el TEST cambia, aunque el modulo no.

    Sin esto la cache devolvia "TESTS FALLAN" para siempre despues de que el agente
    arreglara el test: el hash solo mira el contenido del fichero verificado, y el
    veredicto rancio empuja al modelo a re-editar un fichero que ya estaba bien —
    justo el bucle que este modulo existe para cortar.

    Se hashea el contenido y no el mtime: en Windows dos escrituras seguidas pueden
    compartir marca de tiempo, y una firma que no distingue es una cache que miente.
    """
    p = Path(t)
    try:
        return f"{p}@{hashlib.sha256(p.read_bytes()).hexdigest()}"
    except OSError:
        # borrado o inaccesible: que no reuse un veredicto sobre un test fantasma.
        return f"{p}@ilegible"


def _clave_cache(ruta: Path, contenido: str, tests: list) -> str:
    h = hashlib.sha256(contenido.encode("utf-8", "replace")).hexdigest()
    return "|".join([str(ruta), h] + [_firma_test(t) for t in tests])


def _guardar_cache(clave: str, veredicto: dict) -> None:
    if len(_CACHE) >= _CACHE_MAX:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[clave] = dict(veredicto)


def verificar_edicion(ruta, contenido: str, raiz=None, python_exe=None,
                      correr: bool = True, timeout: int = 120) -> dict:
    """Veredicto completo de una edicion, listo para realimentar al modelo.

    Devuelve {sintaxis_ok, mensaje, tests_encontrados, tests_ok, resumen,
    salida_recortada, texto}. `tests_encontrados` son rutas relativas a la raiz
    (strings con '/', legibles para el modelo en Windows). `tests_ok` es True/False,
    o None cuando no se corrio nada (sin tests, sintaxis rota, o correr=False).
    `texto` es el bloque RESULTADO ya formateado (ver texto_resultado).

    Los tests NO se corren si la sintaxis falla: pytest solo repetiria el mismo
    SyntaxError tras 2 minutos de espera.
    """
    raiz = Path(raiz) if raiz is not None else Path.cwd()
    p = Path(ruta)
    try:
        raiz = raiz.resolve()
        p_abs = p.resolve()
    except OSError:
        p_abs = p

    ok_sintaxis, mensaje = verificar_sintaxis(p, contenido)
    tests = tests_asociados(p_abs, raiz) if ok_sintaxis else []

    def _rel(t: Path) -> str:
        try:
            return t.relative_to(raiz).as_posix()
        except ValueError:
            return t.as_posix()

    veredicto = {
        "ruta": _rel(p_abs),
        "sintaxis_ok": ok_sintaxis,
        "mensaje": mensaje,
        "tests_encontrados": [_rel(t) for t in tests],
        "tests_ok": None,
        "resumen": "",
        "salida_recortada": "",
        "error_harness": False,
    }

    if not ok_sintaxis:
        veredicto["resumen"] = "tests no corridos: la sintaxis falla"
    elif not tests:
        veredicto["resumen"] = "sin tests asociados (no existe ninguno por convencion de nombre)"
    elif not correr:
        veredicto["resumen"] = "tests encontrados pero no corridos (correr=False)"
    else:
        clave = _clave_cache(p_abs, contenido, tests)
        previo = _CACHE.get(clave)
        if previo is not None:
            # Anti-bucle: mismo fichero, mismo contenido, mismos tests -> mismo
            # veredicto. Re-correr pytest aqui es el bucle caro que hace que el
            # agente "verifique" tres veces lo mismo sin haber cambiado nada.
            resultado = dict(previo)
            resultado["resumen"] += " (cache: el contenido no cambio desde la ultima corrida)"
        else:
            resultado = correr_tests(tests, python_exe=python_exe, timeout=timeout,
                                     cwd=raiz)
            # Un fallo del HARNESS (pytest no lanzable) no se cachea: se arregla fuera
            # del contenido, y cachearlo congelaria el error tras haberlo arreglado.
            if not resultado.get("error_harness"):
                _guardar_cache(clave, resultado)
        veredicto["tests_ok"] = resultado["ok"]
        veredicto["resumen"] = resultado["resumen"]
        veredicto["salida_recortada"] = resultado["salida_recortada"]
        veredicto["error_harness"] = bool(resultado.get("error_harness"))

    veredicto["texto"] = texto_resultado(veredicto)
    return veredicto


def texto_resultado(veredicto: dict) -> str:
    """El veredicto como bloque RESULTADO para el historial del modelo.

    Formato alineado con las tools de ejecucion (`RESULTADO <tool> ...`, 'ERROR linea N')
    para que `agent/stepwise.classify_exec_error` lo clasifique igual que un fallo que
    el propio modelo hubiera provocado corriendo `tests`/`py_validar`.
    """
    ruta = veredicto.get("ruta", "")
    cab = f"RESULTADO verificacion {ruta}"
    if not veredicto.get("sintaxis_ok"):
        return (f"{cab}: {veredicto.get('mensaje', '')}\n"
                "El fichero NO parsea: arregla esa linea antes de seguir "
                "(no se corrieron los tests).")

    tests = veredicto.get("tests_encontrados") or []
    if not tests:
        return f"{cab}: {veredicto.get('mensaje', '')} | {veredicto.get('resumen', '')}"

    lista = ", ".join(tests)
    resumen = veredicto.get("resumen", "")
    # El harness no pudo lanzar pytest: NO es un fallo del codigo del modelo. Decirle
    # "TESTS FALLAN, arregla la causa" lo manda a reescribir un fichero sano.
    if veredicto.get("error_harness") or resumen.startswith("ERROR: no se pudo lanzar pytest"):
        return (f"{cab}: {veredicto.get('mensaje', '')} | VERIFICACION NO DISPONIBLE "
                f"({resumen}) [{lista}]\n"
                "Es un fallo del harness, NO de tu codigo: no cambies el fichero por esto.")

    if veredicto.get("tests_ok") is True:
        return (f"{cab}: {veredicto.get('mensaje', '')} | tests OK "
                f"({veredicto.get('resumen', '')}) [{lista}]")
    if veredicto.get("tests_ok") is False:
        salida = veredicto.get("salida_recortada", "")
        cola = f"\n{salida}" if salida else ""
        return (f"{cab}: {veredicto.get('mensaje', '')} | TESTS FALLAN "
                f"({veredicto.get('resumen', '')}) [{lista}]{cola}\n"
                "Arregla SOLO la causa del fallo y volve a editar; la verificacion "
                "se repite sola tras la proxima edicion.")
    return (f"{cab}: {veredicto.get('mensaje', '')} | {veredicto.get('resumen', '')} "
            f"[{lista}]")
