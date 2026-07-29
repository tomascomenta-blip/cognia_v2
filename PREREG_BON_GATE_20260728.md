# PREREG — Gate de confirmación del modo BoN cableado (K=4 + selector held-out)

**Fecha:** 2026-07-28 ~22:20, nocturna 28→29 (segunda noche). **Escrito ANTES
de correr.** La arquitectura BoN+señal ya quedó VALIDADA como experimento
(PREREG_BON_HELDOUT: techo +7, selector captura todo). Esto NO re-litiga esa
pregunta: mide que el CABLEADO de producción (`cognia/program_creator/bon.py`,
modo env-gated COGNIA_BON_K/COGNIA_BON_SELECTOR, commit de esta noche)
reproduce el efecto de punta a punta. Es un A/B de confirmación de ingeniería.

## Qué cambia respecto del experimento validado (declarado, no escondido)

1. El runner llama a `bon.construir_bon` (el módulo de producción que usará
   /construir), no al harness de investigación. El selector interno del modo
   es el mismo criterio que capturó el 100% del margen (aprobado held-out >
   checks held-out > s menor).
2. **Sin fallback a create_program dentro de las muestras:** construir_bon
   corre construir_para_mockup puro; una réplica que no produce HTML cuenta
   como muestra reprobada (en el experimento, 12/96 muestras llegaron por el
   fallback del harness). Es una propiedad real del modo cableado: se mide
   como es.
3. **Sin semillas por muestra:** producción no re-semilla; la diversidad
   viene del estado aleatorio natural entre réplicas (misma fuente: rehacer
   el pipeline entero).

## Diseño

- Banco brutal (4 tareas), R=6 réplicas, K=4, tareas ROTADAS por réplica
  (intercalado a nivel tarea). 24 ensayos objetivo, 96 generaciones.
- Por ensayo: `bon.construir_bon(idea, k=4, contrato_selector=held_out,
  guardar_muestras=dir, llm=None, usar_mockup_imagen=False, verbose=False)`.
  El modo juzga cada muestra con el held-out (queda en `res.bon`); el runner
  juzga cada muestra guardada con el contrato ORIGINAL. estricto(muestra) =
  original ∧ held-out. No se re-juzga el held-out (se lee del meta del modo:
  mismo juez, mismo commit, cero duplicación).
- **Control = muestra s=1 del propio ensayo** (mismo reloj, misma corrida —
  el diseño intra-ensayo del experimento validado). **Resultado del modo =
  estricto de la muestra ELEGIDA por el modo.**
- Infra (mismas reglas que PREREG_BON_HELDOUT + 1ª enmienda): EXCEPCIÓN del
  harness, juez crasheado, backend degradado/≠8080 → infra; "sin HTML" con
  backend sano = reprobado legítimo. Fallback de Ollama neutralizado (módulo
  + env). Ensayos incompletos fuera del apareado.
- Guardado incremental POR ENSAYO + `--reanudar` (+ `--acepta-commit` con la
  misma regla de siempre); corrida DESACOPLADA.
- **Presupuesto de pared duro por ensayo** (K × COGNIA_PRESUPUESTO_CELDA,
  default 20 min/celda, `cognia/presupuesto_pared.py`): el goteo lento de
  tokens no dispara el timeout por chunk (celda >45 min en b2_ab_gap);
  el desborde cae como EXCEPCIÓN → infra, pre-declarado.
- **Addendum pasivo (no altera lo medido):** COGNIA_DUMP_PROMPTS registra
  en `prompts.jsonl` cada prompt TAL COMO el lazo lo arma (con su system,
  temperatura y effort). Es la materia prima de la sonda futura del ladrón
  de ~17 pts (dos sondas del prompt DIRECTO no transfirieron al lazo); esta
  corrida la produce gratis. El volcado no toca los prompts ni el flujo.

## Métricas y umbrales (fijados ahora; 24 ensayos objetivo)

- **B — neto del modo** (elegida estricta vs control s1, resta apareada):

| B | veredicto |
|---|---|
| ≥ +4 | **CONFIRMADO**: el cableado reproduce el efecto; el modo queda listo para gates |
| +2..+3 | GRIS: el modo funciona pero el efecto llegó recortado — investigar el recorte (p. ej. el no-fallback) antes de usarlo en gates |
| ≤ +1 | NO CONFIRMA: bug de cableado o el efecto no transfiere — el modo NO se usa hasta diagnosticar |

