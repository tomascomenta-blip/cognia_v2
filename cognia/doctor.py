"""
cognia/doctor.py
================
Cognia diagnostics, as an IMPORTABLE package module so `/doctor` works both from
the repo and from a pip-installed wheel (the old scripts/cognia_doctor.py was not
shipped in the package, so the installed CLI crashed). Run via `cognia.doctor.run_all`.

Checks: Python version, required/optional packages, Ollama, config, DB, shards,
and a warm inference speed measurement when local shards are present.
"""

from __future__ import annotations

import importlib
import json
import os
import re
import sys
import urllib.request

# Installed CLI has no "repo root"; use the current working directory for the
# file-presence checks (.env / db / model_shards), which are advisory anyway.
_ROOT = os.getcwd()

_REQUIRED_PACKAGES = [
    "fastapi", "uvicorn", "numpy", "requests", "pydantic", "cryptography",
]

_OPTIONAL_PACKAGES = [
    ("sentence_transformers", "mejores embeddings — pip install sentence-transformers"),
    ("numba", "kernels JIT mas rapidos — pip install numba"),
]


def _line(tag: str, label: str, detail: str = "") -> None:
    text = f"  {tag}  {label}"
    if detail:
        text += f"  -- {detail}"
    print(text)


def _ok(label: str, detail: str = "") -> bool:
    _line("[OK]  ", label, detail)
    return True


def _fail(label: str, detail: str = "") -> bool:
    _line("[FAIL]", label, detail)
    return False


def _warn(label: str, detail: str = "") -> bool:
    _line("[WARN]", label, detail)
    return True


def check_python() -> bool:
    major, minor = sys.version_info[:2]
    ver = f"{major}.{minor}"
    if (major, minor) >= (3, 11):
        return _ok(f"Python {ver}")
    return _fail(f"Python {ver}", "se requiere 3.11+")


def check_packages() -> bool:
    all_ok = True
    for pkg in _REQUIRED_PACKAGES:
        try:
            importlib.import_module(pkg)
            _ok(f"  {pkg}")
        except ImportError:
            _fail(f"  {pkg}", "falta -- pip install -U cognia-ai")
            all_ok = False
    for pkg, hint in _OPTIONAL_PACKAGES:
        try:
            importlib.import_module(pkg)
            _ok(f"  {pkg} (opcional)")
        except ImportError:
            _warn(f"  {pkg} (opcional)", hint)
    return all_ok


def check_gguf() -> bool:
    """Backend REAL de produccion: llama-server + GGUF (cognia install-model)."""
    gguf = None
    try:
        from node.llama_backend import _find_gguf
        gguf = _find_gguf()
    except Exception:
        pass
    if gguf is None:
        return _warn("Backend GGUF no encontrado",
                     "instala el stack recomendado con: cognia install-model")
    _ok(f"GGUF: {gguf}")
    server = os.environ.get("LLAMA_SERVER_PATH", "")
    if server and os.path.isfile(server):
        return _ok(f"llama-server: {server}")
    return _ok("llama-server", "no fijado en config.env (se resuelve on-demand)")


def check_ollama() -> bool:
    url = os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/")
    try:
        req = urllib.request.urlopen(f"{url}/api/tags", timeout=3)
        if req.status != 200:
            return _warn("Ollama", f"estado inesperado {req.status}")
        # Un 200 en /api/tags no garantiza nada: cualquier otro servicio en el
        # 11434 tambien responde 200, y un Ollama SIN modelos instalados da
        # tags vacio mientras /api/generate devuelve 404 (auditoria
        # 2026-08-01). Se valida el JSON y que haya al menos un modelo.
        try:
            data = json.loads(req.read().decode("utf-8", errors="replace"))
            models = data.get("models")
        except Exception:
            models = None
        if not isinstance(models, list):
            return _warn("Ollama", f"{url}/api/tags responde 200 pero sin JSON "
                         "de modelos (otro servicio en ese puerto?)")
        if not models:
            return _warn("Ollama sin modelos instalados",
                         "ollama pull <modelo> para usarlo como fallback")
        nombres = ", ".join(str(m.get("name", "?")) for m in models[:3])
        return _ok(f"Ollama corriendo en {url}", f"modelos: {nombres}")
    except Exception:
        return _warn("Ollama no disponible (opcional)",
                     "el backend principal es llama-server+GGUF; Ollama es solo fallback")


