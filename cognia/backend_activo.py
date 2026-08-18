"""
backend_activo.py — quien atendio cada peticion de LLM: modelo, puerto y via.

POR QUE EXISTE: hasta el 2026-07-25 Cognia tenia DOS backends y nadie lo sabia.
node/llama_backend.py arrancaba llama-server en :8088 con LLAMA_GGUF_PATH
(qwen2.5-7b, el modelo que la auditoria de flota del 24/07 marco RETIRADO) y
atendia el chat, el agente y create_program; cognia/llm_local.py sondeaba :8080,
que es donde scripts/servir_flota.py sirve la flota adoptada por gate. Los
productos salian del 7B jubilado y el diagnostico culpaba a la arquitectura.

Un sistema que no dice quien contesto no se puede medir. Toda llamada real a un
LLM pasa por registrar() y deja:
  - una linea en stderr (visible en la corrida)
  - una linea JSON en ~/.cognia/backend_audit.jsonl (auditable despues)

Y toda ausencia de backend pasa por sin_backend(), que grita en vez de devolver
None en silencio (ver cognia/llm_local.py y node/llama_backend.try_load).

Solo stdlib. Nada aqui puede lanzar: es instrumentacion, no camino critico.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from typing import Optional

try:
    # Windows: el O_APPEND del CRT es seek-al-final + write, NO atomico entre
    # procesos (medido: 8 procesos x 200 filas -> 276 filas pisadas y lineas
    # entrelazadas). El lock de msvcrt serializa el append. En POSIX el
    # O_APPEND del kernel ya es atomico para el append, pero la ROTACION no lo
    # es en ningun sistema, y por eso el lock se toma en los dos.
    import msvcrt
except ImportError:                      # no-Windows
    msvcrt = None

try:
    import fcntl                          # POSIX
except ImportError:
    fcntl = None

AUDIT = Path.home() / ".cognia" / "backend_audit.jsonl"

# Rotacion a UNA generacion (.1): el jsonl crecia sin cota (1.48MB en 2
# semanas). Al superar el tope se renombra a .1 (pisando la generacion previa)
# y se sigue en un archivo fresco. Nada se borra sin dejar una generacion.
_ROTAR_BYTES = 10 * 1024 * 1024

# /props por URL. Sondear en cada token costaria mas que generarlo.
_props_cache: dict = {}

# Sello de tiempo de cada entrada de _props_cache (url -> epoch). Va APARTE
# para no cambiar el formato del cache: hay fixtures que inyectan
# _props_cache[url] = {...} a mano, y una entrada inyectada NO lleva sello y
# NO caduca (es un override deliberado, no una medicion).
#
# POR QUE EL TTL: el cache era un dict de proceso sin expiracion, con el
# argumento de que "un llama-server no cambia de modelo sin reiniciar". El
# summoner de 2026-08-09 rompio ese supuesto: apaga un rol y levanta otro EN
# EL MISMO PUERTO. Desde entonces, tras un swap, props() seguia devolviendo el
# modelo viejo durante toda la vida del proceso -> el REGIMEN del agente
# (model_profiles) se decidia sobre un modelo que ya no estaba. 60 s es corto
# frente a la vida de un proceso REPL y larguisimo frente al coste de un GET
# local (~3 ms).
_props_sello: dict = {}
_TTL_PROPS_S = 60.0

# Ultimo registro, para que los tests y el CLI puedan afirmar quien contesto
# sin releer el jsonl.
_ultimo: dict = {}


def _silencioso() -> bool:
    """True si NO se imprime la linea visible. El jsonl no se apaga nunca.

    2026-08-17: la linea pasa de OPT-OUT a OPT-IN. Medido en un REPL real
    (dos turnos contra :8080): salia una vez por turno Y POR `via`, o sea DOS
    veces en el turno que hace un stream_chat mas un generate interno -- 172
    caracteres de diagnostico, envueltos en dos lineas, pegados justo encima
    de la respuesta. Subirle el contraste (3,15 -> 6,15 con 'info_dim') lo
    EMPEORO: ahora el log compite de igual a igual con lo que el usuario pidio.
    La regla del repo es que la guerra es contra los logs, no contra su
    legibilidad.

    Que se conserva: el jsonl SIEMPRE (es la auditoria que impide volver a
    tener dos backends sin saberlo) y sin_backend(), que grita pase lo que
    pase -- la degradacion no es ruido, es el modo de fallo caro.

    Como se enciende: COGNIA_BACKEND_LOG=1, o COGNIA_TRACE=1 / COGNIA_DEBUG=1
    (los dos interruptores de diagnostico que el resto del repo ya usa; /debug
    del REPL setea COGNIA_DEBUG). COGNIA_BACKEND_LOG explicito manda sobre los
    dos, en los dos sentidos."""
    v = os.environ.get("COGNIA_BACKEND_LOG", "").strip()
    if v:
        return v == "0"
    diag = ("COGNIA_TRACE", "COGNIA_DEBUG")
    return not any(os.environ.get(k, "").strip() == "1" for k in diag)


def _emitir_evento(evento) -> bool:
    """Publica en el bus de ux/events (2026-08-09). Devuelve True si habia al
    menos un suscriptor: sin oyentes (scripts, tests, procesos sin REPL) el
    llamador conserva su print a stderr — pasar de "grita siempre" a "grita
    solo si alguien escucha" seria reabrir la degradacion silenciosa.

    Se mira events._suscriptores directamente porque el contrato del bus no
    expone un 'hay oyentes' y este modulo no puede modificarlo; el acceso va
    guardado y un fallo aqui solo significa 'usa el fallback'."""
    try:
        from cognia.ux import events as _ev
        con_oyentes = bool(_ev._suscriptores)
        _ev.emitir(evento)
        return con_oyentes
    except Exception:
        return False


def _sampling_de(dgs: dict) -> dict:
    """El sampling QUE EL PROPIO SERVER declara usar por defecto.

    llama-server lo mueve de sitio segun el build: hasta b~4xxx colgaba plano
    de default_generation_settings, y desde b10066 (el de esta maquina) vive
    en default_generation_settings.params — medido contra :8080 el 2026-08-13:
    {'params': {...'temperature': 0.8, 'top_p': 0.95, 'repeat_penalty': 1.0},
     'n_ctx': 200192}. Se miran los dos sitios porque adivinar el build seria
    el mismo vicio que adivinar el modelo por su nombre.

    POR QUE IMPORTA: sin esto, model_profiles le inventaba 0.7/0.8 (sampling
    de Qwen) a CUALQUIER modelo que no estuviera en su tabla de familias.
    """
    fuentes = []
    if isinstance(dgs, dict):
        p = dgs.get("params")
        if isinstance(p, dict):
            fuentes.append(p)
        fuentes.append(dgs)
    out = {}
    for clave in ("temperature", "top_p", "repeat_penalty"):
        for f in fuentes:
            v = f.get(clave)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                # El server devuelve el float de C (0.800000011920929): se
                # redondea para que un perfil sea legible y comparable.
                out[clave] = round(float(v), 4)
                break
    return out


def props(url: str, forzar: bool = False) -> dict:
    """
    {'modelo': <basename del gguf>, 'ruta': <model_path completo>,
     'n_ctx': int, 'puerto': int,
     'sampling': {temperature, top_p, repeat_penalty},
     'plantilla': <chat_template crudo>, 'caps': {chat_template_caps}}
    del server.

    'ruta', 'plantilla' y 'caps' se agregaron el 2026-08-17 para que quien
    decide el perfil pueda MEDIR en vez de adivinar por el nombre del fichero:
    'ruta' abre los metadatos del GGUF (arquitectura real) y 'plantilla'/'caps'
    dicen si el modelo lee enable_thinking / reasoning_effort. Son datos
    CRUDOS: la decision vive en cognia/agent/model_profiles.py, aca solo se
    reporta lo que el server dice.

    {} si no responde. Cacheado por URL con TTL de 60 s (ver _props_sello):
    un llama-server no cambia de modelo sin reiniciar, pero el summoner SI
    levanta otro rol en el mismo puerto.
    """
    url = url.rstrip("/")
    if not forzar and url in _props_cache:
        # El sello vale SOLO si es de esta misma entrada. Se compara por
        # identidad (y no por presencia de la url) porque _props_sello vive en
        # un dict aparte y puede quedar HUERFANO: una fixture que hace
        # monkeypatch.setattr(backend_activo, '_props_cache', {}) reemplaza el
        # cache pero no el sello, asi que la entrada recien inyectada heredaba
        # el sello de OTRO test, salia vencida, y props() se iba al server real
        # ignorando lo inyectado. Sintoma medido el 2026-08-14:
        # test_props_manda_sobre_gguf_path daba verde aislado y rojo en la
        # suite entera, que es la peor forma de rojo (parece flakiness y es un
        # cache que miente).
        crudo_sello = _props_sello.get(url)
        if isinstance(crudo_sello, tuple) and len(crudo_sello) == 2:
            sello, duena = crudo_sello
        else:
            # Formato viejo (un float suelto) o ausente: sin dueña que
            # comparar, se trata como override. Tolerar en vez de reventar:
            # esta funcion la llama la barra del REPL y un TypeError aqui
            # apagaria el prompt entero por un detalle de cache.
            sello, duena = None, None
        if (duena is not _props_cache[url] or sello is None
                or (time.time() - sello) < _TTL_PROPS_S):
            return _props_cache[url]
    datos = {}
    try:
        with urllib.request.urlopen(url + "/props", timeout=3) as r:
            crudo = json.loads(r.read().decode("utf-8", errors="replace"))
        dgs = crudo.get("default_generation_settings") or {}
        ruta = crudo.get("model_path") or dgs.get("model", "")
        caps = crudo.get("chat_template_caps")
        datos = {
            "modelo": Path(str(ruta)).name or "desconocido",
            "ruta": str(ruta or ""),
            "n_ctx": dgs.get("n_ctx"),
            "puerto": _puerto_de(url),
            "sampling": _sampling_de(dgs),
            "plantilla": str(crudo.get("chat_template") or ""),
            "caps": dict(caps) if isinstance(caps, dict) else {},
        }
    except Exception:
        datos = {}
    _props_cache[url] = datos
    # (epoch, la entrada que sellamos): la referencia fuerte es lo que permite
    # distinguir "esto lo midio props()" de "esto lo inyecto un test".
    _props_sello[url] = (time.time(), datos)
    return datos


def orden_arrancar() -> str:
    """La orden que se le sugiere al usuario cuando no hay backend.

    NO puede ser 'flota arrancar pensar': ese combo levanta gpt-oss-20b
    (flota.COMBOS['pensar']), mientras que el CEREBRO PRINCIPAL desde el
    2026-08-09 es Qwythos-9B — flota.COMBO_DEFAULT='pensar-qwythos'. Sugerir
    el combo equivocado manda al usuario que ya se quedo sin backend a
    levantar OTRO modelo, distinto del que espera el resto del sistema
    (arranque.py:421 ya decia el bueno; estos tres sitios no).

    El combo se LEE de flota para que no vuelva a divergir cuando el dueno
    cambie de cerebro: la fuente de verdad es una sola. Import perezoso y
    guardado porque flota importa ESTE modulo (ciclo) y aqui nada puede
    lanzar; sin flota disponible (wheel raro) queda el literal de hoy.
    """
    combo = "pensar-qwythos"
    try:
        from cognia.flota import COMBO_DEFAULT, COMBOS
        if COMBO_DEFAULT in COMBOS:
            combo = COMBO_DEFAULT
    except Exception:
        pass
    return f"python -m cognia flota arrancar {combo}"


def _puerto_de(url: str) -> Optional[int]:
    try:
        return int(url.rsplit(":", 1)[1].split("/")[0])
    except (ValueError, IndexError):
        return None


def _rotar_si_toca(path: Path, tope: int) -> None:
    """Rotacion a UNA generacion (.1). SOLO se llama con el lock TOMADO.

    Con el chequeo de tamano y el replace() fuera del lock, dos procesos que
    cruzan el tope a la vez hacen: P1 archiva el gordo en .1 y empieza uno
    fresco; P2, que ya habia visto el tamano viejo, archiva el FRESCO encima
    de .1 y destruye la generacion recien guardada (revision adversarial
    2026-08-01). Dentro del lock, P2 vuelve a medir y ve el archivo chico.
    """
    try:
        if path.stat().st_size > tope:
            path.replace(path.with_name(path.name + ".1"))
    except OSError:
        pass  # no existe aun, o un lector tiene el handle abierto (Windows):
              # no se rota esta vez, se reintenta en el proximo append.


def escribir_linea_jsonl(path: Path, linea: bytes, tope: int) -> None:
    """Append de UNA linea + rotacion, ambos dentro del MISMO lock entre
    procesos. El mutex es un archivo aparte (<audit>.lock) y no el propio
    jsonl: bloquear el byte 0 del jsonl (como se hacia antes) hace fallar la
    LECTURA concurrente del archivo en Windows -- de ahi que leer_audit
    devolviera ([], 0) 'vacio' cuando en realidad no habia podido leer.

    Lo usa tambien cognia/agent/sentinel.py: la rotacion estaba duplicada en
    los dos modulos y por eso el bug tambien.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_name(path.name + ".lock")
    fdl = os.open(lock, os.O_RDWR | os.O_CREAT)
    try:
        if msvcrt is not None:
            # LK_LOCK reintenta ~10s y luego lanza -> cae al except del llamador
            os.lseek(fdl, 0, os.SEEK_SET)
            msvcrt.locking(fdl, msvcrt.LK_LOCK, 1)
        elif fcntl is not None:
            fcntl.flock(fdl, fcntl.LOCK_EX)
        try:
            _rotar_si_toca(path, tope)
            # UNA sola write() de la linea completa sobre O_APPEND: con el
            # open("a") + write() bufereado, dos procesos concurrentes
            # entrelazaban trozos de linea (el jsonl tenia lineas corruptas).
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND)
            try:
                os.write(fd, linea)
            finally:
                os.close(fd)
        finally:
            if msvcrt is not None:
                os.lseek(fdl, 0, os.SEEK_SET)
                msvcrt.locking(fdl, msvcrt.LK_UNLCK, 1)
            elif fcntl is not None:
                fcntl.flock(fdl, fcntl.LOCK_UN)
    finally:
        os.close(fdl)


