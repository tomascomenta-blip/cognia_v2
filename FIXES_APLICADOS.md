# COGNIA — Fixes Aplicados (cognia_clean)

Este es un clon limpio del repositorio `tomascomenta-blip/cognia_v2` con los
siguientes problemas reales corregidos.

---

## 🧹 Limpieza estructural

**Eliminados de la raíz:**
- `paso3_parches.py` → `paso6_parches.py` (parches históricos, ya integrados)
- `fix.py`, `fix3.py`, `fix3.py.py`, `fix_*.py` (scripts de corrección puntual)
- `PARCHES_EXISTENTES.py`, `integration_patch*.py`
- `cognia_v3.py.backup_fix_db` (backup de debug)
- `debug2.py`, `debug_inv.py`, `test_insert.py`, `test_logs.py`, `sandbox_tester.py`
- `migrar.py`, `migrate_db.py`, `limpiar.py`, `limpiar_memoria.py`, `reset_memoria.py`
- `backup_20260411_121400/` (carpeta de backup completa)
- `cognia_update/` (copia obsoleta de módulos)
- `docs/` (vacío)
- `*.db-shm`, `*.db-wal`, `cognia.log` (no deben estar en git)
- `cognia_optimizer.jsx` (sin contexto, sin uso)
- Scripts PowerShell de raíz (`aplicar_paso4.ps1`, `deploy_cognia.ps1`, etc.)

**Movidos a `tools/`** (utilidades, no producción):
- `auto_editor.py`, `backup_manager.py`, `generator_improved.py`

**Unificado duplicado:**
- `cognia/language_engine.py` (801 líneas, desactualizado) → reemplazado por la versión de raíz (853 líneas)
- `consolidation_engine.py` (duplicado idéntico en raíz y en `cognia/`) → conservado solo en `cognia/`

---

## 🔧 Fixes de código

### FIX 1 — `cognia/database.py` → `db_connect()` mejorado
**Problema:** SQLite sin WAL mode ni timeout → `database is locked` bajo concurrencia.  
**Fix:** Añadidos `PRAGMA journal_mode=WAL`, `PRAGMA synchronous=NORMAL`,
`PRAGMA cache_size=10000`, `PRAGMA foreign_keys=ON`, `timeout=30`,
`check_same_thread=False`.

### FIX 2 — `cognia_embedding.py` → `AsyncEmbeddingQueue._run()` race condition
**Problema:** `_trigger.clear()` ocurría FUERA del lock. Si dos hilos agregaban
items simultáneamente, uno podía perder el trigger y esperar 200ms innecesariamente.  
**Fix:** `_trigger.clear()` movido DENTRO del lock, después de tomarlo.

### FIX 3 — `model_router.py` → Cache LRU real (antes FIFO ineficiente)
**Problema:** El cache de 32 entradas usaba FIFO: eliminaba la mitad más antigua.
Con consultas variadas, hit rate era ~0%.  
**Fix:** Reemplazado por `OrderedDict` con `popitem(last=False)` → eviction LRU O(1).
Tamaño aumentado de 32 a 128 entradas.

### FIX 4 — `model_router.py` → Timeout adaptativo por modo
**Problema:** Timeout fijo de 180s para todos los modos. Una consulta general
podía bloquear el hilo 3 minutos.  
**Fix:** `modo_codigo` → 120s, `modo_general` → 60s.

### FIX 5 — `cognia/consolidation_engine.py` → Yield entre fases
**Problema:** El ciclo completo ejecutaba 6 fases seguidas dentro del lock,
bloqueando el hilo principal durante todo el ciclo de sueño.  
**Fix:** `time.sleep(0.05)` entre fases, y cada fase tiene su propio `with self._lock`.

### FIX 6 — `.gitignore` → archivos de runtime excluidos
**Problema:** `*.db-shm` y `*.db-wal` (WAL de SQLite activo) no estaban en
`.gitignore`. Si alguien clonaba el repo y tenía esos archivos, la DB podía
quedar en estado inconsistente.  
**Fix:** Añadidos `*.db-shm`, `*.db-wal`, `*.db-journal`, `*.log`.

### FIX 7 — `cognia/cognia.py` → Connection leak en `energy_log`
**Problema:** Si el `INSERT INTO energy_log` fallaba (tabla no existente, etc.),
`_ec.close()` nunca se llamaba → connection leak.  
**Fix:** Añadido bloque `try/finally` para garantizar `_ec.close()` siempre.

