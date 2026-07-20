# 03 — Plan de entrenamiento y datos (Kaggle GPU + curriculum + motor de datos verificados)

> **Propósito.** Especificar **cómo se entrena** Cognia-X v1: dónde corre cada cosa (el i3 NO
> entrena a escala → **Kaggle GPU** para todo lo grande), el **curriculum** de tres ejes (recall
> asociativo + char-LM de lenguaje + tareas verificables) sobre el sustrato `HybridLM`, y el
> **motor de datos de auto-mejora (STaR)** que genera datos **verificados** para mejorar el
> sustrato sin deriva — gobernado por un **ledger de procedencia** (`origin∈{real,syn}`,
> generación `g≤1`, cuota `≤15%` sintético). Cierra con **DoD por fase de entrenamiento**.

Confianza: **alta en la DIRECCIÓN** (cada eje del curriculum ya corre de verdad en el lab; el motor
de datos ya produjo pares verificados reales), **media/baja en las CONSTANTES de escala** (SCALE=0%
en el ledger: nada se midió aún en GPU a tamaño v1; ver 00_READINESS §5.1). Marco cada afirmación
como **PROBADO** (cita exp/CYCLE/archivo) / **ASUMIDO** (literatura/conjetura) / **PENDIENTE** (a
medir). Alineado con `00_READINESS.md` (gates G1/G2/G3), `01_arquitectura_sistema.md` y
`02_backbone_modelo.md` (config v1, ramas A/B).

---

## 1. Propósito y alcance

**Alcance.** El *pipeline de entrenamiento* de Cognia-X v1: (1) la separación dura **i3 (inferencia
+ smoke + experimentos) ↔ Kaggle GPU (entrenamiento a escala)**; (2) el **curriculum** y su schedule;
(3) el **motor de datos verificados** (STaR) y su **ledger de procedencia** anti-deriva; (4) el
camino **smoke local → corrida real en Kaggle**; (5) la telemetría y los **DoD por fase**.

**Fuera de alcance** (otros planos): la config interna del backbone y la decisión de rama A/B
(`02_backbone_modelo.md`); la representación/tokenizer y la inyección de hechos RAG vs LoRA vs kNN-LM
(gate G3); el verificador profundo como subsistema y el lazo de auto-mejora a nivel de sistema
(planos de verificador/lazo) — **este plano usa el verificador como compuerta de datos**, no lo
re-especifica.

**Qué decide este plano (load-bearing):**
1. Las **dos pistas de entrenamiento** y cuál existe hoy vs cuál hay que construir.
2. El **curriculum** (ejes, schedule, mezcla multi-tarea) y sus métricas de cierre.
3. El **contrato del motor de datos**: qué entra al JSONL, con qué compuerta, y el **ledger de
   procedencia** (esquema + invariantes que el build DEBE chequear antes de cada re-entreno).
4. La disciplina **smoke→real** (no gastar cuota de Kaggle sin pasar el smoke local primero).

---

## 2. Estado de partida (qué existe y corre hoy)

### 2.1 Dos pistas de entrenamiento — una existe, la otra hay que construir

**PISTA-PRE — pre-entrenamiento del backbone híbrido desde cero.** El sustrato `HybridLM`
(`cognia_x/model/hybrid.py`) se entrena hoy con dos entrenadores REALES en CPU:
- `cognia_x/train/charlm.py` — char/byte-LM (vocab 256) sobre corpus local. **PROBADO** (CYCLE 5/7):
  loss baja, muestras plausibles, holdout **cross-book** (1 es + 1 en enteros nunca vistos), baseline
  **gzip bits/byte** como piso de entropía.
- `cognia_x/train/recall_task.py` — recall asociativo estilo MQAR; compara `lineal_puro` /
  `hibrido_3to1` / `atencion_pura`. **PROBADO** (banco de exp013-015, cierre de H-MEZ-4).
- `cognia_x/train/run_overnight.py` — orquestador: FASE 1 recall + FASE 2 char-LM, con `--smoke`
  (120 s) y `--deadline`. `torch.set_num_threads(3)` (vault i3).

**CAVEAT load-bearing (honestidad):** estos entrenadores corren en **CPU a escala juguete** (el v0
verificado en 00_READINESS C4 son **1.56M params**). **NO existe** un kernel de Kaggle que pre-entrene
el `HybridLM` desde cero en GPU a tamaño v1. Eso es **PENDIENTE** (§3.4, kernel nuevo
`pretrain_hybrid_kaggle.py`). El i3 (2c/4t, sin CUDA) **no entrena a escala** (00_READINESS §5.1).

