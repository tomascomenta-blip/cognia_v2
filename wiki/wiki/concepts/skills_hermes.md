---
title: Skills + HERMES — self-tooling con validacion
type: concept
tags: [skills, hermes, self-tooling, decay, sandbox]
updated: 2026-07-16
---

# Skills + HERMES

→ [[index]]

## Skills

`cognia/agent/skills.py` (SkillSpec, load_skills, record_skill_use con
decay) + `skill_capture.py`. Skills .md en cognia/skills/ (commit-git,
depurar, documentar, escribir-tests, revisar-codigo). Matching por
similitud semantica CALIBRADA empiricamente (umbral 0.35 matcheaba
cualquier cosa en espanol → re-calibrado 0.48; la leccion motivo las
reglas LEXICAS del [[entities/fleet_registry]]).

## HERMES (self-tooling)

Ciclo de auto-mejora: `record_wanted_tool` (background_research.py)
registra herramientas DESEADAS durante el uso → tool `crear_herramienta`
(tools.py) genera la herramienta EN VIVO → validacion OBLIGATORIA antes
de registrarla: scan estatico de imports (allowlist) + sandbox con
timeout + rollback + repair-on-live-failure. Regla del repo: nada
auto-generado se vuelve ejecutable sin pasar la verificacion (el RCE de
`__builtins__.eval` se cerro en la corrida 2026-07-03).

## Links

- [[entities/agente]]
- [[synthesis/security_model]]