def _append(fila: dict) -> None:
    try:
        linea = (json.dumps(fila, ensure_ascii=False) + "\n").encode("utf-8")
        escribir_linea_jsonl(AUDIT, linea, _ROTAR_BYTES)
    except Exception:
        pass


def leer_audit(max_lineas: Optional[int] = None,
               con_estado: bool = False) -> tuple:
    """(filas, corruptas): las filas JSON del audit y CUANTAS lineas se
    saltaron por no parsear (herencia de las escrituras concurrentes viejas).
    El contador existe para que un lector no confunda 'archivo a medias
    corrupto' con 'no paso nada'.

    con_estado=True devuelve (filas, corruptas, estado) con estado en
    {'ok', 'vacio', 'ilegible'}. Existe porque devolver ([], 0) tanto cuando
    no hay auditoria como cuando NO SE PUDO LEER (lock tomado, permisos,
    antivirus) es el mismo falso 'todo tranquilo' que este modulo existe para
    impedir: un lector no debe poder confundir 'no paso nada' con 'no mire'.
    """
    estado = "ok"
    try:
        with AUDIT.open("r", encoding="utf-8", errors="replace") as f:
            lineas = f.readlines()
    except FileNotFoundError:
        lineas, estado = [], "vacio"
    except OSError as exc:
        # Reintento corto: en Windows un lock de rango o un antivirus pueden
        # negar la lectura un instante.
        time.sleep(0.2)
        try:
            with AUDIT.open("r", encoding="utf-8", errors="replace") as f:
                lineas = f.readlines()
        except OSError:
            print(f"[backend] NO SE PUDO LEER la auditoria {AUDIT}: {exc}",
                  file=sys.stderr, flush=True)
            return ([], 0, "ilegible") if con_estado else ([], 0)
    if max_lineas:
        lineas = lineas[-max_lineas:]
    filas, corruptas = [], 0
    for ln in lineas:
        ln = ln.strip()
        if not ln:
            continue
        try:
            filas.append(json.loads(ln))
        except ValueError:
            corruptas += 1
    return (filas, corruptas, estado) if con_estado else (filas, corruptas)