**PISTA-ADAPT — adapter LoRA por dominio sobre un modelo CONGELADO.** **PROBADO — existe y corre en
Kaggle GPU:**
- `cognia_v3/training/kaggle/run_kaggle_training.py` — orquestador local: sube el JSONL como dataset
  privado `cognia-dataset`, pushea el kernel con GPU (`machine_shape="NvidiaTeslaT4"`,
  `enable_gpu/enable_internet=true`), pollea (`max_h=5.0`, `poll_s=60`) y descarga
  `final_adapter/` + `eval_compare.json`.
- `cognia_v3/training/kaggle/train_qlora_kaggle.py` — kernel: entrena un **adapter LoRA**
  (`r=8, lora_alpha=16, target_modules=[q,k,v,o]_proj, dropout=0.05`) sobre **Qwen2.5-Coder-3B-Instruct
  CONGELADO** (4-bit nf4 vía bitsandbytes, o **fp16 fallback** si bnb no carga), `MAX_LEN=1024`,
  batch 2 × grad_accum 8 (efectivo 16), `lr=2e-4`, cosine, warmup 0.05; evalúa base vs base+adapter
  con 10 preguntas y escribe `delta`.

**Lectura honesta:** la PISTA-ADAPT entrena **sobre Qwen, no sobre nuestro `HybridLM`**. Es la capa
(b) del aprendizaje continuo (LoRA `r≤16`, regularizador) y el camino "experto≈adapter por dominio"
del giro de CYCLE 47 — **legítima y entregable hoy**, pero **no** es el sustrato propio v1. El plano
mantiene AMBAS pistas: PISTA-ADAPT da valor inmediato sobre un base maduro; PISTA-PRE construye el
sustrato Cognia-X cuando G1/G2 (02_backbone) habiliten la config v1.

### 2.2 El motor de datos verificados — ya produjo pares reales

**PROBADO — el STaR de código corre en Kaggle:** `cognia_v3/training/kaggle/datagen_kernel.py`
genera pares `{prompt, completion, source}` de código con una **compuerta de calidad no negociable**
(regla 9 de CLAUDE.md): por candidato genera 3-5 `assert`, valida **estáticamente** solución+asserts
(`ast.parse`, **allowlist de imports** `{math,re,json,itertools,functools,collections,heapq,bisect,
string,typing,dataclasses,copy}`, prohíbe `input/open/eval/exec/compile/__import__`), y **ejecuta**
solución+asserts en **subprocess aislado `-I` con timeout 10 s**. Solo lo que pasa entra al JSONL.
Anti-leakage explícito contra `cognia_v3/eval/tasks_hard.jsonl`. Corte: 500 pares o 4 h.

**Evidencia REAL de yield (honestidad sobre el costo)** — `synthetic/datagen_report.json` de una
corrida real: `generated=20, accepted=8, acceptance_rate=0.40`, `by_band={syn_long:5, syn_spec:3}`,
`rejects={failed_run:9, bad_static:2, bad_asserts:1}`, `elapsed_s=14813` (~4.1 h con el 7B-Instruct
4-bit). **Lectura:** el motor produce pares VÁLIDOS pero **caro y lento** (~2 pares/hora de GPU en
esa corrida; el cuello es `failed_run`, soluciones que no pasan sus propios asserts). El esquema del
record ya trae `source∈{syn_long,syn_spec}` — la **semilla** del campo de procedencia que este plano
formaliza (§3.3).

### 2.3 Corpus y tooling presentes

- `cognia_x/data/get_corpus.py` + `cognia_x/data/corpus/*.txt` — **~17 MB** de prosa de dominio
  público (Gutenberg, es+en, 15 libros). **PROBADO** (CYCLE 7). Gitignored; el script lo reconstruye.
- `cognia_v3/core/sandbox_tester.py` — AST + allowlist + subprocess timeout (la compuerta canónica;
  el `datagen_kernel` la reimplementa inline en el kernel).
- Kaggle: cuenta `anthuananthuan` configurada, token en `~/.kaggle/kaggle.json`; `venv312/Scripts/
  python.exe` (Python 3.12; el `venv/` está roto).

---

## 3. Diseño detallado

### 3.0 Mapa de decisión: dónde corre cada cosa

| Tarea | Dónde | Por qué | Estado |
|---|---|---|---|
| Smoke del pipeline (no-crash, loss baja, archivos) | **i3 / venv312** | barato, sin cuota | `run_overnight --smoke` **EXISTE** |
| Experimentos numpy / recall toy / telemetría bytes/token | **i3** | CPU viable (00_READINESS) | EXISTE |
| Pre-entreno `HybridLM` v1 a escala (PISTA-PRE) | **Kaggle T4** | i3 no entrena a escala | kernel **PENDIENTE** (§3.4) |
| Adapter LoRA por dominio (PISTA-ADAPT) | **Kaggle T4** | 4-bit/QLoRA exige CUDA | `train_qlora_kaggle.py` **EXISTE** |
| Motor de datos STaR (generación+verificación) | **Kaggle T4** (gen) + **i3** (verif. local de math/recall) | el generador grande necesita GPU; la verificación determinista corre en cualquier lado | `datagen_kernel.py` **EXISTE** (código); math/recall gen **PENDIENTE** (§3.2) |

