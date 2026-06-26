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

### 8.6 H-V4-1d (CYCLE 39, exp025) — el empowerment como VALOR mejora la tarea (R-VALOR aplicado)
Falta el paso de "mecanismo" a "útil". Agente con CAPACIDAD LIMITADA k (atiende/controla sólo k de D
factores) que debe llevar los controlables a un objetivo. **APOYADA, contundente:** a k=n_ctrl=4 el score
de tarea es **EMPOWERMENT 1.000 / PREDICTIBILIDAD 0.250 (=azar puro) / AZAR 0.453** (emp−pred=+0.75; 0.835 s
CPU). Asignar por **predictibilidad es ANTI-útil** (peor que el azar: se va al reloj predecible-inútil). A
capacidad PLENA (k=D) las tres empatan en 1.0 → **la ventaja del valor existe sólo bajo recursos limitados**
(el régimen del lab). **Conclusión:** el valor endógeno (empowerment) no sólo mide (exp024) — **mejora al
agente** (exp025). El arco R-VALOR queda cerrado: real como mecanismo Y como lever. Justifica el integrador:
un razonador act-and-verify que asigna su cómputo/atención limitada por controlabilidad/consecuencia.
**Próximo (H-V4-1e / integrador):** dar el salto al sustrato de lenguaje.

### CYCLE 40 — H-V4-1e (INTEGRADOR): el salto al LENGUAJE, sobre el modelo propio

Hasta acá el arco R-VALOR (controlabilidad>predictibilidad) se demostró en mundos tabulares de juguete
(exp022-025). **H-V4-1e** lo cruza al **sustrato de lenguaje** y al **modelo propio del lab** (HybridLM
byte-level, entrenado desde cero en CPU), no a un GGUF externo. Tarea: suma byte-level con oráculo
chequeable como **verificador**. Lazo **act-and-verify** = *muestrear* (cada sample es una intervención en
la respuesta = R-INTERVENCIÓN) + *verificar* (quedarse con un sample sólo si pasa el checker). Pregunta: a
**igual presupuesto** de cómputo de test-time, ¿asignarlo por **controlabilidad/consecuencia** (empowerment
sobre el resultado verificado) gana al **azar** (uniforme) y a la **predicción-pasiva** (incertidumbre)?

**APOYADA en el régimen discriminante.** Barrido de presupuesto avg∈{2,3,4,6,8} samples/problema, 4 seeds
in-band (M=120 held-out). En el presupuesto ESCASO real (avg=3, el menor con cómputo libre para asignar):
**CONSEC 0.562 / AZAR 0.506 (+0.056) / PASIVA 0.490 (+0.073)**, ambas diferencias > 2σ(0.045) y > margen.
La **predicción-pasiva (incertidumbre) es la PEOR** de las tres en todo el rango discriminante — *anti-útil*,
porque malgasta cómputo en lo incierto-pero-no-controlable (ya resuelto o irresoluble). Es el control
DECISIVO del arco v4, ahora confirmado **en lenguaje**: controlabilidad ≠ predictibilidad. **Caveat honesto
(la curva completa):** a avg≤n_probe el extra=0 y las políticas son idénticas por construcción (degenerado);
a presupuesto generoso (avg≥6) + verificador perfecto el **azar alcanza/supera** (efecto techo). La ventaja
del valor vive **bajo ESCASEZ de cómputo** — exactamente la forma de exp025 (la ventaja era del régimen de
recursos limitados). **Conclusión:** primer ladrillo de "algo que razona barato" — TTS verifier-based
(convergente con arXiv:2408.03314) **guiado por controlabilidad**, sobre el modelo propio, unificando
R-INTERVENCIÓN + R-VALOR. **Próximo (H-V4-1f):** verificador ruidoso/parcial (exp017/018), señal de
consecuencia sin probe caro, y razonamiento multi-paso.

### CYCLE 41 — H-V4-1f: ¿el lever de control sobrevive a un verificador imperfecto?

exp026 demostró el lever con un **oráculo perfecto** — irreal. **H-V4-1f** mete ruido: verificador simétrico
`vnoise` (acepta una correcta con prob 1−vnoise; acepta una incorrecta con prob vnoise). El act-and-verify
**commitea el primer sample que el verificador acepta**; la accuracy se mide REAL (oráculo) → un falso
positivo commitea una respuesta mala y se castiga. Mismo presupuesto escaso (avg=3), barrido de ruido, 4
seeds in-band. **Resultado MIXTA, de dos caras.** Curva vnoise→CONSEC/AZAR/PASIVA/greedy:
`0.0:0.544/0.490/0.483/0.317 · 0.05:0.502/0.452/0.483 · 0.10:0.444/0.440/0.435 · 0.20:0.358/0.385/0.398`.

