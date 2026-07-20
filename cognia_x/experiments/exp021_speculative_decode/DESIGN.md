# exp021 — Híbrido AR↔Difusión para hablar rápido: el decoder de bloque-especulativo

> North Star de la sesión: *que Cognia X pueda hablar y gesticular palabras a una
> velocidad alta.* En texto-in/texto-out, eso es **tok/s de decode**. Hoy: ~8 tok/s
> (techo medido, i3-10110U, Qwen2.5-Coder-3B Q4_K_M, llama-server b9391).

## 0. Descomponer el problema grande en problemas cotidianos

El usuario pidió explícitamente: *descompón el problema grande como problemas
cotidianos, resuélvelos y súbelos al grande.* Aquí está la descomposición.

| Problema grande | Analogía cotidiana | Pregunta operativa |
|---|---|---|
| "Hablar rápido" | Un cartero que reparte casa por casa | ¿Puede repartir varias cartas por viaje en vez de una? |
| El decode AR | Una sola carta por viaje a la oficina (RAM) | El viaje (leer 1.93 GB de pesos) cuesta lo mismo lleve 1 o K cartas |
| La difusión (Gemma) | Rellenar un crucigrama: pones las letras seguras y deduces el resto | Commit de un bloque entero por pasada |
| Speculative | Un ayudante adivina las próximas casas; el cartero solo confirma | Si el ayudante acierta K, el cartero hace 1 viaje por K cartas |

**La intuición central (sigue la intuición, no solo lo científico):** el cuello de
botella no es *pensar* los tokens, es *ir a buscar los pesos a la RAM*. Si logramos
**commitear varios tokens por cada viaje a la RAM**, hablamos más rápido sin tocar la
base. Eso es lo que hacen —por caminos distintos— la difusión y el speculative
decoding.

## 1. La unificación: difusión y speculative son DUALES

Dato propio del lab, **exp004 (roofline CPU)**: el decode en CPU está
*memory-bandwidth-bound* (~15-22 GB/s, satura a 2 hilos; el cómputo sobra). La
métrica maestra (D-006) es **bytes movidos por token**. En Q4_K_M 3B, cada token
AR lee ~1.93 GB → 1.93 GB·8 tok/s ≈ 15 GB/s, que **coincide con exp004**: el techo
de 8 tok/s ES el ancho de banda, no la CPU.

Con esa lente, los dos "mundos" son la misma idea:

```
                 tokens commiteados por cada lectura completa de pesos
  AR puro:       1                       (1 viaje = 1 token)   -> 8 tok/s
  Speculative:   K_aceptados             (1 verificación batch confirma K) 
  Difusión:      bloque / pasos_denoise  (1 pasada refina todo el bloque)
```

- **Difusión (DiffusionGemma, fuente Google, tier-3):** arranca de un "canvas" de
  tokens placeholder y hace pasadas iterativas *fijando los correctos y usándolos
  como pistas para refinar el resto* (unmasking por confianza), atención
  bidireccional, bloque de 256. 1000+ tok/s en H100. **Pero**: requiere un modelo
  *entrenado para difusión* (26B MoE, GPU). En i3 es inviable correrlo.
- **Speculative (EAGLE/Medusa/n-gram, tier-1):** un drafter barato propone K tokens;
  la base AR los **verifica en un solo forward batcheado**. Si acepta, gana K tokens
  por 1 lectura de pesos. A temperature=0 es **lossless**: salida idéntica a AR.

**Conclusión de diseño:** no podemos traer el *modelo* de difusión al i3, pero sí su
*principio* (commit de bloque), implementándolo con la maquinaria que SÍ corre hoy:
**speculative decoding sobre el GGUF AR existente.** Eso es "lo mejor de ambos
mundos" que pidió el usuario, hecho funcional en el hardware real.

## 2. Respuesta a "¿hay parámetros entrenados modificables que funcionen con su
sistema actual?"

Sí — y hay una **escalera de tres peldaños**, todos compatibles con el sistema actual
(GGUF + llama-server b9391, que YA expone `--spec-type`):

| Peldaño | Parámetros entrenables | Coste de banda extra | Entrenamiento | Estado |
|---|---|---|---|---|
| **0. ELC LoRA** (ya existe) | adapters K/V rank-4 por usuario (`node/local_adapter.py`) | ~0 (KB) | sí, en sueño | personaliza *qué* dice, no acelera |
| **1. n-gram / lookup** | **ninguno** (0 params, 0 entrenamiento) | **0** (escanea el contexto) | no | `--spec-type ngram-*` ya en el binario |
| **2. MTP / EAGLE-3 heads** | cabezas pequeñas sobre la base congelada | ~0 (MB, comparten la lectura) | sí (horas en commodity GPU; o head pre-entrenada de HF para Qwen2.5) | `--spec-type draft-mtp` / `draft-eagle3` ya en el binario |

