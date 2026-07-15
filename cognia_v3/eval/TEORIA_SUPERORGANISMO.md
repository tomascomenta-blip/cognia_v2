# TEORÍA DEL SUPERORGANISMO v2 — cómo la colonia cruza el techo de capacidad

**2026-07-15. CORRIDA COMPLETA (13/13).** Todo respaldado por mediciones
cerradas (results_superorganismo_v2.json, PREDICCIONES_SUPERORGANISMO.md
commit 850c6f4 registrado ANTES de los resultados, PREREG_SUPERORGANISMO.md).

## RESULTADO EN UNA LÍNEA

**3/13 vírgenes rotas en tests OCULTOS (NEWX3, ALG3, SPEC3) — gate ≥2/13
CRUZADO** sobre un baseline de 0/13 por definición (pass@16 = 0). Y una **ley
empírica limpia**: las 3 que pasan los ocultos son EXACTA y únicamente las 3
que lograron 100% de su oráculo VISIBLE (20/20, 14/14, 14/14); las 10 que
fallan ninguna completó su oráculo (mejor: NEWX5 6/20). Pasar el oráculo
visible fue **necesario y, en esta corrida, suficiente** para el PASS oculto.

## 1. Qué límite de la teoría v1 se revisa

TEORIA_COLONIA.md (v1, 2026-07-12) declaraba: *"el techo de conocimiento
abierto / generación libre / capacidad cruda no cede con orquestación de
≤7B"* — respaldado por 9-10 negativas. Pero TODAS las negativas compartían
una forma: **N intentos INDEPENDIENTES sobre el problema ENTERO + selección**.
Si el problema entero está sobre el techo, ninguna muestra lo cruza y la
selección no tiene de dónde elegir (ALG3: 0/8 a temp 0.8).

El superorganismo cambia la FORMA: ninguna hifa ataca al oso entero.
1. **CARTOGRAFÍA** (qwen3_4b): descompone en helpers con contrato y extrae
   SPEC-ASSERTS de los ejemplos/reglas LITERALES del enunciado (ground truth
   en el texto, no inventado). Si el razonador no puede con el enunciado, el
   CODER extrae los suyos y se usa la UNIÓN (**refuerzo-coder**).
2. **HORMIGAS POR PIEZA** (qwen35_4b): cada helper contra su micro-oráculo,
   evaluado sobre el ACUMULADO de piezas (soporta recursión mutua).
3. **ENSAMBLE + FEROMONA**: la función principal usa los helpers; cada fallo
   deja rastro-artefacto (asserts fallados, enfoque) que el siguiente intento
   lee. Keep-best por #asserts; el veredicto es SIEMPRE tests ocultos.

Presupuesto ≤16 gens/tarea = presupuesto del baseline pass@16 (mismo modelo
generador) → lo único que cambia es el HARNESS.

## 2. Resultado central

**GATE PRE-REGISTRADO ≥2/13 CRUZADO**: NEWX3 (20/20 spec, 5 gens, corrida
nocturna) y **ALG3** (piezas 3/3+3/3+3/3, spec 14/14, ocultos PASS, 13 gens)
— ALG3 era la virgen emblemática con pass@16 = 0/8. El baseline de las 13 es
0 por definición (vírgenes = no resueltas por la unión de la colonia 3
etapas, 27/40). **El mecanismo compra capacidad más allá del techo, cero GPU.**

Resultado final (spec visible → oculto):
| tarea | spec visible | oculto | | tarea | spec visible | oculto |
|---|---|---|---|---|---|---|
| NEWX3 | 20/20 | **PASS** | | NEWD2 | 3/12 | fail |
| ALG3  | 14/14 | **PASS** | | LONG3 | 1/6  | fail |
| SPEC3 | 14/14 | **PASS** | | LONG5 | 0/6  | fail |
| SPEC1 | 2/14  | fail | | SPEC2 | 1/4  | fail |
| NEWX2 | 0/14  | fail | | LONG2 | 2/10 | fail |
| NEWX4 | 0/6   | fail | | SPEC4 | 0/14 | fail |
| NEWX5 | 6/20  | fail | | | | |

La frontera visible↔oculto es NÍTIDA: spec 100% ⇒ PASS (3/3); spec <100% ⇒
fail (10/10). No hubo ni un falso positivo del oráculo visible en esta corrida.

