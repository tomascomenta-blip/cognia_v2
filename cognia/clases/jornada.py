"""
cognia/clases/jornada.py
========================
El ORQUESTADOR: lo que pasa entre "/grabar-clase" y un cuaderno hecho.

Junta las cuatro piezas y las hace sobrevivir a una jornada de 7 horas:

    captura.Grabador  --cola de trozos-->  transcripcion.Transcripcion
                                                     |
                                              transcripcion.jsonl
                                                     |
                              materias.detectar  ->  cortes.jsonl
                                                     |
                              apuntes.generar    ->  apuntes.json
                                                     |
                              vista.export       ->  cuaderno.html

POR QUE UN SINGLETON DE MODULO. El REPL es un proceso vivo y el duenio teclea
"/grabar-clase" una vez por la maniana y "/grabar-clase parar" por la tarde,
con horas de otros comandos en medio. La jornada tiene que vivir FUERA del
handler del comando. Es el mismo patron que el editor de flujos y los
monitores: un objeto de modulo con hilos daemon.

POR QUE LA DETECCION DE MATERIA VA EN CALIENTE Y TAMBIEN AL CERRAR. En
caliente para que el duenio vea en que materia esta y pueda corregirla ("no,
esto es Fisica") mientras la clase pasa. Y otra vez ENTERA al cerrar, porque
detectar un corte con lo que viene DESPUES es mucho mas fiable que con solo
lo de antes: al final del dia se conoce toda la jornada y se puede reconsiderar.
Lo de en caliente es una ayuda; lo del cierre es la verdad.

RESISTENCIA. Nada de lo que hace un ciclo puede tumbar la grabacion: si la
deteccion falla, se anota y se sigue capturando. Perder la clasificacion es
molesto; perder la clase es irreparable.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from cognia.clases import almacen as alm
from cognia.clases import captura as cap
from cognia.clases import cuaderno as cua
from cognia.clases import transcripcion as tra

_log = logging.getLogger(__name__)

# Cada cuanto se revisa si hay que cortar por materia, en segundos de pared.
# 90 s: bastante corto para que el duenio vea la materia bien pronto, bastante
# largo para no llamar al detector por cada trozo de 30 s.
PERIODO_DETECCION = 90.0


class JornadaViva:
    """Una jornada en curso. No se instancia a mano: se usa `arrancar()`."""

    def __init__(self, nombre: str, fuente: str = cap.FUENTE_SISTEMA,
                 transcriptor=None, orch=None):
        self.nombre = nombre
        self.orch = orch
        self.grabador = cap.Grabador(nombre, fuente=fuente)
        self.transcripcion = tra.Transcripcion(nombre, transcriptor=transcriptor)
        self.avisos: list = []
        self._parar = threading.Event()
        self._vigia = None
        self._t0_pared = 0.0

    # -- ciclo de vida ------------------------------------------------------
    def arrancar(self) -> tuple:
        ok, motivo = self.grabador.arrancar()
        if not ok:
            return False, motivo
        self.transcripcion.arrancar(self.grabador.cola)
        self._t0_pared = time.time()
        j = cua.cargar_jornada(self.nombre)
        j.estado = "grabando"
        j.inicio_epoch = j.inicio_epoch or self._t0_pared
        cua.guardar_jornada(j)
        self._vigia = threading.Thread(target=self._bucle_vigia, daemon=True,
                                       name="clases-vigia")
        self._vigia.start()
        return True, motivo

    def parar(self) -> dict:
        """Cierra la jornada: para la captura, vacia la transcripcion, detecta
        materias con TODO el dia delante y genera los apuntes."""
        self._parar.set()
        self.grabador.parar()
        self.transcripcion.parar()
        if self._vigia is not None:
            self._vigia.join(timeout=5.0)
        self.avisos.extend(self.grabador.avisos)
        self.avisos.extend(self.transcripcion.avisos)

        resumen = {"jornada": self.nombre, "avisos": list(self.avisos)}
        resumen["cortes"] = self.detectar(definitivo=True)
        resumen["apuntes"] = self.generar_apuntes()

        j = cua.cargar_jornada(self.nombre)
        j.estado = "cerrada"
        j.fin_epoch = time.time()
        j.segundos = max(j.segundos, self.grabador._t)
        j.aviso = self.avisos[-1] if self.avisos else ""
        cua.guardar_jornada(j)
        resumen["segundos"] = j.segundos
        return resumen

    @property
    def viva(self) -> bool:
        return self.grabador.viva or self.transcripcion.viva

    # -- trabajo ------------------------------------------------------------
    def _bucle_vigia(self) -> None:
        """Detecta materia cada PERIODO_DETECCION y persiste el reloj.

        El estado se reescribe aqui y no en el grabador para que un cuelgue de
        la deteccion no deje la jornada sin actualizar los segundos: el reloj
        es lo que permite retomar una jornada interrumpida en el punto bueno.
        """
        while not self._parar.wait(PERIODO_DETECCION):
            try:
                j = cua.cargar_jornada(self.nombre)
                j.segundos = self.grabador._t
                cua.guardar_jornada(j)
                self.detectar(definitivo=False)
            except Exception as exc:
                aviso = "vigia: %s: %s" % (type(exc).__name__, exc)
                self.avisos.append(aviso)
                _log.warning(aviso)

    def detectar(self, definitivo: bool = False) -> list:
        """Recalcula los cortes de materia y los reescribe.

        Se REESCRIBE el fichero entero en vez de apendar: los cortes no son
        hechos observados sino una INTERPRETACION del dia, y una
        interpretacion vieja al lado de la nueva confundiria al cuaderno. Los
        cortes que el duenio puso a mano se conservan siempre.
        """
        try:
            from cognia.clases import materias as mat
        except ImportError as exc:
            self.avisos.append("deteccion de materias no disponible: %s" % exc)
            return []
        d = alm.dir_jornada(self.nombre)
        entradas = cua._cargar_entradas(self.nombre)
        if not entradas:
            return []
        manuales = [c for c in alm.leer_jsonl(d / alm.CORTES)
                    if str(c.get("por") or "") == "manual"]
        j = cua.cargar_jornada(self.nombre)
        try:
            cortes = mat.detectar(entradas,
                                  materias_conocidas=cua.materias_conocidas(),
                                  pistas={"horario": j.horario},
                                  orch=self.orch if definitivo else None)
        except Exception as exc:
            aviso = "deteccion fallo: %s: %s" % (type(exc).__name__, exc)
            self.avisos.append(aviso)
            _log.warning(aviso)
            return []
        # Un corte manual GANA a uno automatico que caiga cerca: el duenio ya
        # dijo lo que es esa clase y no hay senial que valga mas que eso.
        for m in manuales:
            cortes = [c for c in cortes
                      if abs(float(c.get("t", 0)) - float(m.get("t", 0))) > 60.0]
            cortes.append(m)
        cortes.sort(key=lambda c: float(c.get("t") or 0.0))
        ruta = d / alm.CORTES
        try:
            if ruta.exists():
                ruta.unlink()
            for c in cortes:
                alm.apendar(ruta, c)
        except OSError as exc:
            self.avisos.append("no se pudieron guardar los cortes: %s" % exc)
            return cortes
        if cortes:
            j.materia_actual = str(cortes[-1].get("materia") or "")
            cua.guardar_jornada(j)
        return cortes

    def generar_apuntes(self) -> dict:
        try:
            from cognia.clases import apuntes as ap
        except ImportError as exc:
            self.avisos.append("generacion de apuntes no disponible: %s" % exc)
            return {}
        try:
            return ap.generar_jornada(self.nombre, orch=self.orch)
        except Exception as exc:
            aviso = "apuntes: %s: %s" % (type(exc).__name__, exc)
            self.avisos.append(aviso)
            _log.warning(aviso)
            return {}

    # -- lo que aniade el duenio -------------------------------------------
    def anotar(self, tipo: str, texto: str = "", adjunto: str = "",
               importante: bool = False) -> dict:
        reg = {"t": self.grabador._t, "tipo": tipo, "texto": texto,
               "adjunto": adjunto, "fuente": "usuario",
               "importante": bool(importante)}
        alm.apendar(alm.dir_jornada(self.nombre) / alm.ENTRADAS, reg)
        return reg

    def marcar_materia(self, materia: str) -> dict:
        """El duenio corrige la materia en curso. Es un corte MANUAL, y manda
        sobre la deteccion para siempre."""
        corte = {"t": self.grabador._t, "materia": materia,
                 "confianza": 1.0, "por": "manual"}
        alm.apendar(alm.dir_jornada(self.nombre) / alm.CORTES, corte)
        j = cua.cargar_jornada(self.nombre)
        j.materia_actual = materia
        cua.guardar_jornada(j)
        return corte


# ── Singleton de modulo ──────────────────────────────────────────────────────
_VIVA = None
_LOCK = threading.Lock()


def nombre_de_hoy() -> str:
    """'2026-08-31', y '-2', '-3'... si ya hubo una jornada cerrada hoy.

    Dos jornadas el mismo dia no es raro: se para al mediodia y se vuelve por
    la tarde. Reusar la carpeta mezclaria las dos en un solo cuaderno.
    """
    hoy = time.strftime("%Y-%m-%d")
    existentes = [n for n in alm.jornadas() if n.startswith(hoy)]
    if not existentes:
        return hoy
    j = cua.cargar_jornada(hoy if hoy in existentes else existentes[0])
    if j.estado != "cerrada" and hoy in existentes:
        return hoy                              # retomar la de hoy sin cerrar
    return "%s-%d" % (hoy, len(existentes) + 1)


def arrancar(fuente: str = cap.FUENTE_SISTEMA, transcriptor=None,
             orch=None, nombre: str = "") -> tuple:
    """(JornadaViva|None, motivo). Idempotente: si ya hay una, la devuelve."""
    global _VIVA
    with _LOCK:
        if _VIVA is not None and _VIVA.viva:
            return _VIVA, "ya habia una jornada grabando (%s)" % _VIVA.nombre
        jv = JornadaViva(nombre or nombre_de_hoy(), fuente=fuente,
                         transcriptor=transcriptor, orch=orch)
        ok, motivo = jv.arrancar()
        if not ok:
            return None, motivo
        _VIVA = jv
        return jv, motivo


def viva():
    return _VIVA if (_VIVA is not None and _VIVA.viva) else None


def parar() -> dict:
    global _VIVA
    with _LOCK:
        if _VIVA is None:
            return {}
        res = _VIVA.parar()
        _VIVA = None
        return res


def estado() -> dict:
    """Lo que ensenia '/grabar-clase' a secas. Sin jornada viva, la ultima."""
    jv = viva()
    if jv is not None:
        j = cua.cargar_jornada(jv.nombre)
        return {"grabando": True, "jornada": jv.nombre,
                "materia": j.materia_actual or "(sin clasificar aun)",
                "segundos": jv.grabador._t,
                "trozos": jv.transcripcion.trozos,
                "transcritos": jv.transcripcion.transcritos,
                "silencios": jv.transcripcion.silencios,
                "avisos": (jv.grabador.avisos + jv.transcripcion.avisos)[-3:]}
    ultimas = alm.jornadas()
    if not ultimas:
        return {"grabando": False, "jornada": "", "materias": 0}
    j = cua.cargar_jornada(ultimas[0])
    ses = cua.sesiones_de(ultimas[0])
    return {"grabando": False, "jornada": j.nombre, "estado": j.estado,
            "segundos": j.segundos, "sesiones": len(ses),
            "materias": sorted({s.materia for s in ses}),
            "aviso": j.aviso}
