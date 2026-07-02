# XHUNDRED — Desvíos del pre-registro (append-only, nunca editar 00_DISENO.md)

## D1 — 2026-07-02 — G4 (mini-cloze) sustituido por batería ya medida
**Qué dice 00_DISENO.md §3-G4:** 40 pares de 2 alternativas (azar 50%), gate ≥75%.
**Desvío:** en paralelo a la síntesis del diseño se codificó `xh_cloze_es.py`: 40 ítems de
3 opciones (azar 33.3%; concordancia 12 / conocimiento 12 / semántica 10 / sintaxis 6) y se midió
el BASELINE en el precedente 37.7M byte-level (xfinal_model.pt):
**total 62.5% — concordancia 75.0%, conocimiento 58.3%, semántica 50.0%, sintaxis 66.7%.**
**Resolución:** G4 pasa a ser la batería de 3 opciones YA ANCLADA con medición real:
`G4 = cloze-es total ≥ 65% (26/40; azar 33.3%; el precedente 37.7M marca 62.5%)`.
Stretch: ≥75%. Razón: un gate calibrado contra un baseline MEDIDO del propio repo es más fuerte
que un umbral inventado sobre una batería sin baseline. La batería queda CONGELADA en
`xh_cloze_es.py` (commiteada antes de K1; no se toca después de ver resultados del 100M).

## D3 — 2026-07-02 — El check de sanidad "loss inicial ≈ ln(V)=10.40±0.3" estaba mal derivado
**Medido en K1v2 (T4):** loss inicial = 14.95, no 10.4. **Causa raíz (analítica, verificada
contra el número):** con ZERO-init de o_proj/w3 los bloques son identidad al inicio → el stream
residual llega a norm_f siendo el embedding puro del token de ENTRADA; con head TIED, el logit
de esa clase vale ≈ ‖e‖²/RMS(e) = 768·0.02 ≈ +15.4 mientras el resto queda ~N(0, 0.55) → CE ≈
logsumexp ≈ 15.4 ("prior de copiar el input", que no es el target). **Resolución:** se acepta y
documenta — es un artefacto benigno de la combinación zero-init+tied (el loss cayó 14.95→5.92 en
~110 steps en el mismo run); el check de sanidad pasa a ser "loss inicial ∈ [10, 16] y cae por
debajo de ln(V) antes del step 200". No se cambia la receta (untie costaría +25.2M params).

## D4 — 2026-07-02 — CE chunked: la versión del diseño no ahorraba memoria (OOM real en T4)
§4.4 asumía "logits 32k nunca materializados enteros" con el loop de 4 chunks. FALSO como estaba
escrito: autograd retiene los 4 chunks fp32 (~4.8GB a b48) hasta el backward → OOM en cascada en
K1v2 (13.08GB pico, b64/b32/parity muertos; el caché de dynamo además retiene VRAM tras un OOM).
**Resolución:** torch.utils.checkpoint por chunk (1 chunk vivo a la vez; +7% FLOPs del head por
el recompute), PYTORCH_ALLOC_CONF=expandable_segments, hard_cleanup() (dynamo reset+gc+empty)
entre brazos, compile fullgraph=False, paridad a b16. El presupuesto de memoria de §4.4 queda
corregido por la medición real.

## D2 — 2026-07-02 — G2: los 5 prompts nuevos, fijados antes de K1
00_DISENO.md §3-G2 exige 5 prompts nuevos "fijados antes de correr". Quedan congelados acá:
1. "Había una vez un niño que " (apertura de cuento)
2. "Un día, la pequeña Sofía encontró " (apertura de cuento)
3. "El agua es una sustancia que " (enciclopédico)
4. "Los planetas del sistema solar " (enciclopédico)
5. "Desde la ventana de mi casa se puede ver " (descriptivo)
(+ los 5 del precedente: "La historia de ", "El sol es ", "Los animales del bosque ",
"En la ciudad de Madrid ", "La ciencia estudia ")
