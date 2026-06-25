# roadmap.md — fases y estado de Cognia-X

> Estado por fase. Una fase avanza solo con evidencia (no por intuición).
> Constitución operativa vigente: `_directiva_v3.md` (descarta lo HECHO, deja lo PENDIENTE; absorbe
> las lecciones de 23 ciclos como reglas). v1/v2 se conservan (append-only).
> **North Star de INGENIERÍA (visión del dueño para entrenar):** `ARQUITECTURA_OBJETIVO.md` — jerarquía de
> expertos + planificador/verificador + metarrazonamiento + hipótesis + auto-mejora. El arco v4 (40-50) ya
> demostró sus piezas centrales en pequeño (ver Apéndice A de ese doc).

## F0 — Fundación del laboratorio  ✅ DONE (2026-06-17)
- [x] Subproyecto independiente `cognia_x/` + rama `cognia-x`.
- [x] Meta-prompt mejorado (constitución operativa) + original conservado.
- [x] Documentación viva mínima en `manager/` (los 9 archivos).
- [x] Primer experimento reproducible corrido (exp001) — el lab "corre de verdad".

## F1 — Ciclo-1 de investigación (mapa de evidencia)  ✅ DONE (2026-06-17)
- [x] exp001 (coste de mezcla) → H-MEZ-1/2; exp002 (capacidad de recall) → H-MEZ-3.
- [x] Workflow de 13 agentes (6 dimensiones), 24 hipótesis verificadas adversarialmente.
- [x] Síntesis integrada en `architecture.md` / `decision_log.md` / `hypotheses.md` / `assumptions.md`.

## F2 — Decisiones por componente (conservadora/moderada/radical)  ✅ DONE (2026-06-17)
- [x] 6 componentes con sus 3 alternativas + evidencia → `architecture.md` (§1-7), `decision_log.md` (D-006..D-012).

## F3 — Validar las constantes en el hardware objetivo  🟡 EN CURSO
La tesis es defendible en dirección; varias constantes ya se midieron en CPU:
- [x] exp003 = E3: inexactitud del FedAvg de LoRA (error 0→66%, rango K·r→r).
- [x] exp004 = E1: roofline CPU — bandwidth-bound (float32 ~2.2× f64; hilos saturan a 2).
- [x] exp005: frontera coste del híbrido (H-MEZ-4) — 3/24 full = ~12-15% del coste de full puro a L=8192.
- [ ] E2 real: SWA vs atención full en llama.cpp con GGUF — tok/s(L) + KV-cache.
- [ ] Cerrar el eje **recall** del híbrido (tarea multi-capa entrenada; entrenamiento en Kaggle GPU).
- 🟡 **CYCLE 24 (exp011, EN CURSO):** ¿el plateau de recall lineal (~0.18) es de FORMA del kernel
  (Taylor 2do orden) o de INIT (mimetic), no de tamaño de estado? 4 brazos a d=24, step-parity.
  Cierra/afila la línea del techo de recall (H-CEIL-1/2/3).

## F4 — Boceto de arquitectura CPU-first v0  🟡 EN CURSO (implementado + entrenando)
- [x] Modelo híbrido v0 en PyTorch CPU (`cognia_x/model/hybrid.py`): la arquitectura del ciclo-1 hecha código.
- [x] Pipeline de entrenamiento (recall + char-LM) verificado y lanzado (corrida nocturna).
- [ ] Documentar resultados: ¿el híbrido cierra el eje recall (H-MEZ-4)? + calidad del char-LM.

## F5 — Aprendizaje continuo viable en CPU  ⬜ PENDIENTE
RAG document-level + LoRA + fusión intra-cuenca, medido (sin olvido catastrófico).

## F6 — Auto-mejora Nivel 1→2 con gates de estabilidad  🟡 EN CURSO
Observación → recomendaciones, con evaluador verificable + rollback antes de subir de nivel.
- [x] Nivel 1: aprende sin olvido (CYCLE 8/10: gate por-dominio + replay + examinador no-circular).
- [x] Anti-colapso (CYCLE 11): verify-before-learn PREVIENE colapso (examinador real + rollback).
- [x] **Nivel 2 — AUTO-MEJORA verificada (CYCLE 29, H-LEARN-1 apoyada):** en tarea verificable, el modelo
  aprende de su propia salida VERIFICADO-CORRECTA y MEJORA (STaR); la corrección del oráculo es el motor
  (control random_matched lo aísla). exp016, n=4, t-pareado p<0.05. Avanza CYCLE 11 (prevención→habilitación).
