# TEORÍA DE LA COLONIA v1 — cómo una flota de modelos chicos actúa como un modelo casi-grande

**2026-07-12, corrida COLONIA→CASI-GRANDE.** v0 salió de la investigación
(COLONIA_RESEARCH_CONSOLIDADO.md, 6 hilos con fuentes primarias); v1 es la
versión EJECUTADA: cada principio de abajo tiene su medición local en este
repo o su cita, y lo implementado esta corrida está marcado ✅.

## Principio rector (estigmergia)

**La colonia no delibera — ejecuta, mide y deja rastro.** La coordinación
por CONVERSACIÓN (debate, roles charlando, consenso) destruye valor con
modelos chicos: medido acá (mesa redonda 0/4 en fallas verdaderas) y en la
literatura (MAD colapsa 9.40→2.48 en código; sicofancia 85.5%). La
coordinación por ARTEFACTOS DETERMINISTAS (tests, tracebacks, scores,
tablas de ruteo) crea valor: cada eval deja "feromona" en el ledger
(results_*.json) y el ruteo del futuro la lee. La restricción del hardware
(1 generación a la vez en 2 cores) se vuelve principio de diseño: **una
sola voz genera; percepción, ruteo, verificación y memoria son baratos.**

## Anatomía (quién hace qué, con su evidencia)

1. **PERCEPCIÓN** — portero 0.5B (turnos triviales, 3.3-3.9× decode) +
   embedder 0.6B (representación para ruteo futuro). ✅ desplegado (portero
   7/7 gates 2026-07-10).

2. **RUTEO por eje, determinista y no-LLM** — léxico (identidad→accion) +
   dificultad (código fácil/duro) + **detector de razonamiento→qwen3_4b**
   ✅ (AUDIT 2026-07-12: G2R 92.5% vs 27.5 crudo / 82 andamiado del 3B,
   McNemar p≈0.0000; encima MÁS RÁPIDO por ítem: 20.4s vs 29.1s). AUD-1
   probó que el ruteo paga en ambos ejes (unión−mejor: +7.5pp G2R, +4pp
   G5). La especialización vive en los GENERADORES, no en el que decide.

3. **GENERACIÓN: un especialista por consulta** (principio Self-MoA:
   muestrear al MEJOR miembro para ese eje > mezclar miembros dispares).
   Perfil de skill medido (la feromona inicial):
   | miembro | razonamiento | español | código duro | costo |
   |---|---|---|---|---|
   | 3B Coder (agente) | 27.5 | 72 | 37.5 RAW / techo con BoN | ~8 tok/s |
   | qwen3_4b | **92.5** | 88 | — | 20.4 s/ítem |
   | qwen35_4b | 42.5 (no-think) | **92** (n.s.) | **42.5 RAW** | lento |
   | lfm25_12b | 75 | 72 | — | **8.1 s/ítem** |
   | vibethinker | 20 | 36 | — | nicho math únicamente |
   | 7B Coder | — | — | +8 recuperadas | lazy |

4. **VERIFICACIÓN: el órgano central, y es DETERMINISTA.** Jerarquía:
   (a) ejecución de tests = gold en código ✅; (b) keep-best ESTRICTO por
   score visible al comparar candidatos entre etapas ✅ (lección del juez
   débil del deploy 7B); (c) sin oráculo → no hay selección que valga
   (Self-MoA archivada por techo: el router ya captura la ganancia).
   Nunca juez-LLM, nunca consenso.

5. **ESCALADO: cascada de 3 etapas por CAPACIDAD** ✅ — 3B BoN → 7B greedy
   → **Qwen3.5-4B greedy no-think** (E1: 17/40 > 15/40 del 3B; 4 tareas
   SOLO-q35). Unión medida de la colonia en código duro: **27/40 (67.5%)
   vs 23/40 de la cascada 2-etapas** — por encima de la referencia GLM 5.2
   del eje (~50%). El miembro caro solo entra donde el barato ya falló.

6. **REPARACIÓN**: self-repair con traceback ya vive en el loop (repair
   dirigido); la mesa redonda multi-modelo queda opt-in (0/4 verdaderas).

7. **AGENTES: encima, no adentro.** El loop /hacer consume la colonia como
   servicio; sub-agentes solo por descomposición secuencial, jamás como
   interlocutores (single-agent > multi-agente conversacional, medido con
   modelos frontera; con ≤7B es peor).

8. **TURNO NOCTURNO**: lo caro corre en batch (audits del oráculo, futuras
   etiquetas de ruteo kNN con el embedder, re-calibración θ con la
   telemetría BoN — 192 registros ya acumulados). El día ejecuta; la noche
   re-mapea el territorio.

## El lazo de mejora sin GPU

ejecutar → medir con oráculos → appendear al ledger → re-calibrar ruteo →
rutear mejor mañana. La colonia aprende por ACUMULACIÓN DE MEDICIONES, no
por gradientes. Kaggle es excepción quirúrgica: adapters de FORMATO cuando
un gate lo justifica (patrón id4b: G3 0→100 en 13 min de GPU).

## Límites declarados (lo que la teoría NO promete)

- El techo de conocimiento abierto / generación libre larga / contexto
  >16k sigue siendo de CAPACIDAD CRUDA: ninguna orquestación de ≤7B lo
  compra (6 negativas de fine-tune + mesa 0/4 + literatura TTS: la cola
  dura no cede con más muestras).
- Los headlines "colonia > modelo grande" de la literatura viven en
  benchmarks LLM-judge (AlpacaEval-style); acá solo cuentan oráculos.
- La latencia es el impuesto de la colonia: cada etapa extra paga
  cold-start + decode. Por eso el ruteo es proactivo y el caro es lazy.

## Pendientes con plan (fase C)

- Router kNN semántico con qwen3_embed sobre el ledger (AUD-1 ya dio el
  gate; falta implementación + split held-out).
- θ-cascada con los 192 registros de telemetría (gana latencia, no pp).
- Español: re-medir qwen35 vs 3B con N mayor antes de mover el default.
- Fallback razonamiento: qwen3_4b → lfm25 (75% a 8 s/ítem) → 3B+stepwise.
