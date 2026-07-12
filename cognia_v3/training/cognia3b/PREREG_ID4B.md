# PREREG — K1: adapter de identidad para Qwen3-4B-Instruct-2507 (FLEET-30 #20)

**CONGELADO ANTES DE CORRER (2026-07-12 ~00:20, corrida nocturna FLEET-30).**

## Hipótesis
El Qwen3-4B-Instruct-2507 (miembro nuevo del fleet, rol agente-v2/FC) tiene el
mismo gap de FORMATO/identidad que tenían el 3B y el portero: sin adapter
contesta como "Qwen" (G3 ≈ 0). Es EL tipo de gap donde el fine-tune paga
(2 positivas previas: accion G3 20/20, portero G3 0→95). La capacidad NO se
toca (5 negativas): SOLO identidad + formato general del e1_train.

## Método (receta E-GROK, idéntica a E-PORT salvo el modelo)
- Base: `Qwen/Qwen3-4B-Instruct-2507` fp16 en T4 (LoRA r16 all-linear,
  lr 3e-4, warmup 10% cosine, 1 epoch, SEQ 1024, MB 2, packing).
- Datos: `e1_train.jsonl` (general + identidad, dataset `cognia3b-emix`
  ya versionado en Kaggle; replay anti-olvido incluido en la mezcla).
- Eval PAREADA base-vs-adapter en las suites congeladas `g3_identidad`
  y `g1_general` (mismas del portero; sha en SUITES_FROZEN.json).

## Gates (congelados)
- **P-ID4B-1 (gate)**: G3 identidad ≥ 90% con adapter (McNemar pareado).
- **P-ID4B-2 (gate)**: G1 general SIN regresión significativa
  (McNemar p<0.05 en contra = FALLA).
- **P-ID4B-3 (info)**: loss estable sin NaN; wall < 3h.

## Regla de corte
Si P-ID4B-1 o P-ID4B-2 fallan: UN ajuste permitido (dataset o detector, no
el gate); segunda falla → la línea se cierra, el 4B queda en el fleet como
especialista SIN identidad (roles no conversacionales) y se documenta.

## Deploy si pasa
convert_lora_to_gguf → `cognia_id4b_f16.gguf` como LoRA ESTÁTICA del server
qwen3_4b (patrón portero: lora_path por instancia, NO fleet hot-swap del 3B)
+ asset al release fleet-v1 + entrada en fleet30.json.
