"""
cognia/clases/cuaderno.py
=========================
El CUADERNO: el modelo de datos de "todo lo que hemos visto en clase".

QUE ES. Un cuaderno de verdad, no un log. La unidad que el duenio abre y mira
es la MATERIA; dentro de cada materia hay SESIONES (un dia de esa materia) y
dentro de cada sesion, ENTRADAS en orden de tiempo: lo que se dijo, lo que el
apunto, la foto de la pizarra, el trozo de audio que quiso guardar.

    Cuaderno
      Materia("Fisica")
        Sesion(2026-08-31, 08:15-09:05)
          Entrada(transcripcion) ...
          Entrada(nota, "esto entra en el examen")
          Entrada(imagen, pizarra_0003.png)
          Entrada(audio, clip_0001.wav, "la explicacion del enunciado")
          Apuntes(titulo, resumen, claves, formulas, deberes, dudas)

POR QUE UNA CAPA DE MODELO Y NO LEER LOS JSONL A PELO. Porque los hechos
llegan por TIEMPO (una jornada es una tira de segundos con todo mezclado) y
se leen por MATERIA. Esta capa es la que hace ese giro: parte la tira por los
cortes que detecto `materias.py` y reparte cada hecho en su sesion. Si eso
viviera repetido en la vista HTML, en los apuntes y en el olvido, los tres
darian cuadernos distintos del mismo dia.

TIEMPOS. Todo `t` es SEGUNDOS DESDE EL INICIO DE LA JORNADA, float. No horas
de reloj: la jornada puede pausarse, y un reloj de pared no cuadraria con el
audio. La hora real se reconstruye con `Jornada.inicio_epoch` cuando hay que
enseniarla.
"""

from __future__ import annotations

import logging
import os

from dataclasses import dataclass, field, asdict
from pathlib import Path

from cognia.clases import almacen as alm

_log = logging.getLogger(__name__)

# Tipos de entrada. Lista CERRADA: la vista HTML, los apuntes y el olvido
# tratan cada tipo distinto, y un tipo inventado se renderizaria como nada.
TIPO_TRANSCRIPCION = "transcripcion"
TIPO_NOTA = "nota"
TIPO_IMAGEN = "imagen"
TIPO_AUDIO = "audio"
TIPO_REFERENCIA = "referencia"
TIPO_MARCA = "marca"          # "esto es importante", sin texto propio
TIPOS = (TIPO_TRANSCRIPCION, TIPO_NOTA, TIPO_IMAGEN, TIPO_AUDIO,
         TIPO_REFERENCIA, TIPO_MARCA)

# Lo que el usuario aniade a mano NUNCA se resume ni se olvida. Es el unico
# contenido del cuaderno del que consta que a alguien le importo.
TIPOS_DEL_USUARIO = (TIPO_NOTA, TIPO_IMAGEN, TIPO_AUDIO, TIPO_REFERENCIA,
                     TIPO_MARCA)


@dataclass
class Entrada:
    t: float                      # segundos desde el inicio de la jornada
    tipo: str
    texto: str = ""
    adjunto: str = ""             # nombre dentro de adjuntos/ (imagen/audio)
    t_fin: float = 0.0            # solo transcripcion y clips
    fuente: str = ""              # 'sistema' | 'micro' | 'usuario'
    importante: bool = False

    def a_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def de_dict(d: dict) -> "Entrada":
        return Entrada(
            t=float(d.get("t") or d.get("t0") or 0.0),
            tipo=str(d.get("tipo") or TIPO_TRANSCRIPCION),
            texto=str(d.get("texto") or ""),
            adjunto=str(d.get("adjunto") or ""),
            t_fin=float(d.get("t_fin") or d.get("t1") or 0.0),
            fuente=str(d.get("fuente") or ""),
            importante=bool(d.get("importante")),
        )