def check_llm_backend() -> bool:
    """
    Lo unico que decide si Cognia puede pensar: que haya un LLM al que hablar.

    POR QUE HACIA FALTA: el doctor comprobaba Ollama (opcional), los shards en
    disco y la velocidad de inferencia, y terminaba con "Todo en orden" sin
    haber verificado nunca que se pudiera generar una sola palabra. Medido el
    2026-07-20 en esta maquina: Ollama no existe, los shards estaban en disco
    pero el orquestador los daba por no disponibles, la prueba de velocidad se
    omitia... y aun asi el diagnostico salia en verde. El backend que SI
    funcionaba, un llama-server en el 8080, no se miraba en ningun sitio.

    Se prueba generando de verdad, no solo sondeando el puerto: un servidor que
    acepta conexiones pero no tiene modelo cargado responderia al ping igual.
    """
    try:
        from cognia.llm_local import detectar_backend, generar
    except Exception as exc:
        return _warn("Backend LLM", f"no se pudo importar llm_local: {exc}")

    backend = detectar_backend(forzar=True)
    if not backend:
        # FAIL, no WARN: sin backend Cognia no puede pensar, y _warn devuelve
        # True, con lo que el diagnostico seguiria terminando en "Todo en
        # orden" — que es exactamente el mensaje enganoso que esto viene a
        # corregir.
        return _fail(
            "Backend LLM no disponible",
            "arrancalo con: python scripts/servir_modelo.py  "
            "(o fija COGNIA_LLM_URL). Sin esto Cognia degrada a sus "
            "fallbacks en silencio")

    # Presupuesto por perfil (11a instancia de la leccion "9 bugs identicos",
    # cazada 2026-08-09 al estrenar la instalacion de PyPI): con un razonador
    # (gpt-oss-20b) max_tokens=8 se va ENTERO en pensamiento, el contenido
    # llega vacio y el doctor declaraba [FAIL] "NO genera texto" sobre un
    # backend SANO — mientras check_inference_speed medee 116 tok/s dos
    # lineas mas abajo. Reproducido a mano: 8 tok -> '' ; 1024+low -> 'OK'.
    from cognia.llm_local import (es_razonador_grande, nombre_modelo_servido,
                                  presupuesto_chat)
    _razonador = es_razonador_grande(nombre_modelo_servido())
    respuesta = generar(
        "Responde solo: OK",
        max_tokens=presupuesto_chat(8, _razonador, piso_razonador=1024),
        reasoning_effort="low" if _razonador else None)
    if not respuesta:
        # _fail, no _warn: un server que acepta el sondeo pero no genera es
        # tan inservible como uno apagado, y _warn devuelve True, con lo que
        # el doctor volvia a terminar "Todo en orden" sobre un backend mudo.
        return _fail(f"Backend LLM en {backend['url']}",
                     "responde al sondeo pero NO genera texto "
                     "(modelo sin cargar o colgado)")

    # "genera texto", no "genera OK": este sondeo solo comprueba que la
    # respuesta no esta vacia. Quien verifica el MARCADOR es
    # check_inference_speed; decir aqui "genera OK" afirmaba una verificacion
    # que no se hizo.
    return _ok(f"Backend LLM: {backend['tipo']} en {backend['url']} — genera texto")


def check_env() -> bool:
    cfg = os.path.join(os.path.expanduser("~"), ".cognia", "config.env")
    if os.path.isfile(cfg):
        return _ok("config en ~/.cognia/config.env")
    return _warn("config", "no configurado -- ejecuta: cognia init")


def check_db() -> bool:
    home = os.path.join(os.path.expanduser("~"), ".cognia")
    db_path = os.path.join(home, "cognia_memory.db")
    if os.path.isfile(db_path):
        return _ok("cognia_memory.db encontrada")
    if os.path.isdir(home) or os.access(os.path.expanduser("~"), os.W_OK):
        return _ok("cognia_memory.db", "se crea en el primer uso")
    return _fail("cognia_memory.db", "el directorio no es escribible")


def _shard_dir() -> str:
    # Fuente unica con el orquestador. Tenerlo duplicado era el bug: el doctor
    # reportaba "4 shards INT4 OK" y dos lineas mas abajo "shards no detectados",
    # porque cada uno miraba un sitio distinto.
    from shattering.model_constants import shard_weights_dir
    return shard_weights_dir()


def check_shards() -> bool:
    sd = _shard_dir()
    if not sd:
        return _warn("shards", "ausentes (camino avanzado; el backend principal es GGUF)")
    present = [f for f in os.listdir(sd) if f.startswith("shard_")]
    if present:
        return _ok("shards INT4", f"{len(present)} en {sd}")
    return _warn("shards", f"directorio vacio: {sd}")