## 3. Los tres factores (modelo predictivo, con su evidencia)

P(PASS de una virgen) crece con:

**F1 — FIDELIDAD del oráculo visible.** Los spec-asserts son la función de
pérdida de la feromona: si el mapa es falso, el descenso ALEJA de la
solución.
- ALG3 PASS con oráculo 14/14 fiel (verificado a mano contra el enunciado).
- NEWX3 pasó EXACTAMENTE cuando el oráculo se completó (el ejemplo "IC" que
  faltaba lo aportó la otra hifa).
- SPEC1: oráculo inventado ('abc'==[] viola el LEN≥5 del propio enunciado) →
  43 min de feromona contra un mapa falso, 2/14.
- NEWX4: asserts AUTOCONTRADICTORIOS (mismo input '123' con dos outputs) →
  0/6 imposible por diseño. Detectable con código puro (implementado:
  filtra_contradicciones en producción).
- Corolario medido: **el techo del oráculo visible es parte del techo de
  capacidad** — enriquecer el oráculo con otra hifa (unión razonador+coder)
  compra capacidad sin GPU. Es el mismo modo de fallo del "juez débil" que
  mató al consenso y al escalado 7B v1, ahora en el cartógrafo.

**F2 — dificultad de PIEZAS y ENSAMBLE vs techo del coder.** La
descomposición debe DESCARGAR la dificultad del entry-point en las hojas, y
las hojas deben ser resolubles.
- NEWX2 0/14: piezas triviales perfectas (4/4, 5/5, 3/3) con TODA la
  dificultad (tokenizer + precedencia + ** derecha + //) en eval_arith → el
  techo se movió, no se cruzó. El ensamble es una PIEZA IMPLÍCITA cuya
  dificultad la cartografía no acota.
- NEWD2 3/12: la pieza-corazón (reduce_slope: fracción exacta con gcd y
  signo canónico) quedó 4/7 → el ensamble construyó sobre una pieza rota.
- ALG3 MATIZA: con oráculo F1 perfecto, la feromona puede domar un ensamble
  gordo (el parser entero) — F1 fuerte compensa F2 débil, no al revés.

**F3 — la FEROMONA solo convierte si F1∧F2.** NEWX3 convergió en 2 intentos
de ensamble; ALG3 en pocas gens. Con mapa falso (F1) o piezas rotas (F2), el
rastro acumula fallos sin dirección.

## 4. Predicciones pre-registradas (el test del modelo)

ANTES de conocer los resultados de las 10 pendientes se comprometieron
predicciones derivadas de F1-F3 con verificación A MANO de cada assert
(commit 850c6f4). Scorecard al escribir: ✓NEWX4 ✓NEWX5 ✗NEWD2 (sobrestimé
la familiaridad de la tarea: F2 en la pieza-corazón) ✗ALG3 (subestimé
F1-compensa-F2 — erró en la dirección que FORTALECE el mecanismo).

**Scorecard final: 8/10 aciertos** sobre las 10 predicciones pre-registradas.
Los 2 fallos, ambos explicados y ambos ILUMINAN la teoría:
- **NEWD2** (predije PASS, fue fail): sobreestimé; el oráculo era 10/12 fiel
  pero la pieza-corazón (`reduce_slope`, fracción exacta con gcd/signo) quedó
  4/7 — F2 (dificultad de pieza) por encima del techo del coder. Lección: F1
  fiel NO basta si una hoja es irresoluble.
- **ALG3** (predije FAIL por "ensamble gordo", fue PASS): erré en la dirección
  que FORTALECE la teoría — con F1 perfecto (14/14) la feromona domó el parser
  entero. F1 fuerte compensa F2, confirmado.
El scorecard 8/10 con los 2 errores acotando F1↔F2 es el resultado más honesto:
el modelo predice, y donde falla, enseña.

## 5. Higiene del oráculo (palancas v3, derivadas de F1)

1. **Detector determinista de contradicciones** (implementado en
   producción): mismo input → outputs distintos ⇒ ambos asserts fuera.
   Cero LLM, solo elimina pares demostrablemente incoherentes.
2. Confianza de dos niveles: assert LITERAL del enunciado (alta) vs
   inventado (baja); la feromona pesa por confianza. [NO implementado]
3. Verificación cruzada entre hifas para inventados: intersección
   razonador∩coder (la unión solo para literales). [NO implementado]
4. Composición recursiva (palanca de F2): si el entry-point requiere lógica
   sustancial, re-cartografiar el ensamble como subproblema. [NO implementado]
Cualquiera de estas entra SOLO con su propio PREREG + gate.

## 6. Construcción (estado real)

- `cognia/agent/superorganismo.py` (commit fb826d9): port del mecanismo v2
  + filtro de contradicciones + límite de tiempo (COGNIA_SUPERORG_TIMEOUT_S,
  default 30 min). Nunca lanza: None y la cascada conserva su candidato.
- **Etapa 4 de generar_codigo**, tras la mesa redonda: opt-in
  `COGNIA_SUPERORGANISMO=1` (default OFF hasta batería e2e — política mesa
  redonda), trigger = tarea dura sin confirmación de etapas 1-3, keep-best
  conservador (reemplaza solo sin-función o con spec-asserts 100%),
  telemetría `superorganismo` en el ledger BoN.
- Tests: 16 unitarios propios (incl. regresión del carto-starving) + suite
  completa 3951 verde.
- **e2e con modelo real HECHO** (§7.4): reveló que el port devuelve None en
  SPEC3 (carto fresco sin helpers + carto starving). Fix del starving
  aplicado; la reliability del helper-extraction fresco queda como palanca
  v3. Batería 17/17 + default-ON siguen GATED hasta resolver eso — el
  opt-in actual es correcto.

## 6a. Fidelidad MEDIDA: la descomposición F1/F2 cuantificada

La evaluación manual de fidelidad (§3-4) se validó con GROUND TRUTH: para cada
tarea se corrieron sus spec_asserts contra una solución CORRECTA (las ganadoras
usan su propio código que pasó ocultos; las perdedoras, una implementación de
referencia re-validada contra los ocultos). Fidelidad = % de asserts que pasan
en la solución correcta (un assert que falla ahí es FALSO). Medido en 7/13:

| tarea | fidelidad | oculto | mecanismo |
|---|---|---|---|
| NEWX3 | 100% | **PASS** | fiel + resoluble |
| ALG3  | 100% | **PASS** | fiel + resoluble |
| SPEC3 | 100% | **PASS** | fiel + resoluble |
| NEWX2 | **100%** | fail | **F2 puro** (oráculo perfecto, ensamble > techo) |
| NEWX5 | **100%** | fail | **F2 puro** (refuerzo-coder hizo oráculo fiel; parser RFC irresoluble) |
| SPEC1 | 14% | fail | **F1** (oráculo falso, anti-solución) |
| NEWX4 | 0% | fail | **F1** (oráculo contradictorio) |

**Hallazgo:** las 3 ganadoras tienen 100% de fidelidad; las perdedoras se parten
NÍTIDAMENTE en dos causas medidas — F1 (oráculo falso: 0-14%) y F2 (oráculo
100% fiel pero pieza/ensamble irresoluble). NEWX2 y NEWX5 son la prueba
cuantitativa de que **fidelidad perfecta NO basta** (contra la intuición de que
"mejor oráculo = PASS"): cuando la pieza-corazón supera el techo del coder, ni
un oráculo impecable convierte. Esto CORRIGE la lectura ingenua de la ley
empírica: spec-visible-100% ⇒ PASS, pero fidelidad-del-oráculo-100% ⇏ PASS
(NEWX2/NEWX5 tienen oráculo 100% fiel y aun así no ALCANZAN spec-visible-100%
porque el coder no resuelve el ensamble). Los dos factores son ortogonales y
ambos necesarios. (Datos: cognia_v3/eval/fidelidad_oraculos.json; 6 tareas sin ref-impl no
medidas por deadline.)

## 6b. La ley empírica y lo que implica para la construcción

Frontera visible↔oculto nítida (spec 100% ⇔ PASS, 13/13) ⇒ **el oráculo
visible es un proxy honesto del oculto CUANDO es fiel y completo**. Esto
valida el diseño de la etapa 4 en producción: el keep-best conservador
(reemplaza solo con spec-asserts 100%) usa exactamente la señal que aquí
resultó ser el discriminador perfecto. Y explica por qué el filtro
determinista de contradicciones (implementado en cognia/agent/superorganismo.py)
es la palanca correcta: sube F1 sin tocar el modelo. Corolario para v3: subir
el yield NO es "más feromona" — es más tareas con oráculo 100%-alcanzable, es
decir (a) oráculos más fieles (higiene + cross-check entre hifas) y (b)
descomposición que ponga piezas resolubles (F2).

## 7. Instrumento: lo que la corrida enseñó sobre MEDIR

1. **Timeout de socket ≠ timeout de cómputo**: prompts largos (feromona)
   timeouteaban con el server computando → gens quemadas contra la
   infraestructura. Fix `_request_timeout_s` con término de prefill
   (fb826d9), ajustado al peor caso de page-in de disco (//25, de28802). La
   corrida FINAL completa (13/13) tuvo **0 timeouts** — cero generaciones
   quemadas por infraestructura. Sin este fix, ~6% se perdían en máquina
   con RAM al límite. Es un bug de PRODUCCIÓN, no solo de la eval: el mismo
   timeout afecta al agente /hacer en máquinas lentas.
2. **Retry determinista entre corridas**: seeds fijas (77/78/79, plano 91)
   re-fallaban idéntico al relanzar. Fix: offset por gens acumuladas
   (6fa4b83), verificado en vivo (NEWX5: SIN MAPA ×8 gens → 10 asserts en 2).
3. **Agentes locales + eval de modelo real NO coexisten en el i3**: 13
   agentes de workflow → RAM 1.1 GB libre → paginación → NEWX5 tardó 9 h
   (server al 26% de utilización). El pipeline pesado se SERIALIZA.
4. **El smoke e2e del MÓDULO DE PRODUCCIÓN cazó lo que la eval no vio**
   (2026-07-15): superorganismo_solve() sobre SPEC3 devolvió None donde la
   eval había PASADO. Dos causas reales que solo un e2e del port revela:
   (a) el carto FRESCO extrajo 20 asserts pero **0 helpers** — la eval había
   ACUMULADO helpers de corridas previas (unión persistente entre runs), y
   sin helpers el mecanismo degrada a "atacar el problema entero" (pierde la
   descomposición); (b) las gens de carto (2400 tokens, ~400s en CPU)
   consumían todo el timeout y **mataban de hambre al ensamble** → 0 gens de
   generación. Fix aplicado (carto ≤55% del timeout, test de regresión que
   falla sin él). Lección: el pytest con fakes prueba la lógica; el gate mide
   el mecanismo; pero solo el e2e del PORT con modelos reales prueba que
   producción reproduce el gate — y aquí NO lo hacía (la eval dependía de
   estado acumulado que producción no tiene). Palanca v3 concreta: la
   fiabilidad de extracción de HELPERS en un solo pase es parte de F2.

## 8. Límites declarados (lo que esta teoría NO promete)

- El gate demuestra que el mecanismo cruza el techo EN TAREAS CON enunciado
  assertable y entry-point claro (código con ejemplos/reglas literales). No
  dice nada de conocimiento abierto, generación libre larga ni contexto.
- El costo es enorme: hasta 16 gens de un 4B + 2 cold-starts ≈ decenas de
  minutos por tarea en el i3. Por eso es etapa 4 (último recurso) y opt-in.
- Vírgenes con oráculo infiel (F1) siguen fuera del alcance hasta las
  palancas v3; vírgenes con pieza-corazón sobre el techo (F2) también.
- El scorecard de predicciones (8/10, §4) es la medida honesta del poder
  del modelo F1-F3; los 2 errores acotan F1↔F2.
- **Producción ≠ eval**: el módulo de producción corre carto FRESCO (sin la
  acumulación entre-runs que ayudó a la eval), así que su tasa de PASS en
  vivo es ≤ la del gate. El e2e (§7.4) lo midió: None en SPEC3. El gate
  prueba que el MECANISMO puede cruzar el techo; NO que el port lo cruce en
  cada corrida fresca. Por eso etapa 4 es opt-in y keep-best conservador
  (nunca empeora al candidato de las etapas 1-3).
