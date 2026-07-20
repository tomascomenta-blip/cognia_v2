# 11 — Plan maestro de build (milestones M0…M6, gates G1-G3, orden Apéndice A)

> **Propósito.** El **cronograma de ensamblaje** de Cognia-X v1: convierte los planos 01-09 (las
> cajas) en una **secuencia de milestones verificables** (M0…M6) con el orden que el lab **probó que
> paga** (Apéndice A: verificador → lazo de auto-mejora + guardia → expertos/routing). Para cada
> milestone fija: **objetivo, entregable concreto, DoD verificable (CLI real con `venv312`),
> dependencias, qué corre en CPU (i3) vs Kaggle GPU, esfuerzo honesto y criterio de salida/gate.**
> Cierra con el diagrama de dependencias entre milestones, la nota de que **M0 puede REDIRIGIR la
> arquitectura** (rama A híbrido vs B GQA denso) y la marca explícita de que **M1/M2 se empiezan EN
> PARALELO a M0**.

> **Anclaje de fuentes:** `00_READINESS.md` (GO CONDICIONADO; gates G1/G2/G3; Apéndice A;
> caveats SCALE=0% / R-VALOR / constantes confianza media), planos `01`–`09` (cajas + DoD por
> subsistema), `cognia_x/manager/ARQUITECTURA_OBJETIVO.md` (Apéndice A = orden que paga). Estado del
> lab al planificar: **CYCLE 155** (investigación toy SATURADA; la construcción es ahora el
> experimento de mayor valor). Fecha: 2026-06-28.

> **Reglas de honestidad de este plan (innegociables, método del lab):** cada afirmación marcada
> **PROBADO** (cita exp/CYCLE/archivo) / **ASUMIDO** (literatura/conjetura) / **PENDIENTE** (a medir).
> Confianza {alta/media/baja} en cada número clave. SCALE = 0% (todo validado en juguete; la
> transferencia a escala real es la mayor incógnita, confianza media). **Los esfuerzos en
> semanas-persona son CONJETURA (confianza baja):** no hay velocidad de equipo medida, un solo
> desarrollador CPU-first + cuota Kaggle escasa; son cotas de planificación, no compromisos.

---

## 0. Principios rectores del cronograma (qué gobierna el orden)

1. **El orden que el lab probó que paga es SOLO el esqueleto de 3 pasos** (Apéndice A, `00_READINESS`):
   **(1) verificador real-chequeable → (2) lazo de auto-mejora + guardia de diversidad → (3) jerarquía
   de expertos/routing.** La ubicación fina del resto (backbone, continual, dos núcleos) es
   **instanciación de este plan, NO probada por el lab** — confianza media en el ordenamiento detallado.
   No atribuir al Apéndice A más de lo que prueba.

2. **Regla anti-Goodhart de la dependencia (lección v4, `01 §3.8`):** NO construir M4/M5/M6 antes de
   que **M1 (verificador) tenga FP-rate medido < e\*** en el dominio objetivo. "Toda la orquestación
   rinde de forma COMPUESTA solo si el paso base es preciso y el verificador confiable"
   (`ARQUITECTURA_OBJETIVO.md`). Un verificador sin FP-rate medido convierte el lazo de auto-mejora en
   un motor de auto-degradación (plano 05 R3).

3. **CPU-first con frontera dura de entrenamiento.** El i3 (2c/4t, sin CUDA, 11.8 GB) hace **solo
   inferencia** (llama.cpp, techo MEDIDO ~8 tok/s 3B Q4_K_M, binario PINEADO b9391) + experimentos
   numpy/torch-cpu chicos. **Todo entrenamiento grande va a Kaggle GPU** (cuenta `anthuananthuan`
   configurada). QLoRA/4-bit están BLOQUEADOS en CPU.

4. **El sustrato ya corre.** `cognia_x/model/hybrid.py` (`HybridLM` tiny) está verificado HOY
   (`00_READINESS C4`: 1.56M params, forward+features+generate, entrena loss 5.56→2.03/30 pasos).
   **M1 y M2 se construyen sobre ESE tiny**, no sobre el backbone v1 (M3) — por eso pueden arrancar
   antes de cerrar la arquitectura (ver §M1/M2 y la nota de paralelismo).

5. **Nada de mocks/stubs.** Cada milestone cierra con **prueba CLI real** end-to-end (no solo pytest):
   "código que corre o no cuenta". Cada cierre se appendea a `MANAGER_LOG.md` (append-only).

---

## NOTA CRÍTICA — M0 puede REDIRIGIR la arquitectura (rama A vs rama B)

> **El backbone v1 (M3) NO está decidido hasta cerrar M0.** El gate **G1/A-018 (RIESGO P0)** decide
> entre dos ramas que el plano 02 mantiene **ambas armadas**:
>
> - **RAMA A — híbrido** (mayoría capas de mezcla lineal O(L) + minoría atención SWA + 1-2 globales).
>   Es el sustrato preferido **SI** los kernels CPU de llama.cpp entregan el ahorro de banda teórico.
>   **El ahorro está SIN VERIFICAR** (A-018). Precedente de que puede fallar: **exp007 midió int8
>   naïve en numpy 8-10× MÁS LENTO sin kernel especializado** — el ahorro de bytes no se materializa
>   solo. Además el `LinearAttention` de `hybrid.py` **no tiene kernel en llama.cpp** (ASUMIDO, no
>   verificado ejecutando): la RAMA A de producción exige re-expresar las capas lineales como
>   **Mamba-2/SSD o RWKV** (que sí tienen kernel GGUF) y **reentrenar**.
> - **RAMA B — fallback (madura en llama.cpp HOY):** Transformer **denso pequeño GQA + KV-cache 4-bit**.
>   Es exactamente la familia que los 6 GGUF Qwen2.5 locales corren HOY a ~8 tok/s. **Confianza alta**
>   (código maduro, no apuesta).
>
> **Implicación de cronograma:** M3 NO arranca su entrenamiento a escala hasta que M0 haya elegido
> rama **con número en mano**. Si G1 no se sostiene en CPU → RAMA B, **sin bloquear el build** (el
> resto del sistema — verificador, lazo, RAG, expertos — es **agnóstico a la arquitectura del
> backbone**; solo cambia la caja 02). La RAMA B es un resultado **honesto y entregable**, no una
> derrota: los checkpoints de embed/head/MLP/tokenizer se reutilizan y la migración a RAMA A queda
> abierta cuando el kernel CPU madure.

---

## NOTA CRÍTICA — M1 y M2 arrancan EN PARALELO a M0

