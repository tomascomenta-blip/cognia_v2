# -*- coding: utf-8 -*-
"""
scripts/banco_kv.py
===================
Banco MEDIDO del compromiso contexto <-> velocidad en esta maquina.

QUE MIDE Y POR QUE
------------------
El dueno pide "usar RAM como extension del espacio de contexto sin sacrificar
la GPU". Antes de disenar politica hay que saber que permite el backend DE
VERDAD. Este banco corre el mismo prompt contra el MISMO modelo con cuatro
configuraciones de KV cache y un barrido de ventanas, y anota lo que el
servidor reporta, no lo que suponemos:

    A  KV f16, todo en VRAM              (linea base)
    B  KV f16 + --no-kv-offload           (KV entero en RAM del sistema)
    C  KV q8_0, todo en VRAM              (KV cuantizado)
    D  KV q8_0 + --no-kv-offload          (cuantizado + RAM)

B y D existen para MEDIR lo que el dueno explicitamente no quiere hacer a
ciegas: mandar el KV entero a RAM. Si el coste medido es alto, queda probado
por que la politica correcta no es esa (ver el informe).

DE DONDE SALE CADA NUMERO (nada es estimado salvo lo que se marca como tal)
--------------------------------------------------------------------------
  tok/s prefill, tok/s generacion, TTFT ... campo `timings` de la respuesta
                                           de llama-server (prompt_ms,
                                           predicted_ms, *_per_second)
  n_ctx servido ........................... GET /props -> default_generation
                                            _settings.n_ctx
  VRAM .................................... nvidia-smi --query-gpu=memory.used
                                            (delta contra la linea base sin
                                            servidor)
  RAM del proceso ......................... working set del PID del servidor
  tokens del prompt ....................... POST /tokenize (exacto, no regla
                                            de tres sobre caracteres)
  calidad ................................. aguja plantada en el prompt: la
                                            respuesta la contiene o no

Lo unico ESTIMADO es el tamano teorico del KV, que se calcula de la geometria
del modelo y se marca como tal en la salida.

DISENO ANTI-PERDIDA
-------------------
Bitacora append-only con flush por linea (patron de la casa): una corrida que
muere a las tres horas deja legible todo lo anterior. Cada celda es
independiente: el servidor se arranca y se mata por celda, asi que un OOM en
la celda 12 no envenena la 13. Y se apunta el fallo como DATO (oom, timeout,
arranque_fallido), porque "no arranca a 256k" es justo lo que el dueno pidio
saber.

USO
---
    venv312\\Scripts\\python.exe scripts\\banco_kv.py --ctxs 8192,16384,32768 \\
        --configs A,C --salida scratchpad/banco_kv.jsonl

    # barrido completo de estres (lento: ~2 min por celda)
    venv312\\Scripts\\python.exe scripts\\banco_kv.py --estres
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

DIR_LLAMA = Path.home() / ".cognia" / "llama"
DIR_MODELOS = Path.home() / ".cognia" / "models"

# Puerto propio: 8080 es el cerebro del dueno y 8088 el fleet. Un banco que
# mata el servidor bueno para medir es un banco que cuesta mas de lo que vale.
PUERTO_BANCO = 8099

# Cuatro configuraciones. `ctk`/`ctv` vacios = f16 (el default del binario).
CONFIGS = {
    "A": {"nombre": "KV f16 / VRAM", "ctk": "", "ctv": "", "nkvo": False},
    "B": {"nombre": "KV f16 / RAM", "ctk": "", "ctv": "", "nkvo": True},
    "C": {"nombre": "KV q8_0 / VRAM", "ctk": "q8_0", "ctv": "q8_0", "nkvo": False},
    "D": {"nombre": "KV q8_0 / RAM", "ctk": "q8_0", "ctv": "q8_0", "nkvo": True},
}

CTXS_DEFECTO = [8192, 16384, 32768, 65536]
CTXS_ESTRES = [8192, 16384, 32768, 65536, 131072, 262144]

# Por encima de esto, la GPU no esta limpia y la celda no es comparable con
# las demas. 1.500 MiB es el escritorio de Windows con lo minimo (medido en
# esta maquina: 435 MiB sin nada, 2.247 con la terminal y el explorador,
# 4.220 con navegador y pruebas encima).
UMBRAL_VRAM_LIMPIA_MIB = 1500

TIMEOUT_ARRANQUE = 300.0     # un 27B con ctx grande tarda en reservar el KV
TIMEOUT_PETICION = 600.0     # prefill de 150k tokens en RAM es lentisimo.
                             # 600 y no 900: una celda que no cabe tarda el
                             # timeout ENTERO, y con 900 cada fallo costaba 15
                             # minutos de banco para decir lo mismo que dice en 10.
N_GENERAR = 200              # 200 y no 16: con pocos tokens el spill a RAM no
                             # se ve (leccion del barrido de perfiles_arranque)


# ---------------------------------------------------------------- utilidades

def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def vram_usada_mib() -> int | None:
    """MiB ocupados en la GPU segun nvidia-smi, o None si no hay nvidia-smi."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=15)
        if out.returncode != 0:
            return None
        return int(out.stdout.strip().splitlines()[0].strip())
    except Exception:
        return None


