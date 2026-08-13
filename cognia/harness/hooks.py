# -*- coding: utf-8 -*-
"""Hooks de usuario PRE/POST herramienta (insignia de Claude Code y OpenHands).

Por que existe (2026-08-12): Cognia ya tiene hooks INTERNOS (sentinel, permisos,
deshacer) pero el usuario no tiene ninguna manera de meter SU regla sin editar el
codigo del agente. "Formatea con ruff cada .py que edites", "prohibido tocar
prod/", "corre el linter despues de escribir" son politicas del proyecto, no del
agente: viven en un fichero del repo y las cambia quien manda en ese repo.
Claude Code (PreToolUse/PostToolUse con matchers y capacidad de BLOQUEAR la
llamada) y OpenHands resolvieron esto asi; esta pieza es el equivalente.

CONFIGURACION — `<raiz>/.cognia/hooks.json` (y NUNCA otro sitio, ver SEGURIDAD):

    {
      "pre_tool":  [{"match": "escribir_archivo(prod/*)",
                     "comando": "python scripts/veto_prod.py {ruta}",
                     "bloqueante": true}],
      "post_tool": [{"match": "editar_archivo(*.py)",
                     "comando": "ruff format {ruta}"}]
    }

`match` usa el MISMO formato que las reglas de permiso (permisos_reglas.py):
"herramienta" o "herramienta(glob)". `match` ausente = "*".
  - El nombre de herramienta admite comodin (`escribir_*`, `*`), que es lo unico
    en lo que se aparta de las reglas de permiso (alli el nombre es exacto).
  - El glob se compara contra {ruta} si se pudo deducir una, y si no contra el
    texto plano de los argumentos, con la MISMA semantica que permisos_reglas:
    antes de casar se normaliza '\\' -> '/' y las rachas de espacios a una sola;
    `*` y `?` NO cruzan la barra, `**` si, y `**/` son cero o mas directorios.
    Ademas se prueba el basename, para que "*.py" case con "cognia/x.py".
  - El casado es SENSIBLE A LA CAJA en todos los SO (por eso no se usa
    `fnmatch.fnmatch`, que en Windows normaliza caja y barras: un hook probado
    aqui se comportaria distinto en Linux). Ver el test de consistencia
    cruzada con permisos_reglas en tests/test_harness_hooks.py.

VARIABLES del comando: {herramienta} {args} {ruta} {raiz}. Se sustituyen en UNA
sola pasada: un valor que contenga literalmente "{raiz}" se pasa tal cual, no se
vuelve a expandir (si no, el contenido de un argumento decidiria la plantilla).
  {ruta} = el PRIMER argumento que parezca una ruta. Heuristica (documentada
  porque es adivinacion, no contrato):
    - args dict: primero los valores de las claves ruta/path/archivo/fichero/
      file/destino; si ninguna, el primer valor string que parezca ruta.
    - args string: se parte por "|" (el separador de argumentos del repo) y por
      espacios, y se toma el primer token que parezca ruta.
    - "parece ruta" = no empieza por "-", no contiene "://", y ademas tiene
      separador (/ o \\) o extension (.ext de 1..8 alfanumericos) o es . / ..
    - si nada califica, {ruta} es cadena vacia.

API para el integrador (el cableado al CLI/tools lo hace otro; esta pieza es
autocontenida y no importa nada de cognia):

    from cognia.harness import hooks
    cfg = hooks.cargar(raiz)                      # una vez al arrancar; cfg["avisos"] al usuario
    pre = hooks.correr_pre("editar_archivo", args, raiz, config=cfg)
    if not pre["permitido"]:
        return pre["motivo"]                      # el motivo ES lo que ve el modelo
    resultado = ...ejecutar la herramienta...
    post = hooks.correr_post("editar_archivo", args, resultado, raiz, config=cfg)
    if post["anexo"]:
        resultado = resultado + "\\n" + post["anexo"]

SEGURIDAD (esto ejecuta comandos del usuario, se trata en serio):
  - Los hooks se cargan SOLO de `<raiz>/.cognia/hooks.json`, con `raiz` el
    directorio de proyecto que pasa el llamador. Jamas de un directorio sacado
    de los argumentos de la herramienta (si no, escribir un fichero bastaria
    para instalar un hook). Ademas el fichero resuelto debe seguir DENTRO de la
    raiz: un symlink que apunte afuera se rechaza con aviso.
  - timeout duro por hook (default 30 s, acotado a [1, 300]); cwd=raiz.
  - stdout/stderr capturados y recortados a 8 KB por hook (cabeza), y el anexo
    total a 8 KB: un hook charlatan no puede ahogar el contexto del modelo.
  - stdin NUNCA se hereda (subprocess.DEVNULL): un hook que pida input muere en
    EOF en vez de colgar la sesion.
  - shell=False siempre que el comando se pueda tokenizar con shlex y ningun
    token DESNUDO traiga metacaracteres (| & ; < > ( ) $ `). Las variables se
    sustituyen token a token DESPUES de tokenizar, asi un {ruta} con espacios o
    con ";" sigue siendo UN argumento y no puede inyectar comandos.
    Se cae a shell=True solo si el usuario escribio pipes/redirecciones o dejo
    comillas sin cerrar: eso ya no es un argv, es un guion de shell, y ejecutarlo
    sin shell fallaria siempre. En ese modo los valores sustituidos se citan
    (shlex.quote en POSIX; comillas dobles y sin " ni % en Windows), pero la
    responsabilidad del pipe es del que lo escribio.
  - El entorno del hijo lleva COGNIA_HOOKS=0, asi un hook que invoque a Cognia no
    dispara hooks recursivamente. Ademas COGNIA_HOOK_HERRAMIENTA / _RUTA /
    _ARGS / _RESULTADO por si el hook prefiere leerlas del entorno.
  - Kill-switch: COGNIA_HOOKS=0 desactiva todo (no se lee ni se ejecuta nada).

DECISIONES Y LIMITES declarados:
  - Un hook PRE bloqueante que salga != 0 BLOQUEA y corta la evaluacion: los
    hooks siguientes NO corren (ya no hay llamada que vetar).
  - Un hook PRE bloqueante que agote el timeout tambien BLOQUEA (fail-closed:
    un guardia que no contesta no autoriza). Los no bloqueantes solo registran.
  - Los hooks POST nunca bloquean nada: solo aportan `anexo` (texto que se le
    anexa al resultado que ve el modelo) y `aviso` (para el humano).
  - El casado distingue mayusculas aun en Windows, donde el disco no: un glob
    "prod/*" no frena "PROD/config.yaml". Es el precio de que el mismo
    hooks.json se comporte igual aqui que en el CI de Linux; para cubrir las
    dos cajas, dos entradas.
  - No hay expansion de globs ni de variables de entorno en modo shell=False:
    `ruff format *.py` no expande. Usar {ruta}, o un shell explicito.
  - El timeout mata el proceso hijo; los NIETOS que ese hijo haya dejado sueltos
    en Windows pueden sobrevivir (no se crea job object).
  - No se valida que el ejecutable exista: si no existe, el hook cuenta como
    fallo con su motivo (OSError capturado), que es lo que el usuario quiere ver.
  - El fichero se lee tolerando el BOM: en Windows `... | Out-File hooks.json`
    escribe UTF-8 CON BOM (verificado: EF BB BF) y Notepad tambien, asi que
    rechazarlo por "JSON invalido" seria culpar al usuario de un default del SO.
    Se aceptan UTF-8 con y sin BOM y UTF-16 con BOM; sin BOM se asume UTF-8.
"""