**Regla dura (cuota):** nada va a Kaggle sin pasar el **smoke local** (§3.5) primero. La cuota GPU de
Kaggle es escasa (**ASUMIDO** ~30 h/sem, ≤9-12 h/sesión según docs de Kaggle — **confianza media**,
no verificado por el lab; los presupuestos REALES del código son `TIME_BUDGET_S=4 h` por corrida de
datagen y `max_h=5.0` de poll).

### 3.1 Curriculum — los tres ejes

El curriculum entrena **una capacidad por eje**, cada uno con su **verificador** (métrica de cierre
objetiva). Todos comparten el mismo `HybridLM` (multi-tarea por mezcla de batches, §3.3).

**EJE-R — RECALL asociativo (capacidad estructural).** Tarea MQAR de `recall_task.py`: secuencia de
pares (clave,valor) + consultas; target = el valor asociado en la posición de la clave-consulta.
Knobs REALES (verbatim `recall_task.py:44-49`): `n_keys=96, n_vals=32, n_pairs=48, n_queries=8`,
`batch=32, lr=3e-4`; `L = 2·n_pairs + n_queries`. Atención **global** (`window>=L`) para el test de
recall. **Verificador:** `acc` exacta contra `azar=1/n_vals`. **Por qué está en el curriculum:** es
el banco que MIDE el caveat C-01/G2 (el híbrido naive platea ~0.18 a carga alta; solo atención pura
cruza) — entrenarlo a la **escala objetivo** es como se cierra G2 (02_backbone §G2). Escalar:
subir `n_pairs/n_keys` y `d_model` hasta el régimen v1.

**EJE-L — LENGUAJE (char-LM).** `charlm.py` sobre `cognia_x/data/corpus/` (17 MB, es+en). Config
REAL de CYCLE 7 (`run_cycle7.py` defaults): `d_model=256, n_layers=8, n_heads=8, window=128,
attn_every=4, L=192, batch=16, lr=3e-4, warmup=300, max_steps=12000` (~2.3 épocas; el tope por
pasos evita el sobreajuste de CYCLE 5 a ~29 épocas). **Verificador:** `val bits/byte` (eval
DETERMINISTA, barrido de ventanas no solapadas) contra **baseline gzip** y contra el **gap train-val**
(señal de sobreajuste). **Por qué:** demuestra que el sustrato aprende ESTRUCTURA de lenguaje, no un
registro. Migra a BPE 32-64k cuando el tokenizer se conmute (02_backbone §migración; G3).

**EJE-V — TAREAS VERIFICABLES (capacidad + combustible del motor de datos).** Tres familias, de menor
a mayor dificultad de verificación:
- **`arith`** (suma/resta/mult de enteros): generador determinista LOCAL (`prompt="12 + 47 ="`,
  `completion="59"`). **Verificador:** igualdad exacta contra la verdad COMPUTADA al generar. Datos
  **infinitos, baratos, g=0 (reales)** — no pasan por el modelo.
- **`expr`** (expresiones aritméticas con paréntesis): generador LOCAL del árbol + evaluador seguro
  (NO `eval`; evaluador aritmético sobre `ast` con allowlist de nodos, o el sandbox). **Verificador:**
  igualdad exacta. **g=0**.
- **`code`** (código Python simple): plantillas dirigidas de `datagen_kernel.py` (syn_long/syn_spec).
  **Verificador:** la compuerta sandbox (3-5 asserts ejecutados, `-I`, timeout 10 s). Aquí el modelo
  PROPONE y el verificador FILTRA → **g=1 (sintético)**, sujeto al ledger (§3.3).

`arith`/`expr` son el piso barato e infinito; `code` es el techo caro y verificado. **PENDIENTE:**
un módulo `cognia_x/train/verifiable_tasks.py` con los generadores deterministas de `arith`/`expr`
(estilo `make_recall_batch`: puro numpy/python, testeable en local) — hoy **NO existe**.

