# Colab GPU — herramientas instaladas (puente agente ↔ GPU de Colab, sin copy-paste)

> Instalado y verificado el 2026-06-28 en el i3 (Windows). Objetivo: que un agente (Claude Code) dispare
> trabajo en runtimes GPU de Colab — para G2 y, más adelante, entrenamientos — sin que el dueño copie y
> pegue, y con menos desconexiones. Dos herramientas, dos modos.

## 1. MCP fork `colab-proxy-mcp` (SebastianGilPinzon/colab-mcp) — modo interactivo, anti-desconexión

**Qué es:** fork del MCP oficial de Google que arregla los 3 bugs que rompían el uso diario: tools
invisibles, "Disconnected from the local Colab MCP server", y control de GPU. Da control de una notebook
de Colab abierta en el navegador (crear/correr/editar celdas en la GPU de la nube).

**Estado:** ✅ instalado y **registrado en Claude Code** (`~/.claude.json`, scope user). `claude mcp list`
lo muestra **✔ Connected**.
- Repo clonado: `C:/Users/Tomanquito/colab-tools/colab-mcp`
- `uv` oficial: `C:/Users/Tomanquito/.local/bin/uv.exe` (v0.11.25)
- Comando registrado: `uv run --directory C:/Users/Tomanquito/colab-tools/colab-mcp colab-mcp`
- Tools (9): `open_colab_browser_connection`, `get_cells`, `add_code_cell`, `add_text_cell`,
  `run_code_cell`, `update_cell`, `delete_cell`, `move_cell`, `change_runtime` (GPU, requiere OAuth).

**Cómo usarlo (lo que hace el dueño):**
1. **Reiniciá Claude Code** una vez (para que cargue los tools del MCP en la sesión).
2. Abrí una notebook en Colab en el navegador (logueado, runtime T4).
3. Pedile al agente que se conecte (`open_colab_browser_connection`) y maneje las celdas. A partir de ahí
   el agente corre G2/entrenamientos en la GPU directamente.
- **Control de GPU sin tocar el navegador** (`change_runtime` → T4/L4/A100): requiere OAuth de una sola vez
  (proyecto GCP + OAuth client desktop, ~5 min). Pasos en el README del fork (`colab-tools/colab-mcp/README.md`,
  sección "Full Setup (With OAuth + GPU Control)"). Sin OAuth, igual funcionan las 8 tools de notebook.

## 2. CLI oficial `google-colab-cli` (`colab`) — modo HEADLESS, ideal para entrenamientos largos

**Qué es:** herramienta de línea de comandos OFICIAL de Google para automatizar Colab sin navegador:
provisiona VMs (CPU/T4/L4/A100/TPU), corre scripts/notebooks, monta Drive, recupera resultados, termina.

**Estado:** ✅ instalado (`uv tool install google-colab-cli`, v0.6.0) → ejecutable `colab` en
`C:/Users/Tomanquito/.local/bin/colab.exe`.
- ⚠️ **Parche de Windows aplicado:** el CLI importaba `termios`/`tty` (módulos solo-Unix) al cargar →
  crasheaba en Windows. Guardé esos imports en
  `…/uv/tools/google-colab-cli/Lib/site-packages/colab_cli/console.py` (try/except ImportError). Ahora
  `colab version`/`--help` y todos los comandos headless funcionan; **sólo la consola TTY interactiva no
  está disponible en Windows** (no se necesita para automatización).
  - **OJO:** el parche vive en el dir del tool → un `uv tool upgrade google-colab-cli` lo BORRA. Si
    actualizás, re-aplicá el guard (o reportá el bug upstream). Alternativa robusta: correr el CLI bajo WSL
    (Linux, donde `termios` existe).

**Cómo usarlo (lo que hace el dueño — requiere login de Google, no automatizable por el agente):**
```powershell
# 1) AUTENTICAR EL CLI (flujo oauth2 copy-paste, NO necesita gcloud). Corré esto en una terminal
#    PowerShell normal (necesita que pegues un código interactivamente). NO crea ninguna VM:
colab --auth oauth2 whoami
#    -> imprime una URL; abrila, logueá con tu Google, copiá el CÓDIGO que te muestra, pegalo en la
#       terminal y Enter. Token cacheado en ~/.config/colab-cli/token.json (una sola vez).
#       Si imprime tu email/scopes = autenticado OK.
#    NOTA: 'colab auth' (sin --auth) es OTRA cosa: autentica la VM remota para GCP, no el CLI.
# 2) provisionar una VM con GPU T4 + correr G2:
colab new -s g2 --gpu T4
colab install -s g2 torch numpy
colab exec  -s g2 -f cognia_x/construccion/m0_g2_recall_colab.py
colab log   -s g2 -o g2_resultado.ipynb    # exportar el log/resultado
colab rm    -s g2                          # terminar la VM (libera la sesión)
```
Comandos: `colab <cmd> --help` para detalle. `colab pay` abre la página de compute units.

## Qué falta (lo tuyo, una sola vez)
- **MCP fork:** reiniciar Claude Code + (opcional) el OAuth GCP para `change_runtime`.
- **CLI:** correr `colab auth` (login de Google). Recién ahí el agente puede disparar `colab new/exec`.
- Ambos dependen de tu cuenta/cuotas de Colab (free vs Pro). Para entrenamientos LARGOS, recordá: el free
  muere a ~90 min idle / 12 h máx → el CLI headless + checkpoints es más robusto que el MCP de navegador.

## Recomendación por caso (cognia-x)
- **G2 / corridas cortas, interactivas:** MCP fork (yo manejo las celdas en vivo).
- **Entrenamiento largo (M3) / batch reproducible:** CLI headless (`colab new/exec/log/rm`) — sobrevive
  mejor y se scriptea; o Kaggle (sesiones 9-12 h más predecibles). Lo medido en G1 ya empuja el diseño a
  RAMA B (GQA denso), que reduce la presión de GPU.