from __future__ import annotations

import fnmatch
import json
import locale
import os
import re
import shlex
import subprocess
from functools import lru_cache
from pathlib import Path, PurePosixPath

_DIR_CONFIG = ".cognia"
_FICHERO_CONFIG = "hooks.json"
_FASES = ("pre_tool", "post_tool")

TOPE_SALIDA = 8 * 1024          # bytes/chars por hook y del anexo total
_TIMEOUT_MIN, _TIMEOUT_MAX = 1, 300
_TIMEOUT_DEFECTO = 30           # el mismo que la firma de correr_pre/correr_post

# Metacaracteres que obligan a shell (ver SEGURIDAD en el docstring).
_METACARACTERES = set("|&;<>()$`")

# Claves de un args dict donde una ruta es lo esperable, en orden de preferencia.
_CLAVES_RUTA = ("ruta", "path", "archivo", "fichero", "file", "destino")

_RX_EXTENSION = re.compile(r"\.[A-Za-z0-9]{1,8}$")


# ── Config ────────────────────────────────────────────────────────────────────

def hooks_activos() -> bool:
    """False si COGNIA_HOOKS=0 (kill-switch: ni se lee el fichero)."""
    return os.environ.get("COGNIA_HOOKS", "1").strip().lower() not in ("0", "false", "no")


