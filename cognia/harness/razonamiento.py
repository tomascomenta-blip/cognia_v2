# -*- coding: utf-8 -*-
"""RECORDATORIO DE RAZONAMIENTO EN BUCLE (2026-08-31).

POR QUE EXISTE
--------------
El repo tiene CUATRO detectores de bucle y los cuatro miran lo mismo: las
LLAMADAS a herramientas (`register_action`, `GuardiaBucle`, `repeticion.
Contador` y el disyuntor de disciplina). Ninguno mira el otro canal, que en un
razonador es donde se va el tiempo: el modelo PIENSA en circulos, no llama a
nada, y como no llama a nada no hay tool+args que contar — asi que para todos
los detectores el turno es "silencioso" y no pasa nada.

Lo medido en esta casa (agent/loop.py, palanca del pensamiento):

    thinking ON,  max_tokens 20000 -> 52.535 chars de razonamiento y CERO tool calls
    enable_thinking=false, max_tokens 4000 -> 0 chars de razonamiento y 10.160 de tool call

Y en la traza del dueno del 2026-08-31 (juego HTML, tres tareas seguidas) el
unico aviso que existia — "el turno se fue entero en razonar sin llegar a
llamar la herramienta" — solo salta cuando el turno se CORTA a mitad. Un turno
que piensa 30.000 chars, concluye "let me reconsider my approach" y CIERRA
limpio no dispara nada: se repite vuelta tras vuelta hasta que el presupuesto
de pasos se agota. Eso son los "largos ciclos de pensar que no solucionan
nada".

QUE HACE
    Por TAREA lleva la cuenta del razonamiento de cada turno y, al cerrarse el
    turno, decide:
      - racha de turnos que piensan mucho y no dejan un AVANCE verificado,
      - si el razonamiento de este turno REPITE el del anterior (shingles),
      - y devuelve un nudge CONCRETO (cita los numeros) para inyectar como
        turno de usuario antes del paso siguiente.
    Al cruzar la racha dura pide ademas apagar el pensamiento, que es la unica
    intervencion de la que hay medicion de que arregla el caso.

    Ademas `vivo()` da el aviso que se imprime DURANTE la generacion (el
    stream ya entrega los fragmentos de razonamiento a `on_reasoning`), para
    que el dueno vea que el modelo lleva 20.000 chars pensando en vez de mirar
    un spinner mudo.

DECISIONES
 1. **Advisory.** No corta el turno, no veta, no toca el presupuesto. Solo
    devuelve texto y una bandera. Quien decide es el bucle.
 2. **El nudge es concreto.** La leccion medida del repo (+62pp,
    bench_estancamiento) es que el aviso que CITA los numeros desvia al modelo
    y el abstracto no. Aqui se citan chars, turnos y la accion pedida.
 3. **Pensar no es malo; pensar SIN AVANZAR lo es.** Un turno que piensa
    12.000 chars y despues deja un avance verificado no cuenta para la racha.
    La racha la rompe el AVANCE, no la llamada: en la traza del dueno el modelo
    llamaba a herramientas en casi todos los pasos (releia el mismo fichero) y
    la tarea no se movia. El objetivo no es que piense poco, es que no de
    vueltas.
 4. **Sin razonamiento el modulo es transparente.** Un modelo que no emite
    reasoning_content nunca dispara nada.

CONFIG (patron del repo: se valida al leer, nunca lanza)
    COGNIA_RAZONAMIENTO         '0'/'off' lo apaga.
    COGNIA_RAZONAMIENTO_UMBRAL  chars de razonamiento que hacen "pesado" un
                                turno (default 4000).
    COGNIA_RAZONAMIENTO_RACHA   turnos pesados seguidos sin avance antes de
                                pedir apagar el pensamiento (default 3).
"""
from __future__ import annotations

import os
import re

UMBRAL_CHARS_DEFECTO = 4000
RACHA_DURA_DEFECTO = 3
# Hitos del aviso EN VIVO, en chars de razonamiento del turno en curso.
HITOS_VIVOS = (8000, 20000, 40000)
# Solapamiento de shingles a partir del cual dos razonamientos son "el mismo".
UMBRAL_REPETICION = 0.45
_SHINGLE = 6

ENV_ACTIVO = "COGNIA_RAZONAMIENTO"
ENV_UMBRAL = "COGNIA_RAZONAMIENTO_UMBRAL"
ENV_RACHA = "COGNIA_RAZONAMIENTO_RACHA"

MARCA = "[RECORDATORIO DE RAZONAMIENTO]"

_RE_PALABRA = re.compile(r"[a-z0-9áéíóúñü]+")


def activo() -> bool:
    return os.environ.get(ENV_ACTIVO, "1").strip().lower() not in ("0", "off", "false", "no")


def _entero(nombre: str, default: int, minimo: int) -> int:
    crudo = (os.environ.get(nombre) or "").strip()
    if not crudo:
        return default
    try:
        v = int(crudo)
    except ValueError:
        return default
    return v if v >= minimo else default