@dataclass
class Sesion:
    """Un bloque contiguo de UNA materia dentro de una jornada."""
    materia: str
    t0: float
    t1: float
    jornada: str = ""
    confianza: float = 0.0        # la del corte que la abrio
    por: str = ""                 # que la detecto: 'silencio'|'deriva'|'manual'...
    entradas: list = field(default_factory=list)
    apuntes: dict = field(default_factory=dict)

    @property
    def duracion(self) -> float:
        return max(0.0, self.t1 - self.t0)

    def texto_dicho(self) -> str:
        """Todo lo transcrito de la sesion, en orden. Es la materia prima de
        los apuntes."""
        return " ".join(e.texto for e in self.entradas
                        if e.tipo == TIPO_TRANSCRIPCION and e.texto).strip()

    def del_usuario(self) -> list:
        """Lo que el duenio aniadio a mano. Va aparte porque ni se resume ni
        se olvida: se ensenia tal cual."""
        return [e for e in self.entradas if e.tipo in TIPOS_DEL_USUARIO]


@dataclass
class Jornada:
    """Un dia de clase entero."""
    nombre: str                   # '2026-08-31' (y '-2', '-3' si hay varias)
    inicio_epoch: float = 0.0
    fin_epoch: float = 0.0
    estado: str = "nueva"         # nueva|grabando|pausada|cerrada
    materia_actual: str = ""
    segundos: float = 0.0         # de audio efectivamente capturado
    horario: list = field(default_factory=list)   # pistas del usuario
    aviso: str = ""               # ultima degradacion visible


def _cargar_entradas(nombre: str) -> list:
    """Transcripcion + entradas del usuario, FUNDIDAS y ordenadas por tiempo.

    Van en dos ficheros distintos porque los escriben dos productores con
    ritmos muy distintos (la transcripcion, cada pocos segundos; el usuario,
    cuando le apetece) y mezclarlos en un solo append-only obligaria a
    serializar los dos hilos. Se funden AQUI, al leer.
    """
    d = alm.dir_jornada(nombre)
    brutas = alm.leer_jsonl(d / alm.TRANSCRIPCION) + alm.leer_jsonl(d / alm.ENTRADAS)
    entradas = [Entrada.de_dict(x) for x in brutas]
    entradas.sort(key=lambda e: e.t)
    return entradas


def cargar_jornada(nombre: str) -> Jornada:
    d = alm.dir_jornada(nombre)
    crudo = alm.leer_json(d / alm.JORNADA, {}) or {}
    j = Jornada(nombre=nombre)
    for k, v in crudo.items():
        if hasattr(j, k):
            setattr(j, k, v)
    j.nombre = nombre
    return j


def guardar_jornada(j: Jornada) -> None:
    alm.guardar_json(alm.dir_jornada(j.nombre) / alm.JORNADA, asdict(j))


def sesiones_de(nombre: str) -> list:
    """Las sesiones de una jornada: los cortes de materia aplicados a la tira
    de entradas, CON sus apuntes colgados.

    Sin ningun corte NO se devuelve vacio -- se devuelve UNA sesion con toda
    la jornada bajo la materia declarada (o 'Sin clasificar'). Devolver vacio
    hacia que un dia con la deteccion apagada se viera como un cuaderno en
    blanco aunque hubiera seis horas transcritas dentro.
    """
    sesiones = _sesiones_crudas(nombre)
    _pegar_apuntes(nombre, sesiones)
    return sesiones


