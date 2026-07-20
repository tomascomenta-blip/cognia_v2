# literature_v4.md — Barrido de literatura del RESET v4 (2023-2026)

> Barrido web citado (CYCLE 37, 2026-06-24) para anclar el reset v4 en lo más actual. Cada arXiv/DOI/
> OpenReview fue devuelto por búsqueda real (no inventado). **Aviso:** casi todos los números de velocidad
> son GPU/vLLM-medidos; las conclusiones ARQUITECTÓNICAS transfieren a CPU, los speedups NO. Re-medir en el
> i3 antes de comprometerse.

## Frente 1 — Valor endógeno / motivación intrínseca como objetivo
- **arXiv:2606.20104** (Ivashkov/Balestriero/Schölkopf 2026): encoder por inverse-dynamics (action-grounded)
  recupera EXACTO las dimensiones controlables y colapsa los distractores; 84% vs 59% de éxito de planning
  vs baseline de reconstrucción; ~5M params (ViT-Tiny, CPU-scale). **APOYA fuerte** R-VALOR action-grounded.
- **arXiv:2509.22504** (EELMA): estima el empowerment de un agente LM desde TEXTO, reward-agnóstico; el
  empowerment correlaciona fuerte con desempeño. **APOYA** (LLM, sin verificador).
- **arXiv:2510.05996** (Schneider 2025): pre-entrenar SOLO con empowerment transfiere; usa Blahut-Arimoto
  (sin gradiente, CPU-runnable en espacios discretos/chicos). **APOYA** (Q1+Q2).
- **arXiv:2502.00835 (CAIMAN)** / **arXiv:2502.10077 (ECL)**: causal action-influence (CMI acción→var) como
  reward intrínseco → representaciones más controlables + mejor eficiencia muestral. **APOYA** (magnitudes de
  abstract, confianza media).
- **Gopnik group** (arXiv:2503.23631; Phil.Trans.R.Soc.A 384:20250003): en humanos info-gain y empowerment
  predicen aprendizaje causal; la entropía no-dirigida NO. **APOYA** (prior de diseño: dirigir a control/
  info-gain, no novedad genérica). Evidencia cognitiva, no benchmark de modelo.
- **OpenReview tHr0vFbS3K** (Butkus & Kriegeskorte 2025): un transformer next-token PLANO descubre SCMs
  lineal-gaussianos y responde contrafácticos no vistos. **CONTRADICE la forma fuerte** = es el NULL que
  R-VALOR debe batir en la MISMA tarea.
- **arXiv:2511.04177** ("When Empowerment Disempowers"): empowerment individual puro desalinea en multi-agente
  → caveat de DISEÑO de objetivo, no de calidad de representación.

**Resumen honesto:** objetivos control/action-grounded tallan estructura causal mejor que reconstrucción
(sobre todo con distractores); "estrictamente necesario" NO está establecido (next-token-SCM). No se halló
ningún paper que entrene un objetivo intrínseco end-to-end en CPU reportando wall-clock CPU → ese dato es un
HUECO que el lab puede llenar.

## Frente 2 — Active causal discovery: activo (info-gain) vs azar (decide H-V4-1b)
- **arXiv:2109.02429** (AIT 2021): ER-4 densos, 15 nodos: SHD final Random 7.2 → AIT 0.0; con ruido η=0.05 el
  random no converge, AIT sí. **APOYA activo** (brecha crece con tamaño/densidad).
- **arXiv:2203.02016** (Soft-CBED 2022): info-gain recupera ~4× más rápido en 50 nodos no-lineales.
- **arXiv:2211.13715** (GIT 2022): AUSHD Random 9.9 → GIT 5.0 (~49%); en grafos CHICOS el random es competitivo.
- **arXiv:2405.16718** (CAASL, NeurIPS 2024): d=10, ventaja sobre random sólo ~5-6%; con ruido
  heteroscedástico "random becomes very competitive". **MIXTO — el contrapeso clave.**
- **arXiv:2306.05781** (Choo & Shiragur UAI 2023): worst-case no-adaptativo O(n) vs adaptativo O(log n)
  intervenciones — adaptativo puede usar exponencialmente menos. **APOYA activo (adaptativo)** como cota.
- **arXiv:2410.20089** (NeurIPS 2024): menos muestras que random para SHD bajo (cualitativo).

**Bottom line H-V4-1b:** activo bate a random de forma ROBUSTA sólo en grafo grande/denso + presupuesto
escaso + ruido bajo; el borde se encoge a "random alcanza" en grafos chicos / presupuesto amplio / ruido
alto. **Regla: presupuestar la ganancia.** ESTO CORROBORA exp023 (régimen ruidoso/chico → margen ~0): mi
null es el corner conocido, no un bug. Pendiente: medir MI crossover (grafo grande/denso/ruido bajo).

## Frente 3 — Arquitecturas baratas que razonan en CPU/edge
- **arXiv:2408.03314** (TTS scaling) + **arXiv:2508.16665** (survey): test-time compute óptimo: 1B bate a
  405B; Qwen2.5-0.5B bate a GPT-4o en mate dura, >4× más eficiente que best-of-N; **verifier-based ≫
  verifier-free, la brecha crece con el cómputo.** **APOYA FUERTE** (el verificador es la pieza que carga).