- [ ] Verificador RUIDOSO/PARCIAL + verificador chequeable real (código→sandbox; hechos→≥2 fuentes) en vez
  del oráculo aritmético; cuota de sintético + ledger de procedencia para loops largos (F-LEARN-2 continúa).

> Criterio de avance entre fases: hipótesis clave apoyada por experimento reproducible + 0
> regresiones + reproducibilidad mantenida.

## F-V4 — RESET a la raíz (R-VALOR como North Star)  🟡 EN CURSO (2026-06-24)
Tras excavar el árbol de descomposición raíz (`decomposition_tree.md`, 6 lentes + auditoría adversarial),
el verdadero primer problema es **R-VALOR** (función de valor endógena), no la eficiencia del decode (que
es un SÍNTOMA). Constitución vigente: `_directiva_v4.md` (conserva v1/v2/v3). La tesis bytes-por-token
queda como restricción de VIABILIDAD, no como dirección.
- [x] **CYCLE 35 (exp022) — H-V4-1: MIXTA.** R-INTERVENCIÓN demostrada (el pasivo queda PLANO bajo
  intervención por más presupuesto → muro informacional; flatness ~0.013; B-A=+0.31; gap invisible i.i.d.).
  R-VALOR específico NO aislado (el azar-activo basta con presupuesto). R-INTERVENCIÓN → techo 'real';
  R-VALOR → 'asumido'. D-V4-1 registrada.
- [x] **CYCLE 36 (exp023) — H-V4-1b: MIXTA→refuta el valor-como-info-gain.** En régimen duro (D=40,
  clúster=8, ruido 0.25) el info-gain NO supera de forma robusta al azar-activo (margen medio +0.004); lo
  robusto es ACTUAR≫observar. Lever = INTERVENCIÓN, no el valor diseñado. R-INTERVENCIÓN reforzada (real);
  R-VALOR 'asumido' refinado (info-gain descartado). D-V4-2 (pivote a act-and-verify).
- [x] **CYCLE 37 — barrido de literatura** (`literature_v4.md`): corrobora exp023 (CAASL ~5-6% a d=10);
  R-VALOR forma-fuerte (empowerment) tiene soporte; camino barato = substrato chico + verificador (TTS).
- [x] **CYCLE 38 (exp024) — H-V4-1c: APOYADA. R-VALOR es REAL en su forma fuerte (empowerment).** Inversión
  limpia: el empowerment (Blahut-Arimoto, sin reward/verificador externo) aísla lo CONTROLABLE (1.71 bits) y
  da 0 al reloj predecible-inútil; la predicción pasiva hace lo contrario. controlabilidad≠predictibilidad.
  R-VALOR forma-fuerte → techo 'real'; unificado con R-INTERVENCIÓN. D-V4-3. 0.57s CPU.
- [x] **CYCLE 39 (exp025) — H-V4-1d: APOYADA. El empowerment como VALOR mejora la tarea.** A capacidad
  limitada k=n_ctrl: empowerment 1.000 / predictibilidad 0.250 (=azar) / azar 0.453; predictibilidad
  ANTI-útil. R-VALOR aplicado → 'real' (bajo recursos limitados). Arco R-VALOR cerrado (mecanismo+utilidad). D-V4-4.
- [x] **CYCLE 40 (exp026) — H-V4-1e INTEGRADOR: APOYADA. El salto al LENGUAJE funciona.** Sobre el MODELO
  PROPIO del lab (HybridLM byte-level desde cero) + oráculo de suma como verificador, asignar el cómputo de
  test-time (act-and-verify: muestrear=actuar + verificar=quedarse con lo correcto) por CONTROLABILIDAD/
  CONSECUENCIA supera al AZAR y a la PREDICCIÓN-PASIVA a IGUAL presupuesto, bajo ESCASEZ. Régimen
  discriminante avg=3 (4 seeds in-band, M=120): CONSEC 0.562 / AZAR 0.506 (+0.056) / PASIVA 0.490 (+0.073),
  ambos >2σ(0.045). La PASIVA-incertidumbre es la PEOR (anti-útil) — control decisivo del arco v4 AHORA en
  lenguaje. Caveat honesto (curva): a avg>=6 + verificador perfecto el azar alcanza (techo) → la ventaja vive
  bajo ESCASEZ (misma forma que exp025). Unifica R-INTERVENCIÓN+R-VALOR; convergente con TTS verifier-based
  (arXiv:2408.03314). ~50s/seed CPU. D-V4-5. Techo 'real': R-VALOR aplicado al lenguaje.
