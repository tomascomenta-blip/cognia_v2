---
name: depurar
description: Depura un error o bug de forma sistematica hasta la causa raiz. Usar cuando el usuario reporte un fallo, excepcion, comportamiento raro o pida "arreglar" algo que no anda.
---

# depurar

Encontra la CAUSA RAIZ, no tapes el sintoma.

## Como proceder
1. Reproduci el fallo: corre el comando/test que falla con la herramienta `ejecutar` o `tests`
   y lee el error completo (stack trace incluido).
2. Localiza: usa `buscar` para encontrar la funcion/linea del trace; `leer_archivo` para verla.
3. Forma UNA hipotesis concreta de por que pasa. Verificala leyendo el codigo o con un
   experimento minimo (`ejecutar`/`calcular`), no asumas.
4. Si la hipotesis falla, descartala y forma otra. Anota lo que ya descartaste con `anotar`.
5. Cuando halles la causa, aplica el fix mas chico que la resuelve con `escribir_archivo`.
6. Verifica: volve a correr lo que fallaba y confirma que ahora pasa.

## Reglas
- Distingui causa de sintoma: si el fix no explica POR QUE fallaba, no es la causa.
- Un solo cambio por vez; reproduci entre cambios.
- No declares resuelto sin volver a correr la reproduccion.
