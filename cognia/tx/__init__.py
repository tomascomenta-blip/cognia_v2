# -*- coding: utf-8 -*-
"""TX/LIBRO -- subsistema de horizonte largo (OPT-IN: COGNIA_TX=1).

Con COGNIA_TX apagado, NADA de este paquete corre: el interceptor ni siquiera
lo importa. Esa es la condicion que puso el dueno (el bucle del agente lo usa a
diario) y esta cristalizada en tests/test_tx_p0.py.

Estado hoy (P0, prerrequisitos de la ESPEC seccion 14.1):
  - errores.py .... LA excepcion tipada `LibroCaido` (P0-2). ENTREGADO.
  - libro.py ...... el almacen append-only. TODAVIA NO EXISTE (bloque M1).

EL CONTRATO DEL HUECO (lo que tiene que cumplir `libro.py` para engancharse
solo, sin tocar el interceptor):

    def registrar_tool(evento: dict, ctx: dict = None) -> int:
        '''Apendea UN evento y devuelve su `n`. Si no puede dejar constancia
        (disco, permisos, cadena prev rota) lanza LibroCaido: NUNCA devuelve
        en silencio ni traga la excepcion.'''

`evento` llega ya armado por `harness/interceptor.envelope()`, con la
provenance escrita POR LA MAQUINA (el modelo no rellena un solo campo) y con
la regla dura de P0-1: `origen='medido'` solo si hubo un exit code entero de
verdad; con exit None baja a 'derivado' y `prov.tipo` deja de ser 'ejecutada'.
`libro.append` completa lo que falta del esquema de la ESPEC 3.2 (n, ts,
ciclo, id, banda, refs, sha, prev).
"""

from cognia.tx.errores import LibroCaido, TxError   # noqa: F401

__all__ = ["LibroCaido", "TxError"]
