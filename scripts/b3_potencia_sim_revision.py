# -*- coding: utf-8 -*-
"""Potencia REAL del diseno REP vs BoN, simulada desde lcb_hard_r2.json."""
import json, random
from collections import defaultdict

d = json.load(open(r'C:/Users/usuario/Desktop/cognia_v2/b3_codigo/lcb_hard_r2.json', encoding='utf-8'))
K = d['k']
por = defaultdict(list)
for m in d['muestras']:
    por[m['tarea']].append(m)
TAREAS = [sorted(v, key=lambda m: m['s']) for v in por.values() if len(v) == K]
print('tareas hard con k=%d: %d' % (K, len(TAREAS)))

def lite(m):
    return {'pasa_vis': m['pasa_vis'], 'vis_ok': m['vis_ok'],
            'pasa_oc': m['pasa_oc'], 'inst': bool(m['instrumento'])}

TAREAS = [[lite(m) for m in v] for v in TAREAS]

def selector(pool):
    return sorted(range(len(pool)),
                  key=lambda i: (not pool[i]['pasa_vis'], -pool[i]['vis_ok'], i))[0]

def cadena(base, raiz, rng, rho, k):
    pool = [raiz]
    for _ in range(k - 1):
        if rho and rng.random() < rho:
            c = {'pasa_vis': True, 'vis_ok': 99, 'pasa_oc': True, 'inst': False}
        else:
            c = rng.choice(base)
        pool.append(c)
        if c['pasa_vis']:
            break
    return pool

INST_IID = 0.0   # si >0, el instrumento se sortea iid POR GENERACION (modelo del revisor)
ROMPE = 0.0      # prob. de que la reparacion ROMPA (pasa visibles, falla oculto)
NGEN = []

def cadena2(base, raiz, rng, rho, k):
    pool = [raiz]
    for _ in range(k - 1):
        u = rng.random()
        if rho and u < rho:
            c = {'pasa_vis': True, 'vis_ok': 99, 'pasa_oc': True, 'inst': False}
        elif rho and ROMPE and u < rho + ROMPE:
            c = {'pasa_vis': True, 'vis_ok': 99, 'pasa_oc': False, 'inst': False}
        else:
            c = rng.choice(base)
        pool.append(c)
        if c['pasa_vis']:
            break
    return pool

def una_corrida(N, rho, rng, k=K):
    difs = []; n_lim = 0; n_tie = 0
    for _ in range(N):
        base = rng.choice(TAREAS)
        raiz = rng.choice(base)
        gens = [raiz]
        if raiz['pasa_vis']:
            dif = 0; n_tie += 1
        else:
            pbon = cadena2(base, raiz, rng, 0.0, k)
            prep = cadena2(base, raiz, rng, rho, k)
            ppla = cadena2(base, raiz, rng, 0.0, k)
            gens = gens + pbon[1:] + prep[1:] + ppla[1:]
            dif = int(prep[selector(prep)]['pasa_oc']) - int(pbon[selector(pbon)]['pasa_oc'])
        NGEN.append(len(gens))
        if INST_IID:
            sucia = any(rng.random() < INST_IID for _ in gens)
        else:
            sucia = any(g['inst'] for g in gens)
        if sucia:
            continue
        n_lim += 1
        difs.append(dif)
    return difs, n_lim, n_tie

def sign_una_cola(difs, reps, rng):
    obs = sum(difs)
    nz = [x for x in difs if x]
    if not nz:
        return 1.0
    ge = 0
    for _ in range(reps):
        s = sum(x if rng.random() < 0.5 else -x for x in nz)
        if s >= obs:
            ge += 1
    return ge / reps

def potencia(N, rho, R=400, k=K, seed=1):
    rng = random.Random(seed)
    rech = 0; efectos = []; disc = []; lim = []
    for _ in range(R):
        difs, n_lim, n_tie = una_corrida(N, rho, rng, k)
        p = sign_una_cola(difs, 2000, rng)
        obs = sum(difs)
        if obs > 0 and p < 0.05:
            rech += 1
        efectos.append(100.0 * obs / max(1, n_lim))
        disc.append(sum(1 for x in difs if x))
        lim.append(n_lim)
    return (rech / R, sum(efectos)/R, sum(disc)/R, sum(lim)/R)

import sys
def tabla(titulo):
    print('\n=== %s ===' % titulo)
    print('  N   rho   limpias  discord.  efecto_realizado  POTENCIA')
    for N in (70, 90):
        for rho in (0.0, 0.05, 0.10, 0.15, 0.20, 0.30):
            pw, ef, dc, lm = potencia(N, rho)
            print('%4d %5.2f %8.1f %9.1f %14.1f pts %9.1f%%' % (N, rho, lm, dc, ef, 100*pw))

tabla('A) instrumento como en los datos reales (por tarea)')
INST_IID = 0.079
tabla('B) instrumento iid 7.9%/generacion  <- el modelo del revisor (mas duro)')
print('\ngeneraciones por tarea: media %.2f  max %d' % (sum(NGEN)/len(NGEN), max(NGEN)))
NGEN.clear()
ROMPE = 0.10
tabla('C) iid 7.9%/gen  Y  la reparacion ROMPE el 10% de las veces (ruido simetrico)')
