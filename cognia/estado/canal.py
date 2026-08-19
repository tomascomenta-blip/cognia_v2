# -*- coding: utf-8 -*-
"""
cognia/estado/canal.py
======================
EL CANAL DE ESTADO: un registro estructurado del turno, separado del canal de
PROSA y por construccion inmune a la compactacion.

POR QUE EXISTE (investigacion 2026-08-18, 36.611 mensajes de produccion):
todo lo que un agente sabe de su propio trabajo vive hoy DENTRO de la
conversacion. Cuando el contexto se comprime, un resumidor decide que
sobrevive. Un resumidor es bueno resumiendo y pesimo llevando la contabilidad:
el seguimiento de artefactos medido dio 2,19-2,45 sobre 5,0 y fue IDENTICO en
las tres implementaciones grandes (Factory, Anthropic, OpenAI). La causa no es
que un resumidor sea malo: es que la compactacion se diseno como un problema de
RESUMEN y no de CONTABILIDAD. Efecto colateral documentado ("governance decay"):
las restricciones de seguridad desaparecen del contexto activo tras varias
rondas y NO se emite ningun error.

La respuesta de este modulo son tres reglas, y las tres son verificables:
  (a) el estado se actualiza con hechos MEDIDOS (sha256 y bytes leidos del
      disco, exit code real del comando), nunca con lo que el modelo declara;
  (b) se serializa compacto y se reinyecta ENTERO en cada paso (`render`);
  (c) NUNCA pasa por el resumidor: el compactador toca la prosa, no este dict.

Lo que este modulo NO puede prometer: si el integrador manda `render(...)` al
resumidor, la inmunidad se pierde. La inmunidad es una propiedad del CABLEADO
(reinyectar el bloque tras compactar), no del texto. Por eso `conservacion()`
existe: es el chequeo que lo hace cumplir en vez de la promesa en prosa.

HONESTIDAD SOBRE LA MEDICION: con el canal cableado, el recall de restricciones
es 1,0 POR CONSTRUCCION mientras el bloque quepa en `tope_chars` (las
restricciones nunca se recortan: ver `render`). El numero informativo no es ese,
es el CONTRAFACTUAL: cuanto pierde el mismo turno sin el canal.

ESTILO: funciones planas y dicts (regla del repo). `EstadoVerificado` es una
FABRICA que devuelve un dict serializable, no una clase; asi el estado viaja por
JSON, se guarda, se compara y se testea sin instanciar nada.

API publica
-----------
    EstadoVerificado(objetivo="", turno=None)      -> dict (el registro del turno)
    anotar_fichero(estado, ruta, operacion, ok)    -> dict de ese fichero (MIDE sha/bytes)
    anotar_comando(estado, cmd, exit_code, salida) -> dict
    anotar_verificacion(estado, comando, ok)       -> dict
    anotar_decision(estado, texto, origen)         -> dict
    anotar_restriccion(estado, texto)              -> bool (False si ya estaba)
    anotar_pendiente(estado, texto)                -> bool
    resolver_pendiente(estado, texto)              -> bool
    render(estado, tope_chars=1200)                -> str  (lo que se reinyecta)
    conservacion(estado_antes, texto_post)         -> dict (recall de artefactos)
    sembrar_trazadores(estado, k=4, semilla=None)  -> [dict] hechos no inferibles
    comprobar_trazadores(estado, texto)            -> dict
    serializar(estado) / deserializar(txt)         -> str / dict
    guardar(estado, directorio=None)               -> ruta str
    cargar(turno, directorio=None)                 -> dict
    dir_estado()                                   -> Path (COGNIA_ESTADO_DIR o ~/.cognia/estado)
"""

import hashlib
import json
import os
import random
import re
import time
import unicodedata
from pathlib import Path

# Umbral de cobertura de tokens para dar por PRESENTE una restriccion en un
# texto compactado. Un resumidor reescribe: exigir substring exacto mediria
# "copiado literal", no "conservado". 0.6 = la mayoria del contenido
# distintivo sobrevivio. Es un parametro del INSTRUMENTO: se declara aca y no
# se toca por corrida (si se toca, deja de comparar).
UMBRAL_COBERTURA = 0.6

