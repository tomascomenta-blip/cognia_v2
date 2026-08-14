# -*- coding: utf-8 -*-
"""
cognia/arranque.py
==================
`cognia empezar`: UNA orden que deja la maquina lista, o dice EXACTAMENTE que
falta y con que orden se arregla.

POR QUE EXISTE: hasta hoy empezar a usar Cognia en una maquina nueva costaba
NUEVE interacciones repartidas en TRES caminos que no coinciden entre si (el
wizard de first_run que pregunta modo/red/shards, cognia_setup.iss, y el
install.ps1). Ninguno de los tres deja la maquina LISTA: el wizard baja pesos
pero no levanta el server, el instalador copia binarios pero no configura, y
ninguno dice en que regimen va a hablar el agente. El dueno pidio "facilitar
todo el proceso de iniciacion": esto es ese proceso reducido a un comando.

CUATRO PASOS, cada uno impreso como [OK] (ya estaba) / [HAGO] (lo hice ahora)
/ [FALTA] (no pude, y aqui esta la orden):

  1. config    ~/.cognia/.setup_done  -> si falta, wizard MINIMO (nombre e
               idioma; nada de descargas: ese es el paso 2).
  2. pesos     hay un GGUF servible? -> si no, se ofrece la descarga UNA vez,
               con el espacio libre COMPROBADO y el tamano REAL del fichero
               (HEAD a HuggingFace) medidos ANTES de preguntar.
  3. backend   responde 127.0.0.1:8080? -> si no, cognia.flota.arrancar().
  4. capacidad cognia.agent.capacidad.medicion(): en UNA linea, el regimen
               (NATIVO o TEXTO) con el que el agente va a hablarle a ese
               server. Es lo que conecta la iniciacion con el adaptador.

Hay un cuarto estado, [AVISO]: la maquina quedo lista pero algo no se pudo
SABER. Existe por el paso 4: la sonda de capacidad tarda 26-30 s en esta
maquina cargada contra un timeout de 30 s, y cuando no contesta el registro
vuelve con soporta_tools=False — que NO es "va en modo texto", es "no se
midio". Imprimir ahi "regimen TEXTO" seria publicar como veredicto una
medicion que no ocurrio. AVISO no baja el exit: el server responde y el
agente funciona (cae al marco de texto de siempre); lo unico que se prohibe
es afirmar un regimen que nadie midio.

IDEMPOTENTE POR CONTRATO: correrlo dos veces seguidas no pregunta nada la
segunda vez y no repite trabajo - solo hace lo que falta. Cierra entrando al
REPL (salvo --sin-repl), que es lo que el usuario queria desde el principio.

    cognia empezar [--sin-descarga] [--sin-repl] [--json]
    python -m cognia.arranque --sin-descarga --sin-repl --json

Exit code: 0 si la maquina quedo lista ([OK]/[HAGO]/[AVISO]), 1 si falta algo
([FALTA], con UNA linea accionable por stderr), 2 si el flag no existe.

NUNCA relanza un backend vivo. `flota.arrancar()` empieza por `parar()`, que
mata TODOS los llama-server de la maquina: un timeout de red no puede costarle
el server a quien lo este usando. Por eso el paso 3 exige DOS sondas fallidas
(3 s y 6 s) antes de declarar el puerto muerto.

Solo stdlib + modulos del propio paquete (first_run / model_install / flota /
agent.capacidad), todos importados PEREZOSAMENTE: este modulo tiene que poder
importarse en una maquina a medio instalar sin arrastrar huggingface_hub.
"""
from __future__ import annotations

import contextlib
import importlib
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

URL_BACKEND = "http://127.0.0.1:8080"

# Cuanto ocupa el stack default de `cognia install-model` (GGUF 3B Q4_K_M +
# llama-server + adapters del fleet + portero 0.5B). Es el MISMO numero que
# model_install._check_espacio usa para abortar: si aquel cambia y este no,
# `empezar` prometeria una descarga que install-model rechaza. El GGUF se mide
# de verdad (HEAD a HF) cuando hay red; esto es el suelo cuando no la hay.
TAM_ESTIMADO_BYTES = 2_600_000_000
TAM_EXTRA_BYTES = 700_000_000        # server + adapters + portero, sobre el GGUF
MARGEN_DISCO_BYTES = 1_000_000_000   # el mismo margen de 1 GB de model_install

