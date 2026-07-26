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

## Qué NO decide esto

- No mide falsos negativos del contrato original (productos buenos reprobados).
- El held-out tambien es un contrato escrito por la misma mano; su validacion
  contra frontier acota, no elimina, sus propios sesgos.
- Un solo check `critico: false` (autorreferencia en hoja_calculo) queda fuera
  del veredicto: se registra como dato, no decide FP.
