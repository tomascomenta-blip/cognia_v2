# 10 — Registro de riesgos consolidado (build de Cognia-X v1)

> **Propósito.** Consolidar en UN solo lugar, priorizado por severidad, todo riesgo load-bearing
> extraído de `00_READINESS.md` + los planos `01`–`09`. Cada riesgo trae su **plano/subsistema**,
> **probabilidad**, **impacto**, **confianza** (cuán bien anclado está el riesgo mismo en el ledger),
> **mitigación** y el **gate de validación** que lo cierra o lo monitorea. Cierra con los **3 gates
> duros (G1/G2/G3)** y qué desbloquea cada uno. Este documento es la **fuente de verdad de riesgos**
> del build; cada plano detalla su versión local, aquí se priorizan transversalmente.

> **Anclaje (verificado, no asumido):** `00_READINESS.md §4-5` (gates + caveats), `01 §6`, `02 §6`,
> `03 §6`, `04 §6`, `05 §6`, `06 §6`, `07 §6`, `08 §6`, `09 §6`. Honestidad innegociable: cada número
> se marca **PROBADO** (cita exp/CYCLE) / **ASUMIDO** (literatura/conjetura) / **PENDIENTE** (a medir).
> **SCALE = 0%** atraviesa todo: nada está medido a tamaño v1 (1-3B) ni end-to-end en el i3 objetivo.

---

## 0. Leyenda

- **Probabilidad** = chance de que el riesgo se materialice si NO se mitiga: `Alta` / `Media` / `Baja`.
- **Impacto** = daño al build si se materializa: `Crítico` (cambia la arquitectura v1 o la bloquea) /
  `Alto` (rehacer un subsistema) / `Medio` (recalibrar constantes/plan) / `Bajo` (higiene).
- **Confianza** = cuán sólido es el diagnóstico del riesgo **en sí** (no su mitigación): `alta` (medido
  in-lab), `media` (literatura + analogía), `baja` (conjetura).
- **Gate** = compuerta de validación que lo cierra (`G1/G2/G3` de M0) o monitoreo continuo.
- **P0** = los tres riesgos que pueden **invalidar la arquitectura v1**; arrancan M0.

---

## 1. Riesgos P0 / CRÍTICOS (cambian o bloquean la arquitectura v1 — arrancan M0)

