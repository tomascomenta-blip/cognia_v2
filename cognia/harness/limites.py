# -*- coding: utf-8 -*-
"""Limites TRIPLES + contabilidad del arnes: pasos, tiempo, tokens y dinero (2026-08-12).

POR QUE EXISTE
--------------
Los tres arneses punteros cortan por VARIOS ejes a la vez y lo hacen ANTES de
llamar al modelo, no despues: mini-swe-agent lleva `step_limit`, `cost_limit`
($3.0 por defecto) y `wall_time_limit`; Claude Code tiene `max_budget_usd` con
un subtipo de error propio; OpenHands cuenta un "iteration budget". Cognia hoy
solo tiene medio eje suelto: `cognia/agent/loop.py` calcula un techo de PASOS
(step budget dinamico) y `cognia/presupuesto_pared.py` corta por reloj de PARED
una llamada concreta. Nadie cuenta tokens ni dinero, y nadie mira los tres ejes
juntos antes de gastar un turno.

Este modulo es la contabilidad que falta, con dos decisiones deliberadas:

 1. **El corte es una EXCEPCION TIPADA, no un `return` silencioso.** Un `return`
    en mitad del bucle deja la tarea a medias sin que nadie lo diga y el usuario
    ve una respuesta truncada como si fuera la final (el fallo tipico de este
    repo: degradacion en silencio). `LimiteExcedido` lleva `eje`, `valor` y
    `limite` para que el integrador distinga "se acabo el presupuesto" de "se
    rompio algo", igual que el subtipo de error de Claude Code.
 2. **El mensaje del corte esta escrito PARA EL MODELO.** No es un log: es el
    siguiente prompt. Dice que hacer ("cierra con lo que tengas y di que falto")
    porque un modelo cuantizado chico al que solo se le dice "limite excedido"
    responde con una disculpa vacia en vez de entregar el trabajo parcial.

Y una tercera, medida fuera: los avisos preventivos van con NUMEROS LITERALES
("te quedan 3 pasos"), nunca con adjetivos ("vas justo"). Los adjetivos no mueven
la conducta del modelo; las cuentas si.

API (modulo autocontenido; el cableado al bucle lo hace el integrador):

    from cognia.harness.limites import (Presupuesto, Contador, LimiteExcedido,
                                        comprobar, restante, aviso_para_prompt,
                                        coste_de_uso)

    pres = Presupuesto()              # defectos leidos de env
    cont = Contador()
    while True:
        comprobar(cont, pres)         # ANTES de llamar al modelo; lanza si no hay margen
        r = restante(cont, pres)
        aviso = aviso_para_prompt(r)  # '' mientras haya holgura
        ...                           # llamada al modelo, con `aviso` inyectado si no es ''
        cont.paso()
        cont.sumar_tokens(uso["prompt_tokens"], uso["completion_tokens"])
        cont.sumar_coste(coste_de_uso(uso["prompt_tokens"], uso["completion_tokens"], precios))

Limites declarados (a proposito, no son deuda oculta):
  - `comprobar` NO interrumpe una llamada ya en vuelo: se comprueba entre pasos.
    Para cortar una llamada colgada esta `cognia/presupuesto_pared.py`, que es
    otra cosa (reloj de pared por celda) y sigue siendo necesaria.
  - El reloj es `time.monotonic()`: no lo mueve un ajuste de hora del sistema.
  - En LOCAL (llama-server, la flota de este repo) el dinero es SIEMPRE 0.0, asi
    que el eje que manda de verdad es el TIEMPO. Un `coste_max_usd` de $3 no
    dispara nunca contra Qwythos-9B; poner `COGNIA_MAX_SEGUNDOS` es lo que
    protege una corrida local.
  - No se estiman tokens por adelantado: se contabiliza lo que el backend
    REPORTA (`usage`). Si el backend no reporta `usage`, ese eje queda en 0 y no
    corta — un contador inventado seria peor que no tenerlo.
"""
from __future__ import annotations

import math
import os
import time
import warnings
from dataclasses import dataclass, field

# ── Ejes, en el orden en que se nombran y se desempatan ────────────────────
EJES = ("pasos", "segundos", "tokens", "usd")

# Defectos sensatos si no hay env. Los de mini-swe-agent como referencia
# ($3.0 de coste), y un techo de pasos del orden del step budget del loop.
DEF_PASOS = 40
DEF_SEGUNDOS = 900.0     # 15 min de pared: en local ES el eje que corta
DEF_TOKENS = 400_000
DEF_USD = 3.0

# Umbrales de apremio sobre la fraccion consumida del eje mas exigido.
UMBRAL_AJUSTADO = 0.70
UMBRAL_CRITICO = 0.90

# Precios de la flota local: cero. Explicito para que el integrador no invente.
PRECIOS_LOCAL = {"entrada": 0.0, "salida": 0.0}

