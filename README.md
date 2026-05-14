# Cognia v3 — Arquitectura Cognitiva Simbolico-Neural

> IA local, ligera, sin APIs externas. Corre en CPU. Objetivo: 2-5W de consumo.
> Ahora con inferencia distribuida real (SRDN) y soporte Qwen2.5-Coder.

**Stack:** Python 3.11+ · SQLite · Qwen2.5-Coder (INT4) · sentence-transformers · numpy · FastAPI · Electron

---

## Estado del proyecto (Mayo 2026)

| Fase | Estado | Descripcion |
|------|--------|-------------|
| **Fase 1-6 — Estabilizacion y Core** | COMPLETADA | Base limpia, NarrativeThread, MeshNode, Seguridad, Escalado. |
| **Fase 7 — Shattering (SRDN)** | COMPLETADA | LOGOS/TECHNE/RHETOR sub-models, MoE, NPQ, RST, MLA. |
| **Fase 8 — Commercial Release** | COMPLETADA | Instaladores, UX, Cifrado por defecto, Documentacion completa. |
| **Fase 9-12 — Hardening y UX** | COMPLETADA | Proteccion SQLi/XSS/SSRF, Consentimiento de privacidad, Auto-update. |
| **Fase 13 — Real Distributed Inference** | COMPLETADA | Inferencia real con Qwen2.5-Coder-3B INT4, auto-sharding. |

Ver [ROADMAP.md](ROADMAP.md) para el detalle tecnico de cada fase.

---

## Que hace Cognia

Cognia es una arquitectura cognitiva que aprende, razona y recuerda localmente. A diferencia de un simple chatbot, gestiona un ciclo de vida cognitivo completo incluyendo consolidacion de memoria durante el "sueño" y razonamiento distribuido entre multiples dispositivos.

### Arquitectura Shattering (SRDN)

Cognia v3 introduce **Sparse-Recursive Distillation Network**, permitiendo correr modelos de 3B+ parametros en dispositivos con poca RAM (Android, PCs antiguos) mediante:
- **Auto-sharding:** El modelo se divide en fragmentos (shards) que pueden ejecutarse en distintos nodos de una red local.
- **Cuantizacion INT4:** Pesos comprimidos un 75% sin perdida critica de precision, operados puramente en numpy.
- **Inferencia hibrida:** Combina Ollama (para razonamiento general) con el motor nativo de Cognia (para tareas especializadas).

### Modulos Principales

| Modulo | Funcion |
|--------|---------|
| `KnowledgeGraph` | Memoria semantica estructurada y jerarquica. |
| `InferenceEngine` | Razonamiento transitivo y herencia de propiedades. |
| `ShatteringOrchestrator` | Gestion de inferencia distribuida y ruteo MoE. |
| `ConsolidationEngine` | Ciclo de sueño: purga, refuerzo y olvido de memorias. |
| `SecureStorage` | Cifrado AES-256-GCM de memorias episodicas. |
| `CogniaMeshNode` | Red P2P para sincronizacion de conocimiento via CRDT. |

---

## Descarga e Instalacion

### Instaladores rapidos

Recomendado para la mayoria de los usuarios. Descarga el repositorio y ejecuta:

**Windows (PowerShell):**
```powershell
.\install.ps1
```

**Linux / macOS (Bash):**
```bash
bash install.sh
```

### Desktop App (Electron)

Para una experiencia visual, puedes construir el instalador de escritorio:
```bash
cd cognia_desktop
npm install
npm run build:win  # o build:linux / build:mac
```

---

## Uso — Comandos Principales

### Cognicion y Memoria
- `aprender <texto> | <etiqueta>`: Enseñar un concepto nuevo.
- `observar <texto>`: Guardar una observacion sin procesar.
- `dormir`: Iniciar ciclo de consolidacion y limpieza (sueño).
- `yo`: Ver estado interno de la memoria y perfil cognitivo.
- `narrativa <texto>`: Recuperar hilos de episodios relacionados.

### Sistema y Red
- `doctor`: Diagnostico completo del sistema y dependencias.
- `update`: Actualizar Cognia, dependencias y migraciones de DB.
- `seguridad`: Gestionar cifrado y llaves de acceso.
- `grafo <concepto>`: Visualizar el grafo de conocimiento local.
- `inferir <concepto>`: Ejecutar razonamiento transitivo sobre un tema.

### Inferencia Distribuida (Qwen2.5)
```bash
# Convertir pesos de HuggingFace a shards de Cognia
python scripts/convert_hf_to_shards.py --hf-dir /path/to/qwen --out-dir model_shards/qwen-q4
```

---

## Seguridad y Privacidad

- **Local-First:** Tus datos nunca salen de tu maquina a menos que conectes nodos en red mesh de forma explicita.
- **Cifrado en reposo:** Memorias episodicas cifradas con AES-256-GCM.
- **Proteccion Anti-Injection:** Filtros estructurales en prompts y consultas SQL parametrizadas.
- **Privacidad Diferencial:** Ruido estadistico aplicado en sincronizaciones de red para proteger la identidad.

Ver [docs/PRIVACY.md](docs/PRIVACY.md) y [docs/SECURITY.md](docs/SECURITY.md) para mas detalles.

---

## Documentacion

| Documento | Contenido |
|-----------|-----------|
| [docs/INSTALL.md](docs/INSTALL.md) | Guia detallada de instalacion y configuracion. |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Solucion a problemas comunes y diagnostico. |
| [docs/PRIVACY.md](docs/PRIVACY.md) | Detalles sobre el manejo de datos y privacidad. |
| [ROADMAP.md](ROADMAP.md) | Plan de desarrollo y estado de las fases. |

---

## Para Colaborar

Lee el [ROADMAP.md](ROADMAP.md) para entender la direccion actual. Cognia prioriza la eficiencia (CPU-only), la privacidad y la estabilidad. No se aceptan dependencias pesadas (PyTorch/Tensorflow) en el motor de inferencia principal.

---
© 2026 Cognia Project. Distribuido bajo licencia MIT.
