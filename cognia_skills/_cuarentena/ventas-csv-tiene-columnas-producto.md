---
name: ventas-csv-tiene-columnas-producto
description: ventas.csv tiene columnas producto,precio. Escribí en caros.txt los nombres de los productos que cuestan MÁS de 100, uno
auto_generated: true
verified: oraculo duro via 'generar_codigo': RESULTADO generar_codigo caros.txt: OK (mejor de 1 candidatos unicos, rank=tests (args: caros.txt | def escribir_ca
version: 0.1.0
---

## Cuando usar
Tareas como: ventas.csv tiene columnas producto,precio. Escribí en caros.txt los nombres de los productos que cuestan MÁS de 100, uno por línea, y ninguno más

## Procedimiento verificado
1. ACCION: leer_archivo ventas.csv
2. ACCION: generar_codigo caros.txt | def escribir_caros(productos):     with open('caros.txt', 'w') as f:         for producto in productos:
3. ACCION: ejecutar python caros.py
4. ACCION: apendar_archivo caros.txt |
5. ACCION: escribir_archivo caros.py | productos_caros = [p for p in productos if p['precio'] > 100] with open('caros.txt', 'w') as f:     for produ
6. ACCION: ejecutar python caros.py
7. ACCION: leer_archivo ventas.csv
8. ACCION: escribir_archivo productos.py | productos = [{'producto': 'teclado', 'precio': 120}, {'producto': 'mouse', 'precio': 35}, {'producto': 'm
9. ACCION: escribir_archivo caros.py | productos = [{'producto': 'teclado', 'precio': 120}, {'producto': 'mouse', 'precio': 35}, {'producto': 'monit

## Verificacion
Cerrar SIEMPRE corriendo los tests (tool `tests`) y confirmar 'N passed'.