def _manifest_path() -> "str | None":
    try:
        import shattering
        base = os.path.join(os.path.dirname(shattering.__file__), "manifests")
        for c in ("cognia_qwen.json", "cognia_desktop.json"):
            p = os.path.join(base, c)
            if os.path.isfile(p):
                return p
    except Exception:
        pass
    return None


# Cuantas veces tiene que aparecer la palabra suelta OK en la respuesta del
# sondeo de inferencia para darlo por bueno (el prompt pide diez).
_OK_MINIMO = 3


def check_inference_speed() -> bool:
    # El install recomendado (GGUF, sin NPZ) tambien se prueba: antes este
    # check se omitia sin shards y el doctor terminaba sin haber verificado
    # inferencia real en una instalacion sana.
    gguf = None
    try:
        from node.llama_backend import _find_gguf
        gguf = _find_gguf()
    except Exception:
        pass
    sd = _shard_dir()
    if not sd and gguf is None:
        return _warn("Inferencia", "sin backend (ni GGUF ni shards) -- "
                     "instala con: cognia install-model")
    manifest = _manifest_path()
    if manifest is None:
        return _warn("Inferencia", "sin manifest -- omitido")
    try:
        import time
        from shattering.orchestrator import ShatteringOrchestrator
        orch = ShatteringOrchestrator(manifest_path=manifest, mode="local")
        if not orch._shards_available() and gguf is None:
            return _warn("Inferencia", "shards no detectados -- omitido")
        if callable(getattr(orch, "_try_load_llama", None)):
            orch._try_load_llama()   # backend GGUF real (patron e2e canonico)
        _ = orch.infer("Hola")  # warm-up (descarta cold start)
        t0 = time.perf_counter()
        # Prompt con marcador VERIFICABLE: antes se pedia "una funcion que
        # sume" y solo se contaban tokens, con lo que la ruta de shards NPZ
        # que genera basura (768 tokens de ruido) salia [OK] con su tok/s
        # medido (auditoria 2026-08-01). Ahora el texto tiene que contener
        # el marcador o el check no aprueba. Se piden varios OK (no uno)
        # para que la medicion de tok/s tenga tokens suficientes.
        result = orch.infer(
            "Repite exactamente la palabra OK diez veces, separadas por espacios.",
            max_tokens=64, temperature=0.0)
        latency_ms = (time.perf_counter() - t0) * 1000
        texto = (getattr(result, "text", "") or "").strip()
        if result.mode != "llama.cpp":
            # No es el backend GGUF real (shards NPZ / simulacion): el numero
            # que salga de aqui no representa la instalacion recomendada.
            return _warn(f"Inferencia via backend={result.mode}",
                         "no es el backend GGUF real; velocidad no representativa")
        # Marcador con FRONTERA DE PALABRA y repetido. Con el `"OK" in
        # texto.upper()` de antes el chequeo seguia siendo un falso PASS: el
        # bigrama "ok" esta dentro de "tokens", "broken" y "look", asi que
        # basura plausible en ingles aprobaba igual (revision adversarial
        # 2026-08-01). Se piden >=3 apariciones de la palabra suelta OK sobre
        # las 10 que pide el prompt: un backend sano las produce y el ruido
        # (CJK, prosa, tokens sueltos) no.
        marcadores = len(re.findall(r"\bOK\b", texto.upper()))
        if marcadores < _OK_MINIMO:
            return _fail("Inferencia genera basura",
                         f"pedido 'OK' x10, {marcadores} OK(s) sueltos en la "
                         f"respuesta: {texto[:60]!r}")
        real_tokens = getattr(result, "tokens_generated", 0) or 0
        if real_tokens > 0 and latency_ms > 0:
            tok_s = real_tokens / latency_ms * 1000
            return _ok(f"Inferencia: {tok_s:.1f} tok/s (warm) | backend={result.mode} | "
                       f"{real_tokens} tok en {latency_ms:.0f}ms | genera OK")
        return _ok(f"Inferencia OK | backend={result.mode} | {latency_ms:.0f}ms")
    except ImportError as e:
        # shattering no instalado: es una dependencia opcional del camino
        # avanzado, no una averia de la instalacion recomendada.
        return _warn("Inferencia omitida", f"falta dependencia: {e}")
    except Exception as e:
        # _fail, no _warn: si el orquestador revienta al generar, la inferencia
        # NO esta verificada, y _warn devuelve True -> el doctor terminaba
        # "Todo en orden" con la inferencia rota (revision adversarial
        # 2026-08-01). Un fallo del sondeo es un fallo del sistema.
        return _fail("Inferencia fallo", f"{type(e).__name__}: {e}")