**Cara buena (robustez del método):** el lazo act-and-verify **nunca cae por debajo del greedy** en ningún
nivel de ruido probado (0.358 > 0.317 incluso a vnoise=0.20) — *samplear+verificar degrada con gracia, no
hace daño*. Y a vnoise=0 **reproduce exp026** (validación cruzada del lever). **Cara mala (fragilidad del
lever):** la *ventaja* de asignar por controlabilidad es **condicional a la calidad del verificador** —
significativa con error ≤~5% (Δazar +0.05), diluida a ~10% e **invertida** a 20% (la consecuencia pasa a ser
la peor). **Mecanismo:** la señal de consecuencia usa `solved_observed` (depende del veredicto del
verificador) → **hereda su ruido**; la pasiva-entropía no depende del verificador y por eso resiste mejor el
ruido (aunque es peor sin ruido). **Conclusión para el integrador:** la **calidad del verificador es
prerequisito** del lever de control, no un detalle de ingeniería. **Próximo (H-V4-1g):** una señal de
consecuencia **robusta-al-ruido** (divergencia de rollouts, sin etiquetar correctas) y/o un verificador
real-chequeable (código→sandbox, exp018) sobre lenguaje.

### CYCLE 42 — H-V4-1g: ¿una señal de control sin verificador es la cura a la fragilidad?

exp027 mostró que la señal de control de exp026 hereda el ruido del verificador. **H-V4-1g** prueba una señal
**verifier-free**: asignar por **consenso emergente** de los rollouts (peso = p_top si p_top<1, si no 0; p_top
= fracción de la respuesta plural en el probe — *self-consistency*, Wang 2022), que no toca el verificador. 4
políticas (azar/pasiva/CONSEC_V verifier-dependiente/CONSEC_FREE verifier-free), commit verifier-based igual
para todas (aísla la asignación), barrido de ruido, 4 seeds in-band. **Resultado MIXTA.** Curva
vnoise→AZAR/PASIVA/CONSEC_V/CONSEC_FREE: `0.0:0.642/0.629/0.710/0.640 · 0.1:0.529/0.525/0.560/0.531 ·
0.2:0.446/0.485/0.412/0.444`.

**Robusta, sí:** a vnoise=0.2 CONSEC_FREE (0.444) supera a CONSEC_V (0.412, ya la peor) por +0.031 — su
asignación no se corrompe con el ruido. **¿Recupera el edge? No:** a verificador bueno (≤0.1) CONSEC_V
**domina** (0.710/0.560) y CONSEC_FREE sólo **empata** a azar/pasiva. **Conclusión honesta:** no existe una
señal de asignación única dominante — el control verifier-dependiente paga cuando el verificador es confiable
y colapsa cuando no; el verifier-free es robusto pero **no es un free lunch**. **Nota de método:** el test de
regresión cazó que mi primera señal `p_top·(1−p_top)` era *simétrica* (no distinguía caos 1/3 de consenso
2/3); corregida a consenso-emergente monótono, el MIXTA se mantuvo → el null es del fenómeno, no del bug.
**Próximo (H-V4-1h):** una política **adaptativa** que estime la fiabilidad del verificador (acuerdo
verificador-vs-consenso) y **mezcle** las señales según ese estimado.

### CYCLE 43 — H-V4-1h: la política adaptativa que cierra el integrador (capstone 40-43)

exp028 cerró que no hay señal de asignación única dominante. **H-V4-1h** da la salida: una política
**adaptativa** que estima cuánto confiar en el verificador y mezcla las señales. La fiabilidad `r` se estima
**sin ground-truth** por **test-retest**: se consulta el verificador dos veces sobre cada muestra del probe y
se mide su auto-acuerdo (`r = clip(2·P(coinciden)−1, 0, 1)`). Crucial: este estimador NO depende del consenso
del modelo (un primer intento basado en "el verificador aprueba el consenso del modelo" **fracasó** —el modelo
débil tiene mal consenso, dando r≈0 aun con verificador perfecto; el smoke lo expuso y se reemplazó). El peso
de asignación es `w = r·CONSEC_V + (1−r)·CONSEC_FREE`. **Resultado APOYADA, no-regret.** Curva
vnoise→CONSEC_V/CONSEC_FREE/ADAPT(r_est): `0.0:0.690/0.621/0.688(r=1.00) · 0.1:0.527/0.550/0.535(r=0.61) ·
0.2:0.415/0.415/0.437(r=0.39)`. A verificador bueno (r≈1) ADAPT **mantiene el edge** de CONSEC_V (0.688≈0.690);
a ruido alto (r≈0.39) **escapa el colapso** y hasta **supera a las dos puras** (0.437 > 0.415) — la mezcla
hedgea. `worst_regret = +0.008`: ADAPT nunca queda por debajo del mínimo de sus componentes. **Cierra el
sub-arco integrador 40-43:** el lever de control es **real** (40), **frágil** al verificador (41), **sin señal
única dominante** (42) y se **resuelve** con una política adaptativa calibrada por la consistencia del
verificador (43). El integrador de un paso queda diseñado y verificado sobre el modelo propio del lab.
**Límite honesto:** el test-retest detecta ruido *aleatorio*, no *sesgo sistemático*. **Próximo gran salto
(H-V4-1i):** razonamiento **multi-paso** (donde control y ruido se componen) y verificador real-chequeable
(código→sandbox).

### CYCLE 44 — H-V4-1i: el salto a MULTI-PASO — ¿verificar el proceso o el resultado?

