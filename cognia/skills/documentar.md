---
name: documentar
description: Explica o documenta codigo de forma clara. Usar cuando el usuario pida explicar, entender, documentar o comentar un archivo, funcion o modulo.
---

# documentar

Explica para que ALGUIEN NUEVO entienda, sin relleno.

## Como proceder
1. Lee el codigo con `leer_archivo`. Si referencia otras piezas, seguilas con `buscar`.
2. Explica en este orden:
   - Que hace (una frase) y por que existe.
   - Como se usa: entradas, salidas, un ejemplo concreto.
   - Decisiones no obvias o trampas (por que asi y no de otra forma).
3. Si te piden documentar EN el codigo, agrega docstrings/comentarios con `escribir_archivo`,
   igualando la densidad y el estilo de comentarios del archivo.

## Reglas
- Preciso sobre exhaustivo: lo que importa, no cada linea.
- No inventes comportamiento; si algo no esta claro en el codigo, decilo.
