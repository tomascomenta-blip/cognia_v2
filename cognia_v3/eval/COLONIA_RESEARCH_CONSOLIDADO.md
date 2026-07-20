# COLONIA → CASI-GRANDE — Consolidación de investigación (2026-07-12)

**Marco fijo:** i3 2-cores / 12GB RAM / llama.cpp b9391 / 1 generación a la vez (3B ~8 tok/s, 7B ~2.2, 4B ~4.5, 1.5B ~15). Ejes del producto: código fácil/duro, razonamiento-math (G2R), español/instrucciones, tool-calling, latencia percibida. Líneas cerradas que NINGUNA propuesta reabre: fine-tune de capacidad (6 negativas), speculative/draft CPU, juez-LLM, debate (mesa redonda 1/6 → opt-in). Vara de promoción: gates propios pre-registrados con juez de EJECUCIÓN, batería 17, e2e camino feliz — nunca cifras de paper.

**Tesis que emerge de los 6 hilos:** con modelos chicos el cuello NO es generación sino SELECCIÓN (oracle gap 32.3% medido en Cost-of-Consensus; el bug del juez-débil cazado en el deploy 7B es el mismo fenómeno local). Las 5 apuestas top atacan selección, ruteo y feedback de ejecución — cero entrenamiento, cero RAM extra, todo sobre infra existente.

---

## 1. RANKING (ganancia × viabilidad CPU × costo)

| # | Estrategia | Eje | Viab. CPU | Costo | Evidencia clave |
|---|---|---|---|---|---|
| 1 | Audit del oracle + router semántico kNN/clusters (Avengers) | transversal + latencia | máxima (embedder 0.6B ya corre; kNN = numpy) | 2-4h audit + 4-8h router condicionado | Avengers: pool ~7B > GPT-4.1 promedio; LLMRouterBench: kNN/clustering ≈ routers entrenados |
| 2 | S* — desempate por ejecución diferencial en best_of_n | código duro | alta (todo es ejecución, mismo modelo) | 12-20h | Qwen2.5-Coder-3B + S* > GPT-4o-mini (LiveCodeBench); ataca la causa raíz YA cazada (juez con tests visibles débiles) |
| 3 | Cascada con umbral θ sobre score de tests (ns×nt) | latencia + robustez del juez | alta (calibración con datos históricos) | 4-6h | Model Cascading for Code: −26% costo promedio (hasta −70%) sin perder accuracy |
| 4 | Self-repair con traceback (debugger loop, gated) | código | alta (single-stream, solo al fallar tests) | 4-8h | Eval 19 modelos: debugger +9.8pp; roles multi-agente sobre debugger +0.96pp n.s. |
| 5 | Self-MoA — agregación de las N muestras en ejes SIN oráculo | razonamiento/español | alta (1 llamada extra sobre best_of_n) | 2-3h | Self-MoA > Mixed-MoA (+6.6pp AlpacaEval, +5.6pp CRUX con ≤7B); valida el diseño actual |

### Top 1 — Audit del oracle → router kNN/cluster
- **Qué:** (fase A) correr cada modelo del fleet_registry sobre sets congelados y tabular por ítem el oracle vs mejor-modelo-único, por eje. (fase B, condicionada) tabla cluster→modelo con embeddings de los results_*.json históricos + k-means; hook antes del router léxico con fallback.
- **Gate pre-registrado:** fase A es el gate de la fase B: construir el router SOLO si oracle − mejor-único ≥ 3pp en algún eje (hipótesis nula fuerte: en código el techo compartido Qwen predice ~0pp; la decorrelación esperable está en VibeThinker-1.5B vs Coder en math y LFM2.5 vs Qwen en español). Fase B: kNN vs léxico en split held-out 50/50, McNemar p<0.05, cero regresión en batería 17 + BFCL, overhead de ruteo ≤ 100ms.
- **Suite congelada:** unión de G2R + set duro + ítems español de batería 17 + set math; corridas nocturnas (cache_prompt=false como en el eval).
- **Kaggle SI pasa:** nada obligatorio (cero entrenamiento por diseño). Única corrida admisible: si el audit revela un cluster de alta demanda sin especialista, un adapter LoRA de FORMATO para ese cluster (patrón K1 id4b) — nunca de capacidad.
- **Bonus:** convierte la cascada reactiva en PROACTIVA (cluster predice fallo del 3B → directo al 7B/plan), ahorrando el intento fallido del 3B.

