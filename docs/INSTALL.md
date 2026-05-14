# Cognia — Installation Guide

## Download (recommended for beta testers)

Download the pre-built installer for your platform — no git or Python required:

| Platform | Installer |
|----------|-----------|
| Windows 10/11 | [Download .exe](https://github.com/tomascomenta-blip/cognia_v2/releases/latest) |
| Linux | [Download .AppImage](https://github.com/tomascomenta-blip/cognia_v2/releases/latest) |
| macOS | Build from source (see below) |

**Windows:** SmartScreen may show a warning — click "More info" then "Run anyway".
The installer does not require administrator privileges by default.

**Linux:** `chmod +x CogniaDesktop-*.AppImage && ./CogniaDesktop-*.AppImage`

**Prerequisites for all platforms:** [Ollama](https://ollama.ai) must be installed and running.
After installing Ollama: `ollama pull llama3.2`

---

## Requirements

- Python 3.11 or 3.12
- 2 GB RAM minimum (4 GB recommended with Shattering)
- No GPU required; runs on CPU

## Quick install (recommended)

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

The installer checks Python, installs dependencies, and creates `.env` from `.env.example`.

## Manual install

```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env and fill in the required values
```

## Optional: Ollama (LLM backend)

Cognia uses Ollama for natural-language responses. Without it, responses fall back to symbolic mode.

1. Download from https://ollama.ai
2. Pull the required models:

```bash
ollama pull llama3.2
ollama pull qwen2.5-coder
```

3. Set `OLLAMA_URL=http://localhost:11434` in `.env`

## Verify installation

```bash
python scripts/cognia_doctor.py
```

All items should show `[OK]`. Ollama items show `[WARN]` if not installed (non-blocking).

## Starting the CLI

```bash
python -m cognia
```

## Starting the web API

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Starting the Desktop app (Electron)

```bash
cd cognia_desktop
npm install
npm start
```

## Environment variables

Copy `.env.example` to `.env` and configure:

| Variable | Required | Description |
|----------|----------|-------------|
| `OLLAMA_URL` | No | Ollama server URL (default: `http://localhost:11434`) |
| `COGNIA_COORDINATOR_URL` | No | Coordinator URL for distributed mode |
| `COORDINATOR_KEY` | Production | Admin key for coordinator endpoints |
| `COGNIA_ADMIN_KEY` | No | Key for `/api/user/data/*` endpoints |
| `COGNIA_ENCRYPT_PASSPHRASE` | No | Passphrase for DB column encryption |
| `PORT` | No | Web API port (default: 8000) |

## Updating

```bash
python scripts/cognia_update.py
```

Or from the CLI:

```
Cognia v3> update
```

This pulls the latest code, upgrades dependencies, and applies any DB schema migrations.
