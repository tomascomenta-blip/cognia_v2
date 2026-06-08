---
name: commit-git
description: Prepara un commit de git con un mensaje claro. Usar cuando el usuario pida commitear, guardar cambios en git o redactar un mensaje de commit.
---

# commit-git

Un commit chico y enfocado con un mensaje que explica el POR QUE.

## Como proceder
1. Mira que cambio: `git_estado` y `git_diff` para ver el alcance real.
2. Si hay cambios no relacionados mezclados, avisalo (idealmente commits separados).
3. Redacta el mensaje:
   - Primera linea: `tipo(area): resumen imperativo` (<=72 chars). tipo = feat/fix/docs/test/refactor/chore.
   - Cuerpo: que cambio y POR QUE (no como; el diff ya dice como). Como se verifico.
4. Ejecuta el commit con `ejecutar`: `git add <archivos> && git commit -m "..."`.

## Reglas
- Nunca commitees secretos (.env, tokens, claves) ni archivos generados/temporales.
- El mensaje describe la intencion, no un volcado del diff.
- No uses `git add .` a ciegas si hay cosas que no deberian entrar.
