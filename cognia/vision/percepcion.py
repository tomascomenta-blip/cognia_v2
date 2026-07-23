# -*- coding: utf-8 -*-
"""Percepción de pantalla en tiempo real (modo SOMBRA, read-only).

Compone las piezas ya verificadas del repo —que hasta ahora eran islas sin
conectar— en un servicio coherente de "qué hay en la pantalla ahora":

  - cognia/pantalla/captura.py   Capturador (mss)         -> el frame
  - cognia/pantalla/cambios.py   DetectorCambios (dHash)  -> ¿cambió?
  - cognia/control/escritorio.py Escritorio (árbol UIA)   -> controles/ventana
  - cognia/control/permisos.py   ventana_es_sensible      -> seguridad

SEGURIDAD (la que faltaba en Vigia, vigia.py:15-19): antes de capturar se lee la
ventana activa; si es SENSIBLE (gestor de contraseñas, banca, incógnito, UAC…) NO se
captura ni se lee el árbol — se emite una percepción REDACTADA. Así, sobre un gestor
de contraseñas, Cognia ni siquiera hace screenshot. Read-only: no mueve mouse/teclado,
no necesita COGNIA_SCREEN. Determinista y ligero (numpy + mss + uiautomation, sin torch).

Uso:
    serv = ServicioPercepcion(fps=2)
    p = serv.instantanea()                 # una foto de percepción (segura)
    for p in serv.percibir(segundos=5):    # stream real-time (solo cambios)
        print(describir(p))
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class Percepcion:
    """Qué percibe Cognia de la pantalla en un instante. NO guarda píxeles por
    defecto (privacidad): solo metadatos + el árbol de controles."""
    instante: float
    ventana: str = ""
    sensible: bool = False
    controles: list = field(default_factory=list)   # [{nombre, tipo}]
    cambio: bool = False                             # ¿cambió respecto al anterior?
    distancia: "int | None" = None                   # distancia dHash (magnitud del cambio)
    ancho: int = 0
    alto: int = 0
    ruta_frame: "str | None" = None                  # solo si se pidió guardar


def describir(p: Percepcion, max_controles: int = 12) -> str:
    """Renderiza la percepción como texto compacto que el cerebro (texto) puede
    consumir HOY, sin VLM. Sobre ventana sensible, redactado."""
    if p.sensible:
        return f"[Ventana sensible: '{p.ventana}' — percepción pausada por seguridad]"
    nombres = [c.get("nombre") or c.get("tipo", "?")
               for c in p.controles if c.get("nombre") or c.get("tipo")]
    extra = f" (+{len(nombres) - max_controles} más)" if len(nombres) > max_controles else ""
    ctrl = ", ".join(nombres[:max_controles]) + extra if nombres else "sin controles legibles"
    cambio = "cambió" if p.cambio else "sin cambios"
    return (f"Ventana activa: '{p.ventana}'. Pantalla {p.ancho}x{p.alto}, {cambio}. "
            f"Controles ({len(nombres)}): {ctrl}")


class ServicioPercepcion:
    """Servicio de percepción read-only. Inyectable (capturador/escritorio) para
    testear sin tocar la pantalla real."""

    def __init__(self, fps: float = 2.0, umbral: int = 8, *, monitor: int = 1,
                 max_controles: int = 40, capturador=None, escritorio=None,
                 detector=None):
        self.fps = max(0.1, float(fps))
        self.monitor = monitor
        self.max_controles = max_controles
        self._cap = capturador
        self._esc = escritorio
        self._det = detector
        self._umbral = umbral

    # -- lazy: no cargar mss/uiautomation hasta usarlos (nodo/headless intactos) --
    def _capturador(self):
        if self._cap is None:
            from cognia.pantalla.captura import Capturador
            self._cap = Capturador(monitor=self.monitor)
        return self._cap

    def _escritorio(self):
        if self._esc is None:
            from cognia.control.escritorio import Escritorio
            self._esc = Escritorio()
        return self._esc

    def _detector(self):
        if self._det is None:
            from cognia.pantalla.cambios import DetectorCambios
            self._det = DetectorCambios(umbral=self._umbral)
        return self._det

    def _ventana(self) -> str:
        try:
            return self._escritorio().ventana_activa() or ""
        except Exception:
            return ""

    def _es_sensible(self, titulo: str) -> bool:
        from cognia.control.permisos import ventana_es_sensible
        return ventana_es_sensible(titulo)

    def _controles(self):
        try:
            return self._escritorio().listar_elementos(limite=self.max_controles) or []
        except Exception:
            return []

    def instantanea(self, *, con_controles: bool = True,
                    guardar_en: "str | None" = None) -> Percepcion:
        """Una percepción puntual, segura. Sobre ventana sensible: redactada (sin
        captura ni controles)."""
        t = time.time()
        ventana = self._ventana()
        if self._es_sensible(ventana):
            return Percepcion(instante=t, ventana=ventana, sensible=True)
        cap = self._capturador()
        frame = cap.frame()
        alto, ancho = (frame.shape[0], frame.shape[1]) if getattr(frame, "shape", None) else (0, 0)
        cambio = self._detector().es_cambio(frame)
        dist = self._detector().estadisticas().get("ultima_distancia")
        ruta = None
        if guardar_en:
            ruta = cap.guardar_png(guardar_en, frame)
        controles = self._controles() if con_controles else []
        return Percepcion(instante=t, ventana=ventana, sensible=False,
                          controles=controles, cambio=cambio, distancia=dist,
                          ancho=ancho, alto=alto, ruta_frame=ruta)

    def percibir(self, segundos: "float | None" = None, *,
                 max_momentos: "int | None" = None, solo_cambios: bool = True):
        """Generador real-time de Percepcion a `fps`. `solo_cambios`=True emite solo
        cuando la pantalla cambió (o cambió la ventana activa) — event-driven,
        eficiente. Sobre ventana sensible emite una percepción redactada y NO captura.
        Se detiene por `segundos` o `max_momentos`."""
        t0 = time.time()
        periodo = 1.0 / self.fps
        emitidos = 0
        ventana_prev = None
        while True:
            ini = time.time()
            ventana = self._ventana()
            if self._es_sensible(ventana):
                p = Percepcion(instante=ini, ventana=ventana, sensible=True)
                emitir = (ventana != ventana_prev)   # emite el cambio a sensible una vez
            else:
                cap = self._capturador()
                frame = cap.frame()
                alto, ancho = (frame.shape[0], frame.shape[1]) if getattr(frame, "shape", None) else (0, 0)
                cambio = self._detector().es_cambio(frame)
                dist = self._detector().estadisticas().get("ultima_distancia")
                p = Percepcion(instante=ini, ventana=ventana, sensible=False,
                               controles=self._controles(), cambio=cambio,
                               distancia=dist, ancho=ancho, alto=alto)
                emitir = (not solo_cambios) or cambio or (ventana != ventana_prev)
            ventana_prev = ventana
            if emitir:
                yield p
                emitidos += 1
            if max_momentos is not None and emitidos >= max_momentos:
                return
            if segundos is not None and (time.time() - t0) >= segundos:
                return
            resto = periodo - (time.time() - ini)
            if resto > 0:
                time.sleep(resto)