def _sesiones_crudas(nombre: str) -> list:
    """Igual que `sesiones_de` pero SIN pegar los apuntes.

    Existe partida en dos por el indice de materias: para saber que materias
    toca una jornada (y en que tramos) no hace falta abrir apuntes.json ni
    cargar `clases.apuntes` -- que a su vez importa el resto del paquete. Lo
    que SI tiene que ser identico entre las dos es el reparto y el filtro de
    sesiones vacias: si el indice se calculara con otras reglas, exportar una
    materia filtrando por el indice daria un cuaderno distinto del que sale
    leyendo el curso entero, y esa diferencia no la veria nadie.
    """
    j = cargar_jornada(nombre)
    entradas = _cargar_entradas(nombre)
    cortes = alm.leer_jsonl(alm.dir_jornada(nombre) / alm.CORTES)
    cortes = sorted(cortes, key=lambda c: float(c.get("t") or 0.0))
    fin = max([e.t_fin or e.t for e in entradas] + [j.segundos, 0.0])

    if not cortes:
        cortes = [{"t": 0.0, "materia": j.materia_actual or "Sin clasificar",
                   "confianza": 0.0, "por": "sin deteccion"}]
    if float(cortes[0].get("t") or 0.0) > 0.0:
        # Lo dicho ANTES del primer corte no puede desaparecer del cuaderno.
        cortes.insert(0, {"t": 0.0, "materia": "Sin clasificar",
                          "confianza": 0.0, "por": "antes del primer corte"})

    sesiones = []
    for i, c in enumerate(cortes):
        t0 = float(c.get("t") or 0.0)
        t1 = float(cortes[i + 1].get("t")) if i + 1 < len(cortes) else fin
        s = Sesion(materia=str(c.get("materia") or "Sin clasificar"),
                   t0=t0, t1=max(t1, t0), jornada=nombre,
                   confianza=float(c.get("confianza") or 0.0),
                   por=str(c.get("por") or ""))
        s.entradas = [e for e in entradas if t0 <= e.t < s.t1 or
                      (i + 1 == len(cortes) and e.t >= t0)]
        sesiones.append(s)

    # Una sesion sin NADA dentro es ruido de la deteccion, no una clase. El
    # filtro va ANTES de colgar los apuntes porque la lista filtrada es la que
    # ve `apuntes.generar_jornada`: si se le pasara la otra, la migracion de
    # claves reclavaria por posiciones que nadie escribio nunca.
    return [s for s in sesiones if s.entradas or s.duracion > 1.0]


def _pegar_apuntes(nombre: str, sesiones: list) -> None:
    """Cuelga de cada sesion sus apuntes de apuntes.json.

    La clave la sabe `clases.apuntes`, que es quien escribe ese fichero: aqui
    se le pregunta en vez de reconstruirla. Hasta el 2026-08-31 esto leia
    `apuntes[str(i)]`, o sea el INDICE POSICIONAL, y en cuanto la deteccion de
    materias aniadia un corte todos los indices de detras se corrian y cada
    sesion se quedaba con los apuntes de otra -- sin error y sin aviso. La
    deteccion corre cada 90 s mientras la jornada esta viva, asi que pasaba
    solo con dejar el cuaderno grabando.

    El import va DENTRO de la funcion porque `clases.apuntes` importa este
    modulo: arriba seria un ciclo.
    """
    try:
        from cognia.clases import apuntes as ap
    except Exception as exc:
        # Sin el modulo de apuntes el cuaderno se sigue leyendo, pero con la
        # clave VIEJA -- que es lo unico reconstruible desde aqui -- y se DICE:
        # "no esta cableado" y "se rompio" no pueden verse igual desde fuera.
        _log.warning("cuaderno: sin cognia.clases.apuntes (%s: %s); los apuntes "
                     "se releen por indice posicional, que es el formato viejo "
                     "y puede pegarlos a la sesion equivocada",
                     type(exc).__name__, exc)
        crudo = alm.leer_json(alm.dir_jornada(nombre) / alm.APUNTES, {}) or {}
        if not isinstance(crudo, dict):
            crudo = {}
        for i, s in enumerate(sesiones):
            s.apuntes = crudo.get(str(i)) or crudo.get("%s|%d" % (nombre, i)) or {}
        return
    mapa = ap.cargar_mapa(nombre, sesiones)
    # Las claves se piden PARA LA LISTA ENTERA, no sesion a sesion: dos
    # sesiones que empiezan en el mismo segundo dan la misma clave y solo
    # mirando la jornada completa se puede romper ese empate. Pedirlas de una
    # en una devolvia a las dos los apuntes de la primera.
    claves = ap.claves_de_jornada(nombre, sesiones)[0]
    for s, k in zip(sesiones, claves):
        s.apuntes = ap.leer_apuntes(nombre, s, mapa, clave=k)


