# Cognia-X — Paper científico vivo

> Documento vivo. Se añade, no se borra. Registra preguntas, hipótesis, evidencia, resultados,
> errores, conclusiones y próximos pasos.

## Título de trabajo
**Rediseño de una IA desde primeros principios para CPU: ¿qué componentes sobreviven a la
evidencia?**

## Abstract (v0.1, 2026-06-17)
Cognia-X investiga, componente por componente, qué piezas de las arquitecturas modernas de IA
están justificadas por evidencia bajo una restricción dura: **eficiencia en CPU de portátil, sin
GPU**. No se acepta ninguna arquitectura por autoridad. Cada componente (representación de
entrada, mezcla de secuencia, mecanismo de cómputo, aprendizaje continuo, inspiración biológica,
auto-mejora) se somete a hipótesis falsables y experimentos reproducibles. Primer resultado
empírico (exp001): el coste de la atención full escala cuadrático en tiempo y memoria en CPU,
mientras un mezclador de tiempo lineal lo domina hasta 70× a L=4096 — pero esto mide coste, no
calidad, y por tanto **no** justifica aún reemplazar la atención.

## 1. Pregunta raíz
Si rediseñáramos una IA desde cero con el conocimiento moderno, ¿qué construiríamos, y por qué,
con evidencia? Prioridad #1: eficiencia computacional. Objetivo de hardware: CPU.

## 2. Método
Ciclo de investigación de 9 pasos (ver `00_protocolo_investigacion.md` §2): investigar →
hipótesis falsable → evidencia a favor/en contra → refutación adversarial → experimento
CPU-feasible → ejecución reproducible → análisis → conclusión documentada. Cada afirmación lleva
confianza y fuentes.

## 3. Resultados
### 3.1 exp001 — coste de mezcla de secuencia (2026-06-17)
La atención full entra en régimen cuadrático ~L≥512 (tiempo y memoria). Un mezclador lineal es
3.5×→70.3× más rápido (L 128→4096) con memoria intermedia constante (4096× menos a L=4096). Un
SSM O(L) implementado con bucle Python pierde contra el lineal vectorizado: la asíntota no basta
en CPU. **Alcance:** mide coste, no calidad. → `experiments.md` exp001, `hypotheses.md` H-MEZ-1/2.

### 3.2 exp002 — capacidad de recall asociativo (2026-06-17)
Contrapeso a exp001. Sonda training-free: almacenar N pares clave→valor y medir recall. La
atención full mantiene accuracy ~1.0 en todo N; la atención lineal se degrada con capacidad
**d²/32** (32→32, 64→128, 128→512), es decir, su recall escala con el **tamaño del estado**, no
con d. → trade-off **coste↔capacidad** medido. → `experiments.md` exp002, `hypotheses.md` H-MEZ-3.

### 3.3 Síntesis del ciclo-1 (workflow de 13 agentes, 2026-06-17)
Barrido de 6 dimensiones con evidencia web + verificación adversarial (24 hipótesis, 13 holds=true /
11 holds=false). **Tesis:** una IA CPU-first se diseña para minimizar **bytes movidos por token**
(decode memory-bandwidth-bound), no FLOPs. De ahí: backbone **híbrido** estado-fijo + atención
sliding-window (3:1-4:1, Gemma-3 verificado); representación **BPE vocab moderado parity-aware**
(no byte-puro ni BLT a 1-3B); **Q4 base + ternario como apuesta** (BitNet NO demostrado superior a
Q4 de igual calidad); aprendizaje continuo **RAG document-level + LoRA + fusión intra-cuenca**
(kNN-LM/token descartado); agregación federada **avg(B@A)/FedEx-LoRA** (FedAvg ingenuo es
INEXACTO — bug real en `federated_store.py` de Cognia); biología = tomar **principios**
(esparsidad, memoria=cómputo) NO **implementación** (SNN/FF/predictive-coding cuestan más);
auto-mejora **solo con evaluador verificable + gate + rollback**. Confianza **alta en direcciones,
media en constantes** (no medidas en el CPU objetivo → E1-E5). Detalle: `architecture.md`,
`hypotheses.md`, `decision_log.md`.

