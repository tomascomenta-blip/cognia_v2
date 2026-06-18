# Cognia-X

**Laboratorio experimental de rediseño de IA desde primeros principios.**

Pregunta raíz: *si hoy rediseñáramos una IA desde cero usando todo el conocimiento moderno,
¿qué construiríamos — y por qué, con evidencia?*

Cognia-X es **independiente** de Cognia: no reutiliza su pipeline ni hereda su arquitectura.
Aquí no se acepta ninguna pieza por autoridad (ni Transformer, ni Mamba, ni RWKV, ni MoE):
cada componente justifica su existencia con evidencia y experimentos reproducibles, o se
reemplaza.

## Estructura

```
cognia_x/
  README.md                     <- este archivo
  manager/                      <- documentación viva (constitución + estado)
    00_protocolo_investigacion.md   meta-prompt mejorado (constitución operativa)
    _prompt_original.md             prompt fundacional literal (histórico)
    paper.md                        paper científico vivo
    roadmap.md                      fases y estado
    research_log.md                 bitácora append-only
    architecture.md                 arquitectura propuesta + justificación
    experiments.md                  fichas de experimentos
    assumptions.md                  supuestos con estado
    hypotheses.md                   hipótesis + evidence ledger
    future_work.md                  direcciones futuras
    decision_log.md                 decisiones con fecha y razón
  experiments/                  <- código + resultados reproducibles
    expNNN_*/run.py + results/
```

## Cómo correr un experimento

Usar siempre el venv que funciona (Python 3.12):

```
.\venv312\Scripts\python.exe cognia_x\experiments\exp001_sequence_mixing_scaling\run.py
```

Cada experimento fija semilla, declara entorno y guarda su salida en `results/`.

## Prioridades (orden estricto)

1. Eficiencia computacional · 2. Aprendizaje continuo · 3. Adaptabilidad ·
4. Creatividad · 5. Razonamiento · 6. Escalabilidad.

Hardware objetivo: **CPU de portátil, sin GPU.** GPU/clúster son optimización futura.

## Modelo v0 (la IA "desde cero")

La arquitectura del ciclo-1 hecha código, en PyTorch CPU:
- `model/hybrid.py` — modelo **híbrido**: mayoría de capas de mezcla **lineal** (estado fijo, O(L))
  + minoría de **atención sliding-window** (ratio ~3:1), RMSNorm + SwiGLU + lm_head atado,
  **byte-level** (vocab 256). Decisiones: ver `manager/decision_log.md` D-007/D-013.
- `train/recall_task.py` — entrena lineal-puro vs híbrido vs atención-pura en recall asociativo
  (cierra el eje recall de H-MEZ-4 end-to-end).
- `train/charlm.py` — byte-LM sobre el texto local del repo (demuestra que aprende lenguaje).
- `train/run_overnight.py` — orquesta ambas fases con deadline + checkpoints.

Correr el entrenamiento (CPU):
```
.\venv312\Scripts\python.exe -m cognia_x.train.run_overnight --smoke          # verificación ~3 min
.\venv312\Scripts\python.exe -m cognia_x.train.run_overnight --deadline <epoch>  # corrida real
```
Salidas en `runs/overnight_v0/` (gitignored): `recall_results.json`, `charlm_best.pt`,
`charlm_samples.txt`, `run.log`, `summary.json`.

## Empezar aquí (para una sesión nueva)

1. Leer `manager/00_protocolo_investigacion.md` (reglas del juego).
2. Leer las últimas entradas de `manager/research_log.md` y `manager/roadmap.md`.
3. Revisar `manager/hypotheses.md` (qué está abierto) y continuar el ciclo.
4. **Si hay un entrenamiento corrido:** leer `runs/overnight_v0/` (resultados de recall + char-LM).