_APAGADO = ("", "none", "null", "sin", "off", "no", "inf", "infinito", "-1")

# `_env_num` corre dentro del `__init__` que genera @dataclass, asi que hay tres
# marcos por encima (env_num -> _def_X -> __init__ generado) antes de llegar al
# `Presupuesto()` que escribio el integrador: con menos, el aviso apunta a
# '<string>:3' y no sirve para encontrar la env sucia.
_NIVEL_AVISO = 4


def _env_num(nombre: str, defecto, entero: bool):
    """Lee un eje del entorno. Devuelve numero, o None = SIN LIMITE.

    Reglas (documentadas porque un env mal leido es un limite fantasma):
      - variable ausente            -> `defecto`
      - '', 'none', 'off', '0', ... -> None (sin limite: apagar el eje a mano)
      - basura no numerica          -> `defecto` + WARNING (nunca reventar por un
        env sucio, pero tampoco callarselo: un tope que no es el que el usuario
        escribio es peor que no tener tope, porque nadie lo mira)
      - 'nan'/'+inf'                -> `defecto` + WARNING. Un NaN de tope NO
        corta nunca (`val >= nan` es False) y envenena `restante` con margenes
        NaN: seria un limite fantasma silencioso, justo lo que este modulo evita.

    En los ejes ENTEROS se acepta igual notacion decimal o cientifica ('1e3',
    '40.5') y se trunca: antes cualquiera de esas caia al defecto en silencio, o
    sea el usuario pedia 1000 pasos y se llevaba 40 sin enterarse.
    """
    crudo = os.environ.get(nombre)
    if crudo is None:
        return defecto
    s = crudo.strip().lower()
    if s in _APAGADO:
        return None
    try:
        v = float(s)
    except ValueError:
        warnings.warn(f"{nombre}={crudo!r} no es un numero: se usa el defecto "
                      f"{defecto!r}", RuntimeWarning, stacklevel=_NIVEL_AVISO)
        return defecto
    if not math.isfinite(v):
        warnings.warn(f"{nombre}={crudo!r} no es finito: se usa el defecto "
                      f"{defecto!r} (para apagar el eje pone 0 o 'none')",
                      RuntimeWarning, stacklevel=_NIVEL_AVISO)
        return defecto
    if v <= 0:
        return None
    # Eje entero: se trunca, pero un positivo NUNCA se convierte en 0 (que
    # cortaria en el paso 0) ni en None (que quitaria el tope): minimo 1.
    return max(1, int(v)) if entero else v


def _def_pasos():
    return _env_num("COGNIA_MAX_PASOS", DEF_PASOS, True)


def _def_segundos():
    return _env_num("COGNIA_MAX_SEGUNDOS", DEF_SEGUNDOS, False)


def _def_tokens():
    return _env_num("COGNIA_MAX_TOKENS", DEF_TOKENS, True)


def _def_usd():
    return _env_num("COGNIA_MAX_USD", DEF_USD, False)


@dataclass
class Presupuesto:
    """Los cuatro topes. `None` en un eje = ese eje no corta nunca.

    Los defectos se leen del ENTORNO en el momento de construir (no al importar):
    asi un cambio de `COGNIA_MAX_*` en la misma sesion se respeta, en vez de
    quedar congelado en el primer import.
    """
    pasos_max: int | None = field(default_factory=_def_pasos)
    segundos_max: float | None = field(default_factory=_def_segundos)
    tokens_max: int | None = field(default_factory=_def_tokens)
    coste_max_usd: float | None = field(default_factory=_def_usd)

    def limite(self, eje: str):
        """Tope del eje ('pasos'|'segundos'|'tokens'|'usd'), o None si no hay.

        Un tope NO FINITO (inf/nan, que puede colarse por construccion directa
        aunque el env ya lo rechace) se normaliza a None = sin limite: es el
        unico punto donde se puede cortar, porque `nan` comparado con `>=` da
        siempre False (no cortaria jamas) y ademas contamina `restante` con
        margenes y fracciones NaN que ninguna barra de estado sabe pintar.
        """
        v = {
            "pasos": self.pasos_max,
            "segundos": self.segundos_max,
            "tokens": self.tokens_max,
            "usd": self.coste_max_usd,
        }[eje]
        if isinstance(v, float) and not math.isfinite(v):
            return None
        return v