# Palabras vacias del espanol que no distinguen nada: si contaran, cualquier
# frase "coincidiria" con cualquier resumen y el recall saldria inflado.
_STOP = {
    "de", "la", "el", "los", "las", "que", "con", "por", "para", "del", "una",
    "uno", "sin", "este", "esta", "esto", "como", "mas", "muy", "hay", "son",
    "ser", "tiene", "sobre", "entre", "cuando", "donde", "pero", "porque",
    "todo", "toda", "nunca", "siempre", "debe", "hasta",
}


# ---------------------------------------------------------------- utilidades

def _ahora():
    return time.time()


def _norm(texto):
    """Minusculas sin tildes y con espacios colapsados. Se compara SIEMPRE aca:
    el resumidor cambia mayusculas y puntuacion todo el tiempo."""
    if not texto:
        return ""
    s = unicodedata.normalize("NFKD", str(texto))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s.lower()).strip()


def _tokens(texto):
    """Tokens distintivos: >=4 chars y fuera de _STOP. Se conservan '/', '.',
    '_' y '-' porque las rutas de fichero son el artefacto que mas importa."""
    crudos = re.findall(r"[a-z0-9_./\\-]+", _norm(texto))
    return [t for t in crudos if len(t) >= 4 and t not in _STOP]


def _cobertura(item, texto_norm):
    """Fraccion de tokens distintivos de `item` presentes en el texto."""
    toks = _tokens(item)
    if not toks:
        return 0.0
    vistos = sum(1 for t in toks if t in texto_norm)
    return vistos / float(len(toks))


def _presente(item, texto_norm, umbral=UMBRAL_COBERTURA):
    if not item:
        return False
    n = _norm(item)
    if n and n in texto_norm:
        return True
    return _cobertura(item, texto_norm) >= umbral


def _fichero_presente(ruta, texto_norm):
    """Un fichero cuenta como conservado si aparece su ruta o su nombre base.
    El nombre base tiene que ser distintivo (>=4 chars) para no contar 'a.py'
    dentro de cualquier palabra."""
    r = _norm(ruta)
    if r and r in texto_norm:
        return True
    base = _norm(os.path.basename(str(ruta)))
    if len(base) >= 4 and base in texto_norm:
        return True
    return False


def _sha_bytes(datos):
    return hashlib.sha256(datos).hexdigest()


# ------------------------------------------------------------------ registro

def EstadoVerificado(objetivo="", turno=None):
    """Crea el registro del turno. Devuelve un dict JSON-serializable.

    `turno` identifica el registro en disco; si falta se usa el reloj (el
    formato es fijo para que ordenar por nombre ordene por tiempo)."""
    t = _ahora()
    return {
        "turno": str(turno) if turno else time.strftime("t%Y%m%d-%H%M%S", time.localtime(t)),
        "objetivo": str(objetivo or ""),
        "ts_inicio": t,
        "pasos": 0,
        "ficheros": {},        # ruta -> {sha, bytes, ts, operacion, ok}
        "comandos": [],        # [{cmd, exit, ts, salida_corta}]
        "verificaciones": [],  # [{comando, ok, ts}]
        "decisiones": [],      # [{texto, ts, origen}]
        "restricciones": [],   # [str]  lo que NUNCA puede perderse
        "pendientes": [],      # [str]
        "trazadores": [],      # [{id, tipo, texto, ts}]
    }


