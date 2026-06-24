# roadmap.md — fases y estado de Cognia-X

> Estado por fase. Una fase avanza solo con evidencia (no por intuición).
> Constitución operativa vigente: `_directiva_v3.md` (descarta lo HECHO, deja lo PENDIENTE; absorbe
> las lecciones de 23 ciclos como reglas). v1/v2 se conservan (append-only).

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
- [ ] **H-V4-1k (P0): backtracking/abstención + verificador RUIDOSO per-step** — cuando un paso agota su
  presupuesto sin verificar (commitea uno malo y descarrila): backtrack o abstención; y reusar la política
  adaptativa calibrada de 43 POR PASO bajo verificador ruidoso (el ruido per-step se compone).
- [ ] H-V4-2 (P0): identificabilidad causal sin cuerpo (SCM de juguete).

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