**Cross-validación:** mi exp002 (recall ∝ d², empírico) reproduce el resultado teórico de la
literatura (Jelassi "Repeat After Me" ICML'24) que el workflow recuperó por una vía independiente.

## 4. Errores / fracasos registrados
- (ninguno aún; se registrarán con su lección — un fracaso es información, no abandono).

## 5. Conclusiones provisionales
- C1: el camino de mezcla por defecto de una arquitectura CPU-first **no** debe contener un
  término O(L²) (apoyado por exp001, confianza alta para coste).
- C2: las decisiones de reemplazo de componentes exigen evidencia de **calidad**, no solo de
  coste (principio metodológico reforzado por el alcance de exp001).
- C3: existe un **trade-off coste↔capacidad** medido en la mezcla de secuencia (exp001+exp002):
  el lineal es barato pero su recall está acotado por el tamaño de su estado (d²); la atención
  full es cara pero con recall ~ilimitado en N. Conclusión de diseño provisional: **ni reemplazar
  ni mantener — combinar** (híbrido). No se acepta por autoridad: se probará (H-MEZ-4).

## 6. Próximos pasos
- ✅ exp002 (calidad/recall) corrido — confirma el trade-off.
- exp003: validar A-001 (CPU memory-bandwidth-bound) + diseñar el experimento del híbrido (H-MEZ-4).
- Integrar síntesis del ciclo-1 → `architecture.md`.
- Derivar el primer boceto de arquitectura CPU-first defendible por evidencia.

---

## 7. Hallazgos CYCLE 22-29 (recall + aprendizaje continuo Nivel 2)

### 7.1 Techo de recall del mezclador de estado fijo — ESTRUCTURAL (CYCLE 22-28)
La línea H-CEIL convergió: el plateau de recall (~0.18) del mezclador lineal entrenado a d≤48 es robusto a
**6 levers no-atención** (ancho exp010; forma del kernel Taylor + mimetic init exp011; profundidad +
escala-d + optimizador exp012) Y la atención pura lo cruza (exp013: 0.95) donde el lineal no. → el techo es
**estructural** (pigeonhole sobre el estado fijo); el remedio del recall a carga alta es **arquitectónico**
(la atención del híbrido), no de tuning (D-CEIL-1/4). Matiz honesto: el híbrido naive es FRÁGIL — a d chico
las capas lineales bottleneckean (exp014/015, H-HYB), no recupera robustamente (caveat a D-007). Incluyó una
autocorrección de diagnóstico (CYCLE 26 'under-training' → CYCLE 27 refutó: era estructural).

### 7.2 Auto-mejora verificada (STaR) — el verificador es el motor (CYCLE 29, F-LEARN-2)
**H-LEARN-1 (apoyada):** en una tarea VERIFICABLE (suma byte-level, oráculo chequeable), entrenar SOLO con
las auto-generaciones VERIFICADO-CORRECTAS produce auto-mejora; el control decisivo (random_matched: mismo
N_keep + mismos pasos, subconjunto ALEATORIO) aísla que el motor es la **señal de corrección** del oráculo,
no el volumen ni el filtrado-per-se. exp016 (d=64, test held-out disjunto, n=4): verified ÚNICO brazo con
ganancia neta sobre base (+0.110) en los 4 seeds; gap verified−random media +0.126 (t-pareado=3.22, p<0.05;
win 15/16). **Avanza CYCLE 11** (de PREVENIR colapso a HABILITAR auto-mejora en tarea verificable). Caveats:
efecto modesto (+0.11), escala tiny, requiere oráculo chequeable. Verificado adversarialmente (workflow 4 lentes).

### 7.3 Método (meta)
Ambas líneas pasaron por el Investigation Engine (compuertas DoD, ledger, ceiling, verify_no_loss) y por
verificación adversarial multi-agente (workflows). El proceso CORRIGIÓ sobre-afirmaciones del propio agente
(narrativa falsa de 'colapso', estadística inflada, un margen perverso) — la evidencia decide, no la intuición.

### 7.4 Robustez de la auto-mejora al ruido del verificador (CYCLE 30, H-LEARN-2)
**H-LEARN-2 (apoyada):** la auto-mejora verificada DECAE al subir el ruido de falso-positivo del verificador (acepta incorrectas). exp017 (dosis-respuesta, volumen+pasos FIJOS → sólo varía la contaminación, n=3): net-sobre-base de verified por ε(FP-rate) = {0:+0.116, 0.15:+0.074, 0.3:+0.056, 0.5:+0.001, 1:−0.001}, decaimiento monótono (caída ε0→ε1=0.117 > 2σ), sobrevive hasta ε*≈0.15, colapsa a naive por ε≥0.5. Como el volumen es fijo, esto CONFIRMA CAUSALMENTE que el verificador (su corrección) es el motor de H-LEARN-1 (degradar la corrección degrada la mejora, graduado) — cierra una objeción a H-LEARN-1. Robusto a la métrica (final-round y media-rondas coinciden); ε=0 reproduce exp016. Implicación (D-LEARN-2): un verificador real necesita FP-rate < ε* para habilitar auto-mejora — la CALIDAD del verificador es un lever de primera clase.

### 7.5 Auto-mejora con un VERIFICADOR CHEQUEABLE REAL (CYCLE 31, H-LEARN-3)
**H-LEARN-3 (núcleo, apoyada):** la auto-mejora verificada generaliza de un oráculo de forma cerrada
(exp016/017) a un VERIFICADOR CHEQUEABLE REAL — un sandbox que EJECUTA la expresión generada por el modelo
(intérprete propio, allowlist, sin eval(); regla #9). exp018 (síntesis de expresiones "N="->"a op b", test
held-out DISJUNTO M=90, n=3): verified sube real_acc +0.230 sobre base (0.437) en los 3 seeds (strong 0.667,
weak 0.672) y supera a naive_all (0.358, que CAE = colapso sin filtro) por >2σ; robusto a la métrica. El
verificador es el motor incluso cuando EJECUTA la salida (no solo cuando conoce la respuesta). Sub-claim
(reward-hacking de un verificador débil, Amodei 2016): NO observado a esta escala (verified_weak ~= strong,
degenerate=0) — el loop no-RL no descubrió el echo; honesto. Con H-LEARN-1/2, F-LEARN-2 cierra un arco: el
VERIFICADOR (existencia, FP-rate < ε*, ejecución real) es el lever central de la auto-mejora segura.

### 7.6 El reward-hack NO emerge en STaR-imitación (CYCLE 32, H-LEARN-4)
**H-LEARN-4 (refutada con insight):** un verificador real DÉBIL NO se reward-hackea en un loop STaR de
IMITACIÓN, aun SEMBRANDO el atajo (echo del target) en el repertorio y con temperatura alta. exp019 (n=3):
weak degenerate(final)=0.085 ≈ strong=0.004 (el echo no domina, sin snowball). RAZÓN (refina Amodei 2016): la
imitación COPIA las auto-generaciones aceptadas (mayormente honestas), no MAXIMIZA la aceptación como RL → no
caza el atajo más barato; el reward-hack es patología de RL-maximización, no inherente a un verificador débil
bajo imitación. Matiz: el verificador FUERTE igual es muy superior (real_acc 0.745 vs weak 0.474, +0.27;
degenerate menor) y naive_all (sin filtro) degrada → la fuerza del verificador importa para la competencia.
Con H-LEARN-1/2/3, F-LEARN-2 cierra un arco maduro: el VERIFICADOR es el lever central de la auto-mejora segura.

### 7.7 Contrapunto RL del reward-hack (CYCLE 33, H-LEARN-5 — null de método)
**H-LEARN-5 (refutada como null de MÉTODO):** intento de confirmar causalmente que el reward-hack del
verificador débil es patología de RL-MAXIMIZACIÓN (no de la imitación). exp020 (mismo verificador/atajo que
exp019; sólo cambia el algoritmo: imitación STaR vs GRPO-lite RL; n=3): el hack NO emergió bajo GRPO-lite
(rl_weak degenerate 0.059 < imit 0.115). CONFOUND: el GRPO estable apenas-entrena (para no colapsar) → sin
ventana limpia a igual presión de optimización (RL estable apenas-entrena; RL agresivo colapsa real~0). Es un
límite de MÉTODO, no del mecanismo (la literatura/Amodei lo apoya; rl_strong degenerate=0.000 = el fuerte
suprime el echo incluso bajo RL). El contrapunto RL queda como future work (RL estabilizado / mayor escala);
el insight de H-LEARN-4 (imitación robusta) se sostiene solo. F-LEARN-2 cierra: H-LEARN-1/2/3/4 apoyadas,
H-LEARN-5 null de método → el VERIFICADOR es el lever central; la IMITACIÓN es la opción segura.

## 8. RESET v4 — del síntoma (eficiencia) a la raíz (R-VALOR) (2026-06-24)

Tras 34 ciclos centrados en la eficiencia (tesis "bytes-por-token / híbrido"), el dueño autorizó un RESET a
primeros principios. Se construyó el artefacto que el prompt fundacional pedía y faltaba: el **árbol de
descomposición raíz** (`decomposition_tree.md`) de *"¿qué es una inteligencia y por qué los enfoques
actuales no llegan a la raíz?"*, por excavación de **6 lentes independientes + auditoría adversarial +
síntesis**, anclado al código del lab (cazó 4 errores de fidelidad propios).

**Hallazgo central — convergencia (5/6 lentes): R-VALOR.** El verdadero primer problema no es la eficiencia
del decode (un SÍNTOMA), sino la **ausencia de una función-de-valor ENDÓGENA** que defina qué información
importa: comprimir-asimétrico, escribir/olvidar-selectivo, asignar-cómputo y consolidar son indefinibles
sin un escalar de valor. Raíces convergentes subordinadas: **R-INTERVENCIÓN** (la causa solo es
identificable si la distribución varía — límite informacional) y **R-PRIOR** (un prior fuerte es necesario;
su calidad fija la eficiencia muestral). La tesis bytes-por-token queda como restricción de **viabilidad**.

### 8.1 H-V4-1 (CYCLE 35, exp022) — valor endógeno vs predicción pasiva: MIXTA
Primer ataque a R-VALOR, en CPU, SIN verificador externo (mundo causal confundido; 3 agentes con idéntica
clase de modelo y update; sólo cambia la política: pasivo / info-gain / azar-activo; 24 seeds, step-parity).
**Resultado MIXTA:** demuestra limpiamente **R-INTERVENCIÓN** — la política PASIVA queda PLANA bajo
intervención por más presupuesto que reciba (flatness 0.013 → muro INFORMACIONAL, no de recursos), mientras
las políticas activas identifican la causa (B−A=+0.31); el hueco es INVISIBLE i.i.d. (|A−B|=0.04). Pero el
VALOR específico (info-gain) **no se aísla** de la "intervención activa": el azar-activo también lo logra
con presupuesto suficiente (B−C=−0.007). → R-INTERVENCIÓN a techo 'real'; R-VALOR 'asumido' (backlog);
genera **H-V4-1b** (aislar el valor en régimen presupuesto-chico/ruido-alto/espacio-grande). Es el patrón
"fracaso/mixta es información" (un bundle que aísla una mitad y afila la siguiente hipótesis).

### 8.2 H-V4-1b (CYCLE 36, exp023) — el valor info-gain NO está aislado: el lever es ACTUAR
Régimen DURO (D=40, clúster=8, ruido 0.25, 24 seeds) donde el azar NO cubre por fuerza bruta. **MIXTA,
inclinada a refutar el valor-como-info-gain:** el margen info-gain − azar-activo oscila alrededor de 0
(media **+0.004**; único pico K=16 +0.099 dentro del ruido std~0.18 y contradicho en K=32). Lo que SÍ
aguanta (replicado) es **ACTUAR ≫ observar** (C−A=+0.07→+0.36; A pasivo plano ~0.58-0.64). **El lever
robusto es la INTERVENCIÓN per se, NO el valor info-gain DISEÑADO** → "valor endógeno = info-gain" queda
descartado como lever; R-VALOR sigue abierto sólo en su forma fuerte (valor AUTO-generado). **Costo:** 360
modelos causales en **1.0 s** de CPU (~2.8 ms c/u). **Pivote (D-V4-2):** explotar R-INTERVENCIÓN como motor
barato (act-and-verify, ya apoyado por exp016-018).

### 8.3 Barrido de literatura v4 (CYCLE 37) — la convergencia con lo más actual (2023-2026)
Barrido web citado (`literature_v4.md`). Tres convergencias que mueven el rumbo:
1. **Corrobora exp023:** la literatura de active causal discovery dice que el muestreo activo gana al azar
   sólo en grafos GRANDES/DENSOS + presupuesto escaso + ruido bajo; a grafo chico/ruido alto **"random se
   vuelve muy competitivo"** (CAASL, arXiv:2405.16718, ~5-6% a d=10) — exactamente mi régimen. Mi null no es
   un bug: es el corner conocido. (Pero adaptativo puede usar O(log n) vs O(n): Choo&Shiragur UAI'23 → hay
   un régimen donde el valor SÍ ganaría; aún no lo medí.)
2. **R-VALOR en su forma fuerte tiene soporte:** objetivos ACTION-GROUNDED (no reconstrucción) sí tallan
   estructura causal — inverse-dynamics encoder 84% vs 59% a ~5M params CPU-scale (arXiv:2606.20104);
   empowerment correlaciona con desempeño SIN reward (EELMA, arXiv:2509.22504); Blahut-Arimoto hace
   empowerment SIN gradiente, corrible en CPU (arXiv:2510.05996). El info-gain que probé NO es buen proxy;
   el **empowerment** sí es candidato. Caveat (el null real): un transformer next-token YA induce SCMs
   en juguete (OpenReview tHr0vFbS3K) → R-VALOR debe batir a la predicción pasiva en la MISMA tarea.
3. **Camino barato a "inteligente que habla":** test-time compute óptimo con VERIFICADOR barato bate a
   escalar parámetros (Qwen2.5-0.5B > GPT-4o en mate dura con TTS verifier-based, >4× eficiente,
   arXiv:2408.03314); **"verifier-based ≫ verifier-free, la brecha crece con el cómputo"**. Backbone híbrido
   SSM-atención / RWKV-7 (corre en llama.cpp en CPU HOY) mata la pared del KV-cache (3-6× throughput
   GPU-medido). Backprop-alternativas: NO valen salvo que el cuello sea RAM (MeZO 12× memoria) — confirma
   H-BIO-3. → **El verificador (no los parámetros) es la pieza; eso ES R-INTERVENCIÓN.** Rumbo: substrato
   chico CPU + lazo act-and-verify barato.

### 8.4 H-V4-1c (CYCLE 38, exp024) — R-VALOR es REAL: el valor endógeno es la CONTROLABILIDAD (empowerment)
El info-gain no era el valor (exp023). Pero el **empowerment** (capacidad de canal acción→futuro, vía
Blahut-Arimoto, **sin reward ni verificador externo**) sí. Mundo con 3 tipos de factor: *controlable* (lo
fija la acción), *reloj* (predecible pero NO controlable), *aleatorio*. **APOYADA — inversión limpia:**
EMPOWERMENT = ctrl **1.71** bits / reloj **0.0** / rand 0.0; PREDICCIÓN pasiva = ctrl **0.0** / reloj
**1.71** / rand 0.0 (std ~0.005; costo **0.57 s** CPU). El empowerment **aísla lo controlable** y descarta
el reloj predecible-inútil; la predicción pasiva hace lo contrario — **ni siquiera VE lo controlable**.
**Conclusión:** para un AGENTE el valor de la información es **controlabilidad ≠ predictibilidad**; un valor
AUTO-generado existe, es CPU-barato y, a diferencia del info-gain, se distingue de lo trivial. **R-VALOR
confirmado real en su forma fuerte**, y se **unifica con R-INTERVENCIÓN** (el valor endógeno es sobre la
acción/control). Límite honesto: muestra el MECANISMO, no aún mejora downstream ni escala a lenguaje
(→ H-V4-1d / integrador).

### 8.5 Síntesis del reset v4 (estado al CYCLE 38) — el rumbo consolidado
Cuatro ciclos de evidencia propia + literatura convergen en un North Star coherente y barato:
- **Qué NO es el lever:** la predicción pasiva (muro informacional, exp022) ni el info-gain diseñado
  (≈ azar, exp023). Escalar parámetros tampoco (lit.: verifier-based TTS > params).
- **Qué SÍ:** **ACTUAR/INTERVENIR** (R-INTERVENCIÓN, exp022/023) con un valor endógeno de **CONTROLABILIDAD**
  (R-VALOR=empowerment, exp024). Las dos raíces se unifican: *el valor es sobre lo que puedo afectar; el
  mecanismo es actuar y aprender de la consecuencia.*
- **Arquitectura objetivo (fast+cheap+intelligent que habla):** substrato chico CPU (híbrido SSM / RWKV-7
  en llama.cpp, ya viable) + lazo **act-and-verify** barato con valor endógeno de controlabilidad/
  consecuencia + test-time compute guiado por verificador barato. El verificador/consecuencia, no los
  parámetros, es la pieza. **Próximo:** H-V4-1d (empowerment mejora una tarea downstream) y el integrador
  hacia el sustrato de lenguaje.
