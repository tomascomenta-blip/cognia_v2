# cognia.tui — TUI profesional de Cognia

Interfaz de terminal (TUI) de Cognia construida sobre [Textual](https://textual.textualize.io/).
Es un frontend **nuevo y paralelo** que reemplaza de forma **incremental** al REPL antiguo
`cognia/cli.py`: el CLI viejo sigue **intacto y funcional**; esta TUI va asumiendo sus
capacidades checkpoint a checkpoint.

Navegacion 100% por teclado, metricas de sistema reales (psutil), chat conectado al backend
real (llama.cpp), dashboard de entrenamiento, paleta de comandos y modales de confirmacion.

## Como correr

```
venv312\Scripts\python.exe -m cognia.tui      # entorno del repo (Python 3.12)
python -m cognia.tui                          # si el entorno ya tiene Textual + psutil
```

Tambien embebible:

```python
from cognia.tui import CogniaTUI
CogniaTUI().run()
```

El arranque es **instantaneo**: el modelo de inferencia NO se carga en el boot, sino de forma
**perezosa** la primera vez que se pide una respuesta en el chat.

## Arquitectura

Un unico ensamblador (`app.py` -> `CogniaTUI`) compone componentes reutilizables y define los
atajos; no duplica logica de las vistas, solo orquesta foco, navegacion, toasts y confirmaciones.

| Componente | Archivo | Que hace |
|---|---|---|
| `CogniaTUI` | `app.py` | App raiz: layout (header / sidebar \| mainview / statusbar + footer), registra el tema, conecta sidebar -> ContentSwitcher, atajos, toasts (`notify_ok/info/warn/err`) y `confirm()`. |
| `CogniaHeader` | `widgets/header.py` | Barra superior: marca "Cognia" a la izquierda + `SystemMetrics` a la derecha. |
| `SystemMetrics` | `widgets/metrics.py` | CPU / RAM / DISK reales via psutil (refresco 1s, color por umbral) + GPU **honesta** (`--` si no hay GPU/pynvml, nunca un numero inventado). `snapshot()` reusa los valores. |
| `Sidebar` | `widgets/sidebar.py` | Menu lateral (`ListView`): un item por vista; `j/k` y flechas mueven el cursor; el item resaltado cambia la vista. |
| `MainView` | `widgets/mainview.py` | `ContentSwitcher` con una vista por seccion (fuente de verdad `VIEWS`). |
| `ChatView` | `widgets/chat.py` | Vista de chat: historial + input; al Enter lanza un worker-thread que llama al backend real (la generacion en CPU **no** bloquea la UI). |
| `TrainingDashboard` | `widgets/training.py` | Dashboard de entrenamiento: cabecera + badge, tiles (epoch/step/tok-s/loss/lr/batch/eta/vram), 2 ProgressBar y metricas de sistema. Empty-state si no hay corrida. |
| Vistas Memoria / Modelos | `widgets/mainview.py` (`PlaceholderView`) | Placeholders con empty-state claro; se cablearan en checkpoints siguientes. |
| `HelpView` (Ayuda) | `widgets/mainview.py` | Lista los atajos agrupados, leyendolos de `App.BINDINGS` (no se desactualiza). |
| `LogsPanel` (Logs) | `widgets/logspanel.py` | `RichLog` con `write(msg, level)` coloreado por nivel (ok/info/warn/err/muted) + timestamp. |
| `StatusBar` | `widgets/statusbar.py` | Franja inferior: estado a la izquierda, contexto (vista activa) a la derecha. |
| `ConfirmModal` | `widgets/modals.py` | `ModalScreen[bool]` centrado para acciones destructivas (salir, limpiar chat). |
| `CogniaCommands` | `commands.py` | Provider de la paleta de comandos (ctrl+p / `:`): `discover()` + `search()` difuso. |
| `CogniaBackend` | `backend.py` | Adaptador **perezoso** y sincrono del backend real llama.cpp (`node/llama_backend.py`); nunca crashea (todo fallo -> `[backend no disponible: ...]`). |
| `TrainingMonitor` | `training_monitor.py` | Lectura no-bloqueante del progreso de entreno desde un JSON; degrada a `idle` si falta/corrupto. |
| `theme.py` | `theme.py` | Sistema de diseno: `COLORS` (paleta semantica, **unica** fuente de hex) + el `Theme` de Textual + helpers (`level_color`, `empty_state`). |
| `app.tcss` | `app.tcss` | Hoja de estilos; usa las variables del tema (`$primary`, `$success`, ...), sin hex hardcodeado. |

## Atajos de teclado

| Tecla | Accion |
|---|---|
| `1` .. `6` | Ir a Chat / Entrenamiento / Memoria / Modelos / Logs / Ayuda |
| `j` / `k` | Bajar / subir en el menu (tambien flechas) |
| `enter` | Activar el item resaltado / enviar el mensaje del chat |
| `?` | Ayuda (lista completa de atajos) |
| `ctrl+p` o `:` | Abrir la paleta de comandos |
| `ctrl+l` | Limpiar el chat (con confirmacion) |
| `tab` / `shift+tab` | Mover el foco entre paneles |
| `q` | Salir (pide confirmacion) |

## Paleta semantica

Definida una sola vez en `theme.py` (`COLORS`); el CSS la consume via el tema registrado.

| Color | Significado |
|---|---|
| Verde (`ok`) | Exito / saludable |
| Azul (`info`) | Informativo |
| Amarillo (`warn`) | Advertencia |
| Rojo (`err`) | Error / critico |
| Gris (`muted`) | Secundario / placeholder |
| Violeta (`accent`) | Identidad de Cognia |

## Estado (FASE 1)

**Hecho:**
- Fundacion: layout por componentes, design system (theme + tcss), navegacion por teclado.
- Metricas de sistema **reales** (CPU/RAM/DISK + GPU honesta).
- Chat cableado al backend real (llama.cpp), con worker-thread (UI nunca se congela) y
  carga perezosa del modelo.
- Dashboard de entrenamiento con polling no-bloqueante de `training_progress.json`.
- Capa de UX: paleta de comandos, toasts con severidad, modales de confirmacion, ayuda viva.
- 24 tests headless (`tests/test_tui_*.py`) verdes.

**Pendiente:**
- Paridad total con los ~60 comandos del `cognia/cli.py` viejo: la migracion es **incremental**
  (memoria, modelos, agentes, etc. siguen viviendo en el CLI por ahora).
- Vistas Memoria y Modelos son placeholders (empty-state); se cablearan a sus subsistemas.
- FASE 2 escribira `cognia_x/training_progress.json` para alimentar el dashboard con una
  corrida real en vivo.