# Un .gguf mas chico que esto no es un modelo servible: en ~/.cognia/models
# conviven los adapters LoRA del fleet (decenas de MB). Decir "ya tenes pesos"
# senalando un adapter es exactamente la degradacion silenciosa que el repo
# lleva anos cazando.
MIN_GGUF_BYTES = 300_000_000

# Ficheros .gguf que NO son un modelo de chat aunque pesen: los proyectores
# multimodales (mmproj-*, 1.3 GB en esta maquina) y los adapters. Y la parte
# 2-de-N de un GGUF partido, que no se sirve sola (la 1-de-N si).
_TROZOS_NO_SERVIBLES = ("mmproj", "lora", "adapter", "portero", "draft")


# ── Paths y utilidades ───────────────────────────────────────────────────────

def _home() -> Path:
    """~/.cognia, o COGNIA_HOME si el entorno lo redirige (la misma convencion
    de first_run.py:26 y capacidad._home: sin esto no habria manera de probar
    el camino de instalacion limpia sin romper el home del dueno)."""
    crudo = os.environ.get("COGNIA_HOME", "").strip()
    return Path(crudo) if crudo else Path.home() / ".cognia"


def _first_run():
    """first_run con sus constantes ALINEADAS al COGNIA_HOME de AHORA.

    first_run congela COGNIA_HOME/CONFIG_FILE/FIRST_RUN_OK en el import. Si el
    entorno cambio despues (un test, o un COGNIA_HOME que el propio proceso se
    puso), escribir por set_config_value iria al home viejo — y el paso 1
    marcaria como hecho un setup en otro directorio."""
    from cognia import first_run as fr
    if str(fr.COGNIA_HOME) != str(_home()):
        fr = importlib.reload(fr)
    return fr


def _gb(n) -> str:
    """Bytes -> '1.9 GB'. Los numeros del disco se muestran, no se redondean
    a 'un par de gigas': el dueno tiene que poder verificarlos."""
    try:
        return f"{float(n) / 1e9:.1f} GB"
    except Exception:
        return "?"


def _espacio_libre(destino: Path) -> int:
    """Bytes libres en el volumen de `destino`, subiendo hasta el primer padre
    que exista (en un home virgen el directorio aun no esta creado). 0 si no se
    puede saber — y 0 NO bloquea: se avisa, no se inventa."""
    p = destino
    for _ in range(6):
        try:
            return int(shutil.disk_usage(str(p)).free)
        except Exception:
            if p.parent == p:
                break
            p = p.parent
    return 0


def _es_servible(nombre: str) -> bool:
    """¿Este .gguf es un modelo al que se le puede hablar?"""
    bajo = nombre.lower()
    if not bajo.endswith(".gguf"):
        return False
    if any(t in bajo for t in _TROZOS_NO_SERVIBLES):
        return False
    # 'x-00002-of-00003.gguf': solo la primera parte es el punto de entrada.
    if "-of-" in bajo and "-00001-of-" not in bajo:
        return False
    return True


def _gguf_servible() -> Optional[Path]:
    """El GGUF mas grande que esta maquina puede servir, o None.

    Mira LLAMA_GGUF_PATH primero (lo que config.env dice que se usa) y despues
    ~/.cognia/models recursivo. No reusa node.llama_backend._find_gguf porque
    aquel resuelve contra Path.home() fijo y contra el repo: aqui hace falta
    respetar COGNIA_HOME para poder verificar el camino de home virgen."""
    env = os.environ.get("LLAMA_GGUF_PATH", "").strip()
    if env:
        p = Path(env)
        if p.is_file() and p.stat().st_size >= MIN_GGUF_BYTES:
            return p
    raiz = _home() / "models"
    if not raiz.is_dir():
        return None
    candidatos = []
    for p in raiz.rglob("*.gguf"):
        try:
            if p.is_file() and _es_servible(p.name) and p.stat().st_size >= MIN_GGUF_BYTES:
                candidatos.append(p)
        except OSError:
            continue
    if not candidatos:
        return None
    return max(candidatos, key=lambda x: x.stat().st_size)


