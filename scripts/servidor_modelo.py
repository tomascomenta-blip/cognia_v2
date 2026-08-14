# -*- coding: utf-8 -*-
"""
servidor_modelo.py - arrancar y parar UN llama-server sin romper el sistema.

POR QUE EXISTE (2026-08-13): el arnes de comparacion de modelos necesita
reciclar el backend (cargar candidato, medir, devolver el cerebro del dueno tal
como estaba). Esa es la pieza peligrosa de todo el arnes: el :8080 que corre
AHORA es el cerebro del usuario y de la flota compartida.

Las tres lecciones del repo que este modulo hace CUMPLIR en codigo (no en prosa):

1. `taskkill /IM llama-server.exe /F` mata TODOS los llama-server de la maquina,
   incluida la flota compartida que sirven otros procesos (cazado en
   scripts/e2e_happy_path.py:101 y cognia/summoner.py:13). Aca se mata SOLO el
   proceso propio: por handle de Popen, o por PID con `taskkill /PID`. El
   martillo global NO aparece en este fichero - hay un test que lo verifica
   leyendo el fuente.
2. Antes de tocar nada hay que poder RESTAURAR lo que habia. `linea_de_comando_
   actual()` lee la cmdline COMPLETA del proceso vivo via CIM (Win32_Process) y
   `restaurar()` la relanza byte a byte. Sin ese paso, "lo devuelvo despues" es
   una promesa sin respaldo.
3. El :8080 puede tener DOS listeners (tailscaled escucha en la IP de la malla:
   "el summoner pierde el cerebro por tailscaled"). Por eso el dueno del puerto
   se busca por 127.0.0.1 Y se confirma que el proceso sea un llama-server.
4. "Responde 200" NO es "esta el cerebro". restaurar() prueba la IDENTIDAD del
   que contesta (cmdline del proceso que escucha, o el .gguf que declara
   /v1/models) antes de darse por satisfecha; darse por bueno un 200 cualquiera
   es como el :8088 sirvio un modelo retirado durante semanas.
5. La restauracion no puede depender de que el que llama se acuerde: por eso
   existe prestar_puerto(), que captura ANTES de matar, se niega a matar lo que
   no sabria relanzar, y devuelve el puerto en el finally + atexit + SIGTERM.

Ademas: NO se pasa `--log-disable` (a diferencia de node/llama_backend.py). En
el arnes queremos VER por que un modelo no carga; un server que muere mudo es
media hora perdida por candidato.

API (todo importable; el CLI de este fichero es SOLO de lectura a proposito -
ver main(): nadie deberia poder apagar el cerebro tecleando un comando):

    prestar_puerto(puerto) -> context manager       # LA FORMA CORRECTA de usarlo
    linea_de_comando_actual(puerto) -> dict | None   # cmdline viva, para restaurar
    construir_cmd(exe, gguf, puerto, ctx, extra_flags) -> list[str]
    arrancar(gguf, puerto, ctx, extra_flags) -> Popen
    esperar_salud(puerto, timeout_s) -> bool
    parar(proc, timeout_s) -> bool                   # SOLO ese proceso
    restaurar(cmdline, timeout_s) -> Popen | None
    ctx_seguro(gguf, vram_libre_mib) -> int

Las piezas sueltas (parar/arrancar/restaurar) dejan la restauracion en manos de
la disciplina del que llama, y "me acuerdo de restaurar en el finally" no es un
mecanismo. Por eso la puerta de entrada es `prestar_puerto()`: captura la
cmdline ANTES de matar nada, se niega a matar lo que no sabria relanzar, deja el
comando de rescate en disco, y restaura en el finally + atexit + SIGTERM.

    with prestar_puerto(8080) as original:      # el cerebro queda parado aca
        proc = arrancar(candidato, 8080, ctx)
        try:
            ...medir...
        finally:
            parar(proc)
    # al salir del with -por return, excepcion o Ctrl-C- el cerebro vuelve

Solo stdlib (+ el lector GGUF de scripts/ctx_maximo.py y cognia/puertos.py, que
tiene el "quien escucha el puerto": ninguno de los dos se duplica aca).
"""

from __future__ import annotations

import atexit
import contextlib
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional, Sequence, Union

# scripts/ no es paquete instalado: la raiz del repo entra a mano, igual que en
# scripts/servir_flota.py. Asi `from scripts import ctx_maximo` funciona tanto
# corriendo este fichero como importandolo desde tests/.
_RAIZ = Path(__file__).resolve().parent.parent
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

from scripts import ctx_maximo                      # noqa: E402  (lector GGUF)
# El paquete es la fuente de verdad de "quien escucha el puerto" (WP: scripts/
# no viaja en el wheel y el summoner lo necesita). Import DESPUES de meter la
# raiz en sys.path: asi funciona igual corriendo el script o importandolo.
from cognia.puertos import (pid_del_puerto,          # noqa: E402,F401
                            pid_llama_del_puerto,
                            procesos_llama)

DIR_LLAMA = Path.home() / ".cognia" / "llama"
DIR_MODELOS = Path.home() / ".cognia" / "models"
DIR_LOGS = Path.home() / ".cognia" / "logs"
# El comando del server original, en disco, desde el segundo cero. Es lo unico
# que sobrevive a un `taskkill /F` del propio arnes o a un corte de luz: ni el
# finally ni el atexit corren en esos casos.
RESCATE = Path.home() / ".cognia" / "servidor_modelo_restaurar.txt"
PUERTO_CEREBRO = 8080          # el que sondea cognia/llm_local.py

