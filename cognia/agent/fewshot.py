"""
cognia/agent/fewshot.py
=======================
Banco de ejemplos ACCION concretos por herramienta (wire de la leccion +62pp).

Medido en el eje tool-calling (BFCL slice, 08_CP4_INFORME.md §2): para un 3B,
DOS ejemplos CONCRETOS de llamadas reales valen mas que cualquier instruccion
abstracta de formato — el baseline 24% estaba deflado porque el modelo tomaba
el placeholder "func(param=value)" LITERAL; 2 ejemplos reales colapsaron 142
fallos de formato a 5. El prompt del loop /hacer (TOOLS_DOC) era 100%
abstracto: una linea de doc por tool y reglas generales, cero ejemplos.

Este banco inyecta 1-2 ejemplos SOLO cuando hay una pista fuerte de la tool
inicial (intent.suggested_tool / entry point detectado): siempre-on inflaria
el prefill de CADA paso (~29 tok/s en el i3) para tareas que no lo necesitan.

Cero LLM, cero estado: dict plano + una funcion, mismo espiritu que stepwise.
"""

# Ejemplos con el formato EXACTO que espera cada tool (separador |, rutas
# relativas al workspace, contenido multi-linea permitido en escribir_archivo).
# 1-2 por tool; cortos a proposito (cada token extra es prefill de cada paso).
_EXAMPLES = {
    "escribir_archivo": [
        "ACCION: escribir_archivo notas/resumen.md | # Resumen\nHallazgos:\n- punto 1",
    ],
    "apendar_archivo": [
        "ACCION: apendar_archivo log.txt | nueva linea al final",
    ],
    "leer_archivo": [
        "ACCION: leer_archivo cognia/config.py",
    ],
    "generar_codigo": [
        "ACCION: generar_codigo utils.py | escribi una funcion sumar(a, b) que devuelva a+b",
    ],
    "tests": [
        "ACCION: tests tests/test_utils.py",
    ],
    "ejecutar": [
        "ACCION: ejecutar git status --short",
    ],
    "buscar": [
        "ACCION: buscar TODO",
    ],
    "crear_herramienta": [
        "ACCION: crear_herramienta contar_vocales | cuenta las vocales de un texto | hola mundo | 4",
    ],
}


def fewshot_for(tool_name: str, max_examples: int = 2) -> str:
    """Bloque 'EJEMPLOS (formato exacto):' para la tool pedida, o '' si no
    hay ejemplos para ella. El caller lo agrega a TOOLS_DOC cuando la pista
    inicial es fuerte (hint de intent o entry point detectado)."""
    ex = _EXAMPLES.get((tool_name or "").strip().lower())
    if not ex:
        return ""
    lines = ex[:max_examples]
    return "EJEMPLOS (formato exacto):\n" + "\n".join(lines)