def ram_libre_mib() -> int | None:
    """MiB de RAM fisica libre. Windows: GlobalMemoryStatusEx via ctypes."""
    try:
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
        return int(ms.ullAvailPhys // (1024 * 1024))
    except Exception:
        return None


def ram_proceso_mib(pid: int) -> int | None:
    """Working set del proceso en MiB (lo que el KV en RAM hace crecer)."""
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=15)
        campos = out.stdout.strip().strip('"').split('","')
        if len(campos) < 5:
            return None
        # "12.345 KB" con separador de miles local (. o ,)
        kb = re.sub(r"[^\d]", "", campos[4])
        return int(kb) // 1024 if kb else None
    except Exception:
        return None


def _get_json(url: str, timeout: float = 20.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _post_json(url: str, cuerpo: dict, timeout: float):
    datos = json.dumps(cuerpo).encode("utf-8")
    req = urllib.request.Request(
        url, data=datos, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def binario() -> Path | None:
    for nombre in ("llama-server.exe", "llama-server"):
        ruta = DIR_LLAMA / nombre
        if ruta.exists():
            return ruta
    return None


def elegir_modelo(patron: str | None) -> Path | None:
    """El gguf que case el patron, EXCLUYENDO los que no son modelos.

    El filtro de mmproj no es cosmetico: `--modelo qwen3.8-27b` casaba
    'mmproj-Qwen3.8-27B-BF16.gguf' antes que 'Qwen3.8-27B-Ridge-3.7bpw.gguf'
    (en Windows el orden de Path es insensible a mayusculas, asi que
    'mmproj' < 'Qwen'), y llama-server moria con 'CLIP cannot be used as main
    model'. Las 20 celdas de la primera corrida se perdieron por esto. Es la
    CUARTA vez en este repo que un match por substring se lleva un modelo que
    no era suyo (flota.CEREBROS, comparar_modelos._CTX_POR_MODELO y
    perfiles_arranque ya lo pagaron con 'nemotron').
    """
    if not DIR_MODELOS.is_dir():
        return None
    cand = sorted(m for m in DIR_MODELOS.glob("*.gguf")
                  if ("-of-" not in m.name or "00001-of-" in m.name)
                  and not m.name.lower().startswith(("mmproj", "clip"))
                  and "mmproj" not in m.name.lower())
    if patron:
        for m in cand:
            if patron.lower() in m.name.lower():
                return m
        return None
    return cand[0] if cand else None


def geometria_kv(props: dict) -> dict:
    """Bytes/token TEORICOS del KV a partir de lo que /props expone.

    Se marca como ESTIMADO en la salida: llama-server no publica el tamano
    real del buffer KV por HTTP, asi que este numero es geometria, no medida.
    Sirve para saber si la VRAM observada cuadra con la teoria, no para
    sustituirla.
    """
    md = props.get("model_meta") or {}
    n_capas = md.get("n_layer") or md.get("block_count")
    n_kv_heads = md.get("n_head_kv")
    dim_cabeza = md.get("n_embd_head_k")
    if not (n_capas and n_kv_heads and dim_cabeza):
        return {"estimado": False, "motivo": "geometria no expuesta en /props"}
    bytes_tok = 2 * int(n_capas) * int(n_kv_heads) * int(dim_cabeza) * 2  # K y V, f16
    return {"estimado": True, "bytes_por_token_f16": bytes_tok,
            "n_layer": n_capas, "n_head_kv": n_kv_heads,
            "n_embd_head_k": dim_cabeza}


# ------------------------------------------------------------- servidor

def arrancar(exe: Path, modelo: Path, ctx: int, cfg: dict,
             cache_ram_mib: int) -> tuple[subprocess.Popen | None, str]:
    """Arranca llama-server para una celda. Devuelve (proc, motivo_fallo)."""
    cmd = [str(exe), "--model", str(modelo), "--host", "127.0.0.1",
           "--port", str(PUERTO_BANCO), "--ctx-size", str(ctx),
           "--parallel", "1", "--n-gpu-layers", "99",
           "--flash-attn", "on", "--jinja",
           "--cache-ram", str(cache_ram_mib),
           # --fit off: sin esto el binario RECORTA el contexto en silencio
           # cuando no cabe, y el banco anotaria "256k OK" sirviendo 90k.
           # Con off, lo que no cabe falla visible, que es el dato que
           # buscamos en el barrido de estres.
           "--fit", "off"]
    # NO se pasa --log-disable: el log del servidor es el UNICO sitio donde
    # aparece POR QUE una celda no arranco (OOM, flag desconocido, gguf roto).
    # Silenciarlo convirtio la primera corrida entera en veinte "murio, exit
    # 1" sin una sola pista. Un banco que no puede explicar sus fallos mide
    # la mitad de lo que cree medir.
    if cfg["ctk"]:
        cmd += ["--cache-type-k", cfg["ctk"]]
    if cfg["ctv"]:
        cmd += ["--cache-type-v", cfg["ctv"]]
    if cfg["nkvo"]:
        cmd += ["--no-kv-offload"]

    log = open(RAIZ / "scratchpad" / f"banco_kv_server_{PUERTO_BANCO}.log",
               "w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)
    limite = time.time() + TIMEOUT_ARRANQUE
    while time.time() < limite:
        if proc.poll() is not None:
            return None, f"el servidor murio al arrancar (exit {proc.returncode})"
        try:
            _get_json(f"http://127.0.0.1:{PUERTO_BANCO}/health", timeout=3)
            return proc, ""
        except Exception:
            time.sleep(2.0)
    matar(proc)
    return None, f"timeout de arranque ({TIMEOUT_ARRANQUE:.0f}s)"


def matar(proc: subprocess.Popen | None) -> None:
    """Mata el arbol del servidor. taskkill /T porque matar el shell NO mata
    el proceso (leccion medida: un banco 'abortado' siguio 2 h ocupando el
    unico slot de la GPU)."""
    if proc is None:
        return
    try:
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                       capture_output=True, timeout=30)
    except Exception:
        pass
    try:
        proc.wait(timeout=30)
    except Exception:
        pass
    # Que la VRAM vuelva de verdad antes de la siguiente celda.
    time.sleep(3.0)


# ------------------------------------------------------------- el prompt

AGUJA = "El codigo de verificacion del banco es MARFIL-7392."

RELLENO = (
    "El sistema registra cada operacion de mantenimiento en la bitacora "
    "correspondiente, indicando la fecha, el responsable y el resultado "
    "observado. Los turnos de revision se reparten entre los equipos de "
    "guardia segun el calendario aprobado, y cualquier desviacion se anota "
    "en el parte diario para que el turno siguiente pueda continuar el "
    "trabajo sin perder informacion. "
)


def construir_prompt(n_tokens_objetivo: int) -> str:
    """Prompt de ~n_tokens_objetivo con la aguja plantada por el MEDIO.

    Por el medio y no al final a proposito: el final lo recuerda cualquier
    modelo y el principio tambien; el medio es donde se ve la degradacion.
    """
    # ~1 token cada 4 caracteres para el primer corte; el tamano REAL se
    # verifica despues con /tokenize y se anota el numero exacto.
    chars_objetivo = n_tokens_objetivo * 4
    repeticiones = max(1, chars_objetivo // len(RELLENO))
    mitad = repeticiones // 2
    cuerpo = (RELLENO * mitad) + " " + AGUJA + " " + (RELLENO * (repeticiones - mitad))
    return ("Lee el siguiente parte de mantenimiento y responde solo con el "
            "codigo de verificacion que aparece en el.\n\n" + cuerpo +
            "\n\nPregunta: cual es el codigo de verificacion del banco?")


def contar_tokens(texto: str) -> int | None:
    try:
        r = _post_json(f"http://127.0.0.1:{PUERTO_BANCO}/tokenize",
                       {"content": texto}, timeout=180)
        return len(r.get("tokens") or [])
    except Exception:
        return None


# ------------------------------------------------------------- una celda

def medir_celda(exe: Path, modelo: Path, ctx: int, clave_cfg: str,
                cache_ram_mib: int, frac_prompt: float) -> dict:
    cfg = CONFIGS[clave_cfg]
    fila = {
        "ts": _ahora(), "config": clave_cfg, "config_nombre": cfg["nombre"],
        "ctx_pedido": ctx, "modelo": modelo.name,
        "cache_ram_mib": cache_ram_mib,
        "ctk": cfg["ctk"] or "f16", "ctv": cfg["ctv"] or "f16",
        "no_kv_offload": cfg["nkvo"],
        "ok": False, "motivo": "",
    }
    vram_antes = vram_usada_mib()
    ram_libre_antes = ram_libre_mib()
    fila["vram_antes_mib"] = vram_antes
    fila["ram_libre_antes_mib"] = ram_libre_antes

    # GUARDA DE VALIDEZ. La VRAM que ya esta ocupada cuando arranca la celda
    # NO es una curiosidad: es cuanta placa le queda al modelo, y decide si
    # cabe o spillea. Sin esta marca, la primera corrida de este banco dejo
    # dos celdas con vram_antes=4.220 MiB (navegador y pruebas del REPL
    # abiertos) contra una con 435 MiB, y el resultado fue absurdo: f16 a
    # 32k daba 66 tok/s de prefill y f16 a 65k daba 750. Un contexto MAYOR no
    # puede ir once veces mas rapido; lo que cambiaba era el escritorio.
    #
    # No se aborta la celda: se MARCA. Un banco que se niega a medir porque
    # hay un Chrome abierto no mide nunca en esta maquina. Lo que no puede
    # pasar es que las filas se comparen entre si como si fueran iguales.
    fila["linea_base_sucia"] = bool(
        vram_antes is not None and vram_antes > UMBRAL_VRAM_LIMPIA_MIB)
    if fila["linea_base_sucia"]:
        print(f"      AVISO: la GPU ya tiene {vram_antes} MiB ocupados "
              f"(> {UMBRAL_VRAM_LIMPIA_MIB}); esta celda NO es comparable "
              f"con las medidas en frio")

    t0 = time.time()
    proc, fallo = arrancar(exe, modelo, ctx, cfg, cache_ram_mib)
    fila["segundos_arranque"] = round(time.time() - t0, 1)
    if proc is None:
        fila["motivo"] = fallo
        # El log del servidor dice si fue OOM; guardar la ultima linea util.
        try:
            txt = (RAIZ / "scratchpad" /
                   f"banco_kv_server_{PUERTO_BANCO}.log").read_text(
                       encoding="utf-8", errors="replace")
            errores = [l for l in txt.splitlines()
                       if re.search(r"error|failed|out of memory|oom", l, re.I)]
            fila["log_error"] = errores[-3:] if errores else txt.splitlines()[-3:]
        except Exception:
            pass
        return fila

    try:
        props = _get_json(f"http://127.0.0.1:{PUERTO_BANCO}/props", timeout=60)
        gen = props.get("default_generation_settings") or {}
        fila["n_ctx_servido"] = gen.get("n_ctx")
        fila["total_slots"] = props.get("total_slots")
        fila["geometria_kv_estimada"] = geometria_kv(props)

        # VRAM y RAM con el modelo cargado y el KV reservado, ANTES de generar.
        fila["vram_cargado_mib"] = vram_usada_mib()
        fila["ram_proceso_cargado_mib"] = ram_proceso_mib(proc.pid)
        fila["ram_libre_cargado_mib"] = ram_libre_mib()
        if vram_antes is not None and fila["vram_cargado_mib"] is not None:
            fila["vram_delta_mib"] = fila["vram_cargado_mib"] - vram_antes

        # El prompt ocupa `frac_prompt` del contexto SERVIDO (no del pedido:
        # si el binario recorto, medir sobre lo que hay de verdad).
        servido = int(fila.get("n_ctx_servido") or ctx)
        objetivo = max(256, int(servido * frac_prompt) - N_GENERAR - 64)
        prompt = construir_prompt(objetivo)
        n_tok = contar_tokens(prompt)
        # Si nos pasamos del contexto servido, recortar por caracteres hasta
        # entrar. Un HTTP 400 exceed_context_size no es un dato de velocidad.
        while n_tok and n_tok > servido - N_GENERAR - 32:
            prompt = prompt[: int(len(prompt) * 0.9)]
            n_tok = contar_tokens(prompt)
        fila["prompt_tokens_exactos"] = n_tok

        t1 = time.time()
        r = _post_json(
            f"http://127.0.0.1:{PUERTO_BANCO}/completion",
            {"prompt": prompt, "n_predict": N_GENERAR, "temperature": 0.0,
             "cache_prompt": False},
            timeout=TIMEOUT_PETICION)
        fila["segundos_peticion"] = round(time.time() - t1, 1)

        t = r.get("timings") or {}
        fila["timings"] = t
        fila["prefill_tok_s"] = t.get("prompt_per_second")
        fila["gen_tok_s"] = t.get("predicted_per_second")
        fila["prompt_ms"] = t.get("prompt_ms")
        fila["predicted_ms"] = t.get("predicted_ms")
        fila["prompt_n"] = t.get("prompt_n")
        fila["predicted_n"] = t.get("predicted_n")
        # TTFT REAL: el prefill entero mas el primer token. Con streaming
        # apagado no hay forma mas fina, y llamarlo "TTFT" sin decir esto
        # seria inventar precision. prompt_ms es la parte dominante y ES
        # medida por el servidor.
        if t.get("prompt_ms") is not None and t.get("predicted_per_second"):
            fila["ttft_ms_aprox"] = round(
                t["prompt_ms"] + 1000.0 / t["predicted_per_second"], 1)

        contenido = (r.get("content") or "")
        fila["respuesta"] = contenido[:300]
        fila["aguja_ok"] = "MARFIL-7392" in contenido.upper()

        fila["vram_pico_mib"] = vram_usada_mib()
        fila["ram_proceso_pico_mib"] = ram_proceso_mib(proc.pid)
        fila["ram_libre_pico_mib"] = ram_libre_mib()
        fila["ok"] = True
    except urllib.error.HTTPError as e:
        try:
            fila["motivo"] = f"HTTP {e.code}: {e.read().decode('utf-8')[:300]}"
        except Exception:
            fila["motivo"] = f"HTTP {e.code}"
    except Exception as e:
        fila["motivo"] = f"{type(e).__name__}: {e}"
    finally:
        matar(proc)
    return fila


# ------------------------------------------------------------- principal

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--modelo", default="qwen3.8-27b",
                    help="substring del gguf (defecto: qwen3.8-27b)")
    ap.add_argument("--ctxs", default="",
                    help="lista de ventanas separadas por coma")
    ap.add_argument("--configs", default="A,C",
                    help="configuraciones a correr (A,B,C,D)")
    ap.add_argument("--cache-ram", type=int, default=1024,
                    help="MiB de --cache-ram (defecto 1024, el de Cognia hoy)")
    ap.add_argument("--frac-prompt", type=float, default=0.5,
                    help="fraccion del contexto que ocupa el prompt (0.5)")
    ap.add_argument("--estres", action="store_true",
                    help="barrido de estres hasta encontrar el techo real")
    ap.add_argument("--salida", default="scratchpad/banco_kv.jsonl")
    args = ap.parse_args()

    exe = binario()
    if exe is None:
        print(f"ERROR: no encuentro llama-server en {DIR_LLAMA}")
        return 2
    modelo = elegir_modelo(args.modelo)
    if modelo is None:
        print(f"ERROR: no encuentro un gguf que case '{args.modelo}' en {DIR_MODELOS}")
        return 2

    if args.ctxs:
        ctxs = [int(x) for x in args.ctxs.split(",") if x.strip()]
    else:
        ctxs = CTXS_ESTRES if args.estres else CTXS_DEFECTO
    claves = [c.strip().upper() for c in args.configs.split(",") if c.strip()]
    for c in claves:
        if c not in CONFIGS:
            print(f"ERROR: config desconocida '{c}' (validas: A,B,C,D)")
            return 2

    salida = RAIZ / args.salida
    salida.parent.mkdir(parents=True, exist_ok=True)

    print(f"banco_kv | modelo={modelo.name} | exe={exe}")
    print(f"  configs={claves} ctxs={ctxs} cache_ram={args.cache_ram} MiB")
    print(f"  bitacora append-only: {salida}")
    ver = subprocess.run([str(exe), "--version"], capture_output=True,
                         text=True, timeout=60)
    build = (ver.stdout + ver.stderr).strip().splitlines()[0] if ver else "?"
    print(f"  {build}\n")

    # Cabecera de la corrida: sin esto, dos corridas de dias distintos se
    # mezclan en el mismo fichero y no hay forma de separarlas.
    with salida.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"tipo": "cabecera", "ts": _ahora(),
                            "modelo": modelo.name, "build": build,
                            "configs": claves, "ctxs": ctxs,
                            "cache_ram_mib": args.cache_ram,
                            "frac_prompt": args.frac_prompt},
                           ensure_ascii=False) + "\n")
        f.flush()

    total = len(claves) * len(ctxs)
    hecho = 0
    for clave in claves:
        # Si una config falla dos ventanas seguidas por no caber, las mayores
        # tampoco van a caber: se anotan como no-intentadas en vez de gastar
        # 5 minutos de arranque fallido cada una.
        fallos_seguidos = 0
        for ctx in ctxs:
            hecho += 1
            etiqueta = f"[{hecho}/{total}] {clave} ctx={ctx:,}"
            if fallos_seguidos >= 2:
                print(f"{etiqueta}  SALTADA (las dos anteriores no cupieron)")
                with salida.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(
                        {"tipo": "celda", "ts": _ahora(), "config": clave,
                         "ctx_pedido": ctx, "ok": False,
                         "motivo": "saltada: techo alcanzado en esta config"},
                        ensure_ascii=False) + "\n")
                    f.flush()
                continue
            print(f"{etiqueta}  ...", flush=True)
            fila = medir_celda(exe, modelo, ctx, clave, args.cache_ram,
                               args.frac_prompt)
            fila["tipo"] = "celda"
            with salida.open("a", encoding="utf-8") as f:
                f.write(json.dumps(fila, ensure_ascii=False) + "\n")
                f.flush()
            if fila["ok"]:
                fallos_seguidos = 0
                print(f"{etiqueta}  OK  n_ctx={fila.get('n_ctx_servido'):,} "
                      f"prompt={fila.get('prompt_tokens_exactos')} tok | "
                      f"prefill={fila.get('prefill_tok_s')} tok/s | "
                      f"gen={fila.get('gen_tok_s')} tok/s | "
                      f"VRAM={fila.get('vram_cargado_mib')} MiB | "
                      f"RAM_proc={fila.get('ram_proceso_pico_mib')} MiB | "
                      f"aguja={'si' if fila.get('aguja_ok') else 'NO'}")
            else:
                fallos_seguidos += 1
                print(f"{etiqueta}  FALLO: {fila['motivo']}")

    print(f"\nlisto. {salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
