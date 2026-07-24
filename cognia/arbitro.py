"""
cognia/arbitro.py — ARBITRO DE COLISIONES entre generadores
===========================================================
Cognia tiene VARIOS procesos que escriben archivos sobre el mismo workspace:
cognia/program_creator/ (generator.py, program_creator.py), la sintesis de
herramientas (cognia/agent/tool_synthesis.py), las tools de escritura del loop
ReAct (cognia/agent/tools.py) y los workers (cognia/agents/workers/dev_tools.py,
que resuelve el workspace en _root_actual()). Verificado leyendo el codigo:
HOY no hay ni un lock ni una deteccion de colision — el ultimo que escribe gana,
en silencio.

El pedido del dueno, literal: "cuando un generador rompa el trabajo de otro, un
arbitro lo detenga y le avise al cerebro".

QUE CUENTA COMO "ROMPER": no es escribir el mismo archivo (eso a veces es
legitimo: iterar sobre lo propio). Es DEJARLO PEOR DE LO QUE ESTABA:
  - PISA_AJENO: el archivo lo creo OTRO generador y este lo sobrescribe.
  - DESTRUYE:   el contenido nuevo pierde >60% del tamano, o convierte un .py
                que compilaba (ast.parse) en uno que NO compila.
  - OK:         todo lo demas.

MODO SOMBRA — ES EL DEFAULT.
  COGNIA_ARBITRO_SOMBRA=1 (o no definida)  -> observa, registra incidentes y
                                              DEJA PASAR la escritura.
  COGNIA_ARBITRO_SOMBRA=0                  -> arbitro con dientes: BLOQUEA.
El default es sombra a proposito: el arbitro se engancha a flujos que hoy
funcionan sin el, y un bloqueo mal calibrado los rompe de golpe. Primero se
miran los incidentes reales que junta el JSON, se calibran los umbrales con
esos datos, y recien despues se apaga la sombra.

BEST-EFFORT SIEMPRE: si el arbitro falla (JSON corrupto, disco lleno, permisos),
NUNCA debe romper al generador. Todas las entradas publicas estan envueltas en
try/except y ante duda DEJAN PASAR. Un arbitro caido es peor que no tener
arbitro solo si ademas bloquea.

Estado: un dict plano persistido en <workspace>/.arbitro.json, escrito atomico
(.tmp + replace) igual que cognia/agent/plan_artifact.py.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import time
from pathlib import Path

# ── Umbrales ───────────────────────────────────────────────────────────────
# Perder mas del 60% del tamano es la senal barata de "lo vacio". No es 100%
# (truncar a cero) porque el modo de fallo real que se busca es el generador
# que reescribe un modulo de 900 bytes con un esqueleto de 120: el archivo
# sigue existiendo y "parece" bien, pero el trabajo del otro desaparecio.
UMBRAL_PERDIDA = 0.60

# Debajo de esto no se juzga tamano: un archivo de 30 bytes puede pasar a 10
# sin que eso sea destruccion, y disparar ahi es puro ruido.
MINIMO_BYTES = 40

# Tope de incidentes guardados. El JSON vive en el workspace del agente y se
# lee en cada escritura; sin tope crece sin limite y encarece el camino feliz.
MAX_INCIDENTES = 200

NOMBRE_REGISTRO = ".arbitro.json"


# ── Ubicacion y forma del registro ─────────────────────────────────────────

def ruta_registro(registro=None) -> Path:
    """Ruta del .arbitro.json. Precedencia: argumento explicito (tests) >
    COGNIA_ARBITRO_REGISTRO > workspace del agente > ~/.cognia. Mismo patron
    call-time que _root_actual(): un proceso largo que cambia de workspace
    entre tareas no debe quedar anclado al primero."""
    if registro:
        return Path(registro)
    env = os.environ.get("COGNIA_ARBITRO_REGISTRO")
    if env:
        return Path(env)
    try:
        from cognia.agents.workers.dev_tools import _root_actual
        base = Path(_root_actual())
    except Exception:
        base = Path.home() / ".cognia"
    return base / NOMBRE_REGISTRO


def _estado_vacio() -> dict:
    # propiedad: {clave_de_ruta: {generador, bytes, sha, mtime, ts, ruta}}
    # incidentes: lista append-only (recortada a MAX_INCIDENTES)
    return {"version": 1, "propiedad": {}, "incidentes": [], "seq": 0}


def _clave(ruta) -> str:
    """Identidad de un archivo, estable entre rutas relativas/absolutas.
    normcase porque en Windows Motor.py y motor.py son EL MISMO archivo y si
    no se normaliza el arbitro cree que son dos y no ve la colision."""
    try:
        return os.path.normcase(str(Path(ruta).resolve()))
    except Exception:
        return os.path.normcase(str(ruta))


def cargar(registro=None) -> dict:
    """Lee el registro. Un JSON corrupto NO es fatal: se arranca de cero."""
    path = ruta_registro(registro)
    try:
        if not path.is_file():
            return _estado_vacio()
        d = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(d, dict):
            return _estado_vacio()
        base = _estado_vacio()
        base.update({k: d[k] for k in ("propiedad", "incidentes", "seq") if k in d})
        if not isinstance(base["propiedad"], dict):
            base["propiedad"] = {}
        if not isinstance(base["incidentes"], list):
            base["incidentes"] = []
        return base
    except Exception:
        return _estado_vacio()


def guardar(estado: dict, registro=None) -> bool:
    """Escritura atomica (.tmp + replace), como plan_artifact.Plan.guardar.
    Hay varios generadores escribiendo a la vez: un write_text directo puede
    dejar el registro a medias y el arbitro se queda ciego."""
    path = ruta_registro(registro)
    try:
        estado["incidentes"] = estado.get("incidentes", [])[-MAX_INCIDENTES:]
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(estado, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        tmp.replace(path)
        return True
    except Exception:
        return False


# ── Huella de un contenido ─────────────────────────────────────────────────

def huella(contenido) -> dict:
    """Tamano + sha256 corto. El sha corto (12 hex) alcanza: no es defensa
    criptografica, es para decir 'esto ya no es lo que yo escribi'.

    Los fines de linea se normalizan a \\n ANTES de medir. Medido en Windows:
    dev_tools.write_file hace resolved.write_text(content), y write_text abre
    en modo texto con newline=None, o sea traduce cada \\n a \\r\\n. Un
    contenido de 900 bytes queda de 990 en disco. Sin normalizar, la huella de
    lo que el generador tiene en memoria NUNCA coincide con la del archivo: el
    arbitro no reconocia ni una reescritura identica (la marcaba PISA_AJENO) y
    los tamanos del aviso al cerebro mentian."""
    if isinstance(contenido, str):
        datos = contenido.replace("\r\n", "\n").encode("utf-8", errors="replace")
    else:
        datos = bytes(contenido or b"").replace(b"\r\n", b"\n")
    return {"bytes": len(datos),
            "sha": hashlib.sha256(datos).hexdigest()[:12]}


def _huella_en_disco(ruta) -> dict | None:
    try:
        p = Path(ruta)
        if not p.is_file():
            return None
        datos = p.read_bytes()
        h = huella(datos)
        h["mtime"] = p.stat().st_mtime
        return h
    except Exception:
        return None


def _texto(contenido) -> str:
    if isinstance(contenido, str):
        return contenido
    try:
        return bytes(contenido or b"").decode("utf-8", errors="replace")
    except Exception:
        return ""


def _compila(texto: str) -> bool:
    try:
        ast.parse(texto)
        return True
    except SyntaxError:
        return False
    except Exception:
        # ValueError por NUL bytes, RecursionError en fuentes patologicas...
        # Ante duda decimos que compila: el arbitro no inventa danos.
        return True


# ── Registro de PROPIEDAD ──────────────────────────────────────────────────

def registrar_creacion(generador: str, ruta, contenido, registro=None) -> bool:
    """Anota que `generador` es el dueno de `ruta` con la huella de lo escrito.
    Si ya habia dueno, se ACTUALIZA la huella pero el dueno original se
    conserva: quien creo el archivo es un hecho historico, y es justo el dato
    que hace falta despues para decir 'esto lo hizo otro'."""
    try:
        estado = cargar(registro)
        k = _clave(ruta)
        previo = estado["propiedad"].get(k) or {}
        h = huella(contenido)
        estado["propiedad"][k] = {
            "generador": previo.get("generador") or generador,
            "ultimo_escritor": generador,
            "ruta": str(ruta),
            "bytes": h["bytes"],
            "sha": h["sha"],
            "mtime": (_huella_en_disco(ruta) or {}).get("mtime", 0.0),
            "ts": time.time(),
        }
        return guardar(estado, registro)
    except Exception:
        return False


def dueno_de(ruta, registro=None) -> str | None:
    try:
        return (cargar(registro)["propiedad"].get(_clave(ruta)) or {}).get("generador")
    except Exception:
        return None


def propiedad(registro=None) -> dict:
    """Registro completo de propiedad (para inspeccion / debug)."""
    try:
        return cargar(registro).get("propiedad", {})
    except Exception:
        return {}


# ── El veredicto ───────────────────────────────────────────────────────────

def revisar_escritura(generador: str, ruta, contenido_nuevo, registro=None) -> dict:
    """Juzga una escritura ANTES de que ocurra. No tiene efectos: no escribe
    el registro ni bloquea. Devuelve
    {"veredicto","motivo","detalle","generador_dueno"} con veredicto en
    OK / PISA_AJENO / DESTRUYE.

    DESTRUYE gana sobre PISA_AJENO cuando aplican los dos, a proposito: el
    dano concreto es mas informativo para el cerebro que la colision sola, y
    el detalle igual nombra al dueno pisado."""
    veredicto = {"veredicto": "OK", "motivo": "", "detalle": "",
                 "generador_dueno": None, "ruta": str(ruta),
                 "generador": generador, "bytes_actual": 0, "bytes_nuevo": 0}
    try:
        estado = cargar(registro)
        prop = estado["propiedad"].get(_clave(ruta)) or {}
        dueno = prop.get("generador")
        veredicto["generador_dueno"] = dueno
        ajeno = bool(dueno) and dueno != generador

        # Huella actual: el DISCO manda sobre el registro. Si alguien escribio
        # por fuera del arbitro, lo que importa es lo que se va a perder de
        # verdad, no lo que el JSON cree que hay.
        actual = _huella_en_disco(ruta)
        if actual is None and prop:
            actual = {"bytes": prop.get("bytes", 0), "sha": prop.get("sha", "")}

        # Archivo nuevo y sin dueno: nada que romper.
        if not actual:
            return veredicto

        nuevo = huella(contenido_nuevo)
        bytes_actual, bytes_nuevo = actual.get("bytes", 0), nuevo["bytes"]
        veredicto["bytes_actual"], veredicto["bytes_nuevo"] = bytes_actual, bytes_nuevo

        if nuevo["sha"] and nuevo["sha"] == actual.get("sha"):
            # Reescribir identico no rompe a nadie, ni siquiera si es ajeno.
            veredicto["detalle"] = "contenido identico al actual"
            return veredicto

        es_py = str(ruta).lower().endswith(".py")
        if es_py:
            texto_actual = None
            try:
                p = Path(ruta)
                texto_actual = p.read_text(encoding="utf-8", errors="replace") \
                    if p.is_file() else None
            except Exception:
                texto_actual = None
            if texto_actual is not None and _compila(texto_actual) \
                    and not _compila(_texto(contenido_nuevo)):
                veredicto["veredicto"] = "DESTRUYE"
                veredicto["motivo"] = "sintaxis rota"
                veredicto["detalle"] = (
                    f"{Path(str(ruta)).name} compilaba y el contenido nuevo no "
                    f"pasa ast.parse")
                return veredicto

        if bytes_actual >= MINIMO_BYTES and \
                bytes_nuevo < bytes_actual * (1.0 - UMBRAL_PERDIDA):
            perdido = 100.0 * (bytes_actual - bytes_nuevo) / max(bytes_actual, 1)
            veredicto["veredicto"] = "DESTRUYE"
            veredicto["motivo"] = "perdida de tamano"
            veredicto["detalle"] = (
                f"{Path(str(ruta)).name} pasa de {bytes_actual} a {bytes_nuevo} "
                f"bytes (-{perdido:.0f}%)")
            return veredicto

        if ajeno:
            veredicto["veredicto"] = "PISA_AJENO"
            veredicto["motivo"] = "archivo de otro generador"
            veredicto["detalle"] = (
                f"{Path(str(ruta)).name} lo creo '{dueno}' y '{generador}' lo "
                f"sobrescribe ({bytes_actual} -> {bytes_nuevo} bytes)")
            return veredicto

        return veredicto
    except Exception as e:
        # Un arbitro roto no acusa a nadie.
        veredicto["detalle"] = f"arbitro no pudo revisar: {e}"
        return veredicto


# ── Sombra / bloqueo ───────────────────────────────────────────────────────

def modo_sombra() -> bool:
    """True = observa y NO bloquea. Default True (ver cabecera del modulo).
    Lectura en call-time: un test o un flujo puede cambiar la env var en
    caliente y el arbitro tiene que enterarse sin reimportar."""
    v = (os.environ.get("COGNIA_ARBITRO_SOMBRA") or "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def registrar_incidente(veredicto: dict, sombra: bool, registro=None) -> dict:
    """Guarda el incidente en el JSON, pendiente de aviso al cerebro."""
    inc = {}
    try:
        estado = cargar(registro)
        estado["seq"] = int(estado.get("seq", 0)) + 1
        inc = {
            "id": estado["seq"],
            "ts": time.time(),
            "generador": veredicto.get("generador", ""),
            "generador_dueno": veredicto.get("generador_dueno"),
            "ruta": veredicto.get("ruta", ""),
            "veredicto": veredicto.get("veredicto", ""),
            "motivo": veredicto.get("motivo", ""),
            "detalle": veredicto.get("detalle", ""),
            "bytes_actual": veredicto.get("bytes_actual", 0),
            "bytes_nuevo": veredicto.get("bytes_nuevo", 0),
            "sombra": bool(sombra),
            "bloqueado": not sombra,
            "avisado": False,
        }
        estado["incidentes"].append(inc)
        guardar(estado, registro)
    except Exception:
        pass
    return inc


def detener(veredicto: dict, registro=None) -> bool:
    """Decide si la escritura sigue. Devuelve False = DETENIDA (bloqueada),
    True = puede seguir. PISA_AJENO y DESTRUYE se registran SIEMPRE como
    incidente; en modo sombra igual devuelve True (observa, no bloquea)."""
    try:
        v = (veredicto or {}).get("veredicto", "OK")
        if v not in ("PISA_AJENO", "DESTRUYE"):
            return True
        sombra = modo_sombra()
        registrar_incidente(veredicto, sombra, registro)
        return bool(sombra)
    except Exception:
        return True


def permitir_escritura(generador: str, ruta, contenido_nuevo, registro=None):
    """Entrada unica para los generadores. Devuelve (puede_escribir, veredicto).

    Uso previsto en cualquier generador, sin importar como escriba:

        ok, v = arbitro.permitir_escritura("program_creator", ruta, contenido)
        if not ok:
            return f"ARBITRO: {v['detalle']}"
        ...escribir...
        arbitro.confirmar_escritura("program_creator", ruta, contenido)

    Nunca levanta: ante cualquier fallo interno devuelve (True, veredicto OK).
    """
    try:
        v = revisar_escritura(generador, ruta, contenido_nuevo, registro)
        return detener(v, registro), v
    except Exception as e:
        return True, {"veredicto": "OK", "motivo": "",
                      "detalle": f"arbitro fallo: {e}", "generador_dueno": None}


def confirmar_escritura(generador: str, ruta, contenido, registro=None) -> bool:
    """Se llama DESPUES de escribir con exito: fija/actualiza la propiedad.
    Separado de permitir_escritura a proposito — registrar como dueno a alguien
    cuya escritura despues fallo deja el registro mintiendo."""
    return registrar_creacion(generador, ruta, contenido, registro)


# ── AVISO AL CEREBRO ───────────────────────────────────────────────────────

def incidentes_pendientes(registro=None) -> list:
    """Incidentes que todavia no se le contaron al cerebro."""
    try:
        return [i for i in cargar(registro).get("incidentes", [])
                if not i.get("avisado")]
    except Exception:
        return []


def marcar_avisados(ids=None, registro=None) -> int:
    """Marca incidentes como ya contados. Sin `ids`, marca todos los pendientes.
    Devuelve cuantos marco."""
    try:
        estado = cargar(registro)
        objetivo = set(ids) if ids is not None else None
        n = 0
        for i in estado.get("incidentes", []):
            if i.get("avisado"):
                continue
            if objetivo is None or i.get("id") in objetivo:
                i["avisado"] = True
                n += 1
        if n:
            guardar(estado, registro)
        return n
    except Exception:
        return 0


def _frase(inc: dict) -> str:
    """Una linea por incidente, en el idioma del cerebro: quien, a quien, que
    archivo, que dano y si lo detuve. Se arma con los campos estructurados del
    incidente (no recortando el detalle) para que la frase quede natural:
    'El generador X intento pisar motor.py, que creo Y, reduciendolo de 900 a
    120 bytes. Lo detuve.'"""
    gen = inc.get("generador") or "un generador"
    archivo = Path(str(inc.get("ruta", ""))).name or "un archivo"
    dueno = inc.get("generador_dueno")
    de_quien = f", que creo '{dueno}'" if dueno and dueno != gen else ""

    motivo = inc.get("motivo") or ""
    if motivo == "perdida de tamano":
        dano = (f", reduciendolo de {inc.get('bytes_actual', 0)} a "
                f"{inc.get('bytes_nuevo', 0)} bytes")
    elif motivo == "sintaxis rota":
        dano = ", dejandolo sin compilar (ast.parse falla)"
    else:
        dano = ""

    cierre = ("Lo detuve." if inc.get("bloqueado")
              else "NO lo detuve (modo sombra), solo lo registre.")
    return f"El generador '{gen}' intento pisar {archivo}{de_quien}{dano}. {cierre}"