def registrar(via: str, url: str, rol: str = "", **extra) -> dict:
    """
    Deja constancia de que `via` atendio una peticion contra `url`.

    via: 'chat', 'agente', 'create_program', 'constructor', 'pulidor', 'juez'...
    rol: el rol de flota esperado ('construir', 'pensar', ...), si se conoce.
    """
    global _ultimo
    p = props(url)
    fila = {
        "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "via": via,
        "url": url.rstrip("/"),
        "puerto": p.get("puerto") or _puerto_de(url),
        "modelo": p.get("modelo", "SIN RESPUESTA /props"),
        "rol": rol,
        **extra,
    }
    _ultimo = fila
    _append(fila)
    if not _silencioso():
        # Al bus de ux/events: el renderer del CLI lo muestra UNA vez por
        # turno (esta linea salia 10+ veces por turno y tapaba la respuesta,
        # evidencia baseline 2026-08-09). El jsonl de arriba conserva TODAS.
        visto = False
        try:
            from cognia.ux.events import Aviso
            visto = _emitir_evento(Aviso(
                texto=(f"backend: {fila['modelo']} :{fila['puerto']} "
                       f"via {fila['via']}" + (f" rol={rol}" if rol else "")),
                origen="backend_activo"))
        except Exception:
            visto = False
        if not visto:
            # ascii: la consola de esta maquina es cp1252.
            print(f"[backend] via={fila['via']} modelo={fila['modelo']} "
                  f"puerto={fila['puerto']}" + (f" rol={rol}" if rol else ""),
                  file=sys.stderr, flush=True)
    return fila


