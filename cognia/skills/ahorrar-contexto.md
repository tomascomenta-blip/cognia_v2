---
name: ahorrar-contexto
description: Comprime salidas largas (logs, listados, tracebacks) para evitar gastar toda la ventana de contexto, activándose cuando el usuario mencione que un log es larguisimo, que la salida ocupa demasiado, o que una traza es tan larga que necesita resumirse.
---

# ahorrar-contexto

Comprime salidas largas para conservar contexto.

## Como proceder
1. Identifica la salida larga que necesitas manejar (logs, listados, tracebacks).
2. Usa `cognia.compresion_salidas.comprimir_error` para comprimir la salida larga. Si no está disponible, usa `cognia.compresion_salidas.comprimir`.
3. Verifica que la salida comprimida sea manejable y contiene toda la información relevante.
4. Si la información es incompleta, usa `arbol` para obtener un mapa del código y `buscar` para localizar las partes relevantes.
5. Comprime y resumir la información relevante usando `resumir` y `apendar_archivo` si es necesario.
6. Continúa con tu tarea usando la salida comprimida.

## Reglas
- Usa `cognia.compresion_salidas.comprimir_error` o `cognia.compresion_salidas.comprimir` siempre que manejes salidas largas.
- Verifica que la salida comprimida sea manejable y contenga toda la información relevante.
- Si la información es incompleta, usa `arbol` y `buscar` para obtener un mapa del código y localizar las partes relevantes.
- Comprime y resumir la información relevante usando `resumir` y `apendar_archivo` si es necesario.
- No intentes manejar salidas largas sin comprimir, esto puede causar problemas de contexto.
