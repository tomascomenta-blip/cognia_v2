# XHUNDRED Fase 2 — Plan pre-registrado: QLoRA 3B vs Qwen base en T4

**Fecha:** 2026-07-02 · **Hardware:** Kaggle 1× Tesla T4 15.6GB, quota restante ~27 h ·
**Precedente:** pipeline QLoRA corrido end-to-end en GPU 2× (2026-07-01, MODE GPU/4-bit/3B,
`cognia_v3/training/kaggle/train_qlora_kaggle.py` + fixes de `train_tooluse_kaggle.py`) ·
**Marco:** `00_DISENO.md` §7 (pretrain 3B desde cero INVIABLE — doble muro cómputo+memoria;
lo viable es ESPECIALIZAR un 3B ajeno) · **Estado:** PLAN PRE-REGISTRADO (predicciones y gates
escritos ANTES de correr; desvíos van a `01_DESVIOS.md` append-only).

Síntesis de 3 informes (benchmarks, datos-nicho, infra). Las contradicciones entre informes se
resuelven acá y quedan anotadas inline (*Discrepancia resuelta*) + en el índice del Anexo.

---

## 1. Qué base y por qué (aclaración honesta del nombre "Qwen3-3B")

**"Qwen3-3B" NO EXISTE.** Verificado vía API de Kaggle (2026-07-02): la familia Qwen3 densa es
0.6/1.7/4/8/14/32B — no hay 3B. El nombre del goal era impreciso y se corrige acá, no se maquilla.
Los vecinos reales disponibles como Kaggle Models:

| instancia Kaggle | tamaño | licencia | rol en Fase 2 |
|---|---|---|---|
| `qwen-lm/qwen2.5/transformers/3b-instruct` (id 141460) | 6.18 GB fp16 | qwen-research (NO Apache) | **BASE PRIMARIA** |
| `qwen-lm/qwen2.5-coder/transformers/3b-instruct` (id 138448) | 6.18 GB | qwen-research | descartada (ver abajo) |
| `qwen-lm/qwen-3/transformers/4b` (id 301514, `fineTunable`) | 8.06 GB | Apache 2.0 | secundaria OPCIONAL (solo si sobra quota) |

**Decisión: `qwen2.5/transformers/3b-instruct` (genérico).** Razones: (a) es la referencia real
del CLI del proyecto (misma familia/tokenizer); (b) el nicho es razonamiento matemático **en
español**, y el coder-instruct rinde 3–8 pts abajo en español general (informe benchmarks); (c) la
comparación honesta es base+adapter vs el MISMO checkpoint, así que cualquier base sirve para el
claim — pero una base más fuerte en español hace el resultado más informativo. Pesos NF4 ≈ 2.0 GB:
entra holgado en T4 para QLoRA y para eval.

*Discrepancia resuelta (base): datos-nicho recomendaba el coder-3b-instruct porque es el ya probado
por el pipeline; infra recomendaba el 3b-instruct genérico. Se adopta el GENÉRICO: el pipeline es
portable (mismo loader `_find_model_dir`, misma familia) y el nicho es español-matemático, no
código. Riesgo anotado: el genérico no corrió aún por el pipeline → smoke de load en P2-K1 antes de
gastar nada más.*

**Qwen3-4B**: existe y es Apache 2.0, pero es el hybrid-thinking (el 4b-instruct-2507 dio 404
verificado). En NLL no afecta; en generación exigiría `enable_thinking=False`. Queda como brazo
condicional NO presupuestado — se corre solo si P2-K1+K2 cierran bajo presupuesto y sobra quota.

---

## 2. Benchmarks elegidos (3, uno por eje)

Los tres son CC-BY-SA-4.0 (sin cláusula NC), tienen parquet en HF (cargan con `datasets>=3` sin
`trust_remote_code`), y chance levels DISTINTOS (25/50/~0) que hacen legible el reporte: todo score
se compara contra su chance, no contra 0. Descartados: HellaSwag-es y ARC-es (traducción GPT-3.5 +
licencia CC-BY-NC), XNLI/PAWS-X (no mapean a los 3 ejes, XNLI semi-saturado).