def _tam_remoto_gguf() -> int:
    """Tamano REAL (bytes) del GGUF que se bajaria, 0 si la red no contesta.

    Preguntar "¿bajo ~2 GB?" con un numero escrito a mano es pedirle al usuario
    que confie en un dato que nadie midio; HF publica el tamano en la cabecera
    (x-linked-size cuando el fichero vive en LFS). Si no hay red se dice
    'estimado' y se sigue: un HEAD caido no puede bloquear el arranque."""
    try:
        from cognia.model_install import GGUF_REPO, GGUF_FILE
    except Exception:
        return 0
    url = f"https://huggingface.co/{GGUF_REPO}/resolve/main/{GGUF_FILE}"
    try:
        pedido = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(pedido, timeout=8) as r:
            crudo = (r.headers.get("x-linked-size")
                     or r.headers.get("Content-Length") or "0")
        return int(crudo)
    except Exception:
        return 0


def _responde(url: str, timeout: float) -> bool:
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/health",
                                    timeout=timeout) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def url_backend() -> str:
    """El server al que el AGENTE le va a hablar: COGNIA_LLM_URL si esta, o
    127.0.0.1:8080.

    Es la misma convencion de agent/capacidad.py:109 y agent/model_profiles.py:
    103, y se copia a proposito. Si el paso 3 sondeara un puerto fijo mientras
    el agente habla con otro, el regimen del paso 4 estaria describiendo un
    server que el usuario no usa — la clase de mentira coherente que el repo
    ya pago cara con el :8088 sirviendo un modelo retirado."""
    return (os.environ.get("COGNIA_LLM_URL") or URL_BACKEND).rstrip("/")


def _es_local(url: str) -> bool:
    """¿Ese server lo puede levantar ESTA maquina? Levantar el combo local no
    arregla un COGNIA_LLM_URL que apunta a otro equipo."""
    return ("127.0.0.1" in url or "localhost" in url or "0.0.0.0" in url
            or "[::1]" in url)


def _backend_vivo(url: str = "") -> bool:
    """DOS sondas (3 s y 6 s) antes de declarar el puerto muerto.

    No es paranoia: el remedio de la rama muerta es flota.arrancar(), que
    empieza con parar() y mata TODOS los llama-server de la maquina. Un
    timeout aislado (el server ocupado con una generacion larga) le costaria
    el backend a quien lo estuviera usando. Dos fallos seguidos con timeout
    creciente es la evidencia minima para tocar procesos ajenos."""
    url = url or url_backend()
    if _responde(url, 3):
        return True
    time.sleep(1.0)
    return _responde(url, 6)


def _arrancar_flota() -> int:
    """Levanta el combo por defecto DEL PAQUETE (nunca scripts/: no viaja en
    el wheel — WP6). Devuelve el exit code de flota.arrancar."""
    from cognia import flota
    return flota.arrancar(flota.COMBO_DEFAULT)


def _modelo_del_backend(url: str = "") -> dict:
    """{'modelo','n_ctx'} del server vivo, {} si no se pudo leer."""
    try:
        from cognia import backend_activo
        return backend_activo.props(url or url_backend(), forzar=True) or {}
    except Exception:
        return {}


# ── Los cuatro pasos ─────────────────────────────────────────────────────────

def _paso(nombre: str, estado: str, detalle: str, accion: str = "") -> dict:
    return {"paso": nombre, "estado": estado, "detalle": detalle,
            "accion": accion}


def _decir(paso: dict) -> None:
    """Una linea por paso. ASCII puro: la consola del dueno es cp1252."""
    tag = {"ok": "[OK]   ", "hago": "[HAGO] ", "falta": "[FALTA]",
           "aviso": "[AVISO]"}.get(paso["estado"], "[?]    ")
    print(f"  {tag} {paso['paso']:9s} {paso['detalle']}")


