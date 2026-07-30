# PREREG — Cabecera nueva: el banco DURO se saturó, hace falta terreno que discrimine

**Fecha:** 2026-07-30 ~06:35. **Escrito ANTES de redactar las tareas.**

## El dato que lo motiva (medido hoy, no supuesto)

Sobre las 64 muestras del goal (2 corridas, juez triple):

| | |
|---|---|
| pass@1 por muestra | **92%** (59/64) — META registraba 83% |
| tareas al 100% | **5 de 8** (descuento, form_cruzado, temporizador, tres_en_raya, undo_redo) |
| única que discrimina | tabla_compuesta 62% |
| techo pass@4 | 8/8 en las dos corridas |

**El banco duro ya no mide progreso.** Es el mismo diagnóstico que META
hizo del banco de 6 tareas ("está SATURADO, no sirve para medir avance") y
la misma consecuencia: **sin cabecera no hay progreso medible**. El 8/8 del
goal sigue siendo válido y replicado, pero hay que decir en voz alta que
mide un banco que el sistema actual ya domina.

## Qué se construye

**5 tareas nuevas** en `b1_tareas_cabecera.json`, con contrato a mano cada
una. El principio de dificultad no es la longitud sino la **interacción
entre mecánicas**: en el banco duro las reglas se componen (3-5 requisitos);
aquí las reglas **se afectan entre sí**, de modo que implementar cada una
por separado no basta.

Candidatas (enunciado preciso con selectores obligatorios, verificable por
ejecución):

1. **editor_undo_buscar** — textarea + buscar/reemplazar-todo + undo/redo:
   el undo debe deshacer un reemplazo masivo como UNA acción.
2. **carrito_cupones** — stock + cupón porcentual + envío gratis por
   umbral, donde el umbral se evalúa sobre el subtotal YA descontado (las
   tres reglas se afectan).
3. **calendario_conflictos** — eventos con inicio/fin que se rechazan si
   solapan, y mover un evento REVALIDA los conflictos.
4. **parser_parentesis** — precedencia + paréntesis anidados + unario
   negativo (más duro que `precedencia`, que no tiene paréntesis).
5. **ascensor** — cola de peticiones servida por dirección (tipo SCAN), no
   FIFO: el orden de servicio depende del sentido actual.

## Criterio de aceptación del banco (PRE-REGISTRADO, y esto es lo que
impide hacer trampa)

Cada tarea se mide con **n=4 muestras del sistema** (mismo modo que el
goal) y entra al banco según su pass@1:

| pass@1 de la tarea | decisión |
|---|---|
| **1/4 – 3/4 (25-75%)** | **ENTRA**: discrimina, que es para lo que existe |
| 4/4 | SATURADA: no entra como está; se anota y, si se endurece, se re-mide y se declara la versión |
| 0/4 | fuera de alcance por ahora: se anota y NO se usa para medir progreso hasta saber si es techo real o enunciado ambiguo |

- **El banco se calibra ANTES de usarlo para medir nada.** Ajustar tareas
  después de ver cómo le va al sistema en una medición de progreso sería
  fabricar el resultado; ajustarlas ahora, contra un criterio escrito
  antes, es calibrar el instrumento.
- Objetivo declarado: **≥3 tareas en la banda que discrimina**. Con menos,
  la cabecera no sirve y se dice.
- Contratos a mano con la regla de siempre: cada check crítico es
  consecuencia lógica del enunciado sobre selectores que el enunciado
  declara obligatorios; nada de valores que el enunciado no fija.

## Presupuesto

Redacción de tareas y contratos ~1.5 h (sin GPU). Calibración: 5 tareas ×
4 muestras ≈ 50-70 min de GPU. Cierre estimado ~10:00, con el aterrizaje a
las 12:14.

## Lo que NO se hace aquí

No se re-mide el goal contra el banco nuevo en esta sesión: primero hay que
saber si el banco discrimina. Un "MODO x/5" sobre un banco sin calibrar no
significaría nada.