# Medido con nvidia-smi en esta maquina (RTX 5060 Ti): 16311 MiB totales.
VRAM_TOTAL_MIB = 16311
# Colchon para buffers de computo, CUDA graphs y el escritorio de Windows.
# Mismo 1.2 GB que usa scripts/ctx_maximo.py.
RESERVA_MIB = 1229
# El KV estimado por cabecera es una COTA, no la verdad (ver ctx_seguro): se
# recorta otro 20% para no quedar al filo.
FACTOR_SEGURIDAD = 0.8
# llama.cpp reparte el contexto en bloques; un ctx multiplo de 256 evita que
# el server redondee por su cuenta y reporte un n_ctx distinto del pedido.
MULTIPLO_CTX = 256
CTX_MINIMO = 4096              # por debajo de esto el modelo no sirve al arnes
# Techo del arnes. Mas arriba SOLO con celdas MEDIDAS (cognia/summoner.py
# ESCALERA_CTX): la formula de cabecera no autoriza ventanas gigantes.
TECHO_CTX = 131072

_TIEMPO_ESPERA = 240.0         # igual que servir_modelo.py / llama_backend.py


# ---------------------------------------------------------------------------
# 1. Que esta corriendo AHORA (lectura pura: no toca ningun proceso)
# ---------------------------------------------------------------------------

def partir_cmdline(cadena: str) -> list[str]:
    """Parte una cmdline de Windows en argumentos, respetando las comillas.

    No es shlex: en Windows la barra invertida NO escapa (las rutas van llenas
    de `\\`), asi que shlex.split(posix=True) destrozaria
    `C:\\Users\\usuario\\.cognia\\...`. Solo la comilla doble agrupa.
    Limite declarado: no implementa el caso raro `\\"` de MSVCRT (llama-server
    nunca lo produce) ni las comillas simples (que en cmd no agrupan)."""
    partes: list[str] = []
    actual: list[str] = []
    dentro = False
    hubo_token = False
    for ch in cadena:
        if ch == '"':
            dentro = not dentro
            hubo_token = True                  # "" es un argumento vacio valido
            continue
        if ch in " \t" and not dentro:
            if actual or hubo_token:
                partes.append("".join(actual))
                actual, hubo_token = [], False
            continue
        actual.append(ch)
    if actual or hubo_token:
        partes.append("".join(actual))
    return partes


def puerto_de_argv(argv: Sequence[str], por_defecto: int = PUERTO_CEREBRO) -> int:
    """El --port de una cmdline ya partida. Sin el flag, llama-server usa 8080,
    que es justo el puerto del cerebro: por eso el default NO es 0."""
    for i, a in enumerate(argv):
        if a == "--port" and i + 1 < len(argv):
            try:
                return int(argv[i + 1])
            except ValueError:
                break
        if a.startswith("--port="):
            try:
                return int(a.split("=", 1)[1])
            except ValueError:
                break
    return por_defecto


# Quien escucha un puerto (y si es un llama-server) vive en cognia/puertos.py
# desde 2026-08-13: scripts/ NO viaja en el wheel y el summoner necesita esas
# tres funciones para adoptar el server vivo. Aca se RE-EXPORTAN para no
# duplicar la logica -- dos copias del mismo netstat es como el :8088 sirvio
# un modelo retirado durante semanas. `_procesos_llama` conserva el nombre
# privado historico porque es la seam que inyectan los tests de este fichero.
_procesos_llama = procesos_llama


def linea_de_comando_actual(puerto: int = PUERTO_CEREBRO) -> Optional[dict]:
    """La cmdline COMPLETA del llama-server que sirve ese puerto AHORA.

    Devuelve {'pid': int, 'cmdline': str, 'argv': list[str]} o None si no hay
    ninguno. Es el seguro de vida del arnes: se guarda ANTES de tocar nada y se
    le pasa a restaurar() al terminar, para devolver el server del dueno con
    sus flags exactos (--ctx-size 200192, --cache-reuse, --spec-type...), no
    con los que este modulo crea que son buenos.

    Se elige por --port de la propia cmdline (fuente de verdad del proceso) y,
    si hubiera varios candidatos, se desempata con quien escucha de verdad en
    127.0.0.1:puerto."""
    vivos = _procesos_llama()
    if not vivos:
        return None
    candidatos = [p for p in vivos
                  if puerto_de_argv(partir_cmdline(p["cmdline"])) == puerto]
    if not candidatos:
        return None
    if len(candidatos) > 1:
        dueno = pid_del_puerto(puerto)
        candidatos = [p for p in candidatos if p["pid"] == dueno] or candidatos
    elegido = candidatos[0]
    return {"pid": elegido["pid"], "cmdline": elegido["cmdline"],
            "argv": partir_cmdline(elegido["cmdline"])}


# ---------------------------------------------------------------------------
# 2. Salud del puerto
# ---------------------------------------------------------------------------

