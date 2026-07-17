# Cognia — Installation Guide

## La via recomendada (PyPI)

```bash
pip install cognia-ai
cognia install-model     # GGUF 3B + llama-server + portero 0.5B + expertos LoRA -> ~/.cognia/
cognia                   # wizard en el primer uso, luego el REPL
```

Eso es todo: no requiere Ollama, ni compilador, ni GPU. `install-model` deja el
backend configurado en `~/.cognia/config.env` y `cognia doctor` verifica la
instalacion (incluido el backend GGUF).

Opcionales:

```bash
pip install "cognia-ai[semantic]"   # embeddings reales (sentence-transformers, ~2GB)
pip install "cognia-ai[tui]"        # interfaz TUI (textual)
cognia install-model --with-heavy-code   # especialista 7B de codigo (~4.7 GB, opt-in)
```

## Requirements

- Python 3.11 or 3.12
- ~4 GB RAM para el 3B (8+ GB si sumas el 7B opt-in)
- No GPU required; runs on CPU

---

## Desktop App (beta testers)

Download the pre-built installer for your platform — no git or Python required:

| Platform | Installer |
|----------|-----------|
| Windows 10/11 | [Download .exe](https://github.com/tomascomenta-blip/cognia_v2/releases/latest) |
| Linux | [Download .AppImage](https://github.com/tomascomenta-blip/cognia_v2/releases/latest) |
| macOS | Build from source (see below) |

**Windows:** SmartScreen may show a warning — click "More info" then "Run anyway".
The installer does not require administrator privileges by default.

**Linux:** `chmod +x CogniaDesktop-*.AppImage && ./CogniaDesktop-*.AppImage`

> Nota: los instaladores Desktop publicados son de una version anterior (era
> 3.2.x); el paquete de PyPI es la via al dia.

---

## Install desde el repo (desarrollo / stack swarm legacy)

### Windows

```powershell
git clone https://github.com/tomascomenta-blip/cognia_v2.git
cd cognia_v2
.\install.ps1
```

### Linux / macOS

```bash
git clone https://github.com/tomascomenta-blip/cognia_v2.git
cd cognia_v2
bash install.sh
```

The installer checks Python, installs dependencies, and creates `.env` from
`.env.example`. Estos scripts montan el stack de shards numpy/swarm (legacy);
para el backend recomendado corre igualmente `cognia install-model`.

## Manual install

```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env and fill in the required values
```

## Optional: Ollama (fallback legacy)

Ollama ya NO es prerequisito ni el backend de Cognia (el backend es
llama-server + GGUF via `cognia install-model`). Si defines `OLLAMA_URL` y no
hay backend GGUF vivo, algunos modulos lo usan como ultimo recurso.
