"""
cognia/puertos.py
=================
Quien ESCUCHA un puerto de verdad, y si tenemos permiso para matarlo.

POR QUE EXISTE (2026-08-13): estas funciones nacieron en
scripts/servidor_modelo.py y scripts/ NO viaja en el wheel. El summoner
(cognia/summoner.py) las necesita para ADOPTAR el llama-server que ya sirve
el :8080 y para no confundir al vecino con el cerebro, asi que la fuente de
verdad se muda al paquete y el script pasa a RE-EXPORTARLAS. Una sola copia
a proposito: dos fuentes de verdad fue como el :8088 sirvio un modelo
retirado durante semanas (memoria del repo 2026-07-25).

La averia que justifica todo el cuidado, MEDIDA en esta maquina el
2026-08-13 (`netstat -ano | findstr :8080`):

    TCP    100.110.56.37:8080     0.0.0.0:0    LISTENING       7520    <- tailscaled
    TCP    127.0.0.1:8080         0.0.0.0:0    LISTENING       20872   <- llama-server

El listener de tailscale sale PRIMERO. Cualquier busqueda que se quede con
la primera linea que contenga ':8080' y 'LISTENING' concluye que el cerebro
no es el dueno de su propio puerto: asi el summoner borraba la entrada del
rol sin matar nada, la VRAM (12,8 GB) no se liberaba jamas e invocar()
esperaba 30 s en vano.

Solo stdlib: esto lo importan tanto el paquete como scripts/.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from typing import Optional


def procesos_llama() -> list[dict]:
    """[{'pid', 'cmdline'}] de los llama-server vivos, via CIM/WMI.

    Windows: PowerShell + Get-CimInstance Win32_Process. Se escribe con
    [Console]::Out.Write porque el formateador de PowerShell CORTA las lineas
    largas al ancho de consola y la cmdline (352 caracteres en el cerebro
    actual) volveria partida e inservible para restaurar.
    POSIX: `ps -eo pid=,args=` (el arnes se midio en Windows; el camino POSIX
    esta para que importar el modulo no reviente en CI)."""
    if os.name != "nt":
        try:
            salida = subprocess.run(["ps", "-eo", "pid=,args="],
                                    capture_output=True, text=True,
                                    errors="replace", timeout=20).stdout
        except Exception as exc:
            print(f"[puertos] no pude listar procesos: {exc}", file=sys.stderr)
            return []
        vivos = []
        for linea in salida.splitlines():
            linea = linea.strip()
            if not linea or "llama-server" not in linea:
                continue
            pid, _, cmd = linea.partition(" ")
            if pid.isdigit():
                vivos.append({"pid": int(pid), "cmdline": cmd.strip()})
        return vivos

    ps = ("$ps = Get-CimInstance Win32_Process | "
          "Where-Object { $_.Name -like 'llama-server*' } | "
          "Select-Object ProcessId,CommandLine; "
          "[Console]::Out.Write((ConvertTo-Json -InputObject @($ps) "
          "-Compress -Depth 3))")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive",
                            "-Command", ps],
                           capture_output=True, text=True, errors="replace",
                           timeout=60)
    except Exception as exc:
        print(f"[puertos] CIM fallo: {exc}", file=sys.stderr)
        return []
    crudo = (r.stdout or "").strip()
    if not crudo:
        return []
    try:
        datos = json.loads(crudo)
    except ValueError as exc:
        print(f"[puertos] CIM devolvio algo que no es JSON: {exc}",
              file=sys.stderr)
        return []
    if isinstance(datos, dict):
        datos = [datos]
    vivos = []
    for d in datos:
        pid = d.get("ProcessId")
        cmd = d.get("CommandLine") or ""
        if pid and cmd:
            vivos.append({"pid": int(pid), "cmdline": cmd})
    return vivos


def pid_del_puerto(puerto: int) -> Optional[int]:
    """PID que ESCUCHA en el `puerto` de LOOPBACK, o None si no se confirma.

    Cuentan 127.0.0.1:P y los comodines 0.0.0.0:P / [::]:P (los tres atienden a
    un cliente que se conecta a 127.0.0.1). NO cuenta una IP concreta que no sea
    loopback: en esta maquina tailscaled tiene un LISTENING propio en el :8080
    de la IP de la malla (100.110.56.37 y su IPv6, verificado con netstat el
    2026-08-13), y confundirlo con el cerebro es como el summoner perdio la
    entrada del rol.

    El estado se compara contra 'LISTENING' en INGLES a proposito: netstat de
    Windows traduce las cabeceras ('Direccion local', 'Estado') pero NO los
    estados - verificado en este Windows 11 en espanol."""
    try:
        if os.name == "nt":
            salida = subprocess.run(["netstat", "-ano"], capture_output=True,
                                    text=True, errors="replace",
                                    timeout=20).stdout
        else:                       # POSIX: `ss` si esta; si no, nada que afirmar
            salida = subprocess.run(["ss", "-lptn"], capture_output=True,
                                    text=True, errors="replace",
                                    timeout=20).stdout
    except Exception:
        return None
    comodines = (f"127.0.0.1:{puerto}", f"0.0.0.0:{puerto}", f"[::]:{puerto}",
                 f"::1:{puerto}", f"[::1]:{puerto}")
    for linea in salida.splitlines():
        if os.name == "nt":
            if "LISTENING" not in linea.upper():
                continue
            campos = linea.split()
            if len(campos) < 5 or campos[1] not in comodines:
                continue           # campos[1] es la direccion LOCAL, exacta
            if campos[-1].isdigit():
                return int(campos[-1])
        else:
            if not any(c in linea for c in comodines):
                continue
            m = re.search(r"pid=(\d+)", linea)
            if m:
                return int(m.group(1))
    return None


def pid_llama_del_puerto(puerto: int) -> Optional[int]:
    """El PID del puerto SOLO si es un llama-server. None en cualquier otro caso.

    Es el permiso para matarlo: `pid_del_puerto` sola devolveria feliz el PID de
    cualquier cosa que ocupe el :8080 (un dashboard, un tunel), y matar eso seria
    peor que la averia que se esta arreglando. Tambien es el permiso para
    ADOPTARLO como rol del summoner: registrar como 'cerebro' un pid que no es
    un llama-server termina en el mismo kill a ciegas, solo que mas tarde."""
    pid = pid_del_puerto(puerto)
    if pid is None:
        return None
    return pid if pid in {p["pid"] for p in procesos_llama()} else None