def estado(puerto: int, timeout: float = 2.0) -> str:
    """'ok' | 'cargando' | 'ausente'.

    El 503 de /health NO es ausencia: es un server que esta cargando su modelo
    (A1 2026-08-01). Tratarlo como ausente es lo que hacia arrancar un segundo
    server sobre el mismo puerto."""
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{puerto}/health", timeout=timeout):
            return "ok"
    except urllib.error.HTTPError as e:
        return "cargando" if e.code == 503 else "ok"
    except (urllib.error.URLError, OSError):
        return "ausente"


def _cadenas(dato) -> list:
    """Todas las cadenas de un JSON anidado, en orden. Sirve para no atarse a la
    forma exacta de /props y /v1/models (cambian entre builds del server)."""
    if isinstance(dato, str):
        return [dato]
    if isinstance(dato, dict):
        return [s for v in dato.values() for s in _cadenas(v)]
    if isinstance(dato, list):
        return [s for v in dato for s in _cadenas(v)]
    return []


def modelo_servido(puerto: int, timeout: float = 5.0) -> str:
    """El NOMBRE del .gguf que ese puerto sirve AHORA, '' si no se pudo leer.

    Es la prueba de identidad: 'el puerto responde' no es 'el puerto sirve MI
    modelo'. Sin esto, restaurar() se da por satisfecha con cualquier cosa que
    conteste 200 - que es exactamente como el :8088 sirvio un modelo retirado
    durante semanas (memoria del repo).
    Verificado contra el server vivo el 2026-08-13: /v1/models trae la ruta
    completa del GGUF; /props queda de respaldo."""
    for ruta in ("/v1/models", "/props"):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{puerto}{ruta}",
                                        timeout=timeout) as r:
                datos = json.loads(r.read().decode("utf-8", "replace"))
        except Exception:
            continue
        for s in _cadenas(datos):
            if s.lower().endswith(".gguf"):
                return Path(s).name
    return ""


def modelo_de_argv(argv: Sequence[str]) -> str:
    """El nombre del .gguf que pide una cmdline ('' si no lleva --model)."""
    for i, a in enumerate(argv):
        if a == "--model" and i + 1 < len(argv):
            return Path(argv[i + 1]).name
        if a.startswith("--model="):
            return Path(a.split("=", 1)[1]).name
    return ""


def puerto_libre(puerto: int) -> bool:
    """True si un server nuevo PODRIA bindear ahi. No es lo mismo que 'no
    contesta /health': un llama-server muriendo (o colgado) mantiene el socket y
    el siguiente candidato falla con 'address in use', que en la tabla del arnes
    parece un modelo que no carga.

    Se prueba BINDEANDO, no conectando: un connect() contra un server que no
    hace accept() llena la cola de backlog y a partir de la segunda prueba
    devuelve 'refused', o sea que el puerto ocupado se declararia libre
    (verificado con un socket listen(1) sin accept en los tests).
    Sin SO_REUSEADDR a proposito: con ese flag Windows deja bindear encima de
    otro socket y la prueba diria que si a un puerto tomado."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", int(puerto)))
        return True
    except OSError:
        return False           # ante la duda, ocupado (no se arranca encima)
    finally:
        s.close()


def esperar_puerto_libre(puerto: int, timeout_s: float = 30.0) -> bool:
    """Espera a que el puerto quede libre. Matar el proceso NO libera el puerto
    en el mismo instante: llama-server tiene que soltar 11 GB de VRAM antes de
    que Windows cierre el socket, y arrancar el siguiente candidato en ese hueco
    es un 'bind: address already in use' que parece un modelo roto."""
    limite = time.time() + float(timeout_s)
    while time.time() < limite:
        if puerto_libre(puerto):
            return True
        time.sleep(0.3)
    return puerto_libre(puerto)


def esperar_salud(puerto: int, timeout_s: float = _TIEMPO_ESPERA,
                  proc: Optional[subprocess.Popen] = None) -> bool:
    """Espera a que /health responda ok. True si respondio, False si no.

    Backoff de 0.5s a 5s (x1.5): sondear cada 0.5s durante 4 minutos son 480
    peticiones contra un proceso que esta peleando por la VRAM.
    Con `proc`, corta APENAS el proceso muere: un modelo que no cabe en la GPU
    muere en 20s y esperar los 240 completos son 4 minutos tirados por
    candidato (y el arnes corre varios)."""
    limite = time.time() + float(timeout_s)
    espera = 0.5
    while time.time() < limite:
        if estado(puerto) == "ok":
            return True
        if proc is not None and proc.poll() is not None:
            print(f"[servidor_modelo] el server murio al arrancar (codigo "
                  f"{proc.returncode}); no espero mas.", file=sys.stderr)
            return False
        time.sleep(min(espera, max(0.0, limite - time.time())))
        espera = min(espera * 1.5, 5.0)
    return estado(puerto) == "ok"


# ---------------------------------------------------------------------------
# 3. Arrancar
# ---------------------------------------------------------------------------

def binario() -> Optional[Path]:
    """El llama-server instalado (misma convencion que servir_modelo.py)."""
    for nombre in ("llama-server.exe", "llama-server"):
        ruta = DIR_LLAMA / nombre
        if ruta.exists():
            return ruta
    return None


def _hilos() -> int:
    """Los hilos que usa el lanzador del repo (node/llama_backend.py): el techo
    es cpu-1 pero manda hilos_cpu_optimos (medido: 6 fisicos > 12 logicos)."""
    techo = max(1, (os.cpu_count() or 4) - 1)
    try:
        from node.cpu_threads import hilos_cpu_optimos
        return int(hilos_cpu_optimos(techo))
    except Exception:
        return techo


def _flags_proceso(despegar: bool) -> dict:
    """Los kwargs de Popen que impiden que el hijo muera con la consola.

    Windows manda el CTRL_C_EVENT a TODO el grupo de procesos de la consola: sin
    CREATE_NEW_PROCESS_GROUP, un Ctrl-C del dueno mata tambien al server que
    acabamos de restaurar - o sea, el gesto de abortar el arnes se lleva puesto
    el cerebro. DETACHED_PROCESS ademas lo desata de la consola, para que cerrar
    la ventana no lo tumbe; solo se usa cuando la salida va a un fichero, porque
    un proceso sin consola escribe su stdout al vacio."""
    if os.name == "nt":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP
        if despegar:
            flags |= subprocess.DETACHED_PROCESS
        return {"creationflags": flags}
    return {"start_new_session": True}


def _lanzar(argv: Sequence[str], log: Union[str, Path, None]):
    """Popen con la salida a `log` (append) o heredada. El handle del fichero se
    CIERRA aca mismo: el hijo se queda con su propia copia del descriptor, asi
    que cerrarlo no le corta el log (misma regla que
    scripts/comparar_modelos.py:lanzar). Colgarlo del Popen 'para que
    sobreviva' solo dejaba un handle abierto por candidato."""
    if log is None:
        return subprocess.Popen(list(argv), **_flags_proceso(False))
    log = Path(log)
    log.parent.mkdir(parents=True, exist_ok=True)
    # append: el arnes corre varios candidatos y pisar el log del anterior borra
    # justamente el error que se quiere leer.
    with open(log, "ab") as fh:
        return subprocess.Popen(list(argv), stdout=fh, stderr=fh,
                                **_flags_proceso(True))