| eje | suite | HF dataset / config | N | formato | chance | costo eval T4 (NF4, por modelo) | score público esperado del base |
|---|---|---|---|---|---|---|---|
| **razonamiento** | MGSM-es | `juletxara/mgsm` / `es` | 250 test (+8 exemplars train) | generativo, exact-match del número final | **~0%** | 10–16 min (batch 16, ≤384 new tok) | sin público para 3B; proyección desde GSM8K-en instruct 86.7 (blog Qwen) − gap español 10–25 pts → **55–70% en 8-shot CoT**; nuestro primario 0-shot será menor |
| **coherencia** | XStoryCloze-es | `juletxara/xstory_cloze` / `es`, split `eval` | 1,511 | 2-way, elegir final de historia por NLL | **50%** | 3–5 min | **68–74%** (3–7B históricos 60–72; Qwen2.5 fuerte multilingüe; el blog solo publica el agregado Multi-Understanding 76.6) |
| **comprensión** | Belebele-es | `facebook/belebele` / `spa_Latn` | 900 | MC 4-way (pasaje FLORES + pregunta) por NLL | **25%** | 8–13 min | sin público para 3B; anclas: Qwen2.5-7B 83.3, Gemma-2-9B 89.2 (paper Iberian) → **65–75% por NLL** |

**Protocolo de scoring (idéntico en base y base+adapter, o el delta es inválido):**
- **NLL (XSC, Belebele):** chat template de Qwen en ambos modelos; la opción se scorea como
  continuación del turno assistant; **NLL media por token de la opción** (normalización fijada acá:
  media por token, NO byte-length — cambiarla cambia el ranking). NO extracción generativa de letra:
  el paper Iberian muestra que hunde a los 3B (Ministral-3B 27.4 probablemente por extracción).