def paso_config(interactivo: bool) -> dict:
    """(1) ~/.cognia/.setup_done. Si falta: wizard MINIMO, sin descargas.

    El wizard largo de first_run pregunta modo (local/red/memoria), URL del
    coordinador, shards NPZ y token de HF ANTES de que el usuario haya escrito
    una sola frase. Aqui se preguntan dos cosas que cambian la primera
    respuesta que va a leer (nombre e idioma) y nada mas; el modo se cambia
    despues con `cognia modo`."""
    fr = _first_run()
    if fr.FIRST_RUN_OK.exists():
        return _paso("config", "ok", f"{fr.CONFIG_FILE}")

    nombre, idioma = "", "espanol"
    if interactivo:
        try:
            print("\n  Primera vez. Dos preguntas y arrancamos "
                  "(Enter para el default):")
            nombre = input("    Tu nombre (Enter para saltar): ").strip()
            idioma = (input("    Idioma de las respuestas "
                            "[espanol]: ").strip().lower() or "espanol")
        except (EOFError, KeyboardInterrupt):
            # Sin TTY real o con Ctrl-C: los defaults, y se dice. Colgarse
            # esperando un input que nadie va a escribir es peor que asumir.
            print()
            nombre, idioma = "", "espanol"
    if idioma not in ("espanol", "ingles"):
        idioma = "espanol"

    fr.COGNIA_HOME.mkdir(parents=True, exist_ok=True)
    fr.DATA_DIR.mkdir(parents=True, exist_ok=True)
    fr.set_config_value("COGNIA_DATA_DIR", str(fr.DATA_DIR))
    fr.set_config_value("COGNIA_LANG", idioma)
    if nombre:
        fr.set_config_value("COGNIA_USER_NAME", nombre)
    fr.FIRST_RUN_OK.touch()
    como = "" if interactivo else " (sin TTY: defaults; cambialo con: cognia modo)"
    return _paso("config", "hago",
                 f"{fr.CONFIG_FILE} idioma={idioma}"
                 + (f" nombre={nombre}" if nombre else "") + como)


