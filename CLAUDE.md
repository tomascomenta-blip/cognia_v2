# CLAUDE.md — Reglas del repo Cognia

## Modo Manager Autónomo (autorizado por el dueño)
El manager/agente tiene autoridad para diagnosticar, decidir, implementar, probar, commitear y
**push a `origin`** sin pedir permiso paso a paso.
Solo detenerse ante: borrar datos del usuario, romper producción en Railway, o gastar dinero real.
Subir todo a GitHub **excepto información sensible** (tokens, claves, `.env`, secretos).
Publicar a PyPI u otros servicios externos solo con **autorización explícita** del dueño (es irreversible).

## Método de trabajo — OBLIGATORIO para TODAS las sesiones de Claude
Así se modifica este repo (es el método demostrado en las sesiones autónomas; seguirlo siempre):

1. **Entorno.** Usar SIEMPRE `venv312\Scripts\python.exe` (Python 3.12). El `venv/` del repo
   está roto (Python 3.14, wheels faltantes). Nunca `python` pelado para tests o scripts.
2. **Verificar antes de construir.** No asumir que lo existente corre: leer el código real,
   ejecutar la pieza y confirmar que funciona ANTES de construir encima. No confiar en docs
   viejas ni en reportes de sub-agentes sin verificar primero la afirmación clave.
3. **Diagnóstico antes que parche.** Encontrar la causa raíz (leer el código, reproducir el
   bug) en vez de tapar el síntoma. Distinguir bug real de producción vs ruido/aislamiento de test.
4. **Verificación REAL, no solo pytest.** Cerrar cada cambio corriendo el CLI / el modelo de
   verdad end-to-end y mostrando el output real con un CHECK explícito. pytest es necesario
   pero no suficiente: "código que corre o no cuenta".
5. **Test de regresión por cada bug/feature.** Agregar un test que falle sin el fix y pase con
   él. Correr los tests dirigidos del área tras cada cambio; la suite completa (ver Verificación)
   como última compuerta antes de cerrar. Reportar el conteo real (N passed / M failed).
6. **Código concreto, sin abstracciones de más.** Funciones planas, dicts, registries simples;
   nada de frameworks/capas que no agregan valor. Igualar el estilo, naming y densidad de
   comentarios del código vecino.
7. **Commits chicos y enfocados.** Mensaje detallado (qué / por qué / cómo se verificó), terminando
   con la línea `Co-Authored-By`. Push a `origin` tras cada unidad verificada.
8. **Secretos.** Nunca commitear `.env`/tokens/claves. Verificar que `.env` esté gitignoreado y
   NO trackeado antes de tocarlo; cargar tokens por variable de entorno en la MISMA línea del
   comando; redactar cualquier secreto del output. Publicar a PyPI/externos solo con autorización
   explícita (es irreversible).
9. **Código generado o ejecutado.** Validar SIEMPRE antes de registrarlo o correrlo: scan estático
   de imports (allowlist) + sandbox con timeout. Nada auto-generado se vuelve ejecutable sin pasar
   la verificación.
10. **Honestidad.** Declarar límites y trade-offs; reportar fallos con su output; si algo queda a
    medias, decirlo. Si rompés algo (p.ej. borrar un archivo trackeado), detectarlo y restaurarlo,
    no esconderlo.

## Restricciones duras (no negociar)
- Sin PyTorch en nodos. Sin sharding WAN síncrono. Sin draft model centralizado.
- **FedAvg:** permitido SOLO sobre adapters LoRA (el coordinator agrega/redistribuye adapters),
  NUNCA sobre parámetros completos del modelo base. Autorizado por el dueño 2026-06-16 (legitima
  `coordinator/federated_store.py`). Sujeto a la regla de abajo: los adapters no deben permitir
  reconstruir datos personales (ruido DP aplicado en cliente).
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
Tests rápidos (excluir e2e de inferencia, lento/pesado) — con el venv que SÍ funciona:
```
.\venv312\Scripts\python.exe -m pytest tests/ --ignore=tests/test_e2e_inference.py -q
```
Para verificación end-to-end real (no solo pytest): arrancar el CLI (`python -m cognia`) o
construir el orquestador (`ShatteringOrchestrator(manifest_path="shattering/manifests/cognia_desktop.json")`
+ `_try_load_llama()`) y probar contra el modelo de verdad, mostrando el output.

## Log
Avances se appendean a `MANAGER_LOG.md` (nunca borrar entradas previas).
