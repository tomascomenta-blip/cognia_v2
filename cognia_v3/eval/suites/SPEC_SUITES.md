# SPEC — Suites held-out de los gates COGNIA 3B (P0-ii, DC-10)

Referencia normativa: `cognia_v3/training/cognia3b/TEORIA_COGNIA3B.md` Parte 3 §3.3.
Estas suites se CONGELAN POR HASH en git antes de la primera corrida de E1 y no se
usan jamás para tuning ni selección de checkpoints. Scoring por oráculo determinista
BINARIO por ítem (McNemar necesita binario), decodificación greedy/temp 0.

## Formato (JSONL, un ítem por línea)

```json
{"id": "G1-RZ-001", "gate": "G1", "dominio": "razonamiento", "idioma": "es",
 "shots": 0, "prompt": "...texto completo que ve el modelo...",
 "oracle": {"must_all": ["palabra1"], "must_any": ["si", "sí"], "not_any": ["xyz"], "number": null},
 "max_new_tokens": 200}
```

- `prompt`: texto COMPLETO (si `shots`=3, los 3 ejemplos van dentro del prompt).
- `oracle` (todas las claves opcionales; el ítem PASA si TODAS las restricciones
  presentes se cumplen sobre la respuesta foldeada — `fold()` = lowercase + sin
  acentos, patrón de `train_qlora_kaggle.py:121-129`):
  - `must_all`: todas estas strings presentes.
  - `must_any`: al menos una presente.
  - `not_any`: ninguna presente.
  - `number`: el ÚLTIMO número de la respuesta == este valor (tolerancia 1e-6;
    para respuesta exacta de matemática).
- `idioma`: es|en. Ítems G5 además exigen respuesta EN español (langid, criterio
  aparte del runner, no va en el oracle).

## Composición pre-registrada

| Archivo | Gate | N | Composición |
|---|---|---|---|
| `g1_general.jsonl` | G1 | 100 | 25 razonamiento (13 es / 12 en), 25 factual (13 es / 12 en), 25 código (leer/predecir/escribir, oráculo por keywords del output esperado — NO ejecución), 25 seguir-instrucciones/formato. **20 de los 100 con `shots`=3** (los few-shot cazan la fijación de modo, lección MGSM −15.2). |
| `g2_razonamiento.jsonl` | G2R | 100 | matemática aritmética/álgebra simple/porcentajes/proporciones (60, oráculo `number`), lógica deductiva/silogismos/orden (40, oráculo keywords). 50 es / 50 en. Dificultad: resoluble por un buen 3B CON esfuerzo (ni trivial ni imposible: apuntar a que la base acierte ~40-60%). |
| `g3_identidad.jsonl` | G3 | 20 | "¿quién sos?", "¿quién te creó?", "¿cómo te llamás?", "what's your name?", variantes directas e indirectas, 12 es / 8 en. Oracle: `must_any: ["cognia"]`, `not_any: ["qwen", "alibaba"]`. |
| `g5_espanol.jsonl` | G5 | 25 | solo-español: 10 instrucciones, 8 cloze estilo XStoryCloze (elegir final coherente A/B → oracle keywords de la opción correcta), 7 QA. |

## Reglas de autoría (anti-ambigüedad)

1. Cada ítem debe tener UNA respuesta claramente correcta; un humano competente
   debe responder igual el 100% de las veces.
2. El oracle debe ACEPTAR las formulaciones razonables de la respuesta correcta
   (sinónimos en must_any) y RECHAZAR una respuesta incorrecta plausible.
   Pensar SIEMPRE: "¿qué respondería un modelo que NO sabe? ¿pasaría el oracle?".
3. Keywords cortas y robustas al parafraseo; nunca frases largas literales.
4. Nada de conocimiento posterior a 2024 (las bases son de 2024-2025).
5. Nada copiado de benchmarks públicos famosos (GSM8K, MMLU, ARC...) — riesgo de
   contaminación del pretraining de la base: redactar ítems ORIGINALES.
6. Ítems 3-shot: los shots son ejemplos CORRECTOS de otros ítems del mismo dominio
   (no de la suite), formato "Pregunta: ...\nRespuesta: ...".
7. Los ítems no deben aparecer en ningún JSONL de entrenamiento del repo
   (se verifica con el script de descontaminación antes del freeze).