- **MGSM (generativo):** greedy (temp 0), `max_new_tokens=384`, stop temprano en newline posterior
  a `####`. Protocolo PRIMARIO: **0-shot instruido** ("Resuelve paso a paso y termina con
  `#### <número>`", en español, mismo template ambos lados). Secundario CONDICIONAL: **3-shot CoT**
  (3 de los 8 exemplars del train de MGSM, fijados por índice antes de correr) — control
  formato-vs-razonamiento (§4). Extracción DOBLE reportada por separado: estricta (número tras
  `####`) y laxa (regex `[-+]?\d[\d.,]*` sobre la última línea).

*Discrepancia resuelta (protocolo MGSM): benchmarks proponía 8-shot CoT; datos-nicho 0-shot
instruido. Primario = 0-shot idéntico ambos lados (es la condición que el FT entrena y el harness
único); el few-shot queda como control secundario con 3 exemplars (8 infla contexto y minutos).*

*Discrepancia resuelta (max_new_tokens): 256 (benchmarks) vs 512 (datos-nicho) → **384** con stop
temprano; truncaciones CONTADAS y reportadas (si >5% de items truncan, se anota como sesgo contra
el modelo que trunca).*

*Discrepancia resuelta (throughput de eval): benchmarks tasó 3–6k tok/s prefill; infra tasó NF4-bnb
en 1.0–1.6k tok/s. Se PLANIFICA con el conservador (infra) y se mide de verdad: gate de tok/s sobre
los primeros 50 items con orden de recorte pre-decidido (§5, GP2-2). Los minutos de la tabla ya
usan el rango conservador.*

**Costo total de eval: 21–34 min/modelo (sin 3-shot) o 33–52 min/modelo (con 3-shot).**

---

## 3. Nicho + datos de fine-tune (higiene train/test explícita)

**Nicho: razonamiento matemático en español (target = MGSM-es).** Es el único nicho candidato con
train split legítimo + eval canónica de traducción HUMANA + métrica objetiva (exact-match numérico).
El nicho alternativo (instrucciones-es generales) se descarta: su ganancia en "coherencia" solo
sería medible con LLM-judge (no disponible offline en Kaggle; medir con juez débil viola honestidad).

**Mezcla de fine-tune (~3.4–3.8M tokens en 2 épocas, dentro de los 2–4M/30–60 min de T4):**

| componente | fuente | N | licencia | rol |
|---|---|---|---|---|
| principal (~85%) | `Danielbrdz/gsm8k-ES` (GSM8K **train** traducido con Llama-3.3-70B) | 7,473 | MIT | señal del nicho: CoT matemático en español |
| regularizador (~15%) | `Iker/OpenHermes-2.5-Spanish`, muestra seed=1234, filtrada ≤512 tok | ~1,500 convs | Apache 2.0 | anti-olvido de formato chat general |

Formato: chat template Qwen; user = pregunta tal cual; assistant = razonamiento paso a paso
terminando en **`#### <número>`** (se preserva la convención del answer original → extracción
determinista en eval).

**Higiene train/test (explícita, con verificación activa, no solo "por construcción"):**
1. **Disjunción estructural:** `gsm8k-ES` = exactamente los 7,473 items del TRAIN de GSM8K;
   MGSM-es = 250 items del TEST de GSM8K (traducción humana) → **intersección vacía por
   construcción**.
2. **Decontaminación verificada en el kernel (assert, no confianza):** hash normalizado (lowercase,
   sin acentos, sin espacios) de las 250 preguntas MGSM + los 900 pasajes+preguntas Belebele + los
   1,511 contextos XSC contra TODO el train mix → **assert intersección = 0** antes de entrenar.
3. **Exemplars del prompt:** los 8 CoT del train de MGSM provienen del train de GSM8K → pueden
   estar en `gsm8k-ES` con otra traducción. Se EXCLUYEN del train de FT los ≤8 items que matcheen
   por respuesta numérica final + multiconjunto de números de la pregunta (barato, cierra el leak
   del control 3-shot).
4. **Fallback:** si la auditoría de calidad falla (gate GP2-3: 20 items muestreados a mano; >2/20
   con números/unidades corruptos por la traducción → descartar `gsm8k-ES`), usar
   `ericrisco/gsm8k-translated-spanish` **SOLO split train** (su test = GSM8K test traducido =
   contaminación directa con MGSM — jamás tocarlo). Si ambos fallan: **abortar el nicho** y
   re-planear en `01_DESVIOS.md`; no hay nicho B pre-registrado y se declara.
5. XSC/Belebele no tienen split de train en la mezcla → sin vector de contaminación propio; el
   check (2) los cubre igual contra OpenHermes.

**Evidencia de que el nicho puede moverse con QLoRA r=16:** LoRA r=16 sobre MetaMathQA sube GSM8K
decenas de puntos y olvida menos que full-FT (arXiv 2405.09673); QLoRA +8–14 pts sobre base con gap
4-bit de 2–4 pts (medRxiv 2025.10.21); FT sobre datos estilo GSM8K-train es la receta estándar
(MetaMath, arXiv 2309.12284).

---

## 4. Predicciones pre-registradas

Comparación SIEMPRE base+adapter vs el MISMO checkpoint base, mismo harness, misma precisión (NF4
ambos lados). Errores estándar: MGSM N=250 → SE≈3.1 pts; XSC N=1,511 → SE≈1.2; Belebele N=900 →
SE≈1.5. "Gana" exige Δ ≥ ~2·SE.

| # | suite (protocolo) | base predicho | Δ predicho (FT − base) | ¿ganamos? (criterio) |
|---|---|---|---|---|
| P1 | **MGSM-es 0-shot, extracción estricta `####`** | 30–50% | **+10 a +18 pts** | **SÍ** — gana si Δ ≥ +6 |
| P2 | MGSM-es 0-shot, extracción laxa | 40–58% | +6 a +12 | sí — gana si Δ ≥ +4 |
| P3 | MGSM-es 3-shot CoT, laxa (control) | 48–66% | +2 a +8 (**menor que P1**) | control, sin claim propio |
| P4 | XStoryCloze-es (NLL) | 66–74% | **−2 a +2 (empate)** | **NO** — se predice empate |
| P5 | Belebele-es (NLL) | 62–75% | **−4 a +2** | **NO** — regresión leve posible y esperable |

**Reglas de interpretación (congeladas antes de correr):**
- Éxito del nicho = P1 (Δ≥+6) **y** P2 (Δ≥+4). Si P1 grande pero P2 <+4 → la ganancia es de
  **FORMATO** (aprendió `####`), se reporta como tal, no como razonamiento.
- Si Δ(P3) ≈ 0 con Δ(P1) grande → mayor parte del salto es formato (el few-shot ya le da el formato
  al base); el claim se degrada explícitamente.
- No-catástrofe: XSC no cae >3 pts ni Belebele >4 pts. Si caen más → "especialización con costo
  general", se reporta igual (la regresión ES parte del resultado).
- Si P4 o P5 SUBEN >2·SE → **sospechar del harness antes que celebrar** (nada en el train debería
  mover coherencia narrativa ni comprensión lectora).

*Discrepancia resuelta (dirección de la predicción): el informe benchmarks predijo "QLoRA no moverá
MGSM-es; lo esperable es mejora en XStoryCloze/quizá Belebele" — pero eso ASUMÍA nicho de
instrucciones-es generales. El informe datos-nicho eligió nicho matemático-es precisamente para
apuntar a MGSM. La contradicción es de premisa, no de datos: con `gsm8k-ES` como train, la
predicción correcta es la de datos-nicho (gana MGSM, neutro/regresión en los otros dos), y así
queda pre-registrada arriba.*

Contexto de calibración (informativo, no gate): los rangos del base salen de scores públicos de
modelos vecinos (§2); la calibración REAL es la corrida P2-K1 propia — nunca comparar el FT contra
números publicados (harness distinto).

---

## 5. Plan de kernels (P2-K1, P2-K2) con presupuesto de minutos T4

Kernels NUEVOS self-contained estilo XH (patrón `run_kaggle_xh.py` + staging con
`kernel-metadata.json`), NO reusar `train_qlora_kaggle.py` tal cual (su eval es keyword-matching de
10 preguntas — inservible acá). Piezas heredadas (probadas): `_ensure_bitsandbytes()` ANTES de
importar transformers (fix 8b67ac3), `_find_model_dir`, load NF4, cast LoRA→fp32 (GradScaler),
fallback fp16, y **`_disable_torchao` de `train_tooluse_kaggle.py`** (torchao 0.10 del image rompe
peft — sin este port, K2 muere en el import). Runner: `PYTHONUTF8=1` obligatorio (lección XSPEED),
`enable_internet=true` (pip bnb + datasets HF), 1 sola GPU `cuda:0` (DP 2×T4 medido más lento).

### P2-K1 — eval del base (`xh_p2k1_evalbase.py`) — presupuesto 60 min, techo 75

| paso | detalle | min |
|---|---|---|
| setup | pip bnb, load NF4 del Kaggle Model input (sin descarga), smoke de generación (10 tok) | 6–8 |
| gate GP2-2 | tok/s medido en 50 items Belebele (NLL) + 10 generaciones MGSM → proyectar total | 3 |
| Belebele 900 | NLL batcheado b16, padding izquierdo, loss solo sobre tokens de la opción | 8–13 |
| XStoryCloze 1,511 | ídem, 2 opciones | 3–5 |
| MGSM 0-shot 250 | greedy, ≤384 new tok, batch 16, extracción estricta+laxa | 10–16 |
| MGSM 3-shot 250 | CONDICIONAL: solo si la proyección total ≤ presupuesto | 12–18 |
| salida | `eval_p2_base.json`: score por suite + SE + tok/s medidos + conteo de truncaciones | 1 |

**GP2-1 (harness sano, gate duro):** base Belebele ≥40% (≫ chance 25), XSC ≥55%, MGSM laxa ≥15%.
Si falla → el harness está roto (prompt/template/extracción); NO entrenar encima; diagnosticar.
**GP2-2 (recortes pre-decididos, en orden):** si proyección >90 min → (1) cae MGSM 3-shot,
(2) Belebele 900→450 estratificado (SE 1.5→2.3), (3) XSC 1,511→755. **NUNCA** recortar MGSM 0-shot
(es el eje del nicho, N=250 ya es mínimo).

### P2-K2 — QLoRA + eval del adapter (`xh_p2k2_qlora.py`) — presupuesto 110 min, techo 120

| paso | detalle | min |
|---|---|---|
| setup + datos | load NF4 + descarga datasets + tokenizar/packing + decontaminación §3 (asserts) + auditoría GP2-3 automatizable (conteo de dígitos preservados en 20 items, revisión manual pre-corrida sobre dump local) | 10–12 |
| train QLoRA | config abajo; **corte duro por reloj a 45 min** (el wall manda, no el conteo de épocas): medir tok/s en step 50 y recalcular `total_steps` para que el cosine aterrice en el corte | 35–45 |
| eval | LA MISMA de K1 (mismo código, mismos regímenes que K1 haya corrido) sobre base+adapter | 33–52 |
| salida | `final_adapter/` (solo adapter, nunca merged — licencia §6) + `eval_p2_compare.json` con Δ por suite | 2 |

**Config QLoRA (congelada):** base NF4 (`bnb_4bit_compute_dtype=fp16`), LoRA **r=16, α=32,
dropout 0.05**, target `q,k,v,o,gate,up,down_proj` (razonamiento pide MLP, no solo atención — sube
del r=8/q,k,v,o actual del pipeline), lr **2e-4** cosine + warmup 3%, **seq 1024 con packing** de
ejemplos, per-device batch **4 SIN gradient-checkpointing** (desactivar el default de
`prepare_model_for_kbit_training`: ~1.2–1.3× medido XSPEED) × grad-accum 4 = **efectivo 16**,
`paged_adamw_8bit`, fp16, **2 épocas objetivo** (~3.6M tok) con el corte por reloj como techo.
Fallback OOM automático: b2 + GC.

*Discrepancia resuelta (seq/batch): datos-nicho pedía seq 768 + batch efectivo 16 vía accum; infra
pedía seq 1024 + b4 sin GC. Se combinan: seq 1024 con packing (mejores GEMMs, mismo presupuesto de
tokens; los items GSM ~230 tok empacan 4/seq) y b4×accum4 = efectivo 16 sin GC.*

*Discrepancia resuelta (duración de train): "2 épocas ≈ 3.4–3.8M tok" (datos-nicho) vs "~30 min ≈
1–2 épocas" (infra) → corte duro por reloj a 45 min con schedule recalculado al tok/s real
(estilo XHUNDRED §4.3: el wall manda). Predicciones de §4 condicionadas a ≥1.5 épocas completadas;
si se completa menos, se reporta y el rango predicho se marca como no-testeado.*

### Presupuesto total

| kernel | nominal | techo |
|---|---|---|
| P2-K1 | 60 min | 75 min |
| P2-K2 | 110 min | 120 min |
| **total Fase 2** | **~170 min (2 h 50)** | 3 h 15 (los recortes GP2-2 lo devuelven a ≤3 h) |

≤ ~11% de la quota restante (~27 h). El brazo opcional Qwen3-4B (repetir K1+K2, +~3 h) NO está en
el presupuesto: decisión posterior en `01_DESVIOS.md` si el core cierra limpio.

---

## 6. Declaración de honestidad

**Qué SIGNIFICA "superar a Qwen" en esta fase:** que `base+adapter` supere al **MISMO checkpoint
base** (Qwen2.5-3B-Instruct NF4), con el mismo harness, la misma precisión y el mismo protocolo, en
**EL NICHO pre-registrado** (MGSM-es), con Δ ≥ 2·SE (§4), reportando los TRES ejes — incluidas las
regresiones. Eso, y nada más.

**Qué NO se puede reclamar (lista congelada):**
1. **"Superamos a Qwen3-3B"** — ese modelo no existe (§1). Todo reporte dice "Qwen2.5-3B-Instruct".
2. **Superioridad general.** El pre-registro PREDICE empate o regresión fuera del nicho (P4/P5).
   Qwen vio ~36T tokens de pretrain; nuestro presupuesto es ~6 órdenes de magnitud menor
   (`00_DISENO.md` §7). Un QLoRA de 45 min solo compra ESPECIALIZACIÓN.
3. **Conocimiento nuevo.** GSM8K train está casi seguro en el pretrain de Qwen; la ganancia
   medible es especialización de formato+idioma+convención de salida, no matemática nueva.
4. **Que el salto sea todo "razonamiento".** La separación estricta/laxa + el control 3-shot (§4)
   existen para descomponer formato vs razonamiento; el reporte publica los tres números y el
   claim se degrada según las reglas pre-registradas.
5. **Comparabilidad con scores públicos.** Los números de blogs/papers usan otros harness
   (8-shot, otras extracciones); acá solo calibran expectativas. El único par comparable es
   base-propio vs FT-propio.
6. **Redistribución de pesos.** Licencia qwen-research (no Apache): NO se publican pesos merged;
   solo el adapter (~50–100MB) + configs + jsons de eval. Si la licencia importa aguas abajo, la
   salida limpia es el brazo Qwen3-4B (Apache 2.0).
7. **"Nuestro 3B".** Fase 2 no produce un modelo nuestro: produce el DATO pre-registrado de qué
   compra QLoRA-en-T4 sobre un 3B ajeno, con la receta reproducible. Lo que XHUNDRED aporta sigue
   siendo receta y método, no pesos (00_DISENO §7).

Si un número general SUBE inesperadamente, la primera hipótesis es bug del harness, no genialidad
(§4). Si el train corta antes de 1.5 épocas, las predicciones quedan no-testeadas y se dice.

---

## Anexo — Índice de discrepancias entre informes (resueltas)

1. **Base:** coder-3b-instruct (datos-nicho) vs 3b-instruct genérico (infra) → **genérico** (§1);
   smoke de load en K1 cubre el riesgo de que el genérico no haya corrido por el pipeline.
2. **Dirección de la predicción MGSM:** "el QLoRA no moverá MGSM" (benchmarks, asumía nicho
   instrucciones-es) vs "gana MGSM" (datos-nicho, nicho matemático-es) → contradicción de PREMISA;
   con el nicho elegido rige datos-nicho (§4).
3. **Protocolo MGSM:** 8-shot CoT (benchmarks) vs 0-shot instruido (datos-nicho) → primario 0-shot
   idéntico ambos lados; 3-shot como control condicional (§2).
4. **max_new_tokens:** 256 (benchmarks) vs 512 (datos-nicho) → 384 + stop temprano + truncaciones
   contadas (§2).
5. **tok/s de eval:** 3–6k (benchmarks) vs 1.0–1.6k NF4 (infra) → se planifica con el conservador
   y se mide con gate GP2-2 (§2, §5).
6. **seq de train:** 768 (datos-nicho) vs 1024 (infra) → 1024 con packing (§5).
7. **batch:** efectivo 16 vía accum (datos-nicho) vs per-device 4 sin GC (infra) → b4 × accum 4 =
   16 efectivo, sin GC, fallback b2+GC (§5).
8. **Duración de train:** 2 épocas (datos-nicho) vs ~30 min (infra) → corte duro por reloj a
   45 min, schedule recalculado, predicciones condicionadas a ≥1.5 épocas (§5).
9. **Minutos totales:** "40–50 min" (benchmarks, solo scoring de 2 modelos, sin load/train) vs
   "2.5–3 h" (infra, todo) → no era contradicción sino alcance distinto; presupuesto unificado en
   §5 (~170 min nominal).

---

**Cierre del pre-registro.** Este documento se congela antes de P2-K1. Cambios posteriores van en
`01_DESVIOS.md` append-only con fecha y razón — nunca editando las predicciones de acá.