def umbral_chars() -> int:
    return _entero(ENV_UMBRAL, UMBRAL_CHARS_DEFECTO, 200)


def racha_dura() -> int:
    return _entero(ENV_RACHA, RACHA_DURA_DEFECTO, 2)


# Telemetria de PROCESO para la puerta `/bucle` (nada en disco): un subsistema
# sin diagnostico visible es indistinguible de uno que no se cableo.
_TOTAL = [0]              # recordatorios emitidos en este proceso
_APAGADOS = [0]           # veces que se pidio apagar el pensamiento
_ULTIMO: dict = {}


class ConfigInvalida(ValueError):
    """Config del subsistema mal escrita. Se avisa; no se rompe el turno."""


def parsear_entero(crudo: str, minimo: int) -> int:
    """El entero de un subcomando de `/bucle razonamiento`, validado."""
    crudo = (crudo or "").strip()
    if not crudo:
        raise ConfigInvalida("falta el numero")
    try:
        v = int(crudo)
    except ValueError:
        raise ConfigInvalida(f"{crudo!r} no es un entero")
    if v < minimo:
        raise ConfigInvalida(f"{v} es menor que el minimo ({minimo})")
    return v


def estado() -> dict:
    """Foto del subsistema para `/bucle` (json-able, sin tocar disco)."""
    return {"activo": activo(), "umbral": umbral_chars(),
            "racha": racha_dura(), "hitos": list(HITOS_VIVOS),
            "umbral_repeticion": UMBRAL_REPETICION,
            "total": _TOTAL[0], "apagados": _APAGADOS[0],
            "ultimo": dict(_ULTIMO)}


def _num(n) -> str:
    """Miles con punto. Aparte a proposito: formatear con `:,` y despues hacer
    `.replace(",", ".")` sobre la frase entera convertia las comas del texto en
    puntos ("20.000 caracteres. mismo contenido")."""
    try:
        return f"{int(n):,}".replace(",", ".")
    except (TypeError, ValueError):
        return str(n)


def _shingles(texto: str) -> set:
    """Conjunto de n-gramas de palabras del razonamiento, normalizado."""
    pals = _RE_PALABRA.findall((texto or "").lower())
    if len(pals) < _SHINGLE:
        return set()
    return {" ".join(pals[i:i + _SHINGLE]) for i in range(len(pals) - _SHINGLE + 1)}