### Top 2 — S*: síntesis de inputs discriminantes + ejecución pareada
- **Qué:** cuando ≥2 candidatos del best_of_n pasan los tests visibles, pedir al 3B/4B inputs que los DISTINGAN (~100-200 tok), ejecutar ambos en el sandbox ya validado, elegir por comportamiento observado.
- **Gate pre-registrado:** reusar el harness del deploy 7B (N=40 con tests ocultos, McNemar pareado). Pre-registrar: (a) medir primero el subset de "falsos empates" (≥2 candidatos pasan visibles pero difieren en ocultos); (b) S* debe flipear una fracción significativa de esos a favor del correcto (p<0.05); (c) cero regresión: set duro 5/5 y e2e camino feliz 5/5 intactos.
- **Suite congelada:** set duro código + los N=40 del gate 7B con tests ocultos.
- **Kaggle SI pasa:** nada en fase 1. Si la síntesis de inputs del 3B falla por FORMATO (>20% inputs inválidos), candidato único: adapter LoRA de formato "generador de inputs discriminantes" con el pipeline QLoRA CLI existente, gate estilo G3 0→100.

### Top 3 — Umbral θ calibrado en la cascada 3B→7B
- **Qué:** score = (tests que pasan × soluciones que los pasan) sobre los candidatos; escalar al 7B solo si score < θ·k·Nt, con θ ajustado por grid sobre resultados históricos (split 30/70 como el paper; óptimo publicado θ≈0.9-1.0).
- **Gate pre-registrado:** no-inferioridad en accuracy (0 ítems perdidos vs cascada actual en el set congelado) Y ≥25% menos invocaciones al 7B. Más los 3 checks e2e en vivo que salvaron el deploy 7B (el gate de suite NO basta — lección medida).
- **Suite congelada:** set duro + set código fácil; calibración solo con results_*.json históricos (nunca con el set de gate).
- **Kaggle SI pasa:** nada (es calibración pura). Ganancia esperada honesta: latencia/costo, NO pp nuevos en código duro (techo compartido).

### Top 4 — Self-repair con feedback de ejecución (máx 2 rondas, gated)
- **Qué:** si best_of_n no produce candidato que pase tests visibles, re-prompt del MISMO modelo con traceback/test fallido, 1-2 iteraciones. Sin roles, sin críticos-LLM (Olausson: el self-repair está acotado por la calidad del feedback → el feedback DEBE ser ejecución).
- **Gate pre-registrado:** sobre el subset histórico de "0 candidatos pasan" (recolectar de results_*.json): recovery ≥15% con ≤2 rondas, presupuesto wall-clock cap (~200s extra solo en fallo), McNemar vs no-repair. Cero regresión camino feliz (el repair no toca el camino sin fallos).
- **Suite congelada:** ítems fallados del set duro + código fácil congelados.
- **Kaggle SI pasa:** nada; solo si el formato de parche del 3B es el modo de fallo dominante, adapter de formato diff/patch (categoría permitida).

### Top 5 — Self-MoA: agregador sobre las N muestras donde NO hay tests
- **Qué:** en razonamiento/diseño/español (donde hoy best_of_n no tiene señal de selección), 1 llamada extra que sintetiza las N muestras (prompt de agregación; Self-MoA-Seq con ventana si el contexto aprieta en 16k).
- **Gate pre-registrado:** G2R congelado N=40, brazos: single-shot / primera-muestra / +agregador-3B / +agregador-4B. McNemar p<0.05. **Kill-condition explícita:** si agregador ≤ single-shot del mismo modelo → matar (trampa medida del campo: el agregador débil es techo — qwen-1.5-7B agregando rinde 28.94 vs 56.83 con agregador bueno). Cero regresión batería 17.
- **Suite congelada:** G2R + subset español de batería 17.
- **Kaggle SI pasa:** opcional adapter de formato "sintetizador" con receta Mix Distillation (teacher = los 7B propios, cadenas CORTAS estilo stepwise v2 — la literatura confirma que CoT largo de teachers grandes DAÑA a ≤3B, consistente con E-RZN/STaR). Si el 3B no pasa, probar Qwen3.5-4B de agregador ANTES que entrenar nada.

