# FLOTA DE MICRO-EXPERTOS — plan pre-registrado

Pedido del dueño (2026-07-20): tras la vía de destilados, una flota GRANDE de
modelos diminutos (~0.8M params) expertos en cosas específicas, que ayuden al
decoding y a resolver tareas. "Finetunear muchos muchos."

Pre-registrado ANTES de entrenar, con gates y criterios de corte, porque el
precedente manda: BDraft murió por entrenar sin escala y el gate ahorró 60 h.

## El suelo físico (medido, no opinión)

Un DRAFT compatible con llama-server debe compartir el tokenizer de Qwen2.5
(vocab 151.936). Solo la embedding a dim 64 pesa 151936×64 ≈ **9.7M params**.
Conclusión: **no existe el draft de 0.8M** con este vocab. La flota tiene dos
castas:

| casta | tamaño | para qué | cómo se enchufa |
|---|---|---|---|
| **micro-expertos de tarea** | ~0.8M reales (byte-level, vocab 256) | decisiones internas de Cognia (clasificar ideas, tipo de pregunta, idioma) | Python puro, CPU, <1 ms |
| **micro-drafts de dominio** | ~10-15M (vocab Qwen completo, dim 64-96) | drafting especulativo POR DOMINIO (código repetitivo, HTML, JSON) | `--spec-draft-model` en llama-server |

## Gates

- **G0 — baseline de drafting gratis.** Medir los `--spec-type ngram-*` de
  llama-server (drafters sin modelo). Si un ngram ya da ganancia en dominio
  repetitivo, el listón de los micro-drafts sube: deben superarlo.
- **G1 — primer micro-experto de tarea.** Entrenar el clasificador de ideas
  (web / módulo python / script terminal, ~0.8M). PASA si: ≥95% en held-out
  sintético Y ≥ la heurística `_es_idea_web` sobre el golden set real (los
  casos de `test_deteccion_idea_web`). Si pasa, se integra como SEGUNDA
  opinión detrás de la heurística (nunca la reemplaza sin A/B).
- **G2 — flota de tarea (N=5-10).** Solo si G1 pasa. Un experto por decisión
  interna donde exista baseline medible: tipo de pregunta (prompt_optimizer),
  idioma (adaptive_prompt), ¿pide gráfico? (vista), ruta de modelo
  (model_router). Cada uno con su metrics.json y su gate individual.
- **G3 — primer micro-draft de dominio (~10M).** Entrenar sobre corpus de UN
  dominio (el HTML generado por el propio pipeline + patrones). PASA si la
  aceptación como spec-draft en ese dominio ≥ la del 0.5B genérico (62-83%
  medido hoy) o los tokens/s superan al ngram de G0. KILL si tras 2 corridas
  no acerca — el 0.5B ya existe y es gratis.
- **G4 — flota de drafts.** Solo si G3 pasa. Un draft por dominio de trabajo
  real (python-cognia, html-dashboard, json-config).

## KILL pre-registrado

- Task-expert que no supere a su heurística baseline en 2 intentos → fuera
  (la heurística es gratis y legible).
- Micro-draft que no alcance al 0.5B en su propio dominio en 2 corridas →
  fuera (el 0.5B ya está en disco).
- La flota NUNCA reemplaza silenciosamente: cada experto entra como segunda
  opinión con log de discrepancias hasta acumular evidencia.

## Registro

- Modelos y métricas en `cognia/microexpertos/<nombre>/` (model.pt,
  config.json, metrics.json).
- Runner de flota: `scripts/entrenar_flota.py` — declarativo, entrena los
  pendientes, no re-entrena los que pasaron su gate.
- Cada corrida se anota en MANAGER_LOG.