Cerrado el integrador de un paso (40-43), **H-V4-1i** da el gran salto a razonamiento de varios pasos, donde
los errores se **componen**. Tarea: una cadena de K sumas mod 20 (cada paso in-distribution) sobre el modelo
propio; la respuesta correcta es la **traza completa** [r₁..r_K] (no un único número — eso evita el piso de
suerte que una primera versión tenía). Dos estrategias a **igual cómputo** (k·K llamadas): **step-wise
act-and-verify** (verifica y corrige CADA paso) vs **end-to-end best-of-k** (verifica sólo la traza final).
**Resultado MIXTA.** Curva K→END_TO_END/STEP_WISE/gap: `K1:0.667/0.692/+0.025 · K2:0.317/0.448/+0.131 ·
K4:0.046/0.219/+0.173 · K6:0.004/0.092/+0.088`.

El **gap absoluto** no crece monótono (cae a K=6) — pero por una razón honesta: con presupuesto por-paso
**fijo** (k=4), *ambas* estrategias colapsan a 0 en cadenas largas. La señal real está en la **ventaja
relativa** `step_wise/end_to_end`, que crece **monótona y enorme**: 1.04× → 4.8× (K4) → **23× (K6)**. La
verificación intermedia (**supervisión de proceso**, convergente con *Let's Verify Step by Step*, Lightman
2023) **frena drásticamente el compounding pero no lo elimina** a presupuesto por-paso fijo: end-to-end se
desploma como ≈p^K mientras step-wise decae mucho más lento. **Conclusión:** el lever del razonamiento
multi-paso es verificar el **proceso**, no sólo el resultado; y para cadenas largas hay que **escalar/adaptar
el presupuesto por paso** — exactamente el control adaptativo del CYCLE 43 aplicado per-step. **Próximo
(H-V4-1j):** control adaptativo per-step en cadenas largas + backtracking/abstención + verificador ruidoso
per-step.

### CYCLE 45 — H-V4-1j: presupuesto adaptativo per-step — rescatar las cadenas largas

CYCLE 44 dejó un techo: con presupuesto por-paso **fijo**, las cadenas largas colapsan igual (se malgasta
cómputo en los pasos fáciles). **H-V4-1j** aplica el control adaptativo (43) *a lo largo de la cadena*: a
**igual cómputo total** `B=avg·K`, ¿gastar **hasta verificar** con un pool compartido (parar en cuanto un
paso verifica, reinvertir lo ahorrado en los pasos difíciles) rescata las cadenas largas? **Resultado MIXTA,
rescate fuerte.** Curva K→UNIFORME/ADAPT/gain: `K2:0.446/0.598/+0.152 · K4:0.190/0.423/+0.233 ·
K6:0.119/0.333/+0.215 · K8:0.058/0.240/+0.181`.

El presupuesto adaptativo **gana en todas las longitudes** (+0.15..+0.23) y **rescata las cadenas largas**:
a K=8 el uniforme colapsa a 0.058 mientras el adaptativo aguanta **0.240 (4.1×)**, *sin gastar un solo
sample más*. Es MIXTA solo porque el gain **absoluto** no es estrictamente monótono (pico en K=4, baja a K=8
porque a presupuesto total fijo incluso el adaptativo satura) — la ventaja **relativa** sí crece monótona
(1.3×→4.1×). **Mecanismo:** parar en cuanto un paso verifica libera cómputo para los pasos difíciles. **El
integrador multi-paso queda definido:** verificación de **proceso** (44) + presupuesto **adaptativo per-step**
(45). **Cota honesta:** a K extremo hace falta más presupuesto total, y cuando un paso agota su presupuesto
sin verificar, descarrila (falta backtracking/abstención). **Próximo (H-V4-1k):** backtracking/abstención +
verificador ruidoso per-step (reusando la política calibrada de 43 por paso).

### CYCLE 46 — H-V4-1k: abstención calibrada — "saber cuándo no sé" en multi-paso

CYCLE 45 dejó dos cabos: cuando un paso agota su presupuesto sin verificar, el sistema commitea basura y
descarrila *en silencio*; y el verificador per-step era perfecto. **H-V4-1k** los ataca juntos: verificador
**ruidoso** per-step + **abstención** (si ningún sample de un paso verifica, la cadena dice "no sé" en vez de
seguir). Métricas: **precisión** sobre lo respondido y **cobertura**, vs la accuracy de commitear-siempre.
**Resultado MIXTA, lever de honestidad.** Curva K|vnoise→COMMIT/PREC/COV: `2|0.0:0.252/1.000/0.248 ·
2|0.1:0.217/0.647/0.317 · 2|0.2:0.169/0.295/0.338 · 6|0.1:0.002/0.125/0.017`.

A cadenas cortas + verificador decente la abstención es un **lever fuerte de honestidad**: las cadenas que
responde son mucho más confiables — precisión **1.000** (vs 0.252 commitando-siempre) a verificador perfecto,
y **0.647** (vs 0.217) a ruido moderado, con cobertura útil (~0.3). Convierte errores **silenciosos** en
abstenciones **flagueadas**. **Pero** es dependiente de régimen: en cadenas largas la cobertura **colapsa**
(a K=6, ~0.01 — abstiene casi todo, porque toda cadena larga falla en *algún* paso) y bajo ruido la precisión
**se erosiona** (los falsos positivos pasan el filtro), conectando de nuevo con 41/43 (el lever es tan bueno
como el verificador que lo dispara). **Cierra el barrido de realismos del integrador multi-paso:** proceso
(44) + presupuesto adaptativo (45) + **modo honesto** (46). **Próximo (H-V4-1l):** **backtracking** —
reintentar el paso fallido en vez de abstener la cadena entera, para recuperar cobertura sin perder precisión.