def construir_cmd(exe: Union[str, Path], gguf: Union[str, Path],
                  puerto: int = PUERTO_CEREBRO, ctx: int = 8192,
                  extra_flags: Sequence[str] = ()) -> list[str]:
    """El comando completo del server del arnes. Funcion pura: se testea sin
    lanzar nada.

    Los flags calcan los del repo (scripts/servir_modelo.py + node/
    llama_backend.py), con dos diferencias DELIBERADAS:
      - SIN --log-disable: en el arnes hay que ver por que un modelo no carga.
        El server vivo del dueno si lo lleva, y por eso restaurar() usa su
        cmdline literal en vez de esta.
      - CON --jinja: el regimen NATIVO (tool-calling del server) que mide
        cognia/agent/model_profiles.py necesita la plantilla del GGUF; sin
        --jinja todos los candidatos caerian a TEXTO y la comparacion medirira
        otra cosa.
    --parallel 1 explicito: las builds recientes usan 4 slots y PARTEN el
    --ctx-size entre ellos (HTTP 500 en el 50% del gate BoN, 2026-07-28).

    `extra_flags` PISA los defaults: si trae un flag que ya estaba (p.ej.
    --flash-attn off o --cache-type-k q8_0), el default se quita en vez de
    aparecer dos veces (llama-server no promete que gane el ultimo)."""
    extra = [str(x) for x in extra_flags]
    pisados = {a.split("=", 1)[0] for a in extra if a.startswith("--")}
    hilos = str(_hilos())
    # (flag, valor); valor None = flag booleano.
    base = [
        ("--model", str(gguf)),
        # --host 127.0.0.1 explicito: el modelo local no se expone a la LAN
        # por el default del binario (misma regla que llama_backend.py).
        ("--host", "127.0.0.1"),
        ("--port", str(int(puerto))),
        ("--ctx-size", str(int(ctx))),
        ("--parallel", "1"),
        ("--n-gpu-layers", "99"),
        ("--threads", hilos),
        ("--threads-batch", hilos),
        ("--cache-reuse", "256"),
        # b9391+ defaultea --cache-ram 8192 MiB por server: con dos servers
        # coexistiendo es swap latente en los 31 GB de esta maquina.
        ("--cache-ram", "1024"),
        ("--prio", "2"),
        ("--flash-attn", "on"),
        ("--jinja", None),
    ]
    orden = [str(exe)]
    for flag, valor in base:
        if flag in pisados:
            continue
        orden.append(flag)
        if valor is not None:
            orden.append(valor)
    return orden + extra


