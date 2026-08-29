# -*- coding: utf-8 -*-
"""
cognia/harness/medidor_contexto.py
==================================
Cuanto contexto hay, donde vive y a que velocidad va. Modulo PURO.

LA REGLA DEL FICHERO: CADA NUMERO DICE DE DONDE SALE
----------------------------------------------------
El dueno pidio "no quiero valores ficticios; si un dato no puede medirse
directamente, indicalo como estimacion". Aqui eso no es un comentario: cada
campo del resultado viaja con su `origen`, que es uno de tres:

    "medido"    lo dijo el servidor, el driver o el sistema operativo
    "estimado"  se calculo de la geometria del modelo o de una regla
    "?"         no se pudo saber

Un numero sin origen no sale de este modulo. La razon es concreta: el tamano
del KV en VRAM NO lo publica llama-server por HTTP, y presentarlo como si lo
hiciera convertiria una cuenta en una medida a ojos de quien lo lee.

QUE SE PUEDE MEDIR Y QUE NO (limitaciones del backend, dichas)
--------------------------------------------------------------
SI se puede:
  - contexto servido y contexto EN USO ......... GET /slots (n_ctx,
                                                 n_prompt_tokens, cache)
  - tok/s de prefill y de generacion, TTFT ..... campo `timings` de cada
                                                 respuesta del servidor
  - uso del KV como fraccion ................... GET /metrics, pero SOLO si
                                                 el server arranco con
                                                 --metrics (si no, HTTP 501)
  - VRAM total y usada ......................... nvidia-smi
  - RAM del sistema y del proceso .............. API del sistema operativo
  - tipo de cuantizacion del KV, cache-ram,
    flash-attn, capas en GPU ................... linea de comandos del
                                                 proceso servidor
NO se puede:
  - cuantos MiB de KV hay en VRAM vs en RAM. llama.cpp no lo publica. Lo que
    SI se sabe es el reparto de POLITICA (si --no-kv-offload esta puesto, el
    KV entero esta en RAM; si no, esta en VRAM y lo que va a RAM es el cache
    de prompts de los slots inactivos, acotado por --cache-ram). Se informa
    la POLITICA, que es verdad, en vez de un reparto en MiB, que seria
    inventado.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass, field

__all__ = ["Medida", "Instantanea", "medir", "formato_humano", "formato_tecnico"]

_TIMEOUT = 4.0


@dataclass
class Medida:
    """Un numero con su procedencia. El `origen` no es decorativo: es lo que
    permite a la UI no mentir."""
    valor: object = None
    unidad: str = ""
    origen: str = "?"        # "medido" | "estimado" | "?"
    fuente: str = ""         # que endpoint / comando lo dijo
    nota: str = ""

    def __bool__(self) -> bool:
        return self.valor is not None

    def a_dict(self) -> dict:
        return {"valor": self.valor, "unidad": self.unidad,
                "origen": self.origen, "fuente": self.fuente, "nota": self.nota}


@dataclass
class Instantanea:
    url: str = ""
    campos: dict = field(default_factory=dict)
    avisos: list = field(default_factory=list)
    ms: int = 0

    def get(self, clave: str) -> Medida:
        return self.campos.get(clave) or Medida()

    def a_dict(self) -> dict:
        return {"url": self.url, "ms": self.ms, "avisos": list(self.avisos),
                "campos": {k: v.a_dict() for k, v in self.campos.items()}}


def _http(url: str, timeout: float = _TIMEOUT):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))


# ---------------------------------------------------------------------------
# Linea de comandos del servidor: de ahi salen los flags de KV, que ningun
# endpoint HTTP publica.
# ---------------------------------------------------------------------------

_CMDLINE_CACHE: dict = {}


def cmdline_servidor(puerto: int) -> str:
    """La linea de comandos del llama-server que escucha en `puerto`, o "".

    Se cachea por puerto: sacarla cuesta ~400 ms (una consulta WMI) y ningun
    servidor cambia sus flags sin reiniciarse, momento en el que cambia el
    PID y la cache deja de aplicar de todos modos.
    """
    if puerto in _CMDLINE_CACHE:
        return _CMDLINE_CACHE[puerto]
    linea = ""
    try:
        if sys.platform == "win32":
            pid = _pid_del_puerto(puerto)
            if pid:
                out = subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     f"(Get-CimInstance Win32_Process -Filter "
                     f"\"ProcessId={pid}\").CommandLine"],
                    capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=20)
                linea = (out.stdout or "").strip()
        else:
            pid = _pid_del_puerto(puerto)
            if pid:
                with open(f"/proc/{pid}/cmdline", "rb") as fh:
                    linea = fh.read().replace(b"\x00", b" ").decode(
                        "utf-8", errors="replace").strip()
    except Exception:
        linea = ""
    _CMDLINE_CACHE[puerto] = linea
    return linea


def _pid_del_puerto(puerto: int):
    try:
        # encoding + errors EXPLICITOS: con text=True a secas, Python decodifica
        # con la codificacion de la consola, que en un Windows en espanol es
        # cp850. netstat escribe acentos en su cabecera y el decode reventaba
        # ANTES de devolver una sola linea -- o sea, el medidor no encontraba
        # NUNCA el PID del servidor y por tanto no podia decir si el KV estaba
        # cuantizado. El sintoma llegaba como "no pude leer la linea de
        # comandos", que se lee como un problema de permisos.
        out = subprocess.run(["netstat", "-ano"], capture_output=True,
                             text=True, encoding="utf-8", errors="replace",
                             timeout=20)
        # Puede haber VARIOS procesos escuchando en el mismo numero de puerto
        # con direcciones distintas. En esta maquina, tailscaled escucha en
        # 100.x.x.x:8080 mientras el llama-server escucha en 127.0.0.1:8080; el
        # primer match de netstat era el de tailscale y el medidor terminaba
        # leyendo los flags del demonio de red. Es la MISMA trampa que ya se
        # llevo por delante al summoner (un segundo LISTENING ajeno en :8080).
        # Por eso se prefiere el bind local, que es el que Cognia usa siempre.
        candidatos = []
        for fila in (out.stdout or "").splitlines():
            if f":{puerto} " not in fila or "LISTENING" not in fila.upper():
                continue
            trozos = fila.split()
            if len(trozos) < 2 or not trozos[-1].isdigit():
                continue
            local = trozos[1]
            prioridad = (0 if local.startswith(("127.0.0.1:", "0.0.0.0:"))
                         else 1)
            candidatos.append((prioridad, int(trozos[-1])))
        candidatos.sort()
        return candidatos[0][1] if candidatos else None
    except Exception:
        pass
    return None


def _flag(cmdline: str, *nombres) -> str:
    """El valor de un flag de la linea de comandos, o "" si no esta."""
    for n in nombres:
        m = re.search(re.escape(n) + r"[= ]+([^\s]+)", cmdline)
        if m:
            return m.group(1)
    return ""


def _tiene_flag(cmdline: str, *nombres) -> bool:
    return any(re.search(r"(?<![\w-])" + re.escape(n) + r"(?![\w-])", cmdline)
               for n in nombres)


# ---------------------------------------------------------------------------
# VRAM y RAM
# ---------------------------------------------------------------------------

def _vram() -> tuple:
    """(usada_mib, total_mib) segun nvidia-smi, o (None, None)."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=15)
        if out.returncode != 0:
            return None, None
        usada, total = out.stdout.strip().splitlines()[0].split(",")
        return int(usada), int(total)
    except Exception:
        return None, None


