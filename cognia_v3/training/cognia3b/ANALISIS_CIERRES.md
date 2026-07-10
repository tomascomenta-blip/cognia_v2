# Diagnóstico CIERRES (accion v3) — análisis honesto

Instrumento: `cognia_v3/eval/diag_cierres.py` sobre `g6_cierres.jsonl` (50 ítems
congelados, sha256 `59d53ec8…`), **con el parche determinista E8 DESACTIVADO**
(monkeypatch de `task_pide_ejecucion`/`salida_de_ejecucion`; assert que verifica
que tomó). Agent loop real, greedy, max_steps=8. Corrida 2026-07-10.

## Números crudos

| dominio | pasa | vacío | parcial | incorrecto |
|---|---|---|---|---|
| cierre_output (22) | 13 | 3 | 0 | 6 |
| multi_tool (14) | **12** | 1 | 0 | 1 |
| error_accionable (14) | **2** | 10 | 2 | 0 |
| **total (50)** | **27 (54%)** | 14 | 2 | 7 |

Veredicto automático por bandas pre-registradas: FORMATO (vacío+parcial) =
16/23 de los fallos = 70% → "apto para experto accion v3". **Pero el desglose
fino lo matiza y hay que leerlo con cuidado.**

## Desglose fino (lo que el veredicto automático NO distingue)

### Los 7 "incorrecto" son CAPACIDAD, no formato — bien excluidos
6 de 7 EJECUTARON la tool pero dieron el valor mal: conteos de líneas
(`"20 líneas"`, `"50 lines"`, `"40 notas"`), sumas multi-archivo (`"total 400"`
con oráculo 64), números de 8 dígitos mal copiados. 1 fue adivinanza sin
ejecutar (`2**31-4051 = 2147483647`, no restó). Contar líneas y copiar/restar
números largos es **capacidad del 3B**, no un hábito que un adapter de formato
arregle. El clasificador los mandó a CAPACIDAD correctamente.

### El gap REAL y ENTRENABLE está en error_accionable (2/14)
Cuando una tool FALLA o el objetivo exige leer/ejecutar algo que da error, el
modelo **se rinde con un cierre vacío** en vez de reportar la causa accionable:
- `"No tengo esa información."` (el archivo existía en el setup)
- `"Listo, tarea completada."` / `"Listo, proceso completado."` (nada hecho)
- `"No puedo ejecutar comandos de sistema."` (negativa infundada)
- `"¿Copiaste el archivo con éxito?"` (devuelve una pregunta)

Esto es **hábito de FORMATO puro** y —clave— es el caso que el **parche E8 NO
cubre**: E8 solo anexa `Salida de la ejecución: X` cuando hubo un
`RESULTADO ejecutar` EXITOSO. Sin salida exitosa (error/archivo faltante), no
hay nada que anexar → el modelo cierra vacío. A diferencia de razonamiento y
código (capacidad, 3 negativas del programa), **este SÍ es gap de formato**.

### Ruido del instrumento a descontar
- **Sesgo de pedido explícito**: todos los prompts de g6 piden reportar
  explícitamente ("decime qué imprime"). El hábito "listo vacío" original
  (batería E) aparecía SIN pedirlo. g6 mide el caso más fácil → si aun así
  falla error_accionable 12/14, el gap real es al menos tan grande.
- **2 fallos son del LOOP, no del modelo**: `"(interrumpida por estancamiento)"`
  (G6-041/042). Un adapter NO arregla el estancamiento — eso es código del loop.
- Algún ítem parece mal clasificado (`"broken_config.json no es un archivo JSON
  válido"` es un error accionable razonable que cayó en vacío).

## Gap entrenable neto (estimación honesta)

De los 23 fallos: descontá 7 capacidad + 2 loop-estancamiento ≈ **~14 fallos de
formato/hábito genuino**, concentrados en manejo-de-error y algunos cierre-vacío.
Es un gap real y del tipo correcto, pero MÁS CHICO que el "16/23" del veredicto
automático, y CONCENTRADO en un sub-dominio (errores accionables + cierre).

## Decisión (método del programa)

1. **Antes de GPU, agotar la palanca de inferencia** (regla que cerró español,
   LCD, estructura): el parche E8 cubre el caso exitoso; el gap está en el caso
   de ERROR. Un **parche determinista análogo** — cuando la última tool falló o
   no hubo salida exitosa y el loop cierra, anexar la causa del error de forma
   accionable — podría cerrar buena parte del gap con CERO GPU. Hay que medirlo:
   re-correr diag_cierres CON ese parche y ver cuánto sube error_accionable.
2. **Si queda gap residual de formato tras el parche** → entrenar accion v3
   sobre ese residuo (cierre-con-salida + error-accionable), con dataset
   verificado por ejecución que NO incluya conteo/cálculo (capacidad), gate
   congelado y McNemar en deploy.
3. El estancamiento del loop (G6-041/042) es un bug de código aparte.

Este es el mismo patrón que dio valor 3 veces: medir el gap por clases, agotar
inferencia, y entrenar SOLO el residuo de formato — o cerrar con la negativa.
