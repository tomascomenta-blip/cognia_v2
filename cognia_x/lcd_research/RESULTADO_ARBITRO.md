# Árbitro AI-nativo de LCD — atribución por etapa (plan 12, Fase 1/3)

**Fecha:** 2026-07-05 · **run:** `eval_attribution(SPECS)` en `cognia_x/lcd/arbiter.py` · CPU, cero-LLM.

## Qué es
El aporte de investigación del paper (§4.2): dado un fallo end-to-end en un
pipeline heterogéneo, **atribuir la falla a la etapa culpable** y re-ejecutar
solo esa. Aquí instanciado para el pipeline LCD (`descripción → plan → geometría
→ render`) con la misma estrategia que ganó en AG-ARB: **verificación por etapa
con oráculos ejecutables cero-LLM, en cascada** — la primera etapa que viola su
contrato es la culpable. NO un crítico-VLM (que en AG-ARB dio 31% con sesgo de
"culpar al artefacto terminal").

Contratos en cascada:
1. **plan** — ¿la escena tiene TODOS los objetos que pidió la descripción?
   (oráculo: el parser de la descripción vs los nombres en la escena)
2. **geometría** — ¿las POSICIONES satisfacen la relación pedida y están en
   canvas? (distingue de plan: los objetos SÍ están, lo que falla es dónde — es
   el "render de control" del paper hecho con código)
3. **render** — ¿el PNG existe y no está degenerado?

## Resultado (números reales, ground-truth por fallos inyectados)

Sobre 8 specs × 3 etapas = **24 fallos inyectados** (borrar un objeto = fallo de
plan; poner el sujeto en el centro de la referencia = fallo de geometría, viola
toda relación estricta sin sacar el objeto; render_ok=False = fallo de render):

| Métrica | Valor |
|---|---|
| **Atribución correcta** | **24/24 = 100%** |
| Distribución de culpas (anti-colapso) | plan 8, geometría 8, render 8 — **balanceada** |
| Confusión fuera de la diagonal | **0** (ninguna etapa mal atribuida) |

**Comparación honesta con AG-ARB:** el árbitro-LLM global medía 31.2% con sesgo
medido de culpar siempre al artefacto terminal (predecía `code` en 24-30/32,
nunca detectaba plan/design). Acá la cascada cero-LLM da 100% con **distribución
de culpas perfectamente balanceada** — que es exactamente la métrica de salud
que el plan original marcó como riesgo #1 ("el árbitro colapsa si culpa siempre
al mismo módulo"). No colapsa.

## Por qué el número es tan limpio (y qué NO demuestra)
- Es 100% porque las 3 etapas de este pipeline tienen **oráculo determinista
  ejecutable** (presencia de objetos, satisfacción de relación, existencia del
  PNG). Ese es justo el régimen donde la tesis del paper (verificación-por-etapa
  > crítico-LLM) es más fuerte, y AG-ARB ya lo había mostrado: 100% en las etapas
  CON oráculo (design/code) vs 31% del LLM.
- NO se afirma que resuelva la atribución donde NO hay oráculo (percepción pura,
  calidad estética del refinador neuronal) — ahí el VLM queda como fallback,
  declarado. El refinador (SD+ControlNet) está FUERA en CPU, así que la etapa
  `render→refinador` no se mide todavía.
- La inyección de fallos es el único ground-truth honesto (el mundo real no da la
  etiqueta de "qué etapa falló"); se declara como tal.

## Herramientas AI-nativas que salen de esto
- `atribuir_fallo` — sobre la escena activa, señala la etapa culpable (o "todos
  los contratos pasan"). Invocable por el agente vía ACCION.
- `reejecutar_etapa <plan|geometria|render>` — re-corre SOLO esa etapa (plan/
  geometría re-planifican desde la descripción; render re-renderiza), sin que el
  usuario reescriba nada. Verificado: tras corromper la escena (borrar un objeto)
  y `atribuir_fallo`→plan, `reejecutar_etapa plan` deja control 3/3 de nuevo.

## Frontera / próximo
1. planner-LLM (7/8 ya medido) como ruta por defecto de `escena_crear` en
   lenguaje natural (Fase 2).
2. verificación e2e REAL: `/hacer` con el modelo disparando escena_crear →
   atribuir_fallo → reejecutar_etapa (Fase, CP5).
3. cuando aparezca GPU: refinador y el contrato `render→refinador` (la etapa sin
   oráculo determinista, donde entra el VLM-fallback).