### CYCLE 47 — H-V4-1l: backtracking/retry — ¿insistir rescata la cobertura?

CYCLE 46 dejó el colapso de cobertura: en cadenas largas, abstenerse al primer paso fallido abstiene *todo*.
**H-V4-1l** prueba el remedio obvio: **retry** — ante un paso que no verifica, darle una segunda tanda de
muestras del pool (con contabilidad gastar-hasta-verificar, los pasos fáciles dejan holgura) antes de abstener.
**Resultado MIXTA.** Curva K|vn→ABST_cov/RETRY_cov(Δcov) prec: `6|0.0:0.30/0.37(+0.07)p1.00 ·
6|0.1:0.51/0.70(+0.19)p0.18 · 6|0.2:0.75/0.86(+0.11)p0.04`.

Retry **recupera cobertura** material en cadenas largas (Δcov **+0.19** a K=6/vn=0.1) **sin dañar precisión**
— cumple literalmente lo pre-registrado. **Pero** su valor está **gateado por el verificador**: donde recupera
mucho (ruido alto) la precisión absoluta es baja (0.18, 0.04 — *rescata cadenas confiadamente-mal*), y donde
la precisión es alta (verificador perfecto) el gain es sub-margen (+0.07). El colapso de cobertura **no se
arregla insistiendo**. *(Nota de método: el piso de "cobertura útil" (precisión ≥0.5) es post-hoc; lo reporto
y NO lo uso para forzar un refutado — la pre-registración se cumple, de ahí MIXTA y no REFUTADA.)*

**Cierra el barrido de mecanismos del integrador multi-paso (44-47):** proceso (44) + presupuesto adaptativo
(45) + abstención (46) + backtracking (47). **Los cuatro convergen al mismo cuello de botella:** la
**calidad/precisión del verificador y del paso**. **Giro estratégico del roadmap:** el próximo lever NO es más
orquestación de cómputo, sino el **sustrato** — un verificador **real-chequeable** (código→sandbox, estilo
exp018) y **mejor precisión por paso** (H-V4-2).

### CYCLE 48 — H-V4-2: el sustrato se mejora a sí mismo, y la mejora se amplifica (capstone del arco v4)

El sub-arco 44-47 concluyó que toda la orquestación de cómputo topa con la **precisión por paso**. **H-V4-2**
cierra el círculo: el lazo act-and-verify **no sólo asigna cómputo — genera datos verificados que mejoran el
sustrato barato**, y esa mejora se **amplifica** en multi-paso. Sobre el modelo propio: se generan auto-salidas,
se separan las **verificado-correctas** (oráculo) de un **control** del mismo tamaño con salidas sin verificar,
y se fine-tunean dos copias. **Resultado APOYADA.** Precisión **por paso**: base 0.317 → **verified 0.419**
(+0.102) vs **control 0.258** — el control sin verificar incluso **empeora** el base, así que el motor es la
**señal de corrección, no el volumen** (replica exp016 en este sustrato). Y la mejora **se amplifica**: en
cadena greedy (sin orquestación, para aislar el sustrato) el ratio verified/base **crece monótono** con la
longitud — `1.32× (K1) → 1.93× (K2) → 2.71× (K3)`. Una mejora *modesta* del paso (+0.10) rinde una mejora
*compuesta* en multi-paso.

**Cierra el arco v4 (CYCLE 40-48):** el integrador del lab es un **lazo de auto-mejora**, no sólo orquestación.
(1) Asigna cómputo test-time por **controlabilidad** + fiabilidad del verificador (40-43). (2) Lo extiende a
**multi-paso** — proceso, presupuesto adaptativo, abstención, backtracking (44-47). (3) Genera datos
**verificados** que mejoran la **precisión por paso** del sustrato barato, mejora que se **amplifica** en lo
largo (48). Unifica **R-INTERVENCIÓN** (actuar+verificar) y **R-VALOR** (valor de controlabilidad) sobre el
modelo propio CPU-first. *(Cota honesta: base débil → la cadena greedy a K≥4 cae al piso de medición; la
amplificación se demostró a K≤3.)* **Próximo (H-V4-2b):** iterar el lazo varias rondas, verificador
real-chequeable (código→sandbox) y razonamiento no-aritmético — el camino hacia *"algo que habla y razona,
barato"*.

### CYCLE 49 — H-V4-2b: ¿el lazo de auto-mejora es un motor sostenible?

CYCLE 48 mostró que UNA ronda de auto-mejora verificada mejora el sustrato. Para que sea un **motor** autónomo
(no un truco de una vez), debe ser **estable a través de rondas** — el riesgo conocido es el *colapso* tipo
STaR (entrenar sobre la propia distribución estrecha y degradar). **H-V4-2b** itera el lazo R=4 rondas
(generar → filtrar verificado → reentrenar in-place) midiendo precisión por paso, accuracy de cadena y
**diversidad** cada ronda. **Resultado APOYADA.** Paso por ronda (prom): `0.300→0.472→0.456→0.481→0.508`
(+0.208); en el mejor seed un base débil se **bootstrappea a fuerte** (paso 0.30→**0.78**, cadena 0.19→**0.75**).
La accuracy de cadena sigue (`0.187→0.436`). **Sin colapso de precisión** — el filtro de *corrección* mantiene
el lazo sano (consistente con el anti-colapso del CYCLE 11). **Caveat honesto:** la **diversidad declina
monótona** (`0.040→0.021`, ~0.52× la inicial, justo en el borde del umbral) — un *narrowing temprano*: en
rondas largas el lazo necesitaría **monitorear/inyectar diversidad** para no colapsar. *(La métrica
fracción-distintas está acotada por el vocab chico de la suma; se usa como señal relativa entre rondas.)*