> **M1 (verificador) y M2 (lazo) NO dependen del backbone final (M3).** Corren sobre el **`HybridLM`
> tiny que ya corre hoy** (d=64-128 byte-level) y sobre el **sandbox real de exp018** (que ya ejecuta):
> - Plano 04 §5.5: *"Todo este subsistema [verificador] corre en CPU (i3): es subprocess + parseo +
>   recuperación, no entrenamiento. Sin necesidad de GPU."*
> - Plano 05 §1.3: el lazo está demostrado-pequeño sobre `HybridLM` d=64 byte-level (exp016/034-039);
>   el bucle se **extrae** de `exp036.run_loop` a `cognia_x/selfimprove/` sin tocar el backbone v1.
>
> Por tanto, **mientras M0 corre sus spikes de validación de arquitectura, M1 puede empezar** (envolver
> el sandbox, FactVerifier, calibración, FP-rate gold). M2 sigue a M1 (dependencia dura: el lazo
> consume el verificador). Esto **paraleliza el camino crítico**: el orden Apéndice A (verificador →
> lazo) avanza en CPU sobre el tiny mientras la decisión de arquitectura (G1) madura en otro hilo. La
> **única sincronización** es M3↔M0 (la rama) y M5/M6 que esperan a M1+M2 sólidos.

---

## M0 — VALIDACIÓN (cierra los supuestos load-bearing; gates G1, G2, G3)

**Objetivo.** Cerrar los 3 gates que, si fallan, cambian la arquitectura v1, **antes** de comprometerla.
No es "más investigación": es la **primera fase de la construcción** (spikes de validación,
`00_READINESS §4`).

**Entregable concreto.**
- **G1 / A-018 (P0):** A/B "SWA vs atención full" en GGUF real en el i3, midiendo `tok/s(L)` +
  RSS de KV a `L∈{512, 2048, 8192, 16384}`. Requiere **bajar 1 GGUF SWA-nativo** (Gemma-2/3,
  Mistral-SWA o Phi-3) — los 6 GGUF locales son **todos Qwen2.5 = atención FULL** (bloqueo conocido).
  Telemetría de bytes/token implementada (`cognia_x/runs/telemetry.py`, plano 07 §3.6: captura
  `timings.predicted_per_second` + deriva `bytes_per_token(L)` desde `model_constants.py`).
- **G2 / fragilidad de recall:** barrido `ratio × arreglo × #globales` en `recall_task.py` con el load
  **escalado a la escala objetivo** (no el toy), sobre `v1-α` en CPU. Tabla recall-vs-coste de banda.
- **G3 / E4:** A/B de inyección de hechos **RAG doc-level vs LoRA vs kNN-LM(control negativo) vs
  full-FT(control negativo)** con N=M=50, midiendo `Δnew` / `Δbase`(olvido) / TTFT en el i3.
- **Higiene de gobernanza:** marcar STALE o sincronizar `hypotheses.md`/`assumptions.md`/
  `contradictions.md`/`future_work.md` (desfasados ~115 ciclos; los vivos son `research_log.md` +
  `decomposition_tree.md` + `STATUS_RVALOR.md`).

**DoD verificable (CLI real, `venv312`).**
- [ ] **G1 cerrado con número:** barrido `tok/s(L)` + RSS impreso desde `llama-server` real (b9391),
      contrastado con la predicción roofline (±15%). **Decisión RAMA A o RAMA B escrita explícitamente
      en `MANAGER_LOG.md`** con su telemetría. Umbral propuesto (recalibrable por M0, **no es del
      ledger**): RAMA A solo si a L=8192 el decode del operador recurrente/SWA ≤ 50% del coste del denso
      equivalente Y el KV-RAM se aplana en `W`.
