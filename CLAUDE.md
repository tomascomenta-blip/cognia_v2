# CLAUDE.md — Reglas del repo Cognia

## Modo Manager Autónomo (autorizado por el dueño 2026-06-06)
El manager tiene autoridad para diagnosticar, decidir, implementar, probar, commitear y
**push a `origin`** sin pedir permiso paso a paso, hasta el deadline **04:30** (apagado
programado por `scripts/schedule_shutdown.py`). NO parar hasta esa hora.
Solo detenerse ante: borrar datos del usuario, romper producción en Railway, o gastar dinero real.
Subir todo a GitHub **excepto información sensible** (tokens, claves, `.env`, secretos).

## Restricciones duras (no negociar)
- Sin PyTorch en nodos. Sin sharding WAN síncrono. Sin FedAvg. Sin draft model centralizado.
- Cero datos personales centralizados.
- HYDRA como atención en la red es INVIABLE (modelo pre-cuantizado INT4 + pre-shardeado).
  El trabajo HYDRA es el **análogo a nivel de sistema**: enrutador de contexto/memoria de
  3 bandas (LOCAL / MEDIA / GLOBAL) construido SOBRE el routing LOGOS/TECHNE/RHETOR existente.
- Nada de mocks/stubs. Código que corre o no cuenta. Cada subsistema cierra con prueba CLI real.
- Sin `sqlite3.connect()` directo → usar `storage/db_pool.py` si existe.
- Sin constantes hardcodeadas de modelo → usar `shattering/model_constants.py`.

## Fuentes canónicas (verificar, no asumir)
- `CLAUDE_NOTES.md` — log real de sesiones autónomas + fixes (tracked).
- `ROADMAP.md` — estado de fases.
- `MANAGER_LOG.md` — bitácora del manager (append-only).
Regla del dueño: no tomar lo existente como verdad absoluta; revisar que **corra de verdad**
antes de construir encima, e implementar lo que falte.

## Verificación
Tests rápidos (excluir e2e de inferencia, lento/pesado):
```
python -m pytest tests/ --ignore=tests/test_e2e_inference.py -q
```

## Log
Avances se appendean a `MANAGER_LOG.md` (nunca borrar entradas previas).