def sin_backend(via: str, detalle: str = "") -> dict:
    """
    No habia backend. Esto NO es un estado normal: es el modo de fallo caro.

    Grita siempre (aunque COGNIA_BACKEND_LOG=0) y queda en el jsonl, para que
    una corrida que degrado se pueda distinguir despues de una que no.
    """
    global _ultimo
    fila = {
        "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "via": via,
        "url": None,
        "puerto": None,
        "modelo": None,
        "degradado": True,
        "detalle": detalle,
    }
    _ultimo = fila
    _append(fila)
    # Evento Degradado al bus (el renderer lo pinta ambar, una vez por turno)
    # y, si NADIE escucha, el grito clasico a stderr: la degradacion tiene que
    # verse en ambos mundos, con o sin REPL.
    visto = False
    try:
        from cognia.ux.events import Degradado
        visto = _emitir_evento(Degradado(
            donde=via,
            motivo=detalle or "no responde ningun servidor",
            # La orden que de verdad existe en una instalacion desde el
            # wheel: scripts/ NO viaja en el paquete, asi que sugerir
            # 'python scripts/servir_flota.py' era mandar al usuario a un
            # fichero que no tiene. El combo sale de flota.COMBO_DEFAULT
            # (ver orden_arrancar): 'pensar' a secas levanta gpt-oss, no el
            # cerebro principal.
            accion_sugerida=orden_arrancar()))
    except Exception:
        visto = False
    if not visto:
        print(f"[backend] DEGRADADO: '{via}' sin backend LLM -- "
              f"{detalle or 'no responde ningun servidor'}. "
              f"Arranca la flota: {orden_arrancar()}",
              file=sys.stderr, flush=True)
    return fila


