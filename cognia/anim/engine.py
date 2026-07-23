# -*- coding: utf-8 -*-
"""Motor de animación 2D por keyframes/capas (F5) — 100% determinista.

Filosofía del plan (PLAN_ASSETS_IA.md §C): "interpolar es matemática". El motor NO
usa IA: samplea keyframes con easing, hace forward-kinematics de una jerarquía de
huesos (bones) y compone las capas (slots = sprites atados a un hueso). Formato
inspirado en DragonBones/Spine (huesos -> slots -> timelines), en JSON propio.

Estrategia de runtime: el motor HORNEA (bake) la animación a una tabla de frames
{fps, frames:[[{slot,asset,m:[a,b,c,d,e,f],z,w,h,ax,ay}]]}. El runtime web
(cognia/anim/runtime.js) solo DIBUJA esos frames -> determinismo garantizado y sin
reimplementar la matemática en JS. Autocontenido (Canvas2D, sin PixiJS/CDN) para
respetar la regla offline del generator.

Formato del rig (dict):
  {
    "fps": 30,
    "bones": [{"name","parent"|None,"x","y","rot"(grados),"sx","sy"}],
    "slots": [{"name","bone","asset","x","y","z","w","h","ax","ay"}],  # ax/ay=ancla 0..1
    "animations": {
      "<nombre>": {"duration": segundos, "loop": bool,
                   "tracks": {"<bone>": {"<canal>": [{"t","v","ease"}]}}}
    }
  }
Canales animables por hueso: x, y, rot (grados), sx, sy. El valor del keyframe es
ABSOLUTO (reemplaza el del setup pose para ese canal); si un canal no se anima, se usa
el del setup. Easing por segmento: 'linear','ease-in','ease-out','ease' (smoothstep).
"""
from __future__ import annotations

import math

_CANALES = ("x", "y", "rot", "sx", "sy")


# --- matrices afines 2D (a,b,c,d,e,f): x' = a*x+c*y+e ; y' = b*x+d*y+f
#     (misma convención que canvas.setTransform, para que el runtime la use directo) ---
def mat_trs(x, y, rot_grados, sx, sy):
    r = math.radians(rot_grados)
    cos, sin = math.cos(r), math.sin(r)
    return (sx * cos, sx * sin, -sy * sin, sy * cos, x, y)


def mat_mul(p, c):
    """Composición P∘C (aplica C, luego P)."""
    pa, pb, pc, pd, pe, pf = p
    ca, cb, cc, cd, ce, cf = c
    return (pa * ca + pc * cb, pb * ca + pd * cb,
            pa * cc + pc * cd, pb * cc + pd * cd,
            pa * ce + pc * cf + pe, pb * ce + pd * cf + pf)


def _ease(nombre, p):
    """Curva de easing sobre p in [0,1] -> [0,1]. Determinista."""
    if nombre == "linear" or not nombre:
        return p
    if nombre == "ease-in":
        return p * p
    if nombre == "ease-out":
        return 1 - (1 - p) * (1 - p)
    # 'ease' / smoothstep por defecto
    return p * p * (3 - 2 * p)


def _sample(keys, t, defecto):
    """Valor de un canal (lista de keyframes {t,v,ease}) en tiempo t. Sostiene los
    extremos (antes del primer key = primer valor; después del último = último)."""
    if not keys:
        return defecto
    if t <= keys[0]["t"]:
        return keys[0]["v"]
    if t >= keys[-1]["t"]:
        return keys[-1]["v"]
    for i in range(len(keys) - 1):
        k0, k1 = keys[i], keys[i + 1]
        if k0["t"] <= t <= k1["t"]:
            span = k1["t"] - k0["t"]
            p = 0.0 if span == 0 else (t - k0["t"]) / span
            p = _ease(k1.get("ease", "linear"), p)
            return k0["v"] + (k1["v"] - k0["v"]) * p
    return keys[-1]["v"]


def _tracks_en(anim, bone_name, t):
    """Dict canal->valor animado para un hueso en tiempo t (solo canales con track)."""
    tr = anim.get("tracks", {}).get(bone_name, {})
    return {c: _sample(tr[c], t, None) for c in tr}


def _local(bone, anim, t):
    """Transform local del hueso: setup pose con los canales animados sobrescritos."""
    a = _tracks_en(anim, bone["name"], t)
    x = a.get("x", bone.get("x", 0.0))
    y = a.get("y", bone.get("y", 0.0))
    rot = a.get("rot", bone.get("rot", 0.0))
    sx = a.get("sx", bone.get("sx", 1.0))
    sy = a.get("sy", bone.get("sy", 1.0))
    return mat_trs(x, y, rot, sx, sy)


def _orden_topologico(bones):
    """Huesos ordenados padre-antes-que-hijo (para FK en una pasada)."""
    by_name = {b["name"]: b for b in bones}
    orden, visto = [], set()

    def visita(b):
        if b["name"] in visto:
            return
        p = b.get("parent")
        if p and p in by_name:
            visita(by_name[p])
        visto.add(b["name"])
        orden.append(b)
    for b in bones:
        visita(b)
    return orden


def posar(rig, anim_name, t):
    """Devuelve la lista de capas a dibujar en tiempo t (segundos), ordenadas por z:
    [{slot, asset, m:(a,b,c,d,e,f), z, w, h, ax, ay}]. Determinista."""
    anim = rig["animations"][anim_name]
    dur = anim.get("duration", 1.0)
    if anim.get("loop", True) and dur > 0:
        t = t % dur
    else:
        t = max(0.0, min(t, dur))

    by_name = {b["name"]: b for b in rig["bones"]}
    world = {}
    for b in _orden_topologico(rig["bones"]):
        local = _local(b, anim, t)
        p = b.get("parent")
        world[b["name"]] = mat_mul(world[p], local) if p in world else local

    capas = []
    for s in rig["slots"]:
        wm = world.get(s["bone"], (1, 0, 0, 1, 0, 0))
        # offset del slot dentro del hueso
        m = mat_mul(wm, mat_trs(s.get("x", 0.0), s.get("y", 0.0), 0.0, 1.0, 1.0))
        capas.append({
            "slot": s["name"], "asset": s["asset"],
            "m": [round(v, 5) for v in m], "z": s.get("z", 0),
            "w": s.get("w", 100), "h": s.get("h", 100),
            "ax": s.get("ax", 0.5), "ay": s.get("ay", 0.5),
        })
    capas.sort(key=lambda c: c["z"])
    return capas


def bake(rig, anim_name):
    """Hornea la animación a una tabla de frames que el runtime web reproduce.
    {fps, duration, loop, frames:[[capa,...] por frame]}. Muestreo a fps del rig."""
    fps = rig.get("fps", 30)
    anim = rig["animations"][anim_name]
    dur = anim.get("duration", 1.0)
    n = max(1, int(round(dur * fps)))
    frames = [posar(rig, anim_name, i / fps) for i in range(n)]
    return {"fps": fps, "duration": dur, "loop": anim.get("loop", True),
            "frames": frames}