- Secundarias (se reportan, no deciden): A techo pass@4 y pérdida C = A−B
  (sanidad del selector: C ≤ 1 esperado); nº de muestras sin HTML (mide el
  coste real del no-fallback); FP del original (D, actualiza memoria);
  composición de elegidas por s.
- Cortes parciales: veredicto con ensayos COMPLETOS; R<3 completas = solo
  direccional (regla de siempre).
- Presupuesto: 96 gens × ~85 s + 96 juzgados originales × ~12 s + 96
  held-out internos × ~12 s ≈ 3.0–3.4 h. Si el reloj de la sesión corta,
  `--solo-resumen` lee el parcial.

## Revisión

Revisión adversarial (1 agente, lente implementación+diseño) del prereg +
runner + bon.py ANTES de encender la flota. Los tests unitarios de bon.py
(10, sin GPU) ya están en verde.

## PRIMERA ENMIENDA (2026-07-28 ~22:30 — tras la revisión, ANTES de correr)

La revisión (verificaciones ejecutadas, no asumidas: backend_activo NO es
thread-local; PresupuestoAgotado cae al except correcto; sin circularidad
nueva en el control s1) encontró 1 BLOQUEA + 3 arreglos. Aplicados:

1. **Infra POR MUESTRA restaurada (BLOQUEA):** una réplica que CRASHEA
   dentro de bon quedaba como "sin HTML" (reprobado legítimo) — y si era
   s=1, el ensayo contaba "control falla, modo gana": sesgo pro-B justo en
   la dirección que confirma. Igual el juez held-out caído (`sel_crasheo`).
   Regla (la del experimento validado): `error` o `sel_crasheo` en s=1 o en
   la ELEGIDA → ensayo infra, fuera del apareado; crashes en s2-s4 solo
   achican el pool. Los crashes de réplica se reportan aparte de sin_html
   (h. 4: el coste del no-fallback no se infla con infra).
2. **Lectura condicional al headroom (h. 3):** neto B ≤ fallos del control
   por construcción y la deriva medida es ~20 pts/12 h. Si fallos_control
   < 5, CONFIRMADO = B ≥ fallos_control − 1 ∧ pierde = 0 (además de la
   tabla original, que rige con headroom ≥ 5).
3. **Regla de reanudación pre-declarada (h. 5):** los ensayos con EXCEPCIÓN
   quedan grabados y `--reanudar` no los repite. Si una tormenta transitoria
   de backend come ensayos, la poda manual de filas infra del JSON antes de
   reanudar está PERMITIDA y se anota en la config/log (nunca podar filas
   válidas).
4. Notas aceptadas sin cambio: la carrera del hilo huérfano tras
   PresupuestoAgotado puede ensuciar logs y el snapshot de backend del
   ensayo siguiente (el veredicto está a salvo: la fila es infra); fp_orig
   se cuenta sobre ensayos válidos (comparabilidad con la memoria
   fp-heldout aproximada, no exacta).

## RESULTADO (2026-07-29 ~01:30 — corrida v2 completa, veredicto por umbrales pre-fijados)

**CONFIRMADO: neto B = +8 (umbral ≥ +4).** 20 ensayos válidos (4 infra por
s1/elegida degradada), 0 incompletos.

- Control (s=1 estricto): **12/20 (60%)** — más bajo que el 71% del
  experimento (deriva conocida); headroom 8, así que la regla condicional
  de la 1ª enmienda no hizo falta.
- **Modo BoN (elegida): 20/20 (100%)** — el cableado rescató LOS OCHO
  fallos del control y no perdió ninguno (pierde = 0).
- Techo pass@4: 20/20; **pérdida C = 0** — el selector held-out capturó
  todo el margen otra vez, ahora a través del módulo de producción.
- Coste del no-fallback visible y tolerable: 3 muestras infra + 1 sin HTML
  de 80 (5%); elegidas s1×12, s2×5, s3×7 (s4 nunca — compatible con la
  espiral de presupuesto que golpea más tarde en el proceso, cuando la
  feromona ya engordó el prompt; anotado para la sonda del lazo).
