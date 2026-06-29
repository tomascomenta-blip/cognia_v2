# Context Map — memoria de proyecto con punteros, auto-construccion y gap-filling

> Sistema de ventana de contexto efectiva amplia y ESCALABLE para Cognia, CPU-first.
> Patron canonico: MemGPT/Letta (ventana = RAM, disco = memoria archival/recall con punteros).
> Diseno aprobado por el dueno (sesion /manager 2026-06-29).

## Problema que resuelve

El modelo tiene una ventana fija (16k hoy, 32k nativo). Un proyecto/conversacion puede crecer
a millones de tokens. En vez de meter todo a la ventana (imposible y, en el i3, ~18 min de
prefill por 32k), se mantiene un INDICE de PUNTEROS al texto que vive en disco, y solo se traen
a la ventana los pocos spans precisos que una consulta necesita.

## Principios

1. **No duplicar texto.** El puntero guarda `(source_ref, char_start, char_end)`, no el contenido.
   El texto se re-lee on-demand del origen por offset. -> O(1) espacio por chunk, ESCALABLE.
2. **Lossless solo en la capa de punteros.** Re-leer el original por offset es exacto (sin perdida).
   Los `summary` son lossy: sirven para NAVEGAR/rankear, nunca para reconstruir.
3. **Auto-construccion incremental.** Conforme Cognia ingiere archivos, edita o cierra turnos,
   hace upsert de punteros nuevos. La memoria se construye sola, sin paso manual.
4. **Gap-filling.** Cuando una consulta no encuentra cobertura en el indice, se busca en la parte
   del corpus NO indexada aun, se indexa ese hueco, y se reintenta. Indexado perezoso bajo demanda.
5. **CPU-first.** Sin GPU, sin ML nuevo. Re-lectura por offset + ranking vectorial/lexico baratos.

## Modelo de datos (SQLite via storage/db_pool — NUNCA sqlite3.connect directo)

```
context_pointers(
  id, project, source_kind['file'|'msg'|'text'], source_ref, char_start, char_end,
  chunk_ord, label, summary, inline_text, vector, importance, created_at )
context_coverage(
  id, project, source_ref, indexed_through, total_chars, mtime, updated_at,
  UNIQUE(project, source_ref) )   -- que parte de cada fuente ya esta indexada (para gap-filling)
```

- `source_kind='file'`: lossless por offset (re-lee `Path(source_ref).read_text()[start:end]`).
- `source_kind='msg'`: offset dentro de `chat_history.id` (mensajes de la conversacion).
- `source_kind='text'`: contenido NO offsetable (p.ej. PDF extraido) -> guardado en `inline_text`.

## Componentes y ciclos de construccion

- **Ciclo 1 (keystone):** `ContextMap` (schema + add_pointer + resolve lossless + coverage) + tests.
- **Ciclo 2 (auto-build en ingest):** `_chunk_text` trackea offsets; `_store_chunks` escribe punteros
  + marca coverage. El "anchor" pasa de copia-de-texto a puntero real.
- **Ciclo 3 (fetch index-first):** `query(texto, budget)` rankea punteros (vector), resuelve top-k a
  spans crudos dentro de un presupuesto PEQUENO y PARAMETRIZABLE (no los caps de 800, no 32k).
- **Ciclo 4 (gap-filling):** ante baja cobertura, `fill_gap` escanea lo NO indexado de la fuente,
  indexa el hueco y reintenta. Usa `context_coverage` para saber que falta.
- **Ciclo 5 (auto-maintain + artefacto + CLI):** hook por turno hace upsert de punteros de mensajes;
  `write_markdown` produce `cognia_context.md` legible; comandos CLI `/contexto` y `/retomar`.
- **Ciclo 6 (retriever fuerte):** indice lexico BM25 (identificadores de codigo) + recency real +
  log del fallback silencioso del embedder. Es el TECHO de calidad real del recall.

## Lo que el sistema SI y NO promete (honestidad)

- SI: lookup/recall preciso sobre corpus grande en disco, re-lectura lossless por offset,
  jump-to-message, retomar sesion sin releer todo.
- NO (sin trabajo extra fuera de alcance): sintesis global multi-hop "gratis" (la respuesta vive en
  las conexiones entre fragmentos; eso requiere pre-computo jerarquico tipo GraphRAG). El techo lo
  fija la calidad del retriever, no el tamano de la ventana.
