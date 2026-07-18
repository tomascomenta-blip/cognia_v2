# bbrain.md — Cerebro del repo Cognia

> AUTOGENERADO por cognia/bbrain.py — no editar a mano; regenerar con `cognia bbrain`.
> Generado: 2026-07-18 05:01:03

## Entorno
- Python: 3.12.10 (C:\Users\usuario\Desktop\cognia_v2\venv312\Scripts\python.exe)
- SO: Windows-11-10.0.26200-SP0
- CPU: AMD64 Family 26 Model 68 Stepping 0, AuthenticAMD
- Cores: 6 fisicos / 12 logicos
- RAM: 33.4 GB
- GPU: NVIDIA GeForce RTX 5060 Ti, 16311 MiB

## Backend LLM
- GGUF activo (node.llama_backend): no encontrado
- Modelos en C:\Users\usuario\.cognia\models: (vacio)
- Shards NPZ en C:\Users\usuario\.cognia\shards\qwen-coder-3b-q4: shard_0.npz, shard_1.npz, shard_2.npz, shard_3.npz
- Ollama: no disponible en http://localhost:11434

## Mapa del repo
- Modulos .py top-level: 36
- cognia/: 201 archivos .py
- node/: 14 archivos .py
- shattering/: 18 archivos .py
- coordinator/: 10 archivos .py
- storage/: 2 archivos .py
- security/: 4 archivos .py
- tests/: 188 archivos .py
- Archivos de test (tests/test_*.py): 185

## Reglas del proyecto

### Restricciones duras (no negociar)
- Entorno: usar SIEMPRE `venv312\Scripts\python.exe` (Python 3.12). El `venv/` del repo
  esta roto (Python 3.14, wheels faltantes). Nunca `python` pelado para tests o scripts.
- Sin PyTorch en nodos. Sin sharding WAN sincrono. Sin FedAvg. Sin draft model centralizado.
- Cero datos personales centralizados.
- Nada de mocks/stubs en produccion. Codigo que corre o no cuenta: cada subsistema
  cierra con prueba CLI real.
- Sin `sqlite3.connect()` directo -> usar `storage/db_pool.py`.
- Sin constantes de modelo hardcodeadas -> usar `shattering/model_constants.py`.
- Secretos NUNCA commiteados: `.env`, tokens y claves quedan fuera de git; cargar
  tokens por variable de entorno y redactar cualquier secreto del output.

### Metodo de trabajo esencial
1. Verificar antes de construir: leer el codigo real y ejecutar la pieza ANTES de
   construir encima; no confiar en docs viejas sin verificar la afirmacion clave.
2. Diagnostico antes que parche: encontrar la causa raiz (leer codigo, reproducir el
   bug) en vez de tapar el sintoma.
3. Verificacion REAL, no solo pytest: cerrar cada cambio corriendo el CLI / el modelo
   de verdad end-to-end y mostrando el output real. pytest es necesario pero no
   suficiente.
4. Test de regresion por cada bug/feature: un test que falle sin el fix y pase con el.
   Reportar el conteo real (N passed / M failed).
5. Codigo concreto, sin abstracciones de mas: funciones planas, dicts, registries
   simples; igualar estilo y densidad de comentarios del codigo vecino.
6. Honestidad: declarar limites y trade-offs; si algo queda a medias, decirlo.

### Verificacion rapida
```
.\venv312\Scripts\python.exe -m pytest tests/ --ignore=tests/test_e2e_inference.py -q
```
