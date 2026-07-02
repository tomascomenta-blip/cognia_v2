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

## D2 — 2026-07-02 — G2: los 5 prompts nuevos, fijados antes de K1
00_DISENO.md §3-G2 exige 5 prompts nuevos "fijados antes de correr". Quedan congelados acá:
1. "Había una vez un niño que " (apertura de cuento)
2. "Un día, la pequeña Sofía encontró " (apertura de cuento)
3. "El agua es una sustancia que " (enciclopédico)
4. "Los planetas del sistema solar " (enciclopédico)
5. "Desde la ventana de mi casa se puede ver " (descriptivo)
(+ los 5 del precedente: "La historia de ", "El sol es ", "Los animales del bosque ",
"En la ciudad de Madrid ", "La ciencia estudia ")