def ruta_config(raiz) -> Path:
    """Ruta del fichero de hooks del proyecto. No garantiza que exista."""
    return Path(raiz).expanduser() / _DIR_CONFIG / _FICHERO_CONFIG


def cargar(raiz) -> dict:
    """Lee `<raiz>/.cognia/hooks.json`. Tolerante: ausente o corrupto -> vacio.

    Devuelve {"pre_tool": [...], "post_tool": [...], "avisos": [str], "ruta": str}.
    Cada hook normalizado es {"match": str, "comando": str, "bloqueante": bool}.
    Fichero ausente NO genera aviso (es el caso normal); corrupto SI, porque el
    usuario creyo haber configurado algo y hay que decirle que no corre.
    """
    cfg = {"pre_tool": [], "post_tool": [], "avisos": [], "ruta": ""}
    if not hooks_activos():
        return cfg
    try:
        base = Path(raiz).expanduser().resolve()
    except (OSError, TypeError, ValueError) as e:
        cfg["avisos"].append(f"hooks: raiz de proyecto ilegible ({e}); hooks desactivados")
        return cfg
    fichero = base / _DIR_CONFIG / _FICHERO_CONFIG
    cfg["ruta"] = str(fichero)
    if not fichero.is_file():
        return cfg
    try:
        real = fichero.resolve()
    except OSError as e:
        cfg["avisos"].append(f"hooks: {fichero} no resuelve ({e}); se ignora")
        return cfg
    if not _es_subruta(real, base):
        # Un symlink que sale del proyecto convertiria "hooks del proyecto" en
        # "hooks de cualquiera": se rechaza en vez de seguirlo.
        cfg["avisos"].append(f"hooks: {fichero} apunta fuera de la raiz ({real}); se ignora")
        return cfg
    try:
        datos = json.loads(_texto_json(fichero.read_bytes()))
    except (OSError, ValueError, UnicodeDecodeError) as e:
        cfg["avisos"].append(f"hooks: {fichero} ilegible o JSON invalido ({e}); se ignora")
        return cfg
    if not isinstance(datos, dict):
        cfg["avisos"].append(f"hooks: {fichero} debe ser un objeto JSON; se ignora")
        return cfg
    for fase in _FASES:
        cfg[fase] = _normalizar(datos.get(fase), fase, cfg["avisos"])
    return cfg


def _texto_json(crudo: bytes) -> str:
    """Decodifica el fichero respetando el BOM que ponga el editor de turno.

    En Windows `Out-File`/Notepad escriben UTF-8 CON BOM y json.loads lo rechaza
    ("Unexpected UTF-8 BOM"): el usuario veria "JSON invalido" por un default del
    SO. Sin BOM se asume UTF-8, que es lo que documenta el modulo.
    """
    if crudo.startswith(b"\xef\xbb\xbf"):
        return crudo.decode("utf-8-sig")
    if crudo.startswith((b"\xff\xfe", b"\xfe\xff")):
        return crudo.decode("utf-16")          # PS 5.1 antiguo / "Unicode" de Notepad
    return crudo.decode("utf-8")


