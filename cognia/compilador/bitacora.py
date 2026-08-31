"""
cognia/compilador/bitacora.py
=============================
EL REGISTRO de todo lo que el compilador de herramientas ha creado, con su
evidencia, para poder listarlo, auditarlo y revertirlo.

POR QUE EXISTE. `injertador.py` edita cli.py, cli_visibilidad.py y ayuda.py:
o sea, el producto entero. Sin un registro, un mes despues nadie puede
contestar tres preguntas que SI tienen respuesta y hay que poder dar:

  1. Que comandos de este CLI los escribio Cognia y cuales el duenio.
  2. Con que evidencia se dieron por buenos (que criterios, que veredicto,
     que dijeron los guardianes) -- porque "paso los tests" no es una
     afirmacion auditable si no se guarda CUAL test y CUANDO.
  3. Como se deshace uno: con que copia de seguridad y con que codigo, si
     el fuente del handler ya no esta en el fichero.

Sin esto el compilador es una caja negra que escribe en el CLI. Con esto es
un cambio con recibo.

COMO SE GUARDA, Y POR QUE ASI

  - Los EVENTOS (creada / evaluada / marcada) van a un JSONL **append-only**
    con fsync. Es el historial y es la VERDAD: nada se reescribe, nada se
    borra, y un fichero cortado a mitad pierde como mucho la ultima linea
    (que al leer se salta). Un historial que se reescribe no es un historial.
  - El ESTADO ACTUAL (que comando esta vivo, retirado o fallido) va a un JSON
    chico escrito de forma ATOMICA (tmp + os.replace). Es una CACHE derivable:
    si desaparece o se corrompe, se reconstruye desde los eventos y se vuelve
    a dejar en disco. Por eso el JSONL es el que manda.
  - El CODIGO GENERADO (handler y modulo) se copia a la ficha en disco. No se
    referencia el fuente: revertir tiene que funcionar DESPUES de que alguien
    haya retirado el comando de cli.py, que es justo cuando el fuente ya no
    esta. Mismo motivo por el que `clases/almacen.py` copia los adjuntos en
    vez de guardar la ruta original.

Las tres primitivas de disco (apendar con fsync, guardar_json con tmp+replace,
leer_jsonl que salta lineas rotas) se IMPORTAN de `cognia/clases/almacen.py`
en lugar de copiarse: ya estan verificadas por una jornada de clase real y
duplicarlas solo garantiza que un dia una de las dos copias pierda el fsync.

RELOJ. Ninguna funcion mira el reloj por su cuenta: `ahora` entra por
parametro con default `time.time()`. Un modulo que llama a time.time() dentro
de la logica solo se puede testear con sleeps y tolerancias, y eso es un test
que un dia parpadea.

DISPOSICION EN DISCO

    ~/.cognia/compilador/          (COGNIA_COMPILADOR_DIR la mueve)
      eventos.jsonl                {t,evento,cmd,...}      append-only
      indice.json                  {cmd: ficha}            atomico (cache)
      fichas/<cmd>/ficha.json      la evidencia completa   atomico
      fichas/<cmd>/handler.py      codigo generado
      fichas/<cmd>/modulo.py       codigo generado
      copias/<sello>/              las hace el injertador y NO se mueven con
                                   COGNIA_COMPILADOR_DIR: injertador.DIR_COPIAS
                                   esta clavado en ~/.cognia. Aqui solo se
                                   guarda el sello; quien revierta lo busca en
                                   el HOME, no en esta carpeta.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

# Se reusan las primitivas de disco ya verificadas en produccion (jornadas de
# clase de 6 horas): apendar hace fsync, guardar_json es tmp+os.replace, y
# leer_jsonl salta la linea rota del final en vez de reventar.
from cognia.clases.almacen import apendar, guardar_json, leer_json, leer_jsonl

_log = logging.getLogger(__name__)

EVENTOS = "eventos.jsonl"
INDICE = "indice.json"
DIR_FICHAS = "fichas"

# Los tres unicos estados. Cerrado a proposito: un estado libre en texto
# convierte listar(estado=...) en una loteria de erratas.
ESTADOS = ("viva", "retirada", "fallida")

# Las claves del dict del generador que traen FUENTE. El resto ('via',
# 'ruta_modulo', 'ruta_tests') son metadatos y no se escriben como .py.
CLAVES_CODIGO = ("handler", "modulo", "tests")


def dir_bitacora() -> Path:
    """~/.cognia/compilador, creada. COGNIA_COMPILADOR_DIR la mueve.

    La variable de entorno no es un lujo de tests: sin ella los tests
    escribirian en la bitacora REAL del duenio y el listado de sus comandos
    quedaria lleno de /foo de prueba.
    """
    env = os.environ.get("COGNIA_COMPILADOR_DIR", "").strip()
    base = Path(env) if env else Path.home() / ".cognia" / "compilador"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _ruta_eventos() -> Path:
    return dir_bitacora() / EVENTOS


def _ruta_indice() -> Path:
    return dir_bitacora() / INDICE


def _norm(cmd) -> str:
    """La clave canonica de un comando: '/algo'. Sin excepciones.

    `registrar` anadia la barra que faltase y `marcar`/`obtener` no, asi que
    `orquesta._registrar()` daba de alta '/x' y acto seguido marcaba 'x': el
    marcado se perdia con un warning en el log y la herramienta que el
    evaluador habia RECHAZADO se quedaba 'viva' en el indice. Un rechazo que
    se lee como aprobado es el peor fallo que puede tener una bitacora, asi
    que la normalizacion vive en un sitio y la usan TODAS las puertas.
    """
    c = str(cmd or "").strip()
    if not c:
        return ""
    return c if c.startswith("/") else "/" + c


def _slug(cmd: str) -> str:
    """Nombre de carpeta seguro para un comando. '/mi-cmd' -> 'mi-cmd'.

    El comando viene de una descripcion en lenguaje natural, o sea que puede
    traer cualquier cosa; nada de lo que traiga puede salirse de fichas/.
    """
    limpio = "".join(c if (c.isalnum() or c in "-_") else "-"
                     for c in (cmd or "").strip().lstrip("/"))
    limpio = limpio.strip("-_")[:60]
    return limpio or "sin-nombre"


def _dir_ficha(cmd: str, fila=None) -> Path:
    """La carpeta de la ficha, SIEMPRE dentro de la bitacora activa.

    La ficha guarda su 'ruta' absoluta, y esa ruta es de la maquina y del
    directorio en los que se registro. Honrarla a ciegas hace que, con
    COGNIA_COMPILADOR_DIR puesto o la carpeta movida, se lea la evidencia de
    OTRA bitacora (o de un tmp_path de test que ya no existe). La ruta
    guardada solo vale si sigue cayendo dentro de esta bitacora.
    """
    base = dir_bitacora()
    guardada = (fila or {}).get("ruta")
    if guardada:
        p = Path(guardada)
        try:
            if p.is_absolute() and p.resolve().is_relative_to(base.resolve()):
                return p
        except (OSError, ValueError):
            pass
    return base / DIR_FICHAS / _slug(cmd)


def _a_dict(obj) -> dict:
    """Un dict JSON-serializable a partir de lo que llegue.

    `espec` y `evaluacion` los producen otros modulos del compilador
    (generador, evaluador) y pueden ser dict o dataclass segun quien llame.
    Aqui se acepta lo que venga y se deja plano: la bitacora no puede ser el
    sitio donde el pipeline se rompe por una diferencia de tipo, porque
    entonces el injerto ya esta hecho y sin registrar (que es el peor estado).
    """
    if obj is None:
        return {}
    if isinstance(obj, dict):
        crudo = dict(obj)
    elif hasattr(obj, "_asdict"):                    # namedtuple
        crudo = dict(obj._asdict())
    elif hasattr(obj, "__dict__"):                   # dataclass u objeto
        crudo = {k: v for k, v in vars(obj).items() if not k.startswith("_")}
    else:
        return {"valor": str(obj)}
    # Round-trip por JSON con default=str: si algo no es serializable (un
    # Path, un datetime) se guarda su texto en vez de tirar el registro.
    try:
        return json.loads(json.dumps(crudo, ensure_ascii=False, default=str))
    except (TypeError, ValueError) as exc:
        # `default=str` NO cubre ni una referencia circular ni una clave que no
        # sea de tipo basico: eso lanza. Y lanzar aqui contradice el parrafo de
        # arriba, porque cuando esto corre el injerto YA esta hecho: quedarse
        # sin registro de un cambio ya aplicado a cli.py es el peor estado.
        _log.error("bitacora: %s no serializable (%s); se guarda campo a campo",
                   type(obj).__name__, exc)
        salvado = {}
        for k, v in crudo.items():
            try:
                salvado[str(k)] = json.loads(
                    json.dumps(v, ensure_ascii=False, default=str))
            except (TypeError, ValueError):
                salvado[str(k)] = str(v)
        salvado["aviso_bitacora"] = ("campos no serializables guardados como "
                                     "texto: %s" % exc)
        return salvado


def _primero(d: dict, claves, defecto=""):
    """El primer valor no vacio entre varias claves alternativas.

    Los modulos vecinos aun se estan escribiendo y no hay garantia de que
    llamen 'criterios' a lo mismo; se aceptan los alias conocidos en vez de
    perder la evidencia por un nombre.
    """
    for k in claves:
        v = d.get(k)
        if v not in (None, "", [], {}):
            return v
    return defecto


def _criterios(espec: dict, evaluacion: dict) -> list:
    """Los criterios de aceptacion normalizados a [{'texto','ok'}].

    Se miran los dos lados: la espec dice que se pedia, la evaluacion dice
    cual se cumplio. Si solo hay uno, se usa ese; sin criterios, la ficha
    seria un veredicto sin razones.

    LA FORMA REAL MANDA. `especificacion.py` produce criterios
    {'invocacion': '/clima estado', 'espera': 'imprime la config activa'}, no
    {'texto': ...}. Mirando solo los alias de 'texto', la ficha guardaba el
    json.dumps CRUDO del criterio como si fuese su enunciado. Se leen las dos
    formas porque las dos existen: la del generador de hoy y la que traiga un
    modulo vecino manana.
    """
    crudos = _primero(evaluacion, ("criterios", "criterios_aceptacion",
                                   "aceptacion", "pruebas"), None)
    if not isinstance(crudos, list):        # 'pruebas' puede venir como dict, y
        crudos = None                       # iterarlo daria las CLAVES por criterio
    if not crudos:
        crudos = _primero(espec, ("criterios", "criterios_aceptacion",
                                  "aceptacion", "postcondiciones"), None)
        if not isinstance(crudos, list):
            crudos = None
    fuera = []
    for c in (crudos or []):
        if isinstance(c, dict):
            invoc = str(_primero(c, ("invocacion", "comando", "teclear"), ""))
            espera = str(_primero(c, ("espera", "esperado", "postcondicion"), ""))
            if invoc or espera:
                texto = " -> ".join(x for x in (invoc, espera) if x)
            else:
                texto = str(_primero(c, ("texto", "criterio", "nombre", "que"),
                                     json.dumps(c, ensure_ascii=False)))
            ok = c.get("ok", c.get("paso", c.get("cumple")))
            fuera.append({"texto": texto,
                          "ok": None if ok is None else bool(ok)})
        else:
            fuera.append({"texto": str(c), "ok": None})
    return fuera


def _fases(evaluacion: dict) -> list:
    """Las fases EJECUTADAS del examen, normalizadas a [{fase, ok, detalle}].

    Esta es la evidencia de verdad y faltaba ENTERA. `evaluador.evaluar()` no
    devuelve un ok por criterio: devuelve las CINCO fases que corrio
    (sintaxis, guardianes, tests, invocacion, criterios) con su detalle, y el
    veredicto es 'aprobada' solo si las cinco dieron ok. Guardar el veredicto
    y tirar las fases deja la ficha contestando "aprobada" a la pregunta "y
    esto por que se dio por bueno", que es no contestarla.
    """
    crudas = _primero(evaluacion, ("fases", "etapas"), None)
    if not isinstance(crudas, list):
        return []
    fuera = []
    for f in crudas:
        if not isinstance(f, dict):
            fuera.append({"fase": str(f), "ok": None, "detalle": ""})
            continue
        ok = f.get("ok")
        fuera.append({
            "fase": str(_primero(f, ("fase", "nombre", "etapa"), "?")),
            "ok": None if ok is None else bool(ok),
            "detalle": str(_primero(f, ("detalle", "motivo", "resumen"), ""))[:300],
        })
    return fuera


def _veredicto(evaluacion: dict) -> str:
    """El veredicto legible de la evaluacion, o 'sin evaluar'.

    'sin evaluar' se dice con todas las letras y no se deja vacio: no lo
    evaluaron y lo evaluaron mal tienen que verse distintos desde fuera
    (es la leccion del vacio silencioso de este repo).
    """
    v = _primero(evaluacion, ("veredicto", "resultado", "estado"), "")
    if v:
        return str(v)
    if not evaluacion:
        return "sin evaluar"
    ok = evaluacion.get("ok")
    if ok is None:
        return "sin evaluar"
    return "APTA" if ok else "NO APTA"


def _guardar_codigo(destino: Path, codigo) -> dict:
    """Escribe el codigo generado junto a la ficha. Devuelve {nombre: ruta}.

    Acepta un str (el handler, que es lo que recibe injertar()) o un dict
    {'handler':..., 'modulo':..., 'tests':...}. Se guarda tal cual, sin
    validar: la bitacora registra lo que PASO, incluso el codigo de un
    injerto que fallo -- que es precisamente el que hay que poder leer luego.

    Lo que NO se guarda es lo que no es codigo. `orquesta.py` pasa el dict
    ENTERO del generador, que ademas del fuente lleva 'ruta_modulo',
    'ruta_tests' y 'via': escribirlas dejaba en la ficha un via.py con la
    palabra "modelo" dentro y tres lineas "codigo <clave> ...py" que no son el
    codigo de nada. Se aceptan las claves de fuente conocidas y, para no
    perder lo que anada un modulo vecino, cualquier valor multilinea.
    """
    if not codigo:
        return {}
    if isinstance(codigo, str):
        codigo = {"handler": codigo}
    if not isinstance(codigo, dict):
        _log.warning("bitacora: codigo de tipo %s ignorado", type(codigo).__name__)
        return {}
    destino.mkdir(parents=True, exist_ok=True)
    rutas = {}
    for nombre, texto in codigo.items():
        if not isinstance(texto, str) or not texto.strip():
            continue
        if nombre not in CLAVES_CODIGO and "\n" not in texto.strip():
            _log.debug("bitacora: %r (%r) no es fuente, no se guarda como .py",
                       nombre, texto[:40])
            continue
        fichero = destino / ("%s.py" % _slug(str(nombre)))
        try:
            fichero.write_text(texto, encoding="utf-8", newline="\n")
        except OSError as exc:                        # nunca en silencio
            _log.error("bitacora: no pude guardar %s: %s", fichero, exc)
            continue
        rutas[str(nombre)] = str(fichero)
    return rutas


# ── Escritura ────────────────────────────────────────────────────────────────

def _evento(tipo: str, cmd: str, ahora: float, **extra) -> dict:
    reg = {"t": float(ahora), "evento": tipo, "cmd": cmd}
    reg.update(extra)
    apendar(_ruta_eventos(), reg)
    return reg


def _indice() -> dict:
    """El indice de estado. Si falta o esta roto, se reconstruye del JSONL.

    El indice es cache derivable y los eventos son la verdad: por eso aqui se
    puede perder el fichero sin perder la bitacora, y por eso reconstruir no
    es un modo de emergencia sino el camino normal cuando no cuadra.
    """
    datos = leer_json(_ruta_indice(), None)
    if isinstance(datos, dict) and isinstance(datos.get("comandos"), dict):
        return datos
    if not _ruta_eventos().exists():
        return {"version": 1, "comandos": {}}
    # Que el indice este roto es un aviso; que no exista todavia es normal la
    # primera vez. No pueden verse igual en el log o el aviso deja de avisar.
    if _ruta_indice().exists():
        _log.warning("bitacora: %s ilegible, reconstruyendo desde %s",
                     INDICE, EVENTOS)
    else:
        _log.info("bitacora: sin %s, reconstruyendo desde %s", INDICE, EVENTOS)
    return _reconstruir()


def _guardar_indice(idx: dict) -> None:
    guardar_json(_ruta_indice(), idx)


def _reconstruir() -> dict:
    """Rehace el indice leyendo los eventos en orden y lo deja en disco.

    Las lineas rotas se saltan (lo hace leer_jsonl): la ultima linea de un
    JSONL cortado a mitad no puede invalidar los 40 comandos anteriores.
    """
    comandos, huerfanos = {}, set()
    for ev in leer_jsonl(_ruta_eventos()):
        if not isinstance(ev, dict):
            continue
        cmd = _norm(ev.get("cmd"))
        if not cmd:
            continue
        tipo = ev.get("evento")
        if tipo == "creada":
            ficha_ev = ev.get("ficha")
            if isinstance(ficha_ev, dict):
                comandos[cmd] = dict(ficha_ev)
                huerfanos.discard(cmd)
        elif tipo in ("evaluada", "marcada"):
            fila = comandos.get(cmd)
            if fila is None:
                huerfanos.add(cmd)
                continue
            for k in ("estado", "motivo", "veredicto", "criterios", "fases",
                      "evaluacion"):
                if k in ev:
                    fila[k] = ev[k]
            fila["ultimo_cambio"] = ev.get("t", fila.get("ultimo_cambio"))
    if huerfanos:
        # Su alta se perdio (la linea rota del final de un JSONL cortado).
        # Callarlo hace DESAPARECER el comando de listar() sin un solo aviso,
        # que es el vacio silencioso de siempre: "no lo hubo" y "se perdio"
        # tienen que verse distintos desde fuera.
        _log.warning("bitacora: %d comando(s) con eventos pero SIN alta en %s, "
                     "no salen en el indice: %s", len(huerfanos), EVENTOS,
                     ", ".join(sorted(huerfanos)))
    idx = {"version": 1, "comandos": comandos}
    _guardar_indice(idx)
    return idx


def registrar(espec, resultado_injerto, evaluacion, codigo=None,
              ahora: float = None) -> dict:
    """Da de alta en la bitacora una herramienta recien compilada.

    `espec` es lo que se pidio (dict o dataclass del generador),
    `resultado_injerto` lo que devolvio `injertador.injertar()` y `evaluacion`
    lo que dijo el evaluador. `codigo` es el fuente generado: un str (el
    handler) o {'handler':..., 'modulo':...}.

    El estado inicial sale del injerto y no de la evaluacion: si el injerto no
    entro, el comando NO esta vivo aunque el codigo fuese perfecto.

    Devuelve la ficha guardada.
    """
    ahora = time.time() if ahora is None else float(ahora)
    espec_d = _a_dict(espec)
    injerto_d = _a_dict(resultado_injerto)
    eval_d = _a_dict(evaluacion)

    cmd = _norm(_primero(espec_d, ("cmd", "comando", "slash"), ""))
    if not cmd:
        cmd = _norm(_primero(injerto_d, ("cmd", "comando"), ""))
    if not cmd:
        raise ValueError("registrar necesita un comando: ni la espec ni el "
                         "resultado del injerto traen 'cmd'")

    nombre = str(_primero(espec_d, ("nombre", "funcion", "handler"),
                          cmd.lstrip("/").replace("-", "_")))
    dir_ficha = _dir_ficha(cmd)
    rutas_codigo = _guardar_codigo(dir_ficha, codigo)

    ficha_d = {
        "cmd": cmd,
        "nombre": nombre,
        "estado": "viva" if injerto_d.get("ok") else "fallida",
        "cuando": ahora,
        "cuando_iso": time.strftime("%Y-%m-%d %H:%M:%S",
                                    time.localtime(ahora)),
        "ultimo_cambio": ahora,
        "veredicto": _veredicto(eval_d),
        "copia": str(injerto_d.get("copia") or ""),
        "descripcion": str(_primero(espec_d, ("descripcion", "que", "resumen"),
                                    "")),
        "peticion": str(_primero(espec_d, ("peticion", "pedido", "natural",
                                           "entrada"), "")),
        "categoria": str(_primero(injerto_d, ("categoria",), "")
                         or _primero(espec_d, ("categoria",), "")),
        "cubo": str(_primero(injerto_d, ("cubo",), "")
                    or _primero(espec_d, ("cubo",), "")),
        "sitios": injerto_d.get("sitios") or [],
        "guardianes": injerto_d.get("guardianes") or {},
        "motivo": str(injerto_d.get("motivo") or ""),
        "criterios": _criterios(espec_d, eval_d),
        "fases": _fases(eval_d),
        "codigo": rutas_codigo,
        "ruta": str(dir_ficha),
        "espec": espec_d,
        "evaluacion": eval_d,
        "injerto": injerto_d,
    }

    # Primero el evento (append-only, es la verdad), despues la ficha y el
    # indice (derivables). En ese orden un corte de luz deja la bitacora
    # reconstruible; al reves, deja un indice sin respaldo.
    # El indice se LEE antes de apendar: leerlo despues haria que la primera
    # alta de todas viese un JSONL sin indice y reconstruyese sin necesidad
    # (trabajo inutil y un aviso de "indice ausente" que no era un problema).
    idx = _indice()
    _evento("creada", cmd, ahora, ficha=ficha_d)
    dir_ficha.mkdir(parents=True, exist_ok=True)
    guardar_json(dir_ficha / "ficha.json", ficha_d)
    if eval_d:
        _evento("evaluada", cmd, ahora, veredicto=ficha_d["veredicto"],
                criterios=ficha_d["criterios"], fases=ficha_d["fases"],
                evaluacion=eval_d)
    idx["comandos"][cmd] = ficha_d
    _guardar_indice(idx)
    return ficha_d


def marcar(cmd: str, estado: str, motivo: str = "",
           ahora: float = None) -> dict:
    """Cambia el estado de una herramienta ya registrada.

    Estados validos: viva / retirada / fallida. Un estado fuera de esa lista
    lanza ValueError a proposito: es un bug del que llama, y tragarselo
    dejaria la bitacora diciendo algo que nadie podria filtrar despues.

    Un motivo VACIO no borra el que hubiera: el motivo de una ficha fallida
    es el diagnostico del injerto ("no encuentro el ancla"), y retirarla
    despues con `marcar(cmd, "retirada")` lo dejaba en "" -- o sea, perdia la
    unica razon registrada de por que aquello no entro. Para cambiarlo hay que
    pasar uno nuevo.

    Devuelve la ficha actualizada, o {} si el comando no esta registrado (se
    avisa por log; no se inventa una ficha vacia).
    """
    if estado not in ESTADOS:
        raise ValueError("estado invalido %r; los validos son %s"
                         % (estado, ", ".join(ESTADOS)))
    ahora = time.time() if ahora is None else float(ahora)
    cmd = _norm(cmd)
    idx = _indice()
    fila = idx["comandos"].get(cmd)
    if fila is None:
        _log.warning("bitacora: marcar(%r) pero no esta registrado", cmd)
        return {}
    fila["estado"] = estado
    fila["ultimo_cambio"] = ahora
    extra = {"estado": estado}
    if motivo:
        fila["motivo"] = motivo
        extra["motivo"] = motivo
    # El evento lleva el motivo solo si lo hay, para que _reconstruir() (que
    # copia las claves presentes) llegue exactamente al mismo estado que esta
    # rama. Si el evento llevase motivo="" siempre, reconstruir borraria el
    # motivo que aqui se conserva y las dos vias dirian cosas distintas.
    _evento("marcada", cmd, ahora, **extra)
    _guardar_indice(idx)
    dir_ficha = _dir_ficha(cmd, fila)
    if dir_ficha.is_dir():
        guardar_json(dir_ficha / "ficha.json", fila)
    else:
        _log.warning("bitacora: %s marcado %s pero su carpeta %s no esta; "
                     "el indice y los eventos SI quedan al dia",
                     cmd, estado, dir_ficha)
    return fila


# ── Lectura ──────────────────────────────────────────────────────────────────

def listar(estado: str = None) -> list:
    """Las herramientas registradas, de la mas nueva a la mas vieja.

    `estado` filtra por viva / retirada / fallida. Sin filtro salen TODAS,
    incluidas las retiradas: la bitacora es un historial, no un inventario, y
    borrar del listado lo que se retiro es como no haberlo registrado.
    """
    if estado is not None and estado not in ESTADOS:
        raise ValueError("estado invalido %r; los validos son %s"
                         % (estado, ", ".join(ESTADOS)))
    filas = list(_indice()["comandos"].values())
    if estado is not None:
        filas = [f for f in filas if f.get("estado") == estado]
    filas.sort(key=lambda f: f.get("cuando") or 0, reverse=True)
    return filas


def obtener(cmd: str) -> dict:
    """La ficha completa de un comando, con su evidencia. {} si no esta.

    Se prefiere la ficha del disco a la fila del indice porque la ficha es la
    que sobrevive a que alguien borre indice.json, y ambas se escriben juntas.
    """
    cmd = _norm(cmd)
    fila = _indice()["comandos"].get(cmd)
    en_disco = leer_json(_dir_ficha(cmd, fila) / "ficha.json", None)
    if isinstance(en_disco, dict) and en_disco:
        if fila:
            # El indice manda en lo que cambia (estado, motivo); la ficha
            # aporta la evidencia. Mezclar evita devolver un 'viva' rancio.
            en_disco = dict(en_disco)
            en_disco.update({k: fila[k] for k in
                             ("estado", "motivo", "ultimo_cambio")
                             if k in fila})
        return en_disco
    return dict(fila) if fila else {}


def eventos(cmd: str = "") -> list:
    """Los eventos crudos, todos o los de un comando. Es la auditoria.

    No forma parte del contrato minimo pero sin esto 'auditar' significaria
    abrir el JSONL a mano, y la ficha necesita la linea de tiempo.
    """
    todos = [e for e in leer_jsonl(_ruta_eventos()) if isinstance(e, dict)]
    cmd = _norm(cmd)
    if cmd:
        todos = [e for e in todos if _norm(e.get("cmd")) == cmd]
    return todos


def ficha(cmd: str) -> str:
    """La ficha en texto legible, para imprimirla en el CLI.

    Lleva la evidencia entera: veredicto, criterios uno a uno, sitios que se
    tocaron, guardianes, sello de la copia y donde esta el codigo. Es lo que
    contesta "y esto por que se dio por bueno".
    """
    cmd = _norm(cmd)
    f = obtener(cmd)
    if not f:
        return "No hay ficha de %s en la bitacora (%s)." % (cmd, dir_bitacora())

    lin = []
    lin.append("%s  [%s]   creado %s" % (f.get("cmd", cmd), f.get("estado", "?"),
                                         f.get("cuando_iso", "?")))
    if f.get("descripcion"):
        lin.append("  que hace   %s" % f["descripcion"])
    if f.get("peticion"):
        lin.append("  se pidio   %s" % f["peticion"])
    ubic = " / ".join(x for x in (f.get("categoria"), f.get("cubo")) if x)
    if ubic:
        lin.append("  ubicacion  %s" % ubic)
    lin.append("  handler    _slash_%s" % f.get("nombre", "?"))

    crit = f.get("criterios") or []
    ok_n = sum(1 for c in crit if c.get("ok"))
    juzgados = [c for c in crit if c.get("ok") is not None]
    if not crit:
        cola = ""
    elif juzgados:
        cola = "  (%d/%d criterios)" % (ok_n, len(crit))
    else:
        # "0/3" cuando NADIE marco los criterios uno a uno es una mentira que
        # se lee como tres fallos. El evaluador marca las FASES, no cada
        # criterio, asi que hay que decir que no hay marca en vez de inventar
        # un cero.
        cola = "  (%d criterios, sin marcar uno a uno)" % len(crit)
    lin.append("  veredicto  %s%s" % (f.get("veredicto", "sin evaluar"), cola))

    fases = f.get("fases") or []
    if fases:
        lin.append("  fases")
        for x in fases:
            marca = "??" if x.get("ok") is None else ("ok" if x["ok"] else "NO")
            lin.append("    [%s] %-11s %s" % (marca, x.get("fase", "?"),
                                              x.get("detalle", "")))
    if crit:
        lin.append("  criterios")
        for c in crit:
            marca = "??" if c.get("ok") is None else ("ok" if c["ok"] else "NO")
            lin.append("    [%s] %s" % (marca, c.get("texto", "")))
    else:
        lin.append("  criterios  (ninguno registrado)")

    sitios = f.get("sitios") or []
    lin.append("  injerto    sitios: %s" % (", ".join(sitios) if sitios
                                            else "ninguno"))
    g = f.get("guardianes") or {}
    if g:
        lin.append("  guardianes %s  %s" % ("verdes" if g.get("ok") else "ROJOS",
                                            str(g.get("resumen", ""))[:120]))
    if f.get("copia"):
        lin.append("  revertir   copia %s (injertador.revertir_a)" % f["copia"])
    for nombre, ruta in (f.get("codigo") or {}).items():
        lin.append("  codigo     %-8s %s" % (nombre, ruta))
    if f.get("motivo"):
        lin.append("  motivo     %s" % f["motivo"])

    evs = eventos(f.get("cmd", cmd))
    if evs:
        lin.append("  historia   %s" % " -> ".join(
            "%s@%s" % (e.get("evento", "?"),
                       time.strftime("%H:%M:%S", time.localtime(e.get("t", 0))))
            for e in evs))
    return "\n".join(lin)