- [x] **CYCLE 41 (exp027) — H-V4-1f: MIXTA (matizada).** Verificador RUIDOSO simétrico (vnoise=FP=FN) sobre el
  act-and-verify de exp026; accuracy REAL del commit (castiga falsos positivos). 4 seeds in-band, avg=3.
  Curva vnoise→CONSEC/AZAR/PASIVA/greedy: 0.0:0.544/0.490/0.483/0.317 | 0.05:0.502/0.452/0.483 |
  0.10:0.444/0.440/0.435 | 0.20:0.358/0.385/0.398. DOS caras: (ROBUSTEZ) el lazo NUNCA cae bajo greedy en
  ningún ruido → degrada con gracia; (FRAGILIDAD) la ventaja del lever de CONTROL es CONDICIONAL a la calidad
  del verificador: significativa a error≤~5%, diluida a ~10%, invertida a 20% (la señal de consecuencia
  depende del verificador; la pasiva-entropía no). A vnoise=0 reproduce exp026 (validación cruzada). D-V4-6,
  techo 'real'. → el integrador debe priorizar verificador preciso/auto-calibrado o una señal de control
  robusta-al-ruido.
- [x] **CYCLE 42 (exp028) — H-V4-1g: MIXTA. No hay señal de asignación única dominante.** Señal de control
  VERIFIER-FREE (consenso emergente p_top de rollouts, sin tocar el verificador) vs la verifier-dependiente,
  bajo verificador ruidoso. 4 seeds in-band, avg=5, n_probe=3. Curva vnoise→AZAR/PASIVA/CONSEC_V/CONSEC_FREE:
  0.0:0.642/0.629/0.710/0.640 | 0.1:0.529/0.525/0.560/0.531 | 0.2:0.446/0.485/0.412/0.444. ROBUSTA SÍ
  (FREE−CONSEC_V=+0.031 a vnoise=0.2, donde CONSEC_V colapsa a la peor); RECUPERA-EL-EDGE NO (CONSEC_V domina
  a verificador bueno; CONSEC_FREE sólo empata baselines). El control verifier-dependiente paga con verificador
  confiable y colapsa sin él; el verifier-free es robusto pero no un free lunch. (El test de regresión cazó un
  bug: la señal p_top·(1−p_top) era simétrica; corregida a consenso-emergente monótono el MIXTA se mantuvo →
  null real.) D-V4-7, techo 'real'. → integrador necesita política ADAPTATIVA.
- [x] **CYCLE 43 (exp029) — H-V4-1h: APOYADA. CAPSTONE del sub-arco integrador (cierra 40-43).** Política
  ADAPTATIVA que estima la fiabilidad r del verificador por TEST-RETEST (re-consultarlo y medir su auto-acuerdo;
  SIN ground-truth, NO depende del consenso del modelo débil) y mezcla w=r·CONSEC_V+(1−r)·CONSEC_FREE. Logra
  NO-REGRET. Curva vnoise→CONSEC_V/CONSEC_FREE/ADAPT(r_est): 0.0:0.690/0.621/0.688(r=1.00) |
  0.1:0.527/0.550/0.535(r=0.61) | 0.2:0.415/0.415/0.437(r=0.39). keeps_edge a verificador bueno (r≈1→usa
  CONSEC_V) Y escapes_collapse a ruido alto (ADAPT 0.437 > CONSEC_V 0.415, hasta supera a las dos puras);
  worst_regret +0.008. r calibra monótona 1.00→0.39. D-V4-8, techo 'real'. Límite honesto: detecta ruido
  ALEATORIO, no SESGO sistemático.