@dataclass
class Contador:
    """Lo gastado hasta ahora. Plano y mutable: lo actualiza el bucle."""
    pasos: int = 0
    tokens_entrada: int = 0
    tokens_salida: int = 0
    usd: float = 0.0
    # Reloj monotonico: inmune a que el sistema ajuste la hora a mitad de corrida.
    inicio: float = field(default_factory=time.monotonic)

    @property
    def tokens(self) -> int:
        """Tokens totales (entrada + salida): es lo que se compara con el tope."""
        return self.tokens_entrada + self.tokens_salida

    def paso(self) -> int:
        """Cuenta un paso consumido. Devuelve el total."""
        self.pasos += 1
        return self.pasos

    def sumar_tokens(self, entrada: int, salida: int) -> int:
        """Acumula el `usage` REPORTADO por el backend. Devuelve el total."""
        self.tokens_entrada += int(entrada or 0)
        self.tokens_salida += int(salida or 0)
        return self.tokens

    def sumar_coste(self, usd: float) -> float:
        """Acumula dinero. En local siempre se le pasa 0.0. Devuelve el total."""
        self.usd += float(usd or 0.0)
        return self.usd

    def transcurrido(self) -> float:
        """Segundos de pared desde que arranco la tarea."""
        return time.monotonic() - self.inicio

    def valor(self, eje: str):
        """Gasto actual del eje, en las unidades de su tope."""
        return {
            "pasos": self.pasos,
            "segundos": self.transcurrido(),
            "tokens": self.tokens,
            "usd": self.usd,
        }[eje]


class LimiteExcedido(Exception):
    """Corte por presupuesto. NO es un bug: es el arnes haciendo su trabajo.

    Lleva `eje`, `valor` y `limite` para que el integrador la distinga de un
    fallo real (el equivalente al subtipo de error de presupuesto de Claude
    Code) y su texto esta escrito para el MODELO, no para un log.
    """

    def __init__(self, eje: str, valor, limite):
        self.eje = eje
        self.valor = valor
        self.limite = limite
        super().__init__(_mensaje_corte(eje, valor, limite))

    def __reduce__(self):
        """Sobrevivir a pickle/deepcopy (motor de workflows: brazos en PROCESOS).

        `Exception.__reduce__` reconstruye llamando `LimiteExcedido(*self.args)`,
        y aqui `args` es solo el mensaje -> al cruzar un ProcessPoolExecutor
        petaba con 'missing 2 required positional arguments' y el corte por
        presupuesto llegaba al padre disfrazado de fallo del arnes, que es
        exactamente la confusion que esta excepcion existe para evitar.
        """
        return (self.__class__, (self.eje, self.valor, self.limite))


def _n(x) -> str:
    """Numero corto y legible: entero si lo es, si no 2 decimales."""
    f = float(x)
    if abs(f - round(f)) < 1e-9:
        return str(int(round(f)))
    return f"{f:.2f}"


_CIERRA = ("CIERRA AHORA con lo que tengas: responde al usuario con el resultado "
           "parcial, di EXPLICITAMENTE que falto y que quedaba por hacer. No "
           "llames mas herramientas.")


def _mensaje_corte(eje: str, valor, limite) -> str:
    """El texto que ve el modelo. Primero el hecho con numeros, luego la orden."""
    if eje == "pasos":
        cabeza = f"te quedaste sin pasos: llevas {_n(valor)} de {_n(limite)}"
    elif eje == "segundos":
        cabeza = f"te quedaste sin tiempo: llevas {_n(valor)} s de {_n(limite)} s"
    elif eje == "tokens":
        cabeza = f"te quedaste sin tokens: llevas {_n(valor)} de {_n(limite)}"
    else:
        cabeza = f"te quedaste sin presupuesto: llevas {_n(valor)} USD de {_n(limite)} USD"
    return f"{cabeza}. {_CIERRA}"


def comprobar(contador: Contador, presupuesto: Presupuesto) -> None:
    """Los TRES (cuatro) limites, ANTES de cada llamada al modelo.

    `None` si hay margen; `LimiteExcedido` si no. Si hay varios ejes pasados se
    reporta el MAS excedido (mayor fraccion consumida), desempatando por el orden
    de `EJES`: el mensaje nombra la causa dominante, no la primera de la lista.
    """
    culpables = []
    for eje in EJES:
        lim = presupuesto.limite(eje)
        if lim is None:
            continue
        val = contador.valor(eje)
        if val >= lim:
            culpables.append((val / lim if lim else 0.0, eje, val, lim))
    if not culpables:
        return None
    # `max` devuelve el PRIMER maximo y `culpables` se llena en el orden de
    # EJES: con fracciones empatadas manda el eje que va antes en EJES.
    _, eje, val, lim = max(culpables, key=lambda t: t[0])
    raise LimiteExcedido(eje, val, lim)


