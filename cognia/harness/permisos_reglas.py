"""
cognia/harness/permisos_reglas.py
=================================
Reglas de permiso PERSISTENTES por herramienta y patron (allow/ask/deny).

POR QUE EXISTE (2026-08-12): hoy el permiso es una decision de UN solo turno y
GLOBAL. `cognia/console/permissions.py` clasifica por `action_kind` (shell_exec,
file_write...) y el REPL solo ofrece Si/No: no hay "permitir siempre", ni
allowlist por patron, ni nada que sobreviva al cierre del proceso. El resultado
es que el usuario contesta "si" a `git status` cuarenta veces por sesion, y al
cansarse pone el modo `bypass` — es decir, la fatiga de confirmaciones termina
DESACTIVANDO el permiso entero. Eso es exactamente lo que resuelven Claude Code
(`Bash(npm test:*)`, `Edit(src/**)` guardados por proyecto), opencode y Goose:
memoria de decisiones, con grano fino.

Este modulo NO reemplaza a `console/permissions.py`: lo COMPLEMENTA. El orden
que se espera del integrador es "regla primero, clasificador despues":

    from cognia.harness import permisos_reglas as PR
    from cognia.console.permissions import needs_confirmation

    reglas = PR.cargar(raiz)                      # .cognia/permisos.json
    efecto, regla = PR.decidir(herramienta, args, reglas)
    if efecto == "denegar":
        ...  # cortar la accion, nombrando regla["patron"] al usuario
    elif efecto == "permitir":
        ...  # ejecutar sin preguntar
    else:                                          # "preguntar"
        if needs_confirmation(action_kind, args):  # el clasificador de siempre
            ...  # menu: Si / No / Permitir siempre
            #  -> si el usuario elige "permitir siempre":
            patron = PR.recordar(raiz, "permitir", herramienta, args)
            #  -> mostrarle SIEMPRE el patron devuelto: es lo que acaba de
            #     autorizar, y puede ser mas ancho que el comando que vio.

FORMATO DE REGLA
    Una regla es {"efecto": ..., "patron": ...} (tambien se acepta la tupla
    (efecto, patron)). `efecto` in ("permitir", "preguntar", "denegar").
    `patron` es "<herramienta>(<glob>)" o "<herramienta>" a secas (que casa
    cualquier argumento de esa herramienta):

        ejecutar(git status*)          escribir_archivo(src/**)
        borrar_archivo                 leer_archivo(**/*.py)

NORMALIZACION DE LOS ARGUMENTOS (documentada porque decide los aciertos)
    Antes de casar, `args` se normaliza asi y SOLO asi:
      1. '\\' -> '/'  (una ruta de Windows y una POSIX casan con el mismo glob;
         efecto colateral aceptado: un escape de shell '\\ ' se vuelve '/ ').
      2. Cualquier racha de espacios/tabs/saltos colapsa a UN espacio.
      3. strip de los extremos.
    El GLOB del patron pasa por la MISMA normalizacion. Sin eso, un patron que el
    usuario escribe a mano en Windows ("escribir_archivo(src\\app\\**)") no casaria
    jamas —y en silencio— porque los args ya vienen con '/'.
    NO se toca la caja: el casado es sensible a mayusculas en todos los SO (se
    traduce el glob a regex propia, no se usa `fnmatch.fnmatch`, que en Windows
    normaliza la caja y haria que un test pase aqui y falle en Linux).

QUE PARTE DE `args` DECIDE (importa tanto como el glob)
    - Herramienta de HERRAMIENTAS_DE_COMANDO: la linea de comando ENTERA (la
      tuberia de "cat a | grep b" es parte del comando).
    - Cualquier otra: solo el PRIMER campo de la convencion "ruta | resto", es
      decir la RUTA. El contenido pegado detras del " | " no decide permisos: si
      decidiera, (a) escribir un fichero cuyo texto lleva una '/' romperia un
      permiso ya concedido —el glob '*' no cruza barras— y el REPL volveria a
      preguntar, y (b) un "; del x" dentro del texto marcaria la escritura como
      destructiva. Cuando no hay " | " el texto se usa entero, asi que una
      herramienta de shell que nadie registro en HERRAMIENTAS_DE_COMANDO se sigue
      analizando como comando (lado seguro).

SEMANTICA DEL GLOB (tipo fnmatch, con la barra como frontera)
      **     casa cualquier cosa, barras INCLUIDAS.
      **/    casa cero o mas directorios ("**/x.py" casa "x.py" y "a/b/x.py").
      *      casa cualquier cosa MENOS '/'.
      ?      casa un caracter que no sea '/'.
    Se aparta de `fnmatch` puro en un punto a proposito: alli `*` ya cruza las
    barras y '**' seria decorativo, con lo que "escribir_archivo(src/*)" daria
    permiso sobre todo el subarbol sin que el usuario lo pidiera. El resto de
    caracteres son literales (no hay clases [a-z]).

PRECEDENCIA (explicita; la resuelve `decidir`)
      1. Gana el efecto mas restrictivo entre las reglas que casan:
             denegar  >  preguntar  >  permitir
      2. A igual efecto, gana el patron MAS ESPECIFICO = mas caracteres no
         comodin en el glob ("ejecutar(git status*)" [10] bate a
         "ejecutar(git*)" [3], y ambos baten a "ejecutar" a secas [-1]).
      3. A igual efecto y especificidad, gana la que aparece ANTES en la lista.
    Si NINGUNA regla casa, el resultado es ("preguntar", None): sin regla no se
    presume permiso.
    Trade-off asumido en el punto 1: un "preguntar" ancho vence a un "permitir"
    estrecho (un "preguntar ejecutar(git*)" vuelve a preguntar por
    "permitir ejecutar(git status*)"). Es deliberado — el unico modo de que un
    freno sea util es que no lo pueda desactivar una regla mas larga.

LLAMADAS ENCADENADAS (por que `decidir` no mira solo la linea entera)
    Casar el patron contra la linea ENTERA deja un agujero de contrabando: con
    "permitir ejecutar(git*)" guardado, la linea "git status && rm -rf build"
    casa "git*" de punta a punta y se ejecutaba SIN PREGUNTAR — el mismo truco
    tumbaba un "denegar ejecutar(rm*)" escrito a mano, porque el denegar solo
    miraba la linea completa y esa empieza por "git". Medido antes del arreglo:
    "git status && rm -rf build" -> permitir, con la regla denegar puesta.
    Por eso, cuando la parte que decide trae MAS DE UN SEGMENTO (';', '&&', '|',
    salto de linea), `decidir` ademas:
      a. decide cada segmento por separado y se queda con el efecto MAS
         RESTRICTIVO que salga de una regla que CASA de verdad (un segmento sin
         regla no estrecha nada: si no, "cat a | grep b" dejaria de estar
         permitido por "ejecutar(cat*)" y volveria la fatiga de confirmaciones);
      b. si el veredicto sigue siendo "permitir", exige que CADA segmento
         destructivo (`es_destructivo`) este permitido POR SI MISMO; si no lo
         esta, degrada a "preguntar" devolviendo igualmente la regla que caso,
         para que el REPL pueda decir cual se quedo corta. Un "permitir
         ejecutar(rm*)" escrito a mano SI cubre su segmento: la guardia frena el
         contrabando, no la voluntad explicita del usuario.
    Con UN solo segmento no se toca nada: la regla casa contra el objetivo
    entero, que es exactamente lo que el usuario autorizo.
    IMPORTANTE para el integrador: manda el efecto DEVUELTO, no `regla["efecto"]`
    (pueden diferir justo en el caso b).

COMANDOS QUE NUNCA SE GENERALIZAN (guardia de `recordar`)
    Pedir "permitir siempre" sobre un comando destructivo convertiria un si
    puntual en una licencia permanente para borrar. Sobre esta lista `recordar`
    guarda el comando EXACTO y con efecto "preguntar", jamas "permitir":
        rm, rmdir, rd, del, erase, format, shutdown, reboot, mkfs* (mkfs.ext4,
        mkfs.xfs...), dd, taskkill, diskpart, remove-item, y "reg add|delete".
    Los ocho nombres del encargo (rm, del, format, shutdown, mkfs, dd,
    "reg delete", taskkill) estan todos; el resto son alias del mismo dano en la
    otra shell (rd/rmdir/erase de cmd, remove-item de PowerShell).
    Tambien se marcan destructivas las herramientas de HERRAMIENTAS_DESTRUCTIVAS
    (borrar_archivo), y los comandos ENVUELTOS (sudo/cmd /c/powershell -c/...):
    envolver es justo como se cuela un destructivo bajo un primer token inocente,
    asi que un comando envuelto se recuerda literal, sin comodin.

LIMITES DECLARADOS
    - Es una capa de POLITICA, no un sandbox: decide sobre el texto de los
      argumentos. No expande variables de entorno ni resuelve rutas relativas
      contra el disco, y no sabe que "cd /x && rm y" borra en /x.
    - `args` es la cadena legacy del repo (`tool_schemas.args_legacy`). Para
      herramientas de fichero el integrador debe pasar la RUTA como primer
      campo (la convencion "path | resto" que ya usa estado_tarea.py); si le
      pasa el contenido del fichero pegado, el glob de rutas no casara.
    - Fichero por proyecto (.cognia/permisos.json). No hay nivel global de
      usuario ni herencia entre proyectos: un permiso concedido aqui no viaja.
    - Sin bloqueo entre procesos: dos `recordar` simultaneos pueden dejar solo
      la ultima regla (lectura rancia). Lo que SI se garantiza es que el fichero
      nunca queda corrupto: cada escritura usa su propio temporal (pid+azar) y
      entra con un `os.replace`; con un temporal de nombre fijo, dos escritores
      a la vez se pisaban el mismo fichero y podian dejar un JSON entrelazado.
    - Lo que este modulo no entiende, NO lo borra: si `permisos.json` no se puede
      interpretar (o trae reglas que no reconoce), `recordar` lo aparta como
      `permisos.json.corrupto*` antes de reescribir. Un JSON con una coma de mas
      no puede costarle al usuario sus reglas `denegar` escritas a mano.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path, PurePosixPath

EFECTOS = ("permitir", "preguntar", "denegar")

# Cuanto mas restrictivo, mas alto: es el criterio 1 de la precedencia.
_RANGO = {"permitir": 1, "preguntar": 2, "denegar": 3}

FICHERO_REGLAS = "permisos.json"
DIR_REGLAS = ".cognia"
_VERSION = 1

# Herramientas cuyos args son una LINEA DE COMANDO (se generalizan por el primer
# token). El resto se trata como ruta de fichero.
HERRAMIENTAS_DE_COMANDO = ("ejecutar", "shell", "bash", "cmd", "powershell")

# Herramientas irreversibles por si mismas: nunca se generalizan (ver docstring).
HERRAMIENTAS_DESTRUCTIVAS = ("borrar_archivo",)

# Comandos destructivos (ver docstring). Se comparan contra el basename del
# ejecutable en minusculas y sin sufijo .exe.
COMANDOS_DESTRUCTIVOS = frozenset({
    "rm", "rmdir", "rd", "del", "erase", "format", "shutdown", "reboot",
    "dd", "taskkill", "diskpart", "remove-item",
})
# 'reg' solo es destructivo con estos subcomandos (reg query es inofensivo).
_SUBCOMANDOS_REG = frozenset({"add", "delete", "import", "restore"})

# Prefijos que ENVUELVEN al comando real; se saltan para mirar quien manda.
_ENVOLTORIOS = frozenset({
    "sudo", "doas", "env", "nohup", "time", "start", "cmd", "cmd.exe",
    "powershell", "powershell.exe", "pwsh", "bash", "sh", "zsh",
})

# "<herramienta>" o "<herramienta>(<glob>)"; el glob se toma hasta el ULTIMO
# parentesis (un glob puede contener parentesis).
_RE_PATRON = re.compile(r"^([^()\s]+)(?:\s*\((.*)\))?$", re.DOTALL)

# Separador de la convencion "ruta | resto" (ver el docstring del modulo).
_RE_CAMPO = re.compile(r"\s\|\s")

# Separadores de comandos encadenados. El salto de linea cuenta: `normalizar` lo
# volveria un espacio, y "git status\nrm -rf build" pasaria por un solo comando
# cuyo jefe es 'git' — es decir, un destructivo colado en la segunda linea.
_RE_SEGMENTO = re.compile(r"[;&|\r\n]+")

# "FOO=bar cmd": la asignacion va DELANTE del comando real, como un envoltorio.
_RE_ASIGNACION = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


# ── Casado ────────────────────────────────────────────────────────────────────

def normalizar(args) -> str:
    """Normaliza los argumentos antes de casar (barras, espacios, strip).

    Ver "NORMALIZACION DE LOS ARGUMENTOS" en el docstring del modulo.
    """
    return " ".join(str(args or "").replace("\\", "/").split())


def partir_patron(patron: str):
    """("herramienta", "glob") del patron, o (None, None) si esta mal formado.

    El glob es "" cuando el patron es la herramienta a secas.
    """
    m = _RE_PATRON.match((patron or "").strip())
    if not m:
        return None, None
    herramienta = m.group(1).strip()
    if not herramienta:
        return None, None
    glob = m.group(2)
    return herramienta, ("" if glob is None else glob.strip())


def _objetivo_crudo(herramienta: str, args) -> str:
    """La parte de `args` que decide, SIN normalizar (conserva los saltos).

    Ver "QUE PARTE DE `args` DECIDE" en el docstring del modulo: linea entera
    para las herramientas de comando, ruta (primer campo) para el resto.
    """
    texto = str(args or "")
    if (herramienta or "").strip() in HERRAMIENTAS_DE_COMANDO:
        return texto
    return _RE_CAMPO.split(texto, maxsplit=1)[0]


def _objetivo(herramienta: str, args) -> str:
    """`_objetivo_crudo` ya normalizado: es lo que se compara contra el glob."""
    return normalizar(_objetivo_crudo(herramienta, args))


def casar(patron: str, herramienta: str, args) -> bool:
    """True si el patron aplica a esta llamada (herramienta + argumentos)."""
    herr_patron, glob = partir_patron(patron)
    if herr_patron is None or herr_patron != (herramienta or "").strip():
        return False
    if glob == "":
        return True     # herramienta a secas: cualquier argumento
    return _regex_glob(glob).match(_objetivo(herramienta, args)) is not None


@lru_cache(maxsize=512)
def _regex_glob(glob: str):
    """Compila el glob a regex. Cacheado: `decidir` corre por cada paso del
    agente y los patrones son pocos y repetidos."""
    glob = normalizar(glob)   # mismo trato que los args (barras y espacios)
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
    return re.compile("".join(salida) + r"\Z")


def especificidad(patron: str) -> int:
    """Caracteres NO comodin del glob; -1 para la herramienta a secas.

    Es el criterio 2 de la precedencia: mide cuanto compromete el patron.
    """
    _, glob = partir_patron(patron)
    glob = normalizar(glob)   # se mide el glob que de verdad se usa al casar
    if not glob:
        return -1
    return sum(1 for c in glob if c not in "*?")


# ── Decision ──────────────────────────────────────────────────────────────────

def _como_regla(regla):
    """Acepta {"efecto","patron"} o la tupla (efecto, patron); None si no vale."""
    if isinstance(regla, dict):
        efecto, patron = regla.get("efecto"), regla.get("patron")
    elif isinstance(regla, (tuple, list)) and len(regla) == 2:
        efecto, patron = regla
    else:
        return None
    efecto = str(efecto or "").strip().lower()
    patron = str(patron or "").strip()
    if efecto not in EFECTOS or not patron:
        return None
    if partir_patron(patron)[0] is None:
        return None
    return {"efecto": efecto, "patron": patron}


def _mejor(herramienta: str, args, reglas):
    """(efecto, regla) mirando el texto TAL CUAL, sin trocearlo en segmentos."""
    mejor, mejor_clave = None, None
    for cruda in (reglas or []):
        regla = _como_regla(cruda)
        if regla is None or not casar(regla["patron"], herramienta, args):
            continue
        clave = (_RANGO[regla["efecto"]], especificidad(regla["patron"]))
        if mejor_clave is None or clave > mejor_clave:   # '>' estricto: gana la 1a
            mejor, mejor_clave = regla, clave
    if mejor is None:
        return "preguntar", None
    return mejor["efecto"], mejor


def _segmentos(herramienta: str, args):
    """Trozos de la parte que decide (';', '&&', '|', salto de linea)."""
    return [s for s in _RE_SEGMENTO.split(_objetivo_crudo(herramienta, args)) if s.strip()]


def decidir(herramienta: str, args, reglas):
    """(efecto, regla_que_caso) para esta llamada. Ver PRECEDENCIA en el modulo.

    Sin regla que case devuelve ("preguntar", None): la ausencia de regla NO es
    permiso. Las reglas mal formadas se ignoran en silencio (no bloquean el
    turno; `cargar` ya avisa cuando el fichero venia roto).
    Si la llamada trae varios segmentos encadenados, ninguno puede colarse a la
    sombra de otro: ver "LLAMADAS ENCADENADAS" en el docstring del modulo. Ahi
    el efecto devuelto puede ser MAS RESTRICTIVO que el de la regla devuelta (se
    devuelve para poder nombrarla); manda el efecto, no `regla["efecto"]`.
    """
    efecto, regla = _mejor(herramienta, args, reglas)
    segmentos = _segmentos(herramienta, args)
    if len(segmentos) < 2:
        return efecto, regla        # un solo objetivo: la regla lo cubre entero
    for seg in segmentos:
        efecto_seg, regla_seg = _mejor(herramienta, seg, reglas)
        if regla_seg is not None and _RANGO[efecto_seg] > _RANGO[efecto]:
            efecto, regla = efecto_seg, regla_seg
    if efecto == "permitir":
        for seg in segmentos:
            if (es_destructivo(herramienta, seg)
                    and _mejor(herramienta, seg, reglas)[0] != "permitir"):
                return "preguntar", regla
    return efecto, regla


# ── Persistencia (.cognia/permisos.json del proyecto) ─────────────────────────

def ruta_reglas(raiz) -> Path:
    """Ruta del fichero de reglas del proyecto (no lo crea)."""
    return Path(raiz) / DIR_REGLAS / FICHERO_REGLAS


def _leer(ruta: Path):
    """(reglas, estado) del fichero. `estado` es lo que puede hacer `recordar`:

        "ok"        reescribir sin miedo (no habia fichero, o se entendio entero).
        "apartar"   se leyo el texto pero no se entendio todo (JSON roto, reglas
                    desconocidas): hay que guardarlo aparte ANTES de reescribir.
        "ilegible"  no se pudo ni leer: nadie debe escribir encima a ciegas.
    """
    try:
        # utf-8-SIG, no utf-8: PowerShell 5.1 (`Out-File -Encoding utf8`, el modo
        # normal de editar el fichero a mano en esta maquina) antepone un BOM, y
        # con "utf-8" el BOM llegaba a json.loads, que lo rechaza: TODAS las
        # reglas del usuario —incluidas las `denegar`— se perdian en silencio.
        texto = ruta.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return [], "ok"
    except UnicodeDecodeError as exc:      # guardado en latin-1 / utf-16...
        # No es OSError ni se puede leer: antes se escapaba de los dos `except`
        # y reventaba el turno entero desde `cargar`, que promete lo contrario.
        _avisar("cargar", f"{ruta}: {type(exc).__name__}: {exc}")
        return [], "apartar"               # ilegible pero PRESENTE: no pisarlo
    except OSError as exc:                 # permisos, fichero bloqueado, disco...
        _avisar("cargar", f"{ruta}: {type(exc).__name__}: {exc}")
        return [], "ilegible"
    try:
        crudo = json.loads(texto)
    except ValueError as exc:
        _avisar("cargar", f"{ruta}: {type(exc).__name__}: {exc}")
        return [], "apartar"
    if isinstance(crudo, dict):
        crudo = crudo.get("reglas", [])
    if not isinstance(crudo, list):
        _avisar("cargar", f"{ruta}: el contenido no es una lista de reglas")
        return [], "apartar"
    reglas = [r for r in (_como_regla(x) for x in crudo) if r is not None]
    if len(reglas) != len(crudo):
        _avisar("cargar", f"{ruta}: {len(crudo) - len(reglas)} regla(s) invalida(s) ignorada(s)")
        return reglas, "apartar"
    return reglas, "ok"


def cargar(raiz, crear: bool = False):
    """Reglas del proyecto (las que se entendieron), o [] si no hay fichero.

    Ni un JSON roto ni un fichero que no sea UTF-8 revientan el turno: devuelve
    lo que se pudo leer ([] en el caso normal) y AVISA por el bus de eventos
    (Degradado) — la degradacion silenciosa es el modo de fallo historico del
    repo, pero un permiso caido en abierto tampoco puede tumbar la sesion; sin
    reglas todo vuelve a "preguntar", que es el lado seguro.
    Con crear=True deja el fichero vacio en disco si faltaba (para que el
    usuario lo encuentre y lo edite a mano).
    """
    ruta = ruta_reglas(raiz)
    existia = ruta.exists()
    reglas, _ = _leer(ruta)
    if crear and not existia:
        guardar(raiz, [])
    return reglas


def guardar(raiz, reglas) -> Path:
    """Persiste las reglas (dedup, orden preservado) y devuelve la ruta.

    Escritura ATOMICA (tmp + os.replace, ambos en el MISMO directorio para que
    el replace sea atomico tambien en NTFS): un corte a mitad deja el fichero
    anterior legible, nunca un JSON truncado que luego se leeria como "sin
    reglas". El temporal lleva pid+azar en el nombre: con un nombre fijo, dos
    escritores simultaneos abrian EL MISMO temporal en modo truncado y el
    ganador podia publicar un JSON entrelazado. Si algo falla se borra el
    temporal (no se deja basura junto al fichero de reglas). A diferencia de
    `cargar`, esta si lanza: si no se puede guardar, el usuario tiene que
    enterarse ANTES de creer que su permiso quedo grabado.
    """
    limpias, vistas = [], set()
    for cruda in (reglas or []):
        regla = _como_regla(cruda)
        if regla is None:
            continue
        clave = (regla["efecto"], regla["patron"])
        if clave in vistas:
            continue
        vistas.add(clave)
        limpias.append(regla)
    ruta = ruta_reglas(raiz)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_name(f"{ruta.name}.{os.getpid()}-{uuid.uuid4().hex[:8]}.tmp")
    datos = json.dumps({"version": _VERSION, "reglas": limpias},
                       ensure_ascii=False, indent=2) + "\n"
    try:
        # newline="\n": en Windows el modo texto pondria CRLF y el fichero
        # cambiaria de bytes segun el SO que lo escribio (ruido en git).
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(datos)
            fh.flush()
            os.fsync(fh.fileno())   # el replace es atomico; los datos, solo si estan en disco
        _reemplazar(tmp, ruta)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return ruta


_REINTENTOS_REPLACE = 6
_ESPERA_REPLACE = 0.03      # 0,03+0,06+... ~0,45 s en el peor caso

# Cuanto se espera al candado antes de seguir sin el, y a partir de que edad un
# .lock se considera de un proceso muerto.
_ESPERA_CANDADO = 2.0
_CADUCA_CANDADO = 10.0


def _reemplazar(origen, destino) -> None:
    """`os.replace` con reintentos cortos ante PermissionError.

    En Windows MoveFileEx falla con WinError 5 si OTRO proceso tiene el destino
    abierto — y basta con que este LEYENDO permisos.json. Reproducido: 4 procesos
    grabando a la vez en el mismo proyecto y 3 morian con PermissionError dentro
    de `recordar`, es decir, el "permitir siempre" del usuario reventaba el turno.
    """
    for intento in range(_REINTENTOS_REPLACE):
        try:
            os.replace(origen, destino)
            return
        except PermissionError:
            if intento == _REINTENTOS_REPLACE - 1:
                raise
            time.sleep(_ESPERA_REPLACE * (intento + 1))


@contextmanager
def _candado(ruta: Path):
    """Serializa el leer-modificar-escribir de `recordar` entre procesos.

    Sin el, dos sesiones abiertas en el mismo proyecto hacen last-writer-wins
    sobre una lectura rancia: el que llega tarde reescribe con lo que leyo ANTES
    y puede borrar una regla `denegar` recien guardada por el otro. Perder un
    freno por una carrera no es un "lost update" cualquiera.
    Si el candado no se consigue en _ESPERA_CANDADO se sigue IGUALMENTE (dejar al
    usuario colgado en el menu de permisos seria peor que la carrera rara), y un
    .lock huerfano de un proceso muerto se roba pasados _CADUCA_CANDADO.
    """
    lock = ruta.with_name(ruta.name + ".lock")
    limite, fd = time.monotonic() + _ESPERA_CANDADO, None
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > _CADUCA_CANDADO:
                    lock.unlink()          # de un proceso que murio sin soltarlo
                    continue
            except OSError:
                pass                       # lo solto otro entre el stat y el unlink
            if time.monotonic() >= limite:
                _avisar("candado", f"{lock.name} ocupado; se graba sin exclusion")
                break
            time.sleep(0.02)
        except OSError as exc:             # sin permisos, sin carpeta...
            _avisar("candado", f"{lock.name}: {type(exc).__name__}: {exc}")
            break
    try:
        yield
    finally:
        if fd is not None:
            os.close(fd)
            try:
                lock.unlink()
            except OSError:
                pass


# ── "Permitir siempre": generalizacion conservadora ───────────────────────────

def es_destructivo(herramienta: str, args) -> bool:
    """True si esta llamada NO se puede generalizar (ver la lista en el modulo).

    Mira el comando en posicion de mando de CADA segmento (';', '&&', '|', y
    tambien el SALTO DE LINEA), saltando envoltorios (sudo, cmd /c, powershell
    -Command), flags, asignaciones "FOO=bar" y comillas.
    Para las herramientas que no son de comando solo mira la RUTA, no el
    contenido pegado (ver "QUE PARTE DE `args` DECIDE" en el modulo).
    """
    if (herramienta or "").strip() in HERRAMIENTAS_DESTRUCTIVAS:
        return True
    for segmento in _RE_SEGMENTO.split(_objetivo_crudo(herramienta, args)):
        tokens = _tokens_de_mando(segmento)
        if not tokens:
            continue
        jefe = _basename(tokens[0])
        if jefe in COMANDOS_DESTRUCTIVOS or jefe.startswith("mkfs"):
            return True
        if jefe == "reg" and len(tokens) > 1 and tokens[1].lower() in _SUBCOMANDOS_REG:
            return True
    return False


def _tokens_de_mando(segmento: str):
    """Tokens del segmento a partir del comando REAL (sin envoltorios ni flags).

    Las comillas se quitan token a token: en `bash -c "rm -rf /"` el token era
    literalmente '"rm' y el jefe se escapaba de COMANDOS_DESTRUCTIVOS.
    """
    tokens = [t for t in (t.strip("\"'") for t in segmento.split()) if t]
    while tokens and (_basename(tokens[0]) in _ENVOLTORIOS or _es_flag(tokens[0])
                      or _RE_ASIGNACION.match(tokens[0])):
        tokens = tokens[1:]
    return tokens


def _es_flag(token: str) -> bool:
    """'-c', '--login' y los switches de cmd ('/c', '/k'). OJO: una ruta POSIX
    ('/usr/bin/rm') NO es un flag — por eso el switch se limita a 1-2 letras."""
    if token.startswith("-"):
        return True
    return token.startswith("/") and 2 <= len(token) <= 3 and token[1:].isalpha()


def _basename(token: str) -> str:
    nombre = token.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return nombre[:-4] if nombre.endswith(".exe") else nombre


def _va_envuelto(texto: str) -> bool:
    """True si el primer token no es el comando real (sudo/cmd /c/FOO=bar/...)."""
    tokens = [t for t in (t.strip("\"'") for t in normalizar(texto).split()) if t]
    if not tokens:
        return False
    return _tokens_de_mando(" ".join(tokens))[:1] != tokens[:1]


def _no_generalizable(herramienta: str, args) -> bool:
    """Guardia unica de `generalizar` y `recordar` (destructivo o envuelto)."""
    return (es_destructivo(herramienta, args)
            or _va_envuelto(_objetivo(herramienta, args)))


def generalizar(herramienta: str, args) -> str:
    """Patron que resume esta llamada, sin tocar disco (lo usa `recordar`).

    - Comando (HERRAMIENTAS_DE_COMANDO): primer token + '*'
      -> "git status --short"  =>  "ejecutar(git*)"
    - Fichero: directorio de la ruta + '/**'
      -> "src/app/a.py | contenido"  =>  "escribir_archivo(src/app/**)"
      Una ruta sin directorio da '*', que por la semantica del glob NO cruza
      barras: se queda en la raiz del proyecto.
    - Destructivo o envuelto: el argumento EXACTO, sin comodin.

    Siempre sobre la parte que decide (comando entero / ruta): el contenido de un
    fichero no entra en el patron — acabaria pegado dentro de permisos.json.
    """
    objetivo = _objetivo(herramienta, args)
    if _no_generalizable(herramienta, args):
        return f"{herramienta}({objetivo})" if objetivo else str(herramienta)
    if (herramienta or "").strip() in HERRAMIENTAS_DE_COMANDO:
        primero = objetivo.split(" ")[0] if objetivo else ""
        return f"{herramienta}({primero}*)" if primero else str(herramienta)
    carpeta = str(PurePosixPath(objetivo).parent) if objetivo else ""
    if not objetivo or carpeta in ("", "."):
        return f"{herramienta}(*)"
    return f"{herramienta}({carpeta}/**)"


def recordar(raiz, efecto: str, herramienta: str, args) -> str:
    """Graba la eleccion del usuario ("permitir siempre"...) y devuelve el patron.

    El patron devuelto es lo que hay que MOSTRARLE: puede ser mas ancho que la
    llamada concreta que aprobo. Si la llamada es destructiva (o va envuelta), el
    efecto se DEGRADA a "preguntar" y el patron queda literal, aunque el usuario
    haya pedido "permitir" — un si de hoy no puede firmar los borrados de manana;
    usar `es_destructivo` antes para avisarselo.
    Una regla previa con el MISMO patron se reemplaza (cambiar de opinion no
    debe dejar dos reglas peleandose).
    Si el fichero traia algo que este modulo no entiende, se aparta primero como
    `permisos.json.corrupto*` en vez de sobrescribirlo: reescribir sin mas
    borraria las reglas `denegar` que el usuario habia puesto a mano. Y si no se
    puede ni LEER, lanza: escribir a ciegas encima seria borrar lo que no se vio.
    El leer-modificar-escribir va bajo candado entre procesos (ver `_candado`).
    """
    efecto = str(efecto or "").strip().lower()
    if efecto not in EFECTOS:
        raise ValueError(f"Efecto invalido: {efecto!r}. Validos: {', '.join(EFECTOS)}")
    patron = generalizar(herramienta, args)
    if efecto == "permitir" and _no_generalizable(herramienta, args):
        efecto = "preguntar"
    ruta = ruta_reglas(raiz)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with _candado(ruta):
        previas, estado = _leer(ruta)
        if estado == "ilegible":
            raise OSError(f"no se pudo leer {ruta}; no se sobrescribe a ciegas")
        if estado == "apartar":
            _respaldar(ruta)
        reglas = [r for r in previas if r["patron"] != patron]
        reglas.append({"efecto": efecto, "patron": patron})
        guardar(raiz, reglas)
    return patron


def _respaldar(ruta: Path):
    """Aparta (os.replace, atomico) el fichero que no se pudo interpretar entero.

    Devuelve la ruta de la copia, o None si no se pudo apartar — en ese caso no
    se toca nada mas: `guardar` escribira encima, pero al menos quedo el aviso.
    """
    destino, n = ruta.with_name(ruta.name + ".corrupto"), 1
    while destino.exists():
        destino = ruta.with_name(f"{ruta.name}.corrupto-{n}")
        n += 1
    try:
        os.replace(ruta, destino)
    except OSError as exc:
        _avisar("recordar", f"no se pudo apartar {ruta.name}: {exc}")
        return None
    _avisar("recordar",
            f"{ruta.name} no se entendio entero; copia intacta en {destino.name}")
    return destino


def _avisar(donde: str, motivo: str) -> None:
    """Aviso por el bus de eventos; si no hay bus, no pasa nada (no es critico)."""
    try:
        from cognia.ux import events as _ev
        _ev.emitir(_ev.Degradado(
            donde=f"permisos_reglas.{donde}", motivo=motivo,
            accion_sugerida="revisar .cognia/permisos.json (se siguio sin reglas)"))
    except Exception:
        pass