- D (de paso): 4 FP más del contrato original (carrito 1, buscaminas 2,
  hoja 1) — actualiza la memoria fp-heldout.
- Materia prima de la sonda: 96 prompts del lazo capturados con outcome.

**Lectura de inversión:** la arquitectura BoN+señal ya no es solo un
resultado de experimento — es un MODO del sistema que reproduce el efecto
de punta a punta (con la mejora de que el modo entrega 100% donde el
experimento entregó 100%). El env-gate queda listo para gates de banco;
para producción general sigue faltando el generador de señal (la
conclusión de inversión no cambia).

## TERCERA ENMIENDA (2026-07-28 ~23:15 — corrida v1 ABORTADA por infra sistémica; corrida v2 desde cero)

A 5 ensayos de la corrida v1, la telemetría de infra (no el outcome) mostró
~50% de muestras con backend "degradado". Diagnóstico por la regla de
[[descartar-hipotesis-reproduce-condiciones]] — reproducir la llamada
exacta y mirar finish_reason/usage antes de culpar a capacidad:

- **Causa raíz: las builds recientes de llama-server usan `--parallel 4`
  por defecto y PARTEN `--ctx-size` entre slots** → 8192/4 = 2048 tokens
  por petición. El prompt del lazo con la visión VIVA mide ~1.5-2.2k
  tokens: todo prompt >2048 recibía **HTTP 500** determinista (verificado:
  el prompt capturado #9 mide 2190 tokens y daba 500). Anoche la flota
  servía con ctx 16384 (→4096/slot) y la visión DEGRADADA acortaba los
  prompts: por eso el fallo era ~15% y no 50%. Peor: las muestras
  "exitosas" de v1 generaban 5k+ tokens en un slot de 2048 vía context
  shift silencioso — TODA la corrida v1 queda contaminada, no solo las
  muestras 500.
- **Fix (ops, no toca cognia/):** servir_modelo.py pasa `--parallel 1`
  explícito (comentario con la medición); relanzado gpt-oss con ctx 16384.
  **Verificación REAL:** el mismo prompt #9 ahora genera finish=stop,
  usage 2190+5474 tokens, contenido 4813 chars.
- **La corrida v1 se descarta ENTERA** (dir b2_bon_gate intacto como
  evidencia; la v2 corre con --sufijo v2, mismo prereg, mismos umbrales).
  Exposición al outcome durante v1: solo las líneas "elegida sN" del log y
  los campos de infra/selector por muestra de 3 ensayos — ningún veredicto
  estricto se computó ni miró.
- Lección para memoria al cierre: el chequeo de arranque del server debe
  afirmar slots=1 (o ctx/slot suficiente), no solo /health — la lección en
  prosa no impide nada.

## SEGUNDA ENMIENDA (2026-07-28 ~22:40 — tras el HUMO, antes de la corrida)

El humo (kanban, K=2, --sufijo humo) cazó lo que la revisión no podía ver
sin correr: la muestra s2 falló con contenido VACÍO (la espiral de
razonamiento que quema el presupuesto — el mismo fallo que en el
experimento rescataba el fallback create_program, 12/96) y, sin fallback,
el ÚLTIMO intento es el Ollama neutralizado, así que `backend_activo`
termina con registro **degradado aunque el servidor esté sano** — y mi
snapshot único por ensayo marcaba TODO el ensayo como infra (n se habría
desplomado con ~10% de fallo por muestra).

Fix (fiel al experimento validado): **backend POR MUESTRA** en el meta de
bon.py (`fila["backend"] = backend_activo.ultimo()` tras cada réplica) e
infra POR MUESTRA en el runner (excepción de réplica, sel_crasheo, backend
degradado/≠8080): s1 o la ELEGIDA infra → ensayo fuera; muestra infra en
s2-s4 → solo achica el pool del techo. El contador `muestras_infra`
absorbe también el caso contenido-vacío (que el experimento veía como
fallback exitoso y aquí es una muestra perdida — el coste del no-fallback
queda visible en dos contadores: muestras_infra + sin_html). El humo
además VERIFICÓ: prompts.jsonl capturando el prompt del lazo, selector
held-out juzgando (18 checks), guardado incremental y resumen sin crash.