def _normalizar(entradas, fase: str, avisos: list) -> list:
    """Filtra entradas invalidas dejando aviso por cada una (nunca revienta)."""
    if entradas is None:
        return []
    if not isinstance(entradas, list):
        avisos.append(f"hooks: '{fase}' deberia ser una lista; se ignora")
        return []
    limpias = []
    for i, e in enumerate(entradas):
        if not isinstance(e, dict):
            avisos.append(f"hooks: {fase}[{i}] no es un objeto; se ignora")
            continue
        comando = e.get("comando")
        if not isinstance(comando, str) or not comando.strip():
            avisos.append(f"hooks: {fase}[{i}] sin 'comando'; se ignora")
            continue
        patron = e.get("match", "*")
        if not isinstance(patron, str) or not patron.strip():
            patron = "*"
        glob = _partir_patron(patron.strip())[1]
        if glob and "\\" in glob:
            # Los args se normalizan a '/' antes de casar, asi que un glob con
            # '\' no casa NUNCA. Callarlo es peor que un aviso: un hook
            # bloqueante que no casa deja pasar la llamada que iba a vetar.
            avisos.append(f"hooks: {fase}[{i}] usa '\\' en el glob de '{patron.strip()}'; "
                          f"las rutas se comparan con '/' y ese patron no casara nunca")
        limpias.append({
            "match": patron.strip(),
            "comando": comando.strip(),
            "bloqueante": bool(e.get("bloqueante", False)),
        })
    return limpias


# ── Matching (mismo formato que las reglas de permiso) ────────────────────────

def patron_matchea(patron: str, herramienta: str, args=None) -> bool:
    """True si "herramienta" o "herramienta(glob)" aplica a esta llamada.

    Sensible a la caja en todos los SO y con la barra como frontera (`*` no la
    cruza, `**` si): misma semantica que permisos_reglas.casar. Ver el docstring
    del modulo, seccion `match`.
    """
    nombre, glob = _partir_patron(patron)
    # fnmatchCASE, no fnmatch: fnmatch pasa por os.path.normcase, que en Windows
    # baja la caja y convierte '/' en '\', y entonces el mismo hooks.json casaria
    # distinto aqui que en Linux.
    if not fnmatch.fnmatchcase((herramienta or "").strip(), nombre):
        return False
    if not glob:                       # "herramienta" o "herramienta()": cualquier arg
        return True
    objetivo = _normalizar_objetivo(ruta_de(args) or _texto_args(args))
    if not objetivo:
        return False
    # Se prueba la cadena entera y el basename: "*.py" tiene que casar tanto con
    # "cognia/x.py" como con "x.py", y "test_*.py" con "tests/test_x.py".
    rx = _regex_glob(glob)
    return rx.match(objetivo) is not None or rx.match(PurePosixPath(objetivo).name) is not None


# "<herramienta>" o "<herramienta>(<glob>)", el glob hasta el ULTIMO parentesis
# (un glob puede contener parentesis). DOTALL: un glob con salto de linea es
# raro, pero tiene que seguir siendo un patron y no un nombre de herramienta.
_RE_PATRON = re.compile(r"^([^()\s]+)(?:\s*\((.*)\))?$", re.DOTALL)


def _partir_patron(patron: str):
    """("herramienta", glob) del patron; glob None si no hay parentesis."""
    m = _RE_PATRON.match((patron or "").strip())
    if not m:
        return (patron or "").strip(), None
    glob = m.group(2)
    return m.group(1), (None if glob is None else glob.strip())


def _normalizar_objetivo(texto: str) -> str:
    """'\\' -> '/' y rachas de espacios a una sola (igual que permisos_reglas)."""
    return " ".join(str(texto or "").replace("\\", "/").split())


@lru_cache(maxsize=512)
def _regex_glob(glob: str):
    """Compila el glob a regex: '*'/'?' no cruzan '/', '**' si, '**/' opcional.

    Copia deliberada de permisos_reglas._regex_glob (este modulo es autocontenido
    a proposito); el test de consistencia cruzada salta si las dos divergen.
    """
    salida, i, n = [], 0, len(glob)
    while i < n:
        c = glob[i]
        if c == "*":
            if glob[i + 1:i + 2] == "*":
                if glob[i + 2:i + 3] == "/":
                    salida.append(r"(?:.*/)?")   # '**/' = cero o mas directorios
                    i += 3
                    continue
                salida.append(r".*")             # '**' cruza barras
                i += 2
                continue
            salida.append(r"[^/]*")              # '*' se detiene en la barra
        elif c == "?":
            salida.append(r"[^/]")
        else:
            salida.append(re.escape(c))
        i += 1
    return re.compile("".join(salida) + r"\Z", re.DOTALL)


