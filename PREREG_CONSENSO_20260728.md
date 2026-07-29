# PREREG — Consenso conductual cruzado: ¿el contrato ciego sirve como RANKER aunque sea ruido como JUEZ?

**Fecha:** 2026-07-28 ~23:00, nocturna 28→29. **Escrito ANTES de implementar
o correr.** Es el primer experimento del "marco nuevo" que exigen los cuatro
KILL del contrato autogenerado (contrato-interno-al-azar) y la conclusión de
inversión del BoN (bon-con-senal-real: el cuello es FABRICAR SEÑAL).

## Hipótesis (mecanismo pre-declarado)

El contrato ciego generado desde idea+inventario inventa expectativas que
condenan páginas SANAS (FN 74-79% con tres pensadores). Pero si esas
invenciones son mayormente propiedades del PAR (idea, estilo del pensador) y
no de la muestra concreta, condenan a las K muestras de un mismo ensayo POR
IGUAL → como veredicto absoluto son ruido, pero como RANKING intra-ensayo el
offset constante se cancela y los bugs reales (que sí difieren por muestra)
quedan expuestos. Si además el contrato se genera desde el DOM de OTRA
muestra, sus aserciones no están contaminadas por las idiosincrasias de la
muestra evaluada. Riesgo pre-declarado en contra: los selectores
incidentales del DOM de origen (más allá de los obligatorios) pueden fallar
en las demás muestras por pura idiosincrasia y ahogar la señal — este
experimento mide exactamente eso.

## Diseño (todo sobre datos CONGELADOS de esta noche; cero páginas nuevas)

- Corpus: los 24 ensayos × 4 muestras del BoN (b2_bon_heldout, commit
  3a7186d), con `estricto` ya calculado por muestra (original ∧ held-out).
- **Generador de contratos: qwen2.5-coder-14b** (emisión 6/6 usable, 5-8 s;
  ya medido como juez absoluto: aciertos 10/24 — azar; esto NO es "probar
  un tercer modelo" sino cambiar el MARCO de uso del artefacto).
- Por cada muestra s del ensayo: generar UN contrato C_s (modo clasico, 2
  intentos como el runner real) desde idea + inventario del DOM de s.
- **Score de consenso de la muestra X** = sobre los contratos AJENOS C_s
  (s ≠ X, para no auto-examinarse): primero nº de contratos ajenos que la
  APRUEBAN, luego fracción media de checks superados (todos los checks del
  contrato, proxy: el juez no expone la criticidad por check), luego índice
  menor. Contratos no generados (None tras 2 intentos) simplemente no votan;
  si en un ensayo hay <2 contratos ajenos generados para alguna muestra, el
  ensayo se reporta aparte (sin voto suficiente) y sale del apareado.
- **Selector-consenso elige el argmax**; su resultado = `estricto` guardado
  de la muestra elegida. Control = muestra s1 (el mismo del prereg BoN).

## Métricas y umbrales (24 ensayos objetivo; pares discordantes)

| lectura | condición | veredicto |
|---|---|---|
| B' (consenso vs control s1) | neto ≥ +5 | **MARCO VIVO**: hay selector de producción candidato sin contratos a mano |
| B' | +3..+4 | señal moderada: vale iterar el marco (no adopción aún) |
| B' | −2..+2 | KILL de esta variante del marco |
| B' | ≤ −3 | el consenso ELIGE MAL activamente (peor que tomar la primera) |

- Secundarias (se reportan, no deciden): B' − A (cuánto del techo +7
  captura); % de ensayos donde el consenso coincide con el selector
  held-out; distribución de votos (¿los contratos ajenos aprueban algo o
  condenan todo — el offset constante existe?).
- Deriva: no aplica a las muestras (congeladas). La generación de contratos
  ocurre toda esta noche, intercalada por ensayo (los 4 contratos de un
  ensayo se generan consecutivos).
- Infra: contrato None no vota (ya cubierto); juzgado de C_s sobre X que
  crashea = ese voto se omite y se cuenta (si deja <2 votos, fuera del
  apareado, reportado).
- Presupuesto: ~96 gens × ~8 s ≈ 15 min (coder) + ~288 juzgados × ~12 s ≈
  1-1.5 h de Playwright. Guardado incremental + --reanudar.
- Este prereg NO adopta nada en producción: decide si el marco merece el
  cableado (próxima sesión) o muere como las otras vías.

## PRIMERA ENMIENDA (2026-07-28 ~23:25, tras la revisión adversarial y ANTES de correr)

1. **El voto decisorio es SOLO por checks DEL CONTRATO** (aprueba_contrato =
   todos los checks del contrato pasan; fracción = c_ok/c_n). Hallazgo #1
   del revisor: juzgar_web antepone checks universales (carga, contenido…)
   que son la MISMA batería que fabricó `estricto` — dejarlos votar
   compartiría el instrumento con el juez del outcome y un MARCO VIVO sería
   ininterpretable. `aprueba` (con universales) se guarda solo como
   secundaria.
2. Correcciones de registro: la config no se pisa al reanudar (procedencia);
   el resumen reporta votos crasheados, hechos/esperados y flag `parcial`;
   el denominador de la secundaria "¿condenan todo?" excluye crasheos.
3. Fe de erratas del prereg: el corpus congelado registra commit c13df07
   (58a9cba+c13df07 en config), no 3a7186d (ese es el commit que LO
   commiteó); y son 22 ensayos × 4 + 2 × 3 muestras (94 con HTML: las 2
   sin-HTML del BoN) → 276 juzgados esperados, no 288. El código maneja
   ambos casos (control s1 existe en los 24).
4. Declarado: un voto crasheado no se reintenta en --reanudar (se cuenta y
   audita; si deja a una muestra con <2 votos, el ensayo sale del apareado
   y se reporta en sin_voto).

## RESULTADO (2026-07-29 ~00:45 — corrida completa, 255/255 votos, 0 crasheos)

**Neto B' = +2 (23 ensayos, 1 sin voto) → KILL de esta variante** por el
umbral pre-fijado ([−2,+2]). Control s1: 16/23; selector-consenso: 18/23.

Observaciones secundarias (se reportan, no deciden):
- **Asimetría 2-0:** el consenso rescató 2 ensayos (carrito r1, hoja r3) y
  no eligió peor que el control en NINGUNO. No es un selector dañino; es
  uno débil.
- **El offset pre-declarado existe y es severo:** solo 39/255 votos por
  contrato aprueban (15%) — los contratos ajenos condenan casi todo, así
  que el primer criterio (votos que aprueban) apenas discrimina y el
  ranking cae sobre la fracción de checks.
- Coincide con el selector held-out solo 6/23 — elige distinto y aun así
  acierta 18/23 (la mayoría de muestras son buenas; el mérito real se mide
  en los discordantes, y ahí está el 2-0).
- Iteración imaginable para OTRA sesión (no esta noche, no adoptar nada:
  el umbral habló): votar solo con checks sobre selectores OBLIGATORIOS
  del enunciado (menos idiosincrasia del DOM ajeno), o mayoría-de-fracción
  en vez de todos-pasan. Queda anotado en el backlog, con este KILL como
  baseline.