def arrancar(gguf: Union[str, Path], puerto: int = PUERTO_CEREBRO,
             ctx: int = 8192, extra_flags: Sequence[str] = (),
             exe: Union[str, Path, None] = None,
             log: Union[str, Path, None] = None) -> subprocess.Popen:
    """Lanza UN llama-server y devuelve su Popen (el handle ES el permiso de
    matarlo despues: sin el solo queda el martillo global).

    NO espera la salud: eso es esperar_salud(puerto, timeout, proc=...), que
    ademas corta si el proceso muere.

    Se niega a arrancar si el puerto ya esta ocupado (ok o cargando). Ese
    chequeo es la diferencia entre "reciclo el backend" y "le pongo un segundo
    server encima al cerebro del dueno y los dos pelean por la VRAM".

    La salida del server se hereda (se VE en la consola) o va a `log` si se
    pasa una ruta. Nunca a DEVNULL: un candidato que no cabe en la GPU tiene
    que decirlo."""
    est = estado(puerto)
    if est != "ausente":
        raise RuntimeError(
            f"ya hay un llama-server en :{puerto} ({est}). No arranco otro "
            f"encima: para el suyo primero (parar()) o elige otro puerto.")
    if not puerto_libre(puerto):
        # /health puede no contestar (server muriendo, o algo que no habla HTTP)
        # y el socket seguir tomado: sin este chequeo el candidato arranca, no
        # puede bindear y muere, y el informe lo anota como 'modelo que no carga'.
        raise RuntimeError(
            f"el socket :{puerto} sigue tomado aunque /health no conteste. "
            f"Espera con esperar_puerto_libre() o elige otro puerto.")
    binario_final = Path(exe) if exe else binario()
    if binario_final is None:
        raise FileNotFoundError(f"no encuentro llama-server en {DIR_LLAMA}")
    gguf = Path(gguf)
    if not gguf.is_file():
        raise FileNotFoundError(f"no existe el GGUF {gguf}")

    orden = construir_cmd(binario_final, gguf, puerto, ctx, extra_flags)
    proc = _lanzar(orden, log)
    print(f"[servidor_modelo] pid {proc.pid}: {gguf.name} en :{puerto} "
          f"(ctx {ctx})")
    return proc


# ---------------------------------------------------------------------------
# 4. Parar - SOLO el proceso propio
# ---------------------------------------------------------------------------

def _cmd_kill(pid: int) -> list[str]:
    """Kill SELECTIVO por PID. PROHIBIDO /IM en este modulo: ese martillo mata
    todos los llama-server de la maquina, incluida la flota compartida
    (:8080/:8081) que sirven otros procesos. Misma regla que
    cognia/summoner.py:_cmd_kill."""
    if os.name == "nt":
        return ["taskkill", "/PID", str(int(pid)), "/F"]
    return ["kill", "-9", str(int(pid))]


def parar(proc: Union[subprocess.Popen, int], timeout_s: float = 20.0) -> bool:
    """Mata SOLO ese proceso. True si quedo muerto.

    Con un Popen: terminate() y, si no muere en la mitad del plazo, kill().
    Con un PID pelado (int): taskkill /PID (Windows) o kill -9 (POSIX) - nunca
    por nombre de imagen.

    Un proceso que ya estaba muerto cuenta como exito (idempotente: el arnes
    llama a parar() en el finally de cada candidato)."""
    if isinstance(proc, int):
        pid = proc
        if not _pid_vivo(pid):
            return True                      # ya estaba muerto: idempotente
        try:
            subprocess.run(_cmd_kill(pid), capture_output=True, timeout=15)
        except Exception as exc:
            print(f"[servidor_modelo] kill de pid {pid} fallo: {exc}",
                  file=sys.stderr)
            return False
        # taskkill vuelve ANTES de que el proceso termine de morir (soltar la
        # VRAM tarda): preguntar una sola vez daria False en un kill que si
        # funciono, y el arnes concluiria que no puede tocar el puerto.
        limite = time.time() + max(1.0, float(timeout_s))
        while time.time() < limite:
            if not _pid_vivo(pid):
                return True
            time.sleep(0.3)
        return not _pid_vivo(pid)

    if proc.poll() is not None:
        return True
    mitad = max(1.0, float(timeout_s) / 2.0)
    proc.terminate()
    try:
        proc.wait(timeout=mitad)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=mitad)
        except subprocess.TimeoutExpired:
            print(f"[servidor_modelo] pid {proc.pid} no murio en "
                  f"{timeout_s}s", file=sys.stderr)
            return False
    return True


def _pid_vivo(pid: int) -> bool:
    """Un PID es hipotesis, no verdad (cognia/summoner.py)."""
    if not pid:
        return False
    if os.name == "nt":
        try:
            salida = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                                    capture_output=True, text=True,
                                    errors="replace", timeout=15).stdout
            return str(pid) in salida
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# 5. Restaurar el server original
# ---------------------------------------------------------------------------