# ── Deduccion de {ruta} y {args} ──────────────────────────────────────────────

def ruta_de(args) -> str:
    """Primer argumento que parezca una ruta (heuristica en el docstring)."""
    if isinstance(args, dict):
        for clave in _CLAVES_RUTA:
            v = args.get(clave)
            if isinstance(v, str) and v.strip():
                return v.strip()
        for v in args.values():
            if isinstance(v, str) and _parece_ruta(v.strip()):
                return v.strip()
        return ""
    texto = _texto_args(args)
    for trozo in texto.split("|"):
        for token in trozo.split():
            token = token.strip().strip('"').strip("'")
            if _parece_ruta(token):
                return token
    return ""


def _parece_ruta(token: str) -> bool:
    if not token or token.startswith("-") or "://" in token:
        return False
    if token in (".", ".."):
        return True
    if "/" in token or "\\" in token:
        return True
    return bool(_RX_EXTENSION.search(token))


def _texto_args(args) -> str:
    if args is None:
        return ""
    if isinstance(args, str):
        return args
    if isinstance(args, dict):
        return " ".join(str(v) for v in args.values() if v is not None)
    if isinstance(args, (list, tuple)):
        return " ".join(str(v) for v in args if v is not None)
    return str(args)


# ── Ejecucion ─────────────────────────────────────────────────────────────────

def correr_pre(herramienta: str, args, raiz, timeout: int = 30, config=None) -> dict:
    """Corre los hooks pre_tool que matcheen. -> {permitido, motivo, salidas}.

    Un hook con "bloqueante": true que salga != 0 (o que agote el timeout) veta
    la llamada: `permitido` False y `motivo` con su stdout/stderr, que es lo que
    hay que devolverle al modelo en lugar del resultado de la herramienta.
    """
    cfg = config if isinstance(config, dict) else cargar(raiz)
    salidas = []
    if not hooks_activos():
        return {"permitido": True, "motivo": "", "salidas": salidas}
    for hook in cfg.get("pre_tool") or []:
        if not patron_matchea(hook["match"], herramienta, args):
            continue
        r = _correr_uno(hook["comando"], herramienta, args, raiz, timeout, resultado="")
        r["match"] = hook["match"]
        r["bloqueante"] = hook["bloqueante"]
        salidas.append(r)
        if hook["bloqueante"] and r["codigo"] != 0:
            return {"permitido": False, "motivo": _motivo(herramienta, r), "salidas": salidas}
    return {"permitido": True, "motivo": "", "salidas": salidas}


def correr_post(herramienta: str, args, resultado, raiz, timeout: int = 30, config=None) -> dict:
    """Corre los hooks post_tool que matcheen. -> {salidas, anexo, aviso}.

    `anexo` es texto para pegarle al resultado que ve el modelo (vacio si ningun
    hook escribio nada). `aviso` recoge fallos de hooks para el humano: un hook
    post que falla NO invalida la herramienta, que ya se ejecuto.
    """
    cfg = config if isinstance(config, dict) else cargar(raiz)
    salidas, trozos, avisos = [], [], []
    if not hooks_activos():
        return {"salidas": salidas, "anexo": "", "aviso": ""}
    for hook in cfg.get("post_tool") or []:
        if not patron_matchea(hook["match"], herramienta, args):
            continue
        r = _correr_uno(hook["comando"], herramienta, args, raiz, timeout,
                        resultado=resultado if isinstance(resultado, str) else str(resultado or ""))
        r["match"] = hook["match"]
        salidas.append(r)
        if r["salida"]:
            trozos.append(f"[hook post_tool: {hook['comando']}] {r['salida']}")
        if r["codigo"] != 0:
            avisos.append(f"hook post_tool '{hook['comando']}' fallo (exit {r['codigo']})"
                          + (" por timeout" if r["timeout"] else ""))
    return {
        "salidas": salidas,
        "anexo": _recortar("\n".join(trozos)),
        "aviso": "; ".join(avisos),
    }


