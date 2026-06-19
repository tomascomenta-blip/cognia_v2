# CYCLE 8 — Resultados: la IA aprende sin olvidar (aprendizaje continuo Nivel 1)

Demostración medible de que la IA híbrida **aprende un dominio nuevo sin olvidar los viejos**, con un
examinador independiente (held-out cross-book REAL, NO circular) que decide por-dominio si fijar o
revertir cada lección. Cierra el eje de H-SELF-2 (ver abajo).

## Resultado FULL (base d=128/4-capas, 4000 pasos, 4 dominios viejos)

Base sabe: inglés (Alice, Sherlock, Pride) + español. Aprende inglés nuevo (Frankenstein), examinado
en inglés hermano cross-book (Drácula). Aprender inglés DAÑA el español → adversario natural.

| brazo | nuevo Δ | español Δ | learned | **no_harm** | decisión |
|---|---:|---:|:---:|:---:|:---:|
| naive (sin gate) | +0.042 | **+1.217** | — | — | (olvido catastrófico) |
| B gate AGREGADO | +0.050 | +1.161 | False | **True** ⟵ ciego | rechaza |
| C gate POR-DOMINIO | +0.062 | +1.186 | False | **False** ⟵ atrapa | rechaza |
| **D por-dominio + replay** | **−0.030** | **+0.058** | **True** | **True** | **ACEPTA** ✓ |

**Lo que demuestra:**
1. **El gate AGREGADO es CIEGO.** Sobre el MISMO daño al español (~+1.17), el agregado dice
   `no_harm=True` (promedio de los 4 viejos = +0.40 < umbral 0.81, el daño concentrado se diluye)
   mientras el por-dominio dice `no_harm=False` (español +1.19 > 0.81). El promedio esconde ~3× del
   daño. Esta es la causa que marcaba H-SELF-2 ❌false ("evaluador circular/agregado").
2. **El REPLAY resuelve las dos caras.** D aprende lo nuevo (Drácula −0.030) **y** protege el español
   (+0.058 vs naive +1.217 = **21× menos olvido**). El replay además ESTABILIZA el aprendizaje: naive
   (sin replay) desestabiliza incluso el dominio nuevo (+0.042); con replay aprende (−0.030).
3. **El examinador es NO circular** (held-out cross-book real) y la banda de incertidumbre (umbral =
   k·σ del propio examinador) evita aceptar/rechazar por ruido.

## Resultado SMOKE (base d=128, 600 pasos — régimen base-débil)
Confirmó el mecanismo cuando el aprendizaje nuevo SÍ transfiere: naive olvida español +0.96; el
agregado ve solo +0.25 (esconde 75%); **replay reduce el olvido 15×** (+0.86 → +0.058) aprendiendo
lo nuevo. (A base-fuerte, aprender otra obra del MISMO idioma no transfiere al hermano cross-book —
por eso en el full B/C dan `learned=False`; pero la DETECCIÓN del daño se demuestra igual de limpia.)

## Cierre de H-SELF-2 (de ❌false a ✅ condicional)
H-SELF-2 era ❌false "porque el evaluador de Cognia era CIRCULAR/agregado". Con un examinador
**held-out cross-book NO circular + gate POR-DOMINIO**, el olvido (deriva) **se detecta y se reduce
verificablemente** (gate por-dominio atrapa lo que el agregado esconde; replay protege 15-21×). →
H-SELF-2 condicional: el gate+rollback held-out SÍ reduce deriva **si el evaluador no es circular y
es por-dominio**.

## Caveats (honestidad)
- Modelo chico (779k params), corpus de libros, semilla única — resultado sobre el MECANISMO, no escala.
- A base-fuerte el aprendizaje de una obra del mismo idioma no transfiere cross-book (B/C learned=False);
  el smoke (base-débil) muestra el lado de "aprender". Combinados cubren detección + protección + aprendizaje.
- Umbrales (k·σ, eps de la zona ciega) calibrados para la demo; a escala hay que recalibrarlos multi-seed.

Reproducir: `python -m cognia_x.learn.run_cycle8` (full) / `--smoke` (rápido). Datos: `runs/cycle8/`.