**Lo que cierra:** el integrador del lab puede **mejorarse solo, de forma autónoma y sostenible** — el lazo
act-and-verify no sólo razona y mejora el sustrato (48), sino que **itera de forma estable** (49). El motor de
auto-mejora del North Star está demostrado en pequeño. **Próximo (H-V4-2c):** el **monitor de diversidad** + el
**techo del bootstrapping** (cuántas rondas hasta plateau) + verificador real-chequeable (código→sandbox) para
tareas más ricas que la aritmética.

### CYCLE 50 — H-V4-2c: una guardia barata controla el narrowing y sube el techo

CYCLE 49 dejó un caveat: la diversidad del lazo iterado declina (narrowing). **H-V4-2c** prueba una **guardia
barata** — *dedup* de los ejemplos verificados + *replay* de datos semilla de la verdad — contra el lazo
**plano**, sobre R=6 rondas. **Resultado APOYADA.** El lazo **plano** trepa pero **errático**
(`0.300→0.442→0.475→0.536→0.425→0.547→0.642`, con un bajón en la ronda 4) y su **cobertura** de prompts se
**estanca** (~180). El **guarded** trepa **suave y más alto** (`→0.697→0.692`, techo 0.692 vs 0.642), con
**cobertura creciente** (175→**202**) y **sin costo de precisión**. **Mecanismo:** el plano entrena con los
verificados *con frecuencia* → se machaca en los correctos fáciles/frecuentes (overfit, se estanca); el
**dedup** quita ese sesgo de frecuencia y el **replay** reinyecta señal de la verdad → el lazo cubre **más del
espacio de problemas** y trepa más. *(Caveat honesto: la métrica diversidad-de-respuestas colapsa para ambos
porque está acotada por el vocab chico de la suma; la señal válida de narrowing es la **cobertura de
prompts**.)*

**Cierra el sub-arco de auto-mejora (48-50):** una ronda mejora el sustrato y se amplifica en multi-paso (48) +
iterar es un **motor estable y fuerte** (49) + una **guardia barata controla el narrowing y sube el techo**
(50). El lazo de auto-mejora del lab es **autónomo, sostenible y controlable sin un modelo más grande** — justo
lo que pide el North Star (*intelligent que mejora, barato*). **Próximo (H-V4-3):** salto a una tarea más
**rica** con **verificador real-chequeable** (código→sandbox), donde el verificador es real y la diversidad no
está acotada por un vocab chico.

---

# Corrida 51-60 — el verificador, el valor endógeno, y su unión (síntesis)

Esta corrida (autónoma, hacia un deadline) produjo dos arcos verificados y su unificación. Todos los ciclos
pasaron por las compuertas del engine (hipótesis pre-registrada con DoD, decisión aceptada por el ledger, techo
real, analogía de 7 etapas, `verify_no_loss=OK`) y tienen test de regresión.

## Arco VERIFICADOR-REAL (51-55) — el verificador es el motor; la guardia compra robustez
El sub-arco de auto-mejora (48-50) se había probado sobre la SUMA con oráculo EXACTO. La corrida lo llevó a un
**verificador chequeable REAL** (un sandbox que EJECUTA la expresión generada, no un oráculo que ya sabe la
respuesta) y lo estresó:
- **51 (H-V4-2d, APOYADA):** el lazo iterado + guardia GENERALIZA del oráculo exacto al verificador ejecutable,
  sin colapso ni reward-hack — el VERIFICADOR (no el tipo de oráculo) es el motor.
- **52 (H-V4-2e, APOYADA):** desde un base DÉBIL (0.08) el lazo bootstrapea a 0.93; con base débil la GUARDIA
  (replay limpio de la verdad) es CRÍTICA — resuelve el cold-start que el lazo plano no puede.
- **53 (H-V4-2f, APOYADA):** la tolerancia al ruido del verificador TRANSFIERE del oráculo (ε*≈0.15) al
  verificador real, y la guardia SUBE el umbral a ε*=0.50 (el replay limpio diluye la contaminación).
- **54 (H-V4-2g, APOYADA — capstone):** los dos estresores realistas (ruido + arranque débil) COEXISTEN — el
  lazo bootstrapea bajo 30% de falsos positivos desde casi-cero (ε*_coldstart=0.30).
- **55 (H-V4-2h, MIXTA):** ante un verificador con SESGO sistemático (off-by-one sembrado), el lazo plano queda
  PINNED (no deriva runaway, consistente con la barrera de discovery) y la guardia DEFIENDE (recupera precisión,
  suprime el sesgo). El replay limpio es defensa también contra sesgo estructural, no sólo ruido.