# ── Indice incremental materia -> jornadas ───────────────────────────────────
#
# EL PROBLEMA QUE RESUELVE. `cuaderno()` releia TODAS las jornadas del curso en
# CADA llamada: para un filtro de una sola materia eso son 180 dias de JSONL
# parseados para quedarse con 30. Y el cuaderno se exporta AHORA por materia
# (una llamada por asignatura), asi que el curso entero se releia N veces.
#
# QUE GUARDA. Por jornada, la HUELLA de sus ficheros y los TRAMOS que salieron
# de leerla ([{m, t0, t1}]). El mapa materia -> jornadas NO se guarda: se
# deriva al leer. Un mapa persistido puede desincronizarse de los tramos que lo
# generaron; uno derivado, no -- y derivarlo son microsegundos.
#
# COMO SE MANTIENE AL DIA SIN QUE NADIE LO AVISE. Por huella (tamanio +
# mtime_ns de los cinco ficheros de la jornada), no por notificacion. Es a
# proposito: el que escribe es el hilo que esta grabando la clase (ver
# almacen._emitir, que ya mide y penaliza a los suscriptores lentos) y
# colgarle ahi un reindexado seria robarle tiempo al grabador. Comprobar la
# huella son cinco stat() por jornada -- 900 syscalls en un curso entero, del
# orden de milisegundos -- frente a parsear megabytes de JSONL. Y ademas es
# AUTOREPARABLE: si alguien edita un JSONL a mano, o si un proceso paralelo
# escribe sin llamar a nadie, la huella cambia igual y el tramo se recalcula.
# `actualizar_indice(jornada)` existe para quien SI quiera empujarlo al cerrar
# una jornada, pero el indice es correcto aunque nadie lo llame nunca.
INDICE_MATERIAS = "indice_materias.json"
VERSION_INDICE = 1

# Los ficheros cuyo contenido decide los tramos. jornada.json entra porque de
# el salen `materia_actual` y `segundos` (el final de la ultima sesion), y
# apuntes.json NO entra: no cambia ni una materia ni un corte, y meterlo haria
# reindexar la jornada entera cada vez que se regeneran los apuntes.
_FICHEROS_HUELLA = (alm.JORNADA, alm.TRANSCRIPCION, alm.ENTRADAS, alm.CORTES)

# Ultimo motivo por el que el indice se cayo al barrido completo. Es la puerta
# de diagnostico del subsistema: sin esto, "el indice esta apagado" y "el
# indice se rompio" se ven igual desde fuera -- que es el fallo tipico de este
# repo.
_ultimo_fallo_indice: dict = {}


def indice_activo() -> bool:
    """Si el indice de materias esta encendido. COGNIA_CLASES_INDICE=0 lo
    apaga y todo vuelve a leer el curso entero (mismo resultado, mas lento):
    el interruptor existe para poder comparar los dos caminos sin parchear
    codigo, que es como se midio la mejora."""
    return (os.environ.get("COGNIA_CLASES_INDICE", "1").strip().lower()
            not in ("0", "no", "off", "false"))


def _degradar_indice(motivo: str, accion: str = "") -> None:
    """Deja constancia de que el indice no se pudo usar. Nunca un except mudo:
    caerse al barrido completo es correcto pero LENTO, y si eso pasa en cada
    exportacion el duenio tiene derecho a enterarse."""
    _ultimo_fallo_indice.clear()
    _ultimo_fallo_indice.update({"motivo": motivo, "accion": accion})
    _log.warning("cuaderno: indice de materias no usable -- %s", motivo)
    try:
        from cognia.ux import events as _ux
        _ux.emitir(_ux.Degradado(donde="clases.cuaderno.indice", motivo=motivo,
                                 accion_sugerida=accion))
    except Exception as exc:
        _log.warning("cuaderno: tampoco pude avisar por ux.events (%s: %s)",
                     type(exc).__name__, exc)


