"""
cognia_x/lcd/physics.py — FISICA local determinista para la escena LCD.

Hace que la escena estructurada sea FISICAMENTE PLAUSIBLE sin motor pesado ni
GPU: gravedad (los objetos se asientan sobre su soporte, no flotan), soporte/
apilamiento (un objeto descansa sobre el de abajo si se solapan en x), colision
(no se interpenetran horizontalmente), plano de suelo, y una prueba de
ESTABILIDAD (el centro de un objeto debe caer sobre su base o se cae).

Es 2D, axis-aligned, iterativo y O(n^2) por paso (n = objetos; escenas chicas):
determinista (mismo input -> mismo output, sin random) y barato en CPU. NO
simula dinamica continua (velocidades/rebotes); "asienta" a un estado de reposo
plausible, que es lo que una herramienta de EDICION necesita (colocar bien las
cosas), no un simulador de juego.

Convencion de coordenadas (de scene.py): x,y en [0,1], y=0 arriba, y=1 abajo;
el "suelo" esta en y=GROUND (borde inferior). Un objeto 'descansa' cuando su
borde inferior toca el suelo o el borde superior de un soporte debajo.
"""
from __future__ import annotations

from cognia_x.lcd.scene import DENSITY, FLOATING, Scene

GROUND = 1.0            # borde inferior del canvas (el suelo)
_EPS = 1e-4
_MAX_ITERS = 60         # tope de iteraciones del asentamiento (converge mucho antes)


def _x_overlap(a, b) -> float:
    """Solapamiento horizontal [0,1] entre dos objetos (0 = no se tocan en x)."""
    left = max(a.x - a.w / 2, b.x - b.w / 2)
    right = min(a.x + a.w / 2, b.x + b.w / 2)
    return max(0.0, right - left)


def _density(o) -> float:
    return DENSITY.get(o.name, 1.0)


def _is_floating(o) -> bool:
    """Objetos de cielo/decorativos no caen (sol, nube, pajaro, ...)."""
    return o.name in FLOATING


def support_of(scene: Scene, o):
    """Devuelve el objeto SOBRE el que descansa `o` (el mas alto que esta
    debajo, se solapa en x lo suficiente y es una base VALIDA), o None si
    descansa en el suelo.

    Base valida: un objeto ANCHO no se apoya sobre uno mucho mas angosto (una
    mesa no descansa sobre un libro; el libro descansa sobre la mesa). Regla:
    el soporte debe tener al menos la mitad del ancho del objeto -> lo pesado/
    ancho cae al suelo y lo chico se apila encima, que es lo fisico."""
    best, best_top = None, GROUND
    for other in scene.objects:
        if other is o:
            continue
        if _is_floating(other):
            continue
        # 'other' es soporte si su cara superior esta por DEBAJO del centro de o,
        # hay solapamiento horizontal, y es lo bastante ancho para sostenerlo.
        if (other.top() >= o.y
                and _x_overlap(o, other) > min(o.w, other.w) * 0.3
                and other.w >= o.w * 0.5):
            if other.top() < best_top:
                best, best_top = other, other.top()
    return best


def settle(scene: Scene, ground: float = GROUND) -> dict:
    """Asienta la escena a un estado de reposo plausible: aplica gravedad
    (cada objeto cae hasta tocar su soporte o el suelo) y separa solapamientos
    horizontales entre objetos al mismo nivel. Muta la escena in-place.

    Determinista: procesa de abajo hacia arriba por altura. Devuelve un reporte
    {iters, moved, unstable} para inspeccionabilidad."""
    movibles = [o for o in scene.objects if not _is_floating(o)]
    moved = 0
    iters = 0
    for iters in range(1, _MAX_ITERS + 1):
        changed = False
        # procesar de MENOR y (mas arriba) NO; queremos asentar de abajo->arriba
        # para que los soportes ya esten en su lugar. Orden por bottom desc.
        for o in sorted(movibles, key=lambda o: o.bottom(), reverse=True):
            sup = support_of(scene, o)
            target_bottom = ground if sup is None else sup.top()
            new_y = target_bottom - o.h / 2
            # gravedad: si esta por ENCIMA de su reposo (flotando), cae; si esta
            # hundido dentro del soporte/suelo, sube a la superficie.
            if abs(o.y - new_y) > _EPS:
                o.y = new_y
                moved += 1
                changed = True
        # separacion de colisiones horizontales entre objetos que comparten nivel
        if _resolve_horizontal(movibles):
            changed = True
        if not changed:
            break
    unstable = [o.key() for o in movibles if not is_stable(scene, o)]
    return {"iters": iters, "moved": moved, "unstable": unstable}


def _resolve_horizontal(objs) -> bool:
    """Empuja aparte pares de objetos que se solapan MUCHO en x Y estan al mismo
    nivel vertical (misma fila): evita que dos cosas ocupen el mismo lugar."""
    changed = False
    for i, a in enumerate(objs):
        for b in objs[i + 1:]:
            # mismo nivel: sus rangos verticales se solapan >50% del menor alto
            v_over = min(a.bottom(), b.bottom()) - max(a.top(), b.top())
            if v_over <= min(a.h, b.h) * 0.5:
                continue
            xo = _x_overlap(a, b)
            need = (a.w + b.w) / 2                       # separacion centro-centro deseada
            if xo > 0 and abs(a.x - b.x) < need - _EPS:
                # empujar por densidad: el mas liviano cede mas
                da, db = _density(a), _density(b)
                push = (need - abs(a.x - b.x)) / 2 + _EPS
                if a.x <= b.x:
                    a.x -= push * db / (da + db)
                    b.x += push * da / (da + db)
                else:
                    a.x += push * db / (da + db)
                    b.x -= push * da / (da + db)
                a.x = min(1.0, max(0.0, a.x))
                b.x = min(1.0, max(0.0, b.x))
                changed = True
    return changed


def is_stable(scene: Scene, o) -> bool:
    """True si `o` es estable: descansa en el suelo, o su centro x cae dentro
    del ancho de su soporte (si el centro se sale del soporte, se caeria)."""
    if _is_floating(o):
        return True
    sup = support_of(scene, o)
    if sup is None:
        return abs(o.bottom() - GROUND) < 0.02      # apoyado en el suelo
    return (sup.x - sup.w / 2) <= o.x <= (sup.x + sup.w / 2)


def physics_report(scene: Scene) -> dict:
    """Diagnostico SIN mutar: cuantos objetos flotan (no tocan soporte/suelo),
    cuantos se solapan, cuantos son inestables. El oraculo cero-LLM de la fisica."""
    movibles = [o for o in scene.objects if not _is_floating(o)]
    flotando, solapando, inestables = [], [], []
    for o in movibles:
        sup = support_of(scene, o)
        rest = GROUND if sup is None else sup.top()
        if o.bottom() < rest - 0.02:                # su base esta por encima del reposo
            flotando.append(o.key())
        if not is_stable(scene, o):
            inestables.append(o.key())
    for i, a in enumerate(movibles):
        for b in movibles[i + 1:]:
            v_over = min(a.bottom(), b.bottom()) - max(a.top(), b.top())
            if v_over > min(a.h, b.h) * 0.5 and _x_overlap(a, b) > min(a.w, b.w) * 0.5:
                solapando.append(f"{a.key()}~{b.key()}")
    ok = not flotando and not solapando and not inestables
    return {"plausible": ok, "flotando": flotando, "solapando": solapando,
            "inestables": inestables, "n_movibles": len(movibles)}
