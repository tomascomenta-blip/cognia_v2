"""
scripts/comparar_modelos.py - EL ARNES DE BARRIDO: N modelos, una GPU, una tabla.

POR QUE EXISTE (2026-08-13): elegir cerebro se venia haciendo de a un modelo por
vez, a mano, y comparando numeros de corridas distintas. La memoria del repo dice
lo que eso vale: la varianza ENTRE corridas es de +-34 puntos, asi que solo los
netos APAREADOS intra-corrida son evidencia. Este script hace la corrida unica:
para el server, levanta cada candidato en el MISMO puerto con los MISMOS flags
(solo cambian --model y --ctx-size), le mide lo mismo a todos, y saca una tabla.

Lo que mide por modelo:
  1. si ARRANCA (y en cuantos segundos: cargar 11 GB tarda)
  2. el REGIMEN que le asigna cognia.agent.model_profiles (nativo|texto). No es
     un bug a arreglar: es UN DATO DEL EXPERIMENTO. Solo gpt-oss y qwythos estan
     en _FAMILIAS_NATIVAS; el resto cae a TEXTO y hay que saber cuanto cuesta.
  3. tok/s con una generacion corta REAL (timings de llama-server; usage y reloj
     como respaldo)
  4. el banco que se le pase por --banco (un comando, p.ej.
     scripts/e2e_happy_path.py, o un import "py:modulo:funcion")

LO MAS IMPORTANTE DEL SCRIPT NO ES LA TABLA, ES LA RESTAURACION. Antes de tocar
nada se lee la linea de comando COMPLETA del llama-server vivo (via CIM: en este
Windows 11 build 26200 `wmic` YA NO EXISTE, verificado 2026-08-13) y se guarda en
disco. Pase lo que pase - excepcion, Ctrl-C, banco colgado, modelo que no entra
en VRAM - el finally (y un atexit de respaldo) relanza ESA linea exacta y
verifica /health + /props. Si el barrido muere a la mitad, el dueno NO puede
quedarse sin cerebro. Cuando ni asi se pudo, el script sale con codigo 2 y grita
el comando para copiar y pegar (que ademas quedo escrito en
~/.cognia/comparar_modelos_restaurar.txt desde el segundo cero).

    # ver el plan SIN tocar ningun server (esto es seguro siempre):
    venv312\\Scripts\\python.exe scripts\\comparar_modelos.py --dry-run

    # el barrido de verdad (para y arranca servers: cierra el CLI antes)
    venv312\\Scripts\\python.exe scripts\\comparar_modelos.py ^
        --modelos qwythos,gpt-oss,Qwen3-4B ^
        --banco scripts\\e2e_happy_path.py

El --ctx-size NO puede ser fijo: los 200192 del server actual los aguanta
Qwythos porque su KV cuesta ~38 B/token (arquitectura hibrida); un denso de 14B
con esa ventana no arranca o se come la VRAM. Hay tabla por modelo
(_CTX_POR_MODELO), default conservador (--ctx 16384) y override
(--ctx-modelo nombre=N).

El banco corre con COGNIA_LLM_URL y LLAMA_SERVER_PORT apuntando al candidato:
node/llama_backend ADOPTA el server que ya responde en ese puerto en vez de
levantar otro (verificado leyendo _check_adopted_server). Un banco que se
arranque su propio modelo mediria otra cosa: es responsabilidad del banco.

Solo stdlib. Reusa scripts/servir_modelo.py (binario, catalogo de .gguf,
construir_cmd, estado de /health): dos copias de esa logica fue exactamente como
el :8088 sirvio un modelo retirado durante semanas.

Codigos de salida:
    0  barrido completo y cerebro restaurado
    1  algun modelo no arranco / algun banco fallo (cerebro restaurado igual)
    2  NO SE PUDO RESTAURAR EL SERVER ORIGINAL  <-- el unico que importa de noche
    3  abortado antes de tocar nada (falta binario, falta modelo, etc.)
"""

from __future__ import annotations

import argparse
import atexit
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time
import traceback
import urllib.request
from pathlib import Path