def escribir_rescate(cmdline: str, ruta: Union[str, Path, None] = None) -> None:
    """Deja el comando del server original en disco ANTES de tocar nada.

    Ni el `finally` ni el `atexit` corren si al arnes lo matan con /F, si se va
    la luz o si el interprete se cae. Lo unico que sobrevive a eso es un fichero
    con la linea para copiar y pegar.

    El destino se resuelve EN CADA LLAMADA (`ruta or RESCATE`) y no como valor
    por defecto: un `ruta=RESCATE` en la firma congela la constante en el import
    y deja el fichero real fuera de control de quien la reapunte - los tests
    escribian en el ~/.cognia de verdad creyendo que escribian en su tmp."""
    try:
        ruta = Path(ruta or RESCATE)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(
            "# servidor_modelo.py - comando del llama-server ORIGINAL\n"
            f"# capturado {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"{cmdline}\n", encoding="utf-8")
    except OSError as exc:
        print(f"[servidor_modelo] AVISO: no pude escribir {ruta}: {exc}",
              file=sys.stderr)


def _ya_esta_el_original(puerto: int, argv: Sequence[str],
                         cmdline: str) -> bool:
    """True solo si lo que responde en el puerto ES el server original.

    Dos pruebas independientes, como en scripts/comparar_modelos.py:
      1. la cmdline del proceso que ESCUCHA ahi es identica a la nuestra;
      2. el .gguf que declara /v1/models es el de nuestro --model.
    'Responde 200' NO es prueba: un dashboard, un tunel o el candidato que se
    quedo colgado tambien responden, y darlos por buenos es como el :8088
    sirvio un modelo retirado durante semanas sin que nadie lo notara.

    Si NINGUNA de las dos pruebas se puede leer, esto devuelve False y el
    original se relanza: ante la duda, un reinicio de mas es recuperable y un
    :8080 sirviendo otro modelo sin que nadie lo note, no (misma eleccion que
    scripts/comparar_modelos.py:restaurar)."""
    vivo = linea_de_comando_actual(puerto)
    if vivo and vivo["cmdline"].strip() == cmdline.strip():
        return True
    esperado = modelo_de_argv(argv)
    servido = modelo_servido(puerto)
    return bool(esperado) and servido.lower() == esperado.lower()


def restaurar(cmdline: Union[str, Sequence[str]],
              timeout_s: float = 300.0,
              log: Union[str, Path, None] = None) -> Optional[subprocess.Popen]:
    """Relanza el server original TAL CUAL y espera su salud.

    `cmdline` es lo que devolvio linea_de_comando_actual() (str o argv ya
    partido). No se le agrega ni se le quita un flag: el cerebro del dueno
    vuelve con su --ctx-size 200192, su --cache-reuse y su --log-disable, que
    son celdas medidas de esta maquina, no las que este modulo prefiera.

    Devuelve el Popen del server relanzado, o None si el original YA estaba
    sirviendo (probado por identidad, no por un 200 pelado).
    Levanta RuntimeError -imprimiendo la linea para copiar y pegar- si no puede
    dejar el original sirviendo: dejar al dueno sin cerebro y en silencio no es
    una opcion, y devolver None 'porque algo contesta' seria justo eso."""
    argv = partir_cmdline(cmdline) if isinstance(cmdline, str) else [str(a) for a in cmdline]
    if not argv:
        raise ValueError("cmdline vacia: no hay nada que restaurar")
    linea = cmdline if isinstance(cmdline, str) else " ".join(argv)
    puerto = puerto_de_argv(argv)
    escribir_rescate(linea)

    # 1. Un server CARGANDO (503) ya ocupa el puerto: relanzar encima seria un
    #    segundo llama-server peleando por la misma VRAM y el mismo socket. Se
    #    le da tiempo a terminar de cargar antes de decidir nada.
    limite = time.time() + float(timeout_s)
    while estado(puerto) == "cargando" and time.time() < limite:
        time.sleep(2.0)

    # 2. Si ya esta el original, no se toca (idempotente: esto corre desde el
    #    finally Y desde el atexit).
    if estado(puerto) == "ok":
        if _ya_esta_el_original(puerto, argv, linea):
            print(f"[servidor_modelo] :{puerto} ya sirve el original; "
                  f"no relanzo nada.")
            return None
        ajeno = pid_llama_del_puerto(puerto)
        if ajeno is None:
            print(f"[servidor_modelo] :{puerto} lo ocupa un proceso que NO es "
                  f"un llama-server; no lo mato yo. Libera el puerto y corre:"
                  f"\n  {linea}", file=sys.stderr)
            raise RuntimeError(f"no pude restaurar el original en :{puerto}: "
                               f"el puerto lo ocupa otro proceso")
        # Un llama-server que no es el nuestro (candidato colgado): ese si se
        # para, y SOLO ese, por PID.
        print(f"[servidor_modelo] :{puerto} lo ocupa otro llama-server "
              f"(pid {ajeno}): lo paro y relanzo el original.")
        parar(ajeno, timeout_s=30.0)

    if not esperar_puerto_libre(puerto, 30.0):
        print(f"[servidor_modelo] :{puerto} sigue tomado. Corre a mano:\n  "
              + linea, file=sys.stderr)
        raise RuntimeError(f"el puerto :{puerto} no se libero")

    proc = _lanzar(argv, log if log is not None else DIR_LOGS / "restauracion.log")
    restante = max(30.0, limite - time.time())
    if not esperar_salud(puerto, restante, proc=proc):
        print("[servidor_modelo] NO PUDE RESTAURAR el server original. "
              f"El comando quedo en {RESCATE}. Relanzalo a mano con:\n  "
              + linea, file=sys.stderr)
        raise RuntimeError(f"el server original no volvio en :{puerto}")
    print(f"[servidor_modelo] server original restaurado en :{puerto} "
          f"(pid {proc.pid})")
    return proc


# ---------------------------------------------------------------------------
# 5b. El prestamo: la unica forma correcta de usar este modulo
# ---------------------------------------------------------------------------

_PRESTAMOS: list = []          # prestamos abiertos, para el atexit


def _restaurar_pendientes() -> None:
    """Cinturon del finally. Corre en atexit: si el arnes se va por un camino
    raro (sys.exit dentro de un hilo, excepcion en el propio finally), el
    cerebro vuelve igual. NO corre si al proceso lo matan con /F: para eso esta
    el fichero de rescate."""
    for prestamo in list(_PRESTAMOS):
        try:
            prestamo["restaurar"]()
        except Exception as exc:
            print(f"[servidor_modelo] atexit: la restauracion fallo: {exc}",
                  file=sys.stderr)


atexit.register(_restaurar_pendientes)


@contextlib.contextmanager
def prestar_puerto(puerto: int = PUERTO_CEREBRO,
                   timeout_parada: float = 60.0,
                   timeout_restauracion: float = 300.0,
                   log: Union[str, Path, None] = None):
    """Toma prestado el puerto del cerebro y lo DEVUELVE pase lo que pase.

    Al entrar: captura la cmdline del server vivo, la escribe en disco y para
    ESE proceso (por PID, nunca por nombre de imagen).
    Al salir -por return, por excepcion, por Ctrl-C o por SIGTERM- relanza esa
    cmdline exacta y verifica por identidad que el original volvio.

    Se NIEGA a empezar si el puerto esta ocupado por algo cuya linea de comando
    no pudo leer: no se mata lo que no se sabria relanzar. Esa regla es el
    modulo entero; el resto son detalles.

    Cede el dict de linea_de_comando_actual() (o None si el puerto estaba
    libre, en cuyo caso al salir no hay nada que restaurar)."""
    original = linea_de_comando_actual(puerto)
    if original is None:
        if estado(puerto) != "ausente" or not puerto_libre(puerto):
            raise RuntimeError(
                f":{puerto} esta ocupado por un proceso del que no pude leer la "
                f"linea de comando. No lo paro: no sabria como devolverlo.")
        print(f"[servidor_modelo] :{puerto} estaba libre: nada que devolver.")
        yield None
        return

    escribir_rescate(original["cmdline"])
    marca = {"restaurado": False, "intentos": 0}

    def _devolver():
        """Idempotente y con DOS intentos como mucho: el del finally y el del
        atexit. El segundo no es ceremonia - si el primero fallo porque el
        puerto no se habia liberado todavia, el de la salida suele acertar."""
        if marca["restaurado"] or marca["intentos"] >= 2:
            return
        marca["intentos"] += 1
        restaurar(original["cmdline"], timeout_restauracion, log)
        marca["restaurado"] = True

    prestamo = {"restaurar": _devolver}
    _PRESTAMOS.append(prestamo)

    def _por_senal(num, _marco):
        raise KeyboardInterrupt(f"senal {num}")

    # SIGTERM/SIGBREAK -> KeyboardInterrupt, para caer en el finally de abajo
    # (Ctrl-C ya llega asi por su cuenta, y el manejador de Python para SIGINT
    # hace exactamente esto: no se toca). signal() falla fuera del hilo
    # principal: ahi el finally y el atexit siguen siendo la defensa.
    previos = {}
    for nombre in ("SIGTERM", "SIGBREAK"):
        sig = getattr(signal, nombre, None)
        if sig is None:
            continue
        try:
            previos[sig] = signal.getsignal(sig)
            signal.signal(sig, _por_senal)
        except (ValueError, OSError):
            previos.pop(sig, None)

    try:
        print(f"[servidor_modelo] tomo prestado :{puerto} (pid "
              f"{original['pid']}); el comando de vuelta esta en {RESCATE}")
        if not parar(original["pid"], timeout_s=timeout_parada):
            raise RuntimeError(f"no pude parar el server original (pid "
                               f"{original['pid']}): no sigo.")
        esperar_puerto_libre(puerto, timeout_parada)
        yield original
    finally:
        # BaseException incluida (KeyboardInterrupt, SystemExit): el finally
        # corre igual, y esa es toda la garantia de esta pieza.
        for sig, previo in previos.items():
            try:
                signal.signal(sig, previo)
            except (ValueError, OSError):
                pass
        try:
            _devolver()
        finally:
            if prestamo in _PRESTAMOS:
                _PRESTAMOS.remove(prestamo)


# ---------------------------------------------------------------------------
# 6. Cuanto contexto pedir sin que reviente
# ---------------------------------------------------------------------------

_PARTIDO = re.compile(r"^(?P<base>.+)-(?P<n>\d{5})-of-(?P<total>\d{5})\.gguf$",
                      re.IGNORECASE)


def pesos_mib(gguf: Union[str, Path]) -> float:
    """Tamano REAL del modelo en MiB, sumando las partes de un GGUF partido.

    scripts/ctx_maximo.py mide solo el fichero que se le pasa: en
    qwen2.5-coder-14b (7630 MiB la parte 1 de 8572 MiB totales) eso subestima
    los pesos en 942 MiB, o sea regala contexto que la GPU no tiene."""
    ruta = Path(gguf)
    m = _PARTIDO.match(ruta.name)
    if not m:
        return ruta.stat().st_size / 1024 ** 2
    # Las hermanas se buscan con la MISMA regex, no con un glob armado a partir
    # del nombre: un modelo llamado 'mixtral[Q4]-00001-of-00002.gguf' convierte
    # ese glob en una clase de caracteres y el peso vuelve a ser el de una sola
    # parte - o sea, se regala VRAM que no existe, que es justo el bug que esta
    # funcion arregla.
    total = 0
    for parte in ruta.parent.iterdir():
        h = _PARTIDO.match(parte.name)
        if (h and h.group("base") == m.group("base")
                and h.group("total") == m.group("total")):
            try:
                total += parte.stat().st_size
            except OSError:
                pass
    return total / 1024 ** 2


def ctx_seguro(gguf_path: Union[str, Path],
               vram_libre_mib: Optional[float] = None) -> int:
    """Un --ctx-size que no deberia reventar, para ESTE modelo en ESTA GPU.

    Cuenta: (VRAM libre - pesos - reserva) / KV por token, por 0.8, recortado
    al ctx entrenado del modelo y al techo del arnes, redondeado a multiplo de
    256. Devuelve 0 si el modelo no entra ni con el contexto minimo.

    LIMITE MEDIDO - LA ESTIMACION FALLA EN ARQUITECTURAS HIBRIDAS. El KV por
    token sale de la formula de cabecera de scripts/ctx_maximo.py
    (n_layer x n_head_kv x head_dim x 2 x bytes_elem). Para el cerebro actual
    (Huihui-Qwythos-9B, arq 'qwen35': 33 capas, 4 kv-heads, head_dim 256) esa
    formula da 135.168 B/token = 132 KB/token, y lo MEDIDO contra el server
    real (scripts/medir_kv_real.py) fue 38 B/token: la formula se paso ~3.500x
    porque la arquitectura hibrida no gasta KV denso en todas las capas. Por
    eso ese modelo sirve hoy una ventana de 200.192 tokens que esta funcion
    jamas autorizaria.

    Consecuencia asumida: el valor devuelto es CONSERVADOR, no optimo. Sirve
    para que un candidato ARRANQUE sin OOM, no para exprimir la tarjeta. Las
    ventanas grandes de verdad solo salen de celdas MEDIDAS
    (cognia/summoner.py: ESCALERA_CTX), nunca de esta cuenta.
    El error va en la direccion segura (sobreestimar el KV -> pedir menos
    contexto); no esta medido ningun caso donde subestime."""
    ruta = Path(gguf_path)
    libre = float(VRAM_TOTAL_MIB if vram_libre_mib is None else vram_libre_mib)
    perfil = ctx_maximo.perfil(ruta)
    if not all((perfil.get("n_layer"), perfil.get("n_head_kv"),
                perfil.get("head_dim"))):
        raise ValueError(f"cabecera GGUF incompleta en {ruta.name}: "
                         f"{perfil} (sin n_layer/n_head_kv/head_dim no hay "
                         f"cuenta posible; no invento un ctx)")
    # f16 es el cache por defecto del server; si el arnes pasa --cache-type-k
    # q8_0 el KV real sera MENOR, o sea que este numero sigue siendo seguro.
    b_token = ctx_maximo.bytes_por_token(perfil, "f16")
    disponible_mib = libre - pesos_mib(ruta) - RESERVA_MIB
    if disponible_mib <= 0:
        return 0
    tokens = disponible_mib * 1024 ** 2 * FACTOR_SEGURIDAD / b_token
    tope = min(int(tokens), TECHO_CTX, int(perfil.get("ctx_train") or TECHO_CTX))
    tope -= tope % MULTIPLO_CTX
    return tope if tope >= CTX_MINIMO else 0


def vram_libre_mib() -> Optional[float]:
    """VRAM libre segun nvidia-smi (solo lectura). None si no hay nvidia-smi.

    Util cuando ya hay un server cargado: pasarle a ctx_seguro() el total de
    la tarjeta cuando la mitad esta ocupada es como se pide un ctx que no
    cabe."""
    try:
        salida = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=30).stdout
        return float(salida.strip().splitlines()[0])
    except Exception:
        return None


