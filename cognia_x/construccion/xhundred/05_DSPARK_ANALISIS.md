# Dspark de DeepSeek — análisis honesto y cómo lo superamos SIN copiarlo

**Fecha:** 2026-07-03 · **Pedido del dueño:** analizar "Dspark" con honestidad, NO copiarlo,
guiarse por su PROCESO de investigación y MEJORAR mucho más lo que plantearon.
**Fuentes:** 4 informes de investigación web (identidad, proceso, resultados, solape) con el paper
completo leído (33 págs, PDF en el repo DeepSpec), + mediciones propias del repo (X1–X4 de
`04_MOM_GROKKING.md` §8, K1–K3 de `03_INVESTIGACION.md` §4, exp021/F-SPEED, XSPEED).
**Estado:** ANÁLISIS + PRE-REGISTRO de mejoras (predicciones y presupuestos escritos ANTES de correr).

---

## 1. Qué es (nombre exacto resuelto, fecha, hechos vs marketing)

**Nombre exacto resuelto: `DSpark`** (precedente Kimera/Chimera: verificar el nombre antes de
razonar sobre él). No es "DeepSpark" ni un modelo nuevo: es un **framework de speculative
decoding** de DeepSeek + Peking University, liberado el **2026-06-27**. El codebase de
entrenamiento/eval se llama **DeepSpec** ([github.com/deepseek-ai/DeepSpec](https://github.com/deepseek-ai/DeepSpec),
MIT); el paper (*"DSpark: Confidence-Scheduled Speculative Decoding with Semi-Autoregressive
Generation"*, 33 págs) vive SOLO dentro del repo — **no está en arXiv ni tiene peer review**:
tratarlo como technical report corporativo. Checkpoints en HF
([DeepSeek-V4-Pro-DSpark](https://huggingface.co/deepseek-ai/DeepSeek-V4-Pro-DSpark),
V4-Flash-DSpark): mismo peso del target V4 + módulo drafter adjunto.

**Hechos (lo que el paper sostiene con método):**
- Ataca latencia por-usuario del decode autoregresivo. Baseline honesto: su **MTP-1 de
  producción**, no un vanilla débil.
- Técnica: drafter **semi-autoregresivo híbrido** injertado sobre el target CONGELADO (reusa
  embeddings y LM head; sin draft model separado) = backbone paralelo estilo DFlash (logits de todo
  el bloque en 1 pasada) + **cabeza secuencial Markov liviana** (mira solo el token previo,
  low-rank r=256) que corrige el "multi-modal collision" del drafting puramente paralelo + **cabeza
  de confianza** (supervivencia por token, supervisada con la tasa ANALÍTICA de aceptación
  `1 − ½‖p_d−p_t‖₁`) + scheduler load-aware. Rejection sampling → salida **lossless** (distribución
  exacta del target).
- Loss de variación total (proxy analítico de la aceptación, no heurístico); pesos posicionales
  `w_k = exp(−(k−1)/γ)`; calibración post-hoc (Sequential Temperature Scaling): ECE 3–8% → ~1%.
- Números propios: **+60–85% tok/s/usuario en V4-Flash y +57–78% en V4-Pro vs MTP-1** en tráfico
  real; offline **+26.7–30.9% de largo aceptado vs EAGLE-3** y +16.3–18.4% vs DFlash (Qwen3
  4B/8B/14B, Gemma4-12B); un DSpark de 2 capas le gana a un DFlash de 5 (diseño > escala).

**Marketing (lo que NO es un hecho):**
- El **"hasta 661% de throughput"** que amplificó la prensa es un tope de frontera bajo SLA
  estrictos que **el propio paper etiqueta como "no representativo"** — el número serio es 57–85%
  por-usuario vs su propio MTP-1, en SU engine, con kernels propios. Distintos medios reportan
  celdas distintas (+51%, +400%, +661%): la dispersión ya es señal de cherry-picking editorial.
- "Speedup gratis": el drafter exige data-prep de **~38 TB de caché del target para un Qwen3-4B**
  y 1 nodo de 8 GPUs — costo que se amortiza a escala de serving masivo, no en nuestro régimen.

**Contexto que SÍ nos toca:** el pariente directo de nuestro MoM no es DSpark sino el
**post-training de V4** ([arXiv 2606.19348](https://arxiv.org/abs/2606.19348)): cultivo de
expertos por dominio (SFT+RL) → **consolidación en UN modelo por destilación on-policy**. Ellos
consolidan y pierden la modularidad; nosotros la conservamos (§4, §5-M5). Nota menor: V4 entrena
con **Muon** — el optimizador que nuestra receta K3 ya adoptó por medición propia (K2-A: Δ0.072
bpb); vamos con el consenso de frontera, no detrás.

---

## 2. Su proceso de investigación (las prácticas replicables, como lista)

Lo valioso de DSpark para nosotros NO es la técnica (que en nuestro sustrato ya está descartada
con números, §4): es el proceso. Extraído del paper como prácticas independientes de la técnica.
**Negrita = las 3 que este pre-registro adopta formalmente.**

1. **Métrica diagnóstica condicional ANTES de diseñar.** Inventaron *position-wise conditional
   acceptance* (aceptación en posición k condicionada a que 1..k−1 sobrevivieron) y con ella
   DESCOMPUSIERON el problema en dos causas medidas (capacidad en posición 1 vs *suffix decay*).
   El diseño responde a las dos mediciones, no a una intuición. → la adoptamos en M4.
2. Proxy chico → producción: TODAS las ablaciones en modelos abiertos (Qwen3/Gemma4) con datos
   abiertos; solo el diseño validado se llevó a V4. (Ya es nuestro método: toy→tiny→K3.)
3. **Baselines re-entrenados en igualdad.** EAGLE-3 y DFlash re-entrenados en el MISMO framework,
   mismos datos, horizontes alineados — nunca contra números de paper ajeno. → nos obliga a cerrar
   el asterisco de fairness de X3 (LoRA entrenó 6 min vs 12 del denso; control pendiente, M5).
4. Barrido de diseño en 2 ejes con análisis marginal (profundidad 1→5, γ∈{4..16}) Y el costo de
   cada componente medido (+0.2–1.3% latencia).
5. Compuerta de simplicidad: la cabeza RNN medía mejor que la Markov y la DESCARTARON como default
   por complejidad de despliegue. (Nuestro análogo ya operó: selector n-grams <5ms vs fusión 4×.)
6. Loss = proxy ANALÍTICO de la métrica final (aceptación es una identidad de la TV-distance, no
   una heurística). Lección anti-Goodhart resuelta por matemática donde nosotros la resolvimos por
   verificador externo (CYCLE 12).
7. Aislamiento de componentes: eval offline con el scheduler APAGADO; umbral estático para validar
   el estimador SOLO; recién después el sistema completo.
8. **Calibración medida antes de que una decisión use la señal.** El estimador discriminaba bien
   (AUC 0.81–0.90) pero era sobreconfiado (ECE 3–8%); temperature scaling en held-out → ECE ~1%;
   la aceptación en chat saltó 45.7%→95.7%. → la adoptamos en M1 (nuestro selector NUNCA midió su ECE).
9. El hardware como dato empírico: curva de capacidad perfilada UNA vez por engine (tabla O(1));
   al chocar con la realidad adaptaron el algoritmo y PROBARON formalmente (contraejemplo,
   Apéndice A) que la variante ingenua rompía la garantía lossless.
10. Honestidad interpretativa en producción: los +661%/+406% etiquetados como frontera no
    representativa; limitación declarada (costo fijo del draft irrecuperable en queries difíciles);
    justificación del baseline (MTP-1 era producción porque MTP-3/5 estático degrada throughput).
11. Release reproducible de la parte abierta: pipeline 3 etapas + checkpoints para modelos de la
    COMPETENCIA (Qwen, Gemma) — compró la credibilidad que los números solos no dan.

*Lectura honesta: este proceso ES el nuestro (pre-registro + gates + igual-wall + desvíos
append-only, validado en K1–K3 cazando 5 predicciones fallidas propias y 4 bugs). DSpark confirma
que el método barato-primero escala a frontier. Donde ellos van más lejos que nosotros hoy: 6
(supervisión analítica), 8 (ECE medido) y 3 (fairness estricta de baselines). Eso es exactamente
lo que las mejoras de §5 incorporan — el proceso, no el artefacto.*

---

## 3. Resultados: verificado por terceros vs claims

A 2026-07-03 (6 días post-release), el estado de verificación es:

| afirmación | fuente | estado |
|---|---|---|
| +60–85% (Flash) / +57–78% (Pro) por-usuario vs MTP-1 | paper/vendor | **solo claim** — cero reproducción independiente; varios medios lo dicen explícito ("independent deployments still need to validate") |
| +26.7–30.9% vs EAGLE-3 offline (Qwen3/Gemma4) | paper | solo claim, pero ES reproducible (código+checkpoints MIT liberados) — nadie lo corrió aún |
| "hasta 661% throughput" | prensa | **marketing** — el propio paper lo desactiva como frontera no representativa |
| desplegado en la API productiva de DeepSeek desde 27-06 | vendor + prensa | verificado INDIRECTO (no es demo de paper; pero el stack es cerrado — V4 preview) |
| adopción de ecosistema | GitHub/vLLM | verificado: issue vLLM [#46910](https://github.com/vllm-project/vllm/issues/46910) abierto 27-06 y cerrado con 3 asignados; SGLang y Docker Model Runner; >1.200 estrellas en días |
| chat 45.7%→95.7% con umbral calibrado | paper | solo claim; consistente internamente (AUC/ECE reportados) |

**Crítica técnica pública más citada** ([antirez](https://x.com/antirez/status/2071943446193938860)):
speculative de sesión única local + MoE "no va a ayudar demasiado: es genial para serving en GPUs
high-end con requests concurrentes". **Eso es NUESTRO hallazgo dicho por otro** — exp021 midió en
CPU bandwidth-bound que el draft separado hunde 0.37× y que la palanca dominante es el TAMAÑO del
modelo despachado (0.5B = 4.3× el 3B). Escepticismo adicional de HN/devs: bajo carga los tokens de
baja confianza consumen capacidad de batch (el throughput agregado puede EMPEORAR); en coding
multi-turno la aceptación cae al crecer el contexto.

**Limitaciones ADMITIDAS por DeepSeek:** ~38 TB de caché de training para un 4B; la confianza
neural exige calibración post-hoc; la ganancia varía fuerte con concurrencia; la aceptación se
degrada en posiciones tardías del bloque y con contexto largo.

**Regla de cita para este repo (congelada):** todo número de DSpark se cita como *"claim de
DeepSeek vs su propio MTP-1, sin réplica independiente"* — nunca como hecho general. El único
número defendible como orden de magnitud es 57–85% por-usuario en SU stack.

---

## 4. Comparación honesta con nuestro MoM medido

DSpark y el MoM no compiten: ellos aceleran el MISMO output de UN modelo; nosotros especializamos
VARIOS y cambiamos el output. Pero convergen en el mismo patrón estructural — **el chico hace el
trabajo barato y un mecanismo de confianza decide cuándo interviene el grande** — y por eso la
comparación pieza a pieza es informativa.

### Las 5 diferencias que importan

| # | eje | DSpark | MoM nuestro (evidencia) |
|---|---|---|---|
| 1 | **objetivo** | lossless: el mismo output del grande, más rápido | output MEJOR por dominio: el experto GANA su nicho +0.169/+0.177/+0.297 bpb sobre el generalista (X3, 3/3 dominios ≥ umbral 0.10 congelado) |
| 2 | **dónde vive el chico** | intra-modelo: drafter injertado al target congelado (reusa embeddings/head) | nivel sistema: expertos densos separados e intercambiables, ~97.5M c/u, 25.7 min de T4 por experto (K3 medido) |
| 3 | **routing** | confianza APRENDIDA + calibrada + scheduler por carga, decidiendo por TOKEN | selector ESTÁTICO n-grams, 96.7% acc, <5 ms, 1 decisión por turno/plan (X4) — correcto en CPU bandwidth-bound, donde decidir por token gasta banda sin ahorrar bytes (exp021, blueprint 08 #2) |
| 4 | **costo de inferencia** | el grande SIEMPRE residente (verifica cada draft) | se despacha el chico; el grande solo en fallback — en nuestro hardware ESA es la ganancia (0.5B = 4.3× el 3B, exp021) |
| 5 | **dónde está la evidencia** | datacenter GPU con batch/concurrencia; nada medido en CPU | T4-free + i3; nada medido a escala. Ninguno pisó el régimen del otro |

### Dónde ellos tienen razón y nosotros no (con nuestra evidencia en contra nuestra)

1. **Su señal de confianza es mejor que la nuestra.** Aprendida, supervisada con una cantidad
   ANALÍTICA (la tasa de aceptación — anti-Goodhart por matemática) y con calibración MEDIDA
   (ECE 3–8%→1%). Nuestro selector n-grams funciona (96.7% X4) pero su score es crudo: **nunca le
   medimos ECE**, y el umbral de fallback es heurístico. Peor: nuestra alternativa aprendida (bandit
   + verificador) NO convergió a 90 queries (X4: regret 1.05 ≫ 0.01 predicho — predicción formal
   fallida y declarada).
2. **Su fairness de baselines es más estricta.** Re-entrenaron EAGLE-3/DFlash en igualdad total.
   Nuestro X3 tiene un asterisco declarado: el LoRA-control entrenó 6 min de dominio vs 12 del
   denso (config pre-registrada, pero el control limpio de 12 min quedó pendiente). Hasta cerrarlo,
   `lora_empata=FALSE` es un veredicto con nota al pie.
3. **Su validación es tráfico real; la nuestra, 90 ventanas.** Desplegaron en su API productiva.
   Nuestro X4 corre sobre held-out sintético de 30 ventanas/dominio — el bandit se murió de hambre
   de pulls justamente por eso. La escala de validación de ellos es otra liga (y su régimen otro).

### Dónde nosotros tenemos razón y ellos no (para NUESTRO problema)

1. **El techo lossless es el target; el nuestro no.** Por construcción DSpark nunca supera la
   calidad del grande. Nuestros expertos SÍ la superan en su nicho (X3, 3/3). Para un producto que
   quiere respuestas MEJORES por dominio y no las mismas más rápido, su marco es un techo de cristal.
2. **En CPU bandwidth-bound su técnica ya está falseada en casa.** exp021: draft separado 0.37×;
   solo cabezas injertadas tipo MTP respetan la banda; la palanca dominante es el tamaño del modelo
   despachado. La crítica de antirez lo confirma desde afuera. DSpark-como-técnica es baja
   prioridad para la flota (i3, usuario único, sin concurrencia).
3. **Su modo de fallo conocido es nuestro caso resuelto.** Aceptación que colapsa fuera de
   distribución/contexto largo ↔ nuestro experto fuera de nicho se derrumba **+0.94 a +3.5 bpb**
   (X3). Nuestra respuesta ya está medida y es estructural: selector + fallback al generalista
   (X4: selección estática ≈ oracle en 2/3 dominios). Ellos lo dejan como "difficulty-aware early
   exit, trabajo futuro".
4. **Costo unitario de nuestro lado del patrón: resuelto y barato.** 1 experto = 25.7 min de T4
   (K3: 19,429 tok/s, MFU 19.7%, 13.05GB — K1v4); quota Kaggle 30 h/semana ⇒ ~60 expertos/semana
   teóricos. Su lado exige ~38 TB de caché y 8 GPUs para UN drafter de un 4B.
5. **Long-context: nosotros tenemos pieza, ellos tienen síntoma.** Su aceptación se degrada con el
   contexto (admitido). Nuestra banded 3:1 extrapola GRATIS y MEJORANDO (K3: bpb 512→1024 =
   1.2888→1.2491, sin NTK; tercera validación e2e).

---

## 5. MEJORAS PROPIAS pre-registradas (el corazón del doc)

Reglas comunes (heredadas de 00_DISENO §5 / 04 §6): predicciones y umbrales congelados acá;
comparaciones a igual wall o igual FLOPs, nunca a igual step; harness existente (checkpoints X3 en
`results_x3/`, kernel K3 `xh_final_kernel.py`, pesos `results_final/xh_model.pt`); curva completa;
desvíos a `01_DESVIOS.md`. **Ninguna mejora replica la técnica DSpark** (ni drafter, ni cabezas,
ni TV-loss): son principios distintos que atacan el MISMO problema (cuándo interviene qué modelo,
cuánto gastar) desde nuestras ventajas medidas. Orden = prioridad: M1 primero porque es la más
barata y des-riesga a M2/M3 (todas usan el margen calibrado).

### M1 — Selector de 3 ZONAS con umbral ASIMÉTRICO calibrado

**Qué es.** Calibrar el score del selector n-grams (temperature scaling por dominio en held-out,
ECE medido antes/después — práctica 8 de ellos, aplicada a NUESTRA señal) y convertir el margen
top1−top2 en una decisión de 3 zonas: **zona A** (margen alto) → experto top-1, 1 forward;
**zona B** (margen bajo) → fusión de logits top-2 SOLO ahí (X4 midió que la fusión únicamente paga
donde el router duda: código, con el 3.3% de error concentrado); **zona C** (score bajo en TODOS
los dominios) → generalista. Los umbrales NO son simétricos: se fijan minimizando pérdida esperada
de bpb con los costos MEDIDOS de X3 — errar hacia el experto equivocado cuesta +0.94 a +3.5 bpb;
errar hacia el generalista cuesta solo +0.17–0.30. Esa asimetría de 5–10× exige umbral sesgado a
fallback, cosa que un threshold simétrico de confianza (el de ellos) no puede expresar: en su marco
lossless todo error cuesta lo mismo (re-decodificar).

**Por qué supera lo de ellos.** DSpark paga el modelo grande SIEMPRE (residente + verificación);
acá el costo extra se paga solo en la zona de duda medida (~3–5% de queries → costo esperado
≈1.03–1.10 forwards/query). Y donde su decisión optimiza supervivencia del draft, la nuestra
optimiza pérdida esperada del PRODUCTO con costos direccionales medidos.

**Falsación barata: ~25 min CPU.** Reusar los 4 checkpoints X3; ampliar de 90 a 300 ventanas
held-out (dominio oculto). Medir: ECE crudo vs calibrado; AUC del margen para detectar misroutes;
bpb por dominio de 3-zonas vs selección-pura vs fusión-siempre vs oracle; forwards promedio.
**Predicción congelada:** (a) ECE crudo >5%, calibrado ≤2%; (b) 3-zonas logra bpb código ≤ fusión-
siempre (≤1.11 en la escala X4) MANTENIENDO cuentos/wiki en nivel oracle (0.714/1.343), con ≤1.10
forwards promedio; (c) si el AUC del margen para separar misroutes es <0.70, la zona B no paga y
el diseño cae a selección+fallback puro — falsación declarada, no se fuerza.

### M2 — Presupuesto por VALOR de la query, no por carga de hardware

**Qué es.** Una sola señal (margen calibrado de M1 × dominio) asigna el presupuesto por query:
max_tokens, si corre pase de verificación (cloze/checker del dominio), si amerita zona B. Es la
unificación selección+gasto que DSpark NO hace: su scheduler mira la carga de GPU (el sustrato);
el nuestro mira el valor de la decisión (la demanda) — exactamente la brújula R-VALOR (CYCLE 123:
la calibración del selector paga en la decisión bajo ESCASEZ; CYCLEs 83–114: asignación).

**Por qué supera lo de ellos.** En régimen single-user sin concurrencia (i3, T4 propia) el
load-aware es una no-op — la carga es constante (la crítica de antirez, medida por nosotros en
exp021). El único grado de libertad real es CUÁNTO vale cada query, y esa señal ellos no la miran.
Bajo presupuesto total fijo, asignar por valor domina a uniforme si la señal está calibrada — que
es justo lo que M1 garantiza o falsea primero.

**Falsación barata: ~30 min CPU.** 300 queries mezcladas, presupuesto TOTAL de forwards fijo
(1.2×N); comparar asignación por valor (margen bajo → más presupuesto) vs uniforme vs aleatoria al
MISMO total. Métrica: bpb promedio ponderado + tasa de acierto del fallback.
**Predicción congelada:** valor gana a uniforme por ≥0.02 bpb a igual FLOPs; aleatoria pierde
contra ambas. Si valor ≈ uniforme, el margen del selector NO es señal de valor a esta escala y la
unificación queda falseada (se conserva selección sola; R-VALOR no se fuerza donde no paga).

### M3 — Generalista de FRONTERA: entrenar el fallback donde el selector duda

**Qué es.** Re-entrenar el generalista (12 min T4, receta K3 congelada) con la mezcla re-ponderada
hacia las regiones de confusión MEDIDAS del selector (ventanas con margen bajo, fronteras
inter-dominio — hoy: código con identificadores/prosa mezclados), en vez de tercios uniformes. El
rol del generalista en MoM no es "saber de todo": es cubrir la zona donde el router se equivoca.
Entonces su corpus debe ser LA FRONTERA, no el promedio.

**Por qué supera lo de ellos.** Estructuralmente inaccesible para su marco: DSpark no puede tocar
su target (congelado por diseño lossless) — su red de seguridad es fija. La nuestra es re-entrenable
por 12 minutos de T4, y se especializa en el modo de fallo REAL del sistema (los misroutes), no en
un promedio de dominios.

**Falsación barata: ~15 min T4 + 10 min CPU.** Entrenar generalista-frontera; evaluar en (i) las
ventanas mal-ruteadas identificadas en M1, (ii) la mezcla global held-out.
**Predicción congelada:** en misroutes mejora ≥0.05 bpb vs generalista-uniforme; en mezcla global
no empeora >0.03. Si empeora la mezcla más que eso, deja de ser red de seguridad y se descarta
(el generalista-uniforme de X3 queda).

### M4 — bpb condicional por posición: la plantilla diagnóstica de ellos sobre NUESTRA banda

**Qué es.** Robar la PRÁCTICA 1 (no la técnica): cuando una métrica agregada esconde causas,
construir la condicional que las separe. Aplicación: bpb por bucket de posición × distancia-de-
alcance a los global layers (capas 3/7/11), sobre extrapolación 512→1024→2048→4096 del K3
(`xh_model.pt`, eval-only, cero entrenamiento). Hoy sabemos que la banda extrapola mejorando a
1024 (1.2888→1.2491); NO sabemos DÓNDE empieza a romper ni por qué mecanismo — y eso decide si el
remedio futuro es más globals, NTK, o nada.

**Por qué supera lo de ellos.** Ellos usaron la condicional para diseñar un drafter; nosotros para
mapear la pieza que ellos NO tienen: su aceptación se degrada con contexto largo (limitación
admitida), nuestra banda extrapola gratis (validada 3×, K2-H y K3). Convertimos una ventaja medida
en un mapa causal ANTES de escalar — diagnóstico antes que parche, a costo de eval.

**Falsación barata: ~10 min T4 (eval-only).** bpb por bucket de 128 posiciones a 512/1024/2048/4096,
con y sin NTK.
**Predicción congelada:** a 2048 el bpb agregado sube ≤0.05 vs 1024; la degradación (si existe) se
concentra en buckets cuya distancia al último global excede el alcance efectivo w×saltos; si
degrada UNIFORME en posición, la hipótesis de alcance queda falseada y el remedio NO es más
globals (sería NTK u otra cosa — se anota, no se decide acá).

### M5 — Flota 6-dominios: escalar HORIZONTAL lo que ellos escalan vertical (+ cierre de fairness X3)

**Qué es.** Pasar de 3 a 6 expertos con la receta K3 congelada (25.7 min/experto MEDIDO; quota
30 h/semana ≈ 60 teóricos/semana): + matemática-es, + diálogo/tool-use estilo ACCION, + inglés
técnico (candidatos; la selección final de dominios se fija antes de lanzar, con corpus verificado
estilo K0). Gates por experto pre-registrados (≥+0.10 bpb su nicho; derrumbe fuera de nicho
esperado y verificado) y el gate NUEVO que nadie midió: **¿el selector n-grams aguanta 6 clases?**
Incluye el brazo que cierra el asterisco de fairness de X3: **LoRA-control de 12 min** (mismo wall
que el denso), adoptando la práctica 3 de ellos (baselines en igualdad).

**Por qué supera lo de ellos.** El pariente real de nuestro MoM es el post-training de V4 (cultivo
de expertos → consolidación destilada en UN modelo): ellos pierden la modularidad al consolidar;
nosotros la conservamos — cada experto es intercambiable, re-entrenable en 25 min, y GANA su nicho
(no paridad lossless). Nuestra unit-economics (25 min/experto en quota free) es un régimen en el
que ellos no operan ni pueden operar (su unidad mínima son nodos de 8 GPUs). La apuesta
falsable: la ventaja del MoM crece con el número de dominios ANTES de que el selector se degrade —
y ese cruce nadie lo midió.

**Falsación barata: ~3.5 h T4 total (6×~26 min + evals) + ~20 min CPU (selector).**
**Predicción congelada:** (a) selector n-grams ≥90% a 6 clases (cae desde 96.7% a 3; si <90% →
selector jerárquico de 2 niveles grupo→dominio ANTES de tocar features aprendidas); (b) cada
experto nuevo gana su nicho ≥+0.10 bpb vs generalista; (c) el LoRA de 12 min sigue sin empatar al
denso (si empata, la decisión X3 se RE-ABRE y se declara — el asterisco muere en cualquier caso);
(d) el derrumbe fuera de nicho persiste en los dominios nuevos (el selector sigue siendo estructural).

### Tabla resumen de mejoras

| # | mejora | qué ataca de DSpark | presupuesto | predicción clave congelada |
|---|---|---|---|---|
| M1 | selector 3-zonas, umbral asimétrico calibrado (ECE medido) | su threshold simétrico + grande-siempre-residente | ~25 min CPU | ECE ≤2% calibrado; código ≤ fusión-siempre con ≤1.10 fwd/query; AUC<0.70 → cae a selección pura |
| M2 | presupuesto por VALOR de la query (R-VALOR) | su scheduler load-aware (ciego a demanda) | ~30 min CPU | valor ≥0.02 bpb sobre uniforme a igual FLOPs, o se falsea la unificación |
| M3 | generalista de frontera (fallback entrenado en misroutes) | su target congelado e intocable | ~15 min T4 + 10 CPU | ≥0.05 bpb en misroutes sin perder >0.03 en mezcla |
| M4 | bpb condicional por posición sobre la banda | su degradación admitida con contexto (nosotros: mapa causal de la ventaja) | ~10 min T4 eval | ≤+0.05 a 2048; degradación localizada por alcance o hipótesis falseada |
| M5 | flota 6-dominios + gate del selector + control fairness LoRA-12min | su consolidación que pierde modularidad; su unidad mínima de 8 GPUs | ~3.5 h T4 + 20 min CPU | selector ≥90% a 6 clases; +0.10 bpb/nicho; el asterisco X3 se cierra en cualquier dirección |

Total: **~4 h de T4 + ~1.5 h de CPU** — menos que el programa X1–X4 completo, todo dentro de una
semana de quota, con M1–M4 ejecutables hoy sin lanzar entrenamiento nuevo salvo M3.

---

## 6. Qué NO hacemos (anti-scope-creep + riesgos de copia/licencia)

1. **NO cabeza draft/MTP con TV-loss sobre nuestros modelos — ahora.** Es LA técnica de ellos
   (directiva del dueño: no copiar) y es scope-creep vertical contra la flota. Estado honesto:
   exp021 dejó las cabezas injertadas como única vía speculative viva en nuestro sustrato (2–3×
   proyectado, no medido), así que la puerta NO se tapia — pero solo se abre en un ciclo futuro
   con pre-registro y benchmark propio (regla P9 de 04: X2 demostró DOS veces que las recetas de
   paper no transfieren a nuestros harness), y nunca como copia del diseño de 3 cabezas.
2. **NO portar DeepSpec.** ~38 TB de caché del target para un 4B + 1 nodo de 8 GPUs: inviable en
   T4-free y absurdo en el i3. No es una limitación nuestra a lamentar: es un régimen ajeno.
3. **NO routing por token.** CPU decode es bandwidth-bound: decidir por token gasta banda sin
   ahorrar bytes (exp021; decisión #2 del blueprint 08). Una decisión por turno/plan, margen
   calibrado (M1) — punto.
4. **NO confidence-head neural entrenada con recompensa propia.** Goodhart medido en casa (CYCLE
   12: el "fanfarrón" secuestra la política). Nuestra señal de confianza es score estático
   calibrado (M1) o verificador real — nunca la autoevaluación del modelo.
5. **NO citar 60–85%/661% como hechos.** Claims del vendor sin réplica independiente (a
   2026-07-03), contra su propio MTP-1, en su stack cerrado. Regla de cita de §3, congelada.
6. **NO adoptar el marco lossless.** Garantizar "el mismo output del grande" destruiría nuestra
   propuesta de valor: el experto gana +0.17–0.30 bpb EN su nicho (X3). Queremos output mejor y
   más barato por dominio, no el mismo más rápido.
7. **NO re-litigar lo medido por el hype.** exp021 (draft separado 0.37× en CPU) y CYCLE 47 ("más
   orquestación no mueve la aguja; el orden es verificador→expertos→router") siguen vigentes; un
   release ajeno no es "razón nueva" bajo nuestra regla de descarte con evidencia.
8. **Licencia y procedencia.** DeepSpec es MIT pero su NOTICE declara código adaptado de terceros
   (SpecForge, DFlash, Qwen3, Gemma); los checkpoints sobre Gemma pueden arrastrar los Gemma
   Terms. Hoy este análisis importa CERO líneas de su código; si algún ciclo futuro tomara algo,
   se audita el NOTICE archivo por archivo — no se asume "MIT limpio". El paper (sin arXiv ni
   review) se cita como technical report corporativo, nunca como literatura revisada.
9. **NO replicar el marketing.** Titular único sin matriz por tarea/carga es lo que nuestro método
   prohíbe: se reporta la matriz completa con gates, como XSPEED (4.10× CON 4 gates de calidad) y
   K3 (2/4 gates, declarado NO FUNCIONAL sin maquillaje).

---

**Cierre del pre-registro.** Este documento se congela antes de correr M1. Cambios posteriores van
a `01_DESVIOS.md` append-only con fecha y razón — nunca editando las predicciones de acá.


---

## 7. Resultados post-registro

### M1 — CORRIDO 2026-07-03 (37.8 min CPU, `results_x3/xh_m1_results.json`; presupuesto era ~25)

| predicción congelada | medido | veredicto |
|---|---|---|
| (a) ECE crudo >5%, calibrado ≤2% | **47.7% → 1.8%** (T=0.05) | **CONFIRMADA** con margen — la señal n-grams estaba brutalmente sub-confiada; la práctica de calibración adoptada de DSpark paga |
| (c) AUC margen→misroute ≥0.70 | **0.868** (3 misroutes/150; router calibrado 98%) | **CONFIRMADA** |
| (b) 3-zonas: código ≤ fusión-siempre con cuentos/wiki ≈ oracle | 3-zonas colapsó a selección pura (fwd 1.0); fusión gana en código **1.048 vs 1.112**; cuentos/wiki = oracle ✓ | **FALLIDA en código** — declarada |

**Causa raíz de (b):** la calibración por sharpening global (T=0.05) satura los márgenes
post-calibración (~1.0 para casi todo) → la zona B nunca se activa con el grid congelado, y el
optimizador de pérdida esperada en cal eligió selección pura. La falsación prevista en (c)
("si la zona B no paga → selección+fallback puro") se activó por otra vía: no por AUC bajo,
sino por saturación del margen calibrado. **v2 pre-registrada (no corrida, anti-scope-creep):**
zonificar sobre el margen CRUDO (donde vive el AUC 0.868) o calibrar con isotónica que preserve
granularidad; predicción: la zona B se activa en ~5-10% de queries y recupera ≥0.03 bpb en
código con ≤1.15 fwd promedio. **Lo que ya es adoptable HOY para el CLI:** la calibración T
(ECE 1.8%) y la confirmación de que selección-pura calibrada ≈ oracle en cuentos/wiki con 1
forward — el selector del MoM queda con base medida más sólida que la v0.
