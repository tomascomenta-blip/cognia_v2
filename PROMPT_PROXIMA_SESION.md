# Prompt para la próxima sesión (Fable 5, plan Max 200)

_(escrito al cerrar la sesión del 2026-07-31 mañana. Copiar tal cual y poner la hora límite.)_

---

ultracode — Sesión autónoma en C:\Users\usuario\Desktop\cognia_v2 hasta las
HH:MM. Trabaja 100% autónomo hasta esa hora: no me preguntes nada. Tengo plan
Max 200: no racionees los subagentes — revisión adversarial (2-4 agentes)
antes de CADA gasto de GPU, verificación independiente de todo número que te
devuelva un subagente, y workflows para las revisiones. El cuello es la GPU,
no tus tokens.

ARRANQUE (en este orden):
1. Si queda un shutdown armado, `shutdown /a` y arma el nuevo al deadline, más
   un cron de aterrizaje 16 min antes (matar corridas con gracia — guardan
   incremental y reanudan con --reanudar —, verificar TÚ los números de los
   subagentes, árbol limpio y 0 commits sin pushear, actualizar
   MANAGER_LOG/META, lecciones a memoria, bajar el backend).
2. Lee ANTES de tocar nada: MANAGER_LOG.md (la entrada "2026-07-31 (mañana
   05:41→12:44)" ENTERA, con sus cierres 11:55 / 12:35 / 12:46),
   META_MODELO_GRANDE.md ("DÓNDE ESTAMOS — síntesis del 2026-07-31 por la
   MAÑANA", que manda sobre todo), PREREG_REPARACION_CONTRAEJEMPLO_20260731.md
   (5 enmiendas) y PREREG_CONDICIONES_OFICIALES_20260731.md (3 enmiendas), y
   tus memorias reparar-no-bate-a-remuestrear, el-muro-era-mi-configuracion,
   potencia-antes-de-matar-una-via, reproducir-antes-de-contar-como-fallo y
   split-disjunto-por-indice-no-basta.
3. Flota: para el eje ESFUERZO el backend va OBLIGATORIO a `--ctx 65536`
   (cabe: 13.487 de 16.311 MiB, MEDIDO) y `set COGNIA_TIMEOUT_HTTP=1500`.
   Verifica slots=1 y n_ctx en /props antes de gastar GPU. Para lo demás,
   16384 basta. Levanta con:
   venv312\Scripts\python.exe scripts\servir_modelo.py --modelo gpt-oss --sin-draft --ctx 65536
4. OPERATIVO: el harness mata procesos a los ~45 min; lo que sobrevive es
   `Start-Process ... -WindowStyle Hidden -PassThru` con redirección a log.
   Una corrida MURIÓ EN SILENCIO ayer (sin traza en el .err): vigila VIDA DEL
   PROCESO (PID en fichero + tasklist en un Monitor), no solo el log. Y NUNCA
   edites .py con Get-Content/Set-Content en PS 5.1: dobla la codificación
   (pasó ayer; se arregla con git checkout + herramienta Edit, y se verifica
   en BYTES).

EL DIAGNÓSTICO QUE MANDA (medido, no lo re-litigues):
- El BoN replica en terreno público: +21.25 sobre el AZAR (P<1e-4, ya con la
  fuga por contenido corregida), 3 réplicas, crece con dificultad. `hard` es
  el único estrato que informa (pass@1 ~25%; easy saturado al 94.8%).
- REPARAR NO BATE A REMUESTREAR ni con verificador fiable: a iso-cómputo
  empate EXACTO (57 y 57 en 135 tareas hard). El contraejemplo no informa más
  que el placebo (+2, P=0.41) y TRIPLICA la negativa del modelo (5.3%→15.8%,
  P=0.0009; 34 cadenas cortadas). Veredicto SIN POTENCIA (efecto mínimo
  detectable ±10): no hay desbloqueo grande; un efecto <10 sigue sin excluirse.
- Lo que manda en esa tabla: 28.9% (1 muestra) → 40-44% (4 muestras). Gastar
  más cómputo compra 12-15 pts; CÓMO se gasta casi da igual.
- Prioridad 2 de ayer: NO se ganó el derecho a comparar con el 70 publicado
  (blog.collinear.ai, LCB v6, 3 muestras, reasoning high, 64k; NO es
  leaderboard oficial y no declara temperatura). Ejes ya medidos: EVALUADOR
  −2.7 pts, PROMPT +0 (10 discordantes 5-5). El eje ESFUERZO quedó ABIERTO:
  el muro eran TRES capas MÍAS (cap de tokens → n_ctx → TIMEOUT_HTTP matando
  a los 300.0 s exactos) y debajo hay un muro BIMODAL del modelo: o resuelve
  en <2.5 min o se pasa de 60.000 tokens pensando (5/9, todas ~567 s). Coste
  medido de replicar la referencia: ~346 s/muestra × 3 × 211 ≈ 60 h.
- El cuello del goal NO se ha movido: el BoN necesita TESTS; en web van 11
  vías de señal autogenerada muertas bajo "una verificación que no lee la
  especificación detecta INACTIVIDAD, no INCORRECCIÓN".

PRIORIDAD 1 — CERRAR EL EJE ESFUERZO por tramos (es el candidato grande de
los ~18 pts que faltan hasta el 70, y ya se sabe el precio):
  1. PREREG primero, y decide ANTES qué se hace con las muestras que truncan
     a 60.000 tokens: contarlas como fallo es el error que ayer se cazó DOS
     veces. Lo honesto: reportarlas como estrato aparte y dar el pass@1 con y
     sin ellas.
  2. Corre por tramos reanudables. El runner ya existe:
     venv312\Scripts\python.exe scripts\b3_factorial.py --n 24 --minutos MM
         --max-tokens 60000 --pared 1500 --celdas oficial_high
         --sufijo _high2 --reanudar
     (hay 9 muestras ya en b3_codigo/factorial_high2.json; el fichero
     factorial_high.json es la sonda vieja con timeout 300, NO mezclar).
     Con n=24 × 1 muestra son ~2.5 h y el eje queda cerrado con potencia
     mínima; si el reloj da, amplía hacia k=3 o n mayor.
  3. La comparación con el 70 SOLO desde la celda (prompt oficial, high, juez
     oficial) y enumerando en la MISMA frase las diferencias residuales
     (mi banco no cubre 2024-08→09-21; k; temperatura no declarada). Si no
     llega, se dice que no se comparó.

PRIORIDAD 2 — REPARACIÓN CON FALLBACK a generación fresca (el único cabo
suelto de la vía, y es barato: el arnés ya está):
  - Enmienda al prereg de reparación: brazo REP-F = cadena que cae a muestra
    independiente cuando el modelo se niega o no hay contraejemplo.
    Comparación apareada contra BoN, mismas tareas hard, POTENCIA calculada
    ANTES con scripts\b3_potencia_apareado.py.
  - Si REP-F tampoco bate a BoN, la vía se cierra del todo y META se
    actualiza. Eso también es un resultado.

PRIORIDAD 3 — si sobra reloj:
  (a) Completar reparacion.json (135→138 tareas):
      venv312\Scripts\python.exe scripts\b3_reparacion.py --n 154
          --minutos 30 --pared 240 --reanudar
  (b) DISEÑAR (no correr) la referencia frontier real sobre la misma ventana:
      qué modelo, qué condiciones, qué costaría — sin gastar dinero real.

QUÉ NO HAY QUE HACER:
- No reabrir la vía 12 de señal autogenerada en web (contrato ciego /
  consenso / metamórfico / poda / mudez / familia). Van 0 de 11.
- No comparar NADA con tablas fuera de la celda oficial-high-oficial.
- No re-medir el BoN global: replicado 3 veces. `hard` es donde se mide.

MÉTODO (no negociable): prereg antes de correr; brazos INTERCALADOS en la
misma corrida; POTENCIA calculada antes de gastar y efecto mínimo detectable
reportado SIEMPRE (veredicto SIN POTENCIA existe y sustituye al KILL); humo
barato antes de cada corrida larga; los TRES nulos; la primaria no condiciona
sobre variables post-tratamiento; instrumento ≠ modelo ≠ método (tres marcas:
instrumento / sin_codigo_modelo / no_generado — mirar finish_reason y el
crudo antes de clasificar); VERIFICA TÚ los números de los subagentes; suite
completa antes de cada commit con código; commit+push por unidad verificada;
corridas largas desacopladas Y con vigilancia de vida del proceso.

TRAMPAS DE AYER, para no repetirlas:
- TRES capas de instrumento propias leídas como "el modelo no puede". Antes
  de atribuir un límite al hardware o al modelo, MIDE el instrumento (la
  tercera capa se delataba porque todas las muestras morían a los 300.0 s
  EXACTOS — un número redondo repetido es firma de timeout propio).
- El modelo SE RINDE con respuesta completa ("Sorry, I cannot provide a
  solution."): es fallo del MODELO, no instrumento. Clasificarlo como
  instrumento expulsa de la primaria justo las tareas difíciles.
- El split disjunto por índice tenía FUGA POR CONTENIDO (11.4% de tareas).
  Todo split nuevo se comprueba con scripts\b3_fuga_split.py antes de usarlo.
- Un "+0 con P=1.0" se verifica antes de firmarlo (¿los brazos difieren de
  verdad? ¿hay discordantes?). Ayer era real: 10 discordantes repartidos 5-5.

RED Y DINERO: sin dependencias de red salvo ampliar datasets. No gastes
dinero real: nada de APIs de pago ni suscripciones. Líneas duras: no borrar
datos míos, no romper producción, no commitear secretos. Los procesos chrome
son el NAVEGADOR del dueño y los python de word-mcp son suyos — no los mates.
