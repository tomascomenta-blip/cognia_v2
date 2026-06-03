# MANAGER_RULES.md
# Reglas del sistema autonomo de Cognia — leer ANTES de modificar cualquier archivo

## Archivos PROHIBIDOS sin permiso explicito del usuario
- `.claude/settings.json` / `settings.local.json`
- `.claude/CLAUDE.md`
- `.env`
- `coordinator/app.py` (auth critica)
- `security/key_manager.py`

Si necesitas cambiar algo en esos archivos: escribe la propuesta en
`MANAGER_LOG.md` y espera confirmacion.

## Archivos LIBRES para modificar sin pedir permiso
Todo lo demas en el repo, especialmente:
- `shattering/`, `node/`, `cognia/`, `coordinator/` (excepto app.py)
- `cognia_desktop/renderer/`, `cognia_desktop/main.js`, `preload.js`
- `cognia_desktop_api.py`
- `tests/`
- `scripts/`

## Reglas de codigo
- Sin abstracciones nuevas sin pedido explicito
- Sin comentarios que expliquen QUE; solo WHY si no es obvio
- Sin half-implementations
- Nunca `sqlite3.connect()` directo — usar `storage/db_pool.py`
- Nunca hardcodear constantes de arquitectura — usar `shattering/model_constants.py`
- Tests primero si afecta consolidacion, VectorCache o relay

## Flujo de sub-agente
1. Leer este archivo
2. Leer ROADMAP.md para contexto de fases
3. Implementar el cambio asignado
4. Correr tests: `python -m pytest tests/ -x --tb=short -q`
5. Reportar resultado en MANAGER_LOG.md

## MANAGER_LOG.md
Cada sub-agente debe appendear una entrada al final de MANAGER_LOG.md con:
```
## [YYYY-MM-DD HH:MM] <tarea>
- Archivo modificado: X
- Resultado tests: PASS/FAIL
- Notas: ...
```