def ultimo() -> dict:
    """El ultimo registro de este proceso ({} si no hubo ninguno)."""
    return dict(_ultimo)


def resetear_cache() -> None:
    """Tras reiniciar un server en el mismo puerto, el /props cacheado miente.

    Y con el, la sonda de capacidad: su cache esta indexado por (url, modelo)
    y el modelo lo saca de props(), asi que un swap en el mismo puerto dejaria
    al agente decidiendo el regimen con la medicion del modelo ANTERIOR.
    Import perezoso y guardado: capacidad importa este modulo (ciclo) y esto
    es instrumentacion — nada aqui puede lanzar.
    """
    _props_cache.clear()
    _props_sello.clear()
    try:
        from cognia.agent import capacidad
        capacidad.invalidar()
    except Exception:
        pass


# ── Chequeo de arranque ──────────────────────────────────────────────────────

# El modelo que la auditoria de flota del 2026-07-24 retiro ("redundante: ni
# coder, ni thinking, ni VL; ningun modulo lo rutea") y que aun asi atendia el
# chat, el agente y create_program el 25/07.
RETIRADOS = ("qwen2.5-7b-instruct",)

PUERTO_UNICO = 8080


def estado() -> dict:
    """Que backend hay AHORA: puerto, modelo, y si algo esta mal."""
    url = os.environ.get("COGNIA_LLM_URL") or f"http://127.0.0.1:{PUERTO_UNICO}"
    p = props(url, forzar=True)
    modelo = p.get("modelo", "")
    avisos = []
    if not p:
        avisos.append(
            f"NO HAY BACKEND en {url}. Cognia va a degradar a sus fallbacks. "
            f"Arranca: {orden_arrancar()}")
    else:
        for r in RETIRADOS:
            if r in modelo.lower():
                avisos.append(
                    f"El modelo servido ({modelo}) esta RETIRADO por la "
                    f"auditoria de flota del 2026-07-24. Ningun modulo deberia "
                    f"rutear a el.")
    return {"url": url, "modelo": modelo or None,
            "puerto": p.get("puerto") or _puerto_de(url), "avisos": avisos}


