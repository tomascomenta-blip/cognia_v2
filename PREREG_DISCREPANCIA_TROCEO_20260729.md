# PREREG — Sonda de la DISCREPANCIA del troceo: ¿por qué +6 en replay y −4 en el lazo?

**Fecha:** 2026-07-29 ~16:45, sesión tarde-noche 29. **Escrito ANTES de
correr.** Cierra el hueco que dejó la fase 3 (PREREG_SIN_TROCEO_LAZO,
RESULTADO): la ablación del troceo cobra +6 sobre los prompts CAPTURADOS
del gate v2 (fase 2, apareada, válida) y el mismo quitar cuesta −4/−6 en
el LAZO de esta tarde — con el lazo OFF rindiendo 79% (nivel crudo, sin
gap). Hipótesis en competencia:

- **H-material (texto×texto):** el efecto del troceo depende del CONTEXTO
  del prompt (feromona rica del gate nocturno, sus briefs, sus hints). En
  material fresco de hoy la ablación directa NO reproducirá el +6.
- **H-flujo (texto×flujo):** la ablación directa reproduce el +6 también
  en material fresco, pero el LAZO invierte el efecto (parse/reintentos/
  interacción con la visión). Entonces el lazo hace algo más que el texto.

## Diseño (dos etapas + un diff sin GPU)

### Etapa A — captura del material de HOY (~25-35 min GPU)

`b2_ab_fix2.py --var COGNIA_SIN_TROCEO --replicas 3 --sufijo capturas`
con **COGNIA_DUMP_PROMPTS** apuntando a su directorio (el volcado vive en
generator._call_llm; el contrato interno NO pasa por ahí y no contamina;
con max_rondas=1 cada celda emite EXACTAMENTE un prompt de generación).
24 celdas (12 OFF con troceo + 12 ON sin), intercaladas. Doble función:
materia prima fresca + re-medida direccional del A/B (n=3, NO decide —
se reporta junto al n=6 de fase 3).

- Verificación de alineación pre-fijada (antes de la etapa B): nº de
  prompts html == nº de celdas; los prompts del brazo OFF contienen
  "- REQUIRED component" y los del ON no (auto-etiquetado del brazo);
  orden de captura == orden de ejecución de celdas.

### Etapa B — ablación apareada sobre material FRESCO (~40-55 min GPU)

El instrumento de fase 2 (`b2_ablacion_texto.py`) con `--materia` nuevo
apuntando a las capturas OFF de la etapa A: **L = replay íntegro del
prompt fresco** vs **L−REQ = mismo prompt sin el bloque** (la MISMA
cirugía verificada), apareados, intercalados, juez estricto (original ∧
held-out), la clasificación de fallos de la sonda de la mañana. 12 pares
(24 gens).

### Diff estructural gate-vs-hoy (SIEMPRE, sin GPU)

Sobre los dos prompts.jsonl (96 del gate, 24 de hoy): largo total, tamaño
del bloque de feromona ("PROVEN PATTERNS"→formato), largo del brief
(TARGET LOOK→fin de bold), nº y largo de componentes REQUIRED, presencia
de reglas condicionales. Salida: tabla comparativa en el RESULTADO.

## Lecturas pre-fijadas (12 pares = DIRECCIONAL declarado; dirige, no adopta)

| neto (L−REQ)−L en material fresco | lectura |
|---|---|
| ≥ +3 | el +6 REPRODUCE en directo → **H-flujo**: el lazo invierte el efecto del texto; siguiente sonda = flujo (parse/reintentos/visión), con los crudos ya guardados |
| −2..+2 | el +6 NO reproduce → **H-material**: el efecto era del contexto del gate; el diff estructural nombra al sospechoso (feromona/brief); el troceo se queda como está en producción |
| ≤ −3 | el troceo PROTEGE también en directo hoy → H-material con signo invertido; mismo camino que la fila anterior |

- Guardas heredadas: pares con infra excluidos; sin_html = reprobado
  legítimo (clasificación por salud real del backend); si el neto de la
  etapa B y el de su lectura por contrato original caen en ramas
  distintas → gris.
- La re-medida direccional de la etapa A se reporta con su n=3 declarado:
  si contradice en SIGNO al n=6 de fase 3, ninguna conclusión de contexto
  se firma esta noche (inestabilidad intra-día > efecto).

## Presupuesto y orden

Corre DESPUÉS del bloque del marco (en cola ya): etapa A ~17:45, etapa B
~18:30, diff y RESULTADO ~19:30. Guardado incremental; corridas
desacopladas + vigías; slots=1/ctx verificados por los runners.

## Revisión

1 agente adversarial del prereg + el cambio `--materia` del runner de
ablación ANTES de la etapa B (la etapa A no toca código). Enmiendas aquí.

## PRIMERA ENMIENDA (2026-07-29 ~17:45 — tras la revisión, etapa A ya en el aire)

NO BLOQUEA (alineación verificada: con max_rondas=1 nada más pasa por el
dump; atribución 96/96 sin ambigüedad en el proxy del gate; el continue
sparse no rompe el apareado). Arreglos aplicados:

1. **Verificación de alineación corregida:** ~12.5% de celdas del lazo
   caen al fallback create_program y emiten un SEGUNDO dump (idea pelada,
   sin REQUIRED — se filtra solo). Esperado = 3 prompts OFF con REQUIRED
   por tarea (≥2 aceptable con declaración; <8 en total aborta), no
   "nº prompts == nº celdas". De paso, fe de erratas a fase 3: 3/19
   aprobados OFF venían del camino pelado (OFF lazo puro ~76%, misma
   banda).
2. **Cirugía en material fresco:** esperado = líneas RE_REQ del original
   + 1 (los briefs frescos dan 6-10 componentes, no siempre 10; el 11
   exacto era propiedad de los briefs del gate), mínimo 3.
3. **Atribución cortada antes del brief** (split en TARGET LOOK): un brief
   que mencione "hoja" en otra tarea abortaba la etapa B entera.
4. Notas operativas: etapa B con `--sufijo fresca --replicas 3`; la etapa
   A NO se reanuda (romperia el mapeo conteo→rep); si el neto de etapa B
   cae exactamente en +2, extensión pre-comprometida con 12 pares más
   (capturas nuevas) antes de leer.