# La orden EXACTA que arregla la flota apagada: funciona instalado (comando
# del paquete) y en el repo (scripts/servir_flota.py delega en el mismo modulo).
_ORDEN_ARRANCAR = "python -m cognia flota arrancar pensar"


def check_flota() -> bool:
    """Los puertos de la flota por roles, verificados por /props: reporta el
    GGUF REAL que sirve cada puerto y a que combo corresponde.

    POR QUE /props y no /health: un server rancio sirviendo OTRO modelo
    responde /health igual — la averia historica del :8088 (el 7B RETIRADO
    atendiendo el chat mientras la flota estaba apagada, memoria 2026-07-25)
    era invisible para el sondeo por health. Y "flota apagada" es FAIL, no
    WARN: sin cerebro en :8080 Cognia degrada a fallbacks en silencio, y un
    doctor que termina "Todo en orden" sobre eso es el mensaje enganoso que
    este archivo lleva tres auditorias corrigiendo."""
    from cognia import backend_activo
    from cognia.flota import PUERTOS, combo_de_modelo

    estados, cerebro_vivo, problema = [], False, ""
    for puerto, rol in PUERTOS:
        p = backend_activo.props(f"http://127.0.0.1:{puerto}", forzar=True)
        if not p:
            estados.append(f":{puerto} {rol}: no responde")
            continue
        modelo = p.get("modelo") or "desconocido"
        combo = combo_de_modelo(modelo)
        estados.append(f":{puerto} {rol}: {modelo}"
                       + (f" [combo '{combo}']" if combo else ""))
        if puerto != 8080:
            continue
        cerebro_vivo = True
        for retirado in backend_activo.RETIRADOS:
            if retirado in modelo.lower():
                problema = (f"el :8080 sirve {modelo}, RETIRADO por la "
                            f"auditoria de flota 2026-07-24")
        if combo is None and not problema:
            problema = (f"el :8080 sirve {modelo}, que no es el cerebro de "
                        f"ningun combo de la flota (cognia/flota.py)")
    detalle = " | ".join(estados)

    if not cerebro_vivo:
        # FAIL con la orden exacta, no WARN decorativo: _warn devuelve True y
        # el doctor terminaba "Todo en orden" con la flota apagada.
        return _fail("flota apagada (sin cerebro en :8080)",
                     detalle + f" -- arranca con: {_ORDEN_ARRANCAR}")
    if problema:
        # Un modelo rancio/ajeno en :8080 es PEOR que la flota apagada: todo
        # el producto sale de un modelo que nadie eligio.
        return _fail(problema, detalle + f" -- reserva: {_ORDEN_ARRANCAR}")
    if any("no responde" in e for e in estados):
        # VLM caido = WARN, no FAIL: los combos 'pensar' y 'solo' corren sin
        # :8081 a proposito (gpt-oss-20b ocupa la GPU entera).
        return _warn("flota parcial (:8081 sin VLM: el arbitro visual y el "
                     "lazo diseno-a-codigo no corren)", detalle)
    return _ok("flota por roles", detalle)


def check_backend_audit() -> bool:
    """Lee la cola de ~/.cognia/backend_audit.jsonl: el doctor sondea UN
    instante, pero las degradaciones reales pasan durante las sesiones y
    quedan ahi. Un sistema que sondea verde con 40 eventos DEGRADADO en el
    dia NO esta "en orden"."""
    import datetime
    path = os.path.join(os.path.expanduser("~"), ".cognia", "backend_audit.jsonl")
    if not os.path.isfile(path):
        return _ok("backend_audit", "sin auditoria todavia (se crea al usar el CLI)")
    corte = datetime.datetime.now() - datetime.timedelta(hours=24)
    total = degradados = 0
    ultimo = ""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lineas = fh.readlines()[-500:]   # solo la cola: el archivo crece
        for ln in lineas:
            try:
                ev = json.loads(ln)
                t = datetime.datetime.fromisoformat(str(ev.get("t", "")))
            except Exception:
                continue    # linea corrupta por escritura concurrente: saltar
            if t < corte:
                continue
            total += 1
            if ev.get("degradado"):
                degradados += 1
                ultimo = str(ev.get("via", ""))
    except Exception as exc:
        return _warn("backend_audit ilegible", str(exc))
    if degradados:
        return _warn(f"backend_audit: {degradados} evento(s) DEGRADADO en 24h",
                     f"ultimo via={ultimo} -- detalle en {path}")
    return _ok(f"backend_audit: sin degradados en 24h ({total} eventos)")


