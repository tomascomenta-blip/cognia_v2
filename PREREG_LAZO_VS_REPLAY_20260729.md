# PREREG — ¿El REPLAY representa al LAZO? (validez del instrumento de las sondas)

**Fecha:** 2026-07-29 ~18:30, sesión tarde-noche 29. **Escrito ANTES de
implementar el runner y ANTES de correr.** Nace de una contradicción
MEDIDA esta tarde, no de una idea:

| medición (misma tarde, mismo banco, mismo juez estricto) | tasa |
|---|---|
| LAZO con troceo (fase 3, n=24) | 79% |
| LAZO con troceo (etapa A, n=12) | **92%** |
| REPLAY del prompt del lazo (etapa B, n=12) | **42%** |
| REPLAY del prompt del lazo (fase 1 y fase 2, n=24 c/u) | 46%, 46% |

El replay rinde 42-46% en TRES corridas independientes; el lazo, con el
MISMO prompt (capturado de esa misma celda), 79-92%. Si esa brecha es
real, **el replay no es un sustituto del lazo** y toda conclusión de
NIVEL medida por replay queda acotada (los netos apareados intra-corrida
siguen válidos: sus brazos comparten instrumento).

## Diferencias candidatas (enumeradas y medibles, no especuladas)

1. **PARSEO.** El lazo usa `_parse_response(raw, category, "html")` real:
   elige el mejor bloque, corta `<think>`, **rechaza truncados** y exige
   `<html`. Las sondas usan `_parsear`, que por una firma incorrecta
   heredada (`TypeError`, documentado) SIEMPRE cae al fallback de fence
   `crudo.split("```")[1]`. Medido ya: 2/105 crudos truncados (los dos en
   replay, ambos fallidos) — el truncamiento explica poco, pero la
   elección de bloque está sin medir.
2. **FALLBACK del flujo.** Si el lazo no entrega HTML, `correr_sistema`
   cae a `create_program` (idea pelada). Medido en etapa A: 4/24 celdas,
   4/4 aprobadas.
3. **Varianza de generación.** temp 0.2 no es 0; fase 1 midió concordancia
   replay↔gate 12/23 (el mismo prompt cambia de destino la mitad de las
   veces).
4. Descartadas por lectura de código: `generate_program` NO reintenta;
   system/temperature/max_tokens/effort idénticos; con `max_rondas=1` no
   hay reparación.

## Diseño (apareado PERFECTO: mismo prompt, misma corrida, mismo minuto)

Por cada (tarea, réplica), en este orden y dentro de la misma celda:

1. **LAZO**: `b2_sistema_real.correr_sistema(idea, dir)` con
   `COGNIA_DUMP_PROMPTS` apuntando a un directorio POR CELDA (así el
   prompt capturado es inequívocamente el de ESTA celda). Se registra si
   entregó por lazo o por fallback.
2. **REPLAY** inmediato de ESE prompt (el que contiene `REQUIRED
   component`; si la celda cayó al fallback hay 2 dumps y se toma el del
   lazo): `llm_local.generar` con los args exactos del lazo
   (system=_SISTEMA_WEB, temp del dump, max_tokens 12000, effort None).
   Del MISMO crudo se derivan **DOS páginas**:
   - `replay_real` = `_parse_response(crudo, tarea, "html")` (el parseo
     del lazo). Si rechaza → cuenta como reprobado (el lazo regeneraría;
     esa ventaja del flujo se mide aparte en la secundaria de fallback).
   - `replay_fence` = el `_parsear` de las sondas.
3. Los tres productos se juzgan con **juez estricto** (contrato original ∧
   held-out), cada juzgado bajo presupuesto de pared propio (300 s;
   lección juez-colgado-js-bloqueante).

n = 6 réplicas × 4 tareas = **24 pares**; 48 generaciones (24 lazo + 24
replay) y hasta 72 juzgados. Intercalado no aplica (ambos brazos comparten
la misma celda y el mismo minuto: el apareado es perfecto por
construcción). Infra: EXCEPCIÓN, juez crasheado, backend degradado/≠8080
→ par fuera; "sin HTML" del replay con server sano = reprobado legítimo.

## Métricas y umbrales (fijados ahora)

**Primaria — neto (LAZO − replay_real)** sobre pares válidos:

| neto | veredicto pre-fijado |
|---|---|
| ≥ +4 | **EL FLUJO APORTA**: el replay NO representa al lazo. Consecuencias declaradas: (a) las conclusiones de NIVEL por replay quedan acotadas a "nivel replay"; (b) la tesis histórica "el envoltorio roba" se re-abre y debe re-medirse con parseo homogéneo; (c) los netos apareados de fases 1-2 siguen válidos como comparaciones intra-instrumento |
| −1..+3 | el flujo aporta poco: la brecha 92-vs-42 era comparación entre corridas distintas; el replay se mantiene como instrumento con su caveat |
| ≤ −2 | el flujo ROBA (la tesis histórica del gap), ahora con apareado perfecto |

**Secundaria decisiva — neto (replay_real − replay_fence)**: el coste del
parseo de las sondas, medido sobre el MISMO crudo (cero generación extra).
≥ +2 ⇒ el parseo de `_parsear` deprime el brazo replay y hay que
corregirlo en los runners antes de cualquier sonda futura.

Otras secundarias: nº de celdas por fallback y su outcome; truncados por
brazo; concordancia lazo↔replay por celda; tiempos.

Reglas heredadas: <12 pares válidos = direccional; si primaria y
secundaria por contrato original caen en ramas distintas → gris.

## Presupuesto y logística

