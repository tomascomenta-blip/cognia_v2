"""
cognia/agent/presupuesto_salida.py
==================================
El techo de generacion REAL es ``n_ctx - prompt``, no ``max_tokens``.

POR QUE EXISTE (medido 2026-08-30 contra el llama-server del dueno,
Qwen3.8-27B-Ridge en :8080 con n_ctx=65536). Se mando una peticion con un
prompt de 63.277 tokens y ``max_tokens=32768``:

    finish_reason : length
    usage         : completion_tokens=2258  prompt_tokens=63277
                    total_tokens=65535        <-- n_ctx MENOS UNO
    tool_calls    : NINGUNO
    content       : 0 chars
    reasoning     : 8827 chars

O sea: se pidieron 32768 tokens de salida y llegaron 2258, porque el server
corta en ``n_ctx``. El ``max_tokens`` del perfil no manda cuando el prompt ya
ocupa la ventana, y el bucle no lo sabia: ante un corte SUBIA max_tokens
(8192 -> 16384 -> 32768) y repetia el MISMO paso. Con el corte mandado por el
contexto la rampa es un no-op perfecto -- el modelo regenera el mismo
razonamiento y muere en la misma columna -- y cada vuelta cuesta una
generacion entera. En la corrida que lo cazo (tarea "un Minecraft en un solo
HTML", 2026-08-30) fueron 8 vueltas, 7 refunds, 92.245 tokens y 48 minutos
para CERO ficheros escritos.

Es la cara numero 12 de la familia "presupuesto de tokens con razonadores"
que este repo ya tiene documentada, y la primera en la que el numero que se
subia no era el que cortaba.

QUE APORTA. Aritmetica pura y testeable, sin red ni estado:

  - ``disponible()``    : lo que de verdad cabe de salida.
  - ``clamp()``         : max_tokens recortado a lo que cabe, con motivo.
  - ``es_corte_por_contexto()`` : distingue "se acabo el presupuesto que pedi"
    de "se acabo la VENTANA", que piden acciones opuestas (subir el tope /
    liberar contexto).
  - ``reparto()``       : cuanto de lo disponible se le va a ir en pensar.
"""

from __future__ import annotations

# Holgura para decidir "el corte lo dio la ventana". El server para en n_ctx-1
# (medido arriba), pero el prompt_tokens que devuelve no siempre cuadra al
# token con lo que el bucle estimo, y un razonador puede parar uno o dos antes.
# 256 es cero falsos positivos en las medidas y sigue siendo el 0,4% de una
# ventana de 64k: nadie llega ahi por casualidad.
HOLGURA_CONTEXTO = 256

# Reserva que NUNCA se pide como salida. El server necesita sitio para el
# turno que esta formateando y para los tokens de control de la plantilla;
# pedir exactamente n_ctx - prompt hace que el corte caiga justo en el ultimo
# token util, que es donde se rompe el JSON del tool call.
RESERVA = 512

# Por debajo de esto una llamada no puede terminar nada: un razonador gasta
# el presupuesto entero pensando y devuelve finish_reason='length' con cero
# tool_calls y cero content (medido: 2200 tokens -> 7668 chars de
# razonamiento y NADA mas). Llamar igual es pagar una generacion completa por
# un turno que ya se sabe que no cierra: lo que toca es liberar contexto.
MINIMO_UTIL = 4096


def disponible(n_ctx, prompt_tokens, reserva: int = RESERVA) -> int:
    """Tokens de salida que de verdad caben. 0 si no se puede saber.

    Sin ``n_ctx`` (backend que no publica /props) devuelve 0 = NO SE SABE, y
    el llamador deja el presupuesto como estaba. Devolver un numero inventado
    seria peor que no saber: recortaria max_tokens por una ventana imaginaria.
    """
    try:
        n_ctx = int(n_ctx or 0)
        prompt_tokens = int(prompt_tokens or 0)
    except (TypeError, ValueError):
        return 0
    if n_ctx <= 0:
        return 0
    return max(0, n_ctx - prompt_tokens - max(0, int(reserva)))


def clamp(max_tokens, n_ctx, prompt_tokens, reserva: int = RESERVA):
    """``(max_tokens_efectivo, motivo)``.

    ``motivo`` es "" cuando no se toco nada, y si no una linea legible para el
    aviso del CLI. Nunca sube el tope: solo lo baja a lo que cabe. Bajarlo no
    cambia lo que el modelo puede generar (ya lo cortaba la ventana), pero SI
    cambia lo que el bucle CREE, que es de donde salia la rampa inutil.
    """
    try:
        max_tokens = int(max_tokens or 0)
    except (TypeError, ValueError):
        return max_tokens, ""
    cabe = disponible(n_ctx, prompt_tokens, reserva)
    if not cabe:                      # sin n_ctx: no se sabe, no se toca
        return max_tokens, ""
    if max_tokens <= cabe:
        return max_tokens, ""
    return cabe, (f"la ventana solo deja {cabe} tokens de salida "
                  f"(max_tokens pedia {max_tokens})")


def es_corte_por_contexto(usage, n_ctx, holgura: int = HOLGURA_CONTEXTO) -> bool:
    """True si el turno se corto porque se lleno la VENTANA.

    La firma es ``total_tokens`` pegado a ``n_ctx`` (medido: 65535 de 65536).
    Se distingue de un corte por max_tokens porque ese para en el tope pedido
    y deja ventana de sobra. Los dos llegan como finish_reason='length' y por
    eso el bucle los confundia: subir max_tokens cura el segundo y no puede
    curar el primero.
    """
    try:
        n_ctx = int(n_ctx or 0)
    except (TypeError, ValueError):
        return False
    if n_ctx <= 0 or not isinstance(usage, dict):
        return False
    total = usage.get("total_tokens")
    if total is None:
        # Sin total_tokens se reconstruye; con un usage estimado por timings
        # puede faltar prompt_tokens, y entonces NO se afirma nada.
        p, c = usage.get("prompt_tokens"), usage.get("completion_tokens")
        if p is None or c is None:
            return False
        try:
            total = int(p) + int(c)
        except (TypeError, ValueError):
            return False
    try:
        return int(total) >= n_ctx - max(0, int(holgura))
    except (TypeError, ValueError):
        return False


def hay_sitio_para_trabajar(n_ctx, prompt_tokens,
                            minimo: int = MINIMO_UTIL) -> bool:
    """False cuando lo que queda de ventana no alcanza para que el turno
    cierre nada. Sin n_ctx devuelve True: no se sabe, y bloquear el turno por
    una ventana desconocida seria peor que intentarlo."""
    cabe = disponible(n_ctx, prompt_tokens)
    return cabe == 0 or cabe >= max(1, int(minimo))