**Schedule del curriculum (ASUMIDO — sin exp propio de ordenamiento a escala):** confianza
**media** en el ORDEN incremental (L→R→V→STaR, respaldado por el Apéndice A), **baja** en los
**porcentajes exactos** del mix (70/30, 50/20/30 — conjeturas, no medidos; ver §6 #5).
fases incrementales, cada una añade un eje al *mix* sin quitar los previos (anti-olvido por mezcla):

| Fase | Mix de batches | Cierre (verificador) |
|---|---|---|
| **C1** | 100% EJE-L (lenguaje) | `val bpb < gzip baseline`; gap acotado |
| **C2** | 70% L + 30% R | EJE-R cruza el umbral de recall a la carga objetivo (G2) |
| **C3** | 50% L + 20% R + 30% V (`arith`/`expr`, g=0) | acc `arith`/`expr` > 0.95 sin colapsar L/R |
| **C4** | C3 + **motor de datos** (`code` g=1, cuota ≤15%) | mejora en `code` SIN deriva en L/R/arith (§3.6) |

El orden L→R→V→STaR respeta el **Apéndice A** del lab (sustrato sólido ANTES de amplificar con el
lazo): el motor de datos (C4) solo se enciende cuando el sustrato base (C1-C3) ya es preciso.

### 3.2 Motor de datos de auto-mejora (STaR) — contrato

El motor cierra el lazo "el modelo genera datos que mejoran al modelo", pero **SOLO** con verificación
ejecutable, nunca con auto-recompensa (restricción dura: *prohibido RL con auto-reward online o proxy
auto-generado como fitness* — modo de fallo reward-hacking/colapso, H-SELF-2). **PROBADO-pequeño:**
el motor STaR bootstrappea un base débil 0.30→0.78 estable con verificación dura (exp037/038, CYCLE
48-50). (Nota de honestidad: exp019/020 sobre reward-hack están **REFUTADAS** — la seguridad de la
imitación es precaución de diseño + literatura, no un hack medido in-lab.)

**Contrato (lo que el motor DEBE cumplir antes de que un par entre al entreno):**
1. **Verificador ejecutable**, no proxy: `code` → sandbox con asserts; `arith/expr` → igualdad
   exacta; `recall` → acc exacta. Solo `verdict==true` entra.
2. **Diversidad (anti-colapso):** dedup por hash de contenido + replay limpio. **PROBADO:** la guardia
   dedup+replay sube el `e*` tolerable de ~0.15 a ~0.50 (CYCLE 50/53).
3. **Procedencia registrada** (§3.3) en `provenance.jsonl` ANTES de mezclar.
4. **Anti-leakage:** temas DISJUNTOS del set de evaluación (`datagen_kernel` ya lo hace contra
   `tasks_hard.jsonl`); el eval NUNCA se contamina con datos del motor.

Flujo por iteración del motor:
```
modelo_g0  --genera-->  candidatos  --compuerta(sandbox/exact)-->  pares verificados (g=1)
                                                                        |
                          provenance.record(origin=syn, g=1, gen_model=hash(g0), verifier=...)
                                                                        |
build_mix(real_pool, syn_pool, quota_syn=0.15, max_gen=1)  --->  JSONL de entreno  --->  modelo_g1
```
**Disciplina g≤1 (clave anti-deriva):** `modelo_g1` se entrena con real + syn-de-g0. Los pares syn
generados por `modelo_g1` serían **g=2 y se RECHAZAN** para entreno (no syn-de-syn). Esto rompe el
bucle recursivo que causa *model collapse* (Shumailov et al. 2024, Nature — **LITERATURA**, sin exp
propio en este loop, **confianza media**). El motor puede seguir generando con g0 fijo como semilla
todo lo que quiera; lo que el cap prohíbe es **encadenar generaciones** de sintético sobre sintético.

### 3.3 Ledger de procedencia — esquema e invariantes

**Archivo:** `cognia_x/train/provenance.jsonl` (append-only, una línea por par de entreno).
**Módulo (PENDIENTE):** `cognia_x/train/provenance.py` con `record(...)`, `build_mix(...)`,
`assert_invariants(...)`.

**Esquema del record:**
```json
{
  "id": "sha1(prompt+completion)[:16]",
  "origin": "real" | "syn",
  "generation": 0 | 1,
  "task": "recall" | "charlm" | "arith" | "expr" | "code",
  "verifier": "exact" | "sandbox" | "gzip_bpb" | null,
  "verdict": true,
  "gen_model": "<sha del ckpt que generó>" | null,
  "gen_train_set": "<sha del manifest de datos del gen_model>" | null,
  "seed_ids": ["<id real del que derivó>", ...],
  "ts": 1750000000.0
}
```

**Invariantes que `build_mix` y un test de regresión DEBEN chequear (compuerta dura del re-entreno):**
1. **Cuota:** `|syn| / |total| ≤ 0.15`. Si se excede, se **submuestrea** el pool syn (priorizando por
   diversidad / por valor, §3.7) — nunca se baja la cuota silenciosamente.
2. **g≤1:** ningún record con `generation > 1` entra. Además, todo `origin==syn` con `generation==1`
   debe tener `gen_train_set` que **NO contenga ningún id `origin==syn`** (prueba de que el generador
   nunca vio sintético → no hay syn-de-syn encubierto).
3. **Solo verificado:** todo record tiene `verdict==true` y `verifier!=null` (los `real` deterministas
   usan `verifier="exact"`/`"gzip_bpb"`).
4. **Dedup:** `id` único (la guardia de diversidad CYCLE 50/53).
5. **Trazabilidad:** todo `syn` referencia su `gen_model` y sus `seed_ids` (de qué reales derivó) →
   un par defectuoso es auditable y purgable aguas arriba.

`build_mix` devuelve el JSONL final + un `mix_report.json` (conteos por `origin/generation/task`,
cuota efectiva). Ese report es **input del DoD de C4** (§7).

**Pseudocódigo de `build_mix` (concreto, sin frameworks):**
```python
def build_mix(real_recs, syn_recs, quota_syn=0.15, max_gen=1, seed=0):
    syn = [r for r in syn_recs if r["generation"] <= max_gen and r["verdict"]]
    assert all(_no_syn_in(r["gen_train_set"]) for r in syn), "g<=1 violado (syn-de-syn)"
    seen, real = set(), []
    for r in real_recs:                      # dedup
        if r["id"] not in seen: seen.add(r["id"]); real.append(r)
    # cuota: |syn| <= quota/(1-quota) * |real|
    cap = int(quota_syn / (1 - quota_syn) * len(real))
    if len(syn) > cap:
        syn = _topk_diverse(syn, cap, seed)  # submuestreo por diversidad/valor
    mix = real + syn
    report = {"real": len(real), "syn": len(syn),
              "quota_eff": len(syn) / max(1, len(mix)),
              "by_task": _count(mix, "task"), "by_gen": _count(mix, "generation")}
    return mix, report
```

### 3.4 Kernel de pre-entreno en Kaggle (PISTA-PRE) — diseño (PENDIENTE)

**Nuevo:** `cognia_v3/training/kaggle/pretrain_hybrid_kaggle.py` + reutilizar el orquestador
`run_kaggle_training.py` (mismo patrón dataset privado + push + poll + download). Diferencias con
`train_qlora_kaggle.py`:
- **No** carga Qwen ni LoRA: instancia `HybridLM(HybridConfig(...))` (copiar `hybrid.py` al staging del
  kernel — es torch puro, sin deps exóticas). La clase del backbone es un **parámetro**: si G1/G2 no
  cierran (§Riesgo residual), el mismo kernel instancia la **rama de fallback** (Transformer denso GQA
  + KV-cache 4-bit) sin tocar curriculum/ledger.
- **CUDA + AMP fp16/bf16** (T4 = Turing, sin bf16 → `fp16`), `torch.cuda.is_available()` gate, y
  **fallback CPU 0.5×-toy** para que el kernel no muera si Kaggle ignora `enable_gpu` (lección REAL:
  el backend nuevo IGNORA `enable_gpu` sin `machine_shape="NvidiaTeslaT4"` — comentario verbatim en
  `run_kaggle_training.py:99-102`).
- **Multi-tarea:** un `get_batch` que muestrea del *mix* `provenance.jsonl` según el schedule (§3.1);
  EJE-L usa `charlm.get_batch`, EJE-R `recall_task.make_recall_batch`, EJE-V tokeniza
  `{prompt,completion}` byte-level.
- **Checkpoint + métricas** idénticos a `charlm.checkpoint` (val determinista, best por val, CSV).
- **Salida** en `/kaggle/working`: `hybrid_v1_best.pt`, `metrics.csv`, `mix_report.json`,
  `samples.txt` (descargable por `kaggle kernels output`).

**Config de bring-up (`v1-α`, ASUMIDO — la fija M0 del 02_backbone):** arrancar pequeño y CRECER con
telemetría; el ledger no ata `d_model/n_layers` aquí (es decisión del 02_backbone §config v1). El
schedule de tamaño se valida por `val bpb` vs presupuesto de banda, no por intuición.

**Restricción dura respetada:** el kernel valida `hybrid.py` (allowlist de imports + el sandbox del
repo) antes de ejecutarlo; nada auto-generado se vuelve ejecutable sin pasar la verificación (regla 9).

### 3.5 Smoke local vs corrida real en Kaggle

**Smoke local (i3 / venv312) — compuerta OBLIGATORIA antes de gastar GPU:**
```
.\venv312\Scripts\python.exe -m cognia_x.train.run_overnight --smoke
```
**PROBADO (existe):** `--smoke` ⇒ `deadline=+120s`, FASE 1 recall `steps=30` (config tiny
`d=96/4 capas`), FASE 2 char-LM `d_model=96, n_layers=4, L=96, batch=8, max_steps=16`. Deja
`recall_results.json`, `summary.json`, `charlm_samples.txt`, `metrics.csv` en
`cognia_x/runs/overnight_v0/`. **Criterio de pase del smoke:** sin excepción en ninguna fase, loss
de char-LM DECRECE, `acc` de recall > `azar`, archivos escritos. (Para el motor de datos, el smoke
análogo es generar 2-3 pares y correr la compuerta sandbox local — NO requiere Kaggle.)

**Corrida real (Kaggle GPU):**
- PISTA-ADAPT (existe): `.\venv312\Scripts\python.exe -m cognia_v3.training.kaggle.run_kaggle_training
  --dataset-file <JSONL> [--push-only]`.
- Motor de datos (existe): `... -m cognia_v3.training.kaggle.run_kaggle_datagen` (genera el JSONL).
- PISTA-PRE (PENDIENTE): el orquestador análogo que pushea `pretrain_hybrid_kaggle.py`.

La disciplina es: **smoke (CPU, 2 min, sin cuota) → si pasa, push a Kaggle (GPU, horas, con cuota)**.
Nunca al revés. Es la barrera que evita quemar cuota en un bug de pipeline.

### 3.6 Detección de deriva (loops largos sin degradar)

El riesgo del motor en C4 es **deriva**: el modelo mejora `code` pero olvida/empeora L/R/arith. Guardia:
- **Eval congelado multi-eje** tras cada re-entreno: `val bpb` (L), `acc` recall (R), `acc` arith/expr
  (V), `pass@1 code` (sandbox). Si CUALQUIERA cae > umbral δ vs el ckpt anterior → **rollback** al
  ckpt previo (gate NO circular: el eval vive en datos congelados, NUNCA en la DB que el motor
  escribe — el fallo H-SELF-2 de Cognia es exactamente evaluar sobre la misma DB auto-escrita).
- **Cuota+g≤1 del ledger** como prevención estructural (§3.3): aún si el eval no cazara la deriva, la
  cuota ≤15% y el corte de generaciones acotan cuánto puede arrastrar el sintético.

### 3.7 R-VALOR como heurística de selección (ACOTADA, opcional)

El `_topk_diverse` de `build_mix` puede priorizar pares por **valor endógeno** (controlabilidad ×
relevancia) cuando hay que submuestrear el pool syn bajo la cuota. **Honestidad (00_READINESS §5.2):**
R-VALOR es una **brújula decisional** sólida solo en toy/oráculo (~31% en sistema real; el arco
downstream 149-155 cerró del lado RANKING, la tesis de calibración NO está confirmada en el lazo
real). Por eso aquí es **opcional y acotado**: un criterio de desempate sobre la diversidad, NO el
fitness del lazo. El default seguro es diversidad pura (dedup + cobertura de tareas).

---

## 4. Decisiones y alternativas

| Decisión | Conservadora | **Moderada (elegida)** | Radical | Evidencia |
|---|---|---|---|---|
| **Cuota sintético** | 0% (solo real) | **≤15%** | ≥50% | model-collapse (Shumailov 2024, LIT); el lab solo probó STaR estable con verificación dura (CYCLE 48-50). 15% = margen prudente. **ASUMIDO** |
| **Generaciones** | g=0 (sin STaR) | **g≤1** (un salto) | g libre (recursivo) | g recursivo = colapso (LIT). g≤1 conserva la ganancia STaR (exp037/038, CYCLE 48-50) sin el bucle recursivo. **ASUMIDO** (umbral anti-deriva de literatura) |
| **Pista de entreno v1** | solo PISTA-ADAPT (Qwen+LoRA, maduro) | **ambas** (ADAPT ya da valor; PRE construye el sustrato) | solo PISTA-PRE (from-scratch ya) | ADAPT **PROBADO** corre; PRE **PENDIENTE** (kernel nuevo). Mantener ambas = entregable hoy + sustrato propio cuando G1/G2 cierren |
| **Verificador del motor** | tests humanos | **ejecución sandbox / igualdad exacta** | LLM-judge / auto-reward | auto-reward = reward-hacking (H-SELF-2, restricción dura). Sandbox **PROBADO** (datagen_kernel, exp018) |
| **Schedule curriculum** | todo mezclado de entrada | **incremental L→R→V→STaR** | STaR desde el paso 0 | Apéndice A: sustrato sólido ANTES del lazo. **ASUMIDO** el ordenamiento exacto |

---

## 5. Plan de validación (cómo se mide que funciona)

**En CPU (i3 / venv312), sin cuota:**
1. `run_overnight --smoke` pasa (criterio §3.5). **Compuerta 0.**
2. Tests dirigidos: `pytest tests/test_datagen_kernel.py -q` (las funciones puras del motor ya son
   testeables, ver docstring del kernel) + un **test nuevo** `tests/test_provenance.py` que verifique
   los 5 invariantes de `build_mix` (cuota, g≤1, syn-de-syn rechazado, dedup, trazabilidad).
3. Generadores `arith`/`expr` (`verifiable_tasks.py`): test de que la verdad computada coincide con el
   evaluador seguro en 10⁴ muestras aleatorias.

**En Kaggle (GPU, con cuota):**
4. PISTA-ADAPT: `delta` (base vs base+adapter) ≥ 0 en `eval_compare.json` para el dominio entrenado.
5. PISTA-PRE: `val bpb` del `HybridLM` v1 **baja del baseline gzip** del corpus (EJE-L) y `acc` recall
   cruza el umbral G2 a la escala objetivo (EJE-R), reportados en `metrics.csv`/`mix_report.json`.
6. Motor de datos: `acceptance_rate` y `by_band` en `datagen_report.json`; el `mix_report.json` muestra
   `quota_eff ≤ 0.15` y `by_gen` sin g>1.
7. **Anti-deriva (C4):** el eval congelado multi-eje no cae > δ tras el re-entreno (§3.6); si cae,
   rollback automático y el log lo registra.

**Telemetría append-only:** cada corrida deja su `run.log` + JSON en `cognia_x/runs/<fase>/`;
los hallazgos se appendean a `MANAGER_LOG.md` (nunca borrar entradas).

---

## 6. Lo que NO está probado / riesgos

1. **SCALE = 0% (riesgo P0).** TODO el curriculum está validado en juguete (1.56M params CPU). Que el
   `HybridLM` pre-entrenado en GPU a tamaño v1 transfiera las propiedades del toy es la **mayor
   incógnita** (00_READINESS §5.1). Confianza **media** en dirección, **baja** en constantes de escala.
2. **El kernel de PISTA-PRE NO existe.** `pretrain_hybrid_kaggle.py` es PENDIENTE (§3.4). Hasta
   construirlo y correrlo, "entrenar el sustrato Cognia-X a escala" es **diseño, no hecho**. Lo que
   corre HOY en Kaggle entrena **Qwen+LoRA**, no nuestro backbone.
3. **El motor de datos es caro y de bajo yield.** Corrida real: 8 pares aceptados / 20 generados en
   ~4.1 h (`datagen_report.json`). A cuota ≤15%, juntar suficiente sintético útil para mover la aguja
   puede costar **muchas horas de GPU** — el throughput, no la calidad, es el cuello. Confianza **alta**
   en que el dato es correcto, **media** en que sea costo-efectivo a escala.
4. **Cuota 15% y g≤1 son de LITERATURA, no de exp propio.** Los umbrales anti-deriva se apoyan en
   model-collapse (Shumailov 2024) y en el STaR del lab (CYCLE 48-50), pero **el lab no midió el punto
   exacto de deriva** en este loop. Son prudentes, no óptimos. Confianza **media**.
5. **El ordenamiento del curriculum (L→R→V→STaR) no se midió a escala.** Es el orden que el Apéndice A
   sugiere, pero la mezcla exacta (70/30, 50/20/30) es **ASUMIDA**. Confianza **baja** en los %.
6. **Dependencia de bitsandbytes/4-bit en Kaggle es frágil.** El run 1 del datagen murió en el load
   4-bit (fix 8b67ac3); el kernel mitiga con `pip install -U bitsandbytes` + fallback fp16, pero la
   GPU/cuota de Kaggle puede cambiar bajo los pies. Confianza **media**.
7. **`verifiable_tasks.py` y `provenance.py` no existen** — son entregables de este plano, con riesgo
   de implementación normal (mitigado por tests dirigidos, §5).
8. **R-VALOR como selector es acotado** (§3.7): solo desempate sobre diversidad; NO apoyarse en él
   como fitness (riesgo de sobre-claim ya marcado por el lab).

---

## 7. Definición de Hecho (DoD) + dependencias + riesgos

### DoD por fase de entrenamiento (verificable)

**E0 — Smoke (compuerta, i3):**
- `run_overnight --smoke` pasa sin excepción; loss char-LM decrece; `acc` recall > azar; archivos en
  `cognia_x/runs/overnight_v0/`. `pytest tests/test_datagen_kernel.py tests/test_provenance.py -q`
  verde (`venv312`, reportar N passed/M failed).

**E1 — Lenguaje (C1, Kaggle PISTA-PRE):**
- `val bpb < gzip_val_bpb` del corpus (EJE-L); gap train-val acotado; `hybrid_v1_best.pt` +
  `metrics.csv` descargados. Config de tamaño v1 fijada con el 02_backbone (no heredada del toy).

**E2 — Recall (C2, Kaggle):**
- una config (ratio+arreglo+#globales del 02_backbone) cruza el **umbral de recall G2** a la carga
  objetivo, documentada con su tabla recall-vs-coste, **sin** degradar `val bpb` de E1.
- **CAVEAT (no asumir que el híbrido cruza):** por C-01/H-HYB-3 el techo del mezclador de estado
  fijo es **estructural** (pigeonhole, exp002; 6 levers no-atención refutados, exp010-012) y solo la
  **atención pura** cruzó a carga alta (0.88-0.95, exp013) mientras el híbrido naive plateó ~0.18
  (exp014/015). G2 puede por tanto resolverse **subiendo la fracción de atención / #globales** (rama B
  del 02_backbone), NO necesariamente con el ratio 3:1-4:1; este DoD NO presupone que el híbrido lo
  logre. Si ninguna config híbrida cruza dentro del presupuesto de banda, aplica la **rama de fallback
  arquitectónica** (ver Riesgo residual).

**E3 — Verificables g=0 (C3, Kaggle + i3):**
- `verifiable_tasks.py` existe y testeado; `acc` `arith`/`expr` > 0.95; los pares g=0 quedan en
  `provenance.jsonl` con `verifier="exact"`; sin regresión en L/R.

**E4 — Motor de datos g=1 (C4, lazo):**
- `datagen_report.json` con `acceptance_rate` reportada; `build_mix` produce `mix_report.json` con
  `quota_eff ≤ 0.15` y `by_gen` sin g>1 (test de invariantes verde); mejora medible en `pass@1 code`
  **sin** caída > δ en el eval congelado multi-eje (anti-deriva, §3.6); rollback probado (un re-entreno
  que degrada se revierte solo y queda en el log).

### Dependencias
- **Hardware:** i3/venv312 (smoke, experimentos, verificación local) + **Kaggle T4** (todo entreno a
  escala). Cuenta `anthuananthuan`, token `~/.kaggle/kaggle.json`.
- **Existe y corre:** `hybrid.py`, `charlm.py`, `recall_task.py`, `run_overnight.py`,
  `run_kaggle_training.py`, `train_qlora_kaggle.py`, `datagen_kernel.py`, `run_kaggle_datagen.py`,
  `get_corpus.py` + corpus 17 MB, `sandbox_tester.py`, `model_constants.py`.
- **A construir (entregables de este plano):** `cognia_x/train/verifiable_tasks.py` (gen `arith`/
  `expr`), `cognia_x/train/provenance.py` + `provenance.jsonl`, `cognia_v3/training/kaggle/
  pretrain_hybrid_kaggle.py`, `tests/test_provenance.py`.
- **Planos hermanos:** `02_backbone_modelo.md` (config v1 + ramas A/B + G2), `00_READINESS.md`
  (G1/G2/G3), plano de verificador/lazo (el motor de datos consume su compuerta), plano de
  representación/tokenizer (migración byte→BPE; G3 RAG vs LoRA).

### Riesgo residual aceptado
La v1 puede entregar valor **solo por la PISTA-ADAPT** (Qwen+LoRA) si la PISTA-PRE (from-scratch a
escala) no rinde en el tiempo de GPU disponible. Es un resultado **honesto y entregable**: el sistema
(verificador + lazo + adapters por dominio) funciona sobre un base maduro mientras el sustrato propio
madura. El motor de datos y el ledger de procedencia sirven a AMBAS pistas sin cambios.

**Rama de fallback ARQUITECTÓNICA del sustrato (de 00_READINESS G1/G2, no inventada aquí).** PISTA-PRE
depende de DOS gates abiertos que este plano NO cierra: **G1** (que los kernels CPU de mezcla
lineal/SWA logren el ahorro de banda — **SIN verificar**; precedente exp007: int8 naive en numpy es
8-10× más lento, el ahorro de baja precisión/estado es de MEMORIA, no de cómputo, sin kernels
especializados) y **G2** (que alguna config híbrida cruce recall a la escala objetivo — abierto, ver
E2). Si G1/G2 no cierran, el `pretrain_hybrid_kaggle.py` puede pre-entrenar en su lugar la **rama de
fallback ya prevista por 00_READINESS: un Transformer denso pequeño con GQA + KV-cache 4-bit**,
maduro en llama.cpp HOY (mismo orquestador, mismo curriculum, mismo ledger — solo cambia la clase del
modelo en el kernel). Es decir: "PISTA-PRE no rinde" NO equivale a "solo queda Qwen+LoRA"; hay un
sustrato propio de respaldo con riesgo de banda menor. El curriculum, el motor de datos y el ledger
son **agnósticos a la arquitectura del backbone**.