| ID | Riesgo (descripción) | Plano / Subsistema | Prob | Impacto | Conf | Mitigación | Gate |
|---|---|---|---|---|---|---|---|
| **R1** | **A-018: el ahorro de banda de SSM/SWA NO está verificado con kernels CPU reales.** TODA la viabilidad CPU-first del backbone híbrido (RAMA A) asume que llama.cpp entrega el ahorro de banda teórico. Precedente **PROBADO** de fallo: exp007 midió int8 naïve numpy **8-10× MÁS LENTO** sin kernel especializado (el ahorro de bytes NO se materializa solo). exp005 (frontera coste-decode 3:1→26%@L=8192) es **numpy, no kernel**. | 02 (RAMA A), 07 (KV/SWA), 01 §5.3 | Media | Crítico | media | **Rama de fallback ya prevista (NO inventada): RAMA B = Transformer denso pequeño GQA + KV-cache 4-bit, madura en llama.cpp HOY.** El build NO se bloquea: si A-018 no se sostiene, la v1 es RAMA B; el resto del sistema (verificador/lazo/RAG/federado) no cambia, solo el mezclador. | **G1** |
| **R2** | **Recall del híbrido FRÁGIL a carga alta — techo ESTRUCTURAL, no knob afinable.** **PROBADO** (exp013-015): el híbrido naive interleaved platea **~0.18**; **solo la atención pura cruza** (0.88-0.95). El techo del mezclador de estado fijo es estructural (pigeonhole, exp002); subir `d` NO rescata (d=64 vuelve a 0.19); **6 levers no-atención REFUTADOS** (ancho exp010, forma Taylor+init mimética exp011, profundidad/escala/optimizador exp012). El remedio es **ARQUITECTÓNICO = atención**. | 02 §3.4, 01 R11, 03 (EJE-R) | Alta | Crítico | **alta** (medido) | NO tratar el ratio como knob que se "afina": G2 puede tener que **subir la cuota de atención / ensanchar W / añadir 1-2 capas GLOBALES** a la escala objetivo. La banda LOCAL descansa en sliding-window (atención). La RAMA B (fallback de R1) es atención-mayoritaria → recall garantizado por construcción. | **G2** |
| **R3** | **Verificador buggy con FP SISTEMÁTICO induce sesgo y se compone** — el lazo de auto-mejora se vuelve motor de auto-degradación. **PROBADO** (exp017 dose-response): pasado e\* el lazo colapsa. La guardia (dedup+replay) acota la **amplificación**, NO el **sesgo**. El FP-rate real de código/hechos **no está medido** (e\*≈0.15/0.50 son del toy: exp017/CYCLE50-53). | 04 §6 R3, 05 §6 R3, 09 R-RC4 | Media | Crítico | **alta** (mecanismo medido) | FP-rate **medido y monitoreado** por dominio sobre *gold* DISJUNTO (A-V1/A-V4); `verifier_id` versionado para cazar regresiones; dedup evita amplificar el FP correlacionado; **el lazo NO se enciende en un dominio cuyo FP-rate no esté medido < e\*** (dependencia bloqueante 04→05). | A-V1/A-V3/A-L3 |
| **R4** | **Gate de auto-mejora CIRCULAR (H-SELF-2): evaluar sobre la misma DB que el sistema se auto-escribe** → el gate aprueba su propio ruido y el lazo diverge. La línea roja del lab. | 04 §3.8, 05 §3.5, 08 §5.4, 09 §2.1 | Baja | Crítico | **alta** (modo de fallo conocido) | **Mitigado por diseño:** held-out rotativo DISJUNTO + committee anti-Goodhart + snapshot/rollback (05); gate por-dominio `gated_learn_domains(aggregate=False)` ya cierra H-SELF-2 (CYCLE 8); persistencia separada de la memoria auto-escrita (db_pool o JSON append-only); el verificador NO comparte params con el generador. Test de regresión de fuga circular. | A-L4 / A-V3 |
| **R5** | **SCALE = 0%, hardware-bloqueado.** TODO el thesis (arquitectura + R-VALOR + lazo + verificador + recall + federado) está validado en **juguete** (numpy + `HybridLM` tiny ≤1.56M params, d=64 byte-level). La transferencia a 1-3B reales es la **mayor incógnita**. El i3 (2c/4t, sin CUDA) **NO entrena a escala**. | Transversal (todos) | Alta | Crítico | media | **Todo entrenamiento grande → Kaggle GPU** (cuenta `anthuananthuan` configurada, pipeline `cognia_v3/training/kaggle/`); el i3 hace solo inferencia (llama.cpp ~8 tok/s 3B Q4) + experimentos chicos. Escalar gradualmente con telemetría; cada constante se re-mide al comprometerse, no se hereda del toy. | M0 + telemetría |
| **R6** | **FedAvg naïve AÚN PRESENTE en `coordinator/federated_store.py`** (Pass 3, líneas 316-329): promedia los factores `k_A,k_B,v_A,v_B` por separado → `avg(B)@avg(A) ≠ avg(B@A)`. **PROBADO** (exp003): error relativo Frobenius **0.43%→65.7%** con heterogeneidad creciente, y **colapso de rango K·r→r** (tira la diversidad de los K clientes). Bajo el ruido DP que Cognia exige (`sigma=0.01`) el error se vuelve **cuadrático**. | 06 §3.4, 01 R5, 08 R9 | Alta (si se usa hoy) | Crítico (federado) | **alta** (álgebra + medido) | **Corregir a FedEx-LoRA (`avg(B@A)` + SVD truncado r'≤16) ANTES de usar la banda GLOBAL federada.** El archivo YA reconstruye la delta (`_effective_delta_embed`); mover esa reconstrucción al camino de agregación. Reusar exp003 como **test de regresión** (falla con el bug, pasa con el fix). FedAvg SOLO sobre adapters LoRA, nunca params base; ruido DP en cliente. | §5.2 (06) |

---

## 2. Riesgos ALTOS (rehacer un subsistema / overclaim peligroso)

| ID | Riesgo (descripción) | Plano / Subsistema | Prob | Impacto | Conf | Mitigación | Gate |
|---|---|---|---|---|---|---|---|
| **R7** | **El `LinearAttention` de `hybrid.py` NO tiene kernel en llama.cpp.** La RAMA A de producción EXIGE re-expresar las capas lineales como **Mamba-2/SSD o RWKV** (que sí tienen kernel GGUF) y **reentrenar**. **ASUMIDO** (alta confianza en que llama.cpp no soporta la atención lineal custom, pero **NO verificado ejecutando** en el build pineado b9391). El `State_bytes` de la telemetría cambia con el operador elegido. | 02 §3.2 R-2, 02 §3.7 | Alta | Alto | media | RAMA B (R1) NO depende de esto. Si A-018 pasa, portar a Mamba-2/SSD (A1, recomendada) o RWKV6/7 (A2); el `hybrid.py` queda como substrato de investigación. G1 confirma al cargar el GGUF recurrente. | **G1** |
| **R8** | **Reward-hack bajo RL: mecanismo SOLO por literatura — exp019/exp020 REFUTADAS in-lab.** El reward-hack que justifica "imitación, nunca RL-con-auto-recompensa" **NO se reprodujo en el toy**: exp019 (H-LEARN-4) **REFUTADA** (el verificador débil NO se hackeó ni con el atajo sembrado, weak=0.085~strong=0.004); exp020 (H-LEARN-5) **REFUTADA** (RL no se separó de imitación, rl=0.059~imit=0.115; *null de MÉTODO*: GRPO-lite tiny inestable/colapsa). **NO citar exp019/020 como APOYO ni invertir su veredicto.** | 04 §2/§4-D1/§6-R5, 05 D1, 09 §3.6/D4/R-RC10 | Media | Alto | **alta** (en que NO está demostrado) | La elección **imitación/STaR** se mantiene como **precaución de diseño** (literatura RL [Amodei] + asimetría estructural + exp017 dose-response que SÍ muestra colapso por FP), **no** como veredicto empírico. Razón práctica extra: el RL **colapsó** el modelo tiny en CPU. La eficacia de cobertura/held-out contra el hack se **mide en A-V1**, no se asume. Demostrarlo exigiría RL estabilizado (KL/on-policy) o más escala. | A-V1 (mide), no asume |
| **R9** | **Verificador SESGADO que test-retest NO detecta.** La fiabilidad por test-retest `r=clip(2P-1,0,1)` (exp029/CYCLE43) detecta ruido **ALEATORIO**, NO **sesgo sistemático**: un verificador "siempre-acepta" se ve **consistente** (r alto) pero es inútil. Un experto con verificador sesgado pasaría el filtro de fiabilidad. | 08 §6 R3, 04 R3, 09 R-RC4 | Media | Alto | **alta** (límite declarado por exp029) | Complementar con una señal de SESGO (tasa de aceptación vs base esperada) — **NO resuelta**, marcada para fase tardía (M-tarde). El FP-rate medido sobre *gold* (R3) es la defensa primaria; test-retest es solo la capa de ruido aleatorio. | A-V1 + M-tarde |
| **R10** | **Transferencia toy→real del verificador de código.** exp018 demuestra **forma cerrada** (d=64, byte-level, aritmética); la transferencia a **suites de tests Python sobre funciones de varias líneas** está **ASUMIDA**, no medida. El A/B weak-vs-strong de exp018 **aún no midió** una reducción real del FP (el `degenerate` quedó en 0 en ambos brazos porque el lazo nunca descubrió el echo). | 04 §1.3/§5/R1 | Alta | Alto | media | A-V1/A-V3 miden FP-rate vs cobertura sobre *gold* de código con incorrectas plantadas (off-by-one, hardcode, return constante, loop infinito); A-V1 debe **sembrar** el atajo en la generación para que el A/B sea informativo. No comprometer el lazo (05) hasta tener FP medido. | A-V1 |
| **R11** | **`FactVerifier` sin exp propio + error sistemático de corpus.** Redundancia ≥2 fuentes acota el ruido **independiente**, NO el **error sistemático**: 2 fuentes que repiten el mismo error (sesgo de corpus) pasan el gate. Diseño nuevo, apoyado solo en literatura RAG/auto-consistencia. | 04 §3.4/R4 | Media | Alto | baja | Exigir **diversidad de origen** (distinto dominio/autor); `confidence` bajo si comparten linaje; **abstención por defecto** en 1-fuente/conflicto. **NO resuelto** — es el límite estructural del verificador de hechos. A-V4 mide FP-rate y tasa de abstención. | A-V4 + G3 |
| **R12** | **Throughput de generar+verificar en CPU a escala = pared de wall-clock.** Los timings toy (exp038 ~200s/seed) **NO transfieren**. A 3B Q4 (~8 tok/s) generar `K=6 × N_PROMPTS=384 = 2304` completaciones/ronda + ejecutar el sandbox por candidato = **horas por ronda**. Las constantes K/N_PROMPTS/ROUNDS del toy son inviables tal cual. | 05 §6 R10, 03 §6 #3 | Media-Alta | Alto | media | Recortar drásticamente K/N_PROMPTS/ROUNDS a escala; gating endógeno (exp047) para abaratar verificación; generación batcheada por longitud; medir tok/s real + costo de sandbox/candidato en A-L1 ANTES de comprometer ROUNDS; tratar el presupuesto de generación como recurso escaso. **Fallback:** degradar a fine-tune OFFLINE por lotes (curar set una vez, no online por rondas). | A-L1 |
| **R13** | **Puente adapter federado/fundido → inferencia FALTA.** El formato del adapter federado es `npz` propio (`k_A,k_B,v_A,v_B`, **solo k,v**, rango ≤8), que **NO es el GGUF-LoRA que llama.cpp carga** (`LLAMA_LORA_PATH`). Sin el puente `npz→GGUF-LoRA`, la **banda GLOBAL produce adapters que no se pueden correr** — deliverabilidad NO probada (ningún test ejerce inferencia real con adapter federado). | 06 §6 #8, 08 §6 | Alta | Alto | **alta** (gap de integración real) | Construir el puente `npz→GGUF-LoRA` y mostrar **generación real en el i3** con la banda GLOBAL activa (DoD de 06). Tarea de M0. Interactúa con R14 (el npz solo lleva k,v). | DoD 06 §7.1 |
| **R14** | **Desajuste de contrato de adapter (q,k,v,o vs k,v).** `qlora_trainer.py` entrena `q,k,v,o`; `federated_store.py` solo federa `k,v` (`_KEYS`). Federar adapters entrenados así **pierde `q,o` silenciosamente** → degrada los adapters. | 06 §3.2/§6 #3, 08 R9 | Alta | Alto | **alta** (leído en código) | **Decisión de M0:** (i) ampliar `_KEYS` para federar `q,o` también (recomendada — no dejar capacidad sobre la mesa), o (ii) restringir el entrenamiento federable a `k,v`. Documentar la decisión. | M0 (decisión) |
| **R15** | **Separación física en dos núcleos (razonador↔comunicador) NO demostrada ni en pequeño.** Puede no pagar o duplicar RAM (el i3 tiene 11.8 GB). El arco v4 razonó SIN lenguaje (Apéndice A fila 1); la separación es del dueño, sin exp propio. Riesgo derivado (R-COMM-1): el comunicador "rellena" una idea no verificada y la afirma → reward-hack por el lenguaje. | 01 R1/§3.6, 09 §3.1/R-RC2/R-RC5 | Media | Alto | baja | v1 arranca **conservadora**: un `HybridLM` con dos modos de decodificación; subir a **dos adapters LoRA** solo con señal de filtración (A-RC6 la detecta). `checked` gobierna el modo del comunicador; si `checked=False` expresa abstención, NO afirma. PENDIENTE, fase tardía. | A-RC5/A-RC6 |
| **R16** | **Constantes de ARQUITECTURA/MODELO de confianza MEDIA — no medidas end-to-end en el i3** (las de RUNTIME de inferencia SÍ están medidas, plano 07: tok/s, threads, Q4 vs Q4_0, pin b9391). ratio 3:1-4:1, ventana W~1024 (`SWA_WINDOW=512` es early-impl, NO el target), vocab 32-64k, e\*≈0.15/0.50, τ de abstención, % del mix de curriculum (70/30, 50/20/30), ~35% TTFT RAG, umbral `|Δbase|≤1%`. Citadas de literatura/toy, **no medidas en el target**. Comprometer una constante errada propaga error aguas abajo (p.ej. el tokenizer se fija ANTES de entrenar → revertir = reentrenar). | 02 R-5, 04 R2/R8, 03 §6 #4-5, 06 §6 #2, 07 R-3, 09 §3.7 | Alta | Alto | media | M0 + telemetría las fijan; el default es **conservador**; las fronteras de `01 §3.2` son estables para que cambiar una constante interna (caja 02) no rompa el ensamblaje. El tokenizer y el ratio se fijan en M0 antes de entrenar la v1. | M0 (G1/G2/G3) |

---

## 3. Riesgos MEDIOS (recalibrar constantes / plan / diseño nuevo sin exp propio)

| ID | Riesgo (descripción) | Plano / Subsistema | Prob | Impacto | Conf | Mitigación | Gate |
|---|---|---|---|---|---|---|---|
| **R17** | **Transferencia R-VALOR toy→real NO confirmada — es BRÚJULA, no acelerador.** El arco downstream **149-155 cerró del lado RANKING**: el residuo del lazo real es **discriminación, NO calibración**. La tesis 123 (la calibración paga en la decisión bajo escasez) sigue **intacta pero NO confirmada en el lazo real** (~31% en sistema real); sólida solo en toy/oráculo. Riesgo: **sobre-apoyarse** en R-VALOR como fitness/acelerador de loss. | 01 R6, 03 §3.7, 05 §3.4, 06 §6 #6, 08 R7, 09 §3.5/R-RC6 | Media | Medio | media | Usar R-VALOR SOLO como **heurística decisional acotada** de asignación/abstención/desempate (`_topk_diverse`, `CONSEC_FREE`, ordenar bandas), **nunca** como única señal ni acelerador. El default seguro es diversidad pura. | Monitoreo |
| **R18** | **GQA-vs-MHA recall sin medir.** El v0 (`hybrid.py`) es **MHA pura** (sin GQA → KV-cache mayor de lo necesario). Añadir GQA recorta los KV heads (16→2-4) → **menos capacidad asociativa**, justo el recurso que exp013-015 PROBARON escaso (recall frágil). "GQA empata MHA a igualdad de params" es **HIPÓTESIS, no hecho**. | 02 §3.3 G-1/R-6 | Media | Medio | media | Gap chico y testeable (`q_proj`+`kv_proj`); test de regresión: recall exp013 con GQA vs MHA **medido**. Si degrada: **mantener MHA / más KV heads en las capas GLOBALES load-bearing** y reservar GQA agresivo para las SWA locales. | G-1 (test) |
| **R19** | **G3/E4 (RAG vs LoRA vs kNN-LM) sin exp propio.** La triple capa de aprendizaje continuo se apoya en **literatura** (Ovadia 2024, Biderman TMLR'24, Model Soups), NO en medición propia en Cognia. "RAG ≥ fine-tune en hechos nuevos con cero olvido" es **ASUMIDO** hasta el gate. | 06 §5.1, 01 R2, 00_READINESS §4 | Alta | Medio | media | **G3:** A/B barato en CPU (RAG/kNN son CPU; LoRA en Kaggle) con N=M=50 hechos, midiendo `Δnew`/`Δbase`/TTFT por brazo (RAG/LoRA/kNN-LM/full-FT). kNN-LM por-token entra solo como **control negativo** (ya descartado, memory-bound). | **G3** |
| **R20** | **Calidad de recuperación del RAG en el i3 sin medir (no solo banda).** El "cero olvido" del RAG es tautológico, pero su utilidad depende del **recall@k del retriever**. En modo bajo-recurso `cognia_embedding` cae a **n-gramas** (sin all-MiniLM) → el recall puede degradarse fuerte justo en el target i3. | 06 §6 #9 | Media | Medio | baja | **Rama de fallback documentada:** si G3 muestra que el RAG en n-gramas no alcanza `Δnew` útil, la política de hechos cae a **LoRA-para-hechos** (al costo de perder el olvido explícito RGPD y reentrenar en Kaggle). Análogo a la rama de fallback de G1. | **G3** |
| **R21** | **Router de 3 bandas (LOCAL/MEDIA/GLOBAL) es diseño nuevo sin exp propio.** La política de banda puede no respetar bytes/token (P5). | 01 R2/§3.3, 06 §3.3.2 | Media | Medio | media | G3 lo valida en CPU; banda GLOBAL = **1-hit doc-level por construcción** (kNN-LM por-token DESCARTADO); montado SOBRE el routing de dominios existente (logos/techne/rhetor), no reemplaza. Telemetría bytes/token confirma que GLOBAL no domina por-token. | **G3** |
| **R22** | **Asincronía CPU↔Kaggle introduce deriva.** El adapter entrenado en Kaggle no encaja con el modelo que generó en CPU si éste cambió entre rondas. El lazo a escala es asíncrono por rondas (generar+verificar CPU → entrenar adapter Kaggle → reimportar). **No medido.** | 05 §6 R7 | Media | Medio | media (PENDIENTE) | Versionar base+adapter por ronda; fusión solo dentro de la misma cuenca; medir deriva en A-L1 a escala. Fallback: fine-tune OFFLINE por lotes (sin lazo iterado). | A-L1 |
| **R23** | **Jerarquía de expertos N1/N2/N3 de DOMINIO no demostrada.** Lo demostrado (CYCLE 12-21) es ruteo de **cadenas de razonamiento**, no de **expertos de dominio**. Que un árbol de adapters supere a un adapter plano por cuenca es **conjetura**. El **giro CYCLE 47**: el lever es sustrato+verificador, NO más routing. N2/N3 con pocos datos degradan (adapter de bajo rango sobre poco dato). | 08 §6 #1/#5, 01 R4 | Media | Medio | media | Construir 08 **DESPUÉS** de 04/05 (orden Apéndice A); su valor es **modularidad** (añadir dominios sin reentrenar), NO capacidad. Herencia del padre (N2/N3 sin adapter heredan); micro-experto solo bajo demanda. **Control negativo:** si adapter-por-plan ≈ base sola (V2), el routing no paga → congelar la fase. | V2 (08) |
| **R24** | **Calidad por-PLAN vs por-token no medida a escala.** Que la selección por plan IGUALE a MoE token-por-token en CALIDAD (no solo costo) es **ASUMIDO**; solo está fundado el ahorro de banda (exp004). | 08 §6 #4/§3.4 | Media | Medio | media | V2 (08) lo mide en pequeño con verificador real. MoE token-por-token está descartado por RAM del i3 (no caben N sub-redes; sí N adapters, **uno cargado a la vez** vía `--lora`). | V2 (08) |
| **R25** | **Coordinación probada solo en TOY/1-paso.** exp029/CYCLE43 (mezcla adaptativa no-regret, `worst_regret=+0.008`) usa **verificador sintético + tarea de 1 paso**; su propio límite declarado es el multi-paso + verificador real. | 08 §6 #2/§5.1 | Media | Medio | media | V1 (08): replicar la mezcla test-retest con verificador **real-ejecutable** (plano 04); pre-registro APOYADA si `ADAPT ≥ max(componentes) − 0.02` y `r` calibra monótona; `test_cycle43_adaptive_allocation.py` sigue 4/4. | V1 (08) |
| **R26** | **Pizarra / comunicación-por-necesidad PENDIENTES, sin exp.** Riesgo de filtrar "todo el contexto" y perder la eficiencia; la pizarra puede serializar (cuello si N expertos escriben mucho); el protocolo need/provide puede omitir contexto crítico. | 01 R3/§3.4, 08 §3.5-3.6/§6 #6 | Media | Medio | baja | Solo se diseña la **interfaz** (`Pizarra.read(query)` band-filtered, append-only journaleado de `record.py`; protocolo `need()`/`provide()`); NO se reclama funcionamiento. Fase tardía, post-verificador. No bloquea el DoD central. | Diseño (fase tardía) |
| **R27** | **Throughput/yield del motor de datos STaR caro y bajo.** **PROBADO** (corrida real `datagen_report.json`): 8 pares aceptados / 20 generados en ~4.1h (~2 pares/hora GPU). A cuota ≤15%, juntar sintético útil puede costar muchas horas de GPU; el cuello es `failed_run`, no la calidad. | 03 §2.2/§6 #3 | Media | Medio | **alta** (medido) | Confianza alta en que el dato es **correcto**; media en costo-efectividad a escala. Cuota ≤15% + g≤1 acotan deriva; recortar K/N a escala (interactúa con R12). | A-L1/E4 |
| **R28** | **Cuota 15% + g≤1 son de LITERATURA, no de exp propio.** Los umbrales anti-deriva (model-collapse, Shumailov 2024) son prudentes, no óptimos; el lab **no midió el punto exacto de deriva** en este loop. | 03 §3.2/§6 #4, 05 | Media | Medio | media | Eval congelado multi-eje tras cada re-entreno (val bpb / acc recall / arith / pass@1 code); **rollback** si CUALQUIERA cae > δ; el gate vive en datos congelados (NO la DB auto-escrita). g≤1 rompe el bucle recursivo (no syn-de-syn). | E4 (anti-deriva) |
| **R29** | **Schedule del curriculum (orden + %) sin medir a escala.** El orden L→R→V→STaR respeta el Apéndice A (media confianza), pero la mezcla exacta (70/30, 50/20/30) es **ASUMIDA** (baja confianza). | 03 §3.1/§6 #5 | Media | Medio | baja | Fases incrementales (cada una añade un eje sin quitar previos = anti-olvido por mezcla); el schedule de tamaño se valida por `val bpb` vs presupuesto de banda, no por intuición. | E1-E4 |
| **R30** | **Truncado SVD de la corrección federada reintroduce error.** `avg(B@A)`+SVD-r' NO es loss-less; si la heterogeneidad real exige rango K·r alto, r'≤16 puede ser insuficiente. (El blob full `256×2048` f32 ~2MB > `MAX_BLOB_BYTES=512KB` → no se puede shippear delta full.) | 06 §6 #4 | Media | Medio | alta (es controlado) | Error **controlado y medible** (energía espectral retenida), a diferencia del FedAvg ingenuo (error NO controlado). Medir energía retenida; subir el cap de rango del blob si hace falta. | §5.2 (06) |
| **R31** | **Fusión cross-cuenca puede degradar.** "Solo intra-cuenca" (Model Soups) es heurística, no garantía; fundir logos+rhetor podría caer fuera de cuenca. | 06 §6 #5 | Media | Medio | media | El **router de bandas los mantiene separados** por defecto; la fusión es opt-in y verificada (plano 04) antes de comprometer; opera sobre **deltas reconstruidas**, nunca factores A/B. | V3 (08) |
| **R32** | **Gating endógeno/externo mal-calibrado.** exp046 (MIXTA): el endógeno colapsa si mal-calibrado; exp047 (también MIXTA): el gating no colapsa pero la separación por régimen es imperfecta (en débil elige endógeno solo 33%). El ahorro endógeno depende del costo del verificador real (no medido a escala). | 05 §3.4/§6 R6 | Media | Medio | media | Probe (`probe_frac=0.15`) + umbral `calib_threshold=0.65`; ante duda, **caer al externo** (conservador). A-L5 mide. | A-L5 |
| **R33** | **bitsandbytes / 4-bit en Kaggle es frágil.** El run 1 del datagen murió en el load 4-bit; la GPU/cuota de Kaggle puede cambiar bajo los pies. | 03 §6 #6 | Media | Medio | media (un fallo real visto) | `pip install -U bitsandbytes` + **fallback fp16** en el kernel; gate `torch.cuda.is_available()`; `machine_shape="NvidiaTeslaT4"` obligatorio (el backend nuevo ignora `enable_gpu` sin él). | Smoke→Kaggle |
| **R34** | **Pin `b9391` frágil.** Cualquier `git pull` del binario puede traer la regresión **−37% decode** de b9414 (5.2 vs 8.2 tok/s, **PROBADO**). | 07 R-5 | Baja | Medio | **alta** (medido) | Pin documentado en docstring + plano; cualquier bump EXIGE re-correr el A/B (`/completion`, `timings.predicted_per_second`). | Monitoreo |
| **R35** | **Telemetría `timings.predicted_per_second` NO se captura aún** + bytes/token analítico no derivado. Hoy solo `tokens_predicted`. Sin esto, los gates G1/G2 no tienen su métrica maestra instrumentada. | 07 §3.6/R-6, 02 §3.7 | Alta | Medio | alta | Cambio chico retrocompatible (`self.last_timings`); helper `cognia_x/runs/telemetry.py` deriva `bytes_per_token(L)` desde `model_constants.py` (cero constantes nuevas); test de regresión (reproduce 36.0 KiB/token, 576 MiB @16k). | DoD 07 |
| **R36** | **Calidad de KV-4bit (q4_0) sin medir.** El ahorro de RAM es claro (~3.6×); el costo de calidad (pass@1) no. | 07 R-4 | Media | Medio | media (PENDIENTE) | A/B fp16 vs q4_0 en RAMA B (RAM + pass@1); mantener fp16 si degrada. | M0 (RAMA B) |

---

## 4. Riesgos BAJOS (higiene / deuda técnica / numeración)

| ID | Riesgo (descripción) | Plano / Subsistema | Prob | Impacto | Conf | Mitigación | Gate |
|---|---|---|---|---|---|---|---|
| **R37** | **Ternario b1.58 presentado como decidido (NO lo está).** **H-BIT-1 holds=false** (los 2-6× de bitnet.cpp son **kernel-vs-kernel**; BitNet-2B4T pierde **~12% MMLU** vs Qwen2.5-1.5B); **H-LUT-1 holds=false** (T-MAC usa L1, no transfiere al patrón del i3). Riesgo: invertir en una vía sin payoff. | 02 §3.6, 07 §4/R-8 | Baja | Bajo | **alta** (refutación sólida) | **Q4_K_M es la base de producción HOY** (A/B ganado en el i3). Ternario queda como **I+D futuro NO decidido**, fuera de la ruta crítica; solo si aparece un kernel CPU que lo realice sin pérdida a 1-3B. | Fuera de v1 |
| **R38** | **Docs de gobernanza desfasados ~115 ciclos.** `hypotheses.md`/`assumptions.md`/`contradictions.md`/`future_work.md` quedaron congelados ~CYCLE 35-55; el ledger vivo es `research_log.md` + `decomposition_tree.md` + `STATUS_RVALOR.md`. Riesgo: construir sobre una afirmación STALE. | 00_READINESS §5.4, 01 §6 caveat | Media | Bajo | **alta** (verificado) | La construcción se ancla SOLO en los docs **vivos**. Tarea de higiene en M0: sincronizar o marcar **STALE** en cabecera los congelados. | M0 (higiene) |
| **R39** | **Deuda `sqlite3.connect` directo en `federated_store.py`** (líneas 125,135) viola la regla dura "sin `sqlite3.connect` directo → usar `storage/db_pool.py`". | 06 §3.4/§6 #7 | Alta | Bajo | alta | Migrar a `db_pool` **en la misma intervención** del fix federado (R6), sin romper el auto-trigger (`AGGREGATE_EVERY_N=5`) ni el peso semántico (`SEMANTIC_WEIGHT_ALPHA=0.3`). | §5.2 (06) |
| **R40** | **Mocks/stubs prohibidos vs smoke end-to-end necesita cajas mínimas.** | 01 R10 | Baja | Bajo | alta | Cajas = **funciones reales mínimas que corren** (no mocks); cada frontera con CHECK real del contrato de `01 §3.2`. "Código que corre o no cuenta." | DoD 01 |
| **R41** | **Numeración cruzada de planos.** El plano 01 referenciaba una numeración pre-final. | 01 §3.7, 09 R-RC8 | — | Bajo | alta | **RESUELTO (2026-06-28):** 01 re-numerado a la numeración canónica de `00_INDICE.md` y verificado por el crítico de consistencia cruzada. Convención vigente: 09 define **interfaces/orquestación**, los módulos los implementan 04/05/06; sin doble implementación. | Resuelto |
| **R42** | **Trampa `success` exige stdout no vacío** (cazada en `sandbox_tester.py`): un módulo que solo define clase/función no imprime → `success=False` aunque sea correcto. | 04 §2.1/D2 | Baja | Bajo | **alta** (cazada en código) | El `CodeVerifier` cuelga su `ok` de **"la suite de tests pasó"** (señal POSITIVA explícita), NO de `success`. Test de regresión. | A-V1 |
| **R43** | **Crash del verificador = aceptar basura** (excepción no capturada en la rama equivocada). | 04 §3.1/R7 | Baja | Bajo | alta | Contrato: `verify()` **nunca lanza**; toda excepción → `ok=False` con traceback en `evidence`. Test de regresión con input adversarial. | A-V (regresión) |
| **R44** | **Sin combustible: base demasiado débil (acc≈0) no produce verificados** → el lazo no arranca (exp016 exige base en banda [0.20,0.50]). | 05 §6 R9 | Baja | Bajo | media (conocido) | Calibrar el base a una banda bootstrappable; si `n_verified=0` persistente, el monitor para (`ALARM_YIELD`). exp038 arrancó de 0.081 PORQUE el verificador real daba señal. | A-L1 |

---

## 5. Los 3 gates duros de M0 (G1/G2/G3) y qué desbloquea cada uno

Los gates NO son "más investigación toy": son la **primera fase de la construcción** (Milestone 0,
spikes de validación). Cierran los supuestos load-bearing ANTES de comprometer la arquitectura v1.

### G1 — A-018: ¿el ahorro de banda de SSM/SWA se materializa con kernels CPU reales? (riesgos R1, R7, R35, R36)
- **Qué mide:** A/B "SWA vs atención full" en GGUF real, midiendo **tok/s(L∈{256,2k,4k,8k,16k}) + RAM de
  KV (RSS)** en el i3 con llama.cpp b9391. Umbral PROPUESTO (autor, recalibrable): a L=8192, decode del
  híbrido ≤ **50%** del coste del denso equivalente.
- **Bloqueo honesto:** los 6 GGUF locales son **Qwen2.5 = atención FULL**; falta un GGUF **SWA-nativo**
  (Gemma-2/3, Mistral-SWA, Phi-3). El binario y el resto del tooling NO faltan. → M0 baja un GGUF SWA y
  corre el A/B, O declara el fallback.
- **Qué DESBLOQUEA:** la elección de la **caja 02 (backbone)** con número en mano. **Si G1 pasa** → RAMA A
  (híbrido, lineales = Mamba-2/SSD o RWKV con kernel real, reentrenar). **Si G1 NO pasa** → **RAMA B =
  Transformer denso pequeño GQA + KV-cache 4-bit** (madura en llama.cpp HOY). El flujo de `01` **no
  cambia**; solo cambia el mezclador. El build NO se bloquea por A-018 — el fallback es honesto y
  entregable (~8 tok/s HOY).

### G2 — Fragilidad de recall del híbrido a carga alta (riesgos R2, R18)
- **Qué mide:** barrido `ratio × arreglo × #globales` con `recall_task.py` al **load escalado** (n_keys ≫
  ventana, secuencias > W) en el i3. Elegir la **menor fracción de atención** (y de globales) que **cruza
  el umbral de recall al load OBJETIVO** (no al toy).
- **Caveat duro (PROBADO):** el techo del mezclador de estado fijo es **ESTRUCTURAL** (pigeonhole exp002;
  6 levers no-atención REFUTADOS exp010-012); solo la **atención pura cruza** (exp013-015). G2 NO solo
  "afina un ratio": puede tener que **subir la cuota de atención / ensanchar W / añadir 1-2 capas
  GLOBALES**. El remedio es arquitectónico = atención.
- **Qué DESBLOQUEA:** el **ratio:atención, el arreglo y el #globales de la caja 02** fijados con tabla
  recall-vs-coste. Habilita E2 (entreno de recall en Kaggle). Si A-018 ya tiró a RAMA B, G2 es trivial
  (B es atención-mayoritaria → recall garantizado) y solo fija SWA vs denso.

### G3 — E4: política de inyección de hechos (RAG doc-level vs LoRA vs kNN-LM) (riesgos R11, R19, R20, R21)
- **Qué mide:** A/B barato en CPU (RAG/kNN son CPU; LoRA en Kaggle) con N=M=50 hechos: `Δnew`
  (aprendizaje), `Δbase` (olvido, ≤0), **TTFT/tok-s en el i3** por brazo (RAG / LoRA r=8 / kNN-LM
  por-token / full-FT). kNN-LM por-token entra **solo como control negativo** (ya descartado,
  memory-bound).
- **Qué DESBLOQUEA:** la **política de inyección de hechos** y la **banda GLOBAL** del router de 3 bandas
  (caja 07), fijada por datos propios (no literatura). Habilita el `FactVerifier` (consume el índice) y el
  DoD de aprendizaje continuo ("inyectar N hechos sin olvido medible"). **Rama de fallback (R20):** si el
  RAG en el i3 (modo n-gramas) no rinde, la política cae a LoRA-para-hechos.

---

## 6. Mapa rápido riesgo → gate / dependencia bloqueante

| Gate / dependencia | Riesgos que cierra o monitorea | Si falla → |
|---|---|---|
| **G1** (A-018) | R1, R7, R35, R36 | RAMA B (denso GQA + KV-4bit) — build NO se bloquea |
| **G2** (recall) | R2, R18 | subir atención/W/globales, o RAMA B (atención-mayoritaria) |
| **G3** (E4 hechos) | R11, R19, R20, R21 | LoRA-para-hechos (pierde olvido explícito RGPD) |
| **04→05 bloqueante** (FP < e\*) | R3, R4, R8, R10, R42, R43 | NO encender el lazo en ese dominio |
| **Corrección federada** | R6, R13, R14, R30, R39 | banda GLOBAL federada inservible/degradada |
| **Kaggle GPU** | R5, R12, R22, R27, R33 | fine-tune OFFLINE por lotes (sin lazo iterado) |
| **Monitoreo continuo** | R17, R34, R37, R38 | recalibrar / no sobre-apoyar / re-A/B |

---

## 7. Cierre honesto

El build de Cognia-X v1 arranca por **M0 (G1/G2/G3)** precisamente porque los tres riesgos P0 (R1
A-018, R2 recall estructural, R5 SCALE=0%) pueden cambiar la arquitectura v1, y **es deshonesto
comprometer el backbone híbrido sin medirlos primero**. La arquitectura está diseñada para **degradar
con gracia**: cada riesgo crítico tiene una **rama de fallback madura y entregable** (RAMA B denso GQA
para R1/R2; Kaggle para R5; FedEx-LoRA para R6; LoRA-para-hechos para R20; fine-tune OFFLINE para
R12/R22). Las dependencias bloqueantes respetan el **orden que el Apéndice A probó que paga**
(verificador 04 → lazo 05 → expertos 08); **NO construir 05-08 antes de que el verificador (04) tenga
FP-rate medido < e\***.

Dos honestidades que este registro NO esconde: **(a)** la mitad "imitación-NO-RL" del diseño se apoya
**solo en literatura** — exp019/exp020 (H-LEARN-4/5) están **REFUTADAS** in-lab (null de método); el
reward-hack de RL NO se demostró en el toy (R8). **(b)** R-VALOR es una **brújula decisional**, NO un
acelerador; el arco 149-155 cerró del lado RANKING y la tesis 123 **no está confirmada en el lazo
real** (R17). Ningún plano debe sobre-apoyarse en ninguna de las dos.

**SCALE = 0%** atraviesa todo: la mayor incógnita es la transferencia toy→escala, confianza **media**.
El build la enfrenta midiendo cada constante al comprometerla (telemetría bytes/token + tok/s real),
no heredándola del juguete.