# ---------------------------------------------------------------------------
# CLI: SOLO LECTURA, a proposito
# ---------------------------------------------------------------------------

def main(argv: Optional[list] = None) -> int:
    """El CLI no arranca ni para nada. Es deliberado: arrancar/parar son API
    para el arnes, que sabe guardar la cmdline antes y restaurarla despues. Un
    `servidor_modelo.py parar` a mano es exactamente como se apaga el cerebro
    del dueno sin querer."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 1
    accion = argv[0]
    if accion == "mirar":
        puerto = int(argv[1]) if len(argv) > 1 else PUERTO_CEREBRO
        info = linea_de_comando_actual(puerto)
        print(f"  :{puerto} -> {estado(puerto)}")
        print(f"  sirve: {modelo_servido(puerto) or '(no lo pude leer)'}")
        if info is None:
            print("  no hay ningun llama-server sirviendo ese puerto")
            return 1
        print(f"  pid {info['pid']}")
        print(f"  {info['cmdline']}")
        return 0
    if accion == "ctx":
        if len(argv) < 2:
            print("Uso: servidor_modelo.py ctx <ruta.gguf> [vram_libre_mib]",
                  file=sys.stderr)
            return 1
        ruta = Path(argv[1])
        if not ruta.is_file():
            candidatos = [m for m in DIR_MODELOS.glob("*.gguf")
                          if argv[1].lower() in m.name.lower()]
            if not candidatos:
                print(f"no encuentro {argv[1]}", file=sys.stderr)
                return 1
            ruta = candidatos[0]
        libre = float(argv[2]) if len(argv) > 2 else (vram_libre_mib()
                                                     or VRAM_TOTAL_MIB)
        n = ctx_seguro(ruta, libre)
        print(f"  {ruta.name}")
        print(f"  pesos {pesos_mib(ruta):,.0f} MiB | VRAM libre {libre:,.0f} MiB")
        print(f"  ctx_seguro (conservador): {n:,}"
              + ("  <- NO CABE" if n == 0 else ""))
        return 0
    print(f"Accion desconocida: {accion!r}. Usa: mirar [puerto] | ctx <gguf>",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
