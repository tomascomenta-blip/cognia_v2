# PREREG — E-SUPERORGANISMO (la colonia muerde por pedazos, no ataca al oso entero)

**2026-07-13. Mandato del dueño**: reinventar el MoM para que su límite no sea
capacidad cruda — que la flota trabaje como UN organismo (lógica hormigas vs oso).

## Diagnóstico de por qué las 9 negativas no refutan esto

Todas las negativas previas (consenso, Self-MoA, mesa redonda, pass@16) comparten
la misma forma: **N intentos INDEPENDIENTES sobre el problema ENTERO + selección**.
Si el problema entero está sobre el techo del modelo, ninguna muestra lo cruza
(ALG3: 0/8 a temp 0.8) y la selección no tiene de dónde elegir. Las hormigas no
hacen eso: ninguna pelea contra el oso; cada una ejecuta una acción POR DEBAJO de
su capacidad individual, y coordinan por rastro en el entorno (estigmergia), no
por votación.

## Mecanismo bajo prueba (3 piezas nuevas, juntas)

1. **CARTOGRAFÍA** (qwen3_4b, el razonador 92.5): del SPEC deriva
   (a) descomposición en 2-4 funciones auxiliares con contrato explícito,
   (b) **SPEC-ASSERTS**: asserts extraídos de los ejemplos/reglas LITERALES del
   enunciado (p.ej. `calc("(1-8)/2") == -3` está EN el texto de ALG3). A
   diferencia de los inputs-distinguidores inventados que mataron al consenso,
   estos tienen ground truth en el propio enunciado.
2. **HORMIGAS POR PIEZA** (qwen35_4b): cada auxiliar se resuelve por separado
   contra sus micro-asserts (oráculo determinista POR PIEZA). Cada pieza está
   por debajo del techo individual.
3. **ENSAMBLE + FEROMONA**: la función principal se escribe USANDO los
   auxiliares verificados; corre contra los SPEC-ASSERTS; cada fallo deja
   rastro (tipo de error, assert que falló, enfoque usado) que el siguiente
   intento LEE como artefacto (no conversación) y debe evitar.

## Protocolo

- Set: las 13 vírgenes de AUTOPSIA_13 (no resueltas por la colonia 3 etapas =
  la unión 27/40). SMOKE primero: ALG3, SPEC2, NEWX3, LONG2 (4 categorías).
- Presupuesto: ≤16 generaciones/tarea (= presupuesto del pass@16 baseline).
- Baseline: pass@16 qwen35_4b temp 0.8 (results_passk_techo.json; ALG3 ya 0/8).
  Mismo modelo generador, mismo presupuesto → aísla el HARNESS.
- Score: SOLO tests ocultos de tasks_hard_v2.jsonl. Los ocultos jamás se
  muestran a ningún modelo.
- Gate de éxito (pre-registrado): ≥2/13 vírgenes resueltas → el mecanismo
  compra capacidad más allá del techo (el baseline es 0/13 por definición).
  1/13 = señal débil, extender N antes de afirmar. 0/13 = 10ª negativa, se
  declara y se archiva.
- Riesgo declarado: SPEC-ASSERTS incorrectos pueden bloquear una solución
  correcta (el mismo modo de fallo del juez débil). Mitigación: keep-best por
  #asserts pasados (nunca descarte binario), y el score final es SIEMPRE
  contra los ocultos.

## v2 (2026-07-13 22:50, tras autopsia del smoke v1)

Smoke v1: 0/4 en ocultos, pero la autopsia por-assert cambia el cuadro:
- **NEWX3 quedó a 1 assert de pasar (10/11 ocultos)**: el único fallo ("IC")
  está LITERAL en el enunciado y el cartógrafo no lo convirtió en spec-assert.
  Con oráculo visible completo, la feromona convergió en 1 intento.
- ALG3: helpers mutuamente recursivos no se pueden verificar aislados
  (1 assert c/u) → 0/5 ocultos.
- SPEC2: spec-asserts correctos pero formato-exacto nunca alcanzado (0/3).

Cambios v2 (pre-registrados ANTES de la corrida v2):
1. Cartógrafo OBLIGADO a convertir CADA ejemplo y CADA regla literal del
   enunciado en assert (6-14), y 3-5 asserts por helper.
2. Micro-asserts de pieza evaluados sobre el ACUMULADO de piezas (soporta
   recursión mutua).
3. Feromona con TODOS los asserts que fallan (no solo el primero).
Gate intacto: ≥2/13 vírgenes en OCULTOS. Presupuesto intacto (16 gens).
Salida: results_superorganismo_v2.json (v1 queda como archivo).
