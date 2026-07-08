# E2-FINAL-v2 — receta E-GROK: recupera G1 (predicción central ✓) pero NO APTO por G5 (1 ítem)

Kaggle 1×T4, 93.3 min (2.7× más barato que v1: replay cacheado + 1 epoch).
Receta: mezcla única D1×3 idéntica a v1, **1 epoch + lr 3e-4 + warmup 10%**
(E-GROK), 311 steps @502.8 tok/s, loss 1.351→1.252, sin NaN.

## Veredicto contra el pre-registro (McNemar pareado vs base, suites congeladas)

| Gate | pre-registro | base | cognia3b_v2 | delta | p | veredicto |
|---|---|---|---|---|---|---|
| G3 identidad (20) | ≥18/20 | 0% | **95%** (19/20) | +95pp | 0.0 | **PASA** |
| G1 general (100) | ≥85% | 89% | **85%** | −4pp | 0.34 (n.s.) | **PASA** (v1: 81% FALLÓ) |
| G5 español (25) | ≥60% | 60% | **56%** (14/25) | −4pp | 1.0 (n01=3,n10=4) | **FALLA por 1 ítem** |
| G2A ACCION (147) | ≥95% | 20.4% | **98%** | +77.6pp | ~0 | **PASA** (mejor que v1: 96.6%) |

**`APTO_PARA_E5: false`** — regla "pasa todo". Predicciones: **3/4 confirmadas**.

## Lectura honesta

- **P-V2-2 (la central) CONFIRMADA**: mitad de exposición (1 epoch) con lr
  3e-4+warmup recupera G1 de 81%→85% manteniendo el grokking de identidad
  (G3 19/20). La palanca del olvido ES la exposición total; el lr alto compra
  la identidad sin pagar en G1 (n10=7 vs 10 de v1, ya no significativo).
- **G5 falla por UN ítem** (14/25 vs 15/25) con p=1.0 y discordantes 3↔4:
  esto es el PISO DE RUIDO del gate (N=25). No hay señal de regresión real;
  hay un gate binario apoyado sobre una suite chica.
- **G2A 98%** — el mejor número ACCION de todo el programa (v1: 96.6%).

## Decisión de arquitecto: línea "checkpoint único" CERRADA

Dos corridas colapsadas, cada una falla UNA compuerta distinta en el borde
(v1: G1 −8pp real; v2: G5 −1 ítem ruido). Mientras tanto el FLEET ya está
desplegado y MEDIDO mejor que el CLI anterior (GATES_CLI_VNEXT.md) sin
necesitar el checkpoint único: la base pura atiende G1/G5 (sin regresión
posible) y el experto atiende ACCION/identidad. Insistir con un v3 para
flippear 1 ítem de G5 sería cazar ruido, no señal. Se cierra con:

1. **v2 compite con v1 por el puesto de EXPERTO del fleet** (donde G1/G5 no
   juegan): se decide con G4 en el deploy real (results_g4_e5_cognia3b_v2.json)
   — regla: promover v2 si mejora G2A+G3 agregado en deploy sin regresión
   significativa vs v1.
2. La receta E-GROK queda VALIDADA a escala corpus-completo como la receta
   del fleet (93 min/experto, G2A 98%): es la que usarán los próximos
   expertos (razonamiento, código).
3. Si algún día se necesita el checkpoint único: subir N de G5 (25→100) para
   sacar el gate del piso de ruido ANTES de gastar otra corrida.