def paso_pesos(sin_descarga: bool, interactivo: bool,
               backend_ok: bool) -> dict:
    """(2) ¿Hay un GGUF servible? Si no, la descarga se ofrece UNA vez.

    El orden importa: primero se mide el tamano real y el espacio libre, y
    recien despues se pregunta. Preguntar antes de mirar el disco es como
    murio la descarga de 1.9 GB a la mitad con un error crudo de urllib
    (auditoria 2026-07-15, la razon de model_install._check_espacio)."""
    gguf = _gguf_servible()
    if gguf is not None:
        return _paso("pesos", "ok",
                     f"{gguf.name} ({_gb(gguf.stat().st_size)})")

    if backend_ok:
        # Un server ya vivo puede estar sirviendo un GGUF que vive fuera de
        # ~/.cognia (o en otra maquina, si COGNIA_LLM_URL apunta afuera): NO
        # hacen falta pesos locales para que la maquina este lista.
        p = _modelo_del_backend()
        return _paso("pesos", "ok",
                     f"sin GGUF local, pero {url_backend()} ya sirve "
                     f"{p.get('modelo') or 'un modelo'}")

    orden = "python -m cognia install-model"
    if sin_descarga:
        return _paso("pesos", "falta",
                     "no hay GGUF servible en " + str(_home() / "models"),
                     orden)

    tam_gguf = _tam_remoto_gguf()
    total = (tam_gguf + TAM_EXTRA_BYTES) if tam_gguf else TAM_ESTIMADO_BYTES
    medido = "real" if tam_gguf else "estimado"
    libre = _espacio_libre(_home())
    if libre and libre < total + MARGEN_DISCO_BYTES:
        return _paso("pesos", "falta",
                     f"hacen falta {_gb(total)} ({medido}) + {_gb(MARGEN_DISCO_BYTES)} "
                     f"de margen y hay {_gb(libre)} libres",
                     f"libera espacio en {_home().drive or _home()} y corre: {orden}")

    if not interactivo:
        return _paso("pesos", "falta",
                     f"no hay GGUF y no hay TTY para ofrecer la descarga "
                     f"({_gb(total)} {medido})", orden)

    print(f"\n  No hay modelo instalado. La descarga son {_gb(total)} "
          f"({medido}); libres en disco: {_gb(libre) if libre else '?'}.")
    try:
        r = input("  Descargar ahora el stack (GGUF + llama-server + "
                  "expertos)? [S/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        r = "n"
    if r and r not in ("s", "si", "y", "yes"):
        return _paso("pesos", "falta", "descarga declinada por el usuario", orden)

    try:
        # Mismo cuidado que con first_run: model_install congela MODELS_DIR en
        # su import, y si el home cambio despues instalaria en el viejo.
        from cognia import model_install as mi
        if str(mi.COGNIA_HOME) != str(_home()):
            mi = importlib.reload(mi)
        mi.install_model()
    except Exception as exc:
        # Sin red / 401 de HF / disco: el mensaje accionable, no el traceback.
        return _paso("pesos", "falta", f"la descarga fallo: {exc}", orden)
    gguf = _gguf_servible()
    if gguf is None:
        return _paso("pesos", "falta",
                     "install-model termino pero no encuentro el GGUF", orden)
    return _paso("pesos", "hago", f"{gguf.name} ({_gb(gguf.stat().st_size)})")


def paso_backend(url: str = "", vivo: Optional[bool] = None) -> dict:
    """(3) ¿Responde el server del agente? Si no, se levanta el combo default.

    `vivo` evita sondar dos veces: el paso 2 ya necesita saberlo (un server
    vivo hace innecesarios los pesos locales) y cada sonda cuesta hasta 9 s.

    JAMAS se relanza un server vivo: `flota.arrancar` empieza por `parar()`,
    que mata todos los llama-server de la maquina."""
    url = url or url_backend()
    if _backend_vivo(url) if vivo is None else vivo:
        p = _modelo_del_backend(url)
        ctx = f", ctx {p.get('n_ctx')}" if p.get("n_ctx") else ""
        return _paso("backend", "ok",
                     f"{url} responde - {p.get('modelo') or 'modelo desconocido'}{ctx}")

    if not _es_local(url):
        # Levantar el combo local no arreglaria un server ajeno, y en cambio
        # mataria los llama-server de esta maquina para nada.
        return _paso("backend", "falta",
                     f"{url} (COGNIA_LLM_URL) no responde y no es de esta "
                     f"maquina",
                     "arranca ese server, o quita COGNIA_LLM_URL para usar el "
                     "local: python -m cognia flota arrancar pensar-qwythos")

    from cognia import flota   # solo para nombrar el combo en el mensaje
    orden = f"python -m cognia flota arrancar {flota.COMBO_DEFAULT}"
    print(f"  ...  backend   {url} no responde; levanto el combo "
          f"'{flota.COMBO_DEFAULT}' (tarda ~1 min)")
    try:
        codigo = _arrancar_flota()
    except Exception as exc:
        return _paso("backend", "falta", f"no pude arrancar la flota: {exc}",
                     orden)
    if codigo != 0 or not _backend_vivo(url):
        return _paso("backend", "falta",
                     f"la flota no dejo nada escuchando en {url} "
                     f"(codigo {codigo})", orden)
    p = _modelo_del_backend(url)
    return _paso("backend", "hago",
                 f"{url} arriba - {p.get('modelo') or 'modelo desconocido'}")


def _no_se_pudo_medir(motivo: str) -> bool:
    """¿Ese `motivo` de capacidad dice "no soporta" o dice "no pregunte"?

    capacidad.sondar devuelve SIEMPRE soporta_tools=False cuando algo sale
    mal, y mete en `motivo` dos cosas muy distintas: el veredicto medido
    ("respondio sin tool_calls (finish_reason=stop)") y la NO-medicion ("no
    se pudo consultar al server: TimeoutError: timed out", capacidad.py:198-
    201). Solo la segunda familia se reconoce aqui, por substring del motivo,
    que es lo unico que la API publica expone: el registro no trae una marca
    de "hubo respuesta"."""
    bajo = (motivo or "").lower()
    return any(t in bajo for t in
               ("no se pudo consultar", "timeout", "timed out", "urlerror"))


def paso_capacidad(backend_ok: bool, url: str = "") -> dict:
    """(4) El regimen con el que el agente le va a hablar a ESE server.

    Medido, no declarado: capacidad.medicion() hace una peticion real con una
    tool trivial. Es la linea que le falta a todo el resto de la iniciacion —
    hasta hoy el usuario terminaba de instalar sin saber si su agente iba a
    usar tool-calling nativo o el marco de texto.

    Y si la medicion NO se pudo hacer, se dice ESO y no un regimen. El caso
    esta reproducido (1 de 2 homes virgenes, 2026-08-13): la sonda tarda
    26-30 s en esta maquina cargada contra su _TIMEOUT_S=30, vuelve
    soporta_tools=False con motivo 'TimeoutError' y la version anterior de
    este paso imprimia "regimen TEXTO con <modelo>" como si lo hubiera
    medido. Peor: medicion() cachea TAMBIEN los fallos (capacidad.py:268-273)
    con un TTL de 24 h, asi que ese regimen falso lo arrastraba el usuario
    nuevo todo el dia — el agente entero decide por esta medicion. Por eso
    aqui, ademas de decir la verdad, se llama a invalidar(url): un timeout es
    transitorio y no puede quedar sellado.

    Se usa medicion() y no diagnostico() a proposito: diagnostico() devuelve
    la linea YA formateada como veredicto ("regimen TEXTO con ...") y no deja
    manera de distinguir los dos casos."""
    if not backend_ok:
        return _paso("capacidad", "falta",
                     "sin backend no hay regimen que medir",
                     "arregla el paso 3 y vuelve a correr: cognia empezar")
    url = url or url_backend()
    reintento = "python -m cognia.agent.capacidad --forzar"
    try:
        from cognia.agent import capacidad as cap
        reg = cap.medicion(url) or {}
    except Exception as exc:
        # capacidad.medicion no lanza por contrato; si lo hiciera, el arranque
        # no se cae por ello (la maquina sigue lista) pero tampoco inventa un
        # regimen que no midio.
        return _paso("capacidad", "aviso",
                     f"no pude medir el regimen ({exc}); "
                     f"reintenta: {reintento}", reintento)

    motivo = str(reg.get("motivo") or "")
    if not reg.get("soporta_tools") and _no_se_pudo_medir(motivo):
        try:
            cap.invalidar(url)
        except Exception:
            # Si no se puede limpiar el cache, el aviso se imprime igual: lo
            # inaceptable es callarlo, no que el JSON quede sucio.
            pass
        return _paso("capacidad", "aviso",
                     f"no pude medir el regimen ({motivo}); no lo dejo "
                     f"cacheado - reintenta: {reintento}", reintento)

    # Medicion de verdad: el mismo formato de capacidad.diagnostico().
    modelo = reg.get("modelo") or "(sin backend)"
    regimen = "NATIVO" if reg.get("soporta_tools") else "TEXTO"
    return _paso("capacidad", "ok", f"regimen {regimen} con {modelo}: {motivo}")


# ── Orquestacion ─────────────────────────────────────────────────────────────

_FLAGS_VALIDOS = {"--sin-descarga", "--sin-repl", "--json", "-h", "--help",
                  "--ayuda"}


def _correr(sin_descarga: bool, interactivo: bool) -> dict:
    """Los 4 pasos en orden, imprimiendo cada uno. Devuelve el informe."""
    t0 = time.time()
    fr = _first_run()
    fr.apply_config()   # config.env -> os.environ (LLAMA_GGUF_PATH, etc.)

    print("\n  cognia empezar - dejo la maquina lista o te digo que falta\n")

    pasos = [paso_config(interactivo)]
    _decir(pasos[0])

    # La SONDA del backend se hace antes de imprimir el paso de pesos (un
    # server vivo hace innecesarios los pesos locales: puede estar sirviendo
    # un GGUF de fuera de ~/.cognia). Lo que se difiere es el ARRANQUE, para
    # que las lineas salgan en el orden 1-2-3-4 que el usuario entiende.
    url = url_backend()
    vivo = _backend_vivo(url)

    p_pesos = paso_pesos(sin_descarga, interactivo, vivo)
    _decir(p_pesos)

    p_backend = paso_backend(url, vivo=vivo)
    _decir(p_backend)
    backend_ok = p_backend["estado"] in ("ok", "hago")
    pasos += [p_pesos, p_backend]

    p_cap = paso_capacidad(backend_ok, url)
    _decir(p_cap)
    pasos.append(p_cap)

    # 'aviso' NO cuenta como fallo: la maquina esta lista (el backend
    # responde), lo que falto fue SABER algo — hoy solo el regimen del paso 4
    # cuando la sonda no contesta a tiempo. Convertir eso en exit 1 dejaria al
    # usuario fuera del REPL por un timeout de una sonda opcional; callarlo
    # seria mentir. Se avisa y se sigue.
    listo = not any(p["estado"] == "falta" for p in pasos)
    fallo = next((p for p in pasos if p["estado"] == "falta"), None)
    return {
        "listo": listo,
        "home": str(_home()),
        "pasos": pasos,
        # Solo hay regimen si se MIDIO: con [AVISO] (sonda sin respuesta) o
        # [FALTA] (sin backend) el campo va vacio. Quien consuma el JSON tiene
        # que poder distinguir "TEXTO" de "no se sabe" sin leer prosa.
        "regimen": p_cap["detalle"] if p_cap["estado"] == "ok" else "",
        "accion": (fallo or {}).get("accion", "") if fallo else "",
        "segundos": round(time.time() - t0, 2),
    }


def main(argv: Optional[list] = None) -> int:
    """`cognia empezar` (B1 cablea aqui) y `python -m cognia.arranque`."""
    argv = list(sys.argv[1:] if argv is None else argv)
    desconocidos = [a for a in argv if a not in _FLAGS_VALIDOS]
    if desconocidos:
        # Un typo NO puede cambiar en silencio lo que el comando hace (misma
        # regla que model_install.main).
        print(f"flags desconocidos: {' '.join(desconocidos)}\n"
              f"validos: --sin-descarga --sin-repl --json", file=sys.stderr)
        return 2
    if {"-h", "--help", "--ayuda"} & set(argv):
        print(__doc__)
        return 0

    sin_descarga = "--sin-descarga" in argv
    como_json = "--json" in argv
    # --json es modo maquina: nada de preguntas (bloquearia a quien lo
    # invoque) y nada de REPL. --sin-repl solo se pide, aqui se impone.
    sin_repl = "--sin-repl" in argv or como_json
    interactivo = (not como_json) and sys.stdin is not None and sys.stdin.isatty()

    salida = sys.stdout
    # En modo JSON stdout lleva SOLO el JSON: las lineas de progreso (las
    # propias y las de flota/install_model, que imprimen por su cuenta) van a
    # stderr. Se siguen viendo — no se esconden, se separan.
    ctx = contextlib.redirect_stdout(sys.stderr) if como_json \
        else contextlib.nullcontext()
    with ctx:
        informe = _correr(sin_descarga, interactivo)
        if informe["listo"]:
            print("\n  Lista." + ("" if sin_repl else " Entrando al REPL...\n"))
        else:
            print("")

    if como_json:
        print(json.dumps(informe, ensure_ascii=False, indent=2), file=salida)

    if not informe["listo"]:
        # UNA linea accionable, con una orden que existe INSTALADA (nada de
        # 'python scripts/...': scripts/ no viaja en el wheel).
        accion = informe["accion"] or "corre: python -m cognia doctor"
        print(f"  -> {accion}", file=sys.stderr)
        return 1

    if not sin_repl:
        from cognia.cli import repl
        repl()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
