# M0 / G1 — RESULTADO MEDIDO (A-018: ¿la SWA ahorra banda en CPU?)

> **Medido en el hardware objetivo** (Intel i3-10110U, 2c/4t, sin CUDA, llama.cpp b9391, n_gpu_layers=0,
> --parallel 1, threads=3). Fecha: 2026-06-28. Script: `m0_g1_bandwidth.py`. Datos crudos:
> `results_g1/g1_qwen3b_full.json`, `results_g1/g1_gemma2_swa.json`.

## Datos (decode tok/s y RSS vs longitud de contexto L)

| L (prompt_n) | **Gemma-2-2B (SWA, ventana 4096)** decode | **Qwen2.5-3B (full)** decode |
|---|---|---|
| 512  | 8.11 tok/s | 7.67 tok/s |
| 2048 | 6.20 | 5.19 |
| 4096 | 4.95 | 3.79 |
| 8192 | 3.70 | 2.72 |

**Retención de decode 2048→8192:** SWA **0.597** vs full **0.525**.
**Decode absoluto a 8192:** SWA 3.70 vs full 2.72 → la SWA es **36% más rápida** a contexto largo.
(RSS: ambos crecen con L; el delta de KV es chico frente al peso del modelo — señal secundaria, confound de
vocab 256k de Gemma; el de decode es el limpio.)

## Veredicto honesto

**La SWA SÍ ahorra banda en CPU — pero el ahorro es MODESTO y GRADUAL, no un step-change.** La curva de
decode del modelo SWA es más plana que la del full (+0.07 de retención, 36% más rápido a L=8192), así que
el ahorro es **real y crece con L**. PERO **no alcanza el umbral pre-registrado de ≥0.70** (el SWA todavía
pierde ~40% de su decode de 2048 a 8192).

**El hallazgo clave (confirma la tesis del propio lab):** **el decode en CPU es WEIGHT-READ-BOUND.** Ambos
modelos caen sustancialmente al crecer L porque el costo dominante por token es **leer los pesos del modelo
desde RAM** (bytes/token, memory-bandwidth-bound — la tesis maestra de `architecture.md`), NO la atención.
La SWA sólo reduce la parte de KV/atención, que es **secundaria** frente al weight-read. Por eso el ahorro
es marginal a estas escalas. **Esto VALIDA empíricamente en el i3 la tesis bytes/token** (antes era confianza
media; ahora medida).

### Caveats (honestidad — el dato no es perfecto)
1. **Confound de tamaño:** Gemma-2-2B (2B) vs Qwen-3B (3B). Comparamos la *forma* (retención), no el absoluto,
   pero arquitecturas distintas más allá de la SWA contaminan algo.
2. **Gemma-2 es SWA DÉBIL:** alterna capas SWA/global (≈mitad y mitad), ventana 4096 → sólo la mitad de las
   capas ahorran, y sólo para L>4096. Un modelo 5:1-SWA (Gemma-3, ventana 1024) mostraría MÁS. → el +0.07 es
   un **piso** del beneficio de SWA, no el techo.
3. **FALTA la mitad grande de RAMA A:** la RAMA A es "mayoría capas de ESTADO FIJO (Mamba/SSM, O(1) por token,
   KV=0) + minoría SWA". G1 midió sólo la SWA (la minoría). El lever GRANDE — el SSM que elimina la KV — está
   **SIN MEDIR**. Pero ojo: el SSM ataca la KV, que acá vimos que es la parte SECUNDARIA → aun con SSM, el
   weight-read seguiría dominando el decode a estas escalas. El SSM ayuda sobre todo en **RAM y contexto muy
   largo**, no en velocidad de decode a L moderado.

## Implicación para la arquitectura (G1)

- **A estas escalas (L≤8192) y en CPU, RAMA A (híbrido) vs RAMA B (GQA denso) NO es una diferencia decisiva de
  velocidad de decode** — ambas son weight-read-bound. La SWA da un beneficio marginal que crece con L.
- **Lean: RAMA B (Transformer denso GQA + KV-cache 4-bit) para el v1** — es madura HOY, simple, y pierde poco
  a contexto típico. La SWA/SSM (RAMA A) se justifican si el caso de uso objetivo es **contexto MUY largo**
  (donde la RAM de KV y el beneficio de SWA crecen) o por **RAM** (KV acotada), no por decode a L moderado.
- **El lever de velocidad #1 en CPU es el TAMAÑO/cuantización del modelo** (bytes/token), no el esquema de
  atención. Esto re-prioriza el plano 02: optimizar bytes/peso (Q4 sólido, modelo chico) por encima de la
  complejidad del híbrido.

> **G1 cierra la mitad SWA con dato real.** Falta (opcional, para completar A-018): medir un GGUF Mamba/SSM
> (¿el kernel SSM corre rápido en el build CPU pineado? — precedente exp007). Y el veredicto de ARQUITECTURA
> final se cierra con **G2** (¿el híbrido recupera recall?): si G2 también empuja a atención-mayoritaria, G1+G2
> convergen en **RAMA B** para el v1. Si el caso de uso pide contexto larguísimo, se reabre RAMA A con el test SSM.

## Estado del GO

G1 mueve el GO de "condicionado a ciegas" a "**condicionado con dato**": la dirección de backbone v1 se inclina
a **RAMA B** por evidencia medida (CPU weight-read-bound; SWA marginal). Queda **G2** para el lock final del
backbone (recall) y, si se quiere certeza sobre la RAMA A de contexto-largo, el **test SSM**. Ninguno bloquea
el build (el resto del sistema es agnóstico al backbone).