def check_fleet30() -> bool:
    """Miembros del FLEET-30 declarados en el manifest cuyo GGUF no esta en
    disco: fleet_backend() los cachea como FAILED con un warning de logger que
    nadie ve y la cascada cae al fallback en silencio. Aca se listan."""
    try:
        from node.fleet_registry import load_manifest
        manifest = load_manifest(force=True)
    except Exception as exc:
        return _warn("fleet30", f"registry no importable: {exc}")
    if not manifest:
        return _warn("fleet30", "sin manifest fleet30.json (opcional)")
    faltan = sorted(k for k, m in manifest.items()
                    if not getattr(m.get("gguf"), "is_file", lambda: False)())
    if faltan:
        return _warn(f"fleet30: {len(faltan)}/{len(manifest)} miembros SIN GGUF",
                     ", ".join(faltan)
                     + " -- instala con: cognia install-model --fleet30 <key>")
    return _ok(f"fleet30: {len(manifest)} miembros con GGUF en disco")


def check_sentinel() -> bool:
    """El centinela (cognia/agent/sentinel.py) es el cerebro antidanios: una
    compuerta determinista pre-accion, default-ON. Nada lo verificaba (no
    tenia check propio, auditoria 2026-08-01), asi que una desactivacion o una
    regresion en su clasificacion pasaba inadvertida. Aca: (1) reporta si esta
    ON/OFF, (2) smoke determinista de que un `rm -rf /` se clasifica BLOCK, y
    (3) el estado de la auditoria ~/.cognia/sentinel_audit.jsonl."""
    try:
        from cognia.agent.sentinel import (
            sentinel_enabled, clasificar_shell, BLOCK,
        )
    except Exception as exc:
        return _warn("centinela no importable", str(exc))
    nivel, _ = clasificar_shell("rm -rf /")
    if nivel != BLOCK:
        # Regresion real: el guard dejo de bloquear un comando destructivo.
        return _fail("centinela: 'rm -rf /' NO se clasifica BLOCK",
                     f"clasificado como {nivel!r} -- revisar _BLOCK_SUB/_BLOCK_RE")
    estado = "ON" if sentinel_enabled() else "OFF (COGNIA_SENTINEL=0)"
    path = os.path.join(os.path.expanduser("~"), ".cognia", "sentinel_audit.jsonl")
    aud = ""
    if os.path.isfile(path):
        aud = f" -- auditoria: {os.path.getsize(path)} bytes"
    if not sentinel_enabled():
        return _warn(f"centinela {estado}", "el guard anti-danios esta apagado" + aud)
    return _ok(f"centinela {estado}, 'rm -rf /' -> BLOCK{aud}")


def run_all() -> int:
    # config.env ANTES de cualquier check. El bloque __main__ de abajo ya lo
    # hacia, pero el wrapper scripts/cognia_doctor.py y el /doctor del CLI
    # entran por main()/run_all() y se lo saltaban: el doctor sondeaba sin
    # LLAMA_SERVER_URL ni el modelo de config.env y termino "Todo en orden"
    # sobre un sistema DEGRADADO (auditoria 2026-08-01). apply_config respeta
    # las env vars ya presentes, asi que llamarlo dos veces es inocuo.
    try:
        from cognia.first_run import apply_config
        apply_config()
    except Exception:
        pass
    sections = [
        ("Version de Python", check_python),
        ("Paquetes Python",   check_packages),
        ("Backend GGUF (principal)", check_gguf),
        ("Ollama (opcional)", check_ollama),
        # Va antes que shards y velocidad a proposito: es la comprobacion que
        # de verdad decide si Cognia puede trabajar.
        ("Backend LLM",       check_llm_backend),
        ("Flota por roles",   check_flota),
        ("Auditoria de backend", check_backend_audit),
        ("Centinela (anti-danios)", check_sentinel),
        ("FLEET-30",          check_fleet30),
        ("Configuracion",     check_env),
        ("Base de datos",     check_db),
        ("Shards del modelo", check_shards),
        ("Velocidad inferencia", check_inference_speed),
    ]
    fails = 0
    for label, fn in sections:
        print(f"\n{label}:")
        try:
            if not fn():
                fails += 1
        except Exception as e:
            _fail(label, str(e))
            fails += 1
    print()
    if fails == 0:
        print("Todo en orden. Cognia esta lista.")
    else:
        print(f"{fails} chequeo(s) con problemas. Revisa los [FAIL] arriba.")
    print()
    return 0 if fails == 0 else 1


def main() -> int:
    print("\nCognia -- diagnostico\n")
    return run_all()


if __name__ == "__main__":
    try:
        from cognia.first_run import apply_config
        apply_config()   # config.env instalado (fix auditoria 2026-07-15)
    except Exception:
        pass
    sys.exit(main())
