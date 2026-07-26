# PRE-REGISTRO — Tasa de falsos positivos del contrato brutal

**Escrito el 2026-07-25 a las 22:4x, ANTES de correr el held-out sobre un solo
producto del pool.** Existe para que el umbral no se elija despues de ver el
resultado. Es la contramedida que META_MODELO_GRANDE.md declaro obligatoria
("suite held-out por tarea desde el dia uno") y que la sesion anterior no
construyo.

## Qué se mide

La tasa de falsos positivos del contrato original del banco brutal
(`scripts/b1_tareas_brutales.json`): la fraccion de productos que APRUEBAN el
contrato original pero FALLAN una suite held-out de consecuencias logicas del
mismo enunciado (`scripts/b1_contratos_heldout.json`) que ningun modelo vio y
que el contrato original no menciona.

Ese numero es el techo de todo lo demas: con FP > 0 hay un limite que ningun
presupuesto de computo cruza (arXiv:2411.17501). El pass@6 = 100% del 20B y el
"iguala al frontier" de la sesion anterior valen exactamente lo que valga este
numero.

## Método

1. **Validacion del held-out primero** (caza de falsos NEGATIVOS del held-out,
   el metodo que ya cazo seis): la suite corre contra los productos de
   `frontier_brutal/` que aprueban el contrato original. Si un producto que el
   frontier resolvio bien falla el held-out, se arregla el CONTRATO held-out,
   no el producto, y se re-valida. Solo despues se toca el pool.
2. **Re-juzgado del pool**: los 48 productos en disco
   (`b1_oraculo/{hoja_calculo,carrito_stock,kanban,buscaminas}__{pensar,laguna}__r1..r6`)
   se juzgan con el contrato ORIGINAL (misma corrida, mismo juez — elimina
   dudas de mapeo muestra↔directorio) y con el HELD-OUT. Cero generacion,
   cero GPU: los bytes son los que ya estan en disco.
3. **FP** = #(aprueba original ∧ falla held-out) / #(aprueba original),
   agregado y por modelo. Errores de harness (pagina que no carga en la corrida
   held-out pero si en la original) se cuentan aparte, no como FP.

## Umbral — decidido AHORA

| FP | lectura |
|---|---|
| **≤ 10%** | los numeros de la sesion anterior se sostienen |
| **10–30%** | son TECHOS, no medidas; se reportan como cota superior |
| **> 30%** | el juez es el que aprueba, no el modelo; no se construye nada encima hasta rehacer los contratos |

Regla adicional pre-registrada: si el FP difiere fuerte por modelo (p.ej.
laguna hackea y gpt-oss no), la lectura se hace por modelo con el mismo
umbral; el agregado no promedia un juez roto con uno sano.

## Resultado (2026-07-25 ~23:20; nada de lo de arriba se tocó después de esto)

| modelo | aprueban original | FP | tasa |
|---|---|---|---|
| gpt-oss-20b (pensar) | 18/24 | **0** | **0.0%** |
| Laguna XS 2.1 (laguna) | 12/24 | **3** | **25.0%** |
| agregado | 30/48 | 3 | 10.0% |

Aplica la regla por-modelo (la diferencia es fuerte):

- **gpt-oss-20b: los números de la sesión anterior SE SOSTIENEN.** pass@1 75%
  y pass@6 100% en el banco brutal quedan como medidas, no como techos. El
  "iguala al frontier con 6 muestras verificadas" sobrevive al held-out.
- **Laguna: sus números son TECHOS.** 3 de sus 12 aprobados pasan el examen y
  no la materia. Consistente con SpecBench: hackea más el modelo con mayor
  brecha dificultad-capacidad.

Los 3 FP se inspeccionaron a mano y son defectos REALES de producto, no del
held-out: dos buscaminas cuya cascada solo funciona desde la región que el
contrato original ejercitó (desde la celda 20 abren 1 celda en vez de 8), y un
kanban donde `menos` sobre una tarjeta en `todo` la mueve (el enunciado lo
prohíbe expresamente y el original nunca lo pulsó).

Corrección durante la validación (fase 1 + revisor adversarial, ANTES de tocar
el pool): el held-out tenía 3 falsos negativos propios — una adyacencia mal
calculada por mí en buscaminas (celda 16: "2" cuando es "1"; lo cazó el
producto frontier), lecturas de celdas-fórmula con el foco puesto, y un fill()
de Playwright que corrompe al pisar una fórmula. El método de validar el
verificador contra una referencia conocida antes de usarlo volvió a pagar.

## Qué NO decide esto

- No mide falsos negativos del contrato original (productos buenos reprobados).
- El held-out tambien es un contrato escrito por la misma mano; su validacion
  contra frontier acota, no elimina, sus propios sesgos.
- Un solo check `critico: false` (autorreferencia en hoja_calculo) queda fuera
  del veredicto: se registra como dato, no decide FP.