- [x] **CYCLE 44 (exp030) — H-V4-1i: MIXTA. La verificación INTERMEDIA frena el compounding.** Cadena de sumas
  mod 20 sobre el modelo propio; step-wise act-and-verify vs end-to-end best-of-k a IGUAL cómputo (k·K).
  Curva K→END_TO_END/STEP_WISE/gap: K1:0.667/0.692/+0.025 | K2:0.317/0.448/+0.131 | K4:0.046/0.219/+0.173 |
  K6:0.004/0.092/+0.088. El gap ABSOLUTO no es monótono (cae a K=6 porque AMBAS colapsan a 0 con presupuesto
  por-paso fijo), pero la ventaja RELATIVA crece monótona y es enorme (1.04×→4.8×→23× a K=6). La verif
  intermedia (supervisión de PROCESO, cf. Lightman 2023) frena el compounding pero no lo elimina a presupuesto
  por-paso fijo. (Se detectó y corrigió un piso de suerte mod-20 → verif de TRAZA COMPLETA.) D-V4-9, techo
  'real'. → integrador multi-paso necesita presupuesto per-step ESCALADO/ADAPTATIVO.
- [x] **CYCLE 45 (exp031) — H-V4-1j: MIXTA (rescate fuerte).** Presupuesto ADAPTATIVO per-step (gastar-hasta-
  verificar con pool compartido: parar al verificar, reinvertir en los pasos difíciles) vs UNIFORME, a IGUAL
  cómputo total B=avg·K. Curva K→UNIFORME/ADAPT/gain: K2:0.446/0.598/+0.152 | K4:0.190/0.423/+0.233 |
  K6:0.119/0.333/+0.215 | K8:0.058/0.240/+0.181. El adaptativo GANA en TODA K (+0.15..+0.23) y RESCATA cadenas
  largas (a K=8 uniforme colapsa a 0.058, adaptativo aguanta 0.240 = 4.1×). MIXTA solo porque el gain absoluto
  no es monótono (pico K=4, satura a K extremo); la ventaja RELATIVA sí crece (1.3×→4.1×). D-V4-10, techo
  'real'. → integrador multi-paso = verificación de PROCESO (44) + presupuesto ADAPTATIVO per-step (45).
- [x] **CYCLE 46 (exp032) — H-V4-1k: MIXTA (lever de honestidad).** Abstención calibrada + verificador RUIDOSO
  per-step. Cuando ningún sample de un paso verifica, ABSTENER (decir "no sé") en vez de commitear basura.
  Curva K|vnoise→COMMIT/PREC/COV: 2|0.0:0.252/1.000/0.248 | 2|0.1:0.217/0.647/0.317 | 2|0.2:0.169/0.295/0.338 |
  4|0.1:0.054/0.293/0.081 | 6|0.1:0.002/0.125/0.017. FUNCIONA fuerte a cadenas cortas + verificador decente
  (precisión 1.000 vs commit 0.252 = +0.748, cobertura útil 0.248; a vn=0.1: 0.647 vs 0.217). PERO la cobertura
  COLAPSA a K largo (a K=6 ~0.01-0.02: abstiene todo) y la precisión se erosiona con ruido. Lever real de
  honestidad ("saber cuándo no sé") pero dependiente de régimen. D-V4-11, techo 'real'.
- [x] **CYCLE 47 (exp033) — H-V4-1l: MIXTA.** RETRY del paso fallido (segunda tanda desde el pool en vez de
  abstener) recupera COBERTURA material en cadenas largas (Δcov +0.19 a K6/vn0.1, +0.11 a K6/vn0.2) SIN dañar
  precisión — cumple la pre-registración. PERO su UTILIDAD está gateada por el verificador: donde recupera
  mucho (ruido alto) la precisión es baja (0.18/0.04 = rescata cadenas confiadamente-MAL); donde la precisión
  es alta (vn=0) el gain es sub-margen (+0.07). El colapso de cobertura NO se arregla insistiendo. (Nota de
  método: el piso de utilidad retry_prec≥0.5 es post-hoc, reportado, NO usado para forzar REFUTADA.) D-V4-12,
  techo 'real'. → **GIRO ESTRATÉGICO: el cuello de botella de TODO el integrador multi-paso (44-47) es la
  CALIDAD/PRECISIÓN del verificador y del paso, no la orquestación de cómputo.**
