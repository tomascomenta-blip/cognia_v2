"""
cognia/monitores/sondas.py
==========================
El CATALOGO de condiciones listas para monitorizar esta maquina y este repo.

QUE RESUELVE
    cognia/monitores/nucleo.py sabe agendar, persistir y disparar acciones,
    pero no sabe MIRAR nada. Este modulo aporta las condiciones concretas de
    alto valor (VRAM libre, backend caido, log con un patron, puerto robado,
    proceso zombi...) en dos mitades separadas a proposito:

      1. un CONSTRUCTOR por sonda -- `gpu_libre(4000)` -- que devuelve el dict
         serializable `{"tipo": ..., ...}` que el nucleo guarda en disco;
      2. un EVALUADOR puro por tipo -- `evaluar_gpu_libre(cond) -> dict` --
         que el nucleo invoca (directo o via `evaluar(cond)`).

    Esa separacion es la que permite testear el catalogo entero en seco: el
    evaluador no toca el nucleo, no arranca hilos y no imprime nada.

POR QUE EXISTE (las averias REALES que motivan cada sonda)
    - `puerto_ocupado_por_otro`: el 2026-08-13 tailscaled escuchaba en el
      :8080 de la IP de la malla y el summoner concluia que el llama-server no
      era dueno de su puerto -> borraba la entrada del rol sin matar nada y la
      VRAM (12,8 GB) no se liberaba jamas. Saber SI el puerto esta ocupado no
      sirve de nada: hay que saber QUIEN escucha.
    - `proceso_zombi`: matar el shell NO mata el proceso. Un banco "abortado"
      siguio 2 h vivo contaminando el unico slot de GPU. Un proceso vivo y sin
      CPU durante minutos es la firma de esa averia.
    - `log_patron`: un log de 100 MB no se puede releer cada 2 s. El tail es
      INCREMENTAL por offset y el offset se persiste en la propia condicion.
    - `gpu_libre` / `backend_vivo`: la degradacion silenciosa es el modo de
      fallo historico de Cognia; por eso ninguna sonda contesta "no" cuando lo
      que pasa es que NO PUDO MEDIR.

CONTRATO DEL RESULTADO (dict plano, siempre las mismas claves)
    {
      "disparo":  bool,   # la condicion se cumple AHORA
      "detalle":  str,    # una linea legible con la evidencia (numeros reales)
      "medible":  bool,   # False = el instrumento fallo; NUNCA implica disparo
      "tipo":     str,    # el tipo de la condicion evaluada
      "estado":   dict,   # estado que el nucleo debe PERSISTIR junto a la cond
    }
    Regla dura: `medible=False` siempre viene con `disparo=False`. "No hay
    nvidia-smi" no es "no hay VRAM libre", y "la suite no arranco" no es "los
    tests estan rojos". Confundirlos es exactamente la degradacion silenciosa.

ESTADO
    Las sondas con memoria (`fichero_cambio`, `log_patron`, `proceso_zombi`)
    guardan su estado DENTRO del dict de condicion, en la clave "estado", y lo
    mutan in situ ademas de devolverlo. Asi el nucleo persiste la condicion
    entera (JSON) sin conocer ni una sola sonda.

NINGUN EVALUADOR LANZA
    Camino caliente: instrumentacion que devuelve valores. Un fallo del
    instrumento sale como `medible=False`, jamas como excepcion.

Solo stdlib.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request

# --------------------------------------------------------------------------
# Utilidades comunes
# --------------------------------------------------------------------------

# nvidia-smi puede tardar cuando la GPU esta al 100%; 8 s es el techo con el
# que cognia/agent/_backend_gate.py convive sin falsos "no corre".
TIMEOUT_NVIDIA_S = 8.0

# Cuanto se lee de un log por pasada. El offset avanza solo lo leido, asi que
# un log que crece a borbotones se consume en varias pasadas en vez de meter
# 100 MB en RAM de una.
MAX_BYTES_LOG = 1 << 20

# Por encima de esto no se hashea el fichero entero: se hashea el primer y el
# ultimo MiB mas el tamano. Un GGUF de 12 GB no se puede sha256-ear cada 2 s.
TOPE_HASH_BYTES = 8 << 20


def _res(tipo: str, disparo: bool, detalle: str, medible: bool = True,
         estado: dict | None = None, **extra) -> dict:
    """Resultado normalizado. `medible=False` fuerza `disparo=False`."""
    if not medible:
        disparo = False
    salida = {"disparo": bool(disparo), "detalle": str(detalle),
              "medible": bool(medible), "tipo": tipo, "estado": estado or {}}
    salida.update(extra)
    return salida


def _no_medible(tipo: str, motivo: str, estado: dict | None = None) -> dict:
    return _res(tipo, False, f"no medible: {motivo}", medible=False, estado=estado)


def _correr(cmd, timeout_s: float, cwd: str | None = None) -> dict:
    """Corre un comando y devuelve {'rc','salida','error','fallo','timeout'}.

    'fallo' != '' significa que el INSTRUMENTO no pudo correr (el binario no
    existe, permisos): eso es 'no medible', no un resultado negativo.
    'timeout' es distinto: el comando SI corrio y se colgo, y para algunas
    sondas (tests_rojos) colgarse es justamente el hallazgo.
    """
    usar_shell = isinstance(cmd, str)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           errors="replace", timeout=timeout_s, cwd=cwd,
                           shell=usar_shell)
    except subprocess.TimeoutExpired as exc:
        parcial = exc.stdout or ""
        if isinstance(parcial, bytes):
            parcial = parcial.decode("utf-8", "replace")
        return {"rc": None, "salida": parcial, "error": "", "fallo": "",
                "timeout": True}
    except (FileNotFoundError, NotADirectoryError, PermissionError, OSError) as exc:
        return {"rc": None, "salida": "", "error": "", "fallo": str(exc),
                "timeout": False}
    return {"rc": r.returncode, "salida": r.stdout or "",
            "error": r.stderr or "", "fallo": "", "timeout": False}


def _recorte(texto, tope: int = 200) -> str:
    """Una linea legible: sin saltos y recortada. Los detalles viajan a un
    aviso de consola y a un JSONL; un volcado de 4 MB no ayuda a nadie."""
    plano = " ".join(str(texto).split())
    return plano if len(plano) <= tope else plano[:tope] + "..."


def _estado_de(cond: dict) -> dict:
    """El dict de estado de la condicion, creandolo si hace falta.

    Vive DENTRO de la cond para que el nucleo lo persista sin saber de sondas.
    """
    estado = cond.get("estado")
    if not isinstance(estado, dict):
        estado = {}
        cond["estado"] = estado
    return estado


# --------------------------------------------------------------------------
# 1. GPU libre  (nvidia-smi)
# --------------------------------------------------------------------------

CMD_NVIDIA_LIBRE = ["nvidia-smi", "--query-gpu=memory.free",
                    "--format=csv,noheader,nounits"]


def gpu_libre(mib_min: int, modo: str = "al_menos", cmd=None,
              timeout_s: float = TIMEOUT_NVIDIA_S) -> dict:
    """Condicion: hay al menos `mib_min` MiB libres en alguna GPU.

    modo 'al_menos' (default) es el caso de uso real: ESPERAR a que se libere
    la VRAM para lanzar el siguiente banco. modo 'por_debajo' es la alarma
    inversa (alguien se comio la GPU).
    `cmd` es configurable para poder ejercitar la rama 'no medible' con un
    binario que no existe, sin inventar un mock de subprocess.
    """
    return {"tipo": "gpu_libre", "mib_min": int(mib_min), "modo": str(modo),
            "cmd": list(cmd) if cmd else list(CMD_NVIDIA_LIBRE),
            "timeout_s": float(timeout_s)}


def evaluar_gpu_libre(cond: dict) -> dict:
    tipo = "gpu_libre"
    cmd = cond.get("cmd") or CMD_NVIDIA_LIBRE
    r = _correr(cmd, float(cond.get("timeout_s", TIMEOUT_NVIDIA_S)))
    if r["fallo"]:
        # Sin nvidia-smi no se afirma NADA sobre la VRAM. Esta es la rama que
        # separa "no hay GPU libre" de "no se puede ver la GPU".
        return _no_medible(tipo, f"nvidia-smi no corre ({_recorte(r['fallo'], 120)})")
    if r["timeout"]:
        return _no_medible(tipo, "nvidia-smi no respondio a tiempo")
    if r["rc"] != 0:
        return _no_medible(tipo, f"nvidia-smi rc={r['rc']} {_recorte(r['error'], 120)}")
    megas = [int(x) for x in re.findall(r"\d+", r["salida"] or "")]
    if not megas:
        return _no_medible(tipo, f"nvidia-smi sin cifras: {_recorte(r['salida'], 120)}")
    libre = max(megas)
    minimo = int(cond.get("mib_min", 0))
    if str(cond.get("modo", "al_menos")) == "por_debajo":
        disparo = libre < minimo
        detalle = f"{libre} MiB libres ({'<' if disparo else '>='} {minimo} pedidos)"
    else:
        disparo = libre >= minimo
        detalle = f"{libre} MiB libres ({'>=' if disparo else '<'} {minimo} pedidos)"
    if len(megas) > 1:
        detalle += f" [gpus: {', '.join(str(m) for m in megas)}]"
    return _res(tipo, disparo, detalle, mib_libres=libre)


# --------------------------------------------------------------------------
# 2. Backend vivo / caido  (llama-server u ollama)
# --------------------------------------------------------------------------

def _url_salud(url: str) -> str:
    """Anade /health si la URL viene pelada.

    llama-server y ollama exponen /health; si el que configura la sonda ya
    puso una ruta, se respeta tal cual.
    """
    texto = str(url or "").strip()
    if not texto:
        return ""
    resto = texto.split("//", 1)[-1]
    if "/" in resto:
        return texto
    return texto.rstrip("/") + "/health"


def backend_vivo(url: str, timeout_s: float = 3.0) -> dict:
    """Condicion: el backend responde saludable (2xx/3xx)."""
    return {"tipo": "backend_vivo", "url": _url_salud(url),
            "timeout_s": float(timeout_s)}


def backend_caido(url: str, timeout_s: float = 3.0,
                  solo_sin_respuesta: bool = False) -> dict:
    """Condicion: el backend NO esta sirviendo.

    `solo_sin_respuesta=True` dispara UNICAMENTE si no hay nadie escuchando.
    Por que la distincion importa: llama-server contesta 503 en /health
    mientras carga el modelo. Eso es "responde error" (esta vivo, aun no
    sirve), no "se cayo"; tratarlo igual haria disparar el monitor de caida en
    cada arranque normal.
    """
    return {"tipo": "backend_caido", "url": _url_salud(url),
            "timeout_s": float(timeout_s),
            "solo_sin_respuesta": bool(solo_sin_respuesta)}


def sondear_http(url: str, timeout_s: float = 3.0) -> dict:
    """{'situacion','codigo','detalle'} con situacion en
    'vivo' | 'error' | 'sin_respuesta' | 'no_medible'."""
    if not url:
        return {"situacion": "no_medible", "codigo": 0, "detalle": "url vacia"}
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as r:
            codigo = int(getattr(r, "status", 0) or 0)
            try:
                cuerpo = r.read(200).decode("utf-8", "replace")
            except Exception:
                cuerpo = ""
            if 200 <= codigo < 400:
                return {"situacion": "vivo", "codigo": codigo,
                        "detalle": _recorte(f"HTTP {codigo} {cuerpo}", 100)}
            return {"situacion": "error", "codigo": codigo,
                    "detalle": f"HTTP {codigo}"}
    except urllib.error.HTTPError as exc:
        # Contesto: hay un servidor ahi. 503 de llama-server = cargando.
        return {"situacion": "error", "codigo": int(exc.code),
                "detalle": _recorte(f"HTTP {exc.code} {getattr(exc, 'reason', '')}", 80)}
    except urllib.error.URLError as exc:
        return {"situacion": "sin_respuesta", "codigo": 0,
                "detalle": _recorte(getattr(exc, "reason", exc), 120)}
    except ValueError as exc:
        # URL mal formada / esquema desconocido: fallo de CONFIGURACION, no del
        # backend. No se puede afirmar nada del servidor.
        return {"situacion": "no_medible", "codigo": 0, "detalle": _recorte(exc, 120)}
    except Exception as exc:
        return {"situacion": "sin_respuesta", "codigo": 0, "detalle": _recorte(exc, 120)}


def evaluar_backend_vivo(cond: dict) -> dict:
    tipo = "backend_vivo"
    url = str(cond.get("url", ""))
    s = sondear_http(url, float(cond.get("timeout_s", 3.0)))
    if s["situacion"] == "no_medible":
        return _no_medible(tipo, s["detalle"])
    if s["situacion"] == "vivo":
        return _res(tipo, True, f"{url} responde OK ({s['detalle']})",
                    situacion="vivo", codigo=s["codigo"])
    if s["situacion"] == "error":
        return _res(tipo, False,
                    f"{url} responde ERROR ({s['detalle']}): vivo pero no sirve",
                    situacion="error", codigo=s["codigo"])
    return _res(tipo, False, f"{url} no responde ({s['detalle']})",
                situacion="sin_respuesta", codigo=0)


def evaluar_backend_caido(cond: dict) -> dict:
    tipo = "backend_caido"
    url = str(cond.get("url", ""))
    s = sondear_http(url, float(cond.get("timeout_s", 3.0)))
    if s["situacion"] == "no_medible":
        return _no_medible(tipo, s["detalle"])
    solo_sin = bool(cond.get("solo_sin_respuesta", False))
    if s["situacion"] == "sin_respuesta":
        return _res(tipo, True, f"{url} no responde ({s['detalle']})",
                    situacion="sin_respuesta", codigo=0)
    if s["situacion"] == "error":
        return _res(tipo, not solo_sin,
                    f"{url} responde ERROR ({s['detalle']})"
                    + ("; no cuenta como caida (solo_sin_respuesta)" if solo_sin else ""),
                    situacion="error", codigo=s["codigo"])
    return _res(tipo, False, f"{url} sigue vivo ({s['detalle']})",
                situacion="vivo", codigo=s["codigo"])


# --------------------------------------------------------------------------
# 3. Disco libre
# --------------------------------------------------------------------------

def disco_libre(ruta: str, gb_min: float, modo: str = "al_menos") -> dict:
    """Condicion sobre el espacio libre de la unidad que contiene `ruta`.

    modo 'al_menos' = espero a tener sitio (bajar un GGUF de 20 GB);
    modo 'por_debajo' = alarma de disco lleno.
    """
    return {"tipo": "disco_libre", "ruta": str(ruta), "gb_min": float(gb_min),
            "modo": str(modo)}


def evaluar_disco_libre(cond: dict) -> dict:
    tipo = "disco_libre"
    ruta = str(cond.get("ruta", "."))
    try:
        uso = shutil.disk_usage(ruta)
    except OSError as exc:
        # La ruta puede no existir todavia (un dir de salida aun sin crear):
        # eso no dice nada del disco.
        return _no_medible(tipo, f"{ruta}: {_recorte(exc, 120)}")
    libres_gb = uso.free / (1024.0 ** 3)
    minimo = float(cond.get("gb_min", 0.0))
    if str(cond.get("modo", "al_menos")) == "por_debajo":
        disparo = libres_gb < minimo
        cmp_txt = "<" if disparo else ">="
    else:
        disparo = libres_gb >= minimo
        cmp_txt = ">=" if disparo else "<"
    detalle = (f"{ruta}: {libres_gb:.1f} GB libres {cmp_txt} {minimo:g} pedidos "
               f"(total {uso.total / (1024.0 ** 3):.1f} GB)")
    return _res(tipo, disparo, detalle, gb_libres=round(libres_gb, 3))


# --------------------------------------------------------------------------
# 4. Fichero que cambia  (mtime + tamano + sha256 corto)
# --------------------------------------------------------------------------

def fichero_cambio(ruta: str, tope_hash_bytes: int = TOPE_HASH_BYTES) -> dict:
    """Condicion: el fichero cambio respecto de la ultima observacion.

    mtime solo no basta (dos escrituras dentro del mismo tick del reloj dan el
    MISMO mtime, y hay editores que lo preservan); el sha lo cierra. Y el sha
    solo tampoco basta: sobre ficheros grandes es caro, por eso primero se
    comparan mtime y tamano.
    """
    return {"tipo": "fichero_cambio", "ruta": str(ruta),
            "tope_hash_bytes": int(tope_hash_bytes), "estado": {}}


def _huella(ruta: str, tope: int) -> dict:
    """Huella del fichero. Lanza OSError si existe pero no se puede leer."""
    try:
        st = os.stat(ruta)
    except FileNotFoundError:
        return {"existe": False, "mtime": 0.0, "tam": -1, "sha": ""}
    tam = int(st.st_size)
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        if tam <= tope:
            for bloque in iter(lambda: f.read(1 << 16), b""):
                h.update(bloque)
        else:
            # Ficheros grandes (GGUF, logs): cabeza + cola + tamano. Un cambio
            # SOLO en el medio de un fichero de 12 GB se escapa, y se declara:
            # hashear 12 GB cada 2 s no es pagable.
            h.update(f.read(1 << 20))
            f.seek(-(1 << 20), os.SEEK_END)
            h.update(f.read(1 << 20))
            h.update(str(tam).encode("ascii"))
    return {"existe": True, "mtime": float(st.st_mtime), "tam": tam,
            "sha": h.hexdigest()[:16]}


def evaluar_fichero_cambio(cond: dict) -> dict:
    tipo = "fichero_cambio"
    estado = _estado_de(cond)
    ruta = str(cond.get("ruta", ""))
    try:
        actual = _huella(ruta, int(cond.get("tope_hash_bytes", TOPE_HASH_BYTES)))
    except OSError as exc:
        # Fichero bloqueado por otro proceso (tipico en Windows mientras se
        # escribe): no se pudo mirar, no se afirma que no cambio.
        return _no_medible(tipo, f"{ruta}: {_recorte(exc, 120)}", estado=estado)
    previo = estado.get("huella")
    estado["huella"] = actual
    if not isinstance(previo, dict):
        # Sin referencia no hay cambio que afirmar: la primera pasada solo toma
        # la linea base. Declararlo evita el falso positivo de arranque.
        marca = "existe" if actual["existe"] else "no existe"
        return _res(tipo, False,
                    f"linea base de {ruta} ({marca}, {actual['tam']} bytes)",
                    estado=estado, base=True)
    if previo == actual:
        return _res(tipo, False, f"{ruta} sin cambios (sha {actual['sha'] or '-'})",
                    estado=estado)
    if previo.get("existe") and not actual["existe"]:
        return _res(tipo, True, f"{ruta} DESAPARECIO", estado=estado)
    if not previo.get("existe") and actual["existe"]:
        return _res(tipo, True, f"{ruta} APARECIO ({actual['tam']} bytes)", estado=estado)
    cambios = []
    if previo.get("tam") != actual["tam"]:
        cambios.append(f"tam {previo.get('tam')}->{actual['tam']}")
    if previo.get("sha") != actual["sha"]:
        cambios.append(f"sha {previo.get('sha')}->{actual['sha']}")
    if previo.get("mtime") != actual["mtime"]:
        cambios.append("mtime")
    return _res(tipo, True, f"{ruta} cambio ({', '.join(cambios)})", estado=estado)


# --------------------------------------------------------------------------
# 5. Log con un patron  (tail INCREMENTAL por offset)
# --------------------------------------------------------------------------

def log_patron(ruta: str, regex: str, desde_inicio: bool = False,
               max_bytes: int = MAX_BYTES_LOG) -> dict:
    """Condicion: aparece una linea que casa `regex` en el log.

    El offset vive en el estado y SOLO avanza: un log de 100 MB no se puede
    releer cada 2 s (la sonda costaria mas que lo vigilado). Consecuencia
    querida: cada linea se examina UNA vez, asi que una coincidencia ya
    consumida no vuelve a disparar.

    `desde_inicio=False` (default) arranca en el final del fichero: al montar
    el monitor interesa lo que pase A PARTIR DE AHORA, no la historia. Con
    True se examina tambien lo que ya estaba escrito.
    """
    return {"tipo": "log_patron", "ruta": str(ruta), "regex": str(regex),
            "desde_inicio": bool(desde_inicio), "max_bytes": int(max_bytes),
            "estado": {}}


def evaluar_log_patron(cond: dict) -> dict:
    tipo = "log_patron"
    estado = _estado_de(cond)
    ruta = str(cond.get("ruta", ""))
    try:
        rx = re.compile(str(cond.get("regex", "")))
    except re.error as exc:
        return _no_medible(tipo, f"regex invalido: {_recorte(exc, 120)}", estado=estado)
    try:
        tam = os.path.getsize(ruta)
    except OSError as exc:
        # El log todavia no existe (el proceso aun no arranco): no es un fallo
        # del monitor, pero tampoco se puede afirmar nada del contenido.
        return _no_medible(tipo, f"{ruta}: {_recorte(exc, 120)}", estado=estado)

    nota = ""
    if "offset" not in estado:
        estado["offset"] = 0 if bool(cond.get("desde_inicio")) else int(tam)
    offset = int(estado["offset"])
    if tam < offset:
        # El fichero encogio: truncado o rotado. Seguir en el offset viejo
        # dejaria el monitor CIEGO para siempre sobre el log nuevo.
        nota = f" [rotacion detectada: {offset}->0]"
        offset = 0
    if tam == offset:
        estado["offset"] = offset
        return _res(tipo, False,
                    f"{ruta}: sin lineas nuevas (offset {offset}){nota}",
                    estado=estado, bytes_leidos=0, offset=offset)

    tope = max(1, int(cond.get("max_bytes", MAX_BYTES_LOG)))
    try:
        with open(ruta, "rb") as f:
            f.seek(offset)
            datos = f.read(tope)
    except OSError as exc:
        return _no_medible(tipo, f"{ruta}: {_recorte(exc, 120)}", estado=estado)
    if len(datos) == tope:
        # No se llego al final: cortar en el ultimo salto de linea para no
        # partir una linea y perder la coincidencia por culpa del corte.
        corte = datos.rfind(b"\n")
        if corte > 0:
            datos = datos[:corte + 1]
    estado["offset"] = offset + len(datos)

    texto = datos.decode("utf-8", "replace")
    for linea in texto.splitlines():
        if rx.search(linea):
            return _res(tipo, True, f"{ruta}: {_recorte(linea, 200)}",
                        estado=estado, bytes_leidos=len(datos),
                        offset=estado["offset"], linea=_recorte(linea, 400))
    return _res(tipo, False,
                f"{ruta}: {len(datos)} bytes nuevos sin coincidencia{nota}",
                estado=estado, bytes_leidos=len(datos), offset=estado["offset"])


# --------------------------------------------------------------------------
# 6. Git sucio
# --------------------------------------------------------------------------

def git_sucio(repo: str = ".", timeout_s: float = 30.0) -> dict:
    """Condicion: el arbol de trabajo tiene cambios sin commitear."""
    return {"tipo": "git_sucio", "repo": str(repo), "timeout_s": float(timeout_s)}


def evaluar_git_sucio(cond: dict) -> dict:
    tipo = "git_sucio"
    repo = str(cond.get("repo", "."))
    r = _correr(["git", "-C", repo, "status", "--porcelain"],
                float(cond.get("timeout_s", 30.0)))
    if r["fallo"]:
        return _no_medible(tipo, f"git no corre ({_recorte(r['fallo'], 120)})")
    if r["timeout"]:
        return _no_medible(tipo, "git status no respondio a tiempo")
    if r["rc"] != 0:
        # Tipico: la ruta no es un repo. Eso NO significa "limpio".
        return _no_medible(tipo, f"git rc={r['rc']} {_recorte(r['error'], 140)}")
    lineas = [l for l in (r["salida"] or "").splitlines() if l.strip()]
    if not lineas:
        return _res(tipo, False, f"{repo}: arbol limpio", cambios=0)
    muestra = "; ".join(l.strip() for l in lineas[:5])
    return _res(tipo, True,
                f"{repo}: {len(lineas)} cambios sin commitear ({_recorte(muestra, 160)})",
                cambios=len(lineas))


# --------------------------------------------------------------------------
# 7. Tests rojos
# --------------------------------------------------------------------------

def tests_rojos(repo: str, cmd, timeout_s: float = 600.0) -> dict:
    """Condicion: el comando de tests FALLA (rc != 0) o se cuelga.

    `cmd` puede ser lista (sin shell, lo recomendado) o cadena (con shell).
    El timeout dispara a proposito: una suite colgada es un fallo, no un
    "no medible" -- el repo ya tiene el caso del juez que se colgaba con JS
    bloqueante y contaba como reprobado legitimo.
    """
    return {"tipo": "tests_rojos", "repo": str(repo),
            "cmd": list(cmd) if isinstance(cmd, (list, tuple)) else str(cmd),
            "timeout_s": float(timeout_s)}


def evaluar_tests_rojos(cond: dict) -> dict:
    tipo = "tests_rojos"
    repo = str(cond.get("repo") or ".")
    cmd = cond.get("cmd")
    if not cmd:
        return _no_medible(tipo, "sin comando de tests")
    if not os.path.isdir(repo):
        return _no_medible(tipo, f"el repo {repo} no existe")
    r = _correr(cmd, float(cond.get("timeout_s", 600.0)), cwd=repo)
    if r["fallo"]:
        # El binario de tests no existe: fallo del INSTRUMENTO. Contarlo como
        # "tests rojos" seria acusar al codigo de una averia del arnes.
        return _no_medible(tipo,
                           f"no pude correr los tests ({_recorte(r['fallo'], 140)})")
    if r["timeout"]:
        return _res(tipo, True,
                    f"la suite se colgo (timeout {cond.get('timeout_s')}s): "
                    f"{_recorte(r['salida'][-400:], 160)}", rc=None, timeout=True)
    cola = (r["salida"] or "")[-400:] + (r["error"] or "")[-200:]
    if r["rc"] != 0:
        return _res(tipo, True, f"tests ROJOS (rc={r['rc']}): {_recorte(cola, 200)}",
                    rc=r["rc"], timeout=False)
    return _res(tipo, False, f"tests verdes (rc=0): {_recorte(cola, 120)}",
                rc=0, timeout=False)


# --------------------------------------------------------------------------
# 8. Proceso zombi  (vivo pero sin CPU)
# --------------------------------------------------------------------------

def proceso_zombi(nombre: str, min_cpu: float = 1.0, minutos: float = 10.0) -> dict:
    """Condicion: hay un proceso que casa `nombre` vivo pero SIN actividad.

    Por que existe: matar el shell NO mata el proceso. Un banco "abortado"
    siguio 2 h ocupando el unico slot de GPU. "Vivo" no es senal de nada;
    "vivo y por debajo de min_cpu % durante `minutos`" si lo es.

    min_cpu se mide como porcentaje de UN nucleo ENTRE DOS OBSERVACIONES
    (delta de tiempo de CPU / delta de reloj), no sobre el acumulado: un
    proceso que trabajo 3 h y ahora esta clavado tiene un acumulado enorme.
    """
    return {"tipo": "proceso_zombi", "nombre": str(nombre),
            "min_cpu": float(min_cpu), "minutos": float(minutos), "estado": {}}


def _cpu_segundos_posix(campo: str) -> float:
    """'[dd-]hh:mm:ss[.cc]' de ps -> segundos."""
    texto = str(campo).strip()
    dias = 0.0
    if "-" in texto:
        cabeza, _, texto = texto.partition("-")
        dias = float(cabeza or 0)
    seg = 0.0
    for p in texto.split(":"):
        seg = seg * 60 + float(p or 0)
    return dias * 86400.0 + seg


def listar_procesos(filtro: str = "") -> list:
    """[{'pid','nombre','cmdline','cpu_s'}] de los procesos que casan `filtro`.

    Windows: CIM/Win32_Process, con KernelModeTime+UserModeTime en unidades de
    100 ns (de ahi el /1e7). Se escribe con [Console]::Out.Write porque el
    formateador de PowerShell CORTA las lineas largas al ancho de consola y la
    cmdline vuelve partida (misma trampa documentada en cognia/puertos.py).
    POSIX: `ps -eo pid=,time=,comm=,args=`.
    El filtro se aplica sobre nombre Y cmdline: el zombi tipico de esta maquina
    es 'python.exe scripts/banco_xxx.py', donde el nombre no distingue nada.
    Lanza OSError si no se pudo listar (el evaluador lo traduce a no medible).
    """
    filtro_bajo = str(filtro or "").lower()
    salida = []
    if os.name == "nt":
        ps = ("$ps = Get-CimInstance Win32_Process | Select-Object "
              "ProcessId,Name,CommandLine,KernelModeTime,UserModeTime; "
              "[Console]::Out.Write((ConvertTo-Json -InputObject @($ps) "
              "-Compress -Depth 3))")
        r = _correr(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], 60.0)
        if r["fallo"] or r["timeout"] or r["rc"] != 0:
            raise OSError("no pude listar procesos ("
                          + (r["fallo"] or r["error"] or f"rc={r['rc']}") + ")")
        crudo = (r["salida"] or "").strip()
        if not crudo:
            return []
        try:
            datos = json.loads(crudo)
        except ValueError as exc:
            raise OSError(f"CIM no devolvio JSON: {exc}")
        if isinstance(datos, dict):
            datos = [datos]
        for d in datos:
            nombre = str(d.get("Name") or "")
            cmdline = str(d.get("CommandLine") or "")
            if filtro_bajo and filtro_bajo not in nombre.lower() \
                    and filtro_bajo not in cmdline.lower():
                continue
            cien_ns = float(d.get("KernelModeTime") or 0) + float(d.get("UserModeTime") or 0)
            salida.append({"pid": int(d.get("ProcessId") or 0), "nombre": nombre,
                           "cmdline": cmdline, "cpu_s": cien_ns / 1e7})
        return salida
    r = _correr(["ps", "-eo", "pid=,time=,comm=,args="], 30.0)
    if r["fallo"] or r["timeout"] or r["rc"] != 0:
        raise OSError("no pude listar procesos ("
                      + (r["fallo"] or r["error"] or f"rc={r['rc']}") + ")")
    for linea in (r["salida"] or "").splitlines():
        campos = linea.split(None, 3)
        if len(campos) < 3 or not campos[0].isdigit():
            continue
        pid, tiempo, nombre = campos[0], campos[1], campos[2]
        cmdline = campos[3] if len(campos) > 3 else nombre
        if filtro_bajo and filtro_bajo not in nombre.lower() \
                and filtro_bajo not in cmdline.lower():
            continue
        try:
            cpu = _cpu_segundos_posix(tiempo)
        except ValueError:
            continue
        salida.append({"pid": int(pid), "nombre": nombre, "cmdline": cmdline,
                       "cpu_s": cpu})
    return salida


def evaluar_proceso_zombi(cond: dict, listar=None, ahora=None) -> dict:
    """`listar` y `ahora` se INYECTAN para poder probar el modulo en seco: un
    zombi de 10 minutos no se puede esperar dentro de un test."""
    tipo = "proceso_zombi"
    estado = _estado_de(cond)
    listar = listar or listar_procesos
    momento = time.time() if ahora is None else float(ahora)
    try:
        procs = list(listar(str(cond.get("nombre", ""))))
    except Exception as exc:
        return _no_medible(tipo, f"no pude listar procesos ({_recorte(exc, 140)})",
                           estado=estado)

    vistos = estado.get("procs")
    if not isinstance(vistos, dict):
        vistos = {}
        estado["procs"] = vistos

    min_cpu = float(cond.get("min_cpu", 1.0))
    umbral_s = float(cond.get("minutos", 10.0)) * 60.0
    zombis = []
    vivos_ahora = set()

    for p in procs:
        pid = str(p.get("pid"))
        vivos_ahora.add(pid)
        cpu_s = float(p.get("cpu_s") or 0.0)
        previo = vistos.get(pid)
        if not isinstance(previo, dict):
            # Primera observacion de este pid: solo linea base. Sin DOS
            # muestras no hay ritmo de CPU que medir.
            vistos[pid] = {"cpu_s": cpu_s, "ts": momento, "quieto_desde": None,
                           "nombre": str(p.get("nombre") or "")}
            continue
        dt = momento - float(previo.get("ts", momento))
        if dt <= 0:
            continue                       # dos lecturas en el mismo instante
        dcpu = max(0.0, cpu_s - float(previo.get("cpu_s", 0.0)))
        pct = 100.0 * dcpu / dt
        quieto_desde = previo.get("quieto_desde")
        if pct >= min_cpu:
            quieto_desde = None            # trabajo: el reloj de quietud se reinicia
        elif quieto_desde is None:
            quieto_desde = momento
        vistos[pid] = {"cpu_s": cpu_s, "ts": momento, "quieto_desde": quieto_desde,
                       "nombre": str(p.get("nombre") or previo.get("nombre") or "")}
        if quieto_desde is not None and (momento - float(quieto_desde)) >= umbral_s:
            zombis.append({"pid": int(p.get("pid") or 0),
                           "nombre": str(p.get("nombre") or ""),
                           "cpu_pct": round(pct, 2),
                           "quieto_min": round((momento - float(quieto_desde)) / 60.0, 1),
                           "cmdline": _recorte(p.get("cmdline", ""), 120)})

    for pid in [k for k in vistos if k not in vivos_ahora]:
        del vistos[pid]                    # murio: el estado no crece sin techo

    if zombis:
        muestra = "; ".join(f"pid {z['pid']} {z['nombre']} {z['cpu_pct']}% CPU "
                            f"quieto {z['quieto_min']} min" for z in zombis[:3])
        return _res(tipo, True, f"{len(zombis)} proceso(s) zombi: {muestra}",
                    estado=estado, zombis=zombis)
    if not procs:
        return _res(tipo, False, f"ningun proceso casa '{cond.get('nombre')}'",
                    estado=estado, zombis=[])
    return _res(tipo, False,
                f"{len(procs)} proceso(s) con actividad o sin muestras suficientes",
                estado=estado, zombis=[])


# --------------------------------------------------------------------------
# 9. Puerto ocupado por OTRO
# --------------------------------------------------------------------------

def puerto_ocupado_por_otro(puerto: int, exe_esperado: str) -> dict:
    """Condicion: alguien escucha el puerto y NO es quien deberia.

    La averia real (2026-08-13): tailscaled con un LISTENING propio en el
    :8080 de la IP de la malla mientras llama-server tenia el de loopback. Un
    chequeo de "puerto ocupado" da lo mismo en los dos casos; lo que hay que
    responder es QUIEN escucha.
    """
    return {"tipo": "puerto_ocupado_por_otro", "puerto": int(puerto),
            "exe_esperado": str(exe_esperado)}


def pid_escuchando(puerto: int):
    """PID que escucha el puerto de LOOPBACK, o None.

    Se delega en cognia/puertos.py a proposito: alli vive la unica copia de la
    regla que separa el listener de loopback del de la IP de la malla, y dos
    fuentes de verdad fue como el :8088 sirvio un modelo retirado durante
    semanas. Si el import falla, el evaluador lo traduce a 'no medible'.
    """
    from cognia.puertos import pid_del_puerto
    return pid_del_puerto(int(puerto))


def nombre_de_pid(pid: int) -> str:
    """Nombre del ejecutable de un PID ('' si no se pudo resolver)."""
    if os.name == "nt":
        r = _correr(["tasklist", "/FI", f"PID eq {int(pid)}", "/FO", "CSV", "/NH"], 20.0)
        if r["fallo"] or r["timeout"] or r["rc"] != 0:
            return ""
        lineas = [l for l in (r["salida"] or "").splitlines() if l.strip()]
        if not lineas:
            return ""
        primera = lineas[0].strip()
        if not primera.startswith('"'):
            return ""                      # 'INFO: no tasks are running...'
        return primera.split('","')[0].strip('"')
    r = _correr(["ps", "-p", str(int(pid)), "-o", "comm="], 20.0)
    if r["fallo"] or r["timeout"] or r["rc"] != 0:
        return ""
    lineas = [l for l in (r["salida"] or "").splitlines() if l.strip()]
    return lineas[0].strip() if lineas else ""


def _casa_exe(nombre: str, esperado: str) -> bool:
    """Compara sin distinguir mayusculas ni la extension .exe."""
    a = str(nombre or "").strip().lower()
    b = str(esperado or "").strip().lower()
    if not b:
        return True
    for sufijo in (".exe", ".com"):
        if a.endswith(sufijo):
            a = a[: -len(sufijo)]
        if b.endswith(sufijo):
            b = b[: -len(sufijo)]
    return bool(a) and (b in a or a in b)


def evaluar_puerto_ocupado_por_otro(cond: dict, pid_de_puerto=None,
                                    nombre_pid=None) -> dict:
    """`pid_de_puerto` y `nombre_pid` se inyectan para pruebas dirigidas; por
    defecto se mide de verdad contra el sistema."""
    tipo = "puerto_ocupado_por_otro"
    puerto = int(cond.get("puerto", 0))
    esperado = str(cond.get("exe_esperado", ""))
    buscar = pid_de_puerto or pid_escuchando
    resolver = nombre_pid or nombre_de_pid
    try:
        pid = buscar(puerto)
    except Exception as exc:
        return _no_medible(tipo,
                           f"no pude mirar el puerto {puerto} ({_recorte(exc, 120)})")
    if pid is None:
        return _res(tipo, False, f"puerto {puerto} libre (nadie escucha)", pid=0, exe="")
    try:
        nombre = resolver(int(pid))
    except Exception:
        nombre = ""
    if not nombre:
        # Hay un listener pero no se puede decir QUIEN: afirmar "es un intruso"
        # aqui es exactamente el error que termina matando al proceso que no era.
        return _no_medible(
            tipo, f"pid {pid} escucha el {puerto} pero no pude resolver su ejecutable")
    if _casa_exe(nombre, esperado):
        return _res(tipo, False,
                    f"puerto {puerto}: lo tiene {nombre} (pid {pid}), el esperado",
                    pid=int(pid), exe=nombre)
    return _res(tipo, True,
                f"puerto {puerto} ROBADO: escucha {nombre} (pid {pid}), "
                f"se esperaba '{esperado}'", pid=int(pid), exe=nombre)


# --------------------------------------------------------------------------
# Registro: lo que consume cognia/monitores/nucleo.py
# --------------------------------------------------------------------------

EVALUADORES = {
    "gpu_libre": evaluar_gpu_libre,
    "backend_vivo": evaluar_backend_vivo,
    "backend_caido": evaluar_backend_caido,
    "disco_libre": evaluar_disco_libre,
    "fichero_cambio": evaluar_fichero_cambio,
    "log_patron": evaluar_log_patron,
    "git_sucio": evaluar_git_sucio,
    "tests_rojos": evaluar_tests_rojos,
    "proceso_zombi": evaluar_proceso_zombi,
    "puerto_ocupado_por_otro": evaluar_puerto_ocupado_por_otro,
}

# nombre -> constructor, para que el agente/CLI pueda listar y armar sondas sin
# importar cada funcion a mano.
CONSTRUCTORES = {
    "gpu_libre": gpu_libre,
    "backend_vivo": backend_vivo,
    "backend_caido": backend_caido,
    "disco_libre": disco_libre,
    "fichero_cambio": fichero_cambio,
    "log_patron": log_patron,
    "git_sucio": git_sucio,
    "tests_rojos": tests_rojos,
    "proceso_zombi": proceso_zombi,
    "puerto_ocupado_por_otro": puerto_ocupado_por_otro,
}


def evaluar(cond: dict) -> dict:
    """Despacha una condicion a su evaluador. NUNCA lanza.

    Un tipo desconocido o un evaluador que revienta salen como 'no medible': el
    motor de monitores no puede caerse porque una sonda este mal escrita.
    """
    if not isinstance(cond, dict):
        return _no_medible("?", "la condicion no es un dict")
    tipo = str(cond.get("tipo", ""))
    fn = EVALUADORES.get(tipo)
    if fn is None:
        return _no_medible(tipo or "?", f"tipo de condicion desconocido: {tipo!r}")
    try:
        salida = fn(cond)
    except Exception as exc:
        estado = cond.get("estado")
        return _no_medible(tipo,
                           f"la sonda fallo: {type(exc).__name__}: {_recorte(exc, 140)}",
                           estado=estado if isinstance(estado, dict) else None)
    if not isinstance(salida, dict) or "disparo" not in salida:
        return _no_medible(tipo, "la sonda devolvio algo que no es un resultado")
    return salida


def describir(cond: dict) -> str:
    """Una linea legible de la condicion, para /monitores y para los logs."""
    if not isinstance(cond, dict):
        return "condicion invalida"
    tipo = str(cond.get("tipo", "?"))
    partes = [f"{k}={v}" for k, v in sorted(cond.items())
              if k not in ("tipo", "estado", "cmd") and not k.startswith("_")]
    return f"{tipo}({', '.join(partes)})"
