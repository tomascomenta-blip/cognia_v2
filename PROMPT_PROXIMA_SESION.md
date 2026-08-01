# Prompt de arranque — próxima sesión (Fable 5, plan Max 200)

*Escrito el 2026-08-01 tras la sesión nocturna 19:05→07:44. Copiar desde la
línea siguiente y rellenar HH:MM.*

---

ultracode — Sesión autónoma en C:\Users\usuario\Desktop\cognia_v2 hasta las
HH:MM. Trabaja 100% autónomo hasta esa hora: no me preguntes nada. Plan Max
200: no racionees los subagentes — revisión adversarial (2-4 agentes) antes
de CADA gasto de GPU, verificación independiente de todo número que devuelva
un subagente (también de los TUYOS: anoche tu propia cota estaba mal sumada
hacia tu conclusión), y workflows para las revisiones.

ARRANQUE (en este orden):
1. Si queda un shutdown armado, `shutdown /a` y arma el nuevo al deadline,
   más un cron de aterrizaje 16 min antes. **Si el deadline de arriba quedó
   como "HH:MM" literal, NO armes apagado a una hora inventada**: aterriza
   autogestionado y déjalo registrado (así se hizo el 2026-07-31).
2. Lee ANTES de tocar nada: MANAGER_LOG.md (entradas "2026-07-31 (noche
   19:05→22:10)" y "2026-08-01 (madrugada)" con su cierre 07:44),
   META_MODELO_GRANDE.md ("DÓNDE ESTAMOS — 2026-08-01 de MADRUGADA", que
   manda), y tus memorias eje-esfuerzo-cerrado-presupuesto-manda,
   reparar-no-bate-a-remuestrear, potencia-antes-de-matar-una-via,
   reproducir-antes-de-contar-como-fallo.
3. Flota: el backend SOLO si la prioridad lo pide (quedó abajo). Para celdas
   high: `--ctx` según lo que exija el preflight del runner (65536 estándar;
   131072 CABE, medido 15.251/16.311 MiB) y `COGNIA_TIMEOUT_HTTP` ≥ pared.
   El preflight de b3_factorial ABORTA solo si falta algo: confía en él.
4. OPERATIVO: el harness mata procesos a los ~45 min → corridas largas con
   `Start-Process ... -WindowStyle Hidden -PassThru` + log + PID, y
   vigilancia de VIDA con Monitor (tasklist), no solo del log. NUNCA edites
   .py con Get-Content/Set-Content en PS 5.1. Si el guard del shell bloquea
   un comando con rutas tipo "/algo" en strings (falsos positivos vistos con
   "/props" y "GPU / workflows"), escribe el script a fichero y ejecútalo.

EL DIAGNÓSTICO QUE MANDA (todo medido, banco propio — no lo re-litigues):
- **El goal en código está medido de punta a punta:** 20B local k=1 ~50-55%
  · BoN k=4 +12-15 pts (techo del pool 54.8% en hard) · esfuerzo +4 (MDE ±8)
  · presupuesto XL 1/12 tareas (4 truncan también a 110k; 3 re-sorteos con
  criterio tok>60k pre-registrado) · **frontier opus-5 95.5% (189/198),
  +79 netas (80/1, P=3.4e-23), hard 94% vs 30%.** El hueco es del MODELO en
  hard, no de configuración: las tres capas de instrumento están fuera y los
  dos knobs agotados.
- La comparación con el 70 publicado: hecha y firmada (50.0% [34.5,65.5],
  fuera del IC, residuales enumeradas). REP-F: cerrado sin GPU (techo +7 <
  MDE +9). El 12º intento de señal autogenerada en web: NO reabrir (0/11).
- Limitaciones del denominador frontier, firmadas: harness de Claude Code
  (no API pura), k=1, contaminación de entrenamiento plausible.

PRIORIDAD 1 — CERRAR EL GOAL COMO RESULTADO (sin GPU, una mañana):
  El número que falta no es un experimento nuevo: es el VEREDICTO. Con lo ya
  en disco, escribe el análisis formal "¿iguala el 20B+cómputo al frontier?"
  — pass@k del 20B (BoN de reparacion.json, k=1..4 y techo del pool) contra
  frontier k=1, apareado en las tareas hard comunes, con IC y MDE — y el
  informe EL GOAL, RESPONDIDO en META: dónde iguala (easy/medium con BoN),
  dónde no puede (hard, y con qué factor aun con techo de pool), y qué
  compraría cada palanca restante. Revisión adversarial del informe antes de
  firmarlo.

PRIORIDAD 2 — VARIANZA DEL DENOMINADOR (vía plan, ~1h, solo si mi
  autorización del plan sigue en pie — la di el 2026-07-31 y no la he
  retirado): frontier k=3 sobre las 83 hard (2 muestras más por tarea, ~166
  agentes opus effort high, misma mecánica de fichero byte-exacto).
  Enmienda al diseño ANTES; pass@1 promedio y varianza por tarea; actualiza
  el apareado. Si algo del instrumento cambia, para y enmienda.

PRIORIDAD 3 — VOLVER AL PRODUCTO (si sobra reloj): las pendientes de
  memoria: modo sombra del disyuntor de reparación, G3 de autoprogramación.
  Nada de GPU salvo verificación e2e; el gate de 5/5 sigue vigente.

QUÉ NO HAY QUE HACER:
- No re-medir nada ya firmado (BoN global, eje esfuerzo, XL, REP-F, 198).
- No reabrir señal autogenerada en web sin una idea NUEVA de verificación.
- No gastar dinero real (la referencia por API ~$31-78 tiene diseño listo
  pero exige mi OK explícito en esa sesión).
- No comparar niveles entre corridas: solo netos apareados intra-corrida, o
  entre-corridas con el confound declarado y medido (como low 60/138).

MÉTODO (no negociable): prereg antes de correr; potencia ANTES de gastar y
MDE reportado SIEMPRE; los TRES nulos donde haya selector; humo antes de
corrida larga; instrumento ≠ modelo ≠ método (mira finish_reason y el crudo);
VERIFICA TÚ los números de los subagentes y los tuyos (recomputo
independiente); suite completa antes de cada commit con código; commit+push
por unidad verificada; benchmarks se entregan por FICHERO byte-exacto, nunca
por transcripción (la lección del 2026-07-31: recorté prompts sin querer al
transcribir y hubo que parar y re-correr).

TRAMPAS RECIENTES, para no repetirlas:
- Un pase con más presupuesto puede ser RE-SORTEO (no hay seed de sampling):
  el criterio de atribución se pre-registra (tok_salida > presupuesto viejo).
- Re-correr SOLO fallos conocidos tiene ratchet estructural: la compuesta
  solo puede subir — se declara y se etiqueta NO COMPARABLE.
- Mi juez "oficial" capa lotes a 8MB/120s: demasiado_grande es estrato de MI
  instrumento (re-juicio a 64MB en rejuicio_grandes.json), nunca fallo del
  modelo. El tope XL también deja residuo (abc377_e 87.9MB).
- El harness capa la salida de subagentes a 64k tokens: un agente que se
  pasa (arc191_d) es instrumento del PLAN, no fallo del modelo.

RED Y DINERO: sin dependencias de red salvo ampliar datasets. Nada de APIs
de pago. Líneas duras: no borrar datos míos, no romper producción, no
commitear secretos. Los chrome son mi navegador y los python de word-mcp y
ollama son míos — no los mates.