- [x] **CYCLE 48 (exp034) — H-V4-2: APOYADA. CAPSTONE del arco v4 (cierra el lazo verify→sustrato→razonamiento).**
  El lazo act-and-verify genera datos VERIFICADOS que mejoran el sustrato barato (auto-mejora STaR por la señal
  de CORRECCIÓN, no el volumen) y esa mejora se AMPLIFICA en multi-paso. PASO: base 0.317→VERIFIED 0.419
  (+0.102) vs CONTROL 0.258 (el control sin verificar EMPEORA el base → es la corrección). AMPLIFICACIÓN (cadena
  greedy, aísla el sustrato): ratio verified/base K1 1.32× → K2 1.93× → K3 2.71× (creciente). Una mejora modesta
  del paso (+0.10) rinde compuesta en lo largo. D-V4-13, techo 'real'. Cota honesta: base débil → cadena greedy
  a K≥4 cae a ~0 (piso; amplificación demostrada a K≤3).
- [x] **CYCLE 49 (exp035) — H-V4-2b: APOYADA. El lazo de auto-mejora es un MOTOR ESTABLE y FUERTE.** Iterar el
  lazo verificado R=4 rondas. PASO por ronda (prom): 0.300→0.472→0.456→0.481→0.508 (+0.208; mejor seed un base
  débil se bootstrappea a **0.783** paso, **0.753** cadena). CADENA: 0.187→0.436. SIN colapso de precisión
  (no-decreciente). DIVERSIDAD declina monótona 0.040→0.021 (~0.52× inicial = narrowing temprano, no colapso en
  4 rondas) → en rondas largas necesita MONITOR/inyector de diversidad. El filtro de CORRECCIÓN mantiene el
  lazo sano (consistente con anti-colapso CYCLE 11). D-V4-14, techo 'real'. → el integrador puede mejorarse
  SOLO de forma autónoma y sostenible.
- [x] **CYCLE 50 (exp036) — H-V4-2c: APOYADA. La guardia barata (dedup+replay) arregla el narrowing y sube el
  techo.** Lazo PLANO vs GUARDED (dedup de verificados + replay de datos semilla de la verdad), R=6. PLANO step
  por ronda [0.300,0.442,0.475,0.536,0.425,0.547,0.642] — trepa ERRÁTICO (cae a 0.425 en r4), cobertura
  estancada ~180. GUARDED [0.300,0.531,0.525,0.586,0.656,0.697,0.692] — suave y MÁS ALTO, cobertura CRECIENTE
  175→202, sin costo de precisión. Mecanismo: el plano se machaca en los verificados frecuentes (overfit fácil);
  dedup+replay sostiene la cobertura del espacio y sube el techo. Caveat: la diversidad-de-answers colapsa para
  ambos (vocab chico) → la COBERTURA de prompts es la señal válida. D-V4-15, techo 'real'. → el lazo de
  auto-mejora usa dedup+replay por defecto.
- [ ] **H-V4-3 (P0): salto a tarea más RICA + verificador real-chequeable** — código→sandbox (exp018) o
  razonamiento no-aritmético, donde el verificador es real y la diversidad no está acotada por un vocab chico;
  medir el techo del bootstrapping ahí.
- [ ] H-V4-4 (P0): identificabilidad causal sin cuerpo (SCM de juguete).

> Sub-arco AUTO-MEJORA (CYCLE 48-50) CERRADO: una ronda mejora el sustrato y se amplifica en multi-paso (48) +
> iterar es un motor estable y fuerte (49) + una guardia barata (dedup+replay) controla el narrowing y sube el
> techo (50). El lazo de auto-mejora del lab es autónomo, sostenible y CONTROLABLE sin un modelo más grande.

> Sub-arco MULTI-PASO (CYCLE 44-47) CERRADO en mecanismos: verificación de PROCESO frena el compounding (44) +
> presupuesto ADAPTATIVO per-step rescata cadenas largas (45) + ABSTENCIÓN honesta sube la precisión-sobre-
> respondidas (46) + BACKTRACKING/RETRY recupera cobertura (47). Los CUATRO convergen al mismo cuello de
> botella: la CALIDAD/PRECISIÓN del verificador y del paso.

> **ARCO v4 CERRADO (CYCLE 40-48):** el integrador del lab es un LAZO DE AUTO-MEJORA, no sólo orquestación.
> (1) Asigna cómputo test-time por controlabilidad + fiabilidad del verificador (40-43). (2) Lo extiende a
> multi-paso: proceso+presupuesto adaptativo+abstención+backtracking (44-47). (3) Genera datos VERIFICADOS que
> mejoran la precisión por paso del sustrato barato, mejora que se AMPLIFICA en multi-paso (48). Unifica
> R-INTERVENCIÓN (actuar+verificar) + R-VALOR (controlabilidad) sobre el modelo propio CPU-first. Próximo:
> ITERAR el lazo (H-V4-2b) + verificador real-chequeable + razonamiento no-aritmético = "algo que habla y razona, barato".