**Tesis del arco:** el verificador (su corrección) es el lever de 1ra clase; la guardia *dedup+replay-limpio* es
el mecanismo de robustez ante verificadores imperfectos (ruido, cold-start, sesgo).

## Sub-arco R-VALOR (56-59) — la RAÍZ PRIMERA, ahora con evidencia POSITIVA
El reset v4 nombró a **R-VALOR** (un valor ENDÓGENO que defina qué información importa) como la raíz primera, con
confianza ALTA en que es la convergencia pero BAJA en que sea *resoluble*. Esta corrida la atacó y obtuvo la
primera evidencia positiva del lab:
- **56 (H-V4-1b, APOYADA):** el valor de *info-gain* (elegir qué consultar) se AÍSLA del de *intervenir*
  (actividad) — pero sólo con el INSTRUMENTO FIEL (post_on_cause, masa sobre la causa verdadera). La *accuracy*
  downstream SATURABA y enmascaraba el valor: ése era el bug de la MIXTA de exp022 (CYCLE 35).
- **57 (H-V4-1c, APOYADA):** el agente puede MEDIR ese valor por su PROPIA confianza calibrada, SIN oráculo —
  rankea políticas igual que la verdad y es confiable con la política correcta; el azar-activo da confianza
  engañosa (confiado-pero-equivocado).
- **58 (H-V4-1d, MIXTA):** en un mundo NO-estacionario (la causa cambia tras un commitment profundo), el agente
  committed se atasca y el OLVIDO dirigido por valor adapta (parcial, presupuesto corto); sweet spot
  estabilidad-plasticidad. Liga R-VALOR a la MEMORIA (escribir≡olvidar).
- **59 (H-V4-1e, APOYADA):** el OLVIDO ADAPTATIVO por SORPRESA (olvidar sólo cuando las predicciones se
  contradicen) detecta el cambio SIN supervisión y logra el trade-off estabilidad-plasticidad endógeno. Une la
  confianza/sorpresa (57) con el olvido (58).

**Tesis del sub-arco:** existe un lazo de valor endógeno cerrado — el sistema juzga QUÉ información vale
(confianza calibrada) y CUÁNDO dejó de valer (sorpresa → olvido), sin oráculo ni aviso externo. R-VALOR pasa de
"resoluble = confianza BAJA" a "resoluble con evidencia positiva en juguete = confianza MEDIA".

## Unificación (60) — los dos arcos se tocan por la CALIBRACIÓN
- **60 (H-V4-2i, MIXTA):** la confianza endógena (auto-consistencia del modelo) reemplaza PARCIALMENTE al
  verificador externo del lazo de auto-mejora, GATEADA por la calibración: con base calibrada supera a no-filtrar
  y captura parte del beneficio sin oráculo; con base mal-calibrada COLAPSA (consistente-pero-equivocado refuerza
  errores). Confirma el CYCLE 57 en el sustrato de auto-mejora: la confianza propia sólo sirve donde el modelo ya
  es competente.

## Qué queda
H-V4-3 (calidad del prior) y H-V4-4 (techo de recall = optimización) siguen ABIERTAS. H-V4-5 (escribir≡olvidar)
tiene evidencia PARCIAL (falta la ablación que ate la memoria a R-VALOR). Todo es en juguete (bayesiano numpy +
HybridLM tiny): falta escala, un mundo no-de-juguete, y un verificador de código real (gated por la capacidad del
modelo). El siguiente paso natural de la unificación es el GATING EXPLÍCITO: usar el filtro endógeno (confianza)
sólo donde la calibración estimada es alta, reservando el verificador externo para el resto.

---

# Corrida 61-66 — gating explícito y el arco de la MEMORIA (síntesis)

Tras la corrida 51-60 (verificador-real + R-VALOR + unificación), otros seis ciclos cerraron el gating explícito
y el arco R-VALOR x memoria.

## Gating explícito (62) — el agente que sabe cuándo confiar en sí mismo
- **62 (H-V4-2j, MIXTA):** el agente estima su calibración con un probe barato y DECIDE: usa la auto-consistencia
  (endógeno) donde es confiable y cae al verificador externo donde no. Es ROBUSTO (nunca colapsa como la
  auto-consistencia pura), aunque la estimación ruidosa no iguala al verificador en el régimen débil. Es
  meta-cognición barata: saber cuándo sabe.

## Arco R-VALOR x MEMORIA (58·63-66) — qué/cuándo/cómo recordar, de señales endógenas
El North-Star pide un valor que decida "qué información merece predecirse, escribirse, recordarse u olvidarse".
Este arco lo ataca en un mundo no-estacionario:
- **58 (H-V4-1d):** el olvido dirigido por valor adapta a un cambio donde el committed se atasca (parcial).
- **59 (H-V4-1e):** el olvido ADAPTATIVO por SORPRESA detecta el cambio sin supervisión -- óptimo para un cambio aislado.
- **63 (H-V4-1f):** en no-estacionariedad RECURRENTE el committed se atasca PROGRESIVAMENTE; el óptimo de olvido
  DEPENDE del régimen (constante para recurrente, surprise-gated para aislado).
- **64 (H-V4-1g):** el meta-olvido (modula el decay por su sorpresa) adapta en dirección correcta pero no iguala
  el óptimo (el trade-off lo limita).
