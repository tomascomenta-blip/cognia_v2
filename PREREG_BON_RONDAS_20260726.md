# PRE-REGISTRO — Best-of-N verificado en el lazo + rondas que rematan

**Escrito el 2026-07-26 a las 13:1x, ANTES de implementar y de correr nada.**
Existe para que los umbrales no se elijan después de ver los resultados
(mismo espíritu que PREREG_FP_CONTRATO_20260725.md).

## Contexto medido que motiva esto

- Serie b2 de la config final (runs 4-8): **3, 4, 5, 5, 4 / 6** (media 4.2,
  mínimo 3) contra baseline 2/6. Falta la réplica 6 (run9, en curso al
  escribir esto; su número se suma a la serie ANTES de cualquier comparación).
- Las tareas que fallan ROTAN entre corridas (memoria_4x4 10/10 en run8 y
  falla en otras): el cuello es la VARIANZA de la generación inicial.
- Los fallos quedan a 1-2 checks del pase (contador 9/14, calculadora 7/10 en
  run8) con el tope fijo de 3 rondas: la reparación progresa y se corta.

## Experimento A — Best-of-N verificado DENTRO del lazo

**Mecanismo:** hasta k=3 candidatos iniciales, generados SECUENCIALMENTE: el
juez ejecutable juzga el candidato 1; si aprueba, no se genera nada más (coste
0 extra en el caso bueno). Si falla, se genera y juzga el 2, luego el 3. Se
entra al lazo de reparación con el primer APROBADO o, si ninguno aprueba, con
el de más checks_ok. Sin contrato posible, BoN se desactiva solo (elegir sin
juez sería elegir por opinión).

**Medición:** b2 completo (6 tareas), n≥3 réplicas, config idéntica a la final
salvo `--candidatos 3`. Se mide pass/6 por corrida Y segundos por tarea (cada
candidato extra son ~60-90 s de GPU; el coste se reporta junto al pass).

**Criterio (decidido AHORA):**

| veredicto | condición |
|---|---|
| **PASA** | media ≥ 5/6 en n≥3 réplicas y ninguna corrida < 4/6 |
| **GRIS** | media en [4.5, 5) — mejora real pero no cierra el gate; se combina con reparación |
| **KILL** | media ≤ la media de la serie config-final (con run9 incluido), o coste medio > 2× sin subir la media |

## Experimento B — rondas de reparación que rematan (A/B contra tope fijo)

**Mecanismo:** el tope de rondas sigue en 3, pero si checks_ok del juez CRECIÓ
estrictamente entre la ronda anterior y esta (progreso real, no espiral), se
permite seguir hasta 5. El disyuntor sigue rigiendo: síntoma idéntico dos
veces corta igual que hoy.

**Medición:** b2 completo, n≥3 réplicas, config final + `--rondas-progreso 5`
(sin BoN, para no confundir atribución).

**Criterio (decidido AHORA):**

| veredicto | condición |
|---|---|
| **PASA** | media > media de la serie config-final (run9 incluido) y mínimo ≥ 4/6 |
| **GRIS** | media mejora pero mínimo < 4 — ayuda pero no estabiliza |
| **KILL** | media ≤ la de la serie config-final |

## Caveats declarados antes de correr (revisión adversarial 2026-07-26)

- **El contrato queda anclado al DOM del candidato en cuyo turno se generó**
  (normalmente el 1º): los candidatos siguientes se juzgan contra selectores
  que pueden no usar. Mitigado porque las 6 tareas de b2 fijan los selectores
  como OBLIGATORIOS en el enunciado; sigue siendo un sesgo conocido a favor
  del candidato que fabricó el contrato. Si BoN da GRIS/KILL, esta es la
  primera causa a inspeccionar antes de descartar la vía.
- **El APROBADO del BoN corta el lazo sin re-juzgar** (post-revisión): el
  caso bueno paga 0 extra de verdad. El juez externo de b2 sigue siendo el
  árbitro final del pass/6, así que un falso APROBADO interno no infla el
  número reportado.
- El reintento de contrato se paga sobre el MISMO candidato 1 (no cuesta una
  generación); si ambos intentos fallan, el lazo corre sin juez — igual que
  hoy — y la corrida queda contada en la telemetría de sellos.

## Qué NO decide esto

- A y B se miden POR SEPARADO. Si ambos dan señal, una corrida combinada es
  exploratoria (se reporta como tal, no como confirmación).
- n=3 por brazo es poco contra la varianza conocida del gate (~50% flaky);
  un GRIS aquí significa "más réplicas", no "adoptar".
- La tasa de "sin verificar" (contador nuevo de telemetría) se REPORTA sobre
  las corridas de esta noche; no tiene umbral pre-registrado — es la primera
  medición.