### Segunda ola (condicionadas, no rankear hasta cerrar top-5)
- **Multi-LoRA hot-swap por rol** (4-8h): smoke de `/lora-adapters` + campo `lora` per-request en b9391; extiende K1 a 2-3 roles de FORMATO con RAM ~cero. Gate e2e camino feliz obligatorio.
- **Trigger de estancamiento → cascada en /hacer** (4-8h): conectar la señal de no-progreso (fix 3.8.4) como 2º trigger del 3B→7B, máx 1-2 escaladas/tarea (patrón SWE-Protégé sin el SFT).
- **Plan-then-code** (8-16h): 7B/4B emite plan ~150 tok → 3B decodifica; gate vs cascada actual (COPE: +2.4pp a −74% costo). Apunta a EXPANDIR el set duro resoluble.
- **PRM 1.5B + particle filtering N=4 en math** (16-44h): kill-gate PREVIO obligatorio — verificar que b9391 sirve el scoring vía logprobs de token especial (RECORDADO, no verificado); si falla, muere toda la línea PRM. Solo eje math (los PRM no generalizan fuera; en código el juez ejecutable ya es gold). Requiere cache_prompt=true en esa ruta.
- **Fusión top-k UniTE en pares decorrelacionados** (4-8h; API ya verificada en vivo): solo pares <10pp de gap y como UN candidato más dentro del best_of_n; hipótesis nula fuerte en código (fallos correlacionados Qwen).

### Decisiones de 0h a registrar (para no re-litigar)
- Cap de N en best_of_n y prompts SIMPLES en las muestras (4 fuentes: TTS satura en la cola dura; prompting elaborado + scaling = regresión).
- PRM solo para math/razonamiento, jamás juez general (error crece lineal con longitud del CoT fuera de math).
- Nunca mergear adapters de rol (TIES/DARE pierden 12-35% del pico); rutear, no fusionar.
- Check de fingerprint de tokenizer en fleet_registry antes de cualquier par de fusión (Qwen2.5-Coder 0.5B↔7B verificado interoperable; VibeThinker/Qwen3.5/LFM2.5 pendientes).

---

## 2. DESCARTES DE PLANO (este hardware, 1 línea c/u)

- **MoA multi-modelo ≥2 capas como default:** costo aditivo secuencial 3-5 a 30 min/query; solo concebible opt-in "pensar fuerte" y con proposers ≤4B.
- **ReM-MoA / profundidad >2:** 13-37 llamadas de 7Bs a 2.2 tok/s = 40+ min/query; además el vanilla se AUTO-degrada con capas (−9.1pp a L=9).
- **Debate/MAD (reabrir mesa redonda):** 7ª+ confirmación externa — peor que self-correction a 2.1-3.4× el costo, sicofancia 85.5%, oracle gap 32.3%; queda opt-in.
- **PRMs generativos (GenPRM/ThinkPRM):** el juez genera más tokens que el policy; en 2 cores el decode es el recurso escaso.
- **MCTS / TTS a N=256:** horas por pregunta a 8 tok/s; los headline "1B>405B" viven en ese régimen.
- **CoS / speculative ensembles / EAGLE-class:** el speedup es verify batcheado = compute-bound en 2 cores; línea ya CERRADA con medición (0.464×, 0.37×).
- **Proxy-tuning/DExperts:** 3 pasadas/token (0.7-1.3 tok/s) y no existe par tuned/untuned chico en la flota.
- **Routers entrenados (RouteLLM-MF, R2-Router, FusionRoute):** exigen GPU + decenas de miles de etiquetas; kNN/clustering rinde parecido según LLMRouterBench.
- **Router generativo (Arch-Router-class):** 1-3s por decisión de ruta vs ~0ms del léxico; presión de RAM por modelo residente extra.
- **Frameworks multi-agente conversacionales (AutoGen/CAMEL/AgentVerse):** single-agent les gana en software incluso con modelos frontera; los 7-8B rompen sus formatos rígidos.
- **SWE-bench-class con ≤7B local:** 3.0% zero-shot; no es terreno del producto sin fine-tune (cerrado) o experto de nube.
- **Merging de adapters (task arithmetic/TIES/DARE):** pérdida medida 12-35% del pico del especialista; la flota no tiene presión de slots que lo justifique.
- **Búsqueda PSO de pipelines (Heterogeneous Swarms):** cientos de evals de pipeline = días de cómputo; el resultado cualitativo (DAGs cortos heterogéneos) ya está capturado por la cascada.
- **Peer distillation / ReM-MoA* / MapCoder-Lite:** todo es fine-tune de capacidad → línea cerrada con 6 negativas; la literatura además CONFIRMA esas negativas (learnability gap).
- **Scorer aprendido tipo FrugalGPT como judger:** es juez-LLM por la ventana; el gaming ya se midió localmente.
- **Fusión full-logits (GaC/DeePen/cross-vocab):** llama-server solo expone top-n_probs y UniTE demuestra que k=10 basta — no justificar un runtime custom.