def anotar_fichero(estado, ruta, operacion="escribir", ok=None, raiz=None):
    """Anota un fichero tocado MIDIENDO el disco: sha256 y bytes reales.

    POR QUE se mide y no se declara: el fallo tipico no es "el modelo miente",
    es "el modelo cree que escribio". Si el fichero no existe, `ok` sale False
    aunque el modelo haya dicho que lo creo."""
    p = Path(raiz) / ruta if raiz else Path(ruta)
    sha = None
    tam = 0
    existe = False
    try:
        datos = p.read_bytes()
        existe = True
        tam = len(datos)
        sha = _sha_bytes(datos)
    except OSError:
        existe = False
    entrada = {
        "sha": sha,
        "bytes": tam,
        "ts": _ahora(),
        "operacion": str(operacion),
        "ok": bool(existe) if ok is None else bool(ok),
        "existe": existe,
    }
    estado["ficheros"][str(ruta)] = entrada
    estado["pasos"] += 1
    return entrada


def anotar_comando(estado, cmd, exit_code, salida="", tope_salida=160):
    """Anota un comando con su exit code REAL y una cola corta de la salida.

    Se guarda la COLA y no la cabeza: el error util casi siempre esta al final
    (traceback, 'FAILED', 'error:')."""
    txt = str(salida or "")
    corta = txt[-tope_salida:] if len(txt) > tope_salida else txt
    corta = re.sub(r"\s+", " ", corta).strip()
    entrada = {
        "cmd": str(cmd),
        "exit": int(exit_code),
        "ts": _ahora(),
        "salida_corta": corta,
    }
    estado["comandos"].append(entrada)
    estado["pasos"] += 1
    return entrada


def anotar_verificacion(estado, comando, ok):
    """Una verificacion es un comando cuyo exit code decide si hubo PROGRESO.
    Es lo unico que permite decir 'llevas 400k tokens y cero tests en verde'."""
    entrada = {"comando": str(comando), "ok": bool(ok), "ts": _ahora()}
    estado["verificaciones"].append(entrada)
    estado["pasos"] += 1
    return entrada


def anotar_decision(estado, texto, origen="agente"):
    entrada = {"texto": str(texto), "ts": _ahora(), "origen": str(origen)}
    estado["decisiones"].append(entrada)
    estado["pasos"] += 1
    return entrada


def anotar_restriccion(estado, texto):
    """Devuelve False si ya estaba (idempotente): el mismo limite sembrado dos
    veces no debe contar dos veces en el recall."""
    t = str(texto).strip()
    if not t:
        return False
    if any(_norm(x) == _norm(t) for x in estado["restricciones"]):
        return False
    estado["restricciones"].append(t)
    return True


def anotar_pendiente(estado, texto):
    t = str(texto).strip()
    if not t or any(_norm(x) == _norm(t) for x in estado["pendientes"]):
        return False
    estado["pendientes"].append(t)
    return True


def resolver_pendiente(estado, texto):
    """Quita un pendiente. Casa por igualdad normalizada y, si no, por
    substring: el agente rara vez repite la frase exacta."""
    n = _norm(texto)
    if not n:
        return False
    for i, x in enumerate(estado["pendientes"]):
        if _norm(x) == n:
            estado["pendientes"].pop(i)
            return True
    for i, x in enumerate(estado["pendientes"]):
        nx = _norm(x)
        if nx and (nx in n or n in nx):
            estado["pendientes"].pop(i)
            return True
    return False


# -------------------------------------------------------------------- render

# Orden de prioridad. Lo de arriba sobrevive al recorte; lo de abajo se cae
# primero. Las restricciones estan primero porque su perdida es SILENCIOSA
# (governance decay): un fichero perdido se nota al siguiente paso, un limite
# de seguridad perdido no se nota nunca.
_ORDEN = ["restricciones", "ficheros", "pendientes", "verificaciones", "decisiones", "comandos"]

# Espacio reservado para la linea de recorte. Si el aviso no cabe, el recorte
# seria invisible, que es exactamente el fallo que este modulo ataca.
_RESERVA_AVISO = 110


