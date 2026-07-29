# PREREG — Sonda del prompt QUE EL LAZO ARMA, fase 1: el FORK texto-vs-flujo

**Fecha:** 2026-07-29 ~05:50, sesión matinal 29 (hasta las 12:00). **Escrito
ANTES de implementar el runner y ANTES de correr.** Materializa la fase 1 de
PREREG_SONDA_LAZO_BORRADOR.md (diseñado la noche del 28→29); los brazos y la
lectura vienen de allí, con dos decisiones nuevas declaradas abajo (camino de
backend unificado y regla de infra para sin-HTML). Pendiente de revisión
adversarial ANTES de encender la GPU; las enmiendas se anotan aquí.

## Pregunta

El GAP con control concurrente (2026-07-28) dio sistema 15/23 (65%) vs crudo
19/23 (83%): el envoltorio roba ~17 pts. ¿El ladrón vive en el TEXTO del
prompt que el lazo arma, o en el FLUJO del lazo (parseo, reintentos,
validaciones, fallback, mockup)? Dos sondas del prompt DIRECTO no
transfirieron al lazo (fix2 v2 −5, v3 −4): esta sonda usa los prompts REALES
capturados del lazo (COGNIA_DUMP_PROMPTS, corrida b2_bon_gate_v2).

## Materia prima (verificada HOY, antes de escribir esto)

- `cognia/program_creator/generated_programs/b2_bon_gate_v2/prompts/prompts.jsonl`:
  96 prompts (24 ensayos × 4 muestras, 4 tareas × 6 reps del banco brutal).
- **Alineación verificada:** timestamps monotónicos, orden = ensayos de
  `resultados.json` × s=1..4, tarea del texto == tarea del ensayo en 96/96
  (0 desalineados).
- Homogéneos: temperature 0.2 (96/96), reasoning_effort None, max_tokens
  None (→ default 12000), system == `_SISTEMA_WEB` vigente (verificado
  contra el literal del código de hoy).

## Decisiones de diseño NUEVAS respecto del borrador (declaradas)

1. **Ambos brazos por el MISMO camino de backend:** `generator._call_llm(
   texto, "html", temperature=0.2)` con `COGNIA_CONSTRUCTOR_URL` DESPUESTO
   (popped) — el camino `generar`/llm_local que usó el lazo del gate
   (b2_sistema_real.py:52 lo despuebla: "que rutee EL sistema"). Motivo: el
   crudo histórico (`b1_router_oraculo.generar_html`) iba por
   `_preguntar_constructor`, un camino DISTINTO al del lazo; mantener esa
   asimetría confundiría texto con camino. Consecuencia declarada: el C de
   esta sonda no es numéricamente comparable con el crudo del GAP (además
   de la deriva); la lectura del fork es interna (L vs C concurrentes).
2. **"Sin HTML" con backend sano = REPROBADO LEGÍTIMO, no infra** (regla del
   PREREG_BON_GATE, distinta de la de b2_ab_gap): la espiral de
   contenido-vacío puede ser CAUSADA por el texto del prompt — contarla
   como infra escondería exactamente el efecto que se busca. Infra queda
   para: EXCEPCIÓN del harness, juez crasheado, backend degradado/≠8080,
   PresupuestoAgotado. `sin_html` se reporta por brazo como secundaria.

## Diseño

- Banco brutal (4 tareas), R=6 réplicas por brazo, apareado por
  (tarea, rep), INTERCALADO a nivel tarea (orden L/C alterna con
  (rep + i_tarea) % 2, la mecánica de b2_ab_gap). 48 generaciones.
- **Brazo L (replay):** para (tarea t, rep r), el prompt capturado del
  ensayo (t, rep=r) del gate v2, muestra **s = ((r−1) mod 4) + 1**
  (r1→s1 ... r4→s4, r5→s1, r6→s2). Regla FIJADA AQUÍ, ciega al outcome;
  cubre 24/96 capturados balanceados por s. Replay ÍNTEGRO: el texto
  capturado tal cual, misma temperature (0.2), mismo system (lo pone
  `_call_llm` por lenguaje="html"; igualdad ya verificada).
- **Brazo C (crudo):** la idea del enunciado tal cual
  (`b1_tareas_brutales.json`), mismo `_call_llm`, misma temperature.
- Parseo de la respuesta IDÉNTICO en ambos brazos (el helper de
  `b1_router_oraculo.generar_html`: _parse_response + fallback de fence).
- **Juez ESTRICTO por generación: contrato original ∧ held-out**
  (`b1_tareas_brutales.json` ∧ `b1_contratos_heldout.json`). Se juzgan
  ambos SIEMPRE (no solo si el original aprueba): la concordancia
  secundaria necesita el estricto completo.
