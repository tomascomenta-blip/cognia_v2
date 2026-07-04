"""
cognia_x/lcd/modeling.py — Operaciones de MODELADO de Blender recreadas como
AI-nativas, sobre la lista de vertices de un poligono (Obj.points, coords
locales [-0.5,0.5]).

Cada op de Blender (Edit Mode / modificadores) se recrea como una funcion PURA
sobre una lista de vertices [[x,y],...] (o un factor sobre el objeto), para que
una IA la invoque via ACCION y componga edicion de figuras de forma verificable.
2D (el analogo 2D de la op 3D), determinista, sin dependencias.

Mapa Blender -> AI-nativa (ver el informe de investigacion):
  subdivide  -> subdivide(points): agrega el punto medio de cada arista.
  bevel      -> bevel(points, amt): corta cada esquina en dos (chaflan).
  extrude    -> extrude_edge(points, i, dx, dy): desplaza una arista creando cara.
  inset      -> inset(points, amt): copia interior escalada (devuelve el borde).
  mirror     -> mirror(points, axis): refleja los vertices.
  spin/ngon  -> ngon(n): poligono regular de n lados (base para cilindros/tuercas).
  subsurf    -> smooth(points, iters): Chaikin (suaviza el contorno).
"""
from __future__ import annotations

import math


def ngon(n: int, r: float = 0.5, rot: float = 0.0) -> list:
    """Poligono regular de n lados (analogo de add mesh circle/cylinder cap).
    Base para hexagonos (lapiz), tuercas, etc. Vertices en coords locales."""
    n = max(3, int(n))
    return [[r * math.cos(rot + 2 * math.pi * i / n),
             r * math.sin(rot + 2 * math.pi * i / n)] for i in range(n)]


def subdivide(points: list, cuts: int = 1) -> list:
    """Subdivide: inserta `cuts` puntos equiespaciados en cada arista (mas
    resolucion sin cambiar la forma). Analogo de Subdivide (Edit Mode)."""
    if len(points) < 2:
        return list(points)
    out = []
    n = len(points)
    for i in range(n):
        a, b = points[i], points[(i + 1) % n]
        out.append([a[0], a[1]])
        for k in range(1, cuts + 1):
            t = k / (cuts + 1)
            out.append([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t])
    return out


def bevel(points: list, amount: float = 0.15) -> list:
    """Bevel (Ctrl+B): reemplaza cada vertice por DOS puntos sobre sus aristas,
    achaflanando la esquina. amount in (0,0.5) = fraccion de la arista."""
    n = len(points)
    if n < 3:
        return list(points)
    amount = max(0.001, min(0.49, amount))
    out = []
    for i in range(n):
        prev, cur, nxt = points[(i - 1) % n], points[i], points[(i + 1) % n]
        p1 = [cur[0] + (prev[0] - cur[0]) * amount, cur[1] + (prev[1] - cur[1]) * amount]
        p2 = [cur[0] + (nxt[0] - cur[0]) * amount, cur[1] + (nxt[1] - cur[1]) * amount]
        out.append(p1)
        out.append(p2)
    return out


def extrude_edge(points: list, i: int, dx: float, dy: float) -> list:
    """Extrude (E) de una arista i->i+1: duplica sus 2 vertices desplazados
    (dx,dy) e inserta la cara nueva. Analogo 2D del extrude de Blender."""
    n = len(points)
    if n < 2:
        return list(points)
    i = i % n
    a, b = points[i], points[(i + 1) % n]
    na = [a[0] + dx, a[1] + dy]
    nb = [b[0] + dx, b[1] + dy]
    # insertar na,nb entre a y b (recorriendo el contorno por afuera)
    out = points[:i + 1] + [na, nb] + points[i + 1:]
    return out


def inset(points: list, amount: float = 0.2) -> list:
    """Inset (I): contorno interior escalado hacia el centroide. amount = cuanto
    se encoge (0..1). Devuelve el borde interior (para caras concentricas)."""
    if not points:
        return []
    cx = sum(p[0] for p in points) / len(points)
    cy = sum(p[1] for p in points) / len(points)
    s = max(0.0, min(1.0, 1.0 - amount))
    return [[cx + (p[0] - cx) * s, cy + (p[1] - cy) * s] for p in points]


def mirror(points: list, axis: str = "x") -> list:
    """Mirror modifier: refleja los vertices sobre el eje ('x' invierte x)."""
    if axis == "x":
        return [[-p[0], p[1]] for p in points]
    if axis == "y":
        return [[p[0], -p[1]] for p in points]
    return list(points)


def smooth(points: list, iters: int = 1) -> list:
    """Subdivision Surface (subsurf) / suavizado: Chaikin corner-cutting, que
    redondea el contorno acercandolo a una curva (analogo del subsurf de Blender
    en 2D). iters mas altos = mas suave."""
    pts = list(points)
    for _ in range(max(1, iters)):
        n = len(pts)
        if n < 3:
            break
        out = []
        for i in range(n):
            a, b = pts[i], pts[(i + 1) % n]
            out.append([0.75 * a[0] + 0.25 * b[0], 0.75 * a[1] + 0.25 * b[1]])
            out.append([0.25 * a[0] + 0.75 * b[0], 0.25 * a[1] + 0.75 * b[1]])
        pts = out
    return pts


def array(obj, n: int, dx: float, dy: float) -> list:
    """Array modifier: N copias de un objeto con offset (dx,dy) acumulado.
    Devuelve una lista de Obj (copias); el caller las agrega a la escena."""
    import copy
    n = max(1, int(n))
    out = []
    for k in range(n):
        c = copy.deepcopy(obj)
        c.id = ""
        c.x = min(1.0, max(0.0, obj.x + dx * k))
        c.y = min(1.0, max(0.0, obj.y + dy * k))
        out.append(c)
    return out
