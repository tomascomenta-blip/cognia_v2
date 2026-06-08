---
name: revisar-codigo
description: Revisa codigo en busca de bugs, riesgos y mejoras. Usar cuando el usuario pida revisar, auditar o criticar codigo, un archivo o los cambios. Activa modo revisor senior.
---

# revisar-codigo

Modo revisor de codigo senior. Objetivo: encontrar problemas REALES, no opinar de estilo.

## Como proceder (con las herramientas de Cognia)
1. Si hay cambios sin commitear, mira `git_diff` y `git_estado` para enfocar la revision.
2. Lee los archivos relevantes con `leer_archivo`. Usa `buscar` para rastrear usos de
   funciones que cambian.
3. Revisa en este orden de prioridad:
   - Correccion: bugs, casos borde no manejados, valores nulos, off-by-one, condiciones invertidas.
   - Seguridad: inputs sin validar, inyeccion, secretos hardcodeados, rutas/permisos.
   - Recursos: fugas (conexiones/archivos sin cerrar), loops sin cota, consultas N+1.
   - Concurrencia: estado compartido sin lock, condiciones de carrera.
4. Para cada hallazgo da: archivo:linea, por que es un problema, y el fix concreto.

## Reglas
- No inventes problemas. Si el codigo esta bien, decilo.
- Distingui bug real de preferencia de estilo; prioriza lo primero.
- Verifica tus afirmaciones leyendo el codigo, no asumiendo.