- Fallback de Ollama neutralizado (módulo, como siempre);
  COGNIA_DUMP_PROMPTS APAGADO (no re-capturar); presupuesto de pared por
  celda activo (con_presupuesto, default 1200 s → PresupuestoAgotado =
  infra); guardado incremental + `--reanudar`; corrida DESACOPLADA.
- Requisito de infra: slots=1 confirmado en /props de :8080 ANTES de
  correr; gpt-oss con --ctx 16384.

## Métricas y umbrales (fijados ahora)

Primaria: **neto L−C sobre pares válidos** (gana L − gana C en discordantes
por estricto; pares con infra en cualquiera de los dos brazos, excluidos).

| lectura | veredicto pre-fijado |
|---|---|
| \|L−C\| ≤ 2 | **el ladrón NO está en el texto del prompt** — está en el FLUJO del lazo; las ablaciones de texto NO se corren; fase 2 = instrumentar el flujo (parseo, reintentos, validaciones, mockup) |
| L−C ≤ −4 | **el texto roba**: fase 2 = ablaciones por CONTENIDO de pieza (troceo REQUIRED primero, brief-en-bold segundo, feromona tercero), pre-registradas aparte |
| L−C = −3 | zona gris: ampliar réplicas si el reloj alcanza (dimensionar), sin veredicto |
| L−C ≥ +3 | sorpresa (el texto del lazo AYUDA): se reporta y la fase 2 va al flujo |

- El veredicto se lee con pares COMPLETOS; <12 pares válidos = solo
  direccional (regla de siempre).
- **Este veredicto NO adopta nada:** decide dónde se gasta la fase 2.

Secundarias (se reportan, no deciden):

- **Concordancia del replay:** outcome estricto del replay vs outcome
  estricto ORIGINAL de esa misma muestra en el gate (de resultados.json:
  orig[s].aprobado ∧ aprobado_sel). Mide cuánto del outcome vive en el
  texto (determinismo a temp 0.2) vs en el ruido de generación.
- Neto por contrato original solo (comparabilidad direccional con el GAP).
- `sin_html` y crashes por brazo (¿el texto del lazo dispara más
  espirales?).
- Tiempos por celda; checks_ok en fallidas (¿fallas ajustadas o
  desplomes?).

## Presupuesto

48 gens × ~85 s ≈ 70 min GPU + 96 juzgados Playwright × ~12 s ≈ 20 min →
**~1.5-1.8 h**. Si el reloj corta, `--solo-resumen` lee el parcial.

## Revisión

Revisión adversarial (2 agentes: diseño / implementación) del prereg +
runner ANTES de encender la flota; humo barato (1 celda por brazo, tarea
kanban, --sufijo humo) ANTES de la corrida completa.

## PRIMERA ENMIENDA (2026-07-29 ~06:35 — tras la revisión adversarial, ANTES de correr)

Dos agentes (diseño con Monte Carlo ejecutado / implementación con dry-runs
ejecutados). DOS BLOQUEA convergentes + arreglos, todos aplicados al runner
antes de gastar GPU:

1. **BLOQUEA (los dos agentes): la espiral de contenido-vacío quedaba
   clasificada INFRA y el par excluido** — `_call_llm` con texto vacío cae a
   `sin_backend` (registro degradado con server sano) y el timeout de 120 s
   de `generar` (3/96 celdas del gate rozaron 115 s) censuraba espirales
   lentas. Sesgo DIRECCIONAL pro-"flujo": los prompts L (~6k chars) sufren
   ese canal más que C. **Fix:** ambos brazos llaman `llm_local.generar`
   DIRECTO con los args exactos del lazo (system=_SISTEMA_WEB,
   max_tokens=12000, effort None) y timeout 400 (desviación del 120 de la
   captura, declarada: no censurar; simétrica). Clasificación nueva:
   `""` con server sano → sin HTML legítimo; None con server sano →
   reprobado legítimo (contador aparte); server caído (health post-fallo
   KO) / degradado / puerto ≠8080 / EXCEPCIÓN → infra. La cita al
   PREREG_BON_GATE de la decisión 2 era infiel (el gate contó el vacío como
   muestra infra): la regla de ESTA sonda es la de arriba, propia.