---

## 3. TEORÍA DE LA COLONIA (borrador v0)

**Principio rector: la colonia no delibera — ejecuta, mide y deja rastro.** Toda la evidencia 2025-2026 converge: con modelos chicos, la coordinación por CONVERSACIÓN (debate, roles charlando, consenso) destruye valor; la coordinación por ARTEFACTOS DETERMINISTAS (tests, tracebacks, scores, tablas de ruteo) lo crea. Es estigmergia: como las hormigas, los miembros no se hablan entre sí — modifican un entorno compartido (el ledger de resultados, el sandbox, el registry) y reaccionan a él. La restricción de hardware (1 generación a la vez) deja de ser limitación y pasa a ser principio de diseño: **una sola voz genera; todo lo demás es percepción, ruteo, verificación y memoria — y eso es barato.**

**Anatomía (quién hace qué):**

1. **PERCEPCIÓN — portero 0.5B + embedder 0.6B (residentes, ~ms).** El portero filtra/acelera como hoy; el embedder produce la representación de cada query que alimenta al ruteo. Costo marginal cero: ya están desplegados.

2. **RUTEO — UN router, barato y determinista (léxico + kNN/cluster; Top 1).** La lección transversal: el router debe ser uno solo y no-LLM; la especialización vive en los GENERADORES, no en el que decide. La tabla cluster→(modelo, presupuesto N, estrategia) se aprende OFFLINE de los evals propios — los results_*.json son la feromona de la colonia: cada eval corrido deja rastro de qué miembro acierta dónde, y el ruteo del futuro lo lee. El router decide también la ESTRATEGIA: BoN simple en fácil, plan-then-code en duro, stepwise en math — porque el óptimo de test-time compute es dependiente de dificultad (medido en 4 fuentes).

3. **GENERACIÓN — un especialista por query (principio Self-MoA).** No mezclar la flota: muestrear N veces al MEJOR miembro para ese cluster gana a mezclar miembros dispares (la heterogeneidad LFM2.5-junto-a-Coder-7B es exactamente donde Mixed-MoA pierde). Los 30 miembros del fleet NO son 30 voces simultáneas: son un BANCO DE ESPECIALISTAS FRÍOS con perfil de skill medido; en RAM viven 4 (3B agente + 7B lazy + portero + embedder = 7.8GB) y el resto se carga por cluster o en el turno nocturno. Los roles de FORMATO no son modelos: son adapters LoRA hot-swap sobre la misma base residente (patrón K1) — castas sin costo de RAM.

4. **VERIFICACIÓN — el órgano central, y es DETERMINISTA.** Jerarquía de jueces: (a) ejecución de tests = gold en código; (b) S* ejecución diferencial cuando los tests visibles empatan (Top 2); (c) score ns×nt con umbral θ como termómetro de confianza que decide escalado (Top 3); (d) SOLO donde no existe oráculo ejecutable, el agregador Self-MoA (Top 5) — el único juez-LLM tolerado, en cuarentena, gated con kill-condition. Nunca consenso, nunca ranking por LLM.

5. **REPARACIÓN — self-repair con traceback, 2 rondas máx (Top 4).** El mismo generador + feedback de ejecución. La mesa redonda queda opt-in (6ª negativa local + toda la literatura). 

6. **ESCALADO — la cascada con 3 gatillos.** Proactivo (el cluster predice fallo del 3B → directo al miembro fuerte o al plan del 4B/7B), reactivo (θ-score bajo tras generar), y por estancamiento (el agent loop detecta no-progreso en /hacer → 1-2 escaladas presupuestadas). El miembro fuerte se usa en el rol de máxima palanca por token: plan corto (~150 tok) o diagnóstico, no decode largo — el decode largo es del 3B/1.5B rápido.

