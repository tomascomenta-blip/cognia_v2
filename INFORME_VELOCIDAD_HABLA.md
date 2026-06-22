# Informe — Cómo hacer que Cognia X hable a velocidad alta (sesión 2026-06-21/22)

> Respuesta directa, medida sobre TU hardware real (i3-10110U, 2 núcleos, sin GPU,
> llama-server b9391, Qwen2.5-Coder-3B Q4_K_M). Todo lo que digo "medido" está en
> `cognia_x/experiments/exp021_speculative_decode/` y registrado en el ledger (cycle34).

## Tus dos preguntas, respondidas

**1) "¿Hay parámetros entrenados modificables que funcionen con el sistema actual?"**
Sí, en tres niveles, todos compatibles con tu GGUF + llama-server actual:
- **n-gram** (`--spec-type ngram-mod`): 0 parámetros, 0 entrenamiento, **bit-idéntico** a la
  salida normal. Acelera texto repetitivo/código/RAG (hasta **1.45× gratis y sin perder
  calidad**). En habla natural casi no ayuda.
- **Cabezas MTP / EAGLE-3** (`--spec-type draft-mtp|draft-eagle3`): **estos SON los "parámetros
  entrenados modificables"** — matrices pequeñas que se montan sobre tu 3B *congelado*,
  predicen varios tokens de golpe y la base verifica (sin perder exactitud). El binario YA las
  carga. Proyección calibrada: **17.7–24.8 tok/s (2.1–3.0×)**. Falta entrenarlas/convertirlas
  para Qwen2.5-Coder-3B (se puede en el pipeline de Kaggle que ya tienes).
- **LoRA episódico (ELC)** que ya existe en `node/local_adapter.py`: personaliza *qué* dice
  (no acelera). Complementa: ELC = estilo/persona; cabezas MTP/EAGLE = velocidad.

**2) "El nuevo método de Gemma para generar texto + un híbrido de lo mejor de ambos mundos."**
El nuevo método es **DiffusionGemma**: genera *bloques enteros de tokens en paralelo* por
"denoising" (4× en GPU, modelo 26B solo-GPU). **Difusión y speculative decoding son DUALES**:
ambos commitean varios tokens por cada lectura de los pesos. El modelo de difusión no corre en
tu i3 (es 26B/GPU), pero su **principio** sí se importa con speculative sobre tu modelo AR
actual. Ese es el híbrido funcional: **drafter barato (n-gram o cabeza entrenable) + tu base AR
como verificador exacto** = "lo mejor de ambos mundos" corriendo HOY en tu máquina.

## Lo que de verdad mueve la aguja (medido, no teoría)

| Vía | Habla (tok/s) | vs 3B | Estado |
|---|---|---|---|
| 3B AR (hoy) | 8.3 | 1× | baseline |
| 3B + n-gram | ~8.8 | ~1.06× | **gratis hoy** (solo repetición/código) |
| 3B + draft 0.5B separado | 3.05 | **0.37× (¡PEOR!)** | descartar en CPU |
| **0.5B solo** | **35.9** | **4.3×** | **medido — el lever dominante** |
| 3B + cabeza MTP/EAGLE | 17.7–24.8 | 2.1–3.0× | proyectado (entrenar head) |

**La clave (confirmada por exp004):** en CPU el cuello es el **ancho de banda de memoria**, no
el cómputo. Cada token AR lee ~1.8 GiB de pesos. Por eso: **el tamaño del modelo manda**
(0.5B mueve ¼ de los bytes → ~4× tok/s), un draft model separado *compite por la banda y te
hunde*, y solo las cabezas (que comparten la lectura) o un modelo más chico ayudan.

## Plan radical pero funcional (priorizado)

1. **CASCADA DE HABLA (máximo impacto, ya casi listo):** usa un modelo 0.5B para los turnos
   conversacionales cortos/simples (saludos, charla, backchannel) → habla a **36 tok/s** (6–9×
   sobre el ritmo del habla humana, suficiente para TTS+gesto en tiempo real). Escala al 3B
   solo cuando la tarea exige profundidad (igual que la cascada 3B→7B de código). Router por
   complejidad. *Caveat medido:* el 0.5B es fluido pero menos preciso → solo para bajo riesgo.
2. **n-gram-mod por defecto** en `node/llama_backend.py` para flujos de código/RAG (gratis,
   bit-idéntico, riesgo 0).
3. **Entrenar una cabeza MTP/EAGLE-3** para el 3B → 2–3× general sin perder calidad. Es la
   respuesta a "parámetros entrenados modificables". Necesita GPU unas horas (Kaggle).
4. **(Cerrado con cota)** Difusión en CPU: llama.cpp ya soporta LLaDA/Dream, pero son ~8B y en
   CPU bandwidth-bound *pierden* contra el AR-3B (hacen N pasadas de pesos por bloque). Gana en
   GPU, no en tu i3. No se persigue.

## Hallazgo de calidad (medido esta sesión)
Probé Coder-0.5B **e** Instruct-0.5B general en habla española: **ambos son fluidos pero poco
fiables en hechos** (el Instruct general no es mejor; incluso alucina con más confianza). ⇒ la
cascada 0.5B sirve SOLO para habla social/relleno de bajo riesgo. Para *habla rápida Y precisa*
el lever robusto es la **cabeza MTP/EAGLE sobre el 3B** (prioridad sube).

## Próximos pasos concretos
1. **Entrenar/convertir la cabeza MTP/EAGLE-3 para Qwen2.5-Coder-3B** (lever general 2–3×, sin
   perder calidad) — el camino principal. GPU unas horas (Kaggle).
2. Router de cascada de habla (0.5B↔3B) acotado a turnos sociales/triviales (latencia baja).
3. `ngram-mod` por defecto para flujos de código/RAG (gratis, bit-idéntico).

*(Apagado programado 05:00; cancelar con `shutdown /a`.)*
