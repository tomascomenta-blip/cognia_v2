# -*- coding: utf-8 -*-
"""Presupuesto gobernado por PROGRESO VERIFICADO, no por cantidad (2026-08-18).

POR QUE EXISTE
--------------
Hoy todo arnes corta por CANTIDAD: `max_iterations`, `step_limit`, `cost_limit`,
`max_tokens`. Ninguno sabe decir la frase que importa: "llevas 400k tokens y cero
tests nuevos en verde". Por eso el 95,6% de los bucles documentados terminan en
agotamiento de coste: el unico limite se dispara cuando se acaba el contador, no
cuando el trabajo dejo de avanzar. Un bucle que repite la misma edicion rota 400
veces y uno que resuelve la tarea en 4 pasos consumen el MISMO presupuesto y el
arnes no distingue uno de otro hasta que ya se lo gasto.

Este modulo mide la otra magnitud: COSTE POR UNIDAD DE PROGRESO VERIFICADO, y
corta cuando la curva se aplana. Tres decisiones deliberadas:

 1. **Un avance no se declara, se OBSERVA.** `avanzar()` exige `evidencia` no
    vacia y un `tipo` de la lista cerrada; todos los tipos son comprobables por
    la maquina. "El modelo dice que avanzo" no es un avance. Los observadores
    (`observar_*`) van mas lejos: reciben el resultado de la comprobacion y solo
    cuentan avance en la TRANSICION (rojo->verde, error presente->ausente,
    fichero inexistente->valido). Volver a correr un test que ya estaba verde no
    suma nada: si sumara, un bucle que repite `pytest` pareceria avanzar para
    siempre, que es exactamente el fallo que este modulo persigue.
 2. **El estado vive fuera de la prosa.** `informe()` devuelve un dict plano
    json-able pensado para el envelope del turno. La compactacion puede tirar la
    conversacion entera: la contabilidad sobrevive porque no es texto que haya
    que resumir, son numeros que se copian tal cual.
 3. **Los umbrales salen de trazas REALES de este repo, no del gusto.** Ver la
    seccion de constantes: cada numero lleva la medicion que lo fija.

API (modulo autocontenido; el cableado al bucle lo hace el integrador):

    from cognia.estado.presupuesto_progreso import Progreso, comparar

    p = Progreso(nombre="tarea-42", tope_tokens=400_000)
    while True:
        v = p.veredicto()                      # ANTES de gastar otro turno
        if v["estado"] != "avanza":
            break                              # v["sugerencia"] es el siguiente prompt
        ...                                    # llamada al modelo + herramientas
        p.gastar(tokens=uso["total_tokens"], segundos=dt, pasos=1)
        p.observar_verificacion("pytest tests/test_x.py", ok=paso_el_test,
                                evidencia=salida_recortada)
        p.observar_fichero("cognia/x.py")
    envelope["progreso"] = p.informe()

Limites declarados (a proposito, no son deuda oculta):
  - **No hay reloj interno.** El coste SIEMPRE entra por `gastar()`. Un modulo que
    llamara a `time.monotonic()` por su cuenta seria intesteable sin dormir el
    proceso y mentiria en un `resume` (el tiempo entre sesiones no es trabajo).
  - **No ejecuta nada.** No corre pytest, no invoca linters, no llama al modelo.
    Recibe el resultado de la verificacion que ya hizo otro (`cognia/harness/
    verificacion.py` es el proveedor natural). Un modulo de contabilidad que
    ademas ejecuta se vuelve imposible de testear sin red ni modelo.
  - **`observar_fichero` solo valida Python y JSON.** Para el resto comprueba
    existencia y tamano > 0. Declarar "compila" sobre un .md seria mentir.
  - **El veredicto NO lanza excepciones ni corta por su cuenta.** Devuelve un
    dict; quien decide es el bucle. Cortar desde aqui esconderia la decision.
  - **Governance decay queda FUERA.** Este modulo no vigila si las restricciones
    de seguridad siguen en el contexto activo; eso es otro canal de estado.
  - **FALSA ALARMA MEDIDA en fases de arranque con verificacion tardia.** En el
    replay de `cognia_v3/eval/results_promptevo_ap_fast_v3_20260705_1755` el
    veredicto dispara `sin_arranque` en la generacion 4, pero esa corrida si
    lograba su unico avance verificado en la generacion 20: las 20 primeras
    generaciones son la cosecha de exemplars, que por diseno no mide nada hasta
    terminar. Regla practica: si una fase NO puede verificar nada antes de
    `umbral_arranque` pasos, subelo para esa fase (`Progreso(umbral_arranque=N)`)
    o emite las comprobaciones parciales que si existan. Con el umbral por
    defecto el corte honesto de esa corrida (el primero POSTERIOR a su ultimo
    avance real) cae en la generacion 25 y habria ahorrado 8.531 s de 9.701
    (87,9%) que terminaron en delta_test = +0,000.
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path

# -- Tipos de avance: lista CERRADA y toda ella comprobable por la maquina --
#
# La lista es cerrada a proposito. Si `avanzar()` aceptara cualquier cadena, el
# primer tipo inventado ("progreso_conceptual", "entendi_el_bug") volveria a
# meter la autoevaluacion del modelo dentro de la contabilidad, que es la
# enfermedad que este modulo cura.
TIPO_FICHERO = "fichero_nuevo_valido"          # existe, no vacio y (si es codigo) compila
TIPO_TEST = "test_en_verde"                    # verificacion que ANTES fallaba y ahora pasa
TIPO_POSTCONDICION = "postcondicion_cumplida"  # postcondicion declarada, ahora cierta
TIPO_ERROR = "error_resuelto"                  # un error que aparecia y ya no aparece
TIPO_PENDIENTE = "pendiente_resuelto"          # item de pendientes, cerrado con evidencia
TIPO_CRECIMIENTO = "artefacto_crecio_valido"   # el MISMO fichero crecio y sigue siendo valido

TIPOS_AVANCE = (
    TIPO_FICHERO,
    TIPO_TEST,
    TIPO_POSTCONDICION,
    TIPO_ERROR,
    TIPO_PENDIENTE,
    TIPO_CRECIMIENTO,
)

# -- Umbrales, con la medicion que los fija --------------------------------
#
# MEDIDO sobre `b3_codigo/reparacion.json` (893 muestras reales del experimento
# de reparacion con contraejemplo, 135 tareas, tokens y segundos reales por
# intento). De las 135 tareas del brazo raiz+rep, 69 llegaron a algun avance
# verificado (`pasa_vis`). La peor racha de intentos ESTERILES que precede a un
# avance real es 3 (distribucion: 48 tareas con racha 0, 9 con 1, 6 con 2, 6 con
# 3). Cortar en 3 reprobaria a esas 6 tareas que si iban a llegar.
PASOS_SIN_AVANCE_SIN_ARRANQUE = 4
# 4 = primer valor que no reprueba a NINGUNA de las 135 tareas reales. El
# contrafactual, corrido sobre esas mismas 69 tareas que si avanzaban:
# umbral 2 -> 12 falsas alarmas, umbral 3 -> 6, umbral 4 -> 0, umbral 5 -> 0.
# Se queda en 4 (el mas barato de los que no reprueban a nadie). Se aplica solo
# cuando la corrida no ha logrado NI UN avance: sin una sola prueba de que la via
# funciona, no hay razon para pagar un quinto intento.

PASOS_SIN_AVANCE_ESTANCADO = 5
# 5 = la peor racha real observada (3) mas 2 de margen. Se aplica cuando ya hubo
# algun avance: ahi si hay evidencia de que la via funciona, asi que se le
# concede un intento mas de holgura que a la corrida que nunca arranco.

FACTOR_MESETA_COSTE = 5.0
# Meseta de COSTE: se declara estancado si el gasto desde el ultimo avance supera
# 5x la mediana de coste por avance DE ESTA MISMA CORRIDA. Es auto-calibrado a
# proposito: un umbral absoluto en tokens ("400k") es correcto para una tarea y
# absurdo para otra. El 5,0 sale de la dispersion real del coste por unidad:
# max/mediana = 2,67 en tokens (b3_codigo/reparacion.json, 326 intentos) y
# max/mediana = 4,13 en segundos (cognia_v3/eval/results_promptevo_ap_fast_v3,
# 220 generaciones); p95/mediana = 1,90 y 1,76. 5,0 queda por encima del peor
# outlier medido, asi que una unidad legitimamente cara NO dispara la regla.

MIN_AVANCES_PARA_FACTOR = 2
# La regla de meseta de coste necesita una linea base propia. Con un solo avance
# la "mediana de coste por avance" es ese unico dato y cortar por el seria cortar
# por ruido.

MIN_CRECIMIENTO_BYTES = 200
# UN ARTEFACTO QUE CRECE ES PROGRESO (2026-08-30). `observar_fichero` solo
# contaba la transicion inexistente->valido, asi que una tarea que construye UN
# fichero grande por partes (escribir_archivo + N apendar_archivo, que es como
# el arnes obliga a escribir cuando el contenido no cabe en un tool call)
# registraba exactamente UN avance y despues parecia parada. MEDIDO en la
# corrida real del minecraft.html (2026-08-30): 1 escritura + 4 apendices + 1
# edicion = 6 pasos, UN avance, cierre por 'meseta' en el paso 8 con el fichero
# a medias (655 lineas, sin bucle de juego y sin `</html>`).
#
# El avance sigue siendo OBSERVADO, no declarado, y sigue siendo una TRANSICION:
# el fichero tiene que seguir siendo valido y superar el MAXIMO historico de
# bytes de esta corrida. Un churn que reescribe lo mismo (A->B->A) no crece
# nunca, y por eso no puntua: es la misma propiedad anti-gaming del modulo.
# 200 bytes = un bloque de codigo de verdad; por debajo es retoque.

CREDITO_EXPLORACION = 8
# LEER NO ES ESTAR ATASCADO (2026-08-30). `pasos_sin_avance` contaba TODOS los
# pasos, incluidos los de solo lectura. MEDIDO: con el offload a 2.000 bytes,
# recorrer entero el fichero de 32 KB que habia que editar costaba 1 `listar` +
# 1 `leer_archivo` + 5 `recuperar` = SIETE pasos de pura lectura, y el umbral de
# arranque era 6: la corrida moria por 'sin_arranque' antes de tener derecho a
# su primera edicion. Paso tres veces seguidas el 2026-08-30.
#
# Los pasos exploratorios (tools puras: leer/listar/buscar/recuperar) no gastan
# credito de arranque hasta `credito_exploracion`. PROPIEDAD QUE IMPORTA: los
# pasos efectivos son SIEMPRE <= los crudos, o sea que esta regla solo puede
# RETRASAR un corte, nunca adelantarlo -- no puede introducir ni una falsa
# alarma nueva sobre las 135 tareas con las que se calibro el umbral 4. El tope
# existe para que un bucle de solo lectura siga siendo finito: 8 lecturas
# seguidas sin producir nada ya vuelven a contar.

# -- Sugerencias: escritas PARA EL MODELO, no para un log ------------------
#
# Un "estancado: limite alcanzado" hace que un modelo chico responda con una
# disculpa vacia. La sugerencia dice QUE HACER y nombra las tres unicas salidas
# honestas de un atasco: cambiar de via, pedir ayuda, o cerrar diciendo la verdad.
_SUGERENCIAS = {
    "sin_arranque": (
        "Cero avances verificados en {pasos} pasos y {tokens} tokens. La via elegida no ha "
        "producido NI UNA prueba objetiva. No repitas el mismo intento: (1) cambia de via "
        "-- lee el fichero o el error real antes de volver a escribir, o ataca un subproblema "
        "mas chico que si puedas verificar; (2) si te falta un dato que no esta en el "
        "contexto, PIDELO en vez de adivinarlo; (3) si la tarea no es alcanzable con lo que "
        "tienes, cierra diciendo exactamente que falta y que se intento."
    ),
    "meseta": (
        "{avances} avances verificados, pero los ultimos {pasos} pasos ({tokens} tokens) no "
        "produjeron ninguno. Estas iterando sobre lo mismo. Entrega lo que YA esta verificado "
        "({ultimo}), y para lo que falta: cambia de via, pide el dato que te falta, o cierra "
        "declarando el resto como no hecho. No vuelvas a intentar la misma edicion."
    ),
    "meseta_de_coste": (
        "El gasto desde el ultimo avance ({tokens} tokens) ya supera {factor}x lo que te "
        "costo de mediana cada avance de esta misma corrida ({mediana} tokens). Este intento "
        "es anomalamente caro: parte el problema en algo mas chico y verificable, o cierra "
        "con lo hecho."
    ),
    "agotado": (
        "Presupuesto agotado por {eje}: {valor} de {limite}. Llevas {avances} avances "
        "verificados. Cierra AHORA: entrega lo verificado, di en una linea que quedo sin "
        "hacer y por que. No empieces nada nuevo."
    ),
    "avanza": (
        "La corrida avanza: {avances} avances verificados, ultimo hace {pasos} paso(s). Sigue."
    ),
}


def _num(x, nombre):
    """Rechaza costes negativos: un gasto negativo reescribiria la historia en silencio."""
    if x is None:
        return 0
    if x < 0:
        raise ValueError("%s no puede ser negativo (recibido %r)" % (nombre, x))
    return x


class Progreso:
    """Acumulador de coste y de avances VERIFICADOS de una corrida.

    Todo el coste entra por `gastar()`; todo el avance entra por `avanzar()` o por
    un `observar_*`. No hay ninguna otra via de mutar el estado.
    """

    def __init__(
        self,
        nombre="corrida",
        tope_tokens=None,
        tope_segundos=None,
        tope_pasos=None,
        umbral_estancado=PASOS_SIN_AVANCE_ESTANCADO,
        umbral_arranque=PASOS_SIN_AVANCE_SIN_ARRANQUE,
        factor_meseta=FACTOR_MESETA_COSTE,
        credito_exploracion=CREDITO_EXPLORACION,
        contar_crecimiento=True,
    ):
        self.nombre = nombre
        self.tope_tokens = tope_tokens
        self.tope_segundos = tope_segundos
        self.tope_pasos = tope_pasos
        self.umbral_estancado = umbral_estancado
        self.umbral_arranque = umbral_arranque
        self.factor_meseta = factor_meseta
        self.credito_exploracion = max(0, int(credito_exploracion or 0))
        # Este modulo NO lee el entorno a proposito (seria intesteable y
        # mentiria en un resume): el interruptor COGNIA_TAREAS_LARGAS lo
        # traduce el integrador, que es quien si conoce el entorno.
        self.contar_crecimiento = bool(contar_crecimiento)

        self.tokens = 0
        self.segundos = 0.0
        self.pasos = 0

        self.avances = []      # dicts serializables, en orden
        self.regresiones = []  # verde->rojo y error que reaparece: no restan, pero se registran
        self._gastos = []      # un dict por llamada a gastar(), para curva()

        # Memoria del canal de ESTADO. Sin ella no existe la nocion de TRANSICION
        # y "test en verde" degeneraria en "test corrido".
        self._verificaciones = {}   # clave -> bool (ultimo resultado conocido)
        self._errores = {}          # firma -> bool (presente)
        self._ficheros = {}         # ruta -> bool (valido)
        self._tam_max = {}          # ruta -> bytes MAXIMOS vistos (para el crecimiento)
        self._postcondiciones = {}  # nombre -> bool
        self._pendientes = {}       # id -> bool (resuelto)

    # -- Coste -------------------------------------------------------------
    def gastar(self, tokens=0, segundos=0.0, pasos=1, exploratorio=False):
        """Suma coste. Devuelve el snapshot acumulado (dict).

        `exploratorio=True` marca el paso como de SOLO LECTURA (tools puras).
        Sigue costando tokens y segundos igual que cualquier otro -- lo unico
        que cambia es que no gasta credito de arranque mientras quede
        `credito_exploracion`. Ver la constante para el porque y el limite.
        """
        tokens = _num(tokens, "tokens")
        segundos = _num(segundos, "segundos")
        pasos = _num(pasos, "pasos")
        self.tokens += int(tokens)
        self.segundos += float(segundos)
        self.pasos += int(pasos)
        self._gastos.append(
            {"paso": self.pasos, "tokens": int(tokens), "segundos": float(segundos),
             "exploratorio": bool(exploratorio)}
        )
        return {"tokens": self.tokens, "segundos": self.segundos, "pasos": self.pasos}

    def marcar_exploratorio(self, valor=True):
        """Marca el ULTIMO paso gastado como exploratorio (o deja de marcarlo).

        Existe porque el integrador cobra el paso en cuanto el modelo contesta,
        pero solo sabe si fue de lectura DESPUES de ejecutar las tools de ese
        paso. Sin gasto previo no hace nada (nunca lanza: es contabilidad).
        """
        if not self._gastos:
            return False
        self._gastos[-1]["exploratorio"] = bool(valor)
        return True

    # -- Avance ------------------------------------------------------------
    def avanzar(self, tipo, detalle, evidencia):
        """Registra un avance VERIFICADO. Lanza ValueError si no lo es.

        `evidencia` es obligatoria y no vacia: un avance sin evidencia es
        exactamente lo que este modulo existe para impedir.
        """
        if tipo not in TIPOS_AVANCE:
            raise ValueError(
                "tipo de avance desconocido %r; los validos son %s" % (tipo, list(TIPOS_AVANCE))
            )
        if not str(detalle or "").strip():
            raise ValueError("un avance sin `detalle` no es rastreable")
        if not str(evidencia or "").strip():
            raise ValueError(
                "un avance sin `evidencia` no es verificable: es exactamente lo que este "
                "modulo existe para impedir"
            )
        av = {
            "n": len(self.avances) + 1,
            "tipo": tipo,
            "detalle": str(detalle),
            "evidencia": str(evidencia),
            "paso": self.pasos,
            "tokens": self.tokens,
            "segundos": round(self.segundos, 3),
        }
        self.avances.append(av)
        return av

    def _regresion(self, tipo, detalle, evidencia):
        reg = {
            "tipo": tipo,
            "detalle": str(detalle),
            "evidencia": str(evidencia or ""),
            "paso": self.pasos,
            "tokens": self.tokens,
        }
        self.regresiones.append(reg)
        return reg

    # -- Observadores: la transicion es la que cuenta ----------------------
    def observar_verificacion(self, clave, ok, evidencia=""):
        """Un comando de verificacion (pytest, un check) dio `ok` o no.

        Solo la transicion rojo->verde cuenta como avance. Verde->verde no suma:
        si sumara, correr el mismo test en bucle simularia progreso infinito.
        """
        antes = self._verificaciones.get(clave)
        self._verificaciones[clave] = bool(ok)
        if ok and antes is False:
            return {
                "avance": self.avanzar(
                    TIPO_TEST, clave, evidencia or "verificacion en verde: %s" % clave),
                "transicion": "rojo->verde",
            }
        if (not ok) and antes is True:
            return {"avance": None, "transicion": "verde->rojo",
                    "regresion": self._regresion(TIPO_TEST, clave, evidencia)}
        return {"avance": None,
                "transicion": "sin_cambio" if antes is not None else "primera_observacion"}

    def observar_error(self, firma, presente, evidencia=""):
        """Un error identificado por `firma` esta o no presente. presente->ausente es avance."""
        antes = self._errores.get(firma)
        self._errores[firma] = bool(presente)
        if (not presente) and antes is True:
            return {
                "avance": self.avanzar(
                    TIPO_ERROR, firma, evidencia or "el error ya no aparece: %s" % firma),
                "transicion": "presente->ausente",
            }
        if presente and antes is False:
            return {"avance": None, "transicion": "ausente->presente",
                    "regresion": self._regresion(TIPO_ERROR, firma, evidencia)}
        return {"avance": None,
                "transicion": "sin_cambio" if antes is not None else "primera_observacion"}

    def observar_postcondicion(self, nombre, ok, evidencia=""):
        """Una postcondicion declarada de la tarea. falso->cierto es avance."""
        antes = self._postcondiciones.get(nombre)
        self._postcondiciones[nombre] = bool(ok)
        if ok and not antes:
            return {
                "avance": self.avanzar(
                    TIPO_POSTCONDICION, nombre,
                    evidencia or "postcondicion cumplida: %s" % nombre),
                "transicion": "falso->cierto",
            }
        if (not ok) and antes is True:
            return {"avance": None, "transicion": "cierto->falso",
                    "regresion": self._regresion(TIPO_POSTCONDICION, nombre, evidencia)}
        return {"avance": None,
                "transicion": "sin_cambio" if antes is not None else "primera_observacion"}

    def observar_pendiente(self, ident, resuelto, evidencia=""):
        """Un item de la lista de pendientes. abierto->resuelto es avance."""
        antes = self._pendientes.get(ident)
        self._pendientes[ident] = bool(resuelto)
        if resuelto and not antes:
            return {
                "avance": self.avanzar(
                    TIPO_PENDIENTE, ident, evidencia or "pendiente cerrado: %s" % ident),
                "transicion": "abierto->resuelto",
            }
        if (not resuelto) and antes is True:
            return {"avance": None, "transicion": "resuelto->abierto",
                    "regresion": self._regresion(TIPO_PENDIENTE, ident, evidencia)}
        return {"avance": None,
                "transicion": "sin_cambio" if antes is not None else "primera_observacion"}

    def observar_fichero(self, ruta, contenido=None):
        """Un fichero existe, no esta vacio y (si es .py/.json) parsea.

        `contenido` permite verificar sin tocar disco (util cuando el arnes acaba
        de escribirlo y ya lo tiene en memoria). Cuenta una sola vez por ruta: el
        segundo `escribir_archivo` sobre el mismo fichero no es un avance nuevo.
        """
        ruta_s = str(ruta)
        valido, motivo = _validar_fichero(ruta_s, contenido)
        tam = _tamano_fichero(ruta_s, contenido)
        antes = self._ficheros.get(ruta_s)
        self._ficheros[ruta_s] = valido
        if valido and not antes:
            if tam is not None:
                self._tam_max[ruta_s] = tam
            return {"avance": self.avanzar(TIPO_FICHERO, ruta_s, motivo),
                    "valido": True, "motivo": motivo}
        if (not valido) and antes is True:
            return {"avance": None, "valido": False, "motivo": motivo,
                    "regresion": self._regresion(TIPO_FICHERO, ruta_s, motivo)}
        # CRECIMIENTO VERIFICADO: el fichero ya contaba como valido, pero ahora
        # es MAS GRANDE que en cualquier momento anterior de esta corrida y
        # sigue siendo valido. Es una transicion observada, no una declaracion.
        # Contra el maximo historico a proposito: un churn A->B->A no crece.
        if valido and tam is not None and self.contar_crecimiento:
            tope = self._tam_max.get(ruta_s, 0)
            if tam >= tope + MIN_CRECIMIENTO_BYTES:
                self._tam_max[ruta_s] = tam
                ev = "%d -> %d bytes (+%d) y sigue valido: %s" % (
                    tope, tam, tam - tope, motivo)
                return {"avance": self.avanzar(TIPO_CRECIMIENTO, ruta_s, ev),
                        "valido": True, "motivo": motivo, "bytes": tam}
            # La linea base NO se mueve con un crecimiento que no llego al
            # minimo: si se moviera, diez apendices de 100 bytes (1 KB de
            # trabajo real) no contarian ni una vez, porque cada uno subiria
            # el liston que el siguiente tiene que batir.
        return {"avance": None, "valido": valido, "motivo": motivo}

    # -- Lectura -----------------------------------------------------------
    def pasos_sin_avance(self):
        """Pasos gastados desde el ultimo avance verificado (o desde el inicio)."""
        if not self.avances:
            return self.pasos
        return self.pasos - self.avances[-1]["paso"]

    def exploratorios_sin_avance(self):
        """Pasos de SOLO LECTURA gastados desde el ultimo avance verificado."""
        desde = self.avances[-1]["paso"] if self.avances else 0
        return sum(1 for g in self._gastos
                   if g["paso"] > desde and g.get("exploratorio"))

    def pasos_efectivos_sin_avance(self):
        """`pasos_sin_avance` descontando el credito de exploracion.

        SIEMPRE <= `pasos_sin_avance()`: esta resta solo puede retrasar un
        corte, nunca adelantarlo. Ver CREDITO_EXPLORACION.
        """
        return max(0, self.pasos_sin_avance()
                   - min(self.exploratorios_sin_avance(), self.credito_exploracion))

    def coste_sin_avance(self):
        """Tokens y segundos gastados desde el ultimo avance verificado."""
        if not self.avances:
            return {"tokens": self.tokens, "segundos": round(self.segundos, 3)}
        ult = self.avances[-1]
        return {
            "tokens": self.tokens - ult["tokens"],
            "segundos": round(self.segundos - ult["segundos"], 3),
        }

    def tasa(self):
        """Progreso verificado por unidad de coste. Es LA magnitud del modulo."""
        n = len(self.avances)
        minutos = self.segundos / 60.0
        return {
            "avances": n,
            "tokens": self.tokens,
            "segundos": round(self.segundos, 3),
            "pasos": self.pasos,
            "por_1k_tokens": round(n / (self.tokens / 1000.0), 4) if self.tokens else None,
            "por_minuto": round(n / minutos, 4) if minutos > 0 else None,
            "por_paso": round(n / float(self.pasos), 4) if self.pasos else None,
            # Los inversos son los que se leen en voz alta ("cada test verde me
            # cuesta 12k tokens"); None cuando aun no hay avance, nunca 0.
            "tokens_por_avance": round(self.tokens / float(n), 1) if (n and self.tokens) else None,
            "segundos_por_avance": round(self.segundos / float(n), 2) if n else None,
        }

    def curva(self):
        """Serie temporal acumulada: un punto por paso. Sirve para VER la forma."""
        por_paso = {}
        for av in self.avances:
            por_paso[av["paso"]] = por_paso.get(av["paso"], 0) + 1
        puntos = []
        # Un avance registrado antes del primer gasto (p.ej. un fichero que ya
        # estaba) vive en el paso 0 y necesita su propio punto.
        if por_paso.get(0):
            puntos.append({"paso": 0, "tokens": 0, "segundos": 0.0,
                           "avances": por_paso[0], "avances_acum": por_paso[0]})
        tok = 0
        seg = 0.0
        acum = por_paso.get(0, 0)
        for g in self._gastos:
            tok += g["tokens"]
            seg += g["segundos"]
            n = por_paso.get(g["paso"], 0)
            acum += n
            puntos.append({"paso": g["paso"], "tokens": tok, "segundos": round(seg, 3),
                           "avances": n, "avances_acum": acum})
        return puntos

    def _mediana_coste_por_avance(self):
        """Mediana de tokens gastados entre avances consecutivos de ESTA corrida."""
        if len(self.avances) < MIN_AVANCES_PARA_FACTOR:
            return None
        deltas = []
        previo = 0
        for av in self.avances:
            deltas.append(av["tokens"] - previo)
            previo = av["tokens"]
        return statistics.median(deltas)

    def _agotado(self):
        """Devuelve (eje, valor, limite) del primer tope superado, o None."""
        if self.tope_tokens is not None and self.tokens >= self.tope_tokens:
            return ("tokens", self.tokens, self.tope_tokens)
        if self.tope_segundos is not None and self.segundos >= self.tope_segundos:
            return ("segundos", round(self.segundos, 3), self.tope_segundos)
        if self.tope_pasos is not None and self.pasos >= self.tope_pasos:
            return ("pasos", self.pasos, self.tope_pasos)
        return None

    def veredicto(self):
        """{estado, motivo, evidencia, sugerencia}. No lanza y no corta: informa."""
        n = len(self.avances)
        sin = self.pasos_sin_avance()
        sin_ef = self.pasos_efectivos_sin_avance()
        coste = self.coste_sin_avance()
        ultimo = self.avances[-1]["detalle"] if n else ""

        base = {
            "corrida": self.nombre,
            "avances": n,
            "pasos": self.pasos,
            "pasos_sin_avance": sin,
            "pasos_efectivos_sin_avance": sin_ef,
            "exploratorios_sin_avance": self.exploratorios_sin_avance(),
            "tokens": self.tokens,
            "tokens_sin_avance": coste["tokens"],
            "segundos": round(self.segundos, 3),
            "ultimo_avance": ultimo,
        }

        ag = self._agotado()
        if ag is not None:
            eje, valor, limite = ag
            base.update({"eje": eje, "valor": valor, "limite": limite})
            return {
                "estado": "agotado",
                "motivo": "tope_%s" % eje,
                "evidencia": base,
                "sugerencia": _SUGERENCIAS["agotado"].format(
                    eje=eje, valor=valor, limite=limite, avances=n),
            }

        if n == 0 and sin_ef >= self.umbral_arranque:
            base["umbral"] = self.umbral_arranque
            return {
                "estado": "estancado",
                "motivo": "sin_arranque",
                "evidencia": base,
                "sugerencia": _SUGERENCIAS["sin_arranque"].format(
                    pasos=sin_ef, tokens=coste["tokens"]),
            }

        if n > 0 and sin_ef >= self.umbral_estancado:
            base["umbral"] = self.umbral_estancado
            return {
                "estado": "estancado",
                "motivo": "meseta",
                "evidencia": base,
                "sugerencia": _SUGERENCIAS["meseta"].format(
                    avances=n, pasos=sin_ef, tokens=coste["tokens"], ultimo=ultimo or "nada"),
            }

        mediana = self._mediana_coste_por_avance()
        if mediana is not None and mediana > 0 and coste["tokens"] > self.factor_meseta * mediana:
            base["mediana_tokens_por_avance"] = mediana
            base["factor"] = self.factor_meseta
            return {
                "estado": "estancado",
                "motivo": "meseta_de_coste",
                "evidencia": base,
                "sugerencia": _SUGERENCIAS["meseta_de_coste"].format(
                    tokens=coste["tokens"], factor=self.factor_meseta, mediana=mediana),
            }

        return {
            "estado": "avanza",
            "motivo": "avance_reciente" if n else "arrancando",
            "evidencia": base,
            "sugerencia": _SUGERENCIAS["avanza"].format(avances=n, pasos=sin),
        }

    def informe(self):
        """Dict plano y json-able para el envelope del turno."""
        por_tipo = {}
        for av in self.avances:
            por_tipo[av["tipo"]] = por_tipo.get(av["tipo"], 0) + 1
        return {
            "corrida": self.nombre,
            "coste": {"tokens": self.tokens, "segundos": round(self.segundos, 3),
                      "pasos": self.pasos},
            "topes": {"tokens": self.tope_tokens, "segundos": self.tope_segundos,
                      "pasos": self.tope_pasos},
            "umbrales": {
                "sin_arranque": self.umbral_arranque,
                "estancado": self.umbral_estancado,
                "factor_meseta": self.factor_meseta,
                "credito_exploracion": self.credito_exploracion,
                "contar_crecimiento": self.contar_crecimiento,
            },
            "avances": list(self.avances),
            "avances_por_tipo": por_tipo,
            "regresiones": list(self.regresiones),
            "tasa": self.tasa(),
            "curva": self.curva(),
            "veredicto": self.veredicto(),
        }


def _tamano_fichero(ruta, contenido=None):
    """Bytes del fichero (o del contenido en memoria). None si no se pudo medir.

    None y 0 NO son lo mismo: un fichero vacio mide 0 y uno ilegible no mide.
    Devolver 0 en el caso ilegible convertiria "no lo pude medir" en "encogio".
    """
    if contenido is not None:
        try:
            return len(str(contenido).encode("utf-8", "replace"))
        except Exception:
            return None
    try:
        return Path(ruta).stat().st_size
    except OSError:
        return None


def _validar_fichero(ruta, contenido=None):
    """(valido, motivo). Python y JSON se parsean; el resto solo existe/no vacio."""
    p = Path(ruta)
    texto = contenido
    if texto is None:
        if not p.exists():
            return (False, "no existe: %s" % ruta)
        if not p.is_file():
            return (False, "no es un fichero: %s" % ruta)
        try:
            texto = p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return (False, "ilegible (%s): %s" % (e.__class__.__name__, ruta))
    if not str(texto).strip():
        return (False, "vacio: %s" % ruta)
    suf = p.suffix.lower()
    if suf in (".py", ".pyi"):
        try:
            compile(texto, ruta, "exec")
        except SyntaxError as e:
            return (False, "no compila (linea %s): %s" % (getattr(e, "lineno", "?"), e.msg))
        return (True, "existe y compila: %s (%d bytes)" % (ruta, len(texto)))
    if suf == ".json":
        try:
            json.loads(texto)
        except ValueError as e:
            return (False, "JSON invalido: %s" % e)
        return (True, "existe y parsea como JSON: %s (%d bytes)" % (ruta, len(texto)))
    return (True, "existe y no esta vacio: %s (%d bytes)" % (ruta, len(texto)))


def _avances_hasta(prog, tope_tokens):
    """Cuantos avances de `prog` se habian logrado con <= tope_tokens gastados."""
    return sum(1 for av in prog.avances if av["tokens"] <= tope_tokens)


def comparar(a, b):
    """A/B honesto: dos corridas truncadas al MISMO coste en tokens.

    Comparar `a.avances` contra `b.avances` a secas premia a la corrida que mas
    gasto. Aqui se toma el coste comun (el minimo de los dos) y se cuentan solo
    los avances que cada una ya tenia con ese gasto. Es la unica comparacion que
    responde "cual configuracion del arnes rinde mas por token".
    """
    comun = min(a.tokens, b.tokens)
    na = _avances_hasta(a, comun)
    nb = _avances_hasta(b, comun)
    if comun <= 0:
        return {
            "coste_comun_tokens": 0,
            "nombre_a": a.nombre, "nombre_b": b.nombre,
            "avances_a": na, "avances_b": nb,
            "por_1k_a": None, "por_1k_b": None,
            "ganador": "empate", "margen": 0,
            "tokens_totales_a": a.tokens, "tokens_totales_b": b.tokens,
            "nota": "una de las dos corridas no gasto tokens: no hay iso-coste que comparar",
        }
    pa = round(na / (comun / 1000.0), 4)
    pb = round(nb / (comun / 1000.0), 4)
    if na > nb:
        ganador = "a"
    elif nb > na:
        ganador = "b"
    else:
        ganador = "empate"
    return {
        "coste_comun_tokens": comun,
        "nombre_a": a.nombre, "nombre_b": b.nombre,
        "avances_a": na, "avances_b": nb,
        "por_1k_a": pa, "por_1k_b": pb,
        "ganador": ganador,
        "margen": abs(na - nb),
        "tokens_totales_a": a.tokens, "tokens_totales_b": b.tokens,
        "nota": "truncadas a %d tokens (el minimo comun); los avances posteriores no cuentan" % comun,
    }