El peldaño **2** es la respuesta literal a la pregunta: **cabezas multi-token (MTP)
o EAGLE-3 son "parámetros entrenados modificables"** que se *bolt-onean* sobre la
Qwen-3B congelada, predicen un bloque de tokens (la idea de la difusión) y dejan que
la base AR verifique (exactitud). Son entrenables sobre el estilo/datos del usuario
→ habla rápida *y* personalizada. Y por exp004 son ideales para el i3: comparten la
lectura de pesos de la base, así que su coste de banda es ~0.

> Nota de coherencia con las reglas duras (CLAUDE.md): "sin draft model
> centralizado". Estos drafters son **locales** (n-gram no es modelo; MTP/EAGLE son
> cabezas locales sobre la base del nodo). No violan la regla (centralizado =
> servido desde un coordinator compartido).

## 3. El híbrido propuesto: **block-speculative decoder bandwidth-aware**

```
  Contexto ──► DRAFTER barato ──► propone bloque de K tokens (estilo difusión)
                 (n-gram: 0 bytes  |  MTP/EAGLE head: ~MB)
                          │
                          ▼
  Base AR (Qwen3B Q4_K_M) ──► VERIFICA el bloque en 1 forward batcheado
                          │     (1 sola lectura de los 1.93 GB)
                          ▼
        acepta el prefijo correcto (lossless a temp=0) ──► emite K_aceptados tokens
```

Speedup esperado (modelo de banda, se valida empíricamente en `bench_real.py` y se
afina en el modelo de coste de exp021):

```
  speedup ≈ K_aceptado · W_base / (W_base + K_propuesto · W_draft)
  n-gram  : W_draft = 0  -> speedup ≈ K_aceptado           (límite ideal de banda)
  MTP/EAGLE: W_draft ≈ pocos MB << W_base -> speedup ≈ K_aceptado · 0.9–1.0
  draft 0.5B: W_draft ≈ 0.3 GB / 1.93 GB ≈ 0.16·W_base -> penalización real
```

**Por qué esto supera el "spec-decode descartado en CPU" anterior:** el intento
viejo usaba un *draft model separado* que compite por el ancho de banda saturado
(exp004). El n-gram cuesta **0 bytes**; las cabezas MTP/EAGLE **comparten** la
lectura de la base. Reformulamos el problema desde su recurso real (banda), no desde
la suposición heredada ("spec no sirve en CPU").

## 4. Conexión con el objetivo final (hablar y gesticular)

- **Hablar:** TTS aún no existe en v2 (Cognia es texto-in/texto-out). El gate de la
  voz fluida en tiempo real es **tok/s ≥ ritmo del habla** (~2-3 palabras/s ≈
  ~4-6 tok/s sostenidos para español). Romper el techo de 8 → 12-20 tok/s da margen
  para que un TTS streaming hable sin tartamudear.
- **Gesticular:** los visemas/gestos se derivan del texto/fonemas ya generados; con
  más tok/s, el pipeline de animación recibe el texto antes y gesticula a tiempo.
- Por eso el sub-objetivo correcto AHORA es **subir tok/s de decode**; TTS/gesto son
  consumidores downstream que se desbloquean con ello.

## 5. Plan de evidencia (método del lab — código que corre o no cuenta)

1. **exp021 / bench_real.py** (REAL, sin descargas): baseline vs `ngram-*` sobre el
   i3 real, 3 tipos de prompt. Mide tok/s de decode reportado por el server y verifica
   lossless (SHA idéntico a temp=0). → H-SPEC-1.
2. **exp021 / cost model** (numpy, calibrado a exp004): predice tok/s por estrategia
   en función de la longitud de aceptación; mide aceptación n-gram offline sobre
   corpus reales (español + código).
3. **Real draft / MTP**: bajar Qwen2.5-Coder-0.5B GGUF (draft-simple) y/o una head
   MTP/EAGLE para Qwen2.5; medir el peldaño 2.
4. Wire de la mejor config en `node/llama_backend.py` con fallback + test de
   regresión; ciclo de investigación en `cognia_x/research/cycles/`.

## 6. Límites honestos

- n-gram puede dar poco en habla natural poco repetitiva (la literatura: ~1.13×
  general; mucho más en eco/RAG/código). Por eso el peldaño 2 (MTP/EAGLE) es el que
  promete habla rápida *general*. Se medirá, no se asumirá.
- `draft-mtp`/`draft-eagle3` están en el binario, pero requieren un archivo de head
  compatible con Qwen2.5-Coder-3B; hay que conseguirlo/entrenarlo (pendiente).
- Todo el speedup es de *decode*; el *prefill* (contexto largo) se ataca aparte (KV
  cache sharing de Gemma 3n, ya en el backlog F-SWA-REAL).