def _lineas_seccion(estado, nombre):
    """Devuelve (cabecera, [lineas]) de una seccion. Determinista: sin ts
    absolutos (cambian entre corridas y romperian la comparacion byte a byte)."""
    if nombre == "restricciones":
        xs = estado.get("restricciones") or []
        return ("RESTRICCIONES (%d, NUNCA descartar):" % len(xs),
                ["  ! " + x for x in xs])
    if nombre == "ficheros":
        fs = estado.get("ficheros") or {}
        lineas = []
        for ruta, d in fs.items():
            marca = "OK   " if d.get("ok") else "FALLO"
            sha = (d.get("sha") or "-")[:8]
            lineas.append("  %s %s sha=%s %dB %s" % (
                marca, ruta, sha, d.get("bytes", 0), d.get("operacion", "")))
        return ("FICHEROS (%d):" % len(fs), lineas)
    if nombre == "pendientes":
        xs = estado.get("pendientes") or []
        return ("PENDIENTES (%d):" % len(xs), ["  - " + x for x in xs])
    if nombre == "verificaciones":
        vs = estado.get("verificaciones") or []
        oks = sum(1 for v in vs if v.get("ok"))
        cab = "VERIFICACIONES (%d): %d OK / %d FALLO" % (len(vs), oks, len(vs) - oks)
        # Solo se listan los FALLOS: un verde no aporta informacion accionable.
        return (cab, ["  FALLO " + v.get("comando", "") for v in vs if not v.get("ok")])
    if nombre == "decisiones":
        ds = estado.get("decisiones") or []
        return ("DECISIONES (%d):" % len(ds),
                ["  > %s [%s]" % (d.get("texto", ""), d.get("origen", "")) for d in ds])
    if nombre == "comandos":
        cs = estado.get("comandos") or []
        return ("COMANDOS (%d):" % len(cs),
                ["  exit=%d %s" % (c.get("exit", -1), c.get("cmd", "")) for c in cs])
    return ("", [])


def _construir(estado, presupuesto):
    """Arma el bloque respetando `presupuesto` chars. Devuelve
    (texto, omitidas, secciones_tocadas, chars_omitidos)."""
    cab = "[ESTADO VERIFICADO] turno=%s pasos=%d" % (
        estado.get("turno", "?"), estado.get("pasos", 0))
    obj = (estado.get("objetivo") or "").strip()
    partes = [cab]
    if obj:
        partes.append("OBJETIVO: " + obj)
    usado = sum(len(x) + 1 for x in partes)

    omitidas = 0
    chars_omit = 0
    tocadas = []
    for nombre in _ORDEN:
        cabecera, lineas = _lineas_seccion(estado, nombre)
        if not lineas:
            # Seccion vacia: no gasta presupuesto. EXCEPCION: verificaciones
            # sin fallos, cuya cabecera SI informa ("3 OK / 0 FALLO"). Es la
            # linea que responde "cuanto progreso verificado llevas".
            if not (nombre == "verificaciones" and (estado.get("verificaciones") or [])):
                continue
        # Las restricciones NO se recortan nunca, aunque revienten el tope. Es
        # una decision explicita: perderlas es el fallo que se esta atacando.
        forzada = (nombre == "restricciones")
        if not forzada and usado + len(cabecera) + 1 > presupuesto:
            omitidas += len(lineas)
            chars_omit += sum(len(x) + 1 for x in lineas) + len(cabecera) + 1
            tocadas.append(nombre)
            continue
        partes.append(cabecera)
        usado += len(cabecera) + 1
        cortadas = 0
        for ln in lineas:
            if not forzada and usado + len(ln) + 1 > presupuesto:
                cortadas += 1
                chars_omit += len(ln) + 1
                continue
            partes.append(ln)
            usado += len(ln) + 1
        if cortadas:
            omitidas += cortadas
            tocadas.append(nombre)
    return "\n".join(partes), omitidas, tocadas, chars_omit