7. **AGENTES — encima, no adentro.** El agent loop (/hacer) consume la colonia como servicio; sub-agentes solo secuenciales y por descomposición de tarea (delegar_subtarea), jamás como interlocutores. Single-agent bien instrumentado > multi-agente conversacional (medido con modelos frontera; con 7B es peor).

8. **TURNO NOCTURNO — donde la colonia sí es cara.** Lo inviable interactivo (MoA 2-capas opt-in, Symbolic-MoE k>1 agrupando por experto para cargar cada modelo una vez, corridas de audit del oracle, generación de etiquetas de ruteo) corre en batch. El día ejecuta; la noche re-mapea el territorio y actualiza la tabla de ruteo.

**El lazo de mejora de la colonia (sin GPU):** ejecutar → medir con oráculos → appendear al ledger → re-clusterizar/re-calibrar (θ, tabla de ruteo, perfiles de skill) → rutear mejor mañana. La colonia "aprende" por acumulación de mediciones, no por gradientes. Kaggle entra solo como excepción quirúrgica: adapters de FORMATO cuando un gate lo justifique.

---

## 4. ADVERTENCIAS DE HONESTIDAD

1. **AlpacaEval/Arena-Hard/MT-Bench son win-rates juzgados por GPT-4 — miden estilo tanto como sustancia.** El "+12%" del MoA chico y el "65.7 LC" de Self-MoA viven ahí; jamás transferir esas cifras al eje código ni promover nada con ellas. La vara local es ejecución de tests + batería 17 + tests ocultos.
2. **Régimen de N:** los resultados estrella de test-time scaling (1B>405B, 0.5B>GPT-4o) son a N=256 — horas por pregunta en el i3. Solo cuenta la evidencia a N=4-8 (particle filtering, S*), y aún esa hay que re-medirla localmente.
3. **Paralelismo invisible:** todos los papers de MoA/ensembles asumen proposers en paralelo (API/GPU). En CPU secuencial el costo es la SUMA — un "overhead marginal" de paper son 25 minutos aquí. Recalcular latencia SIEMPRE antes de rankear una técnica.
4. **Flota correlacionada = techo del oracle en ~0:** el headroom del routing/ensembling crece con la diversidad de errores; la flota es mayormente familia Qwen y el techo compartido 3B/7B ya está medido localmente. Pre-registrar la hipótesis nula fuerte en código; buscar la ganancia donde hay decorrelación real (VibeThinker en math, LFM2.5 en español).
5. **Juez-LLM contrabandeado:** SMoA (response selection), ReM-MoA (reviewer), FrugalGPT (judger), GenPRM, y el agregador de Symbolic-MoE dependen de LLM-as-a-judge — la medición local (colapso a gaming; el juez best_of_n descartando al candidato correcto del 7B) obliga a sustituirlo por ejecución o a ponerlo en cuarentena gated (Top 5 es el único tolerado).
6. **Headline con backbone frontera:** MapCoder 93.9% y AgentCoder 91.5% son con GPT-4; con modelos chicos los mismos frameworks dan 54-70% y pueden DEGRADAR (hasta −30% reportado, no confirmado en primaria). El "95% de GPT-4 a 85% menos costo" de RouteLLM es el punto dulce de MT-Bench; MMLU/GSM8K dan 1.4-1.5×.
7. **RECORDADO ≠ VERIFICADO:** varios números de los hilos vienen de abstracts o snippets sin fuente primaria confirmada (Dr. MAS workers-3B+verifier-7B, logprob-scoring de PRMs en b9391, vocab de VibeThinker/Qwen3.5, +8pp de Mix Distillation). Ninguno puede sostener una decisión sin verificación local previa — el kill-gate de b9391-logprobs es el ejemplo canónico: si falla, mueren dos líneas enteras antes de escribir código.
8. **Los papers no corren e2e:** la lección local más cara (3 e2e fallidos del deploy 7B: "el gate pasa" ≠ "el deploy funciona") no tiene análogo en la literatura porque nadie despliega. Todo lo que pase gate de suite necesita además el e2e camino feliz con modelo real antes de tocar producción.