> Sub-arco MULTI-PASO (CYCLE 44-45) en curso: la verificación de PROCESO frena el compounding (44, MIXTA,
> ventaja relativa creciente) y el presupuesto ADAPTATIVO per-step rescata cadenas largas (45, MIXTA, rescate
> fuerte 4.1×). El integrador multi-paso = proceso + presupuesto adaptativo. Cota: a K extremo hace falta más B.

> Sub-arco INTEGRADOR (CYCLE 40-43) CERRADO: el lever de control es REAL (40, APOYADA), FRÁGIL al verificador
> (41, MIXTA), sin señal única dominante (42, MIXTA) y se RESUELVE con una política adaptativa calibrada por la
> consistencia del verificador (43, APOYADA, no-regret). El integrador de 1 paso queda diseñado y verificado.
- [ ] INTEGRADOR (P1): lazo act-and-verify barato con valor endógeno de CONTROLABILIDAD sobre el sustrato de
  lenguaje (unifica R-VALOR+R-INTERVENCIÓN; convergente con TTS verifier-based). H-V4-3/4/5/6: ver `_directiva_v4.md` §3.

> Estado del reset (CYCLE 35-40): NO-lever = predicción pasiva / info-gain / escalar params. SÍ-lever =
> ACTUAR (R-INTERVENCIÓN) con valor de CONTROLABILIDAD (R-VALOR=empowerment). DEMOSTRADO en tabular (exp024/
> 025) Y EN LENGUAJE sobre el modelo propio (exp026: act-and-verify TTS guiado por control gana bajo escasez).
> Arquitectura objetivo: substrato chico CPU propio + act-and-verify barato + TTS verifier-based, asignando
> cómputo por controlabilidad. Próximo realismo: verificador ruidoso/parcial + señal de control sin probe caro.

## F-V4b — Arco "R-VALOR bajo realismo" (CYCLE 72+)  🟡 EN CURSO (2026-06-25)
La corrida 51-71 validó el thesis v4 en juguete con oráculos/valores PERFECTOS. Este arco quita las muletas una
por una y mide si la tesis sobrevive (la debilidad honesta #1: todo es juguete con oráculo).
- [x] **CYCLE 72 (exp056) — H-V4-5b: APOYADA.** Ataca el caveat #1 del techo de CYCLE 70 (valor PERFECTO +
  selección estática). En memoria ONLINE (m=10/n=50, T=3000), estimar el valor de la frecuencia observada
  (LFU = valor endógeno) recupera 99% de la ventaja del oráculo (0.508) sobre random (0.219), +0.135 vs recency
  value-free; anti_value < random. R-VALOR×memoria no necesita oráculo en estacionario. Caveat: régimen
  estacionario (LFU≈óptimo clásico); la no-estacionariedad es la próxima hija. Techo 'real'; test 5/5.
- [ ] CYCLE 73: atar el estimador a la NO-estacionariedad (frecuencia con ventana/decay adaptativo + olvido por
  sorpresa de CYCLE 59 / selector de estrategia de CYCLE 66).
- [ ] CYCLE 74+: valores endógenos más ricos (info-gain/confianza) + downstream con consultas correlacionadas.
- [x] **CYCLE 73 (exp057) — H-V4-5c: APOYADA.** Hija del 72: el estimador de valor (frecuencia) debe OLVIDAR (decay)
  bajo no-estacionariedad. CROSSOVER: estac. lfu_full=0.511 gana (decay paga costo 0.443); no-estac. lfu_full
  DEGRADA a 0.341, lfu_decay=0.430 recupera 74% del oráculo, +0.090 sobre full y +0.051 sobre recency value-free.
  Ata R-VALOR (estimador) con el OLVIDO (CYCLE 58-66). Caveat: decay fijo; LRU competitiva con cambio fuerte. Techo
  'real'; D-V4-35; test 4/4.
