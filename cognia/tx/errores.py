# -*- coding: utf-8 -*-
"""Excepciones tipadas de TX. SIN dependencias: se importa desde el camino
caliente de `run_tool` en la rama de excepcion.

POR QUE UNA EXCEPCION Y NO UN BOOL (P0-2, ESPEC 14.1):
`harness/interceptor.py` tiene 11 `except Exception: pass` y su contrato dice
"un fallo de cualquier capa degrada a no hacer nada". Para checkpoints y hooks
eso es correcto. Para la MEMORIA no lo es: si el LIBRO no escribe, el ciclo
siguiente decide sobre un pasado incompleto y nadie se entera -- disco lleno =
memoria apagada en silencio, que es el fallo tipico de este sistema (el vacio
silencioso, no la excepcion). `LibroCaido` es la unica excepcion del arnes que
NO se traga: sube por `interceptor.despues` -> `run_tool` -> el bucle, y PARA.
"""


class TxError(Exception):
    """Raiz de los fallos del subsistema TX. Nada la lanza directamente."""


class LibroCaido(TxError):
    """No se pudo dejar constancia en el LIBRO. El ciclo NO puede continuar.

    `motivo` es lo que se le ensena al humano; `causa` es la excepcion original
    (disco lleno, permiso, cadena prev rota...). Se conserva porque "no pude
    escribir" sin el errno de abajo cuesta el mismo dia de diagnostico que el
    silencio que esta clase viene a eliminar.
    """

    def __init__(self, motivo: str, causa: BaseException = None) -> None:
        self.motivo = str(motivo or "")
        self.causa = causa
        detalle = ""
        if causa is not None:
            detalle = " (%s: %s)" % (type(causa).__name__, causa)
        super().__init__(
            "LIBRO CAIDO: " + self.motivo + detalle
            + ". El ciclo se para: continuar significaria decidir sobre un "
              "pasado incompleto sin saberlo.")


class EventoInvalido(TxError):
    """El evento no cumple el esquema de la ESPEC 3.2 y NO se escribio.

    POR QUE SE SEPARA DE `LibroCaido`: son dos averias con dos duenos y dos
    reacciones. `LibroCaido` es del MUNDO (disco, permisos) y para el ciclo;
    `EventoInvalido` es de QUIEN LLAMA -- casi siempre el modelo intentando
    meter una `afirmacion` con `prov.tipo='dicha'` en banda P, o un `conf` por
    encima del techo 0,30 -- y su destino es volver al modelo como error de
    tool (invariante I3), no parar la tarea. Tratarlas igual convertiria cada
    intento de alucinacion en una parada del agente.
    """