def restante(contador: Contador, presupuesto: Presupuesto) -> dict:
    """Margen por eje + el apremio global. Pensado para la barra de estado.

    Devuelve, por cada eje, un sub-dict {usado, limite, margen, fraccion}, mas:
      - 'apremio': 'holgado' (<70%), 'ajustado' (>=70%), 'critico' (>=90%)
      - 'eje': el eje MAS exigido (None si ningun eje tiene tope)
      - 'fraccion': su fraccion consumida
    Un eje sin tope tiene limite/margen None y fraccion 0.0: no puede apremiar.
    """
    out: dict = {}
    peor = (-1.0, None)
    for eje in EJES:
        lim = presupuesto.limite(eje)
        val = contador.valor(eje)
        if lim is None:
            out[eje] = {"usado": val, "limite": None, "margen": None, "fraccion": 0.0}
            continue
        # Tope <= 0 (el 0 explicito, o un `techo - ya_gastado` que se paso de
        # rosca al reanudar) = eje AGOTADO. Sin esto, un tope negativo daba
        # fraccion -0.0 -> 'holgado' en la barra de estado mientras `comprobar`
        # ya estaba cortando: el pintor y el verdugo decian cosas distintas.
        frac = (val / lim) if lim > 0 else 1.0
        out[eje] = {
            "usado": val,
            "limite": lim,
            "margen": max(lim - val, 0) if isinstance(lim, int) else max(lim - val, 0.0),
            "fraccion": frac,
        }
        if frac > peor[0]:
            peor = (frac, eje)
    frac, eje = (peor if peor[1] is not None else (0.0, None))
    out["eje"] = eje
    out["fraccion"] = frac
    out["apremio"] = ("critico" if frac >= UMBRAL_CRITICO
                      else "ajustado" if frac >= UMBRAL_AJUSTADO
                      else "holgado")
    return out


def _frase_margen(eje: str, d: dict) -> str:
    """'te quedan 3 pasos' y no 'vas justo': el numero LITERAL es lo que funciona."""
    m = d["margen"]
    if eje == "pasos":
        n = int(m)
        return f"{n} paso" if n == 1 else f"{n} pasos"
    if eje == "segundos":
        return f"{_n(m)} s"
    if eje == "tokens":
        # Singular tambien aqui: salia "te queda 1 tokens" (la concordancia solo
        # estaba resuelta para 'pasos'). Al modelo se le habla bien o no obedece.
        return "1 token" if _n(m) == "1" else f"{_n(m)} tokens"
    return f"{_n(m)} USD"


def aviso_para_prompt(r: dict) -> str:
    """La linea LITERAL que se le inyecta al modelo cuando aprieta el presupuesto.

    Cadena VACIA mientras el apremio sea 'holgado' (no gastar contexto ni meter
    prisa sin motivo). En cuanto deja de serlo, la linea lleva los numeros de
    TODOS los ejes con tope — el ranking #12 lo mide: los presupuestos numericos
    literales en el prompt mueven la conducta; los adjetivos no.
    """
    apremio = r.get("apremio", "holgado")
    if apremio == "holgado":
        return ""
    partes = [_frase_margen(eje, r[eje]) for eje in EJES
              if isinstance(r.get(eje), dict) and r[eje]["limite"] is not None]
    if not partes:
        return ""
    # Enumeracion en castellano: "a", "a y b", "a, b y c" (con UN solo eje el
    # `join` de la cola se comia la frase entera; el aviso salia sin numeros).
    cuenta = partes[0] if len(partes) == 1 else ", ".join(partes[:-1]) + " y " + partes[-1]
    # Concordancia: con un solo eje y valor 1 es "te queda 1 paso", no "te quedan".
    verbo = "te queda" if (len(partes) == 1 and partes[0].startswith("1 ")) else "te quedan"
    if apremio == "critico":
        return (f"PRESUPUESTO CRITICO: {verbo} {cuenta}. Es tu ULTIMO turno util: "
                f"da la respuesta final ya, con lo que tengas, y di que quedo sin hacer.")
    return (f"PRESUPUESTO AJUSTADO: {verbo} {cuenta}. Deja de explorar: haz solo "
            f"lo imprescindible para cerrar la tarea y responde.")


def coste_de_uso(prompt_tokens: int, completion_tokens: int, precios: dict | None) -> float:
    """USD de una llamada. `precios` va POR MILLON de tokens: {'entrada', 'salida'}.

    Ejemplo: {'entrada': 3.0, 'salida': 15.0} = $3/Mtok de entrada, $15/Mtok de
    salida. Con `PRECIOS_LOCAL` (o None, o dict vacio) devuelve 0.0: la flota de
    este repo corre en llama-server y no cuesta dinero — en local el eje que
    manda es TIEMPO (`COGNIA_MAX_SEGUNDOS`), no dinero. Claves ausentes valen 0.
    """
    p = precios or {}
    ent = float(p.get("entrada", 0.0) or 0.0)
    sal = float(p.get("salida", 0.0) or 0.0)
    usd = (int(prompt_tokens or 0) * ent + int(completion_tokens or 0) * sal) / 1_000_000.0
    return round(float(usd), 8)
