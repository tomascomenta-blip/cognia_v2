# Publicar 4.3.0 a PyPI — LISTO, falta solo el token

La corrida autónoma del 2026-07-24 dejó 4.3.0 **construido, verificado e instalado
en limpio**, pero NO pudo publicar: no hay credenciales de PyPI en la máquina
(sin `~/.pypirc`, sin `TWINE_*` en el entorno) y el dueño estaba dormido. Publicar
a PyPI es irreversible y requiere token explícito — no se inventa ni se elude.

## Estado verificado (todo verde)
- Suite completa: **5267 passed, 1 skipped**.
- Gate del camino feliz (obligatorio): **5/5**.
- `twine check`: PASSED en wheel y sdist.
- Instalación en venv limpio: OK; importa las 5 piezas nuevas; reporta 4.3.0.
- Artefactos en `dist/`: `cognia_ai-4.3.0-py3-none-any.whl` y `.tar.gz`.

## Para publicar (un solo comando, con tu token en la MISMA línea)
```
TWINE_USERNAME=__token__ TWINE_PASSWORD=pypi-XXXXXXXX \
  venv312/Scripts/python.exe -m twine upload dist/cognia_ai-4.3.0*
```
(no dejes el token en un archivo trackeado; va en la línea del comando y se borra del historial)

## Después de publicar, verificar de verdad (no asumir)
```
pip install --upgrade cognia-ai        # en otra máquina/venv
python -c "import importlib.metadata as m; print(m.version('cognia-ai'))"   # -> 4.3.0
```