- **65 (H-V4-1h, REFUTADA):** un piso constante + sorpresa no cierra el caveat -- el trade-off estabilidad-
  plasticidad es FUNDAMENTAL para un controlador que sólo modula la TASA.
- **66 (H-V4-1i, CIERRE):** un SELECTOR de ESTRATEGIA (clasifica el régimen de su sorpresa y conmuta committear
  <->olvidar-fuerte) alcanza el ÓPTIMO en ambos regímenes -- la decisión DISCRETA vence el trade-off donde el
  escalar fallaba.

**Tesis del arco:** la meta-cognición de memoria es una decisión de MODO (committear vs olvidar-fuerte), no de
intensidad, seleccionada del régimen de no-estacionariedad que el agente clasifica de su PROPIA sorpresa. Junto a
la confianza calibrada (qué información vale, CYCLE 57), la sorpresa (cuándo/cómo olvidar) completa el lazo de
VALOR ENDÓGENO: el sistema juzga qué vale, cuándo deja de valer y cómo recordarlo, sin oráculo ni aviso externo.
Conecta R-VALOR (raíz primera) con H-V4-5 (escribir≡olvidar).

## Estado global (51-66)
Cuatro arcos cerrados: VERIFICADOR-REAL (51-55), R-VALOR (56-59), UNIFICACIÓN/gating (60-62), R-VALOR x MEMORIA
(58·63-66). 16 ciclos, todos por las compuertas del engine (verify_no_loss=OK), tests verdes, decisiones
D-V4-16..D-V4-30 aceptadas por el ledger. Diferido: H-V4-4 (recall=optimización, por cómputo). Abierto: H-V4-3
(calidad del prior). Todo en juguete (bayesiano numpy + HybridLM tiny): la escala y un mundo no-de-juguete siguen
pendientes, pero R-VALOR pasó de "resoluble = confianza BAJA" a "resoluble con evidencia positiva = confianza
MEDIA" en el sustrato disponible.

---

# Veredicto de la corrida 51-70 — R-VALOR aterriza la inteligencia (síntesis global)

20 ciclos (todos verificados, verify_no_loss=OK). El reset v4 nombró a R-VALOR raíz primera con confianza ALTA en
que es la convergencia pero BAJA en que sea RESOLUBLE. Esta corrida la mueve a confianza MEDIA y muestra que
R-VALOR aterriza las demás raíces:

- **R-VALOR resoluble (evidencia positiva):** valor endógeno (info-gain) AISLADO de la actividad con el
  instrumento fiel (56), MEDIBLE por la confianza calibrada del agente sin oráculo (57), con la sorpresa dirigiendo
  el olvido en no-estacionariedad (58-66).
- **aterriza la MEMORIA:** escribir≡olvidar es rate-distortion por valor (70) -- ablar el valor colapsa la ventaja
  de la memoria a aleatoria; el selector de estrategia (66) elige cómo recordar del régimen clasificado de la sorpresa.
- **aterriza el VERIFICADOR:** auto-mejora robusta con verificador real + guardia (51-55); la confianza endógena
  reemplaza parcialmente al verificador externo gateada por calibración (60-62).
- **aterriza el PRIOR:** la calidad del prior fija la eficiencia muestral (69); un buen prior es valor a priori
  sobre la estructura.

Honesto: la ESCALA y un mundo no-de-juguete quedan pendientes; H-V4-4 (recall) diferida; el selector de 3
regímenes MIXTA; la modulación de tasa de olvido tiene un techo (el trade-off es fundamental -> elegir la
ESTRATEGIA, no el ritmo).

**Cierre:** R-VALOR -- un escalar de valor endógeno, estimable sin oráculo de info-gain/confianza/sorpresa --
define qué predecir, qué escribir/olvidar, cómo recordar, qué verificar y qué prior elegir. Demostrado en juguete;
la frontera es la escala. (Método research-as-code: cada ciclo con hipótesis pre-registrada, DoD, decisión por el
ledger, techo real, analogía, test de regresión y verify_no_loss=OK; honestidad anti-Goodhart -- MIXTAS/REFUTADA
reportadas tal cual, H-V4-4 diferida con su razón.)

---

# Síntesis 79-103 — R-VALOR = control×relevancia: reconstrucción endógena y TEORÍA DE ASIGNACIÓN bajo realismo (2026-06-25/26)

> 25 ciclos verificados (engine: hipótesis pre-registrada + DoD + decisión por el ledger + techo real + analogía 7
> etapas + test de regresión + verify_no_loss=OK). Honestidad anti-Goodhart: MIXTAS/REFUTADAS reportadas tal cual,
> caveats explícitos, reformulaciones de métrica documentadas sin mover el poste. Todo CPU; numpy (<pocos s, 48 seeds)
> salvo el lazo cerrado real (PyTorch CPU, ~min, 4 seeds).

## 3.X TESIS UNIFICADA: R-VALOR = CONTROLABILIDAD × RELEVANCIA (79-82)
R-VALOR (el valor referido al objetivo) se RECONSTRUYE de dos marginales ENDÓGENAS: la controlabilidad (empowerment,
R-CONTROL) y la relevancia (el verificador de auto-mejora). Predicción y control NO son rivales de R-VALOR sino sus dos
marginales (la predicción pasiva malgasta en lo predecible-inútil, el empowerment en lo controlable-inútil). 79 acota
(empowerment = marginal-de-controlabilidad, no valor universal), 80 reconstruye (producto de marginales), 81 unifica el
verificador como marginal-de-relevancia, 82 lo hace totalmente endógeno (ambas marginales ruidosas, sin oráculo).