def _dir_jornada_sin_crear(nombre: str) -> Path:
    """La carpeta de una jornada SIN crearla.

    `alm.dir_jornada` crea de paso audio/ y adjuntos/, y este es un camino de
    LECTURA que se recorre para todas las jornadas del curso: crear 360
    carpetas para mirar cinco fechas de modificacion es gastar en el sitio
    exacto donde este indice existe para ahorrar. La sanitizacion es la MISMA
    (`alm._seguro`), que es lo que importa para no mirar otra carpeta.
    """
    return alm.raiz() / "jornadas" / alm._seguro(nombre)


def _huella(nombre: str) -> str:
    """Tamanio y mtime de los ficheros de una jornada, en una cadena.

    Se usan los dos y no solo el mtime: en Windows el mtime de un fichero que
    se acaba de aniadir puede caer en el mismo tick que el anterior, y un
    apendado que no cambia el tamanio (imposible en un JSONL, pero no en
    jornada.json) tampoco moveria el reloj. Los dos juntos no fallan por lo
    mismo.
    """
    d = _dir_jornada_sin_crear(nombre)
    partes = []
    for fichero in _FICHEROS_HUELLA:
        try:
            st = (d / fichero).stat()
            partes.append("%d:%d" % (st.st_size, st.st_mtime_ns))
        except OSError:
            partes.append("-")      # no esta: es un estado, no un error
    return "|".join(partes)


def _tramos_de(nombre: str) -> list:
    """[{'m','t0','t1'}] de una jornada: lo unico que el indice necesita
    saber de ella. Sale de `_sesiones_crudas`, o sea del MISMO reparto que
    luego lee la vista: el indice no puede tener su propia idea de donde
    empieza una materia."""
    return [{"m": s.materia, "t0": s.t0, "t1": s.t1}
            for s in _sesiones_crudas(nombre)]


def indice_materias(refrescar: bool = True) -> dict:
    """El indice entero: {'version', 'jornadas': {nombre: {huella, tramos}}}.

    Con `refrescar` (lo normal) se comprueban las huellas y se reindexan SOLO
    las jornadas que cambiaron, ademas de quitar las que ya no estan. Con
    `refrescar=False` se devuelve lo que hay en disco tal cual, que es lo que
    quiere una pantalla de diagnostico.

    Nunca lanza: un indice ilegible se reconstruye desde cero, y si tampoco se
    puede escribir se sigue trabajando en memoria (avisando). El indice es una
    CACHE -- perderlo cuesta tiempo, nunca datos.
    """
    ruta = alm.raiz() / INDICE_MATERIAS
    crudo = alm.leer_json(ruta, {}) or {}
    if (not isinstance(crudo, dict)
            or int(crudo.get("version") or 0) != VERSION_INDICE
            or not isinstance(crudo.get("jornadas"), dict)):
        crudo = {"version": VERSION_INDICE, "jornadas": {}}
    idx = {"version": VERSION_INDICE, "jornadas": dict(crudo["jornadas"])}
    if not refrescar:
        return idx

    jor = idx["jornadas"]
    vivas = alm.jornadas()
    cambios = 0
    for nombre in vivas:
        h = _huella(nombre)
        vieja = jor.get(nombre)
        if (isinstance(vieja, dict) and vieja.get("huella") == h
                and isinstance(vieja.get("tramos"), list)):
            continue
        jor[nombre] = {"huella": h, "tramos": _tramos_de(nombre)}
        cambios += 1
    for muerta in [n for n in jor if n not in set(vivas)]:
        # Una jornada borrada (por el olvido, o a mano) tiene que salir del
        # indice o su materia seguiria apareciendo en el cuaderno para siempre.
        jor.pop(muerta, None)
        cambios += 1

    if cambios:
        try:
            alm.guardar_json(ruta, idx)
        except OSError as exc:
            _degradar_indice(
                "no pude guardar %s (%s: %s): el indice se recalcula entero en "
                "cada llamada" % (ruta, type(exc).__name__, exc),
                accion="revisar permisos de %s" % alm.raiz())
    return idx


