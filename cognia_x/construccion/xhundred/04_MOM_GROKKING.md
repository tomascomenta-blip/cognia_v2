# MoM + Grokking — Investigación y veredicto honesto

**Fecha:** 2026-07-02 · **Pedido del dueño:** investigar el grokking A PROFUNDIDAD y decir CON
HONESTIDAD si su idea está bien. La idea: *Mixture-of-Models* (MoM) = (a) expertos densos chicos,
uno por dominio, entrenados "mucho, hasta que se estancan y ahí aprenden las BASES/normas"
(grokking); (b) un calibrador que une las respuestas; (c) un modelo creador de herramientas;
(d) el conjunto responde más rápido que un denso grande.
**Fuentes:** 5 informes (mecanismo, aceleración, grokking-real, MoM-arquitectura, prior-repo),
literatura primaria 2022–2026, y mediciones propias del repo (nada re-derivado). Las
contradicciones entre informes se resuelven acá y quedan anotadas en itálica, estilo 00_DISENO §4.7.
**Estado:** INVESTIGACIÓN + PRE-REGISTRO (veredicto y experimentos escritos ANTES de construir).

---

## 1. Qué es el grokking DE VERDAD (mecanismo, no folklore)

**El fenómeno (Power et al. 2022, [2201.02177](https://arxiv.org/abs/2201.02177)).** Redes
sobre-parametrizadas en datasets algorítmicos chicos (aritmética modular): llegan a 100% train
(memorización) y la generalización aparece MUCHO después — miles a cientos de miles de pasos extra
de optimización sobre train loss ya convergido. A menor fracción de datos, más pasos hasta
generalizar (monótono). En ese régimen el acelerador dominante fue weight decay.

**Qué pasa por dentro (Nanda et al., ICLR 2023, [2301.05217](https://arxiv.org/abs/2301.05217)).**
Reverse-engineering completo del transformer que grokea suma modular: el circuito final son
**bases de Fourier** + identidades trigonométricas (rotación en el círculo) — "aprende las
bases/normas" es literalmente cierto cuando el dominio tiene una regla compacta subyacente. Pero
la transición NO es súbita por dentro: **memorización → formación GRADUAL del circuito → cleanup**
(el wd borra la memorización). Las *progress measures* (restricted/excluded loss) mejoran suave
mientras el accuracy salta. **Respuesta a la pregunta clave: sí — el "eureka" es del accuracy
(métrica discreta cruzando umbral); el aprendizaje subyacente es gradual.** Cita textual: "gradual
amplification of structured mechanisms encoded in the weights, followed by removal of memorizing
components".

**Por qué gana el circuito general (Varma et al. 2023, [2309.02390](https://arxiv.org/abs/2309.02390)).**
Dos circuitos compiten: memorizador (rápido, eficiencia ∝ 1/datos) y generalizador (lento,
eficiencia constante); wd premia al eficiente-en-norma. Predice y confirma **D_crit** (tamaño
crítico de dataset), **ungrokking** (por debajo de D_crit el modelo DES-aprende la generalización
si se sigue entrenando) y semi-grokking. Corolario duro: **el grokking existe solo en una VENTANA
de escasez de datos** — con datos abundantes se generaliza directo (sin delay); con muy pocos,
nunca. [Critical Data Size, 2401.10463](https://arxiv.org/abs/2401.10463) lo confirma como zona
Goldilocks: con datos suficientes memorización y generalización co-ocurren y el "eureka"
desaparece porque nunca hubo plateau.

**Condiciones que producen el delay (no la generalización — el DELAY):**
1. **Norma de init grande** ([Omnigrok, ICLR 2023, 2210.01117](https://arxiv.org/abs/2210.01117)):
   mecanismo LU (train loss en "L", test en "U" vs norma). Con init estándar bien escalada casi no
   hay grokking; inflando la init se induce a voluntad (hasta en MNIST con 1k muestras).
2. **Régimen lazy** ([Kumar et al., 2310.06110](https://arxiv.org/abs/2310.06110)): el plateau =
   tiempo atrapado en solución tipo kernel antes del feature-learning; se controla con
   parametrización/escala de salida, ni wd ni optimizador adaptativo son necesarios.
3. **Softmax Collapse** ([Edge of Numerical Stability, ICLR 2025, 2501.04697](https://arxiv.org/abs/2501.04697)):
   sin regularización, logits gigantes + errores fp + gradiente alineado a "naive loss
   minimization"; StableMax y ⊥Grad generalizan rápido SIN período de overfitting.

**Taxonomía que la idea del dueño mezcla (y hay que separar):**

| fenómeno | cuándo | qué lo delata |
|---|---|---|
| grokking (Power/Nanda) | DESPUÉS de converger train loss, datos escasos | plateau largo post-overfit, luego salto |
| abrupt learning (sintaxis, [2309.07311](https://arxiv.org/pdf/2309.07311)) | DURANTE el descenso del loss | "structure onset" sin overfitting previo |
| emergencia de quanta ([Michaud 2303.13506](https://arxiv.org/abs/2303.13506); espejismo de métrica, Schaeffer) | agregado de habilidades discretas por frecuencia | scaling suave en loss, saltos en métricas discretas |

[Circuits competition, 2402.15175](https://arxiv.org/html/2402.15175v2) unifica: el grokking es un
**síntoma de retraso** cuando la memorización carga mucho — no una fase mágica de aprendizaje.

**El grokking del propio repo es OTRO animal (anotado, no folklore).** El MQAR propio grokea en
step ~3600 (0.125→meseta→0.79@3663→1.000@4500, `M0_XSPEED_RESULTADO.md`) **sin overfitting
previo** — es formación abrupta de circuito tipo induction-head (más cerca de "abrupt learning"
que de Power et al.). La prueba: el barrido de wd propio
(`results_g2/g2_grok_accel_partial.json`+`_hi.json`) da **wd=0 → 3600 · 0.01 → 3700 · 0.1 → 4200 ·
0.3 → 8900 · 1.0 → NUNCA (best_acc 0.38)**. El acelerador estrella de la literatura FRENA o MATA
nuestra transición. Y el LR es no-monótono (`g2_grok_lr.json`: 1e-3 y 3e-3 no grokean en
presupuesto; 1e-2 sí, @7600). *Discrepancia entre informes resuelta: el informe aceleración leyó
el wd-sweep como "consistente con Omnigrok" (wd solo importa si la init está mal escalada); el
informe mecanismo lo leyó como "mecanismo distinto al de la literatura". Ambas lecturas coinciden
en lo accionable: los aceleradores son RÉGIMEN-DEPENDIENTES — se miden en el harness propio, no se
importan del paper. Eso queda pre-registrado como regla.*

---

## 2. La pregunta del costo: ¿hay que PAGAR el plateau?

**El impuesto.** En el régimen clásico, 10×–1000× pasos post-overfitting según distancia a D_crit.
Para XHUNDRED es la diferencia entre viable e inviable: el budget es ≤30 min de T4 y el run queda
a **0.2–0.45 tok/param** (36× bajo Chinchilla, 00_DISENO §1) — no hay presupuesto ni para llegar a
la meseta, mucho menos para esperar el salto.

**El reembolso (evidencia de que el delay es artefacto evitable):**

| palanca | ganancia reportada | costo/riesgo | fuente |
|---|---|---|---|
| init norm chica (+ norma constreñida) | delay casi ELIMINADO (train y test suben juntos) | ninguno; es 1 línea | [Omnigrok](https://arxiv.org/abs/2210.01117) |
| StableMax / ⊥Grad | generalización rápida SIN período de overfitting | cambiar softmax/proyección de grad | [2501.04697](https://arxiv.org/abs/2501.04697) |
| Grokfast (amplificar componente lenta del grad) | hasta **50× menos iteraciones** en toys | EMA barata pero INESTABLE (sweet spot λ,w,wd — [NeuralGrok 2504.17243](https://arxiv.org/pdf/2504.17243)); variante MA = w grads en memoria y ×2.4 wall a w=100; sin replicación en LM real | [2405.20233](https://arxiv.org/abs/2405.20233) |
| Muon | epoch medio de grok 153→103 vs AdamW (~1.5×, p=6.3e-8, 7 tareas) | **ya está en la receta K3** (LR 0.02, NS 5 iter fp16) | [2504.16041](https://arxiv.org/abs/2504.16041) |
| más datos / diversidad | "de-grokking": el plateau se acorta hasta desaparecer | necesita corpus del dominio | [2401.10463](https://arxiv.org/abs/2401.10463) |
| weight decay | dominante en Power et al. | **en NUESTRA tarea frena o mata** (§1) | medido, `g2_grok_accel_*` |

*Discrepancia entre informes resuelta (magnitud Grokfast): "50×" es de tareas algorítmicas toy; el
mismo informe aceleración documenta la inestabilidad y el costo de memoria. Se pre-registra como
palanca a PROBAR (X2), no como número prometible.*

**Lo que el repo ya midió sobre el costo:** el step de transición es del problema de optimización,
no del reloj — fp32/amp/fast16 grokean todos en el MISMO step 3600; compile cruza la transición en
la **mitad del wall** (34.5 s vs 67.5 s, `M0_XSPEED_RESULTADO.md`). Acelerar el reloj no mueve el
step; hay que mover el **step**. Y `plateau_stop` es LETAL (falso negativo del sweep G2,
`M0_G2_RESULTADO.md`): si se corta antes de la transición el modelo queda inútil (~0.35 acc). La
lección registrada "GROKKING = costo de convergencia" (`M0_VELOCIDAD_SINTESIS.md` §5) es
exactamente la conclusión de la literatura.

**Respuesta pre-registrada: NO hay que pagar el plateau.** El circuito generalizador es el
producto; el plateau es una patología de parametrización (init grande / lazy / softmax collapse /
datos en la zona Goldilocks). La forma barata de llegar al MISMO circuito: init correcta
(XHUNDRED ya usa zero-init muP-like + std 0.02) + Muon (ya adoptado) + datos suficientes del
dominio + z-loss/QK-norm (estabilidad numérica, ya adoptados) + curva COMPLETA sin plateau_stop +
una progress measure barata como criterio de continuar/parar. Lo único que falta medir es si esas
palancas mueven el grok-step en el harness propio (X1, X2) — porque el wd ya demostró que acá no
transfieren automáticamente.

---

## 3. ¿Grokking en expertos de lenguaje/código REALES?

**Donde SÍ hay evidencia (y es fuerte):** razonamiento **composicional sobre hechos** con regla
exacta subyacente.
- [Wang et al. 2024, 2405.15071](https://arxiv.org/abs/2405.15071): multi-hop implícito emerge
  SOLO vía grokking; lo que controla la transición no es tamaño de modelo ni de dataset sino
  **φ = ratio hechos inferidos/atómicos** de la mezcla. Un transformer chico full-grokkeado logra
  ~100% donde GPT-4-Turbo y Gemini-1.5-Pro "fail badly" incluso con RAG. PERO: *comparación*
  generaliza OOD; **composición generaliza ID y falla sistemáticamente OOD**.
- [Grokking in the Wild, 2504.20752](https://arxiv.org/abs/2504.20752): extiende a datos reales
  (2WikiMultiHopQA, 95–100%) **induciendo** el grokking al subir φ con datos sintéticos — incluso
  factualmente incorrectos (fuerzan estructura relacional sobre memorización). La palanca es la
  MEZCLA, no el sobre-entrenamiento a ciegas.
- [Pretraining real 7B OLMoE, 2506.21551](https://arxiv.org/abs/2506.21551): el grokking existe en
  one-pass pretraining pero es **local y asíncrono por grupo de datos** — no hay UN eureka global;
  math/código requieren memorizar muchas más muestras antes de generalizar que QA. El train loss
  es proxy no confiable de la generalización.

**Donde NO (y esto tumba la mitad de la intuición):** las **normas superficiales de un lenguaje**.
- [TinyStories](https://openreview.net/pdf/b654f63843be38ae2efa177fdb1e5efcff4ebd04.pdf): gramática
  casi perfecta con 1–10M params y **entrenamiento normal** (emerge ya a width 64–128, 1–2 capas).
  Sin plateau, sin eureka.
- [2309.07311](https://arxiv.org/pdf/2309.07311): las transiciones de sintaxis en MLMs son abrupt
  learning DURANTE el descenso del loss — por definición NO grokking. Un experto de Python
  aprenderá la sintaxis de Python de forma ordinaria.
- Código real: **cero evidencia directa** de "grokkear las normas de un lenguaje de programación";
  lo más cercano es [structural grokking 2305.18741](https://arxiv.org/pdf/2305.18741) en tareas
  controladas. Extrapolarlo a un experto de código es especulación y se declara como tal.

**El contrapunto que no se puede omitir ([Is Grokking Worthwhile?, 2601.09049](https://arxiv.org/pdf/2601.09049)):**
los caminos de inferencia ID de modelos grokkeados y no-grokkeados son **idénticos**; alta accuracy
en casos no vistos se logra sin grokking bajo ciertos regímenes de datos; y los circuitos
grokkeados muestran **transferencia LIMITADA al integrar conocimiento nuevo**. Además existe
**ungrokking natural** ([2606.26050](https://arxiv.org/html/2606.26050)): reglas grokkeadas se
pierden con pretraining continuado. "Aprendió las bases" es un overclaim: aprendió UN circuito
para UNA distribución, y puede perderlo.

**Cuándo el experto de nicho SÍ es territorio grokking:** tarea con **regla exacta subyacente**
(semántica de tipos, ejecución, transformaciones de AST, inferencia multi-hop sobre una KB del
dominio — no sintaxis), **datos escasos respecto a la capacidad**, y **control de la mezcla φ**.
Cuándo no: corpus abundante del dominio (de-grokking: se generaliza sin plateau) o normas
superficiales (se aprenden gradual). *Discrepancia entre informes resuelta (wd en el nicho): el
informe grokking-real recomienda "wd alto" para el régimen de composición — coherente con
Power/Varma — pero el harness propio midió que wd alto MATA la transición de recall (§1). Ambas
son ciertas en su régimen: wd ayuda donde hay memorización que limpiar, estorba donde el circuito
se forma sin overfitting previo. Resolución: wd por-tarea, decidido por medición (X2/X5), nunca
por default.*

---

## 4. La arquitectura MoM del dueño, pieza por pieza

### 4a. Expertos densos chicos por dominio

**Lo que la apoya.**
- [BTM, 2208.03306](https://arxiv.org/abs/2208.03306): LMs expertos densos por dominio entrenados
  "embarrassingly parallel", mejor perplejidad in-domain Y out-of-domain que un GPT-style **a
  igual costo de entrenamiento**. [c-BTM](https://arxiv.org/abs/2303.14177): expertos de 1.3B con
  clusters no supervisados igualan a un denso 6.7B con **~29% de los FLOPs**. Es el mejor pedigrí
  empírico de todas las variantes.
- Costo unitario ya en casa: receta K3 congelada = **1 experto ~97.5M entrenado por ≤30 min T4**
  (`03_INVESTIGACION.md`; `xh_bench_results.json`: 19,429 tok/s, MFU 19.7%, 13.05GB b48; el K3
  real quedó 2/4 gates — fuerte en gramática/compresión/narrativa, no en generación libre
  wiki). Quota Kaggle 30 h/semana ⇒ ~60 expertos/semana en teoría.
- La especialización del corpus paga la métrica del nicho: brazo G, wiki-solo bpb 1.3826 vs mezcla
  1.5428 (Δ0.16) — con el costo cualitativo anotado (reproduce la deriva de plantillas).

**Lo que la contradice.**
- **El propio lab ya decidió lo contrario** (`08_expertos_routing.md`, decisión #1): expertos =
  **adapters LoRA por dominio sobre backbone común**, NO densos separados — forzado por la RAM del
  i3 (11.8GB: caben ~8–10 densos 0.5B Q4 de 350–400MB; swap frío = segundos, mata la latencia) y
  por la restricción dura FedAvg-solo-LoRA.
- Un 100M denso es objetivamente débil: bpb wiki 1.38–1.52, muestras con deriva/vaguedad; los 0.5B
  de exp021 ya eran "fluidos pero poco fiables en hechos" y 100M es 5× menor. La alternativa
  diseñada (QLoRA 30 min sobre 3B pre-entrenado, 00_DISENO §7) especializa con mucha más capacidad
  base.
- Restricción dura vigente: **sin PyTorch en nodos** — servir densos propios exige export a
  GGUF/llama.cpp, NO validado para la arquitectura banded propia.

**Variante con mejor evidencia: dual-régimen.** (i) En T4/investigación, densos ~100M BTM-style
son viables y baratos (decenas caben en 15.6GB fp16) — es el régimen donde la idea del dueño VALE
y se falsea barato (X3). (ii) En producción i3, la forma servible del "experto" es adapter LoRA
hot-swap (~MB, `--lora` ya existente) o QLoRA sobre el 3B — el blueprint 08 no se refuta, se
confirma. *Discrepancia entre informes resuelta (densos vs LoRA): MoM-arquitectura y prior-repo no
se contradicen — hablan de regímenes distintos (T4-tiny vs i3-3B). Queda anotado como decisión por
régimen, no una decisión global.*

### 4b. Calibrador que une respuestas

**Lo que la apoya.** El mecanismo de despacho existe y corre: `cognia_x/reason/router.py`
(CYCLEs 12–21, bandit ε-greedy/UCB con recompensa = **verificador real**), coordinación
no-regret probada en toy (exp029 worst_regret +0.008; exp086 regret 0.006). "Cambiar el espacio de
acciones (cadenas→modelos), no inventar el mecanismo" (08 §2).

**Lo que la contradice (la pieza más floja de toda la idea).**
- **Seleccionar > fusionar**, con números: [LLM-Blender](https://arxiv.org/abs/2306.02561) —
  PairRanker (selección) ya supera al mejor modelo fijo (+18% relativo GPT-Rank); GenFuser solo
  paga fusionando los top-K YA rankeados. c-BTM ni fusiona texto: mezcla **logits** top-k.
  [Self-MoE, 2406.12034](https://arxiv.org/abs/2406.12034): routing dinámico 65.6 MMLU > TIES
  merging 63.7 > instance-merging 62.6. Jerarquía empírica: **routing > merging de pesos > fusión
  libre**.
- **"Grokkeado en las normas de unir": cero evidencia.** Unir respuestas no es una tarea con regla
  compacta subyacente conocida → no hay razón para esperar grokking; y 2601.09049 muestra que los
  circuitos grokkeados transfieren MAL a conocimiento nuevo — lo OPUESTO a lo que un calibrador
  necesita (integrar outputs siempre nuevos).
- Riesgo medido en casa: recompensar por confianza propia = Goodhart (el "fanfarrón" secuestra la
  política, CYCLE 12; usar `mode="verifier"`). Sin verificador por dominio no hay señal no-circular
  — y CYCLE 47 ya concluyó que el orden que paga es **verificador → expertos → router**.

**Variante con mejor evidencia:** selector chico (ranker/verificador elige 1 respuesta, re-apuntando
`router.py` mode="verifier"); mezcla de logits estilo c-BTM solo si los expertos comparten
tokenizer; fusión generativa únicamente como fallback sobre top-2 filtrados. El calibrador se
ENTRENA supervisado/bandit — no se "grokea".

### 4c. Modelo creador de herramientas

**Lo que la apoya.** Precedente directo: [LATM, 2305.17126](https://arxiv.org/abs/2305.17126) — un
modelo fuerte CREA herramientas (funciones Python), uno chico las USA, un dispatcher liviano decide
reusar-o-crear; iguala a GPT-4-en-todo con ~79% menos costo por instancia. Sinergia 1:1 con el
pilar del repo: verificación por ejecución (regla 9 de CLAUDE.md: scan de imports + sandbox con
timeout), pipeline tool-use ACCION ya construido.

**Lo que la contradice.** En LATM el creador es el modelo GRANDE — la pieza no puede ser otro
experto chico grokkeado (crear herramientas correctas exige capacidad que un 100M no tiene; los
0.5B ya fallan en fiabilidad factual). No hay prior-art en el repo del creador como tal (SCALE=0%
en expertos).

**Variante con mejor evidencia:** creador = el mejor modelo disponible (3B QLoRA-especializado u
offline/externo), usuarios = los chicos; toda herramienta pasa el gate de sandbox ANTES de
registrarse. Es ingeniería sobre lo que ya existe, no investigación.

### 4d. Claim de velocidad

**Lo que la apoya (medido, exp021/F-SPEED).** 0.5B = **35.88 tok/s vs 8.32 del 3B = 4.3×** en el
i3; respuesta de 200 tok: ~5.8 s vs ~25 s. Router aprendido = clasificador chico de 10–50 ms
([RouteLLM](https://arxiv.org/abs/2406.18665): 2× menos costo a ~95% calidad GPT-4;
[FrugalGPT](https://arxiv.org/abs/2305.05176): hasta 98% menos costo) → overhead ≈ **0.26% del
tiempo ahorrado**. La aritmética del dueño es correcta.

**Lo que la contradice.**
- La cascada real medida: turnos sociales 2.46→0.63 s (~4×) pero **conversación total solo 1.11×**
  (los turnos sustantivos dominan, exp021 §6). El 4.3× es del turno ruteado al chico, no del
  producto entero.
- El cuello real es MEMORIA, no cómputo del router: N densos residentes no caben en el i3 (§4a);
  el peor caso de cascada paga múltiples llamadas antes de escalar (FrugalGPT).
- MoE denso-condicional ya descartado con números (M0_SINTESIS §6: 0.42–0.50× del denso en CPU);
  DP 2×T4 más lento que 1 GPU (XSPEED). La velocidad viene del TAMAÑO del modelo despachado, no de
  la orquestación.
- CYCLE 47 (la verdad incómoda): "el routing NO es el cuello de botella; el lever es
  sustrato+verificador, no más orquestación". El MoM se justifica por velocidad/modularidad, no
  por salto de capacidad.

**Variante con mejor evidencia:** cascada por complejidad con **1 decisión por PLAN** (decisión #2
del blueprint 08; decode CPU es bandwidth-bound, routing por token gasta banda sin ahorrar bytes),
pocos modelos calientes + adapters fríos baratos.

---

## 5. VEREDICTO HONESTO de la idea

**Qué está BIEN (y por qué).**
1. **La física de velocidad es correcta y ya está medida**: despachar al denso chico del dominio es
   la palanca dominante de latencia CPU (4.3×, exp021) y el overhead del router es despreciable.
2. **Expertos por dominio es la variante con mejor pedigrí empírico** (BTM/c-BTM: igual o mejor
   calidad con ~29% de los FLOPs) y el repo tiene el costo unitario resuelto (K3: experto ~100M en
   ≤30 min T4) y el mecanismo de despacho probado (router.py + exp029/086).
3. **La intuición de fondo apunta al fenómeno correcto**: querer expertos que internalizan las
   NORMAS (circuito generalizador, feature learning) y no la tabla memorizada es exactamente lo que
   la mecanística describe (Nanda), y existe un régimen real donde un chico full-grokkeado supera a
   GPT-4-Turbo (Wang 2024: composición multi-hop, datos escasos, φ alto).

**Qué está MAL o CARO tal cual está formulado.**
1. **"Entrenar hasta el eureka" optimiza la patología, no la cura.** El delay es un artefacto
   evitable (init/estabilidad/datos/optimizador, §2) que cuesta 10–100× de wall; el "eureka" es el
   umbral de una métrica discreta sobre un aprendizaje gradual; y a 0.2–0.45 tok/param el budget
   XHUNDRED ni llega a la meseta. Peor: por debajo de D_crit seguir entrenando DES-generaliza
   (ungrokking). Como criterio de parada, el eureka es mala métrica sin progress measures.
2. **"Un eureka por experto" no mapea a dominios reales**: en LM real el grokking es local y
   asíncrono por sub-habilidad (2506.21551), y las normas superficiales del lenguaje se aprenden
   SIN grokking (TinyStories). Aplica solo a sub-tareas composicionales con regla exacta.
3. **El calibrador-fusionador es la pieza sin sustento**: la evidencia dice seleccionar > fusionar,
   los circuitos grokkeados transfieren mal (anti-calibrador), y sin verificador no hay señal
   no-circular (Goodhart medido en CYCLE 12).
4. **N densos residentes chocan con el hardware de producción** (i3) y con las restricciones duras
   (sin PyTorch en nodos, FedAvg-solo-LoRA). Válido en T4-tiny; inválido como forma de servir.

**Reformulación que conserva la intención del dueño con la mejor evidencia.**
> MoM = **expertos especializados baratos** — densos ~100M con receta K3 en el régimen
> T4/investigación, adapters LoRA/QLoRA sobre el 3B en el régimen servible — **entrenados con la
> parametrización que EVITA el plateau** (init correcta + Muon + datos ricos del dominio; mezcla
> φ-alta con sintéticos SOLO donde el dominio tiene reglas composicionales), cerrados con un
> **gate de generalización OOD del dominio** (el análogo honesto del "grokeó las bases") en vez de
> esperar un eureka; despacho por **selector con verificador** (1 decisión por plan; fusión solo
> top-2 como fallback); herramientas **creadas por el modelo grande y usadas por los chicos**, con
> validación sandbox. El eureka no es el producto; el circuito sí.

---

## 6. Plan de experimentos pre-registrado (baratos, falsables)

Reglas comunes: curva COMPLETA siempre (`plateau_stop` PROHIBIDO — lección M0_G2); métricas y
umbrales congelados acá; comparaciones a igual wall, nunca a igual step; harness existente
(`m0_grok_accel.py` para X1/X2 — una corrida MQAR ≈ 256 s CPU, grok baseline conocido = step 3600,
acc ~0.82 — y kernel `xh_ablate`/receta K3 para X3–X5). Orden = X1 primero: es el más barato y
FALSEA la pieza más riesgosa (la premisa "hay que pagar el plateau", que multiplica el costo de
TODO el plan ×10–100 si fuera cierta).

| # | experimento | hipótesis (H) | métrica | presupuesto | PREDICCIÓN pre-registrada |
|---|---|---|---|---|---|
| **X1** | **Plateau = ¿artefacto?** — init-scale α∈{0.25,0.5,1,2,4} (Omnigrok) + progress measure por step (logit-gap del token correcto o norma del sub-circuito de atención) sobre `m0_grok_accel.py` (wd=0) | el delay es de parametrización, no esencial; el aprendizaje interno es gradual | steps-to-grok (acc≥0.8) por α; adelanto de la progress measure vs salto de acc | **~35 min CPU** (5 brazos + logging) | α<1 reduce el plateau ≥30%; α>1 lo alarga; la progress measure mejora suave ≥1000 steps antes del salto. Si α chica NO mueve el grok-step, nuestra transición no es artefacto de init y "pagar el plateau" revive (acotado a esta tarea) |
| **X2** | **Reembolso del delay** — 4 brazos × 2 seeds: baseline wd=0 · Grokfast-EMA (λ∈{2,5}, α=0.98, ~20 líneas) · StableMax en la salida · Muon vs AdamW en la misma tarea | el grok-step se compra barato con optimizador/estabilidad | steps-to-grok y wall a igual acc final (≥0.80); overhead por step (<5% o se descarta) | **~60 min T4** (1 sesión, compile ON) | algún brazo baja ≥2× los steps; Muon ~1.5× (2504.16041); riesgo pre-registrado: Grokfast-EMA inestable. Si nada baja ≥1.3×, los aceleradores de paper no transfieren y la receta queda en init+datos |
| **X3** | **MoM-mínimo vs generalista vs LoRA** — (a) generalista 97.5M mezcla 3 dominios; (b) 2–3 expertos 97.5M, 100% su dominio; (c) generalista + LoRA corto por dominio; receta K3 congelada, 12 min train c/u; router trivial n-grams (CPU, <5 ms, accuracy medida aparte, gate ≥95%) | la especialización densa paga su nicho más que el LoRA-control | bpb held-out POR dominio (bytes crudos) + G2/G3 + cloze-es | **~75 min T4** | cada experto gana su nicho ≥0.10 bpb (brazo G ganó 0.16) pero pierde ≥0.3 fuera; **decisión: si (c) empata a (b), el MoM denso NO paga y gana el diseño 08**; gate honesto: si ningún brazo LM muestra transición abrupta, "entrenar hasta el eureka" queda falseado a este presupuesto |
| **X4** | **Calibrador: selección vs fusión** — sobre los expertos de X3: (i) selección por router n-grams, (ii) selección por verificador/cloze (`router.py` mode="verifier", acciones={exp_a, exp_b, generalista}), (iii) mezcla de logits c-BTM; curva de aprendizaje del bandit completa | fusionar no supera a seleccionar; el "unidor" aprende gradual, sin eureka | calidad por dominio de la respuesta elegida/fundida; regret del bandit | **~20 min CPU** (reusa checkpoints de X3) | (iii) NO supera a (ii) → el calibrador-fusionador queda falseado en pequeño y el diseño cae a selector; el bandit aprende el mapeo consulta→experto sin ground-truth de dominio (regret ≤0.01 como exp029/086); la curva del unidor es gradual |
| **X5** | *(condicional a que X1/X2 dejen vivo el régimen)* **¿Existe el nicho-grokking real?** — mini-lenguaje formal con checker exacto (expresiones tipadas / regex→string), tiny 10–40M, grid 3 tamaños de dato (abundante/medio/escaso barriendo D_crit) × 2 mezclas φ; + transfer: fine-tune del checkpoint grokkeado vs no-grokkeado (mismo train loss) en tarea vecina | el grokking aparece SOLO en escaso+φ-alto; el grokkeado transfiere igual o peor | accuracy OOD (composiciones no vistas) vs steps; Δ de transfer | **~90 min T4** (3–4 corridas ≤30 min) | abundante → misma OOD sin plateau (de-grokking); escaso+φ-alto → plateau+salto; muy escaso → ungrokking; transfer ≈ igual (2601.09049). Si abundante alcanza la misma OOD, "experto grokkeado por dominio" queda como metáfora y gana "datos+entreno normal" |

Criterio de cierre global: si X1+X2 confirman que el delay se elimina/reduce con parametrización,
la receta MoM se escribe SIN presupuesto de plateau ("grokking inducido o evitado, nunca
esperado"). Si X3 da (c)≥(b), los expertos servibles son LoRA y los densos quedan como vehículo de
investigación. Si X4 da (iii)≤(ii), el calibrador ES un selector y se cierra la discusión con ~1
hora de cómputo total.

---

## 7. Riesgos y qué NO prometer

| # | riesgo / promesa prohibida | por qué |
|---|---|---|
| P1 | **NO prometer "expertos grokkeados"** como propiedad del producto | el grokking no es invocable a voluntad fuera de su ventana (D_crit, regla compacta); en LM real es asíncrono por sub-habilidad; las normas del lenguaje se aprenden sin él |
| P2 | **NO prometer generalización OOD composicional** | Wang 2024: la composición grokkeada generaliza ID y falla OOD sistemáticamente |
| P3 | **NO prometer estabilidad del circuito** | ungrokking natural con entrenamiento posterior (2606.26050) y por escasez (Varma); un experto que se sigue actualizando puede DES-aprender |
| P4 | **NO prometer calidad general de un 100M** | bpb 1.38–1.52 y deriva medidos; sub-entrenado estructural por diseño (0.2–0.45 tok/param); "funcional" ≠ "bueno" |
| P5 | **NO prometer 4× de velocidad de conversación** | el 4.3× es por turno ruteado al chico; la conversación total medida mejora 1.11× (exp021) |
| P6 | **NO prometer servir densos propios en la red Cognia** | sin PyTorch en nodos; export GGUF de la arquitectura banded NO validado; FedAvg-solo-LoRA vigente |
| P7 | **Grokfast NO es palanca segura** | inestable y sensible a hiperparámetros (NeuralGrok); variante MA ×2.4 wall; sin replicación en pretraining LM real — solo entra si X2 la valida |
| P8 | **Riesgo de Goodhart en el calibrador** | mode="confidence" fue secuestrado (CYCLE 12); toda recompensa del selector pasa por verificador real; dominios no ejecutables quedan sin señal fuerte — declararlo, no taparlo |
| P9 | **Riesgo de importar recetas de paper** | wd (el acelerador canónico) FRENA nuestra transición; LR no-monótono; TODO acelerador se mide en el harness antes de entrar a la receta |
| P10 | **Riesgo de re-litigar CYCLE 47 sin datos** | "más orquestación no mueve la aguja": el MoM se adopta por velocidad/modularidad SOLO si X3/X4 lo ganan; el orden verificador→expertos→router no se invierte |

---

**Cierre del pre-registro.** Este documento se congela antes de correr X1. Cambios posteriores van
en `01_DESVIOS.md` append-only con fecha y razón — nunca editando las predicciones de acá.

---

## 8. Resultados (post-registro, no editan las predicciones de arriba)

### X1 — CORRIDO 2026-07-02 (9.6 min CPU, `results_x1/xh_x1_results.json`)

| α init | steps-to-grok | final_acc |
|---|---|---|
| 0.25 | **900** (−75%) | 0.975 |
| 0.5 | 1000 (−72%) | 0.963 |
| 1.0 | 3600 (= baseline conocido, réplica exacta) | 0.989 |
| 2.0 | 1100 (−69%) | 1.000 |
| 4.0 | 1500 (−58%) | 0.999 |

**Veredicto de la pieza más riesgosa: "hay que pagar el plateau" queda FALSEADO** (en este
harness): α=0.25 reduce el plateau 75% (predicción pedía ≥30%) sin sacrificar calidad final.
**Dos predicciones FALLIDAS (honesto):** (1) α>1 NO alarga — también acelera (curva no-monótona
con el PEOR caso en la init por defecto α=1); difiere del Omnigrok canónico y re-confirma la
regla pre-registrada: los aceleradores son régimen-dependientes, se miden acá. (2) el logit-gap
NO adelanta el salto (lead 0-100 steps ≪ 1000 predicho): nuestra transición es abrupta también
en la progress measure — consistente con §1: el fenómeno propio es "abrupt learning" (formación
de induction head), otro animal que el grokking post-overfit de Power et al.
**Consecuencia para la receta MoM (criterio de cierre §6):** se escribe SIN presupuesto de
plateau — "grokking inducido o evitado, nunca esperado". Barrer α al armar el harness de un
experto cuesta minutos y puede comprar 4×.

### X2 — CORRIDO 2026-07-02 (94.6 min CPU, `results_x1/xh_x2_results.json`; desvío declarado:
local en vez de T4, mismo harness que X1)

| brazo | grok_steps (seeds 0,1) | final_acc | veredicto |
|---|---|---|---|
| adamw (baseline) | 3600, 1700 (media 2650) | 0.81, 0.88 | referencia; **alta varianza por seed** |
| grokfast λ=2 | NUNCA, NUNCA | 0.36, 0.36 | **MATA la transición** |
| grokfast λ=5 | NUNCA, NUNCA | 0.37, 0.36 | ídem |
| stablemax | NUNCA, 8800 | 0.37, 0.86 | retrasa (0.3× vs baseline) |
| muon | NUNCA, NUNCA (+40%/step) | 0.42, 0.29 | no grokea esta tarea |

**Veredicto (el fallback pre-registrado): los aceleradores de paper NO transfieren a este
harness — todos empeoran o matan la transición.** El riesgo pre-registrado de Grokfast
(inestable) quedó confirmado en su versión fuerte. El contraste más instructivo es Muon: GANA
el entrenamiento LM a 100M (K2, Δ0.072 bpb) y NO grokea el MQAR tiny — no hay optimizador
"universalmente más rápido"; la regla "medí en TU harness" queda validada dos veces (X1: α>1
acelera contra Omnigrok; X2: todos los aceleradores fallan contra sus papers). **La receta de
aceleración de transiciones queda en: parametrización de init (X1, hasta 4×) + datos — no en
el optimizador.** Nota de método: la varianza por seed del baseline (3600 vs 1700) implica que
TODA comparación futura de grok-steps necesita ≥2 seeds (X1 corrió seed única; sus −75% con
α=0.25 superan con margen la varianza observada, pero se anota).