def solapamiento(a: str, b: str) -> float:
    """Jaccard de los shingles de dos razonamientos (0.0 si alguno es corto)."""
    sa, sb = _shingles(a), _shingles(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / float(len(sa | sb))


class Vigilante:
    """Vigila el canal de RAZONAMIENTO de una tarea. No corta nada.

    Uso desde el bucle::

        vig = Vigilante()
        ...                                    # durante el stream:
        aviso = vig.vivo(chars_acumulados)     # "" o texto para imprimir
        ...                                    # al cerrar el turno:
        v = vig.turno(chars, hubo_avance, razonamiento_del_turno)
        if v["nudge"]:
            mensajes.append({"role": "user", "content": v["nudge"]})
        if v["apagar_pensamiento"]:
            _apagar_pensamiento()
    """

    def __init__(self, umbral=None, racha=None):
        self.umbral = int(umbral) if umbral else umbral_chars()
        self.racha_tope = int(racha) if racha else racha_dura()
        self.racha = 0                 # turnos pesados SEGUIDOS sin avance
        self.turnos = 0
        self.chars_totales = 0
        self.previo = ""               # razonamiento del turno anterior
        self.repeticiones = 0
        self._hitos_dichos: set = set()
        self._pedido_apagar = False

    # -- durante la generacion -------------------------------------------
    def vivo(self, chars: int) -> str:
        """Aviso para imprimir mientras el modelo piensa, o "".

        Cada hito se dice UNA vez por turno: un aviso que se repite cada
        fragmento es ruido, no informacion.
        """
        if not activo():
            return ""
        for hito in HITOS_VIVOS:
            if chars >= hito and hito not in self._hitos_dichos:
                self._hitos_dichos.add(hito)
                return (f"lleva {_num(chars)} caracteres pensando en este "
                        "paso sin llamar a ninguna herramienta")
        return ""

    def nuevo_turno(self) -> None:
        """Resetea lo que es POR TURNO (los hitos del aviso en vivo)."""
        self._hitos_dichos = set()

    # -- al cerrar el turno ----------------------------------------------
    def turno(self, chars: int, avanzo: bool, texto: str = "") -> dict:
        """Contabiliza el turno y devuelve el veredicto.

        `avanzo` es lo que ROMPE la racha, y a proposito NO es "llamo a una
        herramienta": en la traza del dueno el modelo llamaba a herramientas en
        casi todos los pasos — releia el mismo fichero, reeditaba lo mismo — y
        aun asi la tarea no se movia. El bucle pasa aqui el avance VERIFICADO
        del gobernador de progreso cuando lo tiene (`estado/
        presupuesto_progreso`), y cae a "hubo tool call" solo si no lo hay.
        Pensar mucho antes de una accion que AVANZA no es dar vueltas; pensar
        mucho antes de una accion que deja todo igual, si.

        ``{"nudge": str, "apagar_pensamiento": bool, "racha": int,
           "repetido": bool, "pesado": bool}``
        """
        out = {"nudge": "", "apagar_pensamiento": False, "racha": self.racha,
               "repetido": False, "pesado": False}
        if not activo():
            return out
        try:
            chars = int(chars or 0)
        except (TypeError, ValueError):
            chars = 0
        self.turnos += 1
        self.chars_totales += chars
        self.nuevo_turno()
        pesado = chars >= self.umbral
        out["pesado"] = pesado
        repetido = bool(texto) and solapamiento(texto, self.previo) >= UMBRAL_REPETICION
        out["repetido"] = repetido
        if repetido:
            self.repeticiones += 1
        self.previo = texto or self.previo
        if avanzo or not pesado:
            # Avanzar ROMPE la racha; un turno ligero tampoco cuenta.
            self.racha = 0
            out["racha"] = 0
            # Aqui NO se emite nudge, ni con el razonamiento repetido: a esta
            # rama se llega por AVANZAR o por pensar poco, y las dos cosas son
            # sanas. Repetirse mientras se avanza es ruido, no bucle. La
            # repeticion que SI importa — pensar mucho, repetirse y no mover
            # nada — cae en el camino de la racha (abajo) y se nombra al final
            # de su nudge.
            self._anotar(out, chars)
            return out
        self.racha += 1
        out["racha"] = self.racha
        if self.racha >= self.racha_tope and not self._pedido_apagar:
            self._pedido_apagar = True
            out["apagar_pensamiento"] = True
            out["nudge"] = self._nudge_duro(chars)
        elif self.racha >= 2:
            out["nudge"] = self._nudge_fuerte(chars)
        else:
            out["nudge"] = self._nudge_suave(chars)
        if repetido and out["nudge"]:
            out["nudge"] += ("\nY es EL MISMO razonamiento del paso anterior: "
                             "volver a pensarlo no va a dar otra respuesta. Ya "
                             "lo pensaste; toma la decision que quedo "
                             "pendiente y ejecutala.")
        self._anotar(out, chars)
        return out

    def _anotar(self, out: dict, chars: int) -> None:
        """Telemetria de proceso para `/bucle razonamiento`. Un subsistema sin
        diagnostico visible es indistinguible de uno que no se cableo, asi que
        esto existe; y como es diagnostico, jamas puede costar el turno."""
        try:
            if out.get("nudge"):
                _TOTAL[0] += 1
                _ULTIMO.clear()
                _ULTIMO.update({"chars": int(chars or 0),
                                "racha": out.get("racha", 0),
                                "repetido": bool(out.get("repetido")),
                                "apago": bool(out.get("apagar_pensamiento")),
                                "ts": __import__("time").strftime("%H:%M:%S")})
            if out.get("apagar_pensamiento"):
                _APAGADOS[0] += 1
        except Exception:
            pass

    # -- textos ------------------------------------------------------------
    def _cab(self, chars: int) -> str:
        return (f"{MARCA} Este paso se fue en pensar "
                f"({_num(chars)} caracteres de razonamiento) y no dejo nada "
                "verificable detras.")

    def _nudge_suave(self, chars: int) -> str:
        return (self._cab(chars) + " Pensar no avanza la tarea: el arnes solo "
                "mide lo que queda en disco. En tu proximo mensaje llama a UNA "
                "herramienta que CAMBIE algo o que compruebe tu siguiente "
                "suposicion — no releas lo que ya leiste.")

    def _nudge_fuerte(self, chars: int) -> str:
        return (self._cab(chars) + f" Van {self.racha} pasos seguidos igual: "
                f"{_num(self.chars_totales)} caracteres de analisis y ni un "
                "avance. PARA DE PLANEAR. Tu proximo mensaje tiene que ser una "
                "llamada a herramienta, sin analisis previo. Si no sabes cual: "
                "escribe o apenda la parte del fichero que ya tengas decidida, "
                "aunque sea pequena; un trozo en disco vale mas que un plan "
                "completo en tu cabeza.")

    def _nudge_duro(self, chars: int) -> str:
        return (self._cab(chars) + f" Son {self.racha} pasos seguidos sin un "
                "solo avance. Se apago el pensamiento extendido para el resto "
                "de la tarea: esta medido que con el apagado este modelo emite "
                "el fichero con la quinta parte del presupuesto. ACTUA AHORA: "
                "una llamada a herramienta, sin preambulo. Si el contenido es "
                "largo, mandalo POR PARTES (escribir_archivo con el primer "
                "trozo y apendar_archivo con cada trozo siguiente).")

    def informe(self) -> dict:
        """Estado json-able para el envelope del turno."""
        return {"turnos": self.turnos, "chars": self.chars_totales,
                "racha": self.racha, "repeticiones": self.repeticiones,
                "umbral": self.umbral, "racha_tope": self.racha_tope,
                "pensamiento_apagado": self._pedido_apagar}
