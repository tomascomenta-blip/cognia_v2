# PREDICCIONES PRE-REGISTRADAS — corrida v2 continuación (2026-07-14 ~06:20)

Registradas ANTES de conocer el resultado de las 10 tareas pendientes (la eval
corre en background; al escribir esto ninguna de las 10 tiene "final" en
results_superorganismo_v2.json). Derivadas de la autopsia de las 3 medidas
(NEWX3 PASS, NEWX2 0/14, SPEC1 2/14) + verificación A MANO de cada spec-assert
contra su enunciado. Si aciertan, la teoría tiene poder predictivo.

## Modelo teórico (3 factores, de la autopsia)

P(PASS de una virgen) crece con:
1. **FIDELIDAD del oráculo visible** — asserts correctos vs inventados/falsos.
   SPEC1 murió por esto (43 min optimizando contra un mapa falso: 'abc'==[]
   viola LEN≥5 del propio enunciado). El mismo modo de fallo del juez débil.
2. **DELGADEZ del ensamble** — la descomposición debe DESCARGAR la dificultad
   en las hojas (piezas), no dejarla en el entry-point. NEWX2 murió por esto:
   piezas triviales perfectas (4/4, 5/5, 3/3) y TODA la dificultad (tokenizer
   + precedencia) en eval_arith → el techo se movió, no se cruzó.
3. **Convergencia de la feromona** — solo convierte si 1 y 2 se cumplen
   (NEWX3: oráculo fiel de 20 asserts unión razonador+coder + ensamble
   delgado → convergió en 2 intentos).

## Fidelidad verificada a mano (hallazgos por tarea)

- NEWX4: asserts casi todos FALSOS + AUTOCONTRADICTORIOS ('123' dos veces con
  resultados distintos: ['length','digit'] y ['sequence']). Ninguno sorted
  como exige el enunciado.
- LONG2: 9/10 FALSOS — la tortuga arranca mirando NORTE (+y) con pen UP; los
  asserts mueven en +x y marcan celdas con el pen levantado (anti-solución).
- SPEC4: MEZCLA contradictoria — asserts correctos (dedup por ID) conviven
  con falsos que NO dedupean el mismo patrón de input → tope visible ~8/14.
- LONG5: derivative(Polynomial([1,-2,3])).coeffs == [2,-1] es FALSO (correcto:
  [-2,6]); además llama derivative() como función global (es método) y nada
  cubre __str__ (el corazón del formato exacto).
- LONG3: 6 asserts fieles pero TRIVIALES (true/null/123/"hello"); cero
  cobertura de objetos/arrays/escapes/anidamiento → oráculo incompleto.
- ALG3: 14/14 FIELES (verificado trunc-toward-zero incluido). El riesgo es
  solo composición (parser = ensamble gordo; pass@16 histórico 0/8).
- NEWD2: 10/12 fieles; 2 FALSOS ([[1,0],[1,0],[2,1]] da 3, no 2 — duplicados
  cuentan en la línea; [[0,1],[2,2],[1,1]] da 2, no 3 — no son colineales).
- SPEC3: 14/14 FIELES (semver, reglas 3/4/5 verificadas). Sin cobertura de
  build-metadata '+' ni numeric-vs-alphanumeric.
- SPEC2 / NEWX5: en re-cartografía al escribir esto (tenían <4 asserts).
  SPEC2 v1: los 2 asserts eran falsos (format_table de 1 columna = 3 líneas,
  no 'a | 1').

## PREDICCIONES (comprometidas)

| tarea | predicción | razón dominante |
|---|---|---|
| NEWX4 | FAIL | oráculo inventado + contradictorio |
| NEWX5 | FAIL | ensamble gordo (parser RFC-4180) |
| NEWD2 | **PASS** | oráculo 10/12 fiel + tarea clásica + keep-best tolera los 2 falsos |
| ALG3  | FAIL | ensamble gordo (modo NEWX2), pese a oráculo fiel |
| LONG3 | FAIL | oráculo incompleto + ensamble gordo |
| LONG5 | FAIL | oráculo falso + __str__ sin cubrir |
| SPEC2 | FAIL | formato exacto jamás alcanzado (v1 0/3) |
| SPEC3 | **PASS** (confianza baja) | oráculo fiel 14/14 + dominio conocido |
| LONG2 | FAIL | oráculo 9/10 falso (anti-solución) |
| SPEC4 | FAIL | oráculo contradictorio (tope visible ~8/14) |

Predicción del gate: NEWX3 + NEWD2 (+SPEC3?) → **2-3/13 = GATE PASA** por
poco. Si NEWD2 y SPEC3 fallan ambas → 1/13, extender según PREREG.

## Implicación de construcción (registrada antes del resultado)

La palanca #1 de una v3 NO es más feromona: es **higiene del oráculo**:
(a) detector DETERMINISTA de contradicciones (mismo input → outputs
    incompatibles) — NEWX4 y SPEC4 son detectables con código puro, cero LLM;
(b) confianza de dos niveles: asserts LITERALES del enunciado (alta) vs
    inventados (baja); la feromona pesa por confianza y keep-best solo
    cuenta los de alta;
(c) verificación cruzada entre hifas para los inventados (intersección
    razonador∩coder, no unión — la unión solo para literales).
La palanca #2 es composición: si el entry-point requiere lógica sustancial,
re-cartografiar el ensamble como subproblema (descomposición recursiva).
