# exp005 - frontera coste<->recall del backbone hibrido (eje COSTE)

- numpy 2.4.6 | m=24 capas | d=128 | reps=80 | seed=7
- Capa FULL: O(L*d), lee KV-cache (L,d) -> crece con L.
- Capa LINEAL: O(d^2), estado fijo (d,d) -> constante en L.
- **El recall se toma de exp002** (full ~ilimitado en N; lineal acotado por d^2).

## ms/token por (k, L)

| k (full/24) | L=512 | L=2048 | L=8192 |
|---|---|---|---|
| 0 | 0.4445 | 0.4778 | 0.4917 |
| 1 | 0.5620 | 0.8289 | 3.1356 |
| 3 | 0.6766 | 1.6927 | 5.0995 |
| 6 | 1.3507 | 2.7460 | 10.6525 |
| 12 | 2.0925 | 5.1176 | 19.8361 |
| 24 | 2.3917 | 9.9090 | 41.0395 |

## pct_of_pure_full = ms(k,L)/ms(24,L)*100

| k (full/24) | L=512 | L=2048 | L=8192 |
|---|---|---|---|
| 0 | 18.6% | 4.8% | 1.2% |
| 1 | 23.5% | 8.4% | 7.6% |
| 3 | 28.3% | 17.1% | 12.4% |
| 6 | 56.5% | 27.7% | 26.0% |
| 12 | 87.5% | 51.6% | 48.3% |
| 24 | 100.0% | 100.0% | 100.0% |

