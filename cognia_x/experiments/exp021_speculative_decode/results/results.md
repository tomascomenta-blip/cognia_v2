# exp021 — Velocidad de decode: speculative vs base-pequeña (REAL, i3, Qwen Q4_K_M)

> North Star: que Cognia X **hable a velocidad alta**. En texto-in/texto-out eso es
> **tok/s de decode**. Todo medido sobre el hardware REAL (i3-10110U, 2c/4t, sin GPU,
> llama-server b9391), temp=0 (greedy → speculative es lossless), n_predict=160, warm.

## TL;DR (lo que de verdad mueve la aguja)

1. **El lever dominante NO es speculative: es el TAMAÑO del modelo.** El 0.5B corriendo
   SOLO da **35.88 tok/s en habla** vs **8.32** del 3B = **4.3× más rápido**, hoy, sin
   entrenar nada. exp004 lo predice: 0.5B mueve ~¼ de los bytes/token ⇒ ~4× tok/s.
2. **n-gram speculative = ganancia GRATIS solo en texto repetitivo/RAG/código** (echo
   hasta **1.45× lossless**), pero **no acelera el habla natural** (≈1.0×) y la variante
   agresiva la **daña** (0.81×).
3. **Un draft model SEPARADO HUNDE el i3** (habla **0.367×**, echo 0.673×): compite por
   el ancho de banda y los 2 núcleos. Confirma empíricamente por qué "spec-decode se
   descartó en CPU" — pero solo aplica al *draft separado*, no a las cabezas.
4. **El único speculative que respeta la pared de banda son las cabezas entrenables
   MTP/EAGLE** (coste de banda ~0, comparten la lectura del 3B): proyección calibrada
   **17.7–24.8 tok/s (2.1–3.0×)**. El binario ya las soporta (`draft-mtp`/`draft-eagle3`).

## 1. Baseline real (3B Q4_K_M, warm)

| prompt | tok/s |
|---|---|
| code | 8.70 |
| speech (objetivo) | 8.32 |
| echo (repetición) | 8.08 |

Calibración (cost_model): 8.32 tok/s × 1.797 GiB = **14.96 GiB/s = en la pared de
memoria** de exp004 (15.6–22.2 GiB/s, algo por debajo por overhead no-GEMV) ⇒ decode
**bandwidth-bound** confirmado. El "code=1.43" del primer pase fue artefacto **cold-mmap**
(1er forward faultea los pesos desde disco); con warmup desaparece.

## 2. Speculative sobre el 3B (warm, vs baseline; lossless = SHA idéntico a temp=0)

| spec-type | code | speech (objetivo) | echo (repet.) | bit-idéntico | veredicto |
|---|---|---|---|---|---|
| **ngram-mod** | ~1.06× | **1.056×** | 1.133× | **SÍ (todos)** | seguro; gana siempre un poco; riesgo 0 |
| ngram-map-k | — | 0.998× | 1.287× | no (FP greedy) | bueno en repet.; neutral en habla |
| ngram-simple | 0.72× | 0.814× | **1.333× (lossless)** | echo sí | agresivo: gran echo, **daña** el resto |
| **draft-0.5B** | 0.64× | **0.367×** | 0.673× | echo sí | draft separado **HUNDE todo** (banda) |

- A temp=0 las variantes agresivas pueden **divergir token-a-token** del baseline (FP en
  la verificación batcheada) aunque sean lossless en distribución; **ngram-mod es
  bit-idéntico** en los 3 prompts → el default seguro.
- El habla natural (poco repetitiva) casi no da n-gramas reutilizables ⇒ n-gram no ayuda.

## 3. El lever radical: base pequeña (0.5B SOLA, warm)

| prompt | 0.5B tok/s | vs 3B |
|---|---|---|
| code | 36.52 | 4.2× |
| speech | **35.88** | **4.3×** |
| echo | 32.06 | 4.0× |

El habla fluida pide ~4–6 tok/s; **36 tok/s = 6–9× headroom** → desbloquea TTS streaming
+ gesticulación sin tartamudeo. Estrategia: **cascada** — 0.5B para el camino
conversacional/habla, escalar al 3B solo cuando la tarea exige profundidad (ya se usa esa
idea para código: 3B→7B).

## 4. Proyección peldaño-2 (cabezas MTP/EAGLE, modelo de banda calibrado a exp004)

| estrategia | speedup | tok/s proyectado | nota |
|---|---|---|---|
| draft-0.5B (a=2.0) | 1.05× | 8.7 | penalizado: +0.34 GiB/token |
| draft-0.5B (a=3.0) | 1.57× | 13.1 | idem |
| **MTP/EAGLE-head (a=2.4)** | **2.13×** | **17.7** | banda ~0; params entrenables |
| **MTP/EAGLE-head (a=3.4)** | **2.98×** | **24.8** | idem |

Las cabezas son la respuesta literal a *"parámetros entrenados modificables que funcionan
con el sistema actual"*: se bolt-onean sobre el 3B congelado, predicen un bloque (la idea
de la difusión) y la base AR verifica (exactitud). Faltan pre-entrenadas para
Qwen2.5-Coder-3B → entrenar/convertir (Kaggle pipeline disponible).

## 5. Conexión con DiffusionGemma (el "nuevo método" de Gemma)

DiffusionGemma genera **bloques en paralelo** por denoising (4× en GPU, 26B MoE, GPU-only
→ inviable en i3). Difusión y speculative son **duales**: ambos commitean varios tokens
por lectura de pesos. En i3 importamos el *principio* por dos vías que SÍ corren:
(a) hacer la lectura más barata (base pequeña, §3) y (b) más tokens por lectura con
drafter de banda ~0 (cabezas, §4). El modelo de difusión en sí no es portable al i3 hoy.