def actualizar_indice(nombre: str) -> dict:
    """Reindexa UNA jornada y devuelve sus tramos.

    El gancho para quien acaba de escribir (cerrar la jornada, corregir una
    materia a mano). No es obligatorio llamarlo -- la huella ya detecta el
    cambio en la siguiente lectura --, pero llamarlo mueve el coste al momento
    en que el duenio no esta esperando un HTML.
    """
    ruta = alm.raiz() / INDICE_MATERIAS
    idx = indice_materias(refrescar=False)
    tramos = _tramos_de(nombre)
    idx["jornadas"][nombre] = {"huella": _huella(nombre), "tramos": tramos}
    try:
        alm.guardar_json(ruta, idx)
    except OSError as exc:
        _degradar_indice("no pude guardar %s al actualizar %s (%s: %s)"
                         % (ruta, nombre, type(exc).__name__, exc),
                         accion="revisar permisos de %s" % alm.raiz())
    return {"jornada": nombre, "tramos": tramos}


def jornadas_de_materia(materia: str) -> list:
    """Las jornadas donde se dio esa materia, de la mas nueva a la mas vieja.
    Derivado del indice; sin indice (o roto) devuelve TODAS, que es la
    respuesta lenta pero nunca la equivocada."""
    return _jornadas_a_leer([materia])


def tramos_de_materia(materia: str) -> list:
    """[(jornada, t0, t1), ...] de una materia, de la mas nueva a la mas
    vieja. Es el indice en la forma en que se pidio (materia -> tramos), y
    sale DERIVADO del indice por jornada: ver la seccion de arriba sobre por
    que el mapa por materia no se persiste.

    Sirve para contestar "cuando y cuanto se dio esto" sin abrir ni un JSONL
    -- que es justo lo que la cabecera de un cuaderno por asignatura necesita
    saber antes de decidir si merece la pena leerlo entero.
    """
    if not indice_activo():
        return [(s.jornada, s.t0, s.t1) for s in cuaderno([materia]).get(materia, [])]
    try:
        idx = indice_materias()
    except Exception as exc:
        _degradar_indice("no pude leer el indice (%s: %s): se lee el curso "
                         "entero" % (type(exc).__name__, exc))
        return [(s.jornada, s.t0, s.t1) for s in cuaderno([materia]).get(materia, [])]
    jor = idx.get("jornadas") or {}
    fuera = []
    for nombre in alm.jornadas():
        for t in (jor.get(nombre, {}).get("tramos") or []):
            if str(t.get("m")) == materia:
                fuera.append((nombre, float(t.get("t0") or 0.0),
                              float(t.get("t1") or 0.0)))
    return fuera


def _jornadas_a_leer(materias_filtro=None) -> list:
    """Que jornadas hay que abrir de verdad para servir este filtro.

    Sin filtro no hay nada que ahorrar (hay que leerlas todas igual) y se
    devuelve la lista completa SIN tocar el indice: refrescarlo ahi seria
    parsear cada jornada dos veces.
    """
    todas = alm.jornadas()
    if not materias_filtro or not indice_activo():
        return todas
    try:
        idx = indice_materias()
    except Exception as exc:
        _degradar_indice("no pude leer el indice (%s: %s): se lee el curso "
                         "entero" % (type(exc).__name__, exc),
                         accion="borrar %s para reconstruirlo"
                                % (alm.raiz() / INDICE_MATERIAS))
        return todas
    quiere = set(materias_filtro)
    jor = idx.get("jornadas") or {}
    fuera = [n for n in todas
             if any(str(t.get("m")) in quiere
                    for t in (jor.get(n, {}).get("tramos") or []))]
    return fuera