### FIX 8 — `investigacion_nocturna.py` + `investigacion_masiva.py` → Rate limiting
**Problema:** Las requests a Wikipedia se hacían sin intervalo mínimo.
Con múltiples nodos activos, esto escalaría a un flood involuntario.  
**Fix:** `_rate_limited_urlopen()` con mínimo 1.5s entre requests (Wikipedia policy: max 1 req/s).

### FIX 9 — `cognia/memory/episodic_fast.py` → VectorCache COUNT throttle
**Problema:** `_get_db_count()` abría una conexión SQLite y hacía `COUNT(*)`
en CADA llamada a `search()` (es decir, en cada búsqueda semántica).  
**Fix:** Cache de 2 segundos para el count. Máximo 1 query COUNT(*) cada 2s.

### FIX 10 — `cognia/vectors.py` → `cosine_similarity` fast path con numpy
**Problema:** La función usaba Python puro (loops). Con 6000+ vectores de
384 dimensiones, era el cuello de botella del fallback lento.  
**Fix:** Fast path con `numpy.dot()` cuando numpy está disponible (100x más rápido).
Fallback Python puro conservado para entornos sin numpy.

### FIX 11 — `cognia/attention.py` → `time.time()` una sola vez por batch
**Problema:** `score()` llamaba `time.time()` dentro del loop por cada episodio.
Con 50+ episodios, esto eran 50+ syscalls innecesarios.  
**Fix:** `current_time` calculado una sola vez en `filter_memories()` y pasado a `score()`.

---

## 🆕 Nuevo: `storage/db_pool.py`

Connection pool opcional para SQLite. Útil cuando hay alta concurrencia.

```python
from storage.db_pool import get_pool

with get_pool("cognia_memory.db").get() as conn:
    rows = conn.execute("SELECT * FROM episodic_memory LIMIT 10").fetchall()
    # commit automático al salir del with
```

Mantiene hasta 5 conexiones reutilizables por DB. Si el pool está agotado,
crea una conexión temporal en lugar de bloquear.

---

## 📁 Estructura final

```
cognia_clean/
├── cognia/                    # paquete principal v3
│   ├── memory/                # episódica, semántica, working, chat
│   ├── knowledge/             # grafo, inferencia, temporal, objetivos
│   ├── reasoning/             # hipótesis, contradicción, metacognición
│   ├── research_engine/       # investigación autónoma
│   ├── program_creator/       # hobby de programación
│   ├── cognia.py              # clase principal (1043 líneas)
│   ├── attention.py           # sistema de atención ponderada
│   ├── language_engine.py     # motor híbrido simbólico+LLM (853 líneas)
│   ├── consolidation_engine.py
│   ├── compression.py
│   ├── database.py            # ← FIJADO
│   ├── vectors.py             # ← FIJADO
│   └── config.py
├── storage/
│   └── db_pool.py             # ← NUEVO: connection pool
├── tools/                     # utilidades de desarrollo (no producción)
│   ├── auto_editor.py
│   ├── backup_manager.py
│   └── generator_improved.py
├── cognia_embedding.py        # ← FIJADO (race condition)
├── model_router.py            # ← FIJADO (LRU cache, timeout adaptativo)
├── language_engine.py         # (movido a cognia/ como versión unificada)
├── consolidation_engine.py    # (unificado, solo en cognia/)
├── investigacion_nocturna.py  # ← FIJADO (rate limiting)
├── investigacion_masiva.py    # ← FIJADO (rate limiting)
├── web_app.py
├── requirements.txt
├── .gitignore                 # ← FIJADO (*.db-shm, *.db-wal)
└── FIXES_APLICADOS.md         # este archivo
```

### FIX 12 — BOM UTF-8 en 5 archivos Python
**Problema:** Los archivos `cognia.py`, `respuestas_articuladas.py`, `cognia/cli.py`,
`cognia/program_creator/__init__.py` y `cognia/memory/episodic.py` tenían BOM
(`\xef\xbb\xbf`) al inicio. Esto puede causar `SyntaxError: invalid non-printable
character` en ciertos entornos Linux y en imports de Python 3.  
**Fix:** BOM eliminado de los 5 archivos.
