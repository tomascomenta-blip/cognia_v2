"""
patrones.py — la memoria de "lo ya creado bonito y funcional".

Idea del dueno (2026-07-20): que Cognia REUSE tecnicas de paginas de ejemplo
que ya funcionan — no copiarlas enteras, sino guiarse de ellas. Los fragmentos
de patrones_web/ salen de la pagina de referencia que paso todos los chequeos
del dia (sonda + critico), y cada uno lleva su POR QUE en el comentario.
La regla "se ADAPTAN, no se copian" va en el prompt del generador, no aqui.

Escrito por Cognia via G4; el centinela anadio este docstring en revision.
"""

from pathlib import Path
import logging

DIR_PATRONES = Path(__file__).parent / "patrones_web"
_MAPA = [
    ("tiles_kpi.html", ("dashboard", "panel", "kpi", "resumen", "metricas", "métricas", "inversion", "inversión")),
    ("grafico_svg.html", ("grafico", "gráfico", "chart", "graph", "grafica", "linea", "sparkline")),
    ("tabla_estados.html", ("tabla", "table", "lista", "cotizacion", "cotización", "precios", "posiciones", "filas"))
]

def elegir_patrones(idea: str, max_n: int = 2) -> list:
    """
    Elige patrones HTML basados en la idea proporcionada.
    Recorre los patrones en orden y devuelve los contenidos de los archivos que coinciden.
    """
    try:
        idea = idea.lower()
        resultados = []
        for fichero, claves in _MAPA:
            if any(clave in idea for clave in claves):
                path = DIR_PATRONES / fichero
                if path.exists():
                    with path.open('r', encoding='utf-8') as file:
                        contenido = file.read()
                        resultados.append((fichero.rsplit('.', 1)[0], contenido))
                        if len(resultados) == max_n:
                            return resultados
                else:
                    logging.warning(f"Archivo inexistente: {path}")
        return resultados
    except Exception as e:
        logging.error(f"Error al elegir patrones: {e}")
        return []