def _ram() -> tuple:
    """(libre_mib, total_mib) del sistema, o (None, None)."""
    try:
        if sys.platform == "win32":
            import ctypes

            class _MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong),
                            ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            ms = _MS()
            ms.dwLength = ctypes.sizeof(_MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))
            return (int(ms.ullAvailPhys // 1048576),
                    int(ms.ullTotalPhys // 1048576))
        libre = total = None
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for linea in fh:
                if linea.startswith("MemAvailable:"):
                    libre = int(linea.split()[1]) // 1024
                elif linea.startswith("MemTotal:"):
                    total = int(linea.split()[1]) // 1024
        return libre, total
    except Exception:
        return None, None


# ---------------------------------------------------------------------------
# La instantanea
# ---------------------------------------------------------------------------

def _kv_bytes_por_token(props: dict):
    """(bytes/token, detalle) TEORICOS del KV en f16, o (None, motivo).

    Geometria pura: 2 (K y V) x capas x cabezas_kv x dim_cabeza x 2 bytes.
    Se marca ESTIMADO siempre. Un modelo hibrido (como el Qwen3.8-27B, con
    solo 16 de sus 64 bloques con atencion completa) hace que este numero
    SOBREESTIME mucho, y eso se dice en la nota en vez de callarlo.
    """
    md = props.get("model_meta") or {}
    capas = md.get("n_layer") or md.get("block_count")
    cabezas = md.get("n_head_kv")
    dim = md.get("n_embd_head_k")
    if not (capas and cabezas and dim):
        return None, "el servidor no publica la geometria del modelo"
    return (2 * int(capas) * int(cabezas) * int(dim) * 2,
            f"{capas} capas x {cabezas} cabezas KV x {dim}")


def medir(url: str = "", *, timings: dict = None) -> Instantanea:
    """Instantanea del estado del contexto. NUNCA lanza.

    `timings` es el bloque que devuelve llama-server en la ULTIMA respuesta
    (prompt_ms, predicted_ms, *_per_second). El servidor no lo guarda, asi
    que quien lo tenga (el CLI, tras un turno) lo pasa aqui.
    """
    inicio = time.monotonic()
    inst = Instantanea()

    if not url:
        try:
            from cognia.llm_local import detectar_backend
            b = detectar_backend() or {}
            url = str(b.get("url") or "")
        except Exception as exc:
            inst.avisos.append(f"no pude detectar el backend "
                               f"({type(exc).__name__}: {exc})")
    inst.url = (url or "").rstrip("/")

    def _poner(clave, valor, unidad="", origen="medido", fuente="", nota=""):
        inst.campos[clave] = Medida(valor=valor, unidad=unidad, origen=origen,
                                    fuente=fuente, nota=nota)

    # --- sistema: se puede medir aunque no haya servidor ------------------
    vram_usada, vram_total = _vram()
    if vram_usada is not None:
        _poner("vram_usada", vram_usada, "MiB", "medido", "nvidia-smi")
        _poner("vram_total", vram_total, "MiB", "medido", "nvidia-smi")
    else:
        inst.avisos.append("sin nvidia-smi: no hay datos de VRAM")
    ram_libre, ram_total = _ram()
    if ram_libre is not None:
        _poner("ram_libre", ram_libre, "MiB", "medido", "sistema operativo")
        _poner("ram_total", ram_total, "MiB", "medido", "sistema operativo")

    if not inst.url:
        inst.avisos.append("no hay backend vivo: solo datos del sistema")
        inst.ms = int((time.monotonic() - inicio) * 1000)
        return inst

    # --- /props -----------------------------------------------------------
    props = {}
    try:
        props = _http(inst.url + "/props")
    except Exception as exc:
        inst.avisos.append(f"/props no responde ({type(exc).__name__}: {exc})")
    if props:
        gen = props.get("default_generation_settings") or {}
        if gen.get("n_ctx"):
            _poner("ctx_max", int(gen["n_ctx"]), "tokens", "medido", "/props")
        modelo = props.get("model_path") or props.get("model") or ""
        if modelo:
            _poner("modelo", os.path.basename(str(modelo)), "", "medido", "/props")
        if props.get("total_slots"):
            _poner("slots", int(props["total_slots"]), "", "medido", "/props")
        bytes_tok, detalle = _kv_bytes_por_token(props)
        if bytes_tok:
            _poner("kv_bytes_por_token", bytes_tok, "bytes/token", "estimado",
                   "geometria de /props",
                   f"{detalle}. Es un TECHO: en modelos hibridos (solo "
                   f"algunas capas con atencion completa) el KV real es "
                   f"bastante menor.")

    # --- /slots: el contexto EN USO ---------------------------------------
    try:
        slots = _http(inst.url + "/slots")
        if isinstance(slots, list) and slots:
            s0 = slots[0]
            if s0.get("n_ctx"):
                _poner("ctx_por_slot", int(s0["n_ctx"]), "tokens", "medido",
                       "/slots")
            usados = int(s0.get("n_prompt_tokens") or 0)
            _poner("ctx_en_uso", usados, "tokens", "medido", "/slots")
            _poner("procesando", bool(s0.get("is_processing")), "", "medido",
                   "/slots")
            if s0.get("n_prompt_tokens_cache") is not None:
                _poner("tokens_de_cache", int(s0["n_prompt_tokens_cache"]),
                       "tokens", "medido", "/slots",
                       "prefijo que NO hubo que volver a procesar")
    except Exception as exc:
        inst.avisos.append(f"/slots no responde ({type(exc).__name__}: {exc})")

    # --- /metrics: solo si el server arranco con --metrics -----------------
    try:
        req = urllib.request.Request(inst.url + "/metrics")
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            crudo = r.read().decode("utf-8", errors="replace")
        if crudo.lstrip().startswith("{"):
            # El 501 viene como JSON de error, no como texto Prometheus.
            inst.avisos.append(
                "el servidor no expone /metrics: arrancalo con --metrics para "
                "ver el uso real del KV (Cognia ya lo pasa desde 2026-08-28; "
                "un servidor arrancado a mano antes de eso no lo tiene)")
        else:
            for linea in crudo.splitlines():
                if linea.startswith("llamacpp:kv_cache_usage_ratio"):
                    _poner("kv_uso", round(float(linea.split()[-1]), 4), "0-1",
                           "medido", "/metrics")
                elif linea.startswith("llamacpp:kv_cache_tokens"):
                    _poner("kv_tokens", int(float(linea.split()[-1])), "tokens",
                           "medido", "/metrics")
    except Exception as exc:
        inst.avisos.append(f"/metrics no disponible "
                           f"({type(exc).__name__}: {exc})")

    # --- flags del proceso: la POLITICA de donde vive el KV ----------------
    puerto = 0
    m = re.search(r":(\d+)$", inst.url)
    if m:
        puerto = int(m.group(1))
    cmdline = cmdline_servidor(puerto) if puerto else ""
    if cmdline:
        ctk = _flag(cmdline, "--cache-type-k", "-ctk") or "f16"
        ctv = _flag(cmdline, "--cache-type-v", "-ctv") or "f16"
        _poner("kv_tipo", f"K={ctk} V={ctv}", "", "medido",
               "linea de comandos del servidor",
               "f16 ocupa el doble que q8_0 a igual contexto")
        en_ram = _tiene_flag(cmdline, "--no-kv-offload", "-nkvo")
        _poner("kv_donde", "RAM del sistema" if en_ram else "VRAM (GPU)", "",
               "medido", "linea de comandos del servidor",
               "con --no-kv-offload el KV entero vive en RAM; sin el, vive en "
               "VRAM y lo que va a RAM es el cache de prompts de los slots "
               "inactivos")
        cram = _flag(cmdline, "--cache-ram", "-cram")
        if cram:
            _poner("cache_ram", int(cram) if cram.isdigit() else cram, "MiB",
                   "medido", "linea de comandos del servidor",
                   "tope del KV de conversaciones INACTIVAS guardado en RAM; "
                   "se restaura a VRAM si vuelve un prompt con el mismo "
                   "prefijo")
        _poner("flash_attn", _flag(cmdline, "--flash-attn", "-fa") or "auto",
               "", "medido", "linea de comandos del servidor")
        ngl = _flag(cmdline, "--n-gpu-layers", "-ngl", "--gpu-layers")
        if ngl:
            _poner("capas_gpu", ngl, "", "medido",
                   "linea de comandos del servidor")
    else:
        inst.avisos.append(
            "no pude leer la linea de comandos del servidor: no puedo decir "
            "si el KV esta cuantizado ni donde vive")

    # --- velocidad: solo si alguien paso los timings del ultimo turno ------
    if timings:
        if timings.get("prompt_per_second"):
            _poner("prefill_tok_s", round(float(timings["prompt_per_second"]), 1),
                   "tok/s", "medido", "timings del ultimo turno")
        if timings.get("predicted_per_second"):
            _poner("gen_tok_s", round(float(timings["predicted_per_second"]), 1),
                   "tok/s", "medido", "timings del ultimo turno")
        if timings.get("prompt_ms") is not None:
            _poner("prompt_ms", round(float(timings["prompt_ms"]), 1), "ms",
                   "medido", "timings del ultimo turno",
                   "lo que tardo en LEER el prompt")
            if timings.get("predicted_per_second"):
                _poner("ttft_ms",
                       round(float(timings["prompt_ms"])
                             + 1000.0 / float(timings["predicted_per_second"]), 1),
                       "ms", "estimado", "prompt_ms + 1/velocidad",
                       "sin streaming no hay forma de medir el primer token "
                       "por separado; esto es el prefill mas un token")
        if timings.get("predicted_ms") is not None:
            _poner("generacion_ms", round(float(timings["predicted_ms"]), 1),
                   "ms", "medido", "timings del ultimo turno")
        for clave, campo in (("prompt_n", "tokens_prompt"),
                             ("predicted_n", "tokens_generados")):
            if timings.get(clave) is not None:
                _poner(campo, int(timings[clave]), "tokens", "medido",
                       "timings del ultimo turno")

    inst.ms = int((time.monotonic() - inicio) * 1000)
    return inst


# ---------------------------------------------------------------------------
# Presentacion. Dos niveles, como pide la mision: lo simple por defecto y lo
# tecnico a peticion. Quien quiera saber cuanto contexto le queda no tiene por
# que enterarse de que existe algo llamado KV cache.
# ---------------------------------------------------------------------------

def _barra(fraccion: float, ancho: int = 24) -> str:
    lleno = max(0, min(ancho, int(round(fraccion * ancho))))
    return "#" * lleno + "." * (ancho - lleno)


def _miles(n) -> str:
    try:
        return f"{int(n):,}".replace(",", ".")
    except Exception:
        return str(n)


def formato_humano(inst: Instantanea) -> str:
    """Lo que ve cualquiera. Sin jerga."""
    lineas = []
    ctx_max = inst.get("ctx_por_slot").valor or inst.get("ctx_max").valor
    usado = inst.get("ctx_en_uso").valor
    if ctx_max:
        if usado is not None:
            frac = min(1.0, usado / float(ctx_max))
            lineas.append(f"  Contexto  [{_barra(frac)}] "
                          f"{_miles(usado)} / {_miles(ctx_max)} tokens "
                          f"({frac * 100:.0f}%)")
        else:
            lineas.append(f"  Contexto  hasta {_miles(ctx_max)} tokens")
    else:
        lineas.append("  Contexto  no hay backend vivo")

    vu, vt = inst.get("vram_usada").valor, inst.get("vram_total").valor
    if vu is not None and vt:
        lineas.append(f"  GPU       [{_barra(vu / float(vt))}] "
                      f"{_miles(vu)} / {_miles(vt)} MiB")
    rl, rt = inst.get("ram_libre").valor, inst.get("ram_total").valor
    if rl is not None and rt:
        lineas.append(f"  RAM       [{_barra(1 - rl / float(rt))}] "
                      f"{_miles(rt - rl)} / {_miles(rt)} MiB en uso")

    gen = inst.get("gen_tok_s").valor
    if gen:
        vel = f"  Velocidad {gen} palabras-token por segundo"
        pre = inst.get("prefill_tok_s").valor
        if pre:
            vel += f"  (leyendo: {pre})"
        lineas.append(vel)
    modelo = inst.get("modelo").valor
    if modelo:
        lineas.append(f"  Modelo    {modelo}")
    return "\n".join(lineas)


def formato_tecnico(inst: Instantanea) -> str:
    """Todo, con la procedencia de cada numero al lado."""
    orden = ("modelo", "ctx_max", "ctx_por_slot", "ctx_en_uso", "tokens_de_cache",
             "kv_uso", "kv_tokens", "kv_tipo", "kv_donde", "cache_ram",
             "kv_bytes_por_token", "flash_attn", "capas_gpu", "slots",
             "procesando", "vram_usada", "vram_total", "ram_libre", "ram_total",
             "prefill_tok_s", "gen_tok_s", "ttft_ms", "prompt_ms",
             "generacion_ms", "tokens_prompt", "tokens_generados")
    lineas = [f"Backend: {inst.url or '(ninguno)'}    "
              f"(instantanea en {inst.ms} ms)", ""]
    for clave in orden:
        m = inst.campos.get(clave)
        if not m:
            continue
        val = m.valor
        if isinstance(val, int) and abs(val) >= 10000:
            val = _miles(val)
        etiqueta = "" if m.origen == "medido" else f" [{m.origen}]"
        lineas.append(f"  {clave:<20} {str(val) + ' ' + m.unidad:<26}"
                      f"{m.fuente}{etiqueta}")
        if m.nota:
            for trozo in _envolver(m.nota, 66):
                lineas.append(f"  {'':<20} {trozo}")
    faltan = [c for c in orden if c not in inst.campos]
    if faltan:
        lineas += ["", f"  sin dato: {', '.join(faltan)}"]
    if inst.avisos:
        lineas.append("")
        for a in inst.avisos:
            lineas.append(f"  aviso: {a}")
    return "\n".join(lineas)


def _envolver(texto: str, ancho: int) -> list:
    palabras, fila, out = texto.split(), "", []
    for p in palabras:
        if len(fila) + len(p) + 1 > ancho:
            out.append(fila)
            fila = p
        else:
            fila = (fila + " " + p).strip()
    if fila:
        out.append(fila)
    return out