def render(estado, tope_chars=1200):
    """El bloque que se reinyecta al modelo en CADA paso.

    Compacto, determinista y priorizado. Si no cabe, se recorta lo MENOS
    critico y se DICE cuanto se recorto: un recorte silencioso es lo mismo que
    la compactacion que este modulo reemplaza."""
    texto, omitidas, _t, _c = _construir(estado, tope_chars)
    if len(texto) <= tope_chars and not omitidas:
        return texto

    # Se rebaja el presupuesto para que el aviso de recorte entre. Se itera
    # porque el aviso cambia de largo al cambiar los conteos.
    presupuesto = max(0, tope_chars - _RESERVA_AVISO)
    salida = texto
    for _ in range(8):
        texto, omitidas, tocadas, chars_omit = _construir(estado, presupuesto)
        if omitidas:
            aviso = "[RECORTE: %d lineas omitidas (%d chars) de %s]" % (
                omitidas, chars_omit, ", ".join(sorted(set(tocadas))) or "-")
            salida = texto + "\n" + aviso
        else:
            salida = texto
        if len(salida) <= tope_chars:
            return salida
        presupuesto = max(0, presupuesto - (len(salida) - tope_chars) - 8)

    # Solo se llega aca si las restricciones solas pasan el tope. Se conservan
    # igual y se avisa: la alternativa (tirarlas) es el bug, no la solucion.
    return salida + "\n[AVISO: las restricciones exceden tope_chars=%d y se conservan igual]" % tope_chars


# --------------------------------------------------- metrica de conservacion

def conservacion(estado_antes, texto_post_compactacion):
    """EL TEST QUE NADIE REPORTA: recall de artefactos tras una compactacion.

    Dado el estado REAL (la contabilidad) y el contexto que sobrevivio a la
    compactacion (la prosa), mide cuantos artefactos siguen ahi. Es la metrica
    que la industria publica como 2,19-2,45 sobre 5,0; `escala_5` la deja en
    las mismas unidades para poder compararla.

    Devuelve {recall_ficheros, recall_restricciones, recall_trazadores,
              recall_global, perdidos, n, n_ficheros, n_restricciones,
              n_trazadores, escala_5}.
    `perdidos` lista los artefactos que ya no estan, con su tipo."""
    tn = _norm(texto_post_compactacion)
    perdidos = []

    ficheros = list((estado_antes.get("ficheros") or {}).keys())
    vivos_f = 0
    for ruta in ficheros:
        if _fichero_presente(ruta, tn):
            vivos_f += 1
        else:
            perdidos.append({"tipo": "fichero", "valor": ruta})

    restr = list(estado_antes.get("restricciones") or [])
    vivos_r = 0
    for r in restr:
        if _presente(r, tn):
            vivos_r += 1
        else:
            perdidos.append({"tipo": "restriccion", "valor": r})

    trz = list(estado_antes.get("trazadores") or [])
    vivos_t = 0
    for t in trz:
        # El trazador se busca por su ID: es la parte NO inferible. Si el
        # resumidor lo parafrasea sin el id, no lo conservo, lo invento.
        if _norm(t.get("id", "")) in tn:
            vivos_t += 1
        else:
            perdidos.append({"tipo": "trazador", "valor": t.get("id", "")})

    def _r(vivos, total):
        return (vivos / float(total)) if total else None

    n = len(ficheros) + len(restr) + len(trz)
    vivos = vivos_f + vivos_r + vivos_t
    rg = _r(vivos, n)
    return {
        "recall_ficheros": _r(vivos_f, len(ficheros)),
        "recall_restricciones": _r(vivos_r, len(restr)),
        "recall_trazadores": _r(vivos_t, len(trz)),
        "recall_global": rg,
        "perdidos": perdidos,
        "n": n,
        "n_ficheros": len(ficheros),
        "n_restricciones": len(restr),
        "n_trazadores": len(trz),
        "escala_5": (round(rg * 5.0, 2) if rg is not None else None),
    }


# ---------------------------------------------------------------- trazadores

_TIPOS_TRAZADOR = ("valor", "fichero_prohibido", "decision", "restriccion")


