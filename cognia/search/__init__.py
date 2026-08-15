# -*- coding: utf-8 -*-
"""Harness de búsqueda de Cognia.

Nace el 2026-08-14 de una investigación del harness de Perplexity y de leer
el propio código: el pipeline de investigación de la casa estaba dimensionado
para una ventana de 8k (3 páginas × 2000 chars) mientras el cerebro servía
1.048.576 tokens, y el fan-out devolvía `None` para un fallo — indistinguible
de "no encontré nada".

Las tres piezas de aquí atacan exactamente eso:
  fanout    — el fallo VIAJA en el resultado (envelope), nunca se pierde
  contexto  — el presupuesto se declara en SEGUNDOS de pared, no en tokens
  evidencia — una cita que no está literal en la página no es una cita
"""