## Veredicto

**H-SPEED-1 = MIXTA** (registrada en el ledger, cycle34, DoD completo, verify_no_loss=OK):
speculative sube tok/s pero **condicional al tipo de texto**; para el objetivo (habla
rápida) los levers reales son **base pequeña + cascada** (medido 4.3×) y **cabezas
entrenables MTP/EAGLE** (proyectado 2–3×), NO el draft separado (medido 0.37×).

## 6. Calidad del 0.5B en habla española (CYCLE 5) y la rama difusión-en-CPU

**Calidad (real, temp=0.7):** el 0.5B-Coder es **fluido** en español pero **menos preciso**
que el 3B: falla "¿por qué el cielo es azul?" (repite la instrucción), da una definición vaga
de gravedad y alguna palabra inventada. El 3B es más fiable (aunque también erró la física del
cielo). ⇒ el lever 4.3× sirve para **habla fluida de bajo riesgo** (saludos, charla corta,
backchannel), no para respuestas sustantivas. Diseño: **cascada con router por complejidad**
(0.5B en turnos cortos/simples → 36 tok/s; escalar al 3B para sustancia).

**3-vías (Coder-0.5B vs Instruct-0.5B vs 3B):** el 0.5B-Instruct general **NO es mejor** que el
Coder — falla "cielo" (sin sentido), inventa con confianza en "dormir" ("espejo cálido…
antiviral") y da gravedad incorrecta. **Ambos 0.5B son fluidos pero poco fiables en hechos.**
⇒ el camino 0.5B sirve SOLO para habla social/relleno de bajo riesgo; el lever general robusto
para *habla rápida Y precisa* es la **cabeza MTP/EAGLE sobre el 3B** (2–3×, conserva calidad).

**Difusión en CPU (rama explorada → cerrada con cota nombrada):** llama.cpp YA soporta LLMs de
difusión (Dream/LLaDA/RND1), pero vía `llama-diffusion-cli` (no el server, que es lo que
tenemos) y con modelos ~8B (~5 GB Q4). En CPU *bandwidth-bound* (exp004) la difusión hace N
pasadas de denoising por bloque, cada una leyendo TODOS los pesos. Para que un difusión-8B
gane al AR-3B se necesita `bloque/N · (3B/8B) > 1` ⇒ `bloque/N > 2.7`; la difusión de calidad
usa `bloque/N ≈ 1–2 < 2.7` ⇒ **el difusión-8B PIERDE contra el AR-3B en el i3**. Difusión gana
en GPU (cómputo paralelo), no en CPU bandwidth-bound. Límite físico nombrado ⇒ no se persigue
el download de 5 GB; el 0.5B AR (36 tok/s) es el mejor camino CPU para habla rápida.

## 7. Lever de cuantización (CYCLE 11): REFUTADO para el 3B

Q3_K_S (1.354 GiB) vs Q4_K_M (1.797 GiB) en el i3, medido (warm, ignore_eos):
- speech 9.08 vs 8.37 tok/s = **1.085×**; code 8.52 vs 8.67 = 0.98×. **NO** el 1.33× que
  sugería el ratio de tamaño.
- Calidad Q3_K_S: **ROTA** (salida incoherente: "23 La frase 'El 3' no tiene significado…").

Insight (refina el modelo de banda, que era una COTA SUPERIOR): tok/s **no** es ∝
1/bytes-del-GGUF. Hay coste por token FIJO fuera del weight-streaming (lm_head O(V=151936),
dequant Q3 más caro que Q4, atención/KV) que domina cuando la reducción de tamaño es modesta
(Q4→Q3 = solo 1.33× menos bytes). Por eso bajar de cuantización casi no acelera Y degrada la
calidad. El lever real es reducir el **TAMAÑO** del modelo (0.5B = 6× menos params → 4.3×), no
la cuantización. **Branch cerrada** (fracaso = información).

## 8. Latencia conversacional real CON vs SIN cascada (consolidación)

Conversación de 6 turnos (3 sociales + 3 sustantivos), wall-time real medido:
- **Turnos sociales:** SIN 2.46/2.74/1.86 s → CON **0.63/0.68/0.48 s** = **~4-5× (sub-segundo)**. La
  cascada hace las respuestas sociales/backchannel **casi instantáneas** — clave para el "feel" de habla.
- **Turnos sustantivos (3B):** ~6-12 s, **sin cambio** (los domina el techo de ~8 tok/s del 3B).
- **Conversación total:** SIN 34.92 s → CON 31.55 s = **1.11×** (ahorro 3.37 s).

**Lección honesta:** la cascada gana en **responsividad percibida** (social instantáneo), no en throughput
total — la conversación completa la dominan los turnos sustantivos. El gran lever del total sigue siendo
acelerar el 3B (cabeza EAGLE, gated). (Estimación conservadora: single-turn sin historia en ambos casos.)

## Reproducir
```
venv312\Scripts\python.exe cognia_x\experiments\exp021_speculative_decode\bench_real.py
venv312\Scripts\python.exe cognia_x\experiments\exp021_speculative_decode\bench_draft.py
venv312\Scripts\python.exe cognia_x\experiments\exp021_speculative_decode\bench_small_base.py
venv312\Scripts\python.exe cognia_x\experiments\exp021_speculative_decode\cost_model.py
venv312\Scripts\python.exe cognia_x\experiments\exp021_speculative_decode\analyze.py
venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle34_speculative_decode
```
(Requiere el draft GGUF 0.5B en model_shards/qwen-coder-0.5b-q4/ — gitignored.)
