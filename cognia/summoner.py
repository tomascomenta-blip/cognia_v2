"""
cognia/summoner.py
==================
Invocador de roles GPU: una capa ENCIMA de cognia/flota.py, no un reemplazo.

POR QUE EXISTE: la flota manual no guarda PID (servir_modelo.py hace Popen y
abandona el handle), mata con taskkill /IM global, no tiene reloj de
inactividad ni presupuesto de VRAM. Este modulo agrega exactamente eso:

- Registry declarativo de ROLES con puerto, VRAM presupuestada e idle.
- ensure(rol): garantiza que el rol este servido y VERIFICADO (identidad via
  /props con forzar=True; cargar no es funcionar).
- liberar(rol): kill selectivo por PID guardado (taskkill /PID, JAMAS /IM).
- barrido(): reloj de inactividad oportunista, SIN hilos demonio (un demonio
  que muere en silencio es el modo de fallo historico de la casa).
- invocar(rol, payload): job pesado con eviction temporal del cerebro y
  auto-restore ANTES de retornar (el tool call vive dentro del bucle del
  agente: al retornar, la proxima request va al cerebro).
- escalar_ctx(): relanza el cerebro SOLO a celdas de contexto MEDIDAS
  (la formula de KV por token erro 6x en este modelo; no se extrapola).

Tipos de rol:
- "llama":       llama-server via los scripts existentes (cerebro, vlm).
- "job":         worker HTTP en subproceso venv312gpu (imagen); matar el
                 proceso ES el unload (cognia.assets no descarga pipelines).
- "presupuesto": SIN proceso; ensure() solo chequea VRAM + anota una reserva
                 en el estado para CLIs one-shot (tresd/voces/musica fase 1).

Regla dura anti degradacion silenciosa: todo camino de error (a) emite
Degradado al bus de ux/events, (b) print a stderr, (c) levanta SummonerError.
Jamas None pelado.

Estado persistido en ~/.cognia/summoner.json (override COGNIA_SUMMONER_STATE
para tests), escritura atomica. Un PID guardado es HIPOTESIS, no verdad:
antes de usarlo se verifica pid vivo + puerto respondiendo + identidad.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

_RAIZ = Path(__file__).resolve().parent.parent  # cognia_v2/


class SummonerError(RuntimeError):
    """Fallo visible del summoner. Siempre precedido por Degradado + stderr."""


# ---------------------------------------------------------------------------
# Registry declarativo. Puertos 8096-8099 elegidos DISJUNTOS de la oficina
# (identidad.py usa 8088/8090/8092 -- conflicto C3 del plan integrado).
# vram_mib es presupuesto DECLARADO provisional: solo decide eviction antes de
# cargar; la verdad post-carga la da nvidia-smi (el coste se mide, no se
# declara -- aca un numero inflado solo causa una eviction de mas, jamas OOM).
# ---------------------------------------------------------------------------
ROLES = {
    "cerebro": {"tipo": "llama", "puerto": 8080, "script": "servir_modelo.py",
                "args": ["--modelo", "qwythos", "--sin-draft", "--ctx", "32768"],
                "identidad": "qwythos", "vram_mib": 11000, "idle_s": None,
                "espera_s": 240},
    "vlm":     {"tipo": "llama", "puerto": 8081, "script": "servir_vlm.py",
                "args": ["--modelo", "VL-3B"], "identidad": "vl",
                "vram_mib": 3300, "idle_s": 900, "espera_s": 240},
    "imagen":  {"tipo": "job", "puerto": 8096, "worker": "scripts/worker_imagen.py",
                "vram_mib": 12000, "idle_s": 300, "espera_s": 600},
    "tresd":   {"tipo": "presupuesto", "puerto": 8097, "vram_mib": 4000, "idle_s": 300},
    "voces":   {"tipo": "presupuesto", "puerto": 8098, "vram_mib": 3000, "idle_s": 300},
    "musica":  {"tipo": "presupuesto", "puerto": 8099, "vram_mib": 2500, "idle_s": 300},
}

# SOLO celdas MEDIDAS en esta maquina entran aca. El KV por token NO se
# calcula: la formula erro 6x en este mismo modelo. Cada celda exige haber
# pasado el criterio CABE de la escalera (/props n_ctx==N y total_slots==1,
# nvidia-smi < 16311 sin sysmem-fallback, prompt-sonda con tok/s del orden
# del baseline). Celdas q8_0/q4_0: fase 2, correr la escalera primero.
# Celdas MEDIDAS en esta maquina (escalera 2026-08-09, --fit off, sonda de
# aguja con 33k de prefill real y VRAM base limpia <500 MiB por peldano):
# q8_0 muere arriba de 524k (655k decodifica a 654s = sysmem fallback; 786k
# crashea en runtime); q4_0 llega al MILLON (1.010.176 = 1M alineado a 256)
# a velocidad sana (16.0s, identica a 262k). Calidad de recuerdo a
# profundidad >500k: sin medir (la sonda ejercita 33k).
ESCALERA_CTX = [
    {"n_ctx": 32768,   "cache": "f16",  "vram_mib": None,  "medida": "default flota"},
    {"n_ctx": 200192,  "cache": "f16",  "vram_mib": 12852, "medida": "2026-08-02 prompt 140k HTTP 200 49s"},
    {"n_ctx": 262144,  "cache": "q8_0", "vram_mib": 11621, "medida": "2026-08-09 sonda 16.9s aguja OK"},
    {"n_ctx": 524288,  "cache": "q8_0", "vram_mib": 15595, "medida": "2026-08-09 sonda 16.8s aguja OK (techo q8)"},
    {"n_ctx": 786432,  "cache": "q4_0", "vram_mib": 15788, "medida": "2026-08-09 sonda 15.2s aguja OK"},
    {"n_ctx": 1010176, "cache": "q4_0", "vram_mib": 15778, "medida": "2026-08-09 sonda 16.0s aguja OK (1M)"},
]

_MARGEN_MIB = 512   # colchon para no rozar el techo de la GPU


# ---------------------------------------------------------------------------
# Seams inyectables (los tests las monkeypatchean; produccion las usa tal cual)
# ---------------------------------------------------------------------------

def _ahora() -> float:
    return time.time()


def _dormir(seg: float) -> None:
    time.sleep(seg)


def _url(puerto: int) -> str:
    return f"http://127.0.0.1:{puerto}"


def _salud(puerto: int, timeout: float = 3.0) -> tuple[Optional[int], Optional[dict]]:
    """GET /health -> (status, cuerpo_json|None). (None, None) si no responde.

    POR QUE devuelve el codigo crudo: llama-server responde 503 DURANTE la
    carga del modelo; confundirlo con 'muerto' y relanzar duplica el proceso
    y provoca OOM (riesgo conocido)."""
    import urllib.request
    import urllib.error
    try:
        with urllib.request.urlopen(_url(puerto) + "/health", timeout=timeout) as r:
            try:
                cuerpo = json.loads(r.read().decode("utf-8", errors="replace"))
            except Exception:
                cuerpo = None
            return r.status, cuerpo
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception:
        return None, None


def _total_slots(url: str) -> Optional[int]:
    """GET /props -> total_slots. POR QUE: backend_activo.props() no expone
    slots, y una build que ignora --parallel 1 reparte el contexto entre 4
    slots y sirve HTTP 500 silenciosos en prompts largos (medido 2026-07-28)."""
    import urllib.request
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/props", timeout=5) as r:
            return json.loads(r.read().decode("utf-8", errors="replace")).get("total_slots")
    except Exception:
        return None


def _pid_vivo(pid: int) -> bool:
    """Un PID guardado es hipotesis: verificarlo antes de usarlo o matarlo."""
    if not pid:
        return False
    if sys.platform == "win32":
        try:
            salida = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True, text=True, errors="replace",
                timeout=10).stdout
            return str(pid) in salida
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _pid_dueno_del_puerto(pid: int, puerto: int) -> Optional[bool]:
    """True/False si se pudo confirmar quien escucha el puerto; None si no se
    pudo determinar (puerto sin listener, netstat fallo). POR QUE: si otro
    proceso tomo el puerto tras un taskkill global del dueno, matar el PID
    guardado mataria a un inocente."""
    try:
        if sys.platform == "win32":
            salida = subprocess.run(["netstat", "-ano"], capture_output=True,
                                    text=True, errors="replace",
                                    timeout=15).stdout
            for linea in salida.splitlines():
                if f":{puerto} " in linea and "LISTENING" in linea.upper():
                    return linea.split()[-1] == str(pid)
            return None
        return None  # POSIX: sin lsof garantizado; no confirmamos
    except Exception:
        return None


def _cmd_kill(pid: int) -> list[str]:
    """Comando de kill SELECTIVO. PROHIBIDO /IM: ese martillo global vive solo
    en flota.parar() y mata al VLM cuando querias reciclar el cerebro."""
    if sys.platform == "win32":
        return ["taskkill", "/PID", str(pid), "/F"]
    return ["kill", "-TERM", str(pid)]


def _matar_pid(pid: int) -> None:
    try:
        subprocess.run(_cmd_kill(pid), capture_output=True, timeout=15)
    except Exception as e:
        print(f"[summoner] kill de pid {pid} fallo: {e}", file=sys.stderr)


def _post_apagar(puerto: int) -> bool:
    """POST /apagar a un worker job (salida limpia antes del kill)."""
    import urllib.request
    try:
        req = urllib.request.Request(_url(puerto) + "/apagar", data=b"{}",
                                     headers={"Content-Type": "application/json"},
                                     method="POST")
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


def _post_job(puerto: int, payload: dict, timeout: float) -> dict:
    import urllib.request
    datos = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(_url(puerto) + "/job", data=datos,
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", errors="replace"))
    except Exception as e:
        return {"ok": False, "error": f"POST /job fallo: {e}"}


def _gpu_python() -> str:
    """Python CON torch/CUDA para los workers. Import perezoso de gpu_env
    (modulo del agente A3, puede no estar en ola 1) con fallback a la misma
    convencion: COGNIA_GPU_PYTHON (flag EXISTENTE de pulidor.py) o venv312gpu."""
    try:
        from cognia.gpu_env import gpu_python
        return gpu_python()
    except ImportError:
        env = os.environ.get("COGNIA_GPU_PYTHON", "").strip()
        if env:
            return env
        return str(_RAIZ / "venv312gpu" / "Scripts" / "python.exe")


# ---------------------------------------------------------------------------
# Eventos: degradacion SIEMPRE visible (bus + stderr), jamas silenciosa
# ---------------------------------------------------------------------------

def _emitir(evento) -> None:
    try:
        from cognia.ux import events
        events.emitir(evento)
    except Exception:
        pass


def _avisar(texto: str) -> None:
    print(f"[summoner] {texto}", file=sys.stderr)
    try:
        from cognia.ux import events
        _emitir(events.Aviso(texto=texto, origen="summoner"))
    except Exception:
        pass


def _fallar(motivo: str, accion: str = ""):
    """Degradado al bus + print + SummonerError. El triple canal es la regla
    de la casa: el modo de fallo historico de Cognia es el vacio silencioso."""
    print(f"[summoner] DEGRADADO: {motivo}"
          + (f" -> {accion}" if accion else ""), file=sys.stderr)
    try:
        from cognia.ux import events
        _emitir(events.Degradado(donde="summoner", motivo=motivo,
                                 accion_sugerida=accion))
    except Exception:
        pass
    raise SummonerError(motivo)


# ---------------------------------------------------------------------------
# Estado persistido (atomico)
# ---------------------------------------------------------------------------

def _ruta_estado() -> Path:
    env = os.environ.get("COGNIA_SUMMONER_STATE", "").strip()
    if env:
        return Path(env)
    return Path.home() / ".cognia" / "summoner.json"


def _dir_logs() -> Path:
    d = Path.home() / ".cognia" / "summoner"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _leer_estado() -> dict:
    ruta = _ruta_estado()
    try:
        crudo = json.loads(ruta.read_text(encoding="utf-8"))
        if isinstance(crudo, dict) and isinstance(crudo.get("roles"), dict):
            return crudo
        print(f"[summoner] estado corrupto en {ruta}; arranco limpio",
              file=sys.stderr)
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"[summoner] estado ilegible ({e}); arranco limpio", file=sys.stderr)
    return {"version": 1, "roles": {}}


def _guardar_estado(estado: dict) -> None:
    """tmp + os.replace: un summoner.json a medias tras un corte de luz es
    peor que ninguno (PIDs fantasma que matarian inocentes)."""
    ruta = _ruta_estado()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(".tmp")
    tmp.write_text(json.dumps(estado, indent=1), encoding="utf-8")
    os.replace(tmp, ruta)


# ---------------------------------------------------------------------------
# Helpers puros (testeables sin GPU)
# ---------------------------------------------------------------------------

def _pad256(n: int) -> int:
    """llama-server paddea n_ctx a multiplo de 256; pedir 200000 deja el aviso
    falso 'adopted 200192 != expected 200000'. Se paddea ANTES de comparar."""
    return ((int(n) + 255) // 256) * 256


def _celda_para(n_ctx_objetivo: int, escalera: list, cache: str = "") -> Optional[dict]:
    """La MENOR celda medida con n_ctx >= objetivo (y cache exacto si se
    pidio). None si no hay: el caller debe negarse a lanzar (jamas extrapolar)."""
    candidatas = [c for c in escalera
                  if c["n_ctx"] >= n_ctx_objetivo
                  and (not cache or c["cache"] == cache)]
    if not candidatas:
        return None
    return min(candidatas, key=lambda c: c["n_ctx"])


def _plan_eviccion(vram_libre: int, vram_rol: int, vivos: dict, *,
                   permitir_cerebro: bool = False, ahora: float = 0.0,
                   margen: int = _MARGEN_MIB) -> list[str]:
    """Que liberar (en orden) para que quepa vram_rol. Funcion PURA.

    Orden de sacrificio: reservas presupuesto (borrar la reserva no mata
    nada) -> jobs con idle vencido -> jobs vivos -> vlm -> cerebro SOLO si el
    caller lo permitio (ensure directo jamas mata al cerebro por su cuenta;
    solo invocar() evicta con restore). Si ni liberando todo alcanza, el plan
    devuelve todos los candidatos: el caller recomputa la cobertura y falla
    VISIBLE con el deficit exacto (ver ensure)."""
    faltan = vram_rol + margen - vram_libre
    if faltan <= 0:
        return []
    grupos: list[list[str]] = [[], [], [], [], []]
    for rol, info in vivos.items():
        spec = ROLES.get(rol) or {}
        tipo = spec.get("tipo", "")
        if info.get("reserva") or tipo == "presupuesto":
            grupos[0].append(rol)
        elif tipo == "job":
            idle = spec.get("idle_s")
            vencido = (idle is not None and ahora > 0
                       and ahora - float(info.get("ultima") or 0) > idle)
            grupos[1 if vencido else 2].append(rol)
        elif rol == "vlm":
            grupos[3].append(rol)
        elif rol == "cerebro" and permitir_cerebro:
            grupos[4].append(rol)
    plan: list[str] = []
    for grupo in grupos:
        for rol in grupo:
            if faltan <= 0:
                break
            plan.append(rol)
            faltan -= int(ROLES.get(rol, {}).get("vram_mib") or 0)
    return plan


def _vram_de_plan(plan: list[str]) -> int:
    return sum(int(ROLES.get(r, {}).get("vram_mib") or 0) for r in plan)


def _n_ctx_de_args(args: list[str]) -> int:
    try:
        return int(args[args.index("--ctx") + 1])
    except (ValueError, IndexError):
        return 0


def _idle_s(rol: str) -> Optional[float]:
    """idle_s efectivo con overrides de entorno (leidos a call-time)."""
    spec = ROLES.get(rol) or {}
    base = spec.get("idle_s")
    if base is None:
        return None    # el cerebro JAMAS se duerme solo (backend_audit no ve
                       # trafico directo: un idle mataria corridas ajenas)
    env = ""
    if rol == "vlm":
        env = os.environ.get("COGNIA_SUMMONER_IDLE_VLM", "")
    elif spec.get("tipo") in ("job", "presupuesto"):
        env = os.environ.get("COGNIA_SUMMONER_IDLE_JOB", "")
    try:
        return float(env) if env.strip() else float(base)
    except ValueError:
        return float(base)


# ---------------------------------------------------------------------------
# VRAM
# ---------------------------------------------------------------------------

def vram_mib() -> tuple[int, int]:
    """(usada, total) en MiB via nvidia-smi; (-1, -1) si falla (visible)."""
    try:
        salida = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, errors="replace",
            timeout=15).stdout.strip()
        usada, total = salida.splitlines()[0].split(",")
        return int(usada.strip()), int(total.strip())
    except Exception as e:
        print(f"[summoner] nvidia-smi no disponible: {e}", file=sys.stderr)
        return -1, -1


def _reservas_mib(estado: dict, salvo: str = "") -> int:
    """VRAM comprometida por reservas presupuesto (nvidia-smi NO las ve)."""
    total = 0
    for rol, info in estado.get("roles", {}).items():
        if rol != salvo and info.get("reserva"):
            total += int(info.get("vram_mib") or ROLES.get(rol, {}).get("vram_mib") or 0)
    return total


def cabe(rol: str, *, con_cerebro: bool = True) -> tuple[bool, str]:
    """(ok, motivo). Con con_cerebro=False simula la VRAM que soltaria evictar
    el cerebro (presupuesto declarado; la verdad la da el poll post-kill)."""
    spec = ROLES.get(rol)
    if spec is None:
        return False, f"rol desconocido '{rol}' (validos: {sorted(ROLES)})"
    usada, total = vram_mib()
    if total < 0:
        return False, "VRAM no medible (nvidia-smi fallo)"
    estado = _leer_estado()
    libre = total - usada - _reservas_mib(estado, salvo=rol)
    if not con_cerebro:
        ent = estado.get("roles", {}).get("cerebro")
        if ent and not ent.get("reserva"):
            libre += int(ROLES["cerebro"]["vram_mib"])
    necesita = int(spec["vram_mib"]) + _MARGEN_MIB
    if necesita <= libre:
        return True, ""
    return False, f"faltan {necesita - libre} MiB para '{rol}' (libres {libre})"


# ---------------------------------------------------------------------------
# Caches que MIENTEN tras (re)lanzar en 8080/8081
# ---------------------------------------------------------------------------

def _invalidar_caches() -> None:
    """Los 3 caches que mienten tras reiniciar un server en el mismo puerto:
    _props_cache de backend_activo, _backend de llm_local y el perfil del
    agente (cachea n_ctx). Cada uno protegido por separado: que uno falle no
    debe dejar los otros dos rancios, y el fallo se IMPRIME."""
    try:
        from cognia import backend_activo
        backend_activo.resetear_cache()
    except Exception as e:
        print(f"[summoner] no invalide backend_activo: {e}", file=sys.stderr)
    try:
        from cognia import llm_local
        llm_local.detectar_backend(forzar=True)
    except Exception as e:
        print(f"[summoner] no invalide llm_local: {e}", file=sys.stderr)
    try:
        from cognia.agent import model_profiles
        model_profiles.perfil_del_agente(forzar=True)
    except Exception as e:
        print(f"[summoner] no invalide model_profiles: {e}", file=sys.stderr)


def _props(url: str) -> dict:
    """backend_activo.props con forzar=True SIEMPRE: /health 200 no es
    'funciona' y el cache por URL miente tras un relanzamiento."""
    from cognia import backend_activo
    return backend_activo.props(url, forzar=True)


# ---------------------------------------------------------------------------
# Lanzamiento (seam mockeable)
# ---------------------------------------------------------------------------

def _lanzar(rol: str, spec: dict, args: list[str]) -> tuple[Optional[int], list[str]]:
    """Lanza el proceso del rol y devuelve (pid, cmd).

    llama: via el script existente (NO duplicar flags de llama-server aca) con
    --pid-file; el script espera el health el mismo y escribe el PID del
    llama-server tras su Popen. job: Popen directo del worker con el python
    GPU; stdout/stderr SIEMPRE a archivo (~/.cognia/summoner/<rol>.log) --
    con DEVNULL, 'murio al arrancar' es indiagnosticable."""
    if spec["tipo"] == "llama":
        pidfile = _dir_logs() / f"{rol}.pid"
        try:
            pidfile.unlink()
        except OSError:
            pass
        cmd = [sys.executable, str(_RAIZ / "scripts" / spec["script"]),
               *args, "--pid-file", str(pidfile)]
        log = (_dir_logs() / f"{rol}.log").open("ab")
        try:
            subprocess.run(cmd, stdout=log, stderr=log,
                           timeout=spec.get("espera_s", 240) + 60)
        finally:
            log.close()
        try:
            return int(pidfile.read_text(encoding="utf-8").strip()), cmd
        except Exception:
            return None, cmd
    # job
    cmd = [_gpu_python(), str(_RAIZ / spec["worker"]),
           "--puerto", str(spec["puerto"])]
    log = (_dir_logs() / f"{rol}.log").open("ab")
    proc = subprocess.Popen(cmd, stdout=log, stderr=log)
    return proc.pid, cmd


def _cola_log(rol: str, n: int = 20) -> str:
    try:
        lineas = (_dir_logs() / f"{rol}.log").read_text(
            encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lineas[-n:])
    except Exception:
        return "(sin log)"


# ---------------------------------------------------------------------------
# API publica
# ---------------------------------------------------------------------------

def tocar(rol: str) -> None:
    """Sella t_ultima del rol (reloj de inactividad). No-op si no esta vivo."""
    estado = _leer_estado()
    if rol in estado["roles"]:
        estado["roles"][rol]["t_ultima"] = _ahora()
        _guardar_estado(estado)


def vivos() -> dict:
    """rol -> {'pid','url','desde','ultima','ocupado','reserva'}. Poda las
    entradas con PID muerto (con Aviso: tolera el taskkill global de flota).
    'ocupado' aqui es False por diseno: la verdad la pide barrido() al /health
    del worker en el momento de decidir (no en cada lectura del estado)."""
    estado = _leer_estado()
    resultado = {}
    sucio = False
    for rol, info in list(estado["roles"].items()):
        if info.get("reserva"):
            resultado[rol] = {"pid": None, "url": None,
                              "desde": info.get("t_arranque"),
                              "ultima": info.get("t_ultima"),
                              "ocupado": False, "reserva": True,
                              "vram_mib": info.get("vram_mib")}
            continue
        pid = info.get("pid")
        if pid and not _pid_vivo(pid):
            _avisar(f"entrada rancia: rol '{rol}' pid {pid} muerto; la limpio")
            del estado["roles"][rol]
            sucio = True
            continue
        resultado[rol] = {"pid": pid, "url": _url(info.get("puerto", 0)),
                          "desde": info.get("t_arranque"),
                          "ultima": info.get("t_ultima"),
                          "ocupado": False, "reserva": False}
    if sucio:
        _guardar_estado(estado)
    return resultado


def barrido(ahora: float = 0.0) -> list[str]:
    """Duerme roles con idle vencido. Corre al inicio de ensure()/invocar()
    (oportunista, sin hilos demonio). Salta workers ocupados (/health con
    ocupado:true): jamas matar a mitad de job. 'ahora' inyectable para tests."""
    ahora = ahora or _ahora()
    dormidos: list[str] = []
    for rol, info in vivos().items():
        idle = _idle_s(rol)
        if idle is None:
            continue
        ultima = float(info.get("ultima") or 0)
        if ahora - ultima <= idle:
            continue
        if not info.get("reserva"):
            spec = ROLES.get(rol) or {}
            if spec.get("tipo") == "job":
                _codigo, cuerpo = _salud(spec["puerto"])
                if isinstance(cuerpo, dict) and cuerpo.get("ocupado"):
                    continue
        if liberar(rol):
            _avisar(f"rol '{rol}' dormido por inactividad "
                    f"({int(ahora - ultima)}s > {int(idle)}s)")
            dormidos.append(rol)
    return dormidos


def liberar(rol: str) -> bool:
    """Duerme un rol por PID guardado. PROHIBIDO taskkill /IM (ese martillo
    global vive solo en flota.parar). Presupuesto: borra la reserva y listo."""
    estado = _leer_estado()
    entrada = estado["roles"].get(rol)
    if entrada is None:
        print(f"[summoner] '{rol}' ya estaba dormido", file=sys.stderr)
        return False
    if entrada.get("reserva"):
        del estado["roles"][rol]
        _guardar_estado(estado)
        return True
    pid = entrada.get("pid")
    puerto = entrada.get("puerto") or ROLES.get(rol, {}).get("puerto", 0)
    if pid and _pid_vivo(pid):
        dueno = _pid_dueno_del_puerto(pid, puerto)
        if dueno is False:
            # otro proceso tomo el puerto: matar el PID guardado seria matar
            # a ciegas -- limpiar la entrada y avisar, NO matar
            _avisar(f"puerto :{puerto} ya no es de pid {pid}; limpio la "
                    f"entrada de '{rol}' sin matar")
            del estado["roles"][rol]
            _guardar_estado(estado)
            return False
        if ROLES.get(rol, {}).get("tipo") == "job":
            _post_apagar(puerto)   # salida limpia; el kill queda de fallback
            _dormir(0.5)
        if _pid_vivo(pid):
            _matar_pid(pid)
        # poll acotado por ITERACIONES, no por reloj: con un reloj congelado
        # (tests) un while sobre _ahora() no termina jamas
        for _ in range(10):
            if _salud(puerto)[0] is None:
                break
            _dormir(1)
    del estado["roles"][rol]
    _guardar_estado(estado)
    if rol in ("cerebro", "vlm"):
        _invalidar_caches()   # que no quede un perfil rancio apuntando al muerto
    return True


def liberar_todo() -> int:
    n = 0
    for rol in list(_leer_estado()["roles"]):
        if liberar(rol):
            n += 1
    return n


def _ensure_presupuesto(rol: str, spec: dict, evictar: bool) -> dict:
    """Rol sin proceso: chequeo VRAM + eviction si hace falta + reserva en el
    estado. El CLI one-shot (clonacion, symphonygen, triposr) corre por fuera;
    la reserva evita que dos pedidos GPU se pisen."""
    usada, total = vram_mib()
    estado = _leer_estado()
    if total < 0:
        _avisar(f"VRAM no medible; anoto la reserva de '{rol}' SIN verificar")
    else:
        libre = total - usada - _reservas_mib(estado, salvo=rol)
        if int(spec["vram_mib"]) + _MARGEN_MIB > libre:
            plan = _plan_eviccion(libre, int(spec["vram_mib"]), vivos(),
                                  permitir_cerebro=evictar, ahora=_ahora())
            if libre + _vram_de_plan(plan) < int(spec["vram_mib"]) + _MARGEN_MIB:
                deficit = int(spec["vram_mib"]) + _MARGEN_MIB - libre - _vram_de_plan(plan)
                _fallar(f"no cabe '{rol}': faltan {deficit} MiB aun liberando todo",
                        "cognia flota parar / summoner.liberar('<rol>')")
            for victima in plan:
                liberar(victima)
    ahora = _ahora()
    estado = _leer_estado()
    estado["roles"][rol] = {"reserva": True, "vram_mib": int(spec["vram_mib"]),
                            "puerto": spec["puerto"],
                            "t_arranque": ahora, "t_ultima": ahora}
    _guardar_estado(estado)
    return {"ok": True, "rol": rol, "url": None, "pid": None,
            "modelo": None, "n_ctx": None, "arranque_frio": False}


def ensure(rol: str, *, ctx: int = 0, timeout_s: int = 0,
           evictar: bool = False, _cache: str = "") -> dict:
    """Garantiza el rol servido y VERIFICADO. Devuelve
    {'ok': True, 'rol', 'url'|None, 'pid'|None, 'modelo', 'n_ctx',
     'arranque_frio'} o levanta SummonerError (tras Degradado + stderr).

    POR QUE tanto postcheck: /health 200 no es 'funciona'. La identidad se
    verifica con /props forzar=True (los caches mienten tras relanzar en el
    mismo puerto); para el cerebro ademas total_slots==1 (builds que ignoran
    --parallel 1 sirven HTTP 500 silenciosos) y n_ctx EXACTO al pedido.

    _cache es privado (lo usa escalar_ctx para --ctk/--ctv); la API publica
    congelada no cambia."""
    barrido(_ahora())
    spec = ROLES.get(rol)
    if spec is None:
        _fallar(f"rol desconocido '{rol}'; validos: {sorted(ROLES)}")
    if spec["tipo"] == "presupuesto":
        return _ensure_presupuesto(rol, spec, evictar)

    puerto = spec["puerto"]
    url = _url(puerto)
    estado = _leer_estado()
    entrada = estado["roles"].get(rol) or {}

    # --- salud actual: ya vivo? ---
    codigo, cuerpo = _salud(puerto)
    arranque_frio = False
    pid = entrada.get("pid")

    if codigo == 200:
        if spec["tipo"] == "llama":
            props = _props(url)
            modelo = str(props.get("modelo") or "").lower()
            if spec["identidad"] in modelo:
                tocar(rol)
                return {"ok": True, "rol": rol, "url": url, "pid": pid,
                        "modelo": props.get("modelo"),
                        "n_ctx": props.get("n_ctx"), "arranque_frio": False}
            if evictar and pid and _pid_vivo(pid):
                # el dueno registrado somos nosotros pero la identidad cambio:
                # liberar selectivo y relanzar de cero (una sola recursion)
                liberar(rol)
                return ensure(rol, ctx=ctx, timeout_s=timeout_s,
                              evictar=False, _cache=_cache)
            else:
                _fallar(f"en :{puerto} vive '{props.get('modelo')}' y no "
                        f"'{spec['identidad']}'; no mato lo ajeno en silencio",
                        "cognia flota parar")
        else:  # job sano
            if isinstance(cuerpo, dict) and cuerpo.get("ok"):
                tocar(rol)
                return {"ok": True, "rol": rol, "url": url, "pid": pid,
                        "modelo": None, "n_ctx": None, "arranque_frio": False}
            _fallar(f"worker '{rol}' responde /health sin ok=true: {cuerpo}")
    elif codigo == 503:
        # llama-server responde 503 DURANTE la carga: NO relanzar (doble
        # proceso = OOM); solo esperar abajo.
        pass
    else:
        # --- no responde: hay que lanzar. Primero VRAM. ---
        entrada_pid = entrada.get("pid")
        if entrada_pid and not _pid_vivo(entrada_pid):
            _avisar(f"entrada rancia de '{rol}' (pid {entrada_pid} muerto); la limpio")
            estado = _leer_estado()
            estado["roles"].pop(rol, None)
            _guardar_estado(estado)
        usada, total = vram_mib()
        if total < 0:
            _avisar(f"VRAM no medible; lanzo '{rol}' sin presupuesto verificado")
        else:
            libre = total - usada - _reservas_mib(_leer_estado(), salvo=rol)
            if int(spec["vram_mib"]) + _MARGEN_MIB > libre:
                plan = _plan_eviccion(libre, int(spec["vram_mib"]), vivos(),
                                      permitir_cerebro=evictar, ahora=_ahora())
                if libre + _vram_de_plan(plan) < int(spec["vram_mib"]) + _MARGEN_MIB:
                    deficit = (int(spec["vram_mib"]) + _MARGEN_MIB
                               - libre - _vram_de_plan(plan))
                    _fallar(f"no cabe '{rol}': faltan {deficit} MiB aun con eviccion",
                            "cognia flota parar / summoner.liberar('<rol>')")
                for victima in plan:
                    liberar(victima)
                if plan and total > 0:
                    _esperar_vram_libre(int(spec["vram_mib"]) + _MARGEN_MIB)
        # --- lanzar ---
        args = list(spec.get("args") or [])
        n_ctx_pedido = 0
        if spec["tipo"] == "llama":
            if rol == "cerebro" and ctx > 0:
                args = ["--modelo", "qwythos", "--sin-draft", "--ctx", str(ctx)]
                if _cache and _cache != "f16":
                    args += ["--ctk", _cache, "--ctv", _cache]
                # b10066 defaultea --fit on y auto-reduce EN SILENCIO: mejor
                # que falle visible a que se auto-ajuste el contexto pedido
                args += ["--fit-off"]
                n_ctx_pedido = ctx
            else:
                n_ctx_pedido = _n_ctx_de_args(args)
        pid, cmd = _lanzar(rol, spec, args)
        if pid is None:
            _fallar(f"'{rol}' no dejo PID tras el lanzamiento; ultimas lineas:\n"
                    + _cola_log(rol))
        arranque_frio = True
        ahora = _ahora()
        estado = _leer_estado()
        estado["roles"][rol] = {"pid": pid, "puerto": puerto,
                                "t_arranque": ahora, "t_ultima": ahora,
                                "modelo": "", "n_ctx": n_ctx_pedido,
                                "cache": _cache or "f16", "cmd": cmd}
        _guardar_estado(estado)

    # --- esperar salud (cubre tambien el 503 = cargando) ---
    espera = timeout_s or spec.get("espera_s", 240)
    inicio = _ahora()
    while True:
        codigo, cuerpo = _salud(puerto)
        if codigo == 200:
            break
        if codigo != 503 and pid and not _pid_vivo(pid):
            _fallar(f"'{rol}' murio al arrancar (cabe en la GPU?); ultimas "
                    f"lineas del log:\n" + _cola_log(rol))
        if _ahora() - inicio > espera:
            liberar(rol)
            _fallar(f"'{rol}' no dio /health 200 en {espera}s; lo libere")
        _dormir(2)

    # --- postcondiciones: cargar no es funcionar ---
    modelo_srv = None
    n_ctx_srv = None
    if spec["tipo"] == "llama":
        props = _props(url)
        modelo_srv = props.get("modelo")
        n_ctx_srv = props.get("n_ctx")
        if spec["identidad"] not in str(modelo_srv or "").lower():
            _fallar(f"postcheck: en :{puerto} quedo '{modelo_srv}' y no "
                    f"'{spec['identidad']}'")
        if rol == "cerebro":
            slots = _total_slots(url)
            if slots is not None and slots != 1:
                liberar(rol)
                _fallar(f"postcheck: el server reparte el contexto entre "
                        f"{slots} slots (ignoro --parallel 1); lo libere")
            n_ctx_esperado = ctx or _n_ctx_de_args(list(spec.get("args") or []))
            if arranque_frio and n_ctx_esperado and n_ctx_srv != n_ctx_esperado:
                liberar(rol)
                _fallar(f"postcheck: n_ctx {n_ctx_srv} != pedido "
                        f"{n_ctx_esperado} (fit silencioso?); lo libere")
    else:  # job
        if not (isinstance(cuerpo, dict) and cuerpo.get("ok")):
            _fallar(f"worker '{rol}' dio /health 200 sin ok=true: {cuerpo}")

    if arranque_frio and puerto in (8080, 8081):
        _invalidar_caches()
    tocar(rol)
    return {"ok": True, "rol": rol, "url": url, "pid": pid,
            "modelo": modelo_srv, "n_ctx": n_ctx_srv,
            "arranque_frio": arranque_frio}


def _esperar_vram_libre(mib_objetivo: int, tope_s: float = 30.0) -> None:
    """WDDM tarda en devolver la VRAM tras un kill: poll hasta que el objetivo
    quepa o venza el tope (entonces se sigue: el lanzamiento fallara visible).
    Acotado por iteraciones (no por reloj) para no colgar con reloj congelado."""
    for _ in range(max(1, int(tope_s))):
        usada, total = vram_mib()
        if total < 0 or total - usada >= mib_objetivo:
            return
        _dormir(1)


def _cerebro_vivo() -> bool:
    return _salud(ROLES["cerebro"]["puerto"])[0] in (200, 503)


def invocar(rol: str, payload: dict, *, timeout_s: int = 0) -> dict:
    """Job pesado con eviction temporal del cerebro y auto-restore ANTES de
    retornar: el tool call vive dentro del bucle del agente y la siguiente
    request va al cerebro. Se ASUME re-prefill: el KV se perdio (49s medidos
    para 140k tokens es el peor caso; a 32k son segundos).

    -> {'ok', 'resultado': dict, 'evicto_cerebro': bool}. Si el restore falla,
    SummonerError que INCLUYE la ruta del artefacto ya escrito (el resultado
    no se pierde: esta en disco). Devolver un loop sin cerebro 'como si nada'
    seria la degradacion silenciosa exacta que este repo prohibe."""
    barrido(_ahora())
    spec = ROLES.get(rol)
    if spec is None:
        _fallar(f"rol desconocido '{rol}'; validos: {sorted(ROLES)}")
    if spec["tipo"] != "job":
        _fallar(f"invocar() es solo para roles tipo job; '{rol}' es "
                f"'{spec['tipo']}'")

    necesita_eviccion = (not cabe(rol, con_cerebro=True)[0]) and _cerebro_vivo()
    if necesita_eviccion and os.environ.get("COGNIA_SUMMONER_EVICT", "1").strip() == "0":
        _fallar(f"'{rol}' no cabe con el cerebro residente y la eviccion esta "
                f"apagada (COGNIA_SUMMONER_EVICT=0)",
                "liberar('cerebro') a mano o COGNIA_SUMMONER_EVICT=1")

    foto = {}
    if necesita_eviccion:
        foto = _props(_url(ROLES["cerebro"]["puerto"])) or {}
        liberar("cerebro")
        _esperar_vram_libre(int(spec["vram_mib"]) + _MARGEN_MIB)

    ensure(rol)
    r = _post_job(spec["puerto"], payload, float(timeout_s or 900))
    tocar(rol)

    if necesita_eviccion:
        # el cerebro necesita la VRAM YA: no esperar al barrido
        liberar(rol)
        try:
            ensure("cerebro", ctx=int(foto.get("n_ctx") or 0))
        except Exception as e:
            ruta = r.get("ruta", "(sin ruta)")
            _fallar(f"cerebro NO restaurado tras job '{rol}': {e}; el "
                    f"artefacto sobrevive en {ruta}",
                    "cognia flota arrancar")
    return {"ok": bool(r.get("ok")), "resultado": r,
            "evicto_cerebro": necesita_eviccion}


def escalar_ctx(n_ctx_objetivo: int, *, cache: str = "") -> dict:
    """Relanza el cerebro a una celda MEDIDA de ESCALERA_CTX. Se niega a
    lanzar a un n_ctx no verificado (la formula de KV erro 6x en este modelo:
    correr la escalera es la unica fuente de celdas). Con --fit-off: b10066
    auto-reduce en silencio y falsearia el techo."""
    objetivo = _pad256(n_ctx_objetivo)
    url = _url(ROLES["cerebro"]["puerto"])
    actual = _props(url)
    n_actual = actual.get("n_ctx") or 0
    if n_actual >= objetivo and (not cache or _cache_actual() == cache):
        return {"ok": True, "n_ctx": n_actual, "cache": _cache_actual(),
                "relanzado": False}
    # Default = la celda mas grande MEDIDA de la escalera (2026-08-09: 1M
    # con KV q4_0 paso la sonda limpio); COGNIA_CTX_MAX lo acota.
    ctx_max = int(os.environ.get("COGNIA_CTX_MAX", "1010176"))
    celda = _celda_para(min(objetivo, ctx_max), ESCALERA_CTX, cache)
    if celda is None:
        _fallar(f"n_ctx {objetivo} (cache '{cache or 'cualquiera'}') no esta "
                f"medido: corre la escalera y agrega la celda a ESCALERA_CTX; "
                f"jamas se lanza a un contexto no verificado")
    if _salud(ROLES["cerebro"]["puerto"])[0] is not None:
        liberar("cerebro")
    r = ensure("cerebro", ctx=int(celda["n_ctx"]), _cache=celda["cache"])
    return {"ok": True, "n_ctx": int(celda["n_ctx"]),
            "cache": celda["cache"], "relanzado": True,
            "pid": r.get("pid")}


def _cache_actual() -> str:
    entrada = _leer_estado()["roles"].get("cerebro") or {}
    return entrada.get("cache", "f16")


def estado_roles() -> dict[str, str]:
    """rol -> linea legible ASCII (la consola del dueno es cp1252). La consume
    flota.estado() en ola 2 con import protegido."""
    estado = _leer_estado()
    ahora = _ahora()
    salida: dict[str, str] = {}
    for rol, spec in ROLES.items():
        info = estado["roles"].get(rol)
        if info is None:
            salida[rol] = ("dormido (presupuesto)"
                           if spec["tipo"] == "presupuesto" else "dormido")
            continue
        if info.get("reserva"):
            salida[rol] = (f"reserva {info.get('vram_mib')} MiB :"
                           f"{info.get('puerto')}")
            continue
        pid = info.get("pid")
        if pid and not _pid_vivo(pid):
            salida[rol] = f"rancio (pid {pid} muerto)"
            continue
        idle = _idle_s(rol)
        if idle is None:
            resto = "sin idle"
        else:
            resto = f"idle en {max(0, int(idle - (ahora - float(info.get('t_ultima') or 0))))}s"
        salida[rol] = (f"VIVO pid={pid} :{info.get('puerto')} "
                       f"{info.get('modelo') or ''} ({resto})").replace("  ", " ")
    return salida