# El repo no esta necesariamente instalado: raiz (cognia/) y scripts/ a mano.
_RAIZ = Path(__file__).resolve().parent.parent
_DIR_SCRIPTS = Path(__file__).resolve().parent
for _p in (str(_RAIZ), str(_DIR_SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import servir_modelo as sm          # noqa: E402  (reuso, no copia)

PUERTO_DEFAULT = 8080
CTX_DEFAULT = 16384                 # conservador: entra en 16 GB con cualquiera
VRAM_MIB = 16311                    # RTX 5060 Ti, medido
DIR_COGNIA = Path.home() / ".cognia"
RESCATE = DIR_COGNIA / "comparar_modelos_restaurar.txt"

# ctx por modelo (trozo del nombre en minusculas -> tokens). Los dos primeros
# son valores MEDIDOS en esta maquina; el resto son conservadores calculados con
# _KV_BYTES_TOKEN y verificables por el propio barrido (si no arranca, se ve).
_CTX_POR_MODELO = {
    "qwythos": 200192,        # el server vivo del 2026-08-13 lo sirve asi (KV ~38 B/tok)
    "gpt-oss": 16384,         # 12.2 GB de 16.3 medidos (combo 'pensar' de flota.py)
    "openreasoning": 16384,   # denso 14B Q4: 8.4 GB de pesos + ~3.2 GB de KV
    "nemotron": 16384,
    "qwen2.5-coder-14b": 16384,
    "qwen2.5-7b": 32768,
    "qwen3-4b": 32768,
}

# Coste de KV por token, en BYTES. ESTIMACION GROSERA a partir de la
# arquitectura publicada (2*capas*kv_heads*head_dim*2 bytes en f16) - no medido,
# salvo qwythos, que sale de la ventana que el server vivo aguanta. Sirve para
# AVISAR antes de lanzar algo que no entra, nunca para decidir por el usuario:
# quien decide es el arranque real, que este script observa.
_KV_BYTES_TOKEN = {
    "qwythos": 38,            # hibrido: por eso aguanta 200192
    "gpt-oss": 49152,         # 24 capas x 8 kv x 64 dim (mitad con sliding window)
    "openreasoning": 196608,  # Qwen2.5-14B: 48 x 8 x 128
    "nemotron": 196608,
    "qwen2.5-coder-14b": 196608,
    "qwen2.5-7b": 57344,      # 28 x 4 x 128
    "qwen3-4b": 147456,       # 36 x 8 x 128
}
_KV_DESCONOCIDO = 200000      # denso de 14B: el peor caso de esta carpeta

# Flags del draft especulativo: un draft de OTRA familia es un confound (y el
# server ni arranca si el vocabulario no casa). Al clonar la linea original se
# quitan; --spec-type ngram-mod no lleva draft aparte, asi que ese se conserva.
_DRAFT_CON_VALOR = ("--spec-draft-model", "--model-draft", "-md",
                    "--spec-draft-ngl", "--spec-draft-n-max",
                    "--spec-draft-p-min", "--draft-max", "--draft-min")

# Estado global de la restauracion: el atexit es el CINTURON del finally (si
# alguien llama sys.exit desde un callback, el finally del main igual corrio;
# si no corrio, esto lo salva). Idempotente por _RESTAURADO.
_ORIGINAL: dict = {}
_RESTAURADO = False
_ESPERA_RESTAURACION = 300
_INTENTOS_RESTAURACION = 0
_MAX_INTENTOS = 2             # finally + atexit; mas seria matar y relanzar en bucle

# PIDs que lanzo ESTE proceso. La restauracion solo puede matar a los suyos:
# un llama-server que no lanzamos nosotros es de otro (la flota del dueno, otra
# sesion, un barrido en paralelo) y matarlo es exactamente la averia que este
# script existe para no causar. Cazado EN VIVO el 2026-08-13: un arnes de
# pruebas importo este modulo, dejo _ORIGINAL puesto con puerto 8080 y el
# atexit mato el llama-server REAL del dueno para relanzar una linea de mentira.
_LANZADOS: set = set()


# ----------------------------------------------------------------- procesos --

def _salida(comando: list, timeout: int = 20) -> str:
    """stdout de un comando del sistema; '' si falla. Nunca lanza."""
    try:
        r = subprocess.run(comando, capture_output=True, timeout=timeout)
        return r.stdout.decode("utf-8", errors="replace")
    except Exception:
        return ""


def _powershell(comando: str, timeout: int = 25) -> str:
    """PowerShell -NoProfile en UTF-8. En Windows 11 26200 `wmic` fue removido
    (verificado 2026-08-13: 'no se reconoce como nombre de cmdlet'), asi que CIM
    es el UNICO camino para leer la linea de comando de otro proceso."""
    envoltura = ("$OutputEncoding=[Console]::OutputEncoding="
                 "[Text.Encoding]::UTF8; " + comando)
    return _salida(["powershell", "-NoProfile", "-NonInteractive",
                    "-Command", envoltura], timeout=timeout)


def pids_del_puerto(puerto: int) -> list:
    """PIDs con un LISTENING en ese puerto (todos los interfaces)."""
    pids = []
    if os.name == "nt":
        for linea in _salida(["netstat", "-ano"], timeout=25).splitlines():
            if f":{puerto} " in linea and "LISTENING" in linea.upper():
                try:
                    pid = int(linea.split()[-1])
                except ValueError:
                    continue
                if pid and pid not in pids:
                    pids.append(pid)
    else:
        for linea in _salida(["ss", "-lptn"], timeout=25).splitlines():
            if f":{puerto} " in linea:
                for m in re.finditer(r"pid=(\d+)", linea):
                    pid = int(m.group(1))
                    if pid not in pids:
                        pids.append(pid)
    return pids


def nombre_de_pid(pid: int) -> str:
    """Nombre del ejecutable de un PID ('' si no vive)."""
    if os.name == "nt":
        csv = _salida(["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"])
        m = re.match(r'"([^"]+)"', csv.strip())
        return m.group(1) if m else ""
    return _salida(["ps", "-p", str(pid), "-o", "comm="]).strip()


def pid_vivo(pid: int) -> bool:
    if not pid:
        return False
    if os.name == "nt":
        return bool(nombre_de_pid(pid))
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def pid_del_llama(puerto: int) -> int:
    """El PID del llama-server que escucha en `puerto`, 0 si no hay.

    FILTRA POR NOMBRE a proposito: en esta maquina tailscaled tambien escucha en
    :8080 (en 100.110.56.37 y en la IPv6 de Tailscale), y quedarse con el primer
    PID del netstat es como el summoner perdio el cerebro (memoria del repo)."""
    for pid in pids_del_puerto(puerto):
        if "llama" in nombre_de_pid(pid).lower():
            return pid
    return 0


def linea_de_comando(pid: int) -> str:
    """Linea de comando COMPLETA de un PID. '' si no se pudo leer.

    Va por JSON (ConvertTo-Json escapa el string entero) y NO por el texto
    pelado: el ' '.join(salida.split()) del texto colapsa cualquier corrida de
    espacios, asi que una ruta con dos espacios seguidos - 'C:\\Mis  Modelos\\' -
    volvia con UN espacio y la restauracion relanzaba una ruta que no existe.
    Medido 2026-08-13 contra el pid vivo: los dos caminos dan los mismos 352
    caracteres y PowerShell NO parte la linea, asi que el JSON es gratis."""
    if not pid:
        return ""
    if os.name == "nt":
        js = _powershell(
            f"@{{c=(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}')"
            f".CommandLine}} | ConvertTo-Json -Compress")
        try:
            valor = json.loads(js).get("c")
            if isinstance(valor, str) and valor.strip():
                return valor.strip()
        except (ValueError, AttributeError):
            pass
        salida = _powershell(          # respaldo: mejor colapsada que ninguna
            f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}')"
            f".CommandLine")
        return " ".join(salida.split()) if salida.strip() else ""
    try:
        crudo = Path(f"/proc/{pid}/cmdline").read_bytes()
        return " ".join(crudo.decode("utf-8", "replace").split("\0")).strip()
    except OSError:
        return ""


def argv_de_linea(linea: str) -> list:
    """Linea de comando -> argv. En Windows usa CommandLineToArgvW (el mismo
    parser que usa el sistema: comillas y rutas con espacios salen exactas)."""
    linea = (linea or "").strip()
    if not linea:
        return []
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes
            n = ctypes.c_int(0)
            shell32 = ctypes.WinDLL("shell32", use_last_error=True)
            shell32.CommandLineToArgvW.restype = ctypes.POINTER(
                ctypes.c_wchar_p)
            shell32.CommandLineToArgvW.argtypes = [wintypes.LPCWSTR,
                                                   ctypes.POINTER(ctypes.c_int)]
            puntero = shell32.CommandLineToArgvW(linea, ctypes.byref(n))
            if puntero:
                try:
                    return [puntero[i] for i in range(n.value)]
                finally:
                    ctypes.windll.kernel32.LocalFree(puntero)
        except Exception:
            pass
        # Respaldo: shlex non-posix DEJA las comillas pegadas al argumento, y
        # Popen(lista) no las quita -> '"C:\\ruta con espacio\\x.exe"' no existe.
        return [a[1:-1] if len(a) > 1 and a[0] == a[-1] == '"' else a
                for a in shlex.split(linea, posix=False)]
    return shlex.split(linea)


# ------------------------------------------------------------------ /health --

def estado_puerto(puerto: int) -> str:
    """'ok' | 'cargando' | 'ausente'. Delegado a servir_modelo.estado(): el 503
    de /health significa 'hay server CARGANDO', no 'no hay server'."""
    return sm.estado(puerto)


def props_de(puerto: int) -> dict:
    """{'modelo','n_ctx'} reales del server, forzando el cache (el puerto se
    reusa entre candidatos: un cache por URL mentiria en cada reinicio)."""
    try:
        from cognia import backend_activo
        return backend_activo.props(f"http://127.0.0.1:{puerto}", forzar=True)
    except Exception:
        pass
    try:                       # sin cognia importable, a mano
        with urllib.request.urlopen(f"http://127.0.0.1:{puerto}/props",
                                    timeout=5) as r:
            crudo = json.loads(r.read().decode("utf-8", "replace"))
        ruta = (crudo.get("model_path")
                or crudo.get("default_generation_settings", {}).get("model", ""))
        return {"modelo": Path(str(ruta)).name,
                "n_ctx": crudo.get("default_generation_settings",
                                   {}).get("n_ctx")}
    except Exception:
        return {}


def esperar_health(puerto: int, timeout: float, proceso=None) -> tuple:
    """(ok, segundos, motivo). Corta antes si el proceso muere: esperar 180 s a
    un server que ya reviento por VRAM es tiempo regalado x N modelos."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        est = estado_puerto(puerto)
        if est == "ok":
            return True, time.time() - t0, ""
        if proceso is not None and proceso.poll() is not None:
            return (False, time.time() - t0,
                    f"el proceso murio al arrancar (codigo {proceso.returncode}); "
                    f"tipico: el modelo + ese ctx no entran en la VRAM")
        time.sleep(2.0)
    return False, time.time() - t0, f"sin /health en {timeout:.0f}s"


def esperar_puerto_libre(puerto: int, timeout: float) -> bool:
    """True cuando ya no queda NINGUN llama-server en el puerto.

    MEDIDO el 2026-08-13, primera corrida real del barrido: mirar /health nunca
    daba 'ausente' aunque el llama-server estuviera muerto, y el arnes saltaba
    todos los modelos con 'NO pude liberar :8080'. La causa es la misma leccion
    que ya cazo al summoner: **tailscaled tiene su propio LISTENING en :8080**
    (sobre 100.110.56.37 y [::]), asi que la sonda HTTP siempre encuentra a
    ALGUIEN. El comentario anterior decia que se miraba /health justamente para
    evitar a tailscaled — y era al reves: /health es lo que cae en su trampa.

    Lo que de verdad hay que saber para arrancar el candidato es si murio el
    llama-server anterior; el bind de tailscaled esta en OTRA direccion y no
    colisiona con 127.0.0.1. `pid_del_llama` ya filtra por nombre de proceso.
    """
    t0 = time.time()
    while time.time() - t0 < timeout:
        if not pid_del_llama(puerto):
            return True
        time.sleep(1.0)
    return not pid_del_llama(puerto)


# ----------------------------------------------------- parar / arrancar servers

def parar_pid(pid: int, puerto: int, espera: float) -> bool:
    """Para un llama-server: primero educado, despues /F. NUNCA taskkill /IM -
    ese martillo global mata tambien al VLM de :8081 y a la flota del dueno."""
    if not pid or not pid_vivo(pid):
        return True
    if os.name == "nt":
        _salida(["taskkill", "/PID", str(pid), "/T"], timeout=20)
    else:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    t0 = time.time()
    while time.time() - t0 < min(espera, 10.0):
        if not pid_vivo(pid):
            break
        time.sleep(0.5)
    if pid_vivo(pid):
        if os.name == "nt":
            _salida(["taskkill", "/PID", str(pid), "/T", "/F"], timeout=20)
        else:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
    libre = esperar_puerto_libre(puerto, max(espera - (time.time() - t0), 5.0))
    return libre and not pid_vivo(pid)


def matar_arbol(proc) -> None:
    """Mata un Popen Y a sus hijos. Sigue siendo kill SELECTIVO: el /T de
    taskkill cuelga del PID, no del nombre de imagen; nunca un /IM."""
    if proc is None or proc.poll() is not None:
        return
    if os.name == "nt":
        _salida(["taskkill", "/PID", str(proc.pid), "/T", "/F"], timeout=20)
    else:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except OSError:
            try:
                proc.kill()
            except OSError:
                pass


def lanzar(argv: list, log: Path):
    """Popen DESPEGADO: nuevo grupo de procesos (un Ctrl-C en esta consola no lo
    mata a medias) y sin consola propia. stdout/stderr a fichero: si no arranca,
    el motivo tiene que quedar en disco, no evaporarse."""
    log.parent.mkdir(parents=True, exist_ok=True)
    extra = {}
    if os.name == "nt":
        extra["creationflags"] = (subprocess.CREATE_NEW_PROCESS_GROUP
                                  | subprocess.DETACHED_PROCESS)
    else:
        extra["start_new_session"] = True
    # `with`: el hijo se queda con SU copia del descriptor, asi que cerrarlo
    # aqui no le corta el log. Sin esto, un barrido de 11 modelos deja 11
    # handles abiertos y los .log del sistema de ficheros tomados.
    with open(log, "wb") as fh:
        proc = subprocess.Popen(argv, stdout=fh, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, **extra)
    _LANZADOS.add(proc.pid)
    return proc


# ------------------------------------------------- construccion del comando --

def _pon_valor(argv: list, flags: tuple, valor: str) -> tuple:
    """Reemplaza el valor de un flag (forma '--f v' y '--f=v'). (argv, puesto)."""
    salida, i, puesto = [], 0, False
    while i < len(argv):
        a = argv[i]
        if a in flags and i + 1 < len(argv):
            salida += [a, str(valor)]
            i += 2
            puesto = True
            continue
        casa = next((f for f in flags if a.startswith(f + "=")), "")
        if casa:
            salida.append(f"{casa}={valor}")
            i += 1
            puesto = True
            continue
        salida.append(a)
        i += 1
    return salida, puesto


def _quitar_draft(argv: list) -> tuple:
    """Saca los flags de draft model (y --spec-type si ese draft se fue).
    Devuelve (argv, quitados)."""
    salida, quitados, i = [], [], 0
    tenia_draft_model = any(a.split("=")[0] in ("--spec-draft-model",
                                               "--model-draft", "-md")
                            for a in argv)
    while i < len(argv):
        a = argv[i]
        base = a.split("=")[0]
        if base in _DRAFT_CON_VALOR:
            quitados.append(a)
            if "=" not in a and i + 1 < len(argv):
                quitados.append(argv[i + 1])
                i += 1
            i += 1
            continue
        if base == "--spec-type" and tenia_draft_model:
            # draft-simple sin draft model no sirve; ngram-mod no lleva draft y
            # por eso solo se cae cuando habia un draft de otra familia.
            quitados.append(a)
            if "=" not in a and i + 1 < len(argv):
                quitados.append(argv[i + 1])
                i += 1
            i += 1
            continue
        salida.append(a)
        i += 1
    return salida, quitados


def argv_candidato(original_argv: list, exe: Path, modelo: Path, puerto: int,
                   ctx: int, con_jinja: bool) -> list:
    """El comando del candidato. Con server original vivo se CLONA su linea
    (mismos threads, cache-reuse, prio, flash-attn...) y solo cambian --model y
    --ctx-size: asi la tabla compara modelos y no configuraciones. Sin original,
    se cae al comando canonico de servir_modelo.construir_cmd()."""
    if original_argv:
        argv = list(original_argv)
        argv, _ = _quitar_draft(argv)
        argv, puesto_m = _pon_valor(argv, ("--model", "-m"), str(modelo))
        if not puesto_m:
            argv += ["--model", str(modelo)]
        argv, puesto_c = _pon_valor(argv, ("--ctx-size", "-c"), str(ctx))
        if not puesto_c:
            argv += ["--ctx-size", str(ctx)]
        argv, puesto_p = _pon_valor(argv, ("--port",), str(puerto))
        if not puesto_p:
            argv += ["--port", str(puerto)]
    else:
        argv = sm.construir_cmd(exe, modelo, puerto, ctx)
        argv += ["--host", "127.0.0.1"]
    if con_jinja and "--jinja" not in argv:
        # El tool-calling nativo se verifico con --jinja (model_profiles). El
        # server vivo del dueno NO lo lleva: por eso es opcional y explicito,
        # para que el clon sea fiel salvo que se pida lo contrario.
        argv += ["--jinja"]
    return argv


# --------------------------------------------------------- ctx y VRAM (aviso) --

def _trozo(nombre: str, tabla: dict):
    bajo = nombre.lower()
    for k, v in tabla.items():
        if k in bajo:
            return v
    return None


def ctx_de_modelo(nombre: str, default: int, overrides: dict) -> tuple:
    """(ctx, fuente). Prioridad: --ctx-modelo > tabla medida > --ctx."""
    bajo = nombre.lower()
    for patron, valor in overrides.items():
        if patron.lower() in bajo:
            return valor, f"--ctx-modelo {patron}"
    de_tabla = _trozo(nombre, _CTX_POR_MODELO)
    if de_tabla is not None:
        return de_tabla, "tabla _CTX_POR_MODELO"
    return default, "--ctx (default)"


def vram_estimada_gb(ruta: Path, ctx: int) -> float:
    """Pesos + KV, en GB. ESTIMACION GROSERA (arquitectura publicada, no
    medida): sirve para avisar antes de lanzar, no para decidir. Quien decide
    es el arranque real."""
    try:
        pesos = ruta.stat().st_size / 1e9
        # Multiparte: el .gguf 00001 es solo el primer trozo; se suman los
        # hermanos. Se recorren a mano y no con glob(): un nombre con '[' o '?'
        # es un patron valido para glob y devolveria CERO ficheros en silencio
        # (peso 0 GB -> ningun aviso de VRAM justo cuando mas hace falta).
        if "-00001-of-" in ruta.name:
            raiz = ruta.name.split("-00001-of-")[0] + "-"
            trozos = [m for m in ruta.parent.iterdir()
                      if m.name.startswith(raiz) and m.name.endswith(".gguf")]
            if trozos:
                pesos = sum(m.stat().st_size for m in trozos) / 1e9
    except OSError:
        pesos = 0.0
    kv = _trozo(ruta.name, _KV_BYTES_TOKEN) or _KV_DESCONOCIDO
    return pesos + (kv * ctx) / 1e9


# --------------------------------------------------------------- mediciones --

def regimen_del_server(puerto: int) -> dict:
    """Regimen que cognia.agent.model_profiles le asigna al modelo SERVIDO.
    forzar=True: el cache de props miente tras reiniciar en el mismo puerto."""
    url = f"http://127.0.0.1:{puerto}"
    try:
        from cognia.agent.model_profiles import perfil_del_agente
        p = perfil_del_agente(url, forzar=True)
        return {"regimen": p.get("tools", "?"), "perfil": p.get("nombre", "?"),
                "modelo": p.get("modelo", ""), "n_ctx": p.get("n_ctx"),
                "temperature": p.get("temperature"),
                "reasoning_effort": p.get("reasoning_effort", "")}
    except Exception as exc:
        return {"regimen": "?", "perfil": "", "error": f"{type(exc).__name__}: {exc}"}


def medir_tok_s(puerto: int, max_tokens: int, timeout: float) -> dict:
    """tok/s con una generacion corta REAL. Fuente preferida: el bloque
    'timings' de llama-server (predicted_per_second, lo que el server cronometro
    de verdad); si la build no lo trae, usage.completion_tokens / reloj.

    Con un razonador el contenido puede salir vacio (se gasta pensando): los
    tokens generados se cuentan igual, que es lo que mide esta celda."""
    url = f"http://127.0.0.1:{puerto}/v1/chat/completions"
    pedido = {
        "model": "local",
        "messages": [{"role": "user",
                      "content": "Escribi los numeros del 1 al 20 separados "
                                 "por comas. Solo los numeros."}],
        "max_tokens": max_tokens,
        "temperature": 0.0,
        "stream": False,
    }

    def _post(cuerpo: dict, tope: float) -> tuple:
        datos = json.dumps(cuerpo).encode("utf-8")
        req = urllib.request.Request(
            url, data=datos, headers={"Content-Type": "application/json"})
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=tope) as r:
            crudo = json.loads(r.read().decode("utf-8", "replace"))
        return crudo, time.time() - t0

    # Calentamiento: la PRIMERA peticion incluye grafos y cache frios y no es la
    # velocidad de generacion del modelo. Se descarta a proposito.
    try:
        _post(dict(pedido, max_tokens=1), min(timeout, 120))
    except Exception:
        pass
    try:
        crudo, seg = _post(pedido, timeout)
    except Exception as exc:
        return {"tok_s": None, "error": f"{type(exc).__name__}: {exc}"}

    t = crudo.get("timings") or {}
    uso = crudo.get("usage") or {}
    generados = t.get("predicted_n") or uso.get("completion_tokens") or 0
    if t.get("predicted_per_second"):
        return {"tok_s": round(float(t["predicted_per_second"]), 2),
                "fuente": "timings", "tokens": generados, "seg": round(seg, 2),
                "prompt_tok_s": round(float(t.get("prompt_per_second") or 0), 2),
                "finish_reason": (crudo.get("choices") or [{}])[0].get(
                    "finish_reason", "")}
    if generados and seg > 0:
        return {"tok_s": round(generados / seg, 2), "fuente": "usage/reloj",
                "tokens": generados, "seg": round(seg, 2),
                "finish_reason": (crudo.get("choices") or [{}])[0].get(
                    "finish_reason", "")}
    return {"tok_s": None, "error": "sin timings ni usage utilizables",
            "seg": round(seg, 2)}


def _ok_de_resultado(r) -> bool:
    """Veredicto de un banco importado. Existe porque el atajo obvio MIENTE:
    `r in (0, True, None)` da True para r=False (en Python False == 0) y para
    r=1 (1 == True), o sea que un banco que devolvia False, o el 1 de 'fallo'
    de toda la vida, se anotaba como OK en la tabla. Verificado en el interprete
    del repo antes de escribir esto."""
    if r is None:
        return True                      # corrio sin excepcion y sin veredicto
    if isinstance(r, bool):
        return r
    if isinstance(r, int):
        return r == 0                    # convencion de codigo de salida
    if isinstance(r, dict):
        return bool(r.get("ok"))
    return bool(r)


def correr_banco(spec: str, puerto: int, timeout: float, python_exe: str) -> dict:
    """Corre el banco contra el candidato servido en `puerto`.

    Dos formas:
      "py:paquete.modulo:funcion"  -> import y llamada. Se le pasan los kwargs
                                      que su firma acepte (url, puerto).
      cualquier otra cosa          -> comando. Si el primer token es .py, se
                                      antepone el python del venv.
    El veredicto duro es el codigo de salida (0 = ok) o lo que devuelva la
    funcion (_ok_de_resultado); el 'N/M' del texto se parsea best-effort para
    la tabla."""
    entorno = dict(os.environ)
    entorno["COGNIA_LLM_URL"] = f"http://127.0.0.1:{puerto}"
    entorno["LLAMA_SERVER_PORT"] = str(puerto)   # node/llama_backend ADOPTA ese
    entorno["PYTHONUTF8"] = "1"
    entorno["PYTHONPATH"] = str(_RAIZ) + os.pathsep + entorno.get("PYTHONPATH", "")
    t0 = time.time()

    if spec.startswith("py:"):
        destino = spec[3:]
        modulo, _, funcion = destino.partition(":")
        anterior = {k: os.environ.get(k) for k in
                    ("COGNIA_LLM_URL", "LLAMA_SERVER_PORT")}
        os.environ.update({k: entorno[k] for k in anterior})
        try:
            import importlib
            import inspect
            mod = importlib.import_module(modulo)
            fn = getattr(mod, funcion or "main")
            acepta = set(inspect.signature(fn).parameters)
            kwargs = {k: v for k, v in
                      (("url", entorno["COGNIA_LLM_URL"]), ("puerto", puerto))
                      if k in acepta}
            r = fn(**kwargs)
            return {"tipo": "import", "spec": spec, "ok": _ok_de_resultado(r),
                    "resultado": r if isinstance(r, (dict, list, int, float, str,
                                                     bool, type(None))) else str(r),
                    "puntaje": _puntaje(str(r)), "seg": round(time.time() - t0, 1)}
        except SystemExit as exc:
            # Un banco de este repo TERMINA en sys.exit (e2e_happy_path lo hace
            # literalmente). SystemExit es BaseException: sin esta rama se
            # escapaba del `except Exception`, se llevaba puesto el barrido
            # entero en el primer modelo y no quedaba ni tabla.
            codigo = exc.code if isinstance(exc.code, int) else (
                0 if exc.code is None else 1)
            return {"tipo": "import", "spec": spec, "ok": codigo == 0,
                    "codigo": codigo, "seg": round(time.time() - t0, 1)}
        except Exception as exc:
            return {"tipo": "import", "spec": spec, "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "seg": round(time.time() - t0, 1)}
        finally:
            for k, v in anterior.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    argv = shlex.split(spec, posix=(os.name != "nt"))
    argv = [a[1:-1] if len(a) > 1 and a[0] == a[-1] == '"' else a for a in argv]
    if argv and argv[0].lower().endswith(".py"):
        argv = [python_exe] + argv
    # Popen y no subprocess.run: al vencer el timeout, run() mata SOLO al hijo
    # directo. Un banco que se colgo despues de arrancar su propio llama-server
    # dejaria ese nieto con la VRAM tomada y los modelos que faltan medirian
    # con la GPU ocupada - un brazo envenenado que envenena a los siguientes.
    # Sin grupo de procesos propio a proposito: asi un Ctrl-C en esta consola
    # tambien se lleva al banco y no compite con la restauracion.
    try:
        proc = subprocess.Popen(argv, cwd=str(_RAIZ), env=entorno,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT)
    except Exception as exc:
        return {"tipo": "comando", "spec": spec, "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "seg": round(time.time() - t0, 1)}
    try:
        crudo, _ = proc.communicate(timeout=timeout)
        texto = (crudo or b"").decode("utf-8", "replace")
        cola = "\n".join(texto.strip().splitlines()[-12:])
        return {"tipo": "comando", "spec": spec, "ok": proc.returncode == 0,
                "codigo": proc.returncode, "puntaje": _puntaje(texto),
                "cola": cola, "seg": round(time.time() - t0, 1)}
    except subprocess.TimeoutExpired:
        matar_arbol(proc)
        try:
            crudo, _ = proc.communicate(timeout=30)
        except Exception:
            crudo = b""
        texto = (crudo or b"").decode("utf-8", "replace")
        return {"tipo": "comando", "spec": spec, "ok": False,
                "error": f"timeout de {timeout:.0f}s (arbol de procesos matado)",
                "cola": "\n".join(texto.strip().splitlines()[-12:]),
                "seg": round(time.time() - t0, 1)}
    except Exception as exc:
        matar_arbol(proc)
        return {"tipo": "comando", "spec": spec, "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "seg": round(time.time() - t0, 1)}


def _puntaje(texto: str) -> str:
    """El ultimo 'N/M' del output ('E2E CAMINO FELIZ: 5/5 OK'). Best-effort y
    declarado como tal: el veredicto duro es el codigo de salida."""
    hits = re.findall(r"(\d+)\s*/\s*(\d+)", texto or "")
    return f"{hits[-1][0]}/{hits[-1][1]}" if hits else ""


# ------------------------------------------------------------ restauracion --

def _guardar(salida: Path, informe: dict) -> None:
    """Escribe el JSON incremental. NUNCA lanza. `default=str` porque el detalle
    del regimen y el resultado del banco vienen de codigo ajeno: un objeto no
    serializable no puede tumbar el barrido - y mucho menos la restauracion, que
    corre en el mismo finally."""
    try:
        salida.write_text(json.dumps(informe, indent=2, ensure_ascii=False,
                                     default=str), encoding="utf-8")
    except Exception as exc:
        print(f"AVISO: no pude escribir {salida}: {exc}", file=sys.stderr)


def escribir_rescate(original: dict) -> None:
    """La linea original a disco ANTES de tocar nada. Si el script se muere de
    la peor manera posible, el dueno tiene el comando para copiar y pegar."""
    try:
        DIR_COGNIA.mkdir(parents=True, exist_ok=True)
        RESCATE.write_text(
            "# comparar_modelos.py - comando del llama-server ORIGINAL\n"
            f"# capturado {time.strftime('%Y-%m-%d %H:%M:%S')} (pid {original.get('pid')})\n"
            f"{original.get('linea', '')}\n", encoding="utf-8")
    except OSError as exc:
        print(f"AVISO: no pude escribir {RESCATE}: {exc}", file=sys.stderr)


class _SenalesEnEspera:
    """Ignora SIGINT/SIGTERM/SIGBREAK mientras dura la restauracion.

    SIN ESTO habia un camino que dejaba al dueno sin cerebro, que es el unico
    fallo que este script no puede tener: Ctrl-C -> el finally empieza a
    restaurar -> el modelo de ctx 200192 tarda un minuto en cargar -> el dueno
    aprieta Ctrl-C OTRA VEZ porque parece colgado -> KeyboardInterrupt DENTRO de
    restaurar() -> y como el flag ya estaba puesto, el atexit no reintentaba.
    :8080 vacio y nadie avisado. Aqui el segundo Ctrl-C no interrumpe nada."""

    def __enter__(self):
        self.previos = {}
        for s in ("SIGINT", "SIGTERM", "SIGBREAK"):
            num = getattr(signal, s, None)
            if num is None:
                continue
            try:
                self.previos[num] = signal.signal(num, signal.SIG_IGN)
            except (ValueError, OSError):
                pass
        return self

    def __exit__(self, *_):
        for num, previo in self.previos.items():
            try:
                signal.signal(num, previo)
            except (ValueError, OSError):
                pass
        return False


# Estados en los que el cerebro esta de vuelta (o en camino): solo estos apagan
# el reintento. Un 'fallo' DEBE dejar el cinturon armado.
_ESTADOS_BUENOS = ("intacto", "restaurado", "restaurado_con_dudas", "cargando")


def restaurar(original: dict, espera: float, log_dir: Path) -> dict:
    """Deja el server ORIGINAL sirviendo otra vez y lo VERIFICA. Se llama desde
    el finally y desde el atexit; el segundo intento SOLO ocurre si el primero
    fallo de verdad (antes el flag se ponia al entrar, asi que un fallo se
    tragaba el cinturon). Nunca lanza: lo que salga mal vuelve como dict."""
    global _RESTAURADO, _INTENTOS_RESTAURACION
    if not original:
        return {"estado": "nada que restaurar"}
    if _RESTAURADO:
        return {"estado": "ya hecha"}
    if _INTENTOS_RESTAURACION >= _MAX_INTENTOS:
        return {"estado": "fallo", "motivo": f"{_INTENTOS_RESTAURACION} intentos "
                f"agotados", "comando": original.get("linea", "")}
    _INTENTOS_RESTAURACION += 1
    with _SenalesEnEspera():
        try:
            r = _restaurar_una_vez(original, espera, log_dir)
        except BaseException as exc:      # incluido un KeyboardInterrupt colado
            r = {"estado": "fallo", "motivo": f"{type(exc).__name__}: {exc}",
                 "comando": original.get("linea", "")}
    if r.get("estado") in _ESTADOS_BUENOS:
        _RESTAURADO = True
    return r


def _restaurar_una_vez(original: dict, espera: float, log_dir: Path) -> dict:
    """Un intento: relanza la linea EXACTA del original y lo verifica por
    /health + identidad doble (linea de comando del proceso vivo y /props)."""
    puerto = original["puerto"]
    esperado = Path(original.get("modelo_ruta") or "").name

    print("\n" + "=" * 74)
    print("RESTAURANDO EL SERVER ORIGINAL (lo mas importante de este script)")
    print(f"Ctrl-C esta IGNORADO hasta {espera:.0f}s: no quiero dejarte sin "
          f"cerebro a mitad de camino.")
    print("=" * 74, flush=True)

    # 0) el original PUEDE estar cargando ya (un intento anterior lo relanzo y
    # la carga de 200192 tokens es lenta). Matarlo para relanzar otro encima
    # seria empezar de cero por impaciencia.
    if estado_puerto(puerto) == "cargando":
        cargando = pid_del_llama(puerto)
        if cargando and linea_de_comando(cargando) == original.get("linea"):
            print(f"  el original YA esta cargando (pid {cargando}); "
                  f"lo dejo terminar.")
            return {"estado": "cargando", "pid": cargando}

    # 1) ya esta el original? (barrido abortado antes de matarlo). Dos pruebas
    # de identidad independientes: la linea de comando del proceso vivo (la
    # prueba fuerte) y el /props. Si NINGUNA identifica al original, se relanza:
    # ante la duda, el dueno prefiere un reinicio de mas que otro modelo servido
    # en su :8080 sin que nadie lo note (la averia historica del :8088).
    if estado_puerto(puerto) == "ok":
        p = props_de(puerto)
        servido = p.get("modelo", "")
        pid_ahora = pid_del_llama(puerto)
        misma_linea = bool(pid_ahora) and (
            linea_de_comando(pid_ahora) == original.get("linea"))
        if misma_linea or not esperado or (servido and servido == esperado):
            print(f"  intacto: :{puerto} sirve {servido or '?'} "
                  f"(ctx {p.get('n_ctx')}) pid {pid_ahora or '?'}")
            return {"estado": "intacto", "props": p, "pid": pid_ahora,
                    "por": "linea de comando" if misma_linea else "/props"}
        print(f"  :{puerto} sirve {servido or '(props ilegible)'!r} y el "
              f"original era {esperado!r}: lo paro y relanzo el original.")

    # 2) liberar el puerto del candidato que haya quedado. SOLO si lo lanzamos
    # nosotros: un llama-server que no esta en _LANZADOS no es un candidato de
    # este barrido, es de otro, y no hay ninguna version de este script que
    # tenga derecho a matarlo.
    ajeno = pid_del_llama(puerto)
    if ajeno and ajeno in _LANZADOS:
        parar_pid(ajeno, puerto, 30)
    elif ajeno:
        print(f"  ME PLANTO: el pid {ajeno} sirve :{puerto} y NO lo lanzo este "
              f"barrido. No lo mato.", file=sys.stderr)
        print("  Si de verdad querias el original, corre esto vos:\n    "
              + original.get("linea", f"(ver {RESCATE})"), file=sys.stderr)
        return {"estado": "fallo", "motivo": f"el pid {ajeno} (ajeno) ocupa "
                f":{puerto}", "comando": original.get("linea", "")}

    # 3) relanzar la linea EXACTA
    argv = original.get("argv") or []
    if not argv:
        print("  NO TENGO la linea original: no puedo relanzar nada.",
              file=sys.stderr)
        return {"estado": "imposible", "motivo": "sin linea de comando"}
    log = log_dir / "restauracion.log"
    try:
        proc = lanzar(argv, log)
    except Exception as exc:
        print(f"  FALLO al relanzar: {exc}", file=sys.stderr)
        return {"estado": "fallo", "motivo": str(exc), "comando": original["linea"]}
    ok, seg, motivo = esperar_health(puerto, espera, proc)
    if not ok:
        # Vivo y todavia CARGANDO no es un fallo: es lento. Devolverlo como
        # fallo haria que el reintento lo MATARA y volviera a empezar.
        if proc.poll() is None and estado_puerto(puerto) == "cargando":
            print(f"  sigue CARGANDO tras {seg:.0f}s (pid {proc.pid}); esta "
                  f"vivo y va a responder solo. Log: {log}")
            return {"estado": "cargando", "pid": proc.pid, "seg": round(seg, 1),
                    "log": str(log)}
        print(f"  NO LEVANTO en {seg:.0f}s ({motivo}). Log: {log}",
              file=sys.stderr)
        print("  CORRE ESTO A MANO:\n    " + original["linea"], file=sys.stderr)
        return {"estado": "fallo", "motivo": motivo, "log": str(log),
                "comando": original["linea"], "seg": round(seg, 1)}
    p = props_de(puerto)
    coincide = (not esperado) or p.get("modelo", "") == esperado
    print(f"  OK en {seg:.0f}s - :{puerto} sirve {p.get('modelo') or '?'} "
          f"(ctx {p.get('n_ctx')}) pid {proc.pid}")
    if not coincide:
        print(f"  ATENCION: esperaba {esperado!r}. Revisa {log}",
              file=sys.stderr)
    return {"estado": "restaurado" if coincide else "restaurado_con_dudas",
            "seg": round(seg, 1), "pid": proc.pid, "props": p}


def _atexit_restaurar():
    """Cinturon del finally. Si el proceso se va por un camino raro, esto corre."""
    if _ORIGINAL and not _RESTAURADO:
        try:
            restaurar(_ORIGINAL, _ESPERA_RESTAURACION,
                      Path(_ORIGINAL.get("log_dir") or DIR_COGNIA / "logs"))
        except Exception as exc:
            print(f"atexit: la restauracion fallo: {exc}", file=sys.stderr)


def _manejar_senal(num, _frame):
    """SIGTERM/SIGBREAK -> KeyboardInterrupt, para caer en el finally que
    restaura. Ctrl-C ya llega como KeyboardInterrupt por su cuenta."""
    raise KeyboardInterrupt(f"senal {num}")


# ------------------------------------------------------------------- tabla --

def _corta(txt: str, n: int) -> str:
    txt = str(txt or "")
    return txt if len(txt) <= n else txt[:n - 3] + "..."


def imprimir_tabla(filas: list) -> None:
    cab = (f"{'MODELO':<38} {'CTX':>7} {'ARRANQUE':>9} {'REGIMEN':<8} "
           f"{'TOK/S':>7} {'BANCO':<12} {'SEG':>7}")
    print("\n" + cab)
    print("-" * len(cab))
    for f in filas:
        banco = f.get("banco") or {}
        if not banco:
            txt_banco = "-"
        elif banco.get("ok"):
            txt_banco = "OK " + (banco.get("puntaje") or "")
        else:
            txt_banco = "FALLO " + (banco.get("puntaje") or
                                    str(banco.get("codigo", "")))
        arranque = (f"{f['arranque_seg']:.0f}s" if f.get("arranco")
                    else "NO ARRANCA")
        tok = f.get("tok_s")
        print(f"{_corta(f['modelo'], 38):<38} {f.get('ctx', 0):>7} "
              f"{arranque:>9} {_corta(f.get('regimen', '?'), 8):<8} "
              f"{(f'{tok:.1f}' if tok else '-'):>7} "
              f"{_corta(txt_banco, 12):<12} {f.get('total_seg', 0):>7.0f}")


def ordenar_veredicto(filas: list) -> list:
    """Orden: arranca > banco ok > puntaje del banco > tok/s. El banco manda
    sobre la velocidad: un modelo rapido que no hace la tarea no sirve."""
    def clave(f):
        banco = f.get("banco") or {}
        num = 0.0
        if banco.get("puntaje"):
            try:
                a, b = banco["puntaje"].split("/")
                num = float(a) / max(float(b), 1.0)
            except ValueError:
                num = 0.0
        return (1 if f.get("arranco") else 0,
                1 if banco.get("ok") else 0,
                num,
                f.get("tok_s") or 0.0)
    return sorted(filas, key=clave, reverse=True)


# -------------------------------------------------------------------- main --

def _python_venv() -> str:
    """El python del repo: venv312 (regla dura del CLAUDE.md)."""
    cand = _RAIZ / "venv312" / "Scripts" / "python.exe"
    if cand.exists():
        return str(cand)
    cand = _RAIZ / "venv312" / "bin" / "python"
    return str(cand) if cand.exists() else sys.executable


def elegir_candidatos(patrones: str) -> list:
    """Rutas de .gguf a barrer. Sin --modelos, todo el catalogo servible (de los
    multiparte solo el 00001: llama.cpp carga el resto solo).

    Los mmproj-*.gguf quedan fuera del default: son proyectores de vision, no
    modelos; servir uno como --model es un 'no arranca' garantizado que solo
    ensuciaria la tabla. Se pueden pedir igual por --modelos si alguien quiere
    ver ese fallo con sus propios ojos."""
    catalogo = [m for m in sm.modelos() if not m.name.lower().startswith("mmproj")]
    if not patrones:
        return catalogo
    elegidos = []
    for p in [x.strip() for x in patrones.split(",") if x.strip()]:
        hit = sm.elegir(p)
        if hit is None:
            print(f"AVISO: ningun .gguf casa con {p!r}", file=sys.stderr)
        elif hit not in elegidos:
            elegidos.append(hit)
    return elegidos


def main() -> int:
    global _ORIGINAL, _ESPERA_RESTAURACION
    ap = argparse.ArgumentParser(
        description="Barrido de modelos en serie (una GPU, un puerto).")
    ap.add_argument("--puerto", type=int, default=PUERTO_DEFAULT)
    ap.add_argument("--modelos", default="",
                    help="trozos de nombre separados por coma (default: todos)")
    ap.add_argument("--ctx", type=int, default=CTX_DEFAULT,
                    help=f"ctx por defecto (default {CTX_DEFAULT}, conservador)")
    ap.add_argument("--ctx-modelo", action="append", default=[],
                    metavar="PATRON=N", help="override de ctx por modelo")
    ap.add_argument("--banco", default="",
                    help="comando (p.ej. scripts/e2e_happy_path.py) o "
                         "'py:modulo:funcion'")
    ap.add_argument("--banco-timeout", type=float, default=900.0)
    ap.add_argument("--espera-arranque", type=float, default=180.0,
                    help="segundos de /health por candidato (default 180)")
    ap.add_argument("--espera-parada", type=float, default=30.0)
    ap.add_argument("--espera-restauracion", type=float, default=300.0,
                    help="el original puede tardar mas: ctx 200192 carga lento")
    ap.add_argument("--tokens-medicion", type=int, default=256)
    ap.add_argument("--con-jinja", action="store_true",
                    help="agrega --jinja al candidato (el tool-calling nativo "
                         "se verifico con jinja; el server vivo no lo lleva)")
    ap.add_argument("--sin-original", action="store_true",
                    help="permite barrer aunque no haya server original vivo")
    ap.add_argument("--salida", default="",
                    help="JSON con todo (default: comparacion_<fecha>.json)")
    ap.add_argument("--python", default="", help="python para el banco")
    ap.add_argument("--dry-run", action="store_true",
                    help="imprime el plan SIN tocar ningun server")
    args = ap.parse_args()

    _ESPERA_RESTAURACION = args.espera_restauracion
    overrides = {}
    for o in args.ctx_modelo:
        patron, _, valor = o.partition("=")
        if not valor.isdigit():
            print(f"--ctx-modelo mal formado: {o!r} (PATRON=N)", file=sys.stderr)
            return 3
        overrides[patron] = int(valor)

    exe = sm.binario()
    if exe is None:
        print(f"No encuentro llama-server en {sm.DIR_LLAMA}", file=sys.stderr)
        return 3
    candidatos = elegir_candidatos(args.modelos)
    if not candidatos:
        print(f"No hay modelos que barrer en {sm.DIR_MODELOS}", file=sys.stderr)
        return 3
    python_exe = args.python or _python_venv()
    log_dir = DIR_COGNIA / "logs" / "comparar_modelos"

    # --- capturar el ORIGINAL antes de nada (solo lectura del proceso vivo) ---
    pid0 = pid_del_llama(args.puerto)
    linea0 = linea_de_comando(pid0) if pid0 else ""
    argv0 = argv_de_linea(linea0)
    props0 = props_de(args.puerto) if estado_puerto(args.puerto) == "ok" else {}
    original = {}
    if pid0 and argv0:
        ruta_modelo = ""
        for i, a in enumerate(argv0):
            if a in ("--model", "-m") and i + 1 < len(argv0):
                ruta_modelo = argv0[i + 1]
            elif a.startswith("--model="):
                ruta_modelo = a.split("=", 1)[1]
        original = {"pid": pid0, "linea": linea0, "argv": argv0,
                    "puerto": args.puerto, "modelo_ruta": ruta_modelo,
                    "props": props0, "log_dir": str(log_dir)}

    # HAY server pero no pude leer su linea: el peor caso posible. Si siguiera,
    # el paso 1 del bucle lo MATARIA (pid_del_llama si lo encuentra) y no
    # tendria con que devolverlo. --sin-original NO puede saltarse esto: esa
    # bandera dice 'no hay nada que restaurar', y aca SI hay.
    if pid0 and not original:
        print(f"\nABORTO: hay un llama-server VIVO (pid {pid0}) en "
              f":{args.puerto} y NO pude leer su linea de comando.\n"
              f"  Sin ella, pararlo seria dejarte sin cerebro y sin con que "
              f"devolvertelo. --sin-original NO sirve aca: esa bandera dice "
              f"'no hay nada que restaurar', y aca SI hay.\n"
              f"  Salidas: corre esto como administrador (para que CIM lea el "
              f"proceso), o para vos el server a mano y volve.", file=sys.stderr)
        if not args.dry_run:
            return 3

    print("=" * 74)
    print(f"ARNES DE BARRIDO - {len(candidatos)} modelo(s) en :{args.puerto}"
          + ("   [DRY-RUN: no toco ningun server]" if args.dry_run else ""))
    print("=" * 74)
    if original:
        print(f"Server ORIGINAL: pid {pid0}, {props0.get('modelo') or '?'} "
              f"(ctx {props0.get('n_ctx')})")
        print(f"  linea: {original['linea']}")
    else:
        print(f"Server ORIGINAL: no hay llama-server vivo en :{args.puerto} "
              f"(estado /health: {estado_puerto(args.puerto)})")
        if not args.sin_original and not args.dry_run:
            print("\nABORTO: sin la linea original no puedo devolverte el "
                  "cerebro al terminar. Si de verdad no hay server que "
                  "restaurar, repeti con --sin-original.", file=sys.stderr)
            return 3

    # Plan (se imprime siempre; en dry-run es TODO lo que pasa).
    plan = []
    for ruta in candidatos:
        ctx, fuente = ctx_de_modelo(ruta.name, args.ctx, overrides)
        argv = argv_candidato(original.get("argv") or [], exe, ruta,
                              args.puerto, ctx, args.con_jinja)
        gb = vram_estimada_gb(ruta, ctx)
        plan.append({"modelo": ruta.name, "ruta": str(ruta), "ctx": ctx,
                     "ctx_fuente": fuente, "argv": argv,
                     "vram_estimada_gb": round(gb, 2)})
        print(f"\n  {ruta.name}")
        print(f"    ctx {ctx} ({fuente}) - VRAM estimada {gb:.1f} GB de "
              f"{VRAM_MIB/1024:.1f} GB"
              + ("   <-- AVISO: puede no entrar" if gb > 14.5 else ""))
        print(f"    {' '.join(argv)}")
    if args.banco:
        print(f"\n  banco por modelo: {args.banco}  (timeout "
              f"{args.banco_timeout:.0f}s, python {python_exe})")
    print(f"\n  restauracion final: "
          + (original["linea"] if original else "(no hay original)"))

    if args.dry_run:
        print("\nDRY-RUN: no se paro ni arranco ningun server. "
              "Nada del sistema fue tocado.")
        return 0

    # A partir de aca SI se tocan servers. El orden importa: primero el
    # cinturon (_ORIGINAL + atexit) y DESPUES todo lo demas. Si el atexit se
    # registrara despues de escribir_rescate/armar el informe, una excepcion en
    # el medio saldria sin finally Y sin atexit.
    _ORIGINAL = original
    atexit.register(_atexit_restaurar)
    if original:
        escribir_rescate(original)
        print(f"\nComando de rescate guardado en {RESCATE}")
    for s in ("SIGTERM", "SIGBREAK"):
        if hasattr(signal, s):
            try:
                signal.signal(getattr(signal, s), _manejar_senal)
            except (ValueError, OSError):
                pass

    salida = Path(args.salida or (_RAIZ / f"comparacion_modelos_"
                                  f"{time.strftime('%Y%m%d_%H%M%S')}.json"))
    informe = {"fecha": time.strftime("%Y-%m-%d %H:%M:%S"),
               "puerto": args.puerto, "original": original,
               "banco": args.banco, "plan": plan, "modelos": [],
               "interrumpido": False, "restauracion": {}}
    filas = []
    interrumpido = False
    error_fatal = ""
    t_total = time.time()

    try:
        for i, entrada in enumerate(plan, 1):
            ruta = Path(entrada["ruta"])
            fila = {"modelo": ruta.name, "ctx": entrada["ctx"],
                    "vram_estimada_gb": entrada["vram_estimada_gb"],
                    "arranco": False, "arranque_seg": 0.0, "regimen": "-",
                    "tok_s": None, "banco": {}, "total_seg": 0.0, "notas": []}
            t0 = time.time()
            print(f"\n[{i}/{len(plan)}] {ruta.name} (ctx {entrada['ctx']})",
                  flush=True)

            # 1) parar lo que haya en el puerto
            vivo = pid_del_llama(args.puerto)
            if vivo:
                print(f"  parando pid {vivo}...", flush=True)
                if not parar_pid(vivo, args.puerto, args.espera_parada):
                    fila["notas"].append(
                        f"el pid {vivo} no solto :{args.puerto}")
                    print(f"  NO pude liberar :{args.puerto}; salto este modelo",
                          flush=True)
                    fila["total_seg"] = round(time.time() - t0, 1)
                    filas.append(fila)
                    informe["modelos"] = filas
                    _guardar(salida, informe)
                    continue

            # 2) arrancar el candidato. El lanzamiento va en try: si el exe de
            # la linea clonada no existe (ruta relativa, binario movido), el
            # barrido salta ESE modelo en vez de morirse entero.
            log = log_dir / f"{ruta.stem[:40]}.log"
            try:
                proc = lanzar(entrada["argv"], log)
            except Exception as exc:
                fila["notas"].append(f"no pude lanzarlo: "
                                     f"{type(exc).__name__}: {exc}")
                print(f"  NO LANZA ({type(exc).__name__}: {exc})", flush=True)
                fila["total_seg"] = round(time.time() - t0, 1)
                filas.append(fila)
                informe["modelos"] = filas
                _guardar(salida, informe)
                continue
            fila["pid"] = proc.pid
            fila["log"] = str(log)
            ok, seg, motivo = esperar_health(args.puerto, args.espera_arranque,
                                             proc)
            fila["arranque_seg"] = round(seg, 1)
            if not ok:
                fila["notas"].append(motivo)
                print(f"  NO ARRANCA ({motivo}). Log: {log}", flush=True)
                parar_pid(proc.pid, args.puerto, args.espera_parada)
                fila["total_seg"] = round(time.time() - t0, 1)
                filas.append(fila)
                informe["modelos"] = filas
                _guardar(salida, informe)
                continue
            fila["arranco"] = True
            print(f"  /health ok en {seg:.0f}s (pid {proc.pid})", flush=True)

            # 3) regimen (dato del experimento, no bug)
            reg = regimen_del_server(args.puerto)
            fila["regimen"] = reg.get("regimen", "?")
            fila["regimen_detalle"] = reg
            fila["props"] = props_de(args.puerto)
            print(f"  regimen: {fila['regimen']} ({reg.get('perfil', '')})",
                  flush=True)

            # 4) tok/s
            med = medir_tok_s(args.puerto, args.tokens_medicion,
                              timeout=max(180.0, args.espera_arranque))
            fila["tok_s"] = med.get("tok_s")
            fila["medicion"] = med
            print(f"  tok/s: {med.get('tok_s')} "
                  f"({med.get('fuente') or med.get('error')})", flush=True)

            # 5) banco
            if args.banco:
                print(f"  banco: {args.banco} ...", flush=True)
                fila["banco"] = correr_banco(args.banco, args.puerto,
                                             args.banco_timeout, python_exe)
                b = fila["banco"]
                print(f"  banco: {'OK' if b.get('ok') else 'FALLO'} "
                      f"{b.get('puntaje') or ''} en {b.get('seg')}s "
                      f"{b.get('error') or ''}", flush=True)

            # 6) parar el candidato
            parar_pid(proc.pid, args.puerto, args.espera_parada)
            fila["total_seg"] = round(time.time() - t0, 1)
            filas.append(fila)
            informe["modelos"] = filas
            _guardar(salida, informe)

    except KeyboardInterrupt:
        interrumpido = True
        informe["interrumpido"] = True
        print("\nINTERRUMPIDO. Voy igual a restaurar el server original.",
              flush=True)
    except BaseException as exc:
        # A proposito BaseException y no Exception: un SystemExit de un banco
        # importado, o cualquier bicho raro, NO puede saltarse el veredicto ni
        # el exit 2. Antes se iba por traceback con codigo 1 aunque el cerebro
        # hubiera quedado abajo, que es justo el caso que hay que gritar.
        error_fatal = f"{type(exc).__name__}: {exc}"
        informe["error"] = error_fatal
        traceback.print_exc()
        print(f"\nEXCEPCION en el barrido ({error_fatal}). Voy igual a "
              f"restaurar el server original.", flush=True)
    finally:
        informe["modelos"] = filas
        informe["restauracion"] = restaurar(original, args.espera_restauracion,
                                            log_dir)
        informe["segundos_totales"] = round(time.time() - t_total, 1)
        _guardar(salida, informe)

    ordenadas = ordenar_veredicto(filas)
    imprimir_tabla(ordenadas)
    print("\nVEREDICTO (arranca > banco > puntaje > tok/s):")
    for pos, f in enumerate(ordenadas, 1):
        motivo = ("no arranca" if not f.get("arranco") else
                  ("banco " + (("OK " + (f["banco"].get("puntaje") or ""))
                               if f["banco"].get("ok") else "FALLO")
                   if f.get("banco") else f"{f.get('tok_s')} tok/s"))
        print(f"  {pos}. {_corta(f['modelo'], 48):<48} {f.get('regimen','-'):<7}"
              f" {motivo}")
    print(f"\nJSON: {salida}")

    rest = (informe.get("restauracion") or {}).get("estado", "")
    if rest not in _ESTADOS_BUENOS + ("nada que restaurar", "ya hecha"):
        # Lista BLANCA y no negra: un estado nuevo que nadie previo tiene que
        # salir por el camino que grita, no por el que calla.
        print("\n" + "!" * 74)
        print(f"EL SERVER ORIGINAL NO QUEDO LEVANTADO (estado {rest!r}). "
              f"Corre esto YA:")
        print("  " + (original.get("linea") or f"(ver {RESCATE})"))
        print("!" * 74, file=sys.stderr)
        return 2
    if rest == "cargando":
        print(f"\nEl original esta CARGANDO en :{args.puerto} (vivo, todavia "
              f"sin /health). Dale un minuto y verifica.")
    if error_fatal or interrumpido or any(not f.get("arranco") for f in filas) \
            or any(f.get("banco") and not f["banco"].get("ok") for f in filas):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