- [x] **CYCLE 74 (exp058) — H-V4-5d: APOYADA. CIERRA el sub-arco 72-73-74.** El estimador de valor elige su tasa de
  olvido: un selector full<->decay gateado por el hit-rate reciente de cada experto (endógeno) logra NO-REGRET --
  ESTAC selector=0.507~full (usa decay 6%), NO-ESTAC selector=0.425~decay (usa decay 88%); ningún fijo gana en ambos.
  Replica el selector de estrategia (CYCLE 66) sobre el estimador de valor. R-VALOR × OLVIDO cerrado endógenamente.
  Techo 'real'; D-V4-36; test 4/4.

> SUB-ARCO R-VALOR-ESTIMADOR (CYCLE 72-73-74) CERRADO: (72) el valor es estimable de la frecuencia observada y
> recupera la ventaja del oráculo en estacionario, venciendo a una memoria value-free; (73) bajo no-estacionariedad
> el estimador DEBE olvidar (decay), crossover full/decay; (74) el estimador AUTO-selecciona su tasa de olvido por su
> propio acierto reciente (no-regret), sin hiperparámetro de régimen. R-VALOR × MEMORIA × OLVIDO queda atado a un
> valor ENDÓGENO ESTIMADO (no un oráculo). Frontera: valor más rico (info-gain/confianza) + downstream no-IID + escala.
- [x] **CYCLE 75 (exp059) — H-V4-5e: APOYADA. CAPSTONE CONCEPTUAL del arco realismo.** El VALOR != FRECUENCIA
  (task-definido = frecuencia × costo de fallar). COST_VARYING (v!=f): value_est=0.636 recupera 99% del oráculo, lfu
  (sólo frecuencia) 0.489 deja 0.150 sobre la mesa; COST_UNIFORM (v~f): value_est=lfu (la divergencia DRIVE la
  ventaja). Rebate "esto es sólo LFU": LFU óptimo SÓLO si valor=frecuencia. Liga memoria con R-INTERVENCIÓN. Techo
  'real'; D-V4-37; test 4/4.

> ARCO "R-VALOR BAJO REALISMO" (CYCLE 72-75) -- estado: el thesis R-VALOR×memoria sobrevive al quitar las muletas de
> juguete una por una: valor ESTIMADO online no oráculo (72), debe OLVIDAR bajo no-estacionariedad (73), AUTO-elige
> su tasa de olvido (74, no-regret), y el valor es TASK-DEFINIDO no un proxy de frecuencia (75). Frontera: costo
> revelado sólo al fallar (exploración/R-INTERVENCIÓN); valor endógeno más rico (info-gain/confianza); escala no-IID.
- [x] **CYCLE 76 (exp060) — H-V4-5f: APOYADA (matizada).** El valor task-definido SOBREVIVE a la observación gateada
  por la acción (costo revelado sólo al fallar): value_miss=0.634 (99% del oráculo) = value_full=0.634 > lfu=0.490;
  value_explore RESTA. El agente observa el costo de lo que NO cachea (su contrafáctico) -> no hace falta intervenir
  bajo estacionariedad. MATIZA R-INTERVENCIÓN sobre la memoria (débil acá). Techo 'real'; D-V4-38; test 4/4.
- [x] **CYCLE 77 (exp061) — H-V4-5g: REFUTADA (informativa).** ¿Drift+obs gateada -> intervenir? El problema es REAL
  (DRIFT value_miss=0.561 pierde 0.051 vs full=0.613; ESTAC miss=full) PERO la intervención naive (slot fijo) NO paga
  (value_explore=0.532 < miss). La intervención sobre la memoria, si paga, debe ser cheap/targeted (sorpresa-gateada,
  CYCLE 59), no un slot fijo. Cota 'real'; D-V4-39; test 4/4.

> ARCO "R-VALOR BAJO REALISMO" (CYCLE 72-77) CERRADO (sub-tema memoria): el thesis R-VALOR×memoria sobrevive al quitar
> 4 muletas (72-75) y se acota honestamente en 2 (76-77): el valor es estimable online (72), debe olvidar bajo
> no-estacionariedad (73) auto-seleccionando la tasa (74), es task-definido no frecuencia (75), aprendible con
> observación gateada por la acción (76), y la intervención naive sobre lo cacheado NO paga aunque el drift sea real
> (77 REFUTADA). Frontera para PIVOTAR: intervención sorpresa-gateada barata; valor endógeno más rico
> (info-gain/confianza, CYCLE 56-57); SCALE a un sustrato no-juguete (HybridLM); o la rama control/empowerment.