2. **BLOQUEA (diseño): la rama "flujo" (|L−C|≤2) tenía ~26% de error de
   cierre bajo H_texto (Monte Carlo con la estructura real del GAP) y era
   irreversible.** Lectura REEMPLAZADA: **neto ≥ 0 → flujo** (el texto no
   roba); **−1 → fase 2 prioriza flujo** (texto no cerrado); **−2/−3 → SIN
   VEREDICTO, extensión pre-comprometida a `--replicas 8`** (n=32, ~30 min)
   y relectura: ≤−5 texto, −3/−4 gris que prioriza flujo sin cerrar texto,
   ≥−2 flujo; **≤ −4 → el texto roba SOLO si las victorias de C vienen de
   ≥2 tareas** (concentradas en 1 = investigar esa tarea antes de declarar);
   **≥ +3 → sorpresa, se reporta, fase 2 flujo**. La frase "las ablaciones
   NO se corren" queda retirada: cerrar la vía texto exige neto ≥ 0.
3. **Primaria vs secundaria en ramas distintas (arreglo):** si el neto
   estricto y el neto por contrato original caen en ramas distintas, el
   veredicto es GRIS (dimensionar), pre-declarado.
4. **Regla de s des-confundida (arreglo):** `s=((r−1+i_tarea) mod 4)+1`
   (la original confundía s con rep y daba cobertura 8/8/4/4; ésta da
   6/6/6/6). Extensión a r>6: `rep_gate=((r−1) mod 6)+1`.
5. **Declaraciones añadidas:** los 4 prompts de ensayos que fueron infra en
   el gate están ÍNTEGROS (verificado por-prompt: brief + REQUIRED
   presentes, largos normales) — la degradación golpeó la generación, no la
   construcción del prompt; la concordancia replay↔gate tiene denominador
   ~21 (3 filas con estricto_gate=None) y se lee por ASIMETRÍA direccional
   (la deriva ~20 pts/12h infla gate-sí→replay-no); C está en techo en 3/4
   tareas (GAP crudo 5/5, 6/6, 2/6, 6/6): un neto positivo chico no se
   sobre-lee, y el resumen desglosa por tarea; el system (_SISTEMA_WEB, con
   su "must animate") es constante en ambos brazos → invisible para esta
   sonda.
6. **Endurecimientos de runner:** chequeo de arranque exige slots=1 Y
   n_ctx ≥ 16384 (la mitad olvidada de la lección v1); OLLAMA_MODEL
   neutralizado también por env (Ollama está VIVO en esta máquina y
   detectar_backend caería a él con :8080 muerto); 4 celdas infra seguidas
   → aborto con parcial guardado; backend capturado en el mismo hilo de la
   generación (el hilo huérfano de PresupuestoAgotado no puede pisarlo);
   `--tarea` para el humo; sin_html del resumen excluye celdas infra.

## SEGUNDA ENMIENDA (2026-07-29 ~06:10 — a 4 celdas de corrida, por cuelgue REAL del juez)

La celda 5 (kanban crudo r1) colgó al runner 8+ minutos con GPU ociosa:
la página generada bloquea el hilo principal con JS ocupado (chromium con
**595 s de CPU clavado**, medido con el proceso vivo) y `page.evaluate` no
tiene timeout — el juez se queda esperando PARA SIEMPRE. El presupuesto de
pared solo cubría la generación: la misma clase de cuelgue que la celda
>45 min de b2_ab_gap (entonces atribuida al goteo del backend; este es un
segundo mecanismo con la misma firma).

- **Fix:** el juzgado (ambos contratos) corre bajo su propio presupuesto
  (300 s). Desborde → **reprobado LEGÍTIMO** con motivo "juez colgado (JS
  bloqueante)": es propiedad de la PÁGINA (un producto que cuelga al
  navegador no sirve), no infra; contador aparte por brazo en el resumen.
- Coste declarado: el hilo huérfano deja su chromium clavado a 100% de un
  core hasta el fin del proceso; se vigila que no se acumulen.
- Exposición al outcome: 4 celdas completas vistas (todas ESTRICTO-OK,
  2 replay / 2 crudo, sin discordantes) — el veredicto no se computó. La
  celda 5 no se guardó; `--reanudar` la regenera desde cero.

## TERCERA ENMIENDA (2026-07-29 ~06:35 — addendum PASIVO, a 11 celdas)

El runner guarda desde ahora la respuesta CRUDA de cada generación
(`respuesta_cruda.txt` + `crudo_chars`). No toca nada de lo medido; es la
materia prima para la rama FLUJO de la fase 2: el parse del lazo tiene
cuatro puntos de rechazo que el parse directo no tiene (corte de <think>,
fence estricto con truncado→regenerar, exigencia de `<html`, mínimo 30
chars) y con los crudos guardados esa comparación se hace SIN GPU. Las
primeras ~11 celdas no tienen crudo (se declara el denominador al usarlo).
Exposición adicional al outcome en el reinicio: ninguna (solo el conteo de
hechas).
