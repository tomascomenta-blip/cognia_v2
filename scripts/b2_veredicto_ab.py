"""
b2_veredicto_ab.py — aplica los criterios de PREREG_BON_RONDAS_20260726.md
(enmendado) a las series basefix/bonfix/rondasfix.

    PYTHONUTF8=1 venv312\\Scripts\\python.exe scripts\\b2_veredicto_ab.py

Solo lee los resultados_{basefix,bonfix,rondasfix}N.json preservados; no
corre nada. Los umbrales estan pre-registrados; este script solo los aplica
(imprime tambien segundos por tarea, porque el coste es parte del criterio
del brazo BoN).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DIR = (RAIZ / "cognia" / "program_creator" / "generated_programs"
       / "b2_sistema_real")


def serie(etiqueta: str) -> list[dict]:
    out = []
    for f in sorted(DIR.glob(f"resultados_{etiqueta}[0-9]*.json")):
        j = json.loads(f.read_text(encoding="utf-8"))
        segs = [r.get("segundos", 0) for r in j["sistema_real"].values()]
        out.append({"archivo": f.name, "real": j["real"], "n": j["n_tareas"],
                    "config": j.get("config"),
                    "segundos_total": sum(segs),
                    "fallidas": [t for t, r in j["sistema_real"].items()
                                 if not r.get("aprobado")]})
    return out


def resumen(etiqueta: str) -> tuple[list[int], float, float]:
    s = serie(etiqueta)
    if not s:
        print(f"  {etiqueta}: SIN REPLICAS")
        return [], 0.0, 0.0
    reales = [x["real"] for x in s]
    media = sum(reales) / len(reales)
    seg_tarea = sum(x["segundos_total"] for x in s) / sum(x["n"] for x in s)
    print(f"  {etiqueta}: serie {reales} (media {media:.2f}, min "
          f"{min(reales)}) — {seg_tarea:.0f}s/tarea")
    for x in s:
        print(f"    {x['archivo']}: {x['real']}/{x['n']}  fallidas: "
              f"{x['fallidas']}")
    return reales, media, seg_tarea


def main() -> int:
    print("Series (post-fix de reparacion, commit 0a70f98):\n")
    base, media_base, seg_base = resumen("basefix")
    bon, media_bon, seg_bon = resumen("bonfix")
    ron, media_ron, seg_ron = resumen("rondasfix")
    esc, media_esc, seg_esc = resumen("escalada")

    if not base:
        return 1
    print("\nVeredictos pre-registrados (contra baseline post-fix):")

    def veredicto(nombre, reales, media, extra_kill=False):
        if len(reales) < 3:
            print(f"  {nombre}: n={len(reales)} < 3 — sin veredicto")
            return
        if media >= 5.0 and min(reales) >= 4:
            v = "PASA"
        elif media <= media_base or extra_kill:
            v = "KILL"
        elif media >= 4.5:
            v = "GRIS"
        else:
            v = "KILL (media < 4.5 sin superar el gate)"
        print(f"  {nombre}: {v}  (media {media:.2f} vs baseline "
              f"{media_base:.2f}, min {min(reales)})")

    if bon:
        coste_doble = seg_bon > 2 * seg_base if base else False
        veredicto("BoN k=3", bon, media_bon, extra_kill=coste_doble)
        if base:
            print(f"    coste: {seg_bon:.0f}s/tarea vs {seg_base:.0f} del "
                  f"baseline ({seg_bon / max(seg_base, 1):.2f}x)")
    if ron:
        # Criterio B: PASA si media > baseline y min >= 4; GRIS si mejora
        # con min < 4; KILL si media <= baseline. (Brazo abortado en la 2da
        # enmienda: si hay <3 replicas no se emite veredicto.)
        if len(ron) >= 3:
            if media_ron > media_base and min(ron) >= 4:
                v = "PASA"
            elif media_ron > media_base:
                v = "GRIS (mejora sin estabilizar el minimo)"
            else:
                v = "KILL"
            print(f"  rondas-progreso 5: {v}  (media {media_ron:.2f} vs "
                  f"{media_base:.2f}, min {min(ron)})")
    if esc and len(esc) >= 3:
        # Criterio C (2da enmienda): PASA si media > baseline post-fix y
        # min >= 4; GRIS si media > baseline con min < 4; KILL si no supera.
        if media_esc > media_base and min(esc) >= 4:
            v = "PASA"
        elif media_esc > media_base:
            v = "GRIS (mejora sin estabilizar el minimo)"
        else:
            v = "KILL"
        print(f"  escalada de esfuerzo: {v}  (media {media_esc:.2f} vs "
              f"{media_base:.2f}, min {min(esc)}; {seg_esc:.0f}s/tarea)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
