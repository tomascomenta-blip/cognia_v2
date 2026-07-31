# Prompt para la próxima sesión (deadline 13:00)

_(escrito al cerrar la sesión del 2026-07-30/31. Copiar tal cual.)_

---

ultracode — Sesión autónoma en C:\Users\usuario\Desktop\cognia_v2 hasta las 13:00.
Trabaja 100% autónomo hasta esa hora: no me preguntes nada.

ARRANQUE (en este orden):
1. HAY UN SHUTDOWN ARMADO A LAS 04:30 de la sesión anterior: si el equipo
   sigue vivo, cancélalo con `shutdown /a` y arma el nuevo a las 13:00, más un
   cron de aterrizaje a las 12:44 (matar corridas con gracia — los runners
   guardan incremental y reanudan con --reanudar —, árbol limpio y 0 commits
   sin pushear, actualizar MANAGER_LOG/META, lecciones a memoria, bajar el
   backend).
2. Lee ANTES de tocar nada: MANAGER_LOG.md (la entrada del 30/31 entera, 21
   puntos + CIERRE 04:14), META_MODELO_GRANDE.md (empieza por "DÓNDE ESTAMOS
   — síntesis del 2026-07-31", que manda sobre lo de abajo),
   PREREG_BANCO_CODIGO_20260730.md **con sus 4 enmiendas**, y tus memorias
   banco-publico-de-codigo, reproducir-antes-de-contar-como-fallo,
   metrica-primaria-y-brazo-nulo, contrato-condena-sanos y
   verificacion-sin-especificacion.
3. Al levantar la flota: VERIFICA slots=1 y n_ctx>=16384 en /props antes de
   gastar GPU. Para gpt-oss usa --ctx 16384.
4. OPERATIVO, no lo aprendas a golpes: **el harness mata los procesos de
   fondo a los ~45 min**. `Start-Process ... -NoNewWindow` muere con su
   PowerShell padre; lo que SÍ sobrevive es
   `Start-Process ... -WindowStyle Hidden -PassThru` con redirección a log.
   Vigila con Monitor y relanza con --reanudar si hace falta.

EL DIAGNÓSTICO QUE MANDA (medido anoche, no lo re-litigues):
- **El BoN REPLICA EN TERRENO PÚBLICO.** LiveCodeBench `test6`, 167 tareas
  posteriores al corte del 20B, examen partido desde `private_test_cases`
  (5 visibles / 15 ocultos, ninguno en ningún prompt):
  **+21.00 sobre el AZAR con P<1e-4**, y replicado 3 veces —
  **+21.00 / +18.50 (otro examen) / +17.75 (otras muestras)**, todos P<1e-4.
  Supera los TRES nulos, incluido AZAR-1-TEST (+17.67), que ya usa el examen.
  El efecto CRECE con la dificultad: hard +13.00, medium +7.25, easy +2.25.
- MBPP es HUMO y no cuenta como réplica: su juez oculto es 1 assert en el
  97.8% y P(oculto|visibles)=0.849; ahí el BoN solo saca +2.17 contra
  AZAR-1-TEST (P=0.18, no vive). Ese contraste es lo que hace interpretable
  el número de LCB.
- **PERO EL CUELLO DEL GOAL NO SE HA MOVIDO: el BoN necesita TESTS.** En web,
  donde no los hay, siguen 10 vías de señal autogenerada muertas bajo *"una
  verificación que no lee la especificación detecta INACTIVIDAD, no
  INCORRECCIÓN"*.
- Banco AMPLIADO ya en disco y validado, SIN medir: **342 tareas,
  2024-09-22 → 2025-04-06**. `easy` está saturado (94.8%): no informa.
  `hard` tiene recorrido (pass@1 24.7%, 154 tareas en el banco ampliado).

PRIORIDAD 1 — LA REPARACIÓN CON CONTRAEJEMPLO SE REABRE, Y AHORA SÍ SE PUEDE.
La prioridad #1 histórica de META (reparación guiada por contraejemplo) está
SUSPENDIDA desde el 2026-07-28 por evidencia propia: dos A/B intercalados
mostraron que las rondas RESTAN (brutal −3, fácil −7). Pero la suspensión
tenía una CONDICIÓN escrita: *"la literatura sigue siendo válida EN SU
CONDICIÓN: TDDev/self-repair ganan con un verificador FIABLE; la nuestra no lo
es todavía"*. **En código el verificador SÍ es fiable: son los tests, y anoche
quedó medido que discriminan (ACUSA_SANOS 2.0%, DEJA_PASAR 13.4%).**
Así que la condición se cumple por primera vez y la vía se reabre.

  1. Prereg antes de correr, con la comparación que manda: **BoN contra
     reparación a ISO-CÓMPUTO**, no a iso-muestra. Es la regla de META y es
     la única lectura honesta (un 20B genera 3-5× más rápido que un frontier:
     lo que se compra es intentos por segundo).
  2. Lo que se le devuelve al modelo es **el CONTRAEJEMPLO del verificador**
     (entrada, salida esperada, salida obtenida), NO la traza ni el código
     roto: un estudio pre-registrado con placebo encontró que traza y código
     fallido EMPATAN CON UN PLACEBO SIN CONTENIDO (arXiv:2606.31511). Aquí el
     contraejemplo es gratis: el arnés ya lo tiene.
  3. Mide sobre `hard` del banco ampliado, que es donde hay recorrido, y con
     los TRES nulos. Brazo de reparación y brazo de BoN INTERCALADOS en la
     misma corrida.

PRIORIDAD 2 — HACER EL NÚMERO COMPARABLE, que es literalmente el goal.
El goal es *"igualar a un modelo grande desde 16 GB"*, y anoche se prohibió
—con razón— comparar con tablas públicas: el prompt, el evaluador y el cap de
tests son míos (enmiendas 1.8 y 2). Para responder al goal hay que quitar esa
prohibición ganándosela:
  - Replicar las CONDICIONES OFICIALES de LiveCodeBench (su prompt, su
    evaluador, su timeout por test, sin cap propio) sobre la misma ventana.
  - Reportar el pass@1 del 20B solo, y el del 20B+BoN, en esas condiciones.
  - Y solo entonces ponerlo al lado de la tabla publicada, nombrando la tabla
    y la ventana exactas.
  Si no se pueden replicar las condiciones, **se dice y no se compara** — es
  la regla que ya está escrita.

PRIORIDAD 3 — Si sobra reloj:
  (a) Completar `lcb_r2`, que se cortó por reloj a 158/167 tareas:
      `venv312/Scripts/python.exe scripts/b3_codigo.py --banco lcb --n 175
      --k 4 --pared 240 --ficheros lcb_test6.jsonl --sufijo _r2 --reanudar`
      **`--ficheros lcb_test6.jsonl` es OBLIGATORIO**: el banco se amplió a
      342 y sin fijarlo cambia el orden barajado. El runner detecta k/semilla/
      temp/banco distintos pero NO puede detectar un pool distinto.
  (b) Medir el banco ampliado de 342 tareas (1368 muestras, ~2 h).

QUÉ NO HAY QUE HACER:
- No abrir la vía 11 de señal autogenerada en la familia muerta (contrato
  ciego / consenso / metamórfico / poda / mudez). Van 0 de 11 y hay un
  argumento estructural de por qué.
- No tirar el pipeline web: el goal es igualar a un modelo grande desde 16 GB
  y el dominio era el vehículo, no el fin.
- No comparar el pass@1 de MBPP con ninguna tabla: está contaminado y su juez
  oculto no discrimina.

MÉTODO (no negociable): prereg antes de correr; brazos INTERCALADOS a nivel
tarea en la misma corrida, n>=6 por brazo; revisión adversarial (1-2 agentes)
antes de cada gasto — anoche devolvió 13 BLOQUEA y tumbó el eje de mi propio
prereg; humo barato antes de cada corrida larga; control CONCURRENTE siempre;
LA REFERENCIA DE UN SELECTOR ES EL AZAR, NO s1; **TODO neto se reporta contra
los TRES nulos (simple / con-código / 1-test), y no se llama "descartar
basura" a un nulo que consulta el examen**; la primaria excluye las tareas con
fallo de instrumento; VERIFICA TÚ MISMO los números que te den los
subagentes; todo juzgado bajo con_presupuesto; suite completa antes de cada
commit con código; commit+push por unidad verificada; corridas largas SIEMPRE
desacopladas.

CUATRO TRAMPAS QUE ME COMÍ ANOCHE, para que no se repitan:
- **Declarar sin medir, dos veces con el mismo número:** firmé "ventana de ~10
  meses" y eran 4 (y tras ampliar, 6.5), comprobable en 30 s sobre el fichero
  que ya tenía en disco.
- **Interpretar un nulo sin preguntarse qué información usa:** escribí "casi
  toda la ganancia es descartar basura" y era falso — con código extraíble en
  el 99.4% no había basura que descartar.
- **Contar INSTRUMENTO como fallo del modelo:** 107 muestras (16%) salieron
  `sin_sentinel`; reproducir UN caso a mano mostró que funcionaba, y
  re-juzgarlas cambió **48 veredictos** y subió el pass@1 de 44.6% a 51.8%.
  Si la tasa de instrumento se dispara, PARA y reproduce un caso a mano.
- **No releer lo que quedó escrito:** un `\b` dentro de una cadena Python
  no-raw metió un backspace invisible y dejó rota la propia instrucción de
  reanudación en el log.

RED Y DINERO: la sesión depende de internet solo si amplías datasets
(`test4.jsonl` son 1.2 GB y daría jul-2024). Si no hay conexión, hay banco de
sobra en disco. No gastes dinero real: nada de APIs de pago ni datasets de
suscripción.

Líneas duras: no borrar datos míos, no romper producción, no gastar dinero
real, no commitear secretos. Y ojo: los procesos `chrome` de la máquina son el
NAVEGADOR del dueño y los `python` de word-mcp son suyos — no los mates.
