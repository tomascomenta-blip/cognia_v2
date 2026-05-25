# Cognia Wiki — instrucciones para Claude Code

## Propósito

Esta wiki relaciona conceptos, entidades y decisiones de diseño de Cognia. Es la fuente de contexto de mediano plazo — entre el código fuente (verdad táctica) y la memoria `.claude/` (verdad de sesión).

## Cómo navegar

1. Leer `wiki/index.md` primero — lista todas las páginas y su propósito en una línea
2. Para un concepto específico: ir directo a `wiki/concepts/<nombre>.md`
3. Para un flujo completo: `wiki/synthesis/`
4. Para comparar dos enfoques: `wiki/comparisons/`
5. Para entender un archivo del repo: `wiki/sources/`

## Cómo actualizar

Al terminar una tarea relevante:
- Si cambia un concepto o restricción → editar la página de concepto
- Si cambia un flujo → editar la página de synthesis
- Si se resuelve deuda activa → actualizar la página que menciona esa deuda
- Agregar entrada al log: `wiki/log.md` (formato: `YYYY-MM-DD | acción | páginas | notas`)

## Reglas de escritura

- Sin emojis, sin box-drawing — ASCII puro
- Sin comentarios que expliquen QUÉ — solo WHY si no es obvio
- Máximo 2-3 líneas de contexto por entrada nueva
- Wikilinks: `[[entities/relay]]` no `[relay](entities/relay.md)`

## Para Obsidian

Abrir la carpeta `wiki/` como vault. Las carpetas son los grupos de nodos.
Activar "Wikilinks" en configuración de Obsidian para que los links funcionen.