def sembrar_trazadores(estado, k=4, semilla=None):
    """Hechos-trazador verificables y NO inferibles del resto de la tarea.

    POR QUE: medir conservacion con los ficheros reales solo funciona si la
    tarea toco ficheros. Un trazador es un hecho con un ID aleatorio dentro:
    ningun resumidor puede reconstruirlo por sentido comun, asi que si aparece
    en el texto post-compactacion es porque SOBREVIVIO, no porque el modelo lo
    dedujo. Es el mismo truco que la aguja del needle-in-a-haystack, aplicado a
    la contabilidad.

    Los trazadores se guardan en el estado (viajan en `render`) y se devuelven
    para que el integrador los siembre TAMBIEN en la prosa: el contraste entre
    los dos canales es la medicion.

    `semilla` fija el generador para tests reproducibles."""
    rnd = random.Random(semilla) if semilla is not None else random.SystemRandom()
    nuevos = []
    base = len(estado.get("trazadores") or [])
    for i in range(int(k)):
        tipo = _TIPOS_TRAZADOR[(base + i) % len(_TIPOS_TRAZADOR)]
        ident = "TRZ-%06X" % rnd.randrange(16 ** 6)
        if tipo == "valor":
            texto = "el umbral acordado para %s es %d" % (ident, rnd.randrange(100, 999))
        elif tipo == "fichero_prohibido":
            texto = "NUNCA tocar el fichero legado_%s.py" % ident
        elif tipo == "decision":
            texto = "decision ya tomada: se descarto la via %s" % ident
        else:
            texto = "restriccion vigente: no publicar sin la firma %s" % ident
        trz = {"id": ident, "tipo": tipo, "texto": texto, "ts": _ahora()}
        estado.setdefault("trazadores", []).append(trz)
        # Cada trazador entra ademas en la seccion que le corresponde por su
        # tipo, y NO en una seccion propia. Si tuvieran seccion propia, el
        # recall con canal saldria 1,0 siempre y la medicion mediria el
        # instrumento: asi un trazador de tipo "decision" se pierde cuando el
        # tope recorta las decisiones, que es la degradacion que hay que ver.
        if tipo in ("restriccion", "fichero_prohibido"):
            anotar_restriccion(estado, texto)
        else:
            anotar_decision(estado, texto, origen="trazador")
        nuevos.append(trz)
    return nuevos


def comprobar_trazadores(estado, texto):
    """Cuantos trazadores siguen presentes en `texto`. Se busca por ID."""
    tn = _norm(texto)
    trz = list(estado.get("trazadores") or [])
    presentes, perdidos = [], []
    for t in trz:
        if _norm(t.get("id", "")) in tn:
            presentes.append(t["id"])
        else:
            perdidos.append(t["id"])
    return {
        "n": len(trz),
        "presentes": presentes,
        "perdidos": perdidos,
        "recall": (len(presentes) / float(len(trz))) if trz else None,
    }


# --------------------------------------------------------------- persistencia

def dir_estado():
    """COGNIA_ESTADO_DIR si esta puesta; si no, ~/.cognia/estado."""
    d = os.environ.get("COGNIA_ESTADO_DIR")
    return Path(d) if d else (Path.home() / ".cognia" / "estado")


def serializar(estado):
    """JSON compacto y ORDENADO: dos estados iguales dan bytes iguales, que es
    lo que permite diffear turnos y detectar que se perdio."""
    return json.dumps(estado, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def deserializar(texto):
    d = json.loads(texto)
    # Se rellenan las secciones que falten: un estado guardado por una version
    # vieja no debe reventar el render de la nueva.
    plantilla = EstadoVerificado()
    for k, v in plantilla.items():
        if k not in d:
            d[k] = type(v)() if isinstance(v, (dict, list)) else v
    return d


def guardar(estado, directorio=None):
    """Persistencia OPCIONAL para auditar despues. Devuelve la ruta escrita."""
    base = Path(directorio) if directorio else dir_estado()
    base.mkdir(parents=True, exist_ok=True)
    ruta = base / ("%s.json" % estado.get("turno", "sin-turno"))
    ruta.write_text(serializar(estado), encoding="utf-8")
    return str(ruta)


def cargar(turno, directorio=None):
    base = Path(directorio) if directorio else dir_estado()
    ruta = base / ("%s.json" % turno)
    return deserializar(ruta.read_text(encoding="utf-8"))
