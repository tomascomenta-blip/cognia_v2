# Diagnóstico ESTRUCTURA (JSON) — veredicto: CERRAR sin GPU (GBNF)

Instrumento: `cognia_v3/eval/diag_json.py` (N=72, sha256 TAREAS
`616cb05f…`) + `gbnf_json.py` (genera GBNF desde el schema {clave:tipo}).
Brazos pareados por ítem, greedy, cache_prompt=false, matando el
llama-server entre brazos. Corrida 2026-07-10.

## Resultado (pareado, N=72)

| brazo | pasa | no_json | schema (FORMATO) | contenido (CAPACIDAD) |
|---|---|---|---|---|
| A — sin grammar | 64 (88.9%) | 0 | **7** | 1 |
| B — GBNF | **71 (98.6%)** | 0 | **0** | 1 |

**McNemar A→B**: n01 = 7 (A falla, B pasa), n10 = 0, **p = 0.016**.
Delta = **+9.7pp**, todo por eliminar los 7 fallos de schema.
Fallos de schema en A: ítems `[14,17,20,34,47,51,64]` → **0 en B**.
Único residual de B: ítem 16 (`¿cuánto es 7×8?` → responde `0.875`) =
CAPACIDAD (el modelo calcula mal), que ni grammar ni adapter arreglan.

## Por qué el experto "estructura" del plan NO se entrena

1. **El gate del plan (+15pp) era aritméticamente inalcanzable.** El techo de
   formato total era 7/72 = 9.7pp (todos los fallos son de schema, no_json=0).
   Ningún adapter puede subir +15pp cuando el gap de formato entero es 9.7pp.
   El resto (contenido) es capacidad, línea muerta del programa.
2. **GBNF captura el techo completo con CERO GPU.** El grammar fuerza las
   claves exactas del schema en el sampling → `no_json` y `schema` quedan
   imposibles por construcción (schema 7→0, medido). Cierra `dependencias`
   vs `dependencies`, `{}` vs `{empty:{}}`, `{}` vs `{nulo:null}` — los 3
   fallos originales del diag N=24 — y los 4 nuevos del N=72.
3. Es exactamente el criterio del plan (§6): "estructura solo si el gap es de
   FORMATO → kernel". El formato lo cierra GBNF; no queda gap para el kernel.

## Palanca de deploy (cero GPU)

El backend ya pasa `grammar` a `/completion` (node/llama_backend.py) y ya se
usa en benchmark_code. Para que el PRODUCTO emita JSON contra schema:
cuando una tarea/tool pide JSON con estructura conocida, pasar el GBNF de
`gbnf_json.esquema_a_gbnf(schema)`. Queda como utilidad disponible; el
cableado a un caller concreto (p.ej. tool `json_crear` con schema) es trabajo
de producto, no de entrenamiento.

## Estado

Línea "experto estructura (#4 del plan)" **CERRADA sin GPU** — 4ª línea que el
método "diagnóstico por clases antes de la GPU" cierra con medición (junto a
español, LCD y razonamiento/código por capacidad). El valor entregado: la
medición honesta + `gbnf_json.py` como palanca reutilizable.