- **arXiv:2501.12948** (R1-Distill-Qwen-1.5B): AIME24 28.9% pass@1; 1.5B = sweet spot de llama.cpp; CoT
  larga = lento en CPU.
- **arXiv:2504.21318** (Phi-4-mini-reasoning 3.8B): bate modelos ~2× su tamaño en mate; data-curation > escala.
- **arXiv:2504.03624 (Nemotron-H)** / **2601.02346 (Falcon-H1)**: híbrido SSM-atención 3-6× throughput a
  exactitud igualada, sin KV-cache creciente. **APOYA fuerte** (la ganancia arquitectónica transfiere a CPU
  RAM-limitada; los números son GPU).
- **arXiv:2503.14456** (RWKV-7 "Goose"): memoria/tiempo constante por token; **YA corre en llama.cpp en CPU,
  sin Python**; 2.9B SoTA multilingüe 3B. **APOYA lo más directo** (corrible hoy); no es razonador dedicado.
- **arXiv:2410.03810**: Mamba flojo en COPY/CoT exacto → caveat para razonamiento.
- **arXiv:2502.05171** (recurrent-depth) / **2507.02092** (EBT +29%) / **2502.09992** (LLaDA diffusion-LM):
  razonamiento latente/iterativo; **MIXTO para CPU** (ahorra tokens pero gasta FLOPs/paso; vigilar, no deployar).

**Mejor apuesta razonamiento-por-FLOP en CPU 2026:** backbone híbrido SSM-atención o RWKV-7 (1.5-4B, Q4 en
llama.cpp) + test-time compute guiado por VERIFICADOR barato. El verificador, no los parámetros, convierte
pases baratos en respuestas correctas. **Re-medir en i3 (todo número es GPU/vLLM).**

## Frente 4 — Alternativas a backprop, juzgadas por COSTO (no bio-plausibilidad)
- **arXiv:2407.01163**: PC 3.3-7.2× más lento/época; −22.8 pts en ResNet-18/CIFAR-10. **PIERDE** (wall-clock).
- **arXiv:2305.17333** (MeZO): 12× menos memoria (30B en 1 A100); 2-pass alta varianza → más lento en
  wall-clock; sólo fine-tuning. **GANA en memoria, PIERDE/MIXTO en wall-clock.**
- **arXiv:2212.13345** (FF) / **2501.09238** (Mono-Forward): FF más lento, tope ~16 capas. **PIERDE** a escala.
- **arXiv:2409.12965** (DFA óptico): gana sólo en óptica analógica (>1B). **PIERDE** en HW comodín.
- **arXiv:1812.11446** (greedy layer-wise): BP usa 5× más memoria; tope por debajo del BP full. **GANA en
  memoria, MIXTO/PIERDE en exactitud/wall-clock.**

**Bottom line:** NO usar alternativas a backprop para entrenar más rápido/barato (todas igual-o-peor en
wall-clock). Conditional sólo si el cuello es RAM (no cómputo): MeZO o layer-wise desbloquean lo que BP no
cabe — a costo de wall-clock + algo de exactitud. **Confirma H-BIO-3 del lab.** (El "PC −10-50% energía" era
un blog de Medium feb-2026, NO peer-reviewed → descartado.)

## 3 experimentos accionables y baratos (CPU)
1. **Empowerment (Blahut-Arimoto) vs reconstrucción en un gridworld con distractores (numpy, sin gradiente)**
   — el test MÍNIMO de la premisa R-VALOR forma-fuerte: ¿un valor "qué-importa" AUTO-generado (empowerment)
   recupera factores controlables e ignora distractores, batiendo a un auto-encoder de predicción pasiva?
   (replica arXiv:2606.20104 a escala juguete). **Es el próximo cycle natural (H-V4-1c).**
2. **Empowerment verifier-free como señal de valor sobre rollouts de un modelo chico (torch-CPU)** — portar
   EELMA (arXiv:2509.22504) a un sub-1B: ¿el score endógeno correlaciona con éxito SIN reward externo?
3. **Curva active-vs-random en SCMs chicos→grandes (numpy)** — encontrar MI crossover (donde active deja de
   ganar) replicando AIT/CBED; completa exp023 hacia el régimen grande/denso/ruido-bajo.

## 2 riesgos
1. **El null es real y barato:** la predicción pasiva ya induce SCMs en juguete (OpenReview tHr0vFbS3K). Todo
   mecanismo R-VALOR debe batir a un baseline de predicción pasiva en la MISMA tarea o no se gana su costo.
2. **Contaminación de números GPU + hype de un solo lab** (VibeThinker, Xmodel): las ganancias ARQUITECTÓNICAS
   transfieren a CPU; los speedups/exactitudes medidos NO. Re-medir en el i3.

**Lectura neta:** Frentes 1+3 APOYAN el rumbo R-VALOR/CPU-first (objetivos action-grounded tallan causa;
híbrido-SSM + verificador barato = razonamiento-por-FLOP ganador). Frente 2 corrobora exp023 (active gana
sólo en el corner escaso/grande/denso). Frente 4: saltar las alternativas a backprop salvo cuello de RAM.
