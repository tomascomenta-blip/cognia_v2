---
name: palabras-txt-tiene-palabra-por
description: palabras.txt tiene una palabra por línea. Hacé estas cuatro cosas: (1) escribí en largas.txt las palabras de MÁS de 5 le
auto_generated: true
verified: oraculo duro via 'generar_codigo': RESULTADO generar_codigo largas.txt: OK (mejor de 1 candidatos unicos, rank=test (args: largas.txt | def escribir_l
version: 0.1.0
---

## Cuando usar
Tareas como: palabras.txt tiene una palabra por línea. Hacé estas cuatro cosas: (1) escribí en largas.txt las palabras de MÁS de 5 letras, ordenadas alfabéticamente, una por línea; (2) escribí en conteo.txt cuánta

## Procedimiento verificado
1. ACCION: leer_archivo palabras.txt
2. ACCION: generar_codigo largas.txt | def escribir_largas(palabras):     palabras_largas = [p for p in palabras if len(p) > 5]     palabras_larga
3. ACCION: ejecutar python largas.py
4. ACCION: escribir_archivo largas.py | def escribir_largas(palabras):     palabras_largas = [p for p in palabras if len(p) > 5]     palabras_largas
5. ACCION: editar_archivo largas.py | <<<<<<< SEARCH def escribir_largas(palabras):     palabras_largas = [p for p in palabras if len(p) > 5]
6. ACCION: escribir_archivo largas.py | def escribir_largas(palabras):     palabras_largas = [p for p in palabras if len(p) > 5]     palabras_largas
7. ACCION: editar_archivo largas.py | <<<<<<< SEARCH def escribir_largas(palabras):     palabras_largas = [p for p in palabras if len(p) > 5]
8. ACCION: ejecutar python largas.py < palabras.txt
9. ACCION: ejecutar python largas.py < palabras.txt
10. ACCION: escribir_archivo largas.py | def escribir_largas(palabras):     palabras_largas = [p for p in palabras if len(p) > 5]     palabras_largas

## Verificacion
Cerrar SIEMPRE corriendo los tests (tool `tests`) y confirmar 'N passed'.
