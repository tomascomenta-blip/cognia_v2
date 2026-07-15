from math import gcd


def max_points_on_line(points):
    n = len(points)
    if n == 0:
        return 0
    if n == 1:
        return 1
    best = 1
    for i in range(n):
        # puntos duplicados de i (misma ubicacion) cuentan siempre
        same = 0
        slopes = {}
        base = points[i]
        for j in range(n):
            if j == i:
                continue
            dx = points[j][0] - base[0]
            dy = points[j][1] - base[1]
            if dx == 0 and dy == 0:
                same += 1
                continue
            g = gcd(dx, dy)
            dx //= g
            dy //= g
            # signo canonico: dx > 0, o (dx == 0 y dy > 0)
            if dx < 0 or (dx == 0 and dy < 0):
                dx, dy = -dx, -dy
            key = (dy, dx)
            slopes[key] = slopes.get(key, 0) + 1
        mejor_linea = max(slopes.values()) if slopes else 0
        best = max(best, mejor_linea + same + 1)
    return best