def materias_vistas() -> list:
    """Las materias que ya aparecen en alguna jornada, en el orden en que se
    encuentran leyendo de la jornada mas nueva a la mas vieja. Sale del
    indice: preguntar 'que asignaturas hay' no puede costar releer el curso.
    """
    if not indice_activo():
        return list(cuaderno().keys())
    try:
        idx = indice_materias()
    except Exception as exc:
        _degradar_indice("no pude leer el indice (%s: %s): se lee el curso "
                         "entero" % (type(exc).__name__, exc))
        return list(cuaderno().keys())
    fuera, visto = [], set()
    jor = idx.get("jornadas") or {}
    for nombre in alm.jornadas():
        for t in (jor.get(nombre, {}).get("tramos") or []):
            m = str(t.get("m") or "")
            if m and m not in visto:
                visto.add(m)
                fuera.append(m)
    return fuera


def estado_indice() -> dict:
    """Puerta de diagnostico: si esta activo, cuantas jornadas cubre, cuantas
    materias conoce y el ultimo motivo por el que no se pudo usar."""
    ruta = alm.raiz() / INDICE_MATERIAS
    idx = indice_materias(refrescar=False)
    jor = idx.get("jornadas") or {}
    materias = sorted({str(t.get("m")) for v in jor.values()
                       for t in (v.get("tramos") or [])})
    return {"activo": indice_activo(), "ruta": str(ruta),
            "existe": ruta.is_file(), "jornadas": len(jor),
            "jornadas_en_disco": len(alm.jornadas()),
            "materias": materias,
            "ultimo_fallo": dict(_ultimo_fallo_indice)}


def cuaderno(materias_filtro=None) -> dict:
    """{materia: [Sesion, ...]} de TODAS las jornadas, cada lista de la mas
    nueva a la mas vieja. Esta es la vista que el duenio pidio: 'todo lo que
    hemos visto en clase', ordenado por asignatura y no por dia.

    Con `materias_filtro` solo se ABREN las jornadas que el indice dice que
    tocan esas materias (ver la seccion del indice, arriba); el filtro se
    vuelve a aplicar sesion a sesion, asi que un indice mentiroso costaria
    tiempo pero nunca meteria una materia ajena en el cuaderno.
    """
    fuera: dict = {}
    for nombre in _jornadas_a_leer(materias_filtro):
        for s in sesiones_de(nombre):
            if materias_filtro and s.materia not in materias_filtro:
                continue
            fuera.setdefault(s.materia, []).append(s)
    for lista in fuera.values():
        lista.sort(key=lambda s: (s.jornada, s.t0), reverse=True)
    return fuera


def materias_conocidas() -> list:
    """Las materias que el cuaderno ya ha visto, mas las que el duenio
    declaro a mano en el indice. Alimenta la deteccion: reconocer 'Fisica'
    otra vez es mucho mas fiable que descubrirla de cero cada dia."""
    idx = alm.leer_json(alm.raiz() / alm.INDICE, {}) or {}
    declaradas = [str(m) for m in (idx.get("materias") or [])]
    vistas = list(cuaderno().keys())
    fuera, visto = [], set()
    for m in declaradas + vistas:
        if m and m != "Sin clasificar" and m.lower() not in visto:
            visto.add(m.lower())
            fuera.append(m)
    return fuera


def declarar_materias(nombres: list) -> list:
    """Fija la lista de materias del curso. Es la pista mas barata y mas util
    que el duenio le puede dar a la deteccion."""
    ruta = alm.raiz() / alm.INDICE
    idx = alm.leer_json(ruta, {}) or {}
    idx["materias"] = [str(n).strip() for n in nombres if str(n).strip()]
    alm.guardar_json(ruta, idx)
    return idx["materias"]