def _motivo(herramienta: str, r: dict) -> str:
    detalle = r["salida"] or "(sin output)"
    causa = "timeout" if r["timeout"] else f"exit {r['codigo']}"
    return (f"BLOQUEADO por hook pre_tool del proyecto antes de '{herramienta}' "
            f"({causa}): {detalle}\nEs una regla del proyecto, no un error tuyo: "
            f"cambia de enfoque o pidele al usuario que ajuste .cognia/hooks.json.")


def _correr_uno(comando: str, herramienta: str, args, raiz, timeout: int, resultado: str) -> dict:
    """Ejecuta UN hook. Nunca lanza: los fallos vuelven como codigo != 0."""
    try:
        # None/0 = "el default", NO "matalo en 1 segundo": un timeout ausente no
        # puede volverse el mas agresivo posible.
        timeout = max(_TIMEOUT_MIN, min(int(timeout or _TIMEOUT_DEFECTO), _TIMEOUT_MAX))
    except (TypeError, ValueError):
        timeout = _TIMEOUT_DEFECTO      # timeout basura: se acota, no se revienta
    try:
        base = Path(raiz).expanduser()
    except (TypeError, ValueError) as e:
        return {"comando": comando, "shell": False, "timeout": False,
                "codigo": 127, "salida": f"raiz de proyecto invalida: {e}"}
    ruta = ruta_de(args)
    valores = {
        "herramienta": herramienta or "",
        "args": _texto_args(args),
        "ruta": ruta,
        "raiz": str(base),
    }
    argv, usa_shell = _plan_comando(comando, valores)
    salida_base = {"comando": comando, "shell": usa_shell, "timeout": False}
    if not base.is_dir():
        return {**salida_base, "codigo": 127,
                "salida": f"raiz de proyecto inexistente: {base}"}
    entorno = dict(os.environ)
    entorno["COGNIA_HOOKS"] = "0"          # corta la recursion hook -> cognia -> hook
    entorno["COGNIA_HOOK_HERRAMIENTA"] = valores["herramienta"]
    entorno["COGNIA_HOOK_RUTA"] = valores["ruta"]
    entorno["COGNIA_HOOK_ARGS"] = _recortar(valores["args"])
    entorno["COGNIA_HOOK_RESULTADO"] = _recortar(resultado or "")
    try:
        r = subprocess.run(
            argv,
            shell=usa_shell,
            cwd=str(base),
            env=entorno,
            stdin=subprocess.DEVNULL,     # jamas heredar stdin: colgaria la sesion
            capture_output=True,          # en BYTES a proposito: ver _decodificar
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        parcial = _decodificar(e.stdout) + _decodificar(e.stderr)
        return {**salida_base, "timeout": True, "codigo": 124,
                "salida": _recortar(f"timeout tras {timeout}s. {parcial}".strip())}
    except (OSError, ValueError) as e:
        # Ejecutable inexistente, permisos, comando vacio: es fallo del hook.
        return {**salida_base, "codigo": 127, "salida": _recortar(f"no se pudo ejecutar: {e}")}
    return {**salida_base, "codigo": r.returncode,
            "salida": _recortar((_decodificar(r.stdout) + _decodificar(r.stderr)).strip())}


def _plan_comando(comando: str, valores: dict):
    """-> (argv_o_cadena, usa_shell). Sustituye las variables sin romper argv.

    En modo argv se tokeniza PRIMERO la plantilla y se sustituye DESPUES token a
    token: un valor con espacios o con ';' sigue siendo un unico argumento.
    """
    try:
        crudos = shlex.split(comando, posix=False)
    except ValueError:
        return _sustituir(comando, valores, citar=True), True   # comillas sin cerrar
    if not crudos:
        return _sustituir(comando, valores, citar=True), True
    for token in crudos:
        if _entrecomillado(token):
            continue
        if any(c in _METACARACTERES for c in token):
            return _sustituir(comando, valores, citar=True), True
    argv = []
    for token in crudos:
        plantilla = _sin_comillas(token)
        valor = _sustituir(plantilla, valores, citar=False)
        # Un token que existia y quedo vacio al sustituir (p.ej. {ruta} sin ruta)
        # se descarta: un argv con "" casi nunca es lo que el usuario queria.
        if not valor and plantilla and "{" in plantilla:
            continue
        argv.append(valor)
    return argv, False


_RX_MARCA = re.compile(r"\{(herramienta|args|ruta|raiz)\}")


def _sustituir(texto: str, valores: dict, citar: bool) -> str:
    """Sustituye {herramienta} {args} {ruta} {raiz} en UNA sola pasada.

    Una pasada por clave (replace en cadena) dejaria que el VALOR de {args}
    aporte marcas: un argumento que contenga el texto "{raiz}" se expandiria
    despues, y el contenido de la llamada acabaria decidiendo la plantilla.
    """
    def _uno(m):
        valor = valores.get(m.group(1), "")
        return _citar(valor) if citar else valor
    return _RX_MARCA.sub(_uno, texto)


def _citar(valor: str) -> str:
    """Cita un valor que va a pasar por un shell (mitiga, no bendice)."""
    if not valor:
        return '""'
    if os.name == "nt":
        limpio = valor.replace('"', "").replace("%", "")
        return f'"{limpio}"'
    return shlex.quote(valor)


def _entrecomillado(token: str) -> bool:
    return len(token) >= 2 and token[0] == token[-1] and token[0] in ("'", '"')


def _sin_comillas(token: str) -> str:
    return token[1:-1] if _entrecomillado(token) else token


def _decodificar(crudo) -> str:
    """Decodifica la salida del hook: UTF-8, y si no, la codificacion local.

    Decodificar en UTF-8 a secas convierte en '?' cualquier acento de un hook
    que escriba en la pagina de codigos de Windows (un `print('camión')` de un
    Python sin PYTHONUTF8, o cualquier herramienta vieja): el usuario ve su
    mensaje roto justo cuando el hook le esta explicando por que le bloqueo la
    llamada. UTF-8 estricto primero (lo normal hoy) y la local como red.
    Limite: una consola en OEM (cp850) puede seguir dando algun acento raro; no
    hay forma de saber la codificacion de un proceso ajeno, solo de acertar mas.
    """
    if not crudo:
        return ""
    if isinstance(crudo, str):
        return crudo
    for codec in _codecs_de_respaldo():
        try:
            return crudo.decode(codec)
        except (UnicodeDecodeError, LookupError):
            continue
    return crudo.decode("latin-1", errors="replace")


def _codecs_de_respaldo() -> list:
    """La cascada de codificaciones a probar, en orden.

    OJO con ``locale.getpreferredencoding(False)``: bajo el modo UTF-8 de Python
    (PYTHONUTF8=1, que es como corre el propio repo) devuelve 'utf-8', o sea el
    mismo codec que ya falló — el respaldo no respaldaba nada y el acento salía
    igual de roto. ``locale.getencoding()`` sí da la codificación REAL del
    locale (la página ANSI en Windows), que es la que usa un proceso ajeno que
    no active el modo UTF-8.
    """
    codecs = ["utf-8"]
    try:
        codecs.append(locale.getencoding())      # 3.11+: ignora el modo UTF-8
    except AttributeError:                        # pragma: no cover - 3.10 y anteriores
        codecs.append(locale.getpreferredencoding(False))
    codecs.append("cp1252")                       # la ANSI mas comun en Windows
    vistos, unicos = set(), []
    for c in codecs:
        cl = (c or "").lower()
        if cl and cl not in vistos:
            vistos.add(cl)
            unicos.append(c)
    return unicos


def _recortar(texto: str, tope: int = TOPE_SALIDA) -> str:
    texto = texto or ""
    if len(texto) <= tope:
        return texto
    return texto[:tope] + f"\n[... {len(texto) - tope} chars omitidos por el tope de {tope} ...]"


def _es_subruta(p: Path, raiz: Path) -> bool:
    try:
        p.relative_to(raiz)
        return True
    except ValueError:
        return False
