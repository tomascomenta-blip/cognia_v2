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

from dataclasses import dataclass, field, asdict
from pathlib import Path

from cognia.clases import almacen as alm

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
    de entradas.

    Sin ningun corte NO se devuelve vacio -- se devuelve UNA sesion con toda
    la jornada bajo la materia declarada (o 'Sin clasificar'). Devolver vacio
    hacia que un dia con la deteccion apagada se viera como un cuaderno en
    blanco aunque hubiera seis horas transcritas dentro.
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

    apuntes = alm.leer_json(alm.dir_jornada(nombre) / alm.APUNTES, {}) or {}
    for i, s in enumerate(sesiones):
        s.apuntes = apuntes.get(str(i)) or apuntes.get("%s|%d" % (nombre, i)) or {}
    # Una sesion sin NADA dentro es ruido de la deteccion, no una clase.
    return [s for s in sesiones if s.entradas or s.duracion > 1.0]


def cuaderno(materias_filtro=None) -> dict:
    """{materia: [Sesion, ...]} de TODAS las jornadas, cada lista de la mas
    nueva a la mas vieja. Esta es la vista que el duenio pidio: 'todo lo que
    hemos visto en clase', ordenado por asignatura y no por dia."""
    fuera: dict = {}
    for nombre in alm.jornadas():
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
