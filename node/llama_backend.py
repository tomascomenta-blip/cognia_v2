"""
node/llama_backend.py
=====================
Optional llama.cpp acceleration layer for local inference.

Priority order:
  1. llama-cpp-python (in-process, fastest)
  2. llama-server subprocess (pre-built binary, OpenAI-compatible REST API)
  3. Returns None → orchestrator falls back to numpy/C shard inference

This module NEVER raises — every public function returns None on failure so
the rest of Cognia keeps working unchanged.

Setup: el camino recomendado es `cognia install-model` — descarga el GGUF 3B
Q4_K_M + llama-server b9391 + fleet de expertos a ~/.cognia/ y escribe
LLAMA_GGUF_PATH / LLAMA_SERVER_PATH en ~/.cognia/config.env (apply_config()
los carga en todos los entry points). Manual (avanzado): definir esas claves
en config.env apuntando a un GGUF/binario propios; LLAMA_SERVER_PORT opcional
(default 8088, evita chocar con app :8000).

NOTE: node/llama-server.exe is pinned to b9391 (7fb1e70b5) — b9414 has a ~37% CPU
decode regression measured on i3-10110U (5.2 vs 8.2 tok/s). Do NOT update the binary
without re-running the A/B (real server, /completion, timings.predicted_per_second).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _request_timeout_s(max_tokens: int, payload_len: int) -> int:
    """Timeout del request a llama-server. urlopen(timeout) es de SOCKET:
    en generate() no-streaming el server calla hasta terminar prefill+decode
    (actúa como límite total) y en streaming el prefill es el único silencio
    largo. Tres términos: base 30s + decode (0.6 s/token cubre el peor caso
    ~2 tok/s) + PREFILL (~4 chars/token a ~6 tok/s peor-caso ≈ 1 s cada 25
    bytes de payload). Sin el término de prefill, prompts largos (feromona /
    contexto crecido) timeouteaban en máquinas lentas aunque el server
    estuviera computando (medido 2026-07-14: 4+ gens quemadas con el server
    a 2.5 hilos activos). El divisor 25 (antes 60) sale del peor caso REAL
    de esa noche: con la RAM al límite el mmap del GGUF queda parcialmente
    frío y el prefill paga page-ins de disco (~3-6 tok/s); con //60 seguía
    quemándose ~6% de las gens. Un timeout holgado NO ralentiza requests
    rápidos (corta apenas llega la respuesta) — solo tolera los lentos."""
    return max(120, 30 + int(max_tokens * 0.6) + payload_len // 25)


_ux_events = None   # cache: modulo cognia.ux.events, o False si no importable


def _eventos_ux():
    """El bus de eventos de UX (cognia/ux/events.py), o None si no esta.

    Import LAZY y cacheado, jamas a nivel de modulo: importar cognia dispara
    su __init__ (subsistemas enteros) y node/ tiene que poder correr solo.
    Cuando el CLI ya cargo cognia, esto es un lookup de sys.modules; cuando
    no hay cognia (nodo suelto), falla UNA vez y queda False. emitir() es
    no-lanzante por contrato: nada de esto puede romper una generacion."""
    global _ux_events
    if _ux_events is None:
        try:
            from cognia.ux import events as _ev
            _ux_events = _ev
        except Exception:
            _ux_events = False
    return _ux_events or None


def _es_timeout(exc: Exception) -> bool:
    """True si exc es un timeout de socket (directo o envuelto en URLError).

    socket.timeout es alias de TimeoutError desde 3.10; urlopen a veces lo
    entrega crudo (timeout de lectura) y a veces envuelto (timeout de connect).
    Se usa para distinguir "backend OCUPADO" (timeout con /health ok, p.ej.
    --parallel 1 y otro cliente en el slot) de "backend ausente"."""
    if isinstance(exc, TimeoutError):
        return True
    import urllib.error
    return (isinstance(exc, urllib.error.URLError)
            and isinstance(getattr(exc, "reason", None), TimeoutError))


# ── Config ────────────────────────────────────────────────────────────────────

# 8080 y no 8088 (cambiado 2026-07-25): eran DOS backends. Este arrancaba
# llama-server en :8088 con LLAMA_GGUF_PATH y atendia chat/agente/create_program,
# mientras cognia/llm_local.py sondeaba :8080, que es donde
# scripts/servir_flota.py sirve la flota adoptada por gate. Resultado medido: los
# productos salian del qwen2.5-7b RETIRADO por la auditoria del 24/07 y la flota
# estaba apagada. Con un solo puerto, si la flota corre este backend la ADOPTA
# (ver _ping/_check_adopted_server abajo) en vez de levantar un segundo modelo.
_DEFAULT_PORT   = int(os.environ.get("LLAMA_SERVER_PORT", "8080"))
# 90s cubria el GGUF 3B de 1.9GB, pero el 7B (4.7GB) tarda >90s en carga fria en
# el i3 (falla "did not start within 90s", medido 2026-07-04). El wait es un
# poll a /health que CORTA apenas responde, asi que un timeout mas alto NO
# ralentiza un arranque rapido — solo tolera cargas lentas. Env-overridable.
_SERVER_TIMEOUT = int(os.environ.get("LLAMA_SERVER_TIMEOUT", "240"))  # seg
# BORRADO 2026-08-17: `_CTX_SIZE = int(os.environ.get("LLAMA_CTX_SIZE", "32768"))`.
# Era la env leida EN EL IMPORT y su unico consumidor era la guarda de ctx de
# generate_long, que asi presupuestaba contra una cifra que nadie habia
# comprobado contra el server. Con ~/.cognia/config.env poniendo
# LLAMA_CTX_SIZE=200192 y el :8080 sirviendo 16.384, la guarda creia tener
# 150.144 tokens de prefill y no recortaba nunca -> HTTP 400
# exceed_context_size a mitad de una generacion larga (repro medida; ver
# LlamaBackend.n_ctx_efectivo). Ahora la ventana se PREGUNTA al server via
# /props, y la env sobrevive solo como respaldo en _ctx_size() de abajo, que
# ademas se lee en tiempo de llamada.
_N_GPU_LAYERS   = 0       # CPU only; Intel UHD integrated GPU (Vulkan) is slower than CPU on i3-10110U (3.8 vs 8.8 tok/s)

def _env_int(name: str, default: int) -> int:
    """Read an int from the environment, falling back to `default` if unset/garbage."""
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        logger.warning("[llama_backend] %s is not an int; using %d", name, default)
        return default


# All three are machine-dependent, so they are env-overridable with the historical
# defaults. Read at CALL time (not import time) so cognia/perf_profiles.py can switch
# CPU/GPU knobs at runtime and the next backend construction picks them up.
# LLAMA_N_GPU_LAYERS=0 (default) keeps the CPU-only behaviour measured on the i3-10110U,
# where the Intel UHD iGPU (Vulkan) was SLOWER than the CPU (3.8 vs 8.8 tok/s).
# On a machine with a real CUDA GPU set LLAMA_N_GPU_LAYERS=99 to offload every layer.

def _ctx_size() -> int:
    # 4096 es DELIBERADO (piso seguro para maquinas CPU de gama baja): es el
    # ctx con el que se ARRANCA un server propio o un llama-cpp-python cuando
    # nadie pide otra cosa, y subirlo cambiaria el consumo de RAM de toda
    # instalacion sin LLAMA_CTX_SIZE. Quien quiera mas contexto lo pide por
    # env/perfil; ver cognia/perf_profiles.py.
    # Ojo con el rol: esto dice CON QUE VENTANA SE ARRANCA, no con cual se
    # esta sirviendo. Para presupuestar contra un server ya vivo (que puede
    # ser adoptado, con otros flags) va LlamaBackend.n_ctx_efectivo(), que
    # pregunta a /props. Confundir las dos cosas fue exactamente el bug de la
    # guarda de ctx (2026-08-17).
    return _env_int("LLAMA_CTX_SIZE", 4096)


def _n_gpu_layers() -> int:
    return _env_int("LLAMA_N_GPU_LAYERS", 0)


def _n_threads() -> int:
    # El default historico era max(4, cpu_count()) = TODOS los hilos logicos.
    # Medido con llama-bench (Qwen3-1.7B Q4_K_M, -ngl 0, tg32, r=5) en la 6c/12t:
    # 12 hilos -> 39.81 tok/s, 6 hilos (fisicos) -> 45.65 tok/s = +14.7%.
    # hilos_cpu_optimos() cappea a nucleos fisicos con piso 4, asi que en el
    # i3-10110U (2 fisicos / 4 logicos) devuelve 4 = el default de siempre.
    from .cpu_threads import hilos_cpu_optimos
    return _env_int("LLAMA_N_THREADS", hilos_cpu_optimos(max(4, os.cpu_count() or 4)))


def _draft_gguf() -> Optional[Path]:
    """Draft GGUF for classic speculative decoding (cognia 'dspark' mode).

    Read at CALL time from LLAMA_DRAFT_GGUF_PATH (persisted/cleared by
    cognia/velocity.py, same pattern as the perf-profile knobs above).
    Returns the path only when the var points to an existing file;
    unset/empty/missing file -> None (no speculative flags added).
    """
    raw = os.environ.get("LLAMA_DRAFT_GGUF_PATH", "").strip()
    if not raw:
        return None
    p = Path(raw)
    if p.is_file():
        return p
    logger.warning("[llama_backend] LLAMA_DRAFT_GGUF_PATH set but file not found: %s", p)
    return None

# Q4_K_M listed first: measured on i3-10110U with llama-server b9391 it is faster
# AND higher quality than Q4_0 — decode 8.09 tok/s / prefill 29.3 tok/s (Q4_K_M)
# vs decode 7.58 / prefill 20.3 (Q4_0). Q3_K_S kept as a smaller fallback.
_GGUF_CANDIDATES = [
    "Qwen2.5-Coder-3B-Instruct-Q4_K_M.gguf",
    "Qwen2.5-Coder-3B-Instruct-Q4_0.gguf",
    "Qwen2.5-Coder-3B-Instruct-Q3_K_S.gguf",
    "Qwen2.5-Coder-3B-Instruct-Q5_K_M.gguf",
    "qwen2.5-coder-3b-instruct-q4_k_m.gguf",
]

_SERVER_BINARIES = [
    "llama-server",
    "llama-server.exe",
    "llama_server",
    "server",                          # older builds
    str(Path(__file__).parent / "llama-server.exe"),
    str(Path(__file__).parent / "llama-server"),
    # instalación estándar (cognia install-model): ~/.cognia/bin/llama-*/
    # (mismo fallback que _find_gguf; el producto instalado no tiene repo)
    *sorted(str(p) for p in
            (Path.home() / ".cognia" / "bin").glob("llama-*/llama-server.exe")),
    *sorted(str(p) for p in
            (Path.home() / ".cognia" / "bin").glob("llama-*/llama-server")),
]


# ── Stop-reason mapping ───────────────────────────────────────────────────────

def _stop_reason(data: dict) -> Optional[str]:
    """Map a /completion response (or final SSE chunk) to 'eos'|'limit'|'word'|None.

    Verified empirically against the pinned b9391 binary (2026-06-10):
    /completion reports stop_type as a string ('eos'|'limit'|'word'|'none')
    plus stopping_word; the LAST streaming SSE chunk carries the same fields.
    /v1/chat/completions streaming instead puts finish_reason ('stop'|'length')
    in choices[0] of the last chunk before [DONE]. Older builds used
    stopped_eos/stopped_limit/stopped_word booleans — kept as fallback.
    """
    st = data.get("stop_type")
    if st in ("eos", "limit", "word"):
        return st
    # Older llama-server builds: boolean flags instead of stop_type
    if data.get("stopped_eos"):
        return "eos"
    if data.get("stopped_limit"):
        return "limit"
    if data.get("stopped_word"):
        return "word"
    # OpenAI-compatible /v1/chat/completions final chunk
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        fr = choices[0].get("finish_reason")
        if fr == "length":
            return "limit"
        if fr == "stop":
            return "eos"
    return None


# ── Sampling params ───────────────────────────────────────────────────────────

def _sampling_payload(top_p=None, top_k=None, min_p=None,
                      repeat_penalty=None, seed=None) -> dict:
    """Dict con SOLO los sampling params no-None, listo para mergear al payload.

    Nombres estandar de llama.cpp aceptados nativos por llama-server b9391 en
    /completion y /v1/chat/completions: top_p, top_k, min_p, repeat_penalty,
    seed. Si todos son None devuelve {} y el payload queda identico al actual
    (defaults del server intactos).
    """
    out = {}
    if top_p is not None:
        out["top_p"] = top_p
    if top_k is not None:
        out["top_k"] = top_k
    if min_p is not None:
        out["min_p"] = min_p
    if repeat_penalty is not None:
        out["repeat_penalty"] = repeat_penalty
    if seed is not None:
        out["seed"] = seed
    return out


# ── /props parsing ────────────────────────────────────────────────────────────

def _server_props_summary(data: dict) -> dict:
    """Parseo puro de la respuesta de GET /props de llama-server -> resumen.

    Campos observados en builds recientes (a verificar contra b9391):
    default_generation_settings.n_ctx (contexto por slot), model_path (GGUF
    cargado), build_info y total_slots a nivel raiz. Devuelve dict con claves
    fijas y None donde el campo no este, para que el caller loguee sin KeyError.
    """
    dgs = data.get("default_generation_settings") or {}
    return {
        "n_ctx":       dgs.get("n_ctx"),
        "model_path":  data.get("model_path"),
        "build_info":  data.get("build_info"),
        "total_slots": data.get("total_slots"),
    }


# ── GGUF path resolution ──────────────────────────────────────────────────────

def _find_gguf() -> Optional[Path]:
    """Return path to GGUF model file, or None if not found."""
    # Explicit env var takes priority
    env_path = os.environ.get("LLAMA_GGUF_PATH", "").strip()
    if env_path:
        p = Path(env_path)
        if not p.is_absolute():
            p = Path(__file__).parent.parent / p
        if p.is_file():
            return p
        logger.warning("[llama_backend] LLAMA_GGUF_PATH set but file not found: %s", p)

    # Search next to the existing NPZ shards
    shard_dir_raw = os.environ.get("SHARD_WEIGHTS_DIR", "model_shards/qwen-coder-3b-q4")
    shard_dir = Path(shard_dir_raw)
    if not shard_dir.is_absolute():
        shard_dir = Path(__file__).parent.parent / shard_dir

    for name in _GGUF_CANDIDATES:
        p = shard_dir / name
        if p.is_file():
            return p

    # Broader search one level up
    for p in shard_dir.parent.rglob("*.gguf"):
        return p

    # Instalación estándar (cognia install-model): ~/.cognia/models/*/*.gguf.
    # El producto INSTALADO no tiene repo alrededor: si config.env no se
    # aplicó (o el env falta), este fallback hace que "instalar el modelo y
    # usarlo" funcione sin configurar nada (cazado e2e 2026-07-15: la
    # oficina instalada corría sin backend). Se elige el GGUF más grande
    # fuera del dir del portero (= el modelo principal, no un adapter LoRA).
    home_models = Path.home() / ".cognia" / "models"
    if home_models.is_dir():
        candidatos = [p for p in home_models.rglob("*.gguf") if p.is_file()]
        principales = [p for p in candidatos
                       if "portero" not in p.parent.name.lower()] or candidatos
        if principales:
            elegido = max(principales, key=lambda p: p.stat().st_size)
            logger.info("[llama_backend] GGUF por fallback ~/.cognia/models: %s",
                        elegido)
            return elegido

    return None


# ── LoRA adapter args ─────────────────────────────────────────────────────────

def _fleet_manifest(gguf_path: Optional[Path]) -> list:
    """Manifiesto del fleet: adapters.json junto al GGUF o en ~/.cognia/loras, o [].

    Formato: {"adapters": [{"name": "accion", "file": "cognia3b_v1_f16.gguf"}]}
    "file" es relativo al dir del PROPIO adapters.json (o absoluto). Entradas con
    archivo inexistente se saltean con warning (el server arranca igual con el
    resto). El ORDEN de la lista define los ids que llama-server asigna (0..n-1).

    Clave opcional `nativo_compatible: true` (plan LoRA Qwythos 2026-08-09):
    marca un adapter entrenado para el regimen NATIVO (tool-calling chatml del
    server, no el marco ACCION). POR QUE es opt-in por manifest: el experto
    'accion' del 3B se entreno contra el marco ACCION y aplicado en nativo
    degrada — sin la clave, un manifest viejo se comporta EXACTO como hoy
    (ningun experto en nativo). Los consumidores historicos leen solo
    name/path, la clave extra es backward-compatible.

    Busqueda (primero que exista):
      1. <dir del GGUF>/adapters.json  — layout historico junto al modelo
      2. ~/.cognia/loras/adapters.json — donde viven los LoRA reales del usuario
         (el layout model_shards/qwen-coder-3b-q4/ ya no se crea; desync cazada
         2026-08-01). COGNIA_LORAS_DIR la overridea (tests/instalaciones raras).
    """
    if gguf_path is None:
        return []
    loras_dir = Path(os.environ.get("COGNIA_LORAS_DIR", "").strip()
                     or Path.home() / ".cognia" / "loras")
    candidatos = [Path(gguf_path).parent / "adapters.json",
                  loras_dir / "adapters.json"]
    manifest = next((c for c in candidatos if c.is_file()), None)
    if manifest is None:
        return []
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("[llama_backend] adapters.json ilegible (%s); fleet OFF", exc)
        return []
    out = []
    for entry in data.get("adapters", []):
        name = (entry.get("name") or "").strip()
        file_ = (entry.get("file") or "").strip()
        if not name or not file_:
            logger.warning("[llama_backend] adapters.json: entrada sin name/file: %r", entry)
            continue
        p = Path(file_).expanduser()
        if not p.is_absolute():
            p = manifest.parent / p
        if not p.is_file():
            logger.warning("[llama_backend] adapters.json: no existe %s (salteado)", p)
            continue
        out.append({"name": name, "path": p,
                    "nativo_compatible": entry.get("nativo_compatible") is True})
    return out


def experto_del_guard(regimen_nativo: bool,
                      experto_nativo: Optional[str]) -> Optional[str]:
    """Que experto debe activar el guard A3 de cli.py. Pura, sin server.

    POR QUE existe: la logica del guard vivia inline en cli.py (~9603) y era
    intesteable sin levantar el CLI entero. Extraida aca (dueno unico ola 1)
    para que cli.py (ola 2) solo la llame:
      - legacy (marco ACCION)  -> 'accion' (comportamiento historico intacto)
      - nativo                 -> SOLO el adapter marcado nativo_compatible
                                  en el manifest, o None (hoy: nada se activa)
    """
    if not regimen_nativo:
        return "accion"
    return experto_nativo or None


def _lora_args(gguf_path: Optional[Path] = None) -> tuple:
    """(args extra de LoRA para el cmd de llama-server, nombres del fleet).

    Precedencia:
    1. LLAMA_LORA_PATH seteada -> UN adapter estatico aplicado (["--lora", p], [])
       — comportamiento historico, sin fleet.
    2. adapters.json junto al GGUF -> fleet: todos los adapters cargados con
       --lora-init-without-apply (scale 0.0 = base pura) y hot-swap por request
       via POST /lora-adapters (validado 2026-07-07: swap 2-41 ms, FLEET_DESIGN).
    3. Nada -> ([], []) (cmd identico al actual).
    """
    env_path = os.environ.get("LLAMA_LORA_PATH", "").strip()
    if env_path:
        p = Path(env_path)
        if not p.is_absolute():
            p = Path(__file__).parent.parent / p
        if p.is_file():
            logger.info("[llama_backend] LoRA adapter (estatico): %s", p)
            return ["--lora", str(p)], []
        logger.warning("[llama_backend] LLAMA_LORA_PATH set but file not found: %s", p)
        return [], []
    fleet = _fleet_manifest(gguf_path)
    if not fleet:
        return [], []
    args = ["--lora-init-without-apply"]
    for a in fleet:
        args += ["--lora", str(a["path"])]
    logger.info("[llama_backend] fleet: %d adapter(s) cargados sin aplicar: %s",
                len(fleet), [a["name"] for a in fleet])
    return args, [a["name"] for a in fleet]


# ── Speculative decoding args ─────────────────────────────────────────────────

# Solo drafters de coste de banda ~0 (variantes ngram): escanean el contexto, sin
# modelo extra ni entrenamiento. Se PROHIBE 'draft-*' (draft model separado): en CPU
# bandwidth-bound compite por banda + nucleos y mide 0.37x en habla (exp021/cycle34).
_SPEC_NGRAM_ALLOWED = {"ngram-mod", "ngram-simple", "ngram-map-k", "ngram-map-k4v", "ngram-cache"}

# MTP (multi-token prediction) NATIVO: la cabeza de draft viaja DENTRO del gguf
# (<arch>.nextn_predict_layers), asi que no es un "draft-* separado" y la
# prohibicion de arriba no le aplica: no hay segundo modelo compitiendo por
# banda ni por nucleos.
#
# MEDIDO 2026-08-18 en la RTX 5060 Ti sobre Qwythos-9B (ctx 32k, KV q8_0,
# temp 0, 6 medidas por brazo en rondas de orden invertido, brazo nulo de
# referencia):
#     brazo             codigo          prosa        aceptacion
#     sin-spec          71,4            71,3            --
#     draft-mtp n=2    125,1 (1,75x)   94,2 (1,32x)   87% / 53%
#     draft-mtp n=4    118,1 (1,65x)   73,3 (1,03x)   67% / 32%
#     draft-mtp n=6     97,4 (1,36x)   55,3 (0,78x)   52% / 22%
# De ahi el n-max 2: la aceptacion cae rapido y con 6 el trabajo desperdiciado
# se come la ganancia (en prosa queda mas LENTO que sin nada).
#
# Y de ahi que el default cambie: en la MISMA corrida, ngram-mod acepto 0% en
# la primera peticion (70,6 tok/s, o sea ninguna ganancia) y solo dio 216 tok/s
# en la SEGUNDA peticion del mismo prompt, copiando su propia respuesta previa
# del cache del server. El "1.45x lossless" de exp021 es real pero es eso: solo
# aparece cuando el contexto ya contiene el texto que se va a escribir.
#
# LIMITE HONESTO: MTP no sale bit-identico. Con temp 0 el texto difirio del
# brazo nulo en UNA palabra de 31 lineas (misma longitud, misma tasa de
# repeticion) — divergencia numerica por el batching del verificador, no
# degradacion. ngram-mod si salio bit-identico. Quien necesite identidad exacta
# byte a byte tiene COGNIA_SPEC_TYPE=ngram-mod.
_SPEC_MTP = "draft-mtp"
_SPEC_MTP_N_MAX = "2"


def _tiene_cabeza_mtp(gguf_path) -> bool:
    """True si el gguf DECLARA cabeza MTP. Se lee del fichero a proposito.

    Decidirlo por el nombre del modelo seria la bomba de siempre, y aca el
    fallo es SILENCIOSO: llama-server acepta --spec-type draft-mtp sobre un
    modelo sin cabeza, sirve igual, no acelera y no dice nada."""
    if gguf_path is None:
        return False
    try:
        from cognia.agent.gguf_meta import meta
        return int((meta(str(gguf_path)) or {}).get("mtp_capas") or 0) >= 1
    except Exception:
        return False


def _spec_args(gguf_path=None) -> list:
    """Args de speculative decoding para el cmd de llama-server, o [].

    Default: 'draft-mtp' con n-max 2 si el gguf trae cabeza MTP (1,75x en
    codigo medido); 'ngram-mod' si no la trae (el default historico).
    COGNIA_SPEC_TYPE pisa: 'none' apaga, las variantes ngram valen siempre, y
    'draft-mtp' solo si el fichero declara la cabeza. Los 'draft-*' con modelo
    aparte siguen prohibidos (en CPU bandwidth-bound miden 0.37x, exp021).
    """
    spec = os.environ.get("COGNIA_SPEC_TYPE", "").strip()
    cabeza = _tiene_cabeza_mtp(gguf_path)
    mtp = ["--spec-type", _SPEC_MTP, "--spec-draft-n-max", _SPEC_MTP_N_MAX]
    if not spec:
        return mtp if cabeza else ["--spec-type", "ngram-mod"]
    if spec in _SPEC_NGRAM_ALLOWED:
        return ["--spec-type", spec]
    if spec == _SPEC_MTP:
        if cabeza:
            return mtp
        logger.warning("[llama_backend] COGNIA_SPEC_TYPE=draft-mtp pero %s no "
                       "declara cabeza MTP (nextn_predict_layers): el server lo "
                       "aceptaria y lo ignoraria en silencio. Uso ngram-mod.",
                       getattr(gguf_path, "name", gguf_path))
        return ["--spec-type", "ngram-mod"]
    if spec != "none":
        logger.warning("[llama_backend] COGNIA_SPEC_TYPE=%r ignorado (variantes "
                       "ngram, draft-mtp con cabeza en el gguf, o none); "
                       "speculative OFF", spec)
    return []


# ── Backend 1: llama-cpp-python (in-process) ─────────────────────────────────

class _LlamaCppBackend:
    """Thin wrapper around the llama-cpp-python package."""

    def __init__(self, gguf_path: Path) -> None:
        from llama_cpp import Llama  # imported lazily; raises ImportError if missing
        self._gguf_path = gguf_path   # expuesto via LlamaBackend.gguf_path (/modelo)
        self._model = Llama(
            model_path     = str(gguf_path),
            n_ctx          = _ctx_size(),
            n_gpu_layers   = _n_gpu_layers(),
            verbose        = False,
        )
        # Mirror _LlamaServerBackend: token count real + stop reason del ultimo
        # generate(), para que la auto-continuacion (generate_long) funcione tambien
        # in-process. Sin esto last_stop_reason era siempre None y el loop cortaba
        # tras la ronda 1 (None != 'limit').
        self.last_tokens_predicted: Optional[int] = None
        self.last_stop_reason: Optional[str] = None
        logger.info("[llama_backend] llama-cpp-python loaded: %s", gguf_path.name)

    def generate(self, prompt: str, max_tokens: int = 256,
                 temperature: float = 0.7, top_p=None, top_k=None,
                 min_p=None, repeat_penalty=None, seed=None,
                 cache_prompt: bool = True, grammar: str = None,
                 stop=None) -> Optional[str]:
        # cache_prompt se ignora: backend in-process, no hay KV-cache de server.
        # grammar se ignora: el binding exige un objeto LlamaGrammar, no el
        # string GBNF crudo que acepta llama-server (fuera de alcance aca).
        # llama-cpp-python soporta los 5 sampling kwargs nativos (min_p desde
        # 0.2.20). Un binding mas viejo levanta TypeError -> lo atrapa el
        # except de abajo (mismo contrato: None en fallo).
        extra = _sampling_payload(top_p=top_p, top_k=top_k, min_p=min_p,
                                  repeat_penalty=repeat_penalty, seed=seed)
        try:
            result = self._model(
                prompt,
                max_tokens  = max_tokens,
                temperature = temperature,
                echo        = False,
                # Mismos stop strings que el server backend: corta en fin de turno
                # ChatML; MERGE con los stops extra del caller (nunca reemplaza).
                stop        = ["<|im_end|>", "<|endoftext|>"] + list(stop or []),
                **extra,
            )
            # Mismo contrato que el server backend: token count real + stop reason.
            # llama-cpp-python devuelve formato OpenAI (choices[0].finish_reason
            # 'length'|'stop' + usage.completion_tokens); _stop_reason ya lo mapea a
            # 'limit'|'eos', habilitando la continuacion de generate_long.
            self.last_tokens_predicted = (result.get("usage") or {}).get("completion_tokens")
            self.last_stop_reason = _stop_reason(result)
            return result["choices"][0]["text"]
        except Exception as exc:
            logger.warning("[llama_backend] llama-cpp-python generate failed: %s", exc)
            return None

    @staticmethod
    def available() -> bool:
        try:
            import llama_cpp  # noqa: F401
            return True
        except ImportError:
            return False


# ── Backend 2: llama-server subprocess (REST API) ────────────────────────────

class _LlamaServerBackend:
    """Manages a llama-server subprocess and calls it via its OpenAI-compatible API."""

    def __init__(self, gguf_path: Path, port: int = _DEFAULT_PORT,
                 lora_path: Optional[Path] = None,
                 ctx_size: Optional[int] = None) -> None:
        import urllib.request, json as _json

        self._port    = port
        self._base    = f"http://127.0.0.1:{port}"
        self._proc: Optional[subprocess.Popen] = None
        self._gguf_path = gguf_path   # expuesto via LlamaBackend.gguf_path (/modelo)
        # LoRA ESTATICA aplicada por parametro (portero 0.5B, PREREG_PORTERO_FASE2):
        # a diferencia de LLAMA_LORA_PATH (env global, envenenaria TODOS los
        # servers del proceso) esto es por-instancia. Excluye el fleet hot-swap.
        self._lora_path = Path(lora_path) if lora_path else None
        # ctx por instancia: el portero usa 4096 (turnos triviales; KV chico)
        # sin tocar el 32k del server principal.
        # None = resolver en call-time via _ctx_size() (env-overridable,
        # perf_profiles cambia el knob en runtime); el parametro manda.
        self._ctx_size = int(ctx_size) if ctx_size else None
        self._json    = _json
        self._urlreq  = urllib.request
        # Real token count from the last /completion response (None until first call)
        self.last_tokens_predicted: Optional[int] = None
        # Why the last generation stopped: 'eos'|'limit'|'word'|None (see _stop_reason)
        self.last_stop_reason: Optional[str] = None
        # HARNESS #1: telemetria de KV-cache (timings del ultimo /completion).
        self.last_timings: dict = {}
        self.last_prompt_n: Optional[int] = None
        self.last_prompt_ms: Optional[float] = None
        # Fleet de expertos LoRA (FLEET_DESIGN): nombres en orden de carga
        # (id de llama-server = indice), experto activo, y flag de swap
        # pendiente — tras un POST /lora-adapters el KV cache es invalido y la
        # PRIMERA request debe ir con cache_prompt=false (regla medida).
        self._fleet_names: list = []
        self._active_expert: Optional[str] = None
        self._lora_dirty: bool = False

        # Check if a server is already running on the port.
        # 'cargando' = hay server pero /health da 503 (todavia cargando el
        # modelo, p.ej. servir_flota recien lanzado con el 14B). Antes _ping()
        # lo trataba igual que "ausente" y se intentaba arrancar OTRO server
        # sobre el mismo puerto; y la primera request contra un server en
        # carga moria con reset (WinError 10054) que aguas arriba se leia
        # como fallo permanente (A1 2026-08-01). Ahora se ESPERA la carga.
        estado = self._health_state()
        if estado == "cargando":
            logger.info("[llama_backend] server en :%d cargando modelo; "
                        "espero /health ok hasta %ds", port, _SERVER_TIMEOUT)
            if self._wait_health_ok(_SERVER_TIMEOUT):
                estado = "ok"
        if estado == "ok":
            logger.info("[llama_backend] llama-server already running on :%d", port)
            # Server adoptado sin verificar flags: loguear su config real via
            # /props y avisar si el contexto no coincide con el esperado.
            self._check_adopted_server()
            if self._lora_path is not None:
                # Con LoRA estatica pedida NO se adopta un server que no la
                # tenga aplicada: serviria la base pelada como si fuera el
                # experto (identidad silenciosamente rota). Raise -> el caller
                # (speech_cascade) cae al 3B, que es el fallback seguro.
                self._check_adopted_static_lora()
            else:
                self._adopt_fleet()
            return

        env_server = os.environ.get("LLAMA_SERVER_PATH", "").strip()
        binary = (
            (env_server if env_server and Path(env_server).is_file() else None)
            or shutil.which("llama-server")
            or shutil.which("llama_server")
        )
        if not binary:
            for candidate in _SERVER_BINARIES:
                if Path(candidate).is_file():
                    binary = candidate
                    break
        if not binary:
            raise FileNotFoundError("llama-server binary not found; set LLAMA_SERVER_PATH in .env")

        # Medido en i3-10110U (b9391, Q4_K_M): el 4o hilo logico compite con
        # el SO y empeora decode Y prefill -> cpu-1 para ambos. Override:
        # LLAMA_N_THREADS (main lo lee en call-time para perf_profiles).
        # 2026-07-23: cpu-1 escala mal hacia arriba. En la 6c/12t daba 11 hilos,
        # y llama-bench mide 12 hilos -> 39.81 tok/s vs 6 (fisicos) -> 45.65
        # (+14.7%). hilos_cpu_optimos() toma cpu-1 como TECHO, asi que en el i3
        # sigue dando 3 (la medicion de arriba intacta) y solo baja en maquinas
        # con mas de 4 nucleos fisicos.
        from .cpu_threads import hilos_cpu_optimos
        n_threads_decode = _env_int(
            "LLAMA_N_THREADS", hilos_cpu_optimos(max(1, (os.cpu_count() or 4) - 1)))
        n_threads_batch  = n_threads_decode
        cmd = [
            binary,
            "--model",    str(gguf_path),
            # --host 127.0.0.1: bind SOLO a localhost, explicito (no depender del
            # default del binario). Los servers de inferencia (fleet 8088, portero
            # 8090, heavy 8092) son INTERNOS — el cliente conecta a 127.0.0.1 (self.
            # _base). Sin esto, un binario que default-ee a 0.0.0.0 expondria el
            # modelo local a la LAN, en contra del core "IA local, privada".
            "--host",     "127.0.0.1",
            "--port",     str(port),
            "--ctx-size", str(self._ctx_size if self._ctx_size is not None else _ctx_size()),
            # --parallel 1 EXPLICITO: las builds recientes de llama-server usan
            # 4 slots por defecto y PARTEN --ctx-size entre ellos. scripts/
            # servir_modelo.py ya lo arreglo el 2026-07-28, pero ESTE lanzador
            # —el que usa Cognia cuando arranca el backend sola— se quedo sin
            # el fix: el server servido desde aqui reportaba total_slots=4, asi
            # que --ctx-size 4096 daba 1024 tokens REALES por peticion y todo
            # prompt normal moria con HTTP 400 exceed_context_size. Medido
            # 2026-08-02: /props total_slots=4 con este cmd, =1 al agregar esto.
            "--parallel", "1",
            "--n-gpu-layers", str(_n_gpu_layers()),
            "--threads",  str(n_threads_decode),
            "--threads-batch", str(n_threads_batch),
            "--cache-reuse", "256",
            # b9391 defaultea --cache-ram 8192 MiB por server: con 3-4
            # servers coexistiendo en 12GB es swap/OOM latente. Acotado.
            "--cache-ram", os.environ.get("LLAMA_CACHE_RAM_MIB", "1024"),
            "--prio",     "2",
            "--flash-attn", "on",
            "--log-disable",
        ]
        # Especulacion, fusion del merge 4.0: si hay draft GGUF configurado
        # (modo 'dspark' de velocity.py — medido 2026-07-18: codigo 142.9
        # tok/s, 1.63x), draft clasico; si no, _spec_args() pone ngram-mod
        # (exp021: bit-identico, gratis, gana en repetitivo/codigo/RAG).
        # OJO b10066: sin --spec-type, --model-draft es un no-op SILENCIOSO.
        draft = _draft_gguf()
        if draft is not None:
            cmd += [
                "--model-draft",      str(draft),
                "--spec-type",        "draft-simple",
                "--gpu-layers-draft", str(_n_gpu_layers()),
                "--spec-draft-n-max", "8",
                "--spec-draft-n-min", "1",
                "--spec-draft-p-min", "0.75",
            ]
        else:
            cmd += _spec_args(gguf_path)
        if self._lora_path is not None:
            # LoRA estatica por parametro (portero): aplicada al arrancar.
            cmd += ["--lora", str(self._lora_path)]
            self._fleet_names = []
        else:
            # LoRA: estatico (LLAMA_LORA_PATH) o fleet (adapters.json junto al GGUF)
            lora_cmd, self._fleet_names = _lora_args(gguf_path)
            cmd += lora_cmd
        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Wait for server to be ready
        deadline = time.time() + _SERVER_TIMEOUT
        while time.time() < deadline:
            if self._ping():
                logger.info("[llama_backend] llama-server started on :%d (pid=%d)",
                            port, self._proc.pid)
                self._force_base_scales()
                return
            time.sleep(0.5)
        self._proc.kill()
        raise RuntimeError(f"llama-server did not start within {_SERVER_TIMEOUT}s")

    def _ping(self) -> bool:
        try:
            self._urlreq.urlopen(f"{self._base}/health", timeout=1)
            return True
        except Exception:
            return False

    def _health_state(self) -> str:
        """'ok' | 'cargando' | 'ausente' segun /health.

        b9391 responde 503 mientras carga el modelo -> 'cargando' (HAY server,
        todavia no acepta requests; hay que esperarlo, no relanzarlo ni darlo
        por muerto). Conexion rechazada/reset/timeout -> 'ausente'. Cualquier
        otro HTTP -> 'ok' (el server esta ahi y responde).

        Pregunta primero a _ping(): ademas de ahorrar el segundo request en el
        caso sano, mantiene el contrato historico de los tests/callers que
        stubean _ping para simular un server vivo."""
        if self._ping():
            return "ok"
        import urllib.error
        try:
            self._urlreq.urlopen(f"{self._base}/health", timeout=2)
            return "ok"
        except urllib.error.HTTPError as exc:
            return "cargando" if exc.code == 503 else "ok"
        except Exception:
            return "ausente"

    def _wait_health_ok(self, max_wait_s: float) -> bool:
        """Poll a /health hasta 200 (True) o agotar max_wait_s (False).

        Corta apenas responde. 'ausente' NO corta antes de tiempo: un server
        reiniciandose externamente tarda unos segundos en volver a abrir el
        puerto y volveria como 'cargando' -> 'ok'."""
        deadline = time.time() + max_wait_s
        while time.time() < deadline:
            if self._health_state() == "ok":
                return True
            time.sleep(1.0)
        return False

    def props(self) -> Optional[dict]:
        """GET /props del server (JSON crudo), o None si falla."""
        try:
            with self._urlreq.urlopen(f"{self._base}/props", timeout=5) as resp:
                return self._json.loads(resp.read())
        except Exception as exc:
            logger.debug("[llama_backend] GET /props failed: %s", exc)
            return None

    def tokenize_len(self, texto: str) -> Optional[int]:
        """Tokens REALES de `texto` segun POST /tokenize del server, o None si falla.

        Se usa para presupuestar prompts contra el n_ctx del server (la cabeza de
        generate_delegated) sin inventar la cifra: el estimador de chars/token
        varia con el idioma (4,21 medidos en castellano el 2026-08-17) y el que
        decide es el tokenizer del modelo cargado, no una constante."""
        if not texto:
            return 0
        try:
            req = self._urlreq.Request(
                f"{self._base}/tokenize",
                data=self._json.dumps({"content": texto}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with self._urlreq.urlopen(req, timeout=60) as resp:
                return len(self._json.loads(resp.read()).get("tokens", []))
        except Exception as exc:
            logger.debug("[llama_backend] POST /tokenize failed: %s", exc)
            return None

    def _check_adopted_server(self) -> None:
        """Loguea la config real de un server preexistente; warn si n_ctx difiere.

        No falla duro: un server ajeno con otro contexto sigue siendo usable,
        pero el mismatch explica diferencias de calidad/velocidad en benchmarks.
        """
        data = self.props()
        if not data:
            logger.warning("[llama_backend] adopted server: /props unavailable, "
                           "cannot verify n_ctx/model")
            return
        summary = _server_props_summary(data)
        logger.info("[llama_backend] adopted server: n_ctx=%s model=%s",
                    summary["n_ctx"], summary["model_path"])
        # self._ctx_size puede ser None (= resolver en call-time via _ctx_size());
        # comparar y loguear con el valor RESUELTO — con None, el %d del warning
        # reventaba el propio logging (TypeError en emit, medido 2026-07-20).
        ctx_esperado = self._ctx_size if self._ctx_size is not None else _ctx_size()
        if summary["n_ctx"] is not None and summary["n_ctx"] != ctx_esperado:
            # info y no warning: desde la obra 2026-08-09 el camino del agente
            # presupuesta contra el n_ctx REAL del server (via /props), asi que
            # adoptar un server con otro ctx es una condicion manejada, no una
            # averia que gritar en consola en cada arranque.
            logger.info("[llama_backend] adopted server n_ctx=%s != expected "
                        "ctx_size=%d — results may differ from a self-started "
                        "server", summary["n_ctx"], ctx_esperado)

    def _check_adopted_static_lora(self) -> None:
        """Server adoptado cuando se pidio LoRA estatica: exigir que ESE server
        tenga la LoRA cargada con scale > 0. Si no se puede confirmar via
        GET /lora-adapters -> RuntimeError (el caller hace fallback; nunca
        servir la base pelada haciendose pasar por el experto)."""
        quiero = self._lora_path.name
        vivos = self.lora_adapters()
        ok = any(Path(a.get("path", "")).name == quiero
                 and float(a.get("scale", 0.0) or 0.0) > 0.0
                 for a in (vivos or []))
        if not ok:
            raise RuntimeError(
                f"server adoptado en :{self._port} sin la LoRA {quiero} aplicada "
                f"(adapters vivos: {[Path(a.get('path', '')).name for a in (vivos or [])]})")

    # ── Fleet de expertos LoRA (hot-swap POST /lora-adapters) ────────────────

    def _adopt_fleet(self) -> None:
        """Server adoptado: reconstruye el fleet matcheando el manifiesto local
        contra GET /lora-adapters por basename. Mismatch -> fleet OFF (warning);
        nunca asumir que un server ajeno cargo los adapters esperados."""
        if os.environ.get("LLAMA_LORA_PATH", "").strip():
            return  # modo estatico historico: sin fleet
        manifest = _fleet_manifest(self._gguf_path)
        if not manifest:
            return
        vivos = self.lora_adapters()
        if vivos is None:
            logger.warning("[llama_backend] server adoptado sin /lora-adapters; fleet OFF")
            return
        vivos_por_base = {Path(a.get("path", "")).name: a.get("id") for a in vivos}
        nombres = []
        for a in manifest:
            aid = vivos_por_base.get(a["path"].name)
            if aid is None or aid != len(nombres):
                logger.warning("[llama_backend] server adoptado no cargo el fleet del "
                               "manifiesto (falta %s o ids corridos); fleet OFF — "
                               "matar llama-server.exe y relanzar", a["path"].name)
                return
            nombres.append(a["name"])
        self._fleet_names = nombres
        logger.info("[llama_backend] fleet adoptado: %s", nombres)
        self._force_base_scales()

    def _force_base_scales(self) -> None:
        """Arranque del fleet: fuerza TODOS los scales a 0.0 (base pura).

        Medido 2026-07-08: aun con --lora-init-without-apply el b9391 reporta
        el adapter con scale 1.0 al arrancar — el estado inicial NO es base.
        Se postea explicito en vez de confiar en el flag."""
        if not self._fleet_names:
            return
        self._active_expert = "__arranque__"   # sentinela: fuerza el POST real
        if not self.activate_expert(None):
            logger.warning("[llama_backend] no se pudo forzar base al arrancar; "
                           "fleet OFF por seguridad")
            self._fleet_names = []
            self._active_expert = None

    def lora_adapters(self) -> Optional[list]:
        """GET /lora-adapters del server (lista cruda), o None si falla."""
        try:
            with self._urlreq.urlopen(f"{self._base}/lora-adapters", timeout=5) as resp:
                return self._json.loads(resp.read())
        except Exception as exc:
            logger.debug("[llama_backend] GET /lora-adapters failed: %s", exc)
            return None

    def activate_expert(self, name: Optional[str]) -> bool:
        """Activa el experto `name` (scale 1.0, resto 0.0) o None = base pura.

        Idempotente y barato: si ya esta activo no hace nada. Tras un swap real
        marca _lora_dirty para que la proxima request fuerce cache_prompt=false
        (el KV cache calculado con otros pesos efectivos es invalido y
        llama.cpp NO lo invalida solo — medido 2026-07-07, FLEET_DESIGN).
        Devuelve True si el experto pedido quedo activo (o ya lo estaba).
        """
        if not self._fleet_names:
            return name is None  # sin fleet, la base "esta activa" por definicion
        if name is not None and name not in self._fleet_names:
            logger.warning("[llama_backend] experto desconocido: %r (fleet: %s)",
                           name, self._fleet_names)
            return False
        if name == self._active_expert:
            return True
        scales = [{"id": i, "scale": 1.0 if n == name else 0.0}
                  for i, n in enumerate(self._fleet_names)]
        try:
            req = self._urlreq.Request(
                f"{self._base}/lora-adapters",
                data=self._json.dumps(scales).encode(),
                headers={"Content-Type": "application/json"},
            )
            self._urlreq.urlopen(req, timeout=10).read()
        except Exception as exc:
            logger.warning("[llama_backend] POST /lora-adapters failed: %s", exc)
            return False
        self._active_expert = name
        self._lora_dirty = True
        logger.info("[llama_backend] experto activo: %s", name or "(base)")
        return True

    def _consume_lora_dirty(self, cache_prompt: bool) -> bool:
        """cache_prompt efectivo: False forzado en la 1ra request post-swap.

        getattr defensivo: instancias parciales (tests de payload) o picklings
        viejos pueden no tener el atributo — sin fleet no hay swap que invalide.
        """
        if getattr(self, "_lora_dirty", False):
            self._lora_dirty = False
            return False
        return cache_prompt

    def experto_nativo(self) -> Optional[str]:
        """Primer adapter del manifest con nativo_compatible: true, o None.

        POR QUE: el guard A3 de cli.py necesita saber si hay un experto
        entrenado para el regimen nativo SIN adivinar por nombre. Re-lee
        adapters.json del disco (barato y local; no toca el server) y solo
        devuelve un experto que el fleet cargado realmente tiene — un adapter
        marcado pero no cargado (server adoptado con fleet OFF) devolveria un
        nombre que activate_expert rechazaria, asi que se filtra aca con
        warning visible en vez de fallar aguas abajo en silencio.
        """
        if not getattr(self, "_fleet_names", None):
            return None
        for a in _fleet_manifest(self._gguf_path):
            if not a.get("nativo_compatible"):
                continue
            if a["name"] in self._fleet_names:
                return a["name"]
            logger.warning("[llama_backend] adapter nativo_compatible %r no "
                           "esta en el fleet cargado %s (ignorado)",
                           a["name"], self._fleet_names)
        return None

    def generate(self, prompt: str, max_tokens: int = 256,
                 temperature: float = 0.7, top_p=None, top_k=None,
                 min_p=None, repeat_penalty=None, seed=None,
                 cache_prompt: bool = True, grammar: str = None,
                 stop=None) -> Optional[str]:
        import urllib.error
        cache_prompt = self._consume_lora_dirty(cache_prompt)
        payload = self._json.dumps({
            "prompt":      prompt,
            "n_predict":   max_tokens,
            "temperature": temperature,
            # MERGE (no reemplazo): siempre corta en fin-de-turno, y ademas en los
            # stops extra que pase el caller (p.ej. '\nACCION:' del agente).
            "stop":        ["<|im_end|>", "<|endoftext|>"] + list(stop or []),
            # cache_prompt True (default): no re-prefilla el historial entero.
            # False: prefill completo — el KV-cache reusado cambia los logits
            # (experimento 2026-06-11), necesario para benchmarks deterministas.
            "cache_prompt": cache_prompt,
            # grammar: string GBNF que el server compila y usa para restringir
            # el sampling (campo nativo de /completion en b9391). Solo si se
            # pasa: sin grammar el payload queda identico al actual.
            **({"grammar": grammar} if grammar is not None else {}),
            # Sampling params: solo los no-None (defaults del server intactos)
            **_sampling_payload(top_p=top_p, top_k=top_k, min_p=min_p,
                                repeat_penalty=repeat_penalty, seed=seed),
        }).encode()
        # Proportional timeout: at the measured ~5.5 tok/s a fixed 120s killed any
        # generation past ~660 tokens (returned None silently). 0.6 s/token covers
        # the ~2 tok/s worst case with margin.
        timeout_s = _request_timeout_s(max_tokens, len(payload))
        # Reintento acotado (A1 2026-08-01): un UNICO 10054 transitorio (reset
        # durante la carga fria del 14B, blip del server) devolvia None y el
        # orchestrator lo leia como fallo permanente (deshabilitaba llama.cpp
        # para toda la sesion). 2 reintentos con re-sondeo de /health entre
        # medio distinguen "cargando/blip" (recuperable) de "ausente".
        for intento in range(3):
            try:
                req = self._urlreq.Request(
                    f"{self._base}/completion",
                    data    = payload,
                    headers = {"Content-Type": "application/json"},
                )
                with self._urlreq.urlopen(req, timeout=timeout_s) as resp:
                    data = self._json.loads(resp.read())
                    # Real token count reported by llama-server (replaces len//4 estimates)
                    self.last_tokens_predicted = data.get("tokens_predicted")
                    self.last_stop_reason = _stop_reason(data)
                    # HARNESS #1 (telemetria de KV-cache): timings del server.
                    # prompt_n = tokens REALMENTE prefilleados este request; con el
                    # cache sano, en un paso >1 del loop es chico (solo los tokens
                    # nuevos). prompt_ms = costo del prefill (el recurso escaso en
                    # CPU). last_prompt_n permite medir cache hit y el efecto ACI.
                    tim = data.get("timings") or {}
                    self.last_timings = tim
                    self.last_prompt_n = tim.get("prompt_n")
                    self.last_prompt_ms = tim.get("prompt_ms")
                    return data.get("content", "")
            except Exception as exc:
                es_http = isinstance(exc, urllib.error.HTTPError)
                if es_http and exc.code != 503:
                    # El server RESPONDIO con error (p.ej. 500 por ctx desbordado):
                    # no es transporte — reintentar repetiria el mismo error.
                    logger.warning("[llama_backend] llama-server request failed: %s", exc)
                    return None
                estado = self._health_state()
                if estado == "ok" and _es_timeout(exc):
                    # Timeout con el server SANO = ocupado (--parallel 1 y otro
                    # cliente en el slot), no "no hay backend". El timeout ya es
                    # proporcional y holgado: reintentar solo duplica la espera.
                    logger.warning("[llama_backend] llama-server OCUPADO en :%d "
                                   "(timeout de %ds con /health ok): %s",
                                   self._port, timeout_s, exc)
                    return None
                if intento == 2:
                    logger.warning("[llama_backend] llama-server request failed "
                                   "(3 intentos, /health=%s): %s", estado, exc)
                    return None
                if estado == "cargando" or es_http:
                    # Server vivo pero cargando el modelo (la 1ra request contra
                    # el 14B frio caia aca con reset): esperar la carga entera
                    # antes de reintentar, no un backoff a ciegas.
                    logger.warning("[llama_backend] server cargando en :%d; espero "
                                   "/health ok antes de reintentar (%s)",
                                   self._port, exc)
                    self._wait_health_ok(_SERVER_TIMEOUT)
                else:
                    logger.warning("[llama_backend] request fallo (%s); reintento "
                                   "%d/2", exc, intento + 1)
                    time.sleep(1.0 * (intento + 1))
        return None

    def stream_generate(self, prompt: str, max_tokens: int = 256,
                        temperature: float = 0.7, top_p=None, top_k=None,
                        min_p=None, repeat_penalty=None, seed=None,
                        cache_prompt: bool = True, grammar: str = None):
        """Yield tokens one at a time using llama-server SSE /completion?stream=true."""
        import urllib.error
        cache_prompt = self._consume_lora_dirty(cache_prompt)
        payload = self._json.dumps({
            "prompt":      prompt,
            "n_predict":   max_tokens,
            "temperature": temperature,
            "stop":        ["<|im_end|>", "<|endoftext|>"],
            "stream":      True,
            # cache_prompt True (default): no re-prefilla el historial entero.
            # False: prefill completo (logits deterministas, ver generate()).
            "cache_prompt": cache_prompt,
            # grammar: string GBNF, solo si se pasa (ver generate())
            **({"grammar": grammar} if grammar is not None else {}),
            # Sampling params: solo los no-None (defaults del server intactos)
            **_sampling_payload(top_p=top_p, top_k=top_k, min_p=min_p,
                                repeat_penalty=repeat_penalty, seed=seed),
        }).encode()
        # Proportional timeout: at the measured ~5.5 tok/s a fixed 120s killed any
        # generation past ~660 tokens. 0.6 s/token covers the ~2 tok/s worst case.
        timeout_s = _request_timeout_s(max_tokens, len(payload))
        self.last_stop_reason = None
        try:
            req = self._urlreq.Request(
                f"{self._base}/completion",
                data    = payload,
                headers = {"Content-Type": "application/json"},
            )
            with self._urlreq.urlopen(req, timeout=timeout_s) as resp:
                buf = b""
                while True:
                    chunk = resp.read(64)
                    if not chunk:
                        break
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        line = line.strip()
                        if line.startswith(b"data:"):
                            try:
                                data = self._json.loads(line[5:].strip())
                                tok = data.get("content", "")
                                if tok:
                                    yield tok
                                if data.get("stop"):
                                    # Final SSE chunk carries the same fields as
                                    # the non-streaming response (verified on b9391)
                                    self.last_tokens_predicted = data.get("tokens_predicted")
                                    self.last_stop_reason = _stop_reason(data)
                                    return
                            except Exception:
                                pass
        except Exception as exc:
            logger.warning("[llama_backend] llama-server stream failed: %s", exc)

    def stream_chat(self, messages: list, max_tokens: int = 512,
                    temperature: float = 0.7, top_p=None, top_k=None,
                    min_p=None, repeat_penalty=None, seed=None,
                    cache_prompt: bool = True, on_reasoning=None):
        """Yield tokens using /v1/chat/completions (multi-turn, OpenAI-compatible).

        Razonadores (gpt-oss/Harmony via --jinja): el server manda el
        pensamiento como delta.reasoning_content ANTES del content. Hasta
        2026-08-09 se DESCARTABA: minutos de aire muerto en pantalla sin un
        solo token (B3 del plan de obra). Ahora:
          - se acumula en self.last_reasoning (inspeccionable post-stream),
          - on_reasoning(fragmento) lo recibe en vivo si se pasa (callback
            best-effort: sus excepciones se tragan, el stream manda),
          - se emite RazonamientoTick al bus de ux/events (y TokenTexto por
            cada trozo de respuesta) para el indicador 'pensando... (Ns)'.
        Los consumidores existentes no cambian: el yield sigue siendo SOLO
        el content, str por str."""
        import urllib.error
        cache_prompt = self._consume_lora_dirty(cache_prompt)
        self.last_reasoning = ""
        _ev = _eventos_ux()
        payload = self._json.dumps({
            "messages":    messages,
            "max_tokens":  max_tokens,
            "temperature": temperature,
            "stream":      True,
            "stop":        ["<|im_end|>", "<|endoftext|>"],
            # cache_prompt True (default): no re-prefilla el historial entero.
            # False: prefill completo (logits deterministas, ver generate()).
            "cache_prompt": cache_prompt,
            # Sampling params: solo los no-None. llama-server acepta los nombres
            # nativos (top_k/min_p/repeat_penalty/seed) tambien en el endpoint
            # OpenAI-compatible (extension propia de llama.cpp).
            **_sampling_payload(top_p=top_p, top_k=top_k, min_p=min_p,
                                repeat_penalty=repeat_penalty, seed=seed),
        }).encode()
        # Proportional timeout: at the measured ~5.5 tok/s a fixed 120s killed any
        # generation past ~660 tokens. 0.6 s/token covers the ~2 tok/s worst case.
        timeout_s = _request_timeout_s(max_tokens, len(payload))
        self.last_stop_reason = None
        try:
            req = self._urlreq.Request(
                f"{self._base}/v1/chat/completions",
                data    = payload,
                headers = {"Content-Type": "application/json"},
            )
            with self._urlreq.urlopen(req, timeout=timeout_s) as resp:
                buf = b""
                while True:
                    chunk = resp.read(64)
                    if not chunk:
                        break
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        line = line.strip()
                        if line.startswith(b"data:"):
                            raw = line[5:].strip()
                            if raw == b"[DONE]":
                                return
                            try:
                                data = self._json.loads(raw)
                                choice = (data.get("choices") or [{}])[0]
                                delta = choice.get("delta", {})
                                # Pensamiento del razonador (verificado en vivo
                                # 2026-08-09 contra b10066 + gpt-oss-20b: llega
                                # como delta.reasoning_content; 'reasoning' es
                                # el nombre en otros builds).
                                frag = (delta.get("reasoning_content")
                                        or delta.get("reasoning") or "")
                                if frag:
                                    self.last_reasoning += frag
                                    if on_reasoning is not None:
                                        try:
                                            on_reasoning(frag)
                                        except Exception:
                                            pass
                                    if _ev is not None:
                                        _ev.emitir(_ev.RazonamientoTick(
                                            chars=len(self.last_reasoning),
                                            fragmento=frag))
                                tok = delta.get("content", "")
                                if tok:
                                    if _ev is not None:
                                        _ev.emitir(_ev.TokenTexto(texto=tok))
                                    yield tok
                                # Last chunk before [DONE] carries finish_reason
                                # and timings.predicted_n (verified on b9391)
                                if choice.get("finish_reason"):
                                    self.last_stop_reason = _stop_reason(data)
                                    predicted = data.get("timings", {}).get("predicted_n")
                                    if predicted is not None:
                                        self.last_tokens_predicted = predicted
                            except Exception:
                                pass
        except Exception as exc:
            logger.warning("[llama_backend] stream_chat failed: %s", exc)

    def stop(self) -> bool:
        """Para el llama-server propio. Devuelve True si el puerto quedo libre.

        Un server ADOPTADO (arrancado externamente, self._proc is None) no es
        nuestro proceso y no se puede matar limpio desde aca: si sigue
        respondiendo al health-check se devuelve False para que el caller
        (p.ej. /modelo) avise al usuario en vez de adoptar el modelo viejo.
        """
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                try:
                    self._proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
            logger.info("[llama_backend] llama-server stopped")
        alive = self._ping()
        if alive and self._proc is None:
            logger.warning("[llama_backend] server adoptado sigue vivo en :%d "
                           "(proceso externo; no se puede parar desde aca)",
                           self._port)
        return not alive

    @staticmethod
    def available() -> bool:
        env_path = os.environ.get("LLAMA_SERVER_PATH", "").strip()
        return bool(
            (env_path and Path(env_path).is_file())
            or shutil.which("llama-server")
            or shutil.which("llama_server")
            or any(Path(c).is_file() for c in _SERVER_BINARIES)
        )


# ── Public facade ─────────────────────────────────────────────────────────────

class LlamaBackend:
    """
    Unified llama.cpp backend. Tries llama-cpp-python first, then llama-server.
    Returns None from generate() if neither is available.

    Usage:
        backend = LlamaBackend.try_load()   # None if nothing available
        if backend:
            text = backend.generate(prompt)
    """

    def __init__(self, impl) -> None:
        self._impl = impl

    def _auditar(self, via: str) -> None:
        """
        Deja constancia de que ESTE backend atendio una peticion: modelo + puerto.

        Anadido 2026-07-25. Sin esto no habia forma de saber, mirando una corrida,
        si el producto lo hizo la flota de :8080 o el qwen2.5-7b RETIRADO que este
        mismo modulo levantaba en :8088. No lanza nunca: es instrumentacion.
        """
        try:
            from cognia import backend_activo
            base = getattr(self._impl, "_base", None)
            if base:
                backend_activo.registrar(via, base, rol="backend-inyectado")
            else:   # in-process (llama-cpp-python): no hay puerto que auditar
                backend_activo.registrar(via, "in-process",
                                         rol="llama-cpp-python",
                                         gguf=str(self.gguf_path))
        except Exception:
            pass

    @property
    def last_tokens_predicted(self) -> Optional[int]:
        """Real token count from the last generate() call, or None if unknown."""
        return getattr(self._impl, "last_tokens_predicted", None)

    @property
    def last_stop_reason(self) -> Optional[str]:
        """Why the last generation stopped: 'eos'|'limit'|'word'|None (see _stop_reason)."""
        return getattr(self._impl, "last_stop_reason", None)

    @property
    def last_reasoning(self) -> str:
        """reasoning_content acumulado del ultimo stream_chat ('' si no hubo)."""
        return getattr(self._impl, "last_reasoning", "") or ""

    @property
    def gguf_path(self) -> Optional[Path]:
        """Ruta del GGUF con el que se construyo el impl, o None si no la expone."""
        return getattr(self._impl, "_gguf_path", None)

    def server_props(self) -> Optional[dict]:
        """JSON crudo de GET /props del impl server, o None (in-process no tiene)."""
        fn = getattr(self._impl, "props", None)
        return fn() if callable(fn) else None

    def n_ctx_efectivo(self) -> int:
        """La ventana REAL contra la que hay que presupuestar el prefill.

        SE MIDE, NO SE DECLARA. Primero /props del server que atiende de
        verdad (default_generation_settings.n_ctx); LLAMA_CTX_SIZE queda como
        RESPALDO para cuando no hay server (impl in-process de
        llama-cpp-python, que se construye con ese mismo `_ctx_size()`) o
        /props no responde.

        LA AVERIA QUE ARREGLA (medida 2026-08-17). generate_long presupuestaba
        contra `_CTX_SIZE`, o sea la env LLAMA_CTX_SIZE leida EN EL IMPORT.
        ~/.cognia/config.env trae LLAMA_CTX_SIZE=200192 (perfil 'gpu', ver
        cognia/perf_profiles.py) y arranque.py la carga al entorno, mientras
        que el :8080 de esta maquina sirve con --ctx-size 16384. Resultado: la
        guarda creia tener 150.144 tokens de prefill (0,75 x 200.192) contra
        una ventana de 16.384 y no recortaba NUNCA. A/B MEDIDO contra el :8080
        vivo (mismo prompt de 11.501 tokens reales, chunk 1024, tope 6144):
          ANTES (ctx de la env)   8 rondas, stop_reason='error' (HTTP 400
                                  exceed_context_size), 4.883/6.144 tokens
                                  entregados y el prompt reenviado creciendo
                                  hasta 66.349 chars; las 3 ultimas rondas ya
                                  no producian nada (el server sin sitio).
          AHORA (n_ctx de /props) 6 rondas, stop_reason='limit', 6.144/6.144
                                  tokens y el prefill clavado en 49.155 chars
                                  = el budget de 12.288 tokens.

        El adoptado es el caso NORMAL, no una rareza: `cognia flota arrancar`
        levanta el server aparte y el backend se engancha, asi que la env del
        proceso del agente y los flags del server son dos fuentes distintas
        que nada obliga a coincidir.
        """
        try:
            n = (_server_props_summary(self.server_props() or {}) or {}).get("n_ctx")
        except Exception:
            n = None
        if isinstance(n, int) and not isinstance(n, bool) and n > 0:
            return n
        return _ctx_size()

    def contar_tokens(self, texto: str) -> int:
        """Cuantos tokens ocupa `texto` en ESTE backend. SE MIDE, NO SE DECLARA.

        Primero POST /tokenize del server que atiende de verdad; solo si el impl
        no lo expone (in-process) o el server no contesta se ESTIMA por chars, y
        la estimacion es deliberadamente PESIMISTA (GEN_CHARS_POR_TOKEN_EST=3,5
        frente a los 4,21 chars/token medidos en castellano el 2026-08-17): un
        presupuesto que se pasa por arriba recorta de mas, uno que se pasa por
        abajo se come un HTTP 400 a mitad de camino."""
        from shattering.model_constants import GEN_CHARS_POR_TOKEN_EST
        fn = getattr(self._impl, "tokenize_len", None)
        if callable(fn):
            try:
                n = fn(texto)
            except Exception:
                n = None
            if isinstance(n, int) and not isinstance(n, bool) and n >= 0:
                return n
        return int(len(texto or "") / GEN_CHARS_POR_TOKEN_EST) + 1

    def server_state(self) -> str:
        """Estado del server del impl: 'ok' | 'cargando' | 'ausente';
        'in-process' si el impl no tiene server (llama-cpp-python).

        Para que el caller (orchestrator._local_infer) distinga "backend caido"
        de "backend cargando/ocupado" ANTES de deshabilitar la via llama.cpp:
        un generate()==None con el server 'ok'/'cargando' es un fallo de UNA
        peticion, no la ausencia del backend (A1 2026-08-01)."""
        fn = getattr(self._impl, "_health_state", None)
        if not callable(fn):
            return "in-process"
        try:
            return fn()
        except Exception:
            return "ausente"

    @property
    def fleet_experts(self) -> list:
        """Nombres de expertos LoRA del fleet cargado, o [] (sin fleet)."""
        return list(getattr(self._impl, "_fleet_names", []) or [])

    @property
    def active_expert(self) -> Optional[str]:
        """Experto activo del fleet, o None (base pura / sin fleet)."""
        return getattr(self._impl, "_active_expert", None)

    def activate_expert(self, name: Optional[str]) -> bool:
        """Hot-swap del experto LoRA (None = base). False si el impl no soporta
        fleet (in-process) o el swap fallo. Ver _LlamaServerBackend.activate_expert."""
        fn = getattr(self._impl, "activate_expert", None)
        if not callable(fn):
            return name is None
        return fn(name)

    def experto_nativo(self) -> Optional[str]:
        """Primer adapter del manifest marcado nativo_compatible, o None.

        None tambien si el impl no soporta fleet (in-process): sin fleet no
        hay experto que activar. Ver _LlamaServerBackend.experto_nativo."""
        fn = getattr(self._impl, "experto_nativo", None)
        if not callable(fn):
            return None
        return fn()

    def generate(self, prompt: str, max_tokens: int = 256,
                 temperature: float = 0.7, top_p=None, top_k=None,
                 min_p=None, repeat_penalty=None, seed=None,
                 cache_prompt: bool = True, grammar: str = None,
                 stop=None) -> Optional[str]:
        # Sampling params: se reenvian SOLO si no son None, asi un impl viejo
        # sin esos kwargs sigue funcionando con la llamada posicional de siempre.
        extra = _sampling_payload(top_p=top_p, top_k=top_k, min_p=min_p,
                                  repeat_penalty=repeat_penalty, seed=seed)
        # cache_prompt: se reenvia SOLO cuando es False (el default True del
        # impl queda intacto y los impls viejos sin el kwarg siguen andando).
        if not cache_prompt:
            extra["cache_prompt"] = False
        # grammar (string GBNF): solo si se pasa, mismo criterio que arriba.
        if grammar is not None:
            extra["grammar"] = grammar
        # stop extra (p.ej. '\nACCION:' del loop del agente): solo si se pasa. El
        # impl lo MERGEA con los stops de fin-de-turno, nunca los reemplaza.
        if stop is not None:
            extra["stop"] = stop
        self._auditar("generate")
        return self._impl.generate(prompt, max_tokens, temperature, **extra)

    def generate_long(self, prompt: str, max_total_tokens: int = None,
                      chunk_tokens: int = None, temperature: float = 0.7,
                      on_chunk=None, resume_text: str = None) -> Optional[dict]:
        """
        Long-form generation via auto-continuation (FASE 1, target 5000 tokens).

        Generates chunk_tokens per round; while the round stops at the n_predict
        cap (last_stop_reason == 'limit') and the running total is below
        max_total_tokens, re-launches with prompt + accumulated text. Because
        every payload sends cache_prompt:true, llama-server re-uses the shared
        prefix KV-cache and each continuation only prefills the new tail.
        Stop strings are kept: an emitted <|im_end|> is a legitimate natural end.

        Ctx guard: cuando prompt+acumulado se acerca a la ventana REAL del server
        (n_ctx_efectivo(), o sea /props y no la env) el loop deja de reenviar el
        texto completo y manda prompt + la cola mas reciente, de modo que el
        prefill nunca desborda la ventana (el output sigue siendo completo).

        resume_text: cola YA ESCRITA de una corrida anterior (p.ej. /largo
        --continuar retomando desde un archivo). Se usa SOLO como contexto de
        re-anclaje (se antepone a lo acumulado en ESTA llamada antes de aplicar
        la guarda de ctx); NO se re-emite en el "text" devuelto -- el caller ya
        la tiene persistida. Default None = comportamiento actual (sin cola previa).

        on_chunk: optional callback on_chunk(round, chunk_tokens, total_tokens,
        stop_reason, chunk_text) for progress reporting AND escritura incremental
        (chunk_text es el texto crudo generado en esa ronda, para poder appendearlo
        a un archivo a medida que llega).

        Returns {"text", "total_tokens", "stop_reason", "rounds"}; None only if
        the FIRST round fails (same contract as generate()).
        """
        from shattering.model_constants import (
            GEN_CONTINUATION_CHUNK, GEN_LONG_MAX_TOKENS,
            GEN_CTX_GUARD_RATIO, GEN_CTX_MARGIN_TOKENS,
        )
        if max_total_tokens is None:
            max_total_tokens = GEN_LONG_MAX_TOKENS
        if chunk_tokens is None:
            chunk_tokens = GEN_CONTINUATION_CHUNK
        resume_text = resume_text or ""

        text_parts: list = []
        total_tokens = 0
        rounds       = 0
        stop_reason: Optional[str] = None

        # Techo de prefill: una fraccion del ctx, dejando sitio para el chunk a
        # generar. ~4 chars/token (mismo estimador que el fallback de abajo).
        # El ctx sale de /props (la ventana que el server sirve DE VERDAD) y no
        # de LLAMA_CTX_SIZE: ver n_ctx_efectivo() para la averia que eso causaba.
        # Una sola consulta para todo el bucle (GET local cacheado, ~3 ms).
        ctx = self.n_ctx_efectivo()
        prefill_cap = int(ctx * GEN_CTX_GUARD_RATIO)

        while total_tokens < max_total_tokens:
            ask   = min(chunk_tokens, max_total_tokens - total_tokens)
            # Guarda de ctx: si prompt+acumulado no entra bajo el techo, no reenviar
            # TODO -> mandar prompt + la cola mas reciente. text_parts conserva el
            # texto completo (la cola es solo input al modelo, no recorta el output).
            # resume_text (si hay) cuenta como acumulado YA ESCRITO -> va primero.
            budget = min(prefill_cap, ctx - ask - GEN_CTX_MARGIN_TOKENS)
            accumulated = resume_text + "".join(text_parts)
            if (len(prompt) + len(accumulated)) // 4 > budget:
                keep_tokens = max(0, budget - len(prompt) // 4)
                accumulated = accumulated[-(keep_tokens * 4):] if keep_tokens else ""
            chunk = self.generate(prompt + accumulated,
                                  max_tokens=ask, temperature=temperature)
            if chunk is None:
                # Request failed; surface what we have (None if nothing yet)
                if not text_parts:
                    return None
                stop_reason = "error"
                break
            rounds += 1
            real = self.last_tokens_predicted
            chunk_toks = real if real is not None else max(1, len(chunk) // 4)
            total_tokens += chunk_toks
            text_parts.append(chunk)
            stop_reason = self.last_stop_reason
            if on_chunk is not None:
                try:
                    on_chunk(rounds, chunk_toks, total_tokens, stop_reason, chunk)
                except Exception:
                    pass
            if stop_reason != "limit":
                break   # eos/word (natural end) or unknown -> do not continue
            if not chunk:
                break   # no progress despite 'limit' -> avoid an infinite loop

        return {
            "text":         "".join(text_parts),
            "total_tokens": total_tokens,
            "stop_reason":  stop_reason,
            "rounds":       rounds,
        }

    @staticmethod
    def _append_to_user_turn(prompt: str, extra: str) -> str:
        """Agrega ``extra`` al TURNO DE USUARIO de un prompt ChatML.

        Bug real (medido 2026-07-04): generate_delegated/hierarchical hacian
        f'{prompt}\\n\\n{instruccion}', pero cuando el caller (el CLI) pasa un
        prompt YA templado que termina en '<|im_start|>assistant\\n', la
        instruccion caia DENTRO del turno del asistente -> el modelo creia que
        ya habia terminado y devolvia vacio (eos inmediato). Las sub-generaciones
        del outline/secciones salian de 1 token. Los tests con backends FALSOS no
        lo cazaron (usaban prompts crudos).

        Fix: si el prompt trae el marcador de apertura del asistente al final,
        insertar ``extra`` antes del cierre del turno de usuario (para que el
        modelo lo vea como parte del pedido). Si NO esta templado (prompt crudo),
        se appendea como antes -> compat total con los callers de test."""
        tail = "<|im_end|>\n<|im_start|>assistant\n"
        if prompt.endswith(tail):
            head = prompt[:-len(tail)]
            return f"{head}\n\n{extra}{tail}"
        return f"{prompt}\n\n{extra}"

    @staticmethod
    def _items_enumerados(text: str) -> list:
        """Items de una enumeracion 1., 2., 3., ... siguiendo la numeracion
        CONSECUTIVA por TODO el texto, crucen o no los saltos de linea.

        POR QUE ASI Y NO LINEA A LINEA (fallo MEDIDO el 2026-08-17, 2 de 7
        corridas del sondeo de outline): el modelo devuelve la lista entera en
        UNA linea -- "1. Diseno Arquitectonico 2. Implementacion de Software
        3. Configuracion de la GPU ..." -- y el parseo por lineas la tomaba como
        UN item; con al menos otra linea numerada detras ya habia >=2 items, no
        se disparaba el reparto inline y el item 1 se entregaba RECORTADO a 120
        chars como titulo de la seccion 1. Un worker recibio exactamente ese
        titulo y escribio el documento entero.

        Encadenar por numero ESPERADO parte esa linea y a la vez no destroza
        titulos con numeros sueltos: solo se acepta el marcador cuyo numero es
        el siguiente de la cadena (1, 2, 3, ...). Si no hay cadena de >=2, el
        caller cae a los heuristicos de siempre (vinetas, lineas sueltas)."""
        import re
        marcas = []
        esperado = 1
        for m in re.finditer(r"(?:(?<=\s)|^)[\(\[]?(\d{1,3})[\.\)]\s+", text):
            if int(m.group(1)) == esperado:
                marcas.append(m)
                esperado += 1
        if len(marcas) < 2:
            return []
        items = []
        for i, m in enumerate(marcas):
            fin = marcas[i + 1].start() if i + 1 < len(marcas) else len(text)
            trozo = text[m.end():fin].strip()
            # El titulo termina donde termina su linea: lo que siga (descripcion
            # del item, epilogo del modelo) no es parte del titulo.
            trozo = trozo.split("\n", 1)[0].strip(" .;:-\t")
            if trozo:
                items.append(trozo)
        return items

    @staticmethod
    def _parse_outline(text: str, max_sections: int) -> list:
        """Extrae titulos de seccion de un outline LLM. Robusto al modelo que no
        respeta 'uno por linea': (1) cadena de numeracion consecutiva por todo el
        texto -- parte tambien la lista escrita en UNA sola linea, ver
        _items_enumerados; (2) lineas numeradas/vinetas; (3) marcadores numerados
        INLINE '(1.' / '2)'; (4) fallback a lineas no vacias. Capa cada titulo a
        120 chars."""
        import re
        text = text or ""
        items = LlamaBackend._items_enumerados(text)
        if len(items) < 2:
            items = []
            for line in text.splitlines():
                line = line.strip()
                m = re.match(r"^[\(\[]?(?:\d+[\.\)]|[-*•])\s*(.+)", line)
                if m and m.group(1).strip():
                    items.append(m.group(1).strip())
        if len(items) < 2:
            # marcadores numerados en cualquier posicion (el 3B mete '(1. ...' inline)
            chunks = re.split(r"[\(\[]?\b\d+[\.\)]\s+", text)
            cand = [c.strip(" .)\n\t-") for c in chunks if len(c.strip()) > 2]
            if len(cand) >= 2:
                items = cand
        if not items:
            items = [ln.strip() for ln in text.splitlines() if ln.strip()]
        return [it[:120] for it in items][:max_sections]

    # ── outline VALIDADO y por LOTES ─────────────────────────────────────────
    # El outline es el punto donde /largo --delegado miente sin gritar: si el
    # parseo devuelve menos items de los pedidos, el documento sale corto y
    # nadie se entera (medido: n=144 -> 55 items = ~77k tokens de los 200k
    # pedidos). De aca en adelante NADA corre workers sin contar los items
    # primero.

    @staticmethod
    def _numerar(items: list, desde: int = 1) -> str:
        """Lista numerada '1. titulo' lista para incrustar en un prompt."""
        return "\n".join(f"{desde + i}. {s}" for i, s in enumerate(items))

    @staticmethod
    def _reparto(total: int, partes: int) -> list:
        """Reparte `total` secciones en `partes` lotes lo mas parejos posible."""
        partes = max(1, partes)
        base, resto = divmod(total, partes)
        return [base + (1 if i < resto else 0) for i in range(partes)]

    @staticmethod
    def _avisar(cb, tipo: str, mensaje: str) -> None:
        """Callback de aviso, blindado (nunca revienta al caller).

        Los fallos de esta ruta son MUDOS por naturaleza: un documento mas corto
        sigue pareciendo un documento. Ademas de loguear, se ofrece un canal
        explicito para que la UI pueda decirlo."""
        if cb is None:
            return
        try:
            cb(tipo, mensaje)
        except Exception:
            pass

    @staticmethod
    def _familia_repetida(items: list):
        """El bucle que el CONTEO no ve: (tamano, titulo_base) de la familia mas
        grande de titulos que son extensiones de un mismo titulo del esquema.

        MEDIDO 2026-08-18 en un ensayo de 24 secciones que el conteo dio por
        bueno (24/24 items, los 24 strings distintos): del 12 al 23 el modelo
        encadeno "Modelos de Consistencia de Sesgo" -> "... Total" ->
        "... Parcial" -> "... Parcial Total" -> ... Once secciones, la mitad del
        documento, sobre un tema que se invento sobre la marcha; y el gate
        imprimio PASS porque los tokens salieron. En 9 outlines sanos medidos el
        mismo dia la familia maxima fue 1."""
        lo = [(it or "").strip().lower() for it in items]
        mejor = (1, items[0] if items else "")
        for j, base in enumerate(lo):
            if not base:
                continue
            # +1: la propia base cuenta como miembro de su familia
            n = 1 + sum(1 for i, a in enumerate(lo)
                        if i != j and len(a) > len(base) and a.startswith(base + " "))
            if n > mejor[0]:
                mejor = (n, items[j])
        return mejor

    def _outline_validado(self, prompt: str, n: int, temperature: float,
                          instruccion: str = None, intentos: int = None):
        """Pide un esquema de EXACTAMENTE n items, los CUENTA y comprueba que no
        sean un BUCLE antes de darlo por bueno.

        Devuelve (items, error): error None si len(items) == n y ninguna familia
        de titulos pasa de GEN_OUTLINE_MAX_FAMILIA. Si tras `intentos` llamadas
        sigue sin cuadrar, devuelve el mejor intento y un error con los DOS
        numeros ("esquema incompleto: pedi 24, parsee 9") -- el fallo mudo es lo
        que convertia 200k tokens en 77k. Si el numero cuadra pero el esquema esta
        degenerado, devuelve el ULTIMO (los items existen y son usables) con un
        error que lo dice: la decision de correr igual o abortar es del caller.
        """
        from shattering.model_constants import (
            GEN_OUTLINE_MAX_FAMILIA, GEN_OUTLINE_REINTENTOS,
        )
        if intentos is None:
            intentos = GEN_OUTLINE_REINTENTOS
        if instruccion is None:
            # Texto historico, palabra por palabra: es el prompt con el que se
            # midieron 6/6 y 40/40, y el que reconocen los fakes de los tests.
            instruccion = (
                f"Primero, devuelve SOLO un esquema de exactamente {n} secciones "
                f"para responder lo anterior: una por linea, numeradas (1., 2., ...), con un "
                f"titulo corto cada una. Sin texto adicional.")
        mejor: list = []
        sin_respuesta = 0
        degenerado = None
        for _ in range(max(1, int(intentos))):
            texto = self.generate(self._append_to_user_turn(prompt, instruccion),
                                  max_tokens=max(128, n * 32), temperature=temperature)
            if texto is None:
                sin_respuesta += 1
                continue
            items = self._parse_outline(texto, n)
            if len(items) == n:
                familia, base = self._familia_repetida(items)
                if familia < GEN_OUTLINE_MAX_FAMILIA:
                    return items, None
                # El numero cuadra pero el modelo esta en bucle: se REINTENTA el
                # lote (cuesta segundos) en vez de escribir el documento.
                degenerado = (items, familia, base)
                logger.warning("[llama_backend] esquema degenerado: %d de %d "
                               "titulos son variantes de %r; reintentando",
                               familia, n, base[:60])
                continue
            if len(items) > len(mejor):
                mejor = items
        if degenerado is not None:
            items, familia, base = degenerado
            return items, (f"esquema degenerado: {familia} de {n} titulos son "
                           f"variantes de {base[:60]!r}")
        if not mejor:
            return [], (f"esquema de {n} secciones sin respuesta del backend "
                        f"({sin_respuesta} de {intentos} intentos vacios)")
        return mejor, f"esquema incompleto: pedi {n}, parsee {len(mejor)}"

    def _plan_outline(self, prompt: str, n_tasks: int, temperature: float,
                      batch: int = None, intentos: int = None):
        """Plan de n_tasks secciones, en UN nivel o en DOS segun el tamano.

        Un solo outline no aguanta 144 secciones (medido: 144 items en 1 de 2
        corridas, 55 en la otra), pero si aguanta 40 (3 de 3) y 24. Asi que por
        encima de `batch` se pide un INDICE de ceil(n/batch) capitulos y luego el
        esquema de cada capitulo por separado: cada llamada se queda dentro del
        rango donde el parseo se midio fiable.

        Devuelve (tasks, bloques, meta):
          tasks    titulos de seccion (len == n_tasks salvo que meta['error'])
          bloques  paralela a tasks: el esquema que ve CADA worker. Con dos
                   niveles el worker ve el indice de capitulos + las secciones de
                   SU capitulo, numeradas con el indice GLOBAL (mandarle las 144
                   a cada worker son ~4k tokens de prefill por worker, y el numero
                   que se le pide escribir tiene que coincidir con el que ve).
          meta     {'niveles','lote','capitulos','error'}
        """
        from shattering.model_constants import GEN_OUTLINE_BATCH
        if batch is None:
            batch = GEN_OUTLINE_BATCH
        batch = max(1, int(batch))
        meta = {"niveles": 1, "lote": batch, "capitulos": [], "error": None}

        if n_tasks <= batch:
            items, err = self._outline_validado(prompt, n_tasks, temperature,
                                                intentos=intentos)
            meta["error"] = err
            bloque = self._numerar(items)
            return items, [bloque] * len(items), meta

        meta["niveles"] = 2
        n_caps = -(-n_tasks // batch)          # ceil
        tamanos = self._reparto(n_tasks, n_caps)
        caps, err = self._outline_validado(
            prompt, n_caps, temperature, intentos=intentos,
            instruccion=(f"Primero, devuelve SOLO el indice de capitulos de un documento "
                         f"extenso que responda lo anterior: exactamente {n_caps} capitulos, "
                         f"uno por linea, numerados (1., 2., ...), con un titulo corto cada "
                         f"uno. Sin texto adicional."))
        if err:
            meta["error"] = f"indice de capitulos: {err}"
            return [], [], meta
        meta["capitulos"] = list(caps)
        indice = self._numerar(caps)

        tasks: list = []
        bloques: list = []
        for j, (cap, k) in enumerate(zip(caps, tamanos)):
            sub, err = self._outline_validado(
                prompt, k, temperature, intentos=intentos,
                instruccion=(f"El documento se organiza en estos capitulos:\n{indice}\n\n"
                             f"Devuelve SOLO el esquema del capitulo {j + 1} ({cap}): "
                             f"exactamente {k} secciones, una por linea, numeradas "
                             f"(1., 2., ...), con un titulo corto cada una. Sin texto adicional."))
            if err:
                meta["error"] = f"capitulo {j + 1}/{n_caps} ({cap}): {err}"
                return tasks, bloques, meta
            desde = len(tasks) + 1
            bloque = (f"Capitulos:\n{indice}\n\n"
                      f"Secciones del capitulo {j + 1} ({cap}):\n"
                      + self._numerar(sub, desde))
            tasks.extend(sub)
            bloques.extend([bloque] * len(sub))
        return tasks, bloques, meta

    # ── cabeza que teje, sin reventar muda ───────────────────────────────────

    def _head_prompt(self, prompt: str, drafts: list, extracto_chars: int) -> str:
        """Prompt de la cabeza con `extracto_chars` de cada draft (0 = solo titulos)."""
        if extracto_chars > 0:
            excerpts = "\n".join(
                f"{i + 1}. {t}: {(txt[:extracto_chars]).strip()}"
                for i, (t, txt) in enumerate(drafts)
            ).replace("\n\n", " ")
        else:
            excerpts = "\n".join(f"{i + 1}. {t}" for i, (t, _txt) in enumerate(drafts))
        # Prompt POSITIVO (sin negaciones) + repeat_penalty en el caller: las
        # negaciones ("No repitas...") inducian un loop degenerado en el 3B.
        return self._append_to_user_turn(
            prompt,
            f"Un documento tiene estas secciones (extractos):\n{excerpts}\n\n"
            f"Escribe una introduccion breve de 2 a 4 frases que presente de que trata el "
            f"documento y como se conectan sus secciones.")

    def _cabeza_tejida(self, prompt: str, drafts: list, temperature: float):
        """Introduccion que teje los drafts SIN reventar muda si no entra en el ctx.

        LA AVERIA (medida 2026-08-17): el prompt de la cabeza son ~400 chars de
        extracto x n_secciones; con castellano real (4,21 chars/token) 144
        secciones daban 15.191 de 16.384 tokens -- entraba con 973 de margen --,
        y por encima de ~151 el server devolvia HTTP 400, generate() devolvia
        None y `head = ... or ""` se lo tragaba: documento sin introduccion y sin
        una linea de aviso.

        Ahora: el prompt se MIDE contra el n_ctx REAL (/props + /tokenize, nunca
        la env), el extracto se ENCOGE por pasos hasta que entra, y si ni con los
        titulos pelados entra se trocea el resumen. Cualquier fallo sale por
        meta['error'] -- nunca en silencio.

        Devuelve (texto, meta) con meta =
        {'extracto_chars','bloques','prompt_tokens','ctx','presupuesto','error'}.
        """
        from shattering.model_constants import (
            GEN_CTX_GUARD_RATIO, GEN_CTX_MARGIN_TOKENS, GEN_HEAD_MAX_TOKENS,
            GEN_HEAD_EXCERPT_STEPS,
        )
        ctx = self.n_ctx_efectivo()
        presupuesto = min(int(ctx * GEN_CTX_GUARD_RATIO),
                          ctx - GEN_HEAD_MAX_TOKENS - GEN_CTX_MARGIN_TOKENS)
        meta = {"extracto_chars": None, "bloques": 1, "prompt_tokens": None,
                "ctx": ctx, "presupuesto": presupuesto, "error": None}
        if presupuesto <= 0:
            meta["error"] = (f"el ctx del server no da ni para la cabeza "
                             f"(n_ctx={ctx}): documento sin introduccion")
            return "", meta

        for chars in GEN_HEAD_EXCERPT_STEPS:
            p = self._head_prompt(prompt, drafts, chars)
            n = self.contar_tokens(p)
            if n <= presupuesto:
                meta["extracto_chars"] = chars
                meta["prompt_tokens"] = n
                txt = self.generate(p, max_tokens=GEN_HEAD_MAX_TOKENS,
                                    temperature=temperature, repeat_penalty=1.3)
                if txt is None:
                    meta["error"] = (f"la cabeza no respondio (prompt de {n} tokens "
                                     f"contra n_ctx {ctx}): documento sin introduccion")
                    return "", meta
                return txt.strip(), meta

        return self._cabeza_troceada(prompt, drafts, temperature, presupuesto, meta)

    def _cabeza_troceada(self, prompt: str, drafts: list, temperature: float,
                         presupuesto: int, meta: dict):
        """Cabeza en DOS niveles: una sintesis por bloque de secciones y una cabeza
        final sobre esas sintesis. Solo se usa cuando ni el prompt con titulos
        pelados entra en el presupuesto (n muy grande o ctx muy chico)."""
        from shattering.model_constants import GEN_HEAD_MAX_TOKENS
        titulos_tok = self.contar_tokens(self._head_prompt(prompt, drafts, 0))
        n_bloques = min(len(drafts),
                        max(2, -(-titulos_tok // max(1, presupuesto)) + 1))
        meta["bloques"] = n_bloques
        sintesis: list = []
        i = 0
        for j, k in enumerate(self._reparto(len(drafts), n_bloques)):
            bloque = drafts[i:i + k]
            i += k
            p = self._head_prompt(prompt, bloque, 0)
            n = self.contar_tokens(p)
            if n > presupuesto:
                meta["error"] = (f"ni troceado en {n_bloques} bloques entra el resumen de "
                                 f"{len(drafts)} secciones ({n} tokens > {presupuesto} de "
                                 f"presupuesto, n_ctx {meta['ctx']}): documento sin introduccion")
                return "", meta
            txt = self.generate(p, max_tokens=GEN_HEAD_MAX_TOKENS,
                                temperature=temperature, repeat_penalty=1.3)
            if txt is None:
                meta["error"] = (f"la sintesis del bloque {j + 1}/{n_bloques} no respondio: "
                                 f"documento sin introduccion")
                return "", meta
            sintesis.append((f"Bloque {j + 1}", txt.strip()))

        p = self._head_prompt(prompt, sintesis, 400)
        n = self.contar_tokens(p)
        meta["prompt_tokens"] = n
        if n > presupuesto:
            meta["error"] = (f"la cabeza final no entra ({n} tokens > {presupuesto}): "
                             f"documento sin introduccion")
            return "", meta
        txt = self.generate(p, max_tokens=GEN_HEAD_MAX_TOKENS, temperature=temperature,
                            repeat_penalty=1.3)
        if txt is None:
            meta["error"] = "la cabeza final no respondio: documento sin introduccion"
            return "", meta
        return txt.strip(), meta

    def generate_hierarchical(self, prompt: str, target_tokens: int = None,
                              n_sections: int = None, temperature: float = 0.7,
                              on_section=None, on_outline=None) -> Optional[dict]:
        """
        Generacion larga JERARQUICA (FASE 7a): pide un outline de N secciones y genera
        cada seccion con un prompt FRESCO = prompt + outline + resumen corto de lo previo.
        El prefill por seccion es acotado (no crece con el texto total), asi la longitud
        total deja de estar limitada por el ctx de 16k -> generacion cuasi-infinita; el
        unico limite real pasa a ser el tiempo de pared (~8 tok/s).

        on_outline: callback opcional on_outline(sections) invocado UNA vez, apenas se
        parsea el esquema (antes de generar ninguna seccion) -- permite persistir el
        plan completo (p.ej. el sidecar de /largo --continuar) sin esperar a que termine
        la primera seccion.
        on_section: callback opcional on_section(idx, total, titulo, tokens, texto,
        stop_reason) por cada seccion COMPLETA (texto = el texto de esa seccion,
        stop_reason = el de su generate_long interno; para escritura incremental).
        Returns {"text","outline","sections","total_tokens","rounds"}; None si falla el
        outline o la primera seccion (mismo contrato de None que generate()).
        """
        from shattering.model_constants import (
            GEN_LONG_MAX_TOKENS, GEN_HIERARCHICAL_SECTIONS, GEN_SECTION_SUMMARY_CHARS,
        )
        if target_tokens is None:
            target_tokens = GEN_LONG_MAX_TOKENS
        if n_sections is None:
            n_sections = GEN_HIERARCHICAL_SECTIONS

        outline_prompt = self._append_to_user_turn(
            prompt,
            f"Primero, devuelve SOLO un esquema de exactamente {n_sections} secciones "
            f"para responder lo anterior: una por linea, numeradas (1., 2., ...), con un "
            f"titulo corto cada una. Sin texto adicional."
        )
        outline_text = self.generate(outline_prompt,
                                     max_tokens=max(128, n_sections * 32),
                                     temperature=temperature)
        if outline_text is None:
            return None
        sections = self._parse_outline(outline_text, n_sections) or [prompt]
        if on_outline is not None:
            try:
                on_outline(sections)
            except Exception:
                pass

        outline_block = "\n".join(f"{i+1}. {s}" for i, s in enumerate(sections))
        per_section = max(256, target_tokens // max(1, len(sections)))
        parts: list = []
        total_tokens = 0
        rounds = 0
        prev_summary = ""

        for i, sec in enumerate(sections):
            sec_prompt = self._append_to_user_turn(
                prompt,
                f"Esquema:\n{outline_block}\n\n"
                + (f"Resumen de lo ya escrito: {prev_summary}\n\n" if prev_summary else "")
                + f"Escribe SOLO la seccion {i+1}: {sec}"
            )
            res = self.generate_long(sec_prompt, max_total_tokens=per_section,
                                     temperature=temperature)
            if res is None:
                if not parts:
                    return None
                break
            parts.append(f"## {sec}\n{res['text']}")
            total_tokens += res["total_tokens"]
            rounds += res["rounds"]
            # Resumen acotado -> mantiene chico el prefill de la siguiente seccion
            prev_summary = (sec + ": " + (res["text"] or "")[:GEN_SECTION_SUMMARY_CHARS]
                            ).replace("\n", " ")
            if on_section is not None:
                try:
                    on_section(i + 1, len(sections), sec, res["total_tokens"],
                              res["text"], res["stop_reason"])
                except Exception:
                    pass

        return {
            "text":         "\n\n".join(parts),
            "outline":      sections,
            "sections":     len(parts),
            "total_tokens": total_tokens,
            "rounds":       rounds,
        }

    def generate_delegated(self, prompt: str, target_tokens: int = None,
                           n_tasks: int = None, per_task_cap: int = None,
                           aggregate: bool = True, temperature: float = 0.7,
                           on_task=None, on_outline=None, outline_batch: int = None,
                           outline_intentos: int = None, on_aviso=None) -> Optional[dict]:
        """
        Generacion larga por DELEGACION (orchestrator-workers). Descompone en un outline
        de N subtareas (spec compartido) y genera cada una con un worker de CONTEXTO LIMPIO:
        el prompt de cada worker es prompt + esquema + SOLO esa subtarea, SIN arrastrar el
        resumen de las previas (a diferencia de generate_hierarchical). Cada worker corre
        hasta per_task_cap (<= GEN_LONG_MAX_TOKENS), asi el output TOTAL = suma de subtareas
        y deja de estar acotado por el ctx de 16k.

        EL PLAN SE VALIDA ANTES DE GASTAR LA GPU (2026-08-18). El outline de golpe no
        aguanta 144 secciones (medido: 144 items en 1 de 2 corridas, 55 en la otra) y
        es flaky incluso a n=6, siempre en silencio. Ahora: por encima de
        `outline_batch` (default GEN_OUTLINE_BATCH=24) el esquema se pide en DOS
        NIVELES -- indice de capitulos + lote por capitulo, cada llamada dentro del
        rango medido fiable --, cada lote se CUENTA y se reintenta, y si al final no
        cuadra se devuelve None con el error ("pedi 24, parsee 9") en vez de correr
        medio documento como si nada. Ver _plan_outline/_outline_validado.

        Si aggregate y hay >1 subtarea, una CABEZA final teje: recibe el esquema + un
        extracto acotado de cada draft y escribe una introduccion unificadora. El cuerpo
        (drafts completos) se CONSERVA -> la cabeza ENMARCA, no reescribe. El prompt de
        la cabeza se MIDE contra el n_ctx real del server y se encoge/trocea hasta que
        entra; si aun asi falla, sale por result['head_error'] y por on_aviso -- nunca en
        silencio (ver _cabeza_tejida). Honesto: los workers son ciegos entre si; la
        coherencia global la aporta el esquema compartido + el frame de la cabeza.

        on_outline: callback opcional on_outline(tasks) invocado UNA vez, apenas el plan
        esta COMPLETO y validado (antes de correr ningun worker).
        on_task: callback opcional on_task(idx, total, titulo, tokens, texto, stop_reason)
        por cada subtarea COMPLETA.
        on_aviso: callback opcional on_aviso(tipo, mensaje) para los fallos que antes eran
        mudos; tipo in {'outline','worker','cabeza'}.

        Returns {"text","outline","sections","total_tokens","rounds","head","head_error",
        "truncado","plan"}; None si falla el plan o la primera subtarea.
        """
        from shattering.model_constants import (
            GEN_LONG_MAX_TOKENS, GEN_HIERARCHICAL_SECTIONS,
        )
        if n_tasks is None:
            n_tasks = GEN_HIERARCHICAL_SECTIONS
        if target_tokens is None:
            target_tokens = GEN_LONG_MAX_TOKENS
        if per_task_cap is None:
            per_task_cap = GEN_LONG_MAX_TOKENS

        tasks, bloques, plan = self._plan_outline(prompt, n_tasks, temperature,
                                                  batch=outline_batch,
                                                  intentos=outline_intentos)
        if plan.get("error"):
            # NO se gasta la GPU con un plan incompleto NI con uno degenerado: el
            # documento saldria corto (55 de 144 secciones = ~77k tokens de los
            # 200k) o saldria entero pero con media docena de capitulos que son
            # variantes del mismo titulo (medido 2026-08-18: 11 de 24), y en los
            # dos casos nadie se enteraria.
            logger.error("[llama_backend] plan del outline: %s", plan["error"])
            self._avisar(on_aviso, "outline", plan["error"])
            return None
        if on_outline is not None:
            try:
                on_outline(tasks)
            except Exception:
                pass

        per_task = min(per_task_cap, max(256, target_tokens // max(1, len(tasks))))
        parts: list = []
        drafts: list = []
        total_tokens = 0
        rounds = 0
        truncado = None

        for i, sec in enumerate(tasks):
            # CAMBIO 1 vs generate_hierarchical: worker de CONTEXTO LIMPIO ->
            # NO se incluye prev_summary; cada subtarea arranca con el esquema puro.
            sec_prompt = self._append_to_user_turn(
                prompt,
                f"Esquema:\n{bloques[i]}\n\n"
                f"Escribe SOLO la seccion {i + 1}: {sec}. No repitas las otras secciones."
            )
            res = self.generate_long(sec_prompt, max_total_tokens=per_task,
                                     temperature=temperature)
            if res is None:
                truncado = (f"el worker {i + 1} de {len(tasks)} no respondio: el documento "
                            f"queda con {len(parts)} secciones de {len(tasks)}")
                logger.warning("[llama_backend] %s", truncado)
                self._avisar(on_aviso, "worker", truncado)
                if not parts:
                    return None
                break
            parts.append(f"## {sec}\n{res['text']}")
            drafts.append((sec, res["text"] or ""))
            total_tokens += res["total_tokens"]
            rounds += res["rounds"]
            if on_task is not None:
                try:
                    on_task(i + 1, len(tasks), sec, res["total_tokens"],
                           res["text"], res["stop_reason"])
                except Exception:
                    pass

        body = "\n\n".join(parts)
        head = ""
        head_error = None
        # CAMBIO 2 vs generate_hierarchical: cabeza que teje (reemplaza el join crudo).
        if aggregate and len(drafts) > 1:
            head, hmeta = self._cabeza_tejida(prompt, drafts, temperature)
            head_error = hmeta.get("error")
            plan["cabeza"] = hmeta
            if head_error:
                logger.warning("[llama_backend] cabeza: %s", head_error)
                self._avisar(on_aviso, "cabeza", head_error)

        text = (head.strip() + "\n\n" + body) if head.strip() else body
        return {
            "text":         text,
            "outline":      tasks,
            "sections":     len(parts),
            "total_tokens": total_tokens,
            "rounds":       rounds,
            "head":         head.strip(),
            "head_error":   head_error,
            "truncado":     truncado,
            "plan":         plan,
        }

    def stream_generate(self, prompt: str, max_tokens: int = 256,
                        temperature: float = 0.7, top_p=None, top_k=None,
                        min_p=None, repeat_penalty=None, seed=None,
                        cache_prompt: bool = True, grammar: str = None):
        """Yield tokens; falls back to non-streaming generate() if impl has no stream_generate."""
        extra = _sampling_payload(top_p=top_p, top_k=top_k, min_p=min_p,
                                  repeat_penalty=repeat_penalty, seed=seed)
        # cache_prompt: solo cuando es False (ver generate())
        if not cache_prompt:
            extra["cache_prompt"] = False
        # grammar (string GBNF): solo si se pasa (ver generate())
        if grammar is not None:
            extra["grammar"] = grammar
        self._auditar("stream_generate")
        if hasattr(self._impl, "stream_generate"):
            yield from self._impl.stream_generate(prompt, max_tokens, temperature, **extra)
        else:
            result = self._impl.generate(prompt, max_tokens, temperature, **extra)
            if result:
                yield result

    def stream_chat(self, messages: list, max_tokens: int = 512,
                    temperature: float = 0.7, top_p=None, top_k=None,
                    min_p=None, repeat_penalty=None, seed=None,
                    cache_prompt: bool = True, on_reasoning=None):
        """Yield tokens using multi-turn /v1/chat/completions.

        on_reasoning: callback opcional que recibe cada fragmento de
        reasoning_content del razonador (ver el impl server). Solo se
        reenvia cuando se pasa: los impls viejos/mocks no lo conocen."""
        extra = _sampling_payload(top_p=top_p, top_k=top_k, min_p=min_p,
                                  repeat_penalty=repeat_penalty, seed=seed)
        # cache_prompt: solo cuando es False (ver generate())
        if not cache_prompt:
            extra["cache_prompt"] = False
        if on_reasoning is not None:
            extra["on_reasoning"] = on_reasoning
        self._auditar("chat")
        if hasattr(self._impl, "stream_chat"):
            yield from self._impl.stream_chat(messages, max_tokens, temperature, **extra)
        else:
            # Flatten history to a single prompt as fallback. Sin razonamiento
            # separado en /completion: el callback no aplica aqui.
            extra.pop("on_reasoning", None)
            text = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
            yield from self.stream_generate(text, max_tokens, temperature, **extra)

    def stop(self) -> bool:
        """Para el server si el impl lo maneja. True si quedo parado (o no habia server).

        El impl in-process (llama-cpp-python) no tiene stop(): se devuelve True
        porque no hay puerto que liberar (el modelo viejo lo libera el GC).
        """
        if hasattr(self._impl, "stop"):
            return bool(self._impl.stop())
        return True

    @classmethod
    def try_load(cls) -> Optional["LlamaBackend"]:
        """
        Try to build a working backend. Returns None if:
        - No GGUF model found
        - Neither llama-cpp-python nor llama-server binary is available
        - Any initialisation error

        Ya NO es silencioso (2026-07-25). Cada None pasa por
        cognia.backend_activo.sin_backend(): grita por stderr y queda en
        ~/.cognia/backend_audit.jsonl. Devolver None en silencio es exactamente
        como el sistema estuvo degradando durante meses sin que se viera en la
        salida — el caller sigue pudiendo manejar el None, pero ya no puede
        hacerlo sin que quede registro.
        """
        def _gritar(detalle: str):
            try:
                from cognia import backend_activo
                backend_activo.sin_backend("llama_backend.try_load", detalle)
            except Exception:
                pass
            return None

        gguf = _find_gguf()
        if gguf is None:
            return _gritar("no hay GGUF (revisa LLAMA_GGUF_PATH en "
                           "~/.cognia/config.env)")

        # Try in-process Python bindings first
        if _LlamaCppBackend.available():
            try:
                return cls(_LlamaCppBackend(gguf))
            except Exception as exc:
                logger.debug("[llama_backend] llama-cpp-python init failed: %s", exc)

        # Try subprocess server
        if _LlamaServerBackend.available():
            port = int(os.environ.get("LLAMA_SERVER_PORT", _DEFAULT_PORT))
            try:
                return cls(_LlamaServerBackend(gguf, port))
            except Exception as exc:
                logger.debug("[llama_backend] llama-server init failed: %s", exc)
                return _gritar(f"llama-server no arranco en :{port}: {exc}")

        # Diagnostico PRECISO, no generico. Un verificador de contexto fresco
        # (2026-07-25) recibio "ni el binario llama-server" con el binario
        # PRESENTE en ~/.cognia/llama: lo que faltaba era apply_config(), que es
        # quien mete LLAMA_SERVER_PATH y LLAMA_GGUF_PATH en el entorno. Un aviso
        # que apunta a la causa equivocada hace perder mas tiempo que el
        # silencio, porque se investiga lo que no es.
        binario_en_casa = (Path.home() / ".cognia" / "llama" /
                           "llama-server.exe")
        if binario_en_casa.is_file() and not os.environ.get("LLAMA_SERVER_PATH"):
            return _gritar(
                f"el binario existe ({binario_en_casa}) pero LLAMA_SERVER_PATH "
                f"no esta en el entorno: falta llamar "
                f"cognia.first_run.apply_config() antes de usar el backend "
                f"(el CLI lo hace; un script suelto, no). Ademas por eso el "
                f"GGUF elegido fue {gguf.name} y no el de config.env.")
        return _gritar(f"GGUF encontrado ({gguf.name}) pero no hay runtime: "
                       f"ni llama-cpp-python ni el binario llama-server")