48 generaciones (~60-120 s) + hasta 72 juzgados (~12-25 s) ≈ **2.5-3.5 h**.
Lanzada ~19:15, cierre ~22:00-22:45 — holgado (aterrizaje 04:14). Guardado
incremental + `--reanudar`; desacoplada + vigías; slots=1/ctx/modelo
verificados al arrancar.

## Revisión

1 agente adversarial (diseño + implementación con verificaciones
ejecutadas) ANTES de encender; humo de 1 celda antes de la corrida
completa. Enmiendas con fecha aquí.

## RESULTADO (2026-07-29 ~22:10 — corrida completa, veredicto por umbrales pre-fijados)

**Neto (lazo − replay_real) = −1; co-primaria sin fallbacks = −1 → rama
"−1..+3": el flujo aporta poco. LA BRECHA 92-vs-42 ERA COMPARACIÓN ENTRE
CORRIDAS DISTINTAS. El replay queda VALIDADO como instrumento.** 24 pares,
0 infra.

- LAZO **14/24 (58%)** vs replay_real **15/24 (62%)**: indistinguibles
  (gana lazo 5, gana replay 6). El fallback del flujo apareció 3 veces (2
  aprobadas) y la co-primaria que lo excluye da el mismo −1: el flujo no
  compra nada medible por esa vía.
- **Secundaria del parseo: neto 0, cero pares discordantes, 0 rechazos del
  parse real** — confirma en vivo la medición offline (veredicto estricto
  idéntico en 107/107 crudos). La candidata #1 queda enterrada.
- **El número que se lleva la noche: concordancia lazo↔replay = 13/24
  (54%).** Con el MISMO prompt, el mismo modelo y temp 0.2, el destino de
  la celda cambia casi la mitad de las veces. Coincide con la
  concordancia replay↔gate de fase 1 (12/23). **El prompt fija la TASA,
  no el destino.**

**Consecuencia metodológica (la más importante, y me obliga a acotar mis
propias lecturas de hoy):** el LAZO midió 92% (etapa A, n=12), 79% (fase
3, n=24) y 58% (aquí, n=24) **en la misma tarde-noche, con el mismo
código**. Eso es ±34 pts de varianza entre corridas del mismo sistema.
- Lo que se SOSTIENE: todo neto APAREADO dentro de una corrida (fase 1
  −7, fase 2 +6, fase 3 −4, etapa B +1, este −1). El apareado es inmune a
  esta varianza; por eso el método lo exige desde hace semanas.
- Lo que queda FRÁGIL: cualquier lectura que compare NIVELES o NETOS entre
  corridas distintas. En particular, la conclusión "H-material" de
  PREREG_DISCREPANCIA_TROCEO (comparar +6 del gate contra +1 fresco) es
  una comparación entre corridas y hereda esta fragilidad: sigue siendo
  la mejor lectura disponible, pero **no está al nivel de evidencia de un
  neto apareado**, y así queda anotado allí.
- Regla operativa que sale de aquí: **una sola muestra por celda tiene
  ~54% de reproducibilidad**; ninguna decisión debe apoyarse en una celda,
  y las comparaciones entre corridas exigen control concurrente o no se
  hacen.

## PRIMERA ENMIENDA (2026-07-29 ~19:00 — tras la revisión, ANTES de correr)

**4 BLOQUEA aplicados** (todos verificados con mocks por el revisor):

1. Un juez crasheado en la pata REPLAY devolvía None y contaba como
   reprobado → engordaba la primaria en la dirección de la hipótesis.
   Ahora: crash o None en CUALQUIERA de los tres productos → par infra.
2. Una EXCEPCIÓN del LAZO se guardaba en `como_lazo` y `_es_infra` miraba
   `como` → el par contaba como victoria del replay. Corregido.
3. `--reanudar` sobre una celda cortada replayaba el prompt VIEJO (el dump
   se abre en modo append y `extra_hint` tiene 7 variantes): el dir de
   dump se limpia por celda.
4. La pata LAZO corría SIN presupuesto de pared, con Playwright y
   `page.evaluate` sin timeout dentro (la firma del cuelgue de 595 s), en
   corrida nocturna desatendida. Ahora va bajo `con_presupuesto`.

**Arreglos:** el replay usa el timeout REAL del lazo (120 s, no 400 — con
400 tendría una ventaja que el lazo no tiene, y el corte a 120 es
justamente lo que dispara su fallback) y el `system` del propio dump;
`parseos_iguales` compara con `strip`; `commits` acumulados.

**CO-PRIMARIA añadida (obligatoria):** el neto EXCLUYENDO las celdas que
el lazo resolvió por fallback (`create_program`, idea pelada). El fallback
es una SEGUNDA generación que el replay no tiene: declarar "el flujo
aporta" por tener dos tiros sería trampa. **Rige la MÁS CONSERVADORA de
las dos lecturas.**

**La secundaria del PARSEO queda CERRADA sin GPU** (medición offline sobre
los 107 crudos del repo, hecha antes de correr): los dos parseos producen
la misma página tras `strip` en 104/107 y **veredicto estricto idéntico en
todos**; el parse real rechaza 3 (2.8%, truncados con fence sin cerrar) que
el fence acepta como página incompleta. **La candidata #1 (parseo) queda
DESCARTADA como explicación de la brecha**; en la corrida se reporta como
telemetría, no como umbral. Quedan vivas: fallback del flujo y varianza de
generación.

**Presupuesto corregido:** 3.5-4.5 h (cada celda del lazo incluye contrato
interno + dos pasadas de Playwright; p95 ~6-7 min). Lanzada ~19:15 →
cierre ~23:00-23:45, dentro de la ventana.

**Declaración de diseño (N2):** el orden dentro de la celda es siempre
lazo→replay (no aleatorizado): el apareado es perfecto en PROMPT, no en
instante.