def chequeo_arranque(silencioso_si_ok: bool = False) -> bool:
    """
    Se corre al arrancar Cognia. Devuelve True si el backend esta sano.

    POR QUE EXISTE: "Cognia degrada en silencio" estaba escrito como leccion
    desde hace meses y el 2026-07-25 volvio a pasar (dos backends, el retirado
    sirviendo el chat). Una leccion en prosa no impide nada: no se ejecuta. Esto
    es la misma leccion convertida en un chequeo que corre solo y que se ve.
    """
    e = estado()
    if e["avisos"]:
        print("", file=sys.stderr)
        for a in e["avisos"]:
            print(f"  [!] BACKEND: {a}", file=sys.stderr)
        print("", file=sys.stderr)
        return False
    if not silencioso_si_ok:
        print(f"  backend: {e['modelo']} en :{e['puerto']}", file=sys.stderr)
    return True


if __name__ == "__main__":
    e = estado()
    print(f"url    : {e['url']}")
    print(f"puerto : {e['puerto']}")
    print(f"modelo : {e['modelo'] or 'NINGUNO'}")
    for a in e["avisos"]:
        print(f"AVISO  : {a}")
    filas, corruptas, est = leer_audit(max_lineas=500, con_estado=True)
    if corruptas:
        print(f"AVISO  : {corruptas} linea(s) corruptas en la cola del audit "
              f"({AUDIT})")
    if est == "ilegible":
        print(f"AVISO  : la auditoria {AUDIT} EXISTE pero no se pudo leer "
              f"(lock/permisos); esto NO es 'sin eventos'")
    sys.exit(0 if not e["avisos"] else 1)
