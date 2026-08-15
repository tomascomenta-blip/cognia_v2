"""
servir_modelo.py — Levanta el llama-server que Cognia espera encontrar.

POR QUE EXISTE: sin backend, Cognia degrada a sus fallbacks en silencio — es el
modo de fallo que mas costo cazar la madrugada del 2026-07-20. El doctor y el
bucle del agente ya avisan ("arranca llama-server o configura COGNIA_LLM_URL"),
pero no habia ningun comando que lo hiciera: habia que recordar la ruta del
binario, el modelo y los flags.

    python scripts/servir_modelo.py                 # el modelo por defecto
    python scripts/servir_modelo.py --modelo UIGEN  # por trozo del nombre
    python scripts/servir_modelo.py --listar        # que hay instalado

Sirve en el puerto 8080, que es el que sondea cognia/llm_local.py. Si ya hay
algo respondiendo ahi, no arranca otro: avisa y sale.

Solo stdlib.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DIR_MODELOS = Path.home() / ".cognia" / "models"
DIR_LLAMA   = Path.home() / ".cognia" / "llama"
PUERTO      = 8080          # el que sondea llm_local.py
CTX         = 8192
ESPERA_SEG  = 240

# Preferencia por defecto: el coder de 14B, que es con el que se midio todo.
PREFERIDOS = ("qwen2.5-coder-14b", "qwen2.5-coder", "qwen2.5")

# Tipos de cache KV que acepta llama-server b10066 (--cache-type-k/-v).
# Validados en argparse para fallar ANTES de lanzar: un valor invalido haria
# morir el server al arrancar con un log criptico.
CACHES_KV = ("f32", "f16", "bf16", "q8_0", "q4_0", "q4_1", "iq4_nl",
             "q5_0", "q5_1")


# Perfiles de arranque POR MODELO, con flags MEDIDOS en esta maquina. Solo se
# aplican si el basename del gguf casa el patron: para cualquier otro modelo el
# comando sale byte-identico al historico (contrafactual del test de regresion).
#
# nemotron (2026-08-14, RTX 5060 Ti 16 GB): el gguf pesa 17,6 GB y NO cabe
# entero en VRAM, pero es MoE 128x2.4B con solo 6 activos y solo 6 de sus 52
# capas tienen KV (el resto es Mamba2). Medido:
#   - `--fit on` reparte los expertos GPU/CPU solo; con --ctx-size EXPLICITO
#     NO toca el contexto (verificado: pedi 1.048.576 y /props devolvio
#     1.048.576). Por eso aca fit_off queda en False a proposito: con off el
#     server no reparte y muere por OOM.
#   - `--no-mmap` + batch grande: prefill 645 -> 1.023 tok/s en el mismo
#     escalon de 32k (+59%). El propio log lo pide cuando hay tensores en CPU.
#   - KV q8_0: el MILLON entero entra en 14.622 MiB con los pesos.
# Sonda de punta a punta: prompt real de 1.046.706 tokens, aguja recuperada.
# La clave es 'nemotron-3.5' y NO 'nemotron' a secas: en ~/.cognia/models/ hay
# OpenReasoning-Nemotron-14B (denso, ctx viable 16.384) y nemotron-mtp (la
# cabeza MTP de 1,1 GB). Con la clave corta, el combo 'pensar-en-lazo' —que
# arranca justamente --modelo OpenReasoning— habria pedido un KV de 1M sobre
# un denso de 48 capas: ~103 GB solo de KV contra 16.311 MiB de placa. Es la
# TERCERA tabla del repo que casa modelos por substring y la tercera vez que
# 'nemotron' se lleva lo que no es suyo (ya paso en flota.CEREBROS y en
# comparar_modelos._CTX_POR_MODELO). Por eso, ademas, el match va de patron
# MAS LARGO a mas corto: que la proxima entrada no reabra el agujero por el
# orden en que alguien la escriba.
PERFILES_ARRANQUE = {
    "nemotron-3.5": {"ctx": 1048576, "ctk": "q8_0", "ctv": "q8_0",
                     "no_mmap": True, "batch": 4096, "ubatch": 1024,
                     "sin_draft": True},
}


def perfil_arranque(modelo) -> dict:
    """Flags extra medidos para ese gguf, o {} si no hay perfil."""
    nombre = Path(modelo).name.lower()
    for patron in sorted(PERFILES_ARRANQUE, key=len, reverse=True):
        if patron in nombre:
            return dict(PERFILES_ARRANQUE[patron])
    return {}


def construir_cmd(exe, modelo, puerto, ctx, *, ctk="", ctv="",
                  fit_off=False, no_mmap=False, batch=0, ubatch=0) -> list:
    """Arma el comando base de llama-server (sin el draft, que se agrega
    despues como siempre). Factorizado para el test de regresion: SIN los
    flags nuevos (ctk/ctv/fit_off) el resultado es BYTE-IDENTICO al
    historico; los aditivos van al FINAL para no perturbar el orden.

    --parallel 1 EXPLICITO: las builds recientes usan 4 slots por defecto y
    PARTEN --ctx-size entre ellos (cazado 2026-07-28: HTTP 500 silenciosos
    en el 50% del gate BoN). Un cliente secuencial no necesita slots."""
    orden = [str(exe), "--model", str(modelo), "--port", str(puerto),
             "--ctx-size", str(ctx), "--parallel", "1",
             "--n-gpu-layers", "99", "--flash-attn", "on", "--jinja"]
    if ctk:
        orden += ["--cache-type-k", ctk]
    if ctv:
        orden += ["--cache-type-v", ctv]
    if fit_off:
        # b10066 defaultea --fit on y auto-reduce el contexto EN SILENCIO:
        # con off, si no cabe falla visible en vez de falsear el n_ctx pedido.
        # MATIZ medido 2026-08-14: lo que --fit ajusta son los argumentos NO
        # puestos; con --ctx-size explicito el contexto no se toca (por eso
        # los modelos que necesitan reparto MoE pueden usar fit on sin
        # perder la ventana). El chequeo de n_ctx post-arranque lo verifica.
        orden += ["--fit", "off"]
    if no_mmap:
        orden += ["--no-mmap"]
    if batch:
        orden += ["--batch-size", str(batch)]
    if ubatch:
        orden += ["--ubatch-size", str(ubatch)]
    return orden


def binario() -> Path | None:
    for nombre in ("llama-server.exe", "llama-server"):
        ruta = DIR_LLAMA / nombre
        if ruta.exists():
            return ruta
    return None


def modelos() -> list[Path]:
    if not DIR_MODELOS.is_dir():
        return []
    # De los ficheros partidos (-00001-of-0000N) solo interesa el primero:
    # llama.cpp carga el resto solo.
    return sorted(m for m in DIR_MODELOS.glob("*.gguf")
                  if "-of-" not in m.name or "00001-of-" in m.name)


def elegir(patron: str | None) -> Path | None:
    disponibles = modelos()
    if not disponibles:
        return None
    if patron:
        p = patron.lower()
        for m in disponibles:
            if p in m.name.lower():
                return m
        return None
    for pref in PREFERIDOS:
        for m in disponibles:
            if pref in m.name.lower():
                return m
    return disponibles[0]


def responde(puerto: int, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{puerto}/health", timeout=timeout) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError):
        return False


def estado(puerto: int, timeout: float = 2.0) -> str:
    """'ok' | 'cargando' | 'ausente'. El 503 de /health significa que HAY un
    server cargando su modelo (asi responde llama-server durante la carga):
    el puerto esta ocupado y arrancar otro ahi solo puede fallar. responde()
    lo daba por ausente (mismo bug que la adopcion en node/llama_backend,
    A1 2026-08-01)."""
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{puerto}/health", timeout=timeout):
            return "ok"
    except urllib.error.HTTPError as e:
        return "cargando" if e.code == 503 else "ok"
    except (urllib.error.URLError, OSError):
        return "ausente"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--modelo", help="trozo del nombre del .gguf a servir")
    ap.add_argument("--puerto", type=int, default=PUERTO)
    ap.add_argument("--ctx", type=int, default=CTX)
    ap.add_argument("--listar", action="store_true", help="ver modelos y salir")
    ap.add_argument("--sin-draft", action="store_true",
                    help="servir sin decodificacion especulativa")
    # Flags aditivos (ola 2): sin ellos el comando armado no cambia ni un byte.
    ap.add_argument("--pid-file",
                    help="escribe el PID del llama-server lanzado a esa ruta "
                         "(lo lee el summoner; sin esto el Popen abandona el "
                         "handle y el kill selectivo es imposible)")
    ap.add_argument("--ctk", choices=CACHES_KV,
                    help="tipo de cache KV para K (--cache-type-k)")
    ap.add_argument("--ctv", choices=CACHES_KV,
                    help="tipo de cache KV para V (--cache-type-v)")
    ap.add_argument("--fit-off", action="store_true",
                    help="pasa --fit off (b10066 auto-reduce el ctx en "
                         "silencio con fit on)")
    args = ap.parse_args()

    if args.listar:
        disponibles = modelos()
        if not disponibles:
            print(f"No hay .gguf en {DIR_MODELOS}")
            return 1
        print(f"Modelos en {DIR_MODELOS}:")
        for m in disponibles:
            print(f"  {m.stat().st_size / 1e9:6.1f} GB  {m.name}")
        return 0

    est = estado(args.puerto)
    if est == "ok":
        print(f"Ya hay un servidor respondiendo en :{args.puerto}. No arranco otro.")
        return 0
    if est == "cargando":
        print(f"Ya hay un servidor CARGANDO su modelo en :{args.puerto}. "
              f"No arranco otro; espera a que /health responda ok.")
        return 0

    exe = binario()
    if exe is None:
        print(f"No encuentro llama-server en {DIR_LLAMA}", file=sys.stderr)
        return 1

    modelo = elegir(args.modelo)
    if modelo is None:
        print(f"No encuentro modelo{' que case con ' + args.modelo if args.modelo else ''} "
              f"en {DIR_MODELOS}. Usa --listar para ver que hay.", file=sys.stderr)
        return 1

    # Perfil por modelo: rellena SOLO lo que el usuario no pidio a mano (un
    # flag explicito siempre gana al perfil), y sin perfil no cambia nada.
    perfil = perfil_arranque(modelo)
    ctx = args.ctx
    if perfil:
        if args.ctx == CTX:          # el default, no una eleccion del usuario
            ctx = perfil.get("ctx", ctx)
        if not args.ctk:
            args.ctk = perfil.get("ctk", "")
        if not args.ctv:
            args.ctv = perfil.get("ctv", "")
        if perfil.get("sin_draft"):
            args.sin_draft = True
        print(f"  + perfil de arranque medido para {modelo.name} "
              f"(ctx {ctx:,}, KV {args.ctk or 'f16'})")

    # El comando base vive en construir_cmd() (factorizado para el test de
    # regresion byte-identico; el POR QUE de --parallel 1 esta alla).
    orden = construir_cmd(exe, modelo, args.puerto, ctx,
                          ctk=args.ctk or "", ctv=args.ctv or "",
                          fit_off=args.fit_off,
                          no_mmap=perfil.get("no_mmap", False),
                          batch=perfil.get("batch", 0),
                          ubatch=perfil.get("ubatch", 0))

    # Decodificacion especulativa: el 0.5B borra tokens y el 14B los verifica
    # y corrige — la salida es IDENTICA a la del 14B solo, pero mas rapida.
    # Medido el 2026-07-20 en esta maquina (300 tokens, mismas peticiones):
    #   codigo:  43.9 -> 107.4 tok/s (2.4x)
    #   espanol: 43.9 ->  47.8 tok/s
    # El p-min 0.6 es lo que evita el caso malo: sin el, en prosa espanola el
    # 0.5B (que es un coder) proponia basura, el 14B la rechazaba casi toda
    # (9% aceptado) y el total CAIA a 33 tok/s. Con p-min solo borra cuando
    # esta confiado: 66% de aceptacion en prosa y sin penalizacion.
    # OJO: --spec-type draft-simple es OBLIGATORIO — sin el, el server acepta
    # --spec-draft-model, lo ignora EN SILENCIO y sirve sin draft.
    draft = None
    if not args.sin_draft:
        preferido = modelo.name.lower()
        for m in modelos():
            if "0.5b" in m.name.lower() and m != modelo \
                    and preferido.split("-")[0] in m.name.lower():
                draft = m
                break
    if draft is not None:
        orden += ["--spec-draft-model", str(draft),
                  "--spec-type", "draft-simple",
                  "--spec-draft-ngl", "99",
                  "--spec-draft-n-max", "16",
                  "--spec-draft-p-min", "0.6"]
        print(f"  + draft especulativo: {draft.name} (2.4x medido en codigo)")

    print(f"Sirviendo {modelo.name} en :{args.puerto} (ctx {ctx:,})...")
    proceso = subprocess.Popen(
        orden,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    # PID a disco APENAS lanzado (no tras el health): si la carga cuelga, el
    # summoner igual puede matar selectivo por PID en vez del /IM global.
    if args.pid_file:
        try:
            Path(args.pid_file).write_text(str(proceso.pid), encoding="utf-8")
        except OSError as exc:
            print(f"AVISO: no pude escribir el pid-file {args.pid_file}: {exc}",
                  file=sys.stderr)

    inicio = time.time()
    while time.time() - inicio < ESPERA_SEG:
        if responde(args.puerto):
            # Chequeo ejecutable, no lección en prosa: /health con 4 slots
            # silenciosos ya nos costó una corrida entera (2026-07-28, gate
            # BoN v1: ctx/4 por slot → HTTP 500 al 50% de los prompts).
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{args.puerto}/props",
                        timeout=5) as r:
                    props_srv = json.loads(r.read())
                slots = props_srv.get("total_slots")
                # La ventana SERVIDA, no la pedida: --fit y el padding a
                # multiplo de 256 pueden dejar otra, y una ventana fantasma
                # falsea toda medicion posterior ("cargar no es funcionar").
                servido = ((props_srv.get("default_generation_settings") or {})
                           .get("n_ctx"))
                if servido and abs(int(servido) - ctx) > 256:
                    print(f"AVISO: pediste ctx {ctx:,} y el server sirve "
                          f"{int(servido):,}. Lo que mida esta sesion es la "
                          f"ventana SERVIDA, no la pedida.", file=sys.stderr)
                if slots != 1:
                    print(f"AVISO: el server reparte el contexto entre "
                          f"{slots} slots ({args.ctx // (slots or 1)} tokens "
                          f"c/u). Esta build ignoro --parallel 1; los "
                          f"prompts largos van a recibir HTTP 500.",
                          file=sys.stderr)
            except Exception:
                pass    # /props puede no existir en builds viejas
            print(f"Listo en {time.time() - inicio:.0f}s. "
                  f"Cognia ya lo detecta (llm_local sondea :{PUERTO}).")
            print(f"Para pararlo: taskkill /IM {exe.name} /F")
            return 0
        if proceso.poll() is not None:
            print(f"El servidor murio al arrancar (codigo {proceso.returncode}). "
                  f"¿Cabe el modelo en la GPU?", file=sys.stderr)
            return 1
        time.sleep(2)

    print(f"No respondio en {ESPERA_SEG}s.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
