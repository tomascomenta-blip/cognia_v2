# REGLA — Autonomía Total del Manager hasta Deadline

> **Documento de gobernanza. CRÍTICO. Autorizado por el dueño (2026-06-24).** Define cómo opera el modo
> manager cuando el dueño da una hora límite. Es REGLA VINCULANTE: enlazada desde `CLAUDE.md`. No borrar;
> append-only para cambios de política.

---

## Regla principal (la que pidió el dueño)

**Cuando se active el modo manager con una HORA LÍMITE, el agente realiza mejoras INDEFINIDAS, de forma 100%
AUTÓNOMA, SIN PREGUNTAR ABSOLUTAMENTE NADA al usuario y SIN DETENERSE EN NINGÚN MOMENTO, hasta esa hora.**

Durante la corrida el usuario está **100% inactivo**. El agente asume control total y trabaja en bucle
continuo respecto al tiempo restante hasta el deadline, donde se programa un apagado.

---

## Activación

1. El dueño invoca `/manager` e indica una **HORA LÍMITE** (deadline), p.ej. `/manager continua hasta las 08:00`.
2. El agente registra el deadline en la sección **Config de la corrida** (abajo) y entra en **AUTONOMÍA TOTAL
   HASTA DEADLINE**.
3. Si el dueño NO da hora límite, aplica el modo manager normal (autónomo pero con checkpoints permitidos).
   Esta regla de "sin detenerse jamás" aplica SOLO cuando hay deadline explícito.

---

## Comportamiento obligatorio durante la corrida

- **CERO preguntas.** Prohibido usar `AskUserQuestion` o pedir confirmación/aclaración por cualquier medio.
  Ante toda bifurcación, **tomar siempre la mejor decisión** y seguir. El usuario no responderá.
- **CERO paradas.** Prohibido hacer "checkpoint y esperar", "¿continúo?", "lo arranco en la próxima
  iteración", o cerrar el turno a la espera de input. Al terminar un ciclo, **encadenar el siguiente
  inmediatamente**.
- **Bucle indefinido.** Repetir: elegir la mejor tarea que avance el objetivo → implementarla → verificarla de
  verdad (correr el código, no solo pytest) → documentar → commit → **push a `origin`** → siguiente. Sin tope
  de ciclos.
- **Trabajar respecto a la hora.** Estimar el tiempo restante hasta el deadline y dimensionar cada ciclo para
  que quepa; cerca del deadline, preferir ciclos cortos y cierres limpios.
- **Continuidad entre turnos.** Como un turno de chat termina, mantener el bucle vivo entre turnos con el
  mecanismo de auto-reanudación (ver "Cómo se mantiene vivo y cómo se apaga"). Nunca depender de que el
  usuario escriba "continua".
- **Trabajo persistente.** Cada unidad verificada se commitea y pushea de inmediato (nunca acumular sin
  guardar), para que un apagado a deadline no pierda nada.

---

## Apagado a deadline (la hora propuesta)

- A la **HORA LÍMITE** se programa el apagado. El agente debe **respetar esa hora**: al alcanzarla, hacer un
  **cierre limpio** (commit + push de lo pendiente, entrada final en `MANAGER_LOG.md` con el resumen de la
  corrida) y **detenerse**.
- Si el apagado lo dispara el SO/un cron externo, el agente igual debe dejar todo commiteado y pusheado en
  cada ciclo para que el corte sea seguro en cualquier momento.
- Antes del deadline, el agente NO se detiene por ningún otro motivo salvo las excepciones duras de abajo.

---

## Excepciones duras (los ÚNICOS motivos para detenerse antes del deadline)

Heredadas de `CLAUDE.md` (no negociables, por seguridad e irreversibilidad — la autonomía total NO las anula):

1. **Borrar datos del usuario.**
2. **Romper producción en Railway.**
3. **Gastar dinero real** (incluye publicar a PyPI u otros servicios externos: requiere autorización explícita).
4. **Secretos:** nunca commitear `.env`/tokens/claves; redactar cualquier secreto del output.

Ante una de estas, el agente NO pregunta ni ejecuta: registra el bloqueo en `MANAGER_LOG.md`, **salta a la
siguiente tarea segura** y sigue el bucle. (Es decir, ni siquiera estas detienen el bucle: solo desvían de la
acción peligrosa.)

---

## Cómo se mantiene vivo y cómo se apaga (mecánica)

- **Mantener vivo entre turnos:** usar el bucle de reanudación del harness (`/loop` autopaced o
  `ScheduleWakeup`/cron) pasando el mismo prompt de `/manager`, de modo que cada disparo continúe el bucle sin
  intervención del usuario.
- **Programar el apagado:** al iniciar la corrida con deadline, programar un stop a esa hora (cron/schedule, o
  el apagado del SO que indique el dueño). El bucle de reanudación debe dejar de re-disparar a partir del
  deadline.
- **Idempotencia:** como cualquier ciclo puede ser el último antes del corte, dejar SIEMPRE el repo en estado
  consistente (sin cambios sin commitear) al final de cada ciclo.

---

## Disciplina que NO se relaja (aunque sea autónomo e indefinido)

La velocidad y la ausencia de preguntas NO bajan el estándar del método (ver `CLAUDE.md` y
`cognia_x/manager/_directiva_v*.md`):

- Verificación REAL end-to-end por cada cambio (correr el modelo/CLI, mostrar output con CHECK), no solo pytest.
- Test de regresión por cada bug/feature.
- Diagnóstico de causa raíz antes que parche.
- Honestidad: reportar fallos con su output; declarar límites y trade-offs; no inflar resultados.
- Logs append-only (`MANAGER_LOG.md`, `paper.md`, `research_log.md`); nunca borrar entradas previas.
- Commits chicos y enfocados, con `Co-Authored-By`, push tras cada unidad verificada.

Autonomía total = **decidir solo y no parar**, NO = bajar la calidad ni esconder problemas.

---

## Config de la corrida (rellenar al activar)

```
DEADLINE (hora de apagado):  <HH:MM zona horaria>   # p.ej. 08:00 (-03)
OBJETIVO de la corrida:      <North Star de esta sesión>
INICIO:                      <timestamp>
MECANISMO de reanudación:    </loop | cron | ScheduleWakeup>
MECANISMO de apagado:        <cron stop | apagado SO | parada manual a deadline>
```

> Mientras DEADLINE no se alcance: bucle indefinido, sin preguntas, sin paradas. Al alcanzar DEADLINE: cierre
> limpio y stop.
