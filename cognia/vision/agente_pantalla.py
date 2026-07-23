# -*- coding: utf-8 -*-
"""Bucle percibir -> decidir -> actuar sobre la pantalla, SEGURO por defecto.

Cierra el lazo del pedido del dueño ("ver Y actuar en tiempo real") componiendo:
  - ServicioPercepcion (cognia/vision/percepcion): los ojos, read-only.
  - una POLÍTICA inyectable (Percepcion -> Accion|None): el "qué hacer". Puede ser
    una regla simple o, más adelante, el cerebro/VLM.
  - Escritorio (cognia/control/escritorio) bajo GestorPermisos: las manos, gateadas.

SEGURIDAD (para "sin romper nada"):
  - DRY-RUN por defecto (`ejecutar=False`): decide y REGISTRA la acción, pero NO la
    ejecuta. Encender acciones es explícito.
  - Toda acción pasa por GestorPermisos.evaluar(accion, ventana_activa): lecturas =
    LIBRE; clic/escribir = CONFIRMAR (denegadas sin canal de confirmación); ventana
    sensible = PROHIBIDO. La percepción ya se pausa sobre ventanas sensibles.
  - Tope de pasos y de acciones ejecutadas.

Es un servicio lateral: NO se registra como tool default-ON del agente (respeta el
techo de nº de tools del modelo chico). Se usa por CLI o embebido.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from .percepcion import ServicioPercepcion, describir


@dataclass
class Registro:
    """Qué decidió y (quizá) hizo el agente en un paso."""
    instante: float
    ventana: str
    percepcion_txt: str
    intencion: "object | None" = None      # cognia.control.permisos.Accion o None
    permitida: bool = False
    motivo: str = ""
    ejecutada: bool = False
    resultado: str = ""


class AgentePantalla:
    def __init__(self, *, servicio: ServicioPercepcion = None, escritorio=None,
                 permisos=None, ejecutar: bool = False, confirmar=None,
                 max_acciones: int = 20):
        self.serv = servicio or ServicioPercepcion(fps=2)
        self._esc = escritorio
        self._permisos = permisos
        self.ejecutar = ejecutar          # False = dry-run (sombra)
        self._confirmar = confirmar
        self.max_acciones = max_acciones
        self._acciones_hechas = 0

    def _escritorio(self):
        if self._esc is None:
            from cognia.control.escritorio import Escritorio
            self._esc = Escritorio()
        return self._esc

    def _gestor(self):
        if self._permisos is None:
            from cognia.control.permisos import GestorPermisos
            self._permisos = GestorPermisos(confirmar=self._confirmar,
                                            modo_estricto=True)
        return self._permisos

    def _ejecutar_accion(self, accion) -> str:
        """Mapea la intención a una acción real del Escritorio (gateado)."""
        esc = self._escritorio()
        tipo = accion.tipo
        obj = accion.objetivo
        if tipo == "clic":
            return esc.clic(obj)
        if tipo == "escribir_texto":
            return esc.escribir(obj)
        if tipo == "enfocar_ventana":
            return esc.enfocar(obj)
        if tipo == "abrir_app":
            return esc.abrir_app(obj)
        return f"tipo de accion no soportado: {tipo}"

    def paso(self, politica) -> Registro:
        """Un ciclo: percibe -> politica decide -> gate -> (dry-run o ejecuta)."""
        p = self.serv.instantanea()
        reg = Registro(instante=p.instante, ventana=p.ventana,
                       percepcion_txt=describir(p))
        if p.sensible:
            reg.motivo = "ventana sensible: percepcion/accion pausadas"
            return reg
        intencion = politica(p)
        reg.intencion = intencion
        if intencion is None:
            reg.motivo = "la politica no propuso accion"
            return reg
        veredicto = self._gestor().evaluar(intencion, ventana_activa=p.ventana)
        reg.permitida = bool(veredicto)
        reg.motivo = veredicto.motivo
        if not veredicto:
            return reg
        if not self.ejecutar:
            reg.resultado = "[DRY-RUN] no ejecutada (modo sombra)"
            return reg
        if self._acciones_hechas >= self.max_acciones:
            reg.resultado = "tope de acciones alcanzado"
            return reg
        reg.resultado = self._ejecutar_accion(intencion)
        reg.ejecutada = True
        self._acciones_hechas += 1
        return reg

    def bucle(self, politica, *, segundos: float = None, max_pasos: int = None):
        """Generador de Registro: percibe y decide a fps del servicio hasta el límite."""
        t0 = time.time()
        pasos = 0
        periodo = 1.0 / self.serv.fps
        while True:
            ini = time.time()
            yield self.paso(politica)
            pasos += 1
            if max_pasos is not None and pasos >= max_pasos:
                return
            if segundos is not None and (time.time() - t0) >= segundos:
                return
            resto = periodo - (time.time() - ini)
            if resto > 0:
                time.sleep(resto)


# --- políticas de ejemplo (deterministas) ---
def politica_por_control(nombre_control: str, tipo_accion: str = "clic"):
    """Devuelve una política que propone `tipo_accion` sobre el primer control cuyo
    nombre contiene `nombre_control`. Útil para demos/pruebas deterministas."""
    from cognia.control.permisos import Accion

    def politica(p):
        for c in p.controles:
            if nombre_control.lower() in (c.get("nombre") or "").lower():
                return Accion(tipo_accion, c["nombre"])
        return None
    return politica
