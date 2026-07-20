# exp003 - resultados (inexactitud del FedAvg de LoRA)

- numpy 2.4.6 | m=n=256 | r=8 (=_RANK_MAX de Cognia) | trials=20 | seed=11
- **Sanity (heterogeneidad 0 -> error 0):** rel_error = 0.00e+00

## Error relativo vs heterogeneidad de clientes (K=4)
| heterogeneidad | error relativo Frobenius | rango efectivo exacto | rango efectivo ingenuo |
|---|---|---|---|
| 0.0 | 0.0000 | 8 | 8 |
| 0.1 | 0.0043 | 32 | 8 |
| 0.25 | 0.0268 | 32 | 8 |
| 0.5 | 0.1008 | 32 | 8 |
| 1.0 | 0.3289 | 32 | 8 |
| 2.0 | 0.6565 | 32 | 8 |

## Error relativo vs numero de clientes (heterogeneidad=0.5)
| K clientes | error relativo Frobenius |
|---|---|
| 2 | 0.1109 |
| 3 | 0.1078 |
| 4 | 0.1006 |
| 8 | 0.0795 |
| 16 | 0.0595 |