def aviso_para_el_cerebro(registro=None, max_n: int = 3, marcar: bool = False) -> str:
    """Texto corto y accionable listo para inyectar en el prompt del cerebro.
    Cadena vacia si no hay nada que avisar (asi el caller puede hacer
    `if aviso: prompt += aviso` sin ensuciar el prompt en el caso normal).

    `marcar=True` los da por avisados en la misma llamada; el default es False
    para que el enganche pueda marcar recien cuando el prompt SALIO de verdad.
    """
    try:
        pend = incidentes_pendientes(registro)
        if not pend:
            return ""
        ultimos = pend[-max_n:]
        cab = ("AVISO DEL ARBITRO DE COLISIONES "
               f"({len(pend)} incidente{'s' if len(pend) != 1 else ''}):")
        lineas = [cab] + [f"- {_frase(i)}" for i in ultimos]
        if len(pend) > len(ultimos):
            lineas.append(f"- (+{len(pend) - len(ultimos)} incidentes mas en "
                          f"{NOMBRE_REGISTRO})")
        lineas.append("Revisa quien tiene que escribir ese archivo antes de "
                      "volver a mandarlo a generar.")
        texto = "\n".join(lineas)
        if marcar:
            marcar_avisados([i.get("id") for i in ultimos], registro)
        return texto
    except Exception:
        return ""