## 3.Y GAP #2 — la factorización producto (83-86)
El producto ctrl×rel es un PRIOR DE COMPLEMENTARIEDAD: robusto salvo bajo sustitutos (83); un combinador APRENDIDO
(ridge poly2) recupera bajo sustitutos, noise-gated (84); el noise-gating es una pendiente que la calidad del feedback
destraba (85); el aprendido NESTA el producto y lo DOMINA sobre una compuerta de feedback -> detectar el régimen es
innecesario (86). Política: combinador aprendido si el feedback es adecuado, producto si es pobre.

## 3.Z FEEDBACK-REALISMO (87-88)
La política always-learn/greedy es robusta bajo feedback ACTION-GATED (87) y bajo CONCENTRACIÓN extrema del soporte (88):
el greedy recupera la forma de sustitutos sin explorar; R-INTERVENCIÓN no liga en régimen ESTACIONARIO.

## 3.AA EL SALTO GRANDE — lazo de acción-consecuencia REAL (89-94)
La política R-VALOR se aterriza de un valor sintético suave a un VERIFICADOR CHEQUEABLE REAL (sandbox exp018 que EJECUTA
el candidato) y a un LAZO CERRADO con el GENERADOR de MODELO REAL (HybridLM propio):
- 89: sobrevive el salto smooth→discrete (no-regret donde el producto es Bayes-óptimo; recupera donde el echo lo vuelve
  relevancia-dominante; el veredicto discreto no rompe el aprendizaje).
- 90-92 (R-PRIOR): el poly2 NO es universal (falla en media no-nesteable, 90); la FORMA del prior fija la eficiencia
  muestral (un prior matcheado recupera a fracción del costo, 91); el agente puede DESCUBRIR el prior de sus datos por CV
  (no-regret) pero un prior flexible lo hace innecesario (92). R-PRIOR/H-V4-3 de ABIERTA a APOYADA-en-juguete.
- 93: en el LAZO CERRADO real, la CONFIANZA ENDÓGENA (calibrada, corr~0.6 real) asigna la verificación escasa MUCHo mejor
  que el azar (yield) — pero confidence-greedy COLAPSA la diversidad (narrowing).
- 94: la guardia dedup+replay (CYCLE 50) rescata el downstream sin perder el yield -> RECETA del lazo: allocation por
  confianza + guardia de diversidad.

## 3.AB TEORÍA DE ASIGNACIÓN R-VALOR bajo realismo (95-103) — la REGLA GENERAL
La asignación de un recurso escaso por valor estimado, caracterizada axis por axis:
- **Objetivo NO-aditivo (gap #4):** el valor es MARGINAL en la AGREGACIÓN verdadera, no absoluto: top-k falla bajo
  submodular/cobertura (95) y bajo vector egalitario asimétrico (100); el greedy por ganancia marginal recupera. El
  'balance' multi-objetivo es la forma vectorial de la cobertura/diversidad.
- **Costo de acción HETEROGÉNEO:** R-VALOR es valor-POR-COSTO (knapsack) para objetivos ADITIVOS; para objetivos que
  SATURAN (cobertura) el costo importa menos (cubrir manda). Objeto-dependiente (101).
- **No-estacionariedad:** el combinador debe OLVIDAR (decay > full-history, 97); bajo drift + observación estrecha la
  EXPLORACIÓN liga (98, R-INTERVENCIÓN reconciliada — la distribución debe VARIAR); la exploración SURPRISE-GATED domina
  al ε-fijo (99). La ABLACIÓN (103) revela que el OLVIDO es la pieza DOMINANTE y la exploración un sustituto redundante
  dado decay (bajo reward action-gated) — composición parcial, honesta.
- **Meta-nivel:** cuando ningún brazo de asignación domina (per-costo objeto-dependiente), el agente DESCUBRE la política
  correcta del feedback con un bandit no-regret (102, converso de 92 donde un default flexible la hacía innecesaria).

**REGLA GENERAL (83-103):** asignar por la GANANCIA MARGINAL en la AGREGACIÓN verdadera, dividida por el COSTO si el
objetivo es aditivo; con la base/prior que matchee la estructura del valor; bajo no-estacionariedad, descontar lo viejo
(decay) y, si no se puede olvidar o explorar es barato, explorar gateado por sorpresa; en el lazo cerrado real, con
guardia de diversidad / selección marginal por cobertura. La meta-decisión (qué política) es ella misma aprendible del
feedback cuando ninguna domina.

## 3.AC Lo que NO se resolvió (honesto)
La ESCALA (todo CPU/juguete; numpy + HybridLM tiny) — el salto a un sustrato no-juguete requiere GPU/Kaggle, fuera de la
corrida CPU. La integración de TODAS las piezas de la regla general en UN lazo cerrado real (cada axis se validó por
separado; el core 93-94/96 en el lazo real, las extensiones 95/97-103 en numpy). Objetivos sintéticos (cobertura/vector
/bump) — falta un objetivo de un lazo real no-sintético. H-V4-4 (techo de recall = optimización) sigue DIFERIDA.