- [ ] **G2 cerrado con número:** una config (ratio+arreglo+#globales) que **cruza el umbral de recall
      al load objetivo con el mínimo de atención**, documentada con su tabla recall-vs-coste.
- [ ] **G3 cerrado con número:** tabla `Δnew`/`Δbase`/TTFT por brazo; **política de inyección fijada por
      datos** (predicción a confirmar, no asumir: RAG → `Δbase≈0`; kNN-LM por-token descartado por TTFT).
- [ ] Telemetría `bytes_per_token(L)` reproduce el sanity de KV (plano 07: 36.0 KiB/token, 576 MiB @16k).

**Dependencias.** Tooling presente (✅): `venv312`, `node/llama-server.exe` b9391 + 6 GGUF,
`model_constants.py`, `recall_task.py`, `cognia_embedding.py`, `qlora_trainer.py` + pipeline Kaggle.
**Faltante (bloqueo de G1):** un GGUF SWA-nativo a bajar. **G3-LoRA** necesita 1 entreno en Kaggle.

**CPU (i3) vs Kaggle GPU.**
- **i3:** G1 (inferencia/telemetría pura), G2 (recall toy numpy/torch-cpu), G3-RAG/kNN/medición de
  inferencia. **Nada de esto entrena a escala.**
- **Kaggle:** solo el adapter LoRA de G3 (`train_qlora_kaggle.py`) y el full-FT de control.

**Esfuerzo honesto (CONJETURA, confianza baja):** ~3-6 semanas-persona. G1 es rápido (días) salvo la
descarga/compat del GGUF SWA; G2 es un barrido CPU (~1 semana); G3 cuesta más por el ciclo Kaggle
(cuota escasa). La higiene de gobernanza es ~1-2 días.

**Criterio de salida / gate.** M0 **completo** cuando los 3 gates tienen número y **G1 ha elegido rama
A o B**. Este es el gate que **habilita M3** (no M1/M2, que ya corren en paralelo). Si G1→RAMA B, M3
se simplifica (B es atención-mayoritaria, recall garantizado por construcción → G2 se vuelve trivial,
solo fija SWA-local vs denso).

> **Honestidad sobre G2 (no tratar el híbrido como knob de ratio afinable):** el techo de recall del
> mezclador de **estado fijo es ESTRUCTURAL** (pigeonhole sobre el estado, **exp002**), y los **6 levers
> no-atención están REFUTADOS** (ancho exp010; forma Taylor + init mimética exp011; profundidad/escala/
> optimizador exp012). A `d` chico / carga alta el híbrido **naive interleaved platea ~0.18**
> (exp014/015); **solo la atención pura cruza** (0.88-0.95, exp013). **El remedio es ARQUITECTÓNICO =
> atención.** G2 puede por tanto **subir la cuota de atención / ensanchar W / agregar capas globales** —
> no es "afinar un número 3:1". Si ninguna config híbrida cruza sin volverse atención-mayoritaria → la
> ventaja de banda se evapora → RAMA B (que también es atención plena). **PROBADO el riesgo; PENDIENTE
> la resolución a escala.**

---

## M1 — VERIFICADOR real-chequeable (plano 04) — la pieza de 1ra clase, PRIMERO

**Objetivo.** Construir la infraestructura de **verificadores por dominio** que deciden de forma
*chequeable* (ejecutando/calculando/corroborando, **nunca opinando**) si un candidato es correcto, con
**FP-rate medido < e\*** y **abstención calibrada**. El lever dominante de todo el sistema es la
**CALIDAD** del verificador.

**Entregable concreto.** `cognia_x/verify/` con: `base.py` (`VerifyResult`, protocolo `Verifier`),
`registry.py` (dispatcher + abstención de sistema), `code_verifier.py` (**envuelve** el sandbox que ya
corre: `cognia_v3/interfaces/code_executor.py` + `cognia_v3/core/sandbox_tester.py`, sin reimplementar),
`closed_form_verifier.py` (**porta** `interpret()` de exp018, sin `eval`), `fact_verifier.py`
(redundancia ≥2 fuentes, **diseño nuevo sin exp propio**), `calibration.py` (isotónica/Platt + ECE),
`config.py`. Experimentos de medición de FP-rate A-V1…A-V4 sobre *gold* disjunto.

**DoD verificable (CLI real, `venv312`).**
- [ ] Los 3 verificadores corren sobre 3-5 candidatos de muestra con **output real mostrado**
      (`VerifyResult` + evidencia), incl. **caso de timeout real** (loop infinito → `ok=False`) y
      **import bloqueado** (`import os; os.system(...)` → `ok=False`).
- [ ] **FP-rate medido y reportado por dominio** sobre *gold* etiquetado **disjunto** del lazo (A-V1/
      A-V4); existe τ que da **FP-efectivo < e\*** con cobertura reportada (A-V2).
- [ ] **Gate NO circular demostrado** (A-V3): medición sobre holdout disjunto; persistencia vía
      `storage/db_pool.py` (sin `sqlite3.connect` directo) o JSON append-only, **separada** de la memoria
      auto-escrita (defensa H-SELF-2).
- [ ] `CodeVerifier.ok` cuelga de **"la suite de tests pasó"** (señal positiva), NO de `success`
      (que exige stdout — trampa real cazada en `sandbox_tester.py §2.1`).
- [ ] Test de regresión por verificador (falla sin fix / pasa con fix); suite dirigida verde
      (`venv312\Scripts\python.exe -m pytest cognia_x/verify/tests -q`, reportar N passed/M failed).

**Dependencias.** Existentes (✅): `code_executor.py`, `sandbox_tester.py`, `exp018/expression_task.py`,
`venv312`. **De M4 (no bloqueante para los 2 primeros verificadores):** el `FactVerifier` consume el
índice RAG doc-level (plano 06) — puede quedar como segunda ola dentro de M1 o sincronizarse con M4.

**CPU (i3) vs Kaggle GPU.** **100% CPU** (subprocess + parseo + recuperación). **Nada va a Kaggle**:
el verificador no entrena. Por eso M1 **arranca en paralelo a M0** sobre el tiny + sandbox actuales.

**Esfuerzo honesto (CONJETURA, confianza baja):** ~4-8 semanas-persona. `CodeVerifier` y
`ClosedFormVerifier` son **construibles sobre código que ya corre** (rápido). El `FactVerifier` es
**diseño nuevo sin exp propio** (más lento, arrastra el riesgo estructural del error sistemático de
corpus). La calibración + los 4 experimentos de gold son el grueso.

**Criterio de salida / gate.** M1 **completo** cuando hay **al menos un verificador (código o forma
cerrada) con FP-rate medido < e\* sobre gold disjunto**. Este es el **gate bloqueante de M2 y de toda
la fase posterior** (regla anti-Goodhart, principio 2): sin él, no se enciende el lazo.

> **Honestidad sobre el reward-hack (CAZADO):** **exp019 (H-LEARN-4) y exp020 (H-LEARN-5) están
> REFUTADAS en el ledger** — NO son evidencia de apoyo. exp019: el verificador débil **NO se hackeó
> aun con el atajo sembrado**; exp020: RL-maximización **NO se separó de imitación** (GRPO-lite tiny
> inestable). Por tanto: la defensa anti-reward-hack (cobertura/held-out "strong") y la elección de
> **imitación sobre RL** son **precaución de diseño (literatura RL + exp017 dose-response)**, **NO un
> resultado medido del lab**. El motor del verificador se sostiene en **exp017 + exp018 (ambas
> APOYADAS)**, no en exp019/020. La eficacia del "strong"/held-out contra el hack se **mide en A-V1**,
> no se asume.

---

## M2 — LAZO de auto-mejora STaR + guardia de diversidad (plano 05) — SEGUNDO

**Objetivo.** Empaquetar el motor *act → verify → keep → retrain* que evoluciona el sustrato desde sus
propias salidas **verificadas**, con la **guardia de diversidad OBLIGATORIA** (dedup + replay limpio) y
un **gate NO circular** (held-out rotativo + committee + rollback por snapshot). El lazo **consume** el
verificador de M1; no lo reimplementa.

**Entregable concreto.** `cognia_x/selfimprove/` con: `loop.py` (bucle, **extraído** de
`exp036.run_loop` generalizando el oráculo a `VerifierRegistry.verify()`), `guard.py` (dedup + replay
semilla-verdad), `gate.py` (`NonCircularGate`), `monitor.py` (diversidad/cobertura/yield + alarmas),
`config.py`. Experimentos A-L1…A-L5 (réplica empaquetada, guardia ablada, FP-sweep, gate no-circular,
multi-paso).

**DoD verificable (CLI real, `venv312`).**
- [ ] **Bootstrap medible sin colapso** (el DoD nuclear): sobre la tarea con verificador real de M1,
      base débil → techo, `non_decreasing`, `plateaus=True`, `collapses=False`, cobertura no cae
      (réplica de exp037/038: base 0.081→0.933 en el toy — **prueba de concepto, no garantía a escala**).
- [ ] **Guardia OBLIGATORIA activa por defecto**; ablación A-L2 reproduce `plain_narrows / guard_keeps /
      no_prec_cost` (exp036).
- [ ] **e\* medido por dominio** (A-L3): `guard_raises_eps_star=True`; el lazo **solo se habilita donde
      M1 garantiza FP < e\*_medido** (no se hereda el 0.50 del toy; se mide).
- [ ] **Gate no-circular demostrado** (A-L4): regresión plantada (verificador con FP alto deliberado) →
      ronda **revertida** (`reverted=True`) + alarma del monitor; el lazo **no avanza a un estado peor**.
- [ ] Corrida completa con output por ronda (`step, cov, div, n_verified, gate, reverted`) + **caso de
      colapso forzado** (FP=0.6) que dispara rollback. Tests de regresión (sin-guardia→narrowing falla /
      con-guardia pasa; sin-gate→avanza-peor falla / con-gate pasa).

**Dependencias.** **DURA: M1** (el lazo no construye sin un verificador con FP-rate medido < e\* — la
dependencia bloqueante). Existentes (✅): `exp016/exp018` (`build_base/generate_pool/train_arm`),
`hybrid.py` tiny.

**CPU (i3) vs Kaggle GPU.**
- **i3:** todo el lazo toy + A-L1…A-L5 (numpy/torch-cpu in-place, `torch.set_num_threads(3)`).
- **Kaggle:** **solo** el paso "re-entrenar a escala real" se vuelve **fine-tune de adapter LoRA sobre
  las salidas verificadas** (los nodos no entrenan; restricción dura). El lazo a escala es **asíncrono
  por rondas**: generar+verificar en CPU → exportar set verificado → entrenar adapter en Kaggle →
  re-importar. **NO medido aún** (ASUMIDO, R1/R7).

**Esfuerzo honesto (CONJETURA, confianza baja):** ~4-8 semanas-persona. El algoritmo está
**demostrado de punta a punta en pequeño** (extraer, no inventar); el grueso es el gate no-circular
robusto, el monitor con alarmas y los 5 experimentos. La asincronía CPU↔Kaggle a escala es el riesgo.

**Criterio de salida / gate.** M2 **completo** cuando el bootstrap empaquetado reproduce el DoD nuclear
(base débil → techo, plateau, sin colapso) con el verificador **real de M1** y el gate no-circular
revierte una regresión plantada. **Rama de fallback honesta (plano 05 §7.3):** si el lazo iterado no
bootstrappea a escala (R1), o la asincronía/throughput es prohibitiva (R7/R10), **degradar a fine-tune
por lotes OFFLINE** (curar un set verificado una vez, entrenar el adapter, evaluar con el mismo gate,
desplegar sin lazo iterado). **El sistema sigue útil sin auto-mejora** (GGUF base + verificador-gate +
RAG): la auto-mejora iterada es una **mejora opcional sobre un sistema que ya funciona**, no un
prerequisito.

---

## M3 — BACKBONE v1 (plano 02) — rama A o B según G1

**Objetivo.** Entrenar el sustrato de secuencia v1 (la caja 02), en la **rama que M0/G1 eligió**, con el
tokenizer BPE byte-fallback 32k, el ratio/arreglo que G2 fijó, y la cuantización Q4_K_M de producción.

**Entregable concreto.**
- **Tokenizer** BPE byte-fallback `vocab=32768` parity-aware (sentencepiece/HF tokenizers), entrenado
  una vez en CPU sobre el corpus es/multilingüe (`cognia_x/data/corpus/`, ~17 MB).
- **Kernel de pre-entreno** `cognia_v3/training/kaggle/pretrain_hybrid_kaggle.py` (NUEVO, **agnóstico a
  la rama**: instancia `HybridLM` RAMA A o el denso GQA RAMA B según parámetro) + reutilizar el
  orquestador `run_kaggle_training.py`.
- **Curriculum** L→R→V→STaR (plano 03 §3.1) + **ledger de procedencia** `cognia_x/train/provenance.py`
  + `verifiable_tasks.py` (generadores deterministas `arith`/`expr`).
- Checkpoint bf16 → conversión GGUF Q4_K_M → inferencia en i3 (+ KV-cache q4_0 en RAMA B).
- **Gaps de implementación cerrados:** G-1 (añadir GQA a `SlidingWindowAttention`), G-2 (schedule de
  ventana por capa: `effective_window`/`global_layers`).

**DoD verificable (CLI real, `venv312`).**
- [ ] **Config v1 fijada** (`v1-α` bring-up + `v1` objetivo) con `num_params()` reportado y
      `forward`/`generate` corriendo (extiende el smoke de C4).
- [ ] **Bifurcación A/B decidida con número** (de M0/G1) y registrada; la rama elegida entrena.
- [ ] **Tokenizer 32k** conmutado; la v1 entrena con él; **PPL-por-byte ≤ baseline char-LM v0** a
      igualdad de FLOPs.
- [ ] **GGUF Q4_K_M** de la rama elegida corre en el i3 con **tok/s ≥ 8** (baseline 3B) a decode corto y
      `bytes/token(L)` reportado (telemetría de M0/plano 07).
- [ ] Gaps con test de regresión: **G-1 mide recall GQA vs MHA** (si GQA degrada — hipótesis, no hecho —
      aplicar "MHA/más KV heads en las capas globales load-bearing"); **G-2** `effective_window`/
      `global_layers` no rompen `forward`/`generate`.
- [ ] Suite completa como última compuerta (reportar N passed/M failed con `venv312`).

**Dependencias.** **DURA: M0/G1** (elige rama) **+ G2** (fija ratio/arreglo). Existentes (✅):
`hybrid.py`, `charlm.py`, `recall_task.py`, `run_overnight.py`, pipeline Kaggle. **Faltante:** el kernel
de pre-entreno (nuevo), el tokenizer, `provenance.py`, `verifiable_tasks.py`.

**CPU (i3) vs Kaggle GPU.**
- **i3:** smoke del pipeline (`run_overnight --smoke`, compuerta 0 antes de gastar cuota), tokenizer,
  generadores `arith`/`expr`, telemetría, inferencia del GGUF resultante.
- **Kaggle GPU (T4):** **todo el pre-entreno a escala** (el i3 NO entrena a escala). T4 = Turing → AMP
  **fp16** (sin bf16). Atención al detalle real: el backend Kaggle **ignora `enable_gpu` sin
  `machine_shape="NvidiaTeslaT4"`** (lección verbatim en `run_kaggle_training.py`).

**Esfuerzo honesto (CONJETURA, confianza baja-MUY baja):** ~8-16 semanas-persona. **Es el milestone más
caro y de mayor incógnita (SCALE = 0%).** Que el `HybridLM` pre-entrenado en GPU a tamaño v1 transfiera
las propiedades del toy (1.56M params CPU) es la mayor incógnita del proyecto. El motor de datos STaR es
**caro y de bajo yield** (corrida real: 8 pares aceptados/20 generados en ~4.1 h GPU). La cuota Kaggle es
escasa (ASUMIDO ~30 h/sem, confianza media).

**Criterio de salida / gate.** M3 **completo** cuando la `v1` (rama elegida) entrena, convierte a GGUF
Q4_K_M y corre en el i3 a tok/s ≥ baseline con telemetría reportada. **Rama de fallback (plano 03 §7):**
la v1 puede entregar valor **solo por la PISTA-ADAPT** (Qwen2.5 + LoRA, maduro) si la PISTA-PRE
(from-scratch a escala) no rinde en el tiempo de GPU disponible — resultado honesto y entregable; el
sistema (verificador + lazo + adapters por dominio) funciona sobre un base maduro mientras el sustrato
propio madura.

> **Honestidad sobre cuantización (CAZADO):** **Q4_K_M es la base de producción HOY** (A/B ganado en el
> i3: decode 8.09/prefill 29.3 tok/s vs Q4_0). El **ternario b1.58 es solo I+D NO decidido**: **H-BIT-1
> holds=false** (los 2-6× de bitnet.cpp son kernel-vs-kernel; BitNet-2B4T pierde ~12% MMLU vs
> Qwen2.5-1.5B) y **H-LUT-1 holds=false** (T-MAC usa registros/L1, no transfiere al patrón del i3). El
> ternario **NO entra en v1**; queda como experimento gated si aparece un kernel CPU que lo realice sin
> pérdida de calidad a 1-3B. La única baja-precisión adicional de v1 es **KV-cache q4_0** (RAMA B, madura).

---

## M4 — APRENDIZAJE CONTINUO (plano 06): RAG doc-level + LoRA r≤16 + FedEx-LoRA

**Objetivo.** Triple capa de aprendizaje continuo con **cero olvido por construcción** en la capa barata
(RAG) y **olvido acotado** en las caras (LoRA): inyectar hechos nuevos sin degradar lo que ya sabía. Y
**corregir el bug REAL de agregación federada** antes de usar la banda federada.

**Entregable concreto.**
- `cognia_x/continual/rag_index.py` (RAG doc-level, 1 recuperación/consulta, base congelada; reusa
  `cognia_embedding` + `db_pool`; `remove()` para olvido explícito/RGPD).
- **Corrección de `coordinator/federated_store.py`** (Pass 3, líneas 316-329): reemplazar el **FedAvg
  naïve** `avg(B)@avg(A)` por **FedEx-LoRA `avg(B@A)` + SVD truncado a r'**. Migrar a `db_pool`.
- `cognia_x/continual/band_router.py` (router de 3 bandas LOCAL/MEDIA/GLOBAL, **sobre** el routing de
  dominios `DOMAIN_EXPERT_CLUSTERS`), `adapter_fusion.py` (fusión intra-cuenca sobre deltas
  reconstruidas).
- **Puente `npz → GGUF-LoRA`** (riesgo P1, plano 06 §6.8): el adapter federado (`npz` k,v) NO es el
  formato que `llama.cpp` carga (`LLAMA_LORA_PATH`) — sin este puente la federación produce adapters que
  no se pueden correr.
- **Decisión de contrato de adapter** q,k,v,o vs k,v (riesgo P1, plano 06 §3.2).

**DoD verificable (CLI real, `venv312`).**
- [ ] **Corrección federada como test de regresión:** **reusar exp003** — tras el fix, el `rel_error`
      heterogéneo baja de **0.10-0.66 a ~0** (salvo el truncado SVD declarado) y el rango efectivo
      recupera K·r en vez de colapsar a r. **Test que falla con el bug y pasa con el fix.**
- [ ] `rag_index` corre: indexar 50 docs, recuperar top-4 por coseno, output real mostrado.
- [ ] **Gate G3/E4 corrido** (puede heredarse de M0): tabla `Δnew`/`Δbase`/TTFT por brazo; política de
      inyección fijada por datos.
- [ ] **DoD de negocio:** N=50 hechos nuevos inyectados, `new_acc` ↑ a umbral acordado con **`|Δbase| ≤
      1%`** (el 1% es PROPUESTO, no medido; calibrar contra el ruido de `base_acc` — con N=50, 1%≈0.5
      ítems cae bajo la resolución del test), medido con CLI real sobre Qwen2.5-Coder-3B Q4_K_M en el i3.
- [ ] **Puente federado→inferencia demostrado:** convertir un `npz` federado a LoRA cargable y mostrar
      **generación real en el i3** con la banda GLOBAL activa.

**Dependencias.** **Bloqueantes:** M1 (sus 2 primeros verificadores: código/forma-cerrada), M3 (backbone que
consume el bloque RAG y carga adapters). **Carve-out de la circularidad M1↔M4:** el `FactVerifier` (M1)
consume el índice RAG doc-level (M4) → **se co-desarrolla con M4**, no lo bloquea (M1 cierra con código/
forma-cerrada; el FactVerifier es segunda ola, sincronizada con M4). Infra que ya corre (reusar): `cognia_embedding`,
`conversation_memory`, `db_pool`, `qlora_trainer` + pipeline Kaggle, `federated_store`,
`model_constants`.

**CPU (i3) vs Kaggle GPU.** **i3:** RAG, fusión, agregación federada (numpy puro, determinista), medición
de inferencia. **Kaggle GPU:** entrenamiento de los adapters LoRA (el i3 NO entrena QLoRA).

**Esfuerzo honesto (CONJETURA, confianza baja):** ~6-12 semanas-persona. La corrección federada es
**acotada y de alto valor** (el archivo YA sabe reconstruir la delta, `_effective_delta_embed` — solo
hay que mover esa reconstrucción al camino de agregación). El RAG reusa infra que corre. El puente
`npz→GGUF-LoRA` y el contrato de adapter son los riesgos de integración.

**Criterio de salida / gate.** M4 **completo** cuando: (a) la agregación federada corregida pasa el test
de regresión exp003 (`rel_error ~0`); (b) la política de inyección está fijada por datos (G3); (c) se
inyectan N=50 hechos con olvido acotado, medido con CLI real. **Rama de fallback (plano 06 §6.9):** si E4
muestra que el RAG en el i3 (modo n-gramas, sin all-MiniLM) no alcanza `Δnew` útil, la política de hechos
cae a **LoRA-para-hechos** dentro del presupuesto `|Δbase|` (al costo de perder el olvido explícito RGPD).

> **Honestidad sobre el federado (CAZADO):** **SOLO FedEx-LoRA / `avg(B@A)` sobre adapters LoRA, NUNCA
> params base ni FedAvg naïve.** El error del naïve está **MEDIDO** (exp003: 0.43%→65.7% con
> heterogeneidad; colapsa el rango K·r→r), y bajo el **ruido DP que Cognia exige (`sigma=0.01`) se vuelve
> cuadrático** → la corrección importa MÁS con privacidad. El bug naïve **existe HOY** en
> `federated_store.py` (Pass 3) y **debe corregirse ANTES** de usar la banda federada. **Ruido DP en el
> cliente, cero datos personales centralizados.**

---

## M5 — EXPERTOS jerárquicos + routing (plano 08) — fase TARDÍA (CYCLE 47)

**Objetivo.** Jerarquía de expertos (N1 general / N2 sub / N3 micro) como **adapters LoRA por dominio**
(NO MoE token-por-token), **seleccionados por PLAN** (1 decisión/consulta), con coordinación **no-regret**
que estima la fiabilidad del verificador sin ground-truth. **DoD central: añadir/actualizar un experto
sin reentrenar todo.**

**Entregable concreto.** `cognia_x/experts/` con: `registry.py` (`Expert(expert_id, level, parent_id,
domain_cluster, adapter_path, basin_id, …)`, herencia del padre cuando `adapter_path=None`),
`director.py` (**reusa el bandit de `reason/router.py`** con `mode="verifier"` y `unsure_margin`/
presupuesto, cambiando el espacio de acciones de cadenas→adapters), `blackboard.py` (interfaz de pizarra,
PENDIENTE, no bloquea el DoD central). Coordinación adaptativa test-retest (exp029).

**DoD verificable (CLI real, `venv312`).**
- [ ] **DoD de modularidad (el central):** añadir un experto NUEVO (adapter entrenado en Kaggle +
      registro) **sin reentrenar el base ni los demás adapters**; el director lo selecciona en su dominio
      (`LLAMA_LORA_PATH`→`--lora`), **sube accuracy en ese dominio y `|Δaccuracy|≈0` en los otros**.
      Medido con CLI real sobre Qwen2.5-Coder-3B Q4_K_M en el i3.
- [ ] **Coordinación no-regret (V1):** la mezcla adaptativa test-retest sobre **verificador real (M1)**
      cumple `ADAPT ≥ max(componentes) − 0.02` y `r` monótona; `test_cycle43_adaptive_allocation.py` sigue
      4/4 (test de regresión). Tabla `CONSEC_V/CONSEC_FREE/ADAPT(r)` real reportada.
- [ ] **Anti-circularidad verificada:** el director usa `mode="verifier"` (no `confidence`); test que
      muestra que `confidence` es secuestrado por el "fanfarrón" (replica CYCLE 12) y `verifier` no.
- [ ] Suite rápida verde (`pytest tests/ --ignore=tests/test_e2e_inference.py -q`).

**Dependencias.** **Bloqueantes (orden Apéndice A):** M1 (verificador — el director lo CONSUME como
recompensa y para test-retest) y M2 (lazo — genera los datos con que se entrenan los expertos). 08 **no
se construye antes** de 04 y 05. **De diseño (reusar):** M4 (formato/rango del adapter, fusión, agregación
federada correcta, router de bandas), M3 (backbone que carga el adapter). Infra que corre: `reason/router.py`,
exp029/086/098, `DOMAIN_EXPERT_CLUSTERS`, `qlora_trainer`, `_lora_args()`.

**CPU (i3) vs Kaggle GPU.** **i3:** coordinación/router/director/medición (verificador = sandbox, numpy).
**Kaggle GPU:** entrenamiento de los adapters. El i3 carga **un adapter a la vez** (limitación física de
RAM; no es MoE multi-experto en una pasada, es adapter-switching por plan).

**Esfuerzo honesto (CONJETURA, confianza baja):** ~4-8 semanas-persona. La coordinación no-regret está
**probada en toy** (exp029, `worst_regret=+0.008`) y el `Router` ya implementa el patrón del director (el
trabajo es cambiar el espacio de acciones + componer la jerarquía, no inventar el mecanismo). La pizarra/
comunicación-por-necesidad son interfaces, no implementación.

**Criterio de salida / gate.** M5 **completo** cuando el DoD de modularidad pasa (experto nuevo sin
reentrenar el resto) y la coordinación no-regret se confirma sobre el verificador real. **Control negativo
declarado:** si el adapter-por-plan ≈ base sola (V2), el routing **no paga** → confirma CYCLE 47 y se
**congela la fase** (su valor es modularidad, no capacidad).

> **Honestidad sobre la prioridad (CAZADO):** el propio lab concluyó en **CYCLE 47 (giro estratégico)**
> que **el routing NO es el cuello de botella** — *"el próximo lever es el SUSTRATO, no más orquestación"*.
> Esta fase es **TARDÍA por diseño**: vale **poco** sobre un sustrato impreciso o un verificador no
> confiable, y rinde de forma compuesta solo cuando M1/M2/M3 están sólidos. Su justificación de existir es
> **modularidad** (añadir dominios sin reentrenar), NO un salto de capacidad por routing. La **jerarquía
> N1/N2/N3 de dominio, la pizarra y la comunicación-por-necesidad están PENDIENTES** (no demostradas ni en
> pequeño); lo demostrado (CYCLE 12-21) es ruteo de **cadenas de razonamiento**, no de expertos de dominio.

---

## M6 — INTEGRACIÓN dos núcleos razonamiento↔comunicación (plano 09) + meta-razonamiento + hipótesis

**Objetivo.** Ensamblar el lado cognitivo: la **separación física en dos núcleos** (razonador produce
ideas verificadas, comunicador las expresa), el lazo planificador-rápido→verificador-profundo→re-plan, el
**router de meta-razonamiento** (ya corre, CYCLE 12-21), el **engine de hipótesis** (ya en código, CYCLE
22) y la **auto-evaluación + abstención calibrada**. **DoD: un razonamiento multi-paso verificado
end-to-end con comunicación desacoplada.**

**Entregable concreto.** `cognia_x/reasoncore/` (config + orquestación) que: **envuelve** `reason/Router`
para un LLM real (estrategias de un GGUF chico + `verify()` real en vez de solvers de juguete + oráculo
perfecto); **conecta** `research/HypothesisRegistry` (una idea no verificable de un tiro → se **registra**
como hipótesis exploratoria, no se afirma); implementa la **frontera de núcleos** (`ReasoningTrace`
verificado y mínimo cruza al comunicador; el comunicador **no lee el scratchpad**, **no razona**, **no
fabrica citas**). Separación arranca **conservadora** (`single_model_two_modes`) → sube a
`two_lora_adapters` si hay filtración.

**DoD verificable (CLI real, `venv312`).**
- [ ] **A-RC5 (DoD central):** una consulta atraviesa planificador → meta-router → candidato →
      `verify()` real → `ReasoningTrace{checked=True}` → comunicador → `Response` con `citations` derivadas
      de `evidence`. **Output real**, con CHECK de los 3 puntos: (a) cita la evidencia del verificador;
      (b) ante candidato **no verificado** (`checked=False`) el comunicador **abstiene** ("no estoy
      seguro…"), no afirma; (c) el comunicador **no accedió al scratchpad** (auditado).
- [ ] **A-RC3 (meta-router sobre LLM real):** `mode="verifier"` supera a la mejor estrategia fija en
      held-out; `mode="confidence"` colapsa (replica anti-Goodhart, cierra el `Frontier` de
      `reason/README.md`).
- [ ] **A-RC2 (engine de hipótesis):** `mark_supported/refuted/mixta` **lanzan `PrematureVerdictError`**
      sin el DoD completo y pasan con él; `EvidenceLedger.record_decision` **lanza `OpinionOnlyError`** con
      solo fuentes tier-6.
- [ ] **A-RC6 (no-filtración de núcleos):** un razonamiento incorrecto-pero-fluido NO sale como
      afirmación correcta; `checked` gobierna el modo del comunicador.
- [ ] Suite dirigida verde (`pytest cognia_x/tests/ -k "reason or hypoth" -q`, ~21 passed del meta-router).

**Dependencias.** **Bloqueantes (orden Apéndice A):** M1 (`verify()` real con FP-rate medido < e\* —
PRIMERO), M2 (lazo STaR para la internalización A-RC7), M3 (backbone como sustrato de ambos núcleos).
Contratos `Plan`/`VerifiedPlan`/`ExpertTask` de `01 §3.2`. Existentes (✅): `reason/` (router/composer/
supervised_router), `research/` (hypotheses/ledger/schema/record), GGUF chico 0.5B local.

**CPU (i3) vs Kaggle GPU.** **i3:** todo el andamiaje (meta-router bandit, engine de hipótesis, lazo
plan→verify→replan, abstención, comunicación) — solvers/registros/parseo + GGUF chico. **Kaggle GPU:**
**solo** la internalización (A-RC7: destilar el router a un *prior* en los pesos vía imitación/STaR),
porque entrena pesos. **Es mejora de sustrato, no requisito del v1 mínimo.**

**Esfuerzo honesto (CONJETURA, confianza baja):** ~6-12 semanas-persona. El meta-router y el engine de
hipótesis son **código que ya corre** (envolver, no inventar); el grueso es el envoltorio para LLM real,
la frontera de núcleos auditada y la internalización (Kaggle). La separación física de núcleos y la
internalización son **PENDIENTES sin exp propio** (confianza media-baja).

**Criterio de salida / gate.** M6 **completo** cuando A-RC5 pasa (razonamiento multi-paso verificado con
comunicación desacoplada, output real) con el verificador de M1. La internalización (A-RC7) es **opcional**:
si la destilación no transfiere, el andamiaje externo es un **fallback funcional** (no bloquea el v1, solo
el "mejor sustrato").

> **Honestidad sobre internalización e imitación-vs-RL (CAZADO):** el eje conceptual es **"verificación
> SIEMPRE externa (no se internaliza nunca = sería auto-recompensa circular H-SELF-2), generación/propuesta
> destilable a los pesos"**. La internalización usa **imitación/STaR, NO RL**. PERO el contrapunto "RL
> hackea más que imitación" **NO está demostrado in-lab**: **exp019/exp020 (H-LEARN-4/5) están REFUTADAS**
> (null de método — GRPO-lite tiny inestable/colapsa el modelo). La elección imitación-sobre-RL se apoya
> **solo en literatura (Amodei) + la asimetría estructural + que el RL colapsó el modelo tiny en CPU** — NO
> citar exp019/020 como APOYO.

> **Honestidad transversal sobre R-VALOR (CAZADO):** `value_signal` en `ReasoningTrace` y la abstención
> usan R-VALOR como **BRÚJULA DECISIONAL acotada** (asignación/abstención bajo escasez), **NO como
> acelerador de loss**. El arco downstream **149-155 cerró del lado RANKING**: el residuo del lazo real es
> **discriminación, no calibración**; la tesis 123 (la calibración paga en la decisión bajo escasez) sigue
> **intacta pero NO confirmada en el lazo real** (sólida solo en toy/oráculo). Usar para ordenar/abstener,
> **nunca** sobre-apoyarse.

---

## Diagrama de dependencias entre milestones (ASCII)

```
        ┌──────────────────────────────────────────────────────────────┐
        │  SUSTRATO QUE CORRE HOY (00_READINESS C4):                     │
        │  HybridLM tiny (d=64-128) + sandbox exp018 + venv312 + b9391   │
        └───────────────┬───────────────────────────────┬──────────────┘
                        │                                │
        ┌───────────────┘                                └───────────────┐
        ▼                                                                ▼
 ┌──────────────────┐                                      ┌──────────────────────┐
 │ M0  VALIDACIÓN   │   (REDIRIGE la arquitectura)          │ M1  VERIFICADOR (04) │  ◀── arranca EN
 │  G1 A-018 (P0) ──┼──▶ elige RAMA A (híb) / RAMA B (GQA)   │  FP-rate < e* medido │      PARALELO a M0
 │  G2 recall híb.  │                                       │  (100% CPU, tiny)    │      (no depende
 │  G3 E4 (RAG/LoRA)│                                       └──────────┬───────────┘      del backbone)
 └────────┬─────────┘                                                  │
          │ G1 (rama) + G2 (ratio)                                     ▼ (dep. DURA: gate
          │                                                ┌──────────────────────┐  anti-Goodhart)
          ▼                                                │ M2  LAZO STaR (05)    │  ◀── sigue a M1;
 ┌──────────────────┐                                      │  + guardia diversidad │      ∥ a M0
 │ M3  BACKBONE v1  │◀── G1/G2 deciden la caja 02           │  + gate no-circular   │
 │  (02, rama A/B)  │    (resto del sistema es AGNÓSTICO    │  (CPU; train→Kaggle)  │
 │  tokenizer 32k   │     a la rama)                        └──────────┬───────────┘
 │  Kaggle GPU      │                                                  │
 └────────┬─────────┘                                                  │
          │                                                            │
          ├──────────────────────┐                                    │
          ▼                       │ (G3 fija política)                 │
 ┌──────────────────┐            │                                     │
 │ M4  CONTINUO (06)│◀───────────┘  + M1 (FactVerifier filtra docs)    │
 │  RAG doc-level   │                                                  │
 │  LoRA r<=16      │                                                  │
 │  FedEx-LoRA fix  │  (corrige el bug naive ANTES de usar)            │
 └────────┬─────────┘                                                  │
          │                                                            │
          ▼                                                            │
 ┌──────────────────┐                                                  │
 │ M5  EXPERTOS (08)│◀──── M1 + M2 (orden Apéndice A) ──────────────────┤
 │  LoRA por dominio│      (FASE TARDÍA — CYCLE 47: routing NO es el    │
 │  director/no-reg.│       lever; valor = modularidad)                │
 └────────┬─────────┘                                                  │
          ▼                                                            │
 ┌─────────────────────────────────────────────────┐                  │
 │ M6  DOS NÚCLEOS (09) + meta-razonam. + hipótesis │◀─────────────────┘
 │  razonador↔comunicador; verificación SIEMPRE     │   (dep. DURA: M1 + M2 + M3)
 │  externa, generación destilable (imitación/STaR) │
 └─────────────────────────────────────────────────┘

LEYENDA de dependencias:
  ──▶  "depende de / se construye encima de"
  ∥    M0, M1 y (tras M1) M2 avanzan EN PARALELO sobre el tiny que ya corre.
  Camino crítico Apéndice A:  M1 → M2 → {M5, M6}.   Camino de arquitectura:  M0/G1 → M3 → M4.
  Sincronización: M3 espera la RAMA de M0; M4/M5/M6 esperan FP-rate<e* de M1 (regla anti-Goodhart).
```

---

## Resumen de gates y criterios de salida

| Milestone | Gate de salida (verificable, CLI real) | Habilita |
|---|---|---|
| **M0** | G1 con número → **RAMA A o B elegida**; G2 config de recall fija; G3 política de inyección fijada | **M3** (arquitectura) |
| **M1** | ≥1 verificador con **FP-rate medido < e\*** sobre gold disjunto; gate no-circular | **M2, M4, M5, M6** (bloqueante) |
| **M2** | Bootstrap base-débil→techo sin colapso con verificador real; rollback revierte regresión plantada | **M5, M6** |
| **M3** | `v1` (rama elegida) entrena → GGUF Q4_K_M corre en i3 a tok/s ≥ 8 con telemetría | **M4, M6** |
| **M4** | Agregación federada corregida (`rel_error~0`, test exp003); N=50 hechos con `\|Δbase\|≤1%` | **M5** |
| **M5** | Experto nuevo sin reentrenar el resto; coordinación no-regret sobre verificador real | **M6** (expertos) |
| **M6** | Razonamiento multi-paso verificado end-to-end con comunicación desacoplada (A-RC5) | **v1 cognitivo** |

---

## Riesgos del cronograma (transversales, honestos)

| # | Riesgo | Sev. | Estado | Mitigación |
|---|---|---|---|---|
| RM1 | **SCALE = 0% (P0).** Todo el thesis está validado en juguete (numpy + HybridLM tiny ≤1.56M). La transferencia a 1.3B real es la mayor incógnita; afecta sobre todo M3. | Alta | ASUMIDO | M0 + telemetría fijan constantes; `v1-α` de bring-up antes de la `v1`; PISTA-ADAPT (Qwen+LoRA) como fallback de valor inmediato. Confianza media. |
| RM2 | **G1/A-018 falla** (kernels SSM/SWA CPU inmaduros; exp007: int8 naïve 8-10× más lento). | Alta | PROBADO el riesgo | **RAMA B (GQA denso + KV-4bit) ya armada**; M3 cambia solo la caja 02; el resto es agnóstico. No bloquea el build. |
| RM3 | **Recall híbrido no cruza a escala** (techo ESTRUCTURAL exp002; 6 levers no-atención refutados exp010-012; solo atención pura cruza exp013). | Alta | PROBADO | Remedio arquitectónico = atención (G2 sube cuota/W/globales); en el límite → RAMA B (atención plena). NO es un knob de ratio. |
| RM4 | **Verificador con FP-rate no medido enciende el lazo** → motor de auto-degradación (M2 R3). | Alta | Mitigado por orden | Regla anti-Goodhart: M2/M4/M5/M6 NO arrancan sin FP<e\* de M1. Gate no-circular + dedup+replay. |
| RM5 | **Cuota Kaggle escasa** (ASUMIDO ~30 h/sem; el motor de datos STaR rinde ~2 pares/h GPU). | Media-Alta | Confianza media | Smoke local OBLIGATORIO antes de gastar GPU; recortar K/N_PROMPTS/ROUNDS a escala; PISTA-ADAPT como camino barato. |
| RM6 | **Federado sin corregir** arrastra el bug naïve (exp003: error 0.4%→66%; cuadrático bajo DP). | Alta | PROBADO | Corregir a FedEx-LoRA (`avg(B@A)`+SVD) en M4 **antes** de usar la banda federada; test de regresión exp003. |
| RM7 | **Asincronía CPU↔Kaggle** (el adapter entrenado en Kaggle no encaja con el modelo que generó en CPU si cambió). | Media | PENDIENTE | Versionar base+adapter por ronda; fusión solo intra-cuenca; medir deriva en M2 a escala; fallback offline por lotes. |
| RM8 | **Esfuerzos son conjetura** (sin velocidad de equipo medida; un dev CPU-first). | Media | Honesto | Rangos amplios; M3 marcado como el más caro y de mayor incógnita; el cronograma prioriza el camino Apéndice A barato (M1→M2 en paralelo a M0). |
| RM9 | **Piezas PENDIENTES sin exp propio** (dos núcleos, pizarra, comunicación-por-necesidad, jerarquía de dominio). | Media | PENDIENTE | Tratadas como fase tardía (M5/M6); se diseñan como interfaz + plan de medición, NO se reclaman funcionando. |
| RM10 | **Numeración cruzada de planos** (01 referenciaba numeración pre-final). | Baja | **RESUELTO** | 01 re-numerado a la numeración canónica de `00_INDICE.md` (2026-06-28, verificado). Convención: 09 define interfaces/orquestación; los módulos los implementan 04/05/06. Sin doble implementación. |

---

## Definición de Hecho (DoD) del PLAN MAESTRO + dependencias

### DoD verificable del cronograma completo (v1 mínimo entregable)
Se considera el build v1 **HECHO** cuando:
1. **M0** cerró los 3 gates con número y eligió rama de backbone (registrado en `MANAGER_LOG.md`).
2. **M1** tiene ≥1 verificador con FP-rate medido < e\* (gate anti-Goodhart satisfecho).
3. **M2** reproduce el bootstrap sin colapso con el verificador real + rollback funcional.
4. **M3** entrega un GGUF Q4_K_M (rama elegida) corriendo en el i3 a tok/s ≥ baseline, O — fallback
   honesto — el sistema entrega valor sobre Qwen+LoRA (PISTA-ADAPT) mientras el sustrato propio madura.
5. **M4** inyecta hechos nuevos con olvido acotado y la agregación federada está corregida.
6. **M5** demuestra modularidad (experto nuevo sin reentrenar el resto) — o se congela si el routing no
   paga (control negativo CYCLE 47).
7. **M6** corre un razonamiento multi-paso verificado end-to-end con comunicación desacoplada (A-RC5).
8. Cada milestone cerró con **prueba CLI real** (no solo pytest), tests de regresión por bug/feature, y
   entrada en `MANAGER_LOG.md`.

### Dependencias del plan
- **Duras:** el sustrato tiny que corre hoy (✅), `venv312` (✅), `node/llama-server.exe` b9391 + 6 GGUF
  (✅), sandbox `exp018`/`sandbox_tester.py` (✅), Kaggle GPU configurada (✅).
- **Faltante crítico:** un GGUF SWA-nativo para G1 (a bajar en M0); el kernel de pre-entreno
  `pretrain_hybrid_kaggle.py` (nuevo, M3); el tokenizer BPE 32k (M3).
- **De secuencia (orden Apéndice A):** M1 antes de M2 antes de {M5, M6}; M0/G1 antes de M3; M3 antes de M4.
- **Paralelizables:** M0 ∥ M1 (→ M2). Esto acorta el camino crítico.

### Restricciones duras que el build respeta (recordatorio)
Sin PyTorch en nodos (el lab v0 usa torch-cpu, permitido); FedAvg **solo** adapters LoRA (FedEx-LoRA,
nunca params base ni naïve); cero datos personales centralizados; ruido DP en cliente; HYDRA = router de
3 bandas a nivel de sistema (NO atención de red); nada de mocks/stubs (cada subsistema cierra con prueba
CLI real); sin `sqlite3.connect()` directo (usar `storage/db_pool.py`); sin constantes de modelo
hardcodeadas (usar `shattering/model_constants.py`); validar código auto-generado (allowlist + sandbox
timeout, `cognia_v3/core/sandbox_tester.py`); publicar a PyPI/externos solo con autorización explícita.

---

> **Cierre honesto.** Este plan maestro es **el cronograma, no la promesa**: ordena los planos 01-09 por
> el esqueleto de 3 pasos que el lab **probó que paga** (verificador → lazo+guardia → expertos), arranca
> por **M0** para no comprometer la arquitectura a ciegas, **paraleliza M1/M2 sobre el tiny que ya corre**,
> y mantiene **ambas ramas de backbone armadas** (A híbrido / B GQA denso) porque A-018 está sin verificar.
> Marca con honestidad lo PROBADO (los subsistemas demostrados-en-pequeño con código que corre), lo
> ASUMIDO (literatura, constantes confianza media, esfuerzos conjeturales) y lo PENDIENTE (dos núcleos,
> pizarra, jerarquía de dominio, internalización — todo SCALE=0%). El sistema **entrega valor incluso en
> el peor caso de cada gate** (RAMA B en backbone, PISTA-ADAPT en entrenamiento, fine-tune offline en el
> lazo, LoRA-para-hechos en continuo): ningún fallo de gate bloquea el build, solo redirige una caja